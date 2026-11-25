'use strict';
/* The set-up forms: conditions, teams, tournament, Classic, League Season, domestic seasons. */

function setMode(m, show = true) {
  MODE = m;
  document.querySelectorAll('.form').forEach(f => f.classList.toggle('on', f.id === 'f-' + m));
  const b = m === 'builder' || m === 'saved';
  if (m === 'saved') drawSaved();
  if (m === 'career') drawCareers();
  $('go-wrap').style.display = b ? 'none' : ''; $('cond').style.display = b || m === 'league' || m === 'domestic' || m === 'career' ? 'none' : '';
  $('mp-clock-box').style.display = m === 'mp' ? '' : 'none';
  // a Test's length: a series and the WTC choose it in their own form, a two-player room in the room
  $('g-test-box').style.display = ['tournament', 'classic_t', 'draft', 'auction'].includes(m) ? '' : 'none';
  if (m === 'mp') mpPane('');
  if (m === 'auction') aRefresh();
  testModeGuard();
  if (m === 'wtc' && $('c-fmt').value !== 'test') { $('c-fmt').value = 'test'; $('c-fmt').dispatchEvent(new Event('change')); }
  capHome();
  capOptions();
  autoConds();
  $('go-err').textContent = '';
  const M = MODES[m] || {t: m, s: ''};
  $('su-title').textContent = M.t; $('su-blurb').textContent = M.s; $('su-ic').outerHTML = modeIcon(m, 'big').replace('class="mic', 'id="su-ic" class="mic');
  $('su-sum-t').textContent = M.t; syncSum();
  $('go-btn').innerHTML = {mp: '&#9654;&nbsp; Open a room', draft: '&#9654;&nbsp; Start the draft', auction: '&#9654;&nbsp; Start the auction',
    career: '&#9654;&nbsp; Start the career', league: '&#9654;&nbsp; Start the season',
    domestic: '&#9654;&nbsp; Start the season'}[m] || '&#9654;&nbsp; Start';
  if (!show) return;
  if (m === 'builder') { showView('v-builder'); loadBuilderPool(); }
  else showView('v-setup');
}
/* the captain boxes live in the conditions panel; the draft room borrows them once the draft is done */
function capHome() {
  const a = $('cap-anchor'), m = $('cap-more-anchor');
  if (a && $('g-cap-box').previousElementSibling !== a) a.after($('g-cap-box'));
  if (m && $('g-manual-box').previousElementSibling !== m) m.after($('g-manual-box'));
}

/* conditions: format, competition, year, venues */
function fillConditions() {
  const f = META.formats[$('c-fmt').value];
  fillSelect($('c-comp'), f.competitions.map(c => ({v: c.id, t: `${c.label} (${c.first}–${c.last})`})), true);
  $('c-venues').innerHTML = f.venues.map(v => `<option value="${esc(v.name)}" data-k="${esc(v.name.toLowerCase())}">${esc(v.name)} (${v.matches} games${v.runs >= 1.03 ? ', high-scoring' : v.runs <= 0.97 ? ', low-scoring' : ''})</option>`).join('');
  drawVenues(); checkYear(); condLine();
}
/* the venues: a searchable tick list in front of the hidden <select multiple> (phones can't Ctrl+click); ticked
   grounds first */
