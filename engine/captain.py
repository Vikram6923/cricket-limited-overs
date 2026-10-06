"""Captaincy (design T0-5): batting order, keeper, toss decision and over-by-over bowling choice.

Tier 0 keeps this deliberately simple: order by usual batting position, and each over goes to the eligible bowler
with the lowest expected cost for that phase, subject to quotas, no consecutive overs, and a feasibility check that
the remaining overs can still be bowled legally. Tier 1 (T1-6/T1-7) replaces this with real plans.
"""
from __future__ import annotations

import json
import math
import random
from functools import lru_cache

from .conditions import venue_key
from .data import DATA, PHASES, Player

ROLE_ORDER = {"top": 2.0, "middle": 4.5, "lower": 6.5, "tail": 9.5}
WICKET_VALUE = {"t20": 9.0, "odi": 22.0}   # rough runs-equivalent of a wicket, for ranking bowlers (T1 refits)


def batting_order(players: list[Player]) -> list[Player]:
    """By usual batting position. More than two openers: the two best keep the top slots, the others drop into
    the middle order (an opener is usually a better No. 4 than a lower-order player)."""
    pos = slot_position
    openers = sorted((p for p in players if p.opener_share >= 0.5), key=batting_value, reverse=True)
    demoted = {p.id for p in openers[2:]}
    return sorted(players, key=lambda p: 4.0 if p.id in demoted else pos(p))


def slot_position(p: Player) -> float:
    """Where this player usually bats, as a number (1 = opener)."""
    if p.position is None:
        return ROLE_ORDER.get(p.bat_role, 6.0)
    # blend the average with the most common slot (Kohli and Ishan Kishan both average 3.2 in ODIs, but
    # Kohli's usual slot is 3 and Kishan's is 4); anchor real openers at the top
    x = 0.5 * p.position + 0.5 * (p.usual_slot or p.position)
    return min(x, 1.8) if p.opener_share >= 0.5 else max(x, 2.6)


def batting_value(p: Player) -> float:
    """Expected runs per dismissal x scoring speed, from the overall-ish (middle-phase) indexes."""
    b = p.bat["middle"]
    return (b["runs"] / max(b["wkt"], 0.2)) * b["runs"]


def player_capacity(p: Player, fmt: str) -> float:
    """Overs a player can be expected to bowl: a genuine bowler a full quota, others ~1.25x their usual overs."""
    from .data import FORMATS
    quota = FORMATS[fmt]["quota"]
    return min(quota, max(p.bowl_overs_per_match * 1.25, quota if p.bowl_overs_per_match >= quota * 0.5 else 0))


def bowling_capacity(team: list[Player], keeper: Player | None, fmt: str) -> float:
    return sum(player_capacity(p, fmt) for p in team if p is not keeper)


def xi_ok(xi: list[Player], squad: list[Player], fmt: str) -> bool:
    """Hard constraints on any XI: a keeper if the squad has one, and enough bowling for the overs."""
    from .data import FORMATS
    keepers = [p for p in xi if p.keeper]
    if any(p.keeper for p in squad) and not keepers:
        return False
    k = max(keepers, key=batting_value) if keepers else None
    # enough bowling for the overs, or as much as this squad can possibly offer
    best = sorted(squad, key=lambda p: -p.bowl_overs_per_match)[:11]
    need = min(FORMATS[fmt]["overs"], bowling_capacity(best, None, fmt))
    return bowling_capacity(xi, k, fmt) >= need - 1e-9


def select_xi(squad: list[Player], fmt: str, base: dict, rng: random.Random | None = None, venue: str | None = None,
              runs_factor: float = 1.0, learned: bool = True, max_overseas: int | None = None) -> list[Player]:
    """Pick the XI from a squad. With a fitted model (data/engine/selection_{fmt}.json, engine/selection.py) the
    choice follows real captains' selections: sampled with `rng` (close calls rotate; the venue's spin help and the
    ground/pitch scoring level shift it), or the most likely XI without one. Otherwise, or if no sampled XI meets
    the hard constraints, the rule below (design T2-9)."""
    if len(squad) <= 11:
        return list(squad)
    if learned:
        from . import selection
        xi = selection.choose(squad, fmt, base, rng, venue, runs_factor, max_overseas)
        if xi:
            return xi
    return rule_xi(squad, fmt, base)


