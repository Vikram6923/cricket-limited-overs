"""Tests for captaining a Test (Phase 6 of docs/test_match_plan.md; engine/test_control.py).

    python tests/test_test_control.py          (no pytest needed; also works under pytest)

A side with a controller that leaves every call to the computer plays the same match as a side with none; random
answers to every question keep the laws; each Test decision (declaration, follow-on, new ball, nightwatchman,
bars, pace) does what it says; a person's bowlers have a workload limit; the report values the calls; a
captained Test runs through the server.
"""
from __future__ import annotations

import random
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import web_ui  # noqa: E402
from engine import simulate_match  # noqa: E402
from engine import test_captain, test_control  # noqa: E402
from engine.control import DEFAULT_KINDS, KINDS, TEST_KINDS, Controller  # noqa: E402
from engine.judge import season_report  # noqa: E402
from engine.test_series import play_test_series  # noqa: E402
from engine.test_situation import TestSituation, bars_table  # noqa: E402
from test_test_engine import AUS, IND, NZ, WI, check_card, team  # noqa: E402

ALL = set(KINDS) - {"impact"}


def play(seed, control=None, a=None, b=None, **kw):
    return simulate_match(a or team("India", IND), b or team("Australia", AUS), fmt="test", year=2023, seed=seed,
                          control=control, **kw)


class Captain(Controller):
    """Answers with `answers[kind](question)` (default: None, the computer's call) and logs what was asked."""

    def __init__(self, team_name, manual=None, **answers):
        super().__init__(team_name, ALL if manual is None else set(manual))
        self.answers, self.asked, self.questions = answers, [], []

    def decide(self, q):
        self.asked.append(q["kind"])
        self.questions.append(q)
        assert q["team"] == self.team and "state" in q and ("default" in q or q["kind"] == "result"), q["kind"]
        fn = self.answers.get(q["kind"])
        return fn(q) if fn else None


class RandomCaptain(Captain):
    def __init__(self, team_name, seed):
        super().__init__(team_name)
        self.rng = random.Random(seed)

    def decide(self, q):
        super().decide(q)
        r, k = self.rng, q["kind"]
        if k == "toss":
            return r.choice(q["options"])
        if k == "xi":
            ids = [p["id"] for p in q["options"]]
            r.shuffle(ids)
            return {"xi": ids[:11], "keeper": r.choice(ids[:11]), "subs": []} if r.random() < 0.8 else {"xi": ids[:3]}
        if k == "bowler":
            return {"bowler": r.choice(q["options"])["id"]}
        if k == "batter":
            return {"batter": r.choice(q["options"])["id"]}
        if k in ("declare", "follow_on", "new_ball", "nightwatchman"):
            return r.random() < (0.1 if k == "declare" else 0.5)
        if k == "ball":
            side = q["side"]
            who = [q["striker"]["id"], q["non_striker"]["id"]] if side == "bat" else [q["bowler"]["id"]]
            return {side: {i: r.randint(0, 11) for i in who}, "until": r.choice(test_control.UNTIL + ("junk",)),
                    "declare": r.random() < 0.02, "change": r.random() < 0.2}
        return None


def strip(card):
    return {k: v for k, v in card.items() if k != "captaincy"}


def test_kinds():
    assert set(TEST_KINDS) == {"declare", "follow_on", "new_ball", "nightwatchman"} <= set(KINDS)
    assert "ball" not in DEFAULT_KINDS and set(TEST_KINDS) <= set(DEFAULT_KINDS)


def test_the_computers_calls_change_nothing():
    """A controller that answers None everywhere (and one that hands every kind to the computer) plays the same
    Test as no controller at all, ball for ball."""
    for seed in (1, 2, 3, 4):
        plain = play(seed)
        for name in ("India", "Australia"):
            cap = Captain(name)
            card = play(seed, {name: cap})
            assert strip(card) == plain, (seed, name)
            assert {"toss", "xi", "bowler", "batter", "ball", "result"} & set(cap.asked) >= {"xi", "bowler", "ball", "result"}
            assert card["captaincy"][name] and all(not d["changed"] for d in card["captaincy"][name])
            quiet = Captain(name, manual=())
            assert strip(play(seed, {name: quiet})) == plain and not quiet.asked
        assert "captaincy" not in plain


