"""Preset squads for a franchise league season, from Cricsheet: everyone who played for each team that season.

    python scripts/build_league_presets.py               # IPL 2026 -> data/teams_default.json (and data/teams.json)

A player is "overseas" if he has played international cricket for a country other than the league's home country
(Cricsheet T20I / ODI records); the team gets max_overseas (IPL: 4) and the captain's XI respects it.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATS = ROOT / "data" / "raw_stats"
LEAGUES = {"ipl": {"home": "India", "max_overseas": 4,
                   "teams": ["Chennai Super Kings", "Delhi Capitals", "Gujarat Titans", "Kolkata Knight Riders",
                             "Lucknow Super Giants", "Mumbai Indians", "Punjab Kings", "Rajasthan Royals",
                             "Royal Challengers Bengaluru", "Sunrisers Hyderabad"]}}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", default="ipl", choices=sorted(LEAGUES))
    ap.add_argument("--year", type=int, default=2026)
    a = ap.parse_args(argv)
    cfg = LEAGUES[a.league]
    lg = json.loads((STATS / "players_t20_league.json").read_text(encoding="utf-8"))
    rated = set(json.loads((ROOT / "data" / "ratings_t20.json").read_text(encoding="utf-8"))["players"])
    nation = {}
    for f in ("players_t20.json", "players_odi.json"):
        for pid, r in json.loads((STATS / f).read_text(encoding="utf-8")).items():
            if r.get("team"):
                nation.setdefault(pid, r["team"])
    presets = []
    for team in cfg["teams"]:
        rows = []
        for pid, r in lg.items():
            n = (((r.get("by_year") or {}).get(str(a.year)) or {}).get("teams") or {}).get(team, 0)
            if n and pid in rated:     # unrated (no balls in the data) can't be used
                rows.append((n, pid, r["name"]))
        rows.sort(reverse=True)
        if not rows:
            print(f"  {team}: no {a.year} matches, skipped")
            continue
        overseas = [pid for _, pid, _ in rows if nation.get(pid) not in (None, cfg["home"])]
        presets.append({"name": f"{team} {a.year}", "players": [{"id": pid, "name": nm} for _, pid, nm in rows],
                        "overseas": overseas, "max_overseas": cfg["max_overseas"]})
        print(f"  {team} {a.year}: {len(rows)} players, {len(overseas)} overseas")
    for path in (ROOT / "data" / "teams_default.json", ROOT / "data" / "teams.json"):
        if not path.exists():
            continue
        teams = json.loads(path.read_text(encoding="utf-8"))
        names = {p["name"] for p in presets}
        teams = [t for t in teams if t["name"] not in names] + presets
        path.write_text(json.dumps(teams, indent=1, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
