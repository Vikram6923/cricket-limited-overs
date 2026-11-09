/* Manual captaincy: the person captains one side (engine/control.py). The server holds the open question in
   /api/status (captain.pending); the answer goes to /api/decide. Every screen shows the computer's choice.
   The live screen: a score bug, a permanent field where each ball plays, this
   over and the players, the striker's bars and an action bar; the bowler, next batter, Impact Player and the
   result open as sheets over it. Before the first ball (toss, XI) the question fills the screen (#cap-pre). */
'use strict';

const KIND_LABEL = {toss: 'Toss', xi: 'Playing XI', bowler: 'Bowlers', batter: 'Next batter', impact: 'Impact Player',
  result: 'Stop after each of my matches', ball: 'Ball by ball'};
const CAP = {qid: null, q: null, auto: {}, manual: [], impact: true, view: 'st', vals: {}, land: null, striker: null};
const n1 = v => v === null || v === undefined ? '–' : v;
const statLine = p => [p.role + (p.kind && p.role !== 'Batter' && p.role !== 'WK' ? ` (${p.kind})` : ''),
  p.bat_avg ? `bat avg ${p.bat_avg}, SR ${p.bat_sr}` : '', p.bowl_econ && p.overs_per_match >= 0.5 ? `bowl econ ${p.bowl_econ}, ${p.overs_per_match} ov/match` : ''].filter(Boolean).join(' · ');
const osTag = p => p.overseas ? '<span class="os-tag">OS</span>' : '';
const sur = n => String(n || '').trim().split(/\s+/).pop();
const isSpin = k => /break|orthodox|googly|chinaman|spin|slow/i.test(k || '');
const KIND_ICON = {
  pace: '<svg class="kind" viewBox="0 0 24 24" fill="none" stroke="#ff9a76" stroke-width="2" aria-label="pace"><circle cx="15" cy="12" r="5"/><path d="M2 9h6M3 13h5M2 17h7"/></svg>',
  spin: '<svg class="kind" viewBox="0 0 24 24" fill="none" stroke="#9ed1ff" stroke-width="2" aria-label="spin"><circle cx="12" cy="12" r="5"/><path d="M4 8a9 9 0 0 1 14-3M20 16a9 9 0 0 1-14 3M18 2v4h-4M6 22v-4h4"/></svg>'};
const kindIcon = k => KIND_ICON[isSpin(k) ? 'spin' : 'pace'];
const sheetOpen = () => $('bsheet').classList.contains('on');

function capRender(st) {
  const cap = st.captain, q = cap.pending;
  $('cap-progress').textContent = st.total > 1 ? `${st.done} of ${st.total} matches played` : '';
  $('cap-skip-all').style.display = st.total > 1 ? '' : 'none';      // no "rest of the season" in a single match
  CAP.total = st.total;
  if (!q) {
    if (CAP.qid === 'sent' && Date.now() - CAP.sentAt < 1500) return;   // the next ball is a moment away
    if (CAP.qid !== 'wait') { CAP.qid = 'wait'; capWait('Playing on…'); }
    return;
  }
  if (q.id === CAP.qid) return;
  CAP.qid = q.id; CAP.q = q; CAP.manual = cap.manual; CAP.auto = {};
  CAP.land = null;                            // a replay still playing from the last question must not land on this one
  const c = q.context || {}, s = q.state || {};
  const tt = capTeams(q); setDisplayTeams(tt.filter(Boolean));
  $('cap-title').innerHTML = `You captain ${badge(q.team, 'sm')} ${esc(dn(q.team))}`;
  $('cap-ctx').textContent = [c.stage, c.match_no && c.stage !== 'Match ' + c.match_no ? 'match ' + c.match_no : '', s.venue || 'neutral venue',
    s.pitch ? 'pitch: ' + s.pitch : ''].filter(Boolean).join(' · ');
  $('cap-score').innerHTML = scoreHTML(q);
  renderAuto();
  const ask = {toss: qToss, xi: qXI, bowler: q2 => qPick(q2, 'bowler'), batter: q2 => qPick(q2, 'batter'), impact: qImpact,
    result: qResult, ball: qBall}[q.kind] || qResult;
  if (s.runs === undefined) {                 // before the first ball: the question fills the screen
    capMode(false); closeSheet(); CAP.keys = null; HL.stop();
    $('cap-bug').innerHTML = bugHTML(q);
    ask(q);
    return;
  }
  capMode(true);
  capReplay(q, ask);
}

