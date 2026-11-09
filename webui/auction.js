/* Auction game (engine/auction.py): the form, the server calls, the wishlist, the players table and the
   retention / release / set / nomination questions; the room itself (stage, replay, teams, report) is in
   webui/auction_room.js. The server runs the auction up to the next decision of your team (retentions, a bid,
   Right to Match, a set coming up in wishlist mode, the accelerated round's names); /api/auction/act sends the
   answer, /api/auction/wish changes the wishlist. */
'use strict';

const cr = l => l === null || l === undefined ? '–' : l >= 100 ? `₹${(l / 100).toFixed(2)} cr` : `₹${l} L`;
const HOMES = ['India', 'Australia', 'England', 'Pakistan', 'South Africa', 'New Zealand', 'West Indies', 'Sri Lanka',
  'Bangladesh', 'Afghanistan', 'Zimbabwe', 'Ireland'];
const RET_CAPPED = [1800, 1400, 1100, 1800, 1400], RET_UNCAPPED = 400;
let AU = null, APOOL = null, ALAST = {teams: []}, TOYOU = {}, WISH_WIRED = false;

/* ───────────── form ───────────── */
function initAuctionForm() {
  fillSelect($('a-league'), META.leagues.map(l => ({v: l.id, t: l.label})));
  fillSelect($('a-home'), [{v: '', t: 'None - no overseas limits'}, ...HOMES.map(h => ({v: h, t: h}))]);
  fillSelect($('a-ko'), META.knockouts.map(k => ({v: k.id, t: k.label})));
  const seasons = () => { const l = aLeague(); fillSelect($('a-season'), l ? l.seasons.map(s => ({v: s.season, t: s.season})) : []); aRefresh(); };
  $('a-league').onchange = seasons;
  ['a-season', 'a-pool', 'a-user', 'a-rounds', 'a-ko', 'a-kind'].forEach(id => $(id).addEventListener('change', aRefresh));
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
  const mini = $('a-kind').value === 'mini';
  if (!mini) opts.push({v: 'none', t: 'No retentions'});
  fillSelect($('a-retain'), opts);
  $('a-retain-lbl').textContent = mini ? 'Squads to keep from' : 'Retain players from';
  $('a-kind-hint').innerHTML = mini
    ? `As in the IPL's auctions between mega auctions (Dec 2023, Dec 2025): each team keeps any of its players at the price it paid
      (a real season's squads: estimated contracts), up to 25 players and 8 overseas, and releases the rest into the pool.
      The purse is ₹120 cr less the players kept. No Right to Match, no marquee set; an overseas buy above ₹18 cr is paid ₹18 cr,
      but the whole bid comes off the purse.` + (opts.length ? '' : ' <span class="err">No squads to keep for these teams: play an auction first, or pick a real season with one before it.</span>')
    : 'Up to 6 players kept at ₹18, 14, 11, 18 and 14 cr (capped) and ₹4 cr (uncapped); unused slots become Right to Match cards.';
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
  Object.assign(body, {user: $('a-user').value, retain: $('a-retain').value, kind: $('a-kind').value, seed: $('a-seed').value.trim()});
  openAuctionRoom(await api('/api/auction/start', body));
}
function openAuctionRoom(d) {          // d.state null: the two-player room renders when its state arrives
  APOOL = new Map(d.pool.map(p => [p.id, p]));
  RP.qseq = null;
  fillSelect($('ap-role'), [{v: '', t: 'All roles'}, ...['Batter', 'WK', 'All-rounder', 'Pace', 'Spin'].map(r => ({v: r, t: r}))]);
  fillSelect($('ap-status'), [{v: 'sale', t: 'For sale'}, {v: '', t: 'Everyone'}, {v: 'pool', t: 'Still to come'}, {v: 'sold', t: 'Sold'},
    {v: 'retained', t: 'Retained'}, {v: 'unsold', t: 'Unsold'}]);
  ['ap-search', 'ap-role', 'ap-status'].forEach(id => $(id).oninput = drawAuctionPool);
  $('au-fold').onclick = () => document.body.classList.toggle('au-fold');
  if (!WISH_WIRED) {          // top-bid inputs live in the players table, the wishlist and the set preview
    WISH_WIRED = true;
    $('v-auction').addEventListener('change', e => {
      const w = e.target.closest('[data-wrow]');
      if (w) { const v = w.querySelector('.wish-max').value.trim();
        setWish(w.dataset.wrow, v === '' ? null : Math.round(+v * 100), w.querySelector('.wish-ask').checked); }
      if (e.target.id === 'au-pause' || e.target.id === 'au-pause-q') setPause(e.target.checked);
    });
    $('v-auction').addEventListener('click', e => {   // ☆ buttons: on / off the wishlist
      const b = e.target.closest('[data-star]');
      if (b) toggleWish(b.dataset.star);
      if (e.target.closest('[data-go-wish]')) auAct({auto: 'wish'});
    });
  }
  TOYOU = d.to_you || {};
  $('au-play').onclick = () => mpOn() ? mpAuctionSend({ready: !(MP.au && MP.au.auction.ready[MP.au.you])})
    : AU.career ? careerAuctionDone() : playAuctionLeague();
  if (d.state) renderAuction(d.state);
}
async function auAct(body) {
  if (mpOn()) {                        // two players: the room's endpoint (an answer names its question)
    if (body.answer && AU.question) body = {...body, answer: {...body.answer, seq: AU.question.seq}};
    return mpAuctionSend(body);
  }
  $('au-msg').textContent = '';
  try {
    const d = await api('/api/auction/act', body);
    for (const [id, c] of Object.entries(d.changes)) Object.assign(APOOL.get(id), c);
    TOYOU = d.to_you || {};
    renderAuction(d.state);
  } catch (e) { $('au-msg').textContent = e.message; }
}
const answer = a => auAct({answer: a});
async function setWish(id, max, ask) {
  $('au-msg').textContent = '';
  if (mpOn()) { const d = await mpAuctionSend({wish: {id, max, ask}}); if (d) AU.wish = d.wish; }
  else try { const d = await api('/api/auction/wish', {id, max, ask}); AU.wish = d.wish; }
  catch (e) { $('au-msg').textContent = e.message; }
  drawWish(); drawAuctionPool(); drawUpcoming(AU); drawTabs(AU);
}
const onWish = id => !!(AU.wish || {})[id];
const forSale = p => ['pool', 'unsold'].includes(p.status);
function starBtn(p) {
  if (!forSale(p)) return '';
  const on = onWish(p.id);
  return `<button class="ar-star ${on ? 'on' : ''}" data-star="${esc(p.id)}" title="${on ? 'On your wishlist: click to remove' : 'Add to your wishlist'}">${on ? '★' : '☆'}</button>`;
}
function toggleWish(id) {           // a new entry's top bid: what he is worth to you (at least his base price)
  const p = APOOL.get(id);
  if (!p || !forSale(p)) return;
  if (onWish(id)) return setWish(id, null, false);
  const top = Math.max(p.base, Math.round((TOYOU[id] || p.est || p.base) / 5) * 5);
  setWish(id, top, false).then(() => {
    if (AU.user_auto !== 'wish') toast(`${p.name} added at ${cr(top)}. Change top bids in the Wishlist tab; "By my wishlist" bids for them.`);
  });
}
async function setPause(on) {
  if (mpOn()) { const d = await mpAuctionSend({pause: on}); if (d) AU.pause_sets = d.pause_sets; }
  else try { const d = await api('/api/auction/wish', {pause: on}); AU.pause_sets = d.pause_sets; } catch (e) { $('au-msg').textContent = e.message; }
  drawWish();
}
function wishCell(p) {
  const w = (AU.wish || {})[p.id] || {};
  return `<span class="wish" data-wrow="${esc(p.id)}">₹<input type="number" class="wish-max" step="0.05" min="0" placeholder="–"
    value="${w.max ? (w.max / 100).toFixed(2) : ''}" title="Your top bid (₹ cr); empty = not on your list">
    <label title="Stop and ask me when he comes up"><input type="checkbox" class="wish-ask" ${w.ask ? 'checked' : ''}>ask</label></span>`;
}
const toYou = p => p.id in TOYOU ? cr(TOYOU[p.id]) : '';
function drawWish() {
  const st = AU, box = $('au-wish');
  if (!st.user || st.done) { box.innerHTML = ''; return; }
  if (!$('au-wadd')) {               // the search box stays put while the list under it is redrawn
    box.innerHTML = `<div class="ar-wadd"><input type="text" id="au-wadd" placeholder="Add a player: type a name…" autocomplete="off">
      <div id="au-wres"></div></div><div id="au-wlist"></div>`;
    $('au-wadd').oninput = drawWishSearch;
  }
  drawWishSearch();
  const ws = Object.entries(st.wish || {}).map(([id, w]) => ({p: APOOL.get(id), w})).filter(r => r.p);
  const open = ws.filter(r => forSale(r.p)), gone = ws.filter(r => !forSale(r.p));
  const sum = open.reduce((a, r) => a + (r.w.max || 0), 0);
  const live = !['retain', 'release'].includes(st.phase);
  const row = r => `<tr><td><b>${esc(r.p.name)}</b>${osTag(r.p)}<div class="muted small">${esc(r.p.role)} · ${esc(r.p.set || '')}${r.p.status === 'unsold' ? ' · unsold' : ''}</div></td>
    <td class="num">${cr(r.p.est)}</td><td class="num">${toYou(r.p)}</td><td>${wishCell(r.p)}</td>
    <td><button class="ar-x" data-star="${esc(r.p.id)}" title="Remove from your wishlist">×</button></td></tr>`;
  const done = r => `<div class="small">${esc(r.p.name)}: ${r.p.buyer === st.user ? `<span class="w">yours for ${cr(r.p.price)}</span>`
    : r.p.buyer ? `${tc(r.p.buyer)} for ${cr(r.p.price)}` : 'gone'}</div>`;
  $('au-wlist').innerHTML = `${open.length ? `<table class="mini ar-wtab"><tr><th>Player</th><th class="num">Expected</th><th class="num">To you</th><th>Top bid</th><th></th></tr>
      ${open.map(row).join('')}</table>
      <div class="muted small" style="margin:6px 0">${open.length} on your list, top bids ${cr(sum)} · your purse ${cr(st.purse[st.user])}${sum > st.purse[st.user] ? ' (you can\'t buy them all, which is fine)' : ''}</div>`
    : `<p class="muted small" style="margin:8px 0">Nobody on your list yet. Search above, or press ☆ next to a name in <i>Up next</i> or the Players tab.</p>`}
    <div class="ar-wfoot">${st.user_auto === 'wish' ? '<span class="w small">✔ Bidding by your wishlist</span>'
      : `<button class="btn sec" data-go-wish ${open.length && live ? '' : 'disabled'}>Bid by my wishlist</button>`}
      <label class="small"><input type="checkbox" id="au-pause" ${st.pause_sets ? 'checked' : ''}> stop before each set to change the list</label></div>
    <p class="muted small" style="margin-top:6px">By my wishlist: the computer bids for these players up to their top bids and passes on everyone else
      (list your former players to use Right to Match on them). Tick <i>ask</i> to decide yourself when he comes up.</p>
    ${gone.length ? `<h4 class="muted small" style="margin-top:8px">Already gone</h4>${gone.map(done).join('')}` : ''}`;
}
function drawWishSearch() {
  const box = $('au-wres'), q = $('au-wadd').value.trim().toLowerCase();
  if (q.length < 2) { box.innerHTML = ''; return; }
  const hits = [...APOOL.values()].filter(p => forSale(p) && p.name.toLowerCase().includes(q))
    .sort((a, b) => (b.est || 0) - (a.est || 0)).slice(0, 8);
  box.innerHTML = hits.map(p => `<div class="ar-wres"><button class="btn sec ar-addb" data-star="${esc(p.id)}">${onWish(p.id) ? '✓ On list' : '+ Add'}</button><span><b>${esc(p.name)}</b>${osTag(p)}
      <span class="muted small">${esc(p.role)} · ${esc(p.set || '')}</span></span>
      <span class="muted small">expected ${cr(p.est)}${p.id in TOYOU ? ` · to you ${cr(TOYOU[p.id])}` : ''}</span></div>`).join('')
    || '<div class="muted small" style="padding:6px 0">No player still for sale matches.</div>';
}
async function playAuctionLeague() {
  const st = AU, years = !st.comp, me = $('a-captain').checked ? st.user : '';
  const impact = st.comp === 'ipl' && st.year >= 2023;
  const body = years
    ? {mode: 'auction', fmt: st.fmt, comp: $('c-comp').value, year: +$('c-year').value,
       venues: [...$('c-venues').selectedOptions].map(o => o.value), seed: $('c-seed').value.trim(), rain: $('c-rain').checked,
       rounds: +$('a-rounds').value, knockout: $('a-ko').value}
    : {mode: 'auction', fmt: 't20', seed: $('a-seed').value.trim(), rain: $('a-rain').checked};
  if (me) { body.captain = me; body.opponents = $('a-opp').value; body.manual = ['toss', 'xi', 'bowler', 'batter', 'result', ...(impact ? ['impact'] : []), ...($('a-ball').checked ? ['ball'] : [])]; CAP.impact = impact; }
  try { await api('/api/run', body); poll(); }
  catch (e) { $('au-msg').textContent = e.message; toast(e.message, true); }
}

