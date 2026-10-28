"""UNSAID engine v4 (UNSAID.md §3.1-3.3 win over engine-v3.md). One query = city + up to 3 loves + a wall.

  C1  city        precomputed table (cities.py); NYC's locality UUID from /search, region checked
  C2  loves       /search typed -> entity; on a miss /v2/tags (then semantic) -> tag; vibe/mood tag = dead on arrival
  C4  pools       per ENTITY love: base + signal.interests.entities=<L_i>, offsets 0 and 50, explainability page 1
                  only (raw log). A tag love never enters a discovery call.
  floor           closed, allowlist hard-excludes, rating >= 4.3 - 1e-4, distance  ->  U (the fixed set)
  C6'             fixed-set rescoring per love: base + filter.results.entities=<48 of U + 2 anchors> + ONE love's
                  signal (entity or tag, never both) -> order_i; tie guard at Qloo's default affinity
  dead loves      rho(order_i, popularity) >= 0.95, or a vibe/mood tag -> out of the fusion, dead-love line
  for you         RRF (k = 60) over the live loves' orders. anyone = popularity rank inside U (0 calls; P12 checks)
  strike          matcher R1-R4 (unchanged) over U; C7 /search only for names R1 missed that share a distinctive
                  token with U
  holds           #{i : x in the top third of S under the RRF of the loves other than i}; keep holds >= n-1
  order           by lift (flat: fit within the bottom 80 % of popularity); 7 + 3 reserves via the reverse check
                  and the last-seen check; the street check (L2, a hook the server supplies) burns and promotes;
                  displayed in for-you order
  because         the live love whose order_i ranks x best (no explainability shares anywhere)
  CAP             base + entity loves + filter.popularity.max removing |struck| members of U (1 call)
"""
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor

from unsaid import cities as C
from unsaid import matcher as M
from unsaid import stats as ST
from unsaid.qloo import (QlooDeadline, QlooError, TIMEOUT_POOL, canonical_query, TIMEOUT_RESCORE, affinity, explain_items, is_default_affinity,
                         latlon, prop)

ENGINE_V = "unsaid-engine-4.0"
CFG = {
    "CAT_TAGS": ["urn:tag:category:place:bar", "urn:tag:category:place:restaurant"],   # union
    "RATING_SERVER": 4,          # filter.properties.business_rating.min is an integer enum
    "RATING_CLIENT": 4.3, "RATING_EPS": 1e-4,   # client floor 4.3 - 1e-4 (float32 values like 4.1999998)
    "TAKE": 50, "OFFSETS": [0, 50],
    "EXTRA_OFFSETS": [],         # spec: none. R may set [100] if gate B shows |U| < U_MIN with two entity loves
    "U_MIN": 150,
    "CHUNK": 48, "ANCHORS": 2,   # 48 of U + 2 anchors = 50 = take
    "RRF_K": 60, "HOLD_FRAC": 1.0 / 3,
    "N_CARDS": 7, "N_RESERVES": 3,
    "SEARCH_RADIUS_MI": 15,      # C7 city-scoped /search
    "FLAT_RHO": 0.90, "DEAD_RHO": 0.95, "THIN_TIE": 0.30, "FLAT_POP_KEEP": 0.80,
    "ANCHOR_DRIFT_MAX": 0.005, "COVERAGE_MIN": 0.95,
    "BASELINE": "popularity",    # P12 decides; "nosignal" rescores U with no signal (+~5 calls)
    "NS_IS_POP_RHO": 0.99,       # P12: no-signal order == popularity at Spearman >= 0.99 -> RHO_RES undefined
    "WORKERS": 5,                # <= burst; the global bucket paces at 3/s anyway
    "HOURS_COVERAGE_MIN": 0.5,   # the hours part of the last-seen check applies only where Qloo carries hours
    # allowlist hard-excludes (tag id substrings / tag names); probes print the real IDs, R sets the final list
    "EXCLUDE_TAG_PATTERNS": ["food_court", "fast_food", "takeout_pizza", "pizza_delivery", "pizza_takeout",
                             "category:place:hotel", "genre:place:hotel", "lodging", "shopping_mall",
                             "category:place:mall", "grocery", "supermarket", "butcher", "music_venue",
                             "concert_venue", "concert_hall", "category:place:gym", "fitness_center", "health_club"],
    "EXCLUDE_TAG_NAMES": ["food court", "fast food", "takeout pizza", "hotel", "shopping mall", "mall", "grocery",
                          "grocery store", "supermarket", "butcher", "butcher shop", "music venue",
                          "live music venue", "concert hall", "gym", "fitness center"],
    "DEAD_TAG_PATTERNS": [":vibe", ":mood", "style:qloo", ":keyword:"],   # vibe/mood tags: dead on arrival
}
PLACE = "urn:entity:place"
GENERIC_WHAT = {"urn:tag:category:place:restaurant", "urn:tag:category:place:bar", "urn:tag:genre:place:restaurant",
                "urn:tag:genre:place:restaurant:bar"}   # too generic for "what it is"


def _noop(*a, **k):
    pass


