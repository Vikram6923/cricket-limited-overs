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

# Phase 2: the Test match engine (2026-11-15)

`simulate_match(fmt="test", ...)` plays a Test and returns a scorecard. Files: `engine/test_match.py` (clock,
innings, results, card), `engine/test_captain.py` (declarations, follow-on, bowling spells, nightwatchman, batting
order, XI by rule), `engine/test_situation.py` (the tables at a ball), `engine/fit/fit_test_situation.py` and
`engine/fit/fit_test_captain.py` (the fits, about 12 s and 35 s), `tests/test_test_engine.py`. This phase is not
calibrated against real matches; that is Phase 3.

## How a Test is played

- **Time** is counted in overs: `days` x `day_overs` (5 x 90), three sessions a day. Lunch, tea and stumps are
  events with the score; `card["days"]` has each day's overs, runs, wickets and close-of-play score. A change of
  innings costs 2 overs; what is left of a day is not carried over. When the last day's overs are gone the match
  is drawn. **No overs are lost to weather, light or slow over rates yet** (Phase 3), so every day has its full
  90 overs.
- **Innings**: built on `Scorebook`. An innings ends all out, declared, with the target reached, or when time is
  up (`ended`). Order A, B, A, B, or A, B, B, A after a follow-on. Results: an innings and runs, runs, wickets,
  draw, tie (the side batting last all out with the scores level).
- **A ball**: `BallModel.delivery` with the Test baseline of the year, the two players' indexes, and the product
  of four fitted tables (below). No free hit. Venue factor, pitch of the day and spin edge go through the shared
  `conditions.py` and are all 1 until Phase 3 fits them.
- **New ball**: taken at once at 80 overs of an innings; the ball-age table starts again.
- **Bowling**: two ends, a spell at each. After his over the bowler at that end goes on with a fitted chance;
  otherwise the captain picks from the others by fitted weights. Nobody bowls two overs running; the keeper does
  not bowl.
- **Random numbers**: one stream for the balls, a second for the captains' calls (declarations, follow-on,
  bowling changes). A seed reproduces a Test, also across processes.

## What was fitted, and on how much data

All from the 899 Cricsheet Tests. A table value is observed / predicted, where predicted is the year's baseline
x batter index x bowler index, on 1,715,672 legal balls between rated players.

**Situation (`data/engine/test_situation.json`)**: four tables fitted jointly by backfitting (15 rounds), so
what they share is counted once. A state cell is shrunk toward its innings x wickets parent with 400
pseudo-balls, the parent toward 1.

| Table | Cells | Balls per cell | Wicket multiplier | Runs multiplier |
|---|---|---|---|---|
| Settling in, balls faced 0 / 10 / 30 / 60 / 120 / 200 | 6 | 88,881 to 402,012 | 1.05, 1.00, 0.97, 0.95, 1.01, 1.04 | 0.85, 1.00, 1.02, 1.04, 1.08, 1.09 |
| Pitch wear, pace, match overs 0 / 90 / 180 / 270 / 360 | 5 | 34,187 to 319,697 | 1.13, 1.03, 0.94, 0.89, 0.92 | 1.03, 1.01, 0.97, 0.99, 0.98 |
| Pitch wear, spin | 5 | 41,595 to 177,330 | 0.99, 1.01, 0.98, 1.00, 0.95 | 1.04, 1.00, 0.97, 0.99, 0.94 |
| Ball age, pace, overs 0 / 10 / 20 / 40 / 60 | 5 | 126,733 to 270,617 | 1.06, 1.01, 0.99, 0.97, 0.94 | 1.04, 1.02, 0.99, 0.97, 0.97 |
| Ball age, spin | 5 | 51,616 to 210,544 | 1.14, 1.07, 1.03, 0.96, 0.93 | 1.01, 1.02, 1.01, 0.99, 0.99 |
| Innings 1-3 x wickets down (0-2, 3-5, 6-9) x lead (under -200, -100, 0, 100, 200, 350, above) | 54 with balls | 210 to 133,745; 10 cells under 5,000 | 0.74 to 1.38 | 0.90 to 1.30 |
| Innings 4 x wickets down x runs needed per over left (1.5, 2.5, 3.5, 5, 8) | 18 | 2,691 to 36,403 | 0.84 to 1.36 | 0.77 to 1.17 |

The full tables, with the ball count of every cell, are printed by the fit and stored in the JSON (`*_n`).

What the tables say:

- **Settling in is mostly about scoring, not dismissal.** The probe's raw wicket rate halved between a batter's
  first ten balls and his 200th. Once the prediction knows who is batting and bowling, the first ten balls carry
  5% more dismissals and 15% fewer runs, and balls 60-120 are the safest (0.95). The raw slope was better batters
  lasting longer. The dismissal part is in the table as fitted.
- **Wear and innings number are read together.** Wear alone shows pace losing wickets as the match goes on and
  spin flat; the later innings' state cells carry wicket multipliers of 1.0-1.4 for everyone. The product is the
  probe's picture: spin gains on pace through the match. The two are strongly correlated in real matches, so
  neither table should be read alone.
- **The push for a declaration is there**: third innings 350 or more ahead, runs x1.29 and wickets x1.36.
- **Saving the match is there**: last innings, 6-9 down needing 8 or more an over, runs x0.77, dots x1.10,
  wickets x0.91. **A run chase barely is**: at 3.5-5 an over needed the runs multiplier is 0.87-0.95. Real sides
  seldom go for them, and the engine copies that. A cell is called "save" when its runs multiplier is under 0.9
  and "chase" above 1.08 (labels on the over log and one event; they change nothing).

**Captaincy (`data/engine/test_captain.json`)**:

| Call | Model | Data |
|---|---|---|
| Toss | bat with probability 0.682 | 899 tosses |
| Declare, innings 1 | logistic at each over-end: runs, wickets down, overs left, a batter in the nineties | 171 declarations in 30,266 over-ends from 237 runs up |
| Declare, innings 2 | logistic: lead, runs, wickets, overs left, nineties | 92 in 45,923 over-ends from a lead of -181 up |
| Declare, innings 3 | logistic: lead, overs left, runs an over the other side would need, wickets, nineties | 267 in 38,557 over-ends from a lead of 47 up |
| Follow-on | logistic: lead, overs left, overs the bowlers have just bowled | 176 chances, 91 enforced |
| Spell goes on | table by kind (specialist pace, specialist spin, part-timer) x overs in the spell (1 to 7, 8-9, 10-12, 13-16, 17+) x new ball due, times a logistic correction for runs and wickets in the spell against prediction and overs bowled in the innings | 162,059 pace, 99,882 spin, 18,541 part-timer decisions |
| Who comes on | weight = career overs per match x kind by ball age x kind by wear x kind by rest since he last bowled x overs-per-match band, fitted by iterative scaling to the bowler chosen | 61,242 choices |