/* the live layout on or off (#cap-live vs the full-screen question #cap-pre) */
function capMode(live) {
  const v = $('v-captain'), was = v.classList.contains('live');
  v.classList.toggle('live', live);
  if (live && !was && !$('hl-box').firstChild) HL.idle($('hl-box'), {});
}

/* play the balls since the last question in the field, then show the new state and the question. The score, this
   over and the players change when the last ball lands; a decision sheet opens a moment later. While a replay
   plays, the main button (and Space) skips it; after a single ball the same press also bowls the next one, so
   quick play never needs two presses. */
const MAIN_LABEL = {ball: '&#9654;&nbsp; Next ball <kbd class="full-only">Space</kbd>', bowler: 'Choose the bowler',
  batter: 'Choose the batter', impact: 'Impact Player'};
function capReplay(q, ask) {
  const evs = q.since || [];
  const land = now => {
    if (CAP.land !== land) return;
    CAP.land = null; CAP.keys = null;
    liveState(q);
    if (q.kind === 'ball' || now) ask(q);
    else setTimeout(() => { if (CAP.q === q && CAP.qid === q.id) ask(q); }, evs.length ? 650 : 0);
  };
  CAP.land = land;
  const skip = () => {
    if (CAP.land !== land) return;
    HL.stop(); land(true);
    if (q.kind === 'ball' && evs.length <= 2) $('cap-main').click();
  };
  actMain(MAIN_LABEL[q.kind] || mpResultNext(), skip, false);
  $('cap-over-btn').style.display = q.kind === 'ball' ? '' : 'none';
  CAP.keys = e => {
    if (/INPUT|SELECT|TEXTAREA/.test(e.target.tagName) || sheetOpen()) return;
    if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); skip(); }
  };
  if (!evs.length) { land(); if (q.kind === 'ball') HL.idle($('hl-box'), nextBall(q)); return; }
  HL.play(evs, $('hl-box'), {onLand: () => land(false)});
}
function nextBall(q) {
  return {phase: q.phase, plan: q.side === 'bowl' ? (q.bowler.bars || 5) : 5, bowl_type: isSpin(q.bowler.kind) ? 'spin' : 'pace',
    bowler: q.bowler.name, batter: q.striker.name, foot: q.free_hit ? 'Free hit' : ''};
}

/* the score bug, this over and the one-line player cards, from a question (or a bare state: two players waiting) */
function liveState(q) {
  const s = q.state || {};
  $('cap-bug').innerHTML = bugHTML(q);
  $('cap-cards').innerHTML = cardsHTML(q);
  if (q.kind === 'wait') return;              // two players, the other side choosing: this over stays as it was
  let balls = q.this_over;
  if (!balls) {                               // between balls: the over so far, from the balls just shown
    const evs = (q.since || []).filter(e => e.innings === s.innings), last = evs[evs.length - 1];
    balls = last ? evs.filter(e => e.over === last.over).map(e => e.sym) : [];
  }
  const legal = balls.filter(b => !/wd|nb/.test(b)).length;
  $('cap-over').innerHTML = balls.map((b, i) => i === balls.length - 1 && (q.since || []).length
    ? chip(b, true).replace('class="ball', 'class="ball pop') : chip(b, true)).join('')
    + '<span class="ball sm empty"></span>'.repeat(Math.max(0, 6 - legal));
  const say = [];
  const lb = mpOn() && q.since && q.since.length ? q.since[q.since.length - 1] : null;   // two players: both choices
  if (lb && lb.bars) say.push(`${esc(sur(lb.batter))} <b>${BAT_WORD[lb.bars]}</b> v ${esc(sur(lb.bowler))} <b>${BOWL_WORD[lb.plan]}</b>`);
  if (q.kind === 'ball' && q.side === 'bat') {           // the strike changed: say so for a second
    if (CAP.striker && CAP.striker !== q.striker.id) say.push(`<b>${esc(sur(q.striker.name))}</b> on strike: ${BAT_WORD[q.striker.bars]}`);
    CAP.striker = q.striker.id;
  }
  if (say.length) liveToast(say.join('<br>'), lb ? 1800 : 1100);
  if (q.kind !== 'ball') $('cap-bars').innerHTML = '';
}
function liveToast(html, ms = 1100) {
  const t = $('cap-toast'); t.innerHTML = html; t.classList.add('on');
  clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove('on'), ms);
}
function cardsHTML(q) {
  const s = q.state || {};
  if (!s.batters) return '';
  const crease = s.batters.filter(x => x.at_crease).sort((x, y) => (y.on_strike ? 1 : 0) - (x.on_strike ? 1 : 0));
  const more = q.kind === 'ball' ? {[q.striker.name]: q.striker, [q.non_striker.name]: q.non_striker} : {};
  const pl = x => {
    const m = more[x.name];
    return `<span class="pl ${x.on_strike ? 'st' : ''}"><b>${esc(x.name)}${x.on_strike ? '*' : ''}</b> <span class="num">${x.runs} (${x.balls})</span>${x.balls < 10 ? '<span class="new-tag simple-only" title="New at the crease">NEW</span>' : ''}${m
      ? `<span class="fs full-only"><i><u style="width:${Math.round(100 * m.settled)}%"></u></i>settled ${Math.round(100 * m.settled)}% · usual SR ${n1(m.sr)}</span>` : ''}</span>`;
  };
  const bn = q.kind === 'ball' ? q.bowler.name : (s.recent && s.recent.length ? s.recent[s.recent.length - 1].bowler : '');
  const f = (s.bowlers || []).find(b => b.name === bn);
  const balls = o => { const [p, r] = String(o).split('.').map(Number); return 6 * p + (r || 0); };
  const bw = bn ? `<div class="bw">${kindIcon(q.kind === 'ball' ? q.bowler.kind : '')}<b>${esc(bn)}</b>${f ? `<span class="num">${f.wkts}-${f.runs} (${esc(f.overs)})</span>
    <span class="full-only small">econ ${balls(f.overs) ? (6 * f.runs / balls(f.overs)).toFixed(1) : '–'}${q.kind === 'ball' ? ` · expected ${n1(q.bowler.econ)}` : ''}</span>` : ''}</div>` : '';
  return `<div class="ln">${crease.map(pl).join('')}</div>${bw}`;
}

