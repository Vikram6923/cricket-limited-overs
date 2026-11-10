"""Domestic cup presets (data/domestic_seasons.json): every season is complete and plays as a tournament.

    python tests/test_domestic.py          (no pytest needed; also works under pytest)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.domestic import competitions, match_total, season, tournament_args  # noqa: E402
from engine.leagues import LEAGUES  # noqa: E402
from engine.tournament import play_tournament  # noqa: E402

RATED = set(json.loads((ROOT / "data" / "ratings_t20.json").read_text(encoding="utf-8"))["players"])


def test_every_season_is_complete():
    seasons = competitions()["sma"]["seasons"]
    assert seasons[0]["season"] == "2025-26" and seasons[0]["squads"] == "latest"
    assert {"2018-19", "2019-20", "2020-21", "2021-22"} <= {s["season"] for s in seasons}
    assert not LEAGUES["sma"].league_season, "SMAT seasons live here, not in League Season"
    for s in seasons:
        f = s["format"]
        names = [t["name"] for t in s["teams"]]
        in_groups = [n for g in f["groups"].values() for n in g] + (f["plate"]["teams"] if f["plate"] else [])
        assert sorted(names) == sorted(in_groups) and len(set(names)) == len(names), s["season"]
        for t in s["teams"]:
            assert len(t["players"]) >= 11 and set(t["players"]) <= RATED, (s["season"], t["name"])
        assert s["real"]["winner"] in names and s["real"]["runner_up"] in names, s["season"]
        assert f["win_points"] == 4 and s["venues"]
        args = tournament_args(season("sma", s["season"]))
        assert len(args["teams"]) + len((args.get("plate") or {}).get("teams", [])) == len(names)


def test_a_season_plays_through():
    s = season("sma", "2020-21")
    res = play_tournament(**tournament_args(s), seed=3)
    assert len(res["matches"]) == match_total(s)
    assert [k["stage"] for k in res["knockouts"]][-3:] == ["Semi-final 1", "Semi-final 2", "Final"]
    qf_teams = {t for k in res["knockouts"] if k["stage"].startswith("Quarter") for t in k["teams"]}
    assert res["plate"]["winner"] in qf_teams, "2020-21: the Plate winner plays the quarter-finals"
    venues = set(s["venues"]) | set(s["knockout_venues"])
    assert all(c["venue"] in venues for c in res["matches"])
    assert res["competition"] == "sma" and res["winner"] in res["teams"] + res["plate"]["teams"]


def test_web_mode():
    import tempfile
    import time
    import web_ui
    web_ui.LAST = Path(tempfile.mkdtemp()) / "last"      # don't touch the user's last results
    c = web_ui.app.test_client()
    meta = c.get("/api/meta").get_json()
    cup = meta["domestic"][0]
    assert cup["id"] == "sma" and len(cup["seasons"]) == len(competitions()["sma"]["seasons"])
    s = next(x for x in cup["seasons"] if x["season"] == "2017-18")
    bad = c.post("/api/run", json={"mode": "domestic", "season": "2017-18", "captain": "Nowhere"})
    assert bad.status_code == 400
    assert c.post("/api/run", json={"mode": "domestic", "season": "2017-18", "seed": "4"}).status_code == 200
    for _ in range(240):
        st = c.get("/api/status").get_json()
        if st["status"] != "running":
            break
        time.sleep(0.5)
    assert st["status"] == "done" and st["done"] == s["matches"]
    r = c.get("/api/results").get_json()
    assert r["mode"] == "domestic" and r["competition"] == "sma" and r["domestic"]["season"] == "2017-18"
    assert list(r["super_league"]) == ["Super League A", "Super League B"]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
