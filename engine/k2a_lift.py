"""K2a: lift is not noise.
  (1) Spearman(taste rank, base rank) over the fixed set U <= 0.90 in >= 8 of 10 sets per city;
  (2) the top-20 by lift is identical across 2 runs (second run bypasses the cache);
  (3) two strangers: Cedric's top-7 vs Jason's top-7 in St. Louis, Jaccard <= 0.5, AND the rank-level version:
      Cedric's U rescored under Jason's signal, Spearman <= 0.90. The Jaccard alone is not enough: in a
      popularity-only fake world (FAKE_TASTE_WEIGHT=0.03) top-7-by-lift Jaccard was 0.27 (lift there is tail noise,
      and noise differs between people) while the rank rho was 0.96. Also prints the mean pairwise top-7 Jaccard.
Also prints the leakage panel: rho(taste, popularity), rho(no-signal, popularity), anchor drift, rescoring coverage."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from itertools import combinations  # noqa: E402
from unsaid import cli, engine as E, stats as ST, seeds as SD  # noqa: E402
from unsaid.qloo import Qloo  # noqa: E402

ap = cli.parser(__doc__)
ap.add_argument("--reruns", type=int, default=3, help="sets to rerun without cache (each costs ~8 calls)")
args = ap.parse_args()
q = cli.client(args, "k2a_lift")


def analyse(qq, city, spec):
    c = cli.city_obj(qq, city)
    loves = [E.resolve_love(qq, t, h) for t, h in spec]
    if any(l["status"] == "needs_input" for l in loves):
        return None
    pool, _, _ = E.taste_pool(qq, c, loves)
    U, _ = E.floor(pool)
    if len(U) < 10:
        return None
    R = E.pool_ranks(qq, c, loves, U)
    top = sorted(R["lift"], key=lambda i: (-R["lift"][i], R["taste_rank"][i], i))
    return {"c": c, "loves": loves, "U": U, "R": R, "top7": top[:7], "top20": top[:20]}


ok_all, results = True, {}
for city in cli.cities(args):
    good, n = 0, 0
    print("  %s" % city.upper())
    for sid, spec in cli.sets(args, city):
        a = analyse(q, city, spec)
        if a is None:
            print("    %-8s skipped (needs_input or thin)" % sid); continue
        results[(city, sid)] = a
        R = a["R"]; b = R.get("baseline_rescore") or {}
        n += 1
        good += R["rho_taste_base"] <= 0.90
        print("    %-8s N=%3d rho(taste,base)=%s rho(taste,pop)=%s rho(nosig,pop)=%s cover=%s drift=%s base=%s" % (
            sid, R["N"], cli.f(R["rho_taste_base"]), cli.f(R["rho_taste_pop"]), cli.f(R.get("rho_nosignal_pop")),
            cli.f(b.get("coverage")), cli.f(b.get("drift"), 4), R["baseline"].split(" (")[0]))
    ok = n > 0 and good >= 0.8 * n
    ok_all &= ok
    print("  %s: rho<=0.90 in %d of %d -> %s%s" % (city.upper(), good, n, cli.verdict(ok), cli.tag(args)))
    keys = [k for k in results if k[0] == city]
    js = [ST.jaccard(results[x]["top7"], results[y]["top7"]) for x, y in combinations(keys, 2)]
    if js:
        print("  %s strangers matrix: mean top-7 Jaccard %s, max %s over %d pairs" % (
            city.upper(), cli.f(sum(js) / len(js)), cli.f(max(js)), len(js)))

# (2) determinism
q2 = Qloo(fake=args.fake, use_cache=True, refresh=True)
same, tried = 0, 0
for (city, sid) in list(results)[:args.reruns]:
    b = analyse(q2, city, SD.get(city, sid))
    tried += 1
    same += b is not None and b["top20"] == results[(city, sid)]["top20"]
ok_det = tried > 0 and same == tried
print("  rerun determinism: top-20 by lift identical in %d of %d reruns -> %s%s" % (same, tried, cli.verdict(ok_det), cli.tag(args)))

# (3) two strangers
_, x, y = SD.STRANGERS
ok_str = False
if ("stl", x) in results and ("stl", y) in results:
    A, B = results[("stl", x)], results[("stl", y)]
    j = ST.jaccard(A["top7"], B["top7"])
    ids = [e["entity_id"] for e in A["U"]]
    rs = E.rescore(q, A["c"], A["loves"], ids, B["loves"], "K2a stranger")
    rho = ST.spearman(A["R"]["taste_rank"], E.ranks_from(rs["aff"], ids))
    ok_str = j <= 0.5 and rho <= 0.90
    print("  two strangers (STL %s vs %s): top-7 Jaccard %s (gate <=0.5), rank rho over %s's U %s (gate <=0.90; rho(taste,pop) %s) -> %s%s" % (
        x, y, cli.f(j), x, cli.f(rho), cli.f(A["R"]["rho_taste_pop"]), cli.verdict(ok_str), cli.tag(args)))
else:
    print("  two strangers: not run (STL sets missing)")
print("K2a lift:", cli.verdict(ok_all and ok_det and ok_str) + cli.tag(args),
      "| fallback if FAIL: drop lift; order by taste rank within the bottom 80% of base rank; card says 'fits you #k'")
cli.finish(q, args, "k2a_lift")
