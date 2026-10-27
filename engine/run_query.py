"""One UNSAID query end to end: city + 3 loves + wall -> 7 cards, plus the README call trace.
  python3 -I run_query.py --fake --city stl --set cedric
  python3 -I run_query.py --city stl --set cedric --walls walls.json      (live)
Writes out/query_<city>_<set>[.fake].md (README trace) and .json (cards + diagnostics)."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from unsaid import cli, engine as E, report, seeds as SD, walls as W  # noqa: E402

ap = cli.parser(__doc__)
ap.add_argument("--set", default="cedric")
ap.add_argument("--skeptic-fake", action="store_true", help="with --fake: burn against the exp 'fresh' asks")
args = ap.parse_args()
city = "stl" if args.city == "both" else args.city
q = cli.client(args, "run_query")
spec = SD.get(city, args.set)
wall = W.wall_for(city, args.set, args.walls)
sk = None
if args.fake and args.skeptic_fake:
    fresh = W.names({"answers": W.fresh_for(city)})
    sk = lambda hood, cname: fresh  # noqa: E731
c = cli.city_obj(q, city)
res = E.run(q, c, spec, wall, skeptic_fn=sk)
d = res["diag"]
print("  status %s | P %s U %s struck %s S %s kept %s | rho(taste,base) %s | flags %s" % (
    res["status"], d.get("P"), d.get("U"), (d.get("wall") or {}).get("struck"), d.get("S"), d.get("kept"),
    cli.f(d.get("rho_taste_base")), res.get("flags")))
for i, card in enumerate(res["cards"], 1):
    print("  %d. %-32s %-18s fits %-10s city %-10s holds %-6s %s" % (
        i, card["name"][:32], (card["neighbourhood"] or "")[:18], card["fits"], card["city_order"], card["holds"],
        card["because"]["line"]))
base = os.path.join(cli.OUT, "query_%s_%s%s" % (city, args.set, ".fake" if args.fake else ""))
with open(base + ".md", "w") as fh:
    fh.write(report.markdown(res, q, c["name"], spec, wall, args.fake))
with open(base + ".json", "w") as fh:
    json.dump({k: v for k, v in res.items() if not k.startswith("_")}, fh, indent=1, default=str)
with open(base + ".wall.json", "w") as fh:
    json.dump(wall, fh, indent=1)
print("  wrote %s.md (README trace), .json, .wall.json" % base)
cli.finish(q, args, "run_query")
