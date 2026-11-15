'use strict';
/* Home: the state every screen shares, the modes, the quick match, navigation and start-up (init). */

/* ───────────────────────── state / init ───────────────────────── */
let META = null, MODE = 'series';

/* modes: home tiles, setup header */
const ICON = {
  series: '<circle cx="12" cy="12" r="8"/><path d="M8 6c2 3 2 9 0 12M16 6c-2 3-2 9 0 12"/>',
  mp: '<rect x="3" y="5" width="8" height="13" rx="2"/><rect x="13" y="5" width="8" height="13" rx="2"/>',
  tournament: '<path d="M7 4h10v4a5 5 0 0 1-10 0z"/><path d="M12 13v4M8 20h8M7 6H4a3 3 0 0 0 3 4M17 6h3a3 3 0 0 1-3 4"/>',
  league: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18M8 2v4M16 2v4"/>',
  domestic: '<path d="M12 3l7 3v5c0 4.5-3 8-7 10-4-2-7-5.5-7-10V6z"/><path d="M9 12l2 2 4-4"/>',
  career: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
  auction: '<path d="M14 4l6 6-3 3-6-6zM11 7l-8 8 3 3 8-8M3 21h8"/>',
  draft: '<path d="M4 6h16M4 12h10M4 18h13"/>',
  classic: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  classic_t: '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
  builder: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0M17 8v6M14 11h6"/>',
  saved: '<path d="M6 3h12v18l-6-4-6 4z"/>'};
const MODES = {
  series: {t: 'Match or series', s: 'Two saved teams, one to seven matches', g: 'Quick play', c: '#2ee88a'},
  mp: {t: 'Two players', s: 'You v a friend on another device, ball by ball', g: 'Quick play', c: '#3d8bff'},
  tournament: {t: 'Tournament', s: 'Groups, points table with NRR, knockouts', g: 'Quick play', c: '#f6c453'},
  league: {t: 'League season', s: 'Any IPL, BBL, PSL… season with the real squads', g: 'Seasons and careers', c: '#f6c453', feat: true},
  domestic: {t: 'Mushtaq Ali Trophy', s: "India's 38 states: a real season's groups, format and squads", g: 'Seasons and careers', c: '#ff9f43'},
  career: {t: 'Career', s: 'Run a franchise or a state for years: ageing, auctions, trophies', g: 'Seasons and careers', c: '#b26bff', feat: true},
  auction: {t: 'Auction', s: 'Bid live with retentions and Right to Match', g: 'Seasons and careers', c: '#ff4061'},
  draft: {t: 'Fantasy draft', s: 'Snake draft from any era, then a league', g: 'Seasons and careers', c: '#39c5cf'},
  classic: {t: 'Classic series', s: 'Any nation, any era: Australia 2003–07 v India 2011', g: 'History', c: '#f6c453'},
  classic_t: {t: 'Classic tournament', s: 'Great sides from different eras', g: 'History', c: '#2ee88a'},
  builder: {t: 'Team builder', s: 'Pick 11–15 from about 6,500 rated players', g: 'Tools', c: '#3d8bff'},
  saved: {t: 'Saved', s: 'Seasons and series you kept', g: 'Tools', c: '#8d9bb5'}};
const modeIcon = (m, cls = '') => `<span class="mic ${cls}" style="--mc:${MODES[m].c}"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${ICON[m]}</svg></span>`;
function drawModeTiles() {
  const groups = {};
  Object.entries(MODES).forEach(([k, m]) => (groups[m.g] = groups[m.g] || []).push(k));
  $('home-modes').innerHTML = Object.entries(groups).map(([g, ks]) => `<div class="grp"><div class="kicker">${esc(g)}</div>${ks.map(k =>
    `<button class="card tile mode ${MODES[k].feat ? 'feat' : ''}" data-mode="${k}">${modeIcon(k)}<div><b>${esc(MODES[k].t)}</b><span>${esc(MODES[k].s)}</span></div></button>`).join('')}</div>`).join('');
}

/* home: one way in. Play = you captain the left team, ball by ball; the computer picks
   the XI, the next batter and the Impact Player (6.3). The two teams live in the Match or series form (s-t1 / s-t2). */
