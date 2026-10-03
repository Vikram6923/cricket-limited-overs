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
function showView(id) { document.querySelectorAll('.view').forEach(v => v.classList.toggle('on', v.id === id)); }
const fmtTime = s => { s = Math.round(s); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; };
const fmtNum = (v, d) => v === null || v === undefined || v === '' ? '–' : (typeof v === 'number' && d !== undefined ? v.toFixed(d) : v);
function fillSelect(sel, items, keep) {
  const old = keep ? sel.value : null;
  sel.innerHTML = items.map(i => typeof i === 'string' ? `<option>${esc(i)}</option>` : `<option value="${esc(i.v)}">${esc(i.t)}</option>`).join('');
  if (old !== null && [...sel.options].some(o => o.value === old)) sel.value = old;
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

async function init() {
  META = await api('/api/meta');
  document.querySelectorAll('.mode').forEach(b => b.onclick = () => setMode(b.dataset.mode));
  document.querySelectorAll('.tab').forEach(t => t.onclick = () => openTab(t.dataset.pane));
  $('c-fmt').onchange = () => { fillConditions(); };
  $('c-comp').onchange = checkYear; $('c-year').oninput = checkYear;
  $('c-vsearch').oninput = filterVenues;
  fillSelect($('t-ko'), META.knockouts.map(k => ({v: k.id, t: k.label})));
  ['t-rounds', 't-groups', 't-ko'].forEach(id => $(id).onchange = updateTournamentTotal);
  $('t-search').oninput = filterTeams;
  fillConditions(); fillTeams(); initBuilder(); initMatchNav();
  $('go-btn').onclick = start;
  if (META.has_results) { $('last-btn').style.display = ''; $('home-note').textContent = 'Results from your last run are still available — click “View last results”.'; }
  if (META.job && META.job.status === 'running') poll();
}

function setMode(m) {
  MODE = m;
  document.querySelectorAll('.mode').forEach(b => b.classList.toggle('on', b.dataset.mode === m));
  document.querySelectorAll('.form').forEach(f => f.classList.toggle('on', f.id === 'f-' + m));
  const b = m === 'builder';
  $('go-wrap').style.display = b ? 'none' : ''; $('cond').style.display = b ? 'none' : '';
  $('go-err').textContent = '';
  if (b) { showView('v-builder'); loadBuilderPool(); }
  else if ($('v-builder').classList.contains('on')) showView('v-home');
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
  fillSelect($('s-t1'), names, true); fillSelect($('s-t2'), names, true);
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
    `<label data-name="${esc(t.name.toLowerCase())}"><input type="checkbox" value="${esc(t.name)}" ${checked.has(t.name) || (first && / T20 2024$/.test(t.name)) ? 'checked' : ''}> ${esc(t.name)} <span class="muted small">(${t.players.length})</span></label>`).join('');
  $('t-list').querySelectorAll('input').forEach(i => i.onchange = updateTournamentTotal);
  updateTournamentTotal(); drawSavedTeams();
}
function showRoster(selId, outId) {
  const t = META.teams.find(t => t.name === $(selId).value);
  $(outId).textContent = t ? t.players.map(p => p.name).join(', ') + (t.players.length > 11 ? ` — ${t.players.length} players, the XI is picked per match` : '') : '';
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

/* ───────────────────────── start / poll ───────────────────────── */
function payload() {
  const base = {mode: MODE, fmt: $('c-fmt').value, comp: $('c-comp').value, year: +$('c-year').value,
    venues: [...$('c-venues').selectedOptions].map(o => o.value), seed: $('c-seed').value.trim()};
  if (MODE === 'series') return {...base, team1: $('s-t1').value, team2: $('s-t2').value, matches: +$('s-n').value};
  return {...base, teams: [...document.querySelectorAll('#t-list input:checked')].map(i => i.value),
    rounds: +$('t-rounds').value, groups: +$('t-groups').value, knockout: $('t-ko').value};
}
async function start() {
  $('go-err').textContent = ''; $('go-btn').disabled = true;
  try { await api('/api/run', payload()); poll(); }
  catch (e) { $('go-err').textContent = e.message; $('go-btn').disabled = false; }
}
let POLL_T = null;
async function poll() {
  clearTimeout(POLL_T);
  let st;
  try { st = await api('/api/status'); } catch (e) { POLL_T = setTimeout(poll, 1500); return; }
  const running = st.status === 'running';
  $('status-pill').textContent = running ? 'Running' : 'Idle';
  $('status-pill').classList.toggle('run', running);
  $('go-btn').disabled = running;
  if (running) {
    showView('v-running');
    $('run-title').textContent = st.title || 'Simulating…';
    $('run-bar').style.width = (st.total ? Math.round(100 * st.done / st.total) : 0) + '%';
    $('run-count').textContent = `${st.done} of ${st.total} matches · ${fmtTime(st.elapsed)} elapsed`;
    POLL_T = setTimeout(poll, 500);
  } else if (st.status === 'done') { $('last-btn').style.display = ''; showResults(); }
  else if (st.status === 'error') { $('e-text').textContent = st.error || '(no details)'; showView('v-error'); }
  else if (st.status === 'stopped') { toast('Simulation stopped.'); showView('v-home'); }
}
async function stopJob() { await api('/api/stop', {}); setTimeout(poll, 300); }

/* ───────────────────────── results ───────────────────────── */
let R = null, CUR_MATCH = 0;
const MCACHE = {};
async function showResults() {
  clearTimeout(POLL_T);
  try { R = await api('/api/results'); } catch (e) { toast(e.message, true); showView('v-home'); return; }
  for (const k in MCACHE) delete MCACHE[k];
  showView('v-results');
  const fmt = R.format.toUpperCase();
  $('r-title').textContent = R.kind === 'series' ? R.result : `${R.winner} won the tournament`;
  $('r-sub').textContent = `${fmt} · ${R.title || ''} · ${R.fixtures.length} match${R.fixtures.length === 1 ? '' : 'es'} · conditions: ${R.competition} ${R.year} · seed ${R.seed}`;
  const pos = R.player_of_series;
  $('r-pos').style.display = pos ? '' : 'none';
  if (pos) $('r-pos').textContent = `Player of the series: ${pos.name} (${pos.team})`;
  CUR_MATCH = 0;
  renderSummary(); renderMatchSelect(); renderStatsTables(); renderMVP();
  openTab('p-summary');
}
function openTab(id) {
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('on', t.dataset.pane === id));
  document.querySelectorAll('.pane').forEach(p => p.classList.toggle('on', p.id === id));
  if (id === 'p-matches') showMatch(CUR_MATCH);
}
function renderSummary() {
  const el = $('p-summary');
  let h = '';
  if (R.kind === 'series') {
    const [a, b] = R.teams;
    h += `<div class="series-line">${esc(a)} ${R.score[a]} – ${R.score[b]} ${esc(b)}</div>`;
  } else {
    h += `<div class="winner">🏆 ${esc(R.winner)} <span class="muted">beat ${esc(R.runner_up || '')}${R.knockouts.length ? ' in the final' : ' to top the table'}</span></div>`;
    for (const [label, rows] of Object.entries(R.tables)) {
      h += `<h3>${label === 'League' ? 'Points table' : 'Group ' + esc(label)}</h3><div class="tbl" data-table="${esc(label)}"></div>`;
    }
    if (R.knockouts.length) h += '<h3>Knockouts</h3><ul class="ko">' + R.knockouts.map(k =>
      `<li><b>${esc(k.stage)}</b><a class="mlink" data-match="${k.match_no}">${esc(k.result)}</a> <span class="muted">(${esc(k.teams.join(' v '))})</span></li>`).join('') + '</ul>';
  }
  h += '<h3>Top performers</h3><div class="tops">';
  const li = (rows, f) => rows.length ? rows.map(f).join('') : '<li class="muted">–</li>';
  h += `<div class="card"><b>Most runs</b><ol>${li(R.batting.slice(0, 5), r => `<li>${esc(r.name)} <span>${r.runs} @ ${fmtNum(r.average, 1)}, SR ${fmtNum(r.strike_rate, 1)} · ${esc(r.team)}</span></li>`)}</ol></div>`;
  h += `<div class="card"><b>Most wickets</b><ol>${li(R.bowling.slice(0, 5), r => `<li>${esc(r.name)} <span>${r.wickets} @ ${fmtNum(r.average, 1)}, econ ${fmtNum(r.economy, 2)} · ${esc(r.team)}</span></li>`)}</ol></div>`;
  const poms = R.batting.filter(r => r.pom).sort((a, b) => b.pom - a.pom).slice(0, 5);
  h += `<div class="card"><b>Player of the match awards</b><ol>${li(poms, r => `<li>${esc(r.name)} <span>${r.pom} · ${esc(r.team)}</span></li>`)}</ol></div>`;
  h += '</div>' + recordsHTML(R.records) + '<h3>All results</h3><div class="tbl" id="res-table"></div>';
  el.innerHTML = h;
  if (R.kind !== 'series') {
    const per = R.knockouts.length ? (R.settings.knockout === 'final' ? (Object.keys(R.tables).length > 1 ? 1 : 2) : (Object.keys(R.tables).length > 1 ? 2 : 4)) : 1;
    for (const [label, rows] of Object.entries(R.tables)) {
      table(el.querySelector(`[data-table="${CSS.escape(label)}"]`), [
        {k: 'pos', label: '#', num: true}, {k: 'team', label: 'Team'}, {k: 'played', label: 'P', num: true},
        {k: 'won', label: 'W', num: true, html: r => `<span class="w">${r.won}</span>`},
        {k: 'lost', label: 'L', num: true, html: r => `<span class="l">${r.lost}</span>`},
        {k: 'tied', label: 'T', num: true}, {k: 'points', label: 'Pts', num: true, html: r => `<b>${r.points}</b>`},
        {k: 'nrr', label: 'NRR', num: true, f: r => (r.nrr >= 0 ? '+' : '') + r.nrr.toFixed(3)},
        {k: 'for', label: 'For', nosort: true}, {k: 'against', label: 'Against', nosort: true},
      ], rows, {rowClass: r => r.pos <= per && R.knockouts.length ? 'q' : ''});
    }
  }
  table($('res-table'), [
    {k: 'match_no', label: '#', num: true}, {k: 'stage', label: 'Stage'},
    {k: 'scores', label: 'Scores', nosort: true, f: r => r.scores.join('  ·  ')},
    {k: 'result', label: 'Result', html: r => `<span class="w">${esc(r.result)}</span>`},
    {k: 'player_of_match', label: 'Player of the match'},
  ], R.fixtures, {onRow: r => { CUR_MATCH = R.fixtures.indexOf(r); openTab('p-matches'); }});
}
function recordsHTML(rec) {
  if (!rec) return '';
  const card = (title, list, fmt) => list && list.length ? `<div class="card rec"><b>${title}</b><ol>${list.slice(0, 5).map(x =>
    `<li><a data-match="${x.match_no}">${fmt(x)}</a></li>`).join('')}</ol></div>` : '';
  const m = x => ` <span class="muted">· M${x.match_no}</span>`;
  const cards = [
    card('Highest totals', rec.highest_totals, x => `<b>${x.runs}/${x.wickets}</b> ${esc(x.team)} <span class="muted">v ${esc(x.vs)}</span>${m(x)}`),
    card('Lowest all-out totals', rec.lowest_all_out, x => `<b>${x.runs}</b> ${esc(x.team)} <span class="muted">v ${esc(x.vs)} (${x.overs} ov)</span>${m(x)}`),
    card('Highest scores', rec.highest_scores, x => `<b>${x.runs}${x.not_out ? '*' : ''}</b> ${esc(x.name)} <span class="muted">(${x.balls}b) v ${esc(x.vs)}</span>${m(x)}`),
    card('Best bowling', rec.best_bowling, x => `<b>${x.wickets}/${x.runs}</b> ${esc(x.name)} <span class="muted">v ${esc(x.vs)}</span>${m(x)}`),
    card('Fastest fifties', rec.fastest_fifties, x => `<b>${x.balls} balls</b> ${esc(x.name)}${m(x)}`),
    card('Fastest hundreds', rec.fastest_hundreds, x => `<b>${x.balls} balls</b> ${esc(x.name)}${m(x)}`),
    card('Biggest wins by runs', rec.biggest_wins_by_runs, x => `<span class="w">${esc(x.winner)}</span> by ${x.margin} runs <span class="muted">v ${esc(x.loser)}</span>${m(x)}`),
    card('Biggest wins by wickets', rec.biggest_wins_by_wickets, x => `<span class="w">${esc(x.winner)}</span> by ${x.margin} wkt${x.margin === 1 ? '' : 's'} <span class="muted">(${x.balls_left} ball${x.balls_left === 1 ? '' : 's'} left)</span>${m(x)}`),
    card('Closest finishes', [...(rec.super_overs || []).map(x => ({...x, so: true})), ...(rec.narrowest_wins_by_runs || []), ...(rec.narrowest_chases || [])]
      .sort((a, b) => (a.so ? -1 : 0) - (b.so ? -1 : 0) || (a.margin ?? 0) - (b.margin ?? 0)).slice(0, 5),
      x => x.so ? `<span class="d">Super over</span> ${esc(x.winner)} beat ${esc(x.loser)}${m(x)}` : `${esc(x.winner)} ${esc(x.text.split(' won ')[1] || '')}${m(x)}`),
  ].join('');
  return cards ? `<h3>Records</h3><div class="tops recs">${cards}</div>` : '';
}

