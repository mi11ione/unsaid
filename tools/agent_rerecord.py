#!/usr/bin/env python3
"""Re-record the live agent runs against the deployed engine (freeze.sh step 7, before the video renders).

  python3 -I tools/agent_rerecord.py              # both runs
  python3 -I tools/agent_rerecord.py --no-claude  # only the scripted MCP session
  python3 -I tools/agent_rerecord.py --check      # no recording: what the current files say

1. The scripted MCP session (Agent E's recorder, agent/test_client.py --no-remote --record): agent/demo/
   live_transcript.jsonl, which the video's agent shot shows.
2. The Claude run the site's "Use it from Claude" block shows (site/data/live/agent_demo.json): the same `claude -p`
   command E recorded (its "command" field), with a temporary MCP config pointing at this checkout; the stream goes
   to agent/demo/claude_p_live.jsonl (gitignored), the summary to agent_demo.json.
Before (2) overwrites agent_demo.json, the recording that holds the approved ⟦AGENT_QUOTE⟧ is kept once at
~/Desktop/qloo/private/agent_quote_source.json (a new answer words things differently; the quote stays verbatim to its
own recording). Both runs are one hosted query each (the host caches a repeat; a cold host spends ~45 Qloo calls).
UNSAID_TOKEN comes from the env or ~/.config/unsaid/env and is never printed or written.
Exit 0 when the recordings succeed (or with --check); prints WARN lines when The Spot Sports Bar is not in the new run."""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import freeze_numbers as FN  # noqa: E402

DEMO = FN.AGENT_DEMO
STREAM = os.path.join(ROOT, "agent", "demo", "claude_p_live.jsonl")
API = os.environ.get("UNSAID_URL") or "https://unsaid-ang.pages.dev"


def env_with_token():
    env = dict(os.environ)
    if not env.get("UNSAID_TOKEN"):
        p = os.path.expanduser("~/.config/unsaid/env")
        for line in open(p) if os.path.exists(p) else []:
            if line.startswith("UNSAID_TOKEN="):
                env["UNSAID_TOKEN"] = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not env.get("UNSAID_TOKEN"):
        sys.exit("UNSAID_TOKEN not set and not in ~/.config/unsaid/env")
    return env


def keep_quote_source():
    if os.path.exists(FN.QUOTE_SRC) or not os.path.exists(DEMO):
        return
    d = json.load(open(DEMO))
    if FN.QUOTE in (d.get("answer") or ""):
        os.makedirs(os.path.dirname(FN.QUOTE_SRC), exist_ok=True)
        json.dump(d, open(FN.QUOTE_SRC, "w"), indent=1, ensure_ascii=False)
        print("kept the approved quote's recording (%s) -> %s" % (d.get("recorded_at"), FN.QUOTE_SRC))


def host():
    h = {}
    try:
        with urllib.request.urlopen(urllib.request.Request(API + "/api/health", headers={"User-Agent": "unsaid-freeze/1.0"}),
                                    timeout=90) as r:
            h["engine_v"] = json.loads(r.read().decode()).get("engine_v")
    except Exception as e:  # noqa: BLE001
        h["engine_v"] = "unknown (%s)" % type(e).__name__
    try:
        import render_deploy as RD
        d = RD.live_deploy()
        h["render_deploy"] = ((d or {}).get("commit") or {}).get("id", "")[:7]
    except Exception as e:  # noqa: BLE001
        h["render_deploy"] = "unknown (%s)" % type(e).__name__
    return h


def record_mcp(env):
    p = subprocess.run([sys.executable, "-I", "test_client.py", "--no-remote", "--record", "demo/live_transcript.jsonl"],
                       cwd=os.path.join(ROOT, "agent"), env=env, capture_output=True, text=True, timeout=600)
    tail = [l for l in p.stdout.splitlines() if l.startswith("== recorded") or "failed checks" in l]
    print("MCP session: %s" % ("; ".join(tail) or p.stderr.strip()[-300:]))
    return p.returncode == 0


