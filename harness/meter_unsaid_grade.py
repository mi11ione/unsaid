"""Grade the post-hoc unsaid meter arm (harness/meter_unsaid.md) with k10's grading, unchanged. 0 Qloo calls.

engine/k10_meter.py runs as is (runpy) on one combined file: the frozen runs/meter.jsonl (alone, with Qloo) plus
runs/meter_unsaid.jsonl, whose arms are renamed "unsaid" and "drift" so k10's own alone / with-Qloo medians are untouched.
Every run is then scored with k10's own pools and k10's per-pick rule (match_wall against the other assistants'
city-wall + census names, own provider left out, street asks excluded). On top: the measures meter_unsaid.md defines:
leakage split, adherence (tool-call rate, tool picks of 12), intention to treat, drift. Label: post-hoc, not pre-registered.

  python3 -I meter_unsaid_grade.py > runs/meter_unsaid_grade.txt
"""
import io, json, os, runpy, statistics, sys, tempfile
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
ENGINE = os.path.join(REPO, "engine")
# The frozen protocol grades on the city wall + census (data/meter.protocol.md). The later lanes (street, search-on,
# saturation, e1) are left out so every arm is graded on the same list the frozen meter used; override with UNSAID_GRADE_WALLS.
WALLS = os.environ.get("UNSAID_GRADE_WALLS") or ""


def protocol_walls():
    """A temp dir with only data/walls/wall-<N>.json and census.json: the frozen protocol's grading list."""
    import glob, re, shutil
    d = tempfile.mkdtemp(prefix="unsaid-grade-")
    for f in glob.glob(os.path.join(REPO, "data", "walls", "*.json")):
        b = os.path.basename(f)
        if b == "census.json" or re.match(r"wall-\d+\.json$", b):
            shutil.copy(f, d)
    return d
sys.path.insert(0, HERE)
import lanes as L


def recs(path):
    return [r for r in L.load(path).values() if L.is_done(r)]


