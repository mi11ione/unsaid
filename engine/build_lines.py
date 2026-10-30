"""Card lines (29-30 Oct): one line of <= 9 words per place, plus up to 3 dishes or drinks, condensed by Claude from
Qloo's OWN text for that place (unique_selling_points, overall_description, cuisine_description, specialty_dishes,
short_description), then checked twice:
  1. word check (code): every content word (a stem of it) is in the source, <= 9 words, no marketing word;
  2. read check (Claude, 30 Oct): every line goes back to `claude -p` with its source: "is this fluent, natural English,
     fully supported by the source, and does it lead with what you eat, drink or do there?" -> {ok, fix?}. A fix is
     kept only if it passes the word check too; otherwise the line is marked failed and the engine uses its rules
     fallback (engine.blurb_line).
Lines lead with the food, drink or thing to do and never name ownership or identity (Black-owned, women-owned,
family-run, LGBTQ+, gay bar ...; card audit 30 Oct): such a line is rewritten (names_identity). Food facts (halal,
kosher, vegan) stay. --must <dir of result files>: every card and reserve there gets extra rounds (with the last
attempt and its reason as feedback) until it has a checked line.
Dishes must appear verbatim in the source.

  python3 -I build_lines.py                       # both cities: every place in the Qloo cache + the prior universe
  python3 -I build_lines.py --city stl --max-calls 10 --dry-run

Places (30 Oct): every place entity with Qloo text in ANY cached response under engine/.cache/live (insights for
every query run so far), assigned to the nearest configured city within --within-mi of its centre, plus
data/priors/<city>.json "scored". So fresh queries rarely meet a place without a line. 0 Qloo calls.
Claude runs as `claude -p` (no tools, structured JSON output): ~50 places a write call, ~80 lines a read call,
<= --max-calls in all. Output: data/lines/<city>.json (Qloo-derived: gitignored, pushed to Render by
server/push_priors.py as lines-<city>.json). Raw replies are kept in data/lines/.raw/; a rerun only asks for places
with no line and only reads lines not yet read ("checked")."""
import argparse, glob, json, os, re, subprocess, sys, tempfile, time
from concurrent.futures import ThreadPoolExecutor
from multiprocessing import Pool

KIT = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(KIT)
sys.path.insert(0, KIT)
from unsaid.cities import CITIES, haversine_mi  # noqa: E402

FIELDS = ("unique_selling_points", "overall_description", "cuisine_description", "short_description")
MAX_WORDS = 9
BANNED = {"vibrant", "destination", "establishment", "experience", "nestled", "hidden", "gem", "must-visit",
          "unforgettable", "iconic", "beloved", "premier", "elevated", "unique", "boasts", "offers", "venue"}
FUNC = set("""a an the and or nor but of for with in on at to by from into onto over under than as is are was were be
been being its it's it their there this that these those his her our your who whom which what where when while plus
via per & + - — – ; , . : ' " ( ) / since around within inside near beside behind along across through
after before about up down out off both each every also just you yourself""".split())
# Ownership / identity: never in a line at all (juror, 30 Oct: "5 of my 14 cards say Black-owned"; card audit, 30 Oct).
# Food facts (halal, kosher, vegan) and "dog-friendly" / "family-friendly" stay.
_IDW = (r"(?:black|brown|women|woman|female|family|lgbtq\+?|lgbt|queer|gay|lesbian|latin[oax]|latine|hispanic|"
        r"veteran|minority|immigrant|asian|indigenous|native|chef|artist|owner|mom|mother|father|husband|wife|couple)")
IDENTITY = re.compile(r"\b%s(?:-|\s)*(?:owned|run|operated)\b|\b(?:owned|run|operated)\s+by\b|\blgbtq|\blgbt\b|"
                      r"\bqueer\b|\bgay\b|\blesbian\b|\bafrican[- ]american\b|\b(?:black|women|woman)[- ]led\b" % _IDW,
                      re.I)

SCHEMA = {"type": "object", "required": ["lines"], "properties": {"lines": {"type": "array", "items": {
    "type": "object", "required": ["id", "line", "dishes"], "properties": {
        "id": {"type": "string"}, "line": {"type": "string"},
        "dishes": {"type": "array", "items": {"type": "string"}, "maxItems": 3}}}}}}
VSCHEMA = {"type": "object", "required": ["results"], "properties": {"results": {"type": "array", "items": {
    "type": "object", "required": ["id", "ok"], "properties": {
        "id": {"type": "string"}, "ok": {"type": "boolean"}, "fix": {"type": "string"}}}}}}

