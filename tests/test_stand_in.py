"""Tests for estimated ratings: a player with no record in a format, rated from another (engine/stand_in.py).

    python tests/test_stand_in.py          (no pytest needed; also works under pytest)

An IPL side's T20-only players get ODI and Test ratings from their T20 record: the fitted line keeps their order
(a better T20 batter is a better ODI batter) but shrinks it, more for Tests; the estimate is uncertain; bowlers
bowl their share of the longer format's overs. First-class (Test) and List A (ODI) records sharpen the estimate where
Wikipedia has them: fitted without the records they predict, weighted only the sensible way round, and a bowler's
overs come from his domestic overs. The side plays an ODI and a Test through the server, the set-up screen is told
who is estimated (and with which domestic record), and only a side with a player rated in no format is refused.
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import web_ui  # noqa: E402
from engine import stand_in  # noqa: E402
from engine.data import player, ratings, resolve  # noqa: E402

CSK = "Chennai Super Kings 2026"


def _team(name: str) -> dict:
    defaults = json.loads((ROOT / "data" / "teams_default.json").read_text(encoding="utf-8"))
    return next(t for t in defaults if t["name"] == name)


def _client():
    tmp = Path(tempfile.mkdtemp())
    web_ui.LAST = tmp / "last"
    web_ui.TEAMS = tmp / "teams.json"
    return web_ui.app.test_client()


def test_the_fit_keeps_order_and_shrinks_more_for_tests():
    odi, test = stand_in.mapping("t20", "odi"), stand_in.mapping("t20", "test")
    for side in ("bat", "bowl"):
        for m in ("runs", "wkt"):
            a, b, r2, lo, hi = odi[side][m]
            assert b > 0 and 0 < r2 < 1 and lo < 0 < hi, (side, m, odi[side][m])
            assert test[side][m][2] < r2, (side, m)            # T20 says less about a Test than an ODI
    assert 1.5 < odi["opm"] < 3.5 and test["opm"] > odi["opm"]  # 4 T20 overs -> most of 10 ODI overs, more in a Test


def test_a_t20_only_player_is_rated_for_odis_and_tests():
    t20 = ratings("t20")["players"]
    only = [p for p in _team(CSK)["players"] if p["id"] not in ratings("odi")["players"]]
    assert len(only) >= 5
    for p in only:
        assert stand_in.source("odi", p["id"]) == "t20" and resolve("odi", p["id"]) == p["id"]
        e = player("odi", p["id"])
        assert e.estimated_from == "t20" and e.name == t20[p["id"]]["name"] and e.caps == 0
        assert set(e.bat) == {"powerplay", "middle", "death"} and set(player("test", p["id"]).bat) == {"all"}
        if t20[p["id"]].get("bat"):
            assert e.rated_bat and 0 < e.bat_conf < t20[p["id"]]["bat"]["confidence"]
        if (t20[p["id"]].get("bowl") or {}).get("balls", 0) > 300:
            assert 4 < e.bowl_overs_per_match <= 10.5, (e.name, e.bowl_overs_per_match)
    # a rated player is untouched
    assert player("odi", "45a43fe2").estimated_from is None and stand_in.source("odi", "45a43fe2") is None


def test_a_better_t20_batter_is_a_better_estimated_batter():
    """Two top-order T20-only batters: the one with the higher T20 runs index has the higher estimate, and the
    gap is smaller than in T20."""
    t20, odi = ratings("t20")["players"], ratings("odi")["players"]
    tops = [pid for pid, r in t20.items() if pid not in odi and r.get("bat_role") == "top"
            and (r.get("bat") or {}).get("balls", 0) > 1000]
    tops.sort(key=lambda pid: t20[pid]["bat"]["idx"]["runs"])
    lo, hi = tops[0], tops[-1]
    t_gap = t20[hi]["bat"]["idx"]["runs"] / t20[lo]["bat"]["idx"]["runs"]
    o_gap = player("odi", hi).bat["middle"]["runs"] / player("odi", lo).bat["middle"]["runs"]
    s_gap = player("test", hi).bat["all"]["runs"] / player("test", lo).bat["all"]["runs"]
    assert 1 < s_gap < o_gap < t_gap, (t_gap, o_gap, s_gap)


def test_domestic_records_are_fitted_without_the_format_they_predict():
    """A Test player's first-class record, less his Tests, is what the line is fitted on; each kept weight points
    the sensible way (a higher average, fewer dismissals; a higher economy, more runs; a higher strike rate, fewer
    wickets) and adds to what the T20 record explains."""
    warner = ratings("test")["players"]["dcce6f09"]
    fc = stand_in._styles()["dcce6f09"]["first_class"]
    d = stand_in.domestic("test", "dcce6f09", warner)
    fc_outs = stand_in._num(fc["runs"]) / stand_in._num(fc["bat_avg"])
    t_outs = warner["totals"]["runs"] / warner["totals"]["bat_avg"]
    assert abs(d["bat"]["wkt"][1] - (fc_outs - t_outs)) < 0.5                 # his Tests taken away
    fit = stand_in.mapping("t20", "test")
    dom = fit["dom"]
    assert "wkt" in dom["bat"] and "runs" in dom["bowl"], dom.keys()
    for side, ms in dom.items():
        if side in ("bat", "bowl"):
            for m, (a, b, c, r2, lo, hi) in ms.items():
                assert c * stand_in.DOM_X[side][m] > 0, (side, m, c)
                assert r2 >= fit[side][m][2] - 1e-9, (side, m)
    assert 0.9 < dom["opm"] < 1.4                                            # a Test is much like a first-class match


def test_a_better_first_class_record_means_a_better_test_estimate():
    """The same T20-only batter with a first-class average of 60 is out less often in a Test than with one of 20;
    the same bowler with a first-class economy of 2.5 concedes less than with 4. Without the record he gets the
    plain estimate."""
    pid = next(p["id"] for p in _team(CSK)["players"] if player("t20", p["id"]).name == "S Dube")
    fit = stand_in.mapping(stand_in.source("test", pid), "test")      # fitted on the real records first
    real = stand_in._styles

    def with_fc(fc):
        stand_in._styles = lambda: {pid: {"first_class": fc}}
        stand_in.record.cache_clear()
        try:
            return stand_in.record("test", pid)
        finally:
            stand_in._styles = real
            stand_in.record.cache_clear()

    def fc(avg, econ):
        return {"matches": "60", "runs": str(40 * avg), "bat_avg": str(avg), "balls": "6000", "wkts": "100",
                "bowl_avg": str(econ * 10)}
    good, poor, none = with_fc(fc(60, 2.5)), with_fc(fc(20, 4.0)), with_fc(None)
    assert good["estimated_with"] == poor["estimated_with"] == "first_class" and none["estimated_with"] is None
    assert good["bat"]["idx"]["wkt"] < poor["bat"]["idx"]["wkt"]
    assert good["bowl"]["idx"]["runs"] < poor["bowl"]["idx"]["runs"]
    assert good["opm"] == round(100 / 6 * fit["dom"]["opm"], 2)             # 6000 balls in 60 matches
    assert none["opm"] != good["opm"]


def test_a_thin_record_in_the_nearer_format_does_not_win():
    """Noor Ahmad's 13 ODIs are known only as Wikipedia totals; his Test estimate comes from his ball-by-ball T20
    record, and he bowls a frontline spinner's share."""
    pid = next(p["id"] for p in _team(CSK)["players"] if player("t20", p["id"]).name == "Noor Ahmad")
    assert "ball_by_ball" not in ratings("odi")["players"][pid]["source"]
    assert stand_in.source("test", pid) == "t20" and player("test", pid).bowl_overs_per_match > 20


