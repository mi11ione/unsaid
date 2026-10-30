#!/usr/bin/env python3
"""UNSAID as MCP tools over stdio. Standard library only (Python 3.9+), zero install.

- `unsaid_places(loves, city)`: the product. Qloo's taste pool minus every place the AIs name, ranked by Qloo.
- `qloo_places(loves, city)`: the meter's "with" arm (UNSAID.md §3.8). The top 50 of the same Qloo taste pool,
  with NO subtraction: no wall, no strike. It never calls unsaid_places, which would make the arm true by construction.

Dual-era per the MCP spec 2026-07-28 ("Versioning and Compatibility"):
- modern clients: `server/discover` and per-request `_meta["io.modelcontextprotocol/protocolVersion"]`, stateless;
- legacy clients (Claude Desktop / Claude Code / most SDKs on 2025-11-25 and earlier): `initialize` handshake.

Modes (UNSAID_MODE):
- remote (the default): the hosted API at UNSAID_URL (default https://unsaid.mi11ion.io), the same engine, walls
  and live Qloo calls as the website. Needs no Qloo key and no engine kit. UNSAID_TOKEN is optional: without
  it, fresh runs share a per-address limit; with it, they get their own bucket. Cached repeats are free. Only unsaid_places is listed: the hosted API has no qloo_places endpoint.
- fake: the engine kit in ../engine (override with UNSAID_KIT) on its FakeQloo world, offline. Place names and
  numbers prove code paths, not Qloo. The wall is real saved AI answers.
- live + QLOO_API_KEY: the same local kit against hackathon.api.qloo.com.
Local modes run engine/unsaid/api.py run_unsaid, as the server does (same lanes, floor, strike, reverse and
last-seen checks), with the walls in UNSAID_WALLS (default ../data/walls). A city with no AI answers on file gets an
empty wall and the `no_wall` flag, never another city's wall.

stdout carries only JSON-RPC lines. Everything else (kit prints, logs) goes to stderr.
"""
import contextlib
import json
import os
import re
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.environ.get("UNSAID_KIT") or os.path.normpath(os.path.join(HERE, "..", "engine"))

SERVER_INFO = {"name": "unsaid", "title": "UNSAID", "version": "0.6.0"}
MODERN = ["2026-07-28"]
LEGACY = ["2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"]
MODE = (os.environ.get("UNSAID_MODE") or "remote").strip().lower()
if MODE not in ("remote", "fake", "live"):
    MODE = "remote"
REMOTE = MODE == "remote"
FAKE = MODE == "fake"
URL = (os.environ.get("UNSAID_URL") or "https://unsaid.mi11ion.io").rstrip("/")
TOKEN = (os.environ.get("UNSAID_TOKEN") or "").strip()
UA = "unsaid-mcp/%s (+https://unsaid.mi11ion.io/agents.html)" % SERVER_INFO["version"]
REMOTE_TIMEOUT_S = float(os.environ.get("UNSAID_REMOTE_TIMEOUT_S", "150"))
OUT = sys.stdout                      # the protocol channel; nothing else may write here

if not REMOTE:                        # the local kit; remote mode needs none of it
    sys.path.insert(0, KIT)
    from unsaid import api as A, cities as CI, engine as E, seeds as SD  # noqa: E402
    from unsaid.qloo import Qloo, QlooError, prop  # noqa: E402
else:
    class QlooError(Exception):
        status = None

INSTRUCTIONS = (
    "UNSAID returns places to eat and drink that fit a person's taste and that the dated Claude and GPT answers "
    "for that city don't name. Call unsaid_places when a user wants recommendations that are personal and not the usual list. "
    "Every pick is a Qloo entity ranked by Qloo; do not suggest other places to eat or drink. You may name "
    "places from `wall.top_names` as what every assistant tells everyone. qloo_places returns Qloo's own taste "
    "ranking for the same loves and city with nothing crossed out.")

TYPES = ["artist", "movie", "tv_show", "book", "podcast", "videogame", "brand", "place", "tag"]

