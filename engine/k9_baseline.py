"""K9 baseline: does the no-signal call with filter.results.entities (same filters as the pool) return every ID,
in a real order? Checks coverage, distinct affinities, anchor drift across chunks, and rho with the popularity field.
Decision printed: rescoring baseline, or the popularity field (0 calls) when they are the same order (rho >= 0.98)
or when rescoring fails. Also tries the whole U in ONE filter.results.entities list paged by take=50 (URL ~7.5 KB)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from unsaid import cli, engine as E, stats as ST  # noqa: E402
from unsaid.qloo import QlooError, affinity  # noqa: E402

args = cli.parser(__doc__).parse_args()
q = cli.client(args, "k9_baseline")
oks = []
for city in cli.cities(args):
    c = cli.city_obj(q, city)
    sid, spec = cli.sets(args, city)[0]
    loves = [E.resolve_love(q, t, h) for t, h in spec]
    pool, _, _ = E.taste_pool(q, c, loves)
    U, _ = E.floor(pool)
    ids = [e["entity_id"] for e in U]
    rs = E.rescore(q, c, loves, ids, None, "K9 nosignal")
    nr = E.ranks_from(rs["aff"], ids)
    pr = ST.rank({e["entity_id"]: e.get("popularity") or 0 for e in U})
    rho = ST.spearman(nr, pr)
    ok = rs["coverage"] >= 0.95 and rs["distinct"] >= 0.5 * len(ids) and rs["drift"] <= E.CFG["ANCHOR_DRIFT_MAX"]
    oks.append(ok)
    dec = ("popularity field (same order, 0 calls)" if ok and rho >= 0.98 else
           "no-signal rescoring" if ok else "popularity field (fallback)")
    print("  %s/%s: N=%d coverage %s (missing %d) distinct %d drift %s calls %d rho(nosignal,popularity) %s -> %s; baseline = %s%s" % (
        city.upper(), sid, len(ids), cli.f(rs["coverage"]), len(rs["missing"]), rs["distinct"], cli.f(rs["drift"], 4),
        rs["calls"], cli.f(rho), cli.verdict(ok), dec, cli.tag(args)))
    # single-list variant: all of U in one filter.results.entities, paged
    p = E.base_filters(c, loves)
    p["filter.results.entities"] = sorted(ids)
    p["take"] = 50
    got = []
    try:
        for k in range(1, 6):
            p["page"] = k
            ents = (q.insights(dict(p), label="K9 one-list p%d" % k).get("results") or {}).get("entities") or []
            got += [e["entity_id"] for e in ents]
            if len(ents) < 50:
                break
        print("    one-list paging: %d returned, %d distinct of %d -> %s" % (len(got), len(set(got)), len(ids),
              "usable (no chunk merge needed)" if len(set(got)) >= 0.95 * len(ids) else "not usable; keep chunks"))
    except QlooError as e:
        print("    one-list paging: HTTP %s (URL too long or rejected); keep chunks" % e.status)
print("K9 baseline:", cli.verdict(all(oks)) + cli.tag(args), "| fallback: popularity-field rank from the pool responses (0 calls)")
cli.finish(q, args, "k9_baseline")
