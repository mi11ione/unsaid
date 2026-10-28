"""The three $0 lanes (UNSAID.md §3.6), the answer store and the resumable runner.

Every ask runs one official tool once, from a fresh empty temp dir, with stdin closed. Nothing here is callable from a
server path: claude and codex use Roman's subscriptions on this Mac only; gemini uses a free-tier key from the env.
Kept from each answer: venue names, neighbourhoods, timestamps, the raw answer text (for the reverse check) and the
instrument metadata (provider, model id, tool version, search on/off). No name or email goes in any request or header.
"""
import datetime, json, os, re, shutil, subprocess, sys, tempfile, threading, time, urllib.error, urllib.request
from collections import deque

HERE = os.path.dirname(os.path.abspath(__file__))
RUNS = os.path.join(HERE, "runs")
SCHEMA = os.path.join(HERE, "places.schema.json")
SYS_CLAUDE = "You are Claude, a helpful assistant chatting with a user in a consumer chat app."  # the census line
SYS_GEMINI = "You are Gemini, a helpful assistant chatting with a user in a consumer chat app."
TIMEOUT = 300
MIN_FREE_GB = float(os.environ.get("UNSAID_MIN_FREE_GB") or 3)  # abort cleanly below this (the disk filled on 28 Oct)


def disk_low():
    free = shutil.disk_usage(HERE).free / 1e9
    return "disk: %.1f GB free < %.0f GB floor" % (free, MIN_FREE_GB) if free < MIN_FREE_GB else None
CODEX_MODEL_DEFAULT = "gpt-5.6-terra"  # orchestrator decision 27 Oct; env CODEX_MODEL overrides


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def parse_places(text):
    """[{name, neighbourhood}] from a JSON array, a {"places": [...]} object, or the first [...] in the text."""
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    arr = None
    try:
        d = json.loads(t)
        arr = d.get("places") if isinstance(d, dict) else d
    except Exception:
        m = re.search(r"\[.*\]", t, re.S)
        if m:
            try:
                arr = json.loads(m.group(0))
            except Exception:
                arr = None
    if not isinstance(arr, list):
        return None
    out = []
    for x in arr:
        if isinstance(x, dict) and x.get("name"):
            out.append({"name": str(x["name"]).strip(),
                        "neighbourhood": str(x.get("neighbourhood") or x.get("neighborhood") or "").strip()})
    return out


def _version(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL).stdout.strip()
    except Exception:
        return ""


def _finish(res, raw, t0, s):
    """Fill status/places/timestamps. ok = a parsed list; unparsed = the tool answered but gave no list (kept, not
    retried: re-asking until it parses would bias the wall); failed = no answer (retried on the next run)."""
    res.setdefault("error", None)
    res["raw"] = raw
    res["asked_at"], res["answered_at"], res["secs"] = t0, now(), round(time.time() - s, 1)
    if res.get("status") != "failed":
        res["places"] = parse_places(raw)
        res["status"] = "ok" if res["places"] else "unparsed"
    else:
        res["places"] = None
    return res


class Lane:
    name = provider = assistant = ""
    workers = 1

    def check(self):
        return True, ""

    def pace(self):
        pass


