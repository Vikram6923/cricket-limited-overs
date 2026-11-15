"""The server's shared base: the Flask app, visitors (one per browser with --public), limits and housekeeping,
saved teams, the catalogue the page needs (competitions, venues, players), and where runs and careers are kept.

The server was one file (web_ui.py); it is now split by mode, and every part starts from this one:
    core.py     this file
    runs.py     the background job that plays a run, and the routes every mode uses (meta, teams, run, status)
    draft.py    Fantasy Draft          auction.py   Auction
    rooms.py    Two players            careers.py   Career
    saved.py    saved runs and results
web_ui.py starts it (python web_ui.py) and still offers every name (web_ui.app, web_ui.ROOMS ...).
"""
from __future__ import annotations

import argparse
import hmac
import json
import os
import random
import re
import secrets
import shutil
import socket
import threading
import time
import traceback
import webbrowser
from collections import Counter
from functools import lru_cache
from pathlib import Path

from flask import Flask, Response, abort, g, jsonify, request, send_from_directory

from engine.conditions import venue_table
from engine.control import DEFAULT_KINDS, KINDS, Cancelled, WaitingController
from engine.judge import AllBut, season_report
from engine import history
from engine.auction import Auction, season_pool, years_pool
from engine.career import Career
from engine.state_career import StateCareer, load as career_from_json, start_seasons
from engine.draft import DEFAULT_TEAMS, Draft
from engine import domestic
from engine.leagues import LEAGUES, ui_info as league_info
from engine.data import ratings
from engine.render import full_text, match_report
from engine.tournament import match_count, play_series, play_tournament, save

ROOT = Path(__file__).resolve().parent.parent
UI = ROOT / "webui"
TEAMS = ROOT / "data" / "teams.json"
TEAMS_DEFAULT = ROOT / "data" / "teams_default.json"
LAST = ROOT / "results" / "last"
SAVED = ROOT / "results" / "saved"        # runs the user saved: one folder each (summary.json, matches/, meta.json)
AUCTION_LAST = ROOT / "results" / "auction_last.json"   # squads of the last finished auction (to retain from)
CAREERS = ROOT / "results" / "careers"    # one folder per career: career.json, seasons/<season>/
VISITORS_DIR = ROOT / "results" / "visitors"   # --public: one folder per visitor, laid out like results/
SEASONS = ROOT / "data" / "league_seasons.json"   # every season of 11 leagues (scripts/build_league_presets.py)


def league_seasons() -> dict:
    return json.loads(SEASONS.read_text(encoding="utf-8")) if SEASONS.exists() else {}


def league_season(league: str | None, season: str | None) -> dict | None:
    """One season of a league (the latest if `season` is not given), with the league's label."""
    lg = league_seasons().get(league or "")
    if not lg:
        return None
    s = next((x for x in lg["seasons"] if x["season"] == season), None) if season else lg["seasons"][0]
    return {**s, "label": lg["label"]} if s else None

COMP_LABELS = {
    "t20i_full": "T20 internationals (full members)", "t20i": "T20 internationals (all teams)",
    **{c: lg.long for c, lg in LEAGUES.items()},
    "odi_full": "ODIs (full members)", "odi": "ODIs (all teams)",
}
KNOCKOUTS = {"semis": "Semi-finals + final", "ipl": "IPL playoffs (Q1, Eliminator, Q2, Final)",
             "final": "Final (top two)", "none": "No knockouts (league winner)"}

app = Flask(__name__, static_folder=None)
# MULTI (set by --public): every browser is its own visitor. Otherwise everyone shares LOCAL (one person, maybe
# with a phone on the same Wi-Fi), with the folders above.
app.config.update(MULTI=False, PASSWORD=None, MAX_JOBS=None, LIMITS=None)


# ------------------------------------------------------------------------------------------------ visitors

