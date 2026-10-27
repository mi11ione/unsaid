"""Gate B · survivors (UNSAID.md §4). Full pipeline per seed set against its wall. A set passes when |U| >= 150,
7 cards + 3 reserves survive, no card is junk (closed, below 4.3, outside R, or an allowlist kind), and the tie share
at Qloo's default affinity is < 30%. PASS: >= 8 of 10 NYC sets and >= 6 of 10 STL sets.
Also prints the cap overlap per set (gate C's measure; run_query.py reports gate C)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from unsaid import cli, engine as E, walls as W  # noqa: E402
from unsaid import cities as C  # noqa: E402

NEED = {"nyc": 8, "stl": 6, "la": 6}
args = cli.parser(__doc__).parse_args()
q = cli.client(args, "k3_survivors")
T = cli.tag(args)


def junk(card, city):
    bad = []
    if not card["open"]:
        bad.append("closed")
    if card["rating"] is None or card["rating"] < E.CFG["RATING_CLIENT"] - E.CFG["RATING_EPS"]:
        bad.append("rating")
    if card["lat"] is not None and C.haversine_mi((card["lat"], card["lon"]), city["center_latlon"]) > city["radius_mi"]:
        bad.append("distance")
    return bad


ok_all, caps = True, []
for city in cli.cities(args):
    c = cli.city_obj(q, city)
    hits, n = 0, 0
    print("  %s" % city.upper())
    for sid, spec in cli.sets(args, city):
        loves = cli.loves(q, spec)
        if loves is None:
            print("    %-8s a love is not in Qloo%s" % (sid, T)); continue
        r = E.run(q, c, loves, W.wall_for(city, sid, args.walls))
        d = r["diag"]
        if r["status"] in ("needs_input", "degraded"):
            print("    %-8s %s%s" % (sid, r["status"], T)); continue
        n += 1
        U = {e["entity_id"]: e for e in r["_U"]}
        bad = {x["name"]: junk(x, c) + (["kind"] if E.excluded_kind(U[x["id"]]) else []) for x in r["picks"] + r["reserves"]}
        bad = {k: v for k, v in bad.items() if v}
        passed = d["N"] >= 150 and len(r["picks"]) >= 7 and len(r["reserves"]) >= 3 and not bad and d["tie_share"] < 0.30
        hits += passed
        caps.append(d.get("popcap_overlap"))
        st = d["wall"]["status"]
        print("    %-8s U=%3d wall %2d answers/%3d names -> struck %3d (C7 %d calls, %d skipped) S=%3d kept=%3d -> "
              "%d+%d %s | tie %s | junk %s | cap overlap %s%s -> %s%s" % (
                  sid, d["N"], d["wall"]["answers"], d["wall"]["names"], d["wall"]["struck"], d["wall"]["c7_calls"],
                  d["wall"]["c7_skipped"], d["S"], d["kept"], len(r["picks"]), len(r["reserves"]), r["status"],
                  cli.f(d["tie_share"]), bad or "none", cli.f(d.get("popcap_overlap")),
                  " FLAGS " + ",".join(r["flags"]) if r["flags"] else "", cli.verdict(passed), T))
    ok = n > 0 and hits >= NEED.get(city, 8) * n / 10.0
    ok_all &= ok
    print("  %s: %d of %d sets pass (gate %d of 10) -> %s%s" % (city.upper(), hits, n, NEED.get(city, 8),
                                                              cli.verdict(ok), T))
vals = [v for v in caps if v is not None and v == v]
print("B survivors:", cli.verdict(ok_all) + T, "| if FAIL: widen R, holds 2 of 3, empty_few shown; STL < 5 -> NYC hero")
print("  cap overlap median %s over %d sets (gate C <= 0.80; run_query.py reports gate C)%s" % (
    cli.f(cli.median(vals)), len(vals), T))
cli.finish(q, args, "k3_survivors")
