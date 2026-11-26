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

Domestic records sharpen it. Wikipedia's career table (data/raw_stats/styles.json, scripts/fetch_styles.py) gives
first-class totals for a Test estimate and List A totals for an ODI one: batting average, bowling strike rate and
economy. For the runs and wicket indexes of a player with enough of them, a second line y = a + b x + c d is used,
d being his domestic measure against his role group's. It is fitted on the players rated in both formats, with their
domestic careers less their Tests (or ODIs), so it is not fitted on the records it predicts. The fit gives the
domestic measure the weight it earns: first-class economy and batting average say a good deal about a Test bowler's
economy and a batter's dismissal rate, first-class strike rate nothing about Test wickets (a weight with the wrong
sign is dropped, and that index keeps the plain line). The fitted
players' leftover differences by home country (domestic cricket is stronger in some than in others) are kept, shrunk,
and applied by his. A bowler's overs a match then come from his domestic overs a match. Players whose infobox has no
such column keep the plain estimate: it shows four columns, and many internationals' show ODI, T20I, List A and T20.

record() returns a row shaped like one of data.ratings(fmt)["players"], marked "estimated_from" (and
"estimated_with": the domestic record used, if any), which data.player() reads like any other.
"""
from __future__ import annotations

import json
import math
import re
from functools import lru_cache

from .data import DATA, METRICS, phase_names, ratings
from .leagues import LEAGUES

FIT_BALLS = 300                 # balls in each format for a player to count in the fit
# formats tried, in order, for a player with no record in this one: the nearest in length first
SOURCES = {"odi": ("t20", "test"), "test": ("odi", "t20"), "t20": ("odi", "test")}
DEFAULT_ROLE = {"bat": "middle", "bowl": "part_unk"}
EXTRA_SHRINK = 0.5              # run-out, wide and no-ball tendencies: halfway back to average
PHASE_HINT_BALLS = 60           # his phase usage in the other format, counted as this many balls
# the domestic record that informs each format's estimate (a Wikipedia career column) and its measure per index
DOMESTIC = {"test": "first_class", "odi": "list_a"}
# the indexes it informs and the sign its weight must have: a higher batting average, fewer dismissals (and maybe
# more runs); a higher economy, more runs; a higher strike rate, fewer wickets. A weight the other way is noise, and
# that index keeps the plain line.
DOM_X = {"bat": {"runs": 1, "wkt": -1}, "bowl": {"runs": 1, "wkt": -1}}
DOM_MIN = {"bat": 10, "bowl": 15}   # domestic dismissals / wickets (outside the format) for the record to count
DOM_MIN_BALLS = 600                 # and balls bowled, for a bowler
DOM_SHRINK = 20                     # his domestic measure counts n / (n + this) (n: dismissals or wickets)
DOM_MIN_FIT = 40                    # fitted players with a domestic record for the second line
COUNTRY_SHRINK = 20                 # a country's mean leftover counts n / (n + this) (n: its fitted players)
COUNTRY_MIN = 8                     # fitted players for a country to get its own correction
DOM_MIN_MATCHES = 10                # domestic matches for his domestic overs a match to be used


def _role(rec: dict, side: str) -> str:
    return rec.get(f"{side}_role") or DEFAULT_ROLE[side]


def _role_mean(fmt: str, m: str, side: str, role: str) -> float:
    means = ratings(fmt)["meta"]["role_means"][m][side]
    return means.get(role) or sum(means.values()) / len(means)


def _x(fmt: str, rec: dict, side: str, m: str) -> float:
    return math.log(max(rec[side]["idx"][m], 1e-3) / _role_mean(fmt, m, side, _role(rec, side)))


def _matches(rec: dict) -> float:
    """Matches in his career rows ("m"; rows from Wikipedia totals say "matches", as text)."""
    return sum(_num(c.get("m") or c.get("matches")) or 0 for c in (rec.get("career") or {}).values()
               if isinstance(c, dict))


def _opm(rec: dict) -> float:
    w, n = rec.get("bowl") or {}, _matches(rec)
    return (w.get("balls") or 0) / 6 / n if n else 0.0


def _num(v) -> float | None:
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r"-?[\d,]+(?:\.\d+)?", v or "")
    return float(m.group().replace(",", "")) if m else None


@lru_cache(maxsize=None)
def _styles() -> dict:
    path = DATA / "raw_stats" / "styles.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _country(rec: dict) -> str | None:
    """His home country: his national side, or the home of the league he mostly plays in ("league:ipl")."""
    team = rec.get("team") or ""
    if team.startswith("league:"):
        lg = LEAGUES.get(team.split(":")[1])
        return lg.home if lg else None
    return team or None


def domestic(fmt: str, pid: str, rec: dict | None = None) -> dict:
    """His domestic record that informs fmt, less his record in fmt (rec: his fmt ratings row, whose career totals
    are taken away): {"bat"/"bowl": {metric: (log measure, weight n)}, "opm": overs a match or None}. Empty when
    Wikipedia has no such column for him; "bat" / "bowl" only when there is enough of it."""
    col = (_styles().get(pid) or {}).get(DOMESTIC.get(fmt, ""))
    if not col:
        return {}
    m, runs, avg = _num(col.get("matches")), _num(col.get("runs")), _num(col.get("bat_avg"))
    balls, wk, bav = _num(col.get("balls")), _num(col.get("wkts")), _num(col.get("bowl_avg"))
    t = (rec or {}).get("totals") or {}
    t_runs, t_avg, t_wk, t_bav, t_balls = (_num(t.get(k)) for k in ("runs", "bat_avg", "wkts", "bowl_avg", "balls"))
    out: dict = {"opm": balls / 6 / m if balls and m and m >= DOM_MIN_MATCHES else None}
    if runs and avg:
        outs = runs / avg
        if t_runs and t_avg:
            runs, outs = runs - t_runs, outs - t_runs / t_avg
        if outs >= DOM_MIN["bat"] and runs > 0:
            x = math.log(runs / outs)
            out["bat"] = {"runs": (x, outs), "wkt": (x, outs)}
    if balls and wk and bav:
        rc = wk * bav
        if t_wk and t_bav:
            wk, rc = wk - t_wk, rc - t_wk * t_bav
        if t_balls:
            balls -= t_balls
        if wk >= DOM_MIN["bowl"] and balls >= DOM_MIN_BALLS and rc > 0:
            out["bowl"] = {"runs": (math.log(6 * rc / balls), wk), "wkt": (math.log(balls / wk), wk)}
    return out


def _ols(rows: list[tuple]) -> tuple[list[float], float]:
    """Least squares y = a + b1 x1 + ... over rows (x1, ..., y): coefficients [a, b1, ...] and r^2."""
    k = len(rows[0])
    A = [[1.0, *r[:-1]] for r in rows]
    y = [r[-1] for r in rows]
    M = [[sum(a[i] * a[j] for a in A) for j in range(k)] for i in range(k)]
    v = [sum(a[i] * yy for a, yy in zip(A, y)) for i in range(k)]
    for c in range(k):                                  # Gauss-Jordan on the normal equations
        piv = max(range(c, k), key=lambda r: abs(M[r][c]))
        M[c], M[piv], v[c], v[piv] = M[piv], M[c], v[piv], v[c]
        if abs(M[c][c]) < 1e-12:
            return [sum(y) / len(y)] + [0.0] * (k - 1), 0.0
        for r in range(k):
            if r != c:
                f = M[r][c] / M[c][c]
                M[r] = [a - f * b for a, b in zip(M[r], M[c])]
                v[r] -= f * v[c]
    beta = [v[i] / M[i][i] for i in range(k)]
    my = sum(y) / len(y)
    sst = sum((yy - my) ** 2 for yy in y)
    sse = sum((yy - sum(b * a for b, a in zip(beta, row))) ** 2 for row, yy in zip(A, y))
    return beta, (1 - sse / sst if sst else 0.0)


def _dom_x(dom: dict, side: str, m: str, role: str, means: dict) -> float:
    """His domestic measure against his role group's, shrunk by how much of it there is."""
    x, n = dom[side][m]
    mu = means[role] if role in means else sum(means.values()) / len(means)
    return (x - mu) * n / (n + DOM_SHRINK)


