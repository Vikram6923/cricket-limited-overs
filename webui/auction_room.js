/* Auction room: team colours, the stage (player card, price bar, bidding replay, controls), the set timeline, the
   teams strip, your team, the sales feed and the report card. webui/auction.js has the form, the server calls, the
   wishlist and the retention / release / set / nomination questions. */
'use strict';

/* ───────────── team colours ───────────── */
// [short name, background, text, accent stripe]: the clubs' best-known colours (not official values)
const FRANCHISE = {
  'Chennai Super Kings': ['CSK', '#F9CD05', '#1a1a1a', '#0081E9'], 'Mumbai Indians': ['MI', '#004BA0', '#fff', '#D1AB3E'],
  'Royal Challengers Bengaluru': ['RCB', '#2B2A29', '#fff', '#EC1C24'], 'Royal Challengers Bangalore': ['RCB', '#2B2A29', '#fff', '#EC1C24'],
  'Kolkata Knight Riders': ['KKR', '#3A225D', '#fff', '#B3A123'], 'Sunrisers Hyderabad': ['SRH', '#F26522', '#000', '#000'],
  'Rajasthan Royals': ['RR', '#EA1A85', '#fff', '#254AA5'], 'Delhi Capitals': ['DC', '#17479E', '#fff', '#EF1B23'],
  'Delhi Daredevils': ['DD', '#1A2A6C', '#fff', '#EF1B23'], 'Punjab Kings': ['PBKS', '#D71920', '#fff', '#DCDDDF'],
  'Kings XI Punjab': ['KXIP', '#D71920', '#fff', '#DCDDDF'], 'Gujarat Titans': ['GT', '#1B2133', '#fff', '#B8975A'],
  'Lucknow Super Giants': ['LSG', '#0057E2', '#fff', '#F28B00'], 'Deccan Chargers': ['DEC', '#1D3F6E', '#fff', '#C0C0C0'],
  'Gujarat Lions': ['GL', '#E04F16', '#fff', '#1D1D1B'], 'Kochi Tuskers Kerala': ['KTK', '#5B2C83', '#fff', '#F28C28'],
  'Pune Warriors': ['PWI', '#2F9BD6', '#000', '#1B1B1B'], 'Rising Pune Supergiant': ['RPS', '#252C64', '#fff', '#D1176C'],
  'Rising Pune Supergiants': ['RPS', '#252C64', '#fff', '#D1176C'],
  'Adelaide Strikers': ['STR', '#00A3E0', '#000', '#002B5C'], 'Brisbane Heat': ['HEA', '#00B2A9', '#000', '#E4002B'],
  'Hobart Hurricanes': ['HUR', '#6A2C91', '#fff', '#A6CE39'], 'Melbourne Renegades': ['REN', '#D71920', '#fff', '#1D1D1B'],
  'Melbourne Stars': ['STA', '#00A651', '#000', '#004225'], 'Perth Scorchers': ['SCO', '#F47920', '#000', '#1D1D1B'],
  'Sydney Sixers': ['SIX', '#E6007E', '#fff', '#1D1D1B'], 'Sydney Thunder': ['THU', '#A6CE39', '#000', '#1D1D1B'],
  'Islamabad United': ['IU', '#E31B23', '#fff', '#1D1D1B'], 'Karachi Kings': ['KK', '#0072BC', '#fff', '#E31B23'],
  'Lahore Qalandars': ['LQ', '#00A651', '#000', '#E31B23'], 'Multan Sultans': ['MS', '#00A79D', '#000', '#F8C300'],
  'Peshawar Zalmi': ['PZ', '#FDB913', '#000', '#1D1D1B'], 'Quetta Gladiators': ['QG', '#6A2C91', '#fff', '#FDB913'],
  'MI Cape Town': ['MICT', '#004BA0', '#fff', '#D1AB3E'], 'MI Emirates': ['MIE', '#004BA0', '#fff', '#D1AB3E'],
  'MI New York': ['MINY', '#004BA0', '#fff', '#D1AB3E'], 'Joburg Super Kings': ['JSK', '#F9CD05', '#1a1a1a', '#0081E9'],
  'Texas Super Kings': ['TSK', '#F9CD05', '#1a1a1a', '#0081E9'], 'Sunrisers Eastern Cape': ['SEC', '#F26522', '#000', '#000'],
  'Paarl Royals': ['PR', '#EA1A85', '#fff', '#254AA5'], 'Barbados Royals': ['BR', '#EA1A85', '#fff', '#254AA5'],
  'Pretoria Capitals': ['PC', '#17479E', '#fff', '#EF1B23'], 'Dubai Capitals': ['DCP', '#17479E', '#fff', '#EF1B23'],
  "Durban's Super Giants": ['DSG', '#0057E2', '#fff', '#F28B00'], 'Abu Dhabi Knight Riders': ['ADKR', '#3A225D', '#fff', '#B3A123'],
  'Los Angeles Knight Riders': ['LAKR', '#3A225D', '#fff', '#B3A123'], 'Trinbago Knight Riders': ['TKR', '#C8102E', '#fff', '#1D1D1B'],
};
const PALETTE = ['#4C8DFF', '#E3B341', '#3FB950', '#F85149', '#A371F7', '#F778BA', '#39C5CF', '#FF9F43', '#56D364',
  '#D2A8FF', '#FFA198', '#79C0FF'];
