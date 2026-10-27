"""K1 density (gate B, first half): |U| after the floor, the allowlist and the distance check, from the per-love pools
(2 calls per entity love, offsets 0 and 50). PASS: |U| >= 150 in >= 8 of 10 NYC sets and >= 6 of 10 STL sets
(UNSAID.md §4 B). Prints the floor line per set."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from unsaid import cli, engine as E  # noqa: E402

NEED = {"nyc": 8, "stl": 6, "la": 6}
args = cli.parser(__doc__).parse_args()
q = cli.client(args, "k1_density")
T = cli.tag(args)
ok_all = True
for city in cli.cities(args):
    c = cli.city_obj(q, city)
    if c["status"] != "ok":
        print("  %s city: %s%s" % (city, c.get("reason"), T)); ok_all = False; continue
    print("  %s -> %s (%s)" % (city.upper(), c["name"], c["disamb"]))
    hits, n = 0, 0
    for sid, spec in cli.sets(args, city):
        loves = cli.loves(q, spec)
        if loves is None:
            print("    %-8s a love is not in Qloo%s" % (sid, T)); continue
        pool, d = E.per_love_pools(q, c, loves)
        U, dr = E.floor(pool, c)
        n += 1
        hits += len(U) >= 150
        print("    %-8s %d pool calls: %d -> %d (closed %d, below 4.3 %d, outside %s mi %d, not a restaurant or bar %d)%s" % (
            sid, d["calls"], len(pool), len(U), dr["closed"], dr["below_43"], c["radius_mi"], dr["outside_R"],
            dr["not_venue"], T))
    need = NEED.get(city, 8) * n / 10.0
    ok = n > 0 and hits >= need
    ok_all &= ok
    print("  %s: |U|>=150 in %d of %d sets (gate %d of 10) -> %s%s" % (city.upper(), hits, n, NEED.get(city, 8),
                                                                     cli.verdict(ok), T))
print("K1 density:", cli.verdict(ok_all) + T, "| if FAIL: widen R; holds 2 of 3; STL < 5 -> NYC hero, Cedric -> LA")
cli.finish(q, args, "k1_density")
