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
import json
import math
import os
import re
import threading
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
    "EXTRA_OFFSETS": [100, 150],  # live 28 Oct: gate B left Cedric at 7+0 (U 28); the 50k/month key affords it
    "EXTRA_OFFSETS_2": [200, 250],  # a second step, only while U is still short (the state rule took ~30 IL places
                                    # out of every STL pool: 28 Oct)
    "U_MIN": 150,
    "CHUNK": 48, "ANCHORS": 2,   # 48 of U + 2 anchors = 50 = take
    "RRF_K": 60, "HOLD_FRAC": 1.0 / 3,
    "N_CARDS": 7, "N_RESERVES": 3,
    "SEARCH_RADIUS_MI": 15,      # C7 city-scoped /search
    # C7 budget (gate F live: a ~700-name NYC wall sent 216 /search calls). Only names R1-R5 did not strike, that
    # share a RARE distinctive token with U, are searched, after the veto candidates (names whose only strike is a
    # one-word R2 containment), 20 in all. Past the cap a one-word R2 strike is not applied, and the other
    # candidates strike their best match when its fuzzy score reaches the token threshold. "all" = the old path.
    "C7_MODE": "capped", "C7_MAX": 20, "C7_MIN_TOKEN": 4, "C7_RARE_MAX": 3, "UNSURE_STRIKE": 0.85,
    "C7_WORKERS": 8,
    "CAP_ENABLED": True,
    "CONCURRENT": True,          # False: rescoring and the strike run one after the other (CPU measurement only)         # False: skip the CAP call (offline reruns; cards never depend on it)
    "FLAT_RHO": 0.90, "DEAD_RHO": 0.95, "THIN_TIE": 0.30, "FLAT_POP_KEEP": 0.80,
    "DEAD_TIE": 0.95,            # a love with >= 95% of U at the default affinity ranks nothing: dead (gate B live)
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
    # Not a place to eat or drink, whatever else it is tagged (28 Oct, the 20 frozen sets): adult entertainment, and
    # places whose draw is an activity or a service. Venue tags (event/wedding/music venue, banquet hall, tourist
    # attraction) and cafes stay. Matched on urn:tag:category:place:<x>; adult also on any genre tag.
    "NON_FOOD_CATEGORIES": ["adult_entertainment_club", "adult_entertainment_store", "strip_club", "check_cashing_service",
                            "table_tennis_facility", "bowling_alley", "bowling_supply_shop", "video_arcade",
                            "laser_tag_center", "golf_course", "golf_driving_range", "golf_instructor", "golf_shop",
                            "tennis_court", "beach_volleyball_court", "sports_complex", "movie_theater", "museum",
                            "historical_place_museum", "exhibit", "observatory", "observation_deck", "scenic_spot",
                            "cannabis_store", "laundromat", "coworking_space", "learning_center", "music_school",
                            "painting_studio", "painting_lessons", "art_studio", "conference_center", "talent_agency",
                            "rehearsal_studio", "puppet_theater", "cruise_agency", "casino",
                            # judge 2 (28 Oct): stores and banquet/event businesses. event_venue and wedding_venue
                            # stay: every pool place carrying them is also a bar or restaurant (92 and 15 of 1,178)
                            "liquor_store", "wine_store", "beer_store", "banquet_hall", "event_planner",
                            "party_planner", "wedding_planner", "event_management_company",
                            "hookah_bar", "hookah_lounge", "hookah_store"],
    # Diversity (28 Oct): "everyone's taste" prior per city, data/priors/<city>.json (build_priors.py). A place's
    # prior is its mean fit percentile over the preset sets that share no love with this query (>= PRIOR_MIN_SETS).
    # UNSAID_PRIORS_DIR overrides it (Render Secret Files: /etc/secrets holding nyc.json / stl.json or
    # priors-nyc.json / priors-stl.json)
    "PRIORS_DIR": os.environ.get("UNSAID_PRIORS_DIR") or os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "priors"),
    "PRIOR_MIN_SETS": 1, "PRIOR_ENABLED": True,   # 1: with 10 sets a city, one other taste is evidence
    # how a place's fits for other tastes become "fits everyone": "top" = share of other tastes that put it in their
    # top PRIOR_TOP (a place many tastes rank high); "mean" = its mean fit percentile
    "PRIOR_STAT": "top", "PRIOR_TOP": 0.7,
    # Dish loves (28 Oct): a tag love ties every place at Qloo's default affinity under C6' ("rib tips" 1.0). Its
    # sub-pool comes from filter.tags=<the tag and its same-name menu_highlight/specialty_dish siblings>; a place that
    # carries the dish ranks first for that love, then untagged places Qloo did score, then the rest (tied).
    "DISH_POOL": True, "DISH_OFFSETS": [0, 50], "DISH_SIBLING_TYPES": ("menu_highlight", "specialty_dish", "cuisine")   # 1: with 10 sets a city, one other taste is evidence
}
PLACE = "urn:entity:place"
GENERIC_WHAT = {"urn:tag:category:place:restaurant", "urn:tag:category:place:bar", "urn:tag:genre:place:restaurant",
                "urn:tag:genre:place:restaurant:bar"}   # too generic for "what it is"


def _noop(*a, **k):
    pass


class CPU:
    """Process CPU seconds per stage (time.process_time, all threads): diag.cpu_s."""

    def __init__(self):
        self.t = time.process_time()
        self.out = {}

    def mark(self, stage):
        now = time.process_time()
        self.out[stage] = round(self.out.get(stage, 0.0) + now - self.t, 4)
        self.t = now


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


_PRE = None


def _pre_resolved():
    """§3.2 C2: common loves pre-resolved by hand (data/loves_resolved.json, keyed by matcher.norm of the typed text)."""
    global _PRE
    if _PRE is None:
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                            "data", "loves_resolved.json")
        try:
            _PRE = {M.norm(k): v for k, v in json.load(open(path)).get("loves", {}).items()}
        except (OSError, ValueError):
            _PRE = {}
    return _PRE


SCREEN_TYPES = ("urn:entity:movie", "urn:entity:tv_show")      # hint movie or tv_show searches both
LOVE_TAG_PREF = {"urn:tag:specialty_dish:place": 0.03, "urn:tag:menu_highlight:qloo": 0.02,
                 "urn:tag:cuisine:qloo": 0.01}                  # the dish and drink tags, most specific first
VENUE_WORDS = {"bar", "pub", "tavern", "cafe", "kitchen", "smokehouse", "grill", "grille", "diner", "deli",
               "delicatessen", "restaurant", "brewery", "brewing", "bakery", "lounge", "saloon", "taqueria", "pizzeria",
               "trattoria", "osteria", "bistro", "brasserie", "cantina", "izakaya", "steakhouse", "chophouse", "inn",
               "shack", "joint", "creamery", "roastery", "speakeasy"}


def _sing(toks):
    return [t[:-1] if len(t) > 3 and t.endswith("s") and not t.endswith("ss") else t for t in toks]


def _name_match(text, name, akas=()):
    """How well typed text names a candidate, 0..1: 1 the same name (matcher.norm), 0.97 the same up to spacing or a
    plural, 0.95 an alias, 0.8 the text starts the name ('Anchorman'), 0.7 / 0.6 one's words inside the other's,
    else at most 0.5 by word overlap."""
    a, b = M.norm(text), M.norm(name or "")
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    ta, tb = a.split(), b.split()
    if "".join(ta) == "".join(tb) or _sing(ta) == _sing(tb):
        return 0.97
    if any(M.norm(x) == a for x in akas if x):
        return 0.95
    if b.startswith(a + " "):
        return 0.8
    if len(ta) == len(tb) > 1 and all(y.startswith(x) for x, y in zip(ta, tb)):
        return 0.8                              # "parks and rec", "earth wind and fir"
    sa, sb = set(_sing(ta)), set(_sing(tb))
    if sa <= sb:
        return 0.7
    if sb <= sa:
        return 0.6
    return 0.5 * len(sa & sb) / len(sa | sb)


