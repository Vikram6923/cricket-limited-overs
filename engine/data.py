"""Load ratings, baselines and fitted tables; turn rating records into engine players.

Everything is cached per format, so many simulated matches share one load.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

PHASES = ("powerplay", "middle", "death")
METRICS = ("runs", "wkt", "dot", "four", "six")
FORMATS = {
    "t20": {"overs": 20, "quota": 4, "phases": ((0, 5, "powerplay"), (6, 14, "middle"), (15, 19, "death")),
            "intl": "t20i_full"},
    "odi": {"overs": 50, "quota": 10, "phases": ((0, 9, "powerplay"), (10, 39, "middle"), (40, 49, "death")),
            "intl": "odi_full"},
}
YEAR_POOL_BALLS = 6000  # a baseline year with fewer balls than this borrows from neighbouring years


def phase_of(over: int, fmt: str) -> str:
    for lo, hi, name in FORMATS[fmt]["phases"]:
        if lo <= over <= hi:
            return name
    return "death"


@dataclass
class Player:
    id: str
    name: str
    team: str = ""
    position: float | None = None
    bat_role: str = "middle"
    bowl_role: str = "part_unk"
    bat_hand: str | None = None
    bowl_type: str | None = None   # pace / spin / None
    bowl_kind: str | None = None
    keeper: bool = False
    rated_bat: bool = True
    rated_bowl: bool = True
    bat: dict = field(default_factory=dict)    # phase -> metric -> index
    bowl: dict = field(default_factory=dict)
    other_out: float = 1.0                     # run-out (non-bowler dismissal) index
    wide: float = 1.0
    noball: float = 1.0
    bat_balls: int = 0
    bowl_balls: int = 0
    bowl_phase_share: dict = field(default_factory=dict)   # how this bowler was really used: phase -> share
    opener_share: float = 0.0                              # share of his innings batting at 1 or 2
    usual_slot: int | None = None                          # most common batting position
    bowl_overs_per_match: float = 0.0
    ref: dict = field(default_factory=dict)    # readable reference numbers from the ratings

    def __hash__(self):
        return hash(self.id)

    def __eq__(self, other):
        return isinstance(other, Player) and other.id == self.id


@lru_cache(maxsize=None)
def ratings(fmt: str) -> dict:
    return json.loads((DATA / f"ratings_{fmt}.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def basics(fmt: str) -> dict:
    return json.loads((DATA / "engine" / f"basics_{fmt}.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def _keepers(fmt: str) -> frozenset:
    return frozenset(basics(fmt).get("keepers", []))


def _prior(fmt: str, side: str, group: str, team: str) -> dict:
    """Newcomer / unrated prior: role-group mean x team level, per metric (same for every phase)."""
    meta = ratings(fmt)["meta"]
    out = {}
    for m in METRICS:
        g = meta["role_means"][m][side].get(group)
        if g is None:
            vals = list(meta["role_means"][m][side].values())
            g = sum(vals) / len(vals) if vals else 1.0
        t = meta["team_levels"][m][side].get(team, 1.0)
        out[m] = g * t
    return {ph: dict(out) for ph in PHASES}


def player(fmt: str, pid: str, name: str | None = None, team: str | None = None) -> Player:
    """Engine player from the ratings; unknown IDs get the role/team prior."""
    rec = ratings(fmt)["players"].get(pid)
    if rec is None:
        p = Player(id=pid, name=name or pid, team=team or "unknown", rated_bat=False, rated_bowl=False)
        p.bat = _prior(fmt, "bat", "middle", p.team)
        p.bowl = _prior(fmt, "bowl", "part_unk", p.team)
        p.keeper = pid in _keepers(fmt)
        return p
    p = Player(id=pid, name=name or rec["name"], team=team or rec.get("team") or "unknown",
               position=rec.get("position"), bat_role=rec.get("bat_role") or "middle",
               bowl_role=rec.get("bowl_role") or "part_unk", bat_hand=rec.get("bat_hand"),
               bowl_type=rec.get("bowl_type"), bowl_kind=rec.get("bowl_kind"),
               keeper=pid in _keepers(fmt))
    b, w = rec.get("bat"), rec.get("bowl")
    if b:
        p.bat = {ph: {m: float(b["phase"][ph][m]) for m in METRICS} for ph in PHASES}
        p.other_out = float(b.get("other_out_idx") or 1.0)
        p.bat_balls = int(b.get("balls") or 0)
        p.ref["bat"] = b.get("ref")
    else:
        p.rated_bat = False
        p.bat = _prior(fmt, "bat", p.bat_role, p.team)
    if w:
        p.bowl = {ph: {m: float(w["phase"][ph][m]) for m in METRICS} for ph in PHASES}
        p.wide = float(w.get("wide_idx") or 1.0)
        p.noball = float(w.get("noball_idx") or 1.0)
        p.bowl_balls = int(w.get("balls") or 0)
        p.ref["bowl"] = w.get("ref")
        pb = w.get("phase_balls") or {}
        tot = sum(pb.values())
        typ = typical_phase_share(fmt, p.bowl_type)
        k = 60.0  # balls of the typical profile mixed in, so a short record doesn't dominate
        p.bowl_phase_share = {ph: (pb.get(ph, 0) + k * typ[ph]) / (tot + k) for ph in PHASES}
        car = rec.get("career") or {}
        inns = sum((c.get("m") or 0) for c in car.values() if isinstance(c, dict))
        p.bowl_overs_per_match = (p.bowl_balls / 6) / inns if inns else 0.0
    else:
        p.rated_bowl = False
        p.bowl = _prior(fmt, "bowl", p.bowl_role, p.team)
    if not p.bowl_phase_share:
        p.bowl_phase_share = typical_phase_share(fmt, p.bowl_type)
    hist = _positions(fmt).get(pid)
    if hist:
        tot = sum(hist.values())
        p.opener_share = (hist.get(1, 0) + hist.get(2, 0)) / tot
        p.usual_slot = max(hist, key=hist.get)
    return p


@lru_cache(maxsize=None)
def _positions(fmt: str) -> dict:
    """Batting-position histograms from the raw stats (T20: internationals + leagues combined)."""
    files = ["players_odi.json"] if fmt == "odi" else ["players_t20.json", "players_t20_league.json"]
    out: dict = {}
    for f in files:
        path = DATA / "raw_stats" / f
        if not path.exists():
            continue
        for pid, r in json.loads(path.read_text(encoding="utf-8")).items():
            h = out.setdefault(pid, {})
            for k, v in (r.get("positions") or {}).items():
                h[int(k)] = h.get(int(k), 0) + v
    return out


@lru_cache(maxsize=None)
def _typical_shares(fmt: str) -> dict:
    acc: dict = {}
    for r in ratings(fmt)["players"].values():
        w = r.get("bowl")
        if not w or not w.get("phase_balls"):
            continue
        t = r.get("bowl_type") or "unknown"
        a = acc.setdefault(t, {ph: 0 for ph in PHASES})
        for ph in PHASES:
            a[ph] += w["phase_balls"].get(ph, 0)
    out = {}
    for t, a in acc.items():
        tot = sum(a.values()) or 1
        out[t] = {ph: a[ph] / tot for ph in PHASES}
    return out


def typical_phase_share(fmt: str, bowl_type: str | None) -> dict:
    """Typical share of a bowler's balls in each phase, by bowling type (pace / spin / unknown)."""
    t = _typical_shares(fmt)
    return t.get(bowl_type or "unknown") or t.get("unknown") or {ph: 1 / 3 for ph in PHASES}


