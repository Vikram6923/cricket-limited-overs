# Limited-overs cricket simulator (ODI + T20)

A ball-by-ball simulator for **One-Day Internationals (50 overs)** and **Twenty20 (20 overs)**, with players rated
from real ball-by-ball data. Pick any XIs from about 8,900 rated players (internationals since ~2002, ODI players back
to 1971, eleven franchise leagues and India's Syed Mushtaq Ali Trophy). Play them in any era's conditions and get a
full scorecard, a match report, charts (run worm, Manhattan, win probability, partnerships) and a player of the
match. Rain with DLS targets and the IPL Impact Player rule are modelled.

The engine is a plain Python library: no prompts, no global state, and a seed makes every match reproducible. It
is checked against reality by replaying ~1,500 real matches with their real line-ups (see
[Does it look like real cricket?](#does-it-look-like-real-cricket)).

This project grew out of **Jamie's ([Jamee999](https://github.com/Jamee999)) Test-match cricket simulator,
[github.com/Jamee999/cricket](https://github.com/Jamee999/cricket)**. Its match engine was the template for this one,
and its historical, draft and league modes inspired the modes here. See [Credits](#data-credits-and-licences).

> **Status:** the data pipeline, player ratings, match engine (calibrated), series/tournament runners and a
> browser UI with historical teams, league seasons, a fantasy draft, rain/DLS and the Impact Player rule are built.
> See [Roadmap](#roadmap).

## Quick start

Python 3.10+.

```bash
pip install -r requirements.txt
```

### In the browser

```bash
python web_ui.py
```

This opens **http://localhost:5070** (use `--port` to change it, `--no-browser` to not open a tab). It works
offline. By default only this computer can open it. To play from another device on the same Wi-Fi, start it with
`python web_ui.py --lan`: it prints the address to use (e.g. `http://192.168.1.23:5070`). Windows Firewall must allow
Python on that network. There is no login, so anyone on the same network can use it; don't use `--lan` on public
Wi-Fi.

The page opens on a home screen with one way in: two team badges (tap one to pick a nation, a franchise or your
own team), T20 / ODI and **Play**. Play means you captain the left team, ball by ball: a pre-match card shows the
suggested XI (Change XI lets you pick it after the toss), the match length and you call the toss; if you win you
choose to bat or bowl. **Key moments** (the default, about 5 minutes for a T20) has you play the first over, the
6 balls after each wicket and the last 3 overs of each innings, and the rest plays on with a one-line summary over
the field ("Wicket · 0.6–10.2: 85/1 · Jaiswal 43*, Kohli 0*"); **Every ball** plays them all. You set the bars
each ball you play and pick the bowler for those overs; the computer picks the XI, the next batter and the
Impact Player. In your first match four short tips point at the bars, *Next ball*, *Sim over* and *More* (one more
on the first bowler sheet). Every other screen has first-visit tips too, 2–4 each, one at a time next to what they
name: home (the teams, Play, the four doors, the tab bar), the pre-match card (length, XI, toss), setup screens
(How it works, Start, More options), Two players (Host / Join, then the code, the seats and I'm ready in the room),
the draft room (whose pick, suggestions, the pool, Auto-pick), the auction room while you bid (the stage, purses,
letting the computer bid, the tabs), results (the tabs, Save this run), the career dashboard and the team builder.
A tip goes on *Got it* or when you tap what it points at; *Skip tips* turns them all off. Each browser remembers
the tips it has seen (in its own storage, not by IP address or account), so on a hosted site every friend's phone
or laptop gets them once; *Show tips again* (home page, or *More* in a match) brings them all back. *Just simulate
the result* plays the match without you. Under it, a Continue row shows the one
thing in progress (a live match you left, or a career), and four doors lead to everything else: Play a friend,
Seasons & careers, Auction & draft, and a What-if sandbox (match or series, tournaments, classic sides, team
builder). Full stats also shows the old grid of every mode. Teams carry their colours and short codes everywhere;
results fit the run: a single match opens on its match centre, a series on a scoreboard (records and *Best players*
from 3 matches up), a tournament on a champion banner, points table with a form guide, and a knockout bracket.
Each match has a match centre (summary, HTML scorecard, ball by ball, charts) whose summary leads with the player
of the match, four stat tiles and the win-probability chart, then two sentences of the report (*Read more*) and a
key-moments timeline (OUT, 50, big over, turning point; partnerships and new batters in Full stats). The result
is the headline, with the format and conditions under it; the replay code sits behind *Run details* (i) in Full
stats. The live screen is built for a
phone first: a TV-style score bug with the win bar, the field where every ball plays, this over and one line for
each batter and the bowler, your striker's bars, and *Next ball*, *Sim over* and *More* at the bottom, all on one
screen without scrolling (on a desktop the field sits on the left). Who bowls, who goes in next, the Impact Player
and the result open as sheets over it, with the suggestion first; *More* holds Sim to the next wicket / end of the
innings / end of the match, the length (Key moments / Every ball), the highlights level, *My decisions*, the full
scorecard, Show tips again and Stop. The rest of the site
also works on a phone, with a tab bar at the bottom. A **Simple / Full stats** switch in the top bar
decides how much you see: Simple (the default) keeps the screens to scores, names and plain words; Full stats adds
the model's numbers (expected economy and strike rate, how settled a batter is, the replay code, the MVP formula).
Each setup screen shows at most four choices (the teams, how many matches as 1 / 3 / 5 / 7 chips, a tournament's
format as named presets, and which side you captain); the format, *Era & grounds*, venues, rain, the replay code
and the decisions you make yourself are under **More options**, which remembers whether you left it open. The
format and *Era & grounds* follow the teams you pick (two ODI sides play ODI conditions, two IPL franchises IPL
conditions in their own year) until you change them yourself; venues are a tick list you can search, so they work
on a phone too. Modes:

- **Match / Series:** two saved teams play one match or a series of up to 7.
- **Two players:** you against a friend on another device on the same Wi-Fi (the host runs `python web_ui.py --lan`).
  The mode opens on two buttons, *Host a game* and *Join with a code*. The host chooses how you get teams (pick a
  team each, draft or auction) and how many matches, and opens a room; the room shows its 4-letter code big, with
  *Copy link* and *Share*. Your friend opens the link and types a name, or taps *Join with a code* and types the
  code and a name; names show on the seats. Each player picks their own team (a saved team or a nation from any era) and the decisions they make, then
  both press Ready. Each captains a side: toss, XI, bowlers, next batter, and ball by ball the aggression bars, the
  batting side for its batters and the fielding side for its bowler, both choosing at once; after each ball both
  see what the other chose. Either player can skip to the end of the innings or match (the computer plays their
  side at normal bars) and take their decisions back later. Optional time per ball (10 or 20 seconds). If a
  player loses contact for a minute the other can hand that side to the computer; reopening the page rejoins.
  A third device that joins watches the score. Play a single match or a best of 3 / 5 series (it stops once
  decided, with a result screen for both players between matches); the room keeps a head-to-head record across
  rematches. Or **draft squads against each other**: the host sets the player-pool years, you take turns in a
  snake draft (15 players each, each on your own device), then play your squads - as a match / series, or with
  2, 4 or 6 computer teams drafting too, as a league with a final or semi-finals. Or **buy squads at an auction**:
  a real league season (each of you takes a franchise, the computer runs the others, optional retentions and
  Right to Match) or players from a span of years (with 0, 2, 4 or 6 computer teams); you both bid live, each on
  your own device with your own wishlist, advice and "bid for me" skips; when you both raise at the same price the
  first paddle up wins the bid. Then the host's choice: the league with the computer teams (a real season: double
  round robin and playoffs) or a match / series between the two of you. Design: `docs/multiplayer_design.md`.
- **Tournament:** pick teams; single or double round robin, one league or two groups, then semi-finals, IPL-style
  playoffs, a final or none.
- **Home grounds (Tournament, Classic Tournament, League Season):** each side plays half its league games at its
  primary home ground: a nation's most-used ground in its home series (Eden Gardens for India's T20s, the SCG for
  Australia), a franchise's most-used ground that season (Wankhede, Chepauk, ...). The ground brings its own
  conditions (high or low scoring, pace or spin); there is no home advantage beyond that. Knockouts and sides
  without a home (draft teams) use the chosen venues or neutral conditions.
- **Classic Series / Classic Tournament:** a nation over a range of years (ODIs from 1971, T20Is from 2005), e.g.
  Australia 2003-07 v India 2021-24. The squad is the period's 20 most-capped players (15 / 25 / everyone also
  offered), rated on those years, and batting where they batted then. Ratings for those years are either blended
  with the player's career (default; the most accurate) or based on those years only (closer to what he did then,
  noisier).
- **League Season:** any season of eleven franchise leagues (IPL 2008-26, BBL, PSL, CPL, SA20, ILT20, BPL, LPL,
  MLC, T20 Blast, Super Smash) with the real squads (everyone who played for each franchise that season), that
  season's overseas limit (taken from the real XIs: IPL 4, BBL 3, ...), a double round robin and IPL-style
  playoffs. IPL games from 2023 use the Impact Player rule.
- **Mushtaq Ali Trophy** (Seasons & careers): India's domestic T20 with its 38 state sides. A real season's groups
  and format, 4 points a win, then that season's knockouts (Super League, quarter-finals or preliminary
  quarter-finals) and, from 2020-21, the Plate with promotion and relegation. Real squads for 2015-16 and 2017-18
  to 2021-22; 2025-26 uses each player's latest state in the data. Captain any state or just watch. To run one
  state for years, start a Career and pick the Mushtaq Ali Trophy (below).
- **Captain a team (every mode except Team Builder):** pick one side and make its calls in its matches while the computer
  plays everything else: the toss, the XI in batting order with the keeper (and the 5 Impact substitutes), the
  bowler for every over, the next batter at every wicket, and when to use the Impact Player. Each screen shows a
  live scorecard (score, chase, win probability, both cards, recent overs) and marks what the computer would do,
  with its Impact Player suggestion and how many runs it is worth. Any type of decision can be left to the
  computer, play can be skipped to the end of the innings, the match or the season, and obvious calls (one
  possible bowler, the last batter) are not asked. League Season and Auction pick the team in their own form; Series, Tournament, Classic and Draft (your drafted
  team) in the "Captain a team" box under the conditions. Built on a generic controller (`engine/control.py`).
  - **Ball by ball with aggression bars (League Season and Career, Cricket Captain style):** set each batter's
    aggression and each bowler's plan on 9 bars and play a ball, an over, to the next wicket or to the end of the
    innings (only the striker's bars show; a chip opens the non-striker's, and a toast says when the strike
    changes), with a settled meter for each batter (Full stats; Simple marks a new batter NEW) and the projected score or chase. Bar 5 is how real sides play
    that situation (the engine as calibrated); the bars run Block, Defend, Careful, Steady, Normal, Positive, Attack,
    Hit out, Slog. The trade-off comes from real ball-by-ball data: across match
    situations, how fours, sixes and dots move with the scoring rate, and how far each bar reaches (the range real
    sides show, plus one bar beyond it at each end). Each bar's wicket cost is set so that bar 5 is best on
    average, so the right setting depends on the moment: going hard pays when a wicket is cheap and costs when it
    is dear. See [docs/match_play_design.md](docs/match_play_design.md).
  - **Highlights:** on that screen the balls since your last pause replay as a 2D ball tracker in a field that
    is always there (every ball, fast, by default: about 0.8 s, and the full replay for a four, a six or a wicket;
    or wickets and boundaries; or off). The outcome shows big in the field (a dot, the runs, FOUR, SIX, OUT!), a
    boundary flashes the batting side's colour and a wicket shakes the field; reduced motion is respected. The
    last ball of an over plays before the bowler sheet opens. The ball's path on a top-down ground with the field, fielders chasing, runners, flying
    bails, the catcher's name, and a side-on strip for the length. The engine decides what happened; the direction,
    length and field are drawn by rules (Cricsheet records none of them), and the field follows the phase and your
    bowling plan.
  - **Opponent captains: Expert / Average / Easy.** Expert is the engine's own best calls. Weaker computer
    captains sometimes make another call (bowler, next batter, a swap in the XI, the toss, the Impact Player
    moment), the less costly ones more often, so their mistakes are plausible. Measured over 900 IPL 2024 games:
    an expert side wins 51% against Expert, 56% against Average, 66% against Easy.
  - **Captaincy report:** every call you make is valued in runs against the computer's call, with the engine's
    own numbers (bowlers: this over plus the best way to bowl the rest; batters: the order still to come and the
    balls each can expect; XI: batting by slot plus the best overs the side can bowl). The results summary shows
    the total by decision type (and in wins), each match lists the calls where you differed. Toss and Impact
    Player calls are listed without a value.
- **Fantasy Draft:** you and computer teams draft 15-man squads in snake order from the player pool of chosen
  years (full-member internationals, optionally franchise leagues), then play a league with knockouts.
- **Auction:** an IPL-style auction, then a league. Players: everyone from a real league season (with its
  franchises, conditions and home grounds) or a range of years (as in the draft, with an optional home nation for
  overseas limits). IPL rules: Rs 120 crore purse, squads of 18-25 with at most 8 overseas, players in sets
  (marquee, then capped and uncapped batters, all-rounders, keepers, fast bowlers, spinners) at base prices,
  standard bid steps, an accelerated round for the unsold. **Retentions** before the auction: up to 6 players from
  the previous season's squad (or your last auction), 5 capped at Rs 18 / 14 / 11 / 18 / 14 crore and 2 uncapped
  at 4 crore; every unused slot is a **Right to Match** card (the buyer gets one final raise, then the old team
  matches or not). Bid live for your team (bid, pass, or bid up to a limit), or let the computer bid for you to
  the end of the set or the auction; every call shows what the computer would bid and why. Computer teams value a
  player by what he adds to their best XI in runs per match (the engine's own ratings), at the market rate for the
  money left. With a real season's players they know only what could be known before it: each player's record up
  to the year before, so a debutant with no record (Suryavanshi in 2025) is valued as an unknown newcomer with a
  small scouting hint, not on the seasons he has yet to play; the matches still use his full rating. **What you
  see** (season pools): realistic (default), each player's numbers as the teams know them, or hindsight, his real
  career numbers; either way an amber *unknown* / *little seen* tag marks a player the teams have barely seen play.
  Then the squads play a league, and you can captain your team.
- **Career:** a franchise league season after season, from a real season's squads (any of the 11 leagues). You
  run one franchise (or watch). Between seasons players age (age curves fitted from real careers), retire (the
  real chance at each age) or leave after going unsold twice, and draw a new season's form once the auction is
  over (no team bids knowing it); newcomers arrive: the
  players who really debuted in the league that year, then, once the real seasons run out, made-up youngsters
  copied from real debutants' rating profiles. A **mega auction** (retentions, Right to Match) every 1-5 seasons
  (3 by default, as the IPL) and **mini auctions** in between (keep players at their contract prices or release
  them). Computer teams bid, retain and release on what they can know before the season, while matches use how
  good each player really is: a player's real record before he joined the career, then what the career's own
  seasons showed of him (his matches in the league, and his cricket elsewhere drawn from his level), so a
  youngster who shines in your career gets noticed and a star who flops in it loses his value. **What you see**
  is set when the career starts: realistic (default) shows you the same in auctions, squads and the captain's
  player cards in matches; hindsight shows how good each player really is (careers saved before this setting
  keep hindsight). Play each
  season, captaining your side if you like; the career page keeps the honours (champions, your
  finish, most runs and wickets, MVP, each season's full results), the trophy count, career records across all
  seasons and every squad with ages and current ratings. Careers are kept in `results/careers/` and can be
  reopened at any time.
- **State career** (Career, league "Mushtaq Ali Trophy"): one of the 38 states season after season, from a real
  season with a Plate (2020-21, 2021-22 or 2025-26), keeping that season's format. The Plate winner goes up, the
  lowest Elite side goes down, and next season's Elite groups are dealt by finishing position. There is no auction:
  a state's squad carries over. Players age, find form and retire as in franchise career; the real 2021-22 and
  2025-26 seasons bring their debutants and the players who really changed state; seasons in between get about
  3 made-up newcomers per state (copies of real SMAT debutants, named from the state's own players) and a dozen
  uncapped players changing state. Squads stay between 16 and 22 (the least valuable players over 23 leave). The
  career page shows the season's groups, honours with who went up and down, your state's finish, squads and
  records.
- **Saved runs:** "Save this run" on the results page keeps a run (any mode) under a name in `results/saved/`,
  so the next run doesn't overwrite it; the Saved runs mode lists them to open (the full results page), rename or
  delete. A saved league (an auction league or a League Season) of the same league can be retained from in a later
  auction, so a franchise can carry its squad from one auction season to the next.
- **Team Builder:** search the ~7,800 rated players, pick 11-15 (with more than 11 the captain picks the XI for
  each match) and save the team. Ten preset national squads are included.

For every run choose the format, the year and whose conditions to play in (full-member internationals or a league),
optionally venues, a replay code (the seed) and whether rain can interrupt play (on by default). The results page has a summary
(points tables with net run rate, knockouts, top performers, records), every match (Previous / Next, match report,
rain notes, run worm, Manhattan, win-probability and partnership charts, scorecard and innings log), sortable batting and bowling tables, *Best players* (points: official and balanced) and,
after a draft or an auction, the squads (with prices). Saved teams go in `data/teams.json` (not in git).

### Hosting it for friends

`python web_ui.py --public` runs it as a website that several people can use at once. Each browser is its own
visitor (a cookie): its own simulation, draft, auction, saved teams, saved runs and careers, kept in
`results/visitors/<id>/`. Any number of two-player rooms can run at once, and the room shows the site's link to
send to the other player. Without `--public` nothing changes: one user, the folders above.

- **Password:** set `SITE_PASSWORD` and the browser asks for it once (any user name). Use one on the open internet.
- **Load:** at most `MAX_JOBS` simulations run at once (default 6); the next person is asked to try again in a
  minute. It is one Python process, so they share one CPU core: a full IPL season takes about 8 s alone, longer
  when others are running. Memory: about 300 MB.
- **Housekeeping:** a run nobody has looked at for 15 minutes is stopped, idle rooms close after 3 hours, and a
  visitor's folder is deleted 30 days after their last visit. Each visitor keeps up to 100 teams, 30 saved runs and
  10 careers.
- **One process only.** Runs in progress live in memory, so don't run several copies behind a load balancer, and
  don't use hosts that pause or multiply the app between requests (serverless platforms such as Cloud Run or
  Vercel).

It listens on `$PORT` (or `--port`) on all addresses; `--host 127.0.0.1` keeps it to this computer, for a tunnel.
It needs HTTPS in front of it (a tunnel or a proxy); it serves plain HTTP itself, with `waitress`.

**On your own server with Docker** (the `Dockerfile` and `docker-compose.yml` here):

```bash
SITE_PASSWORD='choose-one' docker compose up -d --build
```

(or put `SITE_PASSWORD=...` in a `.env` file next to `docker-compose.yml`; git ignores it). This runs it as an
unprivileged user in one container, reachable only from that computer on
`http://127.0.0.1:5070`, with a 768 MB memory cap and the visitors' folders in a Docker volume (they survive
restarts and upgrades). To put it on the internet, point a
[Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/) at
it: give it its own hostname (e.g. `cricket.example.com`), not a path under another site, because the page calls
`/api/...` from the root. In the tunnel's `config.yml`, before the final 404 rule:

```yaml
  - hostname: cricket.example.com
    service: http://localhost:5070
```

then `cloudflared tunnel route dns <tunnel> cricket.example.com` and restart cloudflared. To upgrade:
`git pull && docker compose up -d --build`.

**Without a server:** run `python web_ui.py --public --host 127.0.0.1` on your computer and
`cloudflared tunnel --url http://localhost:5070`, which prints a temporary `https://….trycloudflare.com` link. It
works while your computer is on.

**On a hosting service:** anything that runs a Dockerfile as one always-on instance with about 512 MB works,
e.g. Fly.io (a shared-cpu-1x machine with 512 MB; turn off auto-stop and run one machine: `fly deploy --ha=false`)
or Render (a paid instance: the free one has 0.1 CPU, which makes drafts and seasons slow, and sleeps when idle).
Without a volume, saved runs are lost when the service restarts.

### From Python

```python
from engine import simulate_match, scorecard_text, match_report
from engine.data import search

print(search("t20", "Kohli"))   # [('ba607b88', 'V Kohli', 'India'), ...]  (Cricsheet id, name, team)

def ids(names, fmt="t20"):
    return [next(pid for pid, name, team in search(fmt, n) if name == n) for n in names]

india = {"name": "India", "players": ids([
    "Rohit Sharma", "Shubman Gill", "V Kohli", "SA Yadav", "HH Pandya", "RR Pant",
    "RA Jadeja", "AR Patel", "Kuldeep Yadav", "JJ Bumrah", "Arshdeep Singh"])}
australia = {"name": "Australia", "players": ids([
    "TM Head", "MR Marsh", "JP Inglis", "GJ Maxwell", "MP Stoinis", "TH David",
    "MS Wade", "PJ Cummins", "MA Starc", "A Zampa", "JR Hazlewood"])}

card = simulate_match(india, australia, fmt="t20", comp="t20i_full", year=2024,
                      venue="Wankhede Stadium, Mumbai", seed=1)
print(scorecard_text(card))     # full text scorecard
print(match_report(card))       # short narrative report
```

`card` is a JSON-ready dict with batting and bowling cards, fall of wickets, partnerships, over-by-over runs and
win probability (for worm and Manhattan charts), events (milestones, wickets, big overs, hat-tricks), the turning
point, an impact score per player, the player of the match and the result.

Useful options:

| Argument | Meaning |
|---|---|
| `fmt` | `"t20"` or `"odi"` |
| `comp`, `year` | whose conditions to play in: `"t20i_full"` / `"odi_full"` (full-member internationals) or a league (`"ipl"`, `"bbl"`, `"psl"`, `"cpl"`, `"sat"`, `"ilt"`, `"bpl"`, `"lpl"`, `"mlc"`, `"ntb"`, `"ssm"`) |
| `venue` | ground name; known grounds have a fitted scoring factor |
| `seed` | makes the match reproducible |
| team `"squad": [ids]` | give 12+ players and let the captain pick a balanced XI |
| team `"order"`, `"keeper"`, `"captain"` | override the batting order, keeper and captain |
| team `"years": [2007, 2011]` | rate the players on those years (and use their batting slots of then) |
| team `"years_mode"` | `"blend"` (default: shrunk toward the career) or `"only"` (those years alone) |
| team `"overseas"`, `"max_overseas"` | league overseas players and the limit per XI (IPL 4, BBL 3) |
| `rain_on` | rain interruptions for the host country, with DLS targets (default off in the library) |
| `impact_player` | IPL Impact Player rule (default: on for IPL from 2023) |

**Picking the XI from a squad.** With more than 11 players the captain picks the XI for each match. Skill is
each player's expected runs value per match from his ratings (batting weighted by the balls his position faces,
bowling by the overs he bowls); how selectors trade that against keeping, team balance (4-6 specialist bowlers),
spin-friendly venues and experience is learned from every real full-member XI since 2003/2006
(`engine/selection.py`, `python -m engine.fit.fit_selection`). Each match the ratings are redrawn within their
uncertainty, so clear leaders always play and close calls rotate. Same seed, same XI.

**Impact Player (IPL 2023 onwards).** The engine uses the substitute *rationally* instead of copying how teams
use it (`engine/impact.py`). Every decision compares, in runs, what the side gains by using it now with what waiting
is worth. The XI is chosen after the toss with the substitute plan in mind (for example, start with an extra bowler
and bring in a batter only if wickets fall early). A batter can come in at any wicket, valued against the chance of
a later collapse taken from real innings in the same position; a bowler or all-rounder can come in at the end of
any over (often for a bowler who has bowled out); otherwise the swap is made at the innings break. The scorecard
marks the two players with ↑ in and ↓ out, and both are credited with the appearance.

**Rain and DLS.** With rain on, a match is interrupted as often as real matches in the host country are (from
Cricsheet: about a quarter of ODIs in Sri Lanka and the West Indies, a fifth in England, under a tenth in India,
Pakistan and Australia), replaying a real match's pattern: overs lost before the start, the first innings ended
early, the chase reduced, or play stopped for good. Targets and par scores use the DLS Standard Edition formulas
with a resource table in the Duckworth-Lewis form: how resources fall with overs is fitted to what a side scores in
a shortened innings, the cost of wickets to real innings. The targets come out close to the official table's (a
20-over ODI chase: 56.6% of the resources, as in the official table) and are fair: a chase revised by DLS is won about
as often as a normal one. A chase needs 20 overs (ODI) or 5 (T20) for a result. Bowler quotas shrink with the
innings; the powerplay is scaled, and the last overs are death overs however short the innings (`engine/rain.py`).

Historical teams and drafts from Python:

```python
from engine.history import historical_team
from engine.draft import Draft

aus = historical_team("odi", "Australia", 2003, 2007)    # {"name", "squad", "years"}
ind = historical_team("odi", "India", 2011, 2011)
card = simulate_match(aus, ind, fmt="odi", comp="odi_full", year=2011, seed=1)

d = Draft("t20", 2015, 2025, ["London", "Mumbai", "Sydney", "Cape Town"], user=None, seed=1)
d.run_cpu()                                              # computer drafts every team
teams = d.team_specs()                                   # ready for play_tournament
```

Teams from different eras can meet. Ratings are relative to each player's own era, so the 2007 Australians can play
the 2023 Indians under 2023 conditions, or under 2007 conditions.

## Series and tournaments

```bash
python -m engine.tournament examples/t20_world_cup_style.json --out results/wc
python -m engine.tournament examples/odi_series_india_australia.json --out results/series
```

This prints the points tables (with net run rate), knockout results, winner, player of the series and top performers.
It writes `summary.json` (tables, knockouts, batting / bowling / fielding stats, records, MVP rankings) plus
`matches/NNN.json` and `NNN.txt` (full and text scorecard) for every match. Players in the config can be given by
name or Cricsheet ID, and a 12+ player `squad` lets the captain pick the XI.

From Python:

```python
from engine.tournament import play_series, play_tournament, save
res = play_tournament(teams, fmt="t20", comp="t20i_full", year=2024,
                      groups=2, knockout="semis", seed=1)   # or knockout="ipl" / "final" / "none"
save(res, "results/my_cup")
```

- **League stage:** single or double round robin (`rounds`), optionally in groups.
- **Knockouts:** semi-finals (1v4, 2v3; with two groups A1vB2, B1vA2), IPL-style playoffs (Qualifier 1,
  Eliminator, Qualifier 2, Final), a final, or none. For India's domestic cups also `"qf"` (quarter-finals 1v8,
  4v5, 2v7, 3v6), `"pre_qf"` (the lowest seeds play preliminary quarter-finals for the last places),
  `"super_league"` (the qualifiers play two round-robin groups, the winners meet in the final) and
  `"super_league_semis"`. Qualifiers from several groups
  are seeded by group position, then points and NRR, and group-mates are kept apart where possible. `advance` can
  differ per group (a list), `win_points=4` gives India's 4 points a win, and `plate={"teams": [...]}` plays a
  second division in the same run (its own league and final; `advance` sends its top sides into the knockouts)
  and reports the promoted and relegated sides.
