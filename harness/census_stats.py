"""Census statistics over <provider>_answers.jsonl + OSM rosters, per provider.
  python3 -I census_stats.py                        > census_stats_claude.txt   (identical to the 27 Oct census_stats.txt)
  python3 -I census_stats.py --provider codex       > census_stats_codex.txt
  python3 -I census_stats.py --provider gemini      > census_stats_gemini.txt
  python3 -I census_stats.py --gems                 # fills GEM_GPT and GEM_GEM from stored output only
Copied from research/round4/exp/census_stats.py (unchanged there); the changes are the provider flag, the label, the
output file names, the matcher import from ../engine and the --gems section."""
import argparse, csv, json, math, os, random, re, sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "engine"))
CONSENSUS = os.environ.get("UNSAID_CONSENSUS") or os.path.join(HERE, "..", "..", "research", "exp", "consensus.py")
PROVIDER, LABEL = "claude", "Claude"
LABELS = {"claude": "Claude", "codex": "ChatGPT", "gemini": "Gemini"}
from unsaid.matcher import norm, distinctive, split_parts, fold, PoolIndex  # the kit's normaliser and matcher

OUTSIDE = {  # neighbourhood labels that put a place outside the roster boundary
    "stl": ["clayton", "olivette", "brentwood", "maplewood", "chesterfield", "university city", "maryland heights",
            "belleville", "webster groves", "sunset hills", "lemay", "wentzville", "kirkwood", "richmond heights",
            "westport", "st. charles", "alton", "collinsville", "creve coeur", "ladue", "frontenac", "affton", "florissant"],
    "nyc": ["queens", "bronx", "staten island", ", nj", "woodside", "flushing", "jackson heights", "astoria",
            "long island city", "elmhurst", "corona", "ridgewood", "forest hills", "ozone park", "belmont",
            "riverdale", "city island", "arthur avenue", "edgewater"],
}


def outside(ck, hood):
    h = hood.lower()
    if ck == "stl" and h.startswith("clayton-tamm"):
        return False
    return any(w in h for w in OUTSIDE[ck])


def inext_boot(inc_counts, m, B=400):
    """Chao2 with the iNEXT-style bootstrap (Chao et al. 2014): rebuild the assemblage with
    coverage-adjusted detection probabilities plus f0 unseen, resample m asks, recompute; CI = est +/- 1.96 sd."""
    Q = list(inc_counts); U = sum(Q)
    q1 = sum(1 for x in Q if x == 1); q2 = sum(1 for x in Q if x == 2)
    f0 = (m - 1) / m * (q1 * q1 / (2 * q2) if q2 else q1 * (q1 - 1) / 2)
    A = m * f0 / (m * f0 + q1) if q1 else 1
    a = q1 / m * A  # incidence form (iNEXT EstiBootComm.Sam)
    b = sum(x / m * (1 - x / m) ** m for x in Q)
    w = a / b if f0 else 0
    P = [x / m * (1 - w * (1 - x / m) ** m) for x in Q]
    k0 = math.ceil(f0)
    P += [a / k0] * k0 if k0 else []
    est = chao2(Q, m)
    rr = random.Random(11); bs = []
    for _ in range(B):
        X = [sum(1 for _ in range(m) if rr.random() < p) for p in P]
        X = [x for x in X if x > 0]
        bs.append(chao2(X, m))
    mu = sum(bs) / B; sd = (sum((x - mu) ** 2 for x in bs) / (B - 1)) ** 0.5
    bs.sort()
    return est, max(len(Q), est - 1.96 * sd), est + 1.96 * sd, bs[int(0.025 * B)], bs[int(0.975 * B) - 1]

R = random.Random(7)


def load(provider=None):
    best = {}
    p = os.path.join(HERE, "%s_answers.jsonl" % (provider or PROVIDER))
    if not os.path.exists(p):
        return []
    for l in open(p):
        r = json.loads(l)
        if r.get("superseded_by") or r.get("quarantined"):
            continue
        if r.get("places"):
            best[r["id"]] = r
    return sorted(best.values(), key=lambda r: r["order"])


LOWER_OK = {"and", "of", "the", "a", "at", "on", "in", "de", "la", "le", "y", "n", "&"}


