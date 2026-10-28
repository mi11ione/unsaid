/* hero.html?v=devpost|tv|phone[&src=<results .ndjson|.json>]   Devpost image 1 (UNSAID.md §1, §6.3).
   Copy of research/round4/proto/image5.html with the Mon-night fixes (§5): "also on 11 of its 14 plain lists";
   the map tally "11 of 14 plain asks"; place names at 24 px over 13 px neighbourhoods; "#4 for you" on card 1's dot;
   callouts for Gioia's and Pappy's only.
   Data: census figures from site/data/census.json (each checked against census_stats.txt by build_data.py);
   the map from site/data/map/stl.json; the seven, their ranks and the loves from the results file (default: the MOCK
   stream). While the results carry flags "fake", the image says MOCK and the white labels are placeholders. */
(async function () {
  const { C, el, esc, fmt } = UM;
  const v = UM.param('v', 'devpost');
  const SRC = (UM.param('src', null) || await UM.firstOf(['data/live/query_stl-cedric.json', '../site/data/mock/stl-cedric.ndjson']));
  const [CEN, M, RES, TRY] = await Promise.all([UM.json('../site/data/census.json'), UM.json('../site/data/map/stl.json'), UM.result(SRC),
    UM.json('../site/data/try.json')]);
  const TYPED = ((TRY.sets || []).find(x => x.id === 'stl-cedric') || {}).loves;   // the loves as typed (data/sets.json)
  const S = CEN.stl;
  // census_stats.txt:58  "Gioia's Deli  13/16"                     -> S.gem.hits / S.gem.of
  // census_stats.txt:46  "Gioia's Deli 11/13/1/5/7" (generic first) -> S.plain.hits = 11
  // census_stats.txt:52  "generic   14 asks"                         -> S.plain.of = 14
  // census_stats.txt:3   "ST. LOUIS: 64 asks"                        -> S.asks.n
  // census_stats.txt:81  "OSM roster: 818 features"                  -> S.osm.n (footer only)
  const fake = (RES.flags || []).includes('fake');
  const picks = RES.picks || [];
  const N = picks.length;
  const TITLE = new Set(['movie', 'tv_show', 'book', 'podcast', 'videogame', 'film', 'show']);
  const tl = c => c && (c.type_label || (c.type ? String(c.type).split(':').pop() : null));
  const loves = UM.typedLoves(RES, TYPED).filter(l => !l.dead).slice().sort((a, b) => TITLE.has(tl(a)) - TITLE.has(tl(b)));
  const lv = l => `<span style="white-space:nowrap">${TITLE.has(tl(l)) ? `<i>${esc(l.label)}</i>` : esc(l.label)}</span>`;
  const LOVES = loves.length ? loves.slice(0, -1).map(lv).join(', ') + (loves.length > 1 ? ' and ' : '') + lv(loves[loves.length - 1]) : UM.ph(null, 'loves');
  const PLACE = (c, i) => c.name ? esc(c.name) : UM.ph(null, `place ${i + 1}`);
  const HOOD = c => c.neighbourhood == null ? UM.ph(null, 'neighbourhood') : esc(c.neighbourhood);   // "" = none known: nothing shown
  const RANK = c => c.fit_rank == null ? null : `<b>#${c.fit_rank}</b> for you`;
  const stage = document.getElementById('stage');
  const ai = M.ai.slice().sort((a, b) => b.count - a.count);
  const cmax = ai[0].count;
  // VAR: 'gioia' (default, "Ask Claude…", Gioia's Deli) or 'mailee' (hero-mailee.html: "Ask an AI…", Mai Lee, both AIs)
  const VAR = window.VARIANT || UM.param('s', 'gioia');
  const CG = S.chatgpt && S.chatgpt.gem;                 // harness/census_stats_codex.txt:59 (9/16), :48 (first in 4)
  const MAI = S.mailee_claude;                            // harness/census_stats_claude.txt:59 (13/16)
  const OUT = (M.outside || []).find(o => o.name === 'Mai Lee');   // real OSM coordinates (media/data/geo.json), or absent
  // mailee: Mai Lee labelled beside its disc, Gioia's with a small strike-label and no number (one number per section)
  const callouts = VAR === 'mailee' ? [OUT, ai.find(a => a.name === S.gem.name)].filter(Boolean) : M.callouts.map(n => ai.find(a => a.name === n)).filter(Boolean);
  // the projection takes in Mai Lee (Brentwood, just west of the city) so it sits in a thin gutter at its real place
  const PM = VAR === 'mailee' && OUT ? { ...M, frame: (M.frame || M.places).concat([[OUT.lon, OUT.lat]]) } : M;
  const gemDisc = callouts[0];
  const short = n => n.replace(/ On The Hill$/i, '');
  const MOCK = fake ? 'mock · white: not real cards yet' : null;
  const WHITE = fake ? 'placeholders, no Qloo ranking yet' : `the ${N}, ranked by Qloo for these loves · ${esc(UM.day(RES.diag && RES.diag.as_of) || '')}`;
  let DRAWN = null;   // grey dots actually inside the drawn map: the footer's count
  const credit = () => esc(M.credit).replace('{n}', DRAWN == null ? (M.places || []).length.toLocaleString('en-US') : DRAWN.toLocaleString('en-US'));
  // the red discs are Claude's census only (sized by Claude's mentions), so the footer says exactly that
  const RED = `<span style="color:var(--red)">red</span>: places ${esc(CEN.provider)} named, sized by mentions (map: ${esc(CEN.provider)}’s census)`;

  function topbar(s, pad) {
    el(stage, 'div', `left:${pad}px;top:${26 * s}px;display:flex;gap:${22 * s}px;align-items:baseline;position:absolute`,
      `<span class="mark" style="font-size:${13 * s}px"><s>UN</s>SAID</span><span class="slug" style="font-size:${10 * s}px">${esc(S.city)} · eat &amp; drink</span>`);
    if (MOCK) el(stage, 'div', `right:${pad}px;top:${22 * s}px;position:absolute;transform:scale(${s});transform-origin:right top`, `<span class="mock">${MOCK}</span>`);
  }

  function map(o) {
    const ctx = UM.canvas(stage, o.W, o.H);
    const P = UM.projection(UM.frame(PM, picks), o.box);   // the seven at their real lat/lon; the frame grows to hold them
    const b = P.bounds;
    // every mapped place within 15 mi, so the seven sit among dots; drawn only inside the map's own area
    const K = o.clip || { x: 0, y: 0, w: o.W, h: o.H };
    ctx.save(); ctx.beginPath(); ctx.rect(K.x, K.y, K.w, K.h); ctx.clip();
    UM.dots(ctx, M, P, { d: o.dotD, alpha: .95, glow: o.glow });
    // soft edges: the 15 mi of dots fade out at the area's sides instead of stopping at a hard line
    const fade = (x0, y0, x1, y1, rx, ry, rw, rh) => { const g = ctx.createLinearGradient(x0, y0, x1, y1);
      g.addColorStop(0, 'rgba(11,11,11,0)'); g.addColorStop(1, 'rgba(11,11,11,1)'); ctx.fillStyle = g; ctx.fillRect(rx, ry, rw, rh); };
    const F = 70 * (o.dotD / 4.2);
    fade(K.x + K.w - F, 0, K.x + K.w, 0, K.x + K.w - F, K.y, F, K.h);
    fade(K.x + F, 0, K.x, 0, K.x, K.y, F, K.h);
    fade(0, K.y + F * .6, 0, K.y, K.x, K.y, K.w, F * .6);
    fade(0, K.y + K.h - F * .6, 0, K.y + K.h, K.x, K.y + K.h - F * .6, K.w, F * .6);
    ctx.restore();
    DRAWN = M.places.filter(([lo, la]) => { const [x, y] = P(lo, la); return x >= K.x && x <= K.x + K.w && y >= K.y && y <= K.y + K.h; }).length;
    ai.slice().reverse().forEach(a => { const [x, y] = P(a.lon, a.lat); UM.disc(ctx, x, y, UM.discD(a.count, cmax, o.dmax, 5)); });
    if (VAR === 'mailee' && OUT) {
      // Mai Lee (Brentwood) at its real coordinates, among the grey dots of the 15 mi map
      const [mx, my] = P(OUT.lon, OUT.lat); UM.disc(ctx, mx, my, UM.discD(OUT.count, cmax, o.dmax, 5));
    }
    if (gemDisc) { const [gx, gy] = P(gemDisc.lon, gemDisc.lat), gr = UM.discD(gemDisc.count, cmax, o.dmax, 5) / 2; UM.ring(ctx, gx, gy, gr + 7 * (o.dotD / 4.2), 1.5 * (o.dotD / 4.2)); }
    const mid = (b.x0 + b.x1) / 2;
    const items = [];
    callouts.forEach((a, i) => {
      const [x, y] = P(a.lon, a.lat);
      const px = i === 0 ? o.gemPx : o.redPx;
      items.push({ kind: 'red', a, top: i === 0, x, y, r: UM.discD(a.count, cmax, o.dmax, 5) / 2, side: x < mid ? 'L' : 'R', px, h: px * (i === 0 ? 2.1 : 1.2) });
    });
    picks.forEach((c, i) => {
      const [x, y] = P(c.lon, c.lat);
      // a right-hand label that would run into the headline column goes to the left side instead
      let side = x < mid ? 'L' : 'R';
      const est = String(c.name || 'place 0').length * o.whitePx * .5;
      if (side === 'R' && o.maxRight && Math.max(b.x1 + (o.colGapR ?? o.colGap), x + o.sevenD / 2 + o.halo + 28) + est > o.maxRight) side = 'L';
      items.push({ kind: 'white', c, i, x, y, r: o.sevenD / 2 + o.halo, side, h: o.whitePx * 1.1 + o.hoodPx * 1.5 });
    });
    UM.stack(items, o.labelTop, o.labelBottom, o.gap || 10);
    const colL = b.x0 - o.colGap, colR = b.x1 + (o.colGapR ?? o.colGap);
    items.forEach(i => {
      const L = i.side === 'L';
      const lx = L ? Math.min(colL, i.x - i.r - 28) : Math.max(colR, i.x + i.r + 28);
      const ly = i.kind === 'red' ? i.ly + i.px * .6 : i.ly + o.whitePx * .5;
      UM.leader(ctx, i.x + (L ? -i.r : i.r), i.y, lx + (L ? 6 : -6), ly, i.kind === 'red' ? C.red : C.white, i.kind === 'red' ? (i.top ? .8 : .5) : .55);
      const css = `top:${i.ly}px;${L ? `right:${o.W - lx}px;text-align:right` : `left:${lx}px`};`;
      if (i.kind === 'red') {
        // the only number on the map: the gem's plain-list tally (census_stats.txt:46, :52)
        const d = el(stage, 'div', css + `font-size:${i.px}px;line-height:${i.px * 1.2}px`,
          `<span class="n">${esc(short(i.a.name))}</span>` + (i.top ? `<div class="t" style="margin:${i.px * .12}px 0 0;font-size:${i.px * .62}px;line-height:1.2">${VAR === 'mailee' ? `<span style="color:var(--dim)">${esc(MAI.hood)}</span>` : `${S.plain.hits} of ${S.plain.of} plain asks`}</div>` : ''));
        d.className = 'lab red' + (i.top ? ' big' : '');
      } else {
        el(stage, 'div', css + `font-size:${o.whitePx}px;line-height:1`,
          `<div class="pn">${PLACE(i.c, i.i)}</div><div class="ph2" style="font-size:${o.hoodPx}px;margin-top:${o.hoodPx * .4}px;color:var(--dim)">${HOOD(i.c)}</div>`).className = 'lab white';
      }
    });
    picks.forEach(c => { const [x, y] = P(c.lon, c.lat); UM.seven(ctx, x, y, 1, o.sevenD, o.halo); });
    // "#4 for you" on card 1's dot (§5): the first card in for-you order carries its rank at the dot itself
    if (picks[0] && RANK(picks[0])) {
      const it = items.find(i => i.kind === 'white' && i.i === 0), [x, y] = P(picks[0].lon, picks[0].lat);
      const L = it.side === 'L';
      el(stage, 'div', `top:${y - o.rankPx * 2.1}px;${L ? `left:${x - o.sevenD}px` : `right:${o.W - x - o.sevenD}px;text-align:right`};font-size:${o.rankPx}px;line-height:1`, RANK(picks[0])).className = 'rank';
    }
    return P;
  }

  function story(parent, w, s, o = {}) {
    const box = el(parent, 'div', `width:${w}px`);
    const BIG = (o.big || 104) * s;
    if (VAR === 'mailee') {
      el(box, 'div', `font-size:${(o.eye || 40) * s}px`, `Ask an AI for a hidden gem in ${esc(S.city).replace(' ', '&nbsp;')}.`).className = 'eyebrow';
      el(box, 'div', `font-size:${BIG}px;margin-top:${26 * s}px`, esc(MAI.name)).className = 'gem';
      // census_stats_claude.txt:59 (13/16) · census_stats_codex.txt:59 (9/16)
      el(box, 'div', `font-size:${(o.tal || 36) * s * .9}px;margin-top:${20 * s}px`,
        `<span class="r">${esc(CEN.provider)}: ${MAI.hits} times out of ${MAI.of}<br>${esc(CEN.chatgpt_provider)}: ${CG.hits} of ${CG.of}</span>`).className = 'tally';
    } else {
      el(box, 'div', `font-size:${(o.eye || 40) * s}px`, `Ask ${esc(CEN.provider)} for a hidden gem in ${esc(S.city).replace(' ', '&nbsp;')}.`).className = 'eyebrow';
      el(box, 'div', `font-size:${BIG}px;margin-top:${26 * s}px`, esc(S.gem.name).replace("'", '’')).className = 'gem';
      // census_stats_claude.txt:58 (13/16) · :46 + :52 (11 of 14) · codex :59 (Mai Lee 9/16) + claude :59 (13/16)
      el(box, 'div', `font-size:${(o.tal || 36) * s}px;margin-top:${20 * s}px`,
        `<span class="r">${S.gem.hits} times out of ${S.gem.of}</span><br><span class="d" style="font-size:.82em">also on ${S.plain.hits} of its ${S.plain.of} plain lists</span>`).className = 'tally';
      if (CG) el(box, 'div', `font-size:${(o.lov || 19) * s * .84}px;margin-top:${14 * s}px;white-space:nowrap`,
        `${esc(CEN.chatgpt_provider)}’s: ${esc(CG.name)}, ${CG.hits} of ${CG.of}` + (MAI && MAI.name === CG.name ? ` · ${esc(CEN.provider)} says it ${MAI.hits} times too` : '')).className = 'loves';
    }
    el(box, 'div', `margin:${(o.gap || 40) * s}px 0 ${(o.gap || 40) * s * .8}px;width:${w * .55}px`).className = 'hr';
    el(box, 'div', `font-size:${BIG}px`, `${N} for you`).className = 'yours';
    el(box, 'div', `font-size:${(o.lov || 19) * s}px;margin-top:${18 * s}px`, `ranked by Qloo for <b>${LOVES}</b>`).className = 'loves';
    return box;
  }

  function footer(x, y, s, w) {
    // census_stats.txt:3 (64 asks), :51 (16 hidden-gem), :52 (14 plain); OSM 818 (:81) is the map's own count
    el(stage, 'div', `position:absolute;left:${x}px;top:${y}px;width:${w}px;font-size:${12 * s}px;white-space:normal;line-height:1.55;color:var(--dim)`,
      `${RED} · census of ${esc(CEN.model)} (pre-registered) and ${esc(CEN.chatgpt_provider)} ${esc(CEN.chatgpt_model)}, no web search, ${S.asks.n} ${esc(S.city)} asks each incl. ${S.gem.of} hidden-gem and ${S.plain.of} plain “where to eat” phrasings, ${esc(CEN.date)}<br>` +
      `${credit()} · <span style="color:var(--white)">white</span>: ${WHITE}`).className = 'attr';
  }

  if (v === 'devpost' || v === 'tv') {
    const tv = v === 'tv';
    const W = tv ? 1920 : 1600, H = tv ? 1080 : 1000, s = tv ? 1.12 : 1, pad = tv ? 56 : 40;
    stage.style.cssText += `width:${W}px;height:${H}px`;
    const split = Math.round(W * .6);   // room for real names at 24 px on both sides of the map
    topbar(s, pad);
    el(stage, 'div', `left:${pad}px;right:${pad}px;top:${54 * s}px`).className = 'rl';
    map({ W, H, box: { x: pad + 190 * s, y: 76 * s, w: split - pad - 380 * s, h: H - 76 * s - 104 * s },
      labelTop: 76 * s, labelBottom: H - 100 * s, redPx: 19 * s, gemPx: 26 * s, whitePx: 24 * s, hoodPx: 13 * s, rankPx: 15 * s, dmax: 38 * s,
      dotD: 4.2 * s, glow: 18 * s, sevenD: 13 * s, halo: 4 * s, colGap: -20 * s, colGapR: 14 * s, gap: 10 * s,
      clip: { x: pad, y: 64 * s, w: split - pad - 20 * s, h: H - 64 * s - 96 * s }, maxRight: split + 24 * s });
    const colX = split + 44 * s, colW = W - colX - pad;
    const holder = el(stage, 'div', `position:absolute;left:${colX}px;top:0`);
    const box = story(holder, colW, s);
    holder.style.top = Math.round(54 * s + (H - 54 * s - 92 * s - box.offsetHeight) / 2) + 'px';
    el(stage, 'div', `left:${pad}px;right:${pad}px;top:${H - 82 * s}px`).className = 'rl';
    footer(pad, H - 70 * s, s, W - 2 * pad);
  }

  if (v === 'phone') {
    const W = 390;
    stage.style.width = W + 'px';
    const top = el(stage, 'div', 'position:relative;padding:18px 16px 0');
    el(top, 'div', 'display:flex;justify-content:space-between;align-items:center',
      `<span class="mark" style="font-size:12px"><s>UN</s>SAID</span>` + (MOCK ? `<span class="mock" style="font-size:8px;height:16px">${MOCK}</span>` : ''));
    const st = el(top, 'div', 'margin-top:22px');
    if (VAR === 'mailee') {
      el(st, 'div', 'font-size:24px', `Ask an AI for a hidden gem in ${esc(S.city).replace(' ', '&nbsp;')}.`).className = 'eyebrow';
      el(st, 'div', 'font-size:58px;margin-top:14px', esc(MAI.name)).className = 'gem';
      el(st, 'div', 'font-size:20px;margin-top:12px', `<span class="r">${esc(CEN.provider)}: ${MAI.hits} times out of ${MAI.of}<br>${esc(CEN.chatgpt_provider)}: ${CG.hits} of ${CG.of}</span>`).className = 'tally';
    } else {
    el(st, 'div', 'font-size:24px', `Ask ${esc(CEN.provider)} for a hidden gem in ${esc(S.city).replace(' ', '&nbsp;')}.`).className = 'eyebrow';
    el(st, 'div', 'font-size:58px;margin-top:14px', esc(S.gem.name).replace("'", '’')).className = 'gem';
    el(st, 'div', 'font-size:18px;margin-top:12px', `<span class="r">${S.gem.hits} times out of ${S.gem.of}</span><br><span class="d">also on ${S.plain.hits} of its ${S.plain.of} plain lists</span>`).className = 'tally';
    }
    if (CG && VAR !== 'mailee') el(st, 'div', 'font-size:12px;margin-top:10px', `${esc(CEN.chatgpt_provider)}’s: ${esc(CG.name)}, ${CG.hits} of ${CG.of}` + (MAI && MAI.name === CG.name ? ` · ${esc(CEN.provider)} says it ${MAI.hits} times too` : '')).className = 'loves';
    const P = UM.projection(UM.frame(PM, picks), { x: 108, y: 12, w: 172, h: 2000 });
    const shift = 12 - P.bounds.y0, mh = Math.round(P.bounds.y1 - P.bounds.y0 + 24);
    const Q = (lon, lat) => { const [x, y] = P(lon, lat); return [x, y + shift]; };
    const mapWrap = el(stage, 'div', `position:relative;height:${mh}px;overflow:hidden;margin-top:8px`);
    const ctx = UM.canvas(mapWrap, W, mh);
    UM.dots(ctx, M, Q, { d: 2.3, alpha: .95, glow: 7 });
    DRAWN = M.places.filter(([lo, la]) => { const [x, y] = Q(lo, la); return x >= 0 && x <= W && y >= 0 && y <= mh; }).length;
    if (VAR === 'mailee' && OUT) { const [mx, my] = Q(OUT.lon, OUT.lat); UM.disc(ctx, mx, my, UM.discD(OUT.count, cmax, 20, 3)); }
    ai.slice().reverse().forEach(a => { const [x, y] = Q(a.lon, a.lat); UM.disc(ctx, x, y, UM.discD(a.count, cmax, 20, 3)); });
    const [gx, gy] = Q(gemDisc.lon, gemDisc.lat), gr = UM.discD(gemDisc.count, cmax, 20, 3) / 2;
    UM.ring(ctx, gx, gy, gr + 4, 1.2);
    const LX = 100, RX = 290, CH = 6.9, LW = { L: 92, R: 86 };
    const mid = (P.bounds.x0 + P.bounds.x1) / 2;
    const lines = (t, side) => Math.ceil(String(t || 'neighbourhood').length * CH / LW[side]);
    const nameLines = (c, side) => Math.ceil(String(c.name || 'place 0').length * 7.6 / LW[side]);   // 14 px serif wraps
    const items = picks.map((c, i) => { const [x, y] = Q(c.lon, c.lat); const side = x < mid ? 'L' : 'R';
      return { c, i, x, y, side, h: nameLines(c, side) * 16 + (c.neighbourhood ? lines(c.neighbourhood, side) * 12 : 0) + 2 }; });
    items.push({ gem: true, x: gx, y: gy, side: 'L', h: 18 });
    UM.stack(items, 4, mh - 4, 8);
    items.forEach(it => {
      const L = it.side === 'L', lx = L ? LX : RX;
      if (it.gem) {
        UM.leader(ctx, gx - gr - 5, gy, lx + 4, it.ly + 9, C.red, .8);
        el(mapWrap, 'div', `top:${it.ly}px;right:${W - lx + 2}px;text-align:right;font-size:14.5px;line-height:18px`, `<span class="n">${esc(gemDisc.name).replace("'", '’')}</span>`).className = 'lab red big';
        return;
      }
      UM.leader(ctx, it.x + (L ? -7 : 7), it.y, lx + (L ? 4 : -4), it.ly + 8, C.white, .5);
      el(mapWrap, 'div', `top:${it.ly}px;${L ? `right:${W - lx + 2}px;text-align:right` : `left:${lx + 2}px`};font-size:11.5px;line-height:13px;white-space:normal;width:${LW[it.side]}px`,
        `<div class="pn" style="font-size:14px;line-height:16px">${PLACE(it.c, it.i)}</div><div style="font-size:9.5px;line-height:12px;color:var(--dim)">${HOOD(it.c)}</div>`).className = 'lab white';
    });
    picks.forEach(c => { const [x, y] = Q(c.lon, c.lat); UM.seven(ctx, x, y, 1, 8, 3); });
    if (picks[0] && RANK(picks[0])) {
      const it = items.find(i => i.i === 0);
      el(mapWrap, 'div', `top:${it.y - 22}px;left:${it.x - 8}px;font-size:10.5px;line-height:1`, RANK(picks[0])).className = 'rank';
    }
    const bot = el(stage, 'div', 'padding:6px 16px 22px');
    el(bot, 'div', 'width:55%;margin:4px 0 18px').className = 'hr';
    el(bot, 'div', 'font-size:58px', `${N} for you`).className = 'yours';
    el(bot, 'div', 'font-size:12.5px;margin-top:10px', `ranked by Qloo for <b>${LOVES}</b>`).className = 'loves';
    el(bot, 'div', 'border-top:1px solid var(--rule2);border-bottom:1px solid var(--rule2);padding:13px 0;margin-top:18px;display:flex;justify-content:space-between;font-size:12px',
      `<span>everything the AI named, <span style="color:var(--red)">crossed out</span></span><span style="color:var(--dim)">show ›</span>`);
    const f = el(bot, 'div', 'font-size:9.5px;margin-top:12px;white-space:normal;line-height:1.5',
      `red: ${esc(CEN.provider)}’s places (map: ${esc(CEN.provider)}’s census) · census of ${esc(CEN.model)} and ${esc(CEN.chatgpt_provider)} ${esc(CEN.chatgpt_model)}, no web search, ${S.asks.n} asks each · ${credit()} · white: ${WHITE}`);
    f.className = 'attr';
    stage.style.height = (top.offsetHeight + mh + 8 + bot.offsetHeight) + 'px';
  }
  window.__ready = true;
})().catch(e => { window.__error = String(e && e.stack || e); window.__ready = true; document.body.insertAdjacentHTML('beforeend', `<pre style="color:#ff2d3d">${e}</pre>`); });