# ---------------------------------------------------------------- resolve
def resolve_city(q, query, region=None):
    """-> dict with status ok|needs_input. Legacy keys (id, name, lat, lon, disamb, candidates) kept for the MCP agent."""
    text = query if not region else "%s, %s" % (query, region)
    key, borough = C.lookup(query)
    if key:
        cfg = C.CITIES[key]
        center = C.BOROUGHS.get(borough) or cfg["center"]
        city = {"status": "ok", "key": key, "name": cfg["name"], "slug": cfg["slug"], "mode": cfg["mode"],
                "radius_mi": cfg["radius_mi"], "radius_m": cfg.get("radius_m"), "center_latlon": center,
                "borough": borough or ("manhattan" if key == "nyc" else None), "id": None,
                "lat": center[0], "lon": center[1], "disamb": "%s, %s" % (cfg["name"], cfg["region"]), "candidates": []}
        if cfg["mode"] == "locality" and q is not None:      # C1: the locality UUID, region checked
            res = q.search(cfg["query"], types="urn:entity:locality", take=5, label="C1 city")
            cands = [_loc_cand(r) for r in res]
            pick = next((c for c in cands if cfg["region"].lower() in (c["disamb"] or "").lower()), None)
            if pick is None:
                return {"status": "needs_input", "reason": "no %s locality in %s" % (cfg["name"], cfg["region"]),
                        "candidates": cands, "text": text}
            city["id"] = pick["id"]
            city["candidates"] = cands
        elif q is not None:
            city["id"] = "point:%s" % cfg["slug"]
        return city
    name = (query or "").strip()
    if not region and name.lower() in C.AMBIGUOUS:
        return {"status": "needs_input", "reason": "'%s' is ambiguous" % name, "text": text,
                "candidates": [{"name": name, "disamb": d} for d in C.AMBIGUOUS[name.lower()]]}
    if q is None:
        return {"status": "needs_input", "reason": "unknown city", "candidates": [], "text": text}
    res = q.search(name, types="urn:entity:locality", take=5, label="C1 city")
    cands = [_loc_cand(r) for r in res]
    if not cands:
        return {"status": "needs_input", "reason": "city not found", "candidates": [], "text": text}
    if region:
        pick = next((c for c in cands if region.lower() in (c["disamb"] or "").lower()), None)
        if pick is None:
            return {"status": "needs_input", "candidates": cands, "text": text,
                    "reason": "'%s' resolves to %s, not %s" % (name, cands[0]["disamb"], region)}
    else:
        if len({c["disamb"] for c in cands}) > 1:
            return {"status": "needs_input", "reason": "'%s' is ambiguous; add the region" % name,
                    "candidates": cands, "text": text}
        pick = cands[0]
    if pick["lat"] is None:
        return {"status": "needs_input", "reason": "locality has no coordinates", "candidates": cands, "text": text}
    slug = "-".join(M.norm(pick["name"]).split())
    return {"status": "ok", "key": slug, "name": pick["name"], "slug": slug, "mode": "point", "radius_mi": 10,
            "radius_m": 16093, "center_latlon": (pick["lat"], pick["lon"]), "borough": None, "id": pick["id"],
            "lat": pick["lat"], "lon": pick["lon"], "disamb": pick["disamb"], "candidates": cands}


def _loc_cand(r):
    ll = latlon(r)
    return {"id": r["entity_id"], "name": r.get("name"), "lat": ll[0] if ll else None, "lon": ll[1] if ll else None,
            "disamb": r.get("disambiguation") or prop(r, "disambiguation", default="")}


def dead_tag(t):
    s = ("%s %s" % (t.get("type") or "", t.get("id") or "")).lower()
    return any(p in s for p in CFG["DEAD_TAG_PATTERNS"])


def resolve_love(q, text, hint=None):
    """-> {text, status ok|needs_input|miss, kind entity|tag, id, name, type, is_place, alternatives, dead, dead_reason}.
    needs_input still carries the top candidate, so scripts can proceed the way the kit's 'confirm' did."""
    text = (text or "").strip()
    out = {"text": text, "status": "miss", "kind": None, "id": None, "name": None, "type": None,
           "is_place": False, "alternatives": [], "dead": False, "dead_reason": None}

    def as_tag(tags, exact_needed):
        t = tags[0]
        exact = M.norm(t.get("name") or "") == M.norm(text)
        out.update({"kind": "tag", "id": t.get("id") or t.get("tag_id"), "name": t.get("name"),
                    "type": t.get("type") or "tag", "status": "ok" if (exact or not exact_needed) else "needs_input",
                    "alternatives": [{"id": x.get("id"), "label": x.get("name"), "type": x.get("type"), "kind": "tag"}
                                     for x in tags[1:4]]})
        if dead_tag(t):
            out.update({"dead": True, "dead_reason": "vibe"})
        return out

    if hint == "tag":
        tags = q.tags(text, take=5, label="C2 love tag") or q.tags(text, take=5, semantic=True, label="C2 love tag~")
        return as_tag(tags, True) if tags else out
    types = "urn:entity:%s" % hint if hint else None
    res = q.search(text, types=types, take=5, label="C2 love")
    if res:
        exact = [r for r in res if M.norm(r.get("name", "")) == M.norm(text)]
        r = (exact or res)[0]
        sub = r.get("subtype") or (r.get("types") or [""])[0]
        out.update({"kind": "entity", "id": r["entity_id"], "name": r.get("name"), "type": sub,
                    "status": "ok" if exact and len(exact) == 1 or (exact and hint) else "needs_input",
                    "is_place": sub == PLACE,
                    "alternatives": [{"id": x["entity_id"], "label": x.get("name"), "kind": "entity",
                                      "type": x.get("subtype") or (x.get("types") or [""])[0]}
                                     for x in res if x is not r][:3]})
        return out
    tags = q.tags(text, take=5, label="C2 love tag") or q.tags(text, take=5, semantic=True, label="C2 love tag~")
    if tags:
        return as_tag(tags, True)
    return out


# ---------------------------------------------------------------- parameters
def signal_of(love):
    if love.get("kind") == "tag":
        return {"signal.interests.tags": [love["id"]]}
    return {"signal.interests.entities": [love["id"]]}


def signal(loves):
    """Joint ENTITY signal (CAP only). Tags never join a discovery call."""
    ents = sorted(l["id"] for l in loves if l.get("kind") == "entity")
    return {"signal.interests.entities": ents} if ents else {}


def base_filters(city, loves):
    """Identical in every insights call of one query (UNSAID.md §3.1); only the signal and the results restriction
    change."""
    p = {"filter.type": PLACE,
         "filter.tags": sorted(CFG["CAT_TAGS"]),
         "operator.filter.tags": "union",
         "filter.properties.business_rating.min": CFG["RATING_SERVER"],
         "bias.trends": "off"}
    p.update(C.location_params(city))
    seeds = sorted(l["id"] for l in loves if l.get("is_place"))
    if seeds:
        p["filter.exclude.entities"] = seeds
    return p


def _pmap(fn, items, workers):
    if workers <= 1 or len(items) <= 1:
        return [fn(x) for x in items]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(fn, items))