let COL = {};
const lum = h => { const n = parseInt(h.slice(1), 16), c = [n >> 16, (n >> 8) & 255, n & 255].map(v => v / 255);
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]; };
function autoShort(name) {
  const w = name.split(/[\s&]+/).filter(x => x && !/^(and|of|the)$/i.test(x));
  return w.length === 1 ? w[0].slice(0, 3).toUpperCase() : w.map(x => /^\d+$/.test(x) ? x : x[0].toUpperCase()).join('').slice(0, 4);
}
function buildColours(teams) {
  COL = {};
  let k = 0;
  const used = new Set();
  for (const t of teams) {
    let [short, bg, fg, ac] = FRANCHISE[t] || [autoShort(t), PALETTE[k++ % PALETTE.length], null, null];
    if (!fg) { fg = lum(bg) > 0.45 ? '#111' : '#fff'; ac = 'rgba(0,0,0,.35)'; }
    let s = short, n = 2;
    while (used.has(s)) s = short.slice(0, 3) + n++;
    used.add(s);
    // `hi`: a colour that shows on the dark page (dark kits use their accent)
    COL[t] = {short: s, bg, fg, ac, hi: lum(bg) < 0.12 ? ac : bg};
  }
}
const col = t => COL[t] || {short: autoShort(t || '?'), bg: '#555', fg: '#fff', ac: '#555', hi: '#888'};
const tc = (t, cls = '') => { const c = col(t);
  return `<span class="ar-tc ${cls}" style="--c:${c.bg};--f:${c.fg};--a:${c.ac}" title="${esc(t)}">${esc(c.short)}</span>`; };

/* ───────────── replay settings ───────────── */
const SPEED = {off: 0, fast: 70, slow: 220};
const RP = {lot: null, shown: 0, timer: null, busy: false, lastLabel: null};
const replaySpeed = () => { try { return localStorage.getItem('auReplay') || 'fast'; } catch (e) { return 'fast'; } };
const setReplaySpeed = v => { try { localStorage.setItem('auReplay', v); } catch (e) { /* private window */ } };

/* ───────────── the room ───────────── */
function renderAuction(st) {
  const fresh = !AU || RP.lastLabel !== st.label + '|' + st.teams.join();
  AU = st;
  if (fresh) {
    RP.lastLabel = st.label + '|' + st.teams.join();
    RP.lot = null; RP.shown = 0;
    buildColours(st.teams);
    document.body.classList.add('au-fold');
  }
  showView('v-auction'); $('go-btn').disabled = false;
  const me = st.user, q = st.question;
  $('au-title').innerHTML = `${esc(st.label)} auction` + (me ? ` <span class="muted small">you bid for</span> ${tc(me)}` : '');
  $('au-turn').textContent = st.done ? 'Auction complete' : q ? 'Your call!' : st.phase === 'retain' ? 'Retentions'
    : st.phase === 'release' ? 'Releases' : 'Bidding…';
  $('au-turn').className = 'turn' + (q ? ' you' : '');
  $('au-progress').textContent = st.n_sold ? `${st.n_sold} sold · ${cr(st.spent)} spent` : '';
  drawMode(st);
  $('au-play').style.display = st.done ? '' : 'none';
  $('au-play').textContent = st.career ? '✔ Save the squads and go back to the career' : '▶ Play the league';
  drawSets(st); drawStrip(); drawFeed(st); drawUpcoming(st); drawTeam(); drawWish(); drawReport();
  drawBoard($('au-board'), st.teams, st.board, me);
  drawAuctionPool(); drawTabs(st);
  drawStage(st);
}

function drawMode(st) {
  const me = st.user, live = me && !st.done && !['retain', 'release'].includes(st.phase);
  const cur = st.user_auto || 'ask';
  const opts = [['ask', 'I bid', 'You decide on every player'],
    ['wish', 'By my wishlist', 'The computer bids for your wishlist players up to their top bids and passes on everyone else'],
    ['set', 'Computer: this set', 'The computer bids for you until this set ends'], ['all', 'Computer: rest', 'The computer bids for you to the end']];
  $('au-mode').style.display = me && !st.done ? '' : 'none';
  $('au-mode').innerHTML = opts.map(([k, t, h]) => `<button class="${k === cur ? 'on' : ''}" data-mode="${k}" title="${h}" ${live ? '' : 'disabled'}>${t}</button>`).join('');
  $('au-mode').querySelectorAll('button').forEach(b => b.onclick = () => {
    const k = b.dataset.mode;
    if (k === cur) return;
    if (k === 'wish' && !Object.keys(AU.wish || {}).length) {
      showTab('wish');
      $('au-msg').textContent = 'Your wishlist is empty: add players first (☆ next to a name).';
      const f = $('au-wadd'); if (f) f.focus();
      return;
    }
    auAct({auto: k});
  });
}

