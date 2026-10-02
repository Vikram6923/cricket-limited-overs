"""Venue factors (design T2-3) and day-to-day pitch variation (T2-4), fitted with the engine itself.

Every real match since 2012 is replayed REPS times (real XIs, batting order, toss, competition, year) with the
Tier 1 engine only (no venue, pitch or matchup effects). Per match:
    residual = log(actual rate / simulated rate)   for runs per ball and wickets per ball, both innings together
  * venue factor   = mean residual of the venue's matches, shrunk (empirical Bayes) toward 0
  * pitch variance = within-venue residual variance minus the engine's own replay-to-replay variance, per
                     competition (this is the method that was last calibrated; see docs/engine_progress.md)
The runs/wickets correlation of the pitch term is kept.

Writes data/engine/venues_{t20,odi}.json.   Run:  python -m engine.fit.fit_venues
Replays are cached in data/cache/venue_rows_<fmt>.json; delete that file to replay again.
"""
from __future__ import annotations

import json
import math
import sys
import zipfile
import zlib
from collections import defaultdict
from pathlib import Path

from ..conditions import venue_key
from ..match import simulate_match

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "engine"
FULL = {"Afghanistan", "Australia", "Bangladesh", "England", "India", "Ireland", "New Zealand", "Pakistan",
        "South Africa", "Sri Lanka", "West Indies", "Zimbabwe"}
REPS = 3
FIRST_YEAR = 2012
SOURCES = {"t20": [("t20i", "t20s_male_json.zip")] + [(c, f"leagues/{c}_json.zip") for c in
                                                       ("ipl", "bbl", "psl", "cpl", "sat", "ilt", "bpl", "lpl",
                                                        "mlc", "ntb", "ssm")],
           "odi": [("odi", "odis_male_json.zip")]}
OVERS = {"t20": 20, "odi": 50}


def seed_for(match_id: str, rep: int) -> int:
    """Deterministic across runs (Python's hash() is randomised per process)."""
    return zlib.crc32(f"{match_id}|{rep}".encode()) & 0x7FFFFFFF


def real_matches(fmt: str):
    for comp, z in SOURCES[fmt]:
        if not (RAW / z).exists():
            continue
        with zipfile.ZipFile(RAW / z) as zf:
            for n in sorted(zf.namelist()):
                if not n.endswith(".json"):
                    continue
                m = json.loads(zf.read(n))
                info = m["info"]
                yr = int(info["dates"][0][:4])
                if info.get("gender") != "male" or yr < FIRST_YEAR or info.get("balls_per_over", 6) != 6:
                    continue
                oc = info.get("outcome", {})
                if "method" in oc or oc.get("result") == "no result" or info.get("overs") != OVERS[fmt]:
                    continue
                inns = [i for i in m.get("innings", []) if not i.get("super_over")]
                if len(inns) != 2 or (inns[1].get("target") or {}).get("overs", OVERS[fmt]) != OVERS[fmt]:
                    continue
                if comp in ("t20i", "odi"):
                    c = f"{comp}_full" if all(t in FULL for t in info["teams"]) else comp
                else:
                    c = comp
                yield c, yr, n, m


def match_spec(m: dict):
    info = m["info"]
    reg = info["registry"]["people"]
    inns = [i for i in m["innings"] if not i.get("super_over")]
    order = {}
    runs = wk = balls = 0
    for inn in inns:
        seen = []
        for ov in inn["overs"]:
            for d in ov["deliveries"]:
                for nm in (d["batter"], d["non_striker"]):
                    if nm not in seen:
                        seen.append(nm)
                ex = d.get("extras", {})
                runs += d["runs"]["total"]
                if "wides" not in ex and "noballs" not in ex:
                    balls += 1
                wk += sum(1 for w in d.get("wickets", []) if w["kind"] not in ("retired hurt", "retired not out"))
        order[inn["team"]] = [reg[x] for x in seen]
    teams = info["teams"]
    specs = [{"name": t, "players": [reg[x] for x in info["players"][t]], "order": order.get(t, [])} for t in teams]
    first = inns[0]["team"]
    tw = info.get("toss", {}).get("winner")
    return specs, ("a" if tw == teams[0] else "b"), ("bat" if tw == first else "bowl"), (runs, wk, balls)


def replay_rows(fmt: str) -> tuple[list, dict]:
    """Per-match residuals: (venue key, competition, run resid, wkt resid, engine var runs, engine var wkts)."""
    cache = ROOT / "data" / "cache" / f"venue_rows_{fmt}.json"
    if cache.exists():
        d = json.loads(cache.read_text(encoding="utf-8"))
        if d.get("method") == "match_total":
            return [tuple(r) for r in d["rows"]], d["names"]
    rows, names = [], {}
    n = 0
    for comp, yr, mid, m in real_matches(fmt):
        try:
            specs, toss, dec, (ar, aw, ab) = match_spec(m)
        except KeyError:
            continue
        if ab == 0:
            continue
        lr, lw = [], []
        for rep in range(REPS):
            c = simulate_match(specs[0], specs[1], fmt=fmt, comp=comp, year=yr, seed=seed_for(mid, rep),
                               toss=toss, decision=dec, use_venue=False, use_pitch=False, use_matchups=False)
            sb = sum(i["balls"] for i in c["innings"]) or 1
            lr.append(math.log(max(sum(i["runs"] for i in c["innings"]), 1) / sb))
            lw.append(math.log((sum(i["wickets"] for i in c["innings"]) + 0.5) / sb))
        mr, mw = sum(lr) / REPS, sum(lw) / REPS
        vr = sum((x - mr) ** 2 for x in lr) / (REPS - 1)
        vw = sum((x - mw) ** 2 for x in lw) / (REPS - 1)
        key = venue_key(m["info"].get("venue", ""))
        names.setdefault(key, m["info"].get("venue", ""))
        rows.append((key, comp, math.log(max(ar, 1) / ab) - mr, math.log((aw + 0.5) / ab) - mw, vr, vw))
        n += 1
        if n % 1000 == 0:
            print(f"  {fmt}: {n} matches replayed", flush=True)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"method": "match_total", "rows": rows, "names": names}), encoding="utf-8")
    return rows, names


