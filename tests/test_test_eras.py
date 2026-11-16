"""Tests for the era factors and era suite, Test matchups, the computer captain's new ball and the learned
Test XI.

    python tests/test_test_eras.py          (no pytest needed; also works under pytest)
"""
from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from engine import history, simulate_match, test_captain, test_conditions, test_era, test_selection  # noqa: E402
from engine.data import baseline, player  # noqa: E402
from engine.test_match import TestMatch  # noqa: E402
from engine.test_situation import TestSituation, matchup_kind, matchup_table  # noqa: E402
from test_test_engine import AUS, IND, check_card, team  # noqa: E402


def test_era_factors():
    t = test_conditions.era_table()
    assert t["until"] == 2001 and {"1900", "1950", "1990"} <= set(t["decades"])
    for d, f in t["decades"].items():
        assert 0.8 < f["runs"] < 1.1 and 0.85 < f["wkt"] < 1.25 and 60 <= f["day_overs"] <= 180, (d, f)
    assert test_conditions.era_factors(2015) == {"runs": 1.0, "wkt": 1.0, "day_overs": None}
    assert test_conditions.era_factors(1955) == t["decades"]["1950"]
    assert test_conditions.era_factors(1877) == t["decades"][min(t["decades"])]      # before the first: the nearest
    ind, aus = team("India", IND), team("Australia", AUS)
    assert TestMatch(ind, aus, year=2023, seed=1).clock.day_overs == 90, "a modern Test is unchanged"
    m = TestMatch(ind, aus, year=1955, seed=1)
    assert m.clock.day_overs == t["decades"]["1950"]["day_overs"]
    plain = TestMatch(ind, aus, year=1955, seed=1, era=False)
    assert plain.clock.day_overs == 90
    assert m.base["all"]["runs"] < plain.base["all"]["runs"], "an early era's baseline is brought down"
    assert TestMatch(ind, aus, year=1955, seed=1, day_overs=80).clock.day_overs == 80, "an explicit day length wins"
    c = simulate_match(ind, aus, fmt="test", year=1955, seed=4)
    check_card(c)
    assert c["day_overs"] == m.clock.day_overs


def test_era_suite_sides_and_records():
    r = test_era.real(1950)
    assert 27 < r["runs per wicket"] < 31 and 2.1 < r["run rate"] < 2.5 and r["years"] == 10
    assert 0.25 < test_era.real_draws(1950) < 0.40 and test_era.real_draws(1960) > test_era.real_draws(1950)
    assert len(test_era.nations(1900)) == 3 and len(test_era.nations(1990)) == 9
    rng = random.Random(1)
    for nation, dec in (("Australia", 1950), ("India", 1970), ("England", 2010)):
        for _ in range(20):
            s = test_era.drawn_side(nation, dec, rng)
            ps = [q for q in test_era.pool(nation, dec) if q[0] in s["players"]]
            assert len(set(s["players"])) == 11 and any(q[2] for q in ps)
            assert test_era.BOWLERS[0] <= sum(q[3] for q in ps) <= test_era.BOWLERS[1]
    a, b = test_era.plan(1950, 6), test_era.plan(1950, 6)
    assert a == b and all(1950 <= y <= 1959 for _, _, y, _ in a), "the same plan every time"
    row = test_era.run_decade(1950, 24)
    assert row["tests"] == 24 and 22 < row["sim"]["runs per wicket"] < 36 and 1.9 < row["sim"]["run rate"] < 2.7
    hist = json.loads((ROOT / "data" / "engine" / "calibration_test_era.json").read_text(encoding="utf-8"))
    assert hist[-1]["met"][0] >= 8, "the recorded era run has most decades inside the gate"


