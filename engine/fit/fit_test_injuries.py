"""How often is a Test player hurt, and what happens then? (data/engine/test_injuries.json)

Cricsheet shows an injury three ways: a batter "retired hurt", a player listed as absent hurt in an innings he
did not bat in, and a replacement for the rest of the match (a concussion substitute, since 2019). Counted:

- retire:   retirements hurt per legal ball, and of those the share who came back in the same innings, and of
            the rest the share who batted or bowled again later in the match;
- field:    players absent hurt who had not retired hurt in that match (hurt in the field or bowling), per
            legal ball; they take no further part;
- replaced: of the players lost for the match since SUBS_FROM, the share for whom a replacement came in.

An injury that did not stop a player batting (a bowler who breaks down but bats at eleven, a batter who plays
on) cannot be seen, so the rates are low readings of how often players are hurt.

Run:  python -m engine.fit.fit_test_injuries
"""
from __future__ import annotations

import json
import sys

from . import fit_test_situation as fts

SUBS_FROM = 2019             # like-for-like replacements came into the playing conditions in August 2019


def fit() -> dict:
    balls = retired = back_innings = back_match = absent = 0
    lost_since = repl_since = 0
    for m in fts.iter_tests():
        year = int(str(m["info"]["dates"][0])[:4])
        inns = m.get("innings", [])
        hurt_in_match = set()
        seen_after: list = []                      # (innings index, player) of retirements not resumed
        repl = 0
        for k, inn in enumerate(inns):
            flat = [d for ov in inn.get("overs", []) for d in ov["deliveries"]]
            for j, d in enumerate(flat):
                ex = d.get("extras") or {}
                if "wides" not in ex and "noballs" not in ex:
                    balls += 1
                repl += len((d.get("replacements") or {}).get("match", []))
                for w in d.get("wickets", []):
                    if w["kind"] != "retired hurt":
                        continue
                    who = w["player_out"]
                    retired += 1
                    hurt_in_match.add(who)
                    if any(who in (x["batter"], x["non_striker"]) for x in flat[j + 1:]):
                        back_innings += 1
                    else:
                        seen_after.append((k, who))
            for who in inn.get("absent_hurt", []) or []:
                if who not in hurt_in_match:
                    absent += 1
                    hurt_in_match.add(who)
                    if year >= SUBS_FROM:
                        lost_since += 1
        for k, who in seen_after:
            later = any(who in (d["batter"], d["non_striker"], d["bowler"])
                        for inn in inns[k + 1:] for ov in inn.get("overs", []) for d in ov["deliveries"])
            back_match += later
            if not later and year >= SUBS_FROM:
                lost_since += 1
        if year >= SUBS_FROM:
            repl_since += repl
    gone = retired - back_innings
    return {"balls": balls, "retired": retired, "back_innings": back_innings, "back_match": back_match,
            "absent": absent, "lost_since": lost_since, "replaced_since": repl_since, "subs_from": SUBS_FROM,
            "retire": {"per_ball": retired / balls, "returns": back_innings / max(retired, 1),
                       "plays_on": back_match / max(gone, 1)},
            "field": {"per_ball": absent / balls},
            "replaced": min(repl_since / max(lost_since, 1), 1.0)}


def main() -> int:
    t = fit()
    (fts.OUT / "test_injuries.json").write_text(json.dumps(t, indent=1), encoding="utf-8")
    r = t["retire"]
    print(f"{t['balls']} balls: {t['retired']} retired hurt (one in {1 / r['per_ball']:,.0f} balls), "
          f"{t['back_innings']} came back in the innings, {t['back_match']} of the other "
          f"{t['retired'] - t['back_innings']} played on in the match")
    print(f"  {t['absent']} more absent hurt without retiring (one in {1 / t['field']['per_ball']:,.0f} balls)")
    print(f"  since {t['subs_from']}: {t['lost_since']} players lost for a match, {t['replaced_since']} replacements "
          f"-> share replaced {t['replaced']:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
