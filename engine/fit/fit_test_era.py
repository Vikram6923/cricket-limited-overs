"""Era factors for Tests before ball-by-ball coverage (engine/test_conditions.py era_factors).

The baseline of an early year is the modern one scaled by the era table (scripts/build_ratings.py). The engine's
own tables (settling in, the state of the innings, declarations) were learned from modern Tests, and they do not
average out to 1 in a slower era: batters are in for longer and more innings are left unfinished, so the top
order bats a larger share of the balls. Measured: 2010s players given the 1955 baseline score 15% more runs a
wicket than that baseline, against 3% with their own.

Time was different too. Over rates and hours of play were not today's, and at 90 overs a day the 1950s had
twice the draws they really had (59% against 31%: data/raw_stats/test_results.json, every Test's result).

So for each decade the nations of that decade play each other (engine/test_era.py: XIs drawn in proportion to
caps) and three numbers are moved until the simulation agrees with the record: a factor on the run rate and one
on the wicket rate, until the run rate and the runs per wicket are the era table's; and the overs in a day,
until as many Tests are drawn as really were (so "overs in a day" stands for everything that set how much
cricket a Test of that time held: over rates, hours, days, rest days; the weather is drawn as today's). Each step multiplies a factor by (real / simulated) to the power of a gain
that falls as 1, 1, 1/2, 1/3, 1/4 (stochastic approximation: later steps average out the noise of the earlier).

    python -m engine.fit.fit_test_era          # about 40 minutes

Writes data/engine/test_era.json. Run again after anything that changes how early Tests play.
"""
from __future__ import annotations

import argparse
import json
import math
import zlib
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from .. import test_era
from ..test_match import simulate_test

OUT = Path(__file__).resolve().parent.parent.parent / "data" / "engine" / "test_era.json"
UNTIL = 2001                 # the first year with ball-by-ball Tests: from here the baseline is measured
GAINS = (1.0, 1.0, 1 / 2, 1 / 3, 1 / 4)
STEPS = len(GAINS)
TESTS = 400
DRAW_GAIN = 1.5              # log overs per unit of draw share: about the slope measured between 90 and 110 overs
DAY_OVERS = (60, 180)        # the search stays inside these


def _play(task: tuple) -> tuple:
    a, b, year, seed, era = task
    c = simulate_test(a, b, None, year, None, seed, use_wdl=False, era=era)
    inns = c["innings"]
    return (sum(i["runs"] for i in inns), sum(i["wickets"] for i in inns), sum(i["balls"] for i in inns),
            c["result"]["type"] == "draw")


def fit_decade(decade: int, ex, tests: int = TESTS) -> dict:
    real = test_era.real(decade)
    real_wpb = real["run rate"] / 6 / real["runs per wicket"]
    real_draw = test_era.real_draws(decade)
    f = {"runs": 1.0, "wkt": 1.0, "day_overs": 90}
    hist = []
    for step in range(STEPS + 1):
        tasks = [(a, b, y, zlib.crc32(f"erafit|{decade}|{step}|{k}".encode()) & 0x7FFFFFFF, f)
                 for k, (a, b, y, _) in enumerate(test_era.plan(decade, tests))]
        ms = list(ex.map(_play, tasks, chunksize=8))
        runs, wk, balls = (sum(m[i] for m in ms) for i in range(3))
        rr, rpw, draw = 6 * runs / balls, runs / wk, sum(m[3] for m in ms) / len(ms)
        hist.append({"runs": round(f["runs"], 4), "wkt": round(f["wkt"], 4), "day_overs": f["day_overs"],
                     "run rate": round(rr, 3), "runs per wicket": round(rpw, 2), "draw": round(draw, 3)})
        print(f"  {decade}s step {step}: factors {f['runs']:.3f} {f['wkt']:.3f}, {f['day_overs']} overs a day -> "
              f"run rate {rr:.2f} (real {real['run rate']:.2f}), runs per wicket {rpw:.2f} "
              f"(real {real['runs per wicket']:.2f}), drawn {100 * draw:.0f}% (real {100 * real_draw:.0f}%)", flush=True)
        if step == STEPS:
            break
        g = GAINS[step]
        overs = f["day_overs"] * math.exp(g * DRAW_GAIN * (draw - real_draw))
        f = {"runs": f["runs"] * (real["run rate"] / rr) ** g, "wkt": f["wkt"] * (real_wpb / (runs / balls / rpw)) ** g,
             "day_overs": int(round(min(max(overs, DAY_OVERS[0]), DAY_OVERS[1])))}
    return {"runs": round(f["runs"], 4), "wkt": round(f["wkt"], 4), "day_overs": f["day_overs"], "steps": hist}


def main(jobs: int = 4) -> None:
    decades = [d for d in range(1880, UNTIL - 1, 10) if len(test_era.nations(d)) >= 2]
    out = {"until": UNTIL, "tests": TESTS, "decades": {}}
    with ProcessPoolExecutor(max_workers=jobs) as ex:
        for d in decades:
            out["decades"][str(d)] = fit_decade(d, ex)
    OUT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--jobs", type=int, default=4)
    main(ap.parse_args().jobs)
