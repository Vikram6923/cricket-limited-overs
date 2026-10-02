"""Per-delivery outcome model (design section 4).

    rate_m = baseline[comp][year][phase][m] x batter phase index x bowler phase index x situation_m

The legal-ball distribution is built so that every fitted index is honoured at once: P(wicket), P(run-out),
P(four), P(six) come straight from their rates; P(dot) matches the dot rate (dots in the data include wicket balls);
the remaining mass goes to 1/2/3 with a mean chosen so that expected runs off the bat match the runs rate.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

DISMISSALS = ("bowled", "lbw", "caught_fielder", "caught_keeper", "caught_bowler", "stumped", "hit_wicket")
NO_SITUATION = {}


@dataclass(slots=True)
class Outcome:
    legal: bool                 # counts as one of the six balls of the over
    faced: bool                 # counts as a ball faced by the striker (everything except wides)
    bat_runs: int = 0
    extra: str = ""             # "" | "w" | "nb" | "b" | "lb"
    extra_runs: int = 0         # runs credited as extras (a no-ball's penalty run, wides, byes, leg byes)
    wicket: str = ""            # "" | one of DISMISSALS | "run_out"
    non_striker_out: bool = False
    ran: int = 0                # runs physically run (decides the change of strike)


def _pick(rng: random.Random, dist: dict) -> str:
    u = rng.random()
    acc = 0.0
    last = None
    for k, p in dist.items():
        acc += p
        last = k
        if u < acc:
            return k
    return last


class BallModel:
    def __init__(self, basics: dict):
        self.b = basics
        self.free_hit = basics.get("free_hit", {})
        self.wide_runs = {int(k): v for k, v in basics["wide_runs"].items()}
        self.ro_ns = basics["run_out"]["non_striker_share"]
        self.ro_runs = {int(k): v for k, v in basics["run_out"]["runs_completed"].items()}

    # ------------------------------------------------------------------ probabilities
    def legal_probs(self, base: dict, bat: dict, bowl: dict, other_out: float, sit: dict,
                    free_hit: bool, phase: str) -> dict:
        """Probabilities of a legal ball's outcomes: W, RO, 6, 4, 0, 1, 2, 3."""
        g = sit.get
        rw = base["wkt"] * bat["wkt"] * bowl["wkt"] * g("wkt", 1.0)
        rro = base["other_out"] * other_out * g("run_out", 1.0)
        r4 = base["four"] * bat["four"] * bowl["four"] * g("four", 1.0)
        r6 = base["six"] * bat["six"] * bowl["six"] * g("six", 1.0)
        rdot = base["dot"] * bat["dot"] * bowl["dot"] * g("dot", 1.0)
        rruns = base["runs"] * bat["runs"] * bowl["runs"] * g("runs", 1.0)
        if free_hit:
            fh = self.free_hit.get(phase) or {"runs": 1.5, "four": 1.4, "six": 2.5, "dot": 0.7}
            rw = 0.0
            r4 *= fh["four"]
            r6 *= fh["six"]
            rdot *= fh["dot"]
            rruns *= fh["runs"]
        p_w = min(rw, 0.45)
        p_ro = min(rro, 0.05)
        p4 = min(r4, 0.45)
        p6 = min(r6, 0.35)
        if p4 + p6 > 0.7:
            s = 0.7 / (p4 + p6)
            p4, p6 = p4 * s, p6 * s
        p_dot = max(rdot - p_w - p_ro, 0.01)
        rest = 1.0 - p_w - p_ro - p4 - p6
        p_dot = min(p_dot, rest - 0.01)
        p123 = rest - p_dot
        need = rruns - 4 * p4 - 6 * p6
        mu = need / p123 if p123 > 0 else 1.0
        if mu < 1.0 or mu > 2.0:
            # can't honour both the dot rate and the runs rate: honour runs, move the difference into dots
            mu = min(max(mu, 1.0), 2.0)
            p123 = min(max(need / mu, 0.01), rest - 0.01)
            p_dot = rest - p123
        split = self.b["run_split"][phase]
        s3 = split.get("3", 0.01)
        p2_share = min(max(mu - 1.0 - 2 * s3, 0.0), 1.0 - s3)
        p1_share = 1.0 - p2_share - s3
        return {"W": p_w, "RO": p_ro, "6": p6, "4": p4, "0": p_dot,
                "1": p123 * p1_share, "2": p123 * p2_share, "3": p123 * s3}

    # ------------------------------------------------------------------ sampling
    def delivery(self, rng: random.Random, base: dict, striker, bowler, phase: str, bowl_type: str,
                 sit: dict = NO_SITUATION, free_hit: bool = False) -> Outcome:
        w = base["wide"] * bowler.wide * sit.get("wide", 1.0)
        nb = base["noball"] * bowler.noball
        tot = 1.0 + w + nb
        u = rng.random()
        if u < w / tot:
            runs = _pick(rng, self.wide_runs)
            return Outcome(legal=False, faced=False, extra="w", extra_runs=runs, ran=max(runs - 1, 0) % 4)
        bat, bwl = striker.bat[phase], bowler.bowl[phase]
        if u < (w + nb) / tot:
            # no-ball: the batter plays it, can't be out except run out; one extra run; next ball is a free hit
            probs = self.legal_probs(base, bat, bwl, striker.other_out, sit, True, phase)
            o = self._legal(rng, probs, phase, bowl_type)
            o.legal = False
            o.extra = "nb"
            o.extra_runs = 1
            return o
        probs = self.legal_probs(base, bat, bwl, striker.other_out, sit, free_hit, phase)
        return self._legal(rng, probs, phase, bowl_type)

    def _legal(self, rng: random.Random, probs: dict, phase: str, bowl_type: str) -> Outcome:
        k = _pick(rng, probs)
        if k == "W":
            mix = self.b["dismissal"][phase].get(bowl_type) or self.b["dismissal"][phase]["unknown"]
            return Outcome(legal=True, faced=True, wicket=_pick(rng, mix))
        if k == "RO":
            runs = _pick(rng, self.ro_runs)
            return Outcome(legal=True, faced=True, bat_runs=runs, wicket="run_out",
                           non_striker_out=rng.random() < self.ro_ns, ran=runs)
        r = int(k)
        if r == 0:
            bys = self.b["byes"][phase]
            v = rng.random()
            if v < bys["p_legbye"]:
                runs = int(_pick(rng, bys["legbye_runs"]))
                return Outcome(legal=True, faced=True, extra="lb", extra_runs=runs, ran=runs if runs != 4 else 0)
            if v < bys["p_legbye"] + bys["p_bye"]:
                runs = int(_pick(rng, bys["bye_runs"]))
                return Outcome(legal=True, faced=True, extra="b", extra_runs=runs, ran=runs if runs != 4 else 0)
            return Outcome(legal=True, faced=True)
        return Outcome(legal=True, faced=True, bat_runs=r, ran=r if r < 4 else 0)