function drawVenues() {
  const vs = META.formats[$('c-fmt').value].venues, opts = [...$('c-venues').options];
  const order = vs.map((v, i) => i).sort((a, b) => (opts[b].selected ? 1 : 0) - (opts[a].selected ? 1 : 0));
  $('c-vlist').innerHTML = order.map(i => { const v = vs[i];
    return `<label data-k="${esc(v.name.toLowerCase())}"><input type="checkbox" data-i="${i}" ${opts[i].selected ? 'checked' : ''}> <span>${esc(v.name)}
      <span class="muted small full-only">(${v.matches} games${v.runs >= 1.03 ? ', high-scoring' : v.runs <= 0.97 ? ', low-scoring' : ''})</span></span></label>`; }).join('');
  $('c-vlist').querySelectorAll('input').forEach(c => c.onchange = () => { opts[+c.dataset.i].selected = c.checked; venueCount(); });
  filterVenues(); venueCount();
}
function venueCount() { const n = $('c-venues').selectedOptions.length; $('c-vcount').textContent = n ? `· ${n} ticked` : ''; }
function filterVenues() {
  const q = $('c-vsearch').value.toLowerCase();
  [...$('c-venues').options].forEach(o => o.style.display = o.dataset.k.includes(q) ? '' : 'none');
  $('c-vlist').querySelectorAll('label').forEach(l => l.style.display = l.dataset.k.includes(q) ? '' : 'none');
}
/* era & grounds (and the format) follow the teams chosen until you change them yourself under More options */
const COND = {user: false, fmt: false, auto: false};
const teamFmt = n => / Test \d{4}$/.test(n) ? 'test' : / ODI \d{4}$/.test(n) ? 'odi' : / T20 \d{4}$/.test(n) || isFranchise(n) ? 't20' : null;
function condTeams() {
  if (MODE === 'series') return [$('s-t1').value, $('s-t2').value];
  if (MODE === 'tournament') return [...document.querySelectorAll('#t-list input:checked')].map(i => i.value);
  if (MODE === 'wtc') return wtcTeams();
  return [];
}
function condYears() {
  const rows = MODE === 'classic' ? [$('cs-r1').firstChild, $('cs-r2').firstChild] : MODE === 'classic_t' ? [...$('ct-rows').children] : [];
  if (rows.length) return rows.filter(r => r && r.entry).map(r => r.entry().y2);
  if (MODE === 'draft') return [+$('d-yb').value];
  if (MODE === 'auction' && $('a-pool').value === 'years') return [+$('a-yb').value];
  return [];
}
function autoConds() {
  if (META && MODE === 'mp') {                        // a room: T20, international, the latest year, unless you chose
    if (!COND.fmt && $('c-fmt').value !== 't20') { $('c-fmt').value = 't20'; $('c-fmt').dispatchEvent(new Event('change')); return; }
    const c = META.formats[$('c-fmt').value].competitions, i = c.find(x => /_full$/.test(x.id)) || c[0];
    if (!COND.user) { $('c-comp').value = i.id; $('c-year').value = i.last; checkYear(); }
    COND.auto = false; condLine(); return;
  }
  if (!META || !['series', 'tournament', 'wtc', 'classic', 'classic_t', 'draft', 'auction'].includes(MODE)) { COND.auto = false; condLine(); return; }
  const tt = condTeams(), fmts = MODE === 'wtc' ? [] : [...new Set(tt.map(teamFmt).filter(Boolean))];
  if (!COND.fmt && fmts.length === 1 && fmts[0] !== $('c-fmt').value && (fmts[0] !== 'test' || TEST_MODES.includes(MODE))) { $('c-fmt').value = fmts[0]; $('c-fmt').dispatchEvent(new Event('change')); return; }
  if (COND.user) { COND.auto = false; condLine(); return; }
  const fmt = $('c-fmt').value, comps = META.formats[fmt].competitions;
  let cond = null;
  if (tt.length) cond = quickConds(tt.length > 1 ? tt : [tt[0], tt[0]], fmt);
  else {
    const ys = condYears().filter(Boolean), id = {odi: 'odi_full', test: 'test_full'}[fmt] || 't20i_full';
    const c = comps.find(x => x.id === id) || comps[0];
    if (ys.length) cond = {comp: c.id, year: Math.max(c.first, Math.min(c.last, Math.max(...ys)))};
  }
  COND.auto = !!cond;
  if (cond) { $('c-comp').value = cond.comp; $('c-year').value = cond.year; checkYear(); }
  condLine();
}
function condLine() {
  const fmt = $('c-fmt').value;
  $('c-auto').textContent = `· ${+$('c-year').value || ''} ${compName(fmt, $('c-comp').value)}${COND.auto ? ', from the teams' : ''}`;
}
/* number chips (Matches: 1 3 5 7) in front of a hidden number input */
function numChips(inp) {
  const box = document.createElement('div');
  box.className = 'picker chips'; inp.after(box); inp.classList.add('picked');
  const draw = () => { const vals = inp.dataset.chips.split(','); box.innerHTML = vals.map(v => `<button type="button" class="${String(+inp.value) === v ? 'on' : ''}" data-v="${v}">${v}</button>`).join(''); };
  box.onclick = e => { const b = e.target.closest('button'); if (!b) return; inp.value = b.dataset.v; inp.dispatchEvent(new Event('change')); inp.dispatchEvent(new Event('input')); draw(); };
  inp.addEventListener('change', draw); draw();
}
/* tournament formats as named presets; the rounds / groups / knockouts selects stay under More options */
const TPRESETS = [['League + semi-finals', '1', '1', 'semis'], ['League + final', '1', '1', 'final'], ['Two groups + semi-finals', '1', '2', 'semis']];
function presetChips(box, pre) {
  const ids = ['-rounds', '-groups', '-ko'].map(x => pre + x);
  const draw = () => {
    box.innerHTML = TPRESETS.map(([t, ...v], i) => `<button type="button" data-i="${i}" class="${ids.every((id, k) => $(id).value === v[k]) ? 'on' : ''}">${t}</button>`).join('');
  };
  box.onclick = e => {
    const b = e.target.closest('button'); if (!b) return;
    const v = TPRESETS[+b.dataset.i].slice(1);
    ids.forEach((id, k) => { $(id).value = v[k]; });
    $(ids[2]).dispatchEvent(new Event('change'));
  };
  ids.forEach(id => $(id).addEventListener('change', draw)); draw();
}
function checkYear() {
  const f = META.formats[$('c-fmt').value], c = f.competitions.find(c => c.id === $('c-comp').value), y = +$('c-year').value;
  $('c-year-err').textContent = c && (y < c.first || y > c.last) ? `${c.label} data covers ${c.first}–${c.last}; the nearest year's conditions will be used.` : '';
}

