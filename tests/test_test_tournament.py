"""Tests for Test tournaments, the World Test Championship, a Test series that stops once decided, weaker Test
captains, and Test drafts and auctions.

    python tests/test_test_tournament.py          (no pytest needed; also works under pytest)
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import web_ui  # noqa: E402
from engine import simulate_match  # noqa: E402
from engine.auction import years_pool  # noqa: E402
from engine.draft import Draft, build_pool  # noqa: E402
from engine.test_tournament import POINTS, first_innings_lead, play_wtc, wtc_match_count, wtc_series  # noqa: E402
from engine.tournament import play_series, play_tournament  # noqa: E402
from test_test_engine import AUS, IND, check_card, team  # noqa: E402

DEFAULTS = {t["name"]: t for t in json.loads((ROOT / "data" / "teams_default.json").read_text(encoding="utf-8"))}
NATIONS = [n for n in DEFAULTS if n.endswith(" Test 2025")]


def side(name: str) -> dict:
    return {"name": name, "squad": [p["id"] for p in DEFAULTS[name]["players"]]}


def check(card: dict) -> None:
    """check_card, for a knockout too: a drawn knockout names the side that goes through, the scorecard does not."""
    r = card["result"]
    if card.get("knockout") and r.get("by"):
        card = dict(card, result={"type": r["type"], "winner": None, "text": r["text"].split(" - ")[0]})
    check_card(card)


def check_table(table: list[dict], cards: list[dict]) -> None:
    """A Test table against the scorecards: 12 a win, 6 a tie, 4 a draw; ordered by the share of points won."""
    for r in table:
        mine = [c for c in cards if r["team"] in c["teams"]]
        won = sum(c["result"].get("winner") == r["team"] and c["result"]["type"] == "win" for c in mine)
        tied = sum(c["result"]["type"] == "tie" for c in mine)
        drawn = sum(c["result"]["type"] not in ("win", "tie") for c in mine)
        assert (r["played"], r["won"], r["tied"], r["drawn"]) == (len(mine), won, tied, drawn), r
        assert r["lost"] == len(mine) - won - tied - drawn
        assert r["points"] == POINTS["win"] * won + POINTS["tie"] * tied + POINTS["draw"] * drawn
        assert abs(r["pct"] - 100 * r["points"] / (12 * len(mine))) < 0.06
        assert r["runs_for"] == sum(i["runs"] for c in mine for i in c["innings"] if i["team"] == r["team"])
    assert [r["pos"] for r in table] == list(range(1, len(table) + 1))
    assert all(a["pct"] >= b["pct"] for a, b in zip(table, table[1:])), "ordered by the share of points won"


def test_a_test_tournament():
    names = NATIONS[:4]
    r = play_tournament([side(n) for n in names], fmt="test", year=2025, knockout="final", seed=11)
    cards = r["matches"]
    assert r["kind"] == "tournament" and r["format"] == "test" and len(cards) == 7      # six league Tests, a final
    for c in cards:
        check(c)
    league = [c for c in cards if not c["knockout"]]
    check_table(r["tables"]["League"], league)
    assert all(c["conditions"].get("home") == c["teams"][0] for c in league), "a league Test is at the first side's home"
    final = cards[-1]
    top = [x["team"] for x in r["tables"]["League"][:2]]
    assert final["stage"] == "Final" and sorted(final["teams"]) == sorted(top)
    assert final["result"]["winner"] == r["winner"] and r["runner_up"] in final["teams"] and r["winner"] != r["runner_up"]
    assert r["mvp"]["kind"] in ("test", "test_points") and "hundreds" in r["records"]
    r2 = play_tournament([side(n) for n in names], fmt="test", year=2025, knockout="final", seed=11)
    assert json.dumps(r2["fixtures"]) == json.dumps(r["fixtures"]), "the same seed plays the same tournament"


def test_a_drawn_knockout_has_a_winner():
    seen = 0
    for seed in range(40):
        r = play_tournament([side(n) for n in NATIONS[:2]], fmt="test", year=2025, knockout="final", seed=seed)
        f = r["matches"][-1]
        res = f["result"]
        assert f["knockout"] and res["winner"] in f["teams"] and res["loser"] in f["teams"]
        if res["type"] != "win":                  # the Test was drawn (or tied): the words say why a side goes through
            seen += 1
            lead = first_innings_lead(f)
            assert res["winner"] == (lead or f["teams"][0])
            assert ("on first-innings lead" if lead else "as the higher-placed side") in res["text"]
            if seen == 2:
                break
    assert seen, "no drawn final in 40 seeds"


def test_world_test_championship():
    names = NATIONS[:9]
    assert len(names) == 9
    sched = wtc_series(names, 5)
    assert len(sched) == 27 and len({frozenset(s) for s in sched}) == 27, "nobody meets twice"
    assert all(v == 3 for v in Counter(h for h, _ in sched).values()), "three series at home"
    assert all(v == 3 for v in Counter(a for _, a in sched).values()), "three away"
    assert len(wtc_series(names[:4], 5)) == 4 and len(wtc_series(names[:3], 5)) == 3      # one home series each
    assert wtc_match_count(9, 2) == 55 and wtc_match_count(4, 3) == 13
    seen = []
    r = play_wtc([side(n) for n in names[:5]], tests=2, year=2025, seed=3, on_match=lambda c: seen.append(c["match_no"]))
    cards = r["matches"]
    assert len(cards) == wtc_match_count(5, 2) == 21 and seen == list(range(1, 22))
    league = cards[:-1]
    check_table(r["tables"]["League"], league)
    assert len(r["wtc"]["series"]) == 10
    for s in r["wtc"]["series"]:
        mine = [c for c in league if c["match_no"] in s["matches"]]
        assert len(mine) == 2 and all(c["teams"] == [s["home"], s["away"]] for c in mine)
        assert all(c["conditions"].get("home") == s["home"] for c in mine)
        wins = [sum(c["result"].get("winner") == t for c in mine) for t in (s["home"], s["away"])]
        assert s["score"] == wins and s["draws"] == 2 - sum(wins)
    table = r["tables"]["League"]
    final = cards[-1]
    assert final["knockout"] and final["teams"] == [table[0]["team"], table[1]["team"]]
    assert final["venue"] and "Lord's" in final["venue"] and r["winner"] == final["result"]["winner"]
    for bad in (lambda: play_wtc([side(n) for n in names[:2]]), lambda: play_wtc([side(n) for n in names[:4]], tests=4)):
        try:
            bad()
            raise AssertionError("accepted")
        except ValueError:
            pass


def test_a_series_that_stops_once_decided():
    ind, aus = team("India", IND), team("Australia", AUS)
    lengths = set()
    for seed in range(8):
        r = play_series(ind, aus, n=3, fmt="test", year=2023, seed=seed, best_of=True)
        full = play_series(ind, aus, n=3, fmt="test", year=2023, seed=seed)
        a, b = r["teams"]
        cards = r["matches"]
        assert len(full["matches"]) == 3 and full["best_of"] is None and r["best_of"] == 3 and r["tests"] == 3
        assert [c["result"]["text"] for c in cards] == [c["result"]["text"] for c in full["matches"]][:len(cards)]
        for k in range(1, len(cards) + 1):          # it stops at the first Test after which one side cannot be caught
            w = Counter(c["result"].get("winner") for c in cards[:k])
            decided = abs(w[a] - w[b]) > 3 - k
            assert decided == (k == len(cards)) or k == 3
        assert r["draws"] == len(cards) - sum(r["score"].values())
        lengths.add(len(cards))
    assert lengths == {2, 3}, lengths


def test_weaker_captains():
    a, b = team("India", IND), team("Australia", AUS)
    dump = lambda c: json.dumps(c, sort_keys=True)
    base = simulate_match(a, b, fmt="test", year=2023, seed=21)
    assert dump(simulate_match(a, b, fmt="test", year=2023, seed=21, skill={"India": "expert"})) == dump(base)
    assert dump(simulate_match(a, b, fmt="test", year=2023, seed=21, skill={"Nobody": "easy"})) == dump(base)
    changed = 0
    skill = {"India": "easy", "Australia": "average"}
    for seed in range(21, 25):
        easy = simulate_match(a, b, fmt="test", year=2023, seed=seed, skill=skill)
        check_card(easy)
        assert dump(easy) == dump(simulate_match(a, b, fmt="test", year=2023, seed=seed, skill=skill)), \
            "a weaker captain's match is reproduced by its seed"
        changed += dump(easy) != dump(simulate_match(a, b, fmt="test", year=2023, seed=seed))
    assert changed >= 3, "a weaker captain makes different calls"


def test_draft_and_auction_of_test_players():
    pool = build_pool("test", 1990, 2000)
    best = [p.name for p in sorted(pool, key=lambda p: -p.value())[:12]]
    assert len(pool) > 200 and {"M Muralitharan", "GD McGrath", "CEL Ambrose"} & set(best), best
    teams = ["Lions", "Tigers", "Bears", "Wolves"]
    d = Draft("test", 1990, 2000, teams, seed=2)
    d.run_cpu()
    assert d.done and all(len(v) == d.squad for v in d.picks.values())
    r = play_tournament(d.team_specs(), fmt="test", year=2000, knockout="final", seed=2)
    assert len(r["matches"]) == 7 and r["winner"] in teams
    for c in r["matches"]:
        check(c)
    lots = years_pool("test", 1990, 2000, teams)["lots"]
    assert len(lots) == 120 and all(x.value >= y.value for x, y in zip(lots, lots[1:]))
    assert {x.role for x in lots} == {"Batter", "Pace", "Spin", "All-rounder", "WK"}
    rank = {x.name: i for i, x in enumerate(lots)}
    assert max(rank[n] for n in ("M Muralitharan", "GD McGrath", "CEL Ambrose")) < 30, "great bowlers are early lots"
    assert sum(x.bowler for x in lots) >= 40, "enough bowlers for four squads"


def _wait(cl, timeout=180) -> dict:
    t = time.time()
    while time.time() - t < timeout:
        s = cl.get("/api/status").get_json()
        if s["status"] in ("done", "error", "cancelled"):
            return s
        time.sleep(0.1)
    raise AssertionError("the run did not finish")


def test_server_runs():
    tmp = Path(tempfile.mkdtemp())
    web_ui.LAST = tmp / "last"                    # don't touch the user's last results
    web_ui.TEAMS = tmp / "teams.json"             # nor their saved teams: start from the presets
    cl = web_ui.app.test_client()
    base = {"comp": "test_full", "year": 2025, "venues": [], "seed": "4", "rain": False}
    for extra, words in (({"mode": "wtc", "teams": NATIONS[:2]}, "at least three"),
                         ({"mode": "wtc", "teams": NATIONS[:4], "tests": 4}, "1, 2, 3 or 5"),
                         ({"mode": "wtc", "teams": NATIONS[:3] + ["India T20 2024"]}, "Test")):
        r = cl.post("/api/run", json={**base, **extra})
        assert r.status_code == 400 and words in r.get_json()["error"], (extra, r.get_json())
    # the Championship, with weaker computer captains; the format is Test whatever the page sent
    r = cl.post("/api/run", json={**base, "mode": "wtc", "fmt": "t20", "teams": NATIONS[:4], "tests": 1,
                                  "opponents": "easy"})
    assert r.status_code == 200, r.get_json()
    assert _wait(cl)["status"] == "done"
    res = cl.get("/api/results").get_json()
    assert res["format"] == "test" and len(res["fixtures"]) == 5 and len(res["wtc"]["series"]) == 4
    assert res["title"].startswith("World Test Championship - 4 teams") and res["winner"] in NATIONS[:4]
    assert {"drawn", "pct"} <= set(res["tables"]["League"][0])
    # a Test tournament
    r = cl.post("/api/run", json={**base, "mode": "tournament", "fmt": "test", "teams": NATIONS[:4], "rounds": 1,
                                  "groups": 1, "knockout": "final"})
    assert r.status_code == 200, r.get_json()
    assert _wait(cl)["status"] == "done"
    res = cl.get("/api/results").get_json()
    assert res["format"] == "test" and len(res["fixtures"]) == 7 and res["tables"]["League"][0]["pos"] == 1
    assert cl.get("/api/match/7").get_json()["card"]["stage"] == "Final"


def main() -> None:
    fns = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    for name, fn in fns:
        fn()
        print("ok  ", name)
    print(f"{len(fns)} tests passed")


if __name__ == "__main__":
    main()