- **Points table:** net run rate by the ICC method (a side bowled out is charged its full quota of overs; super
  overs don't count; in a DLS match the side batting first is credited with the par score in the chase's overs;
  no-results earn a point each and are left out). With `rain=True`, knockouts get a reserve day, after which the
  higher-placed side goes through.
- **Records:** highest and lowest totals, top scores, best figures, fastest 50s and 100s, biggest and narrowest wins,
  super overs.
- **MVP rankings:**
  - *official*: win probability added; it also picks the player of the series;
  - the player of the match: the balanced score below plus win probability added converted into runs (a whole win
    is worth about 150 runs in a T20, from the chase win model), so a match-winning 70 beats a 6 off 3 balls;
  - *balanced*: runs + 25 per wicket + 5 per catch/stumping + 25 per team win, plus strike-rate and economy
    bonuses.

## How it works

1. **Data**: [Cricsheet](https://cricsheet.org) ball-by-ball files for ODIs, T20Is, eleven T20 leagues and the
   Syed Mushtaq Ali Trophy (India's domestic T20), plus Wikipedia/Wikidata for batting hand, bowling type, and career
   totals of Afghanistan players (Cricsheet withholds Afghanistan matches) and of ODI players from before Cricsheet
   (1971-2002). Pre-2002 strike rates come from
   Wikipedia's match summaries (top scorers' runs and balls in about 1,600 pre-2002 ODIs), corrected for the
   top-scorer bias measured on 2003-12 matches where Cricsheet has the truth.
2. **Ratings**: every player gets batting and bowling indexes for runs, dismissals, dots, fours and sixes, overall
   and by phase (powerplay / middle / death). They are fitted with three things:
   - **opponent adjustment**: runs against weak attacks count for less;
   - **shrinkage**: small samples are pulled toward the player's role and team, so a debut 98* doesn't make a star;
   - **era adjustment**: everyone is rated against their contemporaries.

   They are checked by predicting 2024-26 from data up to 2023.
3. **Engine**: every delivery's outcome comes from baseline × batter × bowler, adjusted by the match situation. The
   situation effects are learned from real matches, not hand-tuned:
   - settling in (new batters score slowly);
   - intent when setting a total or chasing (a DLS-style par / pressure model);
   - batting hand v bowling type;
   - venue, and the day's pitch (internationals);
   - pace v spin: each ground's edge for spinners over seamers, plus the day's (a turner one day, a green top the
     next), fitted from how spinners and seamers did against expectation in every real match since 2012.

   Captains plan the whole bowling innings from each bowler's real usage (bowling more of whichever type the pitch
   helps) and react during it: a bowler going for more than expected loses overs and a wicket-taker can be kept
   on, as much as real captains do (fitted on every over since 2015), pick XIs from squads (learned from real
   selections), choose batting orders from position history, and make toss decisions at real rates. Ties go to
   super overs. Rain, DLS and the Impact Player are described above.

