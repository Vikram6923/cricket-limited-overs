'use strict';
/* Test matches in the match centre: both innings of a side in the score, the day-by-day strip, the lead over the
   match in place of the run worm, a Manhattan and the partnerships for each innings. The set-up form's Test
   switches (1 / 2 / 3 / 5 Tests, where the series is played) are here too. */

const isTest = c => !!c && c.format === 'test';
const FMT_LABEL = {t20: 'T20', odi: 'ODI', test: 'Test'};
const fmtLabel = f => FMT_LABEL[f] || String(f || '').toUpperCase();

/* "220 & 310/5d": a side's innings in order, declared and follow-on marked */
const innScore = i => (i.wickets >= 10 ? String(i.runs) : `${i.runs}/${i.wickets}`) + (i.declared ? 'd' : '');
function testScore(c, t) {
  return c.innings.filter(i => i.team === t).map(i => innScore(i) + (i.follow_on ? ' <small>f/o</small>' : '')).join(' <i>&amp;</i> ');
}
/* "IND 1st" for the innings tabs */
function innTag(c, i) {
  const nth = c.innings.filter(x => x.team === i.team).indexOf(i);
  return `${esc(tcol(i.team).short)} ${nth ? '2nd' : '1st'}${i.follow_on ? ' (f/o)' : ''}`;
}
function testHeroLine(c) {
  const d = c.days || [], lost = d.reduce((a, x) => a + (x.lost || 0), 0);
  return `<span>${d.length === c.scheduled_days ? 'Went to' : 'Over on'} <b>day ${d.length}</b></span>` +
    (lost ? `<span>&#9730; <b>${lost}</b> overs lost</span>` : '') +
    (c.conditions && c.conditions.home ? `<span>Home side <b>${esc(dn(c.conditions.home))}</b></span>` : '');
}

/* the day-by-day strip: lunch, tea and stumps of every day, with how the batting side stands */
function dayStripHTML(strip, c) {
  if (!strip || !strip.length) return '';
  const days = [...new Set(strip.map(r => r.day))], lost = Object.fromEntries((c.days || []).map(d => [d.day, d.lost || 0]));
  const none = (c.days || []).filter(d => !d.overs).map(d => d.day);
  const row = r => `<div class="ds-row"><span class="ds-when">${esc(r.label.split(', ')[1])}</span>
    <span class="ds-sc">${badge(r.team, 'sm')}<b>${esc(r.score)}</b></span><span class="ds-pos">${esc(r.position)}</span></div>`;
  const all = [...new Set([...days, ...none])].sort((a, b) => a - b);
  return `<div class="card daystrip"><div class="kicker">Day by day</div>${all.map(d => `<div class="ds-day"><div class="ds-h">Day ${d}
      ${lost[d] ? `<span class="muted small">&#9730; ${lost[d]} overs lost</span>` : ''}</div>
    ${days.includes(d) ? strip.filter(r => r.day === d).map(row).join('') : '<div class="ds-row muted">No play</div>'}</div>`).join('')}</div>`;
}

