"""Fit the XI-selection model (engine/selection.py) on real XIs.

Data: every full-member v full-member international (ODIs from 2003, T20Is from 2006). For each team in each match,
the candidates are everyone who played for that team within WINDOW_DAYS of the match (a stand-in for the touring
squad, which Cricsheet doesn't record); the chosen XI is the real one. Pools of fewer than 13 are skipped (nothing
to choose). Player features use the ratings for the years around the match (year-1..year+1, as historical teams
do) and caps before the match (T20: internationals and leagues).

Venue spin advantage: log(pace runs per ball / spin runs per ball) at the venue minus the same for all venues,
shrunk by empirical Bayes (noise from per-ball variance, tau^2 estimated from venues with enough balls).

Model: conditional logit, P(XI) ~ exp(sum u_i + c[number of genuine bowlers]), fitted by maximum likelihood (Fisher-scoring steps with an
independent-Bernoulli curvature approximation and step halving on the exact likelihood), small ridge penalty.

In the engine the XI is the best valid XI under these utilities, with ratings redrawn from their uncertainty
each match (engine/selection.py); the validation below scores exactly that pick.

Validation: fit on matches up to TRAIN_UNTIL, test on later ones. Reported: players of the real XI picked by the
learned model's most likely XI, by the old rule (captain.select_xi), and by caps alone; and the expected overlap
when the XI is sampled (as in the engine). Then refit on all matches and write data/engine/selection_{fmt}.json.

    python -m engine.fit.fit_selection          (~5 min)
"""
from __future__ import annotations

import json
import math
import sys
import zipfile
from collections import defaultdict
from datetime import date
from pathlib import Path

from ..captain import select_xi as rule_select_xi
from ..conditions import venue_factor, venue_key
from ..data import FORMATS, baseline, player
from ..periods import fit_tau2
from ..selection import (EXPERIENCE_WEIGHT, FEATURES, XI, Rules, bowler_mask, esp, esp_without, features,
                         utilities)

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "engine"
STYLES = ROOT / "data" / "raw_stats" / "styles.json"
FULL = {"Afghanistan", "Australia", "Bangladesh", "England", "India", "Ireland", "New Zealand", "Pakistan",
        "South Africa", "Sri Lanka", "West Indies", "Zimbabwe"}
INTL = {"t20": "t20s_male_json.zip", "odi": "odis_male_json.zip"}
LEAGUES = [f"leagues/{c}_json.zip" for c in ("ipl", "bbl", "psl", "cpl", "sat", "ilt", "bpl", "lpl", "mlc", "ntb", "ssm")]
FIRST_YEAR = {"t20": 2006, "odi": 2003}
WINDOW_DAYS = 21
MIN_POOL = 13
TRAIN_UNTIL = 2018
RIDGE = 1.0


def _matches(fmt: str) -> tuple[list[dict], dict]:
    """Light match records (all sources, for caps) and venue spin/pace run stats."""
    styles = json.loads(STYLES.read_text(encoding="utf-8")) if STYLES.exists() else {}
    kind = {pid: (s.get("bowl") or {}).get("type") for pid, s in styles.items()}
    zips = [(INTL[fmt], True)] + ([(z, False) for z in LEAGUES] if fmt == "t20" else [])
    out = []
    vs = defaultdict(lambda: {"spin": [0, 0.0, 0.0], "pace": [0, 0.0, 0.0]})   # balls, runs, runs^2
    slot = [[0, 0] for _ in range(XI)]    # balls faced by batting position, team innings counted
    for z, intl in zips:
        if not (RAW / z).exists():
            continue
        with zipfile.ZipFile(RAW / z) as zf:
            for name in zf.namelist():
                if not name.endswith(".json"):
                    continue
                m = json.loads(zf.read(name))
                info = m["info"]
                if info.get("gender") != "male" or info.get("balls_per_over", 6) != 6:
                    continue
                reg = info["registry"]["people"]
                xi = {t: [reg[n] for n in ps if n in reg] for t, ps in info.get("players", {}).items()}
                out.append({"date": info["dates"][0], "teams": info["teams"], "xi": xi, "venue": info.get("venue"),
                            "intl": intl})
                v = vs[venue_key(info.get("venue"))]
                full = intl and all(t in FULL for t in info["teams"]) and int(info["dates"][0][:4]) >= FIRST_YEAR[fmt]
                for inn in m.get("innings", []):
                    if inn.get("super_over"):
                        continue
                    if full:
                        order, faced = [], defaultdict(int)
                        for ov in inn.get("overs", []):
                            for d in ov["deliveries"]:
                                for who in (d["batter"], d["non_striker"]):
                                    if who not in order:
                                        order.append(who)
                                if "wides" not in d.get("extras", {}):
                                    faced[d["batter"]] += 1
                        for k in range(XI):
                            slot[k][0] += faced.get(order[k], 0) if k < len(order) else 0
                            slot[k][1] += 1
                    for ov in inn.get("overs", []):
                        for d in ov["deliveries"]:
                            k = kind.get(reg.get(d["bowler"]))
                            if k not in ("spin", "pace") or "wides" in d.get("extras", {}):
                                continue
                            r = d["runs"]["total"]
                            a = v[k]
                            a[0] += 1
                            a[1] += r
                            a[2] += r * r
    out.sort(key=lambda x: x["date"])
    return out, vs, [round(a / n, 2) if n else 0.0 for a, n in slot]


