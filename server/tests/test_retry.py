"""One failed Qloo call while resolving never sinks a query (30 Oct, 11:15 UTC: "resolve failed: RuntimeError").

  python3 -I server/tests/test_retry.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _harness as H  # noqa: E402

app = H.app
adapter = app.adapter
from unsaid import qloo as QL  # noqa: E402

LOVES = [{"text": "Sade", "hint": "artist"}, {"text": "Insecure", "hint": "movie"}, {"text": "toasted ravioli"}]


class Flaky:
    """Wraps the fake Qloo transport: the first `fail` calls answer `status` (or raise `exc`), then it answers."""

    def __init__(self, inner, fail=1, status=503, exc=None):
        self.inner, self.fail, self.status, self.exc, self.n = inner, fail, status, exc, 0

    def get(self, url, *a, **kw):
        self.n += 1
        if self.n <= self.fail:
            if self.exc is not None:
                raise self.exc
            return self.status, "{}", {}
        return self.inner.get(url)


class Retry(unittest.TestCase):
    def setUp(self):
        self.orig = adapter.make_qloo
        self.made = []

    def tearDown(self):
        adapter.make_qloo = self.orig

    def patch(self, **kw):
        def make(*a, **k):
            q = self.orig(*a, **k)
            q.use_cache = False                    # every lookup reaches the (flaky) transport
            q.transport = Flaky(q.transport, **kw)
            q.waits = []
            q.sleep = q.waits.append
            self.made.append(q)
            return q
        adapter.make_qloo = make

    def test_prepare_survives_one_failed_call(self):
        for kw in ({"status": 503}, {"status": 429}, {"exc": TimeoutError("timed out")}):
            self.patch(**kw)
            q = adapter.make_qloo("fake", H.TMP)
            prep = adapter.prepare("St. Louis", [dict(x) for x in LOVES], q, "fake")
            self.assertEqual(prep["status"], "ok", kw)
            self.assertEqual(len(q.waits), 1, kw)
            self.assertEqual([c["label"] for c in prep["loves"]], ["Sade", "Insecure", "Toasted Ravioli"])
            self.assertIsNone(q.win)               # the window is closed once resolution is over

    def test_still_busy_names_the_status_in_the_log(self):
        self.patch(fail=99, status=503)
        q = adapter.make_qloo("fake", H.TMP)
        with self.assertRaises(adapter.ResolveFailed) as cm:
            adapter.prepare("St. Louis", [dict(x) for x in LOVES], q, "fake")
        self.assertEqual(adapter.describe_error(cm.exception), "ResolveFailed (Qloo HTTP 503)")
        self.assertIsInstance(cm.exception, RuntimeError)
        self.assertEqual(q.transport.n, QL.RESOLVE_RETRIES + 1)   # bounded: the first love's call, 4 attempts

    def test_fresh_query_streams_through_a_failed_call(self):
        self.patch(fail=1, status=502)
        lines = []
        app.stream_unsaid("St. Louis", [dict(x) for x in LOVES], "198.51.100.7", "US", lines.append, bench=True)
        done = lines[-1]
        self.assertEqual(done["type"], "done")
        self.assertNotEqual(done["result"]["status"], "degraded")
        self.assertNotIn(app.COPY["degraded_none"], [x.get("text") for x in lines])
        self.assertTrue(self.made and self.made[0].transport.n >= 2)


if __name__ == "__main__":
    res = unittest.main(argv=[sys.argv[0], "-v"], exit=False).result
    sys.exit(0 if res.wasSuccessful() else 1)
