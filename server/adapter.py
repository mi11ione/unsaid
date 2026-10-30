"""Bridge between the server and the engine.

If engine/unsaid/api.py exists (Agent D, CONTRACT.md), it is used: run_unsaid, resolve_love, resolve_city.
Until then this falls back to the round-3 kit's engine.run (fake mode), mapped onto the CONTRACT result shape.
The server never imports engine internals anywhere else.
"""
import contextlib
import os
import re
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ENGINE = os.environ.get("UNSAID_ENGINE") or os.path.join(ROOT, "engine")
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

from unsaid import engine as E, matcher as M, seeds as SD, walls as W  # noqa: E402
from unsaid.qloo import Qloo, QlooError, latlon, prop  # noqa: E402
try:
    from unsaid.qloo import RESOLVE_BUDGET_S  # noqa: E402
except ImportError:          # an older engine (UNSAID_ENGINE): no resolve window
    RESOLVE_BUDGET_S = 12.0

API = None
API_ERROR = None
if os.path.exists(os.path.join(ENGINE, "unsaid", "api.py")):
    try:
        from unsaid import api as API  # noqa: E402
    except Exception as e:  # D's file mid-edit: keep serving from the fallback, say so in /api/health
        API, API_ERROR = None, "%s: %s" % (type(e).__name__, e)
        print("[adapter] engine api.py failed to import, using the fallback: %s" % API_ERROR, file=sys.stderr)

# The dated walls: env UNSAID_WALLS (a walls JSON file or a directory of them), else the repo's data/walls/.
# Never research/, and never the engine's day-1 fixtures: with no wall file the run is `partial`, said plainly.
WALLS_DEFAULT = os.path.join(ROOT, "data", "walls")
NO_WALL_NOTE = "No dated AI answers are loaded on this host yet, so nothing was crossed out."
_MERGED = {"sig": None, "path": None}


def walls_file(cache_dir):
    """One walls JSON path for this host, or None when there is no wall file. A directory's *.json files are
    merged (their "walls" lists concatenated, in name order) into <cache_dir>/walls_merged.json."""
    src = os.environ.get("UNSAID_WALLS") or WALLS_DEFAULT
    if os.path.isfile(src):
        return src
    if not os.path.isdir(src):
        return None
    files = sorted(os.path.join(src, f) for f in os.listdir(src) if f.endswith(".json"))
    if not files:
        return None
    sig = [(f, os.path.getmtime(f), os.path.getsize(f)) for f in files]
    if _MERGED["sig"] != sig or not os.path.exists(_MERGED["path"] or ""):
        import json
        walls = []
        for f in files:
            with open(f) as fh:
                walls += (json.load(fh) or {}).get("walls") or []
        out = os.path.join(cache_dir, "walls_merged.json")
        os.makedirs(cache_dir, exist_ok=True)
        with open(out + ".tmp", "w") as fh:
            json.dump({"walls": walls}, fh)
        os.replace(out + ".tmp", out)
        _MERGED.update(sig=sig, path=out)
    return _MERGED["path"]


def empty_walls_file(cache_dir):
    """Handed to the engine when there is no wall, so it never falls back to its fixtures."""
    p = os.path.join(cache_dir, "walls_empty.json")
    if not os.path.exists(p):
        os.makedirs(cache_dir, exist_ok=True)
        with open(p, "w") as fh:
            fh.write('{"walls": []}')
    return p

def configure_priors():
    """The 'fits everyone' priors (data/priors/<city>.json) are Qloo-derived, so they are gitignored and never in the
    repo. On Render they are secret files (mounted at /etc/secrets/, uploaded by server/push_priors.py) and
    UNSAID_PRIORS_DIR points the engine there. Returns {city: present} for /api/health."""
    d = os.environ.get("UNSAID_PRIORS_DIR")
    if d and os.path.isdir(d) and "PRIORS_DIR" in E.CFG:
        E.CFG["PRIORS_DIR"] = d
    pd = E.CFG.get("PRIORS_DIR") or ""
    return {k: os.path.exists(os.path.join(pd, "%s.json" % k)) for k in ("stl", "nyc")}


