"""Series and tournaments (build-order step 4): fixtures, points tables with net run rate, knockouts, player
stats, records and MVP rankings, written as JSON (plus a text scorecard per match).

    from engine.tournament import play_series, play_tournament
    res = play_tournament([team1, team2, ...], fmt="t20", comp="t20i_full", year=2024,
                          groups=2, knockout="semis", seed=1)

Teams are the same dicts `simulate_match` takes; players may be given by Cricsheet ID or by exact name.

Command line, driven by a JSON config (see examples/):
    python -m engine.tournament examples/t20_world_cup_style.json --out results/wc
"""
from __future__ import annotations

import argparse
import itertools
import json
import random
import sys
import zlib
from pathlib import Path

from .data import FORMATS, Player, resolve
from .match import simulate_match
from .render import full_text

KNOCKOUTS = ("semis", "ipl", "final", "qf", "pre_qf", "super_league", "super_league_semis", "none")


# ------------------------------------------------------------------------------------------------ helpers

def team_spec(fmt: str, t: dict) -> dict:
    """Copy of a team dict with every player name resolved to a Cricsheet ID."""
    out = dict(t)
    for key in ("players", "squad", "order"):
        if t.get(key):
            out[key] = [x if isinstance(x, (dict, Player)) else resolve(fmt, x) for x in t[key]]
    for key in ("keeper", "captain"):
        if t.get(key):
            out[key] = resolve(fmt, t[key])
    return out


def _seed(base: int, match_no: int) -> int:
    return zlib.crc32(f"{base}|{match_no}".encode()) & 0x7FFFFFFF


def _overs(balls: int) -> str:
    return f"{balls // 6}.{balls % 6}"


class _Runner:
    """Plays matches with consistent numbering, seeds and venues."""

    def __init__(self, fmt: str, comp: str | None, year: int, seed: int | None, venues: list | None,
                 home_venues: dict | None, knockout_venues: list | None, rain: bool = False,
                 control: dict | None = None, skill: dict | None = None):
        self.fmt, self.comp, self.year = fmt, comp or FORMATS[fmt]["intl"], year
        self.rain = rain
        self.seed = seed if seed is not None else random.randrange(1 << 30)
        self.venues = list(venues or [])
        self.home = dict(home_venues or {})
        self.ko_venues = list(knockout_venues or [])
        self.cards: list[dict] = []
        self.control = control or {}  # team name -> engine.control.Controller (a person captains that side)
        self.skill = skill or {}      # team name -> "expert" | "average" | "easy" (computer captains, engine/judge.py)
        self.on_match = None          # optional callback(card) after every match (progress / cancel)

    def venue_for(self, home: str, knockout: bool) -> str | None:
        n = len(self.cards)
        if knockout and self.ko_venues:
            k = sum(1 for c in self.cards if c["knockout"])
            return self.ko_venues[k % len(self.ko_venues)]
        if not knockout and home in self.home:
            return self.home[home]
        if self.venues:
            return self.venues[n % len(self.venues)]
        return None

    def play(self, a: dict, b: dict, stage: str, knockout: bool = False) -> dict:
        no = len(self.cards) + 1
        venue = self.venue_for(a["name"], knockout)
        for ctl in self.control.values():
            ctl.context = {"stage": stage, "match_no": no, "knockout": knockout, "venue": venue}
        card = simulate_match(a, b, fmt=self.fmt, comp=self.comp, year=self.year, venue=venue,
                              seed=_seed(self.seed, no), rain_on=self.rain, control=self.control,
                              skill=self.skill)
        if knockout and card["result"]["type"] == "no_result":
            # reserve day; if that is washed out too, the higher-placed side (named first) goes through
            card = simulate_match(a, b, fmt=self.fmt, comp=self.comp, year=self.year, venue=venue,
                                  seed=_seed(self.seed, no) + 7919, rain_on=self.rain, control=self.control,
                              skill=self.skill)
            card["rain"] = ["Washed out; played on the reserve day."] + card["rain"]
            if card["result"]["type"] == "no_result":
                card["result"] = {"type": "no_result", "winner": a["name"], "loser": b["name"], "by": "no_result",
                                  "text": f"No result (reserve day washed out too) - {a['name']} go through "
                                          "as the higher-placed side"}
        card["match_no"], card["stage"], card["knockout"] = no, stage, knockout
        self.cards.append(card)
        if self.on_match:
            self.on_match(card)
        return card


# ------------------------------------------------------------------------------------------------ tables

