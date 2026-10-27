"""Day-0 parameter probes P1-P12 (~50 calls). Each prints what the live API does, so CFG is set before the gates spend
quota (UNSAID.md §4 row P, §5 K+0:00). Decisions land in out/probes[.fake].json; P9's header names in
.cache/<mode>/p9_headers.json (gitignored), which the quota guard reads.
 P1  paging: offset 0 / 50 disjoint? page=2 == offset=50?
 P2  business_rating.min: enum; what do 4 / 4.3 / 5 do?
 P3  field paths: is_closed, business_rating, neighborhood, popularity, hours, website, affinity, explainability
 P4  filter.results.entities: all IDs back, with and without a signal?
 P5  bias.trends: 'off' (pinned) vs the default (probe-only exemption from the client's pin)
 P6  kind tags: category:place:restaurant, category:place:bar, union
 P7  explainability shapes (page 1; dumped for the raw log; no shares are ever shown)
 P8  floor, 4 calls: STL and NYC x (server rating.min=4 | none): rating coverage, float32 values at the 4.3 edge,
     hours/website coverage, Tripadvisor/Resy field coverage (read, never sent), allowlist tags seen
 P9  the global bucket (5-burst, then a steady 3/s) and the rate/quota header names
 P10 distance distribution: STL and LA POINT+radius vs the locality; NYC locality vs 8 mi from Manhattan; |U| each
 P11 tie share at Qloo's default affinity, one entity love and one tag love, one 50-ID chunk each
 P12 no-signal order = popularity? (non-increasing check per city)"""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from unsaid import cities as C, cli, engine as E, stats as ST  # noqa: E402
from unsaid.qloo import (BURST, RATE, QlooError, TokenBucket, classify_rate_headers, latlon,  # noqa: E402
                         p9_headers_path, prop)

ap = cli.parser(__doc__)
ap.add_argument("--p9-seconds", type=float, default=5.0, help="steady 3/s phase of the bucket test (oracle: 30)")
args = ap.parse_args()
q = cli.client(args, "probes")
T = cli.tag(args)
out, ran, failed = {}, [], []


def probe(name):
    def deco(fn):
        try:
            out[name] = fn()
            ran.extend([name, "P7"] if name == "P3" else [name])
        except (QlooError, KeyError, IndexError, TypeError, ValueError) as e:
            failed.append(name)
            print("  %s ERROR %s%s" % (name, str(e)[:200], T))
        return fn
    return deco


def ents(d):
    return (d.get("results") or {}).get("entities") or []


def ids_of(p, label, **kw):
    try:
        d = q.insights(p, label=label, **kw)
    except QlooError as e:
        return None, e.status
    return [e["entity_id"] for e in ents(d)], d


nyc = cli.city_obj(q, "nyc")
stl = cli.city_obj(q, "stl")
print("  cities: NYC %s (%s), STL %s%s" % ((nyc.get("id") or "")[:8], nyc.get("disamb"), C.location_params(stl), T))
lv_nyc = [E.resolve_love(q, "Khruangbin", "artist"), E.resolve_love(q, "The Grand Budapest Hotel", "movie")]
lv_stl = [E.resolve_love(q, t, h) for t, h in [("The Original Kings of Comedy", "movie"),
                                                ("Frankie Beverly & Maze", "artist"), ("rib tips", "tag")]]
print("  loves: %s%s" % ([(l["text"], l.get("name"), (l.get("id") or "")[:12], l["status"]) for l in lv_nyc + lv_stl], T))
base = dict(E.base_filters(nyc, lv_nyc), take=50, **E.signal_of(lv_nyc[0]))


@probe("P1")
def p1():
    o0, _ = ids_of(dict(base), "P1 offset0")
    o50, _ = ids_of(dict(base, offset=50), "P1 offset50")
    p2, _ = ids_of(dict(base, page=2), "P1 page2")
    r = {"offset_disjoint": bool(o0 and o50 and not set(o0) & set(o50)), "page2_eq_offset50": p2 == o50,
         "n0": len(o0 or []), "n50": len(o50 or [])}
    print("  P1 paging: offset 0 vs 50 overlap %d/%d; page=2 == offset=50: %s -> engine uses offsets 0, 50%s" % (
        len(set(o0 or []) & set(o50 or [])), len(o0 or []), r["page2_eq_offset50"], T))
    return r


