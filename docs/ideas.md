# Ideas for the next big features (brainstorm, 2026-10-09)

Nothing here has been approved. It's a menu to choose from. Every idea that changes the engine still goes
through the usual rule: one feature, one calibration run, then stop once the gate is met.

## What other projects do (research summary)

| Project | What it has that we don't |
|---|---|
| SimCricketX (Python T20 sim, PlanetCricket forum) | ball-by-ball text commentary in a live ticker, a player creator, match archive, light/dark theme |
| NextJS cricket manager (PlanetCricket forum) | transfer market, club finances (supporters drive attendance and revenue), players called up from clubs to national sides, several competitions running at once |
| Cricket Captain 2025 (commercial) | player editor, applying for coaching jobs around the world, a quick score predictor, international rankings from the last 4 years |
| ZenGM (Basketball GM etc., browser) | trade AI and a trading block, contracts and finances, scouting and draft classes, God Mode (edit anything), league import/export files, real historical leagues |
| OOTP Baseball (commercial) | replay any real season with real line-ups, "what if" seasons, commissioner mode (manage any team in any game) |
| CricViz / ESPNcricinfo Smart Stats | expected runs and wickets, pressure-weighted "smart" runs and wickets, match impact |
| yorkr / cricketdata (R, Cricsheet) | player and team analysis pages, win-probability contribution per player from real matches |
| A PlanetCricket analyst's post on Cricket Captain career mode | wants innings dashboards (scoring by line, length and side, cumulative innings charts). Cricsheet has no line, length or shot data, so we can't do this. |

Cricsheet already has more than we use: **women's** T20Is (2,183), ODIs (614), WBBL, WPL, the Women's Hundred,
women's Super Smash and Blast; **The Hundred** (men's and women's); domestic one-day cups (England's One-Day Cup,
Australia's One-Day Cup); **Syed Mushtaq Ali Trophy** (695 Indian domestic T20s); Tests; and "recent matches"
downloads for the last 2, 7 or 30 days.

## A. More cricket from data we can already get (cheapest big wins)

1. **Women's cricket.** A full women's game: internationals, WPL, WBBL, the Hundred, Super Smash, with its own
   ratings, baselines, calibration and every existing mode. The pipeline already works by format, so this is
   mostly configuration plus one new set of fits and calibrations. Effort: medium. Impact: about doubles the
   content.
2. **The Hundred** (100 balls, 5- or 10-ball sets, 20-ball powerplay, bowlers limited to 20 balls). This tests
   whether the engine can handle overs that aren't 6 balls. Effort: medium.
3. **Domestic cricket as a talent pool.** Syed Mushtaq Ali (Indian uncapped players), the English and Australian
   one-day cups. Career mode could then bring in real uncapped prospects instead of made-up ones, the IPL auction
   could have its real uncapped sets, and the inactive List A prior in the ratings would finally have data.
   Effort: medium. *Partly done 2026-11-13:* a state career can play the IPL alongside, and the best uncapped
   Trophy performers reach its auction (`engine/ipl_link.py`). Still open: the same for a franchise career, and
   the one-day cups.
4. **Ratings that keep themselves up to date.** A one-click "update to this week" that downloads Cricsheet's
   recent matches and rebuilds incrementally, plus a "current form" rating (weighted towards recent matches) next
   to the career rating. Effort: medium.

## B. Using the engine as a forecasting and what-if tool (most distinctive)

5. **Rewind a real match.** Load any real Cricsheet match, stop at any ball (for example, the 2019 World Cup final
   after 45 overs), and simulate the rest 1,000 times: win probability, likely scores, how often each side won.
   Or take over as captain from that ball. Nobody else offers this, and it uses only what we already have (the
   real line-ups and the state at every ball). Effort: medium.
6. **Tournament forecasts** in the FiveThirtyEight style: take the real fixture list of an upcoming World Cup or
   IPL season with the real squads, simulate it 10,000 times, and show each team's chance of reaching the playoffs
   and of winning. Re-run after each matchday with the real results fixed. Effort: low to medium (tournament
   runner and squads exist).
