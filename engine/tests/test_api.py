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
        # one ordering: every card scores at least as high as every reserve; every card has a for-you rank
        if r["reserves"]:
            self.assertGreaterEqual(min(c["score"] for c in r["picks"]), max(c["score"] for c in r["reserves"]))
            self.assertEqual([c["score"] for c in r["reserves"]], sorted([c["score"] for c in r["reserves"]], reverse=True))
        for c in r["picks"] + r["reserves"]:
            self.assertFalse(c["tied"])
            self.assertTrue(c["why"] and isinstance(c["fit_rank"], int))
            self.assertNotIn(" | ", c["name"])
            self.assertIn("because_detail", c)
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
        self.assertEqual(set(calls), {"pool", "rescore", "ids", "cap", "loves", "city", "total"})
        self.assertEqual(calls["total"], r["diag"]["qloo_calls"])
        self.assertEqual(calls["total"], sum(v for k, v in calls.items() if k != "total"))
        self.assertGreaterEqual(calls["loves"], 1)
        dish = len(E.CFG["DISH_OFFSETS"]) if E.CFG["DISH_POOL"] else 0          # the rib-tips dish sub-pool
        self.assertIn(calls["pool"], (4 + dish, 4 + dish + 2 * len(E.CFG["EXTRA_OFFSETS"])))   # 2 entity loves x offsets 0, 50 (+ extra pages when U is small)
        self.assertEqual(calls["cap"], 1)
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
        self.assertEqual((c["status"], c["city"]["slug"], c["city"]["radius_mi"]),
                         ("ok", "new-york", C.CITIES["nyc"]["radius_mi"]))
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


class TestWallCount(Tmp):
    VARIANTS = ["Ted Drewes", "Ted Drewes Frozen Custard", "Frozen custard at Ted Drewes",
                "Lemmons", "Lemmons Restaurant",
                "Sweetie Pie's", "Sweetie Pie’s", "Sweetie Pies", "Sweetie Pie's Upper Crust", "Sweetie Pie's"]
    DISTINCT = ["Jazz St. Louis", "Robbie's House of Jazz", "Bailey's Range", "Bailey's Smokehouse",
                "Tower Grove Park", "Tower Grove Tavern",
                "Pork steak and ribs at Salt + Smoke", "Pork steak and ribs BBQ at Pappy's Smokehouse"]

    def test_variants_merge_and_distinct_places_stay_apart(self):
        p = E.wall_places(self.VARIANTS + self.DISTINCT + ["Tower Grove"], {})
        self.assertEqual(len({p[n] for n in self.VARIANTS}), 3)                 # Ted Drewes, Lemmons, Sweetie Pie's
        self.assertEqual(len({p[n] for n in self.DISTINCT}), len(self.DISTINCT))
        self.assertEqual(p["Frozen custard at Ted Drewes"], p["Ted Drewes"])      # "X at Y" counts Y
        self.assertNotEqual(p["Jazz St. Louis"], p["Robbie's House of Jazz"])
        self.assertNotEqual(p["Tower Grove Park"], p["Tower Grove Tavern"])      # no bridge through "Tower Grove"

    def test_counts_wall_is_places_and_wall_names_is_strings(self):
        a = lambda names: {"provider": "t", "asked_at": "2026-10-28", "lane": "dated",  # noqa: E731
                           "names": [{"name": n} for n in names]}
        doc = {"walls": [{"city": "stl", "set": "city", "answers": [a(self.VARIANTS[:5]), a(self.VARIANTS[5:])]}]}
        p = os.path.join(self.dir, "w.json")
        with open(p, "w") as f:
            json.dump(doc, f)
        r = api.run_unsaid("St. Louis", CEDRIC, mode="fake", qloo=self.q(), walls_path=p, gemini=False,
                           street_check=False)
        self.assertEqual(r["counts"]["wall"], 3)
        self.assertEqual(r["diag"]["wall_names"], 8)     # distinct normalised strings (the two quote forms are one)
        self.assertTrue(all(w.get("place") for w in r["wall"]))

    def test_non_venue_is_dimmed_but_counted(self):
        venue = {"entity_id": "v", "tags": [{"id": "urn:tag:category:place:restaurant"}]}
        music = {"entity_id": "m", "tags": [{"id": "urn:tag:category:place:live_music_venue"}]}
        mall = {"entity_id": "x", "tags": [{"id": "urn:tag:category:place:restaurant"},
                                           {"id": "urn:tag:category:place:fast_food"}]}
        self.assertFalse(E.not_restaurant_or_bar(venue))
        self.assertTrue(E.not_restaurant_or_bar(music))
        self.assertTrue(E.not_restaurant_or_bar(mall))
        self.assertFalse(E.not_restaurant_or_bar({"entity_id": "u"}))   # tags unknown: never guess

        class CS:
            closed, busy, skipped, nonvenue = set(), set(), set(), {"m"}
        drops = {"ids": {"closed": [], "not_venue": ["x"]}}
        oc = E.name_outcome("The Pageant", {"status": "outside_pool", "ids": [], "resolved_id": "m"}, CS, None, drops)
        self.assertEqual(oc, ("dimmed", "not a restaurant or bar", "m"))
        idx = __import__("unsaid.matcher", fromlist=["PoolIndex"]).PoolIndex([{"entity_id": "x", "name": "Food Hall X"}])
        oc = E.name_outcome("Food Hall X", {"status": "not_found", "ids": []}, CS, idx, drops)
        self.assertEqual(oc[1], "not a restaurant or bar")
        self.assertEqual(len(set(E.wall_places(["The Pageant", "Gioia's Deli"], {"The Pageant": "m"}).values())), 2)


