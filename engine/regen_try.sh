#!/usr/bin/env bash
# Regenerate the try-these sets in one unattended command (the 30 Oct 12:00 ET freeze re-runs it).
#
#   engine/regen_try.sh            # from anywhere in the repo or its worktrees
#
# 1. A clean detached worktree at origin/main (other agents' uncommitted edits never leak in).
# 2. The gitignored priors (data/priors) are copied in; the Qloo cache (engine/.cache) is linked, so cached
#    calls cost 0 and new ones stay warm for the next run. precompute reads the cache frozen (no TTL).
# 3. precompute: all 20 sets of data/sets.json against every wall in data/walls (search-on.json included)
#    -> $REGEN_FRESH (the previous copy goes to $REGEN_FRESH.bak first).
# 4. The 10 try-these files + index.json -> <main tree>/site/data/live (gitignored; only those 11 files).
# 5. Gate A (k2a_lift: taste vs popularity + the two strangers) and gate B (k3_survivors: yield), --frozen.
# 6. Summary: card changes vs the .bak, cards the search-on lane alone struck (the same 20 sets without
#    search-on walls, cache only), distinct places in 140 cards, max repeats per city, Cedric's seven.
#
# Env: REGEN_REF (origin/main), REGEN_WT (~/Desktop/qloo/wt-regen), REGEN_FRESH (~/Desktop/qloo/private/
# fresh20-28oct), REGEN_BUDGET (Qloo calls for precompute, 150), REGEN_GATE_BUDGET (per gate, 60).
# The key comes from $QLOO_API_KEY or ~/.config/unsaid/env and is never printed. Qloo output never enters git.
set -euo pipefail

MAIN=$(cd "$(dirname "$0")" && cd "$(git rev-parse --path-format=absolute --git-common-dir)/.." && pwd)
REF=${REGEN_REF:-origin/main}
WT=${REGEN_WT:-$HOME/Desktop/qloo/wt-regen}
FRESH=${REGEN_FRESH:-$HOME/Desktop/qloo/private/fresh20-28oct}
BUDGET=${REGEN_BUDGET:-150}
GBUDGET=${REGEN_GATE_BUDGET:-60}
LIVE="$MAIN/site/data/live"
say() { printf '\n== %s  %s\n' "$(date '+%H:%M:%S')" "$*"; }

case "$FRESH" in *frozen20*) echo "refusing: $FRESH is the frozen set" >&2; exit 2;; esac
[ -f "$MAIN/data/priors/nyc.json" ] && [ -f "$MAIN/data/priors/stl.json" ] || {
  echo "missing $MAIN/data/priors/{nyc,stl}.json (gitignored; build_priors.py)" >&2; exit 2; }
git -C "$MAIN" check-ignore -q "$LIVE/x.json" || { echo "refusing: $LIVE is not gitignored" >&2; exit 2; }

if [ -z "${QLOO_API_KEY:-}" ]; then
  QLOO_API_KEY=$(sed -n 's/^QLOO_API_KEY=//p' "$HOME/.config/unsaid/env" | tail -1)
fi
[ -n "$QLOO_API_KEY" ] || { echo "QLOO_API_KEY not set and not in ~/.config/unsaid/env" >&2; exit 2; }
export QLOO_API_KEY

say "worktree $WT at $REF"
git -C "$MAIN" fetch -q origin
if [ -e "$WT" ]; then git -C "$MAIN" worktree remove --force "$WT" 2>/dev/null || rm -rf "$WT"; fi
git -C "$MAIN" worktree prune
git -C "$MAIN" worktree add -q --detach "$WT" "$REF"
git -C "$WT" log --oneline -1
cp -Rp "$MAIN/data/priors" "$WT/data/"
mkdir -p "$MAIN/engine/.cache"
ln -s "$MAIN/engine/.cache" "$WT/engine/.cache"

E="$WT/engine"; OUT="$E/out"; STAGE="$OUT/fresh20"; NOSO="$OUT/fresh20-no-search-on"
mkdir -p "$OUT" "$OUT/walls-no-search-on"
cd "$E"
python3 -I - "$WT" <<'PY'
import json, os, sys
wt = sys.argv[1]
d = json.load(open(os.path.join(wt, "data", "sets.json")))
json.dump([{k: s[k] for k in ("id", "city", "label", "loves")} for s in d["sets"]],
          open(os.path.join(wt, "engine", "out", "sets20.json"), "w"), indent=1)
wd = os.path.join(wt, "data", "walls")
for f in sorted(os.listdir(wd)):
    if f.endswith(".json") and not (json.load(open(os.path.join(wd, f))).get("meta") or {}).get("search"):
        os.symlink(os.path.join(wd, f), os.path.join(wt, "engine", "out", "walls-no-search-on", f))
print("sets: %d; walls without search-on: %s" % (len(d["sets"]),
      ", ".join(sorted(os.listdir(os.path.join(wt, "engine", "out", "walls-no-search-on"))))))
PY