def _pop(r):
    p = r.get("popularity")
    return p if isinstance(p, (int, float)) else 0.0


def _in_service(r):
    """A place inside 1.5x the radius of a city UNSAID serves (cities.CITIES): a typed bar name means that one."""
    ll = latlon(r)
    return bool(ll) and any(C.haversine_mi(ll, c["center"]) <= 1.5 * c["radius_mi"] for c in C.CITIES.values())


def _rank_entities(text, res, hint_types=(), free=False, venue=False, worded=False):
    """[(score, match, result, type)], best first: name match + 0.5 x Qloo popularity (a popular show beats an obscure
    film of the same name), +0.03 for the hinted type, +0.25 for a place in a served city. free (no hint, field 3):
    +0.3 for a brand (a chain's name means the chain), except for a one-off venue ("Katz's Delicatessen": worded like a
    venue, and not two same-named places in a served city); places outside the served cities only when the text reads
    as a venue (venue); and only brands and places compete with a full name match."""
    out = []
    if free:
        res = [r for r in res if venue or (r.get("subtype") or (r.get("types") or [""])[0]) != PLACE or _in_service(r)]
        branches = sum(1 for r in res if (r.get("subtype") or (r.get("types") or [""])[0]) == PLACE and _in_service(r)
                       and _name_match(text, r.get("name")) >= 0.95)
        chain = not worded or branches >= 2
    for r in res:
        sub = r.get("subtype") or (r.get("types") or [""])[0]
        akas = [x.get("value") for x in (prop(r, "akas") or []) if isinstance(x, dict)]
        m = _name_match(text, r.get("name"), akas)
        if sub == PLACE and m < 0.95:           # "Carbone New York" is what someone means by "Carbone"
            base = _strip_city(r.get("name"))
            m = max(m, 0.97) if base and _name_match(text, base) >= 0.97 else m
        if free and sub not in (PLACE, "urn:entity:brand"):
            m = min(m, 0.9)                     # a film or a game named like a dish is never the top answer here
        s = m + 0.5 * _pop(r) + (0.03 if sub in hint_types else 0.0)
        s += 0.25 if sub == PLACE and _in_service(r) else 0.0
        s += 0.3 if free and chain and sub == "urn:entity:brand" else 0.0
        out.append((s, m, r, sub))
    out.sort(key=lambda x: -x[0])               # stable: Qloo's own order breaks ties
    return out


def _strip_city(name):
    """'Carbone New York' -> 'carbone': a place name with a served city's name on the end, without it (else None)."""
    n = M.norm(name or "")
    for c in C.CITIES.values():
        names = {M.norm(c["name"]), M.norm(c.get("query") or ""), M.norm(c.get("region") or "")}
        names |= {x[:-5] for x in names if x.endswith(" city")}      # "New York City" -> "new york"
        for cn in names - {""}:
            if n.endswith(" " + cn):
                return n[:-len(cn) - 1]
    return None


def _rank_tags(text, tags):
    out = [(_name_match(text, t.get("name")) + LOVE_TAG_PREF.get(t.get("type"), 0.0) + 0.1 * _pop(t),
            _name_match(text, t.get("name")), t) for t in tags or []]
    out.sort(key=lambda x: -x[0])
    return out


def _venue_like(text):
    """'Pappy's Smokehouse', 'Katz's Delicatessen', 'Sid's': a possessive or a venue word reads as a place name.
    (Chains and landmarks are caught by Qloo's own nearby_attraction tag of the same name, in resolve_love.)"""
    raw = (text or "").lower().replace("’", "'")
    return bool(re.search(r"[a-z]'s\b", raw)) or bool(set(M.norm(text).split()) & VENUE_WORDS)


def _collab(name, top):
    """'Beyoncé & Nicki Minaj', 'Taylor Swift, Bon Iver': a credit that names the picked artist plus others."""
    n, t = M.norm(name or ""), M.norm(top or "")
    return bool(t) and n != t and (" %s " % t) in (" %s " % n) and bool(re.search(r"[&,]| x | feat| with | and ", (name or "").lower()))


def _disamb(r):
    d = r.get("disambiguation") or prop(r, "disambiguation") or prop(r, "address") or ""
    return str(d)[:80] or None


def _ent_alt(r, sub):
    return {"id": r["entity_id"], "label": r.get("name"), "kind": "entity", "type": sub, "disamb": _disamb(r)}


def _tag_alt(t):
    return {"id": t.get("id") or t.get("tag_id"), "label": t.get("name"), "kind": "tag", "type": t.get("type")}


def _love_alts(alts, top_id, top_name=None, n=3):
    """Up to n alternatives: no repeat of the pick, one per (name, type)."""
    seen, out = {(M.norm(top_name or ""), None)}, []
    for a in alts:
        k = (M.norm(a.get("label") or ""), a.get("type") if a.get("kind") == "entity" else None)
        if a.get("id") == top_id or k in seen or not a.get("id"):
            continue
        seen.add(k)
        out.append(a)
    return out[:n]