/* the side panel's tabs */
const TABS = [['team', 'Your team'], ['wish', 'Wishlist'], ['players', 'Players'], ['sales', 'Sales'], ['squads', 'Squads']];
let TAB = null;
function drawTabs(st) {
  const ok = TABS.filter(([k]) => k === 'team' ? !!st.planner : k === 'wish' ? st.user && !st.done : true);
  if (!TAB || !ok.some(([k]) => k === TAB)) {
    let saved = null; try { saved = localStorage.getItem('auTab'); } catch (e) { /* private window */ }
    TAB = ok.some(([k]) => k === saved) ? saved : ok[0][0];
  }
  const nWish = Object.keys(st.wish || {}).filter(id => APOOL.get(id) && ['pool', 'unsold'].includes(APOOL.get(id).status)).length;
  const badge = k => k === 'wish' && nWish ? ` <i>${nWish}</i>` : k === 'sales' && st.n_sold ? ` <i>${st.n_sold}</i>` : '';
  $('au-tabs').innerHTML = ok.map(([k, t]) => `<button class="${k === TAB ? 'on' : ''}" data-tab="${k}">${t}${badge(k)}</button>`).join('');
  $('au-tabs').querySelectorAll('button').forEach(b => b.onclick = () => showTab(b.dataset.tab));
  document.querySelectorAll('#v-auction .au-pane').forEach(p => p.style.display = p.dataset.pane === TAB ? '' : 'none');
}
function showTab(k) {
  TAB = k;
  try { localStorage.setItem('auTab', k); } catch (e) { /* private window */ }
  drawTabs(AU);
}

function drawSets(st) {
  const box = $('au-sets');
  if (!st.sets.length) { box.innerHTML = ''; return; }
  const n = st.sets.length, i = Math.min(st.set_no, n - 1), s = st.sets[i];
  const all = st.sets.map((x, j) => `${j + 1}. ${x.name}`).join('\n');
  if (st.done || st.set_no < 0) {
    box.innerHTML = `<span title="${esc(all)}"><b>${n} sets</b> <span class="muted">${st.done ? 'all done' : 'bidding starts after retentions'}</span></span>`;
    return;
  }
  const left = st.upcoming.length + (st.lot && APOOL.get(st.lot.id) && APOOL.get(st.lot.id).status === 'pool' ? 1 : 0);
  const next = st.sets.slice(i + 1, i + 3).map(x => esc(x.name)).join(' → ');
  box.innerHTML = `<div class="ar-sprog" title="${esc(all)}"><i style="width:${100 * i / n}%"></i></div>
    <span title="${esc(all)}"><b>Set ${i + 1} of ${n}</b> · ${esc(s.name)} <span class="muted">· ${left} of ${s.n} left</span></span>
    ${next ? `<span class="muted nx">Next: ${next}${i + 3 < n ? ' …' : ''}</span>` : ''}`;
}

const NEED = {keeper: n => 'WK', bowler: n => `${n} bowler${n > 1 ? 's' : ''}`, other: n => `${n} bat/AR`};
function needsText(t) {
  const n = (AU.needs || {})[t];
  if (!n) return '';
  const parts = ['keeper', 'bowler', 'other'].filter(k => n[k]).map(k => NEED[k](n[k]));
  return parts.length ? 'needs ' + parts.join(', ') : 'XI full';
}
function drawStrip(live) {      // live: {in: Set, lead} while a lot is being bid for
  const st = AU;
  $('au-strip').innerHTML = st.teams.map(t => {
    const c = col(t), sq = st.board[t].length, os = st.board[t].filter(p => p.overseas).length;
    const cls = [t === st.user ? 'me' : '', live && live.in.has(t) && live.in.size < st.teams.length ? 'in' : '', live && live.lead === t ? 'lead' : '',
      live && !live.in.has(t) ? 'out' : ''].join(' ');
    const rtm = st.has_prev && st.phase === 'auction' && st.rtm[t] ? st.rtm[t] : 0;
    const tip = `${t}${t === st.user ? ' (you)' : ''}\n${cr(st.purse[t])} left · ${sq} of ${st.squad_max} players · ${st.overseas_max - os} overseas places left`
      + (rtm ? ` · ${rtm} Right to Match card${rtm > 1 ? 's' : ''}` : '') + (needsText(t) ? `\nXI ${needsText(t)}` : '');
    return `<div class="ar-tcard ${cls}" style="--c:${c.hi}" title="${esc(tip)}">
      <div class="hd">${tc(t)}<b>${cr(st.purse[t])}</b></div>
      <div class="ar-bar"><i style="width:${Math.max(0, 100 * st.purse[t] / 12000)}%"></i></div>
      <div class="sub">${sq}/${st.squad_max}${rtm ? `<span class="rtm">${rtm} RTM</span>` : ''}</div></div>`;
  }).join('');
}

function drawFeed(st) {
  const me = st.user;
  $('au-sales').innerHTML = st.sales.map(s => s.team
    ? `<div class="ar-sale ${s.team === me && me ? 'me' : ''}" style="--c:${col(s.team).hi}">${tc(s.team)}
        <div><div class="nm">${esc(s.name)}</div><div class="rl">${esc(s.role)}${s.how === 'rtm' ? ' · Right to Match' : s.how === 'fill' ? ' · fill-up' : ''}</div></div>
        <div class="pr">${cr(s.price)}</div></div>`
    : `<div class="ar-sale uns"><span class="ar-tc" style="--c:#333;--f:#999;--a:#333">—</span>
        <div><div class="nm">${esc(s.name)}</div><div class="rl">${esc(s.role)} · unsold${st.phase === 'auction' ? ', may come back' : ''}</div></div><div class="pr">–</div></div>`).join('')
    || '<div class="muted small">No sales yet.</div>';
}

