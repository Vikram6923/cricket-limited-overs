"""Test series: a host, its grounds in rotation, every match played, the series result and Test statistics.

    from engine.test_series import play_test_series
    res = play_test_series(india, australia, n=5, year=2024, seed=1)          # India at home
    res = play_test_series(india, australia, n=5, host="Australia", seed=1)   # in Australia
    res = play_test_series(india, australia, n=3, host="neutral", seed=1)     # no home side, no ground

`engine.tournament.play_series(..., fmt="test")` sends a Test series here, as `simulate_match` sends a Test to
engine/test_match.py. The result has the shape of a limited-overs series (so it is saved and shown the same way)
with Test figures: draws, best match bowling, ten-wicket matches, Test records (engine/test_records.py) and two
rankings: by points, and by points plus impact (win chance plus half the draw chance added, engine/test_wdl.py).
"""
from __future__ import annotations

import json
import random
from collections import Counter
from functools import lru_cache

from .data import DATA, ratings
from .match import simulate_match
from .test_records import test_records
from .tournament import _seed, team_spec, tournament_stats

FMT = "test"
SIZES = (1, 2, 3, 4, 5, 6)             # a Test series has 1 to 6 matches (the page offers 1, 2, 3 and 5)
ORDINALS = ("1st", "2nd", "3rd", "4th", "5th", "6th")
MIN_NATION = 6                         # a saved side is a nation's when at least this many of its players are


@lru_cache(maxsize=None)
def home_grounds() -> dict:
    """host -> its Test grounds, most used lately first (data/home_grounds.json, scripts/build_home_grounds.py)."""
    p = DATA / "home_grounds.json"
    return (json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}).get("test_grounds", {})


def nation_of(spec: dict) -> str | None:
    """The country a side plays for: its "nation" (a historical side), its name when that is a Test nation, or
    the nation most of its players have played Tests for (at least MIN_NATION of them)."""
    if spec.get("nation"):
        return spec["nation"]
    if spec["name"] in home_grounds():
        return spec["name"]
    rows = ratings(FMT)["players"]
    ids = [x["id"] if isinstance(x, dict) else getattr(x, "id", x) for x in spec.get("squad") or spec.get("players") or []]
    top = Counter(t for i in ids if (t := (rows.get(i) or {}).get("team"))).most_common(1)
    return top[0][0] if top and top[0][1] >= MIN_NATION else None


def series_grounds(host: str | None, n: int, venues: list | None = None) -> list:
    """The ground of each match: the given venues in rotation, else the host's grounds in rotation (None: no
    ground is named, so neutral, average conditions)."""
    pool = list(venues or []) or home_grounds().get(host or "", [])
    return [pool[i % len(pool)] if pool else None for i in range(n)]


def result_text(a: str, b: str, wa: int, wb: int, n: int) -> str:
    """ "India won the series 2-1" (a five-Test series won 2-1 has two draws), "Series drawn 1-1"."""
    if wa == wb:
        return f"Series drawn {wa}-{wb}"
    w, x, y = (a, wa, wb) if wa > wb else (b, wb, wa)
    return f"{w} won the series {x}-{y}"


def innings_scores(card: dict) -> list[str]:
    """One line per side: "India 220 & 310/5d"."""
    out = []
    for t in card["teams"]:
        parts = []
        for i in card["innings"]:
            if i["team"] == t:
                s = str(i["runs"]) if i["wickets"] >= 10 else f"{i['runs']}/{i['wickets']}"
                parts.append(s + ("d" if i.get("declared") else "") + (" (f/o)" if i.get("follow_on") else ""))
        if parts:
            out.append(f"{t} {' & '.join(parts)}")
    return out


def summary_card(c: dict) -> dict:
    return {"match_no": c["match_no"], "stage": c["stage"], "teams": c["teams"], "venue": c.get("venue"),
            "scores": innings_scores(c), "result": c["result"]["text"], "days": len(c.get("days") or []),
            "player_of_match": (c.get("player_of_match") or {}).get("name")}


