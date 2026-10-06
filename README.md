# Limited-overs cricket simulator (ODI + T20)

A ball-by-ball simulator for **One-Day Internationals (50 overs)** and **Twenty20 (20 overs)**, with players rated
from real ball-by-ball data. Pick any XIs from about 7,800 rated players (internationals since ~2002, ODI players back
to 1971, and eleven franchise leagues). Play them in any era's conditions and get a full scorecard, a match report,
charts (run worm, Manhattan, win probability, partnerships) and a player of the match. Rain with DLS targets and
the IPL Impact Player rule are modelled.

The engine is a plain Python library: no prompts, no global state, and a seed makes every match reproducible. It
is checked against reality by replaying ~1,500 real matches with their real line-ups (see
[Does it look like real cricket?](#does-it-look-like-real-cricket)).

> **Status:** the data pipeline, player ratings, match engine (calibrated), series/tournament runners and a
> browser UI with historical teams, league seasons, a fantasy draft, rain/DLS and the Impact Player rule are built.
> See [Roadmap](#roadmap).

## Quick start

Python 3.10+.

```bash
pip install -r requirements.txt
```

### In the browser

```bash
python web_ui.py
```

This opens **http://localhost:5070** (use `--port` to change it, `--no-browser` to not open a tab). It works
offline. Modes:

- **Match / Series:** two saved teams play one match or a series of up to 7.
- **Tournament:** pick teams; single or double round robin, one league or two groups, then semi-finals, IPL-style
  playoffs, a final or none.
- **Home grounds (Tournament, Classic Tournament, League Season):** each side plays half its league games at its
  primary home ground: a nation's most-used ground in its home series (Eden Gardens for India's T20s, the SCG for
  Australia), a franchise's most-used ground that season (Wankhede, Chepauk, ...). The ground brings its own
  conditions (high or low scoring, pace or spin); there is no home advantage beyond that. Knockouts and sides
  without a home (draft teams) use the chosen venues or neutral conditions.
- **Classic Series / Classic Tournament:** a nation over a range of years (ODIs from 1971, T20Is from 2005), e.g.
  Australia 2003-07 v India 2021-24. The squad is the period's 20 most-capped players (15 / 25 / everyone also
  offered), rated on those years, and batting where they batted then. Ratings for those years are either blended
  with the player's career (default; the most accurate) or based on those years only (closer to what he did then,
  noisier).
- **League Season:** any season of eleven franchise leagues (IPL 2008-26, BBL, PSL, CPL, SA20, ILT20, BPL, LPL,
  MLC, T20 Blast, Super Smash) with the real squads (everyone who played for each franchise that season), that
  season's overseas limit (taken from the real XIs: IPL 4, BBL 3, ...), a double round robin and IPL-style
  playoffs. IPL games from 2023 use the Impact Player rule.
- **Fantasy Draft:** you and computer teams draft 15-man squads in snake order from the player pool of chosen
  years (full-member internationals, optionally franchise leagues), then play a league with knockouts.
- **Team Builder:** search the ~7,800 rated players, pick 11-15 (with more than 11 the captain picks the XI for
  each match) and save the team. Ten preset national squads are included.

For every run choose the format, the year and whose conditions to play in (full-member internationals or a league),
optionally venues, a seed and whether rain can interrupt play (on by default). The results page has a summary
(points tables with net run rate, knockouts, top performers, records), every match (Previous / Next, match report,
rain notes, run worm, Manhattan, win-probability and partnership charts, scorecard and innings log), sortable batting and bowling tables, the MVP race (official and balanced) and,
after a draft, the draft board. Saved teams go in `data/teams.json` (not in git).

### From Python

