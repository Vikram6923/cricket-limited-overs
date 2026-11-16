"""What does a day-night Test (pink ball, under lights) do to scoring? (data/engine/test_daynight.json)

Cricsheet does not say which Tests were day-night, so they are listed here by start date and host (a public
record; the list is checked against the data: a date with no Test that started on it in that country is
reported and left out).

For every day-night Test, runs a ball and wickets a ball off pace and off spin are set against the same host
country's day Tests since 2015. The factor is the ball-weighted ratio, shrunk toward 1 by SHRINK pseudo-balls
(runs) or pseudo-wickets, with a standard error from resampling the day-night Tests. The comparison is by host
only: it does not know the two sides' strength, and most of these Tests were Australia's at home.

Run:  python -m engine.fit.fit_test_daynight
"""
from __future__ import annotations

import json
import math
import random
import sys
from collections import defaultdict

from . import fit_test_situation as fts
from .fit_basics import bowl_types
from ..conditions import venue_key

SINCE = 2015
SHRINK_BALLS = 3000          # pseudo-balls at the day rate (runs)
SHRINK_WKTS = 60             # pseudo-wickets at the day rate
DAY_NIGHT = [                # (first day, host)
    ("2015-11-27", "Australia"), ("2016-10-13", "Pakistan"), ("2016-11-24", "Australia"),
    ("2016-12-15", "Australia"), ("2017-08-17", "England"), ("2017-10-06", "Pakistan"),
    ("2017-12-02", "Australia"), ("2017-12-26", "South Africa"), ("2018-03-22", "New Zealand"),
    ("2018-06-23", "West Indies"), ("2019-01-24", "Australia"), ("2019-11-22", "India"),
    ("2019-11-29", "Australia"), ("2019-12-12", "Australia"), ("2020-12-17", "Australia"),
    ("2021-02-24", "India"), ("2021-12-16", "Australia"), ("2022-01-14", "Australia"),
    ("2022-03-12", "India"), ("2022-12-08", "Australia"), ("2023-02-16", "New Zealand"),
    ("2024-01-25", "Australia"), ("2024-12-06", "Australia"), ("2025-07-12", "West Indies"),
    ("2025-12-04", "Australia"),
]
NEUTRAL = {"Pakistan": ("dubai", "abu dhabi", "sharjah")}     # Pakistan's home Tests of those years, by ground


def tally(m: dict, bt: dict) -> dict:
    """{"pace" | "spin": [balls, runs, wickets]} of one Test."""
    reg = m["info"]["registry"]["people"]
    out = {"pace": [0, 0, 0], "spin": [0, 0, 0]}
    for inn in m.get("innings", []):
        for ov in inn.get("overs", []):
            for d in ov["deliveries"]:
                k = bt.get(reg.get(d["bowler"]))
                if k not in out:
                    continue
                ex = d.get("extras") or {}
                if "wides" in ex or "noballs" in ex:
                    continue
                c = out[k]
                c[0] += 1
                c[1] += d["runs"]["batter"]
                c[2] += sum(1 for w in d.get("wickets", []) if w["kind"] in fts.BOWLER_WICKETS)
    return out


def fit() -> dict:
    bt = bowl_types("test")
    hosts = json.loads((fts.OUT / "test_conditions.json").read_text(encoding="utf-8"))["hosts"]
    want = {d: h for d, h in DAY_NIGHT}
    dn, day, found = [], defaultdict(lambda: {"pace": [0, 0, 0], "spin": [0, 0, 0]}), set()
    for m in fts.iter_tests():
        info = m["info"]
        date = str(info["dates"][0])
        if int(date[:4]) < SINCE:
            continue
        vk = venue_key(info.get("venue"))
        host = hosts.get(vk)
        if host is None:
            host = next((h for h, gs in NEUTRAL.items() if any(g in vk for g in gs)), None)
        t = tally(m, bt)
        if want.get(date) == host and host:
            dn.append((host, t))
            found.add(date)
        elif host:
            for k in t:
                for i in range(3):
                    day[host][k][i] += t[k][i]
    missing = sorted(set(want) - found)

    def factors(sample: list) -> dict:
        out = {}
        for k in ("pace", "spin"):
            balls = sum(t[k][0] for _, t in sample)
            runs = sum(t[k][1] for _, t in sample)
            wkts = sum(t[k][2] for _, t in sample)
            er = sum(t[k][0] * day[h][k][1] / max(day[h][k][0], 1) for h, t in sample)
            ew = sum(t[k][0] * day[h][k][2] / max(day[h][k][0], 1) for h, t in sample)
            rate_r = er / max(balls, 1)
            out[k] = {"runs": (runs + SHRINK_BALLS * rate_r) / (er + SHRINK_BALLS * rate_r) if er else 1.0,
                      "wkt": (wkts + SHRINK_WKTS) / (ew + SHRINK_WKTS) if ew else 1.0,
                      "balls": balls, "wickets": wkts}
        return out
    f = factors(dn)
    rng = random.Random(7)
    boots = [factors([rng.choice(dn) for _ in dn]) for _ in range(400)]
    for k in ("pace", "spin"):
        for x in ("runs", "wkt"):
            v = [math.log(b[k][x]) for b in boots]
            mu = sum(v) / len(v)
            f[k][x + "_se"] = round(math.sqrt(sum((a - mu) ** 2 for a in v) / (len(v) - 1)), 4)
            f[k][x] = round(f[k][x], 4)
    return {"since": SINCE, "matches": len(dn), "missing": missing, "hosts": sorted({h for h, _ in dn}), **f}


def main() -> int:
    t = fit()
    (fts.OUT / "test_daynight.json").write_text(json.dumps(t, indent=1), encoding="utf-8")
    print(f"{t['matches']} day-night Tests found since {t['since']}; not in the data: {t['missing'] or 'none'}")
    for k in ("pace", "spin"):
        f = t[k]
        print(f"  {k}: runs x{f['runs']:.3f} (se {f['runs_se']:.3f}), wickets x{f['wkt']:.3f} (se {f['wkt_se']:.3f}) "
              f"from {f['balls']} balls, {f['wickets']} wickets")
    return 0


if __name__ == "__main__":
    sys.exit(main())
