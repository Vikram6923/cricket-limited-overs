"""Auction game (engine/auction.py): squads keep the rules whatever the user answers; seeds reproduce; the squads play."""
from __future__ import annotations

import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.auction import (OVERSEAS_MAX, PURSE, RETAIN_MAX, SQUAD_MAX, Auction, season_pool,  # noqa: E402
                            years_pool)
from engine.tournament import play_tournament  # noqa: E402


def check(a: Auction) -> None:
    assert a.done and a.question is None
    seen = set()
    for t in a.teams:
        sq = a.squad[t]
        assert a.squad_min <= len(sq) <= SQUAD_MAX, (t, len(sq))
        assert sum(a.lots[i].overseas for i in sq) <= OVERSEAS_MAX
        assert len(a.retained[t]) <= RETAIN_MAX
        assert a.purse[t] >= 0 and a.purse[t] == PURSE - sum(a.lots[i].price for i in sq)
        assert not seen & set(sq)
        seen |= set(sq)
        for i in sq:
            assert a.lots[i].buyer == t and a.lots[i].status in ("sold", "retained")


def random_user(a: Auction, rng: random.Random) -> set:
    kinds = set()
    while a.question:
        q = a.question
        kinds.add(q["kind"])
        k = q["kind"]
        if k == "retain":
            ids = [c["id"] for c in q["candidates"] if rng.random() < 0.4]
            if a.retain_error(a.user, ids):
                ids = q["suggested"]
            a.act({"ids": ids})
        elif k == "bid":
            r = rng.random()
            if r < 0.01:
                a.act({"skip": "set"})
            elif r < 0.05 and q["cap"] >= q["next"]:
                a.act({"max": rng.randint(q["next"], q["cap"])})
            else:
                a.act({"bid": r < 0.6 and q["next"] <= q["cap"]})
        elif k == "rtm_raise":
            a.act({"amount": rng.randint(q["price"], q["cap"])})
        else:
            a.act({"yes": rng.random() < 0.5})
    return kinds


def test_computer_auction():
    pool = season_pool("ipl", "2025")
    a = Auction(pool, seed=4)
    check(a)
    assert any(a.retained.values()) and any(s["how"] == "rtm" for s in a.sales)
    b = Auction(season_pool("ipl", "2025"), seed=4)
    assert a.squad == b.squad and a.purse == b.purse


def test_random_user():
    kinds = set()
    for seed in range(4):
        pool = season_pool("ipl", "2024")
        a = Auction(pool, user=pool["teams"][seed], seed=seed)
        kinds |= random_user(a, random.Random(seed))
        check(a)
    assert {"retain", "bid"} <= kinds, kinds


def test_years_pool_and_league():
    teams = ["A", "B", "C", "D"]
    pool = years_pool("t20", 2018, 2022, teams, home="India")
    a = Auction(pool, user="B", prev={"B": [x.id for x in pool["lots"][:10]]}, seed=1)
    random_user(a, random.Random(1))
    check(a)
    res = play_tournament(a.team_specs(), fmt="t20", comp="t20i_full", year=2022, rounds=1, knockout="final", seed=1)
    assert len(res["matches"]) == 7
    a = Auction(years_pool("odi", 1995, 2005, teams), seed=2)       # no overseas limits
    check(a)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok ", name)
