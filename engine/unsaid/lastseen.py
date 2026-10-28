"""The last-seen check (UNSAID.md §3.1) for the 7 cards + 3 reserves. A card passes when:
  - Qloo carries its hours (properties.hours);
  - its address doesn't contain "closed";
  - IF it has a website, the site answers HTTP 2xx/3xx (or 401/403/429: a bot wall in front of a live site) within 5 s (HEAD, then GET; generic User-Agent, no name or
    email). No website: it passes on hours alone, marked `hours only`.
These are venue sites, never Qloo; no Qloo call is made here. Site results are cached for 24 h in .cache/lastseen/
(gitignored). The default hook in api.run_unsaid in live mode; the server can pass its own.
    check(entity) -> (ok, {"checked_at", "how"})      prefetch([entity, ...]) checks sites in parallel first
"""
import hashlib
import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from unsaid.qloo import DEFAULT_CACHE, prop

TIMEOUT = 5.0
TTL = 86400
UA = "Mozilla/5.0 (compatible)"        # generic on purpose
DIR = os.path.join(DEFAULT_CACHE, "lastseen")


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def _cache_path(url):
    return os.path.join(DIR, hashlib.sha256(url.encode()).hexdigest() + ".json")


def _urllib(url, method):
    req = urllib.request.Request(url, method=method, headers={"User-Agent": UA, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            if method == "GET":
                r.read(2048)
            return r.status, None
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception as e:          # timeout, DNS, TLS
        return None, type(e).__name__ + (": " + str(getattr(e, "reason", "")) if getattr(e, "reason", None) else "")


def _curl(url):
    """Fallback when this Python's TLS stack can't talk to the host: curl, same UA and timeout, final status after
    redirects."""
    if not shutil.which("curl"):
        return None, "no curl"
    p = subprocess.run(["curl", "-sS", "-o", os.devnull, "-L", "--max-time", str(int(TIMEOUT)), "-A", UA,
                        "-w", "%{http_code}", url], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       universal_newlines=True, stdin=subprocess.DEVNULL)
    try:
        code = int(p.stdout.strip()[-3:])
        return (code if code else None), (None if code else p.stderr.strip()[:80])
    except ValueError:
        return None, p.stderr.strip()[:80] or "curl failed"


def site(url):
    """-> {"ok", "status", "how", "checked_at"}, cached 24 h."""
    fp = _cache_path(url)
    try:
        if time.time() - os.path.getmtime(fp) <= TTL:
            with open(fp) as f:
                return json.load(f)
    except (OSError, ValueError):
        pass
    status, err = _urllib(url, "HEAD")
    if status is None or status >= 400:          # many sites refuse HEAD: try GET
        s2, e2 = _urllib(url, "GET")
        if s2 is not None:
            status, err = s2, None
        elif status is None:
            err = e2 or err
    if status is None and err and ("SSL" in err or "CERTIFICATE" in err.upper() or "URLError" in err):
        status, err = _curl(url)
    # 401/403/429 is a bot wall or rate limit in front of a live site, not a closed venue (decided 28 Oct)
    ok = status is not None and (200 <= status < 400 or status in (401, 403, 429))
    rec = {"ok": ok, "status": status, "checked_at": _now(),
           "how": ("site HTTP %d" % status) if status is not None else "site unreachable (%s)" % (err or "timeout")}
    os.makedirs(DIR, exist_ok=True)
    tmp = fp + ".%d.tmp" % os.getpid()
    with open(tmp, "w") as f:
        json.dump(rec, f)
    os.replace(tmp, fp)
    return rec


def check(e):
    hours = prop(e, "hours")
    addr = str(prop(e, "address") or "")
    url = prop(e, "website")
    if "closed" in addr.lower():
        return False, {"checked_at": _now(), "how": "failed: address says closed"}
    if not hours:
        return False, {"checked_at": _now(), "how": "failed: no hours in Qloo"}
    if not url:
        return True, {"checked_at": _now(), "how": "hours only"}
    s = site(url)
    if s["ok"]:
        return True, {"checked_at": s["checked_at"], "how": "hours + %s" % s["how"]}
    return False, {"checked_at": s["checked_at"], "how": "failed: %s" % s["how"]}


def prefetch(entities, workers=8):
    urls = [prop(e, "website") for e in entities if prop(e, "website") and prop(e, "hours")]
    if urls:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            list(ex.map(site, dict.fromkeys(urls)))


check.prefetch = prefetch


def fake_check(e):
    """[FAKE] mode: the hours and address halves only; venue sites are never fetched."""
    ok, info = check(dict(e, properties=dict(e.get("properties") or {}, website=None)))
    if ok:
        info["how"] = "hours only [FAKE: site not fetched]"
    return ok, info
