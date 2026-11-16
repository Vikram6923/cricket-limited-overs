"""Fit how Test sides bat with the tail: farming the strike and shielding the tailender.

With seven or more wickets down a recognised batter left with a tailender bats differently, and so does the
tailender: the batter turns down singles early in an over and takes one off the fourth or fifth ball, hits out
more and is out more; the tailender is kept away from the bowling and lasts longer than he does with another
tailender; a last pair of two tailenders swings. The situation table knows only "6 to 9 wickets down", which is
the average of all of that.

For every legal ball of every Cricsheet Test with 7, 8 or 9 wickets down and a tailender at the crease, the rate
the engine would use is ratings x the fitted situation tables (data/engine/test_situation.json). This table
holds observed / that, by

    who is on strike     senior (a batter with a tailender), shielded (a tailender with a batter),
                         last (a tailender with a tailender)
    wickets down         7, 8, 9
    ball of the over     1-3, 4-5, 6 (legal balls)

Each cell is shrunk toward 1 with the situation fit's pseudo-balls. A tailender is a man who came in at No. 9,
10 or 11, a batter one who came in at No. 1 to 8: Cricsheet has no roles, and the line is drawn where the real
share of the strike starts to move (see docs/test_design.md). The line is a definition, not a fitted value.

Writes data/engine/test_tail.json.   Run:  python -m engine.fit.fit_test_tail   (after fit_test_situation)
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict

from ..test_situation import TestSituation
from . import fit_test_situation as fts
from .fit_basics import bowl_types

METRICS = fts.METRICS
NM = len(METRICS)
TAIL_FROM = 9                 # the batting position (order of coming in) from which a man is a tailender
WICKETS = (7, 8, 9)
BALL_EDGES = (3, 5)           # legal balls 1-3, 4-5, 6 of an over
ROLES = ("senior", "shielded", "last")


def role(striker_pos: int, partner_pos: int) -> str | None:
    """The striker's part in the stand; None when no tailender is in."""
    if striker_pos >= TAIL_FROM:
        return "last" if partner_pos >= TAIL_FROM else "shielded"
    return "senior" if partner_pos >= TAIL_FROM else None


def ball_group(legal_in_over: int) -> int:
    """legal_in_over: legal balls already bowled in the over (0 to 5)."""
    return 0 if legal_in_over < BALL_EDGES[0] else 1 if legal_in_over < BALL_EDGES[1] else 2


def fit() -> dict:
    base, bat, bowl, _ = fts.load_ratings()
    btype = bowl_types("test")
    sit = TestSituation()
    A = defaultdict(lambda: [0.0] * NM)
    E = defaultdict(lambda: [0.0] * NM)
    N = defaultdict(int)
    strike = defaultdict(lambda: [0, 0])          # wickets down -> [balls the senior faced, balls] with a tailender
    for m in fts.iter_tests():                    # the same walk as fit_test_situation.fit
        info = m["info"]
        brow = (base.get(info["dates"][0][:4]) or {}).get("all")
        if not brow:
            continue
        reg = info["registry"]["people"]
        total, draw, days = fts.match_overs(m), fts.is_draw(m), len(info["dates"])
        gone = 0
        team_runs = defaultdict(int)
        for k, inn in enumerate(m.get("innings", [])[:4]):
            team = inn["team"]
            other = [t for t in info["teams"] if t != team][0]
            lead0 = team_runs[team] - team_runs[other]
            runs = wk = 0
            faced = defaultdict(int)
            pos: dict = {}
            for ov in inn.get("overs", []):
                left = fts.overs_left(gone, total, draw, days)
                legal = 0
                for d in ov["deliveries"]:
                    for x in (d["batter"], d["non_striker"]):
                        if x not in pos:
                            pos[x] = len(pos) + 1
                    ex = d.get("extras", {})
                    wide, nb = "wides" in ex, "noballs" in ex
                    bid, wid = reg.get(d["batter"]), reg.get(d["bowler"])
                    ro = role(pos[d["batter"]], pos[d["non_striker"]]) if wk in WICKETS else None
                    if ro and not wide and not nb:
                        if ro != "last":
                            strike[wk][0] += ro == "senior"
                            strike[wk][1] += 1
                        if bid in bat and wid in bowl:
                            cell = (sit.cell(k + 1, wk, lead0 + runs) if k < 3
                                    else sit.cell(4, wk, 0, -lead0 + 1 - runs, left))
                            mult = sit.multipliers(cell, faced[bid], btype.get(wid), gone, ov["over"] % 80)
                            bi, wi = bat[bid], bowl[wid]
                            br = d["runs"]["batter"]
                            key = (ro, wk, ball_group(legal))
                            a, e = A[key], E[key]
                            N[key] += 1
                            a[0] += br
                            a[1] += any(w["kind"] in fts.BOWLER_WICKETS for w in d.get("wickets", []))
                            a[2] += br == 0
                            a[3] += br == 4 and not d["runs"].get("non_boundary")
                            a[4] += br == 6
                            for j, mt in enumerate(METRICS):
                                e[j] += brow[mt] * bi[mt] * wi[mt] * mult[mt]
                    if not wide and not nb:
                        legal += 1
                    if not wide:
                        faced[bid] += 1
                    runs += d["runs"]["total"]
                    wk += fts.outs(d)
                gone += 1
            team_runs[team] += runs
    cells: dict = {}
    balls: dict = {}
    for ro in ROLES:
        for wk in WICKETS:
            rows = []
            for g in range(len(BALL_EDGES) + 1):
                key = (ro, wk, g)
                n = N.get(key, 0)
                row = []
                for j in range(NM):
                    a, e = A[key][j], E[key][j]
                    k = fts.SHRINK_BALLS * (e / n) if n else 0.0
                    row.append(round((a + k) / (e + k), 4) if e + k > 0 else 1.0)
                rows.append(row)
                balls[f"{ro}|{wk}|{g}"] = n
            if any(balls[f"{ro}|{wk}|{g}"] for g in range(len(BALL_EDGES) + 1)):
                cells.setdefault(ro, {})[str(wk)] = rows
    return {"format": "test", "metrics": list(METRICS), "tail_from": TAIL_FROM, "wickets": list(WICKETS),
            "ball_edges": list(BALL_EDGES), "shrink_balls": fts.SHRINK_BALLS, "cells": cells, "balls": balls,
            "real_strike_share": {str(w): round(a / b, 4) for w, (a, b) in sorted(strike.items()) if b}}


def main() -> int:
    t = fit()
    (fts.OUT / "test_tail.json").write_text(json.dumps(t, indent=1), encoding="utf-8")
    names = ("balls 1-3", "balls 4-5", "ball 6")
    for ro, by in t["cells"].items():
        for wk, rows in by.items():
            for g, row in enumerate(rows):
                print(f"  {ro:9} {wk} down {names[g]:9} {t['balls'][f'{ro}|{wk}|{g}']:6d}  "
                      + "  ".join(f"{m} {x:5.3f}" for m, x in zip(t["metrics"], row)))
    print("  the batter's share of the strike with a tailender:", t["real_strike_share"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