def test_an_ipl_side_plays_an_odi_and_a_test():
    cl = _client()
    for fmt, comp in (("odi", "odi"), ("test", "test")):
        run = {"fmt": fmt, "comp": comp, "year": 2025, "venues": [], "seed": "5", "mode": "series",
               "team1": CSK, "team2": "Punjab Kings 2026", "matches": 1}
        r = cl.post("/api/run", json=run)
        assert r.status_code == 200, r.get_json()
        while (st := cl.get("/api/status").get_json())["status"] == "running":
            time.sleep(0.2)
        assert st["status"] == "done", st


def test_the_setup_screen_is_told_who_is_estimated():
    cl = _client()
    teams = {t["name"]: t for t in cl.get("/api/meta").get_json()["teams"]}
    est = [p for p in teams[CSK]["players"] if p.get("est", {}).get("odi")]
    assert len(est) == 9 and all(p["est"]["odi"] == "t20" for p in est)
    fc = [p for p in teams[CSK]["players"] if p.get("est_with", {}).get("test") == "first_class"]
    assert len(fc) >= 10 and all("test" in p["est"] for p in fc)
    assert not any("t20" in p.get("est", {}) for p in teams[CSK]["players"])
    saved = {t["name"]: t for t in cl.get("/api/teams").get_json()}       # not written to the saved teams
    assert not any("est" in p for p in saved[CSK]["players"])


def test_only_a_player_rated_nowhere_stops_a_side():
    t = dict(_team(CSK))
    assert web_ui.wrong_format(t, "odi", []) is None and web_ui.wrong_format(t, "test", []) is None
    t["players"] = t["players"][:-1] + [{"id": "00000000", "name": "Nobody"}]
    err = web_ui.wrong_format(t, "odi", [])
    assert err.startswith(f"{CSK} cannot play an ODI match:") and "Nobody" in err and "no record in any format" in err
    assert len(web_ui.estimated(_team(CSK), "odi")) == 9


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in tests:
        t = time.time()
        fn()
        print(f"ok   {fn.__name__}  ({time.time() - t:.1f}s)")
    print(f"{len(tests)} tests passed")


if __name__ == "__main__":
    main()
