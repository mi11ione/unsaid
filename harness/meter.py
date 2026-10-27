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

# M1 is the sentence of the 27 Oct agentic runs (research/round4/agentic.md: Smoki O's 3 of 3).
# M2 is a DRAFT: Roman freezes both into the public hash (Tue 09:00 ET) before any meter ask.
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


def build(sets, cities, set_filter, reps):
    out = []
    for ck in cities:
        for sid, loves in sets.get(ck, []):
            if set_filter and sid not in set_filter:
                continue
            L3 = {"L%d" % (i + 1): l for i, l in enumerate(loves)}
            for pid, t in PHRASINGS:
                ph = t.format(city=P.CITY[ck], **L3)
                for arm in ("alone", "with"):
                    for r in range(1, reps + 1):
                        out.append({"id": "meter:%s:%s:%s:%s:r%d" % (ck, sid, pid, arm, r), "kind": "meter", "city": ck,
                                    "set": sid, "loves": loves, "phrasing_id": pid, "phrasing": ph, "arm": arm, "rep": r,
                                    "prompt": ph + SUFFIX, "prompt_v": "meter-draft"})
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
    ap.add_argument("--city", default="stl")
    ap.add_argument("--sets", default=None, help="set ids; default all 10 of the city")
    ap.add_argument("--sets-file", default=None)
    ap.add_argument("--reps", type=int, default=2)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--allow-fake", action="store_true")
    ap.add_argument("--go", action="store_true")
    a = ap.parse_args()
    arms = [x.strip() for x in a.arm.split(",")]
    sets = P.load_sets(a.sets_file)
    asks = [x for x in build(sets, a.city.split(","), set(a.sets.split(",")) if a.sets else None, a.reps) if x["arm"] in arms]
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
    lanes = L.lanes_from(a.lane)

    def one_lane(lane):  # arms in turn within a lane; lanes in parallel
        for arm in arms:
            L.run(lane, [dict(x, id=x["id"] + ":" + lane.name) for x in asks if x["arm"] == arm], OUT, a.limit, a.go,
                  opts_for(lane, arm, tool))
    ts = [threading.Thread(target=one_lane, args=(l,)) for l in lanes]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    if tool:
        tool[0].close()


if __name__ == "__main__":
    main()
