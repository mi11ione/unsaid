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
import collections
import hashlib
import json
import math
import os
import re
import sys
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
    "RATING_SERVER": 4,          # no longer sent (30 Oct): Qloo ignores business_rating.min (probe P2); 4.3 is client-side
    "RATING_CLIENT": 4.3, "RATING_EPS": 1e-4,   # client floor 4.3 - 1e-4 (float32 values like 4.1999998)
    "TAKE": 50, "OFFSETS": [0, 50],
    "EXTRA_OFFSETS": [100, 150],  # live 28 Oct: gate B left Cedric at 7+0 (U 28); the 50k/month key affords it
    "EXTRA_OFFSETS_2": [200, 250],  # a second step, only while U is still short (the state rule took ~30 IL places
                                    # out of every STL pool: 28 Oct)
    "U_MIN": 150,
    "CHUNK": 48, "ANCHORS": 2,   # 48 of U + 2 anchors = 50 = take
    "RRF_K": 60, "HOLD_FRAC": 1.0 / 3,
    "N_CARDS": 7, "N_RESERVES": 3,
    # Balance (29 Oct): one love may credit at most LOVE_CAP cards, and every live love credits at least one when it
    # can. A love may also credit a place its order ranks in its top ALT_CREDIT_FRAC (not only the love that ranks
    # it best). A dish love credits only places Qloo tags with the dish. GENERIC_SHARE: a place that this share of
    # the prior's tastes (the anchor panel) put in their top 30% fits everyone, not you, and is never a card.
    "LOVE_CAP": 3, "ALT_CREDIT_FRAC": 0.3, "GENERIC_SHARE": 0.6, "BALANCE_SCAN": 60,
    # Variety (29 Oct): a seven is a list for a person, a mix of places to eat and to drink. At most KIND_CAP cards
    # of one kind ("drink", or "eat" by cuisine family: southern, barbecue, italian, asian, cafe ...); at least
    # MIN_EAT and MIN_DRINK when the eligible pool has them; at least MIN_HOODS neighbourhoods when it can. A greedy
    # re-rank over the same score: the score stays the order, the kinds only skip a card.
    "KIND_CAP": 3, "MIN_EAT": 2, "MIN_DRINK": 2, "MIN_HOODS": 3,
    "MIX_WIDE": True,     # the mix may reach places holding for one pair of loves when all-but-one leaves too few
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
                            # judge 3 (29 Oct): kitchens you can't sit in
                            "shared_use_commercial_kitchen", "commercial_kitchen", "ghost_kitchen", "cloud_kitchen",
                            "virtual_restaurant", "virtual_kitchen",
                            "liquor_store", "wine_store", "beer_store", "banquet_hall", "event_planner",
                            "party_planner", "wedding_planner", "event_management_company",
                            "hookah_bar", "hookah_lounge", "hookah_store"],
    # Diversity: "fit for everyone" prior per city, data/priors/<city>.json (build_priors.py). 30 Oct: the share of
    # ~100 Qloo-sampled anchor tastes (not this query's loves) ranking the place in their top 30% of the city's
    # universe; no value -> the median (everyone_pct). Older 28 Oct files hold the preset sets instead.
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


def _years(r):
    """A film's or show's years from Qloo's disambiguation ('1998,2004') or release_year: [first, last] or []."""
    ys = [int(y) for y in re.findall(r"\b(1[89]\d\d|20\d\d)\b", str(r.get("disambiguation") or ""))]
    if not ys and isinstance(prop(r, "release_year"), (int, str)) and str(prop(r, "release_year")).isdigit():
        ys = [int(prop(r, "release_year"))]
    return [min(ys), max(ys)] if ys else []


def _disamb(r, sub=None):
    """What tells two same-named candidates apart, without the type (api.py puts the type in front): a film's year,
    a show's years, a place's address, else Qloo's disambiguation when it says more than the name, else the top
    genres ('Soul, Rhythm & Blues' for Beyoncé)."""
    if sub in SCREEN_TYPES:
        ys = _years(r)
        return ("%d" % ys[0] if ys[0] == ys[1] or sub == "urn:entity:movie" else "%d–%d" % tuple(ys)) if ys else None
    d = str(r.get("disambiguation") or prop(r, "disambiguation") or prop(r, "address") or "").strip()
    if d and (sub == PLACE or M.norm(d) != M.norm(r.get("name") or "")):
        return d[:80]
    genres = [t.get("name") for t in r.get("tags") or [] if isinstance(t, dict) and t.get("type") == "urn:tag:genre"
              and t.get("name")]
    return ", ".join(genres[:2]) or None


SCREEN_WANT = re.compile(r"\s*[(\[]?\b(?:the )?(movie|film|tv show|tv series|tv|series|show)\b[)\]]?\s*$", re.I)


def _screen_query(text):
    """'Sex and the City movie' -> ('Sex and the City', None, 'urn:entity:movie'); 'Dune (2021)' -> ('Dune', 2021,
    None). A year or a trailing movie/film/tv/series/show word says which one; the title is matched without it."""
    t, year, want = text, None, None
    m = re.search(r"\s*[(\[]?\b(1[89]\d\d|20\d\d)\b[)\]]?\s*$", t)
    if m and m.start() > 0:
        year, t = int(m.group(1)), t[:m.start()]
    m = SCREEN_WANT.search(t)
    if m and m.start() > 0:
        want = "urn:entity:movie" if m.group(1).lower() in ("movie", "film") else "urn:entity:tv_show"
        t = t[:m.start()]
    if year is None:
        m = re.search(r"\s*[(\[]?\b(1[89]\d\d|20\d\d)\b[)\]]?\s*$", t)
        if m and m.start() > 0:
            year, t = int(m.group(1)), t[:m.start()]
    return t.strip(" -,:"), year, want


def _rank_screen(text, title, res, year, want):
    """Films and shows: _rank_entities on the title, then the typed qualifier decides. A year picks the candidate it
    falls in (+0.3); 'movie'/'film' or 'tv'/'series'/'show' picks that type (+0.1); with neither, a TV show whose
    exact title is also a film's wins near-ties in popularity (+0.02, i.e. within 0.04: 'Sex and the City' is the
    series, 0.977 against the 2008 film's 0.981; 'Dune' stays the 2021 film, 0.9996 against the 2000 show's 0.916)."""
    ranked = _rank_entities(title, res)
    if title != text:                           # "Scary Movie", "Blade Runner 2049": the typed text is the title
        full = {id(x[2]): x for x in _rank_entities(text, res)}
        ranked = [(full[id(x[2])][0] + 0.3,) + full[id(x[2])][1:] if full[id(x[2])][1] >= 0.95 > x[1] or
                  full[id(x[2])][1] >= 0.95 and full[id(x[2])][1] >= x[1] else x for x in ranked]
    exact_types = {x[3] for x in ranked if x[1] >= 0.95}
    out = []
    for s, m, r, sub in ranked:
        if m >= 0.95:
            ys = _years(r)
            if year and ys and ys[0] <= year <= ys[1]:
                s += 0.3
            if want and sub == want:
                s += 0.1
            elif not want and not year and sub == "urn:entity:tv_show" and exact_types >= set(SCREEN_TYPES):
                s += 0.02
        out.append((s, m, r, sub))
    out.sort(key=lambda x: -x[0])
    return out


def _ent_alt(r, sub):
    return {"id": r["entity_id"], "label": r.get("name"), "kind": "entity", "type": sub, "disamb": _disamb(r, sub)}


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
                    "disamb": _disamb(r, sub), "status": "ok" if ok else "needs_input", "is_place": sub == PLACE,
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
        # can quote"); a typed year or "movie"/"tv" decides, else a show beats a same-titled film (_rank_screen).
        # Other hints keep their one type.
        screen = "urn:entity:%s" % hint in SCREEN_TYPES
        types = ",".join(SCREEN_TYPES) if screen else "urn:entity:%s" % hint
        title, year, want = _screen_query(text) if screen else (text, None, None)

        def rank(rs):
            return _rank_screen(text, title, rs, year, want) if screen else _rank_entities(text, rs, ("urn:entity:%s" % hint,))

        res = q.search(title, types=types, take=10 if screen else 5, label="C2 love")
        if title != text:                       # "Scary Movie", "2001: A Space Odyssey": the typed text as well
            ids = {r["entity_id"] for r in res}
            res = res + [r for r in q.search(text, types=types, take=10, label="C2 love") if r["entity_id"] not in ids]
        ranked = rank(res)
        if (not ranked or ranked[0][1] < 0.95) and not M.fold(title).startswith("the "):
            ids = {r["entity_id"] for r in res}
            more = q.search("The " + title, types=types, take=10 if screen else 5, label="C2 love")
            ranked = rank(res + [r for r in more if r["entity_id"] not in ids])
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


# Delivery- or catering-only (29 Oct): one of these kinds and no sign you can eat there (dine in, table or bar
# service). The Flower Shop (NYC) is tagged delivery_restaurant AND dine in: it stays.
SHOP_SIGNS = {"shopping", "gift_items", "gourmet_condiments", "retail", "specialty_foods", "groceries",
              "grocery", "packaged_goods", "bulk_foods", "gourmet_foods", "specialty_food_store"}
SERVICE_ONLY_KINDS = ("delivery_restaurant", "meal_delivery", "food_delivery", "delivery_service", "caterer",
                      "catering", "catering_service", "catering_food_and_drink_supplier", "meal_takeaway")
DINE_IN_TAGS = ("urn:tag:service_options:place:dine_in", "urn:tag:service_type:qloo:dine_in",
                "urn:tag:dining_options:place:table_service", "urn:tag:service_type:qloo:bar_service",
                "urn:tag:dining_options:place:counter_service")


