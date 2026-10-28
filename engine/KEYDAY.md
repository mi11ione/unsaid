# Key day: the engine checklist

The steps run in UNSAID.md §5 order. UNSAID.md wins over this file. Run everything from `engine/`. Each line to read is the script's last verdict line. Every script prints `QLOO_NETWORK_CALLS=n`, and with `--budget N` it stops before the (N+1)-th network call (cache hits cost 0). Results and Qloo data stay in `out/` and `.cache/`, which git ignores.

```bash
cd /Users/mi11ion/Desktop/qloo/unsaid/engine
export QLOO_API_KEY=…                 # sent only in the X-Api-Key header
W=../data/walls                       # dir or one file; dir = every *.json merged (wall-N + census), like the server
```

## Call budget

Cached reruns cost 0. The insights cache lasts 24 h and `/search` 30 d, so a rerun the next day pays again. A cold set costs about 3 C2 + 2 per entity love (C4) + 3 × ⌈|U|/48⌉ (C6′) + 5–15 (C7) + 1 (CAP), which is 25–40 live. Fake measured 21–23 per set.

| # | step | live estimate | fake, measured cold, same order |
|---|---|---|---|
| 1 | probes P1–P12 (P9 at 5 s) | 45–60 (P9 at 30 s: +75) | 39 |
| 3 | K1 | 150–180 | 145 |
| 4 | A | 375–700 | 205 |
| 5 | K8 + K4 relabel | 6 + 0 | 6 + 0 |
| 6 | B | 0 if run with the same `--walls` as A; otherwise 120–320 | 0 |
| 7–8 | C + first run_query | 0 (cached by A/B) | 0 |
| 9 | k10 | 0 by construction | 0 |
| 10 | k5 | 0 with `--cards`, or with a warm cache | 0 |
| — | k9 (only if P12 ≠ popularity) | ~12 | 6 |
| **total** | | **≈ 580–950** | **401** |

Use `--budget 1000` for the day; the oracle warns that tablefair burned its whole month on evaluations. Leave about 2,000 of the 10,000 for precompute (~30 per try-these set, about 300) and for gate F and live traffic. The quota guard stops fresh runs at 85 % of the month, using the header names P9 records.

## 1 · Probes P1–P12 (K+0:00)

```bash
python3 -I probes.py --city both --budget 80
```
- **Read:** `Probes P1-P12: 12 ran, 0 failed -> PASS`. Decisions go to `out/probes.json`; header names go to `.cache/live/p9_headers.json`.
- **On FAIL** (a probe errored): read its `ERROR` line, fix the parameter, and rerun. The other probes come from the cache for free.
- **§4 pivot:** if P12 is not popularity → `BASELINE="nosignal"` (C5, +~5 calls per query), then run `python3 -I k9_baseline.py --budget 30`. P2 decides the floor.

## 2 · CFG set points (K+0:45, Roman). Edit `unsaid/engine.py` CFG and `unsaid/cities.py` CITIES

| set point | where | decided by | rule |
|---|---|---|---|
| paging | `CFG["OFFSETS"]` = [0, 50] | P1 | keep if offset 0/50 are disjoint. EXTRA_OFFSETS stays [] (§3.1) |
| server floor | `CFG["RATING_SERVER"]` = 4 | P2 | keep if `4 -> min 4.0`. If 4 is ignored, the client floor alone carries it |
| client floor | `CFG["RATING_CLIENT"]` 4.3 − 1e-4 | P8 rating coverage | keep while business_rating is on ≥ 90 % |
| field paths | `qloo.prop()` | P3 | if any field prints `ABSENT`, add its path |
| C6′ usable | `CFG["CHUNK"]`/`ANCHORS` | P4 | 30/30 back with a signal; if not, lower CHUNK |
| trends | pinned `off` | P5 | no decision: the client enforces it |
| kind tags | `CFG["CAT_TAGS"]` | P6 | category restaurant ∪ bar; if it returns 0, fall back to `genre:place:restaurant` + allowlist |
| allowlist | `CFG["EXCLUDE_TAG_PATTERNS"/"_NAMES"]` | P8 tag IDs (`allowlist {...}`, `music venue n`) | swap the patterns for the real IDs. Watch `not_venue_music`: if it catches restaurants, drop the music patterns |
| hours check | `CFG["HOURS_COVERAGE_MIN"]` 0.5 | P8 hours % | the hours part of last-seen applies only above it |
| pacing | `qloo.RATE`/`BURST` 3/s, 5 | P9 429s | any 429 at 3/s → 2.5/s |
| quota guard | automatic | P9 header names | check that `quota guard reads <remaining> / <limit>` is not `None` |
| R and location | `cities.py` radius_mi/radius_m, mode | P10 distance p90, outside-R, U after floor | STL: POINT vs locality U. The Cedric city (STL or LA) is decided by K+1:00 |
| thin_taste | `CFG["THIN_TIE"]` 0.30 | P11 | informational; the threshold stays |
| anyone / RHO_RES | `CFG["BASELINE"]` | P12 ρ ≥ 0.99 | `popularity` → RHO_RES undefined (null; the sentence is deleted). Otherwise `nosignal` → RHO_RES = partial ρ |

