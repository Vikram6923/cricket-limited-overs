"""Fit the Test XI-selection model (engine/test_selection.py) on real XIs.

Data: every Cricsheet Test between full members. For each side in each Test the candidates are everyone who
played for it within WINDOW_DAYS of the Test (a stand-in for the touring party, which is not recorded); the
chosen XI is the real one. Pools of fewer than 13 are skipped. Ratings are those of the years around the Test;
caps are Tests before it (with the Tests a player had before ball-by-ball coverage).

Host spin: the share of overs bowled by spin in Tests in the host country, less the share in all Tests.

The model and its fitting are those of limited overs (fit_selection.py: a conditional logit over XIs with a
balance term for the number of specialist bowlers, by maximum likelihood); only the features differ.

Mixes: the (fast bowlers, spinners) pairs among the specialist bowlers of at least MIX_SHARE of real XIs. The
balance term knows only how many bowlers an XI has; without the mixes the best XI for India at home had four
spinners and no fast bowler, which one real XI in a thousand has.

Validation: fit on Tests up to TRAIN_UNTIL, test on later ones: players of the real XI picked by the learned
model, by the rule it replaces (test_captain.select_xi) and by caps alone. Then refit on all and write
data/engine/selection_test.json.

    python -m engine.fit.fit_test_selection
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import date

from .. import test_captain, test_conditions
from ..conditions import venue_key
from ..data import baseline, player
from ..test_selection import EXPERIENCE_WEIGHT, FEATURES, XI, best_xi, bowler_mask, features, utilities
from . import fit_selection as fs
from . import fit_test_situation as fts
from .fit_basics import bowl_types

WINDOW_DAYS = 30             # a Test series runs longer than a one-day series (limited overs: 21)
MIN_POOL = 13
TRAIN_UNTIL = 2018
MIX_SHARE = 0.01
FULL = fs.FULL


def matches() -> tuple[list[dict], dict]:
    bt = bowl_types("test")
    out = []
    spin = defaultdict(lambda: [0, 0])            # host -> [spin overs, overs]
    for m in fts.iter_tests():
        info = m["info"]
        reg = info["registry"]["people"]
        xi = {t: [reg[n] for n in ps if n in reg] for t, ps in info.get("players", {}).items()}
        host = test_conditions.host_of(info.get("venue"))
        out.append({"date": info["dates"][0], "teams": info["teams"], "xi": xi, "host": host})
        for inn in m.get("innings", []):
            for ov in inn.get("overs", []):
                k = bt.get(reg.get(ov["deliveries"][0]["bowler"]))
                if k in ("spin", "pace"):
                    for key in (host, None):
                        spin[key][0] += k == "spin"
                        spin[key][1] += 1
    out.sort(key=lambda x: x["date"])
    overall = spin[None][0] / spin[None][1]
    host_spin = {h: round(a / n - overall, 4) for h, (a, n) in spin.items() if h and n >= 2000}
    return out, host_spin


def pre_caps() -> dict:
    """Tests a player had before ball-by-ball coverage."""
    p = fts.ROOT / "data" / "raw_stats" / "test_careers.json"
    t = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    return {pid: (q.get("pre") or {}).get("tests", 0) for pid, q in t.items() if q.get("pre")}


def build_pools(ms: list[dict], host_spin: dict) -> list[dict]:
    by_team = defaultdict(list)
    for idx, m in enumerate(ms):
        if all(t in FULL for t in m["teams"]):
            for t in m["teams"]:
                if len(m["xi"].get(t, [])) == XI:
                    by_team[t].append({"date": m["date"], "xi": m["xi"][t], "host": m["host"], "idx": idx})
    want = defaultdict(set)
    for t, recs in by_team.items():
        for rec in recs:
            d0 = date.fromisoformat(rec["date"])
            pool = set()
            for other in recs:
                if abs((date.fromisoformat(other["date"]) - d0).days) <= WINDOW_DAYS:
                    pool.update(other["xi"])
            rec["pool"] = sorted(pool)
            want[rec["idx"]].update(pool)
    count = defaultdict(int, pre_caps())
    snap = {}
    for i, m in enumerate(ms):
        if i in want:
            snap[i] = {pid: count[pid] for pid in want[i]}
        for ps in m["xi"].values():
            for pid in ps:
                count[pid] += 1
    pools, pcache = [], {}
    for t, recs in by_team.items():
        for rec in recs:
            if len(rec["pool"]) < MIN_POOL:
                continue
            y = int(rec["date"][:4])
            squad = []
            for pid in rec["pool"]:
                if (pid, y) not in pcache:
                    pcache[(pid, y)] = player("test", pid, years=(y - 1, y + 1))
                squad.append(pcache[(pid, y)])
            base = baseline("test", "test_full", y)
            chosen = set(rec["xi"])
            pools.append({"year": y, "team": t, "squad": squad, "caps": snap[rec["idx"]],
                          "rows": features(squad, base, host_spin.get(rec["host"], 0.0), snap[rec["idx"]]),
                          "sel": [i for i, p in enumerate(squad) if p.id in chosen], "bmask": bowler_mask(squad)})
    return pools


def spin_mask(p: dict) -> list[bool]:
    return [b and q.bowl_type == "spin" for b, q in zip(p["bmask"], p["squad"])]


def mixes(pools: list[dict]) -> list:
    c = defaultdict(int)
    for p in pools:
        sm = spin_mask(p)
        sel = [i for i in p["sel"] if p["bmask"][i]]
        c[(sum(not sm[i] for i in sel), sum(sm[i] for i in sel))] += 1
    return sorted([a, b] for (a, b), n in c.items() if n >= MIX_SHARE * len(pools))


def evaluate(pools: list[dict], params: list[float], comp: dict, mx: list) -> dict:
    beta = params[:len(FEATURES)]
    half = [b * (EXPERIENCE_WEIGHT if f == "experience" else 1.0) for f, b in zip(FEATURES, beta)]
    hit = defaultdict(int)
    real_b = learned_b = 0
    for p in pools:
        sel = set(p["sel"])
        kp = [q.keeper for q in p["squad"]]
        for name, b in (("learned (fitted weights)", beta), (f"learned (experience x{EXPERIENCE_WEIGHT})", half)):
            S = best_xi(utilities(p["rows"], b), p["bmask"], kp, comp, spin_mask(p), mx)
            hit[name] += len(sel & set(S))
            if b is half:
                learned_b += sum(p["bmask"][i] for i in S)
        real_b += sum(p["bmask"][i] for i in sel)
        rule = {q.id for q in test_captain.select_xi(p["squad"])}
        hit["the rule (select_xi)"] += sum(p["squad"][i].id in rule for i in sel)
        bycaps = sorted(range(len(p["squad"])), key=lambda i: -p["caps"].get(p["squad"][i].id, 0))[:XI]
        hit["caps only"] += len(sel & set(bycaps))
    n = len(pools)
    out = {k: round(v / n, 2) for k, v in hit.items()}
    out.update({"specialist bowlers per XI: real": round(real_b / n, 2),
                "specialist bowlers per XI: learned": round(learned_b / n, 2), "pools": n,
                "mean pool size": round(sum(len(p["rows"]) for p in pools) / n, 1)})
    return out


def main() -> int:
    fs.FEATURES = FEATURES           # the limited-overs fit reads its feature list from its module: give it ours
    ms, host_spin = matches()
    pools = build_pools(ms, host_spin)
    train = [p for p in pools if p["year"] <= TRAIN_UNTIL]
    test = [p for p in pools if p["year"] > TRAIN_UNTIL]
    print(f"{len(pools)} pools ({len(train)} train <= {TRAIN_UNTIL}, {len(test)} test); host spin {host_spin}", flush=True)
    p_tr = fs.fit(train)
    val = evaluate(test, p_tr, fs._comp(p_tr, train), mixes(train))
    print(f"real-XI players picked (of 11), Tests after {TRAIN_UNTIL}: {val}")
    params = fs.fit(pools)
    beta = params[:len(FEATURES)]
    res = {"format": "test", "features": list(FEATURES), "beta": [round(b, 4) for b in beta],
           "composition": fs._comp(params, pools), "experience_weight_used": EXPERIENCE_WEIGHT,
           "window_days": WINDOW_DAYS, "pools": len(pools), "host_spin": host_spin, "mixes": mixes(pools),
           "validation": {"train_until": TRAIN_UNTIL, "test": val,
                          "beta_train": [round(b, 4) for b in p_tr[:len(FEATURES)]]}}
    (fts.OUT / "selection_test.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    print("beta " + ", ".join(f"{f} {b:+.3f}" for f, b in zip(FEATURES, beta)))
    print(f"balance by number of specialist bowlers: {res['composition']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
