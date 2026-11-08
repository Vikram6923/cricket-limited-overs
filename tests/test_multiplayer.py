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


def test_best_of_series_stops_when_decided():
    from engine.tournament import play_series
    a, b = TEAMS["India T20 2024"], TEAMS["Australia T20 2024"]
    lengths = set()
    for seed in range(8):
        res = play_series(a, b, n=3, fmt="t20", comp="t20i_full", year=2024, seed=seed, best_of=True)
        ws = [c["result"].get("winner") for c in res["matches"]]
        lengths.add(len(ws))
        assert res["best_of"] == 3 and len(ws) in (2, 3)
        if len(ws) == 2:
            assert ws[0] == ws[1] and ws[0] is not None, ws
        assert res["winner"] is None or res["score"][res["winner"]] == 2 or len(ws) == 3
    assert lengths == {2, 3}, lengths                 # some series are decided early, some go the distance
    full = play_series(a, b, n=3, fmt="t20", comp="t20i_full", year=2024, seed=0)
    assert len(full["fixtures"]) == 3 and full["best_of"] is None
    one = play_series(a, b, n=1, fmt="t20", comp="t20i_full", year=2024, seed=0)
    assert "series" not in one["result"] and one["result"] == one["matches"][0]["result"]["text"]


def test_result_pause_shown_to_both_at_once():
    from engine.tournament import play_series
    a, b = TEAMS["India T20 2024"], TEAMS["Australia T20 2024"]
    log = []
    ctl = {}
    for t in (a, b):
        c = Recorder(t["name"], log)
        c.manual_kinds = {"result"}
        ctl[t["name"]] = c
    res = play_series(a, b, n=2, fmt="t20", comp="t20i_full", year=2024, seed=4, control=ctl)
    posts = [e for e in log if e[0] == "post"]
    assert [e[2] for e in posts] == ["result"] * 4
    assert [e[0] for e in log] == ["post", "post", "wait", "wait"] * 2
    assert len(res["fixtures"]) == 2


def test_server_room_series():
    import web_ui
    tmp = Path(tempfile.mkdtemp())
    web_ui.LAST = tmp / "last"
    cl = web_ui.app.test_client()
    post = lambda path, body: cl.post(path, json=body)
    state = lambda tok: cl.get("/api/mp/state?token=" + tok).get_json()
    host = post("/api/mp/create", {"fmt": "t20", "comp": "t20i_full", "year": 2024, "venues": [], "rain": False,
                                   "seed": "5", "clock": "off", "series": "3"}).get_json()["token"]
    code = state(host)["code"]
    guest = post("/api/mp/join", {"code": code}).get_json()["token"]
    assert state(host)["settings"]["series"] == 3
    # the host changes it in the room: both must say ready again
    post("/api/mp/lobby", {"token": host, "team": "India T20 2024", "manual": ["toss"], "ready": True})
    st = dict(state(host)["settings"], series=7)
    post("/api/mp/lobby", {"token": host, "settings": st})
    assert state(host)["settings"]["series"] == 1 and not state(host)["seats"][0]["ready"]   # 7 is not offered
    post("/api/mp/lobby", {"token": host, "settings": dict(st, series=3)})
    post("/api/mp/lobby", {"token": guest, "team": "Australia T20 2024", "manual": ["toss"], "ready": True})
    assert post("/api/mp/lobby", {"token": host, "ready": True}).status_code == 200
    pauses = []
    deadline = time.time() + 120
    while time.time() < deadline:
        sts = [state(host), state(guest)]
        if sts[0]["phase"] == "over":
            break
        mine = [s.get("me", {}).get("pending") for s in sts]
        if all(q and q["kind"] == "result" for q in mine):        # both see the result together
            sr = sts[0]["series"]
            assert sr == sts[1]["series"] and sr["of"] == 3 and sum(sr["wins"]) <= sr["finished"]
            pauses.append(sr)
        for tok, q in zip((host, guest), mine):
            if q:
                post("/api/mp/decide", {"token": tok, "id": q["id"], "choice": None})
        time.sleep(0.005)
    st = state(host)
    assert st["phase"] == "over" and st["job"]["status"] == "done", st
    res = json.loads((tmp / "last" / "summary.json").read_text(encoding="utf-8"))
    n = len(res["fixtures"])
    assert res["best_of"] == 3 and n in (2, 3) and res["mode"] == "mp"
    assert [p["finished"] for p in pauses] == list(range(1, n + 1)), pauses
    rec = st["record"]
    assert sum(rec["matches"]) == sum(1 for f in res["fixtures"] if f["winner"]) and rec["played"] == 1
    assert sum(rec["series"]) == (1 if res["winner"] else 0)
    post("/api/mp/lobby", {"token": guest, "rematch": True})
    assert state(host)["phase"] == "lobby" and state(host)["record"] == rec      # kept for the rematch
    post("/api/mp/lobby", {"token": host, "leave": True})