RULES = """no new adjectives, claims, prices, dates or history beyond the text; reuse the text's own words; plain,
  specific, fluent English a local would say (never stitched fragments or word salad); never use marketing words
  (vibrant, destination, establishment, experience, nestled, venue, unique, boasts, offers, iconic, beloved, premier,
  elevated, gem, hidden); no trailing period; do not start with the place's name.
  LEAD WITH WHAT YOU EAT, DRINK OR DO THERE (the dish, the drinks, the music, the game, the dancing). NEVER mention
  ownership or identity anywhere in the line (Black-owned, women-owned, family-run, LGBTQ+, LGBTQ+-friendly, gay,
  lesbian, queer, veteran-owned ...): say what happens there instead (drag shows, dancing, karaoke). Food facts such
  as halal, kosher or vegan are fine."""

PROMPT = """You write the one-line description on a restaurant/bar card. For EACH place below, return:
- line: at most 9 words. Name the one thing you eat, drink or do there that makes this place itself, using ONLY
  facts stated in its text. Examples of the register: "Famous for tender, smoky rib tips"; "Soul food and dancing
  at a neighborhood bar and grill"; "Italian in a Victorian house; legendary vocalists on the stereo".
  Rules: %s
- dishes: up to 3 dishes or drinks people order there, copied EXACTLY as written in the text (same words); [] if
  the text names none. Never generic words like food, drinks, cocktails, beer, wine.
If an item has previous_attempt, that line was rejected for the reason given: write a different line that fixes it
(fewer words, only the text's own words, no marketing word, no identity).
Return every id given, once.

PLACES (JSON):
""" % RULES

VERIFY = """You check the one-line descriptions on restaurant/bar cards. Each item has a `line` that was condensed
from `source` (the place's own text). For EACH item return:
- ok: true only if ALL hold: (1) the line is fluent, natural English a person would write (no garbled or stitched
  phrases, no broken grammar: "Sushi and bluefin tuna rib diners scrape themselves" is NOT ok); (2) every fact in it
  is fully supported by the source; (3) it leads with what you eat, drink or do there and names no ownership or
  identity anywhere ("Black-owned", "women-owned", "family-run", "LGBTQ+", "gay bar" ... are NOT ok).
- fix: only when ok is false, a corrected line of at most 9 words. Rules: %s
  Omit fix if you cannot write a good one.
Return every id given, once.

ITEMS (JSON):
""" % RULES


def stem(w):
    w = w.lower().strip("'’\".,;:!?()[]")
    w = re.sub(r"['’]s$", "", w)
    for suf in ("ing", "ed", "es", "s", "ly"):
        if len(w) > 4 and w.endswith(suf):
            return w[:-len(suf)]
    return w


def words(text):
    return re.findall(r"[A-Za-z0-9À-ɏ][A-Za-z0-9À-ɏ'’+&-]*", text or "")


def names_identity(line):
    """True when the line names ownership or identity anywhere ("Black-owned bar ...", "... at a gay bar",
    "LGBTQ+ friendly sports bar", "queer and women-owned")."""
    return bool(IDENTITY.search(line or ""))


def source_text(p):
    parts = [p.get("name") or ""] + [p.get(k) or "" for k in FIELDS]
    parts += [(d.get("name") if isinstance(d, dict) else str(d)) for d in p.get("specialty_dishes") or []]
    return " \n".join(x for x in parts if x)


def check_line(line, src):
    """-> None if the line passes, else the reason. Every content word (or a stem of it) must be in the source."""
    ws = words(line)
    if not ws:
        return "empty"
    if len(line.split()) > MAX_WORDS:
        return "over %d words" % MAX_WORDS
    if names_identity(line):
        return "names identity"
    low = src.lower()
    stems = set()
    for w in words(src):
        for part in [w] + w.split("-"):
            if part:
                stems.add(stem(part))
    for w in ws:
        lw = w.lower()
        if lw in BANNED or stem(w) in BANNED:
            return "marketing word %r" % w
        if lw in FUNC:
            continue
        for part in [w] + (w.split("-") if "-" in w else []):
            s = stem(part)
            if not s or s in FUNC:
                continue
            if s in stems or (len(s) >= 5 and any(t.startswith(s) or (len(t) >= 5 and s.startswith(t)) for t in stems)):
                continue
            if re.search(r"(?<![a-z0-9])%s" % re.escape(part.lower()), low):
                continue
            return "not in source: %r" % w
    return None


def check_dishes(dishes, src):
    low, out = src.lower(), []
    for d in dishes or []:
        d = (d or "").strip()
        if d and d.lower() in low and d.lower() not in ("food", "drinks", "cocktails", "beer", "wine") \
                and d.lower() not in [x.lower() for x in out]:
            out.append(d)
    return out[:3]


