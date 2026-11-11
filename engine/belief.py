"""What the teams believe a player is worth, as against how good he is.

A player's rating comes from his whole career, including seasons after the one being played. That is the best
estimate of how good he is, so matches use it. But an auction (or a squad decision) in a given season must not know
what happens later: before the 2025 IPL auction Vaibhav Suryavanshi had played no T20 cricket in the data, so no
team could know he would score a 35-ball hundred. The teams' belief about a player as of a season uses only:

1. his record in the years before that season (the per-year actual / expected sufficient statistics that
   engine/periods.py also uses), each year's actual counts age-adjusted to the age his career rating stands for
   (x f(typical age) / f(age then), the career mode's fitted age curve), so a teenager's first season is not read as
   his level at 25;
2. shrunk by empirical Bayes (the career fit's tau^2) toward a debutant prior: the average career rating of the
   league's real newcomers who arrived with no T20 record in the data, per batting or bowling role (shrunk toward
   all such newcomers' average with PRIOR_K pseudo-players). A population fact, not the player's own future;
3. plus a scouting hint: the part of the belief that still rests on the prior moves SCOUT of the way toward his
   real rating. Teams see more than T20 records (age-group and first-class cricket, trials, nets), and real
   unknowns do not all go for the base price. There are no real auction prices in the data to fit SCOUT on; it is
   set so Suryavanshi's expected price in the 2025 IPL season pool is about his real Rs 1.1 crore (0.025 gives
   Rs 1.19 crore; with no hint he is a 30 lakh base-price player, with 0.1 Rs 5 crore). One data point: the
   market is steep near replacement level, so even a small hint matters for an outstanding unknown and hardly at
   all for an ordinary one.

The calendar year is the unit: a season in year Y is judged on the years before Y. For a split season ("2025-26",
year 2026) that includes the calendar year the season starts in, so a few of its own December games count.

In a career the world parts from the real one when the career starts, so from then on the teams learn from what
happens in it, not from the real seasons (Career keeps each player's observations in "obs"):
- the league's own seasons, from the scorecards (league_obs): actual counts, and expected counts = balls x the
  league's baseline rates (averaged over the player's usual phases) x the opposition's indexes (the balls-weighted
  average of the bowlers he faced in that innings, or the batters who faced him), as the rating fit's expected
  counts include the opponents. Situations the baseline doesn't model (aggression, chases) still left these 0-9%
  off the players' true levels in test seasons, so each season's expected counts are scaled per side and metric
  so that over the whole league they add up to the true levels (as the rating fit estimates its baseline from
  the same balls);
- the rest of his cricket (outside_obs): internationals, other leagues and domestic T20, which the career doesn't
  play. Each season every active player (in a squad or unsold) gets a made-up record of that cricket drawn from
  his level that season (age and form), with the sampling noise of that many balls: as many balls a season as
  his real T20 cricket outside this league averaged a year, at least MIN_OUTSIDE (everyone plays a domestic
  season). So an unsold youngster who is good shows it, slowly.
Observations are age-adjusted as they are stored, like the real years. A real player is judged on his real record
before he joined the career (its first season for the opening squads) and on the career's seasons after that.

Made-up players have no record of their own; they copy a real player's rating profile and so his record before
his debut, shifted by the years between his debut and theirs; after that they are observed like everyone else.
The coming season's form is never part of the belief (it is drawn after the auction); past seasons' form is, as
far as the teams saw it.
"""
from __future__ import annotations

import json
import math
import random
from functools import lru_cache

from .data import DATA, METRICS, PHASES, Player, ratings, scale_indexes
from .periods import _noise, load_years

FMT = "t20"
SCOUT = 0.025         # share of the gap between prior and real rating a team sees for a player it has no record of
PRIOR_K = 20          # pseudo-players: a role's debutant average is shrunk toward all debutants' average
MIN_DEBUTANTS = 30    # fewer unknown newcomers than this in a league: use every league's
DEFAULT_GROUP = {"bat": "middle", "bowl": "part_unk"}
MIN_OUTSIDE = 120     # balls a season of cricket outside the league, at least (about a domestic T20 season)


