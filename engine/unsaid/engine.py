"""UNSAID engine v3 (spec: ../../engine-v3.md). One query = city + up to 3 loves + a wall of AI answers.

Steps (call ids as in engine-v3.md §3):
  C1 city      /search types=urn:entity:locality
  C2 loves     /search (typed) -> entity; or /v2/tags -> tag
  C4 pool P    /v2/insights taste signal, identical base filters, take=50, pages 1..4 (page; offset fallback)
  floor        client side: business_rating >= 4.3 and is_closed != true -> the fixed set U
  C5 baseline  /v2/insights NO signal, same filters, filter.results.entities=U in chunks of 48 + 2 anchors
  C7 strike    matcher over U (+ /search scoped to the city for unmatched names)
  C6 hold      /v2/insights drop-one signals over S = U - struck, chunked the same way
  order        kept (holds >= n-1) by lift, then taste rank; skeptic on the top 10; 7 cards
"""
import math

from unsaid import matcher as M
from unsaid import stats as ST
from unsaid.qloo import affinity, aggregate_explain, explain_items, latlon, prop, tag_ids

CFG = {
    "KIND_TAGS": ["urn:tag:genre:place:restaurant", "urn:tag:genre:place:restaurant:bar"],
    "RATING_SERVER": 4,          # filter.properties.business_rating.min is an enum 1..5 (deep dive); 4.3 is not valid
    "RATING_CLIENT": 4.3,        # the real floor, applied to properties.business_rating
    "PAGES": 4, "PAGES_MAX": 6, "U_TARGET": 180, "TAKE": 50,   # page past 4 only while |U| < 180
    "CHUNK": 48, "ANCHORS": 2,   # 48 new IDs + 2 anchors repeated in every chunk = 50 = take
    "BIAS_TRENDS": "off",        # pinned in every call (default for places is "medium"); probe P5 checks the effect
    "PAGING": "page",            # switched to "offset" automatically if page 2 repeats page 1 (probe P1)
    "HOLD_FRAC": 1.0 / 3,
    "N_CARDS": 7, "SKEPTIC_TOP": 10,
    "SEARCH_RADIUS_MI": 15,
    "FLAT_RHO": 0.90, "THIN_POOL": 100, "DOMINANT": 0.6, "DEAD": 0.1,
    "ANCHOR_DRIFT_MAX": 0.005,
}
PLACE = "urn:entity:place"


# ---------------------------------------------------------------- resolve
def resolve_city(q, query, region=None):
    res = q.search(query, types="urn:entity:locality", take=5, label="C1 city")
    cands = []
    for r in res:
        ll = latlon(r)
        cands.append({"id": r["entity_id"], "name": r.get("name"), "lat": ll[0] if ll else None,
                      "lon": ll[1] if ll else None, "disamb": r.get("disambiguation") or prop(r, "disambiguation", default="")})
    if not cands:
        return {"status": "needs_input", "reason": "city not found", "candidates": []}
    pick = None
    if region:
        pick = next((c for c in cands if region.lower() in (c["disamb"] or "").lower()), None)
        if pick is None:
            return {"status": "needs_input", "reason": "'%s' resolves to %s, not %s" % (query, cands[0]["disamb"], region),
                    "candidates": cands}
    else:
        pick = cands[0]
    out = dict(pick)
    out["status"] = "ok"
    out["candidates"] = cands
    return out


def resolve_love(q, text, hint=None):
    if hint == "tag":
        tags = q.tags(text, take=5, label="C2 love tag") or q.tags(text, take=5, semantic=True, label="C2 love tag~")
        if tags:
            t = tags[0]
            return {"text": text, "kind": "tag", "id": t.get("id") or t.get("tag_id"), "name": t.get("name"),
                    "type": t.get("type"), "status": "ok", "is_place": False}
        return {"text": text, "status": "needs_input", "reason": "no tag matches"}
    types = "urn:entity:%s" % hint if hint else None
    res = q.search(text, types=types, take=5, label="C2 love")
    if res:
        exact = [r for r in res if M.norm(r.get("name", "")) == M.norm(text)]
        r = (exact or res)[0]
        sub = r.get("subtype") or (r.get("types") or [""])[0]
        return {"text": text, "kind": "entity", "id": r["entity_id"], "name": r.get("name"), "type": sub,
                "status": "ok" if exact else "confirm", "is_place": sub == PLACE,
                "alternatives": [x.get("name") for x in res[1:4]]}
    tags = q.tags(text, take=5, semantic=True, label="C2 love tag~")
    if tags:
        t = tags[0]
        return {"text": text, "kind": "tag", "id": t.get("id"), "name": t.get("name"), "type": t.get("type"),
                "status": "confirm", "is_place": False}
    return {"text": text, "status": "needs_input", "reason": "no entity or tag matches"}


