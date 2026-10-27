"""Offline lineup eval (final-judge §8: run as an eval, never as a card). Does Qloo, given a person's three
non-place loves, pick out a place they love from 9 popularity-matched lookalikes in the same city?

Per round: hidden place -> 9 decoys (same city, same genre tag, nearest popularity within +-0.03, widened to +-0.06
once; closed dropped; never padded) -> rank the 10 with filter.results.entities under the clues -> position.
Controls on the same 10: no clue (no signal), and strangers (other people's clues, up to 5).
Reports #1 rate, top-3 rate, mean position (chance 10% / 30% / 5.5) with bootstrap 90% intervals, and the
low-popularity stratum (hidden below the median popularity of its decoys' city pool), which is where UNSAID's cards live.
PASS (three-v2 graft gate): #1 >= 15% and mean position <= 4.0, and strangers' mean position worse than own by >= 0.5.
Live input: --rounds rounds.json  {"rounds":[{"person":"p1","city":"stl","hidden":"Pappy's Smokehouse",
           "clues":[["Al Green","artist"],["Barbershop","movie"],["rib tips","tag"]]}]}"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from unsaid import cli, engine as E, matcher as M, stats as ST, seeds as SD  # noqa: E402
from unsaid.qloo import affinity, prop  # noqa: E402

ap = cli.parser(__doc__)
ap.add_argument("--rounds")
args = ap.parse_args()
q = cli.client(args, "lineup_eval")


def fake_rounds():
    """10 people x 3 rounds from the fake world: hidden = a place at taste rank 3, 15 or 40 under their clues."""
    rounds = []
    people = [("nyc", s) for s, _ in SD.SEED_SETS["nyc"][:5]] + [("stl", s) for s, _ in SD.SEED_SETS["stl"][:5]]
    for n, (city, sid) in enumerate(people):
        spec = [x for x in SD.get(city, sid) if x[1] != "place"]
        c = cli.city_obj(q, city)
        loves = [E.resolve_love(q, t, h) for t, h in spec]
        pool, _, _ = E.taste_pool(q, c, loves, pages=1, adaptive=False)
        for pos in (3, 15, 40):
            if len(pool) >= pos:
                rounds.append({"person": "p%d" % n, "city": city, "hidden": pool[pos - 1]["name"], "clues": spec,
                               "_hidden_id": pool[pos - 1]["entity_id"]})
    return rounds


def genre_tag(e):
    t = [x for x in (e.get("tags") or []) if str(x.get("id", "")).startswith("urn:tag:genre:place:restaurant:")]
    return t[0]["id"] if t else "urn:tag:genre:place:restaurant"


def position(c, ids, hidden, clues):
    p = {"filter.type": E.PLACE, "filter.location": c["id"], "filter.results.entities": sorted(ids), "take": 10,
         "bias.trends": E.CFG["BIAS_TRENDS"]}
    if clues:
        p.update(E.signal(clues))
    ents = (q.insights(p, label="lineup score").get("results") or {}).get("entities") or []
    order = [e["entity_id"] for e in ents]
    if hidden not in order:
        return 10, False
    i = order.index(hidden)
    a = [affinity(e) for e in ents]
    tie = i > 0 and a[0] is not None and a[i] is not None and a[0] - a[i] <= 0.01
    return i + 1, tie


rounds = json.load(open(args.rounds))["rounds"] if args.rounds else fake_rounds()
rows = []
for r in rounds:
    c = cli.city_obj(q, r["city"])
    loc = "%s,%s" % (c["lat"], c["lon"])
    if r.get("_hidden_id"):
        hid = r["_hidden_id"]
    else:
        res = q.search(r["hidden"], types=E.PLACE, take=5, location=loc, radius_mi=25, label="lineup hidden")
        best = next((x for x in res if M.strong(r["hidden"], x.get("name", ""))), None)
        if best is None:
            print("  %s: '%s' not found -> skipped" % (r["person"], r["hidden"])); continue
        hid = best["entity_id"]
    h = q.entities([hid], label="lineup facts")
    h = h[0] if h else None
    if h is None or prop(h, "is_closed") is True:
        print("  %s: hidden missing or closed -> skipped" % r["person"]); continue
    pop = h.get("popularity") or 0
    decoys = []
    for band in (0.03, 0.06):
        p = {"filter.type": E.PLACE, "filter.location": c["id"], "filter.tags": [genre_tag(h)],
             "filter.popularity.min": round(max(0, pop - band), 4), "filter.popularity.max": round(min(1, pop + band), 4),
             "filter.exclude.entities": [hid], "take": 50, "bias.trends": E.CFG["BIAS_TRENDS"]}
        ents = (q.insights(p, label="lineup decoys").get("results") or {}).get("entities") or []
        ents = [e for e in ents if prop(e, "is_closed") is not True]
        decoys = sorted(ents, key=lambda e: (abs((e.get("popularity") or 0) - pop), e["entity_id"]))[:9]
        if len(decoys) == 9:
            break
    if len(decoys) < 9:
        print("  %s: thin city (%d decoys) -> skipped, never padded" % (r["person"], len(decoys))); continue
    ids = [hid] + [d["entity_id"] for d in decoys]
    clues = [E.resolve_love(q, t, hh) for t, hh in r["clues"]]
    own, tie = position(c, ids, hid, clues)
    none, _ = position(c, ids, hid, None)
    others = [x for x in rounds if x["person"] != r["person"]][:]
    seen, strangers = set(), []
    for x in others:
        key = tuple(map(tuple, x["clues"]))
        if key in seen:
            continue
        seen.add(key)
        strangers.append(position(c, ids, hid, [E.resolve_love(q, t, hh) for t, hh in x["clues"]])[0])
        if len(strangers) == 5:
            break
    dpop = sorted(d.get("popularity") or 0 for d in decoys)
    rows.append({"own": own, "tie": tie, "none": none, "str": sum(strangers) / len(strangers), "low": pop < dpop[4]})
    print("  %-4s %-30s own #%d%s | no-clue #%d | strangers mean #%.1f" % (
        r["person"], r["hidden"][:30], own, " (tie)" if tie else "", none, rows[-1]["str"]))

if not rows:
    print("lineup: no usable rounds"); sys.exit(1)
n = len(rows)
top1 = [1.0 if x["own"] == 1 else 0.0 for x in rows]
top3 = [1.0 if x["own"] <= 3 else 0.0 for x in rows]
mean = sum(x["own"] for x in rows) / n
lo, hi = ST.bootstrap(top1)
print("  rounds %d: #1 %.0f%% (90%% CI %.0f-%.0f; chance 10%%), top-3 %.0f%% (chance 30%%), mean position %.2f (chance 5.5)" % (
    n, 100 * sum(top1) / n, 100 * lo, 100 * hi, 100 * sum(top3) / n, mean))
nc1 = sum(1 for x in rows if x["none"] == 1) / n
smean = sum(x["str"] for x in rows) / n
low = [x for x in rows if x["low"]]
print("  controls: no-clue #1 %.0f%% (want <=15%%) | strangers mean position %.2f (own %.2f)" % (100 * nc1, smean, mean))
if low:
    print("  low-popularity stratum: %d rounds, #1 %.0f%%, mean position %.2f" % (
        len(low), 100 * sum(1 for x in low if x["own"] == 1) / len(low), sum(x["own"] for x in low) / len(low)))
tier = "good" if sum(top1) / n >= 0.35 and sum(top3) / n >= 0.70 else "graft-level" if sum(top1) / n >= 0.15 else "kill"
ok = sum(top1) / n >= 0.15 and mean <= 4.0 and smean >= mean + 0.5
print("Lineup eval: %s (tier %s)%s | report the population line in the README whatever it says" % (cli.verdict(ok), tier, cli.tag(args)))
cli.finish(q, args, "lineup_eval")