```python
from engine import simulate_match, scorecard_text, match_report
from engine.data import search

print(search("t20", "Kohli"))   # [('ba607b88', 'V Kohli', 'India'), ...]  (Cricsheet id, name, team)

def ids(names, fmt="t20"):
    return [next(pid for pid, name, team in search(fmt, n) if name == n) for n in names]

india = {"name": "India", "players": ids([
    "Rohit Sharma", "Shubman Gill", "V Kohli", "SA Yadav", "HH Pandya", "RR Pant",
    "RA Jadeja", "AR Patel", "Kuldeep Yadav", "JJ Bumrah", "Arshdeep Singh"])}
australia = {"name": "Australia", "players": ids([
    "TM Head", "MR Marsh", "JP Inglis", "GJ Maxwell", "MP Stoinis", "TH David",
    "MS Wade", "PJ Cummins", "MA Starc", "A Zampa", "JR Hazlewood"])}

card = simulate_match(india, australia, fmt="t20", comp="t20i_full", year=2024,
                      venue="Wankhede Stadium, Mumbai", seed=1)
print(scorecard_text(card))     # full text scorecard
print(match_report(card))       # short narrative report
```

`card` is a JSON-ready dict with batting and bowling cards, fall of wickets, partnerships, over-by-over runs and
win probability (for worm and Manhattan charts), events (milestones, wickets, big overs, hat-tricks), the turning
point, an impact score per player, the player of the match and the result.

Useful options:

| Argument | Meaning |
|---|---|
| `fmt` | `"t20"` or `"odi"` |
| `comp`, `year` | whose conditions to play in: `"t20i_full"` / `"odi_full"` (full-member internationals) or a league (`"ipl"`, `"bbl"`, `"psl"`, `"cpl"`, `"sat"`, `"ilt"`, `"bpl"`, `"lpl"`, `"mlc"`, `"ntb"`, `"ssm"`) |
| `venue` | ground name; known grounds have a fitted scoring factor |
| `seed` | makes the match reproducible |
| team `"squad": [ids]` | give 12+ players and let the captain pick a balanced XI |
| team `"order"`, `"keeper"`, `"captain"` | override the batting order, keeper and captain |
| team `"years": [2007, 2011]` | rate the players on those years (and use their batting slots of then) |
| team `"years_mode"` | `"blend"` (default: shrunk toward the career) or `"only"` (those years alone) |
| team `"overseas"`, `"max_overseas"` | league overseas players and the limit per XI (IPL 4, BBL 3) |
| `rain_on` | rain interruptions for the host country, with DLS targets (default off in the library) |
| `impact_player` | IPL Impact Player rule (default: on for IPL from 2023) |

**Picking the XI from a squad.** With more than 11 players the captain picks the XI for each match. Skill is
each player's expected runs value per match from his ratings (batting weighted by the balls his position faces,
bowling by the overs he bowls); how selectors trade that against keeping, team balance (4-6 specialist bowlers),
spin-friendly venues and experience is learned from every real full-member XI since 2003/2006
(`engine/selection.py`, `python -m engine.fit.fit_selection`). Each match the ratings are redrawn within their
uncertainty, so clear leaders always play and close calls rotate. Same seed, same XI.

**Impact Player (IPL 2023 onwards).** The engine uses the substitute *rationally* instead of copying how teams
use it (`engine/impact.py`). Every decision compares, in runs, what the side gains by using it now with what waiting
is worth. The XI is chosen after the toss with the substitute plan in mind (for example, start with an extra bowler
and bring in a batter only if wickets fall early). A batter can come in at any wicket, valued against the chance of
a later collapse taken from real innings in the same position; a bowler or all-rounder can come in at the end of
any over (often for a bowler who has bowled out); otherwise the swap is made at the innings break. The scorecard
marks the two players with ↑ in and ↓ out, and both are credited with the appearance.

**Rain and DLS.** With rain on, a match is interrupted as often as real matches in the host country are (from
Cricsheet: about a quarter of ODIs in Sri Lanka and the West Indies, a fifth in England, under a tenth in India,
Pakistan and Australia), replaying a real match's pattern: overs lost before the start, the first innings ended
early, the chase reduced, or play stopped for good. Targets and par scores use the DLS Standard Edition formulas
with a resource table in the Duckworth-Lewis form: how resources fall with overs is fitted to what a side scores in
a shortened innings, the cost of wickets to real innings. The targets come out close to the official table's (a
20-over ODI chase: 56.6% of the resources, as in the official table) and are fair: a chase revised by DLS is won about
as often as a normal one. A chase needs 20 overs (ODI) or 5 (T20) for a result. Bowler quotas shrink with the
innings; the powerplay is scaled, and the last overs are death overs however short the innings (`engine/rain.py`).

