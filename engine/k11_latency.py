"""Gate F · speed (UNSAID.md §4, §3.4). PASS: p50 <= 20 s to cards (the final 'done' line) and first strike <= 1 s
(p50), on a warm host, fresh love sets (no cache). The pass that counts is measured from a phone on cellular: run with
--url against the deployed /api/unsaid from a machine tethered to the phone. Without --url it runs in-process
(api.run_unsaid, cache off), which is the engine's share of the time only. Fills ⟦P50⟧ ⟦P90⟧.
"First strike" is read as the first wall name on screen (the dated wall streams from static data within 1 s; a red
strike needs U, ~7 s into a fresh run per §3.4). Both times are printed.

  --url https://unsaid.mi11ion.io/api/unsaid streams NDJSON; the token (if any) comes from env UNSAID_TOKEN, sent as the query
                                    param `token` (the Pages proxy forwards the query string as is); loves go as the
                                    set spec's [text, hint] pairs: loves=[["Frankie Beverly & Maze","artist"],...]
  --runs N                          default 5 fake, 3 live (each live in-process run costs ~27 Qloo calls)"""
import json, os, sys, time, urllib.parse, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from unsaid import api, cli, seeds as SD  # noqa: E402

ap = cli.parser(__doc__)
ap.add_argument("--url")
ap.add_argument("--runs", type=int)
args = ap.parse_args()
T = cli.tag(args)
runs = args.runs or (5 if args.fake else 3)
jobs = [(c, sid, spec) for c in cli.cities(args) for sid, spec in cli.sets(args, c)][:runs]
print("== k11_latency  %s  %s" % ("[FAKE]" if args.fake else "[LIVE]", args.url or "in-process (engine share only)"))


def run_http(city, spec):
    params = [("city", SD.CITY_QUERY[city][0]), ("loves", json.dumps([[t, h] for t, h in spec]))]
    tok = os.environ.get("UNSAID_TOKEN")
    if tok:
        params.append(("token", tok))          # never printed: only args.url (without the query) is logged
    req = urllib.request.Request(args.url + ("&" if "?" in args.url else "?") + urllib.parse.urlencode(params),
                                 headers={"Accept": "application/x-ndjson", "User-Agent": "unsaid-k11/1.0"})   # Cloudflare 403s the default urllib agent
    if os.environ.get("UNSAID_BENCH_SECRET"):  # skips the 3-fresh-runs/hour/IP limit; never printed
        req.add_header("X-Unsaid-Bench", os.environ["UNSAID_BENCH_SECRET"])
    t0 = time.monotonic()
    marks = {}
    with urllib.request.urlopen(req, timeout=120) as r:
        for line in r:
            line = line.strip()
            if not line:
                continue
            e = json.loads(line.decode("utf-8"))
            marks.setdefault(e.get("type"), time.monotonic() - t0)
            if e.get("type") == "done":
                return marks, (e.get("result") or {}).get("status")
    return marks, None


def run_local(city, sid, spec):
    q = cli.client(args, "k11_latency") if not hasattr(run_local, "q") else run_local.q
    run_local.q = q
    q.use_cache = False
    t0 = time.monotonic()
    marks = {}

    def on(e):
        marks.setdefault(e["type"], time.monotonic() - t0)
    ch, _ = cli.chips(q, spec)
    t0 = time.monotonic()      # loves resolve on blur in the product, before CROSS OUT
    r = api.run_unsaid(SD.CITY_QUERY[city][0], ch, walls_path=args.walls, mode="fake" if args.fake else "live",
                       on_event=on, qloo=q, set_id=sid, use_cache=False)
    return marks, r["status"]


done, strike = [], []
for city, sid, spec in jobs:
    try:
        marks, st = run_http(city, spec) if args.url else run_local(city, sid, spec)
    except Exception as e:
        print("    %s/%-8s ERROR %s%s" % (city.upper(), sid, str(e)[:120], T))
        continue
    if "done" in marks:
        done.append(marks["done"])
    if "wall_name" in marks or "strike" in marks:
        strike.append(marks.get("wall_name", marks.get("strike")))
    print("    %s/%-8s first wall name %s s · first strike %s s · first card %s s · done %s s · status %s%s" % (
        city.upper(), sid, cli.f(marks.get("wall_name")), cli.f(marks.get("strike")), cli.f(marks.get("card")),
        cli.f(marks.get("done")), st, T))


def pct(xs, p):
    s = sorted(xs)
    return s[min(len(s) - 1, int(p * len(s)))] if s else float("nan")


p50, p90, s50 = cli.median(done), pct(done, 0.9), cli.median(strike)
ok = bool(done) and p50 <= 20 and s50 <= 1
print("  ⟦P50⟧ = %s s · ⟦P90⟧ = %s s (%d runs; %s)%s" % (cli.f(p50, 1), cli.f(p90, 1), len(done),
                                                       "phone/cellular via --url" if args.url else "in-process", T))
print("F speed: p50 %s s to cards (gate <=20), first name on screen p50 %s s (gate <=1) -> %s%s" % (
    cli.f(p50, 1), cli.f(s50, 2), cli.verdict(ok), T), "| if FAIL: try-these first on S1; fresh runs say 'about a minute'")
if getattr(run_local, "q", None) is not None:
    cli.finish(run_local.q, args, "k11_latency")
else:
    print("QLOO_NETWORK_CALLS=0%s" % T)
