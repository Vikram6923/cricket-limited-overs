"""Out-of-sample checks of year-range ratings (engine/periods.py) against career-long ratings.

1. Forecast (default): fit on data up to --until, rate every player on the last 1 / 2 / 3 / 5 years before the
   cut, predict every later ball (as validate_ratings.py).
2. Held-out year (--holdout 2012 2016 ...): the use case of historical teams. Leave one calendar year out of the
   fit entirely, rate players on the years around it (Y-w..Y+w, w = 1, 2, 3) and predict the held-out year.
   Career = the same fit without the year range. The baseline factor of the held-out year is the mean of its
   neighbours.

Skill = 1 - MSE / MSE(flat), per player over balls, players with >= --min-balls balls in the test data.
Also prints the fitted tau^2 (how far true period level strays from the career level).

    python scripts/validate_periods.py
    python scripts/validate_periods.py --holdout 2012 2016 2019 2022
"""
from __future__ import annotations

import argparse
import copy
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from build_ratings import METRICS, PHASES, baselines, fit, load_cells, merge_tiers  # noqa: E402
from engine.periods import period_indexes  # noqa: E402
from validate_ratings import CHECK, predict, score  # noqa: E402

WINDOWS = (1, 2, 3, 5)
SCALES = (0.05, 0.1, 0.2)   # held-out mode: multiples of the fitted tau^2 to compare


def with_period(r: dict, y1: int, y2: int, tau_scale: float = 1.0) -> tuple[dict, dict]:
    """Copy of the fit whose phase indexes are scaled by period / career index."""
    out = copy.copy(r)
    out["phase"] = {"bat": {}, "bowl": {}}
    taus = {}
    for side, ids in (("bat", r["bat_ids"]), ("bowl", r["bowl_ids"])):
        rows = defaultdict(dict)
        for (i, yr), row in r["years"][side].items():
            rows[i][yr] = row
        career = {i: {m: r[side][m][i] for m in METRICS} for i in range(len(ids))}
        idx, tau, _ = period_indexes(rows, career, y1, y2, tau_scale)
        taus[side] = tau
        for m in METRICS:
            out["phase"][side][m] = {}
            for ph in PHASES:
                base = r["phase"][side][m][ph]
                new = list(base["idx"])
                for i, d in idx.items():
                    if career[i][m]:
                        new[i] *= d[m] / career[i][m]
                out["phase"][side][m][ph] = {**base, "idx": new}
    return out, taus


def predict_holdout(r: dict, test: dict, base_all: dict, year: int, fmt: str) -> dict:
    """validate_ratings.predict, but the held-out year's baseline factor = mean of the neighbouring years."""
    from validate_ratings import newcomer_prior
    bi = {p: i for i, p in enumerate(r["bat_ids"])}
    wi = {p: i for i, p in enumerate(r["bowl_ids"])}
    new = newcomer_prior(r, fmt, {k[0] for k in test if k[0] not in bi} | {k[1] for k in test if k[1] not in wi})
    col = {"runs": 1, "wkt": 3, "dot": 4, "four": 5, "six": 6}
    out = {s: {m: defaultdict(lambda: [0.0, 0.0, 0]) for m in CHECK} for s in ("bat", "bowl")}
    for (bat, bwl, comp, yr, ph), c in test.items():
        b = base_all[(comp, yr, ph)]
        for m in CHECK:
            bf = r["base_factor"][m]
            near = [bf[(comp, y, ph)] for y in (year - 1, year + 1) if (comp, y, ph) in bf]
            fb = sum(near) / len(near) if near else 1.0
            fb *= r["phase"]["bat"][m][ph]["idx"][bi[bat]] if bat in bi else new["bat"][m].get(bat, 1.0)
            fw = r["phase"]["bowl"][m][ph]["idx"][wi[bwl]] if bwl in wi else new["bowl"][m].get(bwl, 1.0)
            p = c[0] * b[m] * fb * fw
            for side, pid in (("bat", bat), ("bowl", bwl)):
                x = out[side][m][pid]
                x[0] += c[col[m]]
                x[1] += p
                x[2] += c[0]
    return out