@probe("P2")
def p2():
    r = {}
    for v in (None, 4, 4.3, 5):
        p = dict(base)
        p.pop("filter.properties.business_rating.min", None)
        if v is not None:
            p["filter.properties.business_rating.min"] = v
        ids, d = ids_of(p, "P2 rating=%s" % v)
        if ids is None:
            r[str(v)] = "HTTP %s" % d
            continue
        rs = [prop(e, "business_rating") for e in ents(d)]
        rs = [x for x in rs if x is not None]
        r[str(v)] = "min %s over %d results" % (min(rs) if rs else None, len(ids))
    print("  P2 business_rating.min: " + "; ".join("%s -> %s" % kv for kv in r.items()) + T)
    return r


@probe("P3")
def p3():
    d = q.insights(dict(base, **{"feature.explainability": True}), label="P3/P7 fields+explain")
    e0 = (ents(d) or [{}])[0]
    paths = {}
    for f in ("is_closed", "business_rating", "neighborhood", "popularity", "hours", "website", "address"):
        paths[f] = ("properties.%s" % f if f in (e0.get("properties") or {}) else
                    "properties.geocode.%s" % f if f in ((e0.get("properties") or {}).get("geocode") or {}) else
                    f if f in e0 else "ABSENT")
    paths["affinity"] = "query.affinity" if (e0.get("query") or {}).get("affinity") is not None else (
        "affinity" if "affinity" in e0 else "ABSENT")
    paths["explainability"] = "query.explainability" if (e0.get("query") or {}).get("explainability") else "ABSENT"
    paths["location"] = "location.lat/lon" if latlon(e0) else "ABSENT"
    print("  P3 field paths: %s%s" % (paths, T))
    os.makedirs(cli.OUT, exist_ok=True)
    with open(os.path.join(cli.OUT, "probe_explain%s.json" % (".fake" if args.fake else "")), "w") as fh:
        json.dump({"first_result_query": e0.get("query"), "top_level_query": d.get("query")}, fh, indent=1)
    print("  P7 explainability shapes (page 1, raw log only) dumped to out/probe_explain*.json%s" % T)
    out["_first_ids"] = [e["entity_id"] for e in ents(d)]
    return paths


@probe("P4")
def p4():
    sub = (out.get("_first_ids") or [])[:30]
    pr = dict(E.base_filters(nyc, lv_nyc), **{"filter.results.entities": sorted(sub), "take": 50})
    ws, _ = ids_of(dict(pr, **E.signal_of(lv_nyc[0])), "P4 results+signal", timeout=3.0)
    ns, dn = ids_of(pr, "P4 results nosignal", timeout=3.0)
    print("  P4 filter.results.entities: with signal %s/%d back; no signal %s/%d back%s" % (
        len(ws or []), len(sub), len(ns or []) if ns is not None else "HTTP %s" % dn, len(sub), T))
    return {"with_signal": len(ws or []), "no_signal": len(ns or []) if ns is not None else None, "asked": len(sub)}


@probe("P5")
def p5():
    off, _ = ids_of(dict(base), "P5 trends off")
    dflt = dict(base)
    dflt.pop("bias.trends")
    try:
        dd = [e["entity_id"] for e in ents(q.insights(dflt, label="P5 trends default", unsafe_probe=True))]
    except QlooError as e:
        dd = None
    print("  P5 bias.trends: off vs default top-50 overlap %d/50, same order %s (engine pins off)%s" % (
        len(set(off or []) & set(dd or [])), off == dd, T))
    return {"overlap": len(set(off or []) & set(dd or [])), "same_order": off == dd}


@probe("P6")
def p6():
    r = {}
    for nm, tags in (("restaurant", ["urn:tag:category:place:restaurant"]), ("bar", ["urn:tag:category:place:bar"])):
        ids, _ = ids_of(dict(base, **{"filter.tags": tags}), "P6 %s only" % nm)
        r[nm] = ids or []
    un, _ = ids_of(dict(base), "P6 union")
    tg = [t.get("id") for t in q.tags("bar", tag_types=["urn:tag:category:place"], label="P6 tags")][:5]
    print("  P6 kind tags: restaurant %d, bar %d, overlap %d, union %d; category bar tags: %s%s" % (
        len(r["restaurant"]), len(r["bar"]), len(set(r["restaurant"]) & set(r["bar"])), len(un or []), tg, T))
    return {"restaurant": len(r["restaurant"]), "bar": len(r["bar"]), "union": len(un or []), "bar_tags": tg}


