"""Franchise career mode: one league, season after season, from a real season onward.

Start: a real season's franchises and squads (as in League Season); contract prices for those squads are the
auction's expected prices. Each later season:
1. the season is played (double round robin and IPL playoffs, in the league's conditions; years after the last
   real season use the last real season's conditions);
2. players age a year (age curves fitted from real careers, engine/fit/fit_career.py), some retire (the real
   chance at their age for established players; anyone over 44 retires; anyone unsold in two auctions in a row
   leaves);
3. newcomers arrive: while real seasons last, the players who really made their debut in the league that season
   (rated on their careers, so a debutant comes in roughly as good as his career says, adjusted to his age);
   after that, made-up players: each a copy of a random real debutant's rating profile and debut age (so the
   newcomers have the real spread of debut quality), with a name made from real players' of the same nation;
4. an auction: a mega auction (retentions and Right to Match, engine/auction.py) every `mega_every` seasons,
   a mini auction in between (each team keeps its squad at the contract prices or releases players; the
   released, the unsold and the newcomers are auctioned);
5. after the auction each player draws a fresh season form (small: the spread real players show around their
   level and age), so no team bids knowing who will have a good season.

A player's level in a season = his career rating x f(age) / f(his typical age), where f is the fitted age curve
and his typical age is the exposure-weighted average over the real seasons his rating comes from; times his
season form. Made-up players follow the age path of the real player they were copied from. Matches use that level
(engine_player). The teams' decisions (bids, retentions, releases, opening contracts) use what they can know
before the season instead (seen_player, engine/belief.py): his real record before he joined the career, then what
the career's own seasons showed of him (his league matches, and a made-up record of his cricket outside the league
drawn from his level; _observe). So a real debutant is valued as an unknown newcomer plus a scouting hint, not on
the seasons he has yet to play, and a player who flops in the career is believed worse whatever he really did.

State is plain JSON (to_json / from_json); the server keeps it in results/careers/<id>/career.json.
"""
from __future__ import annotations

import copy
import json
import math
import random
import zlib
from functools import lru_cache

from . import belief
from .auction import MIN_PRICE, PURSE, Auction, _lot, first_cap, league_data
from .data import DATA, METRICS, player as base_player, ratings, scale_indexes

FMT = "t20"
OPENING = 0.95                   # opening squads cost at most this share of the purse
OLDEST = 44                     # everyone retires at this age
UNSOLD_LEAVE = 2                 # unsold in this many auctions in a row: leaves the league
LATE_DEBUT = 34                  # older than this at a first T20 game: distrust the date of birth
NEWCOMER_SEASONS = 5             # made-up newcomers per season = average real debutants over the last 5 seasons


