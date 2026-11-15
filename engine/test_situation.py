"""Situational multipliers for a Test match (docs/test_match_plan.md sections 2-3).

Tables learned by engine/fit/fit_test_situation.py as observed / ratings-predicted over real balls, fitted jointly:
settling in (with a dismissal part), pitch wear and ball age by pace and spin, the innings by wickets down by
lead, and the last innings by wickets down by runs needed per over left (chase, steady, save).
"""
from __future__ import annotations

import bisect
import json
from functools import lru_cache

from .data import DATA


@lru_cache(maxsize=None)
def tables() -> dict:
    return json.loads((DATA / "engine" / "test_situation.json").read_text(encoding="utf-8"))


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
