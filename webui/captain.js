/* Manual captaincy: the person captains one side (engine/control.py). The server holds the open question in
   /api/status (captain.pending); the answer goes to /api/decide. Every screen shows the computer's choice. */
'use strict';

const KIND_LABEL = {toss: 'Toss', xi: 'Playing XI', bowler: 'Bowlers', batter: 'Next batter', impact: 'Impact Player',
  result: 'Stop after each of my matches', ball: 'Ball by ball'};
const CAP = {qid: null, q: null, auto: {}, manual: [], impact: true};
const n1 = v => v === null || v === undefined ? '–' : v;
const statLine = p => [p.role + (p.kind && p.role !== 'Batter' && p.role !== 'WK' ? ` (${p.kind})` : ''),
  p.bat_avg ? `bat avg ${p.bat_avg}, SR ${p.bat_sr}` : '', p.bowl_econ && p.overs_per_match >= 0.5 ? `bowl econ ${p.bowl_econ}, ${p.overs_per_match} ov/match` : ''].filter(Boolean).join(' · ');
const osTag = p => p.overseas ? '<span class="os-tag">OS</span>' : '';

function capRender(st) {
  const cap = st.captain, q = cap.pending;
  $('cap-progress').textContent = st.total > 1 ? `${st.done} of ${st.total} matches played` : '';
  $('cap-skip-all').style.display = st.total > 1 ? '' : 'none';      // no "rest of the season" in a single match
  if (!q) {
    if (CAP.qid !== 'wait') { CAP.qid = 'wait'; $('cap-q').innerHTML = '<div class="muted">Playing on…</div>'; }
    return;
  }
  if (q.id === CAP.qid) return;
  CAP.qid = q.id; CAP.q = q; CAP.manual = cap.manual; CAP.auto = {};
  const c = q.context || {}, s = q.state || {};
  const tt = capTeams(q); setDisplayTeams(tt.filter(Boolean));
  $('cap-title').innerHTML = `You captain ${badge(q.team, 'sm')} ${esc(dn(q.team))}`;
  $('cap-ctx').textContent = [c.stage, c.match_no && c.stage !== 'Match ' + c.match_no ? 'match ' + c.match_no : '', s.venue || 'neutral venue',
    s.pitch ? 'pitch: ' + s.pitch : ''].filter(Boolean).join(' · ');
  $('cap-score').innerHTML = scoreHTML(q);
  $('cap-bug').innerHTML = bugHTML(q);
  renderAuto();
  ({toss: qToss, xi: qXI, bowler: q2 => qPick(q2, 'bowler'), batter: q2 => qPick(q2, 'batter'), impact: qImpact,
    result: qResult, ball: qBall}[q.kind] || qResult)(q);
}

function renderAuto() {
  if (CAP.manual.includes('ball')) CAP.ballOn = true;
  const kinds = Object.keys(KIND_LABEL).filter(k => (k !== 'impact' || CAP.impact || CAP.manual.includes('impact'))
    && (k !== 'result' || !mpOn())
    && (k !== 'ball' || CAP.ballOn));
  const computer = k => CAP.auto[k] !== undefined ? CAP.auto[k] : !CAP.manual.includes(k);
  $('cap-auto').innerHTML = kinds.map(k => `<button class="tog ${computer(k) ? '' : 'on'}" data-k="${k}"
    title="${computer(k) ? 'The computer decides - click to decide yourself' : 'You decide - click to leave it to the computer'}">${KIND_LABEL[k]}${computer(k) ? ' · computer' : ''}</button>`).join('');
  $('cap-auto').querySelectorAll('.tog').forEach(b => b.onclick = () => { CAP.auto[b.dataset.k] = !computer(b.dataset.k); renderAuto(); });
}

const mpOn = () => typeof MP !== 'undefined' && MP.active;      // two players (multiplayer.js)
async function capSend(choice, extra = {}) {
  const mp = mpOn();
  try { await api(mp ? '/api/mp/decide' : '/api/decide', {id: CAP.q.id, choice, auto: CAP.auto, ...extra, ...(mp ? {token: MP.token} : {})}); }
  catch (e) { toast(e.message, true); }
  $('cap-q').innerHTML = '<div class="muted">Playing on…</div>'; CAP.qid = 'sent';
  clearTimeout(POLL_T); POLL_T = setTimeout(mp ? mpPoll : poll, 120);
}

