# UNSAID

**AI sends everyone to Mai Lee. Your taste sends you elsewhere.**

Ask Claude for a hidden gem in St. Louis and it says Mai Lee, on 13 of 16 tries; ChatGPT says it 10 times. Tell UNSAID three things you love. It crosses out every place Claude, ChatGPT and Gemini named in ⟦ASKS_STL⟧ dated asks about the city, and Qloo ranks what's left for your taste: seven places, each with Qloo's photo, what people order there, and why.

On 40 public questions never used to build the list, the AIs named ⟦K12_PLAIN_FRESH_U⟧ of 140 cards from Qloo's plain taste order and ⟦K12_UNSAID_FRESH_U⟧ of UNSAID's; seven random leftovers are named about as rarely but fit far worse (⟦K12_RANDOM_FIT_MED⟧th vs ⟦K12_UNSAID_FIT_MED⟧th fit percentile). Method and every gate, pass or fail: [Gates](#gates).

**Live:** ⟦LIVE_URL⟧ · **Agents:** [MCP](#mcp) · **License:** MIT ([LICENSE](LICENSE)); map data © OpenStreetMap contributors, ODbL 1.0.

<!-- ⟦X⟧ = a number the 30 Oct 12:00 ET freeze fills, from the script named beside it. None ships. -->

## Five minutes

**1. The live demo.** Open ⟦LIVE_URL⟧ and tap **Frankie Beverly & Maze · The Original Kings of Comedy · rib tips**. Tap a card for its detail; tap ✕ to strike one you know and a reserve takes its place; paste any AI's answer and anything it names is already crossed out. Or type three things you love. Cards arrive in about ⟦P50⟧ seconds.

**2. From your agent, no Qloo key, one paste.** Add `https://unsaid-ang.pages.dev/mcp` as a custom connector in Claude (Settings → Connectors), or run the line below.

```bash
claude mcp add --transport http unsaid "https://unsaid-ang.pages.dev/mcp"
# then ask Claude: "I love Frankie Beverly & Maze, The Original Kings of Comedy and rib tips. Where should I go in St. Louis tonight?"
```

**3. The offline check, no key, no network** (Python 3.9+, standard library only; about 2 minutes):

```bash
cd engine
python3 -I run_all.py --fake              # every code path on a synthetic Qloo world; output tagged [FAKE]
python3 -I tests/test_matcher.py          # the golden matcher set
python3 -I tests/test_api.py              # the engine API contract
```

## How a card is picked

1. **Your pool.** Qloo's `/v2/insights` ranks places for each of your three loves, one at a time, within 15 mi (St. Louis) or 10 mi (New York). A dish love ("rib tips") adds a sub-pool of places Qloo tags with that dish.
2. **The floor.** Tagged as a restaurant or bar in Qloo, rated 4.3 or better, open. Adult venues, hookah lounges, liquor and wine stores, banquet halls and out-of-state places are excluded. Each card also gets a last-seen check: hours and address in Qloo, and the venue's own site when Qloo has one.
3. **Crossing out.** Every place the AIs named in the dated answers, even once, is matched to the pool and struck (*Matching*, under [Gates](#gates)).
4. **The score.** Qloo scores every place for each of your loves. We keep the places that fit you much more than they fit most tastes on Qloo, or than their popularity alone would say. In code: fit for you − max(popularity, fit for everyone), where *fit for everyone* is the share of a city's 97 sample tastes on Qloo that put the place in their top 30% of the city. The sample tastes are single loves drawn by a fixed-seed procedure (`unsaid-anchors-v1`) from Qloo's own most popular artists, films, shows, brands, books and podcasts, spread over their Qloo genre tags (*Run it live* below), and never one of your loves. Every place in the city's candidate universe has a value; a place none of them scored gets the panel median, never zero. Cards and reserves come from this one score.
5. **The picks.** At most 3 cards come from any one love while the other loves have places to give. Chains are off the cards (from Qloo's website field: a branch page, or 3 or more pool places sharing a domain and a first word), and so are generic places that 60% or more of the sample tastes put in their top 30%.
6. **Seven cards, three reserves.** Strike a card you know and a reserve takes its place. Under seven, the page says so.
7. **The card line.** Card lines are condensed from Qloo's own descriptions by Claude, checked word-for-word against the source; no new facts (`engine/build_lines.py`; a line that fails the check falls back to Qloo's own first sentence).

## Run it live (your own Qloo key)

The "fit for everyone" priors (`data/priors/<city>.json`, plus the anchor panel `anchors-<city>.json`) are Qloo output keyed by Qloo IDs, so they are gitignored. Build them once per city first, then run a query:

```bash
export QLOO_API_KEY=...                   # from the environment, never in a file
cd engine
python3 -I build_priors.py --city both --dry --frozen           # the universe and the projected cost only
python3 -I build_priors.py --city stl --budget 1300 --frozen   # about 1,000 calls
python3 -I build_priors.py --city nyc --budget 2800 --frozen   # about 2,200 calls
python3 -I run_query.py --city nyc --set nyc-khruangbin --walls ../data/walls --budget 60
```

The procedure (fixed in the `build_priors.py` docstring; seed `unsaid-anchors-v1`): for each of six entity types with a quota (artist 25, movie 20, TV show 20, brand 15, book 10, podcast 10), take Qloo's 200 most popular entities of that type (`/v2/insights`, `filter.popularity.min=0.9`, no signal), group them by their Qloo genre tags, and draw round-robin over the genres with a seeded RNG. In draw order, an anchor is kept if it is live (under 95% of places at Qloo's default affinity), until the quota is met. The city's universe is the city-wide no-signal pool pages plus the pools of the 20 preset sets. Each anchor rescores the whole universe with the engine's own chunked `filter.results.entities` rescoring (48 places + 2 check places per call), and a chunk whose check places drift more than `ANCHOR_DRIFT_MAX` is dropped (checked and enforced; 0 drift in the 28 Oct build). Calls are cached, so a rerun after a `--budget` stop resumes. The script stops before the month's remaining Qloo calls would fall below `--quota-floor` (25,000).

Keys come only from environment variables, and the Qloo key goes only in the `X-Api-Key` header. `--budget N` stops before the (N+1)-th live Qloo call, and cached calls cost nothing. `engine/KEYDAY.md` lists every gate command in order; `engine/regen_try.sh` regenerates the site's try-these sets in one command. The server is `python3 -I server/app.py` (fake mode on port 8710; see `server/DEPLOY.md`). Qloo responses, results and the `.cache/` directory never enter git.

## Call trace

One query (St. Louis; Frankie Beverly & Maze, *The Original Kings of Comedy*, rib tips), every request in order, keys redacted:

<!-- trace:start -->

26 requests, in order. Every one is a GET to `hackathon.api.qloo.com`; the key is sent only in the `X-Api-Key` header. Long ID lists are shortened to the first two plus a count. Generated by `engine/readme_trace.py` from the trace `run_query.py` writes to `engine/out/`.

| # | step | status | request |
|---|---|---|---|
| 1 | C2 love | 200 | `https://hackathon.api.qloo.com/search?query=The+Original+Kings+of+Comedy&take=10&types=urn:entity:movie,urn:entity:tv_show` |
| 2 | C2 love tag | 200 | `https://hackathon.api.qloo.com/v2/tags?filter.query=rib+tips&take=5` |
| 3 | C4 pool Frankie Beverly &  o50 | 200 | `https://hackathon.api.qloo.com/v2/insights?bias.trends=off&filter.location=POINT(-90.1994+38.627)&filter.location.radius=24140&filter.tags=urn:tag:category:place:bar,urn:tag:category:place:restaurant&filter.type=urn:entity:place&offset=50&operator.filter.tags=union&signal.interests.entities=E67A957E-99EF-4941-A74C-1D3A0C4DB3D9&take=50` |
| 4 | C4 pool Frankie Beverly &  o0 | 200 | `https://hackathon.api.qloo.com/v2/insights?bias.trends=off&feature.explainability=true&filter.location=POINT(-90.1994+38.627)&filter.location.radius=24140&filter.tags=urn:tag:category:place:bar,urn:tag:category:place:restaurant&filter.type=urn:entity:place&operator.filter.tags=union&signal.interests.entities=E67A957E-99EF-4941-A74C-1D3A0C4DB3D9&take=50` |
| 5 | C4 pool The Original Kings o0 | 200 | `https://hackathon.api.qloo.com/v2/insights?bias.trends=off&feature.explainability=true&filter.location=POINT(-90.1994+38.627)&filter.location.radius=24140&filter.tags=urn:tag:category:place:bar,urn:tag:category:place:restaurant&filter.type=urn:entity:place&operator.filter.tags=union&signal.interests.entities=05049FF9-844A-4481-9FFD-95F2874B28DD&take=50` |
| 6 | C4 pool The Original Kings o50 | 200 | `https://hackathon.api.qloo.com/v2/insights?bias.trends=off&filter.location=POINT(-90.1994+38.627)&filter.location.radius=24140&filter.tags=urn:tag:category:place:bar,urn:tag:category:place:restaurant&filter.type=urn:entity:place&offset=50&operator.filter.tags=union&signal.interests.entities=05049FF9-844A-4481-9FFD-95F2874B28DD&take=50` |
| 7 | C2 dish siblings | 200 | `https://hackathon.api.qloo.com/v2/tags?filter.query=Rib+Tips&take=10` |
| 8 | C4 dish rib tips o50 | 200 | `https://hackathon.api.qloo.com/v2/insights?bias.trends=off&filter.location=POINT(-90.1994+38.627)&filter.location.radius=24140&filter.tags=urn:tag:menu_highlight:qloo:rib_tips,urn:tag:specialty_dish:place:rib_tips&filter.type=urn:entity:place&offset=50&operator.filter.tags=union&take=50` |
| 9 | C4 dish rib tips o0 | 200 | `https://hackathon.api.qloo.com/v2/insights?bias.trends=off&filter.location=POINT(-90.1994+38.627)&filter.location.radius=24140&filter.tags=urn:tag:menu_highlight:qloo:rib_tips,urn:tag:specialty_dish:place:rib_tips&filter.type=urn:entity:place&operator.filter.tags=union&take=50` |
| 10 | C4 pool The Original Kings o150 | 200 | `https://hackathon.api.qloo.com/v2/insights?bias.trends=off&filter.location=POINT(-90.1994+38.627)&filter.location.radius=24140&filter.tags=urn:tag:category:place:bar,urn:tag:category:place:restaurant&filter.type=urn:entity:place&offset=150&operator.filter.tags=union&signal.interests.entities=05049FF9-844A-4481-9FFD-95F2874B28DD&take=50` |
| 11 | C4 pool Frankie Beverly &  o150 | 200 | `https://hackathon.api.qloo.com/v2/insights?bias.trends=off&filter.location=POINT(-90.1994+38.627)&filter.location.radius=24140&filter.tags=urn:tag:category:place:bar,urn:tag:category:place:restaurant&filter.type=urn:entity:place&offset=150&operator.filter.tags=union&signal.interests.entities=E67A957E-99EF-4941-A74C-1D3A0C4DB3D9&take=50` |
| 12 | C4 pool The Original Kings o100 | 200 | `https://hackathon.api.qloo.com/v2/insights?bias.trends=off&filter.location=POINT(-90.1994+38.627)&filter.location.radius=24140&filter.tags=urn:tag:category:place:bar,urn:tag:category:place:restaurant&filter.type=urn:entity:place&offset=100&operator.filter.tags=union&signal.interests.entities=05049FF9-844A-4481-9FFD-95F2874B28DD&take=50` |
| 13 | C4 pool Frankie Beverly &  o100 | 200 | `https://hackathon.api.qloo.com/v2/insights?bias.trends=off&filter.location=POINT(-90.1994+38.627)&filter.location.radius=24140&filter.tags=urn:tag:category:place:bar,urn:tag:category:place:restaurant&filter.type=urn:entity:place&offset=100&operator.filter.tags=union&signal.interests.entities=E67A957E-99EF-4941-A74C-1D3A0C4DB3D9&take=50` |
| 14 | C4 pool Frankie Beverly &  o200 | 200 | `https://hackathon.api.qloo.com/v2/insights?bias.trends=off&filter.location=POINT(-90.1994+38.627)&filter.location.radius=24140&filter.tags=urn:tag:category:place:bar,urn:tag:category:place:restaurant&filter.type=urn:entity:place&offset=200&operator.filter.tags=union&signal.interests.entities=E67A957E-99EF-4941-A74C-1D3A0C4DB3D9&take=50` |
| 15 | C4 pool The Original Kings o250 | 200 | `https://hackathon.api.qloo.com/v2/insights?bias.trends=off&filter.location=POINT(-90.1994+38.627)&filter.location.radius=24140&filter.tags=urn:tag:category:place:bar,urn:tag:category:place:restaurant&filter.type=urn:entity:place&offset=250&operator.filter.tags=union&signal.interests.entities=05049FF9-844A-4481-9FFD-95F2874B28DD&take=50` |
| 16 | C4 pool Frankie Beverly &  o250 | 200 | `https://hackathon.api.qloo.com/v2/insights?bias.trends=off&filter.location=POINT(-90.1994+38.627)&filter.location.radius=24140&filter.tags=urn:tag:category:place:bar,urn:tag:category:place:restaurant&filter.type=urn:entity:place&offset=250&operator.filter.tags=union&signal.interests.entities=E67A957E-99EF-4941-A74C-1D3A0C4DB3D9&take=50` |
| 17 | C4 pool The Original Kings o200 | 200 | `https://hackathon.api.qloo.com/v2/insights?bias.trends=off&filter.location=POINT(-90.1994+38.627)&filter.location.radius=24140&filter.tags=urn:tag:category:place:bar,urn:tag:category:place:restaurant&filter.type=urn:entity:place&offset=200&operator.filter.tags=union&signal.interests.entities=05049FF9-844A-4481-9FFD-95F2874B28DD&take=50` |
| 18 | C6' The Original Kings c2 | 200 | `https://hackathon.api.qloo.com/v2/insights?bias.trends=off&filter.location=POINT(-90.1994+38.627)&filter.location.radius=24140&filter.results.entities=<27 pool IDs>)&filter.tags=urn:tag:category:place:bar,urn:tag:category:place:restaurant&filter.type=urn:entity:place&operator.filter.tags=union&signal.interests.entities=05049FF9-844A-4481-9FFD-95F2874B28DD&take=50` |
| 19 | C6' The Original Kings c1 | 200 | `https://hackathon.api.qloo.com/v2/insights?bias.trends=off&filter.location=POINT(-90.1994+38.627)&filter.location.radius=24140&filter.results.entities=<50 pool IDs>)&filter.tags=urn:tag:category:place:bar,urn:tag:category:place:restaurant&filter.type=urn:entity:place&operator.filter.tags=union&signal.interests.entities=05049FF9-844A-4481-9FFD-95F2874B28DD&take=50` |
| 20 | C6' rib tips c1 | 200 | `https://hackathon.api.qloo.com/v2/insights?bias.trends=off&filter.location=POINT(-90.1994+38.627)&filter.location.radius=24140&filter.results.entities=<50 pool IDs>)&filter.tags=urn:tag:category:place:bar,urn:tag:category:place:restaurant&filter.type=urn:entity:place&operator.filter.tags=union&signal.interests.tags=urn:tag:specialty_dish:place:rib_tips&take=50` |
| 21 | C6' rib tips c2 | 200 | `https://hackathon.api.qloo.com/v2/insights?bias.trends=off&filter.location=POINT(-90.1994+38.627)&filter.location.radius=24140&filter.results.entities=<27 pool IDs>)&filter.tags=urn:tag:category:place:bar,urn:tag:category:place:restaurant&filter.type=urn:entity:place&operator.filter.tags=union&signal.interests.tags=urn:tag:specialty_dish:place:rib_tips&take=50` |
| 22 | C6' Frankie Beverly &  c2 | 200 | `https://hackathon.api.qloo.com/v2/insights?bias.trends=off&filter.location=POINT(-90.1994+38.627)&filter.location.radius=24140&filter.results.entities=<27 pool IDs>)&filter.tags=urn:tag:category:place:bar,urn:tag:category:place:restaurant&filter.type=urn:entity:place&operator.filter.tags=union&signal.interests.entities=E67A957E-99EF-4941-A74C-1D3A0C4DB3D9&take=50` |
| 23 | C7 name | 200 | `https://hackathon.api.qloo.com/search?filter.location=38.627,-90.1994&filter.radius=15&query=Zodiac+at+Neiman+Marcus&take=5&types=urn:entity:place` |
| 24 | C7 name | 200 | `https://hackathon.api.qloo.com/search?filter.location=38.627,-90.1994&filter.radius=15&query=Oceano+Bistro&take=5&types=urn:entity:place` |
| 25 | C6' Frankie Beverly &  c1 | 200 | `https://hackathon.api.qloo.com/v2/insights?bias.trends=off&filter.location=POINT(-90.1994+38.627)&filter.location.radius=24140&filter.results.entities=<50 pool IDs>)&filter.tags=urn:tag:category:place:bar,urn:tag:category:place:restaurant&filter.type=urn:entity:place&operator.filter.tags=union&signal.interests.entities=E67A957E-99EF-4941-A74C-1D3A0C4DB3D9&take=50` |
| 26 | CAP popularity.max | 200 | `https://hackathon.api.qloo.com/v2/insights?bias.trends=off&filter.location=POINT(-90.1994+38.627)&filter.location.radius=24140&filter.popularity.max=0.8060514817237541&filter.tags=urn:tag:category:place:bar,urn:tag:category:place:restaurant&filter.type=urn:entity:place&operator.filter.tags=union&signal.interests.entities=05049FF9-844A-4481-9FFD-95F2874B28DD,E67A957E-99EF-4941-A74C-1D3A0C4DB3D9&take=50` |

<!-- trace:end -->

## Gates

Every gate is printed as measured, pass or fail, with its script. The bars were set before the measurement; the pivot column is what the build doc says to do on a fail. The build doc (`UNSAID.md`, hashed in `data/prereg/SHA256SUMS`) is private, disclosed on request.

| gate | bar | script | result | pivot applied |
|---|---|---|---|---|
| P · probes | 12 checks of how Qloo behaves | `probes.py` | **PASS**: 12 of 12 ran. `business_rating.min` is ignored server side; no-signal order ≡ popularity | client floor 4.3; "anyone" = popularity rank |
| K1 · density | 150+ places in the pool | `k1_density.py` | **FAIL**: \|U\| ≥ 150 in 0/10 NYC and 0/10 STL at 8 and 10 mi; 2/10 and 2/10 after widening | widen R: STL 15 mi, NYC 10 mi |
| A · taste moves | ρ(taste, popularity) ≤ 0.90 in 8+ of 10 sets per city; two strangers' sevens (Cedric, Jason) share ≤ 2 | `k2a_lift.py` | ⟦GATE_A⟧. All pairs in a city: median ⟦PAIRS_MED⟧ | none |
| K8 · closed | Qloo's `is_closed` catches known closures | `k8_closed.py` | **FAIL**: 2 of 3 known closures | a last-seen check on every card (hours and address in Qloo; the venue's site when Qloo has one) |
| K4 · matcher | 0 AI-named places slip through | `tests/test_matcher.py`, `k4_relabel.py` | **PASS after pivot**: 1,345 AI names on 2 real pools; 3 false survivors, each a branch of a named place, then 0 after R5. Labels by the build agent, not held out | raise the guard (R5 brand containment) |
| B · survivors | 7 cards + 3 reserves, no junk, in 8+ of 10 (NYC) and 6+ of 10 (STL) | `k3_survivors.py` | ⟦GATE_B⟧ | widen R; extra pool pages |
| C · not a cap | overlap with a popularity cut of the same size ≤ 0.80 | `k3_survivors.py`, `run_query.py` | ⟦GATE_C⟧; by city below | none |
| D · meter | with Qloo as a tool, 4+ fewer everyone-list picks than alone in 7+ of 10 sets | `k10_meter.py` | **FAIL**: alone a median 6.0 of 12 picks land on the other AIs' lists (the pre-registered grading list: census + wall 1); with Qloo as the tool 4.0; 4+ below alone in 5 of 10 sets. Final re-grade on the rebuilt walls | printed here, not featured |
| E · fresh asks | median 1 or fewer of 7 cards named | `k5_fresh.py` | **PASS**: 1 of 140 (on the frozen cards; k12's stricter check on today's cards finds 3), median 0; the one hit is a false match (below) | none |
| F · speed | cards p50 20 s or less; first name 1 s or less | `k11_latency.py` | ⟦GATE_F⟧, through the Pages proxy on Render's free tier, at the freeze | none |

- **Gate D's "with Qloo" tool** (`qloo_places`) ordered places by the first love's pool order, not a joint signal, and built its pool the older way at meter time (2 pages, no distance check; 101 places vs the engine's 183 for the same set). It still returned what the frozen protocol asks for, Qloo's top 50 with nothing crossed out, so D stands as measured and was not re-run. Meter protocol: `data/meter.protocol.md`.
- **Gate F** is measured from a home broadband line, not a phone on cellular as the build doc says. The number above is the freeze run's, after the last engine deploy; an earlier pass on 28 Oct predates the ranking change. If the first crossed-out name takes more than 1 s, the cell says FAIL. A fresh query costs about 40–50 Qloo calls and $0 in AI API fees.
- **Memory:** the 512 MB host ran out of memory under repeated cold runs (glibc arenas holding freed memory). Fixed with `malloc_trim` after every run and `MALLOC_ARENA_MAX=2`; a 15-run soak on Render then peaked at 291 MB with 0 restarts.

### Gate E: fresh public questions

40 real public questions (20 per city, Reddit), sent word for word plus one line naming the subreddit and city, and for 4 of them the set's three loves. None was ever used to build the list (checked by SHA-256). Scored on the 140 cards frozen and hashed on 28 Oct (`data/prereg/frozen20_cards.sha256`), about 49 answers per set: 1 of 140 cards named, median 0 of 7.

- **That one hit is Bar Freda**, matched to ChatGPT's "Jack's Wife Freda", a different restaurant. It is counted as measured. On the cards as regenerated on 28 Oct, the same check finds El Born, a real ChatGPT mention.
- **The check was tightened once.** The first scoring counted 5 of 140. The reverse check (does the raw answer text name a card?) was then tightened so month names and common words aren't evidence, which removed 4.
- **No baseline of its own.** k12 below, on the same questions, is the baseline.

### Two strangers (gate A)

Asked 12 times each about their tastes, Claude's answers for Cedric (*The Original Kings of Comedy*, Frankie Beverly & Maze, rib tips; 51 places in all) and Jason (Sinatra, *Rounders*, Carbone; 61 places) overlapped on 9 places in total, though two single answers shared fewer than one place on average. Their UNSAID sevens share ⟦STRANGERS⟧. Cedric and Jason are two of the 20 taste sets.

Over all 20 sets, the ⟦CARDS⟧ cards are ⟦DISTINCT⟧ distinct places; no place appears more than ⟦MAXREP⟧ times in a city; two sets in a city share a median ⟦PAIRS_MED⟧. Similar tastes do share: St. Louis's soul and hip-hop sets, and Wilco with Big Thief, share up to ⟦CLUSTER_MAX⟧ places pair by pair; any other two sets, at most ⟦OTHER_MAX⟧.

### Is this just `filter.popularity.max`?

No, though it does lean to less-known places, on purpose, and so do the AIs. Gate C cuts as many places by Qloo's popularity order as the AIs' list cuts, and measures how much the two cuts overlap (`k3_survivors.py`):

- **It differs by city.** In St. Louis a popularity cap catches most of the AIs' list: a median ⟦CAP_MED_STL⟧ over 10 sets, against ⟦CAP_CHANCE_STL⟧ for a random cut of the same size. In New York it catches less: ⟦CAP_MED_NYC⟧, against ⟦CAP_CHANCE_NYC⟧. Over all 20 sets, ⟦CAP_MED⟧ against ⟦CAP_CHANCE⟧.
- **The cards still differ.** Qloo's popularity-capped top 7 (your loves as one joint signal + `filter.popularity.max`) shares a median ⟦CAP_SHARE_MED⟧ of 7 places with UNSAID's seven.
- **How much is crossed out.** For Cedric, the AIs named ⟦WALL⟧ St. Louis places; ⟦STRUCK_U⟧ were in his ⟦U⟧-place pool, ⟦S⟧ were left (`run_query.py --city stl --set stl-cedric`). Across 20 sets, a median ⟦STRUCK_MED⟧ of ⟦U_MED⟧.
- **k12, below.** On held-out questions, the score alone (no list) does most of the avoiding; the list does the rest.

Probe P12 found that Qloo's no-signal order *is* the popularity order (ρ = 1.00 in New York, St. Louis and LA), so "for anyone" on a card is Qloo's popularity rank of the same pool (`probes.py`).

### What crossing out changes (k12)

`engine/k12_wall_effect.py` runs the same pipeline twice per set, with the real list and with an empty one, and also takes Qloo's plain top 7 by taste (the loves' ranks fused, nothing else). The evidence is the held-out fresh questions: on the dated answers the list is built from, "named" is scored by the same matcher that strikes, so UNSAID's count there is zero by construction.

Held-out, cards the answers named, pooled over 20 sets of 7: **Qloo's plain taste top 7 ⟦K12_PLAIN_FRESH_POOLED⟧ → our score with no list ⟦K12_OFF_FRESH_POOLED⟧ → UNSAID ⟦K12_ON_FRESH_POOLED⟧** (per-set medians ⟦K12_PLAIN_FRESH⟧ / ⟦K12_OFF_FRESH⟧ / ⟦K12_ON_FRESH⟧). By city: St. Louis ⟦K12_PLAIN_FRESH_STL⟧ → ⟦K12_OFF_FRESH_STL⟧ → ⟦K12_ON_FRESH_STL⟧; New York ⟦K12_PLAIN_FRESH_NYC⟧ → ⟦K12_OFF_FRESH_NYC⟧ → ⟦K12_ON_FRESH_NYC⟧.

Most of the drop comes from our ranking, which also drops generic venues (Ballpark Village, Little Italy spots) that Qloo's plain order keeps; crossing out does the rest, mostly in St. Louis. Counts only; the table with names stays in `engine/out/` (gitignored). Full table: [engine/k12_wall_effect.md](engine/k12_wall_effect.md).

### Why a rank per love, not Qloo's joint signal (k13)

`engine/k13_joint.py` compared the two over the same pool, 20 sets ([engine/k13_joint.md](engine/k13_joint.md)), measured on 28 Oct before the final ranking. The joint call can't carry a dish love: the engine's sevens hold 35 dish-tagged places, the joint call's 3; the dish tag got no explainability credit, and in 5 of 14 dish sets Qloo dropped a median 12% of the pool from the response. Joint explainability is flat (the top love's share a median 0.51, 0.05 ahead of the next) and agreed with the card's "because" on 66 of 105, so a card couldn't reliably say which love put it there. The two orders correlate at 0.64 (Spearman) and the sevens share 5 of 7. A switch would add about 4 calls per query and save none. The joint signal is still used for the cap check (gate C).

### With web search on

The main lanes run without web search. A separate lane (`harness/search_on.py`, `data/walls/search-on.json`, labelled `search: true`) asked 24 phrasings per city to Claude with web search allowed (it searched in 6 of 48 asks), to Claude told to search (44 of 48) and to ChatGPT with web search on (48 of 48). 21 of Claude's 96 answers came from `claude-haiku-5-5` (Claude Code's own model routing), not Sonnet; the model is stamped on every answer.

