'use strict';
/* Limited-overs simulator UI. Helpers, sortable tables, popovers and match links are ported from the Test sim's
   webui/app.js; forms and results are rewritten for this engine's results (engine/tournament.py). */

/* ───────────────────────── helpers ───────────────────────── */
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
async function api(path, body) {
  const opt = body === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)};
  const r = await fetch(path, opt);
  let data = null;
  try { data = await r.json(); } catch (e) { data = null; }
  if (!r.ok) throw new Error((data && data.error) || `${r.status} ${r.statusText}`);
  return data;
}
function toast(msg, bad) {
  const t = $('toast'); t.textContent = msg; t.className = 'toast' + (bad ? ' bad' : ''); t.style.display = 'block';
  clearTimeout(t._h); t._h = setTimeout(() => t.style.display = 'none', 4000);
}
function showView(id) {
  const was = document.querySelector('.view.on');
  document.querySelectorAll('.view').forEach(v => v.classList.toggle('on', v.id === id));
  if (id !== 'v-auction') document.body.classList.remove('au-fold');     // the auction room folds the sidebar away
  if (!was || was.id !== id) window.scrollTo(0, 0);
  const nav = {'v-home': 'home', 'v-setup': MODE === 'saved' ? 'saved' : MODE === 'career' ? 'careers' : 'home', 'v-results': 'results',
    'v-builder': 'builder', 'v-career': 'careers', 'v-captain': 'live', 'v-running': 'live', 'v-mp': 'live', 'v-door': 'home', 'v-pre': 'home'}[id] || '';
  document.querySelectorAll('[data-nav]').forEach(b => { if (b.closest('#nav,#tabbar')) b.classList.toggle('on', b.dataset.nav === nav); });
  document.body.dataset.view = id;
  if (id === 'v-home' && META && (!was || was.id !== id)) { drawHero(); drawHomeCont(); }
}
const fmtTime = s => { s = Math.round(s); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; };
const fmtNum = (v, d) => v === null || v === undefined || v === '' ? '–' : (typeof v === 'number' && d !== undefined ? v.toFixed(d) : v);
function fillSelect(sel, items, keep) {
  const old = keep ? sel.value : null;
  sel.innerHTML = items.map(i => typeof i === 'string' ? `<option>${esc(i)}</option>` : `<option value="${esc(i.v)}">${esc(i.t)}</option>`).join('');
  if (old !== null && [...sel.options].some(o => o.value === old)) sel.value = old;
}

/* names for people: competitions, preset teams, detail level */
const COMP_NAME = {t20i_full: 'international', t20i: 'international (all teams)', odi_full: 'international', odi: 'international (all teams)',
  ipl: 'IPL', bbl: 'BBL', psl: 'PSL', cpl: 'CPL', sat: 'SA20', ilt: 'ILT20', bpl: 'BPL', lpl: 'LPL', mlc: 'MLC', ntb: 'T20 Blast', ssm: 'Super Smash'};
function compName(fmt, id) {
  if (!id) return '';
  if (COMP_NAME[id]) return COMP_NAME[id];
  const c = META && META.formats[fmt] && META.formats[fmt].competitions.find(c => c.id === id);
  return c ? c.label : String(id).replace(/_/g, ' ');
}
/* "India T20 2024" -> "India", unless another team in the list has the same name without its year */
function pickName(name, all) {
  const k = teamKey(name);
  if (k === name) return name;
  const same = (all || []).filter(n => teamKey(n) === k);
  if (same.length < 2) return k;
  // two presets of one nation (India T20 2024, India ODI 2023): the one in the chosen format keeps the plain name
  const fm = ($('c-fmt') ? $('c-fmt').value : '').toUpperCase(), inFmt = n => new RegExp(`\\b${fm}\\b`, 'i').test(n.slice(k.length));
  return fm && inFmt(name) && same.filter(inFmt).length === 1 ? k : `${k} (${name.slice(k.length).trim()})`;
}
const DETAIL_KEY = 'lo.detail', MORE_KEY = 'lo.more.';
function lsGet(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
function lsSet(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private window: not remembered */ } }
function setDetail(d) {
  d = d === 'full' ? 'full' : 'simple';
  document.body.classList.toggle('detail-full', d === 'full'); document.body.classList.toggle('detail-simple', d !== 'full');
  document.querySelectorAll('#detail-sw button').forEach(b => b.classList.toggle('on', b.dataset.d === d));
  lsSet(DETAIL_KEY, d);
}
function initDetail() {
  setDetail(lsGet(DETAIL_KEY) || 'simple');
  document.querySelectorAll('#detail-sw button').forEach(b => b.onclick = () => setDetail(b.dataset.d));
  document.querySelectorAll('details.more').forEach(d => {
    if (lsGet(MORE_KEY + d.id) === '1') d.open = true;
    d.addEventListener('toggle', () => lsSet(MORE_KEY + d.id, d.open ? '1' : '0'));
  });
}
initDetail();
/* the top-bar pill only while something runs: "Live: IND v AUS" (click to go back to it) */
function livePill(running, st) {
  const p = $('status-pill');
  p.style.display = running ? '' : 'none';
  p.classList.toggle('run', running);
  if (!running) return;
  const tm = (typeof CAP !== 'undefined' && CAP.teams) || [];
  const vs = tm.length === 2 && tm.every(Boolean) ? ': ' + tm.map(t => tcol(t).short).join(' v ') : '';
  p.innerHTML = '<i></i>' + (st && st.captain ? 'Live' + vs : 'Simulating');
}

/* generic sortable table (from the Test sim) */
function table(el, cols, rows, opt = {}) {
  el._cols = cols; el._rows = rows; el._opt = opt;
  if (!el._sort) el._sort = opt.sort || null;
  renderTable(el);
}
function renderTable(el) {
  const cols = el._cols, opt = el._opt, s = el._sort;
  let rows = el._rows.slice();
  if (s) {
    const c = cols.find(c => c.k === s.k);
    const val = r => c.sv ? c.sv(r) : r[c.k];
    rows.sort((a, b) => {
      let x = val(a), y = val(b);
      const xn = x === null || x === undefined || x === '', yn = y === null || y === undefined || y === '';
      if (xn || yn) return xn && yn ? 0 : xn ? 1 : -1;
      if (typeof x === 'string') return x.localeCompare(y) * s.dir;
      return (x - y) * s.dir;
    });
  }
  const total = rows.length;
  if (opt.limit) rows = rows.slice(0, opt.limit);
  let h = '<table><thead><tr>';
  cols.forEach(c => {
    const arrow = s && s.k === c.k ? (s.dir > 0 ? ' ▲' : ' ▼') : '';
    h += `<th class="${c.nosort ? '' : 'sortable'} ${c.num ? 'num' : ''}" data-k="${c.k}">${esc(c.label)}${arrow}</th>`;
  });
  h += '</tr></thead><tbody>';
  rows.forEach((r, i) => {
    const cls = (opt.rowClass ? opt.rowClass(r) : '') + (opt.onRow ? ' click' : '');
    h += `<tr class="${cls}" data-i="${i}">` + cols.map(c => `<td class="${c.num ? 'num' : ''}">${c.html ? c.html(r) : esc(c.f ? c.f(r) : fmtNum(r[c.k]))}</td>`).join('') + '</tr>';
  });
  if (!rows.length) h += `<tr><td colspan="${cols.length}" class="muted">${esc(opt.empty || 'Nothing to show')}</td></tr>`;
  h += '</tbody></table>';
  if (opt.limit && total > opt.limit) h += `<div class="muted small" style="padding:8px">Showing ${opt.limit} of ${total} — use the filters to narrow down.</div>`;
  el.innerHTML = h;
  el.querySelectorAll('th.sortable').forEach(th => th.onclick = () => {
    const k = th.dataset.k, c = cols.find(c => c.k === k);
    el._sort = el._sort && el._sort.k === k ? {k, dir: -el._sort.dir} : {k, dir: c.num ? -1 : 1};
    renderTable(el);
  });
  if (opt.onRow || opt.onClick) el.querySelectorAll('tbody tr[data-i]').forEach(tr => {
    const r = rows[+tr.dataset.i];
    if (opt.onRow) tr.onclick = e => { if (!e.target.closest('button') && !e.target.closest('[data-match]')) opt.onRow(r); };
    tr.querySelectorAll('button[data-act]').forEach(b => b.onclick = () => opt.onClick(r, b.dataset.act));
  });
}

/* ───────────────────────── state / init ───────────────────────── */
let META = null, MODE = 'series';

/* modes: home tiles, setup header */
const ICON = {
  series: '<circle cx="12" cy="12" r="8"/><path d="M8 6c2 3 2 9 0 12M16 6c-2 3-2 9 0 12"/>',
  mp: '<rect x="3" y="5" width="8" height="13" rx="2"/><rect x="13" y="5" width="8" height="13" rx="2"/>',
  tournament: '<path d="M7 4h10v4a5 5 0 0 1-10 0z"/><path d="M12 13v4M8 20h8M7 6H4a3 3 0 0 0 3 4M17 6h3a3 3 0 0 1-3 4"/>',
  league: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18M8 2v4M16 2v4"/>',
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
  career: {t: 'Career', s: 'Run a franchise for years: ageing, auctions, trophies', g: 'Seasons and careers', c: '#b26bff', feat: true},
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
const isNationPreset = n => / (T20|ODI) \d{4}$/.test(n);
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
  const comp = fmt === 't20' && tt.every(isFranchise) && comps.some(c => c.id === 'ipl') ? 'ipl' : fmt === 'odi' ? 'odi_full' : 't20i_full';
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
  {t: 'Seasons & careers', ic: 'league', modes: ['league', 'career']},
  {t: 'Auction & draft', ic: 'auction', modes: ['auction', 'draft']},
  {t: 'What-if sandbox', ic: 'classic', modes: ['series', 'tournament', 'classic', 'classic_t', 'builder']}];
const DOOR_LINE = {league: 'Any season of 11 leagues, real squads.', career: 'Run a franchise, year after year.',
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
   ['l-captain', teamCard, 'cards teams'], ['k-user', o => o.value ? `${badge(o.value)}<span class="t"><b>${esc(o.text)}</b></span>` : teamCard(o), 'cards teams']]
    .forEach(([id, r, c]) => { if ($(id)) picker($(id), r, c); });
  $('l-captain').dataset.toggle = '';
}

/* the start bar repeats the form's own summary line (".total") */
function syncSum() {
  const t = document.querySelector('#v-setup .form.on .total'), v = t ? t.textContent : '';
  if ($('su-sum').textContent !== v) $('su-sum').textContent = v;
}

async function init() {
  META = await api('/api/meta');
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
  $('c-fmt').onchange = () => { fillConditions(); refreshClassic(); fillTeams(); };
  $('c-comp').onchange = checkYear; $('c-year').oninput = checkYear;
  $('c-vsearch').oninput = filterVenues;
  fillSelect($('t-ko'), META.knockouts.map(k => ({v: k.id, t: k.label})));
  ['t-rounds', 't-groups', 't-ko'].forEach(id => $(id).onchange = updateTournamentTotal);
  $('t-search').oninput = filterTeams;
  fillConditions(); fillTeams(); initClassic(); initDraftForm(); initAuctionForm(); initCareerForm(); initLeague(); initBuilder(); initMatchNav();
  $('go-btn').onclick = start;
  $('g-captain').onfocus = capOptions; $('g-captain').onmousedown = capOptions;
  $('g-captain').onchange = capBoxes; ['c-comp', 'c-year'].forEach(id => $(id).addEventListener('change', capBoxes));
  $('r-save').onclick = saveRun;
  $('r-career').onclick = () => openCareer(R.career.id);
  if (META.has_results) $('last-btn').style.display = '';
  initPickers();
  document.querySelector('.view.on').classList.remove('on'); showView('v-home');
  if (await mpInit()) return;          // two players: a room this browser is in, or a ?join= link
  if (META.job && META.job.status === 'running') poll();
}

