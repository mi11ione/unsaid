/* UNSAID · local matcher for the dare box ($0, nothing leaves the page).
   fold / norm / tokens / distinctive / tok_eq are ported 1:1 from engine/unsaid/matcher.py
   (parity checked by media/tools/test_matcher.mjs against the Python on every wall name).
   find(text, names) answers: which of these names does this free text name? When unsure, it strikes. */
(function (root) {
  const GENERIC = new Set(`the a an and of at on in by for with to n
bar bars cafe caffe coffee restaurant restaurants grill grille pub tavern lounge room club kitchen house
deli diner pizza pizzeria bbq smokehouse taproom brewery brewing brewpub co company eatery bistro trattoria
cantina saloon inn hall garden beer wine wines cocktail cocktails bakery shop spirits food foods
gastropub steakhouse steak seafood cuisine chef table tables`.split(/\s+/));
  const LOCATION = new Set(`nyc new york brooklyn manhattan queens bronx st saint louis stl mo ny usa downtown midtown uptown`.split(/\s+/));
  const STOP = new Set([...GENERIC, ...LOCATION]);
  const COMPOUNDS = [
    [/\bsmoke house\b/g, 'smokehouse'], [/\btap room\b/g, 'taproom'], [/\bbar b que\b/g, 'bbq'],
    [/\bbar b q\b/g, 'bbq'], [/\bbarbe?que\b/g, 'bbq'], [/\bbarbecue\b/g, 'bbq'], [/\bb b q\b/g, 'bbq'],
    [/\bsaint\b/g, 'st'], [/\bmount\b/g, 'mt'],
  ];
  // matcher.py SPLIT_HOST / SPLIT_ON_SUFFIX
  const SPLIT_HOST = /\s+(?:at|inside|@|in the|within)\s+|\s+[-–—|]\s+|\s*\(/;
  const SPLIT_ON_SUFFIX = /\s+on (?:the )?\w+(?: \w+)?$/;

  function fold(s) {
    return String(s).normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase()
      .replace(/[’‘`]/g, "'");
  }

  // matcher.py CORP_SUFFIX: trailing Ltd / LLC / Inc / Co / Corp ("Marshas Ltd" == "Marsha's")
  const BARE_POSSESSIVE = /(^|[^a-z0-9'])([a-z0-9]*[a-rt-z0-9])'(?![a-z0-9])/g;
  const CORP_SUFFIX = /(?:\s+(?:and\s+)?(?:ltd|llc|inc|co|corp)\b)+$/;
  function norm(s) {
    s = fold(s).replace(/&/g, ' and ').replace(/\+/g, ' and ');
    s = s.replace(BARE_POSSESSIVE, '$1$2s');   // "Jody B'" == "Jody B's" (matcher.py BARE_POSSESSIVE)
    s = s.replace(/'/g, '');            // apostrophes dropped; a possessive keeps its s
    s = s.replace(/[^a-z0-9]+/g, ' ').replace(/\s+/g, ' ').trim();
    for (const [p, r] of COMPOUNDS) s = s.replace(p, r);
    s = s.replace(/^the /, '');
    return s.replace(CORP_SUFFIX, '') || s;
  }
  const tokens = s => { const n = norm(s); return n ? n.split(' ') : []; };
  function distinctive(s) {
    let t = tokens(s).filter(x => !STOP.has(x));
    if (!t.length) t = tokens(s).filter(x => !GENERIC.has(x));
    return t;
  }
  function head(raw) {
    const f = fold(raw);
    const parts = f.split(SPLIT_HOST).filter(p => p && p.replace(/[ )]/g, ''));
    const h = parts.length ? parts[0].replace(/^[ )]+|[ )]+$/g, '') : f;
    return h.replace(SPLIT_ON_SUFFIX, '');
  }

  // difflib.SequenceMatcher(None, a, b).ratio() for short strings (no autojunk below 200 chars)
  function ratio(a, b) {
    const T = a.length + b.length; if (!T) return 1;
    let M = 0;
    const q = [[0, a.length, 0, b.length]];
    while (q.length) {
      const [alo, ahi, blo, bhi] = q.pop();
      let bi = alo, bj = blo, bk = 0, j2len = {};
      for (let i = alo; i < ahi; i++) {
        const nj = {};
        for (let j = blo; j < bhi; j++) {
          if (a[i] !== b[j]) continue;
          const k = (j2len[j - 1] || 0) + 1; nj[j] = k;
          if (k > bk) { bi = i - k + 1; bj = j - k + 1; bk = k; }
        }
        j2len = nj;
      }
      if (bk) {
        M += bk;
        if (alo < bi && blo < bj) q.push([alo, bi, blo, bj]);
        if (bi + bk < ahi && bj + bk < bhi) q.push([bi + bk, ahi, bj + bk, bhi]);
      }
    }
    return 2 * M / T;
  }
  const tokEq = (a, b) => a === b || (a.length >= 5 && b.length >= 5 && ratio(a, b) >= 0.85);

  // free text -> normalised tokens with their character spans in the original text
  function textTokens(text) {
    const out = [];
    const re = /[\p{L}\p{N}'’&+]+/gu;
    let m;
    while ((m = re.exec(text))) {
      for (const t of tokens(m[0])) out.push({ t, s: m.index, e: m.index + m[0].length });
    }
    // join the matcher's compounds across words ("smoke house" -> "smokehouse", "bar b que" -> "bbq")
    for (let i = 0; i < out.length - 1; i++) {
      const two = norm(out[i].t + ' ' + out[i + 1].t);
      if (!two.includes(' ')) { out.splice(i, 2, { t: two, s: out[i].s, e: out[i + 1].e }); }
    }
    return out;
  }

  /* Where does `name` occur in the tokenised text? Returns [start, end] in the text, or null.
     1. the name's head as a phrase (a leading "the" optional);
     2. else every distinctive token (>= 2 of them) inside a short window;
     3. else a single distinctive token of >= 4 letters on its own (when unsure, strike). */
  function locate(tt, name, phraseOnly) {
    const nt = tokens(head(name));
    if (!nt.length) return null;
    for (let i = 0; i + nt.length <= tt.length; i++) {
      let ok = true;
      for (let k = 0; k < nt.length && ok; k++) ok = tokEq(nt[k], tt[i + k].t);
      if (ok) return [tt[i].s, tt[i + nt.length - 1].e];
    }
    if (phraseOnly) return null;   // rule 1 only: for striking names inside prose (image 3), never a lone word
    const d = distinctive(head(name));
    if (!d.length) return null;
    if (d.length >= 2) {
      const win = d.length + 3;
      for (let i = 0; i < tt.length; i++) {
        if (!tokEq(d[0], tt[i].t) && !d.some(x => tokEq(x, tt[i].t))) continue;
        const span = tt.slice(i, i + win);
        if (d.every(x => span.some(y => tokEq(x, y.t)))) {
          const hits = span.filter(y => d.some(x => tokEq(x, y.t)));
          return [hits[0].s, hits[hits.length - 1].e];
        }
      }
      return null;
    }
    if (d[0].length >= 4) {
      const hit = tt.find(y => tokEq(d[0], y.t));
      if (hit) return [hit.s, hit.e];
    }
    return null;
  }

  // names: array of strings (nulls skipped). Returns [{name, index, at:[s,e]}]. opt.phraseOnly: rule 1 only.
  function find(text, names, opt = {}) {
    const tt = textTokens(text || '');
    const out = [];
    (names || []).forEach((n, i) => { if (!n) return; const at = locate(tt, n, opt.phraseOnly); if (at) out.push({ name: n, index: i, at }); });
    return out;
  }

  const api = { fold, norm, tokens, distinctive, head, ratio, tokEq, textTokens, locate, find };
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.Matcher = api;
})(typeof window !== 'undefined' ? window : globalThis);
