"""Run every test script, several at a time, and say which failed.

    python tests/run_all.py            # all of them, on most of this computer's cores (about a minute)
    python tests/run_all.py -j 1       # one at a time
    python tests/run_all.py engine tournament     # only tests/test_engine.py and tests/test_tournament.py

Each script is its own process (they patch engine functions and start servers, so they must not share one), and
the longest ones start first. Exit code 1 if any script failed; a failed script's output is printed in full.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
SLOW_FIRST = ("state_career", "engine", "career", "auction", "multiplayer", "control", "aggression")


def run(path: Path) -> tuple[str, int, float, str]:
    t = time.time()
    env = dict(os.environ, PYTHONHASHSEED=os.environ.get("PYTHONHASHSEED", "random"))
    p = subprocess.run([sys.executable, str(path)], cwd=HERE.parent, capture_output=True, text=True, env=env)
    return path.stem, p.returncode, time.time() - t, p.stdout + p.stderr


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("names", nargs="*", help="test scripts to run (engine, tournament ...); default: all")
    ap.add_argument("-j", "--jobs", type=int, default=max(1, min(8, (os.cpu_count() or 2) - 1)))
    a = ap.parse_args(argv)
    files = sorted(HERE.glob("test_*.py"))
    if a.names:
        want = {n.removeprefix("test_").removesuffix(".py") for n in a.names}
        missing = want - {f.stem.removeprefix("test_") for f in files}
        if missing:
            print("no such test script:", ", ".join(sorted(missing)))
            return 2
        files = [f for f in files if f.stem.removeprefix("test_") in want]
    rank = {n: i for i, n in enumerate(SLOW_FIRST)}
    files.sort(key=lambda f: rank.get(f.stem.removeprefix("test_"), len(rank)))
    t0, failed = time.time(), []
    with ThreadPoolExecutor(max_workers=a.jobs) as pool:
        for name, code, secs, out in pool.map(run, files):
            print(f"{'ok  ' if code == 0 else 'FAIL'} {name:22} {secs:5.0f}s")
            if code:
                failed.append(name)
                print(out.rstrip())
    print(f"{len(files) - len(failed)} of {len(files)} test scripts passed in {time.time() - t0:.0f}s"
          + (f"; failed: {', '.join(failed)}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
