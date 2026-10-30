# Meter, third arm: `unsaid_places` (POST-HOC experiment)

**This experiment was not pre-registered.** The frozen meter protocol (`data/meter.protocol.md`, 27 Oct 2026, 19:46 ET, hashed) has two arms, *alone* and *with Qloo*. It never offers `unsaid_places`, and its result stands as published. This file adds a third arm because a judge asked for it. It was written on 28 Oct 2026 at 07:05 ET, before any ask in this arm, and is committed before the first ask. Any change after the first ask is logged at the bottom with its time and reason. The results are always labelled "post-hoc", wherever they are printed.

## Question

An agent is given the same ask as in the meter, with UNSAID as its only tool. How many of its 12 picks are still on the other assistants' everyone-list? How does that compare with the same agent alone and with Qloo's unsubtracted ranking?

## Read this before the numbers

`unsaid_places` crosses out every name on the city wall, and that wall contains the grading list (the other assistants' city-wall and census answers). So the **tool's own picks score 0 by construction.** This arm doesn't test whether UNSAID's picks avoid the everyone-list; the frozen gates already cover that. It tests what an agent does with the tool:

1. **Leakage.** The ask wants 12 picks, and the tool returns at most 7. Any everyone-list name in the answer comes from the agent itself: picks it adds from memory, or picks it keeps over the tool's.
2. **Adherence.** How many of the 12 are tool picks, and whether the agent called the tool at all.

## Design (identical to the frozen meter except for the tool)

| | frozen meter | this arm |
|---|---|---|
| Sets | the 10 STL sets in `harness/runs/meter_sets.json` | the same 10 |
| Phrasings | M1, M2 verbatim, plus the frozen JSON suffix (12 picks) | the same, byte for byte (`harness/meter.py` PHRASINGS, SUFFIX) |
| Assistants | Claude (`claude -p --model sonnet`), ChatGPT (`codex exec`, pinned gpt-5.6-terra) | the same instruments and flags, the same system line |
| Reps | 1 | 1 |
| Tool | none (alone) / `qloo_places` only (with) | **`unsaid_places` only**, served by `agent/unsaid_mcp.py` in **remote mode** (`UNSAID_MODE=remote`, the hosted API at https://unsaid-ang.pages.dev, `UNSAID_TOKEN` from the env). `qloo_places` is not listed in remote mode. |
| Grading | `k10_meter.py`: a pick is on the list if `matcher.match_wall([pick], other assistants' city-wall + census names)` hits; street asks excluded; the run's own provider is excluded | identical code path, unchanged |

That is 10 sets × 2 phrasings × 2 assistants × 1 rep = **40 asks**. Gemini isn't run, as in the frozen meter.

The *alone* and *with Qloo* arms are **not asked again**. Their stored runs in `harness/runs/meter.jsonl` are the comparison. **Drift check:** because the models may have drifted since 28 Oct 02:00 ET, *alone* is asked again for 2 sets (stl-cedric, stl-wilco) × 2 phrasings × 2 assistants = 8 asks. The drift is reported as the mean absolute change in the score. If it is above 2 of 12, the three-arm comparison is printed with that caveat.

## Instruments (for Agent B)

- `harness/meter.py` gains an arm `unsaid`. Every record goes to **`runs/meter_unsaid.jsonl`**, never to the frozen `runs/meter.jsonl`. Each record carries `arm: "unsaid"`, `posthoc: true`, the raw answer, the parsed 12 picks, and the tool's result (`structuredContent`: the picks' names and Qloo IDs, `flags`, `host.key`, `diag` engine version, wall snapshot). Adherence is scored from the stored tool result, with no extra call.
- MCP config: `env = {"UNSAID_MODE": "remote", "UNSAID_TOKEN": "${UNSAID_TOKEN:-}", "UNSAID_URL": "${UNSAID_URL:-}"}`. No Qloo key goes in the agent env.
  - claude: `--allowedTools mcp__unsaid__unsaid_places`.
  - codex: `enabled_tools=["unsaid_places"]`, with `UNSAID_TOKEN` in `env_vars`.
- The hosted API allows 3 fresh runs per hour per address. Repeats are cached: a set costs one fresh run when the agent's loves resolve to the same Qloo IDs. Use the bench header (`X-Unsaid-Bench`, the server's secret, held by the author), or pace at 3 fresh sets per hour. A tool result of `limited`, `degraded` or `waking` is retried once after 60 s. If it fails again, the run is kept and marked `tool_failed`.
- Run order: after Agent D's ranking change is **deployed** to the host, so that every unsaid-arm call uses one engine version. Record `engine_v` and the wall snapshot per run. A run whose engine version differs from the first run's is reported separately.
- Requests from this Mac are geo-gated for the live Gemini lane, so the host answers `dated_only`. Every run sees the same dated wall, and this is recorded.

## Measures (0 Qloo calls)

1. **Primary:** the score per run, out of 12 picks on the other assistants' everyone-list, by k10's grader. Per set, the median over the runs. Across sets, the median for each arm: *alone*, *with Qloo* (stored) and *with UNSAID* (this arm).
2. **Leakage split:** for each everyone-list pick in this arm, whether it is one of the tool's picks (expected never: that would be a strike/grader inconsistency, reported as a bug) or one the agent added.
3. **Adherence:** the tool-call rate, and the median number of the 12 picks that are tool picks, matched by Qloo ID or by matcher R1.
4. **Intention to treat:** runs where the agent didn't call the tool, or the tool failed, stay in the primary measure and are also listed separately.

## Expectation (written before running; not a gate)

The prediction is that *with UNSAID* < *with Qloo* < *alone*, with the UNSAID arm's median at most 3 of 12. Leakage should come only from the agent's own additions beyond the tool's 7 picks. There is no featured/not-featured rule, because this is post-hoc. The three medians, the drift and the adherence are printed together, whatever they say, under the label "post-hoc, not pre-registered".

## Cost

- AI asks: 48 (40 + 8 drift), on the Claude and ChatGPT subscriptions ($0 marginal).
- Qloo: up to 10 fresh hosted runs (one per set). Each is about 37 calls, so at most about 370, fewer where the host's Qloo cache is warm. Needs the author's OK against the key's budget. If the host's cache key changes with the engine version, every set is fresh once.
- Wall clock: about 1 h with the bench header, about 4 h paced.

## Change log (after the first ask)

- **28 Oct 2026, 07:28 ET · Qloo cap 370 → 900 hosted calls** (Agent B).
  - Real spend is about 40 to 90 calls per set. Claude's first call per set is fresh, and ChatGPT calls the tool up to 5 times with different love variants, each a new host cache key. At 370, about 4 to 7 of the 10 sets would complete.
  - Nothing else changed: sets, phrasings, instruments, grading.
  - Two infrastructure faults before this, both fixed and logged:
    - The bench proxy's first port was taken by another local process, so one ask's tool got HTTP 404. That record is in `runs/quarantine.jsonl` and was re-asked.
    - A host cache hit was counted as new Qloo spend. Cache hits now count 0.
  - The bench header is added by `harness/bench_proxy.py` (localhost), because `agent/unsaid_mcp.py` doesn't send it.
