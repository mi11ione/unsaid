#!/bin/bash
# SEARCH-ON lane: ask, build data/walls/search-on.json, audit (apps/shell only), report. Resumable.
cd "$(dirname "$0")" || exit 1
unset GEMINI_API_KEY GEMINI_MODEL GEMINI_RPM GEMINI_RPD QLOO_API_KEY
caffeinate -i python3 -I search_on.py --go
python3 -I walls_cli.py build --walls search-on --no-census
python3 -I audit_codex.py
python3 -I search_on.py --report