class ClaudeLane(Lane):
    name, provider, assistant, workers = "claude", "anthropic", "Claude", 4

    def __init__(self):
        self.version = _version(["claude", "--version"])

    def check(self):
        if not shutil.which("claude"):
            return False, "needs the claude CLI (Claude Code) on PATH, signed in to Roman's plan"
        return True, "claude " + self.version

    def cmd(self, prompt, meter=False, mcp_config=None, search=False, system=None, tool="qloo_places"):
        """Walls, census, fresh asks: §3.6's line exactly. Meter (both arms, so they differ only in the tool):
        --safe-mode is swapped for --setting-sources local --disable-slash-commands, because --safe-mode drops every
        --mcp-config server (checked 27 Oct on 2.1.311: init showed mcp_servers [] and tools []). stream-json shows
        each tool_use. The "with" arm adds the one server and allows only qloo_places; unsaid_places is disallowed."""
        if search:  # the SEARCH-ON lane only (28 Oct): web tools on, nothing else; never mixed into the no-search census
            return ["claude", "-p", prompt, "--output-format", "stream-json", "--verbose", "--model", "sonnet",
                    "--tools", "WebSearch,WebFetch", "--allowedTools", "WebSearch", "WebFetch",
                    "--safe-mode", "--strict-mcp-config", "--no-session-persistence", "--system-prompt", system or SYS_CLAUDE]
        if not meter:
            return ["claude", "-p", prompt, "--output-format", "json", "--model", "sonnet", "--tools", "",
                    "--safe-mode", "--strict-mcp-config", "--no-session-persistence", "--system-prompt", SYS_CLAUDE]
        c = ["claude", "-p", prompt, "--output-format", "stream-json", "--verbose", "--model", "sonnet", "--tools", "",
             "--setting-sources", "local", "--disable-slash-commands", "--strict-mcp-config",
             "--no-session-persistence", "--system-prompt", SYS_CLAUDE]
        if mcp_config:
            other = "unsaid_places" if tool == "qloo_places" else "qloo_places"
            c += ["--mcp-config", mcp_config, "--allowedTools", "mcp__unsaid__" + tool,
                  "--disallowedTools", "mcp__unsaid__" + other]
        return c

    def ask(self, prompt, meter=False, mcp_config=None, search=False, system=None, tool="qloo_places", **_):
        t0, s = now(), time.time()
        res = {"tool": "claude-code " + self.version.split()[0] if self.version else "claude-code",
               "search": "off", "model": None, "model_source": "modelUsage"}
        with tempfile.TemporaryDirectory(prefix="unsaid-claude-") as cwd:
            try:
                p = subprocess.run(self.cmd(prompt, meter, mcp_config, search, system, tool), capture_output=True, text=True, cwd=cwd,
                                   timeout=TIMEOUT, stdin=subprocess.DEVNULL)
            except subprocess.TimeoutExpired:
                return _finish(dict(res, status="failed", error="timeout %ds" % TIMEOUT), "", t0, s)
        d, calls, results = None, [], []
        if search:
            res["search"] = "on"
        if meter or search:  # stream-json: count tool_use blocks, take the final result event
            for line in p.stdout.splitlines():
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                if e.get("type") == "system" and e.get("subtype") == "init":
                    res["mcp_servers"] = [(m.get("name"), m.get("status")) for m in e.get("mcp_servers") or []]
                    res["tools_offered"] = e.get("tools")
                for b in ((e.get("message") or {}).get("content") or []) if e.get("type") == "assistant" else []:
                    if isinstance(b, dict) and b.get("type") in ("tool_use", "server_tool_use"):
                        calls.append(b.get("name"))
                        if re.search(r"search|fetch", str(b.get("name")), re.I):
                            res["search"] = "on"
                for b in ((e.get("message") or {}).get("content") or []) if e.get("type") == "user" else []:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        results.append(b.get("content"))
                if e.get("type") == "result":
                    d = e
            res["tool_calls"], res["tools_called"] = len(calls), sorted(set(calls))
            if mcp_config:
                res["qloo"] = qloo_counts(results)
                res["tool_results"] = [trim_result(x) for x in results]
        else:
            try:
                d = json.loads(p.stdout)
            except Exception:
                d = None
        if not isinstance(d, dict):
            return _finish(dict(res, status="failed", error=("exit %s: %s" % (p.returncode, (p.stderr or p.stdout)[-300:])).strip()), "", t0, s)
        mu = d.get("modelUsage") or {}
        if mu:  # the model that did the work: most output tokens
            res["model"] = max(mu, key=lambda k: (mu[k] or {}).get("outputTokens", 0))
            res["models_seen"] = sorted(mu)
        res["num_turns"] = d.get("num_turns")
        if d.get("is_error") or p.returncode:
            return _finish(dict(res, status="failed", error=("%s: %s" % (d.get("subtype"), d.get("result")))[:300]), "", t0, s)
        return _finish(res, d.get("result") or "", t0, s)


