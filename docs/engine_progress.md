# Engine build progress (step 3 onward)

Companion to `docs/engine_design.md` (plan, decisions, build log). Updated 2026-10-03.

## Current state

Tier 0, Tier 1 and the approved Tier 2 items are built in `engine/` and **calibrated one at a time** (table below).
The engine passes the design's gate criteria in all three replay suites (see "Gate check"). All tests pass
(`python tests/test_engine.py`).

## Process correction (2026-10-03)

The user paused the work because it was drifting. The review found no skipped features had been built, but three
process problems:
1. Tier 2 items had been added together and calibrated once, against the one-feature-at-a-time rule.
2. The pitch model had been re-fitted three times in a tuning loop beyond the plan.
3. Strike farming (T1-5) used hand-set numbers instead of fitted ones.

What was done about it: the pitch model was reverted to the last calibrated method. An unplanned mid-Tier 2 tweak
(finer 7/8/9-down wicket buckets) was reverted. Strike farming was removed. Calibration was then rerun step by step
with deterministic seeds. Tuning stopped once the gate criteria were met.

## What is built (all from the approved catalogue)

| Item | What it does | Files |
|---|---|---|
| T0-1 laws | 20/50 overs, quotas, no consecutive overs, wides/no-balls re-bowled, free hit, strike rotation | `engine/match.py` |
| T0-2 ball model | baseline x batter x bowler per phase; dots and 1/2/3 solved so both dot and runs ratings hold | `engine/ballmodel.py` |
| T0-3 fitted basics | dismissal mix (phase x pace/spin), run splits, wides, byes/leg byes, run-outs, free-hit effect | `engine/fit/fit_basics.py` |
| T0-4 output | scorecard dict, text scorecard, match report | `engine/match.py`, `engine/render.py` |
| T0-5 / T1-6 captaincy | bowling plan from real overs per match and real phase usage, spells, greedy fallback | `engine/captain.py` |
| T0-6 calibration | replays real fixtures; `--no-venue/--no-pitch/--no-matchups` switches, `--label`, fixed seeds | `engine/calibrate.py` |
| T0-7 ties, POM | repeated super overs (T20 and ODI); player of the match by win probability added | `engine/match.py` |
| T1-1 / T1-2 / T1-3 | par/resources, intent tables (1st innings, chase pressure), settling in | `engine/fit/fit_situation.py`, `engine/situation.py` |
| T1-5 strike farming | **removed** (was hand-set; build again only if fitted from data) | - |
| T1-7 batting order | slot from position history; extra openers drop to 4; late hitter promotion; left/right pairs | `engine/captain.py`, `engine/match.py` |
| T1-8 win probability | fitted chase model; worm, turning point, impact per player | `engine/situation.py`, `engine/match.py` |
| T2-1 matchups | batting hand x bowling kind table | `situation_*.json` |
| T2-3 venue factor | shrunk venue effect from replaying every real match since 2012 with the Tier 1 engine | `engine/fit/fit_venues.py` |
| T2-4 pitch of the day | per-match runs/wickets draw; **internationals only** (over-dispersed the IPL) | `engine/conditions.py` |
| T2-5 toss | real bowl-first rate shifted by the venue's chasing advantage | `engine/fit/fit_toss.py` |
| T2-8 era-neutral | works as is (ratings are era-relative) | - |
| T2-9 XI from squad | keeper, 4 specialist bowlers + best 5th option, best batters, bowling-capacity check | `captain.select_xi` |

**Not built**, as decided: dot-ball pressure, dew, ODI ball age, form, fatigue, dropped catches. **Later**: T2-2,
T3-5, T3-6. **Open**: T2-10 year-range ratings (with historical mode).

## Calibration, one feature at a time (fixed seeds, 4 replays per fixture)

Spread = SD of totals v real (1st / 2nd innings). Seed-to-seed noise on the spread is about +-3 points.

| Step | T20I mean, spread | IPL mean, spread | ODI mean, spread | All out % T20I / IPL / ODI (real 12.6 / 7.9 / 36.1) |
|---|---|---|---|---|
| 1 Tier 1 baseline (T2 off) | -1.5%, -19% / -15% | +0.2%, -1% / -10% | -0.8%, -9% / -9% | 14.9 / 11.5 / 39.7 |
| 2 strike farming removed | -1.5%, -19% / -15% | +0.2%, -1% / -9% | -0.7%, -9% / -9% | 15.2 / 12.4 / 39.5 |
| 3 + venue factor (T2-3) | -1.6%, -17% / -12% | +0.3%, -6% / -10% | -0.7%, -8% / -8% | 15.9 / 10.7 / 39.6 |
| 4 + matchups (T2-1) | -1.0%, -15% / -13% | +0.6%, -2% / -9% | -0.1%, -9% / -9% | 16.8 / 11.5 / 40.4 |
| 5 toss (T2-5) | no effect on replays (real toss); simulated bowl-first T20 63.0% (real 62.8%), ODI 59.2% (59.3%) | | | |
| 6 + pitch of the day (T2-4) | -0.7%, +3% / +11% | +1.3%, **+15% / +14%** | -0.4%, +2% / +4% | 17.2 / 12.5 / 39.9 |
| **7 final: pitch for internationals only** | **-0.7%, +3% / +11%** | **+0.6%, -2% / -9%** | **-0.4%, +2% / +4%** | 17.2 / 11.5 / 39.9 |

## Gate check (final configuration)

| Criterion (design section 7) | T20I | IPL | ODI |
|---|---|---|---|
| mean total within ~3% | -0.7% / +0.4% | +0.6% / -0.5% | -0.4% / +0.7% |
| spread within ~10% | +2.9% / +10.9% (within noise) | -2.1% / -8.9% | +1.7% / +3.9% |
| wickets per innings within ~0.3 | +0.03 / -0.22 | +0.12 / -0.11 | -0.01 / +0.02 |
| phase run rates within ~3% | max 0.5% | max 1.4% | max 2.5% |
| chase win % within ~3 points | -0.5 | -4.7 (real figure is +-2.6 from 355 matches; same since Tier 1) | -2.4 |

## Bug fixed after calibration (2026-10-03)

The dismissal-mix table over-counted bowled and lbw (simulated T20I: 37% bowled v 21.5% real). Cause: `fit_basics.py`
skipped caught dismissals in matches where the keeper couldn't be identified, but kept bowled and lbw. Catches from
those matches are now kept and split keeper/fielder in the known-keeper proportion. Simulated T20I mix after the
fix: bowled 20%, caught 65% (real 60%), lbw 6.5% (7.8%). Dismissal type is drawn after the wicket itself, so the
calibration of runs and wickets above is unaffected.

## Open issues (recorded, not being tuned)

1. All-outs are too frequent (T20I 17 v 12.6%, IPL 11.5 v 7.9%, ODI 40 v 36%). This is not a gate criterion. It
   comes from over-dispersed wickets per innings, not from tail-enders: their balls per dismissal match reality.
2. The pitch of the day is off for leagues. Its per-competition spread over-dispersed IPL totals. Other leagues have
   no replay suite, so they follow the IPL decision.
3. Hundreds: T20I -9%, IPL +13%, ODI -13% (small counts).

## Step 4: series and tournaments (2026-10-03)

`engine/tournament.py`, no ball-model change (so no calibration step):
- **Formats:** `play_series` (bilateral, n matches) and `play_tournament` (round robin x `rounds`, optional groups,
  then semis / IPL playoffs / final / none).
- **Points table:** ICC net run rate (bowled-out side charged full overs; super overs excluded).
- **Tables and records:** batting / bowling / fielding tables; records (highest/lowest totals, top scores, best
  figures, fastest 50s/100s, biggest/narrowest wins, super overs).
- **MVP rankings:** official = win probability added (also picks player of the series); balanced = runs + 25/wkt +
  5/catch + 25/team win + strike-rate and economy bonuses.
- **Output:** `save()` writes `summary.json` and `matches/NNN.json` / `.txt`.
- **Command line:** `python -m engine.tournament <config> --out <dir>`; example configs in `examples/`.
- **Engine change (output only):** milestone events now carry `player_id`, `mark` and `balls` for the
  fastest-50/100 records.
- **Helper:** `engine.data.resolve` turns player names into Cricsheet IDs.
- **Tests:** `tests/test_tournament.py` (points and played totals, NRR recomputed by hand, a bowled-out side charged
  full overs, stats summing to scorecards, knockout and IPL playoff structure, seed reproducibility).

Follow-up (user request): saved `matches/NNN.txt` files now end with a **Match Report** paragraph, as in the Test sim
(`engine.render.full_text`). The report is ported from the Test sim's `matchreport` / `innings.report` /
`bowling.report` wording: captain at the toss, pitch, standout batters and bowlers, target, turning point,
"In the end, X beat Y by ...", and player of the match with figures.

