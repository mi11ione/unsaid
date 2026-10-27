"""Wall sources: the AI answers whose names get struck.

Default (day 1, before the consensus harness exists): research/exp/consensus.py, i.e. one model from memory,
8 phrasings, read with ast (never executed). For sets without their own lists the wall is the city's 4 generic
answers only, labelled so. Live: pass --walls <file.json> in the harness contract:
{"walls": [{"city": "stl", "set": "cedric", "answers": [{"provider": "openai", "model": "...", "phrasing": "best",
  "asked_at": "2026-10-28T14:02:00Z", "names": [{"name": "Pappy's Smokehouse", "neighbourhood": "Midtown"}]}]}]}
"""
import ast
import json
import os

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONSENSUS = os.environ.get("UNSAID_CONSENSUS") or os.path.join(KIT, "..", "..", "..", "exp", "consensus.py")


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
    return [{"provider": "exp-memory", "model": "frontier (from memory, no search)", "phrasing": k,
             "asked_at": "2026-10-27", "names": [{"name": n} for n in v], "source": source} for k, v in d.items()]


def wall_for(city, sid, walls_file=None):
    if walls_file:
        with open(walls_file) as f:
            data = json.load(f)
        for w in data.get("walls", []):
            if w["city"] == city and w["set"] == sid:
                return {"answers": w["answers"], "source": walls_file}
    e = _exp()
    generic = lambda D: {k: v for k, v in D.items() if k[:2] in ("P1", "P2", "P3", "P4")}
    if city == "nyc" and sid == "A":
        return {"answers": _answers(e["NYC"], "exp NYC case A"), "source": "exp/consensus.py NYC (8 answers)"}
    if city == "stl" and sid == "cedric":
        return {"answers": _answers(e["STL"], "exp STL Cedric"), "source": "exp/consensus.py STL Cedric (8 answers)"}
    if city == "stl" and sid == "jason":
        d = dict(generic(e["STL"]))
        d.update(e["JASON_STL"])
        return {"answers": _answers(d, "exp STL Jason"), "source": "exp/consensus.py STL Jason (8 answers)"}
    base = e["NYC"] if city == "nyc" else e["STL"]
    return {"answers": _answers(generic(base), "exp generic"),
            "source": "exp/consensus.py %s generic only (4 answers; taste phrasings not yet asked)" % city.upper()}


def fresh_for(city):
    e = _exp()
    return _answers(e["NYC_FRESH" if city == "nyc" else "STL_FRESH"], "exp fresh")


def names(wall):
    out = []
    for a in wall["answers"]:
        for n in a["names"]:
            out.append(n["name"] if isinstance(n, dict) else n)
    return out
