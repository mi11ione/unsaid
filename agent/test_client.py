#!/usr/bin/env python3
"""Minimal MCP stdio client: spawns unsaid_mcp.py and drives it like a host would. Standard library only.
  python3 -I test_client.py            -> fake mode checks + a remote smoke test; wire log in out/transcript.jsonl;
                                          exits 1 on any failed check
  python3 -I test_client.py --http https://unsaid.mi11ion.io/mcp
                                       -> only the hosted Streamable HTTP endpoint (UNSAID_TOKEN from the env)
  python3 -I test_client.py --record demo/live_transcript.jsonl
                                       -> also records one live agent session against the hosted API (remote mode)
Fake mode runs both eras: legacy (initialize -> notifications/initialized -> tools/list -> tools/call) and modern
2026-07-28 (server/discover -> tools/list -> tools/call, per-request _meta), plus error paths. Validates
structuredContent against the tool's outputSchema with a small JSON-Schema subset validator.
The remote smoke test calls the hosted API (UNSAID_URL, default https://unsaid.mi11ion.io) with UNSAID_TOKEN from
the environment, and is skipped when there is no token (or with --no-remote). The token is never written anywhere."""
import ast
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = [sys.executable, "-I", os.path.join(HERE, "unsaid_mcp.py")]
OUT = os.path.join(HERE, "out")       # gitignored
LOG = []
FAILS = []


class Client:
    def __init__(self, mode="fake", log=None):
        env = dict(os.environ, UNSAID_MODE=mode)
        self.p = subprocess.Popen(SERVER, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  universal_newlines=True, bufsize=1, env=env)
        self.n = 0
        self.log = LOG if log is None else log

    def _w(self, obj):
        line = json.dumps(obj)
        self.log.append({"dir": ">>", "msg": obj})
        self.p.stdin.write(line + "\n")
        self.p.stdin.flush()

    def notify(self, method, params=None):
        self._w({"jsonrpc": "2.0", "method": method, **({"params": params} if params else {})})

    def req(self, method, params=None):
        self.n += 1
        t0 = time.monotonic()
        self._w({"jsonrpc": "2.0", "id": self.n, "method": method, **({"params": params} if params else {})})
        line = self.p.stdout.readline()
        if not line:
            raise SystemExit("server closed stdout; stderr:\n" + self.p.stderr.read())
        msg = json.loads(line)  # also proves stdout carried a single valid JSON-RPC line
        self.log.append({"dir": "<<", "msg": msg, "ms": int((time.monotonic() - t0) * 1000)})
        assert msg.get("id") == self.n, "id mismatch"
        return msg

    def close(self):
        self.p.stdin.close()
        rc = self.p.wait(timeout=5)
        return rc, self.p.stderr.read()


def check(ok, what):
    print("  [%s] %s" % ("PASS" if ok else "FAIL", what))
    if not ok:
        FAILS.append(what)


def validate(v, s, path="$"):
    errs = []
    if "anyOf" in s:
        if all(validate(v, sub, path) for sub in s["anyOf"]):
            errs.append("%s matches no anyOf branch" % path)
        return errs
    t = s.get("type")
    if t:
        ts = t if isinstance(t, list) else [t]
        py = {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None)}
        ok = any((isinstance(v, py[x]) if x in py else
                  (isinstance(v, int) and not isinstance(v, bool)) if x == "integer" else
                  (isinstance(v, (int, float)) and not isinstance(v, bool))) for x in ts)
        if not ok:
            return ["%s: expected %s, got %r" % (path, t, type(v).__name__)]
    if "enum" in s and v not in s["enum"]:
        errs.append("%s: %r not in enum" % (path, v))
    if isinstance(v, dict):
        for k in s.get("required", []):
            if k not in v:
                errs.append("%s: missing %s" % (path, k))
        for k, sub in (s.get("properties") or {}).items():
            if k in v:
                errs += validate(v[k], sub, path + "." + k)
    if isinstance(v, list) and "items" in s:
        for i, x in enumerate(v):
            errs += validate(x, s["items"], "%s[%d]" % (path, i))
    return errs