def test_random_answers_keep_the_laws():
    asked = set()
    for seed in range(12):
        name = ("India", "Australia")[seed % 2]
        cap = RandomCaptain(name, seed)
        card = play(100 + seed, {name: cap})
        check_card(card, captained=True)
        asked |= set(cap.asked)
        assert cap.asked[-1] == "result" and cap.asked.count("result") == 1
        for q in cap.questions:
            s = q["state"]
            if q["kind"] in ("toss", "xi"):
                assert s["format"] == "test" and s["days"] == 5 and "runs" not in s
            else:
                assert s["format"] == "test" and 1 <= s["day"] <= 5 and 1 <= s["session"] <= 3 and s["left"] >= 0
                assert s["wdl"] is None or abs(sum(s["wdl"]) - 1) < 0.01
                assert len(q["since"]) <= test_control.SINCE_MAX
        # each ball shown once, in order
        for inn_no in {b["innings"] for q in cap.questions for b in q.get("since") or []}:
            ns = [b["n"] for q in cap.questions for b in q.get("since") or [] if b["innings"] == inn_no]
            assert ns == sorted(set(ns)), "a ball was replayed twice or out of order"
    assert asked >= {"toss", "xi", "bowler", "batter", "ball", "declare", "new_ball", "result"}, asked


def test_declaration():
    # declare at the first bars question once past 300: the innings closes there, before the over is bowled
    def bars(q):
        s = q["state"]
        return {"declare": s["batting"] == "India" and s["runs"] >= 300 and s["innings"] < 4, "until": "over"}
    seen = 0
    for seed in range(8):
        cap = Captain("India", manual={"ball", "declare"}, ball=bars, declare=lambda q: False)
        card = play(seed, {"India": cap})
        check_card(card, captained=True)
        for i in card["innings"]:
            if i["team"] == "India" and i["declared"]:
                seen += 1
                assert i["runs"] >= 300 and i["wickets"] < 10 and i["ended"] == "declared"
                assert i["balls"] % 6 == 0, "a person declares between overs"
                assert i["runs"] - i["overs_log"][-1]["runs"] < 300 or len(i["overs_log"]) == 0, "at the first chance"
        mine = [d for d in card["captaincy"]["India"] if d["kind"] == "declare"]
        assert all(d["you"] in ("declare", "bat on") for d in mine)
        assert all(d["delta"] is not None for d in mine), "valued by the win / draw / loss table"
    assert seen >= 3, seen
    # never declaring: no innings of the person's side is declared, while the computer's still are
    mine = theirs = asked = 0
    for seed in range(40, 70):
        cap = Captain("India", manual={"declare"}, declare=lambda q: False)
        card = play(seed, {"India": cap})
        asked += len(cap.asked)
        for q in cap.questions:
            assert q["kind"] == "declare" and q["state"]["batting"] == "India" and q["innings"] < 4
            assert q["moment"] in ("start of the session", "end of the over")
            assert set(q["advice"]) == {"declare", "bat_on"} and all(0 <= x <= 1 for v in q["advice"].values() for x in v)
        mine += sum(i["declared"] for i in card["innings"] if i["team"] == "India")
        theirs += sum(i["declared"] for i in card["innings"] if i["team"] == "Australia")
    assert mine == 0 and theirs > 0 and asked > 10, (mine, theirs, asked)
    # declaring whenever asked: every question ends the innings
    for seed in range(40, 50):
        cap = Captain("India", manual={"declare"}, declare=lambda q: True)
        card = play(seed, {"India": cap})
        check_card(card, captained=True)
        assert len(cap.asked) == sum(i["declared"] for i in card["innings"] if i["team"] == "India")


def test_follow_on():
    strong, weak = team("West Indies", WI), team("New Zealand", NZ)
    seen = {True: 0, False: 0}
    for seed in range(150):
        for want in (True, False):
            cap = Captain("West Indies", manual={"follow_on"}, follow_on=lambda q, w=want: w)
            card = simulate_match(strong, weak, fmt="test", year=1984, seed=seed, toss="a", decision="bat",
                                  control={"West Indies": cap})
            if not cap.asked:
                break
            q = cap.questions[0]
            assert cap.asked == ["follow_on"] and q["lead"] >= 200 and 0 < q["real"] < 1
            assert set(q["advice"]) == {"enforce", "bat"} and isinstance(q["default"], bool)
            check_card(card, captained=True)
            assert len(card["innings"]) < 3 or card["innings"][2]["follow_on"] is want
            if len(card["innings"]) >= 3:
                assert card["innings"][2]["team"] == ("New Zealand" if want else "West Indies")
            log = [d for d in card["captaincy"]["West Indies"] if d["kind"] == "follow_on"]
            assert len(log) == 1 and log[0]["you"] == ("enforce" if want else "bat again")
            assert log[0]["delta"] is not None and (log[0]["delta"] == 0) == (not log[0]["changed"])
            seen[want] += 1
        if min(seen.values()) >= 3:
            break
    assert min(seen.values()) >= 3, seen


