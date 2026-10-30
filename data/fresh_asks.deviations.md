# Fresh asks (K5′, gate E): deviations from UNSAID.md §4

## D1 · one subreddit context line before each verbatim question

**When:** decided by the author and applied by the harness on 27 Oct 2026 at 21:06 ET, before any gate-E scoring. No card has been checked against any fresh answer.

**What:** §4 says the questions are asked "as posted". From now on, each question is sent with exactly one context line before its verbatim text, chosen by the post's `source` field:

| source | context line (followed by a blank line) |
|---|---|
| reddit r/StLouis | `Posted in r/StLouis (St. Louis, Missouri):` |
| reddit r/AskNYC | `Posted in r/AskNYC (New York City):` |
| reddit r/FoodNYC | `Posted in r/FoodNYC (New York City):` |

- Nothing else changes. The text (title + body) is still verbatim, with no JSON suffix, and codex runs without `--output-schema`.
- The 4 per-set questions (the first 4 of each city in `fresh_asks.json` order: STL-01 to STL-04 and NYC-01 to NYC-04) get the same line, plus the appended sentence "I love {L1}, {L2} and {L3}."
- It applies uniformly to all 40 questions, both lanes (Claude, ChatGPT) and all 20 sets.
- Records carry `variant: "v1-subreddit-context"` and `context_prefix`.
- The hash check against every wall, census, taste and street phrasing, now also covering the prefixed prompts, prints 0 collisions.

**Why:** the posts rely on the subreddit for their city. Asked as posted, the assistants mostly asked "which city?" and named no venue, which would make gate E pass vacuously: no answer could name a card.

**The evidence (v0, kept):** 23 answers were stored before the run was stopped, all for St. Louis questions. They are kept in `harness/runs/fresh.v0.jsonl` with `variant: "v0-no-context"` and are not scored for gate E. Each answer was labelled by hand from its raw text, and the evidence for each label is stored on the record.

| | answers | named ≥ 1 venue | named ≥ 1 St. Louis venue | asked for the location |
|---|---|---|---|---|
| Claude (claude-sonnet-5-5) | 16 | 7 | 6 | 10 |
| ChatGPT (gpt-5.6-terra) | 7 | 2 | 1 | 5 |
| **both** | **23** | **9** | **7** | **15** |

- 1 answer did neither: it assumed St. Louis but declined to name places.
- Both answers to STL-04 ("Westport") named venues in other cities: Westport CT, Westport in Ireland, and Westport in Kansas City.
