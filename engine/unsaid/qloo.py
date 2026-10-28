"""Qloo client for UNSAID (UNSAID.md §3.1, §3.2 pacing, §3.5 caching). Standard library only.

- Base URL is the hackathon host. The key comes only from env QLOO_API_KEY and goes only in the X-Api-Key header.
  It is never logged, hashed, put in a URL, a trace or a file.
- Generic User-Agent; no name or email in any request.
- Cache: .cache/<mode>/ (gitignored). Key = sha256(path + "?" + canonical query). Exact keys only. TTL: /search and
  /v2/tags 30 d, insights 24 h; `frozen=True` (demo sets) ignores TTL.
- Pacing: ONE global token bucket shared by every client and every run in the process: 3/s steady, bursts <= 5.
- Retries: up to 2 on 429/5xx/network errors, honouring Retry-After. A 429 is never "not found in Qloo".
- Timeouts: 12 s per pool call, 3 s per rescoring call (callers pass `timeout`); a per-run hard deadline (90 s).
- The "never send" list is enforced here (NeverSend): signal.location*, filter.location.query, Tripadvisor/Resy
  filters, a tag love in a discovery call, tag + entity signals in one call. bias.trends is pinned to "off".
- Quota guard: reads the month limit/remaining from response headers (names recorded by probes.py P9); at 85 % used
  the module flag `quota_state()["limited"]` turns on and fresh runs return `limited`.
- Fake mode swaps the transport for unsaid.fake.FakeQloo; its cache directory is separate (.cache/fake).
"""
import gzip
import hashlib
import http.client
import json
import os
import random
import re
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

BASE_URL = "https://hackathon.api.qloo.com"
KIT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CACHE = os.path.join(KIT_DIR, ".cache")  # gitignored; Qloo data must never go in a public repo
USER_AGENT = "Python-urllib/%d.%d" % sys.version_info[:2]  # generic on purpose

RATE, BURST = 8.0, 10  # live P9 headers: 10/s per key, 50k/month; 8/s steady, bursts of 10
TIMEOUT_POOL, TIMEOUT_RESCORE, TIMEOUT_DEFAULT = 12.0, 6.0, 12.0   # rescore 3 -> 6 s: concurrent C6′ calls answer in up to 5.6 s live
HARD_CAP_S = 90.0
TTL = {"/search": 30 * 86400, "/v2/tags": 30 * 86400, "/v2/insights": 86400, "/entities": 30 * 86400}
DEFAULT_AFFINITY = 0.7649962877984056   # Qloo's default affinity ("0.765"; field-observed value), compared within 1e-6
TIE_EPS = 1e-6
QUOTA_LIMIT_FRAC = 0.85


class QlooError(Exception):
    def __init__(self, status, body, url):
        super().__init__("Qloo HTTP %s for %s: %s" % (status, url, str(body)[:300]))
        self.status, self.body, self.url = status, body, url

    @property
    def busy(self):
        """429/5xx/timeouts: Qloo is busy, which is never the same as 'not found'."""
        return self.status in (429, 500, 502, 503, 504, 599)


class QlooDeadline(QlooError):
    def __init__(self, url):
        super().__init__(599, "hard cap of %.0f s reached" % HARD_CAP_S, url)


class BudgetExceeded(SystemExit):
    """--budget N: stop before the (N+1)-th network call. A SystemExit, so no engine `except` swallows it and the
    script ends at once (worker threads re-raise it through the executor)."""


class NeverSend(ValueError):
    """A request that UNSAID.md §3.1 forbids. Raised before anything leaves the process."""


def canonical_query(params):
    """Stable query string. Lists are comma-joined in the order given: the engine canonicalises order-free sets
    (sorted IDs) before calling, so identical requests hash identically."""
    items = []
    for k in sorted(params):
        v = params[k]
        if v is None:
            continue
        if isinstance(v, (list, tuple)):
            v = ",".join(str(x) for x in v)
        elif isinstance(v, bool):
            v = "true" if v else "false"
        items.append((k, str(v)))
    return urllib.parse.urlencode(items, safe=":,()")


