"""Historical teams: a nation over a year range ("India 2007-2011"), as in the Test sim's Classic modes.

The squad is the most-capped players for that nation in those years (international matches from Cricsheet: ODIs
from ~2002, T20Is from 2005), 20 by default, with at least one keeper. Ratings are for that period
(engine/periods.py) and batting slots are those of the period. The captain picks the best XI from the squad for each
match, as in the Test sim.

Why 20: a player with only a few games in the period is rated mostly on his career (that is what predicts best,
scripts/validate_periods.py), so with everyone who played in the pool the captain picks one-series players such as
Prithvi Shaw for India 2021-24 ODIs or a 2009 Jayasuriya for Sri Lanka 2009-14. With 15, regulars fall out when
second-string sides played many games (Kohli and Jadeja in India's 2024 T20Is). The UI lets the user choose.
"""
from __future__ import annotations

import json
from functools import lru_cache

from .data import DATA, _keepers

FULL_MEMBERS = {"Afghanistan", "Australia", "Bangladesh", "England", "India", "Ireland", "New Zealand", "Pakistan",
                "South Africa", "Sri Lanka", "West Indies", "Zimbabwe"}   # as in scripts/build_ratings.py
SQUAD_SIZE = 20   # default squad: the 20 most-capped players of the period
MIN_PLAYERS = 15  # a nation needs this many players in the period to be offered


@lru_cache(maxsize=None)
def _intl_years(fmt: str) -> dict:
    """pid -> {year: {team: matches}} for international matches only."""
    path = DATA / "raw_stats" / ("players_odi.json" if fmt == "odi" else "players_t20.json")
    out = {}
    for pid, r in json.loads(path.read_text(encoding="utf-8")).items():
        out[pid] = {int(y): rec.get("teams") or {} for y, rec in (r.get("by_year") or {}).items()}
    if fmt == "odi":   # before Cricsheet: Wikipedia career totals, matches spread evenly over the years
        pre = DATA / "raw_stats" / "pre2002_players.json"
        for pid, q in (json.loads(pre.read_text(encoding="utf-8")) if pre.exists() else {}).items():
            ys = range(q["first"], q["last"] + 1)
            if not q.get("matches") or not ys:
                continue
            by = out.setdefault(pid, {})
            for y in ys:
                if y not in by:
                    by[y] = {q["nation"]: q["matches"] / len(ys)}
    return out


def first_year(fmt: str) -> int:
    return min(y for by in _intl_years(fmt).values() for y in by)


def last_year(fmt: str) -> int:
    return max(y for by in _intl_years(fmt).values() for y in by)


def appearances(fmt: str, nation: str, y1: int, y2: int) -> dict:
    """pid -> matches for the nation in [y1, y2]."""
    out = {}
    for pid, by in _intl_years(fmt).items():
        n = sum(t.get(nation, 0) for y, t in by.items() if y1 <= y <= y2)
        if n:
            out[pid] = n
    return out


@lru_cache(maxsize=256)
def nations(fmt: str, y1: int, y2: int, min_players: int = MIN_PLAYERS) -> tuple:
    """Nations with at least min_players players in the period, most matches first: ((name, approx matches), ...)."""
    apps: dict = {}
    for by in _intl_years(fmt).values():
        for y, teams in by.items():
            if y1 <= y <= y2:
                for t, n in teams.items():
                    a = apps.setdefault(t, [0, 0])
                    a[0] += n
    for t in apps:
        apps[t][1] = len(appearances(fmt, t, y1, y2))
    rows = [(t, round(a[0] / 11)) for t, a in apps.items() if a[1] >= min_players]
    return tuple(sorted(rows, key=lambda r: (-r[1], r[0])))


def squad(fmt: str, nation: str, y1: int, y2: int, size: int | None = None) -> list[str]:
    """Players for the nation in the period, most-capped first (the first `size` if given, keeping a keeper)."""
    apps = appearances(fmt, nation, y1, y2)
    ranked = sorted(apps, key=lambda p: (-apps[p], p))
    if size is None:
        return ranked
    out = ranked[:size]
    keepers = _keepers(fmt)
    if out and not any(p in keepers for p in out):
        k = next((p for p in ranked[size:] if p in keepers), None)
        if k:
            out[-1] = k
    return out


def team_name(nation: str, y1: int, y2: int) -> str:
    return f"{nation} {y1}" if y1 == y2 else f"{nation} {y1}-{str(y2)[-2:] if str(y1)[:2] == str(y2)[:2] else y2}"


def historical_team(fmt: str, nation: str, y1: int, y2: int, size: int | None = SQUAD_SIZE,
                    name: str | None = None, years_mode: str = "blend") -> dict:
    """Team spec for engine.match / engine.tournament: {"name", "squad", "years", "years_mode"}."""
    ids = squad(fmt, nation, y1, y2, size)
    if len(ids) < 11:
        raise ValueError(f"Only {len(ids)} players played for {nation} in {fmt.upper()}s in {y1}-{y2}.")
    return {"name": name or team_name(nation, y1, y2), "squad": ids, "years": [y1, y2], "years_mode": years_mode,
            "nation": nation}
