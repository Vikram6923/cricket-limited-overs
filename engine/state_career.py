"""State career: one Mushtaq Ali Trophy state (or all 38, watched) season after season, Elite and Plate.

Start: a real season that has a Plate (2020-21, 2021-22, 2025-26 in data/domestic_seasons.json), with its groups,
format and squads. Every later season keeps that format (group sizes, knockouts, the Plate's knockout and how
many Plate sides join the Elite knockouts) and:
1. the season is played: Elite groups and knockouts, the Plate alongside (engine/tournament.py);
2. the Plate winner goes up, the lowest Elite side goes down, and next season's Elite groups are dealt by
   finishing position (champions, runners-up, then how deep each side went, then points and NRR), snake order;
3. a year passes: players age, draw a fresh form and some retire, as in franchise career (engine/career.py:
   fitted age curves, the real retirement chance at each age);
4. newcomers and moves: when the new season is one of the real ones in the data, its debutants join their states
   and players who really changed state move (a player dropped earlier in the career comes back if he really
   played); other seasons get NEWCOMERS made-up players per state (each a copy of a real SMAT debutant's rating
   profile and debut age, named from that state's players) and MOVES uncapped players aged 24-33 change state;
5. squads are kept between SQUAD_MIN and SQUAD_MAX: short squads get extra newcomers, long ones drop their
   least valuable players older than PROSPECT (runs value per match, engine/selection.py).

There is no auction: a state's squad carries over. Conditions and grounds are those of the newest real season
not after the one being played. State is plain JSON (Career.to_json, with "kind": "state").
"""
from __future__ import annotations

import random
import re
import zlib
from functools import lru_cache

from .career import FMT, OLDEST, Career, _year_rows, profile, season_leaders, tables
from .data import baseline, ratings
from .domestic import competitions
from .selection import value_parts

COMP = "sma"
SQUAD_MIN, SQUAD_MAX = 16, 22    # real presets: 13-23 players who played a season, 15-18 on average
NEWCOMERS = 3                     # made-up newcomers per state a season (real: 3.3-4.5 debutants per state)
MOVES = 12                        # made-up seasons: players who change state (real: 12-19 a season)
PROSPECT = 23                     # this age or younger: never dropped
DEBUT_FROM = 2019                 # made-up newcomers copy debutants from seasons Cricsheet covers fully
MOVE_AGES = (24, 33)


def _presets() -> dict:
    return {s["season"]: s for s in competitions().get(COMP, {}).get("seasons", [])}


def start_seasons() -> list[str]:
    """Seasons a state career can start from: those with a Plate (promotion and relegation)."""
    return [k for k, s in _presets().items() if s["format"].get("plate")]


def _label(year: int) -> str:
    return f"{year}-{(year + 1) % 100:02d}"


def _first_year(pid: str, fallback: int) -> int:
    rows = _year_rows()
    ys = [int(y) for side in ("bat", "bowl") for y in (rows[side].get(pid) or {})]
    return min(ys) if ys else fallback


@lru_cache(maxsize=1)
def _debutants() -> tuple:
    """(player, first T20 year) for every player whose first SMAT season in the data is DEBUT_FROM or later."""
    seen, out = set(), []
    for k, s in sorted(_presets().items()):
        for t in s["teams"]:
            for pid in t["players"]:
                if pid not in seen and int(k[:4]) >= DEBUT_FROM:
                    out.append((pid, _first_year(pid, int(k[:4]))))
                seen.add(pid)
    return tuple(out)


