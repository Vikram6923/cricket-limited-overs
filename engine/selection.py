"""Learned XI selection (step 7; redesigned twice after the user's review).

The XI is chosen as in a conditional logit over XIs: P(S) ~ exp(sum of u_i for i in S + c[genuine bowlers in S]).
Skill enters through one number per player, his expected **runs value per match** from the engine's own ratings:
  batting: balls his batting position faces on average (measured from real matches) x runs per ball above average
           (more runs, minus the runs-equivalent of extra dismissals);
  bowling: balls he usually bowls x runs saved per ball (fewer runs, plus the runs-equivalent of extra wickets).
So a bowler is judged by his bowling (a No. 10 faces few balls), a batter by his batting, an all-rounder by both.
What is learned from real full-member XIs (engine/fit/fit_selection.py) is how selectors weigh that skill against
the rest: the best keeper, spinners at venues that help spin, the ground's scoring level, experience (caps,
relative to the squad; used at half its fitted weight - the user's decision), and the team balance c (real XIs
have 4-6 specialist bowlers).

(Earlier versions learned separate weights for batting and bowling indexes. They copied real selectors' noise -
resting, injuries, a liking for batting all-rounders - and, with bowling ratings compressed by shrinkage, ranked
Bumrah below Axar Patel and Starc below Mitchell Johnson. Valuing skill in runs keeps the engine's own idea of who
is better.)

The XI for a match is the best valid XI (a keeper, enough bowling for the overs) under the utilities and the
balance term - exact: for each number of bowlers, the best bowlers plus the best others. Randomness comes only from
rating uncertainty: each match every player's indexes are redrawn from their posterior spread (empirical Bayes:
variance (1 - confidence) x tau^2), so a clear leader always plays and players whose values overlap swap now and
then. Without a random stream: the XI from the ratings as they are.
"""
from __future__ import annotations

import json
import math
import random
from functools import lru_cache

from .data import DATA, FORMATS, Player, ratings

FEATURES = ("value", "top_keeper", "other_keeper", "spinner", "spin_x_venue", "bowl_x_runs", "experience")
XI = 11
EXPERIENCE_WEIGHT = 0.5   # user's decision: keep experience, at half its fitted weight


def _share(p: Player, fmt: str) -> float:
    """Share of a full quota he usually bowls (0..1)."""
    opm = p.sel_opm if p.sel_opm is not None else p.bowl_overs_per_match
    return max(0.0, min(1.0, opm / FORMATS[fmt]["quota"]))


def _log(x: float) -> float:
    return math.log(max(x, 0.05))


def _centre(vals: list[float], mask: list[bool]) -> list[float]:
    sel = [v for v, k in zip(vals, mask) if k]
    mu = sum(sel) / len(sel) if sel else 0.0
    return [v - mu if k else 0.0 for v, k in zip(vals, mask)]


def posterior_sd(p: Player, fmt: str) -> dict:
    """Spread of the player's true log indexes given his data: sqrt((1 - confidence) x tau^2) / index."""
    t2 = ratings(fmt)["meta"]["tau2"]
    out = {}
    for side, conf, idx in (("bat", p.bat_conf, p.bat["middle"]), ("bowl", p.bowl_conf, p.bowl["middle"])):
        for m in ("runs", "wkt"):
            out[(side, m)] = math.sqrt(max(1.0 - conf, 0.0) * t2[m][side]) / max(idx[m], 0.3)
    return out


def bowler_mask(squad: list[Player], fmt: str) -> list[bool]:
    """Genuine bowlers: bowl at least half a quota per match."""
    return [_share(p, fmt) >= 0.5 for p in squad]


def _slot_balls(p: Player, slot_balls: list[float]) -> float:
    """Balls faced per match at his usual batting position (interpolated; slot_balls[k] for position k+1)."""
    from .captain import slot_position
    x = min(max(slot_position(p), 1.0), 11.0) - 1
    lo = int(x)
    hi = min(lo + 1, 10)
    return slot_balls[lo] + (slot_balls[hi] - slot_balls[lo]) * (x - lo)


def runs_value(p: Player, fmt: str, base: dict, slot_balls: list[float], z: dict | None = None) -> float:
    """Expected runs value per match (batting + bowling) relative to an average player, over the phases he really
    bats and bowls in (an opener's powerplay record, a death bowler's death record); z shifts log indexes."""
    from .data import PHASES
    from .captain import WICKET_VALUE
    z = z or {}
    dv = WICKET_VALUE[fmt]
    fr, fw = math.exp(z.get(("bat", "runs"), 0.0)), math.exp(z.get(("bat", "wkt"), 0.0))
    gr, gw = math.exp(z.get(("bowl", "runs"), 0.0)), math.exp(z.get(("bowl", "wkt"), 0.0))
    bs = p.bat_phase_share or {ph: 1 / 3 for ph in PHASES}
    ws = p.bowl_phase_share or {ph: 1 / 3 for ph in PHASES}
    bat = bowl = 0.0
    for ph in PHASES:
        b0, bi, wi = base[ph], p.bat[ph], p.bowl[ph]
        bat += bs.get(ph, 0) * (b0["runs"] * (bi["runs"] * fr - 1) - b0["wkt"] * (bi["wkt"] * fw - 1) * dv)
        bowl += ws.get(ph, 0) * (b0["runs"] * (1 - wi["runs"] * gr) + b0["wkt"] * (wi["wkt"] * gw - 1) * dv)
    return _slot_balls(p, slot_balls) * bat + _share(p, fmt) * FORMATS[fmt]["quota"] * 6 * bowl