def strip_dish(raw):
    """'Toasted ravioli at Mama Campisi's' -> "Mama Campisi's" when the left side reads as a dish (has a lower-case word)."""
    f = raw.replace("’", "'")
    f = re.sub(r"\s*\([^)]*\)", "", f).strip()
    m = re.match(r"(.+?)\s+at\s+(.+)$", f)
    if m:
        left, right = m.group(1), m.group(2)
        if any(w[:1].islower() and w.lower() not in LOWER_OK for w in left.split()):
            return right, True
    return f, False


def core(s):
    h, _, h2 = split_parts(s)
    d = distinctive(h2 or h) or distinctive(s)
    return " ".join(sorted(d)) or norm(s)


def canon(names):
    """Return per-level mapping raw -> canonical id, and counts of how many raw strings each level folded."""
    lvl = {"L0 raw string": {}, "L1 kit norm": {}, "L2 + dish/paren strip + core key": {}, "L3 + token containment": {}}
    dish = 0
    for n in names:
        lvl["L0 raw string"][n] = n.strip()
        lvl["L1 kit norm"][n] = norm(n)
        s, d = strip_dish(n); dish += d
        lvl["L2 + dish/paren strip + core key"][n] = core(s)
    # L3: a core whose tokens are a subset of a more frequent core's tokens merges into it
    c2 = Counter(lvl["L2 + dish/paren strip + core key"].values())
    keys = sorted(c2, key=lambda k: (-c2[k], len(k)))
    parent = {}
    for k in keys:
        tk = set(k.split())
        for p in keys:
            if p == k or p in parent:
                continue
            tp = set(p.split())
            if tk < tp or tp < tk:
                small = tk if tk < tp else tp
                if len(small) >= 2 or (len(small) == 1 and len(next(iter(small))) >= 6):
                    if c2[p] >= c2[k]:
                        parent[k] = p; break
    lvl["L3 + token containment"] = {n: parent.get(c, c) for n, c in lvl["L2 + dish/paren strip + core key"].items()}
    return lvl, dish, parent


def chao1(counts):
    f1 = sum(1 for x in counts if x == 1); f2 = sum(1 for x in counts if x == 2); S = len(counts)
    est = S + f1 * (f1 - 1) / (2 * (f2 + 1))
    return est, f1, f2


def chao2(inc, m):  # incidence-based, m sampling units
    q1 = sum(1 for x in inc if x == 1); q2 = sum(1 for x in inc if x == 2); S = len(inc)
    return S + (m - 1) / m * q1 * (q1 - 1) / (2 * (q2 + 1))


def chao_lognormal_ci(S, est, f1, f2):
    T = est - S
    if T <= 0:
        return S, S
    # variance of bias-corrected Chao1 (Chao 1987 / EstimateS), then log-normal interval
    if f2 > 0:
        var = f2 * (0.5 * (f1 / f2) ** 2 + (f1 / f2) ** 3 + 0.25 * (f1 / f2) ** 4)
    else:
        var = f1 * (f1 - 1) / 2 + f1 * (2 * f1 - 1) ** 2 / 4 - f1 ** 4 / (4 * est)
    C = math.exp(1.96 * math.sqrt(math.log(1 + var / T ** 2)))
    return S + T / C, S + T * C


def k50(counts):
    tot = sum(counts); acc = 0
    for i, x in enumerate(sorted(counts, reverse=True), 1):
        acc += x
        if acc * 2 >= tot:
            return i, acc, tot


def roster(ck):
    p = os.path.join(HERE, f"osm_{ck}.csv")
    if not os.path.exists(p):
        return None
    return list(csv.DictReader(open(p)))