TOOL = {
    "name": "unsaid_places",
    "title": "UNSAID: places the AI answers didn't name, ranked for your loves",
    "description": (
        "Crosses out places named in dated Claude and GPT answers (plus a live Gemini ask where available) and "
        "ranks the rest by how much better each fits your loves, per Qloo's rank for each love, than its "
        "popularity or its fit for most tastes. Input: up to three things a person loves (any mix of music, film, "
        "TV, books, brands, a place, or a dish/cuisine/vibe) and a city (the hosted API serves St. Louis and New "
        "York City). Returns up to 7 picks, each with its Qloo id, '#k for you' (rank among the same N places with the person's taste) and "
        "'#j for anyone' (rank among the same N with no taste signal), whether it holds if any one love is "
        "dropped, a reason (\"fits all three of your loves\"; else \"because you love <love>\" when a dish love "
        "credits it or it holds for two loves; none when it rests on one love alone), and how many of the AI answers on file named it (0: those were crossed "
        "out). Also returns the wall: how many distinct places those answers named and the most-named ones. Use it for 'not the usual list' asks. "
        "For where to eat and drink, use only these picks, in the order given; keep your own non-venue color "
        "(neighbourhoods, history, music, what to order). Say once that the usual places (wall.top_names) are "
        "great but everyone gets them. If status is needs_input, fix the input it names (e.g. a full title or a "
        "type) and call again. Pass a type for dishes and places ('tag' for a dish like rib tips, 'place' for a "
        "restaurant or bar): untyped, they can resolve to the wrong thing. A fresh run takes 20-90 s; repeats are cached and instant."),
    "inputSchema": {
        "type": "object",
        "properties": {
            "loves": {
                "type": "array", "minItems": 1, "maxItems": 3,
                "description": "Exactly three works best. Each is a string (\"Frankie Beverly & Maze\"), "
                               "{\"text\", \"type\"}, or a [text, type] pair. ALWAYS give a type for a dish and "
                               "for a place: 'tag' for a dish, cuisine or vibe ({\"text\": \"rib tips\", \"type\": "
                               "\"tag\"}; untyped, \"rib tips\" can resolve to a restaurant), 'place' for a "
                               "restaurant or bar. Give a type whenever a name is ambiguous. Prefer full official "
                               "titles.",
                "items": {"anyOf": [
                    {"type": "string", "minLength": 1, "maxLength": 120},
                    {"type": "object", "properties": {
                        "text": {"type": "string", "minLength": 1, "maxLength": 120},
                        "type": {"type": "string", "enum": TYPES}},
                     "required": ["text"], "additionalProperties": False},
                    {"type": "array", "minItems": 1, "maxItems": 2,
                     "items": {"type": ["string", "null"], "maxLength": 120}}]}},
            "city": {"type": "string", "minLength": 2, "maxLength": 80,
                     "description": "City, with region when ambiguous: \"St. Louis, Missouri\"."},
        },
        "required": ["loves", "city"],
        "additionalProperties": False,
    },
    "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
}

PICK_SCHEMA = {
    "type": "object",
    "required": ["qloo_id", "name", "for_you", "for_anyone", "of", "ranks", "holds", "because", "ai_named", "ai_asked"],
    "properties": {
        "qloo_id": {"type": "string"}, "name": {"type": "string"},
        "neighbourhood": {"type": ["string", "null"]}, "what": {"type": "array", "items": {"type": "string"}},
        "rating": {"type": ["number", "null"]}, "open": {"type": ["boolean", "null"]},
        "for_you": {"type": "integer"}, "for_anyone": {"type": ["integer", "null"]}, "of": {"type": "integer"},
        "ranks": {"type": "string"}, "lift_pts": {"type": ["integer", "null"]},
        "address": {"type": ["string", "null"]}, "url": {"type": ["string", "null"]},
        "why": {"type": ["string", "null"]},
        "blurb": {"type": ["string", "null"]}, "order": {"type": "array", "items": {"type": "string"}},
        "price": {"type": ["string", "null"]}, "image": {"type": ["string", "null"]},
        "hours": {"type": ["object", "null"]}, "tz": {"type": ["string", "null"]},
        "distance_mi": {"type": ["number", "null"]}, "distance_from": {"type": ["string", "null"]},
        "holds": {"type": "string"},
        "because": {"type": "object", "properties": {"love": {"type": ["string", "null"]},
                                                     "share": {"type": ["number", "null"]},
                                                     "line": {"type": ["string", "null"]},
                                                     "source": {"type": "string"}}},
        "ai_named": {"type": "integer"}, "ai_asked": {"type": "integer"},
    },
}
TOOL["outputSchema"] = {
    "type": "object",
    "required": ["status", "mode", "city", "loves", "picks", "wall", "flags", "qloo_calls", "as_of"],
    "properties": {
        "status": {"type": "string", "enum": ["ok", "empty_few", "empty_none", "needs_input", "partial", "degraded",
                                             "limited", "queued", "waking", "error"]},
        "mode": {"type": "string", "enum": ["fake", "live", "remote"]},
        "message": {"type": "string"},
        "city": {"type": ["object", "null"]},
        "loves": {"type": "array"},
        "picks": {"type": "array", "items": PICK_SCHEMA},
        "wall": {"type": "object", "properties": {
            "distinct_names": {"type": "integer"}, "answers": {"type": "integer"},
            "struck_in_pool": {"type": "integer"}, "top_names": {"type": "array", "items": {"type": "string"}},
            "source": {"type": "string"}}},
        "pool": {"type": "object"},
        "flags": {"type": "array", "items": {"type": "string"}},
        "qloo_calls": {"type": "object"},
        "fallback_known": {"type": "array", "items": {"type": "string"}},
        "notes": {"type": "array", "items": {"type": "string"}},
        "lanes": {"type": "object"},
        "host": {"type": "object"},
        "as_of": {"type": "string"},
    },
}

