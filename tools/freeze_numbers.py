#!/usr/bin/env python3
"""The freeze's bookkeeping (freeze.sh calls it; every subcommand reads stored files only, 0 Qloo calls).

  freeze_numbers.py walls-keep <backup dir>       after a walls rebuild: put back every data/walls/*.json whose
                                                  content is unchanged but for meta.built_at (no churn in git)
  freeze_numbers.py snapshot-cedric <result.json> <out.json>     Cedric's seven + reserves, for the next run's diff
  freeze_numbers.py numbers --fresh DIR --nostreet DIR           out/freeze/numbers.json from the step 2/3 logs
  freeze_numbers.py agentcheck --fresh DIR        the video's agent shot (agent/demo/live_transcript.jsonl) vs Cedric
  freeze_numbers.py report                        the final report (gates, numbers, unfilled, Cedric diff, quote)

numbers.json: {"placeholders": {KEY: {value, source, note}}, "gates": {...}, "cedric": ..., "street": ..., "walls": ...,
"qloo_calls": ...}. A value is None when it was not measured: fill_devpost.py then leaves the ⟦KEY⟧ as it is.
Contains card names (Qloo output): out/ is gitignored."""
import collections
import datetime as dt
import glob
import json
import os
import re
import subprocess
import sys
from itertools import combinations

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS = os.path.join(ROOT, "out", "freeze")
NUMBERS = os.path.join(LOGS, "numbers.json")
WALLS = os.path.join(ROOT, "data", "walls")
AGENT_DEMO = os.path.join(ROOT, "site", "data", "live", "agent_demo.json")
TRANSCRIPT = os.path.join(ROOT, "agent", "demo", "live_transcript.jsonl")
# ⟦AGENT_QUOTE⟧: the approved candidate (LOG 28 Oct, Agent E), verbatim from agent_demo.json. It is about The Spot
# Sports Bar at #13 for you and #78 of 78 for anyone; it is used only while all three still hold for Cedric's card.
QUOTE = ("Generic rankings put it dead last of 78, but for your taste it's #13, so it's the hidden gem on this list.")
QUOTE_CARD, QUOTE_FIT, QUOTE_ANY, QUOTE_U = "The Spot Sports Bar", 13, 78, 78
# The recording that holds the approved quote, kept before the freeze re-records agent_demo.json (tools/agent_rerecord.py
# archives it here; a re-recorded answer words things differently, so the quote is checked against this one)
QUOTE_SRC = os.path.join(os.path.dirname(ROOT), "private", "agent_quote_source.json")
ET = dt.timezone(dt.timedelta(hours=-4))   # EDT until 1 Nov 2026
# Similar tastes (St. Louis soul and hip-hop; indie): the copy says these share the most cards (⟦CLUSTER_MAX⟧)
CLUSTERS = (("stl-cedric", "stl-sza", "stl-jayz", "stl-nelly"), ("stl-wilco", "stl-bigthief"))


def log(name):
    p = os.path.join(LOGS, name)
    return open(p).read() if os.path.exists(p) else ""


def rx(text, pattern, cast=str, group=1):
    m = re.search(pattern, text, re.M)
    return cast(m.group(group)) if m else None


def num(x):
    if x is None:
        return None
    return str(int(x)) if float(x) == int(x) else "%.1f" % x


def median(xs):
    s = sorted(xs)
    n = len(s)
    if not n:
        return None
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def load_sets(d):
    out = {}
    p = os.path.join(d, "index.json")
    if not os.path.exists(p):
        return out
    for s in json.load(open(p))["sets"]:
        out[s["id"]] = dict(json.load(open(os.path.join(d, s["file"]))), status=s.get("status"))
    return out


def hood_norm(s):
    s = (s or "").lower().replace("saint ", "st ").replace("st. ", "st ")
    return re.sub(r"[^a-z0-9 ]", "", s).strip()


# ----------------------------------------------------------------------------------------------------------- provenance
REGEN_WALLS = os.path.join(LOGS, "walls.regen")      # the exact walls the regeneration read (copied at stamp time)
ENGINE_PATHS = ["engine/unsaid", "engine/precompute.py"]


def git_out(*a, cwd=ROOT):
    return subprocess.run(["git", "-C", cwd] + list(a), capture_output=True, text=True).stdout.strip()


def tree_hash(d, pattern="*.json"):
    import hashlib
    h = hashlib.sha256()
    for p in sorted(glob.glob(os.path.join(d, pattern))):
        h.update(os.path.basename(p).encode() + b"\0" + open(p, "rb").read() + b"\0")
    return h.hexdigest()


def stamp(a):
    """After a regeneration: which engine, priors and walls made $FRESH, and when (-> $FRESH/freeze_stamp.json)."""
    import shutil
    wt = a.wt
    doc = {"regenerated_at": dt.datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z"),
           "index_generated_at": json.load(open(os.path.join(a.fresh, "index.json"))).get("generated_at"),
           "engine_commit": git_out("rev-parse", "HEAD", cwd=wt),
           "priors_sha256": tree_hash(os.path.join(wt, "data", "priors")),
           "walls_sha256": tree_hash(os.path.join(wt, "data", "walls"))}
    json.dump(doc, open(os.path.join(a.fresh, "freeze_stamp.json"), "w"), indent=1)
    shutil.rmtree(REGEN_WALLS, ignore_errors=True)
    shutil.copytree(os.path.join(wt, "data", "walls"), REGEN_WALLS)
    print("stamp: %s engine %s, priors %s, walls %s -> %s" % (doc["regenerated_at"], doc["engine_commit"][:7],
                                                              doc["priors_sha256"][:8], doc["walls_sha256"][:8], a.fresh))


def prereg(a=None):
    """The five pre-registered files vs the public gist's hashes (data/prereg/SHA256SUMS). Exit 1 on any mismatch."""
    import hashlib
    where = {"UNSAID.md": os.path.join(os.path.dirname(ROOT), "prereg-private", "UNSAID.md")}   # private build doc
    bad = 0
    for line in open(os.path.join(ROOT, "data", "prereg", "SHA256SUMS")):
        if not line.strip():
            continue
        h, name = line.split(None, 1)
        name = name.split(" (")[0].strip()
        p = where.get(name, os.path.join(ROOT, "data", name))
        got = hashlib.sha256(open(p, "rb").read()).hexdigest() if os.path.exists(p) else "missing"
        print("prereg %-24s %s" % (name, "ok" if got == h else "MISMATCH (now %s, gist %s)" % (got[:8], h[:8])))
        bad += got != h
    return 1 if bad else 0