# ---------------------------------------------------------------- C4 per-love pools
def per_love_pools(q, city, loves, offsets=None, workers=None):
    """2 calls per ENTITY love (offsets 0 and 50; explainability on page 1 only). No entity love at all: one
    no-signal pool (popularity order), labelled. Returns (pool, diag)."""
    offsets = offsets or CFG["OFFSETS"]
    ents = [l for l in loves if l.get("kind") == "entity"]
    base = dict(base_filters(city, loves), take=CFG["TAKE"])
    jobs = []
    for li, l in enumerate(ents or [None]):
        for off in offsets:
            p = dict(base)
            if l is not None:
                p.update(signal_of(l))
            if off:
                p["offset"] = off
            else:
                p["feature.explainability"] = True   # page 1 only, for the raw log
            lab = "C4 pool %s o%d" % ((l["text"][:18] if l else "no-signal"), off)
            jobs.append((li, off, p, lab))

    def run(job):
        li, off, p, lab = job
        try:
            return job, q.insights(p, label=lab, timeout=TIMEOUT_POOL), None
        except QlooError as e:
            return job, None, e

    out = _pmap(run, jobs, workers or CFG["WORKERS"])
    seen, pool = {}, []
    diag = {"calls": len(jobs), "failed": 0, "per_love": {}, "dupes": 0, "explain_page1": 0, "no_entity_love": not ents,
            "busy": False}
    for (li, off, p, lab), resp, err in out:
        if isinstance(err, QlooDeadline):
            raise err                       # the 90 s hard cap: degraded, never a half-built pool
        name = ents[li]["text"] if ents else "no-signal"
        d = diag["per_love"].setdefault(name, {"n": 0, "failed": 0})
        if err is not None:
            diag["failed"] += 1
            d["failed"] += 1
            diag["busy"] = diag["busy"] or err.busy
            continue
        ents_ = (resp.get("results") or {}).get("entities") or []
        d["n"] += len(ents_)
        url = "%s/v2/insights?%s" % (q.base, canonical_query(p))     # the request this member came back in
        for k, e in enumerate(ents_):
            if off == 0 and explain_items(e)[0]:
                diag["explain_page1"] += 1
            i = e["entity_id"]
            if i in seen:
                diag["dupes"] += 1
                seen[i]["_loves"].append(name)
                seen[i]["_pool_urls"].append(url)
                continue
            e["_pos"] = len(pool) + 1
            e["_loves"] = [name]
            e["_pool_urls"] = [url]
            seen[i] = e
            pool.append(e)
    return pool, diag


# legacy name used by older scripts
def taste_pool(q, city, loves, pages=None, kind_tags=None, label=None, adaptive=None):
    pool, d = per_love_pools(q, city, loves)
    return pool, {}, d


# ---------------------------------------------------------------- floor
def excluded_kind(e):
    pats, names = CFG["EXCLUDE_TAG_PATTERNS"], set(CFG["EXCLUDE_TAG_NAMES"])
    for t in e.get("tags") or []:
        if not isinstance(t, dict):
            continue
        tid = (t.get("id") or t.get("tag_id") or "").lower()
        if any(p in tid for p in pats) or (t.get("name") or "").strip().lower() in names:
            return t.get("id") or t.get("name")
    return None


MUSIC_PATTERNS = ("music_venue", "concert_venue", "concert_hall", "music venue", "concert hall")


def is_music(e):
    """Did the music-venue part of the allowlist fire? (Tag id or name; counted separately in the floor line.)"""
    for t in e.get("tags") or []:
        if isinstance(t, dict):
            k = ("%s %s" % (t.get("id") or "", t.get("name") or "")).lower()
            if any(p in k for p in MUSIC_PATTERNS):
                return True
    return False


def floor(pool, city=None):
    """UNSAID.md §3.1 client floor. Returns (U, drops) with drops = {closed, below_43, outside_R, not_venue,
    no_rating, no_location} and the dropped IDs by reason (for the wall's 'closed (Qloo)' lines)."""
    U = []
    drop = {"closed": 0, "below_43": 0, "outside_R": 0, "not_venue": 0, "not_venue_music": 0, "no_rating": 0,
            "no_location": 0,
            "ids": {"closed": [], "below_43": [], "outside_R": [], "not_venue": []}}
    thr = CFG["RATING_CLIENT"] - CFG["RATING_EPS"]
    for e in pool:
        if prop(e, "is_closed") is True:
            drop["closed"] += 1
            drop["ids"]["closed"].append(e["entity_id"])
            continue
        kind = excluded_kind(e)
        if kind:
            drop["not_venue"] += 1
            if is_music(e):
                drop["not_venue_music"] += 1        # shown separately: does "music venue" catch restaurants?
            drop["ids"]["not_venue"].append(e["entity_id"])
            continue
        r = prop(e, "business_rating")
        if r is None or float(r) < thr:
            drop["below_43"] += 1
            drop["no_rating"] += r is None
            drop["ids"]["below_43"].append(e["entity_id"])
            continue
        if city is not None:
            ll = latlon(e)
            if ll is None:
                drop["no_location"] += 1
            else:
                dmi = C.haversine_mi(ll, city["center_latlon"])
                e["_dist_mi"] = dmi
                if dmi > city["radius_mi"]:
                    drop["outside_R"] += 1
                    drop["ids"]["outside_R"].append(e["entity_id"])
                    continue
        U.append(e)
    return U, drop


# ---------------------------------------------------------------- C6' fixed-set rescoring
def rescore(q, city, loves_all, ids, sig_love, label, workers=None):
    """Affinity of every id under ONE love's signal (entity or tag), or no signal (sig_love None), with the same
    base filters. Chunks of 48 + 2 anchors; the anchors check that scores merge across chunks. Timeout 3 s."""
    ids = sorted(ids)
    anchors = ids[:CFG["ANCHORS"]]
    rest = [i for i in ids if i not in anchors]
    chunks = [rest[i:i + CFG["CHUNK"]] for i in range(0, len(rest), CFG["CHUNK"])] or [[]]
    base = dict(base_filters(city, loves_all), take=CFG["TAKE"])
    if sig_love is not None:
        base.update(signal_of(sig_love))

    def run(job):
        n, ch = job
        p = dict(base)
        p["filter.results.entities"] = sorted(set(anchors + ch))
        try:
            return q.insights(p, label="%s c%d" % (label, n), timeout=TIMEOUT_RESCORE), None
        except QlooError as e:
            return None, e

    out = _pmap(run, list(enumerate(chunks, 1)), workers or CFG["WORKERS"])
    aff, anchor_vals, ents_by_id, failed, busy = {}, {a: [] for a in anchors}, {}, 0, False
    for resp, err in out:
        if isinstance(err, QlooDeadline):
            raise err
        if err is not None:
            failed += 1
            busy = busy or err.busy
            continue
        for e in (resp.get("results") or {}).get("entities") or []:
            a = affinity(e)
            ents_by_id[e["entity_id"]] = e
            if e["entity_id"] in anchor_vals:
                anchor_vals[e["entity_id"]].append(a)
            if a is not None:
                aff[e["entity_id"]] = float(a)
    drift = max([max(v) - min(v) for v in anchor_vals.values() if len(v) > 1 and None not in v] or [0.0])
    missing = [i for i in ids if i not in aff]
    tied = [i for i in ids if i in aff and is_default_affinity(aff[i])]
    return {"aff": aff, "coverage": (len(ids) - len(missing)) / max(1, len(ids)), "missing": missing,
            "drift": drift, "calls": len(chunks), "failed": failed, "busy": busy, "tied": tied,
            "tie_share": len(tied) / max(1, len(ids)), "distinct": len(set(round(v, 9) for v in aff.values())),
            "ents": ents_by_id}


