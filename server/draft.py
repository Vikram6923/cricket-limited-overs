"""Fantasy Draft: the routes of a one-person draft (the draft itself is engine/draft.py)."""
from __future__ import annotations

from .runs import *  # noqa: F401,F403

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


__all__ = [n for n in dir() if not n.startswith("__")]      # everything, underscore names too: one program in several files
