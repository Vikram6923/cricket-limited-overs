"""Auction game: an IPL-style player auction with retentions and Right to Match, then a league.

Rules (the IPL's 2025 mega auction):
- purse Rs 120 crore; squads of 18-25 with at most 8 overseas players (XIs keep the league's limit, 4 in the IPL)
- retentions first: up to 6 players from the team's previous squad, at most 5 capped (they cost 18, 14, 11, 18 and
  14 crore, in that order) and 2 uncapped (4 crore each); each unused slot is a Right to Match (RTM) card
- players come up in sets (marquee, then capped batters / all-rounders / keepers / pace / spin in turn, then the
  uncapped) at base prices from 2 crore down to 30 lakh; bids rise by 5 lakh below 1 crore, 10 lakh to 2 crore,
  20 lakh to 5 crore and 25 lakh above
- RTM: when a player from a team's previous squad is sold to another team, the old team may use a card; the buyer
  then gets one final raise, and the old team matches it or lets him go (the raise stands either way)
- unsold players come back in an accelerated round; teams still short of 18 then fill up at 30 lakh each

Pools: "season" = everyone who played one real league season, with that season's franchises, retention from the
season before, career ratings and the league's conditions (as in League Season); "years" = a period's players as
in the fantasy draft (rated on those years), overseas = not from the home nation, retention from the last auction.

Computer teams (game AI on the engine's own numbers, not real franchises' habits): a player is worth what he adds
to the team's best XI (1 keeper, 5 bowlers, 5 others, plus one more in Impact Player seasons; empty places filled at replacement level, the level of the
best player who would not make any XI) in runs per match (engine.selection.value_parts), converted to money at the
market rate: the money the teams have left over the runs above replacement still on offer for their open XI places.
A team with more money per open place than the others bids more freely. Bids are capped so the team can still
fill its squad. A small random spread per team and player (seeded) makes auctions differ.

A library: Auction runs as a generator that stops at each decision of the user's team (retentions, each bid,
Right to Match) and is resumed by act(); with no user team the whole auction runs at once.
"""
from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, field
from functools import lru_cache

from .data import DATA, FORMATS, baseline, player
from .selection import bowler_mask, value_parts

PURSE = 12000                        # lakh (Rs 120 crore)
SQUAD_MIN, SQUAD_MAX, OVERSEAS_MAX = 18, 25, 8
RETAIN_MAX, RETAIN_CAPPED, RETAIN_UNCAPPED = 6, 5, 2
CAPPED_COST = (1800, 1400, 1100, 1800, 1400)
UNCAPPED_COST = 400
CAPPED_BASES = (200, 150, 125, 100, 75)
UNCAPPED_BASES = (50, 40, 30)
MIN_PRICE = 30
MARQUEE, SET_SIZE = 12, 8
SPEND = 0.9                          # share of the free purse the market rate expects to spend on XI players
NOISE = 0.12                         # spread of a team's valuation (log scale)
ROLES = ("Batter", "All-rounder", "WK", "Pace", "Spin")
SET_LABEL = {"Batter": "batters", "All-rounder": "all-rounders", "WK": "keepers", "Pace": "fast bowlers",
             "Spin": "spinners"}


def step(price: int) -> int:
    """The next bid above `price` (lakh)."""
    return price + (5 if price < 100 else 10 if price < 200 else 20 if price < 500 else 25)


def money(lakh: int | float) -> str:
    return f"Rs {lakh / 100:.2f} cr" if lakh >= 100 else f"Rs {lakh:.0f} lakh"


@dataclass
class Lot:
    """A player in the auction."""
    id: str
    name: str
    team: str                 # nation (or main team) shown
    role: str
    value: float              # runs value per match (batting + bowling) relative to an average player
    bat: float
    bowl: float
    keeper: bool
    bowler: bool
    overseas: bool
    capped: bool
    p: object = None          # engine Player
    var: float = 0.0          # runs above replacement
    est: int = 0              # expected price (lakh)
    base: int = MIN_PRICE
    set: str = ""
    prev: str | None = None   # team of the previous squad (retention / RTM)
    status: str = "pool"      # pool / retained / sold / unsold
    buyer: str | None = None
    price: int | None = None
    ref: dict = field(default_factory=dict)

    def row(self) -> dict:
        b, w = self.ref.get("bat") or {}, self.ref.get("bowl") or {}
        return {"id": self.id, "name": self.name, "team": self.team, "role": self.role, "value": round(self.value, 1),
                "overseas": self.overseas, "capped": self.capped, "base": self.base, "est": self.est, "set": self.set,
                "prev": self.prev, "status": self.status, "buyer": self.buyer, "price": self.price,
                "bat_avg": b.get("avg"), "bat_sr": b.get("sr"),
                "econ": w.get("econ") if self.bowler else None, "bowl_avg": w.get("avg") if self.bowler else None}


