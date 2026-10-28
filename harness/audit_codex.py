"""Audit every stored codex answer for the codex_apps search leak (28 Oct), and redo the contaminated ones.

Evidence (the same as for the census): a codex record is contaminated when its event stream shows a tool call that is
not our own unsaid/qloo_places (an `mcp_tool_call` item with no unsaid tool recorded, or any `foreign_tools`), a
`web_search` item, `search: "on"`, or any shell use (a `command_execution` item or stored `commands`). codex_apps' search_service.web_run arrives as an mcp_tool_call.

  python3 -I audit_codex.py            # read-only: contaminated count per file
  python3 -I audit_codex.py --fix      # re-ask each contaminated record (codex now runs with --disable apps), append the
                                       # new record under the same id, and mark the old line superseded_by (kept for audit)
The meter "with" arm needs UNSAID_MODE=live and QLOO_API_KEY in the env for --fix.
"""
import argparse, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lanes as L

import glob
FILES = ["codex_answers.jsonl"] + sorted(os.path.relpath(p, os.path.dirname(os.path.abspath(__file__)))
                                         for p in glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)), "runs", "*.jsonl"))
                                         if not p.endswith("quarantine.jsonl"))


def is_codex(r):
    return r.get("runner") == "codex" or r.get("provider") == "openai"


# codex built-ins that only list resources of configured MCP servers. The codex line configures none (apps disabled,
# --ignore-user-config), so they return an empty list: no network, no content. Recorded on the answer, not a leak.
BENIGN = {"codex/list_mcp_resources", "codex/list_mcp_resource_templates"}


def contaminated(r):
    items = r.get("items") or []
    foreign = [t for t in (r.get("foreign_tools") or []) if t not in BENIGN]
    called = [c for c in (r.get("tools_called") or []) if c not in BENIGN]
    ours = [c for c in called if str(c).startswith("unsaid/")]
    benign_only = r.get("foreign_tools") and not foreign and not called
    if foreign or "web_search" in items or r.get("search") == "on":
        return True
    if "command_execution" in items or r.get("commands"):  # any shell use (28 Oct: --disable shell_tool since)
        return True
    if "mcp_tool_call" in items and not benign_only and not (ours and len(ours) == len(called)):
        return True
    return False


def lines(path):
    return [json.loads(l) for l in open(path) if l.strip()] if os.path.exists(path) else []


def mark_superseded(path, recs):
    """An old contaminated line is superseded once a later clean record with the same id exists."""
    later_clean, n = {}, 0
    for i, r in enumerate(recs):
        if is_codex(r) and not contaminated(r) and L.is_done(r):
            later_clean[r["id"]] = (i, r.get("asked_at"))
    for i, r in enumerate(recs):
        if is_codex(r) and contaminated(r) and not r.get("superseded_by") and r["id"] in later_clean and later_clean[r["id"]][0] > i:
            r["superseded_by"] = later_clean[r["id"]][1]
            r["superseded_reason"] = ("tool use in this answer (codex_apps web search or a shell command); "
                                      "re-asked with --disable apps --disable shell_tool")
            n += 1
    if n:
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            f.write("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs))
        os.replace(tmp, path)
    return n


def opts_for(r):
    if r.get("kind") == "fresh" and r.get("verbatim"):
        return {"schema": None}
    if r.get("kind") == "meter" and r.get("arm") == "with":
        import meter
        return {"mcp": {"command": meter.SERVER[0], "args": meter.SERVER[1:], "env_vars": meter.ENV_VARS}}
    return {}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fix", action="store_true")
    a = ap.parse_args()
    lane = L.CodexLane() if a.fix else None
    if a.fix:
        ok, msg = lane.check()
        if not ok:
            sys.exit(msg)
    for f in FILES:
        p = os.path.join(HERE, f)
        recs = lines(p)
        cx = [r for r in recs if is_codex(r)]
        bad = [r for r in cx if contaminated(r)]
        open_bad = [r for r in bad if not r.get("superseded_by")]
        latest = L.load(p)  # last live record per id (skips superseded and quarantined lines)
        unresolved = sorted(i for i, r in latest.items() if is_codex(r) and contaminated(r))
        print("%-24s codex records %4d, contaminated %3d (already superseded %d), unresolved ids %d%s" % (
            f, len(cx), len(bad), len(bad) - len(open_bad), len(unresolved), (": " + ", ".join(unresolved)) if unresolved else ""))
        if not a.fix:
            continue
        def redo(rid):
            old = [r for r in recs if r["id"] == rid][-1]
            ask = {k: v for k, v in old.items() if k in ("id", "kind", "city", "set", "loves", "phrasing_id", "phrasing",
                                                         "prompt", "prompt_v", "family", "person", "order", "wall", "hood",
                                                         "arm", "rep", "variant", "context_prefix", "verbatim", "suffix",
                                                         "url", "with_loves", "with_loves_ids")}
            res = lane.ask(old["prompt"], **opts_for(old))
            rec = dict(ask, **res)
            rec.update(lane="dated", provider=lane.provider, assistant=lane.assistant, runner=lane.name,
                       redo_of="codex tool leak (28 Oct): codex_apps web search or shell command")
            rec.pop("fatal", None)
            if old.get("verbatim") and rec["status"] == "unparsed":
                rec["status"] = "ok"
            L.append(p, rec)
            print("   redo %s -> %s, items %s, tools %s, %d names" % (rid, rec["status"], rec.get("items"),
                                                                     rec.get("tools_called"), len(rec.get("places") or [])), flush=True)
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(lane.workers) as ex:  # codex: 2
            list(ex.map(redo, unresolved))
        n = mark_superseded(p, lines(p))
        if n:
            print("   marked %d old lines superseded_by" % n)


if __name__ == "__main__":
    main()