- **0 of the 140 frozen cards gate E scored** were named by any search-on answer. On the 28 Oct ranking, before these answers joined the list, they named 5 cards in 4 sets; those are struck now.
- Claude's hidden-gem lists barely move: with search allowed, Mai Lee on 14 of 16; told to search, 8 of 16.
- ChatGPT with search scatters: Mai Lee on 4 of 16, Gioia's Deli on 0 of 16. The convergence on short lists is a no-search finding for ChatGPT.
- These answers are now part of the list.

### Each card's own neighbourhood

Two street lanes asked Claude and ChatGPT for the best places to eat and drink in a card's neighbourhood. Of the ⟦STREET_POOL⟧ cards a run without those answers would show, ⟦STREET_ASKED⟧ had their neighbourhood asked about, and ⟦STREET_NAMED_ASKED⟧ of those came up; each was struck and replaced. The freeze tops up the street asks until every card's neighbourhood has been asked (`harness/street_catchup.sh`).

### Matching

Mostly name rules (exact, alias, brand containment: "Ippudo NY" strikes IPPUDO Hell's Kitchen; corporate suffixes and apostrophes normalised, so "Joe's" matches "Joes LLC"), checked against Qloo IDs with a city-scoped `/search` where it matters, up to 20 lookups per query. Close matches are struck. Weak one-word matches past the lookup cap are not, because in testing they were matcher errors ("Home Wine Kitchen" striking Down Home Elegance).

- **K4, the live relabel:** 1,345 AI names on 2 real pools, labelled by the build agent; not held out.
- **The golden set** (`engine/fixtures/labels.py`): 136 AI-named places in New York and St. Louis, each labelled with its kind (clean, alias, multi-location, common word, not a venue, closed). `tests/test_matcher.py` scores them offline against a synthetic pool: 0 false survivors at 95.9% strike precision. The same test holds the R5 golden cases from the live relabel.

### Post-hoc: the meter with `unsaid_places` as the tool

**Not pre-registered.** Written before running (`harness/meter_unsaid.md`), graded by the unchanged `k10_meter.py` (`harness/runs/meter_unsaid_grade.txt`), never mixed with gate D. Same 10 St. Louis sets, same asks.

- Per-set median on the everyone-list, of 12: alone 6.2 · with Qloo 3.2 (per-set medians; gate D pools runs) · **with UNSAID 1.0**.
- Claude on its own put a median 6 of 12 picks on the list (20 runs). With the tool, it called it in 20 of 20 runs and put 0 of 12 on the list in every run.
- ChatGPT didn't call the tool in 12 of its 20 runs (kept, intention to treat).
- All 95 everyone-list picks in this arm were added by the agent; 0 came from the tool. The tool's own picks score 0 by construction, so the arm shows that the agent sticks to the tool, not that the tool avoids the list.

### Live and dated

The ChatGPT and Claude answers are **dated**: asked through each vendor's command-line tool between ⟦DATES⟧, and stamped on every name: ⟦ASKS_STL⟧ dated asks about St. Louis and ⟦ASKS_NYC⟧ about New York, across every lane (Gemini's and the labelled search-on lane included). The census ran on 27 Oct 2026; 8 of ChatGPT's census answers were re-asked on 28 Oct after the search leak, and 24 other ChatGPT answers after the shell leak (*$0 AI side*). Gemini is asked **live** once per fresh run (one taste ask on the free tier, `gemini-3-flash-preview`). Cards don't wait for it: a live Gemini name that hits a card burns it afterwards. When Gemini's daily quota is used up, everything on screen is dated and the page says so. Each answer in `data/walls/` carries `asked_at` and `lane: dated | live`.

