"""Batting aggression and bowling plans (docs/match_play_design.md): the runs-v-risk trade-off real sides show.

    python -m engine.fit.fit_aggression        -> data/engine/aggression_{t20,odi}.json

For every legal ball since 2012 (as fit_situation.py), expected counts come from the ratings alone
(baseline x batter index x bowler index x settling in, no situation table). Balls are pooled in the situation
cells (innings x balls left x wickets lost, and chase pressure when chasing). In each cell, observed / expected is
how much faster or slower, and riskier or safer, real sides batted there than their skill alone predicts. Within
each phase, regressing log(ratio) of every metric on log(ratio of runs) across cells (weighted by expected runs,
cells under MIN_BALLS left out, corrected for the sampling noise in each cell's runs ratio) gives the trade-off:
    a side that scores e^d times faster also loses wickets e^(b_wkt d) times faster, hits e^(b_six d) the sixes...
The dial moves along that curve. Bar 5 = d 0 = the engine as it is (real sides' intent in that situation). The
range: bars 2 and 8 sit at the 5th and 95th percentile (ball-weighted) of log runs ratio across the phase's
cells, so they span the slowest and fastest intent real sides show in that phase; bars 1 and 9 carry on one more
step along the same curve (beyond what real sides do, an extrapolation). Bowling plans use the same
curve (an attacking field gives away runs and takes wickets) over BOWL_SHARE of the batting range: the plan's
effect can't be separated from the bowler's in Cricsheet, so its size is an assumption (design 3b).

The wicket slope is not the slope across cells (that one makes aggression nearly free: sides score fast where they
can do it cheaply). Real captains are taken to be about right on average, so at bar 5 the runs from a little more
intent pay for the wickets it costs: sum runs = b_wkt x sum(k V x wickets) + b_run_out x sum(k V x run-outs), V
= par runs lost per wicket at each ball's state (the fitted resources table). k turns par runs into the engine's
own currency (a saved wicket is worth less in simulation than par says): chosen by `--scan` so that simulated
first-innings totals peak at bar 5 (India v Australia presets, bars 3-7, 200-300 matches per point).
    python -m engine.fit.fit_aggression --scan t20 1.0,0.6,0.4
The bowling plan's edge m (attacking takes wickets at (1 - m) of the batting rate per unit of runs, containing
gives them up at (1 + m)) is chosen the same way, so the opponents' totals are lowest at bar 5:
    python -m engine.fit.fit_aggression --scan-bowl t20 0,0.2,0.4
"""
from __future__ import annotations

import bisect
import json
import math
from collections import defaultdict

from engine.fit.fit_situation import CFG, OUT, PRESS_EDGES, ROOT, SETTLE_EDGES, WKT_EDGES, bucket, iter_matches, \
    load_ratings, phase_of
from engine.situation import Situation

METRICS = ("runs", "wkt", "dot", "four", "six", "run_out")
MIN_BALLS = 300
BOWL_SHARE = 0.5
BARS = 9
WICKET_VALUE = {"t20": 0.6, "odi": 0.7}   # k, from --scan (2026-10-12)
BOWL_EDGE = {"t20": 0.4, "odi": 0.4}      # m (attack), from --scan-bowl (2026-10-12)
CONTAIN_EDGE = {"t20": 0.8, "odi": 0.8}   # m (contain), from --scan-contain (2026-10-12)


