# Grounding meter: protocol (frozen 27 Oct 2026, 19:46 ET, before any meter ask)

UNSAID.md §4 gate D. Frozen into the public SHA-256 bundle before any meter ask.

**Phrasings** (`{city}` plus the set's three loves, verbatim):
- **M1:** "plan my Friday in {city}, I love {L1}, {L2} and {L3}, but nothing every AI would tell me"
- **M2:** "Where should I eat and drink in {city}? I love {L1}, {L2} and {L3}. Skip anything every AI would say."

The same JSON suffix is appended to every meter ask: "Reply with only JSON: an array of exactly 12 objects like {"name": "...", "neighbourhood": "..."}, your 12 picks. Real, currently open venues only. No other text."

**Arms:**
- *alone*: the assistant with no tools and no web search.
- *with Qloo*: the same assistant with exactly one tool, `qloo_places(loves, city)`, which returns the top 50 of the Qloo taste pool with **no subtraction**. `unsaid_places` is never offered.

**Assistants:** Claude (`claude -p`, Claude Code, the subscription) and ChatGPT (`codex exec`, the pinned gpt-5.6-terra). Gemini is not run (free tier, 20 requests a day).

**Sets:** the first 10 sets in `data/sets.json` order that have both arms complete; the 10 are listed in the output.

**Score:** for each run, how many of the 12 picks are on the **other** assistants' everyone-list (their city-wall and census answers for that city; street asks excluded), matched by `engine/unsaid/matcher.py`.

**Decision rule (featured or not):** the meter is featured only if the median *with Qloo* is ≤ 6 of 12 **and** in ≥ 7 of 10 sets *with Qloo* is ≥ 4 below *alone*. Either way, it is printed in Shown and the README, whatever it says.