- Below the lowest lead (or first-innings score) at which anyone has declared, nobody declares.
- A batter in the nineties cuts the odds of a declaration by a factor of 6 to 9 (coefficients -1.9 to -2.2). The
  old simulator had this as a rule; here it is fitted.
- Pace spells: 95% go on after one over, 55-60% after six to eight. Spin: 84-90% at every length. When the new
  ball is due, about half the spinners and two thirds of the part-timers come off.
- A bowler who has gone for 10 more than predicted in the spell is 0.3-0.5 less likely (log odds) to go on; a
  wicket more than predicted, 0.4-0.45 more likely.
- **Tiredness does not show in the rates.** Observed / predicted (situation tables included) for specialist pace
  by over of spell: wickets 0.98, 1.01, 1.01, 1.04, 1.02 for overs 1-2 to 9-10; by overs already bowled in the
  innings 1.00, 1.01, 1.00, 0.97 up to 30-39. So fatigue acts only through who bowls (spell lengths and rest),
  as the plan said it would if the data showed nothing.

## What is not fitted, and why

| Constant | Value | Why it is not fitted |
|---|---|---|
| Days, overs a day, sessions | 5 x 90, 3 | the playing conditions; `days` and `day_overs` are parameters |
| Overs lost at a change of innings | 2 | the playing conditions |
| New ball | at 80 overs, taken at once | Cricsheet does not record it; the fits assume the same |
| Follow-on mark | 200; 150 in a 3-4 day match, 100 in two days, 75 in one | Law 14.1 |
| Nightwatchman | a wicket with 6 overs or fewer left in the day and one of the top six due: the lowest dismissal index of Nos. 8-10 goes in; not on the last day, not with an explicit batting order | no day data; the plan's rule. `nightwatchman=False` turns it off |
| Spells end overnight | both ends choose afresh each morning, everyone rested | no day data. Real spells cut by stumps look unbroken in the fit, so simulated spells may come out a little short |
| "Overs left" in the fits | drawn match: the overs really still bowled; otherwise the larger of that and 450 minus overs bowled | no clock in the data; forgets overs lost to weather in matches with a result |
| Shrinkage | 400 pseudo-balls (situation cells), 20 pseudo-decisions (spell table), ridge 1.0 (logistic models), 0.5 a cell (choice) | regularisation, as in the limited-overs fits |
| Weight of a man who never bowls | 0.15 overs a match | so that he can be chosen at all |
| Cap on "runs an over needed" as a declaration feature | 8 | keeps the last overs of a match from dominating |
| Player of the match | runs x (era runs per wicket / the match's), era runs per wicket for a wicket, 5 a catch or stumping, 25 for the winning side | the plan's interim award until the win / draw / loss table (Phase 5) |
| XI from a squad | best-batting keeper, four best specialist bowlers with a spinner if there is one, six best batters of the rest | the plan's v1 rule; a learned model is deferred |

## Where this differs from the plan

- **No weather or over-rate losses yet.** The plan puts the overs-lost fit in Phase 3; until then a Test has all
  450 overs, so draws are far too rare (see the numbers below).
- **The new ball is always taken at 80.** The plan lets the captain wait when spin is well ahead; that needs the
  spin edge, which is fitted in Phase 3.
- **Hand x bowling-kind matchups, venue factors, pitch of the day and the spin edge are not fitted for Tests
  yet.** The engine reads the last three through `conditions.py`, so Phase 3 only has to add the files.
- **No promotion of a hitter in a declaration push**; the batting order changes only for the nightwatchman.
- **Two fit scripts**, not one per topic, and the tables are `test_situation.json` and `test_captain.json`.
- **`Match(fmt="test")` raises** because the format has no over limit (no format name in `match.py`); the one
  dispatch is in `simulate_match`. `render.py` reads `label`, `declared` and `days` if a card has them, without
  asking the format. `match_report` gives a plain list of scores for a match played over days; the report by days
  is Phase 4.
- **Not wired to anything else**: series, tournaments, the server and manual captaincy do not accept Tests yet
  (Phases 4 and 6). `TestMatch` refuses arguments it does not know (`rain_on`, `control`, `skill` ...).

## Sanity numbers (not calibration)

300 Tests, India v Australia with 2023 baselines, seeds 0-299, one run:

| | Simulated | Real, all 899 Tests (probe) |
|---|---|---|
| Won by runs / wickets / an innings / drawn | 43% / 43% / 10% / 4% | 37% / 26% / 19% / 19% |
| Overs bowled per match | 320 | not measured per match; 73.5 a day with play |
| Runs per wicket, runs per over (extras included) | 32.0, 3.49 | 2023 baseline: 29.5 a wicket, 3.15 off the bat an over |
| Innings declared: 1st / 2nd / 3rd | 13% / 5% / 22% | 19% / 10% / 30% |
| Follow-on enforced when on offer | 25 of 42 | 91 of 176 |
| Matches ending on day 2 / 3 / 4 / 5 | 1% / 18% / 56% / 25% | 1% / 15% / 32% / 52% |
| Hundreds, five-fors per match | 1.87, 1.09 | not yet measured |
| Nightwatchmen | 1.1 per match | not in the data; likely too many |

One fixture is not the real mix of sides, so only the large gaps mean anything: too few draws and too many
matches over by day four (no lost overs), too many wins by wickets and too few by an innings. Phase 3 starts
from these. A Test takes roughly 30 ms here (300 in 8 s, one run on this laptop, not a benchmark).

## Tests

`tests/test_test_engine.py` (15 s): the laws and the bookkeeping over 300 Tests in four set-ups (five days; a
named ground; four days; three days of 60 overs): innings order, follow-on only with the lead for it, no bowler
two overs running, the keeper never bowls, a new ball every 80 overs, never more than the scheduled overs, each
day's overs and runs add up to the innings', every total adds up, the result recomputed from the scores, no draw
with time left. Each result type is forced with a scripted ball model (innings and runs with and without the
follow-on, runs, one run, wickets, tie, a blocked-out draw, a win after following on). Seed reproducibility, the
dispatch, the four-innings text scorecard, the clock, and the direction of each fitted call.

# Phase 3: calibration against real Tests

Built 2026-11-15. `python -m engine.calibrate --suite test` replays the 473 Tests between full members of 2015-26
(real XIs, each side's first-innings batting order, toss, ground, year) and compares the simulation with what
happened on the plan's targets. The code is `engine/test_calibrate.py`; every run is kept in
`data/engine/calibration_test.json`.

## Result: 29 of 32 gates met

Final run, 8 replays of each Test (3,784 simulations):

| Target | Real | Simulated | Gate | |
|---|---|---|---|---|
| Runs per wicket | 30.80 | 30.76 | 2% | met |
| Run rate | 3.31 | 3.34 | 2% | met |
| First-innings total, mean | 331.7 | 329.5 | 2% | met |
| First-innings total, spread (SD) | 137.4 | 142.1 | 10% | met |
| Draws | 13.1% | 18.2% | 3 points | **missed by 5.1** |
| Won by an innings | 18.6% | 17.6% | 3 points | met |
| Won by runs | 42.3% | 37.3% | 3 points | **missed by 4.9** |
| Won by wickets | 26.0% | 26.8% | 3 points | met |
| Home wins | 53.4% | 51.3% | 3 points | met |
| Over in 3 days or fewer / on day 4 / went to day 5 | 19.7 / 33.4 / 46.9% | 24.0 / 32.5 / 43.5% | 5 points | met |
| Overs per match | 305.8 | 299.7 | 5% | met |
| Innings all out | 72.6% | 73.6% | 5% | met |
| Overs per innings | 82.0 | 80.1 | 5% | met |
| Chases won, target under 200 | 88.6% | 81.2% | 10 points | met |
| Chases won, target 200-299 | 28.2% | 29.9% | 10 points | met |
| Chases won, target 300+ | 5.6% | 7.2% | reported | |
| Declarations per match | 0.54 | 0.54 | 10% | met |
| Lead at third-innings declarations | 416 | 403 | 10% | met |
| Follow-ons enforced per match | 0.09 | 0.09 | 10% | met |
| Hundreds per match | 1.73 | 1.66 | 10% | met |
| Five-fors per match | 1.30 | 1.08 | 10% | **missed, -17.5%** |
| Double hundreds / ten-fors per match | 0.17 / 0.18 | 0.16 / 0.12 | reported | |
| Spin's share of overs / wickets | 40.5 / 37.0% | 38.9 / 35.0% | 3 points | met |
| Spell length, pace / spin (overs) | 4.07 / 5.31 | 4.16 / 5.27 | 10% | met |
| Overs by the most-used bowler in an innings | 24.8 | 24.2 | 10% | met |
| Dismissals: caught / bowled / lbw / run out / stumped | 61.6 / 18.0 / 16.1 / 2.4 / 1.9% | 60.1 / 17.6 / 16.3 / 2.2 / 1.7% | 2 points | met |

The plan gave no number for three gates; the choices are: total overs 5%, the two chase bands 10 points (about
60 real chases in each).

### The three misses, and why tuning stopped

- **Draws (18% against 13%) and wins by runs (the same 5 points the other way).** The extra draws are matches
  that real sides finish on the last day: real Tests get a result on day 5 in 34% of matches, the simulation in
  about 25%. After a third-innings declaration real sides bowl the other out 76% of the time and draw 22%; the
  simulation 56% and 34%. Less time lost does not fix it: with overs lost scaled to 0.6 the draw gate was met
  (14.9%) but too few Tests reached day 5 (39% against 47%), so that constant was not kept. What is missing is
  how real cricket changes on the last day (attacking fields, a pitch that has worn more in some matches than
  others, batting that fails under pressure); the engine's last-innings table sees only wickets down and runs
  needed per over left. Left open.
- **Five-fors (1.08 a match against 1.30), ten-fors more so.** Wickets are shared too evenly among a side's
  bowlers. The spin edge of the day moved it from 1.05 to 1.11; the rest would need a bowler's form on the day,
  which the engine does not have in any format.

### The runs, in order (4 replays each unless said)

| Step | Gates met | Draws | Note |
|---|---|---|---|
| Phase 2 engine as committed | 21 of 32 | 5.1% | no weather; 27% of Tests went to day 5 (real 47%) |
| + overs lost by host | 27 | 18.1% | match length met at once |
| + home edge | 29 | 19.0% | home wins 43.8% -> 51.6% (real 53.4%) |
| + spin edge by ground and day | 26 | 16.7% | runs per wicket fell to -2.5% (see the pitch draw below) |
| + venue factor | 26 | 17.5% | |
| + pitch of the day | 29 | 20.4% | first-innings spread -3% -> +4% |
| overs left from the match dates (refit) | 29 | 19.4% | |
| overs lost: dry and wet matches | 28 | 17.5% | |
| overs left = scheduled time as seen then (refit) | 27 | 16.5% | |
| pitch draw leaves average rates unchanged | 28 | 18.4% | runs per wicket -1.9% -> +0.5%, innings length met |
| a draw's last-hour overs not counted as lost | 28 | 18.7% | no effect |
| overs lost scaled by 0.6 (trial, not kept) | 27 | 14.9% | day 5: 39% against 47% |
| as committed, 8 replays | 29 | 18.2% | |

## What was fitted

`python -m engine.fit.fit_test_conditions` (about 40 s) -> `data/engine/test_conditions.json`, `spin_test.json`;
`python -m engine.fit.fit_test_venues` (about 2 minutes) -> `data/engine/venues_test.json`.

| Table | Fitted on | Result |
|---|---|---|
| Host of a ground | 899 Tests | 84 grounds: the side with the most Tests there, when one side is alone at the top |
| Overs lost in a day | 898 Tests, totals only | two kinds of match: dry (94.3%; 56% of days lose nothing, 32% about 5 overs; mean 6.8 a day) and wet (5.7%; mean 41 a day, a fifth of days washed out). A host has its own share of wet matches: England 10%, Bangladesh 11%, Australia and New Zealand 3.6%, Zimbabwe 2.6% (shrunk toward the pooled share with 20 matches) |
| Home edge | 875 Tests with a home side | the home side scores 3.6% faster and is dismissed 9.7% less often per ball than the visitors, after the ratings. Similar for every host (wickets -6.6% to -11.6%) |
| Spin edge | 737 Tests | between grounds SD 0.15 on wickets (Dubai, SSC Colombo, Chennai most for spin; North Sound, Centurion least); day to day SD 0.26 |
| Venue factor | 894 Tests replayed 3 times | between grounds SD 3.2% runs, 6.8% wickets |
| Pitch of the day | 783 matches at grounds with 3 or more | SD 7.4% on the run rate, 17.7% on the wicket rate, uncorrelated (0.04) |

### How overs lost are estimated, and what that cannot see

Cricsheet has no clock, so a match gives one number: scheduled overs minus overs bowled minus 2 for each change
of innings. A draw used all its days, so its loss is known, less up to 15 overs if it was agreed in the last
hour. A decided match ended at an unknown point of its last day, so its loss over the earlier days is known to
within that day's overs (taken as equally likely from 1 to 90). The daily distribution, on a grid of 5 overs, is
the maximum-likelihood one for those totals; days are independent within a dry or a wet match. It cannot see
time made up on later days or the extra half hour, and it treats which matches were drawn as if rain had nothing
to do with it. The plan's checks on it: overs in decided Tests by the day they ended are within 2% (day 3: 224
real, 224 simulated; day 4: 297, 295; day 5: 366, 362); simulated draws use 376 overs against 347 real, so
simulated draws need less rain than real ones, which is the miss described above. Draw rate by host is in the
calibration file (England 10% real, 19% simulated; Sri Lanka 6.5%, 22%; West Indies 24%, 21%).

### Two corrections to the Phase 2 fits

Both are in the "overs left" estimate that the situation and captaincy fits read (`overs_left` in
`engine/fit/fit_test_situation.py`); both tables were refitted.

1. For a decided match Phase 2 used 450 minus the overs bowled so far, which forgets rain. A side batting out a
   rain-hit match looked as if it had time to spare, so the "save the match" cells were filled mostly by sides
   that did save it.
2. For a draw Phase 2 used the overs that really were still bowled, which knows about rain that had not yet
   fallen. Captains then seemed to declare with less time in hand than they thought they had, and simulated
   captains (who see the schedule) declared about 20 overs late.

Now "overs left" is the scheduled time left as the players saw it: the match's playing time (to the end of day
5 in a draw; to its last day, taken as half used, in a decided match), with lost overs spread evenly over it,
plus the days a decided match never reached.