# ---------------------------------------------------------------- parameters
def signal(loves):
    p = {}
    ents = sorted(l["id"] for l in loves if l.get("kind") == "entity")
    tags = sorted(l["id"] for l in loves if l.get("kind") == "tag")
    if ents:
        p["signal.interests.entities"] = ents
    if tags:
        p["signal.interests.tags"] = tags
    return p


def base_filters(city, loves, kind_tags=None):
    """Identical in every call of one query; only the signal (and the results restriction) changes."""
    p = {"filter.type": PLACE,
         "filter.location": city["id"],                        # locality ID; documented padding applies
         "filter.tags": sorted(kind_tags or CFG["KIND_TAGS"]),
         "operator.filter.tags": "union",
         "filter.properties.business_rating.min": CFG["RATING_SERVER"],
         "bias.trends": CFG["BIAS_TRENDS"]}
    seeds = sorted(l["id"] for l in loves if l.get("is_place"))
    if seeds:
        p["filter.exclude.entities"] = seeds                 # a seed place never appears as a card
    return p


# ---------------------------------------------------------------- C4 taste pool
def taste_pool(q, city, loves, pages=None, kind_tags=None, label="C4 pool", adaptive=True):
    """Pages 1..PAGES always; then keeps paging (to PAGES_MAX) while the floored set U is below U_TARGET.
    The server floor can only be 4 (enum), so the 4.3 client floor removes ~1/3 and a fixed 4 pages can fall short."""
    pages = pages or CFG["PAGES"]
    max_pages = max(pages, CFG["PAGES_MAX"]) if adaptive else pages
    base = dict(base_filters(city, loves, kind_tags))
    base.update(signal(loves))
    base["feature.explainability"] = True
    base["take"] = CFG["TAKE"]
    seen, pool, first_resp, prev = set(), [], None, None
    diag = {"pages": 0, "paging": CFG["PAGING"], "dupes": 0, "nonmonotone": 0, "page_repeat": False}
    for k in range(1, max_pages + 1):
        if k > pages and len(floor(pool)[0]) >= CFG["U_TARGET"]:
            break
        p = dict(base)
        if diag["paging"] == "page":
            p["page"] = k
        else:
            p["offset"] = (k - 1) * CFG["TAKE"]
        resp = q.insights(p, label="%s p%d" % (label, k))
        ents = (resp.get("results") or {}).get("entities") or []
        ids = [e["entity_id"] for e in ents]
        if k >= 2 and prev is not None and ids and set(ids) == set(prev) and diag["paging"] == "page":
            diag["page_repeat"] = True
            diag["paging"] = "offset"
            p.pop("page")
            p["offset"] = (k - 1) * CFG["TAKE"]
            resp = q.insights(p, label="%s p%d (offset)" % (label, k))
            ents = (resp.get("results") or {}).get("entities") or []
            ids = [e["entity_id"] for e in ents]
        if k == 1:
            first_resp = resp
        diag["pages"] += 1
        for e in ents:
            if e["entity_id"] in seen:
                diag["dupes"] += 1
                continue
            seen.add(e["entity_id"])
            e["_pos"] = len(pool) + 1
            pool.append(e)
        prev = ids
        if len(ents) < CFG["TAKE"]:
            break
    affs = [affinity(e) for e in pool]
    diag["nonmonotone"] = sum(1 for a, b in zip(affs, affs[1:]) if a is not None and b is not None and b > a + 1e-9)
    return pool, first_resp or {}, diag


def floor(pool):
    U, drop = [], {"closed": 0, "rating": 0, "no_rating": 0}
    for e in pool:
        if prop(e, "is_closed") is True:
            drop["closed"] += 1
            continue
        r = prop(e, "business_rating")
        if r is None:
            drop["no_rating"] += 1
            continue
        if float(r) < CFG["RATING_CLIENT"]:
            drop["rating"] += 1
            continue
        U.append(e)
    return U, drop