/* the action bar: the main button (Next ball, or reopen the open question) and Sim over */
function btns(disabled) { $('cap-act').querySelectorAll('button').forEach(b => { if (b.id !== 'cap-more-btn') b.disabled = disabled; }); }
function actMain(label, fn, sim) {
  const m = $('cap-main');
  m.innerHTML = label; m.onclick = fn; m.disabled = !fn;
  $('cap-over-btn').style.display = sim ? '' : 'none'; $('cap-over-btn').disabled = !sim;
}
/* a message where the question would be (waiting for the other player, playing on) */
function capWait(msg) {
  CAP.keys = null;
  if ($('v-captain').classList.contains('live')) { actMain(`<span class="cl-wait">${msg}</span>`, null, false); if (CAP.sheetKind !== 'more' && CAP.sheetKind !== 'card') closeSheet(); }
  else $('cap-q').innerHTML = `<div class="muted">${msg}</div>`;
}
/* the score without a question (two players: the other side is choosing; watching) */
function capShowState(state, team) {
  if (!state) return;
  const q = {state, team, kind: 'wait'};
  capTeams(q);
  if (state.runs === undefined) { capMode(false); $('cap-bug').innerHTML = bugHTML(q); return; }
  capMode(true); liveState(q);
  $('cap-score').innerHTML = scoreHTML(q);
}

function renderAuto() {
  if (CAP.manual.includes('ball')) CAP.ballOn = true;
  const kinds = Object.keys(KIND_LABEL).filter(k => (k !== 'impact' || CAP.impact || CAP.manual.includes('impact'))
    && (k !== 'result' || (!mpOn() && CAP.total > 1))
    && (k !== 'ball' || CAP.ballOn));
  const computer = k => CAP.auto[k] !== undefined ? CAP.auto[k] : !CAP.manual.includes(k);
  $('cap-auto').innerHTML = kinds.map(k => `<button class="tog ${computer(k) ? '' : 'on'}" data-k="${k}"
    title="${computer(k) ? 'The computer decides - click to decide yourself' : 'You decide - click to leave it to the computer'}">${KIND_LABEL[k]}</button>`).join('');
  $('cap-auto').querySelectorAll('.tog').forEach(b => b.onclick = () => { CAP.auto[b.dataset.k] = !computer(b.dataset.k); renderAuto(); });
}

const mpOn = () => typeof MP !== 'undefined' && MP.active;      // two players (multiplayer.js)
async function capSend(choice, extra = {}) {
  const mp = mpOn();
  if (CAP.land) { HL.stop(); CAP.land = null; liveState(CAP.q); }   // pressed during the replay: the ball lands at once
  CAP.keys = null; CAP.qid = 'sent'; CAP.sentAt = Date.now();
  btns(true); closeSheet();
  try { await api(mp ? '/api/mp/decide' : '/api/decide', {id: CAP.q.id, choice, auto: CAP.auto, ...extra, ...(mp ? {token: MP.token} : {})}); }
  catch (e) { toast(e.message, true); }
  if (!$('v-captain').classList.contains('live')) $('cap-q').innerHTML = '<div class="muted">Playing on…</div>';
  clearTimeout(POLL_T); POLL_T = setTimeout(mp ? mpPoll : poll, 120);
}

