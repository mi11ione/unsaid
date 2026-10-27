"""Shared CLI plumbing for the gate scripts. Every script takes
[--fake] [--city nyc|stl|both] [--sets N] [--walls walls.json] [--no-cache] and prints a verdict line, PASS or FAIL.
Fake output is tagged [FAKE]."""
import argparse
import os
import time

from unsaid.qloo import Qloo, write_trace_md
from unsaid import seeds as SD

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(KIT, "out")          # gitignored
DATA = os.path.join(os.path.dirname(KIT), "data")


def parser(desc):
    ap = argparse.ArgumentParser(description=desc, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fake", action="store_true", help="canned responses shaped like the docs (no key, no network)")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--city", choices=["nyc", "stl", "both", "la"], default="both")
    ap.add_argument("--sets", type=int, default=10, help="seed sets per city (<=10)")
    ap.add_argument("--walls", help="walls JSON from the harness (default: fixtures/consensus.py)")
    return ap


def client(args, name, **kw):
    os.makedirs(OUT, exist_ok=True)
    tp = os.path.join(OUT, "%s%s.trace.jsonl" % (name, ".fake" if args.fake else ""))
    if os.path.exists(tp):
        os.remove(tp)
    q = Qloo(fake=args.fake, use_cache=not args.no_cache, trace_path=tp, **kw)
    banner = "[FAKE] canned responses: numbers prove code paths, not Qloo" if args.fake else "[LIVE] %s" % q.base
    print("== %s  %s  %s" % (name, banner, time.strftime("%Y-%m-%d %H:%M")))
    return q


def tag(args):
    return " [FAKE]" if args.fake else ""


def cities(args):
    return ["nyc", "stl"] if args.city == "both" else [args.city]


def sets(args, city):
    return SD.SEED_SETS.get(city, [])[:args.sets]


def city_obj(q, city, cache={}):
    k = (id(q), city)
    if k not in cache:
        from unsaid.engine import resolve_city
        cache[k] = resolve_city(q, SD.CITY_QUERY[city][0])
    return cache[k]


def loves(q, spec):
    """Resolve a seed set's loves the way the scripts always did: take the top candidate, stop only on a miss."""
    from unsaid.engine import resolve_love
    ls = [resolve_love(q, t, h) for t, h in spec]
    return None if any(l["status"] == "miss" for l in ls) else ls


def chips(q, spec):
    """Seed set -> resolved chips for api.run_unsaid (top candidate, as the kit always did), or None on a miss.
    Also returns the texts whose resolution was not exact, so callers can say so."""
    ls = loves(q, spec)
    if ls is None:
        return None, []
    unsure = ["%s -> %s" % (l["text"], l.get("name")) for l in ls if l["status"] != "ok"]
    return [{"id": l["id"], "label": l.get("name") or l["text"], "kind": l["kind"], "type": l.get("type")}
            for l in ls], unsure


def finish(q, args, name):
    p = os.path.join(OUT, "%s%s.trace.md" % (name, ".fake" if args.fake else ""))
    write_trace_md(q.trace, p, "%s call trace" % name)
    print("calls: %d network, %d cache; trace %s" % (q.calls["network"], q.calls["cache"], p))


def verdict(ok):
    return "PASS" if ok else "FAIL"


def f(x, nd=2):
    return "n/a" if x is None or x != x else ("%.*f" % (nd, x))


def median(xs):
    s = sorted(xs)
    n = len(s)
    if not n:
        return float("nan")
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0