def record_claude(env):
    old = json.load(open(DEMO)) if os.path.exists(DEMO) else {}
    question = old.get("question") or ("I love Frankie Beverly & Maze, The Original Kings of Comedy and rib tips. "
                                       "Where should I go in St. Louis tonight?")
    cfg = {"mcpServers": {"unsaid": {"type": "stdio", "command": "python3",
                                     "args": ["-I", os.path.join(ROOT, "agent", "unsaid_mcp.py")],
                                     "env": {"UNSAID_MODE": "remote", "UNSAID_URL": API, "UNSAID_TOKEN": "${UNSAID_TOKEN}"}}}}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(cfg, f)
        cfg_path = f.name
    shown = ('claude -p "%s" --mcp-config agent/mcp.json --strict-mcp-config --allowedTools mcp__unsaid__unsaid_places '
             '--output-format stream-json --verbose' % question)
    t0 = time.time()
    try:
        p = subprocess.run(["claude", "-p", question, "--mcp-config", cfg_path, "--strict-mcp-config",
                            "--allowedTools", "mcp__unsaid__unsaid_places", "--output-format", "stream-json", "--verbose"],
                           cwd=ROOT, env=env, capture_output=True, text=True, timeout=900)
    finally:
        os.unlink(cfg_path)
    rows = []
    for line in p.stdout.splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            pass
    init = next((r for r in rows if r.get("type") == "system" and r.get("subtype") == "init"), {})
    res = next((r for r in rows if r.get("type") == "result"), {})
    use = next((c for r in rows if r.get("type") == "assistant" for c in r["message"]["content"]
                if isinstance(c, dict) and c.get("type") == "tool_use" and c["name"].endswith("unsaid_places")), None)
    if p.returncode or not res.get("result") or not use:
        print("WARN Claude run failed (rc %s, tool call %s): %s" % (p.returncode, bool(use), (p.stderr or "")[-300:]))
        return False
    h = host()
    tok = env["UNSAID_TOKEN"]
    with open(STREAM, "w") as f:
        f.write(json.dumps({"kind": "session", "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "command": shown,
                            "host": h}) + "\n")
        for line in p.stdout.splitlines():
            f.write(line.replace(tok, "<redacted>") + "\n")
    ver = subprocess.run(["claude", "--version"], capture_output=True, text=True).stdout.split()
    doc = {"recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "question": question, "command": shown,
           "claude_code": ver[0] if ver else None, "model": init.get("model"), "mode": "remote", "api": API, "host": h,
           "tool": "unsaid_places", "input": use.get("input"), "answer": res.get("result"),
           "turns": res.get("num_turns"), "duration_ms": res.get("duration_ms") or int((time.time() - t0) * 1000)}
    json.dump(doc, open(DEMO, "w"), indent=1, ensure_ascii=False)
    print("Claude run: %d turns, %.0f s, host %s -> %s" % (doc["turns"] or 0, time.time() - t0, h, DEMO))
    return True


def check():
    tp, when = FN.transcript_picks(FN.TRANSCRIPT) if os.path.exists(FN.TRANSCRIPT) else ([], None)
    print("MCP transcript (%s): %s" % (when, "; ".join(tp) or "no picks"))
    if FN.QUOTE_CARD not in tp:
        print("!" * 100)
        print("!!! WARN: %s is NOT in the recorded agent run: ⟦AGENT_QUOTE⟧ gets deleted from devpost.final.md; "
              "Roman decides" % FN.QUOTE_CARD)
        print("!" * 100)
    d = json.load(open(DEMO)) if os.path.exists(DEMO) else {}
    print("agent_demo.json (%s): The Spot %s in the answer" % (d.get("recorded_at"),
                                                            "named" if FN.QUOTE_CARD in (d.get("answer") or "") else "NOT named"))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-claude", action="store_true")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    if a.check:
        check()
        return 0
    env = env_with_token()
    keep_quote_source()
    ok = record_mcp(env)
    if not a.no_claude:
        ok = record_claude(env) and ok
    check()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
