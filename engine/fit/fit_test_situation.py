"""Fit the Test situation tables (docs/test_match_plan.md sections 2-3; cells from docs/test_design.md).

For every legal ball of every Cricsheet Test the ratings predict
    rate_m = baseline["test"][year]["all"][m] x batter index x bowler index
and each table holds observed / predicted for the balls of its cell. Four tables are fitted jointly by
backfitting, so what they share is not counted twice:
    settle[balls the striker has faced]                    edges 0, 10, 30, 60, 120, 200; includes dismissal
    wear[pace | spin][overs bowled in the match so far]    edges 0, 90, 180, 270, 360
    age[pace | spin][overs since the innings began % 80]   edges 0, 10, 20, 40, 60
    state[innings 1-3][wickets down][lead of the batting side at that ball]
    fourth[wickets down][runs needed per over left]        the last innings: chase, steady or save
A thin state cell is shrunk toward its innings x wickets parent, the parent toward 1.

Cricsheet has no clock. "Overs left" is: in a drawn match, the overs that really were still bowled (exact);
otherwise the larger of that and 450 minus the overs bowled so far (which forgets overs lost to weather).
A new ball is assumed at every 80th over of an innings (its taking is not recorded).

Writes data/engine/test_situation.json.   Run:  python -m engine.fit.fit_test_situation
"""
from __future__ import annotations

import bisect
import json
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

from .fit_basics import bowl_types

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "engine"
METRICS = ("runs", "wkt", "dot", "four", "six")
NM = len(METRICS)
BOWLER_WICKETS = {"bowled", "caught", "caught and bowled", "lbw", "stumped", "hit wicket"}
NOT_OUT = {"retired hurt", "retired not out"}
SCHEDULED = 450                                   # 5 days x 90 overs

SETTLE_EDGES = [10, 30, 60, 120, 200]             # bucket i = edges[i-1] <= x < edges[i]
WEAR_EDGES = [90, 180, 270, 360]
AGE_EDGES = [10, 20, 40, 60]
WKT_EDGES = [3, 6]                                # 0-2, 3-5, 6-9 down
LEAD_EDGES = [-200, -100, 0, 100, 200, 350]
RR_EDGES = [1.5, 2.5, 3.5, 5.0, 8.0]              # runs needed per over left, last innings
SHRINK_BALLS = 400                                # pseudo-balls at the prior value


def bucket(x: float, edges: list) -> int:
    return bisect.bisect_right(edges, x)


def iter_tests():
    """Every men's Test with six-ball overs, in file order."""
    path = RAW / "tests_male_json.zip"
    if not path.exists():
        raise SystemExit("data/raw/tests_male_json.zip is missing; run scripts/fetch_cricsheet.py")
    with zipfile.ZipFile(path) as z:
        for name in sorted(z.namelist()):
            if not name.endswith(".json"):
                continue
            m = json.loads(z.read(name))
            info = m["info"]
            if info.get("gender") != "male" or info.get("balls_per_over", 6) != 6:
                continue
            yield m


def load_ratings():
    R = json.loads((ROOT / "data" / "ratings_test.json").read_text(encoding="utf-8"))
    bat, bowl, rec = {}, {}, R["players"]
    for pid, p in rec.items():
        if p.get("bat"):
            bat[pid] = p["bat"]["phase"]["all"]
        if p.get("bowl"):
            bowl[pid] = p["bowl"]["phase"]["all"]
    return R["baselines"]["test"], bat, bowl, rec


def is_draw(m: dict) -> bool:
    return m["info"].get("outcome", {}).get("result") == "draw"


def match_overs(m: dict) -> int:
    return sum(len(i.get("overs", [])) for i in m.get("innings", []))


def overs_left(gone: int, total: int, draw: bool) -> int:
    """Overs left in the match after `gone` overs (see the module text)."""
    rem = total - gone
    return max(1, rem if draw else max(SCHEDULED - gone, rem))


def outs(d: dict) -> int:
    return sum(1 for w in d.get("wickets", []) if w["kind"] not in NOT_OUT)


