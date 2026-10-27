#!/usr/bin/env python3
"""UNSAID as an MCP tool: `unsaid_places(loves, city)` over stdio. Standard library only (Python 3.9+), zero install.

Dual-era per the MCP spec 2026-07-28 ("Versioning and Compatibility"):
- modern clients: `server/discover` and per-request `_meta["io.modelcontextprotocol/protocolVersion"]`, stateless;
- legacy clients (Claude Desktop / Claude Code / most SDKs on 2025-11-25 and earlier): `initialize` handshake.

Backed by the round-3 engine kit (research/round3/engine/kit). Mode:
- UNSAID_MODE=fake (default): the kit's FakeQloo world. Place names and numbers prove code paths, not Qloo.
  The wall is real: the frontier-model answers saved in research/exp/consensus.py.
- UNSAID_MODE=live + QLOO_API_KEY: the same code path against hackathon.api.qloo.com (untested here: no key yet).
  UNSAID_WALLS=<walls.json> points at the consensus harness output.

stdout carries only JSON-RPC lines. Everything else (kit prints, logs) goes to stderr.
"""
import contextlib
import json
import os
import re
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.environ.get("UNSAID_KIT") or os.path.normpath(os.path.join(HERE, "..", "..", "round3", "engine", "kit"))
sys.path.insert(0, KIT)

from unsaid import engine as E, seeds as SD, walls as W, matcher as M  # noqa: E402
from unsaid.qloo import Qloo, QlooError  # noqa: E402

SERVER_INFO = {"name": "unsaid", "title": "UNSAID", "version": "0.4.0"}
MODERN = ["2026-07-28"]
LEGACY = ["2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"]
MODE = os.environ.get("UNSAID_MODE", "fake").lower()
FAKE = MODE != "live"
OUT = sys.stdout                      # the protocol channel; nothing else may write here
sys.stdout = sys.stderr               # stray prints from the kit land on stderr

INSTRUCTIONS = (
    "UNSAID returns places to eat and drink that fit a person's taste and that no major AI assistant names for "
    "that city. Call unsaid_places when a user wants recommendations that are personal and not the usual list. "
    "Every pick is a Qloo entity ranked by Qloo; do not suggest other places to eat or drink. You may name "
    "places from `wall.top_names` as what every assistant tells everyone.")

TYPES = ["artist", "movie", "tv_show", "book", "podcast", "videogame", "brand", "place", "tag"]

