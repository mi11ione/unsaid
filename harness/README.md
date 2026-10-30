# harness: the $0 AI side (UNSAID.md §3.6)

Walls, censuses, fresh asks and meter runs, asked on the author's Mac only, through each vendor's own tool. Nothing here is
callable from a server path. No paid API key, no name or email in any request or header, and no web search except in the
labelled search-on lane (below), which is stored apart.

| script | does |
|---|---|
| `walls_cli.py` | `ask` city wall (20 phrasings) / taste (4 per set) / street asks; `build` → `data/walls/`; `status`; `plan` |
| `run_census.py --provider claude\|codex\|gemini` | the frozen 128 census asks (`asks.json`, prompt v1), verbatim |
| `census_stats.py [--provider p] [--gems]` | census numbers per provider; `--gems` fills `GEM_GPT` `GEM_GEM` from stored output only |
| `fresh_asks.py` | K5′ held-out public questions, verbatim (needs `data/fresh_asks.json`) |
| `meter.py` | gate D, alone vs with `qloo_places` (needs `UNSAID_MODE=live` + `QLOO_API_KEY` for the with arm); the post-hoc `unsaid` arm (`meter_unsaid.md`, graded by `meter_unsaid_grade.py`) |
| `search_on.py` | the search-on lane: Claude and ChatGPT with web search, stored apart, labelled `search: true` |
| `saturation.py` | saturation batches that extend the no-search census like for like, until the new-name rate falls under 5% |
| `lanes.py` | the three lanes, the answer store, the resumable runner |
| `phrasings.py` | prompt v2 phrasings (the 16 gem phrasings imported verbatim from `prompts.py`), set loading, question hashes |
| `hoods.py` → `neighbourhoods.json` | OSM neighbourhoods for street asks (STL 79, NYC 130; 4 "Historic District" entries pruned) |

Nothing is asked without `--go`. Every command prints what it would ask first.

## Lanes: the exact commands

Every ask runs once, from a fresh empty temp dir, with stdin closed (`codex exec` would otherwise append piped stdin).

