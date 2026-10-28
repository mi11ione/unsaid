"""The engine's entry point for the server (CONTRACT.md; UNSAID.md wins over it).

    run_unsaid(city, loves, *, walls_path=None, mode="fake"|"live", on_event=None, qloo=None, gemini=None,
               street_check=None, last_seen=None, set_id=None, use_cache=True, deadline_s=90) -> dict
    resolve_love(text, hint, *, mode, qloo=None) -> {"status": "ok"|"needs_input"|"miss", "chip", "alternatives"}
    resolve_city(text, *, mode, qloo=None) -> {"status": "ok"|"needs_input", "city", "alternatives"}

Events (on_event(dict), one per NDJSON line), in the order of the §3.4 timeline:
  status(running) -> wall_name x dated wall (static, < 1 s) -> calls ... -> pool -> strike x names ->
  [status(ranking) after 20 s] -> wall_name/strike for the live taste ask -> card x 7 (candidates, for-you order)
  -> burn x hits (the street check; each carries the card that rises) -> calls(final) -> done
Pluggable lanes (the server supplies them; the subscriptions never touch the server):
  gemini(prompt) or gemini.ask(prompt) -> answer dict {"names": [{"name", "neighbourhood"}], "raw", "provider",
      "model", "asked_at"}   (the one live taste ask)
  street_check(neighbourhood, city_name) -> [answer, ...]   (L2: dated answers for known neighbourhoods, <= 3 live)
  last_seen(entity) -> bool or (bool, {"checked_at", "how"})   default: unsaid.lastseen.check in live mode (hours,
      address, the venue's site HTTP 2xx/3xx in 5 s, cached 24 h); fake mode checks hours and address only
Use one Qloo client per run (pass none, or a fresh one): the deadline and the calls callback live on the client; the
token bucket is global and the cache is on disk, so nothing is lost by not sharing it.
In fake mode, results carry the "fake" flag, and the live lane and the street check are fake stand-ins unless the
caller passes its own (gemini=False / street_check=False switch them off).
"""
import math
import threading
import time

from unsaid import cities as C
from unsaid import engine as E
from unsaid import matcher as M
from unsaid import seeds as SD
from unsaid import walls as W
from unsaid.qloo import HARD_CAP_S, Qloo, QlooError, quota_state, redact

RANKING_AFTER_S = 20.0
LIVE_BUDGET_S = 15.0       # the server's budget for the live Gemini taste ask, counted from when it starts
NUM = {1: "one", 2: "two", 3: "three"}


# ---------------------------------------------------------------- resolve (C1, C2)
def _client(mode, qloo=None, use_cache=True):
    return qloo or Qloo(fake=(mode == "fake"), use_cache=use_cache)


def resolve_city(text, *, mode="fake", qloo=None):
    q = _client(mode, qloo)
    name, region = (text or "").strip(), None
    if "," in name:
        name, region = [x.strip() for x in name.split(",", 1)]
    key, _ = C.lookup(text)
    try:
        c = E.resolve_city(q, text if key else name, None if key else region)
    except QlooError as e:
        return {"status": "degraded", "city": None, "alternatives": [], "reason": "Qloo HTTP %s" % e.status}
    alts = [{"name": x.get("name"), "disamb": x.get("disamb"), "id": x.get("id")} for x in c.get("candidates") or []]
    if c.get("status") != "ok":
        return {"status": "needs_input", "city": None, "alternatives": alts, "reason": c.get("reason"),
                "text": text}
    return {"status": "ok", "city": C.public(c), "alternatives": alts, "_city": c}


TYPE_LABELS = {"movie": "film", "tv_show": "TV show", "videogame": "video game", "specialty_dish": "dish",
               "menu_highlight": "menu item", "genre": "kind of place", "category": "kind of place"}


def type_label(t):
    """What a chip says it matched, for people: 'urn:entity:tv_show' -> 'TV show', 'urn:entity:movie' -> 'film',
    'urn:tag:specialty_dish:place' -> 'dish', 'urn:tag:cuisine:qloo' -> 'cuisine', 'urn:entity:artist' -> 'artist'."""
    parts = (t or "").split(":")
    k = parts[2] if len(parts) >= 3 and parts[1] == "tag" else parts[-1]
    return TYPE_LABELS.get(k, k.replace("_", " ")) if t else None


