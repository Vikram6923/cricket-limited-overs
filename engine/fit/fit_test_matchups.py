"""Fit the Test matchups: batting hand x bowling kind (docs/test_match_plan.md section 2).

A left-hander against off spin, a right-hander against left-arm pace: the ratings hold each player's overall
level, not whom he does well against. For every legal ball of every Cricsheet Test the rate the engine would use
is ratings x the fitted situation tables (data/engine/test_situation.json); this table holds observed / that, by
(batting hand, bowling kind). As in limited overs (fit_situation.py matchup_table) a cell is shrunk toward 1 and
the table is then centred both ways, so that over real balls every hand and every kind still averages 1: it
moves runs and wickets between matchups and leaves every player's level alone.

Kinds: pace (fast to medium, right arm), left_pace, and the spin kinds of data/raw_stats/styles.json.

Writes data/engine/test_matchups.json.   Run:  python -m engine.fit.fit_test_matchups   (after fit_test_situation)
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict

from ..test_situation import TestSituation
from . import fit_test_situation as fts
from .fit_basics import bowl_types

METRICS = fts.METRICS
NM = len(METRICS)
SHRINK_BALLS = 2000                               # as in limited overs
PACE = {"fast", "fast_medium", "medium_fast", "medium"}


def load_styles() -> tuple[dict, dict]:
    """Batting hand and matchup kind per Cricsheet id."""
    st = json.loads((fts.ROOT / "data" / "raw_stats" / "styles.json").read_text(encoding="utf-8"))
    hand = {k: v["bat_hand"] for k, v in st.items() if v.get("bat_hand")}
    kind = {}
    for k, v in st.items():
        k2 = matchup_kind((v.get("bowl") or {}).get("kind"), (v.get("bowl") or {}).get("arm"))
        if k2:
            kind[k] = k2
    return hand, kind


def matchup_kind(kind: str | None, arm: str | None) -> str | None:
    """The table's name for a bowler: pace by arm, spin by its kind."""
    if not kind:
        return None
    if kind in PACE:
        return "left_pace" if arm == "left" else "pace"
    return kind


def centred(MA: dict, ME: dict, MN: dict) -> dict:
    hands = sorted({h for h, _ in MA})
    kinds = sorted({k for _, k in MA})
    out: dict = {}
    for j, name in enumerate(METRICS):
        r, w = {}, {}
        for hk in MA:
            e, a, n = ME[hk][j], MA[hk][j], MN[hk]
            k = SHRINK_BALLS * (e / n) if n else 0.0
            r[hk] = (a + k) / (e + k) if e + k > 0 else 1.0
            w[hk] = e
        for _ in range(50):
            for group, other, mk in ((kinds, hands, lambda g, o: (o, g)), (hands, kinds, lambda g, o: (g, o))):
                for g in group:
                    cells = [mk(g, o) for o in other if mk(g, o) in r]
                    tot = sum(w[c] for c in cells)
                    if tot:
                        avg = sum(r[c] * w[c] for c in cells) / tot
                        for c in cells:
                            r[c] /= avg
        for (h, kd), v in r.items():
            out.setdefault(h, {}).setdefault(kd, {})[name] = round(v, 4)
    return out


def fit() -> dict:
    base, bat, bowl, _ = fts.load_ratings()
    btype = bowl_types("test")
    hand, kind = load_styles()
    sit = TestSituation()
    MA = defaultdict(lambda: [0.0] * NM)
    ME = defaultdict(lambda: [0.0] * NM)
    MN = defaultdict(int)
    for m in fts.iter_tests():                    # the same walk as fit_test_situation.fit
        info = m["info"]
        brow = (base.get(info["dates"][0][:4]) or {}).get("all")
        if not brow:
            continue
        reg = info["registry"]["people"]
        total, draw, days = fts.match_overs(m), fts.is_draw(m), len(info["dates"])
        gone = 0
        team_runs = defaultdict(int)
        for k, inn in enumerate(m.get("innings", [])[:4]):
            team = inn["team"]
            other = [t for t in info["teams"] if t != team][0]
            lead0 = team_runs[team] - team_runs[other]
            runs = wk = 0
            faced = defaultdict(int)
            for ov in inn.get("overs", []):
                left = fts.overs_left(gone, total, draw, days)
                for d in ov["deliveries"]:
                    ex = d.get("extras", {})
                    wide, nb = "wides" in ex, "noballs" in ex
                    bid, wid = reg.get(d["batter"]), reg.get(d["bowler"])
                    h, kd = hand.get(bid), kind.get(wid)
                    if not wide and not nb and bid in bat and wid in bowl and h and kd:
                        cell = (sit.cell(k + 1, wk, lead0 + runs) if k < 3
                                else sit.cell(4, wk, 0, -lead0 + 1 - runs, left))
                        mult = sit.multipliers(cell, faced[bid], btype.get(wid), gone, ov["over"] % 80)
                        bi, wi = bat[bid], bowl[wid]
                        br = d["runs"]["batter"]
                        a, e = MA[(h, kd)], ME[(h, kd)]
                        MN[(h, kd)] += 1
                        a[0] += br
                        a[1] += any(w["kind"] in fts.BOWLER_WICKETS for w in d.get("wickets", []))
                        a[2] += br == 0
                        a[3] += br == 4 and not d["runs"].get("non_boundary")
                        a[4] += br == 6
                        for j, mt in enumerate(METRICS):
                            e[j] += brow[mt] * bi[mt] * wi[mt] * mult[mt]
                    if not wide:
                        faced[bid] += 1
                    runs += d["runs"]["total"]
                    wk += fts.outs(d)
                gone += 1
            team_runs[team] += runs
    return {"format": "test", "metrics": list(METRICS), "shrink_balls": SHRINK_BALLS,
            "matchup": centred(MA, ME, MN), "balls": {f"{h}|{k}": n for (h, k), n in sorted(MN.items())}}


def main() -> int:
    t = fit()
    (fts.OUT / "test_matchups.json").write_text(json.dumps(t, indent=1), encoding="utf-8")
    for h, row in t["matchup"].items():
        for kd, v in row.items():
            print(f"  {h:6} v {kd:18} {t['balls'][f'{h}|{kd}']:8d}  " + "  ".join(f"{m} {x:5.3f}" for m, x in v.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
