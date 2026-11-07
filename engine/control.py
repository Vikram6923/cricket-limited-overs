"""Manual captaincy: a person captains one side and makes its decisions, the engine the rest.

The match asks a side's controller at each decision point (Match.ask). Every question carries the computer's own
choice (`default`) and the live state of the match, so the person can see what the engine would have done; the
answer None means "the computer's choice". Without a controller nothing changes.

Decisions ("kind"):
- toss    the side won the toss: "bat" or "bowl"
- xi      after the toss: the XI in batting order, the keeper, and (Impact Player matches) the 5 substitutes
- bowler  each over in the field: who bowls it (may also make the Impact Player substitution)
- batter  at the fall of a wicket: who goes in (may also make the Impact Player substitution)
- impact  the Impact Player substitution on its own: at the innings break, and whenever the computer would make it
          while the bowler / batter decisions are left to the computer
- result  a pause after each of the side's matches (nothing to decide)
- ball    ball by ball (opt-in, not in the default set): before a delivery, the aggression dials of the side's
          batters or bowler (1-9 bars, 5 = as real sides play) and how far to play before the next pause

Skipping: each kind can be left to the computer (`auto`), and play can be skipped ahead to the end of the innings,
the match, or everything (`skip`). Obvious decisions (one possible bowler, the last batter) are never asked.
Generic: the tournament runner attaches controllers by team name, so any mode can use them.

Two people (docs/multiplayer_design.md): each side has its own controller. Questions that both sides answer at the
same moment (the XI after the toss, each ball's aggression bars) are first posted to both controllers (`post`) and
then collected (`wait`), so neither person waits for the other to finish before seeing their own question.
An optional clock (`clock`: {kind: seconds}) answers None (the computer's choice; for "ball", keep the bars) when
the person takes too long.
"""
from __future__ import annotations

import threading
import time

KINDS = ("toss", "xi", "bowler", "batter", "impact", "result", "ball")
DEFAULT_KINDS = tuple(k for k in KINDS if k != "ball")   # ball by ball only when asked for


class Cancelled(Exception):
    """The run was stopped while waiting for a decision."""


class Controller:
    """Base controller: makes every decision the computer's way (useful for tests and as the interface)."""

    def __init__(self, team: str, manual: set | None = None):
        self.team = team
        self.manual_kinds = set(DEFAULT_KINDS if manual is None else manual)
        self.skip: dict | None = None          # {"scope": "innings"|"match"|"all", "match": key, "innings": n}
        self.context: dict = {}                # set by the tournament runner: stage, match number

    def manual(self, kind: str, match_key=None, innings: int | None = None) -> bool:
        """Is this decision the person's, now? (not left to the computer, not skipped past)"""
        if kind not in self.manual_kinds:
            return False
        s = self.skip
        if s:
            if s["scope"] == "all":
                return False
            if kind == "result":               # skipping to the end of an innings or match still shows the result
                return True
            if s["match"] == match_key and (s["scope"] == "match" or s["innings"] == innings):
                return False
        return True

    def decide(self, question: dict):
        return None

    def post(self, question: dict) -> None:
        """Open a question without waiting for the answer (see `wait`)."""
        self._posted = question

    def wait(self):
        """The answer to the question opened by `post`."""
        return self.decide(self._posted)


class WaitingController(Controller):
    """Waits for the answer from another thread (the browser): `pending` holds the open question, `answer()`
    supplies the reply. `cancel()` makes the waiting match raise Cancelled."""

    def __init__(self, team: str, manual: set | None = None, clock: dict | None = None):
        super().__init__(team, manual)
        self.pending: dict | None = None
        self.clock = dict(clock or {})         # kind -> seconds to answer (None / missing = no limit)
        self._n = 0
        self._event = threading.Event()
        self._reply = None
        self._cancelled = False

    def decide(self, question: dict):
        self.post(question)
        return self.wait()

    def post(self, question: dict) -> None:
        self._n += 1
        self._reply = None
        self._event.clear()
        secs = self.clock.get(question.get("kind"))
        self._deadline = time.time() + secs if secs else None
        self.pending = {"id": self._n, **question, "context": dict(self.context),
                        "seconds": secs or None, "deadline": self._deadline}

    def wait(self):
        while not self._event.wait(0.25 if not self._deadline else
                                   max(0.005, min(0.25, self._deadline - time.time()))):
            if self._cancelled:
                self.pending = None
                raise Cancelled()
            if self._deadline and time.time() > self._deadline:    # out of time: the computer's choice
                self.pending = None
                return None
        self.pending = None
        return self._reply

    def answer(self, qid: int, choice=None, auto: dict | None = None, skip: str | None = None) -> bool:
        """Reply to question `qid`: the choice (None = the computer's), decision kinds to hand to / take back from
        the computer ({kind: True = computer}), and a skip ("innings", "match", "all")."""
        q = self.pending
        if not q or q["id"] != qid:
            return False
        for k, v in (auto or {}).items():
            if k in KINDS:
                (self.manual_kinds.discard if v else self.manual_kinds.add)(k)
        if skip in ("innings", "match", "all"):
            self.skip = {"scope": skip, "match": q.get("match_key"), "innings": q.get("innings")}
        self._reply = choice
        self._event.set()
        return True

    def cancel(self) -> None:
        self._cancelled = True
