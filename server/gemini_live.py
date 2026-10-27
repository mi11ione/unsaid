"""The one live AI lane: Gemini API free tier (UNSAID.md §3.6). Standard library only.

- Key from env GEMINI_API_KEY, sent in the x-goog-api-key header (never in a URL, log or response).
- Model pinned by env GEMINI_MODEL. JSON output (responseSchema), no grounding, no tools, no system prompt.
- Per fresh run: one taste ask, <= 3 street asks, in the exact prompt-v2 phrasings below.
- Geo-gate on the visitor's country (CF-IPCountry via the Pages proxy): EEA, UK or CH -> dated_only.
  An unknown country is gated too: only paid services may serve those regions, so we don't guess.
- Guard at 80% of env GEMINI_RPD (requests per day, reset at midnight Pacific). A 429 -> dated_only for 1 h.
- No GEMINI_API_KEY (or no model / no RPD) -> dated_only. A live answer is never faked.
- Every answer is stored with asked_at and lane=live. Only venue names, neighbourhoods and timestamps are kept.
"""
import datetime as dt
import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.request

try:
    from zoneinfo import ZoneInfo
    PACIFIC = ZoneInfo("America/Los_Angeles")
except Exception:  # no tz database: fall back to a fixed UTC-8
    PACIFIC = dt.timezone(dt.timedelta(hours=-8))

PROVIDER = "gemini"
PROMPT_V = "v2"
SUFFIX = ('Answer only with a JSON array of up to 12 objects {"name": ..., "neighbourhood": ...}. '
          'Real, currently open venues only.')
STREET_MAX = 3
ANSWER_TTL_S = 24 * 3600                       # taste answers 1 d; street answers until the next daily wall
API = "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent"
UA = "Mozilla/5.0 (compatible)"               # generic; no name or email in any request
GATED = set("AT BE BG HR CY CZ DK EE FI FR DE GR HU IE IT LV LT LU MT NL PL PT RO SK SI ES SE "  # EU 27
            "IS LI NO "                                                                     # EEA
            "GB UK CH".split())                                                             # UK, Switzerland
SCHEMA = {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
    "name": {"type": "STRING"}, "neighbourhood": {"type": "STRING"}}, "required": ["name"]}}


def taste_phrasing(labels, city):
    """§3.6 taste phrasing 4 (the combined one): 'I love {L1}, {L2} and {L3}. Where should I eat and drink in {city}?'"""
    labels = [l for l in labels if l]
    if len(labels) >= 2:
        loves = "%s and %s" % (", ".join(labels[:-1]), labels[-1])
    else:
        loves = labels[0] if labels else ""
    return "I love %s. Where should I eat and drink in %s?" % (loves, city)


def street_phrasing(neighbourhood, city):
    """§3.3 step 10, unhinted: 'Best places to eat and drink in {neighbourhood}, {city}'."""
    return "Best places to eat and drink in %s, %s" % (neighbourhood, city)


def _clean(s, n=120):
    return " ".join(str(s or "").split())[:n]


