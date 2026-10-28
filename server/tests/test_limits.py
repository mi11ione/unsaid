"""Token, per-IP limit, quota guard, queue and the Gemini lane's guards.

  python3 -I server/tests/test_limits.py
"""
import json
import os
import sys
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _harness as H  # noqa: E402

app = H.app
L = H.L
import gemini_live as G  # noqa: E402


def loves_q(loves):
    return urllib.parse.quote(json.dumps([{"text": x["text"], "type": x.get("hint")} if x.get("hint") else x["text"]
                                          for x in loves]))


class Http(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.TOKEN = "t0ken"
        cls.srv = app.make_server("127.0.0.1", 0)
        cls.base = "http://127.0.0.1:%d" % cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        app.TOKEN = ""

    def get(self, path, token="t0ken"):
        req = urllib.request.Request(self.base + path, headers={"Authorization": "Bearer " + token} if token else {})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    def unsaid(self, loves):
        code, body = self.get("/api/unsaid?city=st-louis&loves=" + loves_q(loves))
        self.assertEqual(code, 200)
        lines = [json.loads(l) for l in body.splitlines()]
        self.assertEqual(lines[-1]["type"], "done")
        return lines

    def test_bench_header_skips_the_ip_limit(self):
        H.reset_limits()
        H.clear_results()
        app.BENCH_SECRET = "bench-s3cret"
        try:
            def go(loves, bench=None):
                h = {"Authorization": "Bearer t0ken"}
                if bench:
                    h["X-Unsaid-Bench"] = bench
                req = urllib.request.Request(self.base + "/api/unsaid?city=st-louis&loves=" + loves_q(loves), headers=h)
                with urllib.request.urlopen(req, timeout=60) as r:
                    return json.loads(r.read().decode().splitlines()[-1])["result"]["status"]
            got = [go(s, "bench-s3cret") for s in (H.CEDRIC, H.JASON, H.AL_GREEN, H.SOUL)]
            self.assertNotIn("limited", got)
            H.clear_results()
            for _ in range(3):
                app.FRESH_IPS.record("127.0.0.1")
            self.assertEqual(go(H.CEDRIC, "wrong"), "limited")
            self.assertEqual(go(H.CEDRIC), "limited")
            self.assertNotEqual(go(H.CEDRIC, "bench-s3cret"), "limited")
        finally:
            app.BENCH_SECRET = ""

    def test_token(self):
        self.assertEqual(self.get("/api/health", token=None)[0], 200)
        for p in ("/api/resolve?kind=city&q=nyc", "/api/unsaid?city=nyc&loves=x", "/api/result/" + "a" * 64):
            self.assertEqual(self.get(p, token=None)[0], 401, p)
            self.assertEqual(self.get(p, token="wrong")[0], 401, p)
        self.assertEqual(self.get("/api/resolve?kind=city&q=nyc&token=t0ken", token=None)[0], 200)

    def test_fourth_fresh_run_is_limited(self):
        H.reset_limits()
        H.clear_results()
        sets = [H.CEDRIC, H.JASON, H.AL_GREEN, H.SOUL]
        out = [self.unsaid(s)[-1]["result"] for s in sets]
        self.assertEqual([r["status"] for r in out[:3]], ["ok", "ok", "ok"])
        r4 = out[3]
        print("\n  4th fresh run from one IP -> status=%s note=%r picks=%d" % (r4["status"], r4.get("note"), len(r4["picks"])))
        self.assertEqual(r4["status"], "limited")
        self.assertEqual(r4["note"], "Fresh runs are limited so everyone gets through. These open instantly:")
        self.assertEqual(r4["picks"], [])
        again = self.unsaid(H.CEDRIC)[-1]["result"]          # a cached key is not a fresh run
        self.assertTrue(again["cached"])
        self.assertEqual(again["status"], "ok")


class Guards(unittest.TestCase):
    def test_quota_guard_counts(self):
        q = L.QlooQuota(os.path.join(H.TMP, "q1.json"), monthly=100, threshold=0.85)
        for _ in range(84):
            q.note({})
        self.assertFalse(q.fired())
        q.note({})
        self.assertTrue(q.fired())

    def test_quota_guard_headers(self):
        q = L.QlooQuota(os.path.join(H.TMP, "q2.json"), monthly=10000, threshold=0.85,
                        headers="X-RateLimit-Remaining-Month,X-RateLimit-Limit-Month")
        q.note({"x-ratelimit-remaining-month": "2000", "X-RateLimit-Limit-Month": "10000"})
        self.assertFalse(q.fired())
        q.note({"X-RateLimit-Remaining-Month": "1400"})
        self.assertTrue(q.fired())

    def test_queue_copy(self):
        a = L.Admission(max_active=1, avg_run_s=20)
        a.active = 1
        seen = []
        holder = threading.Thread(target=lambda: a.acquire(deadline=time.monotonic() + 3))
        holder.start()
        time.sleep(0.2)
        a.acquire(on_wait=lambda n, eta: seen.append((n, eta)), deadline=time.monotonic() + 0.5)
        holder.join()
        self.assertEqual(seen[0], (2, 40))
        self.assertEqual(app.COPY["queued"] % (app.WORDS[2], 40), "Two runs ahead of yours · about 40 s")

    def test_ip_limiter(self):
        lim = L.IpLimiter(per_hour=3)
        self.assertEqual([lim.record("x") for _ in range(4)], [True, True, True, False])
        self.assertTrue(lim.record("y"))


class Gemini(unittest.TestCase):
    def lane(self, transport, **env):
        return H.make_lane(transport, **dict({"GEMINI_RPD": "20"}, **env))

    @staticmethod
    def ok_transport(calls):
        def t(prompt):
            calls.append(prompt)
            text = json.dumps([{"name": "Place %d" % i, "neighbourhood": "Soulard"} for i in range(15)])
            return 200, {"candidates": [{"content": {"parts": [{"text": text}]}}]}
        return t

    def test_live_model_is_its_own_env_var(self):
        self.assertEqual(self.lane(self.ok_transport([]), GEMINI_LIVE_MODEL=None).model, "gemini-3-flash-preview")
        self.assertEqual(self.lane(self.ok_transport([]), GEMINI_LIVE_MODEL="x-pinned").model, "x-pinned")
        os.environ["GEMINI_MODEL"] = "gemini-3.8-flash"          # the dated lane's model never leaks in
        try:
            self.assertEqual(self.lane(self.ok_transport([]), GEMINI_LIVE_MODEL=None).model, "gemini-3-flash-preview")
        finally:
            os.environ.pop("GEMINI_MODEL")

    def test_no_key_is_dated_only_and_never_calls(self):
        calls = []
        s = self.lane(self.ok_transport(calls), GEMINI_API_KEY=None).for_country("US")
        self.assertIsNone(s.ask_taste("St. Louis", ["A", "B", "C"], "loc", ["1", "2", "3"]))
        self.assertEqual((s.state, s.reason, calls), ("dated_only", "no key", []))

    def test_geo_gate(self):
        for cc in ("GB", "CH", "DE", "NO", "IS", ""):
            calls = []
            s = self.lane(self.ok_transport(calls)).for_country(cc)
            self.assertIsNone(s.ask_taste("St. Louis", ["A"], "loc", ["1"]), cc)
            self.assertEqual((s.state, calls), ("dated_only", []), cc)

    def test_one_taste_ask_and_no_live_street_asks(self):
        calls = []
        s = self.lane(self.ok_transport(calls)).for_country("US")
        a = s.ask_taste("St. Louis", ["Frankie Beverly & Maze", "The Original Kings of Comedy", "Rib Tips"], "loc",
                        ["1", "2", "3"])
        self.assertEqual(s.state, "live")
        self.assertEqual((a["lane"], a["model"]), ("live", "gemini-3-flash-preview"))
        self.assertTrue(a["asked_at"].endswith("Z"))
        self.assertEqual(len(a["names"]), 12)
        self.assertEqual(a["phrasing"], "I love Frankie Beverly & Maze, The Original Kings of Comedy and Rib Tips. "
                                        "Where should I eat and drink in St. Louis?")
        self.assertTrue(calls[0].endswith("Real, currently open venues only."))
        self.assertIsNone(s.ask_taste("St. Louis", ["X"], "loc", ["9"]), "a second taste ask in one run")
        self.assertEqual([s.ask_street(h, "St. Louis", "loc") for h in ("Soulard", "The Hill")], [None, None])
        self.assertEqual(len(calls), 1, "exactly one live call per run")

    def test_429_cools_down_for_an_hour(self):
        calls = []

        def t(prompt):
            calls.append(prompt)
            return 429, None
        lane = self.lane(t)
        s = lane.for_country("US")
        self.assertIsNone(s.ask_taste("St. Louis", ["A"], "loc", ["1"]))
        self.assertEqual(s.state, "dated_only")
        self.assertGreater(lane.cooldown_until - time.time(), 3590)
        s2 = lane.for_country("US")
        self.assertEqual((s2.state, s2.reason), ("dated_only", "429 cooldown"))
        self.assertIsNone(s2.ask_taste("St. Louis", ["B"], "loc", ["2"]))
        self.assertEqual(len(calls), 1)

    def test_guard_16_of_20_then_dated_only_until_pacific_midnight(self):
        calls = []
        lane = self.lane(self.ok_transport(calls))           # GEMINI_RPD=20 -> at most 16 live asks a day
        for i in range(20):
            lane.for_country("US").ask_taste("St. Louis", ["L%d" % i], "loc", [str(i)])
        self.assertEqual(len(calls), 16)
        self.assertEqual(lane.for_country("US").reason, "daily guard")
        lane.usage["day"] = "2000-01-01"                      # a new Pacific day resets the count
        self.assertIsNone(lane.for_country("US").reason)
        self.assertEqual(G.GeminiLane._day(), G.dt.datetime.now(G.PACIFIC).strftime("%Y-%m-%d"))

    def test_live_run_names_the_model_and_makes_one_call(self):
        H.reset_limits()
        H.clear_results()
        calls = []
        old = app.GEMINI
        app.GEMINI = self.lane(self.ok_transport(calls))
        try:
            ev, r = H.run(H.CEDRIC, ip="192.0.2.51", country="US")
            _, again = H.run(H.CEDRIC, ip="192.0.2.52", country="US")     # cached: no second call
        finally:
            app.GEMINI = old
        self.assertEqual(len(calls), 1)
        live = [e for e in ev if e["type"] == "wall_name" and e["lane"] == "live"]
        self.assertTrue(live and all(e["model"] == "gemini-3-flash-preview" for e in live))   # the raw log
        line = [e["text"] for e in ev if e.get("state") == "live"]
        self.assertEqual(line, ["Gemini (gemini-3-flash-preview): asked just now"])          # the status line
        self.assertEqual(r["lanes"]["gemini"]["model"], "gemini-3-flash-preview")
        self.assertNotIn("dated_only", r["flags"])
        self.assertFalse([b for b in r["burn"]["asked"] if b.get("lane") == "live"])
        self.assertTrue(again["cached"])

    def test_slow_gemini_never_delays_cards(self):
        """Gemini answering after the budget (15 s live; 0.5 s here): cards on time, dated_only + its note, and
        the late answer never joins the run or its cached result."""
        H.reset_limits()
        H.clear_results()
        calls, released = [], threading.Event()

        def slow(prompt):
            calls.append(prompt)
            released.wait(3)
            return self.ok_transport([])(prompt)
        old = app.GEMINI
        app.GEMINI = self.lane(slow, GEMINI_LIVE_TIMEOUT_S="0.5")
        try:
            t0 = time.monotonic()
            ev, r = H.run(H.CEDRIC, ip="192.0.2.80", country="US")
            took = time.monotonic() - t0
        finally:
            app.GEMINI = old
        self.assertLess(took, 2.5, "the run waited for Gemini")
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(r["picks"]), 7)
        self.assertIn("dated_only", r["flags"])
        self.assertNotIn("partial", r["flags"])
        self.assertTrue([e for e in ev if e.get("state") == "dated_only" and e["text"].endswith(
            " · no live ask right now")])
        self.assertTrue(r["lanes"]["gemini"]["reason"].startswith("no answer in 0.5"), r["lanes"])
        live = lambda items: [i for i in items if i.get("lane") == "live"]  # noqa: E731
        self.assertEqual(live([e for e in ev if e["type"] == "wall_name"]) + live(r["wall"]), [])
        released.set()
        time.sleep(0.3)                                           # the late answer lands now
        self.assertEqual(live(app.RESULTS.get(r["key"])["result"]["wall"]), [])
        self.assertLess(r["diag"]["timing"]["gemini"], 1.0)

    def test_diag_timing_on_every_result(self):
        H.reset_limits()
        H.clear_results()
        _, r = H.run(H.CEDRIC, ip="192.0.2.81")
        t = r["diag"]["timing"]
        self.assertTrue({"pool", "rescore", "strike", "ids", "cap", "gemini", "total", "resolve", "queue",
                         "cpu_calls", "cpu_window", "cpu_total"} <= set(t), sorted(t))
        self.assertGreater(t["cpu_total"], 0)
        for k in ("pool", "rescore", "total"):
            self.assertIsInstance(t[k], float, k)
        _, c = H.run(H.CEDRIC, ip="192.0.2.82")                  # cached: this request's time + the run's
        self.assertTrue(c["cached"])
        self.assertIsNone(c["diag"]["timing"]["pool"])
        self.assertEqual(c["diag"]["timing_stored"]["pool"], t["pool"])
        for _ in range(3):
            app.FRESH_IPS.record("192.0.2.83")
        _, lim = H.run(H.JASON, ip="192.0.2.83")
        self.assertEqual(lim["status"], "limited")
        self.assertIsInstance(lim["diag"]["timing"]["total"], float)

    def test_street_check_is_dated_only(self):
        wall = {"answers": [
            {"kind": "street", "hood": "Soulard", "lane": "dated", "asked_at": "2026-10-28T09:00:00Z",
             "names": [{"name": "Somewhere"}]},
            {"kind": "city", "lane": "dated", "names": [{"name": "Elsewhere"}]},
            {"kind": "street", "hood": "Soulard", "lane": "live", "names": [{"name": "Never"}]}]}
        fn = app.adapter.dated_street(wall)
        self.assertEqual([n["name"] for a in fn("soulard", "St. Louis") for n in a["names"]], ["Somewhere"])
        self.assertEqual(fn("The Hill", "St. Louis"), [])


