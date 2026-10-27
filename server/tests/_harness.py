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
import limits as L  # noqa: E402

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
