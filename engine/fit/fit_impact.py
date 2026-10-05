"""Tables for the rational Impact Player model (engine/impact.py), from real first innings (IPL 2015-26).

    python -m engine.fit.fit_impact        -> data/engine/impact_t20.json

- balls_next: after the w-th wicket with n overs left, the balls each batter still to come faces on average
  (the next man in first). This is how much batting a substitute batter can still add at that moment.
- scenarios: wicket timelines (legal ball of each wicket) of real first innings since 2023, used to value an XI
  together with the substitute options it leaves open (start with an extra bowler and bring in a batter only if
  wickets fall, etc.).
Neither table says anything about how teams use the Impact Player; the decisions themselves are value-based.
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OVERS = 20


def innings_rows(zpath: Path, y0: int):
    with zipfile.ZipFile(zpath) as zf:
        for n in zf.namelist():
            if not n.endswith(".json"):
                continue
            m = json.loads(zf.read(n))
            if int(m["info"]["dates"][0][:4]) < y0 or not m.get("innings") or m["info"].get("overs", OVERS) != OVERS:
                continue
            inn = m["innings"][0]
            if inn.get("super_over"):
                continue
            yield int(m["info"]["dates"][0][:4]), inn


def main() -> None:
    sums: dict = {}
    scen = []
    for year, inn in innings_rows(ROOT / "data" / "raw" / "leagues" / "ipl_json.zip", 2015):
        order, faced, wk = [], {}, []
        legal = 0
        for ov in inn["overs"]:
            for d in ov["deliveries"]:
                for who in (d["batter"], d["non_striker"]):
                    if who not in faced:
                        order.append(who)
                        faced[who] = 0
                ex = d.get("extras", {})
                if "wides" not in ex:
                    faced[d["batter"]] += 1
                if "wides" not in ex and "noballs" not in ex:
                    legal += 1
                for _ in d.get("wickets", []):
                    wk.append(legal)
        if year >= 2023:
            scen.append(wk)
        balls = [faced[p] for p in order] + [0] * (11 - len(order))
        for w, at in enumerate(wk, start=1):
            left = OVERS * 6 - at
            if w >= 10 or left <= 0:
                continue
            key = f"{w},{-(-left // 6)}"
            rest = balls[w + 1:11]          # positions w+2 .. 11 (the next man in first)
            s = sums.setdefault(key, [[0.0] * len(rest), 0])
            for j, b in enumerate(rest):
                s[0][j] += b
            s[1] += 1
    out = {"balls_next": {k: {"sum": [round(x, 1) for x in v[0]], "n": v[1]} for k, v in sorted(sums.items())},
           "scenarios": scen, "source": "IPL first innings 2015-26 (balls_next), 2023-26 (scenarios)"}
    path = ROOT / "data" / "engine" / "impact_t20.json"
    path.write_text(json.dumps(out), encoding="utf-8")
    print(f"{len(sums)} cells, {len(scen)} scenarios -> {path}")
    for k in ("3,15", "6,5", "7,3"):
        if k in sums:
            s, n = sums[k]
            print(k, n, [round(x / n, 1) for x in s])


if __name__ == "__main__":
    main()
