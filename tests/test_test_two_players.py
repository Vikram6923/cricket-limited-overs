"""Tests for two people captaining a Test, the default Test teams and the messages when a run cannot be played.

    python tests/test_test_two_players.py          (no pytest needed; also works under pytest)

Two controllers in one Test keep the laws; both people get the XI question and the result at the same moment; a
Test room runs through the server (a team each, every Test played, no draft or auction); default teams added to
the program after a person's teams file was made are added to it once; a side that cannot play the format is
refused before the run starts, in words; an error inside a run is reported as a sentence with the traceback apart.
"""
from __future__ import annotations

import json
import random
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import web_ui  # noqa: E402
from engine import simulate_match  # noqa: E402
from engine.control import WaitingController  # noqa: E402
from engine.data import resolve  # noqa: E402
from test_test_control import RandomCaptain  # noqa: E402
from test_test_engine import AUS, IND, check_card, team  # noqa: E402

DEFAULTS = json.loads((ROOT / "data" / "teams_default.json").read_text(encoding="utf-8"))


def test_two_people_keep_the_laws():
    asked = [set(), set()]
    for seed in range(6):
        caps = [RandomCaptain("India", seed), RandomCaptain("Australia", 50 + seed)]
        card = simulate_match(team("India", IND), team("Australia", AUS), fmt="test", year=2023, seed=300 + seed,
                              control={c.team: c for c in caps})
        check_card(card, captained=True)
        assert set(card["captaincy"]) == {"India", "Australia"}
        for i, c in enumerate(caps):
            asked[i] |= set(c.asked)
            assert c.asked[-1] == "result" and c.asked.count("result") == 1 and c.asked.count("xi") == 1
            assert all(q["team"] == c.team for q in c.questions)
            sides = {q["side"] for q in c.questions if q["kind"] == "ball"}
            assert sides == {"bat", "bowl"}, sides            # each person sets bars batting and in the field
    for a in asked:
        assert a >= {"xi", "bowler", "batter", "ball", "result"}, a
    assert asked[0] | asked[1] >= {"toss", "declare"}


def test_both_asked_at_once():
    """The XI after the toss and the result: both people have their question open at the same moment."""
    ctl = {n: WaitingController(n, {"xi", "result"}) for n in ("India", "Australia")}
    out = {}

    def run():
        out["card"] = simulate_match(team("India", IND), team("Australia", AUS), fmt="test", year=2023, seed=7,
                                     control=ctl)
    th = threading.Thread(target=run, daemon=True)
    th.start()
    for kind in ("xi", "result"):
        t0 = time.time()
        while not all(c.pending and c.pending["kind"] == kind for c in ctl.values()):
            assert time.time() - t0 < 120 and th.is_alive(), f"both sides were not asked for {kind} together"
            time.sleep(0.005)
        if kind == "xi":
            assert {c.pending["batting_first"] for c in ctl.values()} == {True, False}
        for c in ctl.values():
            assert c.answer(c.pending["id"], None)
    th.join(60)
    assert not th.is_alive() and out["card"]["format"] == "test"


def _room(cl, tmp, **settings):
    post = lambda path, body: cl.post(path, json=body)
    r = post("/api/mp/create", {"fmt": "test", "comp": "test_full", "year": 2025, "venues": [], "rain": False,
                                "seed": "5", "clock": "off", **settings})
    return post, r


def test_server_test_room():
    tmp = Path(tempfile.mkdtemp())
    web_ui.LAST = tmp / "last"
    web_ui.TEAMS = tmp / "teams.json"
    cl = web_ui.app.test_client()
    post, r = _room(cl, tmp, teams="draft")
    assert r.status_code == 400 and "team each" in r.get_json()["error"]
    post, r = _room(cl, tmp, series="2", host="home")
    assert r.status_code == 200, r.get_json()
    code, host = r.get_json()["code"], r.get_json()["token"]
    guest = post("/api/mp/join", {"code": code, "name": "Asha"}).get_json()["token"]
    state = lambda tok: cl.get("/api/mp/state?token=" + tok).get_json()
    s = state(host)["settings"]
    assert s["fmt"] == "test" and s["series"] == 2 and s["host"] == "home" and s["teams"] == "pick"
    # a best of 3 is not a Test series; a T20 side cannot play a Test
    post("/api/mp/lobby", {"token": host, "settings": {**s, "series": "3", "teams": "auction"}})
    assert state(host)["settings"]["teams"] == "pick"          # refused: the settings stay as they were
    kinds = ["toss", "ball", "declare", "follow_on"]
    post("/api/mp/lobby", {"token": host, "team": "India T20 2024", "manual": kinds, "ready": True})
    r = post("/api/mp/lobby", {"token": guest, "team": "Australia Test 2025", "manual": kinds, "ready": True})
    err = r.get_json()["error"]
    assert r.status_code == 400 and "cannot play a Test match" in err and "India Test 2025" in err, err
    post("/api/mp/lobby", {"token": host, "team": "India Test 2025", "manual": kinds, "ready": True})
    assert post("/api/mp/lobby", {"token": guest, "ready": True}).status_code == 200
    seen, last = [set(), set()], [None, None]
    rng = random.Random(2)
    deadline = time.time() + 240
    while time.time() < deadline:
        st = [state(host), state(guest)]
        if st[0]["phase"] == "over":
            break
        assert st[0]["phase"] == "playing", st[0]
        assert st[0]["series"]["test"] and st[0]["series"]["of"] == 2
        for i, tok in enumerate((host, guest)):
            q = st[i]["me"]["pending"]
            if not q or q["id"] == last[i]:
                continue
            last[i] = q["id"]
            assert q["team"] == st[i]["me"]["team"] and q["state"]["format"] == "test"
            seen[i].add(q["kind"])
            choice = None
            if q["kind"] == "ball":
                ids = [q["striker"]["id"], q["non_striker"]["id"]] if q["side"] == "bat" else [q["bowler"]["id"]]
                choice = {q["side"]: {x: rng.randint(4, 6) for x in ids}, "until": "day"}
            assert post("/api/mp/decide", {"token": tok, "id": q["id"], "choice": choice}).status_code == 200
        time.sleep(0.003)
    st = state(host)
    assert st["phase"] == "over" and st["job"]["status"] == "done", st["job"]
    assert "2-Test series" in st["job"]["title"]
    for sset in seen:
        assert sset >= {"ball", "result"}, seen
    res = json.loads((tmp / "last" / "summary.json").read_text(encoding="utf-8"))
    assert res["mode"] == "mp" and res["format"] == "test" and len(res["fixtures"]) == 2
    assert res["host"] == "India"                               # "home": the host player's country
    assert set(res["captaincy_by"]) == {"India Test 2025", "Australia Test 2025"}
    assert st["record"]["played"] == 1                          # the series is in the room's head to head
    post("/api/mp/lobby", {"token": host, "leave": True})


