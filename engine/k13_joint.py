"""K13 · Qloo's joint signal vs UNSAID's per-love fusion, over the SAME fixed pool U.

The question (a judge's): why fuse per-love ranks (RRF over one C6' rescoring per love) instead of asking Qloo once
with every love in signal.interests.entities and reading feature.explainability for the "because"?

For each frozen set (data/sets.json), offline-first through the engine's own client (frozen cache, budget, 8/s):

  engine   engine.run with the real dated wall: per-love orders -> RRF for-you -> strike -> lift -> holds -> 7 cards
  J        ONE joint signal (all the set's ENTITY loves, dead ones included, as a naive caller would send them) with
           feature.explainability=true, rescoring U in the engine's own 48 + 2-anchor chunks (filter.results.entities)
  J7       engine.run again with the for-you score replaced by J's affinity: same strike, same lift formula, same
           per-love holds and because (option b). B7: J added as one more RRF voter beside the live loves (option c).
  J_live   (sets with a dead entity love) J without the dead love: what the dead love does to the joint order
  J_mix    (sets with a dish/tag love) entities + the tag in one call, which the client's never-send rule forbids in
           the engine; sent here as a probe (unsafe_probe) to see what the joint signal does with a dish
  J-holds  for J7's cards: still in the top third of S when the joint signal drops any one of its loves (leave-one-out
           joint calls; a two-entity set's leave-one-out IS the single-love C6' call, a cache hit)

"named" is k12's check verbatim (matcher R1-R5 on the 7 names + the reverse check on raw answer text, with the
strike's /search vetoes), over the set's dated wall answers + the held-out fresh asks; "fresh" = held-out only.

Payload: the engine sends feature.explainability=true on each entity love's C4 page 1 (offset 0) for the raw log only.
A single-love call's explainability can only say "this love, 1.0". The payload probe fetches the same page-1 request
with and without it (no cache, alternating order) and reports body bytes, gzip wire bytes and ms.

Counts only in the md files (set ids, no place names: Qloo output stays out of git); names go to
out/k13_joint.json (gitignored).

  set -a; . ~/.config/unsaid/env; set +a
  python3 -I k13_joint.py --public-md k13_joint.md          # 20 sets; ~250 live calls cold, 0 warm (+40 payload)
  # from a worktree: --cache-dir <main>/engine/.cache and UNSAID_PRIORS_DIR=<main>/data/priors (both gitignored)
"""
import copy, json, math, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from unsaid import cli, engine as E, matcher as M, seeds as SD, walls as W, stats as ST  # noqa: E402
from unsaid.qloo import (Qloo, QlooError, TIMEOUT_POOL, affinity, explain_items, is_default_affinity)  # noqa: E402

ROOT = os.path.dirname(cli.KIT)
ap = cli.parser(__doc__)
ap.set_defaults(walls=os.path.join(ROOT, "data", "walls"), budget=520, frozen=True)
ap.add_argument("--fresh-answers", default=os.path.join(ROOT, "harness", "runs", "fresh.jsonl"))
ap.add_argument("--cache-dir", help="the Qloo cache to read (a worktree points at the main checkout's engine/.cache)")
ap.add_argument("--only", help="comma-separated set ids")
ap.add_argument("--no-mix", action="store_true", help="skip the entity+tag probe")
ap.add_argument("--no-loo", action="store_true", help="skip the joint leave-one-out holds")
ap.add_argument("--payload-pools", type=int, default=10)
ap.add_argument("--payload-reps", type=int, default=2)
ap.add_argument("--payload-budget", type=int, default=60)
ap.add_argument("--payload-fresh", action="store_true", help="re-measure even when out/k13_joint.payload.json exists")
ap.add_argument("--md", default=os.path.join(cli.OUT, "k13_joint.md"))
ap.add_argument("--public-md", help="also write the same counts-only md here (the committed copy)")
args = ap.parse_args()
T = cli.tag(args)
N7 = E.CFG["N_CARDS"]
E.CFG["CAP_ENABLED"] = False
kw = {"cache_dir": args.cache_dir} if args.cache_dir else {}
q = cli.client(args, "k13_joint", **kw)


# ---------------------------------------------------------------- k12's named check (verbatim)
def load_fresh():
    if not os.path.exists(args.fresh_answers):
        return []
    out = []
    with open(args.fresh_answers) as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("status") == "failed" or r.get("fake"):
                continue
            out.append(dict(r, names=r.get("names") or r.get("places") or []))
    return out


def named_in(names, answers, veto=()):
    if not names or not answers:
        return set()
    pool = [{"entity_id": n, "name": n} for n in names]
    raws = [n["name"] if isinstance(n, dict) else n for a in answers for n in a.get("names") or []]
    st, _ = M.match_wall([r for r in raws if r not in veto], pool, None)
    hit = set(st)
    rix = E.reverse_index(answers)
    return hit | {n for n in names if E.reverse_hit(n, rix) is not None}