def rule_xi(squad: list[Player], fmt: str, base: dict) -> list[Player]:
    """Hand rule (design T2-9): a keeper, at least five genuine bowling options covering the overs (part-timers
    allowed to fill), and the best batters for the rest."""
    from .data import FORMATS
    if len(squad) <= 11:
        return list(squad)
    overs, quota = FORMATS[fmt]["overs"], FORMATS[fmt]["quota"]
    spec_opm = quota * 0.5        # bowls at least half his quota per match -> a genuine bowling option

    def bowl_val(p):
        return -sum(bowling_cost(p, ph, base[ph], fmt) for ph in PHASES) + (0 if p.rated_bowl else -1.0)

    keepers = [p for p in squad if p.keeper] or squad
    xi = [max(keepers, key=batting_value)]
    pool = [p for p in squad if p not in xi]
    bowlers = sorted((p for p in pool if p.bowl_overs_per_match >= spec_opm), key=bowl_val, reverse=True)
    for p in bowlers[:4]:
        xi.append(p)
    pool = [p for p in pool if p not in xi]
    # fifth bowler: the best all-round option among the rest
    if pool:
        fifth = max(pool, key=lambda p: (p.bowl_overs_per_match >= spec_opm) * 2 +
                    bowl_val(p) * 0.5 + batting_value(p) / max(batting_value(q) for q in squad))
        xi.append(fifth)
        pool.remove(fifth)
    pool.sort(key=batting_value, reverse=True)
    while len(xi) < 11 and pool:
        xi.append(pool.pop(0))

    def capacity(team):
        return sum(min(quota, max(p.bowl_overs_per_match * 1.25, quota if p.bowl_overs_per_match >= spec_opm else 0))
                   for p in team if p is not xi[0])
    # not enough bowling: swap the weakest batter for the best remaining bowler
    spare = sorted((p for p in squad if p not in xi), key=bowl_val, reverse=True)
    while capacity(xi) < overs and spare:
        weakest = min((p for p in xi[1:] if p.bowl_overs_per_match < spec_opm), key=batting_value, default=None)
        if weakest is None:
            break
        xi[xi.index(weakest)] = spare.pop(0)
    return xi


def choose_keeper(players: list[Player]) -> Player:
    ks = [p for p in players if p.keeper]
    if ks:
        return max(ks, key=lambda p: p.bat_balls)
    # nobody flagged: the batter least useful as a bowler
    return min(players, key=lambda p: (p.bowl_balls, -p.bat_balls))


def toss_decision(fmt: str, rng: random.Random, venue: str | None = None) -> str:
    """'bat' or 'bowl' (design T2-5): real captains' base rate of bowling first (data/engine/toss_*.json), shifted
    on the logit scale toward the venue's (shrunk) chasing advantage."""
    t = _toss(fmt)
    p = t.get("p_bowl", 0.6)
    v = t.get("venues", {}).get(venue_key(venue)) if venue else None
    if v is not None:
        z = math.log(p / (1 - p)) + 8.0 * (v - t.get("chase_win", 0.52))
        p = 1 / (1 + math.exp(-z))
    return "bowl" if rng.random() < p else "bat"


@lru_cache(maxsize=None)
def _toss(fmt: str) -> dict:
    path = DATA / "engine" / f"toss_{fmt}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def bowling_cost(p: Player, phase: str, base: dict, fmt: str) -> float:
    """Expected runs conceded per ball minus the value of expected wickets per ball."""
    b = p.bowl[phase]
    runs = base["runs"] * b["runs"] + base["wide"] * p.wide + base["noball"] * p.noball
    wkts = base["wkt"] * b["wkt"]
    return runs - WICKET_VALUE[fmt] * wkts


def feasible(quota_left: dict, overs_left: int, last: Player | None) -> bool:
    """Can `overs_left` overs still be bowled with no bowler bowling consecutive overs?"""
    if overs_left <= 0:
        return True
    cap = math.ceil(overs_left / 2)
    total = sum(min(q, cap) for q in quota_left.values())
    if total < overs_left:
        return False
    # the next over can't be bowled by `last`
    return any(q > 0 for p, q in quota_left.items() if p is not last)