const ballClass = b => ballCls(b);

/* the two sides: from "A v B" (the match name) or the question's team and its opponent */
function capTeams(q) {
  const s = q.state || {}, m = String(s.match || '').split(' v ');
  if (m.length === 2) CAP.teams = m;
  else if (s.opponent) CAP.teams = [q.team, s.opponent];
  return CAP.teams || [q.team, s.opponent || ''];
}
/* broadcast score bar across the top */
function bugHTML(q) {
  const s = q.state || {}, [a, b] = capTeams(q);
  if (s.runs === undefined) {
    return `<div class="bug pre" style="--bat:${tcol(a).c};--bowl:${tcol(b).c}">
      <div class="tm">${badge(a, 'md')}<div><div class="lbl">${a === q.team ? 'You' : 'Opponent'}</div><div class="nm">${esc(dn(a))}</div></div></div>
      <div class="mid"><div class="need">${s.format === 'odi' ? 'ODI' : 'T20'} · ${s.overs} overs a side</div><div class="muted small">${esc(s.venue || 'Neutral venue')} · pitch: ${esc(s.pitch || '–')}</div></div>
      <div class="tm r">${badge(b, 'md')}<div><div class="lbl">${b === q.team ? 'You' : 'Opponent'}</div><div class="nm">${esc(dn(b))}</div></div></div></div>`;
  }
  const bat = s.batting, bowl = bat === a ? b : a;
  const wp = s.win_prob === null || s.win_prob === undefined ? null : Math.round(100 * s.win_prob);
  const prev = (s.previous || []).map(x => String(x).startsWith(bowl) ? String(x).slice(bowl.length).trim() : x).join(' · ');
  const over = s.target && s.need > 0 && (s.balls_left <= 0 || s.wkts >= 10);   // the chase has ended short
  const need = q.kind === 'result' && q.result ? esc(dnText(q.result, [a, b]))
    : over ? (s.need === 1 ? 'Scores level' : `<b>${esc(dn(bowl))}</b> have won`)
    : s.target ? (s.need <= 0 ? `<b>${esc(dn(bat))}</b> have won` : `${esc(tcol(bat).short)} need <b>${s.need}</b> off <b>${s.balls_left}</b>${s.rrr !== null && s.rrr !== undefined ? ` <span class="rr">RRR ${s.rrr}</span>` : ''}`)
    : `Innings ${s.innings}${s.crr !== null && s.crr !== undefined ? ` <span class="rr">run rate ${s.crr}</span>` : ''}`;
  return `<div class="bug" style="--bat:${tcol(bat).c};--bowl:${tcol(bowl).c}">
    <div class="tm">${badge(bat, 'md')}<div><div class="lbl">${esc(dn(bat))} · batting${bat === q.team ? ' (you)' : ''}</div>
      <div class="big">${s.runs}/${s.wkts}<small>${esc(s.overs_done)}${s.max_overs ? ' / ' + s.max_overs : ''}</small></div></div></div>
    <div class="mid"><div class="need">${need}</div>
      ${wp !== null ? `<div class="wpbar"><i style="background:${tcol(bat).hi};width:${wp}%"></i><i style="background:${tcol(bowl).hi};width:${100 - wp}%"></i></div>
      <div class="wplab"><span>${esc(tcol(bat).short)} <b>${wp}%</b></span><span>win probability</span><span><b>${100 - wp}%</b> ${esc(tcol(bowl).short)}</span></div>` : ''}
      <div class="muted small">Partnership ${s.partnership.runs} (${s.partnership.balls})</div></div>
    <div class="tm r">${badge(bowl, 'md')}<div><div class="lbl">${esc(dn(bowl))} · bowling${bowl === q.team ? ' (you)' : ''}</div>
      <div class="big dimmed">${prev ? esc(prev) : '<small>yet to bat</small>'}</div></div></div></div>`;
}

