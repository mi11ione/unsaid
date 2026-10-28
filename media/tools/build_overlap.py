"""How much similar and other tastes share: card overlaps between preset sets in the same city, for the line on the
site's "Is this just obscure places?" sheet. Reads the regenerated store (REGEN_FRESH, default
~/Desktop/qloo/private/fresh20-28oct, written by engine/regen_try.sh); writes site/data/overlap.json (counts only).
  python3 -I media/tools/build_overlap.py          (deploy-site.sh runs it when the store exists)"""
import itertools, json, os, statistics, sys

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
FRESH = os.environ.get("REGEN_FRESH") or os.path.expanduser("~/Desktop/qloo/private/fresh20-28oct")
# the two clusters of similar tastes among the St. Louis presets (data/sets.json loves): soul and hip-hop
# (Frankie Beverly & Maze, SZA, Jay-Z, Nelly) and indie (Wilco, Big Thief). "Other pairs" excludes every pair inside
# either cluster, so the baseline is unrelated tastes only.
CLUSTERS = [{"label": "soul and hip-hop", "ids": ["stl-cedric", "stl-sza", "stl-jayz", "stl-nelly"]},
            {"label": "indie", "ids": ["stl-wilco", "stl-bigthief"]}]
if not os.path.exists(os.path.join(FRESH, "index.json")):
    sys.exit("no store at %s" % FRESH)
idx = json.load(open(os.path.join(FRESH, "index.json")))
cards = {s["id"]: {c["id"] for c in json.load(open(os.path.join(FRESH, s["file"])))["result"]["picks"]} for s in idx["sets"]}
for C in CLUSTERS:
    assert all(i in cards for i in C["ids"]), sorted(cards)
    inside = [len(cards[a] & cards[b]) for a, b in itertools.combinations(C["ids"], 2)]
    C.update({"n": len(C["ids"]), "min": min(inside), "max": max(inside)})
same_cluster = lambda a, b: any(a in C["ids"] and b in C["ids"] for C in CLUSTERS)
# every other pair of sets in the same city: an honest baseline of unrelated tastes, not a chosen contrast
city = lambda k: k.split("-")[0]
pairs = [(a, b) for a, b in itertools.combinations(sorted(cards), 2) if city(a) == city(b) and not same_cluster(a, b)]
rest = sorted(len(cards[a] & cards[b]) for a, b in pairs)
top = max(pairs, key=lambda p: len(cards[p[0]] & cards[p[1]]))
out = {"_": "Shared cards between preset sets in the same city (7 cards each), from %s via media/tools/build_overlap.py; "
            "other_* = every same-city pair outside both clusters" % os.path.basename(FRESH),
       "city": "St. Louis", "sets": len(cards),
       "clusters": [{"label": C["label"], "ids": C["ids"], "n": C["n"], "min": C["min"], "max": C["max"]} for C in CLUSTERS],
       "other_pairs": len(rest), "other_median": statistics.median(rest), "other_max": max(rest), "other_max_pair": list(top)}
json.dump(out, open(os.path.join(ROOT, "site", "data", "overlap.json"), "w"), indent=1)
print("site/data/overlap.json:", {k: v for k, v in out.items() if k != "_"})
