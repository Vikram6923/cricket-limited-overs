"""Test career: the Test nations, season after season, from a real year onward.

Start: the nations that were playing Tests in a year (2005 or later: the years with ball-by-ball records), each
with the players who had played for it in the two years before or made their debut that year. Each season:
1. the season is played: every nation meets every other in a Test at home and one away (or once, at the
   first-named side's home), the table is the World Test Championship's (engine/test_tournament.py) and the top
   two play a final. Each nation takes its SQUAD best players into the season (the learned selection's ranking,
   engine/test_selection.py) and picks an XI from them for every Test;
2. players age a year (age curves fitted from real Test careers, engine/fit/fit_test_career.py) and draw a new
   season form; some retire (the real chance at their age that a year is an established regular's last;
   everyone at OLDEST); a player outside his nation's squad for IDLE_YEARS seasons in a row is not picked again;
3. newcomers arrive: while real years last, the players who really made their Test debut for the nation that
   year (rated on their whole careers, adjusted to their age); after that, made-up players, each a copy of a
   random real debutant of the same nation with a name made from that nation's players, as many a year as the
   nation really blooded over its last NEWCOMER_YEARS real years.

A player's level in a season = his career rating x f(age) / f(his typical age) x his season form, as in the
franchise career (engine/career.py). There is no auction and no money: a Test player plays for his country.

The class offers what the server asks of a career (specs, play_args, record, advance, state, to_json), so the
career pages and the season runner work on it; "kind" is "test".

Not fitted: SQUAD (touring parties are 15 to 18), IDLE_YEARS, OLDEST, NEWCOMER_YEARS.
"""
from __future__ import annotations

import json
import math
import random
import zlib
from functools import lru_cache

from . import history, test_selection, test_value
from .data import DATA, METRICS, baseline, player as base_player, ratings, scale_indexes
from .test_captain import batting_value, group

FMT = "test"
COMP = "test_full"
FIRST_YEAR = 2005                # from here most Tests have ball-by-ball records, so ratings have their years
SQUAD = 18
IDLE_YEARS = 3
OLDEST = 44
NEWCOMER_YEARS = 5
MIN_NATIONS = 3
START_WINDOW = 2                 # a nation's players at the start: those who played for it in this many years before


