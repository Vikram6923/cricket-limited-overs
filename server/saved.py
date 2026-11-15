"""Saved runs and results: the list of saved runs, saving / renaming / deleting one, and the results of a run."""
from __future__ import annotations

from .runs import *  # noqa: F401,F403

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


__all__ = [n for n in dir() if not n.startswith("__")]      # everything, underscore names too: one program in several files
