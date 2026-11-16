"""Test match controller (docs/test_match_plan.md sections 1, 3, 4, 5).

    from engine import simulate_match
    card = simulate_match({"name": "India", "players": [...ids]}, {"name": "Australia", "players": [...]},
                          fmt="test", year=2024, seed=1)

A Test is `days` days of `day_overs` overs in three sessions; time is counted in overs because Cricsheet has no
clock. Two innings a side, the follow-on, declarations, the new ball at 80 overs, bowling by spells from two
ends. The scorecard of an innings is engine/scorebook.py, the ball is engine/ballmodel.py, the ratings are
engine/data.py: all shared with limited overs. Nothing here reads an over limit or a bowler's quota.

Returns a JSON-able scorecard dict in the limited-overs shape with up to four innings and a `days` list.
No printing, no files, no global state; `seed` makes a match reproducible.
"""
from __future__ import annotations

import math
import random
import zlib

from . import conditions, test_captain, test_conditions, test_control, test_selection, test_wdl
from .ballmodel import NO_SITUATION, BallModel
from .captain import choose_keeper
from .data import FORMATS, Player, baseline, basics, player
from .match import Team
from .scorebook import BatInns, Scorebook
from .test_situation import TestSituation, tail_role, tail_table

FMT = "test"
PHASE = "all"
CHANGE_OVERS = 2             # overs lost at a change of innings (the playing conditions; not a fitted number)
BREAKS = ("Lunch", "Tea", "Stumps")
ORDINAL = ("1st", "2nd")


def make_team(spec: dict, base: dict | None = None, rng: random.Random | None = None,
              host: str | None = None) -> Team:
    """spec as for limited overs: {"name", "players": [id | Player | {"id", "name"}], "keeper"?, "captain"?,
    "order"? (explicit batting order), "squad"? (the XI is picked from it), "years"?, "years_mode"?}.
    base, rng, host: for the learned pick from a squad (engine/test_selection.py: the era's baseline, the
    stream that redraws the ratings from their uncertainty, the host country); without a base, or with no
    fitted model, the XI is picked by the rule of test_captain.select_xi."""
    yrs, ym = spec.get("years"), spec.get("years_mode") or "blend"

    def mk(x):
        if isinstance(x, Player):
            return x
        if isinstance(x, dict):
            return player(FMT, x["id"], x.get("name"), spec.get("team_level_as") or None, years=yrs, years_mode=ym)
        return player(FMT, x, years=yrs, years_mode=ym)
    squad = [mk(x) for x in spec.get("squad") or []]
    if squad:
        ps = (test_selection.choose(squad, base, rng, host) if base else None) or test_captain.select_xi(squad)
    else:
        ps = [mk(x) for x in spec.get("players", [])]
    if len(ps) < 2:
        raise ValueError(f"{spec.get('name')}: a side needs at least two players")
    by_id = {p.id: p for p in ps}
    order = test_captain.batting_order(ps)
    if spec.get("order"):
        given = [by_id[i] for i in spec["order"] if i in by_id]
        order = given + [p for p in order if p not in given]
    keeper = by_id.get(spec.get("keeper")) or choose_keeper(ps)
    capt = by_id.get(spec.get("captain")) or max(ps, key=lambda p: p.bat_balls + p.bowl_balls)
    return Team(spec["name"], ps, keeper, capt, order, fixed_order=bool(spec.get("order")),
                bench=[p for p in squad if p not in ps], squad=ps + [p for p in squad if p not in ps])


def draw_pitch(rng: random.Random, comp: str) -> dict:
    """The day's pitch, as in limited overs, less half its variance on the log scale: the draw then leaves the
    average run and wicket rates unchanged (a five-day match feels a 1.6% rise in the wicket rate; calibration
    showed it as innings 2% too short)."""
    p = conditions.draw_pitch(FMT, rng, comp)
    t = conditions.venue_table(FMT)
    sd = (t.get("pitch_by_comp") or {}).get(comp) or t.get("pitch") or {}
    if comp in conditions.PITCH_COMPS:
        p["runs"] *= math.exp(-0.5 * sd.get("sd_runs", 0.0) ** 2)
        p["wkt"] *= math.exp(-0.5 * sd.get("sd_wkt", 0.0) ** 2)
    return p


