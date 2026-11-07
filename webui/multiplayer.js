/* Two players (docs/multiplayer_design.md): a room with two seats, usually on two devices on the same Wi-Fi.
   Each seat polls /api/mp/state with its secret token and answers only its own questions through /api/mp/decide;
   the question screens are captain.js's. The token is kept per tab (sessionStorage) so two tabs can test both
   seats, with localStorage as the fallback when the tab was closed. */
'use strict';

const MP = {token: null, code: null, active: false, you: null, team: null, built: false,
  deadline: null, dlFor: null, oppHTML: '', waitHTML: ''};
const MP_KEY = 'mp_seat';
const MP_DOING = {toss: 'calling the toss', xi: 'picking their XI', bowler: 'choosing a bowler',
  batter: 'choosing the next batter', impact: 'thinking about the Impact Player', ball: 'setting their bars',
  result: 'looking at the result'};
const MP_KINDS = [['toss', 'Toss'], ['xi', 'Playing XI'], ['bowler', 'Bowler each over'], ['batter', 'Next batter'],
  ['impact', 'Impact Player'], ['ball', 'Ball by ball (bars)']];

function mpStore(code, token) {
  MP.code = code; MP.token = token;
  const v = JSON.stringify({code, token});
  try { sessionStorage.setItem(MP_KEY, v); } catch (e) { /* private mode */ }
  try { localStorage.setItem(MP_KEY, v); } catch (e) { /* private mode */ }
}
function mpForget() {
  Object.assign(MP, {token: null, code: null, active: false, built: false, team: null});
  try { sessionStorage.removeItem(MP_KEY); } catch (e) { /* private mode */ }
  try { localStorage.removeItem(MP_KEY); } catch (e) { /* private mode */ }
  document.body.classList.remove('mp-on');
}
function mpSaved() {
  for (const get of [() => sessionStorage, () => localStorage]) {
    try { const v = JSON.parse(get().getItem(MP_KEY) || 'null'); if (v && v.token) return v; } catch (e) { /* none */ }
  }
  return null;
}
const mpQ = () => '/api/mp/state?token=' + encodeURIComponent(MP.token);

/* on page load: back into a room this tab (or browser) was in, or join from a ?join=CODE link */
async function mpInit() {
  $('mp-join').onclick = () => mpJoin($('mp-code').value);
  $('mp-code').onkeydown = e => { if (e.key === 'Enter') mpJoin($('mp-code').value); };
  $('mp-leave').onclick = mpLeave;
  $('cap-back').onclick = () => mpControl('me');
  $('r-mp').onclick = mpRematch;
  setInterval(mpTick, 250);
  const join = (new URLSearchParams(location.search).get('join') || '').toUpperCase();
  if (join) window.history.replaceState(null, '', '/');
  const saved = mpSaved();
  if (saved && (!join || join === saved.code)) {
    MP.code = saved.code; MP.token = saved.token;
    let st = null;
    try { st = await api(mpQ()); } catch (e) { st = null; }
    if (st && st.phase !== 'none') { setMode('mp'); MP.active = true; mpPoll(); return true; }
    mpForget();
  }
  if (join) { setMode('mp'); $('mp-code').value = join; await mpJoin(join); return true; }
  return false;
}

async function mpCreate() {
  const p = payload();
  const r = await api('/api/mp/create', {fmt: p.fmt, comp: p.comp, year: p.year, venues: p.venues, seed: p.seed,
    rain: p.rain, clock: $('mp-clock').value});
  mpStore(r.code, r.token); MP.active = true; MP.built = false; mpPoll();
}

async function mpJoin(code) {
  $('mp-join-err').textContent = '';
  code = String(code || '').trim().toUpperCase();
  if (!code) { $('mp-join-err').textContent = 'Type the room code shown on the host\'s screen.'; return; }
  try {
    const r = await api('/api/mp/join', {code});
    mpStore(code, r.token); MP.active = true; MP.built = false;
    if (r.seat === 'spectator') toast('Both seats are taken - you are watching.');
    mpPoll();
  } catch (e) { $('mp-join-err').textContent = e.message; toast(e.message, true); }
}

