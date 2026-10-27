"""Exact-key result cache (UNSAID.md §3.5). Memory plus ephemeral disk under server/.cache/ (gitignored).

key = sha256(engine_v, mode, locality, sorted love IDs, kind, wall-snapshot hash, lane)

`mode` (fake|live) is added to the §3.5 tuple so a fake result can never answer a live key.
`lane` (live|dated_only) is the Gemini lane state of the run, so a visitor gated to dated_only (EEA, UK, CH or an
unknown country) is never served a result that contains a lane=live Gemini answer.
Exact keys only: a lookup returns the record stored under that key or nothing. There is no nearest match,
no prefix match and no "any result for this city". Every stored record embeds its key, and a read whose
embedded key differs from the requested one is treated as a miss.
"""
import hashlib
import json
import os
import re
import threading
import time
from collections import OrderedDict

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.environ.get("UNSAID_CACHE_DIR") or os.path.join(HERE, ".cache")
KEY_RE = re.compile(r"^[0-9a-f]{64}$")
FRESH_S = int(os.environ.get("UNSAID_RESULT_FRESH_S", str(24 * 3600)))  # insights TTL; older = stale fallback only


LANES = ("live", "dated_only")


def result_key(engine_v, mode, locality, love_ids, kind, wall_hash, lane):
    if not locality or not love_ids or any(not i for i in love_ids):
        raise ValueError("a result key needs a locality and resolved love IDs")
    if lane not in LANES:
        raise ValueError("lane is live or dated_only")
    blob = json.dumps([str(engine_v), str(mode), str(locality), sorted(str(i) for i in love_ids), str(kind),
                       str(wall_hash), lane], separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def wall_hash(answers):
    """Content hash of a wall snapshot: any change to any stored answer gives a new key."""
    blob = json.dumps(answers, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class ResultCache:
    def __init__(self, root=None, max_mem=500):
        self.root = os.path.join(root or CACHE_DIR, "results")
        self.mem = OrderedDict()
        self.max_mem = max_mem
        self.lock = threading.Lock()

    def _path(self, key):
        return os.path.join(self.root, key[:2], key + ".json")

    def put(self, key, result):
        if not KEY_RE.match(key or ""):
            raise ValueError("bad key")
        result = dict(result, key=key)
        rec = {"key": key, "stored_at": time.time(), "result": result}
        with self.lock:
            self.mem[key] = rec
            self.mem.move_to_end(key)
            while len(self.mem) > self.max_mem:
                self.mem.popitem(last=False)
        p = self._path(key)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = "%s.%d.%d.tmp" % (p, os.getpid(), threading.get_ident())
        with open(tmp, "w") as f:
            json.dump(rec, f, ensure_ascii=False, default=str)
        os.replace(tmp, p)
        return rec

    def get(self, key):
        """The record for exactly this key, or None. Adds `fresh` (bool) and `age_s`."""
        if not KEY_RE.match(key or ""):
            return None
        with self.lock:
            rec = self.mem.get(key)
        if rec is None:
            try:
                with open(self._path(key)) as f:
                    rec = json.load(f)
            except (OSError, ValueError):
                return None
        if not isinstance(rec, dict) or rec.get("key") != key or (rec.get("result") or {}).get("key") != key:
            return None                                  # never another key's cards
        age = time.time() - float(rec.get("stored_at") or 0)
        out = dict(rec, age_s=int(age), fresh=age <= FRESH_S)
        with self.lock:
            self.mem[key] = rec
            self.mem.move_to_end(key)
        return out
