'use strict';
/* Fantasy Draft (one person): the form, the draft room and its league. */

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
  const k = Math.max(2, Math.min(16, +$('d-k').value || 2));
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
