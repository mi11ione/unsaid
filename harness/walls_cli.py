"""The wall harness (UNSAID.md §3.6): ask the city wall, taste and street phrasings on three lanes, then build
walls.json in the kit's contract (engine/unsaid/walls.py).

  python3 -I walls_cli.py plan                                    # ask counts per lane against the §3.6 budget
  python3 -I walls_cli.py ask --lane all --wall 1                 # dry run: what would be asked
  python3 -I walls_cli.py ask --lane all --wall 1 --go            # dated wall #1: city + taste, STL and NYC
  python3 -I walls_cli.py ask --lane claude,codex --kind street --wall 1 --go     # every neighbourhood
  python3 -I walls_cli.py ask --lane claude --kind street --hoods "Soulard,The Ville" --city stl --wall 1 --go
  python3 -I walls_cli.py build --walls 1,2,3 --out ../data/walls.json
  python3 -I walls_cli.py status

Answers append to runs/wall-<N>.jsonl, one line per attempt; an id already stored ok is never asked again, so a run
that stops on a plan limit resumes by running the same line again. Nothing is asked without --go.
Answer ids: w<N>:<kind>:<city>:<set|->:<phrasing_id>:<lane>.
"""
import argparse, datetime, glob, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lanes as L
import phrasings as P

CENSUS_FILES = {"claude": "claude_answers.jsonl", "codex": "codex_answers.jsonl", "gemini": "gemini_answers.jsonl"}
HOODS = os.path.join(HERE, "neighbourhoods.json")
FRESH = os.environ.get("UNSAID_FRESH") or os.path.join(os.path.dirname(HERE), "data", "fresh_asks.json")


def wall_path(w):
    return os.path.join(L.RUNS, "wall-%s.jsonl" % w)


def load_hoods(args):
    if args.hoods:
        return {ck: [h.strip() for h in args.hoods.split(",") if h.strip()] for ck in args.cities}
    if os.path.exists(HOODS):
        return json.load(open(HOODS))["cities"]
    return {}


def build_asks(lane, wall, kinds, cities, sets, hoods, set_filter=None):
    out = []
    base = lambda **k: dict(k, prompt_v=P.PROMPT_V, prompt=k["phrasing"] + P.SUFFIX_V2, wall=str(wall))
    for ck in cities:
        if "city" in kinds:
            for pid, ph in P.city_wall(ck):
                out.append(base(id="w%s:city:%s:-:%s:%s" % (wall, ck, pid, lane), kind="city", city=ck, set=None,
                                phrasing_id=pid, phrasing=ph))
        if "taste" in kinds:
            for sid, loves in sets.get(ck, []):
                if set_filter and sid not in set_filter:
                    continue
                for pid, ph in P.taste(ck, loves):
                    out.append(base(id="w%s:taste:%s:%s:%s:%s" % (wall, ck, sid, pid, lane), kind="taste", city=ck,
                                    set=sid, loves=loves, phrasing_id=pid, phrasing=ph))
        if "street" in kinds:
            for h in hoods.get(ck, []):
                out.append(base(id="w%s:street:%s:-:%s:%s" % (wall, ck, P.slug(h), lane), kind="street", city=ck,
                                set=None, hood=h, phrasing_id="street:" + P.slug(h), phrasing=P.street(ck, h)))
    return out


def fresh_hashes():
    if not os.path.exists(FRESH):
        return set()
    d = json.load(open(FRESH))
    qs = d.get("questions", d) if isinstance(d, dict) else d
    return {P.qhash(q["text"]) for q in qs}


def cmd_ask(args):
    sets = P.load_sets(args.sets_file)
    hoods = load_hoods(args) if "street" in args.kinds else {}
    if "street" in args.kinds and not any(hoods.get(ck) for ck in args.cities):
        sys.exit("street asks need neighbourhoods: run hoods.py (writes neighbourhoods.json) or pass --hoods")
    fh = fresh_hashes()
    lanes = L.lanes_from(args.lane)
    if not lanes:
        sys.exit("no lane available")

    def asks_for(lane):
        a = build_asks(lane.name, args.wall, args.kinds, args.cities, sets, hoods, args.set_filter)
        clash = [x["id"] for x in a if P.qhash(x["phrasing"]) in fh]
        if clash:
            sys.exit("refusing: %d wall phrasings hash-match a held-out fresh ask: %s" % (len(clash), clash[:3]))
        return a
    L.run_lanes(lanes, asks_for, lambda l: wall_path(args.wall), args.limit, args.go)


