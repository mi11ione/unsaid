# Token note for /agents (copy for the page; Agent C places it)

**Until 30 Oct 23:45 ET the API needs a token.** It is in the Devpost testing instructions. After that the token is removed and the API is open, rate-limited to 3 fresh runs per hour per address. Repeat queries are cached and free.

**REST.** Send the token as a header or a query parameter:

```bash
curl -N -H "Authorization: Bearer $UNSAID_TOKEN" \
  "https://unsaid.pages.dev/api/unsaid?city=st-louis&loves=%5B%22Frankie%20Beverly%20%26%20Maze%22%2C%22rib%20tips%22%5D"
# or: ...&token=$UNSAID_TOKEN   (or the header X-Unsaid-Token: $UNSAID_TOKEN)
```

`loves` is a JSON array of up to three items: plain text, `{"text": "...", "type": "movie"}`, or a chip from `/api/resolve`. A `|`-separated list also works. The reply is NDJSON; the last line is `{"type":"done","result":{...}}`. `GET /api/health` never needs the token.

**MCP.** The MCP server runs locally over stdio, so it needs no token:

```bash
claude mcp add unsaid -e UNSAID_MODE=fake -- python3 -I /path/to/unsaid/agent/unsaid_mcp.py
```

Two tools: `unsaid_places(loves, city)` returns the places no AI names, ranked by Qloo. `qloo_places(loves, city)` returns Qloo's top 50 for the same loves with nothing crossed out; it is the meter's "with" arm. A remote `/mcp` endpoint, if it ships, sits behind the same token.

The meter line: ⟦M_ALONE⟧ → ⟦M_QLOO⟧ (filled from `k10_meter.py`, or the sentence is deleted under the bracket rule).