function setMode(m, show = true) {
  MODE = m;
  document.querySelectorAll('.form').forEach(f => f.classList.toggle('on', f.id === 'f-' + m));
  const b = m === 'builder' || m === 'saved';
  if (m === 'saved') drawSaved();
  if (m === 'career') drawCareers();
  $('go-wrap').style.display = b ? 'none' : ''; $('cond').style.display = b || m === 'league' || m === 'career' ? 'none' : '';
  if (m === 'auction') aRefresh();
  capHome();
  capOptions();
  $('go-err').textContent = '';
  const M = MODES[m] || {t: m, s: ''};
  $('su-title').textContent = M.t; $('su-blurb').textContent = M.s; $('su-ic').outerHTML = modeIcon(m, 'big').replace('class="mic', 'id="su-ic" class="mic');
  $('su-sum-t').textContent = M.t; syncSum();
  $('go-btn').innerHTML = {mp: '&#9654;&nbsp; Open a room', draft: '&#9654;&nbsp; Start the draft', auction: '&#9654;&nbsp; Start the auction',
    career: '&#9654;&nbsp; Start the career', league: '&#9654;&nbsp; Start the season'}[m] || '&#9654;&nbsp; Start';
  if (!show) return;
  if (m === 'builder') { showView('v-builder'); loadBuilderPool(); }
  else showView('v-setup');
}
/* the captain boxes live in the conditions panel; the draft room borrows them once the draft is done */
function capHome() {
  const a = $('cap-anchor'), m = $('cap-more-anchor');
  if (a && $('g-cap-box').previousElementSibling !== a) a.after($('g-cap-box'));
  if (m && $('g-manual-box').previousElementSibling !== m) m.after($('g-manual-box'));
}

/* conditions: format, competition, year, venues */
function fillConditions() {
  const f = META.formats[$('c-fmt').value];
  fillSelect($('c-comp'), f.competitions.map(c => ({v: c.id, t: `${c.label} (${c.first}–${c.last})`})), true);
  $('c-venues').innerHTML = f.venues.map(v => `<option value="${esc(v.name)}" data-k="${esc(v.name.toLowerCase())}">${esc(v.name)} (${v.matches} games${v.runs >= 1.03 ? ', high-scoring' : v.runs <= 0.97 ? ', low-scoring' : ''})</option>`).join('');
  filterVenues(); checkYear();
}
function filterVenues() {
  const q = $('c-vsearch').value.toLowerCase();
  [...$('c-venues').options].forEach(o => o.style.display = o.dataset.k.includes(q) ? '' : 'none');
}
function checkYear() {
  const f = META.formats[$('c-fmt').value], c = f.competitions.find(c => c.id === $('c-comp').value), y = +$('c-year').value;
  $('c-year-err').textContent = c && (y < c.first || y > c.last) ? `${c.label} data covers ${c.first}–${c.last}; the nearest year's conditions will be used.` : '';
}

/* teams (series + tournament) */
function fillTeams() {
  const names = META.teams.map(t => t.name);
  const opts = names.map(n => ({v: n, t: pickName(n, names)}));
  fillSelect($('s-t1'), opts, true); fillSelect($('s-t2'), opts, true);
  if (!$('s-t1')._init) {
    $('s-t1').value = names.includes('India T20 2024') ? 'India T20 2024' : names[0];
    $('s-t2').value = names.includes('Australia T20 2024') ? 'Australia T20 2024' : names[Math.min(1, names.length - 1)];
    $('s-t1')._init = true;
    ['s-t1', 's-t2'].forEach((id, i) => $(id).onchange = () => showRoster(id, 's-r' + (i + 1)));
  }
  showRoster('s-t1', 's-r1'); showRoster('s-t2', 's-r2');
  const checked = new Set([...document.querySelectorAll('#t-list input:checked')].map(i => i.value));
  const first = !$('t-list').children.length;
  $('t-list').innerHTML = META.teams.map(t =>
    `<label data-name="${esc(t.name.toLowerCase())}"><input type="checkbox" value="${esc(t.name)}" ${checked.has(t.name) || (first && / T20 2024$/.test(t.name)) ? 'checked' : ''}> ${esc(pickName(t.name, names))} <span class="muted small full-only">(${t.players.length})</span></label>`).join('');
  $('t-list').querySelectorAll('input').forEach(i => i.onchange = updateTournamentTotal);
  updateTournamentTotal(); drawSavedTeams();
}
function showRoster(selId, outId) {
  const t = META.teams.find(t => t.name === $(selId).value);
  $(outId).innerHTML = t ? `<div class="rhead">${badge(t.name)}<span class="muted small full-only">${t.players.length} players</span></div>
    <div class="pchips">${t.players.map(p => `<span>${esc(p.name)}</span>`).join('')}</div>` : '';
}
function filterTeams() {
  const q = $('t-search').value.toLowerCase();
  $('t-list').querySelectorAll('label').forEach(l => l.style.display = l.dataset.name.includes(q) ? '' : 'none');
}
function matchCount(k, rounds, groups, ko) {
  const sizes = groups > 1 ? [...Array(groups).keys()].map(g => Math.ceil((k - g) / groups)) : [k];
  return rounds * sizes.reduce((a, s) => a + s * (s - 1) / 2, 0) + {semis: 3, ipl: 4, final: 1, none: 0}[ko];
}
function updateTournamentTotal() {
  const k = document.querySelectorAll('#t-list input:checked').length;
  const n = matchCount(k, +$('t-rounds').value, +$('t-groups').value, $('t-ko').value);
  $('t-total').textContent = k < 2 ? `${k} selected — pick at least 2` : `${k} teams · ${n} matches`;
}

/* classic (historical) teams: rows of from / to / nation */
const NATIONS = {};
async function nationsFor(y1, y2) {
  const f = $('c-fmt').value, k = `${f}|${y1}|${y2}`;
  if (!NATIONS[k]) NATIONS[k] = await api(`/api/nations?fmt=${f}&y1=${y1}&y2=${y2}`);
  return NATIONS[k];
}
function classicRow(box, a, b, nation, removable) {
  const row = document.createElement('div');
  row.innerHTML = `<div class="hl-row"><input type="number" value="${a}" title="From"><input type="number" value="${b}" title="To"><select></select><button class="x" title="Remove"${removable ? '' : ' style="visibility:hidden"'}>✕</button></div><div class="err"></div>`;
  const [ia, ib] = row.querySelectorAll('input'), sel = row.querySelector('select'), err = row.querySelector('.err');
  let want = nation;
  row.refresh = async () => {
    const ya = +ia.value, yb = +ib.value;
    if (ya > yb) { err.textContent = `Start year ${ya} is after end year ${yb}.`; return; }
    const d = await nationsFor(ya, yb);
    const names = d.nations.map(n => n.name).sort();
    fillSelect(sel, names);
    if (names.includes(want)) sel.value = want;
    err.textContent = ya < d.first || yb > d.last ? `${$('c-fmt').value.toUpperCase()} data covers ${d.first}–${d.last}.`
      : names.length ? '' : 'No nation has enough players in these years.';
  };
  ia.onchange = row.refresh; ib.onchange = row.refresh;
  sel.onchange = () => { want = sel.value; };
  row.querySelector('.x').onclick = () => { row.remove(); updateClassicTotal(); };
  row.entry = () => ({nation: sel.value, y1: +ia.value, y2: +ib.value});
  box.appendChild(row); row.refresh();
  return row;
}
function initClassic() {
  classicRow($('cs-r1'), 2021, 2024, 'India', false);
  classicRow($('cs-r2'), 2007, 2012, 'Australia', false);
  [[2012, 2016, 'West Indies'], [2021, 2024, 'India'], [2019, 2022, 'England'], [2007, 2012, 'Australia'],
   [2007, 2010, 'Pakistan'], [2009, 2014, 'Sri Lanka']].forEach(([a, b, n]) => classicRow($('ct-rows'), a, b, n, true));
  $('ct-add').onclick = () => { classicRow($('ct-rows'), 2015, 2019, 'New Zealand', true); updateClassicTotal(); };
  fillSelect($('ct-ko'), META.knockouts.map(k => ({v: k.id, t: k.label})));
  ['ct-rounds', 'ct-groups', 'ct-ko'].forEach(id => $(id).onchange = updateClassicTotal);
  document.querySelectorAll('.c-squad').forEach(sel => {
    fillSelect(sel, [{v: '20', t: 'Most-capped 20 of the period (recommended)'}, {v: '15', t: 'Most-capped 15'},
      {v: '25', t: 'Most-capped 25'}, {v: '', t: 'Everyone who played (one-series players too)'}]);
    sel.onchange = () => document.querySelectorAll('.c-squad').forEach(o => o.value = sel.value);
  });
  document.querySelectorAll('.c-ymode').forEach(sel => sel.onchange = () => document.querySelectorAll('.c-ymode').forEach(o => o.value = sel.value));
  updateClassicTotal();
}
function refreshClassic() { document.querySelectorAll('#f-classic .hl-row, #f-classic_t .hl-row').forEach(r => r.parentNode.refresh()); }
function updateClassicTotal() {
  const k = $('ct-rows').children.length;
  const n = matchCount(k, +$('ct-rounds').value, +$('ct-groups').value, $('ct-ko').value);
  $('ct-total').textContent = k < 2 ? 'Add at least 2 teams' : `${k} teams · ${n} matches`;
}

/* ───────────────────────── league season ───────────────────────── */
function initLeague() {
  fillSelect($('l-league'), META.leagues.map(l => ({v: l.id, t: l.label})));
  const league = () => META.leagues.find(x => x.id === $('l-league').value);
  const show = () => {
    const l = league(), s = l && l.seasons.find(x => x.season === $('l-season').value);
    if (!s) { $('l-teams').textContent = 'No league data - run scripts/build_league_presets.py'; return; }
    $('l-teams').innerHTML = s.teams.map(t => `${esc(t.name)} <span class="muted">(${t.n} players, ${t.overseas} overseas)</span>`).join('<br>');
    $('l-total').textContent = `${s.teams.length} teams · ${matchCount(s.teams.length, 2, 1, 'ipl')} matches · ${l.label} ${s.year} conditions · max ${s.max_overseas} overseas per XI`;
    const keep = $('l-captain').value;
    fillSelect($('l-captain'), [{v: '', t: 'None - the computer plays everything'}, ...s.teams.map(t => ({v: t.name, t: t.name}))]);
    if (s.teams.some(t => t.name === keep)) $('l-captain').value = keep;
    CAP.impact = l.id === 'ipl' && s.year >= 2023;
    $('l-impact-opt').style.display = CAP.impact ? '' : 'none';
    $('l-manual-box').style.display = $('l-captain').value ? '' : 'none';
  };
  $('l-captain').onchange = () => { $('l-manual-box').style.display = $('l-captain').value ? '' : 'none'; };
  const seasons = () => { const l = league(); fillSelect($('l-season'), l ? l.seasons.map(s => ({v: s.season, t: s.season})) : []); show(); };
  $('l-league').onchange = seasons; $('l-season').onchange = show; seasons();
}

