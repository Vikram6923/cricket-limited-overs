"""Test career totals for every Test cricketer since 1877, and the era table, from the old Test simulator's data.

Cricsheet's Test ball-by-ball data starts in 2001 and is complete only from about 2007, so most Test cricketers
have no ball-by-ball record. The old Test simulator (the sibling folder ../cricket, forked from
github.com/Jamee999/cricket) holds one row of career totals per Test cricketer, collected from ESPNcricinfo before
it blocked scraping and kept up to date since: Tests, runs, balls faced (where recorded), dismissals, balls
bowled, runs conceded, wickets, first and last year, first-class record, year of birth, Tests as captain and as
wicketkeeper, innings as opener, bowling style. This script only READS that folder and writes our own files:

    data/raw_stats/test_careers.json    one record per player: the totals, linked to a Cricsheet ID where he
                                        has one (by name, checked against his Cricsheet Tests), and his part
                                        before / outside Cricsheet = totals minus data/raw_stats/players_test.json
    data/raw_stats/years_test_pre.json  runs per wicket and runs per over by year, 1877 onward (eradata.txt and
                                        er_data.txt: smoothed yearly averages)

The output files are committed, so the old folder is needed only to rebuild them.

    python scripts/build_pre_tests.py [--source ../cricket]
"""
from __future__ import annotations

import argparse
import ast
import csv
import json
import re
import sys
from pathlib import Path

from fetch_styles import classify_bowling

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
STATS = ROOT / "data" / "raw_stats"
NATIONS = {"england": "England", "australia": "Australia", "southafrica": "South Africa",
           "westindies": "West Indies", "newzealand": "New Zealand", "india": "India", "pakistan": "Pakistan",
           "srilanka": "Sri Lanka", "zimbabwe": "Zimbabwe", "bangladesh": "Bangladesh",
           "afghanistan": "Afghanistan", "ireland": "Ireland"}
# Row layout of <nation>players.txt (cricinfoscrape.py in the old project).
COLS = ("name", "bowl_style", "tests", "runs", "balls_faced", "outs", "balls", "runs_conceded", "wkts", "first",
        "last", "fc_matches", "fc_runs", "fc_bat_avg", "fc_wkts", "fc_bowl_avg", "born", "captain", "keeper_tests",
        "opened")
SUMMED = ("tests", "runs", "balls_faced", "outs", "balls", "runs_conceded", "wkts", "captain", "keeper_tests",
          "opened")


def _n(v):
    """Number, or None for '', '-' and other blanks."""
    if isinstance(v, (int, float)):
        return v
    try:
        return float(v) if "." in str(v) else int(v)
    except (TypeError, ValueError):
        return None


def read_rows(src: Path) -> list[dict]:
    rows = []
    for key, nation in NATIONS.items():
        path = src / f"{key}players.txt"
        if not path.exists():
            print(f"  missing {path.name}, skipped", file=sys.stderr)
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            vals = list(ast.literal_eval(line))
            vals += [0] * (len(COLS) - len(vals))
            r = dict(zip(COLS, vals))
            r["nation"] = nation
            rows.append(r)
    return rows


def full_names(src: Path) -> dict[str, str]:
    out = {}
    path = src / "names.txt"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            short, _, full = line.partition(", ")
            if full.strip():
                out[short.strip()] = full.strip()
    return out


def era_table(src: Path) -> dict:
    """year -> {"runs_per_wkt", "rpo"}. er_data.txt lists some years twice; the later line wins."""
    out: dict = {}
    for fname, key in (("eradata.txt", "runs_per_wkt"), ("er_data.txt", "rpo")):
        for line in (src / fname).read_text(encoding="utf-8").splitlines():
            y, _, v = line.partition(",")
            if y.strip().isdigit() and v.strip():
                out.setdefault(y.strip(), {})[key] = float(v)
    return {y: row for y, row in sorted(out.items()) if len(row) == 2}


