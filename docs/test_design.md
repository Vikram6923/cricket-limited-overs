# Test match mode: data, ratings and probes (Phase 1)

The plan is `docs/test_match_plan.md`. This file records what Phase 1 built and measured, and what the
measurements mean for the engine in Phase 2. Numbers are from the data as fetched on 2026-11-15.

## Sources

| Source | What it gives | Where it lands |
|---|---|---|
| Cricsheet `tests_male_json.zip` | 899 men's Tests ball by ball, 2001-2026 | `data/raw_stats/players_test.json`, `years_test.json`, `coverage_test.json` |
| The old Test simulator's folder (`../cricket`, read only) | One row of career totals for every Test cricketer since 1877; runs per wicket and runs per over by year | `data/raw_stats/test_careers.json`, `years_test_pre.json` |

Cricsheet coverage by Test number: complete from 2007 (2006: 85%), about half of 2003-05, three Tests before
that. 164 numbers are missing between the first and last Test it has, 92 of them on Cricsheet's own missing
list; Afghanistan's Tests are withheld. Every match has six-ball overs. An innings records `declared`; a match
has its list of `dates` (days with play). There is no day, session or clock on a ball and no record of a new
ball being taken.

### The career rows

`scripts/build_pre_tests.py` reads `<nation>players.txt`, `names.txt`, `eradata.txt` and `er_data.txt` from the
old folder and writes our own files; the old folder is never changed and is needed only to rebuild them. The
change from the plan: the plan took these totals from Wikipedia and kept the old files as a cross-check. The old
files are used directly, because they are more complete (balls faced for 1,519 players, first-class record, year
of birth, Tests as keeper and as captain, innings as opener, bowling style) and need no fetching.

- 3,266 players. 3,167 have a known ID: the Cricsheet ID, or the ID the ODI ratings already use for the same
  man. The other 99 get `tc_<country>_<name>_<first year>`.
- Linking is by name and then checked, because names repeat (two SP Joneses, five Rashid Khans, two JP Duminys)
  and the old folder's own name-to-ID list holds one ID per name. A register entry is accepted only if its
  Cricsheet Tests are for the row's country and within its years, or, with no Cricsheet Tests, if the row ended
  by 2008 and the ESPNcricinfo number is of the same generation.
- A man who played for two countries has a row under each. Most such rows repeat his whole career (Kardar,
  Wessels, Rankin) and are counted once; where they differ (Ballance, Moor) they are added up.
- Two-source check: 430 careers of 2008-2023 are in both sources; 385 agree exactly on Tests, runs and wickets.
  The rest differ by one to five Tests: Tests Cricsheet lacks (the old rows are right) or rows not updated since
  mid-2025 (Cricsheet is right). A difference under three Tests is ignored; from three up it becomes the
  player's part outside Cricsheet.
- 2,212 players have no ball-by-ball record at all; 242 have a part outside it (Tendulkar: 118 of 200 Tests).
- 17 Cricsheet Test players have no career row (one-Test players and recent debutants); they are rated from
  ball-by-ball data alone.

## Ratings (`data/ratings_test.json`)

Same model as ODI and T20 (`scripts/build_ratings.py`, `MODELS["test"]`): baseline x batter index x bowler
index for runs, wickets, dots, fours, sixes, fitted by alternating updates with empirical-Bayes shrinkage toward
role group x team level. One phase, `"all"`. 3,268 players:

- 1,070 from ball-by-ball data (source `ball_by_ball`);
- 242 of those also have a `pre` block from the totals of their part outside Cricsheet. Their career rating is
  the precision-weighted blend of both parts (`ball_by_ball+career_totals`), and a year range that ends before
  their covered Tests uses the `pre` block alone;
- 2,198 from career totals alone (`career_totals`): dismissal index from the batting average, wicket and
  economy indexes from balls, runs and wickets, each against the player's own era and shrunk by sample size.
  The strike rate is his own where balls faced are recorded, otherwise his role's.

Era: baselines for 1877-2000 are the pooled 2007-11 baseline scaled by the era table (runs, fours, sixes by the
run rate; wickets by wickets per ball). Assumption, not measured: the share of balls scored off moves with the
run rate; wides and no-balls stay as in 2007-11.

