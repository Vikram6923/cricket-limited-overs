"""Test captaincy (docs/test_match_plan.md section 4): batting order, XI from a squad, the toss, declarations,
the follow-on, bowling by spells from two ends, the nightwatchman.

Computer captains copy real captains: every probability here comes from engine/fit/fit_test_captain.py
(data/engine/test_captain.json). What is not fitted is a named constant below with its reason, and is listed in
docs/test_design.md.
"""
from __future__ import annotations

import bisect
import json
import math
import random
from collections import defaultdict
from functools import lru_cache

from .captain import slot_position
from .data import DATA, Player

# Not fitted (Cricsheet has no days, so none of these can be):
NIGHTWATCH_OVERS = 6        # a wicket this close to stumps brings a nightwatchman (the plan's rule)
NIGHTWATCH_TOP = 6          # ... if the next man in is one of the top six
NEW_BALL_OVERS = 80         # the new ball is available, and taken at once (the fits assume over 80 too)
# Law 14.1: the lead needed to enforce the follow-on, by the length of the match in days
FOLLOW_ON_LEAD = {1: 75, 2: 100, 3: 150, 4: 150}
RR_CAP = 8.0                # cap on "runs an over the other side would need" as a model feature


# ------------------------------------------------------------------------- model features (the fit imports these)
def declare_x(innings: int, runs: int, lead: int, wkts: int, left: int, nineties: bool) -> list:
    if innings == 1:
        return [1.0, runs / 100, wkts / 10, left / 100, float(nineties)]
    if innings == 2:
        return [1.0, lead / 100, runs / 100, wkts / 10, left / 100, float(nineties)]
    return [1.0, lead / 100, left / 100, min(max(lead, 0) / max(left, 1), RR_CAP), wkts / 10, float(nineties)]


def follow_x(lead: int, left: int, overs_bowled: float) -> list:
    return [1.0, (lead - 200) / 100, left / 100, overs_bowled / 100]


def spell_x(runs_excess: float, wkts_excess: float, innings_overs: int) -> list:
    return [1.0, runs_excess / 10, wkts_excess, innings_overs / 10]


@lru_cache(maxsize=None)
def tables() -> dict:
    return json.loads((DATA / "engine" / "test_captain.json").read_text(encoding="utf-8"))


def _sigmoid(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))


def _logit(p: float) -> float:
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


# ---------------------------------------------------------------------------------------------- the side
def group(p: Player) -> str:
    """'pace' | 'spin' (specialist bowlers) | 'part' (everyone else), as the fits group bowlers."""
    if not (p.bowl_role or "").startswith("spec"):
        return "part"
    return "spin" if p.bowl_type == "spin" else "pace"


def batting_value(p: Player) -> float:
    """Runs per dismissal, as an index (Tests: how long he stays matters, not how fast he scores)."""
    b = p.bat["all"]
    return b["runs"] / max(b["wkt"], 0.2)


def bowling_value(p: Player) -> float:
    """Wickets per run conceded, as an index (higher is better); a man who never bowls is worth nothing."""
    b = p.bowl["all"]
    return (b["wkt"] / max(b["runs"], 0.2)) if p.rated_bowl else 0.0


def batting_order(players: list[Player]) -> list[Player]:
    """By usual Test batting position. More than two openers: the two best open, the others drop to No. 4."""
    openers = sorted((p for p in players if p.opener_share >= 0.5), key=batting_value, reverse=True)
    demoted = {p.id for p in openers[2:]}
    return sorted(players, key=lambda p: 4.0 if p.id in demoted else slot_position(p))


def select_xi(squad: list[Player]) -> list[Player]:
    """XI from a squad by rule (the learned selection model is deferred): the best-batting keeper, the four best
    specialist bowlers with a spinner among them if the squad has one, then the six best batters of the rest."""
    if len(squad) <= 11:
        return list(squad)
    keepers = [p for p in squad if p.keeper]
    xi = [max(keepers, key=batting_value)] if keepers else []
    spec = sorted((p for p in squad if p not in xi and group(p) != "part"), key=bowling_value, reverse=True)
    bowlers = spec[:4]
    spinners = [p for p in spec if group(p) == "spin"]
    if spinners and not any(group(p) == "spin" for p in bowlers):
        bowlers = spec[:3] + spinners[:1]
    xi += bowlers
    rest = sorted((p for p in squad if p not in xi), key=batting_value, reverse=True)
    return xi + rest[:11 - len(xi)]


def toss_decision(rng: random.Random) -> str:
    return "bat" if rng.random() < tables()["toss"]["p_bat"] else "bowl"


# ---------------------------------------------------------------------------------------------- declarations
def declare_prob(innings: int, runs: int, lead: int, wkts: int, left: int, nineties: bool) -> float:
    """Chance that the batting captain declares at the end of this over. left: overs left in the match."""
    d = tables()["declare"].get(str(innings))
    if not d or wkts >= 10 or (runs if innings == 1 else lead) < d["floor"]:
        return 0.0
    return _sigmoid(sum(c * x for c, x in zip(d["coef"], declare_x(innings, runs, lead, wkts, left, nineties))))