def _group(rec: dict, side: str) -> str:
    return rec.get(f"{side}_role") or DEFAULT_GROUP[side]


def _first_year(pid: str) -> int | None:
    rows = load_years(FMT)
    ys = [int(y) for side in ("bat", "bowl") for y in (rows.get(side, {}).get(pid) or {})]
    return min(ys) if ys else None


def _arrivals(league: str) -> list[tuple[str, int]]:
    """(player, debut year) of a competition's real newcomers."""
    if league == "sma":
        from .state_career import _debutants
        return list(_debutants())
    from .career import _debutants
    return [(pid, y) for pid, y, _ in _debutants(league)]


@lru_cache(maxsize=None)
def debut_prior(league: str) -> dict:
    """side -> role group (and "_all") -> metric -> the average career index of the league's newcomers who had no
    T20 record in the data before they arrived."""
    from .auction import league_data
    unknown = [pid for pid, y in _arrivals(league) if (_first_year(pid) or 9999) >= y]
    if len(unknown) < MIN_DEBUTANTS:
        unknown = sorted({pid for lg in league_data() for pid, y in _arrivals(lg) if (_first_year(pid) or 9999) >= y})
    players = ratings(FMT)["players"]
    out = {}
    for side in ("bat", "bowl"):
        by: dict[str, list[dict]] = {}
        for pid in unknown:
            rec = players.get(pid) or {}
            idx = (rec.get(side) or {}).get("idx")
            if idx:
                by.setdefault(_group(rec, side), []).append(idx)
        every = [i for v in by.values() for i in v]
        mean = {m: sum(i[m] for i in every) / len(every) if every else 1.0 for m in METRICS}
        out[side] = {"_all": mean}
        for g, v in by.items():
            out[side][g] = {m: (sum(i[m] for i in v) + PRIOR_K * mean[m]) / (len(v) + PRIOR_K) for m in METRICS}
    return out


def _log_f(side: str, m: str, age: int) -> float:
    from .career import log_f
    return log_f(side, m, age)


def ratios(pid: str, cutoff: int, born: int, ref: dict, league: str, shift: int = 0,
           real_until: int | None = None, obs: dict | None = None) -> dict:
    """side -> {metric: belief / career index, "balls": balls of record seen}, for real player `pid`'s rating as
    the teams see it before season `cutoff`. born, ref: the birth year (in the world being played) and the typical
    log age factors per side and metric (engine.career.profile); shift: years added to pid's record (made-up
    players copying him); real_until: his real record counts only before this year (a career: when he joined it);
    obs: side -> observations since (accumulate(), already age-adjusted)."""
    cutoff = min(cutoff, real_until) if real_until is not None else cutoff
    rec = ratings(FMT)["players"].get(pid) or {}
    tau2 = ratings(FMT)["meta"]["tau2"]
    rows = load_years(FMT)
    out = {}
    for side in ("bat", "bowl"):
        career = (rec.get(side) or {}).get("idx")
        if not career:
            continue
        pri = debut_prior(league)[side]
        prior = pri.get(_group(rec, side)) or pri["_all"]
        acc = None
        for y, row in (rows.get(side, {}).get(pid) or {}).items():
            yr = int(y) + shift
            if yr >= cutoff:
                continue
            k = [math.exp(ref[side][m] - _log_f(side, m, yr - born)) for m in METRICS]
            scaled = [row[0]] + [x for j in range(len(METRICS)) for x in (row[1 + 2 * j] * k[j], row[2 + 2 * j])] \
                + [row[-1] * k[0] * k[0]]
            acc = scaled if acc is None else [a + b for a, b in zip(acc, scaled)]
        seen = (obs or {}).get(side)
        if seen:
            acc = _add(acc, seen)
        d = {}
        for j, m in enumerate(METRICS):
            p, e, truth = prior[m], (acc[2 + 2 * j] if acc else 0.0), career[m]
            s = 0.0
            if e > 0:
                t2 = tau2[m][side]
                s = t2 / (t2 + _noise(m, acc, j, p))
            b = p + s * (acc[1 + 2 * j] / e - p) if e > 0 else p
            b += SCOUT * (1 - s) * (truth - b)
            d[m] = b / truth if truth else 1.0
        d["balls"] = acc[0] if acc else 0
        out[side] = d
    return out