class Loves(unittest.TestCase):
    def test_forms_and_hints_reach_resolve_love(self):
        P = app.parse_loves
        want = [{"text": "Frankie Beverly & Maze", "hint": "artist"}, {"text": "rib tips", "hint": "tag"}]
        self.assertEqual(P(['[["Frankie Beverly & Maze","artist"],["rib tips","tag"]]']), want)          # sets file
        self.assertEqual(P(['[{"text":"Frankie Beverly & Maze","type":"artist"},{"text":"rib tips","hint":"dish"}]']),
                         want)                                                                          # objects
        self.assertEqual(P(['["Frankie Beverly & Maze","artist"]', '["rib tips","tag"]']), want)         # repeated
        self.assertEqual(P(['[["Rounders",null],"Carbone"]']), [{"text": "Rounders", "hint": None}, {"text": "Carbone"}])
        self.assertEqual(P(["Al Green|rib tips"]), [{"text": "Al Green"}, {"text": "rib tips"}])
        for bad in ('[["rib tips","nonsense"]]', '[["a","b","c"]]', '[[]]'):
            self.assertRaises(ValueError, P, [bad])
        seen = []
        real = app.adapter.resolve_love

        def spy(text, hint, q, mode):
            seen.append((text, hint))
            return real(text, hint, q, mode)
        app.adapter.resolve_love = spy
        try:
            H.reset_limits()
            ev, r = H.run(P(['[["Frankie Beverly & Maze","artist"],["The Original Kings of Comedy","movie"],'
                              '["rib tips","tag"]]']), ip="192.0.2.90")
        finally:
            app.adapter.resolve_love = real
        self.assertEqual(seen, [("Frankie Beverly & Maze", "artist"), ("The Original Kings of Comedy", "movie"),
                                ("rib tips", "tag")])
        rib = next(l for l in r["loves"] if "rib" in (l.get("label") or "").lower())
        self.assertEqual(rib["kind"], "tag")