def _chip(l):
    t = l.get("type") or ""
    return {"id": l.get("id"), "label": l.get("name") or l.get("text"), "kind": l.get("kind"), "type": t,
            "type_label": type_label(t), "disamb": l.get("disamb"), "dead": bool(l.get("dead"))}


def c2_count(trace):
    """C2 love lookups in a slice of the trace (network or cache, retries excluded): one count for every path."""
    return sum(1 for r in trace if r["label"].startswith("C2") and not r["label"].endswith("(retry)"))


def resolve_counted(q, text, hint=None):
    """E.resolve_love plus the number of C2 calls it made (0 when the pre-resolved table answered)."""
    n0 = len(q.trace)
    l = E.resolve_love(q, text, hint)
    return l, c2_count(q.trace[n0:])


def resolve_love(text, hint=None, *, mode="fake", qloo=None):
    q = _client(mode, qloo)
    try:
        l, n = resolve_counted(q, text, hint)
    except QlooError as e:
        return {"status": "degraded", "chip": None, "alternatives": [], "reason": "Qloo HTTP %s" % e.status}
    chip = dict(_chip(l), text=text, c2_calls=n) if l.get("id") else None
    alts = [dict(a, type_label=type_label(a.get("type"))) for a in l.get("alternatives") or []]
    return {"status": l["status"], "chip": chip, "alternatives": alts, "text": text}


def _love_from_chip(ch):
    t = ch.get("type") or ""
    l = {"text": ch.get("text") or ch.get("label") or ch.get("id"), "name": ch.get("label"), "id": ch["id"],
         "kind": ch.get("kind") or ("tag" if str(ch["id"]).startswith("urn:tag") else "entity"), "type": t,
         "status": "ok", "is_place": t == E.PLACE, "alternatives": [], "dead": False, "dead_reason": None,
         "_c2": int(ch.get("c2_calls") or 0)}      # C2 calls the chip cost when it resolved (on blur)
    if l["kind"] == "tag" and E.dead_tag({"type": t, "id": ch["id"]}):
        l["dead"], l["dead_reason"] = True, "vibe"
    return l


# ---------------------------------------------------------------- fake lanes (fake mode only, tagged)
class FakeGemini:
    """Stand-in for the live Gemini taste ask: real fixture names (one model from memory), labelled [FAKE]."""

    def __init__(self, city_key):
        self.city_key = city_key

    def __call__(self, prompt):
        try:
            fresh = W.fresh_for(self.city_key) if self.city_key in ("nyc", "stl") else []
        except OSError:
            fresh = []
        names = fresh[-1]["names"] if fresh else []
        return {"provider": "fake-gemini", "model": "[FAKE] fixture names", "names": names, "raw": None,
                "asked_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "lane": "live", "phrasing": prompt,
                "phrasing_id": "taste-all-live"}


def fake_street_check(q):
    """[FAKE] the AI names the 3 most popular open places of the fake world in that neighbourhood."""
    world = getattr(q.transport, "places", [])

    def fn(hood, city_name):
        here = [p for p in world if (p["properties"].get("neighborhood") == hood
                                     and p["properties"]["geocode"]["city"] == city_name
                                     and not p["properties"].get("is_closed"))]
        top = sorted(here, key=lambda p: (-p["popularity"], p["entity_id"]))[:3]
        return [{"provider": "fake-gemini", "model": "[FAKE]", "lane": "live",
                 "asked_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                 "phrasing": "Best places to eat and drink in %s, %s" % (hood, city_name),
                 "names": [{"name": p["name"], "neighbourhood": hood} for p in top]}]
    return fn


def _ask(gemini, prompt):
    a = gemini.ask(prompt) if hasattr(gemini, "ask") else gemini(prompt)
    a = dict(a or {})
    a.setdefault("provider", "gemini")
    a.setdefault("lane", "live")
    a.setdefault("asked_at", time.strftime("%Y-%m-%dT%H:%M:%S"))
    a.setdefault("phrasing", prompt)
    a.setdefault("phrasing_id", "taste-all-live")
    return a


def taste_prompt(labels, city_name):
    if len(labels) >= 2:
        ls = "%s and %s" % (", ".join(labels[:-1]), labels[-1])
    else:
        ls = labels[0] if labels else "food"
    return "I love %s. Where should I eat and drink in %s?" % (ls, city_name)


