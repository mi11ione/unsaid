#!/usr/bin/env python3
"""UNSAID engine host: Python 3.9 standard library HTTP server (ThreadingHTTPServer).

  python3 -I server/app.py                      # fake mode on 127.0.0.1:8710
  UNSAID_TOKEN=... PORT=10000 python3 -I server/app.py

Endpoints (CONTRACT.md):
  GET /api/health                               always open; for the S1 wake-up ping and the pinger
  GET /api/resolve?kind=love|city&q=[&type=]    fired on blur
  GET /api/unsaid?city=&loves=                  NDJSON stream, last line {"type":"done","result":...}
  GET /api/result/<key>                         the exact-key cache, nothing else

When UNSAID_TOKEN is set, everything except /api/health needs it: `Authorization: Bearer <t>`,
`X-Unsaid-Token: <t>` or `?token=<t>`. Keys come only from the environment and never appear in a response or log.
"""
import datetime as dt
import hmac
import json
import os
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import adapter  # noqa: E402
import cache as C  # noqa: E402
import limits as L  # noqa: E402
from timing import Timing  # noqa: E402
from gemini_live import GeminiLane  # noqa: E402

try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except Exception:
    ET = dt.timezone(dt.timedelta(hours=-4))


def env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return int(default)


MODE = os.environ.get("UNSAID_MODE", "fake").lower()
if MODE == "live" and not os.environ.get("QLOO_API_KEY", "").strip():
    print("[unsaid] UNSAID_MODE=live but QLOO_API_KEY is not set: serving fake mode", file=sys.stderr)
    MODE = "fake"
if MODE != "live":
    MODE = "fake"
TOKEN = os.environ.get("UNSAID_TOKEN", "")
PROXY_SECRET = os.environ.get("UNSAID_PROXY_SECRET", "")
CACHE_DIR = C.CACHE_DIR
HARD_CAP_S = float(os.environ.get("UNSAID_HARD_CAP_S", "90"))
RANKING_AFTER_S = 20.0
CALLS_TOTAL = 27                                         # §3.2 estimate per fresh query
FAKE_PACE = os.environ.get("UNSAID_FAKE_PACE") == "1"    # pace fake calls through the bucket too (latency drills)

BUCKET = L.SharedBucket(rate=float(os.environ.get("QLOO_RATE", "3")), burst=env_int("QLOO_BURST", 5))
ADMIT = L.Admission(max_active=env_int("UNSAID_MAX_ACTIVE", 2))
FRESH_IPS = L.IpLimiter(per_hour=env_int("UNSAID_FRESH_PER_HOUR", 3))
RESOLVE_IPS = L.IpLimiter(per_hour=env_int("UNSAID_RESOLVE_PER_10MIN", 60), window_s=600)
QUOTA = L.QlooQuota(os.path.join(CACHE_DIR, "qloo_quota.json"), monthly=env_int("QLOO_MONTHLY_QUOTA", 10000),
                    threshold=float(os.environ.get("QLOO_QUOTA_GUARD", "0.85")),
                    headers=os.environ.get("QLOO_QUOTA_HEADERS", ""))
GEMINI = GeminiLane(CACHE_DIR)
RESULTS = C.ResultCache(CACHE_DIR)
INFLIGHT, INFLIGHT_LOCK = {}, threading.Lock()
BOOT = time.time()
WARM = {"state": "pending", "cpu_s": None}


def warm():
    """Boot work off the request path (engine api.warm: walls parsed, every wall name normalised and indexed, once
    per process). Runs on a background thread so /api/health answers at once; a query that arrives first just
    pays for its own share, with identical results."""
    try:
        path = adapter.walls_file(CACHE_DIR)
        fn = getattr(adapter.API, "warm", None)
        if path and fn:
            c = time.process_time()
            fn(path)
            WARM.update(state="done", cpu_s=round(time.process_time() - c, 3))
        else:
            WARM["state"] = "skipped"
    except Exception as e:  # warming is an optimisation; never a reason to fail
        WARM["state"] = "failed: %s" % type(e).__name__
    print("[unsaid] warm %s (cpu %s s)" % (WARM["state"], WARM["cpu_s"]), file=sys.stderr)

