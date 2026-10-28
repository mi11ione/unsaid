"""Pacing and guards the server owns (UNSAID.md §2.2, §3.2).

- SharedBucket: ONE token bucket for every Qloo call of every run, a steady 3/s with bursts of <= 5.
- Admission: fresh runs wait their turn in FIFO order; waiters see runs ahead and an ETA (`queued`).
- IpLimiter: more than 3 fresh runs per IP per hour -> `limited`.
- QlooQuota: the monthly quota guard; at 85% fresh runs stop (`limited`). It reads the remaining quota from
  Qloo's response headers once P9 has named them (QLOO_QUOTA_HEADERS), and counts network calls itself meanwhile.
"""
import json
import os
import threading
import time
from collections import deque


class SharedBucket:
    def __init__(self, rate=3.0, burst=5):
        self.rate, self.capacity = float(rate), float(burst)
        self.tokens, self.t = float(burst), time.monotonic()
        self.lock = threading.Lock()

    def take(self, deadline=None):
        """Blocks for a token. With a monotonic `deadline`, returns False instead of waiting past it."""
        while True:
            with self.lock:
                now = time.monotonic()
                self.tokens = min(self.capacity, self.tokens + (now - self.t) * self.rate)
                self.t = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return True
                wait = (1 - self.tokens) / self.rate
            if deadline is not None and time.monotonic() + wait > deadline:
                return False
            time.sleep(wait)


class Admission:
    """FIFO admission for fresh runs. `max_active` runs share the bucket at once; the rest are `queued`."""

    def __init__(self, max_active=2, avg_run_s=20.0):
        self.max_active = max(1, int(max_active))
        self.active = 0
        self.waiting = deque()
        self.cv = threading.Condition()
        self.avg_run_s = float(avg_run_s)

    def ahead(self, ticket):
        idx = self.waiting.index(ticket) if ticket in self.waiting else 0
        return idx + max(0, self.active - self.max_active + 1)

    def eta_s(self, ahead):
        rounds = -(-ahead // self.max_active)                       # ceil
        return int(round(max(1, rounds) * self.avg_run_s / 5.0) * 5) or 5

    def acquire(self, on_wait=None, deadline=None, poll=1.0):
        """Blocks until admitted. on_wait(ahead, eta_s) is called whenever the position changes.
        Returns True when admitted, False when `deadline` (monotonic) passes first."""
        ticket = object()
        last = None
        with self.cv:
            self.waiting.append(ticket)
            try:
                while not (self.waiting[0] is ticket and self.active < self.max_active):
                    a = self.ahead(ticket)
                    if on_wait and a != last:
                        last = a
                        self.cv.release()
                        try:
                            on_wait(a, self.eta_s(a))
                        finally:
                            self.cv.acquire()
                    if deadline is not None and time.monotonic() >= deadline:
                        return False
                    self.cv.wait(poll)
                self.active += 1
                return True
            finally:
                self.waiting.remove(ticket)
                self.cv.notify_all()

    def release(self, run_s=None):
        with self.cv:
            self.active = max(0, self.active - 1)
            if run_s:
                self.avg_run_s = 0.7 * self.avg_run_s + 0.3 * float(run_s)
            self.cv.notify_all()

    def depth(self):
        with self.cv:
            return self.active, len(self.waiting)


class IpLimiter:
    """per_hour is an int or a callable returning one (so a dated rule can change the limit without a restart)."""

    def __init__(self, per_hour=3, window_s=3600):
        self.per_hour, self.window = per_hour, float(window_s)
        self.hits = {}
        self.lock = threading.Lock()

    def _trim(self, ip, now):
        q = self.hits.setdefault(ip, deque())
        while q and now - q[0] > self.window:
            q.popleft()
        return q

    def limit(self, key=None):
        return int(self.per_hour(key) if callable(self.per_hour) else self.per_hour)

    def allowed(self, ip):
        with self.lock:
            return len(self._trim(ip, time.time())) < self.limit(ip)

    def retry_after(self, ip):
        """Seconds until this IP may start a fresh run again (0 if it may now)."""
        with self.lock:
            now = time.time()
            q = self._trim(ip, now)
            n = self.limit(ip)
            if len(q) < n:
                return 0
            return max(1, int(q[len(q) - n] + self.window - now + 0.999))

    def record(self, ip):
        with self.lock:
            now = time.time()
            q = self._trim(ip, now)
            if len(q) >= self.limit(ip):
                return False
            q.append(now)
            return True


class QlooQuota:
    """Fires at `threshold` of the month. Header names come from P9 via QLOO_QUOTA_HEADERS="<remaining>,<limit>"."""

    def __init__(self, path, monthly=10000, threshold=0.85, headers=""):
        self.path, self.monthly, self.threshold = path, int(monthly), float(threshold)
        names = [h.strip().lower() for h in (headers or "").split(",") if h.strip()]
        self.h_remaining = names[0] if names else None
        self.h_limit = names[1] if len(names) > 1 else None
        self.lock = threading.Lock()
        self.state = {"month": time.strftime("%Y-%m"), "used": 0, "remaining": None, "limit": None}
        try:
            with open(path) as f:
                s = json.load(f)
            if s.get("month") == self.state["month"]:
                self.state.update(s)
        except (OSError, ValueError):
            pass

    def _save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.state, f)
        os.replace(tmp, self.path)

    def note(self, headers):
        """Called after every network call to Qloo (cache hits cost nothing and are not counted)."""
        with self.lock:
            m = time.strftime("%Y-%m")
            if self.state["month"] != m:
                self.state = {"month": m, "used": 0, "remaining": None, "limit": None}
            self.state["used"] += 1
            low = {str(k).lower(): v for k, v in (headers or {}).items()}
            for attr, key in (("remaining", self.h_remaining), ("limit", self.h_limit)):
                if key and key in low:
                    try:
                        self.state[attr] = int(float(low[key]))
                    except ValueError:
                        pass
            self._save()

    def used_frac(self):
        with self.lock:
            lim = self.state.get("limit") or self.monthly
            if self.state.get("remaining") is not None and lim:
                return 1.0 - float(self.state["remaining"]) / lim
            return float(self.state["used"]) / max(1, self.monthly)

    def fired(self):
        return self.used_frac() >= self.threshold


class CountingTransport:
    """Wraps the engine Qloo client's transport: every network response's headers go to the quota guard."""

    def __init__(self, inner, quota):
        self.inner, self.quota = inner, quota

    def get(self, url, *args, **kwargs):
        status, body, headers = self.inner.get(url, *args, **kwargs)
        self.quota.note(headers)
        return status, body, headers
