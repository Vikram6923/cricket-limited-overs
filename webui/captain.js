/* Manual captaincy: the person captains one side (engine/control.py). The server holds the open question in
   /api/status (captain.pending); the answer goes to /api/decide. Every screen shows the computer's choice. */
'use strict';

const KIND_LABEL = {toss: 'Toss', xi: 'Playing XI', bowler: 'Bowlers', batter: 'Next batter', impact: 'Impact Player',
  result: 'Pause after matches'};
const CAP = {qid: null, q: null, auto: {}, manual: [], impact: true};
const n1 = v => v === null || v === undefined ? '–' : v;
const statLine = p => [p.role + (p.kind && p.role !== 'Batter' && p.role !== 'WK' ? ` (${p.kind})` : ''),
  p.bat_avg ? `bat avg ${p.bat_avg}, SR ${p.bat_sr}` : '', p.bowl_econ && p.overs_per_match >= 0.5 ? `bowl econ ${p.bowl_econ}, ${p.overs_per_match} ov/match` : ''].filter(Boolean).join(' · ');
const osTag = p => p.overseas ? '<span class="os-tag">OS</span>' : '';

function capRender(st) {
  const cap = st.captain, q = cap.pending;
  $('cap-progress').textContent = `${st.done} of ${st.total} matches played`;
  if (!q) {
    if (CAP.qid !== 'wait') { CAP.qid = 'wait'; $('cap-q').innerHTML = '<div class="muted">Playing on…</div>'; }
    return;
  }
  if (q.id === CAP.qid) return;
  CAP.qid = q.id; CAP.q = q; CAP.manual = cap.manual; CAP.auto = {};
  const c = q.context || {}, s = q.state || {};
  $('cap-title').textContent = `${s.match || q.team} — you captain ${q.team}`;
  $('cap-ctx').textContent = [c.stage, c.match_no ? 'match ' + c.match_no : '', s.venue || 'neutral venue',
    s.pitch ? 'pitch: ' + s.pitch : ''].filter(Boolean).join(' · ');
  $('cap-score').innerHTML = scoreHTML(q);
  renderAuto();
  ({toss: qToss, xi: qXI, bowler: q2 => qPick(q2, 'bowler'), batter: q2 => qPick(q2, 'batter'), impact: qImpact,
    result: qResult}[q.kind] || qResult)(q);
}

function renderAuto() {
  const kinds = Object.keys(KIND_LABEL).filter(k => k !== 'impact' || CAP.impact || CAP.manual.includes('impact'));
  const computer = k => CAP.auto[k] !== undefined ? CAP.auto[k] : !CAP.manual.includes(k);
  $('cap-auto').innerHTML = kinds.map(k => `<button class="tog ${computer(k) ? 'on' : ''}" data-k="${k}"
    title="${computer(k) ? 'The computer decides - click to decide yourself' : 'You decide - click to leave it to the computer'}">${KIND_LABEL[k]}${computer(k) ? ' · computer' : ''}</button>`).join('');
  $('cap-auto').querySelectorAll('.tog').forEach(b => b.onclick = () => { CAP.auto[b.dataset.k] = !computer(b.dataset.k); renderAuto(); });
}

async function capSend(choice, extra = {}) {
  try { await api('/api/decide', {id: CAP.q.id, choice, auto: CAP.auto, ...extra}); }
  catch (e) { toast(e.message, true); }
  $('cap-q').innerHTML = '<div class="muted">Playing on…</div>'; CAP.qid = 'sent';
  clearTimeout(POLL_T); POLL_T = setTimeout(poll, 120);
}

const ballClass = b => /W/.test(b) ? 'W' : b === '4' ? 'b4' : b === '6' ? 'b6' : '';

