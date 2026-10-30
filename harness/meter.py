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
import argparse, json, os, sys, threading, time

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
QLOO_BUDGET = 380  # Qloo network calls across the whole meter (author: keep it under 400)
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


# ---------------------------------------------------------------- post-hoc third arm (harness/meter_unsaid.md)
OUT_UNSAID = os.path.join(L.RUNS, "meter_unsaid.jsonl")   # never the frozen runs/meter.jsonl
CFG_UNSAID = os.path.join(L.RUNS, ".meter_unsaid.mcp.json")
UNSAID_URL_DEFAULT = "https://unsaid.mi11ion.io"
QLOO_CAP_UNSAID = 900  # raised from 370 by the author, 28 Oct (see meter_unsaid.md change log)
FRESH_PER_HOUR = 3          # the host's per-address limit, unless the agent server sends the bench header
DRIFT_SETS = ("stl-cedric", "stl-wilco")
RETRY_STATUSES = ("limited", "degraded", "waking", "queued", "error")


def write_cfg_unsaid():
    os.makedirs(L.RUNS, exist_ok=True)
    env = {"UNSAID_MODE": "remote", "UNSAID_TOKEN": "${UNSAID_TOKEN:-}", "UNSAID_URL": "${UNSAID_URL:-}",
           }  # no Qloo key and no bench secret here: bench_proxy.py adds the header in front of the host
    json.dump({"mcpServers": {"unsaid": {"type": "stdio", "command": SERVER[0], "args": SERVER[1:], "env": env}}},
              open(CFG_UNSAID, "w"), indent=1)
    return CFG_UNSAID


def host_engine_v():
    import urllib.request
    url = (os.environ.get("UNSAID_URL") or UNSAID_URL_DEFAULT).rstrip("/") + "/api/health"
    try:
        return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "unsaid-harness/0.1"}),
                                                 timeout=30).read()).get("engine_v")
    except Exception as e:
        return "unknown (%s)" % type(e).__name__


def unsaid_opts(lane):
    if lane.name == "claude":
        return {"meter": True, "mcp_config": write_cfg_unsaid(), "tool": "unsaid_places"}
    return {"mcp": {"command": SERVER[0], "args": SERVER[1:], "tool": "unsaid_places",
                    "env_vars": ["UNSAID_MODE", "UNSAID_TOKEN", "UNSAID_URL"]}}


def tool_network(r):
    """Hosted Qloo network calls behind one run's tool results; a host cache hit costs 0."""
    n = 0
    for t in r.get("tool_results") or []:
        if (t.get("host") or {}).get("cached"):
            continue
        q = t.get("qloo_calls") or {}
        n += int(q.get("network") if q.get("network") is not None else (q.get("total") or 0))
    return n