def apply(p: Player, rat: dict) -> Player:
    """Scale engine player p (rated on his whole career) to the teams' belief; ref gets "seen_balls"."""
    scale_indexes(p, rat, None)
    for side, r in rat.items():
        if p.ref.get(side) is not None:
            p.ref[side] = {**p.ref[side], "seen_balls": r["balls"]}
    return p


def seen_balls(p: Player) -> dict | None:
    """side -> balls of record behind the belief (apply()), for the sides he is rated on."""
    from .auction import seen_balls as sb
    return sb(p)


def show(p: Player, seen: Player) -> Player:
    """Make what a captain is shown about match player p (as good as he is) what the teams believe (seen): his
    readable numbers, and factors on the expected rates (Player.shown). The match itself still uses p's indexes."""
    p.ref = dict(seen.ref)
    p.shown = {}
    for side in ("bat", "bowl"):
        if getattr(p, f"rated_{side}"):
            real, b = level(p, side), level(seen, side)
            p.shown[side] = {m: b[m] / real[m] if real[m] else 1.0 for m in METRICS}
    return p


def seen_player(pid: str, season: int, league: str) -> Player:
    """A real player (no age model) as the teams see him before `season` (League Season auctions)."""
    from .career import profile
    from .data import player
    born, ref = profile(pid, season)
    return apply(player(FMT, pid), ratios(pid, season, born, ref, league))


# ------------------------------------------------------------------------------------------------ career seasons

def _shares(p: Player, side: str) -> dict:
    sh = p.bat_phase_share if side == "bat" else p.bowl_phase_share
    return sh or {ph: 1 / len(PHASES) for ph in PHASES}


def level(p: Player, side: str) -> dict:
    """metric -> the player's index averaged over his usual phases."""
    sh, idx = _shares(p, side), getattr(p, side)
    return {m: sum(sh[ph] * idx[ph][m] for ph in PHASES) for m in METRICS}


def _rates(p: Player, side: str, base: dict) -> tuple[dict, float]:
    """(metric -> baseline rate per ball over his usual phases, variance of runs per ball)."""
    sh = _shares(p, side)
    rate = {m: sum(sh[ph] * base[ph][m] for ph in PHASES) for m in METRICS}
    var = sum(sh[ph] * (base[ph]["runs_sq"] - base[ph]["runs"] ** 2) for ph in PHASES)
    return rate, var


def _row(n: float, a: dict, e: dict, v: float) -> list:
    """A record row as in ratings_t20_years.json: [balls, A_runs, E_runs, A_wkt, E_wkt, ..., V_runs]."""
    return [n] + [x for m in METRICS for x in (a[m], e[m])] + [v]


def _add(acc: list | None, row: list) -> list:
    return list(row) if acc is None else [a + b for a, b in zip(acc, row)]