const heroTeams = () => { const n = META.teams.map(t => t.name); return [$('s-t1').value || n[0], $('s-t2').value || n[1] || n[0]]; };
function drawHero() {
  if ($('c-fmt').value === 'test') { heroFormat('t20'); return; }     // quick play is T20 / ODI: nobody captains a Test yet
  const names = META.teams.map(t => t.name), fmt = $('c-fmt').value, tt = heroTeams();
  const side = i => `<button class="qh-team" data-side="${i}" title="Change team">${badge(tt[i], 'lg')}
    <span class="qh-nm">${esc(pickName(tt[i], names))}</span></button>`;
  $('hero').innerHTML = `<p class="qh-tag">Captain a real ${fmt === 'odi' ? 'ODI' : 'T20'} side, ball by ball.</p>
    <div class="qh-vs">${side(0)}<span class="qh-v">v</span>${side(1)}</div>
    <div class="seg qh-fmt" id="h-fmt"><button data-f="t20" class="${fmt === 't20' ? 'on' : ''}">T20</button><button data-f="odi" class="${fmt === 'odi' ? 'on' : ''}">ODI</button></div>
    <button class="btn go big qh-play" id="h-play">&#9654;&nbsp; Play</button>
    <button class="lnk qh-sim" id="h-sim">Just simulate the result &rsaquo;</button>
    <div class="err" id="h-err"></div>`;
  $('hero').querySelectorAll('.qh-team').forEach(b => b.onclick = () => teamSheet(+b.dataset.side));
  $('h-fmt').querySelectorAll('button').forEach(b => b.onclick = () => heroFormat(b.dataset.f));
  $('h-play').onclick = openPre;
  $('h-sim').onclick = simulateQuick;
}
function setHeroTeam(i, name) {
  const id = 's-t' + (i + 1);
  $(id).value = name; showRoster(id, 's-r' + (i + 1)); drawHero();
}
/* T20 <-> ODI: a nation's preset follows the format when the other one exists ("India T20 2024" -> "India ODI 2023") */
function heroFormat(f) {
  $('c-fmt').value = f; $('c-fmt').dispatchEvent(new Event('change'));
  const names = META.teams.map(t => t.name), want = f === 'odi' ? 'ODI' : 'T20';
  heroTeams().forEach((n, i) => {
    if (!isNationPreset(n) || n.includes(' ' + want + ' ')) return;
    const alt = names.find(x => teamKey(x) === teamKey(n) && x.includes(' ' + want + ' '));
    if (alt) $('s-t' + (i + 1)).value = alt;
  });
  drawHero();
}
/* the team sheet: nations, franchises and your own teams, big rows */
const isNationPreset = n => / (T20|ODI|Test) \d{4}$/.test(n);
const isFranchise = n => !isNationPreset(n) && / (19|20)\d{2}$/.test(n) && !!TEAM_ID[teamKey(n)];
function teamSheet(side) {
  const names = META.teams.map(t => t.name), fmt = $('c-fmt').value, cur = heroTeams()[side];
  const mine = n => (fmt === 'odi') === n.includes(' ODI ');
  const nat = names.filter(isNationPreset).sort((a, b) => (mine(b) ? 1 : 0) - (mine(a) ? 1 : 0));
  const fr = names.filter(isFranchise), own = names.filter(n => !nat.includes(n) && !fr.includes(n));
  const yr = fr.length ? (fr[0].match(/\d{4}$/) || [''])[0] : '';
  const grp = (t, list) => list.length ? `<div class="bs-sec">${t}</div><div class="bs-list">${list.map(n => `<button data-n="${esc(n)}" class="${n === cur ? 'on' : ''}">${badge(n, 'md')}
    <span>${esc(pickName(n, names))}</span>${n === cur ? '<b class="ok">&#10003;</b>' : ''}</button>`).join('')}</div>` : '';
  openSheet(`<h3>${side ? 'Opponent' : 'Your team'}</h3>${grp('Nations', nat)}${grp(`Franchises ${yr}`, fr)}${grp('My teams', own)}`);
  $('bsheet-in').querySelectorAll('[data-n]').forEach(b => b.onclick = () => { closeSheet(); setHeroTeam(side, b.dataset.n); });
}
/* elements lent to a sheet (data-home = the id of the element they live in) go back before it changes */
function sheetRescue() { document.querySelectorAll('#bsheet-in [data-home]').forEach(n => $(n.dataset.home).appendChild(n)); }
function openSheet(html) {
  if (typeof coachHide === 'function') coachHide(false);
  sheetRescue();
  $('bsheet-in').innerHTML = html; $('bsheet').scrollTop = 0;
  $('bsheet').classList.add('on'); $('sheet-dim').classList.add('on');
}
function closeSheet() {
  if (!$('bsheet')) return;
  $('bsheet').classList.remove('on'); $('sheet-dim').classList.remove('on');
  sheetRescue();
  if (typeof CAP !== 'undefined') CAP.sheetKind = null;
}
/* era & grounds for a quick match, from the teams: two franchises play in their league's conditions, else
   international; the year is the teams' own (clamped to the data) */
