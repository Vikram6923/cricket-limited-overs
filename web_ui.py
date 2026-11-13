"""Browser UI for the limited-overs simulator (build-order step 5).

    python web_ui.py              # opens http://localhost:5070
    python web_ui.py --no-browser --port 5071
    python web_ui.py --lan        # also reachable from other devices on the same Wi-Fi
    python web_ui.py --public     # a hosted site: every visitor gets their own runs (see README "Hosting it")

Plain Flask, a background job per visitor, the page polls /api/status (no websockets, no CDN scripts, works
offline). The engine is called directly as a library. Modes: Match / Series, Tournament, Classic Series and
Classic Tournament (a nation over a year range, rated on those years), League Season, Fantasy Draft, Auction,
Career (a league season after season, engine/career.py, or a Mushtaq Ali Trophy state, engine/state_career.py,
optionally with the IPL played alongside, engine/ipl_link.py;
kept in results/careers/<id>/), Team Builder.
Two players (docs/multiplayer_design.md): one match, each side captained by a person on their own device; any
number of rooms at once.
On your own computer there is one user: saved teams live in data/teams.json (created from data/teams_default.json
on first run) and the last results in results/last/, so they survive a restart. With --public each browser is a
visitor (a cookie) with its own job, draft, auction, teams and results under results/visitors/<id>/.
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

ROOT = Path(__file__).resolve().parent
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


# ------------------------------------------------------------------------------------------------ job

class Stopped(Exception):
    pass


class Job:
    def __init__(self, title: str, total: int):
        self.title, self.total, self.done = title, total, 0
        self.status, self.error = "running", None
        self.started, self.finished = time.time(), None
        self.cancel = False
        self.controller: WaitingController | None = None   # manual captaincy: the side the person captains
        self.controllers: dict | None = None    # two players: team name -> WaitingController (see ROOMS)
        self.winners: list = []                 # winner of each finished match (None: tie / no result)
        self.room: dict | None = None           # two players: the room the match belongs to

    def to_dict(self) -> dict:
        d = {"status": self.status, "title": self.title, "done": self.done, "total": self.total,
             "elapsed": round((self.finished or time.time()) - self.started, 1), "error": self.error,
             "mp": bool(self.controllers)}
        c = self.controller
        if c:
            d["captain"] = {"team": c.team, "manual": sorted(c.manual_kinds), "pending": c.pending,
                            "skip": (c.skip or {}).get("scope")}
        return d


LOCK = threading.Lock()


def _augment(res: dict) -> None:
    """Links the UI needs: match numbers for each player's fifties, hundreds, five-fors, top score and best figures;
    player-of-the-match counts; fielding merged into the batting rows."""
    fifties, hundreds, fives = {}, {}, {}
    hs, best, pom = {}, {}, {}
    for c in res["matches"]:
        n = c["match_no"]
        p = (c.get("player_of_match") or {}).get("id")
        if p:
            pom[p] = pom.get(p, 0) + 1
        for inn in c["innings"]:
            for b in inn["batting"]:
                if not b["batted"]:
                    continue
                k = (b["id"], inn["team"])
                x = {"n": n, "runs": b["runs"], "balls": b["balls"], "no": not b["out"], "opp": inn["bowling_team"]}
                if b["runs"] >= 100:
                    hundreds.setdefault(k, []).append(x)
                elif b["runs"] >= 50:
                    fifties.setdefault(k, []).append(x)
                if k not in hs or (b["runs"], not b["out"]) > (hs[k]["runs"], hs[k]["no"]):
                    hs[k] = x
            for w in inn["bowling"]:
                k = (w["id"], inn["bowling_team"])
                x = {"n": n, "wkts": w["wickets"], "runs": w["runs"], "overs": w["overs"], "opp": inn["team"]}
                if w["wickets"] >= 5:
                    fives.setdefault(k, []).append(x)
                if k not in best or (w["wickets"], -w["runs"]) > (best[k]["wkts"], -best[k]["runs"]):
                    best[k] = x
    field = {(f["id"], f["team"]): f for f in res.get("fielding", [])}
    for r in res["batting"]:
        k = (r["id"], r["team"])
        r["fifty_list"], r["hundred_list"] = fifties.get(k, []), hundreds.get(k, [])
        r["hs_match"] = hs.get(k, {}).get("n")
        r["pom"] = pom.get(r["id"], 0)
        f = field.get(k, {})
        r["catches"], r["stumpings"] = f.get("catches", 0), f.get("stumpings", 0)
    for r in res["bowling"]:
        k = (r["id"], r["team"])
        r["five_list"] = fives.get(k, [])
        r["best_match"] = best.get(k, {}).get("n")
    for f in res["fixtures"]:
        f["winner"] = next((c["result"].get("winner") for c in res["matches"] if c["match_no"] == f["match_no"]), None)


def _run(job: Job, params: dict, v: Visitor) -> None:
    """The run in a background thread, for visitor v (two players: the host). The results go to v's last run
    (two players: to everyone in the room)."""
    try:
        def on_match(card):
            job.done += 1
            job.winners.append(card["result"].get("winner"))
            if job.cancel:
                raise Stopped()
        fmt, comp, year = params["fmt"], params["comp"], int(params["year"])
        seed = int(params["seed"]) if str(params.get("seed") or "").strip() else random.randrange(1 << 30)
        venues_ = params.get("venues") or None
        rain_ = bool(params.get("rain"))
        size = history.SQUAD_SIZE          # Classic modes: most-capped N of the period ("" = everyone)
        if "squad_size" in params:
            size = int(params["squad_size"]) if params["squad_size"] else None
        ym = params.get("years_mode") if params.get("years_mode") in ("blend", "only") else "blend"
        control = {job.controller.team: job.controller} if job.controller else None   # a side the user captains
        if job.controllers:                    # two players, each captaining a side
            control = dict(job.controllers)
        skill = AllBut(params.get("opponents") or "expert", job.controller.team) if job.controller else None
        if params["mode"] == "league":
            s = league_season(params["league"], params.get("season"))
            specs = [{"name": t["name"], "squad": t["players"], "overseas": t["overseas"],
                      "max_overseas": t["max_overseas"]} for t in s["teams"]]
            homes = {t["name"]: t["home_venue"] for t in s["teams"] if t.get("home_venue")}
            res = play_tournament(specs, fmt="t20", comp=params["league"], year=s["year"], rounds=2, knockout="ipl",
                                  venues=venues_, home_venues=homes, seed=seed, rain=rain_, on_match=on_match,
                                  control=control, skill=skill)
        elif params["mode"] == "domestic":
            s = domestic.season(params.get("cup") or "sma", params.get("season"))
            res = play_tournament(**domestic.tournament_args(s), seed=seed, rain=rain_, on_match=on_match,
                                  control=control, skill=skill)
            res["domestic"] = {"cup": s["comp"], "label": s["label"], "season": s["season"], "squads": s["squads"],
                               "real": s["real"]}
        elif params["mode"] == "draft":
            groups = int(params.get("groups") or 1)
            dr = v.draft
            res = play_tournament(dr.team_specs(), fmt=fmt, comp=comp, year=year,
                                  rounds=int(params.get("rounds") or 1), groups=groups if groups > 1 else None,
                                  knockout=params.get("knockout") or "semis", venues=venues_, seed=seed, rain=rain_,
                                  on_match=on_match, control=control, skill=skill)
            res["draft"] = {"teams": dr.teams, "user": dr.user,
                            "board": dr.state()["board"], "years": [dr.y1, dr.y2]}
        elif params["mode"] == "auction":
            a = v.auction
            if a.comp:                         # a real season: its conditions, home grounds and IPL playoffs
                res = play_tournament(a.team_specs(), fmt="t20", comp=a.comp, year=a.year, rounds=2, knockout="ipl",
                                      home_venues={t: h for t, h in a.homes.items() if h}, seed=seed, rain=rain_,
                                      on_match=on_match, control=control, skill=skill)
            else:
                res = play_tournament(a.team_specs(), fmt=fmt, comp=comp, year=year,
                                      rounds=int(params.get("rounds") or 1), knockout=params.get("knockout") or "semis",
                                      venues=venues_, seed=seed, rain=rain_, on_match=on_match, control=control, skill=skill)
            sm = a.summary()
            res["draft"] = {"teams": sm["teams"], "user": sm["user"], "board": sm["board"], "auction": True,
                            "purse": sm["purse"]}
        elif params["mode"] == "career":
            car = load_career(params["career"], v)
            res = play_tournament(car.specs(), **car.play_args(), rain=rain_, on_match=on_match, control=control,
                                  skill=skill)
            res["career"] = {"id": params["career"], "name": car.name, "season": car.season_label}
        elif params["mode"] == "mp" and len(params.get("specs") or []) > 2:   # two players + computer teams
            res = play_tournament(params["specs"], fmt=fmt, comp=comp, year=year, rounds=int(params.get("rounds") or 1),
                                  knockout=params["knockout"], venues=venues_, home_venues=params.get("homes") or None,
                                  seed=seed, rain=rain_, on_match=on_match, control=control)
            res["draft"] = params["draft_info"]
        elif params["mode"] == "mp":           # a single match or a best-of series between the two players
            a, b = params["specs"]
            res = play_series(a, b, n=int(params.get("series") or 1), best_of=True,
                              fmt=fmt, comp=comp, year=year, venues=venues_, seed=seed, rain=rain_, on_match=on_match,
                              control=control)
            if params.get("draft_info"):
                res["draft"] = params["draft_info"]
        elif params["mode"] == "series":
            res = play_series(team_spec(params["team1"], fmt, size, ym, v), team_spec(params["team2"], fmt, size, ym, v),
                              n=int(params["matches"]),
                              fmt=fmt, comp=comp, year=year, venues=venues_, seed=seed, rain=rain_, on_match=on_match,
                              control=control, skill=skill)
        else:
            groups = int(params.get("groups") or 1)
            specs = [team_spec(t, fmt, size, ym, v) for t in params["teams"]]
            homes = {sp["name"]: h for t, sp in zip(params["teams"], specs) if (h := home_ground(t, fmt, v))}
            res = play_tournament(specs, fmt=fmt, comp=comp, year=year,
                                  rounds=int(params.get("rounds") or 1), groups=groups if groups > 1 else None,
                                  knockout=params.get("knockout") or "semis", venues=venues_, home_venues=homes,
                                  seed=seed, rain=rain_, on_match=on_match, control=control, skill=skill)
        res["title"] = job.title
        res["mode"] = params["mode"]
        if job.controller:                     # how the person's calls compared with the computer's
            res["captaincy"] = season_report(res["matches"], job.controller.team)
            if res["captaincy"]:
                res["captaincy"]["opponents"] = params.get("opponents") or "expert"
        if job.controllers:                    # each player's calls against the computer's
            res["captaincy_by"] = {t: season_report(res["matches"], t) for t in job.controllers}
            for r in res["captaincy_by"].values():
                if r:
                    r["opponents"] = "the other player"
            _mp_record(job, res)
        _augment(res)
        if job.cancel:                         # stopped (or abandoned) after the last match: keep the last run
            raise Stopped()
        dests = [v] if job.room is None else _room_visitors(job.room)
        for i, dv in enumerate(dests):         # two players: everyone in the room sees these results
            if dv.last.exists():
                shutil.rmtree(dv.last)
            if i == 0:
                save(res, dv.last)
            else:
                shutil.copytree(dests[0].last, dv.last)
        if params["mode"] == "career":           # into the career: its season folder, history and statistics
            label = _safe(car.season_label)
            d = v.careers / params["career"] / "seasons" / label
            if d.exists():
                shutil.rmtree(d)
            shutil.copytree(v.last, d)
            car.record(res, run=f"career/{params['career']}/{label}")
            ipl = getattr(car, "ipl", None) and car.ipl_label()
            if ipl:                              # the IPL alongside a state career: auction and season, unwatched
                def bg_match(card):
                    job.done += 1
                folder = _safe(f"IPL-{ipl}")
                r2 = car.play_ipl(run=f"career/{params['career']}/{folder}", on_match=bg_match, rain=rain_)
                if r2:
                    r2["title"], r2["mode"] = f"{car.name} - IPL {ipl}", "career"
                    r2["career"] = {"id": params["career"], "name": car.name, "season": f"IPL {ipl}"}
                    _augment(r2)
                    d2 = v.careers / params["career"] / "seasons" / folder
                    if d2.exists():
                        shutil.rmtree(d2)
                    save(r2, d2)
            car.advance()
            save_career(params["career"], car, v)
        job.status = "done"
    except (Stopped, Cancelled):
        job.status = "stopped"
    except Exception as e:  # noqa: BLE001 - shown to the user
        job.status, job.error = "error", f"{e}\n\n{traceback.format_exc()}"
    finally:
        job.finished = time.time()


# ------------------------------------------------------------------------------------------------ routes

@app.get("/")
def index():
    return send_from_directory(UI, "index.html")


@app.get("/ui/<path:name>")
def ui(name):
    return send_from_directory(UI, name)


@app.get("/api/meta")
def api_meta():
    return jsonify({
        "formats": {f: {"competitions": competitions(f), "venues": venues(f)} for f in ("t20", "odi")},
        # a list, not a dict: Flask sorts dict keys, which would put "final" first in the dropdown
        "knockouts": [{"id": k, "label": v} for k, v in KNOCKOUTS.items()],
        "draft_teams": DEFAULT_TEAMS,
        "league_info": league_info(),     # labels and badges of every league (engine/leagues.py)
        "leagues": [{"id": k, "label": lg["label"],
                     "seasons": [{"season": s["season"], "year": s["year"], "max_overseas": s["max_overseas"],
                                  "teams": [{"name": t["name"], "franchise": t.get("franchise", t["name"]),
                                             "n": len(t["players"]), "overseas": len(t["overseas"])}
                                            for t in s["teams"]]} for s in lg["seasons"]]}
                    for k, lg in league_seasons().items()],
        # domestic cups (data/domestic_seasons.json): the Mushtaq Ali Trophy's seasons, groups and format
        "domestic": [{"id": k, "label": c["label"], "short": c.get("short", k.upper()),
                      "seasons": [{"season": s["season"], "year": s["year"], "squads": s["squads"],
                                   "knockout": s["format"]["knockout"],
                                   "groups": [len(g) for g in s["format"]["groups"].values()],
                                   "plate": len(s["format"]["plate"]["teams"]) if s["format"]["plate"] else 0,
                                   "matches": domestic.match_total(s), "real": s["real"],
                                   "teams": [{"name": t["name"], "n": len(t["players"]),
                                              "plate": bool(s["format"]["plate"])
                                              and t["name"] in s["format"]["plate"]["teams"]} for t in s["teams"]]}
                                  for s in c["seasons"]],
                      "career_seasons": start_seasons() if k == "sma" else []}
                     for k, c in domestic.competitions().items()],
        "years": {f: [history.first_year(f), history.last_year(f)] for f in ("t20", "odi")},
        "teams": load_teams(), "has_results": (V().last / "summary.json").exists(), "saved": saved_runs(),
        "careers": careers_list(),
        "job": V().job.to_dict() if V().job else None,
        "public": bool(app.config.get("MULTI")),
    })


@app.get("/api/players")
def api_players():
    fmt = request.args.get("fmt", "t20")
    if fmt not in ("t20", "odi"):
        abort(400)
    return jsonify(players(fmt))


@app.get("/api/nations")
def api_nations():
    """Nations with enough players in a format and year range (for the Classic modes)."""
    fmt = request.args.get("fmt", "t20")
    if fmt not in ("t20", "odi"):
        abort(400)
    lo, hi = history.first_year(fmt), history.last_year(fmt)
    try:
        y1, y2 = int(request.args.get("y1", lo)), int(request.args.get("y2", hi))
    except ValueError:
        return jsonify(error="Years must be numbers."), 400
    return jsonify(first=lo, last=hi,
                   nations=[{"name": n, "matches": m} for n, m in history.nations(fmt, max(y1, lo), min(y2, hi))])


@app.get("/api/teams")
def api_teams():
    return jsonify(load_teams())


@app.post("/api/team")
def api_team_save():
    d = request.get_json(force=True)
    name = (d.get("name") or "").strip()
    ps = d.get("players") or []
    if not name:
        return jsonify(error="Give the team a name."), 400
    if not 11 <= len(ps) <= 15:
        return jsonify(error="A team needs 11 to 15 players."), 400
    if len({p["id"] for p in ps}) != len(ps):
        return jsonify(error="A player is in the team twice."), 400
    teams = [t for t in load_teams() if t["name"] != (d.get("replace") or name)]
    if any(t["name"] == name for t in teams):
        return jsonify(error=f"There is already a team called {name!r}."), 400
    if (cap := _limit("teams")) and len(teams) >= cap:
        return jsonify(error=f"You can keep up to {cap} teams here: delete one first."), 400
    teams.append({"name": name, "players": [{"id": p["id"], "name": p["name"]} for p in ps]})
    save_teams(teams)
    return jsonify(teams=teams)


@app.post("/api/team/delete")
def api_team_delete():
    name = request.get_json(force=True).get("name")
    teams = [t for t in load_teams() if t["name"] != name]
    save_teams(teams)
    return jsonify(teams=teams)


@app.post("/api/run")
def api_run():
    v = V()
    p = request.get_json(force=True)
    with LOCK:
        if v.busy():
            return jsonify(error="A simulation is already running."), 409
        if err := _capacity_error():
            return jsonify(error=err), 503
        if p.get("mode") in ("league", "domestic"):
            p["fmt"] = "t20"
        fmt = p.get("fmt")
        if fmt not in ("t20", "odi"):
            return jsonify(error="Choose T20 or ODI."), 400
        label = lambda e: history.team_name(e["nation"], int(e["y1"]), int(e["y2"])) if isinstance(e, dict) else e
        if p.get("mode") == "series":
            a, b = p.get("team1"), p.get("team2")
            if not a or not b:
                return jsonify(error="Choose two teams."), 400
            err = check_entries([a, b], fmt)
            if err:
                return jsonify(error=err), 400
            a, b = label(a), label(b)
            n = int(p.get("matches") or 1)
            if not 1 <= n <= 7:
                return jsonify(error="A series has 1 to 7 matches."), 400
            title = f"{a} v {b}" + (f" - {n}-match series" if n > 1 else "")
            sides = [a, b]
            total = n
        elif p.get("mode") == "league":
            s = league_season(p.get("league"), p.get("season"))
            if not s:
                return jsonify(error="Unknown league or season."), 400
            p["comp"], p["year"] = p["league"], s["year"]
            total = match_count(len(s["teams"]), 2, None, "ipl")
            title = f"{s['label']} {s['season']} - {len(s['teams'])} teams, double round robin + playoffs"
            cap = p.get("captain") or None
            if cap and cap not in {t["name"] for t in s["teams"]}:
                return jsonify(error="Choose a team from this season to captain."), 400
            if cap:
                title += f" - you captain {cap}"
        elif p.get("mode") == "domestic":
            s = domestic.season(p.get("cup") or "sma", p.get("season"))
            if not s:
                return jsonify(error="Unknown season."), 400
            p["comp"], p["year"] = s["comp"], s["year"]
            total = domestic.match_total(s)
            title = f"{s['label']} {s['season']} - {len(s['teams'])} teams"
            cap = p.get("captain") or None
            if cap and cap not in {t["name"] for t in s["teams"]}:
                return jsonify(error="Choose a team from this season to captain."), 400
            if cap:
                title += f" - you captain {cap}"
        elif p.get("mode") == "draft":
            dr = v.draft
            if not dr or not dr.done:
                return jsonify(error="Finish the draft first."), 400
            if dr.fmt != fmt:
                return jsonify(error=f"The squads were drafted for {dr.fmt.upper()}."), 400
            teams = dr.teams
            groups = int(p.get("groups") or 1)
            ko = p.get("knockout") or "semis"
            if ko not in KNOCKOUTS:
                return jsonify(error="Unknown knockout format."), 400
            need = {"semis": 4, "ipl": 4, "final": 2, "none": 1}[ko]
            if len(teams) < need or (groups > 1 and (ko == "ipl" or len(teams) < 4)):
                return jsonify(error="Not enough teams for these knockouts / groups."), 400
            total = match_count(len(teams), int(p.get("rounds") or 1), groups if groups > 1 else None, ko)
            title = f"Fantasy draft league - {len(teams)} teams, players from {dr.y1}-{dr.y2}"
            sides = list(teams)
        elif p.get("mode") == "auction":
            a = v.auction
            if not a or not a.done:
                return jsonify(error="Finish the auction first."), 400
            if a.comp:
                p["fmt"], p["comp"], p["year"] = "t20", a.comp, a.year
                total = match_count(len(a.teams), 2, None, "ipl")
            else:
                if a.fmt != fmt:
                    return jsonify(error=f"The squads were bought for {a.fmt.upper()}."), 400
                ko = p.get("knockout") or "semis"
                if ko not in KNOCKOUTS:
                    return jsonify(error="Unknown knockout format."), 400
                if len(a.teams) < {"semis": 4, "ipl": 4, "final": 2, "none": 1}[ko]:
                    return jsonify(error="Not enough teams for these knockouts."), 400
                total = match_count(len(a.teams), int(p.get("rounds") or 1), None, ko)
            title = f"Auction league - {a.label}, {len(a.teams)} teams"
            if p.get("captain") and p["captain"] != a.user:
                return jsonify(error="You can captain the team you bought for."), 400
            if p.get("captain"):
                title += f" - you captain {p['captain']}"
        elif p.get("mode") == "career":
            try:
                car = load_career(p.get("career"), v)
            except FileNotFoundError:
                return jsonify(error="Unknown career."), 400
            if car.phase != "season":
                return jsonify(error="Hold the auction before the season."), 400
            p["fmt"], p["comp"], p["year"] = "t20", car.league, car.cond_year()
            total = car.match_total() + car.background_matches()
            title = f"{car.name} - season {car.season_label}" + (" and the IPL" if car.background_matches() else "")
            if p.get("captain") and car.user:
                p["captain"] = car.user
                title += f" - you captain {car.user}"
            else:
                p["captain"] = None
        elif p.get("mode") == "tournament":
            teams = p.get("teams") or []
            if len(teams) < 2:
                return jsonify(error="Pick at least two teams."), 400
            err = check_entries(teams, fmt)
            if err:
                return jsonify(error=err), 400
            groups = int(p.get("groups") or 1)
            ko = p.get("knockout") or "semis"
            if ko not in KNOCKOUTS:
                return jsonify(error="Unknown knockout format."), 400
            need = {"semis": 4, "ipl": 4, "final": 2, "none": 1}[ko]
            if groups > 1 and ko == "ipl":
                return jsonify(error="IPL playoffs need a single league (1 group)."), 400
            if groups > 1 and len(teams) < 2 * max(2, need // groups):
                return jsonify(error=f"Two groups need at least {2 * max(2, need // groups)} teams."), 400
            if len(teams) < need:
                return jsonify(error=f"This knockout format needs at least {need} teams."), 400
            total = match_count(len(teams), int(p.get("rounds") or 1), groups if groups > 1 else None, ko)
            title = f"Tournament - {len(teams)} teams"
            sides = [label(e) for e in teams]
        else:
            return jsonify(error="Unknown mode."), 400
        cap = p.get("captain") if p.get("mode") in ("league", "domestic", "auction", "career") else None
        if p.get("mode") in ("series", "tournament", "draft") and str(p.get("captain_i", "")).strip() != "":
            try:
                cap = sides[int(p["captain_i"])]
            except (ValueError, IndexError):
                return jsonify(error="Choose a team from this run to captain."), 400
            title += f" - you captain {cap}"
        job = v.job = Job(title, total)
        if cap:
            manual = set(p["manual"]) & set(KINDS) if isinstance(p.get("manual"), list) else set(DEFAULT_KINDS)
            job.controller = WaitingController(cap, manual)
        threading.Thread(target=_run, args=(job, p, v), daemon=True).start()
    return jsonify(ok=True)


# ------------------------------------------------------------------------------------------------ draft

def _draft_state() -> dict:
    dr = V().draft
    return dr.state() if dr else {"current": None, "done": False, "teams": []}


@app.post("/api/draft/start")
def api_draft_start():
    v = V()
    d = request.get_json(force=True)
    fmt = d.get("fmt")
    if fmt not in ("t20", "odi"):
        return jsonify(error="Choose T20 or ODI."), 400
    if v.busy():
        return jsonify(error="A simulation is running."), 409
    try:
        y1, y2 = int(d.get("y1")), int(d.get("y2"))
    except (TypeError, ValueError):
        return jsonify(error="Years must be numbers."), 400
    lo, hi = history.first_year(fmt), history.last_year(fmt)
    if y1 > y2 or y1 < lo or y2 > hi:
        return jsonify(error=f"Choose years within {lo}-{hi}, start before end."), 400
    names = [str(x).strip() for x in d.get("teams") or []]
    if any(not n or len(n) > 40 for n in names):
        return jsonify(error="Every team needs a name (up to 40 characters)."), 400
    if not 2 <= len(names) <= 12:
        return jsonify(error="A draft has 2 to 12 teams."), 400
    source = d.get("source") or "full"
    if source == "leagues" and fmt != "t20":
        source = "full"
    try:
        seed = int(d["seed"]) if str(d.get("seed") or "").strip() else None
        ym = d.get("years_mode") if d.get("years_mode") in ("blend", "only") else "blend"
        dr = Draft(fmt, y1, y2, names, user=d.get("user") or None, source=source, seed=seed, years_mode=ym)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    dr.run_cpu()
    v.draft = dr
    pool = [p.row() for p in dr.pool]
    return jsonify(state=_draft_state(), pool=pool)


@app.get("/api/draft")
def api_draft():
    dr = V().draft
    if not dr:
        return jsonify(error="No draft."), 404
    return jsonify(state=_draft_state(), pool=[p.row() for p in dr.pool])


@app.post("/api/draft/pick")
def api_draft_pick():
    dr = V().draft
    if not dr or dr.done:
        return jsonify(error="No draft in progress."), 400
    d = request.get_json(force=True)
    try:
        if d.get("auto") == "rest":
            while not dr.done:
                dr.cpu_pick()
        elif d.get("auto"):
            if dr.current() != dr.user:
                raise ValueError("It is not your pick.")
            dr.cpu_pick()
        else:
            if dr.current() != dr.user:
                raise ValueError("It is not your pick.")
            dr.pick(d.get("id"))
    except ValueError as e:
        return jsonify(error=str(e)), 400
    dr.run_cpu()
    return jsonify(state=_draft_state())


# ------------------------------------------------------------------------------------------------ auction

def _auction_reply(pool: bool = False):
    a = V().auction
    if a.done and a.user is not None and not getattr(a, "_saved", False) and not getattr(a, "career_id", None):     # retain from it next time
        V().auction_last.parent.mkdir(parents=True, exist_ok=True)
        V().auction_last.write_text(json.dumps({"label": a.label, "fmt": a.fmt, "squads": a.squad,
                                            "prices": _board_prices(a.board())}), encoding="utf-8")
        a._saved = True
    out = {"state": {**a.state(), "career": getattr(a, "career_id", None)}, "to_you": a.to_you()}
    if pool:
        out["pool"] = [x.row() for x in a.lots.values()]
    else:
        out["changes"] = {i: {"status": x.status, "buyer": x.buyer, "price": x.price, "set": x.set, "fee": x.fee}
                          for i, x in a.lots.items()}
    return jsonify(out)


def _board_prices(board: dict) -> dict:
    """{team: {player: contract}} from an auction's squads: what each player is paid (the price, or the capped fee)."""
    return {t: {p["id"]: p.get("fee") or p.get("price") for p in ps} for t, ps in board.items()}


