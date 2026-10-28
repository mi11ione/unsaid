"""Gate D · grounding meter (UNSAID.md §4; protocol in unsaid-v3 §3.5). 0 new Qloo calls: it only reads stored runs.
Each assistant is told "Where should someone who loves L1, L2 and L3 eat and drink tonight in {city}? ... but nothing
every AI would tell me. Name 12 places." twice: alone, and with `qloo_places(loves, city)` as its only tool (the top 50
of the taste pool, nothing subtracted). Measure: picks the matcher finds on the city's GENERIC wall (phrasings 1-4,
three providers; never the assistant's own taste answers).
Decision rule: FEATURED only if the median with Qloo is <= 6 of 12 AND it is >= 4 below alone in >= 7 of 10 sets.
Printed in Shown and the README whatever it says. Fills ⟦M_ALONE⟧ ⟦M_QLOO⟧.

  --meter harness/runs/meter.jsonl (one record per line: set, city, provider, arm "alone"|"with", places [{name}],
          status) or a JSON {"runs": [...]} with "picks"; arm "qloo" == "with"; failed records are skipped
  --walls data/walls (dir or file): the generic wall = set "city", kind != street, phrasings 1-4 by --generic-ids
          or by their text. Graded by the OTHER AIs: a run's own provider is left out of its wall (--include-own)
In --fake mode with no --meter, fixture names stand in, tagged [FAKE]."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from unsaid import cli, matcher as M, seeds as SD, walls as W  # noqa: E402

GENERIC_TEXT = ("best places to eat and drink", "where do locals go", "not touristy", "must try restaurants")
ap = cli.parser(__doc__)
ap.add_argument("--meter")
ap.add_argument("--generic-ids", help="comma-separated phrasing_ids of the 4 generic phrasings")
ap.add_argument("--include-own", action="store_true", help="also count the run's own provider's wall answers")
ap.add_argument("--generic-only", action="store_true",
                help="old unsaid-v3 grading (generic phrasings 1-4 only). Default is the frozen data/meter.protocol.md: "
                     "the other assistants' city-wall and census answers for that city, street asks excluded")
args = ap.parse_args()
T = cli.tag(args)
print("== k10_meter  %s  (0 Qloo calls: no client is created)" % ("[FAKE]" if args.fake else "[LIVE] stored runs"))


def generic_wall(city):
    """-> [(provider, name)] from the city's generic phrasings 1-4."""
    gids = set((args.generic_ids or "").split(",")) - {""}
    if args.walls:
        out = []
        for w in W.load_file(args.walls).get("walls", []):
            sets_ok = ("city", "_city", "*", None, "") + (() if args.generic_only else ("census",))
            if W._ckey(w.get("city")) != city or w.get("set") not in sets_ok:
                continue
            for a in w.get("answers") or []:
                if a.get("kind") == "street" or a.get("hood"):
                    continue
                if not args.generic_only:      # frozen protocol: every city-wall and census answer counts
                    out += [(a.get("provider"), n["name"] if isinstance(n, dict) else n) for n in a.get("names") or []]
                    continue
                pid, txt = str(a.get("phrasing_id") or ""), M.norm(str(a.get("phrasing_text") or a.get("phrasing") or ""))
                if (gids and pid in gids) or (not gids and any(M.norm(g) in txt for g in GENERIC_TEXT)):
                    out += [(a.get("provider"), n["name"] if isinstance(n, dict) else n) for n in a.get("names") or []]
        return out
    w = W.wall_for(city, None)
    return [(a["provider"], n["name"]) for a in w["answers"] if str(a["phrasing"])[:2] in ("P1", "P2", "P3", "P4")
            for n in a["names"]]