@lru_cache(maxsize=None)
def tables() -> dict:
    return json.loads((DATA / "engine" / "career_test.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def _year_rows() -> dict:
    return json.loads((DATA / "ratings_test_years.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def _births() -> dict:
    st = json.loads((DATA / "raw_stats" / "styles.json").read_text(encoding="utf-8"))
    born = {pid: int(r["dob"][:4]) for pid, r in st.items() if (r.get("dob") or "")[:4].isdigit()}
    for pid, r in ratings(FMT)["players"].items():
        if pid not in born and str(r.get("born") or "").isdigit():
            born[pid] = int(r["born"])
    return born


def log_f(side: str, m: str, age: int) -> float:
    t = tables()
    lo, hi = t["ages"]
    return math.log(t["curve"][side][m][str(min(hi, max(lo, age)))])


def profile(pid: str, fallback_year: int) -> tuple[int, dict]:
    """(year of birth, his typical log age factor per side and metric: the exposure-weighted mean over the years
    his rating comes from) of a real player."""
    rows = _year_rows()
    years = sorted({int(y) for side in ("bat", "bowl") for y in (rows[side].get(pid) or {})})
    born = _births().get(pid)
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


@lru_cache(maxsize=None)
def _debuts() -> dict:
    """nation -> [(player, year of his first Test for it)], for players with a rating."""
    rated = ratings(FMT)["players"]
    out: dict = {}
    for pid, by in history._intl_years(FMT).items():
        if pid not in rated:
            continue
        first: dict = {}
        for y, teams in by.items():
            for t in teams:
                first[t] = min(first.get(t, 9999), y)
        for t, y in first.items():
            out.setdefault(t, []).append((pid, y))
    return out


def last_real_year() -> int:
    return history.last_year(FMT)


def start_years() -> list[int]:
    return list(range(FIRST_YEAR, last_real_year() + 1))


def nations_in(year: int) -> list[str]:
    """Full-member nations with enough players around a year to field a squad, most Tests first."""
    return [n for n, _ in history.nations(FMT, year - START_WINDOW, year) if n in history.FULL_MEMBERS]


def _ordinal(n: int) -> str:
    return f"{n}{'st' if n == 1 else 'nd' if n == 2 else 'rd' if n == 3 else 'th'}"


class TestCareer:
    __test__ = False             # not a test class (the name starts with Test)
    KEYS = ("kind", "league", "league_label", "franchises", "user", "seed", "start_season", "year", "season_no",
            "season_label", "name", "players", "pools", "squads", "history", "stats", "news", "phase", "rounds")

    def __init__(self, year: int | str = FIRST_YEAR, nations: list[str] | None = None, user: str | None = None,
                 rounds: int = 2, seed: int | None = None, name: str | None = None, _blank: bool = False):
        self.kind, self.fmt = "test", FMT
        if _blank:
            return
        try:
            year = int(year)
        except (TypeError, ValueError):
            raise ValueError("Choose the year the career starts in.")
        if year not in start_years():
            raise ValueError(f"A Test career starts in {FIRST_YEAR} to {last_real_year()}.")
        have = nations_in(year)
        self.franchises = [n for n in have if not nations or n in nations]
        if len(self.franchises) < MIN_NATIONS:
            raise ValueError(f"A Test career needs at least {MIN_NATIONS} nations that were playing Tests in {year}.")
        if user and user not in self.franchises:
            raise ValueError("Your nation must be one of the career's nations.")
        if int(rounds) not in (1, 2):
            raise ValueError("Nations meet once, or home and away.")
        self.league, self.league_label = COMP, "Test cricket"
        self.user, self.rounds = user or None, int(rounds)
        self.seed = seed if seed is not None else random.randrange(1 << 30)
        self.start_season, self.year, self.season_no, self.season_label = str(year), year, 0, str(year)
        self.name = name or f"Test career from {year}" + (f" - {user}" if user else "")
        self.players: dict[str, dict] = {}
        self.pools: dict[str, list] = {n: [] for n in self.franchises}
        self.squads: dict[str, list] = {}
        self.history: list[dict] = []
        self.stats: dict[str, dict] = {}
        self.news: list[str] = []
        self.phase = "season"
        for n in self.franchises:
            apps = history.appearances(FMT, n, year - START_WINDOW, year - 1)
            ids = set(apps) | {pid for pid, y in _debuts().get(n, []) if y == year}
            for pid in sorted(ids):
                if pid in ratings(FMT)["players"]:
                    self._add_real(pid, n)
        self._new_season()

    # ---------------------------------------------------------------- players
    def _rng(self, *key) -> random.Random:
        return random.Random(zlib.crc32("|".join(map(str, (self.seed,) + key)).encode()))

    def _add_real(self, pid: str, nation: str) -> None:
        if pid in self.players:
            return
        born, ref = profile(pid, self.year)
        rec = ratings(FMT)["players"][pid]
        caps = round(sum(history.appearances(FMT, t, 0, self.year - 1).get(pid, 0) for t in history.FULL_MEMBERS))
        self.players[pid] = {"id": pid, "src": pid, "name": rec.get("name") or pid, "nation": nation, "born": born,
                             "ref": ref, "joined": self.year, "made_up": False, "form": {}, "retired": None,
                             "caps": caps, "last": self.year}
        self.pools[nation].append(pid)

    def age(self, pid: str) -> int:
        return self.year - self.players[pid]["born"]

    def factors(self, pid: str, form: bool = True) -> dict:
        """side -> metric -> multiplier on the career rating this season: age, and season form unless form=False."""
        r = self.players[pid]
        a = self.age(pid)
        f = lambda side, m: 1 + r["form"].get(side, {}).get(m, 0.0) if form else 1.0
        return {side: {m: math.exp(log_f(side, m, a) - r["ref"][side][m]) * f(side, m) for m in METRICS}
                for side in ("bat", "bowl")}

    def engine_player(self, pid: str, form: bool = True):
        """The engine Player for this season: career rating x age x form."""
        r = self.players[pid]
        p = base_player(FMT, r["src"])
        p.id, p.name, p.team, p.caps = pid, r["name"], r["nation"], r["caps"]
        scale_indexes(p, self.factors(pid, form))
        return p

    def active(self) -> list[str]:
        return [pid for n in self.franchises for pid in self.pools[n]]

    # ---------------------------------------------------------------- seasons
    def cond_year(self) -> int:
        """The real year whose conditions (scoring level) are used."""
        return min(self.year, last_real_year())

    def _base(self) -> dict:
        return baseline(FMT, COMP, self.cond_year())

    def _pick_squad(self, nation: str) -> list[str]:
        """The nation's SQUAD players for the season: the selectors' XI as the ratings stand (no form: nobody
        knows it yet), then reserves by the same utilities: a keeper, two fast bowlers, a spinner, then the best
        of the rest (a touring party's cover for every place)."""
        ids = self.pools[nation]
        ps = [self.engine_player(pid, form=False) for pid in ids]
        if len(ps) <= SQUAD:
            return list(ids)
        m = test_selection.model()
        if m:
            u = test_selection.utilities(test_selection.features(ps, self._base()), test_selection.weights(m))
            B = test_selection.bowler_mask(ps)
            xi = test_selection.best_xi(u, B, [p.keeper for p in ps], m["composition"],
                                        [B[i] and p.bowl_type == "spin" for i, p in enumerate(ps)], m.get("mixes"))
        else:
            u = [sum(test_value.value_parts(p, self._base())) for p in ps]
            xi = []
        order = sorted(range(len(ps)), key=lambda i: -u[i])
        pick = list(xi)
        for want, n in ((lambda p: p.keeper, 1), (lambda p: group(p) == "pace" and not p.keeper, 2),
                        (lambda p: group(p) == "spin" and not p.keeper, 1)):
            pick += [i for i in order if i not in pick and want(ps[i])][:n]
        for i in order:
            if len(pick) >= SQUAD:
                break
            if i not in pick:
                pick.append(i)
        return [ids[i] for i in pick]

    def _new_season(self) -> None:
        dr = tables()["drift"]
        for pid in self.active():
            rng = self._rng("form", self.year, pid)
            self.players[pid]["form"] = {side: {m: round(rng.gauss(0.0, dr[side][m]["sigma"]), 4)
                                                for m in ("runs", "wkt")} for side in ("bat", "bowl")}
        self.squads = {n: self._pick_squad(n) for n in self.franchises}

    def specs(self) -> list[dict]:
        return [{"name": n, "nation": n, "squad": [self.engine_player(pid) for pid in self.squads[n]]}
                for n in self.franchises]

    def play_args(self) -> dict:
        return {"fmt": FMT, "comp": COMP, "year": self.cond_year(), "rounds": self.rounds, "knockout": "final",
                "seed": zlib.crc32(f"{self.seed}|season|{self.year}".encode())}

    def match_total(self) -> int:
        from .tournament import match_count
        return match_count(len(self.franchises), self.rounds, None, "final")

    def background_matches(self) -> int:
        return 0

    def record(self, res: dict, run: str | None = None) -> dict:
        """Add a played season (play_tournament's result) to the history, the caps and the career statistics."""
        table = [r["team"] for r in res["tables"]["League"]]
        pos = None
        if self.user:
            nth = _ordinal(table.index(self.user) + 1)
            pos = "Champions" if res["winner"] == self.user else "Runners-up" if res["runner_up"] == self.user \
                else f"{nth} in the table"
        top = lambda rows, k: max(rows, key=lambda r: r[k], default=None)
        runs, wkts = top(res["batting"], "runs"), top(res["bowling"], "wickets")
        mvp = ((res.get("mvp") or {}).get("official") or [None])[0]
        h = {"season": self.season_label, "year": self.year, "champion": res["winner"], "runner_up": res["runner_up"],
             "table": table, "user_pos": pos, "run": run,
             "orange": runs and {"name": runs["name"], "team": runs["team"], "runs": runs["runs"]},
             "purple": wkts and {"name": wkts["name"], "team": wkts["team"], "wkts": wkts["wickets"]},
             "mvp": mvp and {"name": mvp["name"], "team": mvp["team"]},
             "captaincy": (res.get("captaincy") or {}).get("runs")}
        self.history.append(h)
        for pid in self.active():
            self.players[pid]["played"] = 0
        for c in res["matches"]:
            for xi in c.get("xi", {}).values():
                for q in xi:
                    if q["id"] in self.players:
                        self.players[q["id"]]["caps"] += 1
                        self.players[q["id"]]["played"] += 1
        self._add_stats(res)
        for n in self.franchises:
            for pid in self.squads[n]:
                self.players[pid]["last"] = self.year
        self.phase = "advance"
        return h

    def _stat(self, pid: str, name: str) -> dict:
        return self.stats.setdefault(pid, {"name": name, "seasons": 0, "titles": 0, "matches": 0, "inns": 0,
                                           "not_outs": 0, "runs": 0, "balls": 0, "fifties": 0, "hundreds": 0,
                                           "fours": 0, "sixes": 0, "hs": 0, "hs_no": False, "wkts": 0,
                                           "bowl_balls": 0, "bowl_runs": 0, "five_w": 0, "best": [0, 0]})

    def _add_stats(self, res: dict) -> None:
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
        for n in self.franchises:
            for pid in self.squads[n]:
                if pid in self.stats:
                    self.stats[pid]["seasons"] += 1
                    if n == res["winner"]:
                        self.stats[pid]["titles"] += 1

    # ---------------------------------------------------------------- between seasons
    def advance(self) -> None:
        """A year passes: retirements, players who have dropped out, newcomers, ageing and form, new squads."""
        self.year += 1
        self.season_no += 1
        self.season_label = str(self.year)
        news = []
        hz, est = tables()["retire"], tables().get("established", 20)
        for n in self.franchises:
            for pid in list(self.pools[n]):
                r = self.players[pid]
                a = self.age(pid)
                regular = r.get("played", 0) >= tables().get("regular", 3)
                if a >= OLDEST or (r["caps"] >= est and regular
                                   and self._rng("retire", self.year, pid).random() < hz.get(str(a), 0.0)):
                    news.append(f"{r['name']} ({n}) retires at {a} after {r['caps']} Tests.")
                    self._leave(pid, "retired")
                elif self.year - r["last"] > IDLE_YEARS:
                    self._leave(pid, "not picked")
        real = self.year <= last_real_year()
        for n in self.franchises:
            if real:
                new = [pid for pid, y in _debuts().get(n, []) if y == self.year and pid not in self.players]
                for pid in new:
                    self._add_real(pid, n)
                names = [self.players[pid]["name"] for pid in new]
            else:
                names = self._made_up(n)
            if names and n == (self.user or n):
                news.append(f"New for {n}: {', '.join(names[:6])}" + (f" and {len(names) - 6} more" if len(names) > 6 else "") + ".")
        if not real and not self.user:
            news = news[:40]
        news.sort(key=lambda s: (self.user or "") not in s)          # your nation's news first
        self.news = news
        self._new_season()
        self.phase = "season"

    def _leave(self, pid: str, why: str) -> None:
        r = self.players[pid]
        self.pools[r["nation"]].remove(pid)
        r["retired"], r["left"] = self.year, why

    def debut_rate(self, nation: str) -> float:
        """Real Test debutants a year for the nation over its last NEWCOMER_YEARS real years."""
        hi = last_real_year()
        return sum(hi - NEWCOMER_YEARS < y <= hi for _, y in _debuts().get(nation, [])) / NEWCOMER_YEARS

    def _made_up(self, nation: str) -> list[str]:
        deb = [(pid, y) for pid, y in _debuts().get(nation, []) if y >= FIRST_YEAR - NEWCOMER_YEARS]
        if not deb:
            return []
        rng = self._rng("newcomers", self.year, nation)
        rate = self.debut_rate(nation)
        n = int(rate) + (rng.random() < rate - int(rate))
        pool = [r["name"] for r in self.players.values() if r["nation"] == nation and " " in r["name"]]
        taken = {r["name"] for r in self.players.values()} | {r["name"] for r in ratings(FMT)["players"].values()}
        out = []
        for k in range(n):
            src, y = rng.choice(deb)
            born, ref = profile(src, y)
            name = self.players.get(src, {}).get("name") or src
            for _ in range(50):
                name = f"{rng.choice(pool).split(' ')[0]} {rng.choice(pool).split(' ')[-1]}" if pool else f"Player {k}"
                if name not in taken:
                    break
            pid = f"tx{self.year}{zlib.crc32(nation.encode()) % 1000:03d}{k:02d}"
            self.players[pid] = {"id": pid, "src": src, "name": name, "nation": nation,
                                 "born": self.year - (y - born), "ref": ref, "joined": self.year, "made_up": True,
                                 "form": {}, "retired": None, "caps": 0, "last": self.year}
            self.pools[nation].append(pid)
            taken.add(name)
            out.append(name)
        return out

    # ---------------------------------------------------------------- views
    def squad_rows(self, nation: str) -> list[dict]:
        """A nation's players as the page shows them: this season's squad first, then the others in its pool."""
        rows = []
        squad = set(self.squads.get(nation, []))
        for pid in self.pools[nation]:
            r = self.players[pid]
            p = self.engine_player(pid, form=False)
            b, w = p.ref.get("bat") or {}, p.ref.get("bowl") or {}
            role = "WK" if p.keeper else {"pace": "Pace", "spin": "Spin"}.get(group(p), "Batter")
            rows.append({"id": pid, "name": r["name"], "age": self.age(pid), "nation": nation, "role": role,
                         "made_up": r["made_up"], "in_squad": pid in squad, "caps": r["caps"],
                         "bat_avg": b.get("avg") if p.rated_bat else None, "bat_sr": b.get("sr") if p.rated_bat else None,
                         "econ": w.get("econ") if p.rated_bowl else None, "bowl_avg": w.get("avg") if p.rated_bowl else None,
                         "seasons": (self.stats.get(pid) or {}).get("seasons", 0), "overseas": False, "price": 0,
                         "value": round(batting_value(p), 3)})
        return sorted(rows, key=lambda x: (not x["in_squad"], -x["caps"]))

    def leaders(self, n: int = 15) -> dict:
        rows = [dict(s, id=pid, active=pid in self.players and self.players[pid]["retired"] is None)
                for pid, s in self.stats.items()]
        for r in rows:
            outs = r["inns"] - r["not_outs"]
            r["avg"] = round(r["runs"] / outs, 1) if outs else None
            r["sr"] = round(100 * r["runs"] / r["balls"], 1) if r["balls"] else None
            r["econ"] = round(6 * r["bowl_runs"] / r["bowl_balls"], 2) if r["bowl_balls"] else None
            r["bowl_avg"] = round(r["bowl_runs"] / r["wkts"], 1) if r["wkts"] else None
        return {"runs": sorted(rows, key=lambda r: -r["runs"])[:n], "wkts": sorted(rows, key=lambda r: -r["wkts"])[:n]}

    def state(self) -> dict:
        titles: dict = {}
        for h in self.history:
            titles[h["champion"]] = titles.get(h["champion"], 0) + 1
        return {"kind": "test", "name": self.name, "league": self.league, "league_label": self.league_label,
                "user": self.user, "start": self.start_season, "season": self.season_label, "year": self.year,
                "phase": self.phase, "teams": self.franchises, "history": self.history, "titles": titles,
                "news": self.news, "squads": {n: self.squad_rows(n) for n in self.franchises},
                "leaders": self.leaders(), "real": self.year <= last_real_year(), "pool_size": len(self.active()),
                "matches": self.match_total(), "rounds": self.rounds, "knowledge": "hindsight"}

    # ---------------------------------------------------------------- storage
    def to_json(self) -> dict:
        return {k: getattr(self, k) for k in self.KEYS}

    @classmethod
    def from_json(cls, d: dict) -> "TestCareer":
        c = cls(_blank=True)
        for k in cls.KEYS:
            setattr(c, k, d[k])
        return c