## Constants that are not fitted

| Constant | Value | Where | Why not fitted |
|---|---|---|---|
| Last day of a decided match | half used (45 overs), or 1-90 equally likely | `fit_test_situation.py`, `fit_test_conditions.py` | Cricsheet does not record the hour a match ended |
| Last hour | 15 overs | `fit_test_conditions.py` | playing conditions: when a draw may be agreed |
| Loss grid | 5 overs | `fit_test_conditions.py` | resolution of the estimate, not a behaviour |
| Shrink for a host's wet share | 20 matches | `fit_test_conditions.py` | a prior weight, as `SHRINK_BALLS` is |
| Hosts need 15 Tests for their own share | 15 | `fit_test_conditions.py` | below that the pooled share is used |
| An early close | up to 10 overs lost come at the end of the day and are called "bad light and a slow over rate"; more is "rain" at a random point of the day | `engine/test_conditions.py` | no data on when in a day time is lost, or why |
| Pitch draw less half its variance | from the fitted SDs | `engine/test_match.py` | not a free number: it makes the draw leave average rates unchanged. Without it the wicket rate rose 1.6% and innings were 2% short |
| Minimum for a spin-edge match | 300 balls of pace and of spin | `fit_test_conditions.py` | sample floor |

## Differences from the plan

- **Home advantage** is a fitted edge on the batting of both sides (home up, visitors down by half the gap
  each), applied when one side is the host of the ground or `host=` is given. The plan said "fit it and apply
  it when a series has a host"; a single match now has it too, from its venue.
