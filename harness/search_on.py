"""The SEARCH-ON lane (28 Oct): "real ChatGPT and Claude search the web; does the wall hold?"

Per city: the 16 census hidden-gem phrasings (verbatim from prompts.py) + 8 plain ones (the 4 city-wall phrasings w00-w03
and census GENERIC 1, 2, 3, 5), prompt v2 JSON suffix, asked to
  claude  claude -p ... --tools "WebSearch,WebFetch" --allowedTools WebSearch WebFetch (otherwise the census line)
  codex   codex exec ... -c web_search="live" --disable apps --disable shell_tool (otherwise the walls line)
Stored apart: runs/wall-search-on.jsonl -> data/walls/search-on.json (meta.search = true, every answer search "on").
Never read by the no-search census (census_stats.py, census.json).

  python3 -I search_on.py --go        # ask (resumable), build data/walls/search-on.json
  python3 -I search_on.py --report    # share already on the no-search wall, frozen cards named, gem tops
"""
import argparse, glob, json, os, sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lanes as L
import phrasings as P
import prompts

WALL = "search-on"
OUT = os.path.join(L.RUNS, "wall-%s.jsonl" % WALL)
FROZEN = os.path.expanduser("~/Desktop/qloo/private/frozen20")
PLAIN_GENERIC = [1, 2, 3, 5]  # census GENERIC indices that don't repeat w00-w03
GEMS = {"stl": ["Gioia's Deli", "Mai Lee"], "nyc": ["Sripraphai", "Rolo's"]}
# Claude, given the tools, searched in 1 of 16 first asks (the JSON-only reply discourages it). The labelled "nudged"
# variant adds one line to the system prompt; everything else is identical.
NUDGE = L.SYS_CLAUDE + " You can search the web; check current information before recommending places."


def build():
    out = []
    for ck in P.CITY:
        phr = [(pid, ph) for pid, ph in P.city_wall(ck)]  # w00-w03 + h00-h15
        phr += [("g%02d" % i, prompts.GENERIC[i].format(**prompts.CITIES[ck])) for i in PLAIN_GENERIC]
        for pid, ph in phr:
            out.append({"id": "w%s:city:%s:-:%s" % (WALL, ck, pid), "kind": "city", "city": ck, "set": None,
                        "phrasing_id": pid, "phrasing": ph, "prompt": ph + P.SUFFIX_V2, "prompt_v": P.PROMPT_V,
                        "family": "hidden" if pid.startswith("h") else "plain", "wall": WALL, "search_lane": True})
    return out


def core_key():
    import census_stats as C  # its main() only runs under __main__
    return lambda n: C.core(C.strip_dish(n)[0])


def no_search_keys(key):
    """Every name any no-search answer gave, per city: censuses (all providers/models) + every runs/wall-*.jsonl but
    this lane and smoke."""
    keys = {ck: set() for ck in P.CITY}
    files = [os.path.join(HERE, f) for f in ("claude_answers.jsonl", "codex_answers.jsonl")]
    files += glob.glob(os.path.join(HERE, "gemini*_answers.jsonl"))
    files += [f for f in glob.glob(os.path.join(L.RUNS, "wall-*.jsonl")) if "search-on" not in f and "smoke" not in f]
    for f in files:
        for r in L.load(f).values():
            if r.get("city") in keys and L.is_done(r) and r.get("search", "off") == "off":
                keys[r["city"]] |= {key(x["name"]) for x in r.get("places") or []}
    return keys


def report():
    key = core_key()
    keys = no_search_keys(key)
    recs = [r for r in L.load(OUT).values() if L.is_done(r)]
    vname = lambda r: r["runner"] + ("-nudged" if r.get("variant") == "nudged" else "")  # noqa: E731
    print("search-on answers stored: %s" % dict(Counter((vname(r), r["city"]) for r in recs)))
    print("answers that actually searched: %s" % dict(Counter(vname(r) for r in recs if (r.get("tool_calls") or 0) > 0 or (r.get("search_calls") or 0) > 0)))
    for lane in ("claude", "claude-nudged", "codex"):
        for ck in P.CITY:
            rs = [r for r in recs if vname(r) == lane and r["city"] == ck]
            if not rs:
                continue
            names = {key(x["name"]) for r in rs for x in r.get("places") or []}
            ment = [key(x["name"]) for r in rs for x in r.get("places") or []]
            on = [n for n in names if n in keys[ck]]
            mon = sum(1 for n in ment if n in keys[ck])
            hid = [r for r in rs if r["family"] == "hidden"]
            top = Counter(key(x["name"]) for r in hid for x in r.get("places") or []).most_common(4)
            disp = {}
            for r in hid:
                for x in r.get("places") or []:
                    disp.setdefault(key(x["name"]), x["name"])
            gems = ", ".join("%s %d/%d" % (g, sum(1 for r in hid if any(key(x["name"]) == key(g) for x in r.get("places") or [])), len(hid))
                             for g in GEMS[ck])
            print("%-6s %s: %d asks, %d distinct names, %d (%.0f%%) already on the no-search wall; mentions %d/%d (%.0f%%)"
                  % (lane, ck, len(rs), len(names), len(on), 100.0 * len(on) / max(1, len(names)), mon, len(ment),
                     100.0 * mon / max(1, len(ment))))
            print("        hidden-gem tops: %s | census gems: %s" % (", ".join("%s %d" % (disp[k], c) for k, c in top), gems))
    eng = os.path.join(os.path.dirname(HERE), "engine")
    sys.path.insert(0, eng)
    from unsaid import engine as E
    tot = named = 0
    per = []
    for f in sorted(glob.glob(os.path.join(FROZEN, "*.json"))):
        if f.endswith("index.json"):
            continue
        d = json.load(open(f))
        ans = [{"raw": r.get("raw") or "", "names": r.get("places") or []} for r in recs if r["city"] == d.get("city")]
        rix = E.reverse_index(ans)
        picks = (d.get("result") or {}).get("picks", [])
        n = sum(1 for c in picks if E.reverse_hit(c.get("name"), rix) is not None)
        tot += len(picks)
        named += n
        per.append("%s %d" % (d.get("id"), n))
    print("frozen cards named by the search-on answers: %d of %d (%s)" % (named, tot, ", ".join(p for p in per if not p.endswith(" 0")) or "none"))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--go", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--nudge", action="store_true", help="the Claude 'nudged' variant only")
    a = ap.parse_args()
    if a.report:
        return report()
    if a.nudge:
        lane = L.lanes_from("claude")[0]
        asks = [dict(x, id=x["id"] + ":claude-nudged", variant="nudged") for x in build()]
        return L.run(lane, asks, OUT, None, a.go, {"search": True, "system": NUDGE})
    asks = build()
    lanes = L.lanes_from("claude,codex")
    L.run_lanes(lanes, lambda l: [dict(x, id=x["id"] + ":" + l.name) for x in asks], lambda l: OUT, None, a.go,
                {"search": True})


if __name__ == "__main__":
    main()
