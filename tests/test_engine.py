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
    """Every tie is settled by super overs. (A level finish is about 1 match in 300, so the tie is forced here;
    the invariant tests above check the ones that come up by themselves.)"""
    from engine import match as M
    a, b = {"name": "India", "players": _ids(T20_A, "t20")}, {"name": "Australia", "players": _ids(T20_B, "t20")}
    real = M.Match.result
    M.Match.result = lambda self, i1, i2: {"type": "tie", "winner": None, "dls": False, "text": "Match tied"}
    try:
        for seed in range(40):
            c = simulate_match(a, b, fmt="t20", year=2024, seed=seed)
            r, so = c["result"], c["super_overs"]
            assert so and len(so) % 2 == 0 and r["by"] == "super_over" and r["winner"] in ("India", "Australia")
            assert so[-2]["runs"] != so[-1]["runs"] and all(x["runs"] == y["runs"] for x, y in zip(so[:-2:2], so[1:-2:2]))
            assert r["winner"] == max(so[-2:], key=lambda s: s["runs"])["team"]
            assert all(s["balls"] <= 6 and s["wickets"] <= 2 for s in so)
            scorecard_text(c)
    finally:
        M.Match.result = real


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


def test_second_super_over_bars_the_bowler_and_dismissed_batters():
    """When the first super over is tied too, nobody dismissed in it bats in the next one and neither side's
    bowler bowls two super overs running."""
    from engine import match as M
    a, b = {"name": "India", "players": _ids(T20_A, "t20")}, {"name": "Australia", "players": _ids(T20_B, "t20")}
    real_play, real_result, first = M.Innings.play, M.Match.result, {}

    def play(self):
        real_play(self)
        if self.number == 101:
            first["runs"] = self.runs
        elif self.number == 102:
            self.runs = first["runs"]                   # the first super over ends level
    M.Innings.play = play
    M.Match.result = lambda self, i1, i2: {"type": "tie", "winner": None, "dls": False, "text": "Match tied"}
    try:
        seen_out = 0
        for seed in range(12):
            c = simulate_match(a, b, fmt="t20", year=2024, seed=seed)
            so = c["super_overs"]
            assert len(so) >= 4 and c["result"]["winner"]
            for k in range(2, len(so)):
                earlier = [s for s in so[:k - k % 2] if s["team"] == so[k]["team"]]
                out = {x["name"] for s in earlier for x in s["batting"] if x["out"]}
                seen_out += len(out)
                assert not out & {x["name"] for x in so[k]["batting"] if x["batted"]}, "dismissed batter batted again"
                prev = [s for s in so[:k] if s["bowling_team"] == so[k]["bowling_team"]][-1]
                assert prev["bowling"][0]["name"] != so[k]["bowling"][0]["name"], "bowler bowled two super overs running"
        assert seen_out, "no wicket fell in any first super over - the test checked nothing"
    finally:
        M.Innings.play, M.Match.result = real_play, real_result


def test_no_ball_is_not_a_free_hit_and_keeps_its_byes():
    """The no-ball itself scores at its own (near-normal) rate, not the free hit's; byes and leg byes run off it
    are added to the penalty run, go down as byes / leg byes and are not charged to the bowler."""
    import random
    from engine.match import Match
    a, b = {"name": "India", "players": _ids(T20_A, "t20")}, {"name": "Australia", "players": _ids(T20_B, "t20")}
    m = Match("t20", a, b, year=2024, seed=1)
    bat, bowl = m.teams[0].players[2], m.teams[1].players[-1]
    rng = random.Random(7)
    base = dict(m.base["middle"], noball=0.5)            # half the balls are no-balls, to get plenty of them
    nb, free, normal, byes = [], [], [], []
    for k in range(60000):
        o = m.model.delivery(rng, base, bat, bowl, "middle", "pace", free_hit=k % 2 == 1)
        if o.extra == "nb":
            nb.append(o.bat_runs)
            assert not o.legal and o.wicket in ("", "run_out") and o.extra_runs == 1 + o.byes
            if o.byes:
                byes.append(o)
                assert o.bye_kind in ("b", "lb") and o.bat_runs == 0 and o.ran == (o.byes if o.byes != 4 else 0)
        elif not o.extra:
            (free if k % 2 == 1 else normal).append(o.bat_runs)
    mean = lambda x: sum(x) / len(x)
    assert len(byes) > 50
    assert abs(mean(nb) / mean(normal) - 1.0) < 0.2, (mean(nb), mean(normal))     # fitted: x1.03 in these overs
    assert mean(free) > 1.4 * mean(nb), (mean(free), mean(nb))
    # in a match: the scorecard still adds up when a no-ball has byes (check_card), and the over log shows them
    seen = 0
    for seed in range(300):
        c = simulate_match(a, b, fmt="t20", year=2024, seed=seed)
        syms = [x for inn in c["innings"] for o in inn["overs_log"] for x in o["balls"] if "nb+" in x]
        if syms:
            seen += 1
            check_card(c)
    assert seen, "no no-ball with byes in 300 matches"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
