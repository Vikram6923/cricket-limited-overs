"""Tests for Test series, their statistics and report, Classic Test sides, and a Test run through the server
(Phase 4 of docs/test_match_plan.md).

    python tests/test_test_series.py          (no pytest needed; also works under pytest)
"""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import web_ui  # noqa: E402
from engine import history  # noqa: E402
from engine.render import full_text, match_report  # noqa: E402
from engine.test_report import day_strip, position  # noqa: E402
from engine.test_series import (home_grounds, innings_scores, nation_of, play_test_series, result_text,  # noqa: E402
                                series_grounds)
from engine.tournament import play_series, play_tournament  # noqa: E402
from test_test_engine import AUS, IND, check_card, team  # noqa: E402


def _sides():
    return team("India", IND), team("Australia", AUS)


def test_series_result_and_bookkeeping():
    ind, aus = _sides()
    for n, seed in ((1, 3), (2, 4), (3, 5), (5, 6)):
        r = play_series(ind, aus, n=n, fmt="test", year=2023, seed=seed)       # the dispatch in play_series
        cards = r["matches"]
        assert r["kind"] == "series" and r["format"] == "test" and len(cards) == n, "every Test is played"
        for i, c in enumerate(cards, 1):
            check_card(c)
            assert c["match_no"] == i and c["knockout"] is False
            assert c["stage"] == ("Only Test" if n == 1 else f"{('1st', '2nd', '3rd', '4th', '5th')[i - 1]} Test")
        wins = {t: sum(c["result"].get("winner") == t for c in cards) for t in r["teams"]}
        draws = sum(c["result"]["type"] != "win" for c in cards)
        assert r["score"] == wins and r["draws"] == draws and sum(wins.values()) + draws == n
        a, b = r["teams"]
        assert r["winner"] == (a if wins[a] > wins[b] else b if wins[b] > wins[a] else None)
        if n == 1:
            assert r["result"] == cards[0]["result"]["text"]
        elif r["winner"]:
            lo, hi = sorted(wins.values())
            assert r["result"] == f"{r['winner']} won the series {hi}-{lo}"
        else:
            assert r["result"] == f"Series drawn {wins[a]}-{wins[b]}"
        assert [f["match_no"] for f in r["fixtures"]] == list(range(1, n + 1))
        for f, c in zip(r["fixtures"], cards):
            assert f["result"] == c["result"]["text"] and f["scores"] == innings_scores(c)
            assert f["days"] == len(c["days"]) and f["venue"] == c["venue"]
    assert result_text("A", "B", 2, 1, 5) == "A won the series 2-1"        # two draws
    assert result_text("A", "B", 1, 3, 5) == "B won the series 3-1"
    assert result_text("A", "B", 1, 1, 3) == "Series drawn 1-1"
    # the same seed plays the same series; another seed does not
    r1, r2 = (play_test_series(ind, aus, n=2, year=2023, seed=9) for _ in range(2))
    assert [full_text(c) for c in r1["matches"]] == [full_text(c) for c in r2["matches"]]
    r3 = play_test_series(ind, aus, n=2, year=2023, seed=10)
    assert [full_text(c) for c in r1["matches"]] != [full_text(c) for c in r3["matches"]]
    for bad in (0, 7):
        try:
            play_test_series(ind, aus, n=bad)
            raise AssertionError("a series of 0 or 7 Tests was accepted")
        except ValueError:
            pass


def test_host_grounds_and_home_side():
    ind, aus = _sides()
    g = home_grounds()
    assert len(g["India"]) >= 5 and len(g["Australia"]) >= 5 and "Lord's" in g["England"]
    assert not any("Dubai" in x or "Abu Dhabi" in x or "Sharjah" in x for x in g["Pakistan"]), "Pakistan at home now"
    assert nation_of(ind) == "India" and nation_of({"name": "India 2021-24", "nation": "India"}) == "India"
    assert nation_of({"name": "My XI", "players": ind["players"]}) == "India", "by most of its players"
    mixed = {"name": "Mixed", "players": ind["players"][:5] + aus["players"][:5]}
    assert nation_of(mixed) is None
    assert series_grounds("India", 3) == g["India"][:3]
    assert series_grounds("India", 2, ["Lord's"]) == ["Lord's", "Lord's"] and series_grounds(None, 2) == [None, None]
    home = play_test_series(ind, aus, n=5, year=2023, seed=2)                 # the first side is at home
    assert home["host"] == "India" and home["home"] == "India"
    assert [c["venue"] for c in home["matches"]] == g["India"][:5]
    assert all(c["conditions"]["host"] == "India" and c["conditions"]["home"] == "India" for c in home["matches"])
    away = play_test_series(ind, aus, n=2, year=2023, seed=2, host="Australia")
    assert away["home"] == "Australia" and [c["venue"] for c in away["matches"]] == g["Australia"][:2]
    neutral = play_test_series(ind, aus, n=2, year=2023, seed=2, host="neutral")
    assert neutral["host"] is None and neutral["home"] is None
    assert all(c["venue"] is None and c["conditions"]["home"] is None for c in neutral["matches"])
    lords = play_test_series(ind, aus, n=1, year=2023, seed=2, venues=["Lord's"])
    c = lords["matches"][0]
    assert c["venue"] == "Lord's" and c["conditions"]["host"] == "England" and c["conditions"]["home"] is None
    # a side named for its years is still its nation's: "India 2021-24" is at home in India
    named = play_test_series({**ind, "name": "India 2021-24", "nation": "India"}, aus, n=1, year=2023, seed=2)
    assert named["home"] == "India 2021-24"
    mine = play_test_series({**ind, "name": "My XI"}, aus, n=1, year=2023, seed=2)       # by its players
    assert mine["host"] == "India" and mine["home"] == "My XI"


