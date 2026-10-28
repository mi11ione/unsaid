# K12 · what crossing out changes

Engine `unsaid-engine-4.0`. The same pipeline ran twice per set over the same U: with the real dated wall (`on`) and with an empty wall (`off`). `plain` is Qloo's top 7 by taste (fit order over U, floor applied, no strike, no popularity term). *named* = named by any dated wall answer or held-out fresh-ask answer (matcher + reverse check); *fresh* = the held-out fresh asks only, which never fed the wall. *struck* = members of the list the real wall crosses out. Qloo calls: 0 network, 1987 cache.

**Median over 20 sets: 2.0 of 7 cards differ; AI-named cards: with the wall 0.0, without it 1.5, Qloo's plain top 7 4.5 (held-out fresh asks only: 0.0, 0.0, 1.0).**

| set | U | struck in U | cards differ | named: on | off | plain | fresh: on | off | plain | plain struck | plain in on |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| nyc-khruangbin | 182 | 81 | 1 of 7 | 0 | 1 | 3 | 0 | 0 | 0 | 3 | 0 |
| nyc-taylorswift | 220 | 75 | 2 of 7 | 0 | 1 | 3 | 0 | 0 | 1 | 2 | 0 |
| nyc-wutang | 234 | 86 | 2 of 7 | 0 | 2 | 5 | 0 | 0 | 1 | 3 | 1 |
| nyc-newjeans | 186 | 88 | 0 of 7 | 0 | 0 | 6 | 0 | 0 | 1 | 6 | 1 |
| nyc-badbunny | 192 | 91 | 2 of 7 | 0 | 1 | 3 | 0 | 0 | 2 | 2 | 0 |
| nyc-coltrane | 262 | 136 | 4 of 7 | 0 | 4 | 7 | 0 | 2 | 1 | 7 | 0 |
| nyc-kendrick | 192 | 72 | 0 of 7 | 0 | 0 | 2 | 0 | 0 | 1 | 1 | 1 |
| nyc-stapleton | 163 | 65 | 2 of 7 | 0 | 1 | 2 | 0 | 0 | 0 | 3 | 0 |
| nyc-arthurrussell | 247 | 103 | 2 of 7 | 0 | 2 | 4 | 0 | 1 | 1 | 3 | 1 |
| nyc-rosalia | 154 | 64 | 4 of 7 | 1 | 4 | 2 | 1 | 0 | 0 | 2 | 1 |
| stl-cedric | 78 | 28 | 2 of 7 | 0 | 1 | 2 | 0 | 0 | 0 | 2 | 3 |
| stl-jason | 205 | 138 | 4 of 7 | 1 | 4 | 7 | 1 | 4 | 4 | 7 | 0 |
| stl-nelly | 176 | 112 | 2 of 7 | 1 | 1 | 5 | 0 | 1 | 3 | 5 | 0 |
| stl-chuckberry | 202 | 130 | 3 of 7 | 1 | 3 | 7 | 1 | 1 | 4 | 7 | 0 |
| stl-sza | 162 | 104 | 0 of 7 | 0 | 0 | 3 | 0 | 0 | 2 | 2 | 0 |
| stl-wilco | 195 | 123 | 3 of 7 | 0 | 2 | 6 | 0 | 0 | 1 | 6 | 0 |
| stl-taylorswift | 208 | 149 | 4 of 7 | 0 | 4 | 7 | 0 | 2 | 4 | 7 | 0 |
| stl-jayz | 189 | 104 | 3 of 7 | 0 | 1 | 2 | 0 | 0 | 1 | 2 | 2 |
| stl-bigthief | 196 | 131 | 4 of 7 | 0 | 4 | 6 | 0 | 0 | 3 | 6 | 0 |
| stl-morganwallen | 165 | 103 | 3 of 7 | 0 | 3 | 6 | 0 | 1 | 2 | 6 | 0 |
| **median** | | | **2.0** | **0.0** | **1.5** | **4.5** | **0.0** | **0.0** | **1.0** | **3.0** | |

## Baselines: is it just obscure?

Held-out fresh asks only (they never fed the wall). One per-place verdict over U (matcher with the strike's /search vetoes + the reverse check), so every arm is judged the same way; these pooled counts can differ slightly from the 7-name check in the table above. Fit percentile: 1.0 = Qloo's best fit for these loves in U. Popularity percentile: 1.0 = the most popular place in U.

| arm | held-out AI-named, pooled | NYC | STL | median fit pct | median popularity pct |
|---|---:|---:|---:|---:|---:|
| Qloo's plain top 7 (fused taste order, no rules) | 32 of 140 | 8 of 70 | 24 of 70 | 0.98 | 0.77 |
| PLAIN+RULES (taste order + the picks rules, no strike, no popularity/prior term) | 21 of 140 | 8 of 70 | 13 of 70 | 0.89 | 0.54 |
| score-only (UNSAID without the strike) | 12 of 140 | 3 of 70 | 9 of 70 | 0.80 | 0.21 |
| UNSAID (strike + score + rules) | 3 of 140 | 1 of 70 | 2 of 70 | 0.77 | 0.21 |
| RANDOM-7 (7 random survivors of strike + floor, mean of 200 draws) | 2.4 of 140 | 1.0 of 70 | 1.4 of 70 | 0.47 | 0.31 |

RANDOM-7 mean fit percentile: 0.48 (UNSAID 0.76). Per set, held-out AI-named (UNSAID · RANDOM-7 mean): nyc-khruangbin 0 · 0.1, nyc-taylorswift 0 · 0.1, nyc-wutang 0 · 0.1, nyc-newjeans 0 · 0.1, nyc-badbunny 0 · 0.1, nyc-coltrane 0 · 0.0, nyc-kendrick 0 · 0.1, nyc-stapleton 0 · 0.1, nyc-arthurrussell 0 · 0.1, nyc-rosalia 1 · 0.2, stl-cedric 0 · 0.2, stl-jason 1 · 0.1, stl-nelly 0 · 0.1, stl-chuckberry 1 · 0.2, stl-sza 0 · 0.1, stl-wilco 0 · 0.2, stl-taylorswift 0 · 0.1, stl-jayz 0 · 0.1, stl-bigthief 0 · 0.2, stl-morganwallen 0 · 0.1.

Cards still matched with the wall ON, all sets: (a) only a held-out fresh ask matches it: 2 · (b) a dated wall answer the strike missed: 2 · (c) a containment match the strike overruled because Qloo /search resolved the AI name to another place (not counted): 8.

Place names are left out here: they are Qloo output, which stays out of git. The full table with names is engine/out/k12_wall_effect.md (gitignored).
