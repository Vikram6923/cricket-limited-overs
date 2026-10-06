"""Reactive bowling changes: how a bowler's figures so far change how much more he bowls.

    python -m engine.fit.fit_reactive        -> data/engine/reactive_{t20,odi}.json   (~2 min)

Real matches since 2015 (full-member internationals and the IPL for T20; full-member ODIs). At the end of every
over, for every bowler who has bowled and still has overs left:
- outcome: overs he bowls in the rest of the innings;
- compared with bowlers in the same place (overs he has bowled k, overs gone o) and adjusted for how much he
  usually bowls (overs per match);
- explained by his figures so far against expectation: runs conceded - expected and wickets - expected (expected
  from the ratings: baseline x batter index x bowler index for every ball he bowled).
Least squares gives overs gained per run conceded above expectation (negative: an expensive bowler is taken off)
and per wicket above expectation (positive: a wicket-taker is kept on). The engine moves overs between bowlers
by these amounts; the captain's plan (real usage) stays the starting point.
"""
from __future__ import annotations

import json
import zipfile
from collections import defaultdict

from ..data import DATA, FORMATS, baseline, phase_of, player
from .fit_venues import FULL, RAW

SOURCES = {"t20": [("t20i_full", "t20s_male_json.zip"), ("ipl", "leagues/ipl_json.zip")],
           "odi": [("odi_full", "odis_male_json.zip")]}
FIRST = 2015
# The engine applies these effects at the moments the plan picks a bowler, and a bowler taken off can come back
# through the captain's fallback choice, so it under-reacts at face value. GAIN scales the effects so simulated
# captains react as strongly as real ones: fitted by refitting this regression on replays of the real fixtures
# (T20: -0.018 runs slope v real -0.019 at 3.0; ODI: -0.030 v -0.031 at 4.0; docs/engine_progress.md).
GAIN = {"t20": 3.0, "odi": 4.0}


def rows_for(fmt: str) -> list[tuple]:
    overs_max, quota = FORMATS[fmt]["overs"], FORMATS[fmt]["quota"]
    players: dict = {}

    def get(pid):
        if pid not in players:
            try:
                players[pid] = player(fmt, pid)
            except Exception:
                players[pid] = None
        return players[pid]

    bases: dict = {}
    out = []
    for comp, z in SOURCES[fmt]:
        with zipfile.ZipFile(RAW / z) as zf:
            for n in zf.namelist():
                if not n.endswith(".json"):
                    continue
                m = json.loads(zf.read(n))
                info = m["info"]
                yr = int(info["dates"][0][:4])
                if yr < FIRST or info.get("gender") != "male" or info.get("overs") != overs_max:
                    continue
                if comp.endswith("_full") and not all(t in FULL for t in info["teams"]):
                    continue
                if (comp, yr) not in bases:
                    bases[comp, yr] = baseline(fmt, comp, yr)
                base, reg = bases[comp, yr], info["registry"]["people"]
                for inn in m["innings"][:2]:
                    if inn.get("super_over"):
                        continue
                    overs = inn["overs"]
                    who = []                      # bowler of each over
                    fig = defaultdict(lambda: [0, 0.0, 0, 0.0])   # runs, exp runs, wkts, exp wkts
                    for ov in overs:
                        ph = phase_of(ov["over"], fmt)
                        b0 = base[ph]
                        bname = ov["deliveries"][0]["bowler"]
                        who.append(bname)
                        f = fig[bname]
                        bw = get(reg.get(bname))
                        for d in ov["deliveries"]:
                            f[0] += d["runs"]["batter"] + d.get("extras", {}).get("wides", 0) + d.get("extras", {}).get("noballs", 0)
                            f[2] += sum(1 for w in d.get("wickets", []) if w["kind"] not in
                                        ("run out", "retired hurt", "retired not out", "obstructing the field"))
                            if "wides" in d.get("extras", {}) or "noballs" in d.get("extras", {}):
                                continue
                            bt = get(reg.get(d["batter"]))
                            ib = bt.bat[ph] if bt else {"runs": 1.0, "wkt": 1.0}
                            iw = bw.bowl[ph] if bw else {"runs": 1.0, "wkt": 1.0}
                            f[1] += b0["runs"] * ib["runs"] * iw["runs"] + b0["wide"] + b0["noball"]
                            f[3] += b0["wkt"] * ib["wkt"] * iw["wkt"]
                        # state after this over, for every bowler who has bowled and has overs left
                        o = len(who)
                        if o >= overs_max - 1 or len(overs) < overs_max:   # innings cut short: skip (noisy)
                            continue
                        done = {b: who.count(b) for b in set(who)}
                        snap = {b: list(fig[b]) for b in done}
                        for b, k in done.items():
                            if k >= quota:
                                continue
                            p = get(reg.get(b))
                            opm = p.bowl_overs_per_match if p else 0.0
                            rest = sum(1 for x in [ov2["deliveries"][0]["bowler"] for ov2 in overs[o:]] if x == b)
                            r, er, w, ew = snap[b]
                            out.append((k, o, opm, rest, r - er, w - ew))
    return out


def fit(rows: list[tuple]) -> dict:
    """Least squares of remaining overs on [usual overs, runs excess, wickets excess] within (k, o) cells."""
    cell = defaultdict(list)
    for r in rows:
        cell[(r[0], r[1])].append(r)
    X, Y = [], []
    for rs in cell.values():
        if len(rs) < 20:
            continue
        m = [sum(r[i] for r in rs) / len(rs) for i in (2, 3, 4, 5)]
        for r in rs:
            X.append((r[2] - m[0], r[4] - m[2], r[5] - m[3]))
            Y.append(r[3] - m[1])
    # normal equations (3x3)
    A = [[sum(x[i] * x[j] for x in X) for j in range(3)] for i in range(3)]
    b = [sum(x[i] * y for x, y in zip(X, Y)) for i in range(3)]
    n = len(A)
    M = [A[i] + [b[i]] for i in range(n)]
    for i in range(n):
        piv = max(range(i, n), key=lambda r: abs(M[r][i]))
        M[i], M[piv] = M[piv], M[i]
        for r in range(n):
            if r != i:
                f = M[r][i] / M[i][i]
                M[r] = [a - f * c for a, c in zip(M[r], M[i])]
    coef = [M[i][n] / M[i][i] for i in range(n)]
    resid = [y - sum(c * xi for c, xi in zip(coef, x)) for x, y in zip(X, Y)]
    s2 = sum(e * e for e in resid) / max(len(resid) - 3, 1)
    # standard errors from the diagonal of A^-1 (A is small; invert by solving)
    inv = []
    for j in range(n):
        M = [A[i] + [1.0 if i == j else 0.0] for i in range(n)]
        for i in range(n):
            piv = max(range(i, n), key=lambda r: abs(M[r][i]))
            M[i], M[piv] = M[piv], M[i]
            for r in range(n):
                if r != i:
                    f = M[r][i] / M[i][i]
                    M[r] = [a - f * c for a, c in zip(M[r], M[i])]
        inv.append(M[j][n] / M[j][j])
    se = [(s2 * v) ** 0.5 for v in inv]
    return {"per_usual_over": round(coef[0], 4), "per_run": round(coef[1], 5), "per_wicket": round(coef[2], 4),
            "se": [round(x, 5) for x in se], "samples": len(Y)}


def main() -> None:
    for fmt in ("t20", "odi"):
        res = {**fit(rows_for(fmt)), "gain": GAIN[fmt]}
        (DATA / "engine" / f"reactive_{fmt}.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
        print(fmt, res)


if __name__ == "__main__":
    main()
