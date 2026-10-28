#!/bin/bash
# One Gemini dated batch: load the key from ~/.config/unsaid/env (never printed), spend today's remaining allowance
# per model (16/day each): the primary lane's priority queue, then the 32 census gem asks on a second free-tier
# model (stored separately), then refresh data/walls/census.json and print the gem counts.
cd "$(dirname "$0")" || exit 1
set -a; . ~/.config/unsaid/env; set +a
unset QLOO_API_KEY
caffeinate -i python3 -I walls_cli.py queue gemini-priority --go
caffeinate -i python3 -I walls_cli.py queue gemini-gems --model "${GEMINI_GEMS_MODEL:-gemini-3.6-flash}" --go
python3 -I walls_cli.py build --census-only
python3 -I census_stats.py --gems
