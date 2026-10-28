#!/bin/bash
# Gate E then gate D on the claude and codex lanes (Gemini excluded: free tier). Resumable: run it again.
cd "$(dirname "$0")" || exit 1
unset GEMINI_API_KEY GEMINI_MODEL GEMINI_RPM GEMINI_RPD
caffeinate -i python3 -I fresh_asks.py --lane claude,codex --go > runs/logs/fresh.log 2>&1
set -a; . ~/.config/unsaid/env; set +a
unset GEMINI_API_KEY GEMINI_MODEL GEMINI_RPM GEMINI_RPD   # the meter needs only QLOO_API_KEY
export UNSAID_MODE=live UNSAID_WALLS="$(cd ../data/walls && pwd)"
caffeinate -i python3 -I meter.py --lane claude,codex --go > runs/logs/meter.log 2>&1