Design and decisions: [`docs/engine_design.md`](docs/engine_design.md). Calibration log:
[`docs/engine_progress.md`](docs/engine_progress.md).

## Does it look like real cricket?

`python -m engine.calibrate` re-plays real matches (484 full-member T20Is 2021-26, 355 IPL games 2022-26, 732
full-member ODIs 2015-26) with the real XIs, batting orders, toss, venue and year. It then compares the simulated
results with what happened:

| First innings | Real T20I | Sim | Real IPL | Sim | Real ODI | Sim |
|---|---|---|---|---|---|---|
| Average total | 168.8 | 167.5 | 186.3 | 187.4 | 267.5 | 266.4 |
| Spread (SD) | 37.7 | 38.8 | 35.2 | 34.4 | 69.7 | 70.8 |
| Wickets | 6.74 | 6.77 | 6.28 | 6.40 | 8.08 | 8.07 |
| Powerplay / death run rate | 8.01 / 9.94 | 8.03 / 9.99 | 9.08 / 11.04 | 9.13 / 11.11 | 4.87 / 7.95 | 4.77 / 7.75 |

Known gaps: too many all-out innings (T20I 17% v 12.6%) and too few ODI hundreds (-13%). Details are in
[`docs/engine_progress.md`](docs/engine_progress.md).