def test_new_default_teams_are_added_once():
    tmp = Path(tempfile.mkdtemp())
    web_ui.LAST = tmp / "last"
    web_ui.TEAMS = tmp / "teams.json"
    old = [t for t in DEFAULTS if " Test " not in t["name"]] + [{"name": "My XI", "players": DEFAULTS[0]["players"]}]
    web_ui.TEAMS.write_text(json.dumps(old), encoding="utf-8")    # a teams file from before the Test sides
    cl = web_ui.app.test_client()
    names = [t["name"] for t in cl.get("/api/teams").get_json()]
    tests = [t["name"] for t in DEFAULTS if " Test " in t["name"]]
    assert len(tests) >= 8 and set(tests) <= set(names) and "My XI" in names and len(names) == len(old) + len(tests)
    assert names.index(tests[0]) < names.index("My XI")           # with the nations, not after your own teams
    assert len(names) == len(set(names))
    # one the person deletes stays deleted; the rest are not added twice
    cl.post("/api/team/delete", json={"name": tests[0]})
    again = [t["name"] for t in cl.get("/api/teams").get_json()]
    assert tests[0] not in again and len(again) == len(names) - 1
    # a new file starts as the defaults, Test sides included
    web_ui.TEAMS = tmp / "fresh" / "teams.json"
    assert [t["name"] for t in cl.get("/api/teams").get_json()] == [t["name"] for t in DEFAULTS]


def test_a_side_of_the_wrong_format_is_refused_in_words():
    tmp = Path(tempfile.mkdtemp())
    web_ui.LAST = tmp / "last"
    web_ui.TEAMS = tmp / "teams.json"
    cl = web_ui.app.test_client()
    run = {"fmt": "test", "comp": "test_full", "year": 2025, "venues": [], "seed": "1", "mode": "series",
           "team1": "India T20 2024", "team2": "Australia T20 2024", "matches": 1}
    r = cl.post("/api/run", json=run)
    err = r.get_json()["error"]
    assert r.status_code == 400, r.get_json()
    assert err.startswith("India T20 2024 cannot play a Test match:") and "have no Test record (" in err
    assert "Choose India Test 2025 instead" in err and "Traceback" not in err and "a4cc" not in err
    assert cl.get("/api/status").get_json()["status"] != "running"
    # the engine says who, not a player ID
    t20_only = next(p for t in DEFAULTS if t["name"] == "India T20 2024" for p in t["players"]
                    if p["id"] not in web_ui.ratings("test")["players"])
    try:
        resolve("test", t20_only["id"])
        raise AssertionError("a T20-only player was accepted for a Test")
    except ValueError as e:
        assert t20_only["name"] in str(e) and "no Test record" in str(e) and t20_only["id"] not in str(e)


def test_an_error_is_a_sentence_with_the_traceback_apart():
    assert web_ui.friendly_error(ValueError("no saved team called 'X'")) == "No saved team called 'X'."
    msg = web_ui.friendly_error(KeyError("bat"))
    assert "Something went wrong" in msg and "bat" not in msg and "Traceback" not in msg
    job = web_ui.Job("x", 1)
    d = job.to_dict()
    assert d["error"] is None and d["detail"] is None


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in tests:
        t = time.time()
        fn()
        print(f"ok   {fn.__name__}  ({time.time() - t:.1f}s)")
    print(f"{len(tests)} tests passed")


if __name__ == "__main__":
    main()
