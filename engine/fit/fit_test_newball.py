"""When do Test captains take the new ball? (data/engine/test_newball.json, used by engine/test_captain.py)

Cricsheet does not record the taking of the new ball. It is inferred: from the 80th over of an innings, the new
ball is taken at the first over that begins two overs of pace in a row (a new ball is given to the quick
bowlers at both ends). By that reading it is often delayed when spin is on: with spinners at both ends it is
taken at once about four times in ten, and in about one innings in five never.

The table is the chance that it is taken before an over, given that it is available and not yet taken, by
    spinners in the last two overs (0, 1, 2) x overs since it became available (edges 1, 3, 6, 11).
A cell with few overs is shrunk toward its row.

Run:  python -m engine.fit.fit_test_newball
"""
from __future__ import annotations

import bisect
import json
import sys
from collections import defaultdict

from . import fit_test_situation as fts
from .fit_basics import bowl_types

AVAILABLE = 80
EDGES = [1, 3, 6, 11]
SHRINK = 30                  # pseudo-overs at the row's rate


def fit() -> dict:
    bt = bowl_types("test")
    cell = defaultdict(lambda: [0, 0])            # (spinners, delay bucket) -> [taken, overs at risk]
    innings = 0
    for m in fts.iter_tests():
        reg = m["info"]["registry"]["people"]
        for inn in m.get("innings", []):
            seq = [bt.get(reg.get(ov["deliveries"][0]["bowler"])) for ov in inn.get("overs", [])]
            if len(seq) <= AVAILABLE + 1:
                continue
            innings += 1
            for i in range(AVAILABLE, len(seq) - 1):
                c = cell[((seq[i - 2] == "spin") + (seq[i - 1] == "spin"), bisect.bisect_right(EDGES, i - AVAILABLE))]
                c[1] += 1
                if seq[i] == "pace" and seq[i + 1] == "pace":
                    c[0] += 1
                    break
    out = {"available": AVAILABLE, "edges": EDGES, "innings": innings, "take": {}, "n": {}}
    for s in (0, 1, 2):
        row = [cell[(s, b)] for b in range(len(EDGES) + 1)]
        rate = sum(c[0] for c in row) / max(sum(c[1] for c in row), 1)
        out["take"][str(s)] = [round((c[0] + SHRINK * rate) / (c[1] + SHRINK), 4) for c in row]
        out["n"][str(s)] = [c[1] for c in row]
    return out


def main() -> int:
    t = fit()
    (fts.OUT / "test_newball.json").write_text(json.dumps(t, indent=1), encoding="utf-8")
    print(f"{t['innings']} innings of more than {AVAILABLE} overs; chance the new ball is taken before an over")
    print("  spinners in the last two overs x overs since it was available (0, 1-2, 3-5, 6-10, 11+)")
    for s in ("0", "1", "2"):
        print(f"  {s}: " + "  ".join(f"{p:.2f} ({n})" for p, n in zip(t["take"][s], t["n"][s])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
