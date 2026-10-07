"""Browser UI for the limited-overs simulator (build-order step 5).

    python web_ui.py              # opens http://localhost:5070
    python web_ui.py --no-browser --port 5071

Plain Flask, one background job at a time, the page polls /api/status (no websockets, no CDN scripts, works
offline). The engine is called directly as a library. Modes: Match / Series, Tournament, Classic Series and
Classic Tournament (a nation over a year range, rated on those years), Team Builder.
Saved teams live in data/teams.json (created from data/teams_default.json on first run); the last results are
kept in results/last/ so they survive a restart.
"""
from __future__ import annotations

import argparse
import json
import random
import shutil
import threading
import time
import traceback
import webbrowser
from collections import Counter
from functools import lru_cache
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_from_directory

from engine.conditions import venue_table
from engine.control import KINDS, Cancelled, WaitingController
from engine import history
from engine.auction import Auction, season_pool, years_pool
from engine.draft import DEFAULT_TEAMS, Draft
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
    "ipl": "Indian Premier League", "bbl": "Big Bash League", "psl": "Pakistan Super League",
    "cpl": "Caribbean Premier League", "sat": "SA20", "ilt": "International League T20",
    "bpl": "Bangladesh Premier League", "lpl": "Lanka Premier League", "mlc": "Major League Cricket",
    "ntb": "T20 Blast (England)", "ssm": "Super Smash (New Zealand)",
    "odi_full": "ODIs (full members)", "odi": "ODIs (all teams)",
}
KNOCKOUTS = {"semis": "Semi-finals + final", "ipl": "IPL playoffs (Q1, Eliminator, Q2, Final)",
             "final": "Final (top two)", "none": "No knockouts (league winner)"}

app = Flask(__name__, static_folder=None)


# ------------------------------------------------------------------------------------------------ teams

def load_teams() -> list[dict]:
    if not TEAMS.exists():
        shutil.copyfile(TEAMS_DEFAULT, TEAMS)
    return json.loads(TEAMS.read_text(encoding="utf-8"))


def save_teams(teams: list[dict]) -> None:
    TEAMS.write_text(json.dumps(teams, indent=1, ensure_ascii=False), encoding="utf-8")


@lru_cache(maxsize=None)
def home_grounds() -> dict:
    p = ROOT / "data" / "home_grounds.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def home_ground(entry, fmt: str) -> str | None:
    """Primary home ground of a tournament side: a franchise's own ground (league presets), else its nation's
    (scripts/build_home_grounds.py): the historical team's nation, or the nation most of a saved team's players play
    for (at least 6). None (neutral venues) for mixed sides such as draft teams."""
    if isinstance(entry, dict):
        return home_grounds().get(fmt, {}).get(entry.get("nation"))
    saved = next((t for t in load_teams() if t["name"] == entry), None)
    if not saved:
        return None
    if saved.get("home_venue"):
        return saved["home_venue"]
    rows = ratings(fmt)["players"]
    nat = Counter((rows.get(p["id"]) or {}).get("team") for p in saved["players"])
    nat.pop(None, None)
    top = nat.most_common(1)
    return home_grounds().get(fmt, {}).get(top[0][0]) if top and top[0][1] >= 6 else None


def team_spec(entry, fmt: str = "t20", squad_size: int | None = history.SQUAD_SIZE, years_mode: str = "blend") -> dict:
    """A saved team (by name) or a historical team ({"nation", "y1", "y2"}; squad = the most-capped squad_size,
    None = everyone who played; years_mode "blend" | "only", see engine/periods.py)."""
    if isinstance(entry, dict):
        return history.historical_team(fmt, entry["nation"], int(entry["y1"]), int(entry["y2"]), size=squad_size,
                                       years_mode=years_mode)
    t = next((t for t in load_teams() if t["name"] == entry), None)
    if not t:
        raise ValueError(f"no saved team called {entry!r}")
    ids = [p["id"] for p in t["players"]]
    spec = {"name": t["name"], "squad" if len(ids) > 11 else "players": ids}
    for k in ("overseas", "max_overseas"):   # league presets (e.g. IPL: at most 4 overseas players in the XI)
        if t.get(k) is not None:
            spec[k] = t[k]
    return spec