Historical teams and drafts from Python:

```python
from engine.history import historical_team
from engine.draft import Draft

aus = historical_team("odi", "Australia", 2003, 2007)    # {"name", "squad", "years"}
ind = historical_team("odi", "India", 2011, 2011)
card = simulate_match(aus, ind, fmt="odi", comp="odi_full", year=2011, seed=1)

d = Draft("t20", 2015, 2025, ["London", "Mumbai", "Sydney", "Cape Town"], user=None, seed=1)
d.run_cpu()                                              # computer drafts every team
teams = d.team_specs()                                   # ready for play_tournament
```

Teams from different eras can meet. Ratings are relative to each player's own era, so the 2007 Australians can play
the 2023 Indians under 2023 conditions, or under 2007 conditions.

## Series and tournaments

```bash
python -m engine.tournament examples/t20_world_cup_style.json --out results/wc
python -m engine.tournament examples/odi_series_india_australia.json --out results/series
```

This prints the points tables (with net run rate), knockout results, winner, player of the series and top performers.
It writes `summary.json` (tables, knockouts, batting / bowling / fielding stats, records, MVP rankings) plus
`matches/NNN.json` and `NNN.txt` (full and text scorecard) for every match. Players in the config can be given by
name or Cricsheet ID, and a 12+ player `squad` lets the captain pick the XI.

From Python:

```python
from engine.tournament import play_series, play_tournament, save
res = play_tournament(teams, fmt="t20", comp="t20i_full", year=2024,
                      groups=2, knockout="semis", seed=1)   # or knockout="ipl" / "final" / "none"
save(res, "results/my_cup")
```

- **League stage:** single or double round robin (`rounds`), optionally in groups.
- **Knockouts:** semi-finals (1v4, 2v3; with two groups A1vB2, B1vA2), IPL-style playoffs (Qualifier 1,
  Eliminator, Qualifier 2, Final), a final, or none.
- **Points table:** net run rate by the ICC method (a side bowled out is charged its full quota of overs; super
  overs don't count; in a DLS match the side batting first is credited with the par score in the chase's overs;
  no-results earn a point each and are left out). With `rain=True`, knockouts get a reserve day, after which the
  higher-placed side goes through.
- **Records:** highest and lowest totals, top scores, best figures, fastest 50s and 100s, biggest and narrowest wins,
  super overs.
- **MVP rankings:**
  - *official*: win probability added; it also picks the player of the series;
  - the player of the match: the balanced score below plus win probability added converted into runs (a whole win
    is worth about 150 runs in a T20, from the chase win model), so a match-winning 70 beats a 6 off 3 balls;
  - *balanced*: runs + 25 per wicket + 5 per catch/stumping + 25 per team win, plus strike-rate and economy
    bonuses.

## How it works

1. **Data**: [Cricsheet](https://cricsheet.org) ball-by-ball files for ODIs, T20Is and eleven T20 leagues, plus
   Wikipedia/Wikidata for batting hand, bowling type, and career totals of Afghanistan players (Cricsheet withholds
   Afghanistan matches) and of ODI players from before Cricsheet (1971-2002). Pre-2002 strike rates come from
   Wikipedia's match summaries (top scorers' runs and balls in about 1,600 pre-2002 ODIs), corrected for the
   top-scorer bias measured on 2003-12 matches where Cricsheet has the truth.
2. **Ratings**: every player gets batting and bowling indexes for runs, dismissals, dots, fours and sixes, overall
   and by phase (powerplay / middle / death). They are fitted with three things:
   - **opponent adjustment**: runs against weak attacks count for less;
   - **shrinkage**: small samples are pulled toward the player's role and team, so a debut 98* doesn't make a star;
   - **era adjustment**: everyone is rated against their contemporaries.

   They are checked by predicting 2024-26 from data up to 2023.
