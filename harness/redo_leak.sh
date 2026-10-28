#!/bin/bash
# After fresh v1: redo every codex answer that leaked through codex_apps, then rebuild the served walls.
cd "$(dirname "$0")" || exit 1
unset GEMINI_API_KEY GEMINI_MODEL GEMINI_RPM GEMINI_RPD QLOO_API_KEY
caffeinate -i python3 -I audit_codex.py --fix
python3 -I audit_codex.py                       # must show 0 unresolved everywhere
python3 -I walls_cli.py build --walls 1
python3 -I census_stats.py --gems