CEDRIC = {"loves": ["Frankie Beverly & Maze", {"text": "Kings of Comedy", "type": "movie"}, {"text": "rib tips", "type": "tag"}],
          "city": "St. Louis, MO"}


def show_call(r, title):
    res = r.get("result", {})
    print("\n--- %s ---" % title)
    text = res["content"][0]["text"] if res.get("content") else json.dumps(r)[:400]
    print("\n".join(text.splitlines()[:12]))


def run_legacy():
    print("== legacy era (what Claude Desktop / Claude Code send today): initialize handshake")
    c = Client()
    r = c.req("initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
                             "clientInfo": {"name": "unsaid-test-client", "version": "0.1"}})
    check(r["result"]["protocolVersion"] == "2025-11-25", "initialize negotiates 2025-11-25")
    check("tools" in r["result"]["capabilities"], "server declares the tools capability")
    c.notify("notifications/initialized")
    r = c.req("tools/list")
    tools = r["result"]["tools"]
    check([t["name"] for t in tools] == ["unsaid_places", "qloo_places"],
          "tools/list returns exactly unsaid_places and qloo_places")
    schema = tools[0]["outputSchema"]
    qschema = tools[1]["outputSchema"]
    r = c.req("tools/call", {"name": "unsaid_places", "arguments": CEDRIC})
    res = r["result"]
    sc = res.get("structuredContent", {})
    check(res.get("isError") is False, "tools/call isError=false")
    errs = validate(sc, schema)
    check(not errs, "structuredContent validates against outputSchema" + ("" if not errs else ": %s" % errs[:3]))
    check(json.loads(res["content"][1]["text"]) == json.loads(json.dumps(sc)), "serialized JSON TextContent == structuredContent")
    check(sc["status"] == "ok" and len(sc["picks"]) == 7, "status ok, 7 picks")
    fy = [p["for_you"] for p in sc["picks"]]
    check(fy == sorted(fy), "picks shown in for-you order")
    check(all(p["ai_named"] == 0 for p in sc["picks"]), "every pick named by 0 AI answers")
    check(all(p["for_anyone"] > p["for_you"] for p in sc["picks"]), "every pick ranks higher for you than for anyone")
    wall_ids_lower = {n.lower() for n in sc["wall"]["top_names"]}
    check(not any(p["name"].lower() in wall_ids_lower for p in sc["picks"]), "no pick is on the wall's top names")
    show_call(r, "tools/call unsaid_places (legacy) -> content[0]")
    print("  wall: %s" % json.dumps(sc["wall"]))
    print("  qloo_calls: %s" % json.dumps(sc["qloo_calls"]))
    print("  loves resolved: %s" % json.dumps([(l["text"], l["kind"], l["status"]) for l in sc["loves"]]))
    run_qloo_places(c, qschema, sc)
    pairs = {"loves": [["Frankie Beverly & Maze", "artist"], ["The Original Kings of Comedy", "movie"],
                       ["rib tips", "tag"]], "city": "St. Louis, MO"}
    r = c.req("tools/call", {"name": "unsaid_places", "arguments": pairs})
    sp = r["result"].get("structuredContent") or {}
    rib = next((l for l in sp.get("loves", []) if l["text"] == "rib tips"), {})
    check(sp.get("status") == "ok" and rib.get("kind") == "tag",
          "[text, type] pairs accepted; 'rib tips' with type tag resolves to a tag (%s)" % rib.get("resolved"))
    r = c.req("tools/call", {"name": "unsaid_places", "arguments": {"loves": ["Kings of Comedy", "rib tips", "Frankie Beverly & Maze"],
                                                                    "city": "St. Louis"}})
    sc2 = r["result"]["structuredContent"]
    check(sc2["status"] in ("needs_input", "ok"), "untyped ambiguous love -> %s (%s)" % (sc2["status"], sc2.get("message", "")[:90]))
    r = c.req("tools/call", {"name": "unsaid_places", "arguments": {"loves": ["Al Green"], "city": "Richmond"}})
    sc3 = r["result"]["structuredContent"]
    check(sc3["status"] == "needs_input" and "ambiguous" in sc3["message"], "ambiguous city -> needs_input: %s" % sc3["message"][:110])
    r = c.req("tools/call", {"name": "unsaid_places", "arguments": {"loves": [], "city": "St. Louis"}})
    check(r["result"].get("isError") is True, "empty loves -> tool execution error (isError=true), model can self-correct")
    r = c.req("tools/call", {"name": "nope", "arguments": {}})
    check(r.get("error", {}).get("code") == -32602, "unknown tool -> JSON-RPC -32602")
    r = c.req("ping")
    check(r.get("result") == {}, "ping -> {}")
    rc, err = c.close()
    check(rc == 0, "server exits 0 on stdin EOF")
    return err


