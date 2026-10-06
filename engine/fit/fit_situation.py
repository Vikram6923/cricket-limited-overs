"""Fit the situational multiplier tables (design T1-1 resources/par, T1-2 intent, T1-3 settling in).

Method (design section 4): for every legal ball in Cricsheet, the ratings predict
    rate_m = baseline[comp][year][phase][m] x batter index x bowler index
and each situation table holds observed / predicted for the balls in its cell, shrunk toward 1 (or toward its parent
cell) when the cell is thin. Two tables are fitted jointly by backfitting so their overlap isn't double-counted:
    settle[balls already faced by the striker]                      (settling in)
    state1[balls left][wickets lost]                                 (1st innings: setting a total)
    state2[balls left][wickets lost][pressure]                       (2nd innings: chasing)
pressure = runs still needed / par runs still to come for an average side in that state, where
    par = par_frac[balls left][wickets lost] x scale[competition][year]
is learned from complete first innings (the resources table, DLS-style).

Writes data/engine/situation_{t20,odi}.json.   Run:  python -m engine.fit.fit_situation
"""
from __future__ import annotations

import bisect
import json
import math
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "engine"
FULL = {"Afghanistan", "Australia", "Bangladesh", "England", "India", "Ireland", "New Zealand", "Pakistan",
        "South Africa", "Sri Lanka", "West Indies", "Zimbabwe", "ICC World XI", "Asia XI", "Africa XI"}
METRICS = ("runs", "wkt", "dot", "four", "six", "run_out")
FIRST_YEAR = 2012

CFG = {
    "t20": {"overs": 20, "sources": [("t20i", "t20s_male_json.zip")] +
            [(c, f"leagues/{c}_json.zip") for c in ("ipl", "bbl", "psl", "cpl", "sat", "ilt", "bpl", "lpl", "mlc",
                                                     "ntb", "ssm")],
            "phases": ((0, 5, "powerplay"), (6, 14, "middle"), (15, 19, "death")),
            "balls_left_edges": [6, 12, 24, 36, 60, 84]},          # bucket upper bounds (inclusive)
    "odi": {"overs": 50, "sources": [("odi", "odis_male_json.zip")],
            "phases": ((0, 9, "powerplay"), (10, 39, "middle"), (40, 49, "death")),
            "balls_left_edges": [12, 30, 60, 90, 150, 210]},
}
SETTLE_EDGES = [0, 1, 2, 3, 5, 8, 12, 17, 24, 34, 49]   # balls already faced (inclusive upper bounds)
WKT_EDGES = [0, 1, 2, 3, 4, 5, 6]                       # wickets lost; 7+ is the last bucket
PRESS_EDGES = [0.5, 0.7, 0.85, 0.95, 1.05, 1.15, 1.3, 1.5, 1.8]
SHRINK_BALLS = 400                                      # pseudo-balls toward the parent value


def bucket(x: float, edges: list) -> int:
    return bisect.bisect_left(edges, x) if isinstance(edges[0], float) else bisect.bisect_left(edges, x)


def phase_of(over: int, cfg: dict) -> str:
    for lo, hi, name in cfg["phases"]:
        if lo <= over <= hi:
            return name
    return "death"


def load_ratings(fmt: str):
    R = json.loads((ROOT / "data" / f"ratings_{fmt}.json").read_text(encoding="utf-8"))
    bat, bowl, ro = {}, {}, {}
    for pid, p in R["players"].items():
        if p.get("bat"):
            bat[pid] = p["bat"]["phase"]
            ro[pid] = p["bat"].get("other_out_idx") or 1.0
        if p.get("bowl"):
            bowl[pid] = p["bowl"]["phase"]
    return R["baselines"], bat, bowl, ro


def iter_matches(cfg: dict):
    for comp, z in cfg["sources"]:
        if not (RAW / z).exists():
            continue
        with zipfile.ZipFile(RAW / z) as zf:
            for n in zf.namelist():
                if not n.endswith(".json"):
                    continue
                m = json.loads(zf.read(n))
                info = m["info"]
                if info.get("gender") != "male" or info.get("balls_per_over", 6) != 6:
                    continue
                yr = int(info["dates"][0][:4])
                if yr < FIRST_YEAR or info.get("overs") != cfg["overs"]:
                    continue
                full = comp in ("t20i", "odi") and all(t in FULL for t in info["teams"])
                yield comp, full, yr, m


