"""Golden regression test: limited-overs matches must play exactly as before for the same seed.

    python tests/test_golden.py            check today's engine against tests/golden/limited_overs.json
    python tests/test_golden.py --write    regenerate that file

Regenerate the file ONLY in a commit that changes limited-overs behaviour on purpose, and say so in the commit
message. Work on anything else (Test cricket, refactors, the UI) must pass without touching it.

About 60 fixed matches cover the engine's branches: T20Is and ODIs with fixed XIs, squads (XI selection), an IPL
season's squads with the Impact Player, rain and DLS, classic sides rated on a year range, weaker computer
captains, a series and a small tournament. Each match is reduced to its whole-number facts (scores, every batter's
and bowler's line, the result), not its rounded floats: the file is written on Windows and checked on Linux, where
the maths library can differ in the last bit.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import simulate_match  # noqa: E402
from engine.history import historical_team  # noqa: E402
from engine.tournament import play_series, play_tournament  # noqa: E402

GOLDEN = Path(__file__).resolve().parent / "golden" / "limited_overs.json"


def facts(card: dict) -> dict:
    """The whole-number facts of a scorecard."""
    def inn(i):
        return {"team": i["team"], "runs": i["runs"], "wkts": i["wickets"], "balls": i["balls"],
                "target": i.get("target"), "max_overs": i.get("max_overs"), "extras": i["extras"],
                "bat": [[b["id"], b["runs"], b["balls"], b["fours"], b["sixes"], b["dismissal"]]
                        for b in i["batting"]],
                "bowl": [[w["id"], w["balls"], w["maidens"], w["runs"], w["wickets"], w["wides"], w["noballs"]]
                         for w in i["bowling"]],
                "fow": [[f["wkt"], f["runs"], f["over"]] for f in i["fall_of_wickets"]]}
    return {"toss": card["toss"], "xi": {t: [p["id"] for p in xi] for t, xi in card["xi"].items()},
            "impact": {t: [v.get("in_id") or v.get("in"), v.get("out_id") or v.get("out")]
                       for t, v in (card.get("impact_player") or {}).items()},
            "rain": card.get("rain"), "result": card["result"]["text"],
            "pom": (card.get("player_of_match") or {}).get("id"),
            "innings": [inn(i) for i in card["innings"]], "super_overs": [inn(i) for i in card["super_overs"]]}


def digest(cards: list[dict]) -> dict:
    """What is stored per case: a readable line per match and a hash of all its facts."""
    f = [facts(c) for c in cards]
    blob = json.dumps(f, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()
    return {"results": [x["result"] + " | " + ", ".join(f"{i['runs']}/{i['wkts']}" for i in x["innings"])
                        for x in f],
            "sha256": hashlib.sha256(blob).hexdigest()}


def _presets() -> dict:
    teams = json.loads((ROOT / "data" / "teams_default.json").read_text(encoding="utf-8"))
    return {t["name"]: [p["id"] if isinstance(p, dict) else p for p in t["players"]] for t in teams}


def _ipl(year: int) -> list[dict]:
    seasons = json.loads((ROOT / "data" / "league_seasons.json").read_text(encoding="utf-8"))["ipl"]["seasons"]
    s = next(x for x in seasons if x["year"] == year)
    return [{"name": t["name"], "squad": t["players"], "overseas": t["overseas"],
             "max_overseas": t["max_overseas"], "venue": t.get("home_venue")} for t in s["teams"]]


def cases() -> dict:
    """name -> list of cards. Every case is fixed by its seed."""
    P = _presets()
    xi = lambda n: {"name": n, "players": P[n][:11]}          # noqa: E731
    sq = lambda n: {"name": n, "squad": P[n]}                 # noqa: E731
    ia, au = "India T20 2024", "Australia T20 2024"
    io, ao = "India ODI 2023", "Australia ODI 2023"
    out: dict = {}
    out["t20i_xi"] = [simulate_match(xi(ia), xi(au), fmt="t20", comp="t20i_full", year=2024, seed=s)
                      for s in range(1, 9)]
    out["t20i_squads_venue"] = [simulate_match(sq(a), sq(b), fmt="t20", comp="t20i_full", year=2024,
                                               venue="Wankhede Stadium, Mumbai", seed=100 + s)
                                for s, (a, b) in enumerate([(ia, au), ("England T20 2024", "Pakistan T20 2024"),
                                                            ("South Africa T20 2024", "New Zealand T20 2024"),
                                                            ("West Indies T20 2024", "Afghanistan T20 2024")])]
    out["odi_xi"] = [simulate_match(xi(io), xi(ao), fmt="odi", comp="odi_full", year=2023, seed=s)
                     for s in range(11, 17)]
    out["odi_squads_venue"] = [simulate_match(sq(io), sq(ao), fmt="odi", comp="odi_full", year=2023,
                                              venue="Melbourne Cricket Ground", seed=s) for s in (21, 22, 23)]
    out["t20i_rain"] = [simulate_match(sq(ia), sq("England T20 2024"), fmt="t20", comp="t20i_full", year=2024,
                                       venue="Kensington Oval, Bridgetown, Barbados", rain_on=True, seed=s)
                        for s in range(200, 208)]
    out["odi_rain"] = [simulate_match(sq(io), sq(ao), fmt="odi", comp="odi_full", year=2023,
                                      venue="R Premadasa Stadium, Colombo", rain_on=True, seed=s)
                       for s in range(300, 308)]
    ipl = _ipl(2024)
    out["ipl_impact"] = [simulate_match(ipl[i], ipl[i + 1], fmt="t20", comp="ipl", year=2024,
                                        venue=ipl[i]["venue"], seed=400 + i) for i in range(0, 8, 2)]
    out["ipl_2019_no_impact"] = [simulate_match(*_ipl(2019)[:2], fmt="t20", comp="ipl", year=2019, seed=s)
                                 for s in (450, 451)]
    aus, ind = historical_team("odi", "Australia", 2003, 2007), historical_team("odi", "India", 2011, 2011)
    out["classic_odi"] = [simulate_match(aus, ind, fmt="odi", comp="odi_full", year=2011, seed=s) for s in (500, 501)]
    old = historical_team("odi", "West Indies", 1979, 1984)
    only = historical_team("odi", "India", 2011, 2011, years_mode="only")
    out["classic_pre2002"] = [simulate_match(old, only, fmt="odi", comp="odi_full", year=1983, seed=510)]
    t1, t2 = historical_team("t20", "India", 2007, 2010), historical_team("t20", "Pakistan", 2007, 2010)
    out["classic_t20"] = [simulate_match(t1, t2, fmt="t20", comp="t20i_full", year=2009, seed=s) for s in (520, 521)]
    out["weaker_captains"] = [simulate_match(sq(ia), sq(au), fmt="t20", comp="t20i_full", year=2024, seed=600 + i,
                                             skill={ia: lvl, au: "average"})
                              for i, lvl in enumerate(("easy", "average", "easy"))]
    out["flags_off"] = [simulate_match(xi(ia), xi(au), fmt="t20", comp="t20i_full", year=2024, seed=700,
                                       use_situation=False, use_plan=False, use_venue=False, use_pitch=False,
                                       use_matchups=False, use_spin=False, use_reactive=False, use_depth=False),
                        simulate_match(xi(io), xi(ao), fmt="odi", comp="odi_full", year=2023, seed=701, overs=30,
                                       toss="b", decision="bowl")]
    out["series"] = play_series(sq(io), sq(ao), n=3, fmt="odi", comp="odi_full", year=2023, seed=800)["matches"]
    out["tournament"] = play_tournament([sq(n) for n in (ia, au, "England T20 2024", "South Africa T20 2024")],
                                        fmt="t20", comp="t20i_full", year=2024, knockout="final", rain=True,
                                        seed=900)["matches"]
    return out


def build() -> dict:
    return {name: digest(cards) for name, cards in cases().items()}


def test_limited_overs_unchanged():
    want = json.loads(GOLDEN.read_text(encoding="utf-8"))
    got = build()
    assert sorted(got) == sorted(want), f"cases differ: {sorted(set(got) ^ set(want))}"
    bad = []
    for name in want:
        if got[name]["sha256"] != want[name]["sha256"]:
            diff = [f"    match {i + 1}: was  {w}\n             now  {g}"
                    for i, (w, g) in enumerate(zip(want[name]["results"], got[name]["results"])) if w != g]
            bad.append(f"  {name}:\n" + ("\n".join(diff) if diff else "    same results, other facts differ"))
    assert not bad, ("limited-overs matches no longer play as recorded in tests/golden/limited_overs.json:\n"
                     + "\n".join(bad))


if __name__ == "__main__":
    if "--write" in sys.argv:
        GOLDEN.parent.mkdir(exist_ok=True)
        data = build()
        GOLDEN.write_text(json.dumps(data, indent=1, ensure_ascii=True) + "\n", encoding="utf-8")
        print(f"wrote {GOLDEN.relative_to(ROOT)}: {sum(len(v['results']) for v in data.values())} matches "
              f"in {len(data)} cases")
    else:
        test_limited_overs_unchanged()
        print("ok")
