"""Tests for Test records and the win / draw / loss table: the chances on a scorecard, each player's impact, the
turning point, the rankings of a series (Phase 5 of docs/test_match_plan.md).

    python tests/test_test_records.py          (no pytest needed; also works under pytest)
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from engine import match_report, simulate_match  # noqa: E402
from engine.test_records import test_records  # noqa: E402
from engine.test_series import play_test_series  # noqa: E402
from engine.test_wdl import table, turning_point  # noqa: E402
from test_test_engine import AUS, IND, team  # noqa: E402


def _sides():
    return team("India", IND), team("Australia", AUS)


def test_wdl_probabilities_are_probabilities():
    t = table()
    assert t is not None, "data/engine/wdl_test.json is missing: python -m engine.fit.fit_wdl"
    rng = random.Random(1)
    for _ in range(5000):
        i, w = rng.randint(1, 4), rng.randint(0, 9)
        x = rng.randint(-700, 0) if i == 4 else rng.randint(-700, 700)
        left = rng.uniform(0, 450)
        pw, pd = t.probs(i, w, x, left)
        pl = 1 - pw - pd                                  # the three chances sum to 1 by construction
        assert 0 <= pw <= 1 and 0 <= pd <= 1 and pl >= -1e-9, (i, w, x, left, pw, pd)
        v = t.value(i, w, x, left)
        assert abs(v - (pw + pd / 2)) < 0.02 and 0 <= v <= 1
    for i in (1, 2, 3, 4):
        assert t.probs(i, 3, -50, 0) == (0.0, 1.0), "no time left is a draw"
    assert t.probs(4, 5, 0, 40)[0] == 1.0, "nothing left to get is a win"
    assert 250 < t.runs_per_win < 3000, t.runs_per_win


def test_wdl_moves_the_right_way():
    t = table()
    win = lambda *s: t.probs(*s)[0]
    draw = lambda *s: t.probs(*s)[1]
    # the last innings: fewer runs to get, or more wickets in hand, is a better chance of winning
    assert win(4, 4, -60, 80) > win(4, 4, -200, 80) > win(4, 4, -350, 80)
    assert win(4, 2, -150, 80) > win(4, 5, -150, 80) > win(4, 8, -150, 80)
    # a side far behind with wickets falling is likelier to save the match the less time is left
    assert draw(4, 7, -400, 10) > draw(4, 7, -400, 60) and draw(4, 4, -450, 20) > draw(4, 4, -450, 120)
    # with plenty of time, a hopeless chase is lost, an easy one is won
    assert win(4, 8, -400, 200) < 0.05 and win(4, 1, -40, 200) > 0.9
    # earlier innings: a bigger lead is better for the batting side, wickets lost are worse
    assert t.value(3, 0, 200, 250) > t.value(3, 0, 0, 250) > t.value(3, 0, -200, 250)
    assert t.value(2, 2, -100, 330) > t.value(2, 7, -100, 330)
    assert t.value(1, 2, 300, 360) > t.value(1, 8, 150, 360)
    # two equal sides start level, and a first-innings lead with little time left is mostly a draw
    assert 0.4 < t.value(1, 0, 0, 450) < 0.6
    assert draw(2, 3, -150, 40) > 0.7


def test_card_chances_impact_and_turning_point():
    ind, aus = _sides()
    k = table().runs_per_win
    swings = []
    for seed in range(8):
        c = simulate_match(ind, aus, fmt="test", year=2023, venue="Wankhede Stadium, Mumbai", seed=seed)
        plain = simulate_match(ind, aus, fmt="test", year=2023, venue="Wankhede Stadium, Mumbai", seed=seed,
                               use_wdl=False)
        # the table only reads the match: the same seed plays the same Test with or without it
        assert plain["result"] == c["result"] and "impact" not in plain
        assert [(i["runs"], i["wickets"], i["balls"]) for i in plain["innings"]] == \
               [(i["runs"], i["wickets"], i["balls"]) for i in c["innings"]]
        first = c["innings"][0]["team"]
        last = None
        for inn in c["innings"]:
            for o in inn["overs_log"]:
                a, d = o["wdl"]
                assert 0 <= a <= 1 and 0 <= d <= 1 and a + d <= 1.002, o
                assert o["left"] >= 0
                last = o
        win = c["result"].get("winner")
        assert last["wdl"] == [float(win == first), float(not win)], "the chart ends at the result"
        # impact: what one side gains the other loses
        assert abs(sum(c["impact"].values())) < 0.02, sum(c["impact"].values())
        by_team = {t: sum(c["impact"].get(p["id"], 0) for p in xi) for t, xi in c["xi"].items()}
        if win:
            assert by_team[win] > 0, by_team
        pom = c["player_of_match"]
        score = {pid: sum(v) + k * c["impact"].get(pid, 0) for pid, v in c["points"].items()}
        assert pom["id"] == max(score, key=score.get) and pom["impact"] == c["impact"].get(pom["id"])
        tp = c["turning_point"]
        assert tp == turning_point(c) and tp["towards"] in c["teams"] and 0 < tp["swing"] <= 1
        assert 1 <= tp["session"] <= 3 and 1 <= tp["day"] <= 5
        assert any(e["kind"] == "turning_point" and e["text"] == tp["text"] for e in c["events"])
        assert f"on day {tp['day']}, when {tp['team']} went from" in match_report(c)
        if win:
            assert tp["towards"] == win, "the turning point is the biggest swing towards the winner"
        swings.append(tp["swing"])
    assert max(swings) > 0.1, swings


def test_records_match_the_scorecards():
    ind, aus = _sides()
    r = play_test_series(ind, aus, n=5, year=2023, seed=11)
    cards, rec = r["matches"], r["records"]
    assert rec == test_records(cards)
    inns = [(c, i) for c in cards for i in c["innings"]]
    scores = [(c, i, b) for c, i in inns for b in i["batting"] if b["batted"]]
    assert rec["highest_totals"][0]["runs"] == max(i["runs"] for _, i in inns)
    h = rec["hundreds"]
    assert h["hundreds"] == sum(b["runs"] >= 100 for *_, b in scores)
    assert h["doubles"] == sum(b["runs"] >= 200 for *_, b in scores)
    assert h["triples"] == sum(b["runs"] >= 300 for *_, b in scores)
    assert [x["runs"] for x in h["list"]] == sorted((b["runs"] for *_, b in scores if b["runs"] >= 100), reverse=True)[:10]
    assert rec["longest_innings"][0]["balls"] == max(b["balls"] for *_, b in scores)
    # match figures: both innings of a bowler added up
    agg = {}
    for c, i in inns:
        for w in i["bowling"]:
            a = agg.setdefault((c["match_no"], w["id"]), [0, 0])
            a[0] += w["wickets"]
            a[1] += w["runs"]
    best = max(agg.values(), key=lambda a: (a[0], -a[1]))
    top = rec["best_match_bowling"][0]
    assert [top["wickets"], top["runs"]] == best
    assert len(rec["ten_wicket_matches"]) == min(10, sum(a[0] >= 10 for a in agg.values()))
    assert all(x["wickets"] >= 10 for x in rec["ten_wicket_matches"])
    # the best partnership for each wicket
    for p in rec["best_partnerships"]:
        assert p["runs"] == max(q["runs"] for _, i in inns for q in i["partnerships"] if q["wkt"] == p["wkt"])
    assert [p["wkt"] for p in rec["best_partnerships"]] == sorted({q["wkt"] for _, i in inns for q in i["partnerships"]})
    chases = [i for _, i in inns if i.get("ended") == "target"]
    assert len(rec["highest_successful_chases"]) == len(chases)
    if chases:
        assert rec["highest_successful_chases"][0]["runs"] == max(i["runs"] for i in chases)
    for by, key in (("innings", "biggest_wins_by_an_innings"), ("wickets", "biggest_wins_by_wickets"),
                    ("wickets", "narrowest_wins_by_wickets"), ("runs", "biggest_wins_by_runs")):
        assert len(rec[key]) == sum(c["result"].get("by") == by for c in cards), key
    assert len(rec["hat_tricks"]) == sum(e["kind"] == "hat_trick" for c in cards for e in c["events"])
    carried = [b for c, i, b in scores if b["position"] <= 2 and not b["out"] and i["ended"] == "all out"
               and i["wickets"] >= 10]
    assert len(rec["carried_bat"]) == len(carried)
    twins = sum(1 for c in cards for pid in {b["id"] for i in c["innings"] for b in i["batting"]}
                if sum(b["runs"] >= 100 for i in c["innings"] for b in i["batting"] if b["id"] == pid) >= 2)
    assert len(rec["hundred_in_each_innings"]) == twins
    for rows in rec.values():
        for x in (rows["list"] if isinstance(rows, dict) else rows):
            assert 1 <= x["match_no"] <= 5 and x["stage"].endswith("Test")


def test_rare_records_are_found():
    """Carrying the bat, a hundred in each innings and a hat-trick are rare: build the scorecards by hand."""
    def bat(pid, pos, runs, out=True):
        return {"id": pid, "name": pid.upper(), "position": pos, "runs": runs, "balls": 2 * runs + 1, "fours": 0,
                "sixes": 0, "out": out, "batted": True}

    def inn(n, t, vs, bats, ended="all out"):
        return {"number": n, "team": t, "bowling_team": vs, "runs": sum(b["runs"] for b in bats),
                "wickets": sum(b["out"] for b in bats), "overs": "50", "ended": ended, "batting": bats,
                "bowling": [{"id": "bw" + vs, "name": "BOWLER " + vs, "wickets": 6, "runs": 40, "overs": "20"}],
                "partnerships": [{"wkt": 1, "runs": 30, "balls": 60, "batters": ["A", "B"], "split": [10, 20]}]}
    rest = [bat(f"x{k}", k, 5) for k in range(3, 12)]
    card = {"match_no": 1, "stage": "Only Test", "teams": ["P", "Q"],
            "innings": [inn(1, "P", "Q", [bat("a", 1, 130, out=False), bat("b", 2, 4)] + rest),
                        inn(2, "Q", "P", [bat("c", 1, 20), bat("d", 2, 30)] + rest),
                        inn(3, "P", "Q", [bat("a", 1, 101), bat("b", 2, 9)] + rest)],
            "events": [{"kind": "hat_trick", "innings": 2, "over": "30.2", "text": "Hat-trick for BOWLER P!"}],
            "result": {"type": "win", "winner": "P", "loser": "Q", "by": "runs", "margin": 200, "text": "P won by 200 runs"}}
    rec = test_records([card])
    assert [(x["name"], x["runs"], x["total"]) for x in rec["carried_bat"]] == [("A", 130, 179)]
    assert [(x["name"], x["scores"]) for x in rec["hundred_in_each_innings"]] == [("A", ["130*", "101"])]
    assert [(x["name"], x["team"], x["vs"]) for x in rec["hat_tricks"]] == [("BOWLER P", "P", "Q")]
    m = rec["best_match_bowling"][0]
    assert (m["name"], m["wickets"], m["runs"], m["innings"]) == ("BOWLER Q", 12, 80, ["6/40", "6/40"])
    assert len(rec["ten_wicket_matches"]) == 1 and rec["hundreds"]["hundreds"] == 2


def test_series_rankings():
    ind, aus = _sides()
    r = play_test_series(ind, aus, n=3, year=2023, seed=5)
    cards, mvp = r["matches"], r["mvp"]
    assert mvp["kind"] == "test"
    off, bal = mvp["official"], mvp["balanced"]
    assert r["player_of_series"]["id"] == off[0]["id"]
    assert all(a["score"] >= b["score"] for a, b in zip(off, off[1:])), "the official ranking is by score"
    k = cards[0]["runs_per_win"]
    assert all(abs(p["score"] - (p["balanced"] + k * p["impact"])) < 1.0 for p in off)
    assert all(a["balanced"] >= b["balanced"] for a, b in zip(bal, bal[1:]))
    assert [p["rank"] for p in off] == list(range(1, len(off) + 1)) and len(off) == len(bal)
    for p in off[:5] + off[-5:]:
        tot = sum(c["impact"].get(p["id"], 0) for c in cards)
        assert abs(p["impact"] - tot) < 0.005, (p["name"], p["impact"], tot)


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)
             and v.__module__ == __name__]
    for fn in tests:
        fn()
        print(f"ok   {fn.__name__}")
    print(f"{len(tests)} tests passed")


if __name__ == "__main__":
    main()