def _domestic_fit(src: str, tgt: str, S: dict, T: dict, both: list[str]) -> dict:
    """The second line y = a + b x + c d, its role means of d and its country corrections (see the module doc)."""
    out: dict = {"bat": {}, "bowl": {}, "means": {"bat": {}, "bowl": {}}, "country": {"bat": {}, "bowl": {}}}
    doms = {p: domestic(tgt, p, T[p]) for p in both}
    for side in ("bat", "bowl"):
        pairs = [(p, S[p], T[p]) for p in both if S[p].get(side) and T[p].get(side) and side in doms[p]
                 and S[p][side]["balls"] >= FIT_BALLS and T[p][side]["balls"] >= FIT_BALLS]
        if len(pairs) < DOM_MIN_FIT:
            continue
        for m, sign in DOM_X[side].items():
            by_role: dict = {}
            for p, s, _ in pairs:
                by_role.setdefault(_role(s, side), []).append(doms[p][side][m][0])
            means = {r: sum(v) / len(v) for r, v in by_role.items()}
            rows = [(_x(src, s, side, m), _dom_x(doms[p], side, m, _role(s, side), means), _x(tgt, t, side, m))
                    for p, s, t in pairs]
            (a, b, c), r2 = _ols(rows)
            if c * sign <= 0:
                continue
            left: dict = {}
            for (_, _, t), (x, d, y) in zip(pairs, rows):
                left.setdefault(_country(t), []).append(y - (a + b * x + c * d))
            out[side][m] = (a, b, c, r2, min(r[2] for r in rows), max(r[2] for r in rows))
            out["means"][side][m] = means
            out["country"][side][m] = {k: sum(v) / (len(v) + COUNTRY_SHRINK) for k, v in left.items()
                                       if k and len(v) >= COUNTRY_MIN}
    bowlers = [(doms[p]["opm"], _opm(T[p])) for p in both if doms[p].get("opm") and _opm(T[p])
               and (T[p].get("bowl") or {}).get("balls", 0) >= FIT_BALLS]
    sd, st = sum(d for d, _ in bowlers), sum(t for _, t in bowlers)
    out["opm"] = st / sd if sd and len(bowlers) >= 20 else None
    return out