def choose_bowler(fielders: list[Player], keeper: Player, quota_left: dict, overs_left: int, last: Player | None,
                  phase: str, base: dict, fmt: str, rng: random.Random, base_of=None) -> Player:
    """Pick the bowler for the next over. `quota_left` maps every fielder to overs still allowed."""
    cands = [p for p in fielders if p is not last and quota_left[p] > 0]
    if not cands:
        cands = [p for p in fielders if p is not last]   # emergency: quotas exhausted (tiny custom XIs)
    scored = []
    for p in cands:
        c = bowling_cost(p, phase, base_of(p)[phase] if base_of else base, fmt)
        if p is keeper:
            c += 10.0
        if not p.rated_bowl:
            c += 0.3                       # never-bowled players only in an emergency
        c += rng.random() * 0.02           # tiny noise so identical options don't always go the same way
        scored.append((c, p))
    scored.sort(key=lambda t: t[0])
    for c, p in scored:
        q = dict(quota_left)
        q[p] -= 1
        if feasible(q, overs_left - 1, p):
            return p
    return scored[0][1]


@lru_cache(maxsize=2)
def reactive_coef(fmt: str) -> dict | None:
    """Overs gained per run / wicket above expectation (engine/fit/fit_reactive.py)."""
    p = DATA / "engine" / f"reactive_{fmt}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


