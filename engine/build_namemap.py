"""C7 name map (30 Oct): the AI-answer names are fixed per city, so the place-name /search lookups a fresh query would
make (C7: name -> Qloo place, city-scoped) are resolved once, here, and the engine reads the stored /search results
instead of calling. The stored result for a name is exactly what /search returns for the engine's own parameters
(query, types, take, location, radius), so strikes and cards are identical; a name not in the map is still searched.

  python3 -I build_namemap.py --budget 1500           # both cities: the cache first (0 calls), then live misses
  python3 -I build_namemap.py --city stl --budget 0   # cache only

Names: every distinct name in data/walls for the city (all lanes, city and set walls) that C7 could search: it
shares a distinctive token with some place name in the city's candidate universe (data/priors/<city>.json scored
places and the card lines' names; C7 never searches a name sharing no token with the pool). Live misses go in
order of how many answers name them. Output: data/namemap/<city>.json (Qloo-derived: gitignored, pushed to Render
by server/push_priors.py as namemap-<city>.json)."""
import argparse, collections, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from unsaid import engine as E, matcher as M, walls as W, cli  # noqa: E402
from unsaid.qloo import Qloo, BudgetExceeded  # noqa: E402

ROOT = os.path.dirname(cli.KIT)
KEEP_PROPS = ("is_closed", "address", "business_rating")


def slim(r):
    """What the engine reads from a /search result (C7): id, name, kinds/tags, is_closed."""
    return {"entity_id": r.get("entity_id"), "name": r.get("name"), "subtype": r.get("subtype"),
            "types": r.get("types"),
            "tags": [{"id": t.get("id"), "name": t.get("name")} for t in r.get("tags") or [] if isinstance(t, dict)],
            "properties": {k: (r.get("properties") or {}).get(k) for k in KEEP_PROPS
                           if (r.get("properties") or {}).get(k) is not None}}


def universe_tokens(city):
    toks = set()
    try:
        lines = json.load(open(os.path.join(ROOT, "data", "lines", "%s.json" % city))).get("lines") or {}
        for v in lines.values():
            toks.update(M.distinctive(v.get("name") or ""))
    except (OSError, ValueError):
        pass
    return toks


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--city", choices=["nyc", "stl", "both"], default="both")
    ap.add_argument("--walls", default=os.path.join(ROOT, "data", "walls"))
    ap.add_argument("--out", default=os.environ.get("UNSAID_NAMEMAP_DIR") or os.path.join(ROOT, "data", "namemap"))
    ap.add_argument("--budget", type=int, default=0, help="live /search calls for names the cache lacks")
    ap.add_argument("--all-names", action="store_true", help="every wall name, not only those sharing a pool token")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    cities = ["nyc", "stl"] if args.city == "both" else [args.city]
    live = Qloo(frozen=True, budget=args.budget)
    total_live = 0
    for city in cities:
        c = cli.city_obj(live, city)
        lat, lon = c["center_latlon"]
        params = {"types": E.PLACE, "take": 5, "location": "%s,%s" % (lat, lon), "radius_mi": E.CFG["SEARCH_RADIUS_MI"]}
        freq = collections.Counter()
        for w in W.load_file(args.walls)["walls"]:
            if W._ckey(w.get("city")) != city:
                continue
            for a in w.get("answers") or []:
                for n in a.get("names") or []:
                    raw = n["name"] if isinstance(n, dict) else n
                    if raw:
                        freq[raw] += 1
        utoks = universe_tokens(city)
        ti = M.TokenIndex(utoks) if utoks else None
        names = [r for r, _ in freq.most_common()
                 if args.all_names or ti is None or any(ti.any_eq(t) for t in M.distinctive(r))]
        fp = os.path.join(args.out, "%s.json" % city)
        doc = json.load(open(fp)) if os.path.exists(fp) else {}
        if doc.get("params") != params:
            doc = {"names": {}}
        got = doc["names"]
        cached = Qloo(frozen=True, budget=0)
        hit = miss = n_live = 0
        todo = []
        for raw in names:
            if raw in got:
                continue
            try:
                res = cached.search(raw, label="C7 name", **params)
                got[raw] = [slim(r) for r in res]
                hit += 1
            except BudgetExceeded:
                cached.calls["network"] = 0
                todo.append(raw)
        for raw in todo:
            try:
                res = live.search(raw, label="C7 name", **params)
            except BudgetExceeded:
                miss += 1
                continue
            except Exception:
                miss += 1
                continue
            got[raw] = [slim(r) for r in res]
            n_live += 1
        total_live += n_live
        doc.update({"city": city, "params": params, "built_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    "method": "Qloo /search per AI-answer name (the engine's C7 parameters), stored as returned"})
        with open(fp, "w") as fh:
            json.dump(doc, fh, ensure_ascii=False)
        print("%s: %d distinct wall names, %d C7-searchable; map %d (from cache %d, live %d), left unmapped %d" % (
            city.upper(), len(freq), len(names), len(got), hit, n_live, miss), flush=True)
    print("build_namemap: QLOO_NETWORK_CALLS=%d (budget %d)" % (live.calls["network"], args.budget))


if __name__ == "__main__":
    main()