def test_stats_add_up():
    ind, aus = _sides()
    r = play_test_series(ind, aus, n=5, year=2023, seed=12)
    cards = r["matches"]
    inns = [i for c in cards for i in c["innings"]]
    assert sum(b["runs"] for b in r["batting"]) == sum(x["runs"] for i in inns for x in i["batting"])
    assert sum(w["wickets"] for w in r["bowling"]) == sum(x["wickets"] for i in inns for x in i["bowling"])
    assert all(b["matches"] == 5 for b in r["batting"]), "the same XI played all five"
    for b in r["batting"]:
        mine = [x for i in inns if i["team"] == b["team"] for x in i["batting"] if x["id"] == b["id"] and x["batted"]]
        assert b["inns"] == len(mine) <= 10 and b["not_outs"] == sum(not x["out"] for x in mine)
        assert b["hundreds"] == sum(x["runs"] >= 100 for x in mine)
        assert b["fifties"] == sum(50 <= x["runs"] < 100 for x in mine)
        outs = b["inns"] - b["not_outs"]
        assert b["average"] == (round(b["runs"] / outs, 2) if outs else None)
        assert int(b["hs"].rstrip("*")) == max(x["runs"] for x in mine)
    for w in r["bowling"]:
        per_match = []
        for c in cards:
            figs = [x for i in c["innings"] if i["bowling_team"] == w["team"] for x in i["bowling"] if x["id"] == w["id"]]
            if figs:
                per_match.append((sum(x["wickets"] for x in figs), sum(x["runs"] for x in figs), c["match_no"]))
        best = max(per_match, key=lambda f: (f[0], -f[1]))
        assert w["best_match_figures"] == f"{best[0]}/{best[1]}" and w["best_match_no"] == best[2]
        assert w["ten_w"] == sum(f[0] >= 10 for f in per_match)
        mine = [x for i in inns if i["bowling_team"] == w["team"] for x in i["bowling"] if x["id"] == w["id"]]
        assert w["five_w"] == sum(x["wickets"] >= 5 for x in mine) and w["maidens"] == sum(x["maidens"] for x in mine)
        bw, br = (int(v) for v in w["best"].split("/"))
        assert (bw, -br) == max((x["wickets"], -x["runs"]) for x in mine)
    # the ranking: each match's points (four parts) summed; it picks the player of the series
    rank = r["mvp"]["official"]
    assert r["mvp"]["kind"] == "test_points" and r["player_of_series"]["id"] == rank[0]["id"]
    assert [p["rank"] for p in rank] == list(range(1, len(rank) + 1))
    assert all(a["balanced"] >= b["balanced"] for a, b in zip(rank, rank[1:]))
    for p in rank[:6]:
        tot = sum(sum(c["points"].get(p["id"], [0, 0, 0, 0])) for c in cards)
        assert abs(p["balanced"] - tot) < 0.5, (p["name"], p["balanced"], tot)
        assert p["win_pts"] == 25 * sum(c["result"].get("winner") == p["team"] for c in cards)
    for c in cards:
        pom = c["player_of_match"]
        assert pom["id"] == max(c["points"], key=lambda k: sum(c["points"][k]))
    rec = r["records"]
    assert len(rec["biggest_wins_by_an_innings"]) == sum(c["result"].get("by") == "innings" for c in cards)
    assert len(rec["wins_by_wickets"]) == sum(c["result"].get("by") == "wickets" for c in cards)
    assert rec["highest_totals"][0]["runs"] == max(i["runs"] for i in inns)


