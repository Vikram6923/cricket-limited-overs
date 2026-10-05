"""Rain interruptions and DLS targets.

Rain (fitted, engine/fit/fit_rain.py): the share of real matches cut short in the host country, and for an
affected match a real match's rain profile (overs lost before the start, first innings ended early, chase
reduced, chase stopped for good, abandoned) replayed as fractions of the scheduled overs. Countries with little
data use all matches.

DLS (Standard Edition formulas, with the engine's own resource table - situation.par_frac, learned from real
innings - in place of the published one):
- resources R(balls left, wickets lost) = share of an average innings' runs still to come;
- R1 = resources the side batting first had (its overs at the start, less any lost when its innings was cut);
  R2 = the same for the chase (less the resources lost in each interruption);
- par = S x R2 / R1 if R2 <= R1, else S + G x (R2 - R1), with G = the average first-innings total in these
  conditions; target = floor(par) + 1;
- if the chase can't be resumed: par for the resources it has used; more than par wins, par exactly is a tie;
  fewer than the minimum overs (ODI 20, T20 5) = no result.
"""
from __future__ import annotations

import json
import math
import random
import zlib
from functools import lru_cache
from pathlib import Path

from .data import FORMATS

DATA = Path(__file__).resolve().parent.parent / "data" / "engine"
MIN_OVERS = {"odi": 20, "t20": 5}


@lru_cache(maxsize=2)
def _table(fmt: str) -> dict:
    p = DATA / f"rain_{fmt}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"countries": {}}


def country(fmt: str, venue: str | None, comp: str | None) -> str | None:
    t = _table(fmt)
    if comp and comp in t.get("league_home", {}):
        return t["league_home"][comp]
    return t.get("venue_country", {}).get((venue or "").split(",")[0])


def sample(fmt: str, venue: str | None, comp: str | None, seed) -> dict | None:
    """A rain profile for this match, or None if it stays dry. Its own random stream, so a dry match plays out
    exactly as it would with rain off."""
    rng = random.Random(zlib.crc32(f"rain|{seed}".encode()))
    t = _table(fmt)["countries"]
    c = t.get(country(fmt, venue, comp) or "") or t.get("all")
    if not c or rng.random() >= c["p"]:
        return None
    p = dict(rng.choice(c["profiles"]))
    p["u"] = rng.random()            # where in the chase a reduction happens (0 = before it starts)
    return p


class DLS:
    def __init__(self, sit, fmt: str):
        self.sit, self.fmt = sit, fmt
        self.N = FORMATS[fmt]["overs"] * 6
        self.G = sit.scale
        self.r1 = self.r2 = None

    def res(self, balls_left: int, wk: int) -> float:
        if balls_left <= 0 or wk >= 10:
            return 0.0
        return self.sit.par_frac(self.N - min(balls_left, self.N), wk)

    def par(self, s: int, r2: float) -> float:
        if r2 <= self.r1:
            return s * r2 / self.r1
        return s + self.G * (r2 - self.r1)

    def target(self, s: int) -> int:
        return math.floor(self.par(s, self.r2)) + 1


def quota(max_overs: int) -> int:
    """Most overs one bowler may bowl: a fifth of the innings, rounded up (10 of 50, 4 of 20)."""
    return max(1, math.ceil(max_overs / 5))
