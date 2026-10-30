#!/usr/bin/env bash
# The flip (30 Oct, ~21:30 ET): the repo goes public and the API and /mcp stop requiring the UNSAID token.
#
#   tools/flip.sh --preflight-only   # step 1 only: read-only checks (git, README, prereg hashes, secrets, gh, Render)
#   tools/flip.sh --verify-only      # step 4 only: the open API, /mcp, the site, keepwarm (no changes)
#   tools/flip.sh --verify-only --with-token   # step 4 as a rehearsal before the flip (sends the token as a header)
#   tools/flip.sh                    # all steps; asks for "flip" first (--yes skips the question)
#
# Steps, in order; the first failure stops with what to do. Every step checks before it acts, so a re-run after a
# fix picks up where it stopped (an already-public repo, an env var already 0 or a server already open are skipped).
#   1. preflight   2. GitHub repo public + licence   3. Render UNSAID_TOKEN_REQUIRED=0 (UNSAID_TOKEN kept), redeploy
#   4. verify without a token   5. Roman's Devpost checklist
# Undo step 3 (token required again): tools/unflip.sh. Secrets come from ~/.config/unsaid/env and are never printed:
# they go to curl through header files in a private temp dir, never on a command line.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO="mi11ione/unsaid"
SERVICE="${RENDER_SERVICE:-srv-dbgr3fuc6qcc73ce5p3g}"
RAPI="https://api.render.com/v1/services/$SERVICE"
SITE="https://unsaid-ang.pages.dev"
ENVF="$HOME/.config/unsaid/env"
DEVPOST="$(dirname "$ROOT")/devpost.final.md"
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
# the fresh query: St. Louis, three typed loves (the hero set, as typed text with type hints, not the static preset)
LOVES='[["Frankie Beverly & Maze","artist"],["The Original Kings of Comedy","movie"],["rib tips","tag"]]'

MODE=all WITH_TOKEN=0 YES=0
for a in "$@"; do
  case "$a" in
    --preflight-only) MODE=preflight ;;
    --verify-only) MODE=verify ;;
    --with-token) WITH_TOKEN=1 ;;
    --yes) YES=1 ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    *) echo "unknown option: $a (see --help)"; exit 2 ;;
  esac
done

TMP="$(mktemp -d)"; chmod 700 "$TMP"
trap 'rm -rf "$TMP"' EXIT

say()  { printf '%s\n' "$*"; }
ok()   { printf '  ok    %s\n' "$*"; }
warn() { printf '  WARN  %s\n' "$*"; }
step() { printf '\n== %s\n' "$*"; }
die()  { printf '\n  STOP  %s\n' "$1"; shift; for l in "$@"; do printf '        -> %s\n' "$l"; done
         printf '\n  Fix it and re-run tools/flip.sh: finished steps are checked and skipped.\n'; exit 1; }

