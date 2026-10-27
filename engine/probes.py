"""Day-0 parameter probes (run first, ~25 calls). Each prints what the live API actually does, so the engine's
adaptive choices are confirmed before the kill tests spend quota.
 P1 paging: does `page` work for places (it is not in the place guide; `offset` is)?
 P2 business_rating.min: enum 1..5; what does 4.3 do (applied, rounded, ignored, 400)?
 P3 field paths: where are is_closed, business_rating, neighborhood, popularity, affinity, explainability?
 P4 filter.results.entities: all IDs back? order? and with no signal at all?
 P5 bias.trends: does `off` vs default change the top 50?
 P6 tags: is restaurant hierarchical (does it include ...:restaurant:bar)? which bar tag exists?
 P7 explainability: per-result and aggregate shapes (dumped to out/probe_explain.json)."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from unsaid import cli, engine as E, stats as ST  # noqa: E402
from unsaid.qloo import QlooError, affinity, prop  # noqa: E402

args = cli.parser(__doc__).parse_args()
q = cli.client(args, "probes")
c = cli.city_obj(q, "nyc")
print("  city: %s %s (%s)" % (c["name"], c["id"][:8], c["disamb"]))
loves = [E.resolve_love(q, "Khruangbin", "artist"), E.resolve_love(q, "The Grand Budapest Hotel", "movie")]
print("  loves: %s" % [(l["text"], l.get("name"), (l.get("id") or "")[:8], l["status"]) for l in loves])
base = E.base_filters(c, loves)
base.update(E.signal(loves))
base["take"] = 50


def ids_of(p, label):
    try:
        d = q.insights(p, label=label)
    except QlooError as e:
        return None, e.status
    return [e["entity_id"] for e in (d.get("results") or {}).get("entities") or []], d


p1, _ = ids_of(dict(base, page=1), "P1 page1")
p2, _ = ids_of(dict(base, page=2), "P1 page2")
o2, _ = ids_of(dict(base, offset=50), "P1 offset50")
print("  P1 paging: page2 vs page1 overlap %d/50; offset=50 vs page2 identical: %s -> use %s" % (
    len(set(p1 or []) & set(p2 or [])), p2 == o2, "page" if p1 and p2 and not set(p1) & set(p2) else "offset"))
r = {}
for v in (None, 4, 4.3, 5):
    p = dict(base)
    p.pop("filter.properties.business_rating.min", None)
    if v is not None:
        p["filter.properties.business_rating.min"] = v
    ids, d = ids_of(p, "P2 rating=%s" % v)
    if ids is None:
        r[v] = "HTTP %s" % d
        continue
    rs = [prop(e, "business_rating") for e in (d.get("results") or {}).get("entities") or []]
    rs = [x for x in rs if x is not None]
    r[v] = "min rating %s, %d results" % (min(rs) if rs else None, len(ids))
print("  P2 business_rating.min: " + "; ".join("%s -> %s" % kv for kv in r.items()))
d = q.insights(dict(base, page=1, **{"feature.explainability": True}), label="P3/P7 explain")
e0 = ((d.get("results") or {}).get("entities") or [{}])[0]
paths = {}
for f in ("is_closed", "business_rating", "neighborhood", "popularity"):
    paths[f] = ("properties.%s" % f if f in (e0.get("properties") or {}) else
                "properties.geocode.%s" % f if f in ((e0.get("properties") or {}).get("geocode") or {}) else
                f if f in e0 else "ABSENT")
paths["affinity"] = "query.affinity" if (e0.get("query") or {}).get("affinity") is not None else (
    "affinity" if "affinity" in e0 else "ABSENT")
paths["explainability"] = "query.explainability" if (e0.get("query") or {}).get("explainability") is not None else "ABSENT"
paths["aggregate"] = "query.explainability (top level)" if (d.get("query") or {}).get("explainability") else "ABSENT"
print("  P3 field paths: %s" % paths)
os.makedirs(cli.OUT, exist_ok=True)
with open(os.path.join(cli.OUT, "probe_explain%s.json" % (".fake" if args.fake else "")), "w") as fh:
    json.dump({"first_result_query": e0.get("query"), "top_level_query": d.get("query")}, fh, indent=1)
print("  P7 explainability shapes dumped to out/probe_explain*.json")
sub = (p1 or [])[:30]
pr = dict(E.base_filters(c, loves), **{"filter.results.entities": sorted(sub), "take": 50})
withsig, _ = ids_of(dict(pr, **E.signal(loves)), "P4 results+signal")
nosig, dn = ids_of(pr, "P4 results nosignal")
print("  P4 filter.results.entities: with signal %s/30 back; no signal %s/30 back" % (
    len(withsig or []), len(nosig or []) if nosig is not None else "HTTP %s" % dn))
if nosig:
    affs = [affinity(e) for e in (dn.get("results") or {}).get("entities") or []]
    pops = {e["entity_id"]: e.get("popularity") or 0 for e in (dn.get("results") or {}).get("entities") or []}
    rk = {i: k + 1 for k, i in enumerate(nosig)}
    print("     no-signal: %d distinct affinities; rho(order, popularity) = %s" % (
        len(set(affs)), cli.f(ST.spearman(rk, ST.rank(pops)))))
off, _ = ids_of(dict(base, page=1, **{"bias.trends": "off"}), "P5 trends off")
dflt = dict(base, page=1)
dflt.pop("bias.trends")
dd, _ = ids_of(dflt, "P5 trends default")
print("  P5 bias.trends: off vs default top-50 overlap %d/50, same order: %s" % (len(set(off or []) & set(dd or [])), off == dd))
rest, _ = ids_of(dict(base, page=1, **{"filter.tags": ["urn:tag:genre:place:restaurant"]}), "P6 restaurant only")
barr, _ = ids_of(dict(base, page=1, **{"filter.tags": ["urn:tag:genre:place:restaurant:bar"]}), "P6 bar only")
print("  P6 tags: restaurant-only %d, restaurant:bar-only %d, overlap %d (high overlap => hierarchical); bar tags: %s" % (
    len(rest or []), len(barr or []), len(set(rest or []) & set(barr or [])),
    [t.get("id") for t in q.tags("bar", tag_types=["urn:tag:category:place"], label="P6 tags")][:3]))
cli.finish(q, args, "probes")