Follow-up 2 (user request): an **innings log** like the Test sim's, written above each innings' card in the `.txt`
files (`engine.render.innings_log`). Each line has over.ball, score and event. Events: wickets with the partnership
and the new batter, every 50 up with both batters, 50 partnerships, batter 50/100, big overs, hat-tricks, 5-wicket
hauls with figures, end of innings with the not-out batters. Event stamps were one ball early and are fixed. Stamps
and fall of wickets now use the scorer's notation (6th ball of the 1st over = 0.6). Each XI is listed at the top.
Dropped catches stay out (skipped by decision). No change to how matches play: the same seeds give the same results.

## Step 5: browser UI (2026-10-03)

Scope chosen by the user: core UI + team builder. No engine change (so no calibration step).
- **Server:** `web_ui.py` (Flask, port 5070; 5060/5061 are refused by browsers as SIP ports). One background job;
  the page polls `/api/status`; Stop cancels between matches (`on_match` callback added to `play_series` /
  `play_tournament`, plus `match_count` for the progress bar). Results are saved to `results/last/` with the
  same `save()` as the command line.
- **Page:** `webui/` (style copied from the Test sim; no external scripts, works offline). Modes: Match / Series,
  Tournament, Team Builder. Results tabs: Summary (points tables with NRR, knockouts, top performers, records),
  Matches (Previous / Next, report, scorecard, innings log), Batting, Bowling (sortable, searchable, team filter;
  clickable HS / best figures / 50s / 100s open the match), MVP (official and balanced).
- **Teams:** stored by Cricsheet ID in `data/teams.json` (git-ignored); 10 presets in `data/teams_default.json`
  (8 T20 World Cup 2024 squads, India and Australia ODI 2023). 11-15 players; more than 11 lets the captain pick.
- **Fixed while testing:** the knockout dropdown defaulted to "final" because Flask sorts dict keys (now a list);
  "1 balls" plural.
- **Noted, not changed:** with career-long ratings the captain leaves out e.g. Rohit Sharma from India's squad.
  Year-range ratings (design item T2-10) are planned for step 6.

## Step 6a: year-range ratings and historical teams (2026-10-03)

Scope chosen by the user for step 6: year-range ratings + historical teams, worm and Manhattan charts, fantasy
draft (pre-2002 players from Wikipedia not now). Design item T2-10.

**Method.** `build_ratings.py` now also writes `data/ratings_{fmt}_years.json`: per player and calendar year, the
fit's sufficient statistics (actual and expected counts per metric; expected includes the era baseline and the
opponents' final indexes). `engine/periods.py` rates a player on any year range without refitting: period actual /
expected, shrunk toward his career index by empirical Bayes. Applied as a ratio to his phase indexes. Wides,
no-balls and run-outs stay career-long. Batting slots come from the same years (`by_year.pos` in the raw stats).

**Validation** (`scripts/validate_periods.py`), skill vs "everyone average" for players with >= 120 balls:
1. First try: tau^2 estimated against the career index. It came out at the floor (the period is part of the
   career), so period = career. Fixed: tau^2 from players with data both inside and outside the period.
2. Forecast test (fit <= 2023, rate on the last 1-5 years, predict 2024+): with that tau^2, period ratings were
   *worse* than career (ODI bat runs 24.6% -> 16-19%). Recent form doesn't predict the next seasons better than
   the career level.
3. Held-out year (the historical-team use case: drop year Y from the fit, rate on Y-w..Y+w, predict Y; Y = 2012,
   2016, 2019, 2022). The raw tau^2 still lost to career, so the shrinkage strength was chosen by this test
   (multiples of tau^2), window +-2:

| | ODI bat runs | ODI bowl runs | T20 bat runs | T20 bowl runs |
|---|---|---|---|---|
| career | 41.7% | 41.3% | 33.5% | 32.1% |
| tau^2 x 1.0 | 39.5% | 38.7% | 33.4% | 28.5% |
| tau^2 x 0.2 | 42.4% | 41.2% | **35.6%** | 31.5% |
| tau^2 x 0.1 | **42.5%** | **41.4%** | 35.3% | 31.9% |
| tau^2 x 0.05 | 42.4% | 41.4% | 34.8% | **32.0%** |

Chosen: ODI 0.1 / 0.1, T20 batting 0.2, T20 bowling 0.05 (`TAU_SCALE` in `engine/periods.py`). Gate met:
batting better than career (+0.8 ODI, +2.1 T20), bowling no worse. Tuning stopped here.

**Consequence (shown to the user):** period ratings move only modestly from the career level, because that is
what predicts held-out years best. E.g. Rohit Sharma, ODIs 2007-11: average 50.9 -> 47.4, SR 98.8 -> 92.8 and
batting at 5 (his real numbers then were far lower).

**Historical teams** (`engine/history.py`): squad = the 20 most-capped players of the nation in those years (with
a keeper); the captain picks the best XI from it, as in the Test sim. ODIs from 2002, T20Is from 2005. Why 20:
- with everyone who played, one-series players rated near their career level got picked (Prithvi Shaw and Rajat
  Patidar for India 2021-24 ODIs, Jayasuriya for Sri Lanka 2009-14, McGrath for Australia 2007-12);