/* ───────────────────────── fantasy draft ───────────────────────── */
function initDraftForm() {
  const chk = () => {
    const [lo, hi] = META.years[$('c-fmt').value], a = +$('d-ya').value, b = +$('d-yb').value;
    $('d-e').textContent = a > b ? `Start year ${a} is after end year ${b}.` : a < lo || b > hi ? `${$('c-fmt').value.toUpperCase()} data covers ${lo}–${hi}.` : '';
  };
  $('d-ya').onchange = chk; $('d-yb').onchange = chk; $('c-fmt').addEventListener('change', chk);
  $('d-k').oninput = buildDraftNames;
  fillSelect($('d-ko'), META.knockouts.map(k => ({v: k.id, t: k.label})));
  ['d-rounds', 'd-ko'].forEach(id => $(id).onchange = updateDraftTotal);
  buildDraftNames();
}
function buildDraftNames() {
  const k = Math.max(2, Math.min(12, +$('d-k').value || 2));
  const box = $('d-names'), old = [...box.querySelectorAll('input')].map(i => i.value);
  box.innerHTML = '';
  for (let i = 0; i < k; i++) {
    const inp = document.createElement('input');
    inp.type = 'text'; inp.maxLength = 40; inp.style.marginBottom = '4px';
    inp.value = old[i] !== undefined ? old[i] : (META.draft_teams[i] || `Team ${i + 1}`);
    inp.oninput = refreshDraftUser; box.appendChild(inp);
  }
  refreshDraftUser(); updateDraftTotal();
}
function draftNames() { return [...$('d-names').querySelectorAll('input')].map(i => i.value.trim()); }
function refreshDraftUser() {
  const sel = $('d-user'), old = sel.value, first = !sel.options.length;
  fillSelect(sel, [...draftNames().filter(Boolean).map(n => ({v: n, t: n})), {v: '', t: '— none: the computer drafts every team —'}]);
  if (!first && [...sel.options].some(o => o.value === old)) sel.value = old;
}
function updateDraftTotal() {
  const k = draftNames().length;
  $('d-total').textContent = `${k} teams · ${15 * k} picks · then ${matchCount(k, +$('d-rounds').value, 1, $('d-ko').value)} matches`;
}
let DRAFT = null, DPOOL = null;
async function startDraft() {
  const d = await api('/api/draft/start', {fmt: $('c-fmt').value, y1: +$('d-ya').value, y2: +$('d-yb').value,
    teams: draftNames(), user: $('d-user').value, source: $('d-src').value, seed: $('c-seed').value.trim(),
    years_mode: document.querySelector('.c-ymode').value});
  DPOOL = {list: d.pool, byId: new Map(d.pool.map(p => [p.id, p]))};
  const roles = ['WK', 'Batter', 'All-rounder', 'Pace', 'Spin'];
  fillSelect($('dp-role'), [{v: '', t: 'All roles'}, ...roles.map(r => ({v: r, t: r}))]);
  fillSelect($('dp-team'), [{v: '', t: 'All teams'}, ...[...new Set(d.pool.map(p => p.team))].sort().map(t => ({v: t, t}))]);
  ['dp-search', 'dp-role', 'dp-team'].forEach(id => $(id).oninput = drawDraftPool);
  $('dr-auto').onclick = () => draftPick({auto: true});
  $('dr-rest').onclick = () => draftPick({auto: 'rest'});
  $('dr-play').onclick = playDraftLeague;
  renderDraft(d.state);
  if (d.state.done && !d.state.user) playDraftLeague();
}
async function draftPick(body) {
  if (mpOn()) return mpDraftSend(body);            // the two-player draft (multiplayer.js)
  $('dr-msg').textContent = '';
  try { const d = await api('/api/draft/pick', body); renderDraft(d.state); }
  catch (e) { $('dr-msg').textContent = e.message; }
}
async function playDraftLeague() {
  try {
    await api('/api/run', {mode: 'draft', fmt: DRAFT.fmt, comp: $('c-comp').value, year: +$('c-year').value,
      venues: [...$('c-venues').selectedOptions].map(o => o.value), seed: $('c-seed').value.trim(),
      rain: $('c-rain').checked, rounds: +$('d-rounds').value, groups: 1, knockout: $('d-ko').value, ...capPayload()});
    poll();
  } catch (e) { $('dr-msg').textContent = e.message; toast(e.message, true); }
}
const NEED_LABEL = {keeper: 'WK', pace: 'Pace', spin: 'Spin', batter: 'Batters'};
function renderDraft(st) {
  DRAFT = st;
  capOptions();
  showView('v-draft'); $('go-btn').disabled = false;
  if (st.done && st.user) { $('dr-cap').append($('g-cap-box'), $('g-manual-box')); $('dr-cap').classList.add('cap-panel'); }
  else { capHome(); $('dr-cap').classList.remove('cap-panel'); }
  const me = st.user, mine = me ? st.board[me] : [], yours = st.current && st.current === me;
  $('dr-title').textContent = me ? `Drafting for ${me}` : 'Draft';
  $('dr-turn').textContent = st.done ? 'Draft complete' : yours ? 'Your pick!' : `${st.current} to pick`;
  $('dr-turn').className = 'turn' + (yours ? ' you' : '');
  $('dr-progress').textContent = st.done ? `${st.total} picks · players rated on ${st.y1}–${st.y2}` : `Pick ${st.pick_no} of ${st.total} · round ${Math.ceil(st.pick_no / st.teams.length)} of ${st.squad}`;
  $('dr-auto').style.display = st.done || !me ? 'none' : ''; $('dr-rest').style.display = st.done ? 'none' : '';
  $('dr-play').style.display = st.done ? '' : 'none';
  $('dr-sugs').innerHTML = st.suggestions.length ? st.suggestions.map(id => { const p = DPOOL.byId.get(id);
    return `<button class="sug" data-id="${esc(id)}">${esc(p.name)}<small>${esc(p.role)}</small></button>`; }).join('')
    : `<span class="muted small">${st.done ? 'All squads are complete. Press “Play the league”.' : 'Suggestions appear when it is your turn.'}</span>`;
  $('dr-sugs').querySelectorAll('.sug').forEach(b => b.onclick = () => draftPick({id: b.dataset.id}));
  if (me) {
    const c = st.needs[me];
    $('dr-squad-title').textContent = `Your squad (${mine.length}/${st.squad})`;
    $('dr-roles').innerHTML = Object.entries(st.targets).map(([r, t]) => `<span class="role ${c[r] >= t ? 'ok' : ''}">${NEED_LABEL[r]} ${c[r]}/${t}+</span>`).join('');
    $('dr-squad').innerHTML = mine.map(p => `<li>${esc(p.name)} <span>${esc((DPOOL.byId.get(p.id) || {}).team || '')} · ${esc(p.role)}</span></li>`).join('') || '<li class="muted">No players yet</li>';
  } else { $('dr-squad-title').textContent = ''; $('dr-roles').innerHTML = ''; $('dr-squad').innerHTML = ''; }
  drawBoard($('dr-board'), st.teams, st.board, me);
  drawDraftPool();
}
function drawDraftPool() {
  const st = DRAFT, taken = new Set(st.taken), yours = !st.done && st.user && st.current === st.user;
  const q = $('dp-search').value.toLowerCase(), role = $('dp-role').value, team = $('dp-team').value;
  const rows = DPOOL.list.filter(p => !taken.has(p.id) && (!q || p.name.toLowerCase().includes(q)) && (!role || p.role === role) && (!team || p.team === team));
  table($('dp-table'), [
    {k: 'pick', label: '', nosort: true, html: () => `<button class="pick" data-act="pick" ${yours ? '' : 'disabled'}>Pick</button>`},
    {k: 'name', label: 'Player'}, {k: 'team', label: 'Team'}, {k: 'role', label: 'Role'}, {k: 'm', label: 'M', num: true},
    {k: 'bat_avg', label: 'Bat avg', num: true, f: r => fmtNum(r.bat_avg, 1)}, {k: 'bat_sr', label: 'SR', num: true, f: r => fmtNum(r.bat_sr, 1)},
    {k: 'econ', label: 'Econ', num: true, f: r => fmtNum(r.econ, 2)}, {k: 'bowl_avg', label: 'Bowl avg', num: true, f: r => fmtNum(r.bowl_avg, 1)},
    {k: 'value', label: 'Value', num: true, f: r => fmtNum(r.value, 2)},
  ], rows, {limit: 300, sort: {k: 'value', dir: -1}, onClick: r => { if (yours) draftPick({id: r.id}); }, empty: 'No players match'});
}
function drawBoard(el, teams, board, me) {
  el.innerHTML = teams.map(t => `<div class="bcol ${t === me ? 'me' : ''}"><b>${esc(t)}${t === me ? ' (you)' : ''}</b><ol>${(board[t] || []).map(p => `<li>${esc(p.name)} <span class="muted">· ${esc(p.role)}${p.price ? ' · ' + cr(p.price) + (p.retained ? ' R' : '') : ''}</span></li>`).join('')}</ol></div>`).join('');
}

/* ───────────────────────── saved runs ───────────────────────── */
async function saveRun() {
  const name = prompt('Name this run', R.title || 'My run');
  if (!name) return;
  try {
    META.saved = (await api('/api/saved', {name})).saved;
    const sv = META.saved.find(s => s.name === name.trim()) || META.saved[0];
    $('r-save').style.display = 'none'; $('r-saved').textContent = `Saved as “${sv.name}”`;
    toast('Saved. Find it under “Saved”.'); aRefresh();
  } catch (e) { toast(e.message, true); }
}
function drawSaved() {
  const list = META.saved || [];
  $('sv-list').innerHTML = list.length ? list.map(s => `<div class="sv-item" data-id="${esc(s.id)}">
      <b>${esc(s.name)}</b>
      <span class="muted small">${esc(s.title || '')}${s.winner ? ' · winner: ' + esc(s.winner) : ''} · saved ${esc(s.saved)}</span>
      <div class="sv-btns"><button class="btn sec" data-a="open">Open</button><button class="btn sec" data-a="rename">Rename</button>
      <button class="btn sec" data-a="delete">Delete</button></div></div>`).join('')
    : '<div class="muted small">Nothing saved yet. Open a run\'s results and press “Save this run”.</div>';
  $('sv-list').querySelectorAll('.sv-item').forEach(el => {
    const id = el.dataset.id, s = list.find(x => x.id === id);
    el.querySelector('[data-a="open"]').onclick = () => showResults(id);
    el.querySelector('[data-a="rename"]').onclick = async () => {
      const name = prompt('New name', s.name);
      if (name) { META.saved = (await api('/api/saved/rename', {id, name})).saved; drawSaved(); aRefresh(); }
    };
    el.querySelector('[data-a="delete"]').onclick = async () => {
      if (!confirm(`Delete the saved run “${s.name}”? This cannot be undone.`)) return;
      META.saved = (await api('/api/saved/delete', {id})).saved; drawSaved(); aRefresh();
      if (R_RUN === id) showView('v-home');
    };
  });
}

/* ───────────────────────── start / poll ───────────────────────── */
function payload() {
  const base = {mode: MODE, fmt: $('c-fmt').value, comp: $('c-comp').value, year: +$('c-year').value,
    venues: [...$('c-venues').selectedOptions].map(o => o.value), seed: $('c-seed').value.trim(),
    rain: $('c-rain').checked};
  if (MODE === 'series') return {...base, team1: $('s-t1').value, team2: $('s-t2').value, matches: +$('s-n').value};
  if (MODE === 'league') return {mode: 'league', league: $('l-league').value, season: $('l-season').value, seed: $('l-seed').value.trim(), venues: [],
    rain: $('l-rain').checked, captain: $('l-captain').value, opponents: $('l-opp').value,
    manual: [...$('l-manual').querySelectorAll('input:checked')].map(i => i.value).filter(k => k !== 'impact' || CAP.impact)};
  if (MODE === 'classic') return {...base, mode: 'series', team1: $('cs-r1').firstChild.entry(),
    team2: $('cs-r2').firstChild.entry(), matches: +$('cs-n').value, squad_size: document.querySelector('.c-squad').value,
    years_mode: document.querySelector('.c-ymode').value};
  if (MODE === 'classic_t') return {...base, mode: 'tournament', squad_size: document.querySelector('.c-squad').value,
    years_mode: document.querySelector('.c-ymode').value,
    teams: [...$('ct-rows').children].map(r => r.entry()),
    rounds: +$('ct-rounds').value, groups: +$('ct-groups').value, knockout: $('ct-ko').value};
  return {...base, teams: [...document.querySelectorAll('#t-list input:checked')].map(i => i.value),
    rounds: +$('t-rounds').value, groups: +$('t-groups').value, knockout: $('t-ko').value};
}
/* captain a side in Series / Tournament / Classic / Draft (League Season and Auction have their own picker) */
const histName = e => e.y1 === e.y2 ? `${e.nation} ${e.y1}` : `${e.nation} ${e.y1}-${String(e.y1).slice(0, 2) === String(e.y2).slice(0, 2) ? String(e.y2).slice(-2) : e.y2}`;
function capSides() {
  if (MODE === 'series') return [$('s-t1').value, $('s-t2').value];
  if (MODE === 'tournament') return [...document.querySelectorAll('#t-list input:checked')].map(i => i.value);
  if (MODE === 'classic') return [$('cs-r1').firstChild, $('cs-r2').firstChild].map(r => r ? histName(r.entry()) : '');
  if (MODE === 'classic_t') return [...$('ct-rows').children].map(r => histName(r.entry()));
  if (MODE === 'draft') return DRAFT && DRAFT.done && DRAFT.user ? [DRAFT.user] : [];
  return [];
}
function capOptions() {
  const show = ['series', 'tournament', 'classic', 'classic_t', 'draft'].includes(MODE);
  $('g-cap-box').style.display = show ? '' : 'none';
  if (!show) { $('g-manual-box').style.display = 'none'; return; }
  const sel = $('g-captain'), keep = sel.selectedIndex > 0 ? sel.options[sel.selectedIndex].text : '';
  const sides = capSides();
  fillSelect(sel, [{v: '', t: MODE === 'draft' ? 'None - the computer captains every team' : 'None - the computer plays everything'},
    ...sides.map((t, i) => ({v: String(i), t: MODE === 'draft' ? `${t} (your drafted team)` : t}))]);
  const k = [...sel.options].findIndex(o => o.text === keep);
  if (k > 0) sel.selectedIndex = k;
  capBoxes();
}
function capBoxes() {
  $('g-manual-box').style.display = $('g-captain').value ? '' : 'none';
  CAP.impact = $('c-comp').value === 'ipl' && +$('c-year').value >= 2023;
  $('g-impact-opt').style.display = CAP.impact ? '' : 'none';
}
function capPayload() {
  const i = $('g-captain').value;
  return i === '' ? {} : {captain_i: MODE === 'draft' ? DRAFT.teams.indexOf(DRAFT.user) : +i, opponents: $('g-opp').value,
    manual: [...$('g-manual').querySelectorAll('input:checked')].map(x => x.value).filter(k => k !== 'impact' || CAP.impact)};
}
async function start() {
  $('go-err').textContent = ''; $('go-btn').disabled = true; LIVE_AWAY = false;
  try {
    if (MODE === 'draft') { await startDraft(); return; }
    if (MODE === 'auction') { await startAuction(); return; }
    if (MODE === 'career') { await startCareer(); return; }
    if (MODE === 'mp') { await mpCreate(); $('go-btn').disabled = false; return; }
    await api('/api/run', {...payload(), ...capPayload()}); poll();
  }
  catch (e) { $('go-err').textContent = e.message; $('go-btn').disabled = false; }
}
let POLL_T = null;
async function poll() {
  if (mpOn()) return mpPoll();
  clearTimeout(POLL_T);
  let st;
  try { st = await api('/api/status'); } catch (e) { POLL_T = setTimeout(poll, 1500); return; }
  const running = st.status === 'running';
  livePill(running, st);
  if (PRE.on && running && st.captain) { preRender(st); POLL_T = setTimeout(poll, 250); return; }
  PRE.on = false;
  $('go-btn').disabled = running;
  if (running && st.captain && st.captain.skip !== 'all') {
    if (!LIVE_AWAY) { showView('v-captain'); capRender(st); }
    POLL_T = setTimeout(poll, LIVE_AWAY ? 1500 : st.captain.pending ? 700 : 200);
  } else if (running) {
    showView('v-running');
    $('run-title').textContent = st.title || 'Simulating…';
    $('run-bar').style.width = (st.total ? Math.round(100 * st.done / st.total) : 0) + '%';
    $('run-count').textContent = `${st.done} of ${st.total} matches · ${fmtTime(st.elapsed)} elapsed`;
    POLL_T = setTimeout(poll, 500);
  } else if (st.status === 'done') { $('last-btn').style.display = ''; showResults(); }
  else if (st.status === 'error') { $('e-text').textContent = st.error || '(no details)'; showView('v-error'); }
  else if (st.status === 'stopped') { toast('Simulation stopped.'); goHome(); }
}
async function stopJob() { await api('/api/stop', {}); setTimeout(poll, 300); }

