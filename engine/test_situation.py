"""Situational multipliers for a Test match (docs/test_match_plan.md sections 2-3).

Tables learned by engine/fit/fit_test_situation.py as observed / ratings-predicted over real balls, fitted jointly:
settling in (with a dismissal part), pitch wear and ball age by pace and spin, the innings by wickets down by
lead, and the last innings by wickets down by runs needed per over left (chase, steady, save).

Matchups (engine/fit/fit_test_matchups.py): batting hand x bowling kind, a table of its own that moves runs and
wickets between matchups and leaves each player's level alone.

Batting with the tail (engine/fit/fit_test_tail.py): with seven or more down, how a batter left with a
tailender, the tailender he shields and a last pair of tailenders really bat, by ball of the over (`with_tail`).
That is what farms the strike. A person may turn it off for their own side.

A person's bars (batting approach, bowling plan; 1-9, 5 = as real sides play) move a ball along the runs-v-risk
curve of engine/fit/fit_test_aggression.py (`with_bars`). At bar 5, which is all a computer side ever uses,
nothing changes.
"""
from __future__ import annotations

import bisect
import json
import math
from functools import lru_cache

from .data import DATA, ratings


@lru_cache(maxsize=None)
def tables() -> dict:
    return json.loads((DATA / "engine" / "test_situation.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def bars_table() -> dict | None:
    p = DATA / "engine" / "aggression_test.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


@lru_cache(maxsize=None)
def matchup_table() -> dict:
    p = DATA / "engine" / "test_matchups.json"
    return json.loads(p.read_text(encoding="utf-8"))["matchup"] if p.exists() else {}


@lru_cache(maxsize=None)
def tail_table() -> dict | None:
    p = DATA / "engine" / "test_tail.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def tail_role(striker_pos: int, partner_pos: int, wkts: int) -> str | None:
    """The striker's part in a stand with the tail ('senior', 'shielded', 'last'); None when the table has
    nothing to say: fewer wickets down than it covers, or no tailender in."""
    t = tail_table()
    if not t or wkts < t["wickets"][0]:
        return None
    tf = t["tail_from"]
    if striker_pos >= tf:
        return "last" if partner_pos >= tf else "shielded"
    return "senior" if partner_pos >= tf else None


PACE_KINDS = {"fast", "fast_medium", "medium_fast", "medium"}


@lru_cache(maxsize=None)
def matchup_kind(pid: str) -> str | None:
    """A bowler's name in the matchup table: pace by arm (the arm is in the ratings, not on engine.data.Player),
    spin by its kind. None: not known."""
    rec = ratings("test")["players"].get(pid) or {}
    kind = rec.get("bowl_kind")
    if not kind:
        return None
    if kind in PACE_KINDS:
        return "left_pace" if rec.get("bowl_arm") == "left" else "pace"
    return kind


NORMAL_BARS = 5              # the middle of the 9 bars: the engine as calibrated


class TestSituation:
    __test__ = False             # not a test class (the name starts with Test)

    def __init__(self):
        self.t = t = tables()
        self.metrics = t["metrics"]
        self._cache: dict = {}
        r = self.metrics.index("runs")
        # the last innings' cells named by what real sides do in them: scoring well below the usual rate is
        # batting for a draw, well above it is going for the runs
        self.modes = [["save" if c[r] < 0.9 else "chase" if c[r] > 1.08 else "steady" for c in row]
                      for row in t["fourth"]]

    def cell(self, innings: int, wkts: int, lead: int, need: int | None = None, left: int = 1) -> tuple:
        """The state cell: (innings, wickets bucket, lead bucket), or for the last innings (4, wickets bucket,
        bucket of runs needed per over left in the match)."""
        t = self.t
        w = bisect.bisect_right(t["wkt_edges"], wkts)
        if innings >= 4:
            return 4, w, bisect.bisect_right(t["rr_edges"], need / max(left, 1))
        return innings, w, bisect.bisect_right(t["lead_edges"], lead)

    def mode(self, wkts: int, need: int, left: int) -> str:
        """'chase', 'steady' or 'save': how real sides bat in this last-innings state."""
        _, w, q = self.cell(4, wkts, 0, need, left)
        return self.modes[w][q]

    def multipliers(self, cell: tuple, faced: int, bowl_type: str | None, match_overs: int, ball_age: int) -> dict:
        """Metric -> multiplier for one ball. cell: from cell(); faced: balls the striker has faced;
        match_overs: overs bowled in the match so far (wear); ball_age: overs since the ball was new."""
        t = self.t
        s = bisect.bisect_right(t["settle_edges"], faced)
        ty = bowl_type if bowl_type in ("pace", "spin") else None
        wb = bisect.bisect_right(t["wear_edges"], match_overs) if ty else 0
        ab = bisect.bisect_right(t["age_edges"], ball_age) if ty else 0
        key = (cell, s, ty, wb, ab)
        m = self._cache.get(key)
        if m is None:
            i, w, x = cell
            st = t["fourth"][w][x] if i >= 4 else t["state"][str(i)][w][x]
            se = t["settle"][s]
            we = t["wear"][ty][wb] if ty else None
            ag = t["age"][ty][ab] if ty else None
            m = {name: se[j] * st[j] * (we[j] * ag[j] if ty else 1.0) for j, name in enumerate(self.metrics)}
            self._cache[key] = m
        return m

    def with_matchup(self, mult: dict, hand: str | None, bowler_id: str) -> dict:
        """mult x the batting hand v bowling kind matchup (unchanged when either is not known)."""
        kind = matchup_kind(bowler_id)
        if not hand or not kind:
            return mult
        key = (id(mult), "matchup", hand, kind)
        hit = self._cache.get(key)
        if hit is None or hit[0] is not mult:
            mu = (matchup_table().get(hand) or {}).get(kind)
            hit = (mult, {name: v * mu.get(name, 1.0) for name, v in mult.items()} if mu else mult)
            self._cache[key] = hit
        return hit[1]

    def with_tail(self, mult: dict, role: str | None, wkts: int, legal_in_over: int) -> dict:
        """mult x how real sides bat with the tail. role: from tail_role(); legal_in_over: legal balls already
        bowled in the over (0 to 5)."""
        if not role:
            return mult
        t = tail_table()
        g = bisect.bisect_right(t["ball_edges"], legal_in_over)
        key = (id(mult), "tail", role, wkts, g)
        hit = self._cache.get(key)
        if hit is None or hit[0] is not mult:
            rows = (t["cells"].get(role) or {}).get(str(wkts))
            hit = (mult, {name: v * rows[g][j] for j, (name, v) in
                          enumerate((n, mult[n]) for n in self.metrics)} if rows else mult)
            self._cache[key] = hit
        return hit[1]

    def with_bars(self, mult: dict, bat_bars: int, bowl_bars: int) -> dict:
        """mult x the person's bars. Batting: d = step x (bars - 5) moves the runs rate by e^d and every other
        rate by e^(slope x d). Bowling plan: d = step x bowl_share x (bars - 5) moves the runs rate by e^d (fours,
        sixes and dots with it) and the wicket rate by e^(c d), c = the wicket slope x (1 - bowl_edge) when
        attacking, x (1 + contain_edge) when containing (as engine/situation.py does for limited overs)."""
        if bat_bars == NORMAL_BARS and bowl_bars == NORMAL_BARS:
            return mult
        a = bars_table()
        if not a:
            return mult
        key = (id(mult), "bars", bat_bars, bowl_bars)
        hit = self._cache.get(key)
        if hit is None or hit[0] is not mult:
            sl, step = a["slope"], a["step"]
            db = step * (bat_bars - NORMAL_BARS)
            dw = step * a["bowl_share"] * (bowl_bars - NORMAL_BARS)
            c = sl["wkt"] * (1.0 - a["bowl_edge"] if dw > 0 else 1.0 + a["contain_edge"])
            lr = db + dw
            f = {"runs": math.exp(lr)}
            for name, b in sl.items():
                f[name] = math.exp(b * db + c * dw) if name == "wkt" else math.exp(b * lr)
            hit = (mult, {name: mult.get(name, 1.0) * f.get(name, 1.0) for name in set(mult) | set(f)})
            self._cache[key] = hit
        return hit[1]

    def settled(self, balls: int) -> float:
        """How settled a batter is, 0-1: where his scoring rate stands between his first ball and fully set."""
        t = self.t
        r = [row[self.metrics.index("runs")] for row in t["settle"]]
        x = max(r[:bisect.bisect_right(t["settle_edges"], balls) + 1])
        lo, hi = r[0], max(r)
        return 1.0 if hi <= lo else min(1.0, max(0.0, (x - lo) / (hi - lo)))