async function mpLeave() {
  if (MP.you === 0 && !confirm('Close the room? The other player will be sent back to the start.')) return;
  try { if (MP.you !== 'spectator') await api('/api/mp/lobby', {token: MP.token, leave: true}); } catch (e) { /* gone already */ }
  clearTimeout(POLL_T); mpForget(); showView('v-home');
}
async function mpRematch() {
  try { await api('/api/mp/lobby', {token: MP.token, rematch: true}); } catch (e) { toast(e.message, true); }
  MP.built = false; mpPoll();
}
async function mpControl(who) {
  try { await api('/api/mp/control', {token: MP.token, who}); } catch (e) { toast(e.message, true); }
  mpPoll();
}
async function mpLobbySend(body) {
  try { await api('/api/mp/lobby', {token: MP.token, ...body}); } catch (e) { toast(e.message, true); }
  clearTimeout(POLL_T); POLL_T = setTimeout(mpPoll, 100);
}

async function mpPoll() {
  clearTimeout(POLL_T);
  if (!MP.token) return;
  let st;
  try { st = await api(mpQ()); } catch (e) { POLL_T = setTimeout(mpPoll, 1500); return; }
  MP.you = st.you;
  document.body.classList.toggle('mp-on', st.phase === 'playing');
  const running = st.phase === 'playing';
  $('status-pill').textContent = running ? 'Running' : 'Idle';
  $('status-pill').classList.toggle('run', running);
  if (st.phase === 'none') { toast('The room was closed.', true); mpForget(); showView('v-home'); return; }
  if (st.phase === 'lobby') { mpLobby(st); POLL_T = setTimeout(mpPoll, 800); return; }
  if (st.phase === 'playing') { mpPlaying(st); POLL_T = setTimeout(mpPoll, st.me && st.me.pending ? 700 : 250); return; }
  const j = st.job;                      // the match is over
  MP.built = false;
  if (j.status === 'done') { MP.team = st.you === 'spectator' ? null : st.names[st.you]; showResults(); }
  else if (j.status === 'error') { $('e-text').textContent = j.error || '(no details)'; showView('v-error'); }
  else { toast('The match was stopped.'); mpRematch(); }
}

/* ───────── the room before the match ───────── */
function mpCompLabel(s) {
  const c = ((META.formats[s.fmt] || {}).competitions || []).find(c => c.id === s.comp);
  return c ? c.label : s.comp;
}
function mpLobby(st) {
  showView('v-mp');
  CAP.qid = null;                        // question ids start again in a rematch
  const s = st.settings, me = st.you;
  $('mp-room-code').textContent = st.code;
  $('mp-cond').textContent = `${s.fmt.toUpperCase()} · conditions of ${mpCompLabel(s)} ${s.year} · ${s.venues.length ? s.venues.join(', ') : 'neutral venue'}`
    + ` · rain ${s.rain ? 'on' : 'off'} · shot clock ${s.clock === 'off' ? 'off' : s.clock + ' s a ball'}`;
  const joined = st.seats[1].joined;
  const links = me !== 0 || joined ? '' : st.lan
    ? `<div class="lbl">Invite the other player</div><div class="sb-line">On their device (same Wi-Fi), open
       ${st.urls.map(u => `<span class="mp-link">${esc(u)}</span>`).join(' or ') || 'this page'} - or open this page there,
       choose <b>Two players</b> and type the code <b class="mp-code">${esc(st.code)}</b>.</div>`
    : `<div class="lbl">Invite the other player</div><div class="sb-line bad">This server only accepts this computer. Restart it
       with <code>python web_ui.py --lan</code> so another device can join (or open a second tab here to try it out: choose
       Two players and type the code <b class="mp-code">${esc(st.code)}</b>).</div>`;
  $('mp-links').style.display = links ? '' : 'none';
  $('mp-links').innerHTML = links;
  $('mp-seats').innerHTML = st.seats.map((x, i) => `<div class="mp-seat ${i === me ? 'me' : ''}">
    <div class="who">Player ${i + 1}${i === 0 ? ' (host)' : ''}${i === me ? ' · you' : ''}</div>
    <div class="team">${x.label ? esc(x.label) : x.joined ? '<span class="muted">picking a team…</span>' : '<span class="muted">not joined yet</span>'}</div>
    <div class="small ${x.ready ? 'ok' : 'wait'}">${!x.joined ? '' : x.ready ? '✓ ready' : 'not ready'}${x.joined && !x.here ? ' · <span class="muted">away</span>' : ''}</div></div>`).join('');
  if (me === 'spectator') {
    $('mp-mine').innerHTML = '<div class="sb-line">You are watching. The match shows here when both players are ready.</div>';
    $('mp-leave').textContent = 'Stop watching';
    return;
  }
  $('mp-leave').textContent = me === 0 ? 'Close the room' : 'Leave the room';
  const mine = st.seats[me];
  if (!MP.built) mpBuildMine(st, mine);
  $('mp-ready').textContent = mine.ready ? 'Not ready yet' : "✓ I'm ready";
  $('mp-ready').className = 'btn ' + (mine.ready ? 'sec' : 'go');
  const other = st.seats[1 - me];
  $('mp-ready-note').textContent = mine.ready ? (other.ready ? 'Starting…' : 'Waiting for the other player to be ready.')
    : 'The match starts when both players are ready.';
}