def _last_auction() -> dict:
    try:
        return json.loads(V().auction_last.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


@app.get("/api/auction/last")
def api_auction_last():
    d = _last_auction()
    return jsonify(label=d.get("label"), fmt=d.get("fmt"), teams=sorted(d.get("squads") or {}))


@app.post("/api/auction/start")
def api_auction_start():
    """{pool: "season" | "years", league, season | fmt, y1, y2, source, home, years_mode, teams,
    user, retain: "previous" | "last" | "saved:<id>" | "none", kind: "mega" | "mini", seed,
    knowledge: "realistic" | "hindsight" (a season pool: the numbers shown with each player)}
    A mini auction keeps the retention source's squads at their prices (from an auction: what it paid; a real
    season's squads: expected prices, as the engine estimates them) and the teams release players instead."""
    v = V()
    d = request.get_json(force=True)
    if v.busy():
        return jsonify(error="A simulation is running."), 409
    try:
        seed = int(d["seed"]) if str(d.get("seed") or "").strip() else None
        if d.get("pool") == "season":
            if not league_season(d.get("league"), d.get("season")):
                return jsonify(error="Unknown league or season."), 400
            pool = season_pool(d["league"], d["season"], d.get("knowledge") or "realistic")
        else:
            fmt = d.get("fmt")
            if fmt not in ("t20", "odi"):
                return jsonify(error="Choose T20 or ODI."), 400
            y1, y2 = int(d.get("y1")), int(d.get("y2"))
            lo, hi = history.first_year(fmt), history.last_year(fmt)
            if y1 > y2 or y1 < lo or y2 > hi:
                return jsonify(error=f"Choose years within {lo}-{hi}, start before end."), 400
            names = [str(x).strip() for x in d.get("teams") or []]
            if any(not n or len(n) > 40 for n in names) or len(set(names)) != len(names):
                return jsonify(error="Every team needs a different name (up to 40 characters)."), 400
            if not 2 <= len(names) <= 12:
                return jsonify(error="An auction has 2 to 12 teams."), 400
            source = d.get("source") if d.get("source") in ("full", "intl", "leagues") else "full"
            if source == "leagues" and fmt != "t20":
                source = "full"
            ym = d.get("years_mode") if d.get("years_mode") in ("blend", "only") else "blend"
            pool = years_pool(fmt, y1, y2, names, source, d.get("home") or None, ym)
        retain = d.get("retain") or "none"
        mini = d.get("kind") == "mini"
        if mini and retain == "none":
            return jsonify(error="A mini auction needs squads to keep: choose where they come from."), 400
        prev, prices = {}, {}
        if retain == "previous":
            prev = None                        # the pool's own previous season
            if mini:
                prev = pool["prev"]
                if not prev:
                    return jsonify(error="There is no previous season to keep squads from."), 400
        elif retain == "last":
            last = _last_auction()
            prev, prices = last.get("squads") or {}, last.get("prices") or {}
            if not set(prev) & set(pool["teams"]):
                return jsonify(error="Your last auction had none of these teams."), 400
        elif retain.startswith("saved:"):
            sd = v.saved / retain[6:]
            if sd.parent != v.saved or not (sd / "summary.json").exists():
                return jsonify(error="That saved run no longer exists."), 400
            prev = _run_meta(sd)["squads"]
            board = (json.loads((sd / "summary.json").read_text(encoding="utf-8")).get("draft") or {}).get("board")
            if board and _run_meta(sd).get("mode") == "auction":
                prices = _board_prices(board)
            if not set(prev) & set(pool["teams"]):
                return jsonify(error="That saved run has none of these teams."), 400
        if mini:                               # keep at the prices paid (None: the engine estimates a contract)
            pool["kept"] = {t: {pid: (prices.get(t) or {}).get(pid) for pid in ids}
                            for t, ids in prev.items() if t in pool["teams"]}
            prev = {}
        v.auction = Auction(pool, user=d.get("user") or None, prev=prev, seed=seed)
    except (TypeError, ValueError) as e:
        return jsonify(error=str(e) or "Check the settings."), 400
    return _auction_reply(pool=True)


@app.get("/api/auction")
def api_auction():
    if not V().auction:
        return jsonify(error="No auction."), 404
    return _auction_reply(pool=True)


@app.post("/api/auction/act")
def api_auction_act():
    """The user's answer to the open question, or {auto: "set" | "all" | "wish" | "ask"} (the computer, or the
    wishlist, bids for the user; "ask": the user is asked again)."""
    a = V().auction
    if not a or a.done:
        return jsonify(error="No auction in progress."), 400
    d = request.get_json(force=True)
    try:
        if d.get("auto") in ("set", "all", "wish", "ask"):
            a.auto(d["auto"])
        else:
            a.act(d.get("answer") or {})
    except (TypeError, ValueError) as e:
        return jsonify(error=str(e)), 400
    return _auction_reply()


@app.post("/api/auction/wish")
def api_auction_wish():
    """Wishlist: {id, max (lakh or null), ask} for one player, and/or {pause: bool} (stop before each set)."""
    a = V().auction
    if not a or a.done or not a.user:
        return jsonify(error="No auction in progress."), 400
    d = request.get_json(force=True)
    try:
        if d.get("id"):
            top = d.get("max")
            a.set_wish(d["id"], None if top in (None, "") else int(top), bool(d.get("ask")))
        if "pause" in d:
            a.pause_sets = bool(d["pause"])
    except (TypeError, ValueError) as e:
        return jsonify(error=str(e)), 400
    return jsonify(wish=a.wish, pause_sets=a.pause_sets)


@app.get("/api/status")
def api_status():
    job = V().job
    return jsonify(job.to_dict() if job else {"status": "idle"})


@app.post("/api/stop")
def api_stop():
    _cancel(V().job)
    return jsonify(ok=True)


@app.post("/api/decide")
def api_decide():
    """The captain's answer to the open question: {id, choice (None = the computer's), auto: {kind: bool},
    skip: "innings" | "match" | "all"}."""
    p = request.get_json(force=True)
    job = V().job
    c = job.controller if job and job.status == "running" else None
    if not c:
        return jsonify(error="No match is waiting for a decision."), 409
    if not c.answer(int(p.get("id") or 0), p.get("choice"), p.get("auto"), p.get("skip")):
        return jsonify(error="That decision has already been made."), 409
    return jsonify(ok=True)


# ------------------------------------------------------------------------------------------------ two players
# docs/multiplayer_design.md. Any number of rooms (by code): the host creates one (conditions + their team), the
# second device joins with the code and picks its own team, both say ready, and the match runs as the room's job with
# one WaitingController per side. Every call carries the seat's secret token; a seat sees only its own question.
# On your own computer a new room replaces the previous one.

MP_GONE = 60          # seconds without a poll before the other player may hand that side to the computer
MP_CLOCKS = {"off": None, "10": 10, "20": 20}
MP_CAPTAIN_CLOCK = 60  # with a shot clock: toss, XI, bowler, batter, Impact Player decisions
MP_SERIES = (1, 3, 5)  # a single match or best of 3 / 5 (stops once decided)
MP_CPU = (0, 2, 4, 6)  # draft / auction: computer teams that pick or bid too, then play a league with the two players
MP_BID_CLOCK = 15     # auction with a shot clock: seconds per bid (then a pass); other auction questions 60 s
ROOMS: dict[str, dict] = {}   # code -> room


def _token() -> str:
    return secrets.token_urlsafe(12)


def _seat(token: str | None):
    """(room, seat index 0/1, or "spectator") for a token; (None, None) when no room has it."""
    if not token:
        return None, None
    for r in list(ROOMS.values()):
        for i, s in enumerate(r["seats"]):
            if s["token"] == token:
                return r, i
        if token in r["spectators"]:
            return r, "spectator"
    return None, None


def _room_visitors(r: dict) -> list:
    """Everyone in the room (the seats, then the spectators): they all get the results."""
    return list(dict.fromkeys([s["visitor"] for s in r["seats"] if s["visitor"]] + list(r["spectators"].values())))


def _mp_label(e) -> str:
    return history.team_name(e["nation"], int(e["y1"]), int(e["y2"])) if isinstance(e, dict) else e


def _mp_pname(p: dict) -> str | None:
    """A player's own name for the room (shown on the seats), at most 20 characters; None if not given."""
    return " ".join(str(p.get("name") or "").split())[:20] or None


def _mp_kinds(kinds) -> set:
    return set(kinds) & set(KINDS) - {"result"} if isinstance(kinds, list) else set(DEFAULT_KINDS) - {"result"} | {"ball"}


def _mp_job(r: dict) -> bool:
    """Has the room's match started (it is running or just finished)?"""
    return r.get("job") is not None


def _mp_running(r: dict) -> bool:
    return _mp_job(r) and r["job"].status == "running"


def _mp_record_new() -> dict:
    """Head to head in this room, by seat (the players may change teams between rematches)."""
    return {"matches": [0, 0], "series": [0, 0], "played": 0, "titles": [0, 0]}


def _mp_record(job, res: dict) -> None:
    """A finished two-player run: its matches between the two players, its series (best of 3 / 5) and its
    title (a draft league with computer teams) go into the room's head to head."""
    r = job.room
    if not r or r.get("job") is not job or not r.get("names"):
        return
    rec, names = r["record"], r["names"]
    for c in res.get("matches") or []:
        w = c["result"].get("winner")
        if set(c["teams"]) == set(names) and w in names:
            rec["matches"][names.index(w)] += 1
    if res.get("kind") == "series" and (res.get("best_of") or 1) > 1:
        rec["played"] += 1
        if res.get("winner") in names:
            rec["series"][names.index(res["winner"])] += 1
    if res.get("kind") != "series" and res.get("winner") in names:
        rec.setdefault("titles", [0, 0])[names.index(res["winner"])] += 1


def _mp_ko(k: int) -> str:
    """Knockouts for a draft league of k teams (one round robin first): a final for 4, semi-finals for more."""
    return "final" if k <= 4 else "semis"


def _mp_series(job, open_: list) -> dict:
    """The series so far: wins by seat, the match being played; a result on screen already counts.
    A draft league: which match of how many."""
    if getattr(job, "mp_league", False):
        return {"league": True, "of": job.total, "match": min(job.done + 1, job.total), "finished": job.done}
    names = job.room["names"]
    winners = list(job.winners)
    res_q = next((q for q in open_ if q and q.get("kind") == "result"), None)
    if res_q and res_q.get("context", {}).get("match_no") == len(winners) + 1:
        winners.append(res_q.get("winner"))
    return {"of": job.total, "wins": [winners.count(n) for n in names], "match": len(job.winners) + 1,
            "finished": len(winners)}


def _mp_urls(r: dict) -> list[str]:
    """Join links for the other player: this site's address when hosted, the LAN addresses with --lan."""
    if app.config.get("MULTI"):
        return [f"{request.host_url}?join={r['code']}"]
    if not app.config.get("LAN"):
        return []
    port = request.host.rsplit(":", 1)[-1] if ":" in request.host else "80"
    return [f"http://{ip}:{port}/?join={r['code']}" for ip in lan_addresses()]


def _mp_start(r: dict) -> str | None:
    """Both seats ready: check the teams and start the match. Error message or None."""
    st = r["settings"]
    if r.get("auction") is not None:         # squads bought at an auction
        return _mp_auction_play(r)
    d = r.get("draft")                       # drafted squads, or each player's own team
    t1 = t2 = None
    if d is None:
        t1, t2 = (s["team"] for s in r["seats"])
        owners = [s["visitor"] for s in r["seats"]]     # a saved team is from that player's own teams
        err = check_entries([t1, t2], st["fmt"], owners)
        if err:
            return "Both players picked the same team - one of you choose another." if "picked twice" in err else err
    if err := _capacity_error():
        return err
    names = [s["dname"] for s in r["seats"]] if d else [_mp_label(t1), _mp_label(t2)]
    league = bool(d) and len(d.teams) > 2
    n = 1 if league else st.get("series") or 1
    ctl = _mp_controllers(r, names, league, n)
    if league:
        ko = _mp_ko(len(d.teams))
        job = Job(f"Draft league - {len(d.teams)} teams, players from {d.y1}-{d.y2} - two players",
                  match_count(len(d.teams), 1, None, ko))
    else:
        job = Job(f"{names[0]} v {names[1]} - two players" + (", drafted squads" if d else "")
                  + (f", best of {n}" if n > 1 else ""), n)
    job.controllers = ctl
    job.mp_league = league
    job.room = r
    r["job"], r["names"] = job, names
    for s in r["seats"]:
        s["ready"] = False
    params = {"mode": "mp", **{k: st[k] for k in ("fmt", "comp", "year", "venues", "seed", "rain", "series")}}
    if d:
        params.update(specs=d.team_specs(), knockout=_mp_ko(len(d.teams)),
                      draft_info={"teams": d.teams, "user": None, "board": d.state()["board"],
                                  "years": [d.y1, d.y2], "players": names})
    else:
        params["specs"] = [team_spec(t, st["fmt"], v=s["visitor"]) for t, s in zip((t1, t2), r["seats"])]
    threading.Thread(target=_run, args=(job, params, r["seats"][0]["visitor"]), daemon=True).start()
    return None


def _mp_controllers(r: dict, names: list, league: bool, n: int) -> dict:
    """Each player's controller: their decisions, a result pause after each of their matches in a series or a
    league, the room's clock."""
    clock = MP_CLOCKS.get(r["settings"].get("clock") or "off")
    ctl = {}
    for name, seat in zip(names, r["seats"]):
        manual = set(seat["manual"]) | ({"result"} if n > 1 or league else set())
        c = WaitingController(name, manual,
                              clock={k: (clock if k == "ball" else MP_CAPTAIN_CLOCK) for k in KINDS} if clock else None)
        c.home_manual = set(manual)
        ctl[name] = c
    return ctl


def _mp_auction_play(r: dict) -> str | None:
    """Both ready after the auction: the bought squads play a league with the computer teams, or a series between
    the two players (the room's setting; with no computer teams it is a series)."""
    st, a = r["settings"], r["auction"]
    if err := _capacity_error():
        return err
    names = list(a.users)
    league = st["after"] == "league" and len(a.teams) > 2
    n = 1 if league else st.get("series") or 1
    fmt, comp, year = (a.fmt, a.comp, a.year) if a.comp else (st["fmt"], st["comp"], st["year"])
    specs = {sp["name"]: sp for sp in a.team_specs()}
    params = {"mode": "mp", "fmt": fmt, "comp": comp, "year": year, "seed": st["seed"], "rain": st["rain"],
              "venues": [] if a.comp else st["venues"], "series": n,
              "draft_info": {"teams": a.teams, "user": None, "board": a.board(), "auction": True, "purse": a.purse,
                             "players": names, **({"years": list(a.years)} if a.years else {})}}
    if league:
        real = bool(a.comp)                 # a real season: its double round robin, home grounds and playoffs
        ko = "ipl" if real and len(a.teams) >= 4 else _mp_ko(len(a.teams))
        rounds = 2 if real else 1
        params.update(specs=[specs[t] for t in a.teams], knockout=ko, rounds=rounds,
                      homes={t: h for t, h in a.homes.items() if h} if real else None)
        title = f"Auction league - {a.label}, {len(a.teams)} teams - two players"
        total = match_count(len(a.teams), rounds, None, ko)
    else:
        params["specs"] = [specs[t] for t in names]
        title = f"{names[0]} v {names[1]} - two players, auction squads" + (f", best of {n}" if n > 1 else "")
        total = n
    job = Job(title, total)
    job.controllers = _mp_controllers(r, names, league, n)
    job.mp_league = league
    job.room = r
    r["job"], r["names"] = job, names
    for s_ in r["seats"]:
        s_["ready"] = False
    threading.Thread(target=_run, args=(job, params, r["seats"][0]["visitor"]), daemon=True).start()
    return None


def _mp_settings(p: dict) -> dict | str:
    fmt = p.get("fmt")
    if fmt not in ("t20", "odi"):
        return "Choose T20 or ODI."
    try:
        year = int(p.get("year"))
    except (TypeError, ValueError):
        return "Choose a year."
    teams = p.get("teams") if p.get("teams") in ("draft", "auction") else "pick"
    a_pool = "years" if p.get("a_pool") == "years" else "season"     # an auction: a real season unless asked
    league, season = p.get("league") or "ipl", p.get("season") or None
    if teams == "auction" and a_pool == "season":
        s_ = league_season(league, season)
        if not s_:
            return "Choose a league season for the auction."
        season = s_["season"]
    lo, hi = history.first_year(fmt), history.last_year(fmt)
    try:
        y1, y2 = int(p.get("y1") or max(lo, hi - 10)), int(p.get("y2") or hi)
    except (TypeError, ValueError):
        return "Player pool years must be numbers."
    if (teams == "draft" or teams == "auction" and a_pool == "years") and (y1 > y2 or y1 < lo or y2 > hi):
        return f"Choose player pool years within {lo}-{hi}, the start before the end."
    source = p.get("source") if p.get("source") in ("full", "leagues", "intl") else "full"
    if source == "leagues" and fmt != "t20":
        source = "full"
    return {"fmt": fmt, "comp": p.get("comp"), "year": year, "venues": list(p.get("venues") or []),
            "seed": p.get("seed") or "", "rain": bool(p.get("rain")),
            "clock": p.get("clock") if p.get("clock") in MP_CLOCKS else "off",
            "series": int(p.get("series")) if str(p.get("series")) in map(str, MP_SERIES) else 1,
            "teams": teams, "y1": y1, "y2": y2, "source": source,
            "years_mode": "only" if p.get("years_mode") == "only" else "blend",
            "cpu": int(p.get("cpu")) if str(p.get("cpu")) in map(str, MP_CPU) else 0,
            "a_pool": a_pool, "league": league, "season": season, "retain": p.get("retain") is not False,
            "after": "series" if p.get("after") == "series" else "league"}


def _mp_draft_start(r: dict) -> str | None:
    """Both seats ready in a draft room: build the pool and start the snake draft. Error message or None."""
    st = r["settings"]
    n1, n2 = (s["dname"] for s in r["seats"])
    if n1.lower() == n2.lower():
        return "You both chose the same team name - one of you change it."
    cpu = [t for t in DEFAULT_TEAMS if t.lower() not in (n1.lower(), n2.lower())][:st["cpu"]]
    seed = int(st["seed"]) if str(st.get("seed") or "").strip().isdigit() else None
    try:
        d = Draft(st["fmt"], st["y1"], st["y2"], [n1, n2] + cpu, source=st["source"], seed=seed,
                  years_mode=st["years_mode"], users=[n1, n2])
    except ValueError as e:
        return str(e)
    r["draft"], r["draft_t"] = d, time.time()
    for s in r["seats"]:
        s["ready"], s["auto"] = False, False
    _mp_draft_advance(r)
    return None


def _mp_draft_advance(r: dict) -> None:
    """Computer teams (and a player who chose "auto-draft the rest") pick until it is a person's turn."""
    d, before = r["draft"], len(r["draft"].log)
    auto = {s["dname"] for s in r["seats"] if s.get("auto")}
    while not d.done and (d.current() not in d.users or d.current() in auto):
        d.cpu_pick()
    if len(d.log) != before:
        r["draft_t"] = time.time()


def _mp_draft_pick(r: dict, pid: str | None) -> None:
    """The person whose turn it is picks pid (None: the computer's pick for them), then the computer teams."""
    d = r["draft"]
    if pid is None:
        d.cpu_pick()
    else:
        d.pick(pid)
    r["draft_t"] = time.time()
    _mp_draft_advance(r)


def _mp_draft_state(r: dict, i) -> dict:
    """The draft as one seat sees it (suggestions only on your own turn)."""
    d = r["draft"]
    clock = MP_CLOCKS.get(r["settings"].get("clock") or "off")
    with LOCK:
        if clock and not d.done and d.current() in d.users and time.time() - r["draft_t"] > MP_CAPTAIN_CLOCK:
            _mp_draft_pick(r, None)          # out of time: the computer picks for them
        ds = d.state()
        me = r["seats"][i]["dname"] if i != "spectator" else None
        ds["user"] = me
        ds["suggestions"] = [p.id for p in d.suggestions(me)] if me and ds["current"] == me else []
    ds["players"] = [s["dname"] for s in r["seats"]]
    ds["auto"] = [bool(s.get("auto")) for s in r["seats"]]
    ds["ready"] = [bool(s["ready"]) for s in r["seats"]]
    ds["seconds"] = (max(0, round(MP_CAPTAIN_CLOCK - (time.time() - r["draft_t"])))
                     if clock and not d.done and ds["current"] in d.users else None)
    return ds


def _mp_auction_start(r: dict) -> str | None:
    """Both seats ready in an auction room: build the pool and open the auction. Error message or None."""
    st = r["settings"]
    if st["a_pool"] == "season":
        names = [s["team"] for s in r["seats"]]
        if names[0] == names[1]:
            return "You both chose the same franchise - one of you choose another."
    else:
        names = [s["dname"] for s in r["seats"]]
        if names[0].lower() == names[1].lower():
            return "You both chose the same team name - one of you change it."
    seed = int(st["seed"]) if str(st.get("seed") or "").strip().isdigit() else None
    try:
        if st["a_pool"] == "season":
            pool = season_pool(st["league"], st["season"])
            if any(n not in pool["teams"] for n in names):
                return "Choose franchises from this season."
            prev = None if st["retain"] else {}           # None: the season before's squads (retentions, RTM)
        else:
            cpu = [t for t in DEFAULT_TEAMS if t.lower() not in (names[0].lower(), names[1].lower())][:st["cpu"]]
            pool = years_pool(st["fmt"], st["y1"], st["y2"], names + cpu, st["source"], None, st["years_mode"])
            prev = {}
        a = Auction(pool, users=names, prev=prev, seed=seed)
    except (KeyError, ValueError) as e:
        return str(e) or "Check the auction settings."
    r["auction"], r["auction_v"], r["auction_q"] = a, 0, {}
    r["auction_id"] = r.get("auction_id", 0) + 1
    for s in r["seats"]:
        s["ready"], s["auto"] = False, False
    _mp_auction_changed(r)
    return None


def _mp_auction_changed(r: dict) -> None:
    """After every change: a new version for the pollers, and when each open question was first asked (clock)."""
    r["auction_v"] += 1
    now, old, new = time.time(), r["auction_q"], {}
    for u, q in r["auction"].questions.items():
        o = old.get(u)
        new[u] = o if o and o[0] == q["seq"] else (q["seq"], now)
    r["auction_q"] = new


def _mp_auction_default(a: Auction, u: str) -> None:
    """Answer user u's open question as the computer would (out of time, or handed over)."""
    q = a.questions.get(u)
    if not q:
        return
    k = q["kind"]
    a.act({"ids": q["suggested"]} if k in ("retain", "release", "nominate") else {"go": True} if k == "set"
          else {"bid": False} if k == "bid" else {"auto": True}, user=u)


def _mp_auction_clock(r: dict) -> None:
    """With a shot clock: a bid not made in MP_BID_CLOCK seconds is a pass, any other question not answered in
    MP_CAPTAIN_CLOCK seconds gets the computer's answer."""
    if not MP_CLOCKS.get(r["settings"].get("clock") or "off"):
        return
    a, now, moved = r["auction"], time.time(), False
    for u, (seq, t0) in list(r["auction_q"].items()):
        q = a.questions.get(u)
        if q and q["seq"] == seq and now - t0 > (MP_BID_CLOCK if q["kind"] == "bid" else MP_CAPTAIN_CLOCK):
            _mp_auction_default(a, u)
            moved = True
    if moved:
        _mp_auction_changed(r)


def _mp_auction_seconds(r: dict, u: str) -> int | None:
    q = r["auction"].questions.get(u)
    if not q or not MP_CLOCKS.get(r["settings"].get("clock") or "off") or u not in r["auction_q"]:
        return None
    lim = MP_BID_CLOCK if q["kind"] == "bid" else MP_CAPTAIN_CLOCK
    return max(0, round(lim - (time.time() - r["auction_q"][u][1])))


def _mp_auction_state(r: dict, i, v: int | None) -> dict:
    """The auction as one seat sees it (only their question, wishlist and advice), or {same: true} when nothing
    has changed since version v."""
    with LOCK:
        _mp_auction_clock(r)
        a = r["auction"]
        me = a.users[i] if i != "spectator" else None
        secs = {u: _mp_auction_seconds(r, u) for u in a.users}
        out = {"v": r["auction_v"], "seconds": secs, "id": r["auction_id"], "players": list(a.users),
               "ready": [bool(s["ready"]) for s in r["seats"]], "auto": [a.autos.get(u) == "all" for u in a.users]}
        if v is not None and v == r["auction_v"]:
            return {**out, "same": True}
        st = a.state(me)
        if me is None:                           # a spectator sees no one's wishlist or advice
            st["user"] = None
        out.update(state=st, to_you=a.to_you(me) if me else {},
                   changes={pid: {"status": x.status, "buyer": x.buyer, "price": x.price, "set": x.set, "fee": x.fee}
                            for pid, x in a.lots.items()})
    return out


@app.post("/api/mp/create")
def api_mp_create():
    """The host opens a room: conditions, their team and the decisions they make. -> {code, token}"""
    v = V()
    p = request.get_json(force=True)
    with LOCK:
        st = _mp_settings(p)
        if isinstance(st, str):
            return jsonify(error=st), 400
        for c, old in list(ROOMS.items()):    # this host's earlier rooms that aren't playing
            if old["seats"][0]["visitor"] is v and not _mp_running(old):
                del ROOMS[c]
        tok = _token()
        code = None
        while code is None or code in ROOMS:
            code = "".join(random.choice("ABCDEFGHJKLMNPQRSTUVWXYZ") for _ in range(4))
        ROOMS[code] = {"code": code, "settings": st, "job": None, "names": None, "spectators": {},
                       "record": _mp_record_new(), "draft": None, "draft_t": 0.0, "auction": None,
                       "seats": [{"token": tok, "team": p.get("team") or None, "ready": False, "seen": time.time(),
                                  "manual": _mp_kinds(p.get("manual")), "dname": None, "auto": False, "visitor": v,
                                  "pname": _mp_pname(p)},
                                 {"token": None, "team": None, "ready": False, "seen": 0.0, "manual": _mp_kinds(None),
                                  "dname": None, "auto": False, "visitor": None, "pname": None}]}
    return jsonify(code=code, token=tok)


@app.post("/api/mp/join")
def api_mp_join():
    """Join with the room code (and the player's name, optional): the free seat, or a spectator's place if both
    are taken. -> {token, seat}"""
    p = request.get_json(force=True)
    with LOCK:
        r = ROOMS.get(str(p.get("code") or "").strip().upper())
        if not r:
            return jsonify(error="No room with that code. Check it on the host's screen."), 404
        tok = _token()
        guest = r["seats"][1]
        if guest["token"] is None:
            guest.update(token=tok, seen=time.time(), visitor=V(), pname=_mp_pname(p))
            r["record"] = _mp_record_new()        # a new opponent: a new head to head
            return jsonify(token=tok, seat=1)
        r["spectators"][tok] = V()
        return jsonify(token=tok, seat="spectator")


@app.post("/api/mp/lobby")
def api_mp_lobby():
    """A seat's lobby changes: {token, team?, manual?, ready?, settings? (host), rematch?, leave?}. Starts the
    match when both seats have a team and are ready."""
    p = request.get_json(force=True)
    with LOCK:
        r, i = _seat(p.get("token"))
        if r is None or i is None:
            return jsonify(error="You are not in this room any more."), 404
        if i == "spectator":
            return jsonify(error="Spectators can only watch."), 403
        seat = r["seats"][i]
        if p.get("leave"):
            if i == 0:
                ROOMS.pop(r["code"], None)
                _cancel(r.get("job"))
            elif not _mp_running(r):
                seat.update(token=None, team=None, ready=False, seen=0.0, dname=None, auto=False, visitor=None, pname=None)
                r["draft"] = r["auction"] = None  # their squad goes with them
                r["seats"][0]["ready"] = False
            return jsonify(ok=True)
        if p.get("rematch"):
            if _mp_running(r):
                return jsonify(error="The match is still being played."), 409
            r["job"] = None
            return jsonify(ok=True)
        if _mp_running(r):
            return jsonify(error="The match has started."), 409
        if r.get("draft") is not None:
            return jsonify(error="The draft has started. The host can start a new draft from the draft room."), 409
        if r.get("auction") is not None:
            return jsonify(error="The auction has started. The host can start a new one from the auction room."), 409
        if "settings" in p and i == 0:
            st = _mp_settings(p["settings"])
            if isinstance(st, str):
                return jsonify(error=st), 400
            r["settings"] = st
            for s in r["seats"]:
                s["ready"] = False         # the conditions changed: both confirm again
        if "team" in p:
            seat["team"] = p["team"] or None
            seat["ready"] = False
        if "name" in p:
            seat["dname"] = " ".join(str(p["name"] or "").split())[:30] or None
            seat["ready"] = False
        if "manual" in p:
            seat["manual"] = _mp_kinds(p["manual"])
        mode = r["settings"].get("teams")
        named = mode == "draft" or mode == "auction" and r["settings"]["a_pool"] == "years"
        mine = (lambda s: s["dname"]) if named else (lambda s: s["team"])
        if "ready" in p:
            if p["ready"] and not mine(seat):
                return jsonify(error="Name your team first." if named else
                               "Choose your franchise first." if mode == "auction" else "Pick your team first."), 400
            seat["ready"] = bool(p["ready"])
        if all(s["ready"] and mine(s) for s in r["seats"]):
            err = _mp_draft_start(r) if mode == "draft" else _mp_auction_start(r) if mode == "auction" \
                else _mp_start(r)
            if err:
                for s in r["seats"]:
                    s["ready"] = False
                return jsonify(error=err), 400
    return jsonify(ok=True)


@app.get("/api/mp/state")
def api_mp_state():
    """The room as this seat sees it: the lobby, or the match with only this seat's open question."""
    r, i = _seat(request.args.get("token"))
    if r is None or i is None:
        return jsonify(phase="none")
    now = time.time()
    if i != "spectator":
        r["seats"][i]["seen"] = now
    draft = r["settings"].get("teams") == "draft" or r["settings"].get("teams") == "auction" \
        and r["settings"].get("a_pool") == "years"
    seats = [{"team": s["team"], "label": s["dname"] if draft else _mp_label(s["team"]) if s["team"] else None,
              "name": s["dname"], "player": s.get("pname"), "ready": s["ready"], "joined": s["token"] is not None, "here": now - s["seen"] < 10,
              "manual": sorted(s["manual"])} for s in r["seats"]]
    out = {"code": r["code"], "you": i, "seats": seats, "settings": r["settings"], "urls": _mp_urls(r),
           "lan": bool(app.config.get("LAN") or app.config.get("MULTI")), "public": bool(app.config.get("MULTI")),
           "now": now, "record": r["record"]}
    if not _mp_job(r):
        if r.get("auction") is not None:
            try:
                v = int(request.args["v"]) if request.args.get("v") else None
            except ValueError:
                v = None
            out["auction"] = _mp_auction_state(r, i, v)
            if i != "spectator":
                gone = now - r["seats"][1 - i]["seen"]
                out["opp_gone"] = round(gone)
                out["can_take"] = gone > MP_GONE and r["auction"].autos.get(r["auction"].users[1 - i]) != "all" \
                    and not r["auction"].done
            return jsonify(phase="auction", **out)
        if r.get("draft") is None:
            return jsonify(phase="lobby", **out)
        out["draft"] = _mp_draft_state(r, i)
        if i != "spectator":
            gone = now - r["seats"][1 - i]["seen"]
            out["opp_gone"] = round(gone)
            out["can_take"] = gone > MP_GONE and not r["seats"][1 - i].get("auto") and not r["draft"].done
        return jsonify(phase="draft", **out)
    job = r["job"]
    out["job"] = job.to_dict()
    if job.status != "running":
        return jsonify(phase="over", names=r["names"], **out)
    ctl = [job.controllers[n] for n in r["names"]]
    open_ = [c.pending for c in ctl]            # read once: the match thread may close a question meanwhile
    states = [q["state"] for q in open_ if q and q.get("state") and "runs" in q["state"]]
    out["latest"] = states[-1] if states else None   # scoreboard while you wait
    out["names"] = r["names"]
    out["series"] = _mp_series(job, open_)
    if i != "spectator":
        me, opp = ctl[i], ctl[1 - i]
        out["me"] = {"team": me.team, "manual": sorted(me.manual_kinds), "home": sorted(me.home_manual),
                     "pending": open_[i], "skip": (me.skip or {}).get("scope")}
        gone = now - r["seats"][1 - i]["seen"]
        out["opp"] = {"team": opp.team, "choosing": (open_[1 - i] or {}).get("kind"), "gone": round(gone),
                      "can_take": gone > MP_GONE and bool(opp.manual_kinds),
                      "computer": not opp.manual_kinds}
    return jsonify(phase="playing", **out)


@app.get("/api/mp/draft/pool")
def api_mp_draft_pool():
    """The draft's player pool (sent once; the state carries who is taken)."""
    r, i = _seat(request.args.get("token"))
    if r is None or i is None or r.get("draft") is None:
        return jsonify(error="No draft in this room."), 404
    return jsonify(pool=[p.row() for p in r["draft"].pool])


@app.post("/api/mp/draft")
def api_mp_draft():
    """A seat in the draft: {token, id} picks a player on your turn; auto: "one" (the computer's pick for you),
    "rest" (the computer drafts the rest of your squad), "stop" (back to picking yourself); take: auto-draft for
    a player who has been away MP_GONE seconds; ready: play with the drafted squads; redo (host): a new draft."""
    p = request.get_json(force=True)
    with LOCK:
        r, i = _seat(p.get("token"))
        if r is None or i is None:
            return jsonify(error="You are not in this room any more."), 404
        if i == "spectator":
            return jsonify(error="Spectators can only watch."), 403
        d = r.get("draft")
        if d is None:
            return jsonify(error="No draft in this room."), 409
        if _mp_running(r):
            return jsonify(error="The matches are being played."), 409
        seat = r["seats"][i]
        if p.get("redo"):
            if i != 0:
                return jsonify(error="Only the host can start a new draft."), 403
            r["draft"] = None
            for s in r["seats"]:
                s["ready"] = s["auto"] = False
            return jsonify(ok=True)
        if "ready" in p:
            if not d.done:
                return jsonify(error="Finish the draft first."), 400
            seat["ready"] = bool(p["ready"])
            if all(s["ready"] for s in r["seats"]):
                err = _mp_start(r)
                if err:
                    for s in r["seats"]:
                        s["ready"] = False
                    return jsonify(error=err), 400
            return jsonify(ok=True)
        try:
            if p.get("take"):
                if time.time() - r["seats"][1 - i]["seen"] <= MP_GONE:
                    return jsonify(error="The other player is still here."), 409
                r["seats"][1 - i]["auto"] = True
            elif p.get("auto") in ("rest", "stop"):
                seat["auto"] = p["auto"] == "rest"
            else:
                if d.done or d.current() != seat["dname"]:
                    return jsonify(error="It is not your pick."), 400
                _mp_draft_pick(r, None if p.get("auto") else p.get("id"))
        except ValueError as e:
            return jsonify(error=str(e)), 400
        _mp_draft_advance(r)
    return jsonify(ok=True)


@app.get("/api/mp/auction/pool")
def api_mp_auction_pool():
    """The auction's players (sent once; the state carries what has changed)."""
    r, i = _seat(request.args.get("token"))
    if r is None or i is None or r.get("auction") is None:
        return jsonify(error="No auction in this room."), 404
    with LOCK:
        return jsonify(pool=[x.row() for x in r["auction"].lots.values()])


@app.post("/api/mp/auction")
def api_mp_auction():
    """A seat in the auction: {token, answer} (with the question's seq: a bid pressed after the other player's is
    refused), {auto: "set" | "all" | "wish" | "ask"}, {wish: {id, max, ask}}, {pause: bool}; take: hand a player
    who has been away MP_GONE seconds to the computer; ready: play with the bought squads; redo (host): a new
    auction."""
    p = request.get_json(force=True)
    with LOCK:
        r, i = _seat(p.get("token"))
        if r is None or i is None:
            return jsonify(error="You are not in this room any more."), 404
        if i == "spectator":
            return jsonify(error="Spectators can only watch."), 403
        a = r.get("auction")
        if a is None:
            return jsonify(error="No auction in this room."), 409
        if _mp_running(r):
            return jsonify(error="The matches are being played."), 409
        seat, me = r["seats"][i], a.users[i]
        if p.get("redo"):
            if i != 0:
                return jsonify(error="Only the host can start a new auction."), 403
            r["auction"] = None
            for s in r["seats"]:
                s["ready"] = s["auto"] = False
            return jsonify(ok=True)
        if "ready" in p:
            if not a.done:
                return jsonify(error="Finish the auction first."), 400
            seat["ready"] = bool(p["ready"])
            if all(s["ready"] for s in r["seats"]):
                err = _mp_start(r)
                if err:
                    for s in r["seats"]:
                        s["ready"] = False
                    return jsonify(error=err), 400
            return jsonify(ok=True)
        if a.done:
            return jsonify(error="The auction is over."), 400
        try:
            if p.get("take"):
                if time.time() - r["seats"][1 - i]["seen"] <= MP_GONE:
                    return jsonify(error="The other player is still here."), 409
                other = a.users[1 - i]
                a.auto("all", user=other)
                _mp_auction_default(a, other)
            elif p.get("auto") in ("set", "all", "wish", "ask"):
                a.auto(p["auto"], user=me)
            elif isinstance(p.get("wish"), dict):
                w = p["wish"]
                top = w.get("max")
                a.set_wish(w.get("id"), None if top in (None, "") else int(top), bool(w.get("ask")), user=me)
            elif "pause" in p:
                a.pauses[me] = bool(p["pause"])
            else:
                a.act(p.get("answer") or {}, user=me)
        except (TypeError, ValueError) as e:
            _mp_auction_changed(r)
            return jsonify(error=str(e)), 400
        _mp_auction_changed(r)
        return jsonify(ok=True, v=r["auction_v"], wish=a.wishes[me], pause_sets=a.pauses[me])


@app.post("/api/mp/decide")
def api_mp_decide():
    """This seat's answer: {token, id, choice, auto, skip} (as /api/decide)."""
    p = request.get_json(force=True)
    r, i = _seat(p.get("token"))
    if r is None or i in (None, "spectator") or not _mp_running(r):
        return jsonify(error="No match is waiting for your decision."), 409
    c = r["job"].controllers[r["names"][i]]
    if not c.answer(int(p.get("id") or 0), p.get("choice"), p.get("auto"), p.get("skip")):
        return jsonify(error="That decision has already been made."), 409
    return jsonify(ok=True)


@app.post("/api/mp/control")
def api_mp_control():
    """{token, who: "me"} takes your decisions back (after a skip or a hand-over to the computer);
    {token, who: "opponent"} hands a player who has been away for MP_GONE seconds to the computer."""
    p = request.get_json(force=True)
    r, i = _seat(p.get("token"))
    if r is None or i in (None, "spectator") or not _mp_running(r):
        return jsonify(error="No match in progress."), 409
    if p.get("who") == "opponent":
        if time.time() - r["seats"][1 - i]["seen"] <= MP_GONE:
            return jsonify(error="The other player is still here."), 409
        c = r["job"].controllers[r["names"][1 - i]]
        c.manual_kinds = set()
        if c.pending:
            c.answer(c.pending["id"], None)
    else:
        c = r["job"].controllers[r["names"][i]]
        c.skip = None
        c.manual_kinds = set(c.home_manual)
    return jsonify(ok=True)


# ------------------------------------------------------------------------------------------------ careers

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


def _career_reply(cid: str, c: Career | None = None):
    c = c or load_career(cid)
    return jsonify(id=cid, state=c.state(), careers=careers_list())


def _busy() -> bool:
    return V().busy()


@app.get("/api/careers")
def api_careers():
    return jsonify(careers_list())


@app.post("/api/career/new")
def api_career_new():
    d = request.get_json(force=True)
    if _busy():
        return jsonify(error="A simulation is running."), 409
    try:
        seed = int(d["seed"]) if str(d.get("seed") or "").strip() else None
        name = " ".join(str(d.get("name") or "").split())[:80] or None
        know = d.get("knowledge") or "realistic"  # what the person sees of the players (engine/career.py)
        if d.get("league") == "sma":             # a state career (engine/state_career.py): Elite and Plate, no auction
            c = StateCareer(d.get("season") or "", user=d.get("user") or None, seed=seed, name=name, knowledge=know,
                            ipl=bool(d.get("ipl")))
        else:
            c = Career(d.get("league") or "", d.get("season") or "", user=d.get("user") or None,
                       mega_every=int(d.get("mega_every") or 3), seed=seed, name=name, knowledge=know)
    except (ValueError, KeyError, StopIteration) as e:
        return jsonify(error=str(e) or "Could not start the career."), 400
    if (cap := _limit("careers")) and len(careers_list()) >= cap:
        return jsonify(error=f"You can keep up to {cap} careers here: delete one first."), 400
    cid = _safe(f"{c.league}-{c.start_season}-{time.strftime('%Y%m%d-%H%M%S')}")
    save_career(cid, c)
    return _career_reply(cid, c)


@app.get("/api/career")
def api_career():
    try:
        return _career_reply(request.args.get("id"))
    except FileNotFoundError:
        return jsonify(error="Unknown career."), 404


@app.post("/api/career/rename")
def api_career_rename():
    d = request.get_json(force=True)
    c = load_career(d.get("id"))
    c.name = " ".join(str(d.get("name") or "").split())[:80] or c.name
    save_career(d["id"], c)
    return _career_reply(d["id"], c)


@app.post("/api/career/delete")
def api_career_delete():
    p = _career_path(request.get_json(force=True).get("id"))
    if p.exists():
        shutil.rmtree(p.parent)
    return jsonify(careers=careers_list())


@app.post("/api/career/auction")
def api_career_auction():
    """Open the career's auction in the auction room (auto=true: the computer decides everything)."""
    v = V()
    d = request.get_json(force=True)
    if _busy():
        return jsonify(error="A simulation is running."), 409
    c = load_career(d.get("id"))
    if c.phase != "auction":
        return jsonify(error="No auction is due."), 400
    if d.get("auto") or not c.user:
        c.auto_auction()
        save_career(d["id"], c)
        return _career_reply(d["id"], c)
    v.auction = c.auction()
    v.auction.career_id = d["id"]
    return _auction_reply(pool=True)


@app.post("/api/career/auction_done")
def api_career_auction_done():
    d = request.get_json(force=True)
    a = V().auction
    if not a or getattr(a, "career_id", None) != d.get("id") or not a.done:
        return jsonify(error="Finish the auction first."), 400
    c = load_career(d["id"])
    if c.phase != "auction":
        return jsonify(error="This auction is already saved."), 400
    c.apply_auction(a)
    save_career(d["id"], c)
    return _career_reply(d["id"], c)


# ------------------------------------------------------------------------------------------------ saved runs

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


@app.get("/api/saved")
def api_saved():
    return jsonify(saved_runs())


@app.post("/api/saved")
def api_save():
    """Save the last run under a name (a copy of results/last; the next run no longer overwrites it)."""
    v = V()
    if not (v.last / "summary.json").exists():
        return jsonify(error="No results to save."), 400
    name = " ".join(str(request.get_json(force=True).get("name") or "").split())
    name = "".join(ch for ch in name if ch.isalnum() or ch in " -_.,()'&+")[:80].strip(" .")
    if not name:
        return jsonify(error="Give the run a name."), 400
    d = v.saved / name
    if d.exists():
        return jsonify(error=f"There is already a saved run called {name!r}."), 400
    if (cap := _limit("saved")) and len(saved_runs()) >= cap:
        return jsonify(error=f"You can keep up to {cap} saved runs here: delete one first."), 400
    v.saved.mkdir(parents=True, exist_ok=True)
    shutil.copytree(v.last, d)
    m = _run_meta(d)
    m["name"] = name
    (d / "meta.json").write_text(json.dumps(m), encoding="utf-8")
    return jsonify(saved=saved_runs())


@app.post("/api/saved/rename")
def api_saved_rename():
    d = request.get_json(force=True)
    src = _run_dir(d.get("id") or "")
    m = _run_meta(src)
    m["name"] = " ".join(str(d.get("name") or "").split())[:80] or m["name"]
    (src / "meta.json").write_text(json.dumps(m), encoding="utf-8")
    return jsonify(saved=saved_runs())


@app.post("/api/saved/delete")
def api_saved_delete():
    shutil.rmtree(_run_dir(request.get_json(force=True).get("id") or ""))
    return jsonify(saved=saved_runs())


@app.get("/api/results")
def api_results():
    p = _run_dir(request.args.get("run")) / "summary.json"
    if not p.exists():
        return jsonify(error="No results yet - run a simulation first."), 404
    return app.response_class(p.read_text(encoding="utf-8"), mimetype="application/json")


@app.get("/api/match/<int:n>")
def api_match(n: int):
    p = _run_dir(request.args.get("run")) / "matches" / f"{n:03d}.json"
    if not p.exists():
        abort(404)
    card = json.loads(p.read_text(encoding="utf-8"))
    return jsonify(card=card, text=full_text(card), report=match_report(card))


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


def serve_public(host: str, port: int, password: str | None, max_jobs: int) -> None:
    """--public: a hosted site. Every browser is its own visitor; one process (the runs live in memory) with a
    thread per request, behind a proxy that terminates HTTPS (Cloudflare Tunnel, Fly.io, Render...)."""
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.config.update(MULTI=True, PASSWORD=password or None, MAX_JOBS=max_jobs,
                      LIMITS={"teams": 100, "saved": 30, "careers": 10}, MAX_CONTENT_LENGTH=2 << 20)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)   # https links and secure cookies
    threading.Thread(target=_reaper, daemon=True).start()
    print(f"Limited-overs simulator, public mode, on http://{host}:{port}  (Ctrl+C to stop)")
    print(f"  every visitor gets their own runs (in {VISITORS_DIR}); at most {max_jobs} simulations at once; "
          + ("password required" if password else "NO password: set SITE_PASSWORD to require one"), flush=True)
    try:
        from waitress import serve
    except ImportError:
        print("  (waitress is not installed: using Flask's own server. pip install waitress)")
        app.run(host=host, port=port, threaded=True)
        return
    # waitress would drop the proxy's X-Forwarded-* headers; ProxyFix above reads them (one proxy in front)
    serve(app, host=host, port=port, threads=32, ident=None, clear_untrusted_proxy_headers=False)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT") or 5070))  # 5060/5061: blocked (SIP)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--lan", action="store_true",
                    help="also accept connections from other devices on the local network (no login: "
                         "anyone on the same network can use it)")
    ap.add_argument("--public", action="store_true",
                    help="run as a hosted site: each visitor gets their own runs, saved teams and careers; "
                         "password from SITE_PASSWORD, simulation limit from MAX_JOBS (default 6)")
    ap.add_argument("--host", default=None,
                    help="address to listen on (--public: 0.0.0.0, e.g. in Docker; use 127.0.0.1 behind a tunnel "
                         "on the same computer)")
    args = ap.parse_args(argv)
    if args.public:
        serve_public(args.host or "0.0.0.0", args.port, os.environ.get("SITE_PASSWORD"),
                     int(os.environ.get("MAX_JOBS") or 6))
        return 0
    url = f"http://localhost:{args.port}"
    if not args.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    print(f"Limited-overs simulator UI on {url}  (Ctrl+C to stop)")
    if args.lan:
        ips = lan_addresses()
        if ips:
            print("Other devices on this network can open: "
                  + ", ".join(f"http://{ip}:{args.port}" for ip in ips))
        else:
            print("No network address found; is this computer connected to a network?")
        print("If they can't connect, allow Python through Windows Firewall for Private networks "
              "and make sure the Wi-Fi is set to Private.")
    app.config["LAN"] = args.lan            # two-player rooms show join links only when others can connect
    app.run(host=args.host or ("0.0.0.0" if args.lan else "127.0.0.1"), port=args.port, threaded=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
