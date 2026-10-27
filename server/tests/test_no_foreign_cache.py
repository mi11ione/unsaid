"""No screen path ever renders another key's cards (UNSAID.md §3.5, `test_no_foreign_cache`).

  python3 -I server/tests/test_no_foreign_cache.py

Set A (Cedric) is run fresh and cached. Then set B (Jason, never cached) is driven down every path that
does not produce a fresh result for B: limited, Qloo erroring, the 90 s hard cap, the queue timing out,
waiting on an in-flight run, /api/result. None of them may show a single A card. Finally B is cached and
Qloo fails again: B gets its own cards back (degraded), still none of A's.
"""
import json
import os
import shutil
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _harness as H  # noqa: E402

app = H.app
C = app.C
QlooError = app.adapter.QlooError


class NoForeignCache(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        H.reset_limits()
        cls.ev_a, cls.res_a = H.run(H.CEDRIC, ip="203.0.113.1")
        cls.ids_a = H.card_ids(cls.ev_a)
        cls.real_run = staticmethod(app.adapter.run)

    def setUp(self):
        H.reset_limits()
        app.adapter.run = self.real_run
        app.HARD_CAP_S = 90.0

    tearDown = setUp

    def assertNoA(self, events, why):
        """Cards on screen are either none at all, or exactly the record stored under this response's own key."""
        r = events[-1]["result"]
        self.assertNotEqual(r.get("key"), self.res_a["key"], why + " answered with A's key")
        shown = H.card_ids(events)
        if not shown:
            return
        rec = app.RESULTS.get(r.get("key") or "")
        self.assertIsNotNone(rec, why + " showed cards with no record under its own key")
        own = {c["id"] for c in rec["result"]["picks"] + rec["result"]["reserves"]}
        self.assertEqual(shown, own, why + " showed cards that are not its own key's")

    def assertNoCards(self, events, why):
        self.assertEqual(H.card_ids(events), set(), why + " rendered cards")
        self.assertNoA(events, why)

    # ---- the key
    def test_key_is_exact(self):
        base = ("v1", "fake", "loc", ["a", "b", "c"], "unsaid", "w", "live")
        k = C.result_key(*base)
        self.assertEqual(k, C.result_key("v1", "fake", "loc", ["c", "a", "b"], "unsaid", "w", "live"),
                         "love order matters")
        for i, alt in enumerate(["v2", "live", "loc2", ["a", "b", "d"], "qloo_places", "w2", "dated_only"]):
            args = list(base)
            args[i] = alt
            self.assertNotEqual(k, C.result_key(*args), "field %d is not in the key" % i)
        self.assertRaises(ValueError, C.result_key, "v1", "fake", "loc", ["a", None], "unsaid", "w", "live")
        self.assertRaises(ValueError, C.result_key, "v1", "fake", "loc", ["a"], "unsaid", "w", "maybe")

    def test_a_ran_and_was_cached(self):
        self.assertEqual(self.res_a["status"], "ok")
        self.assertIn("fake", self.res_a["flags"])
        self.assertEqual(len(self.res_a["picks"]), 7)
        ev, r = H.run(H.CEDRIC, ip="203.0.113.99")
        self.assertTrue(r["cached"])
        self.assertEqual([p["id"] for p in r["picks"]], [p["id"] for p in self.res_a["picks"]])

    # ---- the cache store
    def test_store_never_answers_for_another_key(self):
        rc = C.ResultCache(os.path.join(H.TMP, "store"))
        ka, kb = "a" * 64, "b" * 64
        rc.put(ka, {"picks": [{"id": "A1"}]})
        self.assertIsNone(rc.get(kb))
        self.assertIsNone(rc.get(ka[:63]))                  # no prefix match
        self.assertIsNone(rc.get("../" + ka))
        # a misplaced file (A's record under B's path) is a miss, not B's result
        os.makedirs(os.path.dirname(rc._path(kb)), exist_ok=True)
        shutil.copy(rc._path(ka), rc._path(kb))
        self.assertIsNone(C.ResultCache(os.path.join(H.TMP, "store")).get(kb))
        # a record whose result names another key is a miss too
        with open(rc._path(kb), "w") as f:
            json.dump({"key": kb, "stored_at": time.time(), "result": {"key": ka, "picks": [{"id": "A1"}]}}, f)
        self.assertIsNone(C.ResultCache(os.path.join(H.TMP, "store")).get(kb))

    # ---- every non-fresh path for B
    def test_limited(self):
        for _ in range(3):
            app.FRESH_IPS.record("203.0.113.2")
        ev, r = H.run(H.JASON, ip="203.0.113.2")
        self.assertEqual(r["status"], "limited")
        self.assertEqual(r["picks"], [])
        self.assertNoCards(ev, "limited")

    def test_qloo_erroring_new_key(self):
        def boom(*a, **k):
            raise QlooError(503, "x", "u")
        app.adapter.run = boom
        ev, r = H.run(H.JASON)
        self.assertEqual(r["status"], "degraded")
        self.assertIn("no_cache", r["flags"])
        self.assertEqual(r["note"], app.COPY["degraded_none"])
        self.assertNoCards(ev, "degraded, no cache")

    def test_hard_cap(self):
        app.HARD_CAP_S = 1.5
        gate = threading.Event()

        def slow(*a, **k):
            gate.wait(10)
            raise QlooError(504, "x", "u")
        app.adapter.run = slow
        t0 = time.monotonic()
        ev, r = H.run(H.JASON)
        gate.set()
        self.assertLess(time.monotonic() - t0, 5)
        self.assertEqual(r["status"], "degraded")
        self.assertNoCards(ev, "hard cap")

    def test_queue_times_out(self):
        app.HARD_CAP_S = 1.0
        app.ADMIT = H.L.Admission(max_active=1)
        app.ADMIT.active = 1                                # someone else holds the only slot
        ev, r = H.run(H.JASON)
        self.assertTrue(any(e.get("state") == "queued" for e in ev))
        q = next(e for e in ev if e.get("state") == "queued")
        self.assertEqual(q["text"], "One run ahead of yours · about %d s" % q["eta_s"])
        self.assertEqual(r["status"], "degraded")
        self.assertNoCards(ev, "queued then capped")

    def test_inflight_other_key(self):
        """B waits on its own in-flight run, never on A's."""
        gate = threading.Event()
        real = self.real_run

        def slow(*a, **k):
            gate.wait(10)
            return real(*a, **k)
        app.adapter.run = slow
        out = {}
        t = threading.Thread(target=lambda: out.setdefault("first", H.run(H.AL_GREEN, ip="10.0.0.1")))
        t.start()
        time.sleep(0.5)
        t2 = threading.Thread(target=lambda: out.setdefault("second", H.run(H.AL_GREEN, ip="10.0.0.2")))
        t2.start()
        time.sleep(0.5)
        gate.set()
        t.join(30)
        t2.join(30)
        (ev1, r1), (ev2, r2) = out["first"], out["second"]
        self.assertEqual(r1["key"], r2["key"])
        self.assertEqual([p["id"] for p in r1["picks"]], [p["id"] for p in r2["picks"]])
        self.assertNoA(ev2, "in-flight join")

    def test_result_endpoint(self):
        self.assertIsNone(app.RESULTS.get("f" * 64))
        rec = app.RESULTS.get(self.res_a["key"])
        self.assertEqual(rec["result"]["key"], self.res_a["key"])

    def test_degraded_with_own_cache(self):
        ev_b, r_b = H.run(H.SOUL, ip="10.9.9.9")         # B is now cached under its own key
        ids_b = H.card_ids(ev_b)
        self.assertTrue(ids_b)
        rec = app.RESULTS.get(r_b["key"])
        with app.RESULTS.lock:                            # age it past the fresh TTL so Qloo is asked again
            app.RESULTS.mem[r_b["key"]]["stored_at"] -= C.FRESH_S + 10

        def boom(*a, **k):
            raise QlooError(500, "x", "u")
        app.adapter.run = boom
        ev, r = H.run(H.SOUL, ip="10.9.9.8")
        self.assertEqual(r["status"], "degraded")
        self.assertTrue(r["note"].startswith("from ") and r["note"].endswith(" · Qloo is slow right now"), r["note"])
        self.assertEqual(r["key"], r_b["key"])
        self.assertEqual(H.card_ids(ev), ids_b)
        self.assertNoA(ev, "degraded with cache")
        self.assertIsNotNone(rec)

    def test_geo_gated_visitor_never_gets_a_live_answer(self):
        """US runs with the live lane on; DE (and an unknown country) with the same loves get no lane=live item."""
        old = app.GEMINI
        app.GEMINI = H.make_lane(H.names_transport([{"name": "Live Lane Bistro", "neighbourhood": "Soulard"}]))
        H.clear_results()
        try:
            ev_us, r_us = H.run(H.CEDRIC, ip="198.51.100.20", country="US")
            live = lambda evs: [e for e in evs if e["type"] == "wall_name" and e.get("lane") == "live"] + \
                [i for i in evs[-1]["result"].get("wall") or [] if i.get("lane") == "live"]  # noqa: E731
            self.assertTrue(live(ev_us), "the US run should carry a live Gemini answer")
            self.assertTrue(app.RESULTS.get(r_us["key"]))
            for cc in ("DE", "GB", ""):
                ev, r = H.run(H.CEDRIC, ip="198.51.100.21", country=cc)
                self.assertEqual(live(ev), [], "%r received a lane=live answer" % cc)
                self.assertNotEqual(r["key"], r_us["key"])
                self.assertIn("dated_only", r["flags"])
            # /api/result/<the US key>: a DE visitor gets 404, a US visitor gets it
            srv = app.make_server("127.0.0.1", 0)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            import urllib.error
            import urllib.request
            url = "http://127.0.0.1:%d/api/result/%s" % (srv.server_address[1], r_us["key"])
            codes = {}
            for cc in ("DE", "US"):
                try:
                    with urllib.request.urlopen(urllib.request.Request(url, headers={"CF-IPCountry": cc})) as resp:
                        codes[cc] = resp.status
                except urllib.error.HTTPError as e:
                    codes[cc] = e.code
            srv.shutdown()
            self.assertEqual(codes, {"DE": 404, "US": 200})
        finally:
            app.GEMINI = old

    def test_engine_live_error_is_dated_only_not_partial(self):
        """CONTRACT engine additions: diag.live_error -> the dated_only flag with its §2.2 note, never partial."""
        old = app.GEMINI
        app.GEMINI = H.make_lane(H.names_transport([]))      # the lane is on for this US visitor
        picks = [{"id": "L%d" % i, "name": "P%d" % i, "fit_rank": i} for i in range(7)]

        def engine_result(lanes_failed):
            def fake_run(*a, **k):
                return {"status": "partial", "flags": ["fake"], "picks": list(picks), "reserves": [], "wall": [],
                        "diag": {"live_error": "live lane timed out", "lanes_failed": lanes_failed}}
            return fake_run
        try:
            H.clear_results()
            app.adapter.run = engine_result(["live lane: TimeoutError"])
            ev, r = H.run(H.SOUL, ip="198.51.100.40", country="US")
            self.assertEqual(r["status"], "ok")
            self.assertIn("dated_only", r["flags"])
            self.assertNotIn("partial", r["flags"])
            self.assertEqual(r["lanes"]["gemini"]["state"], "dated_only")
            note = [e["text"] for e in ev if e.get("state") == "dated_only"]
            self.assertTrue(note and note[0].startswith("All answers dated ") and
                            note[0].endswith(" · no live ask right now"), note)
            H.clear_results()                                   # a Qloo lane failing too stays partial
            app.adapter.run = engine_result(["live lane: TimeoutError", "C4 1 of 6 pool calls"])
            ev, r = H.run(H.SOUL, ip="198.51.100.41", country="US")
            self.assertEqual(r["status"], "partial")
            self.assertIn("dated_only", r["flags"])
        finally:
            app.GEMINI = old

    def test_needs_input_has_no_cards(self):
        ev, r = H.run([{"text": "Kings of Comedy"}, {"text": "Al Green", "hint": "artist"}])
        self.assertEqual(r["status"], "needs_input")
        self.assertNoCards(ev, "needs_input")
        ev, r = H.run(H.JASON, city="Richmond")
        self.assertEqual(r["status"], "needs_input")
        self.assertNoCards(ev, "ambiguous city")


if __name__ == "__main__":
    unittest.main(verbosity=2)