say "precompute 20 sets (budget $BUDGET)"
python3 -I precompute.py --walls ../data/walls --sets-file out/sets20.json --accept-top --out "$STAGE" \
  --budget "$BUDGET" 2>&1 | tee out/regen_precompute.log
grep -q "20 of 20 sets written .* -> PASS" out/regen_precompute.log || { echo "precompute did not PASS 20/20; nothing replaced" >&2; exit 1; }

say "write $FRESH (previous -> $FRESH.bak) and $LIVE (10 try-these + index.json)"
if [ -d "$FRESH" ]; then rm -rf "$FRESH.bak"; cp -Rp "$FRESH" "$FRESH.bak"; fi
mkdir -p "$FRESH" "$LIVE"
rm -f "$FRESH"/*.json
cp -p "$STAGE"/*.json "$FRESH/"
python3 -I - "$WT" "$STAGE" "$LIVE" <<'PY'
import json, os, shutil, sys
wt, stage, live = sys.argv[1:4]
tt = [s["id"] for s in json.load(open(os.path.join(wt, "data", "sets.json")))["sets"] if s.get("try_these")]
idx = json.load(open(os.path.join(stage, "index.json")))
by = {s["id"]: s for s in idx["sets"]}
order = [i for c in ("nyc", "stl") for i in tt if by[i]["city"] == c]       # the site's order: NYC first
for i in order:
    shutil.copy2(os.path.join(stage, by[i]["file"]), os.path.join(live, by[i]["file"]))
idx["sets"] = [by[i] for i in order]
with open(os.path.join(live, "index.json"), "w") as f:
    json.dump(idx, f, indent=1)
print("site: %d try-these + index.json -> %s" % (len(order), live))
PY

say "gate A (k2a_lift) and gate B (k3_survivors), --frozen, budget $GBUDGET each"
python3 -I k2a_lift.py --city both --walls ../data/walls --frozen --budget "$GBUDGET" > out/regen_gateA.log 2>&1 || true
python3 -I k3_survivors.py --city both --walls ../data/walls --frozen --budget "$GBUDGET" > out/regen_gateB.log 2>&1 || true
grep -E "^A taste moves|rho<=0.90 in|two strangers|QLOO_NETWORK_CALLS" out/regen_gateA.log || tail -3 out/regen_gateA.log
grep -E "^B survivors|sets pass|QLOO_NETWORK_CALLS" out/regen_gateB.log || tail -3 out/regen_gateB.log

say "ablation: the same 20 sets without the search-on walls (cache only)"
python3 -I precompute.py --walls out/walls-no-search-on --sets-file out/sets20.json --accept-top --out "$NOSO" \
  --no-cap --budget 10 > out/regen_nosearch.log 2>&1 || true
tail -2 out/regen_nosearch.log

say "summary"
python3 -I - "$STAGE" "$FRESH.bak" "$NOSO" <<'PY'
import collections, json, os, sys
stage, bak, noso = sys.argv[1:4]
def load(d):
    out = {}
    if not os.path.exists(os.path.join(d, "index.json")):
        return out
    for s in json.load(open(os.path.join(d, "index.json")))["sets"]:
        r = json.load(open(os.path.join(d, s["file"])))["result"]
        out[s["id"]] = (s["city"], [(c["id"], c["name"]) for c in r["picks"]], s["status"])
    return out
new, old, ns = load(stage), load(bak), load(noso)
cards = [(c, i, n) for sid, (c, p, _) in new.items() for i, n in p]
per_city = collections.Counter((c, i) for c, i, _ in cards)
print("cards %d in %d sets; status %s" % (len(cards), len(new), dict(collections.Counter(v[2] for v in new.values()))))
print("distinct places %d of %d; max repeats of one place per city %d" % (
    len({i for _, i, _ in cards}), len(cards), max(per_city.values())))
if old:
    ch = {sid: [n for i, n in new[sid][1] if i not in {j for j, _ in old.get(sid, ("", []))[1]}] for sid in new}
    print("vs .bak: %d cards changed in %d of %d sets" % (sum(map(len, ch.values())), sum(1 for v in ch.values() if v), len(new)))
    for sid, v in ch.items():
        if v:
            print("   %-18s in: %s | out: %s" % (sid, "; ".join(v), "; ".join(
                n for i, n in old[sid][1] if i not in {j for j, _ in new[sid][1]})))
if len(ns) == len(new):
    gone = {sid: [n for i, n in ns[sid][1] if i not in {j for j, _ in new[sid][1]}] for sid in new}
    print("search-on lane alone struck %d cards in %d sets" % (sum(map(len, gone.values())), sum(1 for v in gone.values() if v)))
    for sid, v in gone.items():
        if v:
            print("   %-18s %s" % (sid, "; ".join(v)))
else:
    print("search-on ablation incomplete (%d of %d sets)" % (len(ns), len(new)))
if "stl-cedric" in new:
    print("Cedric's seven: " + "; ".join(n for _, n in new["stl-cedric"][1]))
PY
say "done (worktree kept for inspection: $WT; logs in $OUT)"