envval() {  # one value from ~/.config/unsaid/env (KEY=value, optional quotes); never echoed to the terminal
  [ -n "${!1:-}" ] && { printf '%s' "${!1}"; return; }
  [ -f "$ENVF" ] || return 0
  sed -n "s/^$1=//p" "$ENVF" | tail -1 | sed -e "s/^[\"']//" -e "s/[\"']\$//"
}
jq_py() { python3 -I -c "import json,sys
d=json.load(sys.stdin)
$1"; }

# header files (mode 600, in $TMP) so the secrets never show on a command line or in `ps`
RKEY="$(envval RENDER_API_KEY)"; TOKEN="$(envval UNSAID_TOKEN)"
printf 'Authorization: Bearer %s\n' "$RKEY" > "$TMP/h_render"
printf 'Authorization: Bearer %s\n' "$TOKEN" > "$TMP/h_token"
chmod 600 "$TMP"/h_*
: > "$TMP/h_none"
AUTH_H="$TMP/h_none"; [ "$WITH_TOKEN" = 1 ] && AUTH_H="$TMP/h_token"

render() {  # render METHOD PATH [JSON] -> body on stdout, HTTP code in $TMP/rcode
  local m="$1" p="$2" b="${3:-}"
  local args=(-sS -m 60 -X "$m" -H @"$TMP/h_render" -H "Accept: application/json" -o "$TMP/rbody" -w '%{http_code}')
  [ -n "$b" ] && args+=(-H "Content-Type: application/json" --data "$b")
  curl "${args[@]}" "$RAPI$p" > "$TMP/rcode" 2>"$TMP/rerr" || echo 000 > "$TMP/rcode"
  cat "$TMP/rbody" 2>/dev/null
}
rcode() { cat "$TMP/rcode"; }

health_ok() {  # the engine through the Pages proxy: ok, live mode, both priors (as tools/render_deploy.py checks)
  curl -sS -m 60 -A "$UA" "$SITE/api/health" 2>/dev/null | jq_py '
ok = d.get("ok") and d.get("mode") == "live" and all((d.get("priors") or {}).get(c) for c in ("stl","nyc"))
print("mode %s, engine %s, priors %s, uptime %ss, rss %s MB" % (d.get("mode"), d.get("engine_v"), d.get("priors"),
      d.get("uptime_s"), d.get("rss_mb")))
sys.exit(0 if ok else 1)' 2>/dev/null
}

mcp() {  # mcp HEADERFILE JSON [protocol version] -> body on stdout, HTTP code in $TMP/mcode
  local args=(-sS -m 60 -A "$UA" -X POST -H @"$1" -H "Content-Type: application/json"
              -H "Accept: application/json, text/event-stream" -o "$TMP/mbody" -w '%{http_code}' --data "$2")
  [ -n "${3:-}" ] && args+=(-H "MCP-Protocol-Version: $3")
  curl "${args[@]}" "$SITE/mcp" > "$TMP/mcode" 2>/dev/null || echo 000 > "$TMP/mcode"
  cat "$TMP/mbody" 2>/dev/null
}
INIT='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"unsaid-flip-check","version":"1.0"}}}'
open_now() {  # 0 when /mcp answers initialize WITHOUT a token (the server no longer requires one)
  mcp "$TMP/h_none" "$INIT" >/dev/null; [ "$(cat "$TMP/mcode")" = 200 ]
}

# ------------------------------------------------------------------------------------------------ 1. preflight
preflight() {
  step "1. preflight (read-only)"
  local fail=0 f
  cd "$ROOT" || die "cannot cd to $ROOT"

  local br; br="$(git rev-parse --abbrev-ref HEAD)"
  [ "$br" = main ] && ok "on main" || { warn "on branch $br, not main"; fail=1; }
  if git diff --quiet && git diff --cached --quiet; then ok "no uncommitted changes to tracked files"
  else warn "uncommitted changes to tracked files:"; git status --short --untracked-files=no | sed 's/^/          /'; fail=1; fi
  local un; un="$(git ls-files --others --exclude-standard | wc -l | tr -d ' ')"
  [ "$un" = 0 ] || warn "$un untracked file(s) (not published, not blocking): $(git ls-files --others --exclude-standard | head -3 | tr '\n' ' ')"
  if git fetch -q origin main 2>"$TMP/ferr"; then
    local h o; h="$(git rev-parse HEAD)"; o="$(git rev-parse origin/main)"
    [ "$h" = "$o" ] && ok "HEAD ${h:0:7} = origin/main (pushed)" || { warn "HEAD ${h:0:7} != origin/main ${o:0:7}: push or pull first"; fail=1; }
  else warn "git fetch failed: $(head -1 "$TMP/ferr")"; fail=1; fi

  local n; n="$(grep -c '⟦' README.md || true)"
  [ "$n" = 0 ] && ok "README.md has no ⟦ placeholders" || { warn "README.md still has $n line(s) with ⟦:"; grep -n '⟦' README.md | cut -c1-120 | sed 's/^/          /'; fail=1; }

  if python3 -I tools/freeze_numbers.py prereg > "$TMP/prereg" 2>&1 && [ "$(grep -c ' ok$' "$TMP/prereg")" = 5 ]; then
    ok "the 5 pre-registered hashes match data/prereg/SHA256SUMS (the public gist)"
  else warn "pre-registered hashes:"; sed 's/^/          /' "$TMP/prereg"; fail=1; fi

  # secrets: 1. the real values from ~/.config/unsaid/env, in every tracked file AND all of history (public soon);
  # 2. common key shapes in tracked files. Only file names are printed, never a match.
  : > "$TMP/secrets"; chmod 600 "$TMP/secrets"
  for k in RENDER_API_KEY UNSAID_TOKEN PROXY_SECRET UNSAID_BENCH_SECRET QLOO_API_KEY GEMINI_API_KEY; do
    v="$(envval "$k")"; [ "${#v}" -ge 12 ] && printf '%s\n' "$v" >> "$TMP/secrets"
  done
  if [ -s "$TMP/secrets" ]; then
    f="$(git grep -l -I -F -f "$TMP/secrets" HEAD 2>/dev/null | sed 's/^HEAD://')"
    [ -z "$f" ] && ok "no secret value from ~/.config/unsaid/env in tracked files" || { warn "a secret VALUE is in: $f"; fail=1; }
    local hits; hits="$(git log --all -p --no-color 2>/dev/null | grep -c -F -f "$TMP/secrets" || true)"
    [ "$hits" = 0 ] && ok "no secret value anywhere in git history ($(git rev-list --all --count) commits)" \
      || { warn "a secret VALUE appears $hits time(s) in git history: rotate that key before going public"; fail=1; }
  else warn "no secrets read from $ENVF (cannot check values)"; fail=1; fi
  local pat='AIza[0-9A-Za-z_-]{35}|rnd_[A-Za-z0-9]{20,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{20,}|sk-ant-[A-Za-z0-9_-]{20,}|sk-(proj-)?[A-Za-z0-9]{32,}|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{10,}|-----BEGIN [A-Z ]*PRIVATE KEY-----'
  f="$(git grep -l -I -E "$pat" HEAD 2>/dev/null | sed 's/^HEAD://')"
  [ -z "$f" ] && ok "no key-shaped strings in tracked files (Google, Render, GitHub, Anthropic, OpenAI, AWS, Slack, PEM)" \
    || { warn "key-shaped strings in: $(echo $f)  (check each; this script prints no matches)"; fail=1; }
  f="$(git ls-files | grep -E '(^|/)\.env($|\.)|\.pem$|\.key$|(^|/)auth\.json$|\.dev\.vars$' || true)"
  [ -z "$f" ] && ok "no .env/.pem/.key/auth.json files tracked" || { warn "secret-looking files tracked: $f"; fail=1; }

  # tools the next steps need
  if gh auth status -h github.com > "$TMP/gh" 2>&1; then
    grep -q "'repo'" "$TMP/gh" && ok "gh signed in, token has the repo scope" || { warn "gh token lacks the 'repo' scope: gh auth refresh -s repo"; fail=1; }
    grep -q "'workflow'" "$TMP/gh" || warn "gh token lacks the 'workflow' scope (needed only to enable/run keepwarm): gh auth refresh -s workflow"
  else warn "gh is not signed in: gh auth login"; fail=1; fi
  local vis; vis="$(gh repo view "$REPO" --json visibility --jq .visibility 2>/dev/null)"
  [ -n "$vis" ] && ok "gh can see $REPO (now $vis)" || { warn "gh cannot read $REPO"; fail=1; }

  [ -n "$RKEY" ] || { warn "RENDER_API_KEY not in $ENVF"; fail=1; }
  render GET "/env-vars?limit=100" > "$TMP/envs"
  if [ "$(rcode)" = 200 ]; then
    jq_py '
e = {(x.get("envVar") or x)["key"]: (x.get("envVar") or x).get("value") for x in d}
print("%d vars; UNSAID_TOKEN %s; UNSAID_TOKEN_REQUIRED %s" % (len(e), "set" if e.get("UNSAID_TOKEN") else "MISSING",
      repr(e["UNSAID_TOKEN_REQUIRED"]) if "UNSAID_TOKEN_REQUIRED" in e else "unset (= required)"))
sys.exit(0 if e.get("UNSAID_TOKEN") else 1)' < "$TMP/envs" > "$TMP/envsum" \
      && ok "Render env-var GET works: $(cat "$TMP/envsum")" || { warn "Render env: $(cat "$TMP/envsum")"; fail=1; }
  else warn "Render env-var GET answered HTTP $(rcode): check RENDER_API_KEY"; fail=1; fi
  if python3 -I tools/render_deploy.py status > "$TMP/rstat" 2>&1; then
    grep -q "changed since: 0 files" "$TMP/rstat" && ok "$(cat "$TMP/rstat")" \
      || warn "$(cat "$TMP/rstat")  (the flip redeploys the LIVE commit, not origin/main; ship code with tools/render_deploy.py deploy)"
  else warn "render_deploy.py status failed: $(tail -1 "$TMP/rstat")"; fi
  local hs; hs="$(health_ok)" && ok "engine healthy through $SITE: $hs" || warn "engine health not ok yet (cold start?): $hs"

  [ "$fail" = 0 ] || die "preflight failed (the WARN lines above)" \
    "commit or stash tracked changes; git push; fill README placeholders; fix any secret before the repo goes public"
  say "  preflight passed"
}

# ------------------------------------------------------------------------------------------------ 2. GitHub public
go_public() {
  step "2. GitHub: $REPO public"
  local vis; vis="$(gh repo view "$REPO" --json visibility --jq .visibility 2>/dev/null)"
  if [ "$vis" = PUBLIC ]; then ok "already public"
  else
    gh repo edit "$REPO" --visibility public --accept-visibility-change-consequences \
      || die "gh repo edit failed" "check gh auth status (needs the repo scope and admin on $REPO)" \
             "or: GitHub -> $REPO -> Settings -> Danger Zone -> Change visibility -> Public"
    for _ in 1 2 3 4 5 6; do
      vis="$(gh repo view "$REPO" --json visibility --jq .visibility 2>/dev/null)"; [ "$vis" = PUBLIC ] && break; sleep 5
    done
    [ "$vis" = PUBLIC ] && ok "visibility PUBLIC" || die "visibility still '$vis' after the edit" "check the repo settings page"
  fi
  local lic; lic="$(gh api "repos/$REPO/license" --jq '.license.spdx_id' 2>/dev/null)"
  [ "$lic" = MIT ] && ok "licence detected: MIT" \
    || warn "licence detected as '${lic:-none}', not MIT (not blocking; GitHub re-detects after a push to LICENSE)"
  local code; code="$(curl -s -o /dev/null -w '%{http_code}' -A "$UA" "https://github.com/$REPO")"
  [ "$code" = 200 ] && ok "https://github.com/$REPO opens without signing in" || warn "https://github.com/$REPO answered $code anonymously"
}

# ------------------------------------------------------------------------------------------------ 3. Render token off
wait_deploy() {  # wait_deploy DEPLOY_ID -> 0 once live
  local id="$1" st="" t0=$SECONDS
  while [ $((SECONDS - t0)) -lt 1200 ]; do
    sleep 15
    st="$(render GET "/deploys/$id" | jq_py 'print((d.get("deploy") or d).get("status",""))' 2>/dev/null)"
    printf '        deploy %s: %s (%ds)\n' "$id" "$st" $((SECONDS - t0))
    case "$st" in
      live) return 0 ;;
      build_failed|update_failed|canceled|deactivated|pre_deploy_failed) return 1 ;;
    esac
  done
  return 1
}

