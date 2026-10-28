"""Per-city "everyone's taste" prior (diversity, 28 Oct): how well each place fits ANY taste. For every preset set
(data/sets.json; plus anchor sets if given) it takes the set's pool U and its for-you order (RRF over the live loves'
C6' ranks: the same numbers the engine computes) and stores each place's fit percentile in U. At query time
the engine averages a place's percentiles over the sets that share no love with the query (leave-one-out), turns
that into a percentile within the query's U, and subtracts the larger of it and popularity from the place's fit.

  python3 -I build_priors.py --budget 0                     # from the cached C6' data of the 20 sets
  python3 -I build_priors.py --anchors anchors.json --budget 400

Output: data/priors/<city>.json {"city", "built_at", "engine_v", "method", "sets": [{"id", "loves": [{"id","label"}],
"U", "fit_pct": {qloo_id: pct}}]}. It holds Qloo-derived numbers keyed by Qloo IDs, so data/priors/ is gitignored
(UNSAID.md §5.2) and ships the way the live results do."""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from unsaid import cli, engine as E, seeds as SD, stats as ST  # noqa: E402

ap = cli.parser(__doc__)
ap.add_argument("--anchors", help='JSON [{"id", "city", "loves": [["text", "hint"], ...]}] extra diverse sets')
ap.add_argument("--out", default=os.path.join(cli.DATA, "priors"))
args = ap.parse_args()
q = cli.client(args, "build_priors")
E.CFG["CAP_ENABLED"] = False
jobs = [(c, sid, spec, "preset") for c in cli.cities(args) for sid, spec in SD.SEED_SETS.get(c, [])]
if args.anchors:
    with open(args.anchors) as f:
        jobs += [(a["city"], a["id"], [tuple(x) for x in a["loves"]], "anchor") for a in json.load(f)]
out = {}
for city, sid, spec, kind in jobs:
    if city not in cli.cities(args):
        continue
    c = cli.city_obj(q, city)
    loves = cli.loves(q, spec)
    if loves is None:
        print("  %s/%s: a love is not in Qloo; skipped" % (city, sid))
        continue
    r = E.run(q, c, loves, {"answers": [], "source": "none (prior: fit only)"}, street_check=None)
    if not r.get("_U"):
        print("  %s/%s: %s; skipped" % (city, sid, r["status"]))
        continue
    fit, N = r["_R"]["fit"], r["_R"]["N"]
    live = set(r["diag"].get("loves_live") or [])
    rec = {"id": sid, "kind": kind, "U": N,
           "loves": [{"id": l["id"], "label": l.get("name") or l["text"], "live": l["text"] in live} for l in loves],
           "fit_pct": {i: round(ST.pct(fit[i], N), 4) for i in fit}}
    if not live:
        print("  %s/%s: no live love; skipped (it would be popularity, not taste)" % (city, sid))
        continue
    out.setdefault(city, []).append(rec)
    print("  %s/%-18s %-6s U %3d, live loves %d" % (city, sid, kind, N, len(live)))
os.makedirs(args.out, exist_ok=True)
for city, sets in out.items():
    places = {}
    for s in sets:
        for i in s["fit_pct"]:
            places[i] = places.get(i, 0) + 1
    doc = {"city": city, "built_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "engine_v": E.ENGINE_V,
           "method": "per set: percentile of each place in that set's pool under its for-you order (RRF of the live "
                     "loves' C6' ranks); a query averages the sets sharing no love with it",
           "qloo_calls": q.calls["network"], "places": len(places),
           "places_in_3plus_sets": sum(1 for v in places.values() if v >= 3), "sets": sets}
    with open(os.path.join(args.out, "%s.json" % city), "w") as fh:
        json.dump(doc, fh)
    print("%s: %d sets, %d places (%d in 3+ sets) -> %s" % (city.upper(), len(sets), len(places),
                                                           doc["places_in_3plus_sets"], os.path.join(args.out, city + ".json")))
gi = os.path.join(args.out, ".gitignore")
if not os.path.exists(gi):
    with open(gi, "w") as fh:
        fh.write("# Qloo-derived numbers keyed by Qloo IDs: never in git (UNSAID.md 5.2)\n*.json\n")
cli.finish(q, args, "build_priors")
