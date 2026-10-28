"""A localhost forwarder for the post-hoc meter arm: adds the X-Unsaid-Bench header (the engine's per-IP-limit bypass,
passed through by the Pages proxy) to every request agent/unsaid_mcp.py makes in remote mode, so the arm needn't pace
at 3 fresh sets an hour. agent/ is not edited: the MCP server just gets UNSAID_URL=http://127.0.0.1:<port>.

The secret comes from UNSAID_BENCH_SECRET (else PROXY_SECRET) in this process's env only; it is never logged, never
written, and never reaches the agent. Responses stream through unchanged (NDJSON).

  UNSAID_BENCH_SECRET=... python3 -I bench_proxy.py [port]      # default 8799, upstream https://unsaid-ang.pages.dev
"""
import os, sys, urllib.error, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM = (os.environ.get("UNSAID_UPSTREAM") or "https://unsaid-ang.pages.dev").rstrip("/")
SECRET = (os.environ.get("UNSAID_BENCH_SECRET") or os.environ.get("PROXY_SECRET") or "").strip()
PASS = ("Authorization", "Accept", "User-Agent", "X-Unsaid-Token")


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        if not self.path.startswith("/api/"):
            self.send_error(404)
            return
        headers = {k: self.headers[k] for k in PASS if self.headers.get(k)}
        if SECRET:
            headers["X-Unsaid-Bench"] = SECRET
        req = urllib.request.Request(UPSTREAM + self.path, headers=headers)
        try:
            up = urllib.request.urlopen(req, timeout=180)
            code = up.status
        except urllib.error.HTTPError as e:
            up, code = e, e.code
        except Exception as e:
            self.send_error(502, "upstream: %s" % type(e).__name__)
            return
        self.send_response(code)
        for k in ("Content-Type", "Cache-Control", "Retry-After", "X-Unsaid-State", "WWW-Authenticate"):
            if up.headers.get(k):
                self.send_header(k, up.headers[k])
        self.end_headers()
        while True:  # HTTP/1.0, close-delimited: stream chunks as they arrive
            chunk = up.read1(65536) if hasattr(up, "read1") else up.read(65536)
            if not chunk:
                break
            self.wfile.write(chunk)
            self.wfile.flush()

    def log_message(self, fmt, *a):  # path and code only; headers (the secret) are never printed
        sys.stderr.write("[bench_proxy] %s %s\n" % (self.command, (a[1] if len(a) > 1 else "")))


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 0  # 0: a free port chosen by the OS
    if not SECRET:
        sys.exit("needs UNSAID_BENCH_SECRET (or PROXY_SECRET) in the env")
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    pf = os.environ.get("BENCH_PROXY_PORTFILE")
    if pf:
        with open(pf, "w") as f:
            f.write(str(srv.server_address[1]))
    srv.serve_forever()