class Output(unittest.TestCase):
    def test_city_without_answers_is_no_wall_and_says_so(self):
        H.reset_limits()
        ev, r = H.run(H.JASON, city="nyc", ip="192.0.2.95")    # the test walls hold St. Louis only
        self.assertIn("no_wall", r["flags"])
        self.assertEqual(r["note"], "No AI answers collected for this city yet: these are Qloo's picks for you, "
                                    "with nothing crossed out.")
        texts = [e.get("text") or "" for e in ev if e["type"] == "status"]
        self.assertFalse([t for t in texts if "dated" in t], texts)          # never "All answers dated earlier"
        self.assertTrue([t for t in texts if t == r["note"]])

    def test_ratings_have_one_decimal(self):
        self.assertEqual(app.round_card({"rating": 4.1999998})["rating"], 4.2)
        self.assertIsNone(app.round_card({"rating": None})["rating"])
        H.reset_limits()
        ev, r = H.run(H.CEDRIC, ip="192.0.2.96")
        for c in r["picks"] + r["reserves"] + [e for e in ev if e["type"] == "card"]:
            if c.get("rating") is not None:
                self.assertEqual(c["rating"], round(c["rating"], 1))

    def test_last_seen_capped_and_concurrent(self):
        import types
        hook = app.adapter.CappedLastSeen(budget_s=0.4)
        slow = {"http://slow.example"}

        def site(url):
            time.sleep(2 if url in slow else 0.05)
            return {"ok": url != "http://down.example", "status": 200, "checked_at": "t", "how": "site HTTP 200"}
        hook.ls = types.SimpleNamespace(site=site)
        ent = lambda url, **p: {"properties": dict({"hours": {"mon": "9-5"}, "address": "1 Main St",
                                                   "website": url}, **p)}  # noqa: E731
        es = [ent("http://slow.example"), ent("http://fast.example"), ent("http://down.example")] + \
            [ent("http://s%d.example" % i) for i in range(10)]
        t0 = time.monotonic()
        hook.prefetch(es)
        self.assertLess(time.monotonic() - t0, 0.8, "prefetch must be concurrent and capped")
        self.assertEqual(hook(es[0]), (True, {"checked_at": hook(es[0])[1]["checked_at"], "how": "hours only"}))
        self.assertTrue(hook(es[1])[0])
        self.assertFalse(hook(es[2])[0])
        self.assertFalse(hook(ent("http://x.example", address="CLOSED 1 Main St"))[0])
        self.assertEqual(hook(ent(None))[1]["how"], "hours only")
        self.assertLess(time.monotonic() - t0, 1.0, "no check waits past the run's budget")