A place is struck if any answer named it once: 28% of the struck places in the pools were named in exactly one answer.

The list is not every place an AI could name. Against the Chao2 estimate of each AI's full list, the saturation lane (960 extra asks) moved Claude in St. Louis from 46.6% to ⟦COVERAGE⟧ and in New York from 43.9% to ⟦COVERAGE_NYC⟧ (ChatGPT at the lane's end on 28 Oct: St. Louis 53.6% → 61.3%, New York 47.1% → 46.2%, as its estimate grew). In St. Louis, Claude's new-name rate fell to ⟦NEWRATE_STL⟧ over its last 40 asks (our bar for flat was 2%); in New York it is ⟦NEWRATE_NYC⟧. Neither city is flat. The paste box is there for the rest. `harness/census_stats.py`, `harness/saturation.py`.

### FAQ

- **Didn't the same place turn up in every St. Louis set?** It did (Warehouse West in 10 of 10). The ranking now weighs what fits you against what fits 97 sample tastes on Qloo: ⟦DISTINCT⟧ distinct places in ⟦CARDS⟧ cards, at most ⟦MAXREP⟧ per city. Similar tastes still share up to ⟦CLUSTER_MAX⟧ places.
- **How many crossed-out places were even in his pool?** ⟦STRUCK_U⟧ of Cedric's ⟦U⟧; a median ⟦STRUCK_MED⟧ of ⟦U_MED⟧ over 20 sets (*Is this just `filter.popularity.max`?*).
- **Isn't the ranking just a popularity filter?** It leans to less-known places on purpose, and that (with the fit-for-everyone term) does most of the avoiding: on held-out questions, ⟦K12_PLAIN_FRESH_POOLED⟧ AI-named cards in Qloo's plain taste order, ⟦K12_OFF_FRESH_POOLED⟧ with our score alone, ⟦K12_ON_FRESH_POOLED⟧ with the list. A popularity cap catches most of the AIs' list in St. Louis and less in New York, and its top 7 shares a median ⟦CAP_SHARE_MED⟧ of 7 with UNSAID's.
- **Is Cedric typical?** He's the example. Every number here is a 20-set median or total unless it names him.
- **Real ChatGPT searches the web.** So we asked with search on: it scatters, and those answers named 0 of the 140 frozen cards (*With web search on*). They're on the list now.
- **Does the list cover everything the AIs say?** No: about ⟦COVERAGE⟧ of Claude's estimated St. Louis list and ⟦COVERAGE_NYC⟧ in New York, and neither is flat. Paste any answer and a named card burns.
- **Who labelled the matcher test?** The build agent, on 2 sets, not held out. The golden set is scored against a synthetic pool.
- **What's gate E's baseline?** k12, on the same held-out questions.
- **Why fuse a rank per love instead of Qloo's joint signal?** k13 above: the joint call can't carry a dish love, and its explainability can't say which love put a card there.
- **Do people like these places?** Not shown. Only Qloo's taste score says they fit; nobody has walked in, and nobody has paid.
- **Who pays?** The model we'd test, with no partner yet: card dining programmes already pay to put diners in seats, so a programme pays per seated diner, only after Qloo has picked the place. No restaurant can buy a card.
- **When was it pre-registered?** Below: after the census, before the Qloo key and any card.

