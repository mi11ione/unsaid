"""Wall sources: the AI answers whose names get struck (UNSAID.md §3.6).

The wall struck for a set = every name in the city wall, every name in that city's census answers, and the set's
taste answers. With --walls <file.json> (the harness contract, kit/unsaid/walls.py + `lane`):
{"walls": [{"city": "stl", "set": "cedric" | "city" | "census", "answers": [{"provider": "openai", "model": "...",
  "phrasing_id": "g01", "phrasing": "best places to eat and drink in {city}", "asked_at": "2026-10-28T14:02:00Z",
  "lane": "dated", "raw": "<the answer text, for the reverse check>",
  "names": [{"name": "Pappy's Smokehouse", "neighbourhood": "Midtown"}]}]}]}
Entries whose `set` is one of GENERIC_SETS apply to every set in that city.
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


def load_file(walls_file):
    with open(walls_file) as f:
        return json.load(f)


def wall_for(city, sid, walls_file=None):
    city = _ckey(city)
    if walls_file:
        data = load_file(walls_file)
        answers, sets = [], []
        for w in data.get("walls", []):
            if _ckey(w.get("city")) != city:
                continue
            if w.get("set") in GENERIC_SETS or (sid is not None and w.get("set") == sid):
                answers += w.get("answers") or []
                sets.append(w.get("set") or "city")
        return {"answers": answers, "source": "%s (%s: %s)" % (os.path.basename(walls_file), city, ", ".join(sets) or "none")}
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


def taste_answers(city, sid, walls_file=None):
    """Only a set's taste answers: the two-strangers repeat count never uses the shared generic wall."""
    if walls_file:
        data = load_file(walls_file)
        return [a for w in data.get("walls", []) if _ckey(w.get("city")) == _ckey(city) and w.get("set") == sid
                for a in w.get("answers") or []]
    w = wall_for(city, sid)
    return [a for a in w["answers"] if str(a.get("phrasing", ""))[:2] in ("P5", "P6", "P7", "P8")]


def fresh_for(city):
    e = _exp()
    return _answers(e["NYC_FRESH" if _ckey(city) == "nyc" else "STL_FRESH"], "exp fresh")


def names(wall):
    out = []
    for a in wall["answers"]:
        for n in a.get("names") or []:
            out.append(n["name"] if isinstance(n, dict) else n)
    return out
