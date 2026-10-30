"""The hosted MCP endpoint: POST /mcp, MCP Streamable HTTP, standard library only.

One paste for an agent: add https://unsaid-ang.pages.dev/mcp as a custom connector (Claude: Settings -> Connectors) or
`claude mcp add --transport http unsaid <url>`. No token is needed: it is open, under the same per-IP limits as
/api/unsaid (an optional UNSAID token, as `?token=` or `Authorization: Bearer`, gets its own bucket).

Transport (MCP Streamable HTTP, protocol 2025-11-25, also 2025-06-18 / 2025-03-26 and the stateless 2026-07-28):
  POST /mcp     one JSON-RPC message per request. A request gets application/json, or for tools/call, when the client
                accepts text/event-stream, an SSE stream (keep-alive comments and progress while Qloo ranks, then the
                one response event). A notification or a response gets 202 with no body. No session id is issued:
                the server is stateless, so every request stands alone.
  GET  /mcp     405: this server opens no server-to-client stream.
  DELETE /mcp   405: there is no session to end.
Tools: unsaid_places only, with the exact schema of agent/unsaid_mcp.py (loaded from there). A call runs through the
same path as GET /api/unsaid (app.stream_unsaid: result cache, per-IP fresh-run limit, admission queue, Qloo quota
guard, the Gemini lane), and the result is shaped by the stdio server's own converter, so both transports return
the same structuredContent.
"""
import importlib.util
import json
import os
import sys
import threading
import time
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
AGENT = os.path.join(os.path.dirname(HERE), "agent", "unsaid_mcp.py")
MAX_BODY = 64 * 1024
KEEPALIVE_S = 10.0
ORIGINS = {o.strip() for o in (os.environ.get("UNSAID_MCP_ORIGINS") or
                               "https://unsaid-ang.pages.dev,https://claude.ai,https://claude.com").split(",") if o.strip()}


