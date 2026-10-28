"""Love resolution, live: 64 typed inputs (engine/tests/resolver_cases.json), top-1 accuracy per site field.

    set -a; . ~/.config/unsaid/env; set +a          # QLOO_API_KEY, sent only in the X-Api-Key header
    python3 -I engine/tests/test_resolver.py [--budget 250] [--only before|after] [-v]

Every case is sent the way the site sends it: field 1 with hint 'artist', field 2 with hint 'movie', field 3 with no
hint. "before" is the resolver as it was on 28 Oct (a verbatim copy below, legacy_resolve_love); "after" is the
current api.resolve_love. Both go through the Qloo client's disk cache, so a rerun costs no calls.
Exit status 1 when any field is under 90 % after.
"""
import argparse
import json
import math
import os
import sys

ENGINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ENGINE)

from unsaid import api                    # noqa: E402
from unsaid import cities as C            # noqa: E402
from unsaid import engine as E            # noqa: E402
from unsaid import matcher as M           # noqa: E402
from unsaid.qloo import Qloo, latlon      # noqa: E402

CASES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resolver_cases.json")
SITE_HINT = {1: "artist", 2: "movie", 3: None}      # site/js/app.js FIELDS[i].hint
TARGET = 0.90


def legacy_resolve_love(q, text, hint=None):
    """engine.resolve_love as of commit 2e9e349 (28 Oct 2026), kept only to print the 'before' number."""
    text = (text or "").strip()
    out = {"text": text, "status": "miss", "kind": None, "id": None, "name": None, "type": None,
           "is_place": False, "alternatives": [], "dead": False, "dead_reason": None}

    def as_tag(tags, exact_needed):
        t = tags[0]
        exact = M.norm(t.get("name") or "") == M.norm(text)
        out.update({"kind": "tag", "id": t.get("id") or t.get("tag_id"), "name": t.get("name"),
                    "type": t.get("type") or "tag", "status": "ok" if (exact or not exact_needed) else "needs_input"})
        return out

    pre = E._pre_resolved().get(M.norm(text))
    if pre and (not hint or hint == "tag" and pre.get("kind") == "tag" or pre.get("type", "").endswith(":" + hint)):
        out.update({"kind": pre["kind"], "id": pre["id"], "name": pre["name"], "type": pre["type"], "status": "ok"})
        return out
    if hint == "tag":
        tags = q.tags(text, take=5, label="C2 love tag") or q.tags(text, take=5, semantic=True, label="C2 love tag~")
        return as_tag(tags, True) if tags else out
    types = "urn:entity:%s" % hint if hint else None
    res = q.search(text, types=types, take=5, label="C2 love")
    if res:
        exact = [r for r in res if M.norm(r.get("name", "")) == M.norm(text)]
        r = (exact or res)[0]
        sub = r.get("subtype") or (r.get("types") or [""])[0]
        out.update({"kind": "entity", "id": r["entity_id"], "name": r.get("name"), "type": sub,
                    "status": "ok" if exact and len(exact) == 1 or (exact and hint) else "needs_input"})
        return out
    tags = q.tags(text, take=5, label="C2 love tag") or q.tags(text, take=5, semantic=True, label="C2 love tag~")
    if tags:
        return as_tag(tags, True)
    return out


def before(q, text, hint):
    l = legacy_resolve_love(q, text, hint)
    return {"status": l["status"], "id": l["id"], "label": l["name"], "type": l["type"], "type_label": None}


def after(q, text, hint):
    r = api.resolve_love(text, hint, mode="live", qloo=q)
    ch = r.get("chip") or {}
    return {"status": r["status"], "id": ch.get("id"), "label": ch.get("label"), "type": ch.get("type"),
            "type_label": ch.get("type_label"), "disamb": ch.get("disamb"),
            "alts": ["%s (%s)" % (a.get("label"), a.get("type_label") or a.get("type")) for a in r.get("alternatives") or []]}


def miles(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(h))


def grade(q, case, got, dish_tags):
    types = dish_tags if case["types"] == "dish_tags" else case["types"]
    if got.get("type") not in types:
        return False
    if M.norm(got.get("label") or "") not in {M.norm(x) for x in case["labels"]}:
        return False
    if case.get("id") and got.get("id") != case["id"]:
        return False
    if case.get("disamb_contains") and case["disamb_contains"] not in (got.get("disamb") or ""):
        return False
    if case.get("near"):
        ents = q.entities([got["id"]], label="test place") if got.get("id") else []
        ll = latlon(ents[0]) if ents else None
        city = C.CITIES[case["near"]]
        if not ll or miles(ll, city["center"]) > city["radius_mi"] * 1.5:
            return False
    return True


def run(q, fn, cases, dish_tags, verbose, name):
    per = {1: [0, 0], 2: [0, 0], 3: [0, 0]}
    for c in cases:
        got = fn(q, c["text"], SITE_HINT[c["field"]])
        ok = grade(q, c, got, dish_tags)
        per[c["field"]][0] += ok
        per[c["field"]][1] += 1
        if verbose or not ok:
            print("  %-6s %s f%d %-26s -> %s · %s [%s]%s%s" % (
                name, "ok  " if ok else "MISS", c["field"], c["text"], got.get("label"),
                got.get("type_label") or (got.get("type") or "").split(":")[-1] or "-", got.get("status"),
                ("  %s" % got["disamb"][:50]) if got.get("disamb") else "",
                ("  alts: " + "; ".join(got["alts"])) if verbose and got.get("alts") else ""))
    return per


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=int, default=250, help="max live Qloo calls (cache hits are free)")
    ap.add_argument("--only", choices=("before", "after"))
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    spec = json.load(open(CASES))
    cases, dish = spec["cases"], spec["dish_tags"]
    if not os.environ.get("QLOO_API_KEY"):
        sys.exit("QLOO_API_KEY is not set (set -a; . ~/.config/unsaid/env; set +a)")
    q = Qloo(budget=a.budget)
    res = {}
    for name, fn in (("before", before), ("after", after)):
        if a.only and a.only != name:
            continue
        res[name] = run(q, fn, cases, dish, a.verbose, name)
    print("\ntop-1 accuracy (%d cases; field 1 artist, 2 film or show, 3 something you'd order)" % len(cases))
    for f in (1, 2, 3):
        print("  field %d  " % f + "   ".join("%s %2d/%d (%3.0f%%)" % (n, r[f][0], r[f][1], 100.0 * r[f][0] / r[f][1])
                                           for n, r in res.items()))
    print("  Qloo calls: %(network)d network, %(cache)d cache" % q.calls)
    if "after" in res and any(r[0] < TARGET * r[1] for r in res["after"].values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