def run_qloo_places(c, qschema, unsaid_sc):
    """The meter's "with" arm: Qloo's taste pool, top 50, nothing subtracted, never via unsaid_places."""
    r = c.req("tools/call", {"name": "qloo_places", "arguments": CEDRIC})
    res = r["result"]
    sc = res.get("structuredContent", {})
    errs = validate(sc, qschema)
    check(res.get("isError") is False and not errs,
          "qloo_places: isError=false, validates against its outputSchema" + ("" if not errs else ": %s" % errs[:3]))
    U = sc.get("pool", {}).get("U")
    check(sc["status"] == "ok" and len(sc["places"]) == min(50, U) and
          [p["rank"] for p in sc["places"]] == list(range(1, len(sc["places"]) + 1)),
          "qloo_places: top %d of the taste pool, ranked 1..n" % len(sc["places"]))
    us = unsaid_sc["pool"]
    check(sc["subtraction"] == "none" and "wall" not in sc and U == us["U"] and us["after_strike"] < us["U"],
          "qloo_places: nothing subtracted (same pool U=%s that unsaid_places strikes down to %s)" % (U, us["after_strike"]))
    src = open(os.path.join(HERE, "unsaid_mcp.py")).read()
    fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == "qloo_places")
    called = {(x.func.attr if isinstance(x.func, ast.Attribute) else getattr(x.func, "id", ""))
              for x in ast.walk(fn) if isinstance(x, ast.Call)}
    banned = called & {"unsaid_places", "run", "match_wall", "wall_for", "strike", "names"}
    check(not banned, "qloo_places never calls unsaid_places, the engine run, the wall or the matcher%s"
          % ("" if not banned else ": calls %s" % sorted(banned)))
    show_call(r, "tools/call qloo_places (legacy) -> content[0], first lines")


def run_modern():
    print("\n== modern era (MCP 2026-07-28): no handshake, per-request _meta, server/discover")
    meta = {"io.modelcontextprotocol/protocolVersion": "2026-07-28",
            "io.modelcontextprotocol/clientInfo": {"name": "unsaid-test-client", "version": "0.1"},
            "io.modelcontextprotocol/clientCapabilities": {}}
    c = Client()
    r = c.req("server/discover", {"_meta": meta})
    check("2026-07-28" in r["result"]["supportedVersions"] and r["result"]["resultType"] == "complete",
          "server/discover -> DiscoverResult with 2026-07-28, resultType complete")
    r = c.req("tools/list", {"_meta": meta})
    check([t["name"] for t in r["result"]["tools"]] == ["unsaid_places", "qloo_places"] and "_meta" in r["result"],
          "tools/list (stateless) ok, serverInfo in _meta")
    r = c.req("tools/call", {"name": "unsaid_places", "arguments": CEDRIC, "_meta": meta})
    check(r["result"]["structuredContent"]["status"] == "ok", "tools/call (stateless) ok")
    r = c.req("tools/call", {"name": "qloo_places", "arguments": CEDRIC, "_meta": meta})
    check(r["result"]["structuredContent"]["status"] == "ok" and "_meta" in r["result"], "tools/call qloo_places (stateless) ok")
    bad = dict(meta, **{"io.modelcontextprotocol/protocolVersion": "1900-01-01"})
    r = c.req("tools/list", {"_meta": bad})
    check(r.get("error", {}).get("code") == -32022, "unknown version -> -32022 UnsupportedProtocolVersion, data=%s"
          % json.dumps(r.get("error", {}).get("data")))
    r = c.req("tools/list", {"_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28"}})
    check(r.get("error", {}).get("code") == -32602, "missing clientCapabilities -> -32602")
    c.close()