PRIORS = configure_priors()
ENGINE_V = getattr(API, "ENGINE_V", None) or getattr(getattr(API, "E", None), "ENGINE_V", None) or "kit-v3+server-fallback-1"
BACKEND = "api" if API else "fallback"
N_PICKS, N_RESERVES = 7, 3
if not API:
    E.CFG["N_CARDS"] = N_PICKS + N_RESERVES   # the fallback asks the kit for 7 + 3 and splits them

CITY_SLUGS = {  # slug -> (query, region, slug, radius_mi)
    "stl": ("St. Louis", "Missouri", "st-louis", 10), "st-louis": ("St. Louis", "Missouri", "st-louis", 10),
    "st. louis": ("St. Louis", "Missouri", "st-louis", 10), "st louis": ("St. Louis", "Missouri", "st-louis", 10),
    "saint louis": ("St. Louis", "Missouri", "st-louis", 10),
    "nyc": ("New York City", "New York", "new-york", 8), "new-york": ("New York City", "New York", "new-york", 8),
    "new york": ("New York City", "New York", "new-york", 8),
    "new york city": ("New York City", "New York", "new-york", 8),
}
CITY_KEY = {"st-louis": "stl", "new-york": "nyc"}
STATES = {"mo": "Missouri", "ny": "New York", "va": "Virginia", "il": "Illinois", "ca": "California"}
TYPES = {"artist", "movie", "tv_show", "book", "podcast", "videogame", "brand", "place", "tag"}
ID_RE = re.compile(r"^[A-Za-z0-9:_.\-]{1,120}$")


COVERED = ("stl", "nyc")
CITY_NOT_COVERED = ("UNSAID covers St. Louis and New York, the cities where we collected what the AIs say. "
                    "Pick one of those.")
CANON = {"stl": "St. Louis", "nyc": "New York City"}


ENGINE_CACHES = ("_POOL_CACHE", "_RCACHE", "_NRB", "_DETAIL")   # module-level dict/list memo caches (pure)


def trim_caches():
    """Clears the engine's pure memo caches (functools lru caches in matcher/engine, the pool and reverse-index
    caches, per-entity memo dicts). Results are unchanged: everything is recomputed on demand. Returns a summary.
    Called by the server's memory guard on a 512 MB host; the walls are re-warmed afterwards."""
    import gc
    n_lru, n_obj = 0, 0
    mods = [M, E] + ([API] if API else [])
    for mod in mods:
        for name in dir(mod):
            obj = getattr(mod, name, None)
            if callable(getattr(obj, "cache_clear", None)) and getattr(obj, "__module__", None) == mod.__name__:
                obj.cache_clear()
                n_lru += 1
        for name in ENGINE_CACHES:
            obj = getattr(mod, name, None)
            if isinstance(obj, (dict, list)):
                obj.clear()
                n_obj += 1
    gc.collect()
    return {"lru": n_lru, "caches": n_obj}


def city_key(text):
    """City text, slug or alias -> ("stl"|"nyc"|None, text for the engine). Slugs the site sends (new-york,
    st-louis) map to the canonical name, so a resolved city is never sent back for disambiguation."""
    t = " ".join((text or "").split())
    k = t.lower().rstrip(".")
    if k in CITY_SLUGS:
        ck = CITY_KEY[CITY_SLUGS[k][2]]
        return ck, CANON[ck]
    try:
        from unsaid import cities
        ck, _ = cities.lookup(t)
    except ImportError:
        ck = None
    if ck in COVERED:
        return ck, t
    return None, t


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")