def league_obs(cards: list[dict], truth: dict, base: dict) -> dict:
    """pid -> side -> record row of a played season, from its match cards. truth: pid -> the engine Player who
    played (for his usual phases and as the opposition's level); base: the season's baseline rates."""
    lv: dict = {}

    def lev(pid, side):
        if (pid, side) not in lv:
            lv[pid, side] = level(truth[pid], side)
        return lv[pid, side]

    def opp(rows, side):
        rows = [(r["id"], r["balls"]) for r in rows if r["id"] in truth and r["balls"] > 0]
        n = sum(b for _, b in rows)
        return {m: sum(lev(i, side)[m] * b for i, b in rows) / n if n else 1.0 for m in METRICS}

    out: dict = {}
    for card in cards:
        for inn in card["innings"]:
            batted = [b for b in inn["batting"] if b["batted"]]
            o = {"bat": opp(inn["bowling"], "bowl"), "bowl": opp(batted, "bat")}
            for side, rows in (("bat", batted), ("bowl", inn["bowling"])):
                for r in rows:
                    n = r["balls"]
                    if n <= 0 or r["id"] not in truth:
                        continue
                    if side == "bat":
                        gone = r["out"] and (r.get("how_out") or {}).get("kind") != "run_out"
                        a = {"runs": r["runs"], "wkt": int(gone), "dot": r["dots"], "four": r["fours"],
                             "six": r["sixes"]}
                    else:     # runs off the bat: wides and no-balls have their own indexes
                        a = {"runs": max(0, r["runs"] - r.get("wides", 0) - r.get("noballs", 0)),
                             "wkt": r["wickets"], "dot": r["dots"], "four": r["fours"], "six": r["sixes"]}
                    rate, var = _rates(truth[r["id"]], side, base)
                    e = {m: n * rate[m] * o[side][m] for m in METRICS}
                    d = out.setdefault(r["id"], {})
                    d[side] = _add(d.get(side), _row(n, a, e, n * var * o[side]["runs"]))
    for side in ("bat", "bowl"):           # the league's actual counts add up to its players' true levels
        for j, m in enumerate(METRICS):
            act = sum(d[side][1 + 2 * j] for d in out.values() if side in d)
            want = sum(d[side][2 + 2 * j] * lev(pid, side)[m] for pid, d in out.items() if side in d)
            if act > 0 and want > 0:
                k = act / want
                for d in out.values():
                    if side in d:
                        d[side][2 + 2 * j] *= k
    return out


@lru_cache(maxsize=None)
def _comps() -> dict:
    path = DATA / f"ratings_{FMT}_comps.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"bat": {}, "bowl": {}}


@lru_cache(maxsize=None)
def outside_balls(pid: str, league: str) -> dict:
    """side -> balls a season of real player pid's T20 cricket outside `league`: his real balls in every other
    competition over the years he played, at least MIN_OUTSIDE; 0 for a side he isn't rated on."""
    rec = ratings(FMT)["players"].get(pid) or {}
    out = {}
    for side in ("bat", "bowl"):
        if not (rec.get(side) or {}).get("idx"):
            out[side] = 0
            continue
        years = len(load_years(FMT).get(side, {}).get(pid) or {}) or 1
        other = sum(row[0] for c, row in (_comps().get(side, {}).get(pid) or {}).items() if c != league)
        out[side] = max(MIN_OUTSIDE, round(other / years))
    return out


def outside_obs(p: Player, balls: dict, base: dict, rng: random.Random) -> dict:
    """side -> a made-up record row of `balls[side]` balls of cricket outside the league, drawn from engine Player
    p's level (the season's, with age and form): actual = expected x level + sampling noise."""
    out = {}
    for side in ("bat", "bowl"):
        n = balls.get(side, 0)
        if n <= 0 or not (p.rated_bat if side == "bat" else p.rated_bowl):
            continue
        t = level(p, side)
        rate, var = _rates(p, side, base)
        e = {m: n * rate[m] for m in METRICS}
        v = n * var * t["runs"]
        a = {}
        for m in METRICS:
            mean = e[m] * t[m]
            sd = math.sqrt(v) if m == "runs" else math.sqrt(max(mean * (1 - mean / n), 0.05 * mean))
            a[m] = max(0.0, rng.gauss(mean, sd))
        out[side] = _row(n, a, e, v)
    return out


def accumulate(acc: list | None, row: list, k: list) -> list:
    """Add a season's row to a player's observations, age-adjusted: actual counts x k (per metric, f(typical age) /
    f(age then)), the runs variance x k_runs^2. Rounded for storage."""
    scaled = [row[0]] + [x for j in range(len(METRICS)) for x in (row[1 + 2 * j] * k[j], row[2 + 2 * j])] \
        + [row[-1] * k[0] * k[0]]
    return [round(x, 3) for x in _add(acc, scaled)]
