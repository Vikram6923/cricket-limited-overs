"""Rain: how often real matches are cut short, and how, by host country (engine/rain.py).

    python -m engine.fit.fit_rain        -> data/engine/rain_{odi,t20}.json

From every Cricsheet match (ODIs; T20Is + leagues) a "rain profile" is read off the scorecard, as fractions of the
scheduled overs:
- start: both innings reduced alike (overs lost before or early in the match);
- cut1: the first innings ended early (not all out) and the chase was given `o2` overs (DLS target);
- o2: the chase reduced to fewer overs than the first innings had (interruption between innings or during the
  chase; the engine picks the moment);
- stop2: the chase stopped for good after this share of its overs (DLS par result, or no result if under the
  minimum overs);
- stop1: the match abandoned during the first innings (no result); `stop1 = 1` = abandoned at the break.
Host country of a venue = the full member that plays there most (neutral venues go to whoever plays there most);
league matches = the league's home country. Matches abandoned without a ball are not in Cricsheet, so the
washout rate is a little low.
"""
from __future__ import annotations

import json
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
FULL = {"Afghanistan", "Australia", "Bangladesh", "England", "India", "Ireland", "New Zealand", "Pakistan",
        "South Africa", "Sri Lanka", "West Indies", "Zimbabwe"}
LEAGUE_HOME = {"ipl": "India", "bbl": "Australia", "psl": "Pakistan", "cpl": "West Indies", "sat": "South Africa",
               "ilt": "United Arab Emirates", "bpl": "Bangladesh", "lpl": "Sri Lanka", "mlc": "United States of America",
               "ntb": "England", "ssm": "New Zealand"}


def matches(zpath: Path):
    with zipfile.ZipFile(zpath) as zf:
        for n in zf.namelist():
            if n.endswith(".json"):
                m = json.loads(zf.read(n))
                if m["info"].get("gender", "male") == "male":
                    yield m


def legal_balls(inn: dict) -> int:
    return sum(1 for ov in inn.get("overs", []) for d in ov["deliveries"]
               if not {"wides", "noballs"} & set(d.get("extras", {})))


def wickets(inn: dict) -> int:
    return sum(len(d.get("wickets", [])) for ov in inn.get("overs", []) for d in ov["deliveries"])


def profile(m: dict, sched: int) -> dict | None:
    """Rain profile of a match (fractions of scheduled overs), or None if it was not affected."""
    inns = [i for i in m["innings"] if not i.get("super_over")]
    out = m["info"].get("outcome", {})
    nr = out.get("result") == "no result"
    dl = bool(out.get("method"))
    if not inns:
        return None
    b1, w1 = legal_balls(inns[0]), wickets(inns[0])
    o1 = b1 / 6
    if len(inns) < 2:
        return {"stop1": round(min(o1 / sched, 1.0), 3)} if nr else None
    tgt = inns[1].get("target") or {}
    o2 = tgt.get("overs") or sched
    b2, w2 = legal_balls(inns[1]), wickets(inns[1])
    runs2 = sum(d["runs"]["total"] for ov in inns[1]["overs"] for d in ov["deliveries"])
    p: dict = {}
    cut1 = w1 < 10 and o1 < sched - 0.01
    if cut1 and abs(o1 - o2) < 1:
        p["start"] = round(o2 / sched, 3)
    elif cut1:
        p["cut1"] = round(o1 / sched, 3)
        p["o2"] = round(o2 / sched, 3)
    elif o2 < sched:
        p["o2"] = round(o2 / sched, 3)
    chased = tgt.get("runs") and runs2 >= tgt["runs"]
    if (nr or dl) and w2 < 10 and b2 < o2 * 6 - 0.5 and not chased:
        p["stop2"] = round(b2 / 6 / o2, 3)
    return p or None


def first_innings_states(m: dict, sched: int) -> tuple[int, list] | None:
    """(total, [(overs left, wickets lost, runs still to come) at the start of every over]) for a complete,
    uninterrupted first innings, else None."""
    inns = [i for i in m["innings"] if not i.get("super_over")]
    if not inns:
        return None
    inn = inns[0]
    if wickets(inn) < 10 and legal_balls(inn) < sched * 6:
        return None
    per = []                                    # (runs, wickets) in each over
    for ov in inn["overs"]:
        per.append((sum(d["runs"]["total"] for d in ov["deliveries"]),
                    sum(len(d.get("wickets", [])) for d in ov["deliveries"])))
    total = sum(r for r, _ in per)
    out, done, wk = [], 0, 0
    for o in range(sched):
        if wk >= 10:
            break
        out.append((sched - o, wk, total - done))
        if o < len(per):
            done += per[o][0]
            wk += per[o][1]
    return total, out


def main() -> None:
    for fmt, zips in (("odi", [(RAW / "odis_male_json.zip", None)]),
                      ("t20", [(RAW / "t20s_male_json.zip", None)] +
                       [(RAW / "leagues" / f"{k}_json.zip", k) for k in LEAGUE_HOME])):
        sched = 50 if fmt == "odi" else 20
        rows, venue_teams = [], defaultdict(Counter)
        for z, league in zips:
            if not z.exists():
                continue
            for m in matches(z):
                i = m["info"]
                if i.get("overs", sched) != sched:
                    continue
                v = i.get("venue", "").split(",")[0]
                if league is None:
                    for t in i.get("teams", []):
                        if t in FULL:
                            venue_teams[v][t] += 1
                rows.append((v, league, int(i["dates"][0][:4]), profile(m, sched)))
        venue_country = {v: c.most_common(1)[0][0] for v, c in venue_teams.items() if c}
        by = defaultdict(lambda: {"n": 0, "profiles": []})
        for v, league, year, p in rows:
            c = LEAGUE_HOME[league] if league else venue_country.get(v)
            for key in ([c] if c else []) + ["all"]:
                by[key]["n"] += 1
                if p:
                    by[key]["profiles"].append(p)
        out = {"venue_country": venue_country, "league_home": LEAGUE_HOME,
               "countries": {k: {"n": v["n"], "p": round(len(v["profiles"]) / v["n"], 4), "profiles": v["profiles"]}
                             for k, v in by.items() if v["n"] >= 30}}
        path = ROOT / "data" / "engine" / f"rain_{fmt}.json"
        path.write_text(json.dumps(out), encoding="utf-8")
        summ = sorted(((k, v["n"], v["p"]) for k, v in out["countries"].items()), key=lambda x: -x[2])
        kinds = Counter(k for p in out["countries"]["all"]["profiles"] for k in p)
        print(fmt, f"{len(rows)} matches, affected by country:", [(k, n, f"{p:.1%}") for k, n, p in summ])
        print("   profile parts:", dict(kinds))


if __name__ == "__main__":
    main()