def resolve_love(q, text, hint=None):
    """-> {text, status ok|needs_input|miss, kind entity|tag, id, name, type, disamb, is_place, alternatives, dead,
    dead_reason}. needs_input still carries the top candidate, so scripts can proceed the way the kit's 'confirm' did.
    hint: one /search type ('movie' and 'tv_show' search both), 'tag' (tags only), or None (dish and drink tags first,
    then a venue or brand; the site's field 3)."""
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

    def as_entity(ranked, others=()):
        s, m, r, sub = ranked[0]
        rivals = [x for x in ranked[1:] if x[1] >= 0.95]
        ok = m >= 0.95 and (not rivals or bool(hint) or s - rivals[0][0] >= 0.05)
        rest = [x for x in ranked[1:] if not (x[3] == "urn:entity:artist" and _collab(x[2].get("name"), r.get("name")))]
        out.update({"kind": "entity", "id": r["entity_id"], "name": r.get("name"), "type": sub,
                    "disamb": _disamb(r), "status": "ok" if ok else "needs_input", "is_place": sub == PLACE,
                    "alternatives": _love_alts([_ent_alt(x[2], x[3]) for x in rest] + list(others), r["entity_id"])})
        return out

    def as_food_tag(ranked, ok, others=()):
        t = ranked[0][2]
        tid = t.get("id") or t.get("tag_id")
        out.update({"kind": "tag", "id": tid, "name": t.get("name"), "type": t.get("type") or "tag",
                    "status": "ok" if ok else "needs_input",
                    "alternatives": _love_alts([_tag_alt(x[2]) for x in ranked[1:]] + list(others), tid,
                                               t.get("name"))})
        if dead_tag(t):
            out.update({"dead": True, "dead_reason": "vibe"})
        return out

    pre = _pre_resolved().get(M.norm(text))
    if pre and (not hint or hint == "tag" and pre.get("kind") == "tag" or pre.get("type", "").endswith(":" + hint)):
        out.update({"kind": pre["kind"], "id": pre["id"], "name": pre["name"], "type": pre["type"], "status": "ok",
                    "is_place": pre["type"] == PLACE, "pre_resolved": True})
        if pre["kind"] == "tag" and dead_tag({"type": pre["type"], "id": pre["id"]}):
            out.update({"dead": True, "dead_reason": "vibe"})
        return out
    if hint == "tag":
        tags = q.tags(text, take=5, label="C2 love tag") or q.tags(text, take=5, semantic=True, label="C2 love tag~")
        return as_tag(tags, True) if tags else out
    if hint:
        # A film-or-show hint searches films AND TV shows (the site's field 2 sends 'movie' for "a film or show you
        # can quote"); the hinted type only breaks near-ties. Other hints keep their one type.
        screen = "urn:entity:%s" % hint in SCREEN_TYPES
        types = ",".join(SCREEN_TYPES) if screen else "urn:entity:%s" % hint
        res = q.search(text, types=types, take=10 if screen else 5, label="C2 love")
        ranked = _rank_entities(text, res, ("urn:entity:%s" % hint,))
        if (not ranked or ranked[0][1] < 0.95) and not M.fold(text).startswith("the "):
            ids = {r["entity_id"] for r in res}
            more = q.search("The " + text, types=types, take=10 if screen else 5, label="C2 love")
            ranked = _rank_entities(text, res + [r for r in more if r["entity_id"] not in ids], ("urn:entity:%s" % hint,))
        if ranked:
            return as_entity(ranked)
        tags = q.tags(text, take=5, label="C2 love tag") or q.tags(text, take=5, semantic=True, label="C2 love tag~")
        return as_tag(tags, True) if tags else out
    # No hint: the site's field 3, "something you'd order". Dish and drink TAGS first; a restaurant is never offered
    # for a dish, and a place only when the text reads as a venue name (no dish tag covers it, or it says so).
    tags = _rank_tags(text, q.tags(text, take=10, label="C2 love tag"))
    food = [x for x in tags if x[2].get("type") in LOVE_TAG_PREF]
    strong = bool(food) and food[0][1] >= 0.95
    worded = _venue_like(text)
    # Qloo tags chains and landmarks ("Starbucks", "Shake Shack", "Katz's Delicatessen") as nearby_attraction
    venue = worded or any(x[1] >= 0.95 and "nearby_attraction" in (x[2].get("type") or "") for x in tags)
    if strong and not venue:
        return as_food_tag(food, True)
    res = q.search(text, take=10, label="C2 love")
    dishy = bool(food) and food[0][1] >= 0.7 and not venue     # the text names a dish, maybe a less common one
    ents = [x for x in _rank_entities(text, res, free=True, venue=venue, worded=worded) if x[3] != PLACE or not dishy]
    tag_alts = [_tag_alt(x[2]) for x in (food or tags)[:3]]
    if ents and ents[0][1] >= 0.95:
        return as_entity(ents, tag_alts)
    if strong:
        return as_food_tag(food, True)
    if dishy or food and not ents:
        return as_food_tag(food, False)
    named = [x for x in tags if x[1] >= 0.95 and "nearby_attraction" not in (x[2].get("type") or "")]
    if named:                                   # "cozy": Qloo's own tag of that name (a vibe is flagged dead)
        return as_food_tag(named, True)
    if ents:
        return as_entity(ents, tag_alts)
    if tags:
        return as_food_tag(tags, False)
    tags = q.tags(text, take=5, semantic=True, label="C2 love tag~")
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


# ---------------------------------------------------------------- dish loves
def dish_tag_ids(q, love):
    """The love's tag plus same-name siblings of the dish kinds (rib tips: specialty_dish and menu_highlight)."""
    ids = [love["id"]]
    label = love.get("name") or love["text"]
    try:
        tags = q.tags(label, take=10, label="C2 dish siblings") or []
    except QlooError:
        tags = []
    for t in tags:
        tid = t.get("id") or t.get("tag_id")
        if tid and tid not in ids and M.norm(t.get("name") or "") == M.norm(label) and \
                any(k in (t.get("type") or tid) for k in CFG["DISH_SIBLING_TYPES"]):
            ids.append(tid)
    return ids[:3]


def dish_pools(q, city, loves, tag_loves, workers=None):
    """-> ({love text: set of tag ids}, [entities], {love text: set of ids returned}, diag). base filters with
    filter.tags = the dish's tag ids (union) instead of the restaurant/bar kinds; the floor still applies."""
    tagsets, ents, hit, calls = {}, [], {}, 0
    jobs = []
    for l in tag_loves:
        ids = dish_tag_ids(q, l)
        tagsets[l["text"]] = set(ids)
        for off in CFG["DISH_OFFSETS"]:
            p = dict(base_filters(city, loves), take=CFG["TAKE"])
            p["filter.tags"] = sorted(ids)
            p["operator.filter.tags"] = "union"
            if off:
                p["offset"] = off
            jobs.append((l["text"], off, p))

    def run(job):
        txt, off, p = job
        try:
            return job, q.insights(p, label="C4 dish %s o%d" % (txt[:16], off), timeout=TIMEOUT_POOL), None
        except QlooError as e:
            return job, None, e

    for (txt, off, p), resp, err in _pmap(run, jobs, workers or CFG["WORKERS"]):
        calls += 1
        if isinstance(err, QlooDeadline):
            raise err
        if err is not None:
            continue
        url = "%s/v2/insights?%s" % (q.base, canonical_query(p))
        for e in (resp.get("results") or {}).get("entities") or []:
            hit.setdefault(txt, set()).add(e["entity_id"])
            e["_loves"], e["_pool_urls"] = [txt], [url]
            ents.append(e)
    return tagsets, ents, hit, {"calls": calls}


# ---------------------------------------------------------------- floor
_TAG_FACTS = {"cfg": None, "memo": {}}


def _tag_facts(t):
    """(eatery, kind_tag, fast, hit, music) for one tag dict. Pure in the tag and CFG, so memoised: Qloo's tag
    vocabulary is small and every place repeats it."""
    cfg = (tuple(CFG["EXCLUDE_TAG_PATTERNS"]), tuple(CFG["EXCLUDE_TAG_NAMES"]), tuple(CFG["NON_FOOD_CATEGORIES"]))
    if _TAG_FACTS["cfg"] != cfg:
        _TAG_FACTS["cfg"], _TAG_FACTS["memo"] = cfg, {}
    key = (t.get("id"), t.get("tag_id"), t.get("name"))
    f = _TAG_FACTS["memo"].get(key)
    if f is None:
        pats, names, nonfood = cfg
        tid = (t.get("id") or t.get("tag_id") or "").lower()
        eatery = tid in ("urn:tag:category:place:restaurant", "urn:tag:category:place:bar") or \
            (tid.startswith("urn:tag:genre:place:restaurant") and "fast_food" not in tid)
        # live data (28 Oct): setting/decor/interest tags ("setting:qloo:hotel" on Ruth's Chris) are not the
        # place's kind, so only category/genre tags, plus fast-food cuisine tags, can exclude it
        kind_tag = tid.startswith(("urn:tag:category:place:", "urn:tag:genre:place:"))
        fast = "fast_food" in tid and (kind_tag or tid.startswith(("urn:tag:cuisine:", "urn:tag:culinary_style:")))
        hit = any(p in tid for p in pats) or (t.get("name") or "").strip().lower() in names
        music = any(m in tid for m in ("music_venue", "concert_venue", "concert_hall"))
        never = ("adult_entertainment" in tid or "strip_club" in tid or
                 (tid.startswith("urn:tag:category:place:") and tid[len("urn:tag:category:place:"):] in nonfood))
        f = (eatery, kind_tag, fast, hit, music, never)
        if len(_TAG_FACTS["memo"]) > 100000:
            _TAG_FACTS["memo"] = {}
        _TAG_FACTS["memo"][key] = f
    return f