def fit() -> dict:
    base, bat, bowl, _ = load_ratings()
    btype = bowl_types("test")
    J = defaultdict(lambda: [0.0] * (1 + 2 * NM))     # joint cell -> balls, actual x NM, expected x NM
    n_matches = 0
    for m in iter_tests():
        info = m["info"]
        brow = (base.get(info["dates"][0][:4]) or {}).get("all")
        if not brow:
            continue
        n_matches += 1
        reg = info["registry"]["people"]
        total, draw = match_overs(m), is_draw(m)
        gone = 0
        team_runs = defaultdict(int)
        for k, inn in enumerate(m.get("innings", [])[:4]):
            team = inn["team"]
            other = [t for t in info["teams"] if t != team][0]
            lead0 = team_runs[team] - team_runs[other]
            runs = wk = 0
            faced = defaultdict(int)
            for ov in inn.get("overs", []):
                a_b, w_b = bucket(ov["over"] % 80, AGE_EDGES), bucket(gone, WEAR_EDGES)
                left = overs_left(gone, total, draw)
                for d in ov["deliveries"]:
                    ex = d.get("extras", {})
                    wide, nb = "wides" in ex, "noballs" in ex
                    bid, wid = reg.get(d["batter"]), reg.get(d["bowler"])
                    if not wide and not nb and bid in bat and wid in bowl:
                        wb = bucket(wk, WKT_EDGES)
                        if k < 3:
                            st = (k + 1, wb, bucket(lead0 + runs, LEAD_EDGES))
                        else:
                            st = (4, wb, bucket((-lead0 + 1 - runs) / left, RR_EDGES))
                        t = btype.get(wid, "unknown")
                        ty = t if t in ("pace", "spin") else None
                        c = J[(bucket(faced[bid], SETTLE_EDGES), st, (ty, w_b) if ty else None,
                               (ty, a_b) if ty else None)]
                        bi, wi = bat[bid], bowl[wid]
                        br = d["runs"]["batter"]
                        c[0] += 1
                        c[1] += br
                        c[2] += any(w["kind"] in BOWLER_WICKETS for w in d.get("wickets", []))
                        c[3] += br == 0
                        c[4] += br == 4 and not d["runs"].get("non_boundary")
                        c[5] += br == 6
                        for j, mt in enumerate(METRICS):
                            c[6 + j] += brow[mt] * bi[mt] * wi[mt]
                    if not wide:
                        faced[bid] += 1
                    runs += d["runs"]["total"]
                    wk += outs(d)
                gone += 1
            team_runs[team] += runs

    # ------------------------------------------------------------- backfitting
    keys = list(J)
    ones = [1.0] * NM
    tabs = [dict() for _ in range(4)]                 # settle, state, wear, age: cell -> multipliers
    for key in keys:
        for i in range(4):
            if key[i] is not None:
                tabs[i][key[i]] = list(ones)

    def val(i, cell):
        return tabs[i][cell] if cell is not None else ones

    def sums(i):
        """Per cell of table i: balls, actual, expected under the other three tables."""
        acc = defaultdict(lambda: [0.0] * (1 + 2 * NM))
        for key in keys:
            if key[i] is None:
                continue
            c, a = J[key], acc[key[i]]
            others = [val(q, key[q]) for q in range(4) if q != i]
            a[0] += c[0]
            for j in range(NM):
                a[1 + j] += c[1 + j]
                a[1 + NM + j] += c[1 + NM + j] * others[0][j] * others[1][j] * others[2][j]
        return acc

    def shrunk(a, prior):
        out = []
        for j in range(NM):
            e = a[1 + NM + j]
            k = SHRINK_BALLS * (e / a[0]) if a[0] else 0.0
            out.append((a[1 + j] + k * prior[j]) / (e + k) if e + k > 0 else prior[j])
        return out

    for _ in range(15):
        for i in (0, 2, 3):
            acc = sums(i)
            for cell, a in acc.items():
                tabs[i][cell] = shrunk(a, ones)
            # settle, wear and age stay mean-preserving; the state table carries the level
            for j in range(NM):
                num = sum(tabs[i][c][j] * a[1 + NM + j] for c, a in acc.items())
                den = sum(a[1 + NM + j] for a in acc.values())
                f = num / den if den else 1.0
                for c in acc:
                    tabs[i][c][j] /= f
        acc = sums(1)
        par = defaultdict(lambda: [0.0] * (1 + 2 * NM))
        for cell, a in acc.items():
            p = par[cell[:2]]
            for j in range(1 + 2 * NM):
                p[j] += a[j]
        parent = {pk: shrunk(a, ones) for pk, a in par.items()}
        for cell, a in acc.items():
            tabs[1][cell] = shrunk(a, parent[cell[:2]])
    # final rescale: over all real balls, ratings x tables give back the actual totals
    for j in range(NM):
        act = sum(J[k][1 + j] for k in keys)
        exp = sum(J[k][1 + NM + j] * val(0, k[0])[j] * val(1, k[1])[j] * val(2, k[2])[j] * val(3, k[3])[j]
                  for k in keys)
        g = act / exp if exp else 1.0
        for c in tabs[1]:
            tabs[1][c][j] *= g
        for pk in parent:
            parent[pk][j] *= g

    balls = [defaultdict(float) for _ in range(4)]
    for key in keys:
        for i in range(4):
            if key[i] is not None:
                balls[i][key[i]] += J[key][0]

    def r(v):
        return [round(x, 4) for x in v]

    nw, nl, nr = len(WKT_EDGES) + 1, len(LEAD_EDGES) + 1, len(RR_EDGES) + 1
    out = {
        "format": "test", "matches": n_matches, "metrics": list(METRICS),
        "balls": int(sum(J[k][0] for k in keys)), "shrink_balls": SHRINK_BALLS,
        "settle_edges": SETTLE_EDGES, "wear_edges": WEAR_EDGES, "age_edges": AGE_EDGES,
        "wkt_edges": WKT_EDGES, "lead_edges": LEAD_EDGES, "rr_edges": RR_EDGES,
        "settle": [r(tabs[0][s]) for s in range(len(SETTLE_EDGES) + 1)],
        "settle_n": [int(balls[0][s]) for s in range(len(SETTLE_EDGES) + 1)],
        "wear": {t: [r(tabs[2].get((t, b), ones)) for b in range(len(WEAR_EDGES) + 1)] for t in ("pace", "spin")},
        "wear_n": {t: [int(balls[2][(t, b)]) for b in range(len(WEAR_EDGES) + 1)] for t in ("pace", "spin")},
        "age": {t: [r(tabs[3].get((t, b), ones)) for b in range(len(AGE_EDGES) + 1)] for t in ("pace", "spin")},
        "age_n": {t: [int(balls[3][(t, b)]) for b in range(len(AGE_EDGES) + 1)] for t in ("pace", "spin")},
        # a cell no real ball fell in (innings 1 behind, say) plays as its innings x wickets parent
        "state": {str(i): [[r(tabs[1].get((i, w, ld), parent.get((i, w), ones))) for ld in range(nl)]
                           for w in range(nw)] for i in (1, 2, 3)},
        "state_n": {str(i): [[int(balls[1][(i, w, ld)]) for ld in range(nl)] for w in range(nw)]
                    for i in (1, 2, 3)},
        "fourth": [[r(tabs[1].get((4, w, q), parent.get((4, w), ones))) for q in range(nr)] for w in range(nw)],
        "fourth_n": [[int(balls[1][(4, w, q)]) for q in range(nr)] for w in range(nw)],
    }
    return out


