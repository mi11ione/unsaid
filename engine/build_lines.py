"""Card lines (29 Oct): one line of <= 9 words per place, plus up to 3 dishes or drinks, condensed by Claude from
Qloo's OWN text for that place (unique_selling_points, overall_description, cuisine_description, specialty_dishes,
short_description), then checked word for word in code. No new facts: a line whose content words are not all in the
source (a stem of each), that runs past 9 words, or that uses a marketing word is rejected and the engine falls back
to its rule-based blurb. Dishes must appear verbatim in the source.

  python3 -I build_lines.py                       # both cities: the prior universe + every card/reserve in --cards
  python3 -I build_lines.py --city stl --max-calls 10 --dry-run

Places: data/priors/<city>.json "scored" (the anchor panel's universe) plus the cards and reserves of the result
files in --cards (default ~/Desktop/qloo/private/fresh20-28oct). Their text comes from the Qloo cache (engine/.cache,
0 Qloo calls). Claude runs as `claude -p` (no tools, structured JSON output), ~40 places a call, <= --max-calls.
Output: data/lines/<city>.json (Qloo-derived: gitignored, pushed to Render by server/push_priors.py as
lines-<city>.json). Raw replies are kept in data/lines/.raw/ so a rerun only asks for places it has no line for."""
import argparse, glob, json, os, re, subprocess, sys, tempfile, time
from concurrent.futures import ThreadPoolExecutor

KIT = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(KIT)
FIELDS = ("unique_selling_points", "overall_description", "cuisine_description", "short_description")
MAX_WORDS = 9
BANNED = {"vibrant", "destination", "establishment", "experience", "nestled", "hidden", "gem", "must-visit",
          "unforgettable", "iconic", "beloved", "premier", "elevated", "unique", "boasts", "offers", "venue"}
FUNC = set("""a an the and or nor but of for with in on at to by from into onto over under than as is are was were be
been being its it's it their there this that these those his her our your who whom which what where when while plus
via per & + - — – ; , . : ' " ( ) / since around within inside near beside behind along across through
after before about up down out off both each every also just""".split())

SCHEMA = {"type": "object", "required": ["lines"], "properties": {"lines": {"type": "array", "items": {
    "type": "object", "required": ["id", "line", "dishes"], "properties": {
        "id": {"type": "string"}, "line": {"type": "string"},
        "dishes": {"type": "array", "items": {"type": "string"}, "maxItems": 3}}}}}}

PROMPT = """You write the one-line description on a restaurant/bar card. For EACH place below, return:
- line: at most 9 words. Name the one thing that makes this place itself, using ONLY facts stated in its text.
  Examples of the register: "Missouri's most historic African American bar"; "Famous for tender, smoky rib tips";
  "Italian in a Victorian house; legendary vocalists on the stereo".
  Rules: no new adjectives, claims, prices, dates or history beyond the text; reuse the text's own words; plain and
  specific; never use marketing words (vibrant, destination, establishment, experience, nestled, venue, unique,
  boasts, offers, iconic, beloved, premier, elevated, gem); no trailing period; do not start with the place's name.
- dishes: up to 3 dishes or drinks people order there, copied EXACTLY as written in the text (same words); [] if
  the text names none. Never generic words like food, drinks, cocktails, beer, wine.
Return every id given, once.

PLACES (JSON):
"""


def stem(w):
    w = w.lower().strip("'’\".,;:!?()[]")
    w = re.sub(r"['’]s$", "", w)
    for suf in ("ing", "ed", "es", "s", "ly"):
        if len(w) > 4 and w.endswith(suf):
            return w[:-len(suf)]
    return w


def words(text):
    return re.findall(r"[A-Za-z0-9À-ɏ][A-Za-z0-9À-ɏ'’+&-]*", text or "")


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


def gather(cities, cards_dir):
    want = {}
    for c in cities:
        try:
            d = json.load(open(os.path.join(ROOT, "data", "priors", "%s.json" % c)))
            for i in d.get("scored") or []:
                want[i] = c
        except (OSError, ValueError):
            pass
    if cards_dir and os.path.exists(os.path.join(cards_dir, "index.json")):
        for s in json.load(open(os.path.join(cards_dir, "index.json")))["sets"]:
            if s["city"] in cities:
                r = json.load(open(os.path.join(cards_dir, s["file"])))["result"]
                for x in r["picks"] + r["reserves"]:
                    want[x["id"]] = s["city"]
    got = {}

    def walk(x):
        if isinstance(x, dict):
            i = x.get("entity_id")
            if i in want and isinstance(x.get("properties"), dict) and not (got.get(i) or {}).get(FIELDS[0]):
                p = x["properties"]
                got[i] = dict({k: p.get(k) for k in FIELDS}, name=x.get("name"),
                              specialty_dishes=p.get("specialty_dishes"))
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    for f in glob.glob(os.path.join(KIT, ".cache", "live", "*", "*.json")):
        try:
            with open(f) as fh:
                s = fh.read()
            if '"properties"' in s:
                walk(json.loads(s))
        except (OSError, ValueError):
            continue
    return {c: {i: got[i] for i in got if want[i] == c} for c in cities}, len(want) - len(got)


