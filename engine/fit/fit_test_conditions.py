"""Test conditions fitted from the ball-by-ball data alone (docs/test_match_plan.md section 3; Phase 3).

    python -m engine.fit.fit_test_conditions      -> data/engine/test_conditions.json, spin_test.json   (~40 s)

hosts     venue -> the country whose ground it is: the side that has played the most Tests there, when one side
          is alone at the top (a neutral ground has no host).
weather   overs lost in a day (rain, bad light and slow over rates are one quantity: Cricsheet has no clock), as
          a distribution in steps of 5 overs, pooled and by host. A match gives only its total: scheduled overs
          minus overs bowled minus 2 for each change of innings. A draw used all its days, so its total loss is
          known; a decided match ended at an unknown point of its last day, so its loss over the earlier days is
          known to within that day's overs, taken as equally likely from 1 to 90. The daily distribution is the
          maximum-likelihood one for those totals (EM over the sum of n days). Rain runs over neighbouring days,
          so there are two kinds of match, dry and wet, each with its own daily distribution; days are
          independent within a kind. A host has its own share of wet matches.
          A draw may be agreed in the last hour, so 0 to 15 of a draw's unused overs are taken as not lost.
          This is an estimate: time made up on later days is counted as loss avoided.
home      how much better the home side bats than its ratings say, against the visitors: observed / predicted
          runs and wickets per ball when the home side bats, over the same when the visitors bat.
spin      spin's edge over pace at each ground and its day-to-day spread, as engine/fit/fit_spin.py does for
          limited overs (same estimator, all innings of the match).
"""
from __future__ import annotations

import json
import math
import sys
from collections import Counter, defaultdict

from ..conditions import venue_key
from .fit_basics import bowl_types
from .fit_spin import fit_metric
from .fit_test_situation import BOWLER_WICKETS, OUT, is_draw, iter_tests, load_ratings, match_overs

STEP = 5                       # overs: the grid of a day's loss
DAY = 90
NK = DAY // STEP + 1           # 0, 5, ..., 90
LAST_HOUR = 15                 # overs: the last hour of a match, in which a draw may be agreed (playing conditions)
CHANGE = 2                     # overs lost at a change of innings (engine/test_match.py CHANGE_OVERS)
PRIOR_MATCHES = 20             # a host's share of wet matches is shrunk toward the pooled one with this many
MIN_HOST_MATCHES = 15          # hosts with fewer Tests use the pooled distribution
MIN_SPIN_BALLS = 300           # a match needs this many balls of spin and of pace to give a spin edge


# ---------------------------------------------------------------------- hosts
def fit_hosts(matches: list) -> dict:
    by = defaultdict(Counter)
    for m in matches:
        by[venue_key(m["info"].get("venue"))].update(m["info"]["teams"])
    out = {}
    for v, c in by.items():
        top = c.most_common(2)
        if v and top[0][1] >= 2 and (len(top) == 1 or top[0][1] > top[1][1]):
            out[v] = top[0][0]
    return dict(sorted(out.items()))


# ---------------------------------------------------------------------- weather
def conv(a: list, b: list) -> list:
    out = [0.0] * (len(a) + len(b) - 1)
    for i, x in enumerate(a):
        if x:
            for j, y in enumerate(b):
                out[i + j] += x * y
    return out


def loss_rows(matches: list, hosts: dict) -> list:
    """(host, full days n, [candidate total losses in grid steps]) per match."""
    rows = []
    for m in matches:
        info = m["info"]
        inns = [i for i in m.get("innings", []) if i.get("overs")]
        days = len(info["dates"])
        if not inns or days > 5:
            continue
        used = match_overs(m) + CHANGE * (len(inns) - 1)
        host = hosts.get(venue_key(info.get("venue")))
        if is_draw(m):
            # a draw may be agreed once the last hour (15 overs) has begun: 0..15 of its unused overs were not
            # lost to anything, equally likely
            cand = Counter(max(0, round((days * DAY - used - h) / STEP)) for h in range(LAST_HOUR + 1))
            rows.append((host, days, sorted(cand.items())))
        elif days >= 2:
            n = days - 1
            cand = Counter()
            for x in range(1, DAY + 1):             # overs bowled on the last day: unknown, 1..90 equally likely
                lost = n * DAY + x - used
                if lost >= 0:
                    cand[min(round(lost / STEP), n * (NK - 1))] += 1
            rows.append((host, n, sorted(cand.items()) if cand else [(0, 1)]))
    return rows


def powers(p: list) -> list:
    pw = [[1.0]]
    for _n in range(5):
        pw.append(conv(pw[-1], p))
    return pw


def match_like(pw: list, n: int, cands: list) -> tuple[float, list]:
    """Likelihood of a match's candidate totals under a daily distribution (its powers), and each candidate's."""
    like = [(c, w * (pw[n][c] if c < len(pw[n]) else 0.0)) for c, w in cands]
    return sum(v for _, v in like), like


