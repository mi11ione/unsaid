"""Offline tests for the engine API (CONTRACT.md) and the client rules (UNSAID.md §3.1-3.3, §3.5). Fake mode only.
  python3 -I tests/test_api.py"""
import collections
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
        # one ordering, balanced (29 Oct): no love credits more than 3 cards, each live love credits one when it can;
        # a reserve outscores no card of a love below the cap; reserves in score order
        credits = collections.Counter(c["because"] for c in r["picks"])
        live = [l["label"] for l in r["loves"] if not l.get("dead")]
        if all(credits[x] for x in live):          # a love that can credit nothing lets the others fill by score
            self.assertLessEqual(max(credits.values()), E.CFG["LOVE_CAP"])
        else:
            self.assertEqual(sum(credits.values()), E.CFG["N_CARDS"])
        self.assertEqual(r["diag"]["credits"], dict(credits))
        if r["reserves"]:
            for x in r["reserves"]:
                under = [c["score"] for c in r["picks"] if credits[c["because"]] < E.CFG["LOVE_CAP"]]
                if credits[x["because"]] < E.CFG["LOVE_CAP"] and under:
                    self.assertGreaterEqual(min(under), x["score"])
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
        self.assertEqual(r["diag"]["wall_names"], 7)     # distinct normalised strings (Sweetie Pie's / Pie’s / Pies are one)
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
                _t.sleep(10.0)    # far past the budget even on a slow run (a daemon thread: never waited for)
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
        # the anchor panel's tastes are samples from Qloo, not people
        line = E.why_line("d", fit, pop, ids, {"d": 0.9}, {"d": (12, 97)}, False, "sample tastes on Qloo")
        self.assertEqual(line, "only 12 of 97 sample tastes on Qloo put it in their top 30%")
        self.assertLessEqual(len(line), 60)

    def test_card_quality_judge3(self):
        self.assertEqual(E.card_name("september"), "September")
        self.assertEqual(E.card_name("Marshas Ltd"), "Marshas")
        self.assertEqual(E.card_name("Guys With The Fries Ride LLC"), "Guys With The Fries Ride")
        self.assertEqual(E.card_name("Bar Laika by e-flux"), "Bar Laika by e-flux")     # mixed case stays
        tag = lambda tid, name: {"id": tid, "name": name}  # noqa: E731
        bar = [tag("urn:tag:category:place:bar", "Bar"), tag("urn:tag:category:place:restaurant", "Restaurant")]
        kitchen = {"tags": bar + [tag("urn:tag:category:place:shared_use_commercial_kitchen", "Shared use commercial kitchen")]}
        self.assertIsNotNone(E.excluded_kind(kitchen))
        deliv = [tag("urn:tag:category:place:delivery_restaurant", "Delivery restaurant")]
        self.assertIsNotNone(E.excluded_kind({"tags": bar + deliv}))                          # delivery only
        dine = [tag("urn:tag:service_options:place:dine_in", "Dine in")]
        self.assertIsNone(E.excluded_kind({"tags": bar + deliv + dine}))                     # The Flower Shop stays
        what = E.what_line({"tags": bar + deliv + dine + [tag("urn:tag:cuisine:qloo:seafood", "Seafood"),
                                                          tag("urn:tag:offerings:place:happy_hour", "Happy hour"),
                                                          tag("urn:tag:cuisine:qloo:burgers", "Burgers")]})
        self.assertNotIn("delivery", what)
        self.assertNotIn("happy hour", what)
        r = api.run_unsaid("St. Louis", CEDRIC, mode="fake", qloo=QL.Qloo(fake=True, cache_dir=tempfile.mkdtemp()),
                           gemini=False, street_check=False)
        for c in r["picks"] + r["reserves"]:
            self.assertIsNone(c["because_detail"])              # 30 Oct: no generated "like the places X fans" line
            self.assertTrue(c["because"])                       # the card states only the love
            self.assertIsNotNone(c["distance_mi"])
        self.assertLessEqual(r["counts"]["named_food_count"], r["counts"]["wall"])

    def test_rich_card_fields(self):
        e = {"properties": {
            "short_description": "Casual bar on Dr. Martin Luther King Dr. in North St. Louis. Dancing on Fridays.",
            "price_level": 2, "image": {"url": "https://images.qloo.com/i/x.jpg"},
            "keywords": [{"name": "atmosphere"}, {"name": "dive bar"}, {"name": "rib tips"}, {"name": "security"},
                         {"name": "peach cobbler"}, {"name": "party"}]}}
        self.assertEqual(E.blurb_line(e), "Casual bar on Dr. Martin Luther King Dr. in North St. Louis")
        self.assertEqual(E.price_line(e), "$$")
        self.assertEqual(E.image_url(e), "https://images.qloo.com/i/x.jpg")
        vocab = {"rib tips", "peach cobbler", "dive bar"}
        self.assertEqual(E.order_line(e, vocab), ["rib tips", "peach cobbler"])     # no venue kind, no stoplist word
        e["properties"]["specialty_dishes"] = [{"name": "Peach Cobbler"}]
        self.assertEqual(E.order_line(e, vocab), ["peach cobbler", "rib tips"])     # specialty dishes first, topped up
        e2 = {"properties": {"cuisine_description": "The menu features standout items like tender rib tips, pork "
                             "steaks, honey hot wings and gourmet cheeseburgers, alongside beer and cocktails.",
                             "keywords": [{"name": "atmosphere"}]}}
        self.assertEqual(E.order_line(e2, {"rib tips", "pork steak", "honey hot wings", "cheeseburger", "beer"}),
                         ["rib tips", "pork steaks", "honey hot wings"])
        u = {"properties": {"unique_selling_points": "The establishment is distinguished by its signature house-made "
                            "sourdough tartines and handcrafted coffee. More text.", "short_description": "x."}}
        self.assertEqual(E.blurb_line(u), "Signature house-made sourdough tartines and handcrafted coffee")
        u["properties"]["unique_selling_points"] = "Famous for their tender, smoky rib tips and highly seasoned burgers."
        self.assertEqual(E.blurb_line(u), "Famous for their tender, smoky rib tips and highly seasoned burgers")
        self.assertEqual(E.order_line({"properties": {"keywords": [{"name": "crowd"}]}}, vocab), [])
        long = {"properties": {"short_description": "word " * 40}}
        self.assertIsNone(E.blurb_line(long))                 # never cut mid-thought; no kind tag -> no line
        # 30 Oct fallback: first complete clause <= 12 words, else "<kind> in <neighbourhood>", never "..."
        tags = [{"id": "urn:tag:category:place:restaurant", "name": "Restaurant"},
                {"id": "urn:tag:category:place:japanese_restaurant", "name": "Japanese restaurant"},
                {"id": "urn:tag:category:place:takeout_restaurant", "name": "Takeout restaurant"}]
        k = {"name": "Kanoyama", "tags": tags, "properties": {"neighborhood": "East Village", "unique_selling_points":
             "The restaurant is famous for its creative and rare menu items, most notably the bluefin tuna rib "
             "which diners scrape themselves, alongside a highly regarded omakase."}}
        self.assertEqual(E.blurb_line(k), "Japanese restaurant in the East Village")
        self.assertEqual(E.blurb_line(k, "SoHo"), "Japanese restaurant in SoHo")
        k["properties"]["unique_selling_points"] = ("Hand-pulled noodles in a rich pork broth with chili oil; the "
                                                    "line forms at noon and runs out the door most days.")
        self.assertEqual(E.blurb_line(k), "Hand-pulled noodles in a rich pork broth with chili oil")
        k["properties"]["unique_selling_points"] = "Black-owned bar with soul food and dancing every Friday night."
        self.assertEqual(E.blurb_line(k), "Japanese restaurant in the East Village")   # identity never first
        self.assertEqual(E._hood_phrase("Financial District"), "the Financial District")
        self.assertEqual(E._hood_phrase("East Harlem"), "East Harlem")
        self.assertEqual(E._hood_phrase("West Village"), "the West Village")
        self.assertEqual(E._hood_phrase("The Hill"), "The Hill")
        k["properties"]["unique_selling_points"] = "Soul food and dancing every Friday night at a Black-owned bar."
        self.assertEqual(E.blurb_line(k), "Japanese restaurant in the East Village")   # identity never named
        # card audit, 30 Oct: order list normalised, no love repeated, the line's own dishes first
        self.assertEqual(E.clean_order(["N Y P D sandwich", "Fish An Chips", "Korean Fried Chicken", "oysters"], k,
                                       set(), n=4, line="East Coast oysters at a dim bar",
                                       loves=["Korean fried chicken"]),
                         ["oysters", "NYPD sandwich", "Fish And Chips"])
        self.assertEqual(E.clean_order(["Glinda"], k, set(), line="Craft cocktails and mocktails, outside food welcome",
                                       extra=["street tacos", "mocktails"]), ["mocktails", "Glinda"])
        self.assertEqual(E.clean_order(["Avocado And Toast", "avocado toast"], k, set()), ["Avocado And Toast"])
        # a love the place's own text names stays, first (Jody B's rib tips); one it doesn't goes (KFC at a steakhouse)
        jb = {"name": "Jody B's", "tags": [], "properties": {"unique_selling_points": "Famous for tender, smoky rib "
                                                               "tips and highly seasoned burgers."}}
        self.assertEqual(E.clean_order(["pork steaks", "rib tips", "Korean Fried Chicken"], jb, set(),
                                       line="Tender, smoky rib tips", loves=["Rib Tips", "Korean fried chicken"]),
                         ["rib tips", "pork steaks"])
        self.assertEqual(E.clean_order(["pork steaks"], jb, set(), loves=["rib tips"], credit="rib tips"),
                         ["rib tips", "pork steaks"])                              # the credited dish love, first
        self.assertEqual(E.clean_order(["Tomahawk Prime Ribeye", "Korean Fried Chicken"], jb, set(),
                                       loves=["Korean fried chicken"], credit="Korean fried chicken"),
                         ["Tomahawk Prime Ribeye"])                # credited by tag but not in the place's own text
        self.assertFalse(E._IDENTITY.search("Dancing, drinks and pool at a long-running lesbian bar"))  # venue type
        self.assertTrue(E._IDENTITY.search("Cocktails at an LGBTQ+-friendly lounge"))
        closed = {d: [{"opens": None, "closed": True, "closes": None}] for d in
                  ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")}
        self.assertTrue(E.closed_all_week({"properties": {"hours": closed}}))
        closed["friday"] = [{"opens": "T17:00", "closed": False, "closes": "T02:00"}]
        self.assertFalse(E.closed_all_week({"properties": {"hours": closed}}))
        self.assertFalse(E.closed_all_week({"properties": {}}))                    # no hours data: stays eligible

    def test_dish_must_be_in_the_places_text(self):
        e = {"name": "Ampersand", "properties": {"short_description": "Cocktail bar with small plates.",
                                                 "keywords": [{"name": "martini"}]}}
        self.assertFalse(E.dish_in_text(e, "tacos"))
        e["properties"]["cuisine_description"] = "Known for birria tacos and margaritas."
        self.assertTrue(E.dish_in_text(e, "tacos"))
        self.assertTrue(E.dish_in_text({"name": "Pappy's Smokehouse", "properties": {}}, "barbecue"))
        self.assertTrue(E.dish_in_text({"name": "X", "properties": {"keywords": [{"name": "catfish"}]}},
                                       "fried catfish"))
        tag = lambda tid, name: {"id": tid, "name": name}  # noqa: E731
        pickles = {"tags": [tag("urn:tag:category:place:restaurant", "Restaurant"),
                            tag("urn:tag:activity_type:place:shopping", "Shopping"),
                            tag("urn:tag:offerings:place:gift_items", "Gift items"),
                            tag("urn:tag:service_options:place:takeout", "Takeout")]}
        self.assertIsNotNone(E.excluded_kind(pickles))                                  # Pearlie's Pickles

    def test_kind_of_and_variety(self):
        tag = lambda k: {"id": "urn:tag:category:place:" + k, "name": k}  # noqa: E731
        self.assertEqual(E.kind_of({"tags": [tag("bar"), tag("restaurant")]}), ("drink", "drink"))
        self.assertEqual(E.kind_of({"tags": [tag("bar"), tag("barbecue_restaurant")]}), ("eat", "barbecue"))
        self.assertEqual(E.kind_of({"tags": [tag("coffee_shop")]}), ("eat", "cafe"))
        self.assertEqual(E.kind_of({"tags": [tag("restaurant")]}), ("eat", "other"))
        r = api.run_unsaid("St. Louis", CEDRIC, mode="fake", qloo=QL.Qloo(fake=True, cache_dir=tempfile.mkdtemp()),
                           gemini=False, street_check=False)
        fam = collections.Counter((c["kind"], c["kind_family"]) for c in r["picks"])
        self.assertTrue(all(c.get("kind") in ("eat", "drink") for c in r["picks"] + r["reserves"]))
        self.assertLessEqual(max(fam.values()), E.CFG["KIND_CAP"] + 1)   # fake pool: one love may force one more

    def test_chain_rule_reads_the_places_own_website(self):
        mk = lambda i, n, w: {"entity_id": i, "name": n, "properties": {"website": w}}  # noqa: E731
        pool = [mk("fw1", "First Watch", "https://www.firstwatch.com/locations/saint-ann/"),
                mk("rb", "Rush Bowls", "https://rushbowls.com/st-louis"),
                mk("bq", "Boqueria Soho", "https://boqueriarestaurant.com/location/nyc/soho/"),
                mk("x1", "Ex Bar", "https://exbar.com/"), mk("x2", "Ex Bar Too", "https://exbar.com/"),
                mk("x3", "Ex Bar Three", "https://exbar.com/"),
                mk("p", "Pappy's Smokehouse", "https://pappyssmokehouse.com/"),
                mk("f1", "Molasses Books", "https://facebook.com/molasses"),
                mk("f2", "Eastwood", "https://facebook.com/eastwood"), mk("f3", "Joe", "https://facebook.com/joe"),
                mk("l", "Locations Bar", "https://locationsbar.com/locations"),
                mk("bf", "Bonefish Grill", "https://locations.bonefishgrill.com/missouri/brentwood/8780-eager-road")]
        self.assertEqual(sorted(E.chain_ids(pool, [p["entity_id"] for p in pool])),
                         ["bf", "bq", "fw1", "rb", "x1", "x2", "x3"])


class Flaky:
    """A fake Qloo transport: the first `fail` calls answer `status` (or raise `exc`), then the fake world answers."""

    def __init__(self, inner, fail=1, status=503, headers=None, exc=None):
        self.inner, self.fail, self.status, self.headers, self.exc = inner, fail, status, headers or {}, exc
        self.n = 0

    def get(self, url, *a, **kw):
        self.n += 1
        if self.n <= self.fail:
            if self.exc is not None:
                raise self.exc
            return self.status, '{"error": "busy"}', dict(self.headers)
        return self.inner.get(url)


class TestRetries(Tmp):
    """30 Oct, 11:15 UTC: one failed Qloo call while resolving a love sank the query. Now resolve and search calls
    retry 429/5xx/timeouts with jittered backoff inside a 12 s window."""

    def flaky(self, **kw):
        q = QL.Qloo(fake=True, cache_dir=tempfile.mkdtemp(dir=self.dir))     # a cold cache every time
        q.transport = Flaky(q.transport, **kw)
        q.waits = []
        q.sleep = q.waits.append
        return q

    def test_love_survives_one_failed_call(self):
        for kw in ({"status": 503}, {"status": 429, "headers": {"Retry-After": "1"}},
                   {"exc": TimeoutError("timed out")}, {"exc": ConnectionResetError("reset")}):
            q = self.flaky(**kw)
            r = api.resolve_love("Sade", "artist", mode="fake", qloo=q)
            self.assertEqual(r["status"], "ok", kw)
            self.assertEqual(q.transport.n, 2, kw)                        # failed once, then answered
            self.assertEqual(len(q.waits), 1, kw)
            self.assertTrue(any(t["label"].endswith("(retry)") for t in q.trace))
            self.assertEqual(r["chip"]["c2_calls"], 1)                     # a retry is not a second lookup

    def test_backoff_is_jittered_bounded_and_honours_retry_after(self):
        waits = [QL.backoff_s(0, resolve=True) for _ in range(200)]
        self.assertTrue(all(0.5 * QL.RETRY_BASE_S <= w <= QL.RETRY_BASE_S for w in waits))
        self.assertGreater(len({round(w, 4) for w in waits}), 50)         # jittered, not one fixed step
        self.assertLessEqual(QL.backoff_s(10, resolve=True), QL.RETRY_CAP_S)
        self.assertGreaterEqual(QL.backoff_s(0, {"Retry-After": "2"}, resolve=True), 2.0)
        self.assertGreaterEqual(QL.backoff_s(0, {"retry-after": "3"}), 3.0)

    def test_city_survives_one_failed_call(self):
        q = self.flaky(status=502)
        r = api.resolve_city("Chicago, IL", mode="fake", qloo=q)
        self.assertNotEqual(r["status"], "degraded")
        self.assertEqual(q.transport.n, 2)

    def test_run_resolves_through_a_failed_call(self):
        q = self.flaky(status=500)
        r = api.run_unsaid("St. Louis", CEDRIC, mode="fake", qloo=q, gemini=False, street_check=False)
        self.assertNotIn(r["status"], ("degraded", "needs_input"))

    def test_still_busy_after_the_retries_is_degraded_never_a_miss(self):
        q = self.flaky(fail=99, status=503)
        r = api.resolve_love("Sade", "artist", mode="fake", qloo=q)
        self.assertEqual((r["status"], r.get("reason")), ("degraded", "Qloo HTTP 503"))
        self.assertEqual(q.transport.n, QL.RESOLVE_RETRIES + 1)          # bounded: one call, 4 attempts at most
        self.assertLess(sum(q.waits), QL.RESOLVE_BUDGET_S)

    def test_retry_after_past_the_window_answers_at_once(self):
        q = self.flaky(fail=99, status=429, headers={"Retry-After": "60"})
        r = api.resolve_love("Sade", "artist", mode="fake", qloo=q)
        self.assertEqual(r["status"], "degraded")
        self.assertEqual((q.transport.n, q.waits), (1, []))               # never sleeps past the 12 s window

    def test_window_caps_attempt_timeout_and_total_time(self):
        q = self.q()
        seen = []

        class Slow:
            def get(self, url, timeout=None):
                seen.append(timeout)
                raise TimeoutError("timed out")
        q.transport, q.fake = Slow(), False            # the live path passes the per-attempt timeout
        q.bucket, q.sleep = None, lambda s: None
        with q.window(1.0):
            t = __import__("time").monotonic()
            with self.assertRaises(QL.QlooError) as cm:
                q.search("Sade", label="C2 love")
            self.assertLess(__import__("time").monotonic() - t, 1.0)
        self.assertTrue(cm.exception.busy)
        self.assertTrue(all(x <= QL.TIMEOUT_RESOLVE for x in seen))
        self.assertIsNone(q.win)                       # closed again: the run's own calls keep their timeouts


class TestStalePool(unittest.TestCase):
    """Qloo closes idle keep-alive connections after 20-70 s (probed 30 Oct). A dead pooled connection is retried
    on a NEW connection, the pool's other idle ones are dropped, and connections idle too long are never reused."""

    class Conn:
        made = []

        def __init__(self, host=None, port=None, timeout=None, context=None, dead=False):
            self.dead, self.sock, self.closed = dead, _Sock(), False
            if not dead:
                TestStalePool.Conn.made.append(self)

        def request(self, *a, **kw):
            if self.dead:
                raise QL.http.client.RemoteDisconnected("Remote end closed connection without response")

        def getresponse(self):
            return _Resp()

        def close(self):
            self.closed, self.sock = True, None

    def setUp(self):
        self.orig = QL.http.client.HTTPSConnection
        QL.http.client.HTTPSConnection = TestStalePool.Conn
        TestStalePool.Conn.made = []
        QL._POOLS.clear()

    def tearDown(self):
        QL.http.client.HTTPSConnection = self.orig
        QL._POOLS.clear()

    def test_dead_pooled_connections_never_fail_a_call(self):
        pool = QL._pool("h.example", 443)
        dead = [TestStalePool.Conn(dead=True) for _ in range(8)]
        for c in dead:
            pool.give(c)
        t = QL.HttpTransport("k")
        status, body, _ = t.get("https://h.example/search?query=x")
        self.assertEqual((status, body), (200, "{}"))
        self.assertEqual(t.stats["stale_retries"], 1)
        self.assertTrue(all(c.closed for c in dead))                     # one dead -> the idle ones all go
        self.assertEqual(len(TestStalePool.Conn.made), 1)

    def test_long_idle_connection_is_not_reused(self):
        pool = QL._pool("h.example", 443)
        old = TestStalePool.Conn()
        pool.give(old)
        old._idle_at -= QL.IDLE_MAX_S + 1
        c, reused = pool.take(5)
        self.assertFalse(reused)
        self.assertIsNot(c, old)
        self.assertTrue(old.closed)


class _Sock:
    def settimeout(self, t):
        pass


class _Resp:
    status, will_close, headers = 200, False, {}

    def read(self):
        return b"{}"

    def getheader(self, k, d=None):
        return d


if __name__ == "__main__":
    res = unittest.main(argv=[sys.argv[0], "-v"], exit=False).result
    ok = res.wasSuccessful()
    print("API contract tests: %d run, %d failed -> %s [FAKE]" % (res.testsRun, len(res.failures) + len(res.errors),
                                                                 "PASS" if ok else "FAIL"))
    sys.exit(0 if ok else 1)
