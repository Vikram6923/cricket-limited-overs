"""The scorecard of one innings, whatever the format: batting cards, bowling figures, extras, fall of wickets,
partnerships, the over log and events.

`Scorebook.apply` books one delivery (an `Outcome` from engine/ballmodel.py). What an innings is (how long it
lasts, who bowls, who comes in next) is the business of the class built on it: `engine.match.Innings` for limited
overs. A subclass sets `done`, `legal` counts up here, and it provides `next_batter` and, if it has more to say
about its state, `state_dict`.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from .data import Player


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


class Scorebook:
    log_milestones = True        # team fifties and partnership fifties as events (off in a super over)

    def __init__(self, bat, bowl, number: int, rng: random.Random, order: list[Player] | None = None):
        """bat, bowl: the two sides (objects with .name, .players, .keeper, .captain, .order); rng: the match's
        random stream (who takes a catch)."""
        self.bat, self.bowl, self.number, self.rng = bat, bowl, number, rng
        order = order or bat.order
        self.cards = [BatInns(p, i + 1) for i, p in enumerate(order)]
        self.figs: dict[Player, BowlFig] = {}
        self.runs = self.wkts = self.legal = 0
        self.extras = {"b": 0, "lb": 0, "w": 0, "nb": 0}
        self.fow, self.partnerships, self.overs, self.events = [], [], [], []
        self.next_in = 2
        self.striker, self.non_striker = self.cards[0], self.cards[1]
        self.striker.batted = self.non_striker.batted = True
        self.pship = {"runs": 0, "balls": 0, "a": self.striker, "b": self.non_striker, "a_runs": 0, "b_runs": 0}
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

    # ------------------------------------------------------------------ one delivery
    def apply(self, o, bowler: Player, f: BowlFig, seq: list):
        s = self.striker
        total = o.bat_runs + o.extra_runs
        self.runs += total
        if o.extra:
            self.extras[o.extra] += o.extra_runs - o.byes
            if o.byes:
                self.extras[o.bye_kind] += o.byes
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
        if total and self.log_milestones:
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
        f.runs += o.bat_runs + (o.extra_runs - o.byes if o.extra in ("w", "nb") else 0)
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
            seq.append(f"{o.bat_runs}nb" if o.bat_runs else f"nb+{o.byes}{o.bye_kind}" if o.byes else "nb")
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
        rng = self.rng
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
        new = self.next_batter(out)
        text = (f"{out.p.name} {out.how['text']} {out.runs} ({out.balls}b) {out.fours}x4 {out.sixes}x6"
                f" - partnership {p['runs']}" + (f" - new batter {new.p.name}" if new else ""))
        self.event(text, "wicket", player_id=out.p.id, partnership=p["runs"],
                   new_batter=new.p.name if new else None)
        if k != "run_out" and f.wkts >= 5:
            ov = f"{f.balls // 6}" + (f".{f.balls % 6}" if f.balls % 6 else "")
            self.event(f"{bowler.name} {ov}-{f.maidens}-{f.runs}-{f.wkts}", "five_wickets",
                       player_id=bowler.id, wickets=f.wkts)

    # ------------------------------------------------------------------ the next batter
    def next_batter(self, out: BatInns) -> BatInns | None:
        """A wicket has just been booked: end the innings (new_partnership(), return None) or choose who comes
        in and return bring_in(index of his card, out). The format's rules decide; see engine.match.Innings."""
        raise NotImplementedError

    def new_partnership(self) -> None:
        self.pship = {"runs": 0, "balls": 0, "a": self.striker, "b": self.non_striker, "a_runs": 0, "b_runs": 0}

    def bring_in(self, j: int, out: BatInns) -> BatInns:
        """The batter on card j takes the place of `out` at the crease."""
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
        self.new_partnership()
        return new

    def close_partnership(self):
        p = self.pship
        if p["balls"] or p["runs"]:
            self.partnerships.append({"wkt": self.wkts + 1, "runs": p["runs"], "balls": p["balls"],
                                      "batters": [p["a"].p.name, p["b"].p.name], "split": [p["a_runs"], p["b_runs"]],
                                      "unbroken": True})

    # ------------------------------------------------------------------ output
    def state_dict(self) -> dict:
        """What the format adds to the innings' header (a target, an over limit, a declaration ...)."""
        return {}

    def to_dict(self) -> dict:
        bowl_order = list(self.figs.values())
        return {
            "number": self.number, "team": self.bat.name, "bowling_team": self.bowl.name,
            "runs": self.runs, "wickets": self.wkts, "balls": self.legal, "overs": self.over_str(),
            **self.state_dict(), "extras": dict(self.extras),
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
