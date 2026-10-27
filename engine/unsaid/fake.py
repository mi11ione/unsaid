"""Fake Qloo: canned, deterministic responses shaped like the documented ones, so every script runs end to end
without a key. The numbers it produces prove code paths, not Qloo. Every script prints [FAKE] next to PASS/FAIL.

Shapes follow the docs:
- /v2/insights -> {"success", "duration", "results": {"entities": [entity...]}, "query": {"explainability": {...}}}
  entity = {name, entity_id (UUID), type "urn:entity", subtype, properties{address, business_rating, is_closed,
  neighborhood, geocode{name, city, admin1_region, country_code, metro}}, location{lat, lon, geohash},
  popularity, tags[{id,name,type}], query{affinity, explainability{"signal.interests.entities":[{entity_id,score}]}}}
  (reference_basic-insights-use-case.md, reference_schema-taxonomy.md place schema, jeretc README for explainability)
- /search -> {"success", "duration", "results": [entity...]}; 404 {"code","reason","message"} when nothing matches
- /v2/tags -> {"success", "duration", "results": {"tags": [{id, name, type}]}}
- /entities -> {"success", "results": {"entities": [...]}}
Unknowns are modelled one way and flagged (engine-v3.md §U): the top-level aggregate explainability shape;
no-signal order (= popularity here); a non-enum business_rating.min (silently ignored here, like other bad params).
Knobs: FAKE_TASTE_WEIGHT (default 0.55) sets how much taste moves ranks; FAKE_FLAKY=1 injects a 429 every 17th call.
"""
import hashlib
import json
import math
import os
import sys
import urllib.parse
import uuid

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if KIT not in sys.path:
    sys.path.insert(0, KIT)
from fixtures import matcher_catalog as MC  # noqa: E402

NS = uuid.UUID("6f1c2a52-3d43-4b55-9a77-2b8f0d0c1e01")


def uid(s):
    return str(uuid.uuid5(NS, s)).upper()


def h(s, k=0):
    return int(hashlib.md5(("%s|%d" % (s, k)).encode()).hexdigest()[:12], 16) / float(16 ** 12)


def vec(s, dim=6):
    v = [h(s, i) * 2 - 1 for i in range(dim)]
    n = math.sqrt(sum(x * x for x in v)) or 1
    return [x / n for x in v]


def cos(a, b):
    return sum(x * y for x, y in zip(a, b))


CITIES = {
    "nyc": {"name": "New York City", "lat": 40.7128, "lon": -74.0060, "admin1": "New York", "metro": "New York City",
            "disamb": "New York, New York, United States of America",
            "hoods": ["East Village", "West Village", "Lower East Side", "Williamsburg", "Bushwick", "Greenpoint",
                      "Upper East Side", "Harlem", "Astoria", "Park Slope", "Chinatown", "Midtown"]},
    "stl": {"name": "St. Louis", "lat": 38.6270, "lon": -90.1994, "admin1": "Missouri", "metro": "St. Louis",
            "disamb": "St. Louis, Missouri, United States of America",
            "hoods": ["Central West End", "The Hill", "Soulard", "Lafayette Square", "The Grove", "Tower Grove",
                      "Delmar Loop", "Downtown", "Benton Park", "Cherokee Street", "Midtown", "North City"]},
}
LOCALITY_IDS = {c: uid("locality:" + c) for c in CITIES}
EXTRA_LOCALITIES = [  # the Richmond trap entrants hit: the first "Richmond" is on Staten Island
    {"key": "richmond-si", "name": "Richmond", "lat": 40.5795, "lon": -74.1502, "disamb": "Staten Island, New York, United States of America"},
    {"key": "richmond-va", "name": "Richmond", "lat": 37.5407, "lon": -77.4360, "disamb": "Richmond, Virginia, United States of America"},
]

