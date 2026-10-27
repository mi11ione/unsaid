#!/usr/bin/env python3
"""Minimal MCP stdio client: spawns unsaid_mcp.py and drives it like a host would. Standard library only.
  python3 -I test_client.py            -> prints the transcript, writes transcript.jsonl, exits 1 on any failed check
Runs both eras: legacy (initialize -> notifications/initialized -> tools/list -> tools/call) and modern 2026-07-28
(server/discover -> tools/list -> tools/call, per-request _meta), plus error paths. Validates structuredContent
against the tool's outputSchema with a small JSON-Schema subset validator."""
import ast
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = [sys.executable, "-I", os.path.join(HERE, "unsaid_mcp.py")]
LOG = []
FAILS = []


class Client:
    def __init__(self):
        self.p = subprocess.Popen(SERVER, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  universal_newlines=True, bufsize=1)
        self.n = 0

    def _w(self, obj):
        line = json.dumps(obj)
        LOG.append({"dir": ">>", "msg": obj})
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
        LOG.append({"dir": "<<", "msg": msg, "ms": int((time.monotonic() - t0) * 1000)})
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


if __name__ == "__main__":
    t0 = time.time()
    err = run_legacy()
    run_modern()
    with open(os.path.join(HERE, "transcript.jsonl"), "w") as f:
        for rec in LOG:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print("\nserver stderr (first lines): %s" % " | ".join(err.strip().splitlines()[:2]))
    print("%d messages, %.1f s, %d failed checks; full wire log: transcript.jsonl" % (len(LOG), time.time() - t0, len(FAILS)))
    sys.exit(1 if FAILS else 0)