def points_table(cards: list[dict], teams: list[str], win_points: int = 2) -> list[dict]:
    """Points and net run rate (ICC method): NRR = runs scored per over faced - runs conceded per over bowled; a
    side bowled out is charged its full quota of overs; super overs are not counted. Ties settled by a super
    over count as a win for the super-over winner. Order: points, NRR, wins, name."""
    rows = {t: {"team": t, "played": 0, "won": 0, "lost": 0, "tied": 0, "no_result": 0, "points": 0,
                "runs_for": 0, "balls_for": 0, "runs_against": 0, "balls_against": 0} for t in teams}
    for c in cards:
        names = list(c.get("teams") or [i["team"] for i in c["innings"]])
        if not all(n in rows for n in names):
            continue
        res = c["result"]
        nr = res.get("type") == "no_result"
        for inn in ([] if nr else c["innings"]):        # abandoned matches don't count towards NRR
            balls = inn["max_overs"] * 6 if inn["wickets"] >= 10 else inn["balls"]
            runs = inn["runs"]
            if inn is c["innings"][0] and res.get("dls"):
                # DLS (ICC): the side batting first is credited with the par score in the chase's overs
                i2 = c["innings"][1]
                runs = res["par"] if "par" in res else i2["target"] - 1
                balls = i2["balls"] if "par" in res else i2["max_overs"] * 6
            bat, bowl = rows[inn["team"]], rows[inn["bowling_team"]]
            bat["runs_for"] += runs
            bat["balls_for"] += balls
            bowl["runs_against"] += runs
            bowl["balls_against"] += balls
        for n in set(names):
            rows[n]["played"] += 1
        if nr:
            for n in set(names):
                rows[n]["no_result"] += 1
                rows[n]["points"] += win_points // 2
        elif res.get("winner"):
            rows[res["winner"]]["won"] += 1
            rows[res["winner"]]["points"] += win_points
            rows[res["loser"]]["lost"] += 1
        else:
            for n in set(names):
                rows[n]["tied"] += 1
                rows[n]["points"] += win_points // 2
    out = []
    for r in rows.values():
        f = 6 * r["runs_for"] / r["balls_for"] if r["balls_for"] else 0.0
        a = 6 * r["runs_against"] / r["balls_against"] if r["balls_against"] else 0.0
        r["nrr"] = round(f - a, 3)
        r["for"] = f"{r['runs_for']}/{_overs(r['balls_for'])}"
        r["against"] = f"{r['runs_against']}/{_overs(r['balls_against'])}"
        out.append(r)
    out.sort(key=lambda r: (-r["points"], -r["nrr"], -r["won"], r["team"]))
    for i, r in enumerate(out, 1):
        r["pos"] = i
    return out


# ------------------------------------------------------------------------------------------------ stats

def match_players(c: dict) -> dict[str, list[dict]]:
    """Everyone who played in the match, per team: the XI plus the player an Impact Player replaced (the card's
    XI lists the final side, with the substitute in place of the player he replaced)."""
    out = {t: list(xi) for t, xi in c["xi"].items()}
    for t, ip in (c.get("impact_player") or {}).items():
        ids = {p["id"] for p in out.get(t, [])}
        for pid, name in ((ip.get("out_id"), ip.get("out")), (ip.get("in_id"), ip.get("in"))):
            if pid and pid not in ids:
                out.setdefault(t, []).append({"id": pid, "name": name})
                ids.add(pid)
    return out


def tournament_stats(cards: list[dict], team_wins: dict) -> dict:
    """Batting, bowling and fielding tables, records and MVP rankings over the given matches (super overs
    excluded from all player figures, as in official statistics)."""
    bat, bowl, field = {}, {}, {}
    team_of, name_of = {}, {}
    apps = {}
    for c in cards:
        for team, xi in match_players(c).items():
            for p in xi:
                apps[(p["id"], team)] = apps.get((p["id"], team), 0) + 1
                team_of.setdefault(p["id"], team)
                name_of[p["id"]] = p["name"]
        for inn in c["innings"]:
            for b in inn["batting"]:
                if not b["batted"]:
                    continue
                k = (b["id"], inn["team"])
                r = bat.setdefault(k, {"inns": 0, "not_outs": 0, "runs": 0, "balls": 0, "fours": 0, "sixes": 0,
                                       "fifties": 0, "hundreds": 0, "ducks": 0, "hs": 0, "hs_not_out": False})
                r["inns"] += 1
                r["not_outs"] += not b["out"]
                for f in ("runs", "balls", "fours", "sixes"):
                    r[f] += b[f]
                r["hundreds"] += b["runs"] >= 100
                r["fifties"] += 50 <= b["runs"] < 100
                r["ducks"] += b["runs"] == 0 and b["out"]
                if b["runs"] > r["hs"] or (b["runs"] == r["hs"] and not b["out"]):
                    r["hs"], r["hs_not_out"] = b["runs"], not b["out"]
                h = b.get("how_out") or {}
                fid = h.get("fielder_id")
                if fid and h["kind"] in ("caught_fielder", "caught_keeper", "caught_bowler", "stumped", "run_out"):
                    fk = (fid, inn["bowling_team"])
                    fr = field.setdefault(fk, {"catches": 0, "stumpings": 0, "run_outs": 0})
                    key = {"stumped": "stumpings", "run_out": "run_outs"}.get(h["kind"], "catches")
                    fr[key] += 1
                    name_of.setdefault(fid, h["fielder"])
            for w in inn["bowling"]:
                k = (w["id"], inn["bowling_team"])
                r = bowl.setdefault(k, {"inns": 0, "balls": 0, "maidens": 0, "runs": 0, "wickets": 0, "dots": 0,
                                        "fours_conceded": 0, "sixes_conceded": 0, "four_w": 0, "five_w": 0,
                                        "best": None})
                r["inns"] += 1
                for f, g in (("balls", "balls"), ("maidens", "maidens"), ("runs", "runs"), ("wickets", "wickets"),
                             ("dots", "dots"), ("fours_conceded", "fours"), ("sixes_conceded", "sixes")):
                    r[f] += w[g]
                r["five_w"] += w["wickets"] >= 5
                r["four_w"] += w["wickets"] == 4
                fig = (w["wickets"], w["runs"])
                if r["best"] is None or (fig[0], -fig[1]) > (r["best"][0], -r["best"][1]):
                    r["best"] = fig

    batting = []
    for (pid, team), r in bat.items():
        outs = r["inns"] - r["not_outs"]
        batting.append({"id": pid, "name": name_of.get(pid, pid), "team": team, "matches": apps.get((pid, team), 0),
                        **{k: v for k, v in r.items() if k not in ("hs", "hs_not_out")},
                        "hs": f"{r['hs']}{'*' if r['hs_not_out'] else ''}",
                        "average": round(r["runs"] / outs, 2) if outs else None,
                        "strike_rate": round(100 * r["runs"] / r["balls"], 2) if r["balls"] else None})
    batting.sort(key=lambda r: (-r["runs"], r["balls"]))
    bowling = []
    for (pid, team), r in bowl.items():
        bowling.append({"id": pid, "name": name_of.get(pid, pid), "team": team, "matches": apps.get((pid, team), 0),
                        **{k: v for k, v in r.items() if k != "best"}, "overs": _overs(r["balls"]),
                        "best": f"{r['best'][0]}/{r['best'][1]}" if r["best"] else None,
                        "average": round(r["runs"] / r["wickets"], 2) if r["wickets"] else None,
                        "economy": round(6 * r["runs"] / r["balls"], 2) if r["balls"] else None,
                        "strike_rate": round(r["balls"] / r["wickets"], 1) if r["wickets"] else None})
    bowling.sort(key=lambda r: (-r["wickets"], r["runs"]))
    fielding = [{"id": pid, "name": name_of.get(pid, pid), "team": team, **r,
                 "dismissals": r["catches"] + r["stumpings"] + r["run_outs"]} for (pid, team), r in field.items()]
    fielding.sort(key=lambda r: -r["dismissals"])

    return {"batting": batting, "bowling": bowling, "fielding": fielding,
            "records": records(cards), "mvp": mvp(cards, batting, bowling, fielding, team_wins)}


