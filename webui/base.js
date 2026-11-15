'use strict';
/* Limited-overs simulator UI. Helpers, sortable tables, popovers and match links are ported from the Test sim's
   webui/app.js; forms and results are rewritten for this engine's results (engine/tournament.py). */

/* ───────────────────────── helpers ───────────────────────── */
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
async function api(path, body) {
  const opt = body === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)};
  const r = await fetch(path, opt);
  let data = null;
  try { data = await r.json(); } catch (e) { data = null; }
  if (!r.ok) throw new Error((data && data.error) || `${r.status} ${r.statusText}`);
  return data;
}
function toast(msg, bad) {
  const t = $('toast'); t.textContent = msg; t.className = 'toast' + (bad ? ' bad' : ''); t.style.display = 'block';
  clearTimeout(t._h); t._h = setTimeout(() => t.style.display = 'none', 4000);
}
function showView(id) {
  const was = document.querySelector('.view.on');
  document.querySelectorAll('.view').forEach(v => v.classList.toggle('on', v.id === id));
  if (id !== 'v-auction') document.body.classList.remove('au-fold');     // the auction room folds the sidebar away
  if (!was || was.id !== id) window.scrollTo(0, 0);
  const nav = {'v-home': 'home', 'v-setup': MODE === 'saved' ? 'saved' : MODE === 'career' ? 'careers' : 'home', 'v-results': 'results',
    'v-builder': 'builder', 'v-career': 'careers', 'v-captain': 'live', 'v-running': 'live', 'v-mp': 'live', 'v-door': 'home', 'v-pre': 'home'}[id] || '';
  document.querySelectorAll('[data-nav]').forEach(b => { if (b.closest('#nav,#tabbar')) b.classList.toggle('on', b.dataset.nav === nav); });
  document.body.dataset.view = id;
  if (id === 'v-home' && META && (!was || was.id !== id)) { drawHero(); drawHomeCont(); }
  if (typeof tipSoon === 'function') tipSoon(id, !was || was.id !== id);     // this screen's first-visit tips (tips.js)
}
const fmtTime = s => { s = Math.round(s); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; };
const fmtNum = (v, d) => v === null || v === undefined || v === '' ? '–' : (typeof v === 'number' && d !== undefined ? v.toFixed(d) : v);
function fillSelect(sel, items, keep) {
  const old = keep ? sel.value : null;
  sel.innerHTML = items.map(i => typeof i === 'string' ? `<option>${esc(i)}</option>` : `<option value="${esc(i.v)}">${esc(i.t)}</option>`).join('');
  if (old !== null && [...sel.options].some(o => o.value === old)) sel.value = old;
}

/* names for people: competitions, preset teams, detail level */
// leagues are added from META.league_info (engine/leagues.py) by setLeagueInfo()
const COMP_NAME = {t20i_full: 'international', t20i: 'international (all teams)', odi_full: 'international', odi: 'international (all teams)', test_full: 'international', test: 'international (all teams)'};
function compName(fmt, id) {
  if (!id) return '';
  if (COMP_NAME[id]) return COMP_NAME[id];
  const c = META && META.formats[fmt] && META.formats[fmt].competitions.find(c => c.id === id);
  return c ? c.label : String(id).replace(/_/g, ' ');
}
/* "India T20 2024" -> "India", unless another team in the list has the same name without its year */
function pickName(name, all) {
  const k = teamKey(name);
  if (k === name) return name;
  const same = (all || []).filter(n => teamKey(n) === k);
  if (same.length < 2) return k;
  // two presets of one nation (India T20 2024, India ODI 2023): the one in the chosen format keeps the plain name
  const fm = ($('c-fmt') ? $('c-fmt').value : '').toUpperCase(), inFmt = n => new RegExp(`\\b${fm}\\b`, 'i').test(n.slice(k.length));
  return fm && inFmt(name) && same.filter(inFmt).length === 1 ? k : `${k} (${name.slice(k.length).trim()})`;
}
const DETAIL_KEY = 'lo.detail', MORE_KEY = 'lo.more.';
function lsGet(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
function lsSet(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private window: not remembered */ } }
/* match length when you play ball by ball: Key moments (default) or Every ball */
const LEN_KEY = 'lo.len';
const capLen = () => lsGet(LEN_KEY) === 'all' ? 'all' : 'key';
function setLen(v) {
  lsSet(LEN_KEY, v === 'all' ? 'all' : 'key');
  document.querySelectorAll('#pre-len button').forEach(b => b.classList.toggle('on', b.dataset.l === capLen()));
}
function setDetail(d) {
  d = d === 'full' ? 'full' : 'simple';
  document.body.classList.toggle('detail-full', d === 'full'); document.body.classList.toggle('detail-simple', d !== 'full');
  document.querySelectorAll('#detail-sw button').forEach(b => b.classList.toggle('on', b.dataset.d === d));
  lsSet(DETAIL_KEY, d);
}
function initDetail() {
  setDetail(lsGet(DETAIL_KEY) || 'simple');
  document.querySelectorAll('#detail-sw button').forEach(b => b.onclick = () => setDetail(b.dataset.d));
  document.querySelectorAll('details.more').forEach(d => {
    if (lsGet(MORE_KEY + d.id) === '1') d.open = true;
    d.addEventListener('toggle', () => lsSet(MORE_KEY + d.id, d.open ? '1' : '0'));
  });
}
initDetail();
/* the top-bar pill only while something runs: "Live: IND v AUS" (click to go back to it) */
function livePill(running, st) {
  const p = $('status-pill');
  p.style.display = running ? '' : 'none';
  p.classList.toggle('run', running);
  if (!running) return;
  const tm = (typeof CAP !== 'undefined' && CAP.teams) || [];
  const vs = tm.length === 2 && tm.every(Boolean) ? ': ' + tm.map(t => tcol(t).short).join(' v ') : '';
  p.innerHTML = '<i></i>' + (st && st.captain ? 'Live' + vs : 'Simulating');
}