def check_never_send(path, params):
    """UNSAID.md §3.1 'Never send', enforced in the client. Mutates params only to pin bias.trends=off."""
    for k in params:
        lk = k.lower()
        if lk.startswith("signal.location"):
            raise NeverSend("%s: signal.location* timed out in 4 of 6 cities" % k)
        if lk == "filter.location.query":
            raise NeverSend("filter.location.query: 29 of 50 results landed outside the borough")
        if "tripadvisor" in lk or "resy" in lk:
            raise NeverSend("%s: Tripadvisor/Resy fields cover 97 and 24 of 152 places" % k)
        if "key" in lk and "api" in lk:
            raise NeverSend("the API key goes in the X-Api-Key header only")
    if path == "/v2/insights":
        has_tags = bool(params.get("signal.interests.tags"))
        if has_tags and not params.get("filter.results.entities"):
            raise NeverSend("a tag love in a discovery call (16 s p50, 28 s max); tags only rescore a fixed set")
        if has_tags and params.get("signal.interests.entities"):
            raise NeverSend("entity and tag signals in one call (afterglow: 1 to 32 of 40 scored)")
        bt = params.get("bias.trends")
        if bt is None:
            params["bias.trends"] = "off"
        elif str(bt) != "off":
            raise NeverSend("bias.trends must stay 'off' ('high' replaced the whole dining set)")
        try:
            if int(params.get("take", 20)) > 50:
                raise NeverSend("take > 50 returns a 400")
        except (TypeError, ValueError):
            pass


class TokenBucket:
    def __init__(self, rate=RATE, burst=BURST):
        self.rate, self.capacity = float(rate), float(burst)
        self.tokens, self.t = float(burst), time.monotonic()
        self.lock = threading.Lock()

    def take(self, deadline=None):
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


BUCKET = TokenBucket(RATE, BURST)   # one global bucket shared by all runs (UNSAID.md §3.2)


# ---- quota guard ---------------------------------------------------------------------------------------------
_QUOTA = {"limited": False, "used_frac": None, "limit": None, "remaining": None, "names": None, "at": None}
_QLOCK = threading.Lock()


def p9_headers_path(fake):
    return os.path.join(DEFAULT_CACHE, "fake" if fake else "live", "p9_headers.json")


def _quota_names(fake):
    try:
        with open(p9_headers_path(fake)) as f:
            d = json.load(f)
        if d.get("month_limit") and d.get("month_remaining"):
            return d["month_limit"].lower(), d["month_remaining"].lower()
    except (OSError, ValueError):
        pass
    return None


def classify_rate_headers(headers):
    """Pick the month limit / remaining header names out of a response's headers. Used by P9 and as the fallback
    when P9 has not run. Monthly = the name says month, or the limit is >= 1000 (per-second limits are single-digit)."""
    low = {k.lower(): v for k, v in (headers or {}).items()}
    rate = {k: v for k, v in low.items() if re.search(r"rate.?limit|quota|limit|remaining|reset|retry", k)}
    lim, rem = None, None
    for k, v in sorted(rate.items()):
        try:
            n = float(str(v).split(",")[0].split(";")[0])
        except ValueError:
            continue
        monthly = "month" in k or (n >= 1000 and "second" not in k and "minute" not in k)
        if not monthly:
            continue
        if "remaining" in k and rem is None:
            rem = k
        elif "limit" in k and "remaining" not in k and "reset" not in k and lim is None:
            lim = k
    return {"all": sorted(rate), "month_limit": lim, "month_remaining": rem}


def update_quota(headers, fake):
    names = _quota_names(fake)
    low = {k.lower(): v for k, v in (headers or {}).items()}
    if not names:
        c = classify_rate_headers(headers)
        names = (c["month_limit"], c["month_remaining"]) if c["month_limit"] and c["month_remaining"] else None
    if not names or names[0] not in low or names[1] not in low:
        return
    try:
        lim = float(str(low[names[0]]).split(",")[0])
        rem = float(str(low[names[1]]).split(",")[0])
    except ValueError:
        return
    if lim <= 0:
        return
    with _QLOCK:
        used = 1 - rem / lim
        _QUOTA.update({"limit": lim, "remaining": rem, "used_frac": used, "names": list(names),
                       "limited": used >= QUOTA_LIMIT_FRAC, "at": time.strftime("%Y-%m-%dT%H:%M:%S")})