## 3 · K1 density (K+1:00)

```bash
python3 -I k1_density.py --city both --budget 220
```
- **Read:** `K1 density: PASS|FAIL`, and the per-city line `|U|>=150 in n of 10`.
- **§4 pivot on FAIL (shared with B):** widen R first (`cities.py`). Keep holds at 2 of 3 (the current rule for three loves) and show `empty_few` proudly. If STL has fewer than 5 sets or any junk → the NYC hero, and Cedric's on-air city becomes LA (POINT + 15 mi).

## 4 · Gate A, taste moves (K+2:00)

```bash
python3 -I k2a_lift.py --city both --walls $W --budget 750
```
- **Read:** `A taste moves: PASS|FAIL`, `two strangers … sevens share k (gate <=2)` and ``STRANGERS` = k`. ρ_AB and the top-50 Jaccard are printed but not gated.
- **§4 pivot on FAIL:** per-love RRF is already on. Then try place-led seeds (one love is a bar you love), drop "#151 for anyone" from the card fronts, and use the copy "new to you". Never ship a rank that doesn't move.

## 5 · K8 closures + the live K4 relabel (K+3:00)

```bash
python3 -I k8_closed.py --budget 20
python3 -I k4_relabel.py --export --city both --walls $W --budget 20   # out/k4_<set>.csv + .pool.csv
#   fill `truth` by hand: the U id(s) the AI name means (from .pool.csv), ';'-separated, or `none`
python3 -I k4_relabel.py --score
```
- **Read:** `K8 is_closed: n of 3` (fills `K8`), and `K4 live relabel: false survivors n (gate 0)` (fills `LABELLED`, `FALSE_SURV`, `PREC`).
- **§4 pivot:** K8 FAIL → the last-seen check carries it, and Shown says so. K4 FAIL → raise the guard and accept over-striking.

## 6 · Gate B, survivors (K+3:30)

```bash
python3 -I k3_survivors.py --city both --walls $W --budget 350
```
- **Read:** `B survivors: PASS|FAIL`. A set passes with |U| ≥ 150, 7 + 3 cards, no junk and tie < 0.30. The gate needs ≥ 8/10 in NYC and ≥ 6/10 in STL. Each set's floor line includes `not_venue_music`.
- **§4 pivot on FAIL:** the same as K1. Roman makes the STL-or-NYC hero call here.

## 7–8 · Gate C + the first run_query (K+4:30 / K+5:00)

```bash
python3 -I run_query.py --city stl --set stl-cedric --walls $W --budget 60     # "cedric" also works
```
- **Read:** `C not a cap: cap overlap x (gate <=0.80) … -> PASS|FAIL` and `run_query: 7 cards, n Qloo calls, status ok -> PASS`.
- **README trace:** `out/query_stl-cedric.md`. It fills `WALL` `ASKS` `U` `R` `FIT` `ANY` `QLOO_CALLS` `A` `B` `C` `CAP_KEEP` `CAP_SHARED` `OBSCURE` `KNOWN` `RHO_TP` `RHO_RES`. `RHO_RES` prints `RHO_RES undefined (base = popularity)` when P12 said popularity.
- **§4 pivot on C FAIL:** all three proofs still ship with real numbers. The claim drops to "the wall is the proof you can read", and the strangers' pair leads image 3.

## 9 · Gate D, meter (K+5:00, after B's harness ran `meter.py`)

```bash
python3 -I k10_meter.py --city stl --meter ../harness/runs/meter.jsonl --walls $W
```
- **Read:** `D meter: … -> PASS|FAIL` and ``M_ALONE` … `M_QLOO``. It makes 0 Qloo calls, and each run is graded by the other AIs' generic answers.
- **§4 rule:** featured only on PASS. Either way it is printed in Shown and the README; on FAIL, Elias gets the residual line.

## 10 · Gate E, fresh asks (K+6:00, after the 20 sets' cards are frozen)

```bash
python3 -I precompute.py --walls $W --sets 10 --accept-top --out /tmp/unsaid-frozen      # outside git; ~0 if warm
python3 -I k5_fresh.py --fresh ../data/fresh_asks.json --answers ../harness/runs/fresh.jsonl --cards /tmp/unsaid-frozen --walls $W
```
- **Read:** `E fresh asks: median m of 7 (gate <=1, 20 sets) -> PASS|FAIL`, with `FA_Q` `FA_SETS` `FA_HITS` `FA_CARDS` `FA_MED`. The hash check must print `0 collisions`.
- **§4 pivot on FAIL:** add the 16 gem phrasings' second pass to the wall and rerun once. If it still fails, cut the dare-as-promise, print "named by n of m" in Shown, and use the weak-data line on air.

## Afterwards

- **Gate F** is Wed 16:00 (agent A): `python3 -I k11_latency.py --url https://<host>/api/unsaid --runs 10` from the phone-tethered machine. It sends `loves` as a JSON array.
- **Try-these:** `python3 -I precompute.py --walls $W --out <dir outside git>` writes the sets marked `try_these` in `data/sets.json` (else `sets.draft.json`).
- **Everything at once:** `python3 -I run_all.py --walls $W --budget 1000` runs the same order with one shared budget and a running total.
