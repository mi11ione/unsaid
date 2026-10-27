"""Local preview: serves unsaid/site/ as static files and passes /api/* through to the engine server, the way the
Pages Function does in production (streaming, headers kept). Standard library only.

    python3 -I server/app.py                          # Agent A's server, fake mode, 127.0.0.1:8710
    python3 -I media/tools/devserver.py [port]        # then open http://127.0.0.1:8080/  (?token=… if one is set)

With no server on 8710, /api/* answers 404 and the page falls back to its MOCK data, marked as such."""
import http.server
import os
import sys
import urllib.error
import urllib.request

SITE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'site')
API = os.environ.get('UNSAID_API', 'http://127.0.0.1:8710')


class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=SITE, **k)

    def log_message(self, fmt, *args):  # path only: the query can carry loves and a token
        sys.stderr.write('%s %s\n' % (self.command, self.path.split('?')[0]))

    def do_GET(self):
        if not self.path.startswith('/api/'):
            if self.path.split('?')[0] == '/agents':
                self.path = '/agents.html'
            return super().do_GET()
        req = urllib.request.Request(API + self.path, headers={k: v for k, v in self.headers.items() if k.lower() in ('authorization', 'x-unsaid-token', 'accept')})
        try:
            r = urllib.request.urlopen(req, timeout=120)
        except urllib.error.HTTPError as e:
            r = e
        except Exception:
            self.send_response(404)
            self.send_header('content-type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"status":"no engine on ' + API.encode() + b'"}')
            return
        self.send_response(r.status if hasattr(r, 'status') else r.code)
        for k, v in r.headers.items():
            if k.lower() in ('content-type', 'retry-after', 'cache-control', 'www-authenticate'):
                self.send_header(k, v)
        self.end_headers()
        while True:
            chunk = r.read1(65536) if hasattr(r, 'read1') else r.read(65536)
            if not chunk:
                break
            self.wfile.write(chunk)
            self.wfile.flush()


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    http.server.ThreadingHTTPServer.daemon_threads = True
    print('UNSAID preview on http://127.0.0.1:%d/  (api -> %s)' % (port, API))
    http.server.ThreadingHTTPServer(('127.0.0.1', port), H).serve_forever()