# ---------------------------------------------------------------- joint rescoring (the engine's C6' layout)
def rescore_joint(city, loves_all, ids, ent_ids, tag_ids=(), explain=True, label="K13 J"):
    """The engine's rescore() with a joint signal and (optionally) feature.explainability. Same sorted ids, same 2
    anchors, same 48-id chunks, same base filters, so a one-love call here is byte-identical to the engine's C6'."""
    ids = sorted(ids)
    anchors = ids[:E.CFG["ANCHORS"]]
    rest = [i for i in ids if i not in anchors]
    chunks = [rest[i:i + E.CFG["CHUNK"]] for i in range(0, len(rest), E.CFG["CHUNK"])] or [[]]
    base = dict(E.base_filters(city, loves_all), take=E.CFG["TAKE"])
    if ent_ids:
        base["signal.interests.entities"] = sorted(ent_ids)
    if tag_ids:
        base["signal.interests.tags"] = sorted(tag_ids)
    if explain:
        base["feature.explainability"] = True
    unsafe = bool(tag_ids and ent_ids)      # entity + tag in one call: the engine never sends it; probed here

    def run(job):
        n, ch = job
        p = dict(base)
        p["filter.results.entities"] = sorted(set(anchors + ch))
        try:
            return q.insights(p, label="%s c%d" % (label, n), timeout=TIMEOUT_POOL, unsafe_probe=unsafe), None
        except QlooError as e:
            return None, e

    out = E._pmap(run, list(enumerate(chunks, 1)), E.CFG["WORKERS"])
    aff, ex, warn, anchor_vals, failed, top = {}, {}, 0, {a: [] for a in anchors}, 0, []
    for resp, err in out:
        if err is not None:
            failed += 1
            continue
        tq = (resp.get("query") or {}).get("explainability")
        if tq:
            top.append(tq)
        for e in (resp.get("results") or {}).get("entities") or []:
            a = affinity(e)
            i = e["entity_id"]
            if i in anchor_vals:
                anchor_vals[i].append(a)
            if a is not None:
                aff[i] = float(a)
            items, w = explain_items(e)
            warn += bool(w)
            if items and i not in ex:
                ex[i] = items
    drift = max([max(v) - min(v) for v in anchor_vals.values() if len(v) > 1 and None not in v] or [0.0])
    tied = {i for i in ids if i in aff and is_default_affinity(aff[i])}
    return {"aff": aff, "ex": ex, "warn": warn, "calls": len(chunks), "failed": failed, "drift": drift,
            "coverage": sum(1 for i in ids if i in aff) / float(max(1, len(ids))), "tied": tied,
            "tie_share": len(tied) / float(max(1, len(ids))), "top": top}


# ---------------------------------------------------------------- engine.run with the for-you score swapped
_RRF = E.rrf
_SWAP = {"armed": False}


def _rrf(orders, ids, k=None):
    s = _SWAP
    if s["armed"] and len(ids) == s["N"] and len(orders) == s["n_live"]:
        s["armed"] = False                     # the for-you call only; holds' leave-one-out calls pass through
        if s["mode"] == "joint":
            return {i: s["aff"].get(i, -1.0) for i in ids}
        return _RRF(list(orders) + [s["order"]], ids, k)       # blend: J is one more voter
    return _RRF(orders, ids, k)


E.rrf = _rrf


def run_swapped(c, ls, wall, mode, jaff, jorder, N, n_live):
    _SWAP.update({"armed": True, "mode": mode, "aff": jaff, "order": jorder, "N": N, "n_live": n_live})
    try:
        r = E.run(q, c, copy.deepcopy(ls), wall)
    finally:
        fired = not _SWAP["armed"]
        _SWAP["armed"] = False
    return r, fired


# ---------------------------------------------------------------- helpers
def med(xs):
    xs = [x for x in xs if x is not None and x == x]
    return cli.median(xs) if xs else float("nan")


def top7(rank, ids):
    return sorted(ids, key=lambda i: (rank[i], i))[:N7]


def argmax_love(exd, love_ids):
    """-> (love id, top share, margin to the 2nd) from one result's explainability, over the given loves."""
    xs = sorted(((exd.get(l, 0.0), l) for l in love_ids), reverse=True)
    if not xs or xs[0][0] <= 0:
        return None, None, None
    return xs[0][1], xs[0][0], xs[0][0] - (xs[1][0] if len(xs) > 1 else 0.0)


def holds_count(cards, S, loo_affs):
    """How many cards stay in the top third of S under every leave-one-out order."""
    if not loo_affs:
        return None
    cut = math.ceil(len(S) * E.CFG["HOLD_FRAC"])
    ok = 0
    for i in cards:
        good = True
        for aff in loo_affs:
            rk = E.ordinal({x: aff.get(x, -1.0) for x in S}, S)
            if rk.get(i, cut + 1) > cut:
                good = False
                break
        ok += good
    return ok


