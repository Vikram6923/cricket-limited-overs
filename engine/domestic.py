"""Domestic cup seasons (data/domestic_seasons.json, scripts/build_domestic_presets.py) as tournaments.

    from engine.domestic import season, tournament_args
    from engine.tournament import play_tournament
    res = play_tournament(**tournament_args(season("sma", "2019-20")), seed=1)

A season carries its real groups, format (knockout, qualifiers per group, 4 points a win, the Plate) and venues;
tournament_args turns it into play_tournament's arguments. There are no home grounds: matches go round the
season's real venues (the group-stage ones, then the knockout ones).
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / "data" / "domestic_seasons.json"


@lru_cache(maxsize=1)
def competitions() -> dict:
    return json.loads(PATH.read_text(encoding="utf-8")) if PATH.exists() else {}


def season(comp: str, name: str | None = None) -> dict | None:
    """One season (the newest if name is None), with the competition's label."""
    c = competitions().get(comp)
    if not c:
        return None
    s = next((x for x in c["seasons"] if x["season"] == name), None) if name else c["seasons"][0]
    return {**s, "comp": comp, "label": c["label"]} if s else None


def tournament_args(s: dict, comp: str | None = None) -> dict:
    """play_tournament keyword arguments for a season (add seed, control, skill, rain, on_match as needed)."""
    squads = {t["name"]: t["players"] for t in s["teams"]}
    f = s["format"]

    def spec(name: str) -> dict:
        return {"name": name, "squad": squads[name]}
    elite = [n for g in f["groups"].values() for n in g]
    args = {"teams": [spec(n) for n in elite], "fmt": "t20", "comp": comp or s.get("comp") or "sma",
            "year": s["year"], "rounds": 1, "groups": [list(g) for g in f["groups"].values()],
            "advance": f["advance"], "knockout": f["knockout"], "win_points": f.get("win_points", 4),
            "venues": s.get("venues") or None, "knockout_venues": s.get("knockout_venues") or None}
    p = f.get("plate")
    if p:
        args["plate"] = {"teams": [spec(n) for n in p["teams"]], "knockout": p.get("knockout", "final"),
                         "advance": p.get("advance", 0)}
    return args


def match_total(s: dict) -> int:
    """How many matches the season's tournament plays (for progress bars)."""
    from .tournament import match_count
    f = s["format"]
    groups = [list(g) for g in f["groups"].values()]
    p = f.get("plate")
    plate = {"teams": len(p["teams"]), "knockout": p.get("knockout", "final"), "advance": p.get("advance", 0)} \
        if p else None
    return match_count(sum(len(g) for g in groups), 1, groups, f["knockout"], f["advance"], plate)
