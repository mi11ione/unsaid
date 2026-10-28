#!/usr/bin/env python3
"""Upload the 'fits everyone' priors (data/priors/*.json) and the card lines (data/lines/<city>.json, as
lines-<city>.json), both Qloo-derived and gitignored, to Render as secret files.

  set -a; . ~/.config/unsaid/env; set +a; python3 -I server/push_priors.py
Render mounts each at /etc/secrets/<name>; the service's UNSAID_PRIORS_DIR=/etc/secrets points the engine there.
Existing secret files are kept (the API replaces the whole set, so this merges). Nothing is printed but names and sizes.
A redeploy (or restart) picks the new files up."""
import glob
import json
import os
import sys
import urllib.request

SERVICE = os.environ.get("RENDER_SERVICE", "srv-dbgr3fuc6qcc73ce5p3g")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = "https://api.render.com/v1/services/%s/secret-files" % SERVICE


def call(method, body=None):
    req = urllib.request.Request(API, method=method, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Authorization": "Bearer " + os.environ["RENDER_API_KEY"],
                                          "Accept": "application/json", "Content-Type": "application/json",
                                          "User-Agent": "Mozilla/5.0 (compatible)"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.status, json.loads(r.read().decode() or "null")


def main():
    files = sorted(glob.glob(os.path.join(ROOT, "data", "priors", "*.json")))
    if not files:
        sys.exit("no data/priors/*.json here")
    _, have = call("GET")
    keep = {}
    for x in have or []:
        f = x.get("secretFile", x)
        keep[f["name"]] = f.get("content", "")
    for p in files:
        with open(p) as fh:
            keep[os.path.basename(p)] = fh.read()
    for p in sorted(glob.glob(os.path.join(ROOT, "data", "lines", "*.json"))):   # card lines -> lines-<city>.json
        with open(p) as fh:
            keep["lines-" + os.path.basename(p)] = fh.read()
    status, _ = call("PUT", [{"name": n, "content": c} for n, c in sorted(keep.items())])
    print("PUT secret-files -> HTTP %s: %s" % (status, ", ".join("%s (%d KB)" % (n, len(c) // 1024)
                                                                 for n, c in sorted(keep.items()))))


if __name__ == "__main__":
    main()
