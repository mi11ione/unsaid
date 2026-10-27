#!/bin/bash
# One Gemini dated batch: load the key from ~/.config/unsaid/env (never printed), spend today's remaining allowance
# in priority order, then refresh data/walls/census.json so new gem answers reach the server.
cd "$(dirname "$0")" || exit 1
set -a; . ~/.config/unsaid/env; set +a
caffeinate -i python3 -I walls_cli.py queue gemini-priority --go
python3 -I walls_cli.py build --census-only
python3 -I census_stats.py --gems