def provenance(fresh):
    """The regeneration's stamp vs the tree now. Problems -> fill_devpost.py refuses to fill."""
    sp = os.path.join(fresh, "freeze_stamp.json")
    st = json.load(open(sp)) if os.path.exists(sp) else {}
    head_engine = git_out("log", "-1", "--format=%H", "HEAD", "--", *ENGINE_PATHS)
    now_priors = tree_hash(os.path.join(ROOT, "data", "priors"))
    probs = []
    if not st:
        probs.append("no %s: this regeneration was not made by freeze.sh step 2" % sp)
    else:
        if subprocess.run(["git", "-C", ROOT, "merge-base", "--is-ancestor", head_engine, st["engine_commit"]]).returncode:
            probs.append("the regeneration ran on engine %s, which predates HEAD's last engine commit %s" % (
                st["engine_commit"][:7], head_engine[:7]))
        if st.get("priors_sha256") != now_priors:
            probs.append("the regeneration's priors (sha256 %s) differ from data/priors now (%s)" % (
                (st.get("priors_sha256") or "?")[:8], now_priors[:8]))
    return {"stamp": st, "head_engine_commit": head_engine, "priors_sha256_now": now_priors, "problems": probs}


# ---------------------------------------------------------------------------------------------------------- walls-keep
def walls_keep(backup):
    kept, changed, new = [], [], []
    for p in sorted(glob.glob(os.path.join(WALLS, "*.json"))):
        b = os.path.join(backup, os.path.basename(p))
        if not os.path.exists(b):
            new.append(os.path.basename(p))
            continue
        x, y = json.load(open(p)), json.load(open(b))
        for d in (x, y):
            (d.get("meta") or {}).pop("built_at", None)
        if x == y:
            with open(b, "rb") as fi, open(p, "wb") as fo:
                fo.write(fi.read())
            kept.append(os.path.basename(p))
        else:
            changed.append(os.path.basename(p))
    print("walls: unchanged (kept byte for byte) %s; changed %s; new %s" % (
        ", ".join(kept) or "none", ", ".join(changed) or "none", ", ".join(new) or "none"))


# ------------------------------------------------------------------------------------------------------ snapshot-cedric
def cedric_of(path):
    d = json.load(open(path))
    r = d["result"]
    return {"file": path, "ran_at": d.get("ran_at"), "as_of": d.get("as_of"),
            "seven": [{"id": p["id"], "name": p["name"], "fit_rank": p.get("fit_rank"), "any_rank": p.get("any_rank")}
                      for p in r["picks"]],
            "reserves": [p["name"] for p in r.get("reserves") or []], "counts": r.get("counts")}


def snapshot_cedric(src, out):
    if not os.path.exists(src):
        print("no %s: nothing to snapshot" % src)
        return
    c = cedric_of(src)
    json.dump(c, open(out, "w"), indent=1, ensure_ascii=False)
    print("Cedric before this run (%s): %s" % (c["ran_at"], "; ".join(p["name"] for p in c["seven"])))


# ------------------------------------------------------------------------------------------------------------ numbers
def walls_stats(wdir=None):
    seen, per = set(), collections.Counter()
    first, last = None, None
    total_nosearch, gem = 0, 0
    city_ns = collections.Counter()
    for p in sorted(glob.glob(os.path.join(wdir or WALLS, "*.json"))):
        d = json.load(open(p))
        search = bool((d.get("meta") or {}).get("search"))
        for e in d["walls"]:
            for a in e["answers"]:
                if a["id"] in seen:
                    continue
                seen.add(a["id"])
                t = a.get("asked_at")
                if t:
                    first = t if first is None or t < first else first
                    last = t if last is None or t > last else last
                prov = a.get("provider")
                per[(os.path.basename(p), prov, e.get("city"))] += 1
                if search or a.get("search") == "on" or a.get("lane") != "dated":
                    continue
                if prov in ("anthropic", "openai"):
                    total_nosearch += 1
                    city_ns[e.get("city")] += 1
                else:
                    gem += 1
    by_city = collections.Counter()
    for (f, prov, city), n in per.items():
        by_city[city] += n
    return {"answers": len(seen), "claude_chatgpt_dated_no_search": total_nosearch, "other_dated_no_search": gem,
            "claude_chatgpt_dated_no_search_by_city": dict(city_ns),
            "first_asked_at": first, "last_asked_at": last, "by_city_all": dict(by_city),
            "by_file": {"%s %s %s" % k: v for k, v in sorted(per.items(), key=lambda kv: str(kv[0]))}}


def date_range(first, last):
    a = dt.datetime.fromisoformat(first).astimezone(ET)
    b = dt.datetime.fromisoformat(last).astimezone(ET)
    if (a.year, a.month) == (b.year, b.month):
        return "%d–%d %s %d" % (a.day, b.day, b.strftime("%b"), b.year) if a.day != b.day else \
            "%d %s %d" % (a.day, a.strftime("%b"), a.year)
    return "%d %s – %d %s %d" % (a.day, a.strftime("%b"), b.day, b.strftime("%b"), b.year)