QLOO_TOOL = {
    "name": "qloo_places",
    "title": "Qloo: places ranked for your taste",
    "description": (
        "Given up to three things a person loves (music, film, TV, books, brands, a place, or a dish/cuisine/vibe) "
        "and a city, returns the top 50 places to eat and drink that Qloo ranks for those loves, in Qloo's order, "
        "each with its Qloo id, neighbourhood, rating and what it is. Nothing is removed: this is Qloo's taste "
        "ranking as is. If status is needs_input, fix the input it names and call again."),
    "inputSchema": json.loads(json.dumps(TOOL["inputSchema"])),
    "annotations": dict(TOOL["annotations"]),
}
PLACE_SCHEMA = {
    "type": "object", "required": ["rank", "qloo_id", "name"],
    "properties": {"rank": {"type": "integer"}, "qloo_id": {"type": "string"}, "name": {"type": "string"},
                   "neighbourhood": {"type": ["string", "null"]}, "what": {"type": "array", "items": {"type": "string"}},
                   "rating": {"type": ["number", "null"]}, "open": {"type": ["boolean", "null"]}},
}
QLOO_TOOL["outputSchema"] = {
    "type": "object",
    "required": ["status", "mode", "city", "loves", "places", "subtraction", "qloo_calls", "as_of"],
    "properties": {
        "status": {"type": "string", "enum": ["ok", "empty_none", "needs_input"]},
        "mode": {"type": "string", "enum": ["fake", "live"]},
        "message": {"type": "string"},
        "city": {"type": ["object", "null"]},
        "loves": {"type": "array"},
        "places": {"type": "array", "items": PLACE_SCHEMA},
        "subtraction": {"type": "string", "enum": ["none"]},
        "pool": {"type": "object"},
        "qloo_calls": {"type": "object"},
        "as_of": {"type": "string"},
    },
}
TOOLS = [TOOL] if REMOTE else [TOOL, QLOO_TOOL]
QLOO_TOP = 50

STATES = {"al": "Alabama", "ak": "Alaska", "az": "Arizona", "ar": "Arkansas", "ca": "California", "co": "Colorado",
          "ct": "Connecticut", "de": "Delaware", "dc": "District of Columbia", "fl": "Florida", "ga": "Georgia",
          "hi": "Hawaii", "id": "Idaho", "il": "Illinois", "in": "Indiana", "ia": "Iowa", "ks": "Kansas",
          "ky": "Kentucky", "la": "Louisiana", "me": "Maine", "md": "Maryland", "ma": "Massachusetts",
          "mi": "Michigan", "mn": "Minnesota", "ms": "Mississippi", "mo": "Missouri", "mt": "Montana",
          "ne": "Nebraska", "nv": "Nevada", "nh": "New Hampshire", "nj": "New Jersey", "nm": "New Mexico",
          "ny": "New York", "nc": "North Carolina", "nd": "North Dakota", "oh": "Ohio", "ok": "Oklahoma",
          "or": "Oregon", "pa": "Pennsylvania", "ri": "Rhode Island", "sc": "South Carolina", "sd": "South Dakota",
          "tn": "Tennessee", "tx": "Texas", "ut": "Utah", "vt": "Vermont", "va": "Virginia", "wa": "Washington",
          "wv": "West Virginia", "wi": "Wisconsin", "wy": "Wyoming"}
NO_WALL = ("No AI answers are on file for %s, so nothing was crossed out: these are Qloo's taste picks with no "
           "wall. UNSAID has dated AI answers for St. Louis and New York City.")
_CACHE = {}


def log(*a):
    print("[unsaid]", *a, file=sys.stderr)


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


# ---------------------------------------------------------------- inputs
def _norm(s):
    s = s.lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\b(the|original)\b", " ", s)
    return " ".join(s.split())


def _city_text(text):
    """'Austin, TX' -> 'Austin, Texas' (the engine checks the region against Qloo's locality name)."""
    if "," not in text:
        return text
    name, region = [x.strip() for x in text.split(",", 1)]
    return "%s, %s" % (name, STATES.get(region.lower().rstrip("."), region))


def _parse_loves(raw):
    """-> [(text, hint)]; the hint goes through to the engine's resolve_love(text, hint)."""
    out = []
    for x in raw:
        if isinstance(x, str):
            out.append((x.strip(), None))
        elif isinstance(x, (list, tuple)):
            out.append((x[0].strip(), x[1] if len(x) == 2 else None))
        else:
            out.append((x["text"].strip(), x.get("type")))
    return out


def _seed_set(city_key, love_texts):
    """Which preset set these loves are (order-free, containment), else None. Local mode only: its type hints fill
    untyped loves (live: /search decides the rest)."""
    mine = [_norm(t) for t in love_texts]
    for sid, loves in SD.SEED_SETS.get(city_key, []):
        theirs = [_norm(t) for t, _ in loves]
        if len(mine) == len(theirs) and all(any(a in b or b in a for b in theirs) for a in mine):
            return sid, loves
    return None, None


def _fill_hints(spec, city_text):
    ck, _ = CI.lookup(city_text)
    _, seed = _seed_set(ck, [t for t, _ in spec]) if ck else (None, None)
    if not seed:
        return spec
    return [(t, h or next((sh for st, sh in seed if _norm(st) in _norm(t) or _norm(t) in _norm(st)), None))
            for t, h in spec]


# ---------------------------------------------------------------- the CONTRACT result -> the tool's output
NUM_WORD = {2: "both", 3: "all three"}


def _love_name(l):
    """A love's display name, the site's rule: typed text equal to Qloo's label but for case -> Qloo's label; typed
    text with any capital -> as typed ("Frankie Beverly & Maze"); all lower case and different -> Qloo's label."""
    t, q = (l.get("text") or "").strip(), (l.get("resolved") or "").strip()
    if not t or not q:
        return q or t
    if t.lower() == q.lower():
        return q
    return t if any(ch.isupper() for ch in t) else q