def complete_first_innings(m: dict, cfg: dict):
    inns = [i for i in m.get("innings", []) if not i.get("super_over")]
    if not inns:
        return None
    oc = m["info"].get("outcome", {})
    if "method" in oc:
        return None
    return inns[0]


PACE_KINDS = {"fast", "fast_medium", "medium_fast", "medium"}
MATCHUP_SHRINK_BALLS = 2000


def load_styles() -> tuple[dict, dict]:
    """Batting hand and bowling kind (pace kinds grouped) per Cricsheet ID."""
    st = json.loads((ROOT / "data" / "raw_stats" / "styles.json").read_text(encoding="utf-8"))
    hand = {k: v["bat_hand"] for k, v in st.items() if v.get("bat_hand")}
    kind = {}
    for k, v in st.items():
        kd = (v.get("bowl") or {}).get("kind")
        if kd:
            kind[k] = "pace" if kd in PACE_KINDS else kd
    return hand, kind


def matchup_table(MA: dict, ME: dict, MN: dict) -> dict:
    """Design T2-1. Ratio actual / ratings-predicted per (batting hand, bowling kind), shrunk toward 1, then
    double-centred by IPF so that, weighted by real exposure, every bowling kind and every batting hand still
    averages 1 (players' own indexes already hold their overall level; this only redistributes by matchup)."""
    hands = sorted({h for h, k in MA})
    kinds = sorted({k for h, k in MA})
    out: dict = {}
    for j, mname in enumerate(METRICS):
        if mname == "run_out":
            continue
        r, w = {}, {}
        for hk in MA:
            e, a, n = ME[hk][j], MA[hk][j], MN[hk]
            k = MATCHUP_SHRINK_BALLS * (e / n) if n else 0.0
            r[hk] = (a + k) / (e + k) if e + k > 0 else 1.0
            w[hk] = e
        for _ in range(50):
            for kd in kinds:
                tot = sum(w.get((h, kd), 0) for h in hands)
                if tot:
                    avg = sum(r[(h, kd)] * w[(h, kd)] for h in hands if (h, kd) in r) / tot
                    for h in hands:
                        if (h, kd) in r:
                            r[(h, kd)] /= avg
            for h in hands:
                tot = sum(w.get((h, kd), 0) for kd in kinds)
                if tot:
                    avg = sum(r[(h, kd)] * w[(h, kd)] for kd in kinds if (h, kd) in r) / tot
                    for kd in kinds:
                        if (h, kd) in r:
                            r[(h, kd)] /= avg
        for (h, kd), v in r.items():
            out.setdefault(h, {}).setdefault(kd, {})[mname] = round(v, 4)
    return out