def records(cards: list[dict], n: int = 10) -> dict:
    inns, scores, figs, fifty, hundred = [], [], [], [], []
    runs_wins, wkt_wins, supers = [], [], []
    for c in cards:
        tag = {"match_no": c["match_no"], "stage": c["stage"]}
        for i in c["innings"]:
            inns.append({**tag, "team": i["team"], "vs": i["bowling_team"], "runs": i["runs"], "wickets": i["wickets"],
                         "overs": i["overs"], "all_out": i["wickets"] >= 10})
            for b in i["batting"]:
                if b["batted"]:
                    scores.append({**tag, "name": b["name"], "team": i["team"], "vs": i["bowling_team"],
                                   "runs": b["runs"], "balls": b["balls"], "not_out": not b["out"],
                                   "fours": b["fours"], "sixes": b["sixes"]})
            for w in i["bowling"]:
                figs.append({**tag, "name": w["name"], "team": i["bowling_team"], "vs": i["team"],
                             "wickets": w["wickets"], "runs": w["runs"], "overs": w["overs"]})
        for e in c["events"]:
            if e.get("kind") == "milestone" and e.get("mark") in (50, 100) and e.get("innings", 0) < 100:
                row = {**tag, "name": e["player"], "balls": e["balls"]}
                (fifty if e["mark"] == 50 else hundred).append(row)
        r = c["result"]
        if r.get("by") == "runs":
            runs_wins.append({**tag, "winner": r["winner"], "loser": r["loser"], "margin": r["margin"], "text": r["text"]})
        elif r.get("by") == "wickets":
            wkt_wins.append({**tag, "winner": r["winner"], "loser": r["loser"], "margin": r["margin"],
                             "balls_left": r["balls_left"], "text": r["text"]})
        elif r.get("by") == "super_over":
            supers.append({**tag, "winner": r["winner"], "loser": r["loser"], "text": r["text"]})
    return {
        "highest_totals": sorted(inns, key=lambda x: -x["runs"])[:n],
        "lowest_all_out": sorted((x for x in inns if x["all_out"]), key=lambda x: x["runs"])[:n],
        "highest_scores": sorted(scores, key=lambda x: (-x["runs"], x["balls"]))[:n],
        "best_bowling": sorted(figs, key=lambda x: (-x["wickets"], x["runs"]))[:n],
        "fastest_fifties": sorted(fifty, key=lambda x: x["balls"])[:n],
        "fastest_hundreds": sorted(hundred, key=lambda x: x["balls"])[:n],
        "biggest_wins_by_runs": sorted(runs_wins, key=lambda x: -x["margin"])[:n],
        "biggest_wins_by_wickets": sorted(wkt_wins, key=lambda x: (-x["margin"], -x["balls_left"]))[:n],
        "narrowest_wins_by_runs": sorted(runs_wins, key=lambda x: x["margin"])[:n],
        "narrowest_chases": sorted(wkt_wins, key=lambda x: (x["balls_left"], x["margin"]))[:n],
        "super_overs": supers,
    }


