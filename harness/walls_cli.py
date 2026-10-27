"""The wall harness (UNSAID.md §3.6): ask the city wall, taste and street phrasings on three lanes, then build
walls.json in the kit's contract (engine/unsaid/walls.py).

  python3 -I walls_cli.py plan                                    # ask counts per lane against the §3.6 budget
  python3 -I walls_cli.py ask --lane all --wall 1                 # dry run: what would be asked
  python3 -I walls_cli.py ask --lane all --wall 1 --go            # dated wall #1: city + taste, STL and NYC
  python3 -I walls_cli.py ask --lane claude,codex --kind street --wall 1 --go     # every neighbourhood
  python3 -I walls_cli.py ask --lane claude --kind street --hoods "Soulard,The Ville" --city stl --wall 1 --go
  python3 -I walls_cli.py build --walls 1,2,3        # -> ../data/walls/wall-1.json ... + census.json (server reads the dir)
  python3 -I walls_cli.py build --census-only        # -> ../data/walls/census.json only
  python3 -I walls_cli.py build --walls smoke --out runs/walls.smoke.json   # smoke never goes in data/walls/
  python3 -I walls_cli.py status

Taste sets per wall (orchestrator, 27 Oct): wall 1 asks all 20 sets; every other wall asks only the sets marked
try_these in the sets file (data/sets.json, else data/sets.draft.json). --sets a,b or --all-sets overrides.
Answers append to runs/wall-<N>.jsonl, one line per attempt; an id already stored ok is never asked again, so a run
that stops on a plan limit resumes by running the same line again. Nothing is asked without --go.
Answer ids: w<N>:<kind>:<city>:<set|->:<phrasing_id>:<lane>.
"""
import argparse, datetime, glob, json, os, sys, time

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


def taste_filter(args, try_these, src):
    if args.set_filter:
        return args.set_filter
    if args.all_sets or str(args.wall) == "1" or "taste" not in args.kinds:
        return None
    if not try_these:
        sys.exit("wall %s asks taste only for try_these sets, and %s marks none: pass --sets or --all-sets" % (args.wall, src))
    return try_these


def cmd_ask(args):
    sets, try_these, src = P.load_sets_meta(args.sets_file)
    args.set_filter = taste_filter(args, try_these, src)
    if "taste" in args.kinds:
        print("sets: %s; taste for %s" % (os.path.relpath(src, HERE), "all %d" % sum(map(len, sets.values()))
                                          if not args.set_filter else "%d: %s" % (len(args.set_filter), ",".join(sorted(args.set_filter)))))
    hoods = load_hoods(args) if "street" in args.kinds else {}
    if "street" in args.kinds and not any(hoods.get(ck) for ck in args.cities):
        sys.exit("street asks need neighbourhoods: run hoods.py (writes neighbourhoods.json) or pass --hoods")
    fh = fresh_hashes()
    if "gemini" in args.lane.split(",") or args.lane == "all":
        print("[gemini] " + GEMINI_ONLY_VIA_QUEUE)
    lanes = L.lanes_from(",".join(x for x in (list(L.LANES) if args.lane == "all" else args.lane.split(",")) if x != "gemini"))
    if not lanes:
        sys.exit("no lane available")

    def asks_for(lane):
        a = build_asks(lane.name, args.wall, args.kinds, args.cities, sets, hoods, args.set_filter)
        clash = [x["id"] for x in a if P.qhash(x["phrasing"]) in fh]
        if clash:
            sys.exit("refusing: %d wall phrasings hash-match a held-out fresh ask: %s" % (len(clash), clash[:3]))
        return a
    L.run_lanes(lanes, asks_for, lambda l: wall_path(args.wall), args.limit, args.go)


PAUSE_MIN = 10
GEMINI_ONLY_VIA_QUEUE = ("gemini: not run here: free-tier 20/day (cap 16). Its dated asks go through "
                         "`walls_cli.py queue gemini-priority` only")


