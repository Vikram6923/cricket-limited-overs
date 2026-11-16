"""Auction: the routes of a one-person auction (the auction itself is engine/auction.py)."""
from __future__ import annotations

from .runs import *  # noqa: F401,F403

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
            if fmt not in FMTS:
                return jsonify(error="Choose T20, ODI or Test."), 400
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


__all__ = [n for n in dir() if not n.startswith("__")]      # everything, underscore names too: one program in several files
