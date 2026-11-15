/* Captaining a Test (engine/test_control.py): what the captain screen (captain.js) shows differently in a Test.
   The score bug has the day, the session, the overs left and three chances (win, draw, loss); the bars are set
   before an over, not a ball; and four questions exist only here: declare, follow-on, new ball, nightwatchman.
   Every question shows the computer's call; where the win / draw / loss table exists, the chances either way. */
'use strict';

const capTest = q => !!q && ((q.state || {}).format === 'test');
const SESSION_NAME = ['morning', 'afternoon', 'evening'];
const pc = x => Math.round(100 * x);
/* "win 44% · draw 51% · lose 5%" from [win, draw] */
const wdlText = v => v ? `win <b>${pc(v[0])}%</b> · draw <b>${pc(v[1])}%</b> · lose <b>${pc(Math.max(0, 1 - v[0] - v[1]))}%</b>` : '';

function testBugHTML(q) {
  const s = q.state || {}, [a, b] = capTeams(q);
  if (s.runs === undefined) {
    return `<div class="bug pre" style="--bat:${tcol(a).c};--bowl:${tcol(b).c}">
      <div class="tm">${badge(a, 'md')}<div><div class="lbl">${a === q.team ? 'You' : 'Opponent'}</div><div class="nm">${esc(dn(a))}</div></div></div>
      <div class="mid"><div class="need">Test · ${s.days} days</div><div class="muted small">${esc(s.venue || 'Neutral venue')} · pitch: ${esc(s.pitch || '–')}</div></div>
      <div class="tm r">${badge(b, 'md')}<div><div class="lbl">${b === q.team ? 'You' : 'Opponent'}</div><div class="nm">${esc(dn(b))}</div></div></div></div>`;
  }
  const bat = s.batting, bowl = bat === a ? b : a, w = s.wdl;
  const time = `Day <b>${s.day}</b>, ${SESSION_NAME[s.session - 1]} · <b>${s.left_today}</b> ov left today`;
  const where = s.target ? (s.need > 0 ? `Need <b>${s.need}</b> · ${s.left} overs left in the match` : `<b>${esc(tcol(bat).short)}</b> have won`)
    : s.margin ? esc(s.margin.charAt(0).toUpperCase() + s.margin.slice(1)) : '1st innings';
  const right = q.kind === 'result' && q.result ? esc(dnText(q.result, [a, b]))
    : `${time}<br>${where}${s.previous && s.previous.length ? `<span class="full-only"><br>${esc(dnText(s.previous.join(' · '), [a, b]))}</span>` : ''}`;
  const bar = w && q.kind !== 'result' ? `<div class="wp wdl3"><i style="background:${tcol(bat).hi};width:${pc(w[0])}%"></i><i class="dr" style="width:${pc(w[1])}%"></i><i style="background:${tcol(bowl).hi};width:${pc(w[2])}%"></i></div>
    <div class="wplab"><span>${pc(w[0])}% ${esc(tcol(bat).short)}</span><span>Draw ${pc(w[1])}%</span><span>${pc(w[2])}% ${esc(tcol(bowl).short)}</span></div>` : '';
  return `<div class="bug live test" style="--bat:${tcol(bat).c};--bowl:${tcol(bowl).c}">
    <div class="bl">${badge(bat, 'sm')}<span class="sc">${s.runs}/${s.wkts}</span><span class="ov">${esc(s.overs_done)}<small> ov</small></span>${bat === q.team ? '<span class="you">you</span>' : ''}</div>
    <div class="br">${right}</div>${bar}</div>`;
}

/* two ways, each with its chances; `cpu` marks the computer's call */
function twoWays(title, lines, yes, no, cpuYes, advYes, advNo, note) {
  const opt = (id, label, adv, cpu, go) => `<button class="bopt ${cpu ? 'sug' : ''}" id="${id}"><div class="bo-m"><b>${label}${cpu ? '<span class="tag-s">COMPUTER\'S CALL</span>' : ''}</b>
    ${adv ? `<span class="small" style="display:block">${wdlText(adv)}</span>` : ''}</div></button>`;
  return `<h3>${title}</h3>${lines.filter(Boolean).map(l => `<div class="sb-line">${l}</div>`).join('')}
    <div style="margin-top:10px">${opt('tw-yes', yes, advYes, cpuYes)}${opt('tw-no', no, advNo, !cpuYes)}</div>
    ${note ? `<div class="hint">${note}</div>` : ''}`;
}
function twoWire() {
  $('tw-yes').onclick = () => capSend(true);
  $('tw-no').onclick = () => capSend(false);
}