def test_matchups():
    t = matchup_table()
    assert set(t) == {"left", "right"} and {"pace", "left_pace", "off_spin", "leg_spin"} <= set(t["right"])
    for hand in t.values():
        for cell in hand.values():
            assert all(0.75 < v < 1.35 for v in cell.values()), cell
    assert t["left"]["off_spin"]["wkt"] > t["right"]["off_spin"]["wkt"], "off spin turns away from a left-hander"
    assert matchup_kind("495d42a5") == "off_spin" and matchup_kind("nobody") is None       # R Ashwin
    sit = TestSituation()
    mult = sit.multipliers(sit.cell(1, 0, 0), 20, "spin", 10, 10)
    out = sit.with_matchup(mult, "left", "495d42a5")
    assert abs(out["wkt"] / mult["wkt"] - t["left"]["off_spin"]["wkt"]) < 1e-9
    assert sit.with_matchup(mult, "left", "495d42a5") is out, "cached"
    assert sit.with_matchup(mult, None, "495d42a5") is mult and sit.with_matchup(mult, "left", "nobody") is mult
    ind, aus = team("India", IND), team("Australia", AUS)
    a = simulate_match(ind, aus, fmt="test", year=2023, seed=6)
    b = simulate_match(ind, aus, fmt="test", year=2023, seed=6, use_matchups=False)
    assert a["innings"][0]["runs"] != b["innings"][0]["runs"] or a["result"] != b["result"]


def test_the_computer_captains_new_ball():
    t = test_captain.newball_table()
    assert t["available"] == test_captain.NEW_BALL_OVERS == 80
    assert t["take"]["0"][0] > t["take"]["1"][0] > t["take"]["2"][0], "it is kept longest with spin at both ends"
    assert all(0 <= p <= 1 for row in t["take"].values() for p in row)
    rng = random.Random(3)
    took = {s: sum(test_captain.take_new_ball(rng, s, 0) for _ in range(2000)) / 2000 for s in (0, 2)}
    assert abs(took[0] - t["take"]["0"][0]) < 0.04 and abs(took[2] - t["take"]["2"][0]) < 0.04
    ind, aus = team("India", IND), team("Australia", AUS)
    late = at_once = 0
    for seed in range(30):
        c = simulate_match(ind, aus, fmt="test", year=2023, seed=seed, venue="Eden Gardens, Kolkata")
        for e in c["events"]:
            if e["kind"] == "new_ball":
                over = int(e["over"].split(".")[0]) + 1          # "79.6": taken after 80 overs
                assert over >= 80
                at_once += over % 80 == 0
                late += over % 80 != 0
    assert late > 0 and at_once > 0, (late, at_once)


def test_learned_xi():
    m = test_selection.model()
    assert m and m["features"] == list(test_selection.FEATURES) and m["mixes"]
    assert all(a >= 1 for a, _ in m["mixes"]), "no real attack is without a fast bowler"
    val = m["validation"]["test"]
    assert val["learned (experience x0.5)"] >= val["the rule (select_xi)"] >= 8.0
    base = baseline("test", "test_full", 2023)
    spec = history.historical_team("test", "India", 2021, 2024)
    squad = [player("test", x, years=spec["years"]) for x in spec["squad"]]
    for host in ("India", "England", None):
        xi = test_selection.choose(squad, base, None, host)
        assert len({p.id for p in xi}) == 11 and any(p.keeper for p in xi)
        B = test_selection.bowler_mask(xi)
        mix = [sum(b and p.bowl_type != "spin" for b, p in zip(B, xi)), sum(b and p.bowl_type == "spin" for b, p in zip(B, xi))]
        assert mix in m["mixes"], mix
    home = test_selection.choose(squad, base, None, "India")
    away = test_selection.choose(squad, base, None, "England")
    spin = lambda xi: sum(p.bowl_type == "spin" and test_captain.group(p) == "spin" for p in xi)
    assert spin(home) >= spin(away), "more spinners where the grounds take spin"
    assert {"V Kohli", "JJ Bumrah"} <= {p.name for p in away}
    assert test_selection.choose(squad[:11], base) == squad[:11]
    a = TestMatch(spec, history.historical_team("test", "England", 2021, 2024), year=2023, seed=8)
    b = TestMatch(spec, history.historical_team("test", "England", 2021, 2024), year=2023, seed=8)
    assert [p.id for p in a.teams[0].players] == [p.id for p in b.teams[0].players], "a seed picks the same XI"
    named = TestMatch(team("India", IND), team("Australia", AUS), year=2023, seed=8)
    assert [p.id for p in named.teams[0].players] == [x if isinstance(x, str) else x["id"] for x in team("India", IND)["players"]]


def main() -> None:
    fns = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    for name, fn in fns:
        t = time.time()
        fn()
        print(f"ok   {name}  ({time.time() - t:.1f}s)")
    print(f"{len(fns)} tests passed")


if __name__ == "__main__":
    main()