def quota_state():
    with _QLOCK:
        return dict(_QUOTA)


# ---- transport --------------------------------------------------------------------------------------------------
# Render free is ~0.1 CPU, so the HTTP layer is built to spend as little CPU per call as possible (measured 28 Oct):
# - one SSLContext for the process (building one per call reloads the CA bundle: ~4.5 ms CPU each on the Mac);
# - keep-alive connections, pooled per host (a fresh TLS handshake per call: ~11 ms CPU vs ~2 ms reused);
# - gzip: an insights page is ~1.4 MB of JSON; gzipped it is ~220 KB on the wire, and reading it costs ~3 ms CPU
#   (+1.6 ms gunzip) instead of ~22 ms through the SSL socket.
# QLOO_GZIP=0 turns gzip off; QLOO_POOL sets how many idle connections are kept (default 8). Busy calls never wait for
# a pooled connection: when all are in use a new one is opened, and kept afterwards only if the pool has room.
POOL_IDLE = int(os.environ.get("QLOO_POOL", "8"))
GZIP_ON = os.environ.get("QLOO_GZIP", "1") != "0"
_SSL = {"ctx": None}
_POOLS = {}
_PLOCK = threading.Lock()


def _ssl_ctx():
    with _PLOCK:
        if _SSL["ctx"] is None:
            _SSL["ctx"] = ssl.create_default_context()
        return _SSL["ctx"]


class _Pool:
    def __init__(self, host, port):
        self.host, self.port = host, port
        self.idle = []
        self.lock = threading.Lock()

    def take(self, timeout):
        with self.lock:
            while self.idle:
                c = self.idle.pop()
                if c.sock is not None:
                    c.sock.settimeout(timeout)
                    return c, True
        return http.client.HTTPSConnection(self.host, self.port, timeout=timeout, context=_ssl_ctx()), False

    def give(self, c):
        with self.lock:
            if len(self.idle) < POOL_IDLE and c.sock is not None:
                self.idle.append(c)
                return
        c.close()


def _pool(host, port):
    with _PLOCK:
        k = (host, port)
        if k not in _POOLS:
            _POOLS[k] = _Pool(host, port)
        return _POOLS[k]


class HttpTransport:
    """GET over pooled keep-alive HTTPS with gzip. Returns (status, body text, headers) like urllib did; per-instance
    counters in `stats` (one client per run) feed the server's diag.timing."""

    def __init__(self, key):
        self.key = key
        self.stats = {"calls": 0, "new_conns": 0, "reused": 0, "stale_retries": 0, "wire_bytes": 0, "body_bytes": 0}
        self._slock = threading.Lock()

    def _count(self, **kv):
        with self._slock:
            for k, v in kv.items():
                self.stats[k] += v

    def get(self, url, timeout=TIMEOUT_DEFAULT):
        u = urllib.parse.urlsplit(url)
        pool = _pool(u.hostname, u.port or 443)
        path = u.path + ("?" + u.query if u.query else "")
        hdrs = {"X-Api-Key": self.key, "Accept": "application/json", "User-Agent": USER_AGENT,
                "Accept-Encoding": "gzip" if GZIP_ON else "identity"}
        for attempt in (0, 1):
            conn, reused = pool.take(timeout)
            try:
                conn.request("GET", path, headers=hdrs)
                r = conn.getresponse()
                raw = r.read()
            except (http.client.RemoteDisconnected, http.client.BadStatusLine, ConnectionResetError,
                    BrokenPipeError) as e:
                conn.close()
                if reused and attempt == 0:      # the server closed an idle keep-alive connection: one fresh retry
                    self._count(stale_retries=1)
                    continue
                raise e
            except Exception:
                conn.close()
                raise
            break
        wire = len(raw)
        if r.will_close:
            conn.close()
        else:
            pool.give(conn)
        if (r.getheader("Content-Encoding") or "").lower() == "gzip":
            raw = gzip.decompress(raw)
        self._count(calls=1, wire_bytes=wire, body_bytes=len(raw), **{"reused" if reused else "new_conns": 1})
        return r.status, raw.decode("utf-8", "replace"), dict(r.headers)