@probe("P8")
def p8():
    r = {}
    for ck, c, lv in (("stl", stl, lv_stl), ("nyc", nyc, lv_nyc)):
        for server in (True, False):
            p = dict(E.base_filters(c, lv), take=50, **E.signal_of(lv[0]))
            if not server:
                p.pop("filter.properties.business_rating.min")
            d = q.insights(p, label="P8 %s rating.min=%s" % (ck, 4 if server else "none"))
            es = ents(d)
            n = max(1, len(es))
            rat = [prop(e, "business_rating") for e in es]
            edge = sum(1 for x in rat if x is not None and 4.3 - 1e-4 <= float(x) < 4.3)
            ext = sum(1 for e in es if any("tripadvisor" in k.lower() for k in (e.get("properties") or {})))
            resy = sum(1 for e in es if any("resy" in k.lower() for k in (e.get("properties") or {})))
            music = sum(1 for e in es if E.excluded_kind(e) and E.is_music(e))
            junk = {}
            for e in es:
                k = E.excluded_kind(e)
                if k:
                    junk[k] = junk.get(k, 0) + 1
            U, dr = E.floor(es, c)
            key = "%s_%s" % (ck, "server4" if server else "noserver")
            r[key] = {"n": len(es), "rating_cov": sum(1 for x in rat if x is not None) / n,
                      "ge43": sum(1 for x in rat if x is not None and float(x) >= 4.3 - 1e-4) / n,
                      "edge_float32": edge, "hours_cov": sum(1 for e in es if prop(e, "hours")) / n,
                      "website_cov": sum(1 for e in es if prop(e, "website")) / n,
                      "tripadvisor_cov": ext / n, "resy_cov": resy / n, "allowlist_hits": junk, "music": music,
                      "U": len(U)}
            x = r[key]
            print("  P8 %s: n %d, rating on %.0f%%, >=4.3 %.0f%% (float32 edge %d), hours %.0f%%, website %.0f%%, "
                  "Tripadvisor %.0f%%, Resy %.0f%% (read only), allowlist %s (music venue %d), U %d%s" % (
                      key, x["n"], 100 * x["rating_cov"], 100 * x["ge43"], edge, 100 * x["hours_cov"],
                      100 * x["website_cov"], 100 * x["tripadvisor_cov"], 100 * x["resy_cov"], junk or "none", music,
                      len(U), T))
    return r


@probe("P9")
def p9():
    names = classify_rate_headers(q.headers_seen)
    burst = []
    secs = min(args.p9_seconds, 1.0) if args.fake else args.p9_seconds
    saved = (q.refresh, q.bucket)
    q.refresh = True                                  # the bucket test must reach the network
    if q.bucket is None:                              # fake mode: exercise the same bucket shape locally
        q.bucket = TokenBucket(RATE, BURST)
    t0 = time.monotonic()
    total = 5 + int(3 * secs)
    try:
        for k in range(total):
            tk = time.monotonic()
            try:
                q.get("/search", {"query": "St. Louis", "types": "urn:entity:locality", "take": 1},
                      label="P9 bucket", timeout=12.0)
                st = 200
            except QlooError as e:
                st = e.status
            burst.append((round(tk - t0, 2), st))
    finally:
        q.refresh, q.bucket = saved
    span = burst[-1][0] if burst else 0
    n429 = sum(1 for _, s in burst if s == 429)
    names = classify_rate_headers(q.headers_seen) if q.headers_seen else names
    rec = {"recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "mode": "fake" if args.fake else "live",
           "rate_headers": names["all"], "month_limit": names["month_limit"], "month_remaining": names["month_remaining"],
           "values": {k: v for k, v in q.headers_seen.items() if k.lower() in names["all"]}}
    os.makedirs(os.path.dirname(p9_headers_path(args.fake)), exist_ok=True)
    with open(p9_headers_path(args.fake), "w") as fh:
        json.dump(rec, fh, indent=1)
    print("  P9 bucket: %d calls in %.1f s (5-burst + 3/s for %.0f s; global bucket 3/s, burst 5), 429s %d; rate "
          "headers %s; quota guard reads %s / %s%s" % (len(burst), span, secs, n429, names["all"] or "none",
                                                     names["month_remaining"], names["month_limit"], T))
    return {"calls": len(burst), "n429": n429, "headers": rec}


