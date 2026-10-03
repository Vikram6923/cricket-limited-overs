"""Tests for the learned XI selection (engine/selection.py, captain.select_xi).

    python tests/test_selection.py          (no pytest needed; also works under pytest)
"""
from __future__ import annotations

import itertools
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import captain, selection, simulate_match  # noqa: E402
from engine.data import baseline, player  # noqa: E402
from engine.history import historical_team  # noqa: E402


def test_inclusion_matches_brute_force():
    w = [0.3, 1.7, 0.9, 2.5, 0.4, 1.1]
    k = 3
    subsets = list(itertools.combinations(range(len(w)), k))
    weight = {s: math.prod(w[i] for i in s) for s in subsets}
    z = sum(weight.values())
    pi, ek = selection.inclusion(w, k)
    assert abs(ek - z) < 1e-9
    for i in range(len(w)):
        brute = sum(v for s, v in weight.items() if i in s) / z
        assert abs(pi[i] - brute) < 1e-9


def test_sampling_frequencies():
    u = [math.log(x) for x in (0.3, 1.7, 0.9, 2.5, 0.4, 1.1)]
    pi, _ = selection.inclusion([math.exp(x) for x in u], 3)
    rng = random.Random(1)
    n = 20000
    count = [0] * len(u)
    for _ in range(n):
        s = selection.sample(u, rng, 3)
        assert len(s) == 3
        for i in s:
            count[i] += 1
    for c, p in zip(count, pi):
        assert abs(c / n - p) < 0.015


def test_xi_valid_and_varies_only_for_close_calls():
    if not selection.model("t20"):
        return  # no fitted model yet
    t = historical_team("t20", "India", 2021, 2024)
    squad = [player("t20", p, years=t["years"]) for p in t["squad"]]
    base = baseline("t20", "t20i_full", 2024)
    seen = set()
    for s in range(40):
        xi = captain.select_xi(squad, "t20", base, rng=random.Random(s))
        assert len(xi) == 11 and len({p.id for p in xi}) == 11
        assert captain.xi_ok(xi, squad, "t20")
        seen.add(frozenset(p.id for p in xi))
    assert len(seen) > 1                                    # close calls rotate
    a = captain.select_xi(squad, "t20", base)               # no rng: the most likely XI, deterministic
    b = captain.select_xi(squad, "t20", base)
    assert [p.id for p in a] == [p.id for p in b]


def test_match_reproducible_with_squads():
    t1 = historical_team("odi", "Australia", 2003, 2007)
    t2 = historical_team("odi", "India", 2011, 2013)
    c1 = simulate_match(t1, t2, fmt="odi", comp="odi_full", year=2012, seed=11)
    c2 = simulate_match(t1, t2, fmt="odi", comp="odi_full", year=2012, seed=11)
    assert c1["xi"] == c2["xi"] and c1["result"] == c2["result"]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
