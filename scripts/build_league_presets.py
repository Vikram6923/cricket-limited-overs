"""Latest-season squads for franchise leagues, from Cricsheet: everyone who played for each team that season.

    python scripts/build_league_presets.py        # IPL + BBL latest seasons -> data/league_seasons.json
                                                  # (+ IPL squads as saved-team presets)

A season is a calendar year (IPL) or July-June (BBL: 2025-26). A player is "overseas" if he has played
international cricket for a country other than the league's home country; teams get the league's overseas limit
(IPL 4, BBL 3) and the captain's XI respects it. Only rated players are kept.
"""
from __future__ import annotations

import json
import sys
import zipfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATS = ROOT / "data" / "raw_stats"
LEAGUES = {
    "ipl": {"label": "IPL", "home": "India", "max_overseas": 4, "season_start": 1, "zip": "ipl_json.zip"},
    "bbl": {"label": "BBL", "home": "Australia", "max_overseas": 3, "season_start": 7, "zip": "bbl_json.zip"},
}


def season_of(date: str, start_month: int) -> str:
    y, m = int(date[:4]), int(date[5:7])
    if start_month == 1:
        return str(y)
    y0 = y if m >= start_month else y - 1
    return f"{y0}-{str(y0 + 1)[-2:]}"


def latest_season(key: str, cfg: dict, rated: set, nation: dict) -> dict:
    with zipfile.ZipFile(ROOT / "data" / "raw" / "leagues" / cfg["zip"]) as zf:
        infos = [json.loads(zf.read(n))["info"] for n in zf.namelist() if n.endswith(".json")]
    infos = [i for i in infos if i.get("gender") == "male"]
    last = max(i["dates"][0] for i in infos)
    season = season_of(last, cfg["season_start"])
    apps: dict = {}
    for i in infos:
        if season_of(i["dates"][0], cfg["season_start"]) != season:
            continue
        reg = i["registry"]["people"]
        for team, names in i["players"].items():
            c = apps.setdefault(team, Counter())
            for n in names:
                if reg.get(n) in rated:
                    c[reg[n]] += 1
    teams = []
    for team in sorted(apps):
        ids = [pid for pid, _ in apps[team].most_common()]
        teams.append({"name": f"{team} {season}", "franchise": team, "players": ids,
                      "overseas": [p for p in ids if nation.get(p) not in (None, cfg["home"])],
                      "max_overseas": cfg["max_overseas"]})
    return {"league": key, "label": cfg["label"], "season": season, "year": int(last[:4]), "teams": teams,
            "matches": sum(1 for i in infos if season_of(i["dates"][0], cfg["season_start"]) == season)}


def main() -> int:
    ratings = json.loads((ROOT / "data" / "ratings_t20.json").read_text(encoding="utf-8"))["players"]
    rated = set(ratings)
    nation = {}
    for f in ("players_t20.json", "players_odi.json"):
        for pid, r in json.loads((STATS / f).read_text(encoding="utf-8")).items():
            if r.get("team"):
                nation.setdefault(pid, r["team"])
    out = {}
    for key, cfg in LEAGUES.items():
        s = latest_season(key, cfg, rated, nation)
        out[key] = s
        print(f"  {cfg['label']} {s['season']}: {len(s['teams'])} teams, {s['matches']} real matches; "
              + ", ".join(f"{t['franchise']} {len(t['players'])}/{len(t['overseas'])}os" for t in s["teams"]))
    (ROOT / "data" / "league_seasons.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    # IPL squads also as saved-team presets (Match / Series, Tournament)
    presets = [{"name": t["name"], "players": [{"id": p, "name": ratings[p]["name"]} for p in t["players"]],
                "overseas": t["overseas"], "max_overseas": t["max_overseas"]} for t in out["ipl"]["teams"]]
    for path in (ROOT / "data" / "teams_default.json", ROOT / "data" / "teams.json"):
        if path.exists():
            teams = json.loads(path.read_text(encoding="utf-8"))
            keep = {p["name"] for p in presets}
            teams = [t for t in teams if t["name"] not in keep] + presets
            path.write_text(json.dumps(teams, indent=1, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