def features(squad: list[Player], fmt: str, base: dict, venue_spin: float = 0.0, runs_factor: float = 1.0,
             caps: dict | None = None, noise: list[dict] | None = None,
             slot_balls: list[float] | None = None) -> list[list[float]]:
    """One feature row per squad player (order of FEATURES). noise: per player, shifts of the log indexes
    {(side, metric): x} (the per-match draw from rating uncertainty)."""
    caps = caps or {}
    sb = slot_balls or (model(fmt) or {}).get("balls_by_slot")
    z = noise or [{} for _ in squad]
    B = bowler_mask(squad, fmt)
    bv = [runs_value(p, fmt, base, sb, z[i]) for i, p in enumerate(squad)]
    bat_only = [_slot_balls(p, sb) * p.bat["middle"]["runs"] / max(p.bat["middle"]["wkt"], 0.05) for p in squad]
    keepers = sorted((i for i, p in enumerate(squad) if p.keeper), key=lambda i: -bat_only[i])
    exp_ = _centre([math.log1p(caps.get(p.id, p.caps)) for p in squad], [True] * len(squad))
    log_runs = math.log(max(runs_factor, 0.5))
    rows = []
    for i, p in enumerate(squad):
        spin = 1.0 if (B[i] and p.bowl_type == "spin") else 0.0
        rows.append([
            bv[i],
            1.0 if keepers and i == keepers[0] else 0.0,
            1.0 if p.keeper and keepers and i != keepers[0] else 0.0,
            spin, spin * venue_spin, _share(p, fmt) * log_runs,
            exp_[i],
        ])
    return rows


# ---------------------------------------------------------------- conditional logit helpers (used by the fit)

