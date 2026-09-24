/*
 * TuxGlass - Liquid Glass for HTML apps built with TuxSign.
 *
 * What makes Liquid Glass look like glass (WWDC25 "Meet Liquid Glass"):
 *   - lensing: light is bent at the curved rim, not just blurred
 *   - specular highlights on the rim that follow device motion
 *   - a light frost + saturation boost, adaptive tint and soft shadow
 *   - interactivity: presses make it flex, grow and glow from the finger
 *   - materializing: elements appear by ramping the lensing up
 *
 * WebKit (the engine inside iOS apps) cannot run SVG filters on
 * `backdrop-filter`, so TuxGlass clones the backdrop *into* each glass
 * element and refracts that copy with an SVG displacement filter
 * (`filter: url()` does work in WebKit). The displacement map is computed
 * physically: a convex squircle rim, Snell's law with IOR 1.5, and a
 * three-channel pass for chromatic dispersion.
 *
 * Usage:
 *   <div class="glass-backdrop"></div>                  what glass refracts
 *   <div class="glass">...</div>                        a glass panel
 *   <button class="glass glass-interactive">Tap</button>
 *   <nav class="glass" data-glass-source=".glass-backdrop, main">  also refract scrolling content
 *   TuxGlass.followTilt()                               highlights follow the device
 */
