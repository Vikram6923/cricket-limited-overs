'use strict';
/* Results: the summary of a run (tables, knockouts, records) and opening a match. */

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
  const fmt = fmtLabel(R.format), tests = R.format === 'test';
  RTEAMS = [...new Set([...(R.teams || []), ...R.fixtures.flatMap(f => f.teams)])];
  setDisplayTeams(RTEAMS);
  const lead = R.kind === 'series' ? (R.winner || '') : R.winner;
  $('r-hero').setAttribute('style', lead ? tStyle(lead) : '');
  const single = R.fixtures.length === 1;
  $('r-kick').textContent = `${fmt} · ${compName(R.format, R.competition)} conditions ${R.year}${R.best_of > 1 ? (tests ? (R.fixtures.length < R.best_of ? ` · ${R.best_of}-Test series, stopped once decided` : '') : ` · best of ${R.best_of}`) : ''}${single ? '' : ` · ${R.fixtures.length} ${tests ? 'Tests' : 'matches'}`}${tests && R.host ? ` · in ${R.host}` : ''}`;
  $('r-title').innerHTML = R.kind === 'series' ? esc(dnText(R.result, RTEAMS)) : `${badge(R.winner)} ${esc(dn(R.winner))} win the ${R.wtc ? 'World Test Championship' : 'tournament'}`;
  /* one match: the scoreboard below names the teams, so no "India v Australia" line (6.8) */
  $('r-sub').textContent = single ? '' : dnt(R.title || '');
  $('r-sub').style.display = single ? 'none' : '';
  /* the replay code lives behind Run details (i), Full only */
  $('r-details').hidden = true; $('r-info').setAttribute('aria-expanded', 'false');
  $('r-details').innerHTML = `Replay code <b>${esc(R.seed)}</b> · type it under More options to play this run again.`;
  $('r-info').onclick = () => { const d = $('r-details'); d.hidden = !d.hidden; $('r-info').setAttribute('aria-expanded', String(!d.hidden)); };
  const sv = (META.saved || []).find(s => s.id === R_RUN);
  $('r-save').style.display = R_RUN || R.career ? 'none' : '';
  $('r-career').style.display = R.career ? '' : 'none';
  if (R.career) $('r-saved').textContent = `${R.career.name} · season ${R.career.season}`;
  if (!R.career) $('r-saved').textContent = sv ? `Saved run: ${sv.name} (${sv.saved})` : '';
  const pos = single ? null : R.player_of_series;   // one match: the Summary's player of the match card says it
  $('r-pos').style.display = pos ? '' : 'none';
  if (pos) $('r-pos').innerHTML = `${avatar(pos.name, pos.team, 'sm')} Player of the ${R.fixtures.length === 1 ? 'match' : 'series'} <b>${esc(pos.name)}</b> <span class="muted">${esc(dn(pos.team))}</span>`;
  CUR_MATCH = 0;
  $('tab-board').style.display = R.draft ? '' : 'none';
  if (R.draft) drawBoard($('r-board'), R.draft.teams, R.draft.board, R.draft.user || (mpOn() && MP.team) || null);
  $('tab-board').textContent = R.draft && R.draft.auction ? 'Auction squads' : 'Draft board';
  renderSummary(); renderMatchSelect(); renderStatsTables(); renderMVP();
  /* results fit the run: one match shows the match centre without the series tabs;
     a series of 2 has no Best players (records and the MVP race need 3 matches or more) */
  ['p-summary', 'p-bat', 'p-bowl', 'p-mvp'].forEach(id => { document.querySelector(`.tab[data-pane="${id}"]`).style.display = single ? 'none' : ''; });
  if (R.fixtures.length < 3) document.querySelector('.tab[data-pane="p-mvp"]').style.display = 'none';
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
    <small>M${f.match_no}</small>${f.winner ? badge(f.winner, 'sm') : '<span class="badge sm tie">' + (R.format === 'test' ? 'D' : 'T') + '</span>'}</a>`).join('');
  return `<div class="card sboard"><div class="sb-side" style="${tStyle(a)}">${badge(a, 'lg')}<b>${esc(dn(a))}</b></div>
    <div class="sb-mid"><div class="sb-sc"><span class="${R.score[a] > R.score[b] ? 'win' : ''}">${R.score[a]}</span><i>–</i><span class="${R.score[b] > R.score[a] ? 'win' : ''}">${R.score[b]}</span></div>
      ${R.draws ? `<div class="muted small">${R.draws} drawn</div>` : ''}<div class="sb-strip">${strip}</div></div>
    <div class="sb-side r" style="${tStyle(b)}">${badge(b, 'lg')}<b>${esc(dn(b))}</b></div></div>`;
}
function champBanner() {
  const ru = R.runner_up, d = R.domestic;
  const final = eliteKO().some(k => k.stage === 'Final');
  const extra = [R.promoted ? `${esc(dn(R.promoted))} promoted from the Plate` : '', R.relegated ? `${esc(dn(R.relegated))} relegated` : '',
    d && d.real ? `real ${esc(d.season)}: ${esc(d.real.winner)}` : ''].filter(Boolean).join(' · ');
  return `<div class="card champ" style="${tStyle(R.winner)}"><div class="trophy">🏆</div>${badge(R.winner, 'lg')}
    <div><div class="kicker">Champions</div><div class="cn">${esc(dn(R.winner))}</div>
    <div class="muted">${ru ? `beat ${esc(dn(ru))}${final ? ' in the final' : ''}` : ''}${!R.knockouts.length ? ' · top of the table' : ''}</div>
    ${extra ? `<div class="muted small">${extra}</div>` : ''}</div></div>`;
}
/* the Plate's knockouts have their own section; the main bracket shows the Elite ones */
const isPlate = k => /^Plate/.test(k.stage);
const eliteKO = () => (R.knockouts || []).filter(k => !isPlate(k));
function bracketHTML(list = eliteKO(), title = 'Knockouts') {
  if (!list.length) return '';
  const stages = [];
  /* numbered ties of one round share a column ("Quarter-final 1".."4" -> "Quarter-finals"); IPL playoffs keep theirs */
  const round = st => { const m = /^(.*(?:quarter-final|Quarter-final|Semi-final|semi-final)) \d+$/.exec(st); return m ? m[1] + 's' : st; };
  list.forEach(k => { const n = round(k.stage); let s = stages.find(x => x.name === n); if (!s) stages.push(s = {name: n, list: []}); s.list.push(k); });
  const fx = n => R.fixtures.find(f => f.match_no === n) || {};
  return `<div class="sec-h"><h2>${esc(title)}</h2></div><div class="bracket">${stages.map(s => `<div class="kcol"><div class="kicker">${esc(s.name)}</div>${s.list.map(k => {
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
    if (R.format === 'test') h += `<div class="hint" style="margin:6px 0 0">12 points a win, 6 a tie, 4 a draw. PCT: the share of the points played for that were won. RpW: runs made a wicket over runs conceded a wicket (the tie-break).${R.knockouts.length ? ' A drawn knockout goes to the side ahead on first innings, else to the higher-placed side.' : ''}</div>`;
    if (R.wtc) h += '<div class="sec-h"><h2>Series</h2></div><div class="tbl" id="wtc-series"></div>';
    for (const label of Object.keys(R.super_league || {}))
      h += `<div class="sec-h"><h2>${esc(label)}</h2></div><div class="tbl pts" data-table="${esc(label)}"></div>`;
    h += bracketHTML();
    if (R.plate) {
      for (const label of Object.keys(R.plate.tables))
        h += `<div class="sec-h"><h2>${esc(label)}</h2></div><div class="tbl pts" data-table="${esc(label)}"></div>`;
      h += bracketHTML(R.knockouts.filter(isPlate), 'Plate knockouts');
    }
  }
  if (R.captaincy) h += `<div class="card pad" style="margin-top:20px">${captaincyHTML(R.captaincy)}</div>`;
  const poms = R.batting.filter(r => r.pom).sort((a, b) => b.pom - a.pom).slice(0, 5);
  const big = R.fixtures.length >= 3;               // awards and records only mean something over 3 matches or more
  h += `<div class="sec-h"><h2>Top performers</h2></div><div class="tops">
    ${perfCard('Most runs', R.batting.slice(0, 5), r => r.runs, r => `avg ${fmtNum(r.average, 1)} · SR ${fmtNum(r.strike_rate, 1)}`)}
    ${perfCard('Most wickets', R.bowling.slice(0, 5), r => r.wickets, r => `avg ${fmtNum(r.average, 1)} · econ ${fmtNum(r.economy, 2)}`)}
    ${big ? perfCard('Player of the match awards', poms, r => r.pom, r => `${r.runs} runs`) : ''}</div>`;
  h += (big ? recordsHTML(R.records) : '') + '<div class="sec-h"><h2>All results</h2></div><div class="tbl" id="res-table"></div>';
  el.innerHTML = h;
  if (R.kind !== 'series') {
    /* a side "went through" if it played on after its group: a later round-robin stage or a knockout */
    const sl = R.super_league || {};
    const onward = (from, ko) => new Set([...Object.values(from).flatMap(rows => rows.map(r => r.team)), ...ko.flatMap(k => k.teams)]);
    const thru = {};
    Object.keys(R.tables).forEach(l => thru[l] = onward(sl, eliteKO()));
    const slKO = new Set(eliteKO().flatMap(k => k.teams));
    Object.keys(sl).forEach(l => thru[l] = slKO);
    if (R.plate) { const pk = new Set(R.knockouts.filter(isPlate).flatMap(k => k.teams).concat(R.plate.to_elite_knockouts || []));
      Object.keys(R.plate.tables).forEach(l => thru[l] = pk); }
    const all = {...R.tables, ...sl, ...(R.plate ? R.plate.tables : {})};
    for (const [label, rows] of Object.entries(all)) {
      table(el.querySelector(`[data-table="${CSS.escape(label)}"]`), [
        {k: 'pos', label: '#', num: true}, {k: 'team', label: 'Team', html: r => teamCell(r.team)}, {k: 'played', label: 'P', num: true},
        {k: 'won', label: 'W', num: true, html: r => `<span class="w">${r.won}</span>`},
        {k: 'lost', label: 'L', num: true, html: r => `<span class="l">${r.lost}</span>`},
        ...(R.format === 'test' ? [{k: 'drawn', label: 'D', num: true}, {k: 'tied', label: 'T', num: true},
            {k: 'points', label: 'Pts', num: true, html: r => `<b class="pts-n">${r.points}</b>`},
            {k: 'pct', label: 'PCT', num: true, f: r => r.pct.toFixed(1)}, {k: 'nrr', label: 'RpW', num: true, f: r => r.nrr.toFixed(3)}]
          : [{k: 'tied', label: 'T', num: true}, {k: 'nrr', label: 'NRR', num: true, f: r => (r.nrr >= 0 ? '+' : '') + r.nrr.toFixed(3)},
            {k: 'points', label: 'Pts', num: true, html: r => `<b class="pts-n">${r.points}</b>`}]),
        {k: 'form', label: 'Last 5', nosort: true, html: r => `<span class="formg">${formOf(r.team)}</span>`},
        {k: 'for', label: 'For', nosort: true}, {k: 'against', label: 'Against', nosort: true},
      ], rows, {rowClass: r => thru[label].has(r.team) ? 'q' : (r.team === R.relegated ? 'rel' : '')});
    }
  }
  if (R.wtc && $('wtc-series')) table($('wtc-series'), [
    {k: 'home', label: 'Home', html: r => teamCell(r.home)}, {k: 'away', label: 'Away', html: r => teamCell(r.away)},
    {k: 'res', label: 'Result', nosort: true, html: r => { const [h, a] = r.score;
      return esc(r.winner ? `${dn(r.winner)} won ${Math.max(h, a)}-${Math.min(h, a)}` : `Drawn ${h}-${a}`) + (r.draws ? ` <span class="muted small">(${r.draws} drawn)</span>` : ''); }},
  ], R.wtc.series, {onRow: r => { CUR_MATCH = R.fixtures.findIndex(f => f.match_no === r.matches[0]); openTab('p-matches'); }});
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
  const card = (title, list, fmt, max = 5) => list && list.length ? `<div class="card rec"><b>${title}</b><ol>${list.slice(0, max).map(x =>
    `<li><a data-match="${x.match_no}">${fmt(x)}</a></li>`).join('')}</ol></div>` : '';
  const m = x => ` <span class="muted">· M${x.match_no}</span>`;
  const H = rec.hundreds || {}, plural = (n, w) => `${n} ${w}${n === 1 ? '' : 's'}`;
  const sc = x => `<b>${x.runs}${x.not_out ? '*' : ''}</b> ${esc(x.name)} <span class="muted">(${x.balls}b) v ${esc(dn(x.vs))}</span>${m(x)}`;
  const cards = [
    card('Highest totals', rec.highest_totals, x => `<b>${x.runs}/${x.wickets}</b> ${esc(dn(x.team))} <span class="muted">v ${esc(dn(x.vs))}</span>${m(x)}`),
    card('Lowest all-out totals', rec.lowest_all_out, x => `<b>${x.runs}</b> ${esc(dn(x.team))} <span class="muted">v ${esc(dn(x.vs))} (${x.overs} ov)</span>${m(x)}`),
    card('Highest scores', rec.highest_scores, x => `<b>${x.runs}${x.not_out ? '*' : ''}</b> ${esc(x.name)} <span class="muted">(${x.balls}b) v ${esc(dn(x.vs))}</span>${m(x)}`),
    card('Best bowling', rec.best_bowling, x => `<b>${x.wickets}/${x.runs}</b> ${esc(x.name)} <span class="muted">v ${esc(dn(x.vs))}</span>${m(x)}`),
    card(`Hundreds: ${H.hundreds || 0}` + (H.doubles ? `, ${plural(H.doubles, 'double')}` : '') + (H.triples ? `, ${plural(H.triples, 'triple')}` : ''), H.list, sc),
    card('A hundred in each innings', rec.hundred_in_each_innings, x => `<b>${x.scores.join(' &amp; ')}</b> ${esc(x.name)} <span class="muted">v ${esc(dn(x.vs))}</span>${m(x)}`),
    card('Carried the bat', rec.carried_bat, x => `<b>${x.runs}*</b> ${esc(x.name)} <span class="muted">out of ${x.total} v ${esc(dn(x.vs))}</span>${m(x)}`),
    card('Longest innings', rec.longest_innings, x => `<b>${x.balls} balls</b> ${esc(x.name)} <span class="muted">${x.runs}${x.not_out ? '*' : ''} v ${esc(dn(x.vs))}</span>${m(x)}`),
    card('Best match bowling', rec.best_match_bowling, x => `<b>${x.wickets}/${x.runs}</b> ${esc(x.name)} <span class="muted">(${x.innings.join(' &amp; ')}) v ${esc(dn(x.vs))}</span>${m(x)}`),
    card('Ten wickets in a match', rec.ten_wicket_matches, x => `<b>${x.wickets}/${x.runs}</b> ${esc(x.name)} <span class="muted">v ${esc(dn(x.vs))}</span>${m(x)}`),
    card('Hat-tricks', rec.hat_tricks, x => `<b>${esc(x.name)}</b> <span class="muted">v ${esc(dn(x.vs))}</span>${m(x)}`),
    card('Best partnership for each wicket', rec.best_partnerships, x => `<b>${x.runs}${x.unbroken ? '*' : ''}</b> ${esc(x.batters.join(' and '))} <span class="muted">${esc(dn(x.team))}</span>${m(x)}`, 10),
    card('Highest successful chases', rec.highest_successful_chases, x => `<b>${x.runs}/${x.wickets}</b> ${esc(dn(x.team))} <span class="muted">v ${esc(dn(x.vs))}</span>${m(x)}`),
    card('Fastest fifties', rec.fastest_fifties, x => `<b>${x.balls} balls</b> ${esc(x.name)}${m(x)}`),
    card('Fastest hundreds', rec.fastest_hundreds, x => `<b>${x.balls} balls</b> ${esc(x.name)}${m(x)}`),
    card('Wins by an innings', rec.biggest_wins_by_an_innings, x => `<span class="w">${esc(dn(x.winner))}</span> by an innings and ${x.margin} run${x.margin === 1 ? '' : 's'} <span class="muted">v ${esc(dn(x.loser))}</span>${m(x)}`),
    card('Biggest wins by runs', rec.biggest_wins_by_runs, x => `<span class="w">${esc(dn(x.winner))}</span> by ${x.margin} runs <span class="muted">v ${esc(dn(x.loser))}</span>${m(x)}`),
    card('Biggest wins by wickets', rec.biggest_wins_by_wickets, x => `<span class="w">${esc(dn(x.winner))}</span> by ${x.margin} wkt${x.margin === 1 ? '' : 's'} <span class="muted">${x.balls_left === undefined ? 'v ' + esc(dn(x.loser)) : `(${x.balls_left} ball${x.balls_left === 1 ? '' : 's'} left)`}</span>${m(x)}`),
    card('Wins by wickets', rec.wins_by_wickets, x => `<span class="w">${esc(dn(x.winner))}</span> by ${x.margin} wkt${x.margin === 1 ? '' : 's'} <span class="muted">v ${esc(dn(x.loser))}</span>${m(x)}`),
    card('Closest finishes', [...(rec.super_overs || []).map(x => ({...x, so: true})), ...(rec.narrowest_wins_by_runs || []), ...(rec.narrowest_chases || []), ...(rec.narrowest_wins_by_wickets || [])]
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