3. **Engine**: every delivery's outcome comes from baseline × batter × bowler, adjusted by the match situation. The
   situation effects are learned from real matches, not hand-tuned:
   - settling in (new batters score slowly);
   - intent when setting a total or chasing (a DLS-style par / pressure model);
   - batting hand v bowling type;
   - venue, and the day's pitch (internationals);
   - pace v spin: each ground's edge for spinners over seamers, plus the day's (a turner one day, a green top the
     next), fitted from how spinners and seamers did against expectation in every real match since 2012.

   Captains plan the whole bowling innings from each bowler's real usage (bowling more of whichever type the pitch
   helps) and react during it: a bowler going for more than expected loses overs and a wicket-taker can be kept
   on, as much as real captains do (fitted on every over since 2015), pick XIs from squads (learned from real
   selections), choose batting orders from position history, and make toss decisions at real rates. Ties go to
   super overs. Rain, DLS and the Impact Player are described above.

Design and decisions: [`docs/engine_design.md`](docs/engine_design.md). Calibration log:
[`docs/engine_progress.md`](docs/engine_progress.md).

## Does it look like real cricket?

`python -m engine.calibrate` re-plays real matches (484 full-member T20Is 2021-26, 355 IPL games 2022-26, 732
full-member ODIs 2015-26) with the real XIs, batting orders, toss, venue and year. It then compares the simulated
results with what happened:

| First innings | Real T20I | Sim | Real IPL | Sim | Real ODI | Sim |
|---|---|---|---|---|---|---|
| Average total | 168.8 | 167.5 | 186.3 | 187.4 | 267.5 | 266.4 |
| Spread (SD) | 37.7 | 38.8 | 35.2 | 34.4 | 69.7 | 70.8 |
| Wickets | 6.74 | 6.77 | 6.28 | 6.40 | 8.08 | 8.07 |
| Powerplay / death run rate | 8.01 / 9.94 | 8.03 / 9.99 | 9.08 / 11.04 | 9.13 / 11.11 | 4.87 / 7.95 | 4.77 / 7.75 |

Known gaps: too many all-out innings (T20I 17% v 12.6%) and too few ODI hundreds (-13%). Details are in
[`docs/engine_progress.md`](docs/engine_progress.md).

## Rebuilding the data

The repository includes the derived data (ratings and fitted tables) so the engine works straight after cloning.
To rebuild everything from scratch, for example each season:

```bash
python scripts/fetch_cricsheet.py      # downloads Cricsheet zips into data/raw/ (cached; --refresh to update)
python scripts/build_raw_stats.py      # per-player raw stats with phase splits
python scripts/build_afghanistan.py    # Afghanistan players from Wikipedia (Cricsheet withholds their matches)
python scripts/fetch_styles.py         # batting hand / bowling type from Wikipedia (cached, ~10 min first time)
python scripts/build_pre2002.py        # pre-2002 ODI players' career totals from Wikipedia lists
python scripts/fetch_wiki_matches.py   # ODI match summaries (top scorers' runs and balls), cached
python scripts/build_ratings.py        # player ratings -> data/ratings_{odi,t20}.json (+ _years, _comps)
python scripts/build_league_presets.py # every season of 11 leagues (+ home grounds) -> data/league_seasons.json
python scripts/build_home_grounds.py   # national sides' home grounds -> data/home_grounds.json
python -m engine.fit.fit_basics        # dismissal mix, run splits, extras, free hit
python -m engine.fit.fit_situation     # settling in, intent, par, win probability, matchups
python -m engine.fit.fit_toss          # toss decisions
python -m engine.fit.fit_venues        # venue factors and pitch variation (~25 min: replays every real match)
python -m engine.fit.fit_selection     # XI selection model
python -m engine.fit.fit_impact        # Impact Player tables (balls still to come, real wicket timelines)
python -m engine.fit.fit_rain          # rain profiles by host country
python -m engine.fit.fit_dls           # DLS resources (after the other fits: it replays shortened matches)
python -m engine.fit.fit_spin          # pace v spin edge by venue and day
python -m engine.fit.fit_reactive      # reactive bowling changes
python -m engine.calibrate             # compare simulated v real
python tests/test_engine.py            # laws and bookkeeping invariants
python tests/test_tournament.py        # points, net run rate, stats totals, knockout structure
python tests/test_selection.py         # also test_history.py, test_draft.py
```