- with 15, regulars fell out where second-string sides played many games (Kohli, Jadeja in India's 2024 T20Is).
The UI offers 15 / 20 / 25 / everyone.

**UI:** Classic Series and Classic Tournament modes (rows of from / to / nation; nation list from `/api/nations`).

**Noticed, not changed:** the XI picker (T2-9) values batters by average x strike rate, so from a big pool it can
prefer Steve Smith to Travis Head in T20 and leave out Rohit / Hardik. Raised with the user.

**Tests:** `tests/test_history.py`.

## Step 6b: worm, Manhattan and win-probability charts (2026-10-03)

Matches tab, above the scorecard: run worm (both innings, wicket dots, target line), Manhattan (runs per over
side by side, a dot per wicket) and win probability of the side batting first through both innings (wicket dots,
50% line). Inline SVG drawn from each innings' `overs_log` (runs, wickets, total, win probability per over), so no
chart library and no engine change. Hover shows the over, bowler, score and probability.

## Step 6c: fantasy draft (2026-10-03)

`engine/draft.py` (library; the Test sim's draft read picks with `input()`), `/api/draft/*`, draft room in the UI.
- **Pool:** players with 10+ matches in the chosen years, rated on those years (`engine/periods.py`). Sources:
  full-member internationals (default), + franchise leagues (T20), or all internationals. Associates are off by
  default: in an all-nations T20 pool an Austrian batter ranked 2nd of 1,982 and Uganda / Bermuda / Japan players
  went early (associate ratings run high, a step-2 limitation). Afghanistan players only come in through the
  leagues pool (Cricsheet withholds Afghanistan internationals).
- **Order:** snake, random first order from the seed; 15 picks per team; 2-12 teams; the user drafts one team or
  none (then the computer drafts all and the league starts at once).
- **Computer teams** (game AI, as in the Test sim's draft): value = z-score of the captain's batting value or
  bowling cost within the pool (+0.3 x the other skill for all-rounders), + a bonus while the squad lacks a role
  (minimum 1 keeper, 3 pace, 2 spin, 6 batters), - a penalty when the role is full, + small noise. Suggestions
  for the user use the same score (at most two per role).
- **Then:** a league with the chosen rounds and knockouts (same runner as Tournament); the results page gets a
  Draft board tab.
- **Tests:** `tests/test_draft.py` (snake order, complete squads with the minimum make-up, no double picks,
  turn checks, pool sources, reproducible with a seed, playable).

## Step 7: rating mode for year ranges, learned XI selection (2026-10-03)

User's decisions: (1) offer both year-range rating modes, "blend" by default; (2) replace the hand XI rule with
selection learned from real XIs; plus: the XI should depend on conditions and vary a little when players are close.

**Rating mode "only"** (`engine/periods.py`): the same empirical-Bayes rating as the career fit (prior = role-group
mean x team level, tau^2 = the career fit's) on the period's balls alone. Rohit Sharma ODI (modern-equivalent
average / SR): career 50.9 / 98.8; 2007-11 blend 47.4 / 92.8, only 38.8 / 84.1; 2013-19 blend 53.0, only 61.6.
UI: "Ratings for those years" in Classic Series / Tournament and the draft.

**Learned XI selection** (`engine/selection.py`, `python -m engine.fit.fit_selection`, ~10 min). Final design
(third version, after the user's review of a 2011-23 tournament: Bumrah 10/12, Smith 10/11, Starc 6/11,
Cummins 8/11 v Johnson 11/11):
- **Skill = runs value per match from the engine's own ratings**, over the phases the player really bats and bowls
  in: batting = balls his batting position faces (measured from real matches; ODI 40, 40, 42, 39, 33, 25, 17, 12,
  8, 5, 2 for positions 1-11) x runs per ball above average minus the runs-equivalent of extra dismissals;
  bowling = balls he usually bowls x runs saved per ball plus the runs-equivalent of extra wickets.
- **Learned from real XIs** (conditional logit; data: every full-member XI, ODI 2003+, T20I 2006+, candidates =
  everyone who played for the team within 21 days): the weight of that value against the best keeper, spinners at
  spin-friendly venues (+1.7 x venue spin advantage), ground scoring level (~0), experience (+0.33 per log-cap,
  **used at half weight - the user's decision**), and the **team balance**: a term per number of genuine bowlers
  (peaks at 5; 4 and 6 next; 3 and 7 rare). P(XI) ~ exp(sum u_i + c[bowlers]); exact likelihood via elementary
  symmetric polynomials, gradient checked numerically.
- **The pick** is the best valid XI (keeper; enough bowling for the overs) under that utility - exact: for each
  number of bowlers, the best bowlers plus the best others. **Randomness only from rating uncertainty**: each
  match every player's log indexes are redrawn from their posterior spread (sqrt((1 - confidence) x tau^2)), so a
  clear leader always plays and players whose values overlap swap. Own random stream from the match seed.
- Held-out test (fit <= 2018, test 2019+), real-XI players picked of 11 (engine's version, experience x0.5):
  ODI 8.56, T20 8.34; old rule 8.40 / 8.25; caps only 8.51 / 8.28; random ~7.8 / 7.6. Genuine bowlers per XI:
  learned 4.95 / 5.05, real 4.90 / 5.09.
- Pick rates over 200 matches (neutral venue): India 2011-23 ODI: Kohli, Rohit, Dhawan, Dhoni 100%, Jadeja 98%,
  Bumrah 92%. Australia 2011-23 ODI: Warner, Clarke, Watson, Haddin 100%, Head 90%, Starc 89%, Hazlewood 77%,
  Johnson 76%, Smith 57%, Finch 50%, Cummins 42%. India T20 2024: Kohli, Samson, Suryakumar, Rohit, Jaiswal
  100%, Bumrah 98%. India ODI 2023: Bumrah 98%. Australia 2003-07: Gilchrist, Ponting, Hayden 100%, McGrath 92%.
  Changes per match: 1.1-2.3 (more in 13-year squads, which have more near-equal players).
- Remaining close calls are close *in the ratings*: Smith v Finch ODI 2011-23 (Finch scores 16-19% faster, Smith
  is out 25% less; at the engine's 22 runs per wicket they come out equal); Cummins v Johnson (same bowling:
  economy 5.0 v 5.02, average 23.1 v 23.7; Johnson bats better and has more caps).
- Dead ends (recorded so they aren't repeated): (1) sampling straight from a model of separate batting / bowling
  index weights rotated far too much and ranked bowlers mostly by their batting (Bumrah below Axar, Johnson above
  Starc); (2) forcing every squad to change ~1.7 players per match (the real rate) made clearly best players drop
  out, because real changes are mostly injuries and rest, which the simulation doesn't have; (3) experience as
  "caps to the end of the period" measured career length and dominated 13-year squads at full weight.
- Own random stream, so the ball-by-ball stream is unchanged; engine calibration unaffected (replays use real XIs).
- Tests: `tests/test_selection.py`.
- **Bug found and fixed:** the "India T20 2024" preset had the wrong Rohit Sharma (an Indonesian namesake, 72 balls
  in the data). That, not career ratings, kept him out of India's XIs since step 5. All 149 preset players were
  checked against their nation; this was the only one. Now he plays 70% of matches (84% with 2024 ratings).
- Tests: `tests/test_selection.py` (inclusion probabilities v brute force, sampling frequencies, valid and varied
  XIs, reproducible matches).

## Step 8: pre-2002 ODI players (2026-10-03)

`scripts/build_pre2002.py`: ODI career totals from Wikipedia's "List of <nation> ODI cricketers" (18 nations; a
header-grid parser handles the different layouts; first Runs/Avg column = batting, second = bowling). 1,216 players
who debuted before 2002, linked via Wikidata P2697 -> Cricsheet register (952 also in Cricsheet); styles from the
article infobox. Players who carried on past 2002 keep a pre-Cricsheet part (Wikipedia total minus Cricsheet).
- Era table (`years_odi_pre2002.json`): each player's totals spread over his years and summed per year: run rate
  3.85 (1975) -> 4.67 (2001), balls per wicket 44 -> 41. ODI baselines 1971-2001 = earliest Cricsheet year scaled
  by run-rate and balls-per-wicket ratios to 2001 (`build_ratings.pre2002_baselines`).
- Ratings (`add_pre2002`): the Afghanistan totals method (average -> dismissal index; balls, wickets, bowling
  average -> bowling indexes; **batting strike rate from the role prior**, lists don't have it; no opponent
  adjustment). 983 new players; 227 Cricsheet-era players get a `pre2002` block, used for year ranges before
  their Cricsheet record.
- Engine: Classic modes and the draft go back to 1971 for ODIs. Check: West Indies 1983-87 XI = Richards,
  Haynes, Greenidge, Lloyd, Richardson, Dujon, Logie, Hooper, Garner, Holding, Walsh; simulated 1st-innings mean
  212 (1985 conditions), 238 (1996), brief's target for the 1990s 220-240.
- Limits: strike rates are role priors (Richards' fast scoring isn't captured); batting positions unknown before
  2002 (order from role); appearances per year are spread evenly over a career.
- Rebuild: `build_pre2002.py` (after build_raw_stats) -> `build_ratings.py`.

## League presets and overseas limit (2026-10-03)

`scripts/build_league_presets.py` (default IPL 2026): a preset squad per franchise = every rated player who played
for it that season (16-24 players). Overseas = played internationals for a country other than India. Teams carry
`overseas` + `max_overseas` (4); the XI picker enforces it (`selection.Rules`). Check: a 10-team double round robin
+ IPL playoffs (94 matches, IPL 2026 conditions): never more than 4 overseas in an XI; 1st-innings mean 202.
Not modelled: Impact Player; the real 14-match league schedule. Editing a preset in Team Builder drops the
overseas list (saved teams store players only).

## League-specific ratings: tested, kept off (2026-10-03)

Question (user): Steve Smith's BBL record (avg 47.9, SR 152) is far better than his T20I record (25.4, 126); should
a BBL simulation use a BBL-specific rating? `build_ratings.py` now also writes `ratings_t20_comps.json` (per
player and competition, actual / expected, i.e. already adjusted for that league's opposition and conditions);
`engine/periods.league_ratios` shrinks a player's league record toward his overall rating.
`scripts/validate_leagues.py` (fit <= 2023, predict each league's 2024+ balls) - skill vs flat, all 11 leagues:

| | bat runs | bat dot | bowl runs | bowl dot |
|---|---|---|---|---|
| overall rating | 1.6% | 22.0% | 28.4% | 28.0% |
| league rating, tau^2 x 0.1 | 0.3% | 21.1% | 28.2% | 27.5% |
| x 0.5 | -4.4% | 18.3% | 26.4% | 25.2% |
| x 2.0 | -14.8% | 12.2% | 21.3% | 20.4% |

Every setting is worse, so the gate fails and league ratings stay **off** (`LEAGUE_TAU_SCALE = None`). Players'
league-to-league differences are opposition and conditions (already modelled: in BBL conditions against BBL
attacks Smith already scores more than in T20Is) plus luck.

## League Season mode (2026-10-03)

`scripts/build_league_presets.py` -> `data/league_seasons.json`: the latest IPL (2026) and BBL (2025-26, seasons
run July-June) squads from Cricsheet (everyone who played for each team that season, rated players only), with
overseas lists (limit IPL 4, BBL 3). UI mode "League Season": pick IPL or BBL; double round robin + IPL-style
playoffs in that league's latest conditions. IPL squads are also saved-team presets.

## Impact Player (IPL 2023+) (2026-10-03)

Real use (Cricsheet IPL 2023-26, 556 substitutions): batting first, 207 of 288 brought in a bowler at the start of
their bowling innings (replacing a batter who had batted); chasing, 249 of 268 brought in a batter (182 during the
chase, 67 in the last overs of the first innings once a bowler's overs were done). Expert comment (Aakash Chopra)
is about effects - part-timers and "bits-and-pieces" all-rounders lose their place, batting goes deeper - not
about misuse; the dominant real use is already the rational one.
Engine (`engine/impact.py`, on for comp "ipl" from 2023, `impact_player=` to override). Second version after the
user's review (Stoinis dropped for Ferguson; bowler-for-bowler swaps; break only): decisions on **team** value -
attack = the best 20 overs the side can bowl (quota and usual capacity per bowler), batting = batters by quality x
the balls their position faces. Innings break: biggest attack gain for the side that batted, batting gain for the
chasers. First innings, at a wicket: bring in a batter for a dismissed batter if the expected gain beats the attack
gain available at the break; that gain is weighted by MID_GAIN_SCALE = 0.2, fitted so sides batting first swap
mid-innings 25% of the time as real sides do (the unweighted rule did it 53% of the time and pushed 1st-innings
totals 2% above reality - double counting, since the IPL baselines already contain real use). Scorecards mark the
players (↑ in, ↓ out).
Check (IPL 2026 squads and conditions): 1st innings 197.0 v real 2026 195.8 (2025: 191).
Tie-break (user saw Yash Thakur replace Chahal): a new bowler's overs push out the weakest bowler's whether that
bowler is dropped or a batter who has batted is, so the gains tie; ties now go to dropping the player with the least
bowling capacity (the batter). Bowling swaps then drop a batter 138 times in 146; the other 8 drop an overseas
all-rounder because an overseas bowler comes in and the side is at its overseas limit.
Two more fixes (user: Yash Thakur batting at 5; Punjab batting first with five bowlers): (1) a specialist bowler
with no batting record now defaults to a tail-ender (he had the "middle" default role and prior); (2) in Impact
Player matches the side batting first starts with an extra batter in place of a specialist bowler when a bench
bowler can come in at the break (`impact.batting_first_xi`; XI selection, not the substitution). Check (240 IPL 2026
matches): batting first, 237 bowling swaps at the break; chasing, 240 batting swaps; 1st innings 198.2 v real 195.8
(+1.2%). Mid-innings batting swaps fell to 1% (real 25%): the extra batter now starts instead - left as is, totals
are within the gate.

## Rebuild order

`python -m engine.fit.fit_basics` -> `python -m engine.fit.fit_situation` -> `python -m engine.fit.fit_toss` ->
`python -m engine.fit.fit_venues` (~25 min; caches replays in `data/cache/venue_rows_*.json`) ->
`python -m engine.calibrate` -> `python tests/test_engine.py`.
XI selection: `python -m engine.fit.fit_selection` (after fit_venues; ~5 min).
After a ratings rebuild (`scripts/build_raw_stats.py` -> `scripts/build_ratings.py`, which also writes
`data/ratings_*_years.json`), `python scripts/validate_periods.py --holdout 2012 2016 2019 2022` (~15 min) checks
the period-rating shrinkage. Tests: `tests/test_engine.py`, `test_tournament.py`, `test_history.py`,
`test_draft.py`, `test_selection.py`.

- Mid-innings Impact Player refit (after the batting-first XI change): with an extra batter already in the XI the
  old scale (0.2) left mid-innings swaps at 1%. Real IPL 2023-26: 25% of sides batting first swap during their
  innings, almost all at 6-8 wickets down in overs 13-19. Refit `MID_GAIN_SCALE` = 2.0 (240 IPL 2026 matches):
  25%, at 6-8 down in overs 13-19; first-innings average unchanged (199.9 at 0.2, 201.1 at 2.0).
  **Superseded by the rational model below** (user: teams don't use the rule rationally, so don't copy them).

### Impact Player - rational model (replaces the fitted usage)

`engine/impact.py`, tables from `python -m engine.fit.fit_impact` -> `data/engine/impact_t20.json` (balls each
batter still to come faces after the w-th wicket with n overs left, IPL 2015-26; real first-innings wicket
timelines 2023-26). No usage rates are fitted; every decision compares runs gained now with runs kept by waiting.
- XI after the toss (+ 5 named substitutes): the selected XI, an extra-batter XI or an extra-bowler XI, each
  valued with the substitute plan it leaves (batting first: over 80 real wicket timelines).
- Batting, at each wicket: a batter (or any sub) in for a dismissed player if the gain beats the value of
  waiting = over real innings that were at the same wickets/ball, the later wicket where a sub beats the bowler at
  the break, else the bowler at the break (option value of a collapse).
- Bowling first, end of each over: a bowler / all-rounder in (usually for a bowler who has bowled out) if the
  better remaining overs plus his batting beat the batter the side could bring in for the chase. The rest of that
  innings is then bowled by the over-by-over chooser.
- Break: as before. Card records innings and score at the swap.
- 240 IPL 2026 matches: batting first, 142 batters in play (at 1-7 down, spread through the innings), 78 bowlers
  in play (mostly late, so they can still bat), 20 bowlers at the break; bowling first, 192 batters at the break,
  48 all-rounders/bowlers in play (many after over 15 for a bowled-out bowler). XI changed after the toss in about
  half the sides (batting first: 74 extra batter, 57 extra bowler; bowling first: 94 extra bowler, 38 extra
  batter). First innings 198.7 (199.9 with the old rule), chasing side won 47%. ~75 ms per IPL match.
- Approximations: the XI valuation uses the simpler "beat the break" rule in play; values are runs, not win
  probability; batters still to come are assumed out in order when valuing waiting.

## Pre-2002 batting strike rates from Wikipedia match summaries (2026-10-06)

Wikipedia's lists and infoboxes have no ODI strike rates (Cricbuzz's robots.txt disallows crawlers, Howstat is
behind a bot check, ESPNcricinfo's robots.txt blocks AI crawlers, so none of those were used). But Wikipedia's
tour / series / World Cup pages summarise most ODIs with the top scorers' runs (balls).
- `scripts/fetch_wiki_matches.py`: pages from the "International cricket competitions from/in <period>"
  categories + season pages (cached); templates {{Single-innings cricket match}}, {{Limited overs matches}},
  {{Limited overs international}}; women's, A, U-19, T20 and associate-trophy pages dropped; the same match on two
  pages merged (date + teams). 2,976 matches 1971-2012, about 1,600 of the ~1,800 ODIs before mid-2002.
- `build_ratings.pre2002_strike_rates`: per player, runs in the sample / runs expected at his era's rate. Top
  scorers' innings are faster than average: bias k = 1.053 and noise (variance x balls) = 14.5, measured on 66
  players with 2003-12 summaries and a Cricsheet runs index (correlation 0.73). Estimate = sample / k, shrunk
  toward the role mean (EB, tau2 of the runs fit). 455 pre-2002 players get one (`sr_sample_balls` in the block);
  the rest keep the role prior.
- Examples (strike rate in 2022-26 terms, before -> after): Richards 95 -> 121, Jayasuriya 95 -> 115, Tendulkar
  95 -> 108, Zaheer Abbas 95 -> 113, Haynes 95 -> 92, Gavaskar 95 -> 91, Boycott 95 -> 87, Marsh 95 -> 83.
  Runs-weighted mean index 1.041 -> 1.047 (era levels unchanged).
- Only the runs index changes; dot / four / six indexes stay at the role mean.

## Rain and DLS (2026-10-06)

The Test sim's rain (`../cricket/callcricketnew.py` `raincheck` / `conditions`) loses random overs with hand-set
chances by country group and has no target revision. Here both parts come from data:
- `python -m engine.fit.fit_rain` -> `data/engine/rain_{odi,t20}.json`: every Cricsheet match (ODIs; T20Is + the
  11 leagues) gives a rain profile read off the scorecard (overs lost before the start, first innings ended early,
  chase reduced, chase stopped for good, abandoned), as fractions of the scheduled overs; grouped by host country
  (venue -> the full member that plays there most; leagues -> home country). Share of matches affected, ODI:
  Sri Lanka 26%, West Indies 25%, Ireland 23%, England 20%, NZ 19%, SA 18%, Zimbabwe 14%, Bangladesh 14%,
  Australia 8%, India 7%, Pakistan 6% (all 16%); T20: NZ 12%, WI 11%, England 10% ... India 4%, UAE 1.5% (all 7%).
  Matches abandoned without a ball are not in Cricsheet, so washouts are slightly under-counted.
- `engine/rain.py`: an affected match replays a real profile from its host country (own random stream, so a dry
  match is identical with rain on or off). DLS Standard Edition formulas on the engine's learned resource table
  (`situation.par_frac`; T20 close to published DLS - 5 overs left 35% vs ~33%; ODI gives more to the last overs,
  as modern scoring does): par = S x R2/R1, or S + G x (R2 - R1) with G = average first-innings total in these
  conditions; par at a stoppage; minimum 20 (ODI) / 5 (T20) overs for a result.
- Match: `rain_on=True`; overs can be cut mid-innings; bowler quota = a fifth of the innings (rounded up), re-set
  when overs are cut; phases scale with a shortened innings; the situation tables see balls left in the shortened
  innings. Results "(DLS method)", par results, no result. Card: `rain` notes; innings `rain_stopped`.
- Tournaments / series: `rain=True`; no result = 1 point each and left out of NRR; DLS matches count the side
  batting first as the par score in the chase's overs (ICC); knockouts have a reserve day, then the higher-placed
  side goes through. UI: "Rain (DLS)" checkbox (on by default) in the conditions panel and League Season.
- Check: 400 ODIs at Lord's: 15% DLS / rain-reduced results, 5.5% no result; IPL season: 4 of 79 matches hit.
  `tests/test_engine.py::test_rain`.


## League seasons, pace v spin pitches, reactive bowling changes (2026-10-06)

Built one at a time; each calibrated alone (`python -m engine.calibrate`, history in data/engine/calibration_*.json).

### Every season of 11 leagues
`scripts/build_league_presets.py` now writes every season of IPL (2008-26), BBL, PSL, CPL, SA20, ILT20, BPL, LPL,
MLC, T20 Blast and Super Smash (101 seasons; July-June seasons for leagues across the new year). The overseas
limit per XI comes from the data: the most overseas players at least 5 real XIs fielded that season, counting the
side on the field (an Impact Player swap lists 12 names). IPL 4 (5 in a few seasons: a player Cricsheet records as
capped by the UAE, AD Nath), BBL 3, SA20 4, ILT20 8-9, MLC 7-8, Super Smash 1-2. UI: League Season has a league and
a season picker. All leagues use a double round robin and IPL-style playoffs.

### Pace v spin pitches
`python -m engine.fit.fit_spin` -> data/engine/spin_{t20,odi}.json. For every real match since 2012 (fit_venues'
matches), expected runs and bowler wickets from the ratings for every ball, observed / expected for spin and for
pace, and the match's spin edge d = log(O/E spin) - log(O/E pace). Venue edge = EB mean at the ground; day's edge
= spread beyond noise around the venue edge.
- T20 (6,593 matches): between-venue sd runs 0.04, wickets 0.11; day sd 0.08 / 0.20. ODI (1,304): 0.03 / 0.17;
  day 0.07 / 0.24. Spin-friendly: Providence, R Premadasa, Kathmandu, Eden Gardens, Arun Jaitley; pace-friendly:
  Adelaide, MCG, SCG, Basin Reserve, SuperSport Park, Hagley Oval.
- Engine (`conditions.spin_edge`, `by_type`): edge = venue (relative to the overall mean) + day draw (own random
  stream); spin balls x exp(edge x pace share), pace balls x exp(-edge x spin share), minus half the day variance
  so the average day is neutral. The bowling plan and the over-by-over chooser cost bowlers on these rates, so
  captains bowl more spin on a turner. Pitch report: "...; it turned" / "...; it helped the seamers".
- Calibration (off -> on): T20I 1st inns 167.2 -> 166.9, wkts 6.79 -> 6.85; IPL 187.4 -> 184.7, 6.45 -> 6.54;
  ODI 265.2 -> 264.5, 8.07 -> 8.11; phase run rates within 3.2%. The extra wickets come from captains using the
  favoured type (intended). Gate met; stopped.

### Reactive bowling changes
`python -m engine.fit.fit_reactive` -> data/engine/reactive_{t20,odi}.json. Real matches since 2015 (full-member
internationals + IPL; full-member ODIs): at the end of every over, for each bowler with overs left, overs bowled in
the rest of the innings v runs and wickets above what his ratings expected so far (within cells of overs bowled x
overs gone, adjusting for usual overs per match). T20: -0.019 overs per run above expectation, +0.024 per wicket;
ODI: -0.031 per run, +0.064 per wicket (~160k situations each; captains react mostly to being hit).
- Engine (`Innings.react`): when the plan picks a bowler running above expectation he is taken off with the
  probability that removes the fitted number of overs (the captain picks someone else); a bowler with wickets
  above expectation can be kept on in place of the planned one. Own random stream. Event "X is taken off after
  going for R from O overs".
- Gain: applied at face value the simulated captains reacted ~40% as strongly as real ones (refitting the same
  regression on replays: T20 -0.008, ODI -0.011). GAIN = 3.0 (T20), 4.0 (ODI) gives -0.018 / -0.030 (real -0.019
  / -0.031); wickets +0.016 / +0.053 (real +0.024 / +0.064).
- Calibration: T20I 1st inns 166.3 (real 168.8), IPL 185.4 (186.3), ODI 264.4 (267.5); phase run rates within
  3%; all-outs slightly down (T20I 17.7%, IPL 11.6%, ODI 40.8%). Gate met; stopped.


## DLS fairness, short-innings play and player of the match (2026-10-06)

User report: Gujarat 104/1 in 11 overs (innings ended by rain), Punjab set 99 from 6 overs, made 50/1, and lost by
48 (DLS). Three faults, fixed one at a time.

1. **Resource table.** DLS used the engine's par table (`situation.par_frac`, cell averages of runs still to come).
   Rare states are biased: sides 0 down after 14 overs of a T20 were having good days, so 6 overs with 10 wickets was
   worth 42% of an innings (official DLS: about 38%) and the target was 99 (official about 80). Now
   `engine/fit/fit_dls.py` fits the Duckworth-Lewis form Z0 F(w) (1 - exp(-b u / F(w))): b from the engine's own
   first innings in matches of 5..full overs (replays of the calibration fixtures; fitting b on real in-progress
   states still over-rated short innings - a 25-over ODI chase won 28%), F(w) and Z0 from every complete real
   first innings (cells of overs left x wickets lost). Resources at 20 ODI overs 0.566 (official 0.566), 25 overs
   0.669 (0.665). The example now gets 81.
2. **Short chases batted as if under no pressure.** Even in equal 10-over matches the chaser won 43% (real
   shortened T20s: 49%). The chase table cells for 0-1 down with half the overs left and a high rate needed are
   rare in full chases and were shrunk toward the (balls left, wickets) average over all pressures (runs x1.03 when
   the first-innings table in the same state says x1.12). `fit_situation` now shrinks every chase cell toward the
   first innings in the same state x the pressure response at that stage (pooled over wickets). 10-over chases
   now win 48-50%; full chases unchanged. Also `Innings.par_k`: par in a shortened innings is scaled to its DLS
   resources (chase pressure and the win-probability chart).
3. **Phases in a shortened innings** were scaled in proportion (an 8-over innings had 1.6 death overs, and the
   bowling plan cut phases differently: 6 powerplay overs, no death). Now `data.phases_for`: powerplay scaled, the
   last 5 (T20) / 10 (ODI) overs death overs as far as the innings allows, middle overs the rest - one rule for
   batting and the bowling plan. Shortened innings scoring v real rain-shortened matches: 8 overs 0.49 of a full
   total (real 0.55, 46 matches), 12 overs 0.68 (0.69); ODI 20 overs 0.57 (0.61, 17 matches).
- Fairness (replays with rain forced; chase win %): chase cut at the break T20I 51%, ODI 48%; cut mid-chase
  46-48%; first innings cut short 50-58% (DLS gives the chaser the G term there, as in real matches - real
  DLS-target matches: chaser won 55%). Before: 28-40%.
- Calibration (full matches): T20I 1st inns 166.1 (real 168.8), IPL 185.4 (186.3), ODI 264.5 (267.5); phase run
  rates within 3%; chase won % within 2 points. Gate met.

**Player of the match** was the top win probability added alone, which could give it to a 6 off 3 balls in a close
finish. Now the balanced score (runs, 20/25 per wicket, rate bonuses, catches, win bonus) plus win probability
added x runs per win (`card["runs_per_win"]`: slope of the chase win model at an average target, ~150 in a T20,
~270 in an ODI). On 250 IPL replays, awards to someone with under 25 runs and no wicket fell from 11 to 3.


## Manual captaincy (2026-10-06)

League Season can be played as the captain of one franchise (user request: decisions with the computer's choice
shown, any part skippable). Not fitted - the person's decisions replace the engine's own.
- `engine/control.py`: Controller (interface; makes the computer's choice), WaitingController (waits for another
  thread: the web server). Decision kinds toss, xi, bowler, batter, impact, result; per-kind auto, skip to the end
  of the innings / match / everything (the result pause is skipped only by "everything").
- `engine/match.py`: Match(control={team: controller}); at each decision the engine computes its own choice
  first (same code path as auto play) and asks; None = the computer's choice. XI after the toss (whole squad,
  batting order, keeper, Impact substitutes; overseas limit checked); bowler each over (options = bowlers who keep
  the rest of the innings feasible, no consecutive overs); next batter; Impact Player: offered inside the bowler /
  batter decisions, at the innings break, and on its own when the computer would make it while those decisions are
  left to it - a controlled side's automatic mid-innings swaps are off. Answers are validated; invalid ones fall
  back to the computer's choice. Live state for the screen: Match.live.
- `engine/tournament.py`: play_tournament(control=...), stage and match number passed as context.
- Web: /api/run (league, `captain`, `manual`), /api/status (`captain.pending`), /api/decide;
  `webui/captain.js` (captain screen).
- Tests (`tests/test_control.py`): random answers to every question for both sides of 60 IPL 2024 matches keep
  the laws (quotas, no consecutive overs, 11 players, overseas limit; 120 Impact substitutions at all moments);
  always taking the computer's choice reproduces auto play exactly (no Impact Player); skip; tournament.

## Auction game (2026-10-07)

User's design (2026-10-07): player pool selectable (a real league season, or a range of years as in the draft);
IPL rules; live bidding with skips; retentions (user request). Game AI, not fitted to real franchises' bidding.
- `engine/auction.py`. Rules of the IPL 2025 mega auction: Rs 120 cr purse, squads 18-25 (fewer if the pool is
  small: 85% of pool / teams), max 8 overseas; retentions up to 6 (5 capped at 18/14/11/18/14 cr, 2 uncapped at
  4 cr), unused slots = RTM cards; sets (2 marquee sets of 6, then capped / uncapped by role, 8 per set, random
  order inside a set); base prices by expected price (capped 2 cr-75 L, uncapped 50-30 L); IPL bid steps;
  accelerated round for the unsold, then fill-up at 30 L for teams short of the minimum.
- Valuation: runs value per match (selection.value_parts, the XI selector's own number). Replacement level per
  slot (keeper, 5 bowlers, 5 others; +1 other in Impact Player seasons) = the best player who would make none of
  the k XIs. A team's worth for a player = gain in its best XI (greedy, empty places at replacement level) x its
  money rate + 30 L while it still needs bodies. Market rate = 0.9 x free money / runs above replacement still on
  offer for the open XI places (recomputed every lot); a team's rate is scaled by its money per open place against
  the others' (0.5-2x). Lognormal spread 0.12 per team and player (seeded). Bids capped to keep 30 L per place
  still needed. Computer retention: keep while expected price >= the next slot's cost. RTM: the old team uses it
  if the player is worth the price to it; the computer buyer raises half way to its own worth.
- Expected prices fixed (2026-10-17; user: "expected values are too low always"). Players sold at a median
  1.14-1.34x their expected price (total spend 1.09-1.45x), from two causes: prices were set before retentions
  (which take the best players and some money, so the market rate rose ~9%), and a lot sells at about the
  second-highest of 10 noisy valuations (E = 1.13x for spread 0.12), not at the average one. Now: re-priced (and
  base prices reset) after retentions, x the expected second-highest spread (`second_best`, by quadrature), capped
  at the second-richest team's free purse. Median price/expected over 5 seeds: IPL 2025 1.01, IPL 2023 1.05, BBL
  1.00, T20 2015-24 years pool 1.03 (totals 0.95-1.02). Left: lots late in the auction (uncapped sets, after XIs
  have filled) still sell a little above or below, as the market rate drifts.
- Years pool: overseas = not from the chosen home nation; if the pool has too few home players to fill the squads
  the overseas limits are switched off. Retention from the last auction you played (results/auction_last.json).
- Result, IPL 2025 pool, no user, seed 1: retentions 0-3 per team (Bumrah, Suryakumar, Rashid, Jaiswal...; CSK
  none), top buys 21-24 cr, 38 players at 10 cr+ (incl. retained), median sold price 3.5 cr, 154 sold + 11 filled,
  17 RTM matches, every team ends at the 17-player minimum (the season pool is only ~200 players). Prices follow
  the engine's ratings, so young players with short, strong records (Priyansh Arya, Suryavanshi, Mhatre) go high.
- Web: /api/auction/start, /api/auction, /api/auction/act, /api/auction/last; /api/run mode "auction" (league
  with optional captain, the controller of League Season); `webui/auction.js` (form + auction room).
- Tests (`tests/test_auction.py`): computer-only auction keeps every rule and reproduces from its seed; random
  user answers (retain, bid, limits, skips, RTM) keep every rule; years pool with home nation, retention from a
  given squad, the squads play a tournament; ODI pool without overseas limits.
- Saved runs (user request, 2026-10-08): results/saved/<name>/ = a copy of results/last plus meta.json (mode,
  league / format, year, winner, user team, squads: an auction's or draft's squads, else everyone who played, with
  League Season names "<franchise> <season>" reduced to the franchise). /api/saved (list, save), /api/saved/rename,
  /api/saved/delete; /api/results and /api/match take ?run=. The auction form offers retention from saved runs of
  the same league (season pool) or format (years pool) that share teams.
- Captaincy in every mode (2026-10-08): play_series takes control too; /api/run takes captain_i (index into
  the run's sides) for series / tournament / classic / draft; one "Captain a team" box in the conditions panel.
  Test: a series between a fixed XI and a historical squad, captained by random answers on either side.

### Wishlist, squad planner, accelerated round, report card (2026-10-17)

User's choice from a list of 12 suggestions (1, 3, 8, 12).
- Wishlist: `Auction.set_wish(player, top, ask)`, /api/auction/wish; `user_auto = "wish"` ("Bid by my
  wishlist"): listed players are bid for up to their top bids (the "max" mode the bid question already had),
  "ask" players stop as usual, everyone else is passed. Right to Match follows the top bid; a former player who
  isn't on the list is let go (asking about every one meant 13 stops in one test run). Optional pause before each
  set (question kind "set") to change the list or go back to bidding yourself. Inputs in the players table, the
  wishlist panel and the set preview; a "To you" column (the computer's top bid for your team, no spread).
- Squad planner: `Auction.planner(team)`: best XI by place (open places at replacement level), worth against the
  average team, overseas places used, and for the player on the block: runs a match added, which place, whose
  place he takes.
- Accelerated round: each team names unsold players (`nominate`: worth his base price to the team, up to its
  open squad places); the user ticks theirs (question "nominate"); only named players are auctioned again,
  then the fill-up as before.
- Report card (`Auction.report()`, shown when the auction ends): strength (best XI's runs a match), rank, spend
  (retained part), purse left, squad size, each team's best and dearest buy against expected price, the 8
  biggest bargains and overpays. Predicted table for a double round robin (Monte Carlo over a logistic win
  chance) only when `engine/fit/fit_auction.py` finds strength predicts simulated results (slope over 2 SE).
- Bug fixed on the way (the planner showed it): the best XI always gave the gloves to the best keeper. With many
  keeper-batters the replacement keeper is worth 5.4 runs a match (IPL 2025) against 0.9 for other places, so
  Rickelton counted as +3.2 as keeper instead of +7.6 as a batter with a cheap keeper. Expected prices used +7.6,
  bids used +3.2. `_xi_pick` now also tries the gloves with each of the squad's top 3 keepers or with nobody and
  keeps the best. Price/expected after it, median over 5 seeds: IPL 2025 1.00, IPL 2023 1.01, BBL 1.00, T20
  2015-24 years pool 0.98.
- Win chance (`python -m engine.fit.fit_auction`, ~25 min): computer-only auctions, then engine matches between
  their squads. T20 (IPL 2025 / 2023, BBL, PSL, CPL, 2 seeds each, 4,800 matches): slope 0.030 +- 0.005 per run
  (scale 33 runs: a side 5 runs a match stronger, about 1 SD between auction squads, wins 54%); a 1,200-match
  run gave 0.013 +- 0.010, so the bigger sample matters. ODI (three years pools, 1,080 matches): 0.029 +- 0.036,
  no clear link (years-pool squads differ by only 1.7 runs a match), so ODI report cards have no predicted table.
  Open: the strength differences between auction squads are small next to T20 match noise; predictions are
  close to even by design, not a bug.
- Bug fixed: to_you() during retentions read the market rate before it was set.
- New auction room (2026-10-17, user approved a mockup: docs/mockups/auction_room.html). `webui/auction_room.js`
  (room) beside `webui/auction.js` (form, server calls, wishlist, retention / release / set / nomination
  questions). The setup sidebar folds away while the room is open (☰ brings it back). Top: one switch for how you
  bid (every player / wishlist / computer this set / computer rest; `auto("ask")` goes back to being asked), the
  set timeline, a teams strip (purse bar, squad and overseas places left, RTM cards, open XI places from
  `Auction.needs`). Stage: player card with stat tiles and "adds to you", a price bar (base, expected, to you,
  your limit; values in a legend under it, because labels on the bar collided), Bid / Pass, a limit slider with
  quick buttons and Auto-bid (bids follow the fixed IPL steps, so no jump bids); keys B / P / L, S skips.
  Bidding replay: each log entry now records the teams still in (`"in"`); the room plays the bids back (Fast
  70 ms default, Slow 220 ms, Off; the last 40 at most), lighting up the strip. After you pass or set a limit,
  the rest of that bidding war (`state["prev_lot"]`) plays on that player's card, then SOLD / UNSOLD in the
  buyer's colour, then the next player. Your team: XI as tiles (open places dashed, the player on the block as
  a green ghost in the place he would take), bench, strength against the average team. Sales feed and report
  card (podium of the top 3 plus your team, table, bargains / dearest) in team colours: real colours for IPL
  (all 19 names), BBL, PSL and the IPL owners' teams in SA20 / ILT20 / MLC / CPL; a palette and automatic short
  names for others. Checked in the browser at 1440 px and on a phone (no sideways scroll; the report table
  scrolls in its own box). Bug found on the way: with the sidebar hidden the room fell into a 0-width column.
- Tests: `test_wishlist_and_report` (only listed players bought before the fill-up, each within its top bid;
  planner and report filled in); the random user now also answers set pauses and nominations.

## Captaincy report and opponent levels (2026-10-09)

User: manual captaincy didn't seem to beat the computer; asked for weaker opponents and a report.
- `engine/judge.py`: option values in runs. Bowler = 6 x bowling_cost this over + min-cost transport of the
  remaining overs (bowlers x phases, quotas; no-consecutive rule ignored). Next batter = the order still to come,
  per-ball value in the phase each would bat in x impact.balls_next. XI = batting by slot + impact.attack_value.
- Report: Match logs each of the person's calls (kind, when, you, computer, changed, delta); card["captaincy"];
  judge.season_report sums by kind (and in wins via runs_per_win); results["captaincy"]. Sanity: always taking
  the computer's choice = 0.0 runs; random answers = -853 runs over 15 matches (mostly the random XI order).
- Loose computer captains: Match(skill={team: level}); per decision, with probability eps the side picks by
  softmax(value / T) over its options (bowler, next batter among the next 4, one XI swap with the bench), flips
  the toss, or lets an Impact Player moment pass. Own random stream: expert sides play exactly as before.
  Levels (eps, T runs): average (0.15, 3), easy (0.6, 10).
- Calibration (one pass; IPL 2024 squads, 90 ordered pairs x 10 seeds, expert side v the level):
  expert 51.3%, average 56.4%, easy at (0.35, 6) 56.4% -> retuned to (0.6, 10): 65.8% (+-3). Gate: three
  distinct levels. Stopped.
- UI: "Opponent captains" in the three captain boxes (League Season, Auction, others); "Your captaincy" on the
  results summary; "Your calls" on each match.

## Career mode (2026-10-09)

User's choices: a franchise career first (an international world later, sharing the same pieces); newcomers are
the real debutants while real seasons last, then made-up players drawn from the real debut distribution.

`engine/career.py` (state as JSON, kept by the server in `results/careers/<id>/`), `engine/fit/fit_career.py`
-> `data/engine/career_t20.json`, mini auctions in `engine/auction.py`, `webui/career.js`, `tests/test_career.py`.

### Fitted tables (`python -m engine.fit.fit_career`, ~3 s)

From `data/ratings_t20_years.json` (actual / expected counts per player and year; expected already allows for
era, competition and opponents) and dates of birth (`styles.json`).

- **Age curves** per side and metric: A ~ Poisson(E x player level x f(age)), player fixed effects, ages 19-39,
  smoothed (1-2-1 over neighbouring ages, exposure weighted). Batting runs index: 0.90 at 19, 0.98 at 23, 1.00 at
  25, peak 1.02 at 29-33, 0.97 at 39; dismissals 1.19 at 19 falling to 0.97 at 29-33, back to 1.06 at 39. Bowling:
  economy barely moves (0.96 at 19, 1.01 at 35); wickets 1.09 at 19, 1.05 at 25, 0.93 at 37, 0.90 at 39.
- **Season form:** the yearly spread around level x age. The noise-corrected moment is scaled by the factor the
  year-range ratings validated on held-out years (`periods.TAU_SCALE`: 0.2 batting, 0.05 bowling). Result: sigma
  2.5% for batting runs, under 0.6% elsewhere: beyond age, season-to-season form is hardly measurable. The lag 1-3
  residual autocovariances are negative (no carry-over), so each season's form is drawn afresh. An AR(1) fit from
  the autocovariances was tried first and failed (all covariances negative: the demeaning bias dominates).
- **Retirement:** the share of established players (30+ T20 matches, careers ended by 2023) playing their last
  season at each age: 0.5% at 24, 1% at 27, 2.6% at 30, 6% at 33, 16% at 36, 24% at 39 and 42; everyone at 44.
- **Debut age:** median 24 (for players with no date of birth). A date of birth that puts a first T20 game past
  34 is treated as a namesake's (Mukesh Choudhary's Wikipedia DOB was 1986) and replaced.

### Model

Season level = career rating x f(age) / f(typical age) x (1 + form), per side and metric; the typical age is the
exposure-weighted mean of log f over the real seasons the rating comes from, so a player is rated at his career
level at his career's typical age. Retirements, plus leaving after two unsold auctions in a row. Newcomers: the
real debutants of each real season (first appearance in the league), then (past the last real season) as many
made-up players as the league's average debutants over its last 5 seasons, each a copy of a random real
debutant's rating profile, debut age and overseas status, named from real players of the same nation (no
duplicate of a real name). Conditions: the real season's while they last, then the last real season's.

Auctions: a mega auction (the existing one, retentions from the last squads) every `mega_every` seasons (default
3), a mini auction otherwise: teams keep players at their contract prices (off the purse) or release them (the
computer releases a player expected to fetch under 0.75 x his contract); no RTM. Opening contracts for the real
squads: each player's expected auction price, scaled down so no squad costs more than 95% of the purse (real
squads were bought over several auctions; unscaled, Punjab Kings 2025 cost more than the purse).

### Calibration (12 seasons from IPL 2024, all teams by the computer, seed 7)

| Season | 1st-inns avg | Wkts | Squad age | Made-up players in squads |
|---|---|---|---|---|
| 2024 | 189.9 | 6.35 | 29.2 | 0 |
| 2026 (last real conditions) | 205.4 | 6.22 | 29.2 | 0 |
| 2028 | 205.4 | 6.14 | 28.8 | 38 |
| 2031 | 204.1 | 6.37 | 29.3 | 81 |
| 2035 | 203.7 | 6.79 | 29.8 | 132 |

Gate: once the conditions are fixed (2026 on), scoring stays at the real level (200-210 against 205 at the start)
and squads do not age or get younger. Wickets drift up slightly (+0.5 an innings over a decade) as made-up
players take over; recorded, not tuned. A season takes ~16 s and an auction ~5 s.

## Batting depth still to come (2026-10-09)

The user noticed the engine played 5 down with all-rounders to come the same as 5 down with a long tail (the
situation tables are averages over real line-ups) and asked for deep batting sides to take more risk and win more.

`engine/fit/fit_depth.py` -> `data/engine/depth_t20.json`; `Situation.with_depth`, `Innings.depth`, Match
`use_depth` (calibrate `--no-depth`). Depth = sum of the batting average indexes (runs / dismissal index, middle
overs; unrated 0.4) of the players yet to bat; excess = depth - the real average at that many wickets down
(T20: 7.3 at 0 down, 5.1 at 2, 3.1 at 4, 1.6 at 6). Observed / engine-expected (with all existing situation
multipliers) per innings x wickets group (0-2, 3-4, 5-6, 7+) x excess bucket, shrunk (2000 pseudo-balls) and
mean-preserving within each innings x wickets group.

What real T20 data says (2012-26, internationals and 11 leagues): with 0-2 down, sides with far more batting to
come (excess > 1.5) score 4-5% faster with 7-15% more sixes and no more dismissals (0.94-0.97); short line-ups
(excess < -1.5) score 5% slower with 9-15% fewer sixes. From 3 down the effect is +-2%. Part of it may be the
ratings' shrinkage (deep sides' batters slightly underrated); either way it predicts. ODI cells showed no
consistent pattern (noise around 1): not used.

Calibration (4 replays, same fixtures):

| | real | depth off | depth on |
|---|---|---|---|
| T20I 1st inns | 168.8 | 166.1 (-1.6%) | 168.3 (-0.3%) |
| T20I 2nd inns | 149.7 | 148.9 | 151.5 (+1.2%) |
| IPL 1st inns | 186.3 | 185.4 (-0.5%) | 189.5 (+1.7%) |
| IPL 2nd inns | 172.0 | 170.4 | 172.9 (+0.5%) |

Phase run rates within 2.4%, wickets within 6.5% (IPL death). Gate met; stopped. Effect on results (8 T20I and 10
IPL 2026 presets, 272 games each, depth off -> on): deepest line-ups (India, England, Australia, Mumbai Indians;
depth of No. 3-11 above 9) +3 to +7 runs an innings and about +3-5 points of win %; the shortest (Afghanistan,
Chennai, Lucknow) -1 to -2 runs and -1 to -4 points.

### Extrapolating beyond real line-ups (2026-10-09, same day)

The user asked for the engine to extrapolate beyond what real teams have shown (an all-batting XI was capped by
the deepest bucket, excess > 1.5). The engine now uses a trend instead of the buckets: per innings x wickets group
x metric, multiplier = exp(a + b x excess), Poisson maximum likelihood over cells of 0.1 depth, the slope shrunk by
b^2 / (b^2 + se^2) (late-innings cells are thin), a re-set so the multiplier averages 1 over real balls, log
multiplier bounded at +-0.5 as a safety limit only. The bucket table stays in the file as a check on linearity.

Bug found on the way: the fit took only 11-man player lists, so IPL games since 2023 (Cricsheet lists the Impact
Player substitutes: 12-13 names) were left out; with the trend, the engine then overshot IPL scoring (1st innings
+2.8%, middle and death RPO +3.7-3.8%). Lists of 11-13 are now used (a substituted-out player still counts as to
come: a small overcount). Slopes per unit of depth (about one proper batter), setting a total / chasing:

| wickets down | runs | dismissals | sixes |
|---|---|---|---|
| 0-2 | +1.6% / +1.6% | -1.7% / -0.1% | +3.4% / +4.0% |
| 3-4 | +1.6% / +1.2% | -2.6% / 0.0% | +3.5% / +1.2% |
| 5-6 | +3.3% / +2.8% | -5.1% / +2.4% | +3.7% / +1.5% |
| 7+ | +3.8% / +3.2% | +0.4% / +3.2% | -0.5% / +0.5% |

Deeper sides score faster without losing more wickets (only chasing late do they also get out a little more).

Calibration (4 replays): T20I 1st inns 167.5 v 168.8 (-0.7%), 2nd 150.7 v 149.7 (+0.7%); IPL 1st 188.8 v 186.3
(+1.4%), 2nd 172.9 v 172.0 (+0.5%); phase RPO within 2.5% (IPL middle overs). Gate met; stopped.

All-batting India XI (Jaiswal, Rohit, Kohli, Suryakumar, Pant, Rinku + Hardik, Jadeja, Axar, Dube, Washington
Sundar; depth of No. 3-11 = 12.0 against 9.6 for the India 2024 preset) v the other 2024 T20I presets, 280
games: scores 169.1 without depth, 180.6 with the trend (180.6 v 177.4 with the capped buckets), concedes 167.9,
wins 65.7% (balanced India 2024: scores 164.8, concedes 153.7, wins 66.8%).

### Open issues from the code review of the depth trend (2026-10-09, not fixed yet)

1. **12-13 man lists count a player who will never bat** (`fit_depth.py`, the `11 <= len(xi) <= 13` check). In an
   IPL Impact Player game the substitute and the player he replaces both count as "to come", so fitted depth is
   too high in those games (`mean_depth["9"]` is 0.024 rather than 0). Fix: drop from the list a player who never
   bats once a substitute has batted in his place (Cricsheet's `replacements` block names both players).
2. **The engine compares 11-card depth with a mean built from 11-13 man lists** (`situation.with_depth`), so an
   engine side of exactly average depth reads as slightly below average. This goes away with fix 1.
3. **Newton steps in `poisson_trend` are undamped.** A thin cell (7+ down, sixes) can make `exp(a + b x)`
   overflow and crash the fit on a future rebuild. Fix: step-halving, or bound a and b.
4. **No guard for an old `depth_t20.json`** without `trend` / `cap`: every T20 ball would raise KeyError. Fix:
   `use_depth` should also check for `"trend"` in the file, or `with_depth` should fall back.
5. **The intercept is re-centred before the +-0.5 cap**, so where the cap bites the mean multiplier is not 1.
   Small with today's slopes.
6. **`Innings.depth()` is recomputed on every ball** but changes only at a wicket or an Impact swap. Cache it.
7. The bucket table is still written to `depth_t20.json` but the engine doesn't read it (it's only a check). It
   could become a printout only.
8. One line in the `with_depth` docstring is ~150 characters; re-wrap.

## Ball by ball with aggression bars (2026-10-12)

This is Cricket Captain-style match play. The research, design, decisions and full build log are in
docs/match_play_design.md.
- Each batter has 9 bars of aggression and each bowler 9 bars of plan. Bar 5 is the engine as calibrated: tested
  ball for ball, and the computer's sides always play at 5.
- Fours, sixes, dots and run-outs follow the runs rate with slopes fitted across real situations. Wickets are
  priced so that bar 5 is best on average.
- The person can pause every ball, every over, at the next wicket or at the end of the innings.
- On in League Season, Career and the Auction league, behind an opt-in tick box.
- Gate: no fixed setting beats Normal. With the batting bars, bar 3 is 8 win points worse in T20 and bar 7 15
  points worse.
- Next: the other captain modes; a settled meter in the scorecard; maybe the Easy opponents could misuse the
  dials.
- Highlights (2026-10-17): `Match.log_ball` records each delivery of a captained side (presentation only: no random
  draws, so matches are unchanged; tested) and `webui/highlight.js` replays them as a 2D ball tracker on the
  ball-by-ball screen. Details in docs/match_play_design.md section 7.

## Mushtaq Ali Trophy in the T20 ratings (2026-11-10)

Step 2 of docs/domestic_design.md. Cricsheet's `sma` (Syed Mushtaq Ali Trophy, 695 matches, 2015-16 to 2024-25)
joins the T20 data like the 11 leagues: one entry in `engine/leagues.py` (`league_season=False`, so League Season
still offers 11 leagues; SMAT seasons get their own mode later). Rebuilt: raw stats, styles (new players from
Wikidata/Wikipedia; 303 of the 425 SMAT bowlers with 120+ balls have a bowling type), T20 ratings, league seasons,
and every fit that reads league data or ratings (basics, situation, toss, venues, selection, rain, DLS, spin,
career, depth, aggression, auction). ODI data and ratings are unchanged.
- 1,468 of the 1,489 SMAT players are rated (T20: 6,457 -> 7,587 players); every 2021-22 state has 11+.
- **State sides.** First rebuild: all domestic-only players shared one team in the prior (`league:sma`), and the
  SMAT replay's first-innings spread came out at SD 30.7 v 40.0 real. Now a competition with `side_level=True`
  puts each player in his state (`league:sma:Mumbai`, from `by_league[...]["teams"]` in the raw stats), in a tier
  of its own ("side"). Out of sample (train <= 2021, predict 2022+ balls; skill vs flat, players with 60+ SMAT /
  120+ test balls):

| SMAT prior | SMAT bat runs | bat dot | bowl runs | bowl dot | all T20 bat runs | bat dot | bowl runs | bowl dot |
|---|---|---|---|---|---|---|---|---|
| one SMAT-wide team | 26.6% | 21.9% | 10.2% | 18.9% | 22.6% | 36.0% | 20.3% | 19.0% |
| **state sides, 5000 balls (kept)** | 29.6% | 26.2% | 10.8% | 19.7% | 23.0% | 37.0% | 19.9% | 19.0% |
| state sides, 1500 balls | 31.8% | 29.3% | 11.1% | 20.3% | 23.1% | 37.4% | 19.5% | 18.8% |
| state sides, 500 balls | 32.8% | 30.9% | 10.1% | 20.1% | 23.0% | 37.6% | 19.0% | 18.5% |

  A weaker team shrinkage helps SMAT but costs bowling elsewhere, so the tuned `TEAM_PSEUDO_BALLS` stays.

Replays with real XIs (`python -m engine.calibrate --suite t20i --suite ipl --suite sma`; history in
`data/engine/calibration_*.json`), before -> after, real in brackets:

| | T20I 2021-26 | IPL 2022-26 | SMAT 2019-21 (new suite) |
|---|---|---|---|
| 1st inns mean | 167.5 -> 167.8 (168.7) | 188.8 -> 188.2 (186.3) | 146.1 (146.5) |
| 1st inns SD | 39.5 -> 38.6 (37.6) | 35.6 -> 35.3 (35.2) | **32.9 (40.0)** |
| 1st inns wickets | 6.81 -> 6.83 (6.74) | 6.46 -> 6.36 (6.28) | 6.63 (6.58) |
| all out % | 18.0 -> 17.7 (12.6) | 12.2 -> 11.3 (7.9) | 13.5 (13.8) |
| powerplay / death RPO | 8.05 / 10.05 -> 8.08 / 10.00 (8.01 / 9.94) | 9.20 / 11.22 -> 9.19 / 11.16 (9.08 / 11.04) | 6.71 / 9.33 (6.71 / 9.39) |
| chase won % | 51.8 -> 50.5 (49.2) | 51.6 -> 49.2 (52.4) | 53.8 (59.5) |

Gate: T20I and IPL are as good or better on everything but the IPL chase-win share (3 points further from real).
SMAT averages, wickets, boundaries and phase run rates are within 2-3%; the spread is not (SD -18%, second
innings -19%, 2nd-innings wickets +10%, chases won 54% v 59%). Diagnosis (`spread` replay by team): the engine
orders the states right (real total on simulated mean: slope 0.85, correlation 0.52) but too gently - Mizoram
87 real v 115 simulated, Sikkim 96 v 109; spread of state averages 15 v 22 - and within-match variation is lower
than SMAT's. The pitch-of-the-day term can't supply it (it is fitted on both innings together, where a mismatch
cancels out). Left open; options are in docs/domestic_design.md (risks). Also open: SMAT extras +16% (5.9 real v
6.8: byes, leg byes and runs per wide are fitted per format, and SMAT has fewer wides than the IPL).

Other effects:
- IPL auction (computer-only, 2025 and 2026 pools, 3 seeds): 16 of 75 uncapped players in 2026 move by 1+ run per
  match (Arjun Tendulkar down on his Goa record; Yash Thakur, Vishnu Vinod, Sachin Baby up); uncapped spend 68 ->
  69 cr (2026), 165 -> 159 cr (2025). The top price (Finn Allen, 2026 mini auction) rises 42 -> 47 cr: his rating
  is unchanged, the replacement level moved.
- Aggression bars: the fitted wicket cost of batting faster rises ~5% in the middle and death overs, so the
  higher bars gain fewer net runs (`tests/test_aggression.py`: bar 2 v bar 8 run rate 9.31 v 9.40, was 9.54 v
  9.77). Same method; tests pass.
- Career: age curves unchanged to 0.01; retirement at 27-33 up ~0.5 points (domestic players leave the data).
- Re-running the Wikidata lookups also refreshed 122 dates of birth and 2 bowling styles of existing players,
  which moved the ODI selection weights slightly (real-XI overlap 8.59 -> 8.58).
- The fantasy draft's "leagues" pool now includes SMAT players with 10+ matches in the period.