def holdout(fmt: str, years: list[int], min_balls: int) -> None:
    data = merge_tiers(load_cells(fmt))
    base_all = baselines(data["cells"], data["extras"], data["other"])
    combos = [(w, k) for w in (1, 2, 3) for k in SCALES]
    names = ["career"] + [f"Y-{w}..Y+{w} tau x{k}" for w, k in combos]
    tot = {n: defaultdict(lambda: [0.0, 0.0]) for n in names + ["flat"]}   # (side, m) -> [sum mse*n, sum n]
    print(f"\n=== {fmt.upper()}: held-out years {years}; players with >= {min_balls} balls in the held-out year")
    for year in years:
        test = {k: v for k, v in data["cells"].items() if k[3] == year}
        r = fit(fmt, exclude=(year,), verbose=False)
        known = set(r["bat_ids"]) | set(r["bowl_ids"])
        variants = [("career", r)]
        taus = []
        for w, k in combos:
            rv, t = with_period(r, year - w, year + w, k)
            variants.append((f"Y-{w}..Y+{w} tau x{k}", rv))
            taus.append(t)
        rows = {"flat": score(predict(None, test, base_all, flat=True), min_balls, known)}
        for name, rv in variants:
            rows[name] = score(predict_holdout(rv, test, base_all, year, fmt), min_balls, known)
        print(f"  {year} done", flush=True)
        for n, sc in rows.items():
            for key, v in sc.items():
                tot[n][key][0] += v
                tot[n][key][1] += 1
    hdr = "".join(f"{s[:4]} {m:>5}".rjust(12) for s in ("bat", "bowl") for m in CHECK)
    print(f"{'mean skill vs flat (higher = better)':38}{hdr}")
    flat = {k: v[0] / v[1] for k, v in tot["flat"].items()}
    for n in names:
        row = "".join(f"{(1 - tot[n][(s, m)][0] / tot[n][(s, m)][1] / flat[(s, m)]) * 100:11.1f}%"
                      for s in ("bat", "bowl") for m in CHECK)
        print(f"{n:38}{row}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--format", choices=["odi", "t20"], action="append")
    ap.add_argument("--until", type=int, default=2023)
    ap.add_argument("--min-balls", type=int, default=120)
    ap.add_argument("--holdout", type=int, nargs="+", help="held-out-year mode: these years")
    args = ap.parse_args(argv)
    for fmt in args.format or ["odi", "t20"]:
        if args.holdout:
            holdout(fmt, args.holdout, args.min_balls)
            continue
        data = merge_tiers(load_cells(fmt))
        base_all = baselines(data["cells"], data["extras"], data["other"])
        test = {k: v for k, v in data["cells"].items() if k[3] > args.until}
        r = fit(fmt, until=args.until, verbose=False)
        known = set(r["bat_ids"]) | set(r["bowl_ids"])
        flat = score(predict(None, test, base_all, flat=True), args.min_balls, known)
        print(f"\n=== {fmt.upper()}: train <= {args.until}, test {args.until + 1}+; "
              f"players with >= {args.min_balls} test balls")
        hdr = "".join(f"{s[:4]} {m:>5}".rjust(12) for s in ("bat", "bowl") for m in CHECK)
        print(f"{'skill vs flat (higher = better)':32}{hdr}")
        variants = [("career", r, None)]
        for w in WINDOWS:
            rv, taus = with_period(r, args.until - w + 1, args.until)
            variants.append((f"last {w} year{'s' if w > 1 else ''}", rv, taus))
        for name, rv, taus in variants:
            sc = score(predict(rv, test, base_all, fmt=fmt), args.min_balls, known)
            row = "".join(f"{(1 - sc[(s, m)] / flat[(s, m)]) * 100:11.1f}%" for s in ("bat", "bowl") for m in CHECK)
            print(f"{name:32}{row}")
        print("fitted tau^2 (period vs career):")
        for name, _, taus in variants[1:]:
            print(f"  {name:14}" + "  ".join(f"{s} {m} {taus[s][m]:.4f}" for s in ("bat", "bowl") for m in ("runs", "wkt")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