def _richness(p):
    return sum(bool(p.get(k)) for k in FIELDS)


def _scan(f):
    """One cache file -> {entity_id: place record} for every place entity carrying properties."""
    out = {}
    try:
        with open(f) as fh:
            s = fh.read()
    except OSError:
        return out
    if '"urn:entity:place"' not in s or '"properties"' not in s:
        return out
    try:
        stack = [json.loads(s)]
    except ValueError:
        return out
    while stack:
        x = stack.pop()
        if isinstance(x, dict):
            if x.get("subtype") == "urn:entity:place" and x.get("entity_id") and isinstance(x.get("properties"), dict):
                p, loc = x["properties"], x.get("location") or {}
                rec = dict({k: p.get(k) for k in FIELDS}, name=x.get("name"), specialty_dishes=p.get("specialty_dishes"),
                           lat=loc.get("lat"), lon=loc.get("lon"))
                if _richness(rec) > _richness(out.get(x["entity_id"]) or {}):
                    out[x["entity_id"]] = rec
            stack.extend(x.values())
        elif isinstance(x, list):
            stack.extend(x)
    return out


def gather(cities, within_mi):
    """Every place in the cached Qloo responses, by nearest city centre (<= within_mi), plus each prior's scored ids
    (kept even if they have no coordinates). -> ({city: {id: record}}, n prior ids missing from the cache)."""
    files = glob.glob(os.path.join(KIT, ".cache", "live", "*", "*.json"))
    got = {}
    with Pool(8) as pool:
        for r in pool.imap_unordered(_scan, files, chunksize=20):
            for i, rec in r.items():
                if _richness(rec) > _richness(got.get(i) or {}):
                    got[i] = rec
    prior = {}
    for c in cities:
        try:
            for i in json.load(open(os.path.join(ROOT, "data", "priors", "%s.json" % c))).get("scored") or []:
                prior[i] = c
        except (OSError, ValueError):
            pass
    out = {c: {} for c in cities}
    for i, p in got.items():
        c = prior.get(i)
        if not c and p.get("lat") is not None:
            d, k = min((haversine_mi((p["lat"], p["lon"]), CITIES[k]["center"]), k) for k in CITIES)
            c = k if d <= within_mi else None
        if c in out:
            out[c][i] = p
    return out, sum(1 for i in prior if i not in got)


def claude_json(prompt, payload, schema, rawdir, tag):
    with tempfile.TemporaryDirectory() as tmp:          # no project context: an empty working directory
        r = subprocess.run(["claude", "-p", "--no-session-persistence", "--tools", "", "--output-format", "json",
                            "--json-schema", json.dumps(schema)], input=prompt + json.dumps(payload, ensure_ascii=False),
                           cwd=tmp, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True,
                           timeout=1200)
    try:
        out = json.loads(r.stdout).get("structured_output") or {}
    except ValueError:
        out = {}
    with open(os.path.join(rawdir, "%s-%d.json" % (tag, int(time.time() * 1000))), "w") as fh:
        json.dump({"ids": [x["id"] for x in payload], "reply": out, "rc": r.returncode,
                   "stderr": r.stderr[-500:]}, fh, ensure_ascii=False, indent=1)
    return out


def ask(batch, rawdir, k):
    """batch: [(id, place, failed record or None)]; a failed record's line and reason go back as feedback."""
    items = []
    for i, p, prev in batch:
        it = {"id": i, "name": p.get("name"), "text": {f: p.get(f) for f in FIELDS if p.get(f)},
              "specialty_dishes": [(d.get("name") if isinstance(d, dict) else str(d))
                                   for d in p.get("specialty_dishes") or []]}
        if prev and (prev.get("fix") or prev.get("line")):
            it["previous_attempt"] = {"line": prev.get("fix") or prev.get("line"), "rejected_because": prev.get("why")}
        items.append(it)
    return claude_json(PROMPT, items, SCHEMA, rawdir, "write-%d" % k).get("lines") or []


