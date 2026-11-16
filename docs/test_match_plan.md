# Test match mode: plan (awaiting approval)

Written 2026-11-15. Nothing here is built. Read for this plan: `CLAUDE.md` (main checkout; it is git-ignored),
`README.md`, `engine/match.py`, `data.py`, `ballmodel.py`, `situation.py`, `conditions.py`, `tournament.py`, the
outlines of `captain.py`, `control.py`, `calibrate.py`, `engine/fit/*`, `scripts/build_raw_stats.py`,
`build_ratings.py`, `build_pre2002.py`, and in `../cricket/` (read only) `callcricketnew.py` (`det`, `aggfactor`,
`bowlchange`, `bowlvalue`, `day`, `declaration`, `followon`, `raincheck`, `pitchmake`), `eradata.txt`, `er_data.txt`,
`testmatchlist.txt`, the per-country files and `cricsheet_scrape.py`.

Numbers marked (approx.) are from memory or from the old sim's era files, not yet measured from Cricsheet. Phase 1
replaces each of them with a measured value before anything is tuned to it.

## 0. Summary of the decisions

| # | Decision | Why |
|---|---|---|
| 1 | Tests get their own controller, `engine/test_match.py`; the ball model, ratings loader, conditions and scorecard bookkeeping are shared | `match.py` assumes an over limit in ~16 places and `impact.py`, `rain.py`, `selection.py`, `captain.py` assume quotas; none of that applies |
| 2 | Limited-overs results are protected by a golden test (`tests/test_golden.py`) added before any other change | the only way to prove "identical for the same seed" in every later commit |
| 3 | Test ratings: the same fit as ODI/T20 (`build_ratings.py`, a third model), one overall index per player, no phase split | ball age and pitch wear act on bowling types, not on a player's skill profile; fewer parameters to shrink |
| 4 | Time is counted in overs: 5 days x 90, three sessions of 30, one fitted "overs lost per day" draw by host country | Cricsheet has no clock, day or session per ball; total overs per match is what can be fitted |
| 5 | Computer captains copy real captains (declarations, follow-on, spells), fitted from Cricsheet | the draw rate cannot be calibrated against real Tests if captains declare better than real ones |
| 6 | A three-way win / draw / loss table is built, by simulating the calibrated engine, but after calibration and as its own commit | it serves four things (chart, player of the match, turning point, advice to a person); it must be rebuilt whenever the engine changes, so it comes last |
| 7 | First competition: a 1-5 match series (current or classic sides), simulate only; captaining a Test yourself is the last phase | a Test is ~2,000 balls; the live screen needs Test "key moments" before it is playable |

## 1. Architecture

### What is shared, unchanged
- `engine/ballmodel.py` (`BallModel.delivery`, `legal_probs`): rate = baseline x batter x bowler x situation. It needs
  only a `basics_test.json` (dismissal mix, run split, byes, wides, run-outs). Tests have no free hit: the Test
  controller never passes `free_hit=True`.
- `engine/data.py`: `Player`, `player()`, `baseline()`, `ratings()`, `search()`, `resolve()`.
- `engine/conditions.py`: venue factor, pitch of the day, pace v spin edge.
- `engine/control.py` (questions to a person), `engine/periods.py`, `engine/history.py`, `engine/render.py`,
  `engine/tournament.py` (`_Runner`, `play_series`, stats).

### What is new
| File | Holds |
|---|---|
| `engine/scorebook.py` | the format-neutral half of today's `Innings`: batting cards, bowling figures, `apply`, the scorecard part of `wicket`, partnerships, events, milestones, `to_dict`. `match.Innings` and `TestInnings` both build on it |
| `engine/test_match.py` | `TestMatch`, `TestInnings`, the match clock (days, sessions, overs lost), new ball, innings order, follow-on, declarations, results; `simulate_test(...)` |
| `engine/test_captain.py` | bowling by spells from two ends, fatigue, new-ball choice, declaration and follow-on calls, nightwatchman, batting-order changes |
| `engine/test_situation.py` | Test situation tables (settling in, innings x lead x wickets, last-innings chase / save), ball age, pitch wear |
| `engine/fit/fit_test_*.py` | Test-only fits (situation, spells, declarations and follow-on, overs lost, win/draw/loss). Fits whose method is the same (`fit_basics`, `fit_toss`, `fit_venues`, `fit_spin`) get a `"test"` entry in their config instead of a copy |

