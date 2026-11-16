"""How every Test since 1877 ended, by year: Tests played and Tests drawn, from the old Test simulator's data.

The old Test simulator (the sibling folder ../cricket) has a list of every Test to 2021 with its result
(testmatchlist.txt, collected from ESPNcricinfo before it blocked scraping). Ball-by-ball data starts in 2001,
so for earlier decades this list is the only record here of how often Tests were drawn. This script only READS
that folder and writes

    data/raw_stats/test_results.json    {"years": {year: {"tests", "draws", "by_host": {country: [tests, draws]}}}}

A Test that ran over New Year is listed under both years in the source; it is counted once, in its first year.
The output is committed, so the old folder is needed only to rebuild it.

    python scripts/build_test_results.py [--source ../cricket]
"""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "raw_stats" / "test_results.json"


def build(source: Path) -> dict:
    seen, years = set(), {}
    for line in (source / "testmatchlist.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        year, home, away, ground, number, winner, margin, dates, mid = ast.literal_eval(line)
        if number in seen:
            continue
        seen.add(number)
        y = years.setdefault(str(year), {"tests": 0, "draws": 0, "by_host": {}})
        draw = winner == "Draw"
        y["tests"] += 1
        y["draws"] += draw
        h = y["by_host"].setdefault(home, [0, 0])
        h[0] += 1
        h[1] += draw
    return {"source": "the old Test simulator's testmatchlist.txt", "tests": len(seen), "years": years}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", default=str(ROOT.parent / "cricket"))
    a = ap.parse_args()
    out = build(Path(a.source))
    OUT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    dec = {}
    for y, r in out["years"].items():
        d = dec.setdefault(int(y) // 10 * 10, [0, 0])
        d[0] += r["tests"]
        d[1] += r["draws"]
    print(f"{out['tests']} Tests; drawn by decade: " + ", ".join(f"{d}s {100 * b / a:.0f}% of {a}" for d, (a, b) in sorted(dec.items())))
