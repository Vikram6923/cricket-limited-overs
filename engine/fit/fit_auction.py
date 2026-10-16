"""Win chance from auction squads, for the auction's report card (engine/auction.py, Auction.report).

    python -m engine.fit.fit_auction [t20] [odi]  -> data/engine/auction_t20.json, auction_odi.json

Plays computer-only auctions (league season pools, and years pools for ODI), then matches between their squads
with the full engine (XI picked from the squad, the pool's conditions). A squad's strength is the value of its
best XI as the auction counts it (Auction._xi: runs per match, empty places at replacement level). Fitted:
P(A beats B) = 1 / (1 + exp(-(strength A - strength B) / scale)), scale by maximum likelihood.
"""
from __future__ import annotations

import json
import math
import random
from pathlib import Path

from ..auction import Auction, league_data, season_pool, years_pool
from ..match import simulate_match

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "engine"
MATCHES = {"t20": 480, "odi": 360}     # per auction


def auctions(fmt: str):
    if fmt == "t20":
        lg = league_data()
        for league, season in (("ipl", "2025"), ("ipl", "2023"), ("bbl", None), ("psl", None), ("cpl", None)):
            s = season or lg[league]["seasons"][0]["season"]
            for seed in (1, 2):
                a = Auction(season_pool(league, s), seed=seed)
                yield a, a.comp, a.year
    else:
        teams = [f"Team {i}" for i in range(8)]
        for (y1, y2), seed in (((2003, 2012), 1), ((2013, 2023), 2), ((2015, 2025), 3)):
            yield Auction(years_pool("odi", y1, y2, teams), seed=seed), "odi_full", y2


def fit(fmt: str) -> dict:
    rows = []
    for n, (a, comp, year) in enumerate(auctions(fmt)):
        specs = a.team_specs()
        strength = {t: a._xi(a.squad[t])[0] for t in a.teams}
        rng = random.Random(n)
        for k in range(MATCHES[fmt]):
            ta, tb = rng.sample(specs, 2)
            card = simulate_match(ta, tb, fmt, comp, year, seed=1000 * n + k)
            w = (card.get("result") or {}).get("winner")
            if w in (ta["name"], tb["name"]):
                rows.append((strength[ta["name"]] - strength[tb["name"]], w == ta["name"]))
        print(f"  {a.label}: {len(rows)} matches so far")

    def loglik(b):
        return sum(-math.log1p(math.exp(-b * d if win else b * d)) for d, win in rows)
    b = max((k / 10000 for k in range(0, 2001)), key=loglik)       # slope per run, 0 to 0.2
    info = sum(d * d * 0.25 for d, _ in rows)                        # Fisher information near p = 0.5
    spread = math.sqrt(sum(d * d for d, _ in rows) / len(rows))
    return {"scale": round(1 / b, 1) if b > 0 else 1000.0, "slope": b, "slope_se": round(info ** -0.5, 4),
            "matches": len(rows), "strength_diff_sd": round(spread, 1)}


def main(fmts=("t20", "odi")) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for fmt in fmts:
        r = fit(fmt)
        (OUT / f"auction_{fmt}.json").write_text(json.dumps(r, indent=1), encoding="utf-8")
        print(fmt, r)


if __name__ == "__main__":
    import sys
    main(sys.argv[1:] or ("t20", "odi"))
