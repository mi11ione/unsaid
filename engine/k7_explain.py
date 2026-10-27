"""K7 explainability: query.explainability.warning (or no per-result contributors) on < 30% of the pool U.
Also prints the aggregate impact (top-level query.explainability: top 3/5/10/all), the seed-domination flag
(one love >= 0.6 of the top-10 influence) and dead loves (< 0.1 over all results)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from unsaid import cli, engine as E  # noqa: E402
from unsaid.qloo import explain_items  # noqa: E402

args = cli.parser(__doc__).parse_args()
q = cli.client(args, "k7_explain")
rates, ok_all = [], True
for city in cli.cities(args):
    c = cli.city_obj(q, city)
    print("  %s" % city.upper())
    for sid, spec in cli.sets(args, city):
        loves = [E.resolve_love(q, t, h) for t, h in spec]
        if any(l["status"] == "needs_input" for l in loves):
            continue
        pool, first, _ = E.taste_pool(q, c, loves)
        U, _ = E.floor(pool)
        bad = sum(1 for e in U if explain_items(e)[1] or not explain_items(e)[0])
        rate = bad / max(1, len(U))
        rates.append(rate)
        agg = E.aggregate_shares(first, loves)
        top10 = agg["shares"].get("top_10") or {}
        print("    %-8s warn/empty %3d of %3d (%2.0f%%) | aggregate top-10: %s%s" % (
            sid, bad, len(U), 100 * rate, ", ".join("%s %.2f" % (k[:22], v) for k, v in sorted(top10.items(), key=lambda kv: -kv[1])) or "absent",
            "".join(" | %s %s" % (k, v) for k, v in agg["flags"].items())))
ok = bool(rates) and max(rates) < 0.30
print("K7 explainability: max warn rate %.0f%% (gate <30%% in every set) -> %s%s" % (100 * max(rates or [1]), cli.verdict(ok), cli.tag(args)),
      "| fallback: because-line from drop-one rank deltas")
cli.finish(q, args, "k7_explain")
