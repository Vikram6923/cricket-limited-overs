'use strict';
/* Match centre: summary, scorecard, ball by ball, charts and your calls for one match. */

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
  const {c, d, f} = MC, mainInns = c.innings.slice(0, 2), teams = c.teams, test = isTest(c);
  const pom = c.player_of_match || {}, cond = c.conditions || {}, res = c.result || {};
  TEAM_COL = pairCols(test ? teams : mainInns.map(i => i.team));
  const scoreOf = t => mainInns.find(i => i.team === t);
  const side = (t, r) => { const i = scoreOf(t), won = res.winner === t;
    return `<div class="mc-side ${r ? 'r' : ''} ${res.winner && !won ? 'lost' : ''}" style="${tStyle(t)}">${badge(t, 'md')}
      <div><div class="nm">${esc(dn(t))}</div><div class="sc${test ? ' tsc' : ''}">${test ? (testScore(c, t) || '<small>did not bat</small>') : i ? `${i.runs}${i.wickets < 10 ? '/' + i.wickets : ''}<small>${esc(i.overs)} ov${i.target ? ' · target ' + i.target : ''}</small>` : '<small>did not bat</small>'}</div>
      ${won ? '<span class="won">WON</span>' : ''}</div></div>`; };
  const tabs = [['sum', 'Summary'], ['sc', 'Scorecard'], ['bb', 'Ball by ball'], ['ch', 'Charts'], ...(c.captaincy ? [['calls', 'Your calls']] : [])];
  if (!tabs.some(t => t[0] === MC_TAB)) MC_TAB = 'sum';
  $('m-body').innerHTML = `<div class="card mc-hero"><div class="teams2">${side(teams[0], false)}
      <div class="mc-mid"><span class="kicker">${esc(fmtLabel(c.format))}</span><span>v</span></div>${side(teams[1], true)}</div>
    <div class="mc-res">${R.fixtures.length === 1 ? '' : `<span class="r">${esc(dnt(res.text || ''))}</span>
      <span>${esc(f.stage)}</span>`}${c.venue ? `<span>Venue <b>${esc(c.venue)}</b></span>` : ''}
      <span>Toss <b>${esc(dn(c.toss.winner))}</b>, chose to ${esc(c.toss.decision)}</span><span>Pitch <b>${esc(cond.report || '–')}</b></span>${test ? testHeroLine(c) : ''}
      ${(c.rain || []).map(t => `<span>&#9730; ${esc(t)}</span>`).join('')}</div></div>
    <div class="subtabs" id="mc-tabs">${tabs.map(([k, l]) => `<button data-t="${k}" class="${k === MC_TAB ? 'on' : ''}">${l}</button>`).join('')}</div>
    <div id="mc-pane"></div>`;
  $('mc-tabs').querySelectorAll('button').forEach(b => b.onclick = () => { MC_TAB = b.dataset.t; drawMatchCentre(); });
  const pane = $('mc-pane');
  if (MC_TAB === 'sum') { pane.innerHTML = mcSummary();
    pane.querySelectorAll('[data-more]').forEach(b => b.onclick = () => { const r = b.previousElementSibling; r.hidden = !r.hidden; b.textContent = r.hidden ? 'Read more' : 'Show less'; }); }
  else if (MC_TAB === 'sc') { pane.innerHTML = mcScorecard(); pane.querySelectorAll('[data-inn]').forEach(b => b.onclick = () => { MC.inn = +b.dataset.inn; drawMatchCentre(); }); }
  else if (MC_TAB === 'bb') pane.innerHTML = mcOvers();
  else if (MC_TAB === 'ch') pane.innerHTML = test ? testChartsHTML(c) : chartsHTML(c);
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
/* key moments (6.8): one short line per moment behind an icon tag; partnership, new batter, boundary counts and the
   balls of a big over are Full only */
const TL_TAG = {wicket: 'OUT', big_over: 'OVER', hat_trick: 'HAT-TRICK', five_wickets: '5W', turning_point: '★', end_of_innings: 'END',
  rain: '☂', partnership: 'P\'SHIP', info: '•', weather: '☂', declaration: 'DEC', follow_on: 'F/O', new_ball: 'NEW', nightwatchman: 'NW', mode: '•'};
const fo = s => s ? `<span class="full-only">${s}</span>` : '';
function momentLine(e, c) {
  const inn = c.innings[(e.innings || 1) - 1] || {};
  if (e.kind === 'wicket') {
    const b = (inn.batting || []).find(x => x.id === e.player_id);
    if (b) return `<b>${esc(b.name)} ${b.runs} (${b.balls})</b>: ${esc(b.dismissal)}` +
      fo(` · partnership ${e.partnership}${e.new_batter ? ` · new batter ${esc(e.new_batter)}` : ''}`);
  }
  if (e.kind === 'milestone' && e.player) { const m = e.text.match(/b, (.*)\)$/);
    return `<b>${esc(e.player)} ${e.mark}</b> (${e.balls}b)` + fo(m ? ' · ' + esc(m[1]) : ''); }
  if (e.kind === 'end_of_innings') { const [a, ...rest] = e.text.replace(/^End of innings: /, '').split(' - ');
    return `<b>${isTest(c) ? esc(dnt(a)) : `${esc(dn(inn.team || ''))} ${esc(a)}`}</b>` + fo(rest.length ? ' · ' + esc(rest.join(' - ')) : ''); }
  if (e.kind === 'big_over') { const m = e.text.match(/^(.*?)( \(.*\))$/); return m ? esc(m[1]) + fo(esc(m[2])) : esc(e.text); }
  if (e.kind === 'turning_point') { const t = e.text.replace(/^Turning point: /, ''); return esc(dnt(t.charAt(0).toUpperCase() + t.slice(1))); }
  return esc(dnt(e.text));
}
function momentsHTML(c) {
  const test = isTest(c);                     /* a Test: the intervals are in the day strip; every wicket is Full only */
  const SKIP = new Set(['team_50', 'bowling_change', ...(test ? ['break', 'new_ball'] : [])]);
  const evs = (c.events || []).filter(e => !SKIP.has(e.kind))
    .filter(e => e.kind !== 'partnership' || (e.runs || 0) >= 50 || /\b(50|100|150) partnership/.test(e.text))
    .map((e, i) => ({e, i, k: [(e.innings || 1), e.kind === 'end_of_innings' ? 1e3 : oversNum(e.over), i]}))
    .sort((a, b) => a.k[0] - b.k[0] || a.k[1] - b.k[1] || a.k[2] - b.k[2]).map(x => x.e);   // the turning point in its place
  return evs.map(e => { const inn = c.innings[(e.innings || 1) - 1] || {};
    const tag = e.kind === 'milestone' ? String(e.mark || '50') : TL_TAG[e.kind] || '•';
    return `<div class="tl ${esc(e.kind)}${e.kind === 'partnership' || (test && e.kind === 'wicket') ? ' full-only' : ''}"><div class="ov">${e.kind === 'end_of_innings' ? '' : esc(e.over)}</div>
      <span class="tg">${tag}</span><div class="tx">${momentLine(e, c)}${e.score && e.kind !== 'end_of_innings' ? `<span class="s">${esc(tcol(inn.team || '').short)} ${esc(e.score)}</span>` : ''}</div></div>`; }).join('');
}
/* the written report: 2 sentences, then Read more */
function reportHTML(text, extra) {
  const ss = String(text || '').match(/[^.!?]+[.!?]+(\s|$)/g) || [text || ''];
  const head = ss.slice(0, 2).join('').trim(), rest = ss.slice(2).join('').trim();
  return `<div class="card pad report">${esc(head)}${rest ? `<span class="rest" hidden> ${esc(rest)}</span>
    <button type="button" class="more-btn" data-more>Read more</button>` : ''}${extra || ''}</div>`;
}
function statTiles(c) {
  const mainInns = isTest(c) ? c.innings : c.innings.slice(0, 2), bat = mainInns.flatMap(i => i.batting.filter(x => x.batted).map(x => ({...x, team: i.team})));
  const bowl = mainInns.flatMap(i => i.bowling.map(x => ({...x, team: i.bowling_team})));
  const hs = [...bat].sort((x, y) => y.runs - x.runs || x.balls - y.balls)[0];
  const bb = [...bowl].sort((x, y) => y.wickets - x.wickets || x.runs - y.runs)[0];
  const per = k => [...new Set(mainInns.map(i => i.team))].map(t => `${esc(tcol(t).short)} ${mainInns.filter(i => i.team === t)
    .reduce((n, i) => n + i.batting.reduce((a, x) => a + (x[k] || 0), 0), 0)}`).join(' · ');
  const tile = (k, v, s) => `<div class="stat-tile"><span class="k">${k}</span><b>${v}</b><span class="s">${s}</span></div>`;
  return `<div class="stat-tiles">${hs ? tile('Top score', `${hs.runs}${hs.out ? '' : '*'} <small>(${hs.balls})</small>`, esc(hs.name)) : ''}
    ${bb ? tile('Best bowling', `${bb.wickets}/${bb.runs}`, esc(bb.name)) : ''}
    ${tile('Sixes', per('sixes'), '')}${tile('Fours', per('fours'), '')}</div>`;
}
function mcSummary() {
  const {c, d} = MC, pom = c.player_of_match || {}, test = isTest(c), mainInns = test ? c.innings : c.innings.slice(0, 2);
  const wp = small => test ? leadChartHTML(c, small) + wdlChartHTML(c, small) : winProbHTML(c, small);
  const tl = momentsHTML(c);
  const best = mainInns.flatMap(i => {
    const b = [...i.batting].filter(x => x.batted).sort((x, y) => y.runs - x.runs)[0];
    const w = [...i.bowling].sort((x, y) => y.wickets - x.wickets || x.runs - y.runs)[0];
    return [b && {n: b.name, t: i.team, what: 'Top score', v: `${b.runs}${b.out ? '' : '*'} <small>(${b.balls})</small>`},
            w && {n: w.name, t: i.bowling_team, what: 'Best bowling', v: `${w.wickets}/${w.runs} <small>(${w.overs})</small>`}];
  }).filter(Boolean);
  const imp = c.impact_player ? Object.entries(c.impact_player).map(([t, x]) => `<div class="small muted">Impact Player · ${esc(dn(t))}: <b>${esc(x.in)}</b> for ${esc(x.out)} (${esc(x.when)})</div>`).join('') : '';
  /* 6.8: player of the match, 4 stat tiles and the win-probability chart first; then 2 sentences of the report and
     the key moments. The top performers list repeats the tiles, so it is Full only. */
  return `<div class="sum-grid"><div>
      ${pom.name ? `<div class="card pom">${avatar(pom.name, pom.team, 'xl')}<div><div class="kicker k">Player of the match</div>
        <div class="nm">${esc(pom.name)}</div><div class="fig">${esc(dn(pom.team))}${pomLine(c, pom) ? ' · ' + esc(pomLine(c, pom)) : ''}</div></div></div>` : ''}
      ${statTiles(c)}
      <div class="wp-first">${wp(true)}</div>
      ${test ? dayStripHTML(d.strip, c) : ''}
      ${reportHTML(dnt(d.report), imp ? '<div style="margin-top:8px">' + imp + '</div>' : '')}
      ${tl ? `<div class="card"><div class="kicker" style="padding:16px 20px 4px">Key moments</div><div class="timeline">${tl}</div></div>` : ''}
    </div><div>
      <div class="wp-side">${wp(true)}</div>
      <div class="card perf full-only"><div class="kicker">Top performers</div>${best.map(x => `<div class="prow">${avatar(x.n, x.t)}
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
  const sw = all.map((i, n) => `<button class="${n === k ? 'on' : ''}" data-inn="${n}" style="${tStyle(i.team)}">${badge(i.team, 'sm')}<span>${n >= c.innings.length ? 'Super over' : isTest(c) ? innTag(c, i) : esc(dn(i.team))}</span>
    <span class="s">${isTest(c) ? innScore(i) : `${i.runs}/${i.wickets}`}</span><span class="small">(${esc(i.overs)})</span></button>`).join('');
  return `<div class="inn-switch">${sw}</div>
    <div class="card"><div class="tblwrap"><table class="sctbl"><tr><th class="l">Batter</th><th class="l hide-s"></th><th>R</th><th>B</th><th class="hide-s">4s</th><th class="hide-s">6s</th><th>SR</th></tr>
    ${bat.map(b => { const sr = b.balls ? 100 * b.runs / b.balls : 0;
      return `<tr class="${b.runs === top && top ? 'hi' : ''}"><td class="l"><b>${esc(b.name)}</b>${b.captain ? '<span class="tag">C</span>' : ''}${b.keeper ? '<span class="tag">WK</span>' : ''}
        <div class="how show-s">${b.out ? esc(b.dismissal) : '<span class="no">not out</span>'}</div></td>
      <td class="l how hide-s">${b.out ? esc(b.dismissal) : '<span class="no">not out</span>'}</td><td class="r">${b.runs}${b.out ? '' : '*'}</td><td>${b.balls}</td>
      <td class="hide-s">${b.fours}</td><td class="hide-s">${b.sixes}</td><td>${b.balls ? sr.toFixed(1) : '–'}<span class="srbar hide-s" style="--c:${t.hi}"><i style="width:${Math.min(100, sr / 3)}%"></i></span></td></tr>`; }).join('')}</table></div>
    <div class="sc-foot"><span>Extras <b>${exT}</b> (b ${ex.b || 0}, lb ${ex.lb || 0}, w ${ex.w || 0}, nb ${ex.nb || 0})</span>
      <span>Total <b>${inn.runs}/${inn.wickets}${inn.declared ? ' declared' : ''}</b> (${esc(inn.overs)} ov, RR ${rr})${inn.follow_on ? ' · following on' : ''}</span>${dnb.length ? `<span>Did not bat: ${dnb.join(', ')}</span>` : ''}</div>
    ${inn.fall_of_wickets && inn.fall_of_wickets.length ? `<div class="kicker" style="padding:4px 14px 0">Fall of wickets</div><div class="fowstrip" style="--c:${t.hi}"><div class="line"></div>
      ${inn.fall_of_wickets.map(w => `<div class="w" style="left:${Math.min(100, 100 * w.runs / Math.max(1, inn.runs))}%" title="${esc(w.batter)}: ${w.runs}/${w.wkt} (${esc(w.over)} ov)">${w.wkt}<span>${w.runs}</span></div>`).join('')}</div>` : ''}</div>
    <div class="card" style="margin-top:16px"><div class="tblwrap"><table class="sctbl"><tr><th class="l">Bowler · ${esc(dn(inn.bowling_team))}</th><th>O</th><th class="hide-s">M</th><th>R</th><th>W</th><th>Econ</th><th class="hide-s">Dots</th><th class="hide-s">Extras</th></tr>
    ${inn.bowling.map(b => `<tr class="${b.wickets === bestW && bestW ? 'hi' : ''}"><td class="l"><b>${esc(b.name)}</b></td><td>${esc(b.overs)}</td><td class="hide-s">${b.maidens}</td><td>${b.runs}</td>
      <td class="r">${b.wickets}</td><td>${fmtNum(b.economy, 2)}</td><td class="hide-s">${b.dots ?? '–'}</td><td class="hide-s">${[b.wides ? b.wides + 'w' : '', b.noballs ? b.noballs + 'nb' : ''].filter(Boolean).join(' ') || '–'}</td></tr>`).join('')}</table></div></div>`;
}
function mcOvers() {
  const {c, d} = MC;
  const evAt = (n, o) => (c.events || []).filter(e => e.innings === n && overOf(e.over) === o && ['wicket', 'big_over', 'milestone'].includes(e.kind));
  return `<div class="card">${c.innings.map((inn, i) => ({inn, i})).reverse().map(({inn, i}) => `<div class="ib" style="${tStyle(inn.team)}">${badge(inn.team, 'sm')} ${isTest(c) ? innTag(c, inn) : esc(dn(inn.team))} · ${inn.runs}/${inn.wickets} (${esc(inn.overs)})</div>` +
    [...(inn.overs_log || [])].reverse().map(o => `<div class="over-card"><div class="o"><b>Over ${o.over}</b><span>${esc(o.bowler)}</span></div>
      <div class="balls">${(o.balls || []).map(b => chip(b, true)).join('')}</div>
      <div class="tot"><b>${o.runs}${o.wkts ? ` · ${o.wkts}W` : ''}</b><span>${esc(tcol(inn.team).short)} ${o.total}/${o.wickets}</span></div>
      ${evAt(i + 1, o.over).map(e => `<div class="ev ${e.kind === 'wicket' ? 'w' : ''}">${e.kind === 'wicket' ? 'WICKET · ' : ''}${esc(dnt(e.text))}</div>`).join('')}</div>`).join('')).join('')}</div>
    <details class="card pad" style="margin-top:16px"><summary class="muted">Text scorecard and innings log</summary><pre class="sc">${esc(d.text)}</pre></details>`;
}
let WP_N = 0;
function winProbHTML(c, small) {
  const inns = c.innings.filter(i => i.overs_log && i.overs_log.length).slice(0, 2);
  const seq = [];
  inns.forEach((inn, k) => inn.overs_log.forEach(o => { if (o.win_prob !== null && o.win_prob !== undefined) seq.push({k, o, p: k === 0 ? o.win_prob : 1 - o.win_prob}); }));
  if (seq.length < 2) return '';
  const W = 460, H = small ? 190 : 240, P = {l: 34, r: 10, t: 12, b: 24}, n1 = inns[0].overs_log.length;
  const X = j => P.l + (W - P.l - P.r) * j / seq.length, Y = p => H - P.b - (H - P.t - P.b) * p;
  const pts = [[0, .5], ...seq.map((s, j) => [j + 1, s.p])];
  const [ca, cb] = TEAM_COL, gid = 'wpg' + (++WP_N);   // own id: a gradient inside a hidden copy draws nothing
  let g = `<defs><linearGradient id="${gid}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${ca}"/><stop offset=".5" stop-color="#8d9bb5"/><stop offset="1" stop-color="${cb}"/></linearGradient></defs>`;
  g += `<line x1="${P.l}" x2="${W - P.r}" y1="${Y(.5)}" y2="${Y(.5)}" class="target"/>`;
  if (inns[1]) g += `<line x1="${X(n1)}" x2="${X(n1)}" y1="${P.t}" y2="${H - P.b}" class="grid"/>`;
  g += `<polyline fill="none" stroke="url(#${gid})" stroke-width="2.6" stroke-linejoin="round" points="${pts.map(([j, p]) => `${X(j).toFixed(1)},${Y(p).toFixed(1)}`).join(' ')}"/>`;
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
  return `<div class="chart-box"><h4>Partnerships · ${esc(inn.label ? dnt(inn.label) : dn(inn.team))}</h4><svg viewBox="0 0 ${W} ${H}" class="chart">${g}</svg></div>`;
}

/* batting / bowling */