def ranks_from(aff, ids):
    """Rank within `ids` by affinity (average rank for ties); ids with no score tie at the bottom."""
    r = ST.rank({i: aff[i] for i in ids if i in aff})
    n_scored = len(r)
    miss = [i for i in ids if i not in r]
    if miss:
        bottom = n_scored + (len(miss) + 1) / 2.0
        for i in miss:
            r[i] = bottom
    return r


def ordinal(score, ids, higher_better=True):
    """Integer ranks 1..N, ties broken by id (display ranks: '#4 for you')."""
    s = sorted(ids, key=lambda i: ((-score[i] if higher_better else score[i]), i))
    return {i: k + 1 for k, i in enumerate(s)}


def rrf(orders, ids, k=None):
    k = k or CFG["RRF_K"]
    return {i: sum(1.0 / (k + o[i]) for o in orders) for i in ids}


def popularity(e):
    v = e.get("popularity")
    if v is None:
        v = prop(e, "popularity")
    return float(v or 0.0)


# ---------------------------------------------------------------- strike (C7 only where it matters)
class CitySearch:
    """search_fn for the matcher. Calls /search (city-scoped: lat,lon + 15 mi) only for names that share a
    distinctive token with U; others are 'not in pool' with no call (E6). A busy Qloo is recorded, never 'not found'."""

    def __init__(self, q, city, U):
        self.q, self.city = q, city
        self.u_tokens = set()
        for e in U:
            self.u_tokens.update(M.distinctive(e.get("name", "")))
        self.skipped, self.busy, self.closed, self.calls = set(), set(), set(), 0
        self.nonvenue = set()   # resolved entities that are not a restaurant or bar (tags known, no category tag)

    def shares_token(self, raw):
        d = M.distinctive(raw)
        return any(t in self.u_tokens or any(M.tok_eq(t, u) for u in self.u_tokens) for t in d)

    def __call__(self, raw):
        if self.q is None or not self.shares_token(raw):
            self.skipped.add(raw)
            return []
        lat, lon = self.city["center_latlon"]
        self.calls += 1
        try:
            res = self.q.search(raw, types=PLACE, take=5, location="%s,%s" % (lat, lon),
                                radius_mi=CFG["SEARCH_RADIUS_MI"], label="C7 name")
        except QlooDeadline:
            raise
        except QlooError:
            self.busy.add(raw)
            return []
        for r in res:
            if not_restaurant_or_bar(r):
                self.nonvenue.add(r["entity_id"])
            if prop(r, "is_closed") is True:
                self.closed.add(r["entity_id"])
        return [{"entity_id": r["entity_id"], "name": r.get("name", "")} for r in res]


def strike(q, city, U, wall_names, use_search=True):
    pool = [{"entity_id": e["entity_id"], "name": e.get("name", "")} for e in U]
    cs = CitySearch(q if use_search else None, city, U)
    struck, per = M.match_wall(wall_names, pool, cs)
    return struck, per, cs


def not_restaurant_or_bar(e):
    """Tags known and either no restaurant/bar category tag, or an allowlist hard-exclude."""
    tags = [t for t in e.get("tags") or [] if isinstance(t, dict)]
    if not tags:
        return False          # unknown: never guess
    ids = {(t.get("id") or "") for t in tags}
    return excluded_kind(e) is not None or not (ids & set(CFG["CAT_TAGS"]))


def name_outcome(raw, info, cs, dropped_index, drops):
    """-> (outcome, reason, qloo_id) for one wall name (CONTRACT.md wall item)."""
    st = info["status"]
    if st in ("struck", "struck_unsure"):
        return "struck", "in pool", (info["ids"] or [None])[0]
    rid = info.get("resolved_id")
    local = dropped_index.r1(raw) if dropped_index is not None else []
    closed_ids = set(drops["ids"]["closed"]) | cs.closed
    if (rid and rid in closed_ids) or any(i in closed_ids for i in local):
        return "dimmed", "closed (Qloo)", rid or next(i for i in local if i in closed_ids)
    nonvenue = set(drops["ids"]["not_venue"]) | cs.nonvenue
    if (rid and rid in nonvenue) or any(i in nonvenue for i in local):
        return "dimmed", "not a restaurant or bar", rid or next(i for i in local if i in nonvenue)
    if st == "outside_pool" or local:
        return "dimmed", "not in pool", rid or (local[0] if local else None)
    if raw in cs.busy:
        return "dimmed", "not checked (Qloo busy)", None
    if raw in cs.skipped:
        return "dimmed", "not in pool", None
    return "dimmed", "not found in Qloo", None


# ---------------------------------------------------------------- reverse check, street check
def answer_text(a):
    parts = []
    raw = a.get("raw") or a.get("text") or a.get("raw_text")
    if raw:
        parts.append(raw if isinstance(raw, str) else str(raw))
    for n in a.get("names") or []:
        parts.append(n["name"] if isinstance(n, dict) else str(n))
    return " | ".join(parts)


def reverse_index(answers):
    return [(i, set(M.tokens(answer_text(a)))) for i, a in enumerate(answers)]


def reverse_hit(name, rindex):
    """Fuzzy, local, 0 calls: every distinctive token of the card's name appears in one stored answer's raw text."""
    d = M.distinctive(name or "")
    if not d:
        return None
    for i, toks in rindex:
        if all(t in toks or any(M.tok_eq(t, x) for x in toks if abs(len(x) - len(t)) <= 3) for t in d):
            return i
    return None


def last_seen_local(e, hours_known):
    """The local half of the last-seen check: address string doesn't contain CLOSED; hours present (where Qloo
    carries hours at all). Site reachability is the server's hook (`last_seen`)."""
    addr = str(prop(e, "address") or "")
    if "CLOSED" in addr.upper():
        return False, "address says CLOSED"
    if hours_known and not prop(e, "hours"):
        return False, "no hours"
    return True, None


# ---------------------------------------------------------------- CAP and the popularity proofs
def popularity_cap(q, city, loves, U, struck_u, pop, pop_rank):
    k = len(struck_u)
    out = {"k": k, "max": None, "cap7": [], "calls": 0, "error": None}
    if not k or k >= len(U):
        return out
    by_pop = sorted(U, key=lambda e: (-pop[e["entity_id"]], e["entity_id"]))
    topk = {e["entity_id"] for e in by_pop[:k]}
    out["topk"] = topk
    out["overlap"] = len(topk & struck_u) / k
    out["cap_keep"] = k - len(topk & struck_u)
    thr = pop[by_pop[k]["entity_id"]]
    out["max"] = thr
    ents = [l for l in loves if l.get("kind") == "entity" and not l.get("dead")] or \
           [l for l in loves if l.get("kind") == "entity"]
    p = dict(base_filters(city, loves), take=CFG["TAKE"])
    p.update(signal(ents))
    p["filter.popularity.max"] = repr(float(thr))
    try:
        resp = q.insights(p, label="CAP popularity.max", timeout=TIMEOUT_POOL)
        out["calls"] = 1
        res = (resp.get("results") or {}).get("entities") or []
        kept, _ = floor(res, city)
        out["cap7"] = [(e["entity_id"], e.get("name")) for e in kept[:CFG["N_CARDS"]]]
    except QlooError as e:
        out["error"] = "HTTP %s" % e.status
    return out