token_off() {
  step "3. Render: UNSAID_TOKEN_REQUIRED=0 (UNSAID_TOKEN kept), redeploy"
  render GET "/env-vars?limit=100" > "$TMP/envs_before"
  [ "$(rcode)" = 200 ] || die "Render env-var GET answered HTTP $(rcode)" "check RENDER_API_KEY in $ENVF"
  local before; before="$(jq_py 'print(len(d))' < "$TMP/envs_before")"
  local cur; cur="$(render GET /env-vars/UNSAID_TOKEN_REQUIRED | jq_py 'print(d.get("value",""))' 2>/dev/null)"
  local changed=0
  if [ "$cur" = 0 ]; then ok "UNSAID_TOKEN_REQUIRED is already 0"
  else
    # the per-key endpoint adds or updates this one var and leaves the others alone (no full-list PUT)
    render PUT /env-vars/UNSAID_TOKEN_REQUIRED '{"value":"0"}' > /dev/null
    [ "$(rcode)" = 200 ] || [ "$(rcode)" = 201 ] || die "PUT UNSAID_TOKEN_REQUIRED answered HTTP $(rcode)" \
      "Render dashboard -> unsaid-engine -> Environment -> add UNSAID_TOKEN_REQUIRED = 0 -> Save (no rebuild needed), then re-run"
    ok "UNSAID_TOKEN_REQUIRED set to 0"; changed=1
  fi
  render GET "/env-vars?limit=100" > "$TMP/envs_after"
  BEFORE="$before" jq_py '
import os
e = {(x.get("envVar") or x)["key"]: (x.get("envVar") or x).get("value") for x in d}
b = int(os.environ["BEFORE"])
assert e.get("UNSAID_TOKEN"), "UNSAID_TOKEN is gone"
assert e.get("UNSAID_TOKEN_REQUIRED") == "0", "UNSAID_TOKEN_REQUIRED is %r" % e.get("UNSAID_TOKEN_REQUIRED")
assert len(e) >= b, "vars went from %d to %d" % (b, len(e))
print("%d vars (was %d); UNSAID_TOKEN still set; UNSAID_TOKEN_REQUIRED=0" % (len(e), b))' < "$TMP/envs_after" > "$TMP/envchk" 2>&1 \
    && ok "$(cat "$TMP/envchk")" || die "env check after the PUT: $(tail -1 "$TMP/envchk")" "check Render -> Environment by hand"

  if [ "$changed" = 0 ] && open_now; then ok "the live server already answers /mcp without a token: no redeploy needed"; return; fi
  # redeploy the commit that is live now, so the flip changes the env and nothing else
  local commit; commit="$(render GET "/deploys?limit=10" | jq_py '
for x in d:
    x = x.get("deploy", x)
    if x.get("status") == "live":
        print((x.get("commit") or {}).get("id", "")); break')"
  local body='{"clearCache":"do_not_clear"}'
  [ -n "$commit" ] && body="{\"clearCache\":\"do_not_clear\",\"commitId\":\"$commit\"}"
  local id; id="$(render POST /deploys "$body" | jq_py 'print((d.get("deploy") or d).get("id",""))' 2>/dev/null)"
  [ -n "$id" ] || die "deploy POST answered HTTP $(rcode)" "Render dashboard -> unsaid-engine -> Manual Deploy -> Deploy latest commit, then re-run"
  ok "deploy $id started (commit ${commit:0:7}, the live one)"
  wait_deploy "$id" || die "deploy $id did not go live" "Render dashboard -> unsaid-engine -> Events/Logs; the old instance keeps serving meanwhile" \
    "re-run tools/flip.sh once it is live (the env var is already 0)"
  local t0=$SECONDS hs=""
  until hs="$(health_ok)"; do
    [ $((SECONDS - t0)) -gt 600 ] && die "deploy live but /api/health not ok after 10 min: $hs" "curl -s $SITE/api/health"
    sleep 10
  done
  ok "/api/health ok: $hs"
  t0=$SECONDS
  until open_now; do
    [ $((SECONDS - t0)) -gt 180 ] && die "/mcp still answers HTTP $(cat "$TMP/mcode") without a token" \
      "Render -> Environment: is UNSAID_TOKEN_REQUIRED exactly 0? then redeploy and re-run"
    sleep 10
  done
  ok "the server no longer requires the token"
}