function scoreHTML(q) {
  const s = q.state || {};
  if (s.runs === undefined) {           // before the match: toss and XI
    return `<div class="cap-panel"><h3>${esc(dnText(s.match, capTeams(q)))}</h3>
      <div class="sb-line">${s.format === 'odi' ? 'ODI' : 'T20'}, ${s.overs} overs a side · v ${esc(dn(s.opponent))}</div>
      <div class="sb-line">Venue: <b>${esc(s.venue || 'neutral')}</b></div>
      <div class="sb-line">Pitch: <b>${esc(s.pitch || '–')}</b></div>
      ${q.toss ? `<div class="sb-line" style="margin-top:6px">${esc(q.toss)}</div>` : ''}
      ${(s.rain || []).map(r => `<div class="sb-line">☂ ${esc(r)}</div>`).join('')}</div>`;
  }
  const [a, b] = capTeams(q), batT = s.batting, bowlT = batT === a ? b : a;
  const bat = s.batters.filter(x => x.batted);
  const crease = bat.filter(x => x.at_crease).sort((x, y) => (y.on_strike ? 1 : 0) - (x.on_strike ? 1 : 0));
  const yet = s.batters.filter(x => !x.batted).map(x => esc(x.name)).join(', ');
  const balls = o => { const [p, r] = String(o).split('.').map(Number); return 6 * p + (r || 0); };
  const cur = q.bowler ? s.bowlers.find(x => x.name === q.bowler.name) : null;
  const pcard = (x, team, fig, sub, on) => `<div class="pc ${on ? 'on' : ''}" style="${tStyle(team)}">${avatar(x.name, team)}
    <div class="who"><div class="nm">${esc(x.name)}${on ? '<span class="strike">ON STRIKE</span>' : ''}</div><div class="prole">${sub}</div></div>
    <div class="fig">${fig}</div></div>`;
  return `<div class="cap-panel live">
    <div class="pcs">${crease.map(x => pcard(x, batT, `<b>${x.runs}</b><span>${x.balls} ball${x.balls === 1 ? '' : 's'}</span>`,
      `${x.fours} × 4 · ${x.sixes} × 6 · SR ${x.balls ? (100 * x.runs / x.balls).toFixed(0) : '–'}`, x.on_strike)).join('')}
    ${cur ? pcard(cur, bowlT, `<b>${cur.wkts}–${cur.runs}</b><span>${esc(cur.overs)} overs</span>`, `bowling${q.bowler.kind ? ' · ' + esc(q.bowler.kind) : ''}`, false) : ''}</div>
    ${s.recent.length ? `<div class="lbl" style="margin-top:14px">Recent overs</div><div class="overs">${s.recent.map(o => `<div class="orow"><span class="muted">Over ${o.over} · ${esc(o.bowler)}</span>
      <span class="balls">${o.balls.map(x => chip(x, true)).join('')}</span><b>${o.runs}</b></div>`).join('')}</div>` : ''}
    ${s.events.length ? `<div class="evs">${s.events.map(e => esc(dnText(e, capTeams(q)))).join('<br>')}</div>` : ''}
    <details class="fullsc"><summary>Full scorecard · ${esc(dn(batT))}</summary>
    <table class="mini"><tr><th>Batter</th><th></th><th>R</th><th>B</th><th>4s</th><th>6s</th><th>SR</th></tr>
    ${bat.map(x => `<tr class="${x.at_crease ? 'crease' : x.out ? 'dim' : ''}"><td>${esc(x.name)}${x.on_strike ? ' *' : ''}</td>
      <td class="how">${x.out ? esc(x.how) : x.at_crease ? 'batting' : 'not out'}</td><td>${x.runs}</td><td>${x.balls}</td>
      <td>${x.fours}</td><td>${x.sixes}</td><td>${x.balls ? (100 * x.runs / x.balls).toFixed(0) : '–'}</td></tr>`).join('')}</table>
    ${yet ? `<div class="sb-line" style="margin-top:6px">Yet to bat: ${yet}</div>` : ''}
    <table class="mini"><tr><th>Bowler</th><th>O</th><th>M</th><th>R</th><th>W</th><th>Econ</th></tr>
    ${s.bowlers.map(x => `<tr><td>${esc(x.name)}</td><td>${x.overs}</td><td>${x.maidens}</td><td>${x.runs}</td><td>${x.wkts}</td>
      <td>${balls(x.overs) ? (6 * x.runs / balls(x.overs)).toFixed(1) : '–'}</td></tr>`).join('')}</table></details>
  </div>`;
}

