"""Bridge between the server and the engine.

If engine/unsaid/api.py exists (Agent D, CONTRACT.md), it is used: run_unsaid, resolve_love, resolve_city.
Until then this falls back to the round-3 kit's engine.run (fake mode), mapped onto the CONTRACT result shape.
The server never imports engine internals anywhere else.
"""
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

API = None
API_ERROR = None
if os.path.exists(os.path.join(ENGINE, "unsaid", "api.py")):
    try:
        from unsaid import api as API  # noqa: E402
    except Exception as e:  # D's file mid-edit: keep serving from the fallback, say so in /api/health
        API, API_ERROR = None, "%s: %s" % (type(e).__name__, e)
        print("[adapter] engine api.py failed to import, using the fallback: %s" % API_ERROR, file=sys.stderr)

# The kit's default consensus path assumes the old research/ layout; point it at the real file when present.
_CONS = os.environ.get("UNSAID_CONSENSUS") or os.path.normpath(os.path.join(ROOT, "..", "research", "exp", "consensus.py"))
if not os.path.exists(getattr(W, "CONSENSUS", "") or "") and os.path.exists(_CONS):
    W.CONSENSUS = _CONS

ENGINE_V = getattr(API, "ENGINE_V", None) or "kit-v3+server-fallback-1"
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


def parse_love(x):
    """A love is plain text, {"text", "type"} or a resolved chip {"id", "label", "kind", "type"}."""
    if isinstance(x, str) and x.strip():
        return {"text": x.strip()[:120]}
    if isinstance(x, dict):
        if x.get("id") is not None:
            if not (isinstance(x["id"], str) and ID_RE.match(x["id"]) and isinstance(x.get("label"), str)):
                raise ValueError("a chip needs a Qloo id and a label")
            return {"chip": {"id": x["id"], "label": x["label"][:120], "kind": x.get("kind") or "entity",
                             "type": x.get("type")}}
        if isinstance(x.get("text"), str) and x["text"].strip():
            if x.get("type") is not None and x["type"] not in TYPES:
                raise ValueError("type is one of %s" % ", ".join(sorted(TYPES)))
            return {"text": x["text"].strip()[:120], "hint": x.get("type")}
    raise ValueError("each love is text, {text, type} or a chip {id, label, kind, type}")


def prepare(city_text, loves, q, mode):
    """Resolve the city and every love. Returns {"status": "ok"|"needs_input", "city", "loves", ...}."""
    rc = resolve_city(city_text, q, mode)
    if rc.get("status") == "degraded":
        raise RuntimeError("Qloo unavailable while resolving")
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
            raise RuntimeError("Qloo unavailable while resolving")
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


def wall_for(city, chips):
    """The dated wall for this (city, loves): static data, no network. {"answers": [...], "source": ...}."""
    if API and hasattr(API, "match_set"):   # the same wall the engine will load (api.run_unsaid's own choice)
        ck = (city or {}).get("key") or CITY_KEY.get((city or {}).get("slug"))
        try:
            sid = API.match_set(ck, [API._love_from_chip(c) for c in chips])
            w = W.wall_for(ck, sid, os.environ.get("UNSAID_WALLS"))
            return {"answers": [dict(a, lane=a.get("lane", "dated")) for a in w["answers"]], "source": w.get("source")}
        except (OSError, ValueError, KeyError, AttributeError) as e:
            return {"answers": [], "source": "wall unavailable: %s" % type(e).__name__}
    ck = CITY_KEY.get((city or {}).get("slug"))
    if not ck:
        return {"answers": [], "source": "no dated wall for this city yet"}
    sid = _seed_sid(ck, [c.get("label") or c.get("text") or "" for c in chips]) or "__generic__"
    try:
        w = W.wall_for(ck, sid, os.environ.get("UNSAID_WALLS"))
    except (OSError, KeyError, ValueError):
        return {"answers": [], "source": "no dated wall available on this host"}
    answers = []
    for a in w["answers"]:
        b = dict(a)
        b.setdefault("lane", "dated")
        answers.append(b)
    return {"answers": answers, "source": w.get("source")}


def wall_items(answers, per=None):
    out = []
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
            out.append(it)
    return out


# ---------------------------------------------------------------- run
def run(prep, wall, q, mode, gemini, emit):
    """One fresh run. `emit(evt)` streams CONTRACT events. Returns the CONTRACT result (no `key`; the server adds it).
    Raises QlooError when Qloo fails; the server turns that into `degraded`."""
    if API:
        def forward(e):
            if e.get("type") == "done":
                return                      # the server sends the one done line, with the key
            if e.get("type") == "wall_name" and e.get("lane") != "live":
                return                      # the server already streamed the dated wall before the run
            emit(e)
        live = gemini is not None and gemini.live
        if not live and gemini is not None:
            gemini.reasons.append(gemini.reason)
        lane = _ApiTaste(gemini, prep) if live else False         # False: no engine stand-in, never a fake live answer
        street = _api_street(gemini, prep) if live else False
        return API.run_unsaid(prep["city_text"], prep["loves"], walls_path=os.environ.get("UNSAID_WALLS"),
                              mode=mode, qloo=q, gemini=lane, street_check=street, on_event=forward)
    return _run_fallback(prep, wall, q, mode, gemini, emit)


class _ApiTaste:
    """The engine calls gemini.ask(prompt) once; the lane session keeps the guards, the cache and asked_at."""

    def __init__(self, session, prep):
        self.s, self.prep = session, prep

    def ask(self, prompt):
        if self.s.taste_used >= 1:
            raise RuntimeError("one taste ask per run")
        self.s.taste_used += 1
        a = self.s._ask("taste-all", prompt, self.prep["city"]["id"], [c["id"] for c in self.prep["loves"]])
        if a is None:
            raise RuntimeError("gemini lane: %s" % (self.s.reasons[-1] if self.s.reasons else "unavailable"))
        return a


def _api_street(session, prep):
    def fn(hood, city_name):
        a = session.ask_street(hood, city_name, prep["city"]["id"])
        return [a] if a else []
    return fn


def _int(s, i=0):
    try:
        return int(re.findall(r"\d+", s)[i])
    except (IndexError, TypeError):
        return None


def _run_fallback(prep, wall, q, mode, gemini, emit):
    city, chips = prep["city"], prep["loves"]
    labels = [c["label"] for c in chips]
    answers = list(wall["answers"])
    if gemini is not None:
        a = gemini.ask_taste(city["name"], labels, city["id"], [c["id"] for c in chips])
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
    if gemini is not None and picks:
        hoods = []
        for p in picks:
            if p["neighbourhood"] and p["neighbourhood"] not in hoods:
                hoods.append(p["neighbourhood"])
        burned_ids = set()
        for hood in hoods[:3]:
            a = gemini.ask_street(hood, city["name"], city["id"])
            if not a:
                continue
            said = [n["name"] for n in a["names"]]
            st, _ = M.match_wall(said, [{"entity_id": x["id"], "name": x["name"]} for x in picks + reserves], None)
            named = [x["name"] for x in picks + reserves if x["id"] in st]
            burn["asked"].append({"neighbourhood": hood, "lane": "live", "asked_at": a["asked_at"], "named": named})
            for cid in st:
                if cid not in burned_ids:
                    burned_ids.add(cid)
                    b = {"card_id": cid, "by": "gemini", "at": a["asked_at"]}
                    burn["burned"].append(b)
                    emit(dict(b, type="burn"))
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
    return type(e).__name__


def trace_tail(e):
    return "".join(traceback.format_exception_only(type(e), e)).strip()[:300]