function scoreHTML(q) {
  const s = q.state || {};
  if (s.runs === undefined) {           // before the match: toss and XI
    return `<div class="cap-panel"><h3>${esc(s.match)}</h3>
      <div class="sb-line">${s.format === 'odi' ? 'ODI' : 'T20'}, ${s.overs} overs a side · v ${esc(s.opponent)}</div>
      <div class="sb-line">Venue: <b>${esc(s.venue || 'neutral')}</b></div>
      <div class="sb-line">Pitch: <b>${esc(s.pitch || '–')}</b></div>
      ${q.toss ? `<div class="sb-line" style="margin-top:6px">${esc(q.toss)}</div>` : ''}
      ${(s.rain || []).map(r => `<div class="sb-line">☂ ${esc(r)}</div>`).join('')}</div>`;
  }
  const wp = s.win_prob === null || s.win_prob === undefined ? null : Math.round(100 * s.win_prob);
  const chase = s.target ? `Target <b>${s.target}</b> · need <b>${s.need}</b> off <b>${s.balls_left}</b> balls` +
    (s.rrr !== null ? ` · required rate <b>${s.rrr}</b>` : '') : `Innings ${s.innings} · ${s.max_overs} overs`;
  const bat = s.batters.filter(b => b.batted);
  const yet = s.batters.filter(b => !b.batted).map(b => esc(b.name)).join(', ');
  const balls = o => { const [a, b] = o.split('.').map(Number); return 6 * a + b; };
  return `<div class="cap-panel">
    <div class="sb-line">${esc(s.batting)} batting${s.previous.length ? ' · ' + s.previous.map(esc).join(' · ') : ''}</div>
    <div class="sb-score">${s.runs}/${s.wkts}<small>${s.overs_done} / ${s.max_overs} ov${s.crr !== null ? ' · run rate ' + s.crr : ''}</small></div>
    <div class="sb-line">${chase} · partnership ${s.partnership.runs} (${s.partnership.balls})</div>
    ${wp !== null ? `<div class="wp"><i style="width:${wp}%"></i></div><div class="sb-line">${esc(s.batting)} win probability <b>${wp}%</b></div>` : ''}
    <table class="mini"><tr><th>Batter</th><th></th><th>R</th><th>B</th><th>4s</th><th>6s</th><th>SR</th></tr>
    ${bat.map(b => `<tr class="${b.at_crease ? 'crease' : b.out ? 'dim' : ''}"><td>${esc(b.name)}${b.on_strike ? ' *' : ''}</td>
      <td class="how">${b.out ? esc(b.how) : b.at_crease ? 'batting' : 'not out'}</td><td>${b.runs}</td><td>${b.balls}</td>
      <td>${b.fours}</td><td>${b.sixes}</td><td>${b.balls ? (100 * b.runs / b.balls).toFixed(0) : '–'}</td></tr>`).join('')}</table>
    ${yet ? `<div class="sb-line" style="margin-top:6px">Yet to bat: ${yet}</div>` : ''}
    <table class="mini"><tr><th>Bowler</th><th>O</th><th>M</th><th>R</th><th>W</th><th>Econ</th></tr>
    ${s.bowlers.map(b => `<tr><td>${esc(b.name)}</td><td>${b.overs}</td><td>${b.maidens}</td><td>${b.runs}</td><td>${b.wkts}</td>
      <td>${balls(b.overs) ? (6 * b.runs / balls(b.overs)).toFixed(1) : '–'}</td></tr>`).join('')}</table>
    ${s.recent.length ? `<div class="overs">${s.recent.map(o => `<div><span class="muted">Over ${o.over} (${esc(o.bowler)}):</span>
      ${o.balls.map(b => `<span class="ball ${ballClass(b)}">${esc(b)}</span>`).join('')} <b>${o.runs}</b></div>`).join('')}</div>` : ''}
    ${s.events.length ? `<div class="evs">${s.events.map(esc).join('<br>')}</div>` : ''}
  </div>`;
}

