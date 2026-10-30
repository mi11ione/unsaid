# K12 · what crossing out changes

Engine `unsaid-engine-4.0`. The same pipeline ran twice per set over the same U: with the real dated wall (`on`) and with an empty wall (`off`). `plain` is Qloo's top 7 by taste (fit order over U, floor applied, no strike, no popularity term). *named* = named by any dated wall answer or held-out fresh-ask answer (matcher + reverse check); *fresh* = the held-out fresh asks only, which never fed the wall. *struck* = members of the list the real wall crosses out. Qloo calls: 0 network, 1610 cache.

**Median over 20 sets: 3.0 of 7 cards differ; AI-named cards: with the wall 0.0, without it 2.5, Qloo's plain top 7 4.5 (held-out fresh asks only: 0.0, 0.0, 1.0).**

| set | U | struck in U | cards differ | named: on | off | plain | fresh: on | off | plain | plain struck | plain in on |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| nyc-khruangbin | 167 | 80 | 2 of 7 | 0 | 2 | 3 | 0 | 0 | 1 | 3 | 0 |
| nyc-taylorswift | 205 | 72 | 2 of 7 | 0 | 1 | 4 | 0 | 0 | 1 | 3 | 0 |
| nyc-wutang | 223 | 88 | 3 of 7 | 0 | 3 | 5 | 0 | 0 | 1 | 3 | 1 |
| nyc-newjeans | 175 | 84 | 1 of 7 | 0 | 0 | 6 | 0 | 0 | 1 | 6 | 1 |
| nyc-badbunny | 178 | 86 | 2 of 7 | 0 | 1 | 4 | 0 | 0 | 1 | 3 | 0 |
| nyc-coltrane | 253 | 134 | 5 of 7 | 0 | 5 | 6 | 0 | 1 | 1 | 7 | 0 |
| nyc-kendrick | 179 | 70 | 0 of 7 | 1 | 1 | 2 | 0 | 0 | 1 | 1 | 2 |
| nyc-stapleton | 153 | 62 | 3 of 7 | 1 | 2 | 2 | 0 | 0 | 0 | 3 | 0 |
| nyc-arthurrussell | 235 | 98 | 3 of 7 | 0 | 3 | 4 | 0 | 1 | 1 | 3 | 1 |
| nyc-rosalia | 224 | 89 | 4 of 7 | 1 | 5 | 2 | 0 | 0 | 0 | 2 | 1 |
| stl-cedric | 75 | 28 | 2 of 7 | 0 | 1 | 2 | 0 | 0 | 0 | 2 | 1 |
| stl-jason | 201 | 137 | 4 of 7 | 0 | 4 | 7 | 0 | 4 | 4 | 7 | 0 |
| stl-nelly | 174 | 113 | 3 of 7 | 1 | 2 | 5 | 0 | 1 | 3 | 5 | 0 |
| stl-chuckberry | 197 | 129 | 5 of 7 | 0 | 4 | 7 | 0 | 2 | 4 | 7 | 0 |
| stl-sza | 158 | 103 | 1 of 7 | 0 | 1 | 3 | 0 | 0 | 2 | 2 | 0 |
| stl-wilco | 190 | 124 | 3 of 7 | 0 | 3 | 6 | 0 | 0 | 1 | 6 | 0 |
| stl-taylorswift | 205 | 148 | 4 of 7 | 0 | 4 | 7 | 0 | 2 | 4 | 7 | 0 |
| stl-jayz | 185 | 104 | 4 of 7 | 0 | 1 | 2 | 0 | 0 | 1 | 2 | 1 |
| stl-bigthief | 191 | 132 | 4 of 7 | 0 | 4 | 6 | 0 | 0 | 3 | 6 | 0 |
| stl-morganwallen | 162 | 104 | 3 of 7 | 0 | 3 | 6 | 0 | 1 | 2 | 6 | 0 |
| **median** | | | **3.0** | **0.0** | **2.5** | **4.5** | **0.0** | **0.0** | **1.0** | **3.0** | |

## Baselines: is it just obscure?

Held-out fresh asks only (they never fed the wall). One per-place verdict over U (matcher with the strike's /search vetoes + the reverse check), so every arm is judged the same way; these pooled counts can differ slightly from the 7-name check in the table above. Fit percentile: 1.0 = Qloo's best fit for these loves in U. Popularity percentile: 1.0 = the most popular place in U.

| arm | held-out AI-named, pooled | NYC | STL | median fit pct | median popularity pct |
|---|---:|---:|---:|---:|---:|
| Qloo's plain top 7 (fused taste order, no rules) | 32 of 140 | 8 of 70 | 24 of 70 | 0.98 | 0.76 |
| PLAIN+RULES (taste order + the picks rules, no strike, no popularity/prior term) | 17 of 140 | 4 of 70 | 13 of 70 | 0.86 | 0.55 |
| score-only (UNSAID without the strike) | 12 of 140 | 2 of 70 | 10 of 70 | 0.79 | 0.21 |
| UNSAID (strike + score + rules) | 0 of 140 | 0 of 70 | 0 of 70 | 0.75 | 0.19 |
| RANDOM-7 (7 random survivors of strike + floor, mean of 200 draws) | 2.5 of 140 | 1.0 of 70 | 1.4 of 70 | 0.47 | 0.31 |

RANDOM-7 mean fit percentile: 0.48 (UNSAID 0.73). Per set, held-out AI-named (UNSAID · RANDOM-7 mean): nyc-khruangbin 0 · 0.1, nyc-taylorswift 0 · 0.1, nyc-wutang 0 · 0.1, nyc-newjeans 0 · 0.1, nyc-badbunny 0 · 0.1, nyc-coltrane 0 · 0.1, nyc-kendrick 0 · 0.1, nyc-stapleton 0 · 0.1, nyc-arthurrussell 0 · 0.1, nyc-rosalia 0 · 0.1, stl-cedric 0 · 0.2, stl-jason 0 · 0.1, stl-nelly 0 · 0.1, stl-chuckberry 0 · 0.2, stl-sza 0 · 0.2, stl-wilco 0 · 0.2, stl-taylorswift 0 · 0.1, stl-jayz 0 · 0.1, stl-bigthief 0 · 0.2, stl-morganwallen 0 · 0.1.

Cards still matched with the wall ON, all sets: (a) only a held-out fresh ask matches it: 0 · (b) a dated wall answer the strike missed: 4 · (c) a containment match the strike overruled because Qloo /search resolved the AI name to another place (not counted): 12.

Place names are left out here: they are Qloo output, which stays out of git. The full table with names is engine/out/k12_wall_effect.md (gitignored).