## Rebuilding the data

The repository includes the derived data (ratings and fitted tables) so the engine works straight after cloning.
To rebuild everything from scratch, for example each season:

```bash
python scripts/fetch_cricsheet.py      # downloads Cricsheet zips into data/raw/ (cached; --refresh to update)
python scripts/build_raw_stats.py      # per-player raw stats with phase splits
python scripts/build_afghanistan.py    # Afghanistan players from Wikipedia (Cricsheet withholds their matches)
python scripts/fetch_styles.py         # batting hand / bowling type from Wikipedia (cached, ~10 min first time)
python scripts/build_pre2002.py        # pre-2002 ODI players' career totals from Wikipedia lists
python scripts/fetch_wiki_matches.py   # ODI match summaries (top scorers' runs and balls), cached
python scripts/build_ratings.py        # player ratings -> data/ratings_{odi,t20}.json (+ _years, _comps)
python scripts/build_league_presets.py # every season of 11 leagues (+ home grounds) -> data/league_seasons.json
python scripts/build_home_grounds.py   # national sides' home grounds -> data/home_grounds.json
python scripts/build_domestic_presets.py # Mushtaq Ali Trophy seasons -> data/domestic_seasons.json
python -m engine.fit.fit_basics        # dismissal mix, run splits, extras, free hit
python -m engine.fit.fit_situation     # settling in, intent, par, win probability, matchups
python -m engine.fit.fit_toss          # toss decisions
python -m engine.fit.fit_venues        # venue factors and pitch variation (~25 min: replays every real match)
python -m engine.fit.fit_selection     # XI selection model
python -m engine.fit.fit_impact        # Impact Player tables (balls still to come, real wicket timelines)
python -m engine.fit.fit_rain          # rain profiles by host country
python -m engine.fit.fit_dls           # DLS resources (after the other fits: it replays shortened matches)
python -m engine.fit.fit_spin          # pace v spin edge by venue and day
python -m engine.fit.fit_reactive      # reactive bowling changes
python -m engine.fit.fit_career        # career mode: age curves, season form, retirements
python -m engine.fit.fit_depth         # T20 batting depth still to come, a trend that extrapolates (after fit_situation)
python -m engine.calibrate             # compare simulated v real
python tests/test_engine.py            # laws and bookkeeping invariants
python tests/test_tournament.py        # points, net run rate, stats totals, knockout structure
python tests/test_domestic.py          # Mushtaq Ali Trophy seasons are complete and play through
python tests/test_state_career.py      # state career: promotion, relegation, squads, a season through the server
python tests/test_selection.py         # also test_history.py, test_draft.py
```

