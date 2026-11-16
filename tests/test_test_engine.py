"""Tests for the Test match engine (Phase 2 of docs/test_match_plan.md): the laws and the bookkeeping must hold
in every simulated Test, each kind of result is reached in a scripted match, and a seed reproduces a match.

    python tests/test_test_engine.py          (no pytest needed; also works under pytest)

Realism (draw rate, runs per wicket ...) is not tested here: that is calibration, Phase 3.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import Match, scorecard_text, full_text, simulate_match  # noqa: E402
from engine import test_captain  # noqa: E402
from engine.ballmodel import Outcome  # noqa: E402
from engine.data import search  # noqa: E402
from engine.test_match import Clock, TestMatch  # noqa: E402
from engine.test_situation import TestSituation  # noqa: E402


def _ids(names):
    out = []
    for n in names:
        hit = [x for x in search("test", n, 8) if x[1] == n]
        assert hit, f"player not in the Test ratings: {n}"
        out.append(hit[0][0])
    return out


IND = ["RG Sharma", "YBK Jaiswal", "Shubman Gill", "V Kohli", "KL Rahul", "RR Pant", "RA Jadeja", "R Ashwin",
       "JJ Bumrah", "Mohammed Siraj", "Mohammed Shami"]
AUS = ["UT Khawaja", "DA Warner", "M Labuschagne", "SPD Smith", "TM Head", "MR Marsh", "AT Carey", "PJ Cummins",
       "MA Starc", "NM Lyon", "JR Hazlewood"]
ENG = ["AN Cook", "Z Crawley", "JE Root", "BA Stokes", "JM Bairstow", "JC Buttler", "MM Ali", "CR Woakes",
       "SCJ Broad", "JM Anderson", "MA Wood"]
NZ = ["TWM Latham", "DP Conway", "KS Williamson", "LRPL Taylor", "HM Nicholls", "BJ Watling", "C de Grandhomme",
      "MJ Santner", "TG Southee", "N Wagner", "TA Boult"]
WI = ["CG Greenidge", "DL Haynes", "IVA Richards", "CH Lloyd", "HA Gomes", "PJL Dujon", "MD Marshall",
      "MA Holding", "J Garner", "AME Roberts", "RB Richardson"]


def team(name, names, **kw):
    return {"name": name, "players": _ids(names), **kw}


def expected_result(c: dict) -> dict:
    """The result the scores imply, worked out here from the innings alone."""
    inns = c["innings"]
    tot = {t: sum(i["runs"] for i in inns if i["team"] == t) for t in c["teams"]}
    last = inns[-1]
    if len(inns) == 3 and last["ended"] in ("all out", "declared") and tot[last["team"]] < tot[last["bowling_team"]]:
        return {"type": "win", "winner": last["bowling_team"], "by": "innings",
                "margin": tot[last["bowling_team"]] - tot[last["team"]]}
    if len(inns) == 4 and last["ended"] == "target":
        return {"type": "win", "winner": last["team"], "by": "wickets", "margin": 10 - last["wickets"]}
    if len(inns) == 4 and last["ended"] == "all out":
        d = tot[last["bowling_team"]] - tot[last["team"]]
        return {"type": "tie", "winner": None} if d == 0 else \
            {"type": "win", "winner": last["bowling_team"], "by": "runs", "margin": d}
    return {"type": "draw", "winner": None}


def check_card(c: dict, captained: bool = False):
    """captained: a person had a side, who may take the new ball late."""
    assert c["format"] == "test"
    days, day_overs = c["scheduled_days"], c["day_overs"]
    inns = c["innings"]
    assert 1 <= len(inns) <= 4 and [i["number"] for i in inns] == list(range(1, len(inns) + 1))
    # ---- innings order: A, B, A, B, or A, B, B, A after a follow-on
    first, second = inns[0]["team"], inns[0]["bowling_team"]
    assert {first, second} == set(c["teams"])
    fo = len(inns) >= 3 and inns[2]["follow_on"]
    order = [first, second, second, first] if fo else [first, second, first, second]
    assert [i["team"] for i in inns] == order[:len(inns)], "innings out of order"
    assert not any(i["follow_on"] for k, i in enumerate(inns) if k != 2)
    mark = test_captain.follow_on_lead(days)
    if fo:
        assert inns[0]["runs"] - inns[1]["runs"] >= mark, "follow-on enforced without the lead for it"
    offers = [e for e in c["events"] if e["kind"] == "follow_on"]
    assert len(offers) == (1 if len(inns) >= 2 and inns[1]["ended"] in ("all out", "declared")
                           and inns[0]["runs"] - inns[1]["runs"] >= mark else 0)
    assert all(e["enforced"] == fo for e in offers)
    # ---- each innings: the bookkeeping
    running = {t: 0 for t in c["teams"]}
    for k, inn in enumerate(inns):
        assert inn["wickets"] <= 10
        assert sum(b["runs"] for b in inn["batting"]) + sum(inn["extras"].values()) == inn["runs"], \
            "batting + extras != total"
        assert sum(w["runs"] for w in inn["bowling"]) == inn["runs"] - inn["extras"]["b"] - inn["extras"]["lb"], \
            "bowling runs mismatch"
        assert sum(w["wickets"] for w in inn["bowling"]) == sum(
            1 for b in inn["batting"] if b["out"] and b["how_out"]["kind"] != "run_out"), "bowler wickets mismatch"
        assert sum(w["balls"] for w in inn["bowling"]) == inn["balls"], "bowler balls != innings balls"
        assert sum(1 for b in inn["batting"] if b["out"]) == inn["wickets"] == len(inn["fall_of_wickets"])
        assert sum(b["balls"] for b in inn["batting"]) == inn["balls"] + sum(w["noballs"] for w in inn["bowling"])
        fow = [f["runs"] for f in inn["fall_of_wickets"]]
        assert fow == sorted(fow), "fall of wickets out of order"
        log = inn["overs_log"]
        assert sum(o["runs"] for o in log) == inn["runs"] and sum(o["wkts"] for o in log) == inn["wickets"]
        assert len(log) == -(-inn["balls"] // 6) or (inn["balls"] % 6 == 0 and len(log) == inn["balls"] // 6 + 1)
        names = [o["bowler"] for o in log]
        for a, b in zip(names, names[1:]):
            assert a != b, f"{a} bowled two overs running"
        # (a keeper lost to injury is followed by another man, who may have bowled before he took the gloves)
        lost = any(e["kind"] in ("injury", "replacement") for e in c["events"])
        keeper = (next((b["name"] for b in inns[k - 1 if k else 1]["batting"] if b["keeper"]), None)
                  if len(inns) > 1 and not lost else None)
        assert keeper not in names, "the keeper bowled"
        assert [o["over"] for o in log] == list(range(1, len(log) + 1))
        when = [(o["day"], o["session"]) for o in log]
        assert when == sorted(when) and all(1 <= d <= days and 1 <= s <= 3 for d, s in when)
        assert inn["ended"] in ("all out", "declared", "target", "time")
        assert inn["declared"] == (inn["ended"] == "declared")
        if inn["declared"]:
            assert inn["wickets"] < 10 and inn["number"] < 4, "a declaration that cannot be"
        if inn["ended"] == "all out":        # ten wickets, less the men retired hurt
            hurt = sum(1 for b in inn["batting"] if b["dismissal"] == "retired hurt")
            assert inn["wickets"] == len(inn["batting"]) - 1 - hurt
            assert len(inn["batting"]) + len(inn.get("absent_hurt") or []) >= 11
        if inn["ended"] == "time":
            assert inn is inns[-1], "time ran out but another innings followed"
        other = inn["bowling_team"]
        running[inn["team"]] += inn["runs"]
        assert inn["lead"] == running[inn["team"]] - running[other]
        if inn["number"] == 4:
            assert inn["target"] == running[other] - (running[inn["team"]] - inn["runs"]) + 1
            assert inn["runs"] < inn["target"] + 6, "batted on after the target"
            assert (inn["ended"] == "target") == (inn["runs"] >= inn["target"])
        else:
            assert inn["target"] is None
        new_balls = [e for e in c["events"] if e["innings"] == inn["number"] and e["kind"] == "new_ball"]
        # a captain may keep the old ball (the computer's does as real captains do), never take one early
        assert len(new_balls) <= max(len(log) - 1, 0) // 80, "a new ball before it was due"
    # ---- time: never more than the scheduled overs
    bowled = sum(len(i["overs_log"]) for i in inns)
    lost = sum(d["lost"] for d in c["days"])
    assert bowled + lost <= days * day_overs, "more overs than the match has"
    assert lost == sum(e["overs"] for e in c["events"] if e["kind"] == "weather")
    assert sum(d["overs"] for d in c["days"]) == bowled
    assert [d["day"] for d in c["days"]] == list(range(1, len(c["days"]) + 1)) and len(c["days"]) <= days
    for d in c["days"]:
        assert d["overs"] + d["lost"] <= day_overs, "a day of more than its overs"
        assert d["overs"] or d["lost"] or d["day"] == len(c["days"]), "a day with nothing in it"
    per_day = {}
    for i in inns:
        for o in i["overs_log"]:
            per_day[o["day"]] = per_day.get(o["day"], 0) + 1
    assert per_day == {d["day"]: d["overs"] for d in c["days"] if d["overs"]}
    assert sum(d["runs"] for d in c["days"]) == sum(i["runs"] for i in inns)
    assert sum(d["wickets"] for d in c["days"]) == sum(i["wickets"] for i in inns)
    # ---- the result agrees with the scores
    r, want = c["result"], expected_result(c)
    for key, v in want.items():
        assert r.get(key) == v, f"result {r} but the scores say {want}"
    if r["type"] == "draw":
        assert r["text"] == "Match drawn"
        # a draw uses all the time: overs bowled, lost to the weather, or gone at a change of innings
        used = bowled + lost + 2 * len(inns)
        assert inns[-1]["ended"] == "time" or used >= days * day_overs, "a draw with time left"
    elif r["type"] == "tie":
        assert r["text"] == "Match tied"
    else:
        assert r["text"].startswith(f"{r['winner']} won by ") and r["loser"] in c["teams"]
    assert c["player_of_match"].get("name")
    assert len(c["events"]) == len([e for e in c["events"] if 1 <= e["day"] <= days + 1])


def test_laws_and_bookkeeping_over_300_tests():
    ind, aus, eng, nz = team("India", IND), team("Australia", AUS), team("England", ENG), team("New Zealand", NZ)
    seen = {"innings": 0, "runs": 0, "wickets": 0, "draw": 0, "declared": 0, "follow_on": 0, "nightwatchman": 0}
    n = 0
    plans = [(ind, aus, 150, {"year": 2023}), (eng, nz, 90, {"year": 2015, "venue": "Lord's, London"}),
             (aus, eng, 30, {"year": 2019, "days": 4}), (nz, ind, 30, {"year": 2021, "days": 3, "day_overs": 60})]
    for a, b, count, kw in plans:
        for seed in range(count):
            c = simulate_match(a, b, fmt="test", seed=seed, **kw)
            check_card(c)
            n += 1
            r = c["result"]
            seen[r.get("by") or r["type"]] = seen.get(r.get("by") or r["type"], 0) + 1
            seen["declared"] += sum(i["declared"] for i in c["innings"])
            seen["follow_on"] += any(i["follow_on"] for i in c["innings"])
            seen["nightwatchman"] += any(i["nightwatchmen"] for i in c["innings"])
    assert n == 300
    for k in ("innings", "runs", "wickets", "draw", "declared", "follow_on", "nightwatchman"):
        assert seen[k] > 0, f"300 Tests without a single {k}: {seen}"


def test_other_sides_and_switches():
    ind, aus = team("India", IND), team("Australia", AUS)
    # classic sides rated on their own years, in another era's conditions; unknown players; a squad of 13
    wi = team("West Indies", WI, years=[1980, 1988])
    check_card(simulate_match(wi, aus, fmt="test", year=1984, seed=3))
    nobodies = {"name": "Nobodies", "players": [{"id": f"nobody{i}", "name": f"Nobody {i}"} for i in range(11)]}
    c = simulate_match(nobodies, ind, fmt="test", year=2023, seed=4)
    check_card(c)
    assert c["result"]["winner"] == "India"
    squad = {"name": "India", "squad": _ids(IND + ["AM Rahane", "Kuldeep Yadav"])}
    c = simulate_match(squad, aus, fmt="test", year=2023, seed=5)
    check_card(c)
    assert len(c["xi"]["India"]) == 11
    for seed in range(40):
        c = simulate_match(ind, aus, fmt="test", year=2023, seed=seed, declare=False, follow_on=False,
                           nightwatchman=False, use_situation=False)
        check_card(c)
        assert not any(i["declared"] or i["follow_on"] or i["nightwatchmen"] for i in c["innings"])
    fixed = dict(ind, order=ind["players"])
    c = simulate_match(fixed, aus, fmt="test", year=2023, seed=6)
    for i in c["innings"]:
        if i["team"] == "India":
            assert not i["nightwatchmen"], "an explicit batting order is kept"


# ---------------------------------------------------------------------------------------------- forced results
SIDE_A = {"name": "Alphas", "players": [{"id": f"alpha{i}", "name": f"Alpha {i}"} for i in range(11)]}
SIDE_B = {"name": "Betas", "players": [{"id": f"beta{i}", "name": f"Beta {i}"} for i in range(11)]}


class Script:
    """Stands in for the ball model: each innings scores its planned runs in singles, then loses a wicket every
    ball (None = blocks every ball for ever)."""

    def __init__(self, m, plan: dict):
        self.m, self.plan = m, plan

    def delivery(self, rng, base, striker, bowler, phase, bowl_type, sit=None, free_hit=False):
        inn = self.m.innings[-1]
        want = self.plan.get(inn.number)
        if want is None:
            return Outcome(legal=True, faced=True)
        if inn.runs < want:
            return Outcome(legal=True, faced=True, bat_runs=1, ran=1)
        return Outcome(legal=True, faced=True, wicket="bowled")


def scripted(plan: dict, **kw) -> dict:
    kw.setdefault("declare", False)
    kw.setdefault("use_weather", False)
    m = TestMatch(SIDE_A, SIDE_B, seed=1, toss="a", decision="bat", **kw)
    m.model = Script(m, plan)
    c = m.play()
    check_card(c)
    return c


def order(c):
    return [i["team"][0] for i in c["innings"]]


def test_forced_results():
    c = scripted({1: 300, 2: 50, 3: 60}, follow_on=True)
    assert c["result"]["text"] == "Alphas won by an innings and 190 runs" and order(c) == ["A", "B", "B"]
    assert c["innings"][2]["follow_on"] and "(following on)" in c["innings"][2]["label"]

    c = scripted({1: 50, 2: 300, 3: 249})                 # no follow-on involved: the side batting first loses
    assert c["result"]["text"] == "Betas won by an innings and 1 run" and order(c) == ["A", "B", "A"]

    c = scripted({1: 100, 2: 100, 3: 100, 4: 60})
    assert c["result"]["text"] == "Alphas won by 40 runs" and c["result"]["by"] == "runs"

    c = scripted({1: 100, 2: 100, 3: 50, 4: 999})
    assert c["result"]["text"] == "Betas won by 10 wickets" and c["innings"][3]["runs"] == 51

    c = scripted({1: 100, 2: 100, 3: 50, 4: 50})
    assert c["result"] == {"type": "tie", "winner": None, "text": "Match tied"}

    c = scripted({1: 100, 2: 100, 3: 50, 4: 49})
    assert c["result"]["text"] == "Alphas won by 1 run"

    c = scripted({1: None}, days=1)                       # one day of blocking: no result is possible, and the
    assert c["result"]["type"] == "draw" and len(c["innings"]) == 1      # captains shake hands in the last hour
    assert c["innings"][0]["overs"] == "75.0" and any(e["kind"] == "agreed_draw" for e in c["events"])
    assert c["days"] == [{"day": 1, "overs": 75, "runs": 0, "wickets": 0, "innings": 1, "close": "Alphas 0/0",
                          "lost": 0}]
    c = scripted({1: None}, days=1, last_hour=False)      # ... or the last hour is played out
    assert c["result"]["type"] == "draw" and len(c["innings"]) == 1 and c["innings"][0]["overs"] == "90.0"
    assert c["days"] == [{"day": 1, "overs": 90, "runs": 0, "wickets": 0, "innings": 1, "close": "Alphas 0/0",
                          "lost": 0}]

    c = scripted({1: 20, 2: 20, 3: 20, 4: None})          # the last pair of the match block out for the draw
    assert c["result"]["text"] == "Match drawn" and len(c["innings"]) == 4 and c["innings"][3]["ended"] == "time"
    assert sum(len(i["overs_log"]) for i in c["innings"]) == 450 - 3 * 2
    assert len(c["days"]) == 5 and all(i["wickets"] == 10 for i in c["innings"][:3])


def test_follow_on_rules():
    c = scripted({1: 249, 2: 50, 3: 10, 4: 999}, follow_on=True)          # a lead of 199: not on offer
    assert order(c) == ["A", "B", "A", "B"] and not [e for e in c["events"] if e["kind"] == "follow_on"]
    c = scripted({1: 250, 2: 50, 3: 10, 4: 999}, follow_on=True)          # 200: on offer, enforced
    assert order(c)[:3] == ["A", "B", "B"]
    c = scripted({1: 300, 2: 50, 3: 10, 4: 100}, follow_on=False)         # on offer, declined
    assert order(c) == ["A", "B", "A", "B"] and c["result"]["text"] == "Alphas won by 160 runs"
    assert [e["enforced"] for e in c["events"] if e["kind"] == "follow_on"] == [False]
    c = scripted({1: 300, 2: 50, 3: 400, 4: 100}, follow_on=True)         # following on and winning
    assert order(c) == ["A", "B", "B", "A"] and c["result"]["text"] == "Betas won by 50 runs"
    c = scripted({1: 300, 2: 50, 3: 260, 4: 999}, follow_on=True)         # ... and the side that enforced it wins
    assert c["result"]["text"] == "Alphas won by 10 wickets" and c["innings"][3]["target"] == 11
    c = scripted({1: 200, 2: 50, 3: 10, 4: 999}, follow_on=True, days=4)  # a four-day match: 150 is enough
    assert order(c)[:3] == ["A", "B", "B"]
    assert [test_captain.follow_on_lead(d) for d in (1, 2, 3, 4, 5, 6)] == [75, 100, 150, 150, 200, 200]
    # the fitted chance of enforcing it rises with the lead and is nil below the mark
    p = [test_captain.follow_on_prob(lead, 300, 60) for lead in (199, 200, 300, 450)]
    assert p[0] == 0.0 and 0 < p[1] < p[2] < p[3] < 1


def test_seed_reproduces_a_match():
    a, b = team("India", IND), team("Australia", AUS)
    x = simulate_match(a, b, fmt="test", year=2023, seed=42)
    y = simulate_match(a, b, fmt="test", year=2023, seed=42)
    z = simulate_match(a, b, fmt="test", year=2023, seed=43)
    assert x == y, "the same seed must give the same Test"
    assert x["innings"][0]["overs_log"] != z["innings"][0]["overs_log"]
    assert x["seed"] == 42 and isinstance(simulate_match(a, b, fmt="test", year=2023)["seed"], int)


def test_dispatch_and_text_scorecard():
    a, b = team("India", IND), team("Australia", AUS)
    try:
        Match("test", a, b)
        raise AssertionError("Match must refuse a Test: simulate_match is the one way in")
    except ValueError:
        pass
    c = next(c for c in (simulate_match(a, b, fmt="test", year=2023, seed=s) for s in range(50))
             if len(c["innings"]) == 4 and any(i["declared"] for i in c["innings"]))
    text = scorecard_text(c)
    for inn in c["innings"]:
        assert inn["label"] in text
        for bat in inn["batting"]:
            if bat["batted"]:
                assert bat["name"] in text
    assert text.count("  TOTAL") == 4 and " dec," in text and "Close of play" in text
    assert f"(target {c['innings'][3]['target']})" in text and f"Result: {c['result']['text']}" in text
    assert all(f"Day {d['day']}: " in text for d in c["days"])
    assert c["result"]["text"] in full_text(c)


def test_clock():
    c = Clock(5, 90)
    assert (c.left, c.left_today, c.session) == (450, 90, 1)
    assert c.spend(29) == [] and c.session == 1
    assert c.spend(1) == [(0, 1)] and c.session == 2          # lunch
    assert c.spend(2) == [] and c.spend(28) == [(1, 1)] and c.session == 3
    assert c.spend(29) == [] and c.spend(2) == [(2, 1)]       # stumps: what is left of the day is not carried over
    assert (c.day, c.used, c.left) == (2, 0, 360)
    for _ in range(4):
        c.spend(90)
    assert c.left == 0 and c.day == 6


def test_tables_and_captains_calls():
    s = TestSituation()
    t = s.t
    assert t["settle_edges"] == [10, 30, 60, 120, 200] and t["wear_edges"] == [90, 180, 270, 360]
    assert t["age_edges"] == [10, 20, 40, 60] and t["balls"] > 1_500_000
    assert s.cell(1, 0, 0) == (1, 0, 3) and s.cell(3, 7, -250) == (3, 2, 0) and s.cell(4, 4, 0, 300, 100)[0] == 4
    m = s.multipliers(s.cell(2, 4, -50), 5, "spin", 200, 30)
    assert set(m) == {"runs", "wkt", "dot", "four", "six"} and all(0.3 < v < 3 for v in m.values())
    assert s.multipliers(s.cell(2, 4, -50), 5, None, 200, 30) != m          # an unknown bowler: no wear, no age
    # a batter's first ten balls are his slowest
    runs = [row[0] for row in t["settle"]]
    assert runs[0] == min(runs) and runs[0] < 0.95
    # saving the match: eight down needing ten an over is slower going than two down needing two
    assert s.mode(8, 300, 30) == "save" and s.mode(1, 40, 60) != "save"
    # declarations: never below the lowest lead anyone has declared at, never ten down, likelier with a bigger
    # lead, less likely with a batter in the nineties
    d = test_captain.declare_prob
    assert d(3, 100, 20, 3, 200, False) == 0.0 and d(3, 300, 400, 10, 100, False) == 0.0
    assert 0 < d(3, 250, 300, 5, 120, False) < d(3, 350, 400, 5, 120, False) < d(3, 450, 500, 5, 120, False) < 1
    assert d(3, 350, 400, 5, 120, True) < d(3, 350, 400, 5, 120, False)
    assert d(1, 200, 200, 3, 400, False) == 0.0 and d(1, 650, 650, 8, 250, False) > d(1, 450, 450, 4, 320, False) > 0
    # the nightwatchman: a top-six batter due with six overs or fewer left, and a lower-order man to send
    cards = [type("C", (), {"p": type("P", (), {"bat": {"all": {"wkt": w}}})()})() for w in
             (1, 1, 1, 1, 1, 1, 1, 1.4, 1.2, 1.6, 2.0)]
    nw = test_captain.nightwatchman
    assert nw(cards, 2, 6) == 8 and nw(cards, 2, 7) is None and nw(cards, 6, 3) is None and nw(cards[:7], 3, 2) is None
    assert 0.5 < test_captain.tables()["toss"]["p_bat"] < 0.9


def main():
    tests = [(k, v) for k, v in globals().items() if k.startswith("test_") and callable(v)]
    for name, fn in tests:
        fn()
        print(f"ok   {name}")
    print(f"{len(tests)} tests passed")


if __name__ == "__main__":
    main()
