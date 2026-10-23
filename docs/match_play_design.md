# Cricket Captain-style match play: research and design proposal (2026-10-12)

Status: **decided 2026-10-12 (section 5); built (section 6).**

## 1. How Cricket Captain works (research)

Cricket Captain (International Cricket Captain until about 2016) has been a yearly management sim since 1998.
Chris Child wrote its engine as a university project; Childish Things has developed it since 2009. There is no
action gameplay. You manage, then make the captain's calls during a match and watch what happens.

**During a match** (from player guides and forum threads on the Childish Things forums and Steam, 2015-2024
editions; these are player accounts, not the official manual):
- **Batting aggression, for each batter, on a scale of "bars"** (players quote 1 to 9). Higher bars bring more
  runs and more risk of getting out. This is the main control. Typical habits:
  - A new batter starts low (2-4) and is moved up as he gets "settled".
  - The 6 and 7 bat aggressively.
  - In ODIs you go to maximum in the last 8-10 overs depending on wickets in hand; in T20 most of the side is near
    maximum.
  - A boundary off the first ball of an over lets you ease off for the rest of it.
- **A "settled" meter** for each batter (a percentage, apparently from balls faced and runs). Players raise
  aggression at about 30-50% settled.
- **Bowling aggression, for each bowler** (also in bars). Higher bars attack for wickets but leak runs. In older
  editions it also used up the bowler's stamina faster. Fields are tied to aggression: an aggressive setting
  brings fielders in, so loose balls go for runs. Limited-overs players mostly bowl at 1-2 bars to keep the
  economy rate down.
- **Line, length and fields:** presets ("corridor" outside off stump; full, good or short length), batters'
  weaknesses to target now and then, and standard or custom fields.
- **Choice of bowler** each over, rotation and changes of end; **choice of batting order** and who goes in next.
- **How fast play moves:** players recommend ball by ball in limited overs, so they can change aggression after
  each delivery. You can also play an over at a time or skip ahead, and there are optional animated highlights
  (3D since the 2007 edition).
- **Conditions:** pitch and weather (cloud helps swing; players drop aggression by one in heavy cloud), bad light,
  the toss.
- **Help:** a score predictor (added to in 2025).

**Outside matches:** career mode with a county or franchise side (and offers to coach a nation), selection,
coaching individual skills, scouting, transfers between seasons, player editor (2025), historical scenarios and
all-time great teams.

**What players criticise:** each yearly edition changes little; the T20 engine was rebalanced after player
complaints (2025); some think the career-mode balance is off; aggression is a black box, so players argue about
what it really does.

## 2. What we already have

The engine already makes most of a captain's calls and lets a person make them (control.py, captain.js): the
toss, the XI and order, the bowler every over, the next batter at every wicket, the Impact Player. Results,
career mode, auction and saved runs exist. **Missing: the two dials that make up most of Cricket Captain's
match play (batting and bowling aggression), a settled meter, and a live view where you play ball by ball.**

## 3. Proposal

### 3a. Batting aggression from data (the core)

Today every batter bats with the intent real teams showed in that situation: the chase-pressure and state tables
in `situation.py`. That "real-team intent" becomes the middle setting of a 5-step dial for each batter:

| Setting | Meaning |
|---|---|
| 1 Block | survive, singles only |
| 2 Careful | |
| 3 Normal | what real teams do here (the engine as it is now) |
| 4 Attack | |
| 5 All out | |

Each step moves the runs rate up or down, and the other rates follow **the trade-off real teams show**. Across
the 616 situation cells in our fitted T20 table, when the situation makes teams score 10% faster:
- dismissals rise about 16% (elasticity 1.54)
- sixes rise about 27% (2.59)
- fours rise about 9% (0.91)
- dots fall about 6% (-0.60)

That's a first look. The real fit (`fit_aggression.py`) would do it within each phase, for T20 and ODI, and
check it against batters who really did speed up (for example, the same batter at 0-10 balls v 20+ balls in the
same state).

Why this design:
- **Setting 3 is exactly the calibrated engine.** Leaving every dial at Normal changes nothing, so calibration
  isn't at risk.
- **Every other setting is a real, data-backed trade-off, not a hand-tuned constant.** Slogging at 1-for-0
  costs what slogging costs real sides.
- **The computer's captains keep Normal.** The Easy opponent level could also set its batters' aggression
  badly, which is a natural way to make Easy weaker.

Honest limit: the trade-off is measured across situations, so part of it is that bowlers and fields change too
(death overs have both more risk and different bowling). The within-phase fit reduces that but can't remove it
fully.

### 3b. Bowling plan

Cricsheet has no line, length or field data, so we can't fit Cricket Captain's line/length/field presets. A
3-way plan per bowler would be:

| Plan | Effect |
|---|---|
| Attack | more wickets, more runs |
| Normal | as now |
| Contain | fewer runs, fewer wickets |

