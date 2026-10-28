"""Per-city "fit for everyone" prior from an anchor panel sampled from Qloo (30 Oct; replaces the 28 Oct prior built
from the city's other preset sets, which was 9 author-written personas and covered only part of each pool).

  python3 -I build_priors.py --city stl --budget 1300 --frozen     # ~10 calls per anchor (STL universe ~460)
  python3 -I build_priors.py --city nyc --budget 2800 --frozen     # ~25 calls per anchor (NYC universe ~1,150)

1. Anchor panel (data/priors/anchors-<city>.json; reused when present, --resample redraws). ~100 single-love tastes
   sampled from Qloo, not chosen by us. Per entity type, a fixed quota (artist 25, movie 20, tv_show 20, brand 15,
   book 10, podcast 10). The type's candidates are Qloo's own most popular entities of that type: insights
   filter.type=<type>, filter.popularity.min=0.9, offsets 0/50/100/150 (take 50; no signal), up to 200 in Qloo's
   order. Genres are Qloo's tags on those entities (urn:tag:genre:*; a type with none uses urn:tag:category:*);
   a genre counts when 3+ candidates carry it and at most half do (catch-alls like "Podcasts" carry no spread).
   Stratified draw with random.Random("<seed>:<city>:<type>") (seed "unsaid-anchors-v1"): shuffle the sorted genre
   list, then round-robin over it, each turn drawing one not-yet-drawn candidate carrying that genre, until the
   type has 1.5x its quota in draw order. In that order, an anchor is kept when it is live (first rescoring chunk
   below: under 95% of the places at Qloo's default affinity, the engine's DEAD_TIE) until the quota is met.
2. Universe: every place that can enter a pool here: the city-wide no-signal pool pages (offsets 0-250, the
   engine's OFFSETS + EXTRA_OFFSETS + EXTRA_OFFSETS_2) plus the U of each of the city's sets in data/sets.json,
   all through the engine's floor.
3. Per anchor: Qloo's affinity for every universe place under that one love, with the engine's own rescoring
   (base filters + filter.results.entities in chunks of 48 + 2 chunk anchors, the same CHUNK/ANCHORS). The two
   chunk anchors are the city's two most popular no-signal places, so every chunk can be checked: a chunk whose
   anchors drift more than ANCHOR_DRIFT_MAX from their median is dropped (its places count as unscored there).
4. A place is in an anchor's top when it has a non-default affinity and ranks in the top (1 - PRIOR_TOP) = 30% of
   the places that anchor scored. The engine's fit for everyone = (hits + 0.5) / (n + 1) over the live anchors
   that are not one of the query's loves; a place no anchor scored, or outside the universe, gets the panel
   median, never zero. Then a percentile within the query's U, and lift = fit for you - max(popularity, that).

Output: data/priors/<city>.json {"method": "anchors", "anchors": [...], "scored": [ids], "top": {id: [anchor idx]},
"miss": {id: [anchor idx that did not score it]}, ...}. Qloo-derived and keyed by Qloo IDs, so data/priors/ is
gitignored (UNSAID.md §5.2); server/push_priors.py ships it to Render. Calls are cached (--frozen: no TTL), so a
rerun after a budget stop resumes at no cost for what is done. --quota-floor (25,000) stops before the month's
remaining Qloo calls (x-month-ratelimit-remaining) would drop below it."""
import json, os, random, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from unsaid import cli, engine as E, stats as ST  # noqa: E402
from unsaid.qloo import BudgetExceeded, affinity, is_default_affinity, quota_state  # noqa: E402

PROCEDURE = "unsaid-anchors-v1"
QUOTAS = [("artist", 25), ("movie", 20), ("tv_show", 20), ("brand", 15), ("book", 10), ("podcast", 10)]
POP_MIN, PAGES, OVERSAMPLE = 0.9, (0, 50, 100, 150), 1.5