const cpuTag = on => on ? '<span class="cpu-tag">SUGGESTED</span>' : '';
const optCard = (p, isCpu, extra) => `<button class="opt ${isCpu ? 'cpu' : ''}" data-id="${esc(p.id)}">${cpuTag(isCpu)}
  <b>${esc(p.name)}${osTag(p)}</b>${extra}</button>`;
const nameOf = (list, id) => (list.find(p => p.id === id) || {}).name || '–';

function qToss(q) {
  $('cap-q').innerHTML = `<h3>${esc(dnText(q.text, CAP.teams || []))} Bat or bowl?</h3>
    <div class="sb-line">Suggested: <b>${esc(q.default)}</b>.</div>
    <div class="opts">${q.options.map(o => `<button class="opt ${o === q.default ? 'cpu' : ''}" data-id="${o}">${cpuTag(o === q.default)}
      <b>${o === 'bat' ? 'Bat first' : 'Bowl first'}</b><span>${o === 'bat' ? 'set a target' : 'chase'}</span></button>`).join('')}</div>`;
  $('cap-q').querySelectorAll('.opt').forEach(b => b.onclick = () => capSend(b.dataset.id));
}

/* Impact Player: the computer's suggestion, who comes in and who goes out */
function impactBoxHTML(imp, standalone) {
  if (!imp) return '';
  const all = [...imp.ins, ...imp.outs], sg = imp.suggestion;
  const say = sg ? `Suggested: <b>${esc(nameOf(all, sg.in))}</b> for <b>${esc(nameOf(all, sg.out))}</b> now (worth about ${sg.gain} runs).`
    : 'Suggested: not now.';
  return `<div class="${standalone ? '' : 'impact-box'}">
    ${standalone ? '' : '<div class="lbl">Impact Player (not used yet)</div>'}
    <div class="sb-line">${say}</div>
    <div class="row"><select id="ib-in">${imp.ins.map(p => `<option value="${esc(p.id)}" ${sg && sg.in === p.id ? 'selected' : ''}>In: ${esc(p.name)}${p.overseas ? ' (OS)' : ''} - ${esc(statLine(p))}</option>`).join('')}</select></div>
    <div class="row" style="margin-top:6px"><select id="ib-out">${imp.outs.map(p => `<option value="${esc(p.id)}" ${sg && sg.out === p.id ? 'selected' : ''}>Out: ${esc(p.name)}${p.overseas ? ' (OS)' : ''} - ${esc(p.role)}</option>`).join('')}</select></div>
    ${standalone ? '' : `<label class="sb-line" style="display:flex;gap:6px;align-items:center;margin-top:6px;cursor:pointer"><input type="checkbox" id="ib-use" style="width:auto"> Make this substitution with my choice</label>`}
    <div class="err" id="ib-err"></div></div>`;
}
function impactChoice(imp) {
  if (!imp || !$('ib-in')) return null;
  const inn = imp.ins.find(p => p.id === $('ib-in').value), out = imp.outs.find(p => p.id === $('ib-out').value);
  if (!inn || !out) return null;
  if (imp.max_overseas !== null && inn.overseas && !out.overseas && imp.overseas_in_xi >= imp.max_overseas) {
    $('ib-err').textContent = `That would make more than ${imp.max_overseas} overseas players.`;
    return 'bad';
  }
  $('ib-err').textContent = '';
  return {in: inn.id, out: out.id};
}