# ------------------------------------------------------------------------------------------------ pools

@lru_cache(maxsize=None)
def first_cap() -> dict:
    """pid -> first year of international cricket (T20I or ODI; Afghanistan from Wikipedia)."""
    out: dict = {}
    for f in ("players_t20.json", "players_odi.json"):
        path = DATA / "raw_stats" / f
        if path.exists():
            for pid, r in json.loads(path.read_text(encoding="utf-8")).items():
                ys = [int(y) for y in (r.get("by_year") or {})]
                if ys:
                    out[pid] = min(min(ys), out.get(pid, 9999))
    path = DATA / "raw_stats" / "afghanistan_players.json"
    if path.exists():
        for r in json.loads(path.read_text(encoding="utf-8")):
            if r.get("cricsheet_id"):
                out.setdefault(r["cricsheet_id"], 0)
    return out


def _lot(pid: str, p, fmt: str, base: dict, team: str, overseas: bool, capped: bool) -> Lot:
    bat, bowl = value_parts(p, fmt, base)
    bowler = bowler_mask([p], fmt)[0]
    if p.keeper:
        role = "WK"
    elif bowler and bat > 0 and bowl > 0:
        role = "All-rounder"
    elif bowler:
        role = "Spin" if p.bowl_type == "spin" else "Pace"
    else:
        role = "Batter"
    p.overseas = overseas
    return Lot(pid, p.name, team, role, bat + bowl, bat, bowl, p.keeper, bowler, overseas, capped, p, ref=dict(p.ref))


def league_data() -> dict:
    return json.loads((DATA / "league_seasons.json").read_text(encoding="utf-8"))


def season_pool(league: str, season: str) -> dict:
    """Everyone who played a league season: lots, the franchises (with home grounds), the previous season's squads."""
    lg = league_data()[league]
    seasons = lg["seasons"]                                      # newest first
    i = next(k for k, s in enumerate(seasons) if s["season"] == season)
    s = seasons[i]
    base = baseline("t20", league, s["year"])
    os_ = {pid for t in s["teams"] for pid in t["overseas"]}
    team_of = {pid: t["franchise"] for t in s["teams"] for pid in t["players"]}
    caps = first_cap()
    lots = []
    for pid in team_of:
        p = player("t20", pid)
        lots.append(_lot(pid, p, "t20", base, p.team or "", pid in os_, caps.get(pid, 9999) < s["year"]))
    prev = {}
    if i + 1 < len(seasons):
        prev = {t["franchise"]: list(t["players"]) for t in seasons[i + 1]["teams"]}
    return {"fmt": "t20", "comp": league, "year": s["year"], "label": f"{lg['label']} {s['season']}",
            "lots": lots, "teams": [t["franchise"] for t in s["teams"]],
            "homes": {t["franchise"]: t.get("home_venue") for t in s["teams"]},
            "max_overseas": s["max_overseas"], "prev": prev, "prev_label": seasons[i + 1]["season"] if prev else None}


def years_pool(fmt: str, y1: int, y2: int, teams: list[str], source: str = "full", home: str | None = None,
               years_mode: str = "blend", min_matches: int = 10) -> dict:
    """A period's players, as in the fantasy draft, rated on those years; the best teams x 30 are auctioned.
    home: the nation whose players are not overseas (None = no overseas limits); the pool then also takes enough
    of its players to fill every squad."""
    from .draft import _appearances
    base = baseline(fmt, FORMATS[fmt]["intl"], y2)
    caps = first_cap()
    lots = []
    for pid, (m, nation) in _appearances(fmt, y1, y2, source).items():
        if m < min_matches:
            continue
        p = player(fmt, pid, years=(y1, y2), years_mode=years_mode)
        if not (p.rated_bat or p.rated_bowl):
            continue
        lots.append(_lot(pid, p, fmt, base, nation, bool(home) and nation != home, caps.get(pid, 9999) <= y2))
    lots.sort(key=lambda x: -x.value)
    k = len(teams)
    out = lots[:30 * k]
    if home:
        need = (SQUAD_MIN - OVERSEAS_MAX + 2) * k - sum(not x.overseas for x in out)   # if there are that many
        out += [x for x in lots[30 * k:] if not x.overseas][:max(0, need)]
    return {"fmt": fmt, "comp": None, "year": None, "label": f"Players from {y1}-{y2}", "lots": out,
            "teams": list(teams), "homes": {}, "max_overseas": 4 if home else None, "prev": {}, "prev_label": None,
            "years": [y1, y2], "years_mode": years_mode}


