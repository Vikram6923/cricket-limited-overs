"""Auction game (engine/auction.py): squads keep the rules whatever the user answers; seeds reproduce; the squads play."""
from __future__ import annotations

import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.auction import (FEE_CAP, OVERSEAS_MAX, PURSE, RETAIN_MAX, SQUAD_MAX, Auction,  # noqa: E402
                            season_pool, years_pool)
from engine.tournament import play_tournament  # noqa: E402


def check(a: Auction) -> None:
    assert a.done and a.question is None and not a.questions
    seen = set()
    for t in a.teams:
        sq = a.squad[t]
        assert a.squad_min <= len(sq) <= SQUAD_MAX, (t, len(sq))
        assert sum(a.lots[i].overseas for i in sq) <= OVERSEAS_MAX
        assert a.kind == "mini" or len(a.retained[t]) <= RETAIN_MAX
        assert a.purse[t] >= 0 and a.purse[t] == PURSE - sum(a.lots[i].price for i in sq)
        assert not seen & set(sq)
        seen |= set(sq)
        for i in sq:
            assert a.lots[i].buyer == t and a.lots[i].status in ("sold", "retained")


def random_answer(a: Auction, u: str, q: dict, rng: random.Random) -> dict:
    k = q["kind"]
    if k == "retain":
        ids = [c["id"] for c in q["candidates"] if rng.random() < 0.4]
        return {"ids": q["suggested"] if a.retain_error(u, ids) else ids}
    if k == "bid":
        r = rng.random()
        if r < 0.01:
            return {"skip": "set"}
        if r < 0.05 and q["cap"] >= q["next"]:
            return {"max": rng.randint(q["next"], q["cap"])}
        return {"bid": r < 0.6 and q["next"] <= q["cap"]}
    if k == "release":
        ids = [c["id"] for c in q["squad"] if rng.random() < 0.4]
        return {"ids": q["suggested"] if a.release_error(u, ids) else ids}
    if k == "nominate":
        return {"ids": [c["id"] for c in q["players"] if rng.random() < 0.3]}
    if k == "set":
        return {"self": rng.random() < 0.1}
    if k == "rtm_raise":
        return {"amount": rng.randint(q["price"], q["cap"])}
    return {"yes": rng.random() < 0.5}


def random_user(a: Auction, rng: random.Random) -> set:
    kinds = set()
    while a.question:
        q = a.question
        kinds.add(q["kind"])
        a.act(random_answer(a, a.user, q, rng))
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
    st = a.state()                                      # what the room shows: who is still in, teams' open places
    assert st["lot"]["log"] and all(me in b["in"] or b["team"] != me for b in st["lot"]["log"])
    assert all(b["team"] in b["in"] for b in st["lot"]["log"]) and set(st["needs"]) == set(a.teams)
    a.auto("ask")                                       # back to being asked: nothing moves
    assert a.question["kind"] == "bid" and a.user_auto is None
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


def test_mini_auction():
    """Kept squads at their contracts (given, or estimated), at most 25 and 8 overseas; no RTM, no marquee set;
    overseas buys above the fee cap are paid the cap."""
    pool = season_pool("ipl", "2026")
    pool["kept"] = {t: {pid: None for pid in ids} for t, ids in pool["prev"].items() if t in pool["teams"]}
    a = Auction(pool, prev={}, seed=1)
    check(a)
    assert a.kind == "mini" and not any(a.rtm.values()) and not any("Marquee" in n for n, _ in a.sets)
    assert not any(s["how"] == "rtm" for s in a.sales)
    for t in a.teams:
        kept = a.retained[t]
        assert kept and len(kept) <= SQUAD_MAX and sum(a.lots[i].overseas for i in kept) <= OVERSEAS_MAX
        assert all(a.lots[i].price == a.lots[i].contract for i in kept)
    for x in a.lots.values():
        assert (x.fee == FEE_CAP) == (x.status == "sold" and x.overseas and x.price > FEE_CAP)
    # the user's releases, with contracts given: a squad of 26 must be cut to 25
    me = a.teams[0]
    ids = [x.id for x in pool["lots"]][:26]
    pool = season_pool("ipl", "2026")
    pool["kept"] = {me: {pid: 30 for pid in ids}}
    b = Auction(pool, user=me, prev={}, seed=2)
    assert b.question["kind"] == "release" and b.release_error(me, []) is not None
    assert len(b.suggest_release(me)) >= 1
    random_user(b, random.Random(2))
    check(b)