class CodexLane(Lane):
    """codex exec --json streams thread.started / turn.* / item.* events. In codex-cli 0.164.0 no event carries the
    model id (checked in the binary: thread_id, items, usage only), so the model is pinned with -m $CODEX_MODEL and
    recorded with model_source "pinned"; if any event ever carries a "model" field, that value wins."""
    name, provider, assistant, workers = "codex", "openai", "ChatGPT", 2

    def __init__(self):
        self.version = _version(["codex", "--version"]) if shutil.which("codex") else ""
        self.model = os.environ.get("CODEX_MODEL", "").strip() or CODEX_MODEL_DEFAULT

    def check(self):
        if not shutil.which("codex"):
            return False, "needs the codex CLI: npm i -g @openai/codex"
        st = subprocess.run(["codex", "login", "status"], capture_output=True, text=True, stdin=subprocess.DEVNULL)
        if st.returncode or "Logged in" not in (st.stdout + st.stderr):
            return False, "needs credential: Roman runs `codex login` (ChatGPT plan) on this Mac"
        if "API key" in (st.stdout + st.stderr):
            return False, "codex is signed in with an API key (paid). $0 rule: sign in with the ChatGPT plan instead"
        if not self.model:
            return False, ("needs CODEX_MODEL: the --json stream doesn't report the model, so pin it "
                           "(ids in ~/.codex/models_cache.json, e.g. gpt-5.5 or gpt-5.6-sol)")
        return True, "%s, model pinned %s" % (self.version, self.model)

    def cmd(self, prompt, mcp=None, schema=SCHEMA, search=False):
        c = ["codex", "exec", "--json", "--ephemeral", "--skip-git-repo-check", "--sandbox", "read-only"]
        if schema:
            c += ["--output-schema", schema]
        # Added to §3.6's line, for the no-web-search rule: the user config.toml loads a browser plugin and MCP
        # servers, and codex's own web_search tool is on ("cached") by default.
        c += ["--ignore-user-config", "-c", 'web_search="live"' if search else 'web_search="disabled"',
              "--disable", "apps", "--disable", "shell_tool", "-m", self.model]  # search: the SEARCH-ON lane only
        # --disable shell_tool (28 Oct): no shell at all, matching claude's --tools "". 6 street answers had run curl.
        # --disable apps: the built-in codex_apps connector exposes search_service.web_run, a web search that arrives
        # as an mcp_tool_call (seen 28 Oct in 8 of 128 census answers and in the first meter ask)
        if mcp:  # meter "with" arm: one MCP server, only the qloo_places tool
            c += ["-c", "mcp_servers.unsaid.command=%s" % json.dumps(mcp["command"]),
                  "-c", "mcp_servers.unsaid.args=%s" % json.dumps(mcp["args"]),
                  "-c", "mcp_servers.unsaid.enabled_tools=%s" % json.dumps([mcp.get("tool", "qloo_places")]),
                  "-c", "mcp_servers.unsaid.env_vars=%s" % json.dumps(sorted(mcp.get("env_vars", [])))]
        return c + [prompt]

    def ask(self, prompt, mcp=None, schema=SCHEMA, search=False, **_):
        t0, s = now(), time.time()
        res = {"tool": "codex-cli " + self.version.split()[-1] if self.version else "codex-cli",
               "search": "off", "model": self.model or None, "model_source": "pinned (-m)"}
        with tempfile.TemporaryDirectory(prefix="unsaid-codex-") as cwd:
            env = dict(os.environ)
            try:
                p = subprocess.run(self.cmd(prompt, mcp, schema, search), capture_output=True, text=True, cwd=cwd,
                                   timeout=TIMEOUT, stdin=subprocess.DEVNULL, env=env)
            except subprocess.TimeoutExpired:
                return _finish(dict(res, status="failed", error="timeout %ds" % TIMEOUT), "", t0, s)
        text, err, kinds, calls, results, called = "", None, [], 0, [], []
        for line in p.stdout.splitlines():
            try:
                e = json.loads(line)
            except Exception:
                continue
            m = _find_key(e, "model")
            if isinstance(m, str) and m:
                res["model"], res["model_source"] = m, "event stream"
            t = e.get("type")
            if t in ("turn.failed", "error"):
                err = json.dumps(e.get("error") or e.get("message") or e)[:300]
            if t == "item.completed":
                it = e.get("item") or {}
                k = it.get("type") or it.get("item_type")
                kinds.append(k)
                if k == "agent_message":
                    text = it.get("text") or text
                elif k == "web_search":
                    res["search"] = "on"
                    res["search_calls"] = res.get("search_calls", 0) + 1
                elif k == "command_execution":  # read-only sandbox, no network; kept so that stays checkable
                    cmd = str(it.get("command") or "")[:300]
                    res.setdefault("commands", []).append(cmd)
                    if re.search(r"\b(curl|wget|http|nc|ssh|ping|dig|nslookup|python[0-9.]*\s+-c.*(urllib|requests|socket))", cmd):
                        res["search"] = "on"
                        res.setdefault("foreign_tools", []).append("command_execution: " + cmd[:80])
                elif k == "mcp_tool_call":
                    calls += 1
                    called.append("%s/%s" % (it.get("server"), it.get("tool")))
                    if it.get("server") != "unsaid":  # any tool but ours is foreign; a search one means search on
                        res.setdefault("foreign_tools", []).append(called[-1])
                        if re.search(r"search|web|browse|fetch", called[-1], re.I):
                            res["search"] = "on"
                    results.append(it.get("result"))
                    if it.get("error") or it.get("status") == "failed":
                        res.setdefault("tool_errors", []).append(str(it.get("error") or it.get("status"))[:200])
        res["items"] = sorted(set(x for x in kinds if x))
        if mcp:
            res["tool_calls"], res["tools_called"], res["qloo"] = calls, sorted(set(called)), qloo_counts(results)
            res["tool_results"] = [trim_result(x) for x in results]
        if err or (p.returncode and not text):
            return _finish(dict(res, status="failed", error=err or ("exit %s: %s" % (p.returncode, p.stderr[-300:]))), "", t0, s)
        return _finish(res, text, t0, s)


