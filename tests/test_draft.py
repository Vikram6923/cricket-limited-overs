"""Tests for the fantasy draft (engine/draft.py).

    python tests/test_draft.py          (no pytest needed; also works under pytest)
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.draft import NEEDS, Draft  # noqa: E402
from engine.history import FULL_MEMBERS  # noqa: E402
from engine.tournament import play_tournament  # noqa: E402

TEAMS = ["London", "Melbourne", "Mumbai", "Cape Town"]


def test_snake_order_and_complete_squads():
    d = Draft("t20", 2019, 2024, TEAMS, seed=3)
    first = d.order[:4]
    assert d.order[4:8] == first[::-1]                     # snake
    d.run_cpu()
    assert d.done and all(len(v) == 15 for v in d.picks.values())
    ids = [p for v in d.picks.values() for p in v]
    assert len(ids) == len(set(ids))                        # nobody picked twice
    for t in TEAMS:                                         # computer squads meet the minimum make-up
        c = d.counts(t)
        assert all(c[r] >= n for r, n in NEEDS.items()), (t, c)


def test_user_turns_and_errors():
    d = Draft("odi", 2005, 2015, TEAMS, user="Mumbai", seed=4)
    d.run_cpu()
    assert d.current() == "Mumbai"
    sug = d.state()["suggestions"]
    assert sug and len(sug) == len(set(sug))
    d.pick(sug[0])
    try:
        d.pick(sug[0])
        assert False, "picking out of turn / twice must fail"
    except ValueError:
        pass
    d.run_cpu()
    assert d.current() in ("Mumbai", None)


def test_pool_sources():
    full = Draft("t20", 2021, 2024, TEAMS, seed=1)
    assert all(p.nation in FULL_MEMBERS for p in full.pool)
    lg = Draft("t20", 2021, 2024, TEAMS, seed=1, source="leagues")
    assert len(lg.pool) > len(full.pool)
    assert any(p.name == "Rashid Khan" for p in lg.pool)     # Afghanistan only via leagues (Cricsheet gap)


def test_reproducible_and_playable():
    a, b = Draft("t20", 2016, 2020, TEAMS, seed=9), Draft("t20", 2016, 2020, TEAMS, seed=9)
    a.run_cpu()
    b.run_cpu()
    assert a.picks == b.picks
    res = play_tournament(a.team_specs(), fmt="t20", comp="t20i_full", year=2020, knockout="final", seed=2)
    assert res["winner"] in TEAMS


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
