"""The grounding meter runner (UNSAID.md §4 gate D; k10_meter.py scores it). Same sentence, two arms, three lanes:
  alone  the assistant with no tools
  with   the assistant with exactly one tool, qloo_places (Qloo's top 50 for the loves, nothing removed), served by
         agent/unsaid_mcp.py over stdio. Never unsaid_places, which would make the arm true by construction.
Each answer is 12 picks; k10_meter.py counts how many sit on the OTHER assistants' everyone-list.

  python3 -I meter.py                               # checks: phrasings, the tool, each lane; prints the ask count
  python3 -I meter.py --lane all --go               # 10 STL sets x 2 phrasings x 2 arms x 2 reps x 3 lanes = 240
  python3 -I meter.py --lane claude --arm alone --go

The "with" arm needs the server to list qloo_places and UNSAID_MODE=live with QLOO_API_KEY in the env (--allow-fake
records fake-mode answers flagged "fake", for plumbing tests only). Writes runs/meter.jsonl (resumable).
Instruments per lane, both arms identical but for the tool:
  claude  claude -p ... --output-format stream-json --verbose --model sonnet --tools "" --setting-sources local
          --disable-slash-commands --strict-mcp-config --no-session-persistence --system-prompt <consumer line>
          [+ --mcp-config runs/.meter.mcp.json --allowedTools mcp__unsaid__qloo_places --disallowedTools mcp__unsaid__unsaid_places]
          (no --safe-mode: it drops --mcp-config servers)
  codex   the walls line [+ -c mcp_servers.unsaid.{command,args,enabled_tools=["qloo_places"],env_vars}]
  gemini  REST, no JSON mode (it doesn't mix with function calling) [+ one functionDeclaration, calls run through
          the same MCP server by mcp_client.py]
"""
import argparse, json, os, sys, threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lanes as L
import phrasings as P
from mcp_client import Stdio

REPO = os.path.dirname(HERE)
SERVER = ["python3", "-I", os.path.join(REPO, "agent", "unsaid_mcp.py")]
ENV_VARS = ["UNSAID_MODE", "QLOO_API_KEY", "UNSAID_WALLS"]
OUT = os.path.join(L.RUNS, "meter.jsonl")
CFG = os.path.join(L.RUNS, ".meter.mcp.json")

# Frozen in data/meter.protocol.md (27 Oct 19:46 ET, hashed): M1, M2 and SUFFIX below are verbatim from it.
QLOO_BUDGET = 380  # Qloo network calls across the whole meter (orchestrator: keep it under 400)
PHRASINGS = [
    ("M1", "plan my Friday in {city}, I love {L1}, {L2} and {L3}, but nothing every AI would tell me"),
    ("M2", "Where should I eat and drink in {city}? I love {L1}, {L2} and {L3}. Skip anything every AI would say."),
]
SUFFIX = (' Reply with only JSON: an array of exactly 12 objects like {"name": "...", "neighbourhood": "..."}, '
          'your 12 picks. Real, currently open venues only. No other text.')


def write_cfg():
    os.makedirs(L.RUNS, exist_ok=True)
    env = {k: "${%s:-}" % k for k in ENV_VARS}  # expanded by claude at launch; no key is ever written to disk
    env["UNSAID_TOOLS"] = "qloo_places"         # honoured if the server supports it; the CLI flags enforce it anyway
    json.dump({"mcpServers": {"unsaid": {"type": "stdio", "command": SERVER[0], "args": SERVER[1:], "env": env}}},
              open(CFG, "w"), indent=1)
    return CFG


def probe(allow_fake):
    if not os.path.exists(SERVER[2]):
        return None, "needs %s" % SERVER[2]
    mode = os.environ.get("UNSAID_MODE", "")
    if mode != "live" and not allow_fake:
        return None, "the with arm needs UNSAID_MODE=live and QLOO_API_KEY (or --allow-fake for a plumbing test)"
    try:
        c = Stdio(SERVER[0], SERVER[1:], env=dict(os.environ, UNSAID_TOOLS="qloo_places"))
        tools = c.tools()
    except Exception as e:
        return None, "MCP server failed to start: %s" % e
    t = [x for x in tools if x["name"] == "qloo_places"]
    if not t:
        c.close()
        return None, "needs the qloo_places tool in agent/unsaid_mcp.py (it lists %s)" % [x["name"] for x in tools]
    return (c, t[0]), "qloo_places found (%s mode)" % (mode or "fake")


def ordered_sets(path=None):
    """[(city, sid, loves)] in the sets file's own order (data/sets.json first), as the protocol requires."""
    src = path or next((p for p in P.SETS_SOURCES if os.path.exists(p)), None)
    raw = json.load(open(src)) if src else None
    if isinstance(raw, dict) and isinstance(raw.get("sets"), list):
        return [(x["city"], x["id"], [l[0] if isinstance(l, list) else l for l in x["loves"]]) for x in raw["sets"]], src
    sets = P.load_sets(path)
    return [(ck, sid, loves) for ck in sets for sid, loves in sets[ck]], src


