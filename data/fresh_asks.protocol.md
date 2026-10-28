# K5′ fresh-ask collection: protocol

Written and frozen **27 Oct 2026, before any search was run** (UNSAID.md §4, "The held-out fresh-ask test").
Collector: Agent E (coding agent). Freezer: the orchestrator (changed from Roman on 28 Oct by coordinator instruction). Output: `data/fresh_asks.json`.

Sections 1 to 6 below were written before the first search. Section 7, the run log, is appended during collection and is the only part written afterwards.

## 1. Sources

Reddit r/StLouis, r/AskNYC and r/FoodNYC; the Tripadvisor forums (St. Louis, New York City); Quora.

## 2. Search instrument

- The `WebSearch` tool available to the collecting agent, `mode: "standard"`, with no domain filters. The query string is passed exactly as listed below.
- "Result order" means the order of the result blocks that tool returns. Web search order isn't perfectly reproducible, so every result of every query that was run is logged in §7 with its position, so the selection can be audited even if a re-run differs.

## 3. Frozen query list (run in this order, city by city; stop when a city has 20)

**St. Louis**

| id | query string |
|---|---|
| STL-Q1 | `reddit r/StLouis where should I eat recommendations` |
| STL-Q2 | `reddit r/StLouis restaurant recommendations visiting St. Louis` |
| STL-Q3 | `reddit r/StLouis best bars recommendations` |
| STL-Q4 | `tripadvisor St. Louis forum where to eat recommendations` |
| STL-Q5 | `quora where should I eat in St. Louis Missouri` |
| STL-Q6 | `reddit r/StLouis date night restaurant suggestions` |
| STL-Q7 | `reddit r/StLouis food recommendations first time in St. Louis` |
| STL-Q8 | `reddit r/StLouis brunch recommendations` |
| STL-Q9 | `reddit StLouis where to eat 2024` |
| STL-Q10 | `reddit StLouis dinner recommendations 2025` |
| STL-Q11 | `reddit StLouis happy hour recommendations` |
| STL-Q12 | `reddit StLouis cheap eats recommendations` |

**New York**

| id | query string |
|---|---|
| NYC-Q1 | `reddit r/AskNYC where should I eat recommendations` |
| NYC-Q2 | `reddit r/FoodNYC restaurant recommendations` |
| NYC-Q3 | `reddit r/AskNYC bar recommendations` |
| NYC-Q4 | `tripadvisor New York City forum where to eat recommendations` |
| NYC-Q5 | `quora where should I eat in New York City` |
| NYC-Q6 | `reddit r/FoodNYC date night restaurant suggestions` |
| NYC-Q7 | `reddit r/AskNYC first time in NYC food recommendations` |
| NYC-Q8 | `reddit r/FoodNYC brunch recommendations` |
| NYC-Q9 | `reddit AskNYC where to eat 2024` |
| NYC-Q10 | `reddit FoodNYC dinner recommendations 2025` |
| NYC-Q11 | `reddit AskNYC happy hour recommendations` |
| NYC-Q12 | `reddit FoodNYC cheap eats recommendations` |

Q9 to Q12 are pre-registered reserves. They run, in order, only if Q1 to Q8 leave a city short of 20. If all 12 leave a city short, collection for that city stops at what it has. No query is added, reworded or reordered after the first search.

## 4. Selection rule

- Walk each city's queries in order. Within a query, walk its results in result order. A URL already seen (under any query) is skipped and logged as a duplicate.
- **The first 20 qualifying posts per city, in that order, are the set.** Nothing after the 20th is looked at for that city.

## 5. Qualification (all must hold)

