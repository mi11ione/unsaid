/* UNSAID · the share image, 1080×1350, dark, drawn client-side on a canvas (UNSAID.md §2.1).
   "The AIs named WALL places. None named these 7."; the loves at 32 px; the struck wall as texture on
   the left, the seven with what each is on the right; footer "ranked by Qloo for what fits you · date" and the site's address.
   data: a result (CONTRACT.md) plus optional wallNames (struck names) and picks override. */
(function () {
  const C = { bg: '#0b0b0b', ink: '#ecebe5', white: '#f2efe6', dim: '#8e8c85', faint: '#55534e', red: '#ff2d3d', amber: '#e2a336', rule: '#34332e' };
  const SERIF = "'Iowan Old Style', 'Palatino Linotype', Palatino, Georgia, serif";
  const MONO = "ui-monospace, 'SF Mono', SFMono-Regular, Menlo, Consolas, monospace";

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
    ctx.fillStyle = C.bg; ctx.fillRect(0, 0, W, H);
    ctx.textBaseline = 'alphabetic';
    const fake = (R.flags || []).includes('fake');
    const picks = R.picks || [];
    const N = picks.length;
    const WALL = wallCount(R);

    // mark
    ctx.font = `700 22px ${MONO}`; ctx.fillStyle = C.ink;
    let x = pad; const my = 96;
    'UNSAID'.split('').forEach(ch => { ctx.fillText(ch, x, my); x += ctx.measureText(ch).width + 7; });
    const unW = ctx.measureText('UN').width + 7;
    ctx.fillStyle = C.ink; ctx.fillRect(pad - 1, my - 9, unW, 3);   // the logo's strike is ours: ink
    if (fake) {
      ctx.font = `14px ${MONO}`; const t = 'MOCK DATA · NOT REAL CARDS', tw = ctx.measureText(t).width;
      ctx.strokeStyle = C.amber; ctx.setLineDash([4, 3]); ctx.strokeRect(W - pad - tw - 24, my - 22, tw + 24, 30); ctx.setLineDash([]);
      ctx.fillStyle = C.amber; ctx.fillText(t, W - pad - tw - 12, my - 2);
    }

    // headline
    let y = 210;
    ctx.font = `400 58px ${SERIF}`;
    if (R.hero && R.hero.gem) {
      // the site's hero: "AI sends everyone to ~~Mai Lee~~." + its receipt, then "None named these 7."
      const pre = 'AI sends everyone to ', g = R.hero.gem, fits = ctx.measureText(pre + g + '.').width <= W - 2 * pad;
      ctx.fillStyle = C.ink; ctx.fillText(fits ? pre : pre.trim(), pad, y);
      let gx = pad + ctx.measureText(pre).width, gy = y;
      if (!fits) { gx = pad; gy = y + 68; }
      ctx.fillStyle = C.red; ctx.fillText(g, gx, gy);
      const gw = ctx.measureText(g).width;
      ctx.fillRect(gx - 2, gy - 19, gw + 4, 4);
      ctx.fillStyle = C.ink; ctx.fillText('.', gx + gw, gy);
      y = gy + 50;
      if (R.hero.receipt) { ctx.font = `20px ${MONO}`; ctx.fillStyle = C.red; ctx.fillText(R.hero.receipt, pad, y); y += 74; } else y += 24;
      ctx.font = `400 58px ${SERIF}`; ctx.fillStyle = C.white; ctx.fillText(`None named these ${N}.`, pad, y);
      y += 70;
    } else {
    // "The AIs named WALL places." (wallCount of this result)
    const a = 'The AIs named ', wtxt = WALL == null ? '' : Number(WALL).toLocaleString('en-US');
    const l1 = wrap(ctx, a + wtxt + ' places.', W - 2 * pad);
    // draw line 1 with the number in red (the number is at the end of the sentence)
    l1.forEach((line, i) => {
      // the count is red wherever the wrap puts it
      const yy = y + i * 68, k = line.indexOf(wtxt);
      if (k < 0) { ctx.fillStyle = C.ink; ctx.fillText(line, pad, yy); return; }
      const pre = line.slice(0, k), post = line.slice(k + wtxt.length);
      ctx.fillStyle = C.ink; ctx.fillText(pre, pad, yy);
      const px = pad + ctx.measureText(pre).width;
      ctx.fillStyle = WALL == null ? C.amber : C.red; ctx.fillText(wtxt, px, yy);
      ctx.fillStyle = C.ink; ctx.fillText(post, px + ctx.measureText(wtxt).width, yy);
    });
    y += l1.length * 68;
    ctx.fillStyle = C.white; ctx.fillText(`None named these ${N}.`, pad, y);
    y += 70;
    }

    // the loves, 32 px
    ctx.font = `400 32px ${SERIF}`; ctx.fillStyle = C.dim;
    const loves = (R.loves || []).filter(l => !l.dead).map(l => l.label);
    wrap(ctx, 'for ' + loves.join(' · '), W - 2 * pad).forEach((line, i) => ctx.fillText(line, pad, y + i * 42));
    y += Math.max(1, wrap(ctx, 'for ' + loves.join(' · '), W - 2 * pad).length) * 42 + 26;
    ctx.fillStyle = C.rule; ctx.fillRect(pad, y, W - 2 * pad, 1);
    y += 40;

    // left: the struck wall as texture
    const top = y, bottom = H - 150, colW = 400;
    ctx.save(); ctx.beginPath(); ctx.rect(pad, top - 24, colW, bottom - top + 24); ctx.clip();
    ctx.font = `400 19px ${SERIF}`;
    let wx = pad, wy = top;
    const names = R.wallNames || wallNames(R);
    for (const n of names) {
      const tw = ctx.measureText(n).width;
      if (wx + tw > pad + colW && wx > pad) { wx = pad; wy += 29; }
      if (wy > bottom + 30) break;
      ctx.fillStyle = '#76746d'; ctx.fillText(n, wx, wy);
      ctx.fillStyle = C.red; ctx.globalAlpha = .9; ctx.fillRect(wx - 1, wy - 7, tw + 2, 1.6); ctx.globalAlpha = 1;
      wx += tw + 16;
    }
    ctx.restore();
    const fade = ctx.createLinearGradient(0, bottom - 120, 0, bottom + 10);
    fade.addColorStop(0, 'rgba(11,11,11,0)'); fade.addColorStop(1, 'rgba(11,11,11,1)');
    ctx.fillStyle = fade; ctx.fillRect(pad, bottom - 120, colW + 4, 140);

    // right: the seven with what each is
    const rx = pad + colW + 48, rw = W - pad - rx;
    const rowH = Math.min(96, (bottom - top + 20) / Math.max(1, N));
    picks.forEach((c, i) => {
      const yy = top + i * rowH;
      ctx.font = `14px ${MONO}`; ctx.fillStyle = C.faint; ctx.fillText(String(i + 1).padStart(2, '0'), rx, yy);
      ctx.font = `400 30px ${SERIF}`;
      if (c.name) { ctx.fillStyle = C.white; ctx.fillText(wrap(ctx, c.name, rw - 40)[0], rx + 36, yy + 4); }
      else { ctx.fillStyle = C.faint; ctx.fillText('–', rx + 36, yy + 4); }
      ctx.font = `16px ${MONO}`; ctx.fillStyle = C.dim;
      const what = c.what == null ? '' : c.what;
      ctx.fillText(wrap(ctx, what + (c.neighbourhood ? ' · ' + c.neighbourhood : ''), rw - 36)[0], rx + 36, yy + 34);
    });

    // footer
    ctx.fillStyle = C.rule; ctx.fillRect(pad, H - 112, W - 2 * pad, 1);
    ctx.font = `18px ${MONO}`; ctx.fillStyle = C.dim;
    const d = dateOf(R.diag && R.diag.as_of);
    ctx.fillText(['ranked by Qloo for what fits you', d].filter(Boolean).join(' · '), pad, H - 70);
    // the site's address, so a shared image leads back (R.site: the host the page runs on, else config.site)
    if (R.site) { ctx.font = `600 22px ${MONO}`; ctx.fillStyle = C.ink; const t = String(R.site); ctx.fillText(t, W - pad - ctx.measureText(t).width, H - 70); }
    return cv;
  }

  window.Share = { draw, wallCount, wallNames, tier, hero };
})();
