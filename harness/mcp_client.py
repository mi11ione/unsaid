"""A minimal stdio MCP client (newline-delimited JSON-RPC, legacy `initialize` handshake). The meter uses it to check
that the qloo_places tool exists before any "with" ask, and to run Gemini's function calls against the same server
that Claude and Codex reach through their own MCP configs."""
import json, subprocess


class Stdio:
    def __init__(self, command, args, env=None, timeout=60):
        self.p = subprocess.Popen([command] + list(args), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, text=True, env=env, bufsize=1)
        self.n = 0
        self.call("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                 "clientInfo": {"name": "unsaid-harness", "version": "0.1"}})
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def _send(self, msg):
        self.p.stdin.write(json.dumps(msg) + "\n")
        self.p.stdin.flush()

    def call(self, method, params):
        self.n += 1
        self._send({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params})
        while True:
            line = self.p.stdout.readline()
            if not line:
                raise RuntimeError("MCP server closed its stdout during %s" % method)
            try:
                m = json.loads(line)
            except ValueError:
                continue
            if m.get("id") == self.n:
                if "error" in m:
                    raise RuntimeError("MCP %s error: %s" % (method, m["error"]))
                return m.get("result") or {}

    def tools(self):
        return self.call("tools/list", {}).get("tools", [])

    def call_tool(self, name, args):
        r = self.call("tools/call", {"name": name, "arguments": args})
        if r.get("structuredContent") is not None:
            return {"result": r["structuredContent"]}
        return {"result": "".join(c.get("text", "") for c in r.get("content", []) if c.get("type") == "text")}

    def close(self):
        try:
            self.p.stdin.close()
            self.p.terminate()
            self.p.wait(timeout=5)
        except Exception:
            pass