Optional checks: `python scripts/validate_ratings.py` (out-of-sample test of the ratings) and
`python scripts/verify_players.py` (raw stats v Wikipedia career figures).

## Project layout

```
engine/            match engine (library)
  match.py         match / innings state machine, scorecard, super overs, win probability
  ballmodel.py     per-delivery outcome model
  captain.py       XI selection, batting order, bowling plan, toss
  situation.py     settling in, intent, par, matchups, win probability
  conditions.py    venue factor, pitch of the day
  periods.py       ratings for a year range
  selection.py     XI selection learned from real XIs
  impact.py        IPL Impact Player decisions
  rain.py          rain interruptions and DLS
  control.py       manual captaincy (a person makes one side's decisions)
  judge.py         captaincy decisions valued in runs: the captaincy report and weaker computer captains
  history.py       historical (nation + years) teams
  draft.py         fantasy draft
  auction.py       IPL-style auction with retentions and Right to Match (and mini auctions)
  career.py        career mode: a league over many seasons (ageing, retirements, newcomers, auctions)
  belief.py        what teams believe a player is worth before a season (his record up to then), apart from his rating
  state_career.py  state career: a Mushtaq Ali Trophy state over many seasons (Elite, Plate, no auction)
  render.py        text scorecard and match report
  tournament.py    series and tournaments: points tables, NRR, knockouts, stats, records, MVP
  calibrate.py     replay real matches and compare
  fit/             scripts that learn the engine's tables from Cricsheet
web_ui.py          Flask server for the browser UI
webui/             the page: index.html, style.css, app.js, teams.js (team colours, badges), one script per room
                   (captain, auction, career, two players); no external scripts or fonts
scripts/           data pipeline: download, raw stats, Afghanistan, pre-2002 players, styles, ratings,
                   league presets, validation
data/              ratings_*.json (+ ratings_*_years.json for year ranges), engine/*.json (fitted tables), raw_stats/ (derived),
                   teams_default.json (preset squads);
                   raw/ and cache/ are rebuilt locally and not in git
docs/              design document and calibration/progress log
examples/          tournament and series configs
tests/             engine and tournament tests
```

