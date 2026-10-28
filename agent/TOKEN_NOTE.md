# Token note for /agents (copy for the page; Agent C places it)

**Until 30 Oct 23:45 ET the API needs a token.** It is in the Devpost testing instructions. After that the token is removed and the API is open, rate-limited to 3 fresh runs per hour per address. Repeat queries are cached and free.

**REST.** Send the token as a header or a query parameter:

```bash
curl -N -H "Authorization: Bearer $UNSAID_TOKEN" \
  "https://unsaid-ang.pages.dev/api/unsaid?city=st-louis&loves=%5B%5B%22Frankie%20Beverly%20%26%20Maze%22%2C%20%22artist%22%5D%2C%20%5B%22The%20Original%20Kings%20of%20Comedy%22%2C%20%22movie%22%5D%2C%20%5B%22rib%20tips%22%2C%20%22tag%22%5D%5D"
# loves = [["Frankie Beverly & Maze", "artist"], ["The Original Kings of Comedy", "movie"], ["rib tips", "tag"]]
# or: ...&token=$UNSAID_TOKEN   (or the header X-Unsaid-Token: $UNSAID_TOKEN)
```

`loves` is a JSON array of up to three `[text, type]` pairs. Give a type for a dish (`"tag"`) and for a place (`"place"`): untyped, `"rib tips"` can resolve to a restaurant. Types: artist, movie, tv_show, book, podcast, videogame, brand, place, tag. Plain text, `{"text": "...", "type": "movie"}` and chips from `/api/resolve` also work. The reply is NDJSON; the last line is `{"type":"done","result":{...}}`. `GET /api/health` never needs the token.

**MCP.** The MCP server calls this API by default (`UNSAID_MODE=remote`), so it takes the same token:

```bash
claude mcp add unsaid -e UNSAID_MODE=remote -e UNSAID_TOKEN=<token> -- python3 -I /path/to/unsaid/agent/unsaid_mcp.py
```

Loves take the same `[text, type]` pairs. In remote mode the server lists `unsaid_places(loves, city)`: the places no AI names, ranked by Qloo. With `UNSAID_MODE=live` and a Qloo key it runs the engine locally and also lists `qloo_places(loves, city)`: Qloo's top 50 for the same loves, with nothing crossed out. That tool is the meter's "with" arm.

The meter line: ⟦M_ALONE⟧ → ⟦M_QLOO⟧ (filled from `k10_meter.py`, or the sentence is deleted under the bracket rule).