def reason(c, loves):
    """The site's reason rule: holds for every live love -> "fits all three of your loves" ("both"); a dish or tag
    love credits it -> "because you love <dish>"; holds >= 2 (or a single live love) -> "because you love <love>";
    holds 1 with an entity credit -> no reason (None)."""
    holds, nl, b = c.get("holds"), c.get("n_loves") or 0, c.get("because")
    # a dish love counts toward "all" only when the place's own text names the dish (Qloo's link is not the menu)
    text = " ".join([" ".join(c.get("order") or []), c.get("line") or "", c.get("blurb") or "", c.get("what") or ""]).lower()
    dishes_hold = all(all(w in text for w in re.findall(r"[a-z]{3,}", _love_name(l).lower()))
                      for l in loves if l.get("kind") == "tag" and l.get("resolved"))
    if holds is not None and nl >= 2 and holds == nl and dishes_hold:
        return "fits %s of your loves" % NUM_WORD.get(nl, "all %d" % nl)
    if not b:
        return None
    love = next((l for l in loves if b in (l.get("resolved"), l.get("text"))), None)
    name = _love_name(love) if love else b
    if (love and love.get("kind") == "tag") or holds is None or holds >= 2:
        return "because you love %s" % name
    return None


def _pick(c, loves=()):
    fy, fa, n = c.get("fit_rank"), c.get("any_rank"), c.get("U")
    holds, nl = c.get("holds"), c.get("n_loves") or 0
    lift = c.get("lift")
    return {
        "qloo_id": c.get("id"), "name": c.get("name"), "neighbourhood": c.get("neighbourhood"),
        "address": c.get("address") or None, "url": c.get("url") or None,
        "what": [t for t in (c.get("what") or "").split(" · ") if t], "rating": c.get("rating"),
        "open": c.get("open"), "for_you": fy, "for_anyone": fa, "of": n,
        "ranks": ("#%d for you · #%d for anyone" % (fy, fa)) if fa is not None else "#%d for you" % fy,
        "lift_pts": int(round(100 * lift)) if isinstance(lift, (int, float)) else None,
        "holds": ("%d of %d" % (holds, nl)) if holds is not None else "n/a (1 love)",
        "because": {"love": c.get("because"), "share": None, "source": "best per-love rank (C6')",
                    "detail": c.get("because_detail"),
                    "line": reason(c, loves)},
        "why": c.get("why"),
        # what Qloo knows about the place itself (the same insights responses; 0 extra calls)
        "blurb": c.get("blurb"), "order": list(c.get("order") or []), "price": c.get("price"),
        "image": c.get("image"), "hours": c.get("hours"), "tz": c.get("tz"),
        "distance_mi": c.get("distance_mi"), "distance_from": c.get("distance_from"),
        "ai_named": 0, "ai_asked": (c.get("never_said") or {}).get("asks") or 0}


def _wall(r):
    items = r.get("wall") or []
    freq, shown = {}, {}
    for it in items:
        k = it.get("place") or it.get("norm") or it.get("name")
        freq[k] = freq.get(k, 0) + 1
        shown.setdefault(k, {})
        shown[k][it.get("name")] = shown[k].get(it.get("name"), 0) + 1
    top = sorted(freq, key=lambda k: (-freq[k], str(k)))[:8]
    d, cn = r.get("diag") or {}, r.get("counts") or {}
    asked = {(it.get("provider"), it.get("phrasing_id"), it.get("asked_at")) for it in items}
    return {"distinct_names": d.get("wall_names") or len({it.get("norm") for it in items}),
            "answers": cn.get("asks") or len(asked), "struck_in_pool": cn.get("struck_in_U") or 0,
            "top_names": [max(shown[k], key=lambda n: (shown[k][n], -len(n or ""))) for k in top],
            "source": d.get("wall_source") or ("no AI answers on file" if not items else "dated AI answers")}


def _needs_message(r, city_res=None):
    """needs_input -> one sentence an agent can act on (local: r["needs"]; hosted: r["resolutions"] + city)."""
    parts = []
    needs = list(r.get("needs") or [])
    if not needs:
        if not r.get("city"):
            cr = city_res or {}
            needs.append({"field": "city", "text": cr.get("text"), "reason": cr.get("reason") or "city not found",
                          "alternatives": cr.get("alternatives") or []})
        for x in r.get("resolutions") or []:
            if x.get("status") != "ok":
                needs.append({"field": "love", "text": x.get("text"), "status": x.get("status"),
                              "alternatives": x.get("alternatives") or []})
    for n in needs:
        alts = n.get("alternatives") or []
        if n.get("field") == "city":
            cands = ["%s (%s)" % (a.get("name"), a.get("disamb")) for a in alts]
            parts.append("city: %s%s" % (n.get("reason") or "not found", (": " + "; ".join(cands[:5])) if cands else ""))
        else:
            cands = ["%s (%s)" % (a.get("label"), str(a.get("type") or "").split(":")[-1]) for a in alts[:4]]
            parts.append("love '%s' is %s%s" % (n.get("text"), "ambiguous" if n.get("status") == "needs_input"
                                                  else "not found in Qloo",
                                                  (": did you mean " + ", ".join(cands) + "?") if cands else ""))
    head = "; ".join(parts) or "check the input"
    return head + ("" if head.endswith("?") else ".") + (" Pass a love as [text, type] (artist, movie, tv_show, book, "
                                                         "podcast, videogame, brand, place, or tag for a dish/cuisine) "
                                                         "and a city with its region.")