# ---------------------------------------------------------------- C5/C6 rescoring over a fixed set
def rescore(q, city, loves_all, ids, sig_loves, label, explain=False):
    """Affinity of every id in `ids` under the signal of `sig_loves` (None/[] = no signal), with the same base
    filters. Chunks of 48 + 2 anchors; anchors give a drift check that scores merge across chunks."""
    ids = list(ids)
    anchors = ids[:CFG["ANCHORS"]]
    rest = [i for i in ids if i not in anchors]
    chunks = [rest[i:i + CFG["CHUNK"]] for i in range(0, len(rest), CFG["CHUNK"])] or [[]]
    base = dict(base_filters(city, loves_all))
    if sig_loves:
        base.update(signal(sig_loves))
    if explain:
        base["feature.explainability"] = True
    aff, anchor_vals, ents_by_id = {}, {a: [] for a in anchors}, {}
    for n, ch in enumerate(chunks, 1):
        p = dict(base)
        p["filter.results.entities"] = sorted(set(anchors + ch))
        p["take"] = CFG["TAKE"]
        resp = q.insights(p, label="%s c%d" % (label, n))
        for e in (resp.get("results") or {}).get("entities") or []:
            a = affinity(e)
            ents_by_id[e["entity_id"]] = e
            if e["entity_id"] in anchor_vals:
                anchor_vals[e["entity_id"]].append(a)
            if a is not None:
                aff[e["entity_id"]] = a
    drift = max([max(v) - min(v) for v in anchor_vals.values() if len(v) > 1] or [0.0])
    missing = [i for i in ids if i not in aff]
    return {"aff": aff, "coverage": (len(ids) - len(missing)) / max(1, len(ids)), "missing": missing,
            "drift": drift, "calls": len(chunks), "distinct": len(set(round(v, 9) for v in aff.values())),
            "ents": ents_by_id}


def ranks_from(aff, ids):
    """Rank within `ids` by affinity; ids with no score tie at the bottom."""
    r = ST.rank({i: aff[i] for i in ids if i in aff})
    n_scored = len(r)
    miss = [i for i in ids if i not in r]
    if miss:
        bottom = n_scored + (len(miss) + 1) / 2.0
        for i in miss:
            r[i] = bottom
    return r


# ---------------------------------------------------------------- the fixed set U and its ranks
def pool_ranks(q, city, loves, U, baseline="auto"):
    ids = [e["entity_id"] for e in U]
    N = len(ids)
    taste_rank = {e["entity_id"]: i + 1 for i, e in enumerate(sorted(U, key=lambda e: e["_pos"]))}
    pop = {e["entity_id"]: e.get("popularity") or prop(e, "popularity") or 0.0 for e in U}
    pop_rank = ST.rank(pop)
    out = {"N": N, "taste_rank": taste_rank, "pop_rank": pop_rank, "pop": pop}
    if baseline in ("auto", "nosignal"):
        rs = rescore(q, city, loves, ids, None, "C5 baseline")
        out["baseline_rescore"] = {k: rs[k] for k in ("coverage", "drift", "calls", "distinct", "missing")}
        out["nosignal_rank"] = ranks_from(rs["aff"], ids)
        ok = rs["coverage"] >= 0.95 and rs["distinct"] >= 0.5 * N and rs["drift"] <= CFG["ANCHOR_DRIFT_MAX"]
        out["rho_nosignal_pop"] = ST.spearman(out["nosignal_rank"], pop_rank)
        if ok:
            out["base_rank"], out["baseline"] = out["nosignal_rank"], "no-signal rescoring (filter.results.entities)"
        else:
            out["base_rank"], out["baseline"] = pop_rank, "popularity field (no-signal rescoring failed K9 checks)"
    else:
        out["base_rank"], out["baseline"] = pop_rank, "popularity field"
    out["taste_pct"] = {i: ST.pct(taste_rank[i], N) for i in ids}
    out["base_pct"] = {i: ST.pct(out["base_rank"][i], N) for i in ids}
    out["lift"] = {i: out["taste_pct"][i] - out["base_pct"][i] for i in ids}
    out["rho_taste_base"] = ST.spearman(taste_rank, out["base_rank"])
    out["rho_taste_pop"] = ST.spearman(taste_rank, pop_rank)
    return out


# ---------------------------------------------------------------- explainability
def aggregate_shares(first_resp, loves):
    agg, warn = aggregate_explain(first_resp)
    by_id = {l["id"]: l for l in loves if l.get("id")}
    shares = {}
    for sub, d in agg.items():
        tot = sum(d.values()) or 1
        shares[sub] = {by_id[i]["text"] if i in by_id else i: v / tot for i, v in d.items()}
    top = shares.get("top_10") or shares.get("all") or {}
    flags = {}
    if top:
        lead, val = max(top.items(), key=lambda kv: kv[1])
        if val >= CFG["DOMINANT"]:
            flags["dominated_by"] = (lead, round(val, 2))
        allv = shares.get("all") or top
        dead = [l["text"] for l in loves if l.get("text") and allv.get(l["text"], 0) < CFG["DEAD"]]
        if dead:
            flags["dead"] = dead
    return {"shares": shares, "warning": warn, "flags": flags}


