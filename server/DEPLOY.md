# Deploying UNSAID (for Roman)

**Deployed (28 Oct 2026).** Engine: Render free web service `unsaid-engine` (srv-dbgr3fuc6qcc73ce5p3g), https://unsaid-a1wy.onrender.com, Python 3.11, quota 0.15 CPU (read from its cgroup). Site and the `/api/*` proxy: Cloudflare Pages project `unsaid`, https://unsaid-ang.pages.dev, deployed by direct upload, never through git. Secrets live in `~/.config/unsaid/env` (never printed) and in each host's own settings.

Redeploy the engine through the Render API (no dashboard needed):

```bash
set -a; . ~/.config/unsaid/env; set +a
curl -s -X POST -H "Authorization: Bearer $RENDER_API_KEY" -H "Content-Type: application/json" \
  -d '{"clearCache":"do_not_clear"}' https://api.render.com/v1/services/srv-dbgr3fuc6qcc73ce5p3g/deploys
# one env var, without touching the others:
curl -s -X PUT -H "Authorization: Bearer $RENDER_API_KEY" -H "Content-Type: application/json" \
  -d '{"value":"3"}' https://api.render.com/v1/services/srv-dbgr3fuc6qcc73ce5p3g/env-vars/UNSAID_MAX_ACTIVE
```

The "fits everyone" priors (`data/priors/*.json`) are Qloo-derived, so they are gitignored. They reach Render as secret files, mounted at `/etc/secrets/`, with `UNSAID_PRIORS_DIR=/etc/secrets`. After `build_priors.py` changes them: `python3 -I server/push_priors.py`, then redeploy. `/api/health` shows `"priors": {"stl": true, "nyc": true}`, and each result's `diag.prior.used` says whether the prior ranked it.

Redeploy the site: `cd site && npx -y wrangler@3 pages deploy . --project-name unsaid --branch main --commit-dirty=true` (run from `site/` so Pages finds `functions/`).

The setup steps below are how it was first set up; keep them for a rebuild.

## 0. Local check (no accounts)

```bash
cd ~/Desktop/qloo/unsaid
python3 -I server/app.py                        # fake mode on http://127.0.0.1:8710
curl -s localhost:8710/api/health
python3 -I server/tests/test_no_foreign_cache.py && python3 -I server/tests/test_limits.py
```

## 1. Two secrets, made once

```bash
python3 -c 'import secrets; print("UNSAID_TOKEN", secrets.token_urlsafe(24)); print("PROXY_SECRET", secrets.token_urlsafe(32))'
```

Keep both in your password manager. The token goes in the Devpost testing instructions; the proxy secret goes nowhere public.

## 2. Render (engine)

1. Sign up at https://render.com with GitHub. Grant access to the private `unsaid` repo only.
2. Dashboard → **New → Blueprint** → pick the repo. Render reads `render.yaml` (one free web service, `unsaid-engine`).
3. Fill in the env values it asks for:
   - `UNSAID_MODE=fake` (switch to `live` once the Qloo key works)
   - `UNSAID_TOKEN`, and `UNSAID_PROXY_SECRET` = the PROXY_SECRET from step 1
   - `UNSAID_BENCH_SECRET`: a third random secret, only for k11's `X-Unsaid-Bench` header (skips the per-IP limit)
   - optional: `QLOO_GZIP` (1), `QLOO_POOL` (8), `UNSAID_LASTSEEN_S` (3), `UNSAID_MAX_ACTIVE` (2)
   - `QLOO_API_KEY` (when it arrives) · `QLOO_MONTHLY_QUOTA=10000` · `QLOO_QUOTA_HEADERS` after P9
   - `GEMINI_API_KEY` (AI Studio, a project with **no billing**), `GEMINI_LIVE_MODEL=gemini-3-flash-preview` (the live lane's own "Gemini 3 Flash" bucket, separate from the dated lane's 3.8 Flash), `GEMINI_RPD=20`
   - The free tier is 20 requests a day and 5 a minute per model. The server makes one live taste ask per fresh run and no live street asks (street checks use dated answers), stops at 16 a day, and is `dated_only` until midnight Pacific. The status line reads "Gemini (gemini-3-flash-preview): asked just now".
4. Deploy (auto-deploy is off: **Manual Deploy → Deploy latest commit**). Check:
   `curl -s https://unsaid-a1wy.onrender.com/api/health`

The repo carries code only. Qloo responses and results live in `server/.cache/` on Render's ephemeral disk and are gitignored.

## 3. Cloudflare Pages (site + proxy), direct upload

```bash
cd ~/Desktop/qloo/unsaid
npx wrangler login
npx wrangler pages project create unsaid --production-branch main
npx wrangler pages secret put ENGINE_URL   --project-name unsaid   # https://unsaid-a1wy.onrender.com
npx wrangler pages secret put PROXY_SECRET --project-name unsaid   # the PROXY_SECRET from step 1
npx wrangler pages deploy . --cwd site --project-name unsaid --branch main --commit-dirty=true
```

`--cwd site` is required. Pages compiles Functions from `functions/` in the working directory, so a bare `npx wrangler pages deploy site/` from the repo root uploads the static files **without** the `/api/*` proxy.

Check through the proxy:

```bash
curl -s https://unsaid-ang.pages.dev/api/health
curl -sN "https://unsaid-ang.pages.dev/api/unsaid?city=st-louis&loves=%5B%22Frankie%20Beverly%20%26%20Maze%22%5D&token=$UNSAID_TOKEN"
```

A cold engine answers `503` with `{"state":"waking"}` (or a `waking` NDJSON stream) for about a minute; that is expected.

## 4. Keeping it warm

`.github/workflows/keepwarm.yml` GETs `https://unsaid-a1wy.onrender.com/api/health` every 10 minutes (GitHub runs schedules best-effort, sometimes late). It is ordinary inbound traffic and keeps Render from sleeping (it spins down after 15 min idle). One service around the clock uses about 744 of the 750 free instance-hours a month. On a private repo each run bills at least one Actions minute: about 144 a day, so about 1,150 through 5 Nov, inside the free 2,000 if nothing else uses Actions. Stop it after 5 Nov by disabling the workflow.

## 5. After 23:45 ET on 30 Oct (the token-off flip)

Set `UNSAID_TOKEN_REQUIRED=0` on Render and redeploy. Keep `UNSAID_TOKEN`: the API and `/mcp` stop requiring it, but a request that carries it (query `token=` or `Authorization: Bearer`) gets the token's own bucket of 60 fresh runs an hour. Claude.ai connectors all call from Anthropic's servers, so they would otherwise share one IP's limit. Without the token, the per-IP limit is 15 fresh runs an hour through 6 Nov, then 3. The Qloo quota guard applies to everyone. A limited reply carries `retry_after` (seconds) and `limited_by` (`ip` or `quota`).

Memory (512 MB host): `/api/health` shows `rss_mb`, `peak_rss_mb` and `memory.trims`. Above `UNSAID_RSS_SOFT_MB` (300) the server clears the engine's pure memo caches after a run and re-warms the walls. Results are unchanged.