class Walls(unittest.TestCase):
    def tearDown(self):
        os.environ["UNSAID_WALLS"] = H.WALLS_DIR

    def test_no_wall_file_is_partial_with_a_note(self):
        H.reset_limits()
        os.environ["UNSAID_WALLS"] = os.path.join(H.TMP, "nowhere")
        ev, r = H.run(H.CEDRIC, ip="192.0.2.70")
        self.assertEqual(r["status"], "partial")
        self.assertIn("no_wall", r["flags"])
        self.assertEqual(r["note"], app.adapter.NO_WALL_NOTE)
        self.assertTrue(any(e.get("state") == "partial" and e["text"] == app.adapter.NO_WALL_NOTE for e in ev))
        self.assertFalse([e for e in ev if e["type"] == "wall_name"])

    def test_directory_is_merged_and_default_is_data_walls(self):
        d = os.path.join(H.TMP, "wdir")
        os.makedirs(d, exist_ok=True)
        for i in (1, 2):
            with open(os.path.join(d, "w%d.json" % i), "w") as f:
                json.dump({"walls": [{"city": "stl", "set": "city", "answers": [
                    {"provider": "claude", "asked_at": "2026-10-28T09:00:00Z", "lane": "dated",
                     "names": [{"name": "Place %d" % i}]}]}]}, f)
        os.environ["UNSAID_WALLS"] = d
        city = {"key": "stl", "slug": "st-louis", "id": "x"}
        w = app.adapter.wall_for(city, [], H.TMP)
        self.assertFalse(w["missing"])
        self.assertEqual(sorted(n["name"] for a in w["answers"] for n in a["names"]), ["Place 1", "Place 2"])
        os.environ.pop("UNSAID_WALLS")
        self.assertEqual(app.adapter.WALLS_DEFAULT, os.path.join(os.path.dirname(H.SERVER), "data", "walls"))
        self.assertNotIn("research", app.adapter.WALLS_DEFAULT)


if __name__ == "__main__":
    unittest.main(verbosity=2)
