"""Match conditions: venue factor and the day's pitch (design T2-3, T2-4).

Both multiply the competition/year baseline for the whole match: runs, fours and sixes by the runs factor,
wickets by the wicket factor. The pitch is a random draw with the spread and runs/wickets correlation fitted by
engine/fit/fit_venues.py (what real grounds vary by from one match to the next, beyond ordinary randomness).
"""
from __future__ import annotations

import json
import math
import random
import re
from functools import lru_cache

from .data import DATA


def venue_key(name: str | None) -> str:
    """'M.Chinnaswamy Stadium, Bengaluru' -> 'm chinnaswamy stadium'."""
    v = (name or "").split(",")[0].lower()
    v = re.sub(r"[^a-z0-9]+", " ", v)
    return " ".join(v.split())


@lru_cache(maxsize=None)
def venue_table(fmt: str) -> dict:
    p = DATA / "engine" / f"venues_{fmt}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"venues": {}, "pitch": {}}


def venue_factor(fmt: str, venue: str | None) -> dict:
    v = venue_table(fmt)["venues"].get(venue_key(venue))
    return {"runs": v["runs"], "wkt": v["wkt"], "known": True, "name": v["name"]} if v else \
        {"runs": 1.0, "wkt": 1.0, "known": False, "name": venue}


# The pitch-of-the-day draw passed calibration for internationals but over-dispersed IPL totals (+15% SD; leagues
# play on more uniform pitches), so it applies to internationals only (docs/engine_progress.md, step 6).
PITCH_COMPS = {"t20i_full", "t20i", "odi_full", "odi"}


def draw_pitch(fmt: str, rng: random.Random, comp: str | None = None) -> dict:
    if comp not in PITCH_COMPS:
        return {"runs": 1.0, "wkt": 1.0, "z_runs": 0.0}
    t = venue_table(fmt)
    p = (t.get("pitch_by_comp") or {}).get(comp or "") or t.get("pitch") or {}
    sr, sw, c = p.get("sd_runs", 0.0), p.get("sd_wkt", 0.0), p.get("corr", 0.0)
    z1, z2 = rng.gauss(0, 1), rng.gauss(0, 1)
    return {"runs": math.exp(sr * z1), "wkt": math.exp(sw * (c * z1 + math.sqrt(max(1 - c * c, 0)) * z2)),
            "z_runs": z1}


def pitch_report(runs: float, wkt: float) -> str:
    """One line for the match report (ported in spirit from the Test sim's pitchreport)."""
    if runs > 1.08 and wkt < 0.95:
        return "a batting paradise"
    if runs > 1.04:
        return "a good batting pitch"
    if runs < 0.92 and wkt > 1.05:
        return "a difficult pitch for batting"
    if runs < 0.96:
        return "a slow, low-scoring surface"
    if wkt > 1.06:
        return "a lively pitch that helped the bowlers"
    return "a fair pitch"


def apply(base: dict, runs: float, wkt: float) -> dict:
    """Baseline with the match conditions folded in (phase -> rates)."""
    out = {}
    for ph, b in base.items():
        c = dict(b)
        for k in ("runs", "four", "six"):
            c[k] = b[k] * runs
        c["wkt"] = b["wkt"] * wkt
        out[ph] = c
    return out
