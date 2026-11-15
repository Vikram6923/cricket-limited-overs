"""Calibration of Test matches by replaying real ones (docs/test_match_plan.md section 7).

Every Test between full members since 2015 is re-simulated K times with its real XIs, first-innings batting
orders, toss, ground and year, and what the simulation produces is compared with what happened: scoring, results,
match length, declarations, hundreds, who bowled. Each target has a gate (the plan's table).

    python -m engine.calibrate --suite test                 # 4 replays per Test
    python -m engine.calibrate --suite test --reps 8 --label "with weather"

Every replay has its own seed, so any number of worker processes gives the same numbers.
Writes data/engine/calibration_test.json (history of runs, newest last).
"""
from __future__ import annotations

import json
import statistics as st
import time
import zipfile
import zlib
from collections import Counter, defaultdict
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from .conditions import venue_key
from .test_match import simulate_test

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "engine"
ZIP = "tests_male_json.zip"
YEARS = (2015, 2026)
COMP = "test_full"
FULL = {"Afghanistan", "Australia", "Bangladesh", "England", "India", "Ireland", "New Zealand", "Pakistan",
        "South Africa", "Sri Lanka", "West Indies", "Zimbabwe"}
BOWLER_WICKETS = {"bowled", "caught", "caught and bowled", "lbw", "stumped", "hit wicket"}
NOT_OUT = {"retired hurt", "retired not out"}
KINDS = ("caught", "bowled", "lbw", "run out", "stumped")
SIM_KIND = {"caught_fielder": "caught", "caught_keeper": "caught", "caught_bowled": "caught",
            "caught_and_bowled": "caught", "run_out": "run out", "hit_wicket": "hit wicket"}

# (target, how the gate is measured, tolerance): "rel" = % of the real value, "pts" = points of a percentage,
# None = reported only. From the plan's table; where the plan gave no number the choice is noted.
GATES = [
    ("runs per wicket", "rel", 2), ("run rate", "rel", 2),
    ("1st inns runs mean", "rel", 2), ("1st inns runs sd", "rel", 10),
    ("draw %", "pts", 3), ("won by an innings %", "pts", 3), ("won by runs %", "pts", 3),
    ("won by wickets %", "pts", 3), ("home win %", "pts", 3),
    ("over in 3 days or fewer %", "pts", 5), ("over on day 4 %", "pts", 5), ("went to day 5 %", "pts", 5),
    ("overs per match", "rel", 5),                       # the plan gates "total overs" without a number: 5%
    ("all out % of innings", "rel", 5), ("overs per innings", "rel", 5),
    ("chase won %, target under 200", "pts", 10),        # the plan gates these bands without a number: 10 points
    ("chase won %, target 200-299", "pts", 10),          # (about 60 real chases in each band)
    ("chase won %, target 300+", None, 0),
    ("declarations per match", "rel", 10), ("lead at 3rd-innings declarations", "rel", 10),
    ("follow-ons enforced per match", "rel", 10),
    ("hundreds per match", "rel", 10), ("five-fors per match", "rel", 10),
    ("double hundreds per match", None, 0), ("ten-fors per match", None, 0),
    ("spin % of overs", "pts", 3), ("spin % of wickets", "pts", 3),
    ("spell length, pace", "rel", 10), ("spell length, spin", "rel", 10),
    ("overs by the most-used bowler", "rel", 10),
] + [(f"dismissals: {k} %", "pts", 2) for k in KINDS]


# ---------------------------------------------------------------------- hosts
@lru_cache(maxsize=None)
def hosts() -> dict:
    """venue key -> the country whose ground it is. From the fitted table when it exists, else counted here:
    the side that has played the most Tests on the ground, if it is alone at the top."""
    p = OUT / "test_conditions.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))["hosts"]
    return count_hosts()


def count_hosts() -> dict:
    by = defaultdict(Counter)
    with zipfile.ZipFile(RAW / ZIP) as zf:
        for n in zf.namelist():
            if n.endswith(".json"):
                info = json.loads(zf.read(n))["info"]
                if info.get("gender") == "male":
                    by[venue_key(info.get("venue"))].update(info["teams"])
    out = {}
    for v, c in by.items():
        top = c.most_common(2)
        if v and top[0][1] >= 2 and (len(top) == 1 or top[0][1] > top[1][1]):
            out[v] = top[0][0]
    return out