/* teams (series + tournament) */
/* the saved teams that can play a format: its nations' presets, the franchises and your own teams (a player with
   no record in the format is rated from another he played; the server says so if a side still cannot play it) */
function teamsFor(fmt) {
  const names = META.teams.map(t => t.name).filter(n => !isNationPreset(n) || teamFmt(n) === fmt);
  return names.length ? names : META.teams.map(t => t.name);
}
/* the two teams of a match: the lists hold the format's sides; a side that is not one of them is replaced by the
   same nation's ("India T20 2024" -> "India Test 2025"), else by India / Australia, else by the first two */
const TEAM_FIRST = ['India', 'Australia'];
function fillTeams() {
  const fmt = $('c-fmt').value, names = teamsFor(fmt), all = META.teams.map(t => t.name);
  const was = [$('s-t1').value, $('s-t2').value];
  const opts = names.map(n => ({v: n, t: pickName(n, all)}));
  fillSelect($('s-t1'), opts, true); fillSelect($('s-t2'), opts, true);
  if (!$('s-t1')._init) {
    $('s-t1')._init = true;
    ['s-t1', 's-t2'].forEach((id, i) => $(id).onchange = () => showRoster(id, 's-r' + (i + 1)));
  }
  const pre = n => isNationPreset(n) && teamFmt(n) === fmt, taken = [];
  was.forEach((n, i) => {
    let pick = names.includes(n) ? n : null;
    if (!pick && n) pick = names.find(x => pre(x) && teamKey(x) === teamKey(n) && !taken.includes(x));
    if (!pick) pick = names.find(x => pre(x) && teamKey(x) === TEAM_FIRST[i] && !taken.includes(x))
      || names.find(x => !taken.includes(x)) || names[0];
    taken.push(pick); $('s-t' + (i + 1)).value = pick;
  });
  showRoster('s-t1', 's-r1'); showRoster('s-t2', 's-r2');
  // a tournament: a ticked nation's side of another format becomes its side for this one (or is unticked)
  const checked = new Set([...document.querySelectorAll('#t-list input:checked')].map(i => i.value)
    .map(n => !isNationPreset(n) || !teamFmt(n) || teamFmt(n) === fmt ? n : names.find(x => pre(x) && teamKey(x) === teamKey(n))).filter(Boolean));
  const first = !$('t-list').children.length;
  $('t-list').innerHTML = META.teams.map(t =>
    `<label data-name="${esc(t.name.toLowerCase())}"><input type="checkbox" value="${esc(t.name)}" ${checked.has(t.name) || (first && / T20 2024$/.test(t.name)) ? 'checked' : ''}> ${esc(pickName(t.name, names))} <span class="muted small full-only">(${t.players.length})</span></label>`).join('');
  $('t-list').querySelectorAll('input').forEach(i => i.onchange = () => { updateTournamentTotal(); autoConds(); capOptions(); });
  // the World Test Championship: the sides that can play a Test, the nations' Test sides ticked
  const wAll = teamsFor('test'), wOn = new Set(wtcTeams()), wFirst = !$('w-list').children.length;
  $('w-list').innerHTML = wAll.map(n =>
    `<label><input type="checkbox" value="${esc(n)}" ${wOn.has(n) || (wFirst && teamFmt(n) === 'test') ? 'checked' : ''}> ${esc(pickName(n, wAll))}</label>`).join('');
  $('w-list').querySelectorAll('input').forEach(i => i.onchange = () => { updateWtcTotal(); autoConds(); capOptions(); });
  updateTournamentTotal(); updateWtcTotal(); drawSavedTeams();
}
const wtcTeams = () => [...document.querySelectorAll('#w-list input:checked')].map(i => i.value);
/* series each side plays at home (as many away): the usual cycle (3, fewer with under seven sides), 1 to k - 1,
   or every other side home and away */
