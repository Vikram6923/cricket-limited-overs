"""DLS resources for rain-reduced matches (engine/rain.py).

    python -m engine.fit.fit_dls        -> data/engine/dls_{t20,odi}.json   (~4 min)

The Duckworth-Lewis form: runs still to come with u overs left and w wickets lost
    Z(u, w) = Z0 x F(w) x (1 - exp(-b x u / F(w)))        F(0) = 1
and resources R(u, w) = Z(u, w) / Z(full overs, 0). Two parts, fitted from different data:
- b (how resources fall with overs, wickets in hand): from fresh shortened innings, which is what a DLS target
  is about (a chase given 10 overs starts with 10 overs and all its wickets). Fitted on the engine's own
  first innings in matches of 5..full overs, replaying the calibration fixtures, so targets are fair in the
  simulator. Fitted on real in-progress states instead (0 down after 25 overs of an ODI), R over-rated short
  innings: the sides that reach those states were having good days, so a 25-over chase of an ODI target won 28%.
- F(w) (the cost of wickets lost) and Z0: by weighted least squares, with b fixed, on the runs still to come at
  every over of every complete real first innings (all out or the full overs), as a share of that
  competition-year's average total.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict

from ..calibrate import SUITES, fixtures, seed_for
from ..data import DATA, FORMATS
from .fit_rain import LEAGUE_HOME, RAW, first_innings_states, matches

GRID = {"t20": [5, 8, 10, 12, 15, 20], "odi": [20, 25, 30, 35, 40, 50]}
SIM_SUITES = {"t20": ["t20i", "ipl"], "odi": ["odi"]}


def engine_shares(fmt: str) -> dict:
    """Mean first-innings total in u-over matches / in full matches, by u (engine replays of real fixtures)."""
    from ..match import simulate_match
    tot = defaultdict(lambda: [0.0, 0])
    for name in SIM_SUITES[fmt]:
        s = SUITES[name]
        fx = fixtures(s)
        per = {}
        for u in GRID[fmt]:
            runs = [simulate_match(f["a"], f["b"], fmt=fmt, comp=s["comp"], year=f["year"], seed=seed_for(f["id"], 0),
                                   toss=f["toss"], decision=f["decision"], venue=f["venue"], overs=u)
                    ["innings"][0]["runs"] for f in fx]
            per[u] = sum(runs) / len(runs)
        for u, v in per.items():
            t = tot[u]
            t[0] += len(fx) * v / per[FORMATS[fmt]["overs"]]
            t[1] += len(fx)
    return {u: s / n for u, (s, n) in tot.items()}


def fit_b(shares: dict, n_overs: int) -> float:
    """b such that (1 - exp(-b u)) / (1 - exp(-b N)) fits the shares (least squares, golden section)."""
    def loss(b):
        return sum((y - (1 - math.exp(-b * u)) / (1 - math.exp(-b * n_overs))) ** 2 for u, y in shares.items())
    a, c = 1e-4, 1.0
    g = (math.sqrt(5) - 1) / 2
    for _ in range(80):
        x1, x2 = c - g * (c - a), a + g * (c - a)
        if loss(x1) < loss(x2):
            c = x2
        else:
            a = x1
    return (a + c) / 2


def fit_wickets(rows: list, b: float) -> tuple[float, list]:
    """Z0 and F(1..9) with b fixed, by weighted least squares on cell means of the real states."""
    groups = defaultdict(list)
    for g, total, _ in rows:
        groups[g].append(total)
    mean = {g: sum(v) / len(v) for g, v in groups.items()}
    cell = defaultdict(lambda: [0.0, 0])
    for g, _, states in rows:
        for u, w, rest in states:
            c = cell[(u, w)]
            c[0] += rest / mean[g]
            c[1] += 1
    cells = [(u, w, s / n, n) for (u, w), (s, n) in cell.items()]

    def z(p, u, w):
        f = p[w] if w else 1.0
        return p[0] * f * (1 - math.exp(-b * u / f))

    def loss(p):
        return sum(n * (y - z(p, u, w)) ** 2 for u, w, y, n in cells)

    p = [2.0] + [max(0.05, 1 - 0.1 * w) for w in range(1, 10)]     # Z0, F(1..9)
    g = (math.sqrt(5) - 1) / 2
    for _ in range(40):                          # coordinate search, each parameter by golden section
        for k in range(len(p)):
            a, c = (0.1, 50.0) if k == 0 else (0.005, p[k - 1] if k > 1 else 1.0)
            for _ in range(40):
                x1, x2 = c - g * (c - a), a + g * (c - a)
                if loss(p[:k] + [x1] + p[k + 1:]) < loss(p[:k] + [x2] + p[k + 1:]):
                    c = x2
                else:
                    a = x1
            p[k] = (a + c) / 2
    return p[0], [1.0] + p[1:]


def real_rows(fmt: str) -> list:
    sched = FORMATS[fmt]["overs"]
    zips = ([(RAW / "odis_male_json.zip", None)] if fmt == "odi" else
            [(RAW / "t20s_male_json.zip", None)] + [(RAW / "leagues" / f"{k}_json.zip", k) for k in LEAGUE_HOME])
    rows = []
    for z, league in zips:
        if not z.exists():
            continue
        for m in matches(z):
            i = m["info"]
            if i.get("overs", sched) != sched:
                continue
            st = first_innings_states(m, sched)
            if st:
                rows.append(((league or "intl", int(i["dates"][0][:4])), *st))
    return rows


def main() -> None:
    for fmt in ("t20", "odi"):
        n_overs = FORMATS[fmt]["overs"]
        shares = engine_shares(fmt)
        b = fit_b(shares, n_overs)
        z0, F = fit_wickets(real_rows(fmt), b)
        res = {"b": round(b, 6), "Z0": round(z0, 5), "F": [round(x, 5) for x in F], "overs": n_overs,
               "engine_shares": {str(u): round(v, 4) for u, v in sorted(shares.items())}}
        (DATA / "engine" / f"dls_{fmt}.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
        print(fmt, res)


if __name__ == "__main__":
    main()