def run_unsaid(a, lanes):
    """40 unsaid asks + 8 drift alone asks, sequential, set by set, so a set's first call is its only fresh run.
    Pacing: <= 3 fresh sets per rolling hour unless UNSAID_BENCH is set (and honoured by the agent server)."""
    os.environ["UNSAID_MODE"] = "remote"
    os.environ.setdefault("UNSAID_URL", UNSAID_URL_DEFAULT)
    if not os.environ.get("UNSAID_TOKEN"):
        sys.exit("needs UNSAID_TOKEN (the hosted API's bearer token) in the env")
    sets_doc = json.load(open(os.path.join(L.RUNS, "meter_sets.json")))
    chosen_ids = [x["set"] for x in sets_doc["sets"]]
    allsets, _ = ordered_sets(a.sets_file)
    chosen = [x for x in allsets if x[1] in chosen_ids]
    asks = []
    for ck, sid, loves in chosen:
        for x in build([(ck, sid, loves)], 1):
            if x["arm"] == "alone" and sid in DRIFT_SETS:
                asks.append(dict(x, id=x["id"].replace(":alone:", ":alone-drift:"), drift=True, posthoc=True))
            if x["arm"] == "with":
                asks.append(dict(x, id=x["id"].replace(":with:", ":unsaid:"), arm="unsaid", posthoc=True,
                                 prompt_v="meter-v1 (data/meter.protocol.md) + post-hoc unsaid arm (harness/meter_unsaid.md)"))
    done = L.done_ids(OUT_UNSAID)
    spent = sum(tool_network(r) for r in L.load(OUT_UNSAID).values())
    todo = [(lane, x) for x in asks for lane in lanes if "%s:%s" % (x["id"], lane.name) not in done]
    bench = bool(os.environ.get("UNSAID_BENCH_VIA_PROXY"))  # bench_proxy.py adds X-Unsaid-Bench in front of the host
    print("[unsaid-arm] post-hoc: %d asks (%d unsaid + %d drift) x lanes, %d to ask; Qloo so far %d (cap %d); pacing %s%s" % (
        len(asks) * len(lanes), sum(1 for x in asks if x["arm"] == "unsaid") * len(lanes),
        sum(1 for x in asks if x.get("drift")) * len(lanes), len(todo), spent, QLOO_CAP_UNSAID,
        "bench header" if bench else "%d fresh sets/hour" % FRESH_PER_HOUR, "" if a.go else " (dry run: add --go)"), flush=True)
    if not a.go:
        return
    starts, first_v = [], None
    for lane, x in todo:
        if L.disk_low() or spent >= QLOO_CAP_UNSAID:
            print("[unsaid-arm] stop: %s" % (L.disk_low() or "Qloo cap %d reached (%d)" % (QLOO_CAP_UNSAID, spent)), flush=True)
            break
        new_set = x["arm"] == "unsaid" and not any(r.get("set") == x["set"] and r.get("arm") == "unsaid"
                                                    for r in L.load(OUT_UNSAID).values())
        if new_set and not bench:
            starts = [t for t in starts if time.time() - t < 3600]
            if len(starts) >= FRESH_PER_HOUR:
                wait = 3600 - (time.time() - starts[0]) + 5
                print("[unsaid-arm] pacing: %d fresh sets this hour; waiting %d s" % (len(starts), wait), flush=True)
                time.sleep(wait)
            starts.append(time.time())
        opts = unsaid_opts(lane) if x["arm"] == "unsaid" else opts_for(lane, "alone", None)
        ev = host_engine_v() if x["arm"] == "unsaid" else None
        if ev and str(ev).startswith("unknown"):  # the proxy or the host is down: never store a tool-less answer
            print("[unsaid-arm] stop: the host is unreachable (%s); nothing asked. Run again to resume." % ev, flush=True)
            break
        for attempt in (1, 2):
            r = lane.ask(x["prompt"], **opts)
            st = [t.get("status") for t in (r.get("tool_results") or [])]
            if x["arm"] != "unsaid" or not any(s_ in RETRY_STATUSES for s_ in st) or attempt == 2:
                break
            print("[unsaid-arm] %s: tool said %s; retrying once in 60 s" % (x["id"], st), flush=True)
            time.sleep(60)
        rec = dict(x, id="%s:%s" % (x["id"], lane.name))
        rec.update(r, lane="dated", provider=lane.provider, assistant=lane.assistant, runner=lane.name, engine_v=ev,
                   tool_failed=bool(x["arm"] == "unsaid" and (not r.get("tool_calls") or any(
                       s_ in RETRY_STATUSES for s_ in [t.get("status") for t in (r.get("tool_results") or [])]))))
        rec.pop("fatal", None)
        first_v = first_v or ev
        if ev and first_v and ev != first_v:
            rec["engine_v_differs"] = True
        L.append(OUT_UNSAID, rec)
        spent += tool_network(r)
        print("[unsaid-arm] %s %s %ss tools %s x%s qloo %s (total %d) engine %s%s" % (
            rec["id"], rec["status"], rec["secs"], rec.get("tools_called"), rec.get("tool_calls"), tool_network(rec), spent, ev,
            " TOOL_FAILED" if rec["tool_failed"] else ""), flush=True)


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
    if a.arm == "unsaid":  # post-hoc third arm; never touches runs/meter.jsonl
        names = [x for x in (list(L.LANES) if a.lane == "all" else a.lane.split(",")) if x != "gemini"]
        return run_unsaid(a, L.lanes_from(",".join(names)))
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
        print("[gemini] not run: free-tier 20/day (28 Oct)")
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
