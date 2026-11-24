"""A person captains a side in a Test (docs/test_match_plan.md Phase 6, docs/test_design.md).

`Desk` sits between engine/test_match.py and the side's controller (engine/control.py). The match calls it at
each point where a captain decides; it asks the person when the decision is theirs and otherwise returns the
computer's call unchanged. With no controller a Test has no Desk and plays exactly as before; nothing here draws
from the match's random streams.

Decisions (the "kind" of a question; every question carries the computer's call as `default`, and the answer
None means "the computer's call"):
- toss, xi      as in limited overs (the XI in batting order and the keeper; no substitutes)
- follow_on     a lead big enough after the first innings each: enforce it? With the chance real captains
                enforce here and, when the win / draw / loss table exists, the chances either way.
- declare       batting in innings 1-3. Asked at each declaration point: the start of a session once real
                captains declare from such a position (DECLARE_POINT), and whenever the computer's captain would. With
                the chances after declaring and as things stand. The bars question also has a Declare button.
- new_ball      when it becomes available (and every NEW_BALL_REASK overs after a "not yet").
- bowler        who bowls the over, asked at bowling moments: an end with no bowler (the start of the innings
                or of a day), when the computer would make a change, and at key moments; in between the bowler
                at that end goes on. The bars question has a Change bowler button.
- batter        at the fall of a wicket: who goes in (the nightwatchman is marked when the rule suggests one)
- nightwatchman only when `batter` is left to the computer: send the nightwatchman the rule suggests?
- ball          the bars, before an over (not before a ball: a Test is some 2,700 balls): the two batters'
                approach when batting, the bowler's plan in the field, and how far to play before the next
                pause: "over", "key" (the next key moment), "wicket", "session", "day", "innings".
- result        a pause after the match.

Key moments: the first over of an innings and of a session, the over after a wicket, the new ball (due or just
taken), the last KEY_LAST_OVERS overs of the match and the last KEY_CLOSE_RUNS runs of a chase.

The captaincy report (card["captaincy"], engine.judge.season_report) values the person's calls against the
computer's in runs: declarations and the follow-on by the win / draw / loss table (chances x the table's runs per
win), the bowler by the expected cost of his over (runs less the runs a wicket is worth). The toss, the XI, the
new ball and batting-order calls are listed without a value.
"""
from __future__ import annotations

import bisect

from . import test_captain
from .data import Player
from .test_situation import NORMAL_BARS, tail_role, tail_table

PHASE = "all"
# Presentation pace and re-asking: none of these change how a ball is played.
KEY_LAST_OVERS = 15          # "the last hour": every over of it is a key moment
KEY_CLOSE_RUNS = 30          # a chase this close to its target: every over is a key moment
DECLARE_REASK = 5            # overs before the computer's "declare now" is put to the person again
DECLARE_POINT = 0.005        # the start of a session is a declaration point once real captains would declare
                             # here at least this often an over (about one time in seven over a session)
NEW_BALL_REASK = 10          # overs before "take the new ball?" is asked again after "not yet"
SINCE_MAX = 12               # balls replayed on the field before a question
# A person's bowlers: a spell no longer than all but SPELL_TAIL of real spells of that kind of bowler (from the
# fitted spell table), and no more than that many overs in any stretch of three times as many. The data shows no
# tiredness in the rates (docs/test_design.md), so without a limit a person would bowl two men all day; real
# captains do not, which the computer copies through the fitted spell lengths.
SPELL_TAIL = 0.02
UNTIL = ("over", "key", "wicket", "session", "day", "innings")


def spell_caps() -> dict:
    """kind of bowler ('pace' | 'spin' | 'part') -> the longest spell a person may ask of him."""
    t = test_captain.tables()["spell"]
    out = {}
    for g, row in t["groups"].items():
        s, k = 1.0, 0
        while s >= SPELL_TAIL and k < 60:
            k += 1
            s *= row["continue"]["normal"][bisect.bisect_right(t["len_edges"], k)]
        out[g] = k
    return out