- **The host of a ground** is counted from the data (who has played there most), since Cricsheet has no country
  field. Pakistan's Tests in the UAE therefore count as home Tests. `data/home_grounds.json` is Phase 4.
- **Overs lost** are fitted from all matches with the last day treated as unknown, not only from matches that
  reached the last day (plan section 3), and as dry and wet matches rather than one distribution a day.
- **The new ball** is still always taken at 80 overs. The plan's "wait when spin is well ahead" was not added:
  Cricsheet does not record when it was taken, so there is nothing to fit or check it against.
- **No hand x bowling kind matchups for Tests** (plan section 2 lists a refit). Not done.
- **No aggression bars for Tests** (the runs v risk curve). They are for a person's captaincy: Phase 6.
- **No era suite** (plan section 7: each decade's classic sides in that decade's baseline). Not done; nothing
  before 2015 has been checked beyond the Phase 1 ratings tests.
- **The Test calibration lives in `engine/test_calibrate.py`**; `engine/calibrate.py` only passes `--suite test`
  on to it, as `simulate_match` does for the engine.
- **Scheduled days.** Cricsheet does not say which Tests were scheduled for four days; all are replayed as five.
- **Replays use each side's first-innings batting order**, so nightwatchmen never appear in calibration.
- Shared code touched: `engine/conditions.py` (the Test competitions join `PITCH_COMPS`), `engine/fit/fit_venues.py`
  (the fit after the replays is a function Tests can call), `engine/calibrate.py` (the dispatch), `engine/render.py`
  (a day's lost overs in the close-of-play line). The golden test passes.

# Phase 4: Test series and results pages

Built 2026-11-15. Tests can now be played from the browser as a Match / Series or a Classic Series; the computer
plays both sides (captaining a Test is Phase 6).

## What was built

| Part | Where | What it does |
|---|---|---|
| Test series | `engine/test_series.py` | `play_test_series(a, b, n, host=...)`: 1 to 6 Tests, all played; the result ("India won the series 2-1", "Series drawn 1-1"; draws counted); the same result shape as a limited-overs series, so it is saved and shown the same way. `play_series(..., fmt="test")` sends a Test series here |
| Host | `engine/test_series.py` | A series is played in a country: the first side's by default, or `host="Australia"`, or `host="neutral"`. Its grounds are used in turn, it sets the weather, and the side whose nation it is gets the home edge of Phase 3 |
| Grounds | `scripts/build_home_grounds.py` -> `data/home_grounds.json` (`test`, `test_grounds`) | Each host's Test grounds, most used since 2019 first, at most six |
| Test statistics | `engine/test_series.py` | The limited-overs batting, bowling and fielding tables plus best match figures and ten-wicket matches; wins by an innings and by wickets among the records |
| Ranking and player of the series | `engine/test_match.py`, `engine/test_series.py` | Every match keeps each player's points in four parts (runs, wickets, catches, the win) as `card["points"]`; the series adds them up. It replaces "win probability added", which needs the win / draw / loss table of Phase 5 |
| Report by days | `engine/test_report.py` | "Day 2: Australia were bowled out for 285 (Smith 72; Bumrah 5/61), a deficit of 115. At stumps India 102/1, lead by 217." Declarations, the follow-on, days with no play, a draw "spoiled by the weather" |
| Day strip | `engine/test_report.py` (`day_strip`) | Lunch, tea and stumps of every day with how the batting side stands; the last row is the result |
| Classic Test sides | `engine/history.py` | A nation over any years from 1877: "West Indies 1980-85" against "Australia 1999-2003" |
| Preset squads | `scripts/build_test_presets.py` -> `data/teams_default.json` | Nine "… Test 2025" squads: the 15 players with the most Tests in 2024-25 |
| Server | `server/core.py`, `runs.py` | The formats come from one list (`FMTS`, `LIMITED`). League and domestic seasons, tournament, draft, auction, two players and careers refuse a Test with one sentence. A Test cannot be captained yet |
| Pages | `webui/testmatch.js` and small changes elsewhere | Format T20 / ODI / Test; chips 1 / 2 / 3 / 5 Tests; "Played in"; both innings in the score ("400 & 444/7d"); a tab for each of up to four innings, declared and follow-on marked; the day strip; the lead over the match in place of the run worm (innings shaded, day lines); a Manhattan and the partnerships for each innings; Team Builder shows Test ratings |

## Checked in the browser (port 5071)

India v Australia, five Tests in India (3-1, one drawn); West Indies 1980-85 v Australia 1999-2003 on neutral
grounds; the match centre's four tabs; the batting, bowling and Best players tables; a phone-width screen (no
sideways scroll). Choosing another mode sends the format back to T20 and greys out Test. No console errors.

