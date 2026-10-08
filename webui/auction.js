/* Auction game (engine/auction.py): the form, the auction room and its questions. The server runs the auction up
   to the next decision of your team (retentions, a bid, Right to Match); /api/auction/act sends the answer. */
'use strict';

const cr = l => l === null || l === undefined ? '–' : l >= 100 ? `₹${(l / 100).toFixed(2)} cr` : `₹${l} L`;
const HOMES = ['India', 'Australia', 'England', 'Pakistan', 'South Africa', 'New Zealand', 'West Indies', 'Sri Lanka',
  'Bangladesh', 'Afghanistan', 'Zimbabwe', 'Ireland'];
const RET_CAPPED = [1800, 1400, 1100, 1800, 1400], RET_UNCAPPED = 400;
let AU = null, APOOL = null, ALAST = {teams: []};

/* ───────────── form ───────────── */
function initAuctionForm() {
  fillSelect($('a-league'), META.leagues.map(l => ({v: l.id, t: l.label})));
  fillSelect($('a-home'), [{v: '', t: 'None - no overseas limits'}, ...HOMES.map(h => ({v: h, t: h}))]);
  fillSelect($('a-ko'), META.knockouts.map(k => ({v: k.id, t: k.label})));
  const seasons = () => { const l = aLeague(); fillSelect($('a-season'), l ? l.seasons.map(s => ({v: s.season, t: s.season})) : []); aRefresh(); };
  $('a-league').onchange = seasons;
  ['a-season', 'a-pool', 'a-user', 'a-rounds', 'a-ko'].forEach(id => $(id).addEventListener('change', aRefresh));
  $('a-k').oninput = aNames;
  $('a-retain').onchange = () => { $('a-retain').dataset.picked = '1'; };
  aNames(); seasons();
  api('/api/auction/last').then(d => { ALAST = d; aRefresh(); }).catch(() => {});
}
const aLeague = () => META.leagues.find(x => x.id === $('a-league').value);
function aSeasonIdx() { const l = aLeague(); return l ? l.seasons.findIndex(s => s.season === $('a-season').value) : -1; }
function aNames() {
  const k = Math.max(2, Math.min(12, +$('a-k').value || 2)), box = $('a-names');
  const old = [...box.querySelectorAll('input')].map(i => i.value);
  box.innerHTML = '';
  for (let i = 0; i < k; i++) {
    const inp = document.createElement('input');
    inp.type = 'text'; inp.maxLength = 40; inp.style.marginBottom = '4px';
    inp.value = old[i] !== undefined ? old[i] : (META.draft_teams[i] || `Team ${i + 1}`);
    inp.oninput = aRefresh; box.appendChild(inp);
  }
  aRefresh();
}
function aTeams() {
  if ($('a-pool').value === 'years') return [...$('a-names').querySelectorAll('input')].map(i => i.value.trim());
  const l = aLeague(), s = l && l.seasons[aSeasonIdx()];
  return s ? s.teams.map(t => t.franchise || t.name) : [];
}
function aRefresh() {
  const years = $('a-pool').value === 'years';
  $('a-season-box').style.display = years ? 'none' : ''; $('a-years-box').style.display = years ? '' : 'none';
  if (MODE === 'auction') $('cond').style.display = years ? '' : 'none';
  const teams = aTeams(), keep = $('a-user').value, kr = $('a-retain').value, first = !$('a-user').options.length;
  fillSelect($('a-user'), [...teams.filter(Boolean).map(t => ({v: t, t})), {v: '', t: '— none: the computer bids for every team —'}]);
  if (!first && (keep === '' || teams.includes(keep))) $('a-user').value = keep;
  const opts = [], l = aLeague(), i = aSeasonIdx();
  if (!years && l && i >= 0 && i + 1 < l.seasons.length) opts.push({v: 'previous', t: `Previous season (${l.seasons[i + 1].season} squads)`});
  if ((ALAST.teams || []).some(t => teams.includes(t))) opts.push({v: 'last', t: `Your last auction (${ALAST.label})`});
  // saved runs of the same league (or format, for a years pool) with some of these teams: retain from their squads
  for (const s of META.saved || []) {
    const same = years ? s.fmt === $('c-fmt').value : s.comp === $('a-league').value;
    if (same && s.teams.some(t => teams.includes(t)))
      opts.push({v: 'saved:' + s.id, t: `Saved: ${s.name}${s.mode === 'auction' ? ' (auction squads)' : ''}`});
  }
  opts.push({v: 'none', t: 'No retentions'});
  fillSelect($('a-retain'), opts);
  if ($('a-retain').dataset.picked && opts.some(o => o.v === kr)) $('a-retain').value = kr;   // else the first option
  $('a-captain-box').style.display = $('a-user').value ? '' : 'none';
  $('a-total').textContent = `${teams.length} teams · purse ₹120 cr each · squads of 18–25, max 8 overseas` +
    (years ? ` · then ${matchCount(teams.length, +$('a-rounds').value, 1, $('a-ko').value)} matches` : ` · then a double round robin and IPL playoffs`);
}
async function startAuction() {
  const years = $('a-pool').value === 'years';
  const body = years
    ? {pool: 'years', fmt: $('c-fmt').value, y1: +$('a-ya').value, y2: +$('a-yb').value, source: $('a-src').value,
       home: $('a-home').value, years_mode: $('a-ymode').value, teams: aTeams()}
    : {pool: 'season', league: $('a-league').value, season: $('a-season').value};
  Object.assign(body, {user: $('a-user').value, retain: $('a-retain').value, seed: $('a-seed').value.trim()});
  const d = await api('/api/auction/start', body);
  APOOL = new Map(d.pool.map(p => [p.id, p]));
  fillSelect($('ap-role'), [{v: '', t: 'All roles'}, ...['Batter', 'WK', 'All-rounder', 'Pace', 'Spin'].map(r => ({v: r, t: r}))]);
  fillSelect($('ap-status'), [{v: '', t: 'Everyone'}, {v: 'pool', t: 'Still to come'}, {v: 'sold', t: 'Sold'},
    {v: 'retained', t: 'Retained'}, {v: 'unsold', t: 'Unsold'}]);
  ['ap-search', 'ap-role', 'ap-status'].forEach(id => $(id).oninput = drawAuctionPool);
  $('au-skip-set').onclick = () => auAct({auto: 'set'});
  $('au-skip-all').onclick = () => auAct({auto: 'all'});
  $('au-play').onclick = playAuctionLeague;
  renderAuction(d.state);
}
async function auAct(body) {
  $('au-msg').textContent = '';
  try {
    const d = await api('/api/auction/act', body);
    for (const [id, c] of Object.entries(d.changes)) Object.assign(APOOL.get(id), c);
    renderAuction(d.state);
  } catch (e) { $('au-msg').textContent = e.message; }
}
const answer = a => auAct({answer: a});
async function playAuctionLeague() {
  const st = AU, years = !st.comp, me = $('a-captain').checked ? st.user : '';
  const impact = st.comp === 'ipl' && st.year >= 2023;
  const body = years
    ? {mode: 'auction', fmt: st.fmt, comp: $('c-comp').value, year: +$('c-year').value,
       venues: [...$('c-venues').selectedOptions].map(o => o.value), seed: $('c-seed').value.trim(), rain: $('c-rain').checked,
       rounds: +$('a-rounds').value, knockout: $('a-ko').value}
    : {mode: 'auction', fmt: 't20', seed: $('a-seed').value.trim(), rain: $('a-rain').checked};
  if (me) { body.captain = me; body.opponents = $('a-opp').value; body.manual = ['toss', 'xi', 'bowler', 'batter', 'result', ...(impact ? ['impact'] : [])]; CAP.impact = impact; }
  try { await api('/api/run', body); poll(); }
  catch (e) { $('au-msg').textContent = e.message; toast(e.message, true); }
}

