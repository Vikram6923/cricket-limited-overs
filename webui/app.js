'use strict';
/* Match links and popovers, then start-up. Loaded last: the page is split by screen into base.js, home.js,
   setup.js, draft.js, run.js, results.js, matchcentre.js, stats.js, builder.js (in that order, see index.html)
   and the room scripts; they share one scope, as when most of it was this one file. */

/* ───────────────────────── match links + popovers (from the Test sim) ───────────────────────── */
function openMatchN(n) {
  const i = R.fixtures.findIndex(m => m.match_no === n);
  if (i < 0) return;
  hidePop(true); CUR_MATCH = i; openTab('p-matches');
  $('v-results').scrollTop = 0;
}
document.addEventListener('click', e => {
  const a = e.target.closest('[data-match]');
  if (a) { e.preventDefault(); openMatchN(+a.dataset.match); return; }
  const p = e.target.closest('.pop');
  if (p) { showPop(p); return; }
  if (!e.target.closest('#popover')) hidePop(true);
});
const POPS = new Map(); let POP_ID = 0, POP_T = null;
function popCell(list, title, line) {
  list = list || [];
  if (!list.length) return '0';
  const id = ++POP_ID;
  POPS.set(id, `<div class="pop-title">${esc(title)} — click to open the match</div>` +
    list.map(x => `<a class="pop-item" data-match="${x.n}">${line(x)}<span class="muted">Match ${x.n}</span></a>`).join(''));
  return `<span class="pop" data-pop="${id}">${list.length}</span>`;
}
function showPop(el) {
  clearTimeout(POP_T);
  const box = $('popover'); box.innerHTML = POPS.get(+el.dataset.pop) || '';
  box.style.display = 'block';
  const r = el.getBoundingClientRect(), w = box.offsetWidth, h = box.offsetHeight;
  let left = Math.min(window.innerWidth - w - 10, Math.max(10, r.left + r.width / 2 - w / 2));
  let top = r.bottom + 6; if (top + h > window.innerHeight - 10) top = Math.max(10, r.top - h - 6);
  box.style.left = left + 'px'; box.style.top = top + 'px';
}
function hidePop(now) {
  clearTimeout(POP_T);
  if (now) { $('popover').style.display = 'none'; return; }
  POP_T = setTimeout(() => $('popover').style.display = 'none', 250);
}
document.addEventListener('mouseover', e => {
  const p = e.target.closest('.pop');
  if (p) showPop(p); else if (e.target.closest('#popover')) clearTimeout(POP_T);
});
document.addEventListener('mouseout', e => {
  if (e.target.closest('.pop') || e.target.closest('#popover')) hidePop(false);
});
document.addEventListener('scroll', () => hidePop(true), true);

init().catch(e => { document.body.innerHTML = `<div style="padding:30px;color:#f85149">Could not start the UI: ${esc(e.message)}</div>`; });
