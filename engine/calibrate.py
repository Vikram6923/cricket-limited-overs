"""Calibration by replaying real fixtures (design T0-6).

Every selected real match is re-simulated K times with its real XIs, real batting order, real toss, competition and
year. Simulated and real distributions are then compared: totals, wickets, phase run rates, boundaries, extras,
individual scores, chase success. Rain-reduced and no-result matches are skipped.

    python -m engine.calibrate                       # all suites, 4 replays per fixture
    python -m engine.calibrate --suite t20i --reps 10
Writes data/engine/calibration_<suite>.json (history of results, newest last).
"""
from __future__ import annotations

import argparse
import json
import statistics as st
import sys
import time
import zipfile
import zlib
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from .data import FORMATS, phase_of
from .match import simulate_match

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "engine"
FULL = {"Afghanistan", "Australia", "Bangladesh", "England", "India", "Ireland", "New Zealand", "Pakistan",
        "South Africa", "Sri Lanka", "West Indies", "Zimbabwe"}

SUITES = {
    "t20i": {"fmt": "t20", "zip": "t20s_male_json.zip", "comp": "t20i_full", "years": (2021, 2026), "full": True},
    "ipl": {"fmt": "t20", "zip": "leagues/ipl_json.zip", "comp": "ipl", "years": (2022, 2026), "full": False},
    "odi": {"fmt": "odi", "zip": "odis_male_json.zip", "comp": "odi_full", "years": (2015, 2026), "full": True},
}


def fixtures(suite: dict) -> list[dict]:
    """Real matches as replay specs plus their real summary stats."""
    out = []
    fmt = suite["fmt"]
    overs = FORMATS[fmt]["overs"]
    with zipfile.ZipFile(RAW / suite["zip"]) as zf:
        for n in sorted(zf.namelist()):
            if not n.endswith(".json"):
                continue
            m = json.loads(zf.read(n))
            info = m["info"]
            yr = int(info["dates"][0][:4])
            if info.get("gender") != "male" or not (suite["years"][0] <= yr <= suite["years"][1]):
                continue
            if suite["full"] and not all(t in FULL for t in info["teams"]):
                continue
            oc = info.get("outcome", {})
            if "method" in oc or oc.get("result") == "no result" or info.get("overs", overs) != overs:
                continue
            inns = [i for i in m.get("innings", []) if not i.get("super_over")]
            if len(inns) != 2 or (inns[1].get("target") or {}).get("overs", overs) != overs:
                continue
            reg = info["registry"]["people"]
            order = {}
            for inn in inns:
                seen = []
                for ov in inn["overs"]:
                    for d in ov["deliveries"]:
                        for nm in (d["batter"], d["non_striker"]):
                            if nm not in seen:
                                seen.append(nm)
                order[inn["team"]] = [reg[x] for x in seen]
            teams = info["teams"]
            specs = []
            for t in teams:
                ids = [reg[x] for x in info["players"][t]]
                specs.append({"name": t, "players": ids, "order": order.get(t, [])})
            tw = info.get("toss", {}).get("winner")
            dec = info.get("toss", {}).get("decision")
            # replay the real batting order of the innings (who batted first), whatever the toss said
            first = inns[0]["team"]
            toss = "a" if tw == teams[0] else "b"
            decision = "bat" if (tw == first) else "bowl"
            out.append({"id": n, "year": yr, "a": specs[0], "b": specs[1], "toss": toss, "decision": decision,
                        "venue": info.get("venue"),
                        "real": summarize_real(inns, reg, fmt, oc, first)})
    return out