def from_contract(r, mode, spec, city_text, city_res=None, host=None):
    """The engine/server result (CONTRACT.md) -> the tool's structuredContent. One shape for every mode."""
    texts = [t for t, _ in spec]
    loves = []
    for i, ch in enumerate(r.get("loves") or []):
        if not ch:
            continue
        loves.append({"text": ch.get("text") or (texts[i] if i < len(texts) else ch.get("label")), "status": "ok",
                      "qloo_id": ch.get("id"), "resolved": ch.get("label"), "kind": ch.get("kind"),
                      "type": ch.get("type"), "dead": bool(ch.get("dead")), "dead_line": ch.get("dead_line")})
    city = r.get("city")
    out = {"status": r.get("status") or "error", "mode": mode, "loves": loves, "picks": [], "flags": list(r.get("flags") or []),
           "city": {"name": city.get("name"), "qloo_id": city.get("id"), "slug": city.get("slug")} if city else None,
           "wall": _wall(r), "qloo_calls": {}, "as_of": now()}
    if host:
        out["host"] = host
    d, cn = r.get("diag") or {}, r.get("counts") or {}
    calls = d.get("calls") or {}
    out["qloo_calls"] = dict(calls, network=d.get("qloo_network")) if calls else {"total": d.get("qloo_calls") or 0}
    notes = [n.get("text") for n in r.get("notes") or [] if n.get("text")]
    if r.get("note") and r["note"] not in notes:
        notes.append(r["note"])
    if out["status"] == "needs_input":
        out["message"] = _needs_message(r, city_res)
        return out
    out["picks"] = [_pick(c, loves) for c in sorted(r.get("picks") or [], key=lambda c: c.get("fit_rank") or 0)]
    out["pool"] = {"P": cn.get("P"), "U": cn.get("U"), "after_strike": cn.get("S"), "held": d.get("kept"),
                   "rho_taste_vs_anyone": d.get("rho_tp")}
    if r.get("fallback"):
        out["fallback_known"] = [x.get("name") for x in r["fallback"] if x.get("name")]
    if r.get("lanes"):
        out["lanes"] = r["lanes"]
    if city and not r.get("wall") and out["status"] not in ("limited", "degraded", "queued", "waking", "error"):
        out["flags"] = sorted(set(out["flags"]) | {"no_wall"})
        notes.append(NO_WALL % city.get("name"))
    for ch in loves:
        if ch.get("dead_line"):
            notes.append(ch["dead_line"])
    if "fake" in out["flags"]:
        notes.append("FAKE MODE: pick names and ranks come from the kit's synthetic Qloo world and prove the code "
                     "path only. The wall is real saved AI answers (%s)." % out["wall"]["source"])
    if notes:
        out["notes"] = notes
        out["message"] = " ".join(n if n.rstrip().endswith((".", "?", "!")) else n + "." for n in notes)
    return out


# ---------------------------------------------------------------- unsaid_places: local (fake | live)
def _unsaid_local(loves, city):
    spec = _fill_hints(_parse_loves(loves), city)
    walls = os.environ.get("UNSAID_WALLS") or os.path.normpath(os.path.join(HERE, "..", "data", "walls"))
    r = A.run_unsaid(_city_text(city), [list(x) for x in spec], walls_path=walls if os.path.exists(walls) else None,
                     mode="fake" if FAKE else "live")
    if r.get("status") == "degraded":
        raise QlooErrorLike((r.get("diag") or {}).get("error") or "Qloo isn't answering")
    return from_contract(r, MODE, spec, city)


class QlooErrorLike(Exception):
    pass


# ---------------------------------------------------------------- unsaid_places: remote (the hosted API)
class RemoteError(Exception):
    pass


def _get(path, params, accept="application/json"):
    headers = {"User-Agent": UA, "Accept": accept}
    if TOKEN:
        headers["Authorization"] = "Bearer " + TOKEN
    req = urllib.request.Request("%s%s?%s" % (URL, path, urllib.parse.urlencode(params)), headers=headers)
    try:
        return urllib.request.urlopen(req, timeout=REMOTE_TIMEOUT_S)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise RemoteError("the hosted API needs the UNSAID token: set UNSAID_TOKEN in this server's env (it is "
                              "in the Devpost testing instructions)")
        if e.code == 400:
            try:
                body = json.loads(e.read().decode("utf-8"))
            except (ValueError, OSError):
                body = {}
            raise RemoteError("the hosted API refused the input (%s): %s" % (
                body.get("status") or "HTTP 400", body.get("note") or "check the city and the loves"))
        if e.code in (429, 503):
            raise RemoteError("the hosted API is busy (HTTP %d); try again in %s s" % (e.code, e.headers.get("Retry-After") or "60"))
        raise RemoteError("the hosted API returned HTTP %d" % e.code)
    except (urllib.error.URLError, OSError) as e:
        raise RemoteError("can't reach %s (%s)" % (URL, getattr(e, "reason", e)))