def make_qloo(mode, cache_dir, bucket=None, quota=None, fake_pace=False):
    """One engine Qloo client per run; all of them share the process-wide bucket and quota guard."""
    from limits import CountingTransport
    q = Qloo(fake=(mode != "live"), cache_dir=os.path.join(cache_dir, "qloo"))
    from unsaid import qloo as QM
    if fake_pace or (mode == "live" and not hasattr(QM, "BUCKET")):
        q.bucket = bucket       # the engine's own module-level BUCKET is already the one global bucket when it has one
    if quota is not None and mode == "live":
        q.transport = CountingTransport(q.transport, quota)
    return q


# ---------------------------------------------------------------- resolve (C1, C2)
def _engine_city(q, text):
    t = " ".join((text or "").split())
    k = t.lower().rstrip(".")
    if k in CITY_SLUGS:
        name, region, slug, radius = CITY_SLUGS[k]
    else:
        name, region = t, None
        if "," in t:
            name, region = [x.strip() for x in t.split(",", 1)]
            region = STATES.get(region.lower().rstrip("."), region)
        slug, radius = None, None
    c = E.resolve_city(q, name, region)
    if c.get("status") == "ok" and region is None:
        if len({x["disamb"] for x in c.get("candidates", [])}) > 1:
            c = dict(c, status="needs_input", reason="'%s' is ambiguous; add the region" % name)
    return c, slug, radius


def _city_out(c, slug, radius):
    return {"id": c.get("id"), "name": c.get("name"), "slug": slug or slugify(c.get("name")),
            "center": [c.get("lon"), c.get("lat")], "radius_mi": radius, "disamb": c.get("disamb")}


def resolve_city(text, q, mode):
    ck, text = city_key(text)
    if ck is None:
        return {"status": "unsupported_city", "city": None, "alternatives": [{"name": CANON[k]} for k in COVERED],
                "note": CITY_NOT_COVERED}
    if API:
        try:
            return API.resolve_city(text, mode=mode, qloo=q)
        except TypeError:
            return API.resolve_city(text, mode=mode)
    c, slug, radius = _engine_city(q, text)
    alts = [{"name": x.get("name"), "disamb": x.get("disamb"), "id": x.get("id")} for x in c.get("candidates", [])]
    if c.get("status") != "ok":
        return {"status": "needs_input", "city": None, "alternatives": alts, "reason": c.get("reason", "city not found")}
    return {"status": "ok", "city": _city_out(c, slug, radius), "alternatives": alts, "_engine": c}


def _hint(chip_or_type):
    t = chip_or_type or ""
    if isinstance(chip_or_type, dict):
        if chip_or_type.get("kind") == "tag":
            return "tag"
        t = chip_or_type.get("type") or ""
    t = t.split(":")[-1] if t else ""
    return t if t in TYPES else None


def resolve_love(text, hint, q, mode):
    if API:
        try:
            return API.resolve_love(text, hint, mode=mode, qloo=q)
        except TypeError:
            return API.resolve_love(text, hint, mode=mode)
    r = E.resolve_love(q, text, hint if hint in TYPES else None)
    if r.get("status") == "needs_input":
        return {"status": "miss", "chip": None, "alternatives": [], "text": text, "reason": r.get("reason")}
    chip = {"id": r["id"], "label": r.get("name") or text, "kind": r.get("kind"), "type": r.get("type"),
            "text": text}
    return {"status": "ok" if r["status"] == "ok" else "needs_input", "chip": chip, "text": text,
            "alternatives": [a for a in (r.get("alternatives") or []) if a]}


HINT_ALIASES = {"dish": "tag", "cuisine": "tag", "food": "tag", "drink": "tag", "vibe": "tag", "film": "movie",
                "tv": "tv_show", "show": "tv_show", "series": "tv_show", "game": "videogame", "restaurant": "place",
                "bar": "place", "venue": "place", "musician": "artist", "band": "artist"}