def excluded_kind(e):
    tags = [t for t in (e.get("tags") or []) if isinstance(t, dict)]
    facts = [_tag_facts(t) for t in tags]
    eatery = any(f[0] for f in facts)
    for t, f in zip(tags, facts):
        if f[5]:
            return t.get("id") or t.get("name")      # not a place to eat or drink, whatever else it is
    for t, (_, kind_tag, fast, hit, music, _n) in zip(tags, facts):
        # §3.1 hard-excludes food courts, hotels, malls, groceries, butchers and gyms outright; only a music
        # venue that is also tagged a restaurant or bar (a jazz bar with a kitchen) is kept
        if hit and (fast or (kind_tag and (not music or not eatery))):
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
            state = (C.CITIES.get(city.get("key")) or {}).get("region")
            where = prop(e, "admin1_region")
            if state and where and str(where).lower() != state.lower():
                drop["outside_R"] += 1           # outside the city's state (690 Park, Cliffside Park NJ, in NYC)
                drop["outside_state"] = drop.get("outside_state", 0) + 1
                drop["ids"]["outside_R"].append(e["entity_id"])
                continue
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
        self.prefetched, self.lock, self.unsure = {}, threading.Lock(), {}

    def shares_token(self, raw):
        if not hasattr(self, "_ti"):
            self._ti = M.TokenIndex(self.u_tokens)      # same test, compared only within tok_eq's length bound
        return any(self._ti.any_eq(t) for t in M.distinctive(raw))

    def __call__(self, raw):
        if raw in self.prefetched:
            return self._consume(raw, self.prefetched.pop(raw))
        if self.q is None or not self.shares_token(raw):
            self.skipped.add(raw)
            return []
        return self._consume(raw, self._search(raw))

    def prefetch(self, raws):
        """The chosen names' /search calls, in parallel within the global bucket."""
        out = _pmap(lambda r: (r, self._search(r)), list(raws), CFG["C7_WORKERS"])
        self.prefetched.update(dict(out))

    def _search(self, raw):
        lat, lon = self.city["center_latlon"]
        with self.lock:
            self.calls += 1
        try:
            return self.q.search(raw, types=PLACE, take=5, location="%s,%s" % (lat, lon),
                                 radius_mi=CFG["SEARCH_RADIUS_MI"], label="C7 name")
        except QlooDeadline:
            raise
        except QlooError:
            return QlooError

    def _consume(self, raw, res):
        if res is QlooError:
            self.busy.add(raw)
            return []
        for r in res:
            if not_restaurant_or_bar(r):
                self.nonvenue.add(r["entity_id"])
            if prop(r, "is_closed") is True:
                self.closed.add(r["entity_id"])
        return [{"entity_id": r["entity_id"], "name": r.get("name", "")} for r in res]


def fuzzy_score(raw, name):
    """The matcher's own fuzzy measure, name to name: the better of the normalised-name ratio and the share of the
    AI name's distinctive tokens that tok_eq a token of the pool name."""
    a, b = M.norm(raw), M.norm(name)
    if not a or not b:
        return 0.0
    r = M.difflib.SequenceMatcher(None, a, b).ratio()
    dr, dp = M.distinctive(raw), M.distinctive(name)
    return max(r, (M.overlap(dr, dp) / float(len(dr))) if dr else 0.0)


def c7_plan(raws, pool, budget=None):
    """-> (search: [raw], unsure: {raw: (eid, score)}, skipped: [raw]) for the names R1-R5 did not strike.
    A candidate shares a rare distinctive token with U: >= 4 letters, outside the generic/city stoplists, and found
    (exactly or by tok_eq) in at most C7_RARE_MAX pool names. Candidates are ranked by their best fuzzy score
    against those pool names; the first C7_MAX are searched; the rest strike their best match locally when that
    score reaches UNSURE_STRIKE."""
    tok_names = {}
    for p in pool:
        for t in set(M.distinctive(p["name"])):
            tok_names.setdefault(t, set()).add(p["entity_id"])
    ti = M.TokenIndex(tok_names)
    name_of = {p["entity_id"]: p["name"] for p in pool}
    ranked, skipped = [], []
    for raw in raws:
        cands = set()
        for t in set(M.distinctive(raw)):
            if len(t) < CFG["C7_MIN_TOKEN"] or t in M.STOP:
                continue
            ids = set()
            for u in ti.related(t):
                ids |= tok_names[u]
            if 0 < len(ids) <= CFG["C7_RARE_MAX"]:
                cands |= ids
        if not cands:
            skipped.append(raw)
            continue
        best = max(((fuzzy_score(raw, name_of[e]), e) for e in sorted(cands)), key=lambda x: (x[0], x[1]))
        ranked.append((-best[0], raws.index(raw), raw, best[1], best[0]))
    ranked.sort()
    cap = CFG["C7_MAX"] if budget is None else max(0, budget)
    search = [r[2] for r in ranked[:cap]]
    unsure = {r[2]: (r[3], r[4]) for r in ranked[cap:]}
    return search, unsure, skipped


def one_word_r2(raw, hits):
    """Is every strike of this name a one-word R2 containment ("home", "rooftop", "golden")? Those are vetoed unless
    /search can't place the name outside U (the old path's rule)."""
    if not hits or any(rule != "R2" for _, rule in hits):
        return False
    dr = M.distinctive(M.split_parts(raw)[0]) or M.distinctive(raw)
    return len(dr) == 1


def strike(q, city, U, wall_names, use_search=True):
    pool = [{"entity_id": e["entity_id"], "name": e.get("name", "")} for e in U]
    cs = CitySearch(q if use_search else None, city, U)
    if CFG["C7_MODE"] == "all" or q is None or not use_search:
        struck, per = M.match_wall(wall_names, pool, cs)
        return struck, per, cs
    raws = list(dict.fromkeys(wall_names))
    struck, per = M.match_wall(raws, pool, None)             # R1-R5 locally: no call for a name they strike
    hits_of = {}
    for eid, v in struck.items():
        for raw, rule in v:
            hits_of.setdefault(raw, []).append((eid, rule))
    name_of = {p["entity_id"]: p["name"] for p in pool}
    veto = [r for r in raws if one_word_r2(r, hits_of.get(r))]
    for r in veto:                                           # lift the one-word R2 strikes; /search decides below
        for eid, _ in hits_of[r]:
            struck[eid] = [x for x in struck[eid] if x[0] != r]
            if not struck[eid]:
                del struck[eid]
        per[r] = {"status": "not_found", "ids": [], "resolved": None}
    veto = sorted(veto, key=lambda r: (-max(fuzzy_score(r, name_of[e]) for e, _ in hits_of[r]), raws.index(r)))
    rest = [r for r in raws if not per[r]["ids"] and r not in set(veto)]
    search, unsure, skipped = c7_plan(rest, pool, CFG["C7_MAX"] - min(len(veto), CFG["C7_MAX"]))
    cs.skipped.update(skipped)
    cs.vetoed = veto[CFG["C7_MAX"]:]                         # past the cap: the one-word strike is not applied
    cs.skipped.update(cs.vetoed)
    search = veto[:CFG["C7_MAX"]] + search
    if search:
        cs.prefetch(search)
        st2, per2 = M.match_wall(search, pool, cs)           # the matcher's own S stage on the chosen names
        for eid, v in st2.items():
            struck.setdefault(eid, []).extend(v)
        per.update(per2)
    for raw, (eid, score) in unsure.items():
        if score >= CFG["UNSURE_STRIKE"]:                    # when unsure, strike (over-striking is accepted)
            struck.setdefault(eid, []).append((raw, "U"))
            per[raw] = {"status": "struck_unsure", "ids": [eid], "resolved": None, "rule": "unsure, not searched"}
        else:
            cs.skipped.add(raw)
    cs.unsure = unsure
    return struck, per, cs