def merge_two_nations(rows: list[dict]) -> list[dict]:
    """A man who played Tests for two countries has a row under each: same name and year of birth. Most such
    rows repeat his whole career (Kardar, Wessels, Rankin), and a few rows are plain repeats; those are counted
    once. Where the two rows differ they are his two parts (Ballance, Moor) and are added up. The career goes
    under the country he played more Tests for (the first listed, if equal)."""
    seen: dict = {}
    out = []
    for r in rows:
        r["tests"] = _n(r["tests"]) or 0
        if not r["tests"]:
            continue
        r["nations"] = [r["nation"]]
        key = (r["name"], r["born"])
        a = seen.get(key) if _n(r["born"]) else None
        if a is None:
            seen[key] = r
            out.append(r)
            continue
        if r["nation"] not in a["nations"]:
            a["nations"].append(r["nation"])
        if (r["tests"], r["runs"], r["wkts"]) == (a["tests"], a["runs"], a["wkts"]):
            continue
        if r["tests"] > a["tests"]:
            a["nation"] = r["nation"]
        for k in SUMMED:
            x, y = _n(a[k]), _n(r[k])
            if k == "balls_faced" and (x is None or y is None):
                a[k] = None        # balls faced known for one country only: unknown for the career
            else:
                a[k] = (x or 0) + (y or 0) if x is not None or y is not None else None
        a["first"], a["last"] = min(a["first"], r["first"]), max(a["last"], r["last"])
    return out


def _initials_surname(name: str) -> tuple[str, str]:
    parts = name.replace(".", " ").split()
    return (parts[0] if len(parts) > 1 else ""), (parts[-1] if parts else "")


