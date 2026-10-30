/* UNSAID · S1 input, S2 run → result, S3 card back, S4 not a popularity filter, share. UNSAID.md §2.
   Every number on screen comes from data (the stream, the result, census.json); a ⟦placeholder⟧ only ever
   stands for a null field. Mock data is always marked MOCK. */
(async function () {
  const { el, esc, et, hhmm } = UM;
  // a null field shows as a quiet dash for visitors; the ⟦bracket⟧ placeholders are for ?mock= development only
  const ph = (v, label) => (v === null || v === undefined) ? (API.FORCE_MOCK ? UM.ph(v, label) : '<span class="faint">–</span>') : esc(v);
  const $ = (s, r = document) => r.querySelector(s);
  const [CFG, CEN, TRY, LIVE, WE] = await Promise.all([UM.json('data/config.json'), UM.json('data/census.json'), UM.json('data/try.json'),
    UM.json('data/live/index.json').catch(() => null), UM.json('data/wall_effect.json').catch(() => null)]);
  const OV = await UM.json('data/overlap.json').catch(() => null);   // similar vs unrelated tastes (build_overlap.py)
  const fmt1 = x => Number.isInteger(+x) ? String(+x) : (+x).toFixed(1);
  // real precomputed sets (site/data/live, uploaded with the deploy) replace the MOCK ones and enable the rest
  if (LIVE && Array.isArray(LIVE.sets)) LIVE.sets.forEach(l => {
    const t = TRY.sets.find(x => x.id === l.id); if (!t || !l.file || l.fake) return;
    Object.assign(t, { src: 'data/live/' + l.file, mock: false, ran: l.ran_at || l.as_of || null });
  });
  API.ping(); // wake the engine while the visitor types (§3.9)
  const view = $('#view'), topEl = $('#top');
  const WORD = ['no', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine'];
  const word = (n, cap) => { const w = WORD[n] ?? String(n); return cap ? w[0].toUpperCase() + w.slice(1) : w; };
  const TITLE = new Set(['movie', 'tv_show', 'book', 'podcast', 'videogame', 'film', 'show']);
  const isPhone = () => matchMedia('(max-width: 720px)').matches;
  // a chip's kind for people: the server's type_label ("artist"), else the tail of a Qloo URN
  const tl = c => c && (c.type_label || (c.type ? String(c.type).split(':').pop() : null));
  // what tells two matches apart: the type, and the year or address when Qloo gives one ("film, 1988")
  const kindOf = c => [tl(c) || c.kind, c.disamb].filter(Boolean).map(esc).join(', ');
  const urlTok = (() => { const t = new URLSearchParams(location.search).get('token'); return t ? `token=${encodeURIComponent(t)}&` : ''; })();
  let ctl = null;

  function topbar({ city, loves, mock } = {}) {
    topEl.innerHTML = `<a class="mark" href="#/"><s>UN</s>SAID</a>` +
      (city ? `<span class="slug">${esc(city)}<span class="rest"> · eat &amp; drink</span></span>` : '') +
      (loves ? `<span class="chips">${loves.map(l => `<span class="chip${l.dead ? ' dead' : ''}">${l.label == null ? ph(null, 'love') : esc(l.label)}${tl(l) ? ` <i>${esc(tl(l))}</i>` : ''}</span>`).join('')}</span>` : '') +
      `<span class="grow"></span>` + (mock ? `<span class="mock">${esc(mock)}</span>` : '');
  }

  // a preset is named by its loves, never by a person: "Frankie Beverly & Maze · The Original Kings of Comedy · rib tips"
  // (the middle love truncates on a phone)
  const lovesLabel = s => { const L = (s.loves || []).filter(Boolean); return L.map((l, i) => `<span class="${i === 1 && L.length > 2 ? 'lmid' : 'l'}">${esc(l)}</span>`).join(' · '); };
  // the presets as two chips ("Or open one:"): each city's first set in data/try.json
  function presetChips(head = 'Or open one:', skip = null) {
    // skip: the set the landing's photo strip already opens; its city's chip is dropped (one way in per city)
    const sk = skip && TRY.sets.find(s => s.id === skip);
    const ok = TRY.sets.filter(s => s.src && !s.mock && !(sk && s.city === sk.city));
    const pick = [...new Set(ok.map(s => s.city))].map(c => ok.find(s => s.city === c));
    return `<div class="try"><span class="dim">${esc(head)}</span> ${pick.map(x => `<a class="pchip" href="#/r?set=${encodeURIComponent(x.id)}">${lovesLabel(x)}</a>`).join('')}</div>`;
  }
  const tryList = (head = 'Or open one:') => presetChips(head || 'Or open one:');

  // ------------------------------------------------------------------ S1 · input
  const FIELDS = [
    { ph: 'an artist you’d play loud', hint: 'artist' },
    { ph: 'a film or show you can quote', hint: 'movie' },
    { ph: 'something you’d order', hint: null },
  ];
  const s1 = { loves: [null, null, null], city: null };
  // the two cities with collected AI answers (a city with none would have nothing to cross out): a choice, not a search
  // how the seven are chosen, in one line (D's selection score, 28 Oct): the card sheet and the popularity sheet carry it
  const EXPLAIN = 'Qloo scores every place for each of your loves. We keep the places that fit you much more than they fit most people’s taste, or than their popularity alone would say.';
  const CITIES = Object.entries(CFG.cities).map(([slug, c]) => ({ slug, name: c.name }));
  // the hero (one idea, said once): "AI sends everyone to ~~Mai Lee~~." + its receipt, from census.json (Share.hero)
  function heroBlock() {
    const H = Share.hero(CEN, 'stl'); if (!H) return '';
    return `<h1>AI sends everyone to <span class="gx">${esc(H.gem)}</span>.</h1><p class="receipt">${H.receipt.split(' · ').map(x => `<span class="ri">${esc(x)}</span>`).join(' · ')}</p>
      <p class="subline">Tell us an artist, a show and a dish you love. We’ll send you where it didn’t.</p>`;
  }

  function inputView() {
    if (ctl) { ctl.abort(); ctl = null; }
    topbar({});
    view.innerHTML = `<div class="land"><section class="s1">
      ${heroBlock()}
      <div class="fields">
        ${FIELDS.map((f, i) => `<div class="fld"><span class="n">0${i + 1}</span><input data-i="${i}" placeholder="${esc(f.ph)}" autocomplete="off" spellcheck="false"><div class="res" id="res${i}"></div></div>`).join('')}
      </div>
      <div class="fields"><div class="fld"><span class="n">in</span><div class="cityopts" role="radiogroup" aria-label="city">${CITIES.map(c => `<button role="radio" aria-checked="false" data-c="${esc(c.slug)}">${esc(c.name)}</button>`).join('')}</div></div></div>
      <div class="go"><button class="btn solid" id="cross" disabled>Find my seven</button></div>
      ${presetChips('Or open one:', 'stl-cedric')}
      <div class="thumbs" id="thumbs"></div>
    </section></div>`;
    view.querySelectorAll('input[data-i]').forEach(inp => {
      const i = +inp.dataset.i;
      if (s1.loves[i]) { inp.value = s1.loves[i].text; drawLove(i); }
      inp.addEventListener('blur', () => resolveLove(i, inp.value));
      inp.addEventListener('input', () => { if (s1.loves[i] && s1.loves[i].text !== inp.value) { s1.loves[i] = null; drawLove(i); } });
    });
    view.querySelectorAll('.cityopts button').forEach(b => b.addEventListener('click', () => {
      const c = CITIES.find(x => x.slug === b.dataset.c);
      s1.city = { text: c.name, city: { slug: c.slug, name: c.name } }; drawCity();
    }));
    drawCity();
    $('#cross').addEventListener('click', go);
    gate();
    thumbStrip();
  }
  // one visual: Cedric's seven as photos with names, opening his set (only the cards that have a photo)
  async function thumbStrip() {
    const set = TRY.sets.find(s => s.id === 'stl-cedric');
    if (!$('#thumbs') || !set || !set.src || set.mock) return;
    try {
      const R = await UM.result(set.src);
      const ph = (R.picks || []).filter(c => httpUrl(c.image));
      if (ph.length < 4) return;
      $('#thumbs').innerHTML = `<a class="thead" href="#/r?set=stl-cedric"><span class="tl">${lovesLabel(set)}</span><span class="dim">seven in ${esc((CFG.cities[set.city] || {}).name || '')} →</span></a>
        <a class="trow" href="#/r?set=stl-cedric" aria-label="Open the seven for ${esc(set.loves.filter(Boolean).join(', '))}">${ph.map(c => `<figure><img src="${esc(c.image)}" alt="" loading="eager" onerror="this.parentNode.remove()" onload="if(this.naturalWidth<100)this.parentNode.remove()"><figcaption>${esc(UM.shortName(c.name, c.neighbourhood))}</figcaption></figure>`).join('')}</a>`;
    } catch (e) { /* the landing works without it */ }
  }
  // a link we share or copy never carries the API token (it lives only in the visitor's own address bar)
  function shareUrl(href = location.href) {
    const u = new URL(href);
    u.searchParams.delete('token');
    const [h, q] = u.hash.split('?');
    if (q && new URLSearchParams(q).has('token')) { const p = new URLSearchParams(q); p.delete('token'); u.hash = h + (p.toString() ? '?' + p : ''); }
    return u.toString();
  }
  const siteHost = () => location.protocol.startsWith('http') && !/^(127\.|localhost)/.test(location.host) ? location.host : (CFG.site || '');

  async function resolveLove(i, text) {
    text = text.trim();
    if (!text) { s1.loves[i] = null; return drawLove(i); }
    if (s1.loves[i] && s1.loves[i].text === text) return;
    s1.loves[i] = { text, pending: true };
    drawLove(i);
    const r = await API.resolve('love', text, FIELDS[i].hint);
    if (!s1.loves[i] || s1.loves[i].text !== text) return;
    s1.loves[i] = { text, r, chip: r.status === 'ok' ? r.chip : null, open: false };
    drawLove(i);
  }
  function drawLove(i) {
    const box = $('#res' + i); if (!box) return;
    const L = s1.loves[i];
    if (!L) box.innerHTML = '';
    else if (L.pending) box.innerHTML = '<span class="faint">looking up…</span>';
    else if (L.chip) {
      const alts = (L.r.alternatives || []);
      // "Sade · artist · Chillout, Soul": the type once, then what tells it apart (the disamb without its type)
      const ty = tl(L.chip), rest = String(L.chip.disamb || '').split(/,\s*/).filter(x => x && (!ty || x.toLowerCase() !== String(ty).toLowerCase())).join(', ');
      box.innerHTML = `<span class="chip lovechip">${esc(L.chip.label)} · ${ty ? esc(ty) : 'as typed'}${rest ? ` · <span class="dim">${esc(rest)}</span>` : ''}</span>` +
        (alts.length ? `<button data-a="toggle">other matches</button>` : '') + (L.r.mock ? '<span class="mock">mock</span>' : '') +
        (L.open ? `<span class="alts">${alts.map((a, k) => `<button data-a="${k}">${esc(a.label)} (${kindOf(a)})</button>`).join('')}</span>` : '');
    } else if (L.r.status === 'needs_input') {
      // amber chip: "rib tips → Rib tips (dish)? · other"
      const c = L.r.chip, alts = L.r.alternatives || [];
      box.innerHTML = `<span class="need">${esc(L.text)} → <button data-a="accept">${esc(c.label)} (${kindOf(c)})?</button> · <button data-a="toggle">other</button></span>` +
        (L.r.mock ? '<span class="mock">mock</span>' : '') +
        (L.open ? `<span class="alts">${alts.map((a, k) => `<button data-a="${k}">${esc(a.label)} (${kindOf(a)})</button>`).join('')}</span>` : '');
    } else if (L.r.status === 'unauthorized') box.innerHTML = '<span class="need">needs the token from the testing instructions: add ?token=… to this page’s address</span>';
    else box.innerHTML = `<span class="need">${esc(L.text)}: not found · try the full name</span>`;
    box.querySelectorAll('button').forEach(b => b.addEventListener('mousedown', e => e.preventDefault()));
    box.querySelectorAll('button').forEach(b => b.addEventListener('click', () => {
      const a = b.dataset.a;
      if (a === 'toggle') L.open = !L.open;
      else if (a === 'accept') { L.chip = L.r.chip; L.open = false; }
      else { L.chip = L.r.alternatives[+a]; L.open = false; }
      drawLove(i);
    }));
    gate();
  }

  function httpUrl(u) { return typeof u === 'string' && /^https?:\/\//i.test(u.trim()); }   // never javascript:, data:, …

  function drawCity() {
    view.querySelectorAll('.cityopts button').forEach(b => { const on = !!(s1.city && s1.city.city && s1.city.city.slug === b.dataset.c); b.classList.toggle('on', on); b.setAttribute('aria-checked', on); });
    gate();
  }
  function gate() {
    const b = $('#cross'); if (!b) return;
    b.disabled = !(s1.loves.every(l => l && l.chip) && s1.city && s1.city.city);
  }
  function go() {
    const loves = s1.loves.map(l => ({ ...l.chip, typed: l.text }));
    const c = s1.city.city;
    location.hash = `#/r?city=${encodeURIComponent(c.slug || c.disamb || c.name)}&cn=${encodeURIComponent(c.name)}&l=${encodeURIComponent(JSON.stringify(loves))}`;
  }

  // ------------------------------------------------------------------ S2 · run → result
  async function resultView(q) {
    if (ctl) { ctl.abort(); ctl = null; }
    let slug = q.get('city'), cityName = q.get('cn'), loves = [], src = null, set = null;
    if (q.get('set')) {
      set = TRY.sets.find(s => s.id === q.get('set'));
      if (!set) { location.hash = '#/'; return; }
      slug = set.city; src = set.src;
      loves = set.loves.map(l => ({ id: null, label: l, kind: 'text', type: null }));
    } else {
      try { loves = JSON.parse(q.get('l') || '[]'); } catch (e) { loves = []; }
    }
    const cc = CFG.cities[slug] || null;
    cityName = cityName || (cc && cc.name) || slug;
    const TYPED = set ? set.loves : loves.map(l => l.typed || l.label);         // the loves as the visitor typed them
    // a love's name on screen: the typed text when it equals Qloo's label but for case -> Qloo's label ("succession" ->
    // "Succession"); typed text with any capital -> as typed ("Frankie Beverly & Maze"); all lower case and different ->
    // Qloo's label. A preset shows its own love text.
    const loveName = (typed, label) => {
      if (set) return typed || label;
      if (!typed || !label) return label || typed;
      if (typed.trim().toLowerCase() === String(label).trim().toLowerCase()) return label;
      return /\p{Lu}/u.test(typed) ? typed.trim() : label;
    };
    const tLoves = () => st.result && Array.isArray(st.result.loves) && st.result.loves.length
      ? st.result.loves.map((l, i) => ({ ...l, qloo_label: l.label, label: loveName(TYPED[i], l.label) }))
      : loves.map((l, i) => ({ ...l, label: loveName(TYPED[i], l.label) }));
    const tName = label => { const x = tLoves().find(l => l.qloo_label === label); return x ? x.label : label; };
    const cen = cc && CEN[cc.census];
    if (!src) await API.ping();   // a stored set never waits on the engine: it opens at once

    const st = {
      slug, cityName, loves, wall: new Map(), asks: new Map(), U: null, calls: null, cards: new Map(), result: null, status: null,
      burned: [], struck: new Map(), slots: [], reserves: [], risen: new Map(), done: false, fake: false,
      mock: false, t0: Date.now(), firstServerEvent: false, order: [], fresh: !src,
    };
    topbar({ city: cityName, loves: tLoves() });
    view.innerHTML = `<div class="res" id="res">
      <div class="maphead" id="maphead"></div>
      <div class="xstrip" id="xstrip"><button class="link" id="xall"></button></div>
      <div class="status" id="status"><span class="live"></span><span id="stxt"></span></div>
      <div class="note" id="notes"></div>
      <section class="sec" id="s-left" hidden>
        <div id="leftbody"></div>
      </section>
      <div class="burnline" id="burn"></div>
    </div>`;
    $('#xall').addEventListener('click', wallSheet);

    // ---- map header
    const mapData = cc && cc.map ? await UM.json(cc.map).catch(() => null) : null;
    let mapDraw = () => {};
    if (mapData && cen) mapDraw = mapHeader($('#maphead'), mapData, cen, st);
    window.addEventListener('resize', () => mapDraw(), { passive: true });

    // ---- the field
    // every name the AIs gave, one entry per place: kept off the page, shown in the "all N, crossed out" sheet
    const fieldEl = document.createElement('div'); fieldEl.className = 'field';
    const wn = w => w.name ? esc(UM.cleanName(w.name)) : ph(null, w.ph || 'name');  // a wall item with no name is a fictional placeholder (mock)
    function addAsk(w) {
      const key = (w.provider || '') + '|' + (w.phrasing_id || '') + '|' + (w.asked_at || '');
      if (!st.asks.has(key)) st.asks.set(key, { provider: UM.provider(w.provider), model: w.model, phrasing: w.phrasing, phrasing_id: w.phrasing_id, asked_at: w.asked_at, lane: w.lane, names: 0 });
      st.asks.get(key).names++;
    }
    // one entry per place: the result's `place` key merges spellings ("Gioia's Deli (hot salami)" = "Gioia's Deli")
    const wk = w => w.place || w.norm || Matcher.norm(w.name || '');
    function addName(w) {
      w = { ...w, provider: UM.provider(w.provider) };
      const k = wk(w);
      addAsk(w);
      const ak = (w.provider || '') + '|' + (w.phrasing_id || '') + '|' + (w.asked_at || '');
      if (st.wall.has(k)) {
        const o = st.wall.get(k); o.n = (o.n || 1) + 1; o.hits.set(ak, w);
        if (o.lane !== 'live' && w.lane === 'live') { o.lane = 'live'; o.el.classList.add('live'); }
        return;
      }
      const o = { ...w, key: k, n: 1, outcome: null, hits: new Map([[ak, w]]) };
      o.el = el(fieldEl, 'span', null, `<button title="">${wn(w)}</button>`);
      o.el.className = 'nm x' + (w.lane === 'live' ? ' live' : '');
      o.el.querySelector('button').addEventListener('click', () => nameSheet(o));
      st.wall.set(k, o);
    }
    function setOutcome(k, outcome, reason, qid) {
      const o = st.wall.get(k); if (!o) return;
      o.outcome = outcome; o.reason = reason; o.qloo_id = qid ?? o.qloo_id;
      // every name the AIs gave is crossed out; the ones that were in this person's Qloo pool (and so cost a card) stand out
      o.el.classList.toggle('inpool', outcome === 'struck');
    }
    // most-named first: the first names on the list are the ones every AI gives everyone
    function sortField() {
      const items = [...st.wall.values()].sort((a, b) => b.hits.size - a.hits.size || String(a.name).localeCompare(String(b.name)));
      items.forEach(o => fieldEl.appendChild(o.el));
    }

    // the dated city wall streams from static data first (within 1 s), whatever the engine is doing
    if (cc && cc.wall) {
      UM.json(cc.wall).then(W => {
        const names = W.answers.flatMap(a => a.names.map(n => ({ name: n, provider: a.provider, model: a.model, phrasing_id: a.phrasing_id, phrasing: a.phrasing, asked_at: a.asked_at, lane: a.lane })));
        // dated names are not happening now: they appear at once, without a landing animation
        if (!st.reconciled) { names.forEach(addName); sortField(); counter(); status(); }
      }).catch(() => {});
    }

    // ---- counters, status, notes
    const liveIds = () => st.slots.filter(id => !st.struck.has(id));
    // the strip under the hero: one line of struck names, most-named first, and the final count (held until the result:
    // the streamed names are spellings the result merges into places, so a running count would go down)
    // the link to every place the AIs named (the final count only: held until the result). Phone: one sentence.
    function counter() {
      const W = st.result ? Share.wallCount(st.result) : null;
      const a = $('#xall'); if (!a) return;
      // the thesis in one line: half of Claude's mentions here go to K50 places (census.json), then the whole list
      const K = cen && cen.k50 && cen.k50.n;
      a.innerHTML = W == null ? (st.wall.size ? 'counting the places the AIs named…' : '')
        : (K ? `Half of what ${esc(CEN.provider)} recommends here is the same ${K} places. ` : '') + `All ${W.toLocaleString('en-US')} places the AIs named, crossed out →`;
    }
    // the full list, in a sheet: every place the AIs named, crossed out
    function wallSheet() {
      const W = st.result ? Share.wallCount(st.result) : null, K = st.result && st.result.counts;
      openSheet(`<div class="cap">${esc(cityName)}</div><h1>${W != null ? W.toLocaleString('en-US') + ' ' : ''}places the AIs named</h1>
        <p class="dim">${K && K.asks ? `In ${K.asks} asks. ` : ''}Good places, all crossed out. Most-named first; tap one to see who named it.</p><div class="wallbox"></div>`);
      const box = document.querySelector('.sheet .wallbox');
      sortField(); box.appendChild(fieldEl);
    }
    function statusLine() {
      const s = st.status && st.status.state;
      const R = st.result, D = R && R.diag;
      // the server's own §2.2 copy wins when it sends it (status events' text, result.notes); otherwise the same copy is built here
      const SERVER_STATES = ['queued', 'waking', 'dated_only', 'partial', 'degraded', 'limited', 'ranking', 'unsupported_city'];
      if (s === 'unauthorized') return 'needs the token from the testing instructions: add ?token=… to this page’s address';
      // after Qloo's last call the engine still checks the streets and asks one AI live (several seconds): say so
      const ranked = !st.done && st.fresh && (st.order.length || (st.U != null && st.calls && st.calls.total != null && st.calls.done >= st.calls.total));
      if (ranked) return `Qloo has ranked your ${st.U != null ? st.U + ' ' : ''}places · picking your ${word(7)}…`;
      if (!st.done && s && SERVER_STATES.includes(s) && !['dated_only', 'partial'].includes(s) && st.status.text) return esc(st.status.text);
      if (s === 'waking' && !st.done) return 'waking the ranker up · about a minute';
      if (s === 'queued') { const a = st.status.ahead; return `${a == null ? ph(null, 'n') : word(a, true)} run${a === 1 ? '' : 's'} ahead of yours · about ${ph(st.status.eta_s, 's')} s`; }
      if (API.health === 'waking' && !st.firstServerEvent) return 'waking the ranker up · about a minute';
      const items = [...st.asks.values()];
      const datedAt = items.filter(a => a.lane !== 'live' && a.provider).map(a => a.asked_at).filter(Boolean).sort().pop() || null;
      const fl = (R && R.flags) || [];
      const span = askDays();
      const qloo = () => st.done && R && R.counts && st.slots.length ? ` · Qloo ranked your ${R.counts.U != null ? R.counts.U + ' ' : ''}places` : '';
      if (s === 'dated_only' || (R && R.status === 'dated_only') || fl.includes('dated_only')) return `AI answers collected ${esc(span || '')}, none asked live this time` + qloo();
      if (R && (R.status === 'partial' || fl.includes('partial'))) {
        const ais = new Set(items.map(a => a.provider).filter(Boolean)).size;
        return `${ais} of ${CFG.lanes.length} AIs answered this time` + (span ? ` (asked ${esc(span)})` : '') + qloo();
      }
      const order = p => { const i = CFG.lanes.indexOf(p); return i < 0 ? 99 : i; };
      const dated = [...new Set(items.filter(a => a.lane !== 'live' && a.provider).map(a => a.provider))].sort((a, b) => order(a) - order(b));
      const live = [...new Set(items.filter(a => a.lane === 'live' && a.provider).map(a => a.provider))].sort((a, b) => order(a) - order(b));
      const parts = [];
      if (dated.length) parts.push(`${dated.map(esc).join(', ')}: asked ${ph(UM.days(items.filter(a => a.lane !== 'live').map(a => a.asked_at)), 'date')}`);
      // the live lane names its model from the data: "Gemini (gemini-3-flash-preview): asked just now"
      if (live.length) parts.push(live.map(p => { const m = items.find(a => a.lane === 'live' && a.provider === p && a.model); return esc(p) + (m ? ` (${esc(m.model)})` : ''); }).join(', ') + ': asked just now');
      const U = (R && R.counts && R.counts.U) ?? st.U;
      // a missing count is left out, never shown as a placeholder
      const calls = D && D.qloo_calls;
      if (st.done && R && R.counts && st.slots.length) parts.push(`Qloo ranked your ${U != null ? U + ' ' : ''}places` + (calls != null ? ` · ${calls} calls` : ''));
      else if (st.calls) parts.push(`Qloo is ranking your ${U != null ? U + ' ' : ''}places · ${st.calls.done}${st.calls.total != null ? ` of ${st.calls.total}` : ''} calls`);
      else if (!st.done && st.fresh) parts.push('ranking with Qloo · about 20 seconds');
      return parts.join(' · ');
    }
    function status() {
      $('#stxt').innerHTML = statusLine();
      $('#status').hidden = st.done;      // a status line only while a run is in progress; failures speak in the results area
      $('#status').classList.toggle('busy', !st.done && !st.failed && (!!st.calls || st.order.length > 0));
      const mock = st.fake || st.mock;
      topbar({ city: cityName, loves: tLoves(), mock: mock ? (st.fake ? 'mock data' : 'mock stream · no server') : null });
    }
    function notes() {
      const R = st.result; const out = [];
      if (R && R.status === 'degraded' && st.slots.length) out.push(`from ${ph(R.stored_at || et(R.diag && R.diag.as_of), 'date time')} · Qloo is slow right now`);
      if (R) {
        const live = (R.loves || []).filter(l => !l.dead).length;
        tLoves().filter(l => l.dead).forEach(l => out.push(esc(UM.deadLine(l, cityName, live))));
      }
      $('#notes').innerHTML = out.map(t => `<div>${t}</div>`).join('');
    }

    // one labelled ask count, the same field everywhere (lead line, card back): counts.asks and diag.as_of
    // one date span for every line that says when the AIs were asked: "27–28 Oct"
    const askDays = () => UM.days([...st.asks.values()].filter(a => a.lane !== 'live').map(a => a.asked_at));
    function askLine(noDate) {
      const R = st.result || {}, n = R.counts && R.counts.asks;
      const d = noDate ? null : askDays() || UM.day(R.diag && R.diag.as_of);
      return `${n != null ? n + ' ' : ''}asks about ${esc(cityName)}` + (d ? ` (${esc(d)})` : '');
    }
        // ---- burn beat: street checks are DATED (asked in advance), so the line states a result and never moves
    function burnLine() {
      const b = $('#burn');
      const asked = (st.result && st.result.burn && st.result.burn.asked) || [];
      const askOf = hood => asked.find(a => a.neighbourhood === hood) || {};
      // only burns of cards the visitor saw, each with its name, and the AI by its name (not its lane id)
      const seen = st.burned.filter(x => st.cards.has(x.card_id) && (st.cards.get(x.card_id) || {}).name);
      if (seen.length) {
        b.innerHTML = seen.map(x => {
          const c = st.cards.get(x.card_id) || {}, r = x.replaced_by && st.cards.get(x.replaced_by);
          const hood = c.neighbourhood ?? x.neighbourhood, a = askOf(hood);
          const who = UM.provider(x.by || a.provider), when = et(x.at || a.asked_at);
          // "⟦provider⟧ named ⟦X⟧ when asked about ⟦Soulard⟧ · ⟦date⟧ · burned. ⟦Y⟧ takes its place."
          return `<span class="red">${ph(who, 'provider')} named ${placeName(c, x.card_id)}</span> when asked about ${ph(hood, 'neighbourhood')} · ${ph(when, 'date')} · burned.` +
            (r ? ` ${placeName(r, r.id)} takes its place.` : '');
        }).join('<br>');
      } else b.innerHTML = '';
    }
    // one numbering: after the result, a card's number is its position in the list (cards, map dots, placeholders);
    // while streaming, the order cards arrived in. A burned card has left the list and has no number.
    const cardNo = id => { const L = st.done ? st.slots : st.order; const i = L.indexOf(id); return i < 0 ? null : i + 1; };
    const placeName = (c, id) => c.name ? esc(UM.shortName(c.name, c.neighbourhood)) : (cardNo(id) ? ph(null, `place ${cardNo(id)}`) : ph(null, 'burned card'));

    // ---- events
    function onEvent(e) {
      if (e.type !== 'wall_name') st.firstServerEvent = true;
      if (e.flags && e.flags.includes('fake')) st.fake = true;
      switch (e.type) {
        case 'status': st.status = e; break;
        case 'wall_name': addName(e); break;
        case 'pool': st.U = e.U; if (e.R_mi != null) st.R_mi = e.R_mi; break;
        case 'strike': setOutcome(e.place || e.norm, e.outcome, e.reason, e.qloo_id); break;
        case 'calls': st.calls = e; break;
        case 'card': st.cards.set(e.id, e); if (!st.order.includes(e.id)) st.order.push(e.id); mapDraw(); provisional(); break;
        case 'burn':
          if (e.card_id) { st.burned.push({ ...e, seen: hhmm() }); }
          if (e.risen && e.risen.id) { st.cards.set(e.risen.id, e.risen); if (!st.order.includes(e.risen.id)) st.order.push(e.risen.id); st.risen.set(e.risen.id, 'rose in its place'); }
          burnLine(); mapDraw(); provisional(); break;
        case 'done': finish(e.result); break;
      }
      counter(); status();
    }
    // a fresh run: each card shows as it arrives (Qloo has ranked; the street and live AI checks still run). The result
    // replaces this list; a card an AI names meanwhile leaves it and the next one rises.
    function provisional() {
      if (st.done || st.failed) return;
      const ids = st.order.filter(id => !st.burned.some(b => b.card_id === id));
      if (!ids.length) return;
      $('#s-left').hidden = false; $('#res').classList.add('hascards');
      $('#leftbody').innerHTML = `<h2 class="lead2"><span class="n">${ids.length}</span> for you so far</h2>
        <p class="leadsub">Ranked by Qloo for what fits you, not everyone. Still checking that no AI names them…</p>
        <div class="cards prov" id="cards">${ids.map((id, i) => cardHTML(st.cards.get(id), i, false, true)).join('')}</div>`;
    }
    function finish(R) {
      st.result = R; st.done = true;
      if ((R.flags || []).includes('fake')) st.fake = true;
      st.R_mi = R.counts && R.counts.R_mi;
      if (Array.isArray(R.wall) && !st.mock) {
        // the static dated wall streamed first; the result's wall is what was actually crossed out, so it replaces it
        fieldEl.innerHTML = ''; st.wall.clear(); st.asks.clear(); st.reconciled = true;
        R.wall.forEach(w => { addName(w); setOutcome(wk(w), w.outcome, w.reason, w.qloo_id); });
      } else (R.wall || []).forEach(w => { if (!st.wall.has(wk(w))) addName(w); setOutcome(wk(w), w.outcome, w.reason, w.qloo_id); });
      sortField();
      [...(R.picks || []), ...(R.reserves || []), ...(R.known || [])].forEach(c => { st.cards.set(c.id, c); if (!st.order.includes(c.id)) st.order.push(c.id); });
      (R.burn && R.burn.burned || []).forEach(b => { if (!st.burned.find(x => x.card_id === b.card_id)) st.burned.push({ ...b, seen: hhmm() }); if (b.replaced_by) st.risen.set(b.replaced_by, 'rose in its place'); });
      st.slots = (R.picks || []).map(c => c.id);
      st.reserves = (R.reserves || []).map(c => c.id);
      burnLine(); notes(); left(); counter(); status(); mapDraw();
      $('#res').classList.add('done');
      clearTimeout(st.failT);
    }

    // ---- LEFT FOR YOU
    function left() {
      const R = st.result, sec = $('#s-left'), body = $('#leftbody');
      sec.hidden = false;
      const flags = R.flags || [];
      const n = st.slots.length;
      const asks = R.counts && R.counts.asks, date = et(R.diag && R.diag.as_of);
      if (R.status === 'needs_input') {
        const fix = (R.resolutions || []).filter(r => r.status !== 'ok');
        if (R.city_resolution && R.city_resolution.status !== 'ok') fix.push({ text: R.city_resolution.text || cityName, chip: null, alternatives: R.city_resolution.alternatives || [] });
        body.innerHTML = fix.map(r => `<p><span class="need">${esc(r.text)} → ${r.chip ? esc(r.chip.label) + (tl(r.chip) ? ` (${esc(tl(r.chip))})` : '') + '?' : ''}${(r.alternatives || []).length ? ' · other: ' + r.alternatives.map(a => esc(a.disamb || a.label || a.name)).join(' · ') : ''}</span></p>`).join('') +
          `<div class="go"><a class="btn" href="#/">Fix it</a></div>`;
        return;
      }
      if (R.status === 'error' || R.status === 'unauthorized' || R.status === 'unsupported_city' || R.status === 'bad_request') {
        body.innerHTML = `<p class="empty">${R.status === 'unauthorized' ? 'needs the token from the testing instructions: add ?token=… to this page’s address' : esc(R.note || 'That didn’t go through.')}</p><div class="go"><a class="btn" href="#/">Fix it</a></div>`;
        return;
      }
      // the server restarted mid-run: its own note, and Retry
      if (flags.includes('restarting') && !n) {
        body.innerHTML = `<p class="empty">${esc(R.note || 'The ranker restarted mid-run. Try again; nothing you typed was lost.')}</p><div class="go"><button class="btn solid" id="retry">Retry</button></div>${tryList()}`;
        $('#retry').addEventListener('click', () => route());
        return;
      }
      if (R.status === 'limited') {
        const ra = R.retry_after ?? (R.diag && R.diag.retry_after) ?? (st.status && st.status.retry_after);
        const min = ra != null ? Math.max(1, Math.ceil(+ra / 60)) : null;
        body.innerHTML = `<p class="empty">Busy: ${min ? `try again in ${min} min` : 'try again in a few minutes'}. These open instantly:</p>${tryList('')}`; return;
      }
      if (R.status === 'degraded' && !n) {
        body.innerHTML = `<p class="empty">Qloo isn’t answering right now. Your three are saved in this link; try in a minute, or open one of these.</p>${tryList('')}`; return;
      }
      if (R.status === 'empty_none' || !n) {
        const known = (R.known || []).slice(0, 3);
        body.innerHTML = `<p class="empty">Everything here that fits you, the AIs already say.</p><div class="cap" style="margin-top:18px">you already know these</div>` +
          `<div class="cards known">${known.length ? known.map((c, i) => cardHTML(c, i, true)).join('') :
            [...st.wall.values()].filter(w => w.reason === 'in pool').slice(0, 3).filter(w => w.name).map(w => `<div class="card"><div class="name">${esc(w.name)}</div></div>`).join('')}</div>`;
        return;
      }
      const lead = R.status === 'empty_few'
        ? `<p class="empty">Only ${n} places in ${esc(cityName)} fit you that no AI names. Here they are.</p>`
        : `<h2 class="lead2"><span class="n">${n}</span> for you</h2><p class="leadsub">All rated ${CFG.floor.rating}+. No AI named any of them${R.counts && R.counts.asks != null ? ` in ${R.counts.asks.toLocaleString('en-US')} asks` : ''}.</p>`;
      // desktop: "7 for you" sits beside the map, so the cards start above the fold; phone: above the cards
      st.lead = R.status === 'empty_few' ? null : lead; mapDraw();
      body.innerHTML = `<div class="leadhere">${lead}</div>` + `<div class="cards" id="cards"></div>
        <details class="dare" id="darebox"><summary>Ask your AI. Paste its answer here →</summary>
          <div class="copyrow"><button class="link" id="copyask">copy an ask</button><span class="dim" id="askq">“hidden gems to eat and drink in ${esc(cityName)}”</span></div>
          <textarea id="dare" placeholder="paste an answer here" spellcheck="false" aria-label="${esc(dareLabel())}"></textarea><div class="out" id="dareout"></div></details>
        <div class="links"><button class="btn" id="lnk-share">Share</button></div>`;
      drawCards();
      $('#cards').after($('#burn'));          // the burn line sits after the seven, never before cards not yet seen
      $('#copyask').addEventListener('click', () => {
        const q = `hidden gems to eat and drink in ${cityName}`, b = $('#copyask');
        (navigator.clipboard ? navigator.clipboard.writeText(q) : Promise.reject()).then(() => { b.textContent = 'copied'; }, () => { b.textContent = 'select the line to copy'; });
        setTimeout(() => { b.textContent = 'copy an ask'; }, 1600);
      });
      $('#lnk-share').addEventListener('click', shareSheet);
      let t = null;
      $('#dare').addEventListener('input', e => { clearTimeout(t); t = setTimeout(() => dare(e.target.value), 250); });
    }

    const cap1 = x => String(x).charAt(0).toUpperCase() + String(x).slice(1);
    // engine lines name a love by Qloo's entity name ("Maze Featuring Frankie Beverly"); people typed "Frankie Beverly & Maze"
    const typedText = x => tLoves().reduce((t, l) => l.qloo_label && l.label && l.qloo_label !== l.label ? t.split(l.qloo_label).join(l.label) : t, String(x));
    const dareLabel = () => `Ask any AI yourself. Paste what it says: any of these ${liveIds().length} it names burns.`;
    // the card face: photo, name, "Neighbourhood · 6 mi · $$ · Open now", one line about it, what to order, the love.
    // Ranks, the because detail, the address and the maps live on the card's sheet.
    function photo(c, i, x) {
      const fb = `<span class="fb">${esc(c.what || '')}</span>`;
      // Qloo serves the same photo wider ("-420x-auto" -> "-800x-auto"): the browser picks by the card's width
      const big = /-420x-auto\.jpg$/.test(c.image || '') ? c.image.replace(/-420x-auto\.jpg$/, '-800x-auto.jpg') : null;
      const set = big ? ` srcset="${esc(c.image)} 420w, ${esc(big)} 800w" sizes="(max-width: 720px) 100vw, 420px"` : '';
      return `<div class="pic${httpUrl(c.image) ? '' : ' none'}">${httpUrl(c.image) ? `<img src="${esc(c.image)}"${set} alt="" ${i < 3 ? 'fetchpriority="high"' : 'loading="lazy"'} onerror="this.parentNode.classList.add('none');this.remove()" onload="if(this.naturalWidth<100){this.parentNode.classList.add('none');this.remove()}">` : ''}${fb}` +
        `<span class="no">${String(i + 1).padStart(2, '0')}</span>${x || ''}</div>`;
    }
    // the area: in St. Louis, a place whose address is in another municipality ("8017 Airport Rd Berkeley, MO") shows that
    // municipality; otherwise Qloo's neighbourhood
    const STREET_T = /^(st|street|ave|avenue|blvd|boulevard|rd|road|dr|drive|pkwy|parkway|hwy|highway|ln|lane|way|pl|place|ct|ter|trl|cir|plz|sq|\d+\w*)\.?$/i;
    function municipality(addr) {
      const m = String(addr || '').match(/^(.*?),\s*[A-Z]{2}\s+\d{5}/); if (!m) return null;
      const head = m[1].trim();
      if (/\bst\.?\s+louis$/i.test(head)) return 'St. Louis';
      const t = head.split(/\s+/); let k = t.length;
      while (k > 0 && !STREET_T.test(t[k - 1])) k--;
      const city = t.slice(k).join(' ');
      return k > 0 && city ? city : null;
    }
    function areaOf(c) {
      const mu = slug === 'st-louis' ? municipality(c.address) : null;
      return mu && mu !== 'St. Louis' ? mu : (c.neighbourhood || c.area || null);
    }
    // the reason line: "Fits all three of your loves" when it fits each; a dish love by name; another love only when the
    // place holds for at least two; otherwise none (the card's own line says what it is)
    function loveOf(label) { return ((st.result && st.result.loves) || []).find(l => l.label === label) || null; }
    function reasonLine(c) {
      const n = c.n_loves, h = c.holds;
      if (n >= 2 && h != null && h >= n) return n === 2 ? 'Fits both of your loves' : `Fits all ${word(n)} of your loves`;
      if (c.because == null) return '';
      const l = loveOf(c.because), tag = l && (l.kind === 'tag' || /^urn:tag/.test(l.type || ''));
      if (tag || (h != null && h >= 2)) return `Because you love ${tName(c.because)}`;
      return '';
    }
    function metaLine(c) {
      // no distance: there is no visitor location, so "6 mi" would only read as far
      return [areaOf(c), price(c), c.open === false ? 'Closed' : openState(c)].filter(Boolean).map(esc).join(' · ');
    }
    // one casing for what to order: lower case, except a word that is all caps or has a capital after its first
    // letter ("BBQ", "McDonald's"): "Traditional Wings And Fries" -> "traditional wings and fries"
    const dish = d => String(d).split(/(\s+)/).map(w => /\p{Lu}/u.test(w.slice(1)) || (w.length > 1 && w === w.toUpperCase() && /\p{L}/u.test(w)) ? w : w.toLowerCase()).join('');
    function cardHTML(c, i, known, prov) {
      const tag = st.struck.get(c.id), rose = st.risen.get(c.id);
      const x = known || tag || prov ? '' : `<button class="xbtn" data-x="1" aria-label="Know it? Strike ${esc(c.name || 'it')}" title="Know it? Strike it">✕</button>`;
      const blurb = c.line || c.blurb || (c.what ? cap1(c.what) : '');
      const order = Array.isArray(c.order) ? c.order.filter(Boolean) : c.order ? [c.order] : [];
      return `<div class="card${tag ? ' struck' : ''}${tag && tag.human ? ' byyou' : ''}${rose ? ' risen' : ''}" data-id="${esc(c.id)}">
        ${photo(c, i, x)}
        <div class="body">
          <div class="name">${known ? (c.name ? esc(c.name) : '') : placeName(c, c.id)}</div>
          ${known || !reasonLine(c) ? '' : `<div class="because">${esc(reasonLine(c))}</div>`}
          <div class="meta">${metaLine(c)}</div>
          ${blurb ? `<p class="blurb">${esc(blurb)}</p>` : ''}
          ${order.length ? `<div class="order">Order: ${order.map(dish).map(esc).join(', ')}</div>` : ''}
          ${tag || rose ? `<div class="tag${rose && !tag ? ' rose' : ''}">${tag ? esc(tag.text) : esc(rose)}</div>` : ''}
        </div>
      </div>`;
    }
    // "Open now" / "Opens 5 pm" / "Opens tomorrow 12 pm", from Qloo's hours in the place's own time zone
    const DAYS = ['sunday', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday'];
    const mins = t => { const m = String(t || '').match(/(\d{1,2}):(\d{2})/); return m ? +m[1] * 60 + +m[2] : null; };
    const clock = m => { const h = Math.floor(m / 60) % 24, mm = m % 60; return `${h % 12 || 12}${mm ? ':' + String(mm).padStart(2, '0') : ''} ${h < 12 ? 'am' : 'pm'}`; };
    function nowIn(tz) {
      let f; try { f = new Intl.DateTimeFormat('en-US', { timeZone: tz || undefined, weekday: 'long', hour: 'numeric', minute: 'numeric', hourCycle: 'h23' }).formatToParts(new Date()); }
      catch (e) { f = new Intl.DateTimeFormat('en-US', { weekday: 'long', hour: 'numeric', minute: 'numeric', hourCycle: 'h23' }).formatToParts(new Date()); }
      const g = t => (f.find(x => x.type === t) || {}).value;
      return { d: DAYS.indexOf(String(g('weekday')).toLowerCase()), m: (+g('hour') % 24) * 60 + +g('minute') };
    }
    function slots(h, d) {
      const x = h[DAYS[d]] || h[DAYS[d].slice(0, 3)] || [];
      return (Array.isArray(x) ? x : [x]).filter(t => t && !t.closed && mins(t.opens) != null && mins(t.closes) != null).map(t => ({ o: mins(t.opens), c: mins(t.closes) }));
    }
    function hoursOk(c) {
      const h = c.hours; if (!h || typeof h !== 'object' || Array.isArray(h)) return false;
      if (/24\s*\/\s*7|24 hours/i.test([c.blurb, c.line, c.what].filter(Boolean).join(' '))) return false;
      const shut = DAYS.filter((_, d) => !slots(h, d).length);
      return !(shut.length === 7 || (shut.length === 2 && shut.includes('friday') && shut.includes('saturday')));
    }
    function openState(c) {
      const h = c.hours; if (!hoursOk(c)) return '';
      const { d, m } = nowIn(c.tz); if (d < 0) return '';
      const now = slots(h, d).find(t => m >= t.o && m < (t.c <= t.o ? t.c + 1440 : t.c))
        || slots(h, (d + 6) % 7).find(t => t.c <= t.o && m < t.c);      // last night's hours, past midnight
      if (now) return `Open now · until ${clock(now.c % 1440)}`;
      const today = slots(h, d);
      if (!today.length) return 'Closed today';
      const later = today.filter(t => t.o > m).sort((a, b) => a.o - b.o)[0];
      if (later) return `Opens ${clock(later.o)}`;
      for (let k = 1; k < 7; k++) {
        const n = slots(h, (d + k) % 7).sort((a, b) => a.o - b.o)[0];
        if (n) return `Opens ${k === 1 ? 'tomorrow' : cap1(DAYS[(d + k) % 7].slice(0, 3))} ${clock(n.o)}`;
      }
      return '';
    }
    // "31st most popular of 78 nearby": Qloo's popularity order among this person's pool (c.U places)
    const ordinal = n => { const t = n % 100, u = n % 10; return n + (t >= 11 && t <= 13 ? 'th' : u === 1 ? 'st' : u === 2 ? 'nd' : u === 3 ? 'rd' : 'th'); };
    function popWords(c, short) {
      if (c.any_rank == null) return '';
      const U = c.U ?? (st.result && st.result.counts && st.result.counts.U);
      const head = c.any_rank === 1 ? 'the most popular' : `${ordinal(c.any_rank)} most popular`;
      return short || U == null ? head : `${head} of ${U} nearby`;
    }
    // "14 mi from downtown" (the engine's distance_mi, measured from the city centre it searches around)
    function distWords(c) {
      if (c.distance_mi == null) return '';
      const d = +c.distance_mi, from = c.distance_from || (cc && cc.from) || 'the city centre';
      return `${d < 1 ? d.toFixed(1) : Math.round(d)} mi from ${from}`;
    }
    // the street part of a Qloo address ("8734 Goodfellow Blvd St. Louis, MO 63147" -> "8734 Goodfellow Blvd")
    function street(c) {
      const a = String(c.address || '').trim(); if (!a) return '';
      const k = a.toLowerCase().indexOf(String(cityName).toLowerCase());
      return (k > 0 ? a.slice(0, k) : a.split(',')[0]).replace(/[\s,]+$/, '');
    }
    // today's hours as text ("12 pm–10 pm"), in the place's own time zone
    function hours(c) {
      const h = c.hours_today || c.hours; if (!h) return '';
      if (typeof h === 'string') return h;
      if (!hoursOk(c)) return '';
      const { d } = nowIn(c.tz); if (d < 0) return '';
      const t = slots(h, d);
      return t.length ? t.map(x => `${clock(x.o)}–${clock(x.c)}`).join(', ') : 'closed';
    }
    const price = c => { const p = c.price_level ?? c.price; return p == null || p === '' ? '' : typeof p === 'number' ? '$'.repeat(Math.max(1, Math.min(4, Math.round(p)))) : String(p); };
    function mapsLinks(c) {
      const q = [c.name, c.address].filter(Boolean).join(', ');
      const apple = `https://maps.apple.com/?q=${encodeURIComponent(c.name || '')}` + (c.lat != null ? `&ll=${c.lat},${c.lon}` : '') + (c.address ? `&address=${encodeURIComponent(c.address)}` : '');
      const google = `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(q)}`;
      return `<a href="${esc(apple)}" target="_blank" rel="noopener">Apple Maps</a><a href="${esc(google)}" target="_blank" rel="noopener">Google Maps</a>`;
    }
    function cardEl(id) {
      const c = st.cards.get(id);
      const wrap = document.createElement('div');
      wrap.innerHTML = cardHTML(c, st.slots.indexOf(id));
      const node = wrap.firstElementChild;
      let timer = null, held = false;
      const cancel = () => { clearTimeout(timer); node.classList.remove('holding'); };
      node.addEventListener('pointerdown', e => {
        if (st.struck.has(id) || e.button > 0 || e.target.closest('a, .xbtn')) return;
        held = false; node.classList.add('holding');
        timer = setTimeout(() => { held = true; node.classList.remove('holding'); strike(id, `struck by you · ${hhmm()}`, true); }, 900);
      });
      ['pointerup', 'pointerleave', 'pointercancel'].forEach(ev => node.addEventListener(ev, cancel));
      node.addEventListener('contextmenu', e => e.preventDefault());
      node.addEventListener('click', e => {
        if (e.target.closest('a')) return;
        if (e.target.closest('.xbtn')) { e.stopPropagation(); strike(id, `struck by you · ${hhmm()}`, true); return; }
        if (held) { held = false; return; } cardSheet(id);
      });
      return node;
    }
    function drawCards() {
      const el2 = $('#cards'); if (!el2) return;
      el2.innerHTML = '';
      st.slots.forEach(id => el2.appendChild(cardEl(id)));
      watchPhotos(el2);
    }
    function watchPhotos(root) {
      const give = img => { if (img.isConnected && (!img.complete || img.naturalWidth < 100)) { img.parentNode.classList.add('none'); img.remove(); } };
      const io = 'IntersectionObserver' in window ? new IntersectionObserver(es => es.forEach(e => {
        if (e.isIntersecting) { io.unobserve(e.target); setTimeout(() => give(e.target), 4000); } }), { rootMargin: '200px' }) : null;
      root.querySelectorAll('.pic img').forEach(img => io ? io.observe(img) : setTimeout(() => give(img), 4000));
    }
    // a struck card stays where it was, struck (in ink if you struck it, red if an AI named it); the next reserve rises
    // in under it, and every number after it moves down one, on the cards and the map alike
    function strike(id, text, human) {
      st.struck.set(id, { text, human: !!human });
      if (human) { try { localStorage.setItem('unsaid.hint', '1'); } catch (e) { /* */ } const h = $('#hint'); if (h) h.remove(); }
      const rid = st.reserves.shift();
      if (rid) {
        st.risen.set(rid, 'rose in its place · another place no AI named');
        st.slots.splice(st.slots.indexOf(id) + 1, 0, rid);
      }
      drawCards(); counter(); mapDraw();
      const dl = $('#darelabel'); if (dl) dl.textContent = dareLabel();
      return rid;
    }
    // a burned card: scrolled to and flashed, so the paste visibly did something
    function flash(id) {
      const n = $(`#cards .card[data-id="${CSS.escape(id)}"]`); if (!n) return;
      n.scrollIntoView({ block: 'center', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
      n.classList.remove('flash'); void n.offsetWidth; n.classList.add('flash');
    }
    // ---- the paste. UI-only pre-extraction: the names an answer gives are its list items' heads, its bold heads and the
    // names that start a line ("Gioia's Deli – The Hill: hot salami" -> "Gioia's Deli – The Hill"); prose is not read
    // for wall names, so "an old-school soda fountain" never matches The Fountain on Locust. Card burns then use the
    // matcher's own rules (Matcher.find, identical to matcher.py) on those names.
    const SEP = /\s+[–—-]\s+|:\s|\s\(|,\s|;\s|\.\s|\s+\|\s+/;
    function pasteNames(text) {
      const out = [], seen = new Set();
      const add = (t, list) => {
        t = String(t).replace(/\*\*|__|[*_`#>]/g, '').replace(/^[\s"“”'‘’]+|[\s:.,;"“”'‘’]+$/g, '').trim();
        if (!t || t.split(/\s+/).length > 8 || !/^[\p{Lu}\p{N}]/u.test(t)) return;   // a name starts with a capital
        const k = t.toLowerCase(); if (seen.has(k)) { if (list) out.find(x => x.t.toLowerCase() === k).list = true; return; }
        seen.add(k); out.push({ t, list });
      };
      // a JSON answer (the form we ask in): its "name" values are the names
      for (const m of String(text).matchAll(/"name"\s*:\s*"((?:[^"\\]|\\.)+)"/g)) add(m[1].replace(/\\(.)/g, '$1'), true);
      if (out.length) return out;
      for (const raw of String(text).split(/\r?\n/)) {
        const line = raw.replace(/^\s*>?\s*#{0,6}\s*/, '');
        if (!line.trim()) continue;
        const m = line.match(/^\s*(?:\d+[.)]|[-*•·–])\s+(.*)$/), body = m ? m[1] : line;
        const bolds = [...line.matchAll(/\*\*(.+?)\*\*|__(.+?)__/g)].map(x => x[1] || x[2]);
        bolds.forEach(b => add(b, !!m && body.trim().startsWith('**' + b)));
        if (body.trim().startsWith('**')) continue;                       // the bold head is the name
        const parts = body.split(SEP), head = parts[0];
        // a list item's head; a line that starts with a name and a separator; a short line on its own (a heading)
        if (m || parts.length > 1 || (head.split(/\s+/).length <= 6 && !/[.!?]$/.test(head.trim()))) add(head, !!m);
      }
      return out;
    }
    let HOODS = null;   // neighbourhood names (data/hoods.json, from harness/neighbourhoods.json): never a place
    UM.json('data/hoods.json').then(h => { HOODS = new Set([].concat(...Object.values(h.cities || {})).map(Matcher.norm)); }).catch(() => { HOODS = new Set(); });
    const SMALL = new Set(['of', 'the', 'and', '&', 'a', 'an', 'at', 'on', 'in', 'de', 'la', 'le', 'del', 'n', 'y', 'e', 'di', 'da']);
    const titled = t => { const w = t.split(/\s+/); return w.length <= 5 && w.every((x, i) => (i && SMALL.has(x.toLowerCase())) || /^[\p{Lu}\p{N}'’"“]/u.test(x)); };
    function dare(text) {
      const out = $('#dareout');
      if (!text.trim()) { out.innerHTML = ''; return; }
      const ids = liveIds(), seven = word(ids.length);
      const names = pasteNames(text);
      const isHood = n => HOODS && HOODS.has(Matcher.norm(n));
      const wallList = [...st.wall.values()].filter(w => w.name && !isHood(UM.cleanName(w.name))).sort((a, b) => b.hits.size - a.hits.size);
      const wallNames = wallList.map(w => UM.cleanName(w.name));
      // each card under its raw Qloo name (what matcher.py sees: "Jody B'") and its display name ("Jody B's")
      const cardNames = [], cardOf = [];
      ids.forEach(id => { const c = st.cards.get(id); [...new Set([c.name_qloo, c.name].filter(Boolean))].forEach(n => { cardNames.push(n); cardOf.push(id); }); });
      const wallSeen = new Map(), cardSeen = new Map(), unknown = [];
      for (const n of names) {
        if (isHood(n.t)) continue;
        const ch = Matcher.find(n.t, cardNames);
        // a wall name only as a name: the phrase itself, capitalised where it stands in the answer
        let wh = Matcher.find(n.t, wallNames, { phraseOnly: true }).filter(h => /^[\p{Lu}\p{N}]/u.test(n.t.slice(h.at[0])));
        const toks = x => Matcher.norm(x).split(' ').filter(t => t && t !== 'the');
        const all = wh.map(h => h.name).concat(ch.map(h => h.name));
        // "The Hill" inside "Blueberry Hill": a hit whose words all sit inside a longer hit is not a separate place
        wh = wh.filter(h => !all.some(m => m !== h.name && toks(m).length > toks(h.name).length && toks(h.name).every(t => toks(m).includes(t))));
        ch.forEach(h => cardSeen.set(cardOf[h.index], h));
        wh.forEach(h => { const w = wallList[h.index]; if (!wallSeen.has(w.key)) wallSeen.set(w.key, h.name); });
        // a place we don't know counts only when it reads as a name: a list item's head in title case, five words at most
        if (!ch.length && !wh.length && n.list && titled(n.t)) unknown.push(n.t);
      }
      const crossed = [...wallSeen.values()], burnedIds = [...cardSeen.keys()];
      const named = crossed.length + burnedIds.length + unknown.length;
      const list = xs => xs.length <= 6 ? xs.map(esc).join(', ') : xs.slice(0, 5).map(esc).join(', ') + ` and ${xs.length - 5} more`;
      const big = [];
      if (!named) big.push('It named none of the places we know.');
      else {
        big.push(`Your AI named ${named} place${named === 1 ? '' : 's'}.`);
        if (crossed.length) big.push(`We’d already crossed out ${crossed.length === named ? (named === 1 ? 'it' : named === 2 ? 'both' : `all ${named}`) : crossed.length}.`);
      }
      const burned = [];
      const after = [];
      burnedIds.forEach(id => {
        const c = st.cards.get(id);
        const rid = strike(id, `named in your paste · ${hhmm()}`);
        burned.push(id);
        big.push(`<span class="red">It named ${esc(c.name)}, one of your ${seven}: burned.</span>`);
        const r = rid && st.cards.get(rid);
        if (r) after.push(`${placeName(r, rid)} takes its place.`);
      });
      if (!burnedIds.length) big.push(`None of your ${seven}.`);
      const small = [];
      if (crossed.length) small.push(`Crossed out already: <span class="red">${list(crossed)}</span>.`);
      if (unknown.length) small.push(`Not on our lists: ${list(unknown)}.`);
      out.innerHTML = `<p class="big">${big.join(' ')}</p>` + (after.length ? `<p>${after.join(' ')}</p>` : '') + (small.length ? `<p class="dim">${small.join(' ')}</p>` : '');
      if (burned.length) flash(burned[0]);
    }
    window.__pasteNames = pasteNames;

    // ---- S3 · card back
    // the sheet's one fit line: "Fits you better than 28 of the 30 places more popular than it. No AI named it in 888 asks."
    // the sheet's one fit line states the taste signal without ever reading as mediocre:
    // top quarter -> "#13 of 77 for your taste · last of 77 by popularity."; top half -> "In the top half for your taste ·
    // 41st of 77 by popularity."; otherwise the "fits you better than N of the M more popular" line. Then the AI count.
    function fitLine(c) {
      const R = st.result || {}, n = R.counts && R.counts.asks;
      const U = c.U ?? (R.counts && R.counts.U), f = c.tied ? null : c.fit_rank, a = c.any_rank;
      const pop = a == null || U == null ? null : a >= U ? `last of ${U} by popularity` : `${ordinal(a)} of ${U} by popularity`;
      const m = String(c.why || '').match(/fits you better than (\d+|all) (?:of )?(?:the )?(\d+)? ?more popular places?/i);
      const better = m ? (m[1] === 'all' ? `Fits you better than all ${m[2]} places more popular than it.` : `Fits you better than ${m[1]} of the ${m[2]} places more popular than it.`)
        : /one more popular place/i.test(c.why || '') ? 'Fits you better than the one place more popular than it.' : null;
      const fit = f != null && U != null && f <= U / 4 ? [`#${f} of ${U} for your taste`, pop].filter(Boolean).join(' · ') + '.'
        : f != null && U != null && f <= U / 2 ? ['In the top half for your taste', pop].filter(Boolean).join(' · ') + '.'
        : better || (pop ? cap1(pop) + '.' : '');
      return [fit, `No AI named it${n != null ? ` in ${n.toLocaleString('en-US')} asks` : ''}.`].filter(Boolean).join(' ');
    }
    function cardSheet(id) {
      const c = st.cards.get(id), R = st.result, flags = R.flags || [];
      const flat = flags.includes('flat'), thin = flags.includes('thin_taste');
      const U = c.U ?? (R.counts && R.counts.U), Rmi = R.counts && R.counts.R_mi;
      const ns = c.never_said || {};
      const fit = c.tied ? null : c.fit_rank;
      const head = esc(UM.shortName(c.name || '', c.neighbourhood));
      const pct = r => Math.max(0, Math.min(100, ((r - 1) / Math.max(1, (U || 1) - 1)) * 100));
      const pos = r => `${pct(r)}%`;
      // a label near either end hangs inward, so it never leaves the sheet
      const lab = r => pct(r) < 12 ? `left:${pct(r)}%;transform:none` : pct(r) > 88 ? `right:${100 - pct(r)}%;transform:none` : `left:${pct(r)}%`;
      // no "#N for you" here: a mid rank reads as "you're mediocre here" (Cedric juror); the popularity spot stays
      const slider = flat || U == null || c.any_rank == null ? '' : `<div class="slider"><div class="track"></div>
          ${c.any_rank != null ? `<div class="tick any" style="left:${pos(c.any_rank)}"></div><div class="tl any" style="${lab(c.any_rank)}">${esc(popWords(c, true))}</div>` : ''}
          <div class="end" style="left:0">#1</div><div class="end" style="right:0">#${U}</div></div>`;
      const holds = '';
      const st3 = st.struck.get(id);
      const order = Array.isArray(c.order) ? c.order.filter(Boolean) : c.order ? [c.order] : [];
      openSheet(`
        ${httpUrl(c.image) ? `<img class="placeimg" src="${esc(c.image)}" alt="" loading="lazy" onerror="this.remove()" onload="if(this.naturalWidth<100)this.remove()">` : ''}
        <div class="cap">${esc(cityName)} · card ${cardNo(id)}</div>
        <h1>${head}</h1>
        <p class="sheetsub">${metaLine(c)}</p>
        ${c.blurb_long || c.description || c.blurb ? `<p class="lede">${esc(c.blurb_long || c.description || c.blurb)}</p>` : ''}
        ${c.what ? `<p class="dim">${esc(c.what)}</p>` : ''}
        ${order.length ? `<p>Order: ${order.map(dish).map(esc).join(', ')}</p>` : ''}
        ${st3 ? `<div class="red">${esc(st3.text)}</div>` : ''}
        ${reasonLine(c) ? `<div class="blk"><div class="sh"><h2>Because</h2></div>
          <div class="big1">${esc(reasonLine(c))}.</div>${c.because_detail ? `<p>${esc(cap1(typedText(c.because_detail)))}.</p>` : ''}</div>` : ''}
        <div class="blk"><div class="sh"><h2>Fits you</h2></div>
          <p>${esc(fitLine(c))}</p></div>
        <div class="blk"><div class="sh"><h2>Go</h2></div>
          ${c.address ? `<p>${esc(c.address)}${hours(c) ? `<br><span class="dim">${hours(c) === 'closed' ? 'Closed today' : `Today ${esc(hours(c))}`}</span>` : ''}</p>` : ''}
          ${c.open === false ? '<p class="red">Qloo marks it closed.</p>' : ''}
          <div class="links">${mapsLinks(c).replace(/<a /g, '<a class="btn solid" ').replace(/<\/a>/g, ' ↗</a>')}${httpUrl(c.url) ? `<a class="btn" href="${esc(c.url)}" target="_blank" rel="noopener">Website ↗</a>` : ''}</div></div>
        <details class="log"><summary>Raw log</summary><div class="logbody">${rawLog(c)}</div></details>`);
    }
    function rawLog(c) {
      const R = st.result, D = R.diag || {}, U = c.U ?? (R.counts && R.counts.U);
      const L = [];
      const asks = [...st.asks.values()].filter(a => a.provider);
      L.push(`<div class="k">every ask behind the wall (${asks.length})</div>`);
      asks.sort((a, b) => String(a.asked_at).localeCompare(String(b.asked_at))).forEach(a =>
        L.push(`<div>${ph(et(a.asked_at), 'time')} · <span class="v">${esc(a.provider)}</span> ${esc(a.model || '')} · ${a.lane === 'live' ? 'live' : 'dated'} · “${esc(a.phrasing || '')}” → ${a.names} names</div>`));
      L.push(`<div class="k" style="margin-top:8px">every name and the Qloo ID it resolved to (${st.wall.size})</div>`);
      [...st.wall.values()].forEach(w => L.push(`<div><span class="v">${wn(w)}</span> → ${w.qloo_id ? esc(w.qloo_id) : '—'} · ${esc(w.outcome || 'pending')}${w.reason ? ' · ' + esc(w.reason) : ''}</div>`));
      L.push(`<div class="k" style="margin-top:8px">this card</div>`);
      const pct = c.any_rank != null && U ? Math.round(100 * c.any_rank / U) : null;
      L.push(`<div>qloo id <span class="v">${esc(c.id)}</span> · popularity #${ph(c.any_rank, 'ANY')} of ${ph(U, 'U')} (top ${ph(pct, '%')}%) · for you #${ph(c.fit_rank, 'FIT')} · holds ${ph(c.holds, 'h')} of ${ph(c.n_loves, 'n')}</div>`);
      ((R.burn && R.burn.asked) || []).filter(a => a.neighbourhood === c.neighbourhood).forEach(a =>
        L.push(`<div>street ask · ${esc(a.provider || '')} · ${esc(a.lane || '')} · ${ph(et(a.asked_at), 'time')} · “${esc(a.neighbourhood)}” → ${a.named && a.named.length ? 'named this card' : 'not named'}</div>`));
      L.push(`<div class="k" style="margin-top:8px">request URLs</div>`);
      (c.request_urls || c.requests || []).forEach(u => L.push(`<div>${esc(u)}</div>`));
      L.push(`<div>${D.trace_url ? `<a href="${esc(D.trace_url)}">${esc(D.trace_url)}</a>` : ph(null, 'trace_url')} · engine ${esc(D.engine_v || '')} · ${ph(D.qloo_calls, 'N')} Qloo calls</div>`);
      return L.join('');
    }
    function nameSheet(o) {
      const hits = [...o.hits.values()];
      const all = [...st.asks.values()];
      const byP = p => ({ n: hits.filter(h => h.provider === p).length, of: all.filter(a => a.provider === p).length });
      const provs = [...new Set(hits.map(h => h.provider).filter(Boolean))];
      // the hidden-gem asks (the census's 16 phrasings), per AI: "Claude named it in 13 of its 16 hidden-gem asks"
      const gemOf = p => { const H = all.filter(a => a.provider === p && /-hidden-/.test(a.phrasing_id || '')); return H.length ? { n: hits.filter(h => h.provider === p && /-hidden-/.test(h.phrasing_id || '')).length, of: H.length } : null; };
      const lines = provs.map(p => { const g = gemOf(p), b = byP(p);
        return g && g.n ? `<b>${esc(p)}</b> named it in <span class="red">${g.n} of its ${g.of}</span> hidden-gem asks, and in ${b.n} of all ${b.of} of its asks here.`
          : `<b>${esc(p)}</b> named it in ${b.n} of its ${b.of} asks here.`; });
      const first = hits.slice().sort((a, b) => String(a.asked_at).localeCompare(String(b.asked_at)))[0] || o;
      const why = o.outcome === 'struck' ? 'It was in your Qloo pool, so crossing it out cost you a card.' : o.reason === 'not in pool' ? 'It wasn’t in your Qloo pool for these loves, so crossing it out cost you nothing.' : '';
      openSheet(`<div class="cap">everyone gets these</div><h1 style="font-size:32px"><span style="text-decoration:line-through;text-decoration-color:var(--red);text-decoration-thickness:2px">${wn(o)}</span></h1>
        ${lines.map(l => `<p>${l}</p>`).join('')}
        ${why ? `<p class="dim">${why}</p>` : ''}
        <p class="dim">For example, asked “${esc(first.phrasing || '')}”${first.asked_at ? ` (${esc(et(first.asked_at))})` : ''}.</p>
        <details class="log"><summary>Raw</summary><div class="logbody">${hits.map(h => `<div>${esc(et(h.asked_at) || '')} · <span class="v">${esc(h.provider || '')}</span> ${esc(h.model || '')} · ${h.lane === 'live' ? 'live' : 'dated'} · “${esc(h.phrasing || '')}”</div>`).join('')}
          <div>${o.qloo_id ? 'Qloo ID ' + esc(o.qloo_id) : 'no Qloo ID'}${o.reason ? ' · ' + esc(o.reason) : ''}</div></div></details>`);
    }

    // ---- share
    function shareSheet() {
      const link = set ? `${location.origin}${location.pathname}#/r?set=${encodeURIComponent(set.id)}` : shareUrl();
      const W = Share.wallCount(st.result) ?? st.wall.size, N = liveIds().length;
      const text = `The AIs named ${W} places. None named these ${N}.`;
      openSheet(`<div class="cap">share</div><canvas class="sharecv" id="sharecv"></canvas>
        <p>${esc(text)}<br><span class="dim">${esc(link)}</span></p>
        <div class="links">${navigator.share ? '<button class="btn solid" id="sh">Share</button>' : ''}<a class="btn" id="dl" download="unsaid.png" href="#">Save image</a><button class="btn" id="cp">Copy link</button></div>`);
      const cv = $('#sharecv');
      Share.draw(cv, { ...shareData(), site: siteHost() });
      $('#cp').addEventListener('click', () => { const b = $('#cp'); (navigator.clipboard ? navigator.clipboard.writeText(link) : Promise.reject()).then(() => { b.textContent = 'Copied'; }, () => { b.textContent = 'Select the link above'; }); });
      cv.toBlob(b => {
        const u = URL.createObjectURL(b); $('#dl').href = u;
        const sb = $('#sh');
        if (sb) sb.addEventListener('click', () => {
          const file = new File([b], 'unsaid.png', { type: 'image/png' });
          const full = { files: [file], url: link, text };
          (navigator.canShare && !navigator.canShare(full) ? navigator.share({ url: link, text }) : navigator.share(full)).catch(() => {});
        });
      });
    }
    function shareData() {
      const R = st.result;
      return { ...R, hero: cc && Share.hero(CEN, cc.census), loves: tLoves(), picks: liveIds().map(id => ({ ...st.cards.get(id), _ph: cardNo(id) ? `place ${cardNo(id)}` : 'burned card' })), wallNames: Share.wallNames(R) };
    }
    window.__shareData = shareData;

    // ---- go
    if (API.health === 'waking' && !src) status();
    // a fresh run that hasn't finished in 90 s, or a stream that ends without a result, says so plainly, with Retry
    function fail() {
      if (st.done || st.failed || window.__st !== st) return;   // a later page owns the screen now
      st.failed = true; clearTimeout(st.failT); if (ctl) ctl.abort();
      $('#status').classList.remove('busy');
      $('#s-left').hidden = false; $('#res').classList.add('done');
      $('#leftbody').innerHTML = `<p class="empty">That run didn’t finish. The ranker may be waking up or busy; your three loves are saved in this link.</p>
        <div class="go"><button class="btn solid" id="retry">Retry</button><a class="link" href="#/">change your three</a></div>${tryList()}`;
      $('#retry').addEventListener('click', () => route());
    }
    if (!src) st.failT = setTimeout(fail, 90000);
    ctl = API.run({ city: slug, loves, src, instant: !!set }, onEvent, () => { if (!st.done) { status(); fail(); } });
    st.mock = ctl.mock;
    window.__st = st;
    status(); counter();
  }

  // ------------------------------------------------------------------ the map header
  function mapHeader(box, M, cen, st) {
    // the hero (UNSAID.md §0): St. Louis leads with Mai Lee, named by both AIs; elsewhere the city's own census gem
    const two = cen.mailee_claude && cen.chatgpt && cen.chatgpt.gem && cen.chatgpt.gem.name === cen.mailee_claude.name ? cen.mailee_claude : null;
    const gem = two || cen.gem;
    const gemXY = (M.ai || []).find(a => a.name === gem.name) || (M.outside || []).find(a => a.name === gem.name) || null;
    function draw() {
      box.innerHTML = '';
      const W = box.clientWidth, phone = W < 600;
      const resEl = document.getElementById('res');
      if (phone) {
        // phone: no map and no hero; the link to everything the AIs named, then "7 for you"
        box.style.height = '0'; if (resEl) resEl.classList.remove('leadmap');
        return;
      }
      // desktop: "7 for you" and its one line sit beside the map, so the cards start above the fold
      const story = el(box, 'div', `position:absolute;left:${Math.round(W * .58)}px;top:50%;transform:translateY(-50%);width:${Math.round(W * .42)}px`);
      story.className = 'maplead';
      story.innerHTML = st.lead || '';
      if (resEl) resEl.classList.toggle('leadmap', !!st.lead);
      const H = 380, mw = W * .56;
      const holder = el(box, 'div', `position:absolute;left:0;top:0;height:${H}px;width:${Math.round(mw)}px`);
      holder.className = 'mapfade';      // the dots fade out at the edges instead of stopping at a hard line
      box.style.height = H + 'px';
      const ctx = UM.canvas(holder, mw, H);
      // the frame takes in every card (the pool reaches past the city, e.g. North County) and the gem; a dot is never moved
      const cardsXY = [...st.cards.values()].filter(c => c.lat != null).concat(gemXY ? [gemXY] : []);
      const P = UM.projection(UM.frame(M, cardsXY), { x: mw * .22, y: 10, w: mw * .7, h: H - 20 });
      const ai = M.ai, cmax = Math.max(...ai.map(a => a.count)), dmax = 28;
      const dense = M.places.length > 3000;   // New York: ~20k dots, smaller and without the haze
      UM.dots(ctx, M, P, dense ? { d: 1.3, alpha: .55 } : { d: 2.8, glow: 10 });
      ai.slice().sort((a, b) => a.count - b.count).forEach(a => { const [x, y] = P(a.lon, a.lat); UM.disc(ctx, x, y, UM.discD(a.count, cmax, dmax, 3), st.done ? .55 : .85); });
      // the seven's pins and number labels; a label that would sit on another pin or label moves round its pin
      const boxes = [], hit = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
      const ids = st.done ? st.slots : st.order.slice(0, 7);
      const pins = ids.map((id, i) => { const c = st.cards.get(id); if (!c || c.lat == null) return null; const [x, y] = P(c.lon, c.lat); boxes.push({ x: x - 6, y: y - 6, w: 12, h: 12 }); return { id, i, x, y }; }).filter(Boolean);
      pins.forEach(({ id, i, x, y }) => {
        const k = st.struck.get(id), byAI = (k && !k.human) || st.burned.some(b => b.card_id === id), byYou = k && k.human;
        UM.seven(ctx, x, y, byYou ? .45 : 1, 9, 3, byAI ? UM.C.red : UM.C.white);
        const t = String(i + 1), w = 7 * t.length + 2, h = 11;
        const at = [[x + 9, y - 5], [x - 9 - w, y - 5], [x - w / 2, y - 19], [x - w / 2, y + 8]].map(([lx, ly]) => ({ x: lx, y: ly, w, h }))
          .find(b => !boxes.some(o => hit(b, o) && !(o.x === x - 6 && o.y === y - 6))) || { x: x + 9, y: y - 5, w, h };
        boxes.push(at);
        el(holder, 'div', `top:${at.y}px;left:${at.x}px`, t).className = 'lab num' + (byAI ? ' x' : byYou ? ' xi' : '');
      });
      // the AIs' gem: its ring always; its name on a leader only where it collides with nothing
      if (gemXY) {
        const [x, y] = P(gemXY.lon, gemXY.lat), r = UM.discD(gemXY.count || cmax, cmax, dmax, 3) / 2;
        if (!ai.includes(gemXY)) UM.disc(ctx, x, y, r * 2, .85);
        UM.ring(ctx, x, y, r + 5, 1.4);
        const lx = Math.min(P.bounds.x0, x - r - 30) - 14, tw = 8.2 * gem.name.length;
        const lb = { x: lx - tw, y: y - 10, w: tw + (x - r - 5 - lx), h: 20 };
        if (lx - tw > 0 && !boxes.some(o => hit(lb, o))) {
          UM.leader(ctx, x - r - 5, y, lx + 4, y, UM.C.red, .8);
          el(holder, 'div', `top:${y - 9}px;right:${Math.round(mw) - lx}px;font-size:16px;text-align:right`, `<span class="n">${esc(gem.name).replace("'", '’')}</span>`).className = 'lab red';
        }
      }
      // the legend, under the map
      const lg = el(box, 'div', `position:absolute;left:0;top:${H + 4}px;width:${W}px`,
        `<span><i class="k g"></i>places to eat and drink (OpenStreetMap)</span><span><i class="k r"></i>places the AIs named, by how often</span><span><i class="k w"></i>yours, numbered like the cards</span>`);
      lg.className = 'maplegend';
      box.style.height = (H + 30) + 'px';
    }
    draw();
    let raf = 0;
    return () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(draw); };
  }

  // ------------------------------------------------------------------ sheets
  function openSheet(html) {
    closeSheet();
    const veil = el(document.body, 'div', null); veil.className = 'veil';
    const sh = el(document.body, 'div', null, `<button class="close">close ✕</button>` + html); sh.className = 'sheet';
    sh.setAttribute('role', 'dialog');
    veil.addEventListener('click', closeSheet);
    sh.querySelector('.close').addEventListener('click', closeSheet);
    document.body.style.overflow = 'hidden';
  }
  function closeSheet() { document.querySelectorAll('.veil, .sheet').forEach(n => n.remove()); document.body.style.overflow = ''; }
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeSheet(); });
  window.__open = { card: () => view.querySelector('.card') && view.querySelector('.card').click() };

  // ------------------------------------------------------------------ routes
  function route() {
    closeSheet();
    const h = location.hash || '#/';
    if (h.startsWith('#/r')) resultView(new URLSearchParams(h.split('?')[1] || ''));
    else inputView();
    window.scrollTo(0, 0);
  }
  window.addEventListener('hashchange', route);
  route();
  window.__ready = true;
})().catch(e => { window.__error = String(e && e.stack || e); window.__ready = true; console.error(e); });