def check_entries(entries: list, fmt: str) -> str | None:
    """Error message for a list of team entries, or None. Historical entries need a nation that played then."""
    names = {t["name"] for t in load_teams()}
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
            if e not in names:
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

    def to_dict(self) -> dict:
        d = {"status": self.status, "title": self.title, "done": self.done, "total": self.total,
             "elapsed": round((self.finished or time.time()) - self.started, 1), "error": self.error}
        c = self.controller
        if c:
            d["captain"] = {"team": c.team, "manual": sorted(c.manual_kinds), "pending": c.pending,
                            "skip": (c.skip or {}).get("scope")}
        return d


JOB: Job | None = None
LOCK = threading.Lock()
DRAFT: Draft | None = None     # the draft in progress (or just finished, waiting for its league)
AUCTION: Auction | None = None  # the auction in progress (or just finished, waiting for its league)


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


def _run(job: Job, params: dict) -> None:
    global JOB
    try:
        def on_match(card):
            job.done += 1
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
        if params["mode"] == "league":
            s = league_season(params["league"], params.get("season"))
            specs = [{"name": t["name"], "squad": t["players"], "overseas": t["overseas"],
                      "max_overseas": t["max_overseas"]} for t in s["teams"]]
            homes = {t["name"]: t["home_venue"] for t in s["teams"] if t.get("home_venue")}
            control = {job.controller.team: job.controller} if job.controller else None
            res = play_tournament(specs, fmt="t20", comp=params["league"], year=s["year"], rounds=2, knockout="ipl",
                                  venues=venues_, home_venues=homes, seed=seed, rain=rain_, on_match=on_match,
                                  control=control)
        elif params["mode"] == "draft":
            groups = int(params.get("groups") or 1)
            res = play_tournament(DRAFT.team_specs(), fmt=fmt, comp=comp, year=year,
                                  rounds=int(params.get("rounds") or 1), groups=groups if groups > 1 else None,
                                  knockout=params.get("knockout") or "semis", venues=venues_, seed=seed, rain=rain_,
                                  on_match=on_match)
            res["draft"] = {"teams": DRAFT.teams, "user": DRAFT.user,
                            "board": DRAFT.state()["board"], "years": [DRAFT.y1, DRAFT.y2]}
        elif params["mode"] == "auction":
            a = AUCTION
            control = {job.controller.team: job.controller} if job.controller else None
            if a.comp:                         # a real season: its conditions, home grounds and IPL playoffs
                res = play_tournament(a.team_specs(), fmt="t20", comp=a.comp, year=a.year, rounds=2, knockout="ipl",
                                      home_venues={t: h for t, h in a.homes.items() if h}, seed=seed, rain=rain_,
                                      on_match=on_match, control=control)
            else:
                res = play_tournament(a.team_specs(), fmt=fmt, comp=comp, year=year,
                                      rounds=int(params.get("rounds") or 1), knockout=params.get("knockout") or "semis",
                                      venues=venues_, seed=seed, rain=rain_, on_match=on_match, control=control)
            sm = a.summary()
            res["draft"] = {"teams": sm["teams"], "user": sm["user"], "board": sm["board"], "auction": True,
                            "purse": sm["purse"]}
        elif params["mode"] == "series":
            res = play_series(team_spec(params["team1"], fmt, size, ym), team_spec(params["team2"], fmt, size, ym),
                              n=int(params["matches"]),
                              fmt=fmt, comp=comp, year=year, venues=venues_, seed=seed, rain=rain_, on_match=on_match)
        else:
            groups = int(params.get("groups") or 1)
            specs = [team_spec(t, fmt, size, ym) for t in params["teams"]]
            homes = {sp["name"]: h for t, sp in zip(params["teams"], specs) if (h := home_ground(t, fmt))}
            res = play_tournament(specs, fmt=fmt, comp=comp, year=year,
                                  rounds=int(params.get("rounds") or 1), groups=groups if groups > 1 else None,
                                  knockout=params.get("knockout") or "semis", venues=venues_, home_venues=homes,
                                  seed=seed, rain=rain_, on_match=on_match)
        res["title"] = job.title
        res["mode"] = params["mode"]
        _augment(res)
        if LAST.exists():
            shutil.rmtree(LAST)
        save(res, LAST)
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
        "leagues": [{"id": k, "label": lg["label"],
                     "seasons": [{"season": s["season"], "year": s["year"], "max_overseas": s["max_overseas"],
                                  "teams": [{"name": t["name"], "franchise": t.get("franchise", t["name"]),
                                             "n": len(t["players"]), "overseas": len(t["overseas"])}
                                            for t in s["teams"]]} for s in lg["seasons"]]}
                    for k, lg in league_seasons().items()],
        "years": {f: [history.first_year(f), history.last_year(f)] for f in ("t20", "odi")},
        "teams": load_teams(), "has_results": (LAST / "summary.json").exists(), "saved": saved_runs(),
        "job": JOB.to_dict() if JOB else None,
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
    global JOB
    p = request.get_json(force=True)
    with LOCK:
        if JOB and JOB.status == "running":
            return jsonify(error="A simulation is already running."), 409
        if p.get("mode") == "league":
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
        elif p.get("mode") == "draft":
            if not DRAFT or not DRAFT.done:
                return jsonify(error="Finish the draft first."), 400
            if DRAFT.fmt != fmt:
                return jsonify(error=f"The squads were drafted for {DRAFT.fmt.upper()}."), 400
            teams = DRAFT.teams
            groups = int(p.get("groups") or 1)
            ko = p.get("knockout") or "semis"
            if ko not in KNOCKOUTS:
                return jsonify(error="Unknown knockout format."), 400
            need = {"semis": 4, "ipl": 4, "final": 2, "none": 1}[ko]
            if len(teams) < need or (groups > 1 and (ko == "ipl" or len(teams) < 4)):
                return jsonify(error="Not enough teams for these knockouts / groups."), 400
            total = match_count(len(teams), int(p.get("rounds") or 1), groups if groups > 1 else None, ko)
            title = f"Fantasy draft league - {len(teams)} teams, players from {DRAFT.y1}-{DRAFT.y2}"
        elif p.get("mode") == "auction":
            a = AUCTION
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
        else:
            return jsonify(error="Unknown mode."), 400
        JOB = Job(title, total)
        if p.get("mode") in ("league", "auction") and p.get("captain"):
            manual = set(p["manual"]) & set(KINDS) if isinstance(p.get("manual"), list) else set(KINDS)
            JOB.controller = WaitingController(p["captain"], manual)
        threading.Thread(target=_run, args=(JOB, p), daemon=True).start()
    return jsonify(ok=True)