class Visitor:
    """One person's state: their job, draft and auction (in memory) and their folders. root None: the local
    user, whose folders are the module paths (read at call time, so tests can point them elsewhere)."""

    def __init__(self, vid: str, root: Path | None = None):
        self.id, self.root = vid, root
        self.job: Job | None = None
        self.draft: Draft | None = None     # the draft in progress (or just finished, waiting for its league)
        self.auction: Auction | None = None  # the auction in progress (or just finished, waiting for its league)
        self.seen = time.time()

    def _p(self, local: Path, name: str) -> Path:
        return local if self.root is None else self.root / name

    @property
    def teams_file(self) -> Path:
        return self._p(TEAMS, "teams.json")

    @property
    def last(self) -> Path:
        return self._p(LAST, "last")

    @property
    def saved(self) -> Path:
        return self._p(SAVED, "saved")

    @property
    def careers(self) -> Path:
        return self._p(CAREERS, "careers")

    @property
    def auction_last(self) -> Path:
        return self._p(AUCTION_LAST, "auction_last.json")

    def busy(self) -> bool:
        return bool(self.job and self.job.status == "running")


LOCAL = Visitor("local")
VISITORS: dict[str, Visitor] = {}      # --public: cookie id -> visitor
VID = re.compile(r"[A-Za-z0-9_-]{16,40}")
VLOCK = threading.Lock()


def V() -> Visitor:
    """The visitor making this request."""
    return g.get("visitor") or LOCAL


@app.before_request
def _before():
    pw = app.config.get("PASSWORD")
    if pw:                                 # one shared password (any user name), so strangers and bots stay out
        a = request.authorization
        if not a or not hmac.compare_digest(str(a.password or "").encode(), pw.encode()):
            return Response("This cricket simulator needs the password you were given.", 401,
                            {"WWW-Authenticate": 'Basic realm="Cricket simulator", charset="UTF-8"'})
    if not app.config.get("MULTI"):
        g.visitor = LOCAL
        return None
    vid = request.cookies.get("vid") or ""
    if not VID.fullmatch(vid):
        vid = g.new_vid = secrets.token_urlsafe(18)
    with VLOCK:
        v = VISITORS.get(vid)
        if v is None:
            v = VISITORS[vid] = Visitor(vid, VISITORS_DIR / vid)
            if v.root.exists():            # back after a restart: keep the folder from being cleaned up
                os.utime(v.root)
    v.seen = time.time()
    g.visitor = v
    return None


@app.after_request
def _after(resp):
    if g.get("new_vid"):
        resp.set_cookie("vid", g.new_vid, max_age=400 * 86400, httponly=True, samesite="Lax", secure=request.is_secure)
    return resp


def _limit(kind: str) -> int | None:
    """--public: how many saved teams / runs / careers one visitor may keep (None: no limit)."""
    return (app.config.get("LIMITS") or {}).get(kind) if V().root is not None else None


def _running_jobs() -> list:
    jobs = [v.job for v in [LOCAL, *VISITORS.values()]] + [r.get("job") for r in ROOMS.values()]
    return [j for j in dict.fromkeys(j for j in jobs if j) if j.status == "running"]


def _capacity_error() -> str | None:
    """--public: at most MAX_JOBS simulations at once (one process, so they share one CPU core)."""
    cap = app.config.get("MAX_JOBS")
    if cap and len(_running_jobs()) >= cap:
        return f"The server is busy ({cap} simulations are running). Try again in a minute."
    return None


def _cancel(job) -> None:
    if job and job.status == "running":
        job.cancel = True
        if job.controller:
            job.controller.cancel()
        for c in (job.controllers or {}).values():
            c.cancel()


IDLE_CANCEL = 15 * 60     # --public: stop a run nobody has looked at for this long (it would hold a job slot)
VISITOR_FORGET = 24 * 3600  # drop an idle visitor's in-memory draft / auction
ROOM_FORGET = 3 * 3600    # close a room neither player has opened for this long
KEEP_DAYS = 30            # delete a visitor's folder this long after their last visit


