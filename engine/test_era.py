"""The era suite: do Tests of an earlier decade score as that decade did? (docs/test_match_plan.md section 7)

There are no real XIs to replay before ball-by-ball coverage. So the nations that played in a decade meet on
neutral grounds in that decade's baseline, rated for those years, and the runs per wicket and the run rate are
compared with the era table (data/raw_stats/years_test_pre.json: what Tests of those years really scored; for
the control decade, data/raw_stats/years_test.json). Gate: within 3% each. The share of Tests drawn is
compared with the real share (data/raw_stats/test_results.json) and reported: with 240 Tests it is known to
about 3 points, and the plan did not gate it.

Each side's XI is drawn for every Test from all who played for the nation in the decade, in proportion to their
caps (with a keeper and four to six bowlers). The plan said "classic sides", the most-capped players: measured,
those score 13% above the 2010s' real figure, where replays of real XIs are within 2%, because the most-capped
players are better than the players of an average Test. Drawn sides have the decade's mix of players, so they
test what the suite is for: do the era's baseline and the era's ratings give the era's scoring? `--classic` runs
the plan's version. The 2010s are the control: covered ball by ball, so the method itself can be checked.
Not fitted: four to six bowlers in an XI (what Test sides pick).

    python -m engine.test_era                 # 1900s to 1990s and the 2010s as a control, 240 Tests a decade
    python -m engine.test_era --tests 400

Every Test has its own seed, so any number of worker processes gives the same numbers.
Writes data/engine/calibration_test_era.json (history of runs, newest last).
"""
from __future__ import annotations

import argparse
import json
import time
import zlib
from datetime import datetime
import random
from functools import lru_cache
from itertools import combinations
from pathlib import Path

from . import history
from .data import _keepers, player
from .test_match import simulate_test
from .test_value import is_bowler

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "engine"
PRE = ROOT / "data" / "raw_stats" / "years_test_pre.json"
YEARS = ROOT / "data" / "raw_stats" / "years_test.json"
RESULTS = ROOT / "data" / "raw_stats" / "test_results.json"
CONTROL = 2010
DECADES = tuple(range(1900, 2000, 10)) + (CONTROL,)
BOWLERS = (4, 6)                 # specialist bowlers in a drawn XI
GATE = 3.0                       # per cent, the plan's number
MIN_SIDES = 3


@lru_cache(maxsize=None)
def era_table() -> dict:
    """year -> {"runs_per_wkt", "rpo"}: the era table, then the covered years."""
    t = {int(y): r for y, r in json.loads(PRE.read_text(encoding="utf-8")).items()}
    for y, r in json.loads(YEARS.read_text(encoding="utf-8")).items():
        t.setdefault(int(y), r)
    return t


def real(decade: int) -> dict:
    """Runs per wicket and run rate, the mean of the decade's years."""
    rows = [era_table()[y] for y in range(decade, decade + 10) if y in era_table()]
    return {"runs per wicket": sum(r["runs_per_wkt"] for r in rows) / len(rows),
            "run rate": sum(r["rpo"] for r in rows) / len(rows), "years": len(rows)}


def real_draws(decade: int) -> float:
    """The share of the decade's real Tests that were drawn."""
    ys = json.loads(RESULTS.read_text(encoding="utf-8"))["years"]
    rows = [ys[str(y)] for y in range(decade, decade + 10) if str(y) in ys]
    return sum(r["draws"] for r in rows) / max(sum(r["tests"] for r in rows), 1)


def nations(decade: int) -> list[str]:
    return [n for n, _ in history.nations("test", decade, decade + 9)]


@lru_cache(maxsize=None)
def pool(nation: str, decade: int) -> tuple:
    """((id, caps, keeper?, bowler?), ...) for everyone who played for the nation in the decade."""
    apps = history.appearances("test", nation, decade, decade + 9)
    keepers = _keepers("test")
    return tuple((pid, n, pid in keepers, is_bowler(player("test", pid, years=[decade, decade + 9])))
                 for pid, n in sorted(apps.items()))


def drawn_side(nation: str, decade: int, rng: random.Random) -> dict:
    """An XI drawn in proportion to caps, with a keeper and BOWLERS specialist bowlers."""
    ps = pool(nation, decade)
    xi = None
    for _ in range(200):
        left, xi = list(ps), []
        for _ in range(11):
            k = rng.choices(range(len(left)), [q[1] for q in left])[0]
            xi.append(left.pop(k))
        if any(q[2] for q in xi) and BOWLERS[0] <= sum(q[3] for q in xi) <= BOWLERS[1]:
            break
    return {"name": nation, "players": [q[0] for q in xi], "years": [decade, decade + 9]}