/* bowler for the next over / batter after a wicket */
function qPick(q, kind) {
  const imp = q.impact, ph = (q.options[0] || {}).phase;
  const fig = p => q.state.bowlers.find(b => b.name === p.name) || {overs: '0.0', maidens: 0, runs: 0, wkts: 0};
  const extra = p => kind === 'bowler'
    ? `<span>${esc(p.kind || p.role)} · usually ${p.overs_per_match} ov/match</span><span>today ${fig(p).overs}-${fig(p).maidens}-${fig(p).runs}-${fig(p).wkts} · ${p.quota_left} ov left</span>
       <span class="full-only">expected econ${ph ? ' (' + ph + ')' : ''} <b>${n1(p.phase_econ)}</b> · career ${n1(p.bowl_econ)}</span>`
    : `<span>${esc(p.role)}${p.hand ? ' · ' + esc(p.hand) + 'HB' : ''}${p.slot ? ' · usually #' + p.slot : ''}</span>
       <span>avg ${n1(p.bat_avg)} · SR ${n1(p.bat_sr)}</span><span class="full-only">expected SR${ph ? ' (' + ph + ')' : ''} <b>${n1(p.phase_sr)}</b></span>`;
  const draw = () => {
    const use = $('ib-use') && $('ib-use').checked, ic = use ? impactChoice(imp) : null;
    let opts = q.options;
    if (kind === 'bowler') {                      // the computer's pick, then real bowlers by expected economy
      const rank = p => (p.id === q.default ? -1e6 : 0) + (p.overs_per_match >= 1 ? 0 : 1000) + (p.phase_econ || 99);
      opts = [...opts].sort((a, b) => rank(a) - rank(b));
    }
    if (ic && ic !== 'bad') {                     // the substitute can bowl / bat at once
      const sub = imp.ins.find(p => p.id === ic.in);
      opts = opts.filter(p => p.id !== ic.out).concat([{...sub, quota_left: 'full quota', role: sub.role + ' - Impact sub'}]);
    }
    $('cap-opts').innerHTML = opts.map(p => optCard(p, p.id === q.default, extra(p))).join('');
    $('cap-opts').querySelectorAll('.opt').forEach(b => b.onclick = () => {
      const c = $('ib-use') && $('ib-use').checked ? impactChoice(imp) : null;
      if (c === 'bad') return;
      capSend(kind === 'bowler' ? {bowler: b.dataset.id, impact: c} : {batter: b.dataset.id, impact: c});
    });
  };
  $('cap-q').innerHTML = `<h3>${kind === 'bowler' ? `Who bowls over ${q.over}?` : 'Wicket! Who goes in next?'}</h3>
    <div class="sb-line">Suggested: <b>${esc(nameOf(q.options, q.default))}</b>${imp && imp.suggestion ? ', with the Impact substitution below' : ''}.</div>
    <div class="opts" id="cap-opts"></div>${impactBoxHTML(imp, false)}
    <div class="cap-actions"><button class="btn sec" id="cap-cpu">Use the suggestion</button></div>`;
  draw();
  ['ib-use', 'ib-in', 'ib-out'].forEach(id => { if ($(id)) $(id).onchange = draw; });
  $('cap-cpu').onclick = () => capSend(null);
}

function qImpact(q) {
  const imp = q.impact;
  $('cap-q').innerHTML = `<h3>Impact Player - ${esc(q.moment)}</h3>
    <div class="sb-line">The substitute can bat and bowl a full quota; the player replaced takes no further part.</div>
    ${impactBoxHTML(imp, true)}
    <div class="cap-actions"><button class="btn go" id="ib-make">Make this substitution</button>
      <button class="btn sec" id="ib-cpu">${imp.suggestion ? 'Use the suggestion' : 'Use the suggestion (wait)'}</button>
      <button class="btn sec" id="ib-wait">Not now</button></div>`;
  $('ib-make').onclick = () => { const c = impactChoice(imp); if (c && c !== 'bad') capSend(c); };
  $('ib-cpu').onclick = () => capSend(null);
  $('ib-wait').onclick = () => capSend({});
}

function qResult(q) {
  $('cap-q').innerHTML = `<h3>${esc(dnText(q.result || 'Match over', CAP.teams || []))}</h3>
    ${(q.scores || []).map(s => `<div class="sb-line">${esc(dnText(s, CAP.teams || []))}</div>`).join('')}
    ${q.pom && q.pom.name ? `<div class="sb-line">Player of the match: <b>${esc(q.pom.name)}</b> (${esc(dn(q.pom.team))})</div>` : ''}
    ${mpResultSeries()}
    <div class="cap-actions"><button class="btn go" id="cap-cont">${mpResultNext()}</button></div>`;
  $('cap-cont').onclick = () => capSend(null);
}

