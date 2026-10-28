"""SATURATION (orchestrator, 28 Oct): push each AI's census coverage with a varied, deterministic phrase grid,
neighbourhood (neighbourhoods.json, from hoods.py) x occasion x cuisine x template, prompt = phrase + the census v1
suffix (so it extends the census like for like). No web search (the walls lines).

Batches of 40 per city per AI. After each batch, per (AI, city), over census + saturation asks in order:
  rate     = new names in the last 40 asks / mentions in the last 40 asks (the census "flat" rule, L2 keys)
  coverage = distinct names (L2) / Chao2 (asks as units), census_stats.chao2
A pair stops when rate < 5% or after 240 extra asks. Results: runs/saturation.json; answers: runs/wall-sat.jsonl
-> data/walls/sat.json.

  python3 -I saturation.py --metrics       # coverage now (before), no asks
  python3 -I saturation.py --go            # run the batches
  python3 -I saturation.py --cards         # frozen cards named by the saturation answers (counts only)
"""
import argparse, glob, itertools, json, os, random, sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lanes as L
import phrasings as P
import prompts
import census_stats as C

WALL = "sat"
OUT = os.path.join(L.RUNS, "wall-%s.jsonl" % WALL)
STATE = os.path.join(L.RUNS, "saturation.json")
BATCH, MAX_EXTRA, FLAT = 40, 240, 0.05
OCCASIONS = ["a date night", "late-night food", "brunch", "cheap eats", "dinner with a big group", "eating out solo"]
CUISINES = ["Italian", "Mexican", "barbecue", "Vietnamese", "Chinese", "pizza", "seafood", "vegetarian food",
            "cocktails", "a good beer bar"]
TEMPLATES = ["where should I go for {occ} in {hood}, {city}? thinking {cui}",
             "{cui} in {hood}, {city}, for {occ}: where?",
             "best spot in or near {hood} ({city}) for {occ}, ideally {cui}"]
CENSUS = {"claude": "claude_answers.jsonl", "codex": "codex_answers.jsonl"}
FROZEN = os.path.expanduser("~/Desktop/qloo/private/frozen20")


def grid(ck):
    hoods = json.load(open(os.path.join(HERE, "neighbourhoods.json")))["cities"][ck]
    combos = list(itertools.product(hoods, OCCASIONS, CUISINES))
    random.Random(20261028).shuffle(combos)
    out = []
    for i, (h, o, c) in enumerate(combos[:MAX_EXTRA]):
        ph = TEMPLATES[i % len(TEMPLATES)].format(occ=o, hood=h, city=P.CITY[ck], cui=c)
        out.append({"id": "w%s:city:%s:-:sat%03d" % (WALL, ck, i), "kind": "city", "city": ck, "set": None,
                    "phrasing_id": "sat%03d" % i, "phrasing": ph, "prompt": ph + prompts.SUFFIX, "prompt_v": "sat-v1",
                    "hood": h, "occasion": o, "cuisine": c, "wall": WALL, "order": i})
    return out


def key(n):
    return C.core(C.strip_dish(n)[0])


def series(lane, ck):
    """Per-ask name sets in ask order: the census (its frozen order), then saturation asks by their grid order."""
    cen = sorted((r for r in L.load(os.path.join(HERE, CENSUS[lane])).values() if r["city"] == ck and r.get("places")),
                 key=lambda r: r["order"])
    sat = sorted((r for r in L.load(OUT).values() if r["city"] == ck and r.get("runner") == lane and L.is_done(r)),
                 key=lambda r: r["order"])
    return [[key(x["name"]) for x in r.get("places") or []] for r in cen + sat], len(cen), len(sat)


