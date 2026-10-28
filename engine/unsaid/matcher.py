"""Name -> Qloo ID matcher. Strikes are decided by ID; when unsure, it strikes.

Pipeline for each raw AI-named string r, against the fixed pool U (Qloo places) of one city:
  R1  exact key match: full / core / compact / acronym / alias / head-of-"X at Y" / Qloo-side head
  S   /search scoped to the city (only if R1 found nothing in U): a hit in U strikes it;
      a strong hit outside U (same core) marks r as resolved_outside: it refers to something
      that isn't in the pool (closed, a music venue, a seed, outside the kind filter)
  R2  forward containment: every distinctive token of r appears in a pool name  (chains, branches, "X Wine Bar")
  R3  reverse containment: a pool name's distinctive tokens (>=2) all appear in r (pool name is the shorter brand)
      R2/R3 run when r matched in U or is unresolved. They are skipped when r resolved strongly outside U.
  R4  guard (unresolved only): a pool name sharing >= 60% of r's distinctive tokens is struck ("may be what X meant")
  R5  brand containment (always, even when /search resolved r to a branch outside U): r's brand, i.e. its head with
      city/borough words and generic suffixes dropped, is a whole-word token sequence at the START of a pool name or
      right after "at" in it ("Ippudo NY" -> "IPPUDO Hell's Kitchen"; "La Goulue" -> "Omar's at La Goulue"). It needs
      one distinctive token of length >= 4 or two tokens, and a weak word never fires it alone. Added 28 Oct after
      the live K4 relabel found 3 false survivors (UNSAID.md §4 K4 pivot: raise the guard, accept over-striking).
Unresolved names that strike nothing stay on the wall greyed out ("not found in Qloo").
"""
import difflib
import math
import re
import unicodedata
from functools import lru_cache

# Speed (28 Oct, gate F): every string function below is pure, so it is memoised; tok_eq skips difflib when an exact
# upper bound already rules the pair out; PoolIndex looks candidates up in key and token indexes instead of scanning
# U. The rules R1-R5 decide exactly as before (tests/test_matcher.py and the frozen 20 sets are byte-identical).

GENERIC = set("""
the a an and of at on in by for with to n
bar bars cafe caffe coffee restaurant restaurants grill grille pub tavern lounge room club kitchen house
deli diner pizza pizzeria bbq smokehouse taproom brewery brewing brewpub co company eatery bistro trattoria
cantina saloon inn hall garden beer wine wines cocktail cocktails bakery shop spirits food foods
gastropub steakhouse steak seafood cuisine chef table tables
""".split())
LOCATION = set("""
nyc new york brooklyn manhattan queens bronx st saint louis stl mo ny usa downtown midtown uptown
""".split())
STOP = GENERIC | LOCATION
BOROUGHS = set("""manhattan brooklyn queens bronx staten island harlem soho tribeca""".split())
BRAND_WEAK = set("""the a an and of at on in by for with to n little big old new rooftop original famous best real
blue red green black white golden gold royal grand upper lower east west north south good great happy lucky sweet
fine hot cool local wild first last main corner city town street park""".split())   # never fire R5 alone

SPLIT_HOST = re.compile(r"\s+(?:at|inside|@|in the|within)\s+|\s+[-–—|]\s+|\s*\(")
SPLIT_ON_SUFFIX = re.compile(r"\s+on (?:the )?\w+(?: \w+)?$")

COMPOUNDS = [
    (r"\bsmoke house\b", "smokehouse"), (r"\btap room\b", "taproom"), (r"\bbar b que\b", "bbq"),
    (r"\bbar b q\b", "bbq"), (r"\bbarbe?que\b", "bbq"), (r"\bbarbecue\b", "bbq"), (r"\bb b q\b", "bbq"),
    (r"\bsaint\b", "st"), (r"\bmount\b", "mt"),
]


@lru_cache(maxsize=1 << 16)
def fold(s):
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower().replace("’", "'").replace("‘", "'").replace("`", "'")


@lru_cache(maxsize=1 << 16)
def norm(s):
    """Lower-case, accents folded, &/+ -> and, possessive 's and apostrophes dropped,
    punctuation to spaces, compounds joined, leading 'the' dropped."""
    s = fold(s)
    s = s.replace("&", " and ").replace("+", " and ")
    s = re.sub(r"'s\b", "", s)
    s = s.replace("'", "")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    for pat, rep in COMPOUNDS:
        s = re.sub(pat, rep, s)
    s = re.sub(r"^the ", "", s)
    return s


def tokens(s):
    return norm(s).split()


def distinctive(s):
    return list(_distinctive(s))


