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


@lru_cache(maxsize=None)
def tables() -> dict:
    p = DATA / "engine" / "test_conditions.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def host_of(venue: str | None) -> str | None:
    """The country whose ground this is (None: unknown or neutral)."""
    return (tables().get("hosts") or {}).get(venue_key(venue)) if venue else None


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