def metrics(lane, ck):
    asks, ncen, nsat = series(lane, ck)
    sets = [set(a) for a in asks]
    inc = Counter(k for s in sets for k in s)
    S, m = len(inc), len(sets)
    chao = C.chao2(list(inc.values()), m) if m else 0
    seen, first = set(), []
    for s in sets:
        first.append(len(s - seen))
        seen |= s
    last = slice(max(0, m - BATCH), m)
    new, ment = sum(first[last]), sum(len(a) for a in asks[last])
    return {"asks": m, "census": ncen, "extra": nsat, "distinct": S, "chao2": round(chao, 1),
            "coverage": round(S / chao, 4) if chao else None, "rate_last40": round(new / ment, 4) if ment else None}


def show(tag):
    out = {}
    for lane in CENSUS:
        for ck in P.CITY:
            mt = metrics(lane, ck)
            out["%s/%s" % (lane, ck)] = mt
            print("%s %-6s %s: %d asks (%d extra), %d distinct, Chao2 %.0f, coverage %.1f%%, new-name rate last 40 %.1f%%" % (
                tag, lane, ck, mt["asks"], mt["extra"], mt["distinct"], mt["chao2"], 100 * (mt["coverage"] or 0),
                100 * (mt["rate_last40"] or 0)), flush=True)
    return out


def cards():
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), "engine"))
    from unsaid import engine as E
    recs = [r for r in L.load(OUT).values() if L.is_done(r)]
    tot = named = 0
    for f in sorted(glob.glob(os.path.join(FROZEN, "*.json"))):
        if f.endswith("index.json"):
            continue
        d = json.load(open(f))
        rix = E.reverse_index([{"raw": r.get("raw") or "", "names": r.get("places") or []} for r in recs if r["city"] == d.get("city")])
        picks = (d.get("result") or {}).get("picks", [])
        tot += len(picks)
        named += sum(1 for c in picks if E.reverse_hit(c.get("name"), rix) is not None)
    print("frozen cards named by the saturation answers: %d of %d" % (named, tot))
    return named, tot


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--go", action="store_true")
    ap.add_argument("--metrics", action="store_true")
    ap.add_argument("--cards", action="store_true")
    a = ap.parse_args()
    if a.cards:
        return cards()
    state = json.load(open(STATE)) if os.path.exists(STATE) else {"batches": []}
    if "before" not in state:
        state["before"] = show("before")
    if a.metrics or not a.go:
        json.dump(state, open(STATE, "w"), indent=1)
        return show("now   ") if a.metrics else None
    lanes = {l.name: l for l in L.lanes_from("claude,codex")}
    grids = {ck: grid(ck) for ck in P.CITY}
    while True:
        active = {}
        for lane in lanes:
            for ck in P.CITY:
                mt = metrics(lane, ck)
                if mt["extra"] >= MAX_EXTRA or (mt["extra"] >= BATCH and mt["rate_last40"] is not None and mt["rate_last40"] < FLAT):
                    continue
                done = L.done_ids(OUT)
                nxt = [dict(x, id=x["id"] + ":" + lane) for x in grids[ck] if x["id"] + ":" + lane not in done][:BATCH]
                if nxt:
                    active.setdefault(lane, []).extend(nxt)
        if not active or L.disk_low():
            print("[sat] stop: %s" % (L.disk_low() or "every (AI, city) is flat (< 5%) or at 240 extra"), flush=True)
            break
        print("[sat] batch %d: %s" % (len(state["batches"]) + 1, {k: len(v) for k, v in active.items()}), flush=True)
        before = len(L.done_ids(OUT))
        L.run_lanes([lanes[k] for k in active], lambda l: active[l.name], lambda l: OUT, None, True)
        if len(L.done_ids(OUT)) == before:
            print("[sat] stop: a whole batch stored nothing (plan limit or outage); run again later to resume", flush=True)
            break
        state["batches"].append({"at": L.now(), "metrics": show("after batch %d" % (len(state["batches"]) + 1))})
        json.dump(state, open(STATE, "w"), indent=1)
    state["after"] = show("after ")
    json.dump(state, open(STATE, "w"), indent=1)


if __name__ == "__main__":
    main()
