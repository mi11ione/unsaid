"""The held-out fresh-ask runner (UNSAID.md §4, K5'). Waits for data/fresh_asks.json, which agent D collects and Roman
freezes into the public hash. Writes runs/fresh.jsonl; k5_fresh.py scores it (matcher + reverse check on raw text).

Per city: its 20 public questions, verbatim, asked once per lane and shared by every set in that city. Per set: 4 of
them with one appended sentence, "I love {L1}, {L2} and {L3}." So 24 questions x 3 lanes per set; about 360 asks for
the 20 sets. None is ever in a wall: every question, plain and with loves, is hashed (case and whitespace folded,
suffix stripped) and checked against every wall, taste, street and census phrasing; one clash and nothing runs.

  python3 -I fresh_asks.py                    # check the file and the hashes, print what would be asked
  python3 -I fresh_asks.py --lane all --go    # ask (resumable)

Expected file (UNSAID_FRESH overrides the path):
  {"frozen_at": "...", "questions": [{"id": "stl-q01", "city": "stl", "text": "<verbatim>", "url": "...", "posted": "2025-03-02"}, ...],
   "with_loves": {"stl": ["stl-q03", ...4 ids], "nyc": [...]}}        # optional; default: each city's first 4 in file order
Questions go out VERBATIM (orchestrator decision 27 Oct): no JSON suffix, and codex runs without --output-schema,
Gemini without JSON mode. The raw text is stored; k5 measures naming on it (matcher + reverse check). Each record
stores verbatim/suffix. --suffix opts back into the v2 JSON suffix and the schemas (not the pre-registered default).
"""
import argparse, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lanes as L
import phrasings as P

FRESH = os.environ.get("UNSAID_FRESH") or os.path.join(os.path.dirname(HERE), "data", "fresh_asks.json")
OUT = os.path.join(L.RUNS, "fresh.jsonl")


def love_line(loves):
    return " I love %s, %s and %s." % tuple(loves[:3])


def build(d, sets, suffix=False):
    qs = d.get("questions", d) if isinstance(d, dict) else d
    wl = (d.get("with_loves") if isinstance(d, dict) else None) or {}
    out = []
    for ck in P.CITY:
        cq = [q for q in qs if q["city"] == ck]
        if not cq:
            continue
        four = [q for q in cq if q["id"] in set(wl.get(ck, []))] or cq[:4]
        for q in cq:
            out.append({"id": "fresh:%s:-:%s" % (ck, q["id"]), "kind": "fresh", "city": ck, "set": None,
                        "phrasing_id": q["id"], "phrasing": q["text"], "url": q.get("url"), "with_loves": False})
        for sid, loves in sets.get(ck, []):
            for q in four[:4]:
                out.append({"id": "fresh:%s:%s:%s+loves" % (ck, sid, q["id"]), "kind": "fresh", "city": ck, "set": sid,
                            "loves": loves, "phrasing_id": q["id"] + "+loves", "phrasing": q["text"] + love_line(loves),
                            "url": q.get("url"), "with_loves": True})
    for a in out:
        a.update(prompt=a["phrasing"] + (P.SUFFIX_V2 if suffix else ""), prompt_v="fresh-" + ("v2suffix" if suffix else "verbatim"),
                 suffix=suffix, verbatim=not suffix)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lane", default="all")
    ap.add_argument("--sets-file", default=None)
    ap.add_argument("--suffix", action="store_true", help="append the v2 JSON suffix (default: verbatim)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--go", action="store_true")
    a = ap.parse_args()
    if not os.path.exists(FRESH):
        sys.exit("needs %s (agent D collects it, Roman freezes it into the public hash). Nothing asked." % FRESH)
    d = json.load(open(FRESH))
    sets = P.load_sets(a.sets_file)
    hoods = json.load(open(os.path.join(HERE, "neighbourhoods.json")))["cities"] if os.path.exists(os.path.join(HERE, "neighbourhoods.json")) else {}
    base = build(d, sets, a.suffix)
    wall = P.all_wall_hashes(sets, hoods)
    clash = [x["id"] for x in base if P.qhash(x["phrasing"]) in wall]
    if clash:
        sys.exit("refusing: %d fresh questions hash-match a wall/census phrasing: %s" % (len(clash), clash[:5]))
    print("hash check: %d fresh questions, 0 clash with %d wall/census phrasings" % (len(base), len(wall)))
    lanes = L.lanes_from(a.lane)
    opts = {} if a.suffix else {"schema": None, "json_mode": False}  # verbatim: no codex schema, no Gemini JSON mode
    L.run_lanes(lanes, lambda l: [dict(x, id=x["id"] + ":" + l.name) for x in base], lambda l: OUT, a.limit, a.go, opts)


if __name__ == "__main__":
    main()