def plan(decade: int, tests: int, classic: bool = False) -> list[tuple]:
    """[(side a, side b, year, seed)]: every pairing in turn, the decade's years in turn (only years the era
    table has: no Tests were played in the war years)."""
    years = [y for y in range(decade, decade + 10) if y in era_table()]
    ns = nations(decade)
    fixed = {n: history.historical_team("test", n, decade, decade + 9) for n in ns} if classic else None
    pairs = list(combinations(ns, 2))
    out = []
    for k in range(tests):
        i, j = pairs[k % len(pairs)]
        if (k // len(pairs)) % 2:
            i, j = j, i
        seed = zlib.crc32(f"era|{decade}|{k}".encode()) & 0x7FFFFFFF
        rng = random.Random(seed ^ 0x5EED)
        a, b = (fixed[i], fixed[j]) if classic else (drawn_side(i, decade, rng), drawn_side(j, decade, rng))
        out.append((a, b, years[k % len(years)], seed))
    return out


def _play(task: tuple) -> dict:
    a, b, year, seed = task
    c = simulate_test(a, b, None, year, None, seed, use_wdl=False)
    inns = c["innings"]
    return {"runs": sum(i["runs"] for i in inns), "wkts": sum(i["wickets"] for i in inns),
            "balls": sum(i["balls"] for i in inns), "draw": c["result"]["type"] == "draw"}


def run_decade(decade: int, tests: int, jobs: int = 1, classic: bool = False) -> dict | None:
    if len(nations(decade)) < MIN_SIDES:
        return None
    tasks = plan(decade, tests, classic)
    if jobs > 1:
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(max_workers=jobs) as ex:
            ms = list(ex.map(_play, tasks, chunksize=8))
    else:
        ms = [_play(t) for t in tasks]
    r = real(decade)
    sim = {"runs per wicket": sum(m["runs"] for m in ms) / max(sum(m["wkts"] for m in ms), 1),
           "run rate": 6 * sum(m["runs"] for m in ms) / max(sum(m["balls"] for m in ms), 1)}
    diff = {k: (sim[k] / r[k] - 1) * 100 for k in sim}
    return {"decade": decade, "sides": nations(decade), "tests": len(ms), "real": r, "sim": sim,
            "diff %": diff, "ok": all(abs(d) <= GATE for d in diff.values()),
            "draw %": 100 * sum(m["draw"] for m in ms) / len(ms), "real draw %": 100 * real_draws(decade)}


def run(tests: int = 240, jobs: int = 1, label: str = "", save: bool = True, decades: tuple = DECADES,
        classic: bool = False) -> dict:
    t = time.time()
    rows = [r for d in decades if (r := run_decade(d, tests, jobs, classic))]
    print(f"\n=== test eras [{label}]: {tests} Tests a decade in {time.time() - t:.0f}s")
    print(f"   {'decade':8}{'sides':>6}  runs per wicket real/sim   diff    run rate real/sim   diff   drawn% real/sim  gate")
    for r in rows:
        print(f"   {r['decade']}s{'*' if r['decade'] == CONTROL else ' '} {len(r['sides']):5}   {r['real']['runs per wicket']:9.2f} /{r['sim']['runs per wicket']:6.2f}"
              f"{r['diff %']['runs per wicket']:8.1f}%   {r['real']['run rate']:7.2f} /{r['sim']['run rate']:5.2f}"
              f"{r['diff %']['run rate']:7.1f}%  {r['real draw %']:7.1f} /{r['draw %']:5.1f}  {'ok' if r['ok'] else 'MISS'} (+-{GATE:g}%)")
    met = sum(r["ok"] for r in rows)
    print(f"   decades inside the gate: {met} of {len(rows)}   (* the control: covered ball by ball)")
    rec = {"when": datetime.now().isoformat(timespec="seconds"), "suite": "test_era", "label": label, "tests": tests, "classic": classic,
           "decades": rows, "met": [met, len(rows)]}
    if save:
        path = OUT / "calibration_test_era.json"
        hist = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        hist.append(rec)
        path.write_text(json.dumps(hist, indent=1), encoding="utf-8")
    return rec


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tests", type=int, default=240, help="Tests a decade")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--label", default="")
    ap.add_argument("--no-save", action="store_true")
    ap.add_argument("--classic", action="store_true", help="the most-capped players of each nation (biased high)")
    a = ap.parse_args()
    run(a.tests, a.jobs, a.label, not a.no_save, classic=a.classic)
