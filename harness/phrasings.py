"""Prompt v2 phrasings for walls, taste and street asks (UNSAID.md §3.6). The 16 hidden-gem phrasings are imported
verbatim from prompts.py (the frozen census file, sha256 d831c304...); only the suffix differs (v2 vs the census v1)."""
import ast, hashlib, json, os, re

import prompts  # the census file, unchanged

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
PROMPT_V = "v2"
SUFFIX_V2 = (' Reply with only JSON: an array of up to 12 objects like '
             '{"name": "...", "neighbourhood": "..."}. Real, currently open venues only. No other text.')
CITY = {"stl": "St. Louis", "nyc": "New York"}

CITY_EXTRA = [  # the 4 non-gem city-wall phrasings, §3.6
    ("w00", "best places to eat and drink in {city}"),
    ("w01", "where do locals go to eat and drink in {city}"),
    ("w02", "not-touristy places to eat and drink in {city}"),
    ("w03", "what are the must-try restaurants in {city}"),
]
TASTE = [
    ("t1", "Where should a fan of {L1} eat and drink in {city}?"),
    ("t2", "Where should a fan of {L2} eat and drink in {city}?"),
    ("t3", "Where should a fan of {L3} eat and drink in {city}?"),
    ("t4", "I love {L1}, {L2} and {L3}. Where should I eat and drink in {city}?"),
]
STREET = "Best places to eat and drink in {hood}, {city}"  # unhinted, §3.3 step 10


def city_wall(ck):
    """20 phrasings: w00-w03, then h00-h15 = prompts.HIDDEN[i] formatted exactly as the census formatted it."""
    out = [(pid, t.format(city=CITY[ck])) for pid, t in CITY_EXTRA]
    out += [("h%02d" % i, t.format(**prompts.CITIES[ck])) for i, t in enumerate(prompts.HIDDEN)]
    return out


def taste(ck, loves):
    L = {"L%d" % (i + 1): l for i, l in enumerate(loves)}
    return [(pid, t.format(city=CITY[ck], **L)) for pid, t in TASTE if all(k in L for k in re.findall(r"\{(L\d)\}", t))]


def street(ck, hood):
    return STREET.format(hood=hood, city=CITY[ck])


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def qhash(text):
    """Hash of a question as a person would type it: case, whitespace and the JSON suffix don't count."""
    t = text.replace(SUFFIX_V2, "").replace(prompts.SUFFIX, "")
    t = re.sub(r"\s+", " ", t.strip().lower())
    return hashlib.sha256(t.encode()).hexdigest()


SETS_SOURCES = [os.path.join(REPO, "data", "sets.json"), os.path.join(REPO, "data", "sets.draft.json")]


def load_sets_meta(path=None):
    """The preset sets, from (in order) --sets-file, data/sets.json (frozen), data/sets.draft.json (Agent E's draft),
    else engine/unsaid/seeds.py SEED_SETS (read with ast, never imported).
    Returns ({city: [(sid, [love text, ...])]}, {sids marked try_these}, source path)."""
    src = path or next((p for p in SETS_SOURCES if os.path.exists(p)), None)
    if src:
        raw = json.load(open(src))
        if isinstance(raw, dict) and isinstance(raw.get("sets"), list):  # Agent E's format
            out, tt = {}, set()
            for x in raw["sets"]:
                out.setdefault(x["city"], []).append((x["id"], [l[0] if isinstance(l, list) else l for l in x["loves"]]))
                if x.get("try_these"):
                    tt.add(x["id"])
            return out, tt, src
    else:
        src = os.path.join(REPO, "engine", "unsaid", "seeds.py")
        raw = None
        for node in ast.parse(open(src).read()).body:
            if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "SEED_SETS":
                raw = ast.literal_eval(node.value)
    return {ck: [(sid, [l[0] for l in loves]) for sid, loves in v] for ck, v in raw.items()}, set(), src


def load_sets(path=None):
    return load_sets_meta(path)[0]


def all_wall_hashes(sets=None, hoods=None):
    """Every question text the walls and census ever ask: the fresh-ask guard compares against these."""
    hs = {qhash(a["phrasing"]) for a in json.load(open(os.path.join(HERE, "asks.json")))}
    sets = sets or load_sets()
    for ck in CITY:
        hs |= {qhash(t) for _, t in city_wall(ck)}
        for _, loves in sets.get(ck, []):
            hs |= {qhash(t) for _, t in taste(ck, loves)}
        for h in (hoods or {}).get(ck, []):
            hs.add(qhash(street(ck, h)))
    return hs