CEDRIC_PAIRS = {"loves": [["Frankie Beverly & Maze", "artist"], ["The Original Kings of Comedy", "movie"],
                          ["rib tips", "tag"]], "city": "St. Louis, MO"}
QUESTION = ("I love Frankie Beverly & Maze, The Original Kings of Comedy and rib tips. "
            "Where should I go in St. Louis tonight?")


def run_remote():
    """Smoke test of remote mode: the hosted API, real Qloo. Skipped without UNSAID_TOKEN."""
    print("\n== remote mode (the hosted API, %s)" % (os.environ.get("UNSAID_URL") or "https://unsaid.mi11ion.io"))
    if not os.environ.get("UNSAID_TOKEN"):
        print("  [SKIP] UNSAID_TOKEN is not set (it is in the Devpost testing instructions)")
        return
    c = Client("remote", [])
    r = c.req("initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
                             "clientInfo": {"name": "unsaid-test-client", "version": "0.2"}})
    check(r["result"]["serverInfo"]["name"] == "unsaid", "remote: initialize")
    c.notify("notifications/initialized")
    r = c.req("tools/list")
    tools = r["result"]["tools"]
    check([t["name"] for t in tools] == ["unsaid_places"], "remote: tools/list lists unsaid_places only")
    r = c.req("tools/call", {"name": "unsaid_places", "arguments": CEDRIC_PAIRS})
    res = r["result"]
    sc = res.get("structuredContent") or {}
    if res.get("isError") or sc.get("status") in ("limited", "degraded", "queued", "waking"):
        print("  [SKIP] the hosted API is busy or rate-limited: %s" % (sc.get("message") or res["content"][0]["text"])[:160])
        c.close()
        return
    errs = validate(sc, tools[0]["outputSchema"])
    check(not errs, "remote: structuredContent validates against outputSchema" + ("" if not errs else ": %s" % errs[:3]))
    check(sc.get("mode") == "remote" and sc.get("host", {}).get("mode") == "live" and "fake" not in sc.get("flags", []),
          "remote: live data from the hosted engine (no fake flag)")
    check(sc.get("status") in ("ok", "partial", "empty_few") and 1 <= len(sc.get("picks", [])) <= 7,
          "remote: %s, %d picks" % (sc.get("status"), len(sc.get("picks", []))))
    check(all(p["ai_named"] == 0 for p in sc["picks"]) and sc["wall"]["answers"] > 0,
          "remote: every pick named by 0 of %d AI answers" % sc["wall"]["answers"])
    rib = next((l for l in sc.get("loves", []) if l["text"] == "rib tips"), {})
    check(rib.get("kind") == "tag", "remote: [text, type] pairs reach the API ('rib tips' -> %s)" % rib.get("type"))
    r = c.req("tools/call", {"name": "qloo_places", "arguments": CEDRIC_PAIRS})
    check(r["result"].get("isError") is True, "remote: qloo_places -> isError (local modes only)")
    show_call({"result": res}, "tools/call unsaid_places (remote) -> content[0]")
    c.close()