def day_counts(cnt: list, weight: float, p: list, pw: list, n: int, like: list, z: float) -> None:
    """Add to cnt the expected number of days with each loss, for one match (posterior given its total)."""
    rest = pw[n - 1]
    for c, v in like:
        if v <= 0:
            continue
        for k in range(NK):
            j = c - k
            if 0 <= j < len(rest) and p[k] and rest[j]:
                cnt[k] += weight * (v / z) * n * p[k] * rest[j] / pw[n][c]


def em(rows: list, rounds: int = 400) -> dict:
    """Two kinds of match, dry and wet (rain runs over neighbouring days, so days are independent only within
    a kind): the share of wet matches and each kind's distribution of a day's loss."""
    dry = [0.6] + [0.4 / (NK - 1)] * (NK - 1)
    wet = [0.2] + [0.8 / (NK - 1)] * (NK - 1)
    share = 0.3
    for _ in range(rounds):
        pd, pw = powers(dry), powers(wet)
        cd, cw, r_sum = [0.0] * NK, [0.0] * NK, 0.0
        for _h, n, cands in rows:
            zd, ld = match_like(pd, n, cands)
            zw, lw = match_like(pw, n, cands)
            tot = (1 - share) * zd + share * zw
            if tot <= 0:
                continue
            r = share * zw / tot
            r_sum += r
            if zd > 0:
                day_counts(cd, 1 - r, dry, pd, n, ld, zd)
            if zw > 0:
                day_counts(cw, r, wet, pw, n, lw, zw)
        nd, nw = [x / sum(cd) for x in cd], [x / sum(cw) for x in cw]
        ns = r_sum / len(rows)
        delta = max(max(abs(a - b) for a, b in zip(nd, dry)), max(abs(a - b) for a, b in zip(nw, wet)), abs(ns - share))
        dry, wet, share = nd, nw, ns
        if delta < 1e-7:
            break
    return {"dry": dry, "wet": wet, "share": share}


def wet_share(rows: list, fit: dict) -> float:
    """A host's share of wet matches (the two kinds' distributions stay the pooled ones), shrunk toward the
    pooled share with PRIOR_MATCHES matches."""
    pd, pw = powers(fit["dry"]), powers(fit["wet"])
    share = fit["share"]
    for _ in range(200):
        r_sum = PRIOR_MATCHES * fit["share"]
        for _h, n, cands in rows:
            zd, zw = match_like(pd, n, cands)[0], match_like(pw, n, cands)[0]
            tot = (1 - share) * zd + share * zw
            r_sum += share * zw / tot if tot > 0 else share
        share = r_sum / (len(rows) + PRIOR_MATCHES)
    return share


def fit_weather(matches: list, hosts: dict) -> dict:
    rows = loss_rows(matches, hosts)
    fit = em(rows)
    mean = lambda p: sum(k * STEP * x for k, x in enumerate(p))        # noqa: E731
    by = defaultdict(list)
    for r in rows:
        if r[0]:
            by[r[0]].append(r)
    out = {"step": STEP, "matches": len(rows), "dry": [round(x, 5) for x in fit["dry"]],
           "wet": [round(x, 5) for x in fit["wet"]], "wet_share": round(fit["share"], 4),
           "mean_dry": round(mean(fit["dry"]), 2), "mean_wet": round(mean(fit["wet"]), 2),
           "wet_share_by_host": {}, "matches_by_host": {}}
    for h, rs in sorted(by.items()):
        if len(rs) >= MIN_HOST_MATCHES:
            out["wet_share_by_host"][h] = round(wet_share(rs, fit), 4)
            out["matches_by_host"][h] = len(rs)
    return out