A role group with fewer than 40 expected events borrows the mean of its like groups (Tests have two part-time
bowlers of unknown type, whose group had a wicket rate of zero). ODI and T20 have no group that small: both
ratings files rebuild as before.

### Checks

Out of sample, skill against "everyone is average" (higher is better), players with 300+ balls:

| | bat runs | bat wkt | bat four | bat six | bat dot | bowl runs | bowl wkt | bowl four | bowl six | bowl dot |
|---|---|---|---|---|---|---|---|---|---|---|
| fit to 2017, predict 2018 on | 20% | 56% | 13% | 16% | 24% | 10% | 39% | 43% | 34% | 31% |
| fit to 2021, predict 2022 on | 7% | 51% | 26% | -20% | 13% | -42% | 34% | 48% | -57% | 9% |
| one year held out (2012, 2016, 2019, 2022), career rating | 47% | 29% | 39% | 41% | 47% | 36% | 28% | 48% | 46% | 55% |

Wicket rates predict well everywhere. Bowlers' economy and six rates predict a held-out year well but forecast
2022 onward worse than "average": scoring rates changed after 2021 (the reference era's six rate is 0.0053 a
ball against 0.0029 in 2008), and a rating cannot see a change of approach coming. This matters for forecasting,
not for replaying a chosen period, which is what the simulator does. Left as measured; not tuned.

Year-range ratings (`engine/periods.py`): on the same four held-out years a window of two years either side
with tau x0.2 for batting and x0.05 for bowling beats the career rating (bat runs 52.5% against 46.5%, bowl runs
37.1% against 35.9%, wickets unchanged). `TAU_SCALE["test"] = {"bat": 0.2, "bowl": 0.05}`.

## Probes (`python -m engine.fit.probe_test`)

Raw rates, not adjusted for who was batting or bowling. rpo = runs off the bat per over; w/100ov = bowler's
wickets per 100 overs; avg = runs off the bat per dismissal.

Matches: 899. Won by runs 329, by wickets 231, by an innings 169, drawn 169 (18.8%), one other. Days with play:
two 9, three 137, four 284, five 468, six 1. Mean 73.5 overs a day with play. Three-innings matches 227,
four-innings 660.

| Innings | Played | Median overs | Declared | Median lead at the declaration |
|---|---|---|---|---|
| 1 | 899 | 100 | 171 | 543 (the score) |
| 2 | 895 | 94 | 92 | 282 |
| 3 | 887 | 73 | 267 | 414 |
| 4 | 660 | 57 | 0 | |

Follow-on: possible (lead 200+) 176 times, enforced 91 (52%). By lead: 200-249 18 of 63, 250-299 13 of 34,
300-399 40 of 57, 400+ 20 of 22.

Fourth innings, by target (won / drawn / lost by the side batting): under 100: 83 / 1 / 0; 100-199: 90 / 5 / 15;
200-299: 41 / 35 / 56; 300-399: 15 / 36 / 97; 400+: 2 / 23 / 161.

Ball age (overs since the innings began, modulo 80):

| Overs | Pace balls | rpo | w/100ov | avg | Spin balls | rpo | w/100ov | avg |
|---|---|---|---|---|---|---|---|---|
| 0-9 | 249,917 | 3.05 | 10.87 | 27.6 | 51,737 | 3.01 | 10.72 | 27.5 |
| 10-19 | 186,061 | 3.11 | 9.93 | 30.7 | 89,968 | 3.04 | 9.26 | 31.7 |
| 20-39 | 273,083 | 3.10 | 9.90 | 30.6 | 211,029 | 3.08 | 8.80 | 33.8 |
| 40-59 | 203,654 | 3.12 | 10.34 | 29.4 | 181,180 | 3.12 | 8.61 | 35.1 |
| 60-79 | 127,846 | 3.17 | 10.82 | 28.5 | 150,474 | 3.17 | 8.68 | 35.1 |

Pitch wear (overs bowled in the match before this over):