def street_stats(fresh, nostreet, wdir=None):
    """Cards the street answers struck: the no-street run's cards that the full run's wall strikes by a street:*
    answer. Denominator: those cards whose neighbourhood a street answer was asked about."""
    full, ns = load_sets(fresh), load_sets(nostreet)
    hoods = street_hoods(wdir)
    if len(ns) != len(full) or not full:
        return {"ok": False, "why": "no-street ablation incomplete (%d of %d sets)" % (len(ns), len(full))}
    cards = asked = named = named_asked = 0
    unasked, hits = [], []
    for sid, d in full.items():
        city = d["city"]
        struck_by_street = {w.get("qloo_id") for w in d["result"]["wall"]
                            if w.get("outcome") == "struck" and str(w.get("phrasing_id", "")).startswith("street:")}
        final_ids = {p["id"] for p in d["result"]["picks"]}
        for p in ns[sid]["result"]["picks"]:
            cards += 1
            h = hood_norm(p.get("neighbourhood"))
            was_asked = bool(h) and h in hoods[city]
            asked += was_asked
            if not was_asked:
                unasked.append("%s: %s (%s)" % (sid, p["name"], p.get("neighbourhood") or "no neighbourhood"))
            if p["id"] in struck_by_street and p["id"] not in final_ids:
                named += 1
                named_asked += was_asked
                hits.append("%s: %s (%s)" % (sid, p["name"], p.get("neighbourhood")))
    return {"ok": True, "cards": cards, "cards_hood_asked": asked, "named": named, "named_hood_asked": named_asked,
            "unasked": unasked, "hits": hits, "hoods_asked": {c: len(v) for c, v in hoods.items()}}


def street_hoods(wdir=None):
    hoods = collections.defaultdict(set)
    for p in glob.glob(os.path.join(wdir or WALLS, "*.json")):
        for e in json.load(open(p))["walls"]:
            for a in e["answers"]:
                if a.get("kind") == "street" and a.get("hood"):
                    hoods[e.get("city")].add(hood_norm(a["hood"]))
    return hoods


def unasked(a):
    """Neighbourhoods of the regenerated cards and reserves that no street answer in data/walls was asked about.
    Writes {"cities": {city: [neighbourhood, ...]}} (the --hoods-file format of walls_cli.py ask --kind street)."""
    asked, out, n_cards, none = street_hoods(), collections.defaultdict(set), 0, []
    for sid, d in load_sets(a.fresh).items():
        for p in d["result"]["picks"] + d["result"].get("reserves", []):
            n_cards += 1
            h = (p.get("neighbourhood") or "").strip()
            if not h:
                none.append("%s: %s" % (sid, p["name"]))
            elif hood_norm(h) not in asked[d["city"]]:
                out[d["city"]].add(h)
    doc = {"source": "neighbourhood fields of %s picks and reserves not yet asked (tools/freeze_numbers.py unasked)" % a.fresh,
           "cities": {c: sorted(v) for c, v in sorted(out.items())}}
    if a.write:
        json.dump(doc, open(a.write, "w"), indent=1, ensure_ascii=False)
    n = sum(len(v) for v in out.values())
    print("street: %d unasked neighbourhoods (%s) over %d cards + reserves%s%s" % (
        n, ", ".join("%s %d" % (c, len(v)) for c, v in sorted(out.items())) or "none", n_cards,
        "; %d without a neighbourhood: %s" % (len(none), "; ".join(none[:5])) if none else "",
        "; -> %s" % a.write if a.write else ""))
    print("UNASKED=%d" % n)


