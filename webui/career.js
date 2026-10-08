/* Career mode (engine/career.py): one league season after season. The server keeps each career in
   results/careers/<id>/; this page starts or opens one, plays its seasons and sends it to the auction room. */
'use strict';

let CAR = null, CAR_ID = '', CAR_TEAM = '';

/* ───────────── form: new career / your careers ───────────── */
function initCareerForm() {
  fillSelect($('k-league'), META.leagues.map(l => ({v: l.id, t: l.label})));
  const seasons = () => {
    const l = kLeague();
    fillSelect($('k-season'), l ? l.seasons.map(s => ({v: s.season, t: s.season})) : []);
    kTeams();
  };
  $('k-league').onchange = seasons; $('k-season').onchange = kTeams;
  seasons(); drawCareers();
}
const kLeague = () => META.leagues.find(x => x.id === $('k-league').value);
function kTeams() {
  const l = kLeague(), s = l && l.seasons.find(x => x.season === $('k-season').value);
  const teams = s ? s.teams.map(t => t.franchise || t.name) : [];
  fillSelect($('k-user'), [...teams.map(t => ({v: t, t})), {v: '', t: '— none: watch the computer run every team —'}]);
}
function drawCareers() {
  const list = META.careers || [];
  $('k-list').innerHTML = list.length ? list.map(c => `<div class="sv-item" data-id="${esc(c.id)}">
      <b>${esc(c.name)}</b>
      <span class="muted small">${esc(c.league)} · next: ${esc(c.season)} ${c.phase === 'auction' ? 'auction' : 'season'} · ${c.played} season${c.played === 1 ? '' : 's'} played${c.user ? ` · ${esc(c.user)}: ${c.titles} title${c.titles === 1 ? '' : 's'}` : ''}</span>
      <div class="sv-btns"><button class="btn sec" data-a="open">Open</button><button class="btn sec" data-a="delete">Delete</button></div></div>`).join('')
    : '<div class="muted small">No careers yet.</div>';
  $('k-list').querySelectorAll('.sv-item').forEach(el => {
    const id = el.dataset.id, c = list.find(x => x.id === id);
    el.querySelector('[data-a="open"]').onclick = () => openCareer(id);
    el.querySelector('[data-a="delete"]').onclick = async () => {
      if (!confirm(`Delete the career “${c.name}” and all its seasons? This cannot be undone.`)) return;
      META.careers = (await api('/api/career/delete', {id})).careers; drawCareers();
    };
  });
}
async function startCareer() {
  const d = await api('/api/career/new', {league: $('k-league').value, season: $('k-season').value, user: $('k-user').value,
    mega_every: +$('k-mega').value, name: $('k-name').value.trim(), seed: $('k-seed').value.trim()});
  careerLoaded(d);
}
async function openCareer(id) {
  try { careerLoaded(await api('/api/career?id=' + encodeURIComponent(id))); }
  catch (e) { toast(e.message, true); }
}
function careerLoaded(d) {
  CAR = d.state; CAR_ID = d.id; META.careers = d.careers;
  if (!CAR_TEAM || !CAR.teams.includes(CAR_TEAM)) CAR_TEAM = CAR.user || CAR.teams[0];
  drawCareers(); renderCareer();
}