def follow_on_lead(days: int) -> int:
    return FOLLOW_ON_LEAD.get(days, tables()["follow_on"]["lead"])


def follow_on_prob(lead: int, left: int, overs_bowled: float, days: int = 5) -> float:
    """Chance of enforcing the follow-on with this lead. The fit is on five-day Tests (a lead of 200 or more);
    a shorter match is read as the same distance past its own mark."""
    f = tables()["follow_on"]
    mark = follow_on_lead(days)
    if lead < mark:
        return 0.0
    return _sigmoid(sum(c * x for c, x in zip(f["coef"], follow_x(lead - mark + f["lead"], left, overs_bowled))))


# ---------------------------------------------------------------------------------------------- bowling
class Bowling:
    """Who bowls each over of one innings: two ends, a spell at each. After an over the bowler at that end goes
    on with the fitted chance for his kind, the length of his spell, his figures in it against what his ratings
    predicted and whether the new ball is due; otherwise the captain picks from the others by the fitted weights
    (career overs per match x kind by ball age x kind by pitch wear x rest). Nobody bowls two overs running."""

    def __init__(self, fielders: list[Player], keeper: Player | None, rng: random.Random):
        self.t = t = tables()
        self.rng = rng
        self.cands = [p for p in fielders if p is not keeper] or list(fielders)
        self.grp = {p: group(p) for p in self.cands}
        c = t["choice"]
        self.w0 = {p: max(p.bowl_overs_per_match, c["opm_floor"]) *
                   c["opm"][bisect.bisect_right(c["opm_edges"], p.bowl_overs_per_match)] for p in self.cands}
        self.ends: list = [None, None]         # per end: [bowler, overs, runs - expected, wickets - expected]
        self.prev: Player | None = None        # bowled the last over
        self.last: dict = {}                   # bowler -> the over he last bowled
        self.overs: dict = defaultdict(int)    # bowler -> overs this innings

    def new_day(self) -> None:
        """Overnight: both spells are over and everyone who has bowled is rested."""
        self.ends = [None, None]
        for p in self.last:
            self.last[p] = -10 ** 6

    def pick(self, n: int, age: int, wear: int, due: bool, sit_t: dict) -> Player:
        """The bowler of over n (0-based) of the innings. age: overs since the ball was new; wear: overs bowled
        in the match; due: the new ball has just been taken; sit_t: the situation tables (for their edges)."""
        sp = self.ends[n % 2]
        if sp is not None and sp[0] is not self.prev:
            g = self.t["spell"]["groups"][self.grp[sp[0]]]
            row = g["continue"]["due" if due else "normal"]
            z = _logit(row[bisect.bisect_right(self.t["spell"]["len_edges"], sp[1])])
            z += sum(c * x for c, x in zip(g["coef"], spell_x(sp[2], sp[3], self.overs[sp[0]])))
            if self.rng.random() < _sigmoid(z):
                return sp[0]
        off = sp[0] if sp is not None else None
        pool = ([p for p in self.cands if p is not self.prev and p is not off]
                or [p for p in self.cands if p is not self.prev] or self.cands)
        c = self.t["choice"]
        ab = bisect.bisect_right(sit_t["age_edges"], age)
        wb = bisect.bisect_right(sit_t["wear_edges"], wear)
        ws = []
        for p in pool:
            g = self.grp[p]
            lb = self.last.get(p)
            rest = 0 if lb is None else 1 + bisect.bisect_right(c["rest_edges"], n - lb)
            ws.append(self.w0[p] * c["age"][g][ab] * c["wear"][g][wb] * c["rest"][g][rest])
        u, acc = self.rng.random() * sum(ws), 0.0
        pick = pool[-1]
        for p, w in zip(pool, ws):
            acc += w
            if u < acc:
                pick = p
                break
        self.ends[n % 2] = [pick, 0, 0.0, 0.0]
        return pick

    def record(self, p: Player, n: int, runs_excess: float, wkts_excess: float) -> None:
        """Over n has been bowled by p: his spell and rest move on."""
        sp = self.ends[n % 2]
        if sp is None or sp[0] is not p:
            sp = self.ends[n % 2] = [p, 0, 0.0, 0.0]
        sp[1] += 1
        sp[2] += runs_excess
        sp[3] += wkts_excess
        self.prev = p
        self.last[p] = n
        self.overs[p] += 1


# ---------------------------------------------------------------------------------------------- nightwatchman
def nightwatchman(cards: list, next_in: int, overs_left_today: int) -> int | None:
    """Index of the card to send in ahead of the next batter, or None. A wicket with NIGHTWATCH_OVERS or fewer
    left in the day and a top-six batter due: the best defender of Nos. 8-10 (lowest dismissal index) goes in."""
    if overs_left_today > NIGHTWATCH_OVERS or next_in >= NIGHTWATCH_TOP:
        return None
    cand = range(max(next_in + 1, 7), min(10, len(cards)))
    return min(cand, key=lambda j: cards[j].p.bat["all"]["wkt"]) if cand else None
