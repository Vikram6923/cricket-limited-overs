"""Invariant tests for the match engine: the laws and the bookkeeping must hold in every simulated match.

    python tests/test_engine.py          (no pytest needed; also works under pytest)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import scorecard_text, simulate_match  # noqa: E402
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


def check_card(c: dict):
    fmt = c["format"]
    quota = 4 if fmt == "t20" else 10
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


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