/* the lead of the side that batted first, over by over through the match: innings shaded, day lines */
function leadChartHTML(c, small) {
  const inns = c.innings.filter(i => i.overs_log && i.overs_log.length);
  if (!inns.length) return '';
  const A = c.innings[0].team, B = c.teams.find(t => t !== A) || '';
  const col = t => TEAM_COL[Math.max(0, c.teams.indexOf(t))];
  const pts = [{x: 0, y: 0}], bands = [], dayLines = [];
  let x = 0, a = 0, b = 0, day = null;
  inns.forEach(inn => {
    const x0 = x; let prev = 0;
    inn.overs_log.forEach(o => {
      if (inn.team === A) a += o.total - prev; else b += o.total - prev;
      prev = o.total;
      if (day !== null && o.day !== day) dayLines.push({x, day: o.day});
      day = o.day; x++;
      pts.push({x, y: a - b, o, inn});
    });
    bands.push({x0, x1: x, inn});
  });
  const W = small ? 460 : 560, H = small ? 200 : 250, P = {l: 40, r: 10, t: 20, b: 24};
  const m = niceMax(Math.max(50, ...pts.map(p => Math.abs(p.y))), 3);
  const X = v => P.l + (W - P.l - P.r) * v / Math.max(1, x), Y = v => (P.t + H - P.b) / 2 - (H - P.t - P.b) / 2 * v / m.max;
  let g = '';
  bands.forEach((bd, k) => {
    g += `<rect x="${X(bd.x0).toFixed(1)}" y="${P.t}" width="${(X(bd.x1) - X(bd.x0)).toFixed(1)}" height="${H - P.t - P.b}" fill="${col(bd.inn.team)}" opacity="${k % 2 ? .05 : .11}"/>`;
    if (X(bd.x1) - X(bd.x0) > 44) g += `<text x="${((X(bd.x0) + X(bd.x1)) / 2).toFixed(1)}" y="${P.t - 6}" text-anchor="middle" fill="${col(bd.inn.team)}">${innTag(c, bd.inn)} ${innScore(bd.inn)}</text>`;
  });
  for (let v = -m.max; v <= m.max + 1e-9; v += m.step) {
    g += `<line x1="${P.l}" x2="${W - P.r}" y1="${Y(v)}" y2="${Y(v)}" class="${v ? 'grid' : 'target'}"/><text x="${P.l - 6}" y="${Y(v) + 4}" text-anchor="end">${Math.abs(v)}</text>`; }
  dayLines.forEach(d => { g += `<line x1="${X(d.x).toFixed(1)}" x2="${X(d.x).toFixed(1)}" y1="${P.t}" y2="${H - P.b}" class="dayline"/>
    <text x="${(X(d.x) + 3).toFixed(1)}" y="${H - P.b + 14}" class="ax">Day ${d.day}</text>`; });
  g += `<text x="${P.l + 3}" y="${H - P.b + 14}" class="ax">Day ${pts[1] ? pts[1].o.day : 1}</text>`;
  g += `<polyline fill="none" stroke="var(--text)" stroke-width="2" stroke-linejoin="round" points="${pts.map(p => `${X(p.x).toFixed(1)},${Y(p.y).toFixed(1)}`).join(' ')}"/>`;
  pts.forEach(p => { if (p.o && p.o.wkts) g += `<circle cx="${X(p.x).toFixed(1)}" cy="${Y(p.y).toFixed(1)}" r="2.2" fill="${col(p.inn.team)}" class="wkt"><title>${esc(p.inn.team)} ${p.o.total}/${p.o.wickets} (over ${p.o.over}, day ${p.o.day}): ${esc(p.y >= 0 ? A : B)} ${p.y ? 'lead by ' + Math.abs(p.y) : 'level'}</title></circle>`; });
  g += `<text x="${W - P.r - 4}" y="${P.t + 12}" text-anchor="end" fill="${col(A)}">${esc(tcol(A).short)} ahead</text>
    <text x="${W - P.r - 4}" y="${H - P.b - 6}" text-anchor="end" fill="${col(B)}">${esc(tcol(B).short)} ahead</text>`;
  return `<div class="card chart-card"><h4>Lead over the match</h4><svg viewBox="0 0 ${W} ${H}" class="chart">${g}</svg></div>`;
}