def match_set(city_key, loves):
    """The preset set (data/sets.json, else sets.draft.json, else seeds.py) whose loves these are, order-free and
    normalised, by typed text or resolved label: its dated taste answers join the wall."""
    keys = [tuple(sorted(M.norm(l.get(f) or "") for l in loves)) for f in ("text", "name")]
    for sid, spec in SD.SEED_SETS.get(city_key, []):
        if tuple(sorted(M.norm(t) for t, _ in spec)) in keys:
            return sid
    return None


# ---------------------------------------------------------------- boot
def warm(walls_path, cities=("nyc", "stl")):
    """Boot work, once per process (the server calls it at start): parse the walls and normalise every wall name
    (norm, keys, distinctive tokens, brand prefix, bigrams, place part) so no query pays for it. Returns
    {city: names, "cpu_s"}. Results are unchanged: these are the same memoised pure functions the strike calls."""
    import time as _t
    t = _t.process_time()
    out = {}
    for ck in cities:
        try:
            w = W.wall_for(ck, None, walls_path)
            data = W.load_file(walls_path)
        except (OSError, ValueError):
            continue
        answers = [a for x in data.get("walls", []) if W._ckey(x.get("city")) == ck for a in x.get("answers") or []]
        names = list(dict.fromkeys(n["name"] if isinstance(n, dict) else n
                                   for a in answers for n in a.get("names") or []))
        for n in names:
            M.keys(n)
            M.brand_seq(n)
            E.place_part(n)
            for x in (n, M.split_parts(n)[0]):
                for tok in M.distinctive(x):
                    M.bigrams(tok)
            M.norm(n)
        E.reverse_index_cached(list(w["answers"]))
        out[ck] = len(names)
    out["cpu_s"] = round(_t.process_time() - t, 3)
    return out