def load_runs():
    if args.meter:
        with open(args.meter) as f:
            txt = f.read()
        try:
            recs = json.loads(txt).get("runs", [])
        except ValueError:
            recs = [json.loads(l) for l in txt.splitlines() if l.strip()]
        runs = []
        for r in recs:
            if r.get("status") in ("failed",) or r.get("fake"):
                continue
            arm = {"with": "qloo"}.get(r.get("arm"), r.get("arm"))
            runs.append(dict(r, arm=arm, picks=r.get("picks") or r.get("places") or []))
        return runs, args.meter
    if not args.fake:
        raise SystemExit("--meter is required live (agent B's harness stores the meter runs)")
    runs = []   # [FAKE]: alone = the fixture's all-three taste answer; with Qloo = the fixture's fresh answer
    for city in cli.cities(args):
        if city not in ("nyc", "stl"):
            continue
        e = W._exp()
        alone = (e["STL"] if city == "stl" else e["NYC"])["P8 all three"]
        withq = W.fresh_for(city)[0]["names"]
        for sid, _ in cli.sets(args, city):
            for prov in ("openai", "claude", "gemini"):
                runs.append({"set": sid, "city": city, "provider": prov, "arm": "alone", "picks": alone[:12]})
                runs.append({"set": sid, "city": city, "provider": prov, "arm": "qloo",
                             "picks": [n["name"] for n in withq][:12]})
    return runs, "[FAKE] fixture names"


runs, src = load_runs()
walls_by_city, pools = {}, {}
by_set = {}
for r in runs:
    city = W._ckey(r["city"])
    if city not in walls_by_city:
        walls_by_city[city] = generic_wall(city)
    own = None if args.include_own else r.get("provider")
    key = (city, own)
    if key not in pools:
        names = [n for p, n in walls_by_city[city] if own is None or p != own]
        pools[key] = [{"entity_id": M.norm(n), "name": n} for n in dict.fromkeys(names)]
    picks = [p["name"] if isinstance(p, dict) else p for p in r.get("picks") or []][:12]
    on = 0
    for p in picks:
        st, _ = M.match_wall([p], pools[key], None)
        on += bool(st)
    by_set.setdefault((city, r["set"]), {"alone": [], "qloo": []}).setdefault(r["arm"], []).append(on)
alone_all = [v for s in by_set.values() for v in s["alone"]]
qloo_all = [v for s in by_set.values() for v in s["qloo"]]
drops = 0
for (city, sid), s in sorted(by_set.items()):
    ma, mq = cli.median(s["alone"]), cli.median(s["qloo"])
    big = ma == ma and mq == mq and ma - mq >= 4
    drops += big
    print("    %s/%-8s on the generic wall, of 12: alone %s (median %s) · with Qloo %s (median %s)%s%s" % (
        city.upper(), sid, s["alone"], cli.f(ma, 1), s["qloo"], cli.f(mq, 1), " · >=4 below" if big else "", T))
n_sets = len(by_set)
m_alone, m_qloo = cli.median(alone_all), cli.median(qloo_all)
featured = bool(qloo_all) and m_qloo <= 6 and drops >= 0.7 * n_sets
print("  generic wall: %s (%s; %s)%s" % (
    ", ".join("%s %d names" % (c.upper(), len(set(n for _, n in w))) for c, w in sorted(walls_by_city.items())), src,
    "own provider included" if args.include_own else "each run graded by the other AIs' answers", T))
print("  ⟦M_ALONE⟧ = %s · ⟦M_QLOO⟧ = %s (median of 12, %d sets, %d assistants)%s" % (
    cli.f(m_alone, 1), cli.f(m_qloo, 1), n_sets, len({r["provider"] for r in runs}), T))
print("D meter: median with Qloo %s (gate <=6), >=4 below alone in %d of %d sets (gate >=7 of 10) -> %s%s" % (
    cli.f(m_qloo, 1), drops, n_sets, cli.verdict(featured), T),
      "| FAIL = printed in Shown and the README, not featured; Elias gets the residual line")
print("QLOO_NETWORK_CALLS=0%s" % T)