COPY = {  # UNSAID.md §2.2, exact
    "waking": "waking the ranker · about a minute",
    "ranking": "Qloo is ranking your %s places · %d of %d calls",
    "dated_only": "All answers dated %s · no live ask right now",
    "degraded": "from %s · Qloo is slow right now",
    "degraded_none": "Qloo isn't answering right now. Your three are saved in this link; try in a minute, "
                     "or open one of these.",
    "queued": "%s ahead of yours · about %d s",
    "limited": "Fresh runs are limited so everyone gets through. These open instantly:",
    "partial": "%d answers · %d of 3 AIs",
    "live": "Gemini (%s): asked %s",          # §2.1 status line, naming the live model id
}
WORDS = {1: "One run", 2: "Two runs", 3: "Three runs", 4: "Four runs", 5: "Five runs"}
PROVIDERS = {"openai": "ChatGPT", "chatgpt": "ChatGPT", "codex": "ChatGPT", "claude": "Claude",
             "anthropic": "Claude", "gemini": "Gemini", "google": "Gemini"}


def et(when):
    """'30 Oct 09:00 ET' from an epoch or an ISO string."""
    try:
        if isinstance(when, (int, float)):
            d = dt.datetime.fromtimestamp(when, dt.timezone.utc)
        else:
            s = str(when).replace("Z", "+00:00")
            if "T" not in s:                       # a date-only stamp has no time to convert
                return dt.date.fromisoformat(s[:10]).strftime("%d %b").lstrip("0")
            d = dt.datetime.fromisoformat(s)
            if d.tzinfo is None:
                d = d.replace(tzinfo=dt.timezone.utc)
        return d.astimezone(ET).strftime("%d %b %H:%M ET").lstrip("0")
    except (ValueError, TypeError):
        return str(when)


def public(obj):
    """Drop internal fields (leading underscore) before anything leaves the server."""
    if isinstance(obj, dict):
        return {k: public(v) for k, v in obj.items() if not str(k).startswith("_")}
    if isinstance(obj, list):
        return [public(v) for v in obj]
    return obj


# ---------------------------------------------------------------- the run
def shell(status, prep=None, wall=None, note=None, flags=()):
    """A result with no cards: needs_input, limited, degraded (no cache)."""
    r = {"status": status, "flags": sorted(set(list(flags) + (["fake"] if MODE == "fake" else []))),
         "loves": [c for c in ((prep or {}).get("loves") or []) if c], "city": (prep or {}).get("city"),
         "picks": [], "reserves": [], "wall": adapter.wall_items((wall or {}).get("answers") or []),
         "counts": {}, "burn": {"asked": [], "burned": []},
         "diag": {"engine_v": adapter.ENGINE_V, "as_of": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "backend": adapter.BACKEND}}
    if note:
        r["note"] = note
    return r


def has_live(result):
    return any((i or {}).get("lane") == "live" for i in (result or {}).get("wall") or [])


def lane_flags(result, session, wall):
    """dated_only and partial (§2.2), decided by the server from the lanes it actually had."""
    flags = set(result.get("flags") or [])
    if MODE == "fake":
        flags.add("fake")
    notes = []
    if (wall or {}).get("missing"):            # no wall file on this host: say so, never a silent empty wall
        flags.update(("partial", "no_wall"))
        if result.get("status") in ("ok", "empty_few", "empty_none"):
            result["status"] = "partial"
        result["note"] = adapter.NO_WALL_NOTE
        notes.append(("partial", adapter.NO_WALL_NOTE))
    d = result.get("diag") or {}
    if d.get("live_error"):   # the Gemini lane failed in the engine: dated_only (CONTRACT), not partial
        failed = d.get("lanes_failed") or []
        if result.get("status") == "partial" and all(str(f).startswith(adapter.GEMINI_LANES) for f in failed):
            n = len(result.get("picks") or [])
            result["status"] = "ok" if n >= adapter.N_PICKS else ("empty_few" if n else "empty_none")
            flags.discard("partial")
    if (session is not None and session.state != "live") or d.get("live_error"):
        flags.add("dated_only")
        dated = [a.get("asked_at") for a in (wall or {}).get("answers", []) if a.get("asked_at")]
        notes.append(("dated_only", COPY["dated_only"] % (et(max(dated)) if dated else "earlier")))
    have = {PROVIDERS.get(str(i.get("provider") or "").lower()) for i in result.get("wall") or []} - {None}
    if have and len(have) < 3:
        flags.add("partial")
        answers = len({(i.get("provider"), i.get("phrasing_id"), i.get("asked_at")) for i in result.get("wall") or []})
        notes.append(("partial", COPY["partial"] % (answers, len(have))))
    result["flags"] = sorted(flags)
    reasons = [r for r in (session.reasons if session else []) if r]
    if d.get("live_error"):
        reasons.append("engine: %s" % str(d["live_error"])[:80])
    live_a = [a for a in (session.answers if session else []) if a.get("lane") == "live"]
    state = "dated_only" if "dated_only" in flags or not live_a else "live"
    if state == "dated_only" and session is not None and "dated_only" not in flags:
        flags.add("dated_only")
        dated = [a.get("asked_at") for a in (wall or {}).get("answers", []) if a.get("asked_at")]
        notes.append(("dated_only", COPY["dated_only"] % (et(max(dated)) if dated else "earlier")))
        result["flags"] = sorted(flags)
    model = GEMINI.model
    result["lanes"] = {"gemini": {"state": state, "model": model,
                                  "asked_at": live_a[0]["asked_at"] if live_a else None,
                                  "reason": None if state == "live" else (
                                      reasons[0] if reasons else (session.reason if session else "not asked"))},
                       "providers": sorted(have)}
    if state == "live":
        notes.insert(0, ("live", COPY["live"] % (model, "just now")))
    return notes