# ---------------------------------------------------------------- the run
def run_unsaid(city, loves, *, walls_path=None, mode="fake", on_event=None, qloo=None, gemini=None,
               street_check=None, last_seen=None, set_id=None, use_cache=True, deadline_s=HARD_CAP_S):
    t0 = time.monotonic()
    fake = mode == "fake"
    lock = threading.Lock()
    state = {"calls": 0, "total": 27, "ranking": False, "U": None}

    def send(evt):
        if on_event is None:
            return
        with lock:
            try:
                on_event(evt)
            except Exception:
                pass

    def finish(result):
        if state.get("q") is not None:
            state["q"].deadline, state["q"].on_call = None, None
        result.setdefault("flags", [])
        if fake and "fake" not in result["flags"]:
            result["flags"].append("fake")
        result.setdefault("diag", {})
        result["diag"].setdefault("engine_v", E.ENGINE_V)
        result["diag"]["elapsed_s"] = round(time.monotonic() - t0, 3)
        send({"type": "calls", "done": state["calls"], "total": max(state["calls"], state["total"])})
        send({"type": "done", "result": result})
        return result

    send({"type": "status", "state": "running", "text": "crossing out"})
    if not fake and quota_state().get("limited"):
        send({"type": "status", "state": "limited", "text": "Fresh runs are limited so everyone gets through."})
        return finish(_empty("limited", diag={"quota": quota_state()}))

    q = _client(mode, qloo, use_cache)
    q.start_deadline(deadline_s)
    t_start = len(q.trace)
    state["q"] = q

    # ---- city and loves (needs_input stops here; CROSS OUT stays disabled)
    needs = []
    try:
        # C1 (city) and C2 (loves) run at once; the global bucket paces them
        jobs = []
        if not (isinstance(city, dict) and city.get("status") == "ok" and city.get("center_latlon")):
            jobs.append(("city", lambda: resolve_city(city.get("name") if isinstance(city, dict) else city,
                                                      mode=mode, qloo=q)))
        typed = []
        for x in loves or []:
            if isinstance(x, dict) and x.get("id"):
                typed.append((x, None, None))
                continue
            text, hint = (x.get("text"), x.get("hint") or x.get("type")) if isinstance(x, dict) else (x, None)
            if isinstance(x, (list, tuple)):
                text, hint = x[0], x[1]
            typed.append((x, text, hint))
            jobs.append((len(typed) - 1, (lambda t=text, h=hint: E.resolve_love(q, t, h))))
        got = dict(zip([k for k, _ in jobs], E._pmap(lambda j: j[1](), jobs, max(1, len(jobs)))))
        if "city" in got:
            rc = got["city"]
            if rc["status"] == "degraded":
                return finish(_empty("degraded", diag={"error": rc.get("reason")}))
            c = rc.get("_city")
            if rc["status"] != "ok":
                needs.append({"field": "city", "text": city, "reason": rc.get("reason"),
                              "alternatives": rc["alternatives"]})
        else:
            c = city
        ls = []
        for k, (x, text, hint) in enumerate(typed):
            if text is None:
                ls.append(_love_from_chip(x))
                continue
            l = got[k]
            if l["status"] != "ok":
                needs.append({"field": "love", "text": text, "status": l["status"],
                              "suggestion": _chip(l) if l.get("id") else None, "alternatives": l.get("alternatives")})
            ls.append(l)
    except QlooError as e:
        return finish(_empty("degraded", diag={"error": "Qloo HTTP %s while resolving" % e.status}))
    if needs or not ls:
        if not ls:
            needs.append({"field": "love", "text": "", "status": "miss", "alternatives": []})
        send({"type": "status", "state": "needs_input", "text": "check the amber chips"})
        r = _empty("needs_input")
        r["needs"] = needs
        r["loves"] = [_chip(l) for l in ls if l.get("id")]
        return finish(r)

    # ---- the dated wall streams first, from static data
    cpu = E.CPU()
    city_key = c.get("key")
    sid = (SD.resolve(city_key, set_id) or set_id) if set_id else match_set(city_key, ls)
    try:
        wall = W.wall_for(city_key, sid, walls_path, loves=[l["text"] for l in ls])
    except (OSError, ValueError) as e:
        wall = {"answers": [], "source": "wall unavailable: %s" % type(e).__name__}
    for a in wall["answers"]:
        for n in a.get("names") or []:
            send(dict(E.wall_item(a, n["name"] if isinstance(n, dict) else n), type="wall_name"))
    cpu.mark("wall load")

    # ---- the live taste ask runs beside the Qloo path from t = 0
    if gemini is None and fake:
        gemini = FakeGemini(city_key)
    live_box, live_thread = {"answers": [], "error": None}, None
    if gemini:
        prompt = taste_prompt([l.get("name") or l["text"] for l in ls], c["name"])

        def ask():
            try:
                live_box["answers"] = [_ask(gemini, prompt)]
            except Exception as e:
                live_box["error"] = e
        live_thread = threading.Thread(target=ask, daemon=True)
        live_box["started"] = time.monotonic()
        live_thread.start()

    def live_answers():
        if live_thread is None:
            return []
        left = LIVE_BUDGET_S - (time.monotonic() - live_box["started"])      # the cards are already out
        if q.deadline is not None:
            left = min(left, q.deadline - time.monotonic())
        live_thread.join(timeout=max(0.0, left))
        if live_thread.is_alive():
            raise TimeoutError("live lane timed out")
        if live_box["error"] is not None:
            raise live_box["error"]
        return live_box["answers"]

    if street_check is None and fake:
        street_check = fake_street_check(q)
    if last_seen is None:                 # §3.1 last-seen: hours + address + the venue's own site (live); the server
        from unsaid import lastseen      # may pass its own; last_seen=False switches it off
        last_seen = lastseen.fake_check if fake else lastseen.check

    # ---- calls / ranking events from the client
    n_ent = sum(1 for l in ls if l.get("kind") == "entity")
    n_resc = sum(1 for l in ls if not (l.get("dead") and l.get("dead_reason") == "vibe"))

    def on_call(rec):
        state["calls"] += 1
        send({"type": "calls", "done": state["calls"], "total": max(state["calls"], state["total"])})
        if not state["ranking"] and time.monotonic() - t0 > RANKING_AFTER_S:
            state["ranking"] = True
            send({"type": "status", "state": "ranking", "text": "Qloo is ranking your %s places · %d of %d calls" % (
                state["U"] if state["U"] is not None else "", state["calls"], max(state["calls"], state["total"]))})
    q.on_call = on_call

    label = {l["text"]: (l.get("name") or l["text"]) for l in ls}

    def emit(kind, payload):
        live_trace = [r for r in q.trace[t_start:] if not r["label"].endswith("(retry)")]
        if kind == "card":
            payload = contract_card(payload, live_trace, label, keep=("provisional",))
        elif kind == "burn" and payload.get("risen"):
            payload = dict(payload, risen=contract_card(payload["risen"], live_trace, label))
        if kind == "pool":
            state["U"] = payload["U"]
            state["total"] = state["calls"] + n_resc * max(1, math.ceil(payload["U"] / 48.0)) + 1 + 5
        send(dict(payload, type=kind))

    try:
        res = E.run(q, c, ls, wall, street_check=street_check or None, last_seen=last_seen or None,
                    live_answers=live_answers if gemini else None, emit=emit, strict=True)
    except QlooError as e:
        send({"type": "status", "state": "degraded", "text": "Qloo isn't answering right now."})
        return finish(_empty("degraded", diag={"error": "Qloo HTTP %s" % e.status, "qloo_calls": state["calls"]}))
    finally:
        q.on_call = None
        q.deadline = None
    cpu.t = __import__("time").process_time()
    out = to_contract(res, q.trace[t_start:], c, ls, fake)
    cpu.mark("contract")
    out["diag"]["cpu_s"] = dict(cpu.out, **{"engine." + k: v for k, v in ((res.get("diag") or {}).get("cpu_s") or
                                                                      {}).items()})
    return finish(out)


