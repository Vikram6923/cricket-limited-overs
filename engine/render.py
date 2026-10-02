"""Text scorecard and match report from a scorecard dict (design T0-4; narrative ported in spirit from the Test
sim's matchreport / innings.report / bowling.report)."""
from __future__ import annotations

import random


def scorecard_text(card: dict) -> str:
    out = _header(card)
    for inn in card["innings"] + card.get("super_overs", []):
        out += _innings_card(inn)
    out += _footer(card)
    return "\n".join(out)


def _header(card: dict) -> list[str]:
    t = card["teams"]
    venue = f" at {card['venue']}" if card.get("venue") else ""
    out = [f"{t[0]} v {t[1]}{venue} - {card['format'].upper()}, {card['competition']} {card['year']} "
           f"(seed {card['seed']})"]
    for team, xi in (card.get("xi") or {}).items():
        out.append(f"{team}: " + ", ".join(f"{i} {p['name']}" for i, p in enumerate(xi, 1)))
    out.append(f"Toss: {card['toss']['winner']}, chose to {card['toss']['decision']}. "
               f"Pitch: {card.get('conditions', {}).get('report', 'n/a')}.")
    return out


def innings_log(card: dict, inn: dict) -> list[str]:
    """Ball-by-ball log of one innings, as in the Test sim's saved scorecards (over.ball in place of the clock)."""
    out = []
    for e in card["events"]:
        if e.get("innings") != inn["number"] or e["kind"] == "turning_point":
            continue
        out.append(f"  {e['over']:>5} ov  {inn['team']} {e['score']:<8} {e['text']}")
    return out


def _innings_card(inn: dict) -> list[str]:
    out = [""]
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
    return out


def _footer(card: dict) -> list[str]:
    out = [""]
    out.append(f"Result: {card['result']['text']}")
    pom = card.get("player_of_match") or {}
    if pom:
        figs = pom_figures(card)
        out.append(f"Player of the match: {pom['name']} ({pom['team']})" + (f" - {figs}" if figs else ""))
    if card.get("turning_point"):
        out.append(card["turning_point"]["text"])
    return out


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


def pom_figures(card: dict) -> str:
    """'60 off 45, 2-23' for the player of the match (super overs excluded)."""
    pom = card.get("player_of_match") or {}
    bits = []
    for inn in card["innings"]:
        for b in inn["batting"]:
            if b["id"] == pom.get("id") and b["batted"]:
                bits.append(f"{b['runs']}{'' if b['out'] else '*'} off {b['balls']}")
        for w in inn["bowling"]:
            if w["id"] == pom.get("id"):
                bits.append(f"{w['wickets']}-{w['runs']}")
    return ", ".join(bits)


def _score(inn: dict) -> str:
    return f"{inn['runs']}" if inn["wickets"] >= 10 else f"{inn['runs']}/{inn['wickets']}"


def _bowl_line(w: dict, rng: random.Random) -> str:
    """Ported from the Test sim's bowling.report: 'X bowled well, taking 4-23'."""
    adv = []
    if w["wickets"] >= 3:
        adv += ["well", "effectively", "smartly", "superbly"]
    if w["wickets"] >= 5:
        adv += ["beautifully", "wonderfully", "magnificently"]
    if w["economy"] is not None and w["balls"] >= 18 and w["economy"] < 5:
        adv += ["tightly", "with great control"]
    if not adv or rng.random() < 0.3:
        return f"{w['name']} took {w['wickets']}-{w['runs']}"
    verb = rng.choice(["bowled", "bowled", "worked", "ran in"])
    how = rng.choice(["taking", "finishing with", "with figures of", "for"])
    return f"{w['name']} {verb} {rng.choice(adv)}, {how} {w['wickets']}-{w['runs']}"


def _bat_report(b: dict, rng: random.Random) -> str:
    """Ported from the Test sim's innings.report, with limited-overs strike-rate bands."""
    score = f"{b['runs']}{'' if b['out'] else '*'}"
    if not b["out"] and b["runs"] % 100 > 90 and rng.random() < 1 / 3:
        return f"{b['name']} was stranded on {score}"
    if b["out"] and rng.random() < 0.25:
        kind = (b.get("how_out") or {}).get("kind", "")
        how = {"bowled": "bowled", "lbw": "LBW", "stumped": "stumped", "run_out": "run out"}.get(
            kind, "caught" if kind.startswith("caught") else "out")
        return f"{b['name']} was {how} for {score}"
    return _bat_line(b, rng)


