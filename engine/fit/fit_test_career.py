"""Tables for the Test career (engine/test_career.py): how Test players change from year to year.

    python -m engine.fit.fit_test_career        -> data/engine/career_test.json

The method is the T20 career's (fit_career.py: its age-curve and season-form functions are used as they are),
on the Test ratings' per-player, per-year statistics (data/ratings_test_years.json) and years of birth
(data/raw_stats/styles.json, else data/raw_stats/test_careers.json):

- age curve, per side (bat / bowl) and metric: how one player changes with age (player fixed effects);
- season form, per side, for runs and wickets: the spread of a player's yearly level around his level x age,
  less the part that carries over from year to year (in T20 none does; in Tests a batter's dismissals do);
- retirement: the chance that a year is an established player's last, at each age, counted over the years
  in which he was a regular (ESTABLISHED Tests or more in all, REGULAR or more that year), from careers that
  ended by LAST_DATA_YEAR. Counted over every year instead, the table mostly measures being dropped: it ended
  one career in seventy at 24, and the career mode drops players by its own rule (not picked for some years);
- debut age: the median age in a first Test year.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict

from ..periods import TAU_SCALE
from . import fit_career as fc

DATA = fc.DATA
METRICS = fc.METRICS
ESTABLISHED = 20             # Tests; T20 uses 30 matches, and a Test player plays far fewer matches a year
REGULAR = 3                  # Tests in a year: he was in the side
LAST_DATA_YEAR = fc.LAST_DATA_YEAR


def births() -> dict:
    born = fc.births()
    p = DATA / "raw_stats" / "test_careers.json"
    for pid, q in (json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}).items():
        if pid not in born and q.get("born"):
            born[pid] = int(q["born"])
    return born


def careers(born: dict) -> tuple[dict, int]:
    """Retirement chance by age and the median debut age, from the ball-by-ball years."""
    first, last, matches = {}, {}, defaultdict(int)
    covered = json.loads((DATA / "raw_stats" / "players_test.json").read_text(encoding="utf-8"))
    pre = json.loads((DATA / "raw_stats" / "test_careers.json").read_text(encoding="utf-8"))
    for pid, r in covered.items():
        for y, x in (r.get("by_year") or {}).items():
            first[pid] = min(first.get(pid, 9999), int(y))
            last[pid] = max(last.get(pid, 0), int(y))
            matches[pid] += x.get("m", 0)
        part = (pre.get(pid) or {}).get("pre") or {}
        if part.get("tests"):                    # his Tests before coverage count toward "established"
            matches[pid] += part["tests"]
            first[pid] = min(first[pid], part["first"])
    debut = sorted(first[p] - born[p] for p in first if p in born and 15 <= first[p] - born[p] <= 40)
    at_risk, ended = defaultdict(int), defaultdict(int)
    for pid in last:
        if pid not in born or matches[pid] < ESTABLISHED:
            continue
        for ys, x in covered[pid]["by_year"].items():
            y = int(ys)
            if y > LAST_DATA_YEAR or x.get("m", 0) < REGULAR:
                continue
            age = y - born[pid]
            at_risk[age] += 1
            ended[age] += y == last[pid]
    hazard = {}
    for age in range(20, 43):
        n = sum(at_risk[a] for a in (age - 1, age, age + 1))
        hazard[age] = round(sum(ended[a] for a in (age - 1, age, age + 1)) / n, 4) if n >= 30 else None
    for age in range(43, 46):
        hazard[age] = 1.0
    for age in range(42, 19, -1):
        if hazard[age] is None:
            hazard[age] = hazard.get(age + 1) or 1.0
    return {str(a): h for a, h in hazard.items()}, debut[len(debut) // 2]


def main() -> None:
    years = json.loads((DATA / "ratings_test_years.json").read_text(encoding="utf-8"))
    born = births()
    out = {"ages": [fc.AGE_LO, fc.AGE_HI], "curve": {}, "drift": {}}
    for side in ("bat", "bowl"):
        out["curve"][side], out["drift"][side] = {}, {}
        for k, m in enumerate(METRICS):
            curve, lvl = fc.age_curve(years[side], born, k)
            out["curve"][side][m] = {str(a): v for a, v in curve.items()}
            if m in ("runs", "wkt"):
                d = fc.drift(years[side], born, k, m, side, curve, lvl)      # scaled there with the T20 factor
                d["scale"] = TAU_SCALE["test"][side]
                # What carries over from year to year is not form. In Tests a batter's dismissals do carry
                # over (lag covariances as large as the spread itself: his level, estimated from few
                # dismissals, is off by the same amount every year), so that part is taken out.
                lags = list(d["lag_cov"].values())
                d["carried"] = round(max(sum(lags) / len(lags), 0.0), 5) if lags else 0.0
                d["sigma"] = round(math.sqrt(max(d["raw_tau2"] - d["carried"], 0.0) * d["scale"]), 4)
                out["drift"][side][m] = d
    out["retire"], out["debut_age"] = careers(born)
    out["established"], out["regular"] = ESTABLISHED, REGULAR
    (DATA / "engine" / "career_test.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    for side in ("bat", "bowl"):
        for m in ("runs", "wkt"):
            c = out["curve"][side][m]
            print(side, m, " ".join(f"{a}:{c[str(a)]:.3f}" for a in range(fc.AGE_LO, fc.AGE_HI + 1, 2)), out["drift"][side][m])
    print("retire", {a: h for a, h in out["retire"].items() if int(a) % 3 == 0}, "debut age", out["debut_age"])


if __name__ == "__main__":
    main()