def _remote_love(t, h):
    return [t, h] if h else t


def _unsaid_remote(loves, city):
    spec = _parse_loves(loves)
    ctext = _city_text(city)
    params = {"city": ctext, "loves": json.dumps([_remote_love(t, h) for t, h in spec], ensure_ascii=False)}
    result, events = None, 0
    with _get("/api/unsaid", params, "application/x-ndjson") as resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line:
                continue
            try:
                evt = json.loads(line)
            except ValueError:
                continue
            events += 1
            if evt.get("type") == "done":
                result = evt.get("result") or {}
    if result is None:
        raise RemoteError("the hosted API closed the stream before the result (%d events)" % events)
    city_res = None
    if result.get("status") == "needs_input" and not result.get("city"):
        try:
            with _get("/api/resolve", {"kind": "city", "q": ctext}) as resp:
                city_res = json.loads(resp.read().decode("utf-8"))
        except (RemoteError, ValueError):
            city_res = None
    host = {"url": URL, "mode": "fake" if "fake" in (result.get("flags") or []) else "live",
            "cached": bool(result.get("cached")), "stored_at": result.get("stored_at"), "key": result.get("key"),
            "events": events}
    return from_contract(result, "remote", spec, city, city_res, host)


def unsaid_places(loves, city):
    key = json.dumps([loves, city], sort_keys=True)
    if key in _CACHE:
        return _CACHE[key]
    out = _unsaid_remote(loves, city) if REMOTE else _unsaid_local(loves, city)
    if out["status"] not in ("limited", "degraded", "queued", "waking", "error"):
        _CACHE[key] = out
    return out


# ---------------------------------------------------------------- qloo_places (local modes only)
def _city(q, text):
    name, region = text, None
    if "," in text:
        name, region = [x.strip() for x in text.split(",", 1)]
        region = STATES.get(region.lower().rstrip("."), region)
    c = E.resolve_city(q, name, region)
    if c.get("status") == "ok" and region is None:
        dis = {x["disamb"] for x in c.get("candidates", [])}
        if len(dis) > 1:
            return {"status": "needs_input", "reason": "'%s' is ambiguous; add the region" % name,
                    "candidates": c["candidates"]}
    return c


def _calls(trace):
    """Calls per engine step (C1 city, C2 love, C4 pool, C6' rescoring) + network/cache."""
    names = {"C1": "city /search", "C2": "loves /search+/v2/tags", "C4": "taste pool /v2/insights",
             "C5": "same places, no taste /v2/insights", "C6": "same places, each love dropped /v2/insights",
             "C7": "AI names -> Qloo ids /search"}
    c = {}
    for r in trace:
        k = names.get(r["label"][:2], r["label"].split()[0])
        c[k] = c.get(k, 0) + 1
    c["total"] = len(trace)
    c["from_cache"] = sum(1 for r in trace if r.get("cache"))
    return c


