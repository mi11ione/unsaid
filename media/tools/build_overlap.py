"""How much similar and unrelated tastes share: card overlaps between the St. Louis preset sets, for the line on the
site's "Is this just obscure places?" sheet. Reads the regenerated store (REGEN_FRESH, default
~/Desktop/qloo/private/fresh20-28oct, written by engine/regen_try.sh); writes site/data/overlap.json (counts only).
  python3 -I media/tools/build_overlap.py          (deploy-site.sh runs it when the store exists)"""
import itertools, json, os, sys

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
FRESH = os.environ.get("REGEN_FRESH") or os.path.expanduser("~/Desktop/qloo/private/fresh20-28oct")
# the soul and hip-hop sets (data/sets.json loves: Frankie Beverly & Maze, SZA, Jay-Z, Nelly)
CLUSTER = {"label": "soul and hip-hop", "ids": ["stl-cedric", "stl-sza", "stl-jayz", "stl-nelly"]}
if not os.path.exists(os.path.join(FRESH, "index.json")):
    sys.exit("no store at %s" % FRESH)
idx = json.load(open(os.path.join(FRESH, "index.json")))
cards = {s["id"]: {c["id"] for c in json.load(open(os.path.join(FRESH, s["file"])))["result"]["picks"]}
         for s in idx["sets"] if s["id"].startswith("stl-")}
assert all(i in cards for i in CLUSTER["ids"]), sorted(cards)
inside = [len(cards[a] & cards[b]) for a, b in itertools.combinations(CLUSTER["ids"], 2)]
others = [k for k in cards if k not in CLUSTER["ids"]]
across = [len(cards[a] & cards[b]) for a in CLUSTER["ids"] for b in others]
out = {"_": "Shared cards between St. Louis preset sets (7 cards each), from %s via media/tools/build_overlap.py" % os.path.basename(FRESH),
       "city": "St. Louis", "sets": len(cards), "cluster": CLUSTER["label"], "cluster_n": len(CLUSTER["ids"]),
       "cluster_min": min(inside), "cluster_max": max(inside), "across_min": min(across), "across_max": max(across)}
json.dump(out, open(os.path.join(ROOT, "site", "data", "overlap.json"), "w"), indent=1)
print("site/data/overlap.json:", {k: v for k, v in out.items() if k != "_"})
