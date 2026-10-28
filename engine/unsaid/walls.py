"""Wall sources: the AI answers whose names get struck (UNSAID.md §3.6).

The wall struck for a set = every name in the city wall, every name in that city's census answers, and the set's
taste answers. With --walls <file.json> (the harness contract, kit/unsaid/walls.py + `lane`):
{"walls": [{"city": "stl", "set": "cedric" | "city" | "census", "answers": [{"provider": "openai", "model": "...",
  "phrasing_id": "g01", "phrasing": "best places to eat and drink in {city}", "asked_at": "2026-10-28T14:02:00Z",
  "lane": "dated", "raw": "<the answer text, for the reverse check>",
  "names": [{"name": "Pappy's Smokehouse", "neighbourhood": "Midtown"}]}]}]}
Entries whose `set` is one of GENERIC_SETS apply to every set in that city. A set's taste entry joins by set id
(aliases folded: "cedric" == "stl-cedric") and also by its `loves` (order-free, normalised), which the harness writes
on every taste entry, so a fresh love set that equals a preset set gets that set's taste answers.
Without a file (day 1): fixtures/consensus.py, one model from memory, 8 phrasings, read with ast (never executed),
dated 2026-10-27. Sets without their own lists get the city's 4 generic answers only, labelled so.
"""
import ast
import json
import os

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONSENSUS = os.environ.get("UNSAID_CONSENSUS") or os.path.join(KIT, "fixtures", "consensus.py")
GENERIC_SETS = {None, "", "*", "city", "_city", "generic", "census", "__generic__"}
CITY_ALIASES = {"st-louis": "stl", "new-york": "nyc", "los-angeles": "la"}


def _exp():
    with open(CONSENSUS) as f:
        tree = ast.parse(f.read())
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and isinstance(node.value, ast.Dict):
            try:
                out[node.targets[0].id] = ast.literal_eval(node.value)
            except ValueError:
                pass
    return out


def _answers(d, source):
    return [{"provider": "exp-memory", "model": "frontier (from memory, no search)", "phrasing": k, "phrasing_id": k,
             "asked_at": "2026-10-27", "lane": "dated", "names": [{"name": n} for n in v], "source": source}
            for k, v in d.items()]


def _ckey(city):
    return CITY_ALIASES.get(city, city)


_LOADED = {}


def load_file(walls_file):
    """One walls JSON, or a directory of them (data/walls/: wall-N.json + census.json), merged like the server does.
    Parsed once per (path, file mtimes): the answers are shared and read-only."""
    paths = ([os.path.join(walls_file, f) for f in sorted(os.listdir(walls_file)) if f.endswith(".json")]
             if os.path.isdir(walls_file) else [walls_file])
    key = (os.path.abspath(walls_file), tuple((p, os.path.getmtime(p)) for p in paths))
    if key not in _LOADED:
        _LOADED.clear()
        _LOADED[key] = _load_file(walls_file)
    return _LOADED[key]


def _load_file(walls_file):
    if os.path.isdir(walls_file):
        out = {"walls": []}
        for fn in sorted(os.listdir(walls_file)):
            if fn.endswith(".json"):
                with open(os.path.join(walls_file, fn)) as f:
                    out["walls"] += json.load(f).get("walls", [])
        return out
    with open(walls_file) as f:
        return json.load(f)


def _love_key(loves):
    from unsaid.matcher import norm
    out = []
    for l in loves or []:
        t = l[0] if isinstance(l, (list, tuple)) else (l.get("text") or l.get("label")) if isinstance(l, dict) else l
        out.append(norm(str(t)))
    return tuple(sorted(out))


def _same_set(a, b):
    from unsaid.seeds import same
    return same(a, b)


def wall_for(city, sid, walls_file=None, loves=None):
    """loves: the set's love texts (or (text, hint) pairs), for the join by loves."""
    city = _ckey(city)
    lk = _love_key(loves) if loves else None
    if walls_file:
        data = load_file(walls_file)
        answers, sets = [], []
        for w in data.get("walls", []):
            if _ckey(w.get("city")) != city:
                continue
            by_id = sid is not None and _same_set(w.get("set"), sid)
            by_loves = lk is not None and w.get("loves") and _love_key(w["loves"]) == lk
            if w.get("set") in GENERIC_SETS or by_id or by_loves:
                answers += w.get("answers") or []
                sets.append((w.get("set") or "city") + ("" if w.get("set") in GENERIC_SETS or by_id else " (by loves)"))
        return {"answers": answers, "source": "%s (%s: %s)" % (os.path.basename(walls_file), city, ", ".join(sets) or "none")}
    from unsaid.seeds import ALIASES
    sid = ALIASES.get(sid, sid)
    sid = {"nyc-khruangbin": "A", "stl-cedric": "cedric", "stl-jason": "jason"}.get(sid, sid)
    e = _exp()
    generic = lambda D: {k: v for k, v in D.items() if k[:2] in ("P1", "P2", "P3", "P4")}  # noqa: E731
    if city == "nyc" and sid == "A":
        return {"answers": _answers(e["NYC"], "exp NYC case A"), "source": "fixtures/consensus.py NYC (8 answers)"}
    if city == "stl" and sid == "cedric":
        return {"answers": _answers(e["STL"], "exp STL Cedric"), "source": "fixtures/consensus.py STL Cedric (8 answers)"}
    if city == "stl" and sid == "jason":
        d = dict(generic(e["STL"]))
        d.update(e["JASON_STL"])
        return {"answers": _answers(d, "exp STL Jason"), "source": "fixtures/consensus.py STL Jason (8 answers)"}
    if city not in ("nyc", "stl"):
        return {"answers": [], "source": "no wall for %s (fixtures cover NYC and STL)" % city}
    base = e["NYC"] if city == "nyc" else e["STL"]
    return {"answers": _answers(generic(base), "exp generic"),
            "source": "fixtures/consensus.py %s generic only (4 answers; taste phrasings not yet asked)" % city.upper()}


def snapshot(wall):
    """A short hash of the assembled wall (every answer's provider, phrasing, time and names), so two results can be
    compared: the same counts.wall needs the same snapshot (UNSAID.md §3.5 result key)."""
    import hashlib
    rows = sorted(json.dumps([a.get("provider"), a.get("phrasing_id") or a.get("phrasing"), a.get("asked_at"),
                              [n["name"] if isinstance(n, dict) else n for n in a.get("names") or a.get("places") or []]],
                             sort_keys=True, ensure_ascii=False) for a in wall.get("answers") or [])
    return hashlib.sha256("\n".join(rows).encode()).hexdigest()[:12]


def taste_answers(city, sid, walls_file=None, loves=None):
    """Only a set's taste answers: the two-strangers repeat count never uses the shared generic wall."""
    if walls_file:
        data = load_file(walls_file)
        lk = _love_key(loves) if loves else None
        return [a for w in data.get("walls", []) if _ckey(w.get("city")) == _ckey(city)
                and w.get("set") not in GENERIC_SETS
                and (_same_set(w.get("set"), sid) or (lk and w.get("loves") and _love_key(w["loves"]) == lk))
                for a in w.get("answers") or []]
    w = wall_for(city, sid)
    return [a for a in w["answers"] if str(a.get("phrasing", ""))[:2] in ("P5", "P6", "P7", "P8")]


def fresh_for(city):
    e = _exp()
    return _answers(e["NYC_FRESH" if _ckey(city) == "nyc" else "STL_FRESH"], "exp fresh")


def names(wall):
    out = []
    for a in wall["answers"]:
        for n in a.get("names") or a.get("places") or []:
            out.append(n["name"] if isinstance(n, dict) else n)
    return out
