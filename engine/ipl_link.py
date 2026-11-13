"""The IPL alongside a state career ("Play the IPL alongside", engine/state_career.py).

The IPL runs as a franchise career (engine/career.py) with the computer deciding for every franchise, sharing the
state career's player records: one record per player (age, form, retirement), so a state player bought at the
auction is the same player in both. The state career ages everyone, draws everyone's form and retires everyone
(IPL-only players too); the IPL keeps its own squads, contracts and statistics, and writes the franchise a
player played for under "ipl" in his record (his state stays under "teams"). What the teams believe about a
player (engine/belief.py) is one record too: the Trophy and the IPL both add what they saw of him, and only an
IPL-only player gets a made-up record of his cricket outside the IPL. The IPL draws each season's form after
its auction (franchise career's order), so the Trophy and the IPL seasons have their own form.

The calendar is the real one: the Mushtaq Ali Trophy of season Y-(Y+1) is played in November, the IPL auction
in December and the IPL of Y+1 in the spring. So after each state season:
1. the IPL year passes: players who retired from (or were dropped by) the state career leave their franchises;
   players unsold in two auctions in a row drop out of the auction pool (back to state cricket only);
2. newcomers: while real IPL seasons last, the season's real debutants (as in franchise career) and the SCOUTED
   best uncapped performers of the Mushtaq Ali Trophy just played (by MVP points) who are not in the pool yet;
   after the real seasons, as many Trophy performers as the IPL really had Indian debutants a season (average of
   its last 5 seasons) and made-up overseas newcomers (franchise career's method);
   while real seasons last, franchises follow the real league: new ones join (with an empty squad, at a mega
   auction) and renamed ones take their new name;
3. the auction, the computer for everyone: a mega auction in the real mega auction years (MEGA_YEARS) and every
   MEGA_EVERY seasons after the last one, a mini auction in between;
4. the season (double round robin and IPL playoffs).
The first IPL season (the one after the starting state season) is played with its real squads, no auction.
"""
from __future__ import annotations

from .career import UNSOLD_LEAVE, Career, _seasons

LEAGUE = "ipl"
MEGA_EVERY = 3
MEGA_YEARS = (2008, 2011, 2014, 2018, 2022, 2025)
RENAMES = {"Delhi Daredevils": "Delhi Capitals", "Kings XI Punjab": "Punjab Kings",
           "Royal Challengers Bangalore": "Royal Challengers Bengaluru"}
SCOUTED = 6                       # real seasons: Trophy performers added to the real debutants
SCOUT_AGE = 32                    # older uncapped players are not noticed


class LinkedIpl(Career):
    TEAMS_KEY = "ipl"
    KEYS = tuple(k for k in Career.KEYS if k != "players")     # the players live in the state career

    local: frozenset = frozenset()      # players in a state squad this season (set by the state career)

    @classmethod
    def start(cls, players: dict, year: int, seed: int, knowledge: str = "realistic") -> "LinkedIpl":
        """The real IPL season of `year` (the nearest one outside the data), its players merged into `players`."""
        ss = _seasons(LEAGUE)
        s = next((x for x in ss if x["year"] == year), None) or (ss[-1] if year > ss[-1]["year"] else ss[0])
        c = cls(LEAGUE, s["season"], seed=seed, mega_every=MEGA_EVERY, name="IPL", knowledge=knowledge)
        for pid, r in c.players.items():
            players.setdefault(pid, r)          # a player already in the state career keeps his record
        c.players = players
        return c

    @classmethod
    def load(cls, d: dict, players: dict) -> "LinkedIpl":
        c = cls.from_json(d)
        c.players = players
        return c

    def _sees_outside(self, pid: str) -> bool:
        """A state player's cricket outside the IPL is the Trophy, which the state career observes itself."""
        return pid not in self.local

    def to_json(self) -> dict:
        return {k: getattr(self, k) for k in self.KEYS}

    def mega(self, year: int) -> bool:
        last = MEGA_YEARS[-1]
        return year in MEGA_YEARS or (year > last and (year - last) % self.mega_every == 0)

    def next_teams(self) -> int:
        """How many franchises the next IPL season has."""
        ss = _seasons(LEAGUE)
        if self.phase == "season" or self.real_i + 1 >= len(ss):
            return len(self.franchises)
        names = {t["franchise"] for t in ss[self.real_i + 1]["teams"]}
        return len(set(self.franchises) | names) - sum(o in self.franchises and n in names for o, n in RENAMES.items())

    def _follow(self, s: dict) -> list[str]:
        """Franchises as in the real season s: renamed ones take their new name, new ones join. Returns the new."""
        names = [t["franchise"] for t in s["teams"]]
        for old, new in RENAMES.items():
            if old in self.franchises and new in names and new not in self.franchises:
                self.franchises[self.franchises.index(old)] = new
                self.squads[new] = self.squads.pop(old)
                self.homes[new] = self.homes.pop(old, None)
        added = [t for t in s["teams"] if t["franchise"] not in self.franchises]
        for t in added:
            self.franchises.append(t["franchise"])
            self.squads[t["franchise"]] = {}
            self.homes[t["franchise"]] = t.get("home_venue")
        for t in s["teams"]:
            self.homes[t["franchise"]] = t.get("home_venue") or self.homes.get(t["franchise"])
        self.max_overseas = s["max_overseas"]
        return [t["franchise"] for t in added]

    def contracted(self) -> dict:
        """player -> (franchise, contract in lakh) for everyone in an IPL squad."""
        return {pid: (t, price) for t in self.franchises for pid, price in self.squads[t].items()}

    def advance(self, performers: list[str]) -> dict:
        """A year passes for the IPL: departures, newcomers (real debutants, Trophy performers from `performers`
        in order of merit, made-up overseas players); then an auction is due. Returns what happened."""
        self.year += 1
        self.season_no += 1
        gone = lambda pid: self.players[pid]["retired"] is not None
        for t in self.franchises:
            self.squads[t] = {pid: v for pid, v in self.squads[t].items() if not gone(pid)}
        self.free = {pid: n for pid, n in self.free.items() if not gone(pid) and n < UNSOLD_LEAVE}
        ss = _seasons(LEAGUE)
        real, overseas, joined = [], 0, []
        if self.real_i + 1 < len(ss):
            self.real_i += 1
            s = ss[self.real_i]
            self.season_label = s["season"]
            joined = self._follow(s)
            before = {pid for x in ss[:self.real_i] for t in x["teams"] for pid in t["players"]}
            here = set(self.active())
            for t in s["teams"]:
                for pid in t["players"]:
                    if pid in before or pid in here:
                        continue
                    self._add_real(pid, pid in t["overseas"])       # no-op for a player the state career has
                    if not gone(pid):
                        self.free[pid] = 0
                        real.append(pid)
            n = SCOUTED
        else:
            self.season_label = str(self.year)
            overseas = self._made_up(overseas=True)
            n = self.debut_rate(overseas=False)
        here = set(self.active())
        noticed = []
        for pid in performers:
            if len(noticed) >= n:
                break
            r = self.players.get(pid)
            if (r and r["retired"] is None and not r["overseas"] and not self.capped(pid) and pid not in here
                    and self.age(pid) <= SCOUT_AGE):
                self.free[pid] = 0
                noticed.append(pid)
        self.auction_kind = "mega" if joined or self.mega(self.year) else "mini"
        self.phase = "auction"
        return {"real": real, "noticed": noticed, "overseas": overseas, "kind": self.auction_kind, "joined": joined}