class TestStruckFitRanks(Tmp):
    def test_struck_fit_ranks_are_the_struck_members_ranks_under_the_rrf(self):
        q = self.q()
        r = api.run_unsaid("St. Louis", CEDRIC, mode="fake", qloo=q, gemini=False, street_check=False)
        sfr = r["diag"]["struck_fit_ranks"]
        self.assertTrue(sfr and sfr == sorted(sfr) and all(isinstance(x, int) and 1 <= x <= r["counts"]["U"] for x in sfr))
        self.assertEqual(len(set(sfr)), len(sfr))
        self.assertTrue(set(c["fit_rank"] for c in r["picks"] + r["reserves"]).isdisjoint(sfr), "cards are never struck")
        # strike the for-you top 3 on purpose: the UI line's condition then holds
        res = E.run(QL.Qloo(fake=True, cache_dir=self.dir), E.resolve_city(None, "St. Louis"),
                    [tuple(x) for x in CEDRIC], {"answers": []})
        top3 = sorted(res["_R"]["fit"], key=lambda i: res["_R"]["fit"][i])[:3]
        names = {e["entity_id"]: e["name"] for e in res["_U"]}
        wall = os.path.join(self.dir, "w.json")
        with open(wall, "w") as f:
            json.dump({"walls": [{"city": "stl", "set": "city", "answers": [
                {"provider": "t", "asked_at": "2026-10-28", "lane": "dated",
                 "names": [{"name": names[i]} for i in top3]}]}]}, f)
        r = api.run_unsaid("St. Louis", CEDRIC, mode="fake", qloo=self.q(), walls_path=wall, gemini=False,
                           street_check=False)
        self.assertTrue({1, 2, 3} <= set(r["diag"]["struck_fit_ranks"]))