| Overs | Pace balls | rpo | w/100ov | avg | Spin balls | rpo | w/100ov | avg |
|---|---|---|---|---|---|---|---|---|
| 0-89 | 322,757 | 3.09 | 9.47 | 32.1 | 163,485 | 3.14 | 6.76 | 44.7 |
| 90-179 | 301,776 | 3.18 | 10.57 | 29.4 | 177,714 | 3.20 | 8.96 | 34.7 |
| 180-269 | 242,602 | 3.07 | 10.81 | 27.7 | 177,132 | 3.07 | 9.71 | 30.7 |
| 270-359 | 138,916 | 3.07 | 10.81 | 27.6 | 124,349 | 3.07 | 10.43 | 28.3 |
| 360+ | 34,510 | 2.86 | 11.16 | 25.0 | 41,708 | 2.73 | 9.52 | 27.9 |

Innings x wickets down:

| Innings | 0-2 down: balls / rpo / avg | 3-5 down | 6-9 down |
|---|---|---|---|
| 1 | 211,554 / 3.05 / 39.9 | 222,326 / 3.22 / 45.4 | 119,470 / 3.35 / 21.4 |
| 2 | 206,561 / 3.03 / 39.0 | 196,707 / 3.08 / 38.3 | 125,764 / 3.21 / 20.4 |
| 3 | 173,913 / 3.02 / 33.6 | 151,275 / 3.09 / 33.0 | 85,833 / 3.22 / 18.6 |
| 4 | 100,925 / 3.06 / 30.3 | 86,285 / 2.88 / 31.5 | 45,906 / 2.90 / 15.9 |

Third innings by the batting side's lead at that ball: behind by 200+ 2.94 rpo; behind by under 100 2.79; ahead
by 100-199 2.95; ahead by 200-349 3.41; ahead by 350+ 4.15 (35,037 balls). Second innings ahead by 200-349: 4.04.

Balls the batter has faced in the innings:

| Faced | Balls | rpo | w/100ov | avg |
|---|---|---|---|---|
| 0-9 | 290,336 | 2.64 | 13.52 | 19.1 |
| 10-29 | 404,793 | 3.11 | 11.28 | 27.0 |
| 30-59 | 375,812 | 3.16 | 9.28 | 33.2 |
| 60-119 | 377,640 | 3.21 | 7.80 | 39.9 |
| 120-199 | 188,652 | 3.31 | 7.16 | 44.3 |
| 200+ | 89,286 | 3.44 | 6.79 | 48.0 |

### What the probes settle for Phase 2

- **Settling in is real in Tests and it is about dismissal.** The wicket rate halves between a batter's first
  ten balls and his 200th; the scoring rate moves much less after ball ten. The limited-overs settle table has
  no dismissal part; the Test one gets it, with edges 0, 10, 30, 60, 120, 200. Part of the raw slope is better
  batters lasting longer; the fit divides by the expected rate.
- **Pitch wear is a spin effect.** Spin goes from 44.7 a wicket in the first 90 overs of a match to about 28 after
  270; pace from 32 to about 27. Five wear cells by pace and spin all have over 34,000 balls.
- **Ball age is small and mostly pace.** Pace is best with the new ball (27.6), flattest at 10-39 overs, and
  improves again late, which is the second new ball arriving somewhere near 80 without being recorded. Spin in
  overs 0-9 is a selected sample (pitches where spin opens). Five cells by type are enough.
- **Innings number matters beyond wear**: averages fall from about 40 to about 30 for the top order from the
  first innings to the fourth. Innings x wickets-down cells all have over 45,000 balls.
- **Batting sides accelerate with a lead**, from about 200 ahead: the "push for a declaration" cell. The
  fourth-innings "save" behaviour (2.9 an over with wickets down) is visible too.
- **Declarations and the follow-on can be fitted**: 530 declared innings; 176 follow-on decisions with a clear
  slope by lead. Captains enforce about half the time, not always: the plan's "follow-on at 200" becomes a
  fitted probability by lead and time left.
- **Time**: 73.5 overs per day with play against 90 scheduled is the size of what the overs-lost model has to
  explain (weather, light, slow over rates, early finishes on the last day).
