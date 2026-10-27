"""K1 density: does the pool reach >= 150 open places rated >= 4.3 under restaurant U bar, in both cities?
Pages to 6 (300 deep) and reports |U| at 200 and at 300. PASS: >= 8 of 10 sets per city have |U| >= 150 within the
engine's adaptive paging (<= 6 pages). The 200-deep number shows whether pages 5-6 are needed."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from unsaid import cli, engine as E  # noqa: E402

args = cli.parser(__doc__).parse_args()
q = cli.client(args, "k1_density")
ok_all = True
for city in cli.cities(args):
    c = cli.city_obj(q, city)
    if c["status"] != "ok":
        print("  %s city: %s" % (city, c.get("reason"))); ok_all = False; continue
    print("  %s -> %s (%s)" % (city.upper(), c["name"], c["disamb"]))
    hits, n = 0, 0
    for sid, spec in cli.sets(args, city):
        loves = [E.resolve_love(q, t, h) for t, h in spec]
        if any(l["status"] == "needs_input" for l in loves):
            print("    %-8s needs_input: %s" % (sid, [l["text"] for l in loves if l["status"] == "needs_input"])); continue
        pool, _, d = E.taste_pool(q, c, loves, pages=6, adaptive=False)
        U4, drop4 = E.floor([e for e in pool if e["_pos"] <= 200])
        U6, _ = E.floor(pool)
        n += 1
        hits += len(U6) >= 150
        print("    %-8s P(200)=%3d -> U=%3d (closed %d, <4.3 %d, no rating %d) | 300 deep: P=%3d U=%3d | paging=%s%s" % (
            sid, min(len(pool), 200), len(U4), drop4["closed"], drop4["rating"], drop4["no_rating"], len(pool), len(U6),
            d["paging"], " (page repeated: switched to offset)" if d["page_repeat"] else ""))
    ok = n > 0 and hits >= 0.8 * n
    ok_all &= ok
    print("  %s: %d of %d sets reach |U|>=150 within 6 pages -> %s%s" % (city.upper(), hits, n, cli.verdict(ok), cli.tag(args)))
print("K1 density:", cli.verdict(ok_all) + cli.tag(args), "| fallback if FAIL: floor 4.0; filter.location.radius padding; Cedric's city -> LA")
cli.finish(q, args, "k1_density")