def gemini_priority(sets, try_these):
    """The Gemini dated lane's order (orchestrator, 28 Oct; free tier 20 RPD, 5 RPM, one project, one key):
    (a) the 16 census hidden-gem asks, STL then NYC, verbatim from asks.json (prompt v1), stored ONCE in
        gemini_answers.jsonl: census_stats reads them for GEM_GEM, and build puts them in census.json, which joins
        every wall (so they are also the gem part of wall #1);
    (b) the 4 plain wall phrasings per city (w00-w03, v2) -> runs/wall-1.jsonl;
    (c) taste for stl-cedric, then stl-jason; (d) the other try-these sets' taste -> runs/wall-1.jsonl."""
    items = []
    census = json.load(open(os.path.join(HERE, "asks.json")))
    gpath = os.path.join(HERE, CENSUS_FILES["gemini"])
    for ck in ("stl", "nyc"):
        for a in sorted((x for x in census if x["city"] == ck and x["family"] == "hidden"), key=lambda x: x["id"]):
            items.append((gpath, dict(a, kind="census", phrasing_id=a["id"], prompt_v="v1", set=None, also="wall-1 gem part")))
    w1 = wall_path("1")
    for ck in ("stl", "nyc"):
        items += [(w1, a) for a in build_asks("gemini", "1", ["city"], [ck], sets, {}) if a["phrasing_id"].startswith("w")]
    order = ["stl-cedric", "stl-jason"] + [sid for ck in ("stl", "nyc") for sid, _ in sets.get(ck, [])
                                           if sid in try_these and sid not in ("stl-cedric", "stl-jason")]
    for sid in order:
        ck = next((c for c, v in sets.items() if any(x == sid for x, _ in v)), None)
        if ck:
            items += [(w1, a) for a in build_asks("gemini", "1", ["taste"], [ck], sets, {}, {sid})]
    return items


def cmd_queue(args):
    if args.name != "gemini-priority":
        sys.exit("unknown queue %s (gemini-priority)" % args.name)
    sets, try_these, src = P.load_sets_meta(args.sets_file)
    lane = L.GeminiLane()
    if args.already_used:
        lane.seed_used(args.already_used)
    items = gemini_priority(sets, try_these)
    done = {}
    pending = [(p, a) for p, a in items if a["id"] not in done.setdefault(p, L.done_ids(p))]
    ok, msg = lane.check()
    left = lane.remaining() if lane.key else 0
    print("[gemini-priority] %d in queue, %d stored, %d pending; %s" % (len(items), len(items) - len(pending), len(pending),
                                                                     msg if ok else "SKIPPED, " + msg), flush=True)
    for p, a in pending[:max(left, 0) or 3]:
        print("   next: %s" % a["id"])
    if not (ok and args.go):
        return
    streak, busy, day = 0, 0, lane._day()
    for p, a in pending:
        if lane._day() != day:
            print("[gemini-priority] the Pacific day changed; the next batch takes over", flush=True)
            break
        if lane.remaining() <= 0:
            print("[gemini-priority] today's allowance spent (%d of cap %d, Pacific day %s)" % (lane._used(), lane.cap, lane._day()), flush=True)
            break
        r = lane.ask(a["prompt"])
        rec = dict(a)
        rec.update(r, lane="dated", provider=lane.provider, assistant=lane.assistant, runner=lane.name)
        fatal = rec.pop("fatal", False)
        L.append(p, rec)
        print("[gemini] %s %s %ss %s names %s%s" % (rec["id"], rec["status"], rec["secs"], len(rec["places"] or []),
                                                 rec.get("model"), (" " + str(rec.get("error"))[:120]) if rec["status"] == "failed" else ""), flush=True)
        if fatal:
            print("[gemini-priority] stopping: %s" % rec.get("error"), flush=True)
            break
        streak = streak + 1 if rec["status"] == "failed" and not rec.get("transient") else 0
        busy = busy + 1 if rec.get("transient") else 0
        if busy >= 2:  # timeouts / 503s in a row: each one spends a request, so wait instead of hammering
            print("[gemini-priority] %d slow answers in a row; pausing %d min" % (busy, PAUSE_MIN), flush=True)
            time.sleep(PAUSE_MIN * 60)
            busy = 0
        if streak >= 3:
            print("[gemini-priority] stopping after 3 failures in a row", flush=True)
            break
    left = [a["id"] for p, a in items if a["id"] not in L.done_ids(p)]
    print("[gemini-priority] done for now: %d of %d stored, %d pending; next: %s" % (len(items) - len(left), len(items), len(left),
                                                                                  left[0] if left else "-"), flush=True)


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


