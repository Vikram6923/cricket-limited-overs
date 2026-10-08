"""Tables for the franchise career mode (engine/career.py): how players change from season to season.

    python -m engine.fit.fit_career        -> data/engine/career_t20.json

From the per-player, per-year fit statistics of the ratings (data/ratings_t20_years.json: actual and expected
counts per metric, expected already allowing for era, competition and opponents) and dates of birth
(data/raw_stats/styles.json):

- age curve, per side (bat / bowl) and metric: A ~ Poisson(E x player level x f(age)), fitted by alternating
  maximum likelihood (player fixed effects, so it is how a player changes with age, not who plays at which age);
  ages 19-39 (younger / older pooled into the ends), smoothed over neighbouring ages, f = 1 at the
  exposure-weighted mean;
- season form, per side, for runs and wickets: the spread of a player's yearly level around his level x age
  curve (see drift());
- retirement: the chance an established player (30+ T20 matches) plays his last season at each age, from
  careers that ended by 2023 (later ones may still be going);
- debut age: the median age in a player's first T20 season, to place players with no known date of birth.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
METRICS = ("runs", "wkt", "dot", "four", "six")
AGE_LO, AGE_HI = 19, 39
LAST_DATA_YEAR = 2023      # careers ending after this may not have ended


def births() -> dict:
    st = json.loads((DATA / "raw_stats" / "styles.json").read_text(encoding="utf-8"))
    return {pid: int(r["dob"][:4]) for pid, r in st.items() if (r.get("dob") or "")[:4].isdigit()}


def age_curve(rows: dict, born: dict, k: int) -> tuple[dict, dict]:
    """rows: pid -> year -> stats row; metric index k. Returns (age -> factor, pid -> player level)."""
    obs = []                                  # (pid, age, A, E)
    for pid, ys in rows.items():
        if pid not in born:
            continue
        for y, r in ys.items():
            a, e = r[1 + 2 * k], r[2 + 2 * k]
            if e > 0:
                obs.append((pid, min(AGE_HI, max(AGE_LO, int(y) - born[pid])), a, e))
    f = {a: 1.0 for a in range(AGE_LO, AGE_HI + 1)}
    lvl = defaultdict(lambda: 1.0)
    for _ in range(30):
        sa, se = defaultdict(float), defaultdict(float)
        for pid, age, a, e in obs:
            sa[pid] += a
            se[pid] += e * f[age]
        lvl = {p: (sa[p] + 1.0) / (se[p] + 1.0) for p in sa}       # +1 pseudo count keeps zero records finite
        sa, se = defaultdict(float), defaultdict(float)
        for pid, age, a, e in obs:
            sa[age] += a
            se[age] += e * lvl[pid]
        f = {age: sa[age] / se[age] if se[age] else 1.0 for age in f}
    expo = defaultdict(float)
    for pid, age, a, e in obs:
        expo[age] += e
    # smooth: exposure-weighted average with the neighbours (weights 1, 2, 1)
    sm = {}
    for age in f:
        w = s = 0.0
        for d, k2 in ((-1, 1), (0, 2), (1, 1)):
            if age + d in f:
                w += k2 * expo[age + d]
                s += k2 * expo[age + d] * math.log(f[age + d])
        sm[age] = s / w if w else 0.0
    mean = sum(sm[a] * expo[a] for a in sm) / sum(expo.values())
    return {a: round(math.exp(sm[a] - mean), 4) for a in sm}, lvl


def drift(rows: dict, born: dict, k: int, m: str, side: str, curve: dict, lvl: dict) -> dict:
    """Season form of metric k: the spread of a player's yearly level around his level x age curve.

    Raw moment (precision-weighted, sampling noise subtracted, engine.periods.fit_tau2) scaled by the factor the
    year-range ratings validated on held-out years (engine.periods.TAU_SCALE): the raw moment overstates real
    year-to-year change. Persistence: the residual autocovariances at lags 1-3 (players with 5+ seasons) are
    negative, i.e. no carry-over beyond the player's level and age, so each season's form is drawn afresh."""
    from engine.periods import TAU_SCALE, _noise, fit_tau2
    pairs, cov = [], {1: [0.0, 0.0], 2: [0.0, 0.0], 3: [0.0, 0.0]}
    for pid, ys in rows.items():
        if pid not in born or pid not in lvl:
            continue
        res = {}
        for y, r in ys.items():
            e = r[2 + 2 * k]
            if e < 2:                    # too little play that year to say anything
                continue
            age = min(AGE_HI, max(AGE_LO, int(y) - born[pid]))
            mu = lvl[pid] * curve[age]
            ratio = r[1 + 2 * k] / (e * mu)
            pairs.append(((ratio - 1) ** 2, _noise(m, r, k, mu) / (mu * mu)))
            res[int(y)] = (ratio - 1, e)
        if len(ys) >= 5:
            for y, (d, e) in res.items():
                for lag in cov:
                    if y + lag in res:
                        d2, e2 = res[y + lag]
                        cov[lag][0] += min(e, e2) * d * d2
                        cov[lag][1] += min(e, e2)
    raw = fit_tau2(pairs)
    sigma2 = raw * TAU_SCALE["t20"][side]
    return {"sigma": round(math.sqrt(sigma2), 4), "raw_tau2": round(raw, 5), "scale": TAU_SCALE["t20"][side],
            "lag_cov": {str(lag): round(s / w, 5) for lag, (s, w) in cov.items() if w}}


def careers(born: dict) -> tuple[dict, int]:
    """Retirement chance by age and the median debut age."""
    first, last, matches = {}, {}, defaultdict(int)
    for f in ("players_t20.json", "players_t20_league.json"):
        for pid, r in json.loads((DATA / "raw_stats" / f).read_text(encoding="utf-8")).items():
            for y, x in (r.get("by_year") or {}).items():
                y = int(y)
                first[pid] = min(first.get(pid, 9999), y)
                last[pid] = max(last.get(pid, 0), y)
                matches[pid] += x.get("m", 0)
    debut = sorted(first[p] - born[p] for p in first if p in born and 15 <= first[p] - born[p] <= 40)
    at_risk, ended = defaultdict(int), defaultdict(int)
    for pid in first:
        if pid not in born or matches[pid] < 30:
            continue
        for y in range(first[pid], min(last[pid], LAST_DATA_YEAR) + 1):
            age = y - born[pid]
            at_risk[age] += 1
            ended[age] += y == last[pid]
    hazard = {}
    for age in range(20, 43):
        n = sum(at_risk[a] for a in (age - 1, age, age + 1))
        hazard[age] = round(sum(ended[a] for a in (age - 1, age, age + 1)) / n, 4) if n >= 30 else None
    for age in range(43, 46):
        hazard[age] = 1.0
    for age in range(42, 19, -1):                     # thin old ages: no lower than the next younger age
        if hazard[age] is None:
            hazard[age] = hazard.get(age + 1) or 1.0
    return {str(a): h for a, h in hazard.items()}, debut[len(debut) // 2]


def main() -> None:
    years = json.loads((DATA / "ratings_t20_years.json").read_text(encoding="utf-8"))
    born = births()
    out = {"ages": [AGE_LO, AGE_HI], "curve": {}, "drift": {}}
    for side in ("bat", "bowl"):
        out["curve"][side], out["drift"][side] = {}, {}
        for k, m in enumerate(METRICS):
            curve, lvl = age_curve(years[side], born, k)
            out["curve"][side][m] = {str(a): v for a, v in curve.items()}
            if m in ("runs", "wkt"):
                out["drift"][side][m] = drift(years[side], born, k, m, side, curve, lvl)
    out["retire"], out["debut_age"] = careers(born)
    path = DATA / "engine" / "career_t20.json"
    path.write_text(json.dumps(out, indent=1), encoding="utf-8")
    for side in ("bat", "bowl"):
        for m in ("runs", "wkt"):
            c = out["curve"][side][m]
            print(side, m, " ".join(f"{a}:{c[str(a)]:.3f}" for a in range(AGE_LO, AGE_HI + 1, 2)), out["drift"][side][m])
    print("retire", {a: h for a, h in out["retire"].items() if int(a) % 3 == 0}, "debut age", out["debut_age"])


if __name__ == "__main__":
    main()
