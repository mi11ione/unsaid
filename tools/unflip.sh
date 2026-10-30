#!/usr/bin/env bash
# Undo step 3 of tools/flip.sh in case of abuse: the API and /mcp require the UNSAID token again.
#
#   tools/unflip.sh            # UNSAID_TOKEN_REQUIRED=1 on Render, redeploy the live commit, check a token-less
#                              # /mcp call gets 401 and a call with the token still works
#   tools/unflip.sh --limit N  # gentler: keep it open but set UNSAID_FRESH_PER_HOUR=N (fresh runs per IP per hour)
#
# The repo stays public (that is not undone here). After a full unflip the site needs ?token=... again, so the Devpost
# testing instructions must carry the token. Re-open with tools/flip.sh (its finished steps are skipped).
# Secrets come from ~/.config/unsaid/env and are never printed.
set -uo pipefail

SERVICE="${RENDER_SERVICE:-srv-dbgr3fuc6qcc73ce5p3g}"
RAPI="https://api.render.com/v1/services/$SERVICE"
SITE="https://unsaid.mi11ion.io"
ENVF="$HOME/.config/unsaid/env"
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"

KEY=UNSAID_TOKEN_REQUIRED VAL=1
case "${1:-}" in
  "") ;;
  --limit) [[ "${2:-}" =~ ^[0-9]+$ ]] || { echo "usage: tools/unflip.sh [--limit N]"; exit 2; }; KEY=UNSAID_FRESH_PER_HOUR VAL="$2" ;;
  -h|--help) sed -n '2,11p' "$0"; exit 0 ;;
  *) echo "usage: tools/unflip.sh [--limit N]"; exit 2 ;;
esac

TMP="$(mktemp -d)"; chmod 700 "$TMP"; trap 'rm -rf "$TMP"' EXIT
die() { printf '\n  STOP  %s\n' "$1"; shift; for l in "$@"; do printf '        -> %s\n' "$l"; done; exit 1; }
ok()  { printf '  ok    %s\n' "$*"; }
envval() { [ -n "${!1:-}" ] && { printf '%s' "${!1}"; return; }; [ -f "$ENVF" ] || return 0
           sed -n "s/^$1=//p" "$ENVF" | tail -1 | sed -e "s/^[\"']//" -e "s/[\"']\$//"; }
jq_py() { python3 -I -c "import json,sys
d=json.load(sys.stdin)
$1"; }
printf 'Authorization: Bearer %s\n' "$(envval RENDER_API_KEY)" > "$TMP/h_render"
printf 'Authorization: Bearer %s\n' "$(envval UNSAID_TOKEN)" > "$TMP/h_token"
chmod 600 "$TMP"/h_*; : > "$TMP/h_none"

render() { local args=(-sS -m 60 -X "$1" -H @"$TMP/h_render" -H "Accept: application/json" -o "$TMP/rbody" -w '%{http_code}')
           [ -n "${3:-}" ] && args+=(-H "Content-Type: application/json" --data "$3")
           curl "${args[@]}" "$RAPI$2" > "$TMP/rcode" 2>/dev/null || echo 000 > "$TMP/rcode"; cat "$TMP/rbody" 2>/dev/null; }
mcp_code() { curl -sS -m 60 -A "$UA" -X POST -H @"$1" -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
             -o /dev/null -w '%{http_code}' --data '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"unsaid-unflip-check","version":"1.0"}}}' \
             "$SITE/mcp" 2>/dev/null || echo 000; }

echo "== Render: $KEY=$VAL"
render GET "/env-vars/UNSAID_TOKEN" | jq_py 'sys.exit(0 if d.get("value") else 1)' 2>/dev/null \
  || die "UNSAID_TOKEN is not set on Render (HTTP $(cat "$TMP/rcode")): requiring it would lock everyone out" "Render -> Environment"
render PUT "/env-vars/$KEY" "{\"value\":\"$VAL\"}" > /dev/null    # per-key: the other vars are untouched
case "$(cat "$TMP/rcode")" in 200|201) ok "$KEY=$VAL set" ;; *) die "PUT $KEY answered HTTP $(cat "$TMP/rcode")" \
  "Render dashboard -> unsaid-engine -> Environment -> $KEY = $VAL -> Save, then Manual Deploy" ;; esac

commit="$(render GET "/deploys?limit=10" | jq_py '
for x in d:
    x = x.get("deploy", x)
    if x.get("status") == "live":
        print((x.get("commit") or {}).get("id", "")); break')"
body='{"clearCache":"do_not_clear"}'; [ -n "$commit" ] && body="{\"clearCache\":\"do_not_clear\",\"commitId\":\"$commit\"}"
id="$(render POST /deploys "$body" | jq_py 'print((d.get("deploy") or d).get("id",""))' 2>/dev/null)"
[ -n "$id" ] || die "deploy POST answered HTTP $(cat "$TMP/rcode")" "Render dashboard -> Manual Deploy"
ok "deploy $id started (commit ${commit:0:7}, the live one)"
t0=$SECONDS st=""
while [ $((SECONDS - t0)) -lt 1200 ]; do
  sleep 15
  st="$(render GET "/deploys/$id" | jq_py 'print((d.get("deploy") or d).get("status",""))' 2>/dev/null)"
  printf '        deploy %s: %s (%ds)\n' "$id" "$st" $((SECONDS - t0))
  case "$st" in live) break ;; build_failed|update_failed|canceled|deactivated|pre_deploy_failed) die "deploy $id: $st" "Render -> Logs" ;; esac
done
[ "$st" = live ] || die "deploy $id not live after 20 min ($st)" "Render -> Events"

echo "== check"
t0=$SECONDS
until curl -sS -m 60 -A "$UA" "$SITE/api/health" 2>/dev/null | jq_py 'sys.exit(0 if d.get("ok") else 1)' 2>/dev/null; do
  [ $((SECONDS - t0)) -gt 600 ] && die "/api/health not ok 10 min after the deploy went live"; sleep 10
done
ok "/api/health ok"
if [ "$KEY" = UNSAID_TOKEN_REQUIRED ]; then
  t0=$SECONDS
  until [ "$(mcp_code "$TMP/h_none")" = 401 ]; do
    [ $((SECONDS - t0)) -gt 180 ] && die "/mcp still answers without a token" "Render -> Environment: is UNSAID_TOKEN_REQUIRED 1?"; sleep 10
  done
  ok "/mcp without a token: 401"
  [ "$(mcp_code "$TMP/h_token")" = 200 ] && ok "/mcp with the token: 200" || die "/mcp with the token does not answer 200"
  echo "UNFLIPPED: the token is required again. The site needs $SITE/?token=... ; put the token back in the Devpost testing instructions."
else
  ok "open, limited to $VAL fresh runs per IP per hour (a token holder keeps its own bucket)"
fi