function drawUpcoming(st) {
  const set = st.sets[st.set_no];
  $('au-next-box').style.display = st.done || !set || !['auction', 'accelerated'].includes(st.phase)
    || (st.question && ['set', 'nominate'].includes(st.question.kind)) ? 'none' : '';   // those questions list the players themselves
  if (!set) return;
  $('au-next-title').innerHTML = `Up next in ${esc(set.name)}${st.user ? ' <span class="muted small">☆ adds a player to your wishlist</span>' : ''}`;
  $('au-upcoming').innerHTML = st.upcoming.map(id => { const p = APOOL.get(id); if (!p) return '';
    const w = (st.wish || {})[id];
    return `<span class="ar-up ${w ? 'w' : ''}">${st.user ? starBtn(p) : ''}<span class="nm" title="${esc(p.role)} · ${esc(p.team)}">${esc(p.name)}${osTag(p)}</span>
      <span class="muted">${esc(p.role)} · ${cr(p.est)}</span></span>`; }).join('')
    || '<span class="muted small">Last player of the set.</span>';
}

/* ───────────── your team ───────────── */
const SLOT = {keeper: 'WK', bowler: 'Bowler', other: 'Bat / AR'};
function drawTeam() {
  const st = AU, pl = st.planner;
  if (!pl) { $('au-plan').innerHTML = ''; return; }
  const me = st.user, sq = st.board[me], os = sq.filter(p => p.overseas).length;
  const lot = !st.done && pl.lot;
  // the place the player on the block would take
  let ghost = -1;
  if (lot && lot.slot) ghost = lot.replaces === 'an open place' ? pl.xi.findIndex(x => x.open && x.slot === lot.slot)
    : pl.xi.findIndex(x => x.name === lot.replaces);
  const inXI = new Set(pl.xi.filter(x => !x.open).map(x => x.id));
  const bench = sq.filter(p => !inXI.has(p.id));
  const w = Math.max(3, Math.min(97, 50 + 3 * pl.vs_avg));
  $('au-plan').innerHTML = `<div class="ar-facts"><div>Purse left<b>${cr(st.purse[me])}</b></div><div>Players<b>${sq.length} / ${st.squad_max}</b>min ${st.squad_min}</div>
      <div>Overseas<b>${os} / ${st.overseas_max}</b>${pl.xi_overseas_max === null ? 'no XI limit' : `XI: ${pl.xi_overseas} / ${pl.xi_overseas_max}`}</div></div>
    <div class="ar-meter" title="Best XI's worth in runs a match, against the average team (the tick)"><span class="muted">XI strength</span>
      <div class="ar-bar"><i style="width:${w}%;background:${pl.vs_avg >= 0 ? 'var(--green)' : 'var(--red)'}"></i><span class="avg"></span></div>
      <b>${fmtNum(pl.total, 1)}</b><span class="${pl.vs_avg >= 0 ? 'w' : 'l'}">${pl.vs_avg >= 0 ? '+' : ''}${fmtNum(pl.vs_avg, 1)}</span></div>
    <div class="ar-xi">${pl.xi.map((x, i) => i === ghost
      ? `<div class="ar-slot ghost"><div class="k">${SLOT[x.slot]}</div><div class="p">${esc(lot.name)}?</div><div class="v">+${fmtNum(lot.gain, 1)}${x.open ? '' : ` · for ${esc(x.name)}`}</div></div>`
      : x.open ? `<div class="ar-slot open"><div class="k">${SLOT[x.slot]}</div><div>open</div></div>`
      : `<div class="ar-slot"><div class="k">${SLOT[x.slot]}</div><div class="p">${esc(x.name)}${osTag(x)}</div><div class="v">${fmtNum(x.value, 1)}</div></div>`).join('')}</div>
    <div class="ar-bench">${bench.length ? 'Bench: ' + bench.map(p => `${esc(p.name)} <span class="muted">${cr(p.price)}</span>`).join(' · ') : 'Bench: none yet'}
      ${lot && !lot.slot ? `<div style="margin-top:4px">${esc(lot.name)} would not make your best XI (+${fmtNum(lot.gain, 1)}).</div>` : ''}</div>`;
}

