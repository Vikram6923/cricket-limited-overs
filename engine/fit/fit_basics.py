"""Fit the small outcome tables the ball model needs (design T0-3), from Cricsheet ball-by-ball data.

Per format (T20 = T20Is + leagues, ODI), matches since 2010:
  run_split[phase]          share of 1 / 2 / 3 / 5 runs among balls where the batter scored 1-3 (or 5)
  wide_runs                 distribution of runs on a wide (1 = plain wide, 5 = wide to the boundary ...)
  byes[phase]               P(byes) and P(leg byes) per legal non-wicket dot ball, and their run distributions
  dismissal[phase][type]    mix of bowler-credited dismissals: bowled / lbw / caught_keeper / caught_fielder /
                            caught_bowler / stumped / hit_wicket   (type = pace / spin / unknown bowler)
  run_out                   share of run-outs that remove the non-striker; runs completed on run-out balls
  free_hit                  multipliers on the legal ball after a no-ball (runs, fours, sixes, dots)

Writes data/engine/basics_{odi,t20}.json.   Run:  python -m engine.fit.fit_basics
"""
from __future__ import annotations

import json
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "engine"

PHASES = {"odi": ((0, 9, "powerplay"), (10, 39, "middle"), (40, 49, "death")),
          "t20": ((0, 5, "powerplay"), (6, 14, "middle"), (15, 19, "death"))}
SOURCES = {"odi": ["odis_male_json.zip"],
           "t20": ["t20s_male_json.zip"] + [f"leagues/{c}_json.zip" for c in
                                            ("ipl", "bbl", "psl", "cpl", "sat", "ilt", "bpl", "lpl", "mlc", "ntb", "ssm")]}
FIRST_YEAR = 2010


def phase(over: int, fmt: str) -> str:
    for lo, hi, name in PHASES[fmt]:
        if lo <= over <= hi:
            return name
    return PHASES[fmt][-1][2]


def keepers() -> set[str]:
    """Cricsheet IDs of wicket-keepers: Wikipedia role says keeper, or they have stumpings in the data."""
    out = set()
    styles = json.loads((ROOT / "data" / "raw_stats" / "styles.json").read_text(encoding="utf-8"))
    for pid, s in styles.items():
        if "keeper" in (s.get("role") or "").lower():
            out.add(pid)
    for f in ("odi", "t20", "t20_league"):
        p = ROOT / "data" / "raw_stats" / f"players_{f}.json"
        if p.exists():
            for pid, r in json.loads(p.read_text(encoding="utf-8")).items():
                if r["field"]["stumpings"] >= 2:
                    out.add(pid)
    return out


def bowl_types() -> dict[str, str]:
    styles = json.loads((ROOT / "data" / "raw_stats" / "styles.json").read_text(encoding="utf-8"))
    return {pid: (s.get("bowl") or {}).get("type") or "unknown" for pid, s in styles.items()}


def norm(c: Counter) -> dict:
    t = sum(c.values()) or 1
    return {str(k): round(v / t, 5) for k, v in sorted(c.items(), key=lambda kv: str(kv[0]))}


