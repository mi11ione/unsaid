"""Gate A · taste moves (UNSAID.md §4). PASS: rho(taste, popularity) <= 0.90 within U in >= 8 of 10 sets per city,
AND the two strangers' sevens (STL Cedric vs Jason) share <= 2. Printed, not gated: rho_AB (Cedric's U rescored under
Jason's loves, vs Cedric's order), top-50 Jaccard of the for-you order vs popularity, the mean shared count over all
within-city pairs, the AIs' repeat count between the two strangers' taste answers (0 Qloo calls), and rerun
determinism. Fills ⟦STRANGERS⟧."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from itertools import combinations  # noqa: E402
from unsaid import cli, engine as E, matcher as M, seeds as SD, stats as ST, walls as W  # noqa: E402
from unsaid.qloo import Qloo  # noqa: E402

ap = cli.parser(__doc__)
ap.add_argument("--reruns", type=int, default=None, help="sets rerun without cache (default 1 fake, 0 live)")
args = ap.parse_args()
q = cli.client(args, "k2a_lift")
T = cli.tag(args)
reruns = args.reruns if args.reruns is not None else (1 if args.fake else 0)


def analyse(qq, city, sid, spec):
    c = cli.city_obj(qq, city)
    loves = cli.loves(qq, spec)
    if loves is None:
        return None
    r = E.run(qq, c, loves, W.wall_for(city, sid, args.walls, loves=[t for t, _ in spec]), street_check=None)
    if r["status"] in ("needs_input", "degraded") or not r.get("_U"):
        return None
    R = r["_R"]
    ids = list(R["fit"])
    top50_fy = sorted(ids, key=lambda i: R["fit"][i])[:50]
    top50_pop = sorted(ids, key=lambda i: R["pop_ord"][i])[:50]
    return {"c": c, "loves": r["loves"], "r": r, "R": R, "rho": r["diag"]["rho_tp"],
            "jac50": ST.jaccard(top50_fy, top50_pop), "seven": [x["id"] for x in r["picks"]],
            "top20": [i for i in r["_selected"]][:20]}


ok_all, results = True, {}
for city in cli.cities(args):
    good, n = 0, 0
    print("  %s" % city.upper())
    for sid, spec in cli.sets(args, city):
        a = analyse(q, city, sid, spec)
        if a is None:
            print("    %-8s skipped (a love is not in Qloo, or no pool)%s" % (sid, T)); continue
        results[(city, sid)] = a
        n += 1
        good += a["rho"] == a["rho"] and a["rho"] <= 0.90
        d = a["r"]["diag"]
        print("    %-8s U=%3d rho(taste,pop)=%s top-50 Jaccard vs popularity %s tie %s live loves %d flags %s%s" % (
            sid, d["N"], cli.f(a["rho"]), cli.f(a["jac50"]), cli.f(d["tie_share"]), len(d["loves_live"]),
            ",".join(a["r"]["flags"]) or "-", T))
    ok = n > 0 and good >= 0.8 * n
    ok_all &= ok
    print("  %s: rho<=0.90 in %d of %d -> %s%s" % (city.upper(), good, n, cli.verdict(ok), T))
    keys = [k for k in results if k[0] == city]
    sh = [len(set(results[x]["seven"]) & set(results[y]["seven"])) for x, y in combinations(keys, 2)]
    if sh:
        print("  %s all pairs: mean sevens shared %s, max %d over %d pairs (printed, not gated)%s" % (
            city.upper(), cli.f(sum(sh) / float(len(sh))), max(sh), len(sh), T))

# the two strangers
_, x, y = SD.STRANGERS
ok_str, shared = False, None
if ("stl", x) in results and ("stl", y) in results:
    A, B = results[("stl", x)], results[("stl", y)]
    shared = len(set(A["seven"]) & set(B["seven"]))
    ok_str = shared <= 2
    ids = list(A["R"]["fit"])
    live_b = [l for l in B["loves"] if not l.get("dead")]
    orders = []
    for l in live_b:
        rs = E.rescore(q, A["c"], A["loves"], ids, l, "K2a stranger %s" % l["text"][:14])
        orders.append(E.ranks_from(rs["aff"], ids))
    rho_ab = ST.spearman(ST.rank(E.rrf(orders, ids)), ST.rank({i: -A["R"]["fit"][i] for i in ids})) if orders else float("nan")
    ta = {M.norm(n["name"] if isinstance(n, dict) else n) for a in W.taste_answers("stl", x, args.walls, SD.get("stl", x)) for n in a["names"]}
    tb = {M.norm(n["name"] if isinstance(n, dict) else n) for a in W.taste_answers("stl", y, args.walls, SD.get("stl", y)) for n in a["names"]}
    print("  two strangers (STL %s vs %s): sevens share %d (gate <=2) -> %s%s" % (x, y, shared, cli.verdict(ok_str), T))
    print("    rho_AB %s (printed, not gated); the AIs' taste answers for the two share %d of %d / %d names "
          "(0 Qloo calls)%s" % (cli.f(rho_ab), len(ta & tb), len(ta), len(tb), T))
    print("    ⟦STRANGERS⟧ = %d%s" % (shared, T))
else:
    print("  two strangers: not run (STL cedric/jason missing)%s" % T)

# rerun determinism (printed, not gated)
if reruns:
    left = None if args.budget is None else max(0, args.budget - q.calls["network"])
    q2 = Qloo(fake=args.fake, use_cache=True, refresh=True, budget=left)
    cli.extra_clients.append(q2)
    same, tried = 0, 0
    for (city, sid) in list(results)[:reruns]:
        b = analyse(q2, city, sid, SD.get(city, sid))
        tried += 1
        same += b is not None and b["top20"] == results[(city, sid)]["top20"]
    print("  rerun determinism: selection identical in %d of %d reruns (printed, not gated)%s" % (same, tried, T))
print("A taste moves:", cli.verdict(ok_all and ok_str) + T,
      "| if FAIL: place-led seeds; drop '#151 for anyone' from fronts; copy 'new to you'")
cli.finish(q, args, "k2a_lift")
