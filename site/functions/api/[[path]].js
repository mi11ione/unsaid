// Cloudflare Pages Function: proxies /api/* to the engine host (UNSAID.md §3.9).
// - The engine's address lives only in env ENGINE_URL (a Pages secret); it never reaches the browser.
// - Adds the visitor's country (CF-IPCountry) for the Gemini geo-gate, and the visitor's IP for per-IP limits,
//   both signed with env PROXY_SECRET so the engine trusts them only when they come from here.
// - The visitor's UNSAID token (Authorization, X-Unsaid-Token or ?token=) is passed through untouched.
// - A cold or slow engine (Render free spins down after 15 min) gets the `waking` state, never someone else's cards.

const UPSTREAM_MS = { stream: 12000, other: 8000 };
// x-unsaid-bench: k11's per-IP-limit bypass; passed through blindly, validated only by the engine.
const PASS_REQ = ["authorization", "x-unsaid-token", "accept", "x-unsaid-bench"];
const PASS_RES = ["content-type", "cache-control", "retry-after", "www-authenticate", "x-unsaid-state"];
const WAKING_TEXT = "waking the ranker · about a minute";

function respond(status, body, type, extra) {
  const headers = new Headers({ "content-type": type, "cache-control": "no-store", "x-unsaid-state": "waking" });
  for (const [k, v] of Object.entries(extra || {})) headers.set(k, v);
  return new Response(body, { status, headers });
}

function waking(path) {
  const retry = { "retry-after": "20" };
  if (path === "/api/health") {
    return respond(503, JSON.stringify({ ok: false, state: "waking", note: WAKING_TEXT }), "application/json", retry);
  }
  if (path === "/api/unsaid") {
    const result = { status: "waking", flags: [], picks: [], reserves: [], wall: [], note: WAKING_TEXT };
    const lines = [{ type: "status", state: "waking", text: WAKING_TEXT }, { type: "done", result }];
    return respond(503, lines.map((l) => JSON.stringify(l)).join("\n") + "\n", "application/x-ndjson", retry);
  }
  return respond(503, JSON.stringify({ status: "waking", note: WAKING_TEXT }), "application/json", retry);
}

export async function onRequest(ctx) {
  const { request, env, params } = ctx;
  if (request.method !== "GET" && request.method !== "HEAD") {
    return new Response(JSON.stringify({ status: "method_not_allowed" }), {
      status: 405, headers: { "content-type": "application/json", allow: "GET, HEAD" },
    });
  }
  const url = new URL(request.url);
  const parts = [].concat(params.path || []);
  const path = "/api/" + parts.map(encodeURIComponent).join("/");
  if (!env.ENGINE_URL) return waking(path);

  const target = new URL(path + url.search, env.ENGINE_URL);
  const headers = new Headers({ "user-agent": "Mozilla/5.0 (compatible)" });
  for (const k of PASS_REQ) {
    const v = request.headers.get(k);
    if (v) headers.set(k, v);
  }
  // via the unsaid.mi11ion.io edge Worker, the visitor's IP and country arrive signed with PROXY_SECRET
  const edge = env.PROXY_SECRET && request.headers.get("x-unsaid-edge-key") === env.PROXY_SECRET;
  const country = (edge && request.headers.get("x-unsaid-edge-country")) || request.headers.get("cf-ipcountry")
    || (request.cf && request.cf.country) || "";
  headers.set("cf-ipcountry", country);
  headers.set("x-unsaid-country", country);
  headers.set("x-unsaid-client-ip", (edge && request.headers.get("x-unsaid-edge-ip")) || request.headers.get("cf-connecting-ip") || "");
  if (env.PROXY_SECRET) headers.set("x-unsaid-proxy", env.PROXY_SECRET);

  const limit = Number(env.UPSTREAM_TIMEOUT_MS) || (path === "/api/unsaid" ? UPSTREAM_MS.stream : UPSTREAM_MS.other);
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), limit);
  const nudge = () => ctx.waitUntil(fetch(new URL("/api/health", env.ENGINE_URL)).catch(() => {}));
  let res;
  try {
    // Resolves as soon as the engine sends headers; the NDJSON body then streams through untouched.
    res = await fetch(target, { method: request.method, headers, signal: ctrl.signal, redirect: "manual" });
  } catch (e) {
    nudge(); // keep waking it in the background while the page streams the dated wall
    return waking(path);
  } finally {
    clearTimeout(timer);
  }
  // Render answers 502/503 (or its own page) while the instance spins up; only our engine sets x-unsaid-state.
  if ([502, 503, 504].includes(res.status) || !res.headers.get("x-unsaid-state")) {
    nudge();
    return waking(path);
  }
  const out = new Headers();
  for (const k of PASS_RES) {
    const v = res.headers.get(k);
    if (v) out.set(k, v);
  }
  return new Response(res.body, { status: res.status, headers: out });
}
