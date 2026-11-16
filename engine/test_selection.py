"""Learned XI selection for Tests (the limited-overs model of engine/selection.py, with Test values).

P(XI) ~ exp(sum of u_i for the eleven + c[specialist bowlers in the XI]). Skill enters as one number, the
player's runs value a match from the engine's ratings (engine/test_value.py: batting above the era's average
times the innings he has, plus the balls he bowls times what he saves a ball). Separate weights for batting
and bowling were tried and dropped: real selections hardly follow bowling value (injuries, rest, rotation),
so the fit weighed it at a fifth of batting and left Bumrah and Lindwall out. What is learned from real XIs
(engine/fit/fit_test_selection.py) is how selectors weigh that against the rest: the best keeper, a spinner,
more so where the host's grounds take spin, experience, and the balance c (real XIs have four or five
specialist bowlers).

The XI for a match is the best one under the utilities and the balance: for each mix of fast bowlers and
spinners that real sides pick (the mixes found in at least 1% of real XIs: never an attack without pace), the
best keeper, the best of each kind and the best others. With a random stream every player's indexes are first redrawn
from their uncertainty, so a clear first choice always plays and close calls go either way from Test to Test.

Experience is used at half its fitted weight, the owner's decision for limited overs carried over.
With no fitted model the rule of engine/test_captain.py select_xi is used.
"""
from __future__ import annotations

import json
import math
import random
from functools import lru_cache

from . import test_value
from .data import DATA, Player, ratings
from .test_captain import batting_value, group

FEATURES = ("value", "top_keeper", "other_keeper", "spinner", "spin_x_host", "experience")
XI = 11
EXPERIENCE_WEIGHT = 0.5
PHASE = "all"


@lru_cache(maxsize=None)
def model() -> dict | None:
    p = DATA / "engine" / "selection_test.json"
    if not p.exists():
        return None
    m = json.loads(p.read_text(encoding="utf-8"))
    return m if m.get("features") == list(FEATURES) else None


def bowler_mask(squad: list[Player]) -> list[bool]:
    return [group(p) != "part" and not p.keeper for p in squad]


def posterior_sd(p: Player) -> dict:
    """Spread of his true log indexes given his data: sqrt((1 - confidence) x tau^2) / index."""
    t2 = ratings("test")["meta"]["tau2"]
    out = {}
    for side, conf, idx in (("bat", p.bat_conf, p.bat[PHASE]), ("bowl", p.bowl_conf, p.bowl[PHASE])):
        for m in ("runs", "wkt"):
            out[(side, m)] = math.sqrt(max(1.0 - conf, 0.0) * t2[m][side]) / max(idx[m], 0.3)
    return out


def value(p: Player, base: dict, z: dict | None = None) -> tuple[float, float]:
    """(batting, bowling) in runs a match above an average player; z shifts his log indexes (the draw from
    rating uncertainty)."""
    if not z:
        return test_value.value_parts(p, base)
    b0 = base[PHASE]
    par = b0["runs"] / max(b0["wkt"], 1e-6)
    bat = bowl = 0.0
    if p.rated_bat:
        ix = p.bat[PHASE]
        r, w = ix["runs"] * math.exp(z[("bat", "runs")]), ix["wkt"] * math.exp(z[("bat", "wkt")])
        bat = test_value.INNINGS * par * (r / max(w, 0.2) - 1.0)
    if p.rated_bowl:
        ix = p.bowl[PHASE]
        r, w = ix["runs"] * math.exp(z[("bowl", "runs")]), ix["wkt"] * math.exp(z[("bowl", "wkt")])
        bowl = 6 * p.bowl_overs_per_match * b0["runs"] * (w - r)
    return bat, bowl


def features(squad: list[Player], base: dict, host_spin: float = 0.0, caps: dict | None = None,
             noise: list[dict] | None = None) -> list[list[float]]:
    """One row per squad player, in the order of FEATURES."""
    caps = caps or {}
    z = noise or [None] * len(squad)
    B = bowler_mask(squad)
    keepers = sorted((i for i, p in enumerate(squad) if p.keeper), key=lambda i: -batting_value(squad[i]))
    ex = [math.log1p(caps.get(p.id, p.caps)) for p in squad]
    mu = sum(ex) / len(ex)
    rows = []
    for i, p in enumerate(squad):
        spin = 1.0 if B[i] and p.bowl_type == "spin" else 0.0
        rows.append([sum(value(p, base, z[i])), 1.0 if keepers and i == keepers[0] else 0.0,
                     1.0 if p.keeper and keepers and i != keepers[0] else 0.0, spin, spin * host_spin, ex[i] - mu])
    return rows


def utilities(rows: list[list[float]], beta: list[float]) -> list[float]:
    return [sum(b * x for b, x in zip(beta, r)) for r in rows]


def best_xi(u: list[float], bowler: list[bool], keeper: list[bool], comp: dict, spin: list[bool] | None = None,
            mixes: list | None = None) -> list[int]:
    """The best XI under sum(u) + comp[bowlers]: the best keeper, the best bowlers and the best of the rest.
    With mixes [[fast bowlers, spinners], ...] only those attacks are allowed, when the squad can field one."""
    order = sorted(range(len(u)), key=lambda i: -u[i])
    k = next((i for i in order if keeper[i]), None)
    bw = [i for i in order if bowler[i]]
    ot = [i for i in order if not bowler[i] and i != k]
    need = XI - (k is not None)
    best, best_v = None, -1e18

    def consider(picked: list[int]) -> None:
        nonlocal best, best_v
        j = len(picked)
        if str(j) not in comp or need - j > len(ot) or need - j < 0:
            return
        S = ([k] if k is not None else []) + picked + ot[:need - j]
        v = sum(u[i] for i in S) + comp[str(j)]
        if v > best_v:
            best, best_v = S, v
    if mixes and spin:
        pc, sp = [i for i in bw if not spin[i]], [i for i in bw if spin[i]]
        for a, b in mixes:
            if a <= len(pc) and b <= len(sp):
                consider(pc[:a] + sp[:b])
    if best is None:
        for j in range(len(bw) + 1):
            consider(bw[:j])
    return best if best is not None else order[:XI]


def weights(m: dict) -> list[float]:
    return [b * (EXPERIENCE_WEIGHT if f == "experience" else 1.0) for f, b in zip(FEATURES, m["beta"])]


def host_spin(host: str | None) -> float:
    m = model()
    return (m or {}).get("host_spin", {}).get(host or "", 0.0)


def choose(squad: list[Player], base: dict, rng: random.Random | None = None,
           host: str | None = None) -> list[Player] | None:
    """The XI from a squad, or None when there is no fitted model."""
    m = model()
    if not m:
        return None
    if len(squad) <= XI:
        return list(squad)
    noise = [{k: rng.gauss(0.0, sd) for k, sd in posterior_sd(p).items()} for p in squad] if rng else None
    rows = features(squad, base, host_spin(host), None, noise)
    B = bowler_mask(squad)
    S = best_xi(utilities(rows, weights(m)), B, [p.keeper for p in squad], m["composition"],
                [B[i] and p.bowl_type == "spin" for i, p in enumerate(squad)], m.get("mixes"))
    return [squad[i] for i in S] if len(S) == XI else None
