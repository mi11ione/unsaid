// unsaid.mi11ion.io: passes every request through to the Pages site, with the visitor's IP and country signed with
// PROXY_SECRET so the Pages functions keep per-visitor limits and the Gemini geo-gate.
const ORIGIN = "https://unsaid-ang.pages.dev";

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const headers = new Headers(request.headers);
    headers.set("x-unsaid-edge-ip", request.headers.get("cf-connecting-ip") || "");
    headers.set("x-unsaid-edge-country", (request.cf && request.cf.country) || "");
    if (env.PROXY_SECRET) headers.set("x-unsaid-edge-key", env.PROXY_SECRET);
    const init = { method: request.method, headers, redirect: "manual" };
    if (!["GET", "HEAD"].includes(request.method)) init.body = request.body;
    return fetch(ORIGIN + url.pathname + url.search, init);
  },
};