# ------------------------------------------------------------------------------------------------ draft

def _draft_state() -> dict:
    return DRAFT.state() if DRAFT else {"current": None, "done": False, "teams": []}


@app.post("/api/draft/start")
def api_draft_start():
    global DRAFT
    d = request.get_json(force=True)
    fmt = d.get("fmt")
    if fmt not in ("t20", "odi"):
        return jsonify(error="Choose T20 or ODI."), 400
    if JOB and JOB.status == "running":
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
        DRAFT = Draft(fmt, y1, y2, names, user=d.get("user") or None, source=source, seed=seed, years_mode=ym)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    DRAFT.run_cpu()
    pool = [p.row() for p in DRAFT.pool]
    return jsonify(state=_draft_state(), pool=pool)


@app.get("/api/draft")
def api_draft():
    if not DRAFT:
        return jsonify(error="No draft."), 404
    return jsonify(state=_draft_state(), pool=[p.row() for p in DRAFT.pool])


@app.post("/api/draft/pick")
def api_draft_pick():
    if not DRAFT or DRAFT.done:
        return jsonify(error="No draft in progress."), 400
    d = request.get_json(force=True)
    try:
        if d.get("auto") == "rest":
            while not DRAFT.done:
                DRAFT.cpu_pick()
        elif d.get("auto"):
            if DRAFT.current() != DRAFT.user:
                raise ValueError("It is not your pick.")
            DRAFT.cpu_pick()
        else:
            if DRAFT.current() != DRAFT.user:
                raise ValueError("It is not your pick.")
            DRAFT.pick(d.get("id"))
    except ValueError as e:
        return jsonify(error=str(e)), 400
    DRAFT.run_cpu()
    return jsonify(state=_draft_state())


# ------------------------------------------------------------------------------------------------ auction

def _auction_reply(pool: bool = False):
    a = AUCTION
    if a.done and a.user is not None and not getattr(a, "_saved", False):     # retain from it next time
        AUCTION_LAST.parent.mkdir(parents=True, exist_ok=True)
        AUCTION_LAST.write_text(json.dumps({"label": a.label, "fmt": a.fmt, "squads": a.squad}), encoding="utf-8")
        a._saved = True
    out = {"state": a.state()}
    if pool:
        out["pool"] = [x.row() for x in a.lots.values()]
    else:
        out["changes"] = {i: {"status": x.status, "buyer": x.buyer, "price": x.price, "set": x.set}
                          for i, x in a.lots.items()}
    return jsonify(out)


