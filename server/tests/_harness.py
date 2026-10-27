"""Shared setup for the server tests: a throwaway cache dir and the app imported in-process (fake mode)."""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.dirname(HERE)
TMP = tempfile.mkdtemp(prefix="unsaid-test-")
os.environ["UNSAID_CACHE_DIR"] = TMP
os.environ["UNSAID_MODE"] = "fake"
for k in ("UNSAID_TOKEN", "UNSAID_PROXY_SECRET", "GEMINI_API_KEY", "QLOO_API_KEY"):
    os.environ.pop(k, None)
if SERVER not in sys.path:
    sys.path.insert(0, SERVER)

import app  # noqa: E402
import gemini_live as G  # noqa: E402
import limits as L  # noqa: E402
from unsaid import walls as W  # noqa: E402  (the engine's own module; app put it on the path)


def _walls_fixture():
    """A walls JSON in the harness contract, built from the engine's day-1 fixtures: STL's generic answers."""
    import json
    gen = W.wall_for("stl", "__generic__")
    p = os.path.join(TMP, "walls", "stl.json")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        json.dump({"walls": [{"city": "stl", "set": "city", "answers": gen["answers"]}]}, f)
    return os.path.dirname(p)


WALLS_DIR = _walls_fixture()
os.environ["UNSAID_WALLS"] = WALLS_DIR


def make_lane(transport, **env):
    """A GeminiLane with a fake transport (never the network). env overrides GEMINI_* for its construction."""
    import time
    base = {"GEMINI_API_KEY": "k", "GEMINI_MODEL": "gemini-test-flash", "GEMINI_RPD": "1000"}
    base.update(env)
    old = {k: os.environ.get(k) for k in base}
    for k, v in base.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    try:
        return G.GeminiLane(os.path.join(TMP, "g%d" % time.monotonic_ns()), transport=transport)
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def names_transport(names):
    import json

    def t(prompt):
        return 200, {"candidates": [{"content": {"parts": [{"text": json.dumps(names)}]}}]}
    return t

CEDRIC = [{"text": "Frankie Beverly & Maze"}, {"text": "The Original Kings of Comedy", "hint": "movie"},
          {"text": "rib tips", "hint": "tag"}]
JASON = [{"text": "Frank Sinatra", "hint": "artist"}, {"text": "Rounders", "hint": "movie"},
         {"text": "Carbone", "hint": "place"}]
AL_GREEN = [{"text": "Al Green", "hint": "artist"}, {"text": "Barbershop", "hint": "movie"},
            {"text": "rib tips", "hint": "tag"}]
SOUL = [{"text": "The Original Kings of Comedy", "hint": "movie"}, {"text": "Al Green", "hint": "artist"},
        {"text": "soul food", "hint": "tag"}]


def run(loves, city="st-louis", ip="198.51.100.7", country="US"):
    """One /api/unsaid request in-process. Returns (events, result)."""
    events = []
    app.stream_unsaid(city, [dict(x) for x in loves], ip, country, events.append)
    assert events and events[-1]["type"] == "done", events[-1:]
    return events, events[-1]["result"]


def card_ids(events):
    """Every card id that reached the visitor: card events, burn events and the done result."""
    ids = set()
    for e in events:
        if e["type"] == "card":
            ids.add(e["id"])
        if e["type"] == "done":
            r = e["result"]
            ids |= {c["id"] for c in (r.get("picks") or []) + (r.get("reserves") or [])}
    return ids


def reset_limits():
    app.FRESH_IPS = L.IpLimiter(per_hour=3)
    app.ADMIT = L.Admission(max_active=2)


def clear_results():
    import shutil
    app.RESULTS.mem.clear()
    shutil.rmtree(app.RESULTS.root, ignore_errors=True)
