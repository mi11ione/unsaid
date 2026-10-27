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
        return H.make_lane(transport, **dict({"GEMINI_RPD": "10"}, **env))

    @staticmethod
    def ok_transport(calls):
        def t(prompt):
            calls.append(prompt)
            text = json.dumps([{"name": "Place %d" % i, "neighbourhood": "Soulard"} for i in range(15)])
            return 200, {"candidates": [{"content": {"parts": [{"text": text}]}}]}
        return t

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

    def test_live_answer_shape_and_phrasings(self):
        calls = []
        s = self.lane(self.ok_transport(calls)).for_country("US")
        a = s.ask_taste("St. Louis", ["Frankie Beverly & Maze", "The Original Kings of Comedy", "Rib Tips"], "loc",
                        ["1", "2", "3"])
        self.assertEqual(s.state, "live")
        self.assertEqual(a["lane"], "live")
        self.assertTrue(a["asked_at"].endswith("Z"))
        self.assertEqual(len(a["names"]), 12)
        self.assertEqual(a["phrasing"], "I love Frankie Beverly & Maze, The Original Kings of Comedy and Rib Tips. "
                                        "Where should I eat and drink in St. Louis?")
        self.assertTrue(calls[0].endswith("Real, currently open venues only."))
        self.assertIsNone(s.ask_taste("St. Louis", ["X"], "loc", ["9"]), "a second taste ask in one run")
        hoods = ["Soulard", "The Hill", "Midtown", "Downtown"]
        got = [s.ask_street(h, "St. Louis", "loc") for h in hoods]
        self.assertEqual([g is not None for g in got], [True, True, True, False], "at most 3 street asks")
        self.assertEqual(got[0]["phrasing"], "Best places to eat and drink in Soulard, St. Louis")
        self.assertEqual(len(calls), 4)

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
        self.assertIsNone(s2.ask_street("Soulard", "St. Louis", "loc"))
        self.assertEqual(len(calls), 1)

    def test_rpd_guard_at_80_percent(self):
        calls = []
        lane = self.lane(self.ok_transport(calls))           # RPD 10 -> at most 8 calls
        for i in range(10):
            lane.for_country("US").ask_taste("St. Louis", ["L%d" % i], "loc", [str(i)])
        self.assertEqual(len(calls), 8)
        self.assertEqual(lane.for_country("US").reason, "daily guard")

    def test_run_with_live_lane_burns_a_card(self):
        """Taste names join the wall as lane=live; a street answer naming a card burns it and a reserve rises."""
        H.reset_limits()
        first = {}

        def t(prompt):
            if prompt.startswith("Best places") and not first:
                first["hood"] = prompt
                names = [{"name": first_pick["name"], "neighbourhood": first_pick["neighbourhood"]}]
            else:
                names = [{"name": "Pappy's Smokehouse", "neighbourhood": "Midtown"}]
            return 200, {"candidates": [{"content": {"parts": [{"text": json.dumps(names)}]}}]}
        _, base = H.run(H.CEDRIC, ip="192.0.2.50")          # cached run: learn pick 1 to make Gemini name it
        first_pick = base["picks"][0]
        old = app.GEMINI
        app.GEMINI = self.lane(t)
        H.clear_results()
        try:
            ev, r = H.run(H.CEDRIC, ip="192.0.2.51", country="US")
        finally:
            app.GEMINI = old
        live = [e for e in ev if e["type"] == "wall_name" and e["lane"] == "live"]
        self.assertTrue(live and live[0]["provider"] == "gemini")
        self.assertNotIn("dated_only", r["flags"])
        self.assertEqual(r["burn"]["burned"][0]["card_id"], first_pick["id"])
        self.assertNotIn(first_pick["id"], [p["id"] for p in r["picks"]])
        self.assertEqual(len(r["picks"]), 7)
        p0 = r["picks"][0]
        self.assertEqual(p0["never_said"]["street_asks"],
                         sum(1 for b in r["burn"]["asked"] if b["neighbourhood"] == p0["neighbourhood"]))
        self.assertTrue(any(e["type"] == "burn" for e in ev))


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