def show(t: dict) -> None:
    def row(label, v, n):
        print(f"  {label:22} {n:9d}  " + "  ".join(f"{m} {x:5.3f}" for m, x in zip(t["metrics"], v)))

    def lab(edges, i, unit=""):
        lo = edges[i - 1] if i else None
        hi = edges[i] if i < len(edges) else None
        return (f"under {hi}" if lo is None else f"{lo}+" if hi is None else f"{lo} to {hi}") + unit
    print(f"{t['matches']} Tests, {t['balls']} balls")
    print("settling in (balls faced):")
    for i, v in enumerate(t["settle"]):
        row(lab(t["settle_edges"], i), v, t["settle_n"][i])
    for name, edges in (("wear", t["wear_edges"]), ("age", t["age_edges"])):
        for ty in ("pace", "spin"):
            print(f"{name}, {ty} (overs):")
            for i, v in enumerate(t[name][ty]):
                row(lab(edges, i), v, t[name + "_n"][ty][i])
    wl = ("0-2 down", "3-5 down", "6-9 down")
    for inn in ("1", "2", "3"):
        print(f"innings {inn} (wickets down, lead):")
        for w in range(3):
            for ld, v in enumerate(t["state"][inn][w]):
                if t["state_n"][inn][w][ld]:
                    row(f"{wl[w]}, {lab(t['lead_edges'], ld)}", v, t["state_n"][inn][w][ld])
    print("innings 4 (wickets down, runs needed per over left):")
    for w in range(3):
        for q, v in enumerate(t["fourth"][w]):
            row(f"{wl[w]}, {lab(t['rr_edges'], q)}", v, t["fourth_n"][w][q])


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    t = fit()
    (OUT / "test_situation.json").write_text(json.dumps(t, indent=1), encoding="utf-8")
    show(t)
    return 0


if __name__ == "__main__":
    sys.exit(main())
