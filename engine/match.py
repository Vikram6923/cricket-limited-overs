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

from . import captain, conditions
from .ballmodel import BallModel
from .data import FORMATS, Player, baseline, basics, phase_of, player
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
                max_overseas=spec.get("max_overseas"))


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
        self.streak: dict[Player, int] = {}   # consecutive legal balls taking wickets, per bowler (hat-tricks)

    # ------------------------------------------------------------------ helpers
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
        quota = FORMATS[fmt]["quota"] if not self.super_over else 1
        quota_left = {p: quota for p in fielders}
        last = None
        plan = None
        if not self.super_over and self.m.use_plan:
            plan = captain.BowlingPlan(fielders, self.bowl.keeper, fmt, self.m.base, self.max_overs, quota,
                                       self.m.rng)
        for over in range(self.max_overs):
            if self.done:
                break
            ph = phase_of(over, fmt) if not self.super_over else "death"
            base = self.m.base[ph]
            if self.allowed_bowlers and len(self.allowed_bowlers) == 1:
                bowler = self.allowed_bowlers[0]
            else:
                bowler = plan.bowler_for(over, last, quota_left) if plan else None
                if bowler is not None:
                    q = dict(quota_left)
                    q[bowler] -= 1
                    if not captain.feasible(q, self.max_overs - over - 1, bowler):
                        bowler = None
                if bowler is None:
                    bowler = captain.choose_bowler(fielders, self.bowl.keeper, quota_left, self.max_overs - over,
                                                   last, ph, base, fmt, self.m.rng)
            quota_left[bowler] = quota_left.get(bowler, 0) - 1
            self.bowl_over(over, bowler, ph, base)
            last = bowler
            if not self.done and self.legal % 6 == 0:
                self.striker, self.non_striker = self.non_striker, self.striker
            if (not self.done and self.number == 1 and self.m.impact_player and not self.super_over
                    and self.m.impact_mid_bowling(self, quota_left)):
                fielders = self.bowl.players   # a bowler came in: the rest of the innings is chosen over by over
                plan = None
        self.done = True
        left = [c for c in (self.striker, self.non_striker) if c.batted and not c.out]
        self.event(f"End of innings: {self.runs}/{self.wkts} ({self.over_str()} ov)" +
                   ("" if not left else " - " + ", ".join(f"{c.p.name} {c.runs}* ({c.balls}b)" for c in left)),
                   "end_of_innings")

    def bowl_over(self, over: int, bowler: Player, ph: str, base: dict):
        f = self.fig(bowler)
        start_runs, start_wkts, conceded0 = self.runs, self.wkts, f.runs
        balls_in_over = 0
        btype = bowler.bowl_type or "unknown"
        seq = []
        while balls_in_over < 6 and not self.done:
            sit = self.m.sit.multipliers(1 if self.target is None else 2, self.legal, self.wkts, self.runs,
                                         self.target, self.striker.balls) if self.m.use_situation else {}
            if self.m.use_matchups:
                sit = self.m.sit.with_matchup(sit, self.striker.p.bat_hand, bowler.bowl_kind)
            o = self.m.model.delivery(self.m.rng, base, self.striker.p, bowler, ph, btype, sit, self.free_hit)
            wp0 = self.m.wp_batting(self)
            striker = self.striker.p
            if o.legal:                       # counted first so events carry the ball they happened on
                balls_in_over += 1
                self.legal += 1
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
            if self.m.impact_player and not self.super_over:
                self.m.impact_mid_innings(self)
            j = self.pick_next()
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
            "target": self.target, "max_overs": self.max_overs, "extras": dict(self.extras),
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
                 use_matchups: bool = True, use_pitch: bool = True, impact_player: bool | None = None):
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
        self.conditions = {"venue": venue, "venue_known": self.venue_info["known"],
                           "venue_runs": round(self.venue_info["runs"], 3), "venue_wkt": round(self.venue_info["wkt"], 3),
                           "pitch_runs": round(self.pitch["runs"], 3), "pitch_wkt": round(self.pitch["wkt"], 3),
                           "report": conditions.pitch_report(cr, cw)}
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
        # IPL Impact Player rule (2023 onwards): one substitute per side, used at the innings break
        self.impact_player = impact_player if impact_player is not None else (self.comp == "ipl" and year >= 2023)
        self.toss_spec, self.decision_spec = toss, decision
        self.innings: list[Innings] = []
        self.super_overs: list[Innings] = []
        self.wpa: dict[str, float] = {}

    def wp_first(self, inn: "Innings") -> float:
        """Win probability of the side batting first, at the current state of `inn` (design T1-8)."""
        n = self.overs * 6
        if inn.number == 1:
            if inn.done or inn.wkts >= 10 or inn.legal >= n:
                return self.sit.win_prob_first(n, 9, inn.runs)
            return self.sit.win_prob_first(inn.legal, inn.wkts, inn.runs)
        need = inn.target - inn.runs
        if need <= 0:
            return 0.0
        if inn.wkts >= 10 or inn.legal >= n:
            return 0.5 if need == 1 else 1.0
        return 1.0 - self.sit.win_prob_chase(inn.legal, inn.wkts, need)

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
        quota_left[new] = FORMATS[self.fmt]["quota"]
        quota_left.pop(out, None)
        return True

    def play(self) -> dict:
        a, b = self.teams
        toss_winner = {"a": a, "b": b}.get(self.toss_spec) or (a if self.rng.random() < 0.5 else b)
        decision = self.decision_spec or captain.toss_decision(self.fmt, self.rng, self.venue)
        first = toss_winner if decision == "bat" else (b if toss_winner is a else a)
        second = b if first is a else a
        if self.impact_player:                 # XI and substitutes are named after the toss
            from .impact import choose_xi
            choose_xi(first, True, self.fmt, self.base, self._slot_balls())
            choose_xi(second, False, self.fmt, self.base, self._slot_balls())
        i1 = Innings(self, first, second, 1, None, self.overs)
        i1.play()
        i1.close_partnership()
        if self.impact_player:
            self.impact_swap(first, "bowl")    # batted first: bring in the best bowler for the defence
            self.impact_swap(second, "bat")    # has bowled: bring in the best batter for the chase
        i2 = Innings(self, second, first, 2, i1.runs + 1, self.overs)
        i2.play()
        i2.close_partnership()
        self.innings = [i1, i2]
        result = self.result(i1, i2)
        if result["type"] == "tie":
            result = self.play_super_overs(first, second, result)
        card = {
            "format": self.fmt, "competition": self.comp, "year": self.year, "venue": self.venue, "seed": self.seed,
            "overs": self.overs, "teams": [a.name, b.name],
            "xi": {t.name: [{"id": p.id, "name": p.name, "rated": p.rated_bat or p.rated_bowl} for p in t.order]
                   for t in self.teams},
            "impact_player": {t.name: t.impact for t in self.teams if t.impact},
            "toss": {"winner": toss_winner.name, "decision": decision}, "conditions": self.conditions,
            "innings": [i.to_dict() for i in self.innings],
            "super_overs": [i.to_dict() for i in self.super_overs],
            "result": result,
            "events": [e for i in self.innings + self.super_overs for e in i.events],
        }
        card["impact"] = {pid: round(v, 3) for pid, v in sorted(self.wpa.items(), key=lambda kv: -kv[1])}
        card["player_of_match"] = player_of_match(card, self.fmt)
        tp = turning_point(card)
        if tp:
            card["turning_point"] = tp
            card["events"].append({"innings": tp["innings"], "over": str(tp["over"]), "score": tp["score"],
                                   "kind": "turning_point", "text": tp["text"]})
        return card

    def result(self, i1: Innings, i2: Innings) -> dict:
        if i2.runs >= i2.target:
            w = 10 - i2.wkts
            left = self.overs * 6 - i2.legal
            return {"type": "win", "winner": i2.bat.name, "loser": i1.bat.name, "by": "wickets", "margin": w,
                    "balls_left": left,
                    "text": f"{i2.bat.name} won by {w} wicket{'s' if w != 1 else ''} ({left} ball{'s' if left != 1 else ''} left)"}
        if i2.runs < i1.runs:
            r = i1.runs - i2.runs
            return {"type": "win", "winner": i1.bat.name, "loser": i2.bat.name, "by": "runs", "margin": r,
                    "text": f"{i1.bat.name} won by {r} run{'s' if r != 1 else ''}"}
        return {"type": "tie", "winner": None, "text": "Match tied"}

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
    """Balanced impact score: runs and wickets, with credit for scoring faster / conceding slower than the match
    rate, catches, and a bonus for the winning side (ported idea from the Test sim's motmscore)."""
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
    if impact:
        # win probability added decides; the balanced score breaks near-ties
        best = max(score, key=lambda pid: impact.get(pid, 0.0) + 0.0001 * score[pid])
    else:
        best = max(score, key=score.get)
    return {"id": best, "name": names[best], "team": team_of[best], "score": round(score[best], 1),
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
