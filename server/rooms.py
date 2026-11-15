"""Two players: rooms where two people (and spectators) play a match, a series, or a draft / auction and its
league, each on their own device (docs/multiplayer_design.md)."""
from __future__ import annotations

from .runs import *  # noqa: F401,F403

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
    if fmt not in LIMITED:
        return NOT_FOR_TESTS if fmt == "test" else "Choose T20 or ODI."
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


__all__ = [n for n in dir() if not n.startswith("__")]      # everything, underscore names too: one program in several files