WALLS_DIR = os.path.join(os.path.dirname(HERE), "data", "walls")


def entries(recs, cities, census=True):
    """Wall entries in the engine's contract. Set "city" (city wall + street asks) and set "census" apply to every set
    of the city (walls.GENERIC_SETS); a set's own entry holds only its taste answers, with its loves."""
    walls, counts = [], {}
    for ck in cities:
        cr = [r for r in recs if r["city"] == ck]
        city = [r for r in cr if r["kind"] in ("city", "street")]
        cen = census_answers(ck) if census else []
        if city:
            walls.append({"city": ck, "set": "city", "answers": [item(r) for r in city]})
        if cen:
            walls.append({"city": ck, "set": "census", "answers": [item(r) for r in cen]})
        allr = city + cen
        for sid in sorted({r["set"] for r in cr if r["kind"] == "taste"}):
            taste = [r for r in cr if r["kind"] == "taste" and r["set"] == sid]
            walls.append({"city": ck, "set": sid, "loves": taste[0].get("loves"), "answers": [item(r) for r in taste]})
            allr += taste
        by = {}
        for r in allr:
            k = "%s/%s" % (r["kind"], r.get("runner") or r["provider"])
            by[k] = by.get(k, 0) + 1
        if by:
            counts[ck] = by
    return walls, counts


def write(path, walls, meta):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w") as f:
        json.dump({"meta": meta, "walls": walls}, f, ensure_ascii=False, separators=(",", ":"))
    n = sum(len(w["answers"]) for w in walls)
    print("wrote %s: %d entries, %d answers, %.2f MB" % (os.path.relpath(path, HERE), len(walls), n, os.path.getsize(path) / 1e6))
    for ck, c in meta["counts"].items():
        print("  %s %s" % (ck, json.dumps(c, sort_keys=True)))