# ---------------------------------------------------------------- the whole query
def run(q, city_q, loves_spec, wall, region=None, use_search=True, street_check=None, skeptic_fn=None,
        last_seen=None, live_answers=None, emit=None, strict=False, baseline=None, pages=None):
    """city_q: resolved city dict or text. loves_spec: [(text, hint)] or resolved love dicts.
    wall: {"answers": [...], "source"}. street_check(neighbourhood, city_name) -> [answer]. live_answers() ->
    [answer] (the live Gemini taste ask, joined after U exists). emit(type, payload) streams events.
    strict=True: a love that needs input stops the run (the API); False: take the top candidate (the scripts)."""
    emit = emit or _noop
    t0 = time.monotonic()
    res = {"status": None, "flags": [], "cards": [], "picks": [], "reserves": [], "diag": {"engine_v": ENGINE_V},
           "loves": [], "city": None, "wall": [], "counts": {}, "burn": {"asked": [], "burned": []}}
    city = city_q if isinstance(city_q, dict) else resolve_city(q, city_q, region)
    res["city"] = city
    if city.get("status") != "ok":
        res["status"] = "needs_input"
        return res
    loves = [l if isinstance(l, dict) else resolve_love(q, l[0], l[1]) for l in loves_spec]
    res["loves"] = loves
    if any(l["status"] == "miss" for l in loves) or (strict and any(l["status"] == "needs_input" for l in loves)):
        res["status"] = "needs_input"
        return res
    if skeptic_fn and not street_check:          # legacy hook: returns names said about a neighbourhood
        street_check = lambda hood, cname: [{"names": skeptic_fn(hood, cname), "provider": "skeptic",  # noqa: E731
                                             "lane": "live", "asked_at": time.strftime("%Y-%m-%dT%H:%M:%S")}]
    vibe = [l for l in loves if l.get("dead") and l.get("dead_reason") == "vibe"]
    rescorable = [l for l in loves if not (l.get("dead") and l.get("dead_reason") == "vibe")]
    lanes_failed = []

    # ---- C4 pools -> floor -> U
    pool, pdiag = per_love_pools(q, city, loves)
    if pdiag["failed"]:
        lanes_failed.append("C4 %d of %d pool calls" % (pdiag["failed"], pdiag["calls"]))
    if pdiag["failed"] == pdiag["calls"]:
        res["status"] = "degraded"
        res["diag"]["pool"] = pdiag
        return res
    U, drops = floor(pool, city)
    if len(U) < CFG["U_MIN"] and CFG["EXTRA_OFFSETS"]:
        more, mdiag = per_love_pools(q, city, loves, offsets=CFG["EXTRA_OFFSETS"])
        have = {e["entity_id"] for e in pool}
        pool += [e for e in more if e["entity_id"] not in have]
        pdiag["calls"] += mdiag["calls"]
        pdiag["failed"] += mdiag["failed"]
        U, drops = floor(pool, city)
    ids = sorted(e["entity_id"] for e in U)
    byid = {e["entity_id"]: e for e in U}
    N = len(U)
    res["diag"].update({"P": len(pool), "U": N, "drops": {k: v for k, v in drops.items() if k != "ids"},
                        "pool": pdiag, "explain_page1": pdiag["explain_page1"]})
    res["counts"] = {"P": len(pool), "U": N, "R_mi": city["radius_mi"],
                     "floor": {k: drops[k] for k in ("closed", "below_43", "outside_R", "not_venue", "not_venue_music")}}
    emit("pool", {"U": N, "P": len(pool), "floor": res["counts"]["floor"], "R_mi": city["radius_mi"]})
    if not U:
        res["status"] = "empty_none"
        return res
    dropped = [e for e in pool if e["entity_id"] not in byid]
    dropped_index = M.PoolIndex([{"entity_id": e["entity_id"], "name": e.get("name", "")} for e in dropped]) \
        if dropped else None

    # ---- strike the dated wall (generic names strike as soon as U exists)
    answers = list(wall.get("answers") or [])
    wall_items = []

    def strike_answers(ans, struck_acc, per_acc, cs_acc):
        raws = []
        for a in ans:
            raws += [n["name"] if isinstance(n, dict) else n for n in a.get("names") or []]
        raws = [r for r in dict.fromkeys(raws) if r not in per_acc]
        if not raws:
            return []
        st, per, cs = strike(q, city, U, raws, use_search)
        for eid, v in st.items():
            struck_acc.setdefault(eid, []).extend(v)
        per_acc.update(per)
        cs_acc.append(cs)
        out = []
        for raw in raws:
            oc, reason, qid = name_outcome(raw, per[raw], cs, dropped_index, drops)
            per[raw]["outcome"], per[raw]["reason"], per[raw]["qloo_id"] = oc, reason, qid
            out.append(raw)
            emit("strike", {"name": raw, "norm": M.norm(raw), "outcome": oc, "reason": reason, "qloo_id": qid})
        return out

    struck, per, css = {}, {}, []
    strike_answers(answers, struck, per, css)

    # ---- C6' per-love orders (one love's signal per call)
    pop = {i: popularity(byid[i]) for i in ids}
    pop_rank_avg = ST.rank(pop)
    pop_ord = ordinal(pop, ids)
    orders, tied, tied_only, rs_diag = {}, {}, {}, {}
    for l in rescorable:
        rs = rescore(q, city, loves, ids, l, "C6' %s" % l["text"][:18])
        orders[l["text"]] = ranks_from(rs["aff"], ids)
        tied[l["text"]] = set(rs["tied"]) | set(rs["missing"])     # no non-default score (eligibility)
        tied_only[l["text"]] = set(rs["tied"])                      # at Qloo's default affinity (tie share)
        rs_diag[l["text"]] = {k: rs[k] for k in ("coverage", "drift", "calls", "failed", "tie_share", "distinct")}
        scored = [i for i in ids if i not in tied[l["text"]]]     # ties carry no order: rho over scored members
        rs_diag[l["text"]]["rho_pop"] = ST.spearman({i: orders[l["text"]][i] for i in scored}, pop_rank_avg)
        l["_aff"] = rs["aff"]
        if rs["failed"] or rs["coverage"] < CFG["COVERAGE_MIN"]:
            lanes_failed.append("C6' %s coverage %.2f" % (l["text"], rs["coverage"]))
    base_label = "anyone = Qloo popularity order of these %d places" % N
    ns_rank = None          # the city's no-signal rank over U: only when P12 said it is NOT popularity (C5 branch)
    if (baseline or CFG["BASELINE"]) == "nosignal":
        rs0 = rescore(q, city, loves, ids, None, "C5 no-signal")
        if rs0["coverage"] >= CFG["COVERAGE_MIN"]:
            ns_score = {i: rs0["aff"].get(i, -1) for i in ids}
            pop_ord = ordinal(ns_score, ids)
            ns_rank = ST.rank(ns_score)
            base_label = "anyone = Qloo's no-signal order of these %d places (P12)" % N

    # ---- dead loves
    for l in rescorable:
        r = rs_diag[l["text"]]["rho_pop"]
        if r == r and r >= CFG["DEAD_RHO"]:
            l["dead"], l["dead_reason"] = True, "rho %.2f" % r
    live = [l for l in rescorable if not l.get("dead")]
    all_dead = not live
    if all_dead:
        live = list(rescorable)
    tie_share = (sum(len(tied_only[l["text"]]) for l in live) / float(N * len(live))) if live else 0.0
    thin = tie_share > CFG["THIN_TIE"]

    # ---- for you, anyone, lift
    if live:
        fy_score = rrf([orders[l["text"]] for l in live], ids)
    else:                                   # only vibe loves: nothing ranks taste
        fy_score = {i: pop[i] for i in ids}
    fit = ordinal(fy_score, ids)
    fit_avg = ST.rank(fy_score)
    pct = lambda r: ST.pct(r, N)  # noqa: E731
    lift = {i: pct(fit[i]) - pct(pop_ord[i]) for i in ids}
    rho_tp = ST.spearman(fit_avg, pop_rank_avg)
    flat = all_dead or not (rho_tp == rho_tp) or rho_tp > CFG["FLAT_RHO"]
    # RHO_RES = partial Spearman rho(for-you, popularity | the city's no-signal rank). Undefined (None) when the
    # no-signal order IS popularity (P12: Spearman >= 0.99), i.e. whenever the popularity baseline is in use.
    rho_res, rho_res_note = None, "RHO_RES undefined (base = popularity)"
    if ns_rank is not None:
        rho_ns_pop = ST.spearman(ns_rank, pop_rank_avg)
        if rho_ns_pop == rho_ns_pop and rho_ns_pop < CFG["NS_IS_POP_RHO"]:
            rho_res = ST.partial_spearman(fit_avg, pop_rank_avg, ns_rank)
            rho_res_note = "partial Spearman(for-you, popularity | no-signal rank); rho(no-signal, popularity) %.2f" \
                % rho_ns_pop
            if rho_res != rho_res:
                rho_res, rho_res_note = None, "RHO_RES undefined (degenerate ranks)"

    # ---- the live lane (Gemini taste ask), joined now that U exists
    live_ans = []
    if live_answers is not None:
        try:
            live_ans = list(live_answers() or [])
        except Exception as e:  # a lane fails: partial
            lanes_failed.append("live lane: %s" % type(e).__name__)
            res["diag"]["live_error"] = str(e)[:200]
        for a in live_ans:
            for n in a.get("names") or []:
                emit("wall_name", wall_item(a, n["name"] if isinstance(n, dict) else n))
        strike_answers(live_ans, struck, per, css)
    all_answers = answers + live_ans
    struck_u = set(struck) & set(ids)

    # ---- S, holds, eligibility
    S = [i for i in ids if i not in struck_u]
    n_live = len(live)
    holds = {i: None for i in S}
    holds_without = {i: None for i in S}   # 2 of 3: the love it can lose with the least damage ("holds without X")
    if n_live >= 2 and S:
        cut = math.ceil(len(S) * CFG["HOLD_FRAC"])
        holds = {i: 0 for i in S}
        drop_rank = {i: [] for i in S}
        for drop in live:
            others = [orders[l["text"]] for l in live if l is not drop]
            sc = rrf(others, S)
            rk = ordinal(sc, S)
            for i in S:
                holds[i] += rk[i] <= cut
                if rk[i] <= cut:
                    drop_rank[i].append((rk[i], drop["text"]))
        for i in S:
            if 0 < holds[i] < n_live:                   # n of n -> null: "holds even if you drop any one love"
                holds_without[i] = min(drop_rank[i])[1]
    need = n_live - 1 if n_live >= 2 else 0
    eligible = [i for i in S if (holds[i] is None or holds[i] >= need)
                and (not live or any(i not in tied[l["text"]] for l in live))]
    if flat:
        keep_from = (1 - CFG["FLAT_POP_KEEP"]) * N        # drop the most popular 20 %
        order = sorted([i for i in eligible if pop_ord[i] > keep_from], key=lambda i: (fit[i], i))
    else:
        order = sorted(eligible, key=lambda i: (-lift[i], fit[i], i))

    # ---- 7 + 3 via the reverse check and the last-seen check
    rindex = reverse_index(all_answers)
    hours_cov = sum(1 for e in U if prop(e, "hours")) / float(N)
    hours_known = hours_cov >= CFG["HOURS_COVERAGE_MIN"]
    selected, rev_struck, unseen = [], [], []
    want = CFG["N_CARDS"] + CFG["N_RESERVES"]
    for i in order:
        if len(selected) >= want:
            break
        e = byid[i]
        h = reverse_hit(e.get("name"), rindex)
        if h is not None:
            rev_struck.append({"id": i, "name": e.get("name"), "answer": h})
            struck.setdefault(i, []).append(("reverse", "REV"))
            emit("strike", {"name": e.get("name"), "norm": M.norm(e.get("name") or ""), "outcome": "struck",
                            "reason": "reverse check", "qloo_id": i})
            continue
        ok, why = last_seen_local(e, hours_known)
        if ok and last_seen is not None:
            try:
                ok = bool(last_seen(e))
                why = None if ok else "last-seen hook"
            except Exception:
                ok, why = True, None
        if not ok:
            unseen.append({"id": i, "name": e.get("name"), "why": why})
            continue
        selected.append(i)
    picks, reserves = selected[:CFG["N_CARDS"]], selected[CFG["N_CARDS"]:]

    # ---- because-line: the live love whose order ranks x best (a tied order never explains)
    def because(i):
        best = None
        for l in live:
            if i in tied[l["text"]]:
                continue
            r = orders[l["text"]][i]
            if best is None or r < best[0]:
                best = (r, l)
        return best[1] if best else None

    asked_hoods, street_answers = {}, []
    # ---- cards (never_said reads the street asks as they accumulate)
    as_of = max([a.get("asked_at") or "" for a in all_answers] or [""]) or None
    n_city = len(all_answers)

    def card(i):
        e = byid[i]
        b = because(i)
        hood = prop(e, "neighborhood") or ""
        n_street = len(asked_hoods.get(hood, []))
        is_tied = any(i in tied[l["text"]] for l in live)
        ll = latlon(e) or (None, None)
        what = [t.get("name") for t in (e.get("tags") or []) if isinstance(t, dict)
                and (t.get("id") or "") not in GENERIC_WHAT and t.get("name")]
        return {"id": i, "name": e.get("name"), "what": " · ".join(x.lower() for x in what[:2]),
                "because": b["text"] if b else None, "because_label": (b.get("name") or b["text"]) if b else None,
                "fit_rank": fit[i], "any_rank": None if flat else pop_ord[i], "U": N,
                "rating": prop(e, "business_rating"), "open": prop(e, "is_closed") is not True,
                "neighbourhood": hood, "address": prop(e, "address") or "", "lat": ll[0], "lon": ll[1],
                "url": prop(e, "website") or "", "holds": holds.get(i), "n_loves": n_live, "tied": is_tied,
                "holds_without": holds_without.get(i), "_pool_urls": list(e.get("_pool_urls") or []),
                "lift": round(lift[i], 4), "popularity": pop[i],
                "never_said": {"asks": n_city + len(street_answers), "city_asks": n_city, "street_asks": n_street,
                               "as_of": as_of}}

    for i in sorted(picks, key=lambda i: (fit[i], i)):     # candidates light, in for-you order
        emit("card", dict(card(i), provisional=bool(street_check)))

    # ---- the street check (L2): a name hit burns the card; the next reserve rises
    if street_check is not None and picks:
        k = 0
        while k < len(picks):
            i = picks[k]
            hood = prop(byid[i], "neighborhood") or ""
            if hood and hood not in asked_hoods:
                try:
                    got = list(street_check(hood, city["name"]) or [])
                except Exception as e:
                    got = []
                    lanes_failed.append("street check: %s" % type(e).__name__)
                asked_hoods[hood] = got
                street_answers += got
                for a in got:
                    rec = {"neighbourhood": hood, "lane": a.get("lane", "live"), "asked_at": a.get("asked_at"),
                           "provider": a.get("provider"), "named": [n["name"] if isinstance(n, dict) else n
                                                                    for n in a.get("names") or []]}
                    res["burn"]["asked"].append(rec)
                cards_pool = [{"entity_id": x, "name": byid[x].get("name", "")} for x in picks + reserves]
                rix = reverse_index(got)
                hit = set()
                for a in got:
                    st, _ = M.match_wall([n["name"] if isinstance(n, dict) else n for n in a.get("names") or []],
                                         cards_pool, None)
                    for x in st:
                        hit.add((x, a.get("provider"), a.get("asked_at")))
                for x in picks + reserves:
                    j = reverse_hit(byid[x].get("name"), rix)
                    if j is not None:
                        hit.add((x, got[j].get("provider"), got[j].get("asked_at")))
                for x, by, at in sorted(hit, key=lambda t: t[0]):
                    if x in picks or x in reserves:
                        b = {"card_id": x, "name": byid[x].get("name"), "by": by, "at": at, "neighbourhood": hood,
                             "risen": None}
                        if x in picks:
                            picks.remove(x)
                            if reserves:
                                up = reserves.pop(0)
                                picks.append(up)
                                b["risen"] = card(up)
                        else:
                            reserves.remove(x)
                        res["burn"]["burned"].append({k: v for k, v in b.items() if k != "risen"})
                        emit("burn", b)
                k = 0          # re-walk: a risen reserve's street gets asked too
                continue
            k += 1
    picks = sorted(picks, key=lambda i: (fit[i], i))           # displayed in for-you order
    reserves = sorted(reserves, key=lambda i: (fit[i], i))

    res["picks"] = [card(i) for i in picks]
    res["reserves"] = [card(i) for i in reserves]
    # legacy card shape (the MCP agent and the older scripts read it)
    for c in res["picks"]:
        res["cards"].append({
            "qloo_id": c["id"], "name": c["name"], "neighbourhood": c["neighbourhood"], "rating": c["rating"],
            "is_closed": not c["open"], "fits": "#%d of %d" % (c["fit_rank"], N),
            "city_order": "#%d of %d" % (pop_ord[c["id"]], N), "lift_pts": round(100 * lift[c["id"]]),
            "holds": ("%d of %d" % (c["holds"], n_live)) if c["holds"] is not None else "n/a (1 love)",
            "because": {"love": c["because"], "line": ("because you love %s" % c["because_label"])
                        if c["because"] else None, "source": "best per-love rank (C6')", "share": None},
            "ai": {"named": 0, "asked": c["never_said"]["asks"]}, "tags": c["what"].split(" · ") if c["what"] else []})

    # ---- wall items
    for a in all_answers:
        for n in a.get("names") or []:
            raw = n["name"] if isinstance(n, dict) else n
            it = wall_item(a, raw)
            info = per.get(raw) or {}
            it.update({"outcome": info.get("outcome", "dimmed"), "reason": info.get("reason", "not found in Qloo"),
                       "qloo_id": info.get("qloo_id")})
            wall_items.append(it)
    res["wall"] = wall_items

    # ---- popularity proofs
    cap = popularity_cap(q, city, loves, U, struck_u, pop, pop_ord)
    cap_ids = {x for x, _ in cap.get("cap7") or []}
    obscure = sorted([i for i in struck_u if pop_ord[i] > N / 2.0], key=lambda i: -pop_ord[i])
    known = [c["id"] for c in res["picks"] if pop_ord[c["id"]] <= N / 3.0]
    distinct_norms = {M.norm(w["name"]) for w in wall_items}
    strong_id = {}
    for eid, hits in struck.items():
        for raw, rule in hits:
            if rule == "R1":
                strong_id.setdefault(raw, eid)
    for raw, info in per.items():
        if info.get("status") == "outside_pool" and info.get("resolved_id"):
            strong_id.setdefault(raw, info["resolved_id"])
    place_of = wall_places([w["name"] for w in wall_items], strong_id)
    for w in wall_items:
        w["place"] = place_of.get(w["name"])
    n_places = len(set(place_of.values()))

    # ---- status and flags
    n = len(res["picks"])
    status = "ok" if n >= CFG["N_CARDS"] else ("empty_few" if n > 0 else "empty_none")
    if status == "ok" and lanes_failed:
        status = "partial"
    res["status"] = status
    if status == "empty_none":
        res["fallback"] = [byid[i].get("name") for i in sorted(struck_u, key=lambda i: fit[i])[:3]]
        res["fallback_ids"] = sorted(struck_u, key=lambda i: fit[i])[:3]
    flags = []
    if flat:
        flags.append("flat")
    if thin:
        flags.append("thin_taste")
    for l in loves:
        if l.get("dead"):
            flags.append("dead_love:%s" % (l.get("name") or l["text"]))
    res["flags"] = flags
    res["counts"].update({"wall": n_places, "asks": n_city + len(street_answers), "S": len(S),
                          "struck_in_U": len(struck_u)})
    res["diag"].update({
        "N": N, "S": len(S), "kept": len(eligible), "flat": flat, "all_dead": all_dead, "thin_taste": thin,
        "tie_share": tie_share, "rescore": rs_diag, "rho_tp": rho_tp, "rho_res": rho_res, "rho_res_note": rho_res_note,
        "rho_taste_base": rho_tp, "rho_taste_pop": rho_tp, "baseline": base_label,
        "cap_keep": cap.get("cap_keep"), "cap_shared": len(cap_ids & set(picks)) if cap.get("cap7") else None,
        "popcap_overlap": cap.get("overlap", float("nan")), "cap": {k: v for k, v in cap.items() if k != "topk"},
        "obscure": [(i, byid[i].get("name")) for i in obscure], "known": [(i, byid[i].get("name")) for i in known],
        "auc_pop_struck": ST.auc([pop[i] for i in ids], [i in struck_u for i in ids]),
        "wall_names": len(distinct_norms),
        "wall": {"answers": len(all_answers), "names": len(distinct_norms), "places": n_places, "struck": len(struck_u),
                 "status": _count(per), "source": wall.get("source"),
                 "c7_calls": sum(c.calls for c in css), "c7_skipped": sum(len(c.skipped) for c in css),
                 "c7_busy": sum(len(c.busy) for c in css)},
        "reverse_struck": rev_struck, "last_seen_dropped": unseen, "hours_coverage": hours_cov,
        "lanes_failed": lanes_failed, "as_of": as_of, "elapsed_s": round(time.monotonic() - t0, 3),
        "loves_live": [l["text"] for l in live], "street_asks": len(street_answers)})
    res["_R"] = {"fit": fit, "pop_ord": pop_ord, "lift": lift, "orders": orders, "pop": pop, "tied": tied,
                 "taste_rank": fit, "pop_rank": pop_ord, "base_rank": pop_ord, "N": N}
    res["_U"] = U
    res["_struck"] = struck
    res["_per"] = per
    res["_holds"] = holds
    res["_selected"] = selected
    return res