def qloo_places(loves, city):
    """The meter's "with" arm: Qloo's taste pool for these loves, top 50, NOTHING subtracted.
    Deliberately shares no code path with unsaid_places: no wall is loaded, nothing is matched or struck."""
    key = json.dumps(["qloo_places", loves, city], sort_keys=True)
    if key in _CACHE:
        return _CACHE[key]
    q = Qloo(fake=FAKE, cache_dir=os.path.join(HERE, ".cache"))
    spec = _parse_loves(loves)
    base = {"mode": "fake" if FAKE else "live", "loves": [], "places": [], "city": None, "subtraction": "none",
            "qloo_calls": {}, "as_of": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    c = _city(q, city)
    if c.get("status") != "ok":
        cands = ["%s (%s)" % (x["name"], x["disamb"]) for x in c.get("candidates", [])]
        msg = c.get("reason", "city not found")
        if FAKE and not cands:
            msg += ". Fake mode knows St. Louis and New York City only"
        return dict(base, status="needs_input", message=msg + (": " + "; ".join(cands) if cands else ""),
                    qloo_calls=_calls(q.trace))
    spec = _fill_hints(spec, city)  # type hints only; the preset set's wall is never read here
    resolved = [E.resolve_love(q, t, h) for t, h in spec]
    loves_out = [{"text": l.get("text"), "status": l.get("status"), "qloo_id": l.get("id"),
                  "resolved": l.get("name"), "kind": l.get("kind"), "type": l.get("type"),
                  "reason": l.get("reason")} for l in resolved]
    city_out = {"name": c.get("name"), "qloo_id": c.get("id"), "disamb": c.get("disamb")}
    if any(l.get("status") == "needs_input" for l in resolved):
        bad = [l["text"] for l in loves_out if l["status"] == "needs_input"]
        return dict(base, status="needs_input", city=city_out, loves=loves_out, qloo_calls=_calls(q.trace),
                    message="Qloo found no entity or tag for: %s. Give the full official title, or a type "
                            "(artist, movie, tv_show, book, brand, place, or tag for a dish/cuisine)." % ", ".join(bad))
    pool, U, drops = _qloo_pool(q, c, resolved)
    top = sorted(U, key=lambda e: e["_pos"])[:QLOO_TOP]
    places = [{"rank": i, "qloo_id": e["entity_id"], "name": e.get("name"),
               "neighbourhood": prop(e, "neighborhood"),
               "what": [t.get("name") for t in (e.get("tags") or []) if isinstance(t, dict) and t.get("name")][:3],
               "rating": prop(e, "business_rating"),
               "open": (not prop(e, "is_closed")) if prop(e, "is_closed") is not None else None}
              for i, e in enumerate(top, 1)]
    out = dict(base, status="ok" if places else "empty_none", city=city_out, loves=loves_out, places=places,
               pool={"P": len(pool), "U": len(U), "floor": {k: v for k, v in drops.items() if k != "ids"}},
               qloo_calls=_calls(q.trace))
    if FAKE:
        out["message"] = ("FAKE MODE: place names and ranks come from the kit's synthetic Qloo world and prove the "
                          "code path only.")
    _CACHE[key] = out
    return out


def _qloo_pool(q, c, loves):
    """The same U the engine ranks (per-love pools, the client floor with its distance check, extra pages when U
    is small), built from the engine's pool and floor steps only: no wall, no strike."""
    if not hasattr(E, "per_love_pools"):                       # the round-3 kit
        pool, _, _ = E.taste_pool(q, c, loves)
        U, drops = E.floor(pool)
        return pool, U, drops
    pool, _ = E.per_love_pools(q, c, loves)
    U, drops = E.floor(pool, c)
    if len(U) < E.CFG.get("U_MIN", 0) and E.CFG.get("EXTRA_OFFSETS"):
        more, _ = E.per_love_pools(q, c, loves, offsets=E.CFG["EXTRA_OFFSETS"])
        have = {e["entity_id"] for e in pool}
        pool += [e for e in more if e["entity_id"] not in have]
        U, drops = E.floor(pool, c)
    return pool, U, drops


def qloo_summary(r):
    if r["status"] == "needs_input":
        return "needs_input: " + r.get("message", "")
    lines = ["%s · %s: the top %d of Qloo's taste pool for these loves (%s places after the quality floor). "
             "Nothing removed." % (r["status"], r["city"]["name"], len(r["places"]), r["pool"]["U"])]
    for p in r["places"]:
        lines.append("%d. %s (%s) · %s · qloo:%s" % (p["rank"], p["name"], p["neighbourhood"],
                                                    ", ".join(p["what"]) or "-", p["qloo_id"]))
    if r["mode"] == "fake":
        lines.append(r["message"])
    return "\n".join(lines)


def summary(r):
    if r["status"] == "needs_input":
        return "needs_input: " + r.get("message", "")
    if not r["picks"] and r["status"] in ("limited", "degraded", "queued", "waking", "error"):
        return "%s: %s" % (r["status"], r.get("message") or "no result; try again in a minute")
    w = r["wall"]
    if "no_wall" in r["flags"]:
        lines = ["%s · %s: NO WALL (no AI answers on file for this city, nothing crossed out). %d places for these "
                 "loves, ranked by Qloo:" % (r["status"], r["city"]["name"], len(r["picks"]))]
    else:
        lines = ["%s · %s: AIs named %d distinct places in %d answers (%d were in this taste pool, all struck). "
                 "%d left for these loves, ranked by Qloo:" % (r["status"], r["city"]["name"], w["distinct_names"],
                                                              w["answers"], w["struck_in_pool"], len(r["picks"]))]
    for i, p in enumerate(r["picks"], 1):
        lines.append("%d. %s (%s) · %s · %s · holds %s%s%s · named by %d of %d AI answers · qloo:%s" % (
            i, p["name"], p["neighbourhood"] or "-", " · ".join(p["what"]) or "-", p["ranks"], p["holds"],
            (" · " + p["because"]["line"]) if p["because"].get("line") else "",
            (" · " + p["why"]) if p.get("why") else "", p["ai_named"], p["ai_asked"], p["qloo_id"]))
        extra = [x for x in (p.get("price"), p.get("blurb"),
                             ("people order " + ", ".join(p["order"])) if p.get("order") else None) if x]
        if extra:
            lines.append("   " + " · ".join(extra))
    if w["top_names"]:
        lines.append("Everyone else gets: " + ", ".join(w["top_names"]))
    if r.get("message"):
        lines.append(r["message"])
    return "\n".join(lines)


# ---------------------------------------------------------------- JSON-RPC / MCP
class RpcError(Exception):
    def __init__(self, code, message, data=None):
        Exception.__init__(self, message)
        self.code, self.message, self.data = code, message, data


def _check_args(a):
    if not isinstance(a, dict):
        raise ValueError("arguments must be an object")
    extra = set(a) - {"loves", "city"}
    if extra:
        raise ValueError("unknown argument(s): %s" % ", ".join(sorted(extra)))
    loves, city = a.get("loves"), a.get("city")
    if not isinstance(city, str) or len(city.strip()) < 2:
        raise ValueError("city must be a non-empty string, e.g. \"St. Louis, Missouri\"")
    if not isinstance(loves, list) or not 1 <= len(loves) <= 3:
        raise ValueError("loves must be a list of 1 to 3 items (three works best)")
    for x in loves:
        if isinstance(x, str) and x.strip():
            continue
        if isinstance(x, dict) and isinstance(x.get("text"), str) and x["text"].strip() and \
                (x.get("type") is None or x.get("type") in TYPES) and not (set(x) - {"text", "type"}):
            continue
        if isinstance(x, list) and 1 <= len(x) <= 2 and isinstance(x[0], str) and x[0].strip() and \
                (len(x) == 1 or x[1] is None or x[1] in TYPES):
            continue
        raise ValueError("each love is a string, {text, type} or [text, type]; type is one of %s" % ", ".join(TYPES))
    return loves, city.strip()


def call_tool(params):
    name = params.get("name")
    impl = {"unsaid_places": (unsaid_places, summary), "qloo_places": (qloo_places, qloo_summary)}.get(name)
    if impl is None:
        raise RpcError(-32602, "Unknown tool: %s" % name)
    fn, summarize = impl
    try:
        loves, city = _check_args(params.get("arguments") or {})
    except ValueError as e:
        return {"content": [{"type": "text", "text": "Invalid input: %s" % e}], "isError": True}
    if REMOTE and name == "qloo_places":
        return {"content": [{"type": "text", "text": "qloo_places runs only locally (UNSAID_MODE=live with "
                                                     "QLOO_API_KEY); the hosted API serves unsaid_places."}],
                "isError": True}
    try:
        r = fn(loves, city)
    except QlooError as e:
        r = None
        err = "Qloo returned HTTP %s; try again in a minute" % e.status  # never echo the URL or body
    except (RemoteError, QlooErrorLike) as e:
        r, err = None, str(e)
    except Exception as e:  # never kill the server on a tool failure
        log(traceback.format_exc())
        r, err = None, "%s: %s" % (type(e).__name__, e)
    if r is None:
        return {"content": [{"type": "text", "text": "%s failed: %s" % (name, err)}], "isError": True}
    return {"content": [{"type": "text", "text": summarize(r)},
                        {"type": "text", "text": json.dumps(r, ensure_ascii=False, default=str)}],
            "structuredContent": r, "isError": False}


def handle(msg, state, tools=None, call=None):
    """One JSON-RPC request -> result. tools/call: the hosted /mcp endpoint (server/mcp_http.py) passes its own
    tool list and call function; the stdio server uses TOOLS and call_tool."""
    method, params = msg.get("method"), msg.get("params") or {}
    meta = params.get("_meta") or {}
    pv = meta.get("io.modelcontextprotocol/protocolVersion")
    modern = pv is not None
    if modern:
        if pv not in MODERN:
            raise RpcError(-32022, "Unsupported protocol version", {"supported": MODERN + LEGACY, "requested": pv})
        if "io.modelcontextprotocol/clientCapabilities" not in meta:
            raise RpcError(-32602, "Missing required _meta field io.modelcontextprotocol/clientCapabilities")
    if method == "initialize":
        want = params.get("protocolVersion")
        ver = want if want in LEGACY else LEGACY[0]
        state["legacy"] = ver
        return {"protocolVersion": ver, "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER_INFO, "instructions": INSTRUCTIONS}
    if method == "server/discover":
        r = {"supportedVersions": MODERN + LEGACY, "capabilities": {"tools": {"listChanged": False}},
             "instructions": INSTRUCTIONS}
    elif method == "ping":
        r = {}
    elif method == "tools/list":
        r = {"tools": TOOLS if tools is None else tools}
    elif method == "tools/call":
        r = (call or call_tool)(params)
    else:
        raise RpcError(-32601, "Method not found: %s" % method)
    if modern:
        r = dict(r, resultType="complete", _meta={"io.modelcontextprotocol/serverInfo": SERVER_INFO})
    return r


def send(obj):
    OUT.write(json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str) + "\n")
    OUT.flush()


def main():
    sys.stdout = sys.stderr               # stray prints from the kit land on stderr
    state = {}
    log("ready (mode=%s, %s)" % (MODE, ("%s, token %s" % (URL, "set" if TOKEN else "not set")) if REMOTE else "kit=" + KIT))
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
            continue
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
            send({"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}})
            continue
        if "id" not in msg:          # notifications: initialized, cancelled, ... (no reply)
            continue
        if "method" not in msg:      # a response to us; we never send requests
            continue
        if os.environ.get("UNSAID_WIRELOG"):  # debug: which era/method a host opens with
            with open(os.environ["UNSAID_WIRELOG"], "a") as f:
                p = msg.get("params") or {}
                f.write("%s %s pv=%s\n" % (msg["method"], (p.get("clientInfo") or {}).get("name", ""),
                        p.get("protocolVersion") or (p.get("_meta") or {}).get("io.modelcontextprotocol/protocolVersion")))
        try:
            with contextlib.redirect_stdout(sys.stderr):
                result = handle(msg, state)
            send({"jsonrpc": "2.0", "id": msg["id"], "result": result})
        except RpcError as e:
            err = {"code": e.code, "message": e.message}
            if e.data is not None:
                err["data"] = e.data
            send({"jsonrpc": "2.0", "id": msg["id"], "error": err})
        except Exception as e:
            log(traceback.format_exc())
            send({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32603, "message": "Internal error: %s" % e}})


if __name__ == "__main__":
    main()