def _nth(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def _deal(order: list[str], labels: list[str], sizes: list[int]) -> dict:
    """Teams in finishing order into groups of the given sizes, snake order (A B C .. C B A ..)."""
    groups = {lab: [] for lab in labels}
    k = len(labels)
    seq = []
    while len(seq) < 2 * len(order) + 2 * k:
        seq += list(range(k)) + list(range(k - 1, -1, -1))
    it = iter(seq)
    for t in order:
        for i in it:
            if len(groups[labels[i]]) < sizes[i]:
                groups[labels[i]].append(t)
                break
    return groups


def _order(teams: list[str], tabs: dict, kos: list[dict], champ: str | None, ru: str | None,
           extra: dict | None = None) -> list[str]:
    """Finishing order: champions, runners-up, knockout games played, Super League points and NRR, group
    points and NRR."""
    row = {r["team"]: r for rows in tabs.values() for r in rows}
    xr = {r["team"]: r for rows in (extra or {}).values() for r in rows}
    played = {t: sum(t in k["teams"] for k in kos) for t in teams}

    def key(t):
        r, x = row.get(t, {}), xr.get(t, {})
        return (t == champ, t == ru, played[t], x.get("points", -1), x.get("nrr", 0.0),
                r.get("points", 0), r.get("nrr", 0.0), t)
    return sorted(teams, key=key, reverse=True)


class StateCareer(Career):
    KEYS = Career.KEYS + ("kind", "format", "groups", "plate")

    def __init__(self, season: str, user: str | None = None, seed: int | None = None, name: str | None = None,
                 _blank: bool = False):
        self.kind = "state"
        if _blank:
            return
        pre = _presets().get(season)
        if not pre or not pre["format"].get("plate"):
            raise ValueError("A state career starts from a season with a Plate: " + ", ".join(start_seasons()) + ".")
        f, pl = pre["format"], pre["format"]["plate"]
        self.league, self.league_label = COMP, competitions()[COMP]["label"]
        self.franchises = sorted(t["name"] for t in pre["teams"])
        if user and user not in self.franchises:
            raise ValueError("Your side must be one of the season's states.")
        self.user = user or None
        self.homes, self.max_overseas, self.mega_every = {}, 0, 1
        self.seed = seed if seed is not None else random.randrange(1 << 30)
        self.start_season = self.season_label = season
        self.year, self.real_i, self.season_no = int(season[:4]), 0, 0
        self.name = name or f"Mushtaq Ali Trophy career from {season}" + (f" - {user}" if user else "")
        self.players, self.squads, self.free = {}, {}, {}
        self.history, self.stats, self.news = [], {}, []
        self.phase, self.auction_kind = "season", None
        self.format = {"labels": list(f["groups"]), "sizes": [len(g) for g in f["groups"].values()],
                       "advance": f["advance"], "knockout": f["knockout"],
                       "plate_knockout": pl.get("knockout", "final"), "plate_advance": pl.get("advance", 0)}
        self.groups = {k: list(v) for k, v in f["groups"].items()}
        self.plate = list(pl["teams"])
        for t in pre["teams"]:
            for pid in t["players"]:
                self._add_real(pid, False)
            self.squads[t["name"]] = {pid: 0 for pid in t["players"]}
        self._draw_form()

    # ---------------------------------------------------------------- a season
    def _ref(self) -> dict:
        """The real season whose conditions and grounds are used: this one, else the newest before it."""
        ps = _presets()
        here = [k for k in ps if k <= self.season_label]
        return ps[max(here)] if here else ps[min(ps)]

    def cond_year(self) -> int:
        return self._ref()["year"]

    def _spec(self, t: str) -> dict:
        return {"name": t, "squad": [self.engine_player(pid) for pid in self.squads[t]]}

    def elite(self) -> list[str]:
        return [t for g in self.groups.values() for t in g]

    def specs(self) -> list[dict]:
        return [self._spec(t) for t in self.elite()]

    def play_args(self) -> dict:
        f, ref = self.format, self._ref()
        return {"fmt": FMT, "comp": COMP, "year": self.cond_year(), "rounds": 1,
                "groups": [list(g) for g in self.groups.values()], "advance": f["advance"],
                "knockout": f["knockout"], "win_points": 4, "venues": ref.get("venues") or None,
                "knockout_venues": ref.get("knockout_venues") or None,
                "plate": {"teams": [self._spec(t) for t in self.plate], "knockout": f["plate_knockout"],
                          "advance": f["plate_advance"]},
                "seed": zlib.crc32(f"{self.seed}|season|{self.year}".encode())}

    def match_total(self) -> int:
        from .tournament import match_count
        f = self.format
        return match_count(sum(f["sizes"]), 1, [list(g) for g in self.groups.values()], f["knockout"], f["advance"],
                           {"teams": len(self.plate), "knockout": f["plate_knockout"], "advance": f["plate_advance"]})

    def record(self, res: dict, run: str | None = None) -> dict:
        """A played season into the history and statistics; promotion, relegation and next season's groups."""
        elite, plate = self.elite(), list(self.plate)
        ko = [k for k in res["knockouts"] if not k["stage"].startswith("Plate")]
        pko = [k for k in res["knockouts"] if k["stage"].startswith("Plate")]
        p = res["plate"]
        e_order = _order(elite, res["tables"], ko, res["winner"], res["runner_up"], res.get("super_league"))
        p_order = _order(plate, p["tables"], pko, p["winner"], p["runner_up"])
        up, down = res["promoted"], res["relegated"]
        me, pos = self.user, None
        if me:
            if me == res["winner"]:
                pos = "Champions"
            elif me == res["runner_up"]:
                pos = "Runners-up"
            else:
                tabs = res["tables"] if me in elite else p["tables"]
                lab, n = next((lab, i + 1) for lab, rows in tabs.items() for i, r in enumerate(rows) if r["team"] == me)
                where = "the Plate" if me in plate else f"Group {lab}"
                lost = [k["stage"] for k in res["knockouts"] if me in k["teams"] and k["winner"] != me]
                pos = f"Out in the {re.sub(r' [0-9]+$', '', lost[-1])} ({_nth(n)} in {where})" if lost \
                    else f"{_nth(n)} in {where}"
            if me == up:
                pos += ", promoted"
            elif me == down:
                pos += ", relegated"
        h = {"season": self.season_label, "year": self.year, "champion": res["winner"],
             "runner_up": res["runner_up"], "plate_winner": p["winner"], "promoted": up, "relegated": down,
             "user_pos": pos, "user_tier": ("Plate" if me in plate else "Elite") if me else None, "run": run,
             "table": e_order, **season_leaders(res)}
        self.history.append(h)
        self._add_stats(res)
        new_elite = [t for t in e_order if t != down] + [up]
        self.plate = [down] + [t for t in p_order if t != up]
        self.groups = _deal(new_elite, self.format["labels"], self.format["sizes"])
        self.phase = "advance"
        return h

    # ---------------------------------------------------------------- between seasons
    def advance(self) -> None:
        """A year passes: ageing, form, retirements; debutants and moves; squads trimmed. Then the next season."""
        self.year += 1
        self.season_no += 1
        self.season_label = _label(self.year)
        news = []
        hz = tables()["retire"]
        gone = []
        for pid in self.active():
            a = self.age(pid)
            if a >= OLDEST or self._rng("retire", self.year, pid).random() < hz.get(str(a), 0.0):
                gone.append((pid, self._team_of(pid), a))
                self._leave(pid, "retired")
        news += self._retire_news(gone)
        pre = _presets().get(self.season_label)
        news += self._real_season(pre) if pre else self._made_up_season()
        self._draw_form()
        news += self._trim()
        self.news = news
        self.phase = "season"

    def _career_score(self, pid: str) -> float:
        s = self.stats.get(pid) or {}
        return s.get("runs", 0) + 20 * s.get("wkts", 0)

    def _named(self, ids: list[str], n: int = 4) -> str:
        top = sorted(ids, key=lambda p: -self._career_score(p))[:n]
        return ", ".join(self.players[p]["name"] for p in top)

    def _retire_news(self, gone: list) -> list[str]:
        if not gone:
            return []
        mine = [(p, a) for p, t, a in gone if t == self.user]
        out = [f"{self.players[p]['name']} retires at {a} ({self.user})." for p, a in mine]
        others = [p for p, t, _ in gone if t != self.user]
        if others:
            out.append(f"{len(others)} {'other ' if mine else ''}player{'s' if len(others) > 1 else ''} retire"
                       f"{'' if len(others) > 1 else 's'}, including {self._named(others)}.")
        return out

    def _move(self, pid: str, a: str, b: str) -> None:
        del self.squads[a][pid]
        self.squads[b][pid] = 0

    def _move_news(self, moved: list) -> list[str]:
        moved = sorted(moved, key=lambda m: (self.user not in (m[1], m[2]), -self._career_score(m[0])))
        out = [f"{self.players[p]['name']} moves from {a} to {b}." for p, a, b in moved[:8]]
        if len(moved) > 8:
            out.append(f"{len(moved) - 8} more players change state.")
        return out

    def _real_season(self, pre: dict) -> list[str]:
        """The real season's debutants join their states; players who really changed state move."""
        joined, moved = [], []
        for t in pre["teams"]:
            st = t["name"]
            if st not in self.squads:
                continue
            for pid in t["players"]:
                r = self.players.get(pid)
                if r is None:
                    self._add_real(pid, False)
                    self.squads[st][pid] = 0
                    joined.append((pid, st))
                elif r["retired"] is not None and r.get("left") == "dropped":
                    r["retired"] = None
                    r.pop("left", None)
                    self.squads[st][pid] = 0
                    joined.append((pid, st))
                elif r["retired"] is None and (cur := self._team_of(pid)) and cur != st:
                    self._move(pid, cur, st)
                    moved.append((pid, cur, st))
        out = [f"The real {pre['season']} season: {len(joined)} players join or rejoin their state squads"
               + (f", {len(moved)} change state." if moved else ".")]
        mine = [self.players[p]["name"] for p, st in joined if st == self.user]
        if mine:
            out.append(f"New in {self.user}: {', '.join(mine)}.")
        return out + self._move_news(moved)

    def _made_up_season(self) -> list[str]:
        """NEWCOMERS made-up players per state (more where a squad is short); MOVES players change state."""
        rng = self._rng("newcomers", self.year)
        names: dict[str, list[str]] = {}
        for r in self.players.values():
            for st in set(r["teams"].values()):
                names.setdefault(st, []).append(r["name"])
        for st in self.franchises:
            names.setdefault(st, []).extend(self.players[p]["name"] for p in self.squads[st])
        taken = {r["name"] for r in self.players.values()} | {r["name"] for r in ratings(FMT)["players"].values()}
        deb = _debutants()
        mine, k = [], 0
        for st in self.franchises:
            n = max(NEWCOMERS + rng.choice((-1, 0, 0, 1)), SQUAD_MIN - len(self.squads[st]))
            pool = [x for x in names[st] if " " in x] or [x for v in names.values() for x in v if " " in x]
            for _ in range(n):
                src, y = rng.choice(deb)
                born, ref = profile(src, y)
                for _ in range(50):
                    name = f"{rng.choice(pool).split(' ')[0]} {rng.choice(pool).split(' ')[-1]}"
                    if name not in taken:
                        break
                taken.add(name)
                pid = f"sx{self.year}{k:04d}"
                k += 1
                self.players[pid] = {"id": pid, "src": src, "name": name, "nation": "India",
                                     "born": self.year - (y - born), "ref": ref, "overseas": False, "cap_year": None,
                                     "joined": self.year, "made_up": True, "form": {}, "retired": None, "teams": {}}
                self.squads[st][pid] = 0
                if st == self.user:
                    mine.append(name)
        out = [f"{k} young players make their state debuts."]
        if mine:
            out.append(f"New in {self.user}: {', '.join(mine)}.")
        moved = []
        cands = [pid for st in self.franchises for pid in self.squads[st]
                 if MOVE_AGES[0] <= self.age(pid) <= MOVE_AGES[1] and not self.capped(pid)]
        rng.shuffle(cands)
        for pid in cands:
            if len(moved) >= MOVES:
                break
            a = self._team_of(pid)
            to = [b for b in self.franchises if b != a and len(self.squads[b]) < SQUAD_MAX]
            if len(self.squads[a]) <= SQUAD_MIN or not to:
                continue
            b = rng.choice(to)
            self._move(pid, a, b)
            moved.append((pid, a, b))
        return out + self._move_news(moved)

    def _trim(self) -> list[str]:
        """Squads over SQUAD_MAX drop their least valuable players older than PROSPECT."""
        base = baseline(FMT, COMP, self.cond_year())
        mine = []
        for st in self.franchises:
            extra = len(self.squads[st]) - SQUAD_MAX
            if extra <= 0:
                continue
            cands = [pid for pid in self.squads[st] if self.age(pid) > PROSPECT]
            val = {pid: sum(value_parts(self.engine_player(pid), FMT, base)) for pid in cands}
            for pid in sorted(cands, key=lambda q: val[q])[:extra]:
                self._leave(pid, "dropped")
                if st == self.user:
                    mine.append(self.players[pid]["name"])
        return [f"Leaving the {self.user} squad: {', '.join(mine)}."] if mine else []

    # ---------------------------------------------------------------- views
    def squad_rows(self, t: str) -> list[dict]:
        rows = super().squad_rows(t)
        for r in rows:
            r.pop("price", None)
            r["nation"] = ""
        return sorted(rows, key=lambda r: (-(r["seasons"] or 0), r["age"]))

    def state(self) -> dict:
        titles: dict[str, int] = {}
        for h in self.history:
            titles[h["champion"]] = titles.get(h["champion"], 0) + 1
        return {"kind": "state", "name": self.name, "league": self.league, "league_label": self.league_label,
                "user": self.user, "start": self.start_season, "season": self.season_label, "year": self.year,
                "phase": self.phase, "teams": self.franchises, "groups": self.groups, "plate": self.plate,
                "format": self.format, "history": self.history, "titles": titles, "news": self.news,
                "squads": {t: self.squad_rows(t) for t in self.franchises}, "leaders": self.leaders(),
                "real": self.season_label in _presets(), "pool_size": len(self.active()),
                "matches": self.match_total()}


def load(d: dict) -> Career:
    """A saved career of either kind."""
    return (StateCareer if d.get("kind") == "state" else Career).from_json(d)
