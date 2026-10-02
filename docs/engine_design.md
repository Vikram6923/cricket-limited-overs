# Engine design (step 2b) — PROPOSAL, awaiting approval

Status: **approved 2026-10-02** (decisions in section 9). Build tier by tier with a calibration gate after each.

## 1. Summary

- Use `../cricket/callcricketnew.py` as the **template** (match flow, objects, scorecard and match report text, MOTM,
  milestone/partnership logging, dismissal and extras handling) but **rebuild it as a new package** rather than edit
  a copy in place. Most of its innings logic is Test-only (days, sessions, declarations, follow-on, 80-over new ball,
  rain overs), its probability core is a set of hand-tuned power laws that can't use the step-2 ratings, and it
  prints / writes `scorecard.txt` / reads `settings.txt` from the working directory, which the brief forbids
  ("importable library, no input()"). Porting the good parts is cheaper and safer than untangling them.
- **One ball model, learned from data.** The step-2 ratings were fitted with exactly the model the engine will use
  (baseline x batter index x bowler index, per phase), so the engine is calibrated "on average" by construction.
  Every extra behaviour (intent, settling in, matchups, venue...) is added as a **mean-preserving multiplier table
  fitted from Cricsheet residuals** (actual / predicted by the ratings), one feature at a time, each followed by a
  calibration run. That replaces hand-tuned constants and keeps stacked features honest.
- **Calibrate by replaying real matches**: simulate thousands of real fixtures with their real XIs, competition and
  year, and compare the simulated distribution of totals, wickets, phase run rates and results with what actually
  happened. That is a fairer test than "average T20I total" targets.
- The data contradicts two ideas in the brief (section 5): **dot-ball pressure does not raise dismissal risk**, and
  **new batters are not more likely to get out** in their first balls - they just score slower. Recommend cutting
  "pressure" as a mechanic and making "settling in" a strike-rate effect only.

## 2. What the Test engine gives us

