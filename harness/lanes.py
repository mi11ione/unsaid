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

    def cmd(self, prompt, meter=False, mcp_config=None):
        """Walls, census, fresh asks: §3.6's line exactly. Meter (both arms, so they differ only in the tool):
        --safe-mode is swapped for --setting-sources local --disable-slash-commands, because --safe-mode drops every
        --mcp-config server (checked 27 Oct on 2.1.311: init showed mcp_servers [] and tools []). stream-json shows
        each tool_use. The "with" arm adds the one server and allows only qloo_places; unsaid_places is disallowed."""
        if not meter:
            return ["claude", "-p", prompt, "--output-format", "json", "--model", "sonnet", "--tools", "",
                    "--safe-mode", "--strict-mcp-config", "--no-session-persistence", "--system-prompt", SYS_CLAUDE]
        c = ["claude", "-p", prompt, "--output-format", "stream-json", "--verbose", "--model", "sonnet", "--tools", "",
             "--setting-sources", "local", "--disable-slash-commands", "--strict-mcp-config",
             "--no-session-persistence", "--system-prompt", SYS_CLAUDE]
        if mcp_config:
            c += ["--mcp-config", mcp_config, "--allowedTools", "mcp__unsaid__qloo_places",
                  "--disallowedTools", "mcp__unsaid__unsaid_places"]
        return c

    def ask(self, prompt, meter=False, mcp_config=None, **_):
        t0, s = now(), time.time()
        res = {"tool": "claude-code " + self.version.split()[0] if self.version else "claude-code",
               "search": "off", "model": None, "model_source": "modelUsage"}
        with tempfile.TemporaryDirectory(prefix="unsaid-claude-") as cwd:
            try:
                p = subprocess.run(self.cmd(prompt, meter, mcp_config), capture_output=True, text=True, cwd=cwd,
                                   timeout=TIMEOUT, stdin=subprocess.DEVNULL)
            except subprocess.TimeoutExpired:
                return _finish(dict(res, status="failed", error="timeout %ds" % TIMEOUT), "", t0, s)
        d, calls = None, []
        if meter:  # stream-json: count tool_use blocks, take the final result event
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
                        if "search" in str(b.get("name")).lower():
                            res["search"] = "on"
                if e.get("type") == "result":
                    d = e
            res["tool_calls"], res["tools_called"] = len(calls), sorted(set(calls))
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

    def cmd(self, prompt, mcp=None, schema=SCHEMA):
        c = ["codex", "exec", "--json", "--ephemeral", "--skip-git-repo-check", "--sandbox", "read-only"]
        if schema:
            c += ["--output-schema", schema]
        # Added to §3.6's line, for the no-web-search rule: the user config.toml loads a browser plugin and MCP
        # servers, and codex's own web_search tool is on ("cached") by default.
        c += ["--ignore-user-config", "-c", 'web_search="disabled"', "-m", self.model]
        if mcp:  # meter "with" arm: one MCP server, only the qloo_places tool
            c += ["-c", "mcp_servers.unsaid.command=%s" % json.dumps(mcp["command"]),
                  "-c", "mcp_servers.unsaid.args=%s" % json.dumps(mcp["args"]),
                  "-c", "mcp_servers.unsaid.enabled_tools=[\"qloo_places\"]",
                  "-c", "mcp_servers.unsaid.env_vars=%s" % json.dumps(sorted(mcp.get("env_vars", [])))]
        return c + [prompt]

    def ask(self, prompt, mcp=None, schema=SCHEMA, **_):
        t0, s = now(), time.time()
        res = {"tool": "codex-cli " + self.version.split()[-1] if self.version else "codex-cli",
               "search": "off", "model": self.model or None, "model_source": "pinned (-m)"}
        with tempfile.TemporaryDirectory(prefix="unsaid-codex-") as cwd:
            env = dict(os.environ)
            try:
                p = subprocess.run(self.cmd(prompt, mcp, schema), capture_output=True, text=True, cwd=cwd,
                                   timeout=TIMEOUT, stdin=subprocess.DEVNULL, env=env)
            except subprocess.TimeoutExpired:
                return _finish(dict(res, status="failed", error="timeout %ds" % TIMEOUT), "", t0, s)
        text, err, kinds, calls = "", None, [], 0
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
                elif k == "mcp_tool_call":
                    calls += 1
        res["items"] = sorted(set(x for x in kinds if x))
        if mcp:
            res["tool_calls"] = calls
        if err or (p.returncode and not text):
            return _finish(dict(res, status="failed", error=err or ("exit %s: %s" % (p.returncode, p.stderr[-300:]))), "", t0, s)
        return _finish(res, text, t0, s)


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
    BACKOFF = (30, 90, 240)  # seconds between 503 retries

    def __init__(self):
        self.key = os.environ.get("GEMINI_API_KEY", "").strip()
        self.model = os.environ.get("GEMINI_MODEL", "").strip()
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

    def _used(self):
        try:
            return json.load(open(self.LEDGER)).get(self._day(), 0)
        except Exception:
            return 0

    def _count(self):
        os.makedirs(RUNS, exist_ok=True)
        try:
            d = json.load(open(self.LEDGER))
        except Exception:
            d = {}
        d[self._day()] = d.get(self._day(), 0) + 1
        json.dump(d, open(self.LEDGER, "w"))

    def remaining(self):
        return max(0, self.cap - self._used())

    def seed_used(self, n):
        """Record requests made today outside the harness (console count), so the cap covers them too."""
        os.makedirs(RUNS, exist_ok=True)
        try:
            d = json.load(open(self.LEDGER))
        except Exception:
            d = {}
        d[self._day()] = max(d.get(self._day(), 0), int(n))
        json.dump(d, open(self.LEDGER, "w"))

    def pace(self):
        with self._lock:
            wait = self._next - time.time()
            if wait > 0:
                time.sleep(wait)
            self._next = time.time() + 60.0 / max(self.rpm, 0.1) * 1.1

    def _post(self, body):
        req = urllib.request.Request(self.URL % self.model, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", "x-goog-api-key": self.key})
        with urllib.request.urlopen(req, timeout=300) as r:  # 3.8 Flash took 82 s for one census ask on 27 Oct
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
                msg = e.read().decode(errors="replace")[:300].replace(self.key, "<key>") if self.key else ""
                if e.code in (500, 503) and busy < len(self.BACKOFF):  # "high demand": back off, not a failure
                    time.sleep(self.BACKOFF[busy])
                    busy += 1
                    continue
                return _finish(dict(res, status="failed", error="HTTP %s %s" % (e.code, msg), fatal=e.code in (401, 403, 429),
                                    transient=e.code in (500, 503), retries_503=busy), "", t0, s)
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


LANES = {"claude": ClaudeLane, "codex": CodexLane, "gemini": GeminiLane}


# ---------- store ----------
_wlock = threading.Lock()


def load(path):
    """Last record per id."""
    out = {}
    if os.path.exists(path):
        for l in open(path):
            if l.strip():
                r = json.loads(l)
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


def run(lane, asks, path, limit=None, go=False, opts=None):
    """Ask every not-yet-stored ask on one lane with lane.workers threads. Stops the lane after 3 failures in a row
    (a plan limit or a dead key), or at once on a fatal error (Gemini 401/403/429, cap). Resume = run it again."""
    done = done_ids(path)
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
                a = q.popleft()
            ask_opts = dict(opts or {}, **(a.get("opts") or {}))
            r = lane.ask(a["prompt"], **ask_opts)
            if a.get("verbatim") and r.get("status") == "unparsed":
                r["status"] = "ok"  # a verbatim ask expects prose: the raw text is the answer (k5 reads it)
            rec = {k: v for k, v in a.items() if k != "opts"}
            rec.update(r, lane="dated", provider=lane.provider, assistant=lane.assistant, runner=lane.name)
            fatal = rec.pop("fatal", False)
            append(path, rec)
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
