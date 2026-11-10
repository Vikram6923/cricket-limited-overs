'use strict';
/* First-visit tips for every screen (the captained match has its own, in captain.js: coachBall / coachBowler).
   Each screen has 2-4 tips, one at a time, next to what they name, drawn by coachShow (captain.js). A tip counts as
   seen on "Got it" or when the person taps the thing it points at. Each browser remembers what it has seen in
   localStorage (lo.tip.<screen> = the seen tips), so on the hosted site every friend's phone or laptop gets them
   once. "Skip tips" turns all of them off (lo.tips.off); "Show tips again" (home, and More in a match) resets them. */
const TIPS_OFF = 'lo.tips.off', TIP_KEY = 'lo.tip.';
const TOURS = {
  home: [
    {sel: '#hero .qh-vs', text: 'Tap a team to change it. You captain the one on the left.'},
    {sel: '#h-play', text: 'Play starts a match you captain, ball by ball. The computer handles the rest.'},
    {sel: '#home-doors', text: 'Play a friend, run a season or a career, hold an auction or a draft: all in here.'},
    {sel: '#tabbar, #nav', text: 'Your results, saved runs and own teams live here.'}],
  pre: [
    {sel: '#pre-len', text: 'Key moments: you play the big overs and the rest sims quickly. Every ball: you play it all.'},
    {sel: '#pre-xi', text: 'We pick a sensible XI. Tap here to choose your own after the toss.'},
    {sel: '#pre-b', text: 'Call the toss to start the match.'}],
  setup: [
    {sel: '#v-setup .form.on details.how', text: 'New to this mode? How it works explains it in three lines.'},
    {sel: '#go-btn', text: 'The defaults are fine. Press Start when you are ready.'},
    {sel: '#v-setup .form.on details.more, #more-cond', text: 'Rarer settings are folded away under More options.'}],
  mp: [
    {sel: '#mp-split', text: 'Host makes a room and gives you a 4-letter code. Join if a friend sent you one.'},
    {sel: '#mp-host-pane .fg', text: 'Pick a team each, or draft or auction your squads against each other.'},
    {sel: '#mp-join-pane .mp-joinbox', text: 'Type the code from your friend’s screen and your name.'}],
  room: [
    {sel: '#mp-links', text: 'Send your friend this code or link. They join from the Two players screen.'},
    {sel: '#mp-seats', text: 'One seat each. The other fills when your friend joins.'},
    {sel: '#mp-mine', text: 'Choose your side, then tap I’m ready. The match starts when you both are.'}],
  draft: [
    {sel: '#dr-turn', text: 'Teams pick in turn, then back the other way. This shows whose pick it is.'},
    {sel: '#dr-sugs', text: 'Players who fill gaps in your squad. Tap one to draft him.'},
    {sel: '#dp-table', text: 'Or search the whole pool and tap a player when it is your pick.'},
    {sel: '#dr-auto', text: 'In a hurry? The computer can pick for you, once or for the rest of the draft.'}],
  auction: [
    {sel: '#au-q', text: 'The player under the hammer. Bid or Pass, or set a limit and Auto-bid.'},
    {sel: '#au-strip', text: 'Every team’s purse and squad size. You need a full squad, so keep money back.'},
    {sel: '#au-mode', text: 'Short on time? Let the computer bid for you, for this set or to the end.'},
    {sel: '#au-tabs', text: 'Your squad, your wishlist, every player and past sales are in these tabs.'}],
  results: [
    {sel: '#r-tabs', text: 'Every match’s scorecard, the batting and bowling tables and the best players.'},
    {sel: '#r-save', text: 'The next run replaces this one. Save it to keep it.'}],
  career: [
    {sel: '#kc-next', text: 'What comes next for your franchise, an auction or a season. Carry on from here.'},
    {sel: '#kc-news', text: 'Who retired, who arrived and who changed teams since last season.'}],
  builder: [
    {sel: '#bp-table', text: 'Tap players to add them to your team. You need 11 to 15.'},
    {sel: '#b-save', text: 'Name it and save. It then shows up wherever you pick a team.'}]};