@lru_cache(maxsize=None)
def bowl_kinds() -> dict:
    from .fit.fit_basics import bowl_types
    return bowl_types("test")


# ---------------------------------------------------------------------- one match -> summary
def spells(seq: list) -> list:
    """[(bowler, overs)] for an innings' list of who bowled each over: a spell is the same bowler from the same
    end in consecutive overs of that end."""
    out, live = [], {}
    for j, b in enumerate(seq):
        k = live.get(j % 2)
        if k is not None and out[k][0] == b:
            out[k][1] += 1
        else:
            out.append([b, 1])
            live[j % 2] = len(out) - 1
    return out


def finish(s: dict, inns: list) -> dict:
    """The parts of a summary that are computed the same way for a real and a simulated match.
    inns: [{"team", "runs", "wkts", "balls", "overs", "declared", "allout", "scores", "figs" {bowler: wkts},
            "seq" [bowler of each over], "kinds" Counter}]"""
    kind = bowl_kinds()
    s["inns"] = [{k: i[k] for k in ("runs", "wkts", "balls", "overs", "declared", "allout")} for i in inns]
    s["overs"] = sum(i["overs"] for i in inns)
    s["scores"] = [r for i in inns for r in i["scores"]]
    s["five"] = sum(1 for i in inns for w in i["figs"].values() if w >= 5)
    match_w = Counter()
    for i in inns:
        match_w.update(i["figs"])
    s["ten"] = sum(1 for w in match_w.values() if w >= 10)
    tov, twk, sp = Counter(), Counter(), {"pace": [0, 0], "spin": [0, 0]}
    top = []
    for i in inns:
        c = Counter(i["seq"])
        for b, n in c.items():
            tov[kind.get(b, "unknown")] += n
        for b, w in i["figs"].items():
            twk[kind.get(b, "unknown")] += w
        for b, n in spells(i["seq"]):
            t = kind.get(b, "unknown")
            if t in sp:
                sp[t][0] += n
                sp[t][1] += 1
        if i["allout"] and c:
            top.append(max(c.values()))
    s["type_overs"], s["type_wkts"], s["spells"], s["top_overs"] = dict(tov), dict(twk), sp, top
    kinds = Counter()
    for i in inns:
        kinds.update(i["kinds"])
    s["kinds"] = dict(kinds)
    s["follow_on"] = len(inns) > 2 and inns[1]["team"] == inns[2]["team"]
    tot = defaultdict(int)
    s["decl3_lead"], s["chase"] = None, None
    for k, i in enumerate(inns):
        other = sum(v for t, v in tot.items() if t != i["team"])
        if k == 3:
            target = other - tot[i["team"]] + 1
            won = s["result"] == "wickets"
            s["chase"] = (target, "won" if won else "drawn" if s["result"] == "draw" else "lost")
        tot[i["team"]] += i["runs"]
        if k == 2 and i["declared"]:
            s["decl3_lead"] = tot[i["team"]] - other
    return s