def _empty(status, diag=None):
    return {"status": status, "flags": [], "loves": [], "city": None, "picks": [], "reserves": [], "wall": [],
            "counts": {"wall": 0, "asks": 0, "P": 0, "U": 0, "S": 0, "R_mi": 0,
                       "floor": {"closed": 0, "below_43": 0, "outside_R": 0, "not_venue": 0, "not_venue_music": 0}},
            "burn": {"asked": [], "burned": []},
            "diag": dict({"qloo_calls": 0, "rho_tp": None, "rho_res": None, "cap_keep": None, "cap_shared": None,
                          "engine_v": E.ENGINE_V, "as_of": None, "trace_url": None}, **(diag or {}))}


def _nan(x, nd=4):
    return None if x is None or x != x else round(x, nd)


def dead_line(l, city_name, n_live):
    """§2.2 dead love: "Anthony Anderson doesn't change St. Louis restaurants much; ranked on the other two."
    When every love is dead the run is `flat` and the clause is dropped."""
    head = "%s doesn't change %s restaurants much" % (l.get("name") or l["text"], city_name)
    if n_live == 0:
        return head + "."
    return "%s; ranked on the other %s." % (head, "one" if n_live == 1 else NUM.get(n_live, str(n_live)))


CALL_KINDS = (("pool", ("C4",)), ("rescore", ("C6'", "C5")), ("ids", ("C7",)), ("cap", ("CAP",)))


def call_counts(trace, chip_c2=0):
    """diag.calls = {pool, rescore, ids, cap, loves, city, total}. loves = the C2 lookups, whether they ran inside
    this run (typed loves) or when the chips resolved (chip.c2_calls), network or cache. total = the sum."""
    out = {k: sum(1 for r in trace if r["label"].startswith(p)) for k, p in CALL_KINDS}
    out["loves"] = c2_count(trace) + chip_c2
    out["city"] = sum(1 for r in trace if r["label"].startswith("C1"))
    other = len(trace) - (sum(out.values()) - chip_c2)        # anything uncategorised stays visible
    if other:
        out["other"] = other
    out["total"] = sum(out.values())
    return out


def request_urls(card, trace):
    """Every request this card's ranks came from, key-redacted: the C4 pool call(s) it came back in and the C6'
    rescoring chunks that carried its ID (for RAW LOG)."""
    urls = list(card.get("_pool_urls") or [])

    def chunk_key(r):            # parallel calls finish in any order: list them by love, then chunk number
        head, _, tail = r["label"].rpartition(" c")
        return (head, int(tail) if tail.isdigit() else 0, r["url"])
    urls += [r["url"] for r in sorted((r for r in trace if r["label"].startswith(("C6'", "C5"))
                                        and card["id"] in r["url"]), key=chunk_key)]
    return [redact(u) for u in dict.fromkeys(urls)]


