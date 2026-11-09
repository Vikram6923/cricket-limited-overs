/* Two players (docs/multiplayer_design.md): a room with two seats, usually on two devices on the same Wi-Fi.
   Each seat polls /api/mp/state with its secret token and answers only its own questions through /api/mp/decide;
   the question screens are captain.js's; the draft and auction rooms are app.js's / auction_room.js's, fed by
   the room's state (each seat sees only its own question, wishlist and advice). The token is kept per tab (sessionStorage) so two tabs can test both
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
const mpQ = () => '/api/mp/state?token=' + encodeURIComponent(MP.token)
  + (MP.auV !== null && MP.auV !== undefined && $('v-auction').classList.contains('on') ? '&v=' + MP.auV : '');

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
  const [lo, hi] = META.years[p.fmt];
  const r = await api('/api/mp/create', {fmt: p.fmt, comp: p.comp, year: p.year, venues: p.venues, seed: p.seed,
    rain: p.rain, clock: $('mp-clock').value, series: $('mp-series').value, teams: $('mp-teams').value,
    y1: Math.max(lo, hi - 9), y2: hi, source: 'full', cpu: 0});
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
  if (st.phase !== 'auction') MP.auV = null;
  if (st.phase === 'draft') { await mpDraft(st); POLL_T = setTimeout(mpPoll, 700); return; }
  if (st.phase === 'auction') {
    try { await mpAuction(st); } catch (e) { console.error(e); }      // keep polling whatever the screen did
    POLL_T = setTimeout(mpPoll, 500); return;
  }
  if (st.phase === 'playing') { mpPlaying(st); POLL_T = setTimeout(mpPoll, st.me && st.me.pending ? 700 : 250); return; }
  const j = st.job;                      // the match is over
  MP.built = false;
  if (j.status === 'done') { MP.team = st.you === 'spectator' ? null : st.names[st.you]; showResults(); }
  else if (j.status === 'error') { $('e-text').textContent = j.error || '(no details)'; showView('v-error'); }
  else { toast('The match was stopped.'); mpRematch(); }
}

/* ───────── the series between the two players ───────── */
const MP_SERIES_OPTS = [[1, 'A single match'], [3, 'Best of 3'], [5, 'Best of 5']];
/* {of, wins: [seat 0, seat 1], match, finished} -> "Best of 3 · Match 2 · India lead 1-0" (names: by seat) */
function mpSeriesLine(sr, names, withMatch = true) {
  if (sr && sr.league) return `League · match ${sr.match} of ${sr.of}`;
  if (!sr || sr.of < 2) return '';
  const [a, b] = sr.wins, left = sr.of - sr.finished;
  const nm = i => esc(dn(names[i]));
  const done = Math.abs(a - b) > left || left === 0;
  const score = done ? (a === b ? `series drawn ${a}-${b}` : `<b>${nm(a > b ? 0 : 1)}</b> win the series ${Math.max(a, b)}-${Math.min(a, b)}`)
    : a === b ? (a ? `level at ${a}-${b}` : 'series level') : `<b>${nm(a > b ? 0 : 1)}</b> lead ${Math.max(a, b)}-${Math.min(a, b)}`;
  return [`Best of ${sr.of}`, withMatch && !done ? `Match ${sr.match}` : '', score].filter(Boolean).join(' · ');
}

