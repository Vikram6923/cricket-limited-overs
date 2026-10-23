"""Aggression dials and ball by ball (docs/match_play_design.md): bar 5 is the engine unchanged; the dials move
runs and risk the right way; random dials keep the laws; the pace ("until") pauses where it says."""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import simulate_match  # noqa: E402
from engine.control import Controller  # noqa: E402
from engine.situation import Situation  # noqa: E402
from test_engine import check_card  # noqa: E402

TEAMS = {t["name"]: t for t in json.loads((ROOT / "data" / "teams_default.json").read_text(encoding="utf-8"))}
GAMES = {"t20": ("India T20 2024", "Australia T20 2024", "t20i_full", 2024),
         "odi": ("India ODI 2023", "Australia ODI 2023", "odi_full", 2023)}


class Dials(Controller):
    """Ball by ball only: fixed or random bars, and a fixed pace."""

    def __init__(self, team, bat=5, bowl=5, until=None, rng=None):
        super().__init__(team, {"ball"})
        self.bat, self.bowl, self.until, self.rng = bat, bowl, until, rng
        self.asked = []

    def decide(self, q):
        assert q["kind"] == "ball"
        self.asked.append((q["state"]["innings"], q["side"], q["over"], q["state"]["wkts"]))
        pick = (lambda v: self.rng.randint(1, 9)) if self.rng else (lambda v: v)
        if q["side"] == "bat":
            assert q["bowler"]["bars"] is None and 1 <= q["striker"]["bars"] <= 9
            assert 0.0 <= q["striker"]["settled"] <= 1.0
            ans = {"bat": {q["striker"]["id"]: pick(self.bat), q["non_striker"]["id"]: pick(self.bat)}}
        else:
            assert q["striker"]["bars"] is None and 1 <= q["bowler"]["bars"] <= 9
            ans = {"bowl": {q["bowler"]["id"]: pick(self.bowl)}}
        return {**ans, "until": self.until}


class Watcher(Dials):
    """Collects the balls sent for the highlights (q["since"]) with the aggression dials all at Normal."""

    def __init__(self, team, until=None):
        super().__init__(team, until=until)
        self.balls = []

    def decide(self, q):
        assert len(q["since"]) <= 18
        self.balls += q["since"]
        return super().decide(q)


def play(fmt, seed, ctl=None):
    a, b, comp, year = GAMES[fmt]
    return simulate_match(TEAMS[a], TEAMS[b], fmt, comp, year, seed=seed, control={a: ctl} if ctl else None)


def main() -> None:
    for fmt in GAMES:
        # bar 5 everywhere = the engine as calibrated, ball for ball
        for seed in range(6):
            plain, dialled = play(fmt, seed), play(fmt, seed, Dials(GAMES[fmt][0]))
            assert json.dumps(plain["innings"]) == json.dumps(dialled["innings"]), (fmt, seed)
        # the multipliers move the right way
        sit = Situation(fmt, GAMES[fmt][2], GAMES[fmt][3])
        base = sit.multipliers(1, 60, 2, 80, None, 20)
        for ph in ("powerplay", "middle", "death"):
            bat = [sit.with_aggression(base, ph, b, 5) for b in range(1, 10)]
            assert all(x["runs"] < y["runs"] and x["wkt"] < y["wkt"] and x["six"] < y["six"]
                       for x, y in zip(bat, bat[1:])), (fmt, ph)
            bowl = [sit.with_aggression(base, ph, 5, b) for b in range(1, 10)]
            assert all(x["wkt"] < y["wkt"] for x, y in zip(bowl, bowl[1:])), (fmt, ph)
            assert bowl[0]["runs"] < base["runs"] < bowl[8]["runs"], (fmt, ph)
        s = [sit.settled(b) for b in range(0, 80)]
        assert s[0] == 0.0 and s[-1] == 1.0 and all(x <= y for x, y in zip(s, s[1:]))
        # random dials every ball keep the laws
        for seed in range(15):
            card = play(fmt, seed, Dials(GAMES[fmt][0], rng=random.Random(seed)))
            check_card(card, fmt)
    # the balls sent for the highlights: in order, each once, consistent with the scorecard, no random draws used
    for fmt in GAMES:
        w = Watcher(GAMES[fmt][0])
        card = play(fmt, 3, w)
        assert json.dumps(play(fmt, 3)["innings"]) == json.dumps(card["innings"]), fmt
        ns = [(b["innings"], b["n"]) for b in w.balls]
        assert ns == sorted(set(ns)) and w.balls, fmt
        for inn in card["innings"][:2]:
            mine = [b for b in w.balls if b["innings"] == inn["number"] and b["batting"] == inn["team"]]
            got = sum(b["runs"] + b["extra_runs"] for b in mine)
            assert got <= inn["runs"] and inn["runs"] - got <= 20, (fmt, got, inn["runs"])   # the last balls come after the last pause
            assert sum(1 for b in mine if b["wicket"]) <= inn["wickets"]
        for b in w.balls:
            assert (b["wicket"] is None) == (b["out"] is None) and 1 <= b["ball"] <= 6
            if b["wicket"] in ("caught_fielder", "caught_keeper", "caught_bowler", "stumped"):
                assert b["fielder"] and b["fielder_role"] in ("keeper", "bowler", "fielder"), b
    # pace: "over" asks once per over the side is involved in, "innings" once per innings, "wicket" once per
    # wicket (plus the start)
    for until, check in (("over", lambda asked, card: len(asked) == sum(len(i["overs_log"]) for i in card["innings"][:2])),
                         ("innings", lambda asked, card: len(asked) == 2),
                         ("wicket", lambda asked, card: len(asked) <= 2 + sum(i["wickets"] for i in card["innings"][:2]))):
        for seed in range(5):
            c = Dials(GAMES["t20"][0], until=until)
            card = play("t20", seed, c)
            if card["result"].get("type") == "no_result" or len(card["innings"]) > 2:
                continue
            assert check(c.asked, card), (until, seed, len(c.asked))
    # higher batting bars score faster and lose many more wickets (a side batting first, same seeds; the rate
    # rises only a little over a whole innings because the tail comes in sooner)
    a, b, comp, year = GAMES["t20"]
    rate, wk = {}, {}
    for bars in (2, 8):
        r = bl = w = 0
        for seed in range(60):
            card = simulate_match(TEAMS[a], TEAMS[b], "t20", comp, year, seed=seed, control={a: Dials(a, bat=bars)},
                                  toss=a, decision="bat")
            r += card["innings"][0]["runs"]
            bl += card["innings"][0]["balls"]
            w += card["innings"][0]["wickets"]
        rate[bars], wk[bars] = 6 * r / bl, w / 60
    assert rate[8] > rate[2] and wk[8] > wk[2] + 2, (rate, wk)
    print("aggression tests passed: run rate", {k: round(v, 2) for k, v in rate.items()},
          "wickets", {k: round(v, 1) for k, v in wk.items()})


if __name__ == "__main__":
    main()
