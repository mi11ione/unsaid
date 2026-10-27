"""Qloo client for UNSAID. Standard library only.

- Base URL is the hackathon host (keys do not work on staging or production).
- Key comes from QLOO_API_KEY and is sent in the X-Api-Key header. It is never logged or hashed.
- Every GET goes through a content-hash cache: sha256 of mode + base + path + canonical query.
- Pacing: a token bucket of 4 requests/s (entrants measured a 5/s limit; the 6th call within ~1 s gets a 429).
- Retries: up to 2 on 429/5xx/network errors. Retry-After is honoured; otherwise backoff 1 s, then 2 s, plus jitter.
- Every call is appended to a trace (JSONL plus in-memory) with the URL (no key), status, ms, cache hit and result count.
- Fake mode (fake=True) swaps the HTTP transport for unsaid.fake.FakeQloo. The cache lives in its own directory,
  so fake responses can never land in the live cache.
"""
import hashlib
import json
import os
import random
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

BASE_URL = "https://hackathon.api.qloo.com"
KIT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CACHE = os.path.join(KIT_DIR, ".cache")  # gitignored; Qloo data must never go in a public repo


class QlooError(Exception):
    def __init__(self, status, body, url):
        super().__init__("Qloo HTTP %s for %s: %s" % (status, url, str(body)[:300]))
        self.status, self.body, self.url = status, body, url


def canonical_query(params):
    """Stable query string. Lists are comma-joined in the order given: the engine canonicalises
    order-free sets (sorted IDs) before calling, so identical requests hash identically."""
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


class TokenBucket:
    def __init__(self, rate=4.0, burst=4):
        self.rate, self.capacity = rate, burst
        self.tokens, self.t = float(burst), time.monotonic()
        self.lock = threading.Lock()

    def take(self):
        while True:
            with self.lock:
                now = time.monotonic()
                self.tokens = min(self.capacity, self.tokens + (now - self.t) * self.rate)
                self.t = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
                wait = (1 - self.tokens) / self.rate
            time.sleep(wait)


