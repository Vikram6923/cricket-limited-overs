"""Franchise league seasons from Cricsheet: each team's squad (everyone who played for it that season).

    python scripts/build_league_presets.py        # every season of the 11 leagues -> data/league_seasons.json
                                                  # (+ the latest IPL squads as saved-team presets)

A season is a calendar year, or July-June for leagues that run over the new year (BBL, Super Smash, SA20, ILT20,
BPL: "2025-26"). A player is "overseas" if he has played international cricket for a country other than the
league's home country. The overseas limit per XI is taken from the data: the most overseas players any real XI
fielded that season (rules differ by league and have changed over time). Only rated players are kept.
"""
from __future__ import annotations

import json
import sys
import zipfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATS = ROOT / "data" / "raw_stats"
LEAGUES = {   # label, home country, first month of a season
    "ipl": ("IPL", "India", 1), "bbl": ("BBL", "Australia", 7), "psl": ("PSL", "Pakistan", 1),
    "cpl": ("CPL", "West Indies", 1), "sat": ("SA20", "South Africa", 7), "ilt": ("ILT20", "United Arab Emirates", 7),
    "bpl": ("BPL", "Bangladesh", 7), "lpl": ("LPL", "Sri Lanka", 1), "mlc": ("MLC", "United States of America", 1),
    "ntb": ("T20 Blast", "England", 1), "ssm": ("Super Smash", "New Zealand", 7),
}
MIN_TEAMS, MIN_MATCHES = 4, 10


def season_of(date: str, start_month: int) -> str:
    y, m = int(date[:4]), int(date[5:7])
    if start_month == 1:
        return str(y)
    y0 = y if m >= start_month else y - 1
    return f"{y0}-{str(y0 + 1)[-2:]}"


def league_seasons(key: str, rated: set, nation: dict) -> list[dict]:
    label, home, start = LEAGUES[key]
    path = ROOT / "data" / "raw" / "leagues" / f"{key}_json.zip"
    if not path.exists():
        return []
    with zipfile.ZipFile(path) as zf:
        games_all = [json.loads(zf.read(n)) for n in zf.namelist() if n.endswith(".json")]
    by: dict = {}
    for m in games_all:
        i = m["info"]
        if i.get("gender") == "male":
            # Impact Player swaps: the team list then has 12 names, but only 11 are on the field at a time
            i["_swaps"] = {r["team"]: (r["in"], r["out"]) for inn in m.get("innings", []) for ov in inn.get("overs", [])
                           for d in ov["deliveries"] for r in d.get("replacements", {}).get("match", [])
                           if r.get("reason") == "impact_player"}
            by.setdefault(season_of(i["dates"][0], start), []).append(i)
    out = []
    for season, games in by.items():
        apps: dict = {}
        grounds: dict = {}            # team -> Counter of venues played at (home ground = the most used)
        xi_os = Counter()             # overseas players on the field, per XI
        for i in games:
            reg = i["registry"]["people"]
            for team in i["players"]:
                grounds.setdefault(team, Counter())[i.get("venue", "")] += 1
            for team, names in i["players"].items():
                c = apps.setdefault(team, Counter())
                for n in names:
                    if reg.get(n) in rated:
                        c[reg[n]] += 1
                os_ = {n for n in names if nation.get(reg.get(n)) not in (None, home)}
                sw = i["_swaps"].get(team)
                xi_os[max(len(os_ - {sw[0]}), len(os_ - {sw[1]})) if sw else len(os_)] += 1
        # the limit: the most overseas players fielded by at least 5 XIs that season (ignores one-off oddities)
        max_os = max((k for k, v in xi_os.items() if v >= 5), default=max(xi_os, default=0))
        teams = []
        for team in sorted(apps):
            ids = [pid for pid, _ in apps[team].most_common()]
            if len(ids) < 11:
                continue
            home_ground = next((v for v, _ in grounds[team].most_common() if v), None)
            teams.append({"name": f"{team} {season}", "franchise": team, "home_venue": home_ground, "players": ids,
                          "overseas": [p for p in ids if nation.get(p) not in (None, home)], "max_overseas": max_os})
        if len(teams) >= MIN_TEAMS and len(games) >= MIN_MATCHES:
            out.append({"season": season, "year": int(max(i["dates"][-1] for i in games)[:4]), "teams": teams,
                        "matches": len(games), "max_overseas": max_os})
    return sorted(out, key=lambda s: s["season"], reverse=True)


def main() -> int:
    ratings = json.loads((ROOT / "data" / "ratings_t20.json").read_text(encoding="utf-8"))["players"]
    rated = set(ratings)
    nation = {}
    for f in ("players_t20.json", "players_odi.json"):
        for pid, r in json.loads((STATS / f).read_text(encoding="utf-8")).items():
            if r.get("team"):
                nation.setdefault(pid, r["team"])
    out = {}
    for key, (label, home, _) in LEAGUES.items():
        seasons = league_seasons(key, rated, nation)
        if seasons:
            out[key] = {"label": label, "home": home, "seasons": seasons}
            print(f"  {label}: {len(seasons)} seasons ({seasons[-1]['season']} - {seasons[0]['season']}); overseas "
                  f"limit by season: {', '.join(str(s['max_overseas']) for s in reversed(seasons))}")
    (ROOT / "data" / "league_seasons.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    # the latest IPL squads also as saved-team presets (Match / Series, Tournament)
    latest = out["ipl"]["seasons"][0]
    presets = [{"name": t["name"], "players": [{"id": p, "name": ratings[p]["name"]} for p in t["players"]],
                "overseas": t["overseas"], "max_overseas": t["max_overseas"], "home_venue": t["home_venue"]} for t in latest["teams"]]
    for path in (ROOT / "data" / "teams_default.json", ROOT / "data" / "teams.json"):
        if path.exists():
            teams = json.loads(path.read_text(encoding="utf-8"))
            keep = {p["name"] for p in presets}
            teams = [t for t in teams if t["name"] not in keep] + presets
            path.write_text(json.dumps(teams, indent=1, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
