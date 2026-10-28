"""K4 offline: the matcher over the 136 labelled names (fixtures/labels.py, from research/exp/labels.py), no key needed.

Run:  python3 -I tests/test_matcher.py        (from the kit folder, or with any cwd)
Hard gate: zero false survivors (a pool member a human marks as named that is not struck).
Soft gate (K4): strike precision >= 95%. Over-strikes are the safe direction and are listed by name.
"""
import ast
import difflib
import os
import sys
import unittest

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, KIT)

from unsaid import matcher as M          # noqa: E402
from fixtures import matcher_catalog as C  # noqa: E402

LABELS = os.environ.get("UNSAID_LABELS") or os.path.join(KIT, "fixtures", "labels.py")
CLASSES = {"A": "clean", "V": "alias/embedded", "M": "multi-location", "G": "common-word",
           "N": "not eat/drink", "X": "closed", "U": "unverifiable", "S": "seed"}


def load_labels():
    """Read L_NYC / L_STL as string constants with ast (labels.py is never executed)."""
    with open(LABELS) as f:
        tree = ast.parse(f.read())
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            name = node.targets[0].id
            if name in ("L_NYC", "L_STL"):
                items = [x.rsplit(":", 1) for x in node.value.value.split("|")]
                out["nyc" if name == "L_NYC" else "stl"] = [(n, f) for n, f in items]
    return out


def fake_search(catalog):
    """Stand-in for /search scoped to the city: rank every Qloo record by name similarity, top 5."""
    def fn(raw):
        r = M.norm(raw)
        scored = []
        for c in catalog:
            n = M.norm(c["name"])
            s = difflib.SequenceMatcher(None, r, n).ratio()
            s += 0.3 * M.overlap(M.distinctive(raw), M.distinctive(c["name"]))
            if s > 0.55:
                scored.append((s, c))
        scored.sort(key=lambda x: -x[0])
        return [c for _, c in scored[:5]]
    return fn


def evaluate(city, labels, use_search=True):
    pool, catalog, named = C.build(city)
    raws = [n for n, _ in labels]
    struck, per = M.match_wall(raws, pool, fake_search(catalog) if use_search else None)
    s = set(struck)
    tp = s & named
    fp = s - named
    fn = named - s
    by_class = {}
    raw_of = {p["entity_id"]: p.get("raw") for p in pool}
    flags = dict(labels)
    for eid in named:
        for k in flags[raw_of[eid]]:
            t = by_class.setdefault(k, [0, 0])
            t[1] += 1
            t[0] += eid in s
    names = {p["entity_id"]: p["name"] for p in pool}
    return {"pool": len(pool), "named": len(named), "struck": len(s), "tp": len(tp), "fp": sorted(names[e] for e in fp),
            "fn": sorted("%s (from '%s')" % (names[e], raw_of[e]) for e in fn),
            "precision": len(tp) / len(s) if s else 1.0, "by_class": by_class, "per": per, "struck_map": struck,
            "names": names}


class TestNormalisation(unittest.TestCase):
    def test_norm(self):
        self.assertEqual(M.norm("Barbès"), "barbes")
        self.assertEqual(M.norm("Olive + Oak"), M.norm("Olive and Oak"))
        self.assertEqual(M.norm("Pappy's Smokehouse"), "pappy smokehouse")
        self.assertEqual(M.norm("Sugarfire Smoke House"), "sugarfire smokehouse")
        self.assertEqual(M.norm("Phil's Bar-B-Que"), "phil bbq")
        self.assertEqual(M.norm("O'Connell's Pub"), "oconnell pub")

    def test_acronym(self):
        self.assertEqual(M.acronym("Please Don't Tell"), "pdt")
        self.assertTrue(M._key_match(M.keys("Please Don't Tell"), M.keys("PDT")))

    def test_embedded(self):
        h, host, _ = M.split_parts("Lobby Bar at Hotel Chelsea")
        self.assertEqual((h, host), ("lobby bar", "hotel chelsea"))
        self.assertTrue(M._key_match(M.keys("Bemelmans Bar"), M.keys("Bemelmans Bar at The Carlyle")))
        self.assertTrue(M._key_match(M.keys("Charlie Gitto's on the Hill"), M.keys("Charlie Gitto's Downtown")))

    def test_generic_only_name_never_guards(self):
        pool = [{"entity_id": "1", "name": "The Bar Room"}, {"entity_id": "2", "name": "Room Bar"}]
        struck, _ = M.match_wall(["The Bar Room"], pool)
        self.assertEqual(set(struck), {"1", "2"} & set(struck))
        self.assertIn("1", struck)

    def test_outside_pool_strikes_nothing(self):
        pool = [{"entity_id": "p", "name": "Good Enough to Eat"}]
        cat = pool + [{"entity_id": "o", "name": "Good Room"}]
        struck, per = M.match_wall(["Good Room"], pool, fake_search(cat))
        self.assertEqual(struck, {})
        self.assertEqual(per["Good Room"]["status"], "outside_pool")