# ---------------------------------------------------------------- per set
fresh = load_fresh()
only = set((args.only or "").split(",")) - {""}
rows, names = [], {}
for city in cli.cities(args):
    c = cli.city_obj(q, city)
    for sid, spec in cli.sets(args, city):
        if only and sid not in only:
            continue
        ls = cli.loves(q, spec)
        if ls is None:
            print("    %-18s a love is not in Qloo; skipped" % sid)
            continue
        wall = W.wall_for(city, sid, args.walls, loves=[t for t, _ in spec])
        base = E.run(q, c, copy.deepcopy(ls), wall)
        if "_R" not in base:
            print("    %-18s engine status %s; skipped" % (sid, base.get("status")))
            continue
        U, R = base["_U"], base["_R"]
        ids = sorted(e["entity_id"] for e in U)
        N = len(ids)
        name_of = {e["entity_id"]: e.get("name") or "" for e in U}
        byid = {e["entity_id"]: e for e in U}
        L = base["loves"]                                   # resolved, with the engine's dead flags
        live = [l for l in L if l["text"] in base["diag"]["loves_live"]]
        n_live = len(live)
        ent = [l for l in L if l.get("kind") == "entity"]
        tags = [l for l in L if l.get("kind") == "tag"]
        dead_ent = [l for l in ent if l.get("dead")]
        id_of = {l["text"]: l["id"] for l in L}
        fit, pop = R["fit"], R["pop"]
        pop_rank = ST.rank(pop)
        struck_pre = {i for i, v in base["_struck"].items() if i in byid and any(r != "REV" for _, r in v)}
        S = [i for i in ids if i not in struck_pre]
        eng7 = [p["id"] for p in base["picks"]][:N7]

        # ---- J: one joint call over U (all entity loves) with explainability
        J = rescore_joint(c, L, ids, [l["id"] for l in ent], explain=True, label="K13 J %s" % sid)
        jrank = E.ranks_from(J["aff"], ids)
        jord = E.ordinal({i: J["aff"].get(i, -1.0) for i in ids}, ids)

        # ---- J7 (option b) and B7 (option c): the engine with the for-you score swapped
        jrun, fired_j = run_swapped(c, ls, wall, "joint", J["aff"], jrank, N, n_live)
        brun, fired_b = run_swapped(c, ls, wall, "blend", J["aff"], jrank, N, n_live)
        j7 = [p["id"] for p in jrun["picks"]][:N7]
        b7 = [p["id"] for p in brun["picks"]][:N7]

        # ---- because: the engine's per-love pick vs the joint call's explainability argmax
        ent_ids = [l["id"] for l in ent]
        bec = {"agree": 0, "disagree": 0, "eng_dish": 0, "no_explain": 0}
        shares, margins = [], []
        for p in base["picks"][:N7]:
            b = id_of.get(p["because"]) if p.get("because") else None
            jl, sh, mg = argmax_love(J["ex"].get(p["id"]) or {}, ent_ids)
            if sh is not None:
                shares.append(sh)
                margins.append(mg)
            if b is not None and b not in ent_ids:
                bec["eng_dish"] += 1
            elif jl is None:
                bec["no_explain"] += 1
            elif jl == b:
                bec["agree"] += 1
            else:
                bec["disagree"] += 1
        bec_j = {"agree": 0, "n": 0}                         # the same check on J7's own cards
        for p in jrun["picks"][:N7]:
            b = id_of.get(p["because"]) if p.get("because") else None
            jl, _, _ = argmax_love(J["ex"].get(p["id"]) or {}, ent_ids)
            if b in ent_ids and jl is not None:
                bec_j["n"] += 1
                bec_j["agree"] += jl == b
        # whole-U: which love does the joint explainability credit, vs the love whose per-love order ranks it best
        credit = {}
        for i in ids:
            jl, _, _ = argmax_love(J["ex"].get(i) or {}, ent_ids)
            if jl:
                credit[jl] = credit.get(jl, 0) + 1
        top_credit = max(credit.values()) / float(sum(credit.values())) if credit else None

        # ---- named (k12)
        fr = [a for a in fresh if W._ckey(a.get("city")) == city and
              (a.get("set") in (None, "", "-") or SD.same(a.get("set"), sid))]
        every = list(wall["answers"]) + fr
        veto = {raw for raw, info in base["_per"].items() if info.get("status") == "outside_pool"}

        def named(xs):
            ns = [name_of.get(i) or i for i in xs]
            return named_in(ns, every, veto), named_in(ns, fr, veto)

        # ---- holds: per-love (the engine's n of n) and joint leave-one-out
        def nn(run_):
            return sum(1 for p in run_["picks"][:N7] if p.get("holds") is not None and p["holds"] >= p["n_loves"])
        loo = []
        if not args.no_loo and len(ent) >= 2:
            for l in ent:
                others = [x["id"] for x in ent if x is not l]
                loo.append(rescore_joint(c, L, ids, others, explain=False, label="K13 J-%s %s" % (
                    l["text"][:10], sid))["aff"])

        # ---- per-love dominance inside J
        rho_love = {l["text"]: ST.spearman(jrank, R["orders"][l["text"]]) for l in live if l["text"] in R["orders"]}

        r = {"city": city, "set": sid, "U": N, "S": len(S), "n_ent": len(ent), "n_tag": len(tags),
             "n_live": n_live, "dead": [l["text"] for l in L if l.get("dead")], "flat": "flat" in base["flags"],
             "rho_fj": ST.spearman(fit, jrank), "rho_jpop": ST.spearman(jrank, pop_rank),
             "rho_fpop": ST.spearman(fit, pop_rank), "rho_love": rho_love,
             "j_cov": J["coverage"], "j_tie": J["tie_share"], "j_drift": J["drift"], "j_calls": J["calls"],
             "j_warn": J["warn"], "j_failed": J["failed"], "j_explained": len(J["ex"]),
             "plain_ov": len(set(top7(fit, ids)) & set(top7(jrank, ids))),
             "seven_ov": len(set(eng7) & set(j7)), "blend_ov": len(set(eng7) & set(b7)),
             "n_eng": len(eng7), "n_j": len(j7), "n_b": len(b7), "fired": fired_j and fired_b,
             "because": bec, "because_j": bec_j, "share_med": med(shares), "margin_med": med(margins),
             "top_credit": top_credit, "follows_first": bool(rho_love) and max(rho_love, key=rho_love.get) == live[0]["text"],
             "holds_eng": nn(base), "holds_j_perlove": nn(jrun), "holds_b_perlove": nn(brun),
             "holds_j_loo": holds_count(j7, S, loo), "holds_eng_loo": holds_count(eng7, S, loo)}
        for k, xs in (("eng", eng7), ("j", j7), ("b", b7), ("jplain", top7(jrank, ids)), ("plain", top7(fit, ids))):
            a, f = named(xs)
            r[k + "_named"], r[k + "_fresh"] = len(a), len(f)
            names.setdefault(sid, {})[k] = {"cards": [name_of.get(i) for i in xs], "named": sorted(a)}

        # ---- dead entity love: J without it
        if dead_ent and len(dead_ent) < len(ent):
            keep = [l["id"] for l in ent if not l.get("dead")]
            # one live entity left: J_live is that love's single-love order, byte-identical to the engine's C6' (cache)
            Jl = rescore_joint(c, L, ids, keep, explain=False, label="K13 Jlive %s" % sid)
            jl_rank = E.ranks_from(Jl["aff"], ids)
            dshare = [(J["ex"].get(i) or {}).get(dead_ent[0]["id"], 0.0) for i in ids if J["ex"].get(i)]
            dcred = credit.get(dead_ent[0]["id"], 0)
            r["deadlove"] = {"love_kind": dead_ent[0].get("type"), "why": dead_ent[0].get("dead_reason"),
                             "rho_J_Jlive": ST.spearman(jrank, jl_rank), "rho_Jlive_pop": ST.spearman(jl_rank, pop_rank),
                             "rho_J_pop": r["rho_jpop"], "plain_ov": len(set(top7(jrank, ids)) & set(top7(jl_rank, ids))),
                             "dead_share_med": med(dshare), "dead_credited": dcred, "explained": len(J["ex"])}

        # ---- dish / tag love: entity + tag in one call (probe)
        if tags and not args.no_mix:
            t = tags[0]
            Jm = rescore_joint(c, L, ids, [l["id"] for l in ent], [t["id"]], explain=True, label="K13 Jmix %s" % sid)
            jm_rank = E.ranks_from(Jm["aff"], ids)
            tag_in_ex = sum(1 for i in ids if t["id"] in (Jm["ex"].get(i) or {}))
            tag_share = [(Jm["ex"].get(i) or {}).get(t["id"], 0.0) for i in ids if Jm["ex"].get(i)]
            tagged = {i for i in ids if t["text"] in (byid[i].get("_loves") or []) or
                      any((x.get("id") or "") == t["id"] for x in byid[i].get("tags") or [] if isinstance(x, dict))}
            scored = [i for i in ids if i in Jm["aff"]]
            r["dish"] = {"dead": bool(t.get("dead")), "why": t.get("dead_reason"), "cov": Jm["coverage"],
                         "tie": Jm["tie_share"], "returned": len(scored), "warn": Jm["warn"],
                         "rho_mix_J": ST.spearman({i: jm_rank[i] for i in scored}, jrank) if len(scored) >= 3 else None,
                         "tag_in_explain": tag_in_ex, "tag_share_med": med(tag_share), "tagged": len(tagged),
                         "tagged_in_fused7": len(tagged & set(top7(fit, ids))),
                         "tagged_in_J7": len(tagged & set(top7(jrank, ids))),
                         "tagged_in_mix7": len(tagged & set(top7(jm_rank, ids))) if scored else 0,
                         "tagged_in_eng7": len(tagged & set(eng7)), "tagged_in_j7": len(tagged & set(j7)),
                         "keys": sorted({k for tq in Jm["top"] for k in tq if k != "warning"}),
                         "top_warn": sum(1 for tq in Jm["top"] if tq.get("warning"))}
        rows.append(r)
        print("    %-18s U %3d  rho(fused,J) %.2f  rho(J,pop) %.2f vs fused %.2f  plain7 %d/7  seven %d/7  blend %d/7"
              "  because %d agree %d differ %d dish  named eng %d J %d B %d (fresh %d %d %d)  holds n/n eng %d J %d%s"
              % (sid, N, r["rho_fj"], r["rho_jpop"], r["rho_fpop"], r["plain_ov"], r["seven_ov"], r["blend_ov"],
                 bec["agree"], bec["disagree"], bec["eng_dish"], r["eng_named"], r["j_named"], r["b_named"],
                 r["eng_fresh"], r["j_fresh"], r["b_fresh"], r["holds_eng"], r["holds_j_perlove"], T), flush=True)


