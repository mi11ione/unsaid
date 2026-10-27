"""K9 baseline fallback check (P12's '+5 calls' branch, UNSAID.md §3.2): if the no-signal order is NOT popularity,
UNSAID rescores U with no signal instead. This checks that branch works: coverage >= 0.95, distinct scores, anchor drift,
and rho with popularity. PASS: the no-signal rescoring is usable (or not needed: rho >= 0.98 = popularity)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from unsaid import cli, engine as E, stats as ST  # noqa: E402

args = cli.parser(__doc__).parse_args()
q = cli.client(args, "k9_baseline")
T = cli.tag(args)
oks = []
for city in cli.cities(args):
    c = cli.city_obj(q, city)
    sid, spec = cli.sets(args, city)[0]
    loves = cli.loves(q, spec)
    pool, _ = E.per_love_pools(q, c, loves)
    U, _ = E.floor(pool, c)
    ids = [e["entity_id"] for e in U]
    rs = E.rescore(q, c, loves, ids, None, "K9 no-signal")
    nr = E.ranks_from(rs["aff"], ids)
    pr = ST.rank({e["entity_id"]: E.popularity(e) for e in U})
    rho = ST.spearman(nr, pr)
    ok = rs["coverage"] >= 0.95 and rs["distinct"] >= 0.5 * len(ids) and rs["drift"] <= E.CFG["ANCHOR_DRIFT_MAX"]
    oks.append(ok or rho >= 0.98)
    dec = ("popularity (same order, 0 calls)" if rho >= 0.98 else "no-signal rescoring (+%d calls)" % rs["calls"]
           if ok else "popularity (rescoring unusable)")
    print("  %s/%s: N=%d coverage %s (missing %d) distinct %d drift %s calls %d rho(no-signal, popularity) %s -> "
          "anyone = %s%s" % (city.upper(), sid, len(ids), cli.f(rs["coverage"]), len(rs["missing"]), rs["distinct"],
                             cli.f(rs["drift"], 4), rs["calls"], cli.f(rho), dec, T))
print("K9 baseline:", cli.verdict(all(oks)) + T, "| P12 decides; this checks the +5-call branch")
cli.finish(q, args, "k9_baseline")