function mpBuildMine(st, seat) {
  MP.built = true;
  const s = st.settings;
  if ($('c-fmt').value !== s.fmt) { $('c-fmt').value = s.fmt; fillConditions(); }   // classic rows list nations by format
  const impact = s.comp === 'ipl' && s.year >= 2023;
  $('mp-mine').innerHTML = `<div class="lbl">Your team</div>
    <div class="fg"><select id="mp-kind"><option value="saved">A saved team</option><option value="classic">A nation from any era</option></select></div>
    <div class="fg" id="mp-saved-box"><select id="mp-team"></select><div class="roster" id="mp-roster"></div></div>
    <div class="fg" id="mp-classic-box" style="display:none"></div>
    <div class="lbl" style="margin-top:10px">Decisions you make (the rest are the computer's)</div>
    <div class="checks" id="mp-manual">${MP_KINDS.filter(([k]) => k !== 'impact' || impact).map(([k, t]) =>
      `<label><input type="checkbox" value="${k}" ${seat.manual.includes(k) ? 'checked' : ''}> ${t}</label>`).join('')}</div>
    <div class="cap-actions"><button class="btn go" id="mp-ready">✓ I'm ready</button></div>
    <div class="hint" id="mp-ready-note"></div>`;
  const names = META.teams.map(t => t.name);
  fillSelect($('mp-team'), [{v: '', t: '- choose a team -'}, ...names.map(n => ({v: n, t: n}))]);
  const t = seat.team;
  let row = null;
  const classic = t && typeof t === 'object';
  row = classicRow($('mp-classic-box'), classic ? t.y1 : 2021, classic ? t.y2 : 2024, classic ? t.nation : 'India', false);
  if (classic) $('mp-kind').value = 'classic'; else if (t) $('mp-team').value = t;
  const entry = () => $('mp-kind').value === 'classic' ? row.entry() : ($('mp-team').value || null);
  const showKind = () => {
    const c = $('mp-kind').value === 'classic';
    $('mp-saved-box').style.display = c ? 'none' : ''; $('mp-classic-box').style.display = c ? '' : 'none';
  };
  const roster = () => {
    const x = META.teams.find(x => x.name === $('mp-team').value);
    $('mp-roster').textContent = x ? x.players.map(p => p.name).join(', ') : '';
  };
  const kinds = () => [...$('mp-manual').querySelectorAll('input:checked')].map(i => i.value);
  showKind(); roster();
  $('mp-kind').onchange = () => { showKind(); mpLobbySend({team: entry()}); };
  $('mp-team').onchange = () => { roster(); mpLobbySend({team: entry()}); };
  $('mp-classic-box').addEventListener('change', () => setTimeout(() => mpLobbySend({team: entry()}), 300));
  $('mp-manual').onchange = () => mpLobbySend({manual: kinds()});
  $('mp-ready').onclick = () => {
    const ready = $('mp-ready').textContent.includes("I'm ready");
    if (ready && !entry()) { toast('Choose your team first.', true); return; }
    mpLobbySend(ready ? {team: entry(), manual: kinds(), ready: true} : {ready: false});
  };
}