function quickConds(tt, fmt) {
  const comps = META.formats[fmt].competitions;
  const comp = fmt === 't20' && tt.every(isFranchise) && comps.some(c => c.id === 'ipl') ? 'ipl' : {odi: 'odi_full', test: 'test_full'}[fmt] || 't20i_full';
  const c = comps.find(x => x.id === comp) || comps[0];
  const ys = tt.map(n => +((n.match(/(19|20)\d{2}$/) || [])[0] || 0)).filter(Boolean);
  const y = ys.length ? Math.max(...ys) : +$('c-year').value || c.last;
  return {comp: c.id, year: Math.max(c.first, Math.min(c.last, y))};
}
function quickPayload(cap) {
  const tt = heroTeams(), fmt = $('c-fmt').value, cond = quickConds(tt, fmt);
  const p = {mode: 'series', fmt, comp: cond.comp, year: cond.year, venues: [], seed: '', rain: $('c-rain').checked,
    team1: tt[0], team2: tt[1], matches: 1};
  if (cap) Object.assign(p, {captain_i: 0, opponents: $('g-opp').value || 'expert',
    manual: ['toss', 'bowler', 'ball', ...(PRE.xi ? ['xi'] : [])]});
  return p;
}
async function simulateQuick() {
  setMode('series', false); $('h-err').textContent = ''; LIVE_AWAY = false;
  try { await api('/api/run', quickPayload(false)); poll(); } catch (e) { $('h-err').textContent = e.message; }
}

/* pre-match card: the XI is suggested, the toss is one tap; the run starts on the call. The engine tosses the coin:
   it lands on your call when your side won the toss (then Bat / Bowl), else on the other face. */
