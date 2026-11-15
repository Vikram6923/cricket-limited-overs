"""Records over a set of Tests (docs/test_match_plan.md section 5), read from the scorecards.

    from engine.test_records import test_records
    rec = test_records(cards)

The limited-overs records that also mean something in a Test (highest and lowest totals, top scores, best innings
figures, fastest fifties and hundreds, wins by runs) come from engine/tournament.py; the rest are a Test's own.
Every row carries "match_no" and "stage" so the page can open the match.
"""
from __future__ import annotations

from .tournament import records as base_records

SHARED = ("highest_totals", "lowest_all_out", "highest_scores", "best_bowling", "fastest_fifties",
          "fastest_hundreds", "biggest_wins_by_runs", "narrowest_wins_by_runs")


def test_records(cards: list[dict], n: int = 10) -> dict:
    rec = {k: v for k, v in base_records(cards, n).items() if k in SHARED}
    scores, match_figs, chases, hat, carried, twin = [], [], [], [], [], []
    pships: dict = {}
    wins = {"innings": [], "wickets": []}
    for c in cards:
        tag = {"match_no": c["match_no"], "stage": c["stage"]}
        figs: dict = {}
        tons: dict = {}
        for i in c["innings"]:
            for b in i["batting"]:
                if not b["batted"]:
                    continue
                row = {**tag, "name": b["name"], "team": i["team"], "vs": i["bowling_team"], "runs": b["runs"],
                       "balls": b["balls"], "not_out": not b["out"], "fours": b["fours"], "sixes": b["sixes"]}
                scores.append(row)
                if b["runs"] >= 100:
                    tons.setdefault((b["id"], i["team"]), []).append(row)
                # carrying the bat: an opener not out when the side is bowled out
                if b["position"] <= 2 and not b["out"] and i.get("ended") == "all out" and i["wickets"] >= 10:
                    carried.append({**row, "total": i["runs"]})
            for w in i["bowling"]:
                f = figs.setdefault((w["id"], i["bowling_team"]),
                                    {**tag, "name": w["name"], "team": i["bowling_team"], "vs": i["team"],
                                     "wickets": 0, "runs": 0, "innings": []})
                f["wickets"] += w["wickets"]
                f["runs"] += w["runs"]
                f["innings"].append(f"{w['wickets']}/{w['runs']}")
            for p in i["partnerships"]:
                row = {**tag, "wkt": p["wkt"], "runs": p["runs"], "balls": p["balls"], "batters": p["batters"],
                       "team": i["team"], "vs": i["bowling_team"], "unbroken": bool(p.get("unbroken"))}
                best = pships.get(p["wkt"])
                if best is None or row["runs"] > best["runs"]:
                    pships[p["wkt"]] = row
            if i.get("ended") == "target":
                chases.append({**tag, "team": i["team"], "vs": i["bowling_team"], "runs": i["runs"],
                               "wickets": i["wickets"], "target": i["target"]})
        match_figs.extend(figs.values())
        for rows in tons.values():
            if len(rows) >= 2:
                twin.append({**tag, "name": rows[0]["name"], "team": rows[0]["team"], "vs": rows[0]["vs"],
                             "scores": [f"{r['runs']}{'*' if r['not_out'] else ''}" for r in rows]})
        for e in c["events"]:
            if e.get("kind") == "hat_trick":
                inn = c["innings"][e["innings"] - 1]
                hat.append({**tag, "name": e["text"].removeprefix("Hat-trick for ").rstrip("!"),
                            "team": inn["bowling_team"], "vs": inn["team"], "over": e.get("over")})
        r = c["result"]
        if r.get("by") in wins:
            wins[r["by"]].append({**tag, "winner": r["winner"], "loser": r["loser"], "margin": r["margin"],
                                  "text": r["text"]})
    tons_all = sorted((s for s in scores if s["runs"] >= 100), key=lambda x: (-x["runs"], x["balls"]))
    match_figs.sort(key=lambda x: (-x["wickets"], x["runs"]))
    rec.update({
        "hundreds": {"hundreds": len(tons_all), "doubles": sum(s["runs"] >= 200 for s in tons_all),
                     "triples": sum(s["runs"] >= 300 for s in tons_all), "list": tons_all[:n]},
        "longest_innings": sorted(scores, key=lambda x: (-x["balls"], -x["runs"]))[:n],
        "carried_bat": sorted(carried, key=lambda x: -x["runs"])[:n],
        "hundred_in_each_innings": twin[:n],
        "best_match_bowling": match_figs[:n],
        "ten_wicket_matches": [f for f in match_figs if f["wickets"] >= 10][:n],
        "hat_tricks": hat[:n],
        "best_partnerships": [pships[w] for w in sorted(pships)],
        "highest_successful_chases": sorted(chases, key=lambda x: -x["runs"])[:n],
        "biggest_wins_by_an_innings": sorted(wins["innings"], key=lambda x: -x["margin"])[:n],
        "biggest_wins_by_wickets": sorted(wins["wickets"], key=lambda x: -x["margin"])[:n],
        "narrowest_wins_by_wickets": sorted(wins["wickets"], key=lambda x: x["margin"])[:n],
    })
    return rec


test_records.__test__ = False          # not a test (the name starts with test_)
