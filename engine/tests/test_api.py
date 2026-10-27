"""Offline tests for the engine API (CONTRACT.md) and the client rules (UNSAID.md §3.1-3.3, §3.5). Fake mode only.
  python3 -I tests/test_api.py"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, KIT)

from unsaid import api, cities as C, engine as E, qloo as QL  # noqa: E402

CEDRIC = [["The Original Kings of Comedy", "movie"], ["Frankie Beverly & Maze", "artist"], ["rib tips", "tag"]]
RESULT_KEYS = {"status", "flags", "loves", "city", "picks", "reserves", "wall", "counts", "burn", "diag"}
CARD_KEYS = {"id", "name", "what", "because", "fit_rank", "any_rank", "U", "rating", "open", "neighbourhood", "address",
             "lat", "lon", "url", "holds", "n_loves", "tied", "never_said"}
WALL_KEYS = {"name", "norm", "provider", "model", "phrasing_id", "phrasing", "asked_at", "lane", "outcome", "reason",
             "qloo_id"}
DIAG_KEYS = {"qloo_calls", "rho_tp", "rho_res", "cap_keep", "cap_shared", "engine_v", "as_of", "trace_url"}
ORDER = ["status", "wall_name", "pool", "strike", "card", "burn", "done"]


class Tmp(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="unsaid-test-")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def q(self):
        return QL.Qloo(fake=True, cache_dir=self.dir)


class TestRunUnsaid(Tmp):
    def test_streams_in_timeline_order_and_returns_contract_shape(self):
        events = []
        r = api.run_unsaid("St. Louis", CEDRIC, mode="fake", on_event=events.append, qloo=self.q(), set_id="cedric")
        json.dumps(events)          # every event is one NDJSON line
        json.dumps(r)
        types = [e["type"] for e in events]
        firsts = [t for t in ORDER if t in types]
        self.assertEqual(firsts, sorted(firsts, key=lambda t: types.index(t)), "first-seen order follows §3.4")
        self.assertEqual(types[0], "status")
        self.assertEqual(types[-1], "done")
        self.assertIn("calls", types)
        self.assertLess(types.index("wall_name"), types.index("pool"), "the dated wall streams before Qloo")
        self.assertEqual(events[-1]["result"], r)
        self.assertTrue(RESULT_KEYS <= set(r))
        self.assertIn(r["status"], ("ok", "empty_few", "partial"))
        self.assertIn("fake", r["flags"])
        self.assertEqual(len(r["picks"]), 7)
        for c in r["picks"] + r["reserves"]:
            self.assertTrue(CARD_KEYS <= set(c), CARD_KEYS - set(c))
            self.assertTrue({"asks", "city_asks", "street_asks", "as_of"} <= set(c["never_said"]))
            self.assertGreaterEqual(c["rating"], 4.3 - 1e-4)
            self.assertTrue(c["open"])
            self.assertIn(c["because"], [l["label"] for l in r["loves"]])
        fits = [c["fit_rank"] for c in r["picks"]]
        self.assertEqual(fits, sorted(fits), "displayed in for-you order")
        for w in r["wall"]:
            self.assertTrue(WALL_KEYS <= set(w))
            self.assertIn(w["outcome"], ("struck", "dimmed"))
        self.assertTrue(DIAG_KEYS <= set(r["diag"]))
        # CONTRACT "UI additions"
        labels = [l["label"] for l in r["loves"]]
        for c in r["picks"] + r["reserves"]:
            self.assertIn("holds_without", c)
            self.assertTrue(c["holds_without"] is None or c["holds_without"] in labels)
            if c["holds"] == c["n_loves"]:
                self.assertIsNone(c["holds_without"])
            self.assertTrue(c["request_urls"] and all(u.startswith("https://hackathon.api.qloo.com/v2/insights?")
                                                      for u in c["request_urls"]))
            self.assertTrue(any(c["id"] in u for u in c["request_urls"]), "its C6' chunk carries its ID")
            self.assertFalse(any("key" in u.lower() for u in c["request_urls"]))
            self.assertNotIn("_pool_urls", c)
        self.assertTrue(any(c["holds_without"] for c in r["picks"] + r["reserves"]), "a 2-of-3 card names its love")
        calls = r["diag"]["calls"]
        self.assertEqual(set(calls), {"pool", "rescore", "ids", "cap", "total"})
        self.assertEqual(calls["total"], r["diag"]["qloo_calls"])
        self.assertEqual((calls["pool"], calls["cap"]), (4, 1))         # 2 entity loves x offsets 0, 50; one CAP
        self.assertGreaterEqual(calls["rescore"], 3)
        self.assertLessEqual(calls["pool"] + calls["rescore"] + calls["ids"] + calls["cap"], calls["total"])
        self.assertEqual(r["diag"]["obscure_names"], [x["name"] for x in r["diag"]["obscure"]])
        self.assertEqual(r["diag"]["known_names"], [x["name"] for x in r["diag"]["known"]])
        self.assertTrue(all(isinstance(n, str) for n in r["diag"]["obscure_names"] + r["diag"]["known_names"]))
        cards = [e for e in events if e["type"] == "card"]
        self.assertTrue(cards and all("request_urls" in e and "_pool_urls" not in e for e in cards))
        self.assertTrue({"closed", "below_43", "outside_R", "not_venue"} <= set(r["counts"]["floor"]))
        self.assertTrue(set(r["city"]) >= {"id", "name", "slug", "center", "radius_mi"})
        lon, lat = r["city"]["center"]
        self.assertLess(lon, 0)      # [lon, lat]

    def test_no_explainability_shares_anywhere(self):
        r = api.run_unsaid("St. Louis", CEDRIC, mode="fake", qloo=self.q())
        blob = json.dumps(r).lower()
        self.assertNotIn("mostly because", blob)
        self.assertNotIn('"share"', blob)

    def test_needs_input_city_and_love(self):
        r = api.run_unsaid("Richmond", CEDRIC, mode="fake", qloo=self.q())
        self.assertEqual(r["status"], "needs_input")
        self.assertEqual(r["needs"][0]["field"], "city")
        r = api.run_unsaid("St. Louis", [["Joe Turner's Come and Gone", None], ["Al Green", "artist"]],
                           mode="fake", qloo=self.q())
        self.assertEqual(r["status"], "needs_input")
        self.assertIn("fake", r["flags"])

    def test_resolvers(self):
        r = api.resolve_love("rib tips", "tag", mode="fake", qloo=self.q())
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["chip"]["kind"], "tag")
        self.assertEqual(api.resolve_love("zzqx unknown", "tag", mode="fake", qloo=self.q())["status"], "miss")
        c = api.resolve_city("Brooklyn", mode="fake", qloo=self.q())
        self.assertEqual((c["status"], c["city"]["slug"], c["city"]["radius_mi"]), ("ok", "new-york", 8))
        self.assertEqual(api.resolve_city("Richmond", mode="fake", qloo=self.q())["status"], "needs_input")

    def test_dead_love_vibe_and_rho(self):
        r = api.run_unsaid("St. Louis", [["Taylor Swift", "artist"], ["Ted Lasso", "tv_show"], ["Starbucks", "brand"]],
                           mode="fake", qloo=self.q())
        self.assertIn("dead_love:Starbucks", r["flags"])
        dead = [l for l in r["loves"] if l["dead"]]
        self.assertTrue(dead and "ranked on the other two" in dead[0]["dead_line"])
        q = self.q()
        r = api.run_unsaid("St. Louis", [["Al Green", "artist"], ["Barbershop", "movie"], ["cozy", "tag"]],
                           mode="fake", qloo=q)
        self.assertIn("dead_love:Cozy", r["flags"])
        self.assertFalse([t for t in q.trace if "/v2/insights" in t["url"] and "vibe" in t["url"]],
                         "a vibe tag is dead on arrival: no call")

    def test_degraded_when_qloo_fails(self):
        q = self.q()

        class Down:
            places = []

            def get(self, url):
                return 503, "{}", {}
        q.transport = Down()
        r = api.run_unsaid("St. Louis", [{"id": "X", "label": "X", "kind": "entity", "type": "urn:entity:artist"}],
                           mode="fake", qloo=q, gemini=False, street_check=False)
        self.assertEqual(r["status"], "degraded")


class TestSetsAndWalls(Tmp):
    def test_sets_from_data_files_and_aliases(self):
        from unsaid import seeds as SD
        self.assertEqual(SD.resolve("stl", "cedric"), "stl-cedric")
        self.assertEqual(SD.resolve("stl", "jason"), "stl-jason")
        self.assertEqual(SD.resolve("nyc", "A"), "nyc-khruangbin")
        self.assertTrue(SD.same("cedric", "stl-cedric"))
        self.assertEqual(SD.get("stl", "cedric"), SD.get("stl", "stl-cedric"))
        self.assertTrue(SD.SOURCE.endswith((".json", "FALLBACK_SETS")))

    def test_taste_joins_by_id_and_by_loves(self):
        from unsaid import walls as W
        a = lambda n: {"provider": "t", "asked_at": "2026-10-28", "lane": "dated", "names": [{"name": n}]}  # noqa
        doc = {"walls": [{"city": "stl", "set": "city", "answers": [a("Gioia's Deli")]},
                         {"city": "stl", "set": "stl-cedric", "loves": ["Frankie Beverly & Maze",
                          "The Original Kings of Comedy", "rib tips"], "answers": [a("Smoki O's")]},
                         {"city": "stl", "set": "stl-other", "loves": ["rib tips", "Al Green", "Barbershop"],
                          "answers": [a("Roper's Ribs")]}]}
        p = os.path.join(self.dir, "walls.json")
        with open(p, "w") as f:
            json.dump(doc, f)
        names = lambda w: sorted(W.names(w))  # noqa: E731
        self.assertEqual(names(W.wall_for("stl", "cedric", p)), ["Gioia's Deli", "Smoki O's"])
        self.assertEqual(names(W.wall_for("stl", None, p, loves=["Barbershop", "AL GREEN", "Rib Tips"])),
                         ["Gioia's Deli", "Roper's Ribs"])
        r = api.run_unsaid("St. Louis", [["Al Green", "artist"], ["Barbershop", "movie"], ["rib tips", "tag"]],
                           mode="fake", qloo=self.q(), walls_path=p, gemini=False, street_check=False)
        self.assertIn("Roper's Ribs", [w["name"] for w in r["wall"]])

    def test_partial_spearman(self):
        from unsaid import stats as ST
        ids = list(range(40))
        c = {i: i for i in ids}
        a = {i: i + (7 if i % 2 else -7) for i in ids}
        b = {i: i + (5 if i % 2 else -5) for i in ids}
        self.assertGreater(ST.spearman(a, b), 0.9)
        pr = ST.partial_spearman(a, b, c)
        self.assertTrue(-1.0001 <= pr <= 1.0001 and pr > 0.5)   # shared +/- pattern survives holding c fixed
        self.assertNotEqual(ST.partial_spearman(a, {i: -i for i in ids}, c),
                            ST.partial_spearman(a, {i: -i for i in ids}, c))   # b == -c: degenerate -> nan
        r = api.run_unsaid("St. Louis", CEDRIC, mode="fake", qloo=self.q())
        self.assertIsNone(r["diag"]["rho_res"])          # fake no-signal order == popularity -> undefined
        self.assertEqual(r["diag"]["rho_res_note"], "RHO_RES undefined (base = popularity)")
        self.assertIn("not_venue_music", r["counts"]["floor"])


class TestDeadline(Tmp):
    def test_hard_cap_degrades(self):
        events = []
        r = api.run_unsaid("St. Louis", CEDRIC, mode="fake", qloo=self.q(), deadline_s=0.0, on_event=events.append)
        self.assertEqual(r["status"], "degraded")
        self.assertEqual(events[-1]["type"], "done")


class TestClientRules(Tmp):
    def test_never_send(self):
        q = self.q()
        bad = [{"filter.type": E.PLACE, "signal.location.query": "x"},
               {"filter.type": E.PLACE, "filter.location.query": "Brooklyn"},
               {"filter.type": E.PLACE, "filter.external.tripadvisor.rating.min": 4},
               {"filter.type": E.PLACE, "filter.external.resy.rating.min": 4},
               {"filter.type": E.PLACE, "signal.interests.tags": "urn:tag:x"},                       # tag in discovery
               {"filter.type": E.PLACE, "signal.interests.tags": "t", "signal.interests.entities": "e",
                "filter.results.entities": "a"},                                                     # both in one call
               {"filter.type": E.PLACE, "bias.trends": "high"}]
        for p in bad:
            with self.assertRaises(QL.NeverSend, msg=p):
                q.insights(p)
        self.assertEqual(q.calls["network"], 0)
        q.insights({"filter.type": E.PLACE, "filter.location": "POINT(-90.1994 38.627)"})
        self.assertIn("bias.trends=off", q.trace[-1]["url"])

    def test_cache_key_is_path_and_query_only(self):
        os.environ["QLOO_API_KEY"] = "sekrit-key-123456"
        try:
            q = self.q()
            q.fake = False         # the live key derivation
            k = q.cache_key("/search", "query=x&take=5")
            self.assertEqual(k, hashlib.sha256(b"/search?query=x&take=5").hexdigest())
            self.assertNotIn("sekrit", QL.redact("https://h/x?api_key=sekrit-key-123456"))
        finally:
            del os.environ["QLOO_API_KEY"]

    def test_bucket_and_point(self):
        self.assertEqual((QL.BUCKET.rate, QL.BUCKET.capacity), (3.0, 5.0))
        p = C.location_params(E.resolve_city(None, "St. Louis"))
        self.assertEqual(p, {"filter.location": "POINT(-90.1994 38.627)", "filter.location.radius": 16093})
        la = C.location_params(E.resolve_city(None, "Los Angeles"))
        self.assertEqual(la["filter.location.radius"], 24140)
        self.assertTrue(la["filter.location"].startswith("POINT(-118"))

    def test_floor_float32_and_allowlist(self):
        city = E.resolve_city(None, "St. Louis")
        mk = lambda r, tags=(), closed=False: {"entity_id": str(r) + str(tags), "name": "x", "properties": {  # noqa
            "business_rating": r, "is_closed": closed}, "location": {"lat": 38.63, "lon": -90.2},
            "tags": [{"id": t} for t in tags]}
        U, d = E.floor([mk(4.2999997), mk(4.1999998), mk(4.6, ["urn:tag:category:place:fast_food"]),
                        mk(4.6, closed=True)], city)
        self.assertEqual(len(U), 1)
        self.assertEqual((d["below_43"], d["not_venue"], d["closed"]), (1, 1, 1))

    def test_tie_guard_value(self):
        self.assertTrue(QL.is_default_affinity(0.7649962877984056))
        self.assertTrue(QL.is_default_affinity(0.7649970))
        self.assertFalse(QL.is_default_affinity(0.7660))

    def test_quota_guard(self):
        h = lambda rem: {"X-RateLimit-Limit-Month": "10000", "X-RateLimit-Remaining-Month": rem,  # noqa: E731
                         "X-Fake-RateLimit-Limit-Month": "10000", "X-Fake-RateLimit-Remaining-Month": rem}
        QL.update_quota(h("1400"), fake=True)     # 86% of the month used -> limited
        self.assertTrue(QL.quota_state()["limited"])
        QL.update_quota(h("9000"), fake=True)
        self.assertFalse(QL.quota_state()["limited"])

    def test_429_is_never_not_found(self):
        q = self.q()

        class Busy:
            def get(self, url):
                return 429, "{}", {"Retry-After": "0"}
        q.transport = Busy()
        with self.assertRaises(QL.QlooError) as cm:
            q.search("Pappy's Smokehouse")
        self.assertTrue(cm.exception.busy)
        city = E.resolve_city(None, "St. Louis")
        U = [{"entity_id": "u1", "name": "Pappy's Kitchen"}]
        _, per, cs = E.strike(q, city, U, ["Pappy's Smokehouse"])
        oc = E.name_outcome("Pappy's Smokehouse", per["Pappy's Smokehouse"], cs, None,
                            {"ids": {"closed": []}})
        self.assertNotEqual(oc[1], "not found in Qloo")


if __name__ == "__main__":
    res = unittest.main(argv=[sys.argv[0], "-v"], exit=False).result
    ok = res.wasSuccessful()
    print("API contract tests: %d run, %d failed -> %s [FAKE]" % (res.testsRun, len(res.failures) + len(res.errors),
                                                                 "PASS" if ok else "FAIL"))
    sys.exit(0 if ok else 1)