const PRE = {on: false, call: null, xi: false, phase: '', t0: 0};
function openPre() {
  setMode('series', false);
  const tt = heroTeams(), fmt = $('c-fmt').value, cond = quickConds(tt, fmt);
  Object.assign(PRE, {on: false, call: null, xi: false, phase: ''});
  setDisplayTeams(tt);
  $('pre-teams').innerHTML = `${badge(tt[0], 'lg')}<span class="qh-v">v</span>${badge(tt[1], 'lg')}`;
  $('pre-line').innerHTML = `<b>${esc(dn(tt[0]))}</b> v <b>${esc(dn(tt[1]))}</b> · ${fmt === 'odi' ? 'ODI' : 'T20'} · ${esc(compName(fmt, cond.comp))} ${cond.year}`;
  preXI(false); $('pre-xi').style.display = ''; $('pre-xi').disabled = false;
  $('pre-coin').className = 'coin'; $('pre-coin').textContent = 'H';
  $('pre-err').textContent = '';
  document.querySelectorAll('#pre-len button').forEach(b => b.onclick = () => setLen(b.dataset.l));
  setLen(capLen());
  preButtons();
  showView('v-pre');
}
function preXI(pick) {
  PRE.xi = pick;
  $('pre-xi-t').innerHTML = pick ? 'Your XI: you pick it after the toss' : 'Your XI: suggested <b class="ok">&#10003;</b>';
  $('pre-xi').textContent = pick ? 'Use the suggested XI' : 'Change XI';
  $('pre-xi').onclick = () => preXI(!PRE.xi);
}
function preButtons() {
  $('pre-q').textContent = 'Call the toss';
  $('pre-b').innerHTML = ['Heads', 'Tails'].map(c => `<button class="btn go" data-call="${c}">${c}</button>`).join('');
  $('pre-b').querySelectorAll('button').forEach(b => b.onclick = () => preCall(b.dataset.call));
}
async function preCall(call) {
  LIVE_AWAY = false;
  Object.assign(PRE, {call, phase: 'wait', t0: Date.now()});
  $('pre-b').innerHTML = ''; $('pre-q').textContent = ''; $('pre-err').textContent = '';
  $('pre-xi').disabled = true;
  $('pre-coin').className = 'coin spin';
  try { await api('/api/run', quickPayload(true)); PRE.on = true; poll(); }
  catch (e) { PRE.phase = ''; $('pre-coin').className = 'coin'; $('pre-err').textContent = e.message; $('pre-xi').disabled = false; preButtons(); }
}
/* called by poll() while the pre-match card is up */
function preRender(st) {
  const q = st.captain.pending;
  if (!q || PRE.phase !== 'wait' || Date.now() - PRE.t0 < 900) return;
  const won = q.kind === 'toss', other = PRE.call === 'Heads' ? 'Tails' : 'Heads', face = won ? PRE.call : other;
  const tt = heroTeams();
  $('pre-coin').className = 'coin land'; $('pre-coin').textContent = face[0];
  $('pre-xi').disabled = false; $('pre-xi').style.display = 'none';
  if (won) {
    PRE.phase = 'choose';
    $('pre-q').textContent = `${face}. You won the toss.`;
    $('pre-b').innerHTML = q.options.map(o => `<button class="btn ${o === q.default ? 'go' : 'sec'}" data-d="${o}">${o === 'bat' ? 'Bat first' : 'Bowl first'}${o === q.default ? ' <small class="pre-sug">Suggested</small>' : ''}</button>`).join('');
    $('pre-b').querySelectorAll('button').forEach(b => b.onclick = async () => {
      $('pre-b').innerHTML = '';
      try { await api('/api/decide', {id: q.id, choice: b.dataset.d, auto: {}}); } catch (e) { toast(e.message, true); }
      preDone();
    });
    return;
  }
  PRE.phase = 'lost';
  const s = q.state || {};
  const d = q.toss ? (/chose to bat/.test(q.toss) ? 'bat' : 'bowl') : s.innings === 1 ? (s.batting === q.team ? 'bowl' : 'bat') : 'bowl';
  $('pre-q').textContent = `${face}. ${dn(tt[1])} won the toss and chose to ${d}. You ${d === 'bat' ? 'bowl' : 'bat'}.`;
  setTimeout(preDone, 1700);
}
function preDone() { PRE.on = false; PRE.phase = ''; $('pre-xi').style.display = ''; clearTimeout(POLL_T); poll(); }

/* home: the one thing in progress (a live match or a career); past results are under Results */
async function drawHomeCont() {
  let row = '';
  try {
    const st = await api('/api/status');
    if (st.status === 'running' && !PRE.on) {
      const title = String(st.title || 'Match').split(' - ')[0], tt = title.split(' v ');
      setDisplayTeams(tt);
      row = `<button class="cont1 live" data-nav="live"><span class="dot"></span><span>Continue: <b>${esc(dnText(title, tt))}</b> · live</span><span class="go">&rsaquo;</span></button>`;
    }
  } catch (e) { /* offline */ }
  const c = (META.careers || [])[0];
  if (!row && c) row = `<button class="cont1" data-career="${esc(c.id)}"><span class="dot"></span><span>Continue: <b>${esc(c.name)}</b> · ${esc(c.league)} ${esc(c.season)} ${c.phase === 'auction' ? 'auction' : 'season'}</span><span class="go">&rsaquo;</span></button>`;
  $('home-cont').innerHTML = row;
  $('home-cont').querySelectorAll('[data-career]').forEach(b => b.onclick = () => openCareer(b.dataset.career));
}
/* four doors instead of eleven tiles; each opens a chooser with 2-5 big cards */
const DOORS = [
  {t: 'Play a friend', s: 'on two phones', ic: 'mp', modes: ['mp']},
  {t: 'Seasons & careers', ic: 'league', modes: ['league', 'domestic', 'career']},
  {t: 'Auction & draft', ic: 'auction', modes: ['auction', 'draft']},
  {t: 'What-if sandbox', ic: 'classic', modes: ['series', 'tournament', 'classic', 'classic_t', 'builder']}];
