"""Fit what Test captains do (docs/test_match_plan.md section 4), from Cricsheet Tests.

  toss         share of toss winners who bat
  declare      per innings (1-3), the chance of declaring at the end of an over: a logistic model on the lead,
               the score, wickets down, overs left in the match, the rate the other side would need, and whether
               a batter at the crease is in the nineties. Fitted on the over-ends from the lowest lead (score, in
               the first innings) at which anyone has declared; below that nobody declares.
  follow_on    the chance of enforcing it, given a lead of 200 or more: logistic on the lead, overs left and the
               overs the bowlers have just bowled
  spell        the chance that the bowler at an end bowls that end's next over: a table by kind of bowler
               (specialist pace, specialist spin, part-timer) x overs in the spell x "new ball due", times a
               logistic correction for his figures in the spell against what his ratings predicted and for the
               overs he has bowled in the innings
  choice       who comes on when a bowler is taken off (and who opens): each candidate's weight is his career
               overs per match x tables for his kind by ball age, by pitch wear and by his rest since he last
               bowled, and for his overs per match; fitted by iterative scaling to the bowlers really chosen
  fatigue      a probe, not used by the engine: observed / predicted wickets and runs by over of spell and by
               overs already bowled in the innings (predicted includes the situation tables)

Cricsheet has no clock, no days and no ends: an "end" is every other over, a spell is the same bowler at an end
in consecutive turns (a spell broken by lunch or stumps looks unbroken), "overs left" is as in
fit_test_situation.py, and the new ball is taken to be due at every 80th over.

Writes data/engine/test_captain.json.   Run:  python -m engine.fit.fit_test_captain
"""
from __future__ import annotations

import bisect
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

from ..test_captain import declare_x, follow_x, spell_x
from ..test_situation import TestSituation
from .fit_basics import bowl_types
from .fit_test_situation import BOWLER_WICKETS, iter_tests, is_draw, load_ratings, match_overs, outs, overs_left

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "engine"

LEN_EDGES = [2, 3, 4, 5, 6, 7, 8, 10, 13, 17]     # overs in the spell so far: 1, 2, ... 7, 8-9, 10-12, 13-16, 17+
REST_EDGES = [7, 13, 25]                          # overs since he last bowled: 3-6, 7-12, 13-24, 25+ (0 = not yet)
OPM_EDGES = [1, 4, 10, 20, 30]                    # career overs per match
OPM_FLOOR = 0.15                                  # a man who never bowls still has a weight
FOLLOW_ON_LEAD = 200


def bucket(x: float, edges: list) -> int:
    return bisect.bisect_right(edges, x)


def group_of(rec: dict | None) -> str:
    """'pace' | 'spin' (specialists) | 'part'."""
    role = (rec or {}).get("bowl_role") or ""
    if not role.startswith("spec"):
        return "part"
    return "spin" if (rec or {}).get("bowl_type") == "spin" else "pace"


def opm_of(rec: dict | None) -> float:
    """Career overs per match, as engine.data.player works it out."""
    w = (rec or {}).get("bowl")
    car = (rec or {}).get("career") or {}
    m = sum((c.get("m") or 0) for c in car.values() if isinstance(c, dict))
    return (w.get("balls", 0) / 6) / m if w and m else 0.0


# ---------------------------------------------------------------------------------------------- logistic fit
def solve(a: list, b: list) -> list:
    n = len(b)
    a = [row[:] + [b[i]] for i, row in enumerate(a)]
    for i in range(n):
        p = max(range(i, n), key=lambda r: abs(a[r][i]))
        a[i], a[p] = a[p], a[i]
        for r in range(n):
            if r != i and a[i][i]:
                f = a[r][i] / a[i][i]
                for c in range(i, n + 1):
                    a[r][c] -= f * a[i][c]
    return [a[i][n] / a[i][i] if a[i][i] else 0.0 for i in range(n)]


def logit_fit(rows: list, k: int, ridge: float = 1.0) -> list:
    """Maximum likelihood by Newton's method. rows: (features, y, offset). A small ridge penalty (not on the
    intercept, feature 0) keeps thin data from running away."""
    beta = [0.0] * k
    for _ in range(40):
        g = [0.0] * k
        h = [[0.0] * k for _ in range(k)]
        for x, y, off in rows:
            z = off + sum(b * v for b, v in zip(beta, x))
            p = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))
            w = p * (1.0 - p)
            for i in range(k):
                g[i] += (y - p) * x[i]
                hi, wx = h[i], w * x[i]
                for j in range(i, k):
                    hi[j] += wx * x[j]
        for i in range(k):
            for j in range(i):
                h[i][j] = h[j][i]
        for i in range(1, k):
            g[i] -= ridge * beta[i]
            h[i][i] += ridge
        step = solve(h, g)
        beta = [b + s for b, s in zip(beta, step)]
        if max(abs(s) for s in step) < 1e-7:
            break
    return beta


