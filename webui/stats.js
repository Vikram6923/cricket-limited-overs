'use strict';
/* Batting, bowling and MVP tables of a run. */

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
      ...(R.format === 'test' ? [{k: 'best_match_figures', label: 'Best match', num: true,
        sv: r => r.best_match_figures ? +r.best_match_figures.split('/')[0] * 1000 - +r.best_match_figures.split('/')[1] : null,
        html: r => r.best_match_no ? `<a class="mlink" data-match="${r.best_match_no}" title="Open match ${r.best_match_no}">${esc(r.best_match_figures)}</a>` : '–'}]
        : [{k: 'four_w', label: '4w', num: true}]), {k: 'five_w', label: '5w', num: true, html: r => popCell(r.five_list, 'Five-wicket hauls', bowlLine)},
      ...(R.format === 'test' ? [{k: 'ten_w', label: '10w', num: true}] : []),
    ], R.bowling.filter(r => (!q || r.name.toLowerCase().includes(q)) && (!t || r.team === t)), {sort: {k: 'wickets', dir: -1}});
  };
  $('bat-table')._sort = null; $('bowl-table')._sort = null;
  $('bat-q').oninput = bat; $('bat-team').onchange = bat; $('bowl-q').oninput = bowl; $('bowl-team').onchange = bowl;
  bat(); bowl();
}

/* MVP race */
let MVP_KIND = 'official';
function renderMVP() {
  const tp = R.mvp.kind === 'test_points';          // Tests: one ranking, by points (no win probability yet)
  const el = $('p-mvp'), alt = tp || MVP_KIND === 'balanced';
  const rows = (alt ? R.mvp.balanced : R.mvp.official) || [];
  const formula = tp ? '<b>Runs</b> (worth more in a low-scoring match) <b>+ a wicket at the era\'s runs per wicket + 5 per catch or stumping + 25 for a win</b>, added up over the series. It picks the player of each match and of the series.' : alt
    ? '<b>1 point per run + 25 per wicket + 5 per catch or stumping + 25 per team win</b>, plus a strike-rate bonus (half the runs scored above the tournament\'s average rate) and an economy bonus (half the runs saved below it). An alternative view; the player of the series is picked by the official measure.'
    : 'The engine\'s own measure: <b>win probability added</b>, summed over every ball a player batted or bowled (1.00 = one whole match won). It also picks the player of each match and of the series.';
  const legend = alt ? 'Bar: <span style="color:var(--blue)">■ runs</span> <span style="color:var(--green)">■ wickets</span> <span style="color:#c678dd">■ catches</span> <span style="color:var(--amber)">■ team wins</span>.' : '';
  el.innerHTML = `<div class="seg" id="mvp-kind"${tp ? ' hidden' : ''}>
      <button data-k="official" class="${alt ? '' : 'on'}">Official</button>
      <button data-k="balanced" class="${alt ? 'on' : ''}">Balanced</button></div> <span class="muted small">Points</span>
    <button type="button" class="info simple-only" id="mvp-info" title="What the points mean" aria-expanded="false">i</button>
    <div class="mvp-why muted small simple-only" id="mvp-why" hidden>${tp ? '<div>Points for runs, wickets, catches and wins.</div>' : `<div><b>Official:</b> how much each player swung the result.</div>
      <div><b>Balanced:</b> points for runs, wickets, catches and team wins.</div>`}</div>
    <p class="muted small full-only" style="margin:10px 0 12px">${formula} ${legend}</p>
    <div class="filters"><input type="text" id="mvp-q" placeholder="Search player…"><select id="mvp-team"></select></div>
    <div class="tbl" id="mvp-table"></div>`;
  el.querySelectorAll('#mvp-kind button').forEach(b => b.onclick = () => { MVP_KIND = b.dataset.k; renderMVP(); });
  $('mvp-info').onclick = () => { const w = $('mvp-why'); w.hidden = !w.hidden; $('mvp-info').setAttribute('aria-expanded', String(!w.hidden)); };
  fillSelect($('mvp-team'), [{v: '', t: 'All teams'}, ...[...new Set(rows.map(r => r.team))].sort().map(t => ({v: t, t}))]);
  const max = Math.max(1, ...rows.map(r => r.bat_pts + r.bowl_pts + r.field_pts + r.win_pts));
  const draw = () => {
    const q = $('mvp-q').value.toLowerCase(), t = $('mvp-team').value;
    table($('mvp-table'), [
      {k: 'rank', label: '#', num: true}, {k: 'name', label: 'Player'}, {k: 'team', label: 'Team', html: r => teamCell(r.team)},
      {k: 'runs', label: 'Runs', num: true}, {k: 'wickets', label: 'Wkts', num: true}, {k: 'catches', label: 'Ct/St', num: true},
      ...(alt ? [
        ...(tp ? [] : [{k: 'sr_bonus', label: 'SR bonus', num: true, f: r => r.sr_bonus.toFixed(0)}, {k: 'econ_bonus', label: 'Econ bonus', num: true, f: r => r.econ_bonus.toFixed(0)}]),
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
