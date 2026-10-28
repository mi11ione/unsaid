#!/bin/bash
# Post-hoc meter arm (harness/meter_unsaid.md): run ONLY after the orchestrator confirms D's ranking change is deployed.
cd "$(dirname "$0")" || exit 1
set -a; . ~/.config/unsaid/env; set +a
export UNSAID_BENCH="${UNSAID_BENCH_SECRET:-$PROXY_SECRET}"     # sent only if agent/unsaid_mcp.py supports it
unset GEMINI_API_KEY GEMINI_MODEL GEMINI_RPM GEMINI_RPD QLOO_API_KEY UNSAID_BENCH_SECRET PROXY_SECRET
caffeinate -i python3 -I meter.py --lane claude,codex --arm unsaid --go
python3 -I audit_codex.py