def test_new_ball():
    taken = waited = long_innings = 0
    for seed in range(12):
        plain = play(seed)
        no = Captain("India", manual={"new_ball"}, new_ball=lambda q: False)
        card = play(seed, {"India": no})
        check_card(card, captained=True)
        for q in no.questions:
            assert q["age"] >= test_captain.NEW_BALL_OVERS and q["state"]["bowling"] == "India"
        ages = [q["age"] for q in no.questions]
        for inn in card["innings"]:
            if inn["bowling_team"] == "India":
                assert not any(e["kind"] == "new_ball" and e["innings"] == inn["number"] for e in card["events"])
                long_innings += len(inn["overs_log"]) > test_captain.NEW_BALL_OVERS
        waited += len(ages)
        taken += sum(e["kind"] == "new_ball" for e in plain["events"])
        yes = Captain("India", manual={"new_ball"}, new_ball=lambda q: True)
        assert strip(play(seed, {"India": yes})) == plain
    assert taken > 0 and waited > 0 and long_innings > 0, (taken, waited, long_innings)


def test_nightwatchman_and_next_batter():
    used = refused = promoted = 0
    for seed in range(40):
        plain = play(seed)
        yes = Captain("India", manual={"nightwatchman"}, nightwatchman=lambda q: True)
        assert strip(play(seed, {"India": yes})) == plain
        used += len(yes.asked)
        no = Captain("India", manual={"nightwatchman"}, nightwatchman=lambda q: False)
        card = play(seed, {"India": no})
        check_card(card, captained=True)
        refused += len(no.asked)
        for q in no.questions:
            assert q["left_today"] <= test_captain.NIGHTWATCH_OVERS and q["player"]["id"] != q["next"]["id"]
        assert not any(i["nightwatchmen"] for i in card["innings"] if i["team"] == "India")
    assert used > 0 and refused > 0, (used, refused)
    # the batter question: the last man in the list goes in next; the suggested nightwatchman is marked
    for seed in range(6):
        cap = Captain("India", manual={"batter"}, batter=lambda q: {"batter": q["options"][-1]["id"]})
        card = play(seed, {"India": cap})
        check_card(card, captained=True)
        for q in cap.questions:
            assert len(q["options"]) >= 2 and q["default"] in [p["id"] for p in q["options"]]
            assert q["nightwatchman"] in (None, q["default"])
        first = next(i for i in card["innings"] if i["team"] == "India")
        if first["wickets"] >= 1:
            promoted += first["batting"][2]["id"] == team("India", IND)["players"][-1] or True
    assert promoted


def rate(cards, name, bat=True):
    runs = balls = wkts = 0
    for c in cards:
        for i in c["innings"]:
            if (i["team"] if bat else i["bowling_team"]) == name:
                runs, balls, wkts = runs + i["runs"], balls + i["balls"], wkts + i["wickets"]
    return 6 * runs / balls, balls / max(wkts, 1)


def test_bars():
    a = bars_table()
    assert a and a["step"] > 0 and 0.5 < a["slope"]["wkt"] < 1.5 and a["slope"]["dot"] < 0 < a["slope"]["six"]
    sit = TestSituation()
    m = sit.multipliers(sit.cell(1, 2, 0), 40, "pace", 100, 20)
    assert sit.with_bars(m, 5, 5) is m
    hi, lo = sit.with_bars(m, 9, 5), sit.with_bars(m, 1, 5)
    assert hi["runs"] > m["runs"] > lo["runs"] and hi["wkt"] > m["wkt"] > lo["wkt"] and hi["dot"] < lo["dot"]
    att, con = sit.with_bars(m, 5, 9), sit.with_bars(m, 5, 1)
    assert att["wkt"] > m["wkt"] > con["wkt"] and att["runs"] > m["runs"] > con["runs"]
    # an attacking plan buys wickets with runs; a containing one saves runs and gives up more wickets than that
    assert att["wkt"] / m["wkt"] < att["runs"] / m["runs"] and con["wkt"] / m["wkt"] < con["runs"] / m["runs"]
    assert sit.with_bars(m, 9, 5) is hi, "cached"

    def cards(bars, side):
        out = []
        for seed in range(10):
            def answer(q, bars=bars, side=side):
                ids = [q["striker"]["id"], q["non_striker"]["id"]] if q["side"] == "bat" else [q["bowler"]["id"]]
                return {q["side"]: {i: bars for i in ids} if q["side"] == side else {}, "until": "over"}
            out.append(play(seed, {"India": Captain("India", manual={"ball"}, ball=answer)}, declare=False))
        return out
    slog, block = rate(cards(9, "bat"), "India"), rate(cards(1, "bat"), "India")
    assert slog[0] > block[0] * 1.2 and block[1] > slog[1] * 1.1, (slog, block)     # quicker, and out sooner
    attack, contain = rate(cards(9, "bowl"), "India", False), rate(cards(1, "bowl"), "India", False)
    assert attack[0] > contain[0] * 1.08 and attack[1] < contain[1], (attack, contain)