def redact(s):
    """Belt and braces: nothing that looks like a key ever reaches a log or a trace."""
    key = os.environ.get("QLOO_API_KEY", "").strip()
    s = str(s)
    if key and len(key) >= 8:
        s = s.replace(key, "<redacted>")
    return re.sub(r"(?i)(api[_-]?key=)[^&\s]+", r"\1<redacted>", s)


class Qloo:
    def __init__(self, fake=False, cache_dir=None, use_cache=True, trace_path=None, retries=2, base_url=BASE_URL,
                 refresh=False, frozen=False, bucket=None, deadline_s=None, budget=None):
        self.fake = fake
        self.base = base_url
        self.use_cache = use_cache
        self.refresh = refresh  # True: ignore cached reads but still write (rerun determinism)
        self.frozen = frozen    # demo sets: no TTL
        mode = "fake" if fake else "live"
        self.cache_dir = os.path.join(cache_dir or DEFAULT_CACHE, mode)
        os.makedirs(self.cache_dir, exist_ok=True)
        self.retries = retries
        self.budget = budget    # max network calls (cache hits are free); None = unlimited
        self.trace = []
        self.trace_path = trace_path
        self.calls = {"network": 0, "cache": 0, "errors": 0}
        self.headers_seen = {}
        self.lock = threading.Lock()
        self.deadline = None
        self.on_call = None     # callback(rec) after every call (api streams "calls" events from it)
        if deadline_s:
            self.start_deadline(deadline_s)
        if fake:
            from unsaid.fake import FakeQloo
            self.transport = FakeQloo()
            self.bucket = bucket   # no pacing in fake mode unless a test passes a bucket
        else:
            key = os.environ.get("QLOO_API_KEY", "").strip()
            if not key:
                raise SystemExit("QLOO_API_KEY is not set. Export it, or run with --fake to use canned responses.")
            self.transport = HttpTransport(key)
            self.bucket = bucket or BUCKET

    def start_deadline(self, seconds=HARD_CAP_S):
        self.deadline = time.monotonic() + seconds

    # ---- core GET -------------------------------------------------------
    def cache_key(self, path, q):
        k = "%s?%s" % (path, q)
        if self.fake:  # the fake world's knobs are part of the key, so changing them never serves stale responses
            from unsaid.fake import WORLD_V
            k = "fake|%s|%s|%s|%s" % (WORLD_V, os.environ.get("FAKE_TASTE_WEIGHT", "0.55"),
                                      os.environ.get("FAKE_TIE_SHARE", "0.08") + "|" +
                                      os.environ.get("FAKE_TIE_LOVES", ""), k)
        return hashlib.sha256(k.encode()).hexdigest()

    def _fresh(self, fpath, path):
        if self.frozen:
            return True
        ttl = TTL.get(path, 86400)
        try:
            return time.time() - os.path.getmtime(fpath) <= ttl
        except OSError:
            return False

    def get(self, path, params, label="", timeout=None, unsafe_probe=False):
        params = dict(params)
        if not unsafe_probe:
            check_never_send(path, params)
        q = canonical_query(params)
        url = "%s%s?%s" % (self.base, path, q)
        key = self.cache_key(path, q)
        fpath = os.path.join(self.cache_dir, key[:2], key + ".json")
        t0 = time.monotonic()
        if self.use_cache and not self.refresh and os.path.exists(fpath) and self._fresh(fpath, path):
            try:
                with open(fpath) as f:
                    data = json.load(f)
                with self.lock:
                    self.calls["cache"] += 1
                self._log(label, url, 200, t0, True, data, key)
                return data
            except ValueError:
                pass
        status, body, headers = None, None, {}
        for attempt in range(self.retries + 1):
            if self.deadline is not None and time.monotonic() >= self.deadline:
                self._log(label + " (deadline)", url, 599, t0, False, None, key)
                raise QlooDeadline(url)
            if self.bucket and not self.bucket.take(self.deadline):
                self._log(label + " (deadline)", url, 599, t0, False, None, key)
                raise QlooDeadline(url)
            with self.lock:
                if self.budget is not None and self.calls["network"] >= self.budget:
                    raise BudgetExceeded("BUDGET EXCEEDED: stopped before Qloo network call %d (--budget %d); "
                                         "QLOO_NETWORK_CALLS=%d" % (self.calls["network"] + 1, self.budget,
                                                                     self.calls["network"]))
                self.calls["network"] += 1
                n_net = self.calls["network"]
            if self.budget is not None and n_net % 10 == 0:
                print("  [qloo] %d of %d budgeted network calls used%s" % (n_net, self.budget,
                                                                         " [FAKE]" if self.fake else ""), flush=True)
            to = timeout or TIMEOUT_DEFAULT
            if self.deadline is not None:
                to = max(0.5, min(to, self.deadline - time.monotonic()))
            try:
                status, body, headers = self.transport.get(url, timeout=to) if not self.fake else \
                    self.transport.get(url)
            except Exception as e:  # network error, timeout
                status, body, headers = 599, redact(e), {}
            with self.lock:
                for k, v in (headers or {}).items():
                    self.headers_seen[k] = v
            if headers:
                update_quota(headers, self.fake)
            if status in (429, 500, 502, 503, 504, 599) and attempt < self.retries:
                ra = (headers or {}).get("Retry-After") or (headers or {}).get("retry-after")
                try:
                    wait = float(ra)
                except (TypeError, ValueError):
                    wait = (1.0, 2.0)[min(attempt, 1)]
                wait += random.uniform(0, 0.25)
                if self.deadline is not None and time.monotonic() + wait >= self.deadline:
                    self._log(label + " (deadline)", url, status, t0, False, None, key)
                    raise QlooDeadline(url)
                if not self.fake:
                    time.sleep(wait)
                self._log(label + " (retry)", url, status, t0, False, None, key)
                continue
            break
        if status != 200:
            with self.lock:
                self.calls["errors"] += 1
            self._log(label, url, status, t0, False, None, key)
            raise QlooError(status, redact(body), url)
        data = json.loads(body)
        if self.use_cache:
            os.makedirs(os.path.dirname(fpath), exist_ok=True)
            tmp = "%s.%d.%d.tmp" % (fpath, os.getpid(), threading.get_ident())
            with open(tmp, "w") as f:
                f.write(body)          # the body is already JSON: writing it as is saves a full re-serialisation
            os.replace(tmp, fpath)
        self._log(label, url, status, t0, False, data, key)
        return data

    def _log(self, label, url, status, t0, hit, data, key):
        n = None
        if isinstance(data, dict):
            r = data.get("results")
            if isinstance(r, dict):
                n = len(r.get("entities") or r.get("tags") or [])
            elif isinstance(r, list):
                n = len(r)
        rec = {"label": label, "url": redact(url), "status": status, "ms": int((time.monotonic() - t0) * 1000),
               "cache": hit, "n": n, "key": key[:12], "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        with self.lock:
            self.trace.append(rec)
            if self.trace_path:
                with open(self.trace_path, "a") as f:
                    f.write(json.dumps(rec) + "\n")
        cb = self.on_call
        if cb is not None and not label.endswith("(retry)"):
            try:
                cb(rec)
            except Exception:
                pass

    # ---- endpoints ------------------------------------------------------
    def search(self, query, types=None, take=5, location=None, radius_mi=None, label="search", **extra):
        """A 404 is Qloo's documented 'No results' -> []. A 429/5xx raises (QlooError.busy): never 'not found'."""
        p = {"query": query, "take": take}
        if types:
            p["types"] = types
        if location:
            p["filter.location"] = location        # "lat,lon", WKT, or a Qloo ID (reference_get-search.md)
        if radius_mi is not None:
            p["filter.radius"] = radius_mi          # miles, default 10, max 100
        p.update(extra)
        try:
            d = self.get("/search", p, label, timeout=TIMEOUT_DEFAULT)
        except QlooError as e:
            if e.status == 404:
                return []
            raise
        return d.get("results") or []

    def tags(self, query, tag_types=None, take=10, semantic=False, label="tags"):
        p = {"filter.query": query, "take": take}
        if tag_types:
            p["filter.tag.types"] = tag_types
        if semantic:
            p["feature.semantic_search"] = True
        try:
            d = self.get("/v2/tags", p, label, timeout=TIMEOUT_DEFAULT)
        except QlooError as e:
            if e.status == 404:
                return []
            raise
        r = d.get("results") or {}
        return r.get("tags") if isinstance(r, dict) else r

    def insights(self, params, label="insights", timeout=TIMEOUT_POOL, unsafe_probe=False):
        assert "filter.type" in params
        return self.get("/v2/insights", params, label, timeout=timeout, unsafe_probe=unsafe_probe)

    def entities(self, ids, label="entities"):
        d = self.get("/entities", {"entity_ids": sorted(ids)}, label)
        r = d.get("results")
        if isinstance(r, dict):
            return r.get("entities") or []
        return r or []


# ---- tolerant field access (the response nests most fields under `properties`) ----------
def prop(e, *names, default=None):
    """Look a field up in the places the docs show it: properties.<f>, properties.geocode.<f>, top level."""
    p = e.get("properties") or {}
    g = p.get("geocode") or {}
    for n in names:
        for src in (p, g, e):
            if isinstance(src, dict) and src.get(n) is not None:
                return src[n]
    return default


def affinity(e):
    q = e.get("query") or {}
    a = q.get("affinity")
    if a is None:
        a = e.get("affinity")
    return a


def is_default_affinity(a):
    return a is not None and abs(float(a) - DEFAULT_AFFINITY) <= TIE_EPS


def latlon(e):
    loc = e.get("location") or {}
    lat = loc.get("lat", prop(e, "lat", "latitude"))
    lon = loc.get("lon", prop(e, "lon", "longitude"))
    if lat is None or lon is None:
        return None
    return float(lat), float(lon)


def tag_ids(e):
    return [t.get("id") or t.get("tag_id") for t in (e.get("tags") or []) if isinstance(t, dict)]


def explain_items(e):
    """Per-result explainability -> ({entity_or_tag_id: score}, warning). Kept for the raw log only: UNSAID shows
    no explainability shares anywhere (UNSAID.md §3.3 step 8)."""
    q = e.get("query") or {}
    ex = q.get("explainability")
    warn = None
    out = {}
    if isinstance(ex, dict):
        warn = ex.get("warning")
        for k, v in ex.items():
            if k == "warning":
                continue
            if isinstance(v, list):
                for it in v:
                    if isinstance(it, dict):
                        i = it.get("entity_id") or it.get("id") or it.get("tag")
                        s = it.get("score", it.get("value"))
                        if i is not None and s is not None:
                            out[i] = float(s)
    elif isinstance(ex, list):
        for it in ex:
            i = it.get("entity_id") or it.get("id")
            if i:
                out[i] = float(it.get("score", 0))
    if q.get("explainability.warning"):
        warn = q.get("explainability.warning")
    return out, warn


def write_trace_md(trace, path, title="Call trace"):
    lines = ["# %s" % title, "", "| # | step | status | ms | cache | n | request (key in the X-Api-Key header, never in the URL) |",
             "|---|---|---|---|---|---|---|"]
    for i, r in enumerate(trace, 1):
        lines.append("| %d | %s | %s | %s | %s | %s | `%s` |" % (i, r["label"], r["status"], r["ms"],
                                                               "hit" if r["cache"] else "net", r["n"], redact(r["url"])))
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