class TestAllTiedLoveIsDead(Tmp):
    def test_a_love_tied_on_95pct_of_U_is_dead_and_leaves_the_tie_share(self):
        os.environ["FAKE_TIE_LOVES"] = "urn:tag:specialty_dish:place:rib_tips"   # live P11: rib tips 100% tied
        try:
            r = api.run_unsaid("St. Louis", CEDRIC, mode="fake", qloo=self.q(), gemini=False, street_check=False)
        finally:
            del os.environ["FAKE_TIE_LOVES"]
        self.assertAlmostEqual(r["diag"]["tie_by_love"]["Rib Tips"], 1.0)
        self.assertIn("dead_love:Rib Tips", r["flags"])
        self.assertNotIn("thin_taste", r["flags"])
        self.assertLess(r["diag"]["tie_share"], 0.30)          # live loves only
        rib = next(l for l in r["loves"] if l["label"] == "Rib Tips")
        self.assertTrue(rib["dead"] and rib["dead_reason"].startswith("ties"))
        self.assertEqual(rib["dead_line"], "Rib Tips doesn't change St. Louis restaurants much; ranked on the other two.")
        self.assertEqual(len(r["picks"]), 7)
        self.assertFalse(any(c["because"] == "Rib Tips" for c in r["picks"]))
        self.assertTrue(all(c["n_loves"] == 2 for c in r["picks"]))
        self.assertEqual(set(r["diag"]["tie_by_love"]), {l["label"] for l in r["loves"]})


class TestCardFront(Tmp):
    def test_what_line_says_what_the_place_is(self):
        t = lambda i, n: {"id": i, "name": n}  # noqa: E731
        e = {"tags": [t("urn:tag:amenities:place:restroom", "Restroom"), t("urn:tag:genre:place", "Place"),
                      t("urn:tag:payments:place:credit_cards", "Credit cards"),
                      t("urn:tag:accessibility:place:wheelchair_accessible_entrance", "Wheelchair accessible entrance"),
                      t("urn:tag:customer_identity:qloo:lgbtq_friendly", "Lgbtq+ friendly"),
                      t("urn:tag:time_of_day_fit:qloo:late_night", "Late night"),
                      t("urn:tag:cost_description:place:10_to_20", "$10 to $20"),
                      t("urn:tag:cuisine:qloo:american", "American"), t("urn:tag:cuisine:qloo:soul_food", "Soul food"),
                      t("urn:tag:category:place:bar", "Bar"), t("urn:tag:offerings:place:dancing", "Dancing"),
                      t("urn:tag:interests:qloo:live_music", "Live music")]}
        self.assertEqual(E.what_line(e), "soul food · live music")
        e2 = {"tags": [t("urn:tag:category:place:bar", "Bar"), t("urn:tag:interests:qloo:blues_music", "Blues music"),
                       t("urn:tag:amenities:place:restroom", "Restroom")]}
        self.assertEqual(E.what_line(e2), "bar · blues")
        e3 = {"tags": [t("urn:tag:category:place:southern_restaurant_us", "Southern restaurant us"),
                       t("urn:tag:cuisine:qloo:southern", "Southern"), t("urn:tag:category:place:sports_bar", "Sports bar"),
                       t("urn:tag:category:place:bar", "Bar")]}
        self.assertEqual(E.what_line(e3), "southern · sports bar")   # deduped: "southern restaurant us" == "southern"
        self.assertEqual(E.what_line({"tags": [t("urn:tag:amenities:place:restroom", "Restroom")]}), "")

    def test_neighbourhood_falls_back_to_the_nearest_centroid_within_1_5_mi(self):
        e = {"properties": {}, "location": {"lat": 38.7400, "lon": -90.2700}}
        near = [("Jennings", 38.7450, -90.2650), ("Far", 38.90, -90.20)]
        self.assertEqual(E.hood_of(e, [("osm", near)]), ("Jennings", "osm"))
        self.assertEqual(E.hood_of(e, [("osm", [("Far", 38.90, -90.20)])]), ("", None))
        self.assertEqual(E.hood_of(dict(e, properties={"neighborhood": "The Ville"}), [("osm", near)]), ("The Ville", "qloo"))
        self.assertEqual(E.hood_of(e, [("osm", []), ("pool", near)]), ("Jennings", "pool"))
        r = api.run_unsaid("St. Louis", CEDRIC, mode="fake", qloo=self.q())
        self.assertTrue(all(c["neighbourhood_src"] in ("qloo", "osm", "pool", None) for c in r["picks"]))

    def test_last_seen_check(self):
        from unsaid import lastseen as LS
        LS.DIR = os.path.join(self.dir, "lastseen")
        calls = []

        def fake_urllib(url, method):
            calls.append((url, method))
            return (200, None) if "ok.example" in url else (404, None)
        real, LS._urllib = LS._urllib, fake_urllib
        try:
            P = lambda **kw: {"properties": dict({"hours": {"Mon": "9-5"}, "address": "1 Main St"}, **kw)}  # noqa
            self.assertEqual(LS.check(P())[0], True)
            self.assertEqual(LS.check(P())[1]["how"], "hours only")
            ok, info = LS.check(P(website="https://ok.example/"))
            self.assertTrue(ok and info["how"] == "hours + site HTTP 200")
            ok, info = LS.check(P(website="https://gone.example/"))
            self.assertFalse(ok)
            self.assertIn("404", info["how"])
            self.assertEqual([m for u, m in calls if "gone" in u], ["HEAD", "GET"])     # HEAD, then GET
            n = len(calls)
            LS.check(P(website="https://ok.example/"))
            self.assertEqual(len(calls), n, "cached 24 h")
            self.assertFalse(LS.check(P(hours=None))[0])
            self.assertFalse(LS.check(P(address="12 Elm St (CLOSED)"))[0])
        finally:
            LS._urllib = real

    def test_a_card_failing_last_seen_is_struck_and_the_next_rises(self):
        first = api.run_unsaid("St. Louis", CEDRIC, mode="fake", qloo=self.q(), gemini=False, street_check=False)
        victim = first["picks"][0]["id"]
        events = []

        def hook(e):
            if e["entity_id"] == victim:
                return False, {"checked_at": "t", "how": "failed: site HTTP 404"}
            return True, {"checked_at": "t", "how": "hours only"}
        r = api.run_unsaid("St. Louis", CEDRIC, mode="fake", qloo=self.q(), gemini=False, street_check=False,
                           last_seen=hook, on_event=events.append)
        self.assertNotIn(victim, [c["id"] for c in r["picks"] + r["reserves"]])
        self.assertEqual(len(r["picks"]), 7)
        self.assertEqual(r["picks"][-1]["id"] if False else len(r["reserves"]), 3)
        self.assertTrue(all(c["last_seen"] == {"checked_at": "t", "how": "hours only"} for c in r["picks"]))
        self.assertTrue(any(e["type"] == "strike" and e.get("reason") == "last seen: failed" and e["qloo_id"] == victim
                            for e in events))
        self.assertEqual(r["diag"]["last_seen_dropped"][0]["id"], victim)