def venue_spin_table(vs: dict) -> dict:
    tot = {k: [sum(v[k][j] for v in vs.values()) for j in range(3)] for k in ("spin", "pace")}
    g = math.log((tot["pace"][1] / tot["pace"][0]) / (tot["spin"][1] / tot["spin"][0]))
    rows = {}
    for key, v in vs.items():
        (ns, rs, qs), (np_, rp, qp) = v["spin"], v["pace"]
        if ns < 60 or np_ < 60 or rs <= 0 or rp <= 0:
            continue
        ms, mp = rs / ns, rp / np_
        d = math.log(mp / ms) - g
        var = (qs / ns - ms * ms) / (ns * ms * ms) + (qp / np_ - mp * mp) / (np_ * mp * mp)
        rows[key] = (d, var, min(ns, np_))
    tau2 = fit_tau2([(d * d, var) for d, var, n in rows.values() if n >= 300])
    return {k: round(d * tau2 / (tau2 + var), 4) for k, (d, var, n) in rows.items()}


def build_pools(fmt: str, matches: list[dict], vspin: dict, slot_balls: list[float]) -> list[dict]:
    by_team = defaultdict(list)
    for idx, m in enumerate(matches):
        y = int(m["date"][:4])
        if m["intl"] and y >= FIRST_YEAR[fmt] and all(t in FULL for t in m["teams"]):
            for t in m["teams"]:
                if len(m["xi"].get(t, [])) == XI:
                    by_team[t].append({"date": m["date"], "xi": m["xi"][t], "venue": m["venue"], "idx": idx})
    # caps before each match: one pass in date order
    count = defaultdict(int)
    snap = {}
    want = defaultdict(set)
    for t, ms in by_team.items():
        for i, rec in enumerate(ms):
            d0 = date.fromisoformat(rec["date"])
            pool = set()
            for other in ms:
                if abs((date.fromisoformat(other["date"]) - d0).days) <= WINDOW_DAYS:
                    pool.update(other["xi"])
            rec["pool"] = sorted(pool)
            want[rec["idx"]].update(pool)
    for i, m in enumerate(matches):
        if i in want:
            snap[i] = {pid: count[pid] for pid in want[i]}
        for ps in m["xi"].values():
            for pid in ps:
                count[pid] += 1
    pools = []
    pcache = {}
    for t, ms in by_team.items():
        for rec in ms:
            if len(rec["pool"]) < MIN_POOL:
                continue
            y = int(rec["date"][:4])
            squad = []
            for pid in rec["pool"]:
                key = (pid, y)
                if key not in pcache:
                    pcache[key] = player(fmt, pid, years=(y - 1, y + 1))
                squad.append(pcache[key])
            base = baseline(fmt, FORMATS[fmt]["intl"], y)
            vf = venue_factor(fmt, rec["venue"])["runs"]
            rows = features(squad, fmt, base, vspin.get(venue_key(rec["venue"]), 0.0), vf, snap[rec["idx"]],
                            slot_balls=slot_balls)
            chosen = set(rec["xi"])
            pools.append({"year": y, "team": t, "rows": rows, "sel": [i for i, p in enumerate(squad) if p.id in chosen],
                          "squad": squad, "base": base, "caps": snap[rec["idx"]], "date": rec["date"],
                          "xi": chosen, "rules": Rules(squad, fmt), "bmask": bowler_mask(squad, fmt)})
    return pools


