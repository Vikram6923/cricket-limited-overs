# UI redesign: problems and plan (2026-11-08)

Proposal only, nothing built yet. A fresh look at the browser UI after a first-time viewer called it "terrible".
Screens were captured at 1440x900 and at phone width (390x844) from the real app.

## 1. What's wrong now

### First impression (home page)
1. **Nothing on screen says "cricket game".** No imagery, no team colours, no live element: a dark admin panel
   with grey boxes of text. The first sentence is an instruction ("Pick a mode on the left, then press Start").
2. **Eleven modes as small equal buttons in a 2-column grid** in the sidebar. Nothing stands out, no grouping
   (play now / long-term games / tools), and "Team Builder" and "Saved runs" look as important as "Career".
3. The home page repeats the sidebar as six text cards that are **not clickable**.
4. Title is long and generic ("Limited-Overs Cricket Simulator"); no logo or name with personality.

### Setting up a run (sidebar forms)
5. **Everything lives in a 370 px sidebar** under the mode grid: the form starts below the fold, and long
   modes (League, Auction, Career) are a long scroll of selects.
6. **Walls of help text.** The League hint is 9 lines; Auction, Career, Classic and Two players are similar. Users
   read none of it; the useful parts (what you'll get) should be visual.
7. Everything has the same weight: an uppercase grey label + full-width select, repeated 10-15 times. Advanced
   options (seed, ratings mode, opponent level, rain) sit at the same level as the important ones (teams).
8. Team rosters are shown as comma lists of initials ("RG Sharma, V Kohli, SA Yadav...").
9. The Start button is at the very bottom of the sidebar, often off screen.

### Results
10. **Scorecards are monospace text dumps** (`<pre>`), the most-viewed thing in any cricket product. The innings log
    runs off the right edge and is cut off.
11. **Team names carry the year everywhere** ("Punjab Kings 2026" x 40 on one page), which makes every list wrap.
12. No team identity: no colours, short codes or badges outside the auction room (which already has colours for
    franchises).
13. Match tab order is upside down for a viewer: a "Your calls" decision table comes before the charts and the
    scorecard. **Bug:** that table's sticky header floats over the charts when you scroll (see screenshot 08).
14. Top performers / records are numbered lists of small text; no player cards, no highlight of the best number.
15. Tournaments show a points table but no **form guide** (W/L dots), no **knockout bracket**.

### Live captain / ball-by-ball screen (the "game" part)
16. It looks like a form, not a match broadcast: small score, the batting card and bowling card as plain tables,
    aggression bars are tiny (about 12 px wide), and the field highlight is below the fold.
17. The title wraps to two lines ("Lucknow Super Giants 2026 v Chennai Super Kings 2026 - you captain ...").
18. Controls ("Leave to the computer", "Skip ahead") have the same weight as the main action.

### Phone / tablet
19. **The phone layout is broken**: the header wraps into 3-line columns ("View / last / results"), the mode grid
    takes half the screen and pushes the content down, the captain screen title fills the whole first screen.
    Two-player mode is meant for a second device (often a phone), so this matters.

### General
20. One accent colour (green) for everything: selected, success, primary, progress. No hierarchy.
21. System font at 14 px, tight spacing, emoji as icons.
22. No motion: results and balls appear instantly; no sense of a match unfolding except in the highlight panel.

## 2. What good looks like (research)

- **Live score apps** (Cricbuzz/ESPNcricinfo-style, and the scorer apps nxCricket, ScoreBee, Stumps) lead with the
  score bug, current batters and bowler, this over as ball chips, then tabs for scorecard / commentary / charts
  (worm, Manhattan, wagon wheel). Status labels (LIVE, Innings break, Result) at a glance; mobile first; show the
  few numbers people ask for, hide the rest behind a tap.
- **Management games**: Cricket Captain 2025 sold its redesign on a "clean-look interface" with bigger match-screen
  buttons and score; Football Manager 26's big redesign was criticised as "boxy" and FM27 moved navigation to top
  menus and put more information into each tile. Lesson: keep the data density power users like, but give each
  screen one clear focal point and a top-level navigation.
- Sports UI concepts use dark, high-contrast styling with strong typography and **team colours** as the main
  accent.

Sources: Cricket Captain 2025 Steam page (store.steampowered.com/app/3637540) and App Store notes
(apps.apple.com/app/id6747941136); FM26 UI feature article (footballmanager.com/fm26/features/fm26s-reimagined-user-interface)
and FM27 report (simulationdaily.com/news/football-manager-27-expanded-ui); scorer apps nxCricket, ScoreBee,
Stumps (App Store listings); resident.com article on live score usability (2026-09-19).

## 3. Proposed redesign

Constraints kept: plain Flask + vanilla JS, **works offline** (no CDN fonts or scripts: any font is vendored into
`webui/`), same API, every existing feature reachable. Data-dense tables stay; they get better presentation.

### A. Foundation (look and feel)
- New design tokens: layered dark surfaces, one brand accent + semantic colours (win / loss / live / wicket /
  boundary), larger type scale, more spacing, rounded cards with subtle borders and shadows.
- A vendored display font for scores and headings (tabular numbers), system font for body.
- **Team identity everywhere**: colour + 3-letter code badge for every nation and franchise (extend the auction
  room's colour table to all sides); drop the year from team names except where two eras meet (Classic modes).
- Small SVG icon set instead of emoji.

### B. Home and navigation
- Top bar with a name/logo, nav (Play / Results / Teams / Saved), status chip.
- Home = a **launcher**: a hero ("Play a match now": two team badges + one button, sensible defaults) and mode
  tiles grouped as *Quick play* (Match, Two players, Tournament), *Seasons and careers* (League season, Career,
  Auction, Draft), *History* (Classic series, Classic tournament), *Tools* (Team builder, Saved runs). Tiles
  clickable, each with an illustration/icon and one line.
- Recent runs strip (last results, saved runs, careers) on home.

### C. Setup screens
- A mode opens a **full-width setup page** (not the sidebar): the main choice large (team pickers as badge cards
  with key players and a team strength bar), conditions in a compact row, advanced options folded away.
- One sentence of help per mode; details behind an (i).
- Sticky Start button.

### D. Match centre (results Matches tab and live screen share it)
- **Score hero**: both teams with colours, big scores, overs, result line or live status, required rate, win
  probability bar.
- Sub-tabs: Summary (report, POM card, key moments) / **Scorecard (real HTML tables, highlighted top
  scorer/best bowler, FoW as a strip)** / Commentary (ball-by-ball with coloured chips for 4, 6, W) / Charts
  (worm, Manhattan, win probability, partnerships) / Your calls.
- Fix the floating sticky header bug.

### E. Live captaincy / ball by ball
- Broadcast layout: score bug across the top, the highlight field large in the centre, batters and bowler as
  player cards on either side, this over as ball chips, and big, touchable aggression bars (1-9) with keyboard
  hints. Secondary controls in a collapsible drawer.
- Short animations: ball chip pops in, score ticks up, boundary/wicket flash.

### F. Tournament results
- Points table with badges, form guide dots, NRR, qualification line; **knockout bracket** graphic; top
  performers as player cards (photo-less: initials avatar in team colour); records as stat tiles.

### G. Phone layout
- Single column, bottom tab bar, sticky score bug, setup as stacked steps. Two-player mode tested on a phone.

### Suggested order (each step usable on its own)
1. Foundation + team identity (A)  - every page improves at once.
2. Match centre + scorecard tables (D) - the screen people look at most.
3. Home launcher + full-page setup (B, C).
4. Live ball-by-ball screen (E).
5. Tournament results (F) and phone layout (G) - G partly comes with each step.

Before building: a clickable **mockup** of the home page and match centre (as was done for the auction room and
the highlights) to agree the look.

Mockup (2026-11-08): `docs/mockups/ui_redesign.html`, open it straight from disk. Four screens: Home, League
setup, Live ball by ball (replays the real last over of the PBKS v RR 2026 game from results/last; Space or
"Next ball"), Match centre (Summary / Scorecard / Ball by ball / Charts from the same match). Purple boxes are design
notes (toggle at top right). Awaiting the user's verdict.

## 4. Build log (2026-11-08, user: "Yes, build it" after the mockup)

Built across the whole browser UI; no server or engine change, every form element and ID kept so existing logic
(captaincy, auction, career, draft, two players) runs unchanged.

- `webui/teams.js` (new): colours and short codes for nations and franchises (franchise table kept in step with
  `auction_room.js`), badges, initials avatars, display names that drop the words every team in a run shares
  ("Punjab Kings" instead of "Punjab Kings 2026"; classic eras keep their years).
- `index.html`: top bar with navigation (Play / Results / Saved / Careers / Teams) and a phone tab bar; the old
  sidebar became a full-page setup view (`v-setup`: mode header, the form in a card, format and conditions on the
  right, sticky Start bar repeating the form's summary line); long help text folded into "How it works"; the team
  builder's name / saved-teams form moved into the builder view; ball by ball added to the captaincy choices for
  series / tournaments / classic / draft.
- `app.js`: Home launcher (quick match hero driving the series form: two team selects, T20/ODI, captain + ball by
  ball toggles; "Jump back in" cards for the last run, a career and saved runs; grouped mode tiles); card / chip
  pickers that drive the existing hidden selects (league, season, team to captain, career franchise); results header,
  series scoreboard, champion banner, points table with badges and a last-5 form guide, knockout bracket, player
  cards for top performers; match centre with score hero and sub-tabs Summary (player of the match, report, key
  moments timeline, win probability, top performers) / Scorecard (HTML tables, fall-of-wickets strip, super overs) /
  Ball by ball (over chips with events; the old text log folded at the bottom) / Charts (team colours, kept apart
  when two kits clash) / Your calls. Fixed the old sticky table header floating over the charts.
- `captain.js`: broadcast score bar (team colours, equation, two-colour win-probability bar), batter and bowler
  cards, recent overs as ball chips, full scorecard folded; ball question with this-over chips, bigger 1-9 bars
  (blue to red), big Next ball button.
- `style.css`: rewritten design tokens and layout (Bahnschrift / condensed system fonts for numbers, no web fonts);
  auction, career and two-player sections kept and re-themed through the tokens; tablet and phone layouts.
- Checked headless at 1440x900 and 390x844: home, every setup page, series and tournament results, match centre
  tabs, live captaincy (toss, ball by ball), draft room, auction room, running screen; no script errors.