TAG = {
    "restaurant": ("urn:tag:genre:place:restaurant", "Restaurant", "urn:tag:genre:place"),
    "bar": ("urn:tag:genre:place:restaurant:bar", "Bar", "urn:tag:genre:place:restaurant"),
    "catbar": ("urn:tag:category:place:bar", "Bar", "urn:tag:category:place"),
    "bbq": ("urn:tag:genre:place:restaurant:barbecue", "Barbecue", "urn:tag:genre:place:restaurant"),
    "italian": ("urn:tag:genre:place:restaurant:italian", "Italian", "urn:tag:genre:place:restaurant"),
    "music": ("urn:tag:category:place:live_music_venue", "Live music venue", "urn:tag:category:place"),
    "comedy": ("urn:tag:category:place:comedy_club", "Comedy club", "urn:tag:category:place"),
    "hotel": ("urn:tag:genre:place:hotel", "Hotel", "urn:tag:genre:place"),
}
SEED_TAGS = {  # /v2/tags answers for food-ish loves
    "rib tips": ("urn:tag:specialty_dish:place:rib_tips", "Rib Tips", "urn:tag:specialty_dish:place", "bbq"),
    "soul food": ("urn:tag:cuisine:qloo:soul_food", "Soul Food", "urn:tag:cuisine:qloo", "bbq"),
    "toasted ravioli": ("urn:tag:specialty_dish:place:toasted_ravioli", "Toasted Ravioli", "urn:tag:specialty_dish:place", "italian"),
    "tacos al pastor": ("urn:tag:specialty_dish:place:tacos_al_pastor", "Tacos al pastor", "urn:tag:specialty_dish:place", None),
    "natural wine": ("urn:tag:dining_option:qloo:wine_bar", "Wine Bar", "urn:tag:dining_option:qloo", "bar"),
    "ramen": ("urn:tag:cuisine:qloo:ramen", "Ramen", "urn:tag:cuisine:qloo", None),
}
CLOSED_TRUTH = {"Sweetie Pie's": True, "Mike Shannon's Steaks and Seafood": True,
                "Grace Meat & Three": False}  # Grace: modelled as a stale record (closed 13 Sep 2026, still open here)
BBQ_WORDS = ("bbq", "smoke", "rib", "barbecue", "q and")
BAR_WORDS = ("bar", "pub", "tavern", "lounge", "club", "cocktail", "wine", "taproom", "beer")
OUT_KIND = {"Nowadays": "music", "The Sultan Room": "music", "Good Room": "music", "The Lot Radio": "music",
            "Café Carlyle": "music", "The Pageant": "music", "Delmar Hall": "music", "Robbie's House of Jazz": "music",
            "Jazz St. Louis": "music", "The Duck Room at Blueberry Hill": "music", "Helium Comedy Club": "comedy",
            "The Funny Bone": "comedy", "Ballpark Village": "music", "The Carlyle, A Rosewood Hotel": "hotel",
            "Hotel Chelsea": "hotel", "The Beekman, A Thompson Hotel": "hotel"}


def _place(city, name, key, kind_tags, closed=False):
    c = CITIES[city]
    eid = uid("place:%s:%s" % (city, key))
    u = h(key, 1)
    pop = 1 - 10 ** (-(0.35 + 2.9 * u))           # bunches towards 1, like the live API
    rating = round(3.7 + 1.2 * h(key, 2), 1)
    hood = c["hoods"][int(h(key, 3) * len(c["hoods"]))]
    lat = c["lat"] + (h(key, 4) - 0.5) * 0.12
    lon = c["lon"] + (h(key, 5) - 0.5) * 0.12
    tags = [{"id": TAG[t][0], "name": TAG[t][1], "type": TAG[t][2]} for t in kind_tags]
    return {"name": name, "entity_id": eid, "type": "urn:entity", "subtype": "urn:entity:place",
            "properties": {"address": "%d Example St, %s" % (int(h(key, 6) * 900) + 10, c["name"]),
                           "business_rating": rating, "is_closed": closed, "neighborhood": hood,
                           "geocode": {"name": c["name"], "city": c["name"], "admin1_region": c["admin1"],
                                       "country_code": "US", "metro": c["metro"]},
                           "website": "https://example.invalid/%s" % eid[:8]},
            "location": {"lat": lat, "lon": lon, "geohash": "fake%s" % eid[:6].lower()},
            "popularity": pop, "tags": tags, "_city": city, "_vec": vec("place:" + key)}


