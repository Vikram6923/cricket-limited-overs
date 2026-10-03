"""Tests for year-range ratings and historical teams (engine/periods.py, engine/history.py).

    python tests/test_history.py          (no pytest needed; also works under pytest)
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import history, simulate_match  # noqa: E402
from engine.data import PHASES, player  # noqa: E402
from engine.periods import period_indexes  # noqa: E402


def test_shrinkage_toward_career():
    # one player far above his career level in the period, with little data -> stays close to career;
    # with lots of data -> moves toward the period rate (tau^2 estimated from players with data in and out)
    rows, career = {}, {}
    for i in range(300):   # population: period rate = career rate +- noise
        rows[f"p{i}"] = {"2010": [600, 480, 480, 20, 20, 300, 300, 50, 50, 10, 10, 1200],
                         "2015": [600, 480 + (i % 7 - 3) * 20, 480, 20, 20, 300, 300, 50, 50, 10, 10, 1200]}
        career[f"p{i}"] = {"runs": 1.0, "wkt": 1.0, "dot": 1.0, "four": 1.0, "six": 1.0}
    rows["thin"] = {"2015": [30, 48, 24, 1, 1, 15, 15, 2, 2, 1, 1, 60], "2010": [600, 480, 480, 20, 20, 300, 300, 50, 50, 10, 10, 1200]}
    rows["thick"] = {"2015": [3000, 4800, 2400, 100, 100, 1500, 1500, 250, 250, 50, 50, 6000],
                     "2010": [600, 480, 480, 20, 20, 300, 300, 50, 50, 10, 10, 1200]}
    career["thin"] = career["thick"] = {"runs": 1.0, "wkt": 1.0, "dot": 1.0, "four": 1.0, "six": 1.0}
    idx, tau, balls = period_indexes(rows, career, 2015, 2015)
    assert tau["runs"] > 0
    assert 1.0 <= idx["thin"]["runs"] < idx["thick"]["runs"] < 2.0
    assert balls["thick"] == 3000


def test_no_years_means_career():
    a, b = player("t20", "ba607b88"), player("t20", "ba607b88", years=None)
    assert a.bat == b.bat and a.usual_slot == b.usual_slot


def test_period_changes_ratings_and_slot():
    career = player("odi", "740742ef")                      # RG Sharma
    early = player("odi", "740742ef", years=(2007, 2011))   # middle order then, weaker than his career
    assert early.bat["middle"]["runs"] < career.bat["middle"]["runs"]
    assert early.usual_slot >= 4 and career.usual_slot <= 2
    assert set(early.bat) == set(PHASES)


def test_historical_team_and_match():
    t = history.historical_team("odi", "Australia", 2003, 2007)
    assert t["years"] == [2003, 2007] and len(t["squad"]) == 20
    assert len(history.historical_team("odi", "Australia", 2003, 2007, size=None)["squad"]) > 20
    names = [player("odi", p).name for p in t["squad"][:10]]
    assert "RT Ponting" in names and "AC Gilchrist" in names
    other = history.historical_team("odi", "India", 2011, 2011)
    c1 = simulate_match(t, other, fmt="odi", comp="odi_full", year=2011, seed=5)
    c2 = simulate_match(t, other, fmt="odi", comp="odi_full", year=2011, seed=5)
    assert c1["result"] == c2["result"]
    assert set(c1["teams"]) == {"Australia 2003-07", "India 2011"}


def test_nations_by_era():
    early = dict(history.nations("t20", 2005, 2008))
    assert "India" in early and "Nepal" not in early      # Nepal's T20Is start in 2014
    try:
        history.historical_team("t20", "Nepal", 2005, 2008)
        assert False, "expected an error"
    except ValueError:
        pass


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
