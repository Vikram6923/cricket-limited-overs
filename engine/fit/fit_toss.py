"""Toss decisions (design T2-5): how often captains bowl first, and where chasing pays.

Per format (matches since 2018, full overs, result): the share of toss winners who chose to bowl, and per venue the
chasing side's win rate, shrunk toward the format-wide rate (40 pseudo-matches). The captain then bowls first with
the real base rate, shifted on the logit scale toward the venue's chasing advantage.

Writes data/engine/toss_{t20,odi}.json.   Run:  python -m engine.fit.fit_toss
"""
from __future__ import annotations

import json
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

from ..conditions import venue_key

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "engine"
SOURCES = {"t20": ["t20s_male_json.zip"] + [f"leagues/{c}_json.zip" for c in
                                            ("ipl", "bbl", "psl", "cpl", "sat", "ilt", "bpl", "lpl", "mlc", "ntb",
                                             "ssm")],
           "odi": ["odis_male_json.zip"]}
OVERS = {"t20": 20, "odi": 50}
FIRST_YEAR = 2018
PSEUDO = 40


def fit(fmt: str) -> dict:
    bowl = n_toss = 0
    chase = defaultdict(lambda: [0, 0])
    total_w = total_n = 0
    for z in SOURCES[fmt]:
        if not (RAW / z).exists():
            continue
        with zipfile.ZipFile(RAW / z) as zf:
            for name in zf.namelist():
                if not name.endswith(".json"):
                    continue
                info = json.loads(zf.read(name))["info"]
                if info.get("gender") != "male" or int(info["dates"][0][:4]) < FIRST_YEAR:
                    continue
                if info.get("overs") != OVERS[fmt]:
                    continue
                t = info.get("toss") or {}
                if t.get("decision") in ("bat", "field"):
                    n_toss += 1
                    bowl += t["decision"] == "field"
                oc = info.get("outcome") or {}
                if "winner" not in oc or "method" in oc or not t.get("winner"):
                    continue
                first = t["winner"] if t.get("decision") == "bat" else \
                    [x for x in info["teams"] if x != t["winner"]][0]
                won = oc["winner"] != first
                c = chase[venue_key(info.get("venue"))]
                c[0] += won
                c[1] += 1
                total_w += won
                total_n += 1
    base = total_w / total_n
    venues = {k: round((w + PSEUDO * base) / (n + PSEUDO), 4) for k, (w, n) in chase.items() if n >= 5}
    return {"format": fmt, "since": FIRST_YEAR, "p_bowl": round(bowl / n_toss, 4), "chase_win": round(base, 4),
            "venues": venues}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for fmt in ("t20", "odi"):
        r = fit(fmt)
        (OUT / f"toss_{fmt}.json").write_text(json.dumps(r, indent=1), encoding="utf-8")
        v = sorted(r["venues"].items(), key=lambda kv: kv[1])
        print(f"{fmt}: toss winners bowl {r['p_bowl']:.0%}; chasing side wins {r['chase_win']:.1%}; "
              f"venue range {v[0]} .. {v[-1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