def _draft_room(cl, cpu: int, series: int = 1):
    """A draft room with both seats named and ready: (post, state, host token, guest token)."""
    post = lambda path, body: cl.post(path, json=body)
    state = lambda tok: cl.get("/api/mp/state?token=" + tok).get_json()
    host = post("/api/mp/create", {"fmt": "t20", "comp": "t20i_full", "year": 2024, "venues": [], "rain": False,
                                   "seed": "7", "clock": "off", "series": str(series), "teams": "draft",
                                   "y1": 2016, "y2": 2024, "cpu": cpu}).get_json()["token"]
    guest = post("/api/mp/join", {"code": state(host)["code"]}).get_json()["token"]
    assert post("/api/mp/lobby", {"token": host, "ready": True}).status_code == 400        # no name yet
    post("/api/mp/lobby", {"token": host, "name": "  Riverside ", "manual": [], "ready": True})
    r = post("/api/mp/lobby", {"token": guest, "name": "riverside", "manual": [], "ready": True})
    assert r.status_code == 400 and "same team name" in r.get_json()["error"]
    post("/api/mp/lobby", {"token": host, "ready": True})
    assert post("/api/mp/lobby", {"token": guest, "name": "Hilltop", "ready": True}).status_code == 200
    return post, state, host, guest