def excluded_kind(e):
    tags = [t for t in (e.get("tags") or []) if isinstance(t, dict)]
    facts = [_tag_facts(t) for t in tags]
    eatery = any(f[0] for f in facts)
    for t, f in zip(tags, facts):
        if f[5]:
            return t.get("id") or t.get("name")      # not a place to eat or drink, whatever else it is
    tids = [(t.get("id") or "").lower() for t in tags]
    # specialty food shops and grocers (30 Oct, QA: Pearlie's Pickles): a shop kind with no restaurant/bar kind, or
    # shop signs (shopping, gift items, gourmet condiments ...) with nothing that says you can eat or drink there
    kinds_ = [x.rsplit(":", 1)[-1] for x in tids if x.startswith("urn:tag:category:place:")]
    eat_kind = any(k in ("restaurant", "bar") or k in DRINK_KINDS or
                   (k[:-len("_restaurant")] if k.endswith("_restaurant") else k) in EAT_FAMILY for k in kinds_)
    shop_kind = next((k for k in kinds_ if re.search(r"store|market|grocer|specialty_food|butcher|"
                                                     r"pickle|spice|cheese_shop|candy|chocolate_shop", k)
                      and k not in ("coffee_store", "bubble_tea_store", "tea_store", "juice_store")), None)
    if shop_kind and not eat_kind:
        return "urn:tag:category:place:" + shop_kind
    shop_sign = next((x for x in tids if x.rsplit(":", 1)[-1] in SHOP_SIGNS), None)
    bar_kind = any(k in DRINK_KINDS for k in kinds_)
    if shop_sign and not bar_kind and not any(x in DINE_IN_TAGS for x in tids):
        return shop_sign
    svc = next((x for x in tids if x.startswith(("urn:tag:category:place:", "urn:tag:genre:place:restaurant:"))
                and x.rsplit(":", 1)[-1] in SERVICE_ONLY_KINDS), None)
    if svc and not any(x in DINE_IN_TAGS for x in tids):
        return svc                                    # delivery or catering only
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
def rescore(q, city, loves_all, ids, sig_love, label, workers=None, anchors=None, on_drift="flag"):
    """Affinity of every id under ONE love's signal (entity or tag), or no signal (sig_love None), with the same
    base filters. Chunks of 48 + 2 anchors; the anchors check that scores merge across chunks. Timeout 3 s.
    Drift (ANCHOR_DRIFT_MAX): a chunk where an anchor's affinity is more than ANCHOR_DRIFT_MAX from that anchor's
    median over the chunks drifted. on_drift="flag" keeps its scores and lists it; "drop" discards the chunk (its
    places count as missing). A chunk that returns neither anchor cannot be checked ("unverified")."""
    ids = sorted(ids)
    anchors = [a for a in (anchors or ids[:CFG["ANCHORS"]]) if a in ids][:CFG["ANCHORS"]]
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
    per_chunk = []                                   # (chunk no, {id: affinity}, {anchor: affinity})
    for n, (resp, err) in enumerate(out, 1):
        if isinstance(err, QlooDeadline):
            raise err
        if err is not None:
            failed += 1
            busy = busy or err.busy
            continue
        got, av = {}, {}
        for e in (resp.get("results") or {}).get("entities") or []:
            a = affinity(e)
            ents_by_id[e["entity_id"]] = e
            if e["entity_id"] in anchor_vals and a is not None:
                anchor_vals[e["entity_id"]].append(float(a))
                av[e["entity_id"]] = float(a)
            if a is not None:
                got[e["entity_id"]] = float(a)
        per_chunk.append((n, got, av))
    ref = {a: sorted(v)[len(v) // 2] for a, v in anchor_vals.items() if v}
    drift, drifted, unverified = 0.0, [], []
    for n, got, av in per_chunk:
        d = max([abs(v - ref[a]) for a, v in av.items()] or [0.0])
        drift = max(drift, d)
        if not av and len(per_chunk) > 1:
            unverified.append(n)
        if d > CFG["ANCHOR_DRIFT_MAX"]:
            drifted.append(n)
            if on_drift == "drop":
                got = {i: v for i, v in got.items() if i in anchor_vals}
        aff.update(got)
    missing = [i for i in ids if i not in aff]
    tied = [i for i in ids if i in aff and is_default_affinity(aff[i])]
    return {"aff": aff, "coverage": (len(ids) - len(missing)) / max(1, len(ids)), "missing": missing,
            "drift": drift, "drifted_chunks": drifted, "drift_ok": not drifted, "unverified_chunks": unverified,
            "calls": len(chunks), "failed": failed, "busy": busy, "tied": tied,
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
# C7 name map (30 Oct, engine/build_namemap.py): every wall name's city-scoped /search result, stored once per city;
# data/namemap/<city>.json, UNSAID_NAMEMAP_DIR, or namemap-<city>.json beside the priors (Render secret files).
# Used only when its stored parameters equal the engine's own.
_NAMEMAP = {}


def load_namemap(city_key, params):
    if not city_key or not CFG.get("NAMEMAP_ENABLED", True):
        return {}
    cands = []
    if os.environ.get("UNSAID_NAMEMAP_DIR"):
        cands += [os.path.join(os.environ["UNSAID_NAMEMAP_DIR"], n) for n in ("%s.json", "namemap-%s.json")]
    cands += [os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data",
                           "namemap", "%s.json"), os.path.join(CFG["PRIORS_DIR"], "namemap-%s.json")]
    for c in cands:
        fp = c % city_key
        if not os.path.exists(fp):
            continue
        mt = os.path.getmtime(fp)
        hit = _NAMEMAP.get(city_key)
        if hit and hit[0] == (fp, mt):
            return hit[1]
        try:
            with open(fp) as f:
                doc = json.load(f)
        except (OSError, ValueError):
            continue
        names = doc.get("names") or {} if doc.get("params") == params else {}
        _NAMEMAP[city_key] = ((fp, mt), names)
        return names
    return {}


class CitySearch:
    """search_fn for the matcher. Calls /search (city-scoped: lat,lon + 15 mi) only for names that share a
    distinctive token with U; others are 'not in pool' with no call (E6). A busy Qloo is recorded, never 'not found'."""

    def __init__(self, q, city, U):
        self.q, self.city = q, city
        self.u_tokens = set()
        for e in U:
            self.u_tokens.update(M.distinctive(e.get("name", "")))
        self.skipped, self.busy, self.closed, self.calls, self.mapped = set(), set(), set(), 0, 0
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
        nm = load_namemap(self.city.get("key"), {"types": PLACE, "take": 5, "location": "%s,%s" % (lat, lon),
                                                   "radius_mi": CFG["SEARCH_RADIUS_MI"]})
        if raw in nm:                      # resolved once per city (build_namemap.py): the same /search result
            with self.lock:
                self.mapped += 1
            return nm[raw]
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
        if len(_NRB) > 20000:
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


# The reverse check's evidence rules (30 Oct, E's held-out audit: 7 of 8 "hits" were prose words: "pm", "September",
# "Cardinals Nation", "Flor de Mayo", "rooftop", "Harlem" + "breakfast" apart).
REV_FIXED_STOP = set("""
january february march april may june july august september october november december jan feb mar apr jun jul aug
sep sept oct nov dec monday tuesday wednesday thursday friday saturday sunday mon tue tues wed thu thur thurs fri sat
sun am pm noon midnight morning mornings afternoon afternoons evening evenings night nights tonight today tomorrow
weekend weekends weekday weekdays daily hour hours late early open opens closed minute minutes
""".split())
REV_WINDOW_EXTRA = 1          # the informative tokens may sit one word further apart than their own count
REV_STOP_DF = 0.005           # a non-name token in >= 0.5% of the wall's answers is not evidence of a place


_ATOK = {}            # (29 Oct, memory + CPU) sha1(answer) -> its tokens and non-name tokens, interned; bounded
_ATOK_MAX = 6000      # ~2 cities' walls; each set's wall is the city's answers plus a few of its own


def _answer_toks(a):
    """(token list, set of the tokens left once every place the answer names is removed), once per distinct answer
    across runs: the walls' texts are kilobytes and every set's wall repeats its city's answers."""
    text = answer_text(a)
    names = [nm.get("name") if isinstance(nm, dict) else nm for nm in a.get("names") or a.get("places") or []]
    k = hashlib.sha1((text + "\x00" + "\x00".join(n for n in names if n)).encode("utf-8", "replace")).digest()
    got = _ATOK.get(k)
    if got is None:
        if len(_ATOK) >= _ATOK_MAX:
            _ATOK.clear()
        rest = M.fold(text)
        for nm in names:
            if nm:
                rest = rest.replace(M.fold(nm), " ")
        got = (tuple(sys.intern(t) for t in M.tokens(text)), frozenset(sys.intern(t) for t in M.tokens(rest)))
        _ATOK[k] = got
    return got


def derive_rev_stop(answers):
    """The walls' most frequent NON-name tokens (neighbourhoods, list keys, prose): each answer's text with every
    place it names removed, counted once per answer."""
    df, n = {}, 0
    for a in answers:
        n += 1
        for t in _answer_toks(a)[1]:
            df[t] = df.get(t, 0) + 1
    cut = max(2, int(REV_STOP_DF * n))
    return {t for t, c in df.items() if c >= cut}


class _RIndex(list):
    """[(i, tokens)] plus a token -> answers index, so each distinct answer token is compared once, not per answer.
    Also each answer's token sequence (for the window rule) and the evidence stoplist."""

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


_RCACHE = []        # [(content key, index)], most recent last: the dated wall's reverse index, built once per wall
_RCACHE_MAX = 2     # (29 Oct, Render 512 MB) one per city/set wall in use; the old identity key added one per run
_REV_STOP = {"stop": set()}   # the latest wall-derived stoplist; small indexes (street, live) reuse it


def _answers_key(answers):
    """A stable content key for a list of answers (each run loads new objects, so identity never repeats)."""
    h = hashlib.sha1()
    for a in answers:
        h.update(answer_text(a).encode("utf-8", "replace"))
        h.update(b"\x00")
    return h.hexdigest()


def reverse_index_cached(answers):
    key = _answers_key(answers)
    for k, (kk, ri) in enumerate(_RCACHE):
        if kk == key:
            _RCACHE.append(_RCACHE.pop(k))
            _REV_STOP["stop"] = ri.stop
            return ri
    ri = reverse_index(answers, derive=True)
    _RCACHE.append((key, ri))
    del _RCACHE[:-_RCACHE_MAX]
    return ri


def reverse_index(answers, derive=False, stop=None):
    """derive=True: the stoplist comes from these answers (a wall); else the given one or the latest wall's."""
    toks = [_answer_toks(a)[0] for a in answers]
    ri = _RIndex((i, _Toks(t)) for i, t in enumerate(toks))
    ri.seq = {i: list(t) for i, t in enumerate(toks)}
    ri.raw = {i: answer_text(a) for i, a in enumerate(answers)}
    ri.names = {i: [n.get("name") if isinstance(n, dict) else n for n in (a.get("names") or a.get("places") or [])]
                for i, a in enumerate(answers)}
    if stop is not None:
        ri.stop = set(stop)
    elif derive:
        ri.stop = derive_rev_stop(answers)
        _REV_STOP["stop"] = ri.stop
    else:
        ri.stop = set(_REV_STOP["stop"])
    ri.stop |= REV_FIXED_STOP
    return ri


def _tok_in(t, toks):
    if t in toks:
        return True
    if isinstance(toks, _Toks):
        b = toks.by_len()
        return any(M.tok_eq(t, x) for n in range(len(t) - 3, len(t) + 4) for x in b.get(n, ()))
    return any(M.tok_eq(t, x) for x in toks if abs(len(x) - len(t)) <= 3)


def _window_ok(seq, toks, extra=REV_WINDOW_EXTRA):
    """Every token of `toks` (exact or tok_eq) inside one span of len(toks) + extra consecutive words of `seq`."""
    pos = []
    for t in toks:
        p = [k for k, w in enumerate(seq) if w == t or (abs(len(w) - len(t)) <= 3 and M.tok_eq(t, w))]
        if not p:
            return False
        pos.append(p)
    span = len(toks) + extra
    for start in pos[0]:
        lo, hi = start - span + 1, start + span - 1
        if all(any(lo <= q <= hi for q in p) for p in pos[1:]):
            chosen = [start] + [min((q for q in p if lo <= q <= hi), key=lambda q: abs(q - start)) for p in pos[1:]]
            if max(chosen) - min(chosen) < span:
                return True
    return False


def _standalone(name, i, rindex):
    """The place stands as a name in answer i: an entry of its list (R1 keys), its full multi-word name contiguous in
    the text, or its exact display name (case and punctuation kept) as a whole word or phrase."""
    keys = M.keys(name)
    if any(n and M._key_match(keys, M.keys(n)) for n in rindex.names.get(i) or []):
        return True
    full = M.tokens(name)
    seq = rindex.seq.get(i) or []
    if len(full) >= 2 and any(seq[k:k + len(full)] == full for k in range(len(seq) - len(full) + 1)):
        return True
    disp = display_name(name).strip()
    if disp and re.search(r"(?<![\w:])%s(?![\w:])" % re.escape(disp), rindex.raw.get(i) or ""):
        return True
    return False


def reverse_hit(name, rindex):
    """Fuzzy, local, 0 calls: a stored answer names the card although the strike missed it. Evidence: two or more
    informative tokens of the name (not stoplisted) within a short window of one answer; a name with fewer must
    stand as a name (see _standalone)."""
    d = M.distinctive(name or "")
    if not d:
        return None
    if not isinstance(rindex, _RIndex):
        rindex = reverse_index([{"raw": " ".join(sorted(toks))} for _, toks in rindex])
    inf = [t for t in d if t not in rindex.stop]
    order = {i: k for k, (i, _) in enumerate(rindex)}
    if len(inf) >= 2:
        common = None
        for t in inf:
            a = rindex.answers_for(t)
            common = set(a) if common is None else common & a
            if not common:
                break
        for i in sorted(common or (), key=order.get):
            if _window_ok(rindex.seq[i], inf):
                return i
    probe = inf or d                              # candidate answers, then the standalone test
    cands = None
    for t in probe[:1]:
        cands = rindex.answers_for(t)
    for i in sorted(cands or (), key=order.get):
        if _standalone(name, i, rindex):
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
               "live performances", "dj", "drag", "line dancing", "dancing", "dance floor", "trivia",
               "sports viewing", "billiards", "pool table", "darts")       # (b), in this order of preference
# How you get served, not what the place is (judge 3, 29 Oct): never on a card's what line or because line
WHAT_SERVICE = {"delivery", "delivery restaurant", "delivery service", "food delivery", "meal delivery",
                "no contact delivery", "takeout", "take out", "takeaway", "meal takeaway", "takeout service",
                "curbside pickup", "drive thru", "drive through", "dine in", "catering", "caterer",
                "catering service", "reservations", "walk ins", "happy hour", "happy hour drinks",
                "happy hour food", "onsite services", "online ordering", "order online", "table service",
                "bar service", "counter service", "outdoor seating", "shared use commercial kitchen",
                "ok to order just drinks", "food at bar", "late night food", "quick bite"}
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
        if lab in WHAT_SERVICE or raw in WHAT_SERVICE:
            continue
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


# ---------------------------------------------------------------- chains
_BRANCH_SEG = {"location", "locations", "store", "stores"}
_CITY_SEG = {"st-louis", "saint-louis", "stl", "new-york", "new-york-city", "nyc"}


def _site(e):
    """(domain without www., path segments) of a place's own website (Qloo's website property)."""
    w = (prop(e, "website") or "").strip().lower()
    if not w:
        return "", []
    m = re.match(r"^(?:[a-z]+://)?([^/?#]+)([^?#]*)", w)
    if not m:
        return "", []
    return re.sub(r"^www\.", "", m.group(1)), [x for x in m.group(2).split("/") if x]


def chain_ids(pool, ids):
    """Places run by a multi-location brand (29 Oct), from Qloo's own website field, no extra calls:
      a branch page: the website is a location/store page of a brand site (".../locations/brentwood-square/",
        "locations.bonefishgrill.com/missouri/brentwood/...",
        ".../location/nomad/") or the brand site's page for this city ("rushbowls.com/st-louis");
      or one domain, one brand: >= 3 places in the pool share the website's domain and the name's first word
        (First Watch x4 on firstwatch.com). Social and ordering sites never count: their names differ.
    Local groups with branch pages (Boqueria) go too: a card is a place, not a brand."""
    site = {e["entity_id"]: _site(e) for e in pool}
    first = {e["entity_id"]: (M.distinctive(e.get("name") or "") or [""])[0] for e in pool}
    brand = collections.Counter((site[i][0], first[i]) for i in site if site[i][0] and first[i])
    out = set()
    for i in ids:
        d, segs = site.get(i, ("", []))
        if not d:
            continue
        if d.split(".")[0] in _BRANCH_SEG or any(x in _BRANCH_SEG for x in segs[:-1]) or \
                (len(segs) == 1 and segs[0] in _CITY_SEG) or \
                brand[(d, first.get(i))] >= 3:
            out.add(i)
    return out


DISH_SYNONYMS = {"barbecue": ["barbecue", "bbq", "barbeque", "bar-b-q", "smokehouse"],
                 "bbq": ["barbecue", "bbq", "barbeque", "bar-b-q", "smokehouse"],
                 "steak": ["steak", "steaks", "steakhouse", "ribeye", "porterhouse", "filet mignon", "strip steak"],
                 "tacos": ["taco", "tacos", "taqueria"], "taco": ["taco", "tacos", "taqueria"],
                 "sushi": ["sushi", "omakase", "nigiri", "sashimi"],
                 "pizza": ["pizza", "pizzas", "pizzeria"]}


def dish_in_text(e, dish):
    """The dish (singular or plural, without its cooking style, or a cuisine love's own words) appears in the
    place's own Qloo text: name, specialty dishes, keywords, cuisine description, selling points, short
    description. No mention, no credit."""
    p = e.get("properties") or {}
    parts = [e.get("name") or "", p.get("cuisine_description") or "", p.get("unique_selling_points") or "",
             p.get("short_description") or ""]
    parts += [(d.get("name") if isinstance(d, dict) else str(d)) for d in p.get("specialty_dishes") or []]
    parts += [(k.get("name") if isinstance(k, dict) else str(k)) for k in p.get("keywords") or []]
    text = " %s " % M.norm(" | ".join(x for x in parts if x))
    nm = M.norm(dish)
    head = " ".join(w for w in nm.split() if w not in DISH_STYLE)
    forms = set()
    for x in {nm, head} - {""}:
        forms |= {x, x + "s", x + "es", x[:-1] if x.endswith("s") else x, x[:-2] if x.endswith("es") else x}
        forms |= set(M.norm(y) for y in DISH_SYNONYMS.get(x, []))
    return any(f and (" %s " % f) in text for f in forms)


DISH_STYLE = set("""fried deep-fried grilled smoked bbq barbecued baked roasted crispy spicy hot pan-fried pan seared
braised steamed blackened jerk sweet sour""".split())

# ---------------------------------------------------------------- kinds (variety in the seven)
DRINK_KINDS = {"bar", "cocktail_bar", "wine_bar", "bar_grill", "sports_bar", "pub", "lounge_bar", "irish_pub",
               "gastropub", "brewery", "live_music_bar", "night_club", "jazz_club", "beer_garden", "brewpub",
               "dance_club", "beer_hall", "gay_bar", "karaoke_bar", "dive_bar", "comedy_club", "beer_bar",
               "lounge", "tavern", "piano_bar", "whiskey_bar", "sake_bar", "hookah_bar", "taproom"}
EAT_FAMILY = {
    "barbecue": "barbecue", "korean_barbecue": "barbecue", "smokehouse": "barbecue",
    "soul_food": "southern", "southern_restaurant_us": "southern", "southern": "southern", "cajun": "southern",
    "creole": "southern", "chicken": "southern", "chicken_wings": "southern", "fried_chicken": "southern",
    "italian": "italian", "pizza": "italian", "pizzeria": "italian",
    "mexican": "latin", "taco": "latin", "burrito": "latin", "latin_american": "latin", "colombian": "latin",
    "caribbean": "latin", "brazilian": "latin", "peruvian": "latin", "honduran": "latin", "salvadoran": "latin",
    "spanish": "spanish", "tapas": "spanish", "tapas_bar": "spanish", "basque": "spanish",
    "japanese": "asian", "sushi": "asian", "ramen": "asian", "korean": "asian", "chinese": "asian",
    "sichuan": "asian", "thai": "asian", "vietnamese": "asian", "asian": "asian", "asian_fusion": "asian",
    "dim_sum": "asian", "indian": "asian", "filipino": "asian",
    "seafood": "seafood", "oyster_bar": "seafood", "fish_and_chips": "seafood",
    "steak_house": "steak", "steakhouse": "steak",
    "hamburger": "diner", "diner": "diner", "sandwich_shop": "diner", "deli": "diner", "hot_dog": "diner",
    "mediterranean": "mediterranean", "middle_eastern": "mediterranean", "greek": "mediterranean",
    "lebanese": "mediterranean", "falafel": "mediterranean", "turkish": "mediterranean",
    "french": "european", "modern_french": "european", "bistro": "european", "european": "european",
    "irish": "european", "german": "european", "eastern_european": "european", "polish": "european",
    "russian": "european", "ukrainian": "european",
    "cafe": "cafe", "coffee_shop": "cafe", "bakery": "cafe", "espresso_bar": "cafe", "ice_cream_shop": "cafe",
    "dessert": "cafe", "dessert_shop": "cafe", "pancake": "cafe", "tea_house": "cafe", "juice_shop": "cafe",
    "bubble_tea": "cafe", "breakfast": "cafe", "brunch": "cafe", "coffee_roastery": "cafe", "donut_shop": "cafe",
    "vegan": "healthy", "vegetarian": "healthy", "health_food": "healthy", "gluten_free": "healthy",
    "ethiopian": "african", "african": "african", "west_african": "african", "nigerian": "african"}


def kind_of(e):
    """("eat", family) or ("drink", "drink") from the place's Qloo category / restaurant-genre tags: a specific
    cuisine kind ("barbecue_restaurant", "italian") makes it a place to eat of that family; else any bar-type kind
    (bar, pub, lounge, cocktail bar, bar & grill ...) makes it a place to drink; else a place to eat."""
    kinds = []
    for t in e.get("tags") or []:
        tid = (t.get("id") or "") if isinstance(t, dict) else ""
        for pre in ("urn:tag:category:place:", "urn:tag:genre:place:restaurant:"):
            if tid.startswith(pre):
                k = tid[len(pre):]
                kinds.append(k[:-len("_restaurant")] if k.endswith("_restaurant") else k)
    fams = [EAT_FAMILY[k] for k in kinds if k in EAT_FAMILY]
    if fams:                                  # a cuisine before a cafe, a cafe before a diet tag (vegan, healthy)
        return ("eat", min(fams, key=lambda f: (f == "healthy", f == "cafe", fams.index(f))))
    if any(k in DRINK_KINDS for k in kinds):
        return ("drink", "drink")
    return ("eat", "other")


# ---------------------------------------------------------------- card lines
_CUT_POSSESSIVE = re.compile(r"(?<=[^\W\dsS_])['\u2019]$")


def display_name(name):
    """'Space Ping Pong Sports Bar & Lounge | Koreatown NYC' -> 'Space Ping Pong Sports Bar & Lounge'.
    Qloo cuts some possessives ('Jody B\'' for Jody B's, whose own descriptions say "Jody B's"): a name ending in an
    apostrophe after a letter other than s gets its s back; a plural possessive ("The Brothers'") is left alone."""
    out = (name or "").split(" | ")[0].strip() or name
    if out and _CUT_POSSESSIVE.search(out):
        out += "s"
    return out


CENTER_LABEL = {"stl": "downtown", "nyc": "Central Park", "la": "downtown"}   # cities.py centers, in words
CITY_TZ = {"stl": "America/Chicago", "nyc": "America/New_York", "la": "America/Los_Angeles"}

# ---- rich card fields (29 Oct): straight from the insights responses the engine already holds, 0 extra calls
ORDER_STOP = set("""atmosphere crowd security party night owner owners home feel prices price seating patio dining food
friendly staff service vibe vibes music dj drinks drink bar bartender bartenders place spot location parking wait
line lines music dancing dance karaoke tv tvs game games sports event events experience people family friends area
neighborhood wall walls decor ambiance ambience view views time times hour hours happy hour menu portions portion
value quality customer customers environment energy fun good great nice clean cozy space room inside outside
outdoor indoor table tables booth booths floor stage band bands live entertainment respect cowboys birthday weekend
weekends lunch dinner breakfast brunch late night specials special deals deal cash card owner's server servers
manager pool billiards darts trivia jukebox smoke smoking cigar cigars hookah""".split())
ORDER_VENUE = set("""bar bars pub pubs lounge lounges tavern taverns restaurant restaurants cafe cafes grill grille diner
club clubs brewery breweries taproom saloon bistro eatery joint spot spots shop shops house hall garden rooftop""".split())
_ABBREV = set("st dr ave mt mr mrs ms jr sr blvd rd ln hwy ft no vs etc inc ltd co corp n s e w".split())
_ORDER_KINDS = ("urn:tag:menu_highlight:", "urn:tag:specialty_dish:", "urn:tag:cuisine:", "urn:tag:beverage_offering:",
                "urn:tag:offerings:")


def _sing_word(w):
    return w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w


def dish_vocab(U):
    """The city pool's own dish and drink words: names of its menu_highlight / specialty_dish / cuisine / beverage
    tags (and their singular forms), so a keyword counts as something to order only when Qloo knows it as food."""
    v = set()
    for e in U:
        for t in e.get("tags") or []:
            if isinstance(t, dict) and (t.get("id") or "").startswith(_ORDER_KINDS) and t.get("name"):
                n = t["name"].strip().lower()
                if n in WHAT_SERVICE or n in WHAT_BLAND:
                    continue
                v.add(n)
                v.add(" ".join(_sing_word(w) for w in n.split()))
    return v


ORDER_GENERIC = set("""beer beers wine wines cocktail cocktails hard liquor liquor alcohol spirits drinks drink beverages
beverage coffee tea soda food dishes dish options option fare bites plates sides side items menu entrees entree
appetizers appetizer desserts dessert snacks snack comfort food bar food pub food american soul food meals meal
sandwiches sandwich seafood salads salad small plates classic classics sauce sauces soups soup stews stew deli healthy
organic vegan vegetarian gluten-free halal kosher german italian japanese korean mexican chinese thai indian french
greek spanish american southern cajun creole caribbean brazilian colombian ethiopian vietnamese mediterranean
middle-eastern fusion local seasonal beef chicken turkey pork fish rib meat meats""".split()) | {
    "specialty cocktails", "signature cocktails", "juice bar special", "daily specials",
    "bar food", "comfort food", "soul food", "hard liquor", "small plates", "pub food", "pub fare", "bar fare",
    "mixed drinks", "craft cocktails", "craft cocktail", "craft beer", "craft beers", "draft beer", "draft beers",
    "local beer", "local beers", "natural wine", "natural wines", "street food", "street foods", "simple meals",
    "breakfast classics", "korean comfort food", "seasonal dessert", "american classics", "bar bites", "bar snacks"}
_LEAD_WORDS = {"and", "or", "a", "an", "the", "our", "their", "its", "with", "of", "s"}
_LIST_CUE = re.compile(r"\b(?:like|such as|including|includes|include|featuring|features|feature|signature)\s+([^.;:]+)",
                       re.I)
_LIST_END = re.compile(r"\s+(?:alongside|along with|as well as|complemented by|paired with|plus|served|that|which|"
                       r"in a|in an|for)\b.*$", re.I)


def _dishes_in(text, vocab):
    """Dish or drink names in a description's lists ("items like tender rib tips, pork steaks and honey hot wings"):
    each item's longest run of words the pool's dish vocabulary knows, generic words (beer, cocktails, food) never."""
    out = []
    for m in _LIST_CUE.finditer(text or ""):
        seg = _LIST_END.sub("", m.group(1))
        for item in re.split(r",\s*(?:and\s+|or\s+)?|\s+and\s+|\s+or\s+|\s*&\s*", seg):
            words = re.findall(r"[a-z][a-z'-]*", item.lower())
            best = None
            for size in range(min(4, len(words)), 0, -1):
                for k in range(len(words) - size + 1):
                    g = words[k:k + size]
                    ph = " ".join(g)
                    if ph in ORDER_GENERIC or g[-1] in ORDER_VENUE or g[0] in _LEAD_WORDS or g[-1] in _LEAD_WORDS \
                            or all(w in ORDER_STOP for w in g):
                        continue
                    if ph in vocab or " ".join(_sing_word(w) for w in g) in vocab:
                        best = ph
                        break
                if best:
                    break
            if best and best not in out:
                out.append(best)
    return out


def _clean_item(nm):
    """One order item: lower-case, a leading "and"/"an"/"the" dropped, never generic, never a long menu line."""
    w = nm.strip().lower().split()
    while w and w[0] in ("and", "or", "an", "a", "the", "&"):
        w = w[1:]
    nm = " ".join(w)
    return nm if nm and nm not in ORDER_GENERIC and len(nm) <= 32 else None


def order_line(e, vocab, n=3):
    """Up to n things people order, in this order until there are n: Qloo's specialty_dishes; dish names in the
    lists of its unique_selling_points and cuisine_description (multi-word names first);
    else its review keywords that are food or drink (in the pool's dish vocabulary, never a stoplist word or a
    generic drink). [] when nothing real is left."""
    out = []
    for d in prop(e, "specialty_dishes") or []:
        nm = (d.get("name") if isinstance(d, dict) else str(d) if d else "") or ""
        nm = _clean_item(nm)
        if nm and nm not in out:
            out.append(nm)
    if len(out) < n:  # the lists in Qloo's own descriptions (its selling points first), the most specific names first
        found = _dishes_in(prop(e, "unique_selling_points"), vocab)
        found += [x for x in _dishes_in(prop(e, "cuisine_description"), vocab) if x not in found]
        out += [x for x in sorted(found, key=lambda x: (" " not in x, found.index(x))) if x not in out]
    if len(out) < n:  # then review keywords that are food or drink
        for k in prop(e, "keywords") or []:
            nm = ((k.get("name") if isinstance(k, dict) else str(k)) or "").strip().lower()
            words = nm.split()
            if not words or nm in ORDER_STOP or all(w in ORDER_STOP for w in words):
                continue
            if words[-1] in ORDER_VENUE or nm in ORDER_GENERIC or words[0] in _LEAD_WORDS:
                continue                  # "dive bar", "cocktail bar": what the place is, not what you order
            if nm in vocab or " ".join(_sing_word(w) for w in words) in vocab:
                if nm not in out:
                    out.append(nm)
    keep, seen = [], set()
    for x in out:                       # "tartine" == "tartines"
        k = " ".join(_sing_word(w) for w in x.split())
        if k not in seen:
            seen.add(k)
            keep.append(x)
    return keep[:n]


# Boilerplate openers of Qloo's unique_selling_points, stripped so the sentence starts with what is special
# ("The establishment is distinguished by its signature X" -> "Signature X"). Openers that already read well
# ("Famous for their tender, smoky rib tips", "Housed in a beautiful historic Victorian home") stay.
_USP_SUBJ = (r"(?:the|this)\s+(?:[\w-]+\s+){0,2}?(?:restaurant|establishment|spot|venue|cafe|café|bar|lounge|"
             r"steakhouse|staple|eatery|tavern|pub|place|business|diner|bistro|kitchen|menu|location|joint)|it|they")
_USP_VERB = (r"(?:is\s+|are\s+)?(?:(?:widely\s+|highly\s+|best\s+|especially\s+)?(?:distinguished|defined|celebrated|"
             r"known|regarded|recognized|recognised|renowned|praised|noted|notable|anchored|set\s+apart)|"
             r"well-regarded|stands?\s+out|distinguishes\s+itself|sets\s+itself\s+apart|features|boasts|offers)")
_USP_OPENER = re.compile(r"^(?:%s)\s+%s\s*(?:primarily\s+|mainly\s+|most\s+)?(?:by|for|as|through|with|"
                         r"in)?\s*(?:its|their|an|a|the\s+fact\s+that)?\s+" % (_USP_SUBJ, _USP_VERB), re.I)
_USP_LEAD = re.compile(r"^(?:known\s+as|distinguished\s+by|recognized\s+as)\s+(?:its\s+|their\s+)?", re.I)


def _first_sentence(d):
    for m in re.finditer(r"[.!?](?=\s|$)", d):      # the first full stop that is not "St." / "Dr." / "N."
        word = re.findall(r"[A-Za-z]+$", d[:m.start()])
        if word and (word[0].lower() in _ABBREV or len(word[0]) == 1):
            continue
        return d[:m.end()]
    return d


FALLBACK_WORDS = 12
# Where a sentence's first complete clause ends: ";", a spaced dash, or a comma before a subordinate/participle lead
_CLAUSE_END = re.compile(r"\s*(?:;|\s[—–-]\s|,\s+(?:where|which|while|whose|with|offering|featuring|serving|making|"
                         r"alongside|thanks\s+to|earning|creating|providing|giving|combining|blending|set\s+in|"
                         r"located|housed|situated|but|as\s+well\s+as|plus|including|complemented|drawing|"
                         r"attracting|catering|and\s+its|and\s+their|and\s+it|and\s+is)\b)", re.I)
# Ownership identity never opens a card line (juror, 30 Oct); build_lines.IDENTITY is the same pattern
_IDENTITY_HEAD = re.compile(r"(?:[\w+]+-(?:owned|run|operated)\b|\b(?:owned|run|operated)\s+by\b|\blgbtq|\blgbt\b|"
                            r"\bqueer\b|\bgay\b|\blesbian\b|\bblack[- ]owned|\bfamily[- ](?:owned|run)\b)", re.I)
_BOILERPLATE = re.compile(r"^(?:the|this|it)\s+(?:establishment|location|venue|restaurant|bar|place|spot|business|"
                          r"cafe|café)?\b|\bestablishment\b", re.I)   # an opener the USP strip left in: say the kind
_HOOD_THE_LAST = {"district", "side", "end", "bowery"}
_HOOD_THE_DIR = ({"east", "west", "north", "south"}, {"village", "bronx", "slope"})


ORDER_NONFOOD = set("""jazz music live dj karaoke dancing dance trivia arcade games game pool darts billiards options
option healthy vibe vibes atmosphere service staff patio view views seating crowd party night nightlife happy hour
specials deals entertainment comedy""".split())
_ORDER_LEAD = ("for ", "with ", "a ", "an ", "the ", "of ", "in ", "on ", "at ", "to ", "and ", "or ", "&")


def clean_order(items, e, vocab, n=3):
    """The card's "people order" list, whatever its source (30 Oct, QA): apostrophe splits mended ("bernie s" ->
    "bernie's"); never an item that starts with a preposition or article ("for ramen"), never a non-food word
    (jazz, arcade games, healthy options); an item another, more specific item contains goes ("cheesecake" beside
    "matcha cheesecake"); items of the place's own cuisine first; at most n. Empty beats junk."""
    cuisine = set()
    for t in e.get("tags") or []:
        if isinstance(t, dict) and (t.get("id") or "").startswith(("urn:tag:cuisine:", "urn:tag:category:place:",
                                                                   "urn:tag:genre:place:restaurant:")):
            cuisine.update(w for w in M.norm(_what_label(t)).split() if len(w) > 3)
    out = []
    for x in items or []:
        x = re.sub(r"\b(\w+) s\b", r"\1's", (x or "").strip())
        lx = x.lower()
        if not x or lx.startswith(_ORDER_LEAD) or len(x) > 40:
            continue
        ws = re.findall(r"[a-z]+", lx)
        if not ws or any(w in ORDER_NONFOOD for w in ws) or lx in ORDER_GENERIC:
            continue
        out.append(x)
    keep = [x for x in out if not any(y != x and len(y) > len(x) and
                                      re.search(r"(?<![a-z])%s(?![a-z])" % re.escape(x.lower()), y.lower())
                                      for y in out)]
    seen, uniq = set(), []
    for x in keep:
        k = " ".join(_sing_word(w) for w in x.lower().split())
        if k not in seen:
            seen.add(k)
            uniq.append(x)
    pos = {x: k for k, x in enumerate(uniq)}
    uniq.sort(key=lambda x: (not any(w in cuisine for w in M.norm(x).split()), pos[x]))
    return uniq[:n]


def _first_clause(d):
    """d's first sentence when it is <= FALLBACK_WORDS words, else its first complete clause (up to ';', a spaced
    dash, or ', where / which / with / offering ...') when that is 4..FALLBACK_WORDS words; else None. Never cut
    mid-thought."""
    s = _first_sentence(d).strip()
    n = len(s.split())
    if n <= FALLBACK_WORDS:
        return s if n >= 3 else None
    m = _CLAUSE_END.search(s)
    if not m:
        return None
    head = s[:m.start()].rstrip(" ,;:")
    if not 4 <= len(head.split()) <= FALLBACK_WORDS or head.count("(") != head.count(")") or head.count('"') % 2:
        return None
    return head


def _hood_phrase(h):
    """'East Village' -> 'the East Village', 'Financial District' -> 'the Financial District', 'SoHo' -> 'SoHo'."""
    ws = h.split()
    if not ws or ws[0].lower() == "the":
        return h
    first, last = ws[0].lower(), ws[-1].lower()
    if last in _HOOD_THE_LAST or (len(ws) > 1 and first in _HOOD_THE_DIR[0] and last in _HOOD_THE_DIR[1]) \
            or h.lower() in ("bronx", "bowery"):
        return "the " + h
    return h


def kind_in_hood(e, hood=None):
    """'<cuisine or kind> in <neighbourhood>' from Qloo's tags ("Japanese restaurant in the East Village"): a specific
    category tag, else a restaurant genre or cuisine tag + 'restaurant', else 'Bar' / 'Restaurant'; the area is the
    card's (hood) or Qloo's neighborhood property. None when the place has no kind tag."""
    spec, bland = [], []
    for t in e.get("tags") or []:
        if not isinstance(t, dict) or not t.get("name"):
            continue
        tid = (t.get("id") or "").lower()
        lab = _what_label(t)
        if lab in WHAT_SERVICE or (t.get("name") or "").strip().lower() in WHAT_SERVICE or lab in ("place", "food"):
            continue
        name = re.sub(r"\s+us$", "", t["name"].strip(), flags=re.I).replace(" + ", " & ")
        if tid.startswith("urn:tag:category:place:"):
            tier = 0
        elif tid.startswith(("urn:tag:genre:place:restaurant:", "urn:tag:cuisine:")):
            tier = 1
            if not re.search(r"\b(?:restaurant|bar|pub|cafe|café|shop|house|diner|bakery|grill|steakhouse|lounge|"
                             r"tavern|brewery|bistro|deli|pizzeria|taqueria|joint|hall|club)$", name, re.I):
                name += " restaurant"
        else:
            continue
        pref = next((k for k, w in enumerate(WHAT_CUISINE_FIRST) if w == lab), len(WHAT_CUISINE_FIRST))
        named = 0 if re.search(r"\b%s\b" % re.escape(lab), (e.get("name") or "").lower()) else 1   # "LongHorn Steakhouse"
        (bland if lab in WHAT_BLAND else spec).append((named, tier, pref, len(spec) + len(bland), name))
    pick = min(spec or bland or [None], key=lambda x: x or ())
    if not pick:
        return None
    kind = pick[-1][:1].upper() + pick[-1][1:]
    hood = (hood or prop(e, "neighborhood") or "").strip()
    return "%s in %s" % (kind, _hood_phrase(hood)) if hood else kind


def blurb_line(e, hood=None):
    """The rules line when Claude has no checked line (30 Oct: never truncated, never '…'): Qloo's own words, the
    first sentence of unique_selling_points (boilerplate opener stripped, first letter capitalised) when it is <= 12
    words, else its first complete clause of <= 12 words; then the same for short_description; else
    kind_in_hood ("Japanese restaurant in the East Village"). A candidate that opens with ownership identity
    ("Black-owned ...") is skipped."""
    cands = []
    usp = (prop(e, "unique_selling_points") or "").strip()
    if usp:
        d = _first_sentence(usp)
        t = _USP_OPENER.sub("", d, count=1)
        t = _USP_LEAD.sub("", t, count=1) if t == d else t
        t = re.sub(r"^being\s+", "", t, flags=re.I) if t != d else t     # "... by being a rare dive bar" -> "A rare ..."
        cands.append(t[:1].upper() + t[1:] if len(t) >= 25 else d)
    sd = (prop(e, "short_description") or "").strip()
    if sd:
        cands.append(sd)
    for d in cands:
        c = _first_clause(d)
        if c and not _IDENTITY_HEAD.search(" ".join(c.split()[:3])) and not _BOILERPLATE.search(c):
            if c.endswith(".") and not re.search(r"(?:\b(?:%s)|\b[A-Za-z])\.$" % "|".join(_ABBREV), c, re.I):
                c = c[:-1]                                       # no full stop, like the Claude lines ("St." stays)
            return c[:1].upper() + c[1:]
    return kind_in_hood(e, hood)


# Card lines condensed by Claude from Qloo's own text (engine/build_lines.py, checked word for word against the
# source): data/lines/<city>.json, UNSAID_LINES_DIR, or lines-<city>.json beside the priors (Render secret files).
_LINES = {}


def load_lines(city_key):
    cands = []
    if os.environ.get("UNSAID_LINES_DIR"):
        cands += [os.path.join(os.environ["UNSAID_LINES_DIR"], n) for n in ("%s.json", "lines-%s.json")]
    cands += [os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data",
                           "lines", "%s.json"), os.path.join(CFG["PRIORS_DIR"], "lines-%s.json")]
    for c in cands:
        fp = c % city_key
        if os.path.exists(fp):
            mt = os.path.getmtime(fp)
            hit = _LINES.get(city_key)
            if hit and hit[0] == (fp, mt):
                return hit[1]
            try:
                with open(fp) as f:
                    lines = json.load(f).get("lines") or {}
            except (OSError, ValueError):
                continue
            _LINES[city_key] = ((fp, mt), lines)
            return lines
    return {}