def _last_auction() -> dict:
    try:
        return json.loads(AUCTION_LAST.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


@app.get("/api/auction/last")
def api_auction_last():
    d = _last_auction()
    return jsonify(label=d.get("label"), fmt=d.get("fmt"), teams=sorted(d.get("squads") or {}))


@app.post("/api/auction/start")
def api_auction_start():
    """{pool: "season" | "years", league, season | fmt, y1, y2, source, home, years_mode, teams,
    user, retain: "previous" | "last" | "none", seed}"""
    global AUCTION
    d = request.get_json(force=True)
    if JOB and JOB.status == "running":
        return jsonify(error="A simulation is running."), 409
    try:
        seed = int(d["seed"]) if str(d.get("seed") or "").strip() else None
        if d.get("pool") == "season":
            if not league_season(d.get("league"), d.get("season")):
                return jsonify(error="Unknown league or season."), 400
            pool = season_pool(d["league"], d["season"])
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
        prev = {}
        if retain == "previous":
            prev = None                        # the pool's own previous season
        elif retain == "last":
            prev = _last_auction().get("squads") or {}
            if not set(prev) & set(pool["teams"]):
                return jsonify(error="Your last auction had none of these teams."), 400
        elif retain.startswith("saved:"):
            sd = SAVED / retain[6:]
            if sd.parent != SAVED or not (sd / "summary.json").exists():
                return jsonify(error="That saved run no longer exists."), 400
            prev = _run_meta(sd)["squads"]
            if not set(prev) & set(pool["teams"]):
                return jsonify(error="That saved run has none of these teams."), 400
        AUCTION = Auction(pool, user=d.get("user") or None, prev=prev, seed=seed)
    except (TypeError, ValueError) as e:
        return jsonify(error=str(e) or "Check the settings."), 400
    return _auction_reply(pool=True)


@app.get("/api/auction")
def api_auction():
    if not AUCTION:
        return jsonify(error="No auction."), 404
    return _auction_reply(pool=True)


@app.post("/api/auction/act")
def api_auction_act():
    """The user's answer to the open question, or {auto: "set" | "all"} (the computer bids for the user)."""
    if not AUCTION or AUCTION.done:
        return jsonify(error="No auction in progress."), 400
    d = request.get_json(force=True)
    try:
        if d.get("auto") in ("set", "all"):
            AUCTION.auto(d["auto"])
        else:
            AUCTION.act(d.get("answer") or {})
    except (TypeError, ValueError) as e:
        return jsonify(error=str(e)), 400
    return _auction_reply()


@app.get("/api/status")
def api_status():
    return jsonify(JOB.to_dict() if JOB else {"status": "idle"})


@app.post("/api/stop")
def api_stop():
    if JOB and JOB.status == "running":
        JOB.cancel = True
        if JOB.controller:
            JOB.controller.cancel()
    return jsonify(ok=True)


@app.post("/api/decide")
def api_decide():
    """The captain's answer to the open question: {id, choice (None = the computer's), auto: {kind: bool},
    skip: "innings" | "match" | "all"}."""
    p = request.get_json(force=True)
    c = JOB.controller if JOB and JOB.status == "running" else None
    if not c:
        return jsonify(error="No match is waiting for a decision."), 409
    if not c.answer(int(p.get("id") or 0), p.get("choice"), p.get("auto"), p.get("skip")):
        return jsonify(error="That decision has already been made."), 409
    return jsonify(ok=True)


# ------------------------------------------------------------------------------------------------ saved runs

def _run_dir(run: str | None) -> Path:
    """The last run, or a saved one (by folder name)."""
    if not run:
        return LAST
    d = SAVED / run
    if d.parent != SAVED or not (d / "summary.json").exists():
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
    if not SAVED.exists():
        return []
    out = []
    for d in SAVED.iterdir():
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
    if not (LAST / "summary.json").exists():
        return jsonify(error="No results to save."), 400
    name = " ".join(str(request.get_json(force=True).get("name") or "").split())
    name = "".join(ch for ch in name if ch.isalnum() or ch in " -_.,()'&+")[:80].strip(" .")
    if not name:
        return jsonify(error="Give the run a name."), 400
    d = SAVED / name
    if d.exists():
        return jsonify(error=f"There is already a saved run called {name!r}."), 400
    SAVED.mkdir(parents=True, exist_ok=True)
    shutil.copytree(LAST, d)
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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=5070)  # 5060/5061 are blocked by browsers (SIP)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args(argv)
    url = f"http://localhost:{args.port}"
    if not args.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    print(f"Limited-overs simulator UI on {url}  (Ctrl+C to stop)")
    app.run(host="127.0.0.1", port=args.port, threaded=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