def summarize_real(m: dict) -> dict:
    info = m["info"]
    reg = info["registry"]["people"]
    oc = info.get("outcome", {})
    by = oc.get("by", {})
    result = ("innings" if "innings" in by else "runs" if "runs" in by else "wickets" if "wickets" in by
              else oc.get("result", "draw"))
    host = hosts().get(venue_key(info.get("venue")))
    s = {"result": result, "days": len(info["dates"]), "host": host,
         "home_win": (oc.get("winner") == host) if host in info["teams"] else None}
    inns = []
    for inn in m.get("innings", []):
        if not inn.get("overs"):
            continue
        runs = wk = balls = 0
        bat = defaultdict(int)
        figs, kinds, seq = Counter(), Counter(), []
        for ov in inn["overs"]:
            seq.append(reg.get(ov["deliveries"][0]["bowler"]))
            for d in ov["deliveries"]:
                ex = d.get("extras", {})
                runs += d["runs"]["total"]
                if "wides" not in ex and "noballs" not in ex:
                    balls += 1
                bat[d["batter"]] += d["runs"]["batter"]
                bat[d["non_striker"]] += 0
                for w in d.get("wickets", []):
                    if w["kind"] in NOT_OUT:
                        continue
                    wk += 1
                    kinds["caught" if w["kind"] == "caught and bowled" else w["kind"]] += 1
                    if w["kind"] in BOWLER_WICKETS:
                        figs[reg.get(d["bowler"])] += 1
        inns.append({"team": inn["team"], "runs": runs, "wkts": wk, "balls": balls, "overs": len(inn["overs"]),
                     "declared": bool(inn.get("declared")), "allout": wk >= 10, "scores": list(bat.values()),
                     "figs": figs, "seq": seq, "kinds": kinds})
    return finish(s, inns)


def summarize_sim(card: dict, host: str | None) -> dict:
    r = card["result"]
    s = {"result": r.get("by") or r["type"], "days": len(card["days"]), "host": host,
         "home_win": (r.get("winner") == host) if host in card["teams"] else None}
    inns = []
    for i in card["innings"]:
        ids = {b["name"]: b["id"] for b in i["bowling"]}
        kinds = Counter()
        for b in i["batting"]:
            if b["out"]:
                k = (b.get("how_out") or {}).get("kind", "")
                kinds[SIM_KIND.get(k, k)] += 1
        figs = Counter({b["id"]: b["wickets"] for b in i["bowling"] if b["wickets"]})
        inns.append({"team": i["team"], "runs": i["runs"], "wkts": i["wickets"], "balls": i["balls"],
                     "overs": len(i["overs_log"]), "declared": bool(i.get("declared")),
                     "allout": i.get("ended") == "all out", "scores": [b["runs"] for b in i["batting"] if b["batted"]],
                     "figs": figs, "seq": [ids.get(o["bowler"]) for o in i["overs_log"]], "kinds": kinds})
    return finish(s, inns)


# ---------------------------------------------------------------------- fixtures
def fixtures(years: tuple = YEARS) -> list[dict]:
    out = []
    with zipfile.ZipFile(RAW / ZIP) as zf:
        for n in sorted(zf.namelist()):
            if not n.endswith(".json"):
                continue
            m = json.loads(zf.read(n))
            info = m["info"]
            yr = int(info["dates"][0][:4])
            if info.get("gender") != "male" or not (years[0] <= yr <= years[1]) \
                    or info.get("balls_per_over", 6) != 6 or not all(t in FULL for t in info["teams"]):
                continue
            inns = [i for i in m.get("innings", []) if i.get("overs")]
            if not inns:
                continue
            reg = info["registry"]["people"]
            order = {}
            for inn in inns:                         # each side's first innings gives its batting order
                if inn["team"] in order:
                    continue
                seen = []
                for ov in inn["overs"]:
                    for d in ov["deliveries"]:
                        for nm in (d["batter"], d["non_striker"]):
                            if nm not in seen:
                                seen.append(nm)
                order[inn["team"]] = [reg[x] for x in seen]
            teams = info["teams"]
            try:
                specs = [{"name": t, "players": [reg[x] for x in info["players"][t]], "order": order.get(t, [])}
                         for t in teams]
            except KeyError:
                continue
            tw = info.get("toss", {}).get("winner")
            first = inns[0]["team"]
            out.append({"id": n, "year": yr, "a": specs[0], "b": specs[1], "toss": "a" if tw == teams[0] else "b",
                        "decision": "bat" if tw == first else "bowl", "venue": info.get("venue"),
                        "real": summarize_real(m)})
    return out


# ---------------------------------------------------------------------- aggregate
def pct(n: float, d: float) -> float:
    return 100 * n / d if d else 0.0


