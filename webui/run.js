'use strict';
/* Saved runs, starting a run and following its progress. */

/* ───────────────────────── saved runs ───────────────────────── */
async function saveRun() {
  const name = prompt('Name this run', R.title || 'My run');
  if (!name) return;
  try {
    META.saved = (await api('/api/saved', {name})).saved;
    const sv = META.saved.find(s => s.name === name.trim()) || META.saved[0];
    $('r-save').style.display = 'none'; $('r-saved').textContent = `Saved as “${sv.name}”`;
    toast('Saved. Find it under “Saved”.'); aRefresh();
  } catch (e) { toast(e.message, true); }
}
function drawSaved() {
  const list = META.saved || [];
  $('sv-list').innerHTML = list.length ? list.map(s => `<div class="sv-item" data-id="${esc(s.id)}">
      <b>${esc(s.name)}</b>
      <span class="muted small">${esc(s.title || '')}${s.winner ? ' · winner: ' + esc(s.winner) : ''} · saved ${esc(s.saved)}</span>
      <div class="sv-btns"><button class="btn sec" data-a="open">Open</button><button class="btn sec" data-a="rename">Rename</button>
      <button class="btn sec" data-a="delete">Delete</button></div></div>`).join('')
    : '<div class="muted small">Nothing saved yet. Open a run\'s results and press “Save this run”.</div>';
  $('sv-list').querySelectorAll('.sv-item').forEach(el => {
    const id = el.dataset.id, s = list.find(x => x.id === id);
    el.querySelector('[data-a="open"]').onclick = () => showResults(id);
    el.querySelector('[data-a="rename"]').onclick = async () => {
      const name = prompt('New name', s.name);
      if (name) { META.saved = (await api('/api/saved/rename', {id, name})).saved; drawSaved(); aRefresh(); }
    };
    el.querySelector('[data-a="delete"]').onclick = async () => {
      if (!confirm(`Delete the saved run “${s.name}”? This cannot be undone.`)) return;
      META.saved = (await api('/api/saved/delete', {id})).saved; drawSaved(); aRefresh();
      if (R_RUN === id) showView('v-home');
    };
  });
}

