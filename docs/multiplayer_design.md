# Two-player mode: one person bats, the other bowls (proposal, 2026-11-07)

Status: **decided 2026-11-07 (section 8).**

Two people on two devices on the same Wi-Fi (`python web_ui.py --lan`, added 2026-11-07) play one match against each
other. Each captains a side: when your side bats you set your batters' aggression bars; when it fields you set your
bowler's plan. The engine plays every ball as it does now.

## 1. What already exists

| Piece | Where | What it gives us |
|---|---|---|
| A controller for each side | `Match.control` (`engine/match.py`), `engine/control.py` | Every decision is already sent to the controller of the side it belongs to. Two `WaitingController`s, one per side, already give two people their own questions. |
| Ball-by-ball bars | `Match.ball_turn`, `data/engine/aggression_*.json` | Batting side: the two batters' bars (1-9). Fielding side: the bowler's plan bars (attack / contain). Bar 5 = the calibrated engine. |
| Pace controls | `ball_turn`, `until` = over / wicket / innings | A T20 does not need 240 decisions per person. |
| Captain decisions | kinds toss, xi, bowler, batter, impact, result | Each person also captains their side (toss call, XI, bowling changes, next batter, Impact Player). |
| Highlights | `Match.log_ball`, `q["since"]`, `webui/highlight.js` | Each side's question already carries the balls since that side last looked. |
| Other devices | `web_ui.py --lan` | The UI is reachable from a second laptop or phone on the same Wi-Fi. |
| Polling | `/api/status`, `/api/decide`, `webui/app.js` `poll()` | Plain HTTP polling, no websockets (project rule); fast enough on a LAN. |

## 2. What is missing

1. **Seats.** The server has one `Job` with one `controller`. It needs a controller per seat and must show each device
   only its own question: `/api/status` today returns the open question to anyone who asks, so the batter could read
   the bowler's bars before choosing.
2. **A lobby.** The host sets up the match; the second device joins and takes the other side.
3. **Both choosing at once.** `ball_turn` asks the batting side, waits, then asks the fielding side. In two-player
   play neither should see the other's choice before the ball.

## 3. Proposal

### 3a. Seats and lobby (core)

- New mode card **Two players** (host device). The host picks format, competition / year, venue, both teams (any
  team the UI can build today: presets, saved XIs, historical, league franchises), rain, pitch, and which side they
  captain.
- Starting it creates a **room** with a short code (4 letters) and two seats, each with a random secret token. The
  host's token is stored in the host browser's `localStorage`.
- The host screen shows the join link (`http://<LAN IP>:5070/?join=ABCD`, using `lan_addresses()`), the code, and a
  "Waiting for player 2" box. The second device opens the link (or types the code on the Two players card), gets
  the other seat's token, and both screens move to the match.
- Every two-player request carries the seat token: `/api/mp/status?seat=<token>` returns the match state plus *this
  seat's* open question only; `/api/mp/decide` checks the token owns the question.
- A third device opening the link once both seats are taken joins as a **spectator** (scoreboard and highlights, no
  questions).
- Only one job runs at a time (as now). While a two-player match runs, the normal Run buttons stay disabled, as they
  are during any running job.

Server shape: `Job.controllers: {team name: WaitingController}` (the single-captain modes keep using one entry);
`Room {code, seats: {token: team}, spectators}`; the existing `/api/decide` keeps working for single-player modes.

### 3b. Both choose at once, then both choices are shown

