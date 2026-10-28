#!/bin/bash
cd "$(dirname "$0")" || exit 1
unset GEMINI_API_KEY GEMINI_MODEL GEMINI_RPM GEMINI_RPD QLOO_API_KEY
caffeinate -i python3 -I search_on.py --nudge --go
python3 -I walls_cli.py build --walls search-on --no-census
python3 -I audit_codex.py
python3 -I search_on.py --report
exec ./saturation.sh >> runs/logs/saturation.log 2>&1