def _kind_for(name):
    n = name.lower()
    k = ["restaurant"]
    if any(w in n for w in BAR_WORDS):
        k += ["bar", "catbar"]
    if any(w in n for w in BBQ_WORDS):
        k.append("bbq")
    return k


def build_world():
    places = []
    for city, table in (("nyc", MC.NYC), ("stl", MC.STL)):
        for raw, recs in table.items():
            for j, (qname, inpool) in enumerate(recs):
                key = "%s#%d" % (raw, j)
                if qname in OUT_KIND:
                    kt = [OUT_KIND[qname]]
                else:
                    kt = _kind_for(qname)
                    if city == "nyc" and "bar" not in kt:
                        kt += ["bar", "catbar"]  # case A's NYC list is bars
                closed = CLOSED_TRUTH.get(qname, False)
                places.append(_place(city, qname, key, kt, closed))
        for d in MC.DECOYS[city]:
            places.append(_place(city, d, "decoy:" + d, _kind_for(d)))
        if city == "stl":
            places.append(_place(city, "Mike Shannon's Steaks and Seafood", "mike-shannon", ["restaurant"], True))
        syl = ["mar", "vel", "tor", "quin", "bel", "sor", "dra", "lin", "fen", "osk", "pell", "rav", "zan", "thu",
               "corb", "esk", "lom", "nyr", "vash", "ilo", "brin", "cael"]
        suf = ["Tavern", "Kitchen", "Bar", "Cafe", "Room", "Social", "Provisions", "Wine Bar", "Grill", "House",
               "Smokehouse", "Trattoria", "Noodle Bar", "Oyster Bar"]
        n = 0
        for i in range(len(syl)):
            for j in range(len(syl)):
                if i == j or n >= 330:
                    continue
                nm = "%s%s %s" % (syl[i].capitalize(), syl[j], suf[(i * 5 + j * 3 + (city == "stl")) % len(suf)])
                kt = _kind_for(nm)
                if "trattoria" in nm.lower():
                    kt.append("italian")
                closed = h(city + nm, 9) < 0.03
                places.append(_place(city, nm, "filler:" + nm, kt, closed))
                n += 1
    by_id = {p["entity_id"]: p for p in places}
    return places, by_id


SEED_TYPES = {
    "khruangbin": "artist", "the grand budapest hotel": "movie", "radiohead": "artist", "lost in translation": "movie",
    "norwegian wood": "book", "bad bunny": "artist", "narcos": "tv_show", "taylor swift": "artist",
    "gilmore girls": "tv_show", "kendrick lamar": "artist", "atlanta": "tv_show", "popeyes": "brand",
    "phoebe bridgers": "artist", "lady bird": "movie", "frank sinatra": "artist", "the godfather": "movie",
    "beyonce": "artist", "insecure": "tv_show", "sweetgreen": "brand", "bob dylan": "artist",
    "inside llewyn davis": "movie", "daft punk": "artist", "blade runner 2049": "movie",
    "the original kings of comedy": "movie", "frankie beverly & maze": "artist", "frankie beverly and maze": "artist",
    "rounders": "movie", "al green": "artist", "barbershop": "movie", "the neighborhood": "tv_show",
    "joe turner's come and gone": "book", "nelly": "artist", "the blues brothers": "movie", "ted lasso": "tv_show",
    "starbucks": "brand", "jay-z": "artist", "paid in full": "movie", "budweiser": "brand", "wilco": "artist",
}
SEED_PLACES = {"ten bells": ("nyc", "The Ten Bells"), "carbone": ("nyc", "Carbone"), "levain bakery": ("nyc", "Levain Bakery"),
               "joe's pizza": ("nyc", "Joe's Pizza")}