/* ───────────────────────── results ───────────────────────── */
let R = null, CUR_MATCH = 0;
const MCACHE = {};
let R_RUN = '';                        // '' = the last run, else the saved run's id
const runQ = () => R_RUN ? '?run=' + encodeURIComponent(R_RUN) : '';
async function showResults(run) {
  clearTimeout(POLL_T);
  R_RUN = typeof run === 'string' ? run : '';
  try { R = await api('/api/results' + runQ()); } catch (e) { toast(e.message, true); showView('v-home'); return; }
  if (R.captaincy_by) R.captaincy = (mpOn() && MP.team && R.captaincy_by[MP.team]) || null;   // two players: your own report
  $('r-mp').style.display = mpOn() && R.mode === 'mp' && !R_RUN ? '' : 'none';
  for (const k in MCACHE) delete MCACHE[k];
  showView('v-results');
  $('last-btn').style.display = '';
  const fmt = R.format.toUpperCase();
  RTEAMS = [...new Set([...(R.teams || []), ...R.fixtures.flatMap(f => f.teams)])];
  setDisplayTeams(RTEAMS);
  const lead = R.kind === 'series' ? (R.winner || '') : R.winner;
  $('r-hero').setAttribute('style', lead ? tStyle(lead) : '');
  $('r-kick').textContent = `${fmt} · ${compName(R.format, R.competition)} conditions ${R.year} · ${R.best_of > 1 ? `best of ${R.best_of} · ` : ''}${R.fixtures.length} match${R.fixtures.length === 1 ? '' : 'es'}`;
  $('r-title').innerHTML = R.kind === 'series' ? esc(dnText(R.result, RTEAMS)) : `${badge(R.winner)} ${esc(dn(R.winner))} win the tournament`;
  $('r-sub').innerHTML = `${esc(dnt(R.title || ''))}<span class="full-only"> · replay code ${esc(R.seed)}</span>`;
  const sv = (META.saved || []).find(s => s.id === R_RUN);
  $('r-save').style.display = R_RUN || R.career ? 'none' : '';
  $('r-career').style.display = R.career ? '' : 'none';
  if (R.career) $('r-saved').textContent = `${R.career.name} · season ${R.career.season}`;
  if (!R.career) $('r-saved').textContent = sv ? `Saved run: ${sv.name} (${sv.saved})` : '';
  const pos = R.player_of_series;
  $('r-pos').style.display = pos ? '' : 'none';
  if (pos) $('r-pos').innerHTML = `${avatar(pos.name, pos.team, 'sm')} Player of the ${R.fixtures.length === 1 ? 'match' : 'series'} <b>${esc(pos.name)}</b> <span class="muted">${esc(dn(pos.team))}</span>`;
  CUR_MATCH = 0;
  $('tab-board').style.display = R.draft ? '' : 'none';
  if (R.draft) drawBoard($('r-board'), R.draft.teams, R.draft.board, R.draft.user || (mpOn() && MP.team) || null);
  $('tab-board').textContent = R.draft && R.draft.auction ? 'Auction squads' : 'Draft board';
  renderSummary(); renderMatchSelect(); renderStatsTables(); renderMVP();
  /* one match shows a match: the match centre, without the series tabs */
  const single = R.fixtures.length === 1;
  ['p-summary', 'p-bat', 'p-bowl', 'p-mvp'].forEach(id => { document.querySelector(`.tab[data-pane="${id}"]`).style.display = single ? 'none' : ''; });
  $('r-tabs').style.display = single && !R.draft ? 'none' : '';
  document.querySelector('#p-matches .mnav').style.display = single ? 'none' : '';
  openTab(single ? 'p-matches' : 'p-summary');
}
function openTab(id) {
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('on', t.dataset.pane === id));
  document.querySelectorAll('.pane').forEach(p => p.classList.toggle('on', p.id === id));
  if (id === 'p-matches') showMatch(CUR_MATCH);
}
let RTEAMS = [];
const teamCell = t => `<span class="tcell">${badge(t, 'sm')}<span>${esc(dn(t))}</span></span>`;
const dnt = s => dnText(s, RTEAMS);
function formOf(team) {
  const ko = new Set((R.knockouts || []).map(k => k.match_no));
  return R.fixtures.filter(f => !ko.has(f.match_no) && f.teams.includes(team)).slice(-5)
    .map(f => `<i class="fm ${!f.winner ? 'n' : f.winner === team ? 'w' : 'l'}" title="M${f.match_no}: ${esc(dnt(f.result))}" data-match="${f.match_no}">${!f.winner ? '–' : f.winner === team ? 'W' : 'L'}</i>`).join('');
}
function seriesBoard() {
  const [a, b] = R.teams;
  const strip = R.fixtures.map(f => `<a class="sm-res" data-match="${f.match_no}" title="${esc(dnt(f.result))}" style="${f.winner ? tStyle(f.winner) : ''}">
    <small>M${f.match_no}</small>${f.winner ? badge(f.winner, 'sm') : '<span class="badge sm tie">T</span>'}</a>`).join('');
  return `<div class="card sboard"><div class="sb-side" style="${tStyle(a)}">${badge(a, 'lg')}<b>${esc(dn(a))}</b></div>
    <div class="sb-mid"><div class="sb-sc"><span class="${R.score[a] > R.score[b] ? 'win' : ''}">${R.score[a]}</span><i>–</i><span class="${R.score[b] > R.score[a] ? 'win' : ''}">${R.score[b]}</span></div>
      <div class="sb-strip">${strip}</div></div>
    <div class="sb-side r" style="${tStyle(b)}">${badge(b, 'lg')}<b>${esc(dn(b))}</b></div></div>`;
}
function champBanner() {
  const ru = R.runner_up;
  return `<div class="card champ" style="${tStyle(R.winner)}"><div class="trophy">🏆</div>${badge(R.winner, 'lg')}
    <div><div class="kicker">Champions</div><div class="cn">${esc(dn(R.winner))}</div>
    <div class="muted">${ru ? `beat ${esc(dn(ru))}${R.knockouts.length ? ' in the final' : ''}` : ''}${!R.knockouts.length ? ' · top of the table' : ''}</div></div></div>`;
}
function bracketHTML() {
  if (!R.knockouts.length) return '';
  const stages = [];
  R.knockouts.forEach(k => { let s = stages.find(x => x.name === k.stage); if (!s) stages.push(s = {name: k.stage, list: []}); s.list.push(k); });
  const fx = n => R.fixtures.find(f => f.match_no === n) || {};
  return `<div class="sec-h"><h2>Knockouts</h2></div><div class="bracket">${stages.map(s => `<div class="kcol"><div class="kicker">${esc(s.name)}</div>${s.list.map(k => {
    const f = fx(k.match_no), sc = f.scores || [];
    return `<a class="card kmatch" data-match="${k.match_no}">${k.teams.map((t, i) => `<div class="kt ${f.winner === t ? 'win' : f.winner ? 'lose' : ''}">${badge(t, 'sm')}<span>${esc(dn(t))}</span>
      <b>${esc((sc.find(x => x.startsWith(t + ' ')) || '').slice(t.length + 1))}</b></div>`).join('')}<div class="kr">${esc(dnt(k.result))}</div></a>`; }).join('')}</div>`).join('')}</div>`;
}
function perfCard(title, rows, val, sub) {
  return `<div class="card perf"><div class="kicker">${title}</div>${rows.length ? rows.map((r, i) => `<div class="prow ${i ? '' : 'top'}">
    <span class="rk">${i + 1}</span>${avatar(r.name, r.team)}<div class="what"><b>${esc(r.name)}</b><span>${esc(dn(r.team))} · ${sub(r)}</span></div>
    <div class="v">${val(r)}</div></div>`).join('') : '<div class="muted small">–</div>'}</div>`;
}
function renderSummary() {
  const el = $('p-summary');
  let h = '';
  if (R.kind === 'series') h += seriesBoard();
  else {
    h += champBanner();
    for (const label of Object.keys(R.tables))
      h += `<div class="sec-h"><h2>${label === 'League' ? 'Points table' : 'Group ' + esc(label)}</h2></div><div class="tbl pts" data-table="${esc(label)}"></div>`;
    h += bracketHTML();
  }
  if (R.captaincy) h += `<div class="card pad" style="margin-top:20px">${captaincyHTML(R.captaincy)}</div>`;
  const poms = R.batting.filter(r => r.pom).sort((a, b) => b.pom - a.pom).slice(0, 5);
  h += `<div class="sec-h"><h2>Top performers</h2></div><div class="tops">
    ${perfCard('Most runs', R.batting.slice(0, 5), r => r.runs, r => `avg ${fmtNum(r.average, 1)} · SR ${fmtNum(r.strike_rate, 1)}`)}
    ${perfCard('Most wickets', R.bowling.slice(0, 5), r => r.wickets, r => `avg ${fmtNum(r.average, 1)} · econ ${fmtNum(r.economy, 2)}`)}
    ${perfCard('Player of the match awards', poms, r => r.pom, r => `${r.runs} runs`)}</div>`;
  h += recordsHTML(R.records) + '<div class="sec-h"><h2>All results</h2></div><div class="tbl" id="res-table"></div>';
  el.innerHTML = h;
  if (R.kind !== 'series') {
    const per = R.knockouts.length ? (R.settings.knockout === 'final' ? (Object.keys(R.tables).length > 1 ? 1 : 2) : (Object.keys(R.tables).length > 1 ? 2 : 4)) : 1;
    for (const [label, rows] of Object.entries(R.tables)) {
      table(el.querySelector(`[data-table="${CSS.escape(label)}"]`), [
        {k: 'pos', label: '#', num: true}, {k: 'team', label: 'Team', html: r => teamCell(r.team)}, {k: 'played', label: 'P', num: true},
        {k: 'won', label: 'W', num: true, html: r => `<span class="w">${r.won}</span>`},
        {k: 'lost', label: 'L', num: true, html: r => `<span class="l">${r.lost}</span>`},
        {k: 'tied', label: 'T', num: true}, {k: 'nrr', label: 'NRR', num: true, f: r => (r.nrr >= 0 ? '+' : '') + r.nrr.toFixed(3)},
        {k: 'points', label: 'Pts', num: true, html: r => `<b class="pts-n">${r.points}</b>`},
        {k: 'form', label: 'Last 5', nosort: true, html: r => `<span class="formg">${formOf(r.team)}</span>`},
        {k: 'for', label: 'For', nosort: true}, {k: 'against', label: 'Against', nosort: true},
      ], rows, {rowClass: r => r.pos <= per && R.knockouts.length ? 'q' : ''});
    }
  }
  table($('res-table'), [
    {k: 'match_no', label: '#', num: true}, {k: 'stage', label: 'Stage'},
    {k: 'scores', label: 'Scores', nosort: true, html: r => r.scores.map(x => { const t = r.teams.find(t => x.startsWith(t + ' '));
      return t ? `<span class="tcell">${badge(t, 'sm')}<span class="num">${esc(x.slice(t.length + 1))}</span></span>` : esc(x); }).join(' ')},
    {k: 'result', label: 'Result', html: r => `<span class="res-t">${esc(dnt(r.result))}</span>`},
    {k: 'player_of_match', label: 'Player of the match'},
  ], R.fixtures, {onRow: r => { CUR_MATCH = R.fixtures.indexOf(r); openTab('p-matches'); }});
}
function recordsHTML(rec) {
  if (!rec) return '';
  const card = (title, list, fmt) => list && list.length ? `<div class="card rec"><b>${title}</b><ol>${list.slice(0, 5).map(x =>
    `<li><a data-match="${x.match_no}">${fmt(x)}</a></li>`).join('')}</ol></div>` : '';
  const m = x => ` <span class="muted">· M${x.match_no}</span>`;
  const cards = [
    card('Highest totals', rec.highest_totals, x => `<b>${x.runs}/${x.wickets}</b> ${esc(dn(x.team))} <span class="muted">v ${esc(dn(x.vs))}</span>${m(x)}`),
    card('Lowest all-out totals', rec.lowest_all_out, x => `<b>${x.runs}</b> ${esc(dn(x.team))} <span class="muted">v ${esc(dn(x.vs))} (${x.overs} ov)</span>${m(x)}`),
    card('Highest scores', rec.highest_scores, x => `<b>${x.runs}${x.not_out ? '*' : ''}</b> ${esc(x.name)} <span class="muted">(${x.balls}b) v ${esc(dn(x.vs))}</span>${m(x)}`),
    card('Best bowling', rec.best_bowling, x => `<b>${x.wickets}/${x.runs}</b> ${esc(x.name)} <span class="muted">v ${esc(dn(x.vs))}</span>${m(x)}`),
    card('Fastest fifties', rec.fastest_fifties, x => `<b>${x.balls} balls</b> ${esc(x.name)}${m(x)}`),
    card('Fastest hundreds', rec.fastest_hundreds, x => `<b>${x.balls} balls</b> ${esc(x.name)}${m(x)}`),
    card('Biggest wins by runs', rec.biggest_wins_by_runs, x => `<span class="w">${esc(dn(x.winner))}</span> by ${x.margin} runs <span class="muted">v ${esc(dn(x.loser))}</span>${m(x)}`),
    card('Biggest wins by wickets', rec.biggest_wins_by_wickets, x => `<span class="w">${esc(dn(x.winner))}</span> by ${x.margin} wkt${x.margin === 1 ? '' : 's'} <span class="muted">(${x.balls_left} ball${x.balls_left === 1 ? '' : 's'} left)</span>${m(x)}`),
    card('Closest finishes', [...(rec.super_overs || []).map(x => ({...x, so: true})), ...(rec.narrowest_wins_by_runs || []), ...(rec.narrowest_chases || [])]
      .sort((a, b) => (a.so ? -1 : 0) - (b.so ? -1 : 0) || (a.margin ?? 0) - (b.margin ?? 0)).slice(0, 5),
      x => x.so ? `<span class="d">Super over</span> ${esc(dn(x.winner))} beat ${esc(dn(x.loser))}${m(x)}` : `${esc(dn(x.winner))} ${esc(dnt(x.text).split(' won ')[1] || '')}${m(x)}`),
  ].join('');
  return cards ? `<div class="sec-h"><h2>Records</h2></div><div class="tops recs">${cards}</div>` : '';
}