Optional checks: `python scripts/validate_ratings.py` (out-of-sample test of the ratings) and
`python scripts/verify_players.py` (raw stats v Wikipedia career figures).

## Project layout

```
engine/            match engine (library)
  match.py         match / innings state machine, scorecard, super overs, win probability
  ballmodel.py     per-delivery outcome model
  captain.py       XI selection, batting order, bowling plan, toss
  situation.py     settling in, intent, par, matchups, win probability
  conditions.py    venue factor, pitch of the day
  periods.py       ratings for a year range
  selection.py     XI selection learned from real XIs
  impact.py        IPL Impact Player decisions
  rain.py          rain interruptions and DLS
  history.py       historical (nation + years) teams
  draft.py         fantasy draft
  render.py        text scorecard and match report
  tournament.py    series and tournaments: points tables, NRR, knockouts, stats, records, MVP
  calibrate.py     replay real matches and compare
  fit/             scripts that learn the engine's tables from Cricsheet
web_ui.py          Flask server for the browser UI
webui/             the page: index.html, style.css, app.js (no external scripts)
scripts/           data pipeline: download, raw stats, Afghanistan, pre-2002 players, styles, ratings,
                   league presets, validation
data/              ratings_*.json (+ ratings_*_years.json for year ranges), engine/*.json (fitted tables), raw_stats/ (derived),
                   teams_default.json (preset squads);
                   raw/ and cache/ are rebuilt locally and not in git
docs/              design document and calibration/progress log
examples/          tournament and series configs
tests/             engine and tournament tests
```

## Roadmap

- [x] Data pipeline, raw stats with phase splits, verification against real careers
- [x] Ratings with opponent adjustment, shrinkage and era adjustment
- [x] Match engine (Tier 0-2 of the design), calibrated against real matches
- [x] Series and league/tournament runners (points table with net run rate, knockouts, stats, records, MVP)
- [x] Browser UI (Flask, works offline): single match, series, World Cup / IPL-style tournaments, team builder,
      results pages with match reports, stats tables, records and MVP race
- [x] Historical teams (ratings for a year range), fantasy draft, worm / Manhattan / win-probability charts
- [x] Pre-2002 ODI players from Wikipedia career totals (ODI classic teams from 1971); strike rates from match
      summaries
- [x] League seasons (every season of 11 leagues) with overseas limits; IPL Impact Player rule
- [x] Pace v spin pitches; reactive bowling changes
- [x] Rain interruptions and DLS; partnership charts
- [ ] Later: match settings panel (overs, toss, pitch), player-v-player matchups, alternate-history career mode

## Data, credits and licences

- Ball-by-ball data: [Cricsheet](https://cricsheet.org). Cricsheet's data is made available under the Open Data
  Commons Attribution License; check cricsheet.org for the current terms. Thanks to Cricsheet for an outstanding
  free resource. Cricsheet currently withholds matches involving the Afghanistan men's team; those players are
  rated from franchise-league data and Wikipedia career totals.
- Player attributes, Afghanistan and pre-2002 career totals, and pre-2002 match summaries:
  [Wikipedia](https://en.wikipedia.org) (CC BY-SA) and [Wikidata](https://www.wikidata.org) (CC0).
- Inspired by an earlier Test-match simulator by the same author.

Code licence: [MIT](LICENSE). Data keeps the licences of its sources above.

This is a fan project. It is not affiliated with the ICC, any board, league or team.
