# The 60 s video: shot list and the source of every number

`media/video.html` is one deterministic timeline (`window.seek(t)`); `./render.sh video` builds its data, renders 30 fps
frames with `tools/cdp.mjs`, adds the UI-sound track and encodes `shots/video-60s-1920x1080.mp4` (H.264, yuv420p,
faststart) plus `shots/video-keyframes.png`. Set `URL=<live url>` to fill the end card; without it the card shows the
placeholder ⟦LIVE_URL⟧ in amber. All data comes through `tools/build_video_data.py`, which asserts each figure against
its source and fails the render on a mismatch. Its output, `data/live/video.json`, is gitignored (it holds Qloo results).

No humans, no voice. The installed macOS voices are the legacy ones (Fred, Kathy, Ralph…), not good enough, so there is
no voice-over cut. Sound: UI cues only (ticks, a strike swish, a two-note rise, key clicks), synthesised by
`tools/video_audio.py` from sine waves and seeded noise. No music, nothing licensed.

## Shots (59.5 s)

| t (s) | shot | on screen |
|---|---|---|
| 0.0–13.4 | the problem | "Ask an AI for a hidden gem in St. Louis." The 16 real hidden-gem asks run; for each, a dot per AI fills red if it named Mai Lee. **Mai Lee** · Claude 13 of 16 · ChatGPT 10 of 16; the map (grey OSM places, red = Claude's census) with Mai Lee's ring pulsing. "Different AIs. The same secret, told to everyone." "Half of everything Claude recommends here is the same 29 places. ChatGPT's: 30." Mai Lee is struck. |
| 13.4–22.0 | the cross-out | "UNSAID crosses out every place the AIs name." "Asked 179 ways about St. Louis, Claude, ChatGPT and Gemini named 418 places." The wall's 418 names land most-named first, each struck, while the view zooms out; counter 0 → 418. "Good places. Everyone already gets them." |
| 22.0–37.4 | 7 for you | "Three things Cedric loves." (rib tips dims) → funnel 52 → ~~9~~ → 7 (+3 in reserve) → the seven cards, "7 for you. Ranked by Qloo." with the rib-tips line → card one: Starz Bar And Grill, "#4 for you. #30 for anyone.", NEVER SAID "Named 0 times in 179 asks.", BECAUSE "You love Frankie Beverly & Maze." |
| 37.4–45.0 | a judge strikes | "You're the judge. Know one? Strike it." Card 2 (Harlem Tap Room) is held and struck ("struck by you"); the first reserve, The Nation Bar And Grill (#2 for you, #19 for anyone), rises in after it, "rose in its place · a reserve no AI named"; later numbers move down one (the site's `strike()`). "A reserve rises. No AI named that one either." |
| 45.0–52.4 | an agent calls it | "Agents can call it too." Claude's `tool_use` of `unsaid_places` typed out; Claude's reply, two verbatim lines. |
| 52.4–59.5 | end card | UNSAID · "Everything the AIs tell everyone, crossed out." · **418 → 7** · "places the AIs gave everyone · left for Cedric, ranked by Qloo" · ⟦LIVE_URL⟧ · "try Cedric · St. Louis, or your own three loves" |

## Every number, and where it comes from

| number | meaning | source (checked by build_video_data.py) |
|---|---|---|
| 13 of 16 | Claude's hidden-gem asks naming Mai Lee | `harness/claude_answers.jsonl`, family `hidden`, city stl, counted with `census_stats.py`'s `gem_hit`; equals `site/data/census.json` stl.mailee_claude (= `harness/census_stats_claude.txt:59`) |
| 10 of 16 | ChatGPT's hidden-gem asks naming Mai Lee | `harness/codex_answers.jsonl` (superseded lines skipped, as `census_stats.load` does); equals census.json stl.chatgpt.gem (= `harness/census_stats_codex.txt:60`) |
| the 16 dot rows | which ask named Mai Lee, per AI | the same per-ask counts; ask texts from census.json stl.gem_asks |
| 29 / 30 | names carrying half of all mentions (K50), Claude / ChatGPT | census.json stl.k50 (`census_stats_claude.txt:44`) and stl.chatgpt.k50 (`census_stats_codex.txt:45`) |
| 64 | St. Louis asks per AI in the census (footer) | census.json stl.asks (`census_stats_claude.txt:3`) |
| 418 | distinct places on Cedric's wall | `site/data/live/stl_stl-cedric.json` result.counts.wall; recounted from result.wall grouped by `place` |
| 179 | stored asks behind that wall (Claude 88, ChatGPT 88, Gemini 3) | result.counts.asks; recounted as distinct (provider, phrasing_id, asked_at) in result.wall |
| 52 | U: Qloo's pool for his loves, 15 mi, rated 4.3+, open | result.counts.U (and every card's `U`) |
| 15 mi | radius | result.counts.R_mi |
| 9 | pool places the AIs named, struck | result.counts.struck_in_U |
| 43 | left after the strike | result.counts.S (asserted = 52 − 9) |
| 7 (+3) | cards and reserves | result.picks, result.reserves |
| #4 / #30, #5 / #36, #6 / #47, #8 / #39, #9 / #50, #10 / #48, #13 / #52 | each card's rank for him / for anyone among the same 52 | picks[].fit_rank / any_rank |
| 4.5, 4.4 · open | rating, open | picks[].rating (one decimal, as on the site), picks[].open |
| 0 times in 179 asks | card one's never-said line | picks[0].never_said.asks |
| #2 / #19 | the risen reserve, The Nation Bar And Grill | reserves[0].fit_rank / any_rank; reserves[0] rises first, as in `site/js/app.js` strike() |
| 43 calls, 27 Oct (footer) | Qloo calls for the run; its date | result.diag.qloo_calls; result.diag.as_of (01:49 UTC 28 Oct = 27 Oct ET) |
| 418 → 7 | end card | counts.wall → picks |

Words, not numbers, with sources:
- Card neighbourhoods, "what" lines, "because you love …": picks[] / reserves[] (loves shown as typed: `loves[].text`).
- "Rib tips: Qloo scores every place here the same, so the other two ranked.": result.flags `dead_love:Rib Tips`; the site's own dead-tag line (`UM.deadLine`), shortened.
- The `tool_use` block: Claude's own call, verbatim, from `agent/demo/claude_with.jsonl` (the JSON's line breaks are ours). That session's server ran in fake mode, so **its tool_result is not shown**.
- Claude's reply: two verbatim lines from the live run (claude -p, Claude Sonnet 5.5, live `unsaid_places`, Cedric's three loves, 28 Oct), kept outside the repo at `~/Desktop/qloo/private/agent_quote_cedric_202610280308.json`; the same run devpost.md quotes. The build re-checks both lines against it when the file is present. The footer says the call and the reply are each verbatim.
- Census footer: Claude Sonnet 5.5 and ChatGPT gpt-5.6-terra, no web search, 27 Oct 2026, pre-registered (census.json; codex answers' `model`).

Not on screen, on purpose: ⟦ASKS⟧-style placeholders other than ⟦LIVE_URL⟧, the meter (gate D failed, not featured), any latency, any NYC figure.