1. **Source:** the result is a thread or post on one of the §1 sources. Subreddit wikis, listicles, comment permalinks to other content, and search or index pages don't qualify. A comment permalink is resolved to its parent post, and that post is what's judged.
2. **Subreddit or forum:** Reddit posts come from r/StLouis (St. Louis) or r/AskNYC / r/FoodNYC (New York). Tripadvisor posts come from the St. Louis or New York City forum. Quora questions name the city.
3. **City:** the post is about eating or drinking in that city (St. Louis city or county; NYC's five boroughs).
4. **Asks for recommendations on where to eat or drink:** going to a restaurant, bar, café, bakery or food stall. Grocery shopping, ingredient sourcing, delivery-only, catering, cooking and jobs don't count.
5. **Not "Is X good?"** and **names no venue:** a post that names any specific restaurant, bar or café (to evaluate, compare, find something "like", or as already tried) is excluded. This is the strict reading of "posts that name the answer". Named neighbourhoods, cuisines and dishes are fine.
6. **Date:** posted between 2023-01-01 and 2026-10-26 inclusive (UTC), taken from the source page's own timestamp.
7. **Verifiable verbatim:** title and body are extracted **deterministically from the source page's raw HTML** (no summarising model in the loop), and the date is read from the same page. A page that can't be fetched raw, or whose body is `[removed]` or `[deleted]`, doesn't qualify ("unverifiable").
8. **No personal detail:** a post whose text contains a person's name, a handle, a contact detail or an exact private address is excluded rather than redacted, since the text must stay verbatim. Usernames are never recorded.
9. **English.**
10. **Not a meta post:** mod threads, surveys, promotions and "I made a list" posts don't qualify.

## 6. What's recorded per qualifying post (`fresh_asks.json`)

`id`, `city`, `source`, `url` (canonical, query string stripped), `post_date` (ISO date, UTC), `query_id`, `query`, `result_position` (1-based, within that query), `title`, `body`, `text`, `sha256`.

- `text` = `title` + `"\n\n"` + `body` when the body is non-empty, otherwise `title`.
- Whitespace is trimmed only at the ends of `title` and `body`.
- HTML-to-text rendering of the body: block elements (paragraphs, list items, line breaks) become newlines, with a blank line between paragraphs; list items are prefixed `- `; inline markup is dropped while its text is kept; HTML entities are decoded.
- `sha256` = hex SHA-256 of `text`, UTF-8. This is for the "never in a wall" hash check.
- Never recorded: usernames, flair, vote counts or comments.

Conduct: read-only GETs with a generic browser User-Agent. No login, post, comment, vote or contact. No name or email in any request.

## 7. Run log (appended during collection)

### 7.1 Deviations found while running v1 (disclosed, not hidden)

- **D1 · how Reddit text is verified.** `www.reddit.com` serves scripted clients a JavaScript proof-of-work page, and `old.reddit.com` redirects to login. I didn't try to get around either. Reddit posts are therefore read from **Reddit's own submission JSON as archived by Arctic Shift** (`arctic-shift.photon-reddit.com/api/posts/ids`), **cross-checked against PullPush** (`api.pullpush.io/reddit/search/submission/?ids=`). A post qualifies only if both archives return it and agree exactly on title, selftext and `created_utc`. No author field is ever stored.
- **D2 · body rendering.** Because the source is the JSON, `body` is Reddit's `selftext`: the markdown the asker typed, with only `&amp; &lt; &gt;` decoded and the ends trimmed. That is closer to verbatim than §6's HTML-to-text rule, which therefore isn't needed.
- **D3 · mirrors.** Most Reddit hits from the search tool were Redlib or other mirror front-ends (`lr.vern.cc`, `lr.*.psf.lt`, `reddit.birdcat.cafe`, `*.lr.ggtyler.dev`, `reddit.sentinel-team.org`). A mirror URL is resolved by its post id to the canonical `https://www.reddit.com/r/<sub>/comments/<id>/…` post and judged as that post. Mirror index pages (`/r/<sub>/hot`, `/r/<sub>`) are index pages and don't qualify.
- **D4 · Tripadvisor and Quora.** Both return HTTP 403 to a raw GET, so no Tripadvisor or Quora post can pass rule 7. In practice the search tool returned one Tripadvisor thread and no Quora threads.

### 7.2 v1 log: every result of every query, in result order

Key: **Q** qualifies · **x-src** not a §1 source (blog, listicle, press, other forum, SEO page) · **x-idx** index or wiki page · **x-sub** subreddit not in §1 · **x-date** outside the window · **x-venue** names a venue · **x-verify** text can't be fetched raw · **dup** URL or post already seen.

**STL-Q1** `reddit r/StLouis where should I eat recommendations`
1. reddit.birdcat.cafe/r/StLouis/comments/28qp4z · x-date (r/StLouis, 2014-06-21)
2. gummysearch.com/r/STLFood · x-src
3. axebps-redlib.hf.space/r/STLFood/hot · x-idx, x-sub
4. lr.in.psf.lt/r/StLouis/comments/28qp4z · dup (post 28qp4z)
5. lr.eu.psf.lt/r/STLFood/comments/1dsumps · x-sub (r/STLFood, 2024-07-01)
6. theinfatuation.com · x-src
7. lucismorsels.com · x-src
8. housefulofnicholes.com · x-src
9. reddit.sudovanilla.org/r/stlfood · x-idx, x-sub

**STL-Q2** `reddit r/StLouis restaurant recommendations visiting St. Louis`
1. reddit.sentinel-team.org/posts/1tcf4uh (snapshot) → r/StLouis 1tcf4uh, 2026-05-13 · **Q → STL-01**
2. forums.theknot.com · x-src
3. forum.quartertothree.com · x-src
4. lr.vern.cc/r/StLouis/comments/53933v · x-date (2016-09-17)
5. stlpr.org · x-src
6. axebps-redlib.hf.space/r/STLFood/hot · dup
7. news.stlpublicradio.org · x-src
8. smokingmeatforums.com post-2623925 · x-src
9. smokingmeatforums.com post-2623912 · x-src

**STL-Q3** `reddit r/StLouis best bars recommendations`
1. lr.vern.cc/r/StLouis/comments/1b5icdr · r/StLouis, 2024-03-03 · **Q → STL-02**
2. to 9. riverfronttimes.com ×3, hoodline.com ×3, stlmag.com, do2.dr-chuck.com · x-src

**STL-Q4** `tripadvisor St. Louis forum where to eat recommendations`
1. to 9. cyclonefanatic.com, stacker.com, th.foursquare.com, csr.hdsupply.com, forums.anandtech.com, cathe.com, cruisecritic.com, meetingguide.aa.org, maint.oli.org · x-src (no Tripadvisor thread returned)

**STL-Q5** `quora where should I eat in St. Louis Missouri`
1. to 9. theinfatuation.com (dup), housefulofnicholes.com (dup), forums.theknot.com, lucismorsels.com (dup), wanderlog.com, saintlouis.thescoutguide.com, narmare.lansforsakringar.se, meetingguide.aa.org (dup), subscribe.adey.com · x-src (no Quora page returned)

**STL-Q6** `reddit r/StLouis date night restaurant suggestions`
1. to 9. explorestlouis.com, lacledeslanding.com ×2, stlpr.org, thescoutguide.com, opentable.co.th, wyndy.com, cozymeal.com, trunking.opensips.org · x-src

**STL-Q7** `reddit r/StLouis food recommendations first time in St. Louis`
1. reddit.sentinel-team.org/posts/1tcf4uh · dup
2. smokingmeatforums.com · x-src
3. theinfatuation.com · dup
4. to 8. smokingmeatforums.com ×5 · x-src
9. axebps-redlib.hf.space/r/STLFood/hot · dup
10. smokingmeatforums.com · x-src

**STL-Q8** `reddit r/StLouis brunch recommendations`
1. reddit.birdcat.cafe …/28qp4z · dup
2. lr.in.psf.lt …/28qp4z · dup
3. gummysearch.com · dup
4. to 9. stlpr.org, news.stlpublicradio.org, csr.hdsupply.com, hoodline.com, ftp.dundeesciencecentre.org.uk, stlpr.org · x-src

**STL-Q9** `reddit StLouis where to eat 2024` (reserve)
1. to 9. th.foursquare.com (dup), stlmag.com, stlouisarts.org ×2, meetingguide.aa.org (dup), riverfronttimes.com, housefulofnicholes.com (dup), cyclonefanatic.com (dup), ph.hotels.com · x-src

**STL-Q10** `reddit StLouis dinner recommendations 2025` (reserve)
1. axebps-redlib.hf.space/r/STLFood/hot · dup
2. bobistheoilguy.com · x-src
3. to 9. stlmag.com dining pages ×7 · x-src

**STL-Q11** `reddit StLouis happy hour recommendations` (reserve)
1. to 9. forum.nuaire.co.uk, stlmag.com ×3, warpspeed.level1techs.com, csr.hdsupply.com, m.fightcancer.org, v5.boldsystems.org, do2.dr-chuck.com · x-src

**STL-Q12** `reddit StLouis cheap eats recommendations` (reserve)
1. gummysearch.com · dup
2. lr.vern.cc/r/StLouis/comments/173uxfk · r/StLouis, 2023-10-09 · **x-venue** (the body names Pho Grand, Corner 17 and Joy Luck)
3. to 9. stlmag.com ×2, hoodline.com, aam-us.org, stacker.com, riverfronttimes.com, foodnetwork.com · x-src

**NYC-Q1** `reddit r/AskNYC where should I eat recommendations`
1. scraper.emaerket.dk · x-src
2. pol1.lr.ggtyler.dev/r/AskNYC/comments/1i266lx · r/AskNYC, 2025-01-15 · **Q → NYC-01**
3. to 9. acknowledging.embracerace.org, api.bybrand.io, dinneralovestory.substack.com, amateurgourmet.com, beccafreeman.substack.com, maybelline.it.com, ytravelblog.com · x-src

**NYC-Q2** `reddit r/FoodNYC restaurant recommendations`
1. scraper.emaerket.dk · dup
2. to 9. tigerdroppings.com ×2, club.fraiche.io ×2, therelisher.substack.com, forum.broadwayworld.com, miscellaneousgood.substack.com, finedininglovers.com · x-src

**NYC-Q3** `reddit r/AskNYC bar recommendations`
1. to 10. meetingguide.aa.org, insidehook.com ×5, pi.fyi, fodors.com ×3 · x-src

**NYC-Q4** `tripadvisor New York City forum where to eat recommendations`
1. tripadvisor.co.nz/ShowTopic-g60763-i5-k14445321-What_to_eat-New_York_City_New_York.html · **x-verify** (HTTP 403 on .co.nz and .com; post date not checked)
2. acknowledging.embracerace.org · dup
3. to 9. boards.ie ×2, blog.travefy.com, smokingmeatforums.com, mumsnet.com ×2, maybelline.it.com (dup) · x-src

**NYC-Q5** `quora where should I eat in New York City`
1. to 9. antrieu.substack.com, dinneralovestory.substack.com (dup), amateurgourmet.com (dup), testaction.babson.edu, community.realventures.com, dinneralovestory …/comments, maybelline.it.com (dup), girlwiththepassport.com, goodreads.com · x-src (no Quora page returned)

**NYC-Q6** `reddit r/FoodNYC date night restaurant suggestions`
1. to 9. cozymeal.com ×2, theinfatuation.com ×2, sheneedsasnack.substack.com, arlohotels.com ×2, domino.com, opentable.com · x-src

**NYC-Q7** `reddit r/AskNYC first time in NYC food recommendations`
1. to 9. polycount.com ×2, tildes.net, fishbowlapp.com, jenglantz.substack.com, forums.theknot.com ×2, hungryonion.org, forums.anandtech.com · x-src

**NYC-Q8** `reddit r/FoodNYC brunch recommendations`
1. lr.eu.psf.lt/r/FoodNYC/comments/1dw3dqc · r/FoodNYC, 2024-07-05 · **Q → NYC-02**
2. to 9. thetravel.com, bellaiazzetta.substack.com, tigerdroppings.com, blog.resy.com ×2, timeout.com ×2, bloggeratlarge.com · x-src

**NYC-Q9** `reddit AskNYC where to eat 2024` (reserve)
1. to 9. antrieu.substack.com (dup), andreastrong.substack.com ×2, bookishramblings.substack.com, scheckeats.substack.com, dinneralovestory.substack.com (dup), blog.resy.com ×2, localadventurer.com · x-src

**NYC-Q10** `reddit FoodNYC dinner recommendations 2025` (reserve)
1. to 9. roomboard.ipso.ch, hungryonion.org, eregistrasi.bpkad.inhilkab.go.id, timeout.com, dinneralovestory ×2 (dup), kitchensense.substack.com, answer.polygraph.net, gis.christianperone.com · x-src

**NYC-Q11** `reddit AskNYC happy hour recommendations` (reserve)
1. to 9. dev.asburyseminary.edu ×2, freetoursbyfoot.com, mail.hteknologi.com, meetingguide.aa.org ×2, blog.theagencyre.com, opentable.sg, opentable.com · x-src

**NYC-Q12** `reddit FoodNYC cheap eats recommendations` (reserve)
1. to 9. acknowledging.embracerace.org (dup), robertsietsema.substack.com, timeout.com, fodors.com ×2, thatswhatshehad.com, leeabbamonte.com, also.kottke.org, grandavehousing.calpoly.edu · x-src

**v1 result: St. Louis 2 qualifying (STL-01, STL-02), New York 2 qualifying (NYC-01, NYC-02).** All 12 queries per city are exhausted. The general web search tool rarely returns Reddit threads (often only mirrors), and returned no Tripadvisor thread it could fetch and no Quora thread. v1 stops here, as §3 requires.

## 8. Protocol v2 addendum (written after v1 finished, BEFORE any v2 search)

Why: v1 can't reach 20 per city because of the instrument, not the supply of questions. v2 swaps in a search instrument whose result order is deterministic and reproducible. Roman decides whether to freeze v1 alone (4 questions) or v1 + v2. Nothing below was chosen after looking at v2 results.

- **Instrument:** the Arctic Shift Reddit archive search, `GET https://arctic-shift.photon-reddit.com/api/posts/search?subreddit=<sub>&title=<term>&after=2023-01-01&before=2026-10-27&sort=desc&limit=100&fields=id,subreddit,title,selftext,created_utc,permalink` (keyword search on the title, newest first). No author field is requested.
- **Subreddits:** St. Louis: `StLouis`. New York: `AskNYC` and `FoodNYC`. For each term, the two NYC result lists are merged by `created_utc`, newest first. Ties are broken by id.
- **Terms, in this order** (the same for both cities):

| id | `title=` term |
|---|---|
| V2-T1 | `restaurant recommendations` |
| V2-T2 | `where to eat` |
| V2-T3 | `where should I eat` |
| V2-T4 | `food recommendations` |
| V2-T5 | `bar recommendations` |
| V2-T6 | `dinner recommendations` |
| V2-T7 | `brunch recommendations` |
| V2-T8 | `places to eat` |

- **Selection:** a city's set is v1's qualifying posts in v1 order, followed by v2's qualifying posts in v2 order (term by term; within a term, result order), **until the city has 20**. Posts already seen are skipped as dup. Only the first 100 results of each term are walked (one page, no paging).
- **Qualification:** §5 rules 1 to 10 unchanged, with D1 and D2 applied: text and date come from the Arctic Shift record, which must match PullPush exactly. A post missing from PullPush is `x-verify`.
- **Additional exclusions, set now:** link or image posts whose question is only in an image (title alone isn't a recommendation question) → x-notask. Posts asking about a specific dish or cuisine **do** qualify ("where can I get good pho?"), since they ask where to eat. Posts asking only for opinions, news or closures don't (x-notask). Posts set outside the city (for example "near JFK" in NYC counts; "in Chicago" doesn't) → x-city.
- **Log:** every v2 post walked before a city reaches 20 is listed below with its disposition.

### 8.1 v2 run log

**Deviations found while running v2**
- **D5 · fields.** The search API rejects `permalink` as a field, so it was dropped from `fields=`. URLs are built as `https://www.reddit.com/r/<sub>/comments/<id>/`.
- **D6 · retries.** The archive answers busy queries with HTTP 422 or 500 timeouts. The search retries until it succeeds. A first NYC run was discarded unread because my script could reuse the previous term's data after six failed retries. NYC was re-run with a script that aborts on failure. No St. Louis term hit that path: at most 5 retries, then success.
- **D7 · "removed" counts as unverifiable.** A post the archive marks `removed_by_category` (automod, moderator or Reddit removal) is x-verify even when its text survives in the archive, because a reader following the URL can't see it. This is rule 7's "[removed]" case applied to the post's status. It only excludes.
- **D8 · build step.** At build time Arctic Shift was returning 500s, so `fresh_asks.json` was built from the Arctic Shift records saved during the run (v2 search results; the `/ids` records for v1) and re-checked live against PullPush: exact title, selftext and `created_utc`, and not removed.

**St. Louis · V2-T1 `restaurant recommendations`** (r/StLouis, newest first; v1's STL-01 and STL-02 come first)
1. 1x7mxwl 2026-10-16 · x-verify (not in PullPush)
2. 1vfnj84 2026-08-04 · x-notask (explicitly non-restaurant: gifts and activities)
3. 1tl61mg 2026-05-23 · x-verify (body [removed]; the title also names a venue)
4. 1t1arg5 2026-05-02 · x-venue (Sabroso)
5. 1rpdzvc 2026-03-09 · **Q → STL-03** (title only, no body)
6. 1rkuycp 2026-03-04 · x-verify (body [removed])
7. 1renp9u 2026-02-25 · x-venue (Atchafalaya, a New Orleans restaurant named as the model)
8. 1qlqpxt 2026-01-24 · **Q → STL-04**
9. 1qewzvl 2026-01-17 · **Q → STL-05**
10. 1pxzfar 2025-12-28 · x-venue (Nubby, Blarney, Frankie G)
11. 1px2762 2025-12-27 · x-city (Illinois side, Wood River)
12. 1p5oolk 2025-11-24 · **Q → STL-06**
13. 1ot5mhg 2025-11-10 · x-verify (removed: automod_filtered)
14. 1o4ov1j 2025-10-12 · x-verify (removed: automod_filtered)
15. 1ns8kah 2025-09-27 · **Q → STL-07**
16. 1nl1n2r 2025-09-19 · x-venue (Taco Buddha)
17. 1nebypr 2025-09-11 · x-venue (Wright's Tavern)
18. 1mp50bg 2025-08-13 · **Q → STL-08**
19. 1l2mw1l 2025-06-03 · x-verify (removed: reddit)
20. 1kz9mfg 2025-05-30 · x-venue (Old Rock House)
21. 1k8en2x 2025-04-26 · **Q → STL-09**
22. 1iyuzk6 2025-02-26 · x-verify (archives disagree)
23. 1i8z7yn 2025-01-24 · x-verify (body [removed])
24. 1i5egnp 2025-01-20 · x-venue (Pasta House)
25. 1hocf8j 2024-12-28 · x-notask (Uber Eats, delivery-only)
26. 1ghfyod 2024-11-01 · **Q → STL-10**
27. 1g25bd2 2024-10-12 · **Q → STL-11** (title only)
28. 1e8v0g1 2024-07-21 · **Q → STL-12**
29. 1e2m0n4 2024-07-13 · **Q → STL-13**
30. 1dar0x9 2024-06-08 · **Q → STL-14**
31. 1d58vmy 2024-05-31 · x-venue (lists seven restaurants and asks which one)
32. 1cwvy6q 2024-05-21 · x-venue (Olive Garden, Carrabba's)
33. 1coooo8 2024-05-10 · **Q → STL-15**
34. 1c88h9m 2024-04-19 · x-verify (archives disagree; it also names Takashima)
35. 1bufaa1 2024-04-03 · **Q → STL-16** (City Museum and the zoo are attractions, not eat-or-drink venues)
36. 1bbdet7 2024-03-10 · x-city (O'Fallon, MO, in St. Charles County)
37. 1apx9bf 2024-02-13 · x-venue (Seoul Garden)
38. 1aj9tvb 2024-02-05 · x-verify (archives disagree)
39. 1ah7jky 2024-02-02 · x-verify (archives disagree)
40. 18sc07w 2023-12-27 · x-verify (archives disagree)
41. 18jux15 2023-12-16 · **Q → STL-17**
42. 18aobox 2023-12-04 · x-venue (Salt and Smoke, Seoul Taco, The Pageant)
43. 1860h88 2023-11-28 · **Q → STL-18**
44. 185q5i6 2023-11-28 · **Q → STL-19**
45. 16ruyqa 2023-09-25 · **Q → STL-20**. St. Louis reaches 20; the walk stops.

- **D9 · NYC slicing (written before any NYC v2 result was seen).** The archive can't run `title=` over r/AskNYC's whole window: it timed out on 20 of 20 tries for V2-T1, and its docs say title search isn't supported for very active subreddits. NYC therefore runs each (subreddit, term) query **in calendar-quarter slices, newest first** (2026-10-01 to 2026-10-27, then 2026-07-01 to 2026-10-01, and so on back to 2023-01-01). It keeps results until it has the 100 newest for that subreddit. That is the same set and order the unsliced `sort=desc&limit=100` query would return. A slice that still fails after 20 tries is halved, and the halves run newest first. The two subreddits are then merged newest first, as in §8. The selection rule is unchanged.

**New York · v2** (v1's NYC-01 and NYC-02 come first)
Arctic Shift returned HTTP 500 on every endpoint for about an hour on 27–28 Oct. Nothing was searched during the outage. The D9 sliced run of V2-T1 then finished cleanly (AskNYC 100, FoodNYC 100, merged 200).

**New York · V2-T1 `restaurant recommendations`** (r/AskNYC + r/FoodNYC merged, newest first)
1. 1xcr9a2 2026-10-22 · x-verify (body [removed])
2. 1xcr0w6 2026-10-22 · x-verify (body [removed])
3. 1xc7sgg 2026-10-22 · x-verify (body [removed])
4. 1xc3g9j 2026-10-21 · x-verify (not in PullPush)
5. 1x6s7t7 2026-10-15 · x-verify (not in PullPush)
6. 1x3myak 2026-10-11 · **Q → NYC-03**
7. 1x2o1nw 2026-10-10 · x-venue (Casa Carmen)
8. 1x22mts 2026-10-10 · **Q → NYC-04** (title only; MSG is an arena, not an eat-or-drink venue)
9. 1wy8js5 2026-10-05 · x-verify (not in PullPush)
10. 1wwa67j 2026-10-03 · x-verify (archives disagree)
11. 1ww9xvg 2026-10-03 · x-verify (body [removed])
12. 1wttx6g 2026-09-30 · **Q → NYC-05**
13. 1wswcm8 2026-09-29 · x-verify (not in PullPush)
14. 1ws5ue5 2026-09-28 · x-verify (not in PullPush)
15. 1ws202d 2026-09-28 · **Q → NYC-06**
16. 1wok1sq 2026-09-23 · x-verify (body [removed])
17. 1wdza92 2026-09-12 · **Q → NYC-07**
18. 1wdpwm4 2026-09-11 · x-verify (not in PullPush)
19. 1wb1gwg 2026-09-08 · x-verify (not in PullPush)
20. 1w1tuj5 2026-08-29 · x-verify (not in PullPush)
21. 1vx2b2x 2026-08-24 · **Q → NYC-08**
22. 1vwffzz 2026-08-23 · **Q → NYC-09** (refers to an unnamed restaurant in New Jersey)
23. 1vt3k0h 2026-08-20 · **Q → NYC-10** (names a performer, Harry Styles, as the reason for the trip. Rule 8 is read as private personal detail; a public performer isn't one. The same reading as STL-09's band name)
24. 1vt2yyp 2026-08-19 · x-verify (body [removed])
25. 1vqboxp 2026-08-16 · x-verify (body [removed])
26. 1vn9ab4 2026-08-13 · x-verify (body [removed])
27. 1vlgnih 2026-08-11 · x-verify (body [removed])
28. 1vko8f4 2026-08-10 · **Q → NYC-11**
29. 1vk36ny 2026-08-09 · x-verify (archives disagree)
30. 1vheunv 2026-08-06 · x-venue (Bibble and Sip, Supermoon and others)
31. 1vg2cb1 2026-08-05 · **Q → NYC-12**
32. 1vdy59i 2026-08-03 · **Q → NYC-13** (the American Museum of Natural History is a museum, not an eat-or-drink venue)
33. 1vb3msa 2026-07-30 · x-venue (Crab House, Astoria Seafood and others)
34. 1v6g13r 2026-07-25 · **Q → NYC-14**
35. 1v6dl3j 2026-07-25 · x-venue (Old Mates Pub, Pearl Diner, Maison Passerelle)
36. 1v4rykm 2026-07-23 · x-verify (removed: automod_filtered)
37. 1v1tuv8 2026-07-20 · **Q → NYC-15**
38. 1uykv4t 2026-07-17 · x-venue (Beetle House)
39. 1utk512 2026-07-11 · x-verify (removed: automod_filtered)
40. 1uruz59 2026-07-09 · **Q → NYC-16**
41. 1upv314 2026-07-07 · **Q → NYC-17** (cakes from a bakery, plus restaurants; rule 4 counts bakeries)
42. 1uk02v5 2026-06-30 · **Q → NYC-18**
43. 1ueief7 2026-06-24 · x-venue (Best Sichuan)
44. 1u8rvud 2026-06-18 · **Q → NYC-19**
45. 1u6at6g 2026-06-15 · **Q → NYC-20**. New York reaches 20; the walk stops. (The next result, 1u6as40, is the same text cross-posted to r/AskNYC. It wasn't reached.)

## 9. Final result

| city | v1 | v2 | total | date range |
|---|---|---|---|---|
| St. Louis | 2 | 18 | **20** | 2023-09-25 to 2026-05-13 |
| New York | 2 | 18 | **20** | 2024-07-05 to 2026-10-11 |

- Excluded post-level candidates logged above. **v1:** 5 (St. Louis: 2 x-date, 1 x-sub, 1 x-venue; New York: 1 x-verify, the Tripadvisor thread). Every other v1 result was x-src, x-idx or dup. **v2:** 27 for St. Louis (45 walked, 18 Q) and 27 for New York (45 walked, 18 Q). In total, **40 qualifying and 59 excluded post candidates**.
- All 40 `sha256` values are distinct, as are all 40 URLs.
- Notes carried as logged, with no post-hoc exclusions: STL-01's walking-distance area appears only in an image. STL-03, STL-11 and NYC-04 are title-only.
- Because PullPush lags, posts from the last weeks before 27 Oct mostly fall to x-verify. The set therefore leans slightly older than the raw result order.