ap = cli.parser(__doc__)
ap.add_argument("--out", default=os.path.join(cli.DATA, "priors"))
ap.add_argument("--seed", default=PROCEDURE)
ap.add_argument("--scale", type=float, default=1.0, help="multiply every type quota (1.0 = 100 anchors)")
ap.add_argument("--resample", action="store_true", help="redraw the anchor panel even if anchors-<city>.json exists")
ap.add_argument("--dry", action="store_true", help="build the universe, print the projected calls, stop")
ap.add_argument("--quota-floor", type=int, default=25000, help="stop before Qloo's month remaining drops below this")
args = ap.parse_args()
q = cli.client(args, "build_priors")
E.CFG["CAP_ENABLED"] = False
os.makedirs(args.out, exist_ok=True)


def quota_left():
    return quota_state().get("remaining")


def guard(next_calls):
    rem = quota_left()
    if rem is not None and rem - next_calls < args.quota_floor:
        raise SystemExit("STOP: month remaining %d - next %d would cross the floor %d" % (rem, next_calls,
                                                                                         args.quota_floor))


def genre_tags(e, prefix):
    return sorted({t["id"] for t in e.get("tags") or [] if isinstance(t, dict) and (t.get("id") or "").startswith(prefix)})


def candidates(city_key, typ, quota):
    """Qloo's popular entities of one type, genre-stratified in a seeded order (procedure in the module doc)."""
    pool, seen = [], set()
    for off in PAGES:
        p = {"filter.type": "urn:entity:" + typ, "filter.popularity.min": POP_MIN, "take": 50}
        if off:
            p["offset"] = off
        for e in (q.insights(p, label="anchor pool %s o%d" % (typ, off)).get("results") or {}).get("entities") or []:
            if e["entity_id"] not in seen:
                seen.add(e["entity_id"])
                pool.append(e)
    prefix = "urn:tag:genre:" if any(genre_tags(e, "urn:tag:genre:") for e in pool) else "urn:tag:category:"
    carriers = {}
    for e in pool:
        for t in genre_tags(e, prefix):
            carriers.setdefault(t, []).append(e)
    genres = sorted(t for t, es in carriers.items() if 3 <= len(es) <= len(pool) / 2.0)
    rng = random.Random("%s:%s:%s" % (args.seed, city_key, typ))
    rng.shuffle(genres)
    want, out, used = int(round(OVERSAMPLE * quota)), [], set()
    while len(out) < want and genres:
        progressed = False
        for g in genres:
            if len(out) >= want:
                break
            left = sorted((e for e in carriers[g] if e["entity_id"] not in used), key=lambda e: e["entity_id"])
            if not left:
                continue
            e = rng.choice(left)
            used.add(e["entity_id"])
            out.append({"id": e["entity_id"], "name": e.get("name"), "type": typ,
                        "genre": g, "genre_name": next((t.get("name") for t in e.get("tags") or []
                                                         if isinstance(t, dict) and t.get("id") == g), None),
                        "popularity": e.get("popularity")})
            progressed = True
        if not progressed:
            break
    return out, {"pool": len(pool), "genres": len(genres), "genre_prefix": prefix}


def universe(c, city_key):
    """Every place that can enter a pool here, through the engine's floor."""
    offs = E.CFG["OFFSETS"] + E.CFG["EXTRA_OFFSETS"] + E.CFG["EXTRA_OFFSETS_2"]
    pool, _ = E.per_love_pools(q, c, [], offsets=offs)
    u0, _ = E.floor(pool, c)
    byid = {e["entity_id"]: e for e in u0}
    top2 = [e["entity_id"] for e in sorted(u0, key=lambda e: (-E.popularity(e), e["entity_id"]))[:E.CFG["ANCHORS"]]]
    n_sets, from_sets = 0, set()
    sets = json.load(open(os.path.join(cli.DATA, "sets.json")))["sets"]
    for s in sets:
        if s["city"] != city_key:
            continue
        loves = cli.loves(q, [tuple(x) for x in s["loves"]])
        if loves is None:
            print("  %s: a love is not in Qloo; its U is not in the universe" % s["id"])
            continue
        r = E.run(q, c, loves, {"answers": [], "source": "none (prior universe)"}, street_check=None)
        for e in r.get("_U") or []:
            from_sets.add(e["entity_id"])
            byid.setdefault(e["entity_id"], e)
        n_sets += 1
    return sorted(byid), top2, {"nosignal": len(u0), "sets": n_sets, "from_sets": len(from_sets),
                                "sets_only": len(from_sets - {e["entity_id"] for e in u0})}