def main():
    frozen = recs(os.path.join(L.RUNS, "meter.jsonl"))
    post = recs(os.path.join(L.RUNS, "meter_unsaid.jsonl"))
    post = [dict(r, arm="drift" if r.get("drift") else r["arm"]) for r in post]
    tmp = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
    for r in frozen + post:
        tmp.write(json.dumps(r, ensure_ascii=False) + "\n")
    tmp.close()
    sys.path.insert(0, ENGINE)
    walls = WALLS or protocol_walls()
    print("grading list: %s" % sorted(os.listdir(walls)))
    sys.argv = ["k10_meter.py", "--meter", tmp.name, "--walls", walls]
    out = io.StringIO()
    with redirect_stdout(out):
        g = runpy.run_path(os.path.join(ENGINE, "k10_meter.py"), run_name="k10")
    os.unlink(tmp.name)
    print("== k10_meter, unchanged, on the frozen runs + the post-hoc runs (frozen arms' lines exactly as k10 prints them)")
    print(out.getvalue().rstrip())
    M, W, pools, walls_by_city = g["M"], g["W"], g["pools"], g["walls_by_city"]

    def score(r):  # k10's per-run rule, verbatim in effect: picks[:12], match_wall against the run's pool
        city = W._ckey(r["city"])
        if city not in walls_by_city:
            walls_by_city[city] = g["generic_wall"](city)
        key = (city, r.get("provider"))
        if key not in pools:
            names = [n for p, n in walls_by_city[city] if p != r.get("provider")]
            pools[key] = [{"entity_id": M.norm(n), "name": n} for n in dict.fromkeys(names)]
        picks = [p["name"] if isinstance(p, dict) else p for p in (r.get("places") or [])][:12]
        on = [p for p in picks if M.match_wall([p], pools[key], None)[0]]
        return picks, on

    print("\n== POST-HOC, NOT PRE-REGISTERED: meter arm 3, an agent with unsaid_places as its only tool")
    med = lambda xs: statistics.median(xs) if xs else float("nan")  # noqa: E731
    by = {}
    for r in frozen:
        by.setdefault(("qloo" if r["arm"] == "with" else r["arm"]), []).append(r)
    by["unsaid"] = [r for r in post if r["arm"] == "unsaid"]
    sets = sorted({r["set"] for r in by["unsaid"]})
    per_set = {}
    for arm in ("alone", "qloo", "unsaid"):
        for r in by.get(arm, []):
            if r["set"] in sets:
                per_set.setdefault(arm, {}).setdefault(r["set"], []).append(len(score(r)[1]))
    meds = {arm: med([med(v) for v in per_set.get(arm, {}).values()]) for arm in ("alone", "qloo", "unsaid")}
    print("primary (per-set median of runs, then the median across %d sets; of 12 on the other AIs' everyone-list):" % len(sets))
    print("   alone %.1f · with Qloo %.1f · with UNSAID %.1f" % (meds["alone"], meds["qloo"], meds["unsaid"]))
    for s in sets:
        print("   %-18s alone %s · Qloo %s · UNSAID %s" % (s, per_set.get("alone", {}).get(s), per_set.get("qloo", {}).get(s),
                                                         per_set.get("unsaid", {}).get(s)))
    pooled = {arm: med([len(score(r)[1]) for r in by.get(arm, []) if r["set"] in sets]) for arm in ("alone", "qloo", "unsaid")}
    print("k10-style pooled median over all runs: alone %.1f · with Qloo %.1f · with UNSAID %.1f" % (
        pooled["alone"], pooled["qloo"], pooled["unsaid"]))
    tool_on = added_on = 0
    bug = []
    called, tool_share, itt = 0, [], []
    for r in by["unsaid"]:
        picks, on = score(r)
        tool = [t for t in (r.get("tool_results") or []) if t.get("picks")]
        pool = [{"entity_id": x.get("qloo_id") or x.get("name"), "name": x.get("name")} for t in tool for x in t["picks"]]
        idx = M.PoolIndex(pool) if pool else None
        is_tool = lambda p: bool(idx and idx.r1(p))  # noqa: E731 (Qloo ids aren't in the answer: matcher R1)
        n_tool = sum(1 for p in picks if is_tool(p))
        tool_share.append(n_tool)
        for p in on:
            if is_tool(p):
                tool_on += 1
                bug.append("%s <- %s" % (p, r["id"].replace("meter:", "")))
            else:
                added_on += 1
        if (r.get("tool_calls") or 0) > 0:
            called += 1
        if not (r.get("tool_calls") or 0) or r.get("tool_failed"):
            itt.append("%s (%s, %d on list)" % (r["id"].replace("meter:", ""), "no call" if not r.get("tool_calls") else "tool failed", len(on)))
    n = len(by["unsaid"])
    print("leakage split: everyone-list picks in the UNSAID arm: %d added by the agent, %d that were tool picks%s" % (
        added_on, tool_on, " (expected 0: a strike/grader inconsistency, reported as a bug)" if tool_on else ""))
    if bug:
        print("   tool picks graded as on the everyone-list (for D): " + "; ".join(bug))
    print("adherence: tool called in %d of %d runs (%.0f%%); tool picks among the 12, median %.1f (claude %.1f, chatgpt %.1f)" % (
        called, n, 100.0 * called / max(1, n), med(tool_share),
        med([t for t, r in zip(tool_share, by["unsaid"]) if r["runner"] == "claude"]),
        med([t for t, r in zip(tool_share, by["unsaid"]) if r["runner"] == "codex"])))
    print("intention to treat: %d runs with no tool call or a failed tool, kept in the primary: %s" % (len(itt), "; ".join(itt) or "none"))
    drift = []
    for d in [r for r in post if r["arm"] == "drift"]:
        orig = [r for r in by["alone"] if r["set"] == d["set"] and r["phrasing_id"] == d["phrasing_id"] and r["runner"] == d["runner"]]
        if orig:
            drift.append(abs(len(score(d)[1]) - len(score(orig[0])[1])))
    md = statistics.mean(drift) if drift else float("nan")
    print("drift (alone re-asked, %d runs): mean absolute change %.2f of 12%s" % (
        len(drift), md, " (> 2: read the three-arm comparison with that caveat)" if md > 2 else ""))
    ev = sorted({r.get("engine_v") for r in by["unsaid"]})
    print("engine versions: %s · Qloo hosted calls: %d" % (ev, sum(_net(r) for r in by["unsaid"])))


def _net(r):
    import meter
    return meter.tool_network(r)


if __name__ == "__main__":
    main()