| Part of `callcricketnew.py` | Verdict | Notes |
|---|---|---|
| `test` -> `teaminnings` -> `over()` -> `ball()` flow, `innings`/`bowling` per-player objects | **Keep the shape** | Rewrite as dataclasses with no class-level mutable defaults (the original uses `extras = []`, `inns = []` etc. as class attributes - shared-state bugs waiting to happen). |
| `ball()`, `rate()`, `wicketrate()`, `aggfactor()`, `det()` | **Replace** | Power-law mixes of `bat/30`, `bowl/30`, `sr`, `er`, `mod`, form, pitch, day; fixed 4s = 0.06z, 6s = 0.003z. Test-tuned, can't take phase ratings. Replaced by section 4. |
| `howout()` fixed dismissal mix (b 21%, lbw 14%, c wk 16%, c 39%, st, ro, hw) | **Port, re-fit** | Re-fit the mix from Cricsheet by format x phase x bowler type (stumpings only off spin/medium is already there; run outs move to the batter's run-out index). |
| `extracheck()` byes / leg byes / wides / no-balls | **Port, re-fit** | Wides/no-balls now come from the bowler's wide/no-ball index x phase baseline; byes/leg-byes rate per phase from data. Fix bookkeeping (a wide currently adds 1 to the team and 4 to the bowler). Add free hit. |
| `bowlchange()` / `bowlchoice()` / `bowlvalue()` | **Replace** | Built around Test spells, 80-over new ball, sessions. Limited overs needs quota planning (section 6, T1-6). |
| Batting order: next batter = `xi[wickets+1]` | **Replace** | Fixed order; limited overs needs promotion of hitters / floating order (T1-7). |
| `declaration()`, `followon()`, `day()`, `raincheck()`, `time()`, timeless Tests | **Drop** | Test-only. (Rain/DLS is a separate optional feature, T3-6.) |
| `result()`/`margin()` ODI branch | **Port** | Already has target/overs-limit logic; extend with ties -> super over. |
| `matchreport()`, `innings.report()`, `bowling.report()` narrative text | **Port** | Nice flavour, works for limited overs with new adjectives (strike-rate bands differ). |
| `motmscore()` / `motmpick()` | **Port + improve** | Use win-probability added (T1-8) or the brief's balanced MVP formula. |
| `pitchmake()` pace/spin/outfield factors, Asia effect | **Port idea, fit sizes** | Effect sizes from venue data (section 5) instead of guesses. |
| Logging of 50s, partnerships, hat-tricks, big overs, drops | **Port** | Becomes the ball-by-ball event log in the JSON scorecard. |
| Output: `print` + `scorecard.txt` files in cwd | **Replace** | Return a dict (JSON scorecard); separate text renderer. |

Bugs noticed in the Test engine (for information - `../cricket` is not to be modified): line 260 `x + x - 50` is a
no-op (meant `x = x - 50`); line 535 `self.bowler.bowling.spell == 0` compares instead of assigning; `result()` sets
`self.test.lose` in the ODI branch but `self.test.loss` elsewhere; line 839 uses the module-level name `test` instead
of `self.test`; `extracheck()` returns `None` for several extras, so a bye of 0 runs falls through as a normal ball.

## 3. Architecture

```
engine/
  ratings.py     load ratings_{odi,t20}.json; player lookup; newcomer prior (role mean x team level)
  conditions.py  format rules (overs, quotas, powerplays), competition/year baselines, venue & pitch factors
  ballmodel.py   per-ball outcome probabilities (section 4) + situational multiplier tables
  captain.py     XI selection, batting order, bowling plan, toss decision
  match.py       Match / Innings / Over / Ball state machine; laws (free hit, super over, last-ball strike)
  scorecard.py   JSON scorecard (batting, bowling, FOW, partnerships, over-by-over, events, result, MOTM)
  render.py      text scorecard + match report (ported narrative)
  fit/           scripts that learn the multiplier tables from Cricsheet residuals (rebuildable, cached)
  calibrate.py   replay real fixtures, compare distributions, print a report
```

- API: `simulate_match(team_a, team_b, fmt="t20", comp="t20i_full", year=2025, venue=None, seed=None) -> dict`.
  No prints, no files, no globals; RNG is a `random.Random(seed)` passed down, so results are reproducible.
- A team is a list of player IDs (+ optional captain/keeper); unknown players get the newcomer prior.
- Speed target: < 30 ms per T20 and < 80 ms per ODI in pure Python, so a 10,000-match calibration takes minutes.
- Format is configuration (overs, innings count, quotas). Tests could be added later on the same core (open question 3).

## 4. Core ball model

For the striker `b`, bowler `w`, competition `c`, year `y`, phase `ph`:

```
rate_m = baseline[c][y][ph][m] x bat_idx[b][ph][m] x bowl_idx[w][ph][m] x situation_m x conditions_m
         for m in {wkt, four, six, dot, runs};  plus wide/no-ball (bowler) and run-out (batter) rates
```

1. P(wide), P(no-ball) first (re-bowled, extra run; no-ball -> free hit next legal ball).
2. Legal ball: P(W) = rate_wkt (+ run-out rate); P(4), P(6) from their rates.
3. The remaining mass splits into dot / 1 / 2 / 3 so that P(dot) matches rate_dot and **expected runs match
   rate_runs** (two equations, solved per ball; the 1:2:3 split comes from the phase baseline). This keeps the outcome
   distribution consistent with every fitted index at once.
4. Dismissal type from the re-fitted mix; byes / leg-byes from phase rates.

`situation_m` and `conditions_m` are products of multiplier tables, each fitted as observed / predicted-by-ratings
over the Cricsheet balls in that cell, so each averages to 1 over real cricket and stacking them doesn't drift.
Each table is shrunk toward 1 when its cell is thin. Tables are fitted **sequentially** (fit A, then fit B on the
residuals left after A) so overlapping effects aren't double-counted.

## 5. Evidence from the data (probes run 2026-10-02)

Full-member internationals + IPL since 2015 (T20: 1,601 matches; ODI: 869). Raw aggregates, not yet controlled for
who is batting (selection effects), but the directions are clear.

**Settling in** - strong effect on strike rate, *no* extra dismissal risk early (the brief assumed both):

| Balls already faced | T20 SR | T20 out %/ball | ODI SR | ODI out %/ball |
|---|---|---|---|---|
| 0-4 | 106.8 | 4.83 | 63.5 | 2.91 |
| 5-9 | 138.6 | 5.36 | 80.9 | 2.94 |
| 10-19 | 148.2 | 5.22 | 88.7 | 2.82 |
| 30-49 | 162.3 | 6.13 | 93.2 | 2.40 |

**Dot-ball pressure** - striker's dismissal rate after 0 / 1 / 2 / 3 / 4+ consecutive dots: T20 5.24 / 5.33 / 5.11 /
5.21 / 5.02 %; ODI 2.77 / 2.75 / 2.57 / 2.58 / 2.47 %. **No pressure effect on wickets.** Strike rate does drop
(T20 137 -> 124), but that is mostly selection (slow batters and tight phases produce dot streaks).

**After a wicket** (balls since the last wicket fell, both batters): T20 SR 112 -> 154 over ~24 balls, dismissal rate
4.9 -> 5.5 % (slightly *lower* right after a wicket). Collapses therefore shouldn't be scripted; they come from
weaker batters coming in. Check in calibration whether the simulated wicket-clustering matches reality.

**Chasing intent** (2nd innings, middle overs): T20 at required rate 6-9 -> SR ~124, out 4.2 %/ball; at 14+ -> SR 144,
out 8.5 %. ODI at RRR 3-6 -> SR ~84, out 2.1 %; at 10+ -> SR 101, out 5.8 %. So pushing harder buys **+15-20 % strike
rate for +100-170 % dismissal risk** - the intent curve is fit-able and steep. Easy chases also speed up (ODI RRR < 1:
SR 106) - batters finish the game.

**First v second innings** (early overs only): T20 RPO 7.75 v 7.88, ODI 4.82 v 5.13; chasing side wins 53 % (T20) and
53 % (ODI) of results. Cricsheet has no day/night flag, so **dew can't be fitted**.

**Matchups** (since 2012, batting hand x bowling kind) - the ball turning away from the bat is harder:

| T20 | RHB SR | LHB SR | ODI | RHB SR | LHB SR |
|---|---|---|---|---|---|
| off-spin | 125.2 | 117.6 | off-spin | 85.6 | 79.5 |
| leg-spin | 124.6 | 131.2 | leg-spin | 87.1 | 90.3 |
| left-arm orthodox | 120.3 | 137.5 | left-arm orthodox | 78.4 | 87.3 |
| pace | 137.8 | 136.5 | pace | 88.6 | 89.5 |

A small generic hand x kind table is well supported (6-14 % SR swings); per-player matchup splits are not (too
noisy for most players).

**Venues**: true spread of venue scoring (after removing sampling noise) ~9 runs in T20 (Dubai 153, Mirpur 145,
Premadasa 148 v Narendra Modi 187, Rawalpindi 187), ~11 runs in ODI. Real but modest; worth a shrunk venue factor.

## 6. Feature catalogue

Effort: **S** = small (part of a session), **M** = one or two sessions, **L** = several sessions.
"Fit from" says what Cricsheet data calibrates it. Recommendation: **build**, **later**, or **skip**.

### Tier 0 - foundation (needed for any match; not optional)

| # | Feature | Fit from | Effort | Rec. |
|---|---|---|---|---|
| T0-1 | Engine package, state machine, laws: 20/50 overs, quotas (4/10), no consecutive overs, strike change, wides/no-balls re-bowled, free hit, all out / target reached / overs done | rules | M | build |
| T0-2 | Ball model of section 4 using step-2 phase ratings, competition/year baselines (`t20i_full`, `odi_full`, leagues) | ratings | M | build |
| T0-3 | Dismissal-type mix and byes/leg-byes re-fitted by format x phase x bowler type | Cricsheet | S | build |
| T0-4 | JSON scorecard (batting, bowling, FOW, partnerships, over-by-over runs for worm/Manhattan, events) + text render + ported match report | - | M | build |
| T0-5 | Simple captain: batting order by usual position, bowling rotation honouring quotas | ratings | S | build |
| T0-6 | Calibration harness: replay real fixtures (real XIs, comp, year), compare totals distribution, wickets, phase RR, results | Cricsheet | M | build |
| T0-7 | Tie handling: super over (T20; ODI optional), result margins, MOTM (ported) | rules | S | build |

### Tier 1 - core cricket behaviour (from the brief, adjusted by the evidence)

| # | Feature | Fit from | Effort | Rec. |
|---|---|---|---|---|
| T1-1 | **Resources / par model** (DLS-style): expected runs still to come given balls left x wickets lost, per format and era | Cricsheet innings | M | build |
| T1-2 | **Intent dial** driven by the situation: chase required rate v par, wickets in hand, overs left, setting a target, death overs. Intent moves runs/4/6 up and wickets up along the fitted curve (section 5: +15-20 % SR costs +100-170 % wickets) | residual tables by RRR band x wickets x phase | M | build |
| T1-3 | **Settling in** - strike-rate multiplier by balls faced (fitted relative to the player's own expected rate, which removes the selection effect). Dismissal multiplier kept only if the controlled fit shows one | residuals by balls faced x phase | S | build |
| T1-4 | Phase-specific ratings | already in step 2 | - | free |
| T1-5 | Chase endgame: finish easy chases quickly; set batter farms the strike with a tail-ender late; all-out attack in the final overs | residuals (last 3 overs, tail at crease) | M | build |
| T1-6 | **Bowling plan**: plan all overs at the start (new-ball pair in the powerplay, spinners through the middle, best death bowlers' overs reserved for overs 17-20 / 45-50), re-plan after each over; strike bowler back when a new batter arrives; never strand quota | ratings + Cricsheet over-allocation patterns by bowler type | M | build |
| T1-7 | **Batting order flexibility**: roles (opener / anchor / aggressor / finisher) derived from the ratings (SR index v out index); promote a hitter when quick runs are needed late, keep left-right pairs when cheap | ratings, Cricsheet positions | M | build |
| T1-8 | Win-probability per ball (from T1-1) -> win-probability worm, "turning point" in the match report, MOTM by win probability added | T1-1 | S | build (my idea) |
| - | Dot-ball "pressure" raising false-shot risk | **contradicted by data** (section 5) | - | **skip** |

### Tier 2 - richer cricket

| # | Feature | Fit from | Effort | Rec. |
|---|---|---|---|---|
| T2-1 | **Matchups**: generic batting hand x bowling kind table (left-hander v off-spin etc.); captain uses it (bowl the off-spinner at the right-handers) | Cricsheet + styles.json | S-M | build |
| T2-2 | Per-player matchups (batter v pace / v spin individually) with shrinkage | ratings refit | L | later (check value after T2-1) |
| T2-3 | **Venue factor** (shrunk venue run-rate and six-rate effect; boundary size shows up in six rate) | Cricsheet venues | S | build |
| T2-4 | Pitch types per match (flat / slow-turning / green) as random draws around the venue factor; spinners/pacers scaled; Asia effect from the Test sim | venue x bowler-type residuals | M | build |
| T2-5 | Toss AI: bat/bowl choice by format, venue and team strengths (chasing wins ~53 %) | Cricsheet toss + results | S | build |
| T2-6 | Dew (second innings easier, spinners weaker at night) | **no day/night flag in Cricsheet** | S | skip, or a user toggle with a guessed size |
| T2-7 | ODI ball age (swing early, reverse swing later) | no ball-age data; phase ratings already capture new-ball skill | - | skip |
| T2-8 | Era-neutral matches: two teams from different eras play under one chosen era's baseline | baselines exist | S | build |
| T2-9 | XI selection from a squad (5-6 bowling options, keeper, balance; picks for conditions) - needed for national/historical modes | ratings | M | build |
| T2-10 | Ratings for a year range (recency-weighted) for historical teams | ratings rerun with year filter | M | build (when mode 3 is built) |

### Tier 3 - extras and polish

| # | Feature | Fit from | Effort | Rec. |
|---|---|---|---|---|
| T3-1 | Run-outs from the batter's run-out index; more likely when chasing hard / last overs | ratings + residuals | S | build (cheap) |
| T3-2 | Stumpings off spin, caught-behind off pace via the dismissal mix | T0-3 | - | free |
| T3-3 | Dropped catches by fielder quality | **Cricsheet doesn't record drops**; dismissal rates are already net of drops | S | flavour only (log line, no effect) or skip |
| T3-4 | Wides/no-balls more likely at the death | already in phase baselines | - | free |
| T3-5 | Impact Player rule (IPL 2023+): 12th player substitution | IPL scoring jump is already in the IPL baselines; the substitution itself is captain logic | M | later |
| T3-6 | Rain + DLS (reduced overs, revised targets) | DLS needs the resources table (T1-1); rain frequency by country/month | L | later |
| T3-7 | Form across a tournament (hot / cold streaks) | weak evidence in the literature; risks adding noise | M | skip |
| T3-8 | Fatigue (fast bowlers in a long tournament) | no usable data | M | skip |
| T3-9 | Ball-by-ball commentary lines for the UI (from events + ported narrative) | - | S | build |

### My additions (included in the tiers above)

- Real-fixture replay calibration (T0-6) - the strongest guard against a mis-tuned engine.
- Residual-table method for every situational effect (section 4) - "learned from data" made concrete.
- Win probability per ball, turning points, MOTM by win probability added (T1-8).
- Whole-innings bowling plan with re-planning (T1-6), so the best bowler is never "used up" before the death.
- XI selection and year-range ratings (T2-9, T2-10) - needed by the national / historical modes anyway.

## 7. Build order and calibration gates

1. Tier 0 -> calibrate: T20 first, then ODI. Expected result before any situational logic: averages right but
   distributions too narrow and chases unrealistic (no intent yet).
2. T1-1 + T1-2 (resources + intent) -> calibrate (chase success rate, totals distribution, death-overs RR).
3. T1-3 settling in -> calibrate (SR by balls faced, ducks and 30+ scores per innings).
4. T1-6 + T1-7 captaincy -> calibrate (overs per bowler type per phase, positions).
5. T1-5 endgame, T1-8 win probability.
6. Tier 2 in the order T2-3, T2-1, T2-5, T2-4, T2-8, T2-9 - each followed by a calibration run.
7. Tier 3 items as wanted.

Pass criteria per gate (full-member internationals, recent years): simulated mean first-innings total within ~3 % of
real, standard deviation within ~10 %, wickets per innings within ~0.3, phase run rates within ~3 %, chase success
rate within ~3 points, and no regression on the previous gate's checks.

## 8. Open questions for the user

1. Approve / cut / reorder the catalogue in section 6 (especially the **skip** items: dot-ball pressure, dew, ball age,
   drops, form, fatigue).
2. OK to build a new `engine/` package that ports pieces of `callcricketnew.py`, instead of copying the file and
   editing it in place?
3. Should the new core also be able to play **Test matches** later (format as configuration), or limited overs only?
4. Super over in ODIs (current rule since 2019 for knockouts) - on by default, or ties stay ties in ODIs?
5. Dew: skip, or a manual "dew" toggle with a guessed effect size?

## 9. Decisions (user, 2026-10-02)

1. Feature catalogue in section 6 **approved as recommended**, including the skips (dot-ball pressure, dew, ODI ball
   age, form, fatigue; dropped catches at most a cosmetic log line). "Later" items stay later.
2. **New `engine/` package inside `cricket-limited-overs`**, porting pieces of `callcricketnew.py`. `../cricket` is a
   read-only reference and is never modified.
3. **Limited overs only** (ODI + T20). No Test support in the new core.
4. **Super over decides ties** in both T20 and ODI (repeated super overs until there is a winner).
5. **Dew skipped** for now.

## 10. Build log

| Item | Status | Where / notes |
|---|---|---|
| T0-1 laws, state machine | done | `engine/match.py` (wides/no-balls re-bowled, free hit, quotas, no consecutive overs, strike) |
| T0-2 ball model | done | `engine/ballmodel.py`; dot and 1/2/3 solved so dot and runs indexes both hold |
| T0-3 fitted basics | done | `engine/fit/fit_basics.py` -> dismissal mix by phase x pace/spin, run splits, wides, byes, run-outs, free-hit multipliers (T20 free hit: 1.8x runs, 3.6x sixes) |
| T0-4 scorecard + text | done | card dict from `simulate_match`; `engine/render.py` scorecard_text / match_report |
| T0-5 simple captain | done, then replaced by T1-6 | greedy choice remains as fallback |
| T0-6 calibration | done | `engine/calibrate.py` replays real fixtures (T20I, IPL, ODI suites) |
| T0-7 super over, POM | done | repeated super overs; POM by win probability added |
| T1-1 resources/par | done | `fit_situation.py` par table (DLS-style), competition/year scale |
| T1-2 intent | done | state tables: 1st innings (balls left x wickets), chase (x pressure = need / par) |
| T1-3 settling in | done | controlled fit: first ball 0.65x runs and 0.69x wickets (T20); new batters defend |
| T1-5 chase endgame / strike farming | endgame via chase tables; strike farming **removed** (was hand-set, not fitted) | - |
| T1-6 bowling plan | done | `captain.BowlingPlan`: real overs-per-match and real phase usage x phase quality, IPF, spells |
| T1-7 batting order | done | slot = blend of average and most common position; extra openers drop to 4; hitter promotion late; left/right pairs only for interchangeable slots |
| T1-8 win probability | done | logistic in log(pressure), max likelihood on real chases; worm, turning point, impact |
| T2-1 matchups | done | hand x bowling-kind table, double-centred (left-handers v off-spin 0.95x runs; LHB v left-arm orthodox 1.11x in T20) |
| T2-3 venue factor | done | `fit_venues.py` (replays every real match since 2012 with the engine; venue = shrunk mean residual) |
| T2-4 pitch of the day | done, internationals only | per-match runs/wickets draw; spread = within-venue variance minus engine variance, per competition; off for leagues (over-dispersed IPL) |
| T2-5 toss AI | done | `fit_toss.py`: real bowl-first rate (T20 63%, ODI 59%) shifted by venue chasing advantage |
| T2-8 era-neutral | done (inherent) | ratings are era-relative; pass the `comp`/`year` whose conditions you want |
| T2-9 XI from squad | done | `captain.select_xi`: keeper, 4 specialist bowlers + best 5th option, best batters, bowling-capacity check |
| T2-10 year-range ratings | open | with historical-team mode |
| Later items (T2-2, T3-5, T3-6) | not started | as approved |

Lessons (keep): a greedy "best bowler for this phase" captain shifted phase run rates by 6-8%; real usage patterns
fixed it. Separate tier baselines and shrinking team levels toward 1 both hid associate weakness (ratings step).
Within-venue match variance (pitch of the day) closed the totals-spread gap for internationals but over-dispersed
the IPL, so it applies to internationals only. Calibrate one feature at a time with fixed seeds (see
`docs/engine_progress.md`).