7. **Replay a real season** (OOTP-style): the real fixtures, venues and line-ups of IPL 2016, then compare the
   simulated table with the real one. This also works as a calibration showcase. Effort: low to medium.
8. **Strategy lab.** Run experiments by simulation: bat or bowl first at this ground, the best batting order for
   these XI, should X open, how many overs for the spinner, how much an Impact Player is worth to this team. It
   would use the captain AI with an optimiser. Effort: medium.

## C. Analysis built on real data

9. **Player pages.** Career and season stats, phase ratings, rating history by year, matchups by bowling type,
   similar players, and "how good would he be in 2025 conditions" (era-neutral numbers). An all-time XI picker
   with era adjustment. Effort: medium (mostly UI).
10. **Expected and impact stats for real matches** (like CricViz and Smart Stats). The engine already has an
    expectation for every real ball, so we can compute runs above expected, wickets above expected and win
    probability added for every real player in every real match, with leaderboards ("most valuable IPL 2025
    player by WPA"). Effort: low to medium (the validation code already replays real balls).

## D. Bigger game layers (career and management)

11. **International career world** (already on the roadmap). A calendar of bilateral tours, ICC rankings, World
    Cups every 2 or 4 years, players shared between country and franchise, selection and call-ups, a captain who
    resigns or is sacked. This is the biggest piece of work here, and it would reuse career mode's ageing, form and
    retirements. Effort: high.
12. **Deeper franchise management.** An IPL trade window, multi-year contracts and the retention rules that follow
    from them, an owner or board with expectations (and getting sacked), applying for jobs at other franchises, a
    scouting fog (ratings shown with uncertainty until a player is scouted or has played). Effort: medium to high.
13. **Player editor, God mode and custom leagues.** Edit ratings, create players, design your own league (teams,
    overs, overseas limit, Impact Player on or off, playoff format), and import or export a whole league or career
    as one file to share. Effort: medium.
14. **Injuries and workload** (skipped in step 2b for lack of data). A simple version for career mode: random
    injuries by age and workload, rest days for fast bowlers. Calibration would be weak, so leave it optional.
    Effort: low to medium.

## E. Watching and presentation

15. **Watch a match live.** Ball-by-ball playback with speed control, a scoreboard, a live worm and win-probability
    chart, and text commentary from templates keyed to the event and situation (a four off a free hit, a wicket
    in a collapse, a milestone). Captain mode already pauses at decisions, and this would make the waits between
    decisions enjoyable. Effort: medium.
16. **Narrative reports.** Season reviews, awards night (team of the tournament, emerging player), a records book
    across all saved runs, and a hall of fame in career mode. Effort: low to medium.

## F. Playing with others and sharing

17. **Multiplayer auction and draft** over LAN or the internet: several humans bid in the same auction or pick
    in the same draft, then each captains their side. The auction is the most fun mode, and it suits friends.
    Effort: medium (the Flask server has a single job now, and this needs rooms and per-player sessions).
18. **Play in a browser with no install.** The engine is pure Python, so Pyodide could run it on a static GitHub
    Pages site. The rating files (8 MB for T20 ratings) would need trimming. A simpler alternative is a one-file
    Windows build (PyInstaller). Effort: medium.

## G. Engine realism still left from the design (Tier 3)

19. Player-v-player matchups (shrunk heavily). Fielding quality: catches and run-outs by fielder, from
    Cricsheet's fielder names on dismissals. Form within a tournament. Each one is calibrated alone.

## H. A playable action game (bat and bowl yourself), researched 2026-10-09

The commercial games are built by big teams over many years. Big Ant has spent about a decade on cricket games;
Nautilus (Real Cricket) grew from 6 to about 45-48 people; WCC2 advertises 150 batting animations and 28 bowling
actions. The one-person cricket projects that succeed are either management games (Play Auction / Cricket Director,
1.5 million visits) or small arcade or rhythm games (Stick Cricket began as a Flash game; Bat to the Beat). The
closest thing to ours is Pro World Cricket Manager 3D, a Python management sim with a 3D highlights view, which is
still rough. I found no open-source 3D cricket game.

Levels of ambition:
1. **Arcade batting and bowling in the browser** (2D or simple 3D, Stick Cricket style). Your timing and
   direction shift the outcome probabilities of our ball model, so ratings still matter and Bumrah is still hard
   to hit. A natural mode: "bat the last 2 overs of a real chase" (rewind). Weeks.
2. **3D match viewer** (three.js, low-poly players, ball paths, fielders chasing): watch the simulated match like a
   broadcast, with the arcade controls on top. A few months for something decent.
3. **A Cricket 24 / Real Cricket class game** (motion-captured animations, physics, fielding AI, art, audio,
   licences for player likenesses). Years with a team; not realistic solo.

Level 1 was prototyped on 2026-10-09 (bat the last overs of a real chase, timing-based) and deleted; the user
didn't think it would work. Idea 1 (Cricket Captain-style match play) was built instead on 2026-10-12.
Our edge in levels 1-2 is the brain, not the graphics: the opposition plays like the real players and the
situation logic, captaincy and Impact Player AI are already done.
Sources: bigant.com, mcvuk.com/development-news/spotlight-nautilus-mobile, digit.in (Play Auction article),
respawn.outlookindia.com (Bat to the Beat), planetcricket.org post 3670139 (Pro World Cricket Manager 3D),
rawg.io/games/world-cricket-championship-2.

## I. GitHub survey of other cricket projects (2026-11-08)

About 60 GitHub searches (by name, description and topic: simulator, game, auction, draft, manager, Cricsheet, win
probability, DLS, captain...) and the READMEs of the ~25 closest projects. Judgements come from READMEs and live
sites, not from running their code. Search only finds public repos whose names or descriptions match, so a few
good projects may be missing.

### The field

| Project | Stars | What it is | Stronger than us at |
|---|---:|---|---|
| [Jamee999/cricket](https://github.com/Jamee999/cricket) | 64 | **The original Test-match simulator this project grew out of** (Python, 2018-23) | Test cricket, alternate history of all Tests (`altcricket.py`) |
| [Aducj1910/IPLSimulator](https://github.com/Aducj1910/IPLSimulator) | 54 | Ball-by-ball IPL sim from players' IPL data, CLI | Press: Wisden, News18 and others covered its simulated 2021 IPL ("RCB win"). No no-balls or byes. |
| [Manishrdy/SimCricketX](https://github.com/Manishrdy/SimCricketX) ([simcricketx.app](https://simcricketx.app/)) | 3 | Flask web platform: T20, T10, List A, the Hundred, First-Class; tournaments, tours, live Socket.IO play, accounts, community board, CI | **Closest rival in breadth.** Five formats incl. multi-day with a look-ahead declaration captain, hosted, re-simulate a fixture and the table updates, scorecard image export, story packs. Ratings are hand-set, not fitted from data, and there is no replay-based validation. |
| [vsharma245-create/spin-xi](https://github.com/vsharma245-create/spin-xi) ([spin-xi.com](https://www.spin-xi.com)) | 0 | Spin for a historical squad-season, draft one player, repeat x11, chase an unbeaten tournament | Ratings from 15,270 real matches, all formats incl. Tests, a 3-minute loop, hosted, friends' leagues and 4-way live draft. Closest to us on data. |
| [TheJaiv/CricVerse](https://github.com/TheJaiv/CricVerse) | 3 | Discord bot: T20/ODI/Test (pink-ball day-night), tournaments, blind draft, career, Elo ladder | Plays where people already are (Discord), scorecards rendered as images, a **blind knowledge draft** ("name a leg-spinner", ratings hidden). Ratings are hand-set (~1,200 players). |
| [Shaurya01836/ipl-auction](https://github.com/Shaurya01836/ipl-auction) ([crickauction.in](https://crickauction.in)) | 36 | Real-time multiplayer IPL auction (React, Firebase) | Internet multiplayer auction with synced timers and bots filling empty franchises. No match engine. |
| [VikashKumarBundela/batnball-cricket](https://github.com/VikashKumarBundela/batnball-cricket) | 1 | One-file phone cricket manager (PWA): leagues, mega/mini auctions, scouting, hidden potential | Installable on a phone, works offline, **daily challenge with streaks**, news feed, Hall of Fame. Fictional players. |
| [Pravman09/IPLsim](https://github.com/Pravman09/IPLsim), [Parth4Mehta/Cricket_Simulator](https://github.com/Parth4Mehta/Cricket_Simulator), [Loledproski/invincible-ipl-simulator](https://github.com/Loledproski/invincible-ipl-simulator), [Vimal9RAM-NAP/14-zero-cricket-sim](https://github.com/Vimal9RAM-NAP/14-zero-cricket-sim) | 0-3 | Smaller IPL sims and "build an XI, go 14-0" draft games | The "perfect unbeaten run" challenge is clearly a popular, shareable format. |
| [georgenegus/cricket-win-probability](https://github.com/georgenegus/cricket-win-probability), [aatmanpandya/cricket-win-probability](https://github.com/aatmanpandya/cricket-win-probability) | 0 | Cricsheet win-probability models (XGBoost, Elo) with Monte Carlo match sims | **Out-of-fold / held-out-season evaluation with Brier scores**, men's and women's, the Hundred. |
| [AdvayMandalia422/cricket-win-probability](https://github.com/AdvayMandalia422/cricket-win-probability) | 0 | Win-probability-added and WAR for every player, pre-registered hypotheses | Finds that "clutch" is not measurable from ball-by-ball data. Prior art for idea 10. |
| [pratinavseth/cricket-captain-llm](https://github.com/pratinavseth/cricket-captain-llm) | 1 | RL environment that trains an LLM to captain a T20 (1.65M Cricsheet balls) | Uses captaincy as an AI benchmark. |
| [Kulraj69/chat-cricket-captain](https://github.com/Kulraj69/chat-cricket-captain) | 0 | Twitch chat votes on each shot of a chase; OBS overlay | Audience play. |
| [mavaali/cricket-mcp](https://github.com/mavaali/cricket-mcp), [naveenpiedy/pitchside](https://github.com/naveenpiedy/pitchside) | 0-3 | Cricsheet in DuckDB behind MCP tools, so Claude can answer stats questions | AI-assistant access. |
| [Dhaiwat10/cricket07-browser](https://github.com/Dhaiwat10/cricket07-browser) | 211 | EA Cricket 07 statically recompiled to WebAssembly (needs your own game copy) | Most-starred cricket game repo found. Relevant to the parked Cricket 07 front-end idea. |

### Where this project stands

- **Data and validation: ahead of everything found.** No other open simulator both fits ratings for ~7,800 real
  players across internationals and eleven leagues from Cricsheet with the same model the engine uses, and checks
  the engine by replaying ~1,500 real matches with their real line-ups. spin-xi is the only one close on data.
  Everyone else hand-sets ratings or tunes outcome weights until results look plausible.
- **Captaincy depth: ahead.** Aggression bars fitted from real trade-offs, a captaincy report that values each call
  in runs, Expert/Average/Easy captains measured over 900 games, a rational Impact Player. Nothing else found
  values decisions this way.
- **Modes: level with the best.** Auction with retentions and RTM, multi-season career with ageing and real
  debutants, league seasons for 11 leagues, rain/DLS, two-player LAN with a draft. Only SimCricketX matches it on
  breadth, and it covers more formats.
- **Visibility: behind almost everyone.** 0 stars, no screenshot in the README, no hosted link, no CI badge. The
  projects that got attention had a play-now link (SimCricketX, spin-xi, crickauction, batnball), an image at the
  top of the README, or a news hook (IPLSimulator's simulated IPL season).
- **Formats: behind.** No Tests (which the original simulator, SimCricketX, CricVerse and spin-xi all have), no
  Hundred or T10, no women's cricket.

### New ideas from the survey (not already listed above)

20. **Show it off: screenshots and a GIF at the top of the README, plus a CI badge.** The cheapest change with the
    biggest effect on whether anyone looks. Effort: low.
21. **Test cricket again,** on the new engine: sessions, declarations, follow-on, new ball, draws. A captain that
    looks ahead for declarations (SimCricketX uses a fitted forecast plus dynamic programming). Cricsheet has
    Tests, so ratings and calibration work the same way. This brings the project full circle with Jamie's original.
    Effort: high.
22. **"Perfect run" challenge** (spin-xi, Invincible, 14-0): spin for a real squad-season, draft one player from
    it, repeat until you have an XI, then try to go unbeaten through a league. A short loop with a shareable
    result. Add a **daily challenge** (batnball): the same seed for everyone each day. Effort: low to medium
    (draft, seasons and engine all exist).
23. **Blind knowledge draft** for the two-player mode (CricVerse): ratings hidden, each pick answers a prompt
    ("a leg-spinner", "a finisher who keeps wicket"). It rewards cricket knowledge instead of reading numbers.
    Effort: low.
24. **Share a result as an image**: a scorecard or season-summary PNG (CricVerse, SimCricketX). Effort: low.
25. **Held-out evaluation of the win-probability chart**: Brier score and a calibration plot on a season the
    ratings never saw, like the win-probability repos above. This would add one more number to "Does it look like
    real cricket?". Effort: low to medium.
26. **An MCP server for the engine** (like cricket-mcp and pitchside, but with simulation): "simulate India v
    Australia at the MCG 1,000 times", "who wins IPL 2027 with these squads?", "what would this saved career's MVP
    average in 2005?". Effort: low to medium.
27. **Captaincy as an AI benchmark** (cricket-captain-llm): the controller and the captaincy report already value
    every call in runs, so "how many runs does an LLM captain cost per match against Expert?" is a ready-made
    benchmark. Effort: medium.
28. **Crowd captain**: viewers of a two-player room or a stream vote on the aggression bar for each ball
    (chat-cricket-captain). Effort: medium.
29. **Re-simulate one fixture in a finished tournament** and let the table and knockouts update (SimCricketX).
    Effort: low to medium.

Survey sources: the repo links in the table. Searches run with `gh search repos` on 2026-11-08.

## Suggested order

1. **Rewind a real match + tournament forecasts** (5, 6). Unique, mostly reuses existing code, and they show off
   the engine.
2. **Women's cricket** (1). The most content for the least new design.
3. **Watch a match live with commentary** (15). It makes every mode more fun.
4. **International career world** (11) or **multiplayer auction** (17): the big layer, whichever you'd play more.
5. Smaller extras in between: player pages (9), real-match impact stats (10), the Hundred (2).

## Sources

- SimCricketX: https://planetcricket.org/forums/threads/released-simcricketx-v1-0-complete-t20-experience-with-realistic-match-engine-free-to-play.122749
- NextJS cricket manager: https://planetcricket.org/forums/threads/next-js-cricket-simulator.122508/post-3660478
- Career mode analyst post: https://planetcricket.org/forums/threads/career-mode-an-analysts-view.106254/
- Cricket Captain 2025: https://www.nintendolife.com/games/switch-eshop/cricket_captain_2025
- ZenGM: https://github.com/zengm-games/zengm , https://zengm.com/blog/tag/new-feature/
- OOTP replays: https://www.brewcrewball.com/2011/6/26/2244095/review-out-of-the-park-baseball-2012
- Smart Stats: https://www.espn.com/cricket/story/_/id/30017173/introducing-smart-stats-where-context-trumps-raw-numbers
- CricViz app: https://apps.apple.com/gb/app/cricviz/id1044644979
- yorkr: https://tvganesh.r-universe.dev/yorkr ; cricketdata: https://pkg.robjhyndman.com/cricketdata/articles/cricketdata_R_pkg.html
- Cricsheet downloads: https://cricsheet.org/downloads/
