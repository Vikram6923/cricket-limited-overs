"""Manual captaincy (engine/control.py): random answers to every question keep the laws; skips and auto work."""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import simulate_match  # noqa: E402
from engine.control import Controller  # noqa: E402
from engine.tournament import play_tournament  # noqa: E402
from test_engine import check_card  # noqa: E402


def ipl_teams(season: str = "2024", n: int = 2) -> list[dict]:
    s = json.loads((ROOT / "data" / "league_seasons.json").read_text(encoding="utf-8"))["ipl"]
    teams = next(x for x in s["seasons"] if x["season"] == season)["teams"][:n]
    return [{"name": t["name"], "squad": t["players"], "overseas": t["overseas"], "max_overseas": t["max_overseas"]}
            for t in teams]


class RandomCaptain(Controller):
    """Answers every question at random (valid or not), and logs the kinds asked."""

    def __init__(self, team, seed):
        super().__init__(team)
        self.rng, self.asked = random.Random(seed), []

    def decide(self, q):
        self.asked.append(q["kind"])
        assert "state" in q and "default" in q or q["kind"] == "result"
        r = self.rng
        k = q["kind"]
        if k == "toss":
            return r.choice(q["options"])
        if k == "xi":
            opts = list(q["options"])
            r.shuffle(opts)
            xi, os_ = [], 0
            for p in opts:
                if len(xi) < 11 and (q["max_overseas"] is None or not p["overseas"] or os_ < q["max_overseas"]):
                    xi.append(p["id"])
                    os_ += p["overseas"]
            rest = [p["id"] for p in opts if p["id"] not in xi]
            return {"xi": xi, "keeper": r.choice(xi), "subs": rest[:q["n_subs"]]}
        imp = q.get("impact")
        sub = None
        if imp and imp["ins"] and imp["outs"] and r.random() < 0.3:
            sub = {"out": r.choice(imp["outs"])["id"], "in": r.choice(imp["ins"])["id"]}
        if k == "bowler":
            return {"bowler": r.choice(q["options"])["id"], "impact": sub}
        if k == "batter":
            return {"batter": r.choice(q["options"])["id"], "impact": sub}
        if k == "impact":
            return sub or {}
        return None


def test_random_captains_keep_the_laws():
    a, b = ipl_teams()
    kinds = set()
    for seed in range(60):
        ctl = {a["name"]: RandomCaptain(a["name"], seed), b["name"]: RandomCaptain(b["name"], seed + 1000)}
        c = simulate_match(a, b, fmt="t20", comp="ipl", year=2024, seed=seed, control=ctl)
        check_card(c)
        for t, xi in c["xi"].items():
            assert len(xi) == 11 and len({p["id"] for p in xi}) == 11
        for x in ctl.values():
            kinds |= set(x.asked)
    assert {"toss", "xi", "bowler", "batter", "result"} <= kinds, kinds


def test_computer_answers_match_auto_play():
    """A controller that always takes the computer's choice plays like no controller (bar Impact timing)."""
    a, b = ipl_teams("2022")                    # no Impact Player: identical
    for seed in range(20):
        ctl = {a["name"]: Controller(a["name"])}
        c1 = simulate_match(a, b, fmt="t20", comp="ipl", year=2022, seed=seed, control=ctl)
        c2 = simulate_match(a, b, fmt="t20", comp="ipl", year=2022, seed=seed)
        assert [i["runs"] for i in c1["innings"]] == [i["runs"] for i in c2["innings"]]


def test_skip_and_auto():
    a, b = ipl_teams()

    class Skipper(Controller):
        def decide(self, q):
            self.n = getattr(self, "n", 0) + 1
            if q["kind"] == "bowler":
                self.skip = {"scope": "match", "match": q["match_key"], "innings": q["innings"]}
            return None
    s = Skipper(a["name"], {"bowler", "batter", "result"})
    simulate_match(a, b, fmt="t20", comp="ipl", year=2024, seed=3, control={a["name"]: s}, toss="a", decision="bowl")
    assert s.n == 2                              # the first bowler question, the rest skipped, then the result


def test_tournament_with_a_captain():
    teams = ipl_teams(n=4)
    ctl = RandomCaptain(teams[0]["name"], 5)
    res = play_tournament(teams, fmt="t20", comp="ipl", year=2024, rounds=1, knockout="final", seed=2,
                          control={teams[0]["name"]: ctl})
    assert ctl.asked.count("result") == sum(1 for c in res["matches"] if teams[0]["name"] in c["teams"])


def test_series_with_a_captain():
    """Other modes: a series between a fixed XI (exactly 11 players) and a historical squad."""
    from engine.history import historical_team
    from engine.tournament import play_series
    preset = json.loads((ROOT / "data" / "teams_default.json").read_text(encoding="utf-8"))[0]
    xi = {"name": preset["name"], "players": [x["id"] for x in preset["players"]][:11]}
    hist = historical_team("t20", "Australia", 2007, 2012)
    for side in (xi["name"], hist["name"]):
        ctl = RandomCaptain(side, 9)
        res = play_series(xi, hist, n=3, fmt="t20", comp="t20i_full", year=2024, seed=4, control={side: ctl})
        for c in res["matches"]:
            check_card(c)
        assert ctl.asked.count("result") == 3 and "bowler" in ctl.asked


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok ", name)