TOOL = {
    "name": "unsaid_places",
    "title": "UNSAID: places no AI names, ranked for your taste",
    "description": (
        "Given three things a person loves (any mix of music, film, TV, books, brands, a place, or a dish/cuisine/"
        "vibe) and a city, UNSAID asks ChatGPT, Claude and Gemini where to eat and drink there, crosses out every "
        "place they name (matched to Qloo IDs), and has Qloo rank what is left for those loves. Returns up to 7 "
        "picks, each with its Qloo id, '#k for you' (rank among the same N places with the person's taste) and "
        "'#j for anyone' (rank among the same N with no taste signal), whether it holds if any one love is "
        "dropped, the love that drives it, and how many AI answers named it (always 0). Also returns the wall: "
        "how many distinct places the AIs named and the most-named ones. Use it for 'not the usual list' asks. "
        "For where to eat and drink, use only these picks, in the order given; keep your own non-venue color "
        "(neighbourhoods, history, music, what to order). Say once that the usual places (wall.top_names) are "
        "great but everyone gets them. If status is needs_input, fix the input it names (e.g. a full title or a "
        "type) and call again. Takes ~1-25 s live."),
    "inputSchema": {
        "type": "object",
        "properties": {
            "loves": {
                "type": "array", "minItems": 1, "maxItems": 3,
                "description": "Exactly three works best. Each is a string (\"Frankie Beverly & Maze\") or "
                               "{\"text\", \"type\"}; give type when the name is ambiguous. Use 'tag' for a dish, "
                               "cuisine or vibe (\"rib tips\"). Prefer full official titles.",
                "items": {"anyOf": [
                    {"type": "string", "minLength": 1, "maxLength": 120},
                    {"type": "object", "properties": {
                        "text": {"type": "string", "minLength": 1, "maxLength": 120},
                        "type": {"type": "string", "enum": TYPES}},
                     "required": ["text"], "additionalProperties": False}]}},
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
        "for_you": {"type": "integer"}, "for_anyone": {"type": "integer"}, "of": {"type": "integer"},
        "ranks": {"type": "string"}, "lift_pts": {"type": "integer"},
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
        "status": {"type": "string", "enum": ["ok", "empty_few", "empty_none", "needs_input", "error"]},
        "mode": {"type": "string", "enum": ["fake", "live"]},
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
        "as_of": {"type": "string"},
    },
}

STATES = {"mo": "Missouri", "ny": "New York", "va": "Virginia", "il": "Illinois", "ca": "California"}
_CACHE = {}


def log(*a):
    print("[unsaid]", *a, file=sys.stderr)


# ---------------------------------------------------------------- the tool
def _norm(s):
    s = s.lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\b(the|original)\b", " ", s)
    return " ".join(s.split())


def _seed_set(city_key, love_texts):
    """Which pre-asked wall applies: a seed set whose loves match these (order-free, containment), else None."""
    mine = [_norm(t) for t in love_texts]
    for sid, loves in SD.SEED_SETS.get(city_key, []):
        theirs = [_norm(t) for t, _ in loves]
        if len(mine) == len(theirs) and all(any(a in b or b in a for b in theirs) for a in mine):
            return sid, loves
    return None, None


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


def _city_key(c):
    from unsaid.fake import LOCALITY_IDS
    for k, i in LOCALITY_IDS.items():
        if c.get("id") == i:
            return k
    n = (c.get("name") or "").lower()
    return "stl" if "louis" in n else ("nyc" if "new york" in n else None)


def _parse_loves(raw):
    out = []
    for x in raw:
        if isinstance(x, str):
            out.append((x.strip(), None))
        else:
            out.append((x["text"].strip(), x.get("type")))
    return out


def _calls(trace):
    """Calls per engine step (C1 city, C2 love, C4 pool, C5 baseline, C6 drop-one, C7 name match) + network/cache."""
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


def unsaid_places(loves, city):
    key = json.dumps([loves, city], sort_keys=True)
    if key in _CACHE:
        return _CACHE[key]
    q = Qloo(fake=FAKE, cache_dir=os.path.join(HERE, ".cache"))
    spec = _parse_loves(loves)
    base = {"mode": "fake" if FAKE else "live", "loves": [], "picks": [], "flags": [], "city": None,
            "wall": {}, "qloo_calls": {}, "as_of": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    c = _city(q, city)
    if c.get("status") != "ok":
        cands = ["%s (%s)" % (x["name"], x["disamb"]) for x in c.get("candidates", [])]
        msg = c.get("reason", "city not found")
        if FAKE and not cands:
            msg += ". Fake mode knows St. Louis and New York City only"
        return dict(base, status="needs_input", message=msg + (": " + "; ".join(cands) if cands else ""),
                    qloo_calls=_calls(q.trace))
    ck = _city_key(c)
    sid, seed = _seed_set(ck, [t for t, _ in spec]) if ck else (None, None)
    if seed:  # fill missing type hints from the matching seed set (live: /search decides)
        spec = [(t, h or next((sh for st, sh in seed if _norm(st) in _norm(t) or _norm(t) in _norm(st)), None))
                for t, h in spec]
    walls_file = os.environ.get("UNSAID_WALLS")
    wall = W.wall_for(ck or "stl", sid or "__generic__", walls_file)
    res = E.run(q, c, spec, wall)
    loves_out = [{"text": l.get("text"), "status": l.get("status"), "qloo_id": l.get("id"),
                  "resolved": l.get("name"), "kind": l.get("kind"), "type": l.get("type"),
                  "reason": l.get("reason")} for l in res.get("loves", [])]
    city_out = {"name": c.get("name"), "qloo_id": c.get("id"), "disamb": c.get("disamb")}
    if res["status"] == "needs_input":
        bad = [l["text"] for l in loves_out if l["status"] == "needs_input"]
        return dict(base, status="needs_input", city=city_out, loves=loves_out, qloo_calls=_calls(q.trace),
                    message="Qloo found no entity or tag for: %s. Give the full official title, or a type "
                            "(artist, movie, tv_show, book, brand, place, or tag for a dish/cuisine)." % ", ".join(bad))
    d = res["diag"]
    picks = []
    for card in sorted(res["cards"], key=lambda x: int(x["fits"].split()[0][1:])):  # shown in for-you order (v3 #7)
        fy, n = [int(v) for v in re.findall(r"\d+", card["fits"])]
        fa = int(re.findall(r"\d+", card["city_order"])[0])
        picks.append({
            "qloo_id": card["qloo_id"], "name": card["name"], "neighbourhood": card["neighbourhood"],
            "what": [t for t in card["tags"] if t], "rating": card["rating"],
            "open": (not card["is_closed"]) if card["is_closed"] is not None else None,
            "for_you": fy, "for_anyone": fa, "of": n, "ranks": "#%d for you · #%d for anyone" % (fy, fa),
            "lift_pts": card["lift_pts"], "holds": card["holds"], "because": card["because"],
            "ai_named": card["ai"]["named"], "ai_asked": card["ai"]["asked"]})
    names = W.names(wall)
    freq = {}
    for nm in names:
        freq[nm] = freq.get(nm, 0) + 1
    top = sorted(freq, key=lambda k: (-freq[k], k))[:8]
    out = dict(base, status=res["status"], city=city_out, loves=loves_out, picks=picks, flags=res.get("flags", []),
               wall={"distinct_names": d["wall"]["names"], "answers": d["wall"]["answers"],
                     "struck_in_pool": d["wall"]["struck"], "top_names": top, "source": d["wall"]["source"]},
               pool={"P": d.get("P"), "U": d.get("U"), "after_strike": d.get("S"), "held": d.get("kept"),
                     "rho_taste_vs_anyone": round(d["rho_taste_base"], 2) if d.get("rho_taste_base") == d.get("rho_taste_base") else None},
               qloo_calls=_calls(q.trace))
    if res.get("fallback"):
        out["fallback_known"] = res["fallback"]
    if FAKE and os.environ.get("UNSAID_REHEARSAL") == "1":  # demo rehearsal: lets the host write the live-shaped answer
        out["message"] = ("REHEARSAL: pick names are placeholders from a synthetic Qloo world, standing in for the "
                          "live picks. Present the plan exactly as you would live; add one short line at the end "
                          "saying the names are rehearsal placeholders. The wall is real saved AI answers.")
    elif FAKE:
        out["message"] = ("FAKE MODE: pick names and ranks come from the kit's synthetic Qloo world and prove the "
                          "code path only. The wall is real saved AI answers (%s)." % d["wall"]["source"])
    _CACHE[key] = out
    return out


def summary(r):
    if r["status"] == "needs_input":
        return "needs_input: " + r.get("message", "")
    w = r["wall"]
    lines = ["%s · %s: AIs named %d distinct places in %d answers (%d were in this taste pool, all struck). "
             "%d left for these loves, ranked by Qloo:" % (r["status"], r["city"]["name"], w["distinct_names"],
                                                          w["answers"], w["struck_in_pool"], len(r["picks"]))]
    for i, p in enumerate(r["picks"], 1):
        lines.append("%d. %s (%s) · %s · holds %s · %s · named by %d of %d AI answers · qloo:%s" % (
            i, p["name"], p["neighbourhood"], p["ranks"], p["holds"], p["because"].get("line"), p["ai_named"],
            p["ai_asked"], p["qloo_id"]))
    lines.append("Everyone else gets: " + ", ".join(w["top_names"]))
    if r["mode"] == "fake":
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
        raise ValueError("each love is a string or {text, type}; type is one of %s" % ", ".join(TYPES))
    return loves, city.strip()


def call_tool(params):
    name = params.get("name")
    if name != TOOL["name"]:
        raise RpcError(-32602, "Unknown tool: %s" % name)
    try:
        loves, city = _check_args(params.get("arguments") or {})
    except ValueError as e:
        return {"content": [{"type": "text", "text": "Invalid input: %s" % e}], "isError": True}
    try:
        r = unsaid_places(loves, city)
    except QlooError as e:
        r = None
        err = "Qloo returned HTTP %s; try again in a minute" % e.status  # never echo the URL or body
    except Exception as e:  # never kill the server on a tool failure
        log(traceback.format_exc())
        r, err = None, "%s: %s" % (type(e).__name__, e)
    if r is None:
        return {"content": [{"type": "text", "text": "UNSAID failed: " + err}], "isError": True}
    return {"content": [{"type": "text", "text": summary(r)},
                        {"type": "text", "text": json.dumps(r, ensure_ascii=False, default=str)}],
            "structuredContent": r, "isError": False}


def handle(msg, state):
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
        r = {"tools": [TOOL]}
    elif method == "tools/call":
        r = call_tool(params)
    else:
        raise RpcError(-32601, "Method not found: %s" % method)
    if modern:
        r = dict(r, resultType="complete", _meta={"io.modelcontextprotocol/serverInfo": SERVER_INFO})
    return r


def send(obj):
    OUT.write(json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str) + "\n")
    OUT.flush()


def main():
    state = {}
    log("ready (mode=%s, kit=%s)" % ("fake" if FAKE else "live", KIT))
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