def fit(fmt: str, kp: set, btype: dict) -> dict:
    run_split = defaultdict(Counter)
    wide_runs = Counter()
    byes = defaultdict(lambda: {"dot_balls": 0, "b": Counter(), "lb": Counter()})
    dis = defaultdict(lambda: defaultdict(Counter))
    ro_nonstriker = Counter()
    ro_runs = Counter()
    fh = defaultdict(lambda: [0, 0, 0, 0, 0])   # after-no-ball / normal: balls, runs, fours, sixes, dots (by phase)
    n_matches = 0
    for z in SOURCES[fmt]:
        if not (RAW / z).exists():
            continue
        with zipfile.ZipFile(RAW / z) as zf:
            for n in zf.namelist():
                if not n.endswith(".json"):
                    continue
                m = json.loads(zf.read(n))
                info = m["info"]
                if info.get("gender") != "male" or info.get("balls_per_over", 6) != 6 or \
                        int(info["dates"][0][:4]) < FIRST_YEAR:
                    continue
                n_matches += 1
                reg = info["registry"]["people"]
                team_keeper = {}
                for team, names in info["players"].items():
                    ks = [x for x in names if reg.get(x) in kp]
                    team_keeper[team] = ks[0] if len(ks) == 1 else None  # ambiguous -> don't use
                for inn in m.get("innings", []):
                    if inn.get("super_over"):
                        continue
                    bowl_team = [t for t in info["teams"] if t != inn["team"]][0]
                    keeper = team_keeper.get(bowl_team)
                    for ov in inn.get("overs", []):
                        ph = phase(ov["over"], fmt)
                        prev_nb = False
                        for d in ov["deliveries"]:
                            ex = d.get("extras", {})
                            wide, nb = "wides" in ex, "noballs" in ex
                            br = d["runs"]["batter"]
                            wk = d.get("wickets", [])
                            if wide:
                                wide_runs[min(ex["wides"], 5)] += 1
                                continue
                            if not nb:
                                key = ("after_nb" if prev_nb else "normal", ph)
                                x = fh[key]
                                x[0] += 1
                                x[1] += br
                                x[2] += br == 4 and not d["runs"].get("non_boundary")
                                x[3] += br == 6
                                x[4] += br == 0
                            prev_nb = nb
                            if br in (1, 2, 3, 5):
                                run_split[ph][br] += 1
                            if br == 0 and not wk and not nb:
                                byes[ph]["dot_balls"] += 1
                                if "byes" in ex:
                                    byes[ph]["b"][min(ex["byes"], 4)] += 1
                                if "legbyes" in ex:
                                    byes[ph]["lb"][min(ex["legbyes"], 4)] += 1
                            for w in wk:
                                kind = w["kind"]
                                if kind == "run out":
                                    ro_nonstriker[w["player_out"] != d["batter"]] += 1
                                    ro_runs[min(d["runs"]["total"], 3)] += 1
                                    continue
                                bt = btype.get(reg.get(d["bowler"], ""), "unknown")
                                if kind == "caught":
                                    f = (w.get("fielders") or [{}])[0].get("name")
                                    if keeper is None:
                                        # keeper unknown: keep the catch (skipping it inflated bowled/lbw shares)
                                        # and split it later in the known-keeper proportion
                                        kind = "caught_unknown"
                                    else:
                                        kind = "caught_keeper" if f == keeper else "caught_fielder"
                                elif kind == "caught and bowled":
                                    kind = "caught_bowler"
                                elif kind == "hit wicket":
                                    kind = "hit_wicket"
                                elif kind not in ("bowled", "lbw", "stumped"):
                                    continue
                                dis[ph][bt][kind] += 1
    for ph, d in dis.items():
        for bt, c in d.items():
            u = c.pop("caught_unknown", 0)
            ck, cf = c.get("caught_keeper", 0), c.get("caught_fielder", 0)
            share = ck / (ck + cf) if ck + cf else 0.12
            c["caught_keeper"] = ck + u * share
            c["caught_fielder"] = cf + u * (1 - share)
    free_hit = {}
    for ph in [p[2] for p in PHASES[fmt]]:
        a, b = fh[("after_nb", ph)], fh[("normal", ph)]
        if a[0] and b[0]:
            free_hit[ph] = {"balls": a[0], "runs": round((a[1] / a[0]) / (b[1] / b[0]), 3),
                            "four": round((a[2] / a[0]) / (b[2] / b[0]), 3),
                            "six": round((a[3] / a[0]) / (b[3] / b[0]), 3),
                            "dot": round((a[4] / a[0]) / (b[4] / b[0]), 3)}
    out = {
        "format": fmt, "matches": n_matches, "since": FIRST_YEAR,
        "run_split": {ph: norm(c) for ph, c in run_split.items()},
        "wide_runs": norm(wide_runs),
        "byes": {ph: {"p_bye": round(sum(v["b"].values()) / max(v["dot_balls"], 1), 5),
                      "p_legbye": round(sum(v["lb"].values()) / max(v["dot_balls"], 1), 5),
                      "bye_runs": norm(v["b"]), "legbye_runs": norm(v["lb"])} for ph, v in byes.items()},
        "dismissal": {ph: {bt: norm(c) for bt, c in d.items()} for ph, d in dis.items()},
        "dismissal_n": {ph: {bt: sum(c.values()) for bt, c in d.items()} for ph, d in dis.items()},
        "run_out": {"non_striker_share": round(ro_nonstriker[True] / max(sum(ro_nonstriker.values()), 1), 4),
                    "runs_completed": norm(ro_runs)},
        "free_hit": free_hit,
    }
    return out


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    kp, bt = keepers(), bowl_types()
    for fmt in ("t20", "odi"):
        b = fit(fmt, kp, bt)
        b["keepers"] = sorted(kp)
        (OUT / f"basics_{fmt}.json").write_text(json.dumps(b, indent=1), encoding="utf-8")
        print(f"{fmt}: {b['matches']} matches; free hit {b['free_hit']}")
        print(f"   death dismissals pace: {b['dismissal']['death'].get('pace')}")
        print(f"   middle dismissals spin: {b['dismissal']['middle'].get('spin')}")
        print(f"   run split middle {b['run_split']['middle']}  wides {b['wide_runs']}")
        print(f"   byes middle {b['byes']['middle']['p_bye']} legbyes {b['byes']['middle']['p_legbye']}; "
              f"run outs non-striker {b['run_out']['non_striker_share']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