@lru_cache(maxsize=1 << 16)
def _distinctive(s):
    t = [x for x in tokens(s) if x not in STOP]
    if not t:  # all generic or location words: fall back to non-generic tokens, keep city words
        t = [x for x in tokens(s) if x not in GENERIC]
    return tuple(t)


@lru_cache(maxsize=1 << 16)
def acronym(s):
    t = [x for x in tokens(s) if x not in ("and", "of", "the", "a")]
    return "".join(x[0] for x in t) if len(t) >= 3 else None


@lru_cache(maxsize=1 << 16)
def split_parts(raw):
    """'Lobby Bar at Hotel Chelsea' -> head 'Lobby Bar', host 'Hotel Chelsea'. 'Charlie Gitto's on the Hill' -> head."""
    f = fold(raw)
    parts = [p for p in SPLIT_HOST.split(f) if p and p.strip(" )")]
    head = parts[0].strip(" )") if parts else f
    host = parts[1].strip(" )") if len(parts) > 1 else None
    head2 = SPLIT_ON_SUFFIX.sub("", head)
    return head, host, (head2 if head2 != head else None)


def keys(name, akas=()):
    """Exact-match keys for one name (a frozenset; memoised when there are no akas)."""
    if not akas:
        return _keys1(name)
    return _keys(name, tuple(akas))


@lru_cache(maxsize=1 << 16)
def _keys1(name):
    return _keys(name, ())


def _keys(name, akas):
    out = set()
    for n in [name] + list(akas):
        full = norm(n)
        if not full:
            continue
        out.add(("full", full))
        out.add(("compact", full.replace(" ", "")))
        d = distinctive(n)
        if d:
            out.add(("core", " ".join(sorted(d))))
        a = acronym(n)
        if a:
            out.add(("acro", a))
        head, host, head2 = split_parts(n)
        for h in (head, head2):
            if h and norm(h) and norm(h) != full:
                out.add(("full", norm(h)))
                dh = distinctive(h)
                if dh:
                    out.add(("core", " ".join(sorted(dh))))
    return frozenset(out)


def _key_match(rk, pk):
    if any(k != "acro" for k, _ in rk & pk):  # acronym==acronym is not evidence ("Broadway Oyster Bar"/"Beale on Broadway")
        return True
    # an acronym on one side equals the compact name on the other ("Please Don't Tell" <-> "PDT")
    ra = {v for k, v in rk if k == "acro"}
    pa = {v for k, v in pk if k == "acro"}
    rc = {v for k, v in rk if k == "compact"}
    pc = {v for k, v in pk if k == "compact"}
    return bool(ra & pc) or bool(pa & rc)


def tok_eq(a, b):
    if a == b:
        return True
    la, lb = len(a), len(b)
    if la < 5 or lb < 5:
        return False
    if 2.0 * min(la, lb) / (la + lb) < 0.85:   # ratio() can't exceed this bound (real_quick_ratio)
        return False
    return _fuzzy(a, b)


@lru_cache(maxsize=1 << 18)
def _fuzzy(a, b):
    """The same test as before, in the same argument order (ratio() is not symmetric). quick_ratio() is an exact
    upper bound on ratio(), so a pair it rules out could never pass."""
    m = difflib.SequenceMatcher(None, a, b)
    return m.quick_ratio() >= 0.85 and m.ratio() >= 0.85


class TokenIndex:
    """The distinct tokens of a set of names, bucketed by length, so a token is compared only with tokens that
    could pass tok_eq at all (equal, or both >= 5 letters within the length bound)."""

    def __init__(self, toks):
        self.exact = set(toks)
        self.by_len = {}
        for t in self.exact:
            if len(t) >= 5:
                self.by_len.setdefault(len(t), []).append(t)
        self._rel, self._fwd = {}, {}

    def _window(self, t):
        la = len(t)
        if la < 5:
            return []
        lo, hi = max(5, int(math.floor(la * 0.85 / 1.15)) - 1), int(math.ceil(la * 1.15 / 0.85)) + 1
        return [u for n in range(lo, hi + 1) for u in self.by_len.get(n, ())]

    def related(self, t):
        """Every indexed u with tok_eq(t, u) or tok_eq(u, t) (both orders: R2 and R3 call it each way)."""
        r = self._rel.get(t)
        if r is None:
            r = {t} & self.exact
            r |= {u for u in self._window(t) if tok_eq(t, u) or tok_eq(u, t)}
            self._rel[t] = r
        return r

    def any_eq(self, t):
        """Is there an indexed u with tok_eq(t, u)?"""
        r = self._fwd.get(t)
        if r is None:
            r = t in self.exact or any(tok_eq(t, u) for u in self._window(t))
            self._fwd[t] = r
        return r