def mvp(cards: list[dict], batting: list, bowling: list, fielding: list, team_wins: dict) -> dict:
    """Two rankings.
    official: the engine's own measure, win probability added summed over matches (1.0 = one whole win's worth);
              it also picks the player of the match and of the series.
    balanced: 1 point per run + 25 per wicket + 5 per catch/stumping + 25 per team win, plus a strike-rate bonus
              (half the runs scored above the tournament's average rate) and an economy bonus (half the runs
              saved below it)."""
    runs = sum(i["runs"] for c in cards for i in c["innings"])
    balls = sum(i["balls"] for c in cards for i in c["innings"]) or 1
    rate = runs / balls
    people: dict = {}

    def get(pid, team, name):
        return people.setdefault((pid, team), {"id": pid, "name": name, "team": team, "runs": 0, "wickets": 0,
                                               "catches": 0, "bat_pts": 0.0, "bowl_pts": 0.0, "field_pts": 0.0,
                                               "sr_bonus": 0.0, "econ_bonus": 0.0, "impact": 0.0})
    for b in batting:
        p = get(b["id"], b["team"], b["name"])
        p["runs"] = b["runs"]
        p["bat_pts"] = b["runs"]
        p["sr_bonus"] = 0.5 * (b["runs"] - b["balls"] * rate)
    for w in bowling:
        p = get(w["id"], w["team"], w["name"])
        p["wickets"] = w["wickets"]
        p["bowl_pts"] = 25 * w["wickets"]
        p["econ_bonus"] = 0.5 * (w["balls"] * rate - w["runs"])
    for f in fielding:
        p = get(f["id"], f["team"], f["name"])
        p["catches"] = f["catches"] + f["stumpings"]
        p["field_pts"] = 5 * p["catches"]
    team_of_id = {(pid, t) for (pid, t) in people}
    for c in cards:
        teams = {p["id"]: t for t, xi in match_players(c).items() for p in xi}
        for pid, v in (c.get("impact") or {}).items():
            t = teams.get(pid)
            if t and (pid, t) in team_of_id:
                people[(pid, t)]["impact"] += v
    out_bal, out_off = [], []
    for p in people.values():
        p["win_pts"] = 25 * team_wins.get(p["team"], 0)
        p["balanced"] = round(p["bat_pts"] + p["bowl_pts"] + p["field_pts"] + p["win_pts"] + p["sr_bonus"]
                              + p["econ_bonus"], 1)
        p["impact"] = round(p["impact"], 3)
        for k in ("sr_bonus", "econ_bonus"):
            p[k] = round(p[k], 1)
        out_bal.append(p)
    out_off = sorted(out_bal, key=lambda p: -p["impact"])
    out_bal = sorted(out_bal, key=lambda p: -p["balanced"])
    return {"official": [dict(p, rank=i) for i, p in enumerate(out_off, 1)],
            "balanced": [dict(p, rank=i) for i, p in enumerate(out_bal, 1)]}


def _wins(cards: list[dict]) -> dict:
    w: dict = {}
    for c in cards:
        if c["result"].get("winner"):
            w[c["result"]["winner"]] = w.get(c["result"]["winner"], 0) + 1
    return w


def _summary_card(c: dict) -> dict:
    """Short line per match for listings."""
    return {"match_no": c["match_no"], "stage": c["stage"], "teams": c["teams"], "venue": c.get("venue"),
            "scores": [f"{i['team']} {i['runs']}/{i['wickets']} ({i['overs']})" for i in c["innings"]],
            "result": c["result"]["text"], "player_of_match": (c.get("player_of_match") or {}).get("name")}


# ------------------------------------------------------------------------------------------------ series

def play_series(team_a: dict, team_b: dict, n: int = 3, fmt: str = "t20", comp: str | None = None,
                year: int = 2025, venues: list | None = None, seed: int | None = None, on_match=None,
                rain: bool = False, control: dict | None = None, skill: dict | None = None,
                best_of: bool = False) -> dict:
    """Bilateral series of n matches. All n are played, unless best_of: then it stops as soon as one side can no
    longer be caught (2-0 in a best of 3). control, skill: as in play_tournament."""
    a, b = team_spec(fmt, team_a), team_spec(fmt, team_b)
    run = _Runner(fmt, comp, year, seed, venues, None, None, rain, control, skill)
    run.on_match = on_match
    for i in range(n):
        run.play(a, b, f"Match {i + 1}")
        w = _wins(run.cards)
        if best_of and abs(w.get(a["name"], 0) - w.get(b["name"], 0)) > n - i - 1:
            break
    wins = _wins(run.cards)
    wa, wb = wins.get(a["name"], 0), wins.get(b["name"], 0)
    text = (f"{a['name']} won the series {wa}-{wb}" if wa > wb else f"{b['name']} won the series {wb}-{wa}"
            if wb > wa else f"Series drawn {wa}-{wb}")
    if n == 1:                                   # a single match: its own result, not "won the series 1-0"
        text = run.cards[0]["result"]["text"]
    stats = tournament_stats(run.cards, wins)
    pos = stats["mvp"]["official"][0] if stats["mvp"]["official"] else None
    return {"kind": "series", "format": fmt, "competition": run.comp, "year": year, "seed": run.seed,
            "teams": [a["name"], b["name"]], "score": {a["name"]: wa, b["name"]: wb}, "result": text,
            "winner": a["name"] if wa > wb else b["name"] if wb > wa else None,
            "player_of_series": pos, "fixtures": [_summary_card(c) for c in run.cards],
            "matches": run.cards, "best_of": n if best_of else None, **stats}


# ------------------------------------------------------------------------------------------------ tournament

# Qualifiers each knockout needs in total (the default `advance` per group is this divided by the number of groups).
KO_NEED = {"semis": 4, "ipl": 4, "final": 2, "qf": 8, "pre_qf": 10, "super_league": 8, "super_league_semis": 8}
PLATE_KNOCKOUTS = ("final", "semis", "none")