/* a question's screen: a sheet over the live screen, or the whole screen before the first ball */
function capShow(kind, html, label) {
  if ($('v-captain').classList.contains('live')) {
    CAP.sheetKind = kind; openSheet(html);
    actMain(label, () => { const q = CAP.q; ({bowler: q2 => qPick(q2, 'bowler'), batter: q2 => qPick(q2, 'batter'), impact: qImpact, result: qResult}[kind] || (() => {}))(q); }, false);
    btns(false); $('cap-over-btn').style.display = 'none';
  } else $('cap-q').innerHTML = html;
}

const ballClass = b => ballCls(b);

/* the two sides: from "A v B" (the match name) or the question's team and its opponent */
function capTeams(q) {
  const s = q.state || {}, m = String(s.match || '').split(' v ');
  if (m.length === 2) CAP.teams = m;
  else if (s.opponent) CAP.teams = [q.team, s.opponent];
  return CAP.teams || [q.team, s.opponent || ''];
}
/* the score bug: before the match, the two teams; then one line (score, overs, the chase) and the win bar */
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
  const right = q.kind === 'result' && q.result ? esc(dnText(q.result, [a, b]))
    : over ? (s.need === 1 ? 'Scores level' : `<b>${esc(tcol(bowl).short)}</b> have won`)
    : s.target ? (s.need <= 0 ? `<b>${esc(tcol(bat).short)}</b> have won`
      : `Need <b>${s.need}</b> off <b>${s.balls_left}</b>${s.rrr !== null && s.rrr !== undefined ? `<span class="full-only"> · RRR ${s.rrr}</span>` : ''}<span class="full-only"><br>${esc(tcol(bowl).short)} ${esc(prev)}</span>`)
    : `${esc(tcol(bowl).short)} yet to bat${q.projected ? `<span class="full-only"><br>Projected <b>${q.projected}</b></span>` : ''}`;
  return `<div class="bug live" style="--bat:${tcol(bat).c};--bowl:${tcol(bowl).c}">
    <div class="bl">${badge(bat, 'sm')}<span class="sc">${s.runs}/${s.wkts}</span><span class="ov">${esc(s.overs_done)}<small> ov</small></span>${bat === q.team ? '<span class="you">you</span>' : ''}</div>
    <div class="br">${right}</div>
    ${wp !== null ? `<div class="wp"><i style="background:${tcol(bat).hi};width:${wp}%"></i><i style="background:${tcol(bowl).hi};width:${100 - wp}%"></i></div>
    <div class="wplab"><span>${wp}% ${esc(tcol(bat).short)}</span><span class="full-only">Partnership ${s.partnership.runs} (${s.partnership.balls})</span><span>${s.crr !== null && s.crr !== undefined ? `CRR ${s.crr}` : ''}</span></div>` : ''}
  </div>`;
}

