"""Browser UI for the limited-overs simulator (build-order step 5).

    python web_ui.py              # opens http://localhost:5070
    python web_ui.py --no-browser --port 5071

Plain Flask, one background job at a time, the page polls /api/status (no websockets, no CDN scripts, works
offline). The engine is called directly as a library. Modes: Match / Series, Tournament, Team Builder.
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
from functools import lru_cache
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_from_directory

from engine.conditions import venue_table
from engine.data import ratings
from engine.render import full_text, match_report
from engine.tournament import match_count, play_series, play_tournament, save

ROOT = Path(__file__).resolve().parent
UI = ROOT / "webui"
TEAMS = ROOT / "data" / "teams.json"
TEAMS_DEFAULT = ROOT / "data" / "teams_default.json"
LAST = ROOT / "results" / "last"

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


def team_spec(name: str) -> dict:
    t = next((t for t in load_teams() if t["name"] == name), None)
    if not t:
        raise ValueError(f"no saved team called {name!r}")
    ids = [p["id"] for p in t["players"]]
    return {"name": t["name"], "squad" if len(ids) > 11 else "players": ids}


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

    def to_dict(self) -> dict:
        return {"status": self.status, "title": self.title, "done": self.done, "total": self.total,
                "elapsed": round((self.finished or time.time()) - self.started, 1), "error": self.error}


JOB: Job | None = None
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
        if params["mode"] == "series":
            res = play_series(team_spec(params["team1"]), team_spec(params["team2"]), n=int(params["matches"]),
                              fmt=fmt, comp=comp, year=year, venues=venues_, seed=seed, on_match=on_match)
        else:
            groups = int(params.get("groups") or 1)
            res = play_tournament([team_spec(t) for t in params["teams"]], fmt=fmt, comp=comp, year=year,
                                  rounds=int(params.get("rounds") or 1), groups=groups if groups > 1 else None,
                                  knockout=params.get("knockout") or "semis", venues=venues_, seed=seed,
                                  on_match=on_match)
        res["title"] = job.title
        _augment(res)
        if LAST.exists():
            shutil.rmtree(LAST)
        save(res, LAST)
        job.status = "done"
    except Stopped:
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
        "teams": load_teams(), "has_results": (LAST / "summary.json").exists(),
        "job": JOB.to_dict() if JOB else None,
    })


@app.get("/api/players")
def api_players():
    fmt = request.args.get("fmt", "t20")
    if fmt not in ("t20", "odi"):
        abort(400)
    return jsonify(players(fmt))


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
        names = {t["name"] for t in load_teams()}
        if p.get("fmt") not in ("t20", "odi"):
            return jsonify(error="Choose T20 or ODI."), 400
        if p.get("mode") == "series":
            a, b = p.get("team1"), p.get("team2")
            if a not in names or b not in names:
                return jsonify(error="Choose two saved teams."), 400
            if a == b:
                return jsonify(error="Choose two different teams."), 400
            n = int(p.get("matches") or 1)
            if not 1 <= n <= 7:
                return jsonify(error="A series has 1 to 7 matches."), 400
            title = f"{a} v {b}" + (f" - {n}-match series" if n > 1 else "")
            total = n
        elif p.get("mode") == "tournament":
            teams = p.get("teams") or []
            if len(teams) < 2 or any(t not in names for t in teams):
                return jsonify(error="Pick at least two saved teams."), 400
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
        threading.Thread(target=_run, args=(JOB, p), daemon=True).start()
    return jsonify(ok=True)


@app.get("/api/status")
def api_status():
    return jsonify(JOB.to_dict() if JOB else {"status": "idle"})


@app.post("/api/stop")
def api_stop():
    if JOB and JOB.status == "running":
        JOB.cancel = True
    return jsonify(ok=True)


@app.get("/api/results")
def api_results():
    p = LAST / "summary.json"
    if not p.exists():
        return jsonify(error="No results yet - run a simulation first."), 404
    return app.response_class(p.read_text(encoding="utf-8"), mimetype="application/json")


@app.get("/api/match/<int:n>")
def api_match(n: int):
    p = LAST / "matches" / f"{n:03d}.json"
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
