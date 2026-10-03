"""Ratings for a year range ("India 2007-2011"), without refitting the whole model.

`scripts/build_ratings.py` stores, per player and calendar year, the sufficient statistics of the fit: actual and
expected counts per metric (expected already includes the era baseline and the opponents' indexes). A period
index is the player's actual / expected over the chosen years, shrunk toward his career index by empirical Bayes:
the spread of true period-vs-career differences (tau^2) is estimated from all players active in those years, so
a short or thin period stays close to the career rating and a long, well-measured one can move away from it.

The engine applies the result as a ratio (period / career) to the player's phase indexes, keeping the shape of
his phase record. Wides, no-balls and run-outs stay career-long.
"""
from __future__ import annotations

import json
from functools import lru_cache

from .data import DATA, METRICS

MIN_BALLS_TAU = 120   # same rule as the career fit: players with this many balls estimate tau^2
# The moment estimate of tau^2 overstates how much a player's level really moves between periods (the ball-level
# noise model understates innings-to-innings noise), so period ratings with the raw tau^2 predicted held-out
# years worse than career ratings. These multiples were chosen by held-out-year cross-validation
# (scripts/validate_periods.py --holdout 2012 2016 2019 2022; best of 0.05 / 0.1 / 0.2 for runs, window +-2 years;
# results in docs/engine_progress.md).
TAU_SCALE = {"odi": {"bat": 0.1, "bowl": 0.1}, "t20": {"bat": 0.2, "bowl": 0.05}}


def _noise(m: str, row: list, k: int, prior: float) -> float:
    """Sampling variance of A/E for metric m (index k) in an aggregated row."""
    e, n = row[2 + 2 * k], row[0]
    if e <= 0 or n <= 0:
        return 1.0
    if m == "runs":
        return row[-1] / (e * e)
    return prior * max(1 - e / n, 0.05) / e


def fit_tau2(pairs: list[tuple[float, float]]) -> float:
    """Precision-weighted moment estimate of tau^2 from (squared deviation, its noise variance) pairs, as in the
    career fit (weights 1/(tau2+v)^2, iterated)."""
    tau2 = 0.02
    for _ in range(50):
        if not pairs:
            break
        sw = swd = 0.0
        for d2, v in pairs:
            w = 1.0 / (tau2 + v) ** 2
            sw += w
            swd += w * (d2 - v)
        new = max(swd / sw, 1e-4)
        if abs(new - tau2) < 1e-6:
            return new
        tau2 = new
    return tau2


def period_indexes(rows: dict, career: dict, y1: int, y2: int, tau_scale: float = 1.0) -> tuple[dict, dict, dict]:
    """rows: pid -> {year: [balls, A_runs, E_runs, A_wkt, E_wkt, ..., V_runs]}; career: pid -> {metric: idx}.
    Returns (pid -> {metric: period idx}, metric -> tau^2, pid -> balls in the period).

    tau^2 (how far a player's true level in a period strays from his career level) is estimated from players with
    at least MIN_BALLS_TAU balls both inside and outside the period: E[(rate_in - rate_out)^2] - noise_in - noise_out.
    Comparing with the career index instead would understate it, because the career includes the period itself.
    """
    ids, inside, outside = [], [], []
    for pid, by_year in rows.items():
        if pid not in career:
            continue
        acc_in = acc_out = None
        for yr, row in by_year.items():
            if y1 <= int(yr) <= y2:
                acc_in = list(row) if acc_in is None else [a + b for a, b in zip(acc_in, row)]
            else:
                acc_out = list(row) if acc_out is None else [a + b for a, b in zip(acc_out, row)]
        if acc_in and acc_in[0] > 0:
            ids.append(pid)
            inside.append(acc_in)
            outside.append(acc_out)
    out = {pid: {} for pid in ids}
    tau = {}
    for k, m in enumerate(METRICS):
        prior = [career[pid].get(m, 1.0) for pid in ids]
        pairs = []
        for a_in, a_out, p in zip(inside, outside, prior):
            if not a_out or a_in[0] < MIN_BALLS_TAU or a_out[0] < MIN_BALLS_TAU:
                continue
            e_in, e_out = a_in[2 + 2 * k], a_out[2 + 2 * k]
            if e_in <= 0 or e_out <= 0:
                continue
            d = a_in[1 + 2 * k] / e_in - a_out[1 + 2 * k] / e_out
            pairs.append((d * d, _noise(m, a_in, k, p) + _noise(m, a_out, k, p)))
        tau[m] = fit_tau2(pairs) * tau_scale
        for pid, a_in, p in zip(ids, inside, prior):
            e = a_in[2 + 2 * k]
            if e <= 0:
                out[pid][m] = p
                continue
            v = _noise(m, a_in, k, p)
            out[pid][m] = p + tau[m] / (tau[m] + v) * (a_in[1 + 2 * k] / e - p)
    return out, tau, {pid: a[0] for pid, a in zip(ids, inside)}


@lru_cache(maxsize=4)
def load_years(fmt: str) -> dict:
    path = DATA / f"ratings_{fmt}_years.json"
    if not path.exists():
        return {"bat": {}, "bowl": {}}
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=64)
def period_ratios(fmt: str, y1: int, y2: int) -> dict:
    """side -> pid -> {metric: period index / career index, "balls": balls in the period}."""
    from .data import ratings
    players = ratings(fmt)["players"]
    years = load_years(fmt)
    out = {}
    for side in ("bat", "bowl"):
        career = {pid: p[side]["idx"] for pid, p in players.items() if p.get(side) and p[side].get("idx")}
        idx, _, balls = period_indexes(years.get(side, {}), career, y1, y2, TAU_SCALE[fmt][side])
        out[side] = {pid: {**{m: v / career[pid][m] if career[pid][m] else 1.0 for m, v in d.items()},
                           "balls": balls[pid]} for pid, d in idx.items()}
    return out
