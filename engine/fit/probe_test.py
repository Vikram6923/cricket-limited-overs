"""Data probes for the Test engine: how many balls each planned cell has, and what the raw rates look like.

Nothing is fitted here. The tables decide the cells of the Test situation model, the ball-age and pitch-wear
tables and the declaration and follow-on fits (docs/test_match_plan.md, sections 2-4); they are copied into
docs/test_design.md. Rates are raw (not adjusted for who was batting or bowling), so they show sample sizes and
rough shapes only.

    python -m engine.fit.probe_test            (reads data/raw/tests_male_json.zip)
"""
from __future__ import annotations

import json
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

from .fit_basics import bowl_types

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
BOWLER_WICKETS = {"bowled", "caught", "caught and bowled", "lbw", "stumped", "hit wicket"}
NOT_OUT = {"retired hurt", "retired not out"}


def bucket(x: float, edges: tuple) -> str:
    """'lo-hi' label of the bucket x falls in; the last bucket is open ('200+')."""
    for lo, hi in zip(edges, edges[1:]):
        if x < hi:
            return f"{lo}-{hi - 1}"
    return f"{edges[-1]}+"


class Cell:
    """balls, runs off the bat, bowler's wickets, all dismissals."""
    __slots__ = ("balls", "runs", "wkts", "outs")

    def __init__(self):
        self.balls = self.runs = self.wkts = self.outs = 0

    def row(self) -> str:
        b = max(self.balls, 1)
        avg = f"{self.runs / self.outs:6.1f}" if self.outs else "     -"
        return f"{self.balls:8d} {6 * self.runs / b:5.2f} {600 * self.wkts / b:6.2f} {avg}"


HEAD = f"{'balls':>8} {'rpo':>5} {'w/100ov':>7} {'avg':>6}"


def table(title: str, cells: dict, order=None) -> None:
    print(f"\n{title}")
    keys = order or sorted(cells)
    width = max(len(str(k)) for k in keys) + 2
    print(f"{'':{width}}{HEAD}")
    for k in keys:
        if k in cells:
            print(f"{str(k):{width}}{cells[k].row()}")