## Constants that are not fitted

| Constant | Value | Where | Why not fitted |
|---|---|---|---|
| "Now" for a host's grounds | Tests since 2019 | `scripts/build_home_grounds.py` | A choice of what "home" means today: Pakistan played its home Tests in the UAE until 2019 |
| Grounds in a series | at most 6 | `scripts/build_home_grounds.py` | A five-Test series visits five grounds |
| A saved side's nation | at least 6 of its players | `engine/test_series.py` | A rule for whose home it is, as the limited-overs home ground uses |
| Preset squads | 15 players, Tests of 2024-25 | `scripts/build_test_presets.py` | A choice of squad, not behaviour |
| Report wording | fifties and four-wicket hauls are named; 15 lost overs are mentioned; 90 lost overs "spoil" a draw | `engine/test_report.py` | Wording only; no effect on a match |

## Differences from the plan

- **The home side is found by nation, not only by name.** A side is at home when its name is the host's, or its
  spec's `nation` is (a Classic side), or most of its players are that country's (a saved side). Phase 3 matched
  the name only, so "India 2021-24" would not have been at home in India.
- **The series dispatch is in `play_series`** (one `if fmt == "test"`), the Test code in `engine/test_series.py`.
  The plan named `simulate_match` as the only dispatch; that rule covers `match.py`, `impact.py`, `rain.py` and
  `captain.py`, which are untouched. `play_tournament` refuses a Test.
- **1 to 6 Tests are accepted**; the page offers 1, 2, 3 and 5 as the plan says.
- **Classic sides before coverage are ranked by Tests spread evenly over a career.** A player with 60 Tests from
  1975 to 1990 counts as 3.75 a year, whatever he really played each year, because the career file has totals
  only. Squads of famous sides come out right (checked for West Indies 1980-85, Australia 1946-48 and 1999-2003),
  but a player who was dropped for some years can still be picked for them.
- **No "either era's conditions" switch of its own.** The Era box under More options already sets the year of the
  conditions; it follows the later side unless you change it.
- **The lead chart shows days as lines, not rain as gaps.** Its x-axis is overs bowled, so lost time has no
  width; a day's lost overs are in the day strip and the score header.
- **Records are the limited-overs ones plus wins by an innings and by wickets.** The full Test records
  (partnerships by wicket, carrying the bat, a hundred in each innings ...) are Phase 5.
- **Rain cannot be switched off for a Test** in the page: overs lost are part of the calibrated match.
- **An existing `data/teams.json` does not get the Test presets by itself** (it is your own list). Run
  `python scripts/build_test_presets.py` once to add them.
- Shared code touched: `engine/tournament.py` (the dispatch, the refusal), `engine/history.py` (Tests),
  `engine/render.py` (the report of a match played over days), the server and the page scripts. The golden test
  passes.

# Phase 5: Test records and the win / draw / loss table

Built 2026-11-15.

## What was built

| Part | Where | What it does |
|---|---|---|
| Win / draw / loss table | `engine/fit/fit_wdl.py` -> `data/engine/wdl_test.json`, read by `engine/test_wdl.py` | The chance that the batting side wins, and that the match is drawn, from the state: innings (1-4), wickets down, lead (or minus the runs needed in the last innings), overs left in the match |
| Chances on the scorecard | `engine/test_match.py` | Every over of a Test carries `"wdl": [the side that batted first wins, a draw]` and `"left"` (overs left in the match). The last over of the match carries the result |
| Impact | `engine/test_match.py` | Every ball moves the batting side's chance of winning plus half its chance of a draw; the move goes to the striker and against the bowler (`card["impact"]`, as in limited overs). Surviving a ball when batting for a draw earns credit, because the time left is part of the state |
| Player of the match | `engine/test_match.py` | The balanced points of Phase 3 plus impact turned into runs (`card["runs_per_win"]`), as the limited-overs award does |
| Turning point | `engine/test_wdl.py` | The session that moved the match most towards the side that won it: "day 3, before lunch (Australia from 186/4 to 256/9) swung the match 17% towards India". In the key moments, the report and the text scorecard |
| Series rankings | `engine/test_series.py` | Official: each match's award score added up (points + impact in runs); it picks the player of the series. Balanced: the points alone |
| Records | `engine/test_records.py` | Highest and lowest totals; top scores; hundreds with the count of doubles and triples; a hundred in each innings; carrying the bat; longest innings in balls; best innings and match figures; ten-wicket matches; hat-tricks; best partnership for each wicket; highest successful chases; biggest wins by an innings, runs and wickets; narrowest wins; fastest fifties and hundreds |
| Pages | `webui/testmatch.js`, `results.js`, `stats.js` | "Win, draw or loss": three bands over the match under the lead chart; the Test record cards; Best players with Impact, Points and Score |

## How the table is made

`python -m engine.fit.fit_wdl` (20,000 Tests, about four and a half minutes on nine processes of this laptop).

- **Who plays.** Every real Test XI of 2015-26 (946 of them) plays itself on its real ground, in its real year,
  with that country's weather. The sides are equal, so the table favours nobody; the grounds, eras and weather
  vary as they do in real Tests. There is no home edge in these matches.
- **What is counted.** The state at the start of each innings and after every over, with how the match ended
  for the side batting (a tie counts as a draw). 6.6 million states.
- **The grid.** Lead from -600 to 600 in steps of 30, overs left from 0 to 450 in steps of 18, each wicket and
  each innings on its own: 42,640 cells. A state is shared between its four nearest cells.
- **Smoothing.** A 1-2-1 average along the lead and the overs left and a light 1-6-1 along the wickets, applied
  once where a cell then has 150 states or more and up to four times where it has fewer. Cells that no Test came
  near (a lead of 500 in the second innings, say) copy the nearest filled cell.
- **Two rows are the laws, not the fit:** no time left is a draw; nothing left to get in the last innings is a
  win.
- **Reading it.** Straight-line interpolation between the cells for the lead and the overs left.

One Test in ten was kept out of the table to score it (605,183 states):

| | The table | Always saying the overall shares |
|---|---|---|
| Brier score (lower is better) | 0.447 | 0.659 |
| Log loss | 0.743 | 1.087 |

| When it said a win was | 7% | 31% | 46% | 70% | 89% |
|---|---|---|---|---|---|
| It happened | 6% | 30% | 47% | 73% | 90% |

| When it said a draw was | 7% | 29% | 49% | 69% | 91% |
|---|---|---|---|---|---|
| It happened | 6% | 27% | 50% | 72% | 94% |

One run, and the plan's test for it passes (the chances sum to 1 and move the right way: fewer runs to get, more
wickets in hand and a bigger lead are better; less time left means more draws for a side far behind), so it was
not tuned further.

