"""Tests for the Test match conditions and calibration (Phase 3 of docs/test_match_plan.md).

    python tests/test_test_calibration.py          (no pytest needed; also works under pytest)

200 fixed Tests must stay inside wide bands around real Test cricket (the tight gates are checked by
`python -m engine.calibrate --suite test`, which needs the Cricsheet archive and takes a minute); the weather,
the host and the home edge behave as designed; the calibration's own sums are right.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from engine import scorecard_text, simulate_match  # noqa: E402
from engine import test_calibrate, test_conditions  # noqa: E402
from test_test_engine import AUS, ENG, IND, NZ, check_card, team  # noqa: E402


def test_200_fixed_tests_stay_inside_wide_bands():
    ind, aus, eng, nz = team("India", IND), team("Australia", AUS), team("England", ENG), team("New Zealand", NZ)
    plans = [(ind, aus, {"year": 2023, "venue": "Eden Gardens, Kolkata"}),
             (eng, nz, {"year": 2015, "venue": "Lord's, London"}),
             (aus, eng, {"year": 2019, "venue": "Melbourne Cricket Ground"}),
             (nz, ind, {"year": 2021, "venue": "Basin Reserve, Wellington"})]
    ms, lost, home = [], 0, []
    for a, b, kw in plans:
        for seed in range(50):
            c = simulate_match(a, b, fmt="test", seed=seed, **kw)
            check_card(c)
            assert c["conditions"]["host"] == a["name"] == c["conditions"]["home"]
            ms.append(test_calibrate.summarize_sim(c, c["conditions"]["host"]))
            lost += sum(d["lost"] for d in c["days"])
            home.append(c["result"].get("winner") == a["name"])
    a = test_calibrate.aggregate(ms)
    bands = {"runs per wicket": (26, 37), "run rate": (2.9, 3.8), "1st inns runs mean": (270, 400),
             "draw %": (5, 35), "won by an innings %": (5, 35), "won by runs %": (20, 55),
             "won by wickets %": (12, 42), "went to day 5 %": (25, 70), "overs per match": (260, 350),
             "all out % of innings": (60, 85), "declarations per match": (0.2, 1.1),
             "hundreds per match": (1.0, 2.6), "five-fors per match": (0.6, 1.8), "spin % of overs": (20, 55),
             "dismissals: caught %": (52, 68), "dismissals: bowled %": (12, 24), "dismissals: lbw %": (10, 22)}
    for k, (lo, hi) in bands.items():
        assert lo <= a[k] <= hi, f"{k} = {a[k]:.2f}, outside {lo} to {hi}"
    assert 15 <= lost / len(ms) <= 110, f"{lost / len(ms):.0f} overs lost a match"
    assert 0.40 <= sum(home) / len(home) <= 0.80, "the home sides' share of wins"


def test_weather_host_and_home_edge():
    ind, aus = team("India", IND), team("Australia", AUS)
    assert test_conditions.host_of("Lord's, London") == "England"
    assert test_conditions.host_of("Melbourne Cricket Ground") == "Australia"
    assert test_conditions.host_of(None) is None and test_conditions.host_of("Nowhere Park") is None
    w = test_conditions.tables()["weather"]
    for kind in ("dry", "wet"):
        assert abs(sum(w[kind]) - 1) < 1e-3 and all(x >= 0 for x in w[kind])
    assert 0 < w["wet_share"] < 0.5 and w["mean_dry"] < w["mean_wet"]
    assert test_conditions.draw_weather("England", 7, 5, 90) == test_conditions.draw_weather("England", 7, 5, 90)
    for seed in range(200):
        for day, d in test_conditions.draw_weather("England", seed, 5, 90).items():
            assert 1 <= day <= 5 and 1 <= d["overs"] <= 90 and 0 <= d["start"] <= 90 - d["overs"], d
    h = test_conditions.home_factors()
    assert h["runs"] > 1 > h["wkt"], "the home side should score a little faster and lose fewer wickets"
    # switches: no weather = no overs lost; no ground = no host and no home side; the host can be given
    lost = 0
    for seed in range(20):
        c = simulate_match(ind, aus, fmt="test", year=2023, seed=seed, use_weather=False)
        check_card(c)
        lost += sum(d["lost"] for d in c["days"])
        assert c["conditions"]["host"] is None and c["conditions"]["home"] is None
    assert lost == 0
    c = simulate_match(ind, aus, fmt="test", year=2023, seed=1, host="India")
    assert c["conditions"]["home"] == "India"
    c = simulate_match(ind, aus, fmt="test", year=2023, seed=1, host="India", use_home=False)
    assert c["conditions"]["host"] == "India" and c["conditions"]["home"] is None
    c = simulate_match(ind, aus, fmt="test", year=2023, seed=1, venue="Lord's, London")
    assert c["conditions"]["host"] == "England" and c["conditions"]["home"] is None      # a neutral Test
    # the home edge moves results the right way: India win more Tests at home than the same sides without it
    wins = {True: 0, False: 0}
    for seed in range(120):
        for at_home in (True, False):
            c = simulate_match(ind, aus, fmt="test", year=2023, seed=seed, host="India", use_home=at_home,
                               use_weather=False)
            wins[at_home] += c["result"].get("winner") == "India"
    assert wins[True] > wins[False], wins
    # a day that loses overs says so in the events, the day list and the text scorecard
    c = next(c for c in (simulate_match(ind, aus, fmt="test", year=2023, seed=s, host="England") for s in range(60))
             if any(d["lost"] >= 20 for d in c["days"]))
    ev = [e for e in c["events"] if e["kind"] == "weather"]
    assert ev and all("lost" in e["text"] for e in ev)
    assert " lost)" in scorecard_text(c)


def test_calibration_sums():
    assert test_calibrate.spells(["a", "b", "a", "b", "a", "c", "d", "c"]) == \
        [["a", 3], ["b", 2], ["c", 2], ["d", 1]]
    assert test_calibrate.gate("x", "pts", 3, 13.0, 15.5) == (2.5, True)
    d, ok = test_calibrate.gate("x", "rel", 2, 30.0, 31.0)
    assert round(d, 2) == 3.33 and ok is False
    assert test_calibrate.gate("x", None, 0, 1.0, 2.0)[1] is None
    names = [g[0] for g in test_calibrate.GATES]
    assert len(names) == len(set(names))
    ind, aus = team("India", IND), team("Australia", AUS)
    cards = [simulate_match(ind, aus, fmt="test", year=2023, seed=s, host="India") for s in range(12)]
    ms = [test_calibrate.summarize_sim(c, "India") for c in cards]
    a = test_calibrate.aggregate(ms)
    assert set(names) <= set(a)
    for c, m in zip(cards, ms):
        assert m["overs"] == sum(len(i["overs_log"]) for i in c["innings"])
        assert m["result"] == (c["result"].get("by") or c["result"]["type"])
        assert m["home_win"] == (c["result"].get("winner") == "India")
        assert sum(m["kinds"].values()) == sum(i["wickets"] for i in c["innings"])
        assert sum(m["type_overs"].values()) == m["overs"]
        assert m["follow_on"] == any(i["follow_on"] for i in c["innings"])
        if len(c["innings"]) == 4:
            assert m["chase"][0] == c["innings"][3]["target"]


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in tests:
        fn()
        print(f"ok   {fn.__name__}")
    print(f"{len(tests)} tests passed")


if __name__ == "__main__":
    main()