**claude** (Claude Code 2.1.311, the author's plan, 4 workers): §3.6's line, unchanged.
```
claude -p "<ask>" --output-format json --model sonnet --tools "" --safe-mode --strict-mcp-config \
  --no-session-persistence --system-prompt "You are Claude, a helpful assistant chatting with a user in a consumer chat app."
```
The model id is read from `modelUsage` (the key with the most output tokens). Every no-search answer in `data/walls/` reads `claude-sonnet-5-5`. In the search-on lane Claude Code routed 21 of 96 answers to `claude-haiku-5-5`; they are kept and stamped with that model.

**codex** (codex-cli 0.164.0, ChatGPT plan, 2 workers):
```
codex exec --json --ephemeral --skip-git-repo-check --sandbox read-only --output-schema places.schema.json \
  --ignore-user-config -c web_search="disabled" --disable apps --disable shell_tool -m gpt-5.6-terra "<ask>"
```
Any `web_search` item in the event stream labels the answer `search: "on"`. `CODEX_MODEL` overrides the model.

**gemini** (free-tier REST, 1 worker; dated lane = `gemini-3.8-flash` only, one project, one key): `POST https://generativelanguage.googleapis.com/v1beta/models/$GEMINI_MODEL:generateContent`.
- The key goes in the `x-goog-api-key` header, never the URL.
- `systemInstruction`: "You are Gemini, a helpful assistant chatting with a user in a consumer chat app."
- JSON mode with a `[{name, neighbourhood}]` schema. No tools, so no grounding.
- The model id comes from `modelVersion`. A `groundingMetadata` block would label the answer "search on".
- Paced at `GEMINI_RPM`. It stops at `GEMINI_HARNESS_FRACTION` (0.8) × `GEMINI_RPD` per Pacific day, counted in `runs/.gemini_ledger.json`.
- A missing variable prints `needs credential: …` and skips the lane.
- A 500/503 ("high demand") or a per-minute 429 is retried once, after the server's Retry-After / RetryInfo when it gives one, else 90 s. A per-day 429 ends the day. After 2 slow failures in a row (timeouts or 503s) the queue pauses 10 minutes. Failed asks come round again in later passes while the day's cap lasts.
- The read timeout is 420 s. On 28 Oct, answers took up to 282 s, and 7 of 12 attempts died at the old 180 s. Every timed-out request is charged too, so waiting longer costs nothing extra.
- The ledger (`runs/.gemini_ledger.json`) counts per model per Pacific day, and each model is capped at 16, because the free-tier limits are per model per project.
- **A second gem model:** `walls_cli.py queue gemini-gems --model gemini-3.6-flash` asks only the 32 census hidden-gem asks, on a free-tier flash model that is neither the dated lane's 3.8-flash nor the live lane's model. Its answers go to `gemini-3.6-flash_answers.jsonl` and are reported separately (`census_stats.py --gems` prints `GEM_GEM[gemini-3.6-flash]`). `gemini_batch.sh` runs both queues each day. Every attempt counts in the ledger, erring low because the live lane shares the quota. A 503 that outlasts the retries is stored `failed` with `transient: true`: it is asked again later and is no strike toward the 3-in-a-row stop.

### Gemini on the free tier (28 Oct): 20 RPD, 5 RPM, harness cap 16/day

The console shows 20 requests a day and 5 a minute per model per project. Credentials load from `~/.config/unsaid/env` (mode 0600, never printed, never copied): `set -a; . ~/.config/unsaid/env; set +a`.

- **The only Gemini path is the queue:** `walls_cli.py queue gemini-priority [--already-used N] --go`. It spends exactly what is left of today's cap (16 per Pacific day, which resets at 03:00 ET). Resumable: run it again each day.
- `--already-used N` records requests made outside the harness today (the console's count).
- `gemini_batch.sh` runs one batch: it loads the env, runs the queue, then `build --census-only`. To schedule it, run it after 03:00 ET from a wall-clock wait loop, which still fires after the Mac wakes.
- Priority order:
  - (a) the 16 census hidden-gem asks for STL, then NYC, verbatim (`asks.json`, prompt v1). Stored once in `gemini_answers.jsonl`: `census_stats.py --gems` reads them for `GEM_GEM`, and `build` puts them in `census.json`, which joins every wall, so they are also wall #1's gem part.
  - (b) the 4 plain wall phrasings per city (v2).
  - (c) taste for stl-cedric, then stl-jason.
  - (d) the other try-these sets' taste. Items (b) to (d) go to `runs/wall-1.jsonl`.
- **Not run: free-tier 20/day.** The full 64-ask Gemini census, the v2 copies of the 16 gem phrasings, street asks, walls #2 and #3, fresh asks and the meter. `walls_cli.py ask`, `fresh_asks.py` and `meter.py` skip the gemini lane and say so. `run_census.py --provider gemini` refuses without `--only-hidden`.

## Deviations from §3.6, and why

1. **codex `--ignore-user-config -c web_search="disabled"`.** The author's `~/.codex/config.toml` loads a browser plugin and MCP servers, and codex's own `web_search` tool is on (`"cached"`) by default. Either one would break the no-web-search rule. Auth still comes from `CODEX_HOME`.
1b. **codex `--disable apps`** (added 28 Oct). The built-in `codex_apps` connector exposes `search_service.web_run`, a web search that arrives as an `mcp_tool_call`, not a `web_search` item. It ran in 8 of the 128 census answers and in the first meter "with" ask. Those 8 were re-asked with apps disabled (`run_census.py --provider codex --redo-foreign`): the new records supersede the old ones, which stay in the file for audit. The meter record is in `runs/quarantine.jsonl`. Any tool call outside the `unsaid` server is now recorded in `foreign_tools`, and a search-like one labels the answer `search: "on"`.
2. **codex model pinned with `-m`.** The `--json` stream in 0.164.0 carries no model id: its events are `thread.started`, `turn.*`, `item.*` and `error`, with `thread_id`, `items` and `usage`, as checked in the binary and in a real ask on 27 Oct. Answers are recorded as `model: "gpt-5.6-terra"`, `model_source: "pinned (-m)"`. If an event ever carries a `model` field, that value wins and `model_source` becomes `"event stream"`.
3. **Meter, claude, both arms: `--safe-mode` is replaced by `--setting-sources local --disable-slash-commands`.**
   - Why: `--safe-mode` drops every `--mcp-config` server. Checked on 2.1.311 on 27 Oct: the init event showed `mcp_servers: []` and `tools: []`.
   - The replacement loads the server (`unsaid: connected`) and keeps user skills, plugins and hooks off (`skills: []`; only the builtin plugins remain).
   - Both arms use it, so they differ only in the tool. The meter also uses `--output-format stream-json --verbose`, so every `tool_use` is counted.
   - The with arm adds `--mcp-config runs/.meter.mcp.json --allowedTools mcp__unsaid__qloo_places --disallowedTools mcp__unsaid__unsaid_places`.
4. **Meter, codex:** the walls line plus `-c mcp_servers.unsaid.{command,args,enabled_tools=["qloo_places"],env_vars}`. **Meter, gemini:** no JSON mode (it doesn't mix with function calling), plus one `functionDeclaration` whose calls run through the same MCP server (`mcp_client.py`). Both are untested against real tools so far.
5a. **Fresh asks, v1-subreddit-context** (28 Oct, `data/fresh_asks.deviations.md`): one line, "Posted in r/<sub> (<city>):", goes before each verbatim post. The 23 v0 answers sent without it are kept in `runs/fresh.v0.jsonl`.
5. **Fresh asks go out verbatim:** no JSON suffix, codex without `--output-schema`, Gemini without JSON mode. The raw text is the answer, and k5 matches on it. Records carry `verbatim: true, suffix: false`. `--suffix` opts out.
6. **Taste sets per wall:** wall 1 asks all 20 sets. Every other wall asks only the sets marked `try_these` (`data/sets.json`, else `data/sets.draft.json`). `--sets a,b` or `--all-sets` overrides.

## More dated walls

- `street-1` (`street_1.sh`): "Best places to eat and drink in {neighbourhood}, {city}" for the 71 distinct neighbourhoods of the frozen 20 sets' cards and reserves (STL 31, NYC 40), on both lanes. Only the neighbourhood and city fields are read; the list sits in a gitignored file. → `data/walls/street-1.json`.
- `e1` (`sets_e.py`, `sets_e.sh`): each set's own three loves plus the city, two unhinted phrasings, sent verbatim (no suffix) on both lanes: "I love {L1}, {L2} and {L3}. Where should I eat or drink in {city}?" and "Where should I go out to eat or drink in {city}? I'm into {L1}, {L2} and {L3}.". → `data/walls/e1.json`, one taste entry per set. The engine's reverse check reads the raw text. `sets_e.py --count` writes only counts of the cards they name (`runs/sets_e_counts.json`), using k5's rule.
- `search-on` (`search_on.sh`): "real ChatGPT and Claude search the web; does the wall hold?" Per city, the 16 census hidden-gem phrasings plus 8 plain ones, to Claude with `--tools "WebSearch,WebFetch"` (it searched in 6 of 48 asks), to Claude told to search (a labelled `nudged` variant; 44 of 48) and to codex with `-c web_search="live" --disable apps --disable shell_tool` (48 of 48). → `data/walls/search-on.json` (`meta.search: true`). The no-search census never reads it. `search_on.py --report` on 28 Oct: 0 of the 140 frozen gate-E cards named (on the ranking after those cards, before this lane joined the wall, it named 5 cards in 4 sets, now struck); Claude's hidden-gem tops hold (Mai Lee 14 of 16 with search allowed, 8 of 16 nudged); ChatGPT with search moves off them (Mai Lee 4 of 16, Gioia's Deli 0 of 16). Logs: `runs/logs/search-on*.log`.
- `sat` (`saturation.py`, `saturation.sh`): a deterministic phrase grid (neighbourhood × occasion × cuisine × template) with the census v1 suffix, no search, in batches of 40 per city per AI. A pair stops when the new-name rate in the last 40 asks is under 5% or after 240 extra asks. → `data/walls/sat.json`; coverage against the Chao2 estimate in `runs/saturation.json`. 960 extra asks in all (240 per AI per city). At the lane's end (28 Oct), coverage of the Chao2 estimate: Claude STL 46.6% → 51.0%, NYC 43.9% → 44.9%; ChatGPT STL 53.6% → 61.3%, NYC 47.1% → 46.2% (its estimate grew). St. Louis is near flat (new-name rate in the last 40 asks: Claude 7.7%, ChatGPT 8.5%); New York is not (27.7%, 31.2%). Neither city hit the 5% stop.
- Walls #2 and #3 (`wall_day.sh`) are scheduled by `at_et.sh` for 09:00 ET on 29 and 30 Oct. Gemini (`gemini_daily.sh`) runs at 03:05 ET. Every waiter and every lane refuses to start, or stops, below 3 GB of free disk.

## Search leak (28 Oct): found, fixed, redone

**What happened:** `codex exec` ships a built-in connector, `codex_apps`, whose `search_service.web_run` tool is a web search. Neither `--ignore-user-config` nor `-c web_search="disabled"` turns it off, and it reports as an `mcp_tool_call` item, not a `web_search` item. So the "search on" label never fired, and the affected answers were stored as `search: "off"`.

**How it was found:** the first meter "with" ask on codex called `codex_apps/search_service.web_run` three times instead of `qloo_places`. Every stored codex record was then audited (`audit_codex.py`). The evidence, the same for every file: an `mcp_tool_call` that isn't our own `unsaid/qloo_places`, any `foreign_tools`, a `web_search` item, or `search: "on"`.

| file | codex records | contaminated | action |
|---|---|---|---|
| `codex_answers.jsonl` (census) | 128 | 8 | re-asked (`run_census.py --redo-foreign`) |
| `runs/wall-1.jsonl` | 120 | 41 | re-asked (`audit_codex.py --fix`) |
| `runs/meter.jsonl` | 1 (first verification ask) | 1 | moved to `runs/quarantine.jsonl`, re-asked |
| `runs/wall-smoke.jsonl`, `runs/fresh.v0.jsonl`, `runs/meter.jsonl` (the other 40), `runs/fresh.jsonl` | | 0 | none |

**The fix:** the codex lane now runs with `--disable apps` (verified: the redone answers and the meter "with" arm show only `unsaid/qloo_places`, or no tool at all). Any tool call outside the `unsaid` server is now recorded in `foreign_tools`, and a search-like one labels the answer `search: "on"`. Every fresh v1 ask ran with `--disable apps` from the first one (checked in the live process list).

**The shell leak (found the same day):** codex can also run shell commands. In the read-only sandbox these were meant to have no network, but 6 street answers ran `curl` (caught by the new command log, which labelled them `search: "on"`). So the shell is now off as well: `--disable shell_tool`, matching claude's `--tools ""`. Verified on 1 ask that asked it to run `curl` and `ls`: the stream held only `agent_message`, and the answer said the terminal isn't available. `audit_codex.py` now also flags any shell use (a `command_execution` item or stored `commands`). Every such answer was re-asked with both flags: 7 street answers (6 curl + 1 other command), 9 in wall #1, 4 in fresh v1 and 2 in the meter. The 49 street asks still missing were asked with both flags from the start. The only tool left is codex's built-in `codex/list_mcp_resources`, which 3 street answers called. It lists resources of configured MCP servers, and none are configured, so it returns nothing. It stays recorded on the answer, and the audit treats it as benign.

**Audit trail:** each re-asked answer is a new record under the same id, with `redo_of`. The old line stays in the file, marked `superseded_by` (the new answer's `asked_at`) and `superseded_reason`. `lanes.load`, every builder (`walls_cli.py build`, `--census-only`) and `census_stats.py` skip superseded and quarantined lines. `python3 -I audit_codex.py` must print 0 unresolved for every file before a wall is published.

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

## Credentials (the author only)

`codex login` (ChatGPT plan; already signed in on 27 Oct). `GEMINI_API_KEY`, `GEMINI_MODEL`, `GEMINI_RPM` and `GEMINI_RPD` come from an AI Studio project with no billing account. `claude` signed in to the plan.