@lru_cache(maxsize=None)
def mapping(src: str, tgt: str) -> dict:
    """{"bat"/"bowl": {metric: (a, b, r2, y_lo, y_hi)}, "opm": overs-a-match ratio, "dom": the domestic line or
    None} from the players rated in both formats by ball-by-ball records."""
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
    out["dom"] = _domestic_fit(src, tgt, S, T, both) if tgt in DOMESTIC else None
    return out


def source(fmt: str, pid: str) -> str | None:
    """The format an estimate for him in fmt would come from (None: rated in fmt, or in no format): the nearest in
    length he has ball-by-ball records in (the lines are fitted on those), else the nearest he is rated in at all."""
    if pid in ratings(fmt)["players"]:
        return None
    rated = [s for s in SOURCES.get(fmt, ()) if pid in ratings(s)["players"]]
    bbb = [s for s in rated if "ball_by_ball" in (ratings(s)["players"][pid].get("source") or "")]
    return (bbb or rated or [None])[0]


def _side(src: str, tgt: str, rec: dict, side: str, fit: dict, dom: dict) -> dict:
    r, role = rec[side], _role(rec, side)
    dfit = fit.get("dom") or {}
    idx, r2s = {}, []
    for m in METRICS:
        x = _x(src, rec, side, m)
        if side in dom and m in dfit.get(side, {}):
            a, b, c, r2, lo, hi = dfit[side][m]
            y = (a + b * x + c * _dom_x(dom, side, m, role, dfit["means"][side][m])
                 + dfit["country"][side][m].get(_country(rec), 0.0))
        else:
            a, b, r2, lo, hi = fit[side][m]
            y = a + b * x
        y = min(max(y, lo), hi)
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
    dfit = fit.get("dom") or {}
    dom = domestic(fmt, pid) if dfit else {}
    used = [k for k in ("bat", "bowl") if k in dom and rec.get(k) and dfit.get(k)]
    if not rec.get("bowl"):
        opm = 0.0
    elif dom.get("opm") and dfit.get("opm"):
        opm = dom["opm"] * dfit["opm"]                    # his domestic overs a match, scaled
    else:
        opm = _opm(rec) * fit["opm"]
    from .data import _keepers
    row = {k: rec.get(k) for k in ("name", "team", "dob", "bat_hand", "bowl_type", "bowl_kind", "bowl_arm",
                                    "bat_role", "bowl_role", "position", "cricinfo_id")}
    row.update(source="estimated", estimated_from=src, estimated_with=DOMESTIC[fmt] if used else None,
               career={}, keeper=bool(rec.get("keeper")) or pid in _keepers(src),
               bat=_side(src, fmt, rec, "bat", fit, dom) if rec.get("bat") else None,
               bowl=_side(src, fmt, rec, "bowl", fit, dom) if rec.get("bowl") else None,
               opm=round(opm, 2))
    return row
