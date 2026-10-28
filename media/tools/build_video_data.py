"""Data for media/video.html (the 60 s Devpost video), from stored files only. Every number the video shows is
read from here, and each is checked against the file it comes from (the build fails on a mismatch).
  python3 -I media/tools/build_video_data.py          (from unsaid/; render.sh video runs it)
Writes media/data/live/video.json (gitignored). Sources are listed in media/VIDEO-NOTES.md."""
import collections, importlib.util, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
P = lambda *a: os.path.join(ROOT, *a)

# the census module's own loader and gem rule (core-key containment), so the per-ask hits are the stats file's hits
spec = importlib.util.spec_from_file_location("census_stats", P("harness", "census_stats.py"))
CS = importlib.util.module_from_spec(spec); spec.loader.exec_module(CS)

CEN = json.load(open(P("site", "data", "census.json")))
S = CEN["stl"]
GEM = S["mailee_claude"]["name"]          # the two-AI hero's gem (UNSAID.md §0)


def hidden(provider):
    rs = [r for r in CS.load(provider) if r["city"] == "stl" and r["family"] == "hidden"]
    return {r["id"]: any(CS.gem_hit(x["name"], GEM) for x in r["places"]) for r in rs}


cl, gp = hidden("claude"), hidden("codex")
order = [a["id"] for a in S["gem_asks"]]                     # Claude's census order, as the clip shows them
assert sorted(order) == sorted(cl) == sorted(gp), "the 16 hidden-gem phrasings differ between providers"
asks = [{"id": i, "ask": a["ask"], "claude": cl[i], "chatgpt": gp[i]} for i, a in zip(order, S["gem_asks"])]
nc, ng = sum(a["claude"] for a in asks), sum(a["chatgpt"] for a in asks)
# census_stats_claude.txt:59 (Mai Lee 13/16) and census_stats_codex.txt:60 (Mai Lee 10/16), via census.json
assert (nc, len(asks)) == (S["mailee_claude"]["hits"], S["mailee_claude"]["of"]), (nc, S["mailee_claude"])
assert (ng, len(asks)) == (S["chatgpt"]["gem"]["hits"], S["chatgpt"]["gem"]["of"]), (ng, S["chatgpt"]["gem"])


def clean(n):   # site/js/map.js cleanName(): "Pork steak and ribs BBQ at Pappy's Smokehouse" -> "Pappy's Smokehouse"
    s = re.sub(r"\s*\(.*?\)\s*", " ", n).strip()
    m = re.match(r"^.+? at (.+)$", s)
    if m and len(m.group(1).split(" ")) <= 5 and not re.match(r"^(jazz|lounge) at", s, re.I):
        s = m.group(1)
    return s


LIVE = json.load(open(P("site", "data", "live", "stl_stl-cedric.json")))
R = LIVE["result"]
by = collections.defaultdict(lambda: {"asks": set(), "names": collections.Counter(), "prov": set()})
for w in R["wall"]:
    b = by[w["place"]]; b["asks"].add((w["provider"], w["phrasing_id"], w["asked_at"])); b["names"][clean(w["name"])] += 1
    b["prov"].add({"anthropic": "Claude", "openai": "ChatGPT", "google": "Gemini"}[w["provider"]])
wall = sorted(({"name": b["names"].most_common(1)[0][0], "asks": len(b["asks"]), "by": sorted(b["prov"])} for b in by.values()),
              key=lambda x: (-x["asks"], x["name"]))
n_asks = len({(w["provider"], w["phrasing_id"], w["asked_at"]) for w in R["wall"]})
assert len(wall) == R["counts"]["wall"], (len(wall), R["counts"]["wall"])      # 418 places
assert n_asks == R["counts"]["asks"], (n_asks, R["counts"]["asks"])               # 179 asks
prov_asks = collections.Counter(p for p, _, _ in {(w["provider"], w["phrasing_id"], w["asked_at"]) for w in R["wall"]})