def _group_lists(names: list[str], groups) -> list[list[str]]:
    if groups in (None, 1):
        return [list(names)]
    if isinstance(groups, int):
        return [list(names[g::groups]) for g in range(groups)]
    return [list(g) for g in groups]


def _labels(n: int, prefix: str = "") -> list[str]:
    if n == 1:
        return [prefix or "League"]
    return [f"{prefix} {chr(ord('A') + i)}".strip() for i in range(n)]


def _per_group(advance, need: int, n_groups: int) -> list[int]:
    """Qualifiers per group: `advance` as one number for every group, a list (one per group), or the default."""
    if isinstance(advance, (list, tuple)):
        if len(advance) != n_groups:
            raise ValueError(f"advance has {len(advance)} entries for {n_groups} groups")
        return [int(k) for k in advance]
    return [advance or max(1, need // n_groups)] * n_groups


def _seeded(tables: dict, labels: list[str], per: list[int]) -> list[tuple[str, str]]:
    """Qualifiers as (team, group) ranked across groups: group position first (every group winner before any
    runner-up), then points, net run rate and name. With one group this is just the table order."""
    rows = [(r, label) for label, k in zip(labels, per) for r in tables[label][:k]]
    rows.sort(key=lambda x: (x[0]["pos"], -x[0]["points"], -x[0]["nrr"], x[0]["team"]))
    return [(r["team"], label) for r, label in rows]


def _pairs(seeds: list[tuple[str, str]], plan: list[tuple[int, int]]) -> list[tuple[str, str]]:
    """Ties from seed positions (plan: (higher, lower) index pairs, e.g. 1v8, 4v5, 2v7, 3v6), with the lower seeds
    rearranged as little as possible so that no tie is between two sides from the same group."""
    lows = [b for _, b in plan]
    best = None
    for perm in itertools.permutations(lows):
        clash = sum(seeds[a][1] == seeds[b][1] for (a, _), b in zip(plan, perm))
        cost = (clash, sum(abs(b - b0) for b, b0 in zip(perm, lows)))
        if best is None or cost < best[0]:
            best = (cost, perm)
    return [(seeds[a][0], seeds[b][0]) for (a, _), b in zip(plan, best[1])]


def _split_two(seeds: list[tuple[str, str]]) -> tuple[list[str], list[str]]:
    """Two Super League groups from ranked qualifiers: snake seeding (1, 4, 5, 8 | 2, 3, 6, 7), changed as little as
    possible so that sides from the same group are kept apart."""
    n = len(seeds)
    snake = {i for i in range(n) if i % 4 in (0, 3)}
    best = None
    for a in itertools.combinations(range(n), (n + 1) // 2):
        if 0 not in a:                       # the top seed heads group A
            continue
        sa = set(a)
        sb = set(range(n)) - sa
        clash = sum(seeds[i][1] == seeds[j][1]
                    for part in (sa, sb) for i, j in itertools.combinations(sorted(part), 2))
        cost = (clash, len(sa ^ snake))
        if best is None or cost < best[0]:
            best = (cost, sa)
    sa = best[1]
    return [seeds[i][0] for i in sorted(sa)], [seeds[i][0] for i in range(n) if i not in sa]


def _round_robin(run: "_Runner", by_name: dict, labels: list[str], group_lists: list[list[str]], rounds: int,
                 stage_of) -> None:
    """Rounds of single round robins. Within a round each side is at home in about half its games (pair i, j: the
    first at home when i + j is odd); the next round swaps every pairing."""
    for rnd in range(rounds):
        for label, names in zip(labels, group_lists):
            for (i, x), (j, y) in itertools.combinations(enumerate(names), 2):
                home, away = (x, y) if ((i + j) % 2 == 1) == (rnd % 2 == 0) else (y, x)
                run.play(by_name[home], by_name[away], stage_of(label))


def _tables(cards: list[dict], labels: list[str], group_lists: list[list[str]], win_points: int) -> dict:
    return {label: points_table([c for c in cards if set(c["teams"]) <= set(names)], names, win_points)
            for label, names in zip(labels, group_lists)}


def _knockouts(run: "_Runner", by_name: dict, tables: dict, labels: list[str], knockout: str, advance,
               win_points: int, ko: list, extra: list[str] | None = None, prefix: str = "") -> dict:
    """Plays the knockout stage after a league stage; returns champion, runner-up and any Super League tables.
    extra: qualifiers from elsewhere (the Plate), seeded below everyone from these groups. prefix names the stages
    ("Plate" -> "Plate final")."""
    extra = list(extra or [])

    def name(stage: str) -> str:
        return f"{prefix} {stage[0].lower()}{stage[1:]}" if prefix else stage

    def ko_match(t1: str, t2: str, stage: str) -> tuple[str, str]:
        c = run.play(by_name[t1], by_name[t2], name(stage), knockout=True)
        w, l = c["result"]["winner"], c["result"]["loser"]
        ko.append({"stage": name(stage), "match_no": c["match_no"], "teams": [t1, t2], "winner": w,
                   "result": c["result"]["text"]})
        return w, l

    out = {"champion": None, "runner_up": None, "super_league": {}}
    if knockout == "none":
        top = tables[labels[0]]
        out["champion"] = top[0]["team"]
        out["runner_up"] = top[1]["team"] if len(top) > 1 else None
        return out
    need = KO_NEED[knockout]
    if knockout == "ipl" and len(labels) != 1:
        raise ValueError("IPL-style playoffs need a single league")
    per = _per_group(advance, need, len(labels))

    if knockout in ("final", "semis", "ipl"):           # the original brackets, unchanged
        q = {label: [r["team"] for r in tables[label][:k]] for label, k in zip(labels, per)}
        if knockout == "final":
            f1, f2 = (q[labels[0]][0], q[labels[0]][1]) if len(labels) == 1 else (q[labels[0]][0], q[labels[1]][0])
            out["champion"], out["runner_up"] = ko_match(f1, f2, "Final")
        elif knockout == "semis":
            if len(labels) == 1:
                s = q[labels[0]]
                pairs = [(s[0], s[3]), (s[1], s[2])]
            elif len(labels) == 2:
                A, B = q[labels[0]], q[labels[1]]
                pairs = [(A[0], B[1]), (B[0], A[1])]
            else:
                # more groups: rank the qualifiers by their group standing, then points and NRR
                allq = sorted((r for label, k in zip(labels, per) for r in tables[label][:k]),
                              key=lambda r: (r["pos"], -r["points"], -r["nrr"]))
                s = [r["team"] for r in allq[:4]]
                pairs = [(s[0], s[3]), (s[1], s[2])]
            w1, _ = ko_match(*pairs[0], "Semi-final 1")
            w2, _ = ko_match(*pairs[1], "Semi-final 2")
            out["champion"], out["runner_up"] = ko_match(w1, w2, "Final")
        else:  # ipl
            s = q[labels[0]]
            w_q1, l_q1 = ko_match(s[0], s[1], "Qualifier 1")
            w_el, _ = ko_match(s[2], s[3], "Eliminator")
            w_q2, _ = ko_match(l_q1, w_el, "Qualifier 2")
            out["champion"], out["runner_up"] = ko_match(w_q1, w_q2, "Final")
        return out

    seeds = _seeded(tables, labels, per)
    plate_seeds = [(t, "Plate") for t in extra]
    if knockout in ("qf", "pre_qf"):
        if knockout == "qf":
            slots = need - len(plate_seeds)
            if len(seeds) < slots:
                raise ValueError(f"qf needs {need} qualifiers, got {len(seeds) + len(plate_seeds)}")
            seeds = seeds[:slots] + plate_seeds
        else:
            seeds = seeds + plate_seeds
            if not 9 <= len(seeds) <= 16:
                raise ValueError(f"pre_qf needs 9-16 qualifiers, got {len(seeds)}")
        rank = {t: i for i, (t, _) in enumerate(seeds)}
        if knockout == "pre_qf":
            # q qualifiers: the top 16 - q go straight through; the rest play q - 8 preliminary quarter-finals,
            # highest v lowest (10: 7v10, 8v9; 11: 6v11, 7v10, 8v9), the winner taking the higher seed's place
            n_pre = len(seeds) - 8
            d = 8 - n_pre
            group_of = dict(seeds)
            prelim = _pairs(seeds[d:], [(i, 2 * n_pre - 1 - i) for i in range(n_pre)])
            for i, (a, b) in enumerate(prelim):
                w, _ = ko_match(a, b, f"Preliminary quarter-final {i + 1}")
                seeds[d + i] = (w, group_of[w])
                rank[w] = d + i
            seeds = seeds[:8]
        qf = _pairs(seeds, [(0, 7), (3, 4), (1, 6), (2, 5)])
        w = [ko_match(a, b, f"Quarter-final {i + 1}")[0] for i, (a, b) in enumerate(qf)]

        def tie(x: str, y: str) -> tuple[str, str]:      # the higher seed is named first (washout tie-break)
            return (x, y) if rank[x] <= rank[y] else (y, x)
        w1, _ = ko_match(*tie(w[0], w[1]), "Semi-final 1")
        w2, _ = ko_match(*tie(w[2], w[3]), "Semi-final 2")
        out["champion"], out["runner_up"] = ko_match(*tie(w1, w2), "Final")
        return out

    # Super League: two round-robin groups of the qualifiers, then the final (or semis + final)
    seeds = seeds + plate_seeds
    min_q = 4 if knockout == "super_league_semis" else 2
    if len(seeds) < min_q:
        raise ValueError(f"{knockout} needs at least {min_q} qualifiers")
    sl_lists = list(_split_two(seeds))
    sl_labels = ["Super League A", "Super League B"]
    start = len(run.cards)
    _round_robin(run, by_name, sl_labels, sl_lists, 1, lambda label: label)
    sl_tables = _tables(run.cards[start:], sl_labels, sl_lists, win_points)
    out["super_league"] = sl_tables
    A, B = (sl_tables[x] for x in sl_labels)
    if knockout == "super_league":
        a, b = A[0], B[0]
        f1, f2 = (a, b) if (-a["points"], -a["nrr"]) <= (-b["points"], -b["nrr"]) else (b, a)
        out["champion"], out["runner_up"] = ko_match(f1["team"], f2["team"], "Final")
    else:
        w1, _ = ko_match(A[0]["team"], B[1]["team"], "Semi-final 1")
        w2, _ = ko_match(B[0]["team"], A[1]["team"], "Semi-final 2")
        out["champion"], out["runner_up"] = ko_match(w1, w2, "Final")
    return out


def play_tournament(teams: list[dict], fmt: str = "t20", comp: str | None = None, year: int = 2025,
                    rounds: int = 1, groups: int | list | None = None, advance: int | list | None = None,
                    knockout: str = "semis", venues: list | None = None, home_venues: dict | None = None,
                    knockout_venues: list | None = None, seed: int | None = None, win_points: int = 2,
                    on_match=None, rain: bool = False, control: dict | None = None,
                    skill: dict | None = None, plate: dict | None = None) -> dict:
    """League stage (round robin, `rounds` times, optionally in groups) then knockouts.

    groups:   None/1 = one league; an int = that many groups, teams dealt in the order given (1st to group A,
              2nd to B, ...); or explicit lists of team names.
    advance:  qualifiers per group (a number, or a list with one per group); default: what the knockout needs
              divided by the number of groups.
    knockout: "semis" (1v4, 2v3; with two groups A1vB2, B1vA2), "ipl" (qualifier 1, eliminator, qualifier 2,
              final), "final" (top two), "qf" (8 qualifiers: quarter-finals 1v8, 4v5, 2v7, 3v6, then semis and
              final), "pre_qf" (9-16 qualifiers, 10 by default: the lowest 2 x (q - 8) seeds play q - 8
              preliminary quarter-finals for the last places; 10 -> 7v10, 8v9), "super_league" (the qualifiers
              play two round-robin groups; the group winners meet in the final), "super_league_semis" (the same,
              then A1vB2, B1vA2 and the final), or "none".
              For the last four, qualifiers from several groups are ranked by group position, then points and NRR
              (every group winner before any runner-up), and ties keep sides from the same group apart where they
              can.
    win_points: points for a win (a tie or no result gets half); 4 for India's domestic cups.
    plate:    a second division played in the same run: {"teams": [team dicts], "rounds": 1, "groups": None,
              "knockout": "final" | "semis" | "none", "advance": 0}. advance: how many of its top sides (league
              table) join this knockout, seeded last. The result then has "plate" (its tables, knockouts, winner),
              "promoted" (the Plate winner) and "relegated" (the lowest side of all groups, by points then NRR).
    control:  {team name: engine.control.Controller} for sides a person captains (their decisions are asked).
    skill:    {team name: "expert" | "average" | "easy"} for computer captains (engine/judge.py; default expert).
    """
    if knockout not in KNOCKOUTS:
        raise ValueError(f"knockout must be one of {KNOCKOUTS}")
    plate = dict(plate) if plate else None
    if plate and plate.get("knockout", "final") not in PLATE_KNOCKOUTS:
        raise ValueError(f"plate knockout must be one of {PLATE_KNOCKOUTS}")
    specs = [team_spec(fmt, t) for t in teams]
    plate_specs = [team_spec(fmt, t) for t in plate["teams"]] if plate else []
    by_name = {t["name"]: t for t in specs + plate_specs}
    if len(by_name) != len(specs) + len(plate_specs):
        raise ValueError("team names must be unique")
    group_lists = _group_lists([t["name"] for t in specs], groups)
    labels = _labels(len(group_lists))
    run = _Runner(fmt, comp, year, seed, venues, home_venues, knockout_venues, rain, control, skill)
    run.on_match = on_match

    _round_robin(run, by_name, labels, group_lists, rounds,
                 lambda label: "League" if label == "League" else f"Group {label}")
    tables = _tables(list(run.cards), labels, group_lists, win_points)

    ko: list = []
    plate_out = None
    plate_q: list[str] = []
    if plate:
        p_lists = _group_lists([t["name"] for t in plate_specs], plate.get("groups"))
        p_labels = _labels(len(p_lists), "Plate")
        start = len(run.cards)
        _round_robin(run, by_name, p_labels, p_lists, plate.get("rounds", rounds),
                     lambda label: label if label == "Plate" else f"Plate group {label[-1]}")
        p_tables = _tables(run.cards[start:], p_labels, p_lists, win_points)
        n_up = int(plate.get("advance") or 0)
        if n_up:
            plate_q = [t for t, _ in _seeded(p_tables, p_labels, [n_up] * len(p_labels))][:n_up]
        p_ko: list = []
        p_res = _knockouts(run, by_name, p_tables, p_labels, plate.get("knockout", "final"), None, win_points,
                           p_ko, prefix="Plate")
        plate_out = {"teams": [t["name"] for t in plate_specs], "groups": dict(zip(p_labels, p_lists)),
                     "tables": p_tables, "knockouts": p_ko, "winner": p_res["champion"],
                     "runner_up": p_res["runner_up"], "to_elite_knockouts": plate_q}
        ko.extend(p_ko)

    res = _knockouts(run, by_name, tables, labels, knockout, advance, win_points, ko, extra=plate_q)
    stats = tournament_stats(run.cards, _wins(run.cards))
    pos = stats["mvp"]["official"][0] if stats["mvp"]["official"] else None
    out = {"kind": "tournament", "format": fmt, "competition": run.comp, "year": year, "seed": run.seed,
           "settings": {"rounds": rounds, "groups": dict(zip(labels, group_lists)), "knockout": knockout,
                        "win_points": win_points, "advance": advance},
           "teams": [t["name"] for t in specs], "tables": tables, "knockouts": ko,
           "super_league": res["super_league"],
           "winner": res["champion"], "runner_up": res["runner_up"], "player_of_series": pos,
           "fixtures": [_summary_card(c) for c in run.cards], "matches": run.cards, **stats}
    if plate:
        worst = min((r for rows in tables.values() for r in rows), key=lambda r: (r["points"], r["nrr"], r["team"]))
        out.update(plate=plate_out, promoted=plate_out["winner"], relegated=worst["team"])
    return out


# ------------------------------------------------------------------------------------------------ output

def match_count(n_teams: int, rounds: int = 1, groups: int | list | None = None, knockout: str = "semis",
                advance: int | list | None = None, plate: dict | None = None) -> int:
    """How many matches play_tournament will play (for progress bars). plate: as in play_tournament ("teams" may
    also be a number)."""
    if groups in (None, 1):
        sizes = [n_teams]
    elif isinstance(groups, int):
        sizes = [len(range(g, n_teams, groups)) for g in range(groups)]
    else:
        sizes = [len(g) for g in groups]
    league = rounds * sum(k * (k - 1) // 2 for k in sizes)
    if knockout in ("super_league", "super_league_semis"):
        q = sum(_per_group(advance, KO_NEED[knockout], len(sizes))) + int((plate or {}).get("advance") or 0)
        a, b = (q + 1) // 2, q // 2
        ko = a * (a - 1) // 2 + b * (b - 1) // 2 + (1 if knockout == "super_league" else 3)
    else:
        ko = {"semis": 3, "ipl": 4, "final": 1, "qf": 7, "none": 0}.get(knockout, 0)
        if knockout == "pre_qf":
            q = sum(_per_group(advance, KO_NEED[knockout], len(sizes))) + int((plate or {}).get("advance") or 0)
            ko = 7 + q - 8
    if plate:
        pt = plate["teams"]
        ko += match_count(pt if isinstance(pt, int) else len(pt), plate.get("rounds", rounds), plate.get("groups"),
                          plate.get("knockout", "final"))
    return league + ko


def save(result: dict, out_dir: str | Path) -> Path:
    """summary.json (everything except full scorecards), matches/NNN.json (full scorecard) and NNN.txt (text)."""
    out = Path(out_dir)
    (out / "matches").mkdir(parents=True, exist_ok=True)
    for c in result["matches"]:
        stem = f"{c['match_no']:03d}"
        (out / "matches" / f"{stem}.json").write_text(json.dumps(c, ensure_ascii=False, indent=1), encoding="utf-8")
        (out / "matches" / f"{stem}.txt").write_text(f"{c['stage']}\n" + full_text(c), encoding="utf-8")
    summary = {k: v for k, v in result.items() if k != "matches"}
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def summary_text(res: dict, top: int = 5) -> str:
    lines = []
    if res["kind"] == "series":
        lines.append(f"{' v '.join(res['teams'])} - {res['result']}")
    else:
        tables = [(label if label == "League" else "Group " + label, rows) for label, rows in res["tables"].items()]
        tables += list((res.get("super_league") or {}).items())
        tables += list(((res.get("plate") or {}).get("tables") or {}).items())
        for label, rows in tables:
            lines.append(f"\n{label}")
            lines.append(f"  {'#':>2} {'Team':24} {'P':>3} {'W':>3} {'L':>3} {'T':>3} {'Pts':>4} {'NRR':>7}")
            for r in rows:
                lines.append(f"  {r['pos']:>2} {r['team']:24} {r['played']:>3} {r['won']:>3} {r['lost']:>3} "
                             f"{r['tied']:>3} {r['points']:>4} {r['nrr']:>+7.3f}")
        if res["knockouts"]:
            lines.append("\nKnockouts")
            for k in res["knockouts"]:
                lines.append(f"  {k['stage']:14} {k['result']}")
        lines.append(f"\nWinner: {res['winner']}   Runner-up: {res['runner_up']}")
        if res.get("plate"):
            lines.append(f"Plate winner: {res['plate']['winner']} (promoted)   Relegated: {res['relegated']}")
    pos = res.get("player_of_series")
    if pos:
        lines.append(f"Player of the series: {pos['name']} ({pos['team']}) - {pos['runs']} runs, "
                     f"{pos['wickets']} wkts, impact {pos['impact']:+.2f} wins")
    lines.append("\nMost runs:    " + ", ".join(f"{b['name']} {b['runs']}" for b in res["batting"][:top]))
    lines.append("Most wickets: " + ", ".join(f"{w['name']} {w['wickets']}" for w in res["bowling"][:top]))
    lines.append("Balanced MVP: " + ", ".join(f"{p['name']} {p['balanced']:.0f}" for p in res["mvp"]["balanced"][:top]))
    return "\n".join(lines)


def run_config(cfg: dict) -> dict:
    kind = cfg.get("type", "tournament")
    common = {k: cfg[k] for k in ("fmt", "comp", "year", "seed", "venues") if k in cfg}
    if "format" in cfg:
        common["fmt"] = cfg["format"]
    if kind == "series":
        a, b = cfg["teams"]
        return play_series(a, b, n=cfg.get("matches", 3), **common)
    extra = {k: cfg[k] for k in ("rounds", "groups", "advance", "knockout", "home_venues", "knockout_venues",
                                 "win_points", "plate") if k in cfg}
    return play_tournament(cfg["teams"], **common, **extra)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("config", help="JSON config (see examples/)")
    ap.add_argument("--out", help="folder for summary.json and match scorecards")
    ap.add_argument("--seed", type=int, help="override the config's seed")
    args = ap.parse_args(argv)
    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    if args.seed is not None:
        cfg["seed"] = args.seed
    res = run_config(cfg)
    print(summary_text(res))
    if args.out:
        print(f"\nwrote {save(res, args.out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