def link_rows(rows: list[dict], people: list[dict], cs: dict, names: dict) -> dict[int, dict]:
    """Row index -> {"id", "cricsheet_id", "cricinfo_id", "name"}: the player's ID in this project.

    Names repeat (two SP Joneses, five Rashid Khans) and the register spells some old players differently
    (M Hughes, Kepler Wessels), so a name alone is not enough. In order:
    1. players already identified for the ODI ratings (pre2002_players.json, afghanistan_players.json: IDs
       confirmed through Wikidata), by full name and country, so a player has one ID in every format;
    2. the Cricsheet register (people.csv) by name. An entry fits a row if its Cricsheet Test record, when it has
       one, is for one of the row's countries and inside the row's years; if it has none, the row must be one
       Cricsheet would not cover (ended by 2008) and the entry's ESPNcricinfo number must be from the same
       generation (numbers below 60,000 were given to players of the 20th century);
    3. the same with the surname and initials that begin the same way ('A Parore' for AC Parore);
    4. spelling differences: see the last loop."""
    by_name: dict = {}
    by_surname: dict = {}
    for p in people:
        for nm in {p["name"], p["unique_name"]}:
            by_name.setdefault(nm, []).append(p)
        by_surname.setdefault(_initials_surname(p["name"])[1], []).append(p)

    def fits(p: dict, r: dict) -> int:
        """0 = no; 2 = his Cricsheet Test record agrees; 1 = no Test record, but plausible."""
        c = cs.get(p["identifier"])
        if c:
            y = int(c["first"][:4])
            return 2 if set(c["teams"]) & set(r["nations"]) and r["first"] <= y <= r["last"] + 1 else 0
        if r["last"] > 2008:
            return 0
        if not p["key_cricinfo"].isdigit():
            return 0
        return 1 if (int(p["key_cricinfo"]) < 60000) == (r["first"] <= 2003) else 0

    def entry(p: dict) -> dict:
        return {"id": p["identifier"], "cricsheet_id": p["identifier"], "cricinfo_id": p["key_cricinfo"] or None,
                "name": p["name"]}

    link: dict[int, dict] = {}
    used: set = set()
    reg = {p["identifier"]: p for p in people}
    known: dict = {}                                  # (full name, country) -> [ID record]
    pre = STATS / "pre2002_players.json"
    for q in (json.loads(pre.read_text(encoding="utf-8")) if pre.exists() else {}).values():
        known.setdefault((q["name"], q["nation"]), []).append(
            {"id": q["id"], "cricsheet_id": q.get("cricsheet_id"), "cricinfo_id": q.get("cricinfo_id")})
    afg = STATS / "afghanistan_players.json"
    for q in (json.loads(afg.read_text(encoding="utf-8")) if afg.exists() else []):
        if q.get("cricsheet_id"):
            for nm in {q["name"], q.get("cricsheet_name") or q["name"]}:
                known.setdefault((nm, "Afghanistan"), []).append(
                    {"id": q["cricsheet_id"], "cricsheet_id": q["cricsheet_id"], "cricinfo_id": q.get("cricinfo_id")})
    for k, r in enumerate(rows):
        if r["first"] > 2001 and "Afghanistan" not in r["nations"]:
            continue
        hits = {h["id"]: h for nm in {names.get(r["name"]), r["name"]} for nat in r["nations"]
                for h in known.get((nm, nat), [])}
        hits = [h for h in hits.values() if h["id"] not in used
                and (h["cricsheet_id"] not in cs or fits(reg[h["cricsheet_id"]], r))]
        if len(hits) == 1:
            h = hits[0]
            person = reg.get(h["cricsheet_id"] or "")
            link[k] = {**h, "name": person["name"] if person and h["cricsheet_id"] in cs else r["name"]}
            used.add(h["id"])
    for exact in (True, False):
        for k, r in enumerate(rows):
            if k in link:
                continue
            if exact:
                cands = by_name.get(r["name"], [])
            else:   # 'A Parore' for AC Parore: same surname, initials that begin the same way
                ini, sur = _initials_surname(re.sub(r"\s*\(\d+\)$", "", r["name"]))
                cands = [p for p in by_surname.get(sur, [])
                         if ini and _initials_surname(p["name"])[0].startswith(ini)]
            scored = [(fits(p, r), p) for p in cands if p["identifier"] not in used]
            best = max((s for s, _ in scored), default=0)
            top = [p for s, p in scored if s == best and s > 0]
            if len(top) == 1:
                link[k] = entry(top[0])
                used.add(top[0]["identifier"])
    # Last: spelling differences (Mehidy / Mehedi Hasan Miraz). An unlinked row and an unlinked Cricsheet Test
    # player of the same country who began in the same year with nearly the same number of Tests and runs.
    free = {pid: c for pid, c in cs.items() if pid not in used}
    for k, r in enumerate(rows):
        if k in link or r["last"] < 2001:
            continue
        m = [pid for pid, c in free.items()
             if set(c["teams"]) & set(r["nations"]) and abs(int(c["first"][:4]) - r["first"]) <= 1
             and abs(c["matches"] - r["tests"]) <= max(3, 0.1 * r["tests"])
             and abs(c["bat"]["runs"] - (_n(r["runs"]) or 0)) <= max(30, 0.12 * c["bat"]["runs"])]
        if len(m) == 1 and m[0] in reg:
            link[k] = entry(reg[m[0]])
            used.add(m[0])
            del free[m[0]]
    return link


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", type=Path, help="the old Test simulator's folder (read only); default: the "
                    "'cricket' folder beside this project")
    args = ap.parse_args(argv)
    # Beside the project; from a git worktree the project is a few folders further up.
    found = [a.parent / "cricket" for a in (ROOT, *ROOT.parents)
             if (a.parent / "cricket" / "englandplayers.txt").exists()]
    src = args.source or (found[0] if found else ROOT.parent / "cricket")
    if not (src / "englandplayers.txt").exists():
        print(f"{src} does not hold the old simulator's <nation>players.txt files; pass --source", file=sys.stderr)
        return 1

    with open(RAW / "people.csv", encoding="utf-8", newline="") as f:
        people = list(csv.DictReader(f))
    cs = json.loads((STATS / "players_test.json").read_text(encoding="utf-8"))
    names = full_names(src)
    rows = merge_two_nations(read_rows(src))
    link = link_rows(rows, people, cs, names)

    out: dict = {}
    n_part = n_only = 0
    for k, r in enumerate(rows):
        tests = int(r["tests"])
        person = link.get(k)
        csid = person["cricsheet_id"] if person else None
        pid = person["id"] if person else (
            "tc_" + re.sub(r"\W+", "_", f"{r['nation']} {r['name']} {r['first']}").strip("_").lower())
        style = classify_bowling(str(r["bowl_style"] or "").replace(" arm ", "-arm "))
        tot = {c: _n(r[c]) for c in ("runs", "balls_faced", "outs", "balls", "runs_conceded", "wkts")}
        rec = {"id": pid, "name": person["name"] if person else r["name"],
               "full_name": names.get(r["name"]), "nation": r["nation"], "nations": r["nations"],
               "cricsheet_id": csid, "cricinfo_id": person["cricinfo_id"] if person else None,
               "first": int(r["first"]), "last": int(r["last"]), "tests": tests, **tot,
               "born": _n(r["born"]) or None, "captain": int(_n(r["captain"]) or 0),
               "keeper_tests": int(_n(r["keeper_tests"]) or 0), "opened": int(_n(r["opened"]) or 0),
               "bowl_style": r["bowl_style"] if style["type"] else None, "bowl_type": style["type"],
               "bowl_kind": style["kind"], "bowl_arm": style["arm"],
               "fc": {"matches": _n(r["fc_matches"]), "runs": _n(r["fc_runs"]), "bat_avg": _n(r["fc_bat_avg"]),
                      "wkts": _n(r["fc_wkts"]), "bowl_avg": _n(r["fc_bowl_avg"])}}
        # The part of his career Cricsheet does not have: totals minus the ball-by-ball record. "pre" is None
        # when Cricsheet has (nearly) all of it.
        c = cs.get(csid) if csid else None
        if c is None:
            rec["pre"] = {"tests": tests, **tot, "first": rec["first"], "last": rec["last"]}
            n_only += 1
        else:
            def sub(a, b):
                return None if a is None else max(a - b, 0)
            miss = tests - c["matches"]
            if miss >= 3:      # 1-2 Tests of difference are a late update or a withheld match, not a career part
                first_cs = int(c["first"][:4])
                # Cricsheet is thin up to 2006: the uncovered Tests of a career that began by then are spread to
                # 2006 (or to the year before his first covered Test, if later).
                last = min(rec["last"], max(first_cs - 1, 2006)) if rec["first"] <= 2006 else rec["last"]
                rec["pre"] = {"tests": miss, "runs": sub(tot["runs"], c["bat"]["runs"]),
                              "balls_faced": sub(tot["balls_faced"], c["bat"]["balls"]),
                              "outs": sub(tot["outs"], c["bat"]["outs"]),
                              "balls": sub(tot["balls"], c["bowl"]["balls"]),
                              "runs_conceded": sub(tot["runs_conceded"], c["bowl"]["runs"]),
                              "wkts": sub(tot["wkts"], c["bowl"]["wkts"]),
                              "first": rec["first"], "last": max(rec["first"], last)}
                n_part += 1
            else:
                rec["pre"] = None
        if pid in out:
            print(f"  two players with id {pid}: {out[pid]['name']} ({out[pid]['nation']} {out[pid]['first']}) / "
                  f"{rec['name']} ({rec['nation']} {rec['first']}); the second is skipped", file=sys.stderr)
            continue
        out[pid] = rec
    n_linked = sum(1 for r in out.values() if not r["id"].startswith("tc_"))
    not_found = sorted(c["name"] for pid, c in cs.items() if pid not in out)
    if not_found:
        print(f"  {len(not_found)} Cricsheet Test players with no career row (rated from ball-by-ball only): "
              + ", ".join(not_found), file=sys.stderr)

    STATS.mkdir(parents=True, exist_ok=True)
    (STATS / "test_careers.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")),
                                             encoding="utf-8")
    eras = era_table(src)
    (STATS / "years_test_pre.json").write_text(json.dumps(eras, indent=1), encoding="utf-8")
    print(f"test_careers.json: {len(out)} players, {n_linked} with a known ID; {n_only} with no "
          f"ball-by-ball record, {n_part} with a part outside it")
    print(f"years_test_pre.json: {len(eras)} years, {min(eras)}-{max(eras)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
