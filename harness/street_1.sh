#!/bin/bash
# Street asks for every distinct neighbourhood of the frozen 20 sets' cards and reserves (claude + codex, unhinted),
# then build data/walls/street-1.json. Resumable: run it again.
cd "$(dirname "$0")" || exit 1
unset GEMINI_API_KEY GEMINI_MODEL GEMINI_RPM GEMINI_RPD QLOO_API_KEY
caffeinate -i python3 -I walls_cli.py ask --lane claude,codex --wall street-1 --kind street --hoods-file runs/.street-1.hoods.json --go
python3 -I walls_cli.py build --walls street-1 --no-census
python3 -I audit_codex.py
