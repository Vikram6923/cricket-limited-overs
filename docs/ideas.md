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
   Effort: medium.
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
