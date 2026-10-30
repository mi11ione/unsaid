# K14 · an independent labeller for the held-out "named" check

A separate model (`claude -p`, claude-opus-5-5, no tools) read each held-out fresh-ask answer and said, blind, whether it names each candidate venue (same place, not a similar name). Candidates: every pair the matcher's loose prefilter flags (a distinctive name token in the answer, or fuzzy >= 0.6), over the cards of every k12 arm and every strike survivor, plus a seeded 10% sample of the unflagged arm pairs. 3603 pairs labelled over 239 answers. Counts only: names stay in engine/out (gitignored).

**Matcher vs labeller** (the sample weighted back to all unflagged pairs): precision 0.84, recall 0.79, agreement 0.997, Cohen's kappa 0.81. Raw: matcher yes and labeller yes 93, matcher yes and labeller no 18, matcher no and labeller yes 24, both no 3468. Sampled unflagged pairs the labeller calls named: 0 of 1235. Named with a quote not found in the answer: 0.

| arm | held-out AI-named, labeller | matcher (k12) | NYC labeller / matcher | STL labeller / matcher |
|---|---:|---:|---:|---:|
| Qloo's plain top 7 | 33 of 140 | 32 | 8 / 8 | 25 / 24 |
| PLAIN+RULES | 16 of 140 | 17 | 3 / 4 | 13 / 13 |
| score-only (no strike) | 11 of 140 | 12 | 0 / 2 | 11 / 10 |
| UNSAID | 0 of 140 | 0 | 0 / 0 | 0 / 0 |
| RANDOM-7 (mean of k12's draws) | 1.65 of 140 | 2.47 | 0.97 / 1.04 | 0.68 / 1.43 |