def contract_card(x, trace, label, keep=()):
    """Engine card -> CONTRACT CARD (because/holds_without as love labels, request_urls key-redacted)."""
    y = {k: v for k, v in x.items() if k not in ("because_label", "provisional", "_pool_urls") or k in keep}
    y["because"] = label.get(x["because"], x["because"]) if x.get("because") else None
    y["holds_without"] = label.get(x["holds_without"], x["holds_without"]) if x.get("holds_without") else None
    y["request_urls"] = request_urls(x, trace)
    return y


def to_contract(res, trace, c, ls, fake):
    """Engine result -> CONTRACT.md result."""
    d = res.get("diag") or {}
    out = _empty(res["status"])
    live_n = 0 if d.get("all_dead") else len(d.get("loves_live") or [])
    loves = []
    for l in res.get("loves") or ls:
        ch = _chip(l)
        if l.get("dead"):
            ch["dead_line"] = dead_line(l, c["name"], live_n)
            ch["dead_reason"] = l.get("dead_reason")
        loves.append(ch)
    label = {l["text"]: (l.get("name") or l["text"]) for l in ls}

    trace = [r for r in trace if not r["label"].endswith("(retry)")]

    def card(x):
        return contract_card(x, trace, label)

    out.update({
        "flags": list(res.get("flags") or []), "loves": loves, "city": C.public(c),
        "picks": [card(x) for x in res.get("picks") or []], "reserves": [card(x) for x in res.get("reserves") or []],
        "wall": res.get("wall") or [], "burn": res.get("burn") or {"asked": [], "burned": []}})
    cn = res.get("counts") or {}
    out["counts"].update({k: cn.get(k, out["counts"].get(k)) for k in ("wall", "asks", "P", "U", "S", "R_mi")})
    out["counts"]["struck_in_U"] = cn.get("struck_in_U")
    if cn.get("floor"):
        out["counts"]["floor"] = cn["floor"]
    if res.get("fallback_ids"):
        U = {e["entity_id"]: e for e in res.get("_U") or []}
        out["fallback"] = [{"id": i, "name": U[i].get("name") if i in U else None} for i in res["fallback_ids"]]
    cap = d.get("cap") or {}
    out["diag"].update({
        "obscure_names": [n for _, n in d.get("obscure") or []], "known_names": [n for _, n in d.get("known") or []],
        "dish_tagged": d.get("dish_tagged"), "prior": d.get("prior"),
        "calls": call_counts(trace, sum(l.get("_c2", 0) for l in ls)), "wall_names": d.get("wall_names"), "wall_snapshot": d.get("wall_snapshot"),
        "struck_fit_ranks": d.get("struck_fit_ranks") or [],
        "qloo_calls": call_counts(trace, sum(l.get("_c2", 0) for l in ls))["total"], "qloo_network": sum(1 for r in trace if not r["cache"]),
        "rho_tp": _nan(d.get("rho_tp")), "rho_res": _nan(d.get("rho_res")), "rho_res_note": d.get("rho_res_note"),
        "cap_keep": d.get("cap_keep"),
        "cap_shared": d.get("cap_shared"), "cap_overlap": _nan(d.get("popcap_overlap")),
        "cap7": [{"id": i, "name": n} for i, n in cap.get("cap7") or []], "cap_max": cap.get("max"),
        "obscure": [{"id": i, "name": n} for i, n in d.get("obscure") or []],
        "known": [{"id": i, "name": n} for i, n in d.get("known") or []],
        "engine_v": d.get("engine_v", E.ENGINE_V), "as_of": d.get("as_of"), "trace_url": None,
        "tie_share": _nan(d.get("tie_share")),
        "tie_by_love": {label.get(k, k): _nan(v) for k, v in (d.get("tie_by_love") or {}).items()}, "baseline": d.get("baseline"), "lanes_failed": d.get("lanes_failed"),
        "wall_source": (d.get("wall") or {}).get("source"), "kept": d.get("kept"),
        "reverse_struck": d.get("reverse_struck"), "last_seen_dropped": d.get("last_seen_dropped"),
        "rescore": {label.get(k, k): {kk: _nan(vv) if isinstance(vv, float) else vv for kk, vv in v.items()}
                    for k, v in (d.get("rescore") or {}).items()},
        "explain_page1": d.get("explain_page1"), "live_error": d.get("live_error")})
    return out
