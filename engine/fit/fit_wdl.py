"""Build the Test win / draw / loss table (engine/test_wdl.py) by playing the calibrated engine.

    python -m engine.fit.fit_wdl                 # about 20,000 Tests; several minutes on several processes
    python -m engine.fit.fit_wdl --tests 2000    # a quick look

Every real Test XI of 2015-26 plays itself (equal sides, so the table is nobody's favourite) on its real ground
in its real year, with the weather of that country. After every over the state (innings, wickets, lead or runs
needed, overs left in the match) is counted with how the match ended for the side batting. The counts are spread
over a grid, smoothed, and written to data/engine/wdl_test.json.

One Test in ten is kept out of the table and used to score it (how far its chances are from what happened).
Rebuild after any recalibration of the Test engine.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import time
import zlib
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from ..test_calibrate import COMP, fixtures
from ..test_match import simulate_test
from ..test_wdl import PATH, WDL

X0, X_STEP, NX = -600, 30, 41            # the grid: lead (or minus runs needed) from -600 to 600 in steps of 30
L_STEP, NL = 18, 26                      # overs left in the match, 0 to 450 in steps of 18
ENOUGH = 150                             # a cell is trusted at this many (smoothed) states; below it, smooth more
HOLD = 10                                # one Test in this many scores the table instead of making it
REF = (3, 0, 0, 225)                     # where a run's worth is read: third innings starting level, half the time left
CHUNK = 40


def states(card: dict) -> list[tuple]:
    """(innings, wickets, x, overs left, outcome for the batting side: 0 win, 1 draw or tie, 2 loss) at the start
    of every innings and after every over, except the over that ended an innings all out or with the target
    reached (that state is the next innings' start)."""
    res = card["result"]
    out = []
    for inn in card["innings"]:
        log = inn.get("overs_log") or []
        if not log:
            continue
        oc = 1 if not res.get("winner") else 0 if res["winner"] == inn["team"] else 2
        n = inn["number"]
        x0 = -inn["target"] if inn.get("target") else inn["lead"] - inn["runs"]
        out.append((n, 0, x0, log[0]["left"] + 1, oc))
        last = len(log) - 1
        for k, o in enumerate(log):
            if k == last and inn.get("ended") in ("all out", "target"):
                break
            out.append((n, min(o["wickets"], 9), x0 + o["total"], o["left"], oc))
    return out


def _chunk(tasks: list) -> tuple:
    counts: dict = {}
    held = []
    for spec, year, venue, seed in tasks:
        card = simulate_test(dict(spec, name="Side A"), dict(spec, name="Side B"), COMP, year, venue, seed,
                             use_wdl=False)
        st = states(card)
        if seed % HOLD == 0:
            held.extend(st)
            continue
        for n, w, x, left, oc in st:
            fx = min(max((x - X0) / X_STEP, 0.0), NX - 1.000001)
            fl = min(max(left / L_STEP, 0.0), NL - 1.000001)
            xi, li = int(fx), int(fl)
            tx, tl = fx - xi, fl - li
            for dl, wl in ((0, 1 - tl), (1, tl)):
                for dx, wx in ((0, 1 - tx), (1, tx)):
                    if wl * wx > 0:
                        c = counts.setdefault((n, w, li + dl, xi + dx), [0.0, 0.0, 0.0])
                        c[oc] += wl * wx
    return counts, held, len(tasks)


def simulate(n_tests: int, jobs: int) -> tuple:
    fx = fixtures()
    sides = [(f[s], f["year"], f["venue"], f"{f['id']}|{s}") for f in fx for s in ("a", "b")]
    reps = max(1, math.ceil(n_tests / len(sides)))
    tasks = [(spec, year, venue, zlib.crc32(f"wdl|{key}|{r}".encode()) & 0x7FFFFFFF)
             for r in range(reps) for spec, year, venue, key in sides][:n_tests]
    chunks = [tasks[i:i + CHUNK] for i in range(0, len(tasks), CHUNK)]
    counts: dict = {}
    held: list = []
    done = 0
    t = time.time()

    def take(res):
        nonlocal done
        c, h, n = res
        for k, v in c.items():
            a = counts.setdefault(k, [0.0, 0.0, 0.0])
            for j in range(3):
                a[j] += v[j]
        held.extend(h)
        done += n
        if done % (CHUNK * 25) == 0 or done == len(tasks):
            print(f"   {done} of {len(tasks)} Tests, {time.time() - t:.0f}s", flush=True)
    if jobs <= 1:
        for ch in chunks:
            take(_chunk(ch))
    else:
        with ProcessPoolExecutor(max_workers=jobs) as ex:
            for res in ex.map(_chunk, chunks):
                take(res)
    return counts, held, len(tasks)


def _smooth(g: list) -> list:
    """One pass of a 1-2-1 kernel along the lead and the overs left, and a light 1-6-1 along the wickets."""
    def axis(g, step_of, kern):
        out = [[[[[0.0] * 3 for _ in range(NX)] for _ in range(NL)] for _ in range(10)] for _ in range(4)]
        for i in range(4):
            for w in range(10):
                for li in range(NL):
                    for xi in range(NX):
                        acc = out[i][w][li][xi]
                        for d, k in kern:
                            w2, l2, x2 = step_of(w, li, xi, d)
                            if 0 <= w2 < 10 and 0 <= l2 < NL and 0 <= x2 < NX:
                                src = g[i][w2][l2][x2]
                                acc[0] += k * src[0]
                                acc[1] += k * src[1]
                                acc[2] += k * src[2]
        return out
    k121 = ((-1, 1.0), (0, 2.0), (1, 1.0))
    g = axis(g, lambda w, li, xi, d: (w, li, xi + d), k121)
    g = axis(g, lambda w, li, xi, d: (w, li + d, xi), k121)
    return axis(g, lambda w, li, xi, d: (w + d, li, xi), ((-1, 1.0), (0, 6.0), (1, 1.0)))


def build(counts: dict) -> dict:
    raw = [[[[list(counts.get((i + 1, w, li, xi), (0.0, 0.0, 0.0))) for xi in range(NX)] for li in range(NL)]
            for w in range(10)] for i in range(4)]
    levels = [raw]
    for _ in range(4):                       # raw, then 1 to 4 smoothing passes
        levels.append(_smooth(levels[-1]))
    # a pass multiplies every count by 4 * 4 * 8; bring the totals back to states
    scale = [1.0 / (128 ** k) for k in range(len(levels))]
    probs = [[[[None] * NX for _ in range(NL)] for _ in range(10)] for _ in range(4)]
    used = [0] * len(levels)
    for i in range(4):
        for w in range(10):
            for li in range(NL):
                for xi in range(NX):
                    for k in range(1, len(levels)):          # never the raw counts: always one pass at least
                        c = levels[k][i][w][li][xi]
                        tot = sum(c) * scale[k]
                        if tot >= ENOUGH or (k == len(levels) - 1 and tot >= 5):
                            s = sum(c)
                            probs[i][w][li][xi] = (c[0] / s, c[1] / s)
                            used[k] += 1
                            break
    # cells no Test came near: the nearest filled cell along the lead, then the overs left, then the wickets
    def nearest(i, w, li, xi):
        for d in range(1, max(NX, NL)):
            for l2, x2 in ((li, xi - d), (li, xi + d)):
                if 0 <= x2 < NX and probs[i][w][l2][x2]:
                    return probs[i][w][l2][x2]
        for d in range(1, NL):
            for l2 in (li - d, li + d):
                if 0 <= l2 < NL and probs[i][w][l2][xi]:
                    return probs[i][w][l2][xi]
        for d in range(1, 10):
            for w2 in (w - d, w + d):
                if 0 <= w2 < 10 and probs[i][w2][li][xi]:
                    return probs[i][w2][li][xi]
        return (1 / 3, 1 / 3)
    filled = [[[[probs[i][w][li][xi] or nearest(i, w, li, xi) for xi in range(NX)] for li in range(NL)]
               for w in range(10)] for i in range(4)]
    x_zero = -X0 // X_STEP
    for i in range(4):
        for w in range(10):
            for xi in range(NX):
                filled[i][w][0][xi] = (0.0, 1.0)             # no time left: a draw (the laws, not a fit)
            if i == 3:
                for li in range(1, NL):
                    for xi in range(x_zero, NX):
                        filled[i][w][li][xi] = (1.0, 0.0)    # nothing left to get: won
    out = {"x0": X0, "x_step": X_STEP, "nx": NX, "l_step": L_STEP, "nl": NL, "win": {}, "draw": {}}
    for i in range(4):
        out["win"][str(i + 1)] = [[round(1000 * filled[i][w][li][xi][0]) for li in range(NL) for xi in range(NX)]
                                  for w in range(10)]
        out["draw"][str(i + 1)] = [[round(1000 * filled[i][w][li][xi][1]) for li in range(NL) for xi in range(NX)]
                                   for w in range(10)]
    out["cells_by_passes"] = used[1:]
    out["cells_filled_from_a_neighbour"] = 4 * 10 * NL * NX - sum(used)
    return out


def score(t: dict, held: list) -> dict:
    """How well the table predicts the Tests kept out of it: the Brier score and log loss against always saying
    the overall shares, and what happened when it said 0-20%, 20-40% ... for a win."""
    w = WDL(dict(t, runs_per_win=1.0))
    n = len(held)
    base = [sum(1 for s in held if s[4] == k) / n for k in range(3)]
    br = br0 = ll = ll0 = 0.0
    bins = [[0, 0.0, 0] for _ in range(5)]
    dbins = [[0, 0.0, 0] for _ in range(5)]
    for i, wk, x, left, oc in held:
        pw, pd = w.probs(i, wk, x, left)
        p = (pw, pd, max(1 - pw - pd, 0.0))
        br += sum((p[k] - (oc == k)) ** 2 for k in range(3))
        br0 += sum((base[k] - (oc == k)) ** 2 for k in range(3))
        ll -= math.log(max(p[oc], 1e-3))
        ll0 -= math.log(max(base[oc], 1e-3))
        for b, q, hit in ((bins, pw, oc == 0), (dbins, pd, oc == 1)):
            r = b[min(int(q * 5), 4)]
            r[0] += 1
            r[1] += q
            r[2] += hit
    cal = lambda b: [{"said %": round(100 * r[1] / r[0], 1), "happened %": round(100 * r[2] / r[0], 1), "states": r[0]}
                     for r in b if r[0]]
    return {"states": n, "brier": round(br / n, 4), "brier_base": round(br0 / n, 4),
            "log_loss": round(ll / n, 4), "log_loss_base": round(ll0 / n, 4),
            "win_calibration": cal(bins), "draw_calibration": cal(dbins)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tests", type=int, default=20000)
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--out", default=str(PATH))
    a = ap.parse_args(argv)
    t0 = time.time()
    counts, held, n = simulate(a.tests, a.jobs)
    print(f"{n} Tests played in {time.time() - t0:.0f}s; building the table")
    t = build(counts)
    t["tests"] = n
    t["held_out_score"] = score(t, held) if held else None
    w = WDL(dict(t, runs_per_win=1.0))
    i, wk, x, left = REF
    slope = (w.value(i, wk, x + 60, left) - w.value(i, wk, x - 60, left)) / 120
    t["runs_per_win"] = round(1 / max(slope, 1e-4), 1)
    t["note"] = ("Built by engine/fit/fit_wdl.py from Tests played by the engine between equal sides. "
                 "Rebuild after any recalibration.")
    Path(a.out).write_text(json.dumps(t, separators=(",", ":")), encoding="utf-8")
    print(json.dumps({k: t[k] for k in ("tests", "runs_per_win", "cells_by_passes", "cells_filled_from_a_neighbour",
                                        "held_out_score")}, indent=1))
    print(f"wrote {a.out} in {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