/* ───────── the match ───────── */
function mpPlaying(st) {
  showView('v-captain');
  $('go-btn').disabled = true;
  $('cap-progress').textContent = '';
  if (st.you === 'spectator') {
    $('cap-title').textContent = `${st.names[0]} v ${st.names[1]} - watching`;
    $('cap-ctx').textContent = 'Two players';
    $('cap-opp').textContent = ''; $('cap-clock').textContent = '';
    if (st.latest) $('cap-score').innerHTML = scoreHTML({state: st.latest});
    $('cap-q').innerHTML = '<div class="muted">You are watching. The scoreboard updates whenever a player has a decision to make.</div>';
    document.querySelector('#v-captain .cap-ctl').style.display = 'none';
    return;
  }
  document.querySelector('#v-captain .cap-ctl').style.display = '';
  const me = st.me, opp = st.opp;
  MP.team = me.team;
  CAP.impact = st.settings.comp === 'ipl' && st.settings.year >= 2023;
  if (!me.pending) $('cap-title').textContent = `${st.names[0]} v ${st.names[1]} — you captain ${me.team}`;
  capRender({done: st.job.done, total: st.job.total, captain: {pending: me.pending, manual: me.manual}});
  $('cap-progress').textContent = '';
  // the other player: what they are doing, and a hand-over if they have gone
  let o = `${esc(opp.team)}: ${opp.computer ? 'the computer is playing their side' : opp.choosing ? MP_DOING[opp.choosing] + '…' : 'playing'}`;
  if (opp.gone > 15 && !opp.computer) o += ` · <span style="color:var(--amber)">no contact for ${opp.gone} s</span>`;
  if (opp.can_take) o += ` <button class="btn sec" id="mp-take" style="width:auto;padding:3px 8px">Hand their side to the computer</button>`;
  if (o !== MP.oppHTML) {
    MP.oppHTML = o; $('cap-opp').innerHTML = o;
    if ($('mp-take')) $('mp-take').onclick = () => mpControl('opponent');
  }
  $('cap-back').style.display = me.skip || me.manual.length < me.home.length ? '' : 'none';
  if (!me.pending) {
    if (st.latest) $('cap-score').innerHTML = scoreHTML({state: st.latest});
    const w = me.skip ? `Skipping to the end of the ${me.skip === 'innings' ? 'innings' : 'match'}: the computer plays your side.`
      : !me.manual.length ? 'The computer is playing your side.'
      : opp.choosing && !opp.computer ? `Waiting for ${esc(opp.team)} - ${MP_DOING[opp.choosing]}…` : 'Playing on…';
    if (w !== MP.waitHTML || CAP.qid !== 'mpwait') { MP.waitHTML = w; CAP.qid = 'mpwait'; $('cap-q').innerHTML = `<div class="muted">${w}</div>`; }
    MP.deadline = null;
  } else {
    MP.waitHTML = '';
    if (MP.dlFor !== me.pending.id) {            // the server's deadline on this device's clock
      MP.dlFor = me.pending.id;
      MP.deadline = me.pending.deadline ? Date.now() + 1000 * (me.pending.deadline - st.now) : null;
    }
  }
}
function mpTick() {
  const el = $('cap-clock');
  if (!el) return;
  if (!MP.active || !MP.deadline) { el.textContent = ''; return; }
  const left = Math.max(0, Math.ceil((MP.deadline - Date.now()) / 1000));
  el.textContent = `⏱ ${left}s`;
  el.classList.toggle('low', left <= 3);
}
