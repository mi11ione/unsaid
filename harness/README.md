# harness: the $0 AI side (UNSAID.md §3.6)

Walls, censuses, fresh asks and meter runs, asked on Roman's Mac only, through each vendor's own tool. Nothing here is
callable from a server path. No paid API key, no web search, no name or email in any request or header.

| script | does |
|---|---|
| `walls_cli.py` | `ask` city wall (20 phrasings) / taste (4 per set) / street asks; `build` → `data/walls/`; `status`; `plan` |
| `run_census.py --provider claude\|codex\|gemini` | the frozen 128 census asks (`asks.json`, prompt v1), verbatim |
| `census_stats.py [--provider p] [--gems]` | census numbers per provider; `--gems` fills ⟦GEM_GPT⟧ ⟦GEM_GEM⟧ from stored output only |
| `fresh_asks.py` | K5′ held-out public questions, verbatim (needs `data/fresh_asks.json`) |
| `meter.py` | gate D, alone vs with `qloo_places` (needs `UNSAID_MODE=live` + `QLOO_API_KEY` for the with arm) |
| `lanes.py` | the three lanes, the answer store, the resumable runner |
| `phrasings.py` | prompt v2 phrasings (the 16 gem phrasings imported verbatim from `prompts.py`), set loading, question hashes |
| `hoods.py` → `neighbourhoods.json` | OSM neighbourhoods for street asks (STL 79, NYC 130; 4 "Historic District" entries pruned) |

Nothing is asked without `--go`. Every command prints what it would ask first.

## Lanes: the exact commands

Every ask runs once, from a fresh empty temp dir, with stdin closed (`codex exec` would otherwise append piped stdin).