def trim_result(p):
    """A tool result, kept small: status, flags, picks (name + Qloo id), host key/cache, engine version, wall snapshot,
    Qloo call counts. Adherence is scored from this later, with no extra call."""
    if isinstance(p, str):
        try:
            p = json.loads(p)
        except Exception:
            return {"text": p[:300]}
    if isinstance(p, list):  # claude: [{"type": "text", "text": "<json>"}]; codex: {"content": [...], "structured_content": {...}}
        txt = "".join(x.get("text", "") for x in p if isinstance(x, dict))
        return trim_result(txt)
    if isinstance(p, dict) and ("structured_content" in p or "content" in p) and "picks" not in p:
        sc = p.get("structured_content") or p.get("structuredContent")
        return trim_result(sc if sc else (p.get("content") or []))
    if not isinstance(p, dict):
        return {"text": str(p)[:300]}
    diag = p.get("diag") or {}
    return {"status": p.get("status"), "mode": p.get("mode"), "flags": p.get("flags"),
            "picks": [{"name": x.get("name"), "qloo_id": x.get("qloo_id") or x.get("id")} for x in p.get("picks") or []],
            "host": {k: (p.get("host") or {}).get(k) for k in ("key", "cached", "stored_at", "mode")},
            "engine_v": diag.get("engine_v") or p.get("engine_v"),
            "wall_snapshot": {k: (p.get("wall") or {}).get(k) for k in ("distinct_names", "answers", "source")}
            if isinstance(p.get("wall"), dict) else diag.get("wall_snapshot"),
            "qloo_calls": p.get("qloo_calls")}


def qloo_counts(payloads):
    """Sum qloo_places' own qloo_calls {total, from_cache} over tool-result payloads (strings or objects)."""
    tot = cached = n = 0
    for p in payloads:
        if isinstance(p, str):
            try:
                p = json.loads(p)
            except Exception:
                continue
        q = _find_obj(p, "qloo_calls")
        host = _find_obj(p, "host")
        if isinstance(q, dict) and isinstance(host, dict) and host.get("cached"):
            n += 1  # a host cache hit echoes the original run's counts; it made no new Qloo call
            continue
        if isinstance(q, dict):
            n += 1
            tot += int(q.get("total") or 0)
            if q.get("network") is not None:  # the hosted API reports its own network count
                cached += int(q.get("total") or 0) - int(q.get("network") or 0)
            else:
                cached += int(q.get("from_cache") or 0)
    return {"results": n, "total": tot, "from_cache": cached, "network": tot - cached}


def _find_obj(o, key, depth=0):
    if depth > 6:
        return None
    if isinstance(o, dict):
        if isinstance(o.get(key), dict):
            return o[key]
        for v in o.values():
            r = _find_obj(v, key, depth + 1)
            if r is not None:
                return r
    elif isinstance(o, list):
        for v in o:
            r = _find_obj(v, key, depth + 1)
            if r is not None:
                return r
    elif isinstance(o, str) and key in o and depth < 6:
        try:
            return _find_obj(json.loads(o), key, depth + 1)
        except Exception:
            return None
    return None


def _find_key(o, key, depth=0):
    if depth > 4:
        return None
    if isinstance(o, dict):
        if key in o and isinstance(o[key], str):
            return o[key]
        for v in o.values():
            r = _find_key(v, key, depth + 1)
            if r:
                return r
    elif isinstance(o, list):
        for v in o:
            r = _find_key(v, key, depth + 1)
            if r:
                return r
    return None