def image_url(e):
    im = prop(e, "image")
    if isinstance(im, dict) and im.get("url"):
        return im["url"]
    for x in prop(e, "images") or []:
        if isinstance(x, dict) and x.get("url"):
            return x["url"]
    return None


def price_line(e):
    p = prop(e, "price_level")
    return "$" * int(p) if isinstance(p, (int, float)) and 1 <= p <= 4 else None
_CORP_TAIL = re.compile(r"(?:,?\s+(?:ltd|llc|inc)\.?)+$", re.I)


def card_name(name):
    """The card's display name (29 Oct): display_name, a trailing Ltd / LLC / Inc dropped ("Marshas Ltd" ->
    "Marshas"), and an all-lowercase name title-cased ("september" -> "September"). Display only: matching and the
    reverse check read Qloo's own name."""
    out = display_name(name) or ""
    out = _CORP_TAIL.sub("", out).strip() or out
    if out and out == out.lower() and any(c.isalpha() for c in out):
        out = " ".join(w[:1].upper() + w[1:] for w in out.split(" "))
    return out or name


def why_line(i, fit, pop_ord, ids, everyone, counts, flat, tastes="other tastes"):
    """Why this card won, in <= 60 chars, from the score's own numbers (the card already shows "#f for you" and
    "#p for anyone"). lift = fit for you - max(popularity, fit for everyone); the larger of the two is the bar it
    cleared, and the line names that bar:
      fit for everyone  -> "only 9 of 97 sample tastes on Qloo put it in their top 30%" (the prior's own counts;
                           the anchor panel's tastes are samples from Qloo, not users; older set priors: "other tastes")
      popularity        -> "fits you better than 27 of the 30 more popular places"
      flat (taste barely moves the order; the 20% most popular are dropped) -> said so."""
    if flat:
        return "fits you, outside the %d%% most popular places here" % round(100 * (1 - CFG["FLAT_POP_KEEP"]))
    N = len(ids)
    p, e = ST.pct(pop_ord[i], N), everyone.get(i)
    if e is not None and e > p and i in counts:
        hits, n = counts[i]
        top = round(100 * (1 - CFG["PRIOR_TOP"]))
        if n == 1:
            return "%s the top %d%% of the one other taste that rates it" % ("in" if hits else "not in", top)
        if hits == 0:
            return "none of %d %s put it in their top %d%%" % (n, tastes, top)
        return "%s%d of %d %s put it in their top %d%%" % ("only " if 3 * hits <= n else "", hits, n, tastes, top)
    more = [j for j in ids if pop_ord[j] < pop_ord[i]]
    if not more:
        return "the most popular place here, and it fits you"
    beat = sum(1 for j in more if fit[j] > fit[i])
    if beat == len(more):
        return "fits you better than all %d more popular places" % len(more) if len(more) > 1 \
            else "fits you better than the one more popular place"
    return "fits you better than %d of the %d more popular places" % (beat, len(more))