class TestCallsAgree(Tmp):
    def test_typed_loves_and_resolved_chips_count_the_same_calls(self):
        from unsaid import cli
        typed = api.run_unsaid("St. Louis", CEDRIC, mode="fake", qloo=self.q(), gemini=False, street_check=False)
        q = self.q()
        ch, _ = cli.chips(q, [tuple(x) for x in CEDRIC])       # resolved before the run, as precompute does
        self.assertTrue(all("c2_calls" in c for c in ch))
        chips = api.run_unsaid("St. Louis", ch, mode="fake", qloo=q, gemini=False, street_check=False)
        self.assertEqual(typed["diag"]["calls"], chips["diag"]["calls"])
        self.assertEqual(typed["diag"]["qloo_calls"], chips["diag"]["qloo_calls"])
        self.assertEqual([c["id"] for c in typed["picks"]], [c["id"] for c in chips["picks"]])
        r = api.resolve_love("rib tips", "tag", mode="fake", qloo=self.q())
        self.assertEqual(r["chip"]["c2_calls"], 1)


class TestLiveLaneNeverGatesCards(Tmp):
    def test_cards_emit_before_a_slow_live_answer_then_the_named_card_burns(self):
        import time as _t
        base = api.run_unsaid("St. Louis", CEDRIC, mode="fake", qloo=self.q(), gemini=False, street_check=False)
        victim = base["picks"][2]
        marks = {}

        def slow_gemini(prompt):
            _t.sleep(0.5)
            marks["answered"] = _t.monotonic()
            return {"provider": "gemini", "model": "fake-slow", "asked_at": "2026-10-28T12:00:00Z",
                    "names": [{"name": victim["name"]}], "raw": "Try %s." % victim["name"]}
        events = []

        def on(e):
            events.append((e["type"], _t.monotonic(), e))
        r = api.run_unsaid("St. Louis", CEDRIC, mode="fake", qloo=self.q(), gemini=slow_gemini, street_check=False,
                           on_event=on)
        cards = [t for k, t, e in events if k == "card"]
        self.assertEqual(len(cards), 7)
        self.assertLess(max(cards), marks["answered"], "every card is out before the live answer arrives")
        burns = [e for k, t, e in events if k == "burn"]
        self.assertEqual([b["card_id"] for b in burns], [victim["id"]])
        self.assertEqual(burns[0]["by"], "gemini (live)")
        self.assertIsNotNone(burns[0]["risen"])
        types = [k for k, t, e in events]
        self.assertLess(types.index("card"), types.index("burn"))
        self.assertNotIn(victim["id"], [c["id"] for c in r["picks"] + r["reserves"]])
        self.assertEqual(len(r["picks"]), 7)
        self.assertEqual(r["burn"]["burned"][0]["by"], "gemini (live)")
        self.assertIn(victim["name"], [w["name"] for w in r["wall"] if w["lane"] == "live"])
        self.assertEqual([c["id"] for c in r["picks"]],
                         sorted([c["id"] for c in r["picks"]], key=lambda i: next(c["fit_rank"] for c in r["picks"]
                                                                                  if c["id"] == i)))

    def test_a_live_answer_past_the_budget_leaves_the_dated_cards(self):
        import time as _t
        old = api.LIVE_BUDGET_S
        api.LIVE_BUDGET_S = 0.2
        try:
            def too_slow(prompt):
                _t.sleep(1.0)
                return {"names": [{"name": "Anything"}]}
            r = api.run_unsaid("St. Louis", CEDRIC, mode="fake", qloo=self.q(), gemini=too_slow, street_check=False)
        finally:
            api.LIVE_BUDGET_S = old
        self.assertEqual(len(r["picks"]), 7)
        self.assertEqual(r["burn"]["burned"], [])
        self.assertIn("live lane: TimeoutError", r["diag"]["lanes_failed"])