def contained(small, big):
    return all(any(tok_eq(s, b) for b in big) for s in small)


def overlap(r, p):
    return sum(1 for s in r if any(tok_eq(s, b) for b in p))


class PoolIndex:
    def __init__(self, pool, aliases=None):
        """pool: list of dicts with entity_id, name, optional akas."""
        self.pool = pool
        self.aliases = {norm(k): v for k, v in (aliases or {}).items()}
        self.k = {}
        self.d = {}
        self.t = {}     # R5: the pool name's normalised tokens, in order
        self.key_idx, self.acro_idx, self.compact_idx, tok_pos = {}, {}, {}, {}
        for pos, p in enumerate(pool):
            ak = list(p.get("akas") or [])
            self.k[p["entity_id"]] = keys(p["name"], ak)
            self.d[p["entity_id"]] = distinctive(split_parts(p["name"])[0]) or distinctive(p["name"])
            self.d[p["entity_id"] + "#full"] = distinctive(p["name"])
            self.t[p["entity_id"]] = tokens(p["name"])
            for kind, v in self.k[p["entity_id"]]:
                if kind == "acro":
                    self.acro_idx.setdefault(v, []).append(pos)
                else:
                    self.key_idx.setdefault((kind, v), []).append(pos)
                    if kind == "compact":
                        self.compact_idx.setdefault(v, []).append(pos)
            for tok in self.d[p["entity_id"] + "#full"]:
                tok_pos.setdefault(tok, set()).add(pos)
        self.tok_pos = tok_pos
        self.toks = TokenIndex(tok_pos)
        self.r5_idx = {}                   # R5: (pool token at a brand start) -> [(pos, start)]
        for pos, p in enumerate(pool):
            t = self.t[p["entity_id"]]
            for st in [0] + [k + 1 for k, w in enumerate(t) if w == "at"]:
                if st < len(t):
                    self.r5_idx.setdefault(t[st], []).append((pos, st))
        self.memo = {}                     # (rule, raw) -> result; the index is reused across requests

    def _candidates(self, raw_tokens):
        """Pool positions holding a token tok_eq-related to one of raw_tokens: every R2/R3/R4 hit is among them."""
        out = set()
        for t in set(raw_tokens):
            for u in self.toks.related(t):
                out |= self.tok_pos[u]
        return sorted(out)

    def _memo(self, rule, raw, fn):
        k = (rule, raw)
        if k not in self.memo:
            self.memo[k] = fn(raw)
        return list(self.memo[k])

    def r1(self, raw):
        return self._memo("r1", raw, self._r1)

    def containment(self, raw):
        return self._memo("c", raw, self._containment)

    def r5(self, raw):
        return self._memo("r5", raw, self._r5)

    def guard(self, raw, thr=0.6):
        return self._memo(("g", thr), raw, lambda r: self._guard(r, thr))

    def _r1(self, raw):
        names = [raw]
        al = self.aliases.get(norm(raw))
        if al:
            names += al if isinstance(al, list) else [al]
        rk = set()
        for n in names:
            rk |= keys(n)
        hits = set()                       # _key_match through the indexes: a shared non-acronym key, or an
        for k in rk:                       # acronym on one side equal to the compact name on the other
            if k[0] == "acro":
                hits.update(self.compact_idx.get(k[1], ()))
            else:
                hits.update(self.key_idx.get(k, ()))
                if k[0] == "compact":
                    hits.update(self.acro_idx.get(k[1], ()))
        return [self.pool[i]["entity_id"] for i in sorted(hits)]

    def _containment(self, raw):
        dr = distinctive(split_parts(raw)[0]) or distinctive(raw)
        drf = distinctive(raw)
        hits = []
        if not dr:
            return hits
        for i in self._candidates(list(dr) + list(drf)):
            p = self.pool[i]
            dp = self.d[p["entity_id"] + "#full"]
            if not dp:
                continue
            if contained(dr, dp):                       # R2
                hits.append((p["entity_id"], "R2"))
            elif len(dp) >= 2 and contained(dp, drf):   # R3
                hits.append((p["entity_id"], "R3"))
        return hits

    def _r5(self, raw):
        seq = brand_seq(raw)
        if not seq:
            return []
        n = len(seq)
        pos = sorted({i for i, st in self.r5_idx.get(seq[0], ())
                      if self.t[self.pool[i]["entity_id"]][st:st + n] == seq})
        return [self.pool[i]["entity_id"] for i in pos]

    def _guard(self, raw, thr=0.6):
        dr = distinctive(raw)
        if len(dr) < 2:  # a single distinctive token is fully handled by R2
            return []
        cand = self._candidates(dr) if thr > 0 else range(len(self.pool))   # thr > 0 needs >= 1 overlap
        return [self.pool[i]["entity_id"] for i in cand
                if overlap(dr, self.d[self.pool[i]["entity_id"] + "#full"]) / len(dr) >= thr]


