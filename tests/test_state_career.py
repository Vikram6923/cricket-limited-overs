"""State career (engine/state_career.py): a Mushtaq Ali Trophy state season after season, Elite and Plate.

    python tests/test_state_career.py          (no pytest needed; also works under pytest)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.state_career import SQUAD_MAX, SQUAD_MIN, StateCareer, _deal, load, start_seasons  # noqa: E402
from engine.tournament import play_tournament  # noqa: E402


def test_start_and_checks():
    assert set(start_seasons()) == {"2020-21", "2021-22", "2025-26"}, "the seasons with a Plate"
    for bad in (("2019-20", None), ("2021-22", "Nowhere")):
        try:
            StateCareer(*bad)
            raise AssertionError(bad)
        except ValueError:
            pass
    c = StateCareer("2025-26", user="Mumbai", seed=1)
    assert len(c.franchises) == 38 and len(c.elite()) == 32 and len(c.plate) == 6
    assert c.state()["kind"] == "state" and c.phase == "season"


def test_snake_groups():
    g = _deal(list("abcdefghij"), ["A", "B", "C"], [4, 3, 3])
    assert g == {"A": ["a", "f", "g"] + ["j"], "B": ["b", "e", "h"], "C": ["c", "d", "i"]}


def test_seasons_promotion_and_squads():
    c = StateCareer("2020-21", user="Mumbai", seed=7)
    for k in range(2):
        res = play_tournament(c.specs(), **c.play_args())
        assert len(res["matches"]) == c.match_total()
        elite_before, plate_before = set(c.elite()), set(c.plate)
        h = c.record(res)
        assert h["promoted"] in plate_before and h["relegated"] in elite_before
        assert h["promoted"] in c.elite() and h["relegated"] in c.plate, "up and down for next season"
        assert sorted(len(g) for g in c.groups.values()) == [6] * 5 and len(c.plate) == 8
        assert h["user_pos"] and h["orange"] and h["purple"]
        c.advance()
        assert c.phase == "season" and c.season_label == ("2021-22", "2022-23")[k]
        sizes = [len(s) for s in c.squads.values()]
        assert max(sizes) <= SQUAD_MAX and (k == 0 or min(sizes) >= SQUAD_MIN), sizes
        c = load(json.loads(json.dumps(c.to_json())))
        assert isinstance(c, StateCareer)
    news = " ".join(c.news)
    assert "young players make their state debuts" in news, "2022-23 is past the real seasons: made-up newcomers"
    made = [p for p in c.players.values() if p["made_up"] and p["retired"] is None]
    assert made and all(p["nation"] == "India" for p in made)
    assert len(c.history) == 2 and c.stats


def test_web_career():
    import tempfile
    import time
    import web_ui
    tmp = Path(tempfile.mkdtemp())
    web_ui.LAST, web_ui.CAREERS = tmp / "last", tmp / "careers"     # don't touch the user's results or careers
    cl = web_ui.app.test_client()
    meta = cl.get("/api/meta").get_json()
    assert meta["domestic"][0]["career_seasons"]
    new = {"league": "sma", "season": "2021-22", "user": "Kerala", "seed": "3"}
    d = cl.post("/api/career/new", json=new).get_json()
    cid, st = d["id"], d["state"]
    assert st["kind"] == "state" and st["user"] == "Kerala" and st["matches"] > 100
    assert cl.post("/api/run", json={"mode": "career", "career": cid, "fmt": "t20", "rain": True}).status_code == 200
    for _ in range(600):
        s = cl.get("/api/status").get_json()
        if s["status"] != "running":
            break
        time.sleep(0.5)
    assert s["status"] == "done" and s["done"] == st["matches"], s
    st = cl.get("/api/career?id=" + cid).get_json()["state"]
    assert len(st["history"]) == 1 and st["season"] == "2022-23" and st["phase"] == "season"
    assert any(c["id"] == cid and c["kind"] == "state" for c in cl.get("/api/careers").get_json())
    r = cl.get("/api/results").get_json()
    assert r["mode"] == "career" and r["plate"]["winner"] and r["relegated"]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