/* ───────────────────────── start / poll ───────────────────────── */
function payload() {
  const base = {mode: MODE, fmt: $('c-fmt').value, comp: $('c-comp').value, year: +$('c-year').value,
    venues: [...$('c-venues').selectedOptions].map(o => o.value), seed: $('c-seed').value.trim(),
    rain: $('c-rain').checked};
  if (MODE === 'series') return {...base, team1: $('s-t1').value, team2: $('s-t2').value, matches: +$('s-n').value, host: $('s-host').value};
  if (MODE === 'wtc') return {...base, fmt: 'test', teams: wtcTeams(), tests: +$('w-n').value, rain: false};
  if (MODE === 'league') return {mode: 'league', league: $('l-league').value, season: $('l-season').value, seed: $('l-seed').value.trim(), venues: [],
    rain: $('l-rain').checked, captain: $('l-captain').value, opponents: $('l-opp').value,
    manual: [...$('l-manual').querySelectorAll('input:checked')].map(i => i.value).filter(k => k !== 'impact' || CAP.impact)};
  if (MODE === 'domestic') return {mode: 'domestic', cup: 'sma', season: $('dm-season').value, seed: $('dm-seed').value.trim(),
    venues: [], rain: $('dm-rain').checked, captain: $('dm-captain').value, opponents: $('dm-opp').value,
    manual: [...$('dm-manual').querySelectorAll('input:checked')].map(i => i.value)};
  if (MODE === 'classic') return {...base, mode: 'series', team1: $('cs-r1').firstChild.entry(),
    team2: $('cs-r2').firstChild.entry(), matches: +$('cs-n').value, host: $('cs-host').value, squad_size: document.querySelector('.c-squad').value,
    years_mode: document.querySelector('.c-ymode').value};
  if (MODE === 'classic_t') return {...base, mode: 'tournament', squad_size: document.querySelector('.c-squad').value,
    years_mode: document.querySelector('.c-ymode').value,
    teams: [...$('ct-rows').children].map(r => r.entry()),
    rounds: +$('ct-rounds').value, groups: +$('ct-groups').value, knockout: $('ct-ko').value};
  return {...base, teams: [...document.querySelectorAll('#t-list input:checked')].map(i => i.value),
    rounds: +$('t-rounds').value, groups: +$('t-groups').value, knockout: $('t-ko').value};
}
/* captain a side in Series / Tournament / Classic / Draft (League Season and Auction have their own picker) */
const histName = e => e.y1 === e.y2 ? `${e.nation} ${e.y1}` : `${e.nation} ${e.y1}-${String(e.y1).slice(0, 2) === String(e.y2).slice(0, 2) ? String(e.y2).slice(-2) : e.y2}`;
function capSides() {
  if (MODE === 'series') return [$('s-t1').value, $('s-t2').value];
  if (MODE === 'tournament') return [...document.querySelectorAll('#t-list input:checked')].map(i => i.value);
  if (MODE === 'wtc') return wtcTeams();
  if (MODE === 'classic') return [$('cs-r1').firstChild, $('cs-r2').firstChild].map(r => r ? histName(r.entry()) : '');
  if (MODE === 'classic_t') return [...$('ct-rows').children].map(r => histName(r.entry()));
  if (MODE === 'draft') return DRAFT && DRAFT.done && DRAFT.user ? [DRAFT.user] : [];
  return [];
}
function capOptions() {
  const sides = capSides();
  const show = ['series', 'tournament', 'wtc', 'classic', 'classic_t', 'draft'].includes(MODE) && sides.length > 0;   // a draft: once it is done
  $('g-cap-box').style.display = show ? '' : 'none';
  if (!show) { $('g-manual-box').style.display = 'none'; return; }
  const sel = $('g-captain'), keep = sel.selectedIndex > 0 ? sel.options[sel.selectedIndex].text : '';
  fillSelect(sel, [{v: '', t: MODE === 'draft' ? 'None - the computer captains every team' : 'None - the computer plays everything'},
    ...sides.map((t, i) => ({v: String(i), t: MODE === 'draft' ? `${t} (your drafted team)` : t}))]);
  const k = [...sel.options].findIndex(o => o.text === keep);
  if (k > 0) sel.selectedIndex = k;
  capBoxes();
}
function capBoxes() {
  $('g-manual-box').style.display = $('g-captain').value ? '' : 'none';
  CAP.impact = $('c-comp').value === 'ipl' && +$('c-year').value >= 2023;
  $('g-impact-opt').style.display = CAP.impact ? '' : 'none';
}
function capPayload() {
  const i = $('g-captain').value;
  return i === '' ? {} : {captain_i: MODE === 'draft' ? DRAFT.teams.indexOf(DRAFT.user) : +i, opponents: $('g-opp').value,
    manual: [...$('g-manual').querySelectorAll('input:checked')].map(x => x.value).filter(k => k !== 'impact' || CAP.impact)
      .filter(k => $('c-fmt').value === 'test' || !TEST_ONLY_KINDS.includes(k))};
}
async function start() {
  $('go-err').textContent = ''; $('go-btn').disabled = true; LIVE_AWAY = false;
  try {
    if (MODE === 'draft') { await startDraft(); return; }
    if (MODE === 'auction') { await startAuction(); return; }
    if (MODE === 'career') { await startCareer(); return; }
    if (MODE === 'mp') { await mpCreate(); $('go-btn').disabled = false; return; }
    await api('/api/run', {...payload(), ...capPayload()}); poll();
  }
  catch (e) { $('go-err').textContent = e.message; $('go-btn').disabled = false; }
}
/* a run that stopped: what went wrong in a sentence; the traceback is folded away under Technical details */
function showError(st) {
  $('e-text').textContent = st.error || 'The run stopped, and the simulator did not say why.';
  $('e-detail').textContent = st.detail || '';
  $('e-more').style.display = st.detail ? '' : 'none'; $('e-more').open = false;
  showView('v-error');
}
let POLL_T = null;
async function poll() {
  if (mpOn()) return mpPoll();
  clearTimeout(POLL_T);
  let st;
  try { st = await api('/api/status'); } catch (e) { POLL_T = setTimeout(poll, 1500); return; }
  const running = st.status === 'running';
  livePill(running, st);
  if (PRE.on && running && st.captain) { preRender(st); POLL_T = setTimeout(poll, 250); return; }
  PRE.on = false;
  $('go-btn').disabled = running;
  if (running && st.captain && st.captain.skip !== 'all') {
    if (!LIVE_AWAY) { showView('v-captain'); capRender(st); }
    POLL_T = setTimeout(poll, LIVE_AWAY ? 1500 : st.captain.pending ? 700 : 200);
  } else if (running) {
    showView('v-running');
    $('run-title').textContent = st.title || 'Simulating…';
    $('run-bar').style.width = (st.total ? Math.round(100 * st.done / st.total) : 0) + '%';
    $('run-count').textContent = `${st.done} of ${st.total} ${/Test/.test(st.title || '') ? 'Tests' : 'matches'} · ${fmtTime(st.elapsed)} elapsed`;
    POLL_T = setTimeout(poll, 500);
  } else if (st.status === 'done') { $('last-btn').style.display = ''; showResults(); }
  else if (st.status === 'error') showError(st);
  else if (st.status === 'stopped') { toast('Simulation stopped.'); goHome(); }
}
async function stopJob() { await api('/api/stop', {}); setTimeout(poll, 300); }