def hint_of(h):
    """A type hint for resolve_love(text, hint): one of TYPES, an alias of one, or None."""
    if h is None or (isinstance(h, str) and not h.strip()):
        return None
    if not isinstance(h, str):
        raise ValueError("a type hint is a string")
    k = h.strip().lower().replace(" ", "_").split(":")[-1]
    k = HINT_ALIASES.get(k, k)
    if k not in TYPES:
        raise ValueError("type is one of %s" % ", ".join(sorted(TYPES)))
    return k


def parse_love(x):
    """A love is plain text, a [text, hint] pair (the sets-file form), {"text", "type"} (or "hint"),
    or a resolved chip {"id", "label", "kind", "type"}. Hints go through to resolve_love(text, hint)."""
    if isinstance(x, str) and x.strip():
        return {"text": x.strip()[:120]}
    if isinstance(x, (list, tuple)) and 1 <= len(x) <= 2 and isinstance(x[0], str) and x[0].strip():
        return {"text": x[0].strip()[:120], "hint": hint_of(x[1] if len(x) == 2 else None)}
    if isinstance(x, dict):
        if x.get("id") is not None:
            if not (isinstance(x["id"], str) and ID_RE.match(x["id"]) and isinstance(x.get("label"), str)):
                raise ValueError("a chip needs a Qloo id and a label")
            return {"chip": {"id": x["id"], "label": x["label"][:120], "kind": x.get("kind") or "entity",
                             "type": x.get("type")}}
        if isinstance(x.get("text"), str) and x["text"].strip():
            return {"text": x["text"].strip()[:120], "hint": hint_of(x.get("type", x.get("hint")))}
    raise ValueError('each love is text, a [text, hint] pair, {"text", "type"} or a chip {id, label, kind, type}')


class ResolveFailed(RuntimeError):
    """Qloo stayed busy through every retry of the resolve window. `reason` is 'Qloo HTTP <status>' (no URL)."""

    def __init__(self, reason):
        super().__init__("Qloo unavailable while resolving")
        self.reason = str(reason or "Qloo busy")[:40]


def _window(q):
    w = getattr(q, "window", None)
    return w(RESOLVE_BUDGET_S) if w else contextlib.nullcontext()


def prepare(city_text, loves, q, mode):
    """Resolve the city and every love. Returns {"status": "ok"|"needs_input", "city", "loves", ...}.
    All of it shares one resolve window: jittered retries on 429/5xx/timeouts, 12 s in all."""
    with _window(q):
        return _prepare(city_text, loves, q, mode)


def _prepare(city_text, loves, q, mode):
    rc = resolve_city(city_text, q, mode)
    if rc.get("status") == "degraded":
        raise ResolveFailed(rc.get("reason"))
    city_text = city_key(city_text)[1]
    out = {"status": "ok", "city": rc.get("city"), "city_text": city_text, "city_resolution": rc, "loves": [],
           "resolutions": []}
    if rc.get("status") != "ok":
        out["status"] = "needs_input"
    for item in loves:
        if "chip" in item and API:
            out["loves"].append(item["chip"])
            out["resolutions"].append({"status": "ok", "chip": item["chip"]})
            continue
        if "chip" in item:   # the fallback re-resolves (cached, 0 calls) so the IDs it ranks with are the key's IDs
            text, hint = item["chip"]["label"], _hint(item["chip"])
        else:
            text, hint = item["text"], item.get("hint")
        r = resolve_love(text, hint, q, mode)
        if r.get("status") == "degraded":
            raise ResolveFailed(r.get("reason"))
        out["resolutions"].append(r)
        if r.get("status") != "ok":
            out["status"] = "needs_input"
        out["loves"].append(r.get("chip"))
    return out


# ---------------------------------------------------------------- the dated wall
def _seed_sid(ck, labels):
    def n(s):
        s = s.lower().replace("&", " and ")
        s = re.sub(r"[^a-z0-9 ]+", " ", s)
        return " ".join(re.sub(r"\b(the|original)\b", " ", s).split())
    mine = [n(t) for t in labels]
    for sid, loves in SD.SEED_SETS.get(ck, []):
        theirs = [n(t) for t, _ in loves]
        if len(mine) == len(theirs) and all(any(a in b or b in a for b in theirs) for a in mine):
            return sid
    return None


