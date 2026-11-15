"""Tests for the Test match data and ratings (Phase 1 of docs/test_match_plan.md).

    python tests/test_test_data.py          (no pytest needed; also works under pytest)

They read the committed files only (data/ratings_test.json, data/raw_stats/test_careers.json,
data/engine/basics_test.json), not the raw Cricsheet zip or the old Test simulator's folder.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import data  # noqa: E402
from engine.data import FORMATS, METRICS, baseline, basics, phase_names, player, ratings  # noqa: E402

CAREERS = json.loads((ROOT / "data" / "raw_stats" / "test_careers.json").read_text(encoding="utf-8"))


def pid(name: str, nation: str | None = None) -> str:
    hits = [p for p, r in ratings("test")["players"].items()
            if r["name"] == name and (nation is None or r.get("team") == nation)]
    assert len(hits) == 1, f"{name} ({nation}): {len(hits)} players"
    return hits[0]


def avg(p) -> float:
    return p.ref["bat"]["avg"]


def bowl_avg(p) -> float:
    return p.ref["bowl"]["avg"]


def test_format_entry():
    f = FORMATS["test"]
    assert f["overs"] is None and f["quota"] is None and f["days"] == 5 and f["day_overs"] == 90
    assert phase_names("test") == ("all",)
    assert data.phase_of(0, "test") == data.phase_of(400, "test") == "all"
    assert data.phases_for("test", 90) == f["phases"]
    # the limited-overs formats are as they were
    assert phase_names("odi") == phase_names("t20") == ("powerplay", "middle", "death")
    assert FORMATS["odi"]["overs"] == 50 and FORMATS["t20"]["quota"] == 4


def test_three_kinds_of_player_load():
    covered = player("test", pid("JE Root"))                 # ball-by-ball only
    assert covered.rated_bat and covered.bat_conf > 0.9 and covered.caps > 150 and covered.usual_slot in (3, 4)
    old = player("test", pid("DG Bradman"))                  # career totals only
    assert old.rated_bat and old.team == "Australia" and old.caps == 52 and set(old.bat) == {"all"}
    both = ratings("test")["players"][pid("SR Tendulkar")]   # both parts
    assert both["source"] == "ball_by_ball+career_totals" and both["pre"]["tests"] > 100
    unknown = player("test", "no-such-id", name="A Nother", team="England")
    assert not unknown.rated_bat and not unknown.rated_bowl and unknown.name == "A Nother"
    for p in (covered, old, unknown):
        for side in (p.bat, p.bowl):
            assert set(side) == {"all"} and set(side["all"]) == set(METRICS)
            assert all(v > 0 for v in side["all"].values())


def test_known_players_rate_sensibly():
    """'ref' numbers are what the player would do in the reference era (the last five years), so they sit a
    little below career averages from higher-scoring times. Wide bands: this guards against breakage, not taste."""
    P = {n: player("test", pid(n, nat)) for n, nat in (
        ("JE Root", None), ("SPD Smith", None), ("KS Williamson", None), ("V Kohli", None), ("DG Bradman", None),
        ("JB Hobbs", None), ("GS Sobers", None), ("JM Anderson", None), ("NM Lyon", None), ("R Ashwin", None),
        ("K Rabada", None), ("JJ Bumrah", None), ("MD Marshall", None), ("SF Barnes", None), ("SK Warne", None),
        ("M Muralitharan", None), ("GD McGrath", None), ("CS Martin", None))}
    for n in ("JE Root", "SPD Smith", "KS Williamson", "V Kohli", "JB Hobbs", "GS Sobers"):
        assert 38 <= avg(P[n]) <= 62, (n, avg(P[n]))
    assert avg(P["DG Bradman"]) > 65 and avg(P["DG Bradman"]) == max(avg(p) for p in P.values())
    for n in ("JM Anderson", "NM Lyon", "JJ Bumrah", "GD McGrath", "CS Martin"):
        assert avg(P[n]) < 16, (n, avg(P[n]))
    assert avg(P["CS Martin"]) == min(avg(p) for p in P.values())
    for n in ("JM Anderson", "R Ashwin", "K Rabada", "JJ Bumrah", "MD Marshall", "SF Barnes", "SK Warne",
              "M Muralitharan", "GD McGrath"):
        assert 17 <= bowl_avg(P[n]) <= 27, (n, bowl_avg(P[n]))
    assert bowl_avg(P["NM Lyon"]) > bowl_avg(P["R Ashwin"])
    assert bowl_avg(P["JE Root"]) > 35 and bowl_avg(P["V Kohli"]) > 30      # part-timers
    assert P["SK Warne"].bowl_type == "spin" and P["MD Marshall"].bowl_type == "pace"
    assert P["SF Barnes"].bowl_overs_per_match > 30 and P["DG Bradman"].bowl_overs_per_match < 2


def test_year_ranges():
    t = pid("SR Tendulkar")
    early = player("test", t, years=(1996, 2000))     # before his covered Tests: the career-totals part
    late = player("test", t, years=(2008, 2011))      # inside Cricsheet: the usual year-range rating
    only = player("test", t, years=(2008, 2011), years_mode="only")
    career = player("test", t)
    assert early.bat["all"] != career.bat["all"] and late.bat["all"] != career.bat["all"]
    assert 40 <= avg(early) <= 60 and 40 <= avg(late) <= 60 and 40 <= avg(only) <= 65
    assert late.caps < career.caps                    # matches up to 2011 only
    b = pid("DG Bradman")
    assert player("test", b, years=(1930, 1938)).bat == player("test", b).bat   # totals only: no year split


def test_keepers_and_openers():
    for n in ("MS Dhoni", "AC Gilchrist", "APE Knott", "RW Marsh"):
        assert player("test", pid(n)).keeper, n
    for n in ("JE Root", "DG Bradman", "SK Warne"):
        assert not player("test", pid(n)).keeper, n
    assert player("test", pid("JB Hobbs")).opener_share > 0.8      # from the career rows
    assert player("test", pid("AN Cook")).opener_share > 0.8       # from ball-by-ball positions
    assert player("test", pid("DG Bradman")).opener_share < 0.1


def test_career_rows():
    assert 3200 <= len(CAREERS) <= 3600
    linked = sum(1 for r in CAREERS.values() if not r["id"].startswith("tc_"))
    assert linked / len(CAREERS) > 0.95
    assert all(k == r["id"] for k, r in CAREERS.items())
    by = {}
    for r in CAREERS.values():
        by.setdefault(r["name"], []).append(r)
    # two different men with one name stay two players, each in his own time
    jones = sorted(by["SP Jones"], key=lambda r: r["first"])
    assert [(r["nation"], r["first"]) for r in jones] == [("Australia", 1882), ("England", 2002)]
    assert len({r["id"] for r in by["Rashid Khan"]}) == 2
    # one man who played for two countries is one player, counted once
    k = by["AH Kardar"]
    assert len(k) == 1 and k[0]["tests"] == 26 and set(k[0]["nations"]) == {"India", "Pakistan"}
    assert [(r["tests"], r["runs"], r["outs"]) for r in by["DG Bradman"]] == [(52, 6996, 70)]
    t = by["SR Tendulkar"][0]
    assert t["tests"] == 200 and t["runs"] == 15921 and t["pre"]["tests"] + 82 == 200 and t["pre"]["last"] <= 2006
    # the pre-coverage part never exceeds the career
    for r in CAREERS.values():
        pre = r["pre"]
        if pre:
            assert pre["tests"] <= r["tests"] and r["first"] <= pre["first"] <= pre["last"] <= r["last"], r["name"]
            assert (pre["runs"] or 0) <= (r["runs"] or 0) and (pre["wkts"] or 0) <= (r["wkts"] or 0), r["name"]


def test_baselines_by_era():
    years = sorted(int(y) for y in ratings("test")["baselines"]["test_full"])
    assert years[0] == 1877 and years[-1] >= 2025 and years == list(range(years[0], years[-1] + 1))
    rpo, average = {}, {}
    for y in (1890, 1935, 1958, 1985, 2010, 2024):
        b = baseline("test", "test_full", y)["all"]
        assert 0 < b["six"] < b["four"] < 1 - b["dot"] < 0.4 and 0.6 < b["dot"] < 0.9, y
        rpo[y], average[y] = 6 * b["runs"], b["runs"] / (b["wkt"] + b["other_out"])
        assert 2.0 <= rpo[y] <= 3.6 and 18 <= average[y] <= 38, (y, rpo[y], average[y])
    assert rpo[1958] < rpo[1985] < rpo[2010]          # the slow 1950s, the quicker modern game
    assert average[1890] < average[1935]              # low-scoring early Tests, the batsman's 1930s


def test_metadata_and_basics():
    m = ratings("test")["meta"]
    assert m["reference_era"]["competition"] == "test_full"
    for metric in METRICS:
        for side in ("bat", "bowl"):
            assert all(0.3 < v < 2.6 for v in m["role_means"][metric][side].values()), (metric, side)
    assert m["role_means"]["wkt"]["bat"]["tail"] > 1.5 > 1.0 > m["role_means"]["wkt"]["bat"]["top"]
    assert m["career_totals"]["new_players"] > 2000 and m["career_totals"]["with_pre_block"] > 200
    b = basics("test")
    assert set(b["run_split"]) == {"all"} and abs(sum(b["run_split"]["all"].values()) - 1) < 1e-3
    for kind in ("pace", "spin"):
        d = b["dismissal"]["all"][kind]
        assert abs(sum(d.values()) - 1) < 1e-3
    assert b["dismissal"]["all"]["spin"]["stumped"] > 10 * b["dismissal"]["all"]["pace"]["stumped"]
    assert b["dismissal"]["all"]["pace"]["caught_keeper"] > b["dismissal"]["all"]["spin"]["caught_keeper"]
    assert pid("MS Dhoni") in b["keepers"]


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    for name, fn in tests:
        fn()
        print(f"ok  {name}")
    print(f"{len(tests)} tests passed")