def stream_unsaid(city_text, loves, ip, country, emit, bench=False):
    """Runs one /api/unsaid request. Calls emit(evt) for every NDJSON line, the done line last.
    bench=True (a verified X-Unsaid-Bench header) skips the per-IP fresh-run limit, never the quota guard."""
    timing = Timing()
    t0 = timing.t0
    deadline = t0 + HARD_CAP_S

    def done(result, cached=False, stored_at=None):
        result = public(result)
        if session.geo_gated and has_live(result):   # unreachable by key design; refuse rather than leak
            print("[unsaid] refused a lane=live result to a geo-gated visitor", file=sys.stderr)
            result = shell("degraded", prep, wall, COPY["degraded_none"], flags=["no_cache"])
            cached, stored_at = False, None
        if cached:
            g = (result.get("lanes") or {}).get("gemini") or {}
            for n in result.get("notes") or []:
                if n["state"] == "live" and g.get("asked_at"):      # cached: "asked <when>", not "just now"
                    n["text"] = COPY["live"] % (g.get("model"), et(g["asked_at"]))
                emit({"type": "status", "state": n["state"], "text": n["text"]})
        result["cached"] = cached
        if stored_at:
            result["stored_at"] = et(stored_at)
        result["diag"] = dict(result.get("diag") or {})
        if cached and result["diag"].get("timing"):
            result["diag"]["timing_stored"] = result["diag"]["timing"]   # the run that made it; timing = this request
        result["diag"]["timing"] = timing.result()
        emit({"type": "done", "result": result})
        return result

    def status(state, text, **kw):
        emit(dict({"type": "status", "state": state, "text": text}, **kw))

    session = GEMINI.for_country(country)
    prep, wall = None, None
    q = timing.instrument(adapter.make_qloo(MODE, CACHE_DIR, BUCKET, QUOTA, FAKE_PACE))
    try:
        prep = adapter.prepare(city_text, loves, q, MODE)
    except Exception as e:
        print("[unsaid] resolve failed: %s" % adapter.describe_error(e), file=sys.stderr)
        status("degraded", COPY["degraded_none"])
        return done(shell("degraded", note=COPY["degraded_none"], flags=["no_cache"]))
    if prep["status"] != "ok":
        r = shell("needs_input", prep)
        r["resolutions"] = public(prep["resolutions"])
        r["city_resolution"] = public(prep["city_resolution"])
        status("needs_input", "needs_input")
        return done(r)

    wall = adapter.wall_for(prep["city"], prep["loves"], CACHE_DIR)
    for it in adapter.wall_items(wall["answers"]):                    # the dated wall first, from static data
        emit(dict(it, type="wall_name"))
    lane = "live" if session.live else "dated_only"                   # decided before the key, never after
    key = C.result_key(adapter.ENGINE_V, MODE, prep["city"]["id"], [c["id"] for c in prep["loves"]], "unsaid",
                       C.wall_hash(wall["answers"]), lane)
    rec = RESULTS.get(key)
    if rec and rec["fresh"]:
        for p in rec["result"].get("picks") or []:
            emit(dict(p, type="card"))
        return done(rec["result"], cached=True, stored_at=rec["stored_at"])

    def from_stale(why):
        line = COPY["degraded"] % et(rec["stored_at"])
        r = dict(rec["result"], status="degraded", note=line, degraded_reason=why)
        status("degraded", line)
        for p in r.get("picks") or []:
            emit(dict(p, type="card"))
        return done(r, cached=True, stored_at=rec["stored_at"])

    def no_cache(why):
        status("degraded", COPY["degraded_none"])
        r = shell("degraded", prep, wall, COPY["degraded_none"], flags=["no_cache"])
        r["key"], r["degraded_reason"] = key, why
        return done(r)

    # ---- limits: a fresh run is admitted only below both guards
    if (MODE == "live" and QUOTA.fired()) or (not bench and not FRESH_IPS.allowed(ip)):
        if rec:
            return from_stale("limited")
        status("limited", COPY["limited"])
        r = shell("limited", prep, wall, COPY["limited"])
        r["key"] = key
        return done(r)

    # ---- the same key already running: wait for it instead of spending quota twice
    with INFLIGHT_LOCK:
        fl = INFLIGHT.get(key)
        owner = fl is None
        if owner:
            fl = INFLIGHT[key] = {"event": threading.Event(), "result": None}
    if not owner:
        while not fl["event"].wait(1.0):
            if time.monotonic() >= deadline:
                return from_stale("hard cap") if rec else no_cache("hard cap")
        if fl["result"] is not None:
            for p in fl["result"].get("picks") or []:
                emit(dict(p, type="card"))
            return done(fl["result"], cached=True)
        return from_stale("qloo") if rec else no_cache("qloo")

    box = {"result": None, "error": None, "pool_U": None}
    lock = threading.Lock()

    def worker_emit(evt):
        timing.event(evt.get("type"))
        if evt.get("type") == "pool":
            box["pool_U"] = evt.get("U")
        with lock:
            if not box.get("closed"):
                emit(evt)

    def worker():
        started = time.monotonic()
        try:
            r = adapter.run(prep, wall, q, MODE, session, worker_emit,
                            deadline_s=max(1.0, deadline - time.monotonic()), timing=timing)
            r["key"] = key
            notes = lane_flags(r, session, wall)
            r["notes"] = [{"state": s, "text": t} for s, t in notes]
            r["diag"] = dict(r.get("diag") or {}, timing=timing.result())   # the run's own stages, kept in the cache
            if r.get("status") in ("ok", "empty_few", "empty_none", "partial", "dated_only"):
                RESULTS.put(key, public(r), background=True)
            box["result"] = r
            fl["result"] = public(r)
        except Exception as e:  # QlooError or anything else: degraded, never a crash
            box["error"] = adapter.describe_error(e)
            print("[unsaid] run failed: %s" % adapter.trace_tail(e).split(" for ")[0], file=sys.stderr)
        finally:
            ADMIT.release(time.monotonic() - started)
            fl["event"].set()
            with INFLIGHT_LOCK:
                INFLIGHT.pop(key, None)

    try:
        if not bench:
            FRESH_IPS.record(ip)
        q_start = time.monotonic()
        admitted = ADMIT.acquire(
            on_wait=lambda ahead, eta: status("queued", COPY["queued"] % (WORDS.get(ahead, "%d runs" % ahead), eta),
                                              ahead=ahead, eta_s=eta),
            deadline=deadline)
    except BaseException:
        fl["event"].set()
        with INFLIGHT_LOCK:
            INFLIGHT.pop(key, None)
        raise
    timing.span("queue", q_start, time.monotonic())
    if not admitted:
        fl["event"].set()
        with INFLIGHT_LOCK:
            INFLIGHT.pop(key, None)
        return from_stale("hard cap") if rec else no_cache("hard cap")

    th = threading.Thread(target=worker, name="run-" + key[:8], daemon=True)
    run_t0 = time.monotonic()
    th.start()
    last_calls, ranking_sent = -1, False
    while th.is_alive():
        th.join(1.0)
        if not th.is_alive():
            break
        if adapter.BACKEND == "api":      # the engine streams its own calls/ranking events
            if time.monotonic() >= deadline:
                with lock:
                    box["closed"] = True
                return from_stale("hard cap") if rec else no_cache("hard cap")
            continue
        n = q.calls["network"]
        with lock:
            if n != last_calls:
                last_calls = n
                emit({"type": "calls", "done": n, "total": max(CALLS_TOTAL, n)})
            if not ranking_sent and time.monotonic() - run_t0 > RANKING_AFTER_S:
                ranking_sent = True
                emit({"type": "status", "state": "ranking",
                      "text": COPY["ranking"] % (box["pool_U"] or "", n, max(CALLS_TOTAL, n))})
        if time.monotonic() >= deadline:      # the 90 s hard cap; the run finishes in the background and is cached
            with lock:
                box["closed"] = True
            return from_stale("hard cap") if rec else no_cache("hard cap")
    with lock:
        box["closed"] = True
    if box["result"] is None:
        return from_stale(box["error"] or "error") if rec else no_cache(box["error"] or "error")
    r = box["result"]
    for n in r.get("notes") or []:
        emit({"type": "status", "state": n["state"], "text": n["text"]})
    return done(r)


