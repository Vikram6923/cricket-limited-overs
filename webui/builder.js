'use strict';
/* Team Builder: pick a squad from the player pool and save it. */

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