HOST_AT = re.compile(r"\s+(?:at|inside|@|within)\s+", re.I)


def place_part(raw):
    """The place a wall string names: drop a parenthetical; 'X at Y' -> Y; 'X - Y' / 'X | Y' -> X."""
    s = re.sub(r"\s*\(.*?\)\s*", " ", raw).strip() or raw
    m = HOST_AT.split(s)
    if len(m) > 1 and M.distinctive(m[-1]):
        return m[-1].strip()
    return re.split(r"\s+[-–—|]\s+", s)[0].strip() or s


def wall_places(raws, qid_of):
    """Distinct PLACES among wall names (⟦WALL⟧). Merges, strongest first, never through a weak bridge:
      1. the same Qloo ID from a strong resolution (R1 in U, or a strong /search hit outside U)   [qid_of]
      2. the matcher's R1 keys name to name (full / core / compact / acronym / the head of "X at Y", "X (dish)")
      3. plural/possessive folded ("Sweetie Pies" == "Sweetie Pie's")
      4. R2/R3 containment name to name, only when the shorter name has >= 2 distinctive tokens AND every name that
         contains it already sits in one place ("Tower Grove" never bridges Tower Grove Park and Tower Grove Tavern).
    No R4 guard and no single-token containment here: they over-strike on purpose, but would over-merge a count.
    Every rule compares the PLACE part of a name: "Slinger at Crown Candy Kitchen" -> Crown Candy Kitchen,
    "Gioia's Deli (hot salami sandwich)" -> Gioia's Deli, "Salt + Smoke - Delmar Loop" -> Salt + Smoke.
    Returns {raw: place key} (the cluster's first name, normalised)."""
    raws = list(dict.fromkeys(raws))
    order = {r: k for k, r in enumerate(raws)}
    parent = {r: r for r in raws}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            lo, hi = sorted((ra, rb), key=order.get)
            parent[hi] = lo

    by_id, by_key, by_sing, by_tok = {}, {}, {}, {}
    part = {r: place_part(r) for r in raws}
    for r in raws:
        q = qid_of.get(r)
        if q:
            union(r, by_id.setdefault(q, r))
        for k in M.keys(part[r]):
            if k[0] != "acro":
                union(r, by_key.setdefault(k, r))
        ds = M.distinctive(part[r])
        sing = " ".join(sorted(t[:-1] if len(t) > 3 and t.endswith("s") else t for t in ds))
        if sing:
            union(r, by_sing.setdefault(sing, r))
        for t in ds:
            by_tok.setdefault(t, []).append(r)
    members = {}
    for r in raws:
        members.setdefault(find(r), set()).add(" ".join(t[:-1] if len(t) > 3 and t.endswith("s") else t
                                                        for t in M.tokens(part[r])))
    for r in raws:                                   # 4. containment, unambiguous only
        ds = M.distinctive(part[r])
        if len(ds) < 2 or len(members.get(find(r), ())) > 1:   # only a lone short name attaches (no bridges)
            continue
        bigs = {c for c in by_tok.get(ds[0], []) if c != r and len(M.distinctive(part[c])) > len(ds)
                and M.contained(ds, M.distinctive(part[c]))}
        if bigs and len({find(c) for c in bigs}) == 1:
            union(r, next(iter(bigs)))
    return {r: M.norm(find(r)) for r in raws}


def wall_item(a, raw):
    return {"name": raw, "norm": M.norm(raw), "provider": a.get("provider"), "model": a.get("model"),
            "phrasing_id": a.get("phrasing_id") or a.get("phrasing"), "phrasing": a.get("phrasing_text") or
            a.get("phrasing"), "asked_at": a.get("asked_at"), "lane": a.get("lane") or "dated"}


def _count(per):
    c = {}
    for v in per.values():
        c[v["status"]] = c.get(v["status"], 0) + 1
    return c