/* two players, best of 3 / 5: the series score on the result pause (the match just played counts) */
function mpSeries() { return mpOn() && MP.series && MP.series.of > 1 && !MP.series.league ? MP.series : null; }
function mpResultSeries() {
  const sr = mpSeries();
  return sr ? `<div class="series-now">${mpSeriesLine(sr, MP.names, false)}</div>` : '';
}
function mpResultNext() {
  const sr = mpSeries();
  if (!sr) return 'Continue';
  const left = sr.of - sr.finished, [a, b] = sr.wins;
  return Math.abs(a - b) > left || left === 0 ? 'See the series results' : `Next match (${sr.finished + 1} of ${sr.of}) →`;
}

/* ball by ball: aggression bars (1-9, 5 = as real sides play this situation; docs/match_play_design.md) */
const BAT_WORD = {1: 'Block', 2: 'Defend', 3: 'Careful', 4: 'Steady', 5: 'Normal', 6: 'Positive', 7: 'Attack',
  8: 'Hit out', 9: 'Slog'};
const BOWL_WORD = {1: 'Contain', 2: 'Very tight', 3: 'Tight', 4: 'Steady', 5: 'Normal', 6: 'Probing', 7: 'Attack',
  8: 'Very attacking', 9: 'All-out attack'};
function barsHTML(key, val, words) {
  return `<div class="bars" data-key="${esc(key)}">${[1, 2, 3, 4, 5, 6, 7, 8, 9].map(i =>
    `<button class="bar ${i <= val ? 'on' : ''} ${i === 5 ? 'mid' : ''}" data-v="${i}" title="${i}: ${words[i]}"></button>`).join('')}
    <span class="bar-word">${val} · ${words[val]}</span></div>`;
}
function qBall(q) {
  const bat = q.side === 'bat', st = q.state || {};
  const vals = {};
  const pct = c => Math.round(100 * c.settled);
  const who = (c, strike) => `<div class="bb-row">
      <div class="bb-name"><b>${esc(c.name)}${strike ? ' *' : ''}</b> <span class="muted">${c.runs} (${c.balls})</span>${c.balls < 10 ? '<span class="new-tag simple-only" title="New at the crease: still playing himself in">NEW</span>' : ''}
        <div class="settle full-only" title="How far his scoring has picked up since his first ball (the fitted settling-in curve)"><i style="width:${pct(c)}%"></i></div>
        <span class="muted small full-only">settled ${pct(c)}% · usual SR in these overs ${n1(c.sr)}</span></div>
      ${bat ? barsHTML(c.id, c.bars, BAT_WORD) : ''}</div>`;
  if (bat) { vals[q.striker.id] = q.striker.bars; vals[q.non_striker.id] = q.non_striker.bars; }
  else vals[q.bowler.id] = q.bowler.bars;
  const ballsHTML = (q.this_over || []).map(b => chip(b)).join('') + '<span class="ball empty"></span>'.repeat(Math.max(0, 6 - (q.this_over || []).filter(b => !/wd|nb/.test(b)).length));
  const sit = st.target ? `Need <b>${st.need}</b> off <b>${st.balls_left}</b>` : (q.projected ? `Projected score <b>${q.projected}</b>` : '');
  const lb = mpOn() && q.since && q.since.length ? q.since[q.since.length - 1] : null;   // both choices, shown after the ball
  const reveal = lb && lb.bars ? `<div class="mp-reveal">Last ball (${lb.over}.${lb.ball}, ${esc(lb.sym)}): ${esc(lb.batter)} batting
    <b>${lb.bars} · ${BAT_WORD[lb.bars]}</b> v ${esc(lb.bowler)} bowling <b>${lb.plan} · ${BOWL_WORD[lb.plan]}</b></div>` : '';
  $('cap-q').innerHTML = `<div class="hl-box" id="hl-box" style="display:none"></div>
    <h3>Over ${q.over}, ball ${q.ball}: ${esc(q.bowler.name)} to ${esc(q.striker.name)}${q.free_hit ? ' · <span style="color:var(--amber)">FREE HIT</span>' : ''}</h3>${reveal}
    <div class="sb-line">${sit}${sit ? ' · ' : ''}${esc(q.phase)} overs</div>
    <div class="thisover"><span class="lb">This over</span>${ballsHTML}</div>
    <div class="lbl" style="margin-top:10px">${bat ? 'Your batters: aggression' : 'Your bowler: plan'}</div>
    ${who(q.striker, true)}${who(q.non_striker, false)}
    <div class="bb-row"><div class="bb-name"><b>${esc(q.bowler.name)}</b> <span class="muted">${esc(q.bowler.kind || '')} · ${esc(q.bowler.figures)}<span class="full-only"> · expected econ ${n1(q.bowler.econ)}</span></span></div>
      ${bat ? '' : barsHTML(q.bowler.id, q.bowler.bars, BOWL_WORD)}</div>
    <div class="hint bb-hint-short simple-only">${bat ? 'Higher = more runs, more risk.' : 'Higher = more wickets, more runs.'} Keys 1–9, Space = next ball.</div>
    <div class="hint full-only" style="margin-top:6px">${bat ? '5 = how real sides bat in this situation. Higher: more runs and more risk; lower: fewer of both. Far from 5 costs, more so when a wicket is dear.'
      : '5 = a normal plan. Attack takes more wickets but leaks runs; contain saves runs but takes fewer wickets.'} Keys: 1-9 sets ${bat ? 'the striker' : 'the bowler'}, Space = next ball.</div>
    <div class="cap-actions bb-act"><button class="btn go big" data-until="ball">Next ball <kbd>Space</kbd></button>
      <button class="btn sec" data-until="over">Sim over</button>
      <button class="btn sec" data-until="wicket">Sim to wicket</button>
      <button class="btn sec" data-until="innings">Sim innings</button>
      ${HL.selectHTML()}</div>`;
  const el = $('cap-q');
  $('hl-level').onchange = ev => { HL.setLevel(ev.target.value); HL.play(q.since, $('hl-box')); };
  HL.play(q.since, $('hl-box'));
  const words = bat ? BAT_WORD : BOWL_WORD;
  const setBars = (key, v) => {
    vals[key] = v;
    const box = [...el.querySelectorAll('.bars')].find(b => b.dataset.key === key);
    if (!box) return;
    box.querySelectorAll('.bar').forEach(b => b.classList.toggle('on', +b.dataset.v <= v));
    box.querySelector('.bar-word').textContent = `${v} · ${words[v]}`;
  };
  el.querySelectorAll('.bars').forEach(box => box.querySelectorAll('.bar').forEach(b =>
    b.onclick = () => setBars(box.dataset.key, +b.dataset.v)));
  const send = until => { CAP.keys = null; HL.stop(); capSend(bat ? {bat: vals, until} : {bowl: vals, until}); };
  el.querySelectorAll('[data-until]').forEach(b => b.onclick = () => send(b.dataset.until));
  CAP.keys = e => {
    if (/INPUT|SELECT|TEXTAREA/.test(e.target.tagName)) return;
    if (/^[1-9]$/.test(e.key)) setBars(bat ? q.striker.id : q.bowler.id, +e.key);
    else if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); send('ball'); }
  };
}
document.addEventListener('keydown', e => { if (CAP.keys) CAP.keys(e); });