@lru_cache(maxsize=None)
def tables() -> dict:
    return json.loads((DATA / "engine" / "career_t20.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def _year_rows() -> dict:
    return json.loads((DATA / "ratings_t20_years.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def _births() -> dict:
    st = json.loads((DATA / "raw_stats" / "styles.json").read_text(encoding="utf-8"))
    return {pid: int(r["dob"][:4]) for pid, r in st.items() if (r.get("dob") or "")[:4].isdigit()}


def log_f(side: str, m: str, age: int) -> float:
    t = tables()
    lo, hi = t["ages"]
    return math.log(t["curve"][side][m][str(min(hi, max(lo, age)))])


def profile(pid: str, fallback_year: int) -> tuple[int, dict]:
    """(birth year, typical log age factor per side and metric) of a real player."""
    rows = _year_rows()
    years = sorted({int(y) for side in ("bat", "bowl") for y in (rows[side].get(pid) or {})})
    born = _births().get(pid)
    if born is not None and years and years[0] - born > LATE_DEBUT:
        born = None                  # a T20 debut past 34: usually a namesake's date of birth on Wikipedia
    if born is None:
        born = (years[0] if years else fallback_year) - tables()["debut_age"]
    ref = {}
    for side in ("bat", "bowl"):
        ref[side] = {}
        ys = rows[side].get(pid) or {}
        for k, m in enumerate(METRICS):
            w = [(r[2 + 2 * k], log_f(side, m, int(y) - born)) for y, r in ys.items() if r[2 + 2 * k] > 0]
            tot = sum(e for e, _ in w)
            ref[side][m] = round(sum(e * v for e, v in w) / tot, 5) if tot else 0.0
    return born, ref


def _seasons(league: str) -> list[dict]:
    return list(reversed(league_data()[league]["seasons"]))         # oldest first


@lru_cache(maxsize=None)
def _debutants(league: str) -> tuple:
    """(player, debut year, overseas) for every real debut in the league after its first season."""
    seen, out = set(), []
    for i, s in enumerate(_seasons(league)):
        for t in s["teams"]:
            for pid in t["players"]:
                if pid not in seen and i > 0:
                    out.append((pid, s["year"], pid in t["overseas"]))
                seen.add(pid)
    return tuple(out)


KNOWLEDGE = ("realistic", "hindsight")


def check_knowledge(k: str | None) -> str:
    """What the person sees of the players: "realistic" (what the teams know before each season) or "hindsight"
    (how good they really are)."""
    k = k or "realistic"
    if k not in KNOWLEDGE:
        raise ValueError(f"knowledge must be one of {KNOWLEDGE}")
    return k


def season_leaders(res: dict) -> dict:
    """A season's most runs (orange), most wickets (purple), MVP and the person's captaincy score."""
    top = lambda rows, k: max(rows, key=lambda r: r[k], default=None)
    orange, purple = top(res["batting"], "runs"), top(res["bowling"], "wickets")
    mvp = (res.get("mvp") or {}).get("balanced") or []
    return {"orange": orange and {"name": orange["name"], "team": orange["team"], "runs": orange["runs"]},
            "purple": purple and {"name": purple["name"], "team": purple["team"], "wkts": purple["wickets"]},
            "mvp": mvp and {"name": mvp[0]["name"], "team": mvp[0]["team"], "pts": mvp[0]["balanced"]},
            "captaincy": (res.get("captaincy") or {}).get("runs")}


class Career:
    def __init__(self, league: str, season: str, user: str | None = None, mega_every: int = 3,
                 seed: int | None = None, name: str | None = None, knowledge: str = "realistic",
                 _blank: bool = False):
        if _blank:
            return
        self.knowledge = check_knowledge(knowledge)
        lg = league_data()[league]
        ss = _seasons(league)
        i0 = next((i for i, s in enumerate(ss) if s["season"] == season), None)
        if i0 is None:
            raise ValueError("Unknown season.")
        s = ss[i0]
        self.league, self.league_label = league, lg["label"]
        self.franchises = [t["franchise"] for t in s["teams"]]
        if user and user not in self.franchises:
            raise ValueError("Your team must be one of the season's franchises.")
        self.user = user or None
        self.homes = {t["franchise"]: t.get("home_venue") for t in s["teams"]}
        self.max_overseas = s["max_overseas"]
        self.mega_every = max(1, int(mega_every))
        self.seed = seed if seed is not None else random.randrange(1 << 30)
        self.start_season, self.year, self.real_i, self.season_no = season, s["year"], i0, 0
        self.season_label = season
        self.name = name or f"{lg['label']} career from {season}" + (f" - {user}" if user else "")
        self.players: dict[str, dict] = {}
        self.squads: dict[str, dict] = {}
        self.free: dict[str, int] = {}          # player -> auctions in a row unsold
        self.history: list[dict] = []
        self.stats: dict[str, dict] = {}
        self.news: list[str] = []
        self.phase, self.auction_kind = "season", None
        for t in s["teams"]:
            for pid in t["players"]:
                self._add_real(pid, pid in t["overseas"])
            self.squads[t["franchise"]] = {pid: 0 for pid in t["players"]}
        self._draw_form()
        # opening contracts: what each player would be expected to fetch at auction, scaled down where a squad
        # would cost more than OPENING x the purse (real squads were bought over several auctions)
        a = Auction(self.pool(), start=False)
        for t in self.franchises:
            est = {pid: a.lots[pid].est for pid in self.squads[t]}
            k = min(1.0, OPENING * PURSE / max(1, sum(est.values())))
            self.squads[t] = {pid: max(MIN_PRICE, int(v * k)) for pid, v in est.items()}

    # ---------------------------------------------------------------- players
    def _rng(self, *key) -> random.Random:
        return random.Random(zlib.crc32("|".join(map(str, (self.seed,) + key)).encode()))

    def _add_real(self, pid: str, overseas: bool) -> None:
        if pid in self.players:
            return
        born, ref = profile(pid, self.year)
        rec = ratings(FMT)["players"].get(pid) or {}
        cap = first_cap().get(pid)
        self.players[pid] = {"id": pid, "src": pid, "name": rec.get("name") or pid, "nation": rec.get("team") or "",
                             "born": born, "ref": ref, "overseas": overseas,
                             "cap_year": cap if cap and cap < 9999 else None, "joined": self.year,
                             "made_up": False, "form": {}, "retired": None, "teams": {}, "obs": {}}

    def age(self, pid: str) -> int:
        return self.year - self.players[pid]["born"]

    def _draw_form(self) -> None:
        dr = tables()["drift"]
        for pid, r in self.players.items():
            if r["retired"] is None:
                rng = self._rng("form", self.year, pid)
                r["form"] = {side: {m: round(rng.gauss(0.0, dr[side][m]["sigma"]), 4) for m in ("runs", "wkt")}
                             for side in ("bat", "bowl")}

    def factors(self, pid: str, form: bool = True) -> dict:
        """side -> metric -> multiplier on the career rating this season (age, and season form unless form=False)."""
        r = self.players[pid]
        a = self.age(pid)
        f = lambda side, m: 1 + r["form"].get(side, {}).get(m, 0.0) if form else 1.0
        return {side: {m: math.exp(log_f(side, m, a) - r["ref"][side][m]) * f(side, m) for m in METRICS}
                for side in ("bat", "bowl")}

    def _player(self, pid: str, form: bool):
        r = self.players[pid]
        p = base_player(FMT, r["src"])
        p.id, p.name, p.overseas = pid, r["name"], r["overseas"]
        scale_indexes(p, self.factors(pid, form))
        return p

    def engine_player(self, pid: str):
        """The engine Player for this season, as good as he is: career rating x age x form. Matches use this."""
        return self._player(pid, True)

    def prior_key(self) -> str:
        """The competition whose newcomers set the teams' prior for a player they know nothing about."""
        return self.league

    def seen_player(self, pid: str, real=None):
        """The player as the teams believe him to be before this season (engine/belief.py): his real record before
        he joined the career (a made-up player: the record of the real player he copies, shifted to his own debut)
        and what the teams have seen of him in the career's seasons since (_observe), shrunk toward the league's
        debutant prior, plus a scouting hint; times age, never this season's form. Auctions, retentions, releases
        and contracts use this. real: his _player(pid, False) if already built (left unchanged)."""
        r = self.players[pid]
        shift = r["born"] - profile(r["src"], r["joined"])[0] if r["made_up"] else 0
        # a career saved before players were observed: real record up to the first observed season
        real_until = r.get("obs_from", r["joined"]) if "obs" in r else self.year
        rat = belief.ratios(r["src"], self.year, r["born"], r["ref"], self.prior_key(), shift, real_until,
                            r.get("obs"))
        p = copy.copy(real) if real is not None else self._player(pid, False)
        p.ref = dict(p.ref)          # scale_indexes replaces the index and ref dicts, so `real` stays as it was
        return belief.apply(p, rat)

    def capped(self, pid: str) -> bool:
        c = self.players[pid]["cap_year"]
        return c is not None and c <= self.year

    def active(self) -> list[str]:
        return [pid for t in self.franchises for pid in self.squads.get(t, {})] + list(self.free)

    # ---------------------------------------------------------------- seasons
    def cond_year(self) -> int:
        """The real season whose conditions (scoring level) are used."""
        ss = _seasons(self.league)
        return ss[min(self.real_i, len(ss) - 1)]["year"]

    def match_player(self, pid: str):
        """The engine Player for a match: as good as he is (engine_player). With knowledge "realistic" what a
        captain is shown about him (his numbers, his expected rates today) is what the teams believe instead."""
        p = self.engine_player(pid)
        if self.knowledge == "realistic":
            belief.show(p, self.seen_player(pid))
        return p

    def specs(self) -> list[dict]:
        out = []
        for t in self.franchises:
            ps = [self.match_player(pid) for pid in self.squads[t]]
            out.append({"name": t, "squad": ps, "overseas": [p.id for p in ps if p.overseas],
                        "max_overseas": self.max_overseas})
        return out

    def play_args(self) -> dict:
        return {"fmt": FMT, "comp": self.league, "year": self.cond_year(), "rounds": 2, "knockout": "ipl",
                "home_venues": {t: h for t, h in self.homes.items() if h},
                "seed": zlib.crc32(f"{self.seed}|season|{self.year}".encode())}

    def match_total(self) -> int:
        """How many matches a season plays (for the progress bar)."""
        from .tournament import match_count
        return match_count(len(self.franchises), 2, None, "ipl")

    def record(self, res: dict, run: str | None = None) -> dict:
        """Add a played season (play_tournament's result) to the history and the career statistics."""
        table = [r["team"] for r in res["tables"]["League"]]
        pos = None
        if self.user:
            n = table.index(self.user) + 1
            nth = f"{n}{'st' if n == 1 else 'nd' if n == 2 else 'rd' if n == 3 else 'th'}"
            out = [k["stage"] for k in res.get("knockouts", []) if self.user in k["teams"] and k["winner"] != self.user]
            pos = "Champions" if res["winner"] == self.user else "Runners-up" if res["runner_up"] == self.user \
                else f"Out in the {out[-1]} ({nth} in the league)" if out else f"{nth} in the league"
        h = {"season": self.season_label, "year": self.year, "champion": res["winner"], "runner_up": res["runner_up"],
             "table": table, "user_pos": pos, "run": run, **season_leaders(res)}
        self.history.append(h)
        self._add_stats(res)
        self._observe(res)
        self.phase = "advance"
        return h

    def _observe(self, res: dict) -> None:
        """What the teams saw of every active player this season (engine/belief.py): his league matches from the
        scorecards, plus a made-up record of his cricket outside the league drawn from his level; age-adjusted and
        added to his observations ("obs")."""
        truth = {pid: self.engine_player(pid) for pid in self.active()}
        base = self._base()
        league = belief.league_obs(res["matches"], truth, base)
        for pid, p in truth.items():
            r = self.players[pid]
            if "obs" not in r:                 # a career saved before players were observed
                r["obs"], r["obs_from"] = {}, self.year
            rows = belief.outside_obs(p, belief.outside_balls(r["src"], self.prior_key()), base,
                                      self._rng("outside", self.year, pid))
            for side, row in league.get(pid, {}).items():
                rows[side] = belief._add(rows.get(side), row)
            a = self.age(pid)
            for side, row in rows.items():
                k = [math.exp(r["ref"][side][m] - log_f(side, m, a)) for m in METRICS]
                r["obs"][side] = belief.accumulate(r["obs"].get(side), row, k)

    def _add_stats(self, res: dict) -> None:
        """A played season's batting and bowling into the career statistics; who played for whom."""
        batted = {b["id"] for b in res["batting"]}
        for b in res["batting"]:
            s = self._stat(b["id"], b["name"])
            for k in ("matches", "inns", "not_outs", "runs", "balls", "fifties", "hundreds", "fours", "sixes"):
                s[k] += b[k]
            hs = int(str(b["hs"]).rstrip("*"))
            if hs > s["hs"] or (hs == s["hs"] and str(b["hs"]).endswith("*")):
                s["hs"], s["hs_no"] = hs, str(b["hs"]).endswith("*")
        for w in res["bowling"]:
            s = self._stat(w["id"], w["name"])
            if w["id"] not in batted:
                s["matches"] += w["matches"]
            for k, g in (("wkts", "wickets"), ("bowl_balls", "balls"), ("bowl_runs", "runs"), ("five_w", "five_w")):
                s[k] += w[g]
            if w["best"]:
                bw, br = map(int, w["best"].split("/"))
                if (bw, -br) > (s["best"][0], -s["best"][1]):
                    s["best"] = [bw, br]
        seen = set()
        for t in self.franchises:
            for pid in self.squads[t]:
                self.players[pid]["teams"][self.season_label] = t
                if pid in self.stats and pid not in seen:
                    self.stats[pid]["seasons"] += 1
                    seen.add(pid)
                    if t == res["winner"]:
                        self.stats[pid]["titles"] += 1

    def _stat(self, pid: str, name: str) -> dict:
        return self.stats.setdefault(pid, {"name": name, "seasons": 0, "titles": 0, "matches": 0, "inns": 0,
                                           "not_outs": 0, "runs": 0, "balls": 0, "fifties": 0, "hundreds": 0,
                                           "fours": 0, "sixes": 0, "hs": 0, "hs_no": False, "wkts": 0,
                                           "bowl_balls": 0, "bowl_runs": 0, "five_w": 0, "best": [0, 0]})

    # ---------------------------------------------------------------- between seasons
    def advance(self) -> None:
        """A year passes: ageing, form, retirements, departures, newcomers; then an auction is due."""
        self.year += 1
        self.season_no += 1
        news = []
        hz = tables()["retire"]
        for pid in self.active():
            r = self.players[pid]
            a = self.age(pid)
            if a >= OLDEST or self._rng("retire", self.year, pid).random() < hz.get(str(a), 0.0):
                news.append(f"{r['name']} retires at {a}" + (f" ({self._team_of(pid)})" if self._team_of(pid) else "") + ".")
                self._leave(pid, "retired")
        for pid, n in list(self.free.items()):
            if n >= UNSOLD_LEAVE:
                self._leave(pid, "unsold")
        ss = _seasons(self.league)
        made = 0
        if self.real_i + 1 < len(ss):
            self.real_i += 1
            s = ss[self.real_i]
            self.season_label = s["season"]
            before = {pid for x in ss[:self.real_i] for t in x["teams"] for pid in t["players"]}
            for t in s["teams"]:
                for pid in t["players"]:
                    if pid not in before and pid not in self.players:
                        self._add_real(pid, pid in t["overseas"])
                        self.free[pid] = 0
                        made += 1
            news.append(f"{made} players from the real {s['season']} season make their debut in the auction pool.")
        else:
            last = ss[-1]["season"]
            self.season_label = str(self.year) if "-" not in last else f"{self.year}-{(self.year + 1) % 100:02d}"
            made = self._made_up()
            news.append(f"{made} new young players enter the auction pool.")
        for r in self.players.values():     # this season's form is drawn after the auction, so no team bids on it
            r["form"] = {}
        self.auction_kind = "mega" if self.season_no % self.mega_every == 0 else "mini"
        self.news = news
        self.phase = "auction"

    def _team_of(self, pid: str) -> str | None:
        return next((t for t in self.franchises if pid in self.squads[t]), None)

    def _leave(self, pid: str, why: str) -> None:
        for t in self.franchises:
            self.squads[t].pop(pid, None)
        self.free.pop(pid, None)
        self.players[pid]["retired"] = self.year
        self.players[pid]["left"] = why

    def _made_up(self) -> int:
        ss = _seasons(self.league)
        deb = _debutants(self.league)
        recent = {s["year"] for s in ss[-NEWCOMER_SEASONS:]}
        n = round(sum(y in recent for _, y, _ in deb) / max(1, len(recent)))
        rng = self._rng("newcomers", self.year)
        names = {}
        for pid, r in self.players.items():
            names.setdefault(r["nation"], []).append(r["name"])
        taken = {r["name"] for r in self.players.values()} | {r["name"] for r in ratings(FMT)["players"].values()}
        for k in range(n):
            src, y, os_ = rng.choice(deb)
            born, ref = profile(src, y)
            rec = ratings(FMT)["players"].get(src) or {}
            nation = rec.get("team") or ""
            pool = [x for x in names.get(nation, []) if " " in x] or [x for v in names.values() for x in v if " " in x]
            for _ in range(50):
                name = f"{rng.choice(pool).split(' ')[0]} {rng.choice(pool).split(' ')[-1]}"
                if name not in taken:
                    break
            cap = first_cap().get(src)
            pid = f"mx{self.year}{k:03d}"
            self.players[pid] = {"id": pid, "src": src, "name": name, "nation": nation,
                                 "born": self.year - (y - born), "ref": ref, "overseas": os_,
                                 "cap_year": self.year + (cap - y) if cap and cap < 9999 else None,
                                 "joined": self.year, "made_up": True, "form": {}, "retired": None, "teams": {},
                                 "obs": {}}
            self.free[pid] = 0
            taken.add(name)
        return n

    # ---------------------------------------------------------------- auction
    def pool(self) -> dict:
        """The auction pool. Teams value each player on what they believe him to be (seen_player); the numbers
        shown with him are those too, or his real ones (without form) with knowledge "hindsight"."""
        lots = []
        base = self._base()
        for pid in self.active():
            real = self._player(pid, False)
            x = _lot(pid, self.seen_player(pid, real), FMT, base, self.players[pid]["nation"],
                     self.players[pid]["overseas"], self.capped(pid))
            if self.knowledge != "realistic":
                x.ref = dict(real.ref)
            lots.append(x)
        kind = self.auction_kind or "mega"
        out = {"fmt": FMT, "comp": self.league, "year": self.cond_year(),
               "label": f"{self.league_label} {self.season_label}", "lots": lots, "teams": list(self.franchises),
               "homes": dict(self.homes), "max_overseas": self.max_overseas,
               "prev": {t: list(self.squads.get(t, {})) for t in self.franchises} if kind == "mega" else {},
               "prev_label": None, "knowledge": self.knowledge}
        if kind == "mini":
            out["kept"] = {t: dict(self.squads[t]) for t in self.franchises}
        return out

    def _base(self) -> dict:
        from .data import baseline
        return baseline(FMT, self.league, self.cond_year())

    def auction(self, seed: int | None = None) -> Auction:
        if self.phase != "auction":
            raise ValueError("No auction is due.")
        return Auction(self.pool(), user=self.user,
                       seed=seed if seed is not None else zlib.crc32(f"{self.seed}|auction|{self.year}".encode()))

    def apply_auction(self, a: Auction) -> None:
        bought = set()
        for t in self.franchises:
            self.squads[t] = {pid: int(a.lots[pid].fee or a.lots[pid].price or 0) for pid in a.squad[t]}
            bought |= set(a.squad[t])
        for pid in list(self.free):
            if pid in bought:
                del self.free[pid]
        for x in a.lots.values():
            if x.id not in bought:
                self.free[x.id] = self.free.get(x.id, 0) + 1
        self._draw_form()
        self.phase = "season"

    def auto_auction(self) -> None:
        """Run the whole auction with the computer deciding for every team (also the user's)."""
        a = self.auction()
        a.auto("all")
        while not a.done:
            a.act({"ids": a.question.get("suggested", [])} if a.question["kind"] in ("retain", "release") else {"auto": True})
        self.apply_auction(a)

    # ---------------------------------------------------------------- views
    def squad_rows(self, t: str) -> list[dict]:
        """A squad as the person sees it: each player's numbers as the teams believe them before the season
        (knowledge "realistic") or as good as he is this season (knowledge "hindsight"); "seen": balls of record
        the teams have seen of him, per side."""
        rows = []
        for pid, price in self.squads[t].items():
            r = self.players[pid]
            seen = self.seen_player(pid)
            p = seen if self.knowledge == "realistic" else self.engine_player(pid)
            b, w = p.ref.get("bat") or {}, p.ref.get("bowl") or {}
            rows.append({"id": pid, "name": r["name"], "age": self.age(pid), "nation": r["nation"],
                         "overseas": r["overseas"], "price": price, "made_up": r["made_up"],
                         "bat_avg": b.get("avg"), "bat_sr": b.get("sr"),
                         "econ": w.get("econ") if p.rated_bowl else None, "bowl_avg": w.get("avg") if p.rated_bowl else None,
                         "seasons": (self.stats.get(pid) or {}).get("seasons", 0), "seen": belief.seen_balls(seen)})
        return sorted(rows, key=lambda r: -r["price"])

    def leaders(self, n: int = 15) -> dict:
        rows = [dict(s, id=pid, active=self.players[pid]["retired"] is None) for pid, s in self.stats.items()]
        for r in rows:
            outs = r["inns"] - r["not_outs"]
            r["avg"] = round(r["runs"] / outs, 1) if outs else None
            r["sr"] = round(100 * r["runs"] / r["balls"], 1) if r["balls"] else None
            r["econ"] = round(6 * r["bowl_runs"] / r["bowl_balls"], 2) if r["bowl_balls"] else None
            r["bowl_avg"] = round(r["bowl_runs"] / r["wkts"], 1) if r["wkts"] else None
        return {"runs": sorted(rows, key=lambda r: -r["runs"])[:n], "wkts": sorted(rows, key=lambda r: -r["wkts"])[:n]}

    def state(self) -> dict:
        titles = {}
        for h in self.history:
            titles[h["champion"]] = titles.get(h["champion"], 0) + 1
        return {"name": self.name, "league": self.league, "league_label": self.league_label, "user": self.user,
                "start": self.start_season, "season": self.season_label, "year": self.year, "phase": self.phase,
                "auction_kind": self.auction_kind, "mega_every": self.mega_every, "teams": self.franchises,
                "history": self.history, "titles": titles, "news": self.news,
                "squads": {t: self.squad_rows(t) for t in self.franchises}, "leaders": self.leaders(),
                "real": self.real_i < len(_seasons(self.league)) and not self._past_real(),
                "pool_size": len(self.active()), "knowledge": self.knowledge}

    def _past_real(self) -> bool:
        return self.year > _seasons(self.league)[-1]["year"]

    # ---------------------------------------------------------------- storage
    KEYS = ("league", "league_label", "franchises", "user", "homes", "max_overseas", "mega_every", "seed",
            "start_season", "year", "real_i", "season_no", "season_label", "name", "players", "squads", "free",
            "history", "stats", "news", "phase", "auction_kind", "knowledge")
    DEFAULTS = {"knowledge": "hindsight"}      # careers saved before the setting: as they were shown

    def to_json(self) -> dict:
        return {k: getattr(self, k) for k in self.KEYS}

    @classmethod
    def from_json(cls, d: dict) -> "Career":
        c = cls("", "", _blank=True)
        for k in cls.KEYS:
            setattr(c, k, d[k] if k in d or k not in cls.DEFAULTS else cls.DEFAULTS[k])
        return c