_NRB = {}


def not_restaurant_or_bar(e):
    """Tags known and either no restaurant/bar category tag, or an allowlist hard-exclude. Memoised per entity and
    tag count (a /search result's tags don't change within the cache TTL)."""
    k = (e.get("entity_id"), len(e.get("tags") or ()), tuple(CFG["EXCLUDE_TAG_PATTERNS"]))
    if k not in _NRB:
        if len(_NRB) > 50000:
            _NRB.clear()
        _NRB[k] = _not_restaurant_or_bar(e)
    return _NRB[k]


def _not_restaurant_or_bar(e):
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


class _Toks(set):
    """An answer's token set, plus its tokens by length (built once) for the +-3 letters fuzzy test."""

    def by_len(self):
        b = getattr(self, "_b", None)
        if b is None:
            b = self._b = {}
            for x in self:
                b.setdefault(len(x), []).append(x)
        return b


class _RIndex(list):
    """[(i, tokens)] plus a token -> answers index, so each distinct answer token is compared once, not per answer."""

    def answers_for(self, t):
        memo = self.__dict__.setdefault("_memo", {})
        if t not in memo:
            if "_vocab" not in self.__dict__:
                v = {}
                for i, toks in self:
                    for x in toks:
                        v.setdefault(x, set()).add(i)
                self._vocab = v
                self._vlen = {}
                for x in v:
                    self._vlen.setdefault(len(x), []).append(x)
            hit = set(self._vocab.get(t, ()))
            for n in range(len(t) - 3, len(t) + 4):
                for x in self._vlen.get(n, ()):
                    if x != t and M.tok_eq(t, x):
                        hit |= self._vocab[x]
            memo[t] = hit
        return memo[t]


_RCACHE = []        # [(answers kept alive, its index)]: the dated wall's reverse index is built once per snapshot


def reverse_index_cached(answers):
    ids = tuple(map(id, answers))
    for kept, ri in _RCACHE:
        if len(kept) == len(answers) and tuple(map(id, kept)) == ids:
            return ri
    ri = reverse_index(answers)
    _RCACHE.append((list(answers), ri))
    del _RCACHE[:-8]
    return ri


def reverse_index(answers):
    return _RIndex((i, _Toks(M.tokens(answer_text(a)))) for i, a in enumerate(answers))


def _tok_in(t, toks):
    if t in toks:
        return True
    if isinstance(toks, _Toks):
        b = toks.by_len()
        return any(M.tok_eq(t, x) for n in range(len(t) - 3, len(t) + 4) for x in b.get(n, ()))
    return any(M.tok_eq(t, x) for x in toks if abs(len(x) - len(t)) <= 3)


def reverse_hit(name, rindex):
    """Fuzzy, local, 0 calls: every distinctive token of the card's name appears in one stored answer's raw text."""
    d = M.distinctive(name or "")
    if not d:
        return None
    if isinstance(rindex, _RIndex):              # same answer as the scan below: the first answer holding them all
        common = None
        for t in d:
            a = rindex.answers_for(t)
            common = set(a) if common is None else common & a
            if not common:
                return None
        order = {i: k for k, (i, _) in enumerate(rindex)}
        return min(common, key=order.get)
    for i, toks in rindex:
        if all(_tok_in(t, toks) for t in d):
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


# ---------------------------------------------------------------- what the place IS (card front, §2.1)
WHAT_BLAND = {"restaurant", "bar", "place", "american", "bar food", "food", "casual", "casual dining",
              "comfort food", "new american", "pub food", "dining drinking"}
WHAT_KEEP_B = ("live music", "jazz", "blues", "r&b", "soul music", "hip hop", "karaoke", "comedy", "open mic",
               "live performances", "dj", "drag", "line dancing", "dancing", "dance floor", "trivia", "happy hour",
               "sports viewing", "billiards", "pool table", "darts")       # (b), in this order of preference
WHAT_CUISINE_FIRST = ("soul food", "barbecue", "bbq", "cajun", "creole", "caribbean", "jamaican", "ethiopian",
                      "vietnamese", "thai", "mexican", "italian", "chinese", "korean", "japanese", "indian",
                      "mediterranean", "middle eastern", "seafood", "southern", "steakhouse", "wings")
WHAT_RENAME = {"happy hour drinks": "happy hour", "happy hour food": "happy hour", "blues music": "blues",
               "jazz music": "jazz", "live performances": "live shows", "dance floor": "dancing"}
WHAT_B_PREFIX = ("urn:tag:interests:", "urn:tag:activity_type:", "urn:tag:offerings:", "urn:tag:amenity:qloo:",
                 "urn:tag:entertainment", "urn:tag:music")


def _what_label(t):
    n = (t.get("name") or "").strip().lower()
    n = re.sub(r"\s+us$", "", n)                                   # "southern restaurant us" -> "southern restaurant"
    n = re.sub(r"\s+restaurant$", "", n) if n != "restaurant" else n  # "southern restaurant" -> "southern"
    return WHAT_RENAME.get(n, n)


def _b_rank(lab):
    for k, w in enumerate(WHAT_KEEP_B):
        if lab == w or lab.startswith(w + " ") or lab.endswith(" " + w):
            return k
    return len(WHAT_KEEP_B)


def _a_rank(item):
    lab, is_kind = item
    pref = next((k for k, w in enumerate(WHAT_CUISINE_FIRST) if w == lab), len(WHAT_CUISINE_FIRST))
    return (0 if is_kind else 1, pref)


def what_line(e, n=2):
    """Two tags that say what the place IS: (a) cuisine / genre:place:restaurant:<x> / category:place:<x> kinds,
    specific before bland ("soul food" before "american", "sports bar" before "bar"); then (b) music, entertainment
    or offering tags (live music, jazz, karaoke, comedy, happy hour, dancing). Never amenity, payment, accessibility,
    demographic, time-of-day, price or "place" tags. When the place has any kind tag, one is always shown, first."""
    a1, a2, b = [], [], []
    for t in e.get("tags") or []:
        if not isinstance(t, dict) or not t.get("name"):
            continue
        tid = (t.get("id") or "").lower()
        raw = (t.get("name") or "").strip().lower()
        lab = _what_label(t)
        if tid.startswith(("urn:tag:cuisine:", "urn:tag:category:place:", "urn:tag:genre:place:restaurant:")):
            (a2 if lab in WHAT_BLAND else a1).append((lab, not tid.startswith("urn:tag:cuisine:")))
        elif tid.startswith(WHAT_B_PREFIX) and any(raw == k or raw.startswith(k + " ") or raw.endswith(" " + k)
                                                   for k in WHAT_KEEP_B):
            b.append(lab)
    a1 = [lab for lab, _ in sorted(a1, key=_a_rank)]            # kinds ("cocktail bar") first, then cuisines
    a2 = [lab for lab, _ in a2]
    b = sorted(b, key=_b_rank)
    seen, a1u, bu, a2u = set(), [], [], []
    for src, dst in ((a1, a1u), (b, bu), (a2, a2u)):
        for x in src:
            k = re.sub(r"[^a-z0-9]+", "", x.replace("&", "").replace("+", "").replace(" and ", ""))
            if k not in seen:            # "bar + grill" == "bar & grill" == "bar grill"
                seen.add(k)
                dst.append(x.replace(" + ", " & "))
    a2u = [x for x in a2u if not any(x in y.split(" ") for y in a1u)]     # "bar" never beside "sports bar"
    pick = (a1u + bu + a2u)[:n]
    if (a1u or a2u) and not any(x in a1u + a2u for x in pick):            # say what it is first
        pick = [(a1u or a2u)[0]] + pick[:n - 1]
    kinds = [x for x in pick if x in a1u + a2u]
    return " · ".join(kinds + [x for x in pick if x not in kinds])