C = R["counts"]
assert C["U"] - C["struck_in_U"] == C["S"], C                                      # 52 - 9 = 43

keep = ("name", "neighbourhood", "what", "fit_rank", "any_rank", "U", "rating", "open", "because", "holds", "n_loves", "lat", "lon")
card = lambda c: {k: c.get(k) for k in keep} | {"never_said": c["never_said"]["asks"]}
typed = {l["label"]: l.get("text") or l["label"] for l in LIVE["loves"]}
loves = [{"label": typed.get(l["label"], l["label"]), "qloo": l["label"], "type": l.get("type_label"), "dead": l.get("dead", False)} for l in R["loves"]]

# the agent beat: ONE live run, its tool call and its tool result from the same transcript (Agent E records it at
# agent/demo/live_transcript.jsonl, remote mode against the hosted API). Two formats are read: MCP JSON-RPC lines
# ({"dir": ">>"|"<<", "msg": ...}, like agent/transcript.jsonl) and Claude stream-json (assistant tool_use, user
# tool_result, final result). A fake-mode result is refused. No transcript: the video drops the agent scene.
TRANSCRIPT = os.environ.get("AGENT_TRANSCRIPT") or P("agent", "demo", "live_transcript.jsonl")
ALLOW_FAKE = os.environ.get("VIDEO_TEST_ALLOW_FAKE") == "1"     # layout tests only; render.sh never sets it


def result_text(content):
    """the tool result's own text: content blocks (MCP) or a string; returns (text, structured or None)"""
    st = None
    if isinstance(content, dict):
        st = content.get("structuredContent"); content = content.get("content")
    if isinstance(content, list):
        texts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
    else:
        texts = [content or ""]
    for t in texts:
        try:
            j = json.loads(t)
            if isinstance(j, dict) and st is None: st = j
        except Exception:
            pass
    summary = next((t for t in texts if t and not t.lstrip().startswith("{")), None)
    return summary, st


def agent_beat(path):
    if not os.path.exists(path):
        print("note: %s absent: the video has no agent scene" % os.path.relpath(path, ROOT)); return None
    rows = [json.loads(l) for l in open(path) if l.strip()]
    call = res = reply = None; client = model = None; when = None
    sess = next((r for r in rows if r.get("kind") == "session"), {})       # Agent E's recorder adds a session line
    if any("dir" in r for r in rows):                                       # MCP JSON-RPC
        pend = {}
        for r in rows:
            if "dir" not in r:
                continue
            m = r["msg"]
            if r["dir"] == ">>" and m.get("method") == "initialize":
                client = (m.get("params", {}).get("clientInfo") or {}).get("name")
            if r["dir"] == ">>" and m.get("method") == "tools/call" and m["params"]["name"] == "unsaid_places" and call is None:
                call = {"name": m["params"]["name"], "input": m["params"]["arguments"]}; pend = m["id"]
            elif r["dir"] == "<<" and call and m.get("id") == pend and res is None:
                res = m.get("result")
        who = client or "an MCP client"
    else:                                                                   # Claude stream-json
        tid = None
        for r in rows:
            if r.get("type") == "system" and r.get("subtype") == "init":
                model = r.get("model")
            if r.get("type") == "assistant":
                for c in r["message"]["content"]:
                    if isinstance(c, dict) and c.get("type") == "tool_use" and c["name"].split("__")[-1] == "unsaid_places" and call is None:
                        call = {"name": "unsaid_places", "input": c["input"]}; tid = c["id"]
            if r.get("type") == "user" and tid:
                for c in r["message"]["content"]:
                    if isinstance(c, dict) and c.get("type") == "tool_result" and c.get("tool_use_id") == tid and res is None:
                        res = c.get("content")
            if r.get("type") == "result":
                reply = r.get("result")
        who = "Claude"
    assert call and res is not None, "no unsaid_places call with a result in " + path
    summary, st = result_text(res)
    mode = (st or {}).get("mode")
    fake = mode == "fake" or "FAKE MODE" in (summary or "") or "FAKE MODE" in json.dumps(res)
    assert ALLOW_FAKE or not fake, "the transcript is fake mode: not shown (" + path + ")"
    when = (st or {}).get("as_of") or sess.get("recorded_at")
    if not mode and (sess.get("env") or {}).get("UNSAID_MODE"):
        mode = sess["env"]["UNSAID_MODE"] + " (hosted API)" if sess["env"]["UNSAID_MODE"] == "remote" else sess["env"]["UNSAID_MODE"]
    lines = [l for l in (summary or "").splitlines() if l.strip()]
    if not lines and st and st.get("picks"):                                 # no text summary: the result's own fields
        lines = ["%d. %s (%s) · #%s for you · #%s for anyone" % (i + 1, p.get("name"), p.get("neighbourhood"), p.get("fit_rank") or p.get("rank_for_you"),
                 p.get("any_rank") or p.get("rank_for_anyone")) for i, p in enumerate(st["picks"])]
    para = None
    if reply:
        para = next((x.strip() for x in reply.split("\n\n") if x.strip()), None)
    return {"client": who, "model": model, "as_of": when, "mode": "fake (TEST)" if fake else {"remote": "live, hosted API", "live": "live"}.get(mode, mode or "live"), "file": os.path.relpath(path, ROOT),
            "tool_use": call, "result_lines": lines[:5], "result_more": max(0, len(lines) - 5), "reply": para}


