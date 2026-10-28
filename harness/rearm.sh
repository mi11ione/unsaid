#!/bin/zsh -l
# Arm every scheduled harness job that has neither finished nor a waiter already running. Safe to run any number of
# times: each job is resumable (stored answers are never re-asked) and leaves runs/done/<id> when it completes.
# launchd runs this at login (~/Library/LaunchAgents/io.mi11ion.unsaid.rearm.plist), so a reboot re-arms the jobs;
# a job whose time passed while the Mac was off fires at once.
cd "$(dirname "$0")" || exit 1
mkdir -p runs/done runs/logs
JOBS=(
  "gem-29|2026-10-29 03:05|./gemini_batch.sh|runs/logs/gemini-2026-10-29.log"
  "wall-2|2026-10-29 09:00|./wall_day.sh 2|runs/logs/wall-2.log"
  "gem-30|2026-10-30 03:05|./gemini_batch.sh|runs/logs/gemini-2026-10-30.log"
  "wall-3|2026-10-30 09:00|./wall_day.sh 3|runs/logs/wall-3.log"
)
for j in "${JOBS[@]}"; do
  IFS='|' read -r id when cmd log <<< "$j"
  [ -f "runs/done/$id" ] && continue
  if pgrep -f "unsaid-job $id" >/dev/null; then continue; fi
  echo "[rearm] $(date '+%F %T') arming $id at $when ET: $cmd" >> runs/logs/rearm.log
  nohup zsh -lc "exec -a 'unsaid-job $id' zsh -lc './at_et.sh \"$when\" $cmd && touch runs/done/$id'" >> "$log" 2>&1 < /dev/null &!
done