/* ───────── the room before the match ───────── */
function mpCompLabel(s) {
  const c = ((META.formats[s.fmt] || {}).competitions || []).find(c => c.id === s.comp);
  return c ? c.label : s.comp;
}
function mpLobby(st) {
  showView('v-mp');
  MP.settings = st.settings;
  CAP.qid = null;                        // question ids start again in a rematch
  const s = st.settings, me = st.you;
  $('mp-room-code').textContent = st.code;
  const realSeason = s.teams === 'auction' && s.a_pool === 'season' && mpSeason(s);
  $('mp-cond').textContent = (realSeason ? `T20 · ${(mpLeague(s) || {}).label} ${realSeason.season} conditions${s.after === 'league' ? ' and home grounds' : ''}`
    : `${s.fmt.toUpperCase()} · conditions of ${mpCompLabel(s)} ${s.year} · ${s.venues.length ? s.venues.join(', ') : 'neutral venue'}`)
    + ` · rain ${s.rain ? 'on' : 'off'} · shot clock ${s.clock === 'off' ? 'off' : s.clock + ' s a ball'}`
    + ` · ${mpPlayText(s)}`;
  const joined = st.seats[1].joined;
  const links = me !== 0 || joined ? '' : st.lan
    ? `<div class="lbl">Invite the other player</div><div class="sb-line">On their device${st.public ? '' : ' (same Wi-Fi)'}, open
       ${st.urls.map(u => `<span class="mp-link">${esc(u)}</span>`).join(' or ') || 'this page'} - or open this page there,
       choose <b>Two players</b> and type the code <b class="mp-code">${esc(st.code)}</b>.</div>`
    : `<div class="lbl">Invite the other player</div><div class="sb-line bad">This server only accepts this computer. Restart it
       with <code>python web_ui.py --lan</code> so another device can join (or open a second tab here to try it out: choose
       Two players and type the code <b class="mp-code">${esc(st.code)}</b>).</div>`;
  $('mp-links').style.display = links ? '' : 'none';
  $('mp-links').innerHTML = links;
  const rec = st.record || {matches: [0, 0], series: [0, 0], played: 0, titles: [0, 0]};
  const titles = rec.titles || [0, 0];
  const recLine = i => rec.matches[0] + rec.matches[1] + titles[0] + titles[1] === 0 ? '' : `<div class="h2h">Won here: <b>${rec.matches[i]}</b> match${rec.matches[i] === 1 ? '' : 'es'}${rec.played ? ` · <b>${rec.series[i]}</b> series` : ''}${titles[0] + titles[1] ? ` · <b>${titles[i]}</b> league title${titles[i] === 1 ? '' : 's'}` : ''}</div>`;
  $('mp-seats').innerHTML = st.seats.map((x, i) => `<div class="mp-seat ${i === me ? 'me' : ''}" ${x.label ? `style="${tStyle(x.label)}"` : ''}>
    <div class="who">Player ${i + 1}${i === 0 ? ' (host)' : ''}${i === me ? ' · you' : ''}</div>
    <div class="team">${x.label ? `${badge(x.label, 'sm')} ${esc(x.label)}` : x.joined ? `<span class="muted">${mpNamed(s) ? 'naming their team…' : s.teams === 'auction' ? 'choosing a franchise…' : 'picking a team…'}</span>` : '<span class="muted">not joined yet</span>'}</div>
    <div class="small ${x.ready ? 'ok' : 'wait'}">${!x.joined ? '' : x.ready ? '✓ ready' : 'not ready'}${x.joined && !x.here ? ' · <span class="muted">away</span>' : ''}</div>
    ${recLine(i)}</div>`).join('');
  if (me === 'spectator') {
    $('mp-mine').innerHTML = '<div class="sb-line">You are watching. The match shows here when both players are ready.</div>';
    $('mp-leave').textContent = 'Stop watching';
    return;
  }
  $('mp-leave').textContent = me === 0 ? 'Close the room' : 'Leave the room';
  const mine = st.seats[me];
  if (!MP.built || MP.builtTeams !== mpBuildKey(s)) mpBuildMine(st, mine);
  mpSyncHost(s);
  $('mp-ready').textContent = mine.ready ? 'Not ready yet' : "✓ I'm ready";
  $('mp-ready').className = 'btn ' + (mine.ready ? 'sec' : 'go');
  const other = st.seats[1 - me];
  $('mp-ready-note').textContent = mine.ready ? (other.ready ? 'Starting…' : 'Waiting for the other player to be ready.')
    : s.teams === 'draft' ? 'The draft starts when both players are ready.'
    : s.teams === 'auction' ? 'The auction starts when both players are ready.' : 'The match starts when both players are ready.';
}
/* each player names a team (draft, auction from player-pool years) rather than picking one */
const mpNamed = s => s.teams === 'draft' || (s.teams === 'auction' && s.a_pool !== 'season');
const mpBuildKey = s => [s.teams || 'pick', s.a_pool, s.league, s.season].join('|');
const mpLeague = s => (META.leagues || []).find(l => l.id === s.league);
function mpSeason(s) { const l = mpLeague(s); return l ? (l.seasons.find(x => x.season === s.season) || l.seasons[0]) : null; }