const DOOR_LINE = {league: 'Any season of 11 leagues, real squads.', career: 'Run a franchise or a state, year after year.',
  domestic: "India's domestic T20: captain a state.",
  auction: 'Bid for a squad, then play.', draft: 'Pick players in turns, then a league.',
  series: 'Two teams, one to seven matches.', tournament: 'Your own World Cup or league.',
  classic: 'Great sides from any era.', classic_t: 'Eras meet in one tournament.', builder: 'Make and save your own XI.'};
function drawDoors() {
  $('home-doors').innerHTML = DOORS.map((d, i) => `<button class="card door" data-door="${i}">${modeIcon(d.ic)}
    <b>${esc(d.t)}${d.s ? `<span> ${esc(d.s)}</span>` : ''}</b></button>`).join('');
  $('home-doors').querySelectorAll('.door').forEach(b => b.onclick = () => openDoor(+b.dataset.door));
}
function openDoor(i) {
  const d = DOORS[i];
  if (d.modes.length === 1) return setMode(d.modes[0]);
  $('door-title').textContent = d.t;
  $('door-list').innerHTML = d.modes.map(k => `<button class="card tile mode" data-mode="${k}">${modeIcon(k)}<div><b>${esc(MODES[k].t)}</b><span>${esc(DOOR_LINE[k])}</span></div></button>`).join('');
  $('door-list').querySelectorAll('.mode').forEach(b => b.onclick = () => setMode(b.dataset.mode));
  showView('v-door');
}
function goHome() { closeSheet(); const on = $('v-home').classList.contains('on'); showView('v-home'); if (on) { drawHero(); drawHomeCont(); } }
/* leaving the live screen (top bar, tab bar) keeps the match waiting: the pill and Continue lead back to it */
let LIVE_AWAY = false;
function navTo(k) {
  LIVE_AWAY = k !== 'live';
  if (k === 'home') goHome();
  else if (k === 'results') { if (META.has_results || R) showResults(R_RUN || undefined); else toast('No results yet. Play something first.'); }
  else if (k === 'saved') setMode('saved');
  else if (k === 'careers') setMode('career');
  else if (k === 'builder') setMode('builder');
  else if (k === 'live') {
    if (mpOn()) { mpPoll(); return; }
    api('/api/status').then(st => st.status === 'running' ? poll() : toast('Nothing is playing right now.')).catch(() => {});
  }
}

/* clickable card / chip pickers that drive a hidden <select> (keeps every existing onchange handler) */
function picker(sel, render, cls) {
  const box = document.createElement('div');
  box.className = 'picker ' + cls;
  sel.after(box); sel.classList.add('picked');
  const draw = () => {
    box.innerHTML = [...sel.options].map(o => `<button type="button" class="${o.value === sel.value ? 'on' : ''}" data-v="${esc(o.value)}">${render(o)}</button>`).join('');
    box.querySelectorAll('button').forEach(b => b.onclick = () => {
      sel.value = b.dataset.v === sel.value && sel.dataset.toggle !== undefined ? sel.options[0].value : b.dataset.v;
      sel.dispatchEvent(new Event('change')); draw();
    });
  };
  new MutationObserver(draw).observe(sel, {childList: true});
  sel.addEventListener('change', draw);
  draw();
  return draw;
}
const lgCard = o => { const L = LEAGUE_ID[o.value] || [o.text.slice(0, 4).toUpperCase(), '#334', '#fff', '#889', ''];
  return `<span class="badge" style="--c:${L[1]};--f:${L[2]};--a:${L[3]}">${esc(L[0])}</span><span class="t"><b>${esc(o.text)}</b><small>${esc(L[4])}</small></span>`; };
const teamCard = o => o.value ? `${badge(o.value)}<span class="t"><b>${esc(teamKey(o.text))}</b></span>`
  : `<span class="badge" style="--c:#1a2842;--f:#8d9bb5;--a:#2a3a58">—</span><span class="t"><b>Just watch</b><small>the computer plays everything</small></span>`;
function initPickers() {
  [['l-league', lgCard, 'cards'], ['k-league', lgCard, 'cards'], ['a-league', lgCard, 'cards'],
   ['l-season', o => esc(o.text), 'chips'], ['k-season', o => esc(o.text), 'chips'], ['a-season', o => esc(o.text), 'chips'],
   ['l-captain', teamCard, 'cards teams'], ['k-user', o => o.value ? `${badge(o.value)}<span class="t"><b>${esc(o.text)}</b></span>` : teamCard(o), 'cards teams'],
   ['dm-season', o => esc(o.text), 'chips'], ['dm-captain', teamCard, 'cards teams']]
    .forEach(([id, r, c]) => { if ($(id)) picker($(id), r, c); });
  $('l-captain').dataset.toggle = ''; $('dm-captain').dataset.toggle = '';
}

