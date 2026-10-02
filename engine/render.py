"""Text scorecard and match report from a scorecard dict (design T0-4; narrative ported in spirit from the Test
sim's matchreport / innings.report / bowling.report)."""
from __future__ import annotations

import random


def scorecard_text(card: dict) -> str:
    out = []
    t = card["teams"]
    venue = f" at {card['venue']}" if card.get("venue") else ""
    out.append(f"{t[0]} v {t[1]}{venue} - {card['format'].upper()}, {card['competition']} {card['year']} "
               f"(seed {card['seed']})")
    out.append(f"Toss: {card['toss']['winner']}, chose to {card['toss']['decision']}. "
               f"Pitch: {card.get('conditions', {}).get('report', 'n/a')}.")
    for inn in card["innings"] + card.get("super_overs", []):
        out.append("")
        head = inn["team"] + (f"  (target {inn['target']})" if inn.get("target") else "")
        if inn["number"] > 100:
            head = f"Super over: {inn['team']}"
        out.append(head)
        for b in inn["batting"]:
            if not b["batted"]:
                continue
            mark = ("*" if b.get("captain") else "") + ("†" if b.get("keeper") else "")
            name = f"{b['name']} {mark}".strip()
            sr = f"{100 * b['runs'] / b['balls']:.1f}" if b["balls"] else "-"
            out.append(f"  {name:24} {b['dismissal']:38} {b['runs']:>4}{'' if b['out'] else '*':1} "
                       f"({b['balls']:>3})  {b['fours']:>2}x4 {b['sixes']:>2}x6  SR {sr}")
        ex = inn["extras"]
        out.append(f"  {'Extras':24} (b {ex['b']}, lb {ex['lb']}, w {ex['w']}, nb {ex['nb']}){sum(ex.values()):>23}")
        rr = 6 * inn["runs"] / inn["balls"] if inn["balls"] else 0
        wk = "all out" if inn["wickets"] >= 10 else f"{inn['wickets']} wkts"
        out.append(f"  {'TOTAL':24} ({wk}, {inn['overs']} ov, RR {rr:.2f}){inn['runs']:>27}")
        dnb = [b["name"] for b in inn["batting"] if not b["batted"]]
        if dnb:
            out.append(f"  Did not bat: {', '.join(dnb)}")
        if inn["fall_of_wickets"]:
            out.append("  Fall of wickets: " + ", ".join(f"{f['wkt']}-{f['runs']} ({f['batter']}, {f['over']} ov)"
                                                         for f in inn["fall_of_wickets"]))
        out.append(f"  {'Bowling':24} {'O':>5} {'M':>3} {'R':>4} {'W':>3} {'Econ':>6}  {'0s':>3} {'4s':>3} {'6s':>3}  extras")
        for w in inn["bowling"]:
            e = f"{w['economy']:.2f}" if w["economy"] is not None else "-"
            xtra = ", ".join(x for x in (f"{w['wides']}w" if w["wides"] else "", f"{w['noballs']}nb" if w["noballs"] else "") if x)
            out.append(f"  {w['name']:24} {w['overs']:>5} {w['maidens']:>3} {w['runs']:>4} {w['wickets']:>3} {e:>6}  "
                       f"{w['dots']:>3} {w['fours']:>3} {w['sixes']:>3}  {xtra}")
    out.append("")
    out.append(f"Result: {card['result']['text']}")
    pom = card.get("player_of_match") or {}
    if pom:
        out.append(f"Player of the match: {pom['name']} ({pom['team']})")
    if card.get("turning_point"):
        out.append(card["turning_point"]["text"])
    return "\n".join(out)


def _bat_line(b: dict, rng: random.Random) -> str:
    sr = 100 * b["runs"] / b["balls"] if b["balls"] else 0
    score = f"{b['runs']}{'' if b['out'] else '*'}"
    adj = []
    if b["runs"] >= 100:
        adj += ["superb", "brilliant", "match-winning", "magnificent"]
    if sr >= 180:
        adj += ["blistering", "explosive", "brutal"]
    elif sr >= 140:
        adj += ["brisk", "aggressive", "fluent"]
    elif sr < 90 and b["balls"] >= 30:
        adj += ["patient", "watchful", "gritty"]
    verbs = ["made", "scored", "struck"] + (["smashed", "blasted"] if sr >= 150 else [])
    if adj and rng.random() < 0.8:
        return f"{b['name']} {rng.choice(verbs)} a {rng.choice(adj)} {score} off {b['balls']} balls"
    return f"{b['name']} {rng.choice(verbs)} {score} ({b['balls']})"


def match_report(card: dict) -> str:
    rng = random.Random(card.get("seed", 0))
    i1, i2 = card["innings"][0], card["innings"][1]
    s = []
    venue = f"At {card['venue']}, " if card.get("venue") else ""
    toss = card["toss"]
    s.append(f"{venue}{toss['winner']} won the toss and chose to {toss['decision']} on "
             f"{card.get('conditions', {}).get('report', 'a fair pitch')}.")
    for inn, lead in ((i1, "Batting first,"), (i2, "In reply,")):
        wk = "all out for" if inn["wickets"] >= 10 else f"{inn['wickets']} down for" if inn["number"] == 2 else "made"
        tot = f"{inn['runs']}" if inn["wickets"] >= 10 or inn["number"] == 2 else f"{inn['runs']}/{inn['wickets']}"
        s.append(f"{lead} {inn['team']} {wk} {tot} in {inn['overs']} overs.")
        stars = sorted((b for b in inn["batting"] if b["batted"] and (b["runs"] >= 40 or
                        b["runs"] == max(x["runs"] for x in inn["batting"]))), key=lambda b: -b["runs"])[:2]
        if stars:
            s.append(" and ".join(_bat_line(b, rng) for b in stars) + ".")
        bw = sorted((w for w in inn["bowling"] if w["wickets"] >= 3 or (w["wickets"] >= 2 and w["economy"] and
                     w["economy"] < (6.5 if card["format"] == "t20" else 4.5))), key=lambda w: (-w["wickets"], w["runs"]))
        if bw:
            s.append("For " + inn["bowling_team"] + ", " + " and ".join(
                f"{w['name']} took {w['wickets']}-{w['runs']}" for w in bw[:2]) + ".")
    tp = card.get("turning_point")
    if tp:
        what = f"{tp['wickets']} wicket{'s' if tp['wickets'] != 1 else ''} for {tp['runs']}" if tp["wickets"] \
            else f"{tp['runs']} run{'s' if tp['runs'] != 1 else ''}"
        s.append(f"The turning point came in over {tp['over']} of the {tp['which']} innings, bowled by {tp['bowler']} "
                 f"({what}), which swung the match {tp['swing'] * 100:.0f}% towards {tp['towards']}.")
    for e in card["events"]:
        if e["kind"] == "hat_trick":
            s.append(e["text"])
    s.append(card["result"]["text"] + ".")
    pom = card.get("player_of_match") or {}
    if pom:
        s.append(f"{pom['name']} was named player of the match.")
    return " ".join(s)