def first_chunk_live(c, ids, love, chunk_anchors):
    """The engine's first rescoring chunk for this love (the same request, so rescore() reuses it from the cache).
    Live = under DEAD_TIE of the returned places at Qloo's default affinity."""
    ids = sorted(ids)
    rest = [i for i in ids if i not in chunk_anchors][:E.CFG["CHUNK"]]
    p = dict(E.base_filters(c, []), take=E.CFG["TAKE"])
    p.update(E.signal_of(love))
    p["filter.results.entities"] = sorted(set(chunk_anchors + rest))
    es = (q.insights(p, label="prior %s c1" % love["text"][:18], timeout=E.TIMEOUT_RESCORE).get("results") or {}) \
        .get("entities") or []
    a = [affinity(e) for e in es if affinity(e) is not None]
    tie = sum(1 for x in a if is_default_affinity(x)) / float(len(a)) if a else 1.0
    return tie < E.CFG["DEAD_TIE"], tie


def build(city_key):
    c = cli.city_obj(q, city_key)
    print("\n== %s  month remaining %s" % (city_key.upper(), quota_left()))
    U, chunk_anchors, usrc = universe(c, city_key)
    n_chunks = -(-(len(U) - len(chunk_anchors)) // E.CFG["CHUNK"])
    print("  universe %d places (no-signal %d, from %d sets %d, only in sets %d); %d calls per anchor; chunk "
          "anchors %s" % (len(U), usrc["nosignal"], usrc["sets"], usrc["from_sets"], usrc["sets_only"], n_chunks,
                          chunk_anchors))
    if args.dry:
        print("  projected: ~%d calls for %d anchors (+ ~24 to draw them, + 1 per dead candidate)" % (
            n_chunks * int(round(100 * args.scale)), int(round(100 * args.scale))))
        return
    ap_path = os.path.join(args.out, "anchors-%s.json" % city_key)
    panel = None
    if os.path.exists(ap_path) and not args.resample:
        with open(ap_path) as f:
            panel = json.load(f)
        if panel.get("procedure") != args.seed or panel.get("scale") != args.scale:
            panel = None
    if panel is None:
        draws, meta = [], {}
        for typ, quota in QUOTAS:
            quota = max(1, int(round(quota * args.scale)))
            cand, meta[typ] = candidates(city_key, typ, quota)
            meta[typ]["quota"] = quota
            draws.append((typ, quota, cand))
            print("  %-8s pool %3d, %2d genres, %2d drawn for quota %d" % (typ, meta[typ]["pool"], meta[typ]["genres"],
                                                                         len(cand), quota))
        panel = {"procedure": args.seed, "scale": args.scale, "city": city_key, "pop_min": POP_MIN,
                 "pages": list(PAGES), "oversample": OVERSAMPLE, "types": meta, "drawn": draws,
                 "drawn_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    anchors = []
    for typ, quota, cand in panel["drawn"]:
        kept = 0
        for a in cand:
            if kept >= quota:
                break
            guard(1)
            love = {"kind": "entity", "id": a["id"], "text": a["name"] or a["id"]}
            live, tie = first_chunk_live(c, U, love, chunk_anchors)
            anchors.append(dict(a, live=live, c1_tie=round(tie, 4)))
            kept += live
        if kept < quota:
            print("  %s: only %d live of quota %d" % (typ, kept, quota))
    panel["anchors"] = [{k: a[k] for k in ("id", "name", "type", "genre", "genre_name", "live")} for a in anchors]
    with open(ap_path, "w") as f:
        json.dump(panel, f, indent=1, ensure_ascii=False)
    live = [k for k, a in enumerate(anchors) if a["live"]]
    print("  anchors: %d live of %d screened -> %s" % (len(live), len(anchors), ap_path))

    pop = {}
    affs, done = {}, 0
    for k in live:
        a = anchors[k]
        guard(n_chunks)
        love = {"kind": "entity", "id": a["id"], "text": a["name"] or a["id"]}
        try:
            rs = E.rescore(q, c, [], U, love, "prior %s" % love["text"][:18], anchors=chunk_anchors, on_drift="drop")
        except BudgetExceeded as e:
            print("  " + str(e))
            break
        affs[k] = rs["aff"]
        for i, ent in rs["ents"].items():
            pop.setdefault(i, E.popularity(ent))
        a.update({"coverage": round(rs["coverage"], 4), "tie_share": round(rs["tie_share"], 4),
                  "drift": rs["drift"], "drifted_chunks": rs["drifted_chunks"],
                  "unverified_chunks": rs["unverified_chunks"], "failed_chunks": rs["failed"]})
        done += 1
        if done % 10 == 0:
            print("  %d of %d anchors rescored; month remaining %s" % (done, len(live), quota_left()), flush=True)
    for k in live:                      # an anchor that did not finish is not live in the prior
        anchors[k]["live"] = k in affs
    scored = sorted(set().union(*[set(v) for v in affs.values()])) if affs else []
    top, miss = {}, {}
    pop_rank = ST.rank({i: pop.get(i, 0.0) for i in scored}) if scored else {}
    for k, aff in affs.items():
        r = ST.rank(aff)                                     # 1 = highest affinity among the places it scored
        cut = (1 - E.CFG["PRIOR_TOP"]) * len(aff)
        for i in aff:
            if r[i] <= cut and not is_default_affinity(aff[i]):
                top.setdefault(i, []).append(k)
        for i in scored:
            if i not in aff:
                miss.setdefault(i, []).append(k)
        sc = [i for i in aff if not is_default_affinity(aff[i])]
        anchors[k]["rho_pop"] = round(ST.spearman({i: r[i] for i in sc}, pop_rank), 3) if len(sc) > 2 else None
    nl = len(affs)
    shares = sorted((len(top.get(i, ())) + 0.5) / (nl - len(miss.get(i, ())) + 1.0) for i in scored)
    med = shares[(len(shares) - 1) // 2] if shares else 0.5
    drifted = sum(1 for k in affs if anchors[k]["drifted_chunks"])
    doc = {"city": city_key, "built_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "engine_v": E.ENGINE_V,
           "method": "anchors", "procedure": args.seed,
           "definition": "fit for everyone = share of the live anchors (single-love Qloo tastes, not this query's "
                         "loves) that rank the place in their top %d%% of the city universe; no score -> the median"
                         % round(100 * (1 - E.CFG["PRIOR_TOP"])),
           "anchors": [{kk: a.get(kk) for kk in ("id", "name", "type", "genre_name", "live", "c1_tie", "coverage",
                                                  "tie_share", "drift", "drifted_chunks", "rho_pop")} for a in anchors],
           "universe": len(U), "universe_sources": usrc, "chunk_anchors": chunk_anchors,
           "scored": scored, "unscored": len(U) - len(scored), "top": top, "miss": miss,
           "median_share": med, "anchors_live": nl, "anchors_with_drift": drifted,
           "qloo_calls_total_run": q.calls["network"]}
    with open(os.path.join(args.out, "%s.json" % city_key), "w") as fh:
        json.dump(doc, fh, separators=(",", ":"))
    n_top = sorted(len(v) for v in top.values())
    print("%s: %d live anchors; universe %d, scored %d (%.1f%%), unscored -> median %.3f; places in no anchor's top %d; "
          "anchors with a dropped drift chunk %d; month remaining %s -> %s" % (
              city_key.upper(), nl, len(U), len(scored), 100.0 * len(scored) / max(1, len(U)), med,
              len(scored) - len(top), drifted, quota_left(), os.path.join(args.out, city_key + ".json")))
    if n_top:
        print("  hits per place: median %d, max %d of %d" % (n_top[len(n_top) // 2], n_top[-1], nl))


print("month remaining at start: %s (floor %d)" % (quota_left(), args.quota_floor))
for city in cli.cities(args):
    build(city)
gi = os.path.join(args.out, ".gitignore")
if not os.path.exists(gi):
    with open(gi, "w") as fh:
        fh.write("# Qloo-derived numbers keyed by Qloo IDs: never in git (UNSAID.md 5.2)\n*.json\n")
cli.finish(q, args, "build_priors")