# ---------------------------------------------------------------- payload: explainability on single-love C4 page 1
def payload_probe():
    if args.payload_pools <= 0:
        return None
    saved = os.path.join(cli.OUT, "k13_joint.payload%s.json" % (".fake" if args.fake else ""))
    if os.path.exists(saved) and not args.payload_fresh:
        with open(saved) as f:
            out = json.load(f)
        out["reused"] = True
        return out
    q2 = Qloo(fake=args.fake, use_cache=False, budget=args.payload_budget,
              trace_path=os.path.join(cli.OUT, "k13_joint.payload.trace.jsonl"))
    jobs = []
    for city in cli.cities(args):
        c = cli.city_obj(q, city)
        for sid, spec in cli.sets(args, city):
            ls = cli.loves(q, spec)
            if not ls:
                continue
            l = next((x for x in ls if x.get("kind") == "entity"), None)
            if l:
                jobs.append((c, ls, l))
    jobs = jobs[::max(1, len(jobs) // max(1, args.payload_pools))][:args.payload_pools]
    rec = {"with": [], "without": []}
    same_order, info_free, n_res = 0, 0, 0
    for k, (c, ls, l) in enumerate(jobs):
        p = dict(E.base_filters(c, ls), take=E.CFG["TAKE"], **E.signal_of(l))
        ids_seen = {}
        for rep in range(args.payload_reps):
            for v in (("with", "without") if (k + rep) % 2 == 0 else ("without", "with")):
                pp = dict(p, **({"feature.explainability": True} if v == "with" else {}))
                s0 = dict(q2.transport.stats) if hasattr(q2.transport, "stats") else {}
                t0 = time.monotonic()
                try:
                    d = q2.insights(pp, label="K13 payload %s" % v)
                except QlooError:
                    continue
                ms = (time.monotonic() - t0) * 1000
                s1 = getattr(q2.transport, "stats", {})
                ents = (d.get("results") or {}).get("entities") or []
                rec[v].append({"pool": k, "ms": ms, "body": s1.get("body_bytes", 0) - s0.get("body_bytes", 0),
                               "wire": s1.get("wire_bytes", 0) - s0.get("wire_bytes", 0),
                               "json": len(json.dumps(d))})
                ids_seen.setdefault(v, [e["entity_id"] for e in ents])
                if v == "with" and rep == 0:
                    for e in ents:
                        n_res += 1
                        items, w = explain_items(e)
                        info_free += (not w) and set(items) == {l["id"]} and abs(items[l["id"]] - 1.0) < 1e-9
        same_order += ids_seen.get("with") == ids_seen.get("without")
    out = {"pools": len(jobs), "reps": args.payload_reps, "same_order": same_order, "info_free": info_free,
           "results": n_res, "network": q2.calls["network"]}
    for v in rec:
        out[v] = {k: med([x[k] for x in rec[v]]) for k in ("ms", "body", "wire", "json")}
        out[v]["n"] = len(rec[v])
    pair = []          # per pool: median ms with - median ms without (same request, back to back)
    for k in range(len(jobs)):
        a = [x["ms"] for x in rec["with"] if x["pool"] == k]
        b = [x["ms"] for x in rec["without"] if x["pool"] == k]
        if a and b:
            pair.append(med(a) - med(b))
    out["pair_ms"] = {"median": med(pair), "min": min(pair or [0]), "max": max(pair or [0]), "n": len(pair)}
    out["raw"] = rec
    with open(saved, "w") as f:
        json.dump(out, f, indent=1)
    return out


pay = payload_probe()
if pay:
    print("  payload: %s" % json.dumps({k: v for k, v in pay.items() if k != "raw"}))


# ---------------------------------------------------------------- write
def fmt(x, nd=2):
    return cli.f(x, nd)


def cold_calls():
    """Live calls the experiment made: this run's, or the cold run's when this one read the cache."""
    fp = os.path.join(cli.OUT, "k13_joint.calls%s.json" % (".fake" if args.fake else ""))
    if q.calls["network"]:
        with open(fp, "w") as f:
            json.dump({"network": q.calls["network"]}, f)
        return q.calls["network"]
    try:
        with open(fp) as f:
            return json.load(f)["network"]
    except (OSError, ValueError, KeyError):
        return 0


def write(f):
    n = len(rows)
    f.write("# K13 · Qloo's joint signal vs per-love fusion%s\n\n" % T)
    f.write("Engine `%s`, %d sets, over the SAME fixed pool U the engine builds (floor applied). *J* = ONE "
            "`signal.interests.entities` call with all the set's entity loves (dead ones included) and "
            "`feature.explainability=true`, rescoring U in the engine's 48 + 2-anchor `filter.results.entities` "
            "chunks. *fused* = the engine's RRF (k = 60) over the live loves' per-love orders. *J7* = the engine with "
            "its for-you score replaced by J's affinity (same strike, same lift formula, same per-love holds and "
            "because: option b). *B7* = J added as one more RRF voter beside the live loves (option c). *named* = "
            "k12's check (dated wall + held-out fresh asks; *fresh* = held-out only). Counts only; names stay in "
            "`engine/out/k13_joint.json` (gitignored). Everyone-prior for the lift: built %s. Live Qloo calls for the "
            "experiment: %d (this run: %d network, %d cache)%s.\n\n" % (
                E.ENGINE_V, n, ", ".join(sorted({str((E.load_prior(c_) or {}).get("built_at")) for c_ in cli.cities(args)})),
                cold_calls(), q.calls["network"], q.calls["cache"],
                (" + %d payload probe%s" % (pay["network"], " (measured on an earlier run, reused)" if pay.get("reused")
                                             else "")) if pay else ""))
    keys = ("rho_fj", "rho_jpop", "rho_fpop", "plain_ov", "seven_ov", "blend_ov", "eng_named", "j_named", "b_named",
            "jplain_named", "plain_named", "eng_fresh", "j_fresh", "b_fresh", "jplain_fresh", "plain_fresh",
            "holds_eng", "holds_j_perlove", "holds_b_perlove", "holds_j_loo", "holds_eng_loo", "j_tie",
            "share_med", "margin_med", "top_credit")
    M_ = {k: med([r.get(k) for r in rows]) for k in keys}
    P_ = {k: sum(r.get(k) or 0 for r in rows) for k in keys}
    bec = {k: sum(r["because"][k] for r in rows) for k in ("agree", "disagree", "eng_dish", "no_explain")}
    bj = {k: sum(r["because_j"][k] for r in rows) for k in ("agree", "n")}
    f.write("## Summary (medians over %d sets; pooled counts of 140 cards where it says so)\n\n" % n)
    f.write("- **Order over U:** Spearman ρ(fused, J) median **%s** (range %s to %s). ρ with popularity: J **%s**, "
            "fused **%s** (lower = further from \"what everyone likes\").\n" % (
                fmt(M_["rho_fj"]), fmt(min(r["rho_fj"] for r in rows)), fmt(max(r["rho_fj"] for r in rows)),
                fmt(M_["rho_jpop"]), fmt(M_["rho_fpop"])))
    f.write("- **Top 7 by taste alone** (no strike, no lift): fused and J share a median **%s of 7**.\n" %
            fmt(M_["plain_ov"], 1))
    f.write("- **The seven cards** (same strike, same lift, same holds): J7 shares a median **%s of 7** with the "
            "engine's seven; B7 shares **%s of 7**.\n" % (fmt(M_["seven_ov"], 1), fmt(M_["blend_ov"], 1)))
    f.write("- **AI-named cards (k12 check)**, median per set · pooled: engine **%s · %d**, J7 **%s · %d**, B7 "
            "**%s · %d**; held-out fresh only: %s · %d, %s · %d, %s · %d. Qloo's plain top 7: fused %s · %d, J %s · %d.\n"
            % (fmt(M_["eng_named"], 1), P_["eng_named"], fmt(M_["j_named"], 1), P_["j_named"], fmt(M_["b_named"], 1),
               P_["b_named"], fmt(M_["eng_fresh"], 1), P_["eng_fresh"], fmt(M_["j_fresh"], 1), P_["j_fresh"],
               fmt(M_["b_fresh"], 1), P_["b_fresh"], fmt(M_["plain_named"], 1), P_["plain_named"],
               fmt(M_["jplain_named"], 1), P_["jplain_named"]))
    f.write("- **Because:** on the engine's %d cards, J's explainability names the same love as the engine's "
            "\"because\" on **%d**, another love on **%d**; on **%d** the engine's because is a dish, which an "
            "entity-only joint call cannot name; %d had no explainability. On J7's own cards: %d of %d agree. "
            "Explainability is flat: the top love's share is a median **%s**, its margin over the second **%s**; "
            "across all of U one love takes a median **%s** of the argmax credit.\n" % (
                sum(r["n_eng"] for r in rows), bec["agree"], bec["disagree"], bec["eng_dish"], bec["no_explain"],
                bj["agree"], bj["n"], fmt(M_["share_med"]), fmt(M_["margin_med"]), fmt(M_["top_credit"])))
    f.write("- **Holds if you drop any one love** (n of n), pooled: engine seven **%d** of %d (per-love RRF); J7 "
            "**%d** of %d under the same per-love check, **%s** under the joint leave-one-out (J without each entity "
            "love); the engine's seven under the joint leave-one-out **%s**. B7 per-love: %d.\n" % (
                P_["holds_eng"], sum(r["n_eng"] for r in rows), P_["holds_j_perlove"], sum(r["n_j"] for r in rows),
                P_["holds_j_loo"] if not args.no_loo else "n/a", P_["holds_eng_loo"] if not args.no_loo else "n/a",
                P_["holds_b_perlove"]))
    f.write("- **J itself:** coverage of U median %s, tie share at Qloo's default affinity %s, anchor drift max %s, "
            "explainability warnings %d, failed chunks %d.\n\n" % (
                fmt(med([r["j_cov"] for r in rows])), fmt(M_["j_tie"]), fmt(max(r["j_drift"] for r in rows), 4),
                sum(r["j_warn"] for r in rows), sum(r["j_failed"] for r in rows)))
    f.write("| set | U | live/loves | ρ fused·J | ρ J·pop | ρ fused·pop | plain 7 shared | seven shared J7 · B7 | "
            "because agree · differ · dish | named eng · J7 · B7 | fresh eng · J7 · B7 | holds n/n eng · J7 · J7 joint-LOO |\n"
            "|---|---:|---|---:|---:|---:|---:|---|---|---|---|---|\n")
    for r in rows:
        b = r["because"]
        f.write("| %s | %d | %d/%d | %s | %s | %s | %d | %d · %d | %d · %d · %d | %d · %d · %d | %d · %d · %d | %d · %d · %s |\n" % (
            r["set"], r["U"], r["n_live"], r["n_ent"] + r["n_tag"], fmt(r["rho_fj"]), fmt(r["rho_jpop"]),
            fmt(r["rho_fpop"]), r["plain_ov"], r["seven_ov"], r["blend_ov"], b["agree"], b["disagree"], b["eng_dish"],
            r["eng_named"], r["j_named"], r["b_named"], r["eng_fresh"], r["j_fresh"], r["b_fresh"], r["holds_eng"],
            r["holds_j_perlove"], "n/a" if r["holds_j_loo"] is None else r["holds_j_loo"]))
    lv = lambda r, k: list(r["rho_love"].values())[k] if len(r["rho_love"]) > k else None  # noqa: E731
    f.write("\nWhich love J follows: ρ(J, a love's own per-love order), median over sets: the artist **%s**, the "
            "film/show **%s**, the third love **%s** when it is a dish (%d sets) and **%s** when it is a place or brand "
            "(%d sets).\n\n" % (
                fmt(med([lv(r, 0) for r in rows])), fmt(med([lv(r, 1) for r in rows])),
                fmt(med([lv(r, 2) for r in rows if r["n_tag"]])), sum(1 for r in rows if r["n_tag"]),
                fmt(med([lv(r, 2) for r in rows if not r["n_tag"]])), sum(1 for r in rows if not r["n_tag"])))
    dl = [r for r in rows if r.get("deadlove")]
    f.write("## A dead love inside the joint signal (%d sets)\n\n" % len(dl))
    f.write("The engine drops a love whose own order is popularity (ρ ≥ 0.95) or a tie. J has no such step: it takes "
            "every entity it is given and returns no flag. *J_live* = J without the dead love.\n\n")
    if not dl:
        deads = [(r["set"], x) for r in rows for x in r["dead"]]
        f.write("No ENTITY love is dead in these %d sets (the brand loves stay live: their own orders are not "
                "popularity). Dead loves here: %s, dishes only; what J does with a dish is the next section.\n\n"
                % (n, ", ".join("%s's dish (%s)" % (sid, next((r["dish"]["why"] for r in rows if r["set"] == sid
                                                             and r.get("dish")), "?")) for sid, _ in deads) or "none"))
    if dl:
        f.write("| set | why dead | ρ J·J_live | ρ J·pop | ρ J_live·pop | plain 7 shared J·J_live | dead love's median "
                "explain share | U places credited to it |\n|---|---|---:|---:|---:|---:|---:|---:|\n")
        for r in dl:
            d = r["deadlove"]
            f.write("| %s | %s | %s | %s | %s | %d | %s | %d of %d |\n" % (
                r["set"], d["why"], fmt(d["rho_J_Jlive"]), fmt(d["rho_J_pop"]), fmt(d["rho_Jlive_pop"]), d["plain_ov"],
                fmt(d["dead_share_med"]), d["dead_credited"], d["explained"]))
        f.write("\n")
    ds = [r for r in rows if r.get("dish")]
    f.write("## A dish (tag) love inside the joint signal (%d sets)\n\n" % len(ds))
    f.write("The engine never puts an entity and a tag in one call (the client's never-send rule). Here J_mix sends "
            "them together over the same U chunks with explainability, as a probe. *tagged* = U members carrying the "
            "dish tag or returned by its dish sub-pool.\n\n")
    if ds:
        DS = lambda k: sum(r["dish"][k] for r in ds)  # noqa: E731
        f.write("Pooled over %d sets: dish-tagged places in the seven, engine **%d** vs J7 **%d**; in the plain taste "
                "top 7, fused %d · J %d · J_mix %d. The tag shows up in J_mix's explainability for **%d** places "
                "(top-level keys: entities only). J_mix's order equals J's (ρ ≥ 0.99) in **%d** of %d sets: the tag is "
                "ignored; in the other %d, Qloo leaves a median **%s%%** of U out of the response (up to %s%%), so the "
                "order is J's minus places, not J plus the dish.\n\n" % (
                    len(ds), DS("tagged_in_eng7"), DS("tagged_in_j7"), DS("tagged_in_fused7"), DS("tagged_in_J7"),
                    DS("tagged_in_mix7"), DS("tag_in_explain"),
                    sum(1 for r in ds if (r["dish"]["rho_mix_J"] or 0) >= 0.99), len(ds),
                    sum(1 for r in ds if (r["dish"]["rho_mix_J"] or 0) < 0.99),
                    fmt(100 * med([1 - r["dish"]["cov"] for r in ds if (r["dish"]["rho_mix_J"] or 0) < 0.99]), 0),
                    fmt(100 * max(1 - r["dish"]["cov"] for r in ds), 0)))
        f.write("| set | dish dead in engine | J_mix scored of U | tie share | ρ J_mix·J | tag in explain (places) | "
                "tag explain share | tagged in U | tagged in top 7: fused · J · J_mix | in the seven: engine · J7 | top-level keys |\n"
                "|---|---|---:|---:|---:|---:|---:|---:|---|---|---|\n")
        for r in ds:
            d = r["dish"]
            f.write("| %s | %s | %d of %d | %s | %s | %d | %s | %d | %d · %d · %d | %d · %d | %s |\n" % (
                r["set"], d["why"] or "no", d["returned"], r["U"], fmt(d["tie"]), fmt(d["rho_mix_J"]),
                d["tag_in_explain"], fmt(d["tag_share_med"]), d["tagged"], d["tagged_in_fused7"], d["tagged_in_J7"],
                d["tagged_in_mix7"], d["tagged_in_eng7"], d["tagged_in_j7"], ", ".join(d["keys"]) or "none"))
        f.write("\n")
    if pay:
        w, wo = pay["with"], pay["without"]
        f.write("## Is explainability on the single-love pool calls wasted payload?\n\n")
        f.write("The engine sends `feature.explainability=true` on each entity love's C4 page 1 (offset 0), for the "
                "raw log only; nothing downstream reads it except the k7 gate. On a single-love call it can only say "
                "\"this love, 1.0\": %d of %d page-1 results carry exactly that and nothing else. The same request "
                "with and without it, %d pools × %d reps, no cache, alternating order (medians):\n\n" % (
                    pay["info_free"], pay["results"], pay["pools"], pay["reps"]))
        f.write("| | n | ms | body bytes (JSON) | wire bytes (gzip) |\n|---|---:|---:|---:|---:|\n")
        for k, v in (("with", w), ("without", wo)):
            f.write("| %s explainability | %d | %.0f | %.0f | %.0f |\n" % (k, v["n"], v["ms"], v["body"], v["wire"]))
        f.write("| saved per call (ms: paired per pool) | | %.0f | %.0f (%.1f%%) | %.0f (%.1f%%) |\n\n" % (
            (pay.get("pair_ms") or {}).get("median", w["ms"] - wo["ms"]), w["body"] - wo["body"], 100.0 * (w["body"] - wo["body"]) / max(1, w["body"]),
            w["wire"] - wo["wire"], 100.0 * (w["wire"] - wo["wire"]) / max(1, w["wire"])))
        pm = pay.get("pair_ms") or {}
        f.write("Result order identical with and without it in %d of %d pools. Paired per pool (same request back to "
                "back), the ms difference is a median %s ms, ranging %s to %s ms: noise, not a saving. A query sends one "
                "such call per entity love (2 or 3), so dropping it saves about %.0f to %.0f KB of decoded JSON and "
                "%.1f to %.1f KB on the wire per query, and no measurable time.\n\n" % (
                    pay["same_order"], pay["pools"], fmt(pm.get("median"), 0), fmt(pm.get("min"), 0),
                    fmt(pm.get("max"), 0), 2 * (w["body"] - wo["body"]) / 1000.0, 3 * (w["body"] - wo["body"]) / 1000.0,
                    2 * (w["wire"] - wo["wire"]) / 1000.0, 3 * (w["wire"] - wo["wire"]) / 1000.0))
    f.write("## Cost\n\nPer query the engine rescoring is (live + dish loves) × ceil((|U| − 2) / 48) calls in parallel. "
            "J alone would be ceil((|U| − 2) / 48) (median %s here). Option (b) still needs the per-love calls for "
            "because and holds, so it ADDS J's calls; it saves none. J's live chunk calls (with explainability) took a "
            "median %s ms each.\n" % (fmt(med([r["j_calls"] for r in rows]), 0), fmt(j_ms(), 0)))
    recommend(f, M_, P_, bec, ds)


def j_ms():
    """Median ms of J's live chunk calls; kept from the run that made them (a rerun reads the cache)."""
    fp = os.path.join(cli.OUT, "k13_joint.jms%s.json" % (".fake" if args.fake else ""))
    xs = [t["ms"] for t in q.trace if not t["cache"] and t["status"] == 200 and t["label"].startswith("K13 J ")]
    if xs:
        with open(fp, "w") as f:
            json.dump(xs, f)
    elif os.path.exists(fp):
        with open(fp) as f:
            xs = json.load(f)
    return med(xs)


def recommend(f, M_, P_, bec, ds):
    DS = lambda k: sum(r["dish"][k] for r in ds)  # noqa: E731
    ent_only = [r for r in rows if not r["n_tag"]]
    f.write("\n## Recommendation: (a) keep per-love fusion\n\n")
    f.write("1. **The joint signal cannot carry a dish, and %d of 20 sets have one.** Per-love fusion ranks the dish "
            "through its own order (the dish sub-pool and tag), so the engine's seven hold %d dish-tagged places; J7 "
            "holds %d. %d of the engine's 140 because-lines name the dish; an entity-only joint call cannot. Putting "
            "the tag in the same call does not fix it: the tag never appears in explainability, and the order either "
            "ignores it or loses places from U.\n" % (len(ds), DS("tagged_in_eng7"), DS("tagged_in_j7"), bec["eng_dish"]))
    f.write("2. **Explainability is too flat to be a because.** Top share median %s, margin over the second love %s, "
            "and one love takes a median %s of the argmax credit across U. Where both can speak, it names the "
            "engine's love on %d of %d cards, and the shares it gives are too close to state as a reason.\n" % (
                fmt(M_["share_med"]), fmt(M_["margin_med"]), fmt(M_["top_credit"]), bec["agree"],
                bec["agree"] + bec["disagree"]))
    f.write("3. **Switching buys nothing the product measures.** AI-named cards pooled: engine %d, J7 %d, B7 %d (the "
            "strike does that work either way); ρ with popularity: J %s vs fused %s. J7 keeps a median %s of the "
            "engine's 7 cards; on the %d entity-only sets J7 holds n/n %d vs the engine's %d. The one thing J does "
            "better (J7 holds n/n %d vs %d pooled) comes from the dish sets: J7's cards are the ones strongest on the "
            "two entity loves, so dropping the dish cannot move them.\n" % (
                P_["eng_named"], P_["j_named"], P_["b_named"], fmt(M_["rho_jpop"]), fmt(M_["rho_fpop"]),
                fmt(M_["seven_ov"], 1), len(ent_only), sum(r["holds_j_perlove"] for r in ent_only),
                sum(r["holds_eng"] for r in ent_only), P_["holds_j_perlove"], P_["holds_eng"]))
    f.write("4. **(b) and (c) cost calls and save none.** Both keep the per-love calls (because, holds, dead-love "
            "detection) and add J's chunk calls on top. The blend shares a median %s of 7 with the engine and changes "
            "nothing measured.\n\n" % fmt(M_["blend_ov"], 1))
    f.write("Answer for the judge: we compared them on the same pool. The joint order is a real alternative for "
            "entity loves (ρ %s with ours, same popularity lean), but it has no place for a dish, it returns no "
            "sign that a love is dead, and its explainability splits about evenly between loves, so per-love orders are what make "
            "\"because you love X\" and \"holds if you drop any one love\" true statements. The page-1 "
            "explainability on single-love pool calls is redundant (always \"this love, 1.0\") and can go; it saves "
            "about 0.5%% of the body and no measurable time, and k7 would then need its own call.\n" % fmt(M_["rho_fj"]))


for path in [args.md] + ([args.public_md] if args.public_md else []):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w") as f:
        write(f)
with open(os.path.join(cli.OUT, "k13_joint.json"), "w") as f:
    json.dump({"rows": rows, "names": names, "payload": {k: v for k, v in (pay or {}).items() if k != "raw"}}, f, indent=1, ensure_ascii=False, default=str)
print("  table: %s" % args.md)
print("K13 joint vs fused: %d sets -> %s%s" % (len(rows), cli.verdict(len(rows) > 0), T))
cli.finish(q, args, "k13_joint")
