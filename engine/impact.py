"""IPL Impact Player rule (2023 onwards): one substitute per side, chosen by team value.

Real use (Cricsheet IPL 2023-26, 556 substitutions): batting first, most sides bring in a bowler at the start of
their bowling innings in place of a batter who has batted; chasing, nearly all bring in a batter; about a quarter
of the sides batting first use it during their innings (a batter, after a wicket).

Decisions are made on **team** value, not player value (valuing each player against an average bowler made a
below-average bowling all-rounder look worse than a batter who doesn't bowl, so Stoinis was dropped for Ferguson):
- attack value: the best 20 (50) overs the side can bowl, each bowler up to his quota and his usual capacity
  (captain.player_capacity), valued in runs per over against average;
- batting value: the side's batters by quality, each given the balls his position faces in real matches.
Dropping a batter who has already batted then costs nothing; dropping an all-rounder costs his overs.

- Innings break: the side that batted swaps for the biggest attack gain; the chasing side for the biggest batting
  gain. No swap unless it gains.
- During the first innings (batting side, at the fall of a wicket): bring in the best bench batter in place of a
  dismissed batter if the runs he is expected to add now beat the attack gain the side would get at the break.
Keeper stays; the overseas limit holds; the replaced player takes no further part.
"""
from __future__ import annotations

import math

from .data import FORMATS, PHASES, Player

UNFILLED = -3.0   # runs per over below average for overs the side can't cover with real bowlers
MID_GAIN_SCALE = 0.2   # fitted: sides batting first then swap mid-innings 25% of the time, as real IPL sides do (2023-26)


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


def attack_value(players: list[Player], keeper: Player | None, fmt: str, base: dict) -> float:
    from .captain import player_capacity
    overs = FORMATS[fmt]["overs"]
    rows = sorted(((6 * per_ball(p, fmt, base, "bowl"), player_capacity(p, fmt)) for p in players if p is not keeper),
                  reverse=True)
    v, left = 0.0, overs
    for rate, cap in rows:
        take = min(cap, left)
        if take <= 0:
            continue
        v += take * rate
        left -= take
    return v + left * UNFILLED


def batting_value(players: list[Player], fmt: str, base: dict, slot_balls: list[float]) -> float:
    vals = sorted((per_ball(p, fmt, base, "bat") for p in players), reverse=True)
    return sum(v * slot_balls[min(k, len(slot_balls) - 1)] for k, v in enumerate(vals))


def _allowed(team, out: Player, inn: Player) -> bool:
    if team.max_overseas is None or not inn.overseas:
        return True
    return sum(1 for p in team.players if p.overseas) - out.overseas < team.max_overseas


def batting_first_xi(team, fmt: str, base: dict, slot_balls: list[float]) -> None:
    """Impact Player matches, side batting first: like real sides, start with an extra batter in place of a
    specialist bowler, and bring the bowler in at the break - only if a bench bowler is there to come in.
    This is XI selection (no substitution is used)."""
    from .captain import batting_order, player_capacity
    quota = FORMATS[fmt]["quota"]
    bowlers = [p for p in team.bench if player_capacity(p, fmt) >= quota]
    best = best_break_swap(team, "bat", fmt, base, slot_balls,
                           out_ok=lambda p: player_capacity(p, fmt) >= quota)
    if not best or not bowlers:
        return
    _, out, inn = best
    if all(b is inn for b in bowlers):
        return
    team.players = [inn if p is out else p for p in team.players]
    team.bench = [out if p is inn else p for p in team.bench]
    team.order = batting_order(team.players) if not team.fixed_order else [inn if p is out else p for p in team.order]


def best_break_swap(team, need: str, fmt: str, base: dict, slot_balls: list[float], out_ok=None):
    """(gain, out, in) for the biggest team-value gain in `need` ("bowl" or "bat"), or None."""
    def value(ps):
        return attack_value(ps, team.keeper, fmt, base) if need == "bowl" else batting_value(ps, fmt, base, slot_balls)
    from .captain import player_capacity
    now = value(team.players)
    best, best_key = None, None
    for out in team.players:
        if out is team.keeper or (out_ok and not out_ok(out)):
            continue
        rest = [p for p in team.players if p is not out]
        # ties (e.g. the new bowler's overs push out the weakest bowler's whether he is dropped or not) go to
        # dropping the player who offers least in the other discipline - a batter who has batted before a bowler
        spare = player_capacity(out, fmt) if need == "bowl" else per_ball(out, fmt, base, "bat")
        for inn in team.bench:
            if not _allowed(team, out, inn):
                continue
            gain = value(rest + [inn]) - now
            key = (round(gain, 2), -spare)
            if gain > 1e-6 and (best_key is None or key > best_key):
                best, best_key = (gain, out, inn), key
    return best


def mid_innings_swap(team, cards: list, next_in: int, balls_left: int, fmt: str, base: dict, slot_balls: list[float]):
    """At the fall of a wicket in the first innings: (out, in) if bringing in a batter now beats the attack gain
    available at the break, else None. out = a dismissed batter whose loss costs the attack least."""
    dismissed = [c.p for c in cards if c.out and c.p is not team.keeper]
    if not dismissed or not team.bench or next_in >= len(slot_balls):
        return None
    # expected balls for the next batter: his position's share of the balls left (real matches)
    share = slot_balls[next_in] / max(sum(slot_balls[next_in:]), 1e-9)
    nxt = cards[next_in].p if next_in < len(cards) else None
    base_rate = per_ball(nxt, fmt, base, "bat") if nxt else -0.5
    att_now = attack_value(team.players, team.keeper, fmt, base)
    later = best_break_swap(team, "bowl", fmt, base, slot_balls)
    opportunity = later[0] if later else 0.0
    best = None
    for out in dismissed:
        loss = att_now - attack_value([p for p in team.players if p is not out], team.keeper, fmt, base)
        for inn in team.bench:
            if not _allowed(team, out, inn):
                continue
            gain = MID_GAIN_SCALE * (per_ball(inn, fmt, base, "bat") - base_rate) * balls_left * share - loss
            if gain > opportunity and (best is None or gain > best[0]):
                best = (gain, out, inn)
    return best and best[1:]