function drawWtcHome(k) {
  const sel = $('w-home'), keep = sel.value, usual = Math.min(3, Math.floor((k - 1) / 2));
  const opts = [{v: '', t: `${usual} at home, ${usual} away${usual === 3 ? ' (as the real cycle)' : ''}`}];
  for (let i = 1; i < k - 1; i++) if (i !== usual) opts.push({v: String(i), t: `${i} at home, ${i} away`});
  if (k > 2) opts.push({v: 'all', t: `Every other side at home and away (${k - 1} + ${k - 1})`});
  sel.innerHTML = opts.map(o => `<option value="${o.v}">${o.t}</option>`).join('');
  sel.value = opts.some(o => o.v === keep) ? keep : '';
}
function updateWtcTotal() {
  const k = wtcTeams().length, n = +$('w-n').value || 2;
  drawWtcHome(k);
  const h = $('w-home').value, each = h === 'all' ? k - 1 : h ? +h : Math.min(3, Math.floor((k - 1) / 2));
  $('w-total').textContent = k < 3 ? `${k} selected: pick at least 3`
    : `${k} teams · ${2 * each} series each · ${k * each * n + 1} Tests${WTC_LEN[$('w-length').value] || ''}`;
}
const WTC_LEN = {3: ' · three days', 4: ' · four days', 6: ' · six days', timeless: ' · timeless'};
/* a side's squad; players with no record in the format are marked (their ratings are estimated from another) */
function showRoster(selId, outId) {
  const t = META.teams.find(t => t.name === $(selId).value), fmt = $('c-fmt').value;
  if (!t) { $(outId).innerHTML = ''; return; }
  const est = t.players.filter(p => p.est && p.est[fmt]);
  const from = [...new Set(est.map(p => fmtLabel(p.est[fmt])))].join(' or ');
  $(outId).innerHTML = `<div class="rhead">${badge(t.name)}<span class="muted small full-only">${t.players.length} players</span></div>
    ${est.length ? `<div class="muted small est-note">${est.length} ${est.length === 1 ? 'player has' : 'players have'} no ${fmtLabel(fmt)} record: their ${fmtLabel(fmt)} ratings are estimated from ${from} (marked *)</div>` : ''}
    <div class="pchips full-only">${t.players.map(p => p.est && p.est[fmt]
      ? `<span class="est" title="No ${fmtLabel(fmt)} record: rated from ${fmtLabel(p.est[fmt])}">${esc(p.name)} *</span>`
      : `<span>${esc(p.name)}</span>`).join('')}</div>`;
}
function filterTeams() {
  const q = $('t-search').value.toLowerCase();
  $('t-list').querySelectorAll('label').forEach(l => l.style.display = l.dataset.name.includes(q) ? '' : 'none');
}
function matchCount(k, rounds, groups, ko) {
  const sizes = groups > 1 ? [...Array(groups).keys()].map(g => Math.ceil((k - g) / groups)) : [k];
  return rounds * sizes.reduce((a, s) => a + s * (s - 1) / 2, 0) + {semis: 3, qf: 7, ipl: 4, final: 1, none: 0}[ko];
}
function updateTournamentTotal() {
  const k = document.querySelectorAll('#t-list input:checked').length;
  const n = matchCount(k, +$('t-rounds').value, +$('t-groups').value, $('t-ko').value);
  $('t-total').textContent = k < 2 ? `${k} selected: pick at least 2` : `${k} teams · ${n} ${$('c-fmt').value === 'test' ? 'Tests' : 'matches'}`;
}

