#!/usr/bin/env bash
# The 30 Oct 12:00 ET re-freeze, as one resumable runbook. Every number, image and data file is regenerated from the
# final walls, and the Devpost placeholders are filled into a NEW file (~/Desktop/qloo/devpost.final.md).
#
#   ./freeze.sh                     the freeze: steps 1-9
#   ./freeze.sh --dry-run           steps 1-9 without gate F, Render, the agent re-record, commits or the site deploy
#                                   (step 8 only checks); no wait for wall #3; Qloo budgets that sum to <= 145 calls
#   ./freeze.sh --from 5            resume at step 5 (each step re-runs from scratch: all steps are idempotent)
#   ./freeze.sh --only 4            one step
#   flags: --skip-f  --render-if-unchanged  --skip-render  --skip-media  --skip-site  --allow-dirty  --to N
#          --no-street-catchup  --skip-agent  --with-video (the author's rule: no video render unless he asks)  --skip-k14
#          --numbers-only  step 3 runs only k12, k14 and numbers (no gate E, run_query, street ablation, census); a missing
#                          regen worktree is recreated clean at origin/main (cache-only reruns of the k12/k14 keys)
#
#   1 preflight   the 5 pre-registered files hash to data/prereg/SHA256SUMS; disk >= 10 GB; harness/runs/done has gem-30 + wall-3 (warn); git on main, clean but for harness output
#                 and walls, pulled; leak audit 0 unresolved; walls rebuilt from harness/runs (unless saturation or a
#                 wall ask is running: then the committed walls), committed and pushed (regen reads origin/main)
#   2 regen       engine/regen_try.sh: the 20 sets -> $FRESH and site/data/live, gates A and B --frozen; then the
#                 street catch-up: harness/street_catchup.sh $FRESH (B) asks the unasked card/reserve neighbourhoods; walls
#                 are committed, regen again; until nothing is unasked (max 3 passes; soft-fails if the script is absent)
#   3 numbers     k12, gate E (hashed 28 Oct cards + today's), run_query Cedric + README call trace, the no-street
#                 ablation, census gems, saturation coverage -> out/freeze/numbers.json; commits the regenerated
#                 counts-only files (engine/k12_wall_effect.md, site/data/wall_effect.json, README call trace)
#   4 fill        tools/fill_devpost.py -> ~/Desktop/qloo/devpost.final.md; README.md filled in place and committed;
#                 fails if any ⟦X⟧ is left in README.md or the other files a judge may open ($JUDGE_FILES)
#   5 render      tools/render_deploy.py, in this order: deploy HEAD (walls + engine) and wait for live + /api/health;
#                 refuse unless the live commit contains 547ab11 (the new priors format); push the priors; redeploy so
#                 the engine reads them; wait for live + health (priors stl/nyc true)
#   6 gate F      k11_latency.py against the live site, 10 runs (~400-500 Qloo calls)
#   7 media       tools/agent_rerecord.py (the MCP session for the video + the Claude run for the site, against the
#                 deployed engine; loud warning if The Spot Sports Bar left Cedric's run: ⟦AGENT_QUOTE⟧ is deleted);
#                 media/render.sh all (video with URL=$LIVE); agent shot vs Cedric's current cards; commits the
#                 tracked site data build_data.py rewrites
#   8 site        media/tools/deploy-site.sh (the ⟦ check, then Pages)
#   9 report      numbers + fill again (picks up gate F and the share image), out/freeze/report.txt
#
# Logs: out/freeze/ (gitignored; numbers.json names cards, which are Qloo output). Done markers: out/freeze/done/.
# Keys come from ~/.config/unsaid/env and are never printed. Qloo output never enters git.
set -euo pipefail

MAIN=$(cd "$(dirname "$0")" && pwd)
LOGS="$MAIN/out/freeze"
QLOO_DIR=$(dirname "$MAIN")
LIVE_URL=https://unsaid-ang.pages.dev
export REGEN_WT=${REGEN_WT:-$QLOO_DIR/wt-regen}
export REGEN_FRESH=${REGEN_FRESH:-$QLOO_DIR/private/fresh20-freeze}
FROZEN20=${FROZEN20:-$QLOO_DIR/private/frozen20}
SEED_FRESH=$QLOO_DIR/private/fresh20-28oct       # the 28 Oct regeneration: the first .bak, so the first diff works
WT="$REGEN_WT"; FRESH="$REGEN_FRESH"
CO="Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"