# ---------------------------------------------------------------------- home edge and spin edge (ball level)
def fit_ball_level(matches: list, hosts: dict) -> tuple[dict, dict]:
    base, bat, bowl, _ = load_ratings()
    btype = bowl_types("test")
    home = {"home": [0.0] * 4, "away": [0.0] * 4}           # O runs, E runs, O wkts, E wkts
    by_host = defaultdict(lambda: {"home": [0.0] * 4, "away": [0.0] * 4})
    n_home = 0
    spin_rows = []
    for m in matches:
        info = m["info"]
        b0 = (base.get(info["dates"][0][:4]) or {}).get("all")
        if not b0:
            continue
        reg = info["registry"]["people"]
        host = hosts.get(venue_key(info.get("venue")))
        hosted = host in info["teams"]
        n_home += hosted
        acc = {k: [0.0, 0.0, 0.0, 0.0, 0.0, 0] for k in ("spin", "pace")}   # O runs, E runs, var, O wkt, E wkt, balls
        var = max(b0["runs_sq"] - b0["runs"] ** 2, 0.1)
        for inn in m.get("innings", []):
            side = "home" if inn["team"] == host else "away"
            for ov in inn.get("overs", []):
                for d in ov["deliveries"]:
                    ex = d.get("extras", {})
                    if "wides" in ex or "noballs" in ex:
                        continue
                    bid, wid = reg.get(d["batter"]), reg.get(d["bowler"])
                    if bid not in bat or wid not in bowl:
                        continue
                    e_r = b0["runs"] * bat[bid]["runs"] * bowl[wid]["runs"]
                    e_w = b0["wkt"] * bat[bid]["wkt"] * bowl[wid]["wkt"]
                    o_r = d["runs"]["batter"]
                    o_w = sum(1 for w in d.get("wickets", []) if w["kind"] in BOWLER_WICKETS)
                    if hosted:
                        for h in (home[side], by_host[host][side]):
                            h[0] += o_r
                            h[1] += e_r
                            h[2] += o_w
                            h[3] += e_w
                    t = btype.get(wid)
                    if t in acc:
                        a = acc[t]
                        a[0] += o_r
                        a[1] += e_r
                        a[2] += var
                        a[3] += o_w
                        a[4] += e_w
                        a[5] += 1
        s, p = acc["spin"], acc["pace"]
        if s[5] >= MIN_SPIN_BALLS and p[5] >= MIN_SPIN_BALLS:
            spin_rows.append({
                "venue": venue_key(info.get("venue")),
                "d_runs": math.log((s[0] + 1) / (s[1] + 1)) - math.log((p[0] + 1) / (p[1] + 1)),
                "n_runs": s[2] / s[1] ** 2 + p[2] / p[1] ** 2,
                "d_wkt": math.log((s[3] + 0.5) / (s[4] + 0.5)) - math.log((p[3] + 0.5) / (p[4] + 0.5)),
                "n_wkt": 1 / (s[4] + 0.5) + 1 / (p[4] + 0.5),
                "spin_share": s[5] / (s[5] + p[5]),
            })

    def edge(h):
        a, b = h["home"], h["away"]
        return {"runs": round(math.log(a[0] / a[1]) - math.log(b[0] / b[1]), 4),
                "wkt": round(math.log(a[2] / a[3]) - math.log(b[2] / b[3]), 4)}
    home_out = {"matches": n_home, **edge(home),
                "by_host": {h: edge(v) for h, v in sorted(by_host.items()) if v["home"][3] > 150 and v["away"][3] > 150}}

    res = {k: fit_metric(spin_rows, k) for k in ("runs", "wkt")}
    venues = {}
    for v in res["runs"][0]:
        (er, n), (ew, _) = res["runs"][0][v], res["wkt"][0][v]
        venues[v] = {"runs": round(er, 4), "wkt": round(ew, 4), "n": n}
    share = sum(r["spin_share"] for r in spin_rows) / len(spin_rows)
    spin = {"venues": venues, "spin_share": round(share, 3),
            "day": {"sd_runs": round(math.sqrt(res["runs"][2]), 4), "sd_wkt": round(math.sqrt(res["wkt"][2]), 4)},
            "between_venue_sd": {"runs": round(math.sqrt(res["runs"][1]), 4),
                                 "wkt": round(math.sqrt(res["wkt"][1]), 4)},
            "overall": {"runs": round(res["runs"][3], 4), "wkt": round(res["wkt"][3], 4)},
            "matches": len(spin_rows)}
    return home_out, spin


def main(argv=None) -> int:
    matches = list(iter_tests())
    hosts = fit_hosts(matches)
    weather = fit_weather(matches, hosts)
    home, spin = fit_ball_level(matches, hosts)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "test_conditions.json").write_text(
        json.dumps({"matches": len(matches), "hosts": hosts, "weather": weather, "home": home}, indent=1),
        encoding="utf-8")
    (OUT / "spin_test.json").write_text(json.dumps(spin), encoding="utf-8")
    print(f"{len(matches)} Tests; {len(hosts)} grounds with a host")
    print("overs lost in a day (0, 5, ..., 90), dry matches:", [round(x, 3) for x in weather["dry"]])
    print("                                    wet matches:", [round(x, 3) for x in weather["wet"]])
    print(f"  mean a day: dry {weather['mean_dry']}, wet {weather['mean_wet']}; wet share {weather['wet_share']}; "
          f"by host: {weather['wet_share_by_host']}")
    print("home edge (log):", {k: home[k] for k in ("runs", "wkt")}, f"from {home['matches']} Tests")
    print("  by host:", home["by_host"])
    top = sorted(((v["wkt"], k, v["n"]) for k, v in spin["venues"].items() if v["n"] >= 8), reverse=True)
    print(f"spin edge: {spin['matches']} Tests; spin share {spin['spin_share']}; between-venue sd "
          f"{spin['between_venue_sd']}; day sd {spin['day']}; overall {spin['overall']}")
    print("   most spin-friendly (wickets):", [(k, round(w, 2), n) for w, k, n in top[:6]])
    print("   most pace-friendly (wickets):", [(k, round(w, 2), n) for w, k, n in top[-6:]])
    return 0


if __name__ == "__main__":
    sys.exit(main())
