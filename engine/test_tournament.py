"""Test tournaments and the World Test Championship.

    from engine.tournament import play_tournament
    res = play_tournament(teams, fmt="test", knockout="final", seed=1)        # a round robin of Tests, then a final

    from engine.test_tournament import play_wtc
    res = play_wtc(teams, tests=2, seed=1)                                    # home and away series, then a final

`engine.tournament.play_tournament(..., fmt="test")` builds its runner here, as `simulate_match` sends a Test to
engine/test_match.py. What a Test competition does differently:
- every league match is at the first-named side's home: its country's Test grounds in rotation, its weather and
  the home edge (a side with no country, or a ground given by hand, plays as a series does);
- points as the World Test Championship gives them: 12 a win, 6 a tie, 4 a draw; the table is ordered by the
  share of the points played for won, then wins, then the runs-per-wicket ratio (runs a wicket made over runs a
  wicket conceded), which stands where the net run rate stands in limited overs;
- a knockout needs a winner: a drawn (or tied) knockout Test goes to the side that led on first innings when
  both first innings were finished, otherwise to the higher-placed side (named first). The real World Test
  Championship shares its title after a drawn final; here the final follows the same rule as any knockout.
"""
from __future__ import annotations

import random
from collections import Counter

from .data import FORMATS
from .match import simulate_match
from .test_series import ORDINALS, home_grounds, nation_of, summary_card, test_stats
from .tournament import _Runner, _seed, _wins, team_spec

FMT = "test"
POINTS = {"win": 12, "tie": 6, "draw": 4}
WTC_SERIES = 3                 # each side plays this many series at home and as many away (the real cycle: 3)
WTC_TESTS = (1, 2, 3, 4, 5, 6)  # Tests in each series
WTC_FINAL = "Lord's"           # where the final is played, when the ground is known


def test_table(cards: list[dict], teams: list[str], win_points: int = POINTS["win"]) -> list[dict]:
    """The table of a Test league. "nrr" holds the runs-per-wicket ratio (the tie-break), so the code that
    ranks qualifiers (engine/tournament.py) reads it as it reads a net run rate."""
    rows = {t: {"team": t, "played": 0, "won": 0, "lost": 0, "drawn": 0, "tied": 0, "no_result": 0, "points": 0,
                "runs_for": 0, "wkts_for": 0, "runs_against": 0, "wkts_against": 0} for t in teams}
    for c in cards:
        names = list(c["teams"])
        if not all(n in rows for n in names):
            continue
        for inn in c["innings"]:
            bat, bowl = rows[inn["team"]], rows[inn["bowling_team"]]
            bat["runs_for"] += inn["runs"]
            bat["wkts_for"] += inn["wickets"]
            bowl["runs_against"] += inn["runs"]
            bowl["wkts_against"] += inn["wickets"]
        res = c["result"]
        for n in names:
            rows[n]["played"] += 1
        if res.get("type") == "win":
            rows[res["winner"]]["won"] += 1
            rows[res["winner"]]["points"] += POINTS["win"]
            rows[res["loser"]]["lost"] += 1
        else:
            k = "tied" if res.get("type") == "tie" else "drawn"
            for n in names:
                rows[n][k] += 1
                rows[n]["points"] += POINTS["tie" if k == "tied" else "draw"]
    out = []
    for r in rows.values():
        f = r["runs_for"] / max(r["wkts_for"], 1)
        a = r["runs_against"] / max(r["wkts_against"], 1)
        r["nrr"] = round(f / a, 3) if a else 0.0
        r["pct"] = round(100 * r["points"] / (POINTS["win"] * r["played"]), 1) if r["played"] else 0.0
        r["for"] = f"{r['runs_for']}/{r['wkts_for']}"
        r["against"] = f"{r['runs_against']}/{r['wkts_against']}"
        out.append(r)
    out.sort(key=lambda r: (-r["pct"], -r["won"], -r["nrr"], r["team"]))
    for i, r in enumerate(out, 1):
        r["pos"] = i
    return out


test_table.__test__ = False            # not a test (the name starts with test_)


