#!/bin/bash
# E-style asks for all 20 sets (claude + codex), then data/walls/e1.json, the leak audit, the card counts. Resumable.
cd "$(dirname "$0")" || exit 1
unset GEMINI_API_KEY GEMINI_MODEL GEMINI_RPM GEMINI_RPD QLOO_API_KEY
caffeinate -i python3 -I sets_e.py --go
python3 -I walls_cli.py build --walls e1 --no-census
python3 -I audit_codex.py
python3 -I sets_e.py --count
