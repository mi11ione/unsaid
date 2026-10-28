"""Per-request stage timing for diag.timing (seconds), so we can see where the host spends a run.

Qloo stages are wall-clock spans (first call start -> last call end) of the calls whose step label starts with:
  pool C4 · rescore C6' · ids C7 · cap CAP · resolve C1/C2
Calls run in parallel, so a span is not the sum of call times. strike = from the `pool` event to the last `strike`
event (the local matcher, including any C7 lookups in between). gemini = the live taste ask, start to answer or
timeout. queue = waiting for admission. total = request start to the done line.
"""
import threading
import time

PREFIXES = (("C4", "pool"), ("C6", "rescore"), ("C7", "ids"), ("CAP", "cap"), ("C1", "resolve"), ("C2", "resolve"))
KEYS = ("pool", "rescore", "strike", "ids", "cap", "gemini", "total", "resolve", "queue")


def stage_of(label):
    label = str(label or "")
    for p, s in PREFIXES:
        if label.startswith(p):
            return s
    return "other"


class Timing:
    def __init__(self):
        self.t0 = time.monotonic()
        self.spans = {}
        self.first, self.last = {}, {}
        self.lock = threading.Lock()

    def now(self):
        return time.monotonic()

    def span(self, stage, a, b):
        with self.lock:
            lo, hi = self.spans.get(stage, (a, b))
            self.spans[stage] = (min(lo, a), max(hi, b))

    def event(self, kind):
        t = time.monotonic()
        with self.lock:
            self.first.setdefault(kind, t)
            self.last[kind] = t

    def instrument(self, q):
        """Times every Qloo call of this run's client by its step label (shadows the bound method)."""
        orig = q.get

        def timed(path, params, label="", *a, **kw):
            s = time.monotonic()
            try:
                return orig(path, params, label, *a, **kw)
            finally:
                self.span(stage_of(label), s, time.monotonic())
        q.get = timed
        return q

    def result(self):
        with self.lock:
            out = {k: round(hi - lo, 3) for k, (lo, hi) in self.spans.items() if k in KEYS}
            if "pool" in self.first and "strike" in self.last and self.last["strike"] >= self.first["pool"]:
                out["strike"] = round(self.last["strike"] - self.first["pool"], 3)
        out["total"] = round(time.monotonic() - self.t0, 3)
        return {k: out.get(k) for k in KEYS}
