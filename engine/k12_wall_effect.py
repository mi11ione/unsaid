"""K12 · what crossing out changes (the wall ablation). For each frozen set (data/sets.json), the SAME engine pipeline
(engine.run: pools -> floor -> U -> per-love rescoring -> RRF for-you order -> lift order -> holds -> reverse check ->
7 cards) runs twice over the same U: once with the real dated wall, once with an empty wall. Three lists of 7:

  on     the shipped cards (real wall: struck, then the reverse check)
  off    the same pipeline with an empty wall (nothing struck, no reverse check)
  plain  Qloo's plain top 7 by taste: the RRF fit order over U (floor applied), no strike, no popularity/lift term

"named" = any AI answer names the place: the set's dated wall answers (data/walls: city wall, census, street, the
set's taste asks) plus the held-out fresh asks (harness/runs/fresh.jsonl: the city's 20 public questions and the
set's 4 with-loves questions), by the matcher (R1-R4 against the 7 names) and the reverse check on the raw text, the
same check k5_fresh.py uses. "fresh" counts the held-out fresh asks only: they never fed the wall.

Offline by default: the frozen Qloo cache (no TTL) answers; a cache miss costs a live call, capped by --budget.
The live Gemini lane and the street check are off in both arms (as in precompute --no-street with no live ask), the
CAP proof call is skipped (cards never depend on it), and the last-seen check is the local hours + address one
(--site-check adds the venue-site HTTP check, cached 24 h, for both arms).

  python3 -I k12_wall_effect.py                     # 20 sets, writes out/k12_wall_effect.md
  python3 -I k12_wall_effect.py --fake --sets 2     # the code path, [FAKE]
"""
import copy, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from unsaid import cli, engine as E, matcher as M, seeds as SD, walls as W  # noqa: E402

ROOT = os.path.dirname(cli.KIT)
ap = cli.parser(__doc__)
ap.set_defaults(walls=os.path.join(ROOT, "data", "walls"), budget=40)
ap.add_argument("--fresh-answers", default=os.path.join(ROOT, "harness", "runs", "fresh.jsonl"))
ap.add_argument("--site-check", action="store_true", help="last-seen also checks venue sites (network, cached 24 h)")
ap.add_argument("--md", default=os.path.join(cli.OUT, "k12_wall_effect.md"))
args = ap.parse_args()
T = cli.tag(args)
EMPTY = {"answers": [], "source": "empty wall (k12 ablation)"}
N7 = E.CFG["N_CARDS"]
E.CFG["CAP_ENABLED"] = False


def load_fresh():
    if not os.path.exists(args.fresh_answers):
        print("  no fresh answers at %s: the named check uses the dated wall only" % args.fresh_answers)
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


def named_in(names, answers):
    """Which of these place names any answer names: matcher R1-R4 on the names + reverse check on the raw text."""
    if not names or not answers:
        return set()
    pool = [{"entity_id": n, "name": n} for n in names]
    raws = [n["name"] if isinstance(n, dict) else n for a in answers for n in a.get("names") or []]
    st, _ = M.match_wall(raws, pool, None)
    hit = set(st)
    rix = E.reverse_index(answers)
    return hit | {n for n in names if E.reverse_hit(n, rix) is not None}


def last_seen_hook():
    if not args.site_check:
        return None
    from unsaid import lastseen
    return lastseen.fake_check if args.fake else lastseen.check


