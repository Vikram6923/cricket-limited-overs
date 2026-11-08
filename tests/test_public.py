"""The hosted site (python web_ui.py --public): every browser is its own visitor, runs at the same time don't
interfere, two-player rooms work across visitors, the simulation limit and the site password."""
from __future__ import annotations

import base64
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import web_ui  # noqa: E402


class Public:
    """web_ui in public mode with its folders in a temporary directory (restored afterwards)."""

    def __init__(self, **config):
        self.config = {"MULTI": True, "PASSWORD": None, "MAX_JOBS": 6,
                       "LIMITS": {"teams": 100, "saved": 30, "careers": 10}, **config}

    def __enter__(self):
        self.old = ({k: web_ui.app.config.get(k) for k in self.config}, web_ui.VISITORS_DIR)
        self.tmp = Path(tempfile.mkdtemp())
        web_ui.app.config.update(self.config)
        web_ui.VISITORS_DIR = self.tmp
        web_ui.VISITORS.clear()
        web_ui.ROOMS.clear()
        return self

    def __exit__(self, *exc):
        for v in list(web_ui.VISITORS.values()):
            web_ui._cancel(v.job)
        for r in list(web_ui.ROOMS.values()):
            web_ui._cancel(r.get("job"))
        web_ui.app.config.update(self.old[0])
        web_ui.VISITORS_DIR = self.old[1]
        web_ui.VISITORS.clear()
        web_ui.ROOMS.clear()


def wait_done(cl, timeout=180) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = cl.get("/api/status").get_json()
        if st["status"] != "running":
            return st
        time.sleep(0.05)
    raise AssertionError("the run did not finish")


def series(seed: int, a="India T20 2024", b="Australia T20 2024", n=1) -> dict:
    return {"mode": "series", "fmt": "t20", "comp": "t20i_full", "year": 2024, "team1": a, "team2": b,
            "matches": n, "seed": str(seed), "rain": False}


def scores(cl) -> list:
    res = cl.get("/api/results").get_json()
    return [f["winner"] for f in res["fixtures"]], res["title"]


def test_visitors_are_separate():
    with Public() as pub:
        a, b = web_ui.app.test_client(), web_ui.app.test_client()
        r = a.get("/api/meta")
        cookie = r.headers.get("Set-Cookie", "")
        assert "vid=" in cookie and "HttpOnly" in cookie and "SameSite=Lax" in cookie
        assert r.get_json()["public"] is True
        b.get("/api/meta")
        assert len(web_ui.VISITORS) == 2
        # a saved team is only in its owner's list
        xi = json.loads((ROOT / "data" / "teams_default.json").read_text(encoding="utf-8"))[0]["players"][:11]
        assert a.post("/api/team", json={"name": "Mine", "players": xi}).status_code == 200
        assert "Mine" in {t["name"] for t in a.get("/api/teams").get_json()}
        assert "Mine" not in {t["name"] for t in b.get("/api/teams").get_json()}
        # b can't use a's team, and has no results yet
        assert b.post("/api/run", json=series(1, "Mine")).status_code == 400
        assert b.get("/api/results").status_code == 404
        # both run at once; each sees only their own run
        assert a.post("/api/run", json=series(5, "Mine", n=3)).status_code == 200
        assert b.get("/api/status").get_json()["status"] == "idle"
        assert b.post("/api/run", json=series(6)).status_code == 200
        assert a.post("/api/run", json=series(7)).status_code == 409          # one run per visitor
        wait_done(a), wait_done(b)
        ta, tb = scores(a)[1], scores(b)[1]
        assert ta.startswith("Mine v Australia") and tb == "India T20 2024 v Australia T20 2024", (ta, tb)
        # saved runs are per visitor too
        assert a.post("/api/saved", json={"name": "a run"}).status_code == 200
        assert [s["name"] for s in a.get("/api/saved").get_json()] == ["a run"]
        assert b.get("/api/saved").get_json() == []
        assert b.get("/api/results?run=a run").status_code == 404
        assert (pub.tmp / a.get_cookie("vid").value / "saved" / "a run" / "summary.json").exists()


def test_simultaneous_runs_match_runs_alone():
    """Three visitors' seeded tournaments at once give the same results as each one alone: the engine keeps no
    shared state between runs."""
    with Public():
        body = lambda seed: {"mode": "tournament", "fmt": "t20", "comp": "t20i_full", "year": 2024,
                             "teams": ["India T20 2024", "Australia T20 2024", "England T20 2024", "Pakistan T20 2024"],
                             "rounds": 1, "knockout": "final", "seed": str(seed), "rain": True}
        alone = {}
        for seed in (11, 12, 13):
            cl = web_ui.app.test_client()
            r = cl.post("/api/run", json=body(seed))
            assert r.status_code == 200, r.get_json()
            assert wait_done(cl)["status"] == "done"
            alone[seed] = cl.get("/api/results").get_json()
        clients = {seed: web_ui.app.test_client() for seed in alone}
        for seed, cl in clients.items():
            assert cl.post("/api/run", json=body(seed)).status_code == 200
        assert len(web_ui._running_jobs()) >= 2
        for seed, cl in clients.items():
            assert wait_done(cl)["status"] == "done"
            res = cl.get("/api/results").get_json()
            assert res["fixtures"] == alone[seed]["fixtures"] and res["batting"] == alone[seed]["batting"], seed


