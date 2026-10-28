#!/bin/bash
# Dated wall N: the 20 city phrasings for STL and NYC + taste for the try-these sets (walls_cli's rule for N != 1),
# claude + codex (--disable apps). Then data/walls/wall-N.json, census.json, the leak audit. Resumable.
N="$1"; cd "$(dirname "$0")" || exit 1
unset GEMINI_API_KEY GEMINI_MODEL GEMINI_RPM GEMINI_RPD QLOO_API_KEY
python3 -I walls_cli.py ask --lane claude,codex --wall "$N" --go
python3 -I walls_cli.py build --walls "$N" --no-census
python3 -I walls_cli.py build --census-only
python3 -I audit_codex.py