(function (global) {
  'use strict';

  const NS = 'http://www.w3.org/2000/svg';
  const DEFAULTS = {
    thickness: 26,     // glass depth in px: more = stronger lensing
    bezel: 24,         // width of the curved rim in px
    ior: 1.5,          // index of refraction
    frost: 1.2,        // blur radius in px (clear variant uses less)
    dispersion: 0.08,  // chromatic aberration (0 = single pass, faster)
    saturation: 1.5,
    margin: 32,        // how far outside the shape the lens can sample
  };
  const SOURCE_DEFAULT = '.glass-backdrop';

  const glasses = new Set();
  let defs = null;
  let uid = 0;
  let running = false;

  // ---------------------------------------------------------------- helpers
  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
  const div = (cls) => { const d = document.createElement('div'); d.className = cls; d.setAttribute('aria-hidden', 'true'); return d; };

  function svgDefs() {
    if (defs && defs.isConnected) return defs;
    const svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('aria-hidden', 'true');
    svg.setAttribute('width', '0');
    svg.setAttribute('height', '0');
    svg.style.cssText = 'position:absolute;width:0;height:0;overflow:hidden;pointer-events:none';
    defs = document.createElementNS(NS, 'defs');
    svg.appendChild(defs);
    document.body.appendChild(svg);
    return defs;
  }

  function options(el) {
    const cs = getComputedStyle(el);
    const o = {};
    for (const key of Object.keys(DEFAULTS)) {
      const attr = el.dataset['glass' + key[0].toUpperCase() + key.slice(1)];
      const css = cs.getPropertyValue('--glass-' + key).trim();
      const n = parseFloat(attr ?? css);
      o[key] = Number.isFinite(n) ? n : DEFAULTS[key];
    }
    if (el.classList.contains('glass-clear')) { o.frost = Math.min(o.frost, 0.4); o.saturation = Math.min(o.saturation, 1.25); }
    return o;
  }

  // ------------------------------------------------------ displacement map
  // Convex squircle rim profile: flat top, steep rounded edge.
  const height = (t) => Math.pow(1 - Math.pow(1 - clamp(t, 0, 1), 4), 0.25);

  function buildMap(w, h, radius, o) {
    const M = o.margin;
    const W = Math.ceil(w + 2 * M), H = Math.ceil(h + 2 * M);
    const bezel = clamp(o.bezel, 2, Math.min(w, h) / 2);
    const r = clamp(radius, 0, Math.min(w, h) / 2);

    // Lateral displacement across the rim, from Snell's law.
    const N = 256;
    const profile = new Float32Array(N + 1);
    let max = 1e-6;
    for (let i = 0; i <= N; i++) {
      const x = i / N, e = 1 / N;
      const slope = (height(x + e) - height(x - e)) / (2 * e) * (o.thickness / bezel);
      const theta = Math.atan(slope);
      const refracted = Math.asin(Math.sin(theta) / o.ior);
      profile[i] = Math.tan(theta - refracted) * o.thickness * height(x + 0.02);
      max = Math.max(max, profile[i]);
    }

    const canvas = document.createElement('canvas');
    canvas.width = W; canvas.height = H;
    const ctx = canvas.getContext('2d');
    const img = ctx.createImageData(W, H);
    const d = img.data;
    const cx = W / 2, cy = H / 2, hx = w / 2 - r, hy = h / 2 - r;
    const put = (x, y, rv, gv) => {
      if (x < 0 || y < 0 || x >= W || y >= H) return;
      const i = (y * W + x) * 4;
      d[i] = rv; d[i + 1] = gv; d[i + 2] = 128; d[i + 3] = 255;
    };

    // The map is symmetric in both axes: compute one quadrant, mirror the rest.
    const qw = Math.ceil(W / 2), qh = Math.ceil(H / 2);
    for (let y = 0; y < qh; y++) {
      for (let x = 0; x < qw; x++) {
        const px = Math.abs(x + 0.5 - cx), py = Math.abs(y + 0.5 - cy);
        const qx = px - hx, qy = py - hy;
        const outside = Math.hypot(Math.max(qx, 0), Math.max(qy, 0));
        const dist = outside + Math.min(Math.max(qx, qy), 0) - r;   // < 0 inside
        let dx = 0, dy = 0;
        const depth = -dist;
        if (depth > 0 && depth < bezel) {
          const mag = profile[Math.round((depth / bezel) * N)] / max;
          let nx, ny;
          if (qx > 0 && qy > 0) { const l = Math.hypot(qx, qy) || 1; nx = qx / l; ny = qy / l; }
          else if (qx > qy) { nx = 1; ny = 0; } else { nx = 0; ny = 1; }
          // Sample outward: the rim shows light gathered from beyond the edge.
          dx = nx * mag; dy = ny * mag;
        }
        const rv = Math.round(127.5 + 127.5 * dx), gv = Math.round(127.5 + 127.5 * dy);
        const rn = 255 - rv, gn = 255 - gv;
        // top-left quadrant points toward -x/-y
        put(x, y, rn, gn);
        put(W - 1 - x, y, rv, gn);
        put(x, H - 1 - y, rn, gv);
        put(W - 1 - x, H - 1 - y, rv, gv);
      }
    }
    ctx.putImageData(img, 0, 0);
    return { url: canvas.toDataURL(), scale: 2 * max, W, H, M };
  }

  function buildFilter(g) {
    const { map, o } = g;
    const id = 'tux-glass-' + (++uid);
    const f = document.createElementNS(NS, 'filter');
    const attrs = { id, x: 0, y: 0, width: map.W, height: map.H, filterUnits: 'userSpaceOnUse',
      primitiveUnits: 'userSpaceOnUse', 'color-interpolation-filters': 'sRGB' };
    for (const [k, v] of Object.entries(attrs)) f.setAttribute(k, v);

    const channel = (i) => ['1 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 1 0',
      '0 0 0 0 0  0 1 0 0 0  0 0 0 0 0  0 0 0 1 0',
      '0 0 0 0 0  0 0 0 0 0  0 0 1 0 0  0 0 0 1 0'][i];
    const passes = o.dispersion > 0 ? 3 : 1;
    let body = `<feGaussianBlur in="SourceGraphic" stdDeviation="${o.frost}" result="blur"/>
      <feImage href="${map.url}" xlink:href="${map.url}" x="0" y="0" width="${map.W}" height="${map.H}" preserveAspectRatio="none" result="map"/>`;
    for (let i = 0; i < passes; i++) {
      body += `<feDisplacementMap in="blur" in2="map" scale="0" xChannelSelector="R" yChannelSelector="G" result="d${i}"/>`;
      if (passes > 1) body += `<feColorMatrix in="d${i}" type="matrix" values="${channel(i)}" result="c${i}"/>`;
    }
    if (passes > 1) {
      body += `<feBlend in="c0" in2="c1" mode="screen" result="c01"/><feBlend in="c01" in2="c2" mode="screen" result="rgb"/>`;
    }
    body += `<feColorMatrix in="${passes > 1 ? 'rgb' : 'd0'}" type="saturate" values="${o.saturation}"/>`;
    f.innerHTML = body;
    svgDefs().appendChild(f);
    g.filter?.remove();
    g.filter = f;
    g.displacers = [...f.querySelectorAll('feDisplacementMap')];
    g.lens.style.filter = `url(#${id})`;
    g.appliedScale = -1;
  }

  // ---------------------------------------------------------------- clones
  function sourcesFor(el) {
    const sel = el.dataset.glassSource || SOURCE_DEFAULT;
    ensureBackdrop();
    return [...document.querySelectorAll(sel)].filter((s) => s !== el && !s.closest('.tg-lens'));
  }

  // No .glass-backdrop? Move the body background onto one so it can be cloned.
  function ensureBackdrop() {
    if (document.querySelector('.glass-backdrop')) return;
    const cs = getComputedStyle(document.body);
    const bd = div('glass-backdrop tg-auto');
    for (const p of ['backgroundColor', 'backgroundImage', 'backgroundSize', 'backgroundPosition', 'backgroundRepeat']) bd.style[p] = cs[p];
    document.body.prepend(bd);
    document.body.style.background = 'transparent';
  }

  function cloneSource(src) {
    const node = src.cloneNode(true);
    node.removeAttribute('id');
    node.querySelectorAll('[id]').forEach((n) => n.removeAttribute('id'));
    node.querySelectorAll('.tg-layer, script, iframe').forEach((n) => n.remove());
    // Other glass shows up in the copy as its content; the glass being drawn is left out.
    node.querySelectorAll('[data-tg-self]').forEach((n) => { n.style.visibility = 'hidden'; });
    node.querySelectorAll('video').forEach((v) => { v.muted = true; });
    node.classList.remove('glass');
    node.setAttribute('aria-hidden', 'true');
    node.inert = true;
    const rect = src.getBoundingClientRect();
    Object.assign(node.style, {
      position: 'absolute', left: '0', top: '0', right: 'auto', bottom: 'auto', margin: '0',
      width: rect.width + 'px', height: rect.height + 'px', transform: 'none', transformOrigin: '0 0',
      pointerEvents: 'none', animation: 'none', transition: 'none', zIndex: 'auto',
    });
    const canvases = [...src.querySelectorAll('canvas')].map((c, i) => [c, node.querySelectorAll('canvas')[i]]);
    if (src instanceof HTMLCanvasElement) canvases.push([src, node]);
    return { src, node, canvases, last: '' };
  }

  function reclone(g) {
    g.clones.forEach((c) => c.node.remove());
    g.el.dataset.tgSelf = '';
    g.clones = sourcesFor(g.el).map(cloneSource);
    delete g.el.dataset.tgSelf;
    g.clones.forEach((c) => g.lens.appendChild(c.node));
  }

  // ---------------------------------------------------------------- layout
  function layout(g) {
    const el = g.el;
    const w = el.offsetWidth, h = el.offsetHeight;
    if (!w || !h) return;
    const cs = getComputedStyle(el);
    const radius = Math.min(parseFloat(cs.borderTopLeftRadius) || 0, w / 2, h / 2);
    g.o = options(el);
    const key = [w, h, radius, ...Object.values(g.o)].join(',');
    if (key === g.key) return;
    g.key = key;
    g.map = buildMap(w, h, radius, g.o);
    const M = g.map.M;
    Object.assign(g.lens.style, { left: -M + 'px', top: -M + 'px', width: w + 2 * M + 'px', height: h + 2 * M + 'px' });
    buildFilter(g);
    reclone(g);
  }

  // ----------------------------------------------------------- interaction
  function interactive(g) {
    const el = g.el;
    let start = null;
    const setGlow = (e) => {
      const r = el.getBoundingClientRect();
      el.style.setProperty('--tg-x', ((e.clientX - r.left) / r.width) * 100 + '%');
      el.style.setProperty('--tg-y', ((e.clientY - r.top) / r.height) * 100 + '%');
    };
    el.addEventListener('pointerdown', (e) => {
      start = { x: e.clientX, y: e.clientY };
      g.pressTarget = 1;
      el.classList.add('tg-pressed');
      setGlow(e);
      el.setPointerCapture?.(e.pointerId);
    });
    el.addEventListener('pointermove', (e) => {
      if (!start) return;
      setGlow(e);
      // Gel-like stretch toward the drag, preserving volume.
      const dx = clamp((e.clientX - start.x) / 300, -0.12, 0.12);
      const dy = clamp((e.clientY - start.y) / 300, -0.12, 0.12);
      g.stretch = { x: 1 + Math.abs(dx) - Math.abs(dy) / 2, y: 1 + Math.abs(dy) - Math.abs(dx) / 2, tx: dx * 40, ty: dy * 40 };
    });
    const end = () => {
      start = null;
      g.pressTarget = 0;
      g.stretch = null;
      el.classList.remove('tg-pressed');
    };
    el.addEventListener('pointerup', end);
    el.addEventListener('pointercancel', end);
    el.addEventListener('lostpointercapture', end);
  }

  // ------------------------------------------------------------ lifecycle
  function upgrade(el) {
    if (el._tg || el.closest('.tg-lens')) return;
    const lens = div('tg-layer tg-lens');
    const tint = div('tg-layer tg-tint');
    const glow = div('tg-layer tg-glow');
    const rim = div('tg-layer tg-rim');
    // Bare text must sit above the glass layers, so wrap it.
    for (const n of [...el.childNodes]) {
      if (n.nodeType === 3 && n.textContent.trim()) {
        const span = document.createElement('span');
        span.className = 'tg-text';
        n.replaceWith(span);
        span.appendChild(n);
      }
    }
    el.prepend(lens, tint, glow, rim);
    const hidden = el.classList.contains('glass-hidden');
    const g = { el, lens, tint, glow, rim, clones: [], key: '', strength: hidden ? 0 : 1, target: hidden ? 0 : 1,
      press: 0, pressTarget: 0, stretch: null, scale: 1 };
    el._tg = g;
    if (el.dataset.glassTint) el.style.setProperty('--glass-tint', el.dataset.glassTint);
    glasses.add(g);
    if (el.matches('.glass-interactive')) interactive(g);
    g.ro = new ResizeObserver(() => layout(g));
    g.ro.observe(el);
    layout(g);
    start();
  }

  function destroy(g) {
    g.ro.disconnect();
    g.filter?.remove();
    [g.lens, g.tint, g.glow, g.rim].forEach((n) => n.remove());
    delete g.el._tg;
    glasses.delete(g);
  }

  function frame() {
    if (!glasses.size) { running = false; return; }
    for (const g of glasses) {
      if (!g.el.isConnected) { destroy(g); continue; }
      if (!g.map) { layout(g); if (!g.map) continue; }

      // Springs for materialize (strength) and press.
      g.strength += (g.target - g.strength) * 0.18;
      g.press += (g.pressTarget - g.press) * 0.25;
      if (Math.abs(g.target - g.strength) < 0.002) g.strength = g.target;

      const s = g.strength;
      const sx = (1 + 0.06 * g.press) * (g.stretch?.x ?? 1) * (0.92 + 0.08 * s);
      const sy = (1 + 0.06 * g.press) * (g.stretch?.y ?? 1) * (0.92 + 0.08 * s);
      const tx = g.stretch?.tx ?? 0, ty = g.stretch?.ty ?? 0;
      const transform = sx === 1 && sy === 1 && !tx && !ty ? '' : `translate(${tx}px, ${ty}px) scale(${sx}, ${sy})`;
      if (g.el.style.transform !== transform) g.el.style.transform = transform;
      g.scale = sx;
      const vis = String(s);
      if (g.el.style.getPropertyValue('--tg-strength') !== vis) g.el.style.setProperty('--tg-strength', vis);

      // Lensing ramps with materialization and deepens while pressed.
      const scale = g.map.scale * s * (1 + 0.35 * g.press);
      if (Math.abs(scale - g.appliedScale) > 0.05) {
        g.appliedScale = scale;
        g.displacers.forEach((n, i) => n.setAttribute('scale', (scale * (1 + g.o.dispersion * i)).toFixed(2)));
      }

      // Keep each clone aligned with its source on screen.
      const r = g.el.getBoundingClientRect();
      const M = g.map.M;
      const ox = (r.left + r.width / 2) - (g.el.offsetWidth * sx) / 2;
      const oy = (r.top + r.height / 2) - (g.el.offsetHeight * sy) / 2;
      for (const c of g.clones) {
        const sr = c.src.getBoundingClientRect();
        const t = `translate(${((sr.left - ox) / sx + M).toFixed(1)}px, ${((sr.top - oy) / sy + M).toFixed(1)}px)`;
        if (t !== c.last) { c.node.style.transform = t; c.last = t; }
        if (c.node.scrollTop !== c.src.scrollTop) c.node.scrollTop = c.src.scrollTop;
        if (c.node.scrollLeft !== c.src.scrollLeft) c.node.scrollLeft = c.src.scrollLeft;
        for (const [from, to] of c.canvases) {
          if (!to) continue;
          if (to.width !== from.width || to.height !== from.height) { to.width = from.width; to.height = from.height; }
          to.getContext('2d').drawImage(from, 0, 0);
        }
      }
    }
    requestAnimationFrame(frame);
  }

  function start() {
    if (running) return;
    running = true;
    requestAnimationFrame(frame);
  }

  // Re-copy a glass element's backdrop when its source content changes.
  // TuxGlass's own writes (clones, layer nodes, transforms on .glass) are ignored.
  const stale = new Set();
  let recloneTimer = null;
  function watch() {
    new MutationObserver((records) => {
      for (const rec of records) {
        for (const n of rec.addedNodes) {
          if (n.nodeType !== 1 || n.closest?.('.tg-lens')) continue;
          if (n.matches('.glass')) upgrade(n);
          n.querySelectorAll?.('.glass').forEach(upgrade);
        }
        const t = rec.target.nodeType === 1 ? rec.target : rec.target.parentElement;
        if (!t || t.closest('.tg-layer') || t.closest('svg[aria-hidden]')) continue;
        if (rec.type === 'attributes' && t.classList.contains('glass')) continue;
        for (const g of glasses) {
          if (g.clones.some((c) => c.src.contains(t))) stale.add(g);
        }
      }
      if (stale.size && !recloneTimer) {
        recloneTimer = setTimeout(() => {
          recloneTimer = null;
          stale.forEach(reclone);
          stale.clear();
        }, 100);
      }
    }).observe(document.body, { childList: true, subtree: true, characterData: true, attributes: true,
      attributeFilter: ['class', 'src', 'style', 'value'] });
    addEventListener('resize', () => glasses.forEach((g) => { g.key = ''; layout(g); }));
  }

  // --------------------------------------------------------------- light
  function setLight(deg) {
    document.documentElement.style.setProperty('--tg-light', deg.toFixed(1) + 'deg');
  }

  let tilting = false;
  function followTilt() {
    if (tilting) return;
    tilting = true;
    const fromGravity = (x, y) => setLight(-45 + Math.atan2(x, -y) * 57.3 * -0.6);
    if (global.tux && global.tux.on) {
      global.tux.on('motion', (m) => m.gravity && fromGravity(m.gravity.x, m.gravity.y));
      global.tux.motion?.start?.(30).catch?.(() => {});
    } else {
      addEventListener('deviceorientation', (e) => {
        if (e.gamma == null) return;
        setLight(-45 + e.gamma * 0.8 - (e.beta - 45) * 0.3);
      });
    }
  }

  function show(el) { upgrade(el); el._tg.target = 1; el.classList.remove('glass-hidden'); }
  function hide(el) { upgrade(el); el._tg.target = 0; el.classList.add('glass-hidden'); }

  function init() {
    document.querySelectorAll('.glass').forEach(upgrade);
    watch();
  }

  global.TuxGlass = {
    upgrade, show, hide, setLight, followTilt, defaults: DEFAULTS,
    refresh: () => glasses.forEach((g) => { g.key = ''; layout(g); }),
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})(window);