def main():
    rows = load()
    if PROVIDER != "claude":
        print(f"provider: {PROVIDER} ({LABEL}); models: {sorted(set(r.get('model') or '?' for r in rows))}")
    print(f"answers with a parsed list: {len(rows)}")
    for ck, title in (("stl", "ST. LOUIS"), ("nyc", "NEW YORK (Manhattan + Brooklyn prompts)")):
        rs = [r for r in rows if r["city"] == ck]
        if not rs:
            print(f"\n==================== {title}: no answers stored for {PROVIDER}")
            continue
        allnames = [p["name"] for r in rs for p in r["places"]]
        lvl, dish, parent = canon(allnames)
        print(f"\n==================== {title}: {len(rs)} asks, {len(allnames)} mentions "
              f"(mean {len(allnames)/len(rs):.1f} per answer)")
        print("-- normalisation: distinct names at each level")
        for k, m in lvl.items():
            print(f"   {k:38s} {len(set(m.values()))}")
        print(f"   dish-prefixed strings rewritten ('X at Venue'): {dish}")
        L = lvl["L2 + dish/paren strip + core key"]
        # display name per canonical: most common raw
        disp = defaultdict(Counter)
        for n in allnames:
            disp[L[n]][n] += 1
        show = {c: d.most_common(1)[0][0] for c, d in disp.items()}
        merged = {c: sorted(d) for c, d in disp.items() if len(d) > 1}
        print(f"   canonical names with >1 raw spelling: {len(merged)}; examples:")
        for c, d in sorted(merged.items(), key=lambda x: -len(x[1]))[:8]:
            print("     ", " | ".join(d))
        if parent:
            print(f"   L3 containment merges ({len(parent)}): " + "; ".join(f"{show[k]} -> {show[v]}" for k, v in list(parent.items())[:12]))
        # per-ask sets at L2 (headline level per pre-registration)
        sets = [sorted({L[p["name"]] for p in r["places"]}) for r in rs]
        inc = Counter(c for s in sets for c in s)
        ment = Counter(L[n] for n in allnames)
        S = len(inc)
        print(f"-- SAID (L2, headline) = {S}; L3 sensitivity = {len(set(lvl['L3 + token containment'].values()))}")
        # accumulation curve (actual shuffled order) + mean over 200 random orders
        seen = set(); curve = []
        for s in sets:
            new = [c for c in s if c not in seen]; seen |= set(s); curve.append((len(seen), len(new), len(s)))
        perm = []
        for _ in range(200):
            o = sets[:]; R.shuffle(o); sn = set(); cv = []
            for s in o:
                sn |= set(s); cv.append(len(sn))
            perm.append(cv)
        mean = [sum(p[i] for p in perm) / len(perm) for i in range(len(sets))]
        print("-- accumulation (ask k: distinct so far, new at this ask; mean over 200 random orders)")
        for k in (1, 2, 4, 8, 12, 16, 24, 32, 40, 48, 56, 64):
            if k <= len(curve):
                print(f"   ask {k:2d}: {curve[k-1][0]:4d}  new {curve[k-1][1]:2d}   mean-order {mean[k-1]:6.1f}")
        last = curve[-20:]
        newl = sum(x[1] for x in last); menl = sum(x[2] for x in last)
        print(f"   last 20 asks: {newl} new names / {menl} mentions = {newl/menl:.1%} (flat rule: <2%)")
        for a, b in ((44, 64), (32, 48), (48, 64)):
            if b <= len(mean):
                print(f"   mean new per ask, asks {a+1}-{b}: {(mean[b-1]-mean[a-1])/(b-a):.2f}")
        for lab, keep in (("generic+hidden only", ("generic", "hidden")), ("taste+strangers only", ("taste", "stranger"))):
            ss = [s_ for r, s_ in zip(rs, sets) if r["family"] in keep]
            sn = set(); cv = []
            for s_ in ss:
                n_ = len(set(s_) - sn); sn |= set(s_); cv.append((len(sn), n_, len(s_)))
            l10 = cv[-10:]
            print(f"   {lab}: {len(ss)} asks -> {len(sn)} distinct; last 10 asks add {sum(x[1] for x in l10)} new / {sum(x[2] for x in l10)} mentions ({sum(x[1] for x in l10)/sum(x[2] for x in l10):.0%})")
        # Chao
        est, f1, f2 = chao1(list(ment.values()))
        lo, hi = chao_lognormal_ci(S, est, f1, f2)
        c2 = chao2(list(inc.values()), len(sets))
        e2, blo, bhi, plo, phi = inext_boot(list(inc.values()), len(sets))
        q1 = sum(1 for x in inc.values() if x == 1); q2 = sum(1 for x in inc.values() if x == 2)
        print(f"-- mention singletons f1={f1} ({f1/S:.0%} of SAID), doubletons f2={f2}; ask-incidence Q1={q1}, Q2={q2}")
        print(f"   Chao1 (mentions) = {est:.0f}, log-normal 95% CI {lo:.0f}-{hi:.0f}")
        print(f"   Chao2 (asks as units) = {e2:.0f}, bootstrap 95% CI {blo:.0f}-{bhi:.0f} (percentile {plo:.0f}-{phi:.0f}; 400 iNEXT-style resamples)")
        print(f"   coverage: SAID is {S/e2:.0%} of the Chao2 estimate")
        kk, acc, tot = k50(list(ment.values()))
        print(f"-- K50 = {kk} names carry {acc}/{tot} mentions ({acc/tot:.0%}); that is {kk/S:.0%} of SAID")
        top10 = sum(x for _, x in ment.most_common(10))
        print(f"   top 10 carry {top10/tot:.0%} of mentions; top 20 carry {sum(x for _,x in ment.most_common(20))/tot:.0%}")
        fams_of = lambda c: "/".join(str(sum(1 for r, s_ in zip(rs, sets) if (r["person"] or r["family"]) == f and c in s_)) for f in ("generic", "hidden", "cedric", "jason", "stranger"))
        print("   top 12 by family (generic/hidden/cedric/jason/stranger asks): " + "; ".join(f"{show[c]} {fams_of(c)}" for c, _ in inc.most_common(12)))
        first = Counter(L[r["places"][0]["name"]] for r in rs if r["family"] == "hidden")
        print("   named FIRST in the 16 hidden-gem asks: " + ", ".join(f"{show[c]} {x}" for c, x in first.most_common(4)))
        NONFOOD = re.compile(r"museum|garden|park\b|murals|antique|casino|comedy|funny bone|helium|theat|pageant|stadium|ballpark|\barch\b|zoo|cemetery|mansion|mounds|record|radio|gallery|cathedral|foundation|memorial|terminal|island", re.I)
        FOODOK = re.compile(r"cafe|coffee|shack|seoul garden|grille|smoke house|eleven madison|avant garden|tacos|tap room|chase club|on the park|soho park", re.I)
        nfc = {c for c in inc if NONFOOD.search(show[c]) and not FOODOK.search(show[c])}
        nf = sorted(show[c] for c in nfc)  # sorted: the 27 Oct file printed this in hash-seeded set order
        print(f"   names that look like non-restaurant venues (museums, parks, comedy/music clubs...): {len(nf)}: {', '.join(nf[:30])}")
        print("   most named (asks out of %d): " % len(sets) + ", ".join(f"{show[c]} {x}" for c, x in inc.most_common(20)))
        # families
        fam = defaultdict(list)
        for r, s in zip(rs, sets):
            key = r["person"] or r["family"]
            fam[key].append(s)
        print("-- by family: asks, distinct, mean list length")
        for k, v in fam.items():
            u = set(c for s in v for c in s)
            print(f"   {k:9s} {len(v):2d} asks, {len(u):3d} distinct")
        H = fam["hidden"]; hc = Counter(c for s in H for c in s)
        gen = set(c for s in fam["generic"] for c in s)
        print(f"-- HIDDEN-GEM family: {len(H)} asks, {sum(hc.values())} mentions, {len(hc)} distinct; "
              f"{sum(1 for c in hc if c in gen)}/{len(hc)} also named in the 14 mainstream asks")
        print("   most repeated 'hidden gems' (asks out of %d):" % len(H))
        for c, x in hc.most_common(15):
            hoods = Counter(p["neighbourhood"] for r in rs if (r["family"] == "hidden") for p in r["places"] if L[p["name"]] == c)
            print(f"     {show[c]:40s} {x:2d}/{len(H)}   also mainstream: {'yes' if c in gen else 'no ':3s}  ({hoods.most_common(1)[0][0]})")
        hk = k50(list(hc.values()))
        print(f"   hidden-gem K50 = {hk[0]} of {len(hc)}")
        # overlap
        G = gen | set(c for s in H for c in s) | set(c for s in fam["stranger"] for c in s)
        GH = gen | set(c for s in H for c in s)
        Cd = set(c for s in fam["cedric"] for c in s); Js = set(c for s in fam["jason"] for c in s)
        jac = lambda a, b: len(a & b) / len(a | b)
        print("-- taste vs generic (generic = mainstream + hidden-gem asks)")
        print(f"   Cedric {len(Cd)} distinct, {len(Cd & GH)} ({len(Cd & GH)/len(Cd):.0%}) also in generic; Jason {len(Js)}, {len(Js & GH)} ({len(Js & GH)/len(Js):.0%}) also in generic")
        print(f"   Cedric∩Jason = {len(Cd & Js)}: {', '.join(sorted(show[c] for c in Cd & Js))}")
        print(f"   Jaccard: Cedric-generic {jac(Cd, GH):.2f}, Jason-generic {jac(Js, GH):.2f}, Cedric-Jason {jac(Cd, Js):.2f}")
        cm = Counter(c for s in fam["cedric"] for c in s); jm = Counter(c for s in fam["jason"] for c in s)
        print("   Cedric top: " + ", ".join(f"{show[c]} {x}/{len(fam['cedric'])}" for c, x in cm.most_common(8)))
        print("   Jason top:  " + ", ".join(f"{show[c]} {x}/{len(fam['jason'])}" for c, x in jm.most_common(8)))
        st = set(c for s in fam["stranger"] for c in s)
        others = set(c for k, v in fam.items() if k != "stranger" for s in v for c in s)
        print(f"   strangers: {len(st)} distinct, {len(st & others)/len(st):.0%} already named by the other 54 asks")
        # roster
        ros = roster(ck)
        if ros:
            named = [x for x in ros if x["name"]]
            pool = [{"entity_id": x["osm"], "name": x["name"]} for x in named]
            byid = {x["osm"]: x for x in named}
            idx = PoolIndex(pool)
            hit = {}; hit_r1 = set()
            for c in inc:
                ids = set()
                for raw in disp[c]:
                    s_, _ = strip_dish(raw)
                    r1 = idx.r1(s_)
                    if r1:
                        hit_r1.add(c)
                    ids |= set(r1) | {e for e, _ in idx.containment(s_)}
                if ids:
                    hit[c] = [byid[e] for e in sorted(ids)]
            hood = {c: Counter(p["neighbourhood"] for r in rs for p in r["places"] if L[p["name"]] == c).most_common(1)[0][0] for c in inc}
            out = {c for c in inc if outside(ck, hood[c]) and c not in hit}
            S_in = S - len(out)
            S_in_food = S - len(out | nfc)
            rb = sum(1 for x in named if x["amenity"] in ("restaurant", "bar", "pub"))
            print(f"-- OSM roster: {len(ros)} features, {len(named)} named (restaurant/bar/pub only: {rb}); "
                  f"by amenity {dict(Counter(x['amenity'] for x in named))}")
            print(f"   SAID labelled outside the boundary by {LABEL}'s own neighbourhood (and not matched in OSM): {len(out)}; SAID inside ~ {S_in}")
            print(f"   SAID/CITY = {S}/{len(named)} = {S/len(named):.1%} (all names); inside-only {S_in}/{len(named)} = {S_in/len(named):.1%}; vs restaurant+bar+pub {S_in}/{rb} = {S_in/rb:.1%}")
            print(f"   eat-and-drink only (minus {len(nfc)} museums/parks/clubs/casinos), inside: {S_in_food}/{len(named)} = {S_in_food/len(named):.1%}")
            print(f"   Chao2 vocabulary / CITY = {e2:.0f}/{len(named)} = {e2/len(named):.0%}")
            mh = sum(ment[c] for c in hit)
            print(f"   SAID names matched to an OSM name: exact keys {len(hit_r1)}/{S}; with containment {len(hit)}/{S} ({len(hit)/S:.0%}), carrying {mh}/{tot} mentions")
            print(f"   OSM places matched to a {LABEL} name: {len({x['osm'] for v in hit.values() for x in v})} of {len(named)}"
                  f" ({len({x['osm'] for v in hit.values() for x in v})/len(named):.1%}); never named: {1-len({x['osm'] for v in hit.values() for x in v})/len(named):.1%}")
            um = [f"{show[c]} {x}" for c, x in inc.most_common() if c not in hit][:15]
            print("   most-named NOT found in OSM by name: " + ", ".join(um))
        if ck == "stl" and os.path.exists(CONSENSUS):
            src = open(CONSENSUS).read()
            ns = {}
            exec(compile(src.split("def stats")[0], "consensus_walls", "exec"), ns)
            wall = {core(n) for d in (ns["STL"], ns["STL_FRESH"], ns["JASON_STL"]) for v in d.values() for n in v}
            onw = [c for c in inc if c in wall]
            print(f"-- vs the saved round-2 STL wall ({len(wall)} distinct): {len(onw)}/{S} {LABEL} names are on it, carrying "
                  f"{sum(ment[c] for c in onw)}/{tot} mentions ({sum(ment[c] for c in onw)/tot:.0%})")
            sk = core("Smoki O's")
            print(f"   Smoki O's: named in {inc.get(sk, 0)} of {len(sets)} asks")
        # dump canonical table for the prototype
        with open(os.path.join(HERE, f"{PROVIDER}_named_{ck}.csv"), "w", newline="") as f:
            w = csv.writer(f); w.writerow(["canonical", "display", "asks", "mentions", "hidden_asks", "cedric_asks", "jason_asks", "spellings", "osm_match", "osm_ids"])
            for c, x in inc.most_common():
                hm = (hit.get(c) if ros else None) or []
                w.writerow([c, show[c], x, ment[c], hc.get(c, 0), cm.get(c, 0), jm.get(c, 0), " | ".join(sorted(disp[c])), bool(hm), " ".join(h["osm"] for h in hm)])
        with open(os.path.join(HERE, f"{PROVIDER}_curve_{ck}.csv"), "w", newline="") as f:
            w = csv.writer(f); w.writerow(["ask", "id", "distinct_so_far", "new", "listed", "mean_random_order"])
            for i, ((d, n, l), r) in enumerate(zip(curve, rs), 1):
                w.writerow([i, r["id"], d, n, l, round(mean[i-1], 1)])


