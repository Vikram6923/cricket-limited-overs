/* Highlights for ball-by-ball play (docs/match_play_design.md): a top-down ground with the field, the ball's
   path, runners, flying stumps, and a side-on strip showing the length. The engine decides what happened (runs,
   extras, the wicket and the catcher: Match.log_ball); Cricsheet records no shot direction, field or length, so
   those are drawn here from rules (the batter's hand, the phase, the bowling plan, the kind of outcome), seeded by
   the ball so a replay looks the same. Presentation only. */
'use strict';

const HL = (() => {
  const C = {x: 160, y: 160}, R = 150, RING = 64;
  const BAT = {x: 160, y: 192}, BOWL_END = {x: 160, y: 128};
  const POS = {
    slip: [150, 'c', 30], gully: [115, 'c', 44], point: [92, 0.4], cover: [58, 0.42], 'mid-off': [18, 0.44],
    'mid-on': [-18, 0.44], midwicket: [-58, 0.42], 'square leg': [-95, 0.4], 'short fine leg': [-150, 0.36],
    'short third man': [140, 0.4], 'third man': [140, 0.93], 'deep point': [95, 0.93], 'deep cover': [60, 0.93],
    'long-off': [14, 0.94], 'long-on': [-14, 0.94], 'deep midwicket': [-55, 0.93], 'deep square leg': [-92, 0.93],
    'fine leg': [-150, 0.93]};
  const FIELDS = {
    powerplay: {attack: ['slip', 'gully', 'point', 'cover', 'mid-off', 'mid-on', 'midwicket', 'third man', 'fine leg'],
      normal: ['slip', 'point', 'cover', 'mid-off', 'mid-on', 'midwicket', 'square leg', 'third man', 'fine leg'],
      contain: ['point', 'cover', 'mid-off', 'mid-on', 'midwicket', 'square leg', 'short fine leg', 'deep point', 'deep square leg']},
    middle: {attack: ['slip', 'point', 'cover', 'mid-off', 'mid-on', 'midwicket', 'square leg', 'long-on', 'deep midwicket'],
      normal: ['point', 'cover', 'mid-off', 'mid-on', 'midwicket', 'short fine leg', 'long-on', 'deep midwicket', 'deep point'],
      contain: ['point', 'cover', 'mid-on', 'short third man', 'long-off', 'long-on', 'deep midwicket', 'deep square leg', 'deep point']},
    death: {attack: ['slip', 'point', 'cover', 'mid-off', 'short fine leg', 'long-on', 'deep midwicket', 'deep square leg', 'third man'],
      normal: ['point', 'short third man', 'short fine leg', 'cover', 'long-off', 'long-on', 'deep midwicket', 'deep square leg', 'deep point'],
      contain: ['short third man', 'short fine leg', 'mid-on', 'cover', 'long-off', 'long-on', 'deep midwicket', 'deep square leg', 'deep point']}};
  const LEN_X = {yorker: 292, full: 258, good: 214, short: 160};      // bounce point on the side strip
  const LEN_H = {yorker: 4, full: 18, good: 30, short: 46};           // height reaching the batter
  const LEN_ZB = {yorker: 0.95, full: 0.82, good: 0.66, short: 0.45};  // bounce point, top-down
  const LEN_WORD = {yorker: 'yorker', full: 'full', good: 'good length', short: 'short'};

  let token = 0;
  const level = () => { try { return localStorage.getItem('hlLevel') || 'key'; } catch (e) { return 'key'; } };
  const setLevel = v => { try { localStorage.setItem('hlLevel', v); } catch (e) { /* private window */ } };
  const keyBall = e => e.wicket || e.runs === 4 || e.runs === 6;

  function rng(seed) {                       // mulberry32
    let a = 0;
    for (const ch of seed) a = Math.imul(a ^ ch.charCodeAt(0), 2654435761) >>> 0;
    return () => {
      a = (a + 0x6D2B79F5) >>> 0; let t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  const pick = (r, xs) => xs[Math.floor(r() * xs.length)];
  const between = (r, a, b) => a + (b - a) * r();
  const lerp = (a, b, k) => a + (b - a) * k;
  const lerpP = (p, q, k) => ({x: lerp(p.x, q.x, k), y: lerp(p.y, q.y, k)});

  // geometry: angle 0 = straight back past the bowler, positive = off side (to the right for a right-hander)
  function unit(a, hand) { const h = hand === 'left' ? -1 : 1, r = a * Math.PI / 180; return {x: Math.sin(r) * h, y: -Math.cos(r)}; }
  function rope(a, hand) {
    const u = unit(a, hand), dx = BAT.x - C.x, dy = BAT.y - C.y;
    const b = dx * u.x + dy * u.y, c = dx * dx + dy * dy - R * R;
    return -b + Math.sqrt(b * b - c);
  }
  function at(a, frac, hand, px) {
    const u = unit(a, hand), t = px !== undefined ? px : rope(a, hand) * frac;
    return {x: BAT.x + u.x * t, y: BAT.y + u.y * t};
  }
  const angDist = (a, b) => Math.abs(((a - b + 540) % 360) - 180);

  function fieldFor(e) {
    const plan = e.plan <= 3 ? 'contain' : e.plan >= 7 ? 'attack' : 'normal';
    return FIELDS[e.phase] ? FIELDS[e.phase][plan] : FIELDS.middle[plan];
  }
  function place(name, hand) { const p = POS[name]; return p[1] === 'c' ? at(p[0], 0, hand, p[2]) : at(p[0], p[1], hand); }

  // what the ball did, from what the engine says happened
  function plan(e) {
    const r = rng(`${e.innings}|${e.over}|${e.ball}|${e.batter_id}|${e.n}`);
    const hand = e.hand, spin = e.bowl_type === 'spin';
    const field = fieldFor(e).map(n => ({name: n, a: POS[n][0], deep: POS[n][1] >= 0.9, p: place(n, hand)}));
    const keeper = {x: BAT.x, y: BAT.y + 22};
    const s = {hand, field, keeper, len: 'good', line: 0, shot: null, label: '', color: 'var(--text)', runs: e.runs,
      ran: e.ran || 0, stumps: false, catcher: null, chaser: null, speed: spin ? Math.round(between(r, 80, 95)) : Math.round(between(r, 126, 148))};
    const gapAngle = (lo, hi) => {                     // the angle in [lo, hi] furthest from any deep fielder
      let best = lo, bd = -1;
      for (let k = 0; k < 12; k++) {
        const a = between(r, lo, hi);
        const d = Math.min(...field.filter(f => f.deep).map(f => angDist(a, f.a)), 999);
        if (d > bd) { bd = d; best = a; }
      }
      return best;
    };
    const nearest = (p, deepOnly) => field.filter(f => !deepOnly || f.deep)
      .reduce((m, f) => (Math.hypot(f.p.x - p.x, f.p.y - p.y) < Math.hypot(m.p.x - p.x, m.p.y - p.y) ? f : m));
    const w = e.wicket;
    if (e.extra === 'w') {
      s.len = pick(r, ['good', 'full', 'short']); s.line = pick(r, [1, 1, -1]);
      s.shot = {to: {x: keeper.x + s.line * 26 * (hand === 'left' ? -1 : 1), y: keeper.y}, h: 0, kind: 'wide'};
      s.label = 'WIDE'; s.color = 'var(--amber)';
      return s;
    }
    if (w === 'bowled' || w === 'hit_wicket') {
      s.len = spin ? pick(r, ['full', 'good']) : pick(r, ['yorker', 'yorker', 'full', 'good']);
      s.shot = {to: {x: BAT.x, y: BAT.y + 9}, h: 0, kind: 'stumps'}; s.stumps = true;
      s.label = w === 'bowled' ? 'BOWLED' : 'HIT WICKET'; s.color = 'var(--red)';
    } else if (w === 'lbw') {
      s.len = spin ? pick(r, ['full', 'good']) : pick(r, ['yorker', 'full', 'full']);
      s.shot = {to: {x: BAT.x + 4, y: BAT.y - 3}, h: 0, kind: 'pad'}; s.label = 'LBW'; s.color = 'var(--red)';
    } else if (w === 'stumped') {
      s.len = pick(r, ['full', 'good']);
      s.shot = {to: keeper, h: 0, kind: 'keeper'}; s.stumps = true; s.charge = true;
      s.label = 'STUMPED'; s.color = 'var(--red)';
    } else if (w === 'caught_keeper') {
      s.len = pick(r, ['good', 'good', 'short']);
      s.catcher = {name: e.fielder, p: e.fielder_role === 'keeper' ? keeper : place('slip', hand)};
      s.shot = {to: s.catcher.p, h: 6, kind: 'edge'}; s.label = 'CAUGHT BEHIND'; s.color = 'var(--red)';
    } else if (w === 'caught_bowler') {
      s.len = pick(r, ['full', 'good']);
      s.catcher = {name: e.fielder, p: {x: BOWL_END.x + 6, y: BOWL_END.y + 6}};
      s.shot = {to: s.catcher.p, h: 10, kind: 'air'}; s.label = 'CAUGHT AND BOWLED'; s.color = 'var(--red)';
    } else if (w === 'caught_fielder') {
      s.len = pick(r, ['short', 'good', 'good', 'full']);
      const deep = field.filter(f => f.deep), ring = field.filter(f => !f.deep);
      const f = (deep.length && (e.phase === 'death' || r() < 0.6)) ? pick(r, deep) : pick(r, ring);
      s.catcher = {name: e.fielder, p: f.p, pos: f.name};
      s.shot = {to: f.p, h: f.deep ? 60 : 16, kind: 'air'}; s.label = 'CAUGHT'; s.color = 'var(--red)';
    } else if (w === 'run_out') {
      const f = pick(r, field.filter(x => !x.deep));
      s.shot = {to: lerpP(BAT, f.p, 0.8), h: 0, kind: 'ground'}; s.chaser = f;
      s.throwTo = e.out_end === 'striker' ? {x: BAT.x, y: BAT.y + 8} : {x: BOWL_END.x, y: BOWL_END.y - 8};
      s.label = 'RUN OUT'; s.color = 'var(--red)'; s.runout = e.out_end;
    } else if (e.runs === 6) {
      s.len = pick(r, ['short', 'full', 'full', 'good']);
      const a = s.len === 'short' ? gapAngle(-110, -60) : gapAngle(-50, 45);
      s.shot = {to: at(a, 1.14, hand), h: 95, kind: 'air'}; s.label = 'SIX'; s.color = 'var(--green)';
    } else if (e.runs === 4) {
      s.len = pick(r, ['short', 'full', 'good']);
      const a = s.len === 'short' ? (r() < 0.5 ? gapAngle(70, 120) : gapAngle(-110, -70))
        : s.len === 'full' ? (r() < 0.5 ? gapAngle(10, 70) : gapAngle(-70, -10)) : gapAngle(-150, 150);
      const to = at(a, 1.0, hand);
      s.shot = {to, h: 0, kind: 'ground'}; s.chaser = nearest(to, true);
      s.label = 'FOUR'; s.color = 'var(--blue)';
    } else if (e.runs > 0) {
      s.len = pick(r, ['good', 'full', 'short']);
      const frac = {1: 0.42, 2: 0.74, 3: 0.9}[e.runs] || 0.42;
      const a = between(r, -150, 150), to = at(a, frac, hand);
      s.shot = {to, h: e.runs >= 2 ? 0 : 0, kind: 'ground'}; s.chaser = nearest(to, e.runs >= 2);
      s.label = `${e.runs} RUN${e.runs > 1 ? 'S' : ''}`; s.color = 'var(--text)';
    } else if (e.extra === 'b' || e.extra === 'lb') {
      s.len = pick(r, ['good', 'full']);
      const to = at(e.extra === 'lb' ? -150 : 175, e.extra_runs >= 4 ? 1.0 : 0.6, hand);
      s.shot = {to, h: 0, kind: 'ground'}; s.chaser = nearest(to, false);
      s.label = `${e.extra_runs} ${e.extra === 'lb' ? 'LEG BYE' : 'BYE'}${e.extra_runs > 1 ? 'S' : ''}`; s.color = 'var(--muted)';
    } else {
      s.len = pick(r, ['good', 'good', 'full', 'short']);
      if (!spin && r() < 0.3) { s.shot = {to: keeper, h: 0, kind: 'keeper'}; s.label = 'LEFT ALONE'; }
      else { const f = pick(r, field.filter(x => !x.deep)); s.shot = {to: lerpP(BAT, f.p, 0.92), h: 0, kind: 'ground'}; s.label = 'DOT BALL'; }
      s.color = 'var(--muted)';
    }
    if (e.extra === 'nb') { s.label = `NO BALL${e.runs ? ' · ' + s.label : ''}`; s.color = 'var(--amber)'; }
    return s;
  }

  // ------------------------------------------------------------------ drawing
  const NS = 'http://www.w3.org/2000/svg';
  function el(tag, attrs, parent) {
    const n = document.createElementNS(NS, tag);
    for (const k in attrs) n.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(n);
    return n;
  }
  function stumpsAt(g, x, y) { const s = el('g', {}, g); for (const dx of [-3, 0, 3]) el('line', {x1: x + dx, y1: y, x2: x + dx, y2: y - 7, stroke: '#e9dfc0', 'stroke-width': 1.6}, s); return s; }

  function build(box, e, s) {
    box.innerHTML = `<div class="hl-head"><span>${esc(`Over ${e.over}, ball ${e.ball}`)} · ${esc(e.bowler)} to ${esc(e.batter)}</span><span class="hl-count"></span></div>
      <div class="hl-stage"><svg class="hl-ground" viewBox="-12 -12 344 344"></svg><div class="hl-flash"></div></div>
      <svg class="hl-strip" viewBox="0 0 320 64"></svg>
      <div class="hl-foot"></div>`;
    const svg = box.querySelector('.hl-ground');
    el('circle', {cx: C.x, cy: C.y, r: R, fill: '#143823', stroke: '#2d6b45', 'stroke-width': 2.5}, svg);
    el('circle', {cx: C.x, cy: C.y, r: RING, fill: 'none', stroke: '#3c7a54', 'stroke-dasharray': '4 4'}, svg);
    el('rect', {x: 152, y: 124, width: 16, height: 72, rx: 2, fill: '#8a7650'}, svg);
    stumpsAt(svg, BAT.x, BAT.y + 10); const farStumps = stumpsAt(svg, BOWL_END.x, BOWL_END.y - 2);
    const fl = el('g', {}, svg), fielders = {};
    for (const f of s.field) {
      fielders[f.name] = el('circle', {cx: f.p.x, cy: f.p.y, r: 4.5, fill: '#c9d1d9'}, fl);
    }
    const keeper = el('circle', {cx: s.keeper.x, cy: s.keeper.y, r: 4.5, fill: '#c9d1d9'}, fl);
    const bowler = el('circle', {cx: BOWL_END.x + 7, cy: BOWL_END.y - 26, r: 5, fill: '#e3b341'}, svg);
    const striker = el('circle', {cx: BAT.x - 8, cy: BAT.y, r: 5, fill: '#4c8dff'}, svg);
    const nonStr = el('circle', {cx: BOWL_END.x + 9, cy: BOWL_END.y + 2, r: 5, fill: '#4c8dff'}, svg);
    const trail = el('path', {d: '', fill: 'none', stroke: '#e3b341', 'stroke-width': 1.6, 'stroke-dasharray': '3 4', opacity: 0.85}, svg);
    const ball = el('circle', {cx: BOWL_END.x, cy: BOWL_END.y, r: 3.2, fill: '#ffffff'}, svg);
    const tag = el('text', {x: 0, y: 0, fill: '#e6edf3', 'font-size': 11, 'text-anchor': 'middle', opacity: 0}, svg);
    const bails = el('g', {opacity: 0}, svg);
    for (const dx of [-4, 4]) el('line', {x1: BAT.x + dx - 2, y1: BAT.y + 2, x2: BAT.x + dx + 2, y2: BAT.y + 2, stroke: '#e9dfc0', 'stroke-width': 1.6}, bails);
    // side-on strip: release, bounce at the length, on to the batter
    const st = box.querySelector('.hl-strip');
    el('line', {x1: 10, y1: 54, x2: 310, y2: 54, stroke: '#8a7650', 'stroke-width': 3}, st);
    for (const x of [16, 304]) el('line', {x1: x, y1: 54, x2: x, y2: 36, stroke: '#e9dfc0', 'stroke-width': 2}, st);
    const bx = LEN_X[s.len], hEnd = 54 - LEN_H[s.len];
    el('path', {d: `M24 18 Q ${(24 + bx) / 2} ${s.len === 'short' ? 30 : 22} ${bx} 53 Q ${(bx + 300) / 2} ${hEnd - 6} 300 ${hEnd}`,
      fill: 'none', stroke: '#e3b341', 'stroke-width': 1.5, 'stroke-dasharray': '3 4'}, st);
    el('circle', {cx: bx, cy: 53, r: 2.6, fill: '#ffffff'}, st);
    el('text', {x: 10, y: 12, fill: '#8b949e', 'font-size': 11}, st).textContent =
      `${LEN_WORD[s.len]} · ${s.speed} km/h ${e.bowl_kind || e.bowl_type}`;
    return {svg, ball, trail, striker, nonStr, bowler, fielders, keeper, tag, bails, farStumps,
      flash: box.querySelector('.hl-flash'), foot: box.querySelector('.hl-foot')};
  }

  function animate(d, e, s, myToken) {
    return new Promise(done => {
      const T_RUN = 450, T_DEL = 520, T_SHOT = s.shot.kind === 'air' && s.shot.h > 50 ? 1300 : 1000, T_HOLD = 1100;
      const zb = LEN_ZB[s.len], lineX = BAT.x + (s.shot.kind === 'wide' ? 0 : 0);
      const to = s.shot.to, ctrl = {x: (BAT.x + to.x) / 2, y: (BAT.y + to.y) / 2 - (s.shot.h || 0)};
      const chaser = s.chaser ? d.fielders[s.chaser.name] : null;
      const chase0 = s.chaser ? {...s.chaser.p} : null;
      const t0 = performance.now();
      let path = '';
      const runner = (k) => {           // batters running: swap ends `ran` times over the shot
        const n = s.ran;
        if (!n) return;
        const legs = Math.min(n * k, n), leg = Math.floor(legs), frac = legs - leg;
        const A = {x: BAT.x - 8, y: BAT.y}, B = {x: BOWL_END.x + 9, y: BOWL_END.y + 2};
        let p1 = leg % 2 ? B : A, q1 = leg % 2 ? A : B;
        if (leg >= n) { p1 = n % 2 ? B : A; q1 = p1; }
        const s1 = lerpP(p1, q1, leg >= n ? 0 : frac), s2 = lerpP(q1, p1, leg >= n ? 0 : frac);
        if (s.runout && leg === n - 1 && frac > 0.6) {                     // the batter run out stops short
          const stop = (s.runout === 'striker' ? s2 : s1);
          Object.assign(stop, lerpP(s.runout === 'striker' ? q1 : p1, s.runout === 'striker' ? p1 : q1, 0.35));
        }
        d.striker.setAttribute('cx', s1.x.toFixed(1)); d.striker.setAttribute('cy', s1.y.toFixed(1));
        d.nonStr.setAttribute('cx', s2.x.toFixed(1)); d.nonStr.setAttribute('cy', s2.y.toFixed(1));
      };
      function frame(now) {
        if (myToken !== token) return done(false);
        const t = now - t0;
        if (t < T_RUN) {
          d.bowler.setAttribute('cy', (BOWL_END.y - 26 + 22 * t / T_RUN).toFixed(1));
        } else if (t < T_RUN + T_DEL) {
          const k = (t - T_RUN) / T_DEL;
          let p = lerpP(BOWL_END, {x: s.shot.kind === 'wide' ? to.x : lineX, y: BAT.y - 2}, k);
          d.ball.setAttribute('cx', p.x.toFixed(1)); d.ball.setAttribute('cy', p.y.toFixed(1));
          d.ball.setAttribute('r', (k < zb ? 3.2 + 1.2 * Math.sin(Math.PI * k / zb) : 3.2).toFixed(1));
          if (s.charge) d.striker.setAttribute('cy', (BAT.y - 10 * k).toFixed(1));
        } else if (t < T_RUN + T_DEL + T_SHOT) {
          const k = (t - T_RUN - T_DEL) / T_SHOT;
          const kk = s.shot.kind === 'ground' ? 1 - (1 - k) * (1 - k) : k;   // a ground shot slows down
          const from = {x: BAT.x, y: BAT.y - 2};
          const p = {x: (1 - kk) ** 2 * from.x + 2 * (1 - kk) * kk * ctrl.x + kk * kk * to.x,
                     y: (1 - kk) ** 2 * from.y + 2 * (1 - kk) * kk * ctrl.y + kk * kk * to.y};
          d.ball.setAttribute('cx', p.x.toFixed(1)); d.ball.setAttribute('cy', p.y.toFixed(1));
          d.ball.setAttribute('r', (3.2 + (s.shot.h > 20 ? 4 * Math.sin(Math.PI * kk) : 0)).toFixed(1));
          if (!['stumps', 'pad', 'keeper', 'wide'].includes(s.shot.kind)) {
            path += `${path ? 'L' : 'M'}${p.x.toFixed(1)} ${p.y.toFixed(1)} `;
            d.trail.setAttribute('d', path);
          }
          if (chaser) {
            const c = lerpP(chase0, to, Math.min(1, k * (s.label === 'FOUR' ? 0.55 : 1)));
            chaser.setAttribute('cx', c.x.toFixed(1)); chaser.setAttribute('cy', c.y.toFixed(1));
          }
          runner(k);
          if (s.throwTo && k > 0.75) {          // run out: the throw
            const q = lerpP(to, s.throwTo, (k - 0.75) / 0.25);
            d.ball.setAttribute('cx', q.x.toFixed(1)); d.ball.setAttribute('cy', q.y.toFixed(1));
          }
          if (s.stumps && k > 0.15) {           // stumps and bails fly
            const j = Math.min(1, (k - 0.15) / 0.5);
            d.bails.setAttribute('opacity', 1);
            d.bails.setAttribute('transform', `translate(${(10 * j).toFixed(1)} ${(-14 * j + 18 * j * j).toFixed(1)}) rotate(${(200 * j).toFixed(0)} ${BAT.x} ${BAT.y})`);
          }
        } else if (t < T_RUN + T_DEL + T_SHOT + T_HOLD) {
          if (!d.flash.textContent) {
            d.flash.textContent = s.label; d.flash.style.color = s.color; d.flash.classList.add('on');
            if (s.catcher && s.catcher.name) {
              d.tag.textContent = s.catcher.name + (s.catcher.pos ? ` (${s.catcher.pos})` : '');
              d.tag.setAttribute('x', Math.min(290, Math.max(30, s.catcher.p.x)).toFixed(0));
              d.tag.setAttribute('y', (s.catcher.p.y < 30 ? s.catcher.p.y + 18 : s.catcher.p.y - 9).toFixed(0));
              d.tag.setAttribute('opacity', 1);
            }
          }
        } else {
          return done(true);
        }
        requestAnimationFrame(frame);
      }
      requestAnimationFrame(frame);
    });
  }

  function footText(e) {
    if (e.wicket) return `${esc(e.out || '')} ${esc(e.how || e.wicket)} · ${esc(e.score)}`;
    const extra = e.extra === 'w' ? `wide${e.extra_runs > 1 ? ` (${e.extra_runs})` : ''}` : e.extra === 'nb' ? 'no-ball, free hit next'
      : e.extra === 'b' || e.extra === 'lb' ? `${e.extra_runs} ${e.extra === 'lb' ? 'leg bye' : 'bye'}${e.extra_runs > 1 ? 's' : ''}` : '';
    const runs = e.runs ? `${e.runs} run${e.runs > 1 ? 's' : ''}` : extra ? '' : 'no run';
    return [runs, extra].filter(Boolean).join(', ') + ` · ${esc(e.score)}${e.free_hit ? ' · free hit' : ''}`;
  }

  /* play the highlight-worthy balls in `events` (oldest first) in `box`; a newer call stops this one */
  async function play(events, box) {
    const my = ++token;
    const lv = level();
    const list = (events || []).filter(e => lv === 'all' || (lv === 'key' && keyBall(e)));
    if (!box) return;
    if (!list.length || lv === 'off') { box.innerHTML = ''; box.style.display = 'none'; return; }
    box.style.display = '';
    for (let i = 0; i < list.length; i++) {
      const e = list[i], s = plan(e), d = build(box, e, s);
      box.querySelector('.hl-count').innerHTML = `${list.length > 1 ? `${i + 1} of ${list.length} · ` : ''}<a href="#" class="hl-skip">skip</a>`;
      box.querySelector('.hl-skip').onclick = ev => { ev.preventDefault(); token++; box.innerHTML = ''; box.style.display = 'none'; };
      d.foot.textContent = footText(e);
      if (!(await animate(d, e, s, my))) return;
    }
  }
  function stop() { token++; }
  const OPTIONS = [['off', 'Off'], ['key', 'Wickets and boundaries'], ['all', 'Every ball']];
  function selectHTML() {
    const v = level();
    return `<label class="hl-level">Highlights <select id="hl-level">${OPTIONS.map(([k, t]) =>
      `<option value="${k}" ${k === v ? 'selected' : ''}>${t}</option>`).join('')}</select></label>`;
  }
  return {play, stop, plan, level, setLevel, selectHTML};
})();