class TestDishLove(unittest.TestCase):
    def test_tagged_places_rank_first_and_the_dish_is_not_a_tie(self):
        from unsaid import stats as ST
        ids = ["a", "b", "c", "d"]
        aff = {"a": QL.DEFAULT_AFFINITY, "b": QL.DEFAULT_AFFINITY, "c": 0.9, "d": QL.DEFAULT_AFFINITY}
        tagged = {"b", "d"}
        informative = {i: aff[i] for i in ids if not QL.is_default_affinity(aff[i])}
        score = {i: (10.0 + informative.get(i, 0.0)) if i in tagged else informative.get(i, -1.0) for i in ids}
        r = ST.rank(score)
        self.assertEqual(sorted(ids, key=lambda i: r[i])[:2], ["b", "d"])     # the places that carry the dish
        self.assertLess(r["c"], r["a"])                                        # then what Qloo scored


class TestReverseCheckEvidence(unittest.TestCase):
    """Golden cases from E's held-out audit (30 Oct): prose words no longer strike a card; a real mention still does."""

    def hit(self, card, raw, names=(), stop=()):
        ri = E.reverse_index([{"raw": raw, "names": [{"name": n} for n in names]}], stop=set(stop))
        return E.reverse_hit(card, ri) is not None

    def test_prose_words_are_not_evidence(self):
        self.assertFalse(self.hit("Bar:PM", "Happy hour runs from 5 to 6 pm on weekdays."))
        self.assertFalse(self.hit("september", "Go in September, when the patio is open."))
        self.assertFalse(self.hit("Harlem Breakfast Club", "In Harlem, get the breakfast sandwich at a bodega.",
                                  stop={"harlem"}))
        self.assertFalse(self.hit("Cardinals Nation", "Watch the Cardinals game anywhere; the whole nation does."))
        self.assertFalse(self.hit("Flor de Mayo", "Cinco de Mayo specials, then a flor de sal tasting menu."))
        self.assertFalse(self.hit("Creature's Rooftop", "Any rooftop bar works; creature comforts at a diner later."))

    def test_real_mentions_still_strike(self):
        self.assertTrue(self.hit("Bar:PM", "Try Bar:PM in the Grove for late cocktails."))
        self.assertTrue(self.hit("Bar:PM", "[]", names=["Bar PM"]))
        self.assertTrue(self.hit("Harlem Breakfast Club", "The Harlem Breakfast Club does a great brunch.", stop={"harlem"}))
        self.assertTrue(self.hit("Cardinals Nation", "Before the game, Cardinals Nation at Ballpark Village is packed."))
        self.assertTrue(self.hit("Freda", "Freda in Greenpoint has the best natural wine list."))
        self.assertTrue(self.hit("The Spot Sports Bar", "The Spot sports bar on St Charles Rock Rd is a classic."))


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
        self.assertEqual((QL.BUCKET.rate, QL.BUCKET.capacity), (QL.RATE, float(QL.BURST)))
        p = C.location_params(E.resolve_city(None, "St. Louis"))
        self.assertEqual(p, {"filter.location": "POINT(-90.1994 38.627)",
                             "filter.location.radius": C.CITIES["stl"]["radius_m"]})   # R is a set point (§4 widen R)
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


