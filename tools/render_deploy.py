#!/usr/bin/env python3
"""Render (engine host) for the freeze: compare, push the priors, redeploy, wait for live + /api/health.

  python3 -I tools/render_deploy.py status                 # deployed commit vs HEAD (engine/server/data paths), priors
  python3 -I tools/render_deploy.py deploy                 # push priors if they differ, deploy origin/main, wait
  python3 -I tools/render_deploy.py deploy --if-unchanged  # the dry run: deploy only when nothing changed since the
                                                           # live deploy (engine, server, data, priors); else SKIPPED
RENDER_API_KEY comes from the environment or ~/.config/unsaid/env and is never printed. Exit 0 on success or a skip,
1 on a failed deploy or health check."""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVICE = os.environ.get("RENDER_SERVICE", "srv-dbgr3fuc6qcc73ce5p3g")
API = "https://api.render.com/v1/services/" + SERVICE
HEALTH = os.environ.get("UNSAID_HEALTH", "https://unsaid-ang.pages.dev/api/health")
PATHS = ["engine/unsaid", "server", "data", "render.yaml"]      # what the engine host runs or reads


def key():
    k = os.environ.get("RENDER_API_KEY")
    if not k:
        p = os.path.expanduser("~/.config/unsaid/env")
        for line in open(p) if os.path.exists(p) else []:
            if line.startswith("RENDER_API_KEY="):
                k = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not k:
        sys.exit("RENDER_API_KEY not set and not in ~/.config/unsaid/env")
    return k


def call(method, path="", body=None):
    req = urllib.request.Request(API + path, method=method, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Authorization": "Bearer " + key(), "Accept": "application/json",
                                          "Content-Type": "application/json", "User-Agent": "Mozilla/5.0 (compatible)"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode() or "null")


def git(*a):
    return subprocess.run(["git", "-C", ROOT] + list(a), capture_output=True, text=True).stdout.strip()


def live_deploy():
    for x in call("GET", "/deploys?limit=10"):
        d = x.get("deploy", x)
        if d.get("status") == "live":
            return d
    return None


def priors_differ():
    have = {}
    for x in call("GET", "/secret-files") or []:
        f = x.get("secretFile", x)
        have[f["name"]] = f.get("content", "")
    pd = os.path.join(ROOT, "data", "priors")
    diff = []
    for n in sorted(os.listdir(pd)):
        if n.endswith(".json") and open(os.path.join(pd, n)).read() != have.get(n):
            diff.append(n)
    return diff


def status():
    d = live_deploy()
    dep = (d.get("commit") or {}).get("id", "") if d else ""
    git("fetch", "-q", "origin")
    head = git("rev-parse", "origin/main")
    changed = git("diff", "--name-only", dep, head, "--", *PATHS).splitlines() if dep else ["(no live deploy)"]
    pri = priors_differ()
    print("render: live deploy %s at %s (%s); origin/main %s; changed since: %d files%s; priors differ: %s" % (
        d.get("id") if d else "-", dep[:7], d.get("finishedAt") if d else "-", head[:7], len(changed),
        (" (" + ", ".join(changed[:8]) + (" ..." if len(changed) > 8 else "") + ")") if changed else "",
        ", ".join(pri) or "none"))
    return d, dep, head, changed, pri


def health(timeout_s):
    t0 = time.time()
    last = None
    while time.time() - t0 < timeout_s:
        try:
            req = urllib.request.Request(HEALTH, headers={"User-Agent": "unsaid-freeze/1.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                h = json.loads(r.read().decode())
            last = h
            if h.get("ok") and h.get("mode") == "live" and all((h.get("priors") or {}).get(c) for c in ("stl", "nyc")):
                return h
        except (urllib.error.URLError, ValueError, OSError) as e:
            last = str(e)[:120]
        time.sleep(10)
    print("health not ok after %d s: %s" % (timeout_s, last))
    return None


def deploy(if_unchanged, timeout_s):
    d, dep, head, changed, pri = status()
    if if_unchanged and (changed or pri):
        print("render: SKIPPED (--if-unchanged: %d changed files since %s%s); the live engine stays at %s" % (
            len(changed), dep[:7], ", priors differ" if pri else "", dep[:7]))
        return 0
    if git("rev-parse", "HEAD") != head:
        print("WARN: local HEAD %s is not origin/main %s; Render deploys origin/main" % (git("rev-parse", "--short", "HEAD"), head[:7]))
    if pri:
        out = subprocess.run([sys.executable, "-I", os.path.join(ROOT, "server", "push_priors.py")],
                             env=dict(os.environ, RENDER_API_KEY=key()), capture_output=True, text=True)
        print(out.stdout.strip() or out.stderr.strip()[-300:])
        if out.returncode:
            return 1
    nd = call("POST", "/deploys", {"clearCache": "do_not_clear"})
    nd = nd.get("deploy", nd)
    print("render: deploy %s started (%s)" % (nd.get("id"), (nd.get("commit") or {}).get("id", "")[:7]))
    t0 = time.time()
    st = None
    while time.time() - t0 < timeout_s:
        time.sleep(15)
        x = call("GET", "/deploys/" + nd["id"])
        x = x.get("deploy", x)
        st = x.get("status")
        if st == "live":
            break
        if st in ("build_failed", "update_failed", "canceled", "deactivated", "pre_deploy_failed"):
            print("render: deploy %s %s" % (nd["id"], st))
            return 1
    if st != "live":
        print("render: deploy %s not live after %d s (%s)" % (nd["id"], timeout_s, st))
        return 1
    commit = (x.get("commit") or {}).get("id", "")
    h = health(600)
    if not h:
        return 1
    print("render: live at %s in %d s; /api/health ok, mode %s, engine %s, priors %s" % (
        commit[:7], time.time() - t0, h.get("mode"), h.get("engine_v"), h.get("priors")))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["status", "deploy"])
    ap.add_argument("--if-unchanged", action="store_true")
    ap.add_argument("--timeout", type=int, default=1200)
    a = ap.parse_args()
    if a.cmd == "status":
        status()
        return 0
    return deploy(a.if_unchanged, a.timeout)


if __name__ == "__main__":
    sys.exit(main())