def build(chosen, reps):
    out = []
    for ck, sid, loves in chosen:
        if True:
            L3 = {"L%d" % (i + 1): l for i, l in enumerate(loves)}
            for pid, t in PHRASINGS:
                ph = t.format(city=P.CITY[ck], **L3)
                for arm in ("alone", "with"):
                    for r in range(1, reps + 1):
                        out.append({"id": "meter:%s:%s:%s:%s:r%d" % (ck, sid, pid, arm, r), "kind": "meter", "city": ck,
                                    "set": sid, "loves": loves, "phrasing_id": pid, "phrasing": ph, "arm": arm, "rep": r,
                                    "prompt": ph + SUFFIX, "prompt_v": "meter-v1 (data/meter.protocol.md)"})
    return out


def opts_for(lane, arm, tool):
    if lane.name == "claude":
        return {"meter": True, "mcp_config": write_cfg() if arm == "with" else None}
    if lane.name == "codex":
        return {"mcp": {"command": SERVER[0], "args": SERVER[1:], "env_vars": ENV_VARS} if arm == "with" else None}
    if lane.name == "gemini":
        if arm == "alone":
            return {"json_mode": False}
        c, t = tool
        return {"json_mode": False, "call_tool": c.call_tool, "functions": [
            {"name": "qloo_places", "description": t.get("description", ""), "parametersJsonSchema": t["inputSchema"]}]}
    return {}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lane", default="all")
    ap.add_argument("--arm", default="alone,with")
    ap.add_argument("--n-sets", type=int, default=10, help="the first N sets in the sets file's order")
    ap.add_argument("--sets", default=None, help="explicit set ids instead")
    ap.add_argument("--sets-file", default=None)
    ap.add_argument("--reps", type=int, default=1, help="the protocol names no repeats: 1")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--allow-fake", action="store_true")
    ap.add_argument("--go", action="store_true")
    a = ap.parse_args()
    arms = [x.strip() for x in a.arm.split(",")]
    allsets, src = ordered_sets(a.sets_file)
    chosen = [x for x in allsets if x[1] in set(a.sets.split(","))] if a.sets else allsets[:a.n_sets]
    print("[meter] sets (%s order): %s" % (os.path.relpath(src, HERE) if src else "seeds", ", ".join(x[1] for x in chosen)))
    asks = [x for x in build(chosen, a.reps) if x["arm"] in arms]
    os.environ.setdefault("UNSAID_WALLS", os.path.join(REPO, "data", "walls"))  # absolute: the server runs in a temp dir
    for k in ("GEMINI_API_KEY",):
        os.environ.pop(k, None)  # the CLIs never need it
    tool = None
    if "with" in arms:
        tool, msg = probe(a.allow_fake)
        print("[meter] " + msg)
        if not tool:
            arms = [x for x in arms if x != "with"]
            asks = [x for x in asks if x["arm"] != "with"]
            print("[meter] running the alone arm only" if asks else "[meter] nothing to run")
    if os.environ.get("UNSAID_MODE") != "live":
        for x in asks:
            if x["arm"] == "with":
                x["fake"] = True
    names = [x for x in (list(L.LANES) if a.lane == "all" else a.lane.split(",")) if x != "gemini"]
    if "gemini" in a.lane or a.lane == "all":
        print("[gemini] not run: free-tier 20/day (orchestrator, 28 Oct)")
    lanes = L.lanes_from(",".join(names)) if names else []

    spent = {"network": sum(((r.get("qloo") or {}).get("network") or 0) for r in L.load(OUT).values())}
    lk = threading.Lock()

    def on_record(rec):
        with lk:
            spent["network"] += (rec.get("qloo") or {}).get("network") or 0
        if rec.get("arm") == "with":
            print("[%s] %s tools %s, qloo network %s (meter total %d)" % (rec["runner"], rec["id"], rec.get("tools_called"),
                                                                         (rec.get("qloo") or {}).get("network"), spent["network"]), flush=True)

    def over():
        return "Qloo budget: %d network calls >= %d" % (spent["network"], QLOO_BUDGET) if spent["network"] >= QLOO_BUDGET else None

    def one_lane(lane):  # arms in turn within a lane; lanes in parallel
        for arm in arms:
            L.run(lane, [dict(x, id=x["id"] + ":" + lane.name) for x in asks if x["arm"] == arm], OUT, a.limit, a.go,
                  opts_for(lane, arm, tool), on_record, over if arm == "with" else None)
    ts = [threading.Thread(target=one_lane, args=(l,)) for l in lanes]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    if tool:
        tool[0].close()
    recs = L.load(OUT)
    done = lambda sid: all(L.is_done(r) for r in [recs.get("%s:%s" % (x["id"], l.name)) for x in asks if x["set"] == sid for l in lanes] if r) and \
        all(("%s:%s" % (x["id"], l.name)) in recs for x in asks if x["set"] == sid for l in lanes)  # noqa: E731
    status = [{"set": sid, "city": ck, "complete": done(sid)} for ck, sid, _ in chosen]
    json.dump({"protocol": "data/meter.protocol.md", "lanes": [l.name for l in lanes], "reps": a.reps, "sets": status,
               "qloo_network_calls": spent["network"]}, open(os.path.join(L.RUNS, "meter_sets.json"), "w"), indent=1)
    print("[meter] sets complete: %d of %d; Qloo network calls so far: %d (budget %d)" % (
        sum(x["complete"] for x in status), len(status), spent["network"], QLOO_BUDGET))


if __name__ == "__main__":
    main()