class GeminiLane(Lane):
    """Free-tier REST. Key from GEMINI_API_KEY (AI Studio project with no billing), model pinned by GEMINI_MODEL,
    paced at GEMINI_RPM, and capped per Pacific day at GEMINI_HARNESS_FRACTION (default 0.8) of GEMINI_RPD, the
    console numbers. No tools unless the meter passes its one function: no grounding, ever."""
    name, provider, assistant, workers = "gemini", "google", "Gemini", 1
    URL = "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent"
    LEDGER = os.path.join(RUNS, ".gemini_ledger.json")
    BACKOFF = (90,)  # one retry per ask: after Retry-After / RetryInfo when given, else 90 s (503s are charged)
    TIMEOUT = 420    # 28 Oct: answers took up to 282 s and 7 of 12 attempts died at 180 s; a timeout is charged too

    def __init__(self, model=None):
        self.key = os.environ.get("GEMINI_API_KEY", "").strip()
        self.model = (model or os.environ.get("GEMINI_MODEL", "")).strip()
        self.rpm = float(os.environ.get("GEMINI_RPM") or 0)
        self.rpd = int(os.environ.get("GEMINI_RPD") or 0)
        self.cap = int(self.rpd * float(os.environ.get("GEMINI_HARNESS_FRACTION") or 0.8))
        self._lock, self._next = threading.Lock(), 0.0

    def check(self):
        miss = [k for k, v in (("GEMINI_API_KEY", self.key), ("GEMINI_MODEL", self.model),
                               ("GEMINI_RPM", self.rpm), ("GEMINI_RPD", self.rpd)) if not v]
        if miss:
            return False, ("needs credential: %s (AI Studio key in a project with NO billing account; "
                           "model id and RPM/RPD as the console shows them)" % ", ".join(miss))
        left = self.cap - self._used()
        if left <= 0:
            return False, "Gemini harness cap reached for today (Pacific): %d of %d RPD" % (self._used(), self.rpd)
        return True, "%s, %g RPM, %d of today's harness cap left" % (self.model, self.rpm, left)

    def _day(self):
        try:
            from zoneinfo import ZoneInfo
            return datetime.datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()
        except Exception:  # PT is UTC-7/-8; erring early is fine for a cap
            return (datetime.datetime.utcnow() - datetime.timedelta(hours=8)).date().isoformat()

    PRIMARY = "gemini-3.8-flash"  # the ledger's flat {day: n} entries (27-28 Oct) belong to it

    def _ledger(self):
        """{model: {pacific day: requests}}: the free-tier limits are per model per project."""
        try:
            d = json.load(open(self.LEDGER))
        except Exception:
            d = {}
        flat = {k: v for k, v in d.items() if isinstance(v, int)}
        if flat:
            d = {k: v for k, v in d.items() if isinstance(v, dict)}
            d.setdefault(self.PRIMARY, {}).update(flat)
        return d

    def _used(self):
        return self._ledger().get(self.model, {}).get(self._day(), 0)

    def _count(self, n=1, at_least=False):
        os.makedirs(RUNS, exist_ok=True)
        d = self._ledger()
        m = d.setdefault(self.model, {})
        m[self._day()] = max(m.get(self._day(), 0), n) if at_least else m.get(self._day(), 0) + n
        json.dump(d, open(self.LEDGER, "w"))

    def remaining(self):
        return max(0, self.cap - self._used())

    def seed_used(self, n):
        """Record requests made today outside the harness (console count), so the cap covers them too."""
        self._count(int(n), at_least=True)

    def pace(self):
        with self._lock:
            wait = self._next - time.time()
            if wait > 0:
                time.sleep(wait)
            self._next = time.time() + 60.0 / max(self.rpm, 0.1) * 1.1

    def _post(self, body):
        req = urllib.request.Request(self.URL % self.model, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", "x-goog-api-key": self.key})
        with urllib.request.urlopen(req, timeout=self.TIMEOUT) as r:
            return json.loads(r.read())

    def ask(self, prompt, json_mode=True, functions=None, call_tool=None, **_):
        """json_mode: responseMimeType JSON + a places schema (walls, census). functions/call_tool: the meter's
        qloo_places loop (up to 4 tool rounds)."""
        t0, s = now(), time.time()
        res = {"tool": "gemini-api v1beta", "search": "off", "model": self.model, "model_source": "modelVersion"}
        if self._used() >= self.cap:
            return _finish(dict(res, status="failed", error="harness cap reached", fatal=True), "", t0, s)
        body = {"systemInstruction": {"parts": [{"text": SYS_GEMINI}]},
                "contents": [{"role": "user", "parts": [{"text": prompt}]}]}
        if json_mode:
            body["generationConfig"] = {"responseMimeType": "application/json", "responseSchema": {
                "type": "ARRAY", "items": {"type": "OBJECT", "properties": {
                    "name": {"type": "STRING"}, "neighbourhood": {"type": "STRING"}}, "required": ["name", "neighbourhood"]}}}
        if functions:
            body["tools"] = [{"functionDeclarations": functions}]
        calls, busy = 0, 0
        for _round in range(5 + len(self.BACKOFF)):
            if self._used() >= self.cap:
                return _finish(dict(res, status="failed", error="harness cap reached", fatal=True), "", t0, s)
            self.pace()
            self._count()  # every request counts, 503s included: the quota is shared with the live lane, so err low
            try:
                d = self._post(body)
            except urllib.error.HTTPError as e:
                full = e.read().decode(errors="replace")
                msg = full[:300].replace(self.key, "<key>") if self.key else full[:300]
                wait = _retry_after(e, full)
                per_day = e.code == 429 and re.search(r"PerDay|per day|RPD", full, re.I)
                # "high demand" 503 / 500, or a per-minute 429: wait as told, retry once; a per-day 429 ends the day
                if (e.code in (500, 503) or (e.code == 429 and not per_day)) and busy < len(self.BACKOFF):
                    time.sleep(min(max(wait or self.BACKOFF[busy], 13), 300))
                    busy += 1
                    continue
                return _finish(dict(res, status="failed", error="HTTP %s %s" % (e.code, msg),
                                    fatal=e.code in (401, 403) or bool(per_day), retry_after=wait,
                                    transient=e.code in (500, 503) or (e.code == 429 and not per_day), retries_503=busy), "", t0, s)
            except Exception as e:
                return _finish(dict(res, status="failed", error=str(e)[:200].replace(self.key, "<key>"), transient=True,
                                    retries_503=busy), "", t0, s)
            res["retries_503"] = busy
            res["model"] = d.get("modelVersion") or res["model"]
            c = (d.get("candidates") or [{}])[0]
            if c.get("groundingMetadata"):
                res["search"] = "on"
            parts = (c.get("content") or {}).get("parts") or []
            fcs = [p["functionCall"] for p in parts if p.get("functionCall")]
            if fcs and call_tool:
                body["contents"].append(c["content"])
                body["contents"].append({"role": "user", "parts": [
                    {"functionResponse": {"name": fc["name"], "response": call_tool(fc["name"], fc.get("args") or {})}} for fc in fcs]})
                calls += len(fcs)
                continue
            text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
            res["finish"] = c.get("finishReason") or (d.get("promptFeedback") or {}).get("blockReason")
            if functions:
                res["tool_calls"] = calls
            return _finish(res, text, t0, s)
        return _finish(dict(res, status="failed", error="tool loop did not end in 5 rounds"), "", t0, s)


def _retry_after(err, body):
    """Seconds to wait, from a Retry-After header or Google's RetryInfo ("retryDelay": "31s")."""
    try:
        h = err.headers.get("Retry-After") if err.headers else None
        if h and h.strip().isdigit():
            return int(h.strip())
    except Exception:
        pass
    m = re.search(r'"retryDelay"\s*:\s*"(\d+)(?:\.\d+)?s"', body or "")
    return int(m.group(1)) if m else None


LANES = {"claude": ClaudeLane, "codex": CodexLane, "gemini": GeminiLane}


# ---------- store ----------
_wlock = threading.Lock()


def load(path):
    """Last live record per id. Lines marked superseded_by or quarantined are kept in the file for audit and skipped
    here, so every builder (walls_cli build / --census-only, census_stats via its own loader) ignores them."""
    out = {}
    if os.path.exists(path):
        for l in open(path):
            if l.strip():
                r = json.loads(l)
                if r.get("superseded_by") or r.get("quarantined"):
                    continue
                out[r["id"]] = r
    return out


def is_done(r):
    """ok and unparsed answers are kept; failed ones are asked again. Census rows from before the status field count
    when they carry a parsed list, as the original run_census.py did."""
    return r.get("status") in ("ok", "unparsed") or ("status" not in r and bool(r.get("places")))


def done_ids(path):
    done = set()
    if os.path.exists(path):
        for l in open(path):
            if l.strip():
                r = json.loads(l)
                if is_done(r):
                    done.add(r["id"])
    return done


def append(path, rec):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with _wlock, open(path, "a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        f.flush()


def run(lane, asks, path, limit=None, go=False, opts=None, on_record=None, stop_if=None, force=False):
    """Ask every not-yet-stored ask on one lane with lane.workers threads. Stops the lane after 3 failures in a row
    (a plan limit or a dead key), or at once on a fatal error (Gemini 401/403/429, cap). Resume = run it again."""
    done = set() if force else done_ids(path)  # force: re-ask these ids; the new record supersedes (last one wins)
    pending = [a for a in asks if a["id"] not in done]
    todo = pending[:limit] if limit is not None else pending
    print("[%s] %d asks, %d already stored, %d to ask%s" % (lane.name, len(asks), len(asks) - len(pending), len(todo),
                                                         "" if go else " (dry run: add --go to ask)"), flush=True)
    if not go or not todo:
        return {"asked": 0, "failed": 0}
    q, lk, stop, st = deque(todo), threading.Lock(), threading.Event(), {"asked": 0, "failed": 0, "streak": 0}

    def worker():
        while not stop.is_set():
            with lk:
                if not q:
                    return
                why = disk_low() or (stop_if and stop_if())
                if why:
                    print("[%s] stopping the lane: %s" % (lane.name, why), flush=True)
                    stop.set()
                    return
                a = q.popleft()
            ask_opts = dict(opts or {}, **(a.get("opts") or {}))
            try:
                r = lane.ask(a["prompt"], **ask_opts)
            except Exception as e:  # e.g. disk full (28 Oct): record the failure, never lose the ask
                r = {"status": "failed", "error": "%s: %s" % (type(e).__name__, str(e)[:200]), "transient": True,
                     "raw": "", "places": None, "asked_at": now(), "answered_at": now(), "secs": 0, "model": None}
            if a.get("verbatim") and r.get("status") == "unparsed":
                r["status"] = "ok"  # a verbatim ask expects prose: the raw text is the answer (k5 reads it)
            rec = {k: v for k, v in a.items() if k != "opts"}
            rec.update(r, lane="dated", provider=lane.provider, assistant=lane.assistant, runner=lane.name)
            fatal = rec.pop("fatal", False)
            append(path, rec)
            if on_record:
                on_record(rec)
            with lk:
                st["asked"] += 1
                if rec["status"] == "failed" and rec.get("transient"):
                    st["failed"] += 1  # 503 after backoff: recorded, retried next run, not a strike toward the stop
                elif rec["status"] == "failed":
                    st["failed"] += 1
                    st["streak"] += 1
                else:
                    st["streak"] = 0
                if fatal or st["streak"] >= 3:
                    if not stop.is_set():
                        print("[%s] stopping the lane: %s" % (lane.name, rec.get("error")), flush=True)
                    stop.set()
            print("[%s] %s %s %ss %s names %s" % (lane.name, rec["id"], rec["status"], rec["secs"],
                                                  len(rec["places"] or []), rec.get("model")), flush=True)

    ts = [threading.Thread(target=worker, daemon=True) for _ in range(lane.workers)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    print("[%s] done: %d asked, %d failed%s" % (lane.name, st["asked"], st["failed"], ", %d left" % len(q) if q else ""), flush=True)
    return st


def lanes_from(arg):
    names = list(LANES) if arg == "all" else [x.strip() for x in arg.split(",") if x.strip()]
    out = []
    for n in names:
        if n not in LANES:
            sys.exit("unknown lane %s (claude | codex | gemini | all)" % n)
        lane = LANES[n]()
        ok, msg = lane.check()
        print("[%s] %s" % (n, msg if ok else "SKIPPED, " + msg), flush=True)
        if ok:
            out.append(lane)
    return out


def run_lanes(lanes, asks_for, path_for, limit=None, go=False, opts=None):
    """Run several lanes at once, one thread per lane (each with its own workers)."""
    ts = [threading.Thread(target=run, args=(l, asks_for(l), path_for(l), limit, go, opts)) for l in lanes]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