@lru_cache(maxsize=None)
def baseline(fmt: str, comp: str, year: int) -> dict:
    """Per-phase per-ball rates for a competition and year. Thin years are pooled with neighbouring years;
    years outside the competition's coverage use the nearest covered year."""
    base = ratings(fmt)["baselines"]
    if comp not in base:
        raise KeyError(f"no baselines for competition {comp!r}; have {sorted(base)}")
    years = sorted(int(y) for y in base[comp])
    y0 = min(years, key=lambda y: abs(y - year))
    out = {}
    for ph in PHASES:
        acc, n = {}, 0.0
        for width in range(0, 6):
            rows = [base[comp][str(y)][ph] for y in years if abs(y - y0) <= width and ph in base[comp][str(y)]]
            n = sum(r["balls"] for r in rows)
            if n >= YEAR_POOL_BALLS or width == 5:
                for k in ("runs", "runs_sq", "wkt", "dot", "four", "six", "wide", "noball", "other_out"):
                    acc[k] = sum(r[k] * r["balls"] for r in rows) / n if n else 0.0
                break
        out[ph] = acc
    return out


def competitions(fmt: str) -> list[str]:
    return sorted(ratings(fmt)["baselines"])


def search(fmt: str, text: str, limit: int = 10) -> list[tuple[str, str, str]]:
    """(id, name, team) of rated players whose name contains `text` (case-insensitive)."""
    t = text.lower()
    hits = [(pid, r["name"], r.get("team") or "") for pid, r in ratings(fmt)["players"].items()
            if t in r["name"].lower()]
    hits.sort(key=lambda h: -((ratings(fmt)["players"][h[0]].get("bat") or {}).get("balls", 0)
                              + (ratings(fmt)["players"][h[0]].get("bowl") or {}).get("balls", 0)))
    return hits[:limit]