/* ───────────── the stage ───────────── */
const LOT_KINDS = ['bid', 'rtm_use', 'rtm_raise', 'rtm_match'];
function drawStage(st) {
  const q = st.question, box = $('au-q');
  clearTimeout(RP.timer); RP.busy = false;
  if (st.done) { box.innerHTML = doneHTML(st); RP.lot = null; return; }
  if (!q) { box.innerHTML = '<div class="muted">The computer is bidding for you…</div>'; return; }
  if (!LOT_KINDS.includes(q.kind)) { box.innerHTML = questionHTML(q, st); wireQuestion(q); return; }
  const lot = st.lot, prevId = RP.lot, sp = SPEED[replaySpeed()];
  const prevRow = prevId && prevId !== lot.id ? APOOL.get(prevId) : null;
  const finished = prevRow && ['sold', 'unsold'].includes(prevRow.status);
  const pl = st.prev_lot;
  if (finished && sp && pl && pl.id === prevId && RP.shown < pl.log.length) {
    // the rest of the bidding for the player you last saw (after your pass or limit), SOLD, then this one
    const from = RP.shown;
    showLot(st, {kind: 'watch', player: prevRow}, pl);
    replay(from, () => hammer(prevRow, () => showQuestion(st, 0)));
  } else if (finished && sp) showQuestion(st, 0, prevRow);
  else showQuestion(st, prevId === lot.id ? RP.shown : 0);
}
function showLot(st, q, lot) {        // put a lot on the stage: the question's, or one being watched
  RP.view = lot; RP.lot = lot.id;
  $('au-q').innerHTML = stageHTML(q, st, lot);
  if (q.kind !== 'watch') wireQuestion(q);
  wireStage(q);
}
function showQuestion(st, from, hammerFor) {
  showLot(st, st.question, st.lot);
  RP.shown = from;
  if (hammerFor) hammer(hammerFor, () => replay(from)); else replay(from);
}

function stageHTML(q, st, lot) {
  const p = q.player, lp = q.kind !== 'watch' && st.planner && st.planner.lot;
  const initials = p.name.split(/\s+/).map(w => w[0]).join('').slice(0, 2).toUpperCase();
  const tiles = [];
  if (p.bat_avg) tiles.push(['Bat avg', p.bat_avg], ['Strike rate', p.bat_sr]);
  if (p.econ) tiles.push(['Economy', p.econ], ['Bowl avg', p.bowl_avg]);
  tiles.splice(3);
  tiles.push(['Worth', (p.value > 0 ? '+' : '') + fmtNum(p.value, 1), 'runs a match']);
  if (lp) tiles.push(['Adds to you', (lp.gain >= 0 ? '+' : '') + fmtNum(lp.gain, 1), lp.slot ? `${SLOT[lp.slot].toLowerCase()}${lp.replaces === 'an open place' ? ', open place' : ', for ' + lp.replaces}` : 'not in your XI', 'g']);
  const prev = p.prev ? `<span class="ar-badge">last squad ${tc(p.prev)}${st.has_prev ? ` · ${st.rtm[p.prev] || 0} RTM card${st.rtm[p.prev] === 1 ? '' : 's'}` : ''}</span>` : '';
  return `<div class="ar-sold" id="ar-sold"></div>
    <div class="ar-stbar"><span>${q.kind === 'watch' ? 'Still bidding' : 'On the block'}${p.set ? ` · ${esc(p.set)}` : ''}</span><span style="flex:1"></span>
      <button class="ar-chip" id="ar-skip" title="Skip the replay (S)" style="visibility:hidden">Skip ▸▸</button>
      <label title="How the other teams' bids are played back">Replay <select id="ar-sp">${Object.keys(SPEED).map(k =>
        `<option value="${k}" ${replaySpeed() === k ? 'selected' : ''}>${k[0].toUpperCase() + k.slice(1)}</option>`).join('')}</select></label></div>
    <div class="ar-pcard">
      <div class="ar-avatar ${esc(p.role.replace(/\W/g, ''))}">${esc(initials)}</div>
      <div style="min-width:0;flex:1"><div class="ar-pname">${esc(p.name)}</div>
        <div class="ar-badges"><span class="ar-badge role">${esc(p.role)}</span>${p.overseas ? '<span class="ar-badge os">overseas</span>' : ''}
          <span class="ar-badge">${esc(p.team)} · ${p.capped ? 'capped' : 'uncapped'}</span>${prev}</div></div>
    </div>
    <div class="ar-tiles">${tiles.map(([k, v, s, c]) => `<div class="ar-tile"><div class="k">${k}</div><div class="v ${c || ''}">${esc(String(v))}</div>${s ? `<div class="s">${esc(s)}</div>` : ''}</div>`).join('')}</div>
    <div class="ar-price"><span class="now" id="ar-now">${cr(p.base)}</span><span class="by" id="ar-by"><span class="muted">base price</span></span></div>
    <div class="ar-call" id="ar-call"></div>
    ${priceBarHTML(q, p, lot)}
    <div class="ar-log" id="ar-log"></div>
    ${controlsHTML(q, st)}`;
}

function barMax(q, p, lot) {
  const lim = q.kind === 'bid' ? Math.min(Math.max(q.advice, q.next), q.cap) : 0;
  const top = Math.max(p.est, q.advice || 0, lim, q.price || 0, ...lot.log.map(b => b.price));
  return Math.max(500, Math.ceil(top * 1.15 / 100) * 100);
}
function priceBarHTML(q, p, lot) {   // marks on the bar, their values in a legend under it (labels on the bar collide)
  const mx = barMax(q, p, lot), pos = l => `${Math.max(0, Math.min(100, 100 * l / mx))}%`;
  const marks = [[p.base, 'base', 'var(--muted)', ''], [p.est, 'expected', 'var(--amber)', '']];
  if (q.advice) marks.push([q.advice, 'to you', 'var(--green)', '']);
  if (q.kind === 'bid' && q.cap >= q.next) marks.push([Math.min(Math.max(q.advice, q.next), q.cap), 'your limit', 'var(--blue)', 'dash lim']);
  return `<div class="ar-pbar" data-max="${mx}"><div class="track"><div class="fill" id="ar-fill"></div></div>
    ${marks.map(([l, t, c, cl]) => `<div class="mk ${cl}" style="left:${pos(l)};--mc:${c}" title="${t} ${cr(l)}"></div>`).join('')}
    <div class="ends"><span>₹0</span><span>${cr(mx)}</span></div></div>
    <div class="ar-legend">${marks.map(([l, t, c, cl]) => `<span class="${cl}" style="--mc:${c}"><i></i>${t} <b>${cr(l)}</b></span>`).join('')}</div>`;
}