# ------------------------------------------------------------------------------------------------ auction

class Auction:
    def __init__(self, pool: dict, user: str | None = None, prev: dict | None = None, seed: int | None = None):
        self.fmt, self.comp, self.year, self.label = pool["fmt"], pool["comp"], pool["year"], pool["label"]
        self.teams = list(pool["teams"])
        if len(self.teams) < 2:
            raise ValueError("An auction needs at least 2 teams.")
        if user is not None and user not in self.teams:
            raise ValueError("Your team must be one of the teams.")
        self.user, self.homes, self.xi_overseas = user, pool["homes"], pool["max_overseas"]
        # Impact Player seasons: a 12th man plays, so one more place is worth paying for
        self.xi_n = 12 if self.comp == "ipl" and (self.year or 0) >= 2023 else 11
        self.years, self.years_mode = pool.get("years"), pool.get("years_mode", "blend")
        self.seed = seed if seed is not None else random.randrange(1 << 30)
        self.rng = random.Random(self.seed)
        self.lots = {x.id: x for x in pool["lots"]}
        self.squad_min = min(SQUAD_MIN, int(0.85 * len(self.lots) / len(self.teams)))
        if self.squad_min < 11:
            raise ValueError(f"Only {len(self.lots)} players for {len(self.teams)} teams: not enough for squads.")
        self.overseas_max = OVERSEAS_MAX
        self.news: list[str] = []
        home = sum(not x.overseas for x in self.lots.values())
        if any(x.overseas for x in self.lots.values()) and home < (self.squad_min - OVERSEAS_MAX) * len(self.teams):
            for x in self.lots.values():         # too few home players to fill the squads: no overseas limits
                x.overseas = x.p.overseas = False
            self.xi_overseas = None
            self.news.append(f"Only {home} home players in the pool: overseas limits are off.")
        self.purse = {t: PURSE for t in self.teams}
        self.squad: dict[str, list[str]] = {t: [] for t in self.teams}
        self.retained: dict[str, list[str]] = {t: [] for t in self.teams}
        self.rtm = {t: 0 for t in self.teams}
        prev = pool["prev"] if prev is None else prev
        for t, ids in prev.items():
            for pid in ids:
                if t in self.purse and pid in self.lots:
                    self.lots[pid].prev = t
        self.has_prev = any(x.prev for x in self.lots.values())
        self._replacement()
        self.lam0 = self._lambda()
        for x in self.lots.values():
            x.est = int(MIN_PRICE + self.lam0 * x.var)
            bases = CAPPED_BASES if x.capped else UNCAPPED_BASES
            x.base = next((b for b in bases if x.est >= 4 * b), bases[-1])
        self.sets: list[tuple[str, list[str]]] = []
        self.set_no = -1
        self.lot: dict | None = None
        self.sales: list[dict] = []
        self.phase = "retain"
        self.user_auto: str | None = None      # None (asked), "set", "all": the computer bids for the user
        self.question: dict | None = None
        self._gen = self._flow()
        self._advance(None)

    # ---------------------------------------------------------------- valuation
    def _replacement(self) -> None:
        """Replacement levels: the best keeper / bowler / other who would not make any of the k XIs."""
        k = len(self.teams)
        xs = sorted(self.lots.values(), key=lambda x: -x.value)
        keepers = [x for x in xs if x.keeper]
        used = set(x.id for x in keepers[:k])
        bowlers = [x for x in xs if x.bowler and x.id not in used]
        used |= set(x.id for x in bowlers[:5 * k])
        n_other = (self.xi_n - 6) * k
        others = [x for x in xs if x.id not in used]
        lvl = lambda lst, n: lst[n].value if len(lst) > n else (lst[-1].value if lst else 0.0)
        self.repl = {"keeper": lvl(keepers, k), "bowler": lvl(bowlers, 5 * k), "other": lvl(others, n_other)}
        for x in xs:
            r = [x.value - self.repl["other"]]
            if x.keeper:
                r.append(x.value - self.repl["keeper"])
            if x.bowler:
                r.append(x.value - self.repl["bowler"])
            x.var = max(0.0, max(r))

    def _free(self, t: str, buying: int = 0) -> int:
        """Purse the team can spend now, keeping 30 lakh for each place still needed to reach the minimum squad."""
        return self.purse[t] - max(0, self.squad_min - len(self.squad[t]) - buying) * MIN_PRICE

    def _xi(self, ids: list[str]) -> tuple[float, int]:
        """(value of the best XI, real players in it) with empty places at replacement level (greedy)."""
        xs = sorted((self.lots[i] for i in ids), key=lambda x: -x.value)
        chosen, os_, total = set(), 0, 0.0
        ok = lambda x: x.id not in chosen and (not x.overseas or self.xi_overseas is None or os_ < self.xi_overseas)
        for slot, n in (("keeper", 1), ("bowler", 5), ("other", self.xi_n - 6)):
            got = 0
            for x in xs:
                if got >= n:
                    break
                if ok(x) and (slot == "other" or (x.keeper if slot == "keeper" else x.bowler)) \
                        and x.value > self.repl[slot]:
                    chosen.add(x.id)
                    os_ += x.overseas
                    total += x.value
                    got += 1
            total += (n - got) * self.repl[slot]
        return total, len(chosen)

    def _lambda(self) -> float:
        """Market rate (lakh per run per match): free money over the runs above replacement left for open places."""
        free = sum(max(0, self._free(t)) for t in self.teams)
        open_ = sum(self.xi_n - self._xi(self.squad[t])[1] for t in self.teams)
        left = sorted((x.var for x in self.lots.values() if x.status == "pool"), reverse=True)[:max(open_, 1)]
        return SPEND * free / max(sum(left), 1.0)

    def _rate(self, t: str) -> float:
        """The team's money rate: the market rate scaled by its money per open place against the others'."""
        free = {u: max(0, self._free(u)) for u in self.teams}
        open_ = {u: max(self.xi_n - self._xi(self.squad[u])[1], 0.5) for u in self.teams}
        avg = sum(free.values()) / sum(open_.values())
        r = (free[t] / open_[t]) / avg if avg > 0 else 1.0
        return self.lam * min(2.0, max(0.5, r))

    def can_buy(self, t: str, x: Lot) -> bool:
        return (len(self.squad[t]) < SQUAD_MAX
                and (not x.overseas or sum(self.lots[i].overseas for i in self.squad[t]) < self.overseas_max))

    def worth(self, t: str, x: Lot, noise: bool = True) -> int:
        """The most team t would pay for x (lakh), within what it can afford."""
        if not self.can_buy(t, x):
            return 0
        gain = self._xi(self.squad[t] + [x.id])[0] - self._xi(self.squad[t])[0]
        v = self._rate(t) * gain + (MIN_PRICE if len(self.squad[t]) < self.squad_min else 0)
        if noise:
            v *= math.exp(random.Random(f"{self.seed}|{t}|{x.id}").gauss(0.0, NOISE))
        return int(min(v, self._free(t, 1)))

    # ---------------------------------------------------------------- flow
    def _advance(self, answer) -> None:
        try:
            self.question = self._gen.send(answer) if self.question is not None else next(self._gen)
        except StopIteration:
            self.question = None

    def act(self, answer: dict) -> None:
        """The user's answer to the open question (validated here; ValueError if it is not allowed)."""
        q = self.question
        if not q:
            raise ValueError("Nothing to decide.")
        k = q["kind"]
        if k == "retain":
            ids = list(dict.fromkeys(answer.get("ids") or []))
            err = self.retain_error(self.user, ids)
            if err:
                raise ValueError(err)
            answer = {"ids": ids}
        elif k == "bid":
            if answer.get("skip") in ("set", "all"):
                self.user_auto = answer["skip"]
            elif answer.get("max") is not None:
                m = int(answer["max"])
                if m < q["next"]:
                    raise ValueError(f"Your limit must be at least {money(q['next'])}.")
                answer = {"max": min(m, q["cap"])}
            elif answer.get("bid") and q["next"] > q["cap"]:
                raise ValueError("You cannot afford that bid.")
        elif k == "rtm_raise":
            amt = int(answer.get("amount") or q["price"])
            if not q["price"] <= amt <= q["cap"]:
                raise ValueError(f"Raise to between {money(q['price'])} and {money(q['cap'])}.")
            answer = {"amount": amt}
        self._advance(answer)

    def auto(self, scope: str = "all") -> None:
        """Hand the user's bidding to the computer (to the end of the set or the auction)."""
        self.user_auto = scope
        if self.question and self.question["kind"] != "retain":
            self._advance({"auto": True})

    @property
    def done(self) -> bool:
        return self.phase == "done"

    def _user_asks(self) -> bool:
        return self.user is not None and self.user_auto is None

    def _flow(self):
        # retentions (and RTM cards)
        self.phase = "retain"
        for t in self.teams:
            if t != self.user:
                self._retain(t, self.suggest_retain(t))
        if self.user:
            cands = self.retain_candidates(self.user)
            if cands:
                a = yield {"kind": "retain", "candidates": [self.lots[i].row() for i in cands],
                           "suggested": self.suggest_retain(self.user)}
                ids = a.get("ids", []) if isinstance(a, dict) else self.suggest_retain(self.user)
            else:
                ids = []
            self._retain(self.user, ids)
        # sets
        self.phase = "auction"
        self._make_sets()
        for n, (name, ids) in enumerate(self.sets):
            self.set_no = n
            if self.user_auto == "set":
                self.user_auto = None
            for pid in ids:
                yield from self._sell(pid, name)
        # accelerated round
        self.phase = "accelerated"
        if self.user_auto == "set":
            self.user_auto = None
        again = sorted((x for x in self.lots.values() if x.status == "unsold"), key=lambda x: -x.est)
        name = "Accelerated round"
        self.sets.append((name, [x.id for x in again]))
        self.set_no = len(self.sets) - 1
        for x in again:
            yield from self._sell(x.id, name)
        # fill up
        for t in self.teams:
            while len(self.squad[t]) < self.squad_min:
                left = [x for x in self.lots.values() if x.status in ("unsold", "pool") and self.can_buy(t, x)]
                if not left:
                    break
                gain = lambda x: self._xi(self.squad[t] + [x.id])[0] + 0.01 * x.value
                x = max(left, key=gain)
                self._assign(x, t, min(MIN_PRICE, self.purse[t]), "fill")
        self.lot = None
        self.phase = "done"

    # ---------------------------------------------------------------- retention
    def retain_candidates(self, t: str) -> list[str]:
        return sorted((x.id for x in self.lots.values() if x.prev == t and x.status == "pool"),
                      key=lambda i: -self.lots[i].est)

    @staticmethod
    def retain_cost(capped: int, uncapped: int) -> int:
        return sum(CAPPED_COST[:capped]) + UNCAPPED_COST * uncapped

    def retain_error(self, t: str, ids: list[str]) -> str | None:
        cands = set(self.retain_candidates(t))
        if any(i not in cands for i in ids):
            return "You can only retain players from your previous squad."
        c = sum(self.lots[i].capped for i in ids)
        u = len(ids) - c
        if len(ids) > RETAIN_MAX or c > RETAIN_CAPPED or u > RETAIN_UNCAPPED:
            return f"Retain at most {RETAIN_MAX} players: {RETAIN_CAPPED} capped and {RETAIN_UNCAPPED} uncapped."
        if sum(self.lots[i].overseas for i in ids) > OVERSEAS_MAX:
            return "Too many overseas players."
        return None

    def suggest_retain(self, t: str) -> list[str]:
        """Keep a player while his expected auction price is above the cost of the next retention slot."""
        out, c, u = [], 0, 0
        for i in self.retain_candidates(t):
            x = self.lots[i]
            if len(out) >= RETAIN_MAX:
                break
            if x.capped and c < RETAIN_CAPPED and x.est >= CAPPED_COST[c]:
                out.append(i)
                c += 1
            elif not x.capped and u < RETAIN_UNCAPPED and x.est >= UNCAPPED_COST:
                out.append(i)
                u += 1
        return out

    def _retain(self, t: str, ids: list[str]) -> None:
        c = u = 0
        for i in ids:
            x = self.lots[i]
            cost = CAPPED_COST[c] if x.capped else UNCAPPED_COST
            c, u = c + x.capped, u + (not x.capped)
            self.purse[t] -= cost
            self.squad[t].append(i)
            self.retained[t].append(i)
            x.status, x.buyer, x.price = "retained", t, cost
        if any(x.prev == t for x in self.lots.values()):
            self.rtm[t] = RETAIN_MAX - len(ids)

    # ---------------------------------------------------------------- sets
    def _make_sets(self) -> None:
        self.lam = self._lambda()
        left = sorted((x for x in self.lots.values() if x.status == "pool"), key=lambda x: -x.est)
        capped = [x for x in left if x.capped]
        marquee = capped[:MARQUEE]
        sets = [(f"Marquee {k // 6 + 1}", [x.id for x in marquee[k:k + 6]]) for k in range(0, len(marquee), 6)]
        for cap, label in ((True, "Capped"), (False, "Uncapped")):
            by = {r: [x for x in left if x.capped == cap and x not in marquee and x.role == r] for r in ROLES}
            rnd = 0
            while any(by.values()):
                rnd += 1
                for r in ROLES:
                    chunk, by[r] = by[r][:SET_SIZE], by[r][SET_SIZE:]
                    if chunk:
                        sets.append((f"{label} {SET_LABEL[r]} {rnd}", [x.id for x in chunk]))
        for _, ids in sets:
            self.rng.shuffle(ids)
            for i in ids:
                self.lots[i].set = _
        self.sets = sets

    # ---------------------------------------------------------------- one player
    def _assign(self, x: Lot, t: str, price: int, how: str) -> None:
        self.purse[t] -= price
        self.squad[t].append(x.id)
        x.status, x.buyer, x.price = "sold", t, price
        self.sales.append({"id": x.id, "name": x.name, "team": t, "price": price, "how": how, "role": x.role})

    def _sell(self, pid: str, set_name: str):
        x = self.lots[pid]
        self.lam = self._lambda()
        w = {t: self.worth(t, x) for t in self.teams}
        lot = self.lot = {"id": pid, "set": set_name, "price": None, "leader": None, "log": [], "passed": [],
                          "user_max": None}
        user_mode = "ask" if self.user and self.can_buy(self.user, x) else "out"
        while True:
            price, leader = lot["price"], lot["leader"]
            nxt = x.base if leader is None else step(price)
            if self.user and user_mode == "ask" and not self._user_asks():
                user_mode = "auto"
            if user_mode == "auto":
                w[self.user] = self.worth(self.user, x)
            elif user_mode == "max":
                w[self.user] = min(lot["user_max"], self._free(self.user, 1))
            bidders = [t for t in self.teams if t != leader and w[t] >= nxt
                       and (t != self.user or user_mode in ("auto", "max"))]
            if user_mode == "ask" and leader != self.user and nxt <= self._free(self.user, 1) \
                    and not (leader is None and bidders):
                a = yield self._bid_question(x, nxt)
                a = a or {}
                if a.get("bid"):
                    lot["price"], lot["leader"] = nxt, self.user
                    lot["log"].append({"team": self.user, "price": nxt})
                elif a.get("max") is not None:
                    user_mode, lot["user_max"] = "max", a["max"]
                elif a.get("auto") or a.get("skip"):
                    user_mode = "auto"
                else:
                    user_mode = "out"
                    lot["passed"].append(self.user)
                continue
            if not bidders:
                break
            t = self.rng.choice(bidders)
            lot["price"], lot["leader"] = nxt, t
            lot["log"].append({"team": t, "price": nxt})
        if lot["leader"] is None:
            x.status = "unsold"
            self.sales.append({"id": x.id, "name": x.name, "team": None, "price": None, "how": "unsold",
                               "role": x.role})
            return
        buyer, price = lot["leader"], lot["price"]
        holder = x.prev
        if holder and holder != buyer and self.rtm.get(holder, 0) > 0 and self.can_buy(holder, x) \
                and price <= self._free(holder, 1):
            buyer, price = yield from self._rtm(x, holder, buyer, price)
        self._assign(x, buyer, price, "rtm" if buyer == holder else "bid")

    def _rtm(self, x: Lot, holder: str, buyer: str, price: int):
        """Right to Match: the old team may match; the buyer gets one last raise first."""
        ask_h = holder == self.user and self._user_asks()
        if ask_h:
            a = yield {"kind": "rtm_use", "player": x.row(), "buyer": buyer, "price": price,
                       "advice": self.worth(holder, x, noise=False), "cards": self.rtm[holder]}
            a = a or {}
            use = self.worth(holder, x) >= price if a.get("auto") else bool(a.get("yes"))
        else:
            use = self.worth(holder, x) >= price
        if not use:
            return buyer, price
        self.lot["log"].append({"team": holder, "price": price, "rtm": True})
        cap_b = max(price, self._free(buyer, 1))
        new = None
        if buyer == self.user and self._user_asks():
            a = yield {"kind": "rtm_raise", "player": x.row(), "holder": holder, "price": price,
                       "cap": cap_b, "advice": self.worth(buyer, x, noise=False)}
            a = a or {}
            if not a.get("auto"):
                new = int(a.get("amount") or price)
        if new is None:                       # the computer's raise: half way to what he is worth to the buyer
            wb = min(self.worth(buyer, x), cap_b)
            new = price
            while step(new) <= wb and new < price + (wb - price) // 2:
                new = step(new)
        if new > price:
            self.lot["log"].append({"team": buyer, "price": new, "raise": True})
        if new > self._free(holder, 1):
            match = False
        elif ask_h and new > price:
            a = yield {"kind": "rtm_match", "player": x.row(), "buyer": buyer, "price": new,
                       "advice": self.worth(holder, x, noise=False)}
            a = a or {}
            match = self.worth(holder, x) >= new if a.get("auto") else bool(a.get("yes"))
        elif ask_h:
            match = True
        else:
            match = self.worth(holder, x) >= new
        if match:
            self.rtm[holder] -= 1
            return holder, new
        return buyer, new

    def _bid_question(self, x: Lot, nxt: int) -> dict:
        lot = self.lot
        return {"kind": "bid", "player": x.row(), "price": lot["price"], "leader": lot["leader"], "next": nxt,
                "cap": self._free(self.user, 1), "advice": self.worth(self.user, x, noise=False)}

    # ---------------------------------------------------------------- output
    def team_specs(self) -> list[dict]:
        out = []
        for t in self.teams:
            sp = {"name": t, "squad": list(self.squad[t]),
                  "overseas": [i for i in self.squad[t] if self.lots[i].overseas], "max_overseas": self.xi_overseas}
            if self.years:
                sp["years"], sp["years_mode"] = list(self.years), self.years_mode
            out.append(sp)
        return out

    def board(self) -> dict:
        return {t: [{"id": i, "name": self.lots[i].name, "role": self.lots[i].role, "price": self.lots[i].price,
                     "overseas": self.lots[i].overseas, "retained": i in self.retained[t]} for i in self.squad[t]]
                for t in self.teams}

    def state(self) -> dict:
        lot = None
        if self.lot:
            x = self.lots[self.lot["id"]]
            lot = {**{k: v for k, v in self.lot.items() if k != "passed"}, "player": x.row()}
        sold = [s for s in self.sales if s["team"]]
        return {"label": self.label, "fmt": self.fmt, "comp": self.comp, "year": self.year, "teams": self.teams,
                "user": self.user, "phase": self.phase,
                "done": self.done, "purse": self.purse, "rtm": self.rtm, "squad_min": self.squad_min,
                "squad_max": SQUAD_MAX, "overseas_max": OVERSEAS_MAX, "xi_overseas": self.xi_overseas,
                "board": self.board(), "question": self.question, "lot": lot, "user_auto": self.user_auto,
                "set_no": self.set_no, "sets": [{"name": n, "n": len(ids)} for n, ids in self.sets],
                "upcoming": [self.lots[i].name for i in (self.sets[self.set_no][1] if 0 <= self.set_no < len(self.sets) else [])
                             if self.lots[i].status == "pool" and i != (self.lot or {}).get("id")],
                "sales": self.sales[-12:][::-1], "n_sold": len(sold), "spent": sum(s["price"] for s in sold),
                "news": self.news, "has_prev": self.has_prev}

    def summary(self) -> dict:
        """For the results page: squads with prices, purse left, the top buys."""
        top = sorted((x for x in self.lots.values() if x.price is not None), key=lambda x: -x.price)[:15]
        return {"label": self.label, "user": self.user, "teams": self.teams, "board": self.board(),
                "purse": self.purse, "top": [{"name": x.name, "team": x.buyer, "price": x.price,
                                              "retained": x.status == "retained"} for x in top]}