/* classic (historical) teams: rows of from / to / nation */
const NATIONS = {};
async function nationsFor(y1, y2) {
  const f = $('c-fmt').value, k = `${f}|${y1}|${y2}`;
  if (!NATIONS[k]) NATIONS[k] = await api(`/api/nations?fmt=${f}&y1=${y1}&y2=${y2}`);
  return NATIONS[k];
}
function classicRow(box, a, b, nation, removable) {
  const row = document.createElement('div');
  row.innerHTML = `<div class="hl-row"><input type="number" value="${a}" title="From"><input type="number" value="${b}" title="To"><select></select><button class="x" title="Remove"${removable ? '' : ' style="visibility:hidden"'}>✕</button></div><div class="err"></div>`;
  const [ia, ib] = row.querySelectorAll('input'), sel = row.querySelector('select'), err = row.querySelector('.err');
  let want = nation;
  row.refresh = async () => {
    const ya = +ia.value, yb = +ib.value;
    if (ya > yb) { err.textContent = `Start year ${ya} is after end year ${yb}.`; return; }
    const d = await nationsFor(ya, yb);
    const names = d.nations.map(n => n.name).sort();
    fillSelect(sel, names);
    if (names.includes(want)) sel.value = want;
    err.textContent = ya < d.first || yb > d.last ? `${fmtLabel($('c-fmt').value)} data covers ${d.first}–${d.last}.`
      : names.length ? '' : 'No nation has enough players in these years.';
  };
  ia.onchange = row.refresh; ib.onchange = row.refresh;
  sel.onchange = () => { want = sel.value; };
  row.querySelector('.x').onclick = () => { row.remove(); updateClassicTotal(); };
  row.entry = () => ({nation: sel.value, y1: +ia.value, y2: +ib.value});
  box.appendChild(row); row.refresh();
  return row;
}
function initClassic() {
  classicRow($('cs-r1'), 2021, 2024, 'India', false);
  classicRow($('cs-r2'), 2007, 2012, 'Australia', false);
  [[2012, 2016, 'West Indies'], [2021, 2024, 'India'], [2019, 2022, 'England'], [2007, 2012, 'Australia'],
   [2007, 2010, 'Pakistan'], [2009, 2014, 'Sri Lanka']].forEach(([a, b, n]) => classicRow($('ct-rows'), a, b, n, true));
  $('ct-add').onclick = () => { classicRow($('ct-rows'), 2015, 2019, 'New Zealand', true); updateClassicTotal(); };
  fillSelect($('ct-ko'), META.knockouts.map(k => ({v: k.id, t: k.label})));
  ['ct-rounds', 'ct-groups', 'ct-ko'].forEach(id => $(id).onchange = updateClassicTotal);
  document.querySelectorAll('.c-squad').forEach(sel => {
    fillSelect(sel, [{v: '20', t: 'Most-capped 20 of the period (recommended)'}, {v: '15', t: 'Most-capped 15'},
      {v: '25', t: 'Most-capped 25'}, {v: '', t: 'Everyone who played (one-series players too)'}]);
    sel.onchange = () => document.querySelectorAll('.c-squad').forEach(o => o.value = sel.value);
  });
  document.querySelectorAll('.c-ymode').forEach(sel => sel.onchange = () => document.querySelectorAll('.c-ymode').forEach(o => o.value = sel.value));
  updateClassicTotal();
}
function refreshClassic() { document.querySelectorAll('#f-classic .hl-row, #f-classic_t .hl-row').forEach(r => r.parentNode.refresh()); }
function updateClassicTotal() {
  const k = $('ct-rows').children.length;
  const n = matchCount(k, +$('ct-rounds').value, +$('ct-groups').value, $('ct-ko').value);
  $('ct-total').textContent = k < 2 ? 'Add at least 2 teams' : `${k} teams · ${n} ${$('c-fmt').value === 'test' ? 'Tests' : 'matches'}`;
}