def fit(fmt: str) -> dict:
    cfg = CFG[fmt]
    N = cfg["overs"] * 6
    base, bat, bowl, ro = load_ratings(fmt)
    sits: dict = {}
    # (phase, cell) -> [actual per metric], [expected per metric], balls, sum of batter runs squared
    cells = defaultdict(lambda: [[0.0] * len(METRICS), [0.0] * len(METRICS), 0, 0.0])
    env = defaultdict(lambda: [0.0, 0.0, 0.0])   # phase -> [batter runs, sum V x bowler wickets, sum V x run-outs]
    for comp, full, yr, m in iter_matches(cfg):
        if "method" in m["info"].get("outcome", {}):
            continue
        brow = (base.get(comp) or {}).get(str(yr))
        if not brow:
            continue
        sc = f"{comp}_full" if full else comp
        sit = sits.get((sc, yr)) or sits.setdefault((sc, yr), Situation(fmt, sc, yr))
        settle = sit.t["settle"]
        reg = m["info"]["registry"]["people"]
        inns = [i for i in m.get("innings", []) if not i.get("super_over")]
        target = None
        for k, inn in enumerate(inns[:2]):
            if k == 1:
                t = inn.get("target") or {}
                if t.get("overs", cfg["overs"]) != cfg["overs"] or not t.get("runs"):
                    break
                target = t["runs"]
            faced = defaultdict(int)
            runs = wk = legal = 0
            prev_nb = False
            for ov in inn["overs"]:
                ph = phase_of(ov["over"], cfg)
                bp = brow.get(ph)
                for d in ov["deliveries"]:
                    bid, wid = reg.get(d["batter"]), reg.get(d["bowler"])
                    ex = d.get("extras", {})
                    wide, nb = "wides" in ex, "noballs" in ex
                    if not wide and not nb and not prev_nb and bp and bid in bat and wid in bowl:
                        bi, wi = bat[bid][ph], bowl[wid][ph]
                        se = settle[bisect.bisect_left(SETTLE_EDGES, faced[bid])]
                        bl = bucket(N - legal, cfg["balls_left_edges"])
                        w = bisect.bisect_left(WKT_EDGES, wk)
                        if k == 0:
                            key = (ph, 1, bl, w)
                        else:
                            key = (ph, 2, bl, w, bisect.bisect_left(PRESS_EDGES, sit.pressure(legal, wk, target - runs)))
                        br = d["runs"]["batter"]
                        outs = d.get("wickets", [])
                        wk_b = any(o["kind"] in ("bowled", "caught", "caught and bowled", "lbw", "stumped",
                                                 "hit wicket") for o in outs)
                        ro_b = any(o["kind"] == "run out" for o in outs)
                        act = (br, wk_b, br == 0, br == 4 and not d["runs"].get("non_boundary"), br == 6, ro_b)
                        cell = cells[key]
                        for j, mt in enumerate(METRICS):
                            cell[0][j] += act[j]
                            if mt == "run_out":
                                cell[1][j] += bp["other_out"] * ro.get(bid, 1.0) * se[j]
                            else:
                                cell[1][j] += bp[mt] * bi[mt] * wi[mt] * se[j]
                        cell[2] += 1
                        cell[3] += br * br
                        v = sit.par_runs(legal, wk) - sit.par_runs(legal, wk + 1) if wk < 9 else 0.0
                        en = env[ph]
                        en[0] += br
                        en[1] += v * wk_b
                        en[2] += v * ro_b
                    if not wide:
                        faced[bid] += 1
                    prev_nb = nb
                    if not wide and not nb:
                        legal += 1
                    runs += d["runs"]["total"]
                    for o in d.get("wickets", []):
                        if o["kind"] not in ("retired hurt", "retired not out"):
                            wk += 1
    out = {"metrics": list(METRICS), "bars": BARS, "wicket_value": WICKET_VALUE[fmt], "bowl_edge": BOWL_EDGE[fmt], "contain_edge": CONTAIN_EDGE[fmt], "bowl_share": BOWL_SHARE, "min_balls": MIN_BALLS, "phases": {}}
    for ph in ("powerplay", "middle", "death"):
        pts = []   # (x = log runs ratio, {metric: log ratio}, weight, balls, sampling variance of x)
        for key, (a, e, n, sq) in cells.items():
            if key[0] != ph or n < MIN_BALLS or a[0] <= 0:
                continue
            x = math.log(a[0] / e[0])
            ys = {mt: math.log(a[j] / e[j]) for j, mt in enumerate(METRICS) if a[j] > 0 and e[j] > 0}
            mean = a[0] / n
            pts.append((x, ys, e[0], n, (sq / n - mean * mean) / n / (mean * mean)))
        # errors in variables: each cell's x is measured with sampling noise, which flattens the slopes (toward
        # "aggression is free") and widens the spread; correct both by the reliability of x
        W0 = sum(p[2] for p in pts)
        mx0 = sum(p[0] * p[2] for p in pts) / W0
        var_obs = sum(p[2] * (p[0] - mx0) ** 2 for p in pts) / W0
        var_noise = sum(p[2] * p[4] for p in pts) / W0
        rel = max(0.2, 1.0 - var_noise / var_obs)
        slopes = {}
        for mt in METRICS[1:]:
            pr = [(x, ys[mt], w) for x, ys, w, *_ in pts if mt in ys]
            W = sum(w for *_, w in pr)
            mx = sum(x * w for x, _, w in pr) / W
            my = sum(y * w for _, y, w in pr) / W
            sxx = sum(w * (x - mx) ** 2 for x, _, w in pr)
            sxy = sum(w * (x - mx) * (y - my) for x, y, w in pr)
            slopes[mt] = round(sxy / sxx / rel, 4) if sxx else 0.0
        xs = sorted((x, n) for x, _, _, n, _ in pts)
        tot = sum(n for _, n in xs)
        mean = sum(x * n for x, n in xs) / tot

        def pct(q):
            acc = 0
            for x, n in xs:
                acc += n
                if acc >= q * tot:
                    return x
            return xs[-1][0]
        lo, hi = pct(0.05), pct(0.95)
        # the wicket slope: real captains taken to be about right on average, so at bar 5 the runs a little more
        # intent brings equal the runs the extra wickets cost (V = par runs lost per wicket at that ball's state):
        #     sum runs = b_wkt x sum(V x wickets) + b_run_out x sum(V x run-outs)
        # The slope across cells (kept as "cross") makes aggression nearly free: sides score fast where they
        # can do it cheaply (set batters, wickets in hand), which is not what turning up the intent does.
        R, VW, VR = env[ph]
        cross = dict(slopes)
        k = WICKET_VALUE[fmt]
        slopes["wkt"] = round((R / k - slopes["run_out"] * VR) / VW, 4) if VW else slopes["wkt"]
        out["phases"][ph] = {"slope": slopes, "cross": cross, "envelope": [round(R, 1), round(VW, 1), round(VR, 1)], "step": round(math.sqrt(rel) * (hi - lo) / (BARS - 3), 4),
                             "reliability": round(rel, 3),
                             "spread": {"p5": round(lo - mean, 4), "p95": round(hi - mean, 4)},
                             "cells": len(pts), "balls": tot}
    return out


