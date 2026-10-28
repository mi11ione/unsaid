#!/bin/bash
# SATURATION batches (claude + codex), then data/walls/sat.json, census.json, the audit, cards named. Resumable.
cd "$(dirname "$0")" || exit 1
unset GEMINI_API_KEY GEMINI_MODEL GEMINI_RPM GEMINI_RPD QLOO_API_KEY
caffeinate -i python3 -I saturation.py --go
python3 -I walls_cli.py build --walls sat --no-census
python3 -I walls_cli.py build --census-only
python3 -I audit_codex.py
python3 -I saturation.py --cards