function questionHTML(q, st) {      // the questions that are not about the player on the block
  if (q.kind === 'retain') return retainHTML(q, st);
  if (q.kind === 'release') return releaseHTML(q, st);
  if (q.kind === 'set') return setHTML(q, st);
  if (q.kind === 'nominate') return nominateHTML(q, st);
  return '';
}
function setHTML(q, st) {
  return `<h3>Coming up: ${esc(q.name)}</h3>
    <p class="muted small" style="margin:4px 0 8px">You are bidding by your wishlist. Change top bids for this set, then go on.</p>
    <table class="mini"><tr><th>Player</th><th>Role</th><th>Base</th><th>Expected</th><th>To you</th><th>Top bid</th></tr>
    ${q.players.map(c => { const p = APOOL.get(c.id) || c; return `<tr><td>${esc(p.name)}${osTag(p)}${p.prev === st.user ? ' <span class="w small">your RTM</span>' : ''}</td>
      <td>${esc(p.role)}</td><td>${cr(p.base)}</td><td>${cr(p.est)}</td><td>${toYou(p)}</td><td>${wishCell(p)}</td></tr>`; }).join('')}</table>
    <div class="au-act"><button class="btn go" data-a="go">Start the set</button><button class="btn sec" data-a="self">Bid myself from here</button>
      <label class="small"><input type="checkbox" id="au-pause-q" ${st.pause_sets ? 'checked' : ''}> stop before each set</label></div>`;
}
function nominateHTML(q, st) {
  const sug = new Set(q.suggested);
  return `<h3>Accelerated round</h3>
    <p class="muted small" style="margin:4px 0 8px">These players went unsold. Tick the ones you want brought back; the other teams name theirs too,
    and every named player is auctioned again. Ticked: ${st.user_auto === 'wish' ? 'your wishlist' : "the computer's choice (worth his base price to you)"}.
    Teams short of ${st.squad_min} players then fill up at ₹30 L each.</p>
    <table class="mini"><tr><th></th><th>Player</th><th>Role</th><th>Base</th><th>Expected</th><th>To you</th></tr>
    ${q.players.map(c => `<tr><td><input type="checkbox" class="au-nom" value="${esc(c.id)}" ${sug.has(c.id) ? 'checked' : ''}></td>
      <td>${esc(c.name)}${osTag(c)}</td><td>${esc(c.role)}</td><td>${cr(c.base)}</td><td>${cr(c.est)}</td><td>${toYou(c)}</td></tr>`).join('')}</table>
    <div class="au-act"><button class="btn go" data-a="nominate">Bring these back</button></div>`;
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
function releaseHTML(q, st) {
  const sug = new Set(q.suggested);
  return `<h3>Releases (mini auction)</h3>
    <p class="muted small" style="margin:4px 0 8px">Keep any of your players at their contract prices (they come off your ₹120 cr purse), at most 25 and 8 overseas,
    or release them into the auction (no Right to Match on them).
    Ticked: the computer's choice (players now expected to fetch less than ${Math.round(75)}% of their contract). Ages and form have moved on since they were bought.</p>
    <table class="mini"><tr><th>Release</th><th>Player</th><th>Role</th><th>Contract</th><th>Expected now</th></tr>
    ${q.squad.map(c => `<tr><td><input type="checkbox" class="au-rel" value="${esc(c.id)}" data-c="${c.contract || 0}" data-os="${c.overseas ? 1 : 0}" ${sug.has(c.id) ? 'checked' : ''}></td>
      <td>${esc(c.name)}${osTag(c)}</td><td>${esc(c.role)}</td><td>${cr(c.contract)}</td><td class="${c.est < c.contract ? 'l' : 'w'}">${cr(c.est)}</td></tr>`).join('')}</table>
    <div class="au-act"><button class="btn go" data-a="release">Confirm releases</button><span class="muted small" id="au-rel-cost"></span></div>`;
}
function relCost() {
  const all = [...document.querySelectorAll('.au-rel')], kept = all.filter(b => !b.checked);
  const cost = kept.reduce((a, b) => a + +b.dataset.c, 0);
  const os = kept.filter(b => b.dataset.os === '1').length;
  const bad = kept.length > 25 ? 'Keep at most 25 players.' : os > 8 ? 'Keep at most 8 overseas players.' : cost > 12000 ? 'The players you keep cost more than the purse.' : '';
  $('au-rel-cost').innerHTML = bad ? `<span class="err">${bad}</span>`
    : `${kept.length} kept (${os} overseas) for ${cr(cost)} · ${cr(12000 - cost)} to spend · ${all.length - kept.length} released`;
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
  if (q.kind === 'release') {
    document.querySelectorAll('.au-rel').forEach(b => b.onchange = relCost); relCost();
    on('release', () => answer({ids: [...document.querySelectorAll('.au-rel:checked')].map(b => b.value)}));
  }
  on('go', () => answer({go: true}));
  on('self', () => answer({self: true}));
  on('nominate', () => answer({ids: [...document.querySelectorAll('.au-nom:checked')].map(b => b.value)}));
  on('bid', () => answer({bid: true}));
  on('pass', () => answer({bid: false}));
  on('max', () => answer({max: +$('ar-lim').value}));
  on('yes', () => answer({yes: true}));
  on('no', () => answer({yes: false}));
  on('raise', () => answer({amount: Math.round(+$('au-raise').value * 100)}));
  on('keep', () => answer({amount: q.price}));
}
function drawAuctionPool() {
  if (!APOOL) return;
  if (AU && AU.done && $('ap-status').value === 'sale') $('ap-status').value = '';   // nobody is for sale any more
  const q = $('ap-search').value.toLowerCase(), role = $('ap-role').value, status = $('ap-status').value;
  const rows = [...APOOL.values()].filter(p => (!q || p.name.toLowerCase().includes(q)) && (!role || p.role === role) && (!status || p.status === status || status === 'sale' && forSale(p)));
  const mine = AU && AU.user && !AU.done;
  const top = r => ((AU.wish || {})[r.id] || {}).max;
  table($('ap-table'), [
    ...(mine ? [{k: 'star', label: '☆', nosort: true, html: starBtn}] : []),
    {k: 'name', label: 'Player', html: r => `${esc(r.name)}${osTag(r)}<div class="muted small">${esc(r.role)} · ${esc(r.team)}</div>`},
    {k: 'value', label: 'Worth', num: true, f: r => fmtNum(r.value, 1)},
    {k: 'est', label: 'Expected', num: true, f: r => cr(r.est)},
    ...(mine ? [{k: 'toyou', label: 'To you', num: true, sv: r => TOYOU[r.id], f: toYou},
      {k: 'top', label: 'Top bid', num: true, sv: top, f: r => top(r) ? cr(top(r)) : ''}] : []),
    {k: 'set', label: 'Set', html: r => `<span class="small muted">${esc(r.set || '')}</span>`},
    {k: 'price', label: 'Sold', num: true, html: r => r.buyer ? `${tc(r.buyer)} ${cr(r.price)}` : r.status === 'unsold' ? '<span class="muted">unsold</span>' : ''},
  ], rows, {limit: 300, sort: {k: 'est', dir: -1}, empty: 'No players match'});
}