def record(path):
    """One live agent session against the hosted API, as an MCP host would run it: the user's question, list the
    tools, call unsaid_places with the loves as [text, type] pairs, show the answer. Token redacted on write."""
    if not os.environ.get("UNSAID_TOKEN"):
        raise SystemExit("--record needs UNSAID_TOKEN in the environment")
    log = []
    c = Client("remote", log)
    c.req("initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
                         "clientInfo": {"name": "unsaid-demo-agent", "version": "0.2"}})
    c.notify("notifications/initialized")
    tools = c.req("tools/list")["result"]["tools"]
    r = c.req("tools/call", {"name": "unsaid_places", "arguments": {
        "loves": [["Frankie Beverly & Maze", "artist"], ["The Original Kings of Comedy", "movie"], ["rib tips", "tag"]],
        "city": "St. Louis, Missouri"}})
    rc, err = c.close()
    res = r["result"]
    head = {"kind": "session", "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "user": QUESTION,
            "agent": "agent/test_client.py --record (a scripted MCP host: list tools, call unsaid_places, show)",
            "server": "python3 -I agent/unsaid_mcp.py",
            "env": {"UNSAID_MODE": "remote", "UNSAID_URL": os.environ.get("UNSAID_URL") or "https://unsaid.mi11ion.io",
                    "UNSAID_TOKEN": "<redacted>"},
            "tools_listed": [t["name"] for t in tools], "server_exit": rc}
    tail = {"kind": "agent_answer", "text": res["content"][0]["text"] if res.get("content") else json.dumps(res)}
    tok = os.environ["UNSAID_TOKEN"]
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w") as f:
        for rec in [head] + log + [tail]:
            f.write(json.dumps(rec, ensure_ascii=False).replace(tok, "<redacted>") + "\n")
    print("\n== recorded %d lines to %s (token redacted)\n%s" % (len(log) + 2, path, tail["text"]))