def _reaper() -> None:
    """--public housekeeping, once a minute: abandoned runs, idle visitors and rooms, old visitor folders."""
    while True:
        time.sleep(60)
        try:
            now = time.time()
            with LOCK:
                for code, r in list(ROOMS.items()):
                    seen = max(s["seen"] for s in r["seats"])
                    if now - seen > IDLE_CANCEL:
                        _cancel(r.get("job"))
                    if now - seen > ROOM_FORGET and not (r.get("job") and r["job"].status == "running"):
                        del ROOMS[code]
            with VLOCK:
                for vid, v in list(VISITORS.items()):
                    if now - v.seen > IDLE_CANCEL:
                        _cancel(v.job)
                    if now - v.seen > VISITOR_FORGET and not v.busy():
                        del VISITORS[vid]
                    elif v.root.exists() and now - v.seen < 3600:
                        os.utime(v.root)
                live = set(VISITORS)
            if VISITORS_DIR.exists():
                for d in VISITORS_DIR.iterdir():
                    if d.name not in live and now - d.stat().st_mtime > KEEP_DAYS * 86400:
                        shutil.rmtree(d, ignore_errors=True)
        except Exception:  # noqa: BLE001 - housekeeping must never stop
            traceback.print_exc()


# ------------------------------------------------------------------------------------------------ teams

def load_teams(v: Visitor | None = None) -> list[dict]:
    p = (v or V()).teams_file
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(TEAMS_DEFAULT, p)
    return json.loads(p.read_text(encoding="utf-8"))


def save_teams(teams: list[dict]) -> None:
    p = V().teams_file
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(teams, indent=1, ensure_ascii=False), encoding="utf-8")


@lru_cache(maxsize=None)
def home_grounds() -> dict:
    p = ROOT / "data" / "home_grounds.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def home_ground(entry, fmt: str, v: Visitor | None = None) -> str | None:
    """Primary home ground of a tournament side: a franchise's own ground (league presets), else its nation's
    (scripts/build_home_grounds.py): the historical team's nation, or the nation most of a saved team's players play
    for (at least 6). None (neutral venues) for mixed sides such as draft teams."""
    if isinstance(entry, dict):
        return home_grounds().get(fmt, {}).get(entry.get("nation"))
    saved = next((t for t in load_teams(v) if t["name"] == entry), None)
    if not saved:
        return None
    if saved.get("home_venue"):
        return saved["home_venue"]
    rows = ratings(fmt)["players"]
    nat = Counter((rows.get(p["id"]) or {}).get("team") for p in saved["players"])
    nat.pop(None, None)
    top = nat.most_common(1)
    return home_grounds().get(fmt, {}).get(top[0][0]) if top and top[0][1] >= 6 else None


def team_spec(entry, fmt: str = "t20", squad_size: int | None = history.SQUAD_SIZE, years_mode: str = "blend",
              v: Visitor | None = None) -> dict:
    """A saved team (by name, from v's teams) or a historical team ({"nation", "y1", "y2"}; squad = the most-capped
    squad_size, None = everyone who played; years_mode "blend" | "only", see engine/periods.py)."""
    if isinstance(entry, dict):
        return history.historical_team(fmt, entry["nation"], int(entry["y1"]), int(entry["y2"]), size=squad_size,
                                       years_mode=years_mode)
    t = next((t for t in load_teams(v) if t["name"] == entry), None)
    if not t:
        raise ValueError(f"no saved team called {entry!r}")
    ids = [p["id"] for p in t["players"]]
    spec = {"name": t["name"], "squad" if len(ids) > 11 else "players": ids}
    for k in ("overseas", "max_overseas"):   # league presets (e.g. IPL: at most 4 overseas players in the XI)
        if t.get(k) is not None:
            spec[k] = t[k]
    return spec


def check_entries(entries: list, fmt: str, owners: list | None = None) -> str | None:
    """Error message for a list of team entries, or None. Historical entries need a nation that played then.
    owners: whose saved teams each entry is (two players: each seat's own; default: this visitor's)."""
    owners = owners or [V()] * len(entries)
    lo, hi = history.first_year(fmt), history.last_year(fmt)
    seen = set()
    for e in entries:
        if isinstance(e, dict):
            try:
                y1, y2 = int(e.get("y1")), int(e.get("y2"))
            except (TypeError, ValueError):
                return "Years must be numbers."
            if y1 > y2:
                return f"Start year {y1} is after end year {y2}."
            if y1 < lo or y2 > hi:
                return f"{fmt.upper()} data covers {lo}-{hi}."
            if e.get("nation") not in dict(history.nations(fmt, y1, y2)):
                return f"{e.get('nation')} has too few {fmt.upper()} players in {y1}-{y2}."
            key = history.team_name(e["nation"], y1, y2)
        else:
            if e not in {t["name"] for t in load_teams(owners[len(seen)])}:
                return f"No saved team called {e!r}."
            key = e
        if key in seen:
            return f"{key} is picked twice."
        seen.add(key)
    return None