This is the mirror of the batting dial, using the same fitted trade-off curve (from the bowler's side). It's
weaker evidence than batting (how a bowler's plan trades runs for wickets isn't directly observable), so it
could be left out, or added after batting has been played and checked.

### 3c. Settled meter

The settling-in curve already fitted (`settle` in `situation_*.json`: how a batter's scoring and risk change with
balls faced) becomes a 0-100% meter for each batter. Shown only, no new model.

### 3d. Live match screen

A new screen for the person's matches, used when they choose "play ball by ball" when captain mode is on:
- **Scoreboard:** score, the chase equation, both batters (runs, balls, settled %, aggression dial), the bowler
  (figures, plan), this over.
- **Live charts:** a win-probability and par worm (both exist already) and the projected score ("score
  predictor").
- **Commentary:** a ball-by-ball text feed from templates, using the event logic the match report already has.
- **Buttons:** next ball, end of the over, next wicket, end of the innings, sim the rest. The existing decisions
  (bowler, next batter, Impact Player) pop up in the same screen.
- **Plumbing:** needs a "pause after each ball / over" hook in `Match` that uses the existing `Controller`, the
  same way it already works for decisions.

### 3e. Later, if wanted

Weather and light (no data, would be invented), weaknesses for each player (batter v pace / spin with shrinkage),
fielding plans, animated highlights.

## 4. Decisions for the user

1. Build batting aggression (3a) + settled meter (3c) + live screen (3d) first, and decide on bowling plans (3b)
   after trying it? (recommended)
2. Dial size: 5 steps as above, or Cricket Captain's 9 bars?
3. T20 and ODI together, or T20 first?
4. Which modes get the live screen: everywhere captain mode already exists, or League Season / career first?

## 5. Decisions (user, 2026-10-12)

1. Batting aggression **and** bowling plans in the first build (bowling on the weaker evidence, accepted).
2. **9 bars**, as in Cricket Captain (5 = Normal = the engine as it is).
3. T20 and ODI together.
4. Live ball-by-ball screen in **League Season and Career first**; other captain modes later.

## 6. Build log (2026-10-12)

Built:
- `engine/fit/fit_aggression.py` -> `data/engine/aggression_{t20,odi}.json` (about 1 minute).
- `Situation.with_aggression` and `Situation.settled`.
- `Match.bars` / `ball_turn` (decision kind `ball` in `engine/control.py`, opt-in only).
- Live screen in `webui/captain.js` (`qBall`), with an opt-in tick box in League Season and Career.
- `tests/test_aggression.py`.

**Fit.** Every legal ball since 2012 is pooled into the situation cells (innings x balls left x wickets, x chase
pressure), with expected counts from the ratings alone (baseline x batter x bowler x settling in).
- Within each phase, log(observed/expected) of fours, sixes, dots and run-outs is regressed on that of runs.
  The fit is corrected for each cell's sampling noise, though reliability is 0.87-0.97, so the correction barely
  matters.
- One bar is set so that bars 2 and 8 sit at the 5th and 95th percentile of real sides' runs ratio in that
  phase. Bars 1 and 9 go one step further, beyond real sides.

| | Powerplay | Middle | Death |
|---|---|---|---|
| T20: one bar, runs | x1.033 | x1.056 | x1.064 |
| ODI: one bar, runs | x1.044 | x1.073 | x1.095 |

Sixes move about 2.7-3.8 times as fast as runs in percentage terms, fours about 1-1.3 times, dots -0.4 to -0.9
times. At the death, run-outs rise steeply (+5.2 T20, +3.3 ODI), which matches last-over scrambles.

**Three dead ends (kept here so they aren't tried again):**
1. **The wicket slope across cells** (T20 +1.3 to +1.8) makes aggression nearly free. With it, batting at bar 9
   all game won 69% against 56% at Normal, and containing with the ball also won. Sides score fast where they
   can do it cheaply, so the slope across situations is not the cost of turning up the intent.
2. **Pricing a wicket at the par table's value** (runs lost per wicket at that ball's state) helped, but in the
   engine a saved wicket is worth less than par says. Batting then peaked above bar 5 and containing still won.
3. **Bowling plans as the batter's own curve run backwards:** any move away from Normal then pushes the batters
   off their best intent, so it always helps the bowler. Adding a rising runs cost instead made "contain" leak
   more runs than Normal, which is nonsense.

**What's used.**
- **Wicket slope (batting):** taken from the condition that bar 5 is best on average. Real captains are taken to
  be about right, so a little more intent costs exactly what it gains: sum runs = b x sum(k x V x wickets) + the
  run-out term. V is par runs lost per wicket, and k converts par into the engine's own currency. k is chosen by
  simulation so that first-innings totals peak at bar 5: **T20 k 0.6, ODI k 0.7.** Resulting T20 wicket slopes
  are 3.8 / 5.0 / 6.9 by phase.
- **Bowling plan:** same runs step x 0.5. Wickets move at the batting slope x (1 - 0.4) when attacking and
  x (1 + 0.8) when containing. Attack therefore takes wickets at a little below what its runs cost, and contain
  saves runs at a little below what the lost wickets are worth. The attack edge is set so that opponents'
  first-innings totals are lowest at bar 5. The contain edge is set so that containing all game wins no more
  than Normal; it helps when defending a target, which first-innings totals can't show.

**Result** (one side at fixed bars all game; win % of India T20 2024 v Australia over 400 games and India ODI
2023 v Australia over 200, same seeds):

| Setting | T20 | ODI |
|---|---|---|
| Normal (bar 5) | 56.2 | 60.0 |
| Bat 1 | 32.5 | 42.0 |
| Bat 3 | 47.8 | 54.5 |
| Bat 7 | 41.0 | 52.5 |
| Bat 9 | 18.8 | 34.5 |
| Bowl attack 9 | 55.5 | 57.0 |
| Bowl contain 1 | ~57 (win scan) | ~60.5 (win scan) |

Bar 5 everywhere reproduces the engine ball for ball (tested), so calibration is untouched and the computer's
sides are unchanged. A fixed setting never beats Normal, so the skill is in changing the bars with the
situation: go hard when a wicket is cheap (wickets in hand late on, a set batter), ease off when it's dear, and
attack with the ball when you need wickets.

Rebuild after new data or ratings: `fit_aggression`, then check with `--scan t20 0.5,0.6,0.7`, `--scan-bowl`
and `--scan-contain` that the peaks are still at bar 5.

## 7. Highlights (2026-10-17)

Cricket Captain shows animated 3D highlights; real video is not possible (copyright, and no footage of a simulated
ball) and 3D needs hand-made animations (months). We drew a **2D ball tracker** instead: a mockup first (user
approved the look), then built into the ball-by-ball screen.

What it shows, for the balls since the person's last pause (a setting: Off / Wickets and boundaries / Every ball,
remembered in the browser):
- A top-down ground with the 30-yard ring, the pitch, the bowler, both batters and nine fielders. The ball runs
  from the bowler's hand to the bat, then away along its path (ground shots slow down, lofted ones grow and shrink
  with height). A fielder chases, the rope is cleared for a six, runners cross for singles, twos and threes, and for
  a run-out the throw goes to the stumps and the batter stops short.