- Split `WaitingController.decide` into `post(question)` and `wait()`. In `ball_turn`, when both sides have a
  person deciding this ball, post both questions, then wait for both answers. With one person (today's modes) the
  behaviour is unchanged.
- After the ball, both screens show what each side chose ("Batting 7 bars v bowling attack 8") next to the
  highlight, so players can learn to read each other.
- Pace controls stay per person, so one person can play to the end of the over while the other still looks at each
  ball (their bars carry over without being asked).

Alternative (section 7, question 1): the bowler commits first and the batter sees it before choosing. Simpler and
closer to real cricket (the batter sees the field), but it takes the guessing out of it.

### 3c. Timer and disconnects

- Optional **shot clock** per ball (off / 10 s / 20 s). On time-out the last bars are kept, so a slow player never
  stalls the match. Captain decisions (bowler, batter, XI) get a longer clock (e.g. 60 s) and the computer's choice
  on time-out.
- **Disconnects:** each seat's last poll time is tracked. If a seat has not polled for 60 s the other player sees
  "Player 2 has dropped - wait / hand their side to the computer". Reopening the link with the saved token takes the
  seat back. Handing a side to the computer sets that controller's `manual_kinds` to empty (existing mechanism).

### 3d. Screens

- Reuse `webui/captain.js` (the ball question, bars, highlights, captain decisions) for each seat. Additions: the
  opponent's status line ("Bowling side is choosing..." / "locked in"), the reveal after the ball, the shot clock.
- Match end: the normal results page on both devices, plus a head-to-head line (wins between these two players in
  this room). The captaincy report (`engine/judge.py`) works for both sides already.

### 3e. Calibration

Ideas 3a-3d change nothing in the ball model. Two players who leave everything at bar 5 get the calibrated engine.
No calibration run needed; a test checks that a two-player match with both sides at defaults matches a
computer-only match with the same seed.

## 4. Optional: delivery v shot guessing ("arcade" setting)

For a more game-like duel on top of (or instead of) the bars:

- The bowler picks a delivery: yorker, good length, short / bouncer, wide outside off, slower ball (pace); stock ball,
  flighted, quicker / arm ball, wide of off (spin).
- The batter picks a shot: defend, push for one, drive, loft, pull / sweep.
- A payoff table multiplies that ball's dot / 1-3 / 4 / 6 / wicket rates: pull v bouncer = more sixes and more top
  edges; loft v yorker = more bowled / caught; defend v anything = few runs, few wickets.

**Caution:** Cricsheet has no line, length or shot data, so this table would be designed by hand, not fitted, which
goes against the project's "learn from data" rule. To keep totals realistic it must average to 1.0 for each rate
when both sides choose at random in the real mix of deliveries, and it needs its own calibration run (totals, phase
run rates, wickets) before use. Suggested: off by default, labelled "Arcade".

## 5. Later extensions on the same seats

| Extension | Notes | Effort |
|---|---|---|
| Two people in one League Season or Tournament | Each captains a team; their matches against each other are two-player matches, the rest against the computer. The tournament runner already takes a `control` dict for any number of teams. Needs: what to do while one person's match is being played (spectate it, or both play at once - only one job runs). | medium |
| Two-player auction | Both bid live in the auction room; computer bidders fill the other teams. `engine/auction.py` takes one user; needs a second, plus raise / pass from two devices. Probably the most fun extension. | medium-large |
| Two-player draft | Snake draft, turn-based, the easiest of the three. | small |
| Pass and play on one device | Both seats on one screen, choices hidden behind a "hand the laptop over" screen. | small |
| Over the internet | Done: `python web_ui.py --public` behind HTTPS (README "Hosting it for friends"): any number of rooms, each visitor with their own runs, an optional site password. | done |
| Phones | The ball screen should work at phone width so a phone can be the second device. | small-medium |

## 6. Build order and effort

1. Seats, lobby, two controllers in one single match, both choosing at once (3a, 3b). Mostly `web_ui.py` and a
   lobby screen; `engine/control.py` gets `post` / `wait`; `ball_turn` asks both sides before waiting. Tests: two
   scripted controllers play a full T20 and ODI; defaults match a computer-only match; a seat cannot read or answer
   the other seat's question.
2. Reveal, shot clock, disconnect handling (3c, 3d).
3. Series (best of 3 / 5) between the two players - small, reuses the series runner.
4. One of: two-player League / Tournament, two-player draft, two-player auction (section 5).
5. Arcade delivery v shot (section 4), only if wanted, with its own calibration run.

## 7. Decisions for the user

1. Ball by ball: **both choose at once** (hidden, then shown) or **bowler first, batter sees it**?
2. Bars only, or also the **arcade delivery v shot** setting (section 4)?
3. Shot clock: off by default, or on (10 s)?
4. After the single match / series: which extension first - League / Tournament, draft, auction, or pass and play?
5. Should both players be able to pick any teams (custom XIs, any era), or should the guest pick their own team in
   the lobby?

## 8. Decisions (user, 2026-11-07)

1. Both choose at once (hidden, then shown).
2. Bars only - no arcade delivery v shot (section 4 not built).
3. Shot clock off by default.
4. No extensions for now (section 5 not built). Scope: one two-player match (3a-3d).
5. Each player picks their own team in the lobby.
6. Added by the user: both players can skip, like the skips in the existing captain mode (play to the end of the
   over / to the next wicket / to the end of the innings; skip to the end of the innings / match; hand any kind of
   decision to the computer). Each person's skips affect only their own side.

## 9. Build log (2026-11-07)

Built as decided: one two-player match (3a-3d), bars only, shot clock off by default, each player picks their own
team, skips for both players.

- **Engine** (`engine/control.py`, `engine/match.py`): `Controller.post` / `wait` (`decide` = post + wait).
  `Match.ask_all` posts every question for the moment before awaiting any answer; `ball_turn` and the XI after the
  toss use it, so both people answer at once. One-person modes behave as before (one question at a time).
  Optional `WaitingController(clock={kind: seconds})`: out of time = the computer's choice (for "ball": keep the bars).
  Ball-log entries now carry the batter's bars (`bars`) next to the bowler's plan (`plan`) for the reveal.
- **Skips:** `Match.bars_of` returns 5 (the calibrated engine) whenever ball by ball is not the person's at that
  moment - after a skip to the end of the innings / match, or when "Ball by ball" is left to the computer. Before,
  the last bars set stayed in force while the computer "played"; this also changes the one-person modes, for the
  better. "Take back my decisions" (`/api/mp/control` who=me) clears a skip and restores the lobby choices.
- **Server** (`web_ui.py`, section "two players"): one room at a time (`ROOM`), two seats with secret tokens,
  spectators. `/api/mp/create`, `/join`, `/lobby` (team, decisions, ready, rematch, leave), `/state` (only your own
  question; the other side's current kind; the latest scoreboard; seconds since the other seat last polled),
  `/decide`, `/control` (take back / hand an absent player's side to the computer after 60 s). The match is an
  ordinary job (mode "mp", `play_series` n=1) with `Job.controllers`; Stop cancels both sides. Results carry
  `captaincy_by` (each player's own captaincy report). Join links are shown only when the server runs with `--lan`.
- **UI** (`webui/multiplayer.js`, plus hooks in `captain.js`, `app.js`, `index.html`): Two players mode card (host:
  shot clock; join: code), room screen (code, join link, both seats live, team picker for saved or classic teams,
  decisions, Ready), the captain screens reused per seat with an opponent status line ("choosing a bowler…"), the
  reveal line after each ball, the clock, the waiting screen with the live score, "Back to the room" on results.
  The seat token is kept per tab (sessionStorage) with localStorage as the fallback, so two tabs can test both seats.
- **Calibration:** none needed - the ball model is unchanged; `tests/test_multiplayer.py` checks that two players who
  leave everything to the computer get exactly the computer-only match (T20 and ODI, fixed seeds).
- **Tests:** `tests/test_multiplayer.py` (both sides posted before either is awaited, defaults = computer, random
  play keeps the laws incl. Impact Player, a skip at 9 bars plays like the computer, shot clock, the server room
  with seat isolation, same-team check, spectator, rematch, leave). All older suites pass.
- **Checked in the browser** (`web-ui-lan-test`, port 5072): host on localhost, guest on the LAN address via the
  join link; classic v saved team; toss, both XIs at once, bowler choice, bars on both sides with the reveal, skip
  to the end of the innings and take back, host page reload (resumes), guest away 60 s -> hand-over -> guest
  reopens and sees "the computer is playing your side", skip to the end, results with each player's report,
  rematch; lobby at phone width.
- Not done (decided out of scope): series between the two players, two players in a league / tournament / draft /
  auction, the arcade delivery v shot setting. A single match is labelled "won the series 1-0" on the results page,
  as one-match Match / Series runs always were. (Series and the label: fixed 2026-11-08, section 10.)

## 10. Series between the two players (2026-11-08, user chose it as the first extension)

- **Play:** a single match, best of 3 or best of 5 (default best of 3), chosen when hosting and changeable by the
  host in the room (both then confirm Ready again). A best-of series stops as soon as one player can no longer be
  caught: `play_series(..., best_of=True)`. Ties after a super over and no-results count for nobody, so a series
  can be drawn.
- **Between matches:** in a series both players get the "result" pause at the same moment (`Match` now posts it
  through `ask_all`; with one person nothing changes) showing the result, player of the match and the series
  score, with "Next match (2 of 3)" or "See the series results". The next match starts when both have pressed it
  (or the clock runs out, if there is one). Each player's toss / XI / bars decisions carry over to every match.
- **Series score while playing:** `/api/mp/state` returns `series` {of, wins by seat, match, finished}; a result
  on screen already counts. Shown in the captain screen header and on the result pause.
- **Head to head:** the room keeps `record` {matches won, series won by seat, series played} across rematches;
  shown on each seat card in the room. It starts again when a new player takes the guest seat.
- **Results:** kicker shows "best of 3"; a single match now reads as the match result instead of "won the series
  1-0" (also in the ordinary Match / Series mode when it plays one match).
- Also fixed on the live screen: after the last ball the score bar showed "need 27 off 0" instead of the result;
  short team names in the opponent line and the player of the match.
- **Tests:** `tests/test_multiplayer.py` adds best-of stops when decided (and a plain series still plays all
  matches), the result pause posted to both before either is awaited, and a server room playing a best of 3 with
  the host changing the length in the room, both result pauses, the record and the rematch. All other suites pass.
- **Checked in the browser** (port 5071, two tabs as the two seats): best of 3, result pause on both, Australia won
  2-0 and the series stopped after match 2, results page, back to the room with the record; room and result pause
  at phone width (390 px).

## 11. Two-player draft (2026-11-08, user: "Yes, build it")

- **Room settings (host):** Teams = "Each player picks a team" (as before) or "Draft squads", chosen when hosting
  and changeable in the room. Draft: player-pool years (default the last ten seasons), pool (full members /
  + franchise leagues for T20 / all internationals), computer teams 0 / 2 / 4 / 6. Each player names their team
  instead of picking one; both press Ready and the draft starts.
- **Draft** (`Draft(..., users=[two names])`, `run_cpu` stops at either person): the existing snake draft, 15
  players each, order shuffled. Each device shows the draft room (pool, suggestions on your own pick, your squad
  and needs, the board); only the player whose turn it is can pick. "Pick for me" (one computer pick), "Auto-draft
  the rest of my squad" / "Pick myself again", host "New draft". With a shot clock on, a pick not made within 60 s
  is the computer's. A player away for 60 s can be auto-drafted by the other. The pool is sent once
  (`/api/mp/draft/pool`); the state carries who is taken.
- **Then:** no computer teams -> the drafted squads play the room's single match / best of 3 / best of 5. With
  computer teams -> a single round robin, then a final (4 teams) or semi-finals (6, 8); both players' matches
  against each other are two-player games, a match against a computer team is played by that player alone while
  the other watches; result pause after each of your matches; "Draft league · match 3 of 7" in the header.
- After the run, "Back to the room" returns to the finished draft: both press Ready to play the same squads
  again, or the host starts a new draft. Results carry the draft board (your squad highlighted).
- **Head to head:** only matches between the two players count; a league title won by a player is counted too.
- **Server:** room `draft`, `draft_t`, seat `dname`, `auto`; `/api/mp/state` phase "draft" (each seat's own view,
  suggestions only on your turn, seconds left with a clock); `POST /api/mp/draft` (id / auto one / rest / stop /
  take / ready / redo). A guest leaving drops the draft.
- **Also fixed:** the draft room was wider than a phone screen (pool table and board); it now fits at 390 px.
- **Tests:** `test_server_draft_then_series` (names, same-name check, turns enforced, suggestions only for the
  player on the clock, 30 picks, host-only new draft, best of 3 with drafted players only, rematch keeps the
  squads), `test_server_draft_league_with_computer_teams` (2 computer teams pick at once, auto-draft the rest, 4-team
  league + final = 7 matches, head to head and titles). All other suites pass.
- **Checked in the browser** (two tabs): room settings, draft with picks from the suggestions and the pool,
  auto-draft the rest, Ready on both, a 4-team league (the first match two-player, ball by ball on the guest's
  phone-width screen), results with the draft board, back to the finished draft, New draft -> the room with the
  record.

## 12. Two-player auction (2026-11-08, user chose it as the next extension)

Both players bid live in the auction room, each on their own device, against computer bidders for the other teams;
then the bought squads play.

**What exists.** `engine/auction.py` runs a whole auction as a generator with one user: retentions (or releases in a
mini auction), sets with live bidding (the user is asked "bid at X?" at each step while not leading; computer teams
bid by what a player adds to their best XI, priced by a market rate), Right to Match, an accelerated round, fill-up,
wishlists and "the computer bids for me" skips, a report card. The room (`webui/auction_room.js`) replays the
computer bids, then puts the user's question on the stage. It only talks to the server after the user acts; nothing
polls, because nothing happens while the user thinks.

**Proposal.**

- **Room setting:** Teams = pick / draft / **auction**. Pool, as in the one-player auction:
  - a real league season (IPL etc.): each player chooses a franchise, the other franchises are computer bidders;
    retentions from the season before (optional);
  - or player-pool years (as the draft): each player names a team, plus 2 / 4 / 6 computer teams (or none: just
    the two of you bidding against each other).
  - Mega auction only (a mini auction needs last season's bought squads; can come later).
- **Engine:** `Auction(users=[a, b])`. Everything that is "the user's" becomes per user: wishlist, skips
  ("computer bids for me to the end of the set / auction"), retention / nomination questions, planner, advice.
  Questions are asked of both at once where both have one (retentions, the accelerated round's names, a bid when
  neither of you leads). The generator gets the first answer to arrive and asks again whoever is still to answer.
- **Bidding between two people:** both are asked at each price while neither leads. If both raise their paddle at
  the same price, **the first press wins** the bid, and the other is asked at the next step right away (as in a
  real auction room). Pass = out of this player. Computer bidders join in at each step as now.
- **Room screen:** the existing auction room, each device seeing its own team, purse, wishlist, advice and
  planner; the other player's team appears as a rival paddle on the strip (their colours), their wishlist and
  advice are never shown. The room polls every second during the auction, so the other player's bids show up
  live. "Waiting for <name>..." when the other person holds the lot up.
- **Clock:** with the room's shot clock on, 15 s per bid decision (out of time = pass) and 60 s for retentions /
  names (out of time = the computer's suggestion). Clock off: a player away for 60 s can be handed to the
  computer by the other, as in matches and the draft.
- **After the auction:** the room settings choose either a **league** (real season: its fixtures, home grounds and
  playoffs; years pool: single round robin + final / semis, as the draft league) or a **series between the two of
  you** (1 / 3 / 5 with your bought squads). Matches between the two players are two-player matches; a match
  against a computer team is played by that player while the other watches.
- **Results:** the report card (both players' teams marked), squads with prices on the results page, head-to-head
  record and titles in the room. Rematch: "Back to the room" -> play the same squads again, or the host starts a
  new auction.
- **Tests:** engine with two scripted users (both asked at once, first press wins, pass, skips per user, RTM
  between a person and a computer team and between the two people, nothing about one user leaked to the other);
  a server room through auction -> series and auction -> league; the existing one-player auction tests unchanged.

**Effort:** medium-large. Most of the work is in `engine/auction.py` (one user -> several) and the auction room
(per-seat view, polling, the rival's paddle). The match side is already done (draft league / series).

**Decisions for the user:**
1. Pools: real league season, player-pool years, or both?
2. Both raise at the same price: first press wins (proposed), or a random one of the two?
3. After the auction: league, series between the two, or a choice of both (proposed)?
4. Per-user wishlist and "bid for me" skips: keep them (proposed), or plain live bidding only?

**Decisions (user, 2026-11-08):** all as proposed: 1. both pools (real league season and player-pool years);
2. first press wins; 3. the host chooses league or series between the two; 4. each player keeps a wishlist and
"bid for me" skips.

**Build log (2026-11-08):**

- **Engine** (`engine/auction.py`): `Auction(..., users=[a, b])`. The flow now yields `{user: question}` for everyone
  asked at that moment and is resumed with `(user, answer)`; `act(answer, user=)`, `auto(scope, user=)`,
  `set_wish(..., user=)`, `to_you(user)`, `state(viewer)`. Wishlists, skips and set pauses are per user
  (`wishes`, `autos`, `pauses`). Retentions / releases, the set pause and the accelerated round's names are asked of
  both at once (`_ask_all`); a bid is asked of every person not leading at once and the first answer counts; Right
  to Match questions go to one person at a time (`_ask_one`). Each question carries a number (`seq`, kept while the
  question is unchanged); an answer that names an old one is refused ("Too late: the bidding has moved on"), so a
  paddle pressed after the other player's bid does not bid at the new price. The one-player API is unchanged
  (`user`, `question`, `user_auto`, `wish`, `pause_sets` map to the single user): a seeded one-player auction gives
  the same sales as before. The report card is worked out once the auction is over.
- **Server** (`web_ui.py`): room setting Teams = "auction" with `a_pool` (season | years; a real season by default),
  `league`, `season`, `retain`, `after` (league | series), plus the draft's years / pool / computer teams for a years
  pool. Both ready -> `_mp_auction_start` (franchises must differ; named teams for a years pool).
  `/api/mp/state` phase "auction": that seat's view (`state(viewer)`, its advice, lot changes), a version number
  (`v`; a poll that sends the version it has gets `{same: true}`), seconds left per player with a clock.
  `GET /api/mp/auction/pool`, `POST /api/mp/auction` (answer with seq / auto / wish / pause / take / ready / redo).
  Clock on: 15 s per bid (then a pass), 60 s for other questions (then the computer's choice). After the auction
  `_mp_auction_play`: league (real season: double round robin, home grounds, IPL playoffs; years: single round robin +
  final / semis) or the room's single match / best of 3 / 5 between the two squads. `_mp_controllers` is shared with
  the pick / draft start. A guest leaving drops the auction; "Back to the room" returns to the finished auction.
- **Room screen:** the one-player auction room, fed by the poll (`mpAuction`, `mpAuctionBar` in
  `webui/multiplayer.js`; `auAct` / `setWish` / `setPause` go to the room's endpoint). The other player's team is
  marked RIVAL on the strip (dashed amber) and named in the title and report card. While the other player decides,
  the lot stays on the stage with the bids so far ("Waiting for Mumbai Indians to decide..."). A question still open
  keeps its screen when the other player moves (ticked retentions survive), and a top bid being typed in the
  wishlist is not redrawn. "Ready to play" / "New auction" (host) / "Let the computer bid for X (away)" / Leave in the
  top bar. Lobby: franchise chooser for a real season, the auction settings for the host, the room line names the
  season's conditions.
- **Tests:** `tests/test_auction.py` `test_two_users` (asked at once, first answer counts, stale press refused,
  private wishlist / planner, per-person skips) and `test_two_users_random` (random answers in random order, season
  and years pools, seeded runs reproduce); `tests/test_multiplayer.py` `test_server_auction_then_series` (years pool:
  live race over HTTP, version polls, private wishlist, auto, ready, best of 3 with bought players only, rematch,
  new auction) and `test_server_auction_real_season_league` (IPL 2025: same-franchise check, retentions for both, an
  away player handed to the computer, 94-match season). All suites pass.
- **Checked in the browser** (port 5071, two tabs): IPL 2026, Punjab Kings v Mumbai Indians with retentions:
  retentions on both screens (ticks kept while the other confirmed), both asked about N Pooran, the guest's bid
  first and the host asked at the next price, RIVAL / LEAD on the strip, both handed to the computer, report,
  Ready on both, best of 3 (MI won 2-0), results with the auction squads, back to the room, New auction -> lobby
  with the record; the room at phone width (375 px, no sideways scroll).
- **Fixed during the check:** an unchanged poll left out who was ready (the screen stopped updating); the auction
  poll now keeps going if drawing fails.
