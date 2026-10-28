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
GEM = "Mai Lee"


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

# the agent beat. tool_use: Claude's own call to the tool, verbatim (agent/demo/claude_with.jsonl; that server ran in
# fake mode, so its tool_result is NOT shown). Reply: the live run's text, verbatim lines only (private/, see notes).
tu = None
for l in open(P("agent", "demo", "claude_with.jsonl")):
    d = json.loads(l)
    if d.get("type") == "assistant":
        for c in d["message"]["content"]:
            if isinstance(c, dict) and c.get("type") == "tool_use":
                tu = {"name": c["name"].split("__")[-1], "input": c["input"]}
assert tu and tu["name"] == "unsaid_places"
QUOTE = os.path.join(ROOT, "..", "private", "agent_quote_cedric_202610280308.json")
lines = ["The usual names (Pappy's, Sugarfire, Mai Lee, Gioia's) are great, but every AI assistant gives them to everyone, so I left them out.",
         "**A plan for tonight:** Eat at Warehouse West, then go to Starz or Harlem Tap Room for the music."]
if os.path.exists(QUOTE):   # the live run stays outside the repo; checked whenever it is present
    reply = json.load(open(QUOTE))
    for s in lines:
        assert s in reply["result"], "not verbatim: " + s
    assert list(reply["modelUsage"]) == ["claude-sonnet-5-5"], reply["modelUsage"]
else:
    print("note: %s absent; reply lines not re-checked" % QUOTE)

out = {
    "_": "Built by media/tools/build_video_data.py from stored files; see media/VIDEO-NOTES.md for every source.",
    "census": {"model": CEN["model"], "chatgpt_model": "gpt-5.6-terra", "date": CEN["date"], "gem": GEM, "hood": S["mailee_claude"]["hood"],
               "claude": nc, "chatgpt": ng, "of": len(asks), "asks": asks,
               "k50_claude": S["k50"]["n"], "k50_chatgpt": S["chatgpt"]["k50"]["n"], "asks_per_city": S["asks"]["n"]},
    "cedric": {"loves": loves, "wall": wall, "wall_n": C["wall"], "asks": C["asks"], "asks_by": dict(prov_asks),
               "U": C["U"], "struck_in_U": C["struck_in_U"], "S": C["S"], "R_mi": C["R_mi"], "qloo_calls": R["diag"]["qloo_calls"],
               "as_of": R["diag"]["as_of"], "picks": [card(c) for c in R["picks"]], "reserves": [card(c) for c in R["reserves"]]},
    "agent": {"tool_use": tu, "reply": lines, "reply_model": "claude-sonnet-5-5", "reply_date": "28 Oct 2026"},
}
os.makedirs(P("media", "data", "live"), exist_ok=True)   # gitignored: Qloo-derived results never enter git (§3.5)
json.dump(out, open(P("media", "data", "live", "video.json"), "w"), indent=1, ensure_ascii=False)
print("media/data/live/video.json: Mai Lee Claude %d/16, ChatGPT %d/16; wall %d places / %d asks %s; U %d, struck %d, S %d; %d picks + %d reserves"
      % (nc, ng, len(wall), n_asks, dict(prov_asks), C["U"], C["struck_in_U"], C["S"], len(R["picks"]), len(R["reserves"])))