def aggregate(ms: list[dict]) -> dict:
    n = len(ms)
    inns = [i for m in ms for i in m["inns"]]
    a = {}
    a["runs per wicket"] = sum(i["runs"] for i in inns) / max(sum(i["wkts"] for i in inns), 1)
    a["run rate"] = 6 * sum(i["runs"] for i in inns) / max(sum(i["balls"] for i in inns), 1)
    # first innings that ran their course (all out or declared): a total cut short by the weather is not one
    first = [m["inns"][0]["runs"] for m in ms if m["inns"] and (m["inns"][0]["allout"] or m["inns"][0]["declared"])]
    a["1st inns runs mean"] = st.mean(first)
    a["1st inns runs sd"] = st.pstdev(first)
    res = Counter(m["result"] for m in ms)
    a["draw %"] = pct(res["draw"], n)
    a["won by an innings %"] = pct(res["innings"], n)
    a["won by runs %"] = pct(res["runs"], n)
    a["won by wickets %"] = pct(res["wickets"], n)
    hosted = [m for m in ms if m["home_win"] is not None]
    a["home win %"] = pct(sum(m["home_win"] for m in hosted), len(hosted))
    a["over in 3 days or fewer %"] = pct(sum(m["days"] <= 3 for m in ms), n)
    a["over on day 4 %"] = pct(sum(m["days"] == 4 for m in ms), n)
    a["went to day 5 %"] = pct(sum(m["days"] >= 5 for m in ms), n)
    a["overs per match"] = sum(m["overs"] for m in ms) / n
    a["all out % of innings"] = pct(sum(i["allout"] for i in inns), len(inns))
    a["overs per innings"] = sum(i["overs"] for i in inns) / len(inns)
    for label, lo, hi in (("under 200", 0, 200), ("200-299", 200, 300), ("300+", 300, 10 ** 6)):
        ch = [m["chase"][1] for m in ms if m["chase"] and lo <= m["chase"][0] < hi]
        a[f"chase won %, target {label}"] = pct(sum(c == "won" for c in ch), len(ch))
    a["declarations per match"] = sum(i["declared"] for i in inns) / n
    d3 = [m["decl3_lead"] for m in ms if m["decl3_lead"] is not None]
    a["lead at 3rd-innings declarations"] = st.mean(d3) if d3 else 0.0
    a["follow-ons enforced per match"] = sum(m["follow_on"] for m in ms) / n
    a["hundreds per match"] = sum(r >= 100 for m in ms for r in m["scores"]) / n
    a["five-fors per match"] = sum(m["five"] for m in ms) / n
    a["double hundreds per match"] = sum(r >= 200 for m in ms for r in m["scores"]) / n
    a["ten-fors per match"] = sum(m["ten"] for m in ms) / n
    ov, wk = Counter(), Counter()
    for m in ms:
        ov.update(m["type_overs"])
        wk.update(m["type_wkts"])
    a["spin % of overs"] = pct(ov["spin"], ov["spin"] + ov["pace"])
    a["spin % of wickets"] = pct(wk["spin"], wk["spin"] + wk["pace"])
    for t in ("pace", "spin"):
        a[f"spell length, {t}"] = sum(m["spells"][t][0] for m in ms) / max(sum(m["spells"][t][1] for m in ms), 1)
    top = [x for m in ms for x in m["top_overs"]]
    a["overs by the most-used bowler"] = st.mean(top) if top else 0.0
    kinds = Counter()
    for m in ms:
        kinds.update(m["kinds"])
    for k in KINDS:
        a[f"dismissals: {k} %"] = pct(kinds[k], sum(kinds.values()))
    return a


def by_host(ms: list[dict]) -> dict:
    """Draw rate, home wins and spin's share of overs for each host with 10 or more matches (reported)."""
    g = defaultdict(list)
    for m in ms:
        if m["host"]:
            g[m["host"]].append(m)
    out = {}
    for h, xs in sorted(g.items()):
        ov = Counter()
        for m in xs:
            ov.update(m["type_overs"])
        hw = [m["home_win"] for m in xs if m["home_win"] is not None]
        out[h] = {"matches": len(xs), "draw %": round(pct(sum(m["result"] == "draw" for m in xs), len(xs)), 1),
                  "home win %": round(pct(sum(hw), len(hw)), 1),
                  "spin % of overs": round(pct(ov["spin"], ov["spin"] + ov["pace"]), 1),
                  "overs per match": round(sum(m["overs"] for m in xs) / len(xs), 1)}
    return out


