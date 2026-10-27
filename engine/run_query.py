"""One UNSAID query end to end through the product path (unsaid.api.run_unsaid): city + 3 loves + wall -> 7 cards,
plus the README call trace (call trace with request URLs, the floor line, the popularity section).
  python3 -I run_query.py --fake --city stl --set cedric
  QLOO_API_KEY=... python3 -I run_query.py --city stl --set cedric --walls walls.json      (live)
Writes out/query_<city>_<set>[.fake].md (README trace), .json (CONTRACT result), .events.ndjson (the stream).
out/ is gitignored: Qloo-derived results never go where git tracks."""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from unsaid import api, cli, report, seeds as SD  # noqa: E402

ap = cli.parser(__doc__)
ap.add_argument("--set", default="cedric")
ap.add_argument("--no-street", action="store_true", help="skip the street check (L2)")
args = ap.parse_args()
city = "stl" if args.city == "both" else args.city
q = cli.client(args, "run_query")
spec = SD.get(city, args.set)
events = []
t0 = time.monotonic()
stamps = {}


def on_event(e):
    events.append(e)
    stamps.setdefault(e["type"], round(time.monotonic() - t0, 3))


res = api.run_unsaid(SD.CITY_QUERY[city][0], [list(x) for x in spec], walls_path=args.walls,
                     mode="fake" if args.fake else "live", on_event=on_event, qloo=q, set_id=args.set,
                     use_cache=not args.no_cache, street_check=False if args.no_street else None)
d, cn = res["diag"], res["counts"]
T = cli.tag(args)
print("  status %s | P %s U %s S %s kept %s | wall %s names / %s asks | rho_tp %s rho_res %s | flags %s%s" % (
    res["status"], cn["P"], cn["U"], cn["S"], d.get("kept"), cn["wall"], cn["asks"], cli.f(d.get("rho_tp")),
    cli.f(d.get("rho_res")), res["flags"], T))
for i, c in enumerate(res["picks"], 1):
    print("  %d. %-30s %-18s #%-4s for you · %-6s for anyone · holds %s/%s · because %s%s" % (
        i, (c["name"] or "")[:30], (c["neighbourhood"] or "")[:18], c["fit_rank"],
        "#%s" % c["any_rank"] if c["any_rank"] else "—", c["holds"], c["n_loves"], c["because"], T))
print("  events: %s; first strike at %s s, first card at %s s%s" % (
    len(events), stamps.get("strike"), stamps.get("card"), T))
base = os.path.join(cli.OUT, "query_%s_%s%s" % (city, args.set, ".fake" if args.fake else ""))
trace = [r for r in q.trace if not r["label"].endswith("(retry)")]
with open(base + ".md", "w") as fh:
    fh.write(report.markdown(res, trace, res["city"]["name"] if res.get("city") else city,
                             [t for t, _ in spec], args.fake, args.set))
with open(base + ".json", "w") as fh:
    json.dump(res, fh, indent=1, default=str)
with open(base + ".events.ndjson", "w") as fh:
    for e in events:
        fh.write(json.dumps(e, default=str) + "\n")
print("  wrote %s.md (README trace), .json (CONTRACT result), .events.ndjson" % base)
cap_ok = d.get("cap_overlap") is not None and d["cap_overlap"] <= 0.80
print("C not a cap: cap overlap %s (gate <=0.80), cap's 7 share %s with ours -> %s%s" % (
    cli.f(d.get("cap_overlap")), d.get("cap_shared"), cli.verdict(cap_ok), T))
ok = res["status"] in ("ok", "partial") and len(res["picks"]) == 7
print("run_query: %d cards, %d Qloo calls, status %s -> %s%s" % (
    len(res["picks"]), d.get("qloo_calls") or 0, res["status"], cli.verdict(ok), T))
cli.finish(q, args, "run_query")
sys.exit(0 if ok else 1)