/* what the room plays, in words */
function mpPlayText(s) {
  const play = (MP_SERIES_OPTS.find(o => o[0] === (s.series || 1)) || MP_SERIES_OPTS[0])[1].toLowerCase();
  if (s.teams === 'auction') {
    const se = s.a_pool === 'season' ? mpSeason(s) : null, l = mpLeague(s);
    const k = se ? se.teams.length : 2 + (s.cpu || 0);
    const what = se ? `auction for ${l.label} ${se.season} (${k} franchises${s.retain ? ', with retentions' : ''})`
      : `auction of ${s.y1}–${s.y2} players${s.cpu ? ` with ${s.cpu} computer teams` : ''}`;
    const then = s.after === 'league' && k > 2 ? (se ? 'then the season: double round robin + playoffs' : `then a ${k}-team league + ${k <= 4 ? 'final' : 'semi-finals'}`)
      : 'then ' + play + ' between the two of you';
    return `${what} · ${then}`;
  }
  if (s.teams !== 'draft') return play;
  const k = 2 + (s.cpu || 0);
  return `draft squads from ${s.y1}–${s.y2} players · ` + (s.cpu ? `${s.cpu} computer teams draft too, then a ${k}-team league + ${k <= 4 ? 'final' : 'semi-finals'}` : play);
}

/* the host's room settings: teams picked or drafted, draft pool, computer teams, single match or series */
function mpHostHTML(s) {
  const [lo, hi] = META.years[s.fmt] || [2005, 2026];
  return `<div class="lbl" style="margin-top:14px">Room settings (host)</div>
    <div class="seg2">
      <div class="fg"><label>Teams</label><select id="mh-teams"><option value="pick">Each player picks a team</option><option value="draft">Draft squads</option><option value="auction">Auction</option></select></div>
      <div class="fg" id="mh-play-box"><label>Play</label><select id="mh-series">${MP_SERIES_OPTS.map(([v, t]) => `<option value="${v}">${t}</option>`).join('')}</select></div>
    </div>
    <div id="mh-auction" style="display:none">
      <div class="seg2">
        <div class="fg"><label>Players</label><select id="mh-apool"><option value="season">A real league season</option><option value="years">Players from a span of years</option></select></div>
        <div class="fg"><label>Then</label><select id="mh-after"><option value="league">A league with the computer teams</option><option value="series">A match / series between the two of us</option></select></div>
      </div>
      <div class="seg2" id="mh-season-box">
        <div class="fg"><label>League</label><select id="mh-league">${(META.leagues || []).map(l => `<option value="${esc(l.id)}">${esc(l.label)}</option>`).join('')}</select></div>
        <div class="fg"><label>Season</label><select id="mh-season"></select></div>
      </div>
      <label class="small" id="mh-retain-box"><input type="checkbox" id="mh-retain"> Retentions and Right to Match from the season before</label>
    </div>
    <div id="mh-draft" style="display:none">
      <div class="seg2">
        <div class="fg"><label>Player pool years</label><div class="era"><input type="number" id="mh-y1" min="${lo}" max="${hi}"><span class="to">to</span><input type="number" id="mh-y2" min="${lo}" max="${hi}"></div></div>
        <div class="fg"><label>Computer teams</label><select id="mh-cpu"><option value="0">None - just the two of us</option>
          <option value="2">2 (a 4-team league)</option><option value="4">4 (a 6-team league)</option><option value="6">6 (an 8-team league)</option></select></div>
      </div>
      <div class="fg"><label>Pool</label><select id="mh-src"><option value="full">Full-member internationals</option>
        ${s.fmt === 't20' ? '<option value="leagues">Full-member internationals + franchise leagues</option>' : ''}
        <option value="intl">All internationals</option></select></div>
      <div class="hint" id="mh-note" style="margin:0"></div>
    </div>`;
}
function mpSyncHost(s) {
  if (!$('mh-teams')) return;
  const set = (id, v) => { const el = $(id); if (el && document.activeElement !== el && el.value !== String(v)) el.value = String(v); };
  set('mh-teams', s.teams || 'pick'); set('mh-series', s.series || 1); set('mh-y1', s.y1); set('mh-y2', s.y2);
  set('mh-cpu', s.cpu || 0); set('mh-src', s.source || 'full');
  const draft = (s.teams || 'pick') === 'draft', auction = s.teams === 'auction', season = auction && s.a_pool === 'season';
  set('mh-apool', s.a_pool || 'season'); set('mh-after', s.after || 'league'); set('mh-league', s.league || 'ipl');
  const l = mpLeague(s), seasons = l ? l.seasons.map(x => x.season) : [];
  if ($('mh-season').dataset.l !== (s.league || '')) {
    $('mh-season').dataset.l = s.league || '';
    $('mh-season').innerHTML = seasons.map(x => `<option value="${esc(x)}">${esc(x)}</option>`).join('');
  }
  set('mh-season', s.season || seasons[0] || '');
  $('mh-retain').checked = !!s.retain;
  $('mh-auction').style.display = auction ? '' : 'none';
  $('mh-season-box').style.display = $('mh-retain-box').style.display = season ? '' : 'none';
  $('mh-draft').style.display = draft || (auction && !season) ? '' : 'none';
  const se = season ? mpSeason(s) : null, k = se ? se.teams.length : 2 + (s.cpu || 0);
  const league = auction ? s.after === 'league' && k > 2 : draft && s.cpu;
  $('mh-play-box').style.display = league ? 'none' : '';
  $('mh-note').textContent = draft ? (s.cpu ? `A single round robin, then ${2 + s.cpu <= 4 ? 'a final' : 'semi-finals'}. Your matches against each other are two-player games; against the computer teams you play alone while the other player watches.`
    : 'Snake draft, 15 players each, rated on those years. Then you play your drafted squads.')
    : auction ? 'Each team bids with ₹120 cr for a squad of 18–25. Computer teams bid for what a player adds to their XI.' : '';
}