/* generic sortable table (from the Test sim) */
function table(el, cols, rows, opt = {}) {
  el._cols = cols; el._rows = rows; el._opt = opt;
  if (!el._sort) el._sort = opt.sort || null;
  renderTable(el);
}
function renderTable(el) {
  const cols = el._cols, opt = el._opt, s = el._sort;
  let rows = el._rows.slice();
  if (s) {
    const c = cols.find(c => c.k === s.k);
    const val = r => c.sv ? c.sv(r) : r[c.k];
    rows.sort((a, b) => {
      let x = val(a), y = val(b);
      const xn = x === null || x === undefined || x === '', yn = y === null || y === undefined || y === '';
      if (xn || yn) return xn && yn ? 0 : xn ? 1 : -1;
      if (typeof x === 'string') return x.localeCompare(y) * s.dir;
      return (x - y) * s.dir;
    });
  }
  const total = rows.length;
  if (opt.limit) rows = rows.slice(0, opt.limit);
  let h = '<table><thead><tr>';
  cols.forEach(c => {
    const arrow = s && s.k === c.k ? (s.dir > 0 ? ' ▲' : ' ▼') : '';
    h += `<th class="${c.nosort ? '' : 'sortable'} ${c.num ? 'num' : ''}" data-k="${c.k}">${esc(c.label)}${arrow}</th>`;
  });
  h += '</tr></thead><tbody>';
  rows.forEach((r, i) => {
    const cls = (opt.rowClass ? opt.rowClass(r) : '') + (opt.onRow ? ' click' : '');
    h += `<tr class="${cls}" data-i="${i}">` + cols.map(c => `<td class="${c.num ? 'num' : ''}">${c.html ? c.html(r) : esc(c.f ? c.f(r) : fmtNum(r[c.k]))}</td>`).join('') + '</tr>';
  });
  if (!rows.length) h += `<tr><td colspan="${cols.length}" class="muted">${esc(opt.empty || 'Nothing to show')}</td></tr>`;
  h += '</tbody></table>';
  if (opt.limit && total > opt.limit) h += `<div class="muted small" style="padding:8px">Showing ${opt.limit} of ${total} — use the filters to narrow down.</div>`;
  el.innerHTML = h;
  el.querySelectorAll('th.sortable').forEach(th => th.onclick = () => {
    const k = th.dataset.k, c = cols.find(c => c.k === k);
    el._sort = el._sort && el._sort.k === k ? {k, dir: -el._sort.dir} : {k, dir: c.num ? -1 : 1};
    renderTable(el);
  });
  if (opt.onRow || opt.onClick) el.querySelectorAll('tbody tr[data-i]').forEach(tr => {
    const r = rows[+tr.dataset.i];
    if (opt.onRow) tr.onclick = e => { if (!e.target.closest('button') && !e.target.closest('[data-match]')) opt.onRow(r); };
    tr.querySelectorAll('button[data-act]').forEach(b => b.onclick = () => opt.onClick(r, b.dataset.act));
  });
}