**The table must be rebuilt whenever the Test engine is recalibrated.** It knows nothing of the two sides'
strength or of the home edge: a strong home side starts near 50%, as a limited-overs match does.

## Constants that are not fitted

| Constant | Value | Where | Why not fitted |
|---|---|---|---|
| The grid | lead steps of 30, overs-left steps of 18 | `engine/fit/fit_wdl.py` | The size of the table (288 KB); finer cells were emptier |
| States for a trusted cell | 150 | `engine/fit/fit_wdl.py` | A choice between noise and blur; the held-out score above is the check |
| Where a run's worth is read | third innings starting level, half the time left | `engine/fit/fit_wdl.py` | Turns impact into runs for the award (one whole win = 511 runs there); the slope differs elsewhere in a match |
| Tests held out | 1 in 10 | `engine/fit/fit_wdl.py` | Scoring only |

## Differences from the plan

- **"Average sides" are real XIs playing themselves**, not one invented average XI: equal sides, but with the
  spread of real line-ups, grounds and eras.
- **The turning point is a session, and it points to the winner.** In limited overs it is the over with the
  biggest swing. One over of a Test rarely moves the chances by more than a few points, and the biggest swing
  of a match can be towards the side that then lost, so a Test's turning point is the session that moved it most
  towards the winner (in a draw: most, either way).
- **The player of the series is picked by points plus impact**, the same score that picks the player of each
  match, added up. Limited overs uses impact alone; over a Test series that put a batter with one great innings
  above a bowler with 26 wickets.
- **Advice to a person** ("declaring now: win 44%, draw 51%") uses this table but belongs to Phase 6.
- **Hat-tricks are counted within an innings**, as the scorebook does for every format; one spread over two
  innings of a match is not found.
- Shared code touched: none. `engine/tournament.py`'s `records` is called, not changed. The golden test passes,
  and a Test plays the same with or without the table for the same seed (tested).

# Phase 6: captain a Test

Built 2026-11-15.

## What was built

| Part | Where | What it does |
|---|---|---|
| The desk | `engine/test_control.py` | Sits between the Test and a side's controller (`engine/control.py`). The match calls it wherever a captain decides; it asks the person when the call is theirs and otherwise returns the computer's call unchanged. It draws no random numbers |
| New decision kinds | `engine/control.py` | `declare`, `follow_on`, `new_ball`, `nightwatchman` |
| Hooks | `engine/test_match.py` | The toss and the XI; before an over (the batting side's bars, a declaration); the new ball; the bowler; the bars on each ball; the fall of a wicket; the end of an over (the computer's declaration call put to the person); the follow-on; the result |
| The bars | `engine/fit/fit_test_aggression.py`, `data/engine/aggression_test.json`, `TestSituation.with_bars` | A person's batting approach and bowling plan, 1-9, 5 = the engine as calibrated |
| Series and server | `engine/test_series.py`, `engine/tournament.py`, `server/runs.py` | `control` goes through to each Test; a Test run accepts `captain_i` |
| The screen | `webui/testcaptain.js`, hooks in `webui/captain.js` | The limited-overs captain screen with a Test score bar (day, session, overs left, three chances), the four new questions, Declare and Change bowler beside the bars |

## The decisions

- **Toss, XI**: as in limited overs. The XI question gives the squad, the computer's XI in batting order and its
  keeper.
- **Follow-on**: asked when the lead reaches the mark. Shows the computer's call (a draw from the fitted
  chance), that chance ("real captains enforce it about 62% of the time from here") and the person's chances
  either way from the win / draw / loss table.
- **Declare**: asked (a) whenever the computer's captain would declare at the end of an over, (b) at the start
  of a session once the fitted chance of a declaration is at least 0.5% an over, and (c) the bars question has
  a Declare button, so a person can declare before any over they stop at. A declaration by a person before an
  over costs no over; the computer's is still at the end of one. Shows the chances after declaring and as
  things stand.
- **New ball**: asked when it is available. "Not yet" is asked again ten overs later. The computer still takes
  it at once.
- **Bowler**: asked when an end has no bowler (the start of an innings or a day), when the computer would make
  a change, when the new ball is taken and at key moments. In between, the man at that end bowls on. The
  options carry what each bowler is expected to cost today (runs a wicket and an over, with the pitch wear and
  ball age for his type), his overs today and his rest.
- **Next batter / nightwatchman**: the batter question marks the nightwatchman the rule suggests. With the
  batter left to the computer, a yes / no nightwatchman question is asked when the rule applies.
- **Bars** (kind `ball`): before an over. Each batter and each bowler keeps his own bars.
- **Pace**: the answer to the bars question says how far to play: the next over, the next key moment, the next
  wicket, the end of the session, the day or the innings. While playing on to the end of a session, day or
  innings the computer makes the bowling changes, sends in the batters and takes the new ball; declaration and
  follow-on questions are still asked.
- **Key moments**: the first over of an innings and of a session, the over after a wicket, the new ball (due
  or just taken), the last 15 overs of the match, the last 30 runs of a chase.

## The bars: fitted, and one measurement

`fit_test_aggression.py` reads the fitted situation table. Each of its 68 cells with 2,000 balls or more (1.71
million balls) holds how much faster and how much riskier real sides batted there than the ratings predict.
The regression of each metric's log ratio on the log runs ratio across the cells, weighted by balls:

| Metric | Slope on log runs |
|---|---|
| wickets | 0.91 |
| dots | -0.41 |
| fours | 0.74 |
| sixes | 3.58 |

The 5th and 95th percentiles of the cells' log runs ratio are -0.090 and +0.183; one bar is a sixth of that
range, 4.55% of runs, so bar 1 scores 0.83 times and bar 9 1.20 times the usual rate.

In limited overs the cross-cell wicket slope (about 0.3) made hitting nearly free and was replaced by one
derived from the value of a wicket. In Tests it is 0.91. A slope of 1 is where tempo changes the time an
innings takes and not its runs per wicket, which is what an innings without an over limit should show, so the
measured slope is used as it is.

One run, 60 Tests at each setting, India v Australia (2023 sides), the person's side at the same bars all
match:

| India's bars | Runs an over | Runs a wicket | Balls a wicket | Won | Drawn |
|---|---|---|---|---|---|
| batting 1 | 2.98 | 29.2 | 59 | 23 | 14 |
| batting 3 | 3.31 | 30.7 | 56 | 19 | 16 |
| batting 5 (the computer) | 3.55 | 29.9 | 51 | 27 | 9 |
| batting 7 | 3.86 | 31.1 | 48 | 29 | 9 |
| batting 9 | 4.21 | 30.3 | 43 | 30 | 5 |
| bowling plan 1 | 3.10 conceded | 32.4 | 63 | 19 | 14 |
| bowling plan 3 | 3.19 | 30.4 | 57 | 20 | 13 |
| bowling plan 5 (the computer) | 3.38 | 29.5 | 52 | 27 | 9 |
| bowling plan 7 | 3.48 | 31.0 | 53 | 24 | 9 |
| bowling plan 9 | 3.64 | 31.1 | 51 | 29 | 6 |