def read_check(batch, rawdir, k):
    items = [{"id": i, "line": line, "source": {f: p.get(f) for f in FIELDS if p.get(f)}}
             for i, line, p in batch]
    return claude_json(VERIFY, items, VSCHEMA, rawdir, "read-%d" % k).get("results") or []


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--city", choices=["nyc", "stl", "both"], default="both")
    ap.add_argument("--out", default=os.environ.get("UNSAID_LINES_DIR") or os.path.join(ROOT, "data", "lines"))
    ap.add_argument("--within-mi", type=float, default=30.0, help="a cached place belongs to the nearest city centre "
                    "within this distance (NYC's boroughs reach ~25 mi from the Manhattan centroid)")
    ap.add_argument("--batch", type=int, default=50)
    ap.add_argument("--read-batch", type=int, default=80)
    ap.add_argument("--max-calls", type=int, default=120, help="claude -p calls in all (write + read)")
    ap.add_argument("--rounds", type=int, default=2, help="write/read rounds; round 2+ rewrites the failed lines")
    ap.add_argument("--max-tries", type=int, default=2, help="writes per place in all (across runs)")
    ap.add_argument("--must", help="a directory of result files (e.g. site/data/live): every card and reserve in "
                    "them gets extra rounds until it has a checked line")
    ap.add_argument("--must-tries", type=int, default=6)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--force", action="store_true", help="ask again for places that already have a line")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    cities = ["nyc", "stl"] if args.city == "both" else [args.city]
    rawdir = os.path.join(args.out, ".raw")
    os.makedirs(rawdir, exist_ok=True)
    places, missing = gather(cities, args.within_mi)
    places = {c: {i: p for i, p in v.items() if any(p.get(f) for f in FIELDS)} for c, v in places.items()}
    print("places with Qloo text: %s (%d prior ids not in the cache)" % (
        {c: len(v) for c, v in places.items()}, missing), flush=True)
    docs, stats = {}, {"calls": 0, "written": 0, "word_rejected": 0, "no_reply": 0, "identity_regen": 0,
                       "read": 0, "read_ok": 0, "read_fixed": 0, "read_failed": 0, "reasons": {}}
    for c in cities:
        fp = os.path.join(args.out, "%s.json" % c)
        docs[c] = json.load(open(fp)) if os.path.exists(fp) and not args.force else {"lines": {}}
        for k in ("lines", "failed", "rejected"):
            docs[c].setdefault(k, {})
        for i, x in list(docs[c]["lines"].items()):            # lines that name identity are written again
            if names_identity(x.get("line")):
                docs[c]["failed"][i] = {"line": x.get("line"), "why": "names identity", "tries": 0,
                                        "name": x.get("name")}
                docs[c]["lines"].pop(i)
                stats["identity_regen"] += 1
    budget = lambda: args.max_calls - stats["calls"]  # noqa: E731

    tries = lambda f: f.get("tries", f.get("round", 0)) if f else 0  # noqa: E731
    must = set()
    for f in sorted(glob.glob(os.path.join(args.must, "*.json"))) if args.must else []:
        try:
            r = (json.load(open(f)) or {}).get("result") or {}
        except (OSError, ValueError, AttributeError):
            continue
        must |= {x["id"] for x in (r.get("picks") or []) + (r.get("reserves") or []) if x.get("id")}
    if args.must:
        print("must: %d preset cards and reserves (%d without a line, %d not in the cache)" % (
            len(must), sum(1 for i in must if not any(i in docs[c]["lines"] for c in cities)),
            sum(1 for i in must if not any(i in places[c] for c in cities))), flush=True)

    def write_round(rnd, only=None):
        todo = []
        for c in cities:
            for i, p in sorted(places[c].items()):
                if i in docs[c]["lines"] or (only is not None and i not in only):
                    continue
                f = docs[c]["failed"].get(i)
                if tries(f) >= (args.must_tries if i in must else args.max_tries):
                    continue
                todo.append((c, i, p))
        n = -(-len(todo) // args.batch)
        batches = [todo[k:k + args.batch] for k in range(0, len(todo), args.batch)][:max(0, min(n, budget()))]
        print("round %d write: %d places in %d calls (%d left in the budget)" % (rnd, len(todo), len(batches),
                                                                                budget()), flush=True)
        if args.dry_run or not batches:
            return
        stats["calls"] += len(batches)
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            for b, reply in ex.map(lambda kb: (kb[1], ask([(i, p, docs[c]["failed"].get(i)) for c, i, p in kb[1]],
                                                          rawdir, kb[0])), enumerate(batches)):
                by = {x.get("id"): x for x in reply if isinstance(x, dict)}
                for c, i, p in b:
                    x = by.get(i)
                    n_try = tries(docs[c]["failed"].get(i)) + 1
                    if not x:
                        stats["no_reply"] += 1
                        docs[c]["failed"][i] = {"line": None, "why": "no reply", "tries": n_try, "name": p.get("name")}
                        continue
                    src = source_text(p)
                    line = (x.get("line") or "").strip().rstrip(".")
                    why = check_line(line, src)
                    if why:
                        stats["word_rejected"] += 1
                        key = why.split(":")[0]
                        stats["reasons"][key] = stats["reasons"].get(key, 0) + 1
                        docs[c]["failed"][i] = {"line": line, "why": "word check: " + why, "tries": n_try,
                                                "name": p.get("name")}
                        continue
                    docs[c]["failed"].pop(i, None)
                    docs[c]["lines"][i] = {"line": line[:1].upper() + line[1:], "name": p.get("name"),
                                           "dishes": check_dishes(x.get("dishes"), src), "tries": n_try}
                    stats["written"] += 1
                print("  write batch done: %d written, %d word-rejected, %d no reply" % (
                    stats["written"], stats["word_rejected"], stats["no_reply"]), flush=True)

    def read_round(rnd):
        todo = [(c, i, x["line"], places[c].get(i)) for c in cities for i, x in sorted(docs[c]["lines"].items())
                if not x.get("checked") and places[c].get(i)]
        n = -(-len(todo) // args.read_batch)
        batches = [todo[k:k + args.read_batch] for k in range(0, len(todo), args.read_batch)][:max(0, min(n, budget()))]
        print("round %d read: %d lines in %d calls (%d left in the budget)" % (rnd, len(todo), len(batches),
                                                                              budget()), flush=True)
        if args.dry_run or not batches:
            return
        stats["calls"] += len(batches)
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            for b, reply in ex.map(lambda kb: (kb[1], read_check([(i, l, p) for _, i, l, p in kb[1]], rawdir, kb[0])),
                                   enumerate(batches)):
                by = {x.get("id"): x for x in reply if isinstance(x, dict)}
                for c, i, line, p in b:
                    x = by.get(i)
                    if not x:                                    # unread: stays unchecked for a rerun
                        continue
                    stats["read"] += 1
                    rec = docs[c]["lines"][i]
                    if x.get("ok") is True:
                        rec["checked"] = "ok"
                        stats["read_ok"] += 1
                        continue
                    fix = (x.get("fix") or "").strip().rstrip(".")
                    why = check_line(fix, source_text(p)) if fix else "no fix"
                    if not why:
                        rec.update(was=line, line=fix[:1].upper() + fix[1:], checked="fixed")
                        stats["read_fixed"] += 1
                        continue
                    stats["read_failed"] += 1
                    docs[c]["lines"].pop(i)
                    docs[c]["failed"][i] = {"line": line, "fix": fix or None, "why": "read check: " + why,
                                            "tries": rec.get("tries", rec.get("round", 1)), "name": p.get("name")}
                print("  read batch done: %d read, %d ok, %d fixed, %d failed" % (
                    stats["read"], stats["read_ok"], stats["read_fixed"], stats["read_failed"]), flush=True)

    for rnd in range(1, args.rounds + 1):
        write_round(rnd)
        read_round(rnd)
    for rnd in range(args.rounds + 1, args.rounds + 1 + args.must_tries) if must else []:
        if not any(i in places[c] and i not in docs[c]["lines"] for c in cities for i in must):
            break
        write_round(rnd, only=must)
        read_round(rnd)
    if must:
        left = [(docs[c]["failed"].get(i) or {}).get("name") or i for c in cities for i in must
                if i in places[c] and i not in docs[c]["lines"]]
        print("must: %d of %d with a checked line; still without: %s" % (len(must) - len(left), len(must), left))
    if args.dry_run:
        return
    for c in cities:
        docs[c].pop("rejected", None)                       # pre-30 Oct word-check log; now in "failed"
        docs[c].update({"city": c, "built_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "method": (
            "condensed by Claude (claude -p) from Qloo's own text fields %s; every content word checked against the "
            "source; each line then read back by Claude with its source (fluent, supported, leads with what you "
            "eat/drink/do; fixes word-checked too); dishes verbatim; failed -> the engine's rules line"
            % ", ".join(FIELDS + ("specialty_dishes",))),
            "coverage": {"places": len(places[c]), "lines": len(docs[c]["lines"]),
                         "checked": sum(1 for x in docs[c]["lines"].values() if x.get("checked")),
                         "failed": sum(1 for i in docs[c]["failed"] if i in places[c])}})
        with open(os.path.join(args.out, "%s.json" % c), "w") as fh:
            json.dump(docs[c], fh, ensure_ascii=False, indent=1)
    print("build_lines: %s; calls %d -> %s" % (json.dumps(stats), stats["calls"], ", ".join(
        "%s %s" % (c, docs[c]["coverage"]) for c in cities)))


if __name__ == "__main__":
    sys.exit(main())
