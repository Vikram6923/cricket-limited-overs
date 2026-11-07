"""Two players (docs/multiplayer_design.md): both sides' questions are open at once; two people who leave everything
to the computer get the computer's match; random play keeps the laws; a skip hands the bars back to the computer;
the shot clock answers for a slow player; the server shows each seat only its own question."""
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

from engine import simulate_match  # noqa: E402
from engine.control import KINDS, Controller, WaitingController  # noqa: E402
from test_control import RandomCaptain, ipl_teams  # noqa: E402
from test_engine import check_card  # noqa: E402

TEAMS = {t["name"]: t for t in json.loads((ROOT / "data" / "teams_default.json").read_text(encoding="utf-8"))}
ALL = set(KINDS) - {"result"}


class Recorder(Controller):
    """The computer's choice for everything; logs when questions are opened and awaited."""

    def __init__(self, team, log):
        super().__init__(team, ALL)
        self.log = log

    def post(self, q):
        self.log.append(("post", self.team, q["kind"], q.get("over"), q.get("ball")))
        super().post(q)

    def wait(self):
        self.log.append(("wait", self.team))
        return super().wait()


def test_both_sides_asked_at_once():
    a, b = TEAMS["India T20 2024"], TEAMS["Australia T20 2024"]
    log = []
    ctl = {a["name"]: Recorder(a["name"], log), b["name"]: Recorder(b["name"], log)}
    simulate_match(a, b, fmt="t20", comp="t20i_full", year=2024, seed=1, control=ctl)
    balls = [i for i, e in enumerate(log) if e[0] == "post" and e[2] == "ball"]
    assert len(balls) >= 2 * 200, len(balls)
    for i in balls[::2]:                         # each ball: both posted, then both awaited
        assert log[i + 1][0] == "post" and log[i + 1][2] == "ball" and log[i + 1][3:] == log[i][3:], log[i:i + 4]
        assert {log[i][1], log[i + 1][1]} == set(ctl)
        assert log[i + 2][0] == "wait" and log[i + 3][0] == "wait"
    xi = [i for i, e in enumerate(log) if e[0] == "post" and e[2] == "xi"]
    assert len(xi) == 2 and xi[1] == xi[0] + 1   # the XIs too


def test_defaults_match_the_computer():
    a, b = ipl_teams("2022")                     # no Impact Player
    for fmt, seeds in (("t20", range(10)), ("odi", range(3))):
        for seed in seeds:
            ctl = {a["name"]: Controller(a["name"], ALL), b["name"]: Controller(b["name"], ALL)}
            c1 = simulate_match(a, b, fmt=fmt, comp="ipl" if fmt == "t20" else "odi_full", year=2022, seed=seed,
                                control=ctl)
            c2 = simulate_match(a, b, fmt=fmt, comp="ipl" if fmt == "t20" else "odi_full", year=2022, seed=seed)
            assert [i["runs"] for i in c1["innings"]] == [i["runs"] for i in c2["innings"]], (fmt, seed)


class RandomBars(RandomCaptain):
    """Random answers to every question, random bars and pace for ball by ball."""

    def __init__(self, team, seed):
        super().__init__(team, seed)
        self.manual_kinds = set(ALL)

    def decide(self, q):
        if q["kind"] != "ball":
            return super().decide(q)
        r = self.rng
        ids = [q["striker"]["id"], q["non_striker"]["id"]] if q["side"] == "bat" else [q["bowler"]["id"]]
        return {q["side"]: {i: r.randint(1, 9) for i in ids}, "until": r.choice(["ball", "ball", "over", "wicket"])}


def test_random_play_keeps_the_laws():
    for fmt, (x, y), comp in (("t20", ("India T20 2024", "Australia T20 2024"), "t20i_full"),
                              ("odi", ("India ODI 2023", "Australia ODI 2023"), "odi_full")):
        a, b = TEAMS[x], TEAMS[y]
        for seed in range(6 if fmt == "t20" else 2):
            ctl = {a["name"]: RandomBars(a["name"], seed), b["name"]: RandomBars(b["name"], seed + 99)}
            check_card(simulate_match(a, b, fmt=fmt, comp=comp, year=2024, seed=seed, control=ctl))
    a, b = ipl_teams("2024")                     # Impact Player on both sides
    for seed in range(6):
        ctl = {a["name"]: RandomBars(a["name"], seed), b["name"]: RandomBars(b["name"], seed + 7)}
        check_card(simulate_match(a, b, fmt="t20", comp="ipl", year=2024, seed=seed, control=ctl))