def city_wall(city_text, cache_dir):
    """The city's generic dated wall (the sets every love set shares: city wall, street, census), from the city text
    alone: static data, no Qloo call. The server streams it before resolving anything, so the first name is on
    screen at once. Unknown city text -> []."""
    ck, _ = city_key(city_text)
    path = walls_file(cache_dir)
    if not ck or not path:
        return []
    try:
        return [dict(a, lane=a.get("lane", "dated")) for a in W.wall_for(ck, None, path)["answers"]]
    except (OSError, ValueError, KeyError):
        return []


def wall_for(city, chips, cache_dir):
    """The dated wall for this (city, loves): static data, no network.
    {"answers": [...], "source": ..., "path": <walls file handed to the engine>, "missing": bool}."""
    path = walls_file(cache_dir)
    if path is None:
        return {"answers": [], "source": "no wall file", "path": empty_walls_file(cache_dir), "missing": True}
    w = _wall_from(city, chips, path)
    w.update(path=path, missing=False)
    return w


def _wall_from(city, chips, path):
    if API and hasattr(API, "match_set"):   # the same wall the engine will load (api.run_unsaid's own choice)
        ck = (city or {}).get("key") or CITY_KEY.get((city or {}).get("slug"))
        try:
            sid = API.match_set(ck, [API._love_from_chip(c) for c in chips])
            w = W.wall_for(ck, sid, path)
            return {"answers": [dict(a, lane=a.get("lane", "dated")) for a in w["answers"]], "source": w.get("source")}
        except (OSError, ValueError, KeyError, AttributeError) as e:
            return {"answers": [], "source": "wall unavailable: %s" % type(e).__name__}
    ck = CITY_KEY.get((city or {}).get("slug"))
    if not ck:
        return {"answers": [], "source": "no dated wall for this city yet"}
    sid = _seed_sid(ck, [c.get("label") or c.get("text") or "" for c in chips]) or "__generic__"
    try:
        w = W.wall_for(ck, sid, path)
    except (OSError, KeyError, ValueError):
        return {"answers": [], "source": "no dated wall available on this host"}
    answers = []
    for a in w["answers"]:
        b = dict(a)
        b.setdefault("lane", "dated")
        answers.append(b)
    return {"answers": answers, "source": w.get("source")}


def wall_items(answers, per=None):
    return list(iter_wall_items(answers, per))


def iter_wall_items(answers, per=None):
    """Wall items one at a time, so the server streams the first name before building the other ~2,700."""
    for a in answers:
        for n in a.get("names", []):
            name = n["name"] if isinstance(n, dict) else n
            it = {"name": name, "norm": M.norm(name), "provider": a.get("provider"), "model": a.get("model"),
                  "phrasing_id": a.get("phrasing_id") or a.get("phrasing"),
                  "phrasing": a.get("phrasing_text") or a.get("phrasing"), "asked_at": a.get("asked_at"),
                  "lane": a.get("lane", "dated"), "outcome": None, "reason": None, "qloo_id": None}
            if per is not None:
                info = per.get(name) or {}
                st = info.get("status")
                if st in ("struck", "struck_unsure"):
                    it.update(outcome="struck", reason="in pool", qloo_id=(info.get("ids") or [None])[0])
                elif st == "outside_pool":
                    it.update(outcome="dimmed", reason="not in pool", qloo_id=info.get("resolved_id"))
                else:
                    it.update(outcome="dimmed", reason="not found in Qloo")
            yield it


# ---------------------------------------------------------------- run
GEMINI_LANES = ("live lane", "street check")   # engine lanes_failed prefixes that are the Gemini lane