# ------------------------------------------------------------------------------------------------ reference data

@lru_cache(maxsize=None)
def competitions(fmt: str) -> list[dict]:
    base = ratings(fmt)["baselines"]
    out = []
    for comp, years in base.items():
        if comp.endswith("_mixed") or comp.endswith("_assoc"):
            continue
        ys = sorted(int(y) for y in years)
        out.append({"id": comp, "label": COMP_LABELS.get(comp, comp), "first": ys[0], "last": ys[-1]})
    order = list(COMP_LABELS)
    out.sort(key=lambda c: order.index(c["id"]) if c["id"] in order else 99)
    return out


@lru_cache(maxsize=None)
def venues(fmt: str) -> list[dict]:
    v = venue_table(fmt).get("venues", {})
    rows = [{"name": x["name"], "matches": x["matches"], "runs": x["runs"]} for x in v.values() if x["matches"] >= 5]
    return sorted(rows, key=lambda r: -r["matches"])


def _role(r: dict) -> str:
    """Display role for the builder: WK / All-rounder / Pace / Spin / Batter."""
    bowl = r.get("bowl") or {}
    spec = (r.get("bowl_role") or "").startswith("spec") and bowl.get("balls", 0) >= 300
    if r.get("keeper"):
        return "WK"
    if spec and r.get("bat_role") in ("top", "middle"):
        return "All-rounder"
    if spec:
        return "Spin" if r.get("bowl_type") == "spin" else "Pace"
    return "Batter"


@lru_cache(maxsize=None)
def players(fmt: str) -> list[dict]:
    from engine.data import basics
    keepers = set(basics(fmt).get("keepers", []))
    out = []
    for pid, r in ratings(fmt)["players"].items():
        b, w = r.get("bat") or {}, r.get("bowl") or {}
        if b.get("balls", 0) < 60 and w.get("balls", 0) < 60:
            continue
        years = [(c.get("first") or "")[:4] for c in (r.get("career") or {}).values() if c.get("first")]
        lasts = [(c.get("last") or "")[:4] for c in (r.get("career") or {}).values() if c.get("last")]
        rr = dict(r, keeper=pid in keepers)
        out.append({"id": pid, "name": r["name"], "team": r.get("team") or "", "role": _role(rr),
                    "kind": (r.get("bowl_kind") or "").replace("_", " "), "hand": r.get("bat_hand") or "",
                    "bat_balls": b.get("balls", 0), "bat_avg": (b.get("ref") or {}).get("avg"),
                    "bat_sr": (b.get("ref") or {}).get("sr"),
                    "bowl_balls": w.get("balls", 0), "econ": (w.get("ref") or {}).get("econ"),
                    "bowl_avg": (w.get("ref") or {}).get("avg"),
                    "first": min(years) if years else "", "last": max(lasts) if lasts else ""})
    return out


# ------------------------------------------------------------------------------------------------ two players: the rooms

LOCK = threading.Lock()
ROOMS: dict[str, dict] = {}   # code -> room


def _room_visitors(r: dict) -> list:
    """Everyone in the room (the seats, then the spectators): they all get the results."""
    return list(dict.fromkeys([s["visitor"] for s in r["seats"] if s["visitor"]] + list(r["spectators"].values())))


# ------------------------------------------------------------------------------------------------ where careers are kept

def _safe(name: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in str(name))[:60] or "x"


def _career_path(cid: str | None, v: Visitor | None = None) -> Path:
    root = (v or V()).careers
    d = root / _safe(cid or "")
    if d.parent != root:
        raise FileNotFoundError(cid)
    return d / "career.json"


def load_career(cid: str | None, v: Visitor | None = None) -> Career:
    return career_from_json(json.loads(_career_path(cid, v).read_text(encoding="utf-8")))