def numbers(a):
    fresh, nostreet = a.fresh, a.nostreet
    P, G = {}, {}

    def put(k, v, src, note=""):
        P[k] = {"value": v, "source": src, "note": note}

    # ---- gates A, B, C (regen_try.sh, --frozen)
    ga, gb = log("02-gateA.txt"), log("02-gateB.txt")
    G["A"] = {"verdict": rx(ga, r"^A taste moves: (\w+)"), "nyc_pass": rx(ga, r"^  NYC: rho<=0\.90 in (\d+) of", int),
              "stl_pass": rx(ga, r"^  STL: rho<=0\.90 in (\d+) of", int),
              "strangers": rx(ga, r"two strangers .*: sevens share (\d+)", int),
              "pairs_median_k2a": rx(ga, r"both cities: median sevens shared ([\d.]+)", float),
              "source": "out/freeze/02-gateA.txt (engine/k2a_lift.py --frozen)"}
    G["B"] = {"verdict": rx(gb, r"^B survivors: (\w+)"), "nyc_pass": rx(gb, r"^  NYC: (\d+) of \d+ sets pass", int),
              "stl_pass": rx(gb, r"^  STL: (\d+) of \d+ sets pass", int),
              "source": "out/freeze/02-gateB.txt (engine/k3_survivors.py --frozen)"}
    cap = rx(gb, r"cap overlap median ([\d.]+|n/a) over (\d+) sets")
    G["C"] = {"cap_overlap_median": None if cap in (None, "n/a") else float(cap),
              "sets": rx(gb, r"cap overlap median \S+ over (\d+) sets", int), "bar": 0.80,
              "source": "out/freeze/02-gateB.txt ('cap overlap median', k3_survivors.py)"}
    G["C"]["verdict"] = None if G["C"]["cap_overlap_median"] is None else (
        "PASS" if G["C"]["cap_overlap_median"] <= 0.80 else "FAIL")
    put("CAP_MED", cap if cap not in (None, "n/a") else None, G["C"]["source"])

    # ---- precompute + the regen summary
    rg = log("02-regen.log")
    G["precompute"] = {"verdict": rx(rg, r"^precompute: \d+ of \d+ sets written .* -> (\w+)"),
                       "line": rx(rg, r"^(precompute: .*)$"), "source": "out/freeze/02-regen.log"}
    distinct = rx(rg, r"^distinct places (\d+) of (\d+);", int)
    maxrep = rx(rg, r"max repeats of one place per city (\d+)", int)
    sets = load_sets(fresh)
    cards = [(d["city"], p["id"]) for d in sets.values() for p in d["result"]["picks"]]
    if cards:   # recount from the cards themselves (the same numbers regen_try prints)
        d2 = len({i for _, i in cards})
        m2 = max(collections.Counter(cards).values())
        if distinct is not None and (d2 != distinct or m2 != maxrep):
            print("WARN: regen summary (%s, %s) differs from the cards (%s, %s); using the cards" % (distinct, maxrep, d2, m2))
        distinct, maxrep = d2, m2
    src = "%s (the 20 regenerated sets; engine/regen_try.sh summary)" % fresh
    put("DISTINCT", None if distinct is None else str(distinct), src, "%d cards" % len(cards))
    put("MAXREP", None if maxrep is None else str(maxrep), src)

    # ---- PAIRS_MED: cards shared by any two sets in a city, over the shipped sevens
    sh = []
    by_city = collections.defaultdict(list)
    for sid, d in sets.items():
        by_city[d["city"]].append({p["id"] for p in d["result"]["picks"]})
    for c, ss in by_city.items():
        sh += [len(x & y) for x, y in combinations(ss, 2)]
    pm = median(sh)
    G["pairs"] = {"median": pm, "pairs": len(sh), "max": max(sh) if sh else None, "k2a_median": G["A"]["pairs_median_k2a"],
                  "source": src}
    if pm is not None and G["A"]["pairs_median_k2a"] is not None and abs(pm - G["A"]["pairs_median_k2a"]) > 1e-9:
        print("WARN: pairs median over the shipped cards %s != k2a's %s (k2a reruns the engine without last-seen)" % (
            pm, G["A"]["pairs_median_k2a"]))
    put("PAIRS_MED", num(pm), src + "; cross-check engine/k2a_lift.py 'both cities: median'",
        "%d within-city pairs, max %s" % (len(sh), G["pairs"]["max"]))
    put("CARDS", str(len(cards)) if cards else None, src, "cards over the 20 sets (7 each unless a set came up short)")

    # ---- where shared cards sit: pairs of similar tastes (CLUSTERS) vs every other within-city pair; the strangers
    seven = {sid: {p["id"] for p in d["result"]["picks"]} for sid, d in sets.items()}
    if all(s in seven for c in CLUSTERS for s in c) and "stl-cedric" in seven and "stl-jason" in seven:
        cl = {frozenset(x) for c in CLUSTERS for x in combinations(c, 2)}
        cin = [len(seven[a] & seven[b]) for a, b in cl]
        cout = [len(seven[a] & seven[b]) for a, b in combinations(sorted(seven), 2)
                if sets[a]["city"] == sets[b]["city"] and frozenset((a, b)) not in cl]
        put("CLUSTER_MAX", str(max(cin)), src, "most cards shared by two sets of a cluster %s" % [list(c) for c in CLUSTERS])
        put("OTHER_MAX", str(max(cout)), src, "most cards shared by any other two sets in a city (%d pairs)" % len(cout))
        stv = len(seven["stl-cedric"] & seven["stl-jason"])
        if G["A"]["strangers"] is not None and G["A"]["strangers"] != stv:
            print("WARN: strangers share %s in the shipped cards, %s in k2a" % (stv, G["A"]["strangers"]))
        put("STRANGERS", str(stv), src + "; cross-check out/freeze/02-gateA.txt", "Cedric vs Jason sevens")
    else:
        for k_ in ("CLUSTER_MAX", "OTHER_MAX", "STRANGERS"):
            put(k_, None, src, "a cluster set or a stranger is missing from the regenerated sets")

    # ---- the gate table's result cells (A, B, C; F below), so no measured literal sits in the draft
    if G["A"]["verdict"] and None not in (G["A"]["nyc_pass"], G["A"]["stl_pass"]) and P["STRANGERS"]["value"]:
        put("GATE_A", "**%s**: New York %d/10, St. Louis %d/10; strangers share %s" % (
            G["A"]["verdict"], G["A"]["nyc_pass"], G["A"]["stl_pass"], P["STRANGERS"]["value"]), G["A"]["source"])
    else:
        put("GATE_A", None, G["A"]["source"], "gate A did not report")
    if G["B"]["verdict"] and None not in (G["B"]["nyc_pass"], G["B"]["stl_pass"]):
        put("GATE_B", "**%s**: New York %d/10, St. Louis %d/10" % (G["B"]["verdict"], G["B"]["nyc_pass"],
                                                                   G["B"]["stl_pass"]), G["B"]["source"])
    else:
        put("GATE_B", None, G["B"]["source"], "gate B did not report")
    # chance: a random cut of k places from a pool of U overlaps the AIs' k struck places by k/U on average
    ch = [d["result"]["counts"]["struck_in_U"] / float(d["result"]["counts"]["U"]) for d in sets.values()
          if (d["result"].get("counts") or {}).get("U") and (d["result"]["counts"].get("struck_in_U") or 0) > 0]
    G["C"]["chance_median"] = median(ch)
    put("CAP_CHANCE", None if not ch else "%.2f" % median(ch), src + " (median over sets of struck_in_U / U)",
        "the overlap a random cut of the same size would have")
    if G["C"]["verdict"] and ch:
        put("GATE_C", "**%s**: median %s; a random cut of the same size: %s" % (
            G["C"]["verdict"], cap, P["CAP_CHANCE"]["value"]), G["C"]["source"] + " + " + src)
    else:
        put("GATE_C", None, G["C"]["source"], "gate C did not report")
    # gate C by city (the cap catches most of the list in St. Louis, less in New York), and how many of Qloo's
    # popularity-capped joint-signal top 7 (diag.cap7) are also in UNSAID's seven (diag.cap_shared)
    for c in ("stl", "nyc"):
        ov = [d["result"]["diag"]["cap_overlap"] for d in sets.values()
              if d["city"] == c and (d["result"].get("diag") or {}).get("cap_overlap") is not None]
        chc = [d["result"]["counts"]["struck_in_U"] / float(d["result"]["counts"]["U"]) for d in sets.values()
               if d["city"] == c and (d["result"].get("counts") or {}).get("U")
               and (d["result"]["counts"].get("struck_in_U") or 0) > 0]
        put("CAP_MED_" + c.upper(), "%.2f" % median(ov) if ov else None,
            src + " (diag.cap_overlap, median over the city's sets; the same per-set value k3_survivors prints)",
            "%d sets" % len(ov))
        put("CAP_CHANCE_" + c.upper(), "%.2f" % median(chc) if chc else None,
            src + " (median over the city's sets of struck_in_U / U)", "%d sets" % len(chc))
    cs = [d["result"]["diag"]["cap_shared"] for d in sets.values()
          if (d["result"].get("diag") or {}).get("cap_shared") is not None]
    put("CAP_SHARE_MED", num(median(cs)) if cs else None,
        src + " (diag.cap_shared: Qloo's popularity-capped top 7 by the joint signal, also in UNSAID's seven)",
        "%d sets, values %s" % (len(cs), sorted(cs)))

    # ---- Cedric (the shipped stl-cedric: precompute = run_query's product path)
    ced = sets.get("stl-cedric")
    if ced:
        r = ced["result"]
        c, p1 = r["counts"], r["picks"][0]
        csrc = "%s/stl_stl-cedric.json (precompute via regen_try.sh; ran %s)" % (fresh, ced.get("ran_at"))
        for k, v in (("WALL", c.get("wall")), ("ASKS", c.get("asks")), ("U", c.get("U")), ("STRUCK_U", c.get("struck_in_U")),
                     ("S", c.get("S")), ("R", c.get("R_mi")), ("FIT", p1.get("fit_rank")), ("ANY", p1.get("any_rank")),
                     ("A", p1.get("name"))):
            put(k, None if v is None else str(v), csrc)
        rq = os.path.join(LOGS, "query_stl-cedric.json")
        if os.path.exists(rq):
            q = json.load(open(rq))
            q = q.get("result", q)
            same = [p["id"] for p in q.get("picks", [])] == [p["id"] for p in r["picks"]]
            G["run_query_cedric"] = {"same_seven_as_precompute": same, "counts": q.get("counts")}
            if not same:
                print("WARN: run_query's Cedric seven differs from precompute's")
    # ---- k12 (U_MED, STRUCK_MED and the wall effect)
    kp = os.path.join(LOGS, "k12_wall_effect.json")
    if os.path.exists(kp):
        rows = json.load(open(kp))
        md = lambda k: median([x[k] for x in rows])  # noqa: E731
        G["k12"] = {"sets": len(rows), "on_median": md("on_named"), "off_median": md("off_named"),
                    "plain_median": md("plain_named"), "on_fresh_median": md("on_fresh"),
                    "off_fresh_median": md("off_fresh"), "plain_fresh_median": md("plain_fresh"),
                    "on_pooled": sum(x["on_named"] for x in rows), "off_pooled": sum(x["off_named"] for x in rows),
                    "plain_pooled": sum(x["plain_named"] for x in rows), "differ_pooled": sum(x["differ"] for x in rows),
                    "on_fresh_pooled": sum(x["on_fresh"] for x in rows), "off_fresh_pooled": sum(x["off_fresh"] for x in rows),
                    "plain_fresh_pooled": sum(x["plain_fresh"] for x in rows),
                    "U_median": md("U"), "struck_in_U_median": md("struck_in_U"),
                    "verdict": rx(log("03-k12.log"), r"^K12 wall effect: \d+ sets -> (\w+)"),
                    "source": "out/freeze/k12_wall_effect.json (engine/k12_wall_effect.py --frozen)"}
        put("U_MED", num(G["k12"]["U_median"]), G["k12"]["source"])
        put("STRUCK_MED", num(G["k12"]["struck_in_U_median"]), G["k12"]["source"])
        # the held-out chain by city (where crossing out does its part)
        for c in ("stl", "nyc"):
            cr = [x for x in rows if x.get("city") == c]
            for arm in ("PLAIN", "OFF", "ON"):
                put("K12_%s_FRESH_%s" % (arm, c.upper()), str(sum(x[arm.lower() + "_fresh"] for x in cr)) if cr else None,
                    G["k12"]["source"] + " (sum of %s_fresh over the city's sets)" % arm.lower(), "%d sets" % len(cr))
    else:
        put("U_MED", None, "engine/k12_wall_effect.py", "k12 did not run")
        put("STRUCK_MED", None, "engine/k12_wall_effect.py", "k12 did not run")
        for c in ("STL", "NYC"):
            for arm in ("PLAIN", "OFF", "ON"):
                put("K12_%s_FRESH_%s" % (arm, c), None, "engine/k12_wall_effect.py", "k12 did not run")

    # ---- gate E: the official score on the hashed 28 Oct cards, and the same check on today's cards (printed)
    for key, name in (("E", "03-gateE-frozen.log"), ("E_current", "03-gateE-current.log")):
        t = log(name)
        G[key] = {"verdict": rx(t, r"^E fresh asks: .* -> (\w+)"), "hits": rx(t, r"pooled: (\d+) of \d+ cards named", int),
                  "cards": rx(t, r"pooled: \d+ of (\d+) cards named", int),
                  "median": rx(t, r"median per set ([\d.]+) over", float), "source": "out/freeze/" + name}

    # ---- gate F (only when step 6 ran)
    t = log("06-gateF.log")
    G["F"] = {"verdict": rx(t, r"^F speed: .* -> (\w+)"), "p50": rx(t, r"⟦P50⟧ = ([\d.]+) s", float),
              "p90": rx(t, r"⟦P90⟧ = ([\d.]+) s", float),
              "first_name_p50": rx(t, r"first name on screen p50 ([\d.]+) s", float),
              "runs": rx(t, r"⟦P90⟧ = [\d.]+ s \((\d+) runs", int),
              "source": "out/freeze/06-gateF.log" if t else "not run (--skip-f)"}
    F = G["F"]
    g = lambda x: None if x is None else "%g" % x  # noqa: E731
    put("P50", g(F["p50"]), F["source"], "" if t else "gate F not run: delete the sentence")
    put("P90", g(F["p90"]), F["source"], "" if t else "gate F not run")
    put("FIRST_NAME", g(F["first_name_p50"]), F["source"], "" if t else "gate F not run")
    if F["verdict"] and None not in (F["p50"], F["p90"], F["first_name_p50"]):
        put("GATE_F", "**%s**: p50 %s s, p90 %s s, first name %s s (%s cold runs)" % (
            F["verdict"], g(F["p50"]), g(F["p90"]), g(F["first_name_p50"]), F["runs"] or "?"), F["source"])
    else:
        put("GATE_F", None, F["source"], "gate F not run at this freeze")

    # ---- street (the no-street ablation)
    st = street_stats(fresh, nostreet, REGEN_WALLS if os.path.isdir(REGEN_WALLS) else None) if nostreet else {
        "ok": False, "why": "no ablation dir"}
    if st.get("ok") and not st["unasked"]:
        put("STREET_NAMED", str(st["named"]), "the no-street ablation vs the full run (out/freeze/03-nostreet.log)")
        put("STREET_CARDS", str(st["cards"]), "the no-street ablation vs the full run (out/freeze/03-nostreet.log)")
    else:
        why = st.get("why") or ("%d of %d cards' neighbourhoods were never asked (street-1 asked the 28 Oct cards'): "
                                "'every card's neighbourhood' would be false; top up the street asks, or reword "
                                "(measured: %d of the %d asked-neighbourhood cards came up)" % (
                                    len(st["unasked"]), st["cards"], st["named_hood_asked"], st["cards_hood_asked"]))
        put("STREET_NAMED", None, "the no-street ablation", why)
        put("STREET_CARDS", None, "the no-street ablation", why)
    # the scoped version, true whether or not every neighbourhood was asked: of the no-street run's cards, how many
    # had their neighbourhood asked about, and how many of those the street answers named
    ok = bool(st.get("ok"))
    for k_, f_ in (("STREET_POOL", "cards"), ("STREET_ASKED", "cards_hood_asked"), ("STREET_NAMED_ASKED", "named_hood_asked")):
        put(k_, str(st[f_]) if ok else None, "the no-street ablation vs the full run (out/freeze/03-nostreet.log)",
            "" if ok else st.get("why", ""))

    # ---- walls: ASKS_TOTAL, DATES
    wdir = REGEN_WALLS if os.path.isdir(REGEN_WALLS) else WALLS
    ws = walls_stats(wdir)
    wsrc = "%s (the walls this regeneration read, sha256 %s)" % (os.path.relpath(wdir, ROOT), tree_hash(wdir)[:8])
    put("ASKS_TOTAL", "{:,}".format(ws["claude_chatgpt_dated_no_search"]),
        wsrc + ": dated Claude + ChatGPT answers, search-on lane excluded, both cities",
        "plus %d other dated answers (Gemini census) and the search-on lane" % ws["other_dated_no_search"])
    for c in ("stl", "nyc"):
        put("ASKS_" + c.upper(), "{:,}".format(ws["claude_chatgpt_dated_no_search_by_city"].get(c, 0)),
            wsrc + ": the same count, %s only" % c.upper())
    put("DATES", date_range(ws["first_asked_at"], ws["last_asked_at"]) if ws["first_asked_at"] else None,
        wsrc + ": first and last asked_at (ET)", "%s .. %s" % (ws["first_asked_at"], ws["last_asked_at"]))

    # ---- COVERAGE (saturation.py --metrics), GEM_GEM (census_stats.py --gems)
    sat = log("03-saturation.log")
    cov = rx(sat, r"^now\s+claude stl: .*coverage ([\d.]+)%", float)
    put("COVERAGE", None if cov is None else "%d%%" % round(cov),
        "harness/saturation.py --metrics (claude stl distinct / Chao2; out/freeze/03-saturation.log)",
        "" if cov is not None else "no metrics line")
    for key, pat, what in (("COVERAGE_NYC", r"^now\s+claude nyc: .*coverage ([\d.]+)%", "claude nyc distinct / Chao2"),
                           ("NEWRATE_STL", r"^now\s+claude stl: .*new-name rate last 40 ([\d.]+)%", "claude stl, last 40 asks"),
                           ("NEWRATE_NYC", r"^now\s+claude nyc: .*new-name rate last 40 ([\d.]+)%", "claude nyc, last 40 asks")):
        v = rx(sat, pat, float)
        put(key, None if v is None else "%d%%" % round(v), "harness/saturation.py --metrics (%s; out/freeze/03-saturation.log)"
            % what, "" if v is not None else "no metrics line")
    gems = log("03-census_gems.log")
    m = re.search(r"^\s+GEM_GEM = (\d+) of (\d+) asked \((\w+), ([^;]+);", gems, re.M)
    if m and int(m.group(2)) >= 16:
        put("GEM_GEM", "%s on %s of %s hidden-gem lists" % (m.group(4), m.group(1), m.group(2)),
            "harness/census_stats.py --gems (out/freeze/03-census_gems.log)")
    else:
        put("GEM_GEM", None, "harness/census_stats.py --gems",
            "only %s of 16 Gemini gem asks stored: delete the clause (legend rule)" % (m.group(2) if m else "?"))

    # ---- AGENT_QUOTE: usable only while The Spot is still Cedric's card at the quoted ranks, the quote is verbatim
    # in its recording, and (when the agent run was re-recorded after this regeneration) the new run still lists it.
    # Otherwise the note starts with DELETE: fill_devpost.py drops the line, and Roman decides.
    note, val = "", None
    spot = next((p for p in (ced or {}).get("result", {}).get("picks", []) if p["name"] == QUOTE_CARD), None) if ced else None
    src_path = QUOTE_SRC if os.path.exists(QUOTE_SRC) else AGENT_DEMO
    demo = json.load(open(src_path)) if os.path.exists(src_path) else {}
    tp, t_when = transcript_picks(TRANSCRIPT) if os.path.exists(TRANSCRIPT) else ([], None)
    rerecorded = bool(ced and t_when and t_when >= (ced.get("ran_at") or ""))
    if not spot:
        note = "DELETE: %s is no longer a Cedric card" % QUOTE_CARD
    elif (spot.get("fit_rank"), spot.get("any_rank"), ced["result"]["counts"].get("U")) != (QUOTE_FIT, QUOTE_ANY, QUOTE_U):
        note = "DELETE: %s is a card but now #%s for you, #%s of %s for anyone (the quote says 13, 78 of 78)" % (
            QUOTE_CARD, spot.get("fit_rank"), spot.get("any_rank"), ced["result"]["counts"].get("U"))
    elif QUOTE not in (demo.get("answer") or ""):
        note = "DELETE: the quote is not verbatim in %s" % src_path
    elif rerecorded and QUOTE_CARD not in tp:
        note = "DELETE: the re-recorded agent run (%s) no longer lists %s" % (t_when, QUOTE_CARD)
    else:
        val = ("> \"%s\"\n>\n> Claude (%s, Claude Code) with `unsaid_places` as its only tool, asked \"%s\", on %s "
               "(recorded %s)." % (QUOTE, demo.get("model", "?"), demo.get("question", "?"), QUOTE_CARD,
                                   (demo.get("recorded_at") or "?")[:10]))
        note = "" if rerecorded else "the agent run was not re-recorded after this regeneration (step 7)"
    put("AGENT_QUOTE", val, "%s (approved candidate, LOG 28 Oct) + Cedric's regenerated card + the live transcript" %
        os.path.relpath(src_path, os.path.dirname(ROOT)), note)

    # ---- k12 lines of the draft (no literals: the medians and pooled counts come from here)
    k = G.get("k12") or {}
    for key, kk in (("K12_ON", "on_median"), ("K12_OFF", "off_median"), ("K12_PLAIN", "plain_median"),
                    ("K12_ON_POOLED", "on_pooled"), ("K12_OFF_POOLED", "off_pooled"), ("K12_PLAIN_POOLED", "plain_pooled"),
                    ("K12_ON_FRESH", "on_fresh_median"), ("K12_OFF_FRESH", "off_fresh_median"),
                    ("K12_PLAIN_FRESH", "plain_fresh_median"),
                    # the held-out chain (pooled AI-named cards on the fresh questions only): plain -> score-only -> UNSAID
                    ("K12_PLAIN_FRESH_POOLED", "plain_fresh_pooled"), ("K12_OFF_FRESH_POOLED", "off_fresh_pooled"),
                    ("K12_ON_FRESH_POOLED", "on_fresh_pooled")):
        put(key, num(k.get(kk)), "out/freeze/k12_wall_effect.json (engine/k12_wall_effect.py --frozen)",
            "" if k else "k12 did not run")

    # ---- Qloo calls spent by this freeze run (every QLOO_NETWORK_CALLS line in out/freeze logs)
    qc = {}
    for p in sorted(glob.glob(os.path.join(LOGS, "*.log"))):
        ns_ = [int(x) for x in re.findall(r"^QLOO_NETWORK_CALLS=(\d+)", open(p).read(), re.M)]
        if ns_:
            qc[os.path.basename(p)] = sum(ns_)
    head = subprocess.run(["git", "-C", ROOT, "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    doc = {"generated_at": dt.datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z"), "git_head": head,
           "dry_run": bool(a.dry_run), "fresh_dir": fresh, "provenance": provenance(fresh), "placeholders": P, "gates": G,
           "cedric": cedric_of(os.path.join(fresh, "stl_stl-cedric.json")) if ced else None,
           "street": st, "walls": {k: v for k, v in ws.items() if k != "by_file"},
           "qloo_calls": {"by_log": qc, "total": sum(qc.values())}}
    json.dump(doc, open(NUMBERS, "w"), indent=1, ensure_ascii=False, default=str)
    print("numbers: %s" % NUMBERS)
    for pr in doc["provenance"]["problems"]:
        print("STALE: %s (fill_devpost.py will refuse)" % pr)
    for k, v in P.items():
        print("  %-12s %-28s %s" % (k, (v["value"] or "-")[:28].replace("\n", " "), v["note"][:110]))
    print("  gates: " + " · ".join("%s %s" % (k, v.get("verdict")) for k, v in G.items() if isinstance(v, dict) and "verdict" in v))
    print("  Qloo network calls in this run's logs: %d %s" % (doc["qloo_calls"]["total"], qc))