/* the full scorecard (More > Full scorecard) */
function scoreHTML(q) {
  const s = q.state || {};
  if (s.runs === undefined) {           // before the match: toss and XI
    return `<h3>${esc(dnText(s.match, capTeams(q)))}</h3>
      <div class="sb-line">${s.format === 'odi' ? 'ODI' : 'T20'}, ${s.overs} overs a side · v ${esc(dn(s.opponent))}</div>
      <div class="sb-line">Venue: <b>${esc(s.venue || 'neutral')}</b></div>
      <div class="sb-line">Pitch: <b>${esc(s.pitch || '–')}</b></div>
      ${q.toss ? `<div class="sb-line" style="margin-top:6px">${esc(q.toss)}</div>` : ''}
      ${(s.rain || []).map(r => `<div class="sb-line">☂ ${esc(r)}</div>`).join('')}`;
  }
  const [a, b] = capTeams(q), batT = s.batting;
  const bat = s.batters.filter(x => x.batted);
  const yet = s.batters.filter(x => !x.batted).map(x => esc(x.name)).join(', ');
  const balls = o => { const [p, r] = String(o).split('.').map(Number); return 6 * p + (r || 0); };
  return `<h3>Scorecard · ${esc(dn(batT))}</h3>
    <div class="sb-line">${esc(s.venue || 'Neutral venue')}${s.pitch ? ' · pitch: ' + esc(s.pitch) : ''}</div>
    <table class="mini"><tr><th>Batter</th><th></th><th>R</th><th>B</th><th>4s</th><th>6s</th><th>SR</th></tr>
    ${bat.map(x => `<tr class="${x.at_crease ? 'crease' : x.out ? 'dim' : ''}"><td>${esc(x.name)}${x.on_strike ? ' *' : ''}</td>
      <td class="how">${x.out ? esc(x.how) : x.at_crease ? 'batting' : 'not out'}</td><td>${x.runs}</td><td>${x.balls}</td>
      <td>${x.fours}</td><td>${x.sixes}</td><td>${x.balls ? (100 * x.runs / x.balls).toFixed(0) : '–'}</td></tr>`).join('')}</table>
    ${yet ? `<div class="sb-line" style="margin-top:6px">Yet to bat: ${yet}</div>` : ''}
    <table class="mini"><tr><th>Bowler</th><th>O</th><th>M</th><th>R</th><th>W</th><th>Econ</th></tr>
    ${s.bowlers.map(x => `<tr><td>${esc(x.name)}</td><td>${x.overs}</td><td>${x.maidens}</td><td>${x.runs}</td><td>${x.wkts}</td>
      <td>${balls(x.overs) ? (6 * x.runs / balls(x.overs)).toFixed(1) : '–'}</td></tr>`).join('')}</table>
    ${s.recent.length ? `<div class="lbl" style="margin-top:14px">Recent overs</div><div class="overs">${s.recent.map(o => `<div class="orow"><span class="muted">Over ${o.over} · ${esc(o.bowler)}</span>
      <span class="balls">${o.balls.map(x => chip(x, true)).join('')}</span><b>${o.runs}</b></div>`).join('')}</div>` : ''}
    ${s.events.length ? `<div class="evs">${s.events.map(e => esc(dnText(e, [a, b]))).join('<br>')}</div>` : ''}`;
}

const cpuTag = on => on ? '<span class="cpu-tag">SUGGESTED</span>' : '';
const optCard = (p, isCpu, extra) => `<button class="opt ${isCpu ? 'cpu' : ''}" data-id="${esc(p.id)}">${cpuTag(isCpu)}
  <b>${esc(p.name)}${osTag(p)}</b>${extra}</button>`;
const nameOf = (list, id) => (list.find(p => p.id === id) || {}).name || '–';

function qToss(q) {
  $('cap-q').innerHTML = `<h3>${esc(dnText(q.text, CAP.teams || []))} Bat or bowl?</h3>
    <div class="opts">${q.options.map(o => `<button class="opt ${o === q.default ? 'cpu' : ''}" data-id="${o}">${cpuTag(o === q.default)}
      <b>${o === 'bat' ? 'Bat first' : 'Bowl first'}</b></button>`).join('')}</div>`;
  $('cap-q').querySelectorAll('.opt').forEach(b => b.onclick = () => capSend(b.dataset.id));
}