def summarize_real(inns: list, reg: dict, fmt: str, oc: dict, first: str) -> dict:
    res = []
    for k, inn in enumerate(inns):
        s = new_summary()
        bat_scores = defaultdict(lambda: [0, 0, False])
        for ov in inn["overs"]:
            ph = phase_of(ov["over"], fmt)
            for d in ov["deliveries"]:
                ex = d.get("extras", {})
                s["runs"] += d["runs"]["total"]
                s["ph_runs"][ph] += d["runs"]["total"]
                if "wides" not in ex and "noballs" not in ex:
                    s["balls"] += 1
                    s["ph_balls"][ph] += 1
                s["extras"] += d["runs"]["extras"]
                br = d["runs"]["batter"]
                if br == 4 and not d["runs"].get("non_boundary"):
                    s["fours"] += 1
                if br == 6:
                    s["sixes"] += 1
                if "wides" not in ex:
                    b = bat_scores[d["batter"]]
                    b[0] += br
                    b[1] += 1
                for w in d.get("wickets", []):
                    if w["kind"] in ("retired hurt", "retired not out"):
                        continue
                    s["wkts"] += 1
                    s["ph_wkts"][ph] += 1
                    bat_scores[w["player_out"]][2] = True
        s["scores"] = [(r, b, o) for r, b, o in bat_scores.values()]
        res.append(s)
    winner = oc.get("winner")
    second = inns[1]["team"]
    res[1]["chase_won"] = winner == second if winner else None
    return {"inns": res}


def new_summary() -> dict:
    return {"runs": 0, "wkts": 0, "balls": 0, "extras": 0, "fours": 0, "sixes": 0,
            "ph_runs": defaultdict(int), "ph_wkts": defaultdict(int), "ph_balls": defaultdict(int)}


def summarize_sim(card: dict, fmt: str) -> dict:
    res = []
    for i in card["innings"]:
        s = new_summary()
        s["runs"], s["wkts"], s["balls"] = i["runs"], i["wickets"], i["balls"]
        s["extras"] = sum(i["extras"].values())
        s["fours"] = sum(b["fours"] for b in i["batting"])
        s["sixes"] = sum(b["sixes"] for b in i["batting"])
        cum_w = 0
        for o in i["overs_log"]:
            ph = phase_of(o["over"] - 1, fmt)
            s["ph_runs"][ph] += o["runs"]
            s["ph_wkts"][ph] += o["wkts"]
            s["ph_balls"][ph] += 6
        last = i["overs_log"][-1] if i["overs_log"] else None
        if last and i["balls"] % 6:
            s["ph_balls"][phase_of(last["over"] - 1, fmt)] -= 6 - i["balls"] % 6
        s["scores"] = [(b["runs"], b["balls"], b["out"]) for b in i["batting"] if b["batted"]]
        res.append(s)
    w = card["result"].get("winner")
    res[1]["chase_won"] = (w == card["innings"][1]["team"]) if w else None
    return {"inns": res}