class GeminiLane:
    """Process-wide state: daily counter, 429 cooldown, the answer cache. Per request: `for_country`."""

    def __init__(self, cache_dir, transport=None):
        self.key = os.environ.get("GEMINI_API_KEY", "").strip()
        self.model = os.environ.get("GEMINI_MODEL", "").strip()
        try:
            self.rpd = int(os.environ.get("GEMINI_RPD", "0"))
        except ValueError:
            self.rpd = 0
        self.guard = float(os.environ.get("GEMINI_GUARD", "0.80"))
        self.timeout = float(os.environ.get("GEMINI_TIMEOUT_S", "20"))
        self.dir = os.path.join(cache_dir, "ai")
        self.usage_path = os.path.join(cache_dir, "gemini_usage.json")
        self.transport = transport or self._http
        self.cooldown_until = 0.0
        self.lock = threading.Lock()
        self.usage = {"day": self._day(), "used": 0}
        try:
            with open(self.usage_path) as f:
                u = json.load(f)
            if u.get("day") == self.usage["day"]:
                self.usage = u
        except (OSError, ValueError):
            pass

    # ---------------------------------------------------------------- state
    @staticmethod
    def _day():
        return dt.datetime.now(PACIFIC).strftime("%Y-%m-%d")

    def global_reason(self):
        """Why the lane is off for everyone right now, or None when it is on."""
        if not self.key:
            return "no key"
        if not self.model:
            return "no model pinned"
        if self.rpd <= 0:
            return "GEMINI_RPD not set"
        if time.time() < self.cooldown_until:
            return "429 cooldown"
        with self.lock:
            if self.usage["day"] != self._day():
                self.usage = {"day": self._day(), "used": 0}
            if self.usage["used"] + 1 > self.guard * self.rpd:
                return "daily guard"
        return None

    def for_country(self, country):
        return LaneSession(self, (country or "").strip().upper())

    def _count(self):
        with self.lock:
            if self.usage["day"] != self._day():
                self.usage = {"day": self._day(), "used": 0}
            self.usage["used"] += 1
            os.makedirs(os.path.dirname(self.usage_path), exist_ok=True)
            with open(self.usage_path + ".tmp", "w") as f:
                json.dump(self.usage, f)
            os.replace(self.usage_path + ".tmp", self.usage_path)

    # ---------------------------------------------------------------- answer cache (§3.5)
    def _akey(self, locality, phrasing_id, love_ids):
        blob = json.dumps([PROVIDER, self.model, PROMPT_V, locality, phrasing_id, sorted(love_ids or [])],
                          separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()

    def _load(self, k):
        try:
            with open(os.path.join(self.dir, k[:2], k + ".json")) as f:
                a = json.load(f)
        except (OSError, ValueError):
            return None
        if a.get("akey") != k or time.time() - a.get("asked_ts", 0) > ANSWER_TTL_S:
            return None
        return a

    def _store(self, k, a):
        p = os.path.join(self.dir, k[:2], k + ".json")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p + ".tmp", "w") as f:
            json.dump(a, f, ensure_ascii=False)
        os.replace(p + ".tmp", p)

    # ---------------------------------------------------------------- HTTP
    def _http(self, prompt):
        body = json.dumps({"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                           "generationConfig": {"responseMimeType": "application/json", "responseSchema": SCHEMA}})
        req = urllib.request.Request(API % self.model, data=body.encode("utf-8"), method="POST",
                                     headers={"Content-Type": "application/json", "x-goog-api-key": self.key,
                                              "User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, None
        except Exception:
            return 599, None

    @staticmethod
    def _names(data):
        try:
            parts = data["candidates"][0]["content"]["parts"]
            arr = json.loads("".join(p.get("text", "") for p in parts))
        except (KeyError, IndexError, TypeError, ValueError):
            return None
        if not isinstance(arr, list):
            return None
        out = []
        for x in arr[:12]:
            if isinstance(x, dict) and _clean(x.get("name")):
                out.append({"name": _clean(x.get("name")), "neighbourhood": _clean(x.get("neighbourhood"))})
            elif isinstance(x, str) and _clean(x):
                out.append({"name": _clean(x), "neighbourhood": ""})
        return out

    def ask(self, phrasing_id, prompt, locality, love_ids=None):
        """One live ask. Returns (answer|None, reason|None). The cache is checked before the guard."""
        k = self._akey(locality, phrasing_id, love_ids)
        hit = self._load(k)
        if hit:
            return hit, None
        why = self.global_reason()
        if why:
            return None, why
        self._count()
        status, data = self.transport(prompt + "\n\n" + SUFFIX)
        if status == 429:
            self.cooldown_until = time.time() + 3600
            return None, "429"
        if status != 200:
            return None, "error %s" % status
        names = self._names(data)
        if names is None:
            return None, "unparseable"
        now = time.time()
        a = {"akey": k, "provider": PROVIDER, "model": self.model, "prompt_v": PROMPT_V, "phrasing_id": phrasing_id,
             "phrasing": prompt, "lane": "live", "asked_ts": now,
             "asked_at": dt.datetime.fromtimestamp(now, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "names": names}
        self._store(k, a)
        return a, None


class LaneSession:
    """One fresh run's view of the lane: 1 taste ask + <= 3 street asks, gated by the visitor's country."""

    def __init__(self, lane, country):
        self.lane, self.country = lane, country
        self.street_used = 0
        self.taste_used = 0
        self.reasons = []
        self.answers = []

    @property
    def reason(self):
        why = self.lane.global_reason()
        if why:
            return why
        if not self.country or self.country in ("XX", "T1"):
            return "country unknown"
        if self.country in GATED:
            return "EEA/UK/CH"
        return None

    @property
    def geo_gated(self):
        """EEA, UK, CH or unknown: this visitor may never see a live Gemini answer, cached or not."""
        return not self.country or self.country in ("XX", "T1") or self.country in GATED

    @property
    def live(self):
        return self.reason is None

    @property
    def state(self):
        return "live" if self.live and not self.reasons else "dated_only"

    def _ask(self, pid, prompt, locality, love_ids):
        if self.reason in ("country unknown", "EEA/UK/CH"):
            self.reasons.append(self.reason)
            return None
        a, why = self.lane.ask(pid, prompt, locality, love_ids)
        if a is None:
            self.reasons.append(why)
        else:
            self.answers.append(a)
        return a

    def ask_taste(self, city_name, love_labels, locality, love_ids):
        if self.taste_used >= 1:
            return None
        self.taste_used += 1
        return self._ask("taste-all", taste_phrasing(love_labels, city_name), locality, love_ids)

    def ask_street(self, neighbourhood, city_name, locality):
        if self.street_used >= STREET_MAX or not neighbourhood:
            return None
        self.street_used += 1
        return self._ask("street:" + neighbourhood.lower(), street_phrasing(neighbourhood, city_name), locality, None)