class FakeQloo:
    def __init__(self):
        self.places, self.by_id = build_world()
        for key, (city, nm) in SEED_PLACES.items():  # seed places that are not in the fixture
            if not any(p["name"] == nm and p["_city"] == city for p in self.places):
                p = _place(city, nm, "seed:" + key, _kind_for(nm) + (["italian"] if key == "carbone" else []))
                self.places.append(p)
                self.by_id[p["entity_id"]] = p
        self.seeds = {}
        self.n = 0
        self.flaky = os.environ.get("FAKE_FLAKY") == "1"
        self.w = float(os.environ.get("FAKE_TASTE_WEIGHT", "0.55"))

    # ---- transport interface -------------------------------------------
    def get(self, url):
        self.n += 1
        if self.flaky and self.n % 17 == 0:
            return 429, json.dumps({"code": 429, "reason": "Too Many Requests"}), {"Retry-After": "0"}
        u = urllib.parse.urlsplit(url)
        params = dict(urllib.parse.parse_qsl(u.query, keep_blank_values=True))
        try:
            if u.path == "/v2/insights":
                return self.insights(params)
            if u.path == "/search":
                return self.search(params)
            if u.path == "/v2/tags":
                return self.tags(params)
            if u.path == "/entities":
                ids = params.get("entity_ids", "").split(",")
                ents = [self._pub(self.by_id[i]) if i in self.by_id else self.seeds.get(i) for i in ids]
                return 200, json.dumps({"success": True, "results": {"entities": [e for e in ents if e]}}), {}
        except _Bad as e:
            return 400, json.dumps({"code": 400, "reason": "Bad Request", "message": str(e)}), {}
        return 404, json.dumps({"code": 404, "reason": "Not Found"}), {}

    # ---- helpers ---------------------------------------------------------
    def _pub(self, p, aff=None, expl=None):
        e = {k: v for k, v in p.items() if not k.startswith("_")}
        if aff is not None:
            e["query"] = {"affinity": aff}
            if expl is not None:
                e["query"]["explainability"] = expl
        return e

    def _seed(self, name, typ):
        key = name.strip().lower()
        if key in SEED_PLACES:
            city, nm = SEED_PLACES[key]
            p = next(p for p in self.places if p["name"] == nm and p["_city"] == city)
            return self._pub(p)
        eid = uid("seed:" + key)
        e = {"name": name.strip(), "entity_id": eid, "type": "urn:entity", "subtype": "urn:entity:" + typ,
             "types": ["urn:entity:" + typ], "properties": {}, "popularity": 0.9 + 0.099 * h(key, 7), "tags": []}
        self.seeds[eid] = e
        return e

    def _city_of(self, loc):
        if loc is None:
            return None
        for c, i in LOCALITY_IDS.items():
            if loc == i:
                return c
        if loc.upper().startswith("POINT("):
            lon, lat = [float(x) for x in loc[6:-1].split()]
        elif "," in loc:
            lat, lon = [float(x) for x in loc.split(",")]
        else:
            return None
        best = min(CITIES, key=lambda c: (CITIES[c]["lat"] - lat) ** 2 + (CITIES[c]["lon"] - lon) ** 2)
        d = math.hypot(CITIES[best]["lat"] - lat, CITIES[best]["lon"] - lon)
        return best if d < 0.6 else None

    # ---- endpoints -------------------------------------------------------
    def tags(self, p):
        q = p.get("filter.query", "").lower().strip()
        out = []
        if q in SEED_TAGS:
            i, n, t, _ = SEED_TAGS[q]
            out.append({"id": i, "name": n, "type": t})
        if q == "bar":
            for k in ("catbar", "bar"):
                out.append({"id": TAG[k][0], "name": TAG[k][1], "type": TAG[k][2]})
        if q == "restaurant":
            out.append({"id": TAG["restaurant"][0], "name": "Restaurant", "type": TAG["restaurant"][2]})
        tt = p.get("filter.tag.types")
        if tt:
            out = [x for x in out if x["type"] in tt.split(",")]
        return 200, json.dumps({"success": True, "duration": 0.02, "results": {"tags": out}}), {}

    def search(self, p):
        q = p.get("query", "")
        types = (p.get("types") or "").split(",") if p.get("types") else []
        take = int(p.get("take", 10))
        res = []
        if "urn:entity:locality" in types:
            qn = q.lower()
            for c, d in CITIES.items():
                if qn in d["name"].lower() or d["name"].lower() in qn or (c == "stl" and "louis" in qn) or (
                        c == "nyc" and qn in ("new york", "nyc")):
                    res.append({"name": d["name"], "entity_id": LOCALITY_IDS[c], "type": "urn:entity",
                                "subtype": "urn:entity:locality", "types": ["urn:entity:locality"],
                                "location": {"lat": d["lat"], "lon": d["lon"]}, "disambiguation": d["disamb"],
                                "properties": {"geocode": {"name": d["name"]}}, "popularity": 0.99})
            for x in EXTRA_LOCALITIES:
                if x["name"].lower() in qn:
                    res.append({"name": x["name"], "entity_id": uid("locality:" + x["key"]), "type": "urn:entity",
                                "subtype": "urn:entity:locality", "types": ["urn:entity:locality"],
                                "location": {"lat": x["lat"], "lon": x["lon"]}, "disambiguation": x["disamb"],
                                "properties": {}, "popularity": 0.9})
        elif not types or "urn:entity:place" in types:
            from unsaid import matcher as M
            city = self._city_of(p.get("filter.location"))
            r = M.norm(q)
            import difflib
            scored = []
            for pl in self.places:
                if city and pl["_city"] != city:
                    continue
                s = difflib.SequenceMatcher(None, r, M.norm(pl["name"])).ratio()
                s += 0.3 * M.overlap(M.distinctive(q), M.distinctive(pl["name"]))
                if s > 0.6:
                    scored.append((s, pl))
            scored.sort(key=lambda x: (-x[0], x[1]["entity_id"]))
            res = [self._pub(pl) for _, pl in scored[:take]]
            if not res and q.strip().lower() in SEED_PLACES:
                res = [self._seed(q, "place")]
        if not res and types and "urn:entity:place" not in types and "urn:entity:locality" not in types:
            typ = SEED_TYPES.get(q.strip().lower(), types[0].split(":")[-1])
            res = [self._seed(q, typ)]
        elif not res and not types:
            typ = SEED_TYPES.get(q.strip().lower())
            if typ:
                res = [self._seed(q, typ)]
        if not res:
            return 404, json.dumps({"code": 404, "reason": "Not Found", "message": "No results"}), {}
        return 200, json.dumps({"success": True, "duration": 0.05, "results": res}), {}

    def insights(self, p):
        if p.get("filter.type") != "urn:entity:place":
            raise _Bad("fake supports filter.type=urn:entity:place only")
        take = int(p.get("take", 20))
        if take > 50:
            raise _Bad("take must be <= 50")
        city = self._city_of(p.get("filter.location"))
        cand = [pl for pl in self.places if city is None or pl["_city"] == city]
        if p.get("filter.tags"):
            want = set(p["filter.tags"].split(","))
            op = p.get("operator.filter.tags", "union")
            cand = [pl for pl in cand if (want & {t["id"] for t in pl["tags"]}) if op == "union"
                    or want <= {t["id"] for t in pl["tags"]}]
        br = p.get("filter.properties.business_rating.min")
        if br in ("1", "2", "3", "4", "5"):  # documented enum; anything else is silently ignored here
            cand = [pl for pl in cand if pl["properties"]["business_rating"] >= float(br)]
        if p.get("filter.popularity.min"):
            cand = [pl for pl in cand if pl["popularity"] >= float(p["filter.popularity.min"])]
        if p.get("filter.popularity.max"):
            cand = [pl for pl in cand if pl["popularity"] <= float(p["filter.popularity.max"])]
        if p.get("filter.exclude.entities"):
            ex = set(p["filter.exclude.entities"].split(","))
            cand = [pl for pl in cand if pl["entity_id"] not in ex]
        if p.get("filter.results.entities"):
            keep = set(p["filter.results.entities"].split(","))
            cand = [pl for pl in cand if pl["entity_id"] in keep]
        ents = [x for x in (p.get("signal.interests.entities") or "").split(",") if x]
        tagsig = [x for x in (p.get("signal.interests.tags") or "").split(",") if x]
        if not cand and not ents and not tagsig and not p.get("filter.location") and not p.get("filter.results.entities"):
            raise _Bad("at least one valid signal or filter is required")
        seed_vecs = [(e, vec("seed:" + e)) for e in ents] + [(t, vec("tag:" + t)) for t in tagsig]
        tag_boost = {}
        for t in tagsig:
            for k, (tid, _, _, kind) in SEED_TAGS.items():
                if tid == t and kind:
                    tag_boost[t] = TAG[kind][0]
        scored = []
        for pl in cand:
            if not seed_vecs:
                a = pl["popularity"]  # fake model of the no-signal order (unknown live: K9)
                scored.append((a, pl, None))
                continue
            contrib = []
            for sid, v in seed_vecs:
                c = cos(v, pl["_vec"])
                if sid in tag_boost and any(t["id"] == tag_boost[sid] for t in pl["tags"]):
                    c += 0.8
                contrib.append((sid, c))
            taste = sum(c for _, c in contrib) / len(contrib)
            popz = (pl["popularity"] - 0.5) / 0.5
            s = (1 - self.w) * popz + self.w * (taste + 1) / 2
            a = 0.55 + 0.44 / (1 + math.exp(-4 * (s - 0.5))) + 1e-6 * h(pl["entity_id"], 8)
            expl = None
            if p.get("feature.explainability") == "true":
                pos = [(sid, max(c, 0) + 0.05) for sid, c in contrib]
                tot = sum(x for _, x in pos)
                items = [{"entity_id": sid, "score": round(x / tot, 3)} for sid, x in pos if x / tot >= 0.1]
                if h(pl["entity_id"], 10) < 0.08:
                    expl = {"warning": "explainability could not be computed for this result"}
                else:
                    expl = {"signal.interests.entities": [i for i in items if i["entity_id"] in ents],
                            "signal.interests.tags": [i for i in items if i["entity_id"] in tagsig]}
            scored.append((a, pl, expl))
        scored.sort(key=lambda x: (-x[0], x[1]["entity_id"]))
        page = int(p.get("page", 1))
        off = int(p["offset"]) if p.get("offset") else (page - 1) * take
        window = scored[off:off + take]
        body = {"success": True, "duration": 0.12,
                "results": {"entities": [self._pub(pl, round(a, 6), ex) for a, pl, ex in window]}}
        if p.get("feature.explainability") == "true" and seed_vecs:
            agg = {}
            for name, n in (("top_3", 3), ("top_5", 5), ("top_10", 10), ("all", len(window))):
                sums = {}
                for a, pl, ex in window[:n]:
                    if not ex or "warning" in ex:
                        continue
                    for lst in ex.values():
                        for it in lst:
                            sums[it["entity_id"]] = sums.get(it["entity_id"], 0) + it["score"]
                k = max(1, len([1 for _, _, ex in window[:n] if ex and "warning" not in ex]))
                agg[name] = [{"entity_id": i, "score": round(v / k, 3)} for i, v in sums.items()]
            body["query"] = {"explainability": {"signal.interests.entities": agg}}
        return 200, json.dumps(body), {}


class _Bad(Exception):
    pass
