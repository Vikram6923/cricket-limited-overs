"""Tests for series / tournament runners: points, net run rate, stats totals, knockout structure.

    python tests/test_tournament.py          (no pytest needed; also works under pytest)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.tournament import play_series, play_tournament, points_table  # noqa: E402

CFG = json.loads((ROOT / "examples" / "t20_world_cup_style.json").read_text(encoding="utf-8"))
TEAMS = CFG["teams"]


def _nrr_by_hand(cards, team):
    rf = bf = ra = ba = 0
    for c in cards:
        for i in c["innings"]:
            balls = i["max_overs"] * 6 if i["wickets"] >= 10 else i["balls"]
            if i["team"] == team:
                rf, bf = rf + i["runs"], bf + balls
            elif i["bowling_team"] == team:
                ra, ba = ra + i["runs"], ba + balls
    return 6 * rf / bf - 6 * ra / ba


def test_league_points_and_nrr():
    res = play_tournament(TEAMS[:6], fmt="t20", comp="t20i_full", year=2024, rounds=2, knockout="none", seed=5)
    rows = res["tables"]["League"]
    n = len(res["matches"])
    assert n == 6 * 5, "double round robin of 6 teams = 30 matches"
    assert sum(r["played"] for r in rows) == 2 * n
    assert sum(r["points"] for r in rows) == 2 * n
    assert sum(r["won"] for r in rows) == n
    for r in rows:
        assert abs(r["nrr"] - _nrr_by_hand(res["matches"], r["team"])) < 1e-3, r["team"]
    keys = [(-r["points"], -r["nrr"]) for r in rows]
    assert keys == sorted(keys), "table not sorted by points then NRR"
    assert res["winner"] == rows[0]["team"]


def test_stats_add_up():
    res = play_tournament(TEAMS, fmt="t20", comp="t20i_full", year=2024, groups=2, knockout="semis", seed=9)
    total = sum(i["runs"] for c in res["matches"] for i in c["innings"])
    extras = sum(sum(i["extras"].values()) for c in res["matches"] for i in c["innings"])
    assert sum(b["runs"] for b in res["batting"]) + extras == total
    outs = sum(1 for c in res["matches"] for i in c["innings"] for b in i["batting"]
               if b["out"] and b["how_out"]["kind"] != "run_out")
    assert sum(w["wickets"] for w in res["bowling"]) == outs
    assert [k["stage"] for k in res["knockouts"]] == ["Semi-final 1", "Semi-final 2", "Final"]
    finalists = res["knockouts"][2]["teams"]
    assert {res["knockouts"][0]["winner"], res["knockouts"][1]["winner"]} == set(finalists)
    assert res["winner"] in finalists and res["runner_up"] in finalists
    assert res["player_of_series"]["name"]
    assert res["mvp"]["official"][0]["impact"] >= res["mvp"]["official"][-1]["impact"]


def test_ipl_playoffs():
    res = play_tournament(TEAMS[:5], fmt="t20", comp="ipl", year=2025, knockout="ipl", seed=3)
    stages = [k["stage"] for k in res["knockouts"]]
    assert stages == ["Qualifier 1", "Eliminator", "Qualifier 2", "Final"]
    q1, el, q2, final = res["knockouts"]
    loser_q1 = [t for t in q1["teams"] if t != q1["winner"]][0]
    assert set(q2["teams"]) == {loser_q1, el["winner"]}
    assert set(final["teams"]) == {q1["winner"], q2["winner"]}
    top4 = [r["team"] for r in res["tables"]["League"][:4]]
    assert q1["teams"] == top4[:2] and el["teams"] == top4[2:]


def test_series_and_reproducible():
    a, b = TEAMS[0], TEAMS[1]
    x = play_series(a, b, n=3, fmt="t20", comp="t20i_full", year=2024, seed=11)
    y = play_series(a, b, n=3, fmt="t20", comp="t20i_full", year=2024, seed=11)
    assert x["fixtures"] == y["fixtures"]
    assert sum(x["score"].values()) == 3
    assert len(x["matches"]) == 3


def test_points_table_bowled_out_counts_full_quota():
    card = {"teams": ["X", "Y"], "result": {"winner": "X", "loser": "Y"},
            "innings": [{"team": "X", "bowling_team": "Y", "runs": 150, "wickets": 5, "balls": 120, "max_overs": 20},
                        {"team": "Y", "bowling_team": "X", "runs": 100, "wickets": 10, "balls": 60, "max_overs": 20}]}
    t = {r["team"]: r for r in points_table([card], ["X", "Y"])}
    # Y bowled out in 10 overs is charged 20 overs: X = 150/20 - 100/20 = +2.5
    assert abs(t["X"]["nrr"] - 2.5) < 1e-9 and abs(t["Y"]["nrr"] + 2.5) < 1e-9


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
