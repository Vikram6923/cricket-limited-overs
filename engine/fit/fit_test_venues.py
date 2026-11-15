"""Test venue factors and the pitch of the day, fitted with the Test engine itself (Phase 3).

    python -m engine.fit.fit_test_venues       -> data/engine/venues_test.json   (~2 min)

The method is engine/fit/fit_venues.py's: every Cricsheet Test is replayed REPS times with its real XIs, batting
orders, toss and year, with the venue factor and the pitch draw switched off (the spin edge, the weather and the
home edge stay on, so the venue factor is what is left after them). Per match
    residual = log(actual rate / simulated rate)     for runs per ball and wickets per ball, all innings
venue factor = the ground's mean residual, shrunk toward 0; pitch of the day = the spread of residuals within a
ground beyond the engine's own replay-to-replay spread, with its runs / wickets correlation.
Run engine.fit.fit_test_conditions first. Replays are cached in data/cache/venue_rows_test.json; delete it to
replay again (after any change to the engine).
"""
from __future__ import annotations

import json
import math
import sys

from ..conditions import venue_key
from ..test_match import simulate_test
from .fit_test_situation import OUT, ROOT, iter_tests, outs
from .fit_venues import fit_rows, seed_for

REPS = 3
COMP = "test_full"


def spec_of(m: dict):
    """Replay spec of a real Test and its actual (runs, wickets, legal balls)."""
    info = m["info"]
    reg = info["registry"]["people"]
    inns = [i for i in m.get("innings", []) if i.get("overs")]
    order, runs, wk, balls = {}, 0, 0, 0
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
                wk += outs(d)
        order.setdefault(inn["team"], [reg[x] for x in seen])
    teams = info["teams"]
    specs = [{"name": t, "players": [reg[x] for x in info["players"][t]], "order": order.get(t, [])} for t in teams]
    tw = info.get("toss", {}).get("winner")
    first = inns[0]["team"] if inns else teams[0]
    return specs, ("a" if tw == teams[0] else "b"), ("bat" if tw == first else "bowl"), (runs, wk, balls)


def replay_rows() -> tuple[list, dict]:
    cache = ROOT / "data" / "cache" / "venue_rows_test.json"
    if cache.exists():
        d = json.loads(cache.read_text(encoding="utf-8"))
        return [tuple(r) for r in d["rows"]], d["names"]
    rows, names = [], {}
    for n, m in enumerate(iter_tests()):
        info = m["info"]
        try:
            specs, toss, dec, (ar, aw, ab) = spec_of(m)
        except KeyError:
            continue
        if ab < 600:                                   # a washed-out match says nothing about its pitch
            continue
        yr = int(info["dates"][0][:4])
        mid = "|".join(info["dates"][:1] + info["teams"])
        lr, lw = [], []
        for rep in range(REPS):
            c = simulate_test(specs[0], specs[1], COMP, yr, info.get("venue"), seed_for(mid, rep),
                              toss=toss, decision=dec, use_venue=False, use_pitch=False)
            sb = sum(i["balls"] for i in c["innings"]) or 1
            lr.append(math.log(max(sum(i["runs"] for i in c["innings"]), 1) / sb))
            lw.append(math.log((sum(i["wickets"] for i in c["innings"]) + 0.5) / sb))
        mr, mw = sum(lr) / REPS, sum(lw) / REPS
        vr = sum((x - mr) ** 2 for x in lr) / (REPS - 1)
        vw = sum((x - mw) ** 2 for x in lw) / (REPS - 1)
        key = venue_key(info.get("venue", ""))
        names.setdefault(key, info.get("venue", ""))
        rows.append((key, COMP, math.log(max(ar, 1) / ab) - mr, math.log((aw + 0.5) / ab) - mw, vr, vw))
        if (n + 1) % 200 == 0:
            print(f"  {n + 1} Tests replayed", flush=True)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"rows": rows, "names": names}), encoding="utf-8")
    return rows, names


def main(argv=None) -> int:
    rows, names = replay_rows()
    cr = sum(r[2] for r in rows) / len(rows)
    cw = sum(r[3] for r in rows) / len(rows)
    res = fit_rows("test", rows, names)
    res["mean_residual"] = {"runs": round(cr, 4), "wkt": round(cw, 4)}     # the engine's overall level (not applied)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "venues_test.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    v = res["venues"]
    top = sorted((x for x in v.values() if x["matches"] >= 10), key=lambda x: -x["runs"])
    print(f"test: {res['matches']} matches; mean residual {res['mean_residual']}; venue SD {res['venue_sd']}; "
          f"pitch {res['pitch']}")
    print("   highest scoring:", [(x["name"].split(",")[0], x["runs"], x["wkt"], x["matches"]) for x in top[:5]])
    print("   lowest scoring: ", [(x["name"].split(",")[0], x["runs"], x["wkt"], x["matches"]) for x in top[-5:]])
    return 0


if __name__ == "__main__":
    sys.exit(main())
