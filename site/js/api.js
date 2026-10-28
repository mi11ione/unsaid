/* UNSAID · talking to /api/* (relative only: no key and no engine URL ever reach the browser).
   With no server (a plain static host, file://, or ?mock=<name>), everything comes from data/mock/ and is marked MOCK. */
(function () {
  const P = new URLSearchParams(location.search);
  const FORCE_MOCK = P.get('mock');          // ?mock=stl-few etc: replay that mock stream
  const FORCE_HEALTH = P.get('health');      // ?health=waking|ok|offline (to see the states without a server)
  const SPEED = Math.max(0.1, +P.get('speed') || 1); // ?speed=10 replays a static stream ten times faster (screenshots)
  let health = null;                         // 'ok' | 'waking' | 'offline'
  // Until the token comes off (30 Oct 23:45 ET) the API needs one. It only ever arrives in this page's own URL
  // (?token=…, from the testing instructions) and is passed through to every relative /api/* call. Never hard-coded.
  const TOKEN = P.get('token');
  const withToken = u => TOKEN ? u + (u.includes('?') ? '&' : '?') + 'token=' + encodeURIComponent(TOKEN) : u;

  async function timed(url, ms, opt = {}) {
    const ac = new AbortController();
    const t = setTimeout(() => ac.abort(), ms);
    try { return await fetch(url, { ...opt, signal: ac.signal, cache: 'no-store' }); } finally { clearTimeout(t); }
  }

  // pinged on load so a sleeping engine wakes while the visitor types (UNSAID.md §3.9)
  async function ping() {
    if (FORCE_HEALTH) return (health = FORCE_HEALTH);
    if (FORCE_MOCK || location.protocol === 'file:') return (health = 'offline');
    try {
      const r = await timed(withToken('/api/health'), 4000);
      if (r.status === 404 || r.status === 405) return (health = 'offline');
      if (r.status === 503) return (health = 'waking');   // the proxy's answer for a cold engine (Retry-After)
      let j = null; try { j = await r.json(); } catch (e) { /* not JSON */ }
      if (j && (j.ok === true || j.state === 'warm' || j.state === 'ok')) return (health = 'ok');
      if (j && j.state === 'waking') return (health = 'waking');
      return (health = r.ok ? 'ok' : 'waking');
    } catch (e) {
      return (health = e.name === 'AbortError' ? 'waking' : 'offline');
    }
  }
  const mockMode = () => !!FORCE_MOCK || health === 'offline';

  let mockResolve = null;
  async function resolve(kind, q, hint) {
    if (!mockMode()) {
      try {
        const u = `/api/resolve?kind=${kind}&q=${encodeURIComponent(q)}` + (hint ? `&type=${encodeURIComponent(hint)}` : '');
        const r = await timed(withToken(u), 8000);
        if (r.ok) return await r.json();
        if (r.status === 401) return { status: 'unauthorized', alternatives: [] };
      } catch (e) { /* fall through to the mock table */ }
    }
    mockResolve = mockResolve || await UM.json('data/mock/resolve.json');
    const hit = (mockResolve[kind] || {})[Matcher.norm(q)];
    if (hit) return { ...hit, mock: true };
    // unknown text offline: kept as typed; the engine decides (CONTRACT: plain text is allowed)
    return kind === 'city'
      ? { status: 'ok', mock: true, city: { id: null, name: q.trim(), slug: Matcher.norm(q).replace(/ /g, '-'), region: null }, alternatives: [] }
      : { status: 'ok', mock: true, chip: { id: null, label: q.trim(), kind: 'text', type: null }, alternatives: [] };
  }

  /* Run one query. onEvent(evt) for each NDJSON line; returns {abort()}.
     src: a static stream (try-these set or mock). Otherwise GET /api/unsaid?city=&loves=. */
  function run({ city, loves, src, instant }, onEvent, onEnd) {
    let stopped = false;
    const timers = [];
    const ctl = { abort() { stopped = true; timers.forEach(clearTimeout); if (ctl.ac) ctl.ac.abort(); }, mock: false };
    const file = src || (mockMode() ? `data/mock/${FORCE_MOCK || 'stl-cedric'}.ndjson` : null);
    if (file) {
      ctl.mock = file.includes('/mock/');
      const slow = /stl-slow/.test(file) ? 2.2 : 1;           // the 'ranking' state needs > 20 s
      const lag = health === 'waking' ? 3500 : 0;             // the waking state: the dated wall first, then the ranker
      fetch(file).then(r => r.text()).then(t => {
        const evs = t.trim().split('\n').map(l => JSON.parse(l));
        // a try-these set is a stored result: it opens at once, replayed in about a second (Devpost: "opens in about a second")
        const span = Math.max(...evs.map(e => (e.t || 0) * slow + lag)) / SPEED;
        const fit = instant ? Math.max(1, span / 1000) : 1;
        evs.forEach(e => {
          const at = (e.type === 'wall_name' ? (e.t || 0) : (e.t || 0) * slow + lag) / SPEED / fit;
          timers.push(setTimeout(() => { if (!stopped) onEvent(e); }, at));
        });
        const end = span / fit + 50;
        timers.push(setTimeout(() => { if (!stopped) onEnd && onEnd(); }, end));
      }).catch(e => onEvent({ type: 'status', state: 'degraded', text: null, error: String(e) }));
      return ctl;
    }
    ctl.ac = new AbortController();
    const q = withToken(`/api/unsaid?city=${encodeURIComponent(city)}&loves=${encodeURIComponent(JSON.stringify(loves))}`);
    (async () => {
      try {
        let r;
        // a cold engine answers 503 + Retry-After through the proxy: say "waking" and try again (about a minute)
        for (let tries = 0; ; tries++) {
          r = await fetch(q, { signal: ctl.ac.signal, headers: { accept: 'application/x-ndjson' } });
          if (r.status !== 503 || tries >= 12) break;
          onEvent({ type: 'status', state: 'waking', text: null, http: 503 });
          const wait = Math.min(15, Math.max(3, +(r.headers.get('retry-after') || 10)));
          await new Promise(res => setTimeout(res, wait * 1000));
          if (stopped) return;
        }
        if (!r.ok || !r.body) {
          let j = null; try { j = await r.json(); } catch (e) { /* */ }
          if (j && j.type) { onEvent(j); return onEnd && onEnd(); }
          const state = r.status === 429 ? 'limited' : r.status === 401 ? 'unauthorized' : r.status === 400 ? 'error' : 'degraded';
          onEvent({ type: 'status', state, text: null, http: r.status });
          // settle the screen on the matching state; the server's note (if any) is shown as is
          onEvent({ type: 'done', result: { status: state, flags: r.status >= 500 ? ['no_cache'] : [], note: j && j.note || null, picks: [], reserves: [], wall: null, counts: null, diag: {} } });
          return onEnd && onEnd();
        }
        const rd = r.body.getReader(), dec = new TextDecoder();
        let buf = '';
        for (;;) {
          const { value, done } = await rd.read();
          if (done) break;
          buf += dec.decode(value, { stream: true });
          let i;
          while ((i = buf.indexOf('\n')) >= 0) {
            const line = buf.slice(0, i).trim(); buf = buf.slice(i + 1);
            if (line) { try { onEvent(JSON.parse(line)); } catch (e) { /* skip a bad line */ } }
          }
        }
        if (buf.trim()) { try { onEvent(JSON.parse(buf)); } catch (e) { /* */ } }
      } catch (e) {
        if (!stopped) onEvent({ type: 'status', state: 'degraded', text: null });
      }
      onEnd && onEnd();
    })();
    return ctl;
  }

  window.API = { ping, resolve, run, mockMode, withToken, get health() { return health; }, FORCE_MOCK };
})();