class Desk:
    def __init__(self, m, control: dict):
        self.m = m
        self.control = {t.name: control[t.name] for t in m.teams if t.name in control}
        self.log = {name: [] for name in self.control}          # the person's calls, for the report
        self.bars = {name: {} for name in self.control}         # team -> player id -> bars
        self.farm = {name: True for name in self.control}       # team -> bat with the tail as real sides do
        self.pace: dict = {}                                    # team -> how far to play before the next pause
        self.seen: dict = {}                                    # team -> (innings, balls already shown)
        self.declare_after: dict = {}                           # innings number -> no "declare?" before this over
        self.new_ball_after: dict = {}                          # innings number -> no "new ball?" before this over
        self.caps = spell_caps()
        self._ball = None                                       # the delivery just bowled, until it is logged

    # ------------------------------------------------------------------ asking
    def has(self, team) -> bool:
        return team.name in self.control

    def manual(self, team, kind: str, inn=None) -> bool:
        ctl = self.control.get(team.name)
        return bool(ctl and ctl.manual(kind, self.m.key, inn.number if inn else None))

    def ask(self, team, kind: str, payload: dict, inn=None, skip_inn: bool = True):
        """The person's answer (None: the computer's call, also when the decision is not theirs)."""
        if not self.manual(team, kind, inn if skip_inn else None):
            return None
        q = {"kind": kind, "team": team.name, "match_key": self.m.key,
             "innings": inn.number if inn and skip_inn else None,
             "state": self.live(inn) if inn else self.pre_state(team), **payload}
        if inn:
            q["since"] = self.since(team, inn)
        return self.control[team.name].decide(q)

    def note(self, team, kind: str, when: str, you, computer, delta: float | None = None) -> None:
        name = lambda x: x.name if isinstance(x, Player) else x
        self.log[team.name].append({"kind": kind, "when": when, "you": name(you), "computer": name(computer),
                                    "changed": name(you) != name(computer),
                                    "delta": None if delta is None else round(delta, 2)})

    def when(self, inn) -> str:
        c = self.m.clock
        return f"day {c.day}, {inn.bat.name} {inn.score_str()} ({inn.over_str()} ov)"

    # ------------------------------------------------------------------ what the person sees
    def pre_state(self, team) -> dict:
        m = self.m
        a, b = m.teams
        return {"match": f"{a.name} v {b.name}", "venue": m.venue, "pitch": m.conditions["report"],
                "format": "test", "overs": None, "days": m.days, "timeless": m.timeless, "day_night": m.day_night, "day_overs": m.clock.day_overs, "rain": [],
                "host": m.host, "opponent": (b if team is a else a).name}

    def chances(self, inn, left: float) -> list | None:
        """[the batting side wins, a draw, the bowling side wins] as things stand, or None without the table."""
        if not self.m.wdl:
            return None
        pw, pd = self.m.wdl.probs(inn.number, inn.wkts, inn.x(), left)
        return [round(pw, 3), round(pd, 3), round(max(1.0 - pw - pd, 0.0), 3)]

    def live(self, inn) -> dict:
        m, c = self.m, self.m.clock
        st = self.pre_state(inn.bat)
        n = len(inn.overs)
        need = inn.target - inn.runs if inn.target is not None else None
        st.update({
            "innings": inn.number, "label": inn.label, "batting": inn.bat.name, "bowling": inn.bowl.name,
            "runs": inn.runs, "wkts": inn.wkts, "overs_done": inn.over_str(), "max_overs": None,
            "target": inn.target, "need": need, "balls_left": None, "win_prob": None,
            "crr": round(6 * inn.runs / inn.legal, 2) if inn.legal else None,
            "rrr": round(need / c.left, 2) if need is not None and c.left > 0 else None,
            "day": min(c.day, c.days), "session": c.session if c.day <= c.days else 3,
            "left_today": c.left_today if c.day <= c.days else 0, "left": c.left,
            "lead": inn.lead(), "margin": inn.margin_text(), "wdl": self.chances(inn, c.left),
            "ball_age": n - inn.ball_start, "new_ball_in": max(test_captain.NEW_BALL_OVERS - (n - inn.ball_start), 0),
            "mode": inn.mode,
            "previous": [f"{i.bat.name} {i.runs if i.wkts >= 10 else i.score_str()}{'d' if i.declared else ''}"
                         f" ({i.over_str()} ov)" for i in m.innings if i is not inn],
            "batters": [{"name": x.p.name, "runs": x.runs, "balls": x.balls, "fours": x.fours, "sixes": x.sixes,
                         "out": x.out, "how": (x.how or {}).get("text"), "batted": x.batted,
                         "on_strike": x is inn.striker and not x.out,
                         "at_crease": x in (inn.striker, inn.non_striker) and not x.out} for x in inn.cards],
            "bowlers": [{"name": f.p.name, "overs": f"{f.balls // 6}.{f.balls % 6}", "maidens": f.maidens,
                         "runs": f.runs, "wkts": f.wkts} for f in inn.figs.values()],
            "partnership": {"runs": inn.pship["runs"], "balls": inn.pship["balls"]},
            "recent": [{"over": o["over"], "bowler": o["bowler"], "balls": o["balls"], "runs": o["runs"]}
                       for o in inn.overs[-4:]],
            "events": [e["over"] + " " + e["text"] for e in inn.events[-6:]],
            "day_log": [f"Day {d['day']}: {d['close']}" for d in m.day_log],
        })
        return st

    def rates(self, p: Player, inn) -> tuple[float, float]:
        """(runs, wickets) a ball expected of this bowler now: his ratings against an average batter in today's
        conditions, with the pitch wear and ball age for his type."""
        m = self.m
        base = m.base_of(p, inn.bat)[PHASE]
        mult = m.sit.multipliers(m.sit.cell(min(inn.number, 3), inn.wkts, inn.lead()), 30, p.bowl_type or "unknown",
                                 m.overs_bowled, len(inn.overs) - inn.ball_start) if m.use_situation else {}
        b = p.bowl[PHASE]
        return (base["runs"] * b["runs"] * mult.get("runs", 1.0) + base["wide"] * p.wide + base["noball"] * p.noball,
                base["wkt"] * b["wkt"] * mult.get("wkt", 1.0))

    def pinfo(self, p: Player, inn=None) -> dict:
        r = p.ref or {}
        b, w = r.get("bat") or {}, r.get("bowl") or {}
        if p.keeper:
            role = "WK"
        elif (p.bowl_role or "").startswith("spec"):
            role = ("All-rounder" if p.bat_role in ("top", "middle") else
                    "Spin" if p.bowl_type == "spin" else "Pace")
        else:
            role = "Batter"
        d = {"id": p.id, "name": p.name, "role": role, "hand": p.bat_hand, "overseas": False,
             "kind": (p.bowl_kind or p.bowl_type or "").replace("_", " "), "slot": p.usual_slot,
             "bat_avg": b.get("avg"), "bat_sr": b.get("sr"),
             "bowl_econ": w.get("econ") if p.rated_bowl else None, "bowl_avg": w.get("avg") if p.rated_bowl else None,
             "overs_per_match": round(p.bowl_overs_per_match, 1)}
        if inn is not None and inn.bowl is not None and p in inn.bowl.players:
            rr, ww = self.rates(p, inn)
            d["phase_econ"] = round(6 * rr, 2)
            d["exp_avg"] = round(rr / ww, 1) if ww > 0 else None
        return d

    # ------------------------------------------------------------------ the replay
    def ball(self, inn, bowler: Player, o, seq: list) -> None:
        """A delivery is about to be booked: remember who was in (see `flush`)."""
        self._ball = (inn, bowler, inn.striker, inn.non_striker, inn.legal - bool(o.legal), o, seq)

    def flush(self) -> None:
        """Log the delivery for the field replay (presentation only). Called when it has been booked, or
        earlier, when a question about the next batter is about to be asked (the dismissal and the score are
        final by then)."""
        if not self._ball:
            return
        inn, bowler, st, ns, legal_before, o, seq = self._ball
        sym = seq[-1]
        self._ball = None
        out = (st if st.out else ns if ns.out else None) if o.wicket else None
        how = (out.how or {}) if out else {}
        role = None
        if how.get("fielder_id"):
            role = ("keeper" if how["fielder_id"] == (inn.bowl.keeper.id if inn.bowl.keeper else None)
                    else "bowler" if how["fielder_id"] == bowler.id else "fielder")
        inn.ball_log.append({
            "n": len(inn.ball_log), "innings": inn.number, "over": legal_before // 6 + 1,
            "ball": legal_before % 6 + 1, "sym": sym, "phase": "middle",
            "batter": st.p.name, "batter_id": st.p.id, "hand": st.p.bat_hand or "right",
            "non_striker": ns.p.name, "bowler": bowler.name, "bowl_type": bowler.bowl_type or "pace",
            "bowl_kind": (bowler.bowl_kind or "").replace("_", " "),
            "plan": self.bars_of(inn.bowl, bowler), "bars": self.bars_of(inn.bat, st.p),
            "runs": o.bat_runs, "extra": o.extra, "extra_runs": o.extra_runs, "ran": o.ran,
            "byes": o.byes, "bye_kind": o.bye_kind,
            "wicket": o.wicket or None, "out": out.p.name if out else None,
            "out_end": ("striker" if out is st else "non_striker") if out else None,
            "fielder": how.get("fielder"), "fielder_role": role, "how": how.get("text"),
            "free_hit": False, "score": f"{inn.runs}/{inn.wkts}", "batting": inn.bat.name})

    def since(self, team, inn) -> list:
        """The balls of this innings the person has not been shown (at most SINCE_MAX)."""
        seen = self.seen.get(team.name)
        out = inn.ball_log[seen[1]:] if seen and seen[0] == inn.number else inn.ball_log
        self.seen[team.name] = (inn.number, len(inn.ball_log))
        return out[-SINCE_MAX:]

    # ------------------------------------------------------------------ bars and pace
    def bars_of(self, team, p: Player) -> int:
        mine = self.bars.get(team.name)
        return mine.get(p.id, NORMAL_BARS) if mine else NORMAL_BARS

    def bars_for(self, inn, bowler: Player) -> tuple[int, int]:
        """(batting bars of the striker, plan bars of the bowler) for the coming ball; 5, 5 when the bars are
        the computer's (left to it, or skipped past)."""
        bb = self.bars_of(inn.bat, inn.striker.p) if self.manual(inn.bat, "ball", inn) else NORMAL_BARS
        wb = self.bars_of(inn.bowl, bowler) if self.manual(inn.bowl, "ball", inn) else NORMAL_BARS
        return bb, wb

    def farms(self, inn) -> bool:
        """Does the batting side bat with the tail as real sides do (farm the strike, shield the tailender)?
        Always for a computer side and for a person who leaves the bars to it; a person may turn it off."""
        return self.farm.get(inn.bat.name, True) or not self.manual(inn.bat, "ball", inn)

    def tail_stand(self, inn) -> dict | None:
        """For the bars question: the stand with the tail now at the crease, or None."""
        m = self.m
        if not m.use_tail or inn.wkts < m.tail_wkts:
            return None
        t = tail_table()
        a, b = inn.striker, inn.non_striker
        roles = {tail_role(a.pos, b.pos, inn.wkts), tail_role(b.pos, a.pos, inn.wkts)}
        if not roles - {None}:
            return None
        senior = a if a.pos < t["tail_from"] else b if b.pos < t["tail_from"] else None
        return {"on": self.farm.get(inn.bat.name, True), "senior": senior.p.name if senior else None,
                "real_share": t["real_strike_share"].get(str(inn.wkts)) if senior else None}

    def key_moment(self, inn) -> bool:
        c = self.m.clock
        n = len(inn.overs)
        if n == 0 or c.left <= KEY_LAST_OVERS:
            return True
        last = inn.overs[-1]
        if last["wkts"] or (last["day"], last["session"]) != (c.day, c.session):
            return True
        if n - inn.ball_start >= test_captain.NEW_BALL_OVERS or (n == inn.ball_start and n):
            return True
        return inn.target is not None and inn.target - inn.runs <= KEY_CLOSE_RUNS

    def pause(self, team, inn) -> bool:
        """Is the coming over one the person stops at (their pace since the last bars question)?"""
        pc = self.pace.get(team.name)
        if not pc or pc["inn"] != inn.number or pc["until"] == "over":
            return True
        u, c = pc["until"], self.m.clock
        if u == "innings":
            return False
        if u == "wicket":
            return inn.wkts != pc["wkts"]
        if u == "session":
            return (c.day, c.session) != (pc["day"], pc["session"])
        if u == "day":
            return c.day != pc["day"]
        return self.key_moment(inn)

    def fast(self, team, inn) -> bool:
        """Playing on to the end of the session, the day or the innings: the computer makes the small calls
        (bowling changes, the next batter, the new ball) until then."""
        pc = self.pace.get(team.name)
        return bool(pc and pc["inn"] == inn.number and pc["until"] in ("session", "day", "innings")
                    and self.manual(team, "ball", inn) and not self.pause(team, inn))

    def set_pace(self, team, inn, until) -> None:
        c = self.m.clock
        self.pace[team.name] = {"until": until if until in UNTIL else "over", "inn": inn.number, "day": c.day,
                                "session": c.session, "wkts": inn.wkts}

    def set_bars(self, team, ans: dict) -> None:
        mine = self.bars[team.name]
        for side in ("bat", "bowl"):
            for pid, v in (ans.get(side) or {}).items():
                try:
                    mine[str(pid)] = min(9, max(1, int(v)))
                except (TypeError, ValueError):
                    pass
        if isinstance(ans.get("farm"), bool):
            self.farm[team.name] = ans["farm"]

    def _batter(self, inn, c) -> dict:
        m = self.m
        return {"id": c.p.id, "name": c.p.name, "runs": c.runs, "balls": c.balls, "fours": c.fours,
                "sixes": c.sixes, "settled": round(m.sit.settled(c.balls), 2),
                "bars": self.bars_of(inn.bat, c.p) if self.has(inn.bat) else None,
                "sr": round(100 * m.base[PHASE]["runs"] * c.p.bat[PHASE]["runs"], 1)}

    def bars_question(self, team, inn, bowler: Player | None, change_overs: int = 2) -> dict:
        batting = team is inn.bat
        q = {"side": "bat" if batting else "bowl", "phase": "middle", "over": len(inn.overs) + 1, "ball": 1,
             "this_over": [], "free_hit": False, "projected": None, "default": None, "unit": "over",
             "key": self.key_moment(inn),
             "striker": self._batter(inn, inn.striker), "non_striker": self._batter(inn, inn.non_striker),
             "tail": self.tail_stand(inn) if batting else None,
             "can_declare": batting and inn.number < 4 and self.m.declare_on,
             "advice": self.declare_advice(inn, self.m.clock.left, change_overs) if batting and inn.number < 4 else None,
             "can_change": not batting and self.manual(team, "bowler", inn)}
        if bowler is not None:
            f = inn.fig(bowler)
            rr, _ = self.rates(bowler, inn)
            q["bowler"] = {"id": bowler.id, "name": bowler.name,
                           "kind": (bowler.bowl_kind or bowler.bowl_type or "").replace("_", " "),
                           "figures": f"{f.balls // 6}.{f.balls % 6}-{f.maidens}-{f.runs}-{f.wkts}",
                           "bars": None if batting else self.bars_of(team, bowler), "econ": round(6 * rr, 2)}
        else:                                    # the batting side is asked before the bowler is named
            last = inn.overs[-2]["bowler"] if len(inn.overs) >= 2 else None
            q["bowler"] = {"id": "", "name": last or "", "kind": "", "figures": "", "bars": None, "econ": None}
        return q

    # ------------------------------------------------------------------ before the match
    def toss(self, winner, default: str) -> str:
        ans = self.ask(winner, "toss", {"options": ["bat", "bowl"], "default": default,
                                        "text": f"{winner.name} won the toss."})
        if self.manual(winner, "toss"):
            self.note(winner, "toss", "toss", ans if ans in ("bat", "bowl") else default, default)
        return ans if ans in ("bat", "bowl") else default

    def xis(self, first, second, toss_text: str) -> None:
        """Each person's XI, batting order and keeper (None or an invalid answer: the computer's). Two people:
        both are asked at the same moment (post, then wait), so neither waits for the other to finish."""
        asked = []
        for team in (first, second):
            if not self.manual(team, "xi"):
                continue
            squad = team.squad or team.players + team.bench
            default = {"xi": [p.id for p in team.order], "keeper": team.keeper.id, "subs": []}
            self.control[team.name].post({
                "kind": "xi", "team": team.name, "match_key": self.m.key, "innings": None,
                "state": self.pre_state(team), "options": [self.pinfo(p) for p in squad], "default": default,
                "max_overseas": None, "n_subs": 0, "batting_first": team is first, "toss": toss_text})
            asked.append((team, squad, default))
        for team, squad, default in asked:
            self._xi(team, squad, default, self.control[team.name].wait())

    def _xi(self, team, squad: list, default: dict, ans) -> None:
        by = {p.id: p for p in squad}
        xi = [by[i] for i in (ans or {}).get("xi") or [] if i in by] if isinstance(ans, dict) else []
        keeper = by.get(ans.get("keeper")) if isinstance(ans, dict) else None
        if len(xi) != len(team.players) or len(set(xi)) != len(xi) or keeper not in xi:
            self.note(team, "xi", "after the toss", "the computer's XI", "the computer's XI")
            return
        same = [p.id for p in xi] == default["xi"] and keeper.id == default["keeper"]
        self.note(team, "xi", "after the toss", "the computer's XI" if same else "your XI", "the computer's XI")
        team.players, team.order, team.keeper = list(xi), list(xi), keeper
        team.bench = [p for p in squad if p not in xi]
        if team.captain not in xi:
            team.captain = max(xi, key=lambda p: p.bat_balls + p.bowl_balls)

    # ------------------------------------------------------------------ follow-on and declarations
    def _mine(self, pw: float, pd: float, batting: bool) -> list:
        """[win, draw] for the person's side from the batting side's (win, draw)."""
        return [round(pw if batting else max(1.0 - pw - pd, 0.0), 3), round(pd, 3)]

    @staticmethod
    def _value(wd: list | None) -> float | None:
        return None if wd is None else wd[0] + wd[1] / 2

    def _delta(self, you: list | None, computer: list | None) -> float | None:
        """Runs gained by the person's call over the computer's (chances x the table's runs per win)."""
        if you is None or computer is None:
            return None
        return (self._value(you) - self._value(computer)) * self.m.wdl.runs_per_win

    def follow_on(self, team, lead: int, default: bool, p: float, i2, change_overs: int) -> bool:
        if not self.manual(team, "follow_on"):
            return default
        m = self.m
        left = max(m.clock.left - change_overs, 0)
        adv = None
        if m.wdl:
            adv = {"enforce": self._mine(*m.wdl.probs(3, 0, -lead, left), False),
                   "bat": self._mine(*m.wdl.probs(3, 0, lead, left), True)}
        ans = self.ask(team, "follow_on", {"default": default, "lead": lead, "real": round(p, 2), "advice": adv,
                                           "opponent_score": f"{i2.bat.name} {i2.runs}"}, i2, skip_inn=False)
        you = default if ans is None else bool(ans)
        key = lambda e: "enforce" if e else "bat"
        self.note(team, "follow_on", f"lead {lead}", "enforce" if you else "bat again",
                  "enforce" if default else "bat again",
                  self._delta(adv[key(you)], adv[key(default)]) if adv else None)
        return you

    def declare_advice(self, inn, left: float, change_overs: int) -> dict | None:
        """The person's chances after declaring now and as things stand (left: overs left in the match)."""
        m = self.m
        if not m.wdl:
            return None
        lead = inn.lead()
        after = max(left - change_overs, 0)
        x = -lead - 1 if inn.number == 3 else -lead        # the next innings: the other side's lead / runs to get
        return {"declare": self._mine(*m.wdl.probs(inn.number + 1, 0, x, after), False),
                "bat_on": self._mine(*m.wdl.probs(inn.number, inn.wkts, inn.x(), left), True)}

    def declare(self, inn, computer: bool, left: float, change_overs: int, session_start: bool = False) -> bool:
        """The declaration call for a side a person captains. computer: the computer's captain would declare
        now. Asked when it would (not more often than every DECLARE_REASK overs) and at the start of a session."""
        team = inn.bat
        if not self.manual(team, "declare", inn):
            return computer
        n = len(inn.overs)
        if not session_start and (not computer or n < self.declare_after.get(inn.number, 0)):
            return False
        adv = self.declare_advice(inn, left, change_overs)
        ans = self.ask(team, "declare", {"default": computer, "lead": inn.lead(), "advice": adv,
                                         "moment": "start of the session" if session_start else "end of the over"}, inn)
        you = computer if ans is None else bool(ans)
        if computer and ans is not None and not you:           # the person said no: not asked again for a while
            self.declare_after[inn.number] = n + DECLARE_REASK
        key = lambda d: "declare" if d else "bat_on"
        self.note(team, "declare", self.when(inn), "declare" if you else "bat on",
                  "declare" if computer else "bat on",
                  self._delta(adv[key(you)], adv[key(computer)]) if adv else None)
        return you

    # ------------------------------------------------------------------ before an over: the batting side
    def over_start(self, inn, change_overs: int) -> bool:
        """The batting side's pauses before an over: the declaration at the start of a session, then the bars.
        True: the person declares now."""
        team = inn.bat
        if not self.has(team):
            return False
        m, c = self.m, self.m.clock
        n = len(inn.overs)
        can = inn.number < 4 and m.declare_on
        if can and n and (inn.overs[-1]["day"], inn.overs[-1]["session"]) != (c.day, c.session):
            nineties = any(x.runs % 100 >= 90 for x in (inn.striker, inn.non_striker))
            if test_captain.declare_prob(inn.number, inn.runs, inn.lead(), inn.wkts, c.left, nineties) >= DECLARE_POINT \
                    and self.declare(inn, False, c.left, change_overs, session_start=True):
                return True
        if not self.manual(team, "ball", inn) or not self.pause(team, inn):
            return False
        ans = self.ask(team, "ball", self.bars_question(team, inn, None, change_overs), inn)
        ans = ans if isinstance(ans, dict) else {}
        self.set_bars(team, ans)
        self.set_pace(team, inn, ans.get("until"))
        if can and ans.get("declare"):
            adv = self.declare_advice(inn, c.left, change_overs)
            self.note(team, "declare", self.when(inn), "declare", "bat on",
                      self._delta(adv["declare"], adv["bat_on"]) if adv else None)
            return True
        return False

    # ------------------------------------------------------------------ before an over: the fielding side
    def new_ball(self, inn, n: int, default: bool = True) -> bool:
        """The new ball is available: take it? default: what the computer captain would do now (real captains
        often wait while spin is on); it is the answer when the person leaves the call to the computer."""
        team = inn.bowl
        if not self.manual(team, "new_ball", inn) or self.fast(team, inn):
            return default
        if n < self.new_ball_after.get(inn.number, 0):
            return False
        ans = self.ask(team, "new_ball", {"default": default, "age": n - inn.ball_start,
                                          "bowlers": [self.pinfo(p, inn) for p in inn.bowling.cands]}, inn)
        take = default if ans is None else bool(ans)
        if ans is not None and not take:          # a person's "not yet" holds for a while
            self.new_ball_after[inn.number] = n + NEW_BALL_REASK
        say = {True: "take it", False: "not yet"}
        self.note(team, "new_ball", self.when(inn), say[take], say[default])
        return take

    def can_bowl(self, inn, n: int) -> list:
        """The bowlers a person may choose for over n: not the man who bowled the last over, and nobody past
        his workload (spell_caps) today; if that leaves nobody, anyone but the last bowler."""
        bw = inn.bowling
        free = [p for p in bw.cands if p is not bw.prev] or list(bw.cands)
        day = self.m.clock.day
        ok = []
        for p in free:
            cap = self.caps.get(bw.grp[p], 10)
            recent = [o for o in inn.overs[-(3 * cap - 1):] if o["day"] == day]
            if sum(o["bowler"] == p.name for o in recent) < cap:
                ok.append(p)
        return ok or free

    def over_cost(self, p: Player, inn) -> float:
        """Expected cost of an over from p: runs conceded less the runs his wickets are worth (the era's runs
        per wicket)."""
        base = self.m.base[PHASE]
        par = base["runs"] / max(base["wkt"] + base["other_out"], 1e-6)
        rr, ww = self.rates(p, inn)
        return 6 * (rr - par * ww)

    def bowler(self, inn, n: int, default: Player, due: bool) -> Player:
        """Who bowls over n for a side a person captains; then the plan bars for him."""
        team = inn.bowl
        if not self.has(team):
            return default
        pick = default
        on = inn.overs[n - 2] if n >= 2 else None              # the last over from this end
        change = on is None or on["bowler"] != default.name or on["day"] != self.m.clock.day
        if self.manual(team, "bowler", inn) and (change or due or self.key_moment(inn)) \
                and not self.fast(team, inn):
            pick = self.ask_bowler(inn, n, default)
        if self.manual(team, "ball", inn) and self.pause(team, inn):
            for again in (True, False):
                ans = self.ask(team, "ball", self.bars_question(team, inn, pick), inn)
                ans = ans if isinstance(ans, dict) else {}
                self.set_bars(team, ans)
                self.set_pace(team, inn, ans.get("until"))
                if not (again and ans.get("change") and self.manual(team, "bowler", inn)):
                    break
                pick = self.ask_bowler(inn, n, pick, computer=default)
        return pick

    def ask_bowler(self, inn, n: int, default: Player, computer: Player | None = None) -> Player:
        team = inn.bowl
        opts = self.can_bowl(inn, n)
        if default not in opts:
            opts = [default] + opts
        if len(opts) < 2:
            return default
        day = self.m.clock.day

        def card(p):
            today = sum(o["bowler"] == p.name and o["day"] == day for o in inn.overs)
            last = inn.bowling.last.get(p)
            return dict(self.pinfo(p, inn), quota_left=None, overs_today=today,
                        rested=None if last is None or last < 0 else n - last - 1)
        ans = self.ask(team, "bowler", {"options": [card(p) for p in opts], "default": default.id, "over": n + 1,
                                        "impact": None, "ball_age": n - inn.ball_start}, inn)
        pick = next((p for p in opts if isinstance(ans, dict) and p.id == ans.get("bowler")), default)
        ref = computer or default
        self.note(team, "bowler", f"day {self.m.clock.day}, over {n + 1}", pick, ref,
                  0.0 if pick is ref else self.over_cost(ref, inn) - self.over_cost(pick, inn))
        return pick

    # ------------------------------------------------------------------ the fall of a wicket
    def batter(self, inn, default: int, nightwatch: int | None, left_today: int) -> int:
        """Index in inn.cards of the batter a person sends in. default: the next in the order; nightwatch: the
        card the nightwatchman rule would send instead (None: the rule does not apply)."""
        team = inn.bat
        computer = nightwatch if nightwatch is not None else default
        rem = inn.cards[inn.next_in:]
        if len(rem) < 2 or self.fast(team, inn):
            return computer
        self.flush()                                           # the ball that took the wicket, before the question
        when = f"day {self.m.clock.day}, wicket {inn.wkts} ({inn.ball_str()} ov)"
        if self.manual(team, "batter", inn):
            ans = self.ask(team, "batter", {
                "options": [self.pinfo(c.p) for c in rem], "default": inn.cards[computer].p.id, "impact": None,
                "nightwatchman": inn.cards[nightwatch].p.id if nightwatch is not None else None,
                "left_today": left_today}, inn)
            k = next((i for i in range(inn.next_in, len(inn.cards))
                      if isinstance(ans, dict) and inn.cards[i].p.id == ans.get("batter")), computer)
            self.note(team, "batter", when, inn.cards[k].p, inn.cards[computer].p)
            return k
        if nightwatch is not None and self.manual(team, "nightwatchman", inn):
            ans = self.ask(team, "nightwatchman", {
                "default": True, "player": self.pinfo(inn.cards[nightwatch].p),
                "next": self.pinfo(inn.cards[default].p), "left_today": left_today}, inn)
            use = True if ans is None else bool(ans)
            self.note(team, "nightwatchman", when, "nightwatchman" if use else "the next batter", "nightwatchman")
            return nightwatch if use else default
        return computer

    # ------------------------------------------------------------------ the end
    def result(self, card: dict) -> None:
        from .test_series import innings_scores
        last = self.m.innings[-1] if self.m.innings else None
        pause = {"result": card["result"]["text"], "winner": card["result"].get("winner"),
                 "pom": card.get("player_of_match"), "scores": innings_scores(card)}
        for c in self.control.values():         # the full scorecard, while the result waits
            c.last_card = card
        asked = []
        for t in self.m.teams:                  # two people: both see the result at once (post, then wait)
            if last is not None and self.manual(t, "result"):
                q = {"kind": "result", "team": t.name, "match_key": self.m.key, "innings": last.number,
                     "state": self.live(last), "since": self.since(t, last), **pause}
                self.control[t.name].post(q)
                asked.append(t)
        for t in asked:
            self.control[t.name].wait()