Batting bars move the tempo and leave runs per wicket where it was. Batting fast all match drew fewer and won
slightly more; with 60 Tests a setting the difference in wins between bars 5 and 9 (27 and 30) is inside the
noise, and the engine is known to draw too often (Phase 3), which favours anyone who hurries. A containing plan
costs about three runs a wicket; an attacking plan costs about one and a half and gains nothing in balls per
wicket on average, so it pays only where a wicket is worth more than usual. Recorded, not tuned.

## Constants that are not fitted

| Constant | Value | Where | Why not fitted |
|---|---|---|---|
| Size of a bowling plan against a batting approach | 0.5 | `fit_test_aggression.py` | Cricsheet has no field, line or length; taken from the ODI fit |
| Attack and contain edges | 0.4, 0.8 | `fit_test_aggression.py` | The same; taken from the ODI fit, where they were set by simulation |
| A person's longest spell | all but 2% of real spells of that kind of bowler: 10 overs pace, 26 spin, 11 part-time; no more than that in any stretch three times as long, in a day | `engine/test_control.py` | The tail (2%) is a choice; the spell lengths are from the fitted spell table. Needed because tiredness does not show in the rates (Phase 2), so nothing else stops a person bowling two men all day |
| Declaration point at the start of a session | fitted chance of 0.5% an over or more | `engine/test_control.py` | When to ask, not how to play |
| Re-asking | declare 5 overs, new ball 10 overs | `engine/test_control.py` | The same |
| Key moments | last 15 overs of the match, last 30 runs of a chase | `engine/test_control.py` | Pace of the screen only |

## The captaincy report

`card["captaincy"]` lists the person's calls; `engine.judge.season_report` adds them up as it does for limited
overs. Declarations and the follow-on are valued by the win / draw / loss table: (win + half the draw chance
after the person's call) minus the same after the computer's, times the table's runs per win (511). A bowler is
valued by the expected cost of his over against the computer's choice: runs conceded less the era's runs per
wicket for each wicket expected, in today's conditions. The toss, the XI, the new ball and batting-order calls
are listed without a value.

Limits to read it with: the table knows nothing of the two sides' strength, so "declare: win 44%" is for two
average sides from that position; and a bowling choice is valued for one over, not for what it does to the
rest of the day.

## Checks

- A Test with no controller plays as before: 16 Tests (8 series of two) hashed before and after the change are
  identical. `tests/test_golden.py` passes (limited overs untouched: no Test logic entered `match.py`,
  `impact.py`, `rain.py` or `captain.py`).
- A controller that leaves every call to the computer, and one with every kind handed to the computer, play
  the computer's match ball for ball (4 seeds, either side).
- Random answers to every question (invalid ones included) keep every law of `check_card` over 12 Tests. One
  law is relaxed for a captained side: the new ball may be taken late, never early.
- `tests/test_test_control.py`: 12 tests. All 20 scripts pass.
- In the browser (port 5071): the setup page offers "You captain" for a Test with the Test decisions; a Classic
  Test was played through (toss, XI, bars, bowler, declare, result) and its captaincy report shown.

## Differences from the plan

- **The bars are per over, not per ball**, under the existing kind `ball`: a Test is about 2,700 balls.
- **`nightwatchman` is asked only when `batter` is left to the computer**; otherwise the batter question
  carries it.
- **No "last hour" rules**: the last 15 overs are a key moment for the screen; play is unchanged.
- **The follow-on's "computer's call" is a draw from the fitted chance**, as the computer's own is; the screen
  shows the chance as well.
- **One person only.** Two-player Tests stay deferred, as planned. Tests are not on the home page's Play
  button: that flow is built around a T20 / ODI pre-match card.
- **No weaker computer captains for Tests** (deferred in the plan): "Opponent captains" is hidden for a Test.
- Shared code touched: `engine/control.py` (four kinds added), `engine/tournament.py` (`play_series` passes
  `control` to a Test series), `tests/test_test_engine.py` (`check_card(captained=...)`).

## Not verified

- Phone width was not checked for the Test captain screen.
- The follow-on, new-ball and nightwatchman sheets were exercised by the tests through the engine and server,
  not clicked in the browser.

# After Phase 6: default teams, messages, the home screen, two players (2026-11-15)

## What was wrong

A person whose saved-teams file was made before the Test presets existed had no Test sides in it. Choosing
format Test left the two T20 squads in place, and the run stopped inside the engine with "no test player named
'a4cc73aa'" and a traceback.

## What was built

- **Default teams reach old files.** `server/core.py` `load_teams`: default teams missing from a person's file
  are added once. `teams_seen.json` beside the file lists the defaults already offered, so a default the person
  deleted is not added again. New ones go after the last nation's preset, before franchises and own teams.
- **A side must be able to play the format.** `wrong_format` (called by `check_entries`, so for a series, a
  tournament and a two-player room): a saved team with players who have no record in the format is refused
  before the run starts, naming up to three of them and the same nation's side for that format.
  `engine/data.py` `resolve` names the player, not his ID, when he is known in another format.
- **Errors in words.** A run that stops reports `error` (a sentence: the engine's own message for a
  `ValueError`, else a plain line) and `detail` (the traceback). The page shows the sentence and folds the
  traceback under Technical details.
- **Format chips.** The Format select moved out of More options to the top of the conditions, as three chips.
  Modes with no Tests (tournament, classic tournament, draft, auction) do not show the Test chip. The two team
  lists of Match / Series hold only the sides that can play the format (`teamsFor`), and a side that is not one
  of them is replaced by the same nation's.
- **Home screen.** The hero has T20 / ODI / Test. Play with Test starts a captained Test (your side at home):
  the toss, the bowling, the bars, declarations, the follow-on, the new ball and the nightwatchman are yours;
  the XI too if you press Change XI.
- **Two players.** A room may be a Test room: a team each (no draft, no auction), 1, 2, 3 or 5 Tests, all
  played, and a host setting (neutral, the host player's country, the guest's; default neutral). `Desk` already
  kept each side's calls apart; two changes make it fair for two people: both are asked for their XI at the
  same moment and both get the result pause at the same moment (`post`, then `wait`, as in limited overs). The
  bars are asked in turn: the batting side before the over, then the fielding side (its bowler and plan).

## Differences from limited-overs two-player games

- A Test series is not a best-of: every Test is played, and the room's line reads "3-Test series · Test 2".
- With a shot clock, the "time per ball" is the time for an over's bars.
- The two people do not set their bars at the same moment; one waits while the other chooses.

## Checks

- `tests/test_test_two_players.py` (6 tests): two random captains keep the laws; both asked at once for the XI
  and the result; a Test room through the server (draft refused, a T20 side refused in words, a 2-Test series
  played, the head to head); new default teams added once; the refusal message; the error format.
- All 21 test scripts and the golden test pass. Computer-only play is untouched (no engine change outside the
  two `Desk` methods).
- Browser, port 5071, desktop width: the home Play button with Test; Format chips and the team swap; the
  refusal message; the error screen; a Test room in two tabs up to the first bowling choice.

## Not verified

- Phone width for the new Format chips and the Test room.
- A two-player Test played to its end in the browser (the server test plays one to the end).

# Tests in more modes: tournaments, the World Test Championship, drafts, auctions, weaker captains (2026-11-16)

## What was missing

A Test could be a match, a series or a two-player game. A tournament, a draft and an auction refused the format,
there was no World Test Championship, computer captains in a Test were always the fitted one, and a two-player
Test series always played every Test.

## What was built

- **Test tournaments** (`engine/test_tournament.py`). `play_tournament(..., fmt="test")` builds a `TestRunner`
  there (the one dispatch, as `simulate_match` sends a Test to `engine/test_match.py`); `_Runner` gained three
  small methods (`table`, `stats`, `summary`) that the Test runner replaces. A league Test is at the first-named
  side's home (its country's grounds in rotation, its weather, the home edge). The table gives 12 points a win,
  6 a tie and 4 a draw and is ordered by the share of points won, then wins, then the runs-per-wicket ratio
  (stored as `nrr`, so the code that seeds knockouts is unchanged).