_POOL_CACHE = {}


def pool_index(pool, aliases=None):
    """PoolIndex for this exact pool (ids, names, akas) and aliases, reused across requests (a small LRU)."""
    sig = (tuple((p["entity_id"], p["name"], tuple(p.get("akas") or ())) for p in pool),
           repr(sorted((aliases or {}).items())))
    idx = _POOL_CACHE.pop(sig, None) or PoolIndex(pool, aliases)
    _POOL_CACHE[sig] = idx
    while len(_POOL_CACHE) > 16:
        _POOL_CACHE.pop(next(iter(_POOL_CACHE)))
    return idx


@lru_cache(maxsize=1 << 16)
def brand_seq_t(raw):
    return tuple(_brand_seq(raw))


def brand_seq(raw):
    return list(brand_seq_t(raw))


def _brand_seq(raw):
    """R5's brand: the head of r ('X at Y' / 'X (…)' / 'X - Y' -> X), tokens normalised, city and borough words and
    trailing generic suffixes dropped. Empty when it is too weak to strike on its own."""
    head = split_parts(raw)[0]
    seq = [w for w in tokens(head) if w not in LOCATION and w not in BOROUGHS]
    while seq and seq[-1] in GENERIC:
        seq.pop()
    while seq and seq[0] in ("the", "a", "an"):
        seq.pop(0)
    strong_tok = [w for w in seq if w not in STOP and w not in BRAND_WEAK]
    if len(seq) == 1:
        return seq if strong_tok and len(seq[0]) >= 4 else []
    if len(seq) >= 2 and (strong_tok or any(len(w) >= 4 and w not in STOP for w in seq)):
        return seq if strong_tok else []
    return []


def strong(raw, cand_name):
    """Is a search result clearly the thing named?"""
    if _key_match(keys(raw), keys(cand_name)):
        return True
    a, b = norm(raw), norm(cand_name)
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.9


def match_wall(raw_names, pool, search_fn=None, aliases=None, guard_thr=0.6):
    """raw_names: iterable of AI-named strings for one city.
    pool: list of {entity_id, name, akas?} = the fixed set U.
    search_fn(raw) -> list of {entity_id, name} from /search scoped to the city (or None to skip stage S).
    Returns (struck: {entity_id: [(raw, rule)]}, per_name: {raw: {status, ids, resolved}})."""
    idx = pool_index(pool, aliases)
    in_pool = {p["entity_id"] for p in pool}
    struck, per = {}, {}

    def hit(eid, raw, rule):
        struck.setdefault(eid, []).append((raw, rule))

    for raw in dict.fromkeys(raw_names):  # dedupe, keep order
        info = {"status": None, "ids": [], "resolved": None}
        h1 = idx.r1(raw)
        for e in h1:
            hit(e, raw, "R1")
        matched_in_pool = bool(h1)
        outside_strong = False
        if not h1 and search_fn is not None:
            res = search_fn(raw) or []
            first_strong = next((c for c in res if strong(raw, c["name"])), None)
            if first_strong is not None and first_strong["entity_id"] not in in_pool:
                # Qloo's best clear match is something outside U (closed, a venue, the seed): it names that.
                outside_strong = True
                info["resolved"] = first_strong["name"]
                info["resolved_id"] = first_strong["entity_id"]
            else:
                cands = [first_strong] if first_strong is not None else [
                    c for c in res if c["entity_id"] in in_pool
                    and overlap(distinctive(raw), distinctive(c["name"])) >= 1]  # weak, lean to strike
                for c in cands[:1]:
                    hit(c["entity_id"], raw, "S")
                    matched_in_pool = True
                    info["resolved"] = c["name"]
                    for e in idx.r1(c["name"]):  # chain siblings of the resolved entity
                        if e != c["entity_id"]:
                            hit(e, raw, "S-chain")
        for e in idx.r5(raw):                  # R5 runs even when r resolved to a branch outside U
            hit(e, raw, "R5")
        if not outside_strong:
            for e, rule in idx.containment(raw):
                hit(e, raw, rule)
            if not matched_in_pool:
                for e in idx.guard(raw, guard_thr):
                    hit(e, raw, "R4")
        ids = sorted({e for e, v in struck.items() if any(x[0] == raw for x in v)})
        info["ids"] = ids
        if ids:
            info["status"] = "struck" if matched_in_pool else "struck_unsure"
        elif outside_strong:
            info["status"] = "outside_pool"
        else:
            info["status"] = "not_found"
        per[raw] = info
    return struck, per
