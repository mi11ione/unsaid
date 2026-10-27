# Deploying UNSAID (for Roman)

The engine runs on Render (free web service). The site and the `/api/*` proxy run on Cloudflare Pages, deployed by direct upload, never through git. Nothing here has been deployed yet, and no account has been created.

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
   - `QLOO_API_KEY` (when it arrives) · `QLOO_MONTHLY_QUOTA=10000` · `QLOO_QUOTA_HEADERS` after P9
   - `GEMINI_API_KEY` (AI Studio, a project with **no billing**), `GEMINI_MODEL` (one pinned free Flash id), `GEMINI_RPD` (from the console)
4. Deploy (auto-deploy is off: **Manual Deploy → Deploy latest commit**). Check:
   `curl -s https://unsaid-engine.onrender.com/api/health`

The repo carries code only. Qloo responses and results live in `server/.cache/` on Render's ephemeral disk and are gitignored.

## 3. Cloudflare Pages (site + proxy), direct upload

```bash
cd ~/Desktop/qloo/unsaid
npx wrangler login
npx wrangler pages project create unsaid --production-branch main
npx wrangler pages secret put ENGINE_URL   --project-name unsaid   # https://unsaid-engine.onrender.com
npx wrangler pages secret put PROXY_SECRET --project-name unsaid   # the PROXY_SECRET from step 1
npx wrangler pages deploy . --cwd site --project-name unsaid --branch main --commit-dirty=true
```

`--cwd site` is required. Pages compiles Functions from `functions/` in the working directory, so a bare `npx wrangler pages deploy site/` from the repo root uploads the static files **without** the `/api/*` proxy.

Check through the proxy:

```bash
curl -s https://unsaid.pages.dev/api/health
curl -sN "https://unsaid.pages.dev/api/unsaid?city=st-louis&loves=%5B%22Frankie%20Beverly%20%26%20Maze%22%5D&token=$UNSAID_TOKEN"
```

A cold engine answers `503` with `{"state":"waking"}` (or a `waking` NDJSON stream) for about a minute; that is expected.

## 4. The pinger, from Fri 30 Oct 21:30 ET through 5 Nov

At https://cron-job.org (free account), create one job:
- URL `https://unsaid.pages.dev/api/health`, GET, every 10 minutes
- start 30 Oct 21:30 ET, end 5 Nov 23:59 ET

It is ordinary inbound traffic and keeps Render from sleeping (it spins down after 15 min idle). One service around the clock uses about 744 of the 750 free instance-hours in October.

## 5. After 23:45 ET on 30 Oct

To open the API: remove `UNSAID_TOKEN` in Render, then redeploy. Per-IP limits (3 fresh runs per hour) and the quota guards stay on.