q = cli.client(args, "k12_wall_effect", frozen=True)
fresh = load_fresh()
rows = []
for city in cli.cities(args):
    c = cli.city_obj(q, city)
    for sid, spec in cli.sets(args, city):
        ls = cli.loves(q, spec)
        if ls is None:
            print("    %s/%-18s a love is not in Qloo; skipped%s" % (city.upper(), sid, T))
            continue
        wall = W.wall_for(city, sid, args.walls, loves=[t for t, _ in spec])
        on = E.run(q, c, copy.deepcopy(ls), wall, last_seen=last_seen_hook())
        off = E.run(q, c, copy.deepcopy(ls), EMPTY, last_seen=last_seen_hook())
        if on.get("status") in (None, "needs_input", "degraded") or "_R" not in off:
            print("    %s/%-18s %s / %s; skipped%s" % (city.upper(), sid, on.get("status"), off.get("status"), T))
            continue
        name_of = {e["entity_id"]: e.get("name") or "" for e in off["_U"]}
        fit = off["_R"]["fit"]
        on7 = [p["id"] for p in on["picks"]][:N7]
        off7 = [p["id"] for p in off["picks"]][:N7]
        plain7 = sorted(fit, key=lambda i: (fit[i], i))[:N7]
        fr = [a for a in fresh if W._ckey(a.get("city")) == city and (a.get("set") in (None, "", "-") or SD.same(a.get("set"), sid))]
        every = list(wall["answers"]) + fr

        def score(ids):
            ns = [name_of.get(i) or i for i in ids]
            return named_in(ns, every), named_in(ns, fr)
        r = {"city": city, "set": sid, "U": off["diag"]["N"], "struck_in_U": on["counts"].get("struck_in_U"),
             "wall_answers": len(wall["answers"]), "fresh_answers": len(fr),
             "differ": len(set(off7) - set(on7)), "n_on": len(on7), "n_off": len(off7),
             "plain_in_on": len(set(plain7) & set(on7)), "flat": "flat" in (off.get("flags") or []),
             "struck_fit_ranks": on["diag"].get("struck_fit_ranks", [])[:7]}
        for k, ids in (("on", on7), ("off", off7), ("plain", plain7)):
            a, f = score(ids)
            r[k + "_named"], r[k + "_fresh"], r[k + "_names"] = len(a), len(f), sorted(a)
            r[k + "_struck"] = sum(1 for i in ids if i in on["_struck"])
        rows.append(r)
        print("    %s/%-18s U %3d: %d of %d cards differ · named by the AIs: on %d · off %d · plain %d "
              "(fresh asks only: %d · %d · %d) · plain top-7 struck by the wall %d%s" % (
                  city.upper(), sid, r["U"], r["differ"], r["n_off"], r["on_named"], r["off_named"], r["plain_named"],
                  r["on_fresh"], r["off_fresh"], r["plain_fresh"], r["plain_struck"], T))

med = {k: cli.median([r[k] for r in rows]) for k in ("differ", "on_named", "off_named", "plain_named", "on_fresh",
                                                      "off_fresh", "plain_fresh", "plain_struck", "off_struck")}
summary = ("median over %d sets: %s of 7 cards differ; AI-named cards: with the wall %s, without it %s, Qloo's plain "
           "top 7 %s (held-out fresh asks only: %s, %s, %s)" % (
               len(rows), cli.f(med["differ"], 1), cli.f(med["on_named"], 1), cli.f(med["off_named"], 1),
               cli.f(med["plain_named"], 1), cli.f(med["on_fresh"], 1), cli.f(med["off_fresh"], 1),
               cli.f(med["plain_fresh"], 1)))
print("  " + summary + T)

os.makedirs(os.path.dirname(args.md), exist_ok=True)
with open(args.md, "w") as f:
    f.write("# K12 · what crossing out changes%s\n\n" % T)
    f.write("Engine `%s`. The same pipeline ran twice per set over the same U: with the real dated wall (`on`) and "
            "with an empty wall (`off`). `plain` is Qloo's top 7 by taste (fit order over U, floor applied, no strike, "
            "no popularity term). *named* = named by any dated wall answer or held-out fresh-ask answer (matcher + "
            "reverse check); *fresh* = the held-out fresh asks only, which never fed the wall. *struck* = members of the "
            "list the real wall crosses out. Qloo calls: %d network, %d cache.\n\n" % (
                E.ENGINE_V, q.calls["network"], q.calls["cache"]))
    f.write("**%s.**\n\n" % (summary[0].upper() + summary[1:]))
    f.write("| set | U | struck in U | cards differ | named: on | off | plain | fresh: on | off | plain | "
            "plain struck | plain in on |\n|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n")
    for r in rows:
        f.write("| %s | %d | %s | %d of %d | %d | %d | %d | %d | %d | %d | %d | %d |\n" % (
            r["set"], r["U"], r["struck_in_U"], r["differ"], r["n_off"], r["on_named"], r["off_named"],
            r["plain_named"], r["on_fresh"], r["off_fresh"], r["plain_fresh"], r["plain_struck"], r["plain_in_on"]))
    f.write("| **median** | | | **%s** | **%s** | **%s** | **%s** | **%s** | **%s** | **%s** | **%s** | |\n\n" % tuple(
        cli.f(med[k], 1) for k in ("differ", "on_named", "off_named", "plain_named", "on_fresh", "off_fresh",
                                   "plain_fresh", "plain_struck")))
    f.write("Named places (wall off · plain top 7):\n\n")
    for r in rows:
        f.write("- %s: off %s · plain %s\n" % (r["set"], ", ".join(r["off_names"]) or "none",
                                               ", ".join(r["plain_names"]) or "none"))
print("  table: %s" % args.md)
print("K12 wall effect: %d sets -> %s%s" % (len(rows), cli.verdict(len(rows) > 0), T))
cli.finish(q, args, "k12_wall_effect")
