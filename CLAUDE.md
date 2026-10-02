# Limited-overs cricket simulator (ODI + T20) — project brief

Read this file at the start of every session. Keep the "Status" section at the bottom up to date.

## Goal

A ball-by-ball simulator for **ODI (50-over)** and **T20 (20-over)** cricket with a browser UI, inspired by the
Test simulator in `../cricket/`. Players are rated from real data. Same spirit as the Test sim (custom XIs,
historical teams, leagues, fantasy draft, rich results pages) but a new engine built for limited-overs cricket.

## Hard rules

- **Never modify anything in `../cricket/`.** Read it for ideas; copy code out of it if useful, but this folder is separate.
- Platform is Windows. Use `pathlib`, UTF-8 everywhere (`open(..., encoding="utf-8")`), and don't assume `\n` line endings in data files.
- Python 3.10+. Keep dependencies small: `flask`, `requests`. No C-extension packages (they failed to install on this machine before).
- The engine is an importable library, **not** a script that asks questions with `input()`. The old Test sim had to be
  driven by piping answers into prompts, which caused hangs and deadlocks. Here the UI calls Python functions directly.

## What to reuse from `../cricket/`

| Reuse | From | Notes |
|---|---|---|
| UI look and layout | `../cricket/webui/` (index.html, style.css, app.js) | Dark theme, mode cards in sidebar, results tabs: Summary, Matches (prev/next), Batting, Bowling, MVP race. Clickable HS / best bowling / 100s popovers that open the match. Records cards (biggest wins, closest finishes). |
| Server pattern | `../cricket/web_ui.py` | Plain Flask, one background job, browser polls `/api/status`. No websockets, no CDN scripts (works offline). |
| Player-pool / draft / team-builder ideas | `../cricket/draft.py`, Team Builder in the UI | |
| Small-sample shrinkage idea | `../cricket/playersconvert.py` | Blends a player's international numbers with a prior until the sample is big enough. Re-implement properly (see Ratings). |
| Era adjustment idea | `../cricket/eradata.txt` | Need per-format equivalents (ODI and T20 scoring rose sharply over time). |
| Ball model structure | `../cricket/callcricketnew.py` → `teaminnings.ball / rate / wicketrate / aggfactor` | Probabilities scaled by batter vs bowler ratings, conditions, aggression. Note the old code already had an unfinished `odi` flag and `aggfactorodi` hook. Rewrite for limited overs; don't port the Test-specific parts (days, declarations, follow-on). |
| MVP formulas | Results UI | Balanced ranking the user prefers: runs + 25 per wicket + 5 per catch + 25 per team win. For limited overs also consider strike-rate / economy bonuses. |

## Data sources (what works, what doesn't)