def save_career(cid: str, c: Career, v: Visitor | None = None) -> None:
    p = _career_path(cid, v)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(c.to_json()), encoding="utf-8")
    tmp.replace(p)


def careers_list() -> list[dict]:
    out = []
    root = V().careers
    if root.exists():
        for d in root.iterdir():
            p = d / "career.json"
            if p.exists():
                c = json.loads(p.read_text(encoding="utf-8"))
                out.append({"id": d.name, "name": c["name"], "league": c["league_label"], "user": c["user"],
                            "kind": c.get("kind", "franchise"), "ipl": bool(c.get("ipl")),
                            "season": c["season_label"], "played": len(c["history"]), "phase": c["phase"],
                            "titles": sum(h["champion"] == c["user"] for h in c["history"]) if c["user"] else None,
                            "updated": p.stat().st_mtime})
    return sorted(out, key=lambda r: -r["updated"])


# ------------------------------------------------------------------------------------------------ where runs are kept

def _run_dir(run: str | None) -> Path:
    """The last run, a saved one (by folder name) or a career's season ("career/<id>/<season>")."""
    v = V()
    if not run:
        return v.last
    if run.startswith("career/"):
        parts = run.split("/")
        d = v.careers / parts[1] / "seasons" / parts[-1] if len(parts) == 3 else None
        if not d or d.parent.parent.parent != v.careers or not (d / "summary.json").exists():
            abort(404)
        return d
    d = v.saved / run
    if d.parent != v.saved or not (d / "summary.json").exists():
        abort(404)
    return d


def _base_team(name: str) -> str:
    """A League Season side is named "<franchise> <season>": the franchise, for retention."""
    head, _, last = name.rpartition(" ")
    return head if head and any(ch.isdigit() for ch in last) else name


def _run_meta(d: Path) -> dict:
    """What the saved-runs list and retention need (cached in meta.json): mode, league / format, year, winner, the
    user's team, and every side's squad (an auction's or draft's squads; otherwise everyone who played)."""
    mp = d / "meta.json"
    if mp.exists():
        return json.loads(mp.read_text(encoding="utf-8"))
    s = json.loads((d / "summary.json").read_text(encoding="utf-8"))
    dr = s.get("draft") or {}
    mode = s.get("mode") or ("auction" if dr.get("auction") else "draft" if dr else s.get("kind"))
    squads: dict = {}
    if dr.get("board"):
        squads = {t: [p["id"] for p in ps] for t, ps in dr["board"].items()}
    else:
        for r in s.get("batting", []) + s.get("bowling", []):
            ids = squads.setdefault(_base_team(r["team"]), [])
            if r["id"] not in ids:
                ids.append(r["id"])
    meta = {"id": d.name, "name": d.name, "saved": time.strftime("%Y-%m-%d %H:%M", time.localtime(d.stat().st_mtime)),
            "mode": mode, "fmt": s.get("format"), "comp": s.get("competition"), "year": s.get("year"),
            "title": s.get("title"), "winner": s.get("winner") or s.get("result"), "user": dr.get("user"),
            "squads": squads}
    mp.write_text(json.dumps(meta), encoding="utf-8")
    return meta


def saved_runs() -> list[dict]:
    root = V().saved
    if not root.exists():
        return []
    out = []
    for d in root.iterdir():
        if (d / "summary.json").exists():
            m = _run_meta(d)
            out.append({k: v for k, v in m.items() if k != "squads"} | {"teams": sorted(m["squads"])})
    return sorted(out, key=lambda m: m["saved"], reverse=True)


def lan_addresses() -> list[str]:
    """This computer's IPv4 addresses on the local network (best guess, for the --lan message)."""
    found = []
    try:  # the address the OS would use to reach the outside; a UDP connect sends no packet
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 80))
            found.append(s.getsockname()[0])
    except OSError:
        pass
    try:
        found += socket.gethostbyname_ex(socket.gethostname())[2]
    except OSError:
        pass
    return [ip for ip in dict.fromkeys(found) if not ip.startswith("127.")]


__all__ = [n for n in dir() if not n.startswith("__")]      # everything, underscore names too: one program in several files