def cmd_build(args):
    """Default: one file per wall label in data/walls/ (wall-<N>.json, or <label>.json for a non-numeric label) plus
    data/walls/census.json; the server merges every *.json in that directory, so the census lives in one file only.
    --out: one combined file with the census too (unless --no-census)."""
    if args.census_only:
        args.walls = []
    if not args.out and any(w.lower().startswith("smoke") for w in args.walls):
        sys.exit("refusing: smoke answers never go in data/walls/ (the server serves every *.json there); pass --out")
    fh = fresh_hashes()
    per = {}
    for w in args.walls:
        recs, failed = [], []
        for r in L.load(wall_path(w)).values():
            (recs if L.is_done(r) else failed).append(r)
        if args.no_street:
            recs = [r for r in recs if r["kind"] != "street"]
        bad = [r["id"] for r in recs if P.qhash(r["phrasing"]) in fh]
        if bad:
            sys.exit("refusing: %d stored wall answers hash-match a held-out fresh ask: %s" % (len(bad), bad[:3]))
        per[w] = (recs, failed)
    meta = lambda ws, failed, counts: {"built_at": L.now(), "walls_used": ws, "prompt_v": P.PROMPT_V,  # noqa: E731
                                       "failed_not_included": sorted(r["id"] for r in failed), "counts": counts}
    if args.out:
        recs = [r for w in args.walls for r in per[w][0]]
        failed = [r for w in args.walls for r in per[w][1]]
        walls, counts = entries(recs, args.cities, not args.no_census)
        return write(args.out, walls, meta(args.walls, failed, counts))
    for w, (recs, failed) in per.items():
        if not recs:
            print("wall %s: nothing stored, no file written" % w)
            continue
        walls, counts = entries(recs, args.cities, census=False)
        write(os.path.join(WALLS_DIR, ("wall-%s.json" % w) if w.isdigit() else ("%s.json" % w)), walls, meta([w], failed, counts))
    if not args.no_census:
        walls, counts = entries([], args.cities, census=True)
        write(os.path.join(WALLS_DIR, "census.json"), walls, meta(["census"], [], counts))


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
    sets, try_these, src = P.load_sets_meta(args.sets_file)
    hoods = json.load(open(HOODS))["cities"] if os.path.exists(HOODS) else {}
    nset = sum(len(sets.get(ck, [])) for ck in P.CITY)
    ntt = len(try_these) or nset
    city = 20 * len(P.CITY)                                # per lane per wall day
    street = sum(len(hoods.get(ck, [])) for ck in P.CITY)  # per lane, once
    fresh = 20 * len(P.CITY) + 4 * nset                    # per lane: 20 plain per city + 4 with loves per set
    meter = 10 * 2 * 2 * 2                                 # per lane: 10 sets x 2 arms x 2 phrasings x 2 reps
    walls = [city + 4 * nset, city + 4 * ntt, city + 4 * ntt]  # wall 1 all sets; walls 2, 3 try-these only
    print("sets: %s (%d, %d try-these)" % (os.path.relpath(src, HERE), nset, len(try_these)))
    print("per lane: wall 1 %d (city %d + taste 4x%d), wall 2 %d, wall 3 %d (taste 4x%d try-these); street %d once;"
          " census 128 (claude stored); fresh %d; meter %d" % (walls[0], city, nset, walls[1], walls[2], ntt, street, fresh, meter))
    w = sum(walls)
    print("subscriptions (claude+codex): %d = walls %d + street %d + codex census 128 + fresh %d + meter %d (§3.6 ~1,500)" % (
        2 * w + 2 * street + 128 + 2 * fresh + 2 * meter, 2 * w, 2 * street, 2 * fresh, 2 * meter))
    q = gemini_priority(sets, try_these)
    print("gemini (free tier 20 RPD, harness cap 16/day): queue gemini-priority = %d asks: (a) 32 census hidden-gem asks "
          "(also wall #1's gem part), (b) 8 plain wall phrasings, (c) stl-cedric + stl-jason taste 8, (d) other try-these "
          "taste %d; about %d Pacific days at 16/day" % (len(q), len(q) - 48, -(-len(q) // 16)))
    print("gemini not run: free-tier 20/day: the full 64-ask census per city, the v2 copies of the 16 gem wall phrasings (the census v1 answers stand in), street asks, "
          "walls #2 and #3, fresh asks, meter")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    a = sp.add_parser("ask")
    a.add_argument("--lane", required=True, help="claude | codex | gemini | all | comma list")
    a.add_argument("--wall", required=True, help="wall number (1, 2, 3) or a label like smoke")
    a.add_argument("--kind", default="city,taste", help="city,taste,street")
    a.add_argument("--city", default="stl,nyc")
    a.add_argument("--sets", dest="set_filter", default=None, help="only these set ids (taste)")
    a.add_argument("--all-sets", action="store_true", help="taste for every set, whatever the wall")
    a.add_argument("--sets-file", default=None)
    a.add_argument("--hoods", default=None, help="comma list of neighbourhoods (street)")
    a.add_argument("--limit", type=int, default=None, help="at most N asks per lane")
    a.add_argument("--go", action="store_true", help="actually ask (default: dry run)")
    b = sp.add_parser("build")
    b.add_argument("--walls", default="1,2,3")
    b.add_argument("--city", default="stl,nyc")
    b.add_argument("--sets-file", default=None)
    b.add_argument("--out", default=None, help="one combined file instead of data/walls/<label>.json + census.json")
    b.add_argument("--no-census", action="store_true")
    b.add_argument("--census-only", action="store_true", help="write only data/walls/census.json (or --out)")
    b.add_argument("--no-street", action="store_true")
    q = sp.add_parser("queue", help="gemini-priority: spend exactly today's remaining Gemini allowance, in priority order")
    q.add_argument("name")
    q.add_argument("--already-used", type=int, default=0, help="requests made today outside the harness (console)")
    q.add_argument("--sets-file", default=None)
    q.add_argument("--go", action="store_true")
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
    elif args.cmd == "queue":
        cmd_queue(args)
    elif args.cmd == "status":
        cmd_status(args)
    else:
        cmd_plan(args)


if __name__ == "__main__":
    main()