- **ESPNcricinfo blocks scraping (HTTP 403).** Don't try it.
- **Cricsheet** (https://cricsheet.org/downloads/) — the main source. Ball-by-ball JSON, free, updated within days.
  - `odis_male_json.zip`, `t20s_male_json.zip` (internationals), plus leagues: `ipl_json.zip`, `bbl_json.zip`, `psl_json.zip`,
    `cpl_json.zip`, `sat_json.zip`, `ilt_json.zip`, `the_hundred` etc. if domestic T20 is wanted.
  - Coverage: ODIs fairly complete from ~2002, T20Is from 2005. Check gaps using `info.match_type_number` (consecutive numbers).
  - `https://cricsheet.org/register/people.csv` maps Cricsheet player IDs to ESPNcricinfo IDs (`key_cricinfo`).
  - Each match JSON has `info.registry.people` (name → Cricsheet ID). Use IDs, not names, to join players.
- **Wikipedia** — for career totals of players before Cricsheet coverage (pre-2002 ODI greats) and for first-class / List A /
  T20 career stats, birth dates, batting/bowling style and role from player infoboxes.
  - Pages: "List of <Country> ODI cricketers", "List of <Country> Twenty20 International cricketers". Table formats differ by
    country — write a tolerant parser (split cells only at `||` outside `{{ }}` and `[[ ]]`).
  - Use the API (`action=parse` / `action=query&prop=revisions`), batches of ≤ 25–50 titles, **sleep ~3–4 s between calls**,
    and cache every response to disk. It rate-limits (HTTP 429) quickly.
- **Wikidata** — `wbgetentities` gives `P2697` (ESPNcricinfo ID) and `P569` (date of birth). This is how Wikipedia articles were
  linked to Cricsheet players in the Test project: article → Wikidata QID → cricinfo ID ← Cricsheet register.
- Lessons from the Test project's data mess: never overwrite a good career record with a partial one; always compare match counts
  from two sources and keep the more complete one; keep raw downloads and caches so rebuilds don't re-download.

## Ratings (per player, per format)

Store ODI and T20 ratings separately (a player can be great in one, average in the other).

- Batting: average, strike rate, boundary %, dot-ball %, and the same split by **phase** — T20: powerplay 1–6, middle 7–15,
  death 16–20; ODI: 1–10, 11–40, 41–50. Also typical batting position.
- Bowling: average, economy, strike rate, by phase; bowling type (pace / spin, arm) from Wikipedia infobox.
- Role: opener / top order / finisher / keeper / all-rounder / pace / spin.
- Small-sample shrinkage: Bayesian-style blend toward a prior based on role and the player's domestic List A / T20 record
  (from Wikipedia infobox), weight growing with balls faced / bowled. Small samples must not dominate (a debut 98* should not
  rate as a 98 average).
- Era adjustment: scoring rates by year for each format, so a 1990s ODI side and a 2020s side can play each other fairly.
- Output: one JSON/CSV per format, e.g. `data/ratings_odi.json`, `data/ratings_t20.json`. Keep raw → ratings as a rebuildable
  pipeline (`scripts/fetch_*.py`, `scripts/build_ratings.py`) that the user can re-run each season.

## Engine design

- Ball-by-ball. Each ball's outcome probabilities (dot, 1, 2, 3, 4, 6, wicket, wide, no-ball) come from batter rating × bowler
  rating × phase × pitch/venue × match situation.
- Match situation drives aggression: required run rate in a chase, wickets in hand, overs left, setting a target, death overs.
- Rules: 20 / 50 overs; bowler limits (4 overs T20, 10 ODI); no bowler bowls consecutive overs; powerplays; free hit after a
  no-ball; super over for ties (T20; optional ODI). DLS / rain: later, optional.
- Captaincy AI: batting order (openers, anchors, finishers), bowling plans (who bowls the powerplay / death), field-agnostic is fine.
- Output per match: a structured JSON scorecard (batting, bowling, fall of wickets, partnerships, over-by-over runs for worm and
  Manhattan charts, result, player of the match). Also a text scorecard for reading.
- Deterministic option: accept a random seed so results can be reproduced for testing.

## Engine behaviour ideas (input for step 2b — not approved yet)

Prefer behaviour learned from Cricsheet ball-by-ball data over hand-tuned constants. Every feature must pass calibration
before the next is added (adding many at once makes it impossible to tell which one skewed the totals).

- **Tier 1 (core)**
  - Resources model (DLS-style): balls left × wickets in hand → par scoring rate; both innings use it to set intent.
  - Intent dial: higher intent = more boundaries and higher dismissal risk. Fit the risk-vs-scoring curve per phase from data.
  - Chase logic: pace comfortable chases, slog at very high required rates, all-out attack in the final overs; set batter
    farms the strike late.
  - Settling in: lower strike rate and higher dismissal risk for roughly the first 10 balls, then acceleration
    (strike-rate-by-balls-faced curves from Cricsheet).
  - Phase-specific player ratings (powerplay / middle / death) from step 2.
  - Captain's bowling plan: swing/new-ball bowlers in the powerplay, death specialists saved, quotas managed, no consecutive
    overs, strike bowler back when a new batter arrives.
- **Tier 2**
  - Matchups: batter vs pace / spin, left/right-hander vs bowling type — with small-sample shrinkage.
  - Pressure: runs of dot balls raise false-shot risk; wickets make the next batter cautious → realistic collapses.
  - Batter roles: anchor, aggressor, finisher; flexible batting order (promote a hitter when quick runs are needed,
    keep left-right pairs).
  - Conditions: pitch type (flat / slow-turning / green), dew in night games (second innings easier, spinners weaker),
    ground size (boundary rate), venue scoring history from Cricsheet, toss decision AI.
  - ODI ball age: swing early, spin and reverse swing later.
- **Tier 3**
  - Fielding: drop chances by fielder quality, run-outs from risky singles, stumpings off spin.
  - Extras: wides/no-balls more likely at the death; free hits.
  - Rules: super over, DLS rain interruptions, Impact Player (IPL), phase fielding restrictions built into run rates.
  - Form and fatigue across a tournament.

## Modes (UI)

1. Single match / bilateral series (custom XIs or national teams from any era).
2. League + knockouts (World Cup / IPL-style: groups, points table with **net run rate**, semis, final).
3. Historical teams (nation + year range, as in the Test sim).
4. Fantasy draft (snake draft from a player pool, then a league) — do the draft natively in the UI, no CLI prompts.
5. Team builder (pick 11 from the database, save as a custom XI).

Results pages: points table with NRR, every match with prev/next and worm/Manhattan charts, sortable batting and bowling
tables (with SR and economy), records (highest totals, biggest wins, best figures, fastest 50s/100s), MVP race (official and
balanced).

## Calibration targets (check after building the engine)

- Modern men's T20I first-innings average ~160–170; IPL ~180+ in recent seasons. Typical wickets ~6–7 per innings.
- Modern ODI first-innings average ~270–290; 1990s ODIs ~220–240.
- Distribution sanity: T20 totals 120–230 most of the time, ODI 180–380. Run thousands of simulated matches and compare averages,
  strike rates and economy rates with the real data; tune constants until they match.

## Suggested build order

1. Data: download Cricsheet ODI + T20I zips and the register; build per-player per-format raw stats with phase splits. Verify
   against a few known players (e.g. Kohli, Babar Azam, Rashid Khan, Bumrah).
2. Ratings builder with shrinkage and era adjustment.
2b. **Engine design brainstorm — approval gate.** Before writing any engine code, write `docs/engine_design.md`: go through
   the "Engine behaviour ideas" section above, add your own ideas, and for each one say what it does, which Cricsheet data
   would fit/calibrate it, how hard it is, and which tier you'd put it in. Then **stop and ask the user to approve, cut or
   reorder the list.** Only build what the user approved, and record the decisions in that file.
3. Engine for T20 first (simpler), with calibration tests. Then ODI. Build tier by tier; calibrate after each tier.
4. Series and league/tournament runners, writing JSON scorecards and stats.
5. Flask server + UI (copy the style from `../cricket/webui/`).
6. Historical/pre-2002 players from Wikipedia, draft mode, team builder, MVP, records, charts.

## Status

- 2026-10-02: Folder created with this brief only.
- 2026-10-02: **Step 1 done (raw data + raw stats).** No engine/UI yet.
  - `scripts/fetch_cricsheet.py` downloads `odis_male_json.zip`, `t20s_male_json.zip`, `people.csv` and Cricsheet's
    `missing.html` into `data/raw/`; cached files are never re-downloaded unless `--refresh` (do that once a season).
  - `scripts/build_raw_stats.py` (~20 s, pure function of `data/raw/`) writes to `data/raw_stats/`:
    `players_{odi,t20}.json` (keyed by Cricsheet ID: overall batting/bowling/fielding, `bat_phase` / `bowl_phase`
    splits, `by_year`, batting `positions`, cricinfo ID), `players_*.csv` (headline numbers), `years_*.json`
    (runs/RPO/1st-innings averages per calendar year, for era adjustment), `coverage_*.json` (match-number gaps,
    Cricsheet's own missing list). Phases: T20 overs 1-6/7-15/16-20, ODI 1-10/11-40/41-50. Super overs excluded.
  - `scripts/verify_players.py` compares with Wikipedia infobox career tables (cached in `data/raw/wikipedia/`).
    Kohli, Babar, Bumrah match within a few matches; HS, best figures, bowling balls/wkts exact where no games missing.
  - **Cricsheet withholds all Afghanistan men's matches** (377 across formats). Consequences: Rashid Khan, Nabi,
    Rahmanullah Gurbaz etc. have essentially no international data; every other player is missing their games vs
    Afghanistan (e.g. Kohli's only T20I 100, 122* v Afg, is absent). Accept those small gaps for everyone else.
  - Cricsheet ODI coverage starts ~late 2002 (some 2001-02 present); ODI 294 male matches listed missing; no T20I gaps
    besides Afghanistan + abandoned games. `years_*.json` includes associate matches - filter to full members when
    calibrating (T20I 1st-innings average across all teams is only ~150).
- 2026-10-02: **Afghanistan workaround (user chose: rate them from franchise T20 data).**
  - `fetch_cricsheet.py` also caches 11 men's 20-over leagues in `data/raw/leagues/`: ipl bbl psl cpl sat ilt bpl lpl
    mlc ntb (T20 Blast) ssm (Super Smash). The Hundred deliberately excluded (100-ball, 5-ball overs). Afghanistan
    Premier League is withheld by Cricsheet too.
  - `build_raw_stats.py` now also builds format `t20_league` (5,529 matches, 2,867 players): same schema as T20I plus
    `by_league` per player; `years_t20_league.json` has per-league per-year scoring (IPL 1st-inns avg ~190-195 in
    2024-26, BBL/SA20/CPL ~160-175) - leagues differ in strength/scoring, so weight by league in step 2.
  - `scripts/build_afghanistan.py` -> `data/raw_stats/afghanistan_players.{json,csv}`: 79 players from Wikipedia's
    "List of Afghanistan ODI/T20I cricketers", all linked to Cricsheet IDs; ODI/T20I/List A/T20 career totals from
    infoboxes; styles, DOB (Wikidata); `league_t20` summary (32 players have league data, 2,028 matches; full phase
    splits are in `players_t20_league.json` under `cricsheet_id`).
  - Wikipedia list tables have wrong cricinfo IDs in some reference URLs (Rashid's T20I row points at Mohibullah
    Oryakhel, Fareed Ahmad's ODI row at the same, etc.), and link namesakes (Zahir Khan -> the Indian). The script
    votes across ODI row / T20I row / Wikidata P2697 with a register-name tiebreak, drops articles whose Wikidata ID
    disagrees, and merges duplicate spellings. Keep these checks if reusing the list-parsing for other countries.
  - `scripts/wikiutil.py`: shared cached Wikipedia/Wikidata fetch (batches of 25, 3.5 s pause, 429 back-off) and
    infobox parsing; reuse it for step 6 (pre-2002 players).
  - Gaps: 14 Afghanistan players active since 2025 have no league data - mostly ODI specialists (Rahmat Shah,
    Hashmatullah Shahidi, Ikram Alikhil) whose ODI ratings must come from Wikipedia totals anyway.
  - Plan for step 2: Afghanistan T20 ratings = league ball-by-ball (league-strength adjusted) blended with T20I totals
    from Wikipedia; Afghanistan ODI ratings = Wikipedia ODI totals (+ List A), with role-based phase priors.
  - Full rebuild order: `fetch_cricsheet.py` -> `build_raw_stats.py` -> `build_afghanistan.py` (-> `verify_players.py`).
- 2026-10-02: **Step 2 done (ratings).** Outputs `data/ratings_odi.json` (2,058 players) and `data/ratings_t20.json`
  (6,457; T20 = T20Is + the 11 leagues pooled), plus `.csv` views.
  - `scripts/fetch_styles.py` -> `data/raw_stats/styles.json`: batting hand / bowling type (pace|spin, kind, arm) /
    DOB for 4,142 players via cricinfo ID -> Wikidata SPARQL -> enwiki infobox (cached in `data/raw/wikidata_sparql/`).
    Bowling type known for 2,452. Classify the *displayed* text (`[[Fast bowling|medium]]` is a medium pacer).
  - `scripts/build_ratings.py` model: expected count per ball = baseline[comp, year, phase] x batter index x bowler
    index, for runs / bowler wickets / dots / fours / sixes; plus wide & no-ball indexes (bowlers) and run-out index
    (batters). Three-way alternating fit (bat, bowl, baseline factor). Each player index is an empirical-Bayes shrink
    toward prior = role-group mean x team level; tau^2 estimated from data with precision weights. Hierarchy for team
    level: tier (full member / associate / league-only, unshrunk) -> team (shrunk to tier, 5,000 balls) -> player.
    Phase indexes = overall shrunk by the player's own phase record. Indexes are relative to the player's era (that is
    the era adjustment). Cell cache in `data/cache/` (pickle, auto-invalidated when raw zips change).
  - Engine contract: P(event) = `baselines[comp][year][phase][metric]` x batter `phase` idx x bowler `phase` idx.
    Use comp `t20i_full` / `odi_full` (full member v full member, computed as observed / mean idx product) for
    international conditions; league comps (ipl, bbl, ...) for league conditions. `ref` blocks = expected
    avg/SR/econ in 2022-26 full-member internationals (average player: T20 avg 21.8 SR 127.8; ODI avg 30.1 SR 86.7).
  - Unknown/new player in the engine: use role-group mean x team level (`meta.role_means`, `meta.team_levels`).
  - `scripts/validate_ratings.py`: fit on <=2023, predict 2024-26 ball-by-ball; skill vs "everyone average". Full
    model ODI: bat runs 26%, dismissals 34%, dots 41%; bowl runs 48%, dots 35%. T20: bat runs 25%, dots 37%; bowl
    runs 32%, dots 33%; T20 bowler wickets ~0-3% (mostly noise over two seasons). No-shrinkage variants are
    catastrophically worse (raw career rates overfit); opponent adjustment beats no adjustment on most metrics.
  - Lessons (don't undo): international matches are tagged full / mixed / assoc in the cell cache but MERGED for
    fitting (separate tier baselines absorbed associate weakness and made Nepal/UAE batters look elite); team levels
    must be anchored by an unshrunk tier level (shrinking to 1.0 or to opponents' average froze the associate pool at
    full-member level); over-relaxation in the team solver diverged; the baseline must be a fitted factor (separate
    bat/bowl normalisation left 5-13% miscalibration that ruined bowler predictions); newcomers need the team prior.
  - Afghanistan: ODI = Wikipedia totals (67 players, `source: wikipedia_totals`; SR from role prior, opposition
    treated as average). T20 = league ball-by-ball blended (precision-weighted) with Wikipedia T20I totals for 29
    players (`ball_by_ball+wikipedia_totals`); 36 more from totals only.
  - Known limitations: List A prior is implemented (calibrated regression, ODI) but inactive - infoboxes usually show
    only Test/ODI/T20I/FC columns, so List A exists for 42 players. A few emerging-associate bowlers (Uganda's Ramjani,
    Nsubuga) rank too high in T20 (they bowl mostly at the weakest regional sides); a 4th "emerging" tier was tried and
    made bowling validation worse. Pre-2002 ODI careers are partial (e.g. Lara rated on 2003-07 only) until step 6.
    Ratings are career-long; a recency-weighted / year-range version is needed for historical-team mode.
  - Full rebuild: fetch_cricsheet -> build_raw_stats -> build_afghanistan -> fetch_styles -> build_ratings
    (~1.5 min) -> validate_ratings (~4 min).
  - Next: step 2b (engine design brainstorm in `docs/engine_design.md`, then wait for user approval).
- 2026-10-02: **Step 2b proposal written: `docs/engine_design.md` - AWAITING USER APPROVAL. Build no engine code
  until section 9 of that file records the decisions.** Key points: new `engine/` package porting the good parts of
  `../cricket/callcricketnew.py` (flow, scorecard, match report, MOTM, dismissal/extras) with a new ball model built
  on the step-2 ratings; situational effects as data-fitted multiplier tables; calibration by replaying real fixtures.
  Data probes showed dot-ball pressure does not raise dismissals and new batters score slower but aren't out more.
- 2026-10-03: **Step 2b approved** (decisions in `docs/engine_design.md` section 9: all recommended features, new
  `engine/` package, limited overs only, super over for ties in T20 and ODI, dew skipped).
- 2026-10-03: **Engine Tier 0 + Tier 1 built and calibrated** (`engine/`):
  - `data.py` players/baselines (thin years pooled), `ballmodel.py` per-delivery model (wides, no-balls + free hit,
    W/run-out/4/6 from rates, dot and 1/2/3 solved to honour both dot and runs indexes), `captain.py` (batting order,
    keeper, toss, `BowlingPlan`: overs per bowler from real overs-per-match, phase split from each bowler's real
    phase usage x phase quality via IPF, spells, never consecutive; greedy fallback), `situation.py` (settling-in,
    1st-innings state, chase pressure tables; par/resources; win probability), `match.py` (laws, super overs,
    scorecard dict, events, win-prob worm, turning point, impact = win probability added, POM by impact,
    hitter promotion / left-right pairs, strike farming), `calibrate.py` (replays real fixtures).
  - Fitted tables: `python -m engine.fit.fit_basics` (dismissal mix, run splits, wides, byes, free hit) and
    `python -m engine.fit.fit_situation` (situation tables + chase win model) -> `data/engine/*.json`.
  - API: `from engine import simulate_match; simulate_match(team_a, team_b, fmt, comp, year, seed=...)`, teams as
    `{"name", "players": [cricsheet ids], "keeper"?, "captain"?, "order"?}`. ~8 ms per T20, ~25 ms per ODI.
  - Calibration (`python -m engine.calibrate`, 4 replays of 484 T20Is, 355 IPL, 732 ODIs): first-innings means
    within 2%, phase run rates within ~4%, wickets within 5%, chase win % within 3 points. Remaining: T20I totals
    spread 13% too narrow, too many all-outs, too few hundreds -> expected from missing venue/pitch variance (T2-3/4).
  - Lesson: a greedy captain (best bowler for each phase) distorted phase run rates by 6-8%; real usage patterns fix it.
- 2026-10-03: **Engine Tier 2 built** (see build log, section 10 of `docs/engine_design.md`):
  - Matchups (hand x bowling kind, in `situation_*.json`), venue factor + day's pitch (`conditions.py`,
    `python -m engine.fit.fit_venues`, ~25 min: replays every real match since 2012; per-match residuals cached in
    `data/cache/venue_rows_*.json`), toss AI (`python -m engine.fit.fit_toss`), XI from a squad (`"squad": [ids]`),
    era-neutral play (pass the `comp`/`year` whose conditions you want), text scorecard + match report
    (`engine.render`), position history for batting order (blend of average and most common slot).
  - Pitch variance = within-venue residual variance minus the engine's own variance, per competition (an
    inter-innings covariance variant was tried and reverted, uncalibrated); applied to internationals only.
  - Tests: `python tests/test_engine.py` (laws/bookkeeping invariants over 400 matches, seed reproducibility, super
    overs, unknown players).
  - Full engine rebuild after new data or ratings: fit_basics -> fit_situation -> fit_toss -> fit_venues -> calibrate.
- 2026-10-03: **Process correction + step-by-step calibration** (user paused the work for drift). Reverted the pitch
  model to the last calibrated method, reverted the unplanned 7/8/9-down wicket buckets, removed hand-set strike
  farming, then calibrated each Tier 2 item alone with fixed seeds. Result: all gate criteria met (means within 1.3%,
  spread within ~10%, phase rates within 2.5%); pitch of the day on for internationals only (it over-dispersed the
  IPL). Open, not being tuned: too many all-outs. Full table: `docs/engine_progress.md`.
  - Working rule: one feature, one calibration run, record the result, stop tuning once the gate is met.
- 2026-10-03: Project published on GitHub (user's account Vikram6923; public; MIT licence for code). README.md
  describes the project. `results/`, `data/raw/`, `data/cache/` are git-ignored.
- 2026-10-03: **Step 4 done: series and tournaments** (`engine/tournament.py`, `examples/`,
  `tests/test_tournament.py`; details in `docs/engine_progress.md`). `python -m engine.tournament
  examples/t20_world_cup_style.json --out results/wc` plays an 8-team, 2-group T20 World Cup-style event in ~2.5 s.
  - Next (build order step 5): Flask server + UI (copy the style from `../cricket/webui/`).