def match_figures(cards: list[dict]) -> dict:
    """(bowler id, team) -> {"best_match": (wkts, runs, match_no), "ten_w": n}: a bowler's figures over both
    innings of a match."""
    out: dict = {}
    for c in cards:
        tot: dict = {}
        for inn in c["innings"]:
            for w in inn["bowling"]:
                t = tot.setdefault((w["id"], inn["bowling_team"]), [0, 0])
                t[0] += w["wickets"]
                t[1] += w["runs"]
        for k, (wk, rn) in tot.items():
            r = out.setdefault(k, {"best_match": None, "ten_w": 0})
            r["ten_w"] += wk >= 10
            if r["best_match"] is None or (wk, -rn) > (r["best_match"][0], -r["best_match"][1]):
                r["best_match"] = (wk, rn, c["match_no"])
    return out


def points(cards: list[dict], wins: dict) -> list[dict]:
    """The Test ranking by points: each match's balanced points summed (engine/test_match.py: runs weighted by
    how low-scoring the match was, a wicket worth the era's runs per wicket, 5 a catch or stumping, 25 for a
    win), with each player's impact over the series beside it (card["impact"]; 0 without the win / draw / loss
    table)."""
    people: dict = {}
    for c in cards:
        team_of = {p["id"]: t for t, xi in c["xi"].items() for p in xi}
        name_of = {p["id"]: p["name"] for xi in c["xi"].values() for p in xi}
        for pid, (bat, bowl, field, win) in (c.get("points") or {}).items():
            t = team_of.get(pid)
            if not t:
                continue
            p = people.setdefault((pid, t), {"id": pid, "name": name_of[pid], "team": t, "runs": 0, "wickets": 0,
                                             "catches": 0, "bat_pts": 0.0, "bowl_pts": 0.0, "field_pts": 0.0,
                                             "win_pts": 0.0, "sr_bonus": 0.0, "econ_bonus": 0.0, "impact": 0.0,
                                             "impact_pts": 0.0})
            p["bat_pts"] += bat
            p["bowl_pts"] += bowl
            p["field_pts"] += field
            p["win_pts"] += win
        for pid, v in (c.get("impact") or {}).items():
            if (pid, team_of.get(pid)) in people:
                people[(pid, team_of[pid])]["impact"] += v
                people[(pid, team_of[pid])]["impact_pts"] += v * (c.get("runs_per_win") or 0.0)
        for inn in c["innings"]:
            for b in inn["batting"]:
                if (b["id"], inn["team"]) in people:
                    people[(b["id"], inn["team"])]["runs"] += b["runs"]
            for w in inn["bowling"]:
                if (w["id"], inn["bowling_team"]) in people:
                    people[(w["id"], inn["bowling_team"])]["wickets"] += w["wickets"]
    rows = []
    for p in people.values():
        p["catches"] = round(p["field_pts"] / 5)
        for k in ("bat_pts", "bowl_pts", "field_pts", "win_pts"):
            p[k] = round(p[k], 1)
        p["balanced"] = round(p["bat_pts"] + p["bowl_pts"] + p["field_pts"] + p["win_pts"], 1)
        p["impact"] = round(p["impact"], 3)
        p["impact_pts"] = round(p["impact_pts"], 1)
        p["score"] = round(p["balanced"] + p["impact_pts"], 1)     # the player-of-the-match score, summed
        rows.append(p)
    rows.sort(key=lambda p: (-p["balanced"], p["name"]))
    return [dict(p, rank=i) for i, p in enumerate(rows, 1)]


def test_stats(cards: list[dict], wins: dict) -> dict:
    """The limited-overs tables (engine/tournament.py) with the Test columns added: best match figures and
    ten-wicket matches for bowlers; Test records; the rankings. With the win / draw / loss table the official
    ranking is by the score that picks the player of each match, added up (points plus impact turned into
    runs), and it picks the player of the series ("kind": "test"); without the table both rankings are the
    points ("kind": "test_points")."""
    st = tournament_stats(cards, wins)
    figs = match_figures(cards)
    for r in st["bowling"]:
        f = figs.get((r["id"], r["team"])) or {}
        bm = f.get("best_match")
        r["ten_w"] = f.get("ten_w", 0)
        r["best_match_figures"] = f"{bm[0]}/{bm[1]}" if bm else None
        r["best_match_no"] = bm[2] if bm else None
    rank = points(cards, wins)
    if all("impact" in c for c in cards):
        by_score = sorted(rank, key=lambda p: (-p["score"], p["rank"]))
        st["mvp"] = {"official": [dict(p, rank=i) for i, p in enumerate(by_score, 1)], "balanced": rank,
                     "kind": "test"}
    else:
        st["mvp"] = {"official": rank, "balanced": rank, "kind": "test_points"}
    st["records"] = test_records(cards)
    return st


