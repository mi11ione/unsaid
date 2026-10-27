"""K3 survivors (+ K2b, explainability-vs-drop-one agreement): the full pipeline per seed set.
kept = open, rated >= 4.3, not named by the wall, holds in >= 2 of 3 drop-one runs.
PASS: >= 7 kept in >= 8 of 10 NYC sets and >= 6 of 10 STL sets.
K2b: of the struck pool members, <= 80% would also be cut by a popularity cap removing the same number.
Wall: --walls JSON from the harness, else exp/consensus.py (one model from memory; 4 generic answers where no list)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from unsaid import cli, engine as E, walls as W  # noqa: E402
from unsaid.qloo import explain_items  # noqa: E402

args = cli.parser(__doc__).parse_args()
q = cli.client(args, "k3_survivors")
need = {"nyc": 8, "stl": 6}
ok_all, k2b = True, []
agree, agree_n = 0, 0
for city in cli.cities(args):
    c = cli.city_obj(q, city)
    hits, n = 0, 0
    print("  %s" % city.upper())
    for sid, spec in cli.sets(args, city):
        wall = W.wall_for(city, sid, args.walls)
        r = E.run(q, c, spec, wall)
        d = r["diag"]
        if r["status"] == "needs_input":
            print("    %-8s needs_input" % sid); continue
        n += 1
        hits += d["kept"] >= 7
        k2b.append(d["popcap_overlap"])
        st = d["wall"]["status"]
        print("    %-8s U=%3d wall %2d answers/%3d names -> struck %3d (not found %d, outside pool %d) S=%3d kept=%3d -> %s cards | "
              "popcap overlap %s AUC(pop->struck) %s%s" % (
                  sid, d["U"], d["wall"]["answers"], d["wall"]["names"], d["wall"]["struck"], st.get("not_found", 0),
                  st.get("outside_pool", 0), d["S"], d["kept"], r["status"], cli.f(d["popcap_overlap"]),
                  cli.f(d["auc_pop_struck"]), " FLAGS " + ",".join(r["flags"]) if r["flags"] else ""))
        for card in r["cards"]:  # does explainability's top love agree with the drop-one counterfactual?
            dl = r["_deltas"].get(card["qloo_id"]) or {}
            if card["because"]["source"] == "explainability" and dl:
                agree_n += 1
                agree += max(dl.items(), key=lambda kv: kv[1])[0] == card["because"]["love"]
    ok = n > 0 and hits >= need[city] * n / 10.0
    ok_all &= ok
    print("  %s: >=7 kept in %d of %d sets (gate %d of 10) -> %s%s" % (city.upper(), hits, n, need[city], cli.verdict(ok), cli.tag(args)))
vals = [v for v in k2b if v == v]
med = sorted(vals)[len(vals) // 2] if vals else float("nan")
print("K3 survivors:", cli.verdict(ok_all) + cli.tag(args), "| fallback: empty-few state; widen to metro; allow holds 2 of 3")
print("because-line cross-check: explainability's top love = the love whose drop moves the card most in %d of %d cards" % (agree, agree_n))
print("K2b wall vs popularity cap: median overlap %s (gate <=0.80) -> %s%s" % (cli.f(med), cli.verdict(med <= 0.8), cli.tag(args)))
cli.finish(q, args, "k3_survivors")
