"""Per-request stage timing for diag.timing, so we can see where the host spends a run, and whether it is CPU or waiting.

Top-level keys (wall seconds), unchanged: pool, rescore, strike, ids, cap, gemini, total, resolve, queue.
Qloo stages are wall-clock spans (first call start -> last call end) of the calls whose step label starts with:
  pool C4 · rescore C6' · ids C7 · cap CAP · resolve C1/C2
Calls run in parallel, so a span is not the sum of call times. strike = from the `pool` event to the last `strike`
event (the local matcher, plus whatever Qloo work overlaps it). gemini = the live taste ask. queue = admission wait.

CPU (seconds of CPU, time.process_time / time.thread_time):
  cpu_calls  {stage: CPU spent inside that stage's Qloo calls, summed over threads (TLS, read, gunzip, json)}
  cpu_window {stage: process CPU used while the stage ran (all threads), i.e. how busy the box was}
  cpu_total  process CPU over the whole request
  cgroup     {quota_cpus, usage_s, throttled_s, nr_throttled}: the container's own accounting over the request
             (Linux cgroup v2 or v1; absent elsewhere). throttled_s > 0 means the CPU quota held the run back.
  http       the run's Qloo transport counters: calls, new_conns, reused, wire_bytes, body_bytes
A stage whose cpu_window is close to quota_cpus x its wall time is CPU-bound; one far below it is waiting on the network.
"""
import os
import platform
import threading
import time

PREFIXES = (("C4", "pool"), ("C6", "rescore"), ("C7", "ids"), ("CAP", "cap"), ("C1", "resolve"), ("C2", "resolve"))
KEYS = ("pool", "rescore", "strike", "ids", "cap", "gemini", "total", "resolve", "queue")
PY = platform.python_version()


def stage_of(label):
    label = str(label or "")
    for p, s in PREFIXES:
        if label.startswith(p):
            return s
    return "other"


def _read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


def cgroup():
    """{"usage_s", "throttled_s", "nr_throttled", "quota_cpus"} from cgroup v2, else v1, else None."""
    st = _read("/sys/fs/cgroup/cpu.stat")
    if st and "usage_usec" in st:
        kv = dict(line.split() for line in st.splitlines() if len(line.split()) == 2)
        q = (_read("/sys/fs/cgroup/cpu.max") or "max 100000").split()
        quota = None if q[0] == "max" else int(q[0]) / float(q[1])
        return {"usage_s": int(kv.get("usage_usec", 0)) / 1e6, "throttled_s": int(kv.get("throttled_usec", 0)) / 1e6,
                "nr_throttled": int(kv.get("nr_throttled", 0)), "quota_cpus": quota}
    st = _read("/sys/fs/cgroup/cpu/cpu.stat") or _read("/sys/fs/cgroup/cpu,cpuacct/cpu.stat")
    if st:
        kv = dict(line.split() for line in st.splitlines() if len(line.split()) == 2)
        use = _read("/sys/fs/cgroup/cpuacct/cpuacct.usage") or _read("/sys/fs/cgroup/cpu,cpuacct/cpuacct.usage")
        qu, pe = _read("/sys/fs/cgroup/cpu/cpu.cfs_quota_us"), _read("/sys/fs/cgroup/cpu/cpu.cfs_period_us")
        quota = (int(qu) / float(pe)) if qu and pe and int(qu) > 0 else None
        return {"usage_s": int(use or 0) / 1e9, "throttled_s": int(kv.get("throttled_time", 0)) / 1e9,
                "nr_throttled": int(kv.get("nr_throttled", 0)), "quota_cpus": quota}
    return None


class Timing:
    def __init__(self):
        self.t0 = time.monotonic()
        self.c0 = time.process_time()
        self.cg0 = cgroup()
        self.spans, self.windows, self.cpu = {}, {}, {}
        self.first, self.last = {}, {}
        self.q = None
        self.lock = threading.Lock()

    def now(self):
        return time.monotonic()

    def span(self, stage, a, b, cpu=None, pa=None, pb=None):
        with self.lock:
            lo, hi = self.spans.get(stage, (a, b))
            self.spans[stage] = (min(lo, a), max(hi, b))
            if pa is not None:
                plo, phi = self.windows.get(stage, (pa, pb))
                self.windows[stage] = (min(plo, pa), max(phi, pb))
            if cpu is not None:
                self.cpu[stage] = self.cpu.get(stage, 0.0) + cpu

    def event(self, kind):
        t, p = time.monotonic(), time.process_time()
        with self.lock:
            self.first.setdefault(kind, (t, p))
            self.last[kind] = (t, p)

    def instrument(self, q):
        """Times every Qloo call of this run's client by its step label (shadows the bound method)."""
        orig = q.get
        self.q = q

        def timed(path, params, label="", *a, **kw):
            s, ts, ps = time.monotonic(), time.thread_time(), time.process_time()
            try:
                return orig(path, params, label, *a, **kw)
            finally:
                self.span(stage_of(label), s, time.monotonic(), time.thread_time() - ts, ps, time.process_time())
        q.get = timed
        return q

    def _http(self):
        t = getattr(getattr(self.q, "transport", None), "inner", None) or getattr(self.q, "transport", None)
        st = getattr(t, "stats", None)
        return dict(st) if isinstance(st, dict) else None

    def result(self):
        with self.lock:
            out = {k: round(hi - lo, 3) for k, (lo, hi) in self.spans.items() if k in KEYS}
            win = {k: round(hi - lo, 3) for k, (lo, hi) in self.windows.items()}
            if "pool" in self.first and "strike" in self.last and self.last["strike"][0] >= self.first["pool"][0]:
                out["strike"] = round(self.last["strike"][0] - self.first["pool"][0], 3)
                win["strike"] = round(self.last["strike"][1] - self.first["pool"][1], 3)
            cpu = {k: round(v, 3) for k, v in self.cpu.items()}
        out["total"] = round(time.monotonic() - self.t0, 3)
        res = {k: out.get(k) for k in KEYS}
        res.update(cpu_calls=cpu, cpu_window=win, cpu_total=round(time.process_time() - self.c0, 3), python=PY,
                   http=self._http())
        cg1 = cgroup()
        if self.cg0 and cg1:
            res["cgroup"] = {"quota_cpus": cg1["quota_cpus"],
                             "usage_s": round(cg1["usage_s"] - self.cg0["usage_s"], 3),
                             "throttled_s": round(cg1["throttled_s"] - self.cg0["throttled_s"], 3),
                             "nr_throttled": cg1["nr_throttled"] - self.cg0["nr_throttled"]}
        return res
