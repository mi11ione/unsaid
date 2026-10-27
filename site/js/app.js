/* UNSAID · S1 input, S2 run → result, S3 card back, S4 not a popularity filter, share. UNSAID.md §2.
   Every number on screen comes from data (the stream, the result, census.json); a ⟦placeholder⟧ only ever
   stands for a null field. Mock data is always marked MOCK. */
(async function () {
  const { el, esc, ph, et, hhmm } = UM;
  const $ = (s, r = document) => r.querySelector(s);
  const [CFG, CEN, TRY] = await Promise.all([UM.json('data/config.json'), UM.json('data/census.json'), UM.json('data/try.json')]);
  API.ping(); // wake the engine while the visitor types (§3.9)
  const view = $('#view'), topEl = $('#top');
  const WORD = ['no', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine'];
  const word = (n, cap) => { const w = WORD[n] ?? String(n); return cap ? w[0].toUpperCase() + w.slice(1) : w; };
  const TITLE = new Set(['movie', 'tv_show', 'book', 'podcast', 'videogame', 'film', 'show']);
  const isPhone = () => matchMedia('(max-width: 720px)').matches;
  // a chip's kind for people: the server's type_label ("artist"), else the tail of a Qloo URN
  const tl = c => c && (c.type_label || (c.type ? String(c.type).split(':').pop() : null));
  const urlTok = (() => { const t = new URLSearchParams(location.search).get('token'); return t ? `token=${encodeURIComponent(t)}&` : ''; })();
  let ctl = null;

  function topbar({ city, loves, mock } = {}) {
    topEl.innerHTML = `<a class="mark" href="#/"><s>UN</s>SAID</a>` +
      (city ? `<span class="slug">${esc(city)} · eat &amp; drink</span>` : '') +
      (loves ? `<span class="chips">${loves.map(l => `<span class="chip${l.dead ? ' dead' : ''}">${l.label == null ? ph(null, 'love') : esc(l.label)}${tl(l) ? ` <i>${esc(tl(l))}</i>` : ''}</span>`).join('')}</span>` : '') +
      `<span class="grow"></span>` + (mock ? `<span class="mock">${esc(mock)}</span>` : '');
  }

  function tryList(head = 'Or try one (instant):') {
    return `<div class="try"><h3>${head}</h3><ul>` + TRY.sets.map(s => {
      const loves = s.loves.map(l => l == null ? ph(null, 'love') : esc(l)).join(' · ');
      const inner = `<b>${esc(s.label)}</b><span class="when">ran ${ph(et(s.ran), 'date')}</span><span class="dim">${loves}</span>` + (s.mock ? '<span class="mock">mock</span>' : '');
      return `<li>${s.src ? `<a href="#/r?set=${encodeURIComponent(s.id)}">${inner}</a>` : `<span class="row off">${inner}</span>`}</li>`;
    }).join('') + '</ul></div>';
  }

  // ------------------------------------------------------------------ S1 · input
  const FIELDS = [
    { ph: 'an artist you’d play loud', hint: 'artist' },
    { ph: 'a film or show you can quote', hint: 'movie' },
    { ph: 'something you’d order', hint: null },
  ];
  const s1 = { loves: [null, null, null], city: null };

  function inputView() {
    if (ctl) { ctl.abort(); ctl = null; }
    topbar({});
    view.innerHTML = `<section class="s1">
      <h1>Everything the AIs tell everyone, <s>crossed out</s>.</h1>
      <div class="fields">
        ${FIELDS.map((f, i) => `<div class="fld"><span class="n">0${i + 1}</span><input data-i="${i}" placeholder="${esc(f.ph)}" autocomplete="off" spellcheck="false"><div class="res" id="res${i}"></div></div>`).join('')}
      </div>
      <div class="helper">or anything: a bar, a book, a team</div>
      <div class="fields" style="margin-top:18px"><div class="fld"><span class="n">in</span><input id="city" placeholder="a city" autocomplete="off" spellcheck="false"><div class="res" id="resc"></div></div></div>
      <div class="go"><button class="btn solid" id="cross" disabled>Cross out</button></div>
      ${tryList()}
      <div class="legal">Your three loves go to Qloo and to Gemini’s free tier (Google may use free-tier prompts to improve its products). Don’t type anything personal. 18+.</div>
    </section>`;
    view.querySelectorAll('input[data-i]').forEach(inp => {
      const i = +inp.dataset.i;
      if (s1.loves[i]) { inp.value = s1.loves[i].text; drawLove(i); }
      inp.addEventListener('blur', () => resolveLove(i, inp.value));
      inp.addEventListener('input', () => { if (s1.loves[i] && s1.loves[i].text !== inp.value) { s1.loves[i] = null; drawLove(i); } });
    });
    const ci = $('#city');
    if (s1.city) { ci.value = s1.city.text; drawCity(); }
    ci.addEventListener('blur', () => resolveCity(ci.value));
    ci.addEventListener('input', () => { if (s1.city && s1.city.text !== ci.value) { s1.city = null; drawCity(); } });
    $('#cross').addEventListener('click', go);
    gate();
  }

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
      box.innerHTML = `<span class="chip">${esc(L.chip.label)}${tl(L.chip) ? ` · <i>${esc(tl(L.chip))}</i>` : ' · <i>as typed</i>'}</span>` +
        (alts.length ? `<button data-a="toggle">other matches</button>` : '') + (L.r.mock ? '<span class="mock">mock</span>' : '') +
        (L.open ? `<span class="alts">${alts.map((a, k) => `<button data-a="${k}">${esc(a.label)} (${esc(tl(a) || a.kind)})</button>`).join('')}</span>` : '');
    } else if (L.r.status === 'needs_input') {
      // amber chip: "rib tips → Rib tips (dish)? · other"
      const c = L.r.chip, alts = L.r.alternatives || [];
      box.innerHTML = `<span class="need">${esc(L.text)} → <button data-a="accept">${esc(c.label)} (${esc(tl(c) || c.kind)})?</button> · <button data-a="toggle">other</button></span>` +
        (L.r.mock ? '<span class="mock">mock</span>' : '') +
        (L.open ? `<span class="alts">${alts.map((a, k) => `<button data-a="${k}">${esc(a.label)} (${esc(tl(a) || a.kind)})</button>`).join('')}</span>` : '');
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

  async function resolveCity(text) {
    text = text.trim();
    if (!text) { s1.city = null; return drawCity(); }
    if (s1.city && s1.city.text === text) return;
    s1.city = { text, pending: true }; drawCity();
    const r = await API.resolve('city', text);
    if (!s1.city || s1.city.text !== text) return;
    s1.city = { text, r, city: r.status === 'ok' ? r.city : null };
    drawCity();
  }
  function drawCity() {
    const box = $('#resc'); if (!box) return;
    const C = s1.city;
    if (!C) box.innerHTML = '';
    else if (C.pending) box.innerHTML = '<span class="faint">looking up…</span>';
    else if (C.city) box.innerHTML = `<span class="chip">${esc(C.city.name)}${C.city.region ? ` <i>${esc(C.city.region)}</i>` : ''}</span>` + (C.r.mock ? '<span class="mock">mock</span>' : '');
    else if (C.r.status === 'needs_input') {
      // "Richmond → Staten Island? No: Richmond, Virginia"
      // "Richmond → Staten Island? No: Richmond, Virginia"
      const all = C.r.alternatives || [];
      const guess = C.r.city || all[0], rest = C.r.city ? all : all.slice(1), off = C.r.city ? 0 : 1;
      const nm = a => esc(a.disamb || a.name);
      box.innerHTML = `<span class="need">${esc(C.text)} → <button data-a="guess">${nm(guess)}?</button>` +
        (rest.length ? ` No: ${rest.map((a, k) => `<button data-a="${k + off}">${nm(a)}</button>`).join(' · ')}` : '') + '</span>' + (C.r.mock ? '<span class="mock">mock</span>' : '');
    }
    box.querySelectorAll('button').forEach(b => b.addEventListener('mousedown', e => e.preventDefault()));
    box.querySelectorAll('button').forEach(b => b.addEventListener('click', () => {
      C.city = b.dataset.a === 'guess' ? (C.r.city || C.r.alternatives[0]) : C.r.alternatives[+b.dataset.a];
      $('#city').value = C.text = C.city.disamb || C.city.name;
      drawCity();
    }));
    gate();
  }
  function gate() {
    const b = $('#cross'); if (!b) return;
    b.disabled = !(s1.loves.every(l => l && l.chip) && s1.city && s1.city.city);
  }
  function go() {
    const loves = s1.loves.map(l => l.chip);
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
    const cen = cc && CEN[cc.census];
    await API.ping();

    const st = {
      slug, cityName, loves, wall: new Map(), asks: new Map(), U: null, calls: null, cards: new Map(), result: null, status: null,
      burnAsking: false, burned: [], struck: new Map(), slots: [], reserves: [], risen: new Map(), done: false, fake: false,
      mock: false, t0: Date.now(), firstServerEvent: false, order: [],
    };
    topbar({ city: cityName, loves });
    view.innerHTML = `<div class="res" id="res">
      <div class="maphead" id="maphead"></div>
      <div class="status" id="status"><span class="live"></span><span id="stxt"></span></div>
      <div class="note" id="notes"></div>
      <section class="sec" id="s-wall">
        <div class="sh"><h2>Everyone gets these</h2><span class="sub">Good places. Every AI sends everyone here.</span>
          <div class="tr"><div class="counter" id="counter"></div><div class="counter-cap">names the AIs gave everyone · left for you, ranked by Qloo</div></div></div>
        <div class="fieldwrap" id="fw"><div class="field" id="field"></div>
          <button class="showall" id="showall"></button>
          <button class="showrow" id="showrow"><span>everything the AI named, <span class="red">crossed out</span></span><span class="dim">show ›</span></button></div>
      </section>
      <div class="burnline" id="burn"></div>
      <section class="sec" id="s-left" hidden>
        <div class="sh"><h2>Left for you</h2><span class="sub"></span><div class="tr cap">for-you order</div></div>
        <div id="leftbody"></div>
      </section>
    </div>`;
    $('#showrow').addEventListener('click', () => $('#fw').classList.remove('collapsed'));
    $('#showall').addEventListener('click', () => $('#fw').classList.remove('clipped'));

    // ---- map header
    const mapData = cc && cc.map ? await UM.json(cc.map).catch(() => null) : null;
    let mapDraw = () => {};
    if (mapData && cen) mapDraw = mapHeader($('#maphead'), mapData, cen, st);
    window.addEventListener('resize', () => mapDraw(), { passive: true });

    // ---- the field
    const fieldEl = $('#field');
    const wn = w => w.name ? esc(w.name) : ph(null, w.ph || 'name');  // a wall item with no name is a fictional placeholder (mock)
    function addAsk(w) {
      const key = (w.provider || '') + '|' + (w.phrasing_id || '') + '|' + (w.asked_at || '');
      if (!st.asks.has(key)) st.asks.set(key, { provider: w.provider, model: w.model, phrasing: w.phrasing, asked_at: w.asked_at, lane: w.lane, names: 0 });
      st.asks.get(key).names++;
    }
    function addName(w) {
      const k = w.norm || Matcher.norm(w.name);
      addAsk(w);
      if (st.wall.has(k)) { const o = st.wall.get(k); o.n = (o.n || 1) + 1; if (o.lane !== 'live' && w.lane === 'live') { o.lane = 'live'; o.el.classList.add('live'); } return; }
      const o = { ...w, norm: k, n: 1, outcome: null };
      o.el = el(fieldEl, 'span', null, `<button title="">${wn(w)}</button>`);
      o.el.className = 'nm' + (w.lane === 'live' ? ' live' : '');
      o.el.querySelector('button').addEventListener('click', () => nameSheet(o));
      st.wall.set(k, o);
    }
    function setOutcome(k, outcome, reason, qid) {
      const o = st.wall.get(k); if (!o) return;
      o.outcome = outcome; o.reason = reason; o.qloo_id = qid ?? o.qloo_id;
      o.el.classList.toggle('x', outcome === 'struck');
      o.el.classList.toggle('dimmed', outcome === 'dimmed');
      const sup = o.el.querySelector('sup');
      if (sup) sup.remove();
      if (outcome === 'dimmed') {
        const why = reason === 'not in pool' ? (st.R_mi != null ? `not in your ${st.R_mi} mi pool` : (st.done ? `not in your ${ph(null, 'R')} mi pool` : 'not in your pool')) : esc(reason || '');
        el(o.el, 'sup', null, why);
      }
    }

    // the dated city wall streams from static data first (within 1 s), whatever the engine is doing
    if (cc && cc.wall) {
      UM.json(cc.wall).then(W => {
        const names = W.answers.flatMap(a => a.names.map(n => ({ name: n, provider: a.provider, model: a.model, phrasing_id: a.phrasing_id, phrasing: a.phrasing, asked_at: a.asked_at, lane: a.lane })));
        const step = Math.max(1, Math.floor(names.length / 40));
        for (let i = 0; i < names.length; i += step) setTimeout(() => { if (!st.reconciled) { names.slice(i, i + step).forEach(addName); counter(); status(); } }, (i / names.length) * 900);
      }).catch(() => {});
    }

    // ---- counters, status, notes
    const liveIds = () => st.slots.filter(id => !st.struck.has(id));
    function counter() {
      const W = st.result && st.result.counts && st.result.counts.wall != null ? st.result.counts.wall : st.wall.size;
      $('#showall').textContent = `show all ${W} ›`;
      $('#counter').innerHTML = `<span class="w">${W}</span>` + (st.done && st.result && (st.slots.length || st.result.status === 'empty_none') ? `<span class="ar">→</span>${liveIds().length}` : '');
    }
    function statusLine() {
      const s = st.status && st.status.state;
      const R = st.result, D = R && R.diag;
      // the server's own §2.2 copy wins when it sends it (status events' text, result.notes); otherwise the same copy is built here
      const SERVER_STATES = ['queued', 'waking', 'dated_only', 'partial', 'degraded', 'limited', 'ranking'];
      if (s === 'unauthorized') return 'needs the token from the testing instructions: add ?token=… to this page’s address';
      if (R && R.notes && R.notes.length) {
        const keep = [...new Set(R.notes.map(n => n.text).filter(Boolean))];
        if (keep.length) return keep.map(esc).join(' · ');
      }
      if (!st.done && s && SERVER_STATES.includes(s) && st.status.text) return esc(st.status.text);
      if (s === 'waking' && !st.done) return 'waking the ranker · about a minute';
      if (s === 'queued') { const a = st.status.ahead; return `${a == null ? ph(null, 'n') : word(a, true)} run${a === 1 ? '' : 's'} ahead of yours · about ${ph(st.status.eta_s, 's')} s`; }
      if (API.health === 'waking' && !st.firstServerEvent) return 'waking the ranker · about a minute';
      const items = [...st.asks.values()];
      const datedAt = items.filter(a => a.lane !== 'live' && a.provider).map(a => a.asked_at).filter(Boolean).sort().pop() || null;
      const fl = (R && R.flags) || [];
      if (s === 'dated_only' || (R && R.status === 'dated_only') || fl.includes('dated_only')) return `All answers dated ${ph(et(datedAt), 'date')} · no live ask right now`;
      if (R && (R.status === 'partial' || fl.includes('partial'))) {
        const n = R.counts && (R.counts.answers ?? R.counts.asks);
        const ais = new Set(items.map(a => a.provider)).size;
        return `${ph(n, 'answers')} answers · ${ais} of ${CFG.lanes.length} AIs`;
      }
      const order = p => { const i = CFG.lanes.indexOf(p); return i < 0 ? 99 : i; };
      const dated = [...new Set(items.filter(a => a.lane !== 'live' && a.provider).map(a => a.provider))].sort((a, b) => order(a) - order(b));
      const live = [...new Set(items.filter(a => a.lane === 'live' && a.provider).map(a => a.provider))].sort((a, b) => order(a) - order(b));
      const parts = [];
      if (dated.length) parts.push(`${dated.map(esc).join(', ')}: asked ${ph(et(datedAt), 'date')}`);
      if (live.length) parts.push(`${live.map(esc).join(', ')}: asked just now`);
      const U = (R && R.counts && R.counts.U) ?? st.U;
      if (st.done && R && R.counts) parts.push(`Qloo ranked your ${ph(U, 'U')} places · ${ph(D && D.qloo_calls, 'N')} calls`);
      else if (st.calls) parts.push(`Qloo is ranking your ${U != null ? U + ' ' : ''}places · ${st.calls.done} of ${ph(st.calls.total, 'N')} calls`);
      return parts.join(' · ');
    }
    function status() {
      $('#stxt').innerHTML = statusLine();
      $('#status').classList.toggle('idle', st.done);
      const mock = st.fake || st.mock;
      topbar({ city: cityName, loves: (st.result && st.result.loves) || loves, mock: mock ? (st.fake ? 'mock data' : 'mock stream · no server') : null });
    }
    function notes() {
      const R = st.result; const out = [];
      if (R && R.status === 'degraded' && st.slots.length) out.push(`from ${ph(R.stored_at || et(R.diag && R.diag.as_of), 'date time')} · Qloo is slow right now`);
      if (R) {
        const live = (R.loves || []).filter(l => !l.dead).length;
        (R.loves || []).filter(l => l.dead).forEach(l => out.push(`${esc(l.label)} doesn’t change ${esc(cityName)} restaurants much; ranked on the other ${word(live)}.`));
      }
      $('#notes').innerHTML = out.map(t => `<div>${t}</div>`).join('');
    }

    // ---- burn beat
    function burnLine() {
      const b = $('#burn');
      if (st.burned.length) {
        b.innerHTML = st.burned.map(x => {
          const c = st.cards.get(x.card_id) || {}, r = x.replaced_by && st.cards.get(x.replaced_by);
          const ci = cardNo(x.card_id), ri = r ? cardNo(r.id) : null;
          return `<span class="red">${esc(x.by || 'An AI')} just named ${c.name ? esc(c.name) : ph(null, `place ${ci}`)}</span> when asked about ${ph(c.neighbourhood ?? x.neighbourhood, 'neighbourhood')} · ${x.at ? esc(UM.et(x.at, false).replace(' ET', '')) : (st.fake || st.mock ? ph(null, 'time') : esc(x.seen))} · burned.` +
            (r ? ` ${r.name ? esc(r.name) : ph(null, `place ${ri}`)} takes its place.` : '');
        }).join('<br>');
      } else if (st.done && st.result && st.result.burn && st.result.burn.asked && st.result.burn.asked.length) {
        b.innerHTML = `Asked about all ${st.result.burn.asked.length} streets. None named.`;
      } else if (st.burnAsking) b.innerHTML = '<span class="dots">Asking about each card’s street</span>';
      else b.innerHTML = '';
    }
    const cardNo = id => { const i = st.order.indexOf(id); return i < 0 ? '?' : i + 1; };

    // ---- events
    function onEvent(e) {
      if (e.type !== 'wall_name') st.firstServerEvent = true;
      if (e.flags && e.flags.includes('fake')) st.fake = true;
      switch (e.type) {
        case 'status': st.status = e; break;
        case 'wall_name': addName(e); break;
        case 'pool': st.U = e.U; if (e.R_mi != null) st.R_mi = e.R_mi; break;
        case 'strike': setOutcome(e.norm, e.outcome, e.reason, e.qloo_id); break;
        case 'calls': st.calls = e; break;
        case 'card': st.cards.set(e.id, e); if (!st.order.includes(e.id)) st.order.push(e.id); mapDraw(); break;
        case 'burn':
          if (e.phase === 'asking') st.burnAsking = true;
          if (e.card_id) { st.burned.push({ ...e, seen: hhmm() }); }
          burnLine(); mapDraw(); break;
        case 'done': finish(e.result); break;
      }
      counter(); status();
    }
    function finish(R) {
      st.result = R; st.done = true;
      if ((R.flags || []).includes('fake')) st.fake = true;
      st.R_mi = R.counts && R.counts.R_mi;
      if (Array.isArray(R.wall) && !st.mock) {
        // the static dated wall streamed first; the server's wall is what was actually crossed out, so it wins
        const used = new Set(R.wall.map(w => w.norm || Matcher.norm(w.name)));
        [...st.wall.keys()].forEach(k => { if (!used.has(k)) { st.wall.get(k).el.remove(); st.wall.delete(k); } });
        st.reconciled = true;
        st.asks.clear();
      }
      const fresh = Array.isArray(R.wall) && !st.mock;
      (R.wall || []).forEach(w => {
        const k = w.norm || Matcher.norm(w.name);
        if (!st.wall.has(k)) addName({ ...w, norm: k }); else if (fresh) addAsk(w);
        setOutcome(k, w.outcome, w.reason, w.qloo_id);
      });
      [...(R.picks || []), ...(R.reserves || []), ...(R.known || [])].forEach(c => { st.cards.set(c.id, c); if (!st.order.includes(c.id)) st.order.push(c.id); });
      (R.burn && R.burn.burned || []).forEach(b => { if (!st.burned.find(x => x.card_id === b.card_id)) st.burned.push({ ...b, seen: hhmm() }); if (b.replaced_by) st.risen.set(b.replaced_by, 'rose in its place'); });
      st.slots = (R.picks || []).map(c => c.id);
      st.reserves = (R.reserves || []).map(c => c.id);
      burnLine(); notes(); left(); counter(); status(); mapDraw();
      if (isPhone()) $('#fw').classList.add('collapsed'); else if ($('#field').scrollHeight > 260) $('#fw').classList.add('clipped');
      $('#res').classList.add('done');
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
      if (R.status === 'error' || R.status === 'unauthorized') {
        body.innerHTML = `<p class="empty">${R.status === 'unauthorized' ? 'needs the token from the testing instructions: add ?token=… to this page’s address' : esc(R.note || 'That didn’t go through.')}</p><div class="go"><a class="btn" href="#/">Fix it</a></div>`;
        return;
      }
      if (R.status === 'limited') { body.innerHTML = `<p class="empty">Fresh runs are limited so everyone gets through. These open instantly:</p>${tryList('')}`; return; }
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
        : `<div class="lead"><span class="n">${n}</span><span class="c">None of these ${n} came up in ${ph(asks, 'ASKS')} asks about ${esc(cityName)} · ${ph(date, 'date')}.</span></div>`;
      body.innerHTML = lead + `<div class="cards" id="cards"></div>
        <div class="dare"><label for="dare">Ask any AI yourself. Paste what it says: any of these ${n} it names burns.</label>
          <textarea id="dare" placeholder="paste an answer here" spellcheck="false"></textarea><div class="out" id="dareout"></div></div>
        <div class="links"><button class="link" id="lnk-pop">not a popularity filter →</button><button class="link" id="lnk-share">share</button></div>`;
      const cardsEl = $('#cards');
      st.slots.forEach(id => cardsEl.appendChild(cardEl(id)));
      $('#lnk-pop').addEventListener('click', popSheet);
      $('#lnk-share').addEventListener('click', shareSheet);
      let t = null;
      $('#dare').addEventListener('input', e => { clearTimeout(t); t = setTimeout(() => dare(e.target.value), 250); });
    }

    function cardHTML(c, i, known) {
      const R = st.result || {}, flags = R.flags || [];
      const flat = flags.includes('flat');
      const rank = c.tied || c.fit_rank == null ? '' : `<b>#${c.fit_rank}</b>for you`;
      const any = flat ? '' : `<span class="any">#${ph(c.any_rank, 'ANY')} for anyone</span>`;
      const tag = st.struck.get(c.id), rose = st.risen.get(c.id);
      return `<div class="card${tag ? ' struck' : ''}${rose ? ' risen' : ''}" data-id="${esc(c.id)}">
        <div class="row1"><span>${String(i + 1).padStart(2, '0')}</span><span>${c.rating == null ? ph(null, 'rating') : Number(c.rating).toFixed(1)} · ${c.open == null ? ph(null, 'open') : (c.open ? 'open' : 'closed')}</span></div>
        <div class="hood">${ph(c.neighbourhood, 'neighbourhood')}</div>
        <div class="name">${c.name ? esc(c.name) : ph(null, `place ${cardNo(c.id)}`)}</div>
        <div class="what">${ph(c.what, 'what it is')}</div>
        ${known ? '' : `<div class="rk">${rank}${any}</div>
        <div class="because">because you love<b>${ph(c.because, 'love')}</b></div>`}
        <div class="tag${rose && !tag ? ' rose' : ''}">${tag ? esc(tag.text) : (rose ? esc(rose) : '')}</div>
      </div>`;
    }
    function cardEl(id) {
      const c = st.cards.get(id);
      const wrap = document.createElement('div');
      wrap.innerHTML = cardHTML(c, st.slots.indexOf(id));
      const node = wrap.firstElementChild;
      let timer = null, held = false;
      const cancel = () => { clearTimeout(timer); node.classList.remove('holding'); };
      node.addEventListener('pointerdown', e => {
        if (st.struck.has(id) || e.button > 0) return;
        held = false; node.classList.add('holding');
        timer = setTimeout(() => { held = true; node.classList.remove('holding'); strike(id, `struck by you · ${hhmm()}`); }, 900);
      });
      ['pointerup', 'pointerleave', 'pointercancel'].forEach(ev => node.addEventListener(ev, cancel));
      node.addEventListener('contextmenu', e => e.preventDefault());
      node.addEventListener('click', () => { if (held) { held = false; return; } cardSheet(id); });
      return node;
    }
    function redrawCard(id) {
      const old = view.querySelector(`.card[data-id="${CSS.escape(id)}"]`); if (!old) return;
      old.replaceWith(cardEl(id));
    }
    // a struck card stays where it was, struck; the next reserve rises in under it
    function strike(id, text) {
      st.struck.set(id, { text });
      redrawCard(id);
      const rid = st.reserves.shift();
      if (rid) {
        st.risen.set(rid, 'rose in its place · a reserve no AI named');
        st.slots.splice(st.slots.indexOf(id) + 1, 0, rid);
        const after = view.querySelector(`.card[data-id="${CSS.escape(id)}"]`);
        after.after(cardEl(rid));
      }
      counter(); mapDraw();
      return rid;
    }
    function dare(text) {
      const out = $('#dareout');
      if (!text.trim()) { out.innerHTML = ''; return; }
      const ids = liveIds();
      const hits = Matcher.find(text, ids.map(id => st.cards.get(id).name));
      if (!hits.length) { out.innerHTML = `None of these ${ids.length} named.`; return; }
      out.innerHTML = hits.map(h => {
        const id = ids[h.index], c = st.cards.get(id);
        const rid = strike(id, `named in your paste · ${hhmm()}`);
        const r = rid && st.cards.get(rid);
        return `<span class="red">It named ${esc(c.name)} · burned.</span>` + (r ? ` ${r.name ? esc(r.name) : ph(null, `place ${cardNo(rid)}`)} takes its place.` : '');
      }).join('<br>');
    }

    // ---- S3 · card back
    function cardSheet(id) {
      const c = st.cards.get(id), R = st.result, flags = R.flags || [];
      const flat = flags.includes('flat'), thin = flags.includes('thin_taste');
      const U = c.U ?? (R.counts && R.counts.U), Rmi = R.counts && R.counts.R_mi;
      const ns = c.never_said || {};
      const fit = c.tied ? null : c.fit_rank;
      const head = fit == null ? (c.name ? esc(c.name) : ph(null, `place ${cardNo(id)}`)) + '.'
        : `#${fit} for you.` + (flat ? '' : ` <span class="any">#${ph(c.any_rank, 'ANY')} for anyone.</span>`);
      const pct = r => Math.max(0, Math.min(100, ((r - 1) / Math.max(1, (U || 1) - 1)) * 100));
      const pos = r => `${pct(r)}%`;
      // a label near either end hangs inward, so it never leaves the sheet
      const lab = r => pct(r) < 12 ? `left:${pct(r)}%;transform:none` : pct(r) > 88 ? `right:${100 - pct(r)}%;transform:none` : `left:${pct(r)}%`;
      const slider = flat || U == null ? '' : `<div class="slider"><div class="track"></div>
          ${fit != null ? `<div class="tick" style="left:${pos(fit)}"></div><div class="tl" style="${lab(fit)}">#${fit} for you</div>` : ''}
          ${c.any_rank != null ? `<div class="tick any" style="left:${pos(c.any_rank)}"></div><div class="tl any" style="${lab(c.any_rank)}">#${c.any_rank} for anyone</div>` : ''}
          <div class="end" style="left:0">#1</div><div class="end" style="right:0">#${U}</div></div>`;
      const holds = c.holds != null && c.n_loves != null && c.holds >= c.n_loves ? 'holds even if you drop any one love'
        : `holds without ${c.holds_without ? [].concat(c.holds_without).map(esc).join(' or ') : ph(null, 'love')}`;
      const st3 = st.struck.get(id);
      openSheet(`
        <div class="cap">${esc(cityName)} · card ${cardNo(id)} · ${c.name ? esc(c.name) : ph(null, `place ${cardNo(id)}`)} · ${ph(c.neighbourhood, 'neighbourhood')}</div>
        <h1>${head}</h1>
        ${st3 ? `<div class="red">${esc(st3.text)}</div>` : ''}
        ${flat ? '<div class="sub">your loves barely move this city’s order</div>' : ''}
        ${thin ? `<div class="sub">out of ${ph(U, 'U')}; many places tie for you here</div>` : ''}
        <div class="blk"><div class="sh"><h2>Never said</h2></div>
          <p>Named 0 times in ${ph(ns.asks, 'ASKS')} asks: ${ph(ns.city_asks, 'n')} about ${esc(cityName)}, ${ph(ns.street_asks, 'm')} about ${ph(c.neighbourhood, 'neighbourhood')} · ${ph(et(ns.as_of), 'date')}.</p></div>
        <div class="blk"><div class="sh"><h2>Fits you</h2></div>${slider}
          <p class="dim">of ${ph(U, 'U')} places within ${ph(Rmi, 'R')} mi, rated ${CFG.floor.rating}+, open. ‘Anyone’ is Qloo’s popularity order of the same places.</p></div>
        <div class="blk"><div class="sh"><h2>Because</h2></div>
          <div class="big1">${ph(c.because, 'love')}</div><p class="dim">${holds}</p></div>
        <div class="blk">${c.url ? `<a class="btn solid" href="${esc(c.url)}" target="_blank" rel="noopener">Go ↗</a>` : `<span class="btn off">Go ↗ ${ph(null, 'url')}</span>`}
          <p class="dim">No place can pay to be picked.</p></div>
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
      openSheet(`<div class="cap">everyone gets these</div><h1 style="font-size:32px"><span style="text-decoration:line-through;text-decoration-color:var(--red);text-decoration-thickness:2px">${wn(o)}</span></h1>
        <p class="dim">${o.provider ? esc(o.provider) + ' ' + esc(o.model || '') : '<span class="mock">mock</span>'} · ${o.lane === 'live' ? 'asked just now' : 'dated, asked ' + ph(et(o.asked_at), 'date')}</p>
        <p>“${esc(o.phrasing || '')}”</p><p class="dim">named in ${o.n} answer${o.n === 1 ? '' : 's'} here · ${o.qloo_id ? 'Qloo ID ' + esc(o.qloo_id) : 'no Qloo ID'}${o.reason ? ' · ' + esc(o.reason) : ''}</p>`);
    }

    // ---- S4 · not a popularity filter
    function popSheet() {
      const R = st.result, D = R.diag || {}, K = R.counts || {}, F = K.floor || {};
      const cut = K.U != null && K.S != null ? K.U - K.S : null;
      const nm = n => n == null ? null : (typeof n === 'object' ? n.name : n);
      const list = (xs, x) => xs == null ? `<li>${ph(null, 'names')}</li>` : !xs.length ? '<li class="dim">none</li>' : xs.map(n => `<li class="${x ? 'x' : ''}"><span>${nm(n) == null ? ph(null, 'name') : esc(nm(n))}</span></li>`).join('');
      openSheet(`<div class="cap">${esc(cityName)}</div><h1>Not a popularity filter.</h1>
        <div class="cols"><div><div class="sh"><h2>Struck though obscure</h2></div><ul>${list(D.obscure_names ?? D.obscure, true)}</ul></div>
          <div><div class="sh"><h2>Kept though known</h2></div><ul>${list(D.known_names ?? D.known, false)}</ul></div></div>
        <div class="blk"><p>A popularity cap cutting the same ${ph(cut, 'S')} would keep ${ph(D.cap_keep, 'CAP_KEEP')} of the places the AIs named. Its ${st.slots.length} and yours share ${ph(D.cap_shared, 'CAP_SHARED')}.</p>
          <p>Taste vs popularity ρ ${ph(D.rho_tp, 'RHO_TP')}; after the city’s own order is taken away, ρ ${ph(D.rho_res, 'RHO_RES')}.</p>
          <p class="dim">${ph(K.P, 'P')} → ${ph(K.U, 'U')} (closed ${ph(F.closed, 'c')}, below ${CFG.floor.rating} ${ph(F.below_43, 'f')}, outside ${ph(K.R_mi, 'R')} mi ${ph(F.outside_R, 'd')}, not a restaurant or bar ${ph(F.not_venue, 'v')}).</p></div>`);
    }

    // ---- share
    function shareSheet() {
      openSheet(`<div class="cap">share</div><canvas class="sharecv" id="sharecv"></canvas>
        <div class="links"><a class="btn solid" id="dl" download="unsaid.png" href="#">Save image</a>${navigator.share ? '<button class="btn" id="sh">Share</button>' : ''}</div>`);
      const cv = $('#sharecv');
      Share.draw(cv, shareData());
      cv.toBlob(b => {
        const u = URL.createObjectURL(b); $('#dl').href = u;
        const sb = $('#sh');
        if (sb) sb.addEventListener('click', () => navigator.share({ files: [new File([b], 'unsaid.png', { type: 'image/png' })] }).catch(() => {}));
      });
    }
    function shareData() {
      const R = st.result;
      return { ...R, picks: liveIds().map(id => ({ ...st.cards.get(id), _ph: `place ${cardNo(id)}` })), wallNames: [...st.wall.values()].filter(w => w.outcome === 'struck' && w.name).map(w => w.name) };
    }
    window.__shareData = shareData;

    // ---- go
    if (API.health === 'waking' && !src) status();
    ctl = API.run({ city: slug, loves, src }, onEvent, () => { if (!st.done) { status(); } });
    st.mock = ctl.mock;
    window.__st = st;
    status(); counter();
  }

  // ------------------------------------------------------------------ the map header
  function mapHeader(box, M, cen, st) {
    function draw() {
      box.innerHTML = '';
      const W = box.clientWidth, phone = W < 600;
      const story = el(box, 'div', phone ? 'position:relative;margin:18px 0 6px' : `position:absolute;left:${Math.round(W * .56)}px;top:50%;transform:translateY(-50%);width:${Math.round(W * .44)}px`);
      // census_stats.txt:58 (13 of 16) and :46 + :52 (11 of 14), via census.json
      story.innerHTML = `<div style="font:400 ${phone ? 20 : 26}px/1.15 var(--serif)">Ask an AI for a hidden gem in ${esc(cen.city)}.</div>
        <div style="margin-top:10px"><span style="position:relative;font:400 ${phone ? 40 : 54}px/1 var(--serif);color:var(--red);white-space:nowrap">${esc(cen.gem.name).replace("'", '’')}<span style="position:absolute;left:-.04em;right:-.04em;top:56%;height:.07em;background:var(--red);box-shadow:0 0 0 .022em var(--bg)"></span></span></div>
        <div style="margin-top:10px;font:400 ${phone ? 16 : 19}px/1.3 var(--serif)"><span class="red">${cen.gem.hits} times out of ${cen.gem.of}</span>` +
        (cen.plain ? `<br><span class="dim">also on ${cen.plain.hits} of its ${cen.plain.of} plain lists</span>`
          : cen.gem.first != null ? `<br><span class="dim">named first in ${cen.gem.first}</span>` : '') + '</div>';
      const H = phone ? 320 : 430, mw = phone ? W : W * .56;
      const holder = el(box, 'div', `position:relative;height:${H}px;width:${phone ? W : W}px`);
      if (!phone) { box.style.height = H + 'px'; holder.style.position = 'absolute'; holder.style.left = '0'; holder.style.top = '0'; } else box.style.height = 'auto';
      const ctx = UM.canvas(holder, mw, H);
      const P = UM.projection(M, { x: mw * .22, y: 10, w: mw * .7, h: H - 20 });
      const ai = M.ai, cmax = Math.max(...ai.map(a => a.count)), dmax = phone ? 22 : 28;
      const dense = M.places.length > 3000;   // New York: ~20k dots, smaller and without the haze
      UM.dots(ctx, M, P, dense ? { d: phone ? 1 : 1.3, alpha: .55 } : { d: phone ? 2.2 : 2.8, glow: phone ? 7 : 10 });
      ai.slice().sort((a, b) => a.count - b.count).forEach(a => { const [x, y] = P(a.lon, a.lat); UM.disc(ctx, x, y, UM.discD(a.count, cmax, dmax, 3), st.done ? .55 : .85); });
      const g = ai.find(a => a.name === cen.gem.name);
      if (g) {
        const [x, y] = P(g.lon, g.lat), r = UM.discD(g.count, cmax, dmax, 3) / 2;
        UM.ring(ctx, x, y, r + 5, 1.4);
        const lx = P.bounds.x0 - 14;
        UM.leader(ctx, x - r - 5, y, lx + 4, y, UM.C.red, .8);
        el(holder, 'div', `top:${y - 9}px;right:${W - lx}px;font-size:${phone ? 14 : 16}px;text-align:right`, `<span class="n">${esc(cen.gem.name).replace("'", '’')}</span>`).className = 'lab red';
      }
      // the seven, as they land; struck or burned ones in red
      const ids = st.done ? st.slots : st.order.slice(0, 7);
      ids.forEach((id, i) => {
        const c = st.cards.get(id); if (!c || c.lat == null) return;
        const [x, y] = P(c.lon, c.lat);
        const gone = st.struck.has(id) || st.burned.some(b => b.card_id === id);
        UM.seven(ctx, x, y, 1, phone ? 7 : 9, 3, gone ? UM.C.red : UM.C.white);
        el(holder, 'div', `top:${y - 5}px;left:${x + 9}px`, String(i + 1)).className = 'lab num' + (gone ? ' x' : '');
      });
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