def pitch_params(rows: list) -> dict:
    """Within-venue residual (co)variance minus the engine's own replay-to-replay variance."""
    by = defaultdict(list)
    for k, comp, a, b, vr, vw in rows:
        by[k].append((a, b))
    sim_vr = sum(r[4] for r in rows) / len(rows)
    sim_vw = sum(r[5] for r in rows) / len(rows)
    wr = wv = wc = 0.0
    dof = 0
    for xs in by.values():
        if len(xs) < 3:
            continue
        ma = sum(x[0] for x in xs) / len(xs)
        mb = sum(x[1] for x in xs) / len(xs)
        wr += sum((x[0] - ma) ** 2 for x in xs)
        wv += sum((x[1] - mb) ** 2 for x in xs)
        wc += sum((x[0] - ma) * (x[1] - mb) for x in xs)
        dof += len(xs) - 1
    if dof < 30:
        return {}
    r, w, c = wr / dof, wv / dof, wc / dof
    return {"sd_runs": round(math.sqrt(max(r - sim_vr, 0.0)), 4), "sd_wkt": round(math.sqrt(max(w - sim_vw, 0.0)), 4),
            "corr": round(c / math.sqrt(r * w), 3) if r > 0 and w > 0 else 0.0, "matches": dof}


def fit(fmt: str) -> dict:
    rows, names = replay_rows(fmt)
    cr = sum(r[2] for r in rows) / len(rows)
    cw = sum(r[3] for r in rows) / len(rows)
    rows = [(k, comp, a - cr, b - cw, vr, vw) for k, comp, a, b, vr, vw in rows]
    per_comp = {}
    for comp in sorted({r[1] for r in rows}):
        pp = pitch_params([r for r in rows if r[1] == comp])
        if pp:
            per_comp[comp] = pp
    pooled = pitch_params(rows)
    by = defaultdict(list)
    for k, comp, a, b, vr, vw in rows:
        by[k].append((a, b))
    wr = wv = 0.0
    dof = 0
    for xs in by.values():
        if len(xs) < 5:
            continue
        ma = sum(x[0] for x in xs) / len(xs)
        mb = sum(x[1] for x in xs) / len(xs)
        wr += sum((x[0] - ma) ** 2 for x in xs)
        wv += sum((x[1] - mb) ** 2 for x in xs)
        dof += len(xs) - 1
    within_r, within_w = wr / dof, wv / dof
    big = [xs for xs in by.values() if len(xs) >= 5]
    means_r = [sum(x[0] for x in xs) / len(xs) for xs in big]
    means_w = [sum(x[1] for x in xs) / len(xs) for xs in big]
    noise_r = sum(within_r / len(xs) for xs in big) / len(big)
    noise_w = sum(within_w / len(xs) for xs in big) / len(big)
    tau_r = max(sum(v * v for v in means_r) / len(means_r) - noise_r, 1e-5)
    tau_w = max(sum(v * v for v in means_w) / len(means_w) - noise_w, 1e-5)
    venues = {}
    for k, xs in by.items():
        nn = len(xs)
        ma = sum(x[0] for x in xs) / nn
        mb = sum(x[1] for x in xs) / nn
        sr = tau_r / (tau_r + within_r / nn)
        sw = tau_w / (tau_w + within_w / nn)
        venues[k] = {"name": names[k], "matches": nn, "runs": round(math.exp(sr * ma), 4),
                     "wkt": round(math.exp(sw * mb), 4)}
    return {"format": fmt, "matches": len(rows), "reps": REPS, "method": "match_total",
            "venue_sd": {"runs": round(math.sqrt(tau_r), 4), "wkt": round(math.sqrt(tau_w), 4)},
            "pitch": pooled, "pitch_by_comp": per_comp,
            "venues": dict(sorted(venues.items(), key=lambda kv: -kv[1]["matches"]))}


def main(argv=None) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    fmts = (argv or sys.argv[1:]) or ["t20", "odi"]
    for fmt in fmts:
        res = fit(fmt)
        (OUT / f"venues_{fmt}.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
        v = res["venues"]
        top = sorted((x for x in v.values() if x["matches"] >= 15), key=lambda x: -x["runs"])
        print(f"{fmt}: {res['matches']} matches; venue SD {res['venue_sd']}; pitch {res['pitch']}")
        for c, pp in res["pitch_by_comp"].items():
            print(f"   pitch {c:10} {pp}")
        print("   highest scoring:", [(x["name"].split(",")[0], x["runs"], x["matches"]) for x in top[:5]])
        print("   lowest scoring: ", [(x["name"].split(",")[0], x["runs"], x["matches"]) for x in top[-5:]])
    return 0


if __name__ == "__main__":
    sys.exit(main())
