"""Tests for a Test's playing conditions: its length (three to six days, timeless), day-night Tests, the
draw agreed in the last hour, injuries and replacements, and these choices on the server.

    python tests/test_test_conditions.py          (no pytest needed; also works under pytest)
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
from engine import history, simulate_match, test_captain, test_conditions  # noqa: E402
from test_test_engine import AUS, IND, check_card, team  # noqa: E402
from test_test_series import _wait  # noqa: E402

GROUND = "Eden Gardens, Kolkata"


def play(seed, **kw):
    return simulate_match(team("India", IND), team("Australia", AUS), fmt="test", year=2023, seed=seed,
                          venue=GROUND, use_wdl=False, **kw)


def rpw(cards):
    return sum(i["runs"] for c in cards for i in c["innings"]) / sum(i["wickets"] for c in cards for i in c["innings"])


def test_day_night():
    t = test_conditions.day_night()
    assert set(t) == {"pace", "spin"}
    assert 1.05 < t["pace"]["wkt"] < 1.4 and 0.9 < t["pace"]["runs"] < 1.1, t
    fit = json.loads((ROOT / "data" / "engine" / "test_daynight.json").read_text(encoding="utf-8"))
    assert fit["matches"] >= 25 and not fit["missing"], "every listed day-night Test is in the data"
    day = [play(s) for s in range(25)]
    night = [play(s, day_night=True) for s in range(25)]
    for c in night:
        check_card(c)
        assert c["day_night"] and c["conditions"]["day_night"] and "pink ball" in c["conditions"]["report"]
    assert "day_night" not in day[0] and "day_night" not in day[0]["conditions"]
    assert rpw(night) < 0.92 * rpw(day), (rpw(night), rpw(day))


def test_length_and_timeless():
    assert [test_captain.follow_on_lead(d) for d in (3, 4, 5, 6)] == [150, 150, 200, 200]
    for days in (3, 4, 6):
        for s in range(6):
            c = play(s, days=days)
            check_card(c)
            assert c["scheduled_days"] == days and len(c["days"]) <= days and "timeless" not in c
    short = sum(play(s, days=3)["result"]["type"] == "draw" for s in range(30))
    full = sum(play(s)["result"]["type"] == "draw" for s in range(30))
    assert short > full, "three days leave more Tests unfinished than five"
    drawn = 0
    for s in range(30):
        c = play(s, timeless=True, days=3)             # days is ignored
        check_card(c)
        assert c["timeless"] and c["scheduled_days"] == test_conditions.TIMELESS_DAYS
        assert not any(e["kind"] in ("declaration", "last_hour", "agreed_draw") for e in c["events"])
        if c["result"]["type"] == "draw":              # only when ten days were not enough (rain)
            drawn += 1
            assert len(c["days"]) + sum(1 for e in c["events"] if e["kind"] == "weather") >= c["scheduled_days"]
    assert drawn <= 3, drawn


def test_last_hour():
    agreed = 0
    for s in range(60):
        c = play(s, days=3)
        ev = [e for e in c["events"] if e["kind"] == "agreed_draw"]
        full = play(s, days=3, last_hour=False)
        assert c["result"] == full["result"], "the handshake comes only when nothing could change"
        assert not any(e["kind"] in ("last_hour", "agreed_draw") for e in full["events"])
        if not ev:
            continue
        agreed += 1
        last = c["innings"][-1]
        assert c["result"]["type"] == "draw" and last["number"] <= 3 and last["ended"] == "time"
        assert ev[0]["overs"] <= test_conditions.LAST_HOUR_OVERS and ev[0]["day"] == 3
        assert any(e["kind"] == "last_hour" for e in c["events"])
        assert sum(len(i["overs_log"]) for i in c["innings"]) < sum(len(i["overs_log"]) for i in full["innings"])
    assert agreed >= 3, agreed


def test_injuries():
    real = test_conditions.injuries()
    assert 1 / 100000 < real["retire"]["per_ball"] < 1 / 10000 and real["retire"]["returns"] == 0
    assert 0 <= real["retire"]["plays_on"] <= 0.5 and 0 < real["replaced"] <= 1 and real["subs_from"] == 2019
    # a match in which nobody is hurt is the same match with injuries off
    c = play(3)
    assert not any(e["kind"] in ("injury", "retired_hurt", "replacement") for e in c["events"])
    assert json.dumps(c, sort_keys=True) == json.dumps(play(3, injuries=False), sort_keys=True)
    often = {**real, "retire": {**real["retire"], "per_ball": 1 / 400}, "field": {"per_ball": 1 / 600},
             "replaced": 1.0}
    keep = test_conditions.injuries
    test_conditions.injuries = lambda: often
    try:
        seen = {"retired_hurt": 0, "injury": 0, "replacement": 0}
        for s in range(40):
            c = play(s)                                # two elevens: nobody to come in
            check_card(c)
            assert "replacements" not in c
            for e in c["events"]:
                if e["kind"] in seen:
                    seen[e["kind"]] += 1
            gone = set()
            for inn in c["innings"]:
                assert [b["position"] for b in inn["batting"]] == list(range(1, len(inn["batting"]) + 1))
                names = {b["name"] for b in inn["batting"]} | {b["name"] for b in inn["bowling"]}
                assert not (gone & names), "a man lost for the match played on"
                for b in inn["batting"]:
                    if b["dismissal"] == "retired hurt":
                        assert not b["out"] and b["batted"]
                gone |= set(inn.get("absent_hurt") or [])
                assert sorted(inn.get("absent_hurt") or []) == sorted(
                    x for x in gone if any(e["kind"] == "injury" and x in e["text"] and e["innings"] < inn["number"]
                                           for e in c["events"]) and x in (inn.get("absent_hurt") or []))
        assert seen["retired_hurt"] > 40 and seen["injury"] > 40 and seen["replacement"] == 0, seen
        # squads: a like-for-like man comes in (from 2019) and plays the rest of the match
        a, b = (history.historical_team("test", n, 2021, 2024) for n in ("India", "Australia"))
        came = 0
        for s in range(12):
            c = simulate_match(a, b, fmt="test", year=2023, seed=s, venue=GROUND, use_wdl=False)
            check_card(c)
            for r in c.get("replacements", []):
                came += 1
                xi = {p["id"] for p in c["xi"][r["team"]]}
                later = {x["out_id"] for x in c["replacements"]}        # he may be hurt in his turn
                assert (r["in_id"] in xi or r["in_id"] in later) and r["out_id"] not in xi
                after = [i for i in c["innings"] if i["number"] > r["innings"]]
                assert not any(r["out"] in {x["name"] for x in i["batting"] + i["bowling"]} for i in after)
            old = simulate_match(a, b, fmt="test", year=2010, seed=s, venue=GROUND, use_wdl=False)
            assert "replacements" not in old, "no replacements before 2019"
        assert came > 5, came
    finally:
        test_conditions.injuries = keep


def test_server_length_and_day_night():
    tmp = Path(tempfile.mkdtemp())
    web_ui.LAST = tmp / "last"
    web_ui.TEAMS = tmp / "teams.json"
    cl = web_ui.app.test_client()
    base = {"fmt": "test", "comp": "test_full", "year": 2025, "venues": [], "seed": "11", "rain": True,
            "mode": "series", "team1": "India Test 2025", "team2": "Australia Test 2025", "matches": 2}
    r = cl.post("/api/run", json={**base, "length": "9"})
    assert r.status_code == 400 and "timeless" in r.get_json()["error"]
    assert cl.post("/api/run", json={**base, "length": "4", "day_night": True}).status_code == 200
    assert _wait(cl)["status"] == "done"
    card = cl.get("/api/match/1").get_json()["card"]
    assert card["scheduled_days"] == 4 and card["day_night"] and "timeless" not in card
    assert cl.post("/api/run", json={**base, "length": "timeless"}).status_code == 200
    assert _wait(cl)["status"] == "done"
    card = cl.get("/api/match/2").get_json()["card"]
    assert card["timeless"] and "day_night" not in card
    assert cl.post("/api/run", json=base).status_code == 200          # nothing asked: five days, a day Test
    assert _wait(cl)["status"] == "done"
    card = cl.get("/api/match/1").get_json()["card"]
    assert card["scheduled_days"] == 5 and "day_night" not in card and "timeless" not in card
    # a two-player Test room keeps the same two settings
    from server.rooms import _mp_settings
    st = _mp_settings({"fmt": "test", "year": 2025, "length": "timeless", "day_night": True})
    assert st["length"] == "timeless" and st["day_night"] is True
    st = _mp_settings({"fmt": "test", "year": 2025, "length": "12"})
    assert st["length"] == "5" and st["day_night"] is False
    st = _mp_settings({"fmt": "t20", "year": 2025, "length": "3", "day_night": True})
    assert st["length"] == "5" and st["day_night"] is False


def main() -> None:
    fns = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    for name, fn in fns:
        t = time.time()
        fn()
        print(f"ok   {name}  ({time.time() - t:.1f}s)")
    print(f"{len(fns)} tests passed")


if __name__ == "__main__":
    main()
