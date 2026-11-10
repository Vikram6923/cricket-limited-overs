"""Syed Mushtaq Ali Trophy seasons from Cricsheet: squads, real groups, format and venues per season.

    python scripts/build_domestic_presets.py      -> data/domestic_seasons.json

Real seasons are the ones Cricsheet covers well enough to rebuild (2015-16, 2017-18 to 2021-22; 2022-23 onwards
has only a third of the matches or fewer). For each: the groups as played (read from the matches' event group),
that season's format (FORMATS below, checked against the knockout matches in the data), the group-stage and
knockout venues, and each state's squad = every rated player who played for it that season, most appearances
first. A state with fewer than 11 is topped up with its rated players from the nearest seasons and flagged.

"2025-26" is the latest season with the real groups and format (Wikipedia; Cricsheet has no matches from it):
squads are each rated player's latest state in the data, if he played SMAT in 2022-23 or later or any T20 match
(league or international) since ACTIVE_SINCE, most recent first. (Cricsheet has only a third of SMAT from 2022-23
on, so a domestic-only player can look inactive; both tests together miss fewer.) A state below 11 is filled with
its most recent other players. Transfers since a player's last SMAT match and players with no data are missing,
so it is flagged "latest".
"""
from __future__ import annotations

import json
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine.leagues import LEAGUES, zip_name  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "domestic_seasons.json"
CODE = "sma"
MIN_XI = 11
ACTIVE_SINCE = "2023-07-01"          # "latest" squads: played a T20 anywhere since then
NAMES = {"Himachal": "Himachal Pradesh", "Hyderabad (India)": "Hyderabad"}   # one name per state

# Each real season's format. Groups come from the data; these say what followed (checked against its knockouts).
FORMATS = {
    "2015-16": {"knockout": "super_league", "advance": 2},        # 4 groups -> Super League 4 + 4 -> final
    "2017-18": {"knockout": "super_league", "advance": 2},        # 5 zones -> Super League 5 + 5 -> final
    "2018-19": {"knockout": "super_league", "advance": 2},        # 5 groups -> Super League 5 + 5 -> final
    "2019-20": {"knockout": "super_league_semis", "advance": 2},  # 5 groups -> Super League 5 + 5 -> semis
    # 5 Elite groups + Plate: 5 winners, the 2 best runners-up and the Plate winner -> quarter-finals
    "2020-21": {"knockout": "qf", "advance": 2, "plate": {"knockout": "none", "advance": 1}},
    # 5 Elite groups + Plate: winners straight to the quarter-finals; 5 runners-up + the Plate winner play 3
    # preliminary quarter-finals
    "2021-22": {"knockout": "pre_qf", "advance": 2, "plate": {"knockout": "none", "advance": 1}},
}
# Real winner and runner-up (Wikipedia; Cricsheet lacks the 2017-18 final).
REAL = {"2015-16": ("Uttar Pradesh", "Baroda"), "2017-18": ("Delhi", "Rajasthan"),
        "2018-19": ("Karnataka", "Maharashtra"), "2019-20": ("Karnataka", "Tamil Nadu"),
        "2020-21": ("Tamil Nadu", "Baroda"), "2021-22": ("Tamil Nadu", "Karnataka"),
        "2025-26": ("Jharkhand", "Haryana")}
# 2025-26 (Wikipedia): 4 Elite groups of 8 -> top 2 to a Super League of two groups of 4 -> final; Plate of 6,
# top 2 play the Plate final.
LATEST = {
    "season": "2025-26", "year": 2025,
    "groups": {
        "A": ["Mumbai", "Vidarbha", "Andhra", "Kerala", "Railways", "Assam", "Chhattisgarh", "Odisha"],
        "B": ["Madhya Pradesh", "Uttar Pradesh", "Chandigarh", "Jammu & Kashmir", "Hyderabad", "Maharashtra", "Goa",
              "Bihar"],
        "C": ["Baroda", "Bengal", "Gujarat", "Punjab", "Haryana", "Himachal Pradesh", "Services", "Puducherry"],
        "D": ["Delhi", "Saurashtra", "Rajasthan", "Jharkhand", "Karnataka", "Tamil Nadu", "Uttarakhand", "Tripura"],
    },
    "plate": ["Manipur", "Mizoram", "Meghalaya", "Nagaland", "Sikkim", "Arunachal Pradesh"],
    "format": {"knockout": "super_league", "advance": 2, "plate": {"knockout": "final", "advance": 0}},
}