def because(e, loves, deltas=None):
    items, warn = explain_items(e)
    by_id = {l["id"]: l for l in loves if l.get("id")}
    if items and not warn:
        i, s = max(items.items(), key=lambda kv: kv[1])
        l = by_id.get(i)
        if l:
            line = ("mostly because of %s" if l.get("is_place") else "because you love %s") % l["text"]
            return {"love": l["text"], "share": round(s, 2), "source": "explainability", "line": line}
    if deltas:
        txt, d = max(deltas.items(), key=lambda kv: kv[1])
        l = next((x for x in loves if x.get("text") == txt), {})
        line = ("mostly because of %s" if l.get("is_place") else "because you love %s") % txt
        return {"love": txt, "share": None, "source": "drop-one (rank falls %+.0f without it)" % d, "line": line}
    return {"love": None, "share": None, "source": "none", "line": None}


# ---------------------------------------------------------------- strike
def city_search_fn(q, city):
    loc = "%s,%s" % (city["lat"], city["lon"]) if city.get("lat") is not None else city["id"]

    def fn(raw):
        res = q.search(raw, types=PLACE, take=5, location=loc, radius_mi=CFG["SEARCH_RADIUS_MI"], label="C7 name")
        return [{"entity_id": r["entity_id"], "name": r.get("name", "")} for r in res]
    return fn


def strike(q, city, U, wall_names, use_search=True):
    pool = [{"entity_id": e["entity_id"], "name": e.get("name", "")} for e in U]
    return M.match_wall(wall_names, pool, city_search_fn(q, city) if use_search else None)


# ---------------------------------------------------------------- C6 drop-one hold
def hold(q, city, loves, S_ids, taste_rank):
    n = len(loves)
    if n < 2 or not S_ids:
        return {i: None for i in S_ids}, {}, {}
    full_S = ST.rank({i: -taste_rank[i] for i in S_ids})
    cut = math.ceil(len(S_ids) * CFG["HOLD_FRAC"])
    holds = {i: 0 for i in S_ids}
    deltas = {i: {} for i in S_ids}
    diag = {}
    for k, drop in enumerate(loves):
        rest = [l for l in loves if l is not drop]
        rs = rescore(q, city, loves, S_ids, rest, "C6 drop %s" % drop["text"][:18])
        rk = ranks_from(rs["aff"], S_ids)
        diag[drop["text"]] = {"coverage": rs["coverage"], "drift": rs["drift"], "calls": rs["calls"]}
        for i in S_ids:
            if rk[i] <= cut:
                holds[i] += 1
            deltas[i][drop["text"]] = rk[i] - full_S[i]   # positive: falls without this love
    return holds, deltas, diag


