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
- accelerated round: every team names unsold players it wants back (the computer: those worth their base price
  to it); the named players are auctioned again, and teams still short of 18 then fill up at 30 lakh each

Mini auctions (the IPL's auctions between mega auctions, e.g. December 2023 and 2025; also the career mode,
engine/career.py): pool["kept"] = {team: {player: contract price, or None: unknown}}. Unknown contracts are the
players' expected prices, scaled down where a squad would cost more than 95% of the purse. Instead of
retentions each team releases the players it no longer wants and keeps any number of the rest at their contract
prices, which come off the Rs 120 crore purse; a kept squad has at most 25 players and 8 overseas. The computer
releases a player whose expected auction price is below RELEASE x his contract (then the worst value for money
while it keeps too many). The released players join the auction pool. No Right to Match cards and no marquee set.
An overseas player bought for more than FEE_CAP is paid FEE_CAP (the rest goes to the BCCI), but the whole price
comes off the buyer's purse; Lot.fee is what he is paid, and his contract at the next mini auction.

Pools: "season" = everyone who played one real league season, with that season's franchises, retention from the
season before, career ratings and the league's conditions (as in League Season); "years" = a period's players as
in the fantasy draft (rated on those years), overseas = not from the home nation, retention from the last auction.

Computer teams (game AI on the engine's own numbers, not real franchises' habits): a player is worth what he adds
to the team's best XI (1 keeper, 5 bowlers, 5 others, plus one more in Impact Player seasons; empty places filled at replacement level, the level of the
best player who would not make any XI) in runs per match (engine.selection.value_parts), converted to money at the
market rate: the money the teams have left over the runs above replacement still on offer for their open XI places.
A team with more money per open place than the others bids more freely. Bids are capped so the team can still
fill its squad. A small random spread per team and player (seeded) makes auctions differ.
Expected prices: the market rate x runs above replacement x the expected second-highest of the teams' random
spreads (a lot sells at about the second-highest valuation), capped at what the second-richest team can spend;
set before retentions (for retention / release choices) and again once they are done.

A library: Auction runs as a generator that stops at each decision of the user's team (retentions, each bid,
Right to Match, nominations for the accelerated round) and is resumed by act(); with no user team the whole auction
runs at once. The user's team bids in one of four ways (user_auto): asked about every player (None), the computer
for the rest of the set or auction ("set" / "all"), or by the wishlist ("wish": a top bid per player, or "ask me";
everyone else is passed, with an optional pause before each set to change the list).

After the auction, report() gives each squad's strength (its best XI's runs per match), spend, best and worst
buys, and a predicted league table from a win chance fitted on simulated matches (engine/fit/fit_auction.py).
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
RELEASE = 0.75                       # mini auction: release a player expected to fetch less than this x his contract
FEE_CAP = 1800                       # mini auction: most an overseas player is paid (the top retention price)
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
    contract: int | None = None  # mini auction: his current contract price (lakh)
    fee: int | None = None       # mini auction: what an overseas player bought above FEE_CAP is paid
    status: str = "pool"      # pool / retained / sold / unsold
    buyer: str | None = None
    price: int | None = None
    ref: dict = field(default_factory=dict)

    def row(self) -> dict:
        b, w = self.ref.get("bat") or {}, self.ref.get("bowl") or {}
        return {"id": self.id, "name": self.name, "team": self.team, "role": self.role, "value": round(self.value, 1),
                "overseas": self.overseas, "capped": self.capped, "base": self.base, "est": self.est, "set": self.set,
                "prev": self.prev, "contract": self.contract, "fee": self.fee, "status": self.status, "buyer": self.buyer, "price": self.price,
                "bat_avg": b.get("avg"), "bat_sr": b.get("sr"),
                "econ": w.get("econ") if self.bowler else None, "bowl_avg": w.get("avg") if self.bowler else None}


@lru_cache(maxsize=None)
def second_best(k: int, sigma: float) -> float:
    """E[exp(Z)] for Z the second-highest of k normal(0, sigma) draws (k >= 2), by quadrature."""
    out = 0.0
    for i in range(-800, 801):
        z = i / 100
        cdf = 0.5 * (1 + math.erf(z / math.sqrt(2)))
        pdf = math.exp(-z * z / 2) / math.sqrt(2 * math.pi)
        out += k * (k - 1) * cdf ** (k - 2) * (1 - cdf) * pdf * math.exp(sigma * z) / 100
    return out