def gate(name: str, kind: str | None, tol: float, real: float, sim: float) -> tuple[float, bool | None]:
    """(difference in the gate's own unit, passed?)."""
    if kind == "pts":
        d = sim - real
    else:
        d = (sim / real - 1) * 100 if real else 0.0
    return d, (None if kind is None else abs(d) <= tol)


# ---------------------------------------------------------------------- run
def seed_for(match_id: str, rep: int) -> int:
    return zlib.crc32(f"{match_id}|{rep}".encode()) & 0x7FFFFFFF


def _replay(task: tuple) -> dict:
    f, r, flags = task
    card = simulate_test(f["a"], f["b"], COMP, f["year"], f["venue"], seed_for(f["id"], r),
                         toss=f["toss"], decision=f["decision"], **flags)
    return summarize_sim(card, hosts().get(venue_key(f["venue"])))


def simulate_all(fx: list[dict], reps: int, flags: dict, jobs: int = 1) -> list[dict]:
    tasks = [({k: f[k] for k in ("id", "year", "a", "b", "toss", "decision", "venue")}, r, flags)
             for f in fx for r in range(reps)]
    if jobs <= 1 or len(tasks) < 2 * jobs:
        return [_replay(t) for t in tasks]
    from concurrent.futures import ProcessPoolExecutor
    with ProcessPoolExecutor(max_workers=jobs) as ex:
        return list(ex.map(_replay, tasks, chunksize=max(1, min(16, len(tasks) // (jobs * 4)))))


def run(reps: int = 4, limit: int | None = None, flags: dict | None = None, label: str = "", jobs: int = 1,
        save: bool = True) -> dict:
    flags = flags or {}
    fx = fixtures()
    if limit:
        fx = fx[-limit:]
    t = time.time()
    sims = simulate_all(fx, reps, flags, jobs)
    reals = [f["real"] for f in fx]
    real, sim = aggregate(reals), aggregate(sims)
    print(f"\n=== test [{label}]: {len(fx)} real Tests ({YEARS[0]}-{YEARS[1]}), {len(sims)} simulations "
          f"in {time.time() - t:.0f}s")
    print(f"   {'':36}{'real':>9}{'sim':>9}{'diff':>9}  gate")
    passed = failed = 0
    gates = {}
    for name, kind, tol in GATES:
        d, ok = gate(name, kind, tol, real[name], sim[name])
        unit = "pt" if kind == "pts" else "%"
        mark = "" if ok is None else (f"ok   (+-{tol}{unit})" if ok else f"MISS (+-{tol}{unit})")
        passed += ok is True
        failed += ok is False
        gates[name] = ok
        print(f"   {name:36}{real[name]:9.2f}{sim[name]:9.2f}{d:8.1f}{unit:2} {mark}")
    print(f"   gates met: {passed} of {passed + failed}")
    hr, hs = by_host(reals), by_host(sims)
    print(f"   {'by host':14}{'n':>4}  draw% real/sim   home win% real/sim   spin overs% real/sim   overs real/sim")
    for h in hr:
        if hr[h]["matches"] >= 10 and h in hs:
            print(f"   {h:14}{hr[h]['matches']:4}  " + "   ".join(
                f"{hr[h][k]:9.1f} /{hs[h][k]:6.1f}" for k in ("draw %", "home win %", "spin % of overs",
                                                              "overs per match")))
    rec = {"when": datetime.now().isoformat(timespec="seconds"), "suite": "test", "label": label, "flags": flags,
           "fixtures": len(fx), "reps": reps, "real": real, "sim": sim, "gates": gates,
           "gates_met": [passed, passed + failed], "by_host": {"real": hr, "sim": hs}}
    if save:
        OUT.mkdir(parents=True, exist_ok=True)
        path = OUT / "calibration_test.json"
        hist = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        hist.append(rec)
        path.write_text(json.dumps(hist, indent=1), encoding="utf-8")
    return rec
