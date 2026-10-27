"""Run the frozen 128 census asks (asks.json, prompt v1, sha256 ca82f4e3...) on one lane, one fresh session per ask.
Appends to <provider>_answers.jsonl and skips ids already stored, so it resumes. The prompts go out verbatim, so every
provider's census is like for like with the Claude census of 27 Oct.

  python3 -I run_census.py --provider claude            # 0 to ask: the 27 Oct run is stored (128 of 128)
  python3 -I run_census.py --provider codex --go        # 2 workers, needs `codex login` + CODEX_MODEL
  python3 -I run_census.py --provider gemini --go       # paced at GEMINI_RPM, needs GEMINI_* env
  python3 -I run_census.py --provider codex --only-hidden --go   # just the 32 hidden-gem asks first

The original research/round4/exp/run_census.py (claude only, positional CWD) is unchanged; this copy differs in the
lane, the record fields (status, provider, model, asked_at; no session id or cost) and the empty temp dir per ask.
"""
import argparse, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lanes as L


def out_path(provider):
    return os.path.join(HERE, "%s_answers.jsonl" % provider)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--provider", required=True, choices=sorted(L.LANES))
    ap.add_argument("--only-hidden", action="store_true", help="only the 16+16 hidden-gem asks")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--go", action="store_true", help="actually ask (default: dry run)")
    a = ap.parse_args()
    asks = json.load(open(os.path.join(HERE, "asks.json")))  # already in the frozen shuffled order
    if a.only_hidden:
        asks = [x for x in asks if x["family"] == "hidden"]
    asks = [dict(x, kind="census", phrasing_id=x["id"], prompt_v="v1", set=None) for x in asks]
    if a.provider == "gemini" and not a.only_hidden:
        sys.exit("gemini: full 128-ask census not run: free-tier 20/day. Its 32 hidden-gem asks run through "
                 "`walls_cli.py queue gemini-priority` (stored in gemini_answers.jsonl)")
    lanes = L.lanes_from(a.provider)
    if not lanes:
        sys.exit(1)
    L.run(lanes[0], asks, out_path(a.provider), a.limit, a.go)


if __name__ == "__main__":
    main()