class Clock:
    """The match's time, in overs. `used` counts today's overs gone, bowled or lost."""

    def __init__(self, days: int, day_overs: int):
        self.days, self.day_overs = days, day_overs
        self.session_overs = day_overs / 3
        self.day, self.used = 1, 0

    @property
    def left(self) -> int:
        """Overs left in the match."""
        return 0 if self.day > self.days else (self.days - self.day) * self.day_overs + self.day_overs - self.used

    @property
    def left_today(self) -> int:
        return self.day_overs - self.used

    @property
    def session(self) -> int:
        return min(int(self.used // self.session_overs), 2) + 1

    def spend(self, n: int = 1) -> list[tuple]:
        """n overs of today go by. Returns the intervals reached, [(0 lunch | 1 tea | 2 stumps, day)]."""
        before, day = self.used, self.day
        self.used = min(self.used + n, self.day_overs)
        out = [(k, day) for k in (0, 1) if before < (k + 1) * self.session_overs <= self.used < self.day_overs]
        if self.used >= self.day_overs:
            out.append((2, day))
            self.day, self.used = day + 1, 0
        return out


class TestInnings(Scorebook):
    """One Test innings: no over limit; it ends all out, declared, with the target reached, or when time is up."""
    __test__ = False             # not a test class (the name starts with Test)

    def __init__(self, m: "TestMatch", bat: Team, bowl: Team, number: int, target: int | None = None,
                 follow_on: bool = False):
        fit = [p for p in bat.order if p not in m.absent]
        super().__init__(bat, bowl, number, m.rng, fit if len(fit) < len(bat.order) else None)
        self.m = m
        self.retired: list = []                        # (place in the order, card) of batters retired hurt
        self.absent_hurt = [p.name for p in bat.order if p in m.absent]
        self.target, self.follow_on = target, follow_on
        self.lead0 = m.total(bat) - m.total(bowl)      # the batting side's lead before this innings
        self.declared = False
        self.ended: str | None = None                  # "all out" | "declared" | "target" | "time"
        self.ball_start = 0                            # the over at which the ball in use was new
        self.bowl_types = {p.name: p.bowl_type for p in bowl.players}
        self.bowling = test_captain.Bowling(bowl.players, bowl.keeper, m.crng, m.loose.get(bowl.name))
        for p in bowl.players:
            if p in m.absent:
                self.bowling.swap(p, None)
        self.mode: str | None = None                   # last innings: "chase" | "steady" | "save"
        self.nightwatchmen: list[str] = []
        self.ball_log: list[dict] = []                 # deliveries, for a person's field replay (engine/test_control.py)
        nth = sum(1 for i in m.innings if i.bat is bat)
        self.label = f"{bat.name} {ORDINAL[min(nth, 1)]} innings" + (" (following on)" if follow_on else "")

    # ------------------------------------------------------------------ helpers
    def lead(self) -> int:
        return self.lead0 + self.runs

    def event(self, text: str, kind: str = "info", **data):
        c = self.m.clock
        data.setdefault("day", c.day)
        data.setdefault("session", c.session)
        super().event(text, kind, **data)

    def not_out(self) -> str:
        left = [c for c in (self.striker, self.non_striker) if c.batted and not c.out]
        return ", ".join(f"{c.p.name} {c.runs}* ({c.balls}b)" for c in left)

    def x(self) -> int:
        """The state the win / draw / loss table reads: the batting side's lead, or in the last innings minus
        the runs still needed."""
        return self.runs - self.target if self.target is not None else self.lead0 + self.runs

    def margin_text(self) -> str:
        """'lead by 120' / 'trail by 45' / 'need 88 more' for break and close-of-play lines."""
        if self.target is not None:
            return f"need {max(self.target - self.runs, 0)} more"
        d = self.lead()
        if self.number == 1:
            return ""
        return "scores level" if d == 0 else f"lead by {d}" if d > 0 else f"trail by {-d}"

    # ------------------------------------------------------------------ play
    def play(self) -> None:
        m, clock = self.m, self.m.clock
        while not self.done:
            m.lose_time(self)
            if clock.left <= 0 or m.agreed_draw(self):
                self.ended = "time"
                break
            if m.desk and m.desk.over_start(self, CHANGE_OVERS):      # a person declares before the over
                self.declare_event()
                self.declared, self.ended, self.done = True, "declared", True
                break
            self.play_over()
            if not self.done:
                if self.legal % 6 == 0:
                    self.striker, self.non_striker = self.non_striker, self.striker
                if self.number < 4 and m.declare_on and self.declaration():
                    self.declared, self.ended, self.done = True, "declared", True
            m.over_done(self, clock.spend(1))
        self.done = True
        for i, c in reversed(self.retired):            # the retired hurt go back to their places on the card
            self.cards.insert(i, c)
        for i, c in enumerate(self.cards):
            c.pos = i + 1
        how = {"declared": "declared at ", "time": "", "target": "", "all out": "all out for "}[self.ended]
        score = str(self.runs) if self.ended == "all out" else self.score_str()
        self.event(f"End of innings: {self.bat.name} {how}{score} ({self.over_str()} ov)"
                   + (f" - {self.not_out()}" if self.not_out() else ""), "end_of_innings")

    def take_new_ball(self, n: int) -> bool:
        """The new ball is available before over n: is it taken? A person is asked; the computer captain does as
        real captains do, who often wait while spin is on."""
        spin = sum(1 for o in self.overs[-2:] if self.bowl_types.get(o["bowler"]) == "spin")
        call = test_captain.take_new_ball(self.m.crng, spin, n - self.ball_start - test_captain.NEW_BALL_OVERS)
        return self.m.desk.new_ball(self, n, call) if self.m.desk else call

    def play_over(self) -> None:
        m = self.m
        n = len(self.overs)
        day, session = m.clock.day, m.clock.session
        due = False
        desk = m.desk
        if n - self.ball_start >= test_captain.NEW_BALL_OVERS and self.take_new_ball(n):
            self.ball_start = n
            self.event("New ball taken", "new_ball")
        if n >= test_captain.NEW_BALL_OVERS and n - self.ball_start < 2:
            due = True
        age = n - self.ball_start
        sit = m.sit
        bowler = self.bowling.pick(n, age, m.overs_bowled, due, sit.t)
        if desk:
            bowler = desk.bowler(self, n, bowler, due)
        f = self.fig(bowler)
        base = m.base_of(bowler, self.bat)[PHASE]
        btype = bowler.bowl_type or "unknown"
        left = m.clock.left
        if self.target is not None:
            mode = sit.mode(self.wkts, self.target - self.runs, left)
            if mode == "save" and self.mode != "save":
                self.event(f"{self.bat.name} are batting for the draw: {self.target - self.runs} needed "
                           f"with {left} overs left", "mode")
            self.mode = mode
        runs0, wkts0, conceded0, fw0, er0, ew0 = self.runs, self.wkts, f.runs, f.wkts, f.exp_runs, f.exp_wkts
        balls = 0
        seq: list = []
        wdl = m.wdl
        # the batting side's chances now (time lost before this over is nobody's doing)
        v = wdl.value(self.number, self.wkts, self.x(), left) if wdl else 0.0
        while balls < 6 and not self.done:
            striker = self.striker
            if m.use_situation:
                if self.target is None:
                    cell = sit.cell(self.number, self.wkts, self.lead0 + self.runs)
                else:
                    cell = sit.cell(4, self.wkts, 0, self.target - self.runs, left)
                mult = sit.multipliers(cell, self.striker.balls, btype, m.overs_bowled, age)
                if m.use_matchups:
                    mult = sit.with_matchup(mult, striker.p.bat_hand, bowler.id)
                if m.use_tail and self.wkts >= m.tail_wkts and (not desk or desk.farms(self)):
                    mult = sit.with_tail(mult, tail_role(striker.pos, self.non_striker.pos, self.wkts),
                                         self.wkts, balls)
            else:
                mult = NO_SITUATION
            if desk:                                  # a person's bars (5 and 5: nothing changes)
                mult = sit.with_bars(mult, *desk.bars_for(self, bowler))
            o = m.model.delivery(m.rng, base, self.striker.p, bowler, PHASE, btype, mult, False)
            if desk:
                desk.ball(self, bowler, o, seq)
            if o.legal:
                balls += 1
                self.legal += 1
                ib, iw = self.striker.p.bat[PHASE], bowler.bowl[PHASE]
                f.exp_runs += base["runs"] * ib["runs"] * iw["runs"] + base["wide"] + base["noball"]
                f.exp_wkts += base["wkt"] * ib["wkt"] * iw["wkt"]
            self.apply(o, bowler, f, seq)
            if desk:
                desk.flush()
            if self.target is not None and self.runs >= self.target:
                self.done, self.ended = True, "target"
            elif self.done:                           # next_batter found nobody left
                self.ended = "all out"
            elif o.legal and m.inj:
                m.to_retire -= 1
                if m.to_retire <= 0 and not o.wicket and striker in (self.striker, self.non_striker):
                    m.to_retire = m.gap(m.inj["retire"]["per_ball"])
                    self.retire_hurt(striker)
            if wdl:
                # each ball moves the chances; the move goes to the striker and against the bowler. The ball
                # that ends the innings is worth what it leads to: settled when that is known (TestMatch.settle)
                if self.done:
                    m.pending = (striker.p.id, bowler.id, v)
                else:
                    v2 = wdl.value(self.number, self.wkts, self.x(), left - balls / 6)
                    m.credit(striker.p.id, bowler.id, v2 - v)
                    v = v2
        if balls == 6 and f.runs == conceded0:
            f.maidens += 1
        self.bowling.record(bowler, n, (f.runs - conceded0) - (f.exp_runs - er0),
                            (f.wkts - fw0) - (f.exp_wkts - ew0))
        over = {"over": n + 1, "bowler": bowler.name, "runs": self.runs - runs0, "wkts": self.wkts - wkts0,
                "total": self.runs, "wickets": self.wkts, "balls": seq, "day": day, "session": session,
                "left": left - 1}
        if self.mode:
            over["mode"] = self.mode
        if wdl and not self.done:
            over["wdl"] = m.chances(self, left - 1)
        self.overs.append(over)

    def retire_hurt(self, c: BatInns) -> None:
        """This batter is hurt and goes off; he does not bat again in the innings (the retirements Cricsheet
        records are those). The next man comes in, or the innings is over."""
        m = self.m
        c.how = {"kind": "retired_hurt", "bowler": None, "bowler_id": None, "fielder": None, "fielder_id": None,
                 "text": "retired hurt"}
        self.event(f"{c.p.name} retires hurt on {c.runs} ({c.balls}b)", "retired_hurt", player_id=c.p.id)
        self.close_partnership()
        i = self.cards.index(c)
        self.retired.append((i, self.cards.pop(i)))
        self.next_in -= 1
        m.hurt(self, self.bat, c.p, m.irng.random() < m.inj["retire"]["plays_on"])
        if self.next_in >= len(self.cards):
            self.new_partnership()
            self.done, self.ended = True, "all out"
            return
        new = self.bring_in(self.next_in, c)
        self.event(f"{new.p.name} comes in", "new_batter", player_id=new.p.id)

    def declaration(self) -> bool:
        nineties = any(c.runs % 100 >= 90 for c in (self.striker, self.non_striker))
        m = self.m
        p = test_captain.declare_prob(self.number, self.runs, self.lead(), self.wkts, m.clock.left - 1, nineties)
        call = p > 0 and m.crng.random() < p
        loose = m.loose.get(self.bat.name)
        if loose and p > 0:                           # a weaker captain: his own reading, his own stream
            call = loose.rng.random() < loose.prob(self.number, p)
        if m.desk and m.desk.has(self.bat):           # a person's side: their call
            call = m.desk.declare(self, call, m.clock.left - 1, CHANGE_OVERS)
        if call:
            self.declare_event()
        return call

    def declare_event(self) -> None:
        self.event(f"{self.bat.captain.name} declares at {self.score_str()}"
                   + (f", {self.margin_text()}" if self.margin_text() else ""), "declaration")

    def next_batter(self, out: BatInns) -> BatInns | None:
        if self.wkts >= 10 or self.next_in >= len(self.cards):
            self.done = True
        if self.done or (self.target is not None and self.runs >= self.target):
            self.new_partnership()
            return None
        m = self.m
        mine = bool(m.desk and m.desk.has(self.bat))  # a person captains the batting side
        nw = None
        if m.nightwatchman and (mine or not self.bat.fixed_order) and m.clock.day < m.clock.days:
            # the over in progress is not yet off the clock: it does not count as time left today
            nw = test_captain.nightwatchman(self.cards, self.next_in, m.clock.left_today - 1)
        k = nw if nw is not None else self.next_in
        if mine:
            k = m.desk.batter(self, self.next_in, nw, m.clock.left_today - 1)
        new = self.bring_in(k, out)
        if nw is not None and k == nw:
            self.nightwatchmen.append(new.p.name)
            self.event(f"{new.p.name} comes in as nightwatchman", "nightwatchman", player_id=new.p.id)
        return new

    # ------------------------------------------------------------------ output
    def state_dict(self) -> dict:
        return {"label": self.label, "target": self.target, "declared": self.declared,
                "follow_on": self.follow_on, "lead": self.lead(), "ended": self.ended,
                "nightwatchmen": list(self.nightwatchmen),
                **({"absent_hurt": self.absent_hurt} if self.absent_hurt else {})}


class TestMatch:
    __test__ = False             # not a test class (the name starts with Test)

    def __init__(self, team_a: dict, team_b: dict, comp: str | None = None, year: int = 2025,
                 venue: str | None = None, seed: int | None = None, toss: str | None = None,
                 decision: str | None = None, days: int | None = None, day_overs: int | None = None,
                 pitch: dict | None = None, use_situation: bool = True, use_venue: bool = True,
                 use_pitch: bool = True, use_spin: bool = True, declare: bool = True,
                 follow_on: bool | None = None, nightwatchman: bool = True, host: str | None = None,
                 use_weather: bool = True, use_home: bool = True, use_wdl: bool = True,
                 control: dict | None = None, skill: dict | None = None, era: dict | bool = True,
                 use_matchups: bool = True, use_tail: bool = True, day_night: bool = False, timeless: bool = False,
                 last_hour: bool = True, injuries: bool = True):
        """toss: "a" | "b" (who wins it); decision: "bat" | "bowl"; days, day_overs: the match's length
        (default 5 x 90); declare: False = nobody declares; follow_on: True / False = always / never enforced when
        it is on offer, None = the captain's (fitted) choice; nightwatchman: False = never used; host: the
        country whose ground it is (default: looked up from the venue; None with no venue = neutral): it sets
        the overs lost to weather and, when one of the sides is the host, the home edge. use_wdl: False = no
        win / draw / loss chances on the card (they never change how the match is played). control: team name
        -> engine.control.Controller for a side a person captains (engine/test_control.py). skill: team name ->
        "expert" | "average" | "easy" for computer captains (engine/test_captain.py Loose; default expert).
        era: the factors on an early year's baseline and its overs in a day when day_overs is not given
        (test_conditions.era_factors); False = none; a dict = these. day_night: a pink-ball Test (wickets fall
        faster: test_conditions.day_night). timeless: played to a finish, with no declarations (`days` is
        ignored; left drawn after test_conditions.TIMELESS_DAYS days). last_hour: False = the last hour is
        always played out (otherwise the captains agree a draw in it when no result is possible). injuries:
        False = nobody is hurt (otherwise at the fitted rates, from their own random stream: test_conditions
        .injuries; a side with a bench may bring in a like-for-like replacement, from 2019)."""
        self.year, self.venue = year, venue
        self.comp = comp or FORMATS[FMT]["intl"]
        self.seed = seed if seed is not None else random.randrange(1 << 30)
        self.rng = random.Random(self.seed)
        # captains' calls (declarations, the follow-on, bowling changes): their own stream
        self.crng = random.Random(zlib.crc32(f"test-captain|{self.seed}".encode()))
        ef = era if isinstance(era, dict) else test_conditions.era_factors(year) if era else None
        self.timeless, self.day_night, self.last_hour = bool(timeless), bool(day_night), last_hour
        self.last_hour_called = False
        self.days = test_conditions.TIMELESS_DAYS if timeless else days or FORMATS[FMT]["days"]
        self.clock = Clock(self.days, day_overs or (ef or {}).get("day_overs") or FORMATS[FMT]["day_overs"])
        self.base = baseline(FMT, self.comp, year)
        if ef and (ef["runs"] != 1.0 or ef["wkt"] != 1.0):
            self.base = conditions.apply(self.base, ef["runs"], ef["wkt"])
        # conditions, as in limited overs: venue factor x the day's pitch, then spin's edge over pace. The Test
        # tables for these are fitted in Phase 3; until then every factor is 1.
        self.venue_info = conditions.venue_factor(FMT, venue) if use_venue else {"runs": 1.0, "wkt": 1.0,
                                                                                  "known": False, "name": venue}
        self.pitch = pitch or (draw_pitch(self.rng, self.comp) if use_pitch else {"runs": 1.0, "wkt": 1.0})
        cr = self.venue_info["runs"] * self.pitch["runs"]
        cw = self.venue_info["wkt"] * self.pitch["wkt"]
        self.base = conditions.apply(self.base, cr, cw)
        self.spin = conditions.spin_edge(FMT, venue, self.seed) if use_spin else {"runs": 0.0, "wkt": 0.0}
        self.base_type = conditions.by_type(self.base, self.spin, FMT)
        dn = test_conditions.day_night() if day_night else None
        if dn:                                 # the pink ball: by bowling kind; an unknown kind is read as pace
            self.base_type = {k: conditions.apply(b, dn[k]["runs"], dn[k]["wkt"]) if k in dn else b
                              for k, b in self.base_type.items()}
            self.base = conditions.apply(self.base, dn["pace"]["runs"], dn["pace"]["wkt"])
        self.host = host or test_conditions.host_of(venue)
        self.weather = (test_conditions.draw_weather(self.host, self.seed, self.days, self.clock.day_overs)
                        if use_weather else {})
        self.use_home = use_home
        self.conditions = {"venue": venue, "venue_known": self.venue_info["known"],
                           "venue_runs": round(self.venue_info["runs"], 3), "venue_wkt": round(self.venue_info["wkt"], 3),
                           "pitch_runs": round(self.pitch["runs"], 3), "pitch_wkt": round(self.pitch["wkt"], 3),
                           "report": conditions.pitch_report(cr, cw)
                           + (f"; {sr}" if (sr := conditions.spin_report(self.spin)) else ""),
                           "spin_edge": {k: round(v, 3) for k, v in self.spin.items()},
                           "host": self.host}
        if self.day_night:
            self.conditions["day_night"] = True
            self.conditions["report"] += "; day-night, pink ball"
        self.model = BallModel(basics(FMT))
        self.sit = TestSituation()
        self.use_situation = use_situation
        self.use_matchups = use_matchups
        self.use_tail = use_tail and tail_table() is not None      # batting with the tail, as real sides do
        self.tail_wkts = tail_table()["wickets"][0] if self.use_tail else 99
        self.declare_on, self.follow_on_spec, self.nightwatchman = declare and not timeless, follow_on, nightwatchman
        # each side's XI from its squad: its own stream, so the balls of the match are drawn as before
        self.teams = [make_team(sp, self.base, random.Random(zlib.crc32(f"test-xi|{self.seed}|{k}".encode())),
                                self.host) for k, sp in enumerate((team_a, team_b))]
        # the home edge: the host's batters do better than their ratings, the visitors' worse
        # (a side is the host's by its name, or by the "nation" of its spec: "India 2021-24" is India)
        nations = [sp.get("nation") or sp["name"] for sp in (team_a, team_b)]
        self.home = next((t for t, n in zip(self.teams, nations) if use_home and self.host and n == self.host), None)
        self.base_side = {}
        if self.home:
            h = test_conditions.home_factors()
            for t in self.teams:
                fr, fw = (h["runs"], h["wkt"]) if t is self.home else (1 / h["runs"], 1 / h["wkt"])
                self.base_side[t.name] = (conditions.apply(self.base, fr, fw),
                                          {k: conditions.apply(b, fr, fw) for k, b in self.base_type.items()})
        self.conditions["home"] = self.home.name if self.home else None
        self.toss_spec, self.decision_spec = toss, decision
        self.innings: list[TestInnings] = []
        self.overs_bowled = 0                  # in the match (pitch wear)
        self.day_log: list[dict] = []
        self._today = {"overs": 0, "runs": 0, "wickets": 0, "lost": 0}
        self.wdl = test_wdl.table() if use_wdl else None     # None also when the table has not been built
        self.wpa: dict[str, float] = {}        # each player's impact: chances added (win + half a draw)
        self.pending: tuple | None = None      # the ball that ended the last innings, until it is settled
        self.key = f"{self.seed}|{self.teams[0].name}|{self.teams[1].name}"
        self.desk = (test_control.Desk(self, control)
                     if control and any(t.name in control for t in self.teams) else None)
        self.loose = {t.name: lc for t in self.teams if t.name not in (control or {})
                      and (lc := test_captain.loose_captain(skill, t.name, self.seed))}
        # injuries: their own stream, drawn as "balls until the next one", so the balls of a match in which
        # nobody is hurt are the same with injuries on or off
        self.inj = test_conditions.injuries() if injuries else {}
        self.irng = random.Random(zlib.crc32(f"test-injury|{self.seed}".encode()))
        self.absent: set = set()               # players who take no further part
        self.replacements: list[dict] = []
        self.to_retire = self.gap(self.inj["retire"]["per_ball"]) if self.inj else math.inf
        self.to_field = self.gap(self.inj["field"]["per_ball"]) if self.inj else math.inf

    # ------------------------------------------------------------------ helpers
    def credit(self, striker_id: str, bowler_id: str, d: float) -> None:
        self.wpa[striker_id] = self.wpa.get(striker_id, 0.0) + d
        self.wpa[bowler_id] = self.wpa.get(bowler_id, 0.0) - d

    def chances(self, inn: TestInnings, left: float) -> list:
        """[the side that batted first wins, a draw] in the innings' present state, for the chart."""
        pw, pd = self.wdl.probs(inn.number, inn.wkts, inn.x(), left)
        if inn.bat is not self.innings[0].bat:
            pw = max(1.0 - pw - pd, 0.0)
        return [round(pw, 3), round(pd, 3)]

    def settle(self, inn: TestInnings, v: float, chances: list, force: bool = False) -> None:
        """An innings is over. v: its batting side's chances as things now stand (the next innings' first
        state, or the result). The ball that ended it gets the difference; its last over gets the chart point."""
        if self.pending:
            sid, bid, v0 = self.pending
            self.credit(sid, bid, v - v0)
            self.pending = None
        if inn.overs and (force or "wdl" not in inn.overs[-1]):
            inn.overs[-1]["wdl"] = chances

    def base_of(self, p: Player, bat: Team) -> dict:
        """The baseline for this bowler's type against this batting side."""
        base, by_type = self.base_side.get(bat.name) or (self.base, self.base_type)
        return by_type.get(p.bowl_type or "", base)

    def lose_time(self, inn: TestInnings) -> None:
        """Today's lost overs (weather, light, over rate) go off the clock when their time comes."""
        clock = self.clock
        while clock.left > 0:
            w = self.weather.get(clock.day)
            if not w or w.get("done") or clock.used < w["start"]:
                return
            w["done"] = True
            day, n = clock.day, min(w["overs"], clock.left_today)
            if n <= 0:
                return
            self._today["lost"] += n
            inn.event(f"Day {day}: {w['why']}, {n} over{'' if n == 1 else 's'} lost", "weather", overs=n, day=day)
            self.intervals(inn, clock.spend(n))

    def gap(self, rate: float) -> float:
        """Balls until the next event of this rate a ball."""
        return math.inf if rate <= 0 else int(math.log(1.0 - self.irng.random()) / math.log(1.0 - rate)) + 1

    def hurt(self, inn: TestInnings, team: Team, p: Player, plays_on: bool = False) -> None:
        """p is hurt. Unless he plays on later in the match he takes no further part: a like-for-like man from
        the bench comes in for him (from 2019, at the fitted share of such cases), or his side is a man short."""
        u = self.irng.random()                 # drawn every time, so the next injury does not depend on this one
        if plays_on:
            return
        like = [b for b in team.bench if test_captain.group(b) == test_captain.group(p)
                and (p is not team.keeper or b.keeper)]
        if like and self.year >= self.inj["subs_from"] and u < self.inj["replaced"]:
            new = max(like, key=lambda b: test_captain.batting_value(b) + test_captain.bowling_value(b))
            team.bench.remove(new)
            team.players[team.players.index(p)] = new
            team.order[team.order.index(p)] = new
            if team.keeper is p:
                team.keeper = new
            self.replacements.append({"team": team.name, "out": p.name, "out_id": p.id, "in": new.name,
                                      "in_id": new.id, "innings": inn.number, "day": self.clock.day})
            inn.event(f"{new.name} comes into the {team.name} side for {p.name}, who is hurt", "replacement",
                      player_id=new.id)
            if team is inn.bat:
                inn.cards.append(BatInns(new, len(inn.cards) + 1))
            else:
                inn.bowling.swap(p, new)
                inn.bowl_types[new.name] = new.bowl_type
            return
        self.absent.add(p)
        inn.event(f"{p.name} ({team.name}) is hurt and will take no further part in the match", "injury",
                  player_id=p.id)
        if team.keeper is p:                   # someone else takes the gloves
            team.keeper = choose_keeper([q for q in team.players if q not in self.absent])
        if team is inn.bowl:
            inn.bowling.swap(p, None)

    def agreed_draw(self, inn: TestInnings) -> bool:
        """The last hour of the last day (15 overs). The captains shake hands at once when no result is
        possible: a first innings is still going, or the side batting third leads by more than the other could
        score in the overs left (test_captain.RR_CAP an over) and has not declared. The same when a person
        captains a side (a match they play as the computer would is the same match). Not in a timeless Test."""
        clock = self.clock
        if (not self.last_hour or self.timeless or clock.day != self.days
                or clock.left > test_conditions.LAST_HOUR_OVERS):
            return False
        if not self.last_hour_called:
            self.last_hour_called = True
            inn.event(f"The last hour: {clock.left} overs left", "last_hour", overs=clock.left)
        if inn.number > 3:
            return False
        if inn.number == 3 and inn.lead() <= test_captain.RR_CAP * clock.left:
            return False
        inn.event("The captains shake hands on a draw: no result is possible", "agreed_draw", overs=clock.left)
        return True

    def total(self, team: Team) -> int:
        return sum(i.runs for i in self.innings if i.bat is team)

    def over_done(self, inn: TestInnings, breaks: list) -> None:
        o = inn.overs[-1]
        self.overs_bowled += 1
        t = self._today
        t["overs"] += 1
        t["runs"] += o["runs"]
        t["wickets"] += o["wkts"]
        if self.inj and not inn.done:
            self.to_field -= 6
            if self.to_field <= 0:             # a fielder (not the keeper) is hurt and goes off for good
                self.to_field = self.gap(self.inj["field"]["per_ball"])
                pool = [p for p in inn.bowling.cands if p is not inn.bowl.keeper and p not in self.absent]
                if len(pool) > 2:
                    self.hurt(inn, inn.bowl, self.irng.choice(pool))
        self.intervals(inn, breaks)

    def intervals(self, inn: TestInnings, breaks: list) -> None:
        """Lunch, tea and stumps reached (after an over, or in the time lost at a change of innings)."""
        for k, day in breaks:
            line = f"{inn.bat.name} {inn.score_str()}"
            extra = ", ".join(x for x in (inn.margin_text(), inn.not_out() if not inn.done else "") if x)
            inn.event(f"{BREAKS[k]}, day {day}: {line}" + (f" ({extra})" if extra else ""), "break",
                      day=day, session=k + 1, interval=BREAKS[k].lower())
            if k == 2:
                self.close_day(inn, day)
                inn.bowling.new_day()

    def close_day(self, inn: TestInnings, day: int) -> None:
        if any(d["day"] == day for d in self.day_log):
            return
        extra = "" if inn.ended == "target" else inn.margin_text()
        self.day_log.append({"day": day, **self._today, "innings": inn.number,
                             "close": f"{inn.bat.name} {inn.score_str()}" + (f", {extra}" if extra else ""),
                             })
        self._today = {"overs": 0, "runs": 0, "wickets": 0, "lost": 0}

    def start(self, bat: Team, bowl: Team, target: int | None = None, follow_on: bool = False) -> TestInnings | None:
        """Play the next innings; None when there is no time left to start it."""
        if self.innings:
            self.intervals(self.innings[-1], self.clock.spend(CHANGE_OVERS))
            self.lose_time(self.innings[-1])       # rain that has come by now: no innings starts only to stop
        if self.clock.left <= 0:
            return None
        inn = TestInnings(self, bat, bowl, len(self.innings) + 1, target, follow_on)
        self.innings.append(inn)
        if self.wdl and len(self.innings) > 1:
            prev = self.innings[-2]
            v = self.wdl.value(inn.number, 0, inn.x(), self.clock.left)
            self.settle(prev, v if prev.bat is bat else 1.0 - v, self.chances(inn, self.clock.left))
        inn.play()
        inn.close_partnership()
        return inn

    # ------------------------------------------------------------------ the match
    def play(self) -> dict:
        a, b = self.teams
        toss_winner = {"a": a, "b": b}.get(self.toss_spec) or (a if self.rng.random() < 0.5 else b)
        decision = self.decision_spec or test_captain.toss_decision(self.rng)
        desk = self.desk
        if desk:
            decision = desk.toss(toss_winner, decision)
        first = toss_winner if decision == "bat" else (b if toss_winner is a else a)
        second = b if first is a else a
        if desk:
            desk.xis(first, second, f"{toss_winner.name} won the toss and chose to {decision}.")
        result = self.play_innings(first, second)
        if self.innings and not any(d["day"] == self.clock.day for d in self.day_log) and self._today["overs"]:
            self.close_day(self.innings[-1], self.clock.day)          # the match ended during a day
        if self.wdl and self.innings:
            last, win = self.innings[-1], result.get("winner")
            self.settle(last, 0.5 if not win else float(win == last.bat.name),
                        [float(win == self.innings[0].bat.name), float(not win)], force=True)
        card = {
            "format": FMT, "competition": self.comp, "year": self.year, "venue": self.venue, "seed": self.seed,
            "overs": None, "scheduled_days": self.days, "day_overs": self.clock.day_overs,
            **({"timeless": True} if self.timeless else {}), **({"day_night": True} if self.day_night else {}),
            "teams": [a.name, b.name],
            "xi": {t.name: [{"id": p.id, "name": p.name, "rated": p.rated_bat or p.rated_bowl} for p in t.order]
                   for t in self.teams},
            **({"replacements": self.replacements} if self.replacements else {}),
            "toss": {"winner": toss_winner.name, "decision": decision}, "conditions": self.conditions,
            "innings": [i.to_dict() for i in self.innings],
            "days": self.day_log,
            "result": result,
            "events": [e for i in self.innings for e in i.events],
        }
        if self.wdl:
            card["impact"] = {pid: round(v, 3) for pid, v in sorted(self.wpa.items(), key=lambda kv: -kv[1])}
            card["runs_per_win"] = self.wdl.runs_per_win
            tp = test_wdl.turning_point(card)
            if tp:
                card["turning_point"] = tp
                card["events"].append({"innings": tp["innings"], "over": f"{tp['over']}.0", "score": tp["to"],
                                       "kind": "turning_point", "text": tp["text"], "day": tp["day"],
                                       "session": tp["session"]})
        card["player_of_match"] = player_of_match(card, self.base[PHASE])
        if desk:
            card["captaincy"] = desk.log
            desk.result(card)
        return card

    def play_innings(self, first: Team, second: Team) -> dict:
        draw = {"type": "draw", "winner": None, "text": "Match drawn"}
        i1 = self.start(first, second)
        if i1 is None or i1.ended == "time":
            return draw
        i2 = self.start(second, first)
        if i2 is None or i2.ended == "time":
            return draw
        lead = i1.runs - i2.runs
        enforce = False
        if lead >= test_captain.follow_on_lead(self.days):
            if self.follow_on_spec is None:
                p = test_captain.follow_on_prob(lead, self.clock.left, len(i2.overs), self.days)
                enforce = self.crng.random() < p
                loose = self.loose.get(first.name)
                if loose:
                    enforce = loose.rng.random() < loose.prob(0, p)
                if self.desk:
                    enforce = self.desk.follow_on(first, lead, enforce, p, i2, CHANGE_OVERS)
            else:
                enforce = bool(self.follow_on_spec)
            i2.event(f"{first.captain.name} {'enforces' if enforce else 'does not enforce'} the follow-on "
                     f"({first.name} lead by {lead})", "follow_on", enforced=enforce)
        third, fourth = (second, first) if enforce else (first, second)
        i3 = self.start(third, fourth, follow_on=enforce)
        if i3 is None or i3.ended == "time":
            return draw
        ahead = self.total(third) - self.total(fourth)       # the side that has batted twice against the other's one
        if ahead < 0:
            return self.win(fourth, third, "innings", -ahead)
        i4 = self.start(fourth, third, target=ahead + 1)
        if i4 is None:
            return draw
        if i4.ended == "target":
            return self.win(fourth, third, "wickets", len(fourth.order) - 1 - i4.wkts)
        if i4.ended == "all out":
            if i4.runs == ahead:
                return {"type": "tie", "winner": None, "text": "Match tied"}
            return self.win(third, fourth, "runs", ahead - i4.runs)
        return draw

    @staticmethod
    def win(winner: Team, loser: Team, by: str, margin: int) -> dict:
        s = "" if margin == 1 else "s"
        how = {"innings": f"an innings and {margin} run{s}", "runs": f"{margin} run{s}",
               "wickets": f"{margin} wicket{s}"}[by]
        return {"type": "win", "winner": winner.name, "loser": loser.name, "by": by, "margin": margin,
                "text": f"{winner.name} won by {how}"}


def player_of_match(card: dict, base: dict) -> dict:
    """The balanced score (plan section 5): runs, weighted by how low-scoring the match was against the era; a
    wicket worth the era's runs per wicket; 5 a catch or stumping; a bonus for the winning side. No strike-rate
    credit. Everyone's points, in their four parts (batting, bowling, fielding, winning), are kept on the card
    as card["points"]: a series adds them up (engine/test_series.py).

    With the win / draw / loss table the award adds each player's impact (win chance plus half the draw chance
    added, card["impact"]) turned into runs (card["runs_per_win"]), as the limited-overs award does."""
    inns = card["innings"]
    par = base["runs"] / max(base["wkt"] + base["other_out"], 1e-6)        # the era's runs per wicket
    wk = sum(i["wickets"] for i in inns)
    rpw = sum(i["runs"] for i in inns) / wk if wk else par
    weight = min(max(par / max(rpw, 1.0), 0.5), 2.0)
    parts, names, team_of = {}, {}, {}

    def add(pid, k, v):
        parts.setdefault(pid, [0.0, 0.0, 0.0, 0.0])[k] += v
    for i in inns:
        for b in i["batting"]:
            if b["batted"]:
                names[b["id"]], team_of[b["id"]] = b["name"], i["team"]
                add(b["id"], 0, b["runs"] * weight)
            h = b.get("how_out") or {}
            fid = h.get("fielder_id")
            if fid and h["kind"] in ("caught_fielder", "caught_keeper", "stumped", "run_out"):
                add(fid, 2, 5)
                team_of.setdefault(fid, i["bowling_team"])
                names.setdefault(fid, h["fielder"])
        for w in i["bowling"]:
            names[w["id"]], team_of[w["id"]] = w["name"], i["bowling_team"]
            add(w["id"], 1, par * w["wickets"])
    win = card["result"].get("winner")
    for pid in parts:
        if win and team_of.get(pid) == win:
            add(pid, 3, 25)
    card["points"] = {pid: [round(x, 1) for x in v] for pid, v in parts.items()}
    impact = card.get("impact") or {}
    k = card.get("runs_per_win") or 0.0
    score = {pid: sum(v) + k * impact.get(pid, 0.0) for pid, v in parts.items()}
    if not score:
        return {}
    best = max(score, key=score.get)
    return {"id": best, "name": names[best], "team": team_of[best], "score": round(score[best], 1),
            "impact": impact.get(best)}


def simulate_test(team_a: dict, team_b: dict, comp: str | None = None, year: int = 2025,
                  venue: str | None = None, seed: int | None = None, **kw) -> dict:
    return TestMatch(team_a, team_b, comp, year, venue, seed, **kw).play()