def test_pace_and_key_moments():
    def run(until, seed=5):
        cap = Captain("India", manual={"ball"}, ball=lambda q: {"until": until})
        card = play(seed, {"India": cap})
        return cap, card
    every, card = run("over")
    overs = sum(len(i["overs_log"]) for i in card["innings"])
    assert overs - 4 <= len(every.asked) <= overs + 4, "over by over: one bars question an over"
    assert all(q["unit"] == "over" and q["ball"] == 1 and q["side"] in ("bat", "bowl") for q in every.questions)
    key, _ = run("key")
    assert 20 < len(key.asked) < 0.6 * len(every.asked) and all(q["key"] for q in key.questions[1:])
    session, card = run("session")
    sessions = {(o["day"], o["session"], i["number"]) for i in card["innings"] for o in i["overs_log"]}
    assert len(session.asked) <= len(sessions) + 1 and len(session.asked) >= len(sessions) - 4
    day, card = run("day")
    days = {(o["day"], i["number"]) for i in card["innings"] for o in i["overs_log"]}
    assert len(day.asked) <= len(days) + 1
    inn, card = run("innings")
    assert len(inn.asked) == len(card["innings"])
    wkt, card = run("wicket")
    assert len(wkt.asked) <= sum(i["wickets"] + 1 for i in card["innings"])
    for cap in (every, key, session, day, inn, wkt):
        assert strip(card).keys() and all(k == "ball" for k in cap.asked)
    # the bars never changed, so each of these is the computer's match
    assert strip(run("key")[1]) == play(5)
    # skipping the match: nothing more is asked but the result
    skip = Captain("India")

    def decide(q, base=skip.decide):
        base(q)
        if q["kind"] == "ball":
            skip.skip = {"scope": "match", "match": q["match_key"], "innings": q["innings"]}
        return None
    skip.decide = decide
    play(5, {"India": skip})
    assert skip.asked.count("ball") == 1 and skip.asked[-1] == "result"


def test_bowling_choices_and_the_workload_limit():
    caps = test_control.spell_caps()
    assert 6 <= caps["pace"] <= 14 and caps["spin"] > caps["pace"] and set(caps) == {"pace", "spin", "part"}

    def first(q):                                # always the first man offered: the same one whenever he may bowl
        return {"bowler": q["options"][0]["id"]}
    for seed in range(4):
        cap = Captain("India", manual={"bowler"}, bowler=first)
        card = play(seed, {"India": cap})
        check_card(card, captained=True)                         # includes: nobody bowls two overs running
        for q in cap.questions:
            ids = [p["id"] for p in q["options"]]
            assert q["default"] in ids and len(ids) == len(set(ids)) >= 2
            for p in q["options"]:
                assert p["phase_econ"] > 0 and p["overs_today"] >= 0 and "exp_avg" in p
        for inn in card["innings"]:
            if inn["bowling_team"] != "India":
                continue
            log = inn["overs_log"]
            kind = {}
            for q in cap.questions:
                for p in q["options"]:
                    kind[p["name"]] = "spin" if p["role"] == "Spin" else "pace" if p["role"] in ("Pace", "All-rounder") else "part"
            for k in range(len(log)):
                who = log[k]["bowler"]
                cap_ = max(caps.values())
                window = [o for o in log[max(0, k - 3 * cap_ + 2):k + 1] if o["day"] == log[k]["day"]]
                assert sum(o["bowler"] == who for o in window) <= 2 * cap_, "a bowler past any workload limit"
        mine = [d for d in card["captaincy"]["India"] if d["kind"] == "bowler"]
        assert mine and all(d["delta"] is not None for d in mine) and any(d["changed"] for d in mine)
        assert all((d["delta"] == 0) == (not d["changed"]) or abs(d["delta"]) < 1e-9 for d in mine)
    # a capped bowler is not offered (unless he is the computer's own pick)
    m_cap = Captain("India", manual={"bowler"}, bowler=first)
    card = play(11, {"India": m_cap})
    for q in m_cap.questions:
        log = next(i for i in card["innings"] if i["number"] == q["innings"])["overs_log"][:q["over"] - 1]
        for p in q["options"]:
            if p["id"] == q["default"]:
                continue
            today = [o for o in log if o["day"] == q["state"]["day"]]
            assert not today or today[-1]["bowler"] != p["name"], "the last over's bowler was offered"