def first_innings_lead(card: dict) -> str | None:
    """The side ahead on first innings, when both first innings were finished (all out or declared)."""
    inns = card["innings"][:2]
    if len(inns) < 2 or any(i.get("ended") not in ("all out", "declared") for i in inns):
        return None
    a, b = inns
    return None if a["runs"] == b["runs"] else a["team"] if a["runs"] > b["runs"] else b["team"]


class TestRunner(_Runner):
    """Plays the Tests of a competition: numbering and seeds as in limited overs; grounds, hosts and a drawn
    knockout as the module's note says."""
    __test__ = False             # not a test class (the name starts with Test)
    WIN_POINTS = POINTS["win"]

    def __init__(self, comp: str | None, year: int, seed: int | None, venues: list | None,
                 home_venues: dict | None, knockout_venues: list | None, control: dict | None = None,
                 skill: dict | None = None, match_kw: dict | None = None):
        super().__init__(FMT, comp, year, seed, venues, home_venues, knockout_venues, False, control, skill)
        self.hosted: Counter = Counter()       # home Tests so far, by side (its grounds in rotation)
        self.match_kw = dict(match_kw or {})   # every Test's conditions: days, timeless, day_night (test_match)

    def table(self, cards, names, win_points):
        return test_table(cards, names)

    def stats(self, cards):
        return test_stats(cards, _wins(cards))

    def summary(self, card):
        return summary_card(card)

    def play_league(self, fixtures: list[tuple]) -> None:
        for a, b, stage in fixtures:
            self.play(a, b, stage)

    def ground(self, home: dict, knockout: bool) -> tuple:
        """(venue, host): a ground given by hand decides its own country; otherwise a league Test is in the home
        side's country, on its grounds in rotation, and a knockout is on neutral ground."""
        venue = self.venue_for(home["name"], knockout)
        if venue or knockout:
            return venue, None
        nation = home.get("nation")
        pool = home_grounds().get(nation or "", [])
        if not pool:
            return None, None
        k = self.hosted[home["name"]]
        self.hosted[home["name"]] += 1
        return pool[k % len(pool)], nation

    def play(self, a: dict, b: dict, stage: str, knockout: bool = False) -> dict:
        for sp in (a, b):
            if "nation" not in sp:
                sp["nation"] = nation_of(sp)
        no = len(self.cards) + 1
        venue, host = self.ground(a, knockout)
        for ctl in self.control.values():
            ctl.context = {"stage": stage, "match_no": no, "knockout": knockout, "venue": venue}
        args = {**self.match_kw, **({"host": host} if host else {})}
        card = simulate_match(a, b, fmt=FMT, comp=self.comp, year=self.year, venue=venue, seed=_seed(self.seed, no),
                              control=self.control or None, skill=self.skill or None, **args)
        if knockout and not card["result"].get("winner"):
            r = card["result"]
            lead = first_innings_lead(card)
            w = lead or a["name"]
            why = "on first-innings lead" if lead else "as the higher-placed side"
            card["result"] = {**r, "winner": w, "loser": b["name"] if w == a["name"] else a["name"], "by": r["type"],
                              "text": f"{r['text']} - {w} go through {why}"}
        card["match_no"], card["stage"], card["knockout"] = no, stage, knockout
        self.cards.append(card)
        if self.on_match:
            self.on_match(card)
        return card


# ------------------------------------------------------------------------------------- World Test Championship