# ---------------------------------------------------------------- the neighbourhood fallback
_HOODS = {}


def osm_hoods(city_key):
    """fixtures/hood_centroids.json (OSM, written by hood_centroids.py) -> [(name, lat, lon)], or []."""
    if city_key not in _HOODS:
        fp = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures",
                          "hood_centroids.json")
        rows = []
        try:
            with open(fp) as f:
                rows = [(r["name"], r["lat"], r["lon"]) for r in json.load(f)["cities"].get(city_key, [])]
        except (OSError, ValueError, KeyError):
            pass
        _HOODS[city_key] = rows
    return _HOODS[city_key]


def pool_hoods(pool):
    """Centroids of the neighbourhoods Qloo names on the pool's own places (0 calls): the stand-in when the OSM file
    has nothing near."""
    acc = {}
    for e in pool:
        h, ll = prop(e, "neighborhood"), latlon(e)
        if h and ll:
            a = acc.setdefault(h, [0.0, 0.0, 0])
            a[0] += ll[0]
            a[1] += ll[1]
            a[2] += 1
    return [(h, a[0] / a[2], a[1] / a[2]) for h, a in acc.items()]


def hood_of(e, centroids, max_mi=1.5):
    """-> (neighbourhood, src): Qloo's own field (qloo), else the nearest centroid within 1.5 mi (osm, then pool),
    else ("", None)."""
    h = prop(e, "neighborhood")
    if h:
        return h, "qloo"
    ll = latlon(e)
    if not ll:
        return "", None
    for src, rows in centroids:
        best = None
        for name, la, lo in rows:
            d = C.haversine_mi(ll, (la, lo))
            if d <= max_mi and (best is None or d < best[0]):
                best = (d, name)
        if best:
            return best[1], src
    return "", None


# ---------------------------------------------------------------- card lines
def display_name(name):
    """'Space Ping Pong Sports Bar & Lounge | Koreatown NYC' -> 'Space Ping Pong Sports Bar & Lounge'."""
    return (name or "").split(" | ")[0].strip() or name


def why_line(f, p, e, flat):
    """One line from the selection score's parts: fit for you f, popularity p, fit for everyone e (percentiles)."""
    if flat:
        return "fits you, among the less famous places here"
    gap = f - max(p, e if e is not None else 0.0)
    if e is not None and e <= 0.35 and gap >= 0.5:
        return "fits you far more than it fits most people here"
    if p <= 0.35 and gap >= 0.5:
        return "fits you, and few people here know it"
    if e is not None and e < p:
        return "fits you more than its fame suggests"
    return "fits you better than most of the places here"


WHAT_TAG_PREFIX = ("urn:tag:cuisine:", "urn:tag:category:place:", "urn:tag:genre:place:restaurant:",
                   "urn:tag:menu_highlight:", "urn:tag:specialty_dish:", "urn:tag:interests:", "urn:tag:offerings:",
                   "urn:tag:activity_type:", "urn:tag:beverage_offering:", "urn:tag:ambience:", "urn:tag:decor:")
_DETAIL = {}


def _tags_of(e):
    out = {}
    for t in e.get("tags") or []:
        if isinstance(t, dict) and (t.get("id") or "").startswith(WHAT_TAG_PREFIX) and t.get("name"):
            lab = _what_label(t)
            if lab and lab not in WHAT_BLAND:
                out[t["id"]] = lab
    return out


