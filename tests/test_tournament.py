"""Tests for series / tournament runners: points, net run rate, stats totals, knockout structure.

    python tests/test_tournament.py          (no pytest needed; also works under pytest)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.tournament import match_count, play_series, play_tournament, points_table  # noqa: E402

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


# ---------------------------------------------------------------- domestic formats (quarter-finals, Super League, Plate)

def _sides(n: int, tag: str = "") -> list[dict]:
    """n distinct sides: the example nations, then copies under new names (same players)."""
    out = []
    for k in range(n):
        t = dict(TEAMS[k % len(TEAMS)])
        t["name"] = f"{t['name']}{tag}{'' if k < len(TEAMS) else f' {k // len(TEAMS) + 1}'}"
        out.append(t)
    return out


def _group_of(res: dict) -> dict:
    return {t: g for g, names in res["settings"]["groups"].items() for t in names}


def _check_count(res: dict, n: int, **kw) -> None:
    assert match_count(n, **kw) == len(res["matches"]), (match_count(n, **kw), len(res["matches"]))


def test_quarter_finals_from_four_groups():
    teams = _sides(12)
    res = play_tournament(teams, fmt="t20", comp="sma", year=2021, groups=4, knockout="qf", win_points=4, seed=21)
    _check_count(res, 12, groups=4, knockout="qf")
    stages = [k["stage"] for k in res["knockouts"]]
    assert stages == [f"Quarter-final {i}" for i in range(1, 5)] + ["Semi-final 1", "Semi-final 2", "Final"]
    g = _group_of(res)
    tops = {label: [r["team"] for r in rows[:2]] for label, rows in res["tables"].items()}
    winners = {v[0] for v in tops.values()}
    qf = res["knockouts"][:4]
    assert {t for k in qf for t in k["teams"]} == {t for v in tops.values() for t in v}
    for k in qf:
        a, b = k["teams"]
        assert g[a] != g[b], "group-mates kept apart in the quarter-finals"
        assert a in winners and b not in winners, "each group winner meets a runner-up, named first"
    sf1, sf2, final = res["knockouts"][4:]
    assert set(sf1["teams"]) == {qf[0]["winner"], qf[1]["winner"]}
    assert set(sf2["teams"]) == {qf[2]["winner"], qf[3]["winner"]}
    assert set(final["teams"]) == {sf1["winner"], sf2["winner"]} and res["winner"] == final["winner"]
    for rows in res["tables"].values():                   # 4 points a win (no rain, so no no-results)
        assert sum(r["points"] for r in rows) == 4 * sum(r["won"] for r in rows) + 2 * sum(r["tied"] for r in rows)


def test_preliminary_quarter_finals():
    teams = _sides(15)
    res = play_tournament(teams, fmt="t20", comp="sma", year=2024, groups=5, knockout="pre_qf", win_points=4, seed=24)
    _check_count(res, 15, groups=5, knockout="pre_qf")
    stages = [k["stage"] for k in res["knockouts"]]
    assert stages[:2] == ["Preliminary quarter-final 1", "Preliminary quarter-final 2"] and len(stages) == 9
    # seeds: the 5 group winners and the best runner-up go straight through; the other 4 runners-up play off
    runners = sorted((rows[1] for rows in res["tables"].values()), key=lambda r: (-r["points"], -r["nrr"], r["team"]))
    winners = {rows[0]["team"] for rows in res["tables"].values()}
    direct = winners | {runners[0]["team"]}
    prelim = {t for k in res["knockouts"][:2] for t in k["teams"]}
    assert prelim == {r["team"] for r in runners[1:]}
    qf_teams = {t for k in res["knockouts"][2:6] for t in k["teams"]}
    assert qf_teams == direct | {k["winner"] for k in res["knockouts"][:2]}


def test_preliminary_quarter_finals_with_plate_winner():
    # 2021-22: five group winners go through; the five runners-up and the Plate winner play three preliminaries
    elite, plate = _sides(10), _sides(3, " (P)")
    pc = {"teams": plate, "knockout": "none", "advance": 1}
    res = play_tournament(elite, fmt="t20", comp="sma", year=2021, groups=5, knockout="pre_qf", win_points=4,
                          seed=22, plate=pc)
    _check_count(res, 10, groups=5, knockout="pre_qf", plate={**pc, "teams": 3})
    pre = [k for k in res["knockouts"] if k["stage"].startswith("Preliminary")]
    qf = [k for k in res["knockouts"] if k["stage"].startswith("Quarter-final")]
    assert len(pre) == 3 and len(qf) == 4
    winners = {rows[0]["team"] for rows in res["tables"].values()}
    runners = {rows[1]["team"] for rows in res["tables"].values()}
    assert {t for k in pre for t in k["teams"]} == runners | {res["plate"]["winner"]}
    assert {t for k in qf for t in k["teams"]} == winners | {k["winner"] for k in pre}


def test_super_league_then_final():
    teams = _sides(12)
    res = play_tournament(teams, fmt="t20", comp="sma", year=2025, groups=4, knockout="super_league", win_points=4,
                          seed=25)
    _check_count(res, 12, groups=4, knockout="super_league")
    g = _group_of(res)
    sl = res["super_league"]
    assert list(sl) == ["Super League A", "Super League B"]
    qualifiers = {r["team"] for rows in res["tables"].values() for r in rows[:2]}
    assert {r["team"] for rows in sl.values() for r in rows} == qualifiers
    for rows in sl.values():
        assert len(rows) == 4 and all(r["played"] == 3 for r in rows)
        assert len({g[r["team"]] for r in rows}) == 4, "one side from each group per Super League group"
    (final,) = res["knockouts"]
    assert final["stage"] == "Final" and set(final["teams"]) == {sl["Super League A"][0]["team"],
                                                                 sl["Super League B"][0]["team"]}


def test_super_league_semis_with_uneven_groups():
    teams = _sides(9)
    groups = [[t["name"] for t in teams[:5]], [t["name"] for t in teams[5:]]]
    res = play_tournament(teams, fmt="t20", comp="sma", year=2019, groups=groups, advance=[3, 2],
                          knockout="super_league_semis", seed=19)
    _check_count(res, 9, groups=groups, advance=[3, 2], knockout="super_league_semis")
    A, B = res["super_league"]["Super League A"], res["super_league"]["Super League B"]
    assert len(A) + len(B) == 5
    s1, s2, final = res["knockouts"]
    assert s1["teams"] == [A[0]["team"], B[1]["team"]] and s2["teams"] == [B[0]["team"], A[1]["team"]]
    assert set(final["teams"]) == {s1["winner"], s2["winner"]}


def test_plate_promotion_relegation_and_plate_side_in_quarter_finals():
    elite, plate = _sides(8), _sides(4, " (P)")
    res = play_tournament(elite, fmt="t20", comp="sma", year=2021, groups=4, knockout="qf", advance=[2, 2, 2, 1],
                          win_points=4, seed=31, plate={"teams": plate, "knockout": "final", "advance": 1})
    pc = {"teams": 4, "knockout": "final", "advance": 1}
    _check_count(res, 8, groups=4, knockout="qf", advance=[2, 2, 2, 1], plate=pc)
    p = res["plate"]
    top2 = [r["team"] for r in p["tables"]["Plate"][:2]]
    plate_final = next(k for k in res["knockouts"] if k["stage"] == "Plate final")
    assert plate_final["teams"] == top2 and res["promoted"] == p["winner"] == plate_final["winner"]
    assert p["to_elite_knockouts"] == top2[:1]
    qf = [k for k in res["knockouts"] if k["stage"].startswith("Quarter-final")]
    assert qf[0]["teams"][1] == top2[0], "the Plate qualifier is the 8th seed and meets the top seed"
    elite_rows = [r for rows in res["tables"].values() for r in rows]
    assert res["relegated"] == min(elite_rows, key=lambda r: (r["points"], r["nrr"], r["team"]))["team"]
    assert res["relegated"] in res["teams"] and res["promoted"] not in res["teams"]
    assert all(k["stage"] != "Final" for k in res["knockouts"][:-1]) and res["knockouts"][-1]["stage"] == "Final"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