class TestR5BrandContainment(unittest.TestCase):
    """Golden cases from the live K4 relabel on nyc-khruangbin (28 Oct): 3 false survivors before R5. In each, the
    AI's name resolves strongly to a branch OUTSIDE U, which used to switch containment off for its siblings in U."""
    CASES = [("Ippudo NY", "IPPUDO Hell's Kitchen", "IPPUDO NY"),
             ("Sant Ambroeus", "Sant Ambroeus W 4", "Sant Ambroeus Madison"),
             ("La Goulue", "Omar's at La Goulue", "La Goulue")]

    def test_live_false_survivors_are_struck(self):
        for raw, in_pool, outside in self.CASES:
            pool = [{"entity_id": "u", "name": in_pool}, {"entity_id": "other", "name": "Dante"}]
            cat = pool + [{"entity_id": "o", "name": outside}]
            struck, per = M.match_wall([raw], pool, fake_search(cat))
            self.assertIn("u", struck, "%s should strike %s" % (raw, in_pool))
            self.assertIn(("%s" % raw, "R5"), struck["u"])
            self.assertNotIn("other", struck)

    def test_weak_words_never_fire_alone(self):
        pool = [{"entity_id": i, "name": n} for i, n in (("1", "Little Owl"), ("2", "Rooftop at Pier 17"),
                                                          ("3", "The Bar Room"), ("4", "Bar Goto"))]
        for raw in ("Little", "The Rooftop", "Rooftop Bar", "The Bar", "Bar", "NY", "Brooklyn Bar"):
            self.assertEqual(M.PoolIndex(pool).r5(raw), [], raw)

    def test_position_start_or_after_at_only(self):
        pool = [{"entity_id": "a", "name": "Goulue Club"}, {"entity_id": "b", "name": "Le Petit La Goulue"},
                {"entity_id": "c", "name": "Bar at La Goulue"}]
        self.assertEqual(sorted(M.PoolIndex(pool).r5("La Goulue")), ["c"])


class TestK4Golden(unittest.TestCase):
    def test_zero_false_survivors(self):
        labels = load_labels()
        for city in ("nyc", "stl"):
            r = evaluate(city, labels[city])
            self.assertEqual(r["fn"], [], "false survivors in %s: %s" % (city, r["fn"]))


def report():
    labels = load_labels()
    n = sum(len(v) for v in labels.values())
    print("K4 offline matcher test over %d labelled names (%s)" % (n, ", ".join(
        "%s %d" % (k.upper(), len(v)) for k, v in labels.items())))
    missing = [x for c, v in labels.items() for x, _ in v if x not in (C.NYC if c == "nyc" else C.STL)]
    if missing:
        print("FIXTURE MISSING:", missing)
    ok_all = True
    tot = {"tp": 0, "struck": 0, "named": 0, "fn": 0}
    for city in ("nyc", "stl"):
        for use_search in (False, True):
            r = evaluate(city, labels[city], use_search)
            tag = "local + /search" if use_search else "local only"
            print("  %s [%s]: pool %d, named members %d, struck %d, false survivors %d, false strikes %d, precision %.1f%%" % (
                city.upper(), tag, r["pool"], r["named"], r["struck"], len(r["fn"]), len(r["fp"]), 100 * r["precision"]))
            if use_search:
                tot["tp"] += r["tp"]; tot["struck"] += r["struck"]; tot["named"] += r["named"]; tot["fn"] += len(r["fn"])
                if r["fn"]:
                    print("    FALSE SURVIVORS:", "; ".join(r["fn"]))
                if r["fp"]:
                    print("    false strikes (safe direction):", "; ".join(r["fp"]))
                cls = ", ".join("%s %d/%d" % (CLASSES[k], v[0], v[1]) for k, v in sorted(r["by_class"].items()))
                print("    recall by class:", cls)
                st = {}
                for raw, info in r["per"].items():
                    st[info["status"]] = st.get(info["status"], 0) + 1
                print("    name status:", ", ".join("%s %d" % kv for kv in sorted(st.items())))
    prec = tot["tp"] / tot["struck"] if tot["struck"] else 1
    gate1 = tot["fn"] == 0
    gate2 = prec >= 0.95
    print("K4 offline: false survivors %d (gate 0) %s; precision %.1f%% over %d strikes (gate >=95%%) %s" % (
        tot["fn"], "PASS" if gate1 else "FAIL", 100 * prec, tot["struck"], "PASS" if gate2 else "FAIL"))
    print("K4 offline overall:", "PASS" if gate1 and gate2 else ("PASS (hard gate) / precision FAIL" if gate1 else "FAIL"))
    print("Note: the pool here is a synthetic fixture (fixtures/matcher_catalog.py); the live K4 relabels the real pool.")
    return gate1


if __name__ == "__main__":
    ok = report()
    print()
    res = unittest.main(argv=[sys.argv[0], "-v"], exit=False).result
    sys.exit(0 if ok and res.wasSuccessful() else 1)