SCAN = {"t20": ("t20i_full", 2024, "India T20 2024", "Australia T20 2024", 300),
        "odi": ("odi_full", 2023, "India ODI 2023", "Australia ODI 2023", 200)}


def scan(fmt: str, ks: list[float]) -> None:
    """First-innings totals of a side batting at fixed bars 3-7 for each wicket-value scale k (bowling at 5)."""
    import statistics
    from engine.control import Controller
    from engine.match import simulate_match
    from engine.situation import aggression_table
    comp, year, a, b, n = SCAN[fmt]
    teams = {t["name"]: t for t in json.loads((ROOT / "data" / "teams_default.json").read_text(encoding="utf-8"))}

    class Fixed(Controller):
        def __init__(self, bars):
            super().__init__(a, {"ball"})
            self.bars = bars

        def decide(self, q):
            if q["kind"] == "ball" and q["side"] == "bat":
                return {"bat": {q["striker"]["id"]: self.bars, q["non_striker"]["id"]: self.bars}}
            return None
    tab = aggression_table(fmt)
    for k in ks:
        for r in tab["phases"].values():
            R, VW, VR = r["envelope"]
            r["slope"]["wkt"] = (R / k - r["slope"]["run_out"] * VR) / VW
        tot = {}
        for bars in (3, 4, 5, 6, 7):
            tot[bars] = statistics.mean(
                simulate_match(teams[a], teams[b], fmt, comp, year, seed=seed, control={a: Fixed(bars)},
                               toss=a, decision="bat")["innings"][0]["runs"] for seed in range(n))
        print(f"k {k}: " + "  ".join(f"bars {x}: {t:.1f}" for x, t in tot.items()), flush=True)