function tipsOff() { return lsGet(TIPS_OFF) === '1'; }
function tipsSkip() { lsSet(TIPS_OFF, '1'); lsSet(COACH_KEY, '9'); lsSet(COACH_KEY + '.b', '1'); }
function tipsReset() {
  lsSet(TIPS_OFF, ''); lsSet(COACH_KEY, '0'); lsSet(COACH_KEY + '.b', '');
  Object.keys(TOURS).forEach(k => lsSet(TIP_KEY + k, ''));
}
const tipSeen = k => new Set((lsGet(TIP_KEY + k) || '').split(',').filter(Boolean).map(Number));
function tipMark(k, i) { const s = tipSeen(k); s.add(i); lsSet(TIP_KEY + k, [...s].join(',')); }
/* the first visible match of a selector list (the top nav on a laptop, the tab bar on a phone) */
const tipTarget = sel => [...document.querySelectorAll(sel)].find(el => el.offsetParent && el.getClientRects().length);

/* which screen's tips: the setup screen's depend on the mode */
function tourFor(view) {
  if (view === 'v-setup') return MODE === 'mp' ? 'mp' : ['saved', 'career', 'builder'].includes(MODE) ? null : 'setup';
  // the rooms' tips are for someone picking or bidding, not for a finished room or one the computer runs alone
  if (view === 'v-draft' && !(typeof DRAFT !== 'undefined' && DRAFT && DRAFT.user && !DRAFT.done)) return null;
  if (view === 'v-auction' && !(typeof AU !== 'undefined' && AU && AU.user && !AU.done && !['retain', 'release'].includes(AU.phase))) return null;
  return {'v-home': 'home', 'v-pre': 'pre', 'v-mp': 'room', 'v-draft': 'draft', 'v-auction': 'auction',
    'v-results': 'results', 'v-career': 'career', 'v-builder': 'builder'}[view] || null;
}
/* the next unseen tip of this screen whose target is on screen now (a hidden one waits for another visit) */
function tipTour(view) {
  if (tipsOff() || COACH.cur || $('bsheet').classList.contains('on') || document.body.dataset.view !== view) return;
  const k = tourFor(view), tour = k && TOURS[k];
  if (!tour) return;
  const seen = tipSeen(k);
  for (let i = 0; i < tour.length; i++) {
    if (seen.has(i)) continue;
    const el = tipTarget(tour[i].sel);
    if (!el) continue;
    const r = el.getBoundingClientRect();
    if (r.bottom < 0 || r.top > innerHeight) el.scrollIntoView({block: 'center'});
    coachShow(el, tour[i].text, () => tipMark(k, i), () => tipSoon(view, false, 150));
    COACH.cur.tour = k;
    // tapping what the tip points at counts as seen; the next tip follows once the screen has settled
    el.addEventListener('click', () => { if (COACH.cur && COACH.cur.t === el) { coachHide(true); tipSoon(view, false, 600); } }, {once: true, capture: true});
    return;
  }
}
/* called by showView: a new screen (or a new mode on the setup screen) hides the old one's tip; the tip waits for
   the screen to draw. Rooms redraw (and call showView) on every poll, so a pending tip is not pushed back by them. */
let TIP_T = 0, TIP_V = '';
function tipSoon(view, changed, ms = 450) {
  const k = tourFor(view), key = view + ':' + k;
  if (COACH.cur && (changed || (COACH.cur.tour && COACH.cur.tour !== k))) coachHide(false);
  if (TIP_T && TIP_V === key && !changed) return;
  clearTimeout(TIP_T); TIP_V = key;
  TIP_T = setTimeout(() => { TIP_T = 0; tipTour(view); }, ms);
}

document.addEventListener('DOMContentLoaded', () => {
  $('tips-again').onclick = () => { tipsReset(); toast('Tips are back on.'); tipSoon(document.body.dataset.view, true, 100); };
});
