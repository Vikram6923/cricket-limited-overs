"""The background job that plays a run (a match, series, tournament, season, career season ...) and the routes
every mode uses: the page itself, the catalogue, saved teams, starting a run, its status and its questions."""
from __future__ import annotations

from .core import *  # noqa: F401,F403
from engine.test_series import home_grounds as test_grounds

# ------------------------------------------------------------------------------------------------ job

class Stopped(Exception):
    pass


class Job:
    def __init__(self, title: str, total: int):
        self.title, self.total, self.done = title, total, 0
        self.status, self.error = "running", None
        self.detail: str | None = None          # the traceback of an error (shown under Technical details)
        self.started, self.finished = time.time(), None
        self.cancel = False
        self.controller: WaitingController | None = None   # manual captaincy: the side the person captains
        self.controllers: dict | None = None    # two players: team name -> WaitingController (see ROOMS)
        self.winners: list = []                 # winner of each finished match (None: tie / no result)
        self.room: dict | None = None           # two players: the room the match belongs to

    def to_dict(self) -> dict:
        d = {"status": self.status, "title": self.title, "done": self.done, "total": self.total,
             "elapsed": round((self.finished or time.time()) - self.started, 1), "error": self.error,
             "detail": self.detail,
             "mp": bool(self.controllers)}
        c = self.controller
        if c:
            d["captain"] = {"team": c.team, "manual": sorted(c.manual_kinds), "pending": c.pending,
                            "skip": (c.skip or {}).get("scope")}
        return d




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
        test_kw = test_options(params) if fmt == "test" else {}   # every Test's length and ball (a Test competition)
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
                                  on_match=on_match, control=control, skill=skill, match_kw=test_kw)
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
                                      venues=venues_, seed=seed, rain=rain_, on_match=on_match, control=control, skill=skill,
                                      match_kw=test_kw)
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
                                  seed=seed, rain=rain_, on_match=on_match, control=control, match_kw=test_kw)
            res["draft"] = params["draft_info"]
        elif params["mode"] == "mp" and fmt == "test":   # two players: a Test or a Test series, every Test played
            a, b = params["specs"]
            where = params.get("host") or "neutral"
            host = "neutral" if where == "neutral" else (nation_of(b) or "neutral") if where == "away" else None
            res = play_test_series(a, b, n=int(params.get("series") or 1), comp=comp, year=year, venues=venues_,
                                   seed=seed, on_match=on_match, host=host, control=control,
                                   best_of=bool(params.get("best_of")), **test_options(params))
            if params.get("draft_info"):       # drafted or bought squads
                res["draft"] = params["draft_info"]
        elif params["mode"] == "mp":           # a single match or a best-of series between the two players
            a, b = params["specs"]
            res = play_series(a, b, n=int(params.get("series") or 1), best_of=True,
                              fmt=fmt, comp=comp, year=year, venues=venues_, seed=seed, rain=rain_, on_match=on_match,
                              control=control)
            if params.get("draft_info"):
                res["draft"] = params["draft_info"]
        elif params["mode"] == "series" and fmt == "test":
            # a Test series: its host (the first side's country, the second's, or nobody's), that country's
            # grounds in rotation unless grounds were ticked, its weather and the home edge
            t1, t2 = (team_spec(params[k], fmt, size, ym, v) for k in ("team1", "team2"))
            where = params.get("host") or "home"
            host = "neutral" if where == "neutral" else (nation_of(t2) or "neutral") if where == "away" else None
            # a person may captain one side (engine/test_control.py); the other is the fitted captain, or a
            # weaker one (engine/test_captain.py Loose)
            res = play_test_series(t1, t2, n=int(params["matches"]), comp=comp, year=year, venues=venues_, seed=seed,
                                   on_match=on_match, host=host, control=control, skill=skill,
                                   **test_options(params))
        elif params["mode"] == "wtc":          # the World Test Championship: home and away series, then a final
            specs = [team_spec(t, fmt, size, ym, v) for t in params["teams"]]
            res = play_wtc(specs, comp=comp, year=year, tests=int(params.get("tests") or 2), seed=seed,
                           on_match=on_match, control=control, skill=skill,
                           home_series=params.get("home_series") or None, **test_kw)
        elif params["mode"] == "series":
            res = play_series(team_spec(params["team1"], fmt, size, ym, v), team_spec(params["team2"], fmt, size, ym, v),
                              n=int(params["matches"]),
                              fmt=fmt, comp=comp, year=year, venues=venues_, seed=seed, rain=rain_, on_match=on_match,
                              control=control, skill=skill)
        else:
            groups = int(params.get("groups") or 1)
            specs = [team_spec(t, fmt, size, ym, v) for t in params["teams"]]
            # a Test side's home Tests go round its country's grounds (engine/test_tournament.py), not to one
            homes = {} if fmt == "test" else {sp["name"]: h for t, sp in zip(params["teams"], specs)
                                              if (h := home_ground(t, fmt, v))}
            res = play_tournament(specs, fmt=fmt, comp=comp, year=year,
                                  rounds=int(params.get("rounds") or 1), groups=groups if groups > 1 else None,
                                  knockout=params.get("knockout") or "semis", venues=venues_, home_venues=homes,
                                  seed=seed, rain=rain_, on_match=on_match, control=control, skill=skill,
                                  match_kw=test_kw)
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
            from .rooms import _mp_record       # rooms.py builds on this file
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
        job.status, job.error, job.detail = "error", friendly_error(e), traceback.format_exc()
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
        "formats": {f: {"competitions": competitions(f), "venues": venues(f)} for f in FMTS},
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
        "years": {f: [history.first_year(f), history.last_year(f)] for f in FMTS},
        "test_hosts": sorted(test_grounds()),          # nations with Test grounds (a series' host)
        "teams": load_teams(), "has_results": (V().last / "summary.json").exists(), "saved": saved_runs(),
        "careers": careers_list(),
        "test_career": {"years": test_career.start_years(),
                        "nations": {str(y): test_career.nations_in(y) for y in test_career.start_years()}},
        "job": V().job.to_dict() if V().job else None,
        "public": bool(app.config.get("MULTI")),
    })


