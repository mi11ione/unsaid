/* UNSAID · the share image, 1080×1350, dark, drawn client-side on a canvas (UNSAID.md §2.1).
   "The AIs told everyone these ⟦WALL⟧. Not one said these 7."; the loves at 32 px; the struck wall as texture on the
   left, the seven with what each is on the right; footer "ranked by Qloo · ⟦date⟧ · UNSAID". Solid red strikes only.
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

  function draw(cv, R) {
    const W = 1080, H = 1350, pad = 72;
    cv.width = W; cv.height = H;
    const ctx = cv.getContext('2d');
    ctx.fillStyle = C.bg; ctx.fillRect(0, 0, W, H);
    ctx.textBaseline = 'alphabetic';
    const fake = (R.flags || []).includes('fake');
    const picks = R.picks || [];
    const N = picks.length;
    const WALL = R.counts && R.counts.wall != null ? R.counts.wall : null;

    // mark
    ctx.font = `700 22px ${MONO}`; ctx.fillStyle = C.ink;
    let x = pad; const my = 96;
    'UNSAID'.split('').forEach(ch => { ctx.fillText(ch, x, my); x += ctx.measureText(ch).width + 7; });
    const unW = ctx.measureText('UN').width + 7;
    ctx.fillStyle = C.red; ctx.fillRect(pad - 1, my - 9, unW, 3);
    if (fake) {
      ctx.font = `14px ${MONO}`; const t = 'MOCK DATA · NOT REAL CARDS', tw = ctx.measureText(t).width;
      ctx.strokeStyle = C.amber; ctx.setLineDash([4, 3]); ctx.strokeRect(W - pad - tw - 24, my - 22, tw + 24, 30); ctx.setLineDash([]);
      ctx.fillStyle = C.amber; ctx.fillText(t, W - pad - tw - 12, my - 2);
    }

    // headline
    let y = 210;
    ctx.font = `400 58px ${SERIF}`;
    // "The AIs told everyone these ⟦WALL⟧ places." (counts.wall of this result)
    const a = 'The AIs told everyone these ', wtxt = WALL == null ? '⟦WALL⟧' : String(WALL);
    const l1 = wrap(ctx, a + wtxt + ' places.', W - 2 * pad);
    // draw line 1 with the number in red (the number is at the end of the sentence)
    l1.forEach((line, i) => {
      const yy = y + i * 68;
      const k = line.lastIndexOf(wtxt);
      if (k >= 0 && line.endsWith(wtxt + ' places.')) {
        const pre = line.slice(0, k);
        ctx.fillStyle = C.ink; ctx.fillText(pre, pad, yy);
        const px = pad + ctx.measureText(pre).width;
        ctx.fillStyle = WALL == null ? C.amber : C.red; ctx.fillText(wtxt, px, yy);
        ctx.fillStyle = C.ink; ctx.fillText(' places.', px + ctx.measureText(wtxt).width, yy);
      } else { ctx.fillStyle = C.ink; ctx.fillText(line, pad, yy); }
    });
    y += l1.length * 68;
    ctx.fillStyle = C.white; ctx.fillText(`Not one said these ${N}.`, pad, y);
    y += 70;

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
    const seenP = new Set(), names = R.wallNames || (R.wall || []).filter(w => w.name && !seenP.has(w.place || w.norm || w.name) && seenP.add(w.place || w.norm || w.name)).map(w => (window.UM ? UM.cleanName(w.name) : w.name));
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
      else { ctx.fillStyle = C.amber; ctx.fillText(`⟦${c._ph || 'place ' + (i + 1)}⟧`, rx + 36, yy + 4); }
      ctx.font = `16px ${MONO}`; ctx.fillStyle = C.dim;
      const what = c.what == null ? '⟦what it is⟧' : c.what;
      ctx.fillText(wrap(ctx, what + (c.neighbourhood ? ' · ' + c.neighbourhood : ''), rw - 36)[0], rx + 36, yy + 34);
    });

    // footer
    ctx.fillStyle = C.rule; ctx.fillRect(pad, H - 112, W - 2 * pad, 1);
    ctx.font = `18px ${MONO}`; ctx.fillStyle = C.dim;
    const d = dateOf(R.diag && R.diag.as_of);
    ctx.fillText(`ranked by Qloo · ${d || '⟦date⟧'} · UNSAID`, pad, H - 70);
    return cv;
  }

  window.Share = { draw };
})();
