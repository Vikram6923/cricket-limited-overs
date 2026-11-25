"""Estimated ratings for a player with no record in a format, from his record in another (an IPL side's T20-only
players in an ODI or a Test).

The estimate is learned from the players rated in both formats (at least FIT_BALLS balls in each). For each side
(bat / bowl) and metric, x = log(his index / the mean index of his role group) in the format he played and
y = the same in the format he did not; a straight line y = a + b x is fitted over those players. A T20-only
player's estimate is his role group's mean in the new format times exp(a + b x), kept inside the range the fitted
players span. b is well under 1 for most metrics (a T20 strike rate says only so much about an ODI one) and lower
still for Tests, so an outstanding T20 player is good, not outstanding, in a Test. The estimate's confidence is his
confidence in the format he played times the share of the spread the line explains (r^2), so XI selection treats
him as uncertain. Overs a match scale with the formats' quotas as they do for the fitted bowlers.

record() returns a row shaped like one of data.ratings(fmt)["players"], marked "estimated_from", which
data.player() reads like any other.
"""
from __future__ import annotations

import math
from functools import lru_cache

from .data import METRICS, phase_names, ratings

FIT_BALLS = 300                 # balls in each format for a player to count in the fit
# formats tried, in order, for a player with no record in this one: the nearest in length first
SOURCES = {"odi": ("t20", "test"), "test": ("odi", "t20"), "t20": ("odi", "test")}
DEFAULT_ROLE = {"bat": "middle", "bowl": "part_unk"}
EXTRA_SHRINK = 0.5              # run-out, wide and no-ball tendencies: halfway back to average
PHASE_HINT_BALLS = 60           # his phase usage in the other format, counted as this many balls


def _role(rec: dict, side: str) -> str:
    return rec.get(f"{side}_role") or DEFAULT_ROLE[side]


def _role_mean(fmt: str, m: str, side: str, role: str) -> float:
    means = ratings(fmt)["meta"]["role_means"][m][side]
    return means.get(role) or sum(means.values()) / len(means)


def _x(fmt: str, rec: dict, side: str, m: str) -> float:
    return math.log(max(rec[side]["idx"][m], 1e-3) / _role_mean(fmt, m, side, _role(rec, side)))


def _matches(rec: dict) -> int:
    return sum((c.get("m") or 0) for c in (rec.get("career") or {}).values() if isinstance(c, dict))


def _opm(rec: dict) -> float:
    w, n = rec.get("bowl") or {}, _matches(rec)
    return (w.get("balls") or 0) / 6 / n if n else 0.0


@lru_cache(maxsize=None)
def mapping(src: str, tgt: str) -> dict:
    """{"bat"/"bowl": {metric: (a, b, r2, y_lo, y_hi)}, "opm": overs-a-match ratio} from the players rated in
    both formats by ball-by-ball records."""
    S, T = ratings(src)["players"], ratings(tgt)["players"]
    both = [p for p in S if p in T and S[p].get("source") == T[p].get("source") == "ball_by_ball"]
    out: dict = {}
    for side in ("bat", "bowl"):
        pairs = [(S[p], T[p]) for p in both if S[p].get(side) and T[p].get(side)
                 and S[p][side]["balls"] >= FIT_BALLS and T[p][side]["balls"] >= FIT_BALLS]
        out[side] = {}
        for m in METRICS:
            xs = [_x(src, s, side, m) for s, _ in pairs]
            ys = [_x(tgt, t, side, m) for _, t in pairs]
            n = len(xs)
            if n < 20:
                out[side][m] = (0.0, 0.0, 0.0, 0.0, 0.0)
                continue
            mx, my = sum(xs) / n, sum(ys) / n
            sxx = sum((x - mx) ** 2 for x in xs)
            syy = sum((y - my) ** 2 for y in ys)
            sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
            b = sxy / sxx if sxx else 0.0
            r2 = sxy * sxy / (sxx * syy) if sxx and syy else 0.0
            out[side][m] = (my - b * mx, b, r2, min(ys), max(ys))
    bowlers = [(S[p], T[p]) for p in both if (S[p].get("bowl") or {}).get("balls", 0) >= FIT_BALLS
               and (T[p].get("bowl") or {}).get("balls", 0) >= FIT_BALLS and _opm(S[p]) and _opm(T[p])]
    so, to = sum(_opm(s) for s, _ in bowlers), sum(_opm(t) for _, t in bowlers)
    out["opm"] = to / so if so else 1.0
    return out


def source(fmt: str, pid: str) -> str | None:
    """The format an estimate for him in fmt would come from (None: rated in fmt, or in no format)."""
    if pid in ratings(fmt)["players"]:
        return None
    return next((s for s in SOURCES.get(fmt, ()) if pid in ratings(s)["players"]), None)


def _side(src: str, tgt: str, rec: dict, side: str, fit: dict) -> dict:
    r, role = rec[side], _role(rec, side)
    idx, r2s = {}, []
    for m in METRICS:
        a, b, r2, lo, hi = fit[side][m]
        y = min(max(a + b * _x(src, rec, side, m), lo), hi)
        idx[m] = round(_role_mean(tgt, m, side, role) * math.exp(y), 4)
        if m in ("runs", "wkt"):
            r2s.append(r2)
    phases, src_phases = phase_names(tgt), phase_names(src)
    pb = r.get("phase_balls") or {}
    tot = sum(pb.values())
    out = {"balls": 0, "confidence": round(float(r.get("confidence") or 0) * sum(r2s) / len(r2s), 3),
           "idx": idx, "phase": {ph: dict(idx) for ph in phases}, "ref": None,
           # how he is used across the innings carries over when the formats share their phases (T20 / ODI)
           "phase_balls": ({ph: PHASE_HINT_BALLS * pb.get(ph, 0) / tot for ph in phases}
                           if tot and phases == src_phases else {})}
    shrink = lambda v: round(math.exp(EXTRA_SHRINK * math.log(max(float(v or 1.0), 1e-3))), 4)
    if side == "bat":
        out["other_out_idx"] = shrink(r.get("other_out_idx"))
    else:
        out["wide_idx"], out["noball_idx"] = shrink(r.get("wide_idx")), shrink(r.get("noball_idx"))
    return out


@lru_cache(maxsize=None)
def record(fmt: str, pid: str) -> dict | None:
    """His estimated ratings row for fmt, or None (rated in fmt, or in no format to estimate from)."""
    src = source(fmt, pid)
    if not src:
        return None
    rec, fit = ratings(src)["players"][pid], mapping(src, fmt)
    from .data import _keepers
    row = {k: rec.get(k) for k in ("name", "team", "dob", "bat_hand", "bowl_type", "bowl_kind", "bowl_arm",
                                    "bat_role", "bowl_role", "position", "cricinfo_id")}
    row.update(source="estimated", estimated_from=src, career={},
               keeper=bool(rec.get("keeper")) or pid in _keepers(src),
               bat=_side(src, fmt, rec, "bat", fit) if rec.get("bat") else None,
               bowl=_side(src, fmt, rec, "bowl", fit) if rec.get("bowl") else None,
               opm=round(_opm(rec) * fit["opm"], 2) if rec.get("bowl") else 0.0)
    return row