def fit(fmt: str) -> dict:
    cfg = CFG[fmt]
    N = cfg["overs"] * 6
    base, bat, bowl, ro = load_ratings(fmt)
    hand, kind = load_styles()
    MA = defaultdict(lambda: [0.0] * len(METRICS))   # matchup (hand, kind) -> actual sums
    ME = defaultdict(lambda: [0.0] * len(METRICS))   # ... and ratings-predicted sums
    MN = defaultdict(int)

    # ---------------- pass 1: innings scale per competition/year and the par (resources) table
    totals = defaultdict(list)
    rem = defaultdict(lambda: [0.0, 0])           # (balls bowled, wkts lost) -> sum of runs still to come, count
    inn_records = []
    for comp, full, yr, m in iter_matches(cfg):
        inn = complete_first_innings(m, cfg)
        if not inn:
            continue
        seq = []                                   # (legal balls bowled before this ball, wkts, team runs before)
        runs = wk = legal = 0
        for ov in inn["overs"]:
            for d in ov["deliveries"]:
                ex = d.get("extras", {})
                if "wides" not in ex and "noballs" not in ex:
                    seq.append((legal, wk, runs))
                    legal += 1
                runs += d["runs"]["total"]
                wk += sum(1 for w in d.get("wickets", []) if w["kind"] not in ("retired hurt", "retired not out"))
        if not (wk >= 10 or legal >= N):
            continue                               # innings ended early for another reason (abandoned etc.)
        key_comp = f"{comp}_full" if full else comp
        totals[(comp, yr)].append(runs)
        if full:
            totals[(key_comp, yr)].append(runs)
        inn_records.append(((comp, yr), seq, runs))
    scale = {}
    for (c, y), xs in totals.items():
        pool = [v for d in range(-1, 2) for v in totals.get((c, y + d), [])]
        scale[(c, y)] = sum(pool) / len(pool)
    for (c, y), seq, total in inn_records:
        s = scale[(c, y)]
        for b, w, r in seq:
            cell = rem[(b // 6, min(w, 9))]
            cell[0] += (total - r) / s
            cell[1] += 1
    par = [[None] * 10 for _ in range(cfg["overs"])]
    for o in range(cfg["overs"]):
        for w in range(10):
            # pool +-1 over (and +-1 wicket when thin) for stability
            acc = n = 0
            for do in (-1, 0, 1):
                for dw in ((0,) if rem.get((o, w), [0, 0])[1] >= 300 else (-1, 0, 1)):
                    c = rem.get((o + do, w + dw))
                    if c:
                        acc += c[0]
                        n += c[1]
            par[o][w] = acc / n if n else None
    # fill gaps and enforce monotone: fewer resources with more balls bowled and more wickets lost
    for o in range(cfg["overs"]):
        for w in range(10):
            if par[o][w] is None:
                par[o][w] = par[o][w - 1] * 0.8 if w else (par[o - 1][w] if o else 1.0)
    for o in range(cfg["overs"]):
        for w in range(1, 10):
            par[o][w] = min(par[o][w], par[o][w - 1])
    for w in range(10):
        for o in range(1, cfg["overs"]):
            par[o][w] = min(par[o][w], par[o - 1][w])
    par0 = par[0][0]
    par = [[round(v / par0, 5) for v in row] for row in par]   # par[0][0] == 1 -> scale = expected total

    def par_at(balls_bowled: int, wk: int) -> float:
        o = min(balls_bowled // 6, cfg["overs"] - 1)
        frac_in_over = (balls_bowled % 6) / 6
        a = par[o][min(wk, 9)]
        b = par[o + 1][min(wk, 9)] if o + 1 < cfg["overs"] else 0.0
        return a + (b - a) * frac_in_over

    # ---------------- pass 2: observed / predicted per joint (settle, state) cell
    nS = len(SETTLE_EDGES) + 1
    A = defaultdict(lambda: [0.0] * len(METRICS))
    E = defaultdict(lambda: [0.0] * len(METRICS))
    NB = defaultdict(int)
    WIN = defaultdict(lambda: [0, 0])      # chase state (balls left, wkts, pressure) -> [chaser won, balls seen]
    WOBS = defaultdict(lambda: [0.0, 0.0])  # one sample per over of each chase: (log pressure, resources) -> won
    for comp, full, yr, m in iter_matches(cfg):
        oc = m["info"].get("outcome", {})
        if "method" in oc:
            continue
        inns = [i for i in m.get("innings", []) if not i.get("super_over")]
        reg = m["info"]["registry"]["people"]
        bcomp = base.get(comp)
        if not bcomp or str(yr) not in bcomp:
            continue
        brow = bcomp[str(yr)]
        sc = scale.get((comp, yr))
        if not sc:
            continue
        target = None
        winner = oc.get("winner") if "winner" in oc else (None if oc.get("result") != "tie" else "tie")
        for k, inn in enumerate(inns[:2]):
            if k == 1:
                t = inn.get("target") or {}
                if t.get("overs", cfg["overs"]) != cfg["overs"]:
                    break
                target = t.get("runs") or target
                if not target:
                    break
            faced = defaultdict(int)
            runs = wk = legal = 0
            prev_nb = False
            for ov in inn["overs"]:
                ph = phase_of(ov["over"], cfg)
                bp = brow.get(ph)
                for d in ov["deliveries"]:
                    ex = d.get("extras", {})
                    wide, nb = "wides" in ex, "noballs" in ex
                    bid, wid = reg.get(d["batter"]), reg.get(d["bowler"])
                    if not wide and not nb and not prev_nb and bp and bid in bat and wid in bowl:
                        bl = N - legal
                        sb = bucket(faced[bid], SETTLE_EDGES)
                        blb = bucket(bl, cfg["balls_left_edges"])
                        wb = bucket(wk, WKT_EDGES)
                        if k == 0:
                            st = ("1", blb, wb)
                        else:
                            need = target - runs
                            p = par_at(legal, wk) * sc
                            press = need / p if p > 1 else 9.0
                            st = ("2", blb, wb, bucket(press, PRESS_EDGES))
                            if winner is not None:
                                wcell = WIN[st[1:]]
                                wcell[0] += winner == inn["team"]
                                wcell[1] += 1
                                if legal % 6 == 0 and need > 0:
                                    lp = round(math.log(max(press, 0.05)), 1)
                                    rs = round(max(par_at(legal, wk), 0.01), 2)
                                    o = WOBS[(lp, rs)]
                                    o[0] += winner == inn["team"]
                                    o[1] += 1
                        bi, wi = bat[bid][ph], bowl[wid][ph]
                        br = d["runs"]["batter"]
                        wk_b = any(w["kind"] in ("bowled", "caught", "caught and bowled", "lbw", "stumped",
                                                 "hit wicket") for w in d.get("wickets", []))
                        ro_b = any(w["kind"] in ("run out", "obstructing the field") for w in d.get("wickets", []))
                        act = (br, wk_b, br == 0, br == 4 and not d["runs"].get("non_boundary"), br == 6, ro_b)
                        pred = (bp["runs"] * bi["runs"] * bowl[wid][ph]["runs"],
                                bp["wkt"] * bi["wkt"] * wi["wkt"],
                                bp["dot"] * bi["dot"] * wi["dot"],
                                bp["four"] * bi["four"] * wi["four"],
                                bp["six"] * bi["six"] * wi["six"],
                                bp["other_out"] * ro.get(bid, 1.0))
                        hk = (hand.get(bid), kind.get(wid))
                        if hk[0] and hk[1]:
                            ma, me = MA[hk], ME[hk]
                            for j in range(len(METRICS)):
                                ma[j] += act[j]
                                me[j] += pred[j]
                            MN[hk] += 1
                        key = (sb, st)
                        a, e = A[key], E[key]
                        for j in range(len(METRICS)):
                            a[j] += act[j]
                            e[j] += pred[j]
                        NB[key] += 1
                    if not wide:
                        faced[bid] += 1
                    prev_nb = nb
                    if not wide and not nb:
                        legal += 1
                    runs += d["runs"]["total"]
                    wk += sum(1 for w in d.get("wickets", []) if w["kind"] not in ("retired hurt", "retired not out"))

    # ---------------- backfitting: settle[s] x state[st]
    keys = list(A)
    settle = {s: [1.0] * len(METRICS) for s in range(nS)}
    state = {k[1]: [1.0] * len(METRICS) for k in keys}

    def shrunk(a, e, n, prior):
        # pseudo-data: SHRINK_BALLS balls at the prior multiplier, in expected-count units
        out = []
        for j in range(len(METRICS)):
            rate = e[j] / n if n else 0
            k = SHRINK_BALLS * rate
            out.append((a[j] + k * prior[j]) / (e[j] + k) if e[j] + k > 0 else prior[j])
        return out

    for it in range(12):
        # settle given state
        sa = defaultdict(lambda: [0.0] * len(METRICS))
        se = defaultdict(lambda: [0.0] * len(METRICS))
        sn = defaultdict(int)
        for key in keys:
            s, st = key
            for j in range(len(METRICS)):
                sa[s][j] += A[key][j]
                se[s][j] += E[key][j] * state[st][j]
            sn[s] += NB[key]
        for s in sa:
            settle[s] = shrunk(sa[s], se[s], sn[s], [1.0] * len(METRICS))
        # state given settle; chase cells shrink toward their (balls left, wickets) marginal
        ta = defaultdict(lambda: [0.0] * len(METRICS))
        te = defaultdict(lambda: [0.0] * len(METRICS))
        tn = defaultdict(int)
        for key in keys:
            s, st = key
            for j in range(len(METRICS)):
                ta[st][j] += A[key][j]
                te[st][j] += E[key][j] * settle[s][j]
            tn[st] += NB[key]
        marg_a = defaultdict(lambda: [0.0] * len(METRICS))
        marg_e = defaultdict(lambda: [0.0] * len(METRICS))
        marg_n = defaultdict(int)
        for st in ta:
            if st[0] == "2":
                mk = st[:3]
                for j in range(len(METRICS)):
                    marg_a[mk][j] += ta[st][j]
                    marg_e[mk][j] += te[st][j]
                marg_n[mk] += tn[st]
        marg = {mk: shrunk(marg_a[mk], marg_e[mk], marg_n[mk], [1.0] * len(METRICS)) for mk in marg_a}
        # A chase cell with few balls (0 down needing a big rate halfway through: rare in full chases, but the
        # start of every short rain-reduced chase) is shrunk toward the first innings in the same state (balls
        # left, wickets lost: well populated) x the pressure response at that stage, pooled over wickets. Shrunk
        # toward the chase marginal alone, such chases batted as if under no pressure (a 10-over chase won 43%).
        one = {(st[1], st[2]): shrunk(ta[st], te[st], tn[st], [1.0] * len(METRICS)) for st in ta if st[0] == "1"}
        ones = [1.0] * len(METRICS)
        pr_a = defaultdict(lambda: [0.0] * len(METRICS))
        pr_e = defaultdict(lambda: [0.0] * len(METRICS))
        pr_n = defaultdict(int)
        for st in ta:
            if st[0] == "2":
                pk = (st[1], st[3])
                for j in range(len(METRICS)):
                    pr_a[pk][j] += ta[st][j]
                    pr_e[pk][j] += te[st][j] * one.get((st[1], st[2]), ones)[j]
                pr_n[pk] += tn[st]
        press_resp = {pk: shrunk(pr_a[pk], pr_e[pk], pr_n[pk], [1.0] * len(METRICS)) for pk in pr_a}
        for st in ta:
            if st[0] == "2":
                prior = [m * q for m, q in zip(one.get((st[1], st[2]), ones), press_resp[(st[1], st[3])])]
            else:
                prior = [1.0] * len(METRICS)
            state[st] = shrunk(ta[st], te[st], tn[st], prior)
        # keep the settle curve mean-preserving (weighted by expected counts) - state absorbs the level
        for j in range(len(METRICS)):
            num = sum(settle[s][j] * se[s][j] for s in se)
            den = sum(se[s][j] for s in se)
            f = num / den if den else 1.0
            for s in settle:
                settle[s][j] /= f
    # final rescale so that, over all real balls, ratings x tables reproduce the actual totals exactly
    for j in range(len(METRICS)):
        a = sum(A[k][j] for k in keys)
        e1 = sum(E[k][j] * settle[k[0]][j] * state[k[1]][j] for k in keys)
        g = a / e1 if e1 else 1.0
        for st in state:
            state[st][j] *= g
        for mk in marg:
            marg[mk][j] *= g
    # overall check: total predicted with tables v actual
    check = {}
    for j, mname in enumerate(METRICS):
        a = sum(A[k][j] for k in keys)
        e0 = sum(E[k][j] for k in keys)
        e1 = sum(E[k][j] * settle[k[0]][j] * state[k[1]][j] for k in keys)
        check[mname] = {"actual/ratings": round(a / e0, 4), "actual/with_tables": round(a / e1, 4)}

    def r(v):
        return [round(x, 4) for x in v]
    blN = len(cfg["balls_left_edges"]) + 1
    wN = len(WKT_EDGES) + 1
    pN = len(PRESS_EDGES) + 1
    state1 = [[r(state.get(("1", b, w), [1.0] * len(METRICS))) for w in range(wN)] for b in range(blN)]
    state2 = [[[r(state.get(("2", b, w, p), [m * q for m, q in zip(state.get(("1", b, w), [1.0] * len(METRICS)),
                                                                   press_resp.get((b, p), [1.0] * len(METRICS)))]))
                 for p in range(pN)]
               for w in range(wN)] for b in range(blN)]
    # chase win probability per state: shrink toward the (balls left, wickets) marginal, then make it monotone
    # (lower pressure -> higher chance) within each (balls left, wickets) row
    win = [[[0.5] * pN for _ in range(wN)] for _ in range(blN)]
    for b in range(blN):
        for w in range(wN):
            row_w = sum(WIN[(b, w, p)][0] for p in range(pN))
            row_n = sum(WIN[(b, w, p)][1] for p in range(pN))
            prior = row_w / row_n if row_n else 0.5
            vals = []
            for p in range(pN):
                c = WIN[(b, w, p)]
                # balls in one innings are not independent: count each ~30 balls as one observation
                n = c[1] / 30
                vals.append(((c[0] / 30) + 3 * prior) / (n + 3))
            for p in range(1, pN):
                vals[p] = min(vals[p], vals[p - 1])
            win[b][w] = [round(v, 4) for v in vals]
    # smooth model: P(chase won) = 1 / (1 + exp(a + k0 * log(pressure) / resources^g)), max likelihood by grid
    obs = [(lp, rs, o[0], o[1]) for (lp, rs), o in WOBS.items()]
    best = None
    for a in [x / 20 for x in range(-20, 21)]:
        for k0 in [x / 4 for x in range(2, 41)]:
            for g in (0.0, 0.25, 0.5, 0.75):
                ll = 0.0
                for lp, rs, w, n in obs:
                    z = a + k0 * lp / (rs ** g)
                    pr = 1 / (1 + math.exp(min(max(z, -30), 30)))
                    pr = min(max(pr, 1e-6), 1 - 1e-6)
                    ll += w * math.log(pr) + (n - w) * math.log(1 - pr)
                if best is None or ll > best[0]:
                    best = (ll, a, k0, g)
    win_model = {"a": best[1], "k0": best[2], "g": best[3], "samples": sum(o[3] for o in obs)}
    return {
        "format": fmt, "since": FIRST_YEAR, "metrics": list(METRICS), "chase_win": win, "win_model": win_model,
        "matchup": matchup_table(MA, ME, MN), "matchup_balls": {f"{h}|{k}": n for (h, k), n in MN.items()},
        "settle_edges": SETTLE_EDGES, "wkt_edges": WKT_EDGES, "press_edges": PRESS_EDGES,
        "balls_left_edges": cfg["balls_left_edges"],
        "settle": [r(settle[s]) for s in range(nS)],
        "state1": state1, "state2": state2,
        "par": par, "scale": {f"{c}|{y}": round(v, 1) for (c, y), v in sorted(scale.items())},
        "check": check, "balls": sum(NB.values()),
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for fmt in ("t20", "odi"):
        res = fit(fmt)
        (OUT / f"situation_{fmt}.json").write_text(json.dumps(res), encoding="utf-8")
        print(f"\n{fmt}: {res['balls']} balls; check {res['check']}")
        print("  settle (runs, wkt) by balls faced:",
              [(e, s[0], s[1]) for e, s in zip(SETTLE_EDGES + ['50+'], res["settle"])])
        print("  par: start 1.0, halfway 0 wkts", res["par"][len(res["par"]) // 2][0], "halfway 5 wkts",
              res["par"][len(res["par"]) // 2][5])
        print("  state1 runs/wkt, last bucket of balls left (start of innings), by wickets lost:",
              [(x[0], x[1]) for x in res["state1"][-1]])
        print("  state1 runs/wkt, death (fewest balls left), by wickets lost:", [(x[0], x[1]) for x in res["state1"][0]])
        mid = len(res["state2"]) // 2
        print("  state2 runs/wkt, mid-innings, 3 wkts lost, by pressure:",
              [(e, x[0], x[1]) for e, x in zip(PRESS_EDGES + ['>'], res["state2"][mid][3])])
    return 0


if __name__ == "__main__":
    sys.exit(main())
