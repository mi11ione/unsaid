#!/bin/bash
# street_catchup.sh [--label street-2] DIR [DIR ...]
# Ask Claude + ChatGPT (unhinted street protocol) about every card/reserve neighbourhood in these result directories
# that no street wall has asked yet, then rebuild data/walls/<label>.json and run the leak audit (must be 0 unresolved).
# Resumable and idempotent: run it again after every regeneration. Only city + neighbourhood are read from the results.
cd "$(dirname "$0")" || exit 1
LABEL=street-2; if [ "$1" = "--label" ]; then LABEL="$2"; shift 2; fi
[ $# -ge 1 ] || { echo "usage: $0 [--label street-2] DIR [DIR ...]"; exit 2; }
unset GEMINI_API_KEY GEMINI_MODEL GEMINI_RPM GEMINI_RPD QLOO_API_KEY
python3 -I street_catchup.py --label "$LABEL" "$@" || { echo "nothing new to ask"; exit 0; }
caffeinate -i python3 -I walls_cli.py ask --lane claude,codex --wall "$LABEL" --kind street --hoods-file "runs/.$LABEL.hoods.json" --go
python3 -I walls_cli.py build --walls "$LABEL" --no-census
python3 -I audit_codex.py | tee /dev/stderr | awk '/unresolved ids [1-9]/{bad=1} END{exit bad}' || { echo "AUDIT: unresolved codex tool use"; exit 1; }