SKIP_K14=0; NUMBERS_ONLY=0
FROM=1; TO=9; SKIP_F=0; DRY=0; ALLOW_DIRTY=0; STREET_CATCHUP=1; SKIP_AGENT=0; WITH_VIDEO=0; WALL3_DEADLINE=${WALL3_DEADLINE:-12:30}; RENDER=deploy; SKIP_MEDIA=0; SKIP_SITE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --from) FROM=$2; shift;;
    --to) TO=$2; shift;;
    --only) FROM=$2; TO=$2; shift;;
    --dry-run) DRY=1; SKIP_F=1; RENDER=skip; SKIP_AGENT=1;;
    --skip-f) SKIP_F=1;;
    --render-if-unchanged) RENDER=if-unchanged;;
    --skip-render) RENDER=skip;;
    --skip-media) SKIP_MEDIA=1;;
    --skip-site) SKIP_SITE=1;;
    --allow-dirty) ALLOW_DIRTY=1;;
    --no-street-catchup) STREET_CATCHUP=0;;
    --skip-agent) SKIP_AGENT=1;;
    --with-video) WITH_VIDEO=1;;
    --skip-k14) SKIP_K14=1;;
    --numbers-only) NUMBERS_ONLY=1;;
    -h|--help) sed -n '2,32p' "$0"; exit 0;;
    *) echo "unknown flag $1" >&2; exit 2;;
  esac
  shift
done
# Qloo network-call caps per call site (cache hits are free). The dry run's sum is 145 (precompute 80, gates 10+10,
# regen's search-on ablation 10, k12 15, run_query 10, no-street 10).
if [ $DRY = 1 ]; then d_pre=80; d_gate=10; d_k12=15; d_rq=10; d_ns=10; else d_pre=400; d_gate=60; d_k12=60; d_rq=50; d_ns=60; fi
B_PRE=${FREEZE_BUDGET_PRECOMPUTE:-$d_pre}; B_GATE=${FREEZE_BUDGET_GATE:-$d_gate}; B_K12=${FREEZE_BUDGET_K12:-$d_k12}
B_RQ=${FREEZE_BUDGET_RUNQUERY:-$d_rq}; B_NS=${FREEZE_BUDGET_NOSTREET:-$d_ns}

mkdir -p "$LOGS/done"
say() { printf '\n== %s  %s\n' "$(date '+%H:%M:%S')" "$*"; }
warn() { printf 'WARN: %s\n' "$*"; }
die() { printf 'FAIL: %s\n' "$*"; exit 1; }

qloo_key() {   # the Qloo key into the env, never printed
  if [ -z "${QLOO_API_KEY:-}" ]; then
    QLOO_API_KEY=$(sed -n 's/^QLOO_API_KEY=//p' "$HOME/.config/unsaid/env" | tail -1)
  fi
  [ -n "$QLOO_API_KEY" ] || die "QLOO_API_KEY not set and not in ~/.config/unsaid/env"
  export QLOO_API_KEY
}

