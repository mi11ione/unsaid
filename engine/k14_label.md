# K14 · an independent labeller for the held-out "named" check

A separate model (`claude -p`, claude-opus-5-5, no tools) read each held-out fresh-ask answer and said, blind, whether it names each candidate venue (same place, not a similar name). Candidates: every pair the matcher's loose prefilter flags (a distinctive name token in the answer, or fuzzy >= 0.6), over the cards of every k12 arm and every strike survivor, plus a seeded 10% sample of the unflagged arm pairs. 3556 pairs labelled over 239 answers. Counts only: names stay in engine/out (gitignored).

**Matcher vs labeller** (the sample weighted back to all unflagged pairs): precision 0.84, recall 0.83, agreement 0.997, Cohen's kappa 0.83. Raw: matcher yes and labeller yes 102, matcher yes and labeller no 19, matcher no and labeller yes 21, both no 3414. Sampled unflagged pairs the labeller calls named: 0 of 1132. Named with a quote not found in the answer: 0.

| arm | held-out AI-named, labeller | matcher (k12) | NYC labeller / matcher | STL labeller / matcher |
|---|---:|---:|---:|---:|
| Qloo's plain top 7 | 33 of 140 | 32 | 8 / 8 | 25 / 24 |
| PLAIN+RULES | 20 of 140 | 21 | 7 / 8 | 13 / 13 |
| score-only (no strike) | 11 of 140 | 12 | 1 / 3 | 10 / 9 |
| UNSAID | 3 of 140 | 3 | 1 / 1 | 2 / 2 |
| RANDOM-7 (mean of k12's draws) | 1.65 of 140 | 2.34 | 0.95 / 1.01 | 0.7 / 1.33 |