def match_report(card: dict) -> str:
    """Narrative report in the style of the Test sim's matchreport."""
    rng = random.Random(card.get("seed", 0))
    i1, i2 = card["innings"][0], card["innings"][1]
    s = []
    if card.get("venue"):
        s.append(f"At {card['venue']}.")
    toss = card["toss"]
    capt = next((b["name"] for inn in card["innings"] for b in inn["batting"]
                 if b.get("captain") and inn["team"] == toss["winner"]), None)
    who = f"{capt} of {toss['winner']}" if capt else toss["winner"]
    choice = "batted first" if toss["decision"] == "bat" else "chose to field"
    s.append(f"{who} won the toss and {choice}.")
    verb = rng.choice(["appeared to be", "looked to be", "seemed", "was", "was described as being"])
    s.append(f"The pitch {verb} {card.get('conditions', {}).get('report', 'a fair pitch')}.")
    for inn, lead in ((i1, "In the first innings,"), (i2, "In reply,")):
        if inn["wickets"] >= 10 and inn["runs"] < (100 if card["format"] == "t20" else 150):
            lead = "Shockingly,"
        made = rng.choice(["scored", "made", "finished with", "totalled"])
        s.append(f"{lead} {inn['team']} {made} {_score(inn)} in {inn['overs']} overs.")
        best = max((b["runs"] for b in inn["batting"]), default=0)
        stars = sorted((b for b in inn["batting"] if b["batted"] and (b["runs"] >= 50 or b["runs"] == best)),
                       key=lambda b: -b["runs"])[:3]
        if stars:
            s.append(", ".join(_bat_report(b, rng) for b in stars) + ".")
        bw = sorted((w for w in inn["bowling"] if w["wickets"] >= 3), key=lambda w: (-w["wickets"], w["runs"]))
        if bw:
            s.append("For " + inn["bowling_team"] + ", " + " and ".join(_bowl_line(w, rng) for w in bw[:2]) + ".")
        if inn is i1:
            s.append(f"That set a target of {i1['runs'] + 1}.")
    tp = card.get("turning_point")
    if tp:
        what = (f"{tp['wickets']} wicket{'s' if tp['wickets'] != 1 else ''} for {tp['runs']}" if tp["wickets"]
                else f"{tp['runs']} run{'s' if tp['runs'] != 1 else ''}")
        s.append(f"The turning point came in over {tp['over']} of the {tp['which']} innings, bowled by {tp['bowler']} "
                 f"({what}), which swung the match {tp['swing'] * 100:.0f}% towards {tp['towards']}.")
    for e in card["events"]:
        if e["kind"] == "hat_trick":
            s.append(e["text"])
    r = card["result"]
    if r.get("by") == "super_over":
        s.append(f"The scores finished level at {i1['runs']}, and {r['winner']} won the super over.")
    elif r.get("winner"):
        w = i1 if i1["team"] == r["winner"] else i2
        l = i2 if w is i1 else i1
        margin = r["text"].split(" won by ", 1)[1]
        s.append(f"In the end, {w['team']} ({_score(w)}) beat {l['team']} ({_score(l)}) by {margin}.")
    pom = card.get("player_of_match") or {}
    if pom:
        figs = pom_figures(card)
        s.append(f"The player of the match was {pom['name']} of {pom['team']}" + (f" ({figs})." if figs else "."))
    return " ".join(s)


def full_text(card: dict) -> str:
    """As in the Test sim's saved scorecards: for each innings its ball-by-ball log, then its scorecard; then the
    result and the match report."""
    out = _header(card)
    for inn in card["innings"] + card.get("super_overs", []):
        label = "Super over log" if inn["number"] > 100 else "Innings log"
        out += ["", f"{label}: {inn['team']}"] + innings_log(card, inn)
        out += _innings_card(inn)
    out += _footer(card)
    return "\n".join(out) + "\n\nMatch Report: " + match_report(card) + "\n"