## Roadmap

- [x] Data pipeline, raw stats with phase splits, verification against real careers
- [x] Ratings with opponent adjustment, shrinkage and era adjustment
- [x] Match engine (Tier 0-2 of the design), calibrated against real matches
- [x] Series and league/tournament runners (points table with net run rate, knockouts, stats, records, MVP)
- [x] Browser UI (Flask, works offline): single match, series, World Cup / IPL-style tournaments, team builder,
      results pages with match reports, stats tables, records and MVP race
- [x] Historical teams (ratings for a year range), fantasy draft, worm / Manhattan / win-probability charts
- [x] Pre-2002 ODI players from Wikipedia career totals (ODI classic teams from 1971); strike rates from match
      summaries
- [x] League seasons (every season of 11 leagues) with overseas limits; IPL Impact Player rule
- [x] Pace v spin pitches; reactive bowling changes
- [x] Rain interruptions and DLS; partnership charts
- [x] Captain a team in any mode (toss, XI, bowlers, batters, Impact Player)
- [x] IPL-style auction with retentions and Right to Match, then a league; saved runs
- [x] Career mode: a franchise league season after season, with ageing, retirements, newcomers and auctions
- [x] State career: a Mushtaq Ali Trophy state season after season, Elite and Plate with promotion and relegation
- [x] Teams' belief apart from true rating: auctions and squad decisions use only what was known before the season;
      in a career the teams learn from its own seasons; you see what they know (realistic) or the real ratings