function controlsHTML(q, st) {
  const adv = q.advice;
  if (q.kind === 'watch') return `<div class="ar-q muted">The bidding goes on without you…</div>`;
  if (q.kind === 'bid') {
    if (q.next > q.cap) return `<div class="ar-ctl"><button class="btn go" disabled>Bid ${cr(q.next)}</button><button class="btn sec" data-a="pass">Pass<kbd>P</kbd></button></div>
      <div class="ar-hint">You can't afford the next bid and still fill your squad (up to ${cr(q.cap)}).</div>`;
    const lim = Math.min(Math.max(adv, q.next), q.cap);
    const chips = [[adv, "computer's value"], [q.player.est, 'expected'], [q.cap, 'most you can']]
      .filter(([v]) => v >= q.next && v <= q.cap)
      .filter(([v], i, a) => a.findIndex(([w]) => w === v) === i);
    return `<div class="ar-ctl"><button class="btn go" data-a="bid">Bid ${cr(q.next)}<kbd>B</kbd></button><button class="btn sec" data-a="pass">Pass<kbd>P</kbd></button></div>
      <div class="ar-limit"><div class="row"><span class="small muted">or bid for me up to</span><b id="ar-lim-v">${cr(lim)}</b>
        <input type="range" id="ar-lim" min="${q.next}" max="${q.cap}" step="1" value="${lim}"
          title="Up to ${cr(q.cap)}: the most you can spend on him and still fill your squad">
        <button class="btn sec" data-a="max">Auto-bid<kbd>L</kbd></button></div>
        <div class="ar-chips">${chips.map(([v, t]) => `<button class="ar-chip" data-l="${v}">${t} ${cr(v)}</button>`).join('')}</div></div>`;
  }
  if (q.kind === 'rtm_use') return `<div class="ar-q">Sold to ${tc(q.buyer)} for <b>${cr(q.price)}</b>. Use a Right to Match card (${q.cards} left)?
      ${esc(q.buyer)} then gets one final raise, and you can match that too.</div>
    <div class="ar-ctl"><button class="btn go" data-a="yes">Use RTM<kbd>B</kbd></button><button class="btn sec" data-a="no">Let him go<kbd>P</kbd></button></div>
    <div class="ar-hint">The computer would ${adv >= q.price ? 'use it' : 'let him go'}: he is worth ${cr(adv)} to you.</div>`;
  if (q.kind === 'rtm_raise') return `<div class="ar-q">${tc(q.holder)} used Right to Match at ${cr(q.price)}. Your one final raise (they can match it):</div>
    <div class="ar-ctl"><span class="au-max">₹<input type="number" id="au-raise" step="0.05" min="${q.price / 100}" max="${q.cap / 100}" value="${(Math.min(Math.max(adv, q.price), q.cap) / 100).toFixed(2)}"> cr
      <button class="btn go" data-a="raise">Raise</button></span><button class="btn sec" data-a="keep">No raise (${cr(q.price)})</button></div>
    <div class="ar-hint">He is worth ${cr(adv)} to you; you can go up to ${cr(q.cap)}.</div>`;
  return `<div class="ar-q">${tc(q.buyer)} raised to <b>${cr(q.price)}</b>. Match it?</div>
    <div class="ar-ctl"><button class="btn go" data-a="yes">Match ${cr(q.price)}<kbd>B</kbd></button><button class="btn sec" data-a="no">Let him go<kbd>P</kbd></button></div>
    <div class="ar-hint">The computer would ${adv >= q.price ? 'match' : 'let him go'}: he is worth ${cr(adv)} to you.</div>`;
}

function wireStage(q) {
  const lim = $('ar-lim');
  const setLim = v => {
    lim.value = v; $('ar-lim-v').textContent = cr(+v);
    const mk = document.querySelector('#au-q .mk.lim'), mx = +document.querySelector('#au-q .ar-pbar').dataset.max;
    if (mk) mk.style.left = `${Math.min(100, 100 * v / mx)}%`;
    const lg = document.querySelector('#au-q .ar-legend .lim b');
    if (lg) lg.textContent = cr(+v);
    document.querySelectorAll('#au-q .ar-chip[data-l]').forEach(c => c.classList.toggle('on', +c.dataset.l === +v));
  };
  if (lim) { lim.oninput = () => setLim(lim.value); setLim(lim.value); }
  document.querySelectorAll('#au-q .ar-chip[data-l]').forEach(c => c.onclick = () => setLim(c.dataset.l));
  $('ar-sp').onchange = e => { setReplaySpeed(e.target.value); if (!SPEED[e.target.value]) skipReplay(); };
  $('ar-skip').onclick = skipReplay;
}