def wtc_home_series(n_teams: int, home_series: int | None = None) -> int:
    """Series each side plays at home: home_series (at most one fewer than the sides), or by default
    WTC_SERIES when there are enough sides (seven or more), else as many as let nobody meet twice."""
    if home_series:
        return min(home_series, n_teams - 1)
    return min(WTC_SERIES, (n_teams - 1) // 2)


def wtc_series(names: list[str], seed: int, home_series: int | None = None) -> list[tuple[str, str]]:
    """(home, away) for every series of a cycle. The sides stand in a ring in an order drawn from the seed; each
    is at home to the next k and away to the k before (k: wtc_home_series). Nine sides by default: six series
    each, three at home, and two sides each never meets, as in the real cycle. With k above half the sides, some
    pairs meet twice, once at each one's home; k = sides - 1 is every side home and away to every other."""
    ring = list(names)
    random.Random(_seed(seed, 0)).shuffle(ring)
    n = len(ring)
    k = wtc_home_series(n, home_series)
    return [(ring[i], ring[(i + d) % n]) for d in range(1, k + 1) for i in range(n)]


def wtc_match_count(n_teams: int, tests: int = 2, home_series: int | None = None) -> int:
    return n_teams * wtc_home_series(n_teams, home_series) * tests + 1


def play_wtc(teams: list[dict], comp: str | None = None, year: int = 2025, tests: int = 2,
             seed: int | None = None, on_match=None, control: dict | None = None, skill: dict | None = None,
             final_venue: str | None = WTC_FINAL, home_series: int | None = None, **kw) -> dict:
    """A World Test Championship cycle: every side plays series of `tests` Tests, half of them at home (three
    at home and three away with seven sides or more), for 12 points a win, 6 a tie and 4 a draw; the two sides
    with the highest share of their points won meet in a final (at final_venue; None: a neutral ground with no
    name). home_series: series each side plays at home (and as many away) instead, up to one fewer than the
    sides (then every side meets every other at home and away). kw goes to every Test (engine/test_match.py:
    days, timeless, day_night). The result has the shape of a tournament's (engine/tournament.py) with "wtc":
    the series played."""
    if tests not in WTC_TESTS:
        raise ValueError(f"A Championship series has {WTC_TESTS[0]} to {WTC_TESTS[-1]} Tests.")
    if home_series is not None and home_series < 1:
        raise ValueError("Each side plays at least one series at home.")
    specs = [team_spec(FMT, t) for t in teams]
    by_name = {t["name"]: t for t in specs}
    if len(by_name) != len(specs):
        raise ValueError("team names must be unique")
    if len(specs) < 3:
        raise ValueError("A World Test Championship needs at least three sides.")
    run = TestRunner(comp, year, seed, None, None, [final_venue] if final_venue else None, control, skill, kw)
    run.on_match = on_match
    names = [t["name"] for t in specs]
    series = []
    for home, away in wtc_series(names, run.seed, home_series):
        start = len(run.cards)
        for j in range(tests):
            run.play(by_name[home], by_name[away], f"{home} v {away}, " + ("only Test" if tests == 1 else f"{ORDINALS[j]} Test"))
        w = _wins(run.cards[start:])
        wh, wa = w.get(home, 0), w.get(away, 0)
        series.append({"home": home, "away": away, "score": [wh, wa], "draws": tests - wh - wa,
                       "winner": home if wh > wa else away if wa > wh else None,
                       "matches": [c["match_no"] for c in run.cards[start:]]})
    table = test_table(run.cards, names)
    won = Counter(s["winner"] for s in series if s["winner"])
    for r in table:
        r["series_won"] = won.get(r["team"], 0)
    f1, f2 = table[0]["team"], table[1]["team"]
    c = run.play(by_name[f1], by_name[f2], "Final", knockout=True)
    ko = [{"stage": "Final", "match_no": c["match_no"], "teams": [f1, f2], "winner": c["result"]["winner"],
           "result": c["result"]["text"]}]
    stats = run.stats(run.cards)
    return {"kind": "tournament", "format": FMT, "competition": run.comp, "year": year, "seed": run.seed,
            "settings": {"rounds": 1, "groups": {"League": names}, "knockout": "final",
                         "win_points": POINTS["win"], "advance": None},
            "wtc": {"tests": tests, "home_series": wtc_home_series(len(names), home_series), "series": series,
                    "final_venue": c.get("venue")},
            "teams": names, "tables": {"League": table}, "knockouts": ko, "super_league": {},
            "winner": c["result"]["winner"], "runner_up": c["result"]["loser"],
            "player_of_series": stats["mvp"]["official"][0] if stats["mvp"]["official"] else None,
            "fixtures": [run.summary(x) for x in run.cards], "matches": run.cards, **stats}


assert FORMATS[FMT]["overs"] is None
