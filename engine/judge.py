"""Captaincy decisions valued in runs, with the engine's own numbers.

Used twice:
- the captaincy report: for each decision a person made, how many runs it was worth against the computer's choice;
- weaker computer captains (difficulty levels): a "loose" captain sometimes picks another option, the better ones
  more often (softmax over these values), so its mistakes are plausible ones.

Values are estimates for comparing options, not predictions of the score:
- bowler: this over's expected cost (runs conceded minus the runs-value of wickets, engine.captain.bowling_cost)
  plus the cheapest way to bowl the rest of the innings with the quotas that are left (bowlers x phases, solved
  exactly as a small transport problem; the no-consecutive-overs rule is ignored there);
- next batter: the order still to come, each batter's runs value per ball (in the phase he would bat in) x the
  balls the k-th next batter can expect from here (impact.balls_next, fitted on real innings);
- XI: batting in the given order (balls by slot, engine.selection) + the best overs the side can bowl
  (impact.attack_value), as the Impact Player model values an XI.
Toss and Impact Player calls are reported without a value.
"""
from __future__ import annotations

import math
import random

from .captain import WICKET_VALUE, bowling_cost
from .data import FORMATS, phase_at
from . import impact

LEVELS = {                     # (chance of a loose decision, softmax temperature in runs)
    "expert": (0.0, 1.0),
    "average": (0.15, 3.0),
    "easy": (0.6, 10.0),
}
SHORT = 12.0                   # runs per over charged for overs no one can bowl (quotas exhausted)


# ------------------------------------------------------------------------------------------------ bowlers

def _transport(costs: list[list[float]], caps: list[int], demand: list[int]) -> float:
    """Minimum total cost of filling `demand[j]` overs of phase j from bowlers with `caps[i]` overs each
    (successive shortest paths; overs no one can bowl cost SHORT each)."""
    n, k = len(caps), len(demand)
    # nodes: 0 source, 1..n bowlers, n+1..n+k phases, n+k+1 sink
    N, S, T = n + k + 2, 0, n + k + 1
    cap, cost, adj = {}, {}, [[] for _ in range(N)]

    def edge(u, v, c, w):
        adj[u].append(v)
        adj[v].append(u)
        cap[u, v], cost[u, v] = c, w
        cap.setdefault((v, u), 0)
        cost[v, u] = -w
    for i in range(n):
        edge(S, 1 + i, caps[i], 0.0)
        for j in range(k):
            edge(1 + i, n + 1 + j, caps[i], costs[i][j])
    for j in range(k):
        edge(n + 1 + j, T, demand[j], 0.0)
    total, need = 0.0, sum(demand)
    while need > 0:
        dist, prev = [math.inf] * N, [-1] * N
        dist[S] = 0.0
        for _ in range(N - 1):                 # Bellman-Ford (negative residual costs)
            moved = False
            for u in range(N):
                if dist[u] == math.inf:
                    continue
                for v in adj[u]:
                    if cap[u, v] > 0 and dist[u] + cost[u, v] < dist[v] - 1e-12:
                        dist[v], prev[v] = dist[u] + cost[u, v], u
                        moved = True
            if not moved:
                break
        if dist[T] == math.inf:
            break
        f, v = need, T
        while v != S:
            f = min(f, cap[prev[v], v])
            v = prev[v]
        v = T
        while v != S:
            u = prev[v]
            cap[u, v] -= f
            cap[v, u] += f
            v = u
        total += f * dist[T]
        need -= f
    return total + need * SHORT


def bowler_values(m, inn, over: int, opts: list, quota_left: dict) -> dict:
    """Value (higher = better for the fielding side) of each option for this over."""
    fmt, team = m.fmt, inn.bowl
    phases = [phase_at(o, fmt, inn.max_overs) for o in range(over + 1, inn.max_overs)]
    order = sorted(set(phases))
    demand = [phases.count(ph) for ph in order]
    bowlers = [p for p in team.players if p is not team.keeper]
    cost = {id(p): {ph: 6 * bowling_cost(p, ph, m.base_of(p)[ph], fmt) for ph in set(phases) | {phase_at(over, fmt, inn.max_overs)}}
            for p in set(bowlers) | set(opts)}
    ph_now = phase_at(over, fmt, inn.max_overs)
    out = {}
    for p in opts:
        caps = [max(0, quota_left.get(b, 0) - (b is p)) for b in bowlers]
        rest = _transport([[cost[id(b)][ph] for ph in order] for b in bowlers], caps, demand) if demand else 0.0
        out[p] = -(cost[id(p)][ph_now] + rest)
    return out