# ---------------------------------------------------------------- the whole query
def run(q, city_q, loves_spec, wall, region=None, use_search=True, skeptic_fn=None, baseline="auto", pages=None):
    res = {"status": None, "cards": [], "diag": {}, "loves": [], "city": None}
    city = city_q if isinstance(city_q, dict) else resolve_city(q, city_q, region)
    res["city"] = city
    if city.get("status") != "ok":
        res["status"] = "needs_input"
        return res
    loves = [resolve_love(q, t, h) for t, h in loves_spec]
    res["loves"] = loves
    if any(l["status"] == "needs_input" for l in loves):
        res["status"] = "needs_input"
        return res
    pool, first, pdiag = taste_pool(q, city, loves, pages)
    U, drops = floor(pool)
    res["diag"].update({"P": len(pool), "U": len(U), "drops": drops, "pool": pdiag})
    if not U:
        res["status"] = "empty_none"
        return res
    R = pool_ranks(q, city, loves, U, baseline)
    res["diag"].update({k: R[k] for k in ("N", "baseline", "rho_taste_base", "rho_taste_pop")})
    res["diag"]["rho_nosignal_pop"] = R.get("rho_nosignal_pop")
    res["diag"]["baseline_rescore"] = R.get("baseline_rescore")
    res["diag"]["explain_agg"] = aggregate_shares(first, loves)
    warns = sum(1 for e in U if explain_items(e)[1] or not explain_items(e)[0])
    res["diag"]["explain_warn_rate"] = warns / len(U)
    names = []
    for a in wall["answers"]:
        names += [n["name"] if isinstance(n, dict) else n for n in a["names"]]
    struck, per = strike(q, city, U, names, use_search)
    res["diag"]["wall"] = {"answers": len(wall["answers"]), "names": len(set(M.norm(n) for n in names)),
                           "struck": len(struck), "status": _count(per), "source": wall.get("source")}
    in_u = {e["entity_id"] for e in U}
    lab = [i in struck for i in in_u]
    res["diag"]["auc_pop_struck"] = ST.auc([R["pop"][i] for i in in_u], lab)
    k = len(struck)
    top_pop = set(sorted(in_u, key=lambda i: R["pop_rank"][i])[:k])
    res["diag"]["popcap_overlap"] = (len(top_pop & set(struck)) / k) if k else float("nan")
    S = [e for e in U if e["entity_id"] not in struck]
    S_ids = [e["entity_id"] for e in S]
    holds, deltas, hdiag = hold(q, city, loves, S_ids, R["taste_rank"])
    res["diag"]["hold"] = hdiag
    need = max(1, len(loves) - 1) if len(loves) >= 2 else 0
    kept = [e for e in S if holds[e["entity_id"]] is None or holds[e["entity_id"]] >= need]
    flat = R["rho_taste_base"] > CFG["FLAT_RHO"]
    if flat:   # K2a fallback: lift is not trusted; order by taste rank within the bottom 80% of base rank
        cutoff = 0.8 * R["N"]
        kept_order = sorted([e for e in kept if R["base_rank"][e["entity_id"]] >= R["N"] - cutoff],
                            key=lambda e: R["taste_rank"][e["entity_id"]])
    else:
        kept_order = sorted(kept, key=lambda e: (-R["lift"][e["entity_id"]], R["taste_rank"][e["entity_id"]],
                                                 e["entity_id"]))
    res["diag"].update({"S": len(S), "kept": len(kept), "flat": flat})
    burned = []
    if skeptic_fn:
        top = kept_order[:CFG["SKEPTIC_TOP"]]
        for e in top:
            hood = prop(e, "neighborhood") or ""
            said = skeptic_fn(hood, city["name"])
            st, _ = M.match_wall(said, [{"entity_id": e["entity_id"], "name": e.get("name", "")}], None)
            if st:
                burned.append({"id": e["entity_id"], "name": e.get("name"), "neighbourhood": hood})
        kept_order = [e for e in kept_order if e["entity_id"] not in {b["id"] for b in burned}]
    res["diag"]["skeptic"] = {"run": bool(skeptic_fn), "burned": burned}
    n_loves = len(loves)
    for e in kept_order[:CFG["N_CARDS"]]:
        i = e["entity_id"]
        res["cards"].append({
            "qloo_id": i, "name": e.get("name"), "neighbourhood": prop(e, "neighborhood"),
            "rating": prop(e, "business_rating"), "is_closed": prop(e, "is_closed"),
            "fits": "#%d of %d" % (R["taste_rank"][i], R["N"]),
            "city_order": "#%d of %d" % (round(R["base_rank"][i]), R["N"]),
            "lift_pts": round(100 * R["lift"][i]),
            "holds": ("%d of %d" % (holds[i], n_loves)) if holds[i] is not None else "n/a (1 love)",
            "because": because(e, loves, deltas.get(i)),
            "ai": {"named": 0, "asked": len(wall["answers"]) + (3 if skeptic_fn else 0)},
            "tags": [t.get("name") for t in (e.get("tags") or [])][:3],
        })
    n = len(res["cards"])
    if n >= CFG["N_CARDS"]:
        res["status"] = "ok"
    elif n > 0:
        res["status"] = "empty_few"
    else:
        res["status"] = "empty_none"
        res["fallback"] = [e.get("name") for e in sorted([e for e in U if e["entity_id"] in struck],
                                                          key=lambda e: R["taste_rank"][e["entity_id"]])[:3]]
    res["flags"] = [f for f, on in (("flat", flat), ("thin_pool", len(U) < CFG["THIN_POOL"]),
                                    ("dominated", "dominated_by" in res["diag"]["explain_agg"]["flags"])) if on]
    res["_R"] = R
    res["_U"] = U
    res["_struck"] = struck
    res["_per"] = per
    res["_holds"] = holds
    res["_deltas"] = deltas
    return res


def _count(per):
    c = {}
    for v in per.values():
        c[v["status"]] = c.get(v["status"], 0) + 1
    return c