function mpBuildMine(st, seat) {
  MP.built = true;
  const s = st.settings, draft = mpNamed(s), franchise = s.teams === 'auction' && !draft;
  MP.builtTeams = mpBuildKey(s);
  if ($('c-fmt').value !== s.fmt) { $('c-fmt').value = s.fmt; fillConditions(); }   // classic rows list nations by format
  const se = franchise ? mpSeason(s) : null;
  const impact = franchise ? s.league === 'ipl' && se && +se.season.slice(0, 4) >= 2023 : s.comp === 'ipl' && s.year >= 2023;
  $('mp-mine').innerHTML = `${franchise ? `<div class="lbl">Your franchise</div>
    <div class="fg"><select id="mp-fr"><option value="">- choose a franchise -</option>${(se ? se.teams : []).map(t => t.franchise || t.name)
      .map(t => `<option value="${esc(t)}">${esc(t)}</option>`).join('')}</select></div>`
    : draft ? `<div class="lbl">Your team's name</div>
    <div class="fg"><input type="text" id="mp-dname" maxlength="30" placeholder="e.g. ${esc(META.draft_teams[st.you === 0 ? 0 : 1] || 'Riverside')}"></div>`
    : `<div class="lbl">Your team</div>
    <div class="fg"><select id="mp-kind"><option value="saved">A saved team</option><option value="classic">A nation from any era</option></select></div>`}
    <div class="fg" id="mp-saved-box" ${draft || franchise ? 'style="display:none"' : ''}><select id="mp-team"></select><div class="roster" id="mp-roster"></div></div>
    <div class="fg" id="mp-classic-box" style="display:none"></div>
    <div class="lbl" style="margin-top:10px">Decisions you make (the rest are the computer's)</div>
    <div class="checks" id="mp-manual">${MP_KINDS.filter(([k]) => k !== 'impact' || impact).map(([k, t]) =>
      `<label><input type="checkbox" value="${k}" ${seat.manual.includes(k) ? 'checked' : ''}> ${t}</label>`).join('')}</div>
    ${st.you === 0 ? mpHostHTML(s) : ''}
    <div class="cap-actions"><button class="btn go" id="mp-ready">✓ I'm ready</button></div>
    <div class="hint" id="mp-ready-note"></div>`;
  if (st.you === 0) {
    const send = patch => mpLobbySend({settings: {...MP.settings, ...patch}});
    $('mh-teams').onchange = () => send({teams: $('mh-teams').value});
    $('mh-apool').onchange = () => send({a_pool: $('mh-apool').value});
    $('mh-after').onchange = () => send({after: $('mh-after').value});
    $('mh-league').onchange = () => send({league: $('mh-league').value, season: ''});
    $('mh-season').onchange = () => send({season: $('mh-season').value});
    $('mh-retain').onchange = () => send({retain: $('mh-retain').checked});
    $('mh-series').onchange = () => send({series: $('mh-series').value});
    $('mh-cpu').onchange = () => send({cpu: $('mh-cpu').value});
    $('mh-src').onchange = () => send({source: $('mh-src').value});
    $('mh-y1').onchange = $('mh-y2').onchange = () => send({y1: $('mh-y1').value, y2: $('mh-y2').value});
  }
  if (franchise) {
    const fr = () => $('mp-fr').value;
    const kinds = () => [...$('mp-manual').querySelectorAll('input:checked')].map(i => i.value);
    $('mp-fr').value = seat.team && typeof seat.team === 'string' ? seat.team : '';
    $('mp-fr').onchange = () => mpLobbySend({team: fr() || null});
    $('mp-manual').onchange = () => mpLobbySend({manual: kinds()});
    $('mp-ready').onclick = () => {
      const ready = $('mp-ready').textContent.includes("I'm ready");
      if (ready && !fr()) { toast('Choose your franchise first.', true); return; }
      mpLobbySend(ready ? {team: fr(), manual: kinds(), ready: true} : {ready: false});
    };
    return;
  }
  if (draft) {
    const nm = () => $('mp-dname').value.trim();
    const kinds = () => [...$('mp-manual').querySelectorAll('input:checked')].map(i => i.value);
    $('mp-dname').value = seat.name || '';
    $('mp-dname').onchange = () => mpLobbySend({name: nm()});
    $('mp-manual').onchange = () => mpLobbySend({manual: kinds()});
    $('mp-ready').onclick = () => {
      const ready = $('mp-ready').textContent.includes("I'm ready");
      if (ready && !nm()) { toast('Name your team first.', true); $('mp-dname').focus(); return; }
      mpLobbySend(ready ? {name: nm(), manual: kinds(), ready: true} : {ready: false});
    };
    return;
  }
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

/* ───────── the draft: both players take turns in the draft room ───────── */
async function mpDraftSend(body) {
  $('dr-msg').textContent = '';
  try { await api('/api/mp/draft', {token: MP.token, ...body}); }
  catch (e) { $('dr-msg').textContent = e.message; toast(e.message, true); }
  clearTimeout(POLL_T); POLL_T = setTimeout(mpPoll, 50);
}
async function mpDraft(st) {
  const d = st.draft, s = st.settings, me = d.user;
  const poolKey = JSON.stringify([d.teams, s.y1, s.y2, s.source, s.years_mode, s.fmt]);
  if (MP.poolKey !== poolKey) {                       // the pool once per draft
    const p = await api('/api/mp/draft/pool?token=' + encodeURIComponent(MP.token));
    DPOOL = {list: p.pool, byId: new Map(p.pool.map(x => [x.id, x]))};
    fillSelect($('dp-role'), [{v: '', t: 'All roles'}, ...['WK', 'Batter', 'All-rounder', 'Pace', 'Spin'].map(r => ({v: r, t: r}))]);
    fillSelect($('dp-team'), [{v: '', t: 'All teams'}, ...[...new Set(p.pool.map(x => x.team))].sort().map(t => ({v: t, t}))]);
    ['dp-search', 'dp-role', 'dp-team'].forEach(id => $(id).oninput = drawDraftPool);
    MP.poolKey = poolKey; MP.draftKey = null;
  }
  showView('v-draft'); capHome(); $('dr-cap').classList.remove('cap-panel');
  MP.built = false;
  const i = st.you, other = i === 'spectator' ? null : d.players[1 - i];
  const yours = !d.done && me && d.current === me;
  const myAuto = i !== 'spectator' && d.auto[i], myReady = i !== 'spectator' && d.ready[i];
  // the clock and the turn change every poll; the pool and board only when a pick is made
  $('dr-turn').textContent = d.done ? 'Draft complete' : yours ? `Your pick!${d.seconds !== null ? ` · ${d.seconds}s` : ''}`
    : `${d.current} to pick${d.current === other ? ' (the other player)' : ''}${d.seconds !== null ? ` · ${d.seconds}s` : ''}`;
  $('dr-turn').className = 'turn' + (yours ? ' you' : '');
  const key = JSON.stringify([d.pick_no, d.done, d.current, d.auto, d.ready, st.can_take, i]);
  if (key === MP.draftKey) return;
  MP.draftKey = key;
  DRAFT = d;
  setDisplayTeams([]);
  $('dr-title').textContent = me ? `Draft · you are ${me}` : 'Draft · watching';
  $('dr-progress').textContent = d.done ? `${d.total} picks · players rated on ${d.y1}–${d.y2}` : `Pick ${d.pick_no} of ${d.total} · round ${Math.ceil(d.pick_no / d.teams.length)} of ${d.squad}`;
  $('dr-auto').textContent = 'Pick for me';
  $('dr-auto').style.display = yours && !myAuto ? '' : 'none';
  $('dr-auto').onclick = () => mpDraftSend({auto: 'one'});
  $('dr-rest').textContent = myAuto ? 'Pick myself again' : 'Auto-draft the rest of my squad';
  $('dr-rest').style.display = !d.done && me ? '' : 'none';
  $('dr-rest').onclick = () => mpDraftSend({auto: myAuto ? 'stop' : 'rest'});
  $('dr-play').textContent = myReady ? 'Not ready' : '▶ Ready to play';
  $('dr-play').className = 'btn ' + (myReady ? 'sec' : 'go');
  $('dr-play').style.display = d.done && me ? '' : 'none';
  $('dr-play').onclick = () => mpDraftSend({ready: !myReady});
  let extra = document.getElementById('dr-mp-extra');
  if (!extra) { extra = document.createElement('span'); extra.id = 'dr-mp-extra'; extra.style.display = 'contents'; $('dr-play').after(extra); }
  extra.innerHTML = (st.can_take ? `<button class="btn sec" id="dr-take">Auto-draft for ${esc(other)} (away)</button>` : '')
    + (i === 0 ? '<button class="btn sec" id="dr-redo">New draft</button>' : '')
    + `<button class="btn sec" id="dr-leave">${i === 0 ? 'Close the room' : i === 'spectator' ? 'Stop watching' : 'Leave'}</button>`;
  if ($('dr-take')) $('dr-take').onclick = () => mpDraftSend({take: true});
  if ($('dr-redo')) $('dr-redo').onclick = () => { if (confirm('Throw these squads away and go back to the room settings?')) mpDraftSend({redo: true}); };
  $('dr-leave').onclick = mpLeave;
  $('dr-msg').textContent = d.done && me ? (myReady ? (d.ready[1 - i] ? 'Starting…' : `Waiting for ${other} to be ready.`)
    : d.ready[1 - i] ? `${other} is ready to play.` : '') : myAuto ? 'The computer is drafting for you.' : '';
  $('dr-sugs').innerHTML = d.suggestions.length ? d.suggestions.map(id => { const p = DPOOL.byId.get(id);
    return `<button class="sug" data-id="${esc(id)}">${esc(p.name)}<small>${esc(p.role)}</small></button>`; }).join('')
    : `<span class="muted small">${d.done ? (me ? 'All squads are complete. Press “Ready to play” when you are.' : 'All squads are complete.') : 'Suggestions appear when it is your pick.'}</span>`;
  $('dr-sugs').querySelectorAll('.sug').forEach(b => b.onclick = () => mpDraftSend({id: b.dataset.id}));
  if (me) {
    const c = d.needs[me], mine = d.board[me];
    $('dr-squad-title').textContent = `Your squad (${mine.length}/${d.squad})`;
    $('dr-roles').innerHTML = Object.entries(d.targets).map(([r, t]) => `<span class="role ${c[r] >= t ? 'ok' : ''}">${NEED_LABEL[r]} ${c[r]}/${t}+</span>`).join('');
    $('dr-squad').innerHTML = mine.map(p => `<li>${esc(p.name)} <span>${esc((DPOOL.byId.get(p.id) || {}).team || '')} · ${esc(p.role)}</span></li>`).join('') || '<li class="muted">No players yet</li>';
  } else { $('dr-squad-title').textContent = ''; $('dr-roles').innerHTML = ''; $('dr-squad').innerHTML = ''; }
  drawBoard($('dr-board'), d.teams, d.board, me);
  drawDraftPool();
}

/* ───────── the auction: both players bid in the auction room ───────── */
async function mpAuctionSend(body) {
  $('au-msg').textContent = '';
  let d = null;
  try { d = await api('/api/mp/auction', {token: MP.token, ...body}); }
  catch (e) { $('au-msg').textContent = e.message; if (!/Too late/.test(e.message)) toast(e.message, true); }
  clearTimeout(POLL_T); POLL_T = setTimeout(mpPoll, 30);
  return d;
}
async function mpAuction(st) {
  const A = st.auction;
  if (MP.auId !== A.id || !APOOL) {                    // the players once per auction
    const p = await api('/api/mp/auction/pool?token=' + encodeURIComponent(MP.token));
    openAuctionRoom({pool: p.pool, to_you: {}, state: null});
    MP.auId = A.id; MP.auV = null;
    if (A.same) return;                                // the next poll brings the whole state
  }
  MP.built = false;
  MP.au = st;
  if (!A.same) {
    MP.auV = A.v;
    for (const [id, c] of Object.entries(A.changes)) { const p = APOOL.get(id); if (p) Object.assign(p, c); }
    TOYOU = A.to_you || {};
    renderAuction({...A.state, mp: true});
  }
  mpAuctionBar(st);
}
/* the room's own bits: whose call it is (with the clock), Ready / New auction / Leave, an absent player's hand-over */
function mpAuctionBar(st) {
  const A = st.auction, s = AU, i = st.you, me = s.user, other = i === 'spectator' ? null : A.players[1 - i];
  const secs = A.seconds || {}, q = s.question;
  if (!s.done) {
    const w = (s.waiting || []).filter(u => u !== me);
    let t = q ? (RP.busy ? 'Bidding…' : 'Your call!') : w.length ? `Waiting for ${w.join(' and ')}…` : 'Bidding…';
    if (q && secs[me] !== null && secs[me] !== undefined && !RP.busy) t += ` · ${secs[me]}s`;
    else if (!q && w.length && secs[w[0]] !== null && secs[w[0]] !== undefined) t += ` · ${secs[w[0]]}s`;
    $('au-turn').textContent = t;
    $('au-turn').className = 'turn' + (q && !RP.busy ? ' you' : '');
    if ($('au-turn').classList.contains('you') && secs[me] !== null && secs[me] !== undefined) $('au-turn').classList.toggle('low', secs[me] <= 3);
  }
  const myReady = i !== 'spectator' && A.ready[i];
  $('au-play').style.display = s.done && me ? '' : 'none';
  $('au-play').textContent = myReady ? 'Not ready' : '▶ Ready to play';
  $('au-play').className = 'btn ' + (myReady ? 'sec' : 'go');
  const key = JSON.stringify([s.done, A.ready, st.can_take, i, other]);
  let extra = document.getElementById('au-mp-extra');
  if (!extra) { extra = document.createElement('span'); extra.id = 'au-mp-extra'; extra.style.display = 'contents'; $('au-play').after(extra); }
  if (extra.dataset.key === key) return;
  extra.dataset.key = key;
  const play = mpPlayText(st.settings).split(' · ').pop();
  extra.innerHTML = (s.done && me ? `<span class="muted small">${myReady ? (A.ready[1 - i] ? 'Starting…' : `Waiting for ${esc(other)} to be ready.`)
      : A.ready[1 - i] ? `${esc(other)} is ready to play.` : esc(play[0].toUpperCase() + play.slice(1)) + '.'}</span>` : '')
    + (st.can_take ? `<button class="btn sec" id="au-take" style="width:auto">Let the computer bid for ${esc(other)} (away)</button>` : '')
    + (i === 0 ? '<button class="btn sec" id="au-redo" style="width:auto">New auction</button>' : '')
    + `<button class="btn sec" id="au-leave" style="width:auto">${i === 0 ? 'Close the room' : i === 'spectator' ? 'Stop watching' : 'Leave'}</button>`;
  if ($('au-take')) $('au-take').onclick = () => mpAuctionSend({take: true});
  if ($('au-redo')) $('au-redo').onclick = () => { if (confirm('Throw this auction away and go back to the room settings?')) mpAuctionSend({redo: true}); };
  $('au-leave').onclick = mpLeave;
}

/* ───────── the match ───────── */
function mpPlaying(st) {
  showView('v-captain');
  $('go-btn').disabled = true;
  $('cap-progress').textContent = '';
  setDisplayTeams(st.names);
  MP.series = st.series; MP.names = st.names;
  const serLine = mpSeriesLine(st.series, st.names);
  if (st.you === 'spectator') {
    $('cap-title').innerHTML = `${badge(st.names[0], 'sm')} ${esc(dn(st.names[0]))} v ${badge(st.names[1], 'sm')} ${esc(dn(st.names[1]))} · watching`;
    $('cap-ctx').textContent = 'Two players';
    $('cap-progress').innerHTML = serLine;
    $('cap-opp').textContent = ''; $('cap-clock').textContent = '';
    if (st.latest) { $('cap-score').innerHTML = scoreHTML({state: st.latest}); $('cap-bug').innerHTML = bugHTML({state: st.latest}); }
    $('cap-q').innerHTML = '<div class="muted">You are watching. The scoreboard updates whenever a player has a decision to make.</div>';
    document.querySelector('#v-captain .cap-ctl').style.display = 'none';
    return;
  }
  document.querySelector('#v-captain .cap-ctl').style.display = '';
  const me = st.me, opp = st.opp;
  MP.team = me.team;
  CAP.impact = st.settings.comp === 'ipl' && st.settings.year >= 2023;
  if (!me.pending) $('cap-title').innerHTML = `You captain ${badge(me.team, 'sm')} ${esc(dn(me.team))}`;
  capRender({done: st.job.done, total: st.job.total, captain: {pending: me.pending, manual: me.manual}});
  if ($('cap-progress').innerHTML !== serLine) $('cap-progress').innerHTML = serLine;
  // the other player: what they are doing, and a hand-over if they have gone
  let o = `${esc(dn(opp.team))}: ${opp.computer ? 'the computer is playing their side' : opp.choosing ? MP_DOING[opp.choosing] + '…' : 'playing'}`;
  if (opp.gone > 15 && !opp.computer) o += ` · <span style="color:var(--amber)">no contact for ${opp.gone} s</span>`;
  if (opp.can_take) o += ` <button class="btn sec" id="mp-take" style="width:auto;padding:3px 8px">Hand their side to the computer</button>`;
  if (o !== MP.oppHTML) {
    MP.oppHTML = o; $('cap-opp').innerHTML = o;
    if ($('mp-take')) $('mp-take').onclick = () => mpControl('opponent');
  }
  $('cap-back').style.display = me.skip || me.manual.length < me.home.length ? '' : 'none';
  if (!me.pending) {
    if (st.latest) { $('cap-score').innerHTML = scoreHTML({state: st.latest, team: me.team}); $('cap-bug').innerHTML = bugHTML({state: st.latest, team: me.team}); }
    const w = me.skip ? `Skipping to the end of the ${me.skip === 'innings' ? 'innings' : 'match'}: the computer plays your side.`
      : !me.manual.length ? 'The computer is playing your side.'
      : opp.choosing && !opp.computer ? `Waiting for ${esc(dn(opp.team))} - ${MP_DOING[opp.choosing]}…` : 'Playing on…';
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
