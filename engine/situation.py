"""Situational multipliers for the ball model (design T1-1 resources/par, T1-2 intent, T1-3 settling in).

Tables are learned by engine/fit/fit_situation.py as observed / ratings-predicted over real balls, so they are
mean-preserving: over the mix of situations in real cricket they multiply to 1.
"""
from __future__ import annotations

import bisect
import math
import json
from functools import lru_cache

from .data import DATA, FORMATS


@lru_cache(maxsize=None)
def tables(fmt: str) -> dict:
    return json.loads((DATA / "engine" / f"situation_{fmt}.json").read_text(encoding="utf-8"))


class Situation:
    def __init__(self, fmt: str, comp: str, year: int):
        t = tables(fmt)
        self.t = t
        self.metrics = t["metrics"]
        self.N = FORMATS[fmt]["overs"] * 6
        self.overs = FORMATS[fmt]["overs"]
        self.scale = self._scale(t["scale"], comp, year, fmt)
        self._cache: dict = {}

    @staticmethod
    def _scale(table: dict, comp: str, year: int, fmt: str) -> float:
        """Expected first-innings total for an average side in this competition and year (par at the start)."""
        def lookup(c):
            ys = [(int(k.split("|")[1]), v) for k, v in table.items() if k.split("|")[0] == c]
            if not ys:
                return None
            return min(ys, key=lambda yv: abs(yv[0] - year))[1]
        for c in (comp, comp.replace("_full", ""), FORMATS[fmt]["intl"], FORMATS[fmt]["intl"].replace("_full", "")):
            v = lookup(c)
            if v:
                return v
        return 170.0 if fmt == "t20" else 270.0

    def par_frac(self, legal: int, wk: int) -> float:
        par = self.t["par"]
        o = min(legal // 6, self.overs - 1)
        w = min(wk, 9)
        a = par[o][w]
        b = par[o + 1][w] if o + 1 < self.overs else 0.0
        return a + (b - a) * ((legal % 6) / 6)

    def par_runs(self, legal: int, wk: int) -> float:
        """Runs an average side would still add from this state (resources x expected total)."""
        return self.par_frac(legal, wk) * self.scale

    def pressure(self, legal: int, wk: int, need: int) -> float:
        p = self.par_runs(legal, wk)
        return need / p if p > 1 else 9.0

    def multipliers(self, innings: int, legal: int, wk: int, runs: int, target: int | None,
                    faced: int) -> dict:
        t = self.t
        s = bisect.bisect_left(t["settle_edges"], faced)
        bl = bisect.bisect_left(t["balls_left_edges"], self.N - legal)
        w = bisect.bisect_left(t["wkt_edges"], wk)
        if innings == 1 or target is None:
            key = (s, 1, bl, w)
        else:
            p = bisect.bisect_left(t["press_edges"], self.pressure(legal, wk, target - runs))
            key = (s, 2, bl, w, p)
        m = self._cache.get(key)
        if m is None:
            st = t["state1"][bl][w] if len(key) == 4 else t["state2"][bl][w][key[4]]
            se = t["settle"][s]
            m = {name: se[j] * st[j] for j, name in enumerate(self.metrics)}
            self._cache[key] = m
        return m

    PACE = {"fast", "fast_medium", "medium_fast", "medium"}

    def with_matchup(self, mult: dict, hand: str | None, kind: str | None) -> dict:
        """Situation multipliers x batting-hand / bowling-kind matchup (design T2-1). Cached."""
        if not hand or not kind:
            return mult
        k = "pace" if kind in self.PACE else kind
        key = (id(mult), hand, k)
        out = self._cache.get(key)
        if out is None:
            mu = (self.t.get("matchup") or {}).get(hand, {}).get(k)
            out = {m: v * mu.get(m, 1.0) for m, v in mult.items()} if mu else mult
            if mu:
                for m, v in mu.items():
                    out.setdefault(m, v)
            self._cache[key] = out
        return out

    def win_prob_chase(self, legal: int, wk: int, need: int) -> float:
        """Chance the chasing side wins from here (design T1-8): logistic in log(pressure), fitted by maximum
        likelihood on real chases (fit_situation.py: win_model)."""
        if need <= 0:
            return 1.0
        if wk >= 10 or legal >= self.N:
            return 0.0
        m = self.t["win_model"]
        p = max(self.pressure(legal, wk, need), 1e-3)
        res = max(self.par_frac(legal, wk), 0.01)
        z = m["a"] + m["k0"] * math.log(p) / (res ** m["g"])
        return 1.0 / (1.0 + math.exp(min(max(z, -30.0), 30.0)))

    def win_prob_first(self, legal: int, wk: int, runs: int) -> float:
        """Chance the side batting first wins, from its projected total (runs + par still to come)."""
        projected = runs + self.par_runs(legal, wk)
        return 1.0 - self.win_prob_chase(0, 0, int(round(projected)) + 1)