**claude** (Claude Code 2.1.311, Roman's plan, 4 workers): §3.6's line, unchanged.
```
claude -p "<ask>" --output-format json --model sonnet --tools "" --safe-mode --strict-mcp-config \
  --no-session-persistence --system-prompt "You are Claude, a helpful assistant chatting with a user in a consumer chat app."
```
The model id is read from `modelUsage` (the key with the most output tokens).

**codex** (codex-cli 0.164.0, ChatGPT plan, 2 workers):
```
codex exec --json --ephemeral --skip-git-repo-check --sandbox read-only --output-schema places.schema.json \
  --ignore-user-config -c web_search="disabled" -m gpt-5.6-terra "<ask>"
```
Any `web_search` item in the event stream labels the answer `search: "on"`. `CODEX_MODEL` overrides the model.

**gemini** (free-tier REST, 1 worker; dated lane = `gemini-3.8-flash` only, one project, one key): `POST https://generativelanguage.googleapis.com/v1beta/models/$GEMINI_MODEL:generateContent`.
- The key goes in the `x-goog-api-key` header, never the URL.
- `systemInstruction`: "You are Gemini, a helpful assistant chatting with a user in a consumer chat app."
- JSON mode with a `[{name, neighbourhood}]` schema. No tools, so no grounding.
- The model id comes from `modelVersion`. A `groundingMetadata` block would label the answer "search on".
- Paced at `GEMINI_RPM`. It stops at `GEMINI_HARNESS_FRACTION` (0.8) × `GEMINI_RPD` per Pacific day, counted in `runs/.gemini_ledger.json`.
- A missing variable prints `needs credential: …` and skips the lane.
- A 500/503 ("high demand") is retried after 30, 90 and 240 s. Every attempt counts in the ledger, erring low because the live lane shares the quota. A 503 that outlasts the retries is stored `failed` with `transient: true`: it is asked again later and is no strike toward the 3-in-a-row stop.

### Gemini on the free tier (orchestrator, 28 Oct): 20 RPD, 5 RPM, harness cap 16/day

The console shows 20 requests a day and 5 a minute per model per project. Credentials load from `~/.config/unsaid/env` (mode 0600, never printed, never copied): `set -a; . ~/.config/unsaid/env; set +a`.

- **The only Gemini path is the queue:** `walls_cli.py queue gemini-priority [--already-used N] --go`. It spends exactly what is left of today's cap (16 per Pacific day, which resets at 03:00 ET). Resumable: run it again each day.
- `--already-used N` records requests made outside the harness today (the console's count).
- `gemini_batch.sh` runs one batch: it loads the env, runs the queue, then `build --census-only`. To schedule it, run it after 03:00 ET from a wall-clock wait loop, which still fires after the Mac wakes.
- Priority order:
  - (a) the 16 census hidden-gem asks for STL, then NYC, verbatim (`asks.json`, prompt v1). Stored once in `gemini_answers.jsonl`: `census_stats.py --gems` reads them for ⟦GEM_GEM⟧, and `build` puts them in `census.json`, which joins every wall, so they are also wall #1's gem part.
  - (b) the 4 plain wall phrasings per city (v2).
  - (c) taste for stl-cedric, then stl-jason.
  - (d) the other try-these sets' taste. Items (b) to (d) go to `runs/wall-1.jsonl`.
- **Not run: free-tier 20/day.** The full 64-ask Gemini census, the v2 copies of the 16 gem phrasings, street asks, walls #2 and #3, fresh asks and the meter. `walls_cli.py ask`, `fresh_asks.py` and `meter.py` skip the gemini lane and say so. `run_census.py --provider gemini` refuses without `--only-hidden`.

## Deviations from §3.6, and why

1. **codex `--ignore-user-config -c web_search="disabled"`.** Roman's `~/.codex/config.toml` loads a browser plugin and MCP servers, and codex's own `web_search` tool is on (`"cached"`) by default. Either one would break the no-web-search rule. Auth still comes from `CODEX_HOME`.
2. **codex model pinned with `-m`.** The `--json` stream in 0.164.0 carries no model id: its events are `thread.started`, `turn.*`, `item.*` and `error`, with `thread_id`, `items` and `usage`, as checked in the binary and in a real ask on 27 Oct. Answers are recorded as `model: "gpt-5.6-terra"`, `model_source: "pinned (-m)"`. If an event ever carries a `model` field, that value wins and `model_source` becomes `"event stream"`.
3. **Meter, claude, both arms: `--safe-mode` is replaced by `--setting-sources local --disable-slash-commands`.**
   - Why: `--safe-mode` drops every `--mcp-config` server. Checked on 2.1.311 on 27 Oct: the init event showed `mcp_servers: []` and `tools: []`.
   - The replacement loads the server (`unsaid: connected`) and keeps user skills, plugins and hooks off (`skills: []`; only the builtin plugins remain).
   - Both arms use it, so they differ only in the tool. The meter also uses `--output-format stream-json --verbose`, so every `tool_use` is counted.
   - The with arm adds `--mcp-config runs/.meter.mcp.json --allowedTools mcp__unsaid__qloo_places --disallowedTools mcp__unsaid__unsaid_places`.
4. **Meter, codex:** the walls line plus `-c mcp_servers.unsaid.{command,args,enabled_tools=["qloo_places"],env_vars}`. **Meter, gemini:** no JSON mode (it doesn't mix with function calling), plus one `functionDeclaration` whose calls run through the same MCP server (`mcp_client.py`). Both are untested against real tools so far.
5. **Fresh asks go out verbatim:** no JSON suffix, codex without `--output-schema`, Gemini without JSON mode. The raw text is the answer, and k5 matches on it. Records carry `verbatim: true, suffix: false`. `--suffix` opts out.
6. **Taste sets per wall:** wall 1 asks all 20 sets. Every other wall asks only the sets marked `try_these` (`data/sets.json`, else `data/sets.draft.json`). `--sets a,b` or `--all-sets` overrides.

## Storage, resume and failures

- Every attempt appends one line: `runs/wall-<label>.jsonl`, `runs/fresh.jsonl`, `runs/meter.jsonl`, `<provider>_answers.jsonl` (census).
- Each line holds the id, kind, city, set, loves, phrasing_id, phrasing, prompt, prompt_v, provider, assistant, tool version, model and model_source, `lane: "dated"`, search on/off, asked_at, answered_at, status, error, the raw text and the parsed `places`. No session ids, costs or account data are kept.
- `status`:
  - `ok`: a parsed list, or any answer to a verbatim ask.
  - `unparsed`: the tool answered without a list. Kept and not re-asked, since re-asking until it parses would bias the wall.
  - `failed`: no answer (timeout, plan limit, HTTP error). Recorded as failed and asked again on the next run.
- **Resume:** run the same command again. Ids already stored `ok`/`unparsed` are skipped. A lane stops after 3 failures in a row, or at once on a Gemini 401/403/429 or the daily cap.
- **Held out:** fresh questions are hashed (case and whitespace folded, suffix stripped) and checked against every wall, taste, street and census phrasing. One clash and nothing runs. `walls_cli.py` refuses to ask or build a wall phrasing that matches a fresh question.

## Build

`walls_cli.py build --walls 1` writes `data/walls/wall-1.json` (set `city` = city wall + street asks; one entry per set with its taste answers and loves) and `data/walls/census.json` (set `census`, every provider's census).
- The server merges every `*.json` in `data/walls/`, so the census lives in one file only.
- A non-numeric label writes `<label>.json`. `--out FILE` writes one combined file instead.
- `--census-only` writes only `census.json`. Smoke answers never go in `data/walls/`: `build` refuses a `smoke` label without `--out`.

## Credentials (Roman only)

`codex login` (ChatGPT plan; already signed in on 27 Oct). `GEMINI_API_KEY`, `GEMINI_MODEL`, `GEMINI_RPM` and `GEMINI_RPD` come from an AI Studio project with no billing account. `claude` signed in to the plan.
