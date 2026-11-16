"""Tests for batting with the tail in a Test: the fitted table, the computer's batters farming the strike, and a
person's switch for their own side.

    python tests/test_test_tail.py          (no pytest needed; also works under pytest)
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from engine.test_match import TestMatch  # noqa: E402
from engine.test_situation import TestSituation, tail_role, tail_table  # noqa: E402
from test_test_control import Captain, play, strip  # noqa: E402
from test_test_engine import AUS, IND, check_card, team  # noqa: E402


def test_the_table():
    t = tail_table()
    assert t["tail_from"] == 9 and t["wickets"] == [7, 8, 9] and t["ball_edges"] == [3, 5]
    assert set(t["cells"]) == {"senior", "shielded", "last"}
    i = {m: j for j, m in enumerate(t["metrics"])}
    for role, by in t["cells"].items():
        for wk, rows in by.items():
            assert len(rows) == 3 and all(0.5 < v < 4 for row in rows for v in row), (role, wk)
    early, late, _ = t["cells"]["senior"]["9"]
    assert late[i["dot"]] < early[i["dot"]] and late[i["runs"]] > early[i["runs"]], "the single late in the over"
    assert early[i["wkt"]] > 1.3 and early[i["six"]] > 1.5, "the batter hits out with the last man in"
    assert all(row[i["wkt"]] < 1 for row in t["cells"]["shielded"]["7"]), "a shielded tailender lasts longer"
    assert t["real_strike_share"]["9"] > t["real_strike_share"]["7"] + 0.05
    assert tail_role(3, 10, 8) == "senior" and tail_role(10, 3, 8) == "shielded" and tail_role(10, 11, 9) == "last"
    assert tail_role(3, 10, 6) is None and tail_role(3, 8, 7) is None
    sit = TestSituation()
    m = sit.multipliers(sit.cell(1, 9, 250), 40, "pace", 100, 20)
    out = sit.with_tail(m, "senior", 9, 4)
    assert abs(out["wkt"] / m["wkt"] - late[i["wkt"]]) < 1e-9 and sit.with_tail(m, "senior", 9, 3) is out, "cached"
    assert sit.with_tail(m, None, 9, 4) is m and sit.with_tail(m, "senior", 9, 0) is not out


def strike_share(use_tail: bool, seeds) -> float:
    """The batter's share of the legal balls in last-wicket stands with a tailender."""
    t = tail_table()
    got = [0, 0]
    for seed in seeds:
        m = TestMatch(team("India", IND), team("Australia", AUS), year=2023, seed=seed, use_tail=use_tail)
        real = m.model.delivery

        def delivery(rng, base, sp, bowler, *args, _m=m, _real=real, **kw):
            inn = _m.innings[-1]
            a, b, wk = inn.striker.pos, inn.non_striker.pos, inn.wkts
            o = _real(rng, base, sp, bowler, *args, **kw)
            if o.legal and wk == 9 and (a >= t["tail_from"]) != (b >= t["tail_from"]):
                got[0] += a < t["tail_from"]
                got[1] += 1
            return o

        m.model.delivery = delivery
        check_card(m.play())
    return got[0] / got[1]


def test_the_computers_batters_farm_the_strike():
    seeds = range(40)
    on, off = strike_share(True, seeds), strike_share(False, seeds)
    assert on > off + 0.04 and on > 0.5, (on, off)
    a, b = play(7), play(7)
    assert a == b, "a seed plays the same Test"
    assert any(play(s) != play(s, use_tail=False) for s in (7, 8)), "the table changes the play"


def test_a_persons_switch():
    def answer(farm):
        def fn(q):
            return {"until": "over", **({"farm": farm} if q.get("tail") else {})}      # as the page sends it
        return fn

    seen = changed = 0
    for seed in (1, 2, 3):
        plain = play(seed)
        on = Captain("India", manual={"ball"}, ball=answer(True))
        assert strip(play(seed, {"India": on})) == plain, "farming is what the computer does anyway"
        junk = Captain("India", manual={"ball"}, ball=answer("no"))
        assert strip(play(seed, {"India": junk})) == plain, "anything but true or false is ignored"
        off = Captain("India", manual={"ball"}, ball=answer(False))
        card = play(seed, {"India": off})
        check_card(strip(card))
        changed += strip(card) != plain
        tails = [q for q in off.questions if q["kind"] == "ball" and q.get("tail")]
        seen += len(tails)
        for q in tails:
            assert q["side"] == "bat" and q["state"]["wkts"] >= 7 and set(q["tail"]) == {"on", "senior", "real_share"}
        assert all(not q["tail"]["on"] for q in tails[1:]), "the switch stays where it was put"
        assert tails[0]["tail"]["on"], "on until the person says otherwise"
        for q in off.questions:
            if q["kind"] == "ball" and (q["side"] == "bowl" or q["state"]["wkts"] < 7):
                assert not q.get("tail")
    assert seen > 10 and changed, (seen, changed)


def main() -> None:
    fns = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    for name, fn in fns:
        t = time.time()
        fn()
        print(f"ok   {name}  ({time.time() - t:.1f}s)")
    print(f"{len(fns)} tests passed")


if __name__ == "__main__":
    main()
