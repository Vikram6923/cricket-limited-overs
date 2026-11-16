"""Test match conditions beyond the pitch: whose ground it is, overs lost in a day, and the home edge.

All three come from data/engine/test_conditions.json (engine/fit/fit_test_conditions.py). With no such file
there is no host, no time is lost and there is no home edge.
"""
from __future__ import annotations

import json
import math
import random
import zlib
from functools import lru_cache

from .conditions import venue_key
from .data import DATA

# How a day's lost overs are placed and named. Cricsheet has no clock, so neither can be fitted:
SMALL_LOSS = 10      # up to this many overs are an early close (bad light, slow over rate); more is rain
REF_DAY = 90         # the fitted distribution is for a 90-over day; other day lengths are scaled
# Playing conditions (rules, not fitted numbers):
LAST_HOUR_OVERS = 15 # the last hour of the last day is 15 overs; a draw may be agreed in it
TIMELESS_DAYS = 10   # a timeless Test is played to a finish; the longest (Durban 1939) was given up after its
                     # tenth day, so a match still going then is left drawn


@lru_cache(maxsize=None)
def tables() -> dict:
    p = DATA / "engine" / "test_conditions.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def host_of(venue: str | None) -> str | None:
    """The country whose ground this is (None: unknown or neutral)."""
    return (tables().get("hosts") or {}).get(venue_key(venue)) if venue else None


@lru_cache(maxsize=None)
def era_table() -> dict:
    p = DATA / "engine" / "test_era.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def era_factors(year: int) -> dict:
    """Multipliers on the baseline of a year before ball-by-ball coverage, by decade (engine/fit/fit_test_era.py).
    The engine's situation tables were learned from modern Tests; in a slower era batters stay in longer and
    more innings are left unfinished, so the same tables give too many runs a wicket. These factors are fitted
    so that the decade's Tests score what the era table says. "day_overs" is the decade's playing time in a
    day, in overs: fitted so that as many Tests are drawn as really were (over rates and hours of play were not
    today's; 90 overs a day gave the 1950s twice the draws they had). A covered year, or no table: 1 and None."""
    t = era_table()
    if not t or year >= t["until"]:
        return {"runs": 1.0, "wkt": 1.0, "day_overs": None}
    ds = t["decades"]
    d = min(ds, key=lambda k: abs(int(k) - year // 10 * 10))
    return ds[d]


@lru_cache(maxsize=None)
def day_night() -> dict:
    """{"pace" | "spin": {"runs", "wkt"}}: multipliers on the baseline in a day-night Test (pink ball, a
    session under lights), from the day-night Tests played so far against the same hosts' day Tests
    (engine/fit/fit_test_daynight.py). No file: {} (a day-night Test then plays as a day Test)."""
    p = DATA / "engine" / "test_daynight.json"
    if not p.exists():
        return {}
    t = json.loads(p.read_text(encoding="utf-8"))
    return {k: {"runs": t[k]["runs"], "wkt": t[k]["wkt"]} for k in ("pace", "spin")}


@lru_cache(maxsize=None)
def injuries() -> dict:
    """How often a player is hurt and what follows (engine/fit/fit_test_injuries.py). No file: {} (nobody is
    hurt)."""
    p = DATA / "engine" / "test_injuries.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def home_factors() -> dict:
    """Multipliers on the baseline when the home side bats; the visitors get the inverse. The fitted edge is the
    gap between the two sides, so each gets half of it."""
    h = tables().get("home") or {}
    return {"runs": math.exp(h.get("runs", 0.0) / 2), "wkt": math.exp(h.get("wkt", 0.0) / 2)}


def draw_weather(host: str | None, seed, days: int, day_overs: int) -> dict:
    """{day: {"start": overs into the day, "overs": lost, "why": text}} for the days that lose time. Its own
    random stream, so the cricket of a match is the same with the weather on or off until time runs out."""
    w = tables().get("weather")
    if not w:
        return {}
    step = w["step"]
    rng = random.Random(zlib.crc32(f"test-weather|{seed}".encode()))
    # a match is dry or wet (rain runs over neighbouring days); a host has its own share of wet matches
    wet = rng.random() < (w.get("wet_share_by_host") or {}).get(host or "", w["wet_share"])
    pmf = w["wet"] if wet else w["dry"]
    out = {}
    for day in range(1, days + 1):
        u, k = rng.random(), 0
        for k, p in enumerate(pmf):
            u -= p
            if u < 0:
                break
        v = rng.random()                             # drawn every day, so one day's weather does not move the next's
        s = rng.random()
        if k == 0:
            continue
        n = k * step if k * step >= REF_DAY else k * step - step // 2 + int(v * step)   # within the grid step
        n = min(day_overs, max(1, round(n * day_overs / REF_DAY)))
        if n <= SMALL_LOSS * day_overs / REF_DAY:
            out[day] = {"start": day_overs - n, "overs": n, "why": "bad light and a slow over rate"}
        else:
            out[day] = {"start": int(s * (day_overs - n + 1)), "overs": n,
                        "why": "no play, rain" if n >= day_overs else "rain"}
    return out