class BowlingPlan:
    """Whole-innings bowling plan (design T1-6).

    1. Overs per bowler: proportional to how many overs he really bowls per match (his role), nudged by quality,
       capped at the quota, scaled to fill the innings.
    2. Overs per phase: each bowler's real phase usage (Bumrah: powerplay + death; spinners: middle), nudged by his
       phase-specific quality, balanced by iterative proportional fitting so every phase gets exactly its overs.
    3. Sequence: spells from alternating ends (the bowler from two overs ago continues if he has overs left in the
       phase), never two overs in a row, borrowing an over from a later phase if a phase would otherwise jam.
    During the innings the plan is followed unless the planned bowler is unavailable; then the greedy chooser
    steps in.
    """

    QUALITY = 2.0   # how strongly cost moves overs toward better bowlers (exponent on relative cost)

    def __init__(self, fielders: list[Player], keeper: Player, fmt: str, base: dict, max_overs: int,
                 quota: int, rng: random.Random, base_of=None):
        self.fmt = fmt
        from .data import FORMATS
        phases = FORMATS[fmt]["phases"]
        ph_overs = {name: max(0, min(hi, max_overs - 1) - lo + 1) for lo, hi, name in phases if lo < max_overs}
        bowlers = [p for p in fielders if p is not keeper] or list(fielders)
        cost = {p: {ph: bowling_cost(p, ph, (base_of(p) if base_of else base)[ph], fmt) + (0.0 if p.rated_bowl else 0.3)
                    for ph in ph_overs}
                for p in bowlers}
        med = {ph: sorted(c[ph] for c in cost.values())[len(cost) // 2] for ph in ph_overs}

        def rel(p, ph):
            # relative cost, >1 = worse than this XI's median bowler (costs can be negative; shift to stay > 0)
            shift = 1.0 + abs(min(c[ph] for c in cost.values()))
            return (cost[p][ph] + shift) / (med[ph] + shift)

        # 1. overs per bowler
        weight = {p: max(p.bowl_overs_per_match, 0.05 if p.rated_bowl else 0.01) *
                  sum(rel(p, ph) ** -self.QUALITY * ph_overs[ph] for ph in ph_overs) / max_overs for p in bowlers}
        total = max_overs
        lo_f, hi_f = 0.0, 1000.0
        for _ in range(60):
            f = (lo_f + hi_f) / 2
            if sum(min(quota, weight[p] * f) for p in bowlers) < total:
                lo_f = f
            else:
                hi_f = f
        want = {p: min(quota, weight[p] * hi_f) for p in bowlers}
        n = {p: int(want[p]) for p in bowlers}
        for p in sorted(bowlers, key=lambda p: -(want[p] - n[p])):
            if sum(n.values()) >= total:
                break
            if n[p] < quota:
                n[p] += 1
        while sum(n.values()) < total:          # not enough bowling: stretch anyone with quota left
            p = min((p for p in bowlers if n[p] < quota), key=lambda p: sum(cost[p].values()), default=None)
            if p is None:
                break
            n[p] += 1

        # 2. overs per phase (IPF on seed = real usage x quality)
        seed = {p: {ph: (p.bowl_phase_share.get(ph, 1 / 3) + 0.02) * rel(p, ph) ** -self.QUALITY
                    for ph in ph_overs} for p in bowlers}
        x = {p: dict(seed[p]) for p in bowlers}
        for _ in range(30):                       # converges in well under 30 rounds
            for p in bowlers:
                s = sum(x[p].values())
                for ph in ph_overs:
                    x[p][ph] *= (n[p] / s) if s else 0
            for ph in ph_overs:
                s = sum(x[p][ph] for p in bowlers)
                for p in bowlers:
                    x[p][ph] *= (ph_overs[ph] / s) if s else 0
        alloc = {p: {ph: int(x[p][ph]) for ph in ph_overs} for p in bowlers}
        cap = {ph: math.ceil(ph_overs[ph] / 2) + 1 for ph in ph_overs}
        cells = sorted(((x[p][ph] - alloc[p][ph], p, ph) for p in bowlers for ph in ph_overs), key=lambda t: -t[0])
        for _ in range(3):
            for frac, p, ph in cells:
                row = n[p] - sum(alloc[p].values())
                col = ph_overs[ph] - sum(alloc[q][ph] for q in bowlers)
                if row > 0 and col > 0 and alloc[p][ph] < cap[ph]:
                    alloc[p][ph] += 1
        for ph in ph_overs:                       # anything still unfilled: cheapest bowler with quota left
            while sum(alloc[q][ph] for q in bowlers) < ph_overs[ph]:
                spare = [p for p in bowlers if sum(alloc[p].values()) < quota]
                if not spare:
                    break
                alloc[min(spare, key=lambda p: cost[p][ph])][ph] += 1

        # 3. sequence into spells
        self.seq: list[Player | None] = []
        rem = {p: dict(alloc[p]) for p in bowlers}
        order = [name for lo, hi, name in phases if name in ph_overs]
        for ph in order:
            for _ in range(ph_overs[ph]):
                last = self.seq[-1] if self.seq else None
                prev2 = self.seq[-2] if len(self.seq) >= 2 else None
                avail = [p for p in bowlers if rem[p][ph] > 0 and p is not last]
                if not avail:
                    # jam: borrow an over from a later phase for someone else
                    later = [q for q in order[order.index(ph) + 1:]]
                    donors = [p for p in bowlers if p is not last and any(rem[p][q] > 0 for q in later)]
                    if donors and last is not None and rem[last][ph] > 0:
                        d = max(donors, key=lambda p: sum(rem[p][q] for q in later))
                        q = next(q for q in later if rem[d][q] > 0)
                        rem[d][q] -= 1
                        rem[d][ph] += 1
                        rem[last][ph] -= 1
                        rem[last][q] += 1
                        avail = [d]
                if not avail:
                    self.seq.append(None)
                    continue
                if prev2 in avail:
                    pick = prev2                  # continue the spell from this end
                else:
                    pick = max(avail, key=lambda p: (rem[p][ph], -cost[p][ph] + rng.random() * 1e-3))
                rem[pick][ph] -= 1
                self.seq.append(pick)
        self.alloc = alloc

    def bowler_for(self, over: int, last: Player | None, quota_left: dict) -> Player | None:
        if over < len(self.seq):
            p = self.seq[over]
            if p is not None and p is not last and quota_left.get(p, 0) > 0:
                return p
        return None


def super_over_picks(players: list[Player], base: dict, fmt: str) -> tuple[list[Player], Player]:
    """Three batters with the highest death-overs run rate, and the best death bowler."""
    bats = sorted(players, key=lambda p: -(p.bat["death"]["runs"] * (1.0 + p.bat["death"]["six"]) /
                                           max(p.bat["death"]["wkt"], 0.3)))[:3]
    bowler = min(players, key=lambda p: bowling_cost(p, "death", base, fmt) + (0 if p.rated_bowl else 1))
    return bats, bowler
