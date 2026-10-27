"""The preset sets. Source, in order (the same files agent B's harness reads):
  data/sets.json (frozen) -> data/sets.draft.json (draft) -> FALLBACK_SETS below.
File format: {"sets": [{"id": "stl-cedric", "label", "city": "stl", "try_these": bool,
                        "loves": [["Frankie Beverly & Maze", "artist"], ...]}]}
loves are (text, type hint); hint None lets /search decide; "tag" goes straight to /v2/tags.
Ids look like "stl-cedric". Old ids stay aliases: "cedric", "jason" (-> stl-*), "A" (-> nyc-khruangbin), and any
bare suffix resolves to "<city>-<suffix>" when that set exists."""
import json
import os

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(os.path.dirname(KIT), "data")
SOURCES = [os.path.join(DATA, "sets.json"), os.path.join(DATA, "sets.draft.json")]

FALLBACK_SETS = {   # only when neither data file exists
    "nyc": [
        ("nyc-khruangbin", [("Khruangbin", "artist"), ("The Grand Budapest Hotel", "movie"), ("Ten Bells", "place")]),
        ("nyc-B", [("Radiohead", "artist"), ("Lost in Translation", "movie"), ("Norwegian Wood", "book")]),
        ("nyc-badbunny", [("Bad Bunny", "artist"), ("Narcos", "tv_show"), ("tacos al pastor", "tag")]),
        ("nyc-D", [("Taylor Swift", "artist"), ("Gilmore Girls", "tv_show"), ("Levain Bakery", "place")]),
        ("nyc-kendrick", [("Kendrick Lamar", "artist"), ("Atlanta", "tv_show"), ("Popeyes", "brand")]),
        ("nyc-F", [("Phoebe Bridgers", "artist"), ("Lady Bird", "movie"), ("natural wine", "tag")]),
        ("nyc-G", [("Frank Sinatra", "artist"), ("The Godfather", "movie"), ("Carbone", "place")]),
        ("nyc-H", [("Beyonce", "artist"), ("Insecure", "tv_show"), ("Sweetgreen", "brand")]),
        ("nyc-I", [("Bob Dylan", "artist"), ("Inside Llewyn Davis", "movie"), ("Joe's Pizza", "place")]),
        ("nyc-J", [("Daft Punk", "artist"), ("Blade Runner 2049", "movie"), ("ramen", "tag")]),
    ],
    "stl": [
        ("stl-cedric", [("Frankie Beverly & Maze", "artist"), ("The Original Kings of Comedy", "movie"), ("rib tips", "tag")]),
        ("stl-jason", [("Frank Sinatra", "artist"), ("Rounders", "movie"), ("Carbone", "place")]),
        ("stl-cedric2", [("Al Green", "artist"), ("Barbershop", "movie"), ("rib tips", "tag")]),
        ("stl-cedric3", [("Frankie Beverly & Maze", "artist"), ("The Neighborhood", "tv_show"), ("Joe Turner's Come and Gone", None)]),
        ("stl-cedric4", [("The Original Kings of Comedy", "movie"), ("Al Green", "artist"), ("soul food", "tag")]),
        ("stl-nelly", [("Nelly", "artist"), ("The Blues Brothers", "movie"), ("toasted ravioli", "tag")]),
        ("stl-taylorswift", [("Taylor Swift", "artist"), ("Ted Lasso", "tv_show"), ("Starbucks", "brand")]),
        ("stl-jayz", [("Jay-Z", "artist"), ("Paid in Full", "movie"), ("Budweiser", "brand")]),
        ("stl-wilco", [("Wilco", "artist"), ("Lady Bird", "movie"), ("natural wine", "tag")]),
        ("stl-kendrick", [("Kendrick Lamar", "artist"), ("Atlanta", "tv_show"), ("Popeyes", "brand")]),
    ],
    "la": [
        ("la-cedric", [("Frankie Beverly & Maze", "artist"), ("The Original Kings of Comedy", "movie"), ("rib tips", "tag")]),
    ],
}
ALIASES = {"cedric": "stl-cedric", "jason": "stl-jason", "A": "nyc-khruangbin"}
CITY_QUERY = {"nyc": ("New York City", "New York"), "stl": ("St. Louis", "Missouri"), "la": ("Los Angeles", "California")}


def _load():
    src = next((p for p in SOURCES if os.path.exists(p)), None)
    if src:
        try:
            with open(src) as f:
                raw = json.load(f)
            items = raw["sets"] if isinstance(raw, dict) else raw
            sets, meta = {}, {}
            for x in items:
                loves = [tuple(l) if isinstance(l, list) else (l, None) for l in x["loves"]]
                loves = [(l[0], l[1] if len(l) > 1 else None) for l in loves]
                sets.setdefault(x["city"], []).append((x["id"], loves))
                meta[x["id"]] = {"label": x.get("label"), "city": x["city"], "try_these": bool(x.get("try_these"))}
            sets.setdefault("la", FALLBACK_SETS["la"])
            return sets, meta, src
        except (OSError, ValueError, KeyError, TypeError):
            pass
    meta = {sid: {"label": None, "city": c, "try_these": False} for c, v in FALLBACK_SETS.items() for sid, _ in v}
    return FALLBACK_SETS, meta, "engine/unsaid/seeds.py FALLBACK_SETS"


SEED_SETS, SET_META, SOURCE = _load()


def resolve(city, sid):
    """Any accepted id -> the canonical set id in SEED_SETS[city], or None."""
    have = [s for s, _ in SEED_SETS.get(city, [])]
    for cand in (sid, ALIASES.get(sid), "%s-%s" % (city, sid)):
        if cand in have:
            return cand
    return None


def get(city, sid):
    c = resolve(city, sid)
    if c is None:
        raise KeyError("%s/%s (sets from %s)" % (city, sid, SOURCE))
    return dict(SEED_SETS[city])[c]


def same(a, b, city=None):
    """Do two set ids name the same set (aliases and the city prefix folded)?"""
    if a is None or b is None:
        return False
    if a == b:
        return True
    fold = lambda s: ALIASES.get(s, s).split("-", 1)[1] if "-" in ALIASES.get(s, s) else ALIASES.get(s, s)  # noqa
    return fold(a) == fold(b)


STRANGERS = ("stl", resolve("stl", "cedric") or "stl-cedric", resolve("stl", "jason") or "stl-jason")