- Bowled, hit wicket and stumped send the bails flying. Caught shows the catcher's name at his place (the
  wicketkeeper behind the stumps, the bowler in front).
- A side-on strip shows where the ball pitched (yorker, full, good length, short) and its speed.
- A flash word (SIX, FOUR, CAUGHT BEHIND, RUN OUT, WIDE...) and a result line with the score.

What is the engine's and what is drawn:
- From the engine (`Match.log_ball`, one record per delivery for a captained side; no random numbers are drawn
  there, so a match plays the same with or without it, tested): runs, extras, the wicket, who was out and at which
  end, the catcher or fielder and his role, the free hit, the batter's hand, the bowler's type and the plan bars.
- Drawn by `webui/highlight.js` by rules, seeded by the ball (a replay looks the same): the length, the direction
  of a shot, the catcher's position when a fielder takes it, and the field. Cricsheet has no wagon wheel, no
  length and no fielding positions. The rules: a left-hander's off side is mirrored; sixes go to gaps between deep
  fielders and short balls go square, full balls straight; fours chase to the nearest deep fielder.
- The field follows the phase and the bowling plan: powerplay has catchers (slip, gully) and two on the rope;
  the death has five or six on the rope; a bowler on plan 7-9 (attack) has the catchers in and on 1-3 (contain)
  the men back, so the plan bars show up on the screen.

Not done: no sound; no side-on strip for the person's own bowlers' plans beyond the field; highlights only appear
on the ball-by-ball screen (not in the results pages' match view).

## Sources

- https://www.childishthings.com/forum/forum/current-and-future-games/cricket-captain-2024/83211-batting-bowling-strategies
- https://www.childishthings.com/forum/forum/current-and-future-games/cricket-captain-2018/61731-rough-guide-to-formats
- https://www.childishthings.com/forum/forum/current-and-future-games/cricket-captain-2019/68317-t20-tips-views
- https://steamcommunity.com/app/817720/discussions/0/1708438218850527859/ (T20 tactics)
- https://steamcommunity.com/app/351050/discussions/0/490125103620172006
- https://en.wikipedia.org/wiki/International_Cricket_Captain
- https://www.wisden.com/cricket-news/cricket-captain-2021-review-new-life-in-the-classic-franchise
- https://www.nintendolife.com/games/switch-eshop/cricket_captain_2025