function qDeclare(q) {
  const s = q.state, a = q.advice || {};
  capShow('declare', twoWays('Declare?', [`${esc(dn(s.batting))} <b>${s.runs}/${s.wkts}</b>${s.margin ? ', ' + esc(s.margin) : ''}.`,
    `Day ${s.day}, ${esc(q.moment)}: ${s.left} overs left in the match.`],
    'Declare now', 'Bat on', !!q.default, a.declare, a.bat_on,
    a.declare ? 'Chances for two average sides from this position; they do not know who is batting or bowling.' : ''), 'Declare?');
  twoWire();
}
function qFollowOn(q) {
  const a = q.advice || {};
  capShow('follow_on', twoWays('Enforce the follow-on?', [`${esc(dnText(q.opponent_score, CAP.teams || []))} all out: you lead by <b>${q.lead}</b>.`,
    `Real captains enforce it about <b>${pc(q.real)}%</b> of the time from here.`],
    'Enforce: they bat again', 'Bat again yourself', !!q.default, a.enforce, a.bat,
    'Your bowlers have just bowled an innings: a second one straight away is a long stint.'), 'Follow-on?');
  twoWire();
}
function qNewBall(q) {
  const pace = (q.bowlers || []).filter(p => !isSpin(p.kind) && p.overs_per_match >= 5).map(p => esc(sur(p.name))).join(', ');
  capShow('new_ball', twoWays('Take the new ball?', [`The ball is <b>${q.age}</b> overs old.`,
    pace ? `Your quicks: ${pace}.` : 'You have no regular pace bowler.'],
    'Take it', 'Not yet', true, null, null,
    'A new ball helps pace and scores a little quicker; an old one suits spin. Not yet: you are asked again in ten overs.'), 'New ball?');
  twoWire();
}
function qNight(q) {
  capShow('nightwatchman', twoWays('Send a nightwatchman?', [`A wicket with <b>${q.left_today}</b> overs left today. Due in: <b>${esc(q.next.name)}</b>.`],
    `Send ${esc(q.player.name)}`, `Send ${esc(q.next.name)}`, true, null, null, ''), 'Nightwatchman?');
  twoWire();
}

/* the bowler card of a Test: no quota; what he costs today, and how much he has bowled */
function testBowlerCard(p, sug, fig) {
  return `<button class="bopt ${sug ? 'sug' : ''}" data-id="${esc(p.id)}">${kindIcon(p.kind)}<div class="bo-m"><b>${esc(p.name)}${sug ? '<span class="tag-s">SUGGESTED</span>' : ''}</b>
    <span class="fig">${fig.overs}-${fig.maidens}-${fig.runs}-${fig.wkts}</span>
    <span class="small">${esc(p.kind || p.role)} · today ${n1(p.exp_avg)} a wicket, ${n1(p.phase_econ)} an over<span class="full-only"> · career avg ${n1(p.bowl_avg)}</span>${p.rested !== null && p.rested !== undefined ? ` · rested ${p.rested} ov` : ''}</span></div>
    <span class="left"><b>${p.overs_today}</b> today</span></button>`;
}

/* the chips beside the bars: Declare (batting) or Change bowler (in the field) */
function testBarChips(q) {
  if (q.side === 'bat' && q.can_declare) return '<button class="ns-chip" id="cap-declare">Declare</button>';
  if (q.side === 'bowl' && q.can_change) return '<button class="ns-chip" id="cap-change">Change bowler</button>';
  return '';
}
function testBarWire(q, send) {
  if ($('cap-change')) $('cap-change').onclick = () => send('over', {change: true});
  if ($('cap-declare')) $('cap-declare').onclick = () => {
    const s = q.state, a = q.advice || {};
    CAP.sheetKind = 'declare-now';
    openSheet(`<h3>Declare at ${s.runs}/${s.wkts}?</h3>
      <div class="sb-line">${s.margin ? esc(s.margin.charAt(0).toUpperCase() + s.margin.slice(1)) + '. ' : ''}${s.left} overs left in the match.</div>
      ${a.declare ? `<div class="sb-line">Declare: ${wdlText(a.declare)}</div><div class="sb-line">Bat on: ${wdlText(a.bat_on)}</div>` : ''}
      <div class="sh-row" style="margin-top:12px"><button class="btn go" id="dc-yes">Declare</button><button class="btn sec" id="dc-no">Bat on</button></div>`);
    $('dc-yes').onclick = () => { closeSheet(); send('over', {declare: true}); };
    $('dc-no').onclick = closeSheet;
  };
}
