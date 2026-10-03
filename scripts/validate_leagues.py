"""Do league-specific ratings (engine/periods.py league_ratios) predict a player's later seasons *in that league*
better than his overall T20 rating?

Fit on data up to --until; rate each player on his record in a league (shrunk toward his overall rating, tau^2
estimated from players with balls both in and outside the league, times a scale); predict that league's later
balls. Skill vs "everyone average", players with >= --min-balls test balls, summed over the leagues.

    python scripts/validate_leagues.py
"""
from __future__ import annotations

import argparse
import copy
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from build_ratings import METRICS, PHASES, base_comp, baselines, fit, load_cells, merge_tiers  # noqa: E402
from engine.periods import split_indexes  # noqa: E402
from validate_ratings import CHECK, predict, score  # noqa: E402

LEAGUES = ("ipl", "bbl", "psl", "cpl", "sat", "ilt", "bpl", "lpl", "mlc", "ntb", "ssm")
SCALES = (0.1, 0.25, 0.5, 1.0, 2.0)


def with_league(r: dict, comp: str, scale: float) -> dict:
    out = copy.copy(r)
    out["phase"] = {"bat": {}, "bowl": {}}
    for side, ids in (("bat", r["bat_ids"]), ("bowl", r["bowl_ids"])):
        rows = defaultdict(dict)
        for (i, c), row in r["years"]["by_comp"][side].items():
            rows[i][c] = row
        career = {i: {m: r[side][m][i] for m in METRICS} for i in range(len(ids))}
        idx, _, _ = split_indexes(rows, career, lambda k: k == comp, scale)
        for m in METRICS:
            out["phase"][side][m] = {}
            for ph in PHASES:
                base = r["phase"][side][m][ph]
                new = list(base["idx"])
                for i, d in idx.items():
                    if career[i][m]:
                        new[i] *= d[m] / career[i][m]
                out["phase"][side][m][ph] = {**base, "idx": new}
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--until", type=int, default=2023)
    ap.add_argument("--min-balls", type=int, default=120)
    a = ap.parse_args(argv)
    data = merge_tiers(load_cells("t20"))
    base_all = baselines(data["cells"], data["extras"], data["other"])
    r = fit("t20", until=a.until, verbose=False)
    known = set(r["bat_ids"]) | set(r["bowl_ids"])
    tot = {name: defaultdict(float) for name in ["flat", "overall"] + [f"league x{k}" for k in SCALES]}
    for lg in LEAGUES:
        test = {k: v for k, v in data["cells"].items() if k[3] > a.until and base_comp(k[2]) == lg}
        if not test:
            continue
        rows = {"flat": score(predict(None, test, base_all, flat=True), a.min_balls, known),
                "overall": score(predict(r, test, base_all, fmt="t20"), a.min_balls, known)}
        for k in SCALES:
            rows[f"league x{k}"] = score(predict(with_league(r, lg, k), test, base_all, fmt="t20"), a.min_balls, known)
        n = sum(v[0] for v in test.values())
        for name, sc in rows.items():
            for key, v in sc.items():
                if v == v:   # not NaN
                    tot[name][key] += v * n
        print(f"  {lg}: {n} test balls; bat runs skill overall "
              f"{(1 - rows['overall'][('bat', 'runs')] / rows['flat'][('bat', 'runs')]) * 100:.1f}% -> best league "
              + ", ".join(f"x{k} {(1 - rows[f'league x{k}'][('bat', 'runs')] / rows['flat'][('bat', 'runs')]) * 100:.1f}%"
                          for k in SCALES), flush=True)
    hdr = "".join(f"{s[:4]} {m:>5}".rjust(12) for s in ("bat", "bowl") for m in CHECK)
    print(f"\n{'skill vs flat, all leagues':28}{hdr}")
    for name in tot:
        if name == "flat":
            continue
        print(f"{name:28}" + "".join(f"{(1 - tot[name][(s, m)] / tot['flat'][(s, m)]) * 100:11.1f}%"
                                      for s in ("bat", "bowl") for m in CHECK))
    return 0


if __name__ == "__main__":
    sys.exit(main())
