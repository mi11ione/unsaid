"""Gate D · grounding meter (UNSAID.md §4; protocol in unsaid-v3 §3.5). 0 new Qloo calls: it only reads stored runs.
Each assistant is told "Where should someone who loves L1, L2 and L3 eat and drink tonight in {city}? ... but nothing
every AI would tell me. Name 12 places." twice: alone, and with `qloo_places(loves, city)` as its only tool (the top 50
of the taste pool, nothing subtracted). Measure: picks the matcher finds on the city's GENERIC wall (phrasings 1-4,
three providers; never the assistant's own taste answers).
Decision rule: FEATURED only if the median with Qloo is <= 6 of 12 AND it is >= 4 below alone in >= 7 of 10 sets.
Printed in Shown and the README whatever it says. Fills ⟦M_ALONE⟧ ⟦M_QLOO⟧.

  --meter meter.json  {"runs": [{"set", "city", "provider", "model", "arm": "alone"|"qloo", "asked_at",
                                 "picks": ["name", ...] or [{"name"}]}]}     (agent B's harness writes it)
  --walls walls.json  the generic wall (entries with set "city"; phrasings 1-4 by --generic-ids or by their text)
In --fake mode with no --meter, fixture names stand in, tagged [FAKE]."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from unsaid import cli, matcher as M, seeds as SD, walls as W  # noqa: E402

GENERIC_TEXT = ("best places to eat and drink", "where do locals go", "not touristy", "must try restaurants")
ap = cli.parser(__doc__)
ap.add_argument("--meter")
ap.add_argument("--generic-ids", help="comma-separated phrasing_ids of the 4 generic phrasings")
args = ap.parse_args()
T = cli.tag(args)
print("== k10_meter  %s  (0 Qloo calls: no client is created)" % ("[FAKE]" if args.fake else "[LIVE] stored runs"))


def generic_wall(city):
    gids = set((args.generic_ids or "").split(",")) - {""}
    if args.walls:
        out = []
        for w in W.load_file(args.walls).get("walls", []):
            if W._ckey(w.get("city")) != city or w.get("set") not in W.GENERIC_SETS:
                continue
            for a in w.get("answers") or []:
                pid, txt = str(a.get("phrasing_id") or ""), M.norm(str(a.get("phrasing_text") or a.get("phrasing") or ""))
                if (gids and pid in gids) or (not gids and any(M.norm(g) in txt for g in GENERIC_TEXT)):
                    out += [n["name"] if isinstance(n, dict) else n for n in a.get("names") or []]
        return out
    w = W.wall_for(city, None)
    return [n["name"] for a in w["answers"] if str(a["phrasing"])[:2] in ("P1", "P2", "P3", "P4") for n in a["names"]]


def load_runs():
    if args.meter:
        with open(args.meter) as f:
            return json.load(f).get("runs", []), args.meter
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
pools = {}
by_set = {}
for r in runs:
    city = W._ckey(r["city"])
    if city not in pools:
        pools[city] = [{"entity_id": M.norm(n), "name": n} for n in dict.fromkeys(generic_wall(city))]
    picks = [p["name"] if isinstance(p, dict) else p for p in r.get("picks") or []][:12]
    on = 0
    for p in picks:
        st, _ = M.match_wall([p], pools[city], None)
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
print("  generic wall: %s (%s)%s" % (", ".join("%s %d names" % (c.upper(), len(p)) for c, p in sorted(pools.items())),
                                     src, T))
print("  ⟦M_ALONE⟧ = %s · ⟦M_QLOO⟧ = %s (median of 12, %d sets, %d assistants)%s" % (
    cli.f(m_alone, 1), cli.f(m_qloo, 1), n_sets, len({r["provider"] for r in runs}), T))
print("D meter: median with Qloo %s (gate <=6), >=4 below alone in %d of %d sets (gate >=7 of 10) -> %s%s" % (
    cli.f(m_qloo, 1), drops, n_sets, cli.verdict(featured), T),
      "| FAIL = printed in Shown and the README, not featured; Elias gets the residual line")