/* match viewer */
function renderMatchSelect() {
  fillSelect($('m-sel'), R.fixtures.map((m, i) => ({v: i, t: `${m.stage === 'Match ' + m.match_no ? 'Match ' + m.match_no : `Match ${m.match_no} · ${m.stage}`}: ${m.teams.map(dn).join(' v ')}`})));
}
function initMatchNav() {
  $('m-prev').onclick = () => showMatch(CUR_MATCH - 1);
  $('m-next').onclick = () => showMatch(CUR_MATCH + 1);
  $('m-sel').onchange = () => showMatch(+$('m-sel').value);
  document.addEventListener('keydown', e => {
    if (!$('p-matches').classList.contains('on') || !$('v-results').classList.contains('on')) return;
    if (['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement.tagName)) return;
    if (e.key === 'ArrowLeft') showMatch(CUR_MATCH - 1);
    if (e.key === 'ArrowRight') showMatch(CUR_MATCH + 1);
  });
}
async function showMatch(i) {
  const M = R.fixtures;
  i = Math.max(0, Math.min(M.length - 1, i)); CUR_MATCH = i;
  const f = M[i];
  $('m-sel').value = i; $('m-prev').disabled = i === 0; $('m-next').disabled = i === M.length - 1;
  $('m-body').innerHTML = '<div class="muted">Loading…</div>';
  if (!MCACHE[f.match_no]) MCACHE[f.match_no] = api('/api/match/' + f.match_no + runQ());
  const d = await MCACHE[f.match_no];
  if (CUR_MATCH !== i) return;
  MC = {c: d.card, d, f, inn: 0};
  drawMatchCentre();
}

/* match centre: score hero, then Summary / Scorecard / Ball by ball / Charts / Your calls */
let MC = null, MC_TAB = 'sum';
const oversNum = o => { const [a, b] = String(o).split('.').map(Number); return a + (b || 0) / 6; };
const overOf = o => { const [a, b] = String(o).split('.'); return b && +b ? +a + 1 : +a; };
const ballCls = b => b === 'W' || /W/.test(b) ? 'bw' : /wd|nb|lb|\db$|^b$/.test(b) ? 'bx' : b === '4' ? 'b4' : b === '6' ? 'b6' : b === '.' || b === '0' ? 'dot' : '';
const chip = (b, sm) => `<span class="ball ${sm ? 'sm' : ''} ${ballCls(b)}">${b === '.' ? '•' : esc(b)}</span>`;
function pairCols(teams) {
  const hex = h => { const n = parseInt(h.slice(1), 16); return [n >> 16, (n >> 8) & 255, n & 255]; };
  const cs = teams.map(t => tcol(t).hi);
  if (cs.length === 2 && cs.every(x => /^#[0-9a-f]{6}$/i.test(x))) {
    const [a, b] = cs.map(hex), d = Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
    if (d < 140) { const alt = tcol(teams[1]).a; cs[1] = /^#[0-9a-f]{6}$/i.test(alt) && alt.toLowerCase() !== '#000000' ? alt : '#e3b341'; }
  }
  return cs;
}
function drawMatchCentre() {
  const {c, d, f} = MC, mainInns = c.innings.slice(0, 2), teams = c.teams;
  const pom = c.player_of_match || {}, cond = c.conditions || {}, res = c.result || {};
  TEAM_COL = pairCols(mainInns.map(i => i.team));
  const scoreOf = t => mainInns.find(i => i.team === t);
  const side = (t, r) => { const i = scoreOf(t), won = res.winner === t;
    return `<div class="mc-side ${r ? 'r' : ''} ${res.winner && !won ? 'lost' : ''}" style="${tStyle(t)}">${badge(t, 'md')}
      <div><div class="nm">${esc(dn(t))}</div><div class="sc">${i ? `${i.runs}${i.wickets < 10 ? '/' + i.wickets : ''}<small>${esc(i.overs)} ov${i.target ? ' · target ' + i.target : ''}</small>` : '<small>did not bat</small>'}</div>
      ${won ? '<span class="won">WON</span>' : ''}</div></div>`; };
  const tabs = [['sum', 'Summary'], ['sc', 'Scorecard'], ['bb', 'Ball by ball'], ['ch', 'Charts'], ...(c.captaincy ? [['calls', 'Your calls']] : [])];
  if (!tabs.some(t => t[0] === MC_TAB)) MC_TAB = 'sum';
  $('m-body').innerHTML = `<div class="card mc-hero"><div class="teams2">${side(teams[0], false)}
      <div class="mc-mid"><span class="kicker">${esc((c.format || '').toUpperCase())}</span><span>v</span></div>${side(teams[1], true)}</div>
    <div class="mc-res"><span class="r">${esc(dnt(res.text || ''))}</span>
      <span>${esc(f.stage)}</span>${c.venue ? `<span>Venue <b>${esc(c.venue)}</b></span>` : ''}
      <span>Toss <b>${esc(dn(c.toss.winner))}</b>, chose to ${esc(c.toss.decision)}</span><span>Pitch <b>${esc(cond.report || '–')}</b></span>
      ${(c.rain || []).map(t => `<span>&#9730; ${esc(t)}</span>`).join('')}</div></div>
    <div class="subtabs" id="mc-tabs">${tabs.map(([k, l]) => `<button data-t="${k}" class="${k === MC_TAB ? 'on' : ''}">${l}</button>`).join('')}</div>
    <div id="mc-pane"></div>`;
  $('mc-tabs').querySelectorAll('button').forEach(b => b.onclick = () => { MC_TAB = b.dataset.t; drawMatchCentre(); });
  const pane = $('mc-pane');
  if (MC_TAB === 'sum') pane.innerHTML = mcSummary();
  else if (MC_TAB === 'sc') { pane.innerHTML = mcScorecard(); pane.querySelectorAll('[data-inn]').forEach(b => b.onclick = () => { MC.inn = +b.dataset.inn; drawMatchCentre(); }); }
  else if (MC_TAB === 'bb') pane.innerHTML = mcOvers();
  else if (MC_TAB === 'ch') pane.innerHTML = chartsHTML(c);
  else pane.innerHTML = `<div class="card pad">${callsHTML(c)}</div>`;
}
function pomLine(c, pom) {
  const parts = [];
  c.innings.forEach(i => {
    const b = i.batting.find(x => x.id === pom.id && x.batted); if (b) parts.push(`${b.runs}${b.out ? '' : '*'} off ${b.balls}`);
    const w = i.bowling.find(x => x.id === pom.id); if (w) parts.push(`${w.wickets}/${w.runs} (${w.overs} ov)`);
  });
  return parts.join(' and ');
}
function mcSummary() {
  const {c, d} = MC, pom = c.player_of_match || {}, mainInns = c.innings.slice(0, 2);
  const KEEP = new Set(['wicket', 'big_over', 'milestone', 'turning_point', 'end_of_innings', 'partnership']);
  const evs = (c.events || []).filter(e => KEEP.has(e.kind) || !['team_50', 'bowling_change'].includes(e.kind))
    .filter(e => e.kind !== 'partnership' || (e.runs || 0) >= 50 || /\b(50|100|150) partnership/.test(e.text));
  const tl = evs.map(e => { const inn = c.innings[(e.innings || 1) - 1] || {};
    return `<div class="tl ${esc(e.kind)}"><div class="ov">${e.kind === 'end_of_innings' ? '' : esc(e.over)}</div><span class="pt"></span>
      <div class="tx">${esc(dnt(e.text))}${e.score && e.kind !== 'end_of_innings' ? `<span class="s">${esc(tcol(inn.team || '').short)} ${esc(e.score)}</span>` : ''}</div></div>`; }).join('');
  const best = mainInns.flatMap(i => {
    const b = [...i.batting].filter(x => x.batted).sort((x, y) => y.runs - x.runs)[0];
    const w = [...i.bowling].sort((x, y) => y.wickets - x.wickets || x.runs - y.runs)[0];
    return [b && {n: b.name, t: i.team, what: 'Top score', v: `${b.runs}${b.out ? '' : '*'} <small>(${b.balls})</small>`},
            w && {n: w.name, t: i.bowling_team, what: 'Best bowling', v: `${w.wickets}/${w.runs} <small>(${w.overs})</small>`}];
  }).filter(Boolean);
  const imp = c.impact_player ? Object.entries(c.impact_player).map(([t, x]) => `<div class="small muted">Impact Player · ${esc(dn(t))}: <b>${esc(x.in)}</b> for ${esc(x.out)} (${esc(x.when)})</div>`).join('') : '';
  return `<div class="sum-grid"><div>
      ${pom.name ? `<div class="card pom">${avatar(pom.name, pom.team, 'xl')}<div><div class="kicker k">Player of the match</div>
        <div class="nm">${esc(pom.name)}</div><div class="fig">${esc(dn(pom.team))}${pomLine(c, pom) ? ' · ' + esc(pomLine(c, pom)) : ''}</div></div></div>` : ''}
      <div class="card pad report">${esc(dnt(d.report))}${imp ? '<div style="margin-top:8px">' + imp + '</div>' : ''}</div>
      ${tl ? `<div class="card"><div class="kicker" style="padding:16px 20px 4px">Key moments</div><div class="timeline">${tl}</div></div>` : ''}
    </div><div>
      ${winProbHTML(c, true)}
      <div class="card perf"><div class="kicker">Top performers</div>${best.map(x => `<div class="prow">${avatar(x.n, x.t)}
        <div class="what"><b>${esc(x.n)}</b><span>${x.what} · ${esc(dn(x.t))}</span></div><div class="v">${x.v}</div></div>`).join('')}</div>
    </div></div>`;
}
function mcScorecard() {
  const {c} = MC, all = [...c.innings, ...(c.super_overs || []).flatMap(s => s.innings || [])];
  const k = Math.min(MC.inn, all.length - 1), inn = all[k];
  if (!inn) return '<div class="muted">No innings.</div>';
  const t = tcol(inn.team), bat = inn.batting.filter(b => b.batted), top = Math.max(0, ...bat.map(b => b.runs));
  const ex = inn.extras || {}, exT = (ex.b || 0) + (ex.lb || 0) + (ex.w || 0) + (ex.nb || 0) + (ex.pen || 0);
  const dnb = inn.batting.filter(b => !b.batted).map(b => esc(b.name));
  const bestW = Math.max(0, ...inn.bowling.map(b => b.wickets));
  const ov = oversNum(inn.overs), rr = ov ? (inn.runs / ov).toFixed(2) : '–';
  const sw = all.map((i, n) => `<button class="${n === k ? 'on' : ''}" data-inn="${n}" style="${tStyle(i.team)}">${badge(i.team, 'sm')}<span>${n >= c.innings.length ? 'Super over' : esc(dn(i.team))}</span>
    <span class="s">${i.runs}/${i.wickets}</span><span class="small">(${esc(i.overs)})</span></button>`).join('');
  return `<div class="inn-switch">${sw}</div>
    <div class="card"><div class="tblwrap"><table class="sctbl"><tr><th class="l">Batter</th><th class="l hide-s"></th><th>R</th><th>B</th><th class="hide-s">4s</th><th class="hide-s">6s</th><th>SR</th></tr>
    ${bat.map(b => { const sr = b.balls ? 100 * b.runs / b.balls : 0;
      return `<tr class="${b.runs === top && top ? 'hi' : ''}"><td class="l"><b>${esc(b.name)}</b>${b.captain ? '<span class="tag">C</span>' : ''}${b.keeper ? '<span class="tag">WK</span>' : ''}
        <div class="how show-s">${b.out ? esc(b.dismissal) : '<span class="no">not out</span>'}</div></td>
      <td class="l how hide-s">${b.out ? esc(b.dismissal) : '<span class="no">not out</span>'}</td><td class="r">${b.runs}${b.out ? '' : '*'}</td><td>${b.balls}</td>
      <td class="hide-s">${b.fours}</td><td class="hide-s">${b.sixes}</td><td>${b.balls ? sr.toFixed(1) : '–'}<span class="srbar hide-s" style="--c:${t.hi}"><i style="width:${Math.min(100, sr / 3)}%"></i></span></td></tr>`; }).join('')}</table></div>
    <div class="sc-foot"><span>Extras <b>${exT}</b> (b ${ex.b || 0}, lb ${ex.lb || 0}, w ${ex.w || 0}, nb ${ex.nb || 0})</span>
      <span>Total <b>${inn.runs}/${inn.wickets}</b> (${esc(inn.overs)} ov, RR ${rr})</span>${dnb.length ? `<span>Did not bat: ${dnb.join(', ')}</span>` : ''}</div>
    ${inn.fall_of_wickets && inn.fall_of_wickets.length ? `<div class="kicker" style="padding:4px 14px 0">Fall of wickets</div><div class="fowstrip" style="--c:${t.hi}"><div class="line"></div>
      ${inn.fall_of_wickets.map(w => `<div class="w" style="left:${Math.min(100, 100 * w.runs / Math.max(1, inn.runs))}%" title="${esc(w.batter)}: ${w.runs}/${w.wkt} (${esc(w.over)} ov)">${w.wkt}<span>${w.runs}</span></div>`).join('')}</div>` : ''}</div>
    <div class="card" style="margin-top:16px"><div class="tblwrap"><table class="sctbl"><tr><th class="l">Bowler · ${esc(dn(inn.bowling_team))}</th><th>O</th><th class="hide-s">M</th><th>R</th><th>W</th><th>Econ</th><th class="hide-s">Dots</th><th class="hide-s">Extras</th></tr>
    ${inn.bowling.map(b => `<tr class="${b.wickets === bestW && bestW ? 'hi' : ''}"><td class="l"><b>${esc(b.name)}</b></td><td>${esc(b.overs)}</td><td class="hide-s">${b.maidens}</td><td>${b.runs}</td>
      <td class="r">${b.wickets}</td><td>${fmtNum(b.economy, 2)}</td><td class="hide-s">${b.dots ?? '–'}</td><td class="hide-s">${[b.wides ? b.wides + 'w' : '', b.noballs ? b.noballs + 'nb' : ''].filter(Boolean).join(' ') || '–'}</td></tr>`).join('')}</table></div></div>`;
}
function mcOvers() {
  const {c, d} = MC;
  const evAt = (n, o) => (c.events || []).filter(e => e.innings === n && overOf(e.over) === o && ['wicket', 'big_over', 'milestone'].includes(e.kind));
  return `<div class="card">${c.innings.map((inn, i) => ({inn, i})).reverse().map(({inn, i}) => `<div class="ib" style="${tStyle(inn.team)}">${badge(inn.team, 'sm')} ${esc(dn(inn.team))} · ${inn.runs}/${inn.wickets} (${esc(inn.overs)})</div>` +
    [...(inn.overs_log || [])].reverse().map(o => `<div class="over-card"><div class="o"><b>Over ${o.over}</b><span>${esc(o.bowler)}</span></div>
      <div class="balls">${(o.balls || []).map(b => chip(b, true)).join('')}</div>
      <div class="tot"><b>${o.runs}${o.wkts ? ` · ${o.wkts}W` : ''}</b><span>${esc(tcol(inn.team).short)} ${o.total}/${o.wickets}</span></div>
      ${evAt(i + 1, o.over).map(e => `<div class="ev ${e.kind === 'wicket' ? 'w' : ''}">${e.kind === 'wicket' ? 'WICKET · ' : ''}${esc(dnt(e.text))}</div>`).join('')}</div>`).join('')).join('')}</div>
    <details class="card pad" style="margin-top:16px"><summary class="muted">Text scorecard and innings log</summary><pre class="sc">${esc(d.text)}</pre></details>`;
}
function winProbHTML(c, small) {
  const inns = c.innings.filter(i => i.overs_log && i.overs_log.length).slice(0, 2);
  const seq = [];
  inns.forEach((inn, k) => inn.overs_log.forEach(o => { if (o.win_prob !== null && o.win_prob !== undefined) seq.push({k, o, p: k === 0 ? o.win_prob : 1 - o.win_prob}); }));
  if (seq.length < 2) return '';
  const W = 460, H = small ? 190 : 240, P = {l: 34, r: 10, t: 12, b: 24}, n1 = inns[0].overs_log.length;
  const X = j => P.l + (W - P.l - P.r) * j / seq.length, Y = p => H - P.b - (H - P.t - P.b) * p;
  const pts = [[0, .5], ...seq.map((s, j) => [j + 1, s.p])];
  const [ca, cb] = TEAM_COL;
  let g = `<defs><linearGradient id="wpg${small ? 's' : ''}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${ca}"/><stop offset=".5" stop-color="#8d9bb5"/><stop offset="1" stop-color="${cb}"/></linearGradient></defs>`;
  g += `<line x1="${P.l}" x2="${W - P.r}" y1="${Y(.5)}" y2="${Y(.5)}" class="target"/>`;
  if (inns[1]) g += `<line x1="${X(n1)}" x2="${X(n1)}" y1="${P.t}" y2="${H - P.b}" class="grid"/>`;
  g += `<polyline fill="none" stroke="url(#wpg${small ? 's' : ''})" stroke-width="2.6" stroke-linejoin="round" points="${pts.map(([j, p]) => `${X(j).toFixed(1)},${Y(p).toFixed(1)}`).join(' ')}"/>`;
  seq.forEach((s, j) => { if (s.o.wkts) g += `<circle cx="${X(j + 1)}" cy="${Y(s.p)}" r="3" fill="${TEAM_COL[s.k]}" class="wkt"><title>${esc(inns[s.k].team)} ${s.o.total}/${s.o.wickets} after ${s.o.over} ov: ${Math.round(100 * s.p)}% for ${esc(inns[0].team)}</title></circle>`; });
  g += `<text x="${P.l + 4}" y="${P.t + 11}" fill="${ca}">${esc(tcol(inns[0].team).short)} winning</text><text x="${P.l + 4}" y="${H - P.b - 5}" fill="${cb}">${esc(tcol((inns[1] || inns[0]).team).short)} winning</text>`;
  g += `<text x="${P.l - 6}" y="${Y(1) + 4}" text-anchor="end">100%</text><text x="${P.l - 6}" y="${Y(.5) + 4}" text-anchor="end">50%</text><text x="${P.l - 6}" y="${Y(0) + 4}" text-anchor="end">0</text>`;
  return `<div class="card chart-card"><h4>Win probability</h4><svg viewBox="0 0 ${W} ${H}" class="chart">${g}</svg></div>`;
}

/* captaincy report (engine/judge.py): the person's calls against the computer's, in runs */
const CALL_LABEL = {toss: 'Toss', xi: 'Playing XI and order', bowler: 'Bowler each over', batter: 'Next batter', impact: 'Impact Player'};
const sgn = v => v === null || v === undefined ? '–' : (v > 0 ? '+' : '') + v.toFixed(1);
function captaincyHTML(r) {
  if (!r) return '';
  const rows = Object.entries(r.kinds).map(([k, v]) => `<tr><td>${CALL_LABEL[k] || k}</td><td>${v.calls}</td><td>${v.changed}</td>
    <td class="${v.runs > 0 ? 'w' : v.runs < 0 ? 'l' : ''}">${v.valued ? sgn(v.runs) : 'not valued'}</td></tr>`).join('');
  const verdict = r.runs > 0 ? 'better than' : r.runs < 0 ? 'worse than' : 'the same as';
  return `<h3>Your captaincy - ${esc(r.team)}</h3><div class="cap-report">
    <p>Over ${r.matches} matches your calls were worth <b class="${r.runs > 0 ? 'w' : r.runs < 0 ? 'l' : ''}">${sgn(r.runs)} runs</b> against the computer's
    (about ${sgn(r.wins)} wins at ${r.runs_per_win} runs a win): ${verdict} the computer captain. Opponent captains: ${esc(r.opponents || 'expert')}.</p>
    <table class="mini"><tr><th>Decision</th><th>Calls</th><th>Different from the computer</th><th>Runs v the computer</th></tr>${rows}</table>
    <p class="muted small">Estimates from the engine's own ratings (expected runs, wickets valued in runs), not the scorecard: a call can be right and still go wrong on the day. Bowlers: this over plus the best way to bowl the rest with the overs left. Batters: the order still to come and the balls each can expect. XI: batting by slot plus the best 20 overs the side can bowl. Toss and Impact Player calls are listed without a value. Each match's calls are on the Matches tab.</p></div>`;
}
function callsHTML(c) {
  const logs = c.captaincy ? Object.entries(c.captaincy) : [];
  return logs.map(([team, log]) => {
    const valued = log.filter(d => d.delta !== null), tot = valued.reduce((a, d) => a + d.delta, 0);
    const diff = log.filter(d => d.changed);
    return `<h3>Your calls for ${esc(dn(team))}: ${sgn(tot)} runs v the computer</h3>
      <p class="muted small">${log.length} calls, ${diff.length} different from the computer's.</p>
      ${diff.length ? `<table class="mini"><tr><th>When</th><th>Decision</th><th>You</th><th>Computer</th><th>Runs</th></tr>${diff.map(d =>
        `<tr><td>${esc(d.when)}</td><td>${CALL_LABEL[d.kind] || d.kind}</td><td>${esc(d.you)}</td><td>${esc(d.computer)}</td>
         <td class="${d.delta > 0 ? 'w' : d.delta < 0 ? 'l' : ''}">${sgn(d.delta)}</td></tr>`).join('')}</table>` : ''}`;
  }).join('');
}

/* charts: run worm, Manhattan, win probability (inline SVG, data from each innings' overs_log) */
let TEAM_COL = ['#4c8dff', '#e3b341'];
function niceMax(v, steps = 5) {
  const raw = Math.max(v, 1) / steps, mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map(m => m * mag).find(s => s >= raw);
  return {max: step * Math.ceil(Math.max(v, 1) / step), step};
}
function svgFrame(W, H, P, xmax, ymax, ystep, xlabel, ylabel, yfmt = v => v) {
  const X = x => P.l + (W - P.l - P.r) * x / xmax, Y = y => H - P.b - (H - P.t - P.b) * y / ymax;
  let g = '';
  for (let y = 0; y <= ymax + 1e-9; y += ystep)
    g += `<line x1="${P.l}" x2="${W - P.r}" y1="${Y(y)}" y2="${Y(y)}" class="grid"/><text x="${P.l - 6}" y="${Y(y) + 4}" text-anchor="end">${yfmt(y)}</text>`;
  const xstep = xmax > 30 ? 10 : 5;
  for (let x = 0; x <= xmax; x += xstep) g += `<text x="${X(x)}" y="${H - P.b + 15}" text-anchor="middle">${x}</text>`;
  g += `<text x="${(P.l + W - P.r) / 2}" y="${H - 3}" text-anchor="middle" class="ax">${xlabel}</text>`;
  g += `<text x="12" y="${(P.t + H - P.b) / 2}" text-anchor="middle" class="ax" transform="rotate(-90 12 ${(P.t + H - P.b) / 2})">${ylabel}</text>`;
  return {X, Y, g};
}
function legend(inns) {
  return `<div class="legend">${inns.map((inn, k) => `<span><i style="background:${TEAM_COL[k]}"></i>${esc(dn(inn.team))}</span>`).join('')}<span><i class="wk"></i>wicket</span></div>`;
}
function chartsHTML(c) {
  const inns = c.innings.filter(i => i.overs_log && i.overs_log.length).slice(0, 2);
  if (!inns.length) return '';
  const W = 560, H = 240, P = {l: 44, r: 12, t: 12, b: 34}, maxOv = inns[0].max_overs || c.overs || 20;
  // worm
  const top = niceMax(Math.max(...inns.map(i => i.runs)));
  let f = svgFrame(W, H, P, maxOv, top.max, top.step, 'Overs', 'Runs');
  let body = f.g;
  inns.forEach((inn, k) => {
    const pts = [[0, 0], ...inn.overs_log.map((o, j) => [j + 1 === inn.overs_log.length && inn.balls % 6 ? (inn.balls) / 6 : o.over, o.total])];
    body += `<polyline fill="none" stroke="${TEAM_COL[k]}" stroke-width="2.2" points="${pts.map(([x, y]) => `${f.X(x).toFixed(1)},${f.Y(y).toFixed(1)}`).join(' ')}"/>`;
    inn.overs_log.forEach((o, j) => { if (o.wkts) body += `<circle cx="${f.X(pts[j + 1][0])}" cy="${f.Y(o.total)}" r="${2.6 + 1.4 * (o.wkts - 1)}" fill="${TEAM_COL[k]}" class="wkt"><title>${esc(inn.team)} ${o.total}/${o.wickets} after ${o.over} ov (${o.wkts} wkt)</title></circle>`; });
  });
  if (inns[1] && inns[1].target) body += `<line x1="${P.l}" x2="${W - P.r}" y1="${f.Y(inns[1].target)}" y2="${f.Y(inns[1].target)}" class="target"/><text x="${W - P.r}" y="${f.Y(inns[1].target) - 4}" text-anchor="end" class="ax">target ${inns[1].target}</text>`;
  const worm = `<svg viewBox="0 0 ${W} ${H}" class="chart">${body}</svg>`;
  // Manhattan
  const perOver = Math.max(...inns.flatMap(i => i.overs_log.map(o => o.runs)));
  const mt = niceMax(perOver + 2, 4);
  f = svgFrame(W, H, P, maxOv, mt.max, mt.step, 'Over', 'Runs in the over');
  body = f.g;
  const slot = (f.X(1) - f.X(0)), bw = Math.max(1, slot * 0.84 / inns.length);
  inns.forEach((inn, k) => inn.overs_log.forEach(o => {
    const x = f.X(o.over - 1) + slot * 0.08 + k * bw, y = f.Y(o.runs);
    body += `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${bw.toFixed(1)}" height="${(f.Y(0) - y).toFixed(1)}" fill="${TEAM_COL[k]}" opacity=".85"><title>${esc(inn.team)} over ${o.over}: ${o.runs} run${o.runs === 1 ? '' : 's'}${o.wkts ? `, ${o.wkts} wkt` : ''} (${esc(o.bowler)})</title></rect>`;
    for (let w = 0; w < o.wkts; w++) body += `<circle cx="${(x + bw / 2).toFixed(1)}" cy="${(y - 5 - w * 7).toFixed(1)}" r="2.7" fill="${TEAM_COL[k]}" class="wkt"/>`;
  }));
  const manhattan = `<svg viewBox="0 0 ${W} ${H}" class="chart">${body}</svg>`;
  return `<div class="charts">${legend(inns)}<div class="chart-grid">
    <div class="chart-box"><h4>Run worm</h4>${worm}</div>
    <div class="chart-box"><h4>Manhattan</h4>${manhattan}</div>${winProbHTML(c, false).replace('card chart-card', 'chart-box')}
    ${inns.map((inn, k) => partnershipChart(inn, k, inns)).join('')}</div></div>`;
}

/* partnerships: one row per wicket, first batter's runs to the left of centre, second's to the right */
const ORD = n => n + (n % 10 === 1 && n % 100 !== 11 ? 'st' : n % 10 === 2 && n % 100 !== 12 ? 'nd' : n % 10 === 3 && n % 100 !== 13 ? 'rd' : 'th');
function partnershipChart(inn, k, inns) {
  const ps = (inn.partnerships || []).filter(p => p.runs || p.balls);
  if (!ps.length) return '';
  const side = Math.max(10, ...inns.flatMap(i => (i.partnerships || []).flatMap(p => p.split)));
  const W = 560, row = 22, top = 8, H = top + ps.length * row + 8, lab = 34, tot = 62, nameW = 112;
  const cx = (lab + W - tot) / 2, half = (W - tot - lab) / 2 - nameW, X = v => half * v / side;
  let g = `<line x1="${cx}" x2="${cx}" y1="${top - 2}" y2="${H - 6}" class="grid"/>`;
  ps.forEach((p, j) => {
    const y = top + j * row, [a, b] = p.split, [na, nb] = p.batters;
    const tip = `${ORD(p.wkt)} wicket: ${p.runs} (${p.balls}b)${p.unbroken ? ' unbroken' : ''} - ${na} ${a}, ${nb} ${b}`;
    g += `<g><title>${esc(tip)}</title>
      <text x="4" y="${y + 14}" class="ax">${ORD(p.wkt)}</text>
      <rect x="${(cx - X(a)).toFixed(1)}" y="${y + 3}" width="${X(a).toFixed(1)}" height="${row - 7}" fill="${TEAM_COL[k]}" opacity=".95"/>
      <rect x="${cx}" y="${y + 3}" width="${X(b).toFixed(1)}" height="${row - 7}" fill="${TEAM_COL[k]}" opacity=".55"/>
      <text x="${(cx - X(a) - 4).toFixed(1)}" y="${y + 14}" text-anchor="end">${esc(na)} ${a}</text>
      <text x="${(cx + X(b) + 4).toFixed(1)}" y="${y + 14}">${b} ${esc(nb)}</text>
      <text x="${W - 2}" y="${y + 14}" text-anchor="end" class="ax">${p.runs}${p.unbroken ? '*' : ''} (${p.balls})</text></g>`;
  });
  return `<div class="chart-box"><h4>Partnerships · ${esc(dn(inn.team))}</h4><svg viewBox="0 0 ${W} ${H}" class="chart">${g}</svg></div>`;
}

/* batting / bowling */
const inningsLine = x => `<b>${x.runs}${x.no ? '*' : ''}</b> <span class="muted">(${x.balls}b)</span> v ${esc(x.opp)}`;
const bowlLine = x => `<b>${x.wkts}/${x.runs}</b> <span class="muted">(${esc(x.overs)} ov)</span> v ${esc(x.opp)}`;
function renderStatsTables() {
  const teams = [...new Set([...R.batting, ...R.bowling].map(r => r.team))].sort();
  ['bat', 'bowl'].forEach(k => { fillSelect($(k + '-team'), [{v: '', t: 'All teams'}, ...teams.map(t => ({v: t, t: dn(t)}))]); $(k + '-q').value = ''; });
  const bat = () => {
    const q = $('bat-q').value.toLowerCase(), t = $('bat-team').value;
    table($('bat-table'), [
      {k: 'name', label: 'Player'}, {k: 'team', label: 'Team', html: r => teamCell(r.team)}, {k: 'matches', label: 'M', num: true}, {k: 'inns', label: 'Inn', num: true},
      {k: 'not_outs', label: 'NO', num: true}, {k: 'runs', label: 'Runs', num: true}, {k: 'balls', label: 'Balls', num: true},
      {k: 'hs', label: 'HS', num: true, sv: r => parseInt(r.hs) + (r.hs.endsWith('*') ? 0.5 : 0), html: r => r.hs_match ? `<a class="mlink" data-match="${r.hs_match}" title="Open match ${r.hs_match}">${esc(r.hs)}</a>` : esc(r.hs)},
      {k: 'average', label: 'Avg', num: true, f: r => fmtNum(r.average, 2)}, {k: 'strike_rate', label: 'SR', num: true, f: r => fmtNum(r.strike_rate, 1)},
      {k: 'hundreds', label: '100', num: true, html: r => popCell(r.hundred_list, 'Hundreds', inningsLine)},
      {k: 'fifties', label: '50', num: true, html: r => popCell(r.fifty_list, 'Fifties', inningsLine)},
      {k: 'fours', label: '4s', num: true}, {k: 'sixes', label: '6s', num: true}, {k: 'ducks', label: '0s', num: true},
      {k: 'catches', label: 'Ct', num: true}, {k: 'stumpings', label: 'St', num: true}, {k: 'pom', label: 'PoM', num: true},
    ], R.batting.filter(r => (!q || r.name.toLowerCase().includes(q)) && (!t || r.team === t)), {sort: {k: 'runs', dir: -1}});
  };
  const bowl = () => {
    const q = $('bowl-q').value.toLowerCase(), t = $('bowl-team').value;
    table($('bowl-table'), [
      {k: 'name', label: 'Player'}, {k: 'team', label: 'Team', html: r => teamCell(r.team)}, {k: 'matches', label: 'M', num: true},
      {k: 'overs', label: 'Overs', num: true, sv: r => r.balls}, {k: 'maidens', label: 'Mdns', num: true},
      {k: 'runs', label: 'Runs', num: true}, {k: 'wickets', label: 'Wkts', num: true},
      {k: 'best', label: 'Best', num: true, sv: r => r.best ? +r.best.split('/')[0] * 1000 - +r.best.split('/')[1] : null,
        html: r => r.best_match ? `<a class="mlink" data-match="${r.best_match}" title="Open match ${r.best_match}">${esc(r.best)}</a>` : esc(r.best || '–')},
      {k: 'average', label: 'Avg', num: true, f: r => fmtNum(r.average, 2)}, {k: 'economy', label: 'Econ', num: true, f: r => fmtNum(r.economy, 2)},
      {k: 'strike_rate', label: 'SR', num: true, f: r => fmtNum(r.strike_rate, 1)}, {k: 'dots', label: 'Dots', num: true},
      {k: 'four_w', label: '4w', num: true}, {k: 'five_w', label: '5w', num: true, html: r => popCell(r.five_list, 'Five-wicket hauls', bowlLine)},
    ], R.bowling.filter(r => (!q || r.name.toLowerCase().includes(q)) && (!t || r.team === t)), {sort: {k: 'wickets', dir: -1}});
  };
  $('bat-table')._sort = null; $('bowl-table')._sort = null;
  $('bat-q').oninput = bat; $('bat-team').onchange = bat; $('bowl-q').oninput = bowl; $('bowl-team').onchange = bowl;
  bat(); bowl();
}

/* MVP race */
let MVP_KIND = 'official';
function renderMVP() {
  const el = $('p-mvp'), alt = MVP_KIND === 'balanced';
  const rows = (alt ? R.mvp.balanced : R.mvp.official) || [];
  const formula = alt
    ? '<b>1 point per run + 25 per wicket + 5 per catch or stumping + 25 per team win</b>, plus a strike-rate bonus (half the runs scored above the tournament\'s average rate) and an economy bonus (half the runs saved below it). An alternative view; the player of the series is picked by the official measure.'
    : 'The engine\'s own measure: <b>win probability added</b>, summed over every ball a player batted or bowled (1.00 = one whole match won). It also picks the player of each match and of the series.';
  const legend = alt ? 'Bar: <span style="color:var(--blue)">■ runs</span> <span style="color:var(--green)">■ wickets</span> <span style="color:#c678dd">■ catches</span> <span style="color:var(--amber)">■ team wins</span>.' : '';
  el.innerHTML = `<div class="seg" id="mvp-kind">
      <button data-k="official" class="${alt ? '' : 'on'}">Official</button>
      <button data-k="balanced" class="${alt ? 'on' : ''}">Balanced</button></div> <span class="muted small">Points</span>
    <p class="muted small simple-only" style="margin:10px 0 12px">${alt ? 'Runs, wickets, catches and team wins.' : 'How much each player swung the result.'}</p>
    <p class="muted small full-only" style="margin:10px 0 12px">${formula} ${legend}</p>
    <div class="filters"><input type="text" id="mvp-q" placeholder="Search player…"><select id="mvp-team"></select></div>
    <div class="tbl" id="mvp-table"></div>`;
  el.querySelectorAll('#mvp-kind button').forEach(b => b.onclick = () => { MVP_KIND = b.dataset.k; renderMVP(); });
  fillSelect($('mvp-team'), [{v: '', t: 'All teams'}, ...[...new Set(rows.map(r => r.team))].sort().map(t => ({v: t, t}))]);
  const max = Math.max(1, ...rows.map(r => r.bat_pts + r.bowl_pts + r.field_pts + r.win_pts));
  const draw = () => {
    const q = $('mvp-q').value.toLowerCase(), t = $('mvp-team').value;
    table($('mvp-table'), [
      {k: 'rank', label: '#', num: true}, {k: 'name', label: 'Player'}, {k: 'team', label: 'Team', html: r => teamCell(r.team)},
      {k: 'runs', label: 'Runs', num: true}, {k: 'wickets', label: 'Wkts', num: true}, {k: 'catches', label: 'Ct/St', num: true},
      ...(alt ? [
        {k: 'sr_bonus', label: 'SR bonus', num: true, f: r => r.sr_bonus.toFixed(0)}, {k: 'econ_bonus', label: 'Econ bonus', num: true, f: r => r.econ_bonus.toFixed(0)},
        {k: 'balanced', label: 'Points', num: true, html: r => `<b>${r.balanced.toFixed(0)}</b>`},
        {k: 'bar', label: 'Made up of', nosort: true, html: r => `<div class="mvpbar" title="Runs ${r.bat_pts} · Wickets ${r.bowl_pts} · Catches ${r.field_pts} · Team wins ${r.win_pts}">
          <i class="b1" style="width:${100 * r.bat_pts / max}%"></i><i class="b2" style="width:${100 * r.bowl_pts / max}%"></i><i class="b4" style="width:${100 * r.field_pts / max}%"></i><i class="b3" style="width:${100 * r.win_pts / max}%"></i></div>`},
      ] : [
        {k: 'impact', label: 'Impact (wins added)', num: true, html: r => `<b>${(r.impact >= 0 ? '+' : '') + r.impact.toFixed(2)}</b>`},
      ]),
    ], rows.filter(r => (!q || r.name.toLowerCase().includes(q)) && (!t || r.team === t)),
    {sort: {k: alt ? 'balanced' : 'impact', dir: -1}, limit: 300, rowClass: r => r.rank === 1 ? 'gold' : ''});
  };
  $('mvp-table')._sort = null; $('mvp-q').oninput = draw; $('mvp-team').onchange = draw; draw();
}

/* ───────────────────────── team builder ───────────────────────── */
const PLAYERS = {};
let BSEL = [], BEDIT = null;
const ROLES = ['Batter', 'WK', 'All-rounder', 'Pace', 'Spin'];
function initBuilder() {
  ['bp-search', 'bp-team', 'bp-role'].forEach(id => $(id).oninput = drawBuilderPool);
  $('b-fmt').onchange = loadBuilderPool;
  $('b-save').onclick = saveTeam;
  drawBuilderSquad();
}
async function loadBuilderPool() {
  const fmt = $('b-fmt').value;
  if (!PLAYERS[fmt]) {
    $('bp-table').innerHTML = '<div class="muted" style="padding:12px">Loading player database…</div>';
    try { PLAYERS[fmt] = await api('/api/players?fmt=' + fmt); }
    catch (e) { $('bp-table').innerHTML = `<div class="err" style="padding:12px">${esc(e.message)}</div>`; return; }
  }
  const P = PLAYERS[fmt];
  fillSelect($('bp-team'), [{v: '', t: 'All teams'}, ...[...new Set(P.map(p => p.team))].filter(Boolean).sort().map(t => ({v: t, t}))], true);
  fillSelect($('bp-role'), [{v: '', t: 'All roles'}, ...ROLES.map(r => ({v: r, t: r}))], true);
  drawBuilderPool(); drawBuilderSquad();
}
function drawBuilderPool() {
  const P = PLAYERS[$('b-fmt').value];
  if (!P) return;
  const q = $('bp-search').value.toLowerCase(), t = $('bp-team').value, role = $('bp-role').value, chosen = new Set(BSEL.map(p => p.id));
  const rows = P.filter(p => !chosen.has(p.id) && (!q || p.name.toLowerCase().includes(q)) && (!t || p.team === t) && (!role || p.role === role));
  const full = BSEL.length >= 15;
  table($('bp-table'), [
    {k: 'add', label: '', nosort: true, html: () => `<button class="pick" data-act="add" ${full ? 'disabled' : ''}>Add</button>`},
    {k: 'name', label: 'Player'}, {k: 'team', label: 'Team'}, {k: 'role', label: 'Role'}, {k: 'kind', label: 'Bowling'},
    {k: 'bat_avg', label: 'Bat avg*', num: true, f: r => fmtNum(r.bat_avg, 1)}, {k: 'bat_sr', label: 'SR*', num: true, f: r => fmtNum(r.bat_sr, 1)},
    {k: 'econ', label: 'Econ*', num: true, f: r => r.bowl_balls >= 120 ? fmtNum(r.econ, 2) : '–', sv: r => r.bowl_balls >= 120 ? r.econ : null},
    {k: 'bowl_avg', label: 'Bowl avg*', num: true, f: r => r.bowl_balls >= 120 ? fmtNum(r.bowl_avg, 1) : '–', sv: r => r.bowl_balls >= 120 ? r.bowl_avg : null},
    {k: 'bat_balls', label: 'Balls faced', num: true}, {k: 'bowl_balls', label: 'Balls bowled', num: true},
    {k: 'first', label: 'Career', f: r => r.first ? `${r.first}–${r.last}` : '–'},
  ], rows, {limit: 250, sort: {k: 'bat_balls', dir: -1}, empty: 'No players match',
    onClick: r => { if (BSEL.length < 15) { BSEL.push({id: r.id, name: r.name, team: r.team, role: r.role}); drawBuilderSquad(); drawBuilderPool(); } }});
  $('bp-table').insertAdjacentHTML('beforeend', '<div class="muted small" style="padding:8px">* Ratings expressed as expected numbers in modern full-member international conditions (opposition- and era-adjusted).</div>');
}
function drawBuilderSquad() {
  const counts = Object.fromEntries(ROLES.map(r => [r, 0]));
  BSEL.forEach(p => counts[p.role] = (counts[p.role] || 0) + 1);
  $('b-roles').innerHTML = ROLES.map(r => `<span class="role ${counts[r] ? 'ok' : ''}">${r} ${counts[r] || 0}</span>`).join('');
  $('b-squad').innerHTML = BSEL.map((p, i) => `<li>${i + 1}. ${esc(p.name)} <span>${esc(p.team || '')} · ${esc(p.role || '')} <button class="x" data-i="${i}" style="padding:0 6px;margin-left:6px">✕</button></span></li>`).join('') || '<li class="muted">Add players from the table</li>';
  $('b-squad').querySelectorAll('button').forEach(b => b.onclick = () => { BSEL.splice(+b.dataset.i, 1); drawBuilderSquad(); drawBuilderPool(); });
  $('b-count').textContent = `${BSEL.length} players selected (11–15 needed)` + (BEDIT ? ` · editing “${BEDIT}”` : '');
  $('b-save').disabled = BSEL.length < 11;
  $('b-save').textContent = BEDIT ? 'Save changes' : 'Save team';
}
function drawSavedTeams() {
  $('b-teams').innerHTML = META.teams.map((t, i) => `<div class="teamrow"><div>${esc(t.name)} <span>(${t.players.length})</span></div>
    <div class="acts"><button class="chip-btn" data-edit="${i}">Edit</button><button class="chip-btn" data-del="${i}">Delete</button></div></div>`).join('') || '<div class="muted small" style="padding:6px">No saved teams</div>';
  $('b-teams').querySelectorAll('[data-edit]').forEach(b => b.onclick = () => {
    const t = META.teams[+b.dataset.edit];
    BEDIT = t.name; $('b-name').value = t.name;
    const P = PLAYERS[$('b-fmt').value] || [];
    BSEL = t.players.map(p => { const x = P.find(q => q.id === p.id); return {id: p.id, name: p.name, team: x ? x.team : '', role: x ? x.role : ''}; });
    drawBuilderSquad(); drawBuilderPool();
  });
  $('b-teams').querySelectorAll('[data-del]').forEach(b => b.onclick = async () => {
    const t = META.teams[+b.dataset.del];
    if (!confirm(`Delete the team “${t.name}”?`)) return;
    const res = await api('/api/team/delete', {name: t.name});
    META.teams = res.teams; fillTeams(); toast(`Deleted “${t.name}”.`);
  });
}
async function saveTeam() {
  $('b-err').textContent = '';
  const name = $('b-name').value.trim();
  try {
    const res = await api('/api/team', {name, players: BSEL, replace: BEDIT});
    META.teams = res.teams; fillTeams();
    toast(`Saved “${name}” — it is now in the Match / Series and Tournament lists.`);
    BSEL = []; BEDIT = null; $('b-name').value = ''; drawBuilderSquad(); drawBuilderPool();
  } catch (e) { $('b-err').textContent = e.message; }
}

/* ───────────────────────── match links + popovers (from the Test sim) ───────────────────────── */
function openMatchN(n) {
  const i = R.fixtures.findIndex(m => m.match_no === n);
  if (i < 0) return;
  hidePop(true); CUR_MATCH = i; openTab('p-matches');
  $('v-results').scrollTop = 0;
}
document.addEventListener('click', e => {
  const a = e.target.closest('[data-match]');
  if (a) { e.preventDefault(); openMatchN(+a.dataset.match); return; }
  const p = e.target.closest('.pop');
  if (p) { showPop(p); return; }
  if (!e.target.closest('#popover')) hidePop(true);
});
const POPS = new Map(); let POP_ID = 0, POP_T = null;
function popCell(list, title, line) {
  list = list || [];
  if (!list.length) return '0';
  const id = ++POP_ID;
  POPS.set(id, `<div class="pop-title">${esc(title)} — click to open the match</div>` +
    list.map(x => `<a class="pop-item" data-match="${x.n}">${line(x)}<span class="muted">Match ${x.n}</span></a>`).join(''));
  return `<span class="pop" data-pop="${id}">${list.length}</span>`;
}
function showPop(el) {
  clearTimeout(POP_T);
  const box = $('popover'); box.innerHTML = POPS.get(+el.dataset.pop) || '';
  box.style.display = 'block';
  const r = el.getBoundingClientRect(), w = box.offsetWidth, h = box.offsetHeight;
  let left = Math.min(window.innerWidth - w - 10, Math.max(10, r.left + r.width / 2 - w / 2));
  let top = r.bottom + 6; if (top + h > window.innerHeight - 10) top = Math.max(10, r.top - h - 6);
  box.style.left = left + 'px'; box.style.top = top + 'px';
}
function hidePop(now) {
  clearTimeout(POP_T);
  if (now) { $('popover').style.display = 'none'; return; }
  POP_T = setTimeout(() => $('popover').style.display = 'none', 250);
}
document.addEventListener('mouseover', e => {
  const p = e.target.closest('.pop');
  if (p) showPop(p); else if (e.target.closest('#popover')) clearTimeout(POP_T);
});
document.addEventListener('mouseout', e => {
  if (e.target.closest('.pop') || e.target.closest('#popover')) hidePop(false);
});
document.addEventListener('scroll', () => hidePop(true), true);

init().catch(e => { document.body.innerHTML = `<div style="padding:30px;color:#f85149">Could not start the UI: ${esc(e.message)}</div>`; });
