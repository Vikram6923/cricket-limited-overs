"""IPL Impact Player rule (2023 onwards), used **rationally**: one substitute per side, any time, chosen by value.

Real sides don't use it optimally (mostly a bowler in after batting first, a batter in for the chase, a batter
mid-innings only late in a collapse), so their habits are not copied. Every decision compares, in runs, what the
team gains by using the substitute now with what it keeps by waiting:

- attack value: the best overs the side can still bowl, each bowler up to his quota left and his usual capacity
  (captain.player_capacity), in runs per over against average; overs nobody can cover cost UNFILLED;
- batting value: the side's batters still to come, each given the balls a batter in that place still faces from
  this state (data/engine/impact_t20.json, real IPL innings: after the 6th wicket with 5 overs left the next man
  faces ~9 balls, No. 11 almost none); before an innings, the balls each batting position faces.

Decision points and the options a rational side has:
1. XI after the toss (sides name their XI and 5 substitutes after the toss). Compare the selected XI, the XI with
   an extra batter and the XI with an extra bowler, each valued together with the best use of the substitute it
   leaves. Batting first that is valued over real first-innings wicket timelines (the scenarios) with rule 2:
   e.g. start with the bowlers and bring in a batter only if wickets fall early, else a bowler at the break.
2. Batting, at the fall of a wicket: bring in a batter for a dismissed player (or one not needed) if the runs he
   adds from this state, net of any bowling lost, beat the bowling gain still available at the break.
3. Bowling first, at the end of an over: bring in a bowler for a bowler who has bowled out (or anyone) if the
   better remaining overs, net of any batting lost for the chase, beat the batting gain available at the break.
4. Innings break: the side that batted takes the biggest attack gain (dropping a batter who has batted costs
   nothing - including a batter who was not needed); the chasing side the biggest batting gain (dropping a bowler
   who has bowled out costs nothing).
Keeper stays; the overseas limit holds; the replaced player takes no further part.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .data import FORMATS, PHASES, Player

UNFILLED = -3.0   # runs per over below average for overs the side can't cover with real bowlers
N_SUBS = 5        # substitutes named at the toss
N_SCEN = 80       # scenarios used to value an XI
TABLE = Path(__file__).resolve().parent.parent / "data" / "engine" / "impact_t20.json"


@lru_cache(maxsize=1)
def _table() -> dict:
    return json.loads(TABLE.read_text(encoding="utf-8")) if TABLE.exists() else {"balls_next": {}, "scenarios": []}


@lru_cache(maxsize=4096)
def balls_next(w: int, balls_left: int, n: int) -> tuple:
    """Expected balls for the next n batters after the w-th wicket with balls_left left (pooled over nearby
    overs until 30 real innings support it)."""
    t = _table()["balls_next"]
    ol = -(-balls_left // 6)
    s, cnt = [0.0] * 11, 0
    for spread in range(20):
        s, cnt = [0.0] * 11, 0
        for o in range(ol - spread, ol + spread + 1):
            c = t.get(f"{w},{o}")
            if c:
                for j, x in enumerate(c["sum"]):
                    s[j] += x
                cnt += c["n"]
        if cnt >= 30:
            break
    return tuple((s[j] / cnt if cnt and j < 11 else 0.0) for j in range(n))


@lru_cache(maxsize=4096)
def continuations(w: int, at: int, window: int = 9) -> tuple:
    """How real innings went on after their w-th wicket fell near ball `at`: for each, the later wickets as
    (wickets down, ball), shifted to start from `at`."""
    out = []
    for wk in _table()["scenarios"]:
        if len(wk) >= w and abs(wk[w - 1] - at) <= window:
            out.append(tuple((k + 1, at + wk[k] - wk[w - 1]) for k in range(w, len(wk))))
    return tuple(out)


def per_ball(p: Player, fmt: str, base: dict, side: str) -> float:
    """Runs value per ball faced (bat) or bowled (bowl) relative to average, over his usual phases."""
    from .captain import WICKET_VALUE
    dv = WICKET_VALUE[fmt]
    shares = (p.bat_phase_share if side == "bat" else p.bowl_phase_share) or {ph: 1 / 3 for ph in PHASES}
    v = 0.0
    for ph in PHASES:
        b0, ix = base[ph], getattr(p, side)[ph]
        if side == "bat":
            v += shares.get(ph, 0) * (b0["runs"] * (ix["runs"] - 1) - b0["wkt"] * (ix["wkt"] - 1) * dv)
        else:
            v += shares.get(ph, 0) * (b0["runs"] * (1 - ix["runs"]) + b0["wkt"] * (ix["wkt"] - 1) * dv)
    return v


class Values:
    """Per-ball batting and per-over bowling values, cached for one team in one match."""

    def __init__(self, fmt: str, base: dict):
        self.fmt, self.base, self._bat, self._bowl = fmt, base, {}, {}

    # keyed by id(): Player's own __hash__ is slow in these loops
    def bat(self, p: Player) -> float:
        v = self._bat.get(id(p))
        if v is None:
            v = self._bat[id(p)] = per_ball(p, self.fmt, self.base, "bat")
        return v

    def bowl(self, p: Player) -> float:
        v = self._bowl.get(id(p))
        if v is None:
            v = self._bowl[id(p)] = 6 * per_ball(p, self.fmt, self.base, "bowl")
        return v


def _vals(team, fmt: str, base: dict) -> Values:
    v = getattr(team, "_impact_values", None)
    if v is None:
        v = team._impact_values = Values(fmt, base)
    return v


def attack_value(players: list[Player], keeper: Player | None, fmt: str, base: dict, cap: dict | None = None,
                 overs: int | None = None, vals: Values | None = None) -> float:
    """Runs value of the best `overs` the side can bowl; `cap` = overs each can still bowl (default: his usual)."""
    from .captain import player_capacity
    vals = vals or Values(fmt, base)
    left = FORMATS[fmt]["overs"] if overs is None else overs
    rows = sorted(((vals.bowl(p), cap[p] if cap is not None else player_capacity(p, fmt))
                   for p in players if p is not keeper), key=lambda r: -r[0])
    v = 0.0
    for rate, c in rows:
        take = min(c, left)
        if take > 0:
            v += take * rate
            left -= take
    return v + left * UNFILLED


def _fill(rows: list, left: float) -> float:
    """attack_value on rows (rate, overs available, player) already sorted best first."""
    v = 0.0
    for rate, c, _ in rows:
        take = min(c, left)
        if take > 0:
            v += take * rate
            left -= take
    return v + left * UNFILLED


def batting_value(players: list[Player], fmt: str, base: dict, slot_balls: list[float],
                  vals: Values | None = None) -> float:
    vals = vals or Values(fmt, base)
    vs = sorted((vals.bat(p) for p in players), reverse=True)
    return sum(v * slot_balls[min(k, len(slot_balls) - 1)] for k, v in enumerate(vs))


def _allowed(players: list[Player], max_overseas: int | None, out: Player, inn: Player) -> bool:
    if max_overseas is None or not inn.overseas:
        return True
    return sum(1 for p in players if p.overseas) - out.overseas < max_overseas


def _insert(rem: list[Player], inn: Player, vals: Values) -> int:
    """Where a substitute batter goes in the order still to come: ahead of the first weaker batter."""
    v = vals.bat(inn)
    return next((i for i, p in enumerate(rem) if vals.bat(p) < v), len(rem))


def _rem_value(rem: list[Player], balls: tuple, vals: Values) -> float:
    return sum(vals.bat(p) * b for p, b in zip(rem, balls))


# ───────────────────────── innings break ─────────────────────────
def best_break_swap(team, need: str, fmt: str, base: dict, slot_balls: list[float]):
    """(gain, out, in) for the biggest team-value gain in `need` ("bowl" or "bat"), or None."""
    from .captain import player_capacity
    vals = _vals(team, fmt, base)
    key = (need, tuple(id(p) for p in team.players + team.bench))
    cache = team.__dict__.setdefault("_break_cache", {})
    if key in cache:
        return cache[key]

    def value(ps):
        return (attack_value(ps, team.keeper, fmt, base, vals=vals) if need == "bowl"
                else batting_value(ps, fmt, base, slot_balls, vals))
    now = value(team.players)
    best, best_key = None, None
    for out in team.players:
        if out is team.keeper:
            continue
        rest = [p for p in team.players if p is not out]
        # ties (the new bowler's overs push out the weakest bowler's whether he is dropped or not) go to dropping
        # the player who offers least in the other discipline - a batter who has batted before a bowler
        spare = player_capacity(out, fmt) if need == "bowl" else vals.bat(out)
        for inn in team.bench:
            if not _allowed(team.players, team.max_overseas, out, inn):
                continue
            gain = value(rest + [inn]) - now
            k2 = (round(gain, 2), -spare)
            if gain > 1e-6 and (best_key is None or k2 > best_key):
                best, best_key = (gain, out, inn), k2
    cache[key] = best
    return best


# ───────────────────────── XI after the toss ─────────────────────────
def name_subs(team, fmt: str, base: dict) -> list[Player]:
    """The substitutes named at the toss: the best bench batters and bowlers, alternately."""
    from .captain import player_capacity
    vals = _vals(team, fmt, base)
    bats = sorted(team.bench, key=lambda p: -vals.bat(p))
    bowls = sorted((p for p in team.bench if player_capacity(p, fmt) >= 2), key=lambda p: -vals.bowl(p))
    subs: list[Player] = []
    for p in [x for pair in zip(bats, bowls) for x in pair] + bats:
        if p not in subs:
            subs.append(p)
        if len(subs) == N_SUBS:
            break
    return subs


def _first_innings_option(xi: list[Player], team, fmt: str, base: dict, vals: Values, brk: float,
                          scen: list) -> float:
    """Expected gain from the substitute when batting first, over real wicket timelines: a batter in at a wicket
    (rule 2, for a dismissed player) if that beats the bowler at the break, else the bowler at the break."""
    att = attack_value(xi, team.keeper, fmt, base, vals=vals)
    lineup = sorted(xi, key=lambda p: -vals.bat(p))
    delta = {}
    for d in xi:
        if d is team.keeper:
            continue
        rest = [p for p in xi if p is not d]
        for inn in team.bench:
            if _allowed(xi, team.max_overseas, d, inn):
                delta[d, inn] = attack_value(rest + [inn], team.keeper, fmt, base, vals=vals) - att
    by_inn: dict = {}
    for (d, inn), v in delta.items():
        by_inn.setdefault(inn, []).append((d, v))
    for rows in by_inn.values():
        rows.sort(key=lambda r: -r[1])          # the dismissed player whose loss costs least, first
    balls_total = FORMATS[fmt]["overs"] * 6
    total = 0.0
    for wk in scen:
        g = brk
        for w, at in enumerate(wk, start=1):
            left = balls_total - at
            if w >= 10 or left <= 0:
                break
            rem, gone = lineup[w + 1:], set(lineup[:w])
            balls = balls_next(w, left, len(rem))
            now = _rem_value(rem, balls, vals)
            best = None
            for inn, rows in by_inn.items():
                da = next((v for d, v in rows if d in gone), None)
                if da is None:
                    continue
                r = list(rem)
                r.insert(_insert(r, inn, vals), inn)
                gain = _rem_value(r, balls, vals) - now + da
                best = gain if best is None or gain > best else best
            if best is not None and best > brk:
                g = best
                break
        total += g
    return total / max(len(scen), 1)


def choose_xi(team, batting_first: bool, fmt: str, base: dict, slot_balls: list[float]) -> None:
    """After the toss: pick the XI (the selected one, or one swap with the bench) and name the substitutes,
    valuing each XI together with the best use of the substitute it leaves (module docstring, rule 1)."""
    from .captain import batting_order, player_capacity
    vals = _vals(team, fmt, base)
    bench_all = list(team.bench)
    scen = _table()["scenarios"]
    scen = scen[:: max(1, len(scen) // N_SCEN)][:N_SCEN]
    xi0 = list(team.players)
    bat_in = sorted(bench_all, key=lambda p: -vals.bat(p))[:1]
    bowl_in = sorted((p for p in bench_all if player_capacity(p, fmt) >= 2), key=lambda p: -vals.bowl(p))[:1]
    cands = [(xi0, None, None)]
    for inn in bat_in + bowl_in:            # extra batter / extra bowler: drop whoever costs least
        best = None
        for out in xi0:
            if out is team.keeper or not _allowed(xi0, team.max_overseas, out, inn):
                continue
            xi = [inn if p is out else p for p in xi0]
            v = attack_value(xi, team.keeper, fmt, base, vals=vals) + batting_value(xi, fmt, base, slot_balls, vals)
            if best is None or v > best[0]:
                best = (v, (xi, out, inn))
        if best:
            cands.append(best[1])

    def setup(xi):
        team.players = xi
        team.bench = [p for p in bench_all if p not in xi]
        team.bench = name_subs(team, fmt, base)

    def plan_value(xi):
        setup(xi)
        v = attack_value(xi, team.keeper, fmt, base, vals=vals) + batting_value(xi, fmt, base, slot_balls, vals)
        brk = best_break_swap(team, "bowl" if batting_first else "bat", fmt, base, slot_balls)
        brk = brk[0] if brk else 0.0
        return v + (_first_innings_option(xi, team, fmt, base, vals, brk, scen) if batting_first else brk)

    vs = [plan_value(c[0]) for c in cands]
    k = max(range(len(cands)), key=lambda i: (round(vs[i], 6), -i))   # ties: keep the selected XI
    xi, out, inn = cands[k]
    setup(xi)
    if out is not None:
        team.order = [inn if p is out else p for p in team.order] if team.fixed_order else batting_order(xi)


# ───────────────────────── in play ─────────────────────────
def _best_now(team, gone: list, rem: list, w: int, balls_left: int, fmt: str, base: dict, vals: Values,
              att_now: float, outs=None):
    """Best substitution at the fall of the w-th wicket: (gain, out, in, index, "bat"|"bowl") or None."""
    balls = balls_next(w, balls_left, len(rem))
    now_bat = _rem_value(rem, balls, vals)
    key = tuple(id(p) for p in team.players + team.bench)
    if getattr(team, "_att_delta_key", None) != key:     # bowling change from each swap, while the XI is unchanged
        team._att_delta, team._att_delta_key = {}, key
    cache = team._att_delta
    best = None
    for out in (outs if outs is not None else gone + rem):
        if out is team.keeper:
            continue
        r0 = [p for p in rem if p is not out]
        for inn in team.bench:
            if not _allowed(team.players, team.max_overseas, out, inn):
                continue
            r = list(r0)
            i = _insert(r, inn, vals)
            r.insert(i, inn)
            bat = _rem_value(r, balls, vals) - now_bat
            att = cache.get((id(out), id(inn)))
            if att is None:
                att = cache[id(out), id(inn)] = attack_value([p for p in team.players if p is not out] + [inn],
                                                             team.keeper, fmt, base, vals=vals) - att_now
            gain = bat + att
            if best is None or gain > best[0]:
                best = (gain, out, inn, i, "bat" if bat >= att else "bowl")
    return best


def wait_value(team, gone: list, rem: list, w: int, at: int, fmt: str, base: dict, brk: float) -> float:
    """What keeping the substitute is worth after the w-th wicket at ball `at` of the first innings: over real
    innings that were in the same place, the later wicket at which bringing in a batter first beats the bowler
    at the break, else the bowler at the break (the batters still to come are taken to be out in order)."""
    vals = _vals(team, fmt, base)
    att_now = attack_value(team.players, team.keeper, fmt, base, vals=vals)
    total = FORMATS[fmt]["overs"] * 6
    conts = continuations(w, at)
    if not conts:
        return brk
    v = 0.0
    for later in conts:
        g = brk
        for w2, at2 in later:
            if w2 >= 10 or at2 >= total:
                break
            k = w2 - w
            b = _best_now(team, gone + rem[:k], rem[k:], w2, total - at2, fmt, base, vals, att_now,
                          outs=[p for p in gone + rem[:k] if p is not team.keeper])
            if b and b[0] > brk:
                g = b[0]
                break
        v += g
    return v / len(conts)


def batting_swap(team, cards: list, next_in: int, w: int, at: int, fmt: str, base: dict, brk: float | None):
    """At the fall of the w-th wicket, ball `at` (rule 2): (gain, out, in, index in the order still to come,
    "bat"|"bowl" = where most of the gain comes from) or None. brk = the bowling gain still available at the
    break in the first innings (waiting is then worth wait_value), None in the chase (waiting is worth nothing)."""
    vals = _vals(team, fmt, base)
    rem = [c.p for c in cards[next_in:]]
    gone = [c.p for c in cards[:next_in] if c.out]
    att_now = attack_value(team.players, team.keeper, fmt, base, vals=vals)
    best = _best_now(team, gone, rem, w, FORMATS[fmt]["overs"] * 6 - at, fmt, base, vals, att_now)
    if not best or best[0] <= 1e-6:
        return None
    if brk is not None and best[0] <= wait_value(team, gone, rem, w, at, fmt, base, brk):
        return None
    return best


def bowling_swap(team, quota_left: dict, overs_left: int, fmt: str, base: dict, slot_balls: list[float],
                 keep: float):
    """Bowling first, at the end of an over (rule 3): (gain, out, in, "bowl"|"bat") or None. keep = the batting gain available
    for the chase at the break."""
    from .captain import player_capacity
    vals = _vals(team, fmt, base)
    quota = FORMATS[fmt]["quota"]

    def cap(p):
        ql = quota_left.get(p, quota)
        return max(0.0, min(ql, player_capacity(p, fmt) - (quota - ql)))
    caps = {p: cap(p) for p in team.players + team.bench}
    rows = sorted(((vals.bowl(p), caps[p], p) for p in team.players if p is not team.keeper), key=lambda r: -r[0])
    att_now = _fill(rows, overs_left)
    key = tuple(id(p) for p in team.players + team.bench)
    if getattr(team, "_bat_delta_key", None) != key:
        bat_now = batting_value(team.players, fmt, base, slot_balls, vals)
        team._bat_delta = {(out, inn): batting_value([p for p in team.players if p is not out] + [inn], fmt, base,
                                                      slot_balls, vals) - bat_now
                           for out in team.players for inn in team.bench}
        team._bat_delta_key = key
    best = None
    for out in team.players:
        if out is team.keeper:
            continue
        rest = [r for r in rows if r[2] is not out]
        for inn in team.bench:
            if not _allowed(team.players, team.max_overseas, out, inn):
                continue
            r_in = (vals.bowl(inn), caps[inn], inn)
            k = next((i for i, r in enumerate(rest) if r[0] < r_in[0]), len(rest))
            att = _fill(rest[:k] + [r_in] + rest[k:], overs_left) - att_now
            gain = att + team._bat_delta[out, inn]
            if gain > max(keep, 1e-6) and (best is None or gain > best[0]):
                best = (gain, out, inn, "bowl" if att >= team._bat_delta[out, inn] else "bat")
    return best
