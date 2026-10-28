# K13 · Qloo's joint signal vs per-love fusion

Engine `unsaid-engine-4.0`, 20 sets, over the SAME fixed pool U the engine builds (floor applied). *J* = ONE `signal.interests.entities` call with all the set's entity loves (dead ones included) and `feature.explainability=true`, rescoring U in the engine's 48 + 2-anchor `filter.results.entities` chunks. *fused* = the engine's RRF (k = 60) over the live loves' per-love orders. *J7* = the engine with its for-you score replaced by J's affinity (same strike, same lift formula, same per-love holds and because: option b). *B7* = J added as one more RRF voter beside the live loves (option c). *named* = k12's check (dated wall + held-out fresh asks; *fresh* = held-out only). Counts only; names stay in `engine/out/k13_joint.json` (gitignored). Everyone-prior for the lift: built 2026-10-28T12:17:25+0100. Live Qloo calls for the experiment: 252 (this run: 0 network, 3118 cache) + 40 payload probe (measured on an earlier run, reused).

## Summary (medians over 20 sets; pooled counts of 140 cards where it says so)

- **Order over U:** Spearman ρ(fused, J) median **0.64** (range 0.41 to 0.97). ρ with popularity: J **0.14**, fused **0.18** (lower = further from "what everyone likes").
- **Top 7 by taste alone** (no strike, no lift): fused and J share a median **5.0 of 7**.
- **The seven cards** (same strike, same lift, same holds): J7 shares a median **5.0 of 7** with the engine's seven; B7 shares **5.0 of 7**.
- **AI-named cards (k12 check)**, median per set · pooled: engine **0.0 · 2**, J7 **0.0 · 0**, B7 **0.0 · 1**; held-out fresh only: 0.0 · 1, 0.0 · 0, 0.0 · 0. Qloo's plain top 7: fused 4.0 · 87, J 4.0 · 83.
- **Because:** on the engine's 140 cards, J's explainability names the same love as the engine's "because" on **66**, another love on **39**; on **35** the engine's because is a dish, which an entity-only joint call cannot name; 0 had no explainability. On J7's own cards: 88 of 137 agree. Explainability is flat: the top love's share is a median **0.51**, its margin over the second **0.05**; across all of U one love takes a median **0.79** of the argmax credit.
- **Holds if you drop any one love** (n of n), pooled: engine seven **32** of 140 (per-love RRF); J7 **39** of 140 under the same per-love check, **53** under the joint leave-one-out (J without each entity love); the engine's seven under the joint leave-one-out **40**. B7 per-love: 38.
- **J itself:** coverage of U median 0.99, tie share at Qloo's default affinity 0.00, anchor drift max 0.0000, explainability warnings 0, failed chunks 0.

