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
        elif k == "nominate":
            a.act({"ids": [c["id"] for c in q["players"] if rng.random() < 0.3]})
        elif k == "set":
            a.act({"self": rng.random() < 0.1})
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


def test_wishlist_and_report():
    """Bidding by the wishlist buys only listed players (up to their top bids) before the fill-up; the planner
    and report card are filled in."""
    pool = season_pool("ipl", "2025")
    me = pool["teams"][3]
    a = Auction(pool, user=me, seed=5)
    assert a.question["kind"] == "retain" and a.to_you() and a.planner(me)
    a.act({"ids": []})                                  # no retentions
    tv = a.to_you()
    want = sorted((x for x in a.lots.values() if x.status == "pool"), key=lambda x: -tv[x.id])[:8]
    for x in want:
        a.set_wish(x.id, max(x.base, tv[x.id]))
    a.auto("wish")
    kinds = set()
    while a.question:
        kinds.add(a.question["kind"])
        assert a.question["kind"] in ("set", "nominate"), a.question["kind"]
        assert a.planner(me)["xi"]
        a.act({"go": True} if a.question["kind"] == "set" else {"ids": []})
    check(a)
    assert "set" in kinds
    for i in a.squad[me]:
        x = a.lots[i]
        assert x.id in a.wish or x.price == 30, (x.name, x.price)
        if x.id in a.wish:
            assert x.price <= a.wish[x.id]["max"]
    r = a.report()
    assert len(r["teams"]) == len(a.teams) and r["bargains"]
    if r["scale"] is not None:                          # a predicted table only where the fit found a link
        assert abs(sum(t["wins"] for t in r["teams"]) - len(a.teams) * (len(a.teams) - 1)) < 0.5
    else:
        assert all(t["wins"] is None for t in r["teams"])


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
