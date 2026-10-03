"""Fantasy draft (build-order step 6): teams take turns picking squads from a player pool, then play a league.

A library, not a prompt loop (the Test sim's draft.py read picks with input()): the UI calls `pick()` for the
user's team and `run_cpu()` to let the computer teams pick until it is the user's turn again.

- Pool: players with at least `min_matches` matches in the years, rated on those years (engine/periods.py), as in
  the Classic modes. Sources: "full" = full-member internationals (default), "intl" = all internationals,
  "leagues" (T20) = full-member internationals + franchise leagues. Associates are off by default: their ratings
  come mostly from games against other associates and come out too high (a known step-2 limitation; in an
  all-nations pool an Austrian batter ranked 2nd of 1,982 T20 players). min_matches = 10 keeps out players with
  one series in the period, whose rating is mostly their career or team prior.
- Order: snake (1..k, k..1, ...), random first order from the seed.
- Computer teams: like the Test sim's draft AI, a squad template plus "best available": each player is scored by
  how far above the pool he is as a batter and as a bowler (z-scores of the captain's own batting value and
  bowling cost), plus a bonus while the team still lacks his role (keeper, pace, spin, batters) and a penalty once
  the role is full. A little noise makes drafts differ. This is game AI, not a model of real selectors.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from statistics import mean, pstdev

from .captain import batting_value, bowling_cost
from .history import FULL_MEMBERS
from .data import DATA, FORMATS, PHASES, baseline, player, ratings

SQUAD = 15
# minimum squad make-up for computer teams (and the "needs" shown to the user); the rest is best available
NEEDS = {"keeper": 1, "pace": 3, "spin": 2, "batter": 6}
CAPS = {"keeper": 2, "pace": 6, "spin": 4, "batter": 9}
DEFAULT_TEAMS = ["London", "Melbourne", "Mumbai", "Cape Town", "Bridgetown", "Kolkata", "Sydney", "Manchester",
                 "Auckland", "Colombo", "Delhi", "Dhaka", "Kingston", "Johannesburg", "Abu Dhabi", "Perth"]


@dataclass
class PoolPlayer:
    id: str
    name: str
    nation: str
    matches: int
    role: str            # WK / Batter / All-rounder / Pace / Spin
    roles: set           # draft needs this player fills: keeper / batter / pace / spin
    z_bat: float = 0.0
    z_bowl: float = 0.0
    ref: dict = field(default_factory=dict)

    def row(self) -> dict:
        b, w = self.ref.get("bat") or {}, self.ref.get("bowl") or {}
        return {"id": self.id, "name": self.name, "team": self.nation, "role": self.role, "m": self.matches,
                "bat_avg": b.get("avg"), "bat_sr": b.get("sr"), "econ": w.get("econ") if self.roles & {"pace", "spin"} else None,
                "bowl_avg": w.get("avg") if self.roles & {"pace", "spin"} else None,
                "value": round(self.value(), 2)}

    def value(self) -> float:
        """Draft value: the better of the two skills, plus a share of the other for genuine all-rounders."""
        hi, lo = max(self.z_bat, self.z_bowl), min(self.z_bat, self.z_bowl)
        return hi + 0.3 * max(lo, 0.0)


SOURCES = ("full", "intl", "leagues")


def _appearances(fmt: str, y1: int, y2: int, source: str) -> dict:
    """pid -> (matches in the period that count for the pool, team shown: his nation, else his main league team)."""
    files = ["players_odi.json"] if fmt == "odi" else ["players_t20.json"]
    if source == "leagues" and fmt == "t20":
        files.append("players_t20_league.json")
    intl: dict = {}
    league: dict = {}
    for f in files:
        path = DATA / "raw_stats" / f
        if not path.exists():
            continue
        target = league if f == "players_t20_league.json" else intl
        for pid, r in json.loads(path.read_text(encoding="utf-8")).items():
            for yr, rec in (r.get("by_year") or {}).items():
                if y1 <= int(yr) <= y2:
                    c = target.setdefault(pid, {})
                    for t, n in (rec.get("teams") or {}).items():
                        c[t] = c.get(t, 0) + n
    out = {}
    for pid in set(intl) | set(league):
        ci = {t: n for t, n in intl.get(pid, {}).items() if source == "intl" or t in FULL_MEMBERS}
        cl = league.get(pid, {})
        m = sum(ci.values()) + sum(cl.values())
        if m:
            if intl.get(pid):
                nation = max(intl[pid], key=intl[pid].get)
            else:
                rated = (ratings(fmt)["players"].get(pid) or {}).get("team")
                nation = rated if rated in FULL_MEMBERS else max(cl, key=cl.get)
            out[pid] = (m, nation)
    return out


def build_pool(fmt: str, y1: int, y2: int, source: str = "full", min_matches: int = 10) -> list[PoolPlayer]:
    if source not in SOURCES:
        raise ValueError(f"Unknown pool: {source}")
    apps = _appearances(fmt, y1, y2, source)
    base = baseline(fmt, FORMATS[fmt]["intl"], y2)
    spec_opm = FORMATS[fmt]["quota"] * 0.5
    pool, bats, bowls = [], [], []
    for pid, (m, team) in apps.items():
        if m < min_matches:
            continue
        p = player(fmt, pid, years=(y1, y2))
        if not (p.rated_bat or p.rated_bowl):
            continue
        bowler = p.rated_bowl and p.bowl_overs_per_match >= spec_opm
        roles = set()
        if p.keeper:
            roles.add("keeper")
        if bowler:
            roles.add("spin" if p.bowl_type == "spin" else "pace")
        bv = batting_value(p)
        wv = -sum(bowling_cost(p, ph, base[ph], fmt) for ph in PHASES) if bowler else None
        pp = PoolPlayer(pid, p.name, team, m, "", roles, ref=dict(p.ref))
        pp._bv, pp._wv = bv, wv
        pool.append(pp)
        bats.append(bv)
        if wv is not None:
            bowls.append(wv)
    mb, sb = mean(bats), pstdev(bats) or 1.0
    mw, sw = (mean(bowls), pstdev(bowls) or 1.0) if bowls else (0.0, 1.0)
    for pp in pool:
        pp.z_bat = (pp._bv - mb) / sb
        pp.z_bowl = (pp._wv - mw) / sw if pp._wv is not None else -3.0
        bowler = bool(pp.roles & {"pace", "spin"})
        if pp.z_bat > 0.5 or not bowler:
            pp.roles.add("batter")
        if "keeper" in pp.roles:
            pp.role = "WK"
        elif bowler and pp.z_bat > 0.5:
            pp.role = "All-rounder"
        elif bowler:
            pp.role = "Spin" if "spin" in pp.roles else "Pace"
        else:
            pp.role = "Batter"
    pool.sort(key=lambda x: -x.value())
    return pool


class Draft:
    def __init__(self, fmt: str, y1: int, y2: int, teams: list[str], user: str | None = None,
                 source: str = "full", seed: int | None = None, squad: int = SQUAD, min_matches: int = 10):
        if len(teams) < 2:
            raise ValueError("A draft needs at least 2 teams.")
        if len({t.lower() for t in teams}) != len(teams):
            raise ValueError("Team names must be different.")
        if user is not None and user not in teams:
            raise ValueError("Your team must be one of the teams.")
        self.fmt, self.y1, self.y2, self.user, self.source, self.squad = fmt, y1, y2, user, source, squad
        self.seed = seed if seed is not None else random.randrange(1 << 30)
        self.rng = random.Random(self.seed)
        self.pool = build_pool(fmt, y1, y2, source, min_matches)
        if len(self.pool) < squad * len(teams):
            raise ValueError(f"Only {len(self.pool)} players in the pool for {y1}-{y2}: not enough for "
                             f"{len(teams)} squads of {squad}. Widen the years or use fewer teams.")
        self.by_id = {p.id: p for p in self.pool}
        self.teams = list(teams)
        first = self.teams[:]
        self.rng.shuffle(first)
        self.order = [t for r in range(squad) for t in (first if r % 2 == 0 else first[::-1])]   # snake
        self.picks: dict[str, list[str]] = {t: [] for t in self.teams}
        self.log: list[dict] = []
        self.taken: set[str] = set()

    # ---------------------------------------------------------------- state
    @property
    def done(self) -> bool:
        return len(self.log) >= len(self.order)

    def current(self) -> str | None:
        return None if self.done else self.order[len(self.log)]

    def counts(self, team: str) -> dict:
        c = {k: 0 for k in NEEDS}
        for pid in self.picks[team]:
            for r in self.by_id[pid].roles:
                if r in c:
                    c[r] += 1
        return c

    def available(self) -> list[PoolPlayer]:
        return [p for p in self.pool if p.id not in self.taken]

    # ---------------------------------------------------------------- picking
    def pick(self, pid: str, team: str | None = None) -> None:
        team = team or self.current()
        if self.done:
            raise ValueError("The draft is over.")
        if team != self.current():
            raise ValueError(f"It is {self.current()}'s pick.")
        if pid not in self.by_id:
            raise ValueError("That player is not in the pool.")
        if pid in self.taken:
            raise ValueError(f"{self.by_id[pid].name} has already been picked.")
        self.taken.add(pid)
        self.picks[team].append(pid)
        self.log.append({"n": len(self.log) + 1, "round": len(self.picks[team]), "team": team, "id": pid,
                         "name": self.by_id[pid].name})

    def score(self, team: str, p: PoolPlayer, noise: bool = True) -> float:
        c, left = self.counts(team), self.squad - len(self.picks[team])
        short = {r: max(0, NEEDS[r] - c[r]) for r in NEEDS}
        s = p.value()
        fills = [r for r in p.roles if r in NEEDS]
        if any(short[r] for r in fills):
            s += 0.6 + 1.5 * sum(short.values()) / max(left, 1)
        if fills and all(c[r] >= CAPS[r] for r in fills):
            s -= 2.0
        # don't leave a need unfilled: once remaining picks equal the shortfall, only needed roles count
        if sum(short.values()) >= left and not any(short[r] for r in fills):
            s -= 10.0
        return s + (self.rng.gauss(0, 0.25) if noise else 0.0)

    def suggestions(self, team: str, n: int = 8, per_role: int = 2) -> list[PoolPlayer]:
        """Best picks for the team's needs, at most per_role of each role so the list shows the options."""
        out, seen = [], {}
        for p in sorted(self.available(), key=lambda p: -self.score(team, p, noise=False)):
            if seen.get(p.role, 0) < per_role:
                out.append(p)
                seen[p.role] = seen.get(p.role, 0) + 1
            if len(out) >= n:
                break
        return out

    def cpu_pick(self) -> str:
        team = self.current()
        best = max(self.available()[:400], key=lambda p: self.score(team, p))
        self.pick(best.id, team)
        return best.id

    def run_cpu(self) -> None:
        """Computer teams pick until it is the user's turn or the draft is over."""
        while not self.done and self.current() != self.user:
            self.cpu_pick()

    # ---------------------------------------------------------------- output
    def team_specs(self) -> list[dict]:
        return [{"name": t, "squad": list(self.picks[t]), "years": [self.y1, self.y2]} for t in self.teams]

    def state(self) -> dict:
        cur = self.current()
        needs = {t: self.counts(t) for t in self.teams}
        return {"fmt": self.fmt, "y1": self.y1, "y2": self.y2, "teams": self.teams, "user": self.user,
                "squad": self.squad, "order": self.order[:len(self.teams)], "current": cur, "done": self.done,
                "pick_no": len(self.log) + (0 if self.done else 1), "total": len(self.order),
                "board": {t: [{"id": pid, "name": self.by_id[pid].name, "role": self.by_id[pid].role}
                              for pid in self.picks[t]] for t in self.teams},
                "needs": needs, "targets": NEEDS, "taken": sorted(self.taken),
                "suggestions": [p.id for p in self.suggestions(cur)] if cur and cur == self.user else []}