# ------------------------------------------------------------------------------------------------ 4. verify
verify() {
  local how="WITHOUT a token"; [ "$WITH_TOKEN" = 1 ] && how="WITH the token as a header (rehearsal)"
  step "4. verify $how, browser User-Agent"
  local hs; hs="$(health_ok)" && ok "GET $SITE/api/health: $hs" || die "GET /api/health not ok: $hs" "curl -s $SITE/api/health"

  # the site's first call (on blur): resolve the city
  local code; code="$(curl -sS -m 60 -A "$UA" -H @"$AUTH_H" -o "$TMP/res" -w '%{http_code}' "$SITE/api/resolve?kind=city&q=St.%20Louis")"
  [ "$code" = 200 ] && ok "GET /api/resolve?kind=city&q=St. Louis: $(jq_py 'print(d.get("status"), (d.get("city") or {}).get("slug"))' < "$TMP/res" 2>/dev/null)" \
    || die "GET /api/resolve answered HTTP $code: $(head -c 200 "$TMP/res")" "if 401: the token is still required (step 3)"

  # one fresh query: St. Louis, three typed loves -> 7 cards
  local enc; enc="$(python3 -I -c 'import sys,urllib.parse; print(urllib.parse.quote(sys.argv[1]))' "$LOVES")"
  local try out
  for try in 1 2 3; do
    code="$(curl -sS -N -m 240 -A "$UA" -H @"$AUTH_H" -H "Accept: application/x-ndjson" -o "$TMP/run" -w '%{http_code}' \
            "$SITE/api/unsaid?city=st-louis&loves=$enc")"
    out="$(tail -n 1 "$TMP/run" | jq_py '
r = d.get("result") or d
print(r.get("status"), len(r.get("picks") or []), "cached" if r.get("cached") else "fresh",
      (r.get("diag") or {}).get("qloo_calls"), r.get("retry_after"), ",".join(r.get("flags") or []) or "-")' 2>/dev/null)"
    set -- $out
    [ "$code" = 200 ] && [ "${1:-}" = ok ] && [ "${2:-}" = 7 ] && break
    case "${1:-}" in waking|queued|ranking) say "        try $try: $1, waiting 30 s"; sleep 30 ;; *) break ;; esac
  done
  [ "$code" = 200 ] && [ "${1:-}" = ok ] && [ "${2:-}" = 7 ] \
    && ok "GET /api/unsaid (St. Louis, 3 typed loves): status ok, 7 cards, $3, qloo_calls $4, flags $6" \
    || die "GET /api/unsaid: HTTP $code, status ${1:-?}, ${2:-?} cards, retry_after ${5:-}" \
           "the last line: $(tail -n 1 "$TMP/run" | head -c 300)" \
           "limited: wait retry_after and re-run with --verify-only; 401: the token is still required (step 3)"

  # /mcp: initialize + tools/list
  mcp "$AUTH_H" "$INIT" > "$TMP/init"
  code="$(cat "$TMP/mcode")"
  local pv; pv="$(jq_py 'r=d["result"]; print(r["protocolVersion"], r.get("serverInfo",{}).get("name",""))' < "$TMP/init" 2>/dev/null)"
  [ "$code" = 200 ] && [ -n "$pv" ] && ok "POST /mcp initialize: protocol $pv" \
    || die "POST /mcp initialize: HTTP $code $(head -c 200 "$TMP/init")" "401: the token is still required (step 3)"
  mcp "$AUTH_H" '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' "${pv%% *}" > "$TMP/tools"
  local tools; tools="$(jq_py 'print(",".join(t["name"] for t in d["result"]["tools"]))' < "$TMP/tools" 2>/dev/null)"
  [ "$(cat "$TMP/mcode")" = 200 ] && [[ ",$tools," == *",unsaid_places,"* ]] && ok "POST /mcp tools/list: $tools" \
    || die "POST /mcp tools/list: HTTP $(cat "$TMP/mcode") $(head -c 200 "$TMP/tools")"

  # the site with no ?token: the page loads, and the deployed api.js only appends a token when the URL has one
  # (`TOKEN ? u + 'token=' : u`), so its relative /api/* calls are exactly the token-less calls checked above
  code="$(curl -sS -m 30 -A "$UA" -o "$TMP/index" -w '%{http_code}' "$SITE/")"
  [ "$code" = 200 ] && grep -q 'js/api.js' "$TMP/index" && ok "GET $SITE/ (no ?token): 200, loads js/api.js" \
    || die "GET $SITE/ answered $code or does not load js/api.js"
  curl -sS -m 30 -A "$UA" -o "$TMP/api.js" "$SITE/js/api.js"
  grep -qF "const withToken = u => TOKEN ? " "$TMP/api.js" && ok "deployed js/api.js passes a token only when ?token= is in the page URL" \
    || die "deployed js/api.js has no token pass-through guard" "compare $SITE/js/api.js with site/js/api.js"
  cmp -s "$TMP/api.js" "$ROOT/site/js/api.js" && ok "deployed js/api.js = site/js/api.js in the repo" \
    || warn "deployed js/api.js differs from site/js/api.js (site is deployed by direct upload; see server/DEPLOY.md)"

  # keepwarm: enabled on the (now public) repo
  local st; st="$(gh workflow list -R "$REPO" --all --json name,state --jq '.[] | select(.name=="keepwarm") | .state' 2>/dev/null)"
  if [ "$st" != active ]; then
    gh workflow enable keepwarm -R "$REPO" >/dev/null 2>&1 && st=active
  fi
  [ "$st" = active ] && ok "keepwarm workflow: active" || warn "keepwarm workflow is '${st:-?}': gh workflow enable keepwarm -R $REPO"
  # Until the flip every keepwarm run failed to start ("recent account payments have failed or your spending limit"):
  # private-repo Actions minutes. Public repos run standard runners free, so one dispatched run must now succeed.
  local last
  if [ "$MODE" = all ]; then
    local prev; prev="$(gh run list -R "$REPO" --workflow keepwarm.yml -L 1 --json databaseId --jq '.[0].databaseId' 2>/dev/null)"
    if gh workflow run keepwarm -R "$REPO" >/dev/null 2>&1; then
      local t0=$SECONDS
      while [ $((SECONDS - t0)) -lt 180 ]; do
        sleep 10
        last="$(gh run list -R "$REPO" --workflow keepwarm.yml -L 1 --json databaseId,status,conclusion \
                --jq '.[0] | "\(.databaseId) \(.status) \(.conclusion)"' 2>/dev/null)"
        set -- $last
        [ "${1:-}" != "$prev" ] && [ "${2:-}" = completed ] && break
      done
      [ "${3:-}" = success ] && ok "keepwarm: a dispatched run succeeded (run $1)" \
        || warn "keepwarm dispatched run: ${last:-none} (gh run view ${1:-} -R $REPO; not blocking, the engine is warm now)"
    else warn "could not dispatch keepwarm (needs the workflow scope)"; fi
  else
    last="$(gh run list -R "$REPO" --workflow keepwarm.yml -L 1 --json status,conclusion,createdAt \
            --jq '.[0] | "\(.createdAt) \(.status) \(.conclusion)"' 2>/dev/null)"
    [ -n "$last" ] && say "        keepwarm last run: $last (runs on the private repo fail to start: billing; public runs are free)"
  fi
}