def test_skip_hands_the_bars_to_the_computer():
    """Bars set to 9, then a skip to the end of the match: the computer plays at 5, as with no person at all."""
    a, b = ipl_teams("2022")

    class SkipAt9(Controller):
        def decide(self, q):
            if q["kind"] != "ball":
                return None
            self.skip = {"scope": "match", "match": q["match_key"], "innings": q["innings"]}
            ids = [q["striker"]["id"], q["non_striker"]["id"]] if q["side"] == "bat" else [q["bowler"]["id"]]
            return {q["side"]: {i: 9 for i in ids}}
    for seed in range(5):
        ctl = {a["name"]: SkipAt9(a["name"], {"ball"}), b["name"]: SkipAt9(b["name"], {"ball"})}
        c1 = simulate_match(a, b, fmt="t20", comp="ipl", year=2022, seed=seed, control=ctl)
        c2 = simulate_match(a, b, fmt="t20", comp="ipl", year=2022, seed=seed)
        assert [i["runs"] for i in c1["innings"]] == [i["runs"] for i in c2["innings"]], seed


def test_shot_clock_answers_for_a_slow_player():
    a, b = TEAMS["India T20 2024"], TEAMS["Australia T20 2024"]
    slow = WaitingController(a["name"], {"ball", "bowler"}, clock={"ball": 0.01, "bowler": 0.01})
    t0 = time.time()
    c = simulate_match(a, b, fmt="t20", comp="t20i_full", year=2024, seed=4, control={a["name"]: slow})
    check_card(c)
    assert time.time() - t0 < 60 and slow.pending is None


def test_server_room():
    import web_ui
    tmp = Path(tempfile.mkdtemp())
    web_ui.LAST = tmp / "last"                    # don't touch the user's last results
    cl = web_ui.app.test_client()
    post = lambda path, body: cl.post(path, json=body)
    r = post("/api/mp/create", {"fmt": "t20", "comp": "t20i_full", "year": 2024, "venues": [], "rain": False,
                                "seed": "11", "clock": "off"})
    assert r.status_code == 200, r.get_json()
    code, host = r.get_json()["code"], r.get_json()["token"]
    assert post("/api/mp/join", {"code": "ZZZZ"}).status_code == 404
    guest = post("/api/mp/join", {"code": code.lower()}).get_json()
    watcher = post("/api/mp/join", {"code": code}).get_json()
    assert guest["seat"] == 1 and watcher["seat"] == "spectator"
    state = lambda tok: cl.get("/api/mp/state?token=" + tok).get_json()
    assert state(host)["phase"] == "lobby" and state("nope")["phase"] == "none"
    assert post("/api/mp/lobby", {"token": host, "ready": True}).status_code == 400          # no team yet
    post("/api/mp/lobby", {"token": host, "team": "India T20 2024", "manual": ["ball", "bowler", "toss"]})
    r = post("/api/mp/lobby", {"token": guest["token"], "team": "India T20 2024", "ready": True})
    assert r.status_code == 200
    r = post("/api/mp/lobby", {"token": host, "ready": True})
    assert r.status_code == 400 and "same team" in r.get_json()["error"]
    post("/api/mp/lobby", {"token": guest["token"], "team": "Australia T20 2024", "manual": ["ball"], "ready": True})
    assert post("/api/mp/lobby", {"token": host, "ready": True}).status_code == 200
    seen = {0: set(), 1: set()}
    both_ball = 0
    rng = random.Random(3)
    deadline = time.time() + 120
    while time.time() < deadline:
        st = [state(host), state(guest["token"])]
        if st[0]["phase"] == "over":
            break
        assert st[0]["phase"] == "playing", st[0]
        assert "me" not in state(watcher["token"])
        mine = [s["me"]["pending"] for s in st]
        if all(q and q["kind"] == "ball" for q in mine):
            both_ball += 1
            assert {q["side"] for q in mine} == {"bat", "bowl"}
        for i, (tok, q) in enumerate(((host, mine[0]), (guest["token"], mine[1]))):
            if not q:
                continue
            assert q["team"] == st[i]["me"]["team"]           # only your own side's questions
            seen[i].add(q["kind"])
            choice = None
            if q["kind"] == "ball":
                ids = [q["striker"]["id"], q["non_striker"]["id"]] if q["side"] == "bat" else [q["bowler"]["id"]]
                choice = {q["side"]: {x: rng.randint(3, 7) for x in ids}, "until": rng.choice(["ball", "over"])}
            skip = "match" if q["kind"] == "ball" and q["innings"] == 2 and q["over"] >= 5 else None
            assert post("/api/mp/decide", {"token": tok, "id": q["id"], "choice": choice, "skip": skip}).status_code == 200
        time.sleep(0.005)
    st = state(host)
    assert st["phase"] == "over" and st["job"]["status"] == "done", st
    assert seen[0] >= {"ball", "bowler"} and seen[1] == {"ball"}, seen
    assert both_ball > 10
    res = json.loads((tmp / "last" / "summary.json").read_text(encoding="utf-8"))
    assert res["mode"] == "mp" and set(res["captaincy_by"]) == {"India T20 2024", "Australia T20 2024"}
    assert post("/api/mp/lobby", {"token": guest["token"], "rematch": True}).status_code == 200
    assert state(host)["phase"] == "lobby"
    post("/api/mp/lobby", {"token": host, "leave": True})
    assert state(guest["token"])["phase"] == "none"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok ", name)