def test_server_draft_then_series():
    import web_ui
    tmp = Path(tempfile.mkdtemp())
    web_ui.LAST = tmp / "last"
    cl = web_ui.app.test_client()
    post, state, host, guest = _draft_room(cl, cpu=0, series=3)
    st = state(host)
    assert st["phase"] == "draft" and st["draft"]["teams"] == ["Riverside", "Hilltop"]
    assert post("/api/mp/lobby", {"token": host, "team": "India T20 2024"}).status_code == 409   # the draft is on
    pool = cl.get("/api/mp/draft/pool?token=" + guest).get_json()["pool"]
    assert len(pool) >= 30
    picks = 0
    while True:
        sts = {tok: state(tok)["draft"] for tok in (host, guest)}
        if sts[host]["done"]:
            break
        cur = sts[host]["current"]
        on, off = (host, guest) if cur == "Riverside" else (guest, host)
        assert sts[on]["user"] == cur and sts[on]["suggestions"] and not sts[off]["suggestions"]
        sug = sts[on]["suggestions"][0]
        assert post("/api/mp/draft", {"token": off, "id": sug}).status_code == 400      # not your pick
        if picks % 3 == 0:
            assert post("/api/mp/draft", {"token": on, "auto": "one"}).status_code == 200
        else:
            assert post("/api/mp/draft", {"token": on, "id": sug}).status_code == 200
        picks += 1
    board = state(host)["draft"]["board"]
    assert picks == 30 and all(len(board[t]) == 15 for t in board)
    assert post("/api/mp/draft", {"token": guest, "redo": True}).status_code == 403       # host only
    post("/api/mp/draft", {"token": host, "ready": True})
    assert state(host)["phase"] == "draft"                                                  # waiting for the guest
    assert post("/api/mp/draft", {"token": guest, "ready": True}).status_code == 200
    deadline = time.time() + 120
    while time.time() < deadline:
        sts = [state(host), state(guest)]
        if sts[0]["phase"] == "over":
            break
        for tok, s in zip((host, guest), sts):
            q = (s.get("me") or {}).get("pending")
            if q:                                                   # the result pauses between matches
                assert q["kind"] == "result"
                post("/api/mp/decide", {"token": tok, "id": q["id"], "choice": None})
        time.sleep(0.005)
    res = json.loads((tmp / "last" / "summary.json").read_text(encoding="utf-8"))
    assert res["kind"] == "series" and res["teams"] == ["Riverside", "Hilltop"] and res["best_of"] == 3
    assert res["draft"]["board"] == board and res["draft"]["players"] == ["Riverside", "Hilltop"]
    card = json.loads((tmp / "last" / "matches" / "001.json").read_text(encoding="utf-8"))
    xi = {p["id"] for t in card["xi"].values() for p in t}
    assert len(xi) == 22, card["xi"]
    assert xi <= {p["id"] for t in board.values() for p in t}                              # drafted players only
    post("/api/mp/lobby", {"token": guest, "rematch": True})
    st = state(host)
    assert st["phase"] == "draft" and st["draft"]["done"]                                   # same squads again
    assert post("/api/mp/draft", {"token": host, "redo": True}).status_code == 200
    assert state(guest)["phase"] == "lobby"
    post("/api/mp/lobby", {"token": host, "leave": True})


def test_server_draft_league_with_computer_teams():
    import web_ui
    tmp = Path(tempfile.mkdtemp())
    web_ui.LAST = tmp / "last"
    cl = web_ui.app.test_client()
    post, state, host, guest = _draft_room(cl, cpu=2)
    d = state(host)["draft"]
    assert len(d["teams"]) == 4 and d["current"] in d["players"]   # the computer teams have picked up to a person
    for tok in (host, guest):
        assert post("/api/mp/draft", {"token": tok, "auto": "rest"}).status_code == 200
    d = state(host)["draft"]
    assert d["done"] and d["auto"] == [True, True] and all(len(v) == 15 for v in d["board"].values())
    for tok in (host, guest):
        post("/api/mp/draft", {"token": tok, "ready": True})
    leagues = set()
    deadline = time.time() + 180
    while time.time() < deadline:
        sts = [state(host), state(guest)]
        if sts[0]["phase"] == "over":
            break
        if sts[0]["phase"] == "playing":
            leagues.add(sts[0]["series"].get("league"))
        for tok, s in zip((host, guest), sts):
            q = (s.get("me") or {}).get("pending")
            if q:
                post("/api/mp/decide", {"token": tok, "id": q["id"], "choice": None})
        time.sleep(0.005)
    st = state(host)
    assert st["phase"] == "over" and st["job"]["status"] == "done", st
    assert leagues == {True}
    res = json.loads((tmp / "last" / "summary.json").read_text(encoding="utf-8"))
    assert res["kind"] != "series" and len(res["fixtures"]) == 6 + 1 and res["draft"]["teams"][:2] == ["Riverside", "Hilltop"]
    cards = [json.loads(f.read_text(encoding="utf-8")) for f in sorted((tmp / "last" / "matches").glob("*.json"))]
    h2h = [c for c in cards if set(c["teams"]) == {"Riverside", "Hilltop"}]
    rec = st["record"]
    assert sum(rec["matches"]) == sum(1 for c in h2h if c["result"].get("winner"))
    assert sum(rec["titles"]) == (1 if res["winner"] in ("Riverside", "Hilltop") else 0) and rec["played"] == 0
    post("/api/mp/lobby", {"token": host, "leave": True})


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok ", name)