# --------------------------------------------------------------------------------------------------------- agentcheck
def transcript_picks(path):
    picks = []
    for line in open(path):
        r = json.loads(line)
        if r.get("dir") == "<<" and isinstance(r.get("msg", {}).get("result"), dict):
            sc = r["msg"]["result"].get("structuredContent") or {}
            if sc.get("picks"):
                return [p.get("name") for p in sc["picks"]], sc.get("as_of")
    return picks, None


def agentcheck(a):
    ced = os.path.join(a.fresh, "stl_stl-cedric.json")
    seven = [p["name"] for p in json.load(open(ced))["result"]["picks"]]
    if not os.path.exists(TRANSCRIPT):
        print("WARN agent shot: no %s (the video drops the agent scene)" % TRANSCRIPT)
        return
    tp, when = transcript_picks(TRANSCRIPT)
    shown = tp[:5]   # build_video_data.py shows the first 5 result lines
    gone = [n for n in shown if n not in seven]
    if tp == seven:
        print("agent shot: OK, the transcript's 7 (recorded %s) are Cedric's current 7, same order" % when)
    elif not gone:
        print("agent shot: OK for the 5 shown (recorded %s); the full 7 differ: transcript %s vs now %s" % (when, tp, seven))
    else:
        print("WARN agent shot: %d of the 5 names shown are no longer Cedric cards: %s (recorded %s). Re-record "
              "agent/demo/live_transcript.jsonl, then re-render the video" % (len(gone), gone, when))


