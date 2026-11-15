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