/* the bidding replay: one bid at a time from the lot's log, the teams strip lighting up who is still in */
function setBusy(on) {
  RP.busy = on;
  document.querySelectorAll('#au-q .ar-ctl button, #au-q .ar-limit button, #au-q .ar-limit input').forEach(b => {
    if (on) { b.dataset.was = b.disabled ? '1' : ''; b.disabled = true; } else if (b.dataset.was !== undefined) { b.disabled = b.dataset.was === '1'; delete b.dataset.was; }
  });
  if ($('ar-skip')) $('ar-skip').style.visibility = on ? 'visible' : 'hidden';
  $('au-turn').textContent = on ? 'Bidding…' : 'Your call!';
  $('au-turn').className = 'turn' + (on ? '' : ' you');
}
function showBid(i) {
  const log = RP.view.log, b = log[i];
  const mx = +document.querySelector('#au-q .ar-pbar').dataset.max;
  $('ar-now').textContent = cr(b.price);
  $('ar-by').innerHTML = `${tc(b.team)}<span class="muted">${esc(b.team)}${b.team === AU.user ? ' (you)' : ''}${b.rtm ? ' · Right to Match' : b.raise ? ' · final raise' : ''}</span>`;
  $('ar-fill').style.width = `${Math.min(100, 100 * b.price / mx)}%`;
  $('ar-fill').style.background = col(b.team).hi;
  const shown = log.slice(Math.max(0, i - 15), i + 1);
  $('ar-log').innerHTML = shown.map((x, j) => tc(x.team, 'sm' + (x.team === AU.user ? ' me' : '') + (j === shown.length - 1 ? ' new' : ''))
    .replace('</span>', ` ${cr(x.price)}</span>`)).join('');
  if (b.in) {
    drawStrip({in: new Set(b.in), lead: b.team});
    $('ar-call').className = 'ar-call'; $('ar-call').textContent = `${b.in.length} team${b.in.length === 1 ? '' : 's'} still in`;
  }
}
function replay(from, done = finishReplay) {
  const log = RP.view.log, sp = SPEED[replaySpeed()];
  if (!log.length || !sp || from >= log.length) return done();
  let i = Math.max(from, log.length - 40);
  setBusy(true);
  const tick = () => {
    showBid(i); RP.shown = ++i;
    RP.timer = setTimeout(i < log.length ? tick : done, sp);
  };
  tick();
}
function skipReplay() {               // straight to the question, whatever was playing
  clearTimeout(RP.timer);
  const q = AU.question;
  if (!q || !LOT_KINDS.includes(q.kind)) return;
  if (RP.view !== AU.lot) showLot(AU, q, AU.lot);
  else if ($('ar-sold')) $('ar-sold').classList.remove('on');
  finishReplay();
}
function finishReplay() {
  clearTimeout(RP.timer);
  const st = AU, q = st.question, log = st.lot ? st.lot.log : [];
  if (!q || !LOT_KINDS.includes(q.kind)) return;
  RP.view = st.lot; RP.lot = st.lot.id;
  RP.shown = log.length;
  if (log.length) showBid(log.length - 1); else drawStrip();
  setBusy(false);
  const c = $('ar-call');
  c.className = 'ar-call hot';
  c.textContent = q.kind === 'bid' ? (q.price ? `Your call: bid ${cr(q.next)} or pass` : `Opening at the base price: bid ${cr(q.next)} or pass`)
    : q.kind === 'rtm_use' ? 'Your former player: Right to Match?' : q.kind === 'rtm_raise' ? 'Right to Match used against you' : 'Final raise: match it?';
}
function hammer(x, then) {    // going once, twice, SOLD (or UNSOLD) for the lot before this one
  const box = $('ar-sold'), sold = x.status === 'sold', c = sold ? col(x.buyer).hi : 'var(--muted)';
  setBusy(true);
  box.style.setProperty('--c', c);
  box.innerHTML = `<div class="w">${sold ? 'SOLD' : 'UNSOLD'}</div><div class="t">${esc(x.name)}${sold ? ` to ${tc(x.buyer)} ${esc(x.buyer)} for <b>${cr(x.price)}</b>` : ''}</div>`;
  box.classList.add('on');
  const close = () => { box.classList.remove('on'); box.onclick = null; then(); };
  box.onclick = () => { clearTimeout(RP.timer); close(); };
  RP.timer = setTimeout(close, replaySpeed() === 'slow' ? 1800 : 1100);
}

function doneHTML(st) {
  const me = st.user;
  return `<h3>Auction complete</h3><p class="muted small" style="margin:6px 0">${st.n_sold} players bought for ${cr(st.spent)}.
    ${me ? `Your squad: ${st.board[me].length} players, ${cr(st.purse[me])} left.` : ''} ${st.news.map(esc).join(' ')}
    ${st.career ? 'Save the squads to go back to the career and play the season.'
      : `Press “Play the league” for the season${me && $('a-captain').checked ? `, with you as captain of ${esc(me)}` : ''}.`}</p>
    <p class="muted small">The report card is below.</p>`;
}

