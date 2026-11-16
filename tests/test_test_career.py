"""Tests for the Test career (engine/test_career.py) and its server routes.

    python tests/test_test_career.py          (no pytest needed; also works under pytest)
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import web_ui  # noqa: E402
from engine import test_career  # noqa: E402
from engine.test_career import SQUAD, TestCareer  # noqa: E402
from engine.test_captain import group  # noqa: E402
from engine.tournament import play_tournament  # noqa: E402

FOUR = ["India", "Australia", "England", "South Africa"]


def test_tables_are_sane():
    t = test_career.tables()
    for side in ("bat", "bowl"):
        for m in ("runs", "wkt"):
            c = t["curve"][side][m]
            assert all(0.7 < c[str(a)] < 1.4 for a in range(t["ages"][0], t["ages"][1] + 1)), (side, m)
    wk = t["curve"]["bat"]["wkt"]
    assert wk["28"] < wk["20"] and wk["28"] < wk["38"], "batters are out least often in their late twenties"
    r = t["retire"]
    assert r["24"] < r["30"] < r["36"] < r["40"] <= 1 and r["43"] == 1.0
    assert 20 <= t["debut_age"] <= 28


def test_start_and_refusals():
    c = TestCareer(2015, nations=FOUR, user="India", rounds=1, seed=3)
    assert c.franchises and set(c.franchises) == set(FOUR) and c.kind == "test" and c.phase == "season"
    for n in FOUR:
        ps = [c.engine_player(pid, form=False) for pid in c.squads[n]]
        assert len(ps) == SQUAD and sum(p.keeper for p in ps) >= 2
        assert sum(group(p) == "pace" and not p.keeper for p in ps) >= 3, n
        assert any(group(p) == "spin" for p in ps), n
        assert set(c.squads[n]) <= set(c.pools[n])
    assert "V Kohli" in [c.players[p]["name"] for p in c.squads["India"]]
    for kw, words in (({"year": 1990}, "starts in"), ({"year": "x"}, "year"), ({"nations": FOUR[:2]}, "at least"),
                      ({"nations": FOUR, "user": "Peru"}, "one of"), ({"nations": FOUR, "rounds": 3}, "once")):
        try:
            TestCareer(**{"year": 2015, **kw})
            raise AssertionError(f"accepted {kw}")
        except ValueError as e:
            assert words in str(e), (kw, str(e))


def test_seasons_ageing_and_newcomers():
    c = TestCareer(test_career.last_real_year() - 1, nations=FOUR, user="England", rounds=1, seed=5)
    start = {pid: dict(c.players[pid]) for pid in c.active()}
    sizes = []
    for k in range(4):
        res = play_tournament(c.specs(), **c.play_args())
        assert res["format"] == "test" and len(res["matches"]) == c.match_total() == 7
        h = c.record(res, run=f"x/{k}")
        assert c.phase == "advance" and h["champion"] in FOUR and h["user_pos"] and h["orange"]["runs"] > 0
        played = sum(c.players[p].get("played", 0) for p in c.active())
        assert played == 22 * len(res["matches"])
        c.advance()
        assert c.phase == "season" and c.year == int(c.start_season) + k + 1
        c = TestCareer.from_json(json.loads(json.dumps(c.to_json())))      # a career is plain JSON
        sizes.append(len(c.active()))
        for n in FOUR:
            assert len(c.squads[n]) == SQUAD and all(c.players[p]["retired"] is None for p in c.pools[n])
    assert c.year > test_career.last_real_year()
    made = [r for r in c.players.values() if r["made_up"]]
    assert made and all(r["caps"] <= 4 * 7 and r["src"] in start or r["src"] for r in made)
    assert len({r["name"] for r in c.players.values()}) >= len(c.players) - 3, "made-up names are new"
    gone = [r for r in c.players.values() if r["retired"]]
    assert gone and all(r["id"] not in c.active() for r in gone)
    assert 0.7 * sizes[0] <= sizes[-1] <= 1.4 * sizes[0], sizes
    old = next(pid for pid in start if pid in c.active())
    assert c.age(old) == c.year - start[old]["born"]
    s = c.state()
    assert s["kind"] == "test" and len(s["history"]) == 4 and s["leaders"]["runs"][0]["runs"] > 500
    row = s["squads"]["England"][0]
    assert {"name", "age", "role", "caps", "in_squad", "bat_avg"} <= set(row) and row["in_squad"]
    again = TestCareer(test_career.last_real_year() - 1, nations=FOUR, user="England", rounds=1, seed=5)
    assert again.squads == TestCareer(test_career.last_real_year() - 1, nations=FOUR, user="England", rounds=1,
                                      seed=5).squads, "the same seed starts the same career"


def test_server_test_career():
    tmp = Path(tempfile.mkdtemp())
    web_ui.LAST, web_ui.CAREERS = tmp / "last", tmp / "careers"
    cl = web_ui.app.test_client()
    meta = cl.get("/api/meta").get_json()
    assert meta["test_career"]["years"][0] == test_career.FIRST_YEAR and "India" in meta["test_career"]["nations"]["2015"]
    r = cl.post("/api/career/new", json={"league": "test", "season": "1990"})
    assert r.status_code == 400 and "starts in" in r.get_json()["error"]
    r = cl.post("/api/career/new", json={"league": "test", "season": "2018", "nations": FOUR, "user": "Australia",
                                         "rounds": 1, "seed": "9"})
    assert r.status_code == 200, r.get_json()
    cid, st = r.get_json()["id"], r.get_json()["state"]
    assert st["kind"] == "test" and st["user"] == "Australia" and st["matches"] == 7 and st["season"] == "2018"
    assert cl.get("/api/careers").get_json()[0]["kind"] == "test"
    r = cl.post("/api/run", json={"mode": "career", "career": cid, "fmt": "t20"})     # the format is the career's
    assert r.status_code == 200, r.get_json()
    deadline = time.time() + 240
    while time.time() < deadline:
        s = cl.get("/api/status").get_json()
        if s["status"] != "running":
            break
        time.sleep(0.1)
    assert s["status"] == "done", s
    res = cl.get("/api/results").get_json()
    assert res["format"] == "test" and res["mode"] == "career" and len(res["fixtures"]) == 7
    st = cl.get("/api/career?id=" + cid).get_json()["state"]
    assert st["season"] == "2019" and st["phase"] == "season" and len(st["history"]) == 1
    run = st["history"][0]["run"]
    assert cl.get("/api/results?run=" + run).get_json()["winner"] == st["history"][0]["champion"]


def main() -> None:
    fns = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    for name, fn in fns:
        t = time.time()
        fn()
        print(f"ok   {name}  ({time.time() - t:.1f}s)")
    print(f"{len(fns)} tests passed")


if __name__ == "__main__":
    main()
