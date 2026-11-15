"""The runs-v-risk curve of a Test, for a person's batting approach and bowling plan bars (1-9, 5 = as real
sides play the situation; docs/test_design.md, Phase 6).

    python -m engine.fit.fit_test_aggression        -> data/engine/aggression_test.json

It reads the fitted Test situation table (data/engine/test_situation.json, engine/fit/fit_test_situation.py):
each cell (innings x wickets down x lead; last innings x wickets down x runs needed per over left) holds how
much faster or slower, and riskier or safer, real sides batted there than the players' ratings predict. Across
the cells, weighted by their balls, the regression of log(ratio) of each metric on log(ratio of runs) is the
trade-off real sides show:
    a side that scores e^d times faster also loses wickets e^(b_wkt d) times faster, hits e^(b_six d) the sixes...
The bars move along that curve. Bar 5 is d = 0 (the engine as calibrated). step = (p95 - p5) / 6, with p5 and
p95 the 5th and 95th percentile (ball-weighted) of the cells' log runs ratio: bars 2 to 8 span as wide a range
of intent as real sides show, centred on bar 5, and bars 1 and 9 go one step beyond it (an extrapolation).

Unlike limited overs (engine/fit/fit_aggression.py) the wicket slope is the one measured across the cells. There
the cross-cell slope made hitting nearly free and had to be replaced; in Tests it comes out near 1, which is the
value at which tempo changes the time an innings takes and not its runs per wicket, so nothing is replaced.
The cells are large (the smallest used has over 2,000 balls), so the slopes are not corrected for sampling noise.

Bowling plans use the same curve over BOWL_SHARE of the batting range, with the limited-overs edges (attack takes
wickets a little below what its runs cost, contain gives up more wickets than its saved runs are worth). Cricsheet
has no field, line or length data, so the size of a plan's effect cannot be measured: these three numbers are
assumptions carried over from the ODI fit, not fitted for Tests.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "data" / "engine" / "test_situation.json"
OUT = ROOT / "data" / "engine" / "aggression_test.json"
MIN_BALLS = 2000
BARS = 9
BOWL_SHARE = 0.5          # as ODI (an assumption; see the docstring)
BOWL_EDGE = 0.4           # as ODI
CONTAIN_EDGE = 0.8        # as ODI


def cells(t: dict) -> list[tuple]:
    """[(balls, [ratio per metric])] over every situation cell with enough balls."""
    out = []
    for i in ("1", "2", "3"):
        for row, ns in zip(t["state"][i], t["state_n"][i]):
            out += [(n, c) for c, n in zip(row, ns)]
    for row, ns in zip(t["fourth"], t["fourth_n"]):
        out += [(n, c) for c, n in zip(row, ns)]
    return [(n, c) for n, c in out if n >= MIN_BALLS]


def quantile(xs: list[tuple], q: float) -> float:
    total, acc = sum(n for _, n in xs), 0.0
    for x, n in sorted(xs):
        acc += n
        if acc >= q * total:
            return x
    return xs[-1][0]


def fit() -> dict:
    t = json.loads(SRC.read_text(encoding="utf-8"))
    metrics = t["metrics"]
    r = metrics.index("runs")
    pts = cells(t)
    w = [n for n, _ in pts]
    x = [math.log(c[r]) for _, c in pts]
    sw = sum(w)
    mx = sum(a * b for a, b in zip(w, x)) / sw
    sxx = sum(a * (b - mx) ** 2 for a, b in zip(w, x))
    slope = {}
    for j, name in enumerate(metrics):
        if j == r:
            continue
        y = [math.log(c[j]) for _, c in pts]
        my = sum(a * b for a, b in zip(w, y)) / sw
        slope[name] = round(sum(a * (b - mx) * (c - my) for a, b, c in zip(w, x, y)) / sxx, 4)
    p5, p95 = quantile(list(zip(x, w)), 0.05), quantile(list(zip(x, w)), 0.95)
    return {"format": "test", "source": SRC.name, "cells": len(pts), "balls": sw, "min_balls": MIN_BALLS,
            "bars": BARS, "metrics": metrics, "slope": slope, "p5": round(p5, 4), "p95": round(p95, 4),
            "step": round((p95 - p5) / 6, 4), "bowl_share": BOWL_SHARE, "bowl_edge": BOWL_EDGE,
            "contain_edge": CONTAIN_EDGE}


def main() -> int:
    a = fit()
    OUT.write_text(json.dumps(a, indent=1) + "\n", encoding="utf-8")
    print(f"{a['cells']} cells, {a['balls']} balls")
    print("slopes on log runs:", a["slope"])
    print(f"log runs ratio: 5% {a['p5']}, 95% {a['p95']}; step {a['step']} a bar "
          f"(bar 1 x{math.exp(-4 * a['step']):.3f}, bar 9 x{math.exp(4 * a['step']):.3f} the runs)")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
