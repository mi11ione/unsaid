#!/bin/bash
# 28 Oct: finish the ChatGPT street asks, re-ask every codex answer that used a tool, rebuild the served walls, audit.
cd "$(dirname "$0")" || exit 1
set -a; . ~/.config/unsaid/env; set +a   # QLOO_API_KEY for the meter "with" arm re-asks only
unset GEMINI_API_KEY GEMINI_MODEL GEMINI_RPM GEMINI_RPD
export UNSAID_MODE=live UNSAID_WALLS="$(cd ../data/walls && pwd)"
caffeinate -i python3 -I walls_cli.py ask --lane codex --wall street-1 --kind street --hoods-file runs/.street-1.hoods.json --go
caffeinate -i python3 -I audit_codex.py --fix
python3 -I walls_cli.py build --walls street-1 --no-census
python3 -I walls_cli.py build --walls 1 --no-census
python3 -I walls_cli.py build --census-only
python3 -I audit_codex.py