/* match viewer */
function renderMatchSelect() {
  fillSelect($('m-sel'), R.fixtures.map((m, i) => ({v: i, t: `Match ${m.match_no} · ${m.stage}: ${m.teams.join(' v ')}`})));
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
  if (!MCACHE[f.match_no]) MCACHE[f.match_no] = api('/api/match/' + f.match_no);
  const d = await MCACHE[f.match_no];
  if (CUR_MATCH !== i) return;
  const c = d.card, pom = c.player_of_match || {}, cond = c.conditions || {};
  $('m-body').innerHTML = `<div class="banner">${esc(c.result.text)}</div>
    <div class="meta"><span>${esc(f.stage)}</span>${c.venue ? `<span>Venue: <b>${esc(c.venue)}</b></span>` : ''}
      <span>Toss: <b>${esc(c.toss.winner)}</b>, chose to ${esc(c.toss.decision)}</span>
      <span>Pitch: <b>${esc(cond.report || '')}</b></span>
      ${pom.name ? `<span>Player of the match: <b>${esc(pom.name)}</b></span>` : ''}</div>
    <div class="report">${esc(d.report)}</div>
    <h3>Scorecard and innings log</h3><pre class="sc">${esc(d.text)}</pre>`;
}

/* batting / bowling */
const inningsLine = x => `<b>${x.runs}${x.no ? '*' : ''}</b> <span class="muted">(${x.balls}b)</span> v ${esc(x.opp)}`;
const bowlLine = x => `<b>${x.wkts}/${x.runs}</b> <span class="muted">(${esc(x.overs)} ov)</span> v ${esc(x.opp)}`;
function renderStatsTables() {
  const teams = [...new Set([...R.batting, ...R.bowling].map(r => r.team))].sort();
  ['bat', 'bowl'].forEach(k => { fillSelect($(k + '-team'), [{v: '', t: 'All teams'}, ...teams.map(t => ({v: t, t}))]); $(k + '-q').value = ''; });
  const bat = () => {
    const q = $('bat-q').value.toLowerCase(), t = $('bat-team').value;
    table($('bat-table'), [
      {k: 'name', label: 'Player'}, {k: 'team', label: 'Team'}, {k: 'matches', label: 'M', num: true}, {k: 'inns', label: 'Inn', num: true},
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
      {k: 'name', label: 'Player'}, {k: 'team', label: 'Team'}, {k: 'matches', label: 'M', num: true},
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
      <button data-k="official" class="${alt ? '' : 'on'}">Official (impact)</button>
      <button data-k="balanced" class="${alt ? 'on' : ''}">Balanced ranking</button></div>
    <p class="muted small" style="margin:10px 0 12px">${formula} ${legend}</p>
    <div class="filters"><input type="text" id="mvp-q" placeholder="Search player…"><select id="mvp-team"></select></div>
    <div class="tbl" id="mvp-table"></div>`;
  el.querySelectorAll('#mvp-kind button').forEach(b => b.onclick = () => { MVP_KIND = b.dataset.k; renderMVP(); });
  fillSelect($('mvp-team'), [{v: '', t: 'All teams'}, ...[...new Set(rows.map(r => r.team))].sort().map(t => ({v: t, t}))]);
  const max = Math.max(1, ...rows.map(r => r.bat_pts + r.bowl_pts + r.field_pts + r.win_pts));
  const draw = () => {
    const q = $('mvp-q').value.toLowerCase(), t = $('mvp-team').value;
    table($('mvp-table'), [
      {k: 'rank', label: '#', num: true}, {k: 'name', label: 'Player'}, {k: 'team', label: 'Team'},
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
