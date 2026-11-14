"""Invariant tests for the match engine: the laws and the bookkeeping must hold in every simulated match.

    python tests/test_engine.py          (no pytest needed; also works under pytest)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import match_report, scorecard_text, simulate_match  # noqa: E402
from engine.data import search  # noqa: E402


def _ids(names, fmt):
    out = []
    for n in names:
        hit = [x for x in search(fmt, n, 8) if x[1] == n]
        assert hit, f"player not in ratings: {n}"
        out.append(hit[0][0])
    return out


T20_A = ["Rohit Sharma", "Shubman Gill", "V Kohli", "SA Yadav", "HH Pandya", "RR Pant", "RA Jadeja", "AR Patel",
         "Kuldeep Yadav", "JJ Bumrah", "Arshdeep Singh"]
T20_B = ["TM Head", "MR Marsh", "JP Inglis", "GJ Maxwell", "MP Stoinis", "TH David", "MS Wade", "PJ Cummins",
         "MA Starc", "A Zampa", "JR Hazlewood"]
ODI_A = ["RG Sharma", "Shubman Gill", "V Kohli", "SS Iyer", "KL Rahul", "HH Pandya", "RA Jadeja", "Kuldeep Yadav",
         "JJ Bumrah", "Mohammed Siraj", "Mohammed Shami"]
ODI_B = ["TM Head", "MR Marsh", "SPD Smith", "M Labuschagne", "JP Inglis", "GJ Maxwell", "MP Stoinis", "PJ Cummins",
         "MA Starc", "A Zampa", "JR Hazlewood"]


def check_card(c: dict, rain: bool = False):
    fmt = c["format"]
    quota = -(-c["overs"] // 5)                # a fifth of the overs at the start (10 of 50, 4 of 20)
    for inn in c["innings"]:
        max_balls = inn["max_overs"] * 6
        assert inn["balls"] <= max_balls, "too many legal balls"
        assert inn["wickets"] <= 10
        bat_runs = sum(b["runs"] for b in inn["batting"])
        assert bat_runs + sum(inn["extras"].values()) == inn["runs"], "batting + extras != total"
        conceded = sum(w["runs"] for w in inn["bowling"])
        assert conceded == inn["runs"] - inn["extras"]["b"] - inn["extras"]["lb"], "bowling runs mismatch"
        assert sum(w["wickets"] for w in inn["bowling"]) == sum(
            1 for b in inn["batting"] if b["out"] and b["how_out"]["kind"] != "run_out"), "bowler wickets mismatch"
        assert sum(w["balls"] for w in inn["bowling"]) == inn["balls"], "bowler balls != innings balls"
        for w in inn["bowling"]:
            assert w["balls"] <= quota * 6, f"{w['name']} exceeded the quota"
        names = [o["bowler"] for o in inn["overs_log"]]
        for a, b in zip(names, names[1:]):
            assert a != b, f"{a} bowled consecutive overs"
        assert sum(1 for b in inn["batting"] if b["out"]) == inn["wickets"]
        if inn["fall_of_wickets"]:
            runs = [f["runs"] for f in inn["fall_of_wickets"]]
            assert runs == sorted(runs), "fall of wickets out of order"
    if rain:
        return
    i1, i2 = c["innings"]
    r = c["result"]
    assert i2["target"] == i1["runs"] + 1
    if i2["runs"] >= i2["target"]:
        assert r["winner"] == i2["team"] and r["by"] == "wickets"
    elif i2["runs"] < i1["runs"]:
        assert r["winner"] == i1["team"] and r["by"] == "runs"
    else:
        assert c["super_overs"] and r["by"] == "super_over", "tie must go to a super over"
    assert c["player_of_match"].get("name")


def test_invariants_t20():
    a, b = {"name": "India", "players": _ids(T20_A, "t20")}, {"name": "Australia", "players": _ids(T20_B, "t20")}
    for seed in range(300):
        check_card(simulate_match(a, b, fmt="t20", year=2024, seed=seed))


def test_invariants_odi():
    a, b = {"name": "India", "players": _ids(ODI_A, "odi")}, {"name": "Australia", "players": _ids(ODI_B, "odi")}
    for seed in range(100):
        check_card(simulate_match(a, b, fmt="odi", year=2024, seed=seed, venue="Wankhede Stadium, Mumbai"))


def test_seed_reproducible():
    a, b = {"name": "India", "players": _ids(T20_A, "t20")}, {"name": "Australia", "players": _ids(T20_B, "t20")}
    x = simulate_match(a, b, fmt="t20", year=2024, seed=42)
    y = simulate_match(a, b, fmt="t20", year=2024, seed=42)
    assert x == y
    assert scorecard_text(x) == scorecard_text(y)


def test_super_over_happens():
    # with enough matches some end level; every tie must be settled by super overs
    a, b = {"name": "India", "players": _ids(T20_A, "t20")}, {"name": "Australia", "players": _ids(T20_B, "t20")}
    ties = 0
    for seed in range(1500):
        c = simulate_match(a, b, fmt="t20", year=2024, seed=seed)
        if c["super_overs"]:
            ties += 1
            assert c["result"]["winner"] in ("India", "Australia")
    assert ties > 0, "no ties in 1500 T20s - suspicious"


def test_unknown_players():
    a = {"name": "Invented XI", "players": [f"nobody{i}" for i in range(11)]}
    b = {"name": "Australia", "players": _ids(T20_B, "t20")}
    for seed in range(20):
        check_card(simulate_match(a, b, fmt="t20", year=2024, seed=seed))


def test_rain():
    """Rain on: valid results, laws hold in shortened innings, and a dry match is the same as with rain off."""
    a, b = {"name": "India", "players": _ids(ODI_A, "odi")}, {"name": "Australia", "players": _ids(ODI_B, "odi")}
    kinds = set()
    for seed in range(150):
        c = simulate_match(a, b, fmt="odi", year=2024, seed=seed, venue="Lord's, London", rain_on=True)
        check_card(c, rain=True)
        r = c["result"]
        kinds.add(r["type"] + ("_dls" if r.get("dls") else ""))
        assert r["type"] in ("win", "tie", "no_result")
        if not c["rain"]:
            dry = simulate_match(a, b, fmt="odi", year=2024, seed=seed, venue="Lord's, London")
            assert dry["result"] == r and dry["innings"][0]["runs"] == c["innings"][0]["runs"]
        elif len(c["innings"]) == 2 and not r.get("par") and r["type"] == "win" and r.get("by") != "super_over":
            i2 = c["innings"][1]
            assert (r["winner"] == i2["team"]) == (i2["runs"] >= i2["target"])
        scorecard_text(c)
    assert {"win", "win_dls", "no_result"} <= kinds, kinds


def test_last_ball_wicket_and_partnerships():
    """A wicket off the last ball of an innings brings nobody else in (he "did not bat"), and the partnerships
    are one per wicket plus the unbroken one, adding up to the total (an all-out innings has no unbroken one)."""
    a, b = {"name": "India", "players": _ids(T20_A, "t20")}, {"name": "Australia", "players": _ids(T20_B, "t20")}
    last_ball = all_out = 0
    for seed in range(300):
        c = simulate_match(a, b, fmt="t20", year=2024, seed=seed)
        for inn in c["innings"]:
            ps = inn["partnerships"]
            assert sum(p["runs"] for p in ps) == inn["runs"], "partnerships don't add up to the total"
            assert sum(1 for p in ps if not p.get("unbroken")) == inn["wickets"]
            on_wicket = bool(inn["overs_log"]) and inn["overs_log"][-1]["balls"][-1] == "W"
            assert sum(1 for p in ps if p.get("unbroken")) <= (0 if on_wicket else 1)
            batted = sum(1 for x in inn["batting"] if x["batted"])
            assert batted == inn["wickets"] + (1 if on_wicket else 2), "a batter came in after the innings ended"
            last_ball += on_wicket and inn["wickets"] < 10
            all_out += inn["wickets"] >= 10
    assert last_ball > 5 and all_out > 5, (last_ball, all_out)


def test_chase_stopped_by_rain_is_decided_by_runs():
    """Rain ends a chase for good: the result goes by the DLS par score, by runs whichever side is ahead (the
    side batting second wins by its lead over par), and the tournament records can list it."""
    from engine.match import Match
    from engine.tournament import points_table, records
    a, b = {"name": "India", "players": _ids(T20_A, "t20")}, {"name": "Australia", "players": _ids(T20_B, "t20")}
    kinds = set()
    for seed in range(120):
        m = Match("t20", a, b, year=2024, seed=seed)
        m.rain_profile = {"stop2": 0.6, "u": 0.0}          # the chase is stopped after 12 overs
        c = m.play()
        c["match_no"], c["stage"], c["knockout"] = 1, "League", False
        r, i2 = c["result"], c["innings"][1]
        if "par" in r and r["type"] == "win":
            ahead = r["winner"] == i2["team"]
            assert r["by"] == "runs" and r["margin"] == abs(i2["runs"] - r["par"]) and r["margin"] > 0
            assert ahead == (i2["runs"] > r["par"])
            kinds.add("chaser" if ahead else "defender")
        records([c])
        points_table([c], c["teams"])
        scorecard_text(c)
        match_report(c)
    assert kinds == {"chaser", "defender"}, kinds


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