# ------------------------------------------------------------------------------------------------------------- report
def report(a):
    N = json.load(open(NUMBERS))
    fill = json.load(open(os.path.join(LOGS, "fill.json"))) if os.path.exists(os.path.join(LOGS, "fill.json")) else {}
    L = []
    w = L.append
    w("UNSAID freeze report · %s · git %s · %s" % (dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z"),
                                                    N.get("git_head"), "DRY RUN" if N.get("dry_run") else "FREEZE"))
    w("")
    w("Steps:")
    for p in sorted(glob.glob(os.path.join(LOGS, "done", "*"))):
        w("  %s  %s" % (os.path.basename(p), open(p).read().strip()))
    w("")
    G = N["gates"]
    w("Gates:")
    w("  precompute  %s  %s" % (G["precompute"].get("verdict"), G["precompute"].get("line") or ""))
    w("  A taste     %s  NYC %s/10, STL %s/10; strangers share %s" % (G["A"]["verdict"], G["A"]["nyc_pass"],
                                                                     G["A"]["stl_pass"], G["A"]["strangers"]))
    w("  B survivors %s  NYC %s/10, STL %s/10" % (G["B"]["verdict"], G["B"]["nyc_pass"], G["B"]["stl_pass"]))
    w("  C cap       %s  overlap median %s over %s sets (bar 0.80)" % (G["C"]["verdict"], G["C"]["cap_overlap_median"],
                                                                     G["C"]["sets"]))
    w("  E fresh     %s  %s of %s cards named, median %s (official: hashed 28 Oct cards)" % (
        G["E"]["verdict"], G["E"]["hits"], G["E"]["cards"], G["E"]["median"]))
    w("  E today     %s  %s of %s, median %s (printed: today's cards)" % (
        G["E_current"]["verdict"], G["E_current"]["hits"], G["E_current"]["cards"], G["E_current"]["median"]))
    k = G.get("k12") or {}
    w("  k12         %s  medians on/off/plain %s/%s/%s; pooled %s/%s/%s of 140; fresh-only %s/%s/%s" % (
        k.get("verdict"), num(k.get("on_median")), num(k.get("off_median")), num(k.get("plain_median")),
        k.get("on_pooled"), k.get("off_pooled"), k.get("plain_pooled"), num(k.get("on_fresh_median")),
        num(k.get("off_fresh_median")), num(k.get("plain_fresh_median"))))
    F = G["F"]
    w("  F speed     %s  %s" % (F.get("verdict") or "NOT RUN", "p50 %s s, p90 %s s, first name %s s" % (
        F["p50"], F["p90"], F["first_name_p50"]) if F.get("verdict") else F["source"]))
    w("")
    w("numbers.json (%s):" % NUMBERS)
    for kk, v in N["placeholders"].items():
        w("  ⟦%s⟧ = %s%s" % (kk, (v["value"] or "UNFILLED").replace("\n", " ")[:100],
                            ("   (%s)" % v["note"][:160]) if v.get("note") else ""))
    w("  Qloo network calls this run: %s %s" % (N["qloo_calls"]["total"], N["qloo_calls"]["by_log"]))
    st = N.get("street") or {}
    if st.get("ok"):
        w("  street: %d of %d no-street cards came up in street answers (%d of %d asked-neighbourhood cards); "
          "%d cards' neighbourhoods never asked" % (st["named"], st["cards"], st["named_hood_asked"],
                                                     st["cards_hood_asked"], len(st["unasked"])))
    w("")
    w("Unfilled in %s:" % fill.get("out", "devpost.final.md"))
    for kk, v in sorted((fill.get("unfilled") or {}).items()):
        w("  ⟦%s⟧ x%d: %s" % (kk, v["count"], v["why"]))
    for d in fill.get("drift") or []:
        if d["status"] == "DRIFT":
            w("  DRIFT %s: the text says %s, the freeze measured %s" % (d["claim"], d["text"], d["freeze"]))
    w("")
    before = os.path.join(LOGS, "cedric.before.json")
    now = N.get("cedric") or {}
    w("Cedric's seven (ran %s):" % now.get("ran_at"))
    if os.path.exists(before):
        b = json.load(open(before))
        bi = {p["id"]: p for p in b["seven"]}
        ni = {p["id"] for p in now.get("seven", [])}
        for i, p in enumerate(now.get("seven", []), 1):
            o = bi.get(p["id"])
            w("  %d. %-32s #%s for you · #%s for anyone   %s" % (
                i, p["name"], p["fit_rank"], p["any_rank"],
                "new" if not o else ("same" if (o["fit_rank"], o["any_rank"]) == (p["fit_rank"], p["any_rank"])
                                     else "was #%s · #%s" % (o["fit_rank"], o["any_rank"]))))
        out = [p["name"] for p in b["seven"] if p["id"] not in ni]
        w("  out vs the previous run (%s): %s" % (b.get("ran_at"), "; ".join(out) or "none"))
    else:
        w("  (no previous snapshot)")
    q = N["placeholders"].get("AGENT_QUOTE", {})
    if not q.get("value"):
        w("!" * 100)
        w("!!! ⟦AGENT_QUOTE⟧ NOT USABLE: %s. The quote line is DELETED from devpost.final.md; Roman decides." % q.get("note"))
        w("!" * 100)
    w("⟦AGENT_QUOTE⟧ (The Spot Sports Bar): %s" % ("still a Cedric card at #13 / #78 of 78: usable" if q.get("value")
                                                   else "NOT usable: " + q.get("note", "")))
    ac = log("07-agentcheck.log").strip()
    w("Video agent shot: %s" % (ac.splitlines()[-1] if ac else "not checked (step 7 not run)"))
    for name, label in (("05-render.log", "Render"), ("08-site.log", "Site deploy")):
        t = log(name).strip().splitlines()
        w("%s: %s" % (label, t[-1] if t else "not run"))
    txt = "\n".join(L) + "\n"
    open(os.path.join(LOGS, "report.txt"), "w").write(txt)
    print(txt)


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    w = sp.add_parser("walls-keep")
    w.add_argument("backup")
    s = sp.add_parser("snapshot-cedric")
    s.add_argument("src")
    s.add_argument("out")
    n = sp.add_parser("numbers")
    n.add_argument("--fresh", required=True)
    n.add_argument("--nostreet")
    n.add_argument("--dry-run", action="store_true")
    sp.add_parser("prereg")
    t = sp.add_parser("stamp")
    t.add_argument("--fresh", required=True)
    t.add_argument("--wt", required=True)
    u = sp.add_parser("unasked")
    u.add_argument("--fresh", required=True)
    u.add_argument("--write")
    c = sp.add_parser("agentcheck")
    c.add_argument("--fresh", required=True)
    sp.add_parser("report")
    a = ap.parse_args()
    os.makedirs(LOGS, exist_ok=True)
    if a.cmd == "walls-keep":
        walls_keep(a.backup)
    elif a.cmd == "snapshot-cedric":
        snapshot_cedric(a.src, a.out)
    elif a.cmd == "numbers":
        numbers(a)
    elif a.cmd == "prereg":
        return prereg(a)
    elif a.cmd == "stamp":
        stamp(a)
    elif a.cmd == "unasked":
        unasked(a)
    elif a.cmd == "agentcheck":
        agentcheck(a)
    else:
        report(a)


if __name__ == "__main__":
    sys.exit(main())