/* ───────────── report card ───────────── */
function drawReport() {
  const st = AU, r = st.report, box = $('au-report');
  box.style.display = r ? '' : 'none';
  if (!r) return;
  const me = st.user, pred = r.scale !== null, p5 = pred ? Math.round(100 / (1 + Math.exp(-5 / r.scale))) : null;
  const deal = d => d ? `${esc(d.name)} ${cr(d.price)} <span class="${d.diff >= 0 ? 'w' : 'l'}">${d.diff >= 0 ? '−' : '+'}${cr(Math.abs(d.diff))}</span>` : '–';
  const sgn = v => `${v >= 0 ? '+' : ''}${fmtNum(v, 1)}`;
  const card = (t, place) => `<div class="ar-rcard ${t.team === me ? 'me' : ''} ${place ? 'p' + place : ''}" style="--c:${col(t.team).hi}">
    <div class="hd">${place ? `<span class="pl">${place}</span>` : ''}${tc(t.team)}<b>${esc(t.team)}${t.team === me ? ' (you)' : ''}</b></div>
    <div class="nums"><div><b>${fmtNum(t.strength, 1)} <span class="${t.vs_avg >= 0 ? 'w' : 'l'}">${sgn(t.vs_avg)}</span></b>strength</div>
      ${pred ? `<div><b>${fmtNum(t.wins, 1)}</b>of ${t.games} wins</div><div><b>${t.top}%</b>top ${r.top_n}</div><div><b>${t.first}%</b>top</div>`
        : `<div><b>#${t.rank}</b>by strength</div>`}</div>
    <div class="ln">Spent ${cr(t.spent)}${t.retained ? ` (${cr(t.retained)} kept)` : ''} · ${cr(t.purse)} left · ${t.players} players, ${t.overseas} overseas</div>
    <div class="ln">Best buy: ${deal(t.best)}</div><div class="ln">Dearest: ${deal(t.dear)}</div></div>`;
  const top = r.teams.slice(0, 3), mine = me && !top.some(t => t.team === me) ? r.teams.find(t => t.team === me) : null;
  const list = (xs, t) => `<div class="cap-panel"><h3>${t}</h3><div class="au-feed">${xs.map(d =>
    `<div class="ar-sale ${d.team === me && me ? 'me' : ''}" style="--c:${col(d.team).hi}">${tc(d.team)}<div><div class="nm">${esc(d.name)}</div>
      <div class="rl">${esc(d.role)} · expected ${cr(d.est)}</div></div><div class="pr">${cr(d.price)} <span class="${d.diff >= 0 ? 'w' : 'l'} small">${d.diff >= 0 ? '−' : '+'}${cr(Math.abs(d.diff))}</span></div></div>`).join('')}</div></div>`;
  box.innerHTML = `<div class="cap-panel"><h3>Report card</h3>
    <p class="muted small" style="margin:2px 0 10px">Strength = the best XI's worth in runs a match, as the auction values players (open places at replacement level).
    ${pred ? `Predicted table: a double round robin played many times over, each match's win chance from the strength gap (fitted on simulated matches: a side 5 runs a match stronger wins ${p5}%).`
      : 'No predicted table: in simulated matches this strength measure did not clearly predict results.'}
    Best buy / dearest: price against what the auction expected him to fetch.</p>
    <div class="ar-podium">${top.map((t, i) => card(t, i + 1)).join('')}${mine ? card(mine, 0) : ''}</div>
    <div class="ar-scroll"><table class="mini" style="margin-top:12px"><tr><th>Team</th><th>Strength</th><th>Rank</th>${pred ? `<th>Wins (of ${r.teams[0].games})</th><th>Top ${r.top_n}</th><th>Top</th>` : ''}
      <th>Spent</th><th>Left</th><th>Players</th></tr>
    ${r.teams.map(t => `<tr class="${t.team === me && me ? 'crease' : ''}"><td>${tc(t.team)} ${esc(t.team)}${t.team === me ? ' (you)' : ''}</td>
      <td>${fmtNum(t.strength, 1)} <span class="muted small">${sgn(t.vs_avg)}</span></td><td>${t.rank}</td>
      ${pred ? `<td>${fmtNum(t.wins, 1)}</td><td>${t.top}%</td><td>${t.first}%</td>` : ''}<td>${cr(t.spent)}</td><td>${cr(t.purse)}</td>
      <td>${t.players} <span class="muted small">${t.overseas} OS</span></td></tr>`).join('')}</table></div></div>
    <div class="xi-cols">${list(r.bargains, 'Bargains')}${list(r.dearest, 'Dearest against expected')}</div>`;
}

/* keys: B bid (or yes), P pass (or no), L auto-bid to the limit, S skip the replay */
document.addEventListener('keydown', e => {
  if (!$('v-auction').classList.contains('on') || /INPUT|SELECT|TEXTAREA/.test(e.target.tagName) || e.ctrlKey || e.metaKey || e.altKey) return;
  const k = e.key.toLowerCase(), click = a => { const b = document.querySelector(`#au-q [data-a="${a}"]`); if (b && !b.disabled) { b.click(); return true; } };
  if (k === 's' && RP.busy) { skipReplay(); return; }
  if (RP.busy) return;
  if (k === 'b') click('bid') || click('yes');
  else if (k === 'p') click('pass') || click('no');
  else if (k === 'l') click('max');
});
