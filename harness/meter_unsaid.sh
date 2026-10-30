#!/bin/bash
# Post-hoc meter arm (harness/meter_unsaid.md). Released by the author 28 Oct (Render at 469d34a, priors live).
# bench_proxy.py (a free localhost port) adds X-Unsaid-Bench; the agent and the CLIs never see the secret.
cd "$(dirname "$0")" || exit 1
set -a; . ~/.config/unsaid/env; set +a
unset GEMINI_API_KEY GEMINI_MODEL GEMINI_RPM GEMINI_RPD QLOO_API_KEY
PF=runs/.bench_proxy.port; rm -f $PF
BENCH_PROXY_PORTFILE=$PF python3 -I bench_proxy.py 2> runs/logs/bench_proxy.log & PROXY=$!
for i in $(seq 1 20); do [ -s $PF ] && break; sleep 0.5; done
unset UNSAID_BENCH_SECRET PROXY_SECRET
PORT=$(cat $PF 2>/dev/null)
ok=0; for i in 1 2 3 4 5 6; do   # the host may be waking (about a minute on Render)
  curl -sf -m 30 "http://127.0.0.1:$PORT/api/health" | grep -q '"ok": true' && { ok=1; break; }; sleep 10; done
if [ -z "$PORT" ] || [ "$ok" != 1 ]; then
  echo "ABORT: bench proxy not answering /api/health (port '$PORT')"; kill $PROXY 2>/dev/null; exit 1
fi
echo "bench proxy on 127.0.0.1:$PORT"
export UNSAID_URL="http://127.0.0.1:$PORT" UNSAID_BENCH_VIA_PROXY=1
caffeinate -i python3 -I meter.py --lane claude,codex --arm unsaid --go
kill $PROXY
python3 -I audit_codex.py