# ------------------------------------------------------------------------------------------------ 5. checklist
checklist() {
  step "5. Roman, next (Devpost)"
  local ph=""; [ -f "$DEVPOST" ] && ph="$(grep -o '⟦[^⟧]*⟧' "$DEVPOST" | sort -u | tr '\n' ' ')"
  cat <<EOF
  [ ] Open the Devpost submission; paste the text from $DEVPOST section by section
  [ ] Testing instructions: no token needed any more (site, API and /mcp are open); leave none in the text
  [ ] Upload the images (gallery / thumbnail)
  [ ] Video link if there is one${ph:+  (still a placeholder in devpost.final.md: $ph)}
  [ ] Repo link https://github.com/$REPO opens signed out (step 2 checked it)
  [ ] Submit before 23:45 ET; then reload the Devpost page and check it says submitted
  Abuse later: tools/unflip.sh (token required again), or tools/unflip.sh --limit 3 (keep it open, 3 fresh runs/h per IP)
EOF
}

# ------------------------------------------------------------------------------------------------ main
case "$MODE" in
  preflight) preflight; exit 0 ;;
  verify) verify; exit 0 ;;
esac
preflight
if [ "$YES" != 1 ]; then
  printf '\nThis makes %s PUBLIC and opens the API and /mcp without a token. Type flip to go on: ' "$REPO"
  read -r ans; [ "$ans" = flip ] || { say "not flipped"; exit 1; }
fi
go_public
token_off
verify
checklist
say ""
say "FLIPPED: $REPO is public; $SITE, /api and /mcp answer without a token."