def because_detail(i, love, byid, ids, orders, tied, dish_tags, dish_tagged):
    """The one or two Qloo tags that tie the card to the love it credits. A dish love: the dish tag itself. Any other
    love: the card's tags that are most over-represented among that love's top quarter of this pool (Qloo's own
    per-love ranking and Qloo's own tags; 0 extra calls)."""
    if not love:
        return None
    txt = love["text"]
    if txt in dish_tags:
        return ("on Qloo's %s list" % (love.get("name") or txt).lower()) if i in dish_tagged.get(txt, ()) else None
    key = (id(orders), txt)
    if key not in _DETAIL:
        _DETAIL.clear()
        o = orders[txt]
        top = [x for x in ids if x not in tied[txt]]
        top = sorted(top, key=lambda x: o[x])[:max(5, len(ids) // 4)]
        cnt_top, cnt_all = {}, {}
        for x in ids:
            for tid in _tags_of(byid[x]):
                cnt_all[tid] = cnt_all.get(tid, 0) + 1
        for x in top:
            for tid in _tags_of(byid[x]):
                cnt_top[tid] = cnt_top.get(tid, 0) + 1
        lift = {}
        for tid, n in cnt_top.items():
            if n >= 3 and n / float(len(top)) >= 0.2:
                lift[tid] = (n / float(len(top))) / (cnt_all[tid] / float(len(ids)))
        _DETAIL[key] = lift
    lift = _DETAIL[key]
    mine = _tags_of(byid[i])
    best = sorted(((lift[t], mine[t]) for t in mine if lift.get(t, 0) >= 1.5), reverse=True)
    labs = list(dict.fromkeys(l for _, l in best))[:2]
    if not labs:
        return None
    return "%s, like the places %s fans rank highest here" % (" and ".join(labs), love.get("name") or txt)


# ---------------------------------------------------------------- the "everyone's taste" prior
_PRIORS = {}


def load_prior(city_key):
    fp = os.path.join(CFG["PRIORS_DIR"], "%s.json" % city_key)
    if not os.path.exists(fp):
        fp = os.path.join(CFG["PRIORS_DIR"], "priors-%s.json" % city_key)
    try:
        mt = os.path.getmtime(fp)
    except OSError:
        return None
    hit = _PRIORS.get(city_key)
    if hit and hit[0] == mt:
        return hit[1]
    with open(fp) as f:
        doc = json.load(f)
    _PRIORS[city_key] = (mt, doc)
    return doc


def everyone_pct(city, ids, love_ids):
    """{place: percentile within this U of its mean fit over the preset sets sharing no love with this query}.
    Leave-one-out by love: a frozen set never sees its own data, and a fresh query never sees a set it overlaps."""
    doc = load_prior(city.get("key")) if CFG["PRIOR_ENABLED"] else None
    if not doc:
        return {}, {"used": False, "why": "no prior for this city"}
    sets = [s for s in doc["sets"] if not ({l["id"] for l in s["loves"]} & love_ids)]
    mean = {}
    for i in ids:
        v = [s["fit_pct"][i] for s in sets if i in s["fit_pct"]]
        if len(v) >= CFG["PRIOR_MIN_SETS"]:
            if CFG["PRIOR_STAT"] == "top":     # (hits + 0.5) / (n + 1): a lone observation counts for less
                mean[i] = (sum(1 for x in v if x >= CFG["PRIOR_TOP"]) + 0.5) / (len(v) + 1.0)
            else:
                mean[i] = sum(v) / len(v)
    if len(mean) < 3:
        return {}, {"used": False, "why": "too few places with a prior", "sets": len(sets)}
    rk = ST.rank(mean)                       # 1 = fits everyone best
    n = len(mean)
    return ({i: ST.pct(rk[i], n) for i in mean},
            {"used": True, "sets": len(sets), "excluded_sets": len(doc["sets"]) - len(sets), "covered": n,
             "U": len(ids), "built_at": doc.get("built_at")})


# ---------------------------------------------------------------- CAP and the popularity proofs
def popularity_cap(q, city, loves, U, struck_u, pop, pop_rank):
    k = len(struck_u)
    out = {"k": k, "max": None, "cap7": [], "calls": 0, "error": None}
    if not CFG["CAP_ENABLED"]:
        out["error"] = "skipped (CAP_ENABLED off)"
        return out
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
    cpu = CPU()
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
    cpu.mark("resolve")
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
    tag_loves = [l for l in rescorable if l.get("kind") == "tag"] if CFG["DISH_POOL"] else []
    dish_tags, dish_hit = {}, {}
    if tag_loves:                         # the dish sub-pools join the pool like any love's pool
        dish_tags, dents, dish_hit, ddiag = dish_pools(q, city, loves, tag_loves)
        have = {e["entity_id"]: e for e in pool}
        for e in dents:
            if e["entity_id"] in have:
                have[e["entity_id"]]["_loves"] = list(dict.fromkeys(have[e["entity_id"]]["_loves"] + e["_loves"]))
                continue
            e["_pos"] = len(pool) + 1
            pool.append(e)
            have[e["entity_id"]] = e
        pdiag["dish_calls"] = ddiag["calls"]
    U, drops = floor(pool, city)
    for step in ("EXTRA_OFFSETS", "EXTRA_OFFSETS_2"):
        if len(U) >= CFG["U_MIN"] or not CFG.get(step):
            break
        more, mdiag = per_love_pools(q, city, loves, offsets=CFG[step])
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
    cpu.mark("pool")

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

    # C6' (every love at once) runs beside the strike: both need only U. The global bucket paces them together.
    side = ThreadPoolExecutor(max_workers=2)
    do_rescore = lambda: _pmap(lambda l: rescore(q, city, loves, ids, l, "C6' %s" % l["text"][:18]),  # noqa: E731
                               rescorable, max(1, len(rescorable)))
    struck, per, css = {}, {}, []
    if CFG["CONCURRENT"]:
        resc_future = side.submit(do_rescore)
        try:
            strike_answers(answers, struck, per, css)
        finally:
            resc_all = resc_future.result()       # re-raises a deadline or budget stop from the rescoring
        cpu.mark("rescore+strike")
    else:
        resc_all = do_rescore()
        cpu.mark("rescore")
        strike_answers(answers, struck, per, css)
        cpu.mark("strike")

    # ---- C6' per-love orders (one love's signal per call)
    pop = {i: popularity(byid[i]) for i in ids}
    pop_rank_avg = ST.rank(pop)
    pop_ord = ordinal(pop, ids)
    orders, tied, tied_only, rs_diag = {}, {}, {}, {}
    dish_tagged = {}
    for l, rs in zip(rescorable, resc_all):
        orders[l["text"]] = ranks_from(rs["aff"], ids)
        tied[l["text"]] = set(rs["tied"]) | set(rs["missing"])     # no non-default score (eligibility)
        tied_only[l["text"]] = set(rs["tied"])                      # at Qloo's default affinity (tie share)
        if l["text"] in dish_tags:
            tagset = dish_tags[l["text"]]
            tagged = {i for i in ids if i in dish_hit.get(l["text"], ()) or
                      any((t.get("id") or "") in tagset for t in byid[i].get("tags") or [] if isinstance(t, dict))}
            if tagged:
                # carries the dish > untagged that Qloo scored > the rest; a tagged place is never a tie
                informative = {i: rs["aff"][i] for i in ids if i in rs["aff"] and i not in rs["tied"]}
                score = {i: (10.0 + informative.get(i, 0.0)) if i in tagged else informative.get(i, -1.0) for i in ids}
                orders[l["text"]] = ST.rank(score)
                tied[l["text"]] = {i for i in ids if i not in tagged and i not in informative}
                tied_only[l["text"]] = set()     # tagged vs not is information, not a tie
                dish_tagged[l["text"]] = tagged
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
    tie_by_love = {l["text"]: len(tied_only[l["text"]]) / float(N) for l in rescorable}
    for l in rescorable:
        r = rs_diag[l["text"]]["rho_pop"]
        if tie_by_love[l["text"]] >= CFG["DEAD_TIE"]:
            l["dead"], l["dead_reason"] = True, "ties %.2f" % tie_by_love[l["text"]]
        elif r == r and r >= CFG["DEAD_RHO"]:
            l["dead"], l["dead_reason"] = True, "rho %.2f" % r
    live = [l for l in rescorable if not l.get("dead")]
    all_dead = not live
    struck_u0 = set(struck) & set(ids)
    cap_future = side.submit(popularity_cap, q, city, loves, U, struck_u0, pop, pop_ord)   # beside the cards
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
    # lift = pct(fit for you) - max(pct(popularity), pct(fit for everyone)): what fits THIS person, beyond what is
    # famous and beyond what fits every taste. No prior for a place (fewer than PRIOR_MIN_SETS other sets) -> popularity.
    everyone, prior_diag = everyone_pct(city, ids, {l["id"] for l in loves if l.get("id")})
    lift = {i: pct(fit[i]) - max(pct(pop_ord[i]), everyone.get(i, 0.0)) for i in ids}
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

    # the live lane (Gemini taste ask) is joined only after the cards are out (§3.4: it never gates them)
    live_ans = []
    all_answers = list(answers)
    struck_u = set(struck) & set(ids)

    cpu.mark("orders")
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
        score = {i: round(pct(fit[i]), 4) for i in ids}          # flat: the score is fit (what the order uses)
    else:
        order = sorted(eligible, key=lambda i: (-lift[i], fit[i], i))
        score = {i: round(lift[i], 4) for i in ids}

    # ---- 7 + 3 via the reverse check and the last-seen check
    rindex = reverse_index_cached(all_answers)
    hours_cov = sum(1 for e in U if prop(e, "hours")) / float(N)
    hours_known = hours_cov >= CFG["HOURS_COVERAGE_MIN"]
    selected, rev_struck, unseen, seen_info = [], [], [], {}
    want = CFG["N_CARDS"] + CFG["N_RESERVES"]
    if last_seen is not None and hasattr(last_seen, "prefetch"):     # venue sites in parallel, not one by one
        try:
            last_seen.prefetch([byid[i] for i in order[:want + 8]
                                if reverse_hit(byid[i].get("name"), rindex) is None])
        except Exception:
            pass
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
        info = {"checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "how": "hours (Qloo)" if ok else "failed: %s" % why}
        if ok and last_seen is not None:
            try:
                got = last_seen(e)
                ok, extra = got if isinstance(got, tuple) else (bool(got), None)
                ok = bool(ok)
                if extra:
                    info = extra
                elif not ok:
                    info = dict(info, how="failed: last-seen hook")
                why = None if ok else info["how"]
            except Exception:
                ok = True
        if not ok:                       # struck as "last seen: failed"; the next candidate rises
            unseen.append({"id": i, "name": e.get("name"), "why": why, "last_seen": info})
            emit("strike", {"name": e.get("name"), "norm": M.norm(e.get("name") or ""), "outcome": "struck",
                            "reason": "last seen: failed", "qloo_id": i, "how": info.get("how")})
            continue
        seen_info[i] = info
        selected.append(i)
    centroids = [("osm", osm_hoods(city.get("key"))), ("pool", pool_hoods(pool))]
    hoods = {i: hood_of(byid[i], centroids) for i in selected}
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

    # ---- cards (never_said reads the street asks and the live answer as they accumulate)
    def card(i):
        n_city = len(all_answers)
        as_of = max([a.get("asked_at") or "" for a in all_answers] or [""]) or None
        e = byid[i]
        b = because(i)
        hood, hood_src = hoods[i]
        n_street = len(asked_hoods.get(hood, []))
        is_tied = bool(live) and all(i in tied[l["text"]] for l in live)     # never true for a card
        ll = latlon(e) or (None, None)
        return {"id": i, "name": display_name(e.get("name")), "what": what_line(e), "score": score[i],
                "why": why_line(pct(fit[i]), pct(pop_ord[i]), everyone.get(i), flat),
                "because_detail": because_detail(i, b, byid, ids, orders, tied, dish_tags, dish_tagged), "neighbourhood_src": hood_src,
                "last_seen": seen_info.get(i),
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

    def burn(x, by, at, hood):
        """Take card x off the board; the first reserve rises into the picks."""
        b = {"card_id": x, "name": byid[x].get("name"), "by": by, "at": at, "neighbourhood": hood, "risen": None}
        if x in picks:
            picks.remove(x)
            if reserves:
                up = reserves.pop(0)
                picks.append(up)
                b["risen"] = card(up)
        elif x in reserves:
            reserves.remove(x)
        res["burn"]["burned"].append({k: v for k, v in b.items() if k != "risen"})
        emit("burn", b)

    def street_pass():
        # ---- the street check (L2): a name hit burns the card; the next reserve rises
        if street_check is None or not picks:
            return
        k = 0
        while k < len(picks):
            i = picks[k]
            hood = hoods[i][0]
            if hood and hood not in asked_hoods:
                try:
                    got = list(street_check(hood, city["name"]) or [])
                except Exception as e:
                    got = []
                    lanes_failed.append("street check: %s" % type(e).__name__)
                asked_hoods[hood] = got
                street_answers.extend(got)
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
                        burn(x, by, at, hood)
                k = 0          # re-walk: a risen reserve's street gets asked too
                continue
            k += 1

    cpu.mark("ranking")
    street_pass()
    cpu.mark("street")

    # ---- the live lane (Gemini taste ask), joined after the cards are out (§3.4). Its names join the wall; a card
    # they name (the matcher, then the reverse check on its raw text) burns "by gemini (live)", and a reserve rises.
    if live_answers is not None:
        try:
            live_ans = list(live_answers() or [])
        except Exception as e:  # the lane failed or ran out of time: the dated cards stand
            lanes_failed.append("live lane: %s" % type(e).__name__)
            res["diag"]["live_error"] = str(e)[:200]
        if live_ans:
            for a in live_ans:
                for n in a.get("names") or []:
                    emit("wall_name", wall_item(a, n["name"] if isinstance(n, dict) else n))
            before = set(struck)
            strike_answers(live_ans, struck, per, css)
            all_answers.extend(live_ans)
            live_struck = (set(struck) - before) & set(ids)
            struck_u |= live_struck
            rix = reverse_index(live_ans)
            at = max(a.get("asked_at") or "" for a in live_ans) or None
            hits = [x for x in picks + reserves if x in live_struck or reverse_hit(byid[x].get("name"), rix) is not None]
            for x in [h for h in hits if h in reserves] + [h for h in hits if h in picks]:
                burn(x, "gemini (live)", at, hoods[x][0])
            res["diag"]["live_burned"] = [byid[x].get("name") for x in hits]
            street_pass()                  # a risen card's street is asked too
    picks = sorted(picks, key=lambda i: (fit[i], i))           # displayed in for-you order
    reserves = sorted(reserves, key=lambda i: (-score[i], fit[i], i))  # reserves: the selection order, after the last card

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
    cap = cap_future.result()
    side.shutdown(wait=True)
    if struck_u != struck_u0:                 # the live answer struck more of U: the cap must remove as many
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
    n_city = len(all_answers)
    as_of = max([a.get("asked_at") or "" for a in all_answers] or [""]) or None
    res["counts"].update({"wall": n_places, "asks": n_city + len(street_answers), "S": len(S),
                          "struck_in_U": len(struck_u)})
    res["diag"].update({
        "N": N, "S": len(S), "kept": len(eligible), "flat": flat, "all_dead": all_dead, "thin_taste": thin,
        "prior": prior_diag, "dish_tagged": {k: len(v) for k, v in dish_tagged.items()}, "tie_share": tie_share, "tie_by_love": tie_by_love, "rescore": rs_diag, "rho_tp": rho_tp, "rho_res": rho_res, "rho_res_note": rho_res_note,
        "rho_taste_base": rho_tp, "rho_taste_pop": rho_tp, "baseline": base_label,
        "cap_keep": cap.get("cap_keep"), "cap_shared": len(cap_ids & set(picks)) if cap.get("cap7") else None,
        "popcap_overlap": cap.get("overlap", float("nan")), "cap": {k: v for k, v in cap.items() if k != "topk"},
        "obscure": [(i, byid[i].get("name")) for i in obscure], "known": [(i, byid[i].get("name")) for i in known],
        "auc_pop_struck": ST.auc([pop[i] for i in ids], [i in struck_u for i in ids]),
        "wall_names": len(distinct_norms), "wall_snapshot": _snapshot(wall, live_ans),
        "wall": {"answers": len(all_answers), "names": len(distinct_norms), "places": n_places, "struck": len(struck_u),
                 "status": _count(per), "source": wall.get("source"),
                 "c7_calls": sum(c.calls for c in css), "c7_skipped": sum(len(c.skipped) for c in css),
                 "c7_busy": sum(len(c.busy) for c in css)},
        "reverse_struck": rev_struck, "last_seen_dropped": unseen, "hours_coverage": hours_cov,
        # fit ranks in U (RRF order) of every struck member, wall strike + reverse check: "Your #1-#3 were on the
        # AIs' lists." only when 1, 2 and 3 are all here
        "struck_fit_ranks": sorted(fit[i] for i in set(struck) & set(ids)),
        "lanes_failed": lanes_failed, "as_of": as_of, "elapsed_s": round(time.monotonic() - t0, 3),
        "loves_live": [l["text"] for l in live], "street_asks": len(street_answers)})
    cpu.mark("result")
    res["diag"]["cpu_s"] = cpu.out
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


def _snapshot(wall, live_ans):
    from unsaid.walls import snapshot
    return snapshot({"answers": list(wall.get("answers") or []) + list(live_ans or [])})


def wall_item(a, raw):
    return {"name": raw, "norm": M.norm(raw), "provider": a.get("provider"), "model": a.get("model"),
            "phrasing_id": a.get("phrasing_id") or a.get("phrasing"), "phrasing": a.get("phrasing_text") or
            a.get("phrasing"), "asked_at": a.get("asked_at"), "lane": a.get("lane") or "dated"}


def _count(per):
    c = {}
    for v in per.values():
        c[v["status"]] = c.get(v["status"], 0) + 1
    return c
