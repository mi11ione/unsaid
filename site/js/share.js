/* UNSAID · the share image, 1080×1350, on paper, drawn client-side on a canvas (UNSAID.md §2.1).
   the site's hero, its receipt and "None named these 7."; the loves in mono; the struck wall as texture on
   the left, the seven with what each is on the right; footer "ranked by Qloo for what fits you · date" and the site's address.
   data: a result (CONTRACT.md) plus optional wallNames (struck names) and picks override. */
(function () {
  const C = { bg: '#f4f3ee', ink: '#0d0d0c', white: '#0d0d0c', dim: '#5a5954', faint: '#8a8882', red: '#d70412', amber: '#a35f00', rule: '#bdbbb3' };
  const SANS = "Inter, 'Helvetica Neue', Helvetica, Arial, sans-serif";
  const MONO = "'Plex Mono', ui-monospace, 'SF Mono', Menlo, monospace";
  // the image is drawn with the site's own faces: loaded from site/fonts next to this script, then Share.ready resolves
  const base = (document.currentScript && document.currentScript.src) || location.href;
  const face = (fam, file, w) => { try { const f = new FontFace(fam, `url(${new URL('../fonts/' + file, base)})`, { weight: w }); document.fonts.add(f); return f.load(); } catch (e) { return Promise.resolve(); } };
  const ready = Promise.all([face('Inter', 'inter-latin-opsz.woff2', '100 900'), face('Plex Mono', 'plex-mono-400.woff2', '400'),
    face('Plex Mono', 'plex-mono-500.woff2', '500'), face('Plex Mono', 'plex-mono-600.woff2', '600 700')]).catch(() => {});

  function wrap(ctx, text, maxW) {
    const words = text.split(' '), lines = [];
    let cur = '';
    for (const w of words) { const t = cur ? cur + ' ' + w : w; if (ctx.measureText(t).width > maxW && cur) { lines.push(cur); cur = w; } else cur = t; }
    if (cur) lines.push(cur);
    return lines;
  }
  function dateOf(iso) {
    if (!iso) return null;
    return new Intl.DateTimeFormat('en-GB', { timeZone: 'America/New_York', day: 'numeric', month: 'short', year: 'numeric' }).format(new Date(iso));
  }

  // "The AIs named N places": the food-and-drink places only when the engine counts them (counts.named_food_count:
  // no cemeteries or museums), else every distinct place on the wall (counts.wall). null while unknown.
  function wallCount(R) {
    const K = (R && R.counts) || {};
    const v = K.named_food_count ?? (R && R.named_food_count) ?? K.wall;
    return v == null ? null : v;
  }

  // the struck names as texture, most-named first (Mai Lee, Gioia's, Pappy's lead); only the names Qloo says are not a
  // restaurant or bar (a cemetery, a museum) go to the end. One entry per place.
  const tier = w => w.reason === 'not a restaurant or bar' ? 1 : 0;
  function wallNames(R) {
    const by = new Map();
    for (const w of (R && R.wall) || []) {
      if (!w.name) continue;
      const k = w.place || w.norm || w.name, o = by.get(k);
      if (o) { o.n++; if (w.reason === 'not a restaurant or bar') o.reason = w.reason; }
      else by.set(k, { name: w.name, reason: w.reason, n: 1 });
    }
    return [...by.values()].sort((a, b) => tier(a) - tier(b) || b.n - a.n || String(a.name).localeCompare(String(b.name)))
      .map(o => (window.UM ? UM.cleanName(o.name) : o.name));
  }

  // the hero for a city, from census.json only: St. Louis leads with the gem both AIs give (Mai Lee), elsewhere the
  // city's own Claude gem. {gem, receipt: "Claude: 13 of 16 times · ChatGPT: 10 of 16"}
  function hero(CEN, key) {
    const c = CEN && CEN[key]; if (!c) return null;
    const cg = c.chatgpt && c.chatgpt.gem;
    const two = c.mailee_claude && cg && cg.name === c.mailee_claude.name ? c.mailee_claude : null;
    const g = two || c.gem; if (!g) return null;
    return { gem: g.name, city: c.city, receipt: `${CEN.provider}: ${g.hits} of ${g.of} hidden-gem asks` + (two ? ` · ${CEN.chatgpt_provider}: ${cg.hits} of ${cg.of}` : '') };
  }

  function draw(cv, R) {
    const W = 1080, H = 1350, pad = 72;
    cv.width = W; cv.height = H;
    const ctx = cv.getContext('2d');
    const ls = v => { if ('letterSpacing' in ctx) ctx.letterSpacing = v; };   // tracking, where the canvas has it
    ctx.fillStyle = C.bg; ctx.fillRect(0, 0, W, H);
    ctx.textBaseline = 'alphabetic';
    const fake = (R.flags || []).includes('fake');
    const picks = R.picks || [];
    const N = picks.length;
    const WALL = wallCount(R);

    // mark, and a hairline under it
    ctx.font = `600 20px ${MONO}`; ctx.fillStyle = C.ink; ls('5px');
    const my = 92; ctx.fillText('UNSAID', pad, my);
    const unW = (() => { ls('5px'); return ctx.measureText('UN').width; })();
    ls('0px'); ctx.fillRect(pad - 1, my - 8, unW - 4, 2);   // the logo's strike is ours: ink
    if (fake) {
      ctx.font = `14px ${MONO}`; const t = 'MOCK DATA · NOT REAL CARDS', tw = ctx.measureText(t).width;
      ctx.strokeStyle = C.amber; ctx.setLineDash([4, 3]); ctx.strokeRect(W - pad - tw - 24, my - 22, tw + 24, 30); ctx.setLineDash([]);
      ctx.fillStyle = C.amber; ctx.fillText(t, W - pad - tw - 12, my - 2);
    }
    ctx.fillStyle = C.ink; ctx.fillRect(pad, 124, W - 2 * pad, 1.5);

    // headline: "AI sends everyone / to ~~Mai Lee~~." then the receipt, then "None named these 7."
    let y = 252;
    const big = 100, lh = 94;
    ctx.font = `600 ${big}px ${SANS}`; ls('-4.5px');
    if (R.hero && R.hero.gem) {
      const g = R.hero.gem;
      ctx.fillStyle = C.ink; ctx.fillText('AI sends everyone', pad, y);
      y += lh;
      const pre = 'to ', fits = ctx.measureText(pre + g + '.').width <= W - 2 * pad;
      let gx = pad + ctx.measureText(pre).width, gy = y;
      ctx.fillText(pre, pad, y);
      if (!fits) { gx = pad; gy = y + lh; }
      ctx.fillStyle = C.red; ctx.fillText(g, gx, gy);
      const gw = ctx.measureText(g).width;
      ctx.fillRect(gx - 3, gy - big * .34, gw + 2, big * .075);
      ctx.fillStyle = C.ink; ctx.fillText('.', gx + gw, gy);
      y = gy + 58;
      ls('0px');
      if (R.hero.receipt) { ctx.font = `400 22px ${MONO}`; ctx.fillStyle = C.red; ctx.fillText(R.hero.receipt, pad, y); y += 96; } else y += 40;
    } else {
      // "The AIs named WALL places." (wallCount of this result), the count in red
      const wtxt = WALL == null ? '–' : Number(WALL).toLocaleString('en-US');
      ctx.fillStyle = C.ink; ctx.fillText('The AIs named', pad, y); y += lh;
      ctx.fillStyle = WALL == null ? C.amber : C.red; ctx.fillText(wtxt, pad, y);
      ctx.fillStyle = C.ink; ctx.fillText(' places.', pad + ctx.measureText(wtxt).width, y);
      y += 120; ls('0px');
    }
    ctx.font = `600 56px ${SANS}`; ls('-2px'); ctx.fillStyle = C.ink; ctx.fillText(`None named these ${N}.`, pad, y); ls('0px');
    y += 46;

    // the loves
    ctx.font = `400 22px ${MONO}`; ctx.fillStyle = C.dim;
    const loves = (R.loves || []).filter(l => !l.dead).map(l => l.label);
    const LL = wrap(ctx, 'for ' + loves.join(' · '), W - 2 * pad);
    LL.forEach((line, i) => ctx.fillText(line, pad, y + i * 32));
    y += LL.length * 32 + 30;
    ctx.fillStyle = C.ink; ctx.fillRect(pad, y, W - 2 * pad, 1.5);
    y += 48;

    // left: the struck wall as texture; right: the seven, numbered
    const top = y, bottom = H - 138, colW = 360, gut = 48;
    ctx.save(); ctx.beginPath(); ctx.rect(pad, top - 26, colW, bottom - top + 26); ctx.clip();
    ctx.font = `400 19px ${SANS}`;
    let wx = pad, wy = top;
    const names = R.wallNames || wallNames(R);
    for (const n of names) {
      const tw = ctx.measureText(n).width;
      if (wx + tw > pad + colW && wx > pad) { wx = pad; wy += 30; }
      if (wy > bottom + 30) break;
      ctx.fillStyle = C.dim; ctx.fillText(n, wx, wy);
      ctx.fillStyle = C.red; ctx.fillRect(wx - 1, wy - 7, tw + 2, 1.8);
      wx += tw + 16;
    }
    ctx.restore();
    const fade = ctx.createLinearGradient(0, bottom - 140, 0, bottom + 6);
    fade.addColorStop(0, 'rgba(244,243,238,0)'); fade.addColorStop(1, 'rgba(244,243,238,1)');
    ctx.fillStyle = fade; ctx.fillRect(pad, bottom - 140, colW + 4, 148);

    const rx = pad + colW + gut, rw = W - pad - rx;
    ctx.fillStyle = C.rule; ctx.fillRect(rx - gut / 2, top - 26, 1, bottom - top + 26);
    const rowH = Math.min(98, (bottom - top + 20) / Math.max(1, N));
    picks.forEach((c, i) => {
      const yy = top + i * rowH;
      ctx.font = `500 15px ${MONO}`; ctx.fillStyle = C.faint; ctx.fillText(String(i + 1).padStart(2, '0'), rx, yy);
      ctx.font = `600 30px ${SANS}`; ls('-.8px');
      if (c.name) { const nm = window.UM && UM.shortName ? UM.shortName(c.name, c.neighbourhood) : c.name; ctx.fillStyle = C.ink; ctx.fillText(wrap(ctx, nm, rw - 44)[0], rx + 44, yy + 2); }
      else { ctx.fillStyle = C.faint; ctx.fillText('–', rx + 44, yy + 2); }
      ls('0px');
      ctx.font = `400 16px ${MONO}`; ctx.fillStyle = C.dim;
      const what = c.what == null ? '' : c.what;
      const ar = window.UM && UM.area ? UM.area(c, R.city && R.city.slug) : c.neighbourhood;   // the same area as the site's card
      ctx.fillText(wrap(ctx, what + (ar ? ' · ' + ar : ''), rw - 44)[0], rx + 44, yy + 32);
    });

    // footer
    ctx.fillStyle = C.ink; ctx.fillRect(pad, H - 104, W - 2 * pad, 1.5);
    ctx.font = `400 18px ${MONO}`; ctx.fillStyle = C.dim;
    const d = dateOf(R.diag && R.diag.as_of);
    ctx.fillText(['ranked by Qloo for what fits you', d].filter(Boolean).join(' · '), pad, H - 62);
    // the site's address, so a shared image leads back (R.site: the host the page runs on, else config.site)
    if (R.site) { ctx.font = `600 20px ${MONO}`; ctx.fillStyle = C.ink; const t = String(R.site); ctx.fillText(t, W - pad - ctx.measureText(t).width, H - 62); }
    return cv;
  }

  window.Share = { draw, wallCount, wallNames, tier, hero, ready };
})();