### Pre-registration

The public gist, posted 28 Oct 2026 at 00:03 UTC (27 Oct, 20:03 ET), minutes before the Qloo key arrived and so before any card existed: https://gist.github.com/mi11ione/6ae7660a666e9bc5978184576809136c. It lists five SHA-256 hashes, and `data/prereg/SHA256SUMS` maps each to its file: the 20 taste sets (`sets.json`, `ac3e169f…`), the fresh questions (`fresh_asks.json`, `c1f86b2d…`) and their protocol (`d21638ed…`), the meter protocol (`fb19df60…`) and the build doc (`abff575e…`, private, disclosed on request). All five match the files (`python3 -I tools/freeze_numbers.py prereg`; the freeze stops on a mismatch). The site's try-these flags live in `data/try_these.json`, so `data/sets.json` stays byte for byte as hashed. `data/prereg/frozen20_cards.sha256` (committed 28 Oct 02:26 UTC, not in the gist) hashes the 20 card lists that gate E scored. Those lists are Qloo output, so they stay out of the repo and are disclosed on request.

The gist postdates both censuses (Claude's from 27 Oct 12:05 UTC), so the census prompts were not publicly pre-registered. `harness/run_census.py` records the SHA-256 of its 128 prompts (`harness/asks.json`, prompt v1): `ca82f4e3…`.

## $0 AI side

- **Claude:** Claude Sonnet 5.5 via Claude Code (`claude -p --model sonnet`) on the author's subscription, with a one-line consumer-chat system prompt. The model is read back from each answer: every no-search answer in `data/walls/` is `claude-sonnet-5-5`; in the search-on lane Claude Code routed 21 of 96 to `claude-haiku-5-5`.
- **ChatGPT:** GPT-5.6 (`gpt-5.6-terra`) via Codex CLI (`codex exec -m gpt-5.6-terra`) on the author's subscription.
- Census and saturation asks end with the same request for a JSON list of 8–12 places (`harness/prompts.py`), wall asks with a list of up to 12 (`harness/phrasings.py`); fresh questions go out verbatim.
- Both run on the author's machine and never on the server.
- **Gemini:** the free API tier. Dated asks use `gemini-3.8-flash`, which allows 20 requests a day, so the Gemini lane covers the hidden-gem asks only. Live asks use `gemini-3-flash-preview`.
- **No web search** in any lane except the labelled search-on lane. No paid AI API key.
- **Search leak:** Codex's built-in apps connector ran web searches in 8 of 128 census answers and 41 of 120 wall answers even with search disabled. It was found, switched off with `--disable apps`, and every affected answer was asked again.
- **Shell leak:** Codex could also run shell commands, and 6 street answers ran `curl`. The shell is now off too (`--disable shell_tool`), and every answer that used it (24) was asked again.
- The record of both, answer by answer: [harness/README.md](harness/README.md#search-leak-28-oct-found-fixed-redone). Exact commands for each lane are there too.

## Deviations from the build doc

- **Wider radius:** K1 failed at 10 mi (STL) and 8 mi (NYC), so the radius is now 15 mi (STL) and 10 mi (NYC). This is the documented pivot.
- **Extra pool pages:** offsets 100 and 150 are fetched, but only when the floored pool has fewer than 150 places.
- **Ranking (28 Oct):** the first ranking put the same place on most sets' cards (Warehouse West in 10 of 10 St. Louis sets). The score now subtracts what fits everyone (above). Over 20 sets: ⟦DISTINCT⟧ distinct places in ⟦CARDS⟧ cards (before: 68), at most ⟦MAXREP⟧ per place per city (before: 10); two sets in a city share a median ⟦PAIRS_MED⟧. Similar tastes share most: St. Louis's soul and hip-hop sets, and Wilco with Big Thief, up to ⟦CLUSTER_MAX⟧ places pair by pair; any other two sets, at most ⟦OTHER_MAX⟧.
- **Fit-for-everyone prior (28 Oct):** it was first built from the city's other nine preset sets. That made the diversity numbers circular (measured on the sets the prior came from), and a place outside those sets' pools got no penalty at all (in 5 of 10 New York sets only 1–2 of 7 cards had a prior). It now comes from a Qloo-sampled anchor panel (97 live anchors per city, `build_priors.py`) over each city's whole candidate universe, with the median for any place no anchor scored. On the 20 sets that day: cards with a prior value 100 → 136 of 140 (the other 4 get the median; pool places 82% → 95%); distinct places 118 → 105; at most 4 repeats per place per city (was 3); gates A and B still pass; held-out AI-named cards, plain → our score with no list → UNSAID: 32 → 11 → 1 (was 32 → 7 → 1).
- **Picks rules (28 Oct, after the new prior):** at most 3 cards per love while the other loves have places to give (it can't hold when they have none); chains off the cards; generic places cut (60% or more of the sample tastes put them in their top 30%); the matcher normalises corporate suffixes and apostrophes. The diversity targets were missed rather than the rules bent; similar tastes share the most (above).
- **Dish loves:** a dish counts through a `filter.tags` sub-pool of places Qloo tags with it. A dish no place is tagged with (Dry Martini) stays dead: it shows the dead-love line and leaves the ranking.
- **R5 brand containment:** a branch of a named brand is struck. A weak word never fires this rule alone. Added after the live K4 relabel.
- **The 20-lookup cap:** name → Qloo ID lookups are capped at 20 per query, spent first on vetoing one-word strikes; a one-word match past the cap is not applied (gate F needed it; K4 stayed at 0).
- **Love resolution correction:** two frozen loves had resolved to the far side of the world (Ten Bells → a pub in Mariana, Brazil; Carbone → a restaurant in Gijón, Spain). They now resolve to The Ten Bells and Carbone in New York, and both sets were recomputed. The resolver passes a 64-case test at 100% top-1; the cases were written alongside the fix, so it is a regression test, not a held-out score.
- **Meter grading:** `k10_meter.py` first graded against an older definition. It now uses the frozen protocol (the other assistants' city-wall and census answers).
- **Fresh-ask city line:** the verbatim questions don't name the city, so the AIs asked "which city?" and named nothing. One context line ("Posted in r/StLouis (St. Louis, Missouri):") is added to every question, before any scoring (`data/fresh_asks.deviations.md`).
- **The city picker** offers St. Louis and New York only: the two cities with collected AI answers.

## MCP

**Hosted:** `https://unsaid-ang.pages.dev/mcp` is the same tool over MCP Streamable HTTP (`server/mcp_http.py`: POST JSON-RPC, a JSON reply or an SSE stream for `tools/call`, stateless, no session). It runs every call through the same path as `/api/unsaid`, with the same cache and limits (15 fresh runs an hour per IP through 6 Nov), and returns the same `structuredContent` as the stdio server. Add it as a custom connector in Claude (Settings → Connectors), or `claude mcp add --transport http unsaid "https://unsaid-ang.pages.dev/mcp"`. `python3 -I agent/test_client.py --http <url>` checks it.

**Local (stdio):** `agent/unsaid_mcp.py` is a stdio MCP server in one file, standard library only. By default (`UNSAID_MODE=remote`) it calls the hosted API at https://unsaid-ang.pages.dev, so an agent gets the same live Qloo ranks and the same dated AI answers as the site. You don't need a Qloo key or the engine. No token is needed.

Claude Code: the command in *Five minutes* above.

Claude Desktop (`claude_desktop_config.json`; the same block is in `agent/claude_desktop_config.snippet.json`):

```json
{
  "mcpServers": {
    "unsaid": {
      "command": "python3",
      "args": ["-I", "/path/to/unsaid/agent/unsaid_mcp.py"],
      "env": { "UNSAID_MODE": "remote" }
    }
  }
}
```

`agent/mcp.json` is the same config for `claude --mcp-config`. Replace `/path/to/unsaid` with the path to your clone first:

```bash
claude -p "I love Frankie Beverly & Maze, The Original Kings of Comedy and rib tips. Where should I go in St. Louis tonight?" \
  --mcp-config agent/mcp.json --allowedTools mcp__unsaid__unsaid_places
```

- `unsaid_places(loves, city)` returns the product: it crosses out places named in the dated Claude and GPT answers on file (plus a live Gemini ask where available) and ranks the rest by how much better each fits your loves than its popularity or its fit for most tastes, as above. Up to 7 picks, each with its Qloo id, its two ranks, whether it holds if any one love is dropped, a reason ("fits all three of your loves", or "because you love <love>" when a dish love or two or more loves carry it; none when it rests on one love alone), and the wall's most-named places. Pass loves as `[text, type]` pairs; untyped, "rib tips" can resolve to a restaurant. The hosted API serves St. Louis and New York City and refuses other cities with a note. Run locally, a city with no AI answers on file gets an empty wall and the `no_wall` flag.
- `qloo_places(loves, city)` returns the top 50 of the same pool with nothing crossed out. It is the meter's "with" arm. Only the local modes list it. It orders places by the first love's pool order, not a joint signal; at meter time it also built a shallower pool than the engine (see *Gates*), and the pool now matches.
- A real agent run is public on the site: https://unsaid-ang.pages.dev/data/live/agent_demo.json (Claude Code, remote mode, the call and the answer verbatim).

Other modes: `UNSAID_MODE=fake` runs the engine offline on a synthetic Qloo world, and every result is tagged FAKE. `UNSAID_MODE=live` with `QLOO_API_KEY` runs the engine locally, using the walls in `data/walls` (override with `UNSAID_WALLS`). Both local modes call `run_unsaid` in `engine/unsaid/api.py`, as the server does. `python3 -I agent/test_client.py` checks fake mode in both protocol eras, then runs a smoke test against the hosted API. The smoke test is skipped when `UNSAID_TOKEN` isn't set.

## Credits

- Map dots and neighbourhood centroids: © OpenStreetMap contributors, ODbL 1.0.
- Rankings: the Qloo Insights API. No Qloo results are kept in this repository's files; only the Qloo IDs of the preset loves.

## License

MIT ([LICENSE](LICENSE)). Map data derived from OpenStreetMap is under the ODbL 1.0, not MIT.