def inclusion(w: list[float], k: int = XI) -> tuple[list[float], float]:
    """P(i in S) under P(S) ~ prod w_i, |S| = k; and e_k (elementary symmetric polynomial)."""
    n = len(w)
    pre = [[1.0] + [0.0] * k]
    for x in w:
        prev = pre[-1]
        pre.append([prev[0]] + [prev[j] + x * prev[j - 1] for j in range(1, k + 1)])
    suf = [[1.0] + [0.0] * k for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        nxt = suf[i + 1]
        suf[i] = [nxt[0]] + [nxt[j] + w[i] * nxt[j - 1] for j in range(1, k + 1)]
    ek = pre[n][k]
    pi = []
    for i in range(n):
        e_wo = sum(pre[i][a] * suf[i + 1][k - 1 - a] for a in range(k))
        pi.append(w[i] * e_wo / ek if ek > 0 else 0.0)
    return pi, ek


def sample(u: list[float], rng: random.Random, k: int = XI) -> list[int]:
    """Exact draw from P(S) ~ exp(sum u_i) (no constraints)."""
    n = len(u)
    top = max(u)
    w = [math.exp(x - top) for x in u]
    suf = [[1.0] + [0.0] * k for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        nxt = suf[i + 1]
        suf[i] = [nxt[0]] + [nxt[j] + w[i] * nxt[j - 1] for j in range(1, k + 1)]
    out, need = [], k
    for i in range(n):
        if need == 0:
            break
        p = w[i] * suf[i + 1][need - 1] / suf[i][need] if suf[i][need] > 0 else 1.0
        if rng.random() < p:
            out.append(i)
            need -= 1
    return out


def utilities(rows: list[list[float]], beta: list[float]) -> list[float]:
    return [sum(b * x for b, x in zip(beta, r)) for r in rows]


def esp(w: list[float], k: int = XI) -> list[float]:
    """e_0..e_k of the weights w."""
    e = [1.0] + [0.0] * k
    for x in w:
        for j in range(k, 0, -1):
            e[j] += x * e[j - 1]
    return e


def esp_without(w: list[float], k: int = XI) -> list[list[float]]:
    """For each i, e_0..e_k of the weights without w[i] (prefix / suffix tables)."""
    n = len(w)
    pre = [[1.0] + [0.0] * k]
    for x in w:
        prev = pre[-1]
        pre.append([prev[0]] + [prev[j] + x * prev[j - 1] for j in range(1, k + 1)])
    suf = [[1.0] + [0.0] * k for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        nxt = suf[i + 1]
        suf[i] = [nxt[0]] + [nxt[j] + w[i] * nxt[j - 1] for j in range(1, k + 1)]
    return [[sum(pre[i][a] * suf[i + 1][kk - a] for a in range(kk + 1)) for kk in range(k + 1)] for i in range(n)]


# ---------------------------------------------------------------- rules and the pick

class Rules:
    """Hard constraints as fast sums: a keeper (if the squad has one) and enough bowling for the overs (or as much
    as the squad can offer). cap[i] = overs player i can be expected to bowl (captain.player_capacity)."""

    def __init__(self, squad: list[Player], fmt: str):
        from .captain import player_capacity
        self.cap = [player_capacity(p, fmt) for p in squad]
        self.kp = [p.keeper for p in squad]
        self.has_keeper = any(self.kp)
        best = sorted((c for c, k in zip(self.cap, self.kp) if not k), reverse=True)[:XI - (1 if self.has_keeper else 0)]
        self.need = min(FORMATS[fmt]["overs"], sum(best)) - 1e-9

    def ok(self, S) -> bool:
        return (not self.has_keeper or any(self.kp[i] for i in S)) and \
            sum(self.cap[i] for i in S if not self.kp[i]) >= self.need

    def best_balanced(self, u: list[float], bowler: list[bool], comp: dict) -> list[int]:
        """Exact best valid XI under sum(u) + comp[number of bowlers]: for each number j, the best j bowlers and the
        best 11 - j others (the best keeper always among the others), keep the best that meets the rules."""
        bw = sorted((i for i in range(len(u)) if bowler[i]), key=lambda i: -u[i])
        ot = sorted((i for i in range(len(u)) if not bowler[i]), key=lambda i: -u[i])
        keeper = next((i for i in ot if self.kp[i]), None)
        best, best_v = None, -1e18
        for j in range(0, XI + 1):
            if str(j) not in comp or j > len(bw) or XI - j > len(ot):
                continue
            others = ot[:XI - j]
            if keeper is not None and keeper not in others:
                if XI - j == 0:
                    continue
                others = others[:-1] + [keeper]
            S = bw[:j] + others
            if not self.ok(S):
                continue
            v = sum(u[i] for i in S) + comp[str(j)]
            if v > best_v:
                best, best_v = S, v
        return best if best is not None else self.best(u)

    def best(self, u: list[float]) -> list[int]:
        """The highest-utility valid XI, built greedily: best keeper first, then by utility, skipping anyone who
        would leave too few slots to reach the bowling needed."""
        order = sorted(range(len(u)), key=lambda i: -u[i])
        S = []
        if self.has_keeper:
            S.append(next(i for i in order if self.kp[i]))
        for i in order:
            if len(S) == XI:
                break
            if i in S:
                continue
            rest = sorted((self.cap[j] for j in order if j not in S and j != i and not self.kp[j]), reverse=True)
            have = sum(self.cap[j] for j in S if not self.kp[j]) + (0 if self.kp[i] else self.cap[i])
            if have + sum(rest[:XI - len(S) - 1]) >= self.need:
                S.append(i)
        return S


@lru_cache(maxsize=None)
def model(fmt: str) -> dict | None:
    p = DATA / "engine" / f"selection_{fmt}.json"
    if not p.exists():
        return None
    m = json.loads(p.read_text(encoding="utf-8"))
    return m if m.get("features") == list(FEATURES) else None   # an old model file: fall back to the rule


def venue_spin(fmt: str, venue: str | None) -> float:
    from .conditions import venue_key
    m = model(fmt)
    return (m or {}).get("venue_spin", {}).get(venue_key(venue), 0.0) if venue else 0.0


def weights(m: dict) -> list[float]:
    return [b * (EXPERIENCE_WEIGHT if f == "experience" else 1.0) for f, b in zip(FEATURES, m["beta"])]


def choose(squad: list[Player], fmt: str, base: dict, rng: random.Random | None = None, venue: str | None = None,
           runs_factor: float = 1.0) -> list[Player] | None:
    """The XI: the best valid XI under the learned utilities, with each player's ratings redrawn from their
    uncertainty when a random stream is given. None if no fitted model."""
    m = model(fmt)
    if not m:
        return None
    if len(squad) <= XI:
        return list(squad)
    noise = None
    if rng is not None:
        noise = [{k: rng.gauss(0.0, sd) for k, sd in posterior_sd(p, fmt).items()} for p in squad]
    rows = features(squad, fmt, base, venue_spin(fmt, venue), runs_factor, {p.id: p.caps for p in squad}, noise,
                    m["balls_by_slot"])
    S = Rules(squad, fmt).best_balanced(utilities(rows, weights(m)), bowler_mask(squad, fmt), m["composition"])
    return [squad[i] for i in S] if len(S) == XI else None