def _solve(A: list[list[float]], b: list[float]) -> list[float]:
    n = len(b)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(M[r][c]))
        M[c], M[piv] = M[piv], M[c]
        for r in range(n):
            if r != c and M[c][c]:
                f = M[r][c] / M[c][c]
                M[r] = [x - f * y for x, y in zip(M[r], M[c])]
    return [M[i][n] / M[i][i] for i in range(n)]


NC = XI + 1          # balance terms c_0..c_11 follow beta in the parameter vector


def _pool_terms(p: dict, beta: list[float], c: list[float]):
    u = utilities(p["rows"], beta)
    top = max(u)
    w = [math.exp(x - top) for x in u]
    bi = [i for i in range(len(u)) if p["bmask"][i]]
    oi = [i for i in range(len(u)) if not p["bmask"][i]]
    eB, eO = esp([w[i] for i in bi]), esp([w[i] for i in oi])
    cm = max(c)
    term = [math.exp(c[j] - cm) * eB[j] * eO[XI - j] for j in range(NC)]
    Z = sum(term)
    return u, top, w, bi, oi, eB, eO, cm, term, Z


def loglik(pools: list[dict], params: list[float], derivs: bool = True):
    k = len(FEATURES)
    beta, c = params[:k], params[k:]
    K = k + NC
    ll = -0.5 * RIDGE * sum(x * x for x in params)
    g = [-RIDGE * x for x in params]
    H = [[RIDGE if i == j else 0.0 for j in range(K)] for i in range(K)]
    for p in pools:
        u, top, w, bi, oi, eB, eO, cm, term, Z = _pool_terms(p, beta, c)
        nb = sum(1 for i in p["sel"] if p["bmask"][i])
        ll += sum(u[i] - top for i in p["sel"]) + (c[nb] - cm) - math.log(Z)
        if not derivs:
            continue
        P = [t / Z for t in term]
        pi = [0.0] * len(u)
        for grp, other_e, is_b in ((bi, eO, True), (oi, eB, False)):
            ew = esp_without([w[i] for i in grp])
            for a, i in enumerate(grp):
                tot = 0.0
                for j in range(NC):
                    jb = j if is_b else XI - j          # members of i's group in the XI
                    if jb < 1:
                        continue
                    other = other_e[XI - j] if is_b else other_e[j]
                    tot += math.exp(c[j] - cm) * w[i] * ew[a][jb - 1] * other
                pi[i] = tot / Z
        for i in p["sel"]:
            for j in range(k):
                g[j] += p["rows"][i][j]
        g[k + nb] += 1.0
        for j in range(NC):
            g[k + j] -= P[j]
            H[k + j][k + j] += P[j] * (1 - P[j])
        for i, x in enumerate(p["rows"]):
            q = pi[i]
            for j in range(k):
                g[j] -= q * x[j]
            v = q * (1 - q)
            if v > 1e-9:
                for a in range(k):
                    va = v * x[a]
                    for b2 in range(a, k):
                        H[a][b2] += va * x[b2]
    if derivs:
        for a in range(k):
            for b2 in range(a):
                H[a][b2] = H[b2][a]
    return ll, g, H


def fit(pools: list[dict], iters: int = 80) -> list[float]:
    """Newton-type steps with an approximate curvature (independent Bernoulli for players, diagonal for the
    balance terms); longer and shorter steps are tried and the best kept on the exact likelihood."""
    params = [0.0] * (len(FEATURES) + NC)
    ll, g, H = loglik(pools, params)
    for it in range(iters):
        step = _solve(H, g)
        best = None
        for t in (0.25, 0.5, 1.0, 2.0, 4.0):
            nb = [b + t * s for b, s in zip(params, step)]
            nll = loglik(pools, nb, derivs=False)[0]
            if best is None or nll > best[0]:
                best = (nll, nb)
        nll, nb = best
        if nll <= ll:
            break
        gain = nll - ll
        params = nb
        ll, g, H = loglik(pools, params)
        print(f"  iteration {it + 1}: log-likelihood {ll:.1f} (+{gain:.2f})", flush=True)
        if gain < 0.01:
            break
    return params