GEMS = {"stl": "Gioia's Deli", "nyc": "Sripraphai"}
FILL = {"codex": "GEM_GPT", "gemini": "GEM_GEM", "claude": "(census: 13)"}


def gem_tokens(name):
    s_, _ = strip_dish(name)
    t = set(core(s_).split()) | set(distinctive(s_))
    return t | {x[:-1] for x in t if x.endswith("s") and len(x) > 4}  # "Gioias" -> gioia


def gem_hit(name, target):
    return set(core(target).split()) <= gem_tokens(name)


def gems():
    """Each provider's hidden-gem asks that name the census gem. Read from stored output only: an ask counts if its
    parsed list names the gem (core-key containment, so "Sripraphai Thai Restaurant" counts), or, for an answer stored
    without a parsed list, if its raw text contains the gem's core token. The census's own L2 rule is printed beside."""
    print("hidden-gem asks naming the census gem, per provider (16 asks per city; from stored output only)")
    for prov in LABELS:
        p = os.path.join(HERE, "%s_answers.jsonl" % prov)
        recs = {}
        if os.path.exists(p):
            for l in open(p):
                r = json.loads(l)
                if r.get("superseded_by") or r.get("quarantined"):
                    continue
                if r.get("status") in ("ok", "unparsed") or ("status" not in r and r.get("places")):
                    recs[r["id"]] = r
        rs = list(recs.values())
        for ck, target in GEMS.items():
            H = [r for r in rs if r["city"] == ck and r["family"] == "hidden"]
            G = [r for r in rs if r["city"] == ck and r["family"] == "generic"]
            tk = core(target)

            def named(r):
                if r.get("places"):
                    return any(gem_hit(x["name"], target) for x in r["places"])
                return all(t in norm(r.get("raw") or "").split() for t in tk.split())
            hits = sum(1 for r in H if named(r))
            first = sum(1 for r in H if r.get("places") and gem_hit(r["places"][0]["name"], target))
            plain = sum(1 for r in G if named(r))
            allnames = [x["name"] for r in rs if r["city"] == ck for x in (r.get("places") or [])]
            Lm = canon(allnames)[0]["L2 + dish/paren strip + core key"] if allnames else {}
            l2 = sum(1 for r in H if any(Lm.get(x["name"]) == tk for x in (r.get("places") or [])))
            models = sorted(set(r.get("model") or "?" for r in H))
            unp = sum(1 for r in H if not r.get("places"))
            line = (f"  {LABELS[prov]:8s} {ck}: {target} in {hits} of {len(H)} hidden-gem asks stored (named first in {first}; "
                    f"census L2 rule {l2}; {unp} without a parsed list) · plain asks {plain} of {len(G)} · model {', '.join(models) or '-'}")
            print(line)
            if prov != "claude":
                tag = FILL[prov] if ck == "stl" else FILL[prov] + "_NYC"
                # as stored, never extrapolated: m = hidden-gem asks with a stored answer
                print(f"    {tag} = {hits} of {len(H)} asked ({ck}, {target}; 16 planned)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default="claude", choices=sorted(LABELS))
    ap.add_argument("--gems", action="store_true")
    a = ap.parse_args()
    PROVIDER, LABEL = a.provider, LABELS[a.provider]
    if a.gems:
        gems()
    else:
        main()