def test_simulation_limit():
    with Public(MAX_JOBS=1):
        a, b = web_ui.app.test_client(), web_ui.app.test_client()
        # a captains a side: the run waits for a's toss call, holding the one slot
        r = a.post("/api/run", json=dict(series(3), captain_i="0", manual=["toss", "xi", "bowler"]))
        assert r.status_code == 200
        r = b.post("/api/run", json=series(4))
        assert r.status_code == 503 and "busy" in r.get_json()["error"]
        a.post("/api/stop", json={})
        assert wait_done(a)["status"] == "stopped"
        assert b.post("/api/run", json=series(4)).status_code == 200
        assert wait_done(b)["status"] == "done"


def test_rooms_across_visitors():
    """Two rooms at once; each player uses a team from their own saved teams; both players (and a spectator) get
    the results; the room shows this site's join link."""
    with Public():
        host, guest, watcher, other = (web_ui.app.test_client() for _ in range(4))
        xi = json.loads((ROOT / "data" / "teams_default.json").read_text(encoding="utf-8"))[1]["players"][:11]
        host.post("/api/team", json={"name": "Host XI", "players": xi})
        post = lambda cl, path, body: cl.post(path, json=body)
        state = lambda cl, tok: cl.get("/api/mp/state?token=" + tok).get_json()
        conds = {"fmt": "t20", "comp": "t20i_full", "year": 2024, "venues": [], "rain": False, "seed": "9",
                 "clock": "off", "series": "1"}
        h = post(host, "/api/mp/create", conds).get_json()
        o = post(other, "/api/mp/create", conds).get_json()                    # a second room
        assert h["code"] != o["code"] and len(web_ui.ROOMS) == 2
        st = state(host, h["token"])
        assert st["urls"] == [f"http://localhost/?join={h['code']}"] and st["public"] and st["lan"]
        g = post(guest, "/api/mp/join", {"code": h["code"]}).get_json()
        w = post(watcher, "/api/mp/join", {"code": h["code"]}).get_json()
        assert g["seat"] == 1 and w["seat"] == "spectator"
        assert state(other, o["token"])["seats"][1]["joined"] is False         # the other room is untouched
        post(host, "/api/mp/lobby", {"token": h["token"], "team": "Host XI", "manual": [], "ready": True})
        r = post(guest, "/api/mp/lobby", {"token": g["token"], "team": "Host XI", "manual": [], "ready": True})
        assert r.status_code == 400 and "No saved team" in r.get_json()["error"]   # the host's team isn't the guest's
        r = post(guest, "/api/mp/lobby", {"token": g["token"], "team": "England T20 2024", "manual": [], "ready": True})
        assert r.status_code == 200
        assert post(host, "/api/mp/lobby", {"token": h["token"], "ready": True}).status_code == 200   # starts
        deadline = time.time() + 180
        while state(host, h["token"])["phase"] != "over" and time.time() < deadline:
            time.sleep(0.05)
        st = state(host, h["token"])
        assert st["phase"] == "over" and st["job"]["status"] == "done", st
        titles = {cl.get("/api/results").get_json()["title"] for cl in (host, guest, watcher)}
        assert titles == {"Host XI v England T20 2024 - two players"}, titles
        assert other.get("/api/results").status_code == 404
        assert host.get("/api/status").get_json()["status"] == "idle"          # the room's run isn't the host's own
        post(host, "/api/mp/lobby", {"token": h["token"], "leave": True})
        assert state(guest, g["token"])["phase"] == "none" and list(web_ui.ROOMS) == [o["code"]]
        o2 = post(other, "/api/mp/create", conds).get_json()                  # a host's new room replaces their old one
        assert list(web_ui.ROOMS) == [o2["code"]]


def test_password():
    with Public(PASSWORD="open sesame"):
        cl = web_ui.app.test_client()
        r = cl.get("/")
        assert r.status_code == 401 and "Basic" in r.headers["WWW-Authenticate"]
        bad = base64.b64encode(b"x:wrong").decode()
        assert cl.get("/api/meta", headers={"Authorization": "Basic " + bad}).status_code == 401
        ok = base64.b64encode(b"friend:open sesame").decode()
        assert cl.get("/api/meta", headers={"Authorization": "Basic " + ok}).status_code == 200


def test_local_mode_unchanged():
    """Without --public there is one user with the usual folders, and no cookie."""
    cl = web_ui.app.test_client()
    r = cl.get("/api/status")
    assert "Set-Cookie" not in r.headers and not web_ui.VISITORS
    with web_ui.app.test_request_context("/"):
        web_ui.app.preprocess_request()
        assert web_ui.V() is web_ui.LOCAL and web_ui.V().last == web_ui.LAST and web_ui.V().teams_file == web_ui.TEAMS


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok ", name)