def run(prep, wall, q, mode, gemini, emit, deadline_s=90.0, timing=None):
    """One fresh run. `emit(evt)` streams CONTRACT events. Returns the CONTRACT result (no `key`; the server adds it).
    Raises QlooError when Qloo fails; the server turns that into `degraded`."""
    if API:
        def forward(e):           # every other event, burn's `risen` included, goes out unchanged
            if e.get("type") == "done":
                return                      # the server sends the one done line, with the key
            if e.get("type") == "wall_name" and e.get("lane") != "live":
                return                      # the server already streamed the dated wall before the run
            emit(e)
        live = gemini is not None and gemini.live
        if not live and gemini is not None:
            gemini.reasons.append(gemini.reason)
        lane = _ApiTaste(gemini, prep, timing) if live else False  # False: no engine stand-in, never a fake live answer
        street = dated_street(wall)                                # dated answers only, never a live street ask
        seen = CappedLastSeen() if mode == "live" else None      # None: the engine's fake check in fake mode
        resolved = prep["city_resolution"].get("_city")        # the city resolved once, never re-resolved here
        return API.run_unsaid(resolved if isinstance(resolved, dict) else prep["city_text"], prep["loves"],
                              walls_path=wall["path"],
                              mode=mode, qloo=q, gemini=lane, street_check=street, on_event=forward, last_seen=seen,
                              deadline_s=max(1.0, min(90.0, float(deadline_s))))
    return _run_fallback(prep, wall, q, mode, gemini, emit, timing)


class _ApiTaste:
    """The engine calls gemini.ask(prompt) once, on its own thread beside the Qloo path. The answer must arrive
    within the lane's budget counted from the start of the run (15 s), or the run goes on dated_only."""

    def __init__(self, session, prep, timing=None):
        self.s, self.prep, self.timing = session, prep, timing
        self.deadline = time.monotonic() + session.lane.live_timeout

    def ask(self, prompt):
        if self.s.taste_used >= 1:
            raise RuntimeError("one taste ask per run")
        a = self.s.ask_taste_prompt(prompt, self.prep["city"]["id"], [c["id"] for c in self.prep["loves"]],
                                    deadline=self.deadline, timing=self.timing)
        if a is None:
            raise TimeoutError("gemini lane: %s" % (self.s.reasons[-1] if self.s.reasons else "unavailable"))
        return a


class CappedLastSeen:
    """The engine's last-seen hook (UNSAID.md §3.1), capped for a 0.15-CPU host. Every candidate's venue site is
    checked at once (engine prefetch), and the whole check has ONE budget per run (default 3 s, env
    UNSAID_LASTSEEN_S). A card whose site hasn't answered by then passes on hours alone, marked "hours only", as a
    card without a website does; hours and the 'closed' address check still apply. Late checks finish in the
    background and fill the 24 h site cache, so the next run has them."""

    def __init__(self, budget_s=None):
        from unsaid import lastseen
        self.ls = lastseen
        self.budget = float(budget_s if budget_s is not None else os.environ.get("UNSAID_LASTSEEN_S", "3"))
        self.deadline = None
        self.got, self.threads = {}, {}
        self.lock = __import__("threading").Lock()

    def _start(self, url):
        import threading
        with self.lock:
            if url in self.threads:
                return
            if self.deadline is None:
                self.deadline = time.monotonic() + self.budget

            def go():
                try:
                    r = self.ls.site(url)
                except Exception:
                    r = None
                with self.lock:
                    self.got[url] = r
            th = threading.Thread(target=go, name="lastseen", daemon=True)
            self.threads[url] = th
        th.start()

    def _wait(self, urls):
        for u in urls:
            th = self.threads.get(u)
            if th is not None:
                th.join(max(0.0, self.deadline - time.monotonic()))

    def prefetch(self, entities):
        urls = [prop(e, "website") for e in entities if prop(e, "website") and prop(e, "hours")]
        for u in dict.fromkeys(urls):
            self._start(u)
        self._wait(dict.fromkeys(urls))

    def __call__(self, e):
        now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        hours, addr, url = prop(e, "hours"), str(prop(e, "address") or ""), prop(e, "website")
        if "closed" in addr.lower():
            return False, {"checked_at": now, "how": "failed: address says closed"}
        if not hours:
            return False, {"checked_at": now, "how": "failed: no hours in Qloo"}
        if not url:
            return True, {"checked_at": now, "how": "hours only"}
        self._start(url)
        self._wait([url])
        with self.lock:
            s = self.got.get(url)
        if s is None:                                      # no answer within the run's budget
            return True, {"checked_at": now, "how": "hours only"}
        if s.get("ok"):
            return True, {"checked_at": s["checked_at"], "how": "hours + %s" % s["how"]}
        return False, {"checked_at": s["checked_at"], "how": "failed: %s" % s["how"]}


