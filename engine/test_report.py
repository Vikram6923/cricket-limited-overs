"""The written report of a Test, day by day (in the spirit of the old Test sim's match report), and the
day-by-day strip the match centre shows.

    from engine.test_report import report, day_strip
"""
from __future__ import annotations

BREAK_NAMES = ("lunch", "tea", "stumps")
BIG_SCORE, BIG_HAUL = 50, 4            # what the report names: fifties and four-wicket hauls (wording, not behaviour)
RAIN_NOTED = 15                        # a day's lost overs are mentioned from here up


def _score(i: dict) -> str:
    return str(i["runs"]) if i["wickets"] >= 10 else f"{i['runs']}/{i['wickets']}"


def _stars(inn: dict) -> str:
    bats = sorted((b for b in inn["batting"] if b["batted"] and b["runs"] >= BIG_SCORE), key=lambda b: -b["runs"])[:2]
    bowl = sorted((w for w in inn["bowling"] if w["wickets"] >= BIG_HAUL), key=lambda w: (-w["wickets"], w["runs"]))[:2]
    parts = [f"{b['name']} {b['runs']}{'' if b['out'] else '*'}" for b in bats]
    parts += [f"{w['name']} {w['wickets']}/{w['runs']}" for w in bowl]
    return f" ({', '.join(parts)})" if parts else ""


def position(card: dict, upto: int, runs: int, wickets: int) -> str:
    """How the batting side of innings number `upto` (1-based) stands with its score at runs/wickets:
    "lead by 120", "trail by 135", "need 88 more", "scores level"."""
    inns = card["innings"]
    inn = inns[upto - 1]
    if inn.get("target"):
        need = inn["target"] - runs
        return f"need {need} more" if need > 0 else "target reached"
    if upto == 1:
        return ""
    mine = runs + sum(i["runs"] for i in inns[:upto - 1] if i["team"] == inn["team"])
    theirs = sum(i["runs"] for i in inns[:upto - 1] if i["team"] != inn["team"])
    d = mine - theirs
    return f"lead by {d}" if d > 0 else f"trail by {-d}" if d < 0 else "scores level"


def day_strip(card: dict) -> list[dict]:
    """One row per interval reached: {"day", "session" (1 lunch, 2 tea, 3 stumps), "label", "team", "score",
    "position", "innings"}, read from each innings' overs log (the score after the last over of the session)."""
    last: dict = {}
    for n, inn in enumerate(card["innings"], 1):
        for o in inn.get("overs_log") or []:
            if o.get("day"):
                last[(o["day"], o.get("session") or 3)] = (n, inn, o)
    days = {d["day"] for d in card.get("days") or []}
    final_day = max(days) if days else 0
    out = []
    for (day, ses), (n, inn, o) in sorted(last.items()):
        over = o is inn["overs_log"][-1] and n == len(card["innings"]) and day == final_day
        label = f"Day {day}, {'close' if over else BREAK_NAMES[min(ses, 3) - 1]}"
        out.append({"day": day, "session": ses, "label": label, "team": inn["team"], "innings": n,
                    "score": f"{o['total']}/{o['wickets']}" if o["wickets"] < 10 else str(o["total"]),
                    "position": card["result"]["text"] if over else position(card, n, o["total"], o["wickets"])})
    return out


def _innings_line(card: dict, n: int, inn: dict) -> str:
    how = inn.get("ended")
    team = inn["team"]
    if how == "declared":
        s = f"{team} declared at {_score(inn)}"
    elif how == "target":
        s = f"{team} reached their target of {inn['target']} for the loss of {inn['wickets']} wicket{'' if inn['wickets'] == 1 else 's'}"
    elif how == "all out":
        s = f"{team} were {'bowled out' if inn['runs'] >= 150 else 'skittled'} for {inn['runs']}"
        if inn.get("follow_on"):
            s = f"following on, {s}"
    else:
        return ""
    s += _stars(inn)
    pos = position(card, n, inn["runs"], inn["wickets"])
    if n < 4 and how != "target" and pos and not inn.get("target"):
        s += f", a {'lead' if pos.startswith('lead') else 'deficit'} of {pos.split()[-1]}" if pos != "scores level" \
            else ", the scores level"
    return s[0].upper() + s[1:] + "."


def report(card: dict) -> str:
    s = []
    if card.get("venue"):
        s.append(f"At {card['venue']}.")
    toss = card["toss"]
    s.append(f"{toss['winner']} won the toss and chose to {toss['decision']}.")
    rep = (card.get("conditions") or {}).get("report")
    if rep:
        s.append(f"The pitch was {rep}.")
    ended_on: dict = {}
    for n, inn in enumerate(card["innings"], 1):
        log = inn.get("overs_log") or []
        day = log[-1].get("day") if log else None
        ended_on.setdefault(day, []).append((n, inn))
    follow = {e.get("day"): e["text"] for e in card.get("events", []) if "the follow-on" in e.get("text", "")}
    days = card.get("days") or []
    lost_total = sum(d.get("lost", 0) for d in days)
    for d in days:
        bits = []
        if not d["overs"]:
            bits.append("No play was possible.")
        for n, inn in ended_on.get(d["day"], []):
            line = _innings_line(card, n, inn)
            if line:
                bits.append(line)
        if d["day"] in follow:
            bits.append(follow[d["day"]].rstrip(".") + ".")
        if d["overs"] and d.get("lost", 0) >= RAIN_NOTED:
            bits.append(f"{d['lost']} overs were lost.")
        if d is not days[-1] and d["overs"] and "/10" not in d["close"]:
            bits.append(f"At stumps {d['close']}.")      # the score and how the side stands
        if bits:
            s.append(f"Day {d['day']}: " + " ".join(bits))
    r = card["result"]
    if r["type"] == "draw":
        s.append("Match drawn" + (f", spoiled by the weather ({lost_total} overs lost)." if lost_total >= 90 else "."))
    else:
        s.append(r["text"] + ".")
    pom = card.get("player_of_match") or {}
    if pom.get("name"):
        s.append(f"The player of the match was {pom['name']} of {pom['team']}.")
    return " ".join(s)