def ask(batch, rawdir, k):
    items = [{"id": i, "name": p.get("name"), "text": {f: p.get(f) for f in FIELDS if p.get(f)},
              "specialty_dishes": [(d.get("name") if isinstance(d, dict) else str(d))
                                   for d in p.get("specialty_dishes") or []]} for i, p in batch]
    with tempfile.TemporaryDirectory() as tmp:          # no project context: an empty working directory
        r = subprocess.run(["claude", "-p", "--no-session-persistence", "--tools", "", "--output-format", "json",
                            "--json-schema", json.dumps(SCHEMA)], input=PROMPT + json.dumps(items, ensure_ascii=False),
                           cwd=tmp, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True,
                           timeout=900)
    try:
        out = json.loads(r.stdout).get("structured_output") or {}
    except ValueError:
        out = {}
    with open(os.path.join(rawdir, "batch-%d-%d.json" % (int(time.time()), k)), "w") as fh:
        json.dump({"ids": [i for i, _ in batch], "reply": out, "rc": r.returncode,
                   "stderr": r.stderr[-500:]}, fh, ensure_ascii=False, indent=1)
    return out.get("lines") or []


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--city", choices=["nyc", "stl", "both"], default="both")
    ap.add_argument("--cards", default=os.path.expanduser("~/Desktop/qloo/private/fresh20-28oct"))
    ap.add_argument("--out", default=os.environ.get("UNSAID_LINES_DIR") or os.path.join(ROOT, "data", "lines"))
    ap.add_argument("--batch", type=int, default=40)
    ap.add_argument("--max-calls", type=int, default=60)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--force", action="store_true", help="ask again for places that already have a line")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    cities = ["nyc", "stl"] if args.city == "both" else [args.city]
    os.makedirs(os.path.join(args.out, ".raw"), exist_ok=True)
    places, missing = gather(cities, args.cards)
    print("places with Qloo text: %s (%d wanted ids not in the cache)" % (
        {c: len(v) for c, v in places.items()}, missing), flush=True)
    docs, todo = {}, []
    for c in cities:
        fp = os.path.join(args.out, "%s.json" % c)
        docs[c] = json.load(open(fp)) if os.path.exists(fp) and not args.force else {"lines": {}}
        docs[c].setdefault("lines", {})
        todo += [(c, i, p) for i, p in sorted(places[c].items())
                 if i not in docs[c]["lines"] and any(p.get(f) for f in FIELDS)]
    batches = [todo[k:k + args.batch] for k in range(0, len(todo), args.batch)][:args.max_calls]
    print("to ask: %d places in %d calls (cap %d)" % (len(todo), len(batches), args.max_calls), flush=True)
    if args.dry_run:
        return
    stats = {"asked": 0, "kept": 0, "rejected": 0, "missing": 0, "reasons": {}}

    def run(kb):
        k, b = kb
        return b, ask([(i, p) for _, i, p in b], os.path.join(args.out, ".raw"), k)

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for b, reply in ex.map(run, enumerate(batches)):
            by = {x.get("id"): x for x in reply if isinstance(x, dict)}
            for c, i, p in b:
                stats["asked"] += 1
                x = by.get(i)
                if not x:
                    stats["missing"] += 1
                    continue
                src = source_text(p)
                line = (x.get("line") or "").strip().rstrip(".")
                why = check_line(line, src)
                if why:
                    stats["rejected"] += 1
                    key = why.split(":")[0]
                    stats["reasons"][key] = stats["reasons"].get(key, 0) + 1
                    docs[c].setdefault("rejected", {})[i] = {"line": line, "why": why}
                    continue
                docs[c]["lines"][i] = {"line": line[:1].upper() + line[1:], "dishes": check_dishes(x.get("dishes"), src),
                                       "name": p.get("name")}
                stats["kept"] += 1
            print("  batch done: %d asked so far, %d kept, %d rejected, %d missing" % (
                stats["asked"], stats["kept"], stats["rejected"], stats["missing"]), flush=True)
    for c in cities:
        docs[c].update({"city": c, "built_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "method": (
            "condensed by Claude (claude -p) from Qloo's own text fields %s; every content word checked against the "
            "source; dishes verbatim" % ", ".join(FIELDS + ("specialty_dishes",)))})
        with open(os.path.join(args.out, "%s.json" % c), "w") as fh:
            json.dump(docs[c], fh, ensure_ascii=False, indent=1)
    rate = stats["rejected"] / float(max(1, stats["kept"] + stats["rejected"]))
    print("build_lines: asked %d, kept %d, rejected %d (%.1f%%: %s), no reply %d; calls %d -> %s" % (
        stats["asked"], stats["kept"], stats["rejected"], 100 * rate, stats["reasons"], stats["missing"],
        len(batches), ", ".join("%s %d lines" % (c, len(docs[c]["lines"])) for c in cities)))


if __name__ == "__main__":
    sys.exit(main())