def census_answers(ck):
    out = []
    for prov, fn in CENSUS_FILES.items():
        p = os.path.join(HERE, fn)
        for r in L.load(p).values():
            if r["city"] != ck or not L.is_done(r):
                continue
            out.append(dict(r, kind="census", phrasing_id=r["id"], prompt_v=r.get("prompt_v", "v1"),
                            provider=r.get("provider") or {"claude": "anthropic", "codex": "openai", "gemini": "google"}[prov],
                            assistant=r.get("assistant") or {"claude": "Claude", "codex": "ChatGPT", "gemini": "Gemini"}[prov],
                            asked_at=r.get("asked_at") or r.get("t_start"), lane=r.get("lane", "dated"),
                            search=r.get("search", "off"), id="census:%s:%s" % (prov, r["id"])))
    return out


def item(r):
    """One answer in the kit's contract (engine/unsaid/walls.py), plus the fields §3.6 adds."""
    return {"id": r["id"], "kind": r["kind"], "provider": r["provider"], "assistant": r.get("assistant"),
            "model": r.get("model"), "lane": r.get("lane", "dated"), "search": r.get("search", "off"),
            "phrasing_id": r["phrasing_id"], "phrasing": r["phrasing"], "prompt_v": r.get("prompt_v"),
            "asked_at": r.get("asked_at"), "hood": r.get("hood"), "status": r.get("status", "ok"),
            "names": r.get("places") or [], "raw": r.get("raw") or ""}


def cmd_build(args):
    sets = P.load_sets(args.sets_file)
    recs, failed = [], []
    for w in args.walls:
        for r in L.load(wall_path(w)).values():
            (recs if L.is_done(r) else failed).append(r)
    fh = fresh_hashes()
    bad = [r["id"] for r in recs if P.qhash(r["phrasing"]) in fh]
    if bad:
        sys.exit("refusing: %d stored wall answers hash-match a held-out fresh ask: %s" % (len(bad), bad[:3]))
    walls, meta = [], {"built_at": L.now(), "walls_used": args.walls, "prompt_v": P.PROMPT_V,
                       "failed_not_included": sorted(r["id"] for r in failed), "counts": {}}
    n = 0
    for ck in args.cities:
        cr = [r for r in recs if r["city"] == ck]
        # set "city" and "census" apply to every set of the city (walls.GENERIC_SETS); a set's entry is its taste only
        city = [r for r in cr if r["kind"] == "city"] + ([] if args.no_street else [r for r in cr if r["kind"] == "street"])
        census = [] if args.no_census else census_answers(ck)
        walls.append({"city": ck, "set": "city", "answers": [item(r) for r in city]})
        walls.append({"city": ck, "set": "census", "answers": [item(r) for r in census]})
        allr = city + census
        for sid, _ in sets.get(ck, []):
            taste = [r for r in cr if r["kind"] == "taste" and r["set"] == sid]
            walls.append({"city": ck, "set": sid, "answers": [item(r) for r in taste]})
            allr += taste
        by = {}
        for r in allr:
            k = "%s/%s" % (r["kind"], r.get("runner") or r["provider"])
            by[k] = by.get(k, 0) + 1
        meta["counts"][ck] = by
        n += len(allr)
    out = {"meta": meta, "walls": walls}
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print("wrote %s: %d wall entries, %d answers, %d failed asks left out, %.1f MB" % (
        args.out, len(walls), n, len(failed), os.path.getsize(args.out) / 1e6))
    for ck, c in meta["counts"].items():
        print("  %s %s" % (ck, json.dumps(c, sort_keys=True)))