/* Impact Player: the computer's suggestion, who comes in and who goes out */
function impactBoxHTML(imp, standalone) {
  if (!imp) return '';
  const all = [...imp.ins, ...imp.outs], sg = imp.suggestion;
  const outName = sg ? nameOf(all, sg.out) : '–';           // not listed when he is at the crease now
  const say = sg ? `Suggested: <b>${esc(nameOf(all, sg.in))}</b>${outName !== '–' ? ` for <b>${esc(outName)}</b>` : ''} (+${sg.gain} runs expected).`
    : 'Suggested: not now.';
  return `<div class="${standalone ? '' : 'impact-box'}">
    ${standalone ? '' : `<div class="sb-line">${say}</div>`}
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

/* bowler for the next over / batter after a wicket: the suggestion and the next two, the rest behind See all */
function qPick(q, kind) {
  const imp = q.impact, ph = (q.options[0] || {}).phase;
  const fig = p => q.state.bowlers.find(b => b.name === p.name) || {overs: '0.0', maidens: 0, runs: 0, wkts: 0};
  const card = p => {
    const sug = p.id === q.default, tag = sug ? '<span class="tag-s">SUGGESTED</span>' : '';
    if (kind === 'bowler') {
      const f = fig(p);
      return `<button class="bopt ${sug ? 'sug' : ''}" data-id="${esc(p.id)}">${kindIcon(p.kind)}<div class="bo-m"><b>${esc(p.name)}${osTag(p)}${tag}</b>
        <span class="fig">${f.overs}-${f.maidens}-${f.runs}-${f.wkts}</span>
        <span class="full-only small">${esc(p.kind || p.role)} · expected econ${ph ? ' (' + ph + ')' : ''} ${n1(p.phase_econ)} · career ${n1(p.bowl_econ)}</span></div>
        <span class="left"><b>${esc(p.quota_left)}</b> left</span></button>`;
    }
    return `<button class="bopt ${sug ? 'sug' : ''}" data-id="${esc(p.id)}"><div class="bo-m"><b>${esc(p.name)}${osTag(p)}${tag}</b>
      <span class="fig">${esc(p.role)}</span>
      <span class="full-only small">avg ${n1(p.bat_avg)} · SR ${n1(p.bat_sr)} · expected SR${ph ? ' (' + ph + ')' : ''} ${n1(p.phase_sr)}</span></div>
      ${p.slot ? `<span class="left full-only">#${p.slot}</span>` : ''}</button>`;
  };
  let all = false;
  const draw = () => {
    const use = $('ib-use') && $('ib-use').checked, ic = use ? impactChoice(imp) : null;
    let opts = q.options;
    const rank = kind === 'bowler'                // the computer's pick, then real bowlers by expected economy
      ? p => (p.id === q.default ? -1e6 : 0) + (p.overs_per_match >= 1 ? 0 : 1000) + (p.phase_econ || 99)
      : p => (p.id === q.default ? -1e6 : 0) + opts.indexOf(p);
    opts = [...opts].sort((a, b) => rank(a) - rank(b));
    if (ic && ic !== 'bad') {                     // the substitute can bowl / bat at once
      const sub = imp.ins.find(p => p.id === ic.in);
      opts = opts.filter(p => p.id !== ic.out).concat([{...sub, quota_left: 'full', role: sub.role + ' - Impact sub'}]);
    }
    $('cap-opts').innerHTML = (all ? opts : opts.slice(0, 3)).map(card).join('');
    $('cap-all').style.display = all || opts.length <= 3 ? 'none' : '';
    $('cap-opts').querySelectorAll('.bopt').forEach(b => b.onclick = () => {
      const c = $('ib-use') && $('ib-use').checked ? impactChoice(imp) : null;
      if (c === 'bad') return;
      capSend(kind === 'bowler' ? {bowler: b.dataset.id, impact: c} : {batter: b.dataset.id, impact: c});
    });
  };
  capShow(kind, `<h3>${kind === 'bowler' ? `Over ${q.over}: who bowls?` : 'Wicket! Who’s in?'}</h3>
    <div id="cap-opts"></div><button class="lnk" id="cap-all">See all ${kind === 'bowler' ? 'bowlers' : 'batters'}</button>
    ${imp ? `<details class="ib-fold"><summary>Impact Player${imp.suggestion ? '<span class="tag-s">SUGGESTED</span>' : ''}</summary>${impactBoxHTML(imp, false)}</details>` : ''}`,
    kind === 'bowler' ? 'Choose the bowler' : 'Choose the batter');
  draw();
  $('cap-all').onclick = () => { all = true; draw(); };
  ['ib-use', 'ib-in', 'ib-out'].forEach(id => { if ($(id)) $(id).onchange = draw; });
}

/* Impact Player on its own: one card (bring on X for Y?) with Yes / Not now; anyone else behind a fold */
function qImpact(q) {
  const imp = q.impact, sg = imp.suggestion, all = [...imp.ins, ...imp.outs];
  capShow('impact', sg
    ? `<h3>Impact Player</h3>
      <div class="ib-card">Bring on <b>${esc(nameOf(all, sg.in))}</b> for <b>${esc(nameOf(all, sg.out))}</b>? <span class="muted">(+${sg.gain} runs expected)</span></div>
      <div class="sh-row"><button class="btn go" id="ib-yes">Yes</button><button class="btn sec" id="ib-wait">Not now</button></div>
      <details class="ib-fold"><summary>Someone else</summary>${impactBoxHTML(imp, true)}
        <button class="btn sec" id="ib-make" style="margin-top:8px">Make this substitution</button></details>`
    : `<h3>Impact Player</h3><div class="sb-line">${esc(q.moment)}: the suggestion is to wait.</div>${impactBoxHTML(imp, true)}
      <div class="sh-row"><button class="btn sec" id="ib-make">Make this substitution</button><button class="btn go" id="ib-wait">Not now</button></div>`,
    'Impact Player');
  $('ib-make').onclick = () => { const c = impactChoice(imp); if (c && c !== 'bad') capSend(c); };
  if ($('ib-yes')) $('ib-yes').onclick = () => capSend(null);
  $('ib-wait').onclick = () => capSend({});
}

function qResult(q) {
  capShow('result', `<h3>${esc(dnText(q.result || 'Match over', CAP.teams || []))}</h3>
    ${(q.scores || []).map(s => `<div class="sb-line">${esc(dnText(s, CAP.teams || []))}</div>`).join('')}
    ${q.pom && q.pom.name ? `<div class="sb-line">Player of the match: <b>${esc(q.pom.name)}</b> (${esc(dn(q.pom.team))})</div>` : ''}
    ${mpResultSeries()}
    <div class="cap-actions"><button class="btn go" id="cap-cont">${mpResultNext()}</button></div>`, mpResultNext());
  $('cap-cont').onclick = () => capSend(null);
  if ($('v-captain').classList.contains('live')) $('cap-main').onclick = () => capSend(null);
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

/* ball by ball: aggression bars (1-9, 5 = as real sides play this situation; docs/match_play_design.md). Only the
   striker's bars show; a chip opens the non-striker's. Simple shows the word, Full the number too. */
const BAT_WORD = {1: 'Block', 2: 'Defend', 3: 'Careful', 4: 'Steady', 5: 'Normal', 6: 'Positive', 7: 'Attack',
  8: 'Hit out', 9: 'Slog'};
const BOWL_WORD = {1: 'Contain', 2: 'Very tight', 3: 'Tight', 4: 'Steady', 5: 'Normal', 6: 'Probing', 7: 'Attack',
  8: 'Very attacking', 9: 'All-out attack'};
function barsHTML(key, val, words) {
  return `<div class="cbars" data-key="${esc(key)}" role="radiogroup">${[1, 2, 3, 4, 5, 6, 7, 8, 9].map(i =>
    `<button class="${i === val ? 'on' : i < val ? 'lit' : ''} ${i === 5 ? 'mid' : ''}" data-v="${i}" title="${i}: ${words[i]}" aria-label="${words[i]}"
      style="--bc:hsl(${215 - (i - 1) * 27},85%,${i === 5 ? 60 : 56}%)"><i style="height:${30 + i * 7.5}%"></i><small class="full-only">${i}</small></button>`).join('')}</div>`;
}
function qBall(q) {
  const bat = q.side === 'bat';
  CAP.vals = {}; CAP.view = 'st';
  if (bat) { CAP.vals[q.striker.id] = q.striker.bars; CAP.vals[q.non_striker.id] = q.non_striker.bars; }
  else CAP.vals[q.bowler.id] = q.bowler.bars;
  drawBars();
  const send = until => { CAP.keys = null; HL.stop(); capSend(bat ? {bat: CAP.vals, until} : {bowl: CAP.vals, until}); };
  actMain(MAIN_LABEL.ball, () => send('ball'), true);
  btns(false);
  $('cap-over-btn').onclick = () => send('over');
  $('cap-sim-wkt').onclick = () => { closeSheet(); send('wicket'); };
  CAP.keys = e => {
    if (/INPUT|SELECT|TEXTAREA/.test(e.target.tagName) || sheetOpen()) return;
    if (/^[1-9]$/.test(e.key)) setBars(+e.key);
    else if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); send('ball'); }
  };
}
function drawBars() {
  const q = CAP.q, bat = q.side === 'bat';
  const who = bat ? (CAP.view === 'ns' ? q.non_striker : q.striker) : q.bowler, other = CAP.view === 'ns' ? q.striker : q.non_striker;
  const words = bat ? BAT_WORD : BOWL_WORD, v = CAP.vals[who.id];
  $('cap-bars').innerHTML = `<div class="bars-h"><span class="who"><b>${esc(sur(who.name))}</b>’s ${bat ? 'approach' : 'plan'}</span>
      <button class="info" id="cap-info" title="How the bars work">i</button>
      ${bat ? `<button class="ns-chip" id="cap-ns">${CAP.view === 'ns' ? 'Back to striker' : `${esc(sur(other.name))}: ${BAT_WORD[CAP.vals[other.id]]} &#9662;`}</button>` : ''}
      <span class="word"><small class="full-only">${v} · </small>${words[v]}</span></div>${barsHTML(who.id, v, words)}`;
  $('cap-bars').querySelectorAll('.cbars button').forEach(b => b.onclick = () => setBars(+b.dataset.v));
  if ($('cap-ns')) $('cap-ns').onclick = () => { CAP.view = CAP.view === 'ns' ? 'st' : 'ns'; drawBars(); };
  $('cap-info').onclick = () => { CAP.sheetKind = 'info'; openSheet(bat
    ? `<h3>Approach</h3><p>Higher = more runs, more risk. 5 is how real teams bat here.</p><p class="muted" style="margin-top:8px">Keys 1–9, Space = next ball.</p>
       <p class="muted small full-only" style="margin-top:8px">Lower: fewer of both. Far from 5 costs, more so when a wicket is dear. Each batter keeps his own bars, so they swap with the strike.</p>`
    : `<h3>Plan</h3><p>Higher = more wickets, more runs. 5 is a normal plan.</p><p class="muted" style="margin-top:8px">Keys 1–9, Space = next ball.</p>
       <p class="muted small full-only" style="margin-top:8px">Attack takes more wickets but leaks runs; contain saves runs but takes fewer wickets.</p>`); };
}
function setBars(v) {
  const q = CAP.q;
  if (!q || q.kind !== 'ball') return;
  const who = q.side === 'bat' ? (CAP.view === 'ns' ? q.non_striker : q.striker) : q.bowler;
  CAP.vals[who.id] = v;
  drawBars();
}
document.addEventListener('keydown', e => { if (CAP.keys) CAP.keys(e); });

/* the XI: the suggested side as a list and one button; editing (order, keeper, swaps, substitutes) behind Edit */
function qXI(q) {
  const by = Object.fromEntries(q.options.map(p => [p.id, p]));
  const cpu = new Set(q.default.xi);
  let xi = [...q.default.xi], keeper = q.default.keeper, subs = [...q.default.subs];
  const maxOS = q.max_overseas, nSubs = q.n_subs;
  const ROLE_ICON = {WK: '🧤', Batter: '🏏', 'All-rounder': '✦', Pace: '●', Spin: '◐'};
  const compact = () => {
    $('cap-q').innerHTML = `<h3>Your XI</h3>
      <div class="sb-line">${esc(dnText(q.toss, CAP.teams || []))} You ${q.batting_first ? 'bat' : 'bowl'} first.</div>
      <ol class="xi-compact">${xi.map(id => { const p = by[id]; return `<li><span class="ri" title="${esc(p.role)}">${ROLE_ICON[p.role] || '·'}</span>${esc(p.name)}${osTag(p)}${id === keeper ? ' <span class="muted small">(wk)</span>' : ''}</li>`; }).join('')}</ol>
      ${nSubs && subs.length ? `<div class="sb-line full-only">Impact substitutes: ${subs.map(id => esc(by[id].name)).join(', ')}</div>` : ''}
      <div class="cap-actions"><button class="btn go big" id="xi-cpu">Use this XI</button><button class="btn sec" id="xi-edit">Edit</button></div>`;
    $('xi-cpu').onclick = () => capSend(null);
    $('xi-edit').onclick = draw;
  };
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
  compact();
}

/* the More sheet: Sim, highlights, my decisions, detail, the full scorecard, stop */
function moreSheet() {
  CAP.sheetKind = 'more'; openSheet('');
  $('bsheet-in').appendChild($('cap-more'));
  const ball = CAP.q && CAP.q.kind === 'ball' && CAP.qid === CAP.q.id;
  $('cap-sim-wkt').style.display = ball ? '' : 'none';
  $('cap-hl').innerHTML = HL.segHTML();
  $('cap-hl').querySelectorAll('button').forEach(b => b.onclick = () => {
    HL.setLevel(b.dataset.h); $('cap-hl').querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b)); });
  const det = () => $('cap-more').querySelectorAll('.cap-detail button').forEach(b => b.classList.toggle('on', document.body.classList.contains('detail-full') === (b.dataset.d === 'full')));
  $('cap-more').querySelectorAll('.cap-detail button').forEach(b => b.onclick = () => { setDetail(b.dataset.d); det(); });
  det();
}

document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.cap-skip [data-skip]').forEach(b => b.onclick = () => {
    if (CAP.q && CAP.qid === CAP.q.id) { closeSheet(); capSend(null, {skip: b.dataset.skip}); }
  });
  $('cap-more-btn').onclick = moreSheet;
  $('cap-card-btn').onclick = () => { CAP.sheetKind = 'card'; openSheet(''); $('bsheet-in').appendChild($('cap-score')); };
  $('cap-stop-btn').onclick = () => { if (confirm('Stop this match?')) { closeSheet(); stopJob(); } };
});
