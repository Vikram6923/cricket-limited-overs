"""Pace v spin pitches: how much more (or less) spinners get out of a ground than pace bowlers, and how much that
varies from one day to the next.

    python -m engine.fit.fit_spin        -> data/engine/spin_{t20,odi}.json   (~2 min)

For every real match since 2012 (the same matches as fit_venues), each delivery's expected runs and bowler
wickets come from the ratings (baseline x batter index x bowler index, by phase). Per match and bowling type,
observed / expected gives how spin and pace did against expectation; the match's spin edge is
    d = log(O/E spin) - log(O/E pace)       (for runs and for wickets)
- venue edge: empirical-Bayes mean of d at the ground (shrunk toward 0 by the between-venue variance);
- day's edge: the spread of d around the venue edge beyond sampling noise (a dry turner one day, a green top
  the next).
In the engine (conditions.py) spin deliveries are scaled by exp(d * pace share) and pace deliveries by
exp(-d * spin share), so the match's overall scoring level (the venue factor) is unchanged.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict

from ..conditions import venue_key
from ..data import DATA, baseline, phase_of, player
from .fit_venues import real_matches

MIN_BALLS = {"t20": 24, "odi": 60}


def match_rows(fmt: str) -> list[dict]:
    players: dict = {}

    def get(pid):
        if pid not in players:
            try:
                players[pid] = player(fmt, pid)
            except Exception:
                players[pid] = None
        return players[pid]

    bases: dict = {}
    rows = []
    for comp, yr, name, m in real_matches(fmt):
        if (comp, yr) not in bases:
            try:
                bases[comp, yr] = baseline(fmt, comp, yr)
            except KeyError:
                bases[comp, yr] = None
        base = bases[comp, yr]
        if base is None:
            continue
        reg = m["info"]["registry"]["people"]
        acc = {k: [0.0, 0.0, 0.0, 0.0, 0.0, 0] for k in ("spin", "pace")}   # O runs, E runs, var, O wkt, E wkt, balls
        for inn in m["innings"][:2]:
            for ov in inn["overs"]:
                ph = phase_of(ov["over"], fmt)
                b0 = base[ph]
                for d in ov["deliveries"]:
                    ex = d.get("extras", {})
                    if "wides" in ex or "noballs" in ex:
                        continue
                    bt, bw = get(reg.get(d["batter"])), get(reg.get(d["bowler"]))
                    if not bt or not bw or bw.bowl_type not in ("spin", "pace"):
                        continue
                    a = acc[bw.bowl_type]
                    e_r = b0["runs"] * bt.bat[ph]["runs"] * bw.bowl[ph]["runs"]
                    a[0] += d["runs"]["batter"]
                    a[1] += e_r
                    a[2] += max(b0["runs_sq"] - b0["runs"] ** 2, 0.1)
                    a[3] += sum(1 for w in d.get("wickets", []) if w["kind"] not in ("run out", "retired hurt",
                                                                                   "retired not out", "obstructing the field"))
                    a[4] += b0["wkt"] * bt.bat[ph]["wkt"] * bw.bowl[ph]["wkt"]
                    a[5] += 1
        s, p = acc["spin"], acc["pace"]
        if s[5] < MIN_BALLS[fmt] or p[5] < MIN_BALLS[fmt]:
            continue
        rows.append({
            "venue": venue_key(m["info"].get("venue")), "comp": comp,
            "d_runs": math.log((s[0] + 1) / (s[1] + 1)) - math.log((p[0] + 1) / (p[1] + 1)),
            "n_runs": s[2] / s[1] ** 2 + p[2] / p[1] ** 2,
            "d_wkt": math.log((s[3] + 0.5) / (s[4] + 0.5)) - math.log((p[3] + 0.5) / (p[4] + 0.5)),
            "n_wkt": 1 / (s[4] + 0.5) + 1 / (p[4] + 0.5),
            "spin_share": s[5] / (s[5] + p[5]),
        })
    return rows


def fit_metric(rows: list[dict], k: str) -> tuple[dict, float, float]:
    """(venue -> (edge, matches), between-venue variance tau2, day variance)."""
    by = defaultdict(list)
    for r in rows:
        by[r["venue"]].append(r)
    # day variance: spread around each venue's own mean beyond noise (venues with 5+ matches)
    num = den = 0.0
    for v, rs in by.items():
        if len(rs) >= 5:
            mu = sum(r["d_" + k] for r in rs) / len(rs)
            num += sum((r["d_" + k] - mu) ** 2 - r["n_" + k] * (1 - 1 / len(rs)) for r in rs)
            den += len(rs) - 1
    day = max(num / den, 0.0) if den else 0.0
    # between-venue variance: venue means' spread beyond their sampling variance
    means = [(sum(r["d_" + k] for r in rs) / len(rs), sum(r["n_" + k] + day for r in rs) / len(rs) ** 2)
             for rs in by.values() if len(rs) >= 5]
    grand = sum(m for m, _ in means) / len(means)
    tau2 = max(sum((m - grand) ** 2 - v for m, v in means) / len(means), 1e-6)
    out = {}
    for v, rs in by.items():
        w = [1 / (r["n_" + k] + day) for r in rs]
        mean = sum(wi * r["d_" + k] for wi, r in zip(w, rs)) / sum(w)
        out[v] = (grand + (mean - grand) * tau2 / (tau2 + 1 / sum(w)), len(rs))
    return out, tau2, day, grand


def main() -> None:
    for fmt in ("t20", "odi"):
        rows = match_rows(fmt)
        res = {k: fit_metric(rows, k) for k in ("runs", "wkt")}
        venues = {}
        for v in res["runs"][0]:
            (er, n), (ew, _) = res["runs"][0][v], res["wkt"][0][v]
            venues[v] = {"runs": round(er, 4), "wkt": round(ew, 4), "n": n}
        share = sum(r["spin_share"] for r in rows) / len(rows)
        out = {"venues": venues, "spin_share": round(share, 3),
               "day": {"sd_runs": round(math.sqrt(res["runs"][2]), 4), "sd_wkt": round(math.sqrt(res["wkt"][2]), 4)},
               "between_venue_sd": {"runs": round(math.sqrt(res["runs"][1]), 4), "wkt": round(math.sqrt(res["wkt"][1]), 4)},
               "overall": {"runs": round(res["runs"][3], 4), "wkt": round(res["wkt"][3], 4)},
               "matches": len(rows)}
        (DATA / "engine" / f"spin_{fmt}.json").write_text(json.dumps(out), encoding="utf-8")
        top = sorted(((v["wkt"], k, v["n"]) for k, v in venues.items() if v["n"] >= 15), reverse=True)
        print(fmt, f"{len(rows)} matches; spin share {share:.2f}; between-venue sd {out['between_venue_sd']}; "
              f"day sd {out['day']}; overall {out['overall']}")
        print("   most spin-friendly (wickets):", [(k, round(w, 2), n) for w, k, n in top[:6]])
        print("   most pace-friendly (wickets):", [(k, round(w, 2), n) for w, k, n in top[-6:]])


if __name__ == "__main__":
    main()
