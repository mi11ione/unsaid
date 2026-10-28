#!/bin/bash
# The Gemini priority queue at 03:05 ET each day through the deadline (Pacific midnight = 03:00 ET).
cd "$(dirname "$0")" || exit 1
for d in "$@"; do
  ./at_et.sh "$d 03:05" ./gemini_batch.sh >> "runs/logs/gemini-$d.log" 2>&1
done