@app.get("/api/players")
def api_players():
    fmt = request.args.get("fmt", "t20")
    if fmt not in FMTS:
        abort(400)
    return jsonify(players(fmt))


@app.get("/api/nations")
def api_nations():
    """Nations with enough players in a format and year range (for the Classic modes)."""
    fmt = request.args.get("fmt", "t20")
    if fmt not in FMTS:
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
        if p.get("mode") in ("league", "domestic", "career"):
            p["fmt"] = "t20"
        test_career_run = False
        if p.get("mode") == "career":           # a Test career's seasons are Tests
            try:
                test_career_run = getattr(load_career(p.get("career"), v), "fmt", "t20") == "test"
            except FileNotFoundError:
                return jsonify(error="Unknown career."), 400
            if test_career_run:
                p["fmt"] = "test"
        if p.get("mode") == "wtc":
            p["fmt"] = "test"
        fmt = p.get("fmt")
        if fmt not in FMTS:
            return jsonify(error="Choose T20, ODI or Test."), 400
        test = fmt == "test"
        if test and p.get("mode") not in TEST_MODES and not test_career_run:
            return jsonify(error=NOT_FOR_TESTS), 400
        if test and str(p.get("length") or "5") not in TEST_LENGTHS:
            return jsonify(error="A Test lasts three, four, five or six days, or is timeless."), 400
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
            if test and n not in TEST_SIZES:
                return jsonify(error=f"A Test series has {TEST_SIZES[0]} to {TEST_SIZES[-1]} matches."), 400
            if test and p.get("host") not in (None, "", "home", "away", "neutral"):
                return jsonify(error="The series is played at home, away or on neutral grounds."), 400
            if not 1 <= n <= SERIES_MAX:
                return jsonify(error=f"A series has 1 to {SERIES_MAX} matches."), 400
            title = f"{a} v {b}" + (f" - {n}-{'Test' if test else 'match'} series" if n > 1 else "")
            title += test_length_words(p) if test else ""
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
            err = league_format_error(len(teams), int(p.get("rounds") or 1), groups, ko)
            if err:
                return jsonify(error=err), 400
            total = match_count(len(teams), int(p.get("rounds") or 1), groups if groups > 1 else None, ko)
            title = f"Fantasy draft league - {len(teams)} teams, players from {dr.y1}-{dr.y2}" + (test_length_words(p) if test else "")
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
                err = league_format_error(len(a.teams), int(p.get("rounds") or 1), 1, ko)
                if err:
                    return jsonify(error=err), 400
                total = match_count(len(a.teams), int(p.get("rounds") or 1), None, ko)
            title = f"Auction league - {a.label}, {len(a.teams)} teams" + (test_length_words(p) if test else "")
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
            p["fmt"], p["comp"], p["year"] = getattr(car, "fmt", "t20"), car.league, car.cond_year()
            total = car.match_total() + car.background_matches()
            title = f"{car.name} - season {car.season_label}" + (" and the IPL" if car.background_matches() else "")
            if p.get("captain") and car.user:
                p["captain"] = car.user
                title += f" - you captain {car.user}"
            else:
                p["captain"] = None
        elif p.get("mode") == "wtc":
            teams = p.get("teams") or []
            if len(teams) < 3:
                return jsonify(error="The World Test Championship needs at least three teams."), 400
            err = check_entries(teams, fmt)
            if err:
                return jsonify(error=err), 400
            if str(p.get("tests") or 2) not in map(str, WTC_TESTS):
                return jsonify(error=f"A Championship series has {WTC_TESTS[0]} to {WTC_TESTS[-1]} Tests."), 400
            p["tests"] = int(p.get("tests") or 2)
            hs = str(p.get("home_series") or "").strip()      # "" the usual cycle, a number, or "all"
            if hs == "all":
                p["home_series"] = len(teams) - 1
            elif hs:
                if not hs.isdigit() or not 1 <= int(hs) <= len(teams) - 1:
                    return jsonify(error=f"With {len(teams)} teams each plays 1 to {len(teams) - 1} series at home."), 400
                p["home_series"] = int(hs)
            else:
                p["home_series"] = None
            total = wtc_match_count(len(teams), p["tests"], p["home_series"])
            title = f"World Test Championship - {len(teams)} teams, {p['tests']}-Test series" + test_length_words(p)
            sides = [label(e) for e in teams]
        elif p.get("mode") == "tournament":
            teams = p.get("teams") or []
            if len(teams) < 2:
                return jsonify(error="Pick at least two teams."), 400
            err = check_entries(teams, fmt)
            if err:
                return jsonify(error=err), 400
            groups = int(p.get("groups") or 1)
            ko = p.get("knockout") or "semis"
            err = league_format_error(len(teams), int(p.get("rounds") or 1), groups, ko)
            if err:
                return jsonify(error=err), 400
            total = match_count(len(teams), int(p.get("rounds") or 1), groups if groups > 1 else None, ko)
            title = f"Tournament - {len(teams)} teams" + (test_length_words(p) if test else "")
            sides = [label(e) for e in teams]
        else:
            return jsonify(error="Unknown mode."), 400
        cap = p.get("captain") if p.get("mode") in ("league", "domestic", "auction", "career") else None
        if p.get("mode") in ("series", "tournament", "draft", "wtc") and str(p.get("captain_i", "")).strip() != "":
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


__all__ = [n for n in dir() if not n.startswith("__")]      # everything, underscore names too: one program in several files