def _comp(params: list[float], pools: list[dict]) -> dict:
    """Balance terms for the numbers of bowlers seen in real XIs (others are not allowed)."""
    seen = {sum(1 for i in p["sel"] if p["bmask"][i]) for p in pools}
    c = params[len(FEATURES):]
    return {str(j): round(c[j], 4) for j in sorted(seen)}


def evaluate(pools: list[dict], params: list[float], fmt: str, comp: dict) -> dict:
    """Real-XI players picked (of 11) by: the learned best valid XI (fitted weights, and with experience at the
    weight the engine uses), the old rule, caps alone; and genuine bowlers per XI, real v learned."""
    beta = params[:len(FEATURES)]
    half = [b * (EXPERIENCE_WEIGHT if f == "experience" else 1.0) for f, b in zip(FEATURES, beta)]
    hit = {"learned (fitted weights)": 0, f"learned (experience x{EXPERIENCE_WEIGHT})": 0, "old rule (select_xi)": 0,
           "caps only": 0}
    bowlers_real = bowlers_learned = 0
    for p in pools:
        sel = set(p["sel"])
        for name, b in (("learned (fitted weights)", beta), (f"learned (experience x{EXPERIENCE_WEIGHT})", half)):
            S = p["rules"].best_balanced(utilities(p["rows"], b), p["bmask"], comp)
            hit[name] += len(sel & set(S))
            if b is half:
                bowlers_learned += sum(1 for i in S if p["bmask"][i])
        bowlers_real += sum(1 for i in sel if p["bmask"][i])
        rule = {id(x) for x in rule_select_xi(p["squad"], fmt, p["base"], learned=False)}
        hit["old rule (select_xi)"] += sum(1 for i in sel if id(p["squad"][i]) in rule)
        bycaps = sorted(range(len(p["squad"])), key=lambda i: -p["caps"].get(p["squad"][i].id, 0))[:XI]
        hit["caps only"] += len(sel & set(bycaps))
    n = len(pools)
    out = {k: round(v / n, 2) for k, v in hit.items()}
    out["genuine bowlers per XI: real"] = round(bowlers_real / n, 2)
    out["genuine bowlers per XI: learned"] = round(bowlers_learned / n, 2)
    out["pools"] = n
    out["mean pool size"] = round(sum(len(p["rows"]) for p in pools) / n, 1)
    return out


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for fmt in ("odi", "t20"):
        print(f"{fmt}: reading matches...", flush=True)
        matches, vs, slot_balls = _matches(fmt)
        print(f"{fmt}: balls faced per match by batting position: {slot_balls}", flush=True)
        vspin = venue_spin_table(vs)
        pools = build_pools(fmt, matches, vspin, slot_balls)
        train = [p for p in pools if p["year"] <= TRAIN_UNTIL]
        test = [p for p in pools if p["year"] > TRAIN_UNTIL]
        print(f"{fmt}: {len(pools)} pools ({len(train)} train <= {TRAIN_UNTIL}, {len(test)} test)", flush=True)
        beta_tr = fit(train)
        val = evaluate(test, beta_tr, fmt, _comp(beta_tr, train))
        print(f"{fmt}: real-XI players picked (of 11), test {TRAIN_UNTIL + 1}+: {val}")
        params = fit(pools)
        beta = params[:len(FEATURES)]
        res = {"format": fmt, "features": list(FEATURES), "beta": [round(b, 4) for b in beta],
               "composition": _comp(params, pools), "balls_by_slot": slot_balls,
               "experience_weight_used": EXPERIENCE_WEIGHT,
               "window_days": WINDOW_DAYS, "first_year": FIRST_YEAR[fmt], "pools": len(pools),
               "validation": {"train_until": TRAIN_UNTIL, "test": val,
                              "beta_train": [round(b, 4) for b in beta_tr[:len(FEATURES)]]},
               "venue_spin": vspin}
        (OUT / f"selection_{fmt}.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
        print(f"{fmt}: beta " + ", ".join(f"{f} {b:+.2f}" for f, b in zip(FEATURES, beta)))
        print(f"{fmt}: balance terms by number of genuine bowlers: {res['composition']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