def dated_street(wall):
    """street_check from the dated wall only (no live street asks): the stored answers about that neighbourhood."""
    by = {}
    for a in (wall or {}).get("answers") or []:
        hood = a.get("hood") or (a.get("phrasing_id") or "").partition("street:")[2]
        if a.get("kind", "street" if hood else None) == "street" and hood and a.get("lane", "dated") == "dated":
            by.setdefault(slugify(hood), []).append(a)

    def fn(hood, city_name):
        return list(by.get(slugify(hood), []))
    return fn


def _int(s, i=0):
    try:
        return int(re.findall(r"\d+", s)[i])
    except (IndexError, TypeError):
        return None


def _run_fallback(prep, wall, q, mode, gemini, emit, timing=None):
    city, chips = prep["city"], prep["loves"]
    labels = [c["label"] for c in chips]
    answers = list(wall["answers"])
    if gemini is not None:
        a = gemini.ask_taste(city["name"], labels, city["id"], [c["id"] for c in chips], timing=timing)
        if a:
            answers.append(a)
            for it in wall_items([a]):
                emit(dict(it, type="wall_name"))
    spec = [(c["label"], _hint(c)) for c in chips]
    res = E.run(q, prep["city_resolution"]["_engine"], spec, {"answers": answers, "source": wall.get("source")})
    if res["status"] == "needs_input":
        return {"status": "needs_input", "flags": [], "loves": chips, "city": city, "picks": [], "reserves": [],
                "wall": wall_items(answers), "counts": {}, "burn": {"asked": [], "burned": []}, "diag": {}}
    d = res["diag"]
    U = {e["entity_id"]: e for e in res.get("_U", [])}
    emit({"type": "pool", "U": d.get("U")})
    items = wall_items(answers, res.get("_per") or {})
    for it in items:
        emit({"type": "strike", "norm": it["norm"], "outcome": it["outcome"], "reason": it["reason"]})
    city_asks = len(answers)
    as_of = max([a.get("asked_at") or "" for a in answers] or [""]) or None
    cards = []
    for c in res["cards"]:
        e = U.get(c["qloo_id"], {})
        ll = latlon(e) if e else None
        cards.append({
            "id": c["qloo_id"], "name": c["name"], "what": " · ".join(t.lower() for t in c.get("tags", [])[:2] if t),
            "because": (c.get("because") or {}).get("love"), "fit_rank": _int(c["fits"]),
            "any_rank": _int(c["city_order"]), "U": d.get("U"), "rating": c.get("rating"),
            "open": (not c["is_closed"]) if c.get("is_closed") is not None else None,
            "neighbourhood": c.get("neighbourhood") or "", "address": prop(e, "address", default="") or "",
            "lat": ll[0] if ll else None, "lon": ll[1] if ll else None, "url": prop(e, "website", default="") or "",
            "holds": _int(c["holds"]), "n_loves": len(chips), "tied": False,
            "never_said": {"asks": city_asks, "city_asks": city_asks, "street_asks": 0, "as_of": as_of}})
    picks, reserves = cards[:N_PICKS], cards[N_PICKS:]
    burn = {"asked": [], "burned": []}
    if picks:
        hoods = []
        for p in picks:
            if p["neighbourhood"] and p["neighbourhood"] not in hoods:
                hoods.append(p["neighbourhood"])
        burned_ids, risen = set(), set()
        street = dated_street(wall)
        for hood in hoods[:3]:
            got = street(hood, city["name"])
            if not got:
                continue
            a = {"names": [n for x in got for n in x.get("names") or []], "asked_at": max(x.get("asked_at") or ""
                                                                                          for x in got)}
            said = [n["name"] for n in a["names"]]
            st, _ = M.match_wall(said, [{"entity_id": x["id"], "name": x["name"]} for x in picks + reserves], None)
            named = [x["name"] for x in picks + reserves if x["id"] in st]
            burn["asked"].append({"neighbourhood": hood, "lane": "dated", "asked_at": a["asked_at"], "named": named})
            for cid in st:
                if cid not in burned_ids:
                    burned_ids.add(cid)
                    b = {"card_id": cid, "by": "dated street answer", "at": a["asked_at"]}
                    burn["burned"].append(b)
                    nxt = None
                    if cid in {x["id"] for x in picks}:     # a burned pick: the next unburned reserve rises
                        nxt = next((x for x in reserves if x["id"] not in burned_ids and x["id"] not in risen), None)
                        if nxt is not None:
                            risen.add(nxt["id"])
                    emit(dict(b, type="burn", risen=nxt))
        survivors = [x for x in picks + reserves if x["id"] not in burned_ids]
        for x in survivors:   # "m about <its neighbourhood>" (S3): only asks about the card's own street count
            own = sum(1 for b in burn["asked"] if b["neighbourhood"] == x["neighbourhood"])
            x["never_said"].update(asks=city_asks + own, street_asks=own)
        picks = sorted(survivors[:N_PICKS], key=lambda x: x["fit_rank"] or 0)
        reserves = survivors[N_PICKS:N_PICKS + N_RESERVES]
    else:
        picks = sorted(picks, key=lambda x: x["fit_rank"] or 0)   # displayed in for-you order (§3.3 step 7)
    for p in picks:
        emit(dict(p, type="card"))
    n = len(picks)
    status = "ok" if n >= N_PICKS else ("empty_few" if n else "empty_none")
    drops = d.get("drops") or {}
    out = {
        "status": status, "flags": list(res.get("flags") or []),
        "loves": [dict(c, dead=False) for c in chips], "city": city, "picks": picks, "reserves": reserves,
        "wall": items,
        "counts": {"wall": len({i["norm"] for i in items}), "asks": city_asks + len(burn["asked"]),
                   "P": d.get("P"), "U": d.get("U"), "S": d.get("S"), "R_mi": city.get("radius_mi"),
                   "floor": {"closed": drops.get("closed", 0),
                             "below_43": drops.get("rating", 0) + drops.get("no_rating", 0),
                             "outside_R": 0, "not_venue": 0}},
        "burn": burn,
        "diag": {"qloo_calls": q.calls["network"], "qloo_cache_hits": q.calls["cache"],
                 "rho_tp": _num(d.get("rho_taste_pop")), "rho_res": None, "cap_keep": None, "cap_shared": None,
                 "engine_v": ENGINE_V, "as_of": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "trace_url": None,
                 "wall_source": wall.get("source"), "backend": BACKEND},
    }
    if status == "empty_none":
        out["known"] = res.get("fallback") or []
    return out


def _num(x):
    return round(x, 3) if isinstance(x, (int, float)) and x == x else None


def describe_error(e):
    """A short reason with no URL, body or key in it."""
    if isinstance(e, QlooError):
        return "Qloo HTTP %s" % e.status
    if isinstance(e, ResolveFailed):
        return "%s (%s)" % (type(e).__name__, e.reason)
    return type(e).__name__


def trace_tail(e):
    return "".join(traceback.format_exception_only(type(e), e)).strip()[:300]