| set | U | live/loves | ρ fused·J | ρ J·pop | ρ fused·pop | plain 7 shared | seven shared J7 · B7 | because agree · differ · dish | named eng · J7 · B7 | fresh eng · J7 · B7 | holds n/n eng · J7 · J7 joint-LOO |
|---|---:|---|---:|---:|---:|---:|---|---|---|---|---|
| nyc-khruangbin | 182 | 3/3 | 0.62 | 0.10 | 0.12 | 1 | 5 · 6 | 1 · 6 · 0 | 0 · 0 · 0 | 0 · 0 · 0 | 0 · 0 · 1 |
| nyc-taylorswift | 220 | 3/3 | 0.64 | 0.52 | 0.11 | 6 | 2 · 4 | 2 · 0 · 5 | 0 · 0 · 0 | 0 · 0 · 0 | 0 · 1 · 2 |
| nyc-wutang | 234 | 3/3 | 0.64 | 0.23 | 0.20 | 5 | 3 · 5 | 2 · 4 · 1 | 0 · 0 · 0 | 0 · 0 · 0 | 0 · 1 · 1 |
| nyc-newjeans | 186 | 3/3 | 0.56 | 0.45 | 0.24 | 3 | 3 · 5 | 4 · 2 · 1 | 0 · 0 · 0 | 0 · 0 · 0 | 0 · 1 · 3 |
| nyc-badbunny | 192 | 3/3 | 0.52 | 0.35 | -0.00 | 6 | 1 · 3 | 0 · 1 · 6 | 0 · 0 · 0 | 0 · 0 · 0 | 0 · 2 · 4 |
| nyc-coltrane | 262 | 2/3 | 0.63 | 0.12 | 0.23 | 6 | 5 · 5 | 7 · 0 · 0 | 0 · 0 · 0 | 0 · 0 · 0 | 0 · 0 · 0 |
| nyc-kendrick | 192 | 3/3 | 0.46 | -0.14 | 0.03 | 5 | 5 · 5 | 7 · 0 · 0 | 0 · 0 · 0 | 0 · 0 · 0 | 2 · 1 · 1 |
| nyc-stapleton | 163 | 3/3 | 0.64 | 0.06 | 0.18 | 6 | 5 · 5 | 5 · 0 · 2 | 0 · 0 · 0 | 0 · 0 · 0 | 3 · 5 · 7 |
| nyc-arthurrussell | 247 | 3/3 | 0.50 | 0.15 | 0.28 | 5 | 3 · 4 | 3 · 0 · 4 | 0 · 0 · 0 | 0 · 0 · 0 | 0 · 0 · 0 |
| nyc-rosalia | 154 | 3/3 | 0.77 | 0.07 | 0.15 | 4 | 4 · 5 | 4 · 0 · 3 | 1 · 0 · 0 | 1 · 0 · 0 | 1 · 1 · 1 |
| stl-cedric | 78 | 3/3 | 0.91 | -0.05 | -0.16 | 6 | 5 · 5 | 0 · 5 · 2 | 0 · 0 · 0 | 0 · 0 · 0 | 4 · 6 · 7 |
| stl-jason | 205 | 3/3 | 0.91 | 0.38 | 0.32 | 5 | 4 · 6 | 7 · 0 · 0 | 0 · 0 · 0 | 0 · 0 · 0 | 0 · 1 · 2 |
| stl-nelly | 177 | 3/3 | 0.74 | 0.07 | 0.18 | 1 | 3 · 6 | 2 · 0 · 5 | 1 · 0 · 1 | 0 · 0 · 0 | 0 · 0 · 0 |
| stl-chuckberry | 203 | 3/3 | 0.91 | 0.42 | 0.39 | 5 | 6 · 7 | 5 · 2 · 0 | 0 · 0 · 0 | 0 · 0 · 0 | 3 · 3 · 2 |
| stl-sza | 162 | 3/3 | 0.73 | 0.01 | 0.18 | 4 | 5 · 6 | 2 · 1 · 4 | 0 · 0 · 0 | 0 · 0 · 0 | 2 · 3 · 5 |
| stl-wilco | 150 | 3/3 | 0.97 | 0.17 | 0.11 | 7 | 6 · 7 | 3 · 4 · 0 | 0 · 0 · 0 | 0 · 0 · 0 | 5 · 4 · 4 |
| stl-taylorswift | 208 | 3/3 | 0.41 | 0.04 | 0.36 | 3 | 6 · 7 | 1 · 6 · 0 | 0 · 0 · 0 | 0 · 0 · 0 | 3 · 2 · 3 |
| stl-jayz | 189 | 3/3 | 0.54 | 0.01 | 0.04 | 1 | 5 · 6 | 3 · 4 · 0 | 0 · 0 · 0 | 0 · 0 · 0 | 4 · 2 · 1 |
| stl-bigthief | 197 | 3/3 | 0.92 | 0.27 | 0.27 | 7 | 7 · 7 | 6 · 1 · 0 | 0 · 0 · 0 | 0 · 0 · 0 | 4 · 4 · 4 |
| stl-morganwallen | 165 | 3/3 | 0.93 | 0.30 | 0.24 | 7 | 5 · 5 | 2 · 3 · 2 | 0 · 0 · 0 | 0 · 0 · 0 | 1 · 2 · 5 |

