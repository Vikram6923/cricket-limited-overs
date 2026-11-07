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
| Over the internet | Not through code: use a private network tunnel such as Tailscale between the two laptops. Opening a port to the public internet is not recommended (Flask's dev server, no login). | none |
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
  as one-match Match / Series runs always were.
