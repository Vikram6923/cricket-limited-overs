"""Batting depth still to come (does a side with good batters in the shed bat more freely?).

    python -m engine.fit.fit_depth        -> data/engine/depth_t20.json (ODI is fitted and printed, not used)

For every legal ball since 2012 (as fit_situation.py), the engine's expectation is
    baseline x batter index x bowler index x situation multipliers (settling in, state, chase pressure)
and the table holds observed / expected by how much batting the side still has to come, against what sides
usually have at that number of wickets down:
    depth   = sum over the XI players yet to bat (not the two at the crease) of their batting average index
              (runs index / dismissal index, middle overs; 1 = an average batter, a tailender ~0.3-0.5)
    excess  = depth - the average depth of real sides at that many wickets down (same format)
Cells: innings (1 = setting a total, 2 = chasing) x wickets lost (0-2, 3-4, 5-6, 7+) x excess bucket; shrunk
toward 1 with SHRINK pseudo-balls. A cell above 1 for runs and dismissals means sides with more batting to
come score faster and take more risk; the engine applies it as one more multiplier (situation.depth_mult).
"""
from __future__ import annotations

import bisect
import json
from collections import defaultdict

from engine.fit.fit_situation import CFG, OUT, ROOT, bucket, iter_matches, load_ratings, phase_of
from engine.situation import Situation

METRICS = ("runs", "wkt", "dot", "four", "six")
WGROUPS = [2, 4, 6]                       # wickets lost upper bounds: 0-2, 3-4, 5-6, 7+
EXCESS_EDGES = [-1.5, -0.75, -0.25, 0.25, 0.75, 1.5]
SHRINK = 2000
USE = ("t20",)                            # ODI cells showed no consistent pattern (noise): not written
TAIL = 0.4                                # unrated player's batting average index


def quality(R: dict) -> dict:
    out = {}
    for pid, p in R["players"].items():
        b = (p.get("bat") or {}).get("phase", {}).get("middle")
        if b and b.get("wkt"):
            out[pid] = min(3.0, b["runs"] / b["wkt"])
    return out


def fit(fmt: str) -> dict:
    cfg = CFG[fmt]
    N = cfg["overs"] * 6
    base, bat, bowl, _ = load_ratings(fmt)
    R = json.loads((ROOT / "data" / f"ratings_{fmt}.json").read_text(encoding="utf-8"))
    q = quality(R)
    sits = {}
    cells = defaultdict(lambda: [[0.0] * len(METRICS), [0.0] * len(METRICS), 0])   # (inn, wk, round(D,1))
    for comp, full, yr, m in iter_matches(cfg):
        if "method" in m["info"].get("outcome", {}):
            continue
        brow = (base.get(comp) or {}).get(str(yr))
        if not brow:
            continue
        sc = f"{comp}_full" if full else comp
        sit = sits.get((sc, yr)) or sits.setdefault((sc, yr), Situation(fmt, sc, yr))
        reg = m["info"]["registry"]["people"]
        xis = {t: [reg.get(n) for n in ps] for t, ps in m["info"].get("players", {}).items()}
        inns = [i for i in m.get("innings", []) if not i.get("super_over")]
        target = None
        for k, inn in enumerate(inns[:2]):
            if k == 1:
                t = inn.get("target") or {}
                if t.get("overs", cfg["overs"]) != cfg["overs"] or not t.get("runs"):
                    break
                target = t["runs"]
            xi = [p for p in xis.get(inn["team"], []) if p]
            if len(xi) != 11:
                break
            batted = set()
            faced = defaultdict(int)
            runs = wk = legal = 0
            prev_nb = False
            for ov in inn["overs"]:
                ph = phase_of(ov["over"], cfg)
                bp = brow.get(ph)
                for d in ov["deliveries"]:
                    bid, nid, wid = reg.get(d["batter"]), reg.get(d["non_striker"]), reg.get(d["bowler"])
                    batted.update((bid, nid))
                    ex = d.get("extras", {})
                    wide, nb = "wides" in ex, "noballs" in ex
                    if not wide and not nb and not prev_nb and bp and bid in bat and wid in bowl:
                        depth = sum(q.get(p, TAIL) for p in xi if p not in batted)
                        mult = sit.multipliers(k + 1, legal, wk, runs, target, faced[bid])
                        bi, wi = bat[bid][ph], bowl[wid][ph]
                        br = d["runs"]["batter"]
                        wk_b = any(w["kind"] in ("bowled", "caught", "caught and bowled", "lbw", "stumped",
                                                 "hit wicket") for w in d.get("wickets", []))
                        act = (br, wk_b, br == 0, br == 4 and not d["runs"].get("non_boundary"), br == 6)
                        cell = cells[(k + 1, min(wk, 9), round(depth, 1))]
                        for j, mt in enumerate(METRICS):
                            cell[0][j] += act[j]
                            cell[1][j] += bp[mt] * bi[mt] * wi[mt] * mult.get(mt, 1.0)
                        cell[2] += 1
                    if not wide:
                        faced[bid] += 1
                    prev_nb = nb
                    if not wide and not nb:
                        legal += 1
                    runs += d["runs"]["total"]
                    for w in d.get("wickets", []):
                        if w["kind"] not in ("retired hurt", "retired not out"):
                            wk += 1
    # average depth at each number of wickets down (both innings)
    mean_d = {}
    for w in range(10):
        n = sum(c[2] for (i, wk, d), c in cells.items() if wk == w)
        mean_d[w] = sum(c[2] * d for (i, wk, d), c in cells.items() if wk == w) / n if n else 0.0
    agg = defaultdict(lambda: [[0.0] * len(METRICS), [0.0] * len(METRICS), 0])
    for (i, w, d), (a, e, n) in cells.items():
        key = (i, bisect.bisect_left(WGROUPS, w), bucket(d - mean_d[w], EXCESS_EDGES))
        g = agg[key]
        for j in range(len(METRICS)):
            g[0][j] += a[j]
            g[1][j] += e[j]
        g[2] += n
    table = {}
    for (i, g, x), (a, e, n) in sorted(agg.items()):
        row = {}
        for j, mt in enumerate(METRICS):
            k = SHRINK * e[j] / n if n else 0.0
            row[mt] = round((a[j] + k) / (e[j] + k), 4) if e[j] + k else 1.0
        row["balls"] = n
        table.setdefault(str(i), {}).setdefault(str(g), {})[str(x)] = row
    # mean-preserving per (innings, wicket group): weighted by real balls the table averages 1
    for i, gs in table.items():
        for g, xs in gs.items():
            tot = sum(r["balls"] for r in xs.values())
            for mt in METRICS:
                avg = sum(r[mt] * r["balls"] for r in xs.values()) / tot
                for r in xs.values():
                    r[mt] = round(r[mt] / avg, 4)
    return {"metrics": list(METRICS), "wgroups": WGROUPS, "excess_edges": EXCESS_EDGES, "tail": TAIL,
            "mean_depth": {str(w): round(v, 3) for w, v in mean_d.items()}, "table": table}


def main() -> None:
    for fmt in ("t20", "odi"):
        out = fit(fmt)
        if fmt in USE:
            (OUT / f"depth_{fmt}.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
        print(fmt, "mean depth by wickets:", out["mean_depth"])
        for i, gs in out["table"].items():
            for g, xs in gs.items():
                print(f"  inns {i} wkts-group {g}: " + "  ".join(
                    f"[{x}] runs {r['runs']:.3f} wkt {r['wkt']:.3f} six {r['six']:.3f} ({r['balls']})"
                    for x, r in xs.items()))


if __name__ == "__main__":
    main()