WHAT_TAG_PREFIX = ("urn:tag:cuisine:", "urn:tag:category:place:", "urn:tag:genre:place:restaurant:",
                   "urn:tag:menu_highlight:", "urn:tag:specialty_dish:", "urn:tag:interests:", "urn:tag:offerings:",
                   "urn:tag:activity_type:", "urn:tag:beverage_offering:", "urn:tag:ambience:", "urn:tag:decor:")
_DETAIL = {}


# A reason links a place to a love by what you eat, drink or do there (30 Oct, juror: "reads like it guessed my race,
# not my taste"): never by who owns it or who goes there. Identity tags (ownership, customer identity, inclusivity,
# curated identity collections) and broad interest tags never serve as the link.
LINK_TAG_PREFIX = tuple(x for x in WHAT_TAG_PREFIX if x != "urn:tag:interests:")
_IDENTITY_RE = re.compile(r"inclusivity|customer_identity|resy:collection|owned|operated|lgbt|black|latino|latinx|"
                          r"hispanic|asian_owned|women|woman|veteran|minority|identif|heritage|culture|community", re.I)


def is_identity_tag(t):
    return bool(_IDENTITY_RE.search((t.get("id") or "") + " " + (t.get("name") or "")))


def _tags_of(e):
    out = {}
    for t in e.get("tags") or []:
        if isinstance(t, dict) and (t.get("id") or "").startswith(LINK_TAG_PREFIX) and t.get("name") \
                and not is_identity_tag(t):
            lab = _what_label(t)
            if lab and lab not in WHAT_BLAND and lab not in WHAT_SERVICE and \
                    (t.get("name") or "").strip().lower() not in WHAT_SERVICE:
                out[t["id"]] = lab
    return out