def aggregate(summaries: list[dict], fmt: str) -> dict:
    a = {}
    for k, label in ((0, "1st"), (1, "2nd")):
        xs = [s["inns"][k] for s in summaries]
        runs = [x["runs"] for x in xs]
        a[f"{label} inns runs mean"] = st.mean(runs)
        a[f"{label} inns runs sd"] = st.pstdev(runs)
        a[f"{label} inns wkts"] = st.mean(x["wkts"] for x in xs)
        if k == 0:
            q = sorted(runs)
            a["1st inns runs p10"] = q[len(q) // 10]
            a["1st inns runs p90"] = q[9 * len(q) // 10]
            a["1st inns all out %"] = 100 * sum(x["wkts"] >= 10 for x in xs) / len(xs)
    xs = [s["inns"][0] for s in summaries]
    for ph in ("powerplay", "middle", "death"):
        b = sum(x["ph_balls"][ph] for x in xs)
        a[f"1st inns {ph} RPO"] = 6 * sum(x["ph_runs"][ph] for x in xs) / b if b else 0
        a[f"1st inns {ph} wkts"] = sum(x["ph_wkts"][ph] for x in xs) / len(xs)
    allx = [s["inns"][k] for s in summaries for k in (0, 1)]
    a["fours per inns"] = st.mean(x["fours"] for x in allx)
    a["sixes per inns"] = st.mean(x["sixes"] for x in allx)
    a["extras per inns"] = st.mean(x["extras"] for x in allx)
    scores = [sc for x in allx for sc in x["scores"]]
    n_inn = len(allx)
    a["50+ scores per inns"] = sum(r >= 50 for r, b, o in scores) / n_inn
    a["100+ scores per inns"] = sum(r >= 100 for r, b, o in scores) / n_inn
    a["ducks per inns"] = sum(r == 0 and o for r, b, o in scores) / n_inn
    cw = [s["inns"][1]["chase_won"] for s in summaries if s["inns"][1]["chase_won"] is not None]
    a["chase won %"] = 100 * sum(cw) / len(cw) if cw else 0
    return a


def seed_for(match_id: str, rep: int) -> int:
    """Deterministic across runs (Python's hash() is randomised per process)."""
    return zlib.crc32(f"{match_id}|{rep}".encode()) & 0x7FFFFFFF


def run_suite(name: str, reps: int, limit: int | None, flags: dict, label: str) -> dict:
    suite = SUITES[name]
    fmt = suite["fmt"]
    fx = fixtures(suite)
    if limit:
        fx = fx[-limit:]
    t = time.time()
    sims = []
    for f in fx:
        for r in range(reps):
            card = simulate_match(f["a"], f["b"], fmt=fmt, comp=suite["comp"], year=f["year"],
                                  seed=seed_for(f["id"], r), toss=f["toss"], decision=f["decision"],
                                  venue=f["venue"], **flags)
            sims.append(summarize_sim(card, fmt))
    real = aggregate([f["real"] for f in fx], fmt)
    sim = aggregate(sims, fmt)
    print(f"\n=== {name} [{label}]: {len(fx)} real matches ({suite['years'][0]}-{suite['years'][1]}), "
          f"{len(sims)} simulations in {time.time() - t:.0f}s")
    print(f"   {'':30}{'real':>9}{'sim':>9}{'diff':>9}")
    for k in real:
        r, s = real[k], sim[k]
        d = (s / r - 1) * 100 if r else 0
        flag = "  <--" if abs(d) > 10 and not k.endswith("%") else ("  <--" if k.endswith("%") and abs(s - r) > 5 else "")
        print(f"   {k:30}{r:9.2f}{s:9.2f}{d:8.1f}%{flag}")
    rec = {"when": datetime.now().isoformat(timespec="seconds"), "suite": name, "label": label,
           "flags": flags, "fixtures": len(fx), "reps": reps, "real": real, "sim": sim}
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"calibration_{name}.json"
    hist = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    hist.append(rec)
    path.write_text(json.dumps(hist, indent=1), encoding="utf-8")
    return rec


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--suite", choices=sorted(SUITES), action="append")
    ap.add_argument("--reps", type=int, default=4)
    ap.add_argument("--limit", type=int, help="only the most recent N fixtures")
    ap.add_argument("--label", default="", help="name of this calibration step (stored in the history)")
    ap.add_argument("--no-venue", action="store_true", help="switch off the venue factor (T2-3)")
    ap.add_argument("--no-pitch", action="store_true", help="switch off the pitch of the day (T2-4)")
    ap.add_argument("--no-matchups", action="store_true", help="switch off batting-hand x bowling-kind (T2-1)")
    ap.add_argument("--no-spin", action="store_true", help="switch off the pace v spin pitch edge")
    ap.add_argument("--no-depth", action="store_true", help="switch off batting depth still to come")
    args = ap.parse_args(argv)
    flags = {"use_venue": not args.no_venue, "use_pitch": not args.no_pitch, "use_matchups": not args.no_matchups,
             "use_spin": not args.no_spin, "use_depth": not args.no_depth}
    for name in args.suite or ["t20i", "ipl", "odi"]:
        run_suite(name, args.reps, args.limit, flags, args.label)
    return 0


if __name__ == "__main__":
    sys.exit(main())
