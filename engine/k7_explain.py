"""K7 raw log: explainability is requested on page 1 (offset 0) of each per-love pool, for the RAW LOG only. UNSAID
shows no explainability shares anywhere (UNSAID.md §3.3 step 8: flat at 0.28-0.36 with three loves). PASS: page-1
results carry per-result explainability (no warning) for >= 70% of members, in every set."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from unsaid import cli, engine as E  # noqa: E402
from unsaid.qloo import explain_items  # noqa: E402

args = cli.parser(__doc__).parse_args()
q = cli.client(args, "k7_explain")
T = cli.tag(args)
rates = []
for city in cli.cities(args):
    c = cli.city_obj(q, city)
    print("  %s" % city.upper())
    for sid, spec in cli.sets(args, city):
        loves = cli.loves(q, spec)
        if loves is None:
            continue
        for l in [x for x in loves if x["kind"] == "entity"]:
            p = dict(E.base_filters(c, loves), take=50, **E.signal_of(l))
            p["feature.explainability"] = True
            es = (q.insights(p, label="K7 page1").get("results") or {}).get("entities") or []
            bad = sum(1 for e in es if explain_items(e)[1] or not explain_items(e)[0])
            rate = bad / float(max(1, len(es)))
            rates.append(rate)
            print("    %-8s %-28s explainability missing/warned on %2d of %2d page-1 results (%2.0f%%)%s" % (
                sid, l["text"][:28], bad, len(es), 100 * rate, T))
ok = bool(rates) and max(rates) < 0.30
print("K7 raw log: max missing rate %.0f%% (gate <30%% in every pool) -> %s%s" % (100 * max(rates or [1]), cli.verdict(ok), T),
      "| shares are never shown; the because-line is the best per-love rank")
cli.finish(q, args, "k7_explain")