def dist_stats(es, center, R):
    ds = sorted(C.haversine_mi(latlon(e), center) for e in es if latlon(e))
    if not ds:
        return {"n": 0}
    qn = lambda f: round(ds[min(len(ds) - 1, int(f * len(ds)))], 1)  # noqa: E731
    return {"n": len(ds), "p50": qn(0.5), "p90": qn(0.9), "max": round(ds[-1], 1),
            "outside": sum(1 for d in ds if d > R)}


@probe("P10")
def p10():
    r = {}
    la = cli.city_obj(q, "la")
    for ck, c, lv in (("stl", stl, lv_stl), ("la", la, lv_stl), ("nyc", nyc, lv_nyc)):
        variants = [("point" if c["mode"] == "point" else "locality", c)]
        if c["mode"] == "point":     # compare with the locality (C1 search)
            res = q.search(C.CITIES[ck]["query"], types="urn:entity:locality", take=3, label="P10 C1 %s" % ck)
            if res:
                variants.append(("locality", dict(c, mode="locality", id=res[0]["entity_id"])))
        for nm, cc in variants:
            p = dict(E.base_filters(cc, lv), take=50, **E.signal_of(lv[0]))
            es = ents(q.insights(p, label="P10 %s %s" % (ck, nm)))
            U, dr = E.floor(es, c)
            s = dist_stats(es, c["center_latlon"], c["radius_mi"])
            s["U_after_floor"] = len(U)
            r["%s_%s" % (ck, nm)] = s
            print("  P10 %s %-8s: n %s, distance p50 %s p90 %s max %s mi, outside %s mi: %s; U after floor %d%s" % (
                ck.upper(), nm, s.get("n"), s.get("p50"), s.get("p90"), s.get("max"), c["radius_mi"], s.get("outside"),
                len(U), T))
    return r


@probe("P11")
def p11():
    p = dict(E.base_filters(stl, lv_stl), take=50, **E.signal_of(lv_stl[0]))
    es = ents(q.insights(p, label="P11 pool"))
    U, _ = E.floor(es, stl)
    ids = [e["entity_id"] for e in U][:50]
    r = {}
    for l in (lv_stl[1], lv_stl[2]):
        rs = E.rescore(q, stl, lv_stl, ids, l, "P11 %s" % l["kind"])
        r[l["kind"]] = {"tie_share": rs["tie_share"], "coverage": rs["coverage"], "n": len(ids)}
        print("  P11 tie share (%s love %s): %d of %d at Qloo's default affinity (%.0f%%; thin_taste above 30%%), "
              "coverage %.2f%s" % (l["kind"], l["text"], len(rs["tied"]), len(ids), 100 * rs["tie_share"],
                                   rs["coverage"], T))
    return r


@probe("P12")
def p12():
    r = {}
    for ck in ("nyc", "stl", "la"):
        c = cli.city_obj(q, ck)
        es = ents(q.insights(dict(E.base_filters(c, []), take=50), label="P12 no-signal %s" % ck))
        pops = [E.popularity(e) for e in es]
        viol = sum(1 for a, b in zip(pops, pops[1:]) if b > a + 1e-12)
        rk = {e["entity_id"]: k + 1 for k, e in enumerate(es)}
        rho = ST.spearman(rk, ST.rank({e["entity_id"]: E.popularity(e) for e in es}))
        use = "popularity" if es and rho == rho and rho >= E.CFG["NS_IS_POP_RHO"] else "nosignal"
        r[ck] = {"n": len(es), "violations": viol, "rho": rho, "baseline": use}
        print("  P12 %s no-signal order: %d results, %d popularity increases, rho(order, popularity) %s (>= %.2f = "
              "popularity) -> CFG BASELINE=%s%s%s" % (ck.upper(), len(es), viol, cli.f(rho), E.CFG["NS_IS_POP_RHO"], use,
                                                      "; RHO_RES undefined (base = popularity)" if use == "popularity"
                                                      else "; RHO_RES = partial rho | no-signal (C5, +~5 calls/query)", T))
    return r


summary = {k: v for k, v in out.items() if not k.startswith("_")}
summary["ran_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
summary["fake"] = args.fake
with open(os.path.join(cli.OUT, "probes%s.json" % (".fake" if args.fake else "")), "w") as fh:
    json.dump(summary, fh, indent=1, default=str)
ok = not failed
print("Probes P1-P12: %d ran, %d failed%s -> %s%s | decisions in out/probes%s.json; R sets CFG" % (
    len(ran), len(failed), (" (" + ", ".join(failed) + ")") if failed else "", cli.verdict(ok), T,
    ".fake" if args.fake else ""))
cli.finish(q, args, "probes")