/* the XI in batting order, the keeper and the Impact substitutes */
function qXI(q) {
  const by = Object.fromEntries(q.options.map(p => [p.id, p]));
  const cpu = new Set(q.default.xi);
  let xi = [...q.default.xi], keeper = q.default.keeper, subs = [...q.default.subs];
  const maxOS = q.max_overseas, nSubs = q.n_subs;
  const draw = () => {
    const os = xi.filter(id => by[id].overseas).length;
    subs = subs.filter(id => !xi.includes(id));
    const errs = [];
    if (xi.length !== 11) errs.push(`pick 11 (${xi.length} now)`);
    if (maxOS !== null && os > maxOS) errs.push(`at most ${maxOS} overseas (${os} now)`);
    if (!xi.includes(keeper)) errs.push('choose a keeper in the XI');
    const sel = (id, i) => { const p = by[id]; return `<li class="${cpu.has(id) ? 'cpu' : ''}"><span class="n">${i + 1}</span>
      <span class="nm">${esc(p.name)}${osTag(p)}<br><span class="st">${esc(statLine(p))}</span></span>
      <label class="st" title="Wicketkeeper"><input type="radio" name="xi-wk" value="${esc(id)}" ${id === keeper ? 'checked' : ''}> wk</label>
      <button data-up="${i}" title="Bat higher">↑</button><button data-dn="${i}" title="Bat lower">↓</button>
      <button data-rm="${esc(id)}" title="Drop from the XI">✕</button></li>`; };
    const rest = q.options.filter(p => !xi.includes(p.id));
    $('cap-q').innerHTML = `<h3>Name your XI${nSubs ? ` and ${nSubs} Impact substitutes` : ''}</h3>
      <div class="sb-line">${esc(dnText(q.toss, CAP.teams || []))} You ${q.batting_first ? 'bat' : 'bowl'} first.</div>
      <div class="xi-cols">
        <div><div class="lbl" style="margin-top:10px">Batting order</div><ul class="xi-list">${xi.map(sel).join('')}</ul></div>
        <div><div class="lbl" style="margin-top:10px">Rest of the squad</div><ul class="xi-list">${rest.map(p => `<li class="${cpu.has(p.id) ? 'cpu' : ''}">
          <span class="nm">${esc(p.name)}${osTag(p)}<br><span class="st">${esc(statLine(p))}</span></span>
          ${nSubs ? `<label class="st"><input type="checkbox" data-sub="${esc(p.id)}" ${subs.includes(p.id) ? 'checked' : ''}> sub</label>` : ''}
          <button data-add="${esc(p.id)}" title="Add to the XI">+ XI</button></li>`).join('')}</ul></div>
      </div>
      <div class="xi-status">${xi.length}/11 · overseas ${os}${maxOS !== null ? '/' + maxOS : ''} · keeper ${esc((by[keeper] || {}).name || '–')}${nSubs ? ` · substitutes ${subs.length}/${nSubs}` : ''}
        ${errs.length ? `<div class="bad">${errs.join('; ')}</div>` : ''}</div>
      <div class="cap-actions"><button class="btn go" id="xi-ok" ${errs.length ? 'disabled' : ''}>Confirm XI</button>
        <button class="btn sec" id="xi-cpu">Use the suggested XI</button></div>`;
    const el = $('cap-q');
    el.querySelectorAll('[data-up]').forEach(b => b.onclick = () => { const i = +b.dataset.up; if (i > 0) { [xi[i - 1], xi[i]] = [xi[i], xi[i - 1]]; draw(); } });
    el.querySelectorAll('[data-dn]').forEach(b => b.onclick = () => { const i = +b.dataset.dn; if (i < xi.length - 1) { [xi[i + 1], xi[i]] = [xi[i], xi[i + 1]]; draw(); } });
    el.querySelectorAll('[data-rm]').forEach(b => b.onclick = () => { xi = xi.filter(x => x !== b.dataset.rm); draw(); });
    el.querySelectorAll('[data-add]').forEach(b => b.onclick = () => {
      if (xi.length < 11) { xi.push(b.dataset.add); draw(); } else toast('The XI is full - drop someone first.'); });
    el.querySelectorAll('[data-sub]').forEach(b => b.onchange = () => {
      const id = b.dataset.sub;
      subs = b.checked ? [...subs, id] : subs.filter(x => x !== id);
      if (subs.length > nSubs) { subs = subs.filter(x => x !== id); toast(`At most ${nSubs} substitutes.`); }
      draw(); });
    el.querySelectorAll('input[name=xi-wk]').forEach(r => r.onchange = () => { keeper = r.value; draw(); });
    $('xi-ok').onclick = () => capSend({xi, keeper, subs});
    $('xi-cpu').onclick = () => capSend(null);
  };
  draw();
}

document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.cap-skip [data-skip]').forEach(b => b.onclick = () => {
    if (CAP.q && CAP.qid === CAP.q.id) capSend(null, {skip: b.dataset.skip});
  });
});