def test_report_and_day_strip():
    ind, aus = _sides()
    seen = set()
    for seed in range(40):
        c = play_test_series(ind, aus, n=1, year=2023, seed=seed, host="England")["matches"][0]
        text = match_report(c)
        assert text.startswith("At ") and "won the toss" in text and "Day 1:" in text
        assert (c["result"]["text"] in text) or ("Match drawn" in text and c["result"]["type"] == "draw")
        assert f"The player of the match was {c['player_of_match']['name']}" in text
        for d in c["days"]:
            assert (f"Day {d['day']}:" in text) or (d is c["days"][-1]), "every day but perhaps the last is told"
        for i in c["innings"]:
            if i["declared"]:
                assert f"{i['team']} declared at {i['runs']}/{i['wickets']}" in text
                seen.add("declared")
            if i["follow_on"]:
                assert "the follow-on" in text
                seen.add("follow-on")
        if any(not d["overs"] for d in c["days"]):
            assert "No play was possible." in text
            seen.add("washout")
        if c["result"]["type"] == "draw" and sum(d["lost"] for d in c["days"]) >= 90:
            assert "spoiled by the weather" in text
            seen.add("spoiled")
        assert match_report(c) in full_text(c)
        # the strip: one row per interval reached, in order, the score the over log gives
        strip = day_strip(c)
        keys = [(r["day"], r["session"]) for r in strip]
        assert keys == sorted(set(keys)) and {r["day"] for r in strip} == {d["day"] for d in c["days"] if d["overs"]}
        assert strip[-1]["position"] == c["result"]["text"] and strip[-1]["label"].endswith("close")
        for r in strip[:-1]:
            inn = c["innings"][r["innings"] - 1]
            o = [x for x in inn["overs_log"] if x["day"] == r["day"] and x["session"] == r["session"]][-1]
            assert r["team"] == inn["team"] and r["score"].split("/")[0] == str(o["total"])
            assert r["position"] == position(c, r["innings"], o["total"], o["wickets"])
            if r["innings"] == 1:
                assert r["position"] == ""
            elif inn["target"]:
                assert r["position"] in (f"need {inn['target'] - o['total']} more", "target reached")
    assert {"declared", "spoiled"} <= seen, seen


def test_classic_test_sides():
    assert history.first_year("test") == 1877 and history.last_year("test") >= 2025
    for nation, y1, y2, must in (("West Indies", 1980, 1985, ("IVA Richards", "MD Marshall", "CG Greenidge")),
                                 ("Australia", 1946, 1948, ("DG Bradman", "KR Miller", "RR Lindwall")),
                                 ("Australia", 1999, 2003, ("SK Warne", "GD McGrath", "RT Ponting")),
                                 ("India", 2021, 2024, ("V Kohli", "JJ Bumrah", "RA Jadeja"))):
        assert nation in dict(history.nations("test", y1, y2))
        t = history.historical_team("test", nation, y1, y2)
        assert t["nation"] == nation and t["years"] == [y1, y2] and len(t["squad"]) == history.SQUAD_SIZE
        from engine.data import ratings
        names = {ratings("test")["players"][p]["name"] for p in t["squad"]}
        assert set(must) <= names, (t["name"], sorted(names))
    assert "Bangladesh" not in dict(history.nations("test", 1980, 1985))
    # limited overs: the squads are what they were
    assert history.first_year("odi") == 1971 and history.first_year("t20") == 2005
    wi = history.historical_team("test", "West Indies", 1980, 1985)
    au = history.historical_team("test", "Australia", 1999, 2003)
    r = play_test_series(wi, au, n=3, year=1984, seed=1)
    assert r["host"] == "West Indies" and r["home"] == "West Indies 1980-85"
    assert all(v in home_grounds()["West Indies"] for v in (c["venue"] for c in r["matches"]))
    for c in r["matches"]:
        check_card(c)
        assert len(c["xi"]["West Indies 1980-85"]) == 11


def test_tournaments_and_best_of_refuse_tests():
    ind, aus = _sides()
    for call in (lambda: play_tournament([ind, aus], fmt="test"),
                 lambda: play_series(ind, aus, n=3, fmt="test", best_of=True),
                 lambda: play_series(ind, aus, n=3, fmt="test", control={"India": object()})):
        try:
            call()
            raise AssertionError("accepted")
        except ValueError as e:
            assert "Test" in str(e)


def _wait(cl, timeout=120) -> dict:
    t = time.time()
    while time.time() - t < timeout:
        s = cl.get("/api/status").get_json()
        if s["status"] != "running":
            return s
        time.sleep(0.1)
    raise AssertionError("the run did not finish")