const cpuTag = on => on ? '<span class="cpu-tag">COMPUTER</span>' : '';
const optCard = (p, isCpu, extra) => `<button class="opt ${isCpu ? 'cpu' : ''}" data-id="${esc(p.id)}">${cpuTag(isCpu)}
  <b>${esc(p.name)}${osTag(p)}</b>${extra}</button>`;
const nameOf = (list, id) => (list.find(p => p.id === id) || {}).name || '–';

function qToss(q) {
  $('cap-q').innerHTML = `<h3>${esc(q.text)} Bat or bowl?</h3>
    <div class="sb-line">The computer would choose to <b>${esc(q.default)}</b>.</div>
    <div class="opts">${q.options.map(o => `<button class="opt ${o === q.default ? 'cpu' : ''}" data-id="${o}">${cpuTag(o === q.default)}
      <b>${o === 'bat' ? 'Bat first' : 'Bowl first'}</b><span>${o === 'bat' ? 'set a target' : 'chase'}</span></button>`).join('')}</div>`;
  $('cap-q').querySelectorAll('.opt').forEach(b => b.onclick = () => capSend(b.dataset.id));
}

/* Impact Player: the computer's suggestion, who comes in and who goes out */
function impactBoxHTML(imp, standalone) {
  if (!imp) return '';
  const all = [...imp.ins, ...imp.outs], sg = imp.suggestion;
  const say = sg ? `The computer would bring in <b>${esc(nameOf(all, sg.in))}</b> for <b>${esc(nameOf(all, sg.out))}</b> now (worth about ${sg.gain} runs).`
    : 'The computer would not use the Impact Player now.';
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
       <span>expected econ${ph ? ' (' + ph + ')' : ''} <b>${n1(p.phase_econ)}</b> · career ${n1(p.bowl_econ)}</span>`
    : `<span>${esc(p.role)}${p.hand ? ' · ' + esc(p.hand) + 'HB' : ''}${p.slot ? ' · usually #' + p.slot : ''}</span>
       <span>avg ${n1(p.bat_avg)} · SR ${n1(p.bat_sr)}</span><span>expected SR${ph ? ' (' + ph + ')' : ''} <b>${n1(p.phase_sr)}</b></span>`;
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
    <div class="sb-line">The computer's choice: <b>${esc(nameOf(q.options, q.default))}</b>${imp && imp.suggestion ? ', with the Impact substitution below' : ''}. Click a player to choose.</div>
    <div class="opts" id="cap-opts"></div>${impactBoxHTML(imp, false)}
    <div class="cap-actions"><button class="btn sec" id="cap-cpu">Use the computer's choice</button></div>`;
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
      <button class="btn sec" id="ib-cpu">${imp.suggestion ? "Computer's call (its substitution)" : "Computer's call (wait)"}</button>
      <button class="btn sec" id="ib-wait">Not now</button></div>`;
  $('ib-make').onclick = () => { const c = impactChoice(imp); if (c && c !== 'bad') capSend(c); };
  $('ib-cpu').onclick = () => capSend(null);
  $('ib-wait').onclick = () => capSend({});
}

function qResult(q) {
  $('cap-q').innerHTML = `<h3>${esc(q.result || 'Match over')}</h3>
    ${(q.scores || []).map(s => `<div class="sb-line">${esc(s)}</div>`).join('')}
    ${q.pom && q.pom.name ? `<div class="sb-line">Player of the match: <b>${esc(q.pom.name)}</b> (${esc(q.pom.team)})</div>` : ''}
    <div class="cap-actions"><button class="btn go" id="cap-cont">Continue</button></div>`;
  $('cap-cont').onclick = () => capSend(null);
}

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
      <div class="sb-line">${esc(q.toss)} You ${q.batting_first ? 'bat' : 'bowl'} first. The computer's picks are marked CPU (listed in its batting order); the order here is your batting order.</div>
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
        <button class="btn sec" id="xi-cpu">Use the computer's XI</button></div>`;
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