# ---------------------------------------------------------------- HTTP
def parse_loves(values):
    if not values:
        raise ValueError("loves is required")
    raw = []
    if len(values) == 1 and values[0].lstrip().startswith("["):
        raw = json.loads(values[0])
        if not isinstance(raw, list):
            raise ValueError("loves JSON must be an array")
    elif len(values) == 1:
        raw = [x for x in values[0].split("|") if x.strip()]
    else:
        raw = values
    out = []
    for x in raw:
        if isinstance(x, str) and x.lstrip()[:1] in ("{", "["):   # repeated loves=... params, each a pair or object
            x = json.loads(x)
        out.append(adapter.parse_love(x))
    if not 1 <= len(out) <= 3:
        raise ValueError("give 1 to 3 loves (three works best)")
    return out


class Handler(BaseHTTPRequestHandler):
    server_version = "unsaid"
    sys_version = ""
    protocol_version = "HTTP/1.0"

    def log_message(self, fmt, *args):   # the default would log the query string (loves, token): path only
        pass

    def _log(self, code):
        print("[http] %s %s %s %dms" % (self.command, urllib.parse.urlsplit(self.path).path[:80], code,
                                        int((time.monotonic() - self._t0) * 1000)), file=sys.stderr)

    def _json(self, code, obj, extra=None):
        body = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Unsaid-State", "warm")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)
        self._log(code)

    # -- identity
    def _trusted_proxy(self):
        got = self.headers.get("X-Unsaid-Proxy", "")
        return bool(PROXY_SECRET) and hmac.compare_digest(got.encode(), PROXY_SECRET.encode())

    def client_ip(self):
        if self._trusted_proxy() and self.headers.get("X-Unsaid-Client-IP"):
            return self.headers["X-Unsaid-Client-IP"].strip()[:64]
        xff = self.headers.get("X-Forwarded-For")
        if xff and os.environ.get("RENDER"):          # Render's edge appends the address it saw last
            return xff.split(",")[-1].strip()[:64]
        return self.client_address[0]

    def country(self):
        if self._trusted_proxy():
            return self.headers.get("X-Unsaid-Country") or self.headers.get("CF-IPCountry") or ""
        if PROXY_SECRET:            # proxy configured but this request bypassed it: country unknown -> gated
            return ""
        return self.headers.get("CF-IPCountry") or ""

    def bench(self):
        """X-Unsaid-Bench: <proxy secret>, checked here against UNSAID_PROXY_SECRET; it never reaches a browser."""
        got = self.headers.get("X-Unsaid-Bench", "")
        return bool(PROXY_SECRET) and bool(got) and hmac.compare_digest(got.encode(), PROXY_SECRET.encode())

    def authorized(self, qs):
        if not TOKEN:
            return True
        got = self.headers.get("X-Unsaid-Token") or ""
        auth = self.headers.get("Authorization") or ""
        if not got and auth.lower().startswith("bearer "):
            got = auth[7:].strip()
        if not got:
            got = (qs.get("token") or [""])[0]
        return hmac.compare_digest(got.encode(), TOKEN.encode())

    # -- routes
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        self._t0 = time.monotonic()
        try:
            u = urllib.parse.urlsplit(self.path)
            qs = urllib.parse.parse_qs(u.query, keep_blank_values=False)
            path = u.path.rstrip("/") or "/"
            if path == "/api/health":
                a, w = ADMIT.depth()
                return self._json(200, {"ok": True, "state": "warm", "boot_warm": WARM["state"],
                                        "mode": MODE, "backend": adapter.BACKEND,
                                        "engine_v": adapter.ENGINE_V, "uptime_s": int(time.time() - BOOT),
                                        "queue": {"active": a, "waiting": w}})
            if not path.startswith("/api/"):
                return self._json(404, {"status": "not_found"})
            if not self.authorized(qs):
                return self._json(401, {"status": "unauthorized", "note": "this endpoint needs the UNSAID token"},
                                  {"WWW-Authenticate": "Bearer"})
            if path == "/api/resolve":
                return self.resolve(qs)
            if path == "/api/unsaid":
                return self.unsaid(qs)
            if path.startswith("/api/result/"):
                key = path[len("/api/result/"):]
                if not C.KEY_RE.match(key):
                    return self._json(400, {"status": "bad_key"})
                rec = RESULTS.get(key)
                if rec and GEMINI.for_country(self.country()).geo_gated and has_live(rec["result"]):
                    rec = None                    # a live Gemini answer is never shown in EEA/UK/CH or unknown
                if not rec:
                    return self._json(404, {"status": "not_found", "key": key})
                r = dict(rec["result"], cached=True, stored_at=et(rec["stored_at"]))
                return self._json(200, {"key": key, "fresh": rec["fresh"], "result": r})
            return self._json(404, {"status": "not_found"})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            print("[http] error %s" % adapter.describe_error(e), file=sys.stderr)
            try:
                self._json(500, {"status": "error"})
            except Exception:
                pass

    def resolve(self, qs):
        kind = (qs.get("kind") or [""])[0]
        text = " ".join((qs.get("q") or [""])[0].split())
        if kind not in ("love", "city") or not 1 <= len(text) <= 120:
            return self._json(400, {"status": "bad_request", "note": "kind=love|city and q (1-120 chars)"})
        if not RESOLVE_IPS.record(self.client_ip()):
            return self._json(429, {"status": "limited", "note": COPY["limited"]}, {"Retry-After": "60"})
        q = adapter.make_qloo(MODE, CACHE_DIR, BUCKET, QUOTA, FAKE_PACE)
        try:
            if kind == "city":
                r = adapter.resolve_city(text, q, MODE)
            else:
                hint = (qs.get("type") or [None])[0]
                r = adapter.resolve_love(text, hint if hint in adapter.TYPES else None, q, MODE)
        except Exception as e:
            print("[resolve] %s" % adapter.describe_error(e), file=sys.stderr)
            return self._json(503, {"status": "degraded", "note": COPY["degraded_none"]})
        r = public(r)
        r["flags"] = ["fake"] if MODE == "fake" else []
        return self._json(200, r)

    def unsaid(self, qs):
        city = " ".join((qs.get("city") or [""])[0].split())
        try:
            if not 2 <= len(city) <= 80:
                raise ValueError("city is required (2-80 chars)")
            if sum(len(v) for v in qs.get("loves") or []) > 2000:
                raise ValueError("loves is too long")
            loves = parse_loves(qs.get("loves"))
        except ValueError as e:
            return self._json(400, {"status": "bad_request", "note": str(e)})
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("X-Unsaid-State", "warm")
        self.end_headers()
        gone = {"v": False}

        def emit(evt):
            if gone["v"]:
                return
            try:
                self.wfile.write((json.dumps(evt, ensure_ascii=False, default=str) + "\n").encode("utf-8"))
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                gone["v"] = True      # the visitor left; the run still finishes and is cached under its key

        stream_unsaid(city, loves, self.client_ip(), self.country(), emit, bench=self.bench())
        self._log(200)


def make_server(host=None, port=None):
    host = host or os.environ.get("HOST") or ("0.0.0.0" if os.environ.get("RENDER") else "127.0.0.1")
    port = int(port if port is not None else os.environ.get("PORT", "8710"))
    srv = ThreadingHTTPServer((host, port), Handler)
    srv.daemon_threads = True
    return srv


def main():
    threading.Thread(target=warm, name="warm", daemon=True).start()
    srv = make_server()
    h, p = srv.server_address[:2]
    print("[unsaid] listening on %s:%d · mode=%s · backend=%s · token=%s · gemini=%s" % (
        h, p, MODE, adapter.BACKEND, "on" if TOKEN else "off", GEMINI.global_reason() or "live"), file=sys.stderr)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