def season_of(date: str, start_month: int) -> str:
    y, m = int(date[:4]), int(date[5:7])
    y0 = y if m >= start_month else y - 1
    return f"{y0}-{str(y0 + 1)[-2:]}"


def load_matches() -> list[dict]:
    path = ROOT / "data" / "raw" / zip_name(CODE)
    with zipfile.ZipFile(path) as zf:
        games = [json.loads(zf.read(n))["info"] for n in zf.namelist() if n.endswith(".json")]
    games = [i for i in games if i.get("gender") == "male"]
    for i in games:
        i["teams"] = [NAMES.get(t, t) for t in i["teams"]]
        i["players"] = {NAMES.get(t, t): v for t, v in i["players"].items()}
        i["_season"] = season_of(i["dates"][0], LEAGUES[CODE].start)
    return sorted(games, key=lambda i: i["dates"][0])


def appearances(games: list[dict], rated: set) -> dict:
    """season -> team -> Counter of rated players' appearances."""
    out: dict = defaultdict(lambda: defaultdict(Counter))
    for i in games:
        reg = i["registry"]["people"]
        for team, names in i["players"].items():
            for n in names:
                if reg.get(n) in rated:
                    out[i["_season"]][team][reg[n]] += 1
    return out


def squad(apps: dict, season: str, team: str, seasons: list[str]) -> tuple[list[str], int]:
    """The season's players; topped up to 11 from the nearest seasons (returns how many were added)."""
    ids = [p for p, _ in apps[season][team].most_common()]
    added = 0
    if len(ids) < MIN_XI:
        k = seasons.index(season)
        for d in sorted(range(len(seasons)), key=lambda j: (abs(j - k), j)):
            for p, _ in apps[seasons[d]][team].most_common():
                if len(ids) >= MIN_XI:
                    break
                if p not in ids:
                    ids.append(p)
                    added += 1
    return ids, added


def venue_lists(games: list[dict]) -> tuple[list[str], list[str]]:
    group = Counter(i.get("venue", "") for i in games if not i.get("event", {}).get("stage"))
    ko = Counter(i.get("venue", "") for i in games if i.get("event", {}).get("stage"))
    return [v for v, _ in group.most_common() if v], [v for v, _ in ko.most_common() if v]


def real_season(season: str, games: list[dict], apps: dict, seasons: list[str]) -> dict:
    fmt = FORMATS[season]
    labelled: dict = defaultdict(set)
    for i in games:
        e = i.get("event", {})
        if e.get("group") and not e.get("stage"):
            for t in i["teams"]:
                labelled[e["group"]].add(t)
    plate_label = next((g for g in labelled if "plate" in g.lower()), None)
    elite = {g: sorted(v) for g, v in sorted(labelled.items()) if g != plate_label}
    teams = []
    for t in sorted({t for v in labelled.values() for t in v}):
        ids, added = squad(apps, season, t, seasons)
        teams.append({"name": t, "players": ids, "short": len(ids) < MIN_XI, "topped_up": added})
    venues, ko_venues = venue_lists(games)
    plate = None
    if plate_label:
        plate = {**fmt["plate"], "teams": sorted(labelled[plate_label]), "group_name": plate_label}
    w, r = REAL[season]
    return {"season": season, "year": int(max(i["dates"][0] for i in games)[:4]), "squads": "real",
            "format": {"groups": elite, "advance": fmt["advance"], "knockout": fmt["knockout"], "win_points": 4,
                       "plate": plate},
            "teams": teams, "venues": venues, "knockout_venues": ko_venues, "impact_player": False,
            "real": {"winner": w, "runner_up": r}, "matches_in_data": len(games)}