def _load_agent():
    """agent/unsaid_mcp.py in remote mode: its schema, JSON-RPC dispatch and result converter, none of its kit."""
    saved = os.environ.get("UNSAID_MODE")
    os.environ["UNSAID_MODE"] = "remote"
    try:
        spec = importlib.util.spec_from_file_location("unsaid_mcp_agent", AGENT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        if saved is None:
            os.environ.pop("UNSAID_MODE", None)
        else:
            os.environ["UNSAID_MODE"] = saved
    return mod


UM = _load_agent()
TOOLS = [UM.TOOL]
VERSIONS = UM.MODERN + UM.LEGACY


# ---------------------------------------------------------------- HTTP helpers
def _send(h, code, body=None, ctype="application/json; charset=utf-8", extra=None):
    data = b"" if body is None else (body if isinstance(body, bytes) else
                                     json.dumps(body, ensure_ascii=False, default=str).encode("utf-8"))
    h.send_response(code)
    if body is not None:
        h.send_header("Content-Type", ctype)
    h.send_header("Content-Length", str(len(data)))
    h.send_header("Cache-Control", "no-store")
    h.send_header("X-Unsaid-State", "warm")
    for k, v in (extra or {}).items():
        h.send_header(k, v)
    h.end_headers()
    if data and h.command != "HEAD":
        h.wfile.write(data)
    h._log(code)


def _rpc_error(id_, code, message, data=None):
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": id_, "error": err}


def not_allowed(h):
    _send(h, 405, _rpc_error(None, -32000, "Method not allowed: POST JSON-RPC messages to /mcp"), extra={"Allow": "POST"})


def _origin_ok(h):
    o = h.headers.get("Origin")
    return not o or o in ORIGINS


# ---------------------------------------------------------------- the tool
def _tool_text(text):
    return {"content": [{"type": "text", "text": text}], "isError": True}


def _make_call(h, app, progress):
    """tools/call -> CallToolResult, through app.stream_unsaid (the /api/unsaid path, limits and cache included)."""

    def call(params):
        if params.get("name") != "unsaid_places":
            raise UM.RpcError(-32602, "Unknown tool: %s" % params.get("name"))
        try:
            loves, city = UM._check_args(params.get("arguments") or {})
        except ValueError as e:
            return _tool_text("Invalid input: %s" % e)
        spec = UM._parse_loves(loves)
        ctext = UM._city_text(city)
        if app.adapter.city_key(ctext)[0] is None:
            return _tool_text("unsaid_places failed: %s" % app.adapter.CITY_NOT_COVERED)
        try:
            parsed = app.parse_loves([json.dumps([UM._remote_love(t, x) for t, x in spec], ensure_ascii=False)])
        except ValueError as e:
            return _tool_text("Invalid input: %s" % e)
        box = {"result": None, "events": 0}

        def emit(evt):
            box["events"] += 1
            if evt.get("type") == "done":
                box["result"] = evt.get("result")
            elif evt.get("type") == "calls":
                progress(evt.get("done"), evt.get("total"), "Qloo is ranking: %s of %s calls" % (
                    evt.get("done"), evt.get("total")))
        with app.STREAMS_LOCK:
            app.STREAMS["open"] += 1
        try:
            app.stream_unsaid(ctext, parsed, h.client_ip(), h.country(), emit, bench=h.bench())
        finally:
            with app.STREAMS_LOCK:
                app.STREAMS["open"] -= 1
        r = box["result"]
        if not r:
            return _tool_text("unsaid_places failed: the engine returned no result; try again in a minute")
        host = {"url": "/mcp", "mode": app.MODE, "cached": bool(r.get("cached")), "stored_at": r.get("stored_at"),
                "key": r.get("key"), "events": box["events"]}
        out = UM.from_contract(r, "remote", spec, city, None, host)
        if not out["picks"] and out["status"] in ("limited", "degraded", "queued", "waking", "error"):
            return _tool_text("unsaid_places: %s" % UM.summary(out))
        return {"content": [{"type": "text", "text": UM.summary(out)},
                            {"type": "text", "text": json.dumps(out, ensure_ascii=False, default=str)}],
                "structuredContent": out, "isError": False}
    return call


# ---------------------------------------------------------------- POST /mcp
def post(h, app):
    qs = urllib.parse.parse_qs(urllib.parse.urlsplit(h.path).query)
    if not _origin_ok(h):
        return _send(h, 403, _rpc_error(None, -32000, "Origin not allowed"))
    if not h.authorized(qs):
        return _send(h, 401, _rpc_error(None, -32001, "Unauthorized: this endpoint needs the UNSAID token "
                                                      "(?token=... in the URL, or Authorization: Bearer ...)"),
                     extra={"WWW-Authenticate": "Bearer"})
    pv = h.headers.get("MCP-Protocol-Version")
    if pv and pv not in VERSIONS:
        return _send(h, 400, _rpc_error(None, -32022, "Unsupported MCP-Protocol-Version: %s" % pv,
                                        {"supported": VERSIONS}))
    try:
        n = int(h.headers.get("Content-Length") or 0)
    except ValueError:
        n = -1
    if not 0 < n <= MAX_BODY:
        return _send(h, 413 if n > MAX_BODY else 400, _rpc_error(None, -32600, "Invalid Request: one JSON-RPC "
                                                                              "message, at most 64 KB"))
    try:
        msg = json.loads(h.rfile.read(n).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return _send(h, 400, _rpc_error(None, -32700, "Parse error"))
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
        return _send(h, 400, _rpc_error(None, -32600, "Invalid Request (one JSON-RPC 2.0 object; batches are not "
                                                      "supported)"))
    if "method" not in msg or "id" not in msg:        # a notification or a response: accepted, nothing to say
        return _send(h, 202)
    rid, method = msg["id"], msg.get("method")
    sse = method == "tools/call" and "text/event-stream" in (h.headers.get("Accept") or "")
    if not sse:
        progress = lambda *a: None  # noqa: E731
        try:
            out = {"jsonrpc": "2.0", "id": rid, "result": UM.handle(msg, {}, TOOLS, _make_call(h, app, progress))}
        except UM.RpcError as e:
            out = _rpc_error(rid, e.code, e.message, e.data)
        except Exception as e:
            print("[mcp] %s: %s" % (type(e).__name__, e), file=sys.stderr)
            out = _rpc_error(rid, -32603, "Internal error")
        return _send(h, 200, out)
    return _post_sse(h, app, msg)


def _post_sse(h, app, msg):
    """tools/call as an SSE stream: headers now, keep-alives and progress while the run goes, then the response."""
    rid = msg["id"]
    token = ((msg.get("params") or {}).get("_meta") or {}).get("progressToken")
    lock, gone = threading.Lock(), {"v": False}
    h.send_response(200)
    h.send_header("Content-Type", "text/event-stream")
    h.send_header("Cache-Control", "no-store")
    h.send_header("X-Accel-Buffering", "no")
    h.send_header("X-Unsaid-State", "warm")
    h.end_headers()

    def write(text):
        if gone["v"]:
            return
        with lock:
            try:
                h.wfile.write(text.encode("utf-8"))
                h.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                gone["v"] = True          # the client left; the run still finishes and is cached under its key

    def event(obj):
        write("event: message\ndata: %s\n\n" % json.dumps(obj, ensure_ascii=False, default=str))

    last = {"t": 0.0}

    def progress(done, total, text):
        if token is None or time.monotonic() - last["t"] < 1.0:
            return
        last["t"] = time.monotonic()
        event({"jsonrpc": "2.0", "method": "notifications/progress",
               "params": {"progressToken": token, "progress": done or 0, "total": total, "message": text}})

    box = {}

    def run():
        try:
            box["out"] = {"jsonrpc": "2.0", "id": rid,
                          "result": UM.handle(msg, {}, TOOLS, _make_call(h, app, progress))}
        except UM.RpcError as e:
            box["out"] = _rpc_error(rid, e.code, e.message, e.data)
        except Exception as e:
            print("[mcp] %s: %s" % (type(e).__name__, e), file=sys.stderr)
            box["out"] = _rpc_error(rid, -32603, "Internal error")
    t = threading.Thread(target=run, name="mcp-call", daemon=True)
    t.start()
    write(": unsaid is crossing out\n\n")
    while t.is_alive():
        t.join(KEEPALIVE_S)
        if t.is_alive():
            write(": keep-alive\n\n")
    event(box["out"])
    h._log(200)
