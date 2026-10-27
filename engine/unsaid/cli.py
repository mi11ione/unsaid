"""Shared CLI plumbing for the kill-test scripts."""
import argparse
import os
import time

from unsaid.qloo import Qloo, write_trace_md
from unsaid import seeds as SD

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(KIT, "out")


def parser(desc):
    ap = argparse.ArgumentParser(description=desc)
    ap.add_argument("--fake", action="store_true", help="canned responses shaped like the docs (no key, no network)")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--city", choices=["nyc", "stl", "both"], default="both")
    ap.add_argument("--sets", type=int, default=10, help="seed sets per city (<=10)")
    ap.add_argument("--walls", help="walls JSON from the consensus harness (default: exp/consensus.py)")
    return ap


def client(args, name):
    os.makedirs(OUT, exist_ok=True)
    tp = os.path.join(OUT, "%s%s.trace.jsonl" % (name, ".fake" if args.fake else ""))
    if os.path.exists(tp):
        os.remove(tp)
    q = Qloo(fake=args.fake, use_cache=not args.no_cache, trace_path=tp)
    banner = "[FAKE] canned responses: numbers prove code paths, not Qloo" if args.fake else "[LIVE] %s" % q.base
    print("== %s  %s  %s" % (name, banner, time.strftime("%Y-%m-%d %H:%M")))
    return q


def tag(args):
    return " [FAKE]" if args.fake else ""


def cities(args):
    return ["nyc", "stl"] if args.city == "both" else [args.city]


def sets(args, city):
    return SD.SEED_SETS[city][:args.sets]


def city_obj(q, city, cache={}):
    k = (id(q), city)
    if k not in cache:
        from unsaid.engine import resolve_city
        name, region = SD.CITY_QUERY[city]
        cache[k] = resolve_city(q, name, region)
    return cache[k]


def finish(q, args, name):
    p = os.path.join(OUT, "%s%s.trace.md" % (name, ".fake" if args.fake else ""))
    write_trace_md(q.trace, p, "%s call trace" % name)
    print("calls: %d network, %d cache; trace %s" % (q.calls["network"], q.calls["cache"], p))


def verdict(ok):
    return "PASS" if ok else "FAIL"


def f(x, nd=2):
    return "n/a" if x is None or x != x else ("%.*f" % (nd, x))