class TestCardLines(unittest.TestCase):
    def test_display_name_keeps_apostrophe_s(self):
        self.assertEqual(E.display_name("Jody B'"), "Jody B's")              # Qloo's cut possessive (STL rib tips)
        self.assertEqual(E.display_name("Jody B's"), "Jody B's")
        self.assertEqual(E.display_name("Pappy's Smokehouse | Midtown STL"), "Pappy's Smokehouse")
        self.assertEqual(E.display_name("The Brothers'"), "The Brothers'")   # plural possessive stays
        self.assertEqual(E.display_name("Rock 'n' Roll"), "Rock 'n' Roll")

    def test_why_line_names_the_bar_the_card_cleared(self):
        ids = ["a", "b", "c", "d", "e"]
        fit = {"a": 4, "b": 5, "c": 1, "d": 2, "e": 3}          # for you
        pop = {"a": 1, "b": 2, "c": 3, "d": 4, "e": 5}          # for anyone (popularity)
        # popularity is the bar: c is #3 by popularity, both more popular places fit you less
        self.assertEqual(E.why_line("c", fit, pop, ids, {}, {}, False),
                         "fits you better than all 2 more popular places")
        self.assertEqual(E.why_line("e", fit, pop, ids, {}, {}, False),
                         "fits you better than 2 of the 4 more popular places")
        # everyone's fit is the bar (its percentile is above popularity's): the prior's own counts
        self.assertEqual(E.why_line("d", fit, pop, ids, {"d": 0.9}, {"d": (1, 9)}, False),
                         "only 1 of 9 other tastes put it in their top 30%")
        self.assertEqual(E.why_line("d", fit, pop, ids, {"d": 0.9}, {"d": (5, 9)}, False),
                         "5 of 9 other tastes put it in their top 30%")
        self.assertEqual(E.why_line("d", fit, pop, ids, {"d": 0.9}, {"d": (0, 1)}, False),
                         "not in the top 30% of the one other taste that rates it")
        self.assertTrue(E.why_line("d", fit, pop, ids, {}, {}, True).startswith("fits you, outside the 20%"))
        for i in ids:
            self.assertLessEqual(len(E.why_line(i, fit, pop, ids, {}, {}, False)), 60)


if __name__ == "__main__":
    res = unittest.main(argv=[sys.argv[0], "-v"], exit=False).result
    ok = res.wasSuccessful()
    print("API contract tests: %d run, %d failed -> %s [FAKE]" % (res.testsRun, len(res.failures) + len(res.errors),
                                                                 "PASS" if ok else "FAIL"))
    sys.exit(0 if ok else 1)
