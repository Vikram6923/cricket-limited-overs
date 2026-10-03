"""Ratings for a year range ("India 2007-2011"), without refitting the whole model.

`scripts/build_ratings.py` stores, per player and calendar year, the sufficient statistics of the fit: actual and
expected counts per metric (expected already includes the era baseline and the opponents' indexes). A period
index is the player's actual / expected over the chosen years, shrunk toward his career index by empirical Bayes:
the spread of true period-vs-career differences (tau^2) is estimated from all players active in those years, so
a short or thin period stays close to the career rating and a long, well-measured one can move away from it.

The engine applies the result as a ratio (period / career) to the player's phase indexes, keeping the shape of
his phase record. Wides, no-balls and run-outs stay career-long.

Two modes (the user chose to offer both, "blend" by default):
- "blend": shrink toward the career index (above). Most accurate: it predicts held-out years best.
- "only": rate on those years alone, as if the rest of the career didn't exist: the same empirical-Bayes rating as
  the career fit (prior = role-group mean x team level, tau^2 = the career fit's), but on the period's balls only.
  Closer to what the player actually did then, but noisier: one great series counts for more.
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
    """Ratings on the years y1..y2 (see split_indexes)."""
    return split_indexes(rows, career, lambda k: y1 <= int(k) <= y2, tau_scale)


def split_indexes(rows: dict, career: dict, is_in, tau_scale: float = 1.0) -> tuple[dict, dict, dict]:
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
            if is_in(yr):
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


def only_indexes(rows: dict, prior: dict, tau2: dict, y1: int, y2: int) -> tuple[dict, dict]:
    """Mode "only": rate on the period's balls alone. prior: pid -> {metric: role/team prior}; tau2: metric -> the
    career fit's spread of players around that prior. Returns (pid -> {metric: idx}, pid -> balls)."""
    out, balls = {}, {}
    for pid, by_year in rows.items():
        if pid not in prior:
            continue
        acc = None
        for yr, row in by_year.items():
            if y1 <= int(yr) <= y2:
                acc = list(row) if acc is None else [a + b for a, b in zip(acc, row)]
        if not acc or acc[0] <= 0:
            continue
        d = {}
        for k, m in enumerate(METRICS):
            p, e = prior[pid][m], acc[2 + 2 * k]
            if e <= 0:
                d[m] = p
                continue
            v = _noise(m, acc, k, p)
            d[m] = p + tau2[m] / (tau2[m] + v) * (acc[1 + 2 * k] / e - p)
        out[pid], balls[pid] = d, acc[0]
    return out, balls


MODES = ("blend", "only")


@lru_cache(maxsize=64)
def period_ratios(fmt: str, y1: int, y2: int, mode: str = "blend") -> dict:
    """side -> pid -> {metric: period index / career index, "balls": balls in the period}."""
    from .data import _prior, ratings
    if mode not in MODES:
        raise ValueError(f"unknown period mode {mode!r}")
    r = ratings(fmt)
    players = r["players"]
    years = load_years(fmt)
    out = {}
    for side in ("bat", "bowl"):
        career = {pid: p[side]["idx"] for pid, p in players.items() if p.get(side) and p[side].get("idx")}
        if mode == "only":
            role = "bat_role" if side == "bat" else "bowl_role"
            default = "middle" if side == "bat" else "part_unk"
            prior = {pid: _prior(fmt, side, players[pid].get(role) or default, players[pid].get("team") or "")["middle"]
                     for pid in career}
            tau2 = {m: r["meta"]["tau2"][m][side] for m in METRICS}
            idx, balls = only_indexes(years.get(side, {}), prior, tau2, y1, y2)
        else:
            idx, _, balls = period_indexes(years.get(side, {}), career, y1, y2, TAU_SCALE[fmt][side])
        out[side] = {pid: {**{m: v / career[pid][m] if career[pid][m] else 1.0 for m, v in d.items()},
                           "balls": balls[pid]} for pid, d in idx.items()}
    return out


# ---------------------------------------------------------------- league-specific ratings
# Same estimator on competitions instead of years: a player's record in one league (actual / expected, so already
# adjusted for that league's opposition and conditions), shrunk toward his overall T20 rating. LEAGUE_TAU_SCALE is
# chosen by scripts/validate_leagues.py; None = the data didn't support it, league ratings stay off.
LEAGUE_TAU_SCALE = {"t20": None}


@lru_cache(maxsize=4)
def load_comps(fmt: str) -> dict:
    path = DATA / f"ratings_{fmt}_comps.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"bat": {}, "bowl": {}}


@lru_cache(maxsize=32)
def league_ratios(fmt: str, comp: str) -> dict:
    """side -> pid -> {metric: league index / overall index} for players with a record in that competition."""
    from .data import ratings
    scale = LEAGUE_TAU_SCALE.get(fmt)
    if scale is None:
        return {"bat": {}, "bowl": {}}
    players = ratings(fmt)["players"]
    rows = load_comps(fmt)
    out = {}
    for side in ("bat", "bowl"):
        career = {pid: p[side]["idx"] for pid, p in players.items() if p.get(side) and p[side].get("idx")}
        idx, _, _ = split_indexes(rows.get(side, {}), career, lambda k: k == comp, scale)
        out[side] = {pid: {m: v / career[pid][m] if career[pid][m] else 1.0 for m, v in d.items()}
                     for pid, d in idx.items()}
    return out