@lru_cache(maxsize=None)
def report_scale(fmt: str) -> float | None:
    """Runs per match of XI strength that make a side 73% favourite (logistic scale; engine/fit/fit_auction.py);
    None when the fit found no clear link between strength and results (slope under 2 standard errors)."""
    path = DATA / "engine" / f"auction_{fmt}.json"
    try:
        r = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if r.get("slope") is not None and r["slope"] < 2 * r.get("slope_se", 0):
        return None
    return float(r["scale"])


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
    def __init__(self, pool: dict, user: str | None = None, prev: dict | None = None, seed: int | None = None,
                 start: bool = True, users: list[str] | None = None):
        """start=False: set up the pool and its prices without running anything (the career mode prices its
        opening squads this way). users: several people's teams (two-player mode) instead of one user."""
        self.fmt, self.comp, self.year, self.label = pool["fmt"], pool["comp"], pool["year"], pool["label"]
        self.teams = list(pool["teams"])
        if len(self.teams) < 2:
            raise ValueError("An auction needs at least 2 teams.")
        self.users = list(dict.fromkeys(users)) if users else ([user] if user is not None else [])
        if any(u not in self.teams for u in self.users):
            raise ValueError("Your team must be one of the teams.")
        self.user = self.users[0] if len(self.users) == 1 else None      # the one-player API
        self.homes, self.xi_overseas = pool["homes"], pool["max_overseas"]
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
        self.kept = pool.get("kept")           # mini auction: {team: {player: contract}}
        self.kind = "mini" if self.kept is not None else "mega"
        for t, ids in (self.kept or {}).items():
            for pid, price in ids.items():
                if pid in self.lots and t in self.purse:
                    self.lots[pid].contract, self.lots[pid].prev = None if price is None else int(price), t
        prev = pool["prev"] if prev is None else prev
        for t, ids in prev.items():
            for pid in ids:
                if t in self.purse and pid in self.lots:
                    self.lots[pid].prev = t
        self.has_prev = any(x.prev for x in self.lots.values())
        self._replacement()
        self.lam0 = self.lam = self._lambda()
        self._price(self.lam0)
        for t in self.kept or {}:              # mini auction, contracts not known: expected prices, scaled down
            ids = [x for x in self.lots.values() if x.prev == t and x.contract is None]     # where the squad would
            k = min(1.0, 0.95 * PURSE / max(1, sum(x.est for x in ids)))                    # cost over 95% of the purse
            for x in ids:
                x.contract = max(MIN_PRICE, int(x.est * k))
        self.sets: list[tuple[str, list[str]]] = []
        self.set_no = -1
        self.lot: dict | None = None
        self.prev_lot: dict | None = None    # the lot before (its bids, for the room to replay)
        self.sales: list[dict] = []
        self.phase = "retain"
        # per user: None (asked), "set", "all": the computer bids for them; "wish": by their wishlist
        self.autos: dict[str, str | None] = {u: None for u in self.users}
        self.wishes: dict[str, dict] = {u: {} for u in self.users}    # user -> player -> {"max": lakh|None, "ask"}
        self.pauses = {u: True for u in self.users}       # wishlist mode: stop before each set to change the list
        self.questions: dict[str, dict] = {}   # the open question of each user who has one
        self._seq = 0
        self._started = False
        self._gen = self._flow()
        if start:
            self._advance(None)

    # ---------------------------------------------------------------- the one-player API (self.user)
    @property
    def question(self) -> dict | None:
        return self.questions.get(self.user) if self.user else None

    @property
    def user_auto(self) -> str | None:
        return self.autos.get(self.user)

    @user_auto.setter
    def user_auto(self, v) -> None:
        if self.user is not None:
            self.autos[self.user] = v

    @property
    def wish(self) -> dict:
        return self.wishes.get(self.user, {})

    @property
    def pause_sets(self) -> bool:
        return self.pauses.get(self.user, True)

    @pause_sets.setter
    def pause_sets(self, v: bool) -> None:
        if self.user is not None:
            self.pauses[self.user] = bool(v)

    def _who(self, user: str | None) -> str:
        u = self.user if user is None else user
        if u not in self.users:
            raise ValueError("Not a bidder in this auction.")
        return u

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

    def _price(self, lam: float) -> None:
        """Expected prices (and base prices) of the players still in the pool. A player sells at about the
        second-highest of the teams' valuations, so the market value is scaled by the expected second-highest
        of their random spreads, and capped at what the second-richest team can spend."""
        cap = sorted((self._free(t, 1) for t in self.teams), reverse=True)[1]
        m = second_best(len(self.teams), NOISE)
        for x in self.lots.values():
            if x.status != "pool":
                continue
            x.est = int(min(MIN_PRICE + lam * m * x.var, max(cap, MIN_PRICE)))
            bases = CAPPED_BASES if x.capped else UNCAPPED_BASES
            x.base = next((b for b in bases if x.est >= 4 * b), bases[-1])

    def _free(self, t: str, buying: int = 0) -> int:
        """Purse the team can spend now, keeping 30 lakh for each place still needed to reach the minimum squad."""
        return self.purse[t] - max(0, self.squad_min - len(self.squad[t]) - buying) * MIN_PRICE

    def _xi(self, ids: list[str]) -> tuple[float, int]:
        """(value of the best XI, real players in it) with empty places at replacement level (greedy)."""
        total, picks = self._xi_pick(ids)
        return total, sum(i is not None for _, i in picks)

    def _xi_pick(self, ids: list[str]) -> tuple[float, list[tuple[str, str | None]]]:
        """(value of the best XI, its places as (slot, player or None for an empty place)). The gloves go to the
        keeper who adds most there, or to nobody (a replacement keeper) when the squad's keepers are worth more as
        batters: with many keeper-batters in a pool the replacement keeper is a good batter too."""
        xs = sorted((self.lots[i] for i in ids), key=lambda x: -x.value)
        keepers = [x for x in xs if x.keeper and x.value > self.repl["keeper"]][:3]
        best = self._xi_greedy(xs, None)
        for k in keepers:
            alt = self._xi_greedy(xs, k)
            if alt[0] > best[0]:
                best = alt
        return best

    def _xi_greedy(self, xs: list[Lot], keeper: Lot | None) -> tuple[float, list[tuple[str, str | None]]]:
        """Best XI by value with the gloves given to `keeper` (None: a replacement keeper), the rest greedy."""
        chosen, os_, total, picks = set(), 0, 0.0, []
        if keeper is not None:
            chosen.add(keeper.id)
            picks.append(("keeper", keeper.id))
            os_, total = int(keeper.overseas), keeper.value
        else:
            picks.append(("keeper", None))
            total = self.repl["keeper"]
        ok = lambda x: x.id not in chosen and (not x.overseas or self.xi_overseas is None or os_ < self.xi_overseas)
        for slot, n in (("bowler", 5), ("other", self.xi_n - 6)):
            got = 0
            for x in xs:
                if got >= n:
                    break
                if ok(x) and (slot == "other" or x.bowler) and x.value > self.repl[slot]:
                    chosen.add(x.id)
                    picks.append((slot, x.id))
                    os_ += x.overseas
                    total += x.value
                    got += 1
            total += (n - got) * self.repl[slot]
            picks += [(slot, None)] * (n - got)
        return total, picks

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

    def worth(self, t: str, x: Lot, noise: bool = True, rate: float | None = None) -> int:
        """The most team t would pay for x (lakh), within what it can afford (rate: the team's money rate, if
        already worked out)."""
        if not self.can_buy(t, x):
            return 0
        gain = self._xi(self.squad[t] + [x.id])[0] - self._xi(self.squad[t])[0]
        v = (self._rate(t) if rate is None else rate) * gain + (MIN_PRICE if len(self.squad[t]) < self.squad_min else 0)
        if noise:
            v *= math.exp(random.Random(f"{self.seed}|{t}|{x.id}").gauss(0.0, NOISE))
        return int(min(v, self._free(t, 1)))

    # ---------------------------------------------------------------- flow
    def _advance(self, msg) -> None:
        """Resume the flow with msg = (user, answer) (None to start it). The flow yields {user: question} for
        everyone asked at this moment; a question that is the same as before keeps its number (seq)."""
        try:
            qs = self._gen.send(msg) if self._started else next(self._gen)
        except StopIteration:
            qs = {}
        self._started = True
        old, self.questions = self.questions, {}
        for u, q in (qs or {}).items():
            o = old.get(u)
            if o is not None and {k: v for k, v in o.items() if k != "seq"} == q:
                q = o
            else:
                self._seq += 1
                q = {**q, "seq": self._seq}
            self.questions[u] = q

    def _ask_one(self, u: str, q: dict):
        """Ask one user and wait for their answer."""
        while True:
            v, a = yield {u: q}
            if v == u:
                return a

    def _ask_all(self, qs: dict):
        """Ask several users at once; their answers, in whatever order they come."""
        out, left = {}, dict(qs)
        while left:
            v, a = yield left
            if v in left:
                out[v] = a
                del left[v]
        return out

    def act(self, answer: dict, user: str | None = None) -> None:
        """A user's answer to their open question (validated here; ValueError if it is not allowed). An answer
        carrying "seq" must be to the question now open (two people: the other may have bid first)."""
        u = self._who(user)
        q = self.questions.get(u)
        if not q:
            raise ValueError("Nothing to decide.")
        if answer.get("seq") is not None and int(answer["seq"]) != q["seq"]:
            raise ValueError("Too late: the bidding has moved on.")
        answer = {k: v for k, v in answer.items() if k != "seq"}
        k = q["kind"]
        if k in ("retain", "release"):
            ids = list(dict.fromkeys(answer.get("ids") or []))
            err = (self.retain_error if k == "retain" else self.release_error)(u, ids)
            if err:
                raise ValueError(err)
            answer = {"ids": ids}
        elif k == "bid":
            if answer.get("skip") in ("set", "all"):
                self.autos[u] = answer["skip"]
            elif answer.get("max") is not None:
                m = int(answer["max"])
                if m < q["next"]:
                    raise ValueError(f"Your limit must be at least {money(q['next'])}.")
                answer = {"max": min(m, q["cap"])}
            elif answer.get("bid") and q["next"] > q["cap"]:
                raise ValueError("You cannot afford that bid.")
        elif k == "nominate":
            ids = list(dict.fromkeys(answer.get("ids") or []))
            if any(i not in {p["id"] for p in q["players"]} for i in ids):
                raise ValueError("You can only name unsold players.")
            answer = {"ids": ids}
        elif k == "set":
            if answer.get("self"):
                self.autos[u] = None
        elif k == "rtm_raise":
            amt = int(answer.get("amount") or q["price"])
            if not q["price"] <= amt <= q["cap"]:
                raise ValueError(f"Raise to between {money(q['price'])} and {money(q['cap'])}.")
            answer = {"amount": amt}
        self._advance((u, answer))

    def auto(self, scope: str = "all", user: str | None = None) -> None:
        """Hand a user's bidding to the computer (to the end of the set or the auction), or to the wishlist;
        "ask": back to being asked about every player. No user at all: nothing to hand over."""
        if user is None and not self.users:
            return
        u = self._who(user)
        if scope == "ask":
            self.autos[u] = None
            return
        self.autos[u] = scope
        q = self.questions.get(u)
        if q and q["kind"] not in ("retain", "release", "nominate", "set"):
            self._advance((u, {"auto": True}))

    def set_wish(self, pid: str, top: int | None, ask: bool = False, user: str | None = None) -> None:
        """Wishlist entry for a player still to be sold: a top bid (lakh), or ask me; neither = off the list."""
        wish = self.wishes[self._who(user)]
        x = self.lots.get(pid)
        if x is None or x.status not in ("pool", "unsold"):
            raise ValueError("That player is not up for sale.")
        if top is not None and int(top) < x.base:
            raise ValueError(f"A top bid must be at least his base price ({money(x.base)}).")
        if top is None and not ask:
            wish.pop(pid, None)
        else:
            wish[pid] = {"max": None if top is None else int(top), "ask": bool(ask)}

    def _user_plan(self, u: str, x: Lot) -> str:
        """How user u's team bids on x: "ask", "auto" (the computer), "max" (up to the wishlist's top) or "out"."""
        if self.autos[u] is None:
            return "ask"
        if self.autos[u] != "wish":
            return "auto"
        w = self.wishes[u].get(x.id) or {}
        return "ask" if w.get("ask") else "max" if w.get("max") else "out"

    @property
    def done(self) -> bool:
        return self.phase == "done"

    def _flow(self):
        if self.kept is not None:
            yield from self._release_flow()
        else:
            yield from self._retain_flow()
        yield from self._auction_flow()

    def _release_flow(self):
        """Mini auction: each team releases players and keeps the rest at their contracts (no RTM cards)."""
        self.phase = "release"
        for t in self.teams:
            if t not in self.users:
                self._keep(t, self.suggest_release(t))
        qs = {u: {"kind": "release", "squad": [self.lots[i].row() for i in self.retain_candidates(u)],
                  "suggested": self.suggest_release(u)} for u in self.users if self.retain_candidates(u)}
        ans = yield from self._ask_all(qs)
        for u in self.users:                  # everyone's choices are known before any is applied
            a = ans.get(u)
            self._keep(u, a.get("ids", []) if isinstance(a, dict) else qs[u]["suggested"] if u in qs else [])

    def suggest_release(self, t: str) -> list[str]:
        cands = self.retain_candidates(t)
        out = [i for i in cands if self.lots[i].est < RELEASE * (self.lots[i].contract or 0)]
        keep = sorted((i for i in cands if i not in out),        # best value for money first
                      key=lambda i: -self.lots[i].est / max(MIN_PRICE, self.lots[i].contract or 0))
        kept, os_n, cost = [], 0, 0
        for i in keep:
            x = self.lots[i]
            os_ok = self.xi_overseas is None or not x.overseas or os_n < OVERSEAS_MAX
            if len(kept) < SQUAD_MAX and os_ok and cost + (x.contract or 0) <= PURSE:
                kept.append(i); os_n += x.overseas; cost += x.contract or 0
            else:
                out.append(i)
        return out

    def release_error(self, t: str, ids: list[str]) -> str | None:
        cands = set(self.retain_candidates(t))
        if any(i not in cands for i in ids):
            return "You can only release players from your squad."
        keep = [i for i in cands if i not in ids]
        if len(keep) > SQUAD_MAX:
            return f"Keep at most {SQUAD_MAX} players."
        if sum(self.lots[i].contract or 0 for i in keep) > PURSE:
            return "The players you keep cost more than the purse."
        if self.xi_overseas is not None and sum(self.lots[i].overseas for i in keep) > OVERSEAS_MAX:
            return f"Keep at most {OVERSEAS_MAX} overseas players."
        return None

    def _keep(self, t: str, release: list[str]) -> None:
        for i in self.retain_candidates(t):
            x = self.lots[i]
            if i in release:
                x.prev = None                       # back in the pool, no Right to Match
                continue
            self.purse[t] -= x.contract or 0
            self.squad[t].append(i)
            self.retained[t].append(i)
            x.status, x.buyer, x.price = "retained", t, x.contract

    def _retain_flow(self):
        # retentions (and RTM cards)
        self.phase = "retain"
        for t in self.teams:
            if t not in self.users:
                self._retain(t, self.suggest_retain(t))
        qs = {u: {"kind": "retain", "candidates": [self.lots[i].row() for i in self.retain_candidates(u)],
                  "suggested": self.suggest_retain(u)} for u in self.users if self.retain_candidates(u)}
        ans = yield from self._ask_all(qs)
        for u in self.users:
            a = ans.get(u)
            self._retain(u, a.get("ids", []) if isinstance(a, dict) else qs[u]["suggested"] if u in qs else [])

    def _auction_flow(self):
        # sets
        self.phase = "auction"
        self._make_sets()
        for n, (name, ids) in enumerate(self.sets):
            self.set_no = n
            for u in self.users:
                if self.autos[u] == "set":
                    self.autos[u] = None
            qs = {u: {"kind": "set", "name": name, "players": [self.lots[i].row() for i in ids]} for u in self.users
                  if self.autos[u] == "wish" and self.pauses[u] and any(self.can_buy(u, self.lots[i]) for i in ids)}
            yield from self._ask_all(qs)
            for pid in ids:
                yield from self._sell(pid, name)
        # accelerated round: the players the teams name
        self.phase = "accelerated"
        for u in self.users:
            if self.autos[u] == "set":
                self.autos[u] = None
        unsold = [x for x in self.lots.values() if x.status == "unsold"]
        named = set()
        for t in self.teams:
            if t not in self.users or self.autos[t] == "all":
                named |= set(self.nominate(t, unsold))
        qs = {}
        for u in self.users:
            if self.autos[u] != "all" and unsold:
                sug = self.nominate(u, unsold)
                if self.autos[u] == "wish":
                    sug = [x.id for x in unsold if x.id in self.wishes[u]]
                qs[u] = {"kind": "nominate", "players": [x.row() for x in sorted(unsold, key=lambda x: -x.est)],
                         "suggested": sug}
        ans = yield from self._ask_all(qs)
        for u, q in qs.items():
            a = ans.get(u)
            named |= set(a.get("ids", []) if isinstance(a, dict) else q["suggested"])
        again = sorted((x for x in unsold if x.id in named), key=lambda x: -x.est)
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

    def nominate(self, t: str, unsold: list[Lot]) -> list[str]:
        """The unsold players team t names for the accelerated round: those worth their base price to it, best
        first, up to its open squad places."""
        want = [(self.worth(t, x, noise=False), x) for x in unsold if self.can_buy(t, x)]
        want = sorted(((w, x) for w, x in want if w >= x.base), key=lambda wx: -wx[0])
        return [x.id for _, x in want[:max(0, SQUAD_MAX - len(self.squad[t]))]]

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
        self._price(self.lam)                  # re-priced now that retentions have taken players and money
        left = sorted((x for x in self.lots.values() if x.status == "pool"), key=lambda x: -x.est)
        capped = [x for x in left if x.capped]
        marquee = capped[:MARQUEE] if self.kind == "mega" else []     # mini auctions have no marquee set
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
        if self.kind == "mini" and x.overseas and self.xi_overseas is not None and price > FEE_CAP:
            x.fee = FEE_CAP                     # the whole price still comes off the purse
        self.sales.append({"id": x.id, "name": x.name, "team": t, "price": price, "how": how, "role": x.role,
                           "fee": x.fee})

    def _sell(self, pid: str, set_name: str):
        x = self.lots[pid]
        self.lam = self._lambda()
        w = {t: self.worth(t, x) for t in self.teams}
        self.prev_lot = self.lot
        lot = self.lot = {"id": pid, "set": set_name, "price": None, "leader": None, "log": [], "passed": [],
                          "user_max": {}}
        def plan(u):
            m = self._user_plan(u, x)
            if m == "max":
                lot["user_max"][u] = self.wishes[u][pid]["max"]
            return m
        mode = {u: plan(u) if self.can_buy(u, x) else "out" for u in self.users}
        while True:
            price, leader = lot["price"], lot["leader"]
            nxt = x.base if leader is None else step(price)
            for u in self.users:
                if mode[u] == "ask" and self._user_plan(u, x) != "ask":    # handed over mid-lot
                    mode[u] = plan(u)
                if mode[u] == "auto":
                    w[u] = self.worth(u, x)
                elif mode[u] == "max":
                    w[u] = min(lot["user_max"][u], self._free(u, 1))
            bidders = [t for t in self.teams if t != leader and w[t] >= nxt
                       and (t not in mode or mode[t] in ("auto", "max"))]
            # teams still in at this price (the paddles the room shows): the leader, the willing, users being asked
            still = [t for t in self.teams if t == leader or t in bidders or mode.get(t) == "ask"]
            ask = [u for u in self.users if mode[u] == "ask" and u != leader and nxt <= self._free(u, 1)]
            if ask and not (leader is None and bidders):
                # everyone asked at once; the first answer counts (two people: the first paddle up wins the bid)
                u, a = yield {u: self._bid_question(u, x, nxt) for u in ask}
                a = a or {}
                if a.get("bid"):
                    lot["price"], lot["leader"] = nxt, u
                    lot["log"].append({"team": u, "price": nxt, "in": still})
                elif a.get("max") is not None:
                    mode[u], lot["user_max"][u] = "max", a["max"]
                elif a.get("auto") or a.get("skip"):
                    mode[u] = plan(u)
                else:
                    mode[u] = "out"
                    lot["passed"].append(u)
                continue
            if not bidders:
                break
            t = self.rng.choice(bidders)
            lot["price"], lot["leader"] = nxt, t
            lot["log"].append({"team": t, "price": nxt, "in": still})
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
        """Right to Match: the old team may match; the buyer gets one last raise first. On the wishlist, the user's
        top bid decides, and a former player not on it is let go."""
        def plan(t):
            return self._user_plan(t, x) if t in self.users else "auto"

        def value(t):                         # the most t would pay
            m = plan(t)
            if m == "max":
                return min(self.wishes[t][x.id]["max"], self._free(t, 1))
            return 0 if m == "out" else self.worth(t, x)
        ask_h = plan(holder) == "ask"
        if ask_h:
            a = yield from self._ask_one(holder, {"kind": "rtm_use", "player": x.row(), "buyer": buyer, "price": price,
                                                  "advice": self.worth(holder, x, noise=False), "cards": self.rtm[holder]})
            a = a or {}
            use = value(holder) >= price if a.get("auto") else bool(a.get("yes"))
        else:
            use = value(holder) >= price
        if not use:
            return buyer, price
        self.lot["log"].append({"team": holder, "price": price, "rtm": True})
        cap_b = max(price, self._free(buyer, 1))
        new = None
        if plan(buyer) == "ask":
            a = yield from self._ask_one(buyer, {"kind": "rtm_raise", "player": x.row(), "holder": holder,
                                                 "price": price, "cap": cap_b,
                                                 "advice": self.worth(buyer, x, noise=False)})
            a = a or {}
            if not a.get("auto"):
                new = int(a.get("amount") or price)
        if new is None:                       # the computer's raise: half way to what he is worth to the buyer
            wb = min(value(buyer), cap_b)
            new = price
            while step(new) <= wb and new < price + (wb - price) // 2:
                new = step(new)
        if new > price:
            self.lot["log"].append({"team": buyer, "price": new, "raise": True})
        if new > self._free(holder, 1):
            match = False
        elif ask_h and new > price:
            a = yield from self._ask_one(holder, {"kind": "rtm_match", "player": x.row(), "buyer": buyer,
                                                  "price": new, "advice": self.worth(holder, x, noise=False)})
            a = a or {}
            match = value(holder) >= new if a.get("auto") else bool(a.get("yes"))
        elif ask_h:
            match = True
        else:
            match = value(holder) >= new
        if match:
            self.rtm[holder] -= 1
            return holder, new
        return buyer, new

    def _bid_question(self, u: str, x: Lot, nxt: int) -> dict:
        lot = self.lot
        return {"kind": "bid", "player": x.row(), "price": lot["price"], "leader": lot["leader"], "next": nxt,
                "cap": self._free(u, 1), "advice": self.worth(u, x, noise=False)}

    # ---------------------------------------------------------------- planner and report
    def planner(self, t: str) -> dict:
        """Team t's best XI now (open places at replacement level), against the other teams', and what the player
        on the block would change in it."""
        total, picks = self._xi_pick(self.squad[t])
        avg = sum(self._xi(self.squad[u])[0] for u in self.teams) / len(self.teams)
        xi = []
        for slot, i in picks:
            if i is None:
                xi.append({"slot": slot, "open": True, "value": round(self.repl[slot], 1)})
            else:
                x = self.lots[i]
                xi.append({"slot": slot, "id": i, "name": x.name, "role": x.role, "value": round(x.value, 1),
                           "overseas": x.overseas})
        out = {"xi": xi, "total": round(total, 1), "vs_avg": round(total - avg, 1),
               "open": {sl: sum(1 for s_, i in picks if s_ == sl and i is None) for sl in ("keeper", "bowler", "other")},
               "xi_overseas": sum(1 for _, i in picks if i and self.lots[i].overseas), "xi_overseas_max": self.xi_overseas,
               "lot": None}
        if self.lot and self.lot["id"] in self.lots:
            x = self.lots[self.lot["id"]]
            if x.status in ("pool", "unsold") and self.can_buy(t, x):
                t2, p2 = self._xi_pick(self.squad[t] + [x.id])
                before = {i for _, i in picks if i}
                slot = next((sl for sl, i in p2 if i == x.id), None)
                out_ = [self.lots[i].name for i in before - {i for _, i in p2 if i}]
                out["lot"] = {"name": x.name, "gain": round(t2 - total, 1), "slot": slot,
                              "replaces": out_[0] if out_ else ("an open place" if slot else None)}
        return out

    def needs(self, t: str) -> dict:
        """Open places in team t's best XI (keeper / bowler / other) and overseas places left in the squad."""
        _, picks = self._xi_pick(self.squad[t])
        out = {sl: sum(1 for s_, i in picks if s_ == sl and i is None) for sl in ("keeper", "bowler", "other")}
        out["os_left"] = self.overseas_max - sum(self.lots[i].overseas for i in self.squad[t])
        return out

    def to_you(self, user: str | None = None) -> dict:
        """What each player still for sale is worth to a user's team now (the computer's top bid, no spread)."""
        u = self.user if user is None else user
        if u not in self.users or self.done:
            return {}
        r = self._rate(u)
        return {x.id: self.worth(u, x, noise=False, rate=r) for x in self.lots.values()
                if x.status in ("pool", "unsold")}

    def report(self, sims: int = 2000) -> dict:
        """Report card: each squad's strength (best XI, runs per match), spend, best and worst buys, and a
        predicted table for a double round robin (win chance fitted in engine/fit/fit_auction.py)."""
        strength = {t: self._xi(self.squad[t])[0] for t in self.teams}
        avg = sum(strength.values()) / len(self.teams)
        scale = report_scale(self.fmt)
        if scale is None:
            sims = 0
        pw = lambda a, b: 1 / (1 + math.exp(-(strength[a] - strength[b]) / scale)) if scale else 0.5
        top = 4 if len(self.teams) >= 5 else 2 if len(self.teams) >= 3 else 1
        rng = random.Random(f"{self.seed}|report")
        made, first = dict.fromkeys(self.teams, 0), dict.fromkeys(self.teams, 0)
        pairs = [(a, b, pw(a, b)) for n, a in enumerate(self.teams) for b in self.teams[n + 1:]]
        for _ in range(sims):
            wins = dict.fromkeys(self.teams, 0.0)
            for a, b, p_ in pairs:
                for _ in range(2):
                    wins[a if rng.random() < p_ else b] += 1
            order = sorted(self.teams, key=lambda t: (-wins[t], rng.random()))
            first[order[0]] += 1
            for t in order[:top]:
                made[t] += 1
        buys = [x for x in self.lots.values() if x.status == "sold" and x.price is not None and x.buyer]
        bought = [s_ for s_ in self.sales if s_["how"] in ("bid", "rtm")]
        by_bid = {s_["id"] for s_ in bought}
        deal = lambda x: {"name": x.name, "team": x.buyer, "role": x.role, "price": x.price, "est": x.est,
                          "diff": x.est - x.price}
        teams = []
        for t in self.teams:
            sq = [self.lots[i] for i in self.squad[t]]
            mine = [x for x in sq if x.id in by_bid]
            teams.append({
                "team": t, "strength": round(strength[t], 1), "vs_avg": round(strength[t] - avg, 1),
                "spent": sum(x.price or 0 for x in sq), "retained": sum(x.price or 0 for x in sq if x.status == "retained"),
                "purse": self.purse[t], "players": len(sq), "overseas": sum(x.overseas for x in sq),
                "wins": round(sum(2 * (pw(t, u)) for u in self.teams if u != t), 1) if sims else None,
                "games": 2 * (len(self.teams) - 1),
                "top": round(100 * made[t] / sims) if sims else None, "first": round(100 * first[t] / sims) if sims else None,
                "best": deal(max(mine, key=lambda x: x.est - x.price)) if mine else None,
                "dear": deal(min(mine, key=lambda x: x.est - x.price)) if mine else None})
        teams.sort(key=lambda r: -(r["wins"] if sims else r["strength"]))
        for n, r in enumerate(sorted(teams, key=lambda r: -r["strength"])):
            r["rank"] = n + 1
        bid = [x for x in buys if x.id in by_bid]
        return {"teams": teams, "top_n": top, "scale": scale,
                "bargains": [deal(x) for x in sorted(bid, key=lambda x: x.price - x.est)[:8]],
                "dearest": [deal(x) for x in sorted(bid, key=lambda x: x.est - x.price)[:8]]}

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
                     "fee": self.lots[i].fee,
                     "overseas": self.lots[i].overseas, "retained": i in self.retained[t]} for i in self.squad[t]]
                for t in self.teams}

    def state(self, viewer: str | None = None) -> dict:
        """The auction as one user sees it (viewer; default the one user): their question, wishlist, planner and
        top bid on the lot, never another user's. "waiting": the other users who have a question open."""
        me = self.user if viewer is None else viewer
        me = me if me in self.users else None
        lot = None
        if self.lot:
            x = self.lots[self.lot["id"]]
            lot = {**{k: v for k, v in self.lot.items() if k not in ("passed", "user_max")}, "player": x.row(),
                   "user_max": self.lot["user_max"].get(me)}
        sold = [s for s in self.sales if s["team"]]
        return {"label": self.label, "fmt": self.fmt, "comp": self.comp, "year": self.year, "teams": self.teams,
                "kind": self.kind,
                "user": me, "users": self.users, "phase": self.phase,
                "done": self.done, "purse": self.purse, "rtm": self.rtm, "squad_min": self.squad_min,
                "squad_max": SQUAD_MAX, "overseas_max": OVERSEAS_MAX, "xi_overseas": self.xi_overseas,
                "board": self.board(), "question": self.questions.get(me), "lot": lot,
                "user_auto": self.autos.get(me),
                "waiting": [u for u in self.questions if u != me],
                "prev_lot": {"id": self.prev_lot["id"], "log": self.prev_lot["log"]} if self.prev_lot else None,
                "set_no": self.set_no, "sets": [{"name": n, "n": len(ids)} for n, ids in self.sets],
                "upcoming": [i for i in (self.sets[self.set_no][1] if 0 <= self.set_no < len(self.sets) else [])
                             if self.lots[i].status == "pool" and i != (self.lot or {}).get("id")],
                "sales": self.sales[-12:][::-1], "n_sold": len(sold), "spent": sum(s["price"] for s in sold),
                "news": self.news, "has_prev": self.has_prev,
                "wish": self.wishes.get(me, {}), "pause_sets": self.pauses.get(me, True),
                "planner": self.planner(me) if me else None,
                "needs": {t: self.needs(t) for t in self.teams},
                "report": self._report() if self.done else None}

    def _report(self) -> dict:
        if getattr(self, "_rep", None) is None:     # the auction is over: worked out once
            self._rep = self.report()
        return self._rep

    def summary(self) -> dict:
        """For the results page: squads with prices, purse left, the top buys."""
        top = sorted((x for x in self.lots.values() if x.price is not None), key=lambda x: -x.price)[:15]
        return {"label": self.label, "user": self.user, "users": self.users, "teams": self.teams, "board": self.board(),
                "purse": self.purse, "top": [{"name": x.name, "team": x.buyer, "price": x.price,
                                              "retained": x.status == "retained"} for x in top]}
