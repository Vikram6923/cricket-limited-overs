"""Limited-overs match state machine (design T0-1, T0-4, T0-7).

    from engine import simulate_match
    card = simulate_match({"name": "India", "players": [...ids]}, {"name": "Australia", "players": [...]},
                          fmt="t20", comp="t20i_full", year=2025, seed=1)

Returns a JSON-able scorecard dict. No printing, no files, no global state; `seed` makes a match reproducible.
"""
from __future__ import annotations

import random
import zlib
from dataclasses import dataclass, field

from . import judge
from . import rain
from . import captain, conditions
from .ballmodel import BallModel
from .data import FORMATS, Player, baseline, basics, phase_at, player
from .situation import Situation

KIND_TEXT = {"bowled": "b", "lbw": "lbw", "caught_fielder": "c", "caught_keeper": "c", "caught_bowler": "c & b",
             "stumped": "st", "hit_wicket": "hit wicket", "run_out": "run out"}


@dataclass
class Team:
    name: str
    players: list[Player]
    keeper: Player
    captain: Player
    order: list[Player]          # batting order
    fixed_order: bool = False    # True when the caller gave an explicit order (no promotions)
    bench: list[Player] = field(default_factory=list)   # squad players not in the XI (Impact Player candidates)
    max_overseas: int | None = None
    impact: dict | None = None   # the Impact Player substitution made, if any
    squad: list[Player] = field(default_factory=list)   # everyone available (XI + bench) before the toss


@dataclass
class BatInns:
    p: Player
    pos: int
    runs: int = 0
    balls: int = 0
    fours: int = 0
    sixes: int = 0
    dots: int = 0
    out: bool = False
    how: dict | None = None
    batted: bool = False


@dataclass
class BowlFig:
    p: Player
    exp_runs: float = 0.0        # what his ratings predicted for the balls he bowled (reactive changes)
    exp_wkts: float = 0.0
    balls: int = 0
    runs: int = 0
    wkts: int = 0
    maidens: int = 0
    wides: int = 0
    noballs: int = 0
    dots: int = 0
    fours: int = 0
    sixes: int = 0


def make_team(spec: dict, fmt: str, ctx: dict | None = None) -> Team:
    """spec = {"name", "players": [id | Player | {"id", "name"}], "keeper"?: id, "captain"?: id,
    "order"?: [ids] (explicit batting order; default: by usual position), "squad"?: [ids] (pick the XI),
    "years"?: [first, last] (rate the players on those years, design T2-10),
    "years_mode"?: "blend" (default, shrunk toward the career) | "only" (those years alone)}."""
    yrs, ym = spec.get("years"), spec.get("years_mode") or "blend"
    ps = []
    for x in spec.get("players", []):
        if isinstance(x, Player):
            ps.append(x)
        elif isinstance(x, dict):
            ps.append(player(fmt, x["id"], x.get("name"), spec.get("team_level_as") or None, years=yrs,
                             years_mode=ym))
        else:
            ps.append(player(fmt, x, years=yrs, years_mode=ym))
    if spec.get("squad"):
        # design T2-9: pick the XI from a larger squad
        squad = [player(fmt, x, years=yrs, years_mode=ym) if not isinstance(x, Player) else x
                 for x in spec["squad"]]
        overseas = set(spec.get("overseas") or [])   # league overseas limit ("max_overseas", e.g. IPL 4)
        for p in squad:
            p.overseas = p.id in overseas
        # ctx (from Match): the selection's random stream, venue and the scoring level the captain sees
        ctx = ctx or {}
        ps = captain.select_xi(squad, fmt, ctx.get("base") or baseline(fmt, spec.get("comp") or FORMATS[fmt]["intl"],
                                                                       spec.get("year") or 2025),
                               rng=ctx.get("rng"), venue=ctx.get("venue"), runs_factor=ctx.get("runs_factor", 1.0),
                               max_overseas=spec.get("max_overseas"))
    by_id = {p.id: p for p in ps}
    if spec.get("order"):
        order = [by_id[i] for i in spec["order"] if i in by_id]
        order += [p for p in captain.batting_order(ps) if p not in order]
    else:
        order = captain.batting_order(ps)
    keeper = by_id.get(spec.get("keeper")) or captain.choose_keeper(ps)
    capt = by_id.get(spec.get("captain")) or max(ps, key=lambda p: p.bat_balls + p.bowl_balls)
    bench = [p for p in squad if p not in ps] if spec.get("squad") else []
    return Team(spec["name"], ps, keeper, capt, order, fixed_order=bool(spec.get("order")), bench=bench,
                max_overseas=spec.get("max_overseas"), squad=ps + bench)


