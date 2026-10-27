"""K8 exists: is Qloo's is_closed true for three venues confirmed closed (unsaid-v2.md §3 E7)?
  Sweetie Pie's (last STL location closed Sep 2022), Mike Shannon's Steaks & Seafood (downtown, closed 30 Jan 2016),
  Grace Meat + Three, the Grove (closed 13 Sep 2026: the freshness test).
PASS per venue: not found in St. Louis, or found with is_closed=true. FAIL: found and is_closed is false/absent.
Also checks whether each would enter the pool (rescored with the pool's filters: business_rating >= 4, kind tags)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from unsaid import cli, engine as E, matcher as M  # noqa: E402
from unsaid.qloo import prop  # noqa: E402

VENUES = ["Sweetie Pie's", "Mike Shannon's Steaks and Seafood", "Grace Meat + Three"]
args = cli.parser(__doc__).parse_args()
q = cli.client(args, "k8_closed")
c = cli.city_obj(q, "stl")
loc = "%s,%s" % (c["lat"], c["lon"])
oks = []
for v in VENUES:
    res = q.search(v, types=E.PLACE, take=5, location=loc, radius_mi=25, label="K8 search")
    best = next((r for r in res if M.strong(v, r.get("name", ""))), None)
    if best is None:
        print("  %-34s not found near St. Louis (top: %s) -> PASS%s" % (v, [r.get("name") for r in res[:3]], cli.tag(args)))
        oks.append(True)
        continue
    closed = prop(best, "is_closed")
    p = E.base_filters(c, [])
    p["filter.results.entities"] = [best["entity_id"]]
    p["take"] = 5
    inpool = bool((q.insights(p, label="K8 pool check").get("results") or {}).get("entities"))
    ok = closed is True
    oks.append(ok)
    print("  %-34s -> %s [%s] is_closed=%s rating=%s; passes pool filters: %s -> %s%s" % (
        v, best.get("name"), best["entity_id"][:8], closed, prop(best, "business_rating"), inpool, cli.verdict(ok), cli.tag(args)))
print("K8 is_closed: %d of 3 -> %s%s" % (sum(oks), cli.verdict(all(oks)), cli.tag(args)),
      "| fallback: 'last seen' check on the 7 survivors only (website reachable + hours present), card reads 'checked <date>'")
cli.finish(q, args, "k8_closed")