def _http(url, obj=None, method="POST", token=None, accept="application/json, text/event-stream", pv=None):
    """One request to a Streamable HTTP MCP endpoint -> (status, headers, [JSON-RPC messages])."""
    import urllib.error
    import urllib.request
    headers = {"User-Agent": "unsaid-test-client/0.3", "Accept": accept, "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if pv:
        headers["MCP-Protocol-Version"] = pv
    data = json.dumps(obj).encode() if obj is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        resp = urllib.request.urlopen(req, timeout=180)
    except urllib.error.HTTPError as e:
        resp = e
    body = resp.read().decode("utf-8", "replace")
    ctype = resp.headers.get("Content-Type") or ""
    msgs = []
    if "text/event-stream" in ctype:
        for block in body.split("\n\n"):
            data_lines = [l[5:].strip() for l in block.splitlines() if l.startswith("data:")]
            if data_lines:
                msgs.append(json.loads("\n".join(data_lines)))
    elif body.strip():
        msgs.append(json.loads(body))
    return resp.status if hasattr(resp, "status") else resp.code, ctype, msgs


def run_http(url):
    """The hosted MCP endpoint (MCP Streamable HTTP): handshake, tools, a live call over SSE and over JSON, errors."""
    print("\n== Streamable HTTP: %s" % url)
    tok = os.environ.get("UNSAID_TOKEN")
    pv = "2025-11-25"
    st, ct, m = _http(url, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": pv, "capabilities": {}, "clientInfo": {"name": "unsaid-test-client", "version": "0.3"}}},
        token=tok)
    check(st == 200 and "application/json" in ct and m and m[0]["result"]["protocolVersion"] == pv,
          "http: initialize -> 200 JSON, protocol %s" % (m[0].get("result", {}).get("protocolVersion") if m else None))
    st, _, m = _http(url, {"jsonrpc": "2.0", "method": "notifications/initialized"}, token=tok, pv=pv)
    check(st == 202 and not m, "http: notification -> 202, no body")
    st, _, m = _http(url, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, token=tok, pv=pv)
    tools = m[0]["result"]["tools"] if m and "result" in m[0] else []
    check([t["name"] for t in tools] == ["unsaid_places"], "http: tools/list -> unsaid_places")
    t0 = time.monotonic()
    st, ct, m = _http(url, {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
        "name": "unsaid_places", "arguments": CEDRIC_PAIRS, "_meta": {"progressToken": "p1"}}}, token=tok, pv=pv)
    final = [x for x in m if x.get("id") == 3]
    prog = [x for x in m if x.get("method") == "notifications/progress"]
    res = final[0]["result"] if final and "result" in final[0] else {}
    sc = res.get("structuredContent") or {}
    check("text/event-stream" in ct and len(final) == 1, "http: tools/call -> SSE, one response event (%d progress, "
          "%.0f s)" % (len(prog), time.monotonic() - t0))
    if sc.get("status") in ("limited", "degraded", "queued", "waking") or res.get("isError"):
        print("  [SKIP] the engine is busy or rate-limited: %s" % (res.get("content") or [{}])[0].get("text", "")[:160])
    else:
        errs = validate(sc, tools[0]["outputSchema"]) if tools else ["no tools"]
        check(not errs, "http: structuredContent validates against outputSchema" + ("" if not errs else ": %s" % errs[:3]))
        check(sc.get("status") in ("ok", "partial", "empty_few") and 1 <= len(sc.get("picks", [])) <= 7 and
              all(p["ai_named"] == 0 for p in sc["picks"]),
              "http: %s, %d picks, each named by 0 of %s AI answers" % (sc.get("status"), len(sc.get("picks", [])),
                                                                       sc.get("wall", {}).get("answers")))
        show_call({"result": res}, "tools/call unsaid_places (Streamable HTTP) -> content[0]")
    st, ct, m = _http(url, {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {
        "name": "unsaid_places", "arguments": CEDRIC_PAIRS}}, token=tok, pv=pv, accept="application/json")
    check(st == 200 and "application/json" in ct and m and m[0].get("id") == 4 and "result" in m[0],
          "http: tools/call with Accept: application/json -> one JSON response (cached: %s)"
          % ((m[0]["result"].get("structuredContent") or {}).get("host", {}).get("cached") if m and "result" in m[0] else None))
    st, _, m = _http(url, {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {
        "name": "unsaid_places", "arguments": {"loves": [["Al Green", "artist"]], "city": "Chicago, IL"}}},
        token=tok, pv=pv, accept="application/json")
    check(m and m[0]["result"].get("isError") is True, "http: unsupported city -> isError: %s"
          % (m[0]["result"]["content"][0]["text"][:90] if m and "result" in m[0] else m))
    st, _, m = _http(url, {"jsonrpc": "2.0", "id": 6, "method": "nope"}, token=tok, pv=pv)
    check(m and m[0].get("error", {}).get("code") == -32601, "http: unknown method -> -32601")
    st, _, _ = _http(url, method="GET", token=tok)
    check(st == 405, "http: GET -> 405 (no server stream)")
    st, _, m = _http(url, {"jsonrpc": "2.0", "id": 7, "method": "ping"}, token=tok, pv="1900-01-01")
    check(st == 400, "http: unknown MCP-Protocol-Version -> 400")
    if tok:
        st, _, _ = _http(url, {"jsonrpc": "2.0", "id": 8, "method": "ping"}, token="wrong")
        check(st == 401, "http: wrong token -> 401")
        sep = "&" if "?" in url else "?"
        st, _, m = _http(url + sep + "token=" + tok, {"jsonrpc": "2.0", "id": 9, "method": "ping"})
        check(st == 200 and m and m[0].get("result") == {}, "http: ?token= in the URL works (the connector form)")


if __name__ == "__main__":
    if "--http" in sys.argv:                  # only the Streamable HTTP endpoint
        run_http(sys.argv[sys.argv.index("--http") + 1])
        print("\n%d failed checks" % len(FAILS))
        sys.exit(1 if FAILS else 0)
    t0 = time.time()
    err = run_legacy()
    run_modern()
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "transcript.jsonl"), "w") as f:
        for rec in LOG:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    if "--no-remote" not in sys.argv:
        run_remote()
    if "--record" in sys.argv:
        record(sys.argv[sys.argv.index("--record") + 1])
    print("\nserver stderr (first lines): %s" % " | ".join(err.strip().splitlines()[:2]))
    print("%d fake-mode messages, %.1f s, %d failed checks; wire log: out/transcript.jsonl"
          % (len(LOG), time.time() - t0, len(FAILS)))
    sys.exit(1 if FAILS else 0)