Which love J follows: ρ(J, a love's own per-love order), median over sets: the artist **0.79**, the film/show **0.78**, the third love **-0.29** when it is a dish (14 sets) and **0.48** when it is a place or brand (6 sets).

## A dead love inside the joint signal (0 sets)

The engine drops a love whose own order is popularity (ρ ≥ 0.95) or a tie. J has no such step: it takes every entity it is given and returns no flag. *J_live* = J without the dead love.

No ENTITY love is dead in these 20 sets (the brand loves stay live: their own orders are not popularity). Dead loves here: nyc-coltrane's dish (ties 1.00), dishes only; what J does with a dish is the next section.

## A dish (tag) love inside the joint signal (14 sets)

The engine never puts an entity and a tag in one call (the client's never-send rule). Here J_mix sends them together over the same U chunks with explainability, as a probe. *tagged* = U members carrying the dish tag or returned by its dish sub-pool.

Pooled over 14 sets: dish-tagged places in the seven, engine **35** vs J7 **3**; in the plain taste top 7, fused 13 · J 1 · J_mix 9. The tag shows up in J_mix's explainability for **0** places (top-level keys: entities only). J_mix's order equals J's (ρ ≥ 0.99) in **9** of 14 sets: the tag is ignored; in the other 5, Qloo leaves a median **12%** of U out of the response (up to 26%), so the order is J's minus places, not J plus the dish.

| set | dish dead in engine | J_mix scored of U | tie share | ρ J_mix·J | tag in explain (places) | tag explain share | tagged in U | tagged in top 7: fused · J · J_mix | in the seven: engine · J7 | top-level keys |
|---|---|---:|---:|---:|---:|---:|---:|---|---|---|
| nyc-taylorswift | no | 163 of 220 | 0.00 | 1.00 | 0 | 0.00 | 64 | 0 · 0 · 0 | 5 · 0 | signal.interests.entities |
| nyc-wutang | no | 232 of 234 | 0.00 | 1.00 | 0 | 0.00 | 2 | 0 · 0 · 0 | 1 · 0 | signal.interests.entities |
| nyc-newjeans | no | 163 of 186 | 0.00 | 0.64 | 0 | 0.00 | 30 | 1 · 0 · 0 | 1 · 0 | signal.interests.entities |
| nyc-badbunny | no | 181 of 192 | 0.00 | 1.00 | 0 | 0.00 | 26 | 0 · 0 · 0 | 6 · 0 | signal.interests.entities |
| nyc-coltrane | ties 1.00 | 262 of 262 | 0.00 | 1.00 | 0 | 0.00 | 0 | 0 · 0 · 0 | 0 · 0 | signal.interests.entities |
| nyc-stapleton | no | 150 of 163 | 0.00 | 0.37 | 0 | 0.00 | 28 | 0 · 0 · 0 | 2 · 0 | signal.interests.entities |
| nyc-arthurrussell | no | 242 of 247 | 0.00 | 1.00 | 0 | 0.00 | 13 | 2 · 0 · 0 | 4 · 0 | signal.interests.entities |
| nyc-rosalia | no | 117 of 154 | 0.00 | 0.00 | 0 | 0.00 | 73 | 2 · 0 · 3 | 3 · 0 | signal.interests.entities |
| stl-cedric | no | 74 of 78 | 0.00 | 1.00 | 0 | 0.00 | 5 | 1 · 0 · 0 | 2 · 0 | signal.interests.entities |
| stl-nelly | no | 151 of 177 | 0.00 | 0.31 | 0 | 0.00 | 53 | 5 · 0 · 4 | 5 · 1 | signal.interests.entities |
| stl-sza | no | 154 of 162 | 0.00 | 0.31 | 0 | 0.00 | 28 | 1 · 0 · 1 | 4 · 2 | signal.interests.entities |
| stl-wilco | no | 149 of 150 | 0.00 | 1.00 | 0 | 0.00 | 1 | 0 · 0 · 0 | 0 · 0 | signal.interests.entities |
| stl-bigthief | no | 195 of 197 | 0.00 | 1.00 | 0 | 0.00 | 5 | 0 · 0 · 0 | 0 · 0 | signal.interests.entities |
| stl-morganwallen | no | 163 of 165 | 0.00 | 1.00 | 0 | 0.00 | 5 | 1 · 1 · 1 | 2 · 0 | signal.interests.entities |

## Is explainability on the single-love pool calls wasted payload?

The engine sends `feature.explainability=true` on each entity love's C4 page 1 (offset 0), for the raw log only; nothing downstream reads it except the k7 gate. On a single-love call it can only say "this love, 1.0": 500 of 500 page-1 results carry exactly that and nothing else. The same request with and without it, 10 pools × 2 reps, no cache, alternating order (medians):

| | n | ms | body bytes (JSON) | wire bytes (gzip) |
|---|---:|---:|---:|---:|
| with explainability | 20 | 804 | 1157080 | 176170 |
| without explainability | 20 | 1034 | 1151057 | 175896 |
| saved per call (ms: paired per pool) | | 45 | 6023 (0.5%) | 274 (0.2%) |

Result order identical with and without it in 10 of 10 pools. Paired per pool (same request back to back), the ms difference is a median 45 ms, ranging -287 to 535 ms: noise, not a saving. A query sends one such call per entity love (2 or 3), so dropping it saves about 12 to 18 KB of decoded JSON and 0.5 to 0.8 KB on the wire per query, and no measurable time.

## Cost

Per query the engine rescoring is (live + dish loves) × ceil((|U| − 2) / 48) calls in parallel. J alone would be ceil((|U| − 2) / 48) (median 4 here). Option (b) still needs the per-love calls for because and holds, so it ADDS J's calls; it saves none. J's live chunk calls (with explainability) took a median 644 ms each.

## Recommendation: (a) keep per-love fusion

1. **The joint signal cannot carry a dish, and 14 of 20 sets have one.** Per-love fusion ranks the dish through its own order (the dish sub-pool and tag), so the engine's seven hold 35 dish-tagged places; J7 holds 3. 35 of the engine's 140 because-lines name the dish; an entity-only joint call cannot. Putting the tag in the same call does not fix it: the tag never appears in explainability, and the order either ignores it or loses places from U.
2. **Explainability is too flat to be a because.** Top share median 0.51, margin over the second love 0.05, and one love takes a median 0.79 of the argmax credit across U. Where both can speak, it names the engine's love on 66 of 105 cards, and the shares it gives are too close to state as a reason.
3. **Switching buys nothing the product measures.** AI-named cards pooled: engine 2, J7 0, B7 1 (the strike does that work either way); ρ with popularity: J 0.14 vs fused 0.18. J7 keeps a median 5.0 of the engine's 7 cards; on the 6 entity-only sets J7 holds n/n 9 vs the engine's 12. The one thing J does better (J7 holds n/n 39 vs 32 pooled) comes from the dish sets: J7's cards are the ones strongest on the two entity loves, so dropping the dish cannot move them.
4. **(b) and (c) cost calls and save none.** Both keep the per-love calls (because, holds, dead-love detection) and add J's chunk calls on top. The blend shares a median 5.0 of 7 with the engine and changes nothing measured.

Answer for the judge: we compared them on the same pool. The joint order is a real alternative for entity loves (ρ 0.64 with ours, same popularity lean), but it has no place for a dish, it returns no sign that a love is dead, and its explainability splits about evenly between loves, so per-love orders are what make "because you love X" and "holds if you drop any one love" true statements. The page-1 explainability on single-love pool calls is redundant (always "this love, 1.0") and can go; it saves about 0.5% of the body and no measurable time, and k7 would then need its own call.