- **A drawn knockout** goes to the side ahead on first innings when both first innings were finished, else to
  the higher-placed side. The card keeps `type: "draw"` and gains `winner`, `loser` and `by`.
- **The World Test Championship** (`play_wtc`): the sides stand in a ring drawn from the seed; each is at home
  to the next three and away to the three before (fewer with under seven sides, so that nobody meets twice).
  Series of 1, 2, 3 or 5 Tests; the top two meet in a final at Lord's. The result has a tournament's shape plus
  `wtc` (the series). A 9-side, 2-Test cycle is 55 Tests.
- **Weaker Test captains** (`engine/test_captain.py` `Loose`). With the level's chance a bowling change is
  drawn from the fitted weights flattened; once an innings, with the same chance, the captain misreads a
  declaration or the follow-on by a draw from a normal distribution on the fitted model's scale. He draws from
  his own stream, so a Test with expert captains is the same as before (tested). `simulate_match(..., skill=)`,
  `play_test_series(..., skill=)`; the pages' Opponent captains setting now applies to Tests.
- **Test drafts and auctions** (`engine/test_value.py`). A Test player's batting value is his expected average
  above the era's, times the innings a player has in a Test; his bowling value is the balls he bowls a match
  times what he saves a ball. The draft's pool takes Tests from `engine/history.py`'s years. A player whose
  bowling comes from before ball-by-ball coverage has his overs per match from those Tests (it was divided by
  the wrong match count).
- **A two-player Test series can stop once it is decided** (`best_of` in `play_test_series`, a room setting).
  The default is still every Test.
- **Server and pages.** `/api/run` takes Tests for the modes series, tournament, draft, auction and wtc; a
  league season, a domestic cup and a career stay T20. A new World Test Championship mode; the Test table (D,
  PCT, RpW) and the Championship's series list on the results page.

## Measurements

**Weaker captains.** 1,500 Tests for each level between two identical sides (India 2025 v itself), the weaker
captain alternating sides. Share = wins plus half the draws.

| Run | Levels (chance of a loose call; slip) | Weaker side W / D / L | Weaker side's share |
|---|---|---|---|
| 1 | average 0.15; 1.5 | 571 / 353 / 576 | 49.8% |
| 1 | easy 0.60; 2.5 | 490 / 389 / 621 | 45.6% |
| 2 | average 0.35; 2.0 | 510 / 380 / 610 | 46.7% |
| 2 | easy 0.80; 3.0 | 439 / 366 / 695 | 41.5% |

Run 1 used the limited-overs levels and could not tell Average from Expert, so the levels were raised once and
measured again (run 2). They are not tuned further. This was a second run for one feature: a departure from
"one calibration run", recorded here.

**The auction's bowlers.** A specialist bowler's batting was first valued against the average player's, so a
great bowler who cannot bat was a late lot: of the 1990-2000 pool, McGrath was the 68th lot and 23 of the 120
lots were bowlers. Now a specialist bowler with useful bowling is valued against the average specialist
bowler's batting (0.59 of an average player's, read from the ratings, weighted by balls bowled). The same pool
has 46 bowlers; Muralitharan is the 4th lot, Ambrose the 11th and McGrath the 16th. One change, checked once.

## Constants that are not fitted

- `LEVELS` and `SLIP` (weaker captains): the data has no label for a poor captain. Set by the measurement above.
- `POINTS` 12 / 6 / 4 and three series at home and away: the World Test Championship's own rules.
- `INNINGS` 1.5 in `engine/test_value.py`: a side loses about 16 wickets a Test, so a player is out about one
  and a half times.
- The final at Lord's.

## Differences from the plan, and decisions the plan did not cover

- The plan listed the World Test Championship and weaker captains as later work; they are built here.
- A drawn knockout has a winner (first-innings lead, else the higher-placed side). The real Championship shares
  the title after a drawn final.
- Careers, league seasons and the domestic cup do not take Tests: they are real T20 competitions.
- A two-player draft or auction is still limited overs only.
- `engine/control.py`: a "sim to the end of the match" (or innings) is cleared when that match's result is
  acknowledged. It never applied to the next match; the room went on reporting it, so the page said "Skipping
  to the end" while the next Test's toss was being called. Limited-overs rooms get the same correction.

## Checks

- `tests/test_test_tournament.py` (7 tests): a Test tournament's table against its scorecards; a drawn final
  has a winner and says why; the Championship's schedule (nobody meets twice, three at home, three away), its
  series and final; a series that stops once decided; expert captains unchanged and a weaker captain
  reproduced by his seed; the draft and auction pools; the Championship and a Test tournament through the server.
- `tests/test_test_two_players.py` gained the skip test; `tests/test_test_series.py` no longer expects a
  tournament, a draft, an auction or a best-of to refuse Tests.
- All 22 test scripts and the golden test pass.
- Browser at phone width (375 px), two tabs as two players: a 2-Test room set to stop once decided, played to
  the series result (toss, both XIs, bars, the bowler and next-batter sheets by hand for about 110 overs, then
  Sim to end of match on both sides). No page errors. Found and fixed there: the "YOU" tag ran into the day
  line on the Test score bar; "Next match" now reads "Next Test"; a series that plays every Test no longer
  offers "See the series results" early; the captaincy table's headings made the results page scroll sideways.

## Not verified

- The follow-on, new-ball and nightwatchman sheets were not clicked in a two-player game.
- The weaker-captain measurement used one pair of sides.
- The Championship, the Test draft and the Test auction screens were checked in the browser by the session
  that built them, not again after the later fixes; the tests cover their server paths.