/* charts for a Test: the lead, then a Manhattan and the partnerships of each innings */
function testChartsHTML(c) {
  const inns = c.innings.filter(i => i.overs_log && i.overs_log.length);
  if (!inns.length) return '';
  const W = 560, H = 190, P = {l: 44, r: 12, t: 12, b: 34};
  const top = niceMax(Math.max(...inns.flatMap(i => i.overs_log.map(o => o.runs))) + 2, 4);
  const man = inns.map(inn => {
    const k = Math.max(0, c.teams.indexOf(inn.team)), n = inn.overs_log.length;
    const f = svgFrame(W, H, P, Math.max(10, n), top.max, top.step, 'Over', 'Runs in the over');
    const bw = Math.max(.8, (f.X(1) - f.X(0)) * .84);
    let body = f.g, day = null;
    inn.overs_log.forEach(o => {
      const x0 = f.X(o.over - 1), y = f.Y(o.runs);
      if (day !== null && o.day !== day) body += `<line x1="${x0.toFixed(1)}" x2="${x0.toFixed(1)}" y1="${P.t}" y2="${H - P.b}" class="dayline"/>`;
      day = o.day;
      body += `<rect x="${(x0 + bw * .08).toFixed(1)}" y="${y.toFixed(1)}" width="${bw.toFixed(1)}" height="${(f.Y(0) - y).toFixed(1)}" fill="${TEAM_COL[k]}" opacity=".85"><title>Over ${o.over} (day ${o.day}): ${o.runs} run${o.runs === 1 ? '' : 's'}${o.wkts ? `, ${o.wkts} wkt` : ''} (${esc(o.bowler)})</title></rect>`;
      for (let w = 0; w < o.wkts; w++) body += `<circle cx="${(x0 + bw / 2).toFixed(1)}" cy="${(y - 5 - w * 7).toFixed(1)}" r="2.4" fill="${TEAM_COL[k]}" class="wkt"/>`;
    });
    return `<div class="chart-box"><h4>Manhattan · ${innTag(c, inn)} ${innScore(inn)}</h4><svg viewBox="0 0 ${W} ${H}" class="chart">${body}</svg></div>`;
  }).join('');
  const legendT = `<div class="legend">${c.teams.map((t, k) => `<span><i style="background:${TEAM_COL[k]}"></i>${esc(dn(t))}</span>`).join('')}<span><i class="wk"></i>wicket</span><span><i class="dl"></i>new day</span></div>`;
  return `<div class="charts">${legendT}<div class="chart-grid">${leadChartHTML(c, false).replace('card chart-card', 'chart-box wide')}${man}
    ${inns.map(inn => partnershipChart(inn, Math.max(0, c.teams.indexOf(inn.team)), inns)).join('')}</div></div>`;
}

/* ── the set-up form: what changes when the format is Test ── */
const TEST_MODES = ['series', 'classic'];
function fmtChanged() {
  const test = $('c-fmt').value === 'test';
  document.body.classList.toggle('fmt-test', test);
  ['s-n', 'cs-n'].forEach(id => {
    const inp = $(id);
    inp.dataset.chips = test ? '1,2,3,5' : '1,3,5,7';
    if (!inp.dataset.chips.split(',').includes(String(+inp.value))) inp.value = test ? (+inp.value > 5 ? 5 : 3) : 3;
    inp.dispatchEvent(new Event('change'));
  });
  document.querySelectorAll('.match-word').forEach(e => e.textContent = test ? 'Tests' : 'Matches');
}
/* Tests are a Match / Series or a Classic Series: any other mode goes back to T20 */
function testModeGuard() {
  const ok = TEST_MODES.includes(MODE), opt = $('c-fmt').querySelector('option[value="test"]');
  if (opt) opt.disabled = !ok;
  if (!ok && $('c-fmt').value === 'test') { $('c-fmt').value = 't20'; $('c-fmt').dispatchEvent(new Event('change')); }
}
/* the format was changed by hand: a nation's preset follows it ("India T20 2024" -> "India Test 2025") */
function followFormat() {
  const want = ' ' + fmtLabel($('c-fmt').value) + ' ', names = META.teams.map(t => t.name);
  ['s-t1', 's-t2'].forEach((id, i) => {
    const n = $(id).value;
    if (!isNationPreset(n) || n.includes(want)) return;
    const alt = names.find(x => teamKey(x) === teamKey(n) && x.includes(want));
    if (alt) { $(id).value = alt; showRoster(id, 's-r' + (i + 1)); }
  });
}
