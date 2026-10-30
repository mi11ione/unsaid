/* UNSAID · the map. Shared by the site (S2 header) and media/ (hero, clip).
   Ported from research/round4/proto/js/um.js. Grey = the city (OSM places), red = only what the AIs said,
   white = the seven. No basemap: the dots draw the city. */
(function () {
  const C = {
    bg: '#0b0b0b', dot: '#6a6a6a', red: '#ff2d3d', white: '#f2efe6', ink: '#ecebe5', dim: '#8e8c85', faint: '#4b4a46', amber: '#e2a336',
  };
  // the site is printed on paper (<html data-ground="paper">): the seven in ink, the city in grey, red stays the AIs'
  const PAPER = typeof document !== 'undefined' && document.documentElement.dataset.ground === 'paper';
  if (PAPER) Object.assign(C, { bg: '#f4f3ee', dot: '#b4b2aa', red: '#d70412', white: '#0d0d0c', ink: '#0d0d0c', dim: '#5a5954', faint: '#b4b2aa', amber: '#a35f00' });

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
    const j = JSON.parse(t); const R = j.result || j;
    // a deployed set keeps its wall in <set>.wall.json (deploy-site.sh); pages that draw it ask for it with withWall
    if (!R.wall && arguments[1] && arguments[1].withWall) { try { const w = await (await fetch(url.replace(/\.json$/, '.wall.json'))).json(); R.wall = w.wall || w; } catch (e) { R.wall = []; } }
    return R;
  }

  // the map's frame: the city's places plus any extra points (the seven can sit outside the city, e.g. North County).
  // Returns a map-like object for projection() only; the grey dots stay the city's own.
  function frame(M, extra) {
    const ex = (extra || []).filter(p => p && p.lat != null && p.lon != null);
    const top = Math.max(M.latMax || -99, ...ex.map(p => p.lat + 0.004));
    return { ...M, places: (M.frame || M.places).concat(ex.map(p => [p.lon, p.lat])), latMax: M.latMax ? top : undefined };
  }
  // convex hull of the city's places (monotone chain), drawn as a thin line so a dot outside it reads as outside the city
  function hull(points) {
    const P = points.slice().sort((a, b) => a[0] - b[0] || a[1] - b[1]);
    const cr = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
    const lo = [], up = [];
    for (const p of P) { while (lo.length >= 2 && cr(lo[lo.length - 2], lo[lo.length - 1], p) <= 0) lo.pop(); lo.push(p); }
    for (const p of P.slice().reverse()) { while (up.length >= 2 && cr(up[up.length - 2], up[up.length - 1], p) <= 0) up.pop(); up.push(p); }
    return lo.slice(0, -1).concat(up.slice(0, -1));
  }
  function inHull(H, lon, lat) {
    for (let i = 0; i < H.length; i++) {
      const a = H[i], b = H[(i + 1) % H.length];
      if ((b[0] - a[0]) * (lat - a[1]) - (b[1] - a[1]) * (lon - a[0]) < 0) return false;
    }
    return true;
  }
  // the city line: drawn only when some of the given points fall outside the city's hull
  function cityLine(ctx, M, P, pts, color = '#3a3935') {
    const H = hull(M.places);
    if (!(pts || []).some(p => p && p.lat != null && !inHull(H, p.lon, p.lat))) return false;
    ctx.save(); ctx.strokeStyle = color; ctx.lineWidth = 1; ctx.setLineDash([3, 4]); ctx.beginPath();
    H.forEach(([lo, la], i) => { const [x, y] = P(lo, la); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
    ctx.closePath(); ctx.stroke(); ctx.restore();
    return true;
  }
  // the first of several data files that exists (live results first, then the MOCK fallback)
  async function firstOf(urls) {
    for (const u of urls) { try { const r = await fetch(u, { method: 'GET' }); if (r.ok) return u; } catch (e) { /* next */ } }
    return urls[urls.length - 1];
  }
  // a wall name as people read it: "Pork steak and ribs BBQ at Pappy's Smokehouse" -> "Pappy's Smokehouse",
  // "Gioia's Deli (hot salami sandwich)" -> "Gioia's Deli". Same rule as build_data.py clean(); display only.
  function cleanName(n) {
    if (!n) return n;
    let s = String(n).replace(/\s*\(.*?\)\s*/g, ' ').trim();
    const m = s.match(/^.+? at (.+)$/);
    if (m && m[1].split(' ').length <= 5 && !/^(jazz|lounge) at/i.test(s)) s = m[1];
    return s;
  }
  // loves AS TYPED ("Frankie Beverly & Maze"), never Qloo's entity name ("Maze Featuring Frankie Beverly"), which
  // belongs in the raw log only. Sources, in order: the love's own `text`, R.typed (a stored set), the caller's list.
  function typedLoves(R, fallback) {
    const t = (R && R.typed) || [];
    return ((R && R.loves) || []).map((l, i) => ({ ...l, qloo_label: l.label, label: l.text || t[i] || (fallback && fallback[i]) || l.label }));
  }
  function typedName(R, label, fallback) {
    const x = typedLoves(R, fallback).find(l => l.qloo_label === label);
    return x ? x.label : label;
  }
  const WORDS = ['no', 'one', 'two', 'three', 'four', 'five'];
  // the dead-love line: a tag love tied at Qloo's default reads as a tie; a love that only follows popularity, §2.2
  function deadLine(l, city, nLive) {
    const w = WORDS[nLive] || nLive, T = l.label.charAt(0).toUpperCase() + l.label.slice(1);
    const tie = l.kind === 'tag' && /^ties/.test(l.dead_reason || '');
    return tie ? `${T}: Qloo scores every place here the same on it, so your other ${w} did the ranking.`
      : `${l.label} doesn’t change ${city} restaurants much; ranked on the other ${w}.`;
  }
  // a day, never a run time: "27 Oct"; a span of days: "27–28 Oct"
  function day(iso) {
    if (!iso) return null;
    return new Intl.DateTimeFormat('en-GB', { timeZone: 'America/New_York', day: 'numeric', month: 'short' }).format(new Date(iso));
  }
  function days(isos) {
    const d = (isos || []).filter(Boolean).sort();
    if (!d.length) return null;
    const a = day(d[0]), b = day(d[d.length - 1]);
    if (a === b) return a;
    const [da, ma] = a.split(' '), [db, mb] = b.split(' ');
    return ma === mb ? `${da}–${db} ${mb}` : `${a} – ${b}`;
  }

  // provider codes in the data -> the assistant's name on screen
  const PROVIDERS = { anthropic: 'Claude', claude: 'Claude', openai: 'ChatGPT', codex: 'ChatGPT', chatgpt: 'ChatGPT', google: 'Gemini', gemini: 'Gemini' };
  // "openai" -> "ChatGPT"; "gemini (live)" -> "Gemini (live)"
  const provider = p => { if (p == null) return p; const m = String(p).match(/^([A-Za-z]+)(.*)$/); const n = m && PROVIDERS[m[1].toLowerCase()]; return n ? n + m[2] : (PROVIDERS[String(p).toLowerCase()] || p); };

  // "Zushi Sushi and Ramen - S Laclede" -> "Zushi Sushi and Ramen": a trailing " - <street or area>" is dropped for display
  // when it starts with a compass letter, names a street type, or is the card's own neighbourhood. Matching keeps the raw name.
  const STREETY = /\b(st|street|ave|avenue|blvd|boulevard|rd|road|dr|drive|pkwy|parkway|hwy|highway|ln|lane|way|pl|place|ct|sq)\b\.?/i;
  function shortName(name, hood) {
    const s = String(name || ''), m = s.match(/^(.+?)\s+[-–—]\s+([^-–—]+)$/);
    if (!m) return s;
    const tail = m[2].trim();
    const area = /^[NSEW]\.?\s/.test(tail) || STREETY.test(tail) || (hood && tail.toLowerCase() === String(hood).toLowerCase());
    return area && m[1].trim().length >= 3 ? m[1].trim() : s;
  }
  // the area: in St. Louis, a place whose address is in another municipality ("8017 Airport Rd Berkeley, MO") shows that
  // municipality; otherwise Qloo's neighbourhood. One function for the site's cards and the share image.
  const STREET_T = /^(st|street|ave|avenue|blvd|boulevard|rd|road|dr|drive|pkwy|parkway|hwy|highway|ln|lane|way|pl|place|ct|ter|trl|cir|plz|plaza|sq|center|ctr|mall|\d+\w*)\.?$/i;
  // an address as people read it: Qloo sometimes repeats a place type in short form ("Shopping Center Shop Ctr") or a
  // word ("St. Louis St. Louis"); the repeat goes, the street and the town stay
  function cleanAddr(a) {
    let s = String(a || '').replace(/\s+/g, ' ').trim();
    [[/Shopping Cent(?:er|re)/i, /\s+Shop(?:ping)?\.? Ctr\.?(?=[\s,])/i], [/\bPlaza\b/i, /\s+Plz\.?(?=[\s,])/i], [/\bCent(?:er|re)\b/i, /\s+Ctr\.?(?=[\s,])/i]]
      .forEach(([full, short]) => { if (full.test(s)) s = s.replace(short, ''); });
    return s.replace(/\b([A-Z][\w.']+(?: [A-Z][\w.']+)?) \1(?=[\s,]|$)/g, '$1');
  }
  function municipality(addr) {
    const m = cleanAddr(addr).match(/^(.*?),\s*[A-Z]{2}\s+\d{5}/); if (!m) return null;
    const head = m[1].trim();
    if (/\bst\.?\s+louis$/i.test(head)) return 'St. Louis';
    const t = head.split(/\s+/); let k = t.length;
    while (k > 0 && !STREET_T.test(t[k - 1])) k--;
    const city = t.slice(k).join(' ');
    return k > 0 && city ? city : null;
  }
  function area(c, citySlug) {
    const mu = citySlug === 'st-louis' ? municipality(c.address) : null;
    return mu && mu !== 'St. Louis' ? mu : (c.neighbourhood || c.area || null);
  }

  window.UM = { area, cleanAddr, shortName, typedLoves, typedName, deadLine, day, days, cleanName, frame, hull, inHull, cityLine, firstOf, provider, C, canvas, projection, discD, dots, disc, seven, ring, stack, leader, el, esc, fmt, ph, param, et, hhmm, json, result };
})();
