/* UNSAID · the map. Shared by the site (S2 header) and media/ (hero, clip).
   Ported from research/round4/proto/js/um.js. Grey = the city (OSM places), red = only what the AIs said,
   white = the seven. No basemap: the dots draw the city. */
(function () {
  const C = {
    bg: '#0b0b0b', dot: '#6a6a6a', red: '#ff2d3d', white: '#f2efe6', ink: '#ecebe5', dim: '#8e8c85', faint: '#4b4a46', amber: '#e2a336',
  };

  function canvas(el, w, h) {
    const c = document.createElement('canvas');
    const dpr = window.devicePixelRatio || 1;
    c.width = Math.round(w * dpr); c.height = Math.round(h * dpr);
    c.style.cssText = `position:absolute;left:0;top:0;width:${w}px;height:${h}px`;
    el.appendChild(c);
    const ctx = c.getContext('2d'); ctx.scale(dpr, dpr);
    return ctx;
  }

  // fit the city's places into box {x,y,w,h}, north up, aspect kept. M: map JSON {places, lat0, latMax}
  function projection(M, box) {
    const K = Math.cos((M.lat0 || 40) * Math.PI / 180);
    const latMax = box.latMax ?? M.latMax ?? 99;
    let a = Infinity, b = -Infinity, c = Infinity, d = -Infinity;
    for (const [lon, lat] of M.places) { if (lat > latMax) continue; a = Math.min(a, lon); b = Math.max(b, lon); c = Math.min(c, lat); d = Math.max(d, lat); }
    if (latMax < 99) d = Math.max(d, latMax - 0.004);
    const sw = (b - a) * K, sh = d - c;
    const s = Math.min(box.w / sw, box.h / sh);
    const ox = box.x + (box.w - sw * s) / 2, oy = box.y + (box.h - sh * s) / 2;
    const P = (lon, lat) => [ox + (lon - a) * K * s, oy + (d - lat) * s];
    P.bounds = { x0: ox, x1: ox + sw * s, y0: oy, y1: oy + sh * s };
    P.scale = s;
    return P;
  }

  const discD = (count, cmax, dmax, dmin) => Math.max(dmin, dmax * Math.sqrt(count / cmax));

  function dots(ctx, M, P, o = {}) {
    const r = (o.d || 2.5) / 2;
    if (o.glow) { // density haze made from the dots themselves
      M.places.forEach(([lon, lat], i) => {
        const k = o.reveal ? o.reveal(i) : 1; if (k <= 0) return;
        const [x, y] = P(lon, lat);
        const g = ctx.createRadialGradient(x, y, 0, x, y, o.glow);
        g.addColorStop(0, `rgba(150,148,140,${0.06 * k})`); g.addColorStop(1, 'rgba(150,148,140,0)');
        ctx.fillStyle = g; ctx.fillRect(x - o.glow, y - o.glow, o.glow * 2, o.glow * 2);
      });
    }
    ctx.fillStyle = o.color || C.dot;
    M.places.forEach(([lon, lat], i) => {
      const k = o.reveal ? o.reveal(i) : 1; if (k <= 0) return;
      ctx.globalAlpha = (o.alpha ?? 0.95) * k;
      const [x, y] = P(lon, lat);
      ctx.beginPath(); ctx.arc(x, y, r, 0, 7); ctx.fill();
    });
    ctx.globalAlpha = 1;
  }

  function disc(ctx, x, y, d, alpha = 0.88) {
    ctx.globalAlpha = alpha; ctx.fillStyle = C.red;
    ctx.beginPath(); ctx.arc(x, y, d / 2, 0, 7); ctx.fill();
    ctx.globalAlpha = 1;
  }

  function seven(ctx, x, y, k = 1, d = 8, halo = 3, color = C.white) {
    if (k <= 0) return;
    ctx.globalAlpha = 0.28 * k; ctx.fillStyle = color;
    ctx.beginPath(); ctx.arc(x, y, d / 2 + halo + 2 * (1 - k), 0, 7); ctx.fill();
    ctx.globalAlpha = k; ctx.fillStyle = C.bg;
    ctx.beginPath(); ctx.arc(x, y, d / 2 + 1, 0, 7); ctx.fill();
    ctx.fillStyle = color;
    ctx.beginPath(); ctx.arc(x, y, d / 2, 0, 7); ctx.fill();
    ctx.globalAlpha = 1;
  }

  function ring(ctx, x, y, r, w = 1.5, alpha = .9) {
    ctx.strokeStyle = C.red; ctx.lineWidth = w; ctx.globalAlpha = alpha;
    ctx.beginPath(); ctx.arc(x, y, r, 0, 7); ctx.stroke(); ctx.globalAlpha = 1;
  }

  // callouts: items {x,y,h,side} -> label y per side column, no overlaps, kept within [top,bottom]
  function stack(items, top, bottom, gap = 6) {
    for (const side of ['L', 'R']) {
      const col = items.filter(i => i.side === side).sort((a, b) => a.y - b.y);
      col.forEach(i => { i.ly = i.y - i.h / 2; });
      for (let pass = 0; pass < 60; pass++) {
        let moved = false;
        for (let j = 1; j < col.length; j++) {
          const p = col[j - 1], q = col[j], ov = p.ly + p.h + gap - q.ly;
          if (ov > 0) { p.ly -= ov / 2; q.ly += ov / 2; moved = true; }
        }
        col.forEach(i => { i.ly = Math.max(top, Math.min(bottom - i.h, i.ly)); });
        if (!moved) break;
      }
    }
    return items;
  }

  function leader(ctx, x0, y0, x1, y1, color, alpha) {
    ctx.globalAlpha = alpha; ctx.strokeStyle = color; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1); ctx.stroke(); ctx.globalAlpha = 1;
  }

  function el(parent, tag, css, html) {
    const e = document.createElement(tag);
    if (css) e.style.cssText = css;
    if (html != null) e.innerHTML = html;
    parent.appendChild(e);
    return e;
  }

  const esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  const fmt = n => Number(n).toLocaleString('en-US');
  // a placeholder is drawn only for a null data field; it names the field, never invents a value
  const ph = (v, label) => (v === null || v === undefined) ? `<span class="ph">⟦${esc(label)}⟧</span>` : esc(v);
  const param = (k, d) => new URLSearchParams(location.search).get(k) ?? d;

  // ET clock for asked_at stamps: "27 Oct 08:05 ET"
  function et(iso, withDate = true) {
    if (!iso) return null;
    const d = new Date(iso);
    const p = Object.fromEntries(new Intl.DateTimeFormat('en-GB', { timeZone: 'America/New_York', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false })
      .formatToParts(d).map(x => [x.type, x.value]));
    return (withDate ? `${p.day} ${p.month} ` : '') + `${p.hour}:${p.minute} ET`;
  }
  const hhmm = (d = new Date()) => d.toTimeString().slice(0, 5);

  async function json(url) { const r = await fetch(url); if (!r.ok) throw new Error(url + ' ' + r.status); return r.json(); }

  // results file: an NDJSON stream (its "done" line) or a plain result JSON
  async function result(url) {
    const r = await fetch(url); if (!r.ok) throw new Error(url + ' ' + r.status);
    const t = await r.text();
    if (url.endsWith('.ndjson')) {
      const lines = t.trim().split('\n').map(l => JSON.parse(l));
      const done = lines.find(l => l.type === 'done');
      return done && done.result;
    }
    const j = JSON.parse(t); return j.result || j;
  }

  window.UM = { C, canvas, projection, discD, dots, disc, seven, ring, stack, leader, el, esc, fmt, ph, param, et, hhmm, json, result };
})();
