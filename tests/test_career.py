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

from engine.auction import OVERSEAS_MAX, PURSE, SQUAD_MAX  # noqa: E402
from engine.career import Career  # noqa: E402
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


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