### How the format is wired
- `FORMATS["test"] = {"overs": None, "quota": None, "phases": ("all",), "intl": "test_full", "days": 5, "day_overs": 90}`.
- `data.py` today uses the module constant `PHASES` in `player()`, `_prior()`, `baseline()` and
  `_typical_shares()`. These become "the phases of this format" (three names for T20/ODI, `("all",)` for Tests).
  That is the only edit to shared code beyond the scorebook move.
- One dispatch point: `simulate_match(fmt="test", ...)` calls `TestMatch`; `Match(fmt="test")` raises. So
  `tournament._Runner`, the server and the tests reach Tests through the function they already call. No other
  `fmt == "test"` check goes into `match.py`, `impact.py`, `rain.py` or `captain.py`.
- The card keeps the limited-overs shape wherever it means the same (`format`, `teams`, `xi`, `toss`,
  `conditions`, `innings[]`, `result`, `events`, `player_of_match`, `seed`), so the scorecard renderer, stats tables
  and match centre need extensions, not rewrites. Additions: up to four innings, each with `declared`,
  `follow_on`, `lead`, `day`/`session` on every over and event; `days[]` (overs, runs, wickets, close-of-play
  score, overs lost and why); no `super_overs`, `impact_player` or DLS fields.

### Regression check for limited overs (named: `tests/test_golden.py`)
- `tests/golden/limited_overs.json`: for about 60 fixed matches, a digest of the facts of each card (every
  innings' runs, wickets, balls; each batter's runs and balls; each bowler's figures; result text; toss; XI).
  The matrix: T20I, ODI, IPL 2024 with the Impact Player, rain on, squads of 15 (XI selection), classic sides
  with `years`, Average and Easy computer captains, one 3-match series and one 4-team tournament.
- Generated once from `main` at 23bb9bd, before any other change, and committed alone with the test.
- Whole numbers only, not the rounded floats: the file is made on Windows and checked on Linux in CI, where
  `math.exp` can differ in the last bit.
- Runs in `tests/run_all.py` (a few seconds). Every later phase must pass it without touching the file. A commit
  that changes limited-overs behaviour on purpose regenerates the file and says so in its message.
- The scorebook move is the one risky edit: it must keep the order of random draws. The golden test is its proof.

## 2. Data and ratings

### Ball-by-ball source
- Cricsheet `tests_male_json.zip`, added to `scripts/fetch_cricsheet.py`. Coverage is believed to start around
  2001-02 with roughly 850-900 men's Tests (approx.); Phase 1 measures it from `info.match_type_number` gaps and
  Cricsheet's missing list, as `coverage_odi.json` does. Afghanistan's Tests are withheld like its other matches.
- Each innings records `declared` and `forfeited`; the follow-on shows in the batting order of the innings; the
  match has its list of `dates`. There is no day, session or time on a delivery, and no record of when the new
  ball was taken. Every time-related fit below works around that.
- `scripts/build_raw_stats.py` gains format `test`: the existing per-player records, plus splits needed by the
  fits: innings number (1-4), ball age bucket, against pace / spin, batting position, home / away, by year.

### Ratings
- `scripts/build_ratings.py` gets `MODELS["test"]`: the same three-way alternating fit (baseline factor, batter
  index, bowler index) for runs, wickets, dots, fours, sixes, with empirical-Bayes shrinkage toward role-group
  mean x team level. Output `data/ratings_test.json`, `ratings_test_years.json`, `.csv`.
- One overall index per player (phase `"all"`). Reason: in limited overs the phase split captures skills (death
  bowling, powerplay hitting). In Tests the corresponding effects are ball age and pitch wear, and they act on
  pace or spin as a group; they are fitted as tables in section 3. An opener's "new-ball skill" is already in his
  overall index because that is the bowling he faces.
- A home / away factor is fitted with the baseline, so a home-heavy record does not inflate a rating. Whether
  the engine also applies it in matches is question Q3.
- Prior for short careers: role x team as now. Two extra priors are tried and kept only if
  `scripts/validate_ratings.py` (fit to 2021, predict 2022-26) improves: the player's first-class record from his
  Wikipedia infobox (the FC column is usually present, unlike List A), and his ODI index.
- Checks: `validate_ratings.py` for Tests; `verify_players.py` against Wikipedia for Kohli, Root, Smith,
  Williamson, Ashwin, Anderson, Lyon, Rabada.

### Players before ball-by-ball coverage
- Career totals from Wikipedia's "List of <nation> Test cricketers" pages, with the tolerant table parser,
  cached fetches and ID voting already in `scripts/build_pre2002.py` and `wikiutil.py` (new
  `scripts/build_pre_tests.py`). Fields: span, matches, innings, not outs, runs, average, balls bowled, runs
  conceded, wickets, catches, stumpings. Bowling economy and strike rate follow from these.
- Batting strike rate is not in those tables. It comes from the role and era prior (the old sim does the same).
- Players who span the cut (Tendulkar, Lara, Warne) get a pre-coverage part = Wikipedia total minus Cricsheet
  part, as ODI `pre2002` does, so a 1990s year range uses only that part.
- Rated with the existing `totals_rating()`: index = career rate / era rate over his years, shrunk by sample
  size, opposition taken as average. `source: "wikipedia_totals"` on the record.
- The old sim's `<nation>players.txt` files hold the same totals plus balls faced, scraped from ESPNcricinfo
  before it blocked scraping. See Q1: recommended use is a local cross-check of match counts and runs (the
  project's lesson: compare two sources, keep the more complete), not a committed input.

### Era adjustment
- Indexes are relative to the player's contemporaries, as now. Covered years: the fitted per-year baseline.
- Earlier years need runs per wicket and runs per over by year, 1877-2000. `../cricket/eradata.txt` (20.5 in
  1877, about 29.5 in 2022-26) and `er_data.txt` (2.28 in 1877, about 3.27 in 2024-26) are exactly that. Dot,
  four and six rates for those years are scaled from the earliest covered years by the run rate, as
  `pre2002_baselines()` does for ODIs (an assumption, labelled in the file).
- Playing in an era's conditions = passing that `year`, as now. v1 keeps 5 days x 90 six-ball overs in every
  era; 8-ball overs, timeless Tests, 6-day Tests and uncovered pitches are deferred.

### Which situation and aggression models get Test versions
| Limited-overs table | Tests |
|---|---|
| `basics` (dismissal mix, run split, byes, wides, run-outs) | refit, same script. `free_hit` not used |
| settling in (balls faced) | refit with longer edges (to 200+ balls); test whether dismissal risk also falls as a batter settles, which it does not in limited overs |
| `state1` / `state2` (balls left x wickets x pressure), par, resources | replaced: innings (1-4) x wickets down x lead or deficit x stage of the match; for the last innings, runs needed per over left x wickets in hand (chase, steady, save) |
| chase win model, DLS, batting depth, Impact Player | not used |
| hand x bowling kind matchups | refit, same code |
| venue factor, pitch of the day, pace v spin edge | refit with the Test controller (`fit_venues`, `fit_spin`) |
| reactive bowling changes | replaced by the spell model (section 4) |
| toss | refit |
| aggression bars (runs v risk curve) | refit on the Test cells; needed for a person's bars and for the engine's own "push for a declaration" and "shut up shop" |
| (new) ball age x pace / spin | fitted: observed / expected by overs since the innings began, modulo 80 |
| (new) pitch wear x pace / spin | fitted: observed / expected by overs bowled in the match so far |

The exact cells are fixed after data probes in Phase 1 (how many balls each cell has), and recorded, as step 2b
did for the limited-overs engine.

## 3. Time and conditions

- **Clock.** The match has `days x 90` overs. A day is three sessions of 30 overs; lunch, tea and stumps are
  events with the score and both batters. A change of innings inside a session costs 2 overs. The match ends as
  a draw when the last day's overs are used up. `days` is a parameter (4-day Tests work; default 5).
- **Over rate, bad light and rain** are one quantity: overs actually bowled against overs scheduled, by host
  country. It is fitted from matches that reached the last day (overs bowled v `len(dates) x 90`), and applied as
  events: a short delay, a lost session, a washed-out day, or an early close for light. Each is logged ("Day 3:
  rain, 34 overs lost"). This is biased toward long matches and is labelled as an estimate; its check is the
  total overs in drawn Tests and the draw rate by host. The old sim drew a match-level `gameovers` (3% of Tests
  lose a lot, 15% lose up to a fifth); this replaces those hand-set odds with fitted ones.
- Not modelled in v1: making up lost time the next day, the extra half hour, the last-hour 15 overs, over-rate
  fines. Their average effect is inside the fitted quantity.
- **New ball.** Available after 80 overs of an innings. The computer takes it at once unless spin is well ahead
  on the day (spin edge and wear high, two spinners on); then it waits. The ball-age table restarts. Cricsheet
  does not record when it was taken, so the fit assumes over 80.
- **Pitch wear.** A fitted table by overs bowled in the match, separately for pace and spin (old sim: hand-set
  `det()`, spin 1.3 on day 1 to 0.7 on day 5, pace 1.2 to 0.8). The day's pitch draw and the venue's spin edge
  stay as they are and multiply it.
- **Pitch of the day.** As for internationals now: within-venue variance beyond the engine's own, fitted by
  replay. Test pitches vary a lot (a road in Rawalpindi, a three-day turner), so this is expected to matter more
  for the spread of totals and the share of early finishes than it does in limited overs.

## 4. Captaincy

Computer captains follow real captains, each call fitted from Cricsheet and checked in calibration.

- **Declarations.** A fitted chance of declaring at the end of each over from: innings number, lead, wickets
  down, overs bowled in the match (the stand-in for time left, since Cricsheet has no clock; in the simulation
  it is `scheduled - overs remaining`, so rain counts as time gone), and current run rate. A batter in the 90s
  delays it (old sim, kept). Before a third-innings declaration the batting side accelerates: the situation table
  holds what real sides do with a big lead. Checks: share of innings declared, lead at third-innings
  declarations, overs left to the opposition.
- **Follow-on.** Offered at a lead of 200 (150 in a 3-4 day match). Chance of enforcing fitted from real cases
  on lead, overs the bowlers have just bowled and time gone. (Old sim: enforce only when time is short.)
- **Last innings.** Each over the batting captain is in one of three modes from runs needed, overs left and
  wickets in hand: chase, steady, or save the match. The modes are positions on the fitted runs v risk curve.
  Draws saved eight or nine down have to come out of this.
- **Nightwatchman.** A wicket falls with 6 overs or fewer left in the day and the next batter is a specialist
  (top 6): a lower-order batter goes in instead (the best defender of Nos. 8-10). Hand-set and labelled; no day
  data to fit it. Can be switched off.
- **Bowling: spells and fatigue, no quotas.**
  - Two ends. At each end, after each over, the bowler continues or is replaced. The chance of continuing is
    fitted from real spells (visible in Cricsheet as the same bowler bowling alternate overs) on bowling type,
    overs in the spell, overs bowled that innings, and figures against expectation (the Test form of
    `fit_reactive`).
  - The replacement is chosen by value in the conditions (ball age, wear, spin edge, batter's hand), rest since
    his last spell, and his real share of his side's overs. Part-timers appear in long partnerships at their
    real rate. The new ball brings the opening pair back.
  - Whether tiredness lowers a bowler's rates (not only his availability) is a data probe: observed / expected
    by over of spell and overs bowled in the innings, pace and spin. It goes in only if the data shows it.
- **Fields.** Cricsheet has no field or line and length data. Attack and defence are the bowling-plan bars that
  already exist (attack: more wickets and more runs; contain: fewer of both). The computer's use of them is
  implicit in the fitted situation tables; explicit bars are for a person (Phase 6). The highlights screen can
  draw slips and a ring from the bar.
- **Batting order.** By Test position history. Promotions only for the nightwatchman and, in a declaration
  push, a hitter ahead of a blocker.
- **XI from a squad.** v1: a rule (six batters including the keeper, at least four bowlers, a spinner unless the
  ground favours pace) on the engine's Test values. The learned selection model (`fit_selection`) is deferred.

## 5. Results and stats

- **Result.** `{"type": "win" | "draw" | "tie", "winner", "by": "innings" | "runs" | "wickets", "margin", "text"}`:
  "won by an innings and 32 runs", "won by 145 runs", "won by 4 wickets", "Match drawn", "Match tied" (the side
  batting last all out with the scores level). Innings order with a follow-on is A, B, B, A. An abandoned match
  with no play is a draw.
- **Series result.** "India won the series 2-1" with draws counted (2-1 in a five-Test series leaves two
  draws). All matches are played; `best_of` does not apply to Tests.
- **Stats tables.** Batting: M, I, NO, runs, HS, average, SR, 100s, 50s. Bowling: overs, maidens, runs, wickets,
  average, economy, SR, best innings, best match, 5-fors, 10-fors.
- **Records.** Highest and lowest totals; top scores with lists of hundreds, doubles and triples; best innings
  and match figures, ten-wicket matches; hat-tricks; biggest wins (innings, runs); narrowest wins; highest
  successful chases; best partnership for each wicket; longest innings in balls; carrying the bat; a hundred in
  each innings; fastest 50 and 100 by balls.
- **Player of the match.**
  - Until the win / draw / loss table exists: the balanced score, with a wicket worth the match's runs per
    wicket (about 30), 5 per catch or stumping, a bonus for the winning side, and runs weighted by how
    low-scoring the match was. No strike-rate credit.
  - With the table: balanced score + (win probability + half the draw probability) added, converted to runs,
    as the limited-overs award does now.
- **Is the win / draw / loss model worth it? Yes, as its own commit after calibration.** Method: simulate about
  20,000 Tests between average sides in varied conditions, record the state at the end of every over (innings,
  lead, wickets, overs remaining) with the final result, and smooth into a table (`fit_wdl.py` ->
  `data/engine/wdl_test.json`). Uses: a three-band chart in the match centre, player-of-the-match impact, the
  turning point, and advice to a person ("declaring now: win 44%, draw 51%"). Cost: about half an hour of
  simulation, and it must be rebuilt whenever the engine is recalibrated, which is why it comes after Phase 3.

## 6. Competitions and UI

- **First:** Match / Series with 1, 2, 3 or 5 Tests, and Classic Series (nation + years, e.g. West Indies
  1980-85 v Australia 1999-2003, in either era's conditions). A series has a host: its grounds in rotation, its
  weather, and (Q3) home advantage. `data/home_grounds.json` gets each nation's Test grounds.
- Team Builder: "Test" in the ratings selector; preset Test squads in `data/teams_default.json`.
- **Server:** the `("t20", "odi")` tuples in `server/runs.py` and friends come from one list. Modes that cannot
  be Tests (league season, auction, draft, tournament, two players, careers) refuse the format with a clear
  message.
- **Screens.**
  - Format choice T20 / ODI / Test where it exists now; for Tests the match-count chips are 1 / 2 / 3 / 5.
  - Match centre: result headline; a day-by-day strip ("Day 2, tea: Australia 212/4, trail by 135"); scorecard
    with a tab per innings (up to four), declared and follow-on marked; fall of wickets; partnerships.
  - Charts: lead over the match (one line, innings shaded, day lines, rain gaps) in place of the run worm;
    Manhattan per innings; the win / draw / loss bands once Phase 5 lands.
  - Report by days, in the old sim's spirit ("forced to follow on", "spoiled by rain").
  - Text scorecard (`render.py`) for four innings with close-of-play lines.
  - Simple / Full stats, team colours and phone layout as everywhere else.
- **Later:** World Test Championship (points percentage table, two-year cycle, final), an international career
  world, two-player Tests.

## 7. Calibration targets and how they are checked

`python -m engine.calibrate --suite test`: replay every full-member Test 2015-26 (real XIs, batting order, toss,
venue, host, year) K times, compare with what happened, write `data/engine/calibration_test.json`, and log each
run in `docs/engine_progress.md`. Working rule as before: one feature, one run, stop tuning when the gate is met.

| Target | Real, modern (approx. until measured) | Gate |
|---|---|---|
| Runs per wicket | about 29-30 in 2018-26; about 34 in the 2000s | within 2% |
| Run rate | about 3.2-3.3 an over | within 2% |
| First-innings total, mean and spread | measure | mean 2%, SD 10% |
| Draw rate | about 12-15% in the 2020s, 20-25% in the 2000s-2010s | within 3 points |
| Innings victories | about one Test in six | within 3 points |
| Wins by runs v by wickets, home win share | measure | within 3 points each |
| Match length (finished in 3 / 4 / 5 days), total overs | measure | distribution within 5 points per bin |
| All-out share, innings length in overs | measure | within 5% |
| Fourth-innings chases won, by target band | measure | reported; gate on the under-200 and 200-300 bands |
| Declarations per match, lead at third-innings declarations, follow-ons enforced | measure | within 10% |
| Hundreds, double hundreds, five-fors, ten-fors per match; top-score distribution | measure | hundreds and five-fors within 10% |
| Share of overs and wickets by pace / spin, by host | measure | within 3 points |
| Spell lengths by bowling type; overs by the most-used bowler | measure | means within 10% |
| Dismissal mix | measure | within 2 points per kind |

**By era.** There are no real XIs to replay before coverage. An era suite plays each decade's classic sides
against each other in that decade's baseline and checks runs per wicket and run rate against the era table
(within 3%). The draw rate by era (about 45% in the 1980s, about 35% in the 1990s, approx.) is reported, not
gated, in v1: slower scoring produces more draws on its own, but real over rates and day lengths also differed
and v1 does not model them.

**Speed.** A Test is about 2,000 balls; at the ODI's cost per ball that is roughly 80-100 ms, so 500 Tests x 4
replays is a few minutes on several processes. Timed the usual way (old v new interleaved, one core).

## 8. Build order: one commit per phase, each with tests

| Phase | Commit | Contents | Tests |
|---|---|---|---|
| 0 | `test: golden regression for limited overs; move scorecard bookkeeping to scorebook.py` | golden file from `main`; `engine/scorebook.py`; `data.py` phases per format. No behaviour change | `tests/test_golden.py` passes before and after the move; all 13 existing scripts |
| 1 | `feat: Test match data and player ratings` | fetch, raw stats, Wikipedia pre-coverage totals, era baselines, `ratings_test.json`, `basics_test.json`, `FORMATS["test"]`, data probes written into `docs/test_design.md` | `tests/test_test_data.py` (covered, pre-coverage and unknown players load; ratings sane for a list of known players); validation and verification numbers in the commit body |
| 2 | `feat: Test match engine (days, two innings a side, declarations, follow-on)` | `test_match.py`, `test_captain.py`, `test_situation.py`, the Test fits, four-innings text scorecard, `simulate_match(fmt="test")` | `tests/test_test_engine.py`: laws and bookkeeping over 300 Tests (innings order, follow-on only at 200+, no bowler bowls consecutive overs, never more than the scheduled overs, result agrees with the scores, sums add up), forced scenarios for each result type, seed reproducibility |
| 3 | `feat: calibrate Tests against real matches` | calibrate suite, venue / pitch / spin / overs-lost fits, home factor, tuning to the gates, README table | calibration JSON; a fast test that 200 fixed Tests stay inside wide bands |
| 4 | `feat: Test series and results pages` | `play_series` for Tests, Test stats and series result, server format list, format choice, four-innings scorecard, day strip, lead chart, Classic Test series, Team Builder, presets, README | `tests/test_test_series.py`; server test for a Test run; pages checked in the browser on port 5071 |
| 5 | `feat: Test records and win/draw/loss model` | records, `fit_wdl`, three-band chart, player of the match with impact, turning point | records totals test; WDL probabilities sum to 1 and move the right way |
| 6 | `feat: captain a Test (declare, follow-on, new ball, nightwatchman, bars)` | control kinds `declare`, `follow_on`, `new_ball`, `nightwatchman`; Test key moments (first over of a session, after a wicket, new ball, last hour, each declaration point); captaincy report | `tests/test_test_control.py` |

Phases 0-3 have no UI. Each phase ends with the golden test passing and `docs/engine_progress.md` updated.

### Deferred
(Since built, see docs/test_design.md: the Championship, Test careers, two-player Tests, learned XI selection,
weaker captains, era playing hours, timeless and three- to six-day Tests, day-night Tests, the last hour,
injuries and replacements. Still open: 8-ball overs, uncovered pitches, making up lost time, fielding quality,
women's Tests, domestic first-class cricket.)
World Test Championship and careers; two-player Tests; learned XI selection for Tests; weaker computer captains
for Test-only calls; era-specific playing hours, 8-ball overs, timeless and 6-day Tests, uncovered pitches;
day-night Tests; making up lost time, last-hour rules; injuries and substitutes; fielding quality; women's
Tests; domestic first-class cricket.

## 9. `CLAUDE.md` update (on approval)

`CLAUDE.md` is git-ignored and lives only in the main checkout, so this is a local edit, not part of a commit.

- Title and Goal: "ODI, T20 and Test cricket"; Tests added on the same ratings and ball model with their own
  match controller.
- Hard rules, new line: "Limited-overs results must stay identical for the same seed: `tests/test_golden.py`.
  Regenerate its file only in a commit that changes limited-overs behaviour on purpose, and say so."
- Hard rules, new line: "Test logic lives in `engine/test_*.py`. No `fmt == "test"` checks in `match.py`,
  `impact.py`, `rain.py` or `captain.py`; the only dispatch is in `simulate_match`."
- Reuse table, ball model row: replace "don't port the Test-specific parts (days, declarations, follow-on)" with
  "Test mode: read `callcricketnew.py` (`det`, `aggfactor`, `bowlchange`, `declaration`, `followon`,
  `raincheck`) for ideas; rewrite and fit from Cricsheet, don't port constants."
- Data sources: add `tests_male_json.zip`; note that it has `declared` per innings and match `dates` but no day,
  session, clock or new-ball record.
- "Test sim features not in this project": drop "Test-only items ... are left out on purpose" and point to this
  plan.
- Status: a 2026-11-15 entry (plan written, awaiting approval), then one per phase.
- README (in the Phase 4 commit): title, intro, Roadmap, layout, rebuild steps. The repository name stays.

## 10. Questions for you

1. **Data from `../cricket/`.** Recommended: use `eradata.txt` and `er_data.txt` (yearly runs per wicket and run
   rate, 1877-2026) as the pre-coverage era table, credited to Jamie in the README; take player totals from
   Wikipedia; use the old per-country player files only as a local cross-check. Alternative: nothing from that
   folder, and the era table is rebuilt from Wikipedia player totals (rougher).
2. **Computer declarations.** Recommended: copy real captains, so the draw rate can be calibrated; the win /
   draw / loss table later gives a person the "best" call next to the computer's. Alternative: computer captains
   declare optimally from the start (fewer draws than real cricket).
3. **Home advantage.** Recommended: fit it and apply it when a series has a host. This differs from limited
   overs here, where a ground brings its conditions and nothing else; in Tests the home edge is large and the
   home win share is a calibration target. Alternative: conditions only.
4. **Where Tests appear first.** Recommended: Match / Series and Classic Series, simulate only, until Phase 6.
   Alternative: bring Phase 6 forward (before records) if captaining matters more to you than records.