# ------------------------------------------------------------------------------------------------ batters

def _bat_ball(m, p, ph: str) -> float:
    b0, ix = m.base[ph], p.bat[ph]
    return b0["runs"] * (ix["runs"] - 1) - b0["wkt"] * (ix["wkt"] - 1) * WICKET_VALUE[m.fmt]


def order_value(m, inn, rem: list) -> float:
    """Runs value of sending in `rem` in this order from here."""
    total = inn.max_overs * 6
    left = total - inn.legal
    balls = impact.balls_next(min(inn.wkts, 9), left, len(rem))
    at, v = inn.legal, 0.0
    for p, b in zip(rem, balls):
        mid = min(total - 1, at + b / 2)
        v += b * _bat_ball(m, p, phase_at(int(mid // 6), m.fmt, inn.max_overs))
        at += b
    return v


def batter_values(m, inn, cands: list) -> dict:
    """Value of sending in each candidate next (the others follow in their current order)."""
    rem = [c.p for c in inn.cards[inn.next_in:]]
    return {p: order_value(m, inn, [p] + [q for q in rem if q is not p]) for p in cands}


# ------------------------------------------------------------------------------------------------ XI

def xi_value(m, order: list, keeper) -> float:
    sb = m._slot_balls()
    vals = impact.Values(m.fmt, m.base)
    bat = sum(vals.bat(p) * sb[min(k, len(sb) - 1)] for k, p in enumerate(order))
    return bat + impact.attack_value(order, keeper, m.fmt, m.base, vals=vals)


# ------------------------------------------------------------------------------------------------ loose captains

class AllBut(dict):
    """skill mapping for a run: every side except `but` (the person's) captained at `level`."""

    def __init__(self, level: str, but: str | None):
        super().__init__()
        self.level, self.but = level, but

    def get(self, k, default=None):
        return default if k == self.but else self.level

    def __bool__(self):
        return self.level in LEVELS and self.level != "expert"


def pick(values: dict, temp: float, rng: random.Random):
    """Softmax choice: options worth more are likelier; temp = runs that make an option e times less likely."""
    if not values:
        return None
    best = max(values.values())
    ks = list(values)
    w = [math.exp((values[k] - best) / max(temp, 1e-6)) for k in ks]
    r, acc = rng.random() * sum(w), 0.0
    for k, x in zip(ks, w):
        acc += x
        if r <= acc:
            return k
    return ks[-1]


# ------------------------------------------------------------------------------------------------ report

def season_report(cards: list, team: str) -> dict | None:
    """Sum of the captaincy entries of `team` over its matches: per decision kind, the number of calls, how many
    differed from the computer's, and the runs they were worth; with the runs per win to read it as wins."""
    kinds, n_matches, rpw, total = {}, 0, [], 0.0
    for c in cards:
        log = (c.get("captaincy") or {}).get(team)
        if log is None:
            continue
        n_matches += 1
        rpw.append(c.get("runs_per_win") or 0)
        for d in log:
            k = kinds.setdefault(d["kind"], {"calls": 0, "changed": 0, "runs": 0.0, "valued": 0})
            k["calls"] += 1
            k["changed"] += d["changed"]
            if d.get("delta") is not None:
                k["runs"] += d["delta"]
                k["valued"] += 1
                total += d["delta"]
    if not n_matches:
        return None
    for k in kinds.values():
        k["runs"] = round(k["runs"], 1)
    per_win = sum(rpw) / len(rpw) if rpw else 0
    return {"team": team, "matches": n_matches, "kinds": kinds, "runs": round(total, 1),
            "runs_per_win": round(per_win, 1), "wins": round(total / per_win, 2) if per_win else None}