/* ───────────── auction room ───────────── */
function renderAuction(st) {
  AU = st;
  showView('v-auction'); $('go-btn').disabled = false;
  const me = st.user, q = st.question;
  $('au-title').textContent = `${st.label} auction` + (me ? ` — you bid for ${me}` : '');
  const set = st.sets[st.set_no];
  $('au-turn').textContent = st.done ? 'Auction complete' : q ? 'Your call!' : st.phase === 'retain' ? 'Retentions' : 'Bidding…';
  $('au-turn').className = 'turn' + (q ? ' you' : '');
  $('au-progress').textContent = st.done ? `${st.n_sold} players sold for ${cr(st.spent)}`
    : set ? `${set.name} (set ${st.set_no + 1} of ${st.sets.length}) · ${st.n_sold} sold so far` : '';
  const live = !st.done && me;
  $('au-skip-set').style.display = live && st.phase !== 'retain' && st.user_auto !== 'all' ? '' : 'none';
  $('au-skip-all').style.display = live && st.user_auto !== 'all' ? '' : 'none';
  $('au-play').style.display = st.done ? '' : 'none';
  $('au-q').innerHTML = st.done ? doneHTML(st) : q ? questionHTML(q, st) : '<div class="muted">The computer is bidding for you…</div>';
  wireQuestion(q);
  $('au-sales').innerHTML = '<tr><th>Player</th><th>Sold to</th><th>Price</th></tr>' + st.sales.map(s =>
    `<tr class="${s.team === me && me ? 'crease' : s.team ? '' : 'dim'}"><td>${esc(s.name)} <span class="muted small">${esc(s.role)}</span></td>
     <td>${s.team ? esc(s.team) + (s.how === 'rtm' ? ' (RTM)' : s.how === 'fill' ? ' (fill-up)' : '') : 'unsold'}</td><td>${cr(s.price)}</td></tr>`).join('');
  $('au-upcoming').textContent = st.upcoming.length ? 'Still to come in this set: ' + st.upcoming.join(', ') : '';
  const os = t => st.board[t].filter(p => p.overseas).length;
  $('au-teams').innerHTML = '<tr><th>Team</th><th>Players</th><th>OS</th><th>Purse left</th><th>RTM</th></tr>' + st.teams.map(t =>
    `<tr class="${t === me ? 'crease' : ''}"><td>${esc(t)}</td><td>${st.board[t].length}</td><td>${os(t)}</td><td>${cr(st.purse[t])}</td><td>${st.rtm[t]}</td></tr>`).join('');
  if (me) {
    $('au-squad-title').textContent = `Your squad (${st.board[me].length}, ${os(me)} overseas · ${cr(st.purse[me])} left)`;
    $('au-squad').innerHTML = st.board[me].map(p => `<li>${esc(p.name)}${osTag(p)} <span>${esc(p.role)} · ${cr(p.price)}${p.retained ? ' · retained' : ''}</span></li>`).join('') || '<li class="muted">No players yet</li>';
  }
  $('au-squad-box').style.display = me ? '' : 'none';
  drawBoard($('au-board'), st.teams, st.board, me);
  drawAuctionPool();
}
function lotHTML(p, extra = '') {
  const stats = [p.bat_avg ? `bat avg ${p.bat_avg}, SR ${p.bat_sr}` : '', p.econ ? `econ ${p.econ}, bowl avg ${p.bowl_avg}` : ''].filter(Boolean).join(' · ');
  return `<div class="au-name">${esc(p.name)}${osTag(p)} <span class="role">${esc(p.role)}</span></div>
    <div class="muted small">${esc(p.team)} · ${p.capped ? 'capped' : 'uncapped'}${stats ? ' · ' + stats : ''} · worth ${p.value > 0 ? '+' : ''}${p.value} runs a match
    · base ${cr(p.base)} · expected ${cr(p.est)}${p.prev ? ` · last squad: ${esc(p.prev)}` : ''}</div>${extra}`;
}
function bidLogHTML() {
  const lot = AU.lot;
  if (!lot || !lot.log.length) return '<div class="au-log muted small">No bids yet.</div>';
  return `<div class="au-log">${lot.log.slice(-10).map(b => `<span class="${b.team === AU.user ? 'me' : ''}">${esc(b.team)} ${cr(b.price)}${b.rtm ? ' RTM' : b.raise ? ' raise' : ''}</span>`).join('')}</div>`;
}
function questionHTML(q, st) {
  if (q.kind === 'retain') return retainHTML(q, st);
  const p = q.player, adv = q.advice;
  if (q.kind === 'bid') {
    const now = q.price ? `<b>${cr(q.price)}</b> ${esc(q.leader)}${q.leader === st.user ? ' (you)' : ''}` : '<b>No bid yet</b>';
    return lotHTML(p, `<div class="au-price">${now}</div>${bidLogHTML()}
      <div class="au-act">
        <button class="btn go" data-a="bid">Bid ${cr(q.next)}</button>
        <button class="btn sec" data-a="pass">Pass</button>
        ${adv >= q.next ? `<button class="btn sec" data-a="upto">Bid up to ${cr(Math.min(adv, q.cap))} (the computer's value)</button>` : ''}
        <span class="au-max">or up to ₹<input type="number" id="au-max" min="0" step="0.05" value="${(Math.max(adv, q.next) / 100).toFixed(2)}"> cr
        <button class="btn sec" data-a="max">Go</button></span>
      </div>
      <div class="hint">The computer would bid up to <b>${cr(adv)}</b> for you (what he adds to your best XI, at the market rate).
      You can spend up to ${cr(q.cap)} on him and still fill your squad.</div>`);
  }
  if (q.kind === 'rtm_use') return lotHTML(p, `${bidLogHTML()}<p style="margin:10px 0">Sold to <b>${esc(q.buyer)}</b> for <b>${cr(q.price)}</b>.
      Use a Right to Match card (${q.cards} left)? ${esc(q.buyer)} then gets one final raise, and you can match that too.</p>
      <div class="au-act"><button class="btn go" data-a="yes">Use RTM</button><button class="btn sec" data-a="no">Let him go</button></div>
      <div class="hint">The computer would ${adv >= q.price ? 'use it' : 'let him go'}: he is worth ${cr(adv)} to you.</div>`);
  if (q.kind === 'rtm_raise') return lotHTML(p, `${bidLogHTML()}<p style="margin:10px 0"><b>${esc(q.holder)}</b> used Right to Match at ${cr(q.price)}.
      Your one final raise (they can match it):</p>
      <div class="au-act"><span class="au-max">₹<input type="number" id="au-raise" step="0.05" min="${q.price / 100}" max="${q.cap / 100}" value="${(Math.min(Math.max(adv, q.price), q.cap) / 100).toFixed(2)}"> cr
        <button class="btn go" data-a="raise">Raise</button></span><button class="btn sec" data-a="keep">No raise (${cr(q.price)})</button></div>
      <div class="hint">He is worth ${cr(adv)} to you; you can go up to ${cr(q.cap)}.</div>`);
  if (q.kind === 'rtm_match') return lotHTML(p, `${bidLogHTML()}<p style="margin:10px 0"><b>${esc(q.buyer)}</b> raised to <b>${cr(q.price)}</b>. Match it?</p>
      <div class="au-act"><button class="btn go" data-a="yes">Match ${cr(q.price)}</button><button class="btn sec" data-a="no">Let him go</button></div>
      <div class="hint">The computer would ${adv >= q.price ? 'match' : 'let him go'}: he is worth ${cr(adv)} to you.</div>`);
  return '';
}
function retainHTML(q, st) {
  const sug = new Set(q.suggested);
  return `<h3>Retentions</h3>
    <p class="muted small" style="margin:4px 0 8px">Keep up to 6 players from your last squad: at most 5 capped (₹18, 14, 11, 18 and 14 cr in turn) and 2 uncapped (₹4 cr each).
    Each slot you don't use is a Right to Match card for the auction. Ticked: the computer's choice (players expected to fetch more than their slot costs).</p>
    <table class="mini"><tr><th></th><th>Player</th><th>Role</th><th></th><th>Expected price</th></tr>
    ${q.candidates.map(c => `<tr><td><input type="checkbox" class="au-ret" value="${esc(c.id)}" data-capped="${c.capped ? 1 : 0}" ${sug.has(c.id) ? 'checked' : ''}></td>
      <td>${esc(c.name)}${osTag(c)}</td><td>${esc(c.role)}</td><td>${c.capped ? 'capped' : 'uncapped'}</td><td>${cr(c.est)}</td></tr>`).join('')}</table>
    <div class="au-act"><button class="btn go" data-a="retain">Confirm retentions</button><span class="muted small" id="au-ret-cost"></span></div>`;
}
function retCost() {
  const boxes = [...document.querySelectorAll('.au-ret:checked')];
  const c = boxes.filter(b => b.dataset.capped === '1').length, u = boxes.length - c;
  const cost = RET_CAPPED.slice(0, c).reduce((a, b) => a + b, 0) + RET_UNCAPPED * u;
  const bad = c > 5 || u > 2 || boxes.length > 6;
  $('au-ret-cost').innerHTML = bad ? '<span class="err">Too many: at most 5 capped and 2 uncapped.</span>'
    : `${boxes.length} retained for ${cr(cost)} · ₹${((12000 - cost) / 100).toFixed(2)} cr left · ${6 - boxes.length} RTM cards`;
}
function wireQuestion(q) {
  const on = (a, f) => { const b = document.querySelector(`#au-q [data-a="${a}"]`); if (b) b.onclick = f; };
  if (!q) return;
  if (q.kind === 'retain') {
    document.querySelectorAll('.au-ret').forEach(b => b.onchange = retCost); retCost();
    on('retain', () => answer({ids: [...document.querySelectorAll('.au-ret:checked')].map(b => b.value)}));
  }
  on('bid', () => answer({bid: true}));
  on('pass', () => answer({bid: false}));
  on('max', () => answer({max: Math.round(+$('au-max').value * 100)}));
  on('upto', () => answer({max: Math.min(q.advice, q.cap)}));
  on('yes', () => answer({yes: true}));
  on('no', () => answer({yes: false}));
  on('raise', () => answer({amount: Math.round(+$('au-raise').value * 100)}));
  on('keep', () => answer({amount: q.price}));
}
function doneHTML(st) {
  const me = st.user;
  return `<h3>Auction complete</h3><p class="muted small" style="margin:6px 0">${st.n_sold} players bought for ${cr(st.spent)}.
    ${me ? `Your squad: ${st.board[me].length} players, ${cr(st.purse[me])} left.` : ''} ${st.news.map(esc).join(' ')}
    Press “Play the league” for the season${me && $('a-captain').checked ? `, with you as captain of ${esc(me)}` : ''}.</p>`;
}
function drawAuctionPool() {
  if (!APOOL) return;
  const q = $('ap-search').value.toLowerCase(), role = $('ap-role').value, status = $('ap-status').value;
  const rows = [...APOOL.values()].filter(p => (!q || p.name.toLowerCase().includes(q)) && (!role || p.role === role) && (!status || p.status === status));
  table($('ap-table'), [
    {k: 'name', label: 'Player', html: r => `${esc(r.name)}${osTag(r)}`}, {k: 'team', label: 'Team'}, {k: 'role', label: 'Role'},
    {k: 'value', label: 'Worth', num: true, f: r => fmtNum(r.value, 1)},
    {k: 'base', label: 'Base', num: true, f: r => cr(r.base)}, {k: 'est', label: 'Expected', num: true, f: r => cr(r.est)},
    {k: 'set', label: 'Set'}, {k: 'buyer', label: 'Bought by', f: r => r.buyer || (r.status === 'unsold' ? 'unsold' : '')},
    {k: 'price', label: 'Price', num: true, f: r => r.price ? cr(r.price) : ''},
  ], rows, {limit: 300, sort: {k: 'est', dir: -1}, empty: 'No players match'});
}
