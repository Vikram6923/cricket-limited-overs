"""Career mode (engine/career.py): seasons, ageing, newcomers, mini and mega auctions, saving and loading.

    python tests/test_career.py
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.auction import OVERSEAS_MAX, PURSE, SQUAD_MAX, Auction, season_pool  # noqa: E402
from engine.belief import ratios  # noqa: E402
from engine.career import Career, profile  # noqa: E402
from engine.tournament import play_tournament  # noqa: E402


def check_squads(c: Career) -> None:
    seen = set()
    for t in c.franchises:
        sq = c.squads[t]
        assert len(sq) <= SQUAD_MAX and len(sq) >= 11, (t, len(sq))
        if c.league == "ipl":     # smaller leagues' real squads can have more (the auction then lifts the limit)
            assert sum(c.players[p]["overseas"] for p in sq) <= OVERSEAS_MAX
        assert sum(sq.values()) <= PURSE, (t, sum(sq.values()))
        assert not seen & set(sq)
        assert all(c.players[p]["retired"] is None for p in sq)
        seen |= set(sq)
    assert not seen & set(c.free)


def user_auction(c: Career, rng: random.Random) -> str:
    """The user's auction with random answers (as the web page would send them)."""
    a = c.auction()
    kind = a.kind
    while not a.done:
        q = a.question
        try:
            if q["kind"] == "release":
                a.act({"ids": [x["id"] for x in q["squad"] if rng.random() < 0.3]})
            elif q["kind"] == "retain":
                a.act({"ids": q["suggested"]})
            elif q["kind"] == "bid":
                a.act({"bid": rng.random() < 0.3})
            elif q["kind"] == "rtm_raise":
                a.act({"amount": q["price"]})
            else:
                a.act({"yes": rng.random() < 0.5})
        except ValueError:
            a.act({"ids": q.get("suggested", [])} if q["kind"] in ("retain", "release") else {"bid": False})
    for t in a.teams:
        assert a.purse[t] >= 0
    c.apply_auction(a)
    return kind


def test_career_seasons():
    rng = random.Random(3)
    c = Career("mlc", "2025", user=None, mega_every=2, seed=11)
    c.user = c.franchises[0]
    check_squads(c)
    ages = {p: c.age(p) for p in c.squads[c.user]}
    kinds = []
    for season in range(3):
        res = play_tournament(c.specs(), **c.play_args())
        h = c.record(res)
        assert h["champion"] in c.franchises and h["user_pos"]
        c.advance()
        assert c.phase == "auction"
        kinds.append(user_auction(c, rng))
        assert c.phase == "season"
        check_squads(c)
        c = Career.from_json(json.loads(json.dumps(c.to_json())))          # through JSON, as the server does
    assert kinds == ["mini", "mega", "mini"], kinds
    assert [h["season"] for h in c.history] == ["2025", "2026", "2027"]
    assert any(r["made_up"] for r in c.players.values())                     # past the real seasons
    for p, a in ages.items():
        assert c.players[p]["retired"] is not None or c.age(p) == a + 3
    lead = c.leaders()
    assert lead["runs"][0]["runs"] > 0 and lead["wkts"][0]["wkts"] > 0
    st = c.state()
    assert st["season"] == "2028" and sum(st["titles"].values()) == 3


def test_ageing_moves_ratings():
    c = Career("mlc", "2025", seed=1)
    pid = next(p for t in c.franchises for p in c.squads[t] if c.age(p) >= 36)
    now = c.engine_player(pid).bat["death"]["runs"]
    c.year += 4
    later = c.engine_player(pid).bat["death"]["runs"]
    assert later < now, (now, later)


SURYAVANSHI = "470f446b"        # no T20 cricket in the data before 2025, then a star


def test_belief_knows_only_the_past():
    """Teams judge a player on his record before the season, not on seasons he has yet to play."""
    born, ref = profile(SURYAVANSHI, 2025)
    before = ratios(SURYAVANSHI, 2025, born, ref, "ipl")["bat"]
    after = ratios(SURYAVANSHI, 2027, born, ref, "ipl")["bat"]
    assert before["balls"] == 0 and before["runs"] < 0.8, before          # an unknown: near the debutant prior
    assert after["balls"] > 500 and abs(after["runs"] - 1) < 0.05, after   # his whole record seen: his rating
    a = Auction(season_pool("ipl", "2025", "hindsight"), start=False)
    x = a.lots[SURYAVANSHI]
    assert x.est <= 300, x.est                                              # real price Rs 1.1 crore
    assert x.ref["bat"]["sr"] > 180                                         # hindsight: shown his real numbers