def because_detail(i, love, byid, ids, orders, tied, dish_tags, dish_tagged, used=None):
    """The reason line under "because you love X" (never empty for a credited card). A dish love: the dish tag
    itself. Any other love: the card's tag that is most over-represented among that love's top quarter of this pool
    (Qloo's own per-love ranking and Qloo's own tags; 0 extra calls), preferring one no other card in the same seven
    already shows (used: labels taken so far, updated); else Qloo's own rank of the place for that love."""
    if not love:
        return None
    txt = love["text"]
    lname = love.get("name") or txt
    if txt in dish_tags and i in dish_tagged.get(txt, ()):
        return "on Qloo's %s list" % lname.lower()
    if txt in dish_tags:                      # credited through the dish itself ("fried catfish" -> "Catfish")
        nm = M.norm(lname)
        heads = {nm, " ".join(w for w in nm.split() if w not in DISH_STYLE)}
        for t in byid[i].get("tags") or []:
            if isinstance(t, dict) and (t.get("id") or "").startswith(
                    ("urn:tag:menu_highlight:", "urn:tag:specialty_dish:", "urn:tag:cuisine:")) \
                    and M.norm(t.get("name") or "") in heads:
                return "Qloo tags it %s" % (t.get("name") or "").lower()
    if txt not in orders:
        return None
    lift = love_lift(txt, byid, ids, orders, tied)
    used = used if used is not None else set()
    mine = _tags_of(byid[i])
    ranked = sorted(((lift[t], mine[t]) for t in mine if lift.get(t, 0) >= LINK_MIN), key=lambda x: (-x[0], x[1]))
    labs = list(dict.fromkeys(l for _, l in ranked))
    strong = [l for l in labs if l not in used and any(v >= 1.5 for v, ll in ranked if ll == l)]
    fresh = strong or [l for l in labs if l not in used] or labs
    if fresh:
        pick = fresh[:1]
        used.update(pick)
        return "%s, like the places %s fans rank highest here" % (pick[0], lname)
    if i in tied[txt]:
        return None
    return "Qloo ranks it #%d of %d here for %s fans" % (orders[txt][i], len(ids), lname)