- [x] UI redesign: home launcher, team colours and badges, match centre with HTML scorecards, broadcast-style
      live screen, phone layout
- [x] UI simplification phase 1: Simple / Full stats switch, More options folds, plain words
- [x] UI simplification phase 2: home with one Play button (you captain, ball by ball), pre-match card and coin
      toss, Continue, four doors; a single match opens on its match centre
- [x] UI simplification phase 3: phone-first live screen (score bug, permanent field, striker's bars, action bar),
      every ball plays fast, decision sheets (bowler, next batter, Impact Player, result), XI with Use this XI
- [x] UI simplification phase 4: setup screens with at most four choices (the rest under More options), venues as
      a searchable tick list, Era & grounds from the teams; Two players opens on Host / Join, joining is code +
      name + Join, and the room shows the code big with Copy link and Share
- [x] UI simplification phase 5: results fit the run (one match: the match centre only; 2 matches: no records
      or Best players), the result as the headline with the replay code behind Run details (Full), a shorter
      match summary (tiles, win chart, 2-sentence report) and a key-moments timeline with short lines
- [x] UI simplification phase 6: Key moments match length (the engine's `until: "key"` pause plays on between
      the first over, the 6 balls after a wicket and the last 3 overs; a summary line after each stretch) and
      three coach marks in the first captained match, plus one on the bowler sheet
- [x] First-visit tips on every screen (home, pre-match, setup, Two players and the room, draft and auction rooms,
      results, career, team builder) and a fourth match tip on *More*; Skip tips turns all off, Show tips again
      (home or More) resets them, per browser
- [x] Two players on two devices (same Wi-Fi): one bats, one bowls, ball by ball; single match or best of 3 / 5;
  a draft against each other (optionally with computer teams and a league); a live auction against each other
  and the computer franchises, then a league or a series
- [ ] Later: match settings panel (overs, toss, pitch), player-v-player matchups, an international career world

## Data, credits and licences

- Ball-by-ball data: [Cricsheet](https://cricsheet.org). Cricsheet's data is made available under the Open Data
  Commons Attribution License; check cricsheet.org for the current terms. Thanks to Cricsheet for an outstanding
  free resource. Cricsheet currently withholds matches involving the Afghanistan men's team; those players are
  rated from franchise-league data and Wikipedia career totals.
- Player attributes, Afghanistan and pre-2002 career totals, and pre-2002 match summaries:
  [Wikipedia](https://en.wikipedia.org) (CC BY-SA) and [Wikidata](https://www.wikidata.org) (CC0).
- **Original simulator: Jamie ([Jamee999](https://github.com/Jamee999)),
  [Test match cricket simulator](https://github.com/Jamee999/cricket).** This project began as a limited-overs
  rebuild of that program. Its match engine (`callcricketnew.py`) was the template for `engine/`. These ideas were
  carried over and then rewritten and refitted to Cricsheet data:
  - the match, innings, over and ball flow, and the batting and bowling objects for each player
  - the dismissal mix, the extras handling and the pitch factors
  - the match report narrative and the player-of-the-match pick
  - the milestone and partnership log

  The Classic Series and Classic Tournament modes follow its `historical.py` and `historicalleague.py`. Fantasy Draft
  follows its `draft.py`, and Team Builder follows its `custom.py`. Thanks to Jamie for the original program. Jamie's
  code is not included in this repository. That repository has no licence file, so its terms are Jamie's to set.

Code licence: [MIT](LICENSE). Data keeps the licences of its sources above.

This is a fan project. It is not affiliated with the ICC, any board, league or team.