def cmd_status(args):
    for p in sorted(glob.glob(os.path.join(L.RUNS, "*.jsonl"))) + [os.path.join(HERE, f) for f in CENSUS_FILES.values()]:
        if not os.path.exists(p):
            continue
        c = {}
        for r in L.load(p).values():
            k = (r.get("kind", "census"), r.get("runner") or r.get("provider") or "claude", r.get("status") or ("ok" if r.get("places") else "failed"))
            c[k] = c.get(k, 0) + 1
        print(os.path.relpath(p, HERE), ", ".join("%s/%s/%s %d" % (k + (v,)) for k, v in sorted(c.items())))


def cmd_plan(args):
    sets = P.load_sets(args.sets_file)
    hoods = json.load(open(HOODS))["cities"] if os.path.exists(HOODS) else {}
    nset = sum(len(sets.get(ck, [])) for ck in P.CITY)
    city = 20 * len(P.CITY)                        # per lane per wall day
    taste = 4 * nset                               # per lane per wall day
    street = sum(len(hoods.get(ck, [])) for ck in P.CITY)  # per lane, once
    fresh = 20 * len(P.CITY) + 4 * nset            # per lane: 20 plain per city (shared by its sets) + 4 with loves per set
    meter = 10 * 2 * 2 * 2                         # per lane: 10 sets x 2 arms x 2 phrasings x 2 reps
    days = 3
    print("per lane, per wall day: city %d + taste %d (%d sets) = %d" % (city, taste, nset, city + taste))
    print("per lane, once: street %d%s, census 128 (claude: already stored), fresh %d, meter %d" % (
        street, "" if hoods else " (no neighbourhoods.json yet)", fresh, meter))
    for lab, tdays in (("taste every wall day", days), ("taste on wall #1 only", 1)):
        w = days * city + tdays * taste
        sub = 2 * w + 2 * street + 128 + 2 * fresh + 2 * meter
        gem = w + 128 + fresh + meter
        print("%s: subscriptions (claude+codex) %d = walls %d + street %d + codex census 128 + fresh %d + meter %d"
              " (§3.6 ~1,500) | gemini %d free calls (+1 per meter tool round; §3.6 ~600)" % (
                  lab, sub, 2 * w, 2 * street, 2 * fresh, 2 * meter, gem))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    a = sp.add_parser("ask")
    a.add_argument("--lane", required=True, help="claude | codex | gemini | all | comma list")
    a.add_argument("--wall", required=True, help="wall number (1, 2, 3) or a label like smoke")
    a.add_argument("--kind", default="city,taste", help="city,taste,street")
    a.add_argument("--city", default="stl,nyc")
    a.add_argument("--sets", dest="set_filter", default=None, help="only these set ids (taste)")
    a.add_argument("--sets-file", default=None)
    a.add_argument("--hoods", default=None, help="comma list of neighbourhoods (street)")
    a.add_argument("--limit", type=int, default=None, help="at most N asks per lane")
    a.add_argument("--go", action="store_true", help="actually ask (default: dry run)")
    b = sp.add_parser("build")
    b.add_argument("--walls", default="1,2,3")
    b.add_argument("--city", default="stl,nyc")
    b.add_argument("--sets-file", default=None)
    b.add_argument("--out", default=os.path.join(os.path.dirname(HERE), "data", "walls.json"))
    b.add_argument("--no-census", action="store_true")
    b.add_argument("--no-street", action="store_true")
    sp.add_parser("status")
    pl = sp.add_parser("plan")
    pl.add_argument("--sets-file", default=None)
    args = ap.parse_args()
    if hasattr(args, "city"):
        args.cities = [c.strip() for c in args.city.split(",") if c.strip()]
    if args.cmd == "ask":
        args.kinds = [k.strip() for k in args.kind.split(",")]
        args.set_filter = set(args.set_filter.split(",")) if args.set_filter else None
        cmd_ask(args)
    elif args.cmd == "build":
        args.walls = [w.strip() for w in args.walls.split(",") if w.strip()]
        cmd_build(args)
    elif args.cmd == "status":
        cmd_status(args)
    else:
        cmd_plan(args)


if __name__ == "__main__":
    main()
