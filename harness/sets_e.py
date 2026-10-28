"""E-style taste asks for every frozen set (orchestrator, 28 Oct): the set's own three loves plus the city, two unhinted
phrasings, Claude and ChatGPT, sent verbatim (no JSON suffix, no codex schema) like the fresh asks. Stored as dated wall
"e1" (runs/wall-e1.jsonl, kind "taste", one entry per set), so `walls_cli.py build --walls e1` serves them; the engine's
reverse check reads their raw text.

  python3 -I sets_e.py                 # dry run
  python3 -I sets_e.py --go            # ask (resumable), then build data/walls/e1.json
  python3 -I sets_e.py --count         # how many of each set's 7 cards the answers name (counts only, nothing else)

--count reads card names from ~/Desktop/qloo/private/frozen20 in memory and writes only counts (runs/sets_e_counts.json).
Naming = the engine's reverse check (engine/unsaid/engine.py reverse_hit: every distinctive token of the card's name in
one answer's raw text), the same rule k5 uses.
"""
import argparse, glob, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lanes as L
import phrasings as P

WALL = "e1"
PHRASINGS = [
    ("e1", "I love {L1}, {L2} and {L3}. Where should I eat or drink in {city}?"),   # the orchestrator's sentence
    ("e2", "Where should I go out to eat or drink in {city}? I'm into {L1}, {L2} and {L3}."),
]
FROZEN = os.path.expanduser("~/Desktop/qloo/private/frozen20")
OUT = os.path.join(L.RUNS, "wall-%s.jsonl" % WALL)


def build(sets):
    out = []
    for ck in P.CITY:
        for sid, loves in sets.get(ck, []):
            Ls = {"L%d" % (i + 1): l for i, l in enumerate(loves)}
            for pid, t in PHRASINGS:
                ph = t.format(city=P.CITY[ck], **Ls)
                out.append({"id": "w%s:taste:%s:%s:%s" % (WALL, ck, sid, pid), "kind": "taste", "city": ck, "set": sid,
                            "loves": loves, "phrasing_id": pid, "phrasing": ph, "prompt": ph, "prompt_v": "e-v1-verbatim",
                            "verbatim": True, "suffix": False, "wall": WALL})
    return out


def count():
    eng = os.path.join(os.path.dirname(HERE), "engine")
    sys.path.insert(0, eng)
    from unsaid import engine as E
    recs = [r for r in L.load(OUT).values() if L.is_done(r)]
    rows = []
    for f in sorted(glob.glob(os.path.join(FROZEN, "*.json"))):
        if f.endswith("index.json"):
            continue
        d = json.load(open(f))
        sid, res = d.get("id"), d.get("result") or {}
        ans = [{"raw": r.get("raw") or ""} for r in recs if r["set"] == sid]
        if not ans:
            continue
        rix = E.reverse_index(ans)
        by_lane = {}
        for lane in ("claude", "codex"):
            la = [{"raw": r.get("raw") or ""} for r in recs if r["set"] == sid and r["runner"] == lane]
            lx = E.reverse_index(la) if la else None
            by_lane[lane] = sum(1 for c in res.get("picks", []) if lx is not None and E.reverse_hit(c.get("name"), lx) is not None)
        picks = sum(1 for c in res.get("picks", []) if E.reverse_hit(c.get("name"), rix) is not None)
        reserves = sum(1 for c in res.get("reserves", []) if E.reverse_hit(c.get("name"), rix) is not None)
        rows.append({"set": sid, "city": d.get("city"), "answers": len(ans), "picks_named": picks,
                     "picks": len(res.get("picks", [])), "reserves_named": reserves, "reserves": len(res.get("reserves", [])),
                     "picks_named_by": by_lane})
    out = {"rule": "engine reverse_hit on raw text (k5's rule)", "wall": WALL, "phrasings": [p for _, p in PHRASINGS],
           "sets": rows, "total_picks_named": sum(r["picks_named"] for r in rows), "total_picks": sum(r["picks"] for r in rows)}
    json.dump(out, open(os.path.join(L.RUNS, "sets_e_counts.json"), "w"), indent=1)
    for r in rows:
        print("%-22s %d of %d cards named (claude %d, chatgpt %d); reserves %d of %d; %d answers" % (
            r["set"], r["picks_named"], r["picks"], r["picks_named_by"]["claude"], r["picks_named_by"]["codex"],
            r["reserves_named"], r["reserves"], r["answers"]))
    print("total: %d of %d cards named" % (out["total_picks_named"], out["total_picks"]))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--go", action="store_true")
    ap.add_argument("--count", action="store_true")
    a = ap.parse_args()
    if a.count:
        return count()
    sets = P.load_sets()
    asks = build(sets)
    lanes = L.lanes_from("claude,codex")
    L.run_lanes(lanes, lambda l: [dict(x, id=x["id"] + ":" + l.name) for x in asks], lambda l: OUT, None, a.go,
                {"schema": None, "json_mode": False})


if __name__ == "__main__":
    main()