# commit_paths "message" path...: commit exactly these paths (if changed), rebase on origin, push
commit_paths() {
  local msg=$1; shift
  local p have=()
  for p in "$@"; do [ -e "$MAIN/$p" ] || git -C "$MAIN" ls-files --error-unmatch -- "$p" >/dev/null 2>&1 && have+=("$p"); done
  [ ${#have[@]} -gt 0 ] || { echo "commit: nothing to commit"; return 0; }
  if [ $DRY = 1 ]; then   # a dry run never commits or pushes; the files it regenerated go back to HEAD (only the
    # freeze's own outputs: never harness answers, which other agents write)
    echo "commit (dry run, not committed): $(git -C "$MAIN" status --porcelain -- "${have[@]}" | wc -l | tr -d ' ') changed paths in ${have[*]}"
    for p in "${have[@]}"; do
      case "$p" in README.md|engine/k12_wall_effect.md|site/data/*|media/data/*|data/walls)
        git -C "$MAIN" ls-files --error-unmatch -- "$p" >/dev/null 2>&1 && git -C "$MAIN" checkout -q -- "$p";; esac
    done
    return 0
  fi
  git -C "$MAIN" add -A -- "${have[@]}"
  if git -C "$MAIN" diff --cached --quiet -- "${have[@]}"; then echo "commit: no changes in ${have[*]}"; return 0; fi
  git -C "$MAIN" commit -q -m "$msg" -m "$CO" -- "${have[@]}"
  local i   # a concurrent fetch by another agent can make one pull fail ("Cannot rebase onto multiple branches")
  for i in 1 2 3 4; do git -C "$MAIN" pull -q --rebase --autostash && break; [ $i = 4 ] && die "git pull"; sleep 5; done
  for i in 1 2 3 4; do git -C "$MAIN" push -q origin HEAD:main && break; [ $i = 4 ] && die "git push"; sleep 5
    git -C "$MAIN" pull -q --rebase --autostash || true; done
  echo "commit: $(git -C "$MAIN" log --oneline -1 | cut -c1-100) (pushed)"
}

# ------------------------------------------------------------------------------------------------------------ steps
step1() {
  say "1 preflight"
  rm -f "$LOGS"/02-regen.prev-*.log   # a new freeze: earlier attempts' call counts no longer apply
  # the five pre-registered files must still hash to the public gist (data/prereg/SHA256SUMS)
  python3 -I "$MAIN/tools/freeze_numbers.py" prereg || die "pre-registration: a hashed file changed (data/prereg/SHA256SUMS)"
  local avail; avail=$(df -g "$MAIN" | awk 'NR==2{print $4}')
  [ "$avail" -ge 10 ] || die "disk: ${avail} GB free (need >= 10 GB: the video's frames are ~2 GB)"
  echo "disk: ${avail} GB free"
  [ -e "$MAIN/harness/runs/done/gem-30" ] && echo "scheduled job gem-30: done" || warn "scheduled job gem-30 has not finished"
  # dated wall #2 failed offline on 29 Oct (its done marker is false): warn on the wall file itself, never stop
  [ -f "$MAIN/data/walls/wall-2.json" ] && echo "dated wall #2: data/walls/wall-2.json present" \
    || warn "dated wall #2 is missing (data/walls/wall-2.json): the freeze goes on with the walls that exist"
  # dated wall #3 runs at 09:00 ET (~1-2 h): wait for its done marker, or until $WALL3_DEADLINE ET, whichever is first
  local et now
  if [ $DRY = 1 ]; then
    [ -e "$MAIN/harness/runs/done/wall-3" ] && echo "dated wall #3: done" || warn "dated wall #3 not done (dry run: no wait)"
  else
    while [ ! -e "$MAIN/harness/runs/done/wall-3" ]; do
      now=$(TZ=America/New_York date +%H%M)
      [ "$now" -ge "${WALL3_DEADLINE/:/}" ] && { warn "dated wall #3 not done by $WALL3_DEADLINE ET: going on with the walls that exist"; break; }
      [ $(( $(date +%s) / 60 % 10 )) = 0 ] && echo "waiting for dated wall #3 (runs/done/wall-3) until $WALL3_DEADLINE ET; now $(TZ=America/New_York date +%H:%M) ET"
      sleep 60
    done
  fi
  [ -f "$MAIN/data/walls/wall-3.json" ] && echo "dated wall #3: data/walls/wall-3.json present" \
    || warn "dated wall #3 is missing (data/walls/wall-3.json)"
  [ "$(git -C "$MAIN" rev-parse --abbrev-ref HEAD)" = main ] || die "git: not on main"
  # tracked changes allowed only where the harness writes (its logs, answers, walls); anything else stops the freeze
  local dirty
  dirty=$(git -C "$MAIN" status --porcelain --untracked-files=no | awk '{print $2}' |
          grep -vE '^(harness/runs/|harness/[a-z0-9.-]+_answers\.jsonl$|data/walls/)' || true)
  if [ -n "$dirty" ]; then   # regen reads a clean origin/main worktree, so another agent's edit cannot leak in
    [ $ALLOW_DIRTY = 1 ] && warn "git: uncommitted changes outside the harness output (--allow-dirty; not frozen): $(echo $dirty)" \
      || die "git: uncommitted changes outside the harness output: $(echo $dirty) (commit them, or --allow-dirty)"
  fi
  local i; for i in 1 2 3 4; do git -C "$MAIN" pull -q --rebase --autostash && break; [ $i = 4 ] && die "git pull --rebase"; sleep 5; done
  [ -z "$(git -C "$MAIN" rev-list origin/main..HEAD)" ] || warn "local main is ahead of origin/main: regen reads origin/main"
  echo "git: main at $(git -C "$MAIN" log --oneline -1 | cut -c1-90)"
  local audit; audit=$(cd "$MAIN/harness" && python3 -I audit_codex.py 2>&1)
  echo "$audit" | tail -3
  echo "$audit" | grep -qE 'unresolved ids [1-9]' && die "leak audit: unresolved codex answers (harness/audit_codex.py)"
  echo "leak audit: 0 unresolved"
  if pgrep -f 'saturation\.(sh|py)|search_then_sat|walls_cli\.py ask' >/dev/null; then
    warn "a saturation batch or wall ask is running: walls NOT rebuilt; the committed walls are used"
    return 0
  fi
  local labels
  labels=$(cd "$MAIN/harness/runs" && ls wall-*.jsonl | sed 's/^wall-//; s/\.jsonl$//' | grep -v '^smoke' | paste -sd, -)
  echo "walls: rebuilding $labels + census"
  rm -rf "$LOGS/walls.bak"; cp -Rp "$MAIN/data/walls" "$LOGS/walls.bak"
  (cd "$MAIN/harness" && python3 -I walls_cli.py build --walls "$labels" --no-census && python3 -I walls_cli.py build --census-only) \
    > "$LOGS/01-walls-build.txt" 2>&1 || { tail -5 "$LOGS/01-walls-build.txt"; die "walls build"; }
  grep -E '^wrote' "$LOGS/01-walls-build.txt" | cut -c1-120
  python3 -I "$MAIN/tools/freeze_numbers.py" walls-keep "$LOGS/walls.bak"
  (cd "$MAIN" && commit_paths "Freeze: walls rebuilt from harness/runs ($labels + census)" \
    data/walls $(cd "$MAIN" && ls harness/runs/wall-*.jsonl | grep -v smoke) harness/runs/saturation.json \
    $(cd "$MAIN" && ls harness/*_answers.jsonl))
}

regen_once() {   # one engine/regen_try.sh pass; the gate logs are copied for numbers.json
  # a rerun keeps the earlier attempt's log (02-regen.prev-*.log): its Qloo calls still count toward this freeze
  [ -f "$LOGS/02-regen.log" ] && mv "$LOGS/02-regen.log" "$LOGS/02-regen.prev-$(date +%H%M%S).log"
  REGEN_BUDGET=$B_PRE REGEN_GATE_BUDGET=$B_GATE REGEN_ABLATION_BUDGET=$B_NS bash "$MAIN/engine/regen_try.sh" 2>&1 | tee "$LOGS/02-regen.log"
  [ "${PIPESTATUS[0]}" = 0 ] || die "regen_try.sh"
  cp "$WT/engine/out/regen_gateA.log" "$LOGS/02-gateA.txt"
  cp "$WT/engine/out/regen_gateB.log" "$LOGS/02-gateB.txt"
  # which engine, priors and walls made $FRESH: numbers.json carries it, fill_devpost.py refuses a stale one
  python3 -I "$MAIN/tools/freeze_numbers.py" stamp --fresh "$FRESH" --wt "$WT"
}

unasked_count() {   # neighbourhoods of the regenerated cards + reserves no street answer was asked about
  python3 -I "$MAIN/tools/freeze_numbers.py" unasked --fresh "$FRESH" --write "$LOGS/street_unasked.json" \
    | tee -a "$LOGS/02-street.txt" | sed -n 's/^UNASKED=//p'
}

step2() {
  say "2 regen (engine/regen_try.sh; precompute budget $B_PRE, gates $B_GATE each) + street catch-up"
  python3 -I "$MAIN/tools/freeze_numbers.py" snapshot-cedric "$MAIN/site/data/live/stl_stl-cedric.json" "$LOGS/cedric.before.json"
  if [ ! -d "$FRESH" ] && [ -d "$SEED_FRESH" ]; then cp -Rp "$SEED_FRESH" "$FRESH"; echo "seeded $FRESH from $SEED_FRESH"; fi
  : > "$LOGS/02-street.txt"
  regen_once
  # Street catch-up (28 Oct): the cards' own neighbourhoods must all have been asked, or ⟦STREET_*⟧
  # stays unfilled. harness/street_catchup.sh (B) asks only the unasked card and reserve neighbourhoods, rebuilds the
  # walls and audits; the walls are committed and the sets regenerated. Repeat until nothing is unasked, max 3 passes.
  local pass n
  for pass in 1 2 3; do
    n=$(unasked_count); n=${n:-?}
    [ "$n" = 0 ] && { echo "street: every card and reserve neighbourhood has been asked"; return 0; }
    if [ $STREET_CATCHUP = 0 ]; then warn "street catch-up off (--no-street-catchup): $n neighbourhoods unasked"; return 0; fi
    if [ ! -x "$MAIN/harness/street_catchup.sh" ] && [ ! -f "$MAIN/harness/street_catchup.sh" ]; then
      warn "harness/street_catchup.sh is not there yet: $n neighbourhoods unasked ($LOGS/street_unasked.json); ⟦STREET_*⟧ stay unfilled"
      return 0
    fi
    echo "street catch-up pass $pass: $n unasked neighbourhoods"
    if ! bash "$MAIN/harness/street_catchup.sh" "$FRESH" > "$LOGS/02-street-catchup-$pass.txt" 2>&1; then
      tail -5 "$LOGS/02-street-catchup-$pass.txt"
      warn "street catch-up pass $pass failed: keeping the walls as they are; ⟦STREET_*⟧ may stay unfilled"
      return 0
    fi
    tail -3 "$LOGS/02-street-catchup-$pass.txt"
    if grep -q "nothing new to ask" "$LOGS/02-street-catchup-$pass.txt"; then   # B's matcher saw no gap: stop, say ours
      warn "street_catchup.sh asked nothing, but $n neighbourhoods look unasked here (name variants?): see $LOGS/street_unasked.json"
      return 0
    fi
    (cd "$MAIN" && commit_paths "Freeze: street catch-up pass $pass (unasked card and reserve neighbourhoods), walls rebuilt" \
      data/walls $(cd "$MAIN" && ls harness/runs/wall-*.jsonl | grep -v smoke))
    regen_once
  done
  n=$(unasked_count)
  [ "$n" = 0 ] && echo "street: every card and reserve neighbourhood has been asked" \
    || warn "street: $n neighbourhoods still unasked after 3 catch-up passes; ⟦STREET_*⟧ stay unfilled"
}

ensure_wt() {   # --numbers-only: a clean regen-style worktree at origin/main when step 2's is gone (regen_try.sh's setup)
  [ -d "$WT/engine/out" ] && return 0
  echo "worktree $WT missing: recreating it clean at origin/main (priors copied, Qloo cache linked)"
  git -C "$MAIN" fetch -q origin
  git -C "$MAIN" worktree prune
  git -C "$MAIN" worktree add -q --detach "$WT" origin/main
  cp -Rp "$MAIN/data/priors" "$WT/data/"
  mkdir -p "$MAIN/engine/.cache" "$WT/engine/out"
  ln -s "$MAIN/engine/.cache" "$WT/engine/.cache"
}

step3() {
  say "3 gates and stats -> out/freeze/numbers.json$([ $NUMBERS_ONLY = 1 ] && echo ' (--numbers-only: k12, k14, numbers)')"
  [ $NUMBERS_ONLY = 1 ] && ensure_wt
  [ -d "$WT/engine/out" ] && [ -f "$FRESH/index.json" ] || die "no regen worktree/output: run step 2 first"
  qloo_key
  local E="$WT/engine"
  cd "$E"
  echo "k12 (budget $B_K12)"
  python3 -I k12_wall_effect.py --walls ../data/walls --frozen --budget "$B_K12" --public-md "$E/k12_wall_effect.md" \
    > "$LOGS/03-k12.log" 2>&1 || { tail -5 "$LOGS/03-k12.log"; die "k12"; }
  grep -E "^  median over|^K12" "$LOGS/03-k12.log" || true
  cp out/k12_wall_effect.json out/k12_wall_effect.md "$LOGS/"
  cp "$E/k12_wall_effect.md" "$MAIN/engine/k12_wall_effect.md"
  python3 -I - "$E/out/k12_wall_effect.json" "$MAIN/site/data/wall_effect.json" <<'PY'
import json, sys
rows = json.load(open(sys.argv[1])); old = json.load(open(sys.argv[2]))
def med(k):
    s = sorted(r[k] for r in rows); n = len(s)
    return float(s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0)
old.update({"sets": len(rows), "of": 7, "named_unsaid": med("on_named"), "named_no_strike": med("off_named"),
            "named_plain": med("plain_named"),
            # the held-out chain the site shows (pooled cards some AI named on the fresh questions, which never fed the wall)
            "held_out_cards": sum(r["n_on"] for r in rows), "held_out_plain": sum(r["plain_fresh"] for r in rows),
            "held_out_no_strike": sum(r["off_fresh"] for r in rows), "held_out_unsaid": sum(r["on_fresh"] for r in rows)})
json.dump(old, open(sys.argv[2], "w"), indent=1, ensure_ascii=False); open(sys.argv[2], "a").write("\n")
print("site/data/wall_effect.json: UNSAID %s · no strike %s · plain %s" % (old["named_unsaid"], old["named_no_strike"], old["named_plain"]))
PY
  # k14 (Agent E): the independent labeller on THIS k12 run's cards; resumable, so only pairs not yet in
  # engine/out/k14_labels.jsonl cost claude -p calls (subscription). ⟦K14_*⟧ fill only when the labels match this run.
  if [ $SKIP_K14 = 1 ]; then echo "k14: SKIPPED (--skip-k14)"
  else
    echo "k14 independent labeller (claude -p, resumable)"
    mkdir -p "$MAIN/engine/out"
    if python3 -I k14_label.py --k12 "$LOGS/k12_wall_effect.json" --fresh ../harness/runs/fresh.jsonl \
        --labels "$MAIN/engine/out/k14_labels.jsonl" --public-md "$MAIN/engine/k14_label.md" > "$LOGS/03-k14.log" 2>&1; then
      grep -E "^== k14|labelled .* pairs" "$LOGS/03-k14.log" || true
    else
      tail -5 "$LOGS/03-k14.log"; warn "k14 failed: ⟦K14_*⟧ stay unfilled"
    fi
  fi
  if [ $NUMBERS_ONLY = 1 ]; then
    cd "$MAIN"
    python3 -I tools/freeze_numbers.py numbers --fresh "$FRESH" --nostreet "$E/out/fresh20-no-street" $([ $DRY = 1 ] && echo --dry-run)
    commit_paths "Freeze (--numbers-only): k12 table with baselines, k14 counts, site wall-effect medians (counts only)" \
      engine/k12_wall_effect.md site/data/wall_effect.json engine/k14_label.md engine/k14_label.json
    return 0
  fi
  echo "gate E (the hashed 28 Oct cards: the official score) and the same check on today's cards"
  python3 -I k5_fresh.py --cards "$FROZEN20" --answers ../harness/runs/fresh.jsonl --walls ../data/walls > "$LOGS/03-gateE-frozen.log" 2>&1 || true
  python3 -I k5_fresh.py --cards "$FRESH" --answers ../harness/runs/fresh.jsonl --walls ../data/walls > "$LOGS/03-gateE-current.log" 2>&1 || true
  grep -h "^E fresh" "$LOGS/03-gateE-frozen.log" "$LOGS/03-gateE-current.log" || true
  echo "run_query Cedric (budget $B_RQ) + README call trace"
  python3 -I run_query.py --city stl --set cedric --walls ../data/walls --frozen --budget "$B_RQ" > "$LOGS/03-run_query.log" 2>&1 \
    || { tail -5 "$LOGS/03-run_query.log"; die "run_query"; }
  cp out/query_stl-cedric.json "$LOGS/query_stl-cedric.json"
  python3 -I readme_trace.py --trace out/query_stl-cedric.md --readme "$MAIN/README.md" > "$LOGS/03-readme_trace.txt" 2>&1 \
    || { cat "$LOGS/03-readme_trace.txt"; die "readme_trace"; }
  tail -1 "$LOGS/03-readme_trace.txt" || true
  # the trace must be this run's, on the final engine (no business_rating.min; rows = 'N requests' = the run's calls)
  python3 -I "$MAIN/tools/freeze_numbers.py" tracecheck --readme "$MAIN/README.md" --run-json "$LOGS/query_stl-cedric.json" \
    || die "README call trace check"
  echo "street ablation: the 20 sets without the street walls (budget $B_NS)"
  rm -rf out/walls-no-street out/fresh20-no-street; mkdir -p out/walls-no-street
  python3 -I - "$WT/data/walls" out/walls-no-street <<'PY'
import json, os, sys
src, dst = sys.argv[1:3]
for f in sorted(os.listdir(src)):
    if not f.endswith(".json"):
        continue
    d = json.load(open(os.path.join(src, f)))
    kinds = {a.get("kind") for e in d["walls"] for a in e["answers"]}
    if kinds == {"street"}:
        print("  left out: %s" % f); continue
    os.symlink(os.path.join(src, f), os.path.join(dst, f))
PY
  python3 -I precompute.py --walls out/walls-no-street --sets-file out/sets20.json --accept-top --out out/fresh20-no-street \
    --no-cap --budget "$B_NS" > "$LOGS/03-nostreet.log" 2>&1 || true
  grep -E "^precompute:" "$LOGS/03-nostreet.log" || tail -2 "$LOGS/03-nostreet.log"
  echo "census gems and saturation coverage (stored answers, 0 Qloo calls)"
  (cd "$WT/harness" && python3 -I census_stats.py --gems) > "$LOGS/03-census_gems.log" 2>&1 || true
  (cd "$WT/harness" && python3 -I saturation.py --metrics) > "$LOGS/03-saturation.log" 2>&1 || true
  cd "$MAIN"
  python3 -I tools/freeze_numbers.py numbers --fresh "$FRESH" --nostreet "$E/out/fresh20-no-street" $([ $DRY = 1 ] && echo --dry-run)
  commit_paths "Freeze: k12 table, site wall-effect medians and the README call trace regenerated (counts and request URLs only)" \
    engine/k12_wall_effect.md site/data/wall_effect.json README.md engine/k14_label.md engine/k14_label.json
}

# tracked files a judge may open once the repo is public: no ⟦X⟧ may be left in any of them
JUDGE_FILES="README.md site/*.html agent/*.md server/*.md harness/README.md engine/*.md media/VIDEO-NOTES.md"

step4() {
  say "4 fill devpost -> $QLOO_DIR/devpost.final.md, README.md in place"
  cd "$MAIN"
  python3 -I tools/fill_devpost.py --in "$QLOO_DIR/devpost.md" --out "$QLOO_DIR/devpost.final.md" $([ $DRY = 1 ] && echo --allow-stale)
  # README.md: filled from the same numbers.json (same stale guard), then checked: ⟦LIVE_URL⟧/⟦REPO_URL⟧ are filled
  # with the known URLs; anything else left stops the freeze (the repo goes public at the flip)
  # rerun-safe: once a freeze has filled README.md, the template is that commit's parent (plus this run's call trace)
  local tmpl=README.md last
  last=$(git -C "$MAIN" log -1 --format=%H -- README.md)
  if git -C "$MAIN" log -1 --format=%s "$last" | grep -q "^Freeze: README.md filled"; then
    git -C "$MAIN" show "$last^:README.md" > "$LOGS/README.template.md"; tmpl="$LOGS/README.template.md"
    [ -f "$WT/engine/out/query_stl-cedric.md" ] && python3 -I engine/readme_trace.py --trace "$WT/engine/out/query_stl-cedric.md" \
      --readme "$tmpl" > /dev/null
    echo "README template: $last^ (README.md was filled by an earlier freeze run)"
  fi
  rm -f "$LOGS/README.filled.md"
  python3 -I tools/fill_devpost.py --in "$tmpl" --out "$LOGS/README.filled.md" --whole --report "$LOGS/fill.README.json" \
    $([ $DRY = 1 ] && echo --allow-stale) > "$LOGS/04-fill-readme.txt" 2>&1 || { cat "$LOGS/04-fill-readme.txt"; die "README fill"; }
  grep -vE "^  filled" "$LOGS/04-fill-readme.txt" || true
  # the fill's own header comment is for devpost.final.md only; README gets the body
  python3 -I - "$LOGS/README.filled.md" <<'PY'
import re, sys
p = sys.argv[1]; s = open(p).read()
s = re.sub(r"\A(<!-- STALE PREVIEW .*?-->\n)?<!-- Filled by tools/fill_devpost\.py .*?-->\n\n", "", s, flags=re.S)
s = re.sub(r"^<!-- ⟦X⟧ = .*?-->\n\n?", "", s, flags=re.M)      # the draft's own legend note goes with the fill
open(p, "w").write(s)
PY
  local readme_left judge_left
  python3 -I tools/fill_devpost.py --scan "$LOGS/README.filled.md" > "$LOGS/04-readme-left.txt" && readme_left=0 || readme_left=1
  # shellcheck disable=SC2086
  python3 -I tools/fill_devpost.py --scan $(cd "$MAIN" && ls $JUDGE_FILES | grep -vx README.md) > "$LOGS/04-judge-left.txt" \
    && judge_left=0 || judge_left=1
  cat "$LOGS/04-readme-left.txt" "$LOGS/04-judge-left.txt"
  if [ $DRY = 1 ]; then
    echo "dry run: README.md not overwritten or committed (preview: $LOGS/README.filled.md)"
    return 0
  fi
  [ $readme_left = 0 ] || die "README.md would ship with ⟦X⟧ left (listed above): fill them in numbers.json or reword"
  [ $judge_left = 0 ] || die "tracked files a judge may open still hold ⟦X⟧ (listed above)"
  cp "$LOGS/README.filled.md" "$MAIN/README.md"
  commit_paths "Freeze: README.md filled from out/freeze/numbers.json (no placeholder left)" README.md
}

step5() {
  say "5 Render ($RENDER)"
  case $RENDER in
    skip) echo "render: SKIPPED (--skip-render)" | tee "$LOGS/05-render.log";;
    if-unchanged) python3 -I "$MAIN/tools/render_deploy.py" deploy --if-unchanged 2>&1 | tee "$LOGS/05-render.log"
                  [ "${PIPESTATUS[0]}" = 0 ] || die "render deploy";;
    *) python3 -I "$MAIN/tools/render_deploy.py" deploy 2>&1 | tee "$LOGS/05-render.log"
       [ "${PIPESTATUS[0]}" = 0 ] || die "render deploy";;
  esac
}

step6() {
  say "6 gate F (k11 against $LIVE_URL, 10 runs)"
  if [ $SKIP_F = 1 ]; then echo "gate F: SKIPPED (--skip-f); not measured at this run" | tee "$LOGS/06-gateF.log"; return 0; fi
  grep -q "SKIPPED" "$LOGS/05-render.log" 2>/dev/null && warn "Render was not redeployed at step 5: gate F measures the old deploy"
  [ -d "$WT/engine" ] || die "no regen worktree: run step 2 first"
  ( set -a; . "$HOME/.config/unsaid/env"; set +a
    cd "$WT/engine" && python3 -I k11_latency.py --url "$LIVE_URL/api/unsaid" --city both --runs 10 ) > "$LOGS/06-gateF.log" 2>&1 \
    || { tail -5 "$LOGS/06-gateF.log"; die "k11"; }
  grep -E "⟦P50⟧|^F speed|QLOO" "$LOGS/06-gateF.log" || true
}

step7() {
  say "7 agent re-record, then media (render.sh data images site$([ $WITH_VIDEO = 1 ] && echo " clip video, URL=$LIVE_URL"))"
  if [ $SKIP_AGENT = 1 ]; then
    warn "agent re-record skipped (--skip-agent): the video and the site show the earlier recording"
  else
    # E's scripted MCP session (the video's agent shot) and the Claude run (the site's agent block), against the engine
    # step 5 deployed. A failed recording is loud, not fatal: the old files stay and agentcheck/numbers say so.
    python3 -I "$MAIN/tools/agent_rerecord.py" 2>&1 | tee "$LOGS/07-agent.txt" \
      || warn "agent re-record failed: see $LOGS/07-agent.txt"
  fi
  if [ $SKIP_MEDIA = 1 ]; then echo "media: SKIPPED (--skip-media)" | tee "$LOGS/07-media.log"; return 0; fi
  # The author's rule (30 Oct): no video render unless he asks (--with-video renders the clip and the 60 s video too)
  local targets="data images site"; [ $WITH_VIDEO = 1 ] && targets="data images clip video site"
  : > "$LOGS/07-media.log"
  for t in $targets; do
    (cd "$MAIN/media" && URL=$LIVE_URL zsh render.sh $t) >> "$LOGS/07-media.log" 2>&1 || { tail -8 "$LOGS/07-media.log"; die "render.sh $t"; }
  done
  [ $WITH_VIDEO = 1 ] || echo "video and clip: not rendered (no --with-video; the author's rule)"
  grep -E "\.png$|\.mp4$|video\.json|note:" "$LOGS/07-media.log" | tail -25 || true
  python3 -I "$MAIN/tools/freeze_numbers.py" agentcheck --fresh "$FRESH" | tee "$LOGS/07-agentcheck.log"
  cd "$MAIN"
  commit_paths "Freeze: site and media data rebuilt by media/tools/build_data.py" \
    site/data/census.json site/data/map site/data/walls site/data/try.json site/data/config.json site/data/mock media/data/assistant.json
}

step8() {
  say "8 site deploy (media/tools/deploy-site.sh)"
  if [ $SKIP_SITE = 1 ]; then echo "site: SKIPPED (--skip-site)" | tee "$LOGS/08-site.log"; return 0; fi
  # a dry run checks (OG image + the ⟦ check at both widths) without deploying
  CHECK_ONLY=$([ $DRY = 1 ] && echo 1) zsh "$MAIN/media/tools/deploy-site.sh" > "$LOGS/08-site.log" 2>&1 \
    || { tail -8 "$LOGS/08-site.log"; die "deploy-site.sh"; }
  [ $DRY = 1 ] && echo "site: checked, not deployed (dry run)"
  grep -E "placeholder check|og image|Deployment complete|https://" "$LOGS/08-site.log" | tail -4 || true
}

step9() {
  say "9 report"
  cd "$MAIN"
  python3 -I tools/freeze_numbers.py numbers --fresh "$FRESH" --nostreet "$WT/engine/out/fresh20-no-street" \
    $([ $DRY = 1 ] && echo --dry-run) > "$LOGS/09-numbers.txt"
  python3 -I tools/fill_devpost.py --in "$QLOO_DIR/devpost.md" --out "$QLOO_DIR/devpost.final.md" $([ $DRY = 1 ] && echo --allow-stale) \
    > "$LOGS/09-fill.txt" || { cat "$LOGS/09-fill.txt"; die "devpost fill"; }
  python3 -I tools/freeze_numbers.py report
}

NAMES=(x preflight regen numbers fill render gateF media site report)
echo "freeze: steps $FROM-$TO$([ $DRY = 1 ] && echo ' (DRY RUN: no gate F, no Render; Qloo <= 145)')  logs $LOGS"
for n in $(seq "$FROM" "$TO"); do
  f="$LOGS/done/$(printf '%02d' "$n")-${NAMES[$n]}"
  rm -f "$f"
  # errexit stays on inside the step (a subshell, not an if-condition); a failure anywhere stops the step
  set +e; ( set -e; step$n ) 2>&1 | tee "$LOGS/$(printf '%02d' "$n")-${NAMES[$n]}.step.txt"; rc=${PIPESTATUS[0]}; set -e
  [ "$rc" = 0 ] || { echo "FAIL: step $n (${NAMES[$n]}) exited $rc; see $LOGS. Fix, then ./freeze.sh --from $n"; exit 1; }
  echo "$(date '+%Y-%m-%d %H:%M:%S %Z') ok$([ $DRY = 1 ] && echo ' (dry run)')" > "$f"
done
echo "freeze: done (report: $LOGS/report.txt)"