/* the start bar repeats the form's own summary line (".total") */
function syncSum() {
  const t = document.querySelector('#v-setup .form.on .total'), v = t ? t.textContent : '';
  if ($('su-sum').textContent !== v) $('su-sum').textContent = v;
}

async function init() {
  META = await api('/api/meta');
  setLeagueInfo(META.league_info);
  drawModeTiles(); drawDoors();
  $('sheet-dim').onclick = closeSheet;
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeSheet(); });
  document.querySelectorAll('.mode').forEach(b => b.onclick = () => setMode(b.dataset.mode));
  document.addEventListener('click', e => {
    const n = e.target.closest('[data-nav]'); if (n) { e.preventDefault(); navTo(n.dataset.nav); }
    const m = e.target.closest('a[data-mode]'); if (m) { e.preventDefault(); setMode(m.dataset.mode); }
  });
  const sumObs = new MutationObserver(syncSum);
  document.querySelectorAll('#v-setup .total').forEach(t => sumObs.observe(t, {subtree: true, childList: true, characterData: true}));
  document.querySelectorAll('.tab').forEach(t => t.onclick = () => openTab(t.dataset.pane));
  $('c-fmt').onchange = e => { if (e.isTrusted) COND.fmt = true; fmtChanged(); fillConditions(); refreshClassic(); fillTeams();
    if (e.isTrusted) followFormat(); autoConds(); capOptions(); };
  $('c-comp').onchange = e => { if (e.isTrusted) COND.user = true; checkYear(); condLine(); };
  $('c-year').oninput = e => { if (e.isTrusted) COND.user = true; checkYear(); condLine(); };
  $('c-vsearch').oninput = filterVenues;
  $('c-vclear').onclick = () => { [...$('c-venues').options].forEach(o => o.selected = false); $('c-vsearch').value = ''; drawVenues(); };
  fillSelect($('t-ko'), META.knockouts.map(k => ({v: k.id, t: k.label})));
  ['t-rounds', 't-groups', 't-ko'].forEach(id => $(id).onchange = updateTournamentTotal);
  $('t-search').oninput = filterTeams;
  fillConditions(); fillTeams(); initClassic(); initDraftForm(); initAuctionForm(); initCareerForm(); initLeague(); initDomestic(); initBuilder(); initMatchNav();
  document.querySelectorAll('input[data-chips]').forEach(numChips);
  presetChips($('t-preset'), 't'); presetChips($('ct-preset'), 'ct');
  const teamsChanged = () => { capOptions(); autoConds(); };      // the captain chips list the teams chosen
  ['s-t1', 's-t2'].forEach(id => $(id).addEventListener('change', teamsChanged));
  $('t-list').addEventListener('change', teamsChanged);
  ['cs-r1', 'cs-r2', 'ct-rows'].forEach(id => $(id).addEventListener('change', () => setTimeout(teamsChanged, 400)));
  $('ct-add').addEventListener('click', () => setTimeout(teamsChanged, 400));
  ['d-ya', 'd-yb', 'a-ya', 'a-yb'].forEach(id => $(id).addEventListener('change', autoConds));
  mpSetupInit();
  $('go-btn').onclick = start;
  $('g-captain').onfocus = capOptions; $('g-captain').onmousedown = capOptions;
  $('g-captain').onchange = capBoxes; ['c-comp', 'c-year'].forEach(id => $(id).addEventListener('change', capBoxes));
  $('r-save').onclick = saveRun;
  $('r-career').onclick = () => openCareer(R.career.id);
  if (META.has_results) $('last-btn').style.display = '';
  initPickers();
  picker($('g-captain'), o => o.value === '' ? 'Just watch' : esc(pickName(o.text.replace(/ \(your drafted team\)$/, ''), capSides())), 'chips wrap');
  document.querySelector('.view.on').classList.remove('on'); showView('v-home');
  if (await mpInit()) return;          // two players: a room this browser is in, or a ?join= link
  if (META.job && META.job.status === 'running') poll();
}