def main() -> int:
    path = RAW / "tests_male_json.zip"
    if not path.exists():
        print("data/raw/tests_male_json.zip is missing; run scripts/fetch_cricsheet.py", file=sys.stderr)
        return 1
    btype = bowl_types("test")
    age_e, wear_e, faced_e = (0, 10, 20, 40, 60, 80), (0, 90, 180, 270, 360), (0, 10, 30, 60, 120, 200)
    wk_e, lead_e = (0, 3, 6, 10), (-10 ** 6, -199, -99, 0, 100, 200, 350)
    age, wear, sit, faced, lead = (defaultdict(Cell) for _ in range(5))
    results, days, n_inns, declared, inns_len = Counter(), Counter(), Counter(), Counter(), defaultdict(list)
    fo_chance = fo_enforced = 0
    fo_by_lead = defaultdict(lambda: [0, 0])
    decl_lead = defaultdict(list)
    chase = defaultdict(Counter)
    overs_per_day = []
    n = 0
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if not name.endswith(".json"):
                continue
            m = json.loads(z.read(name))
            info, inns = m["info"], m.get("innings", [])
            if info.get("gender") != "male" or info.get("balls_per_over", 6) != 6:
                continue
            n += 1
            reg = info["registry"]["people"]
            o = info["outcome"]
            by = o.get("by") or {}
            res = ("draw" if o.get("result") == "draw" else "tie" if o.get("result") == "tie" else
                   "innings" if "innings" in by else "runs" if "runs" in by else
                   "wickets" if "wickets" in by else "other")
            results[res] += 1
            days[len(info["dates"])] += 1
            n_inns[len(inns)] += 1
            match_overs = 0
            totals = defaultdict(int)          # team -> runs so far in the match
            for k, inn in enumerate(inns):
                team = inn["team"]
                other = [t for t in info["teams"] if t != team][0]
                if k == 2:                      # the follow-on: the side that batted second bats again
                    d = totals[inns[0]["team"]] - totals[inns[1]["team"]]
                    if d >= 200:
                        fo_chance += 1
                        enforced = inn["team"] == inns[1]["team"]
                        fo_enforced += enforced
                        b = fo_by_lead[bucket(d, (200, 250, 300, 400))]
                        b[0] += 1
                        b[1] += enforced
                start_lead = totals[team] - totals[other]
                runs = wkts = legal = 0
                bf = Counter()
                for ov in inn.get("overs", []):
                    a = bucket(ov["over"] % 80, age_e)
                    w = bucket(match_overs, wear_e)
                    for dl in ov["deliveries"]:
                        ex = dl.get("extras", {})
                        if "wides" in ex:
                            runs += dl["runs"]["total"]
                            continue
                        br = dl["runs"]["batter"]
                        t = btype.get(reg.get(dl["bowler"], ""), "unknown")
                        bw = sum(1 for x in dl.get("wickets", []) if x["kind"] in BOWLER_WICKETS)
                        out = sum(1 for x in dl.get("wickets", []) if x["kind"] not in NOT_OUT)
                        ld = bucket(start_lead + runs, lead_e) if k in (1, 2) else None
                        for c in (age[(t, a)], wear[(t, w)], sit[(k + 1, bucket(wkts, wk_e))],
                                  faced[bucket(bf[dl["batter"]], faced_e)]) + ((lead[(k + 1, ld)],) if ld else ()):
                            c.balls += 1
                            c.runs += br
                            c.wkts += bw
                            c.outs += out
                        bf[dl["batter"]] += 1
                        runs += dl["runs"]["total"]
                        wkts += out
                        legal += "noballs" not in ex
                    match_overs += 1
                totals[team] += runs
                inns_len[k + 1].append(legal / 6)
                if inn.get("declared"):
                    declared[k + 1] += 1
                    decl_lead[k + 1].append(totals[team] - totals[other])
                if k == 3:
                    target = totals[other] - (totals[team] - runs) + 1
                    won = o.get("winner") == team
                    chase[bucket(target, (0, 100, 200, 300, 400))]["won" if won else
                                                                 "drawn" if res == "draw" else "lost"] += 1
            overs_per_day.append(match_overs / len(info["dates"]))

    print(f"{n} Tests")
    print("results:", dict(results.most_common()))
    print("days with play:", dict(sorted(days.items())), " innings in the match:", dict(sorted(n_inns.items())))
    print(f"overs per day with play: mean {sum(overs_per_day) / n:.1f}")
    for k in (1, 2, 3, 4):
        v = sorted(inns_len[k])
        print(f"innings {k}: {len(v)} played, median {v[len(v) // 2]:.0f} overs, declared {declared[k]}"
              + (f", median lead at the declaration {sorted(decl_lead[k])[len(decl_lead[k]) // 2]}"
                 if decl_lead[k] else ""))
    print(f"follow-on: possible (lead 200+) {fo_chance} times, enforced {fo_enforced} "
          f"({100 * fo_enforced / max(fo_chance, 1):.0f}%); by lead: "
          + ", ".join(f"{k}: {e}/{c}" for k, (c, e) in sorted(fo_by_lead.items())))
    print("fourth innings by target (won / drawn / lost by the side batting):")
    for k in ("0-99", "100-199", "200-299", "300-399", "400+"):
        c = chase[k]
        print(f"  {k:8} {c['won']:4d} {c['drawn']:4d} {c['lost']:4d}")

    def lab(e):
        return [bucket(x, e) for x in e]
    table("Ball age (overs since the innings began, modulo 80) x bowling type", age,
          [(t, a) for t in ("pace", "spin", "unknown") for a in lab(age_e)])
    table("Pitch wear (overs bowled in the match before this over) x bowling type", wear,
          [(t, w) for t in ("pace", "spin", "unknown") for w in lab(wear_e)])
    table("Innings x wickets down", sit, [(k, w) for k in (1, 2, 3, 4) for w in lab(wk_e)[:-1]])
    table("Innings 2 and 3 x lead of the batting side at that ball", lead,
          [(k, x) for k in (2, 3) for x in lab(lead_e)])
    table("Balls the batter has faced in the innings", faced, lab(faced_e))
    return 0


if __name__ == "__main__":
    sys.exit(main())