LINK_MIN = 1.2


def has_link(i, txt, byid, ids, orders, tied):
    """A taste tag of the place is over-represented (>= LINK_MIN) among the love's top quarter of this pool."""
    if txt not in orders:
        return False
    lift = love_lift(txt, byid, ids, orders, tied)
    return any(lift.get(t, 0) >= LINK_MIN for t in _tags_of(byid[i]))


def love_lift(txt, byid, ids, orders, tied):
    """{taste tag: over-representation in the love's top quarter of this pool}, once per love per run."""
    key = txt
    if _DETAIL.get("orders") is not orders or key not in _DETAIL:    # one run's orders (held: an id can be reused)
        if _DETAIL.get("orders") is not orders:
            _DETAIL.clear()
            _DETAIL["orders"] = orders
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
            if n >= 2 and n / float(len(top)) >= 0.1:
                lift[tid] = (n / float(len(top))) / (cnt_all[tid] / float(len(ids)))
        _DETAIL[key] = lift
    return _DETAIL[key]


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


def _anchor_shares(doc, love_ids):
    """Anchor panel (build_priors.py): per place, the share of the city's anchor tastes (single loves sampled from
    Qloo) that put it in their top PRIOR_TOP of the city's universe, as (hits + 0.5) / (n + 1). Anchors that are one
    of this query's loves are left out. Returns ({place: share}, {place: (hits, n)}, median share, anchors used)."""
    keep = frozenset(k for k, a in enumerate(doc["anchors"]) if a.get("live", True) and a["id"] not in love_ids)
    memo = doc.setdefault("_memo", {})
    if keep not in memo and len(memo) >= 8:      # one entry per distinct set of left-out anchors: bounded
        memo.clear()
    if keep not in memo:
        share, counts = {}, {}
        top, miss = doc.get("top") or {}, doc.get("miss") or {}
        for i in doc["scored"]:
            n = len(keep) - len(keep.intersection(miss.get(i, ())))
            h = len(keep.intersection(top.get(i, ())))
            if n > 0:
                share[i], counts[i] = (h + 0.5) / (n + 1.0), (h, n)
        vals = sorted(share.values())
        med = (vals[(len(vals) - 1) // 2] + vals[len(vals) // 2]) / 2.0 if vals else 0.5
        memo[keep] = (share, counts, med, len(keep))
    return memo[keep]


def everyone_pct(city, ids, love_ids):
    """{place: percentile within this U of its fit for everyone}. Every place in U gets a value: a place with no
    prior gets the median, never zero (zero would exempt exactly the places the prior never saw).
    Anchor-panel priors (doc["anchors"]): see _anchor_shares. Older set priors (doc["sets"]): mean over the preset
    sets sharing no love with this query (leave-one-out by love)."""
    doc = load_prior(city.get("key")) if CFG["PRIOR_ENABLED"] else None
    if not doc:
        return {}, {}, {"used": False, "why": "no prior for this city"}
    if doc.get("anchors"):
        share, counts, med, n_anchors = _anchor_shares(doc, love_ids)
        val = {i: share.get(i, med) for i in ids}
        rk = ST.rank(val)
        covered = sum(1 for i in ids if i in share)
        return ({i: ST.pct(rk[i], len(ids)) for i in ids}, {i: counts[i] for i in ids if i in counts},
                {"used": True, "method": "anchors", "anchors": n_anchors,
                 "excluded_anchors": sum(1 for a in doc["anchors"] if a["id"] in love_ids), "covered": covered,
                 "imputed_median": len(ids) - covered, "U": len(ids), "built_at": doc.get("built_at")})
    sets = [s for s in doc["sets"] if not ({l["id"] for l in s["loves"]} & love_ids)]
    mean, counts = {}, {}                    # counts: {place: (other tastes with it in their top PRIOR_TOP, of n)}
    for i in ids:
        v = [s["fit_pct"][i] for s in sets if i in s["fit_pct"]]
        if len(v) >= CFG["PRIOR_MIN_SETS"]:
            counts[i] = (sum(1 for x in v if x >= CFG["PRIOR_TOP"]), len(v))
            if CFG["PRIOR_STAT"] == "top":     # (hits + 0.5) / (n + 1): a lone observation counts for less
                mean[i] = (sum(1 for x in v if x >= CFG["PRIOR_TOP"]) + 0.5) / (len(v) + 1.0)
            else:
                mean[i] = sum(v) / len(v)
    if len(mean) < 3:
        return {}, {}, {"used": False, "why": "too few places with a prior", "sets": len(sets)}
    vals = sorted(mean.values())
    n0 = len(vals)
    med = (vals[(n0 - 1) // 2] + vals[n0 // 2]) / 2.0 if n0 else 0.5
    rk = ST.rank({i: mean.get(i, med) for i in ids})     # 1 = fits everyone best; no prior -> the median
    n = len(mean)
    return ({i: ST.pct(rk[i], len(ids)) for i in ids}, counts,
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
        # coverage over the places the rescoring can return at all: a dish-only member (tagged with the dish but
        # not with the restaurant/bar kinds the base filter asks for) is ranked by its dish, never a failed lane
        visible = [i for i in ids if any((t.get("id") or "") in CFG["CAT_TAGS"] for t in byid[i].get("tags") or []
                                         if isinstance(t, dict))]
        vis_cov = (sum(1 for i in visible if i in rs["aff"]) / float(len(visible))) if visible else 1.0
        rs_diag[l["text"]]["coverage_visible"] = round(vis_cov, 4)
        if rs["failed"] or vis_cov < CFG["COVERAGE_MIN"]:
            lanes_failed.append("C6' %s coverage %.2f" % (l["text"], vis_cov))
        rs_diag[l["text"]]["drifted_chunks"] = rs["drifted_chunks"]
        if not rs["drift_ok"]:              # chunks did not merge on one scale (ANCHOR_DRIFT_MAX): flagged, not hidden
            lanes_failed.append("C6' %s anchor drift %.4f in chunks %s" % (l["text"], rs["drift"], rs["drifted_chunks"]))
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
    everyone, ev_counts, prior_diag = everyone_pct(city, ids, {l["id"] for l in loves if l.get("id")})
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
    res["diag"]["S_holds"] = [len(S), len(eligible)]
    generic = {i for i in eligible if i in ev_counts and ev_counts[i][1] and
               ev_counts[i][0] >= CFG["GENERIC_SHARE"] * ev_counts[i][1]}
    chain = chain_ids(pool, eligible)
    eligible = [i for i in eligible if i not in generic and i not in chain]
    res["diag"]["generic_cut"] = len(generic)
    res["diag"]["eligible"] = len(eligible)
    res["diag"]["chain_cut"] = sorted(byid[i].get("name") or i for i in chain)
    if flat:
        keep_from = (1 - CFG["FLAT_POP_KEEP"]) * N        # drop the most popular 20 %
        order = sorted([i for i in eligible if pop_ord[i] > keep_from], key=lambda i: (fit[i], i))
        score = {i: round(pct(fit[i]), 4) for i in ids}          # flat: the score is fit (what the order uses)
    else:
        order = sorted(eligible, key=lambda i: (-lift[i], fit[i], i))
        score = {i: round(lift[i], 4) for i in ids}
    # Variety fallback (29 Oct): when the seven can't reach its mix from `order`, places that hold for at least one
    # pair of loves (instead of all but one) may fill the gap, in the same score order; never generic, never chains
    wide = []
    if CFG.get("MIX_WIDE", True) and n_live >= 3:
        inset = set(order)
        wide = [i for i in S if i not in inset and holds[i] is not None and holds[i] >= 1
                and any(i not in tied[l["text"]] for l in live) and i not in generic and i not in chain_ids(pool, [i])]
        wide = sorted(wide, key=(lambda i: (fit[i], i)) if flat else (lambda i: (-lift[i], fit[i], i)))
    res["diag"]["wide"] = len(wide)

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
    # ---- credit: which love a card is "because". A love credits a place it scores (not tied); a dish love only a
    # place Qloo tags with the dish. The best-ranking love credits it; at the cap, another love that ranks it in its
    # top ALT_CREDIT_FRAC may.
    love_by = {l["text"]: l for l in live}

    # a dish love also credits a place tagged with the dish itself without its cooking style: "fried catfish"
    # credits a place Qloo tags "Catfish" (29 Oct; the sub-pool and the ranking are unchanged)
    dish_heads = {}
    for l in live:
        if l["text"] in dish_tags:
            nm = M.norm(l.get("name") or l["text"])
            head = " ".join(w for w in nm.split() if w not in DISH_STYLE)
            dish_heads[l["text"]] = {nm, head} - {""}

    def can_credit(i, l):
        if i in tied[l["text"]] and l["text"] not in dish_tags:
            return False
        if l["text"] in dish_tags and not dish_in_text(byid[i], l.get("name") or l["text"]):
            return False                      # the dish must be in the place's own Qloo text (30 Oct, QA)
        if l["text"] in dish_tags:
            heads = dish_heads.get(l["text"]) or set()
            return any(isinstance(t, dict) and ((t.get("id") or "") in dish_tags[l["text"]] or (
                (t.get("id") or "").startswith(("urn:tag:menu_highlight:", "urn:tag:specialty_dish:",
                                                "urn:tag:cuisine:")) and M.norm(t.get("name") or "") in heads))
                       for t in byid[i].get("tags") or [])
        return True

    alt_cut = math.ceil(N * CFG["ALT_CREDIT_FRAC"])

    _cr = {}

    def credits(i):
        """Loves that may credit i, best first: [(rank, text, alt_ok)] (memoised: it never depends on the counts)."""
        if i not in _cr:
            # a place carrying a dish you love is credited to that dish first (29 Oct: catfish -> fried catfish)
            # a love with a taste link to the place (a dish it carries, or a taste tag over-represented among the
            # love's top places) credits it before a love without one (30 Oct)
            out = sorted((0 if l["text"] in dish_tags else 1, 0 if linked(i, l["text"]) else 1,
                          orders[l["text"]][i], l["text"]) for l in live if can_credit(i, l))
            _cr[i] = [(r, t, k == 0 or r <= alt_cut) for k, (_d, _l, r, t) in enumerate(out)]
        return _cr[i]

    _lk = {}

    def linked(i, txt):
        if (i, txt) not in _lk:
            _lk[(i, txt)] = (txt in dish_tags) or has_link(i, txt, byid, ids, orders, tied)
        return _lk[(i, txt)]

    def any_link(i):
        return any(linked(i, t) for _, t, _ in credits(i)) if live else True

    # soft filter: places no love has a taste link to come after every linked place (same score order within each)
    order = [i for i in order if any_link(i)] + [i for i in order if not any_link(i)]
    wide = [i for i in wide if any_link(i)] + [i for i in wide if not any_link(i)]

    cap = CFG["LOVE_CAP"] if len(live) >= 2 else None
    credit_of, cnt = {}, collections.Counter()

    def credit_for(i, counts):
        """-> (love text or None, fits under the cap)."""
        cs = credits(i)
        if not cs:
            return None, not live           # no love can explain it: never a card when loves are live
        if cap is None or counts[cs[0][1]] < cap:
            return cs[0][1], True
        for r, t, ok in cs[1:]:
            if ok and counts[t] < cap:
                return t, True
        return cs[0][1], False

    checked = {}

    def check(i):
        """The reverse check and the last-seen check, once per place."""
        if i in checked:
            return checked[i]
        e = byid[i]
        h = reverse_hit(e.get("name"), rindex)
        if h is not None:
            rev_struck.append({"id": i, "name": e.get("name"), "answer": h})
            struck.setdefault(i, []).append(("reverse", "REV"))
            emit("strike", {"name": e.get("name"), "norm": M.norm(e.get("name") or ""), "outcome": "struck",
                            "reason": "reverse check", "qloo_id": i})
            checked[i] = False
            return False
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
            checked[i] = False
            return False
        seen_info[i] = info
        checked[i] = True
        return True

    N7, NR = CFG["N_CARDS"], CFG["N_RESERVES"]
    centroids = [("osm", osm_hoods(city.get("key"))), ("pool", pool_hoods(pool))]
    _kind, _hood = {}, {}

    def kind(i):
        if i not in _kind:
            _kind[i] = kind_of(byid[i])
        return _kind[i]

    def bucket(i):
        k = kind(i)
        return k[0] if k[0] == "drink" else "eat:" + k[1]

    def hood(i):
        if i not in _hood:
            _hood[i] = hood_of(byid[i], centroids)[0] or ""
        return _hood[i]

    kcap = CFG["KIND_CAP"]
    kcnt = collections.Counter()
    picks0 = []
    rank_of = {i: r for r, i in enumerate(order + wide)}

    def add(i, c):
        picks0.append(i)
        credit_of[i] = c
        cnt[c] += 1
        kcnt[bucket(i)] += 1

    def drop(i):
        picks0.remove(i)
        cnt[credit_of.pop(i)] -= 1
        kcnt[bucket(i)] -= 1

    # 1. greedy over the score: a card is skipped while its love (LOVE_CAP) or its kind (KIND_CAP) is full
    blocked = []
    for i in order + wide:
        if len(picks0) >= N7:
            break
        c, ok = credit_for(i, cnt)
        if c is None and live:
            continue
        if not ok or kcnt[bucket(i)] >= kcap:
            blocked.append(i)
            continue
        if check(i):
            add(i, c)

    def swap_in(want, may_drop, credit=None, scan=None, any_kind=False):
        """The best-scoring passing place `want` accepts replaces the lowest-scored card `may_drop` allows, keeping
        both caps (the victim's love and kind counts already reduced). Returns True when a swap happened."""
        tries = 0
        for i in (scan if scan is not None else order):
            if i in credit_of or checked.get(i) is False or not want(i):
                continue
            for v in sorted(picks0, key=lambda x: -rank_of[x]) if len(picks0) >= N7 else [None]:
                if v is not None and not may_drop(v):
                    continue
                cc = Counter_minus(cnt, credit_of.get(v)) if v is not None else cnt
                kc = Counter_minus(kcnt, bucket(v)) if v is not None else kcnt
                c = credit if credit is not None else credit_for(i, cc)[0]
                if c is None and live:
                    continue
                if cap is not None and cc[c] >= cap and credit is None:
                    c2, ok2 = credit_for(i, cc)
                    if not ok2:
                        continue
                    c = c2
                if kc[bucket(i)] >= kcap and not any_kind:
                    continue
                tries += 1
                if tries > CFG["BALANCE_SCAN"]:
                    return False
                if not check(i):
                    break
                if v is not None:
                    drop(v)
                add(i, c)
                return True
        return False

    def Counter_minus(cn, key):
        x = collections.Counter(cn)
        x[key] -= 1
        return x

    def keeps_loves(v):         # dropping v leaves every credited love with a card
        return credit_of.get(v) is None or cnt[credit_of[v]] > 1

    # 2. every live love credits at least one card when a passing place can be credited to it
    if cap is not None and not all_dead:
        for l in live:
            t = l["text"]
            if cnt[t]:
                continue
            done_ = False
            for any_kind in (False, True):          # a love's first card outranks the kind cap
                for pool_ in (order, wide):
                    best = [i for i in pool_ if credits(i) and credits(i)[0][1] == t]
                    alt = [i for i in pool_ if i not in best and any(tt == t and ok for _, tt, ok in credits(i)[1:])]
                    if swap_in(lambda i: True, keeps_loves, credit=t, scan=best + alt, any_kind=any_kind):
                        done_ = True
                        break
                if done_:
                    break
    # 3. at least MIN_EAT places to eat and MIN_DRINK to drink, when the pool has them
    for sd, other, need in (("eat", "drink", CFG["MIN_EAT"]), ("drink", "eat", CFG["MIN_DRINK"])):
        while sum(1 for x in picks0 if kind(x)[0] == sd) < need:
            if not swap_in(lambda i, s=sd: kind(i)[0] == s,
                           lambda v, o=other: kind(v)[0] == o and keeps_loves(v)
                           and sum(1 for x in picks0 if kind(x)[0] == o) > need, scan=order + wide):
                break
    # 4. at least MIN_HOODS neighbourhoods: a place in a new one replaces the lowest-scored card of the busiest
    while len({hood(x) for x in picks0}) < CFG["MIN_HOODS"] and len(picks0) >= N7:
        hc = collections.Counter(hood(x) for x in picks0)
        busiest = hc.most_common(1)[0][0]
        have = set(hc)
        sd_n = collections.Counter(kind(x)[0] for x in picks0)
        if not swap_in(lambda i: hood(i) and hood(i) not in have,
                       lambda v: hood(v) == busiest and keeps_loves(v)
                       and sd_n[kind(v)[0]] > (CFG["MIN_EAT"] if kind(v)[0] == "eat" else CFG["MIN_DRINK"]),
                       scan=order + wide):
            break
    # 5. too few under the caps: the wider pool under both caps, then a love may pass its cap (a love that can
    # credit nothing leaves the others more), then the kinds give way, then both
    for scan, relax_kind, relax_love in ((wide, False, False), (order + wide, False, True), (order, True, False),
                                         (order + wide, True, True)):
        for i in scan:
            if len(picks0) >= N7:
                break
            if i in credit_of or (live and not credits(i)):
                continue
            c, ok = credit_for(i, cnt)
            if (not ok and not relax_love) or (kcnt[bucket(i)] >= kcap and not relax_kind):
                continue
            if check(i):
                add(i, c)
    picks0.sort(key=lambda i: rank_of[i])
    # reserves: the next places that keep both caps when they rise into any card's slot; else the next by score
    res0 = []
    for strict in (True, False):
        for i in order + wide:
            if len(res0) >= NR:
                break
            if i in credit_of or (live and not credits(i)):
                continue
            c, ok = credit_for(i, cnt)
            if strict and (not ok or kcnt[bucket(i)] >= kcap):
                continue
            if check(i):
                res0.append(i)
                credit_of[i] = c
    selected = picks0 + res0
    centroids = [("osm", osm_hoods(city.get("key"))), ("pool", pool_hoods(pool))]
    hoods = {i: hood_of(byid[i], centroids) for i in selected}
    picks, reserves = list(picks0), list(res0)

    # ---- because-line: the love credit_of assigned; else the live love whose order ranks x best (never a tied one)
    def because(i):
        if i in credit_of:
            return love_by.get(credit_of[i])
        best = None
        for l in live:
            if i in tied[l["text"]]:
                continue
            r = orders[l["text"]][i]
            if best is None or r < best[0]:
                best = (r, l)
        return best[1] if best else None

    asked_hoods, street_answers = {}, []
    details = {}
    vocab = dish_vocab(U)
    cl = load_lines(city.get("key"))

    def assign_details():
        """Each card's reason line, the seven in for-you order then the reserves, so no two show the same tag."""
        details.clear()
        used = set()
        for i in sorted(picks, key=lambda x: (fit[x], x)) + list(reserves):
            details[i] = because_detail(i, because(i), byid, ids, orders, tied, dish_tags, dish_tagged, used)

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
        return {"id": i, "name": card_name(e.get("name")), "name_qloo": e.get("name"), "what": what_line(e),
                "score": score[i],
                "why": why_line(i, fit, pop_ord, ids, everyone, ev_counts, flat,
                                "sample tastes on Qloo" if prior_diag.get("method") == "anchors" else "other tastes"),
                "because_detail": None,       # 30 Oct: no generated "X, like the places Y fans rank" line
                "neighbourhood_src": hood_src, "area": hood or None,
                "distance_mi": round(C.haversine_mi((ll[0], ll[1]), city["center_latlon"]), 1)
                if ll[0] is not None else None, "distance_from": CENTER_LABEL.get(city.get("key")),
                "kind": kind(i)[0], "kind_family": kind(i)[1], "image": image_url(e), "blurb": (cl.get(i) or {}).get("line") or blurb_line(e, hood),
                "line_src": "claude" if (cl.get(i) or {}).get("line") else "rules",
                "order": clean_order((cl.get(i) or {}).get("dishes") or order_line(e, vocab), e, vocab)
                or clean_order(order_line(e, vocab), e, vocab), "price": price_line(e),
                "hours": prop(e, "hours") or None, "tz": CITY_TZ.get(city.get("key")),
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
            if reserves:                 # the first reserve that keeps the balance (the lost love first)
                now = collections.Counter(credit_of.get(p) for p in picks)
                lost = credit_of.get(x)
                kn = collections.Counter(bucket(p) for p in picks)
                fits = [r for r in reserves if (cap is None or now[credit_of.get(r)] < cap) and kn[bucket(r)] < kcap]
                up = next((r for r in reserves if lost is not None and not now[lost] and credit_of.get(r) == lost),
                          None) or next(iter(fits), None) or next((r for r in reserves if cap is None or
                                                                   now[credit_of.get(r)] < cap), reserves[0])
                reserves.remove(up)
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
    res["diag"]["credits"] = dict(collections.Counter(c["because"] for c in res["picks"]))
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
    # "the AIs named N places", honestly (29 Oct): a name Qloo resolved to something that is not a place to eat or
    # drink (Green-Wood Cemetery, The Cloisters) is on the wall but not in this count; names with no Qloo ID stay
    nonfood = {w["place"] for w in wall_items if w.get("reason") == "not a restaurant or bar"}
    n_food = len({w["place"] for w in wall_items} - nonfood)

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
    res["counts"].update({"wall": n_places, "named_food_count": n_food, "asks": n_city + len(street_answers), "S": len(S),
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