def test_two_users():
    """Two people in one auction: asked at once, the first answer counts (a late answer to an old price is
    refused), each sees only their own question / wishlist / advice, skips are per person; squads keep the rules."""
    pool = season_pool("ipl", "2025")
    me, you = pool["teams"][0], pool["teams"][1]
    a = Auction(pool, users=[me, you], seed=3)
    assert a.user is None and a.question is None
    assert set(a.questions) == {me, you} and all(q["kind"] == "retain" for q in a.questions.values())
    a.act({"ids": []}, user=me)                         # the retentions wait for both
    assert set(a.questions) == {you} and a.state(me)["question"] is None and a.state(me)["waiting"] == [you]
    keep = [c["id"] for c in a.questions[you]["candidates"]][:2]
    assert not a.retain_error(you, keep)
    a.act({"ids": keep}, user=you)
    assert a.phase == "auction" and a.retained[you] and not a.retained[me]
    # a lot both are asked about: the first paddle up leads, the other is asked at the next price
    while set(a.questions) != {me, you} or a.questions[me]["kind"] != "bid":
        u = next(iter(a.questions))
        a.act({"bid": False} if a.questions[u]["kind"] == "bid" else random_answer(a, u, a.questions[u], random.Random(0)), user=u)
    q_me, q_you = a.questions[me], a.questions[you]
    assert q_me["next"] == q_you["next"] and q_me["player"]["id"] == q_you["player"]["id"]
    a.act({"bid": True, "seq": q_you["seq"]}, user=you)
    assert a.lot["leader"] == you and you not in a.questions
    try:
        a.act({"bid": True, "seq": q_me["seq"]}, user=me)     # pressed at the old price: too late
        raise AssertionError("a stale bid was accepted")
    except ValueError as e:
        assert "Too late" in str(e)
    assert a.questions[me]["next"] > q_me["next"]
    a.act({"bid": True, "seq": a.questions[me]["seq"]}, user=me)
    assert a.lot["leader"] == me
    # what each sees
    a.set_wish(a.lot["id"], 5000, user=you)
    s_me, s_you = a.state(me), a.state(you)
    assert s_me["user"] == me and not s_me["wish"] and s_you["wish"] and s_you["planner"]["xi"]
    assert a.to_you(me) and a.to_you(you)
    # skips are per person: one hands the rest of the auction to the computer, the other keeps bidding
    a.auto("all", user=me)
    rng, kinds = random.Random(3), set()
    while a.questions:
        assert me not in a.questions or a.questions[me]["kind"] in ("rtm_use", "rtm_match", "rtm_raise")
        u = rng.choice(sorted(a.questions))
        kinds.add(a.questions[u]["kind"])
        a.act(random_answer(a, u, a.questions[u], rng), user=u)
    check(a)
    assert "bid" in kinds and a.summary()["users"] == [me, you]


def test_two_users_random():
    """Both people answering at random, in random order, in season and years pools; a seeded run reproduces."""
    for seed in range(3):
        runs = []
        for _ in range(2):
            if seed == 2:
                pool = years_pool("t20", 2018, 2022, ["A", "B", "C", "D"], home="India")
                a = Auction(pool, users=["A", "B"], prev={"A": [x.id for x in pool["lots"][:10]],
                                                         "B": [x.id for x in pool["lots"][10:20]]}, seed=seed)
            else:
                pool = season_pool("ipl", "2024")
                a = Auction(pool, users=pool["teams"][seed:seed + 2], seed=seed)
            rng, kinds, both = random.Random(seed), set(), 0
            while a.questions:
                both += len(a.questions) == 2
                u = rng.choice(sorted(a.questions))
                kinds.add(a.questions[u]["kind"])
                a.act(random_answer(a, u, a.questions[u], rng), user=u)
            check(a)
            assert {"retain", "bid"} <= kinds and both, (kinds, both)
            runs.append((a.squad, a.purse))
        assert runs[0] == runs[1]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok ", name)
