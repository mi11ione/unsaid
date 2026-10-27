"""K4 live relabel (UNSAID.md §4 row K4): the matcher on the REAL pool. Two passes, both 0 new Qloo calls when the
sets already ran (A/B warmed the cache):
  python3 -I k4_relabel.py --export [--city stl --set cedric]   -> out/k4_<city>_<set>.csv (one row per wall name) and
                                                                   out/k4_<city>_<set>.pool.csv (U: id, name)
  (a human fills the `truth` column: the Qloo ID(s) in U the AI name refers to, ';'-separated, or `none`)
  python3 -I k4_relabel.py --score                               -> ⟦LABELLED⟧ ⟦FALSE_SURV⟧ ⟦PREC⟧ and the K4 verdict
PASS: 0 false survivors (a pool member a human marks as named that nothing struck). Precision < 95% is fine.
out/ is gitignored (the CSVs hold Qloo IDs and names). In --fake, --score auto-labels unfilled rows with the
strong-name matches, tagged [FAKE]."""
import csv, glob, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from unsaid import cli, engine as E, matcher as M, seeds as SD, walls as W  # noqa: E402

ap = cli.parser(__doc__)
ap.add_argument("--set", action="append", help="set id (repeatable); default cedric (STL) and A (NYC)")
ap.add_argument("--export", action="store_true")
ap.add_argument("--score", action="store_true")
args = ap.parse_args()
T = cli.tag(args)
sfx = ".fake" if args.fake else ""
if args.export:
    q = cli.client(args, "k4_relabel")
    jobs = [(c, SD.resolve(c, s)) for c in cli.cities(args) for s in (args.set or ["cedric", "khruangbin"])
            if SD.resolve(c, s)]
    for city, sid in jobs:
        c = cli.city_obj(q, city)
        spec = SD.get(city, sid)
        r = E.run(q, c, cli.loves(q, spec), W.wall_for(city, sid, args.walls, loves=[t for t, _ in spec]))
        U = {e["entity_id"]: e.get("name") for e in r["_U"]}
        base = os.path.join(cli.OUT, "k4_%s_%s%s" % (city, sid, sfx))
        with open(base + ".pool.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["qloo_id", "name"])
            for i, n in sorted(U.items(), key=lambda kv: kv[1] or ""):
                w.writerow([i, n])
        with open(base + ".csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["raw_name", "status", "reason", "struck_ids", "struck_names", "truth"])
            for raw, info in r["_per"].items():
                ids = info.get("ids") or []
                w.writerow([raw, info["status"], info.get("reason"), ";".join(ids), "; ".join(U.get(i) or i for i in ids), ""])
        print("  exported %s.csv (%d names) and .pool.csv (%d places)%s" % (base, len(r["_per"]), len(U), T))
    cli.finish(q, args, "k4_relabel")
if args.score:
    labelled, fs, struck_all, struck_true = 0, [], 0, 0
    for fp in sorted(glob.glob(os.path.join(cli.OUT, "k4_*%s.csv" % sfx))):
        if fp.endswith(".pool.csv") or (not args.fake and fp.endswith(".fake.csv")):
            continue
        pool = {}
        with open(fp.replace(".csv", ".pool.csv")) as f:
            pool = {row["qloo_id"]: row["name"] for row in csv.DictReader(f)}
        rows = list(csv.DictReader(open(fp)))
        named, struck = set(), set()
        for row in rows:
            truth = (row["truth"] or "").strip()
            if not truth and args.fake:   # [FAKE] auto-label: strong name matches in the pool
                truth = ";".join(i for i, n in pool.items() if M.strong(row["raw_name"], n)) or "none"
            if not truth:
                continue
            labelled += 1
            if truth.lower() != "none":
                named |= {t for t in truth.split(";") if t in pool}
            struck |= set(filter(None, row["struck_ids"].split(";")))
        fs += sorted(pool[i] for i in named - struck)
        struck_all += len(struck)
        struck_true += len(struck & named)
        print("  %s: %d names labelled, %d named pool members, %d struck, false survivors %s%s" % (
            os.path.basename(fp), labelled, len(named), len(struck), sorted(pool[i] for i in named - struck) or 0, T))
    prec = struck_true / float(struck_all) if struck_all else float("nan")
    print("  ⟦LABELLED⟧ = %d · ⟦FALSE_SURV⟧ = %d · ⟦PREC⟧ = %s%s" % (labelled, len(fs), cli.f(100 * prec, 1), T))
    print("K4 live relabel: false survivors %d (gate 0) -> %s%s | if FAIL: raise the guard; accept over-striking" % (
        len(fs), cli.verdict(labelled > 0 and not fs), T))
    if not args.export:
        print("QLOO_NETWORK_CALLS=0%s" % T)