/* ───────────────────────── league season ───────────────────────── */
function initLeague() {
  fillSelect($('l-league'), META.leagues.map(l => ({v: l.id, t: l.label})));
  const league = () => META.leagues.find(x => x.id === $('l-league').value);
  const show = () => {
    const l = league(), s = l && l.seasons.find(x => x.season === $('l-season').value);
    if (!s) { $('l-teams').textContent = 'No league data - run scripts/build_league_presets.py'; return; }
    $('l-teams').innerHTML = s.teams.map(t => `${esc(t.name)} <span class="muted">(${t.n} players, ${t.overseas} overseas)</span>`).join('<br>');
    $('l-total').textContent = `${s.teams.length} teams · ${matchCount(s.teams.length, 2, 1, 'ipl')} matches · ${l.label} ${s.year} conditions · max ${s.max_overseas} overseas per XI`;
    const keep = $('l-captain').value;
    fillSelect($('l-captain'), [{v: '', t: 'None - the computer plays everything'}, ...s.teams.map(t => ({v: t.name, t: t.name}))]);
    if (s.teams.some(t => t.name === keep)) $('l-captain').value = keep;
    CAP.impact = l.id === 'ipl' && s.year >= 2023;
    $('l-impact-opt').style.display = CAP.impact ? '' : 'none';
    $('l-manual-box').style.display = $('l-captain').value ? '' : 'none';
  };
  $('l-captain').onchange = () => { $('l-manual-box').style.display = $('l-captain').value ? '' : 'none'; };
  const seasons = () => { const l = league(); fillSelect($('l-season'), l ? l.seasons.map(s => ({v: s.season, t: s.season})) : []); show(); };
  $('l-league').onchange = seasons; $('l-season').onchange = show; seasons();
}

/* ───────────────────────── domestic cup (Mushtaq Ali Trophy) ───────────────────────── */
const KO_NAME = {super_league: 'Super League, then the final', super_league_semis: 'Super League, semi-finals, final',
  qf: 'quarter-finals, semis, final', pre_qf: 'preliminary quarter-finals, quarter-finals, semis, final'};
function initDomestic() {
  const cup = (META.domestic || [])[0];
  if (!cup) { $('dm-total').textContent = 'No domestic seasons - run scripts/build_domestic_presets.py'; return; }
  fillSelect($('dm-season'), cup.seasons.map(s => ({v: s.season, t: s.squads === 'latest' ? `${s.season} (latest squads)` : s.season})));
  const show = () => {
    const s = cup.seasons.find(x => x.season === $('dm-season').value);
    if (!s) return;
    const plate = s.teams.filter(t => t.plate), elite = s.teams.filter(t => !t.plate);
    $('dm-teams').innerHTML = `${elite.length} Elite sides in ${s.groups.length} groups of ${[...new Set(s.groups)].join(' and ')}`
      + (plate.length ? `; Plate: ${plate.map(t => esc(t.name)).join(', ')}` : '')
      + `<br><span class="muted">Real winner: ${esc(s.real.winner)} (beat ${esc(s.real.runner_up)} in the final)</span>`;
    $('dm-total').textContent = `${s.teams.length} teams · ${s.matches} matches · groups, then ${KO_NAME[s.knockout] || s.knockout}${plate.length ? ' · Plate' : ''}`;
    const keep = $('dm-captain').value;
    const opts = [...s.teams].sort((a, b) => a.name.localeCompare(b.name)).map(t => ({v: t.name, t: t.name + (t.plate ? ' (Plate)' : '')}));
    fillSelect($('dm-captain'), [{v: '', t: 'None - the computer plays everything'}, ...opts]);
    if (s.teams.some(t => t.name === keep)) $('dm-captain').value = keep;
    $('dm-manual-box').style.display = $('dm-captain').value ? '' : 'none';
  };
  $('dm-captain').onchange = () => { $('dm-manual-box').style.display = $('dm-captain').value ? '' : 'none'; };
  $('dm-season').onchange = show; show();
}