def test_career_belief_and_form():
    c = Career("mlc", "2025", seed=4)
    pid = next(p for t in c.franchises for p in c.squads[t])
    assert c.seen_player(pid).bat != c.engine_player(pid).bat
    res = play_tournament(c.specs(), **c.play_args())
    c.record(res)
    c.advance()
    assert all(not r["form"] for r in c.players.values())                   # no form known at the auction
    c.auto_auction()
    assert any(r["form"] for r in c.players.values())                       # drawn once the auction is over
    for _ in range(2):                                                      # past the real seasons: made-up players
        c.record(play_tournament(c.specs(), **c.play_args()))
        c.advance()
        c.auto_auction()
    made = [p for p, r in c.players.items() if r["made_up"] and r["joined"] == c.year]
    assert made
    pid = made[0]
    r = c.players[pid]
    shift = r["born"] - profile(r["src"], r["joined"])[0]
    # before his first season: the real player's record before that player's own debut, moved to his debut year
    real = ratios(r["src"], r["joined"] - shift, profile(r["src"], 0)[0], r["ref"], c.league)
    seen = c.seen_player(pid).ref
    for side in real:
        assert seen[side]["seen_balls"] == real[side]["balls"], (side, seen[side], real[side])
    c.record(play_tournament(c.specs(), **c.play_args()))                   # then what the career shows of him
    c.advance()
    obs = c.players[pid]["obs"]
    seen = c.seen_player(pid).ref
    for side in real:
        assert seen[side]["seen_balls"] == real[side]["balls"] + obs[side][0] >= real[side]["balls"] + 120


def test_career_learns_from_its_seasons():
    """From the career's first season the teams learn from what happens in it, not from the real seasons."""
    c = Career("ipl", "2024", seed=5)
    c.record(play_tournament(c.specs(), **c.play_args()))
    c.advance()                                                             # 2025: he arrives with no record
    assert c.seen_player(SURYAVANSHI).ref["bat"]["seen_balls"] == 0
    assert all(c.players[p]["obs"] for p in c.active() if p != SURYAVANSHI and c.players[p]["joined"] < 2025)
    c.auto_auction()
    c.record(play_tournament(c.specs(), **c.play_args()))
    c.advance()                                                             # 2026: the career's 2025, not the real one
    obs = c.players[SURYAVANSHI]["obs"]["bat"]
    assert c.seen_player(SURYAVANSHI).ref["bat"]["seen_balls"] == obs[0] >= 120
    # a player who flops in the career is believed worse, whatever his real record says
    pid = max(c.squads[c.franchises[0]], key=lambda p: c.seen_player(p).ref.get("bat", {}).get("seen_balls", 0))
    before = c.seen_player(pid).bat["middle"]["runs"]
    o = list(c.players[pid]["obs"]["bat"])
    o[0], o[1], o[2], o[-1] = o[0] + 3000, o[1] + 1800, o[2] + 4000, o[-1] + 9000   # 3000 balls at 45% of par
    c.players[pid]["obs"]["bat"] = o
    assert c.seen_player(pid).bat["middle"]["runs"] < 0.85 * before
    # a career saved before observations: real record until the first observed season
    del c.players[pid]["obs"]
    real = c.seen_player(pid).ref["bat"]["seen_balls"]
    c._observe({"matches": []})
    assert c.players[pid]["obs_from"] == c.year and c.seen_player(pid).ref["bat"]["seen_balls"] > real


def test_knowledge_what_you_see():
    """Realistic: the person is shown what the teams know; hindsight: the real numbers. Matches are the same."""
    real = Auction(season_pool("ipl", "2025", "hindsight"), start=False).lots[SURYAVANSHI].row()
    seen = Auction(season_pool("ipl", "2025", "realistic"), start=False).lots[SURYAVANSHI].row()
    assert seen["est"] == real["est"] and seen["seen"] == real["seen"] == {"bat": 0}
    assert seen["bat_sr"] < 150 < 180 < real["bat_sr"]
    cards = {}
    for know in ("realistic", "hindsight"):
        c = Career("mlc", "2025", seed=2, knowledge=know)
        rows = {r["id"]: r for t in c.franchises for r in c.squad_rows(t)}
        assert all(r["seen"] is None or set(r["seen"]) <= {"bat", "bowl"} for r in rows.values())
        cards[know] = (rows, play_tournament(c.specs(), **c.play_args())["fixtures"])
    (r1, f1), (r2, f2) = cards["realistic"], cards["hindsight"]
    assert f1 == f2                                                          # the same matches either way
    assert any(r1[i]["bat_sr"] != r2[i]["bat_sr"] for i in r1)
    d = c.to_json()
    del d["knowledge"]
    assert Career.from_json(d).knowledge == "hindsight"                     # saved before the setting
    try:
        Career("mlc", "2025", knowledge="psychic")
        raise AssertionError("bad knowledge accepted")
    except ValueError:
        pass


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