def test_server_plays_a_test_series():
    tmp = Path(tempfile.mkdtemp())
    web_ui.LAST = tmp / "last"                    # don't touch the user's last results
    web_ui.TEAMS = tmp / "teams.json"             # nor their saved teams: start from the presets
    cl = web_ui.app.test_client()
    meta = cl.get("/api/meta").get_json()
    assert set(meta["formats"]) == {"t20", "odi", "test"} and meta["years"]["test"][0] == 1877
    assert any(c["id"] == "test_full" for c in meta["formats"]["test"]["competitions"])
    assert len(meta["formats"]["test"]["venues"]) > 30 and "India" in meta["test_hosts"]
    presets = [t["name"] for t in meta["teams"] if t["name"].endswith(" Test 2025")]
    assert {"India Test 2025", "Australia Test 2025", "England Test 2025"} <= set(presets)
    assert len(cl.get("/api/players?fmt=test").get_json()) > 2500
    assert cl.get("/api/players?fmt=xyz").status_code == 400
    nat = cl.get("/api/nations?fmt=test&y1=1980&y2=1985").get_json()
    assert nat["first"] == 1877 and "West Indies" in [n["name"] for n in nat["nations"]]
    base = {"fmt": "test", "comp": "test_full", "year": 2025, "venues": [], "seed": "7", "rain": True}
    two = {"team1": "India Test 2025", "team2": "Australia Test 2025"}
    # what a Test run may not be
    for extra, words in (({"mode": "tournament", "teams": list(two.values())}, "Match / Series"),
                         ({"mode": "draft"}, "Match / Series"), ({"mode": "auction"}, "Match / Series"),
                         ({"mode": "series", **two, "matches": 7}, "1 to 6"),
                         ({"mode": "series", **two, "matches": 3, "host": "moon"}, "home, away or"),
                         ({"mode": "series", **two, "matches": 1, "captain_i": "0"}, "cannot captain a Test")):
        r = cl.post("/api/run", json={**base, **extra})
        assert r.status_code == 400 and words in r.get_json()["error"], (extra, r.get_json())
    assert (tmp / "teams.json").exists(), "the test's own copy of the saved teams"
    # a series away from home
    assert cl.post("/api/run", json={**base, "mode": "series", **two, "matches": 3, "host": "away"}).status_code == 200
    s = _wait(cl)
    assert s["status"] == "done", s
    res = cl.get("/api/results").get_json()
    assert res["format"] == "test" and res["title"] == "India Test 2025 v Australia Test 2025 - 3-Test series"
    assert res["host"] == "Australia" and res["home"] == "Australia Test 2025" and len(res["fixtures"]) == 3
    assert res["draws"] == 3 - sum(res["score"].values())
    assert all("winner" in f for f in res["fixtures"]) and "best_match_figures" in res["bowling"][0]
    m = cl.get("/api/match/2").get_json()
    assert m["card"]["format"] == "test" and m["card"]["stage"] == "2nd Test" and m["report"].startswith("At ")
    assert m["strip"] and m["strip"][0]["label"] == "Day 1, lunch" and "Close of play" in m["text"]
    # the same replay code plays the same series
    cl.post("/api/run", json={**base, "mode": "series", **two, "matches": 3, "host": "away"})
    _wait(cl)
    assert cl.get("/api/match/2").get_json()["text"] == m["text"]
    # Classic: two eras meet; a limited-overs run still works and has no strip
    classic = {"team1": {"nation": "West Indies", "y1": 1980, "y2": 1985},
               "team2": {"nation": "Australia", "y1": 1999, "y2": 2003}}
    assert cl.post("/api/run", json={**base, "mode": "series", **classic, "matches": 2, "squad_size": "20",
                                     "years_mode": "blend", "year": 1984}).status_code == 200
    assert _wait(cl)["status"] == "done"
    res = cl.get("/api/results").get_json()
    assert res["teams"] == ["West Indies 1980-85", "Australia 1999-2003"] and res["home"] == "West Indies 1980-85"
    r = cl.post("/api/run", json={**base, "mode": "series", **classic, "matches": 1})
    assert r.status_code == 200 and _wait(cl)["status"] == "done"
    assert cl.post("/api/run", json={**base, "mode": "series", "matches": 1,
                                     "team1": {"nation": "Bangladesh", "y1": 1980, "y2": 1985},
                                     "team2": classic["team2"]}).status_code == 400
    assert cl.post("/api/run", json={"fmt": "t20", "comp": "t20i_full", "year": 2024, "venues": [], "seed": "3",
                                     "rain": True, "mode": "series", "team1": "India T20 2024",
                                     "team2": "Australia T20 2024", "matches": 1}).status_code == 200
    assert _wait(cl)["status"] == "done"
    assert cl.get("/api/match/1").get_json()["strip"] is None


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in tests:
        fn()
        print(f"ok   {fn.__name__}")
    print(f"{len(tests)} tests passed")


if __name__ == "__main__":
    main()