class Innings:
    def __init__(self, m: "Match", bat: Team, bowl: Team, number: int, target: int | None,
                 max_overs: int, max_wkts: int = 10, order: list[Player] | None = None,
                 bowlers: list[Player] | None = None, super_over: bool = False):
        self.m, self.bat, self.bowl, self.number = m, bat, bowl, number
        self.target, self.max_overs, self.max_wkts, self.super_over = target, max_overs, max_wkts, super_over
        order = order or bat.order
        self.cards = [BatInns(p, i + 1) for i, p in enumerate(order)]
        self.figs: dict[Player, BowlFig] = {}
        self.allowed_bowlers = bowlers
        self.runs = self.wkts = self.legal = 0
        self.extras = {"b": 0, "lb": 0, "w": 0, "nb": 0}
        self.fow, self.partnerships, self.overs, self.events = [], [], [], []
        self.next_in = 2
        self.striker, self.non_striker = self.cards[0], self.cards[1]
        self.striker.batted = self.non_striker.batted = True
        self.pship = {"runs": 0, "balls": 0, "a": self.striker, "b": self.non_striker, "a_runs": 0, "b_runs": 0}
        self.free_hit = False
        self.done = False
        self.rain_stopped = False    # play could not resume (rain): the result goes by DLS par
        self.streak: dict[Player, int] = {}   # consecutive legal balls taking wickets, per bowler (hat-tricks)

    # ------------------------------------------------------------------ helpers
    def offset(self) -> int:
        """Balls to add so the situation tables (full-innings states) see the right balls left in a shortened
        innings: resources depend on overs left and wickets, as in DLS."""
        return 0 if self.super_over else (FORMATS[self.m.fmt]["overs"] - self.max_overs) * 6

    def par_k(self) -> float:
        """Scale on par runs in a shortened innings. The full-innings par table read at the shortened innings'
        balls left over-rates it (rare states such as 0 down after 10 overs of a T20 come from good days), so a
        chaser thought it was ahead and batted too slowly (a 10-over chase won 40%, not 50%). Par is scaled so the
        innings starts at its fitted DLS resources (engine/rain.py)."""
        if self.super_over or self.max_overs >= FORMATS[self.m.fmt]["overs"]:
            return 1.0
        key = self.max_overs
        if getattr(self, "_par_k", (None,))[0] != key:
            off = self.offset()
            self._par_k = (key, self.m.dls.res(self.max_overs * 6, 0) / max(self.m.sit.par_frac(off, 0), 1e-3))
        return self._par_k[1]

    def ball_str(self) -> str:
        """The ball just bowled, as scorers write it: the 6th ball of the 1st over is 0.6 (0.0 before any ball)."""
        n = self.legal
        return f"{(n - 1) // 6}.{(n - 1) % 6 + 1}" if n else "0.0"

    def over_str(self) -> str:
        return f"{self.legal // 6}.{self.legal % 6}"

    def score_str(self) -> str:
        return f"{self.runs}/{self.wkts}"

    def event(self, text: str, kind: str = "info", **data):
        self.events.append({"innings": self.number, "over": self.ball_str(), "score": self.score_str(),
                            "kind": kind, "text": text, **data})

    def fig(self, p: Player) -> BowlFig:
        if p not in self.figs:
            self.figs[p] = BowlFig(p)
        return self.figs[p]

    def chase_won(self) -> bool:
        return self.target is not None and self.runs >= self.target

    # ------------------------------------------------------------------ play
    def play(self):
        fmt = self.m.fmt
        fielders = self.allowed_bowlers or self.bowl.players
        quota = rain.quota(self.max_overs) if not self.super_over else 1
        quota_left = {p: quota for p in fielders}
        last = None
        plan = None
        react = self.m.reactive(self) if not self.super_over else None
        if not self.super_over and self.m.use_plan:
            plan = captain.BowlingPlan(fielders, self.bowl.keeper, fmt, self.m.base, self.max_overs, quota,
                                       self.m.rng, base_of=self.m.base_of)
        over = -1
        while over + 1 < self.max_overs:
            over += 1
            if self.done:
                break
            if self.m.rain_profile and not self.super_over:
                cut = self.m.rain_check(self, over)
                if cut == "stop":
                    break
                if cut:                       # overs reduced: new quota, the rest chosen over by over
                    q2 = rain.quota(self.max_overs)
                    for p in quota_left:
                        quota_left[p] = max(0, quota_left[p] - (quota - q2))
                    quota, plan = q2, None
                    if over >= self.max_overs:
                        break
            # phases scale with a shortened innings (as powerplays do)
            ph = (phase_at(over, fmt, self.max_overs)
                  if not self.super_over else "death")
            base = self.m.base[ph]
            if self.allowed_bowlers and len(self.allowed_bowlers) == 1:
                bowler = self.allowed_bowlers[0]
            else:
                bowler = plan.bowler_for(over, last, quota_left) if plan else None
                if bowler is not None and react:
                    bowler = self.react(plan, over, bowler, last, quota_left, fielders, react)
                if bowler is not None:
                    q = dict(quota_left)
                    q[bowler] -= 1
                    if not captain.feasible(q, self.max_overs - over - 1, bowler):
                        bowler = None
                if bowler is None:
                    skip = react.pop("skip", None) if react else None
                    pool = [p for p in fielders if p is not skip] if skip else fielders
                    if skip and not any(p is not last and quota_left.get(p, 0) > 0 for p in pool):
                        pool = fielders
                    bowler = captain.choose_bowler(pool, self.bowl.keeper, quota_left, self.max_overs - over,
                                                   last, ph, base, fmt, self.m.rng, base_of=self.m.base_of)
                if self.m.skill and not self.super_over:
                    bowler = self.m.loose_bowler(self, over, bowler, last, quota_left)
                if self.m.control:
                    bowler, changed = self.m.bowler_turn(self, over, bowler, last, quota_left, ph)
                    if changed:                # Impact Player came in: the rest chosen over by over
                        fielders, plan = self.bowl.players, None
            quota_left[bowler] = quota_left.get(bowler, 0) - 1
            self.bowl_over(over, bowler, ph, self.m.base_of(bowler)[ph])
            last = bowler
            if not self.done and self.legal % 6 == 0:
                self.striker, self.non_striker = self.non_striker, self.striker
            if (not self.done and self.number == 1 and self.m.impact_player and not self.super_over
                    and not self.m.manual(self.bowl, "impact")
                    and self.m.impact_mid_bowling(self, quota_left)):
                fielders = self.bowl.players   # a bowler came in: the rest of the innings is chosen over by over
                plan = None
        self.done = True
        left = [c for c in (self.striker, self.non_striker) if c.batted and not c.out]
        self.event(f"End of innings: {self.runs}/{self.wkts} ({self.over_str()} ov)" +
                   ("" if not left else " - " + ", ".join(f"{c.p.name} {c.runs}* ({c.balls}b)" for c in left)),
                   "end_of_innings")

    def react(self, plan, over: int, planned: Player, last: Player | None, quota_left: dict, fielders: list,
              st: dict) -> Player | None:
        """Reactive bowling changes (engine/fit/fit_reactive.py): a bowler's figures against what his ratings
        predicted move overs to or from him - runs above expectation cost overs, wickets above expectation earn
        them, by the amounts real captains move them. Done by chance at each over so the expected number of overs
        moved matches; None = take the planned bowler off (the captain picks someone else)."""
        k, rng = st["coef"], st["rng"]
        g = k.get("gain", 1.0)        # fitted so simulated captains react as strongly as real ones (fit_reactive)

        def delta(p):
            f = self.figs.get(p)
            return 0.0 if f is None else g * (k["per_run"] * (f.runs - f.exp_runs)
                                              + k["per_wicket"] * (f.wkts - f.exp_wkts))
        d = delta(planned)
        if d < 0:
            rem = sum(1 for x in plan.seq[over:] if x is planned) or 1
            q = min(1.0, max(0.0, -d - st["off"].get(planned, 0.0)) / rem)
            st["off"][planned] = st["off"].get(planned, 0.0) + q
            if q > 0 and rng.random() < q:
                self.event(f"{planned.name} is taken off after going for {self.figs[planned].runs} "
                           f"from {self.figs[planned].balls // 6} overs.", "bowling_change")
                st["skip"] = planned
                return None
        left = max(self.max_overs - over, 1)
        for p in fielders:
            if p is planned or p is last or quota_left.get(p, 0) <= 0 or p is self.bowl.keeper:
                continue
            d = delta(p)
            if d > 0:
                a = min(1.0, max(0.0, d - st["on"].get(p, 0.0)) / left)
                st["on"][p] = st["on"].get(p, 0.0) + a
                if a > 0 and rng.random() < a:
                    return p
        return planned

    def bowl_over(self, over: int, bowler: Player, ph: str, base: dict):
        f = self.fig(bowler)
        start_runs, start_wkts, conceded0 = self.runs, self.wkts, f.runs
        balls_in_over = 0
        btype = bowler.bowl_type or "unknown"
        seq = []
        while balls_in_over < 6 and not self.done:
            sit = self.m.sit.multipliers(1 if self.target is None else 2, self.legal + self.offset(), self.wkts, self.runs,
                                         self.target, self.striker.balls, self.par_k()) if self.m.use_situation else {}
            if self.m.use_matchups:
                sit = self.m.sit.with_matchup(sit, self.striker.p.bat_hand, bowler.bowl_kind)
            o = self.m.model.delivery(self.m.rng, base, self.striker.p, bowler, ph, btype, sit, self.free_hit)
            wp0 = self.m.wp_batting(self)
            striker = self.striker.p
            if o.legal:                       # counted first so events carry the ball they happened on
                balls_in_over += 1
                self.legal += 1
                ib, iw = self.striker.p.bat[ph], bowler.bowl[ph]
                f.exp_runs += base["runs"] * ib["runs"] * iw["runs"] + base["wide"] + base["noball"]
                f.exp_wkts += base["wkt"] * ib["wkt"] * iw["wkt"]
            self.apply(o, bowler, f, seq)
            self.free_hit = (o.extra == "nb") or (self.free_hit and o.extra == "w")
            if self.chase_won() or self.wkts >= self.max_wkts:
                self.done = True
            if not self.super_over:
                d = self.m.wp_batting(self) - wp0
                if o.faced:
                    self.m.wpa[striker.id] = self.m.wpa.get(striker.id, 0.0) + d
                self.m.wpa[bowler.id] = self.m.wpa.get(bowler.id, 0.0) - d
        if balls_in_over == 6 and f.runs == conceded0:
            f.maidens += 1
        runs = self.runs - start_runs
        wp_bat = self.m.wp_batting(self) if not self.super_over else None
        self.overs.append({"over": over + 1, "bowler": bowler.name, "runs": runs, "wkts": self.wkts - start_wkts,
                           "total": self.runs, "wickets": self.wkts, "balls": seq,
                           "win_prob": round(wp_bat, 3) if wp_bat is not None else None})
        big = 20 if self.m.fmt == "t20" else 18
        if runs >= big:
            self.event(f"{runs} runs off the over from {bowler.name} ({' '.join(seq)})", "big_over")

    def apply(self, o, bowler: Player, f: BowlFig, seq: list):
        s = self.striker
        total = o.bat_runs + o.extra_runs
        self.runs += total
        if o.extra:
            self.extras[o.extra] += o.extra_runs
        if o.faced:
            s.balls += 1
            self.pship["balls"] += 1
            if o.bat_runs == 0:
                s.dots += 1
        s.runs += o.bat_runs
        if o.bat_runs == 4:
            s.fours += 1
            f.fours += 1
        elif o.bat_runs == 6:
            s.sixes += 1
            f.sixes += 1
        self.pship["runs"] += total
        if total and not self.super_over:
            if (self.runs - total) // 50 < self.runs // 50:
                a, b = self.striker, self.non_striker
                self.event(f"{50 * (self.runs // 50)} up - {a.p.name} {a.runs}* ({a.balls}b), "
                           f"{b.p.name} {b.runs}* ({b.balls}b)", "team_50", runs=50 * (self.runs // 50))
            pr = self.pship["runs"]
            if (pr - total) // 50 < pr // 50:
                pa, pb = self.pship["a"].p.name, self.pship["b"].p.name
                self.event(f"{50 * (pr // 50)} partnership between {pa} and {pb} ({self.pship['balls']}b)",
                           "partnership", runs=50 * (pr // 50))
        if self.pship["a"] is s:
            self.pship["a_runs"] += o.bat_runs
        else:
            self.pship["b_runs"] += o.bat_runs
        if o.legal:
            f.balls += 1
            if total == 0:
                f.dots += 1
        f.runs += o.bat_runs + (o.extra_runs if o.extra in ("w", "nb") else 0)
        if o.extra == "w":
            f.wides += 1
        elif o.extra == "nb":
            f.noballs += 1
        # ball symbol for the over log
        if o.wicket:
            seq.append("W")
        elif o.extra == "w":
            seq.append(f"{o.extra_runs}wd" if o.extra_runs > 1 else "wd")
        elif o.extra == "nb":
            seq.append(f"{o.bat_runs}nb" if o.bat_runs else "nb")
        elif o.extra in ("b", "lb"):
            seq.append(f"{o.extra_runs}{o.extra}")
        else:
            seq.append(str(o.bat_runs) if o.bat_runs else ".")
        before = s.runs - o.bat_runs
        for mark in (50, 100, 150, 200):
            if before < mark <= s.runs:
                self.event(f"{s.p.name} reaches {mark} ({s.balls}b, {s.fours}x4, {s.sixes}x6)", "milestone",
                           player_id=s.p.id, player=s.p.name, mark=mark, balls=s.balls)
        if o.ran % 2 == 1:
            self.striker, self.non_striker = self.non_striker, self.striker
        if o.legal:
            if o.wicket and o.wicket != "run_out":
                self.streak[bowler] = self.streak.get(bowler, 0) + 1
                if self.streak[bowler] == 3:
                    self.event(f"Hat-trick for {bowler.name}!", "hat_trick")
            else:
                self.streak[bowler] = 0
        if o.wicket:
            self.wicket(o, bowler, f)

    def wicket(self, o, bowler: Player, f: BowlFig):
        if o.wicket == "run_out":
            # after any runs completed, the batter at the danger end is out
            out = self.non_striker if o.non_striker_out else self.striker
        else:
            out = self.striker
        fielders = [p for p in self.bowl.players if p is not self.bowl.keeper and p is not bowler]
        rng = self.m.rng
        k = o.wicket
        fielder = None
        if k in ("caught_keeper", "stumped"):
            fielder = self.bowl.keeper
        elif k == "caught_fielder":
            fielder = rng.choice(fielders) if fielders else bowler
        elif k == "caught_bowler":
            fielder = bowler
        elif k == "run_out":
            fielder = rng.choice(self.bowl.players)
        if k != "run_out":
            f.wkts += 1
        out.out = True
        out.how = {"kind": k, "bowler": bowler.name if k != "run_out" else None,
                   "bowler_id": bowler.id if k != "run_out" else None,
                   "fielder": fielder.name if fielder else None, "fielder_id": fielder.id if fielder else None,
                   "text": dismissal_text(k, bowler, fielder)}
        self.wkts += 1
        self.fow.append({"wkt": self.wkts, "runs": self.runs, "over": self.ball_str(), "batter": out.p.name})
        p = self.pship
        self.partnerships.append({"wkt": self.wkts, "runs": p["runs"], "balls": p["balls"],
                                  "batters": [p["a"].p.name, p["b"].p.name], "split": [p["a_runs"], p["b_runs"]]})
        new = None
        if self.wkts >= self.max_wkts or self.next_in >= len(self.cards):
            self.done = True
        else:
            if self.m.impact_player and not self.super_over and not self.m.manual(self.bat, "impact"):
                self.m.impact_mid_innings(self)
            j = self.pick_next()
            if self.m.skill and not self.super_over:
                j = self.m.loose_batter(self, j)
            if self.m.control and not self.super_over:
                j = self.m.batter_turn(self, j)
            if j != self.next_in:              # move the chosen batter up to the next slot
                self.cards.insert(self.next_in, self.cards.pop(j))
                for i, c in enumerate(self.cards):
                    c.pos = i + 1
            new = self.cards[self.next_in]
            new.batted = True
            self.next_in += 1
            if out is self.striker:
                self.striker = new
            else:
                self.non_striker = new
            self.pship = {"runs": 0, "balls": 0, "a": self.striker, "b": self.non_striker, "a_runs": 0,
                          "b_runs": 0}
        text = (f"{out.p.name} {out.how['text']} {out.runs} ({out.balls}b) {out.fours}x4 {out.sixes}x6"
                f" - partnership {p['runs']}" + (f" - new batter {new.p.name}" if new else ""))
        self.event(text, "wicket", player_id=out.p.id, partnership=p["runs"],
                   new_batter=new.p.name if new else None)
        if k != "run_out" and f.wkts >= 5:
            ov = f"{f.balls // 6}" + (f".{f.balls % 6}" if f.balls % 6 else "")
            self.event(f"{bowler.name} {ov}-{f.maidens}-{f.runs}-{f.wkts}", "five_wickets",
                       player_id=bowler.id, wickets=f.wkts)

    def pick_next(self) -> int:
        """Index of the next batter (design T1-7). Default: next in the order. Late in the innings with wickets
        in hand, promote the best death hitter among the next three; otherwise, when the next two are
        interchangeable (usual slots within 0.4), prefer a left/right pair with the batter at the
        crease. Off when the order was given explicitly (e.g. replays of real matches)."""
        i = self.next_in
        if self.bat.fixed_order or self.super_over or i >= len(self.cards) - 1:
            return i
        balls_left = self.max_overs * 6 - self.legal
        late = balls_left <= (30 if self.m.fmt == "t20" else 72)
        nxt = self.cards[i:i + 3]
        if late and self.wkts <= 6:
            def hit(c):
                d = c.p.bat["death"]
                return d["runs"] * (1 + 2 * d["six"])
            best = max(range(len(nxt)), key=lambda j: hit(nxt[j]) - 0.02 * j)
            return i + best
        stay = self.non_striker if self.striker.out else self.striker
        a, b = self.cards[i], self.cards[i + 1]
        pa, pb = captain.slot_position(a.p), captain.slot_position(b.p)
        if abs(pa - pb) <= 0.4 and stay.p.bat_hand and a.p.bat_hand == stay.p.bat_hand \
                and b.p.bat_hand and b.p.bat_hand != stay.p.bat_hand:
            return i + 1
        return i

    def close_partnership(self):
        p = self.pship
        if p["balls"] or p["runs"]:
            self.partnerships.append({"wkt": self.wkts + 1, "runs": p["runs"], "balls": p["balls"],
                                      "batters": [p["a"].p.name, p["b"].p.name], "split": [p["a_runs"], p["b_runs"]],
                                      "unbroken": True})

    # ------------------------------------------------------------------ output
    def to_dict(self) -> dict:
        bowl_order = list(self.figs.values())
        return {
            "number": self.number, "team": self.bat.name, "bowling_team": self.bowl.name,
            "runs": self.runs, "wickets": self.wkts, "balls": self.legal, "overs": self.over_str(),
            "target": self.target, "max_overs": self.max_overs, "rain_stopped": self.rain_stopped, "extras": dict(self.extras),
            "batting": [{"id": c.p.id, "name": c.p.name, "position": c.pos, "runs": c.runs, "balls": c.balls,
                         "fours": c.fours, "sixes": c.sixes, "dots": c.dots, "out": c.out,
                         "dismissal": (c.how or {}).get("text", "not out") if c.batted else "did not bat",
                         "how_out": c.how, "batted": c.batted,
                         "captain": c.p is self.bat.captain, "keeper": c.p is self.bat.keeper}
                        for c in self.cards],
            "bowling": [{"id": b.p.id, "name": b.p.name, "balls": b.balls, "overs": f"{b.balls // 6}.{b.balls % 6}",
                         "maidens": b.maidens, "runs": b.runs, "wickets": b.wkts, "wides": b.wides,
                         "noballs": b.noballs, "dots": b.dots, "fours": b.fours, "sixes": b.sixes,
                         "economy": round(6 * b.runs / b.balls, 2) if b.balls else None}
                        for b in bowl_order],
            "fall_of_wickets": self.fow, "partnerships": self.partnerships, "overs_log": self.overs,
        }


def dismissal_text(kind: str, bowler: Player, fielder: Player | None) -> str:
    if kind == "bowled":
        return f"b {bowler.name}"
    if kind == "lbw":
        return f"lbw b {bowler.name}"
    if kind == "caught_bowler":
        return f"c & b {bowler.name}"
    if kind in ("caught_keeper", "caught_fielder"):
        mark = "†" if kind == "caught_keeper" else ""
        return f"c {mark}{fielder.name} b {bowler.name}"
    if kind == "stumped":
        return f"st †{fielder.name} b {bowler.name}"
    if kind == "hit_wicket":
        return f"hit wicket b {bowler.name}"
    if kind == "run_out":
        return f"run out ({fielder.name})" if fielder else "run out"
    return kind


class Match:
    def __init__(self, fmt: str, team_a: dict, team_b: dict, comp: str | None = None, year: int = 2025,
                 venue: str | None = None, seed: int | None = None, toss: str | None = None,
                 decision: str | None = None, overs: int | None = None, use_situation: bool = True,
                 use_plan: bool = True, use_venue: bool = True, pitch: dict | None = None,
                 use_matchups: bool = True, use_pitch: bool = True, impact_player: bool | None = None,
                 rain_on: bool = False, use_spin: bool = True, use_reactive: bool = True,
                 control: dict | None = None, skill: dict | None = None):
        if fmt not in FORMATS:
            raise ValueError(f"format must be one of {sorted(FORMATS)}")
        self.fmt, self.year, self.venue = fmt, year, venue
        self.comp = comp or FORMATS[fmt]["intl"]
        self.seed = seed if seed is not None else random.randrange(1 << 30)
        self.rng = random.Random(self.seed)
        self.base = baseline(fmt, self.comp, year)
        # conditions: venue factor x the day's pitch (design T2-3/T2-4); `pitch` may fix {"runs", "wkt"}
        self.venue_info = conditions.venue_factor(fmt, venue) if use_venue else {"runs": 1.0, "wkt": 1.0,
                                                                                  "known": False, "name": venue}
        self.pitch = pitch or (conditions.draw_pitch(fmt, self.rng, self.comp) if use_pitch
                               else {"runs": 1.0, "wkt": 1.0})
        cr = self.venue_info["runs"] * self.pitch["runs"]
        cw = self.venue_info["wkt"] * self.pitch["wkt"]
        self.base = conditions.apply(self.base, cr, cw)
        # pace v spin: the ground's and the day's edge for spinners over seamers (engine/fit/fit_spin.py)
        self.use_reactive = use_reactive
        self.spin = conditions.spin_edge(fmt, venue, self.seed) if use_spin else {"runs": 0.0, "wkt": 0.0}
        self.base_type = conditions.by_type(self.base, self.spin, fmt)
        self.conditions = {"venue": venue, "venue_known": self.venue_info["known"],
                           "venue_runs": round(self.venue_info["runs"], 3), "venue_wkt": round(self.venue_info["wkt"], 3),
                           "pitch_runs": round(self.pitch["runs"], 3), "pitch_wkt": round(self.pitch["wkt"], 3),
                           "report": conditions.pitch_report(cr, cw)
                           + (f"; {sr}" if (sr := conditions.spin_report(self.spin)) else ""),
                           "spin_edge": {k: round(v, 3) for k, v in self.spin.items()}}
        self.model = BallModel(basics(fmt))
        self.sit = Situation(fmt, self.comp, year)
        self.use_situation = use_situation
        self.use_plan = use_plan
        self.use_matchups = use_matchups
        # XI selection from squads: its own random stream (so it doesn't shift the ball-by-ball stream), the venue,
        # and the scoring level of ground x day's pitch that the captain can see
        sel_rng = random.Random(zlib.crc32(f"xi|{self.seed}".encode()))
        ctx = {"rng": sel_rng, "venue": venue, "runs_factor": cr, "base": baseline(fmt, self.comp, year)}
        self.teams = [make_team(team_a, fmt, ctx), make_team(team_b, fmt, ctx)]
        self.overs = overs or FORMATS[fmt]["overs"]
        # rain (engine/rain.py): a real match's interruption pattern for the host country, own random stream
        self.rain_profile = rain.sample(fmt, venue, self.comp, self.seed) if rain_on and not overs else None
        self.dls = rain.DLS(self.sit, fmt)
        self.rain_log: list[str] = []
        self.no_result = False
        if self.rain_profile and "start" in self.rain_profile:
            self.overs = max(rain.MIN_OVERS[fmt], round(self.rain_profile["start"] * FORMATS[fmt]["overs"]))
            self.rain_log.append(f"Rain before the start: {self.overs} overs a side.")
        # IPL Impact Player rule (2023 onwards): one substitute per side, used at the innings break
        self.impact_player = impact_player if impact_player is not None else (self.comp == "ipl" and year >= 2023)
        self.toss_spec, self.decision_spec = toss, decision
        # manual captaincy (engine/control.py): team name -> controller, for the sides a person captains
        self.control = {t.name: control[t.name] for t in self.teams if control and t.name in control}
        self.key = f"{self.seed}|{self.teams[0].name}|{self.teams[1].name}"
        self.captain_log = {t.name: [] for t in self.teams if t.name in self.control}   # the person's calls, valued
        # weaker computer captains (engine/judge.py): team name -> (chance of a loose call, temperature in runs);
        # their own random stream, so expert sides play exactly as before
        self.skill = {t.name: judge.LEVELS[skill.get(t.name)] for t in self.teams
                      if skill and skill.get(t.name) in judge.LEVELS and skill.get(t.name) != "expert"}
        self.loose_rng = random.Random(zlib.crc32(f"loose|{self.seed}".encode()))
        self.innings: list[Innings] = []
        self.super_overs: list[Innings] = []
        self.wpa: dict[str, float] = {}

    def reactive(self, inn: "Innings") -> dict | None:
        """State for reactive bowling changes in this innings (own random stream), or None if off."""
        if not self.use_reactive:
            return None
        coef = captain.reactive_coef(self.fmt)
        if not coef:
            return None
        return {"coef": coef, "rng": random.Random(zlib.crc32(f"react|{self.seed}|{inn.number}".encode())),
                "off": {}, "on": {}}

    def base_of(self, p: Player) -> dict:
        """Phase baselines for this bowler's deliveries (spin or pace on today's pitch)."""
        return self.base_type.get(p.bowl_type or "", self.base)

    def wp_first(self, inn: "Innings") -> float:
        """Win probability of the side batting first, at the current state of `inn` (design T1-8)."""
        n, off = inn.max_overs * 6, inn.offset()
        if inn.number == 1:
            if inn.done or inn.wkts >= 10 or inn.legal >= n:
                return self.sit.win_prob_first(n + off, 9, inn.runs, inn.par_k(), off)
            return self.sit.win_prob_first(inn.legal + off, inn.wkts, inn.runs, inn.par_k(), off)
        need = inn.target - inn.runs
        if need <= 0:
            return 0.0
        if inn.wkts >= 10 or inn.legal >= n:
            return 0.5 if need == 1 else 1.0
        return 1.0 - self.sit.win_prob_chase(inn.legal + off, inn.wkts, need, inn.par_k())

    def wp_batting(self, inn: "Innings") -> float:
        if inn.super_over:
            return 0.5
        w = self.wp_first(inn)
        return w if inn.number == 1 else 1.0 - w

    def _slot_balls(self) -> list[float]:
        from .selection import model
        return (model(self.fmt) or {}).get("balls_by_slot") or [20.0] * 11

    def _apply_impact(self, team: Team, out: Player, inn: Player, need: str, when: str, gain: float,
                      inn_: "Innings | None" = None) -> None:
        team.players = [inn if p is out else p for p in team.players]
        team.bench = [out if p is inn else p for p in team.bench]
        team.impact = {"in": inn.name, "in_id": inn.id, "out": out.name, "out_id": out.id, "for": need,
                       "when": when, "gain": round(gain, 1)}
        if inn_ is not None:
            team.impact.update(innings=inn_.number, score=f"{inn_.runs}/{inn_.wkts}")

    def impact_swap(self, team: Team, need: str) -> None:
        if self.loose(team):
            return
        """Impact Player at the innings break (engine/impact.py): the biggest team-value gain in the discipline
        still to come (`need`: "bowl" for the side that batted, "bat" for the chasing side)."""
        from . import impact
        if team.impact or not team.bench:
            return
        best = impact.best_break_swap(team, need, self.fmt, self.base, self._slot_balls())
        if not best:
            return
        gain, out, inn = best
        self._apply_impact(team, out, inn, need, "innings break", gain)
        if need == "bat":
            team.order = [inn if p is out else p for p in team.order] if team.fixed_order else captain.batting_order(team.players)
        else:
            team.order = [inn if p is out else p for p in team.order]

    def impact_mid_innings(self, inn_: "Innings") -> None:
        if self.loose(inn_.bat):
            return
        """Batting side, at the fall of a wicket: bring in a batter now if the runs he adds beat what waiting is
        worth (first innings: the bowler the side could bring in at the break) - engine/impact.py rule 2."""
        from . import impact
        team = inn_.bat
        if team.impact or not team.bench:
            return
        brk = None
        if inn_.number == 1:
            b = impact.best_break_swap(team, "bowl", self.fmt, self.base, self._slot_balls())
            brk = b[0] if b else 0.0
        pick = impact.batting_swap(team, inn_.cards, inn_.next_in, inn_.wkts,
                                   inn_.legal + (FORMATS[self.fmt]["overs"] - inn_.max_overs) * 6, self.fmt,
                                   self.base, brk)
        if not pick:
            return
        gain, out, new, i, need = pick
        self._apply_impact(team, out, new, need, f"after {inn_.ball_str()} overs", gain, inn_)
        team.order = [new if p is out else p for p in team.order]
        inn_.cards = [c for k, c in enumerate(inn_.cards) if k < inn_.next_in or c.p is not out]
        inn_.cards.insert(inn_.next_in + i, BatInns(new, 0))
        for k, c in enumerate(inn_.cards):
            c.pos = k + 1

    def impact_mid_bowling(self, inn_: "Innings", quota_left: dict) -> bool:
        if self.loose(inn_.bowl):
            return False
        """Bowling first, at the end of an over: bring in a bowler now if the better remaining overs beat the
        batter the side could bring in for the chase (engine/impact.py rule 3)."""
        from . import impact
        team = inn_.bowl
        if team.impact or not team.bench:
            return False
        brk = impact.best_break_swap(team, "bat", self.fmt, self.base, self._slot_balls())
        pick = impact.bowling_swap(team, quota_left, inn_.max_overs - inn_.legal // 6, self.fmt, self.base,
                                   self._slot_balls(), brk[0] if brk else 0.0)
        if not pick:
            return False
        gain, out, new, need = pick
        self._apply_impact(team, out, new, need, f"after {inn_.ball_str()} overs", gain, inn_)
        team.order = [new if p is out else p for p in team.order]
        quota_left[new] = rain.quota(inn_.max_overs)
        quota_left.pop(out, None)
        return True

    # ------------------------------------------------------------------ manual captaincy (engine/control.py)
    # ---------------------------------------------------------------- weaker captains and the report (judge.py)
    def loose(self, team: Team):
        """(chance, temperature) when this computer side makes a loose call now, else None."""
        s = self.skill.get(team.name)
        return s if s and self.loose_rng.random() < s[0] else None

    def valid_bowlers(self, team: Team, quota_left: dict, left: int, last: Player | None) -> list:
        """Who may bowl the next over: overs left in his quota, not the last over's bowler, and the rest of the
        innings still possible without consecutive overs (the keeper only if no one else can)."""
        out = []
        for p in team.players:
            if p is last or quota_left.get(p, 0) <= 0:
                continue
            q = dict(quota_left)
            q[p] -= 1
            if captain.feasible(q, left - 1, p):
                out.append(p)
        return [p for p in out if p is not team.keeper] or out

    def loose_bowler(self, inn: "Innings", over: int, bowler: Player, last: Player | None, quota_left: dict):
        s = self.loose(inn.bowl)
        if not s:
            return bowler
        opts = self.valid_bowlers(inn.bowl, quota_left, inn.max_overs - over, last)
        if len(opts) < 2:
            return bowler
        return judge.pick(judge.bowler_values(self, inn, over, opts, quota_left), s[1], self.loose_rng) or bowler

    def loose_batter(self, inn: "Innings", j: int) -> int:
        s = self.loose(inn.bat)
        cands = [c.p for c in inn.cards[inn.next_in:inn.next_in + 4]]
        if not s or len(cands) < 2:
            return j
        p = judge.pick(judge.batter_values(self, inn, cands), s[1], self.loose_rng)
        return next(k for k in range(inn.next_in, len(inn.cards)) if inn.cards[k].p is p)

    def loose_xi(self, team: Team) -> None:
        """A loose captain may leave out a better player: one swap with the bench, likelier the less it costs."""
        s = self.loose(team)
        bench = [p for p in (team.squad or []) if p not in team.players and p not in team.bench] + list(team.bench)
        if not s or not bench:
            return
        now = judge.xi_value(self, team.order, team.keeper)
        opts = {}
        for out in team.players:
            if out is team.keeper:
                continue
            for new in bench:
                if team.max_overseas is not None and new.overseas and not out.overseas \
                        and sum(p.overseas for p in team.players) >= team.max_overseas:
                    continue
                xi = [new if p is out else p for p in team.players]
                opts[(out, new)] = judge.xi_value(self, captain.batting_order(xi), team.keeper) - now
        if not opts:
            return
        out, new = judge.pick(opts, s[1], self.loose_rng)
        team.players = [new if p is out else p for p in team.players]
        team.order = captain.batting_order(team.players)
        if new in team.bench:
            team.bench = [out if p is new else p for p in team.bench]
        if team.captain is out:
            team.captain = max(team.players, key=lambda p: p.bat_balls + p.bowl_balls)

    def log(self, team: Team, kind: str, when: str, you, computer, delta: float | None = None) -> None:
        """One of the person's calls for the captaincy report (delta = runs gained against the computer's call)."""
        if team.name not in self.captain_log:
            return
        name = lambda x: x.name if isinstance(x, Player) else x
        self.captain_log[team.name].append({"kind": kind, "when": when, "you": name(you), "computer": name(computer),
                                            "changed": name(you) != name(computer),
                                            "delta": None if delta is None else round(delta, 2)})

    def manual(self, team: Team, kind: str, inn: "Innings | None" = None) -> bool:
        ctl = self.control.get(team.name)
        return bool(ctl and ctl.manual(kind, self.key, inn.number if inn else None))

    def ask(self, team: Team, kind: str, payload: dict, inn: "Innings | None" = None, skip_inn: bool = True):
        """The person's answer for `team` (None = the computer's choice, also when the decision isn't theirs)."""
        if not self.manual(team, kind, inn if skip_inn else None):
            return None
        q = {"kind": kind, "team": team.name, "match_key": self.key,
             "innings": inn.number if inn and skip_inn else None,
             "state": self.live(inn) if inn else self.pre_state(team), **payload}
        return self.control[team.name].decide(q)

    def pre_state(self, team: Team) -> dict:
        a, b = self.teams
        return {"match": f"{a.name} v {b.name}", "venue": self.venue, "pitch": self.conditions["report"],
                "format": self.fmt, "overs": self.overs, "rain": list(self.rain_log),
                "opponent": (b if team is a else a).name}

    def live(self, inn: "Innings") -> dict:
        """The scorecard so far, for a person captaining: score, chase, batters, bowlers, recent overs, events."""
        st = self.pre_state(inn.bat)
        balls_left = inn.max_overs * 6 - inn.legal
        st.update({
            "innings": inn.number, "batting": inn.bat.name, "bowling": inn.bowl.name, "runs": inn.runs,
            "wkts": inn.wkts, "overs_done": inn.over_str(), "max_overs": inn.max_overs, "target": inn.target,
            "crr": round(6 * inn.runs / inn.legal, 2) if inn.legal else None,
            "need": inn.target - inn.runs if inn.target else None, "balls_left": balls_left,
            "rrr": round(6 * (inn.target - inn.runs) / balls_left, 2) if inn.target and balls_left > 0 else None,
            "win_prob": round(self.wp_batting(inn), 3) if not inn.super_over else None,
            "previous": [f"{i.bat.name} {i.score_str()} ({i.over_str()} ov)" for i in self.innings_so_far()
                         if i is not inn],
            "batters": [{"name": c.p.name, "runs": c.runs, "balls": c.balls, "fours": c.fours, "sixes": c.sixes,
                         "out": c.out, "how": (c.how or {}).get("text"), "batted": c.batted,
                         "on_strike": c is inn.striker and not c.out,
                         "at_crease": c in (inn.striker, inn.non_striker) and not c.out}
                        for c in inn.cards],
            "bowlers": [{"name": f.p.name, "overs": f"{f.balls // 6}.{f.balls % 6}", "maidens": f.maidens,
                         "runs": f.runs, "wkts": f.wkts} for f in inn.figs.values()],
            "partnership": {"runs": inn.pship["runs"], "balls": inn.pship["balls"]},
            "recent": [{"over": o["over"], "bowler": o["bowler"], "balls": o["balls"], "runs": o["runs"]}
                       for o in inn.overs[-4:]],
            "events": [e["over"] + " " + e["text"] for e in inn.events[-6:]],
        })
        return st

    def innings_so_far(self) -> list:
        return [i for i in (getattr(self, "_i1", None), getattr(self, "_i2", None)) if i is not None]

    def pinfo(self, p: Player, ph: str | None = None) -> dict:
        """What a captain sees about a player: role, career numbers, and expected rates in this phase today."""
        r = p.ref or {}
        b, w = r.get("bat") or {}, r.get("bowl") or {}
        if p.keeper:
            role = "WK"
        elif (p.bowl_role or "").startswith("spec"):
            role = ("All-rounder" if p.bat_role in ("top", "middle") else
                    "Spin" if p.bowl_type == "spin" else "Pace")
        else:
            role = "Batter"
        d = {"id": p.id, "name": p.name, "role": role, "hand": p.bat_hand, "overseas": p.overseas,
             "kind": (p.bowl_kind or "").replace("_", " "), "slot": p.usual_slot,
             "bat_avg": b.get("avg"), "bat_sr": b.get("sr"),
             "bowl_econ": w.get("econ") if p.rated_bowl else None, "bowl_avg": w.get("avg") if p.rated_bowl else None,
             "overs_per_match": round(p.bowl_overs_per_match, 1)}
        if ph:
            bb, bw = self.base[ph], self.base_of(p)[ph]
            d["phase"] = ph
            d["phase_sr"] = round(100 * bb["runs"] * p.bat[ph]["runs"], 1)
            d["phase_econ"] = round(6 * (bw["runs"] * p.bowl[ph]["runs"] + bw["wide"] * p.wide
                                         + bw["noball"] * p.noball), 2)
        return d

    def ask_xi(self, team: Team, batting_first: bool, toss: str) -> None:
        """The XI (in batting order), keeper and Impact Player substitutes, after the toss."""
        from .impact import N_SUBS
        squad = team.squad or team.players + team.bench
        imp = bool(self.impact_player)
        default = {"xi": [p.id for p in team.order], "keeper": team.keeper.id,
                   "subs": [p.id for p in team.bench] if imp else []}
        ans = self.ask(team, "xi", {"options": [self.pinfo(p) for p in squad], "default": default,
                                    "max_overseas": team.max_overseas, "n_subs": N_SUBS if imp else 0,
                                    "batting_first": batting_first, "toss": toss})
        if not isinstance(ans, dict):
            if self.manual(team, "xi"):
                self.log(team, "xi", "after the toss", "the computer's XI", "the computer's XI", 0.0)
            return
        by = {p.id: p for p in squad}
        xi = [by[i] for i in ans.get("xi") or [] if i in by]
        keeper = by.get(ans.get("keeper"))
        if len(set(xi)) != 11 or len(xi) != 11 or keeper not in xi:
            return
        if team.max_overseas is not None and sum(p.overseas for p in xi) > team.max_overseas:
            return
        before = judge.xi_value(self, team.order, team.keeper)
        same = [p.id for p in xi] == default["xi"] and keeper.id == default["keeper"]
        self.log(team, "xi", "after the toss", "your XI" if not same else "the computer's XI", "the computer's XI",
                 judge.xi_value(self, xi, keeper) - before)
        team.players, team.order, team.keeper = xi, list(xi), keeper
        if imp:
            subs = [by[i] for i in ans.get("subs") or [] if i in by and by[i] not in xi]
            team.bench = list(dict.fromkeys(subs))[:N_SUBS]
        else:
            team.bench = [p for p in squad if p not in xi]
        if team.captain not in xi:
            team.captain = max(xi, key=lambda p: p.bat_balls + p.bowl_balls)

    def impact_block(self, team: Team, inn: "Innings | None", sugg: dict | None, batting: bool) -> dict:
        """The Impact Player options for a decision screen: who can go out, who can come in, the computer's
        suggestion (None = it would wait)."""
        at_crease = {c.p for c in (inn.striker, inn.non_striker)} if inn is not None and batting else set()
        return {"outs": [self.pinfo(p) for p in team.players if p is not team.keeper and p not in at_crease],
                "ins": [self.pinfo(p) for p in team.bench], "max_overseas": team.max_overseas,
                "overseas_in_xi": sum(p.overseas for p in team.players), "suggestion": sugg}

    def manual_impact(self, team: Team, choice: dict | None, inn: "Innings | None", quota_left: dict | None = None,
                      when: str = "", index: int | None = None) -> bool:
        """Make the person's Impact Player substitution, if allowed. Batting: the new player takes the place of the
        one going out in the order still to come (or goes in next if that player has batted)."""
        from .impact import _allowed
        if not isinstance(choice, dict) or team.impact:
            return False
        out = next((p for p in team.players if p.id == choice.get("out")), None)
        new = next((p for p in team.bench if p.id == choice.get("in")), None)
        if out is None or new is None or out is team.keeper or not _allowed(team.players, team.max_overseas, out, new):
            return False
        batting = inn is not None and inn.bat is team
        if batting and any(c.p is out and not c.out for c in (inn.striker, inn.non_striker)):
            return False
        need = choice.get("for") or ("bat" if batting else "bowl")
        self._apply_impact(team, out, new, need, when or (f"after {inn.ball_str()} overs" if inn else "innings break"),
                           float(choice.get("gain") or 0.0), inn)
        team.order = [new if p is out else p for p in team.order]
        if batting:
            rem = [c.p for c in inn.cards[inn.next_in:]]
            if out in rem and index is None:
                inn.cards[inn.next_in + rem.index(out)] = BatInns(new, 0)
            else:
                inn.cards = [c for k, c in enumerate(inn.cards) if k < inn.next_in or c.p is not out]
                inn.cards.insert(inn.next_in + (index or 0), BatInns(new, 0))
            for k, c in enumerate(inn.cards):
                c.pos = k + 1
        if quota_left is not None:
            quota_left[new] = rain.quota(inn.max_overs) if inn else FORMATS[self.fmt]["quota"]
            quota_left.pop(out, None)
        return True

    def ask_break_impact(self, team: Team, need: str, i1: "Innings") -> None:
        """Innings break: the person's Impact Player call (the computer's suggestion is its own break swap)."""
        from . import impact
        if team.impact or not team.bench:
            return
        best = impact.best_break_swap(team, need, self.fmt, self.base, self._slot_balls())
        sugg = {"out": best[1].id, "in": best[2].id, "gain": round(best[0], 1), "for": need} if best else None
        ans = self.ask(team, "impact", {"default": sugg, "moment": "innings break", "for": need,
                                        "impact": self.impact_block(team, None, sugg, False)}, i1, skip_inn=False)
        if ans is None:
            self.impact_swap(team, need)          # the computer's choice
            self.log(team, "impact", "innings break", self._sub_text(sugg), self._sub_text(sugg))
        else:
            done = isinstance(ans, dict) and ans.get("in") and \
                self.manual_impact(team, {**ans, "for": need}, None, when="innings break")
            self.log(team, "impact", "innings break", self._sub_text(ans) if done else "wait", self._sub_text(sugg))

    def bowler_turn(self, inn: "Innings", over: int, default: Player, last: Player | None, quota_left: dict,
                    ph: str) -> tuple[Player, bool]:
        """Each over in the field: the person's bowler (and Impact Player substitution, if made). Returns
        (bowler, whether the substitution was made)."""
        from . import impact
        team = inn.bowl
        if team.name not in self.control:
            return default, False
        left = inn.max_overs - over

        def valid():
            return self.valid_bowlers(team, quota_left, left, last)
        imp_ok = self.impact_player and not team.impact and team.bench and self.manual(team, "impact", inn)
        sugg = None
        if imp_ok and inn.number == 1:            # the computer's own rule 3 (bowling first)
            brk = impact.best_break_swap(team, "bat", self.fmt, self.base, self._slot_balls())
            pick = impact.bowling_swap(team, quota_left, inn.max_overs - inn.legal // 6, self.fmt, self.base,
                                       self._slot_balls(), brk[0] if brk else 0.0)
            if pick:
                sugg = {"out": pick[1].id, "in": pick[2].id, "gain": round(pick[0], 1), "for": pick[3]}
        opts = valid()
        block = self.impact_block(team, inn, sugg, False) if imp_ok else None
        asked = self.manual(team, "bowler", inn) and (len(opts) > 1 or sugg)
        if asked:
            ans = self.ask(team, "bowler", {"options": [dict(self.pinfo(p, ph), quota_left=quota_left.get(p, 0))
                                                        for p in opts],
                                            "default": default.id, "over": over + 1, "impact": block}, inn)
            if ans is None:
                ans = {"bowler": default.id, "impact": sugg}
        elif sugg:                                 # bowler left to the computer: ask only when it would sub now
            a = self.ask(team, "impact", {"default": sugg, "moment": f"before over {over + 1}", "for": sugg["for"],
                                          "impact": block}, inn)
            ans = {"bowler": default.id, "impact": sugg if a is None else a}
        else:
            return default, False
        ans = ans if isinstance(ans, dict) else {}
        changed = self.manual_impact(team, ans.get("impact"), inn, quota_left)
        if changed:
            opts = valid()
        pick = next((p for p in opts if p.id == ans.get("bowler")), None)
        if pick is None:
            pick = default if default in opts else captain.choose_bowler(
                team.players, team.keeper, quota_left, left, last, ph, self.base[ph], self.fmt, self.rng,
                base_of=self.base_of)
        imp = ans.get("impact")
        if self.manual(team, "impact", inn) and (sugg or changed):
            self.log(team, "impact", f"over {over + 1}", self._sub_text(imp) if changed else "wait",
                     self._sub_text(sugg) if sugg else "wait")
        if asked:
            d = None
            if not changed and default in opts:
                d = 0.0 if pick is default else (lambda v: v[pick] - v[default])(
                    judge.bowler_values(self, inn, over, [pick, default], quota_left))
            self.log(team, "bowler", f"over {over + 1}", pick, default, d)
        return pick, changed

    def _sub_text(self, s: dict | None) -> str:
        if not isinstance(s, dict) or not s.get("in"):
            return "wait"
        by = {p.id: p.name for t in self.teams for p in (t.squad or t.players + t.bench)}
        return f"{by.get(s['in'], s['in'])} for {by.get(s.get('out'), s.get('out'))}"

    def batter_turn(self, inn: "Innings", j: int) -> int:
        """At the fall of a wicket: the person's next batter (and Impact Player substitution, if made). Returns
        the index in inn.cards of the batter going in."""
        from . import impact
        team = inn.bat
        if team.name not in self.control:
            return j
        ph = phase_at(min(inn.legal // 6, inn.max_overs - 1), self.fmt, inn.max_overs)
        imp_ok = self.impact_player and not team.impact and team.bench and self.manual(team, "impact", inn)
        sugg = None
        if imp_ok:                                 # the computer's own rule 2
            brk = None
            if inn.number == 1:
                b = impact.best_break_swap(team, "bowl", self.fmt, self.base, self._slot_balls())
                brk = b[0] if b else 0.0
            pick = impact.batting_swap(team, inn.cards, inn.next_in, inn.wkts, inn.legal + inn.offset(), self.fmt,
                                       self.base, brk)
            if pick:
                sugg = {"out": pick[1].id, "in": pick[2].id, "gain": round(pick[0], 1), "for": pick[4],
                        "index": pick[3]}
        rem = inn.cards[inn.next_in:]
        block = self.impact_block(team, inn, sugg, True) if imp_ok else None
        default = inn.cards[j].p
        asked = self.manual(team, "batter", inn) and (len(rem) > 1 or sugg)
        if asked:
            ans = self.ask(team, "batter", {"options": [self.pinfo(c.p, ph) for c in rem], "default": default.id,
                                            "impact": block}, inn)
            if ans is None:
                ans = {"batter": None, "impact": sugg}
        elif sugg:
            a = self.ask(team, "impact", {"default": sugg, "moment": f"after the fall of wicket {inn.wkts}",
                                          "for": sugg["for"], "impact": block}, inn)
            ans = {"batter": None, "impact": sugg if a is None else a}
        else:
            return j
        ans = ans if isinstance(ans, dict) else {}
        imp = ans.get("impact")
        same = bool(sugg and isinstance(imp, dict) and imp.get("out") == sugg["out"] and imp.get("in") == sugg["in"])
        subbed = self.manual_impact(team, imp, inn, index=sugg["index"] if same else None)
        if subbed:
            j = inn.pick_next()
        k = next((i for i in range(inn.next_in, len(inn.cards)) if inn.cards[i].p.id == ans.get("batter")), None)
        k = k if k is not None else j
        when = f"wicket {inn.wkts} ({inn.ball_str()} ov)"
        if self.manual(team, "impact", inn) and (sugg or subbed):
            self.log(team, "impact", when, self._sub_text(imp) if subbed else "wait",
                     self._sub_text(sugg) if sugg else "wait")
        if asked:
            you = inn.cards[k].p
            d = None if subbed else 0.0 if you is default else (lambda v: v[you] - v[default])(
                judge.batter_values(self, inn, [you, default]))
            self.log(team, "batter", when, you, default, d)
        return k

    def play(self) -> dict:
        a, b = self.teams
        toss_winner = {"a": a, "b": b}.get(self.toss_spec) or (a if self.rng.random() < 0.5 else b)
        decision = self.decision_spec or captain.toss_decision(self.fmt, self.rng, self.venue)
        if not self.decision_spec and self.loose(toss_winner):
            decision = "bowl" if decision == "bat" else "bat"
        ans = self.ask(toss_winner, "toss", {"options": ["bat", "bowl"], "default": decision,
                                             "text": f"{toss_winner.name} won the toss."})
        if self.manual(toss_winner, "toss"):
            self.log(toss_winner, "toss", "toss", ans if ans in ("bat", "bowl") else decision, decision)
        if ans in ("bat", "bowl"):
            decision = ans
        first = toss_winner if decision == "bat" else (b if toss_winner is a else a)
        second = b if first is a else a
        toss_text = f"{toss_winner.name} won the toss and chose to {decision}."
        for t, bat_first in ((first, True), (second, False)):
            if self.impact_player:             # XI and substitutes are named after the toss
                from .impact import choose_xi
                choose_xi(t, bat_first, self.fmt, self.base, self._slot_balls())
            if t.name in self.skill:
                self.loose_xi(t)
            if t.name in self.control:
                self.ask_xi(t, bat_first, toss_text)
        i1 = self._i1 = Innings(self, first, second, 1, None, self.overs)
        i1.play()
        i1.close_partnership()
        self.innings_first_runs = i1.runs
        if self.impact_player:
            for t, need in ((first, "bowl"), (second, "bat")):
                # batted first: the best bowler for the defence; has bowled: the best batter for the chase
                if self.manual(t, "impact"):
                    self.ask_break_impact(t, need, i1)
                else:
                    self.impact_swap(t, need)
        p = self.rain_profile or {}
        if "stop1" in p:                       # washed out during the first innings or at the break
            self.no_result = True
            self.rain_log.append("Rain: no further play possible.")
            self.innings = [i1]
            result = {"type": "no_result", "winner": None, "text": "No result"}
        else:
            m2 = self.chase_overs(i1)
            i2 = self._i2 = Innings(self, second, first, 2, self.dls.target(i1.runs), m2)
            if i2.target != i1.runs + 1:
                self.rain_log.append(f"{second.name} need {i2.target} from {m2} overs (DLS).")
            i2.play()
            i2.close_partnership()
            self.innings = [i1, i2]
            result = self.result(i1, i2)
        if result["type"] == "tie" and not result.get("no_super_over"):
            result = self.play_super_overs(first, second, result)
        card = {
            "format": self.fmt, "competition": self.comp, "year": self.year, "venue": self.venue, "seed": self.seed,
            "overs": self.overs, "teams": [a.name, b.name],
            "xi": {t.name: [{"id": p.id, "name": p.name, "rated": p.rated_bat or p.rated_bowl} for p in t.order]
                   for t in self.teams},
            "impact_player": {t.name: t.impact for t in self.teams if t.impact},
            "rain": self.rain_log,
            "toss": {"winner": toss_winner.name, "decision": decision}, "conditions": self.conditions,
            "innings": [i.to_dict() for i in self.innings],
            "super_overs": [i.to_dict() for i in self.super_overs],
            "result": result,
            "events": [e for i in self.innings + self.super_overs for e in i.events],
        }
        card["impact"] = {pid: round(v, 3) for pid, v in sorted(self.wpa.items(), key=lambda kv: -kv[1])}
        if self.captain_log:
            card["captaincy"] = self.captain_log
        # runs worth one whole win at the break (slope of the chase win model at an average target): converts win
        # probability added into runs for the player of the match
        s = round(self.sit.scale)
        card["runs_per_win"] = round(10 / max(self.sit.win_prob_chase(0, 0, s - 5)
                                              - self.sit.win_prob_chase(0, 0, s + 5), 1e-3), 1)
        card["player_of_match"] = player_of_match(card, self.fmt)
        tp = turning_point(card)
        if tp:
            card["turning_point"] = tp
            card["events"].append({"innings": tp["innings"], "over": str(tp["over"]), "score": tp["score"],
                                   "kind": "turning_point", "text": tp["text"]})
        for t in self.teams:
            if t.name in self.control:
                self.ask(t, "result", {"result": result["text"], "pom": card["player_of_match"],
                                       "scores": [f"{i.bat.name} {i.score_str()} ({i.over_str()} ov)"
                                                  for i in self.innings]}, self.innings[-1])
        return card

    def chase_overs(self, i1: Innings) -> int:
        """Overs for the chase and DLS resources after the first innings (engine/rain.py)."""
        d, p, sched = self.dls, self.rain_profile or {}, FORMATS[self.fmt]["overs"]
        m1 = i1.max_overs
        d.r1 = d.res(m1 * 6, 0) - (d.res(*self._cut1) if getattr(self, "_cut1", None) else 0.0)
        m2 = m1
        if "o2" in p:
            m2f = min(m1, max(rain.MIN_OVERS[self.fmt], round(p["o2"] * sched)))
            self._m2_final = m2f
            if "cut1" in p or int(p["u"] * m2f) == 0:
                m2 = m2f                       # reduced before the chase starts
                if m2 < m1:
                    self.rain_log.append(f"Rain at the break: the chase is reduced to {m2} overs.")
        d.r2 = d.res(m2 * 6, 0)
        return m2

    def rain_check(self, inn: Innings, over: int):
        """At the start of an over: None, "stop" (no more play in this innings) or "reduce" (overs cut)."""
        p, d, sched = self.rain_profile, self.dls, FORMATS[self.fmt]["overs"]
        if inn.number == 1:
            k = p.get("stop1", p.get("cut1"))
            if k is not None and k < 1 and over == int(k * sched):
                if "cut1" in p:
                    self._cut1 = (inn.max_overs * 6 - inn.legal, inn.wkts)
                    inn.event(f"Rain: the innings ends at {inn.score_str()} after {inn.over_str()} overs.", "rain")
                else:
                    inn.event(f"Rain stops play at {inn.score_str()} after {inn.over_str()} overs.", "rain")
                return "stop"
            return None
        m2f = getattr(self, "_m2_final", inn.max_overs)
        if "o2" in p and inn.max_overs > m2f and over == max(1, int(p["u"] * m2f)):
            lost = d.res(inn.max_overs * 6 - inn.legal, inn.wkts) - d.res(m2f * 6 - inn.legal, inn.wkts)
            d.r2 -= lost
            inn.max_overs = m2f
            inn.target = d.target(self.innings_first_runs)
            msg = f"Rain: the chase is reduced to {m2f} overs; revised target {inn.target} (DLS)."
            inn.event(msg, "rain")
            self.rain_log.append(msg)
            return "reduce"
        if "stop2" in p:
            k2 = max(int(p["stop2"] * m2f), max(1, int(p.get("u", 0) * m2f)) if "o2" in p else 0)
            if over == k2:
                inn.rain_stopped = True
                inn.event(f"Rain stops play at {inn.score_str()} after {inn.over_str()} overs.", "rain")
                self.rain_log.append(f"Rain stopped play in the chase at {inn.score_str()} ({inn.over_str()} ov).")
                return "stop"
        return None

    def result(self, i1: Innings, i2: Innings) -> dict:
        dls = i2.target != i1.runs + 1 or i2.rain_stopped or bool(self.dls.r2 is not None and self.dls.r2 != self.dls.r1)
        tag = " (DLS method)" if dls else ""
        if i2.runs >= i2.target:
            w = 10 - i2.wkts
            left = i2.max_overs * 6 - i2.legal
            return {"type": "win", "winner": i2.bat.name, "loser": i1.bat.name, "by": "wickets", "margin": w,
                    "balls_left": left, "dls": dls,
                    "text": f"{i2.bat.name} won by {w} wicket{'s' if w != 1 else ''} ({left} ball{'s' if left != 1 else ''} left){tag}"}
        if i2.rain_stopped:
            if i2.legal < rain.MIN_OVERS[self.fmt] * 6:
                return {"type": "no_result", "winner": None, "text": "No result"}
            used = self.dls.r2 - self.dls.res(i2.max_overs * 6 - i2.legal, i2.wkts)
            par = int(self.dls.par(i1.runs, used))
            self.rain_log.append(f"DLS par score at the stoppage: {par}.")
            if i2.runs > par:
                w = 10 - i2.wkts
                return {"type": "win", "winner": i2.bat.name, "loser": i1.bat.name, "by": "wickets", "margin": w,
                        "dls": True, "par": par,
                        "text": f"{i2.bat.name} won by {w} wicket{'s' if w != 1 else ''} (DLS method, par {par})"}
            if i2.runs == par:
                return {"type": "tie", "winner": None, "no_super_over": True, "dls": True, "par": par,
                        "text": f"Match tied (DLS method, par {par})"}
            r = par - i2.runs
            return {"type": "win", "winner": i1.bat.name, "loser": i2.bat.name, "by": "runs", "margin": r,
                    "dls": True, "par": par, "text": f"{i1.bat.name} won by {r} run{'s' if r != 1 else ''} (DLS method)"}
        r = i2.target - 1 - i2.runs
        if r > 0:
            return {"type": "win", "winner": i1.bat.name, "loser": i2.bat.name, "by": "runs", "margin": r,
                    "dls": dls, "text": f"{i1.bat.name} won by {r} run{'s' if r != 1 else ''}{tag}"}
        return {"type": "tie", "winner": None, "dls": dls, "text": "Match tied" + tag}

    def play_super_overs(self, first: Team, second: Team, result: dict) -> dict:
        """Super overs until there is a winner; the side that batted second bats first in the super over."""
        bat_first, bat_second = second, first
        for n in range(1, 21):
            base = self.base["death"]
            bats1, bowler1 = captain.super_over_picks(bat_first.players, base, self.fmt)
            bats2, bowler2 = captain.super_over_picks(bat_second.players, base, self.fmt)
            s1 = Innings(self, bat_first, bat_second, 100 + 2 * n - 1, None, 1, max_wkts=2, order=bats1,
                         bowlers=[bowler2], super_over=True)
            s1.play()
            s2 = Innings(self, bat_second, bat_first, 100 + 2 * n, s1.runs + 1, 1, max_wkts=2, order=bats2,
                         bowlers=[bowler1], super_over=True)
            s2.play()
            self.super_overs += [s1, s2]
            if s1.runs != s2.runs:
                w, l = (s1, s2) if s1.runs > s2.runs else (s2, s1)
                so = "super over" if n == 1 else f"{n} super overs"
                return {"type": "win", "winner": w.bat.name, "loser": l.bat.name, "by": "super_over",
                        "margin": None, "text": f"Match tied; {w.bat.name} won the {so} "
                                                f"({s1.bat.name} {s1.runs}/{s1.wkts}, {s2.bat.name} {s2.runs}/{s2.wkts})"}
            bat_first, bat_second = bat_second, bat_first  # the next super over is batted the other way round
        return result


def player_of_match(card: dict, fmt: str) -> dict:
    """Balanced score (runs and wickets, credit for scoring faster / conceding slower than the match rate,
    catches, a bonus for the winning side; the Test sim's motmscore) plus win probability added converted into
    runs (card["runs_per_win"]). Both count: win probability alone handed the award to a 6 off 3 balls in a close
    finish over the innings that built the win."""
    inns = card["innings"]
    balls = sum(i["balls"] for i in inns) or 1
    rate = sum(i["runs"] for i in inns) / balls          # runs per ball in this match
    wkt_val = 20 if fmt == "t20" else 25
    score: dict = {}
    names = {}
    team_of = {}
    for i in inns:
        for b in i["batting"]:
            if not b["batted"]:
                continue
            names[b["id"]] = b["name"]
            team_of[b["id"]] = i["team"]
            score[b["id"]] = score.get(b["id"], 0) + b["runs"] + 0.5 * (b["runs"] - b["balls"] * rate)
        for w in i["bowling"]:
            names[w["id"]] = w["name"]
            team_of[w["id"]] = i["bowling_team"]
            score[w["id"]] = score.get(w["id"], 0) + wkt_val * w["wickets"] + 0.5 * (w["balls"] * rate - w["runs"])
        for b in i["batting"]:
            h = b.get("how_out") or {}
            fid = h.get("fielder_id")
            if fid and h["kind"] in ("caught_fielder", "caught_keeper", "stumped", "run_out"):
                score[fid] = score.get(fid, 0) + 5
                team_of.setdefault(fid, i["bowling_team"])
                names.setdefault(fid, h["fielder"])
    win = card["result"].get("winner")
    for pid in score:
        if win and team_of.get(pid) == win:
            score[pid] += 25
    if not score:
        return {}
    impact = card.get("impact") or {}
    k = card.get("runs_per_win") or (140 if fmt == "t20" else 270)
    total = {pid: s + k * impact.get(pid, 0.0) for pid, s in score.items()}
    best = max(total, key=total.get)
    return {"id": best, "name": names[best], "team": team_of[best], "score": round(total[best], 1),
            "impact": impact.get(best)}


def turning_point(card: dict) -> dict | None:
    """The over with the biggest swing in the first-batting side's win probability."""
    best = None
    prev = None
    for inn in card["innings"]:
        for o in inn["overs_log"]:
            if o.get("win_prob") is None:
                continue
            wp1 = o["win_prob"] if inn["number"] == 1 else 1 - o["win_prob"]
            if prev is not None:
                sw = wp1 - prev
                if best is None or abs(sw) > abs(best[0]):
                    best = (sw, inn, o)
            prev = wp1
    if not best:
        return None
    sw, inn, o = best
    gainer = inn["team"] if (sw > 0) == (inn["number"] == 1) else inn["bowling_team"]
    which = "first" if inn["number"] == 1 else "second"
    runs = f"{o['runs']} run{'' if o['runs'] == 1 else 's'}"
    wk = f", {o['wkts']} wicket{'' if o['wkts'] == 1 else 's'}" if o["wkts"] else ""
    return {"innings": inn["number"], "over": o["over"], "score": f"{o['total']}/{o['wickets']}",
            "swing": round(abs(sw), 3), "bowler": o["bowler"], "runs": o["runs"], "wickets": o["wkts"],
            "towards": gainer, "which": which,
            "text": f"Turning point: over {o['over']} of the {which} innings ({o['bowler']}: {runs}{wk}) swung the "
                    f"match {abs(sw) * 100:.0f}% towards {gainer}"}


def simulate_match(team_a: dict, team_b: dict, fmt: str = "t20", comp: str | None = None, year: int = 2025,
                   venue: str | None = None, seed: int | None = None, **kw) -> dict:
    return Match(fmt, team_a, team_b, comp, year, venue, seed, **kw).play()
