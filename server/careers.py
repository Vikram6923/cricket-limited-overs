"""Career: the routes of the career modes (a league career, engine/career.py; a state career,
engine/state_career.py). Where careers are kept is in core.py."""
from __future__ import annotations

from .runs import *  # noqa: F401,F403
from .auction import _auction_reply

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


__all__ = [n for n in dir() if not n.startswith("__")]      # everything, underscore names too: one program in several files