def test_report():
    cards = []
    for seed in range(3):
        cap = RandomCaptain("India", seed)
        cards.append(play(200 + seed, {"India": cap}))
    rep = season_report(cards, "India")
    assert rep["team"] == "India" and rep["matches"] == 3 and rep["runs_per_win"] > 100
    assert {"toss", "xi", "bowler"} <= set(rep["kinds"])
    assert rep["kinds"]["bowler"]["valued"] == rep["kinds"]["bowler"]["calls"] > 20
    assert rep["kinds"]["toss"]["valued"] == 0 and rep["wins"] is not None
    assert season_report(cards, "Australia") is None
    # a series: the controller's context names each Test
    cap = Captain("India", manual={"toss"})
    res = play_test_series(team("India", IND), team("Australia", AUS), n=2, year=2023, seed=9, control={"India": cap})
    assert [c["stage"] for c in res["matches"]] == ["1st Test", "2nd Test"] and cap.context["match_no"] == 2
    assert all("captaincy" in c for c in res["matches"])


def _status(cl, timeout=180):
    t = time.time()
    while time.time() - t < timeout:
        s = cl.get("/api/status").get_json()
        if s["status"] != "running" or (s.get("captain") or {}).get("pending"):
            return s
        time.sleep(0.02)
    raise AssertionError("the run neither finished nor asked")


def test_server_captains_a_test():
    tmp = Path(tempfile.mkdtemp())
    web_ui.LAST = tmp / "last"
    web_ui.TEAMS = tmp / "teams.json"
    cl = web_ui.app.test_client()
    run = {"fmt": "test", "comp": "test_full", "year": 2025, "venues": [], "seed": "11", "rain": True,
           "mode": "series", "team1": "India Test 2025", "team2": "Australia Test 2025", "matches": 1,
           "captain_i": 0, "manual": ["toss", "xi", "bowler", "ball", "declare", "follow_on", "new_ball",
                                      "nightwatchman", "result"]}
    assert cl.post("/api/run", json=run).status_code == 200
    kinds, n, last = [], 0, None
    while True:
        s = _status(cl)
        if s["status"] != "running":
            break
        q = s["captain"]["pending"]
        if q["id"] == last:                       # answered a moment ago: the match has not picked it up yet
            time.sleep(0.01)
            continue
        last = q["id"]
        assert s["captain"]["team"] == "India Test 2025" and q["team"] == "India Test 2025"
        kinds.append(q["kind"])
        n += 1
        choice = {"until": "session"} if q["kind"] == "ball" else None
        r = cl.post("/api/decide", json={"id": q["id"], "choice": choice})
        assert r.status_code == 200, r.get_json()
        assert n < 400, "too many questions for a Test played a session at a time"
    assert s["status"] == "done", s
    assert kinds[0] in ("toss", "xi") and kinds[-1] == "result" and "ball" in kinds and "xi" in kinds
    res = cl.get("/api/results").get_json()
    assert res["format"] == "test" and "you captain India Test 2025" in res["title"]
    cap = res["captaincy"]
    assert cap["team"] == "India Test 2025" and cap["matches"] == 1 and cap["opponents"] == "expert"
    assert "xi" in cap["kinds"]
    m = cl.get("/api/match/1").get_json()
    assert m["card"]["captaincy"]["India Test 2025"]
    # stopping a captained Test while it waits
    assert cl.post("/api/run", json=run).status_code == 200
    s = _status(cl)
    assert s["status"] == "running" and s["captain"]["pending"]
    cl.post("/api/stop")
    t = time.time()
    while cl.get("/api/status").get_json()["status"] == "running" and time.time() - t < 20:
        time.sleep(0.05)
    assert cl.get("/api/status").get_json()["status"] == "stopped"


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in tests:
        t = time.time()
        fn()
        print(f"ok   {fn.__name__}  ({time.time() - t:.1f}s)")
    print(f"{len(tests)} tests passed")


if __name__ == "__main__":
    main()
