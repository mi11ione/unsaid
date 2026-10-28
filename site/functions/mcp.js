// Cloudflare Pages Function: proxies /mcp (the hosted MCP endpoint, MCP Streamable HTTP) to the engine host.
// Same rules as functions/api/[[path]].js: the engine's address lives only in env ENGINE_URL; the visitor's IP and
// country go up signed with env PROXY_SECRET (per-IP limits, the Gemini geo-gate); the visitor's token (Authorization,
// X-Unsaid-Token or ?token=) passes through untouched. POST bodies pass through; the SSE response streams back as is.
// A cold engine (Render free spins down) gets a JSON-RPC error with Retry-After, never someone else's result.

const HEADERS_MS = 100000;   // tools/call answers SSE at once; a JSON-only client may wait for the whole run (<= 90 s)
const PASS_REQ = ["authorization", "x-unsaid-token", "accept", "content-type", "mcp-protocol-version",
                  "mcp-session-id", "last-event-id", "origin", "x-unsaid-bench"];
const PASS_RES = ["content-type", "cache-control", "retry-after", "www-authenticate", "mcp-session-id", "allow",
                  "x-unsaid-state"];

function waking(id) {
  const body = { jsonrpc: "2.0", id: id === undefined ? null : id,
                 error: { code: -32000, message: "waking the ranker · about a minute; retry shortly" } };
  return new Response(JSON.stringify(body), {
    status: 503,
    headers: { "content-type": "application/json", "cache-control": "no-store", "retry-after": "20",
               "x-unsaid-state": "waking" },
  });
}

export async function onRequest(ctx) {
  const { request, env } = ctx;
  if (!["POST", "GET", "DELETE"].includes(request.method)) {
    return new Response(null, { status: 405, headers: { allow: "POST" } });
  }
  const body = request.method === "POST" ? await request.text() : null;
  let id;
  try { id = body ? JSON.parse(body).id : undefined; } catch (e) { id = undefined; }
  if (!env.ENGINE_URL) return waking(id);

  const url = new URL(request.url);
  const target = new URL("/mcp" + url.search, env.ENGINE_URL);
  const headers = new Headers({ "user-agent": "Mozilla/5.0 (compatible)" });
  for (const k of PASS_REQ) {
    const v = request.headers.get(k);
    if (v) headers.set(k, v);
  }
  const country = request.headers.get("cf-ipcountry") || (request.cf && request.cf.country) || "";
  headers.set("cf-ipcountry", country);
  headers.set("x-unsaid-country", country);
  headers.set("x-unsaid-client-ip", request.headers.get("cf-connecting-ip") || "");
  if (env.PROXY_SECRET) headers.set("x-unsaid-proxy", env.PROXY_SECRET);

  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), Number(env.MCP_HEADERS_MS) || HEADERS_MS);
  const nudge = () => ctx.waitUntil(fetch(new URL("/api/health", env.ENGINE_URL)).catch(() => {}));
  let res;
  try {
    res = await fetch(target, { method: request.method, headers, body, signal: ctrl.signal, redirect: "manual" });
  } catch (e) {
    nudge();
    return waking(id);
  } finally {
    clearTimeout(timer);
  }
  if ([502, 503, 504].includes(res.status) || !res.headers.get("x-unsaid-state")) {
    nudge();
    return waking(id);
  }
  const out = new Headers();
  for (const k of PASS_RES) {
    const v = res.headers.get(k);
    if (v) out.set(k, v);
  }
  return new Response(res.body, { status: res.status, headers: out });
}