/* ───────────── career dashboard ───────────── */
function renderCareer() {
  const c = CAR, me = c.user;
  showView('v-career'); $('go-btn').disabled = false;
  $('kc-title').textContent = c.name;
  $('kc-sub').textContent = `${c.league_label} from ${c.start} · ${c.history.length} season${c.history.length === 1 ? '' : 's'} played · `
    + `mega auction every ${c.mega_every === 1 ? 'season' : c.mega_every + ' seasons'} · ${c.pool_size} players in the league`
    + (c.real ? '' : ' · past the real seasons: newcomers are made-up players');
  const auction = c.phase === 'auction';
  $('kc-next').innerHTML = auction
    ? `<h3>${esc(c.season)}: ${c.auction_kind === 'mega' ? 'mega auction' : 'mini auction'}</h3>
       <p class="muted small" style="margin:4px 0 8px">${c.auction_kind === 'mega'
         ? 'Every squad is broken up: teams retain up to 6 (₹18/14/11/18/14 cr capped, ₹4 cr uncapped) and get Right to Match cards for the rest.'
         : 'Teams keep their squads at their contract prices or release players; the released, the unsold and the newcomers go under the hammer.'}</p>
       <div class="au-act">${me ? `<button class="btn go" id="kc-auction">Go to the auction</button>` : ''}
       <button class="btn sec" id="kc-auto">${me ? 'Let the computer decide for me' : 'Run the auction'}</button></div>`
    : `<h3>Season ${esc(c.season)}</h3>
       <div class="checks" style="margin:6px 0">
         ${me ? `<label><input type="checkbox" id="kc-cap" ${$('kc-cap') && !$('kc-cap').checked ? '' : 'checked'}> Captain ${esc(me)}</label>` : ''}
         <label><input type="checkbox" id="kc-rain" checked> Rain (DLS)</label></div>
       ${me ? `<div class="fg" style="margin:4px 0 8px"><label>Opponent captains</label><select id="kc-opp">
         <option value="expert">Expert</option><option value="average">Average</option><option value="easy">Easy</option></select></div>` : ''}
       <div class="au-act"><button class="btn go" id="kc-play">▶ Play season ${esc(c.season)}</button></div>`;
  if ($('kc-auction')) $('kc-auction').onclick = careerAuction;
  if ($('kc-auto')) $('kc-auto').onclick = () => careerAuction(true);
  if ($('kc-play')) $('kc-play').onclick = playCareerSeason;
  $('kc-news').innerHTML = c.news.length ? c.news.map(n => `<li>${esc(n)}</li>`).join('') : '<li class="muted">Nothing yet.</li>';
  // honours
  $('kc-hist').innerHTML = c.history.length ? `<tr><th>Season</th><th>Champions</th><th>Runners-up</th>${me ? '<th>' + esc(me) + '</th>' : ''}
      <th>Most runs</th><th>Most wickets</th><th>MVP</th><th></th></tr>` + c.history.slice().reverse().map(h => `<tr>
      <td>${esc(h.season)}</td><td class="${h.champion === me ? 'w' : ''}"><b>${esc(h.champion)}</b></td><td>${esc(h.runner_up || '')}</td>
      ${me ? `<td>${esc(h.user_pos || '')}${h.captaincy !== null && h.captaincy !== undefined ? ` <span class="muted small">(calls ${sgn(h.captaincy)})</span>` : ''}</td>` : ''}
      <td>${h.orange ? `${esc(h.orange.name)} <span class="muted small">${h.orange.runs}</span>` : ''}</td>
      <td>${h.purple ? `${esc(h.purple.name)} <span class="muted small">${h.purple.wkts}</span>` : ''}</td>
      <td>${h.mvp ? esc(h.mvp.name) : ''}</td>
      <td>${h.run ? `<button class="btn sec kc-open" data-run="${esc(h.run)}">Results</button>` : ''}</td></tr>`).join('')
    : '<tr><td class="muted">No seasons played yet.</td></tr>';
  document.querySelectorAll('.kc-open').forEach(b => b.onclick = () => showResults(b.dataset.run));
  const titles = Object.entries(c.titles).sort((a, b) => b[1] - a[1]);
  $('kc-titles').innerHTML = titles.length ? titles.map(([t, n]) => `<li class="${t === me ? 'crease' : ''}">${esc(t)} <span>${'🏆'.repeat(Math.min(n, 10))} ${n}</span></li>`).join('') : '<li class="muted">No titles yet.</li>';
  // squads
  fillSelect($('kc-team'), c.teams.map(t => ({v: t, t: t === me ? `${t} (yours)` : t})));
  $('kc-team').value = CAR_TEAM; $('kc-team').onchange = () => { CAR_TEAM = $('kc-team').value; drawCareerSquad(); };
  drawCareerSquad();
  table($('kc-runs'), [{k: 'name', label: 'Player', html: r => `${esc(r.name)}${r.active ? '' : ' <span class="muted small">retired</span>'}`},
    {k: 'seasons', label: 'Seasons', num: true}, {k: 'matches', label: 'M', num: true}, {k: 'runs', label: 'Runs', num: true},
    {k: 'avg', label: 'Avg', num: true, f: r => fmtNum(r.avg, 1)}, {k: 'sr', label: 'SR', num: true, f: r => fmtNum(r.sr, 1)},
    {k: 'hundreds', label: '100s', num: true}, {k: 'fifties', label: '50s', num: true}, {k: 'hs', label: 'HS', num: true, f: r => r.hs + (r.hs_no ? '*' : '')},
    {k: 'titles', label: 'Titles', num: true}], c.leaders.runs, {sort: {k: 'runs', dir: -1}, empty: 'No matches yet'});
  table($('kc-wkts'), [{k: 'name', label: 'Player', html: r => `${esc(r.name)}${r.active ? '' : ' <span class="muted small">retired</span>'}`},
    {k: 'seasons', label: 'Seasons', num: true}, {k: 'matches', label: 'M', num: true}, {k: 'wkts', label: 'Wkts', num: true},
    {k: 'bowl_avg', label: 'Avg', num: true, f: r => fmtNum(r.bowl_avg, 1)}, {k: 'econ', label: 'Econ', num: true, f: r => fmtNum(r.econ, 2)},
    {k: 'best', label: 'Best', f: r => r.best[0] + '/' + r.best[1]}, {k: 'titles', label: 'Titles', num: true}],
    c.leaders.wkts, {sort: {k: 'wkts', dir: -1}, empty: 'No matches yet'});
}
function drawCareerSquad() {
  const rows = CAR.squads[CAR_TEAM] || [];
  const os = rows.filter(r => r.overseas).length, spent = rows.reduce((a, r) => a + r.price, 0);
  $('kc-squad-sub').textContent = `${rows.length} players, ${os} overseas · contracts ${cr(spent)}`;
  table($('kc-squad'), [
    {k: 'name', label: 'Player', html: r => `${esc(r.name)}${osTag(r)}${r.made_up ? ' <span class="muted small">new</span>' : ''}`},
    {k: 'age', label: 'Age', num: true}, {k: 'nation', label: 'Nation', f: r => (r.nation || '').replace(/^league:.*/, '')},
    {k: 'bat_avg', label: 'Bat avg', num: true, f: r => fmtNum(r.bat_avg, 1)}, {k: 'bat_sr', label: 'SR', num: true, f: r => fmtNum(r.bat_sr, 1)},
    {k: 'econ', label: 'Econ', num: true, f: r => fmtNum(r.econ, 2)}, {k: 'bowl_avg', label: 'Bowl avg', num: true, f: r => fmtNum(r.bowl_avg, 1)},
    {k: 'seasons', label: 'Seasons', num: true}, {k: 'price', label: 'Contract', num: true, f: r => cr(r.price)},
  ], rows, {sort: {k: 'price', dir: -1}, empty: 'No players'});
}
async function careerAuction(auto) {
  try {
    const d = await api('/api/career/auction', {id: CAR_ID, auto: auto === true});
    if (d.state && d.state.phase !== undefined && d.state.teams && d.state.board) { openAuctionRoom(d); return; }
    careerLoaded(d); toast('Auction done: the squads for the new season are set.');
  } catch (e) { toast(e.message, true); }
}
async function careerAuctionDone() {
  try { careerLoaded(await api('/api/career/auction_done', {id: CAR_ID})); toast('Squads saved for the new season.'); }
  catch (e) { $('au-msg').textContent = e.message; }
}
async function playCareerSeason() {
  const me = CAR.user, cap = me && $('kc-cap') && $('kc-cap').checked;
  const impact = CAR.league === 'ipl' && CAR.year >= 2023;
  const body = {mode: 'career', career: CAR_ID, fmt: 't20', rain: $('kc-rain').checked};
  if (cap) { body.captain = me; body.opponents = $('kc-opp').value; body.manual = ['toss', 'xi', 'bowler', 'batter', 'result', ...(impact ? ['impact'] : [])]; CAP.impact = impact; }
  try { await api('/api/run', body); poll(); }
  catch (e) { toast(e.message, true); }
}
