"""Win / draw / loss chances in a Test, from the state of the match (docs/test_match_plan.md section 5).

    from engine.test_wdl import table
    t = table()                                  # None until data/engine/wdl_test.json has been built
    win, draw = t.probs(4, 3, -120, 60)          # last innings, 3 down, 120 to get, 60 overs left in the match
    v = t.value(2, 5, -80, 300)                  # the batting side's win chance + half the draw chance

The state is (innings 1-4, wickets down, x, overs left in the match); x is the batting side's lead (its runs in
the match minus the other side's), or in the last innings minus the runs still needed. The table is made by
engine/fit/fit_wdl.py: thousands of Tests between equal sides played by the calibrated engine, counted and
smoothed. It must be rebuilt whenever the Test engine is recalibrated.

It gives the match centre its three-band chart, each player's impact (so the player of the match), and the
turning point. It does not change how a match is played.
"""
from __future__ import annotations

import json
from functools import lru_cache

from .data import DATA

PATH = DATA / "engine" / "wdl_test.json"
SESSION_NAMES = ("before lunch", "between lunch and tea", "after tea")


class WDL:
    def __init__(self, t: dict):
        self.x0, self.xs, self.nx = t["x0"], t["x_step"], t["nx"]
        self.ls, self.nl = t["l_step"], t["nl"]
        self.runs_per_win = t["runs_per_win"]
        self.tests = t.get("tests")
        # [innings - 1][wickets] -> flat list over (overs-left node, x node)
        self.win = [[[v / 1000 for v in row] for row in t["win"][str(i)]] for i in (1, 2, 3, 4)]
        self.draw = [[[v / 1000 for v in row] for row in t["draw"][str(i)]] for i in (1, 2, 3, 4)]
        self.val = [[[w + d / 2 for w, d in zip(wr, dr)] for wr, dr in zip(wi, di)]
                    for wi, di in zip(self.win, self.draw)]

    def _where(self, x: float, left: float) -> tuple:
        fx = (x - self.x0) / self.xs
        fx = 0.0 if fx < 0 else min(fx, self.nx - 1.000001)
        fl = left / self.ls
        fl = 0.0 if fl < 0 else min(fl, self.nl - 1.000001)
        xi, li = int(fx), int(fl)
        return li * self.nx + xi, fx - xi, fl - li

    def _read(self, row: list, k: int, tx: float, tl: float) -> float:
        nx = self.nx
        a = row[k] + (row[k + 1] - row[k]) * tx
        b = row[k + nx] + (row[k + nx + 1] - row[k + nx]) * tx
        return a + (b - a) * tl

    def value(self, innings: int, wkts: int, x: float, left: float) -> float:
        """The batting side's chance of winning plus half the chance of a draw."""
        k, tx, tl = self._where(x, left)
        return self._read(self.val[min(innings, 4) - 1][min(wkts, 9)], k, tx, tl)

    def probs(self, innings: int, wkts: int, x: float, left: float) -> tuple[float, float]:
        """(the batting side wins, the match is drawn); the other side wins with what is left."""
        k, tx, tl = self._where(x, left)
        i, w = min(innings, 4) - 1, min(wkts, 9)
        pw = self._read(self.win[i][w], k, tx, tl)
        pd = self._read(self.draw[i][w], k, tx, tl)
        s = pw + pd
        return (pw / s, pd / s) if s > 1 else (pw, pd)


@lru_cache(maxsize=None)
def table() -> WDL | None:
    return WDL(json.loads(PATH.read_text(encoding="utf-8"))) if PATH.exists() else None


def _score(o: dict) -> str:
    return str(o["total"]) if o["wickets"] >= 10 else f"{o['total']}/{o['wickets']}"


def turning_point(card: dict) -> dict | None:
    """The session that moved the match most towards the side that won it (in a draw or a tie: most, either
    way): the biggest change, between the start and the end of a session, in a side's chance of winning plus
    half the chance of a draw. A Test turns over a session, not an over (an over rarely moves it by more than a
    few points)."""
    seq = []                                   # (day, session, innings dict, over dict, value for the first side)
    for inn in card["innings"]:
        for o in inn.get("overs_log") or []:
            if o.get("wdl"):
                seq.append((o["day"], o["session"], inn, o, o["wdl"][0] + o["wdl"][1] / 2))
    if len(seq) < 2:
        return None
    first = card["innings"][0]["team"]
    other = next((t for t in card["teams"] if t != first), first)
    win = card["result"].get("winner")
    sign = 0 if not win else 1 if win == first else -1
    swings, prev, k = [], 0.5, 0
    while k < len(seq):
        j = k
        while j + 1 < len(seq) and seq[j + 1][:2] == seq[k][:2]:
            j += 1
        swings.append((seq[j][4] - prev, k, j))
        prev = seq[j][4]
        k = j + 1
    sw, k, j = max([s for s in swings if s[0] * sign > 0] or swings, key=lambda s: abs(s[0]))
    day, ses, inn, o0, _ = seq[k]
    o1 = next(x[3] for x in reversed(seq[k:j + 1]) if x[2] is inn)        # the same innings' last over of the session
    start = o0["total"] - o0["runs"], o0["wickets"] - o0["wkts"]
    was = "0/0" if not start[0] and not start[1] else f"{start[0]}/{start[1]}"
    gainer = first if sw > 0 else other
    text = (f"Turning point: day {day}, {SESSION_NAMES[min(ses, 3) - 1]} ({inn['team']} from {was} to {_score(o1)}"
            f"{', all out' if o1['wickets'] >= 10 else ''}) swung the match {abs(sw) * 100:.0f}% towards {gainer}")
    return {"day": day, "session": ses, "innings": inn["number"], "over": o1["over"],
            "swing": round(abs(sw), 3), "towards": gainer, "team": inn["team"], "from": was, "to": _score(o1),
            "text": text}