AGENT = agent_beat(TRANSCRIPT)
if AGENT and AGENT["result_lines"]:
    top = R["picks"][0]["name"] if R["picks"] else None
    if top and top not in AGENT["result_lines"][min(1, len(AGENT["result_lines"]) - 1)]:
        print("note: the live tool's first pick differs from the site's set (%s); both are shown as they are" % top)
CONF = json.load(open(P("site", "data", "config.json")))
gpt_models = sorted({r.get("model") for r in CS.load("codex") if r["city"] == "stl" and r["family"] == "hidden"})
assert len(gpt_models) == 1, gpt_models

out = {
    "_": "Built by media/tools/build_video_data.py from stored files; see media/VIDEO-NOTES.md for every source.",
    "census": {"city": S["city"], "model": CEN["model"], "chatgpt_model": gpt_models[0], "date": CEN["date"], "gem": GEM, "hood": S["mailee_claude"]["hood"],
               "claude": nc, "chatgpt": ng, "of": len(asks), "asks": asks,
               "k50_claude": S["k50"]["n"], "k50_chatgpt": S["chatgpt"]["k50"]["n"], "asks_per_city": S["asks"]["n"]},
    "cedric": {"label": LIVE["label"], "person": LIVE["label"].split(" · ")[0], "city": R["city"]["name"], "floor": CONF["floor"]["rating"],
               "flags": R.get("flags", []), "loves": loves, "wall": wall, "wall_n": C["wall"], "asks": C["asks"], "asks_by": dict(prov_asks),
               "U": C["U"], "struck_in_U": C["struck_in_U"], "S": C["S"], "R_mi": C["R_mi"], "qloo_calls": R["diag"]["qloo_calls"],
               "as_of": R["diag"]["as_of"], "picks": [card(c) for c in R["picks"]], "reserves": [card(c) for c in R["reserves"]]},
    "agent": AGENT,
}
os.makedirs(P("media", "data", "live"), exist_ok=True)   # gitignored: Qloo-derived results never enter git (§3.5)
json.dump(out, open(P("media", "data", "live", "video.json"), "w"), indent=1, ensure_ascii=False)
print("media/data/live/video.json: Mai Lee Claude %d/16, ChatGPT %d/16; wall %d places / %d asks %s; U %d, struck %d, S %d; %d picks + %d reserves"
      % (nc, ng, len(wall), n_asks, dict(prov_asks), C["U"], C["struck_in_U"], C["S"], len(R["picks"]), len(R["reserves"])))
