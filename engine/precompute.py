"""The try-these sets -> static JSON in the CONTRACT.md result shape, for Cloudflare Pages (direct upload, never git).
  python3 -I precompute.py --fake --out /tmp/try-these              (a directory: index.json + <city>_<set>.json)
  QLOO_API_KEY=... python3 -I precompute.py --walls walls.json --out <dir outside git, or gitignored>
Each file: {"id", "city", "label", "loves", "ran_at", "as_of", "fake", "result": <CONTRACT result>}.
Default sets: the sets marked try_these in data/sets.json (else sets.draft.json), up to --sets per city (5 + 5 = the
10 try-these, Cedric, Jason and Khruangbin included); without marks, the first --sets of each city. A love whose resolution is not exact is reported and the set is skipped unless --accept-top.
Live results contain Qloo data: --out must not be a git-tracked path (checked with `git check-ignore`)."""
import json, os, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from unsaid import api, cli, seeds as SD  # noqa: E402

ap = cli.parser(__doc__)
ap.set_defaults(sets=5)
ap.add_argument("--out", required=True)
ap.add_argument("--sets-file", help='JSON [{"id", "city", "label", "loves": [["text", "hint"], ...]}]')
ap.add_argument("--accept-top", action="store_true", help="use the top candidate for a love that needs input")
ap.add_argument("--no-street", action="store_true")
ap.add_argument("--no-cap", action="store_true", help="skip the CAP call (an offline rerun; cards don't depend on it)")
args = ap.parse_args()
T = cli.tag(args)
LABEL = {("stl", "stl-cedric"): "Cedric · St. Louis", ("stl", "stl-jason"): "Jason · St. Louis",
         ("nyc", "nyc-khruangbin"): "Khruangbin · New York"}   # used only when the sets file carries no label


def inside_git_unignored(path):
    p = os.path.abspath(path)
    d = p if os.path.isdir(p) else os.path.dirname(p)
    while d and not os.path.exists(d):
        d = os.path.dirname(d)
    try:
        top = subprocess.run(["git", "-C", d, "rev-parse", "--show-toplevel"], stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, universal_newlines=True)
    except OSError:
        return False
    if top.returncode != 0:
        return False
    ig = subprocess.run(["git", "-C", d, "check-ignore", "-q", p], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return ig.returncode != 0


if not args.fake and inside_git_unignored(args.out):
    raise SystemExit("refusing: %s is inside a git work tree and not ignored; Qloo data never goes where git tracks"
                     % args.out)

if args.sets_file:
    with open(args.sets_file) as f:
        jobs = [(s["city"], s["id"], [tuple(x) for x in s["loves"]], s.get("label")) for s in json.load(f)]
else:
    jobs = []
    for c in cli.cities(args):
        tt = [(sid, spec) for sid, spec in SD.SEED_SETS.get(c, []) if SD.SET_META.get(sid, {}).get("try_these")]
        for sid, spec in (tt or cli.sets(args, c))[:args.sets]:
            jobs.append((c, sid, spec, SD.SET_META.get(sid, {}).get("label") or LABEL.get((c, sid))))
q = cli.client(args, "precompute", frozen=True)
if args.no_cap:
    from unsaid import engine as _E
    _E.CFG["CAP_ENABLED"] = False
single = args.out.endswith(".json")
if not single:
    os.makedirs(args.out, exist_ok=True)
index, ok_n = [], 0
for city, sid, spec, label in jobs:
    ch, unsure = cli.chips(q, spec)
    if ch is None:
        print("    %s/%-8s a love is not in Qloo; skipped%s" % (city.upper(), sid, T))
        continue
    if unsure and not args.accept_top:
        print("    %s/%-8s needs input (%s); skipped (--accept-top to use the top candidate)%s" % (
            city.upper(), sid, "; ".join(unsure), T))
        continue
    r = api.run_unsaid(SD.CITY_QUERY[city][0], ch, walls_path=args.walls, mode="fake" if args.fake else "live",
                       qloo=q, set_id=sid, use_cache=not args.no_cache, street_check=False if args.no_street else None)
    item = {"id": sid, "city": city, "label": label or "%s · %s" % (", ".join(c["label"] for c in ch), city.upper()),
            "loves": ch, "ran_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "as_of": r["diag"].get("as_of"),
            "fake": args.fake, "result": r}
    ok_n += r["status"] in ("ok", "partial", "empty_few")
    print("    %s/%-8s %s: %d cards, U %s, wall %s places (%s names, snapshot %s), %d Qloo calls%s" % (
        city.upper(), sid, r["status"], len(r["picks"]), r["counts"]["U"], r["counts"]["wall"],
        r["diag"].get("wall_names"), r["diag"].get("wall_snapshot"), r["diag"]["qloo_calls"], T))
    if single:
        index.append(item)
    else:
        fn = "%s_%s.json" % (city, sid)
        with open(os.path.join(args.out, fn), "w") as fh:
            json.dump(item, fh, indent=1, default=str)
        index.append(dict({k: item[k] for k in ("id", "city", "label", "ran_at", "as_of", "fake")},
                          file=fn, status=r["status"]))
doc = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "fake": args.fake, "engine_v": api.E.ENGINE_V,
       "sets": index}
path = args.out if single else os.path.join(args.out, "index.json")
with open(path, "w") as fh:
    json.dump(doc, fh, indent=1, default=str)
ok = ok_n > 0 and ok_n == len(index)
print("precompute: %d of %d sets written to %s -> %s%s" % (len(index), len(jobs), path, cli.verdict(ok), T))
cli.finish(q, args, "precompute")