def last_t20() -> dict:
    """player -> date of his last T20 match anywhere (internationals and leagues, from the raw stats)."""
    out: dict = {}
    for f in ("players_t20.json", "players_t20_league.json"):
        for pid, r in json.loads((ROOT / "data" / "raw_stats" / f).read_text(encoding="utf-8")).items():
            if r.get("last") and r["last"] > out.get(pid, ""):
                out[pid] = r["last"]
    return out


def latest_season(games: list[dict], rated: set, seasons: list[str]) -> dict:
    last: dict = {}                                   # player -> (date, team, season)
    apps = Counter()
    for i in games:
        reg = i["registry"]["people"]
        for team, names in i["players"].items():
            for n in names:
                pid = reg.get(n)
                if pid in rated:
                    last[pid] = (i["dates"][0], team, i["_season"])
                    apps[pid] += 1
    by_team: dict = defaultdict(list)
    for pid, (date, team, season) in last.items():
        by_team[team].append((season, date, apps[pid], pid))
    active = {pid for pid, d in last_t20().items() if d >= ACTIVE_SINCE}
    recent = [s for s in seasons if s >= "2022-23"]
    names = [t for g in LATEST["groups"].values() for t in g] + LATEST["plate"]
    teams = []
    for t in names:
        rows = sorted(by_team.get(t, []), key=lambda x: (x[1], x[2]), reverse=True)
        ids = [r[3] for r in rows if r[0] in recent or r[3] in active]
        fill = [r[3] for r in rows if r[3] not in ids][:max(MIN_XI - len(ids), 0)]
        teams.append({"name": t, "players": ids + fill, "short": len(ids) + len(fill) < MIN_XI,
                      "topped_up": len(fill)})
    venues, ko_venues = venue_lists([i for i in games if i["_season"] in recent])
    w, r = REAL[LATEST["season"]]
    fmt = LATEST["format"]
    return {"season": LATEST["season"], "year": LATEST["year"], "squads": "latest",
            "format": {"groups": LATEST["groups"], "advance": fmt["advance"], "knockout": fmt["knockout"],
                       "win_points": 4, "plate": {**fmt["plate"], "teams": LATEST["plate"], "group_name": "Plate"}},
            "teams": teams, "venues": venues, "knockout_venues": ko_venues, "impact_player": False,
            "real": {"winner": w, "runner_up": r}, "matches_in_data": 0}


def main() -> int:
    rated = set(json.loads((ROOT / "data" / "ratings_t20.json").read_text(encoding="utf-8"))["players"])
    games = load_matches()
    apps = appearances(games, rated)
    seasons = sorted({i["_season"] for i in games})
    out = [latest_season(games, rated, seasons)]
    for s in sorted(FORMATS, reverse=True):
        out.append(real_season(s, [i for i in games if i["_season"] == s], apps, seasons))
    data = {CODE: {"label": "Syed Mushtaq Ali Trophy", "short": "SMAT", "seasons": out}}
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    for s in out:
        n = len(s["teams"])
        short = [t["name"] for t in s["teams"] if t["short"]]
        topped = [f"{t['name']} +{t['topped_up']}" for t in s["teams"] if t["topped_up"]]
        sizes = sorted(len(t["players"]) for t in s["teams"])
        print(f"{s['season']}: {n} teams, squads {sizes[0]}-{sizes[-1]} (median {sizes[n // 2]}), "
              f"{s['format']['knockout']}, groups {[len(v) for v in s['format']['groups'].values()]}"
              f"{' + Plate ' + str(len(s['format']['plate']['teams'])) if s['format']['plate'] else ''}"
              f"{'; under 11: ' + ', '.join(short) if short else ''}"
              f"{'; topped up: ' + ', '.join(topped) if topped else ''}")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