test_stats.__test__ = False            # not a test (the name starts with test_)


def play_test_series(team_a: dict, team_b: dict, n: int = 3, comp: str | None = None, year: int = 2025,
                     venues: list | None = None, seed: int | None = None, on_match=None,
                     host: str | None = None, control: dict | None = None, skill: dict | None = None,
                     best_of: bool = False, **kw) -> dict:
    """A series of n Tests; all are played, unless best_of: then it stops once one side cannot be caught (2-0
    in a three-Test series; draws count for nobody). skill: {team name: "expert" | "average" | "easy"} for
    computer captains (engine/test_captain.py). host: the country it is played in: None = team_a's (the first
    side is at home), "neutral" = nobody's, or a country's name. Its grounds are used in rotation (venues: use
    these instead; a ground's own country then decides the weather and the home side), it sets the weather, and
    the side whose nation it is gets the home edge. control: {team name: engine.control.Controller} for a
    side a person captains (engine/test_control.py). kw goes to every match (engine/test_match.py)."""
    if n not in SIZES:
        raise ValueError(f"A Test series has {SIZES[0]} to {SIZES[-1]} matches.")
    a, b = team_spec(FMT, team_a), team_spec(FMT, team_b)
    if a["name"] == b["name"]:
        raise ValueError("The two sides need different names.")
    for sp in (a, b):
        sp.setdefault("nation", nation_of(sp))
    host = None if host == "neutral" else host or (a["nation"] if a["nation"] in home_grounds() else None)
    seed = seed if seed is not None else random.randrange(1 << 30)
    grounds = series_grounds(host, n, venues)
    cards = []
    for i in range(n):
        args = dict(kw)
        if skill:
            args["skill"] = skill
        if host and not venues:
            args["host"] = host
        stage = "Only Test" if n == 1 else f"{ORDINALS[i]} Test"
        if control:
            args["control"] = control
            for ctl in control.values():
                ctl.context = {"stage": stage, "match_no": i + 1, "knockout": False, "venue": grounds[i]}
        card = simulate_match(a, b, fmt=FMT, comp=comp, year=year, venue=grounds[i], seed=_seed(seed, i + 1), **args)
        card["match_no"], card["knockout"] = i + 1, False
        card["stage"] = stage
        cards.append(card)
        if on_match:
            on_match(card)
        w = Counter(c["result"]["winner"] for c in cards if c["result"].get("winner"))
        if best_of and abs(w.get(a["name"], 0) - w.get(b["name"], 0)) > n - i - 1:
            break
    wins = Counter(c["result"]["winner"] for c in cards if c["result"].get("winner"))
    wa, wb = wins.get(a["name"], 0), wins.get(b["name"], 0)
    text = cards[0]["result"]["text"] if n == 1 else result_text(a["name"], b["name"], wa, wb, n)
    stats = test_stats(cards, dict(wins))
    return {"kind": "series", "format": FMT, "competition": cards[0]["competition"], "year": year, "seed": seed,
            "teams": [a["name"], b["name"]], "score": {a["name"]: wa, b["name"]: wb}, "draws": len(cards) - wa - wb,
            "host": host, "home": cards[0]["conditions"].get("home"), "result": text,
            "winner": a["name"] if wa > wb else b["name"] if wb > wa else None,
            "player_of_series": stats["mvp"]["official"][0] if stats["mvp"]["official"] else None,
            "fixtures": [summary_card(c) for c in cards], "matches": cards, "best_of": n if best_of else None,
            "tests": n, **stats}