def logit(p: float) -> float:
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


DECLARE_NAMES = {1: ["const", "runs/100", "wkts/10", "left/100", "nineties"],
                 2: ["const", "lead/100", "runs/100", "wkts/10", "left/100", "nineties"],
                 3: ["const", "lead/100", "left/100", "need_per_over", "wkts/10", "nineties"]}


def fit() -> dict:
    base, bat, bowl, rec = load_ratings()
    btype = bowl_types("test")
    sit = TestSituation()
    toss = [0, 0]
    drows = {1: [], 2: [], 3: []}                 # innings -> (key value, features, declared)
    frows = []
    scount = defaultdict(lambda: [0, 0])          # (group, spell bucket, new ball due) -> [continued, decisions]
    srows = defaultdict(list)                     # group -> (features, continued, table cell)
    decisions = []                                # (chosen index, [(base weight, age cell, wear cell, rest cell, opm cell)])
    fat = defaultdict(lambda: [0.0] * 5)          # (group, kind, bucket) -> balls, runs, exp runs, wkts, exp wkts
    n_matches = 0
    for m in iter_tests():
        info = m["info"]
        brow = (base.get(info["dates"][0][:4]) or {}).get("all")
        if not brow:
            continue
        n_matches += 1
        reg = info["registry"]["people"]
        if info.get("toss", {}).get("decision") in ("bat", "field"):
            toss[0] += info["toss"]["decision"] == "bat"
            toss[1] += 1
        total, draw = match_overs(m), is_draw(m)
        inns = m.get("innings", [])[:4]
        gone = 0
        team_runs = defaultdict(int)
        for k, inn in enumerate(inns):
            team = inn["team"]
            other = [t for t in info["teams"] if t != team][0]
            lead0 = team_runs[team] - team_runs[other]
            overs = inn.get("overs", [])
            if k == 2 and len(inns[1].get("overs", [])):
                d = team_runs[inns[0]["team"]] - team_runs[inns[1]["team"]]
                if d >= FOLLOW_ON_LEAD:
                    frows.append((follow_x(d, overs_left(gone, total, draw), len(inns[1]["overs"])),
                                  int(team == inns[1]["team"]), 0.0))
            xi = [reg.get(n) for n in info.get("players", {}).get(other, [])]
            xi = [p for p in xi if p]
            grp = {p: group_of(rec.get(p)) for p in xi}
            opm = {p: opm_of(rec.get(p)) for p in xi}
            runs = wk = 0
            score = defaultdict(int)              # batter -> runs
            faced = defaultdict(int)
            crease: list = []
            seq: list = []                        # bowler of each over
            last_bowled: dict = {}
            inns_overs = defaultdict(int)
            spell = [None, None]                  # per end: [bowler, overs, runs, exp runs, wkts, exp wkts]
            for n, ov in enumerate(overs):
                dl = ov["deliveries"]
                bw = reg.get(dl[0]["bowler"])
                end = n % 2
                a_b, w_b = bucket(n % 80, sit.t["age_edges"]), bucket(gone, sit.t["wear_edges"])
                due = n >= 80 and n % 80 < 2
                sp = spell[end]
                if sp is not None:
                    g = group_of(rec.get(sp[0]))
                    cell = (g, bucket(sp[1], LEN_EDGES), due)
                    cont = bw == sp[0]
                    scount[cell][0] += cont
                    scount[cell][1] += 1
                    srows[g].append((spell_x(sp[2] - sp[3], sp[4] - sp[5], inns_overs[sp[0]]), int(cont), cell))
                if (sp is None or bw != sp[0]) and bw in grp:
                    bar = {seq[-1] if seq else None, sp[0] if sp else None}
                    cands = [p for p in xi if p not in bar]
                    if bw in cands:
                        feats = []
                        for p in cands:
                            lb = last_bowled.get(p)
                            rest = 0 if lb is None else 1 + bucket(n - lb, REST_EDGES)
                            feats.append((max(opm[p], OPM_FLOOR), (grp[p], a_b), (grp[p], w_b), (grp[p], rest),
                                          bucket(opm[p], OPM_EDGES)))
                        decisions.append((cands.index(bw), feats))
                if sp is None or bw != sp[0]:
                    sp = spell[end] = [bw, 0, 0.0, 0.0, 0.0, 0.0]
                g = group_of(rec.get(bw))
                fcells = [fat[(g, "spell", min(sp[1] // 2, 5))], fat[(g, "innings", min(inns_overs[bw] // 10, 4))]]
                left = overs_left(gone, total, draw)
                ty = btype.get(bw, "unknown")
                for d in dl:
                    ex = d.get("extras", {})
                    wide, nb = "wides" in ex, "noballs" in ex
                    bid = reg.get(d["batter"])
                    for name in (d["batter"], d["non_striker"]):
                        if name not in crease:
                            crease.append(name)
                    conceded = d["runs"]["batter"] + ex.get("wides", 0) + ex.get("noballs", 0)
                    bwk = sum(1 for w in d.get("wickets", []) if w["kind"] in BOWLER_WICKETS)
                    sp[2] += conceded
                    sp[4] += bwk
                    if not wide and not nb:
                        bi, wi = bat.get(bid), bowl.get(bw)
                        er = brow["runs"] * (bi["runs"] if bi else 1.0) * (wi["runs"] if wi else 1.0)
                        ew = brow["wkt"] * (bi["wkt"] if bi else 1.0) * (wi["wkt"] if wi else 1.0)
                        sp[3] += er + brow["wide"] + brow["noball"]
                        sp[5] += ew
                        if bi and wi and g != "part":
                            c = (sit.cell(k + 1, wk, lead0 + runs) if k < 3 else
                                 sit.cell(4, wk, 0, -lead0 + 1 - runs, left))
                            mu = sit.multipliers(c, faced[bid], ty, gone, n % 80)
                            for fc in fcells:
                                fc[0] += 1
                                fc[1] += d["runs"]["batter"]
                                fc[2] += er * mu["runs"]
                                fc[3] += bwk
                                fc[4] += ew * mu["wkt"]
                    if not wide:
                        faced[bid] += 1
                    score[d["batter"]] += d["runs"]["batter"]
                    runs += d["runs"]["total"]
                    wk += outs(d)
                    for w in d.get("wickets", []):
                        if w["player_out"] in crease:
                            crease.remove(w["player_out"])
                sp[1] += 1
                inns_overs[bw] += 1
                last_bowled[bw] = n
                seq.append(bw)
                gone += 1
                # the declaration decision at the end of this over
                last = n == len(overs) - 1
                declared = bool(inn.get("declared")) and last
                if k < 3 and (declared or not last) and wk < 10:
                    lead = lead0 + runs
                    nineties = any(90 <= score[b] % 100 for b in crease[-2:])
                    x = declare_x(k + 1, runs, lead, wk, overs_left(gone, total, draw), nineties)
                    drows[k + 1].append((runs if k == 0 else lead, x, int(declared)))
            team_runs[team] += runs

    out = {"format": "test", "matches": n_matches,
           "toss": {"p_bat": round(toss[0] / max(toss[1], 1), 4), "n": toss[1]}}

    # ------------------------------------------------------------- declarations
    out["declare"] = {}
    for i in (1, 2, 3):
        events = sorted(v for v, _, y in drows[i] if y)
        floor = events[0]
        rows = [(x, y, 0.0) for v, x, y in drows[i] if v >= floor]
        beta = logit_fit(rows, len(rows[0][0]))
        out["declare"][str(i)] = {"features": DECLARE_NAMES[i], "coef": [round(b, 4) for b in beta],
                                  "floor": floor, "floor_on": "runs" if i == 1 else "lead",
                                  "over_ends": len(rows), "declared": len(events),
                                  "median_at_declaration": events[len(events) // 2]}
    # ------------------------------------------------------------- follow-on
    beta = logit_fit(frows, 4)
    out["follow_on"] = {"features": ["const", "(lead-200)/100", "left/100", "overs_bowled/100"],
                        "coef": [round(b, 4) for b in beta], "lead": FOLLOW_ON_LEAD,
                        "chances": len(frows), "enforced": sum(y for _, y, _ in frows)}
    # ------------------------------------------------------------- spells
    out["spell"] = {"len_edges": LEN_EDGES, "groups": {}}
    for g in ("pace", "spin", "part"):
        tot = [sum(v[0] for c, v in scount.items() if c[0] == g), sum(v[1] for c, v in scount.items() if c[0] == g)]
        rate = tot[0] / max(tot[1], 1)
        table, counts = {}, {}
        for due in (False, True):
            row, nrow = [], []
            for b in range(len(LEN_EDGES) + 1):
                c, n = scount.get((g, b, due), (0, 0))
                row.append(round((c + 20 * rate) / (n + 20), 4))      # 20 pseudo-decisions at the kind's own rate
                nrow.append(n)
            table["due" if due else "normal"] = row
            counts["due" if due else "normal"] = nrow
        rows = [(x, y, logit(table["due" if c[2] else "normal"][c[1]])) for x, y, c in srows[g]]
        beta = logit_fit(rows, 4)
        out["spell"]["groups"][g] = {"continue": table, "decisions": counts, "rate": round(rate, 4),
                                     "features": ["const", "runs_excess/10", "wkts_excess", "innings_overs/10"],
                                     "coef": [round(b, 4) for b in beta]}
    # ------------------------------------------------------------- who comes on
    tabs = [defaultdict(lambda: 1.0) for _ in range(4)]
    obs = [defaultdict(float) for _ in range(4)]
    for ch, feats in decisions:
        for i in range(4):
            obs[i][feats[ch][1 + i]] += 1
    for _ in range(12):
        for i in range(4):
            pred = defaultdict(float)
            for ch, feats in decisions:
                ws = [f[0] * tabs[0][f[1]] * tabs[1][f[2]] * tabs[2][f[3]] * tabs[3][f[4]] for f in feats]
                s = sum(ws)
                for f, w in zip(feats, ws):
                    pred[f[1 + i]] += w / s
            for c, p in pred.items():
                tabs[i][c] = max(tabs[i][c] * (obs[i][c] + 0.5) / (p + 0.5), 1e-4)
    ll = 0.0
    for ch, feats in decisions:
        ws = [f[0] * tabs[0][f[1]] * tabs[1][f[2]] * tabs[2][f[3]] * tabs[3][f[4]] for f in feats]
        ll += math.log(ws[ch] / sum(ws))

    def by_group(i, n):
        res = {}
        for g in ("pace", "spin", "part"):
            vals = [tabs[i][(g, b)] for b in range(n)]
            res[g] = [round(v, 4) for v in vals]
        return res
    out["choice"] = {
        "rest_edges": REST_EDGES, "opm_edges": OPM_EDGES, "opm_floor": OPM_FLOOR,
        "decisions": len(decisions), "mean_log_likelihood": round(ll / max(len(decisions), 1), 4),
        "age": by_group(0, len(sit.t["age_edges"]) + 1), "wear": by_group(1, len(sit.t["wear_edges"]) + 1),
        "rest": by_group(2, len(REST_EDGES) + 2),
        "opm": [round(tabs[3][b], 4) for b in range(len(OPM_EDGES) + 1)],
        "chosen": {"age": {g: [int(obs[0][(g, b)]) for b in range(len(sit.t["age_edges"]) + 1)]
                           for g in ("pace", "spin", "part")},
                   "rest": {g: [int(obs[2][(g, b)]) for b in range(len(REST_EDGES) + 2)]
                            for g in ("pace", "spin", "part")}},
    }
    # ------------------------------------------------------------- fatigue probe
    out["fatigue_probe"] = {
        f"{g}|{kind}": [{"balls": int(v[0]), "runs": round(v[1] / v[2], 3), "wkt": round(v[3] / v[4], 3)}
                        for b in range(6) if (v := fat.get((g, kind, b))) and v[0]]
        for g in ("pace", "spin") for kind in ("spell", "innings")}
    return out


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    t = fit()
    (OUT / "test_captain.json").write_text(json.dumps(t, indent=1), encoding="utf-8")
    print(f"{t['matches']} Tests; toss: bat {t['toss']['p_bat']} of {t['toss']['n']}")
    for i, d in t["declare"].items():
        print(f"declare, innings {i}: {d['declared']} declared in {d['over_ends']} over-ends from "
              f"{d['floor_on']} {d['floor']}; median {d['median_at_declaration']}")
        print("   " + ", ".join(f"{n} {c}" for n, c in zip(d["features"], d["coef"])))
    f = t["follow_on"]
    print(f"follow-on: {f['enforced']} of {f['chances']}; " + ", ".join(f"{n} {c}" for n, c in zip(f["features"], f["coef"])))
    for g, s in t["spell"]["groups"].items():
        print(f"spell, {g}: continue rate {s['rate']}")
        print("   by overs in the spell:", s["continue"]["normal"], s["decisions"]["normal"])
        print("   new ball due:         ", s["continue"]["due"], s["decisions"]["due"])
        print("   " + ", ".join(f"{n} {c}" for n, c in zip(s["features"], s["coef"])))
    c = t["choice"]
    print(f"choice: {c['decisions']} decisions, mean log likelihood {c['mean_log_likelihood']}")
    for k in ("age", "wear", "rest"):
        print(f"   {k}: {c[k]}")
    print(f"   opm: {c['opm']}")
    for k, v in t["fatigue_probe"].items():
        print(f"fatigue {k}: " + "; ".join(f"{x['balls']} balls runs {x['runs']} wkt {x['wkt']}" for x in v))
    return 0


if __name__ == "__main__":
    sys.exit(main())