def scan_bowl(fmt: str, gs: list[float]) -> None:
    """The opponents' first-innings totals against a side bowling at fixed plan bars 3-7, for each edge m."""
    import statistics
    from engine.control import Controller
    from engine.match import simulate_match
    from engine.situation import aggression_table
    comp, year, a, b, n = SCAN[fmt]
    teams = {t["name"]: t for t in json.loads((ROOT / "data" / "teams_default.json").read_text(encoding="utf-8"))}

    class Fixed(Controller):
        def __init__(self, bars):
            super().__init__(a, {"ball"})
            self.bars = bars

        def decide(self, q):
            if q["kind"] == "ball" and q["side"] == "bowl":
                return {"bowl": {q["bowler"]["id"]: self.bars}}
            return None
    tab = aggression_table(fmt)
    for g in gs:
        tab["bowl_edge"] = g
        tot = {}
        for bars in (3, 4, 5, 6, 7):
            tot[bars] = statistics.mean(
                simulate_match(teams[a], teams[b], fmt, comp, year, seed=seed, control={a: Fixed(bars)},
                               toss=b, decision="bat")["innings"][0]["runs"] for seed in range(n))
        print(f"edge {g}: " + "  ".join(f"bars {x}: {t:.1f}" for x, t in tot.items()), flush=True)


def scan_contain(fmt: str, ms: list[float], n: int = 400) -> None:
    """Win % of a side that contains all game (plan bar 1) against Normal, for each contain edge: containing
    pays when defending a target (squeezing the rate beats taking wickets), which first-innings totals can't
    show, so this edge is chosen by results: containing all game should win no more often than Normal."""
    from engine.control import Controller
    from engine.match import simulate_match
    from engine.situation import aggression_table
    comp, year, a, b, _ = SCAN[fmt]
    teams = {t["name"]: t for t in json.loads((ROOT / "data" / "teams_default.json").read_text(encoding="utf-8"))}

    class Fixed(Controller):
        def __init__(self, bars):
            super().__init__(a, {"ball"})
            self.bars = bars

        def decide(self, q):
            if q["kind"] == "ball" and q["side"] == "bowl":
                return {"bowl": {q["bowler"]["id"]: self.bars}}
            return None

    def win(bars):
        return 100 * sum(simulate_match(teams[a], teams[b], fmt, comp, year, seed=seed,
                                        control={a: Fixed(bars)})["result"].get("winner") == a
                         for seed in range(n)) / n
    tab = aggression_table(fmt)
    print(f"normal: win {win(5):.1f}%", flush=True)
    for m in ms:
        tab["contain_edge"] = m
        print(f"contain edge {m}: bar 1 win {win(1):.1f}%  bar 3 win {win(3):.1f}%", flush=True)


def main() -> None:
    import sys
    if len(sys.argv) > 2 and sys.argv[1] == "--scan-contain":
        scan_contain(sys.argv[2], [float(x) for x in sys.argv[3].split(",")])
        return
    if len(sys.argv) > 2 and sys.argv[1] == "--scan-bowl":
        scan_bowl(sys.argv[2], [float(x) for x in sys.argv[3].split(",")])
        return
    if len(sys.argv) > 2 and sys.argv[1] == "--scan":
        scan(sys.argv[2], [float(x) for x in sys.argv[3].split(",")])
        return
    for fmt in ("t20", "odi"):
        out = fit(fmt)
        (OUT / f"aggression_{fmt}.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
        print(fmt)
        for ph, r in out["phases"].items():
            s = r["slope"]
            print(f"  {ph:9s} {r['cells']:3d} cells, reliability {r['reliability']:.2f}; one bar = runs x{math.exp(r['step']):.3f}; "
                  + "  ".join(f"{m} {v:+.2f}" for m, v in s.items()))


if __name__ == "__main__":
    main()