class HttpTransport:
    def __init__(self, key, timeout=8.0):
        self.key, self.timeout = key, timeout

    def get(self, url):
        req = urllib.request.Request(url, headers={"X-Api-Key": self.key, "Accept": "application/json",
                                                   "User-Agent": "unsaid-kit/0.3"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return r.status, r.read().decode("utf-8"), dict(r.headers)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace") if e.fp else ""
            return e.code, body, dict(e.headers or {})


class Qloo:
    def __init__(self, fake=False, cache_dir=None, use_cache=True, trace_path=None, rate=4.0,
                 timeout=8.0, retries=2, base_url=BASE_URL, refresh=False):
        self.fake = fake
        self.base = base_url
        self.use_cache = use_cache
        self.refresh = refresh  # True: ignore cached reads but still write (used by rerun determinism tests)
        mode = "fake" if fake else "live"
        self.cache_dir = os.path.join(cache_dir or DEFAULT_CACHE, mode)
        os.makedirs(self.cache_dir, exist_ok=True)
        self.retries = retries
        self.trace = []
        self.trace_path = trace_path
        self.calls = {"network": 0, "cache": 0}
        if fake:
            from unsaid.fake import FakeQloo
            self.transport = FakeQloo()
            self.bucket = None
        else:
            key = os.environ.get("QLOO_API_KEY", "").strip()
            if not key:
                raise SystemExit("QLOO_API_KEY is not set. Export it, or run with --fake to use canned responses.")
            self.transport = HttpTransport(key, timeout)
            self.bucket = TokenBucket(rate)

    # ---- core GET -------------------------------------------------------
    def get(self, path, params, label=""):
        q = canonical_query(params)
        url = "%s%s?%s" % (self.base, path, q)
        mode = "live"
        if self.fake:  # the fake world's knobs are part of the key, so changing them never serves stale responses
            mode = "fake|w=%s" % os.environ.get("FAKE_TASTE_WEIGHT", "0.55")
        key = hashlib.sha256(("%s|%s" % (mode, url)).encode()).hexdigest()
        fpath = os.path.join(self.cache_dir, key[:2], key + ".json")
        t0 = time.monotonic()
        if self.use_cache and not self.refresh and os.path.exists(fpath):
            with open(fpath) as f:
                data = json.load(f)
            self.calls["cache"] += 1
            self._log(label, url, 200, t0, True, data, key)
            return data
        status, body, headers = None, None, {}
        for attempt in range(self.retries + 1):
            if self.bucket:
                self.bucket.take()
            try:
                status, body, headers = self.transport.get(url)
            except Exception as e:  # network error, timeout
                status, body, headers = 599, str(e), {}
            self.calls["network"] += 1
            if status in (429, 500, 502, 503, 504, 599) and attempt < self.retries:
                ra = headers.get("Retry-After") or headers.get("retry-after")
                try:
                    wait = float(ra)
                except (TypeError, ValueError):
                    wait = (1.0, 2.0)[attempt]
                if not self.fake:
                    time.sleep(wait + random.uniform(0, 0.25))
                self._log(label + " (retry)", url, status, t0, False, None, key)
                continue
            break
        if status != 200:
            self._log(label, url, status, t0, False, None, key)
            raise QlooError(status, body, url)
        data = json.loads(body)
        if self.use_cache:
            os.makedirs(os.path.dirname(fpath), exist_ok=True)
            with open(fpath, "w") as f:
                json.dump(data, f)
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
        rec = {"label": label, "url": url, "status": status, "ms": int((time.monotonic() - t0) * 1000),
               "cache": hit, "n": n, "key": key[:12], "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        self.trace.append(rec)
        if self.trace_path:
            with open(self.trace_path, "a") as f:
                f.write(json.dumps(rec) + "\n")

    # ---- endpoints ------------------------------------------------------
    def search(self, query, types=None, take=5, location=None, radius_mi=None, label="search", **extra):
        p = {"query": query, "take": take}
        if types:
            p["types"] = types
        if location:
            p["filter.location"] = location        # "lat,lon", WKT, or a Qloo ID (reference_get-search.md)
        if radius_mi is not None:
            p["filter.radius"] = radius_mi          # miles, default 10, max 100
        p.update(extra)
        try:
            d = self.get("/search", p, label)
        except QlooError as e:
            if e.status == 404:  # documented "No results"
                return []
            raise
        return d.get("results") or []

    def tags(self, query, tag_types=None, take=10, semantic=False, label="tags"):
        p = {"filter.query": query, "take": take}
        if tag_types:
            p["filter.tag.types"] = tag_types
        if semantic:
            p["feature.semantic_search"] = True
        d = self.get("/v2/tags", p, label)
        r = d.get("results") or {}
        return r.get("tags") if isinstance(r, dict) else r

    def insights(self, params, label="insights"):
        assert "filter.type" in params
        return self.get("/v2/insights", params, label)

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
    """Per-result explainability -> ({entity_or_tag_id: score}, warning). Tolerates both
    {"signal.interests.entities":[{entity_id,score}]} and flat lists."""
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


def aggregate_explain(resp):
    """Top-level query.explainability (aggregate impact). Shape is not documented by example;
    accept {"signal.interests.entities": {"top_3":[..], ...}} or {"top_3": [...]} or a flat list.
    Returns {subset_name: {id: score}} plus a warning if present."""
    q = resp.get("query") or {}
    ex = q.get("explainability")
    out, warn = {}, None
    if not isinstance(ex, dict):
        return out, warn
    warn = ex.get("warning")

    def eat(name, lst):
        d = out.setdefault(name, {})
        for it in lst:
            if isinstance(it, dict):
                i = it.get("entity_id") or it.get("id")
                s = it.get("score", it.get("value", it.get("impact")))
                if i is not None and s is not None:
                    d[i] = float(s)
    for k, v in ex.items():
        if k == "warning":
            continue
        if isinstance(v, dict):
            for sub, lst in v.items():
                if isinstance(lst, list):
                    eat(sub, lst)
        elif isinstance(v, list):
            eat(k, v)
    return out, warn


def write_trace_md(trace, path, title="Call trace"):
    lines = ["# %s" % title, "", "| # | step | status | ms | cache | n | request (key redacted; never in URL) |",
             "|---|---|---|---|---|---|---|"]
    for i, r in enumerate(trace, 1):
        lines.append("| %d | %s | %s | %s | %s | %s | `%s` |" % (i, r["label"], r["status"], r["ms"],
                                                               "hit" if r["cache"] else "net", r["n"], r["url"]))
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
