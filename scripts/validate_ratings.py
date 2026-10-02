"""Out-of-sample check of the ratings model: fit on data up to --until, predict every later ball.

For each model variant the per-player predicted counts (runs, dismissals; batting and bowling) over the test
period are compared with what actually happened. Reported: ball-weighted mean squared error of the per-ball rate,
and skill = 1 - MSE / MSE(flat), where "flat" rates everyone as average. Sampling noise in the test period is the
same for every variant, so differences between variants are what matter.

Variants: full model | no shrinkage | no opponent adjustment | raw career rates (neither) | flat.

    python scripts/validate_ratings.py               # both formats, train <= 2023, test 2024+
    python scripts/validate_ratings.py --until 2021 --min-balls 200
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict

from build_ratings import STATS, _load_json, baselines, fit, load_cells, merge_tiers, player_groups

CHECK = ("runs", "wkt", "four", "six", "dot")


def newcomer_prior(r: dict, fmt: str, ids: set) -> dict:
    """Players unseen in training get role-group mean x team level (team affiliation isn't a performance leak)."""
    ids = sorted(ids)
    afg = {p["cricsheet_id"] for p in _load_json(STATS / "afghanistan_players.json", []) if p.get("cricsheet_id")}
    bat_g, bowl_g, team, _ = player_groups(fmt, ids, r["styles"], afg)
    out = {"bat": {}, "bowl": {}}
    for m in CHECK:
        fb, fw = r["fits"][m]
        tb, tw = r["team_levels"][m]
        out["bat"][m] = {p: fb["group_mean"].get(g, 1.0) * tb.get(t, 1.0) for p, g, t in zip(ids, bat_g, team)}
        out["bowl"][m] = {p: fw["group_mean"].get(g, 1.0) * tw.get(t, 1.0) for p, g, t in zip(ids, bowl_g, team)}
    return out


def predict(r: dict, test_cells: dict, base_all: dict, flat: bool = False, fmt: str = "") -> dict:
    """side -> metric -> player -> [actual, predicted, balls] over the test cells."""
    bi = {p: i for i, p in enumerate(r["bat_ids"])} if r else {}
    wi = {p: i for i, p in enumerate(r["bowl_ids"])} if r else {}
    new = newcomer_prior(r, fmt, {k[0] for k in test_cells if k[0] not in bi} |
                         {k[1] for k in test_cells if k[1] not in wi}) if r and not flat else None
    col = {"runs": 1, "wkt": 3, "dot": 4, "four": 5, "six": 6}
    out = {s: {m: defaultdict(lambda: [0.0, 0.0, 0]) for m in CHECK} for s in ("bat", "bowl")}
    # The fitted baseline factor for test years is unknown: use the mean of the last 3 training years.
    fac = {}
    if r:
        for m in CHECK:
            by = defaultdict(list)
            for (comp, yr, ph), v in r["base_factor"][m].items():
                by[(comp, ph)].append((yr, v))
            fac[m] = {k: sum(v for _, v in sorted(xs)[-3:]) / len(sorted(xs)[-3:]) for k, xs in by.items()}
    for (bat, bwl, comp, yr, ph), c in test_cells.items():
        b = base_all[(comp, yr, ph)]
        for m in CHECK:
            fb = fw = 1.0
            if not flat:
                fb = fac[m].get((comp, ph), 1.0)
                fb *= r["phase"]["bat"][m][ph]["idx"][bi[bat]] if bat in bi else new["bat"][m].get(bat, 1.0)
                fw = r["phase"]["bowl"][m][ph]["idx"][wi[bwl]] if bwl in wi else new["bowl"][m].get(bwl, 1.0)
            p = c[0] * b[m] * fb * fw
            for side, pid in (("bat", bat), ("bowl", bwl)):
                x = out[side][m][pid]
                x[0] += c[col[m]]
                x[1] += p
                x[2] += c[0]
    return out


def score(pred: dict, min_balls: int, known: set) -> dict:
    res = {}
    for side in ("bat", "bowl"):
        for m in CHECK:
            num = den = 0.0
            for pid, (a, p, n) in pred[side][m].items():
                if n >= min_balls and pid in known:
                    num += n * (a / n - p / n) ** 2
                    den += n
            res[(side, m)] = num / den if den else float("nan")
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--format", choices=["odi", "t20"], action="append")
    ap.add_argument("--until", type=int, default=2023)
    ap.add_argument("--min-balls", type=int, default=120, help="players need this many test balls to count")
    args = ap.parse_args(argv)
    for fmt in args.format or ["odi", "t20"]:
        data = merge_tiers(load_cells(fmt))
        base_all = baselines(data["cells"], data["extras"], data["other"])
        test = {k: v for k, v in data["cells"].items() if k[3] > args.until}
        variants = {
            "full model": fit(fmt, until=args.until, verbose=False),
            "no shrinkage": fit(fmt, until=args.until, shrink=False, verbose=False),
            "no opponent adj": fit(fmt, until=args.until, opponent=False, verbose=False),
            "raw career rates": fit(fmt, until=args.until, shrink=False, opponent=False, verbose=False),
        }
        # score only players seen in training, so every variant is judged on the same people
        known = set(variants["full model"]["bat_ids"]) | set(variants["full model"]["bowl_ids"])
        flat = score(predict(None, test, base_all, flat=True), args.min_balls, known)
        print(f"\n=== {fmt.upper()}: train <= {args.until}, test {args.until + 1}+ "
              f"({sum(v[0] for v in test.values())} balls); players with >= {args.min_balls} test balls")
        hdr = "".join(f"{s[:4]} {m:>5}" .rjust(12) for s in ("bat", "bowl") for m in CHECK)
        print(f"{'skill vs flat (higher = better)':32}{hdr}")
        for name, r in variants.items():
            sc = score(predict(r, test, base_all, fmt=fmt), args.min_balls, known)
            row = "".join(f"{(1 - sc[(s, m)] / flat[(s, m)]) * 100:11.1f}%" for s in ("bat", "bowl") for m in CHECK)
            print(f"{name:32}{row}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
