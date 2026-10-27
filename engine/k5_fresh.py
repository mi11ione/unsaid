"""Gate E · fresh asks (UNSAID.md §4, K5'). Real public questions, verbatim, never used in any wall (checked by hash),
asked of the three AIs per frozen set: the 20 city questions as posted, plus 4 with "I love {L1}, {L2} and {L3}."
appended. A card counts as named if any answer names it (matcher R1-R4 against the cards + the reverse check over the
raw text). PASS: median <= 1 of 7 cards named, over the frozen sets (20: 10 NYC + 10 STL). 0 Qloo calls when --cards
is given. Fills ⟦FA_Q⟧ ⟦FA_SETS⟧ ⟦FA_HITS⟧ ⟦FA_CARDS⟧ ⟦FA_MED⟧.

Inputs
  --fresh   data/fresh_asks.json  {"frozen_at", "cities": {"stl": [{"id", "text", "url", "posted"}], "nyc": [...]}}
            (also accepted: {"questions": [{"id", "city", "text", ...}]})
  --answers stored answers, JSON list or JSONL: {"set", "city", "question_id", "provider", "model", "asked_at",
            "names": [{"name"}], "raw"}            (the harness writes them; agent B)
  --cards   frozen cards: precompute.py output (a dir with index.json, or one JSON), else the engine runs now
  --walls   the walls file, for the never-in-a-wall hash check and the new-name rate
In --fake mode with no inputs, fake questions and fixture answers stand in, tagged [FAKE]."""
import glob, hashlib, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from unsaid import api, cli, engine as E, matcher as M, seeds as SD, walls as W  # noqa: E402

ap = cli.parser(__doc__)
ap.add_argument("--fresh", default=os.path.join(cli.DATA, "fresh_asks.json"))
ap.add_argument("--answers")
ap.add_argument("--cards")
args = ap.parse_args()
T = cli.tag(args)
print("== k5_fresh  %s" % ("[FAKE] fixture answers stand in for the fresh-ask run" if args.fake else "[LIVE] stored answers"))


def qhash(text):
    return hashlib.sha256(" ".join(M.norm(text).split()).encode()).hexdigest()


def load_questions():
    if os.path.exists(args.fresh):
        with open(args.fresh) as f:
            d = json.load(f)
        if "cities" in d:
            return {c: v for c, v in d["cities"].items()}, args.fresh
        out = {}
        for x in d.get("questions") or []:
            out.setdefault(x["city"], []).append(x)
        return out, args.fresh
    if args.fake:
        qs = {c: [{"id": "%s-q%02d" % (c, i), "text": "[FAKE] question %d about eating in %s" % (i, c), "url": None}
                  for i in range(1, 21)] for c in ("nyc", "stl")}
        return qs, "[FAKE] generated"
    raise SystemExit("no %s yet (agent D collects, Roman freezes). Run with --fake to exercise the code path." % args.fresh)


def load_answers():
    if args.answers:
        with open(args.answers) as f:
            txt = f.read()
        try:
            d = json.loads(txt)
            return d if isinstance(d, list) else d.get("answers", [])
        except ValueError:
            return [json.loads(l) for l in txt.splitlines() if l.strip()]
    if args.fake:   # fixture "fresh" answers (one model from memory) stand in for every set
        out = []
        for city in ("nyc", "stl"):
            for sid, _ in SD.SEED_SETS[city]:
                for a in W.fresh_for(city):
                    out.append(dict(a, set=sid, city=city, question_id="fake", provider="exp-memory"))
        return out
    raise SystemExit("--answers is required live (the harness stores the fresh-ask answers)")


def load_cards():
    if args.cards:
        files = [os.path.join(args.cards, "index.json")] if os.path.isdir(args.cards) else [args.cards]
        out = {}
        for fp in files:
            with open(fp) as f:
                d = json.load(f)
            for s in d.get("sets", []):
                res = s.get("result")
                if res is None and s.get("file"):
                    with open(os.path.join(os.path.dirname(fp), s["file"])) as g:
                        res = json.load(g).get("result")
                out[(s["city"], s["id"])] = [p["name"] for p in (res or {}).get("picks", [])]
        return out, "frozen cards from %s" % args.cards
    out = {}
    q = cli.client(args, "k5_fresh")
    for city in cli.cities(args):
        for sid, spec in cli.sets(args, city):
            ch, _ = cli.chips(q, spec)
            if ch is None:
                continue
            r = api.run_unsaid(SD.CITY_QUERY[city][0], ch, walls_path=args.walls,
                               mode="fake" if args.fake else "live", qloo=q, set_id=sid, street_check=False,
                               gemini=False, use_cache=not args.no_cache)
            out[(city, sid)] = [p["name"] for p in r["picks"]]
    return out, "cards computed now (%d Qloo calls)" % len(q.trace)


questions, qsrc = load_questions()
answers = load_answers()
cards, csrc = load_cards()

# never used in any wall, by hash
wall_hashes = set()
if args.walls:
    for w in W.load_file(args.walls).get("walls", []):
        for a in w.get("answers") or []:
            for k in ("phrasing_text", "phrasing", "prompt"):
                if a.get(k):
                    wall_hashes.add(qhash(a[k]))
collide = [x["id"] for c in questions.values() for x in c if qhash(x.get("text", "")) in wall_hashes]
print("  questions: %s (%s); hash check vs walls: %d collisions%s" % (
    ", ".join("%s %d" % (c.upper(), len(v)) for c, v in sorted(questions.items())), qsrc, len(collide), T))

per_set, pooled_named, pooled_total, new_names, all_names = [], 0, 0, 0, 0
for (city, sid), names in sorted(cards.items()):
    ans = [a for a in answers if a.get("set") == sid and W._ckey(a.get("city")) == city]
    if not names:
        continue
    pool = [{"entity_id": n, "name": n} for n in names]
    named = set()
    for a in ans:
        st, _ = M.match_wall([n["name"] if isinstance(n, dict) else n for n in a.get("names") or []], pool, None)
        named |= set(st)
    rix = E.reverse_index(ans)
    for n in names:
        if E.reverse_hit(n, rix) is not None:
            named.add(n)
    wall_norms = {M.norm(x) for x in W.names(W.wall_for(city, sid, args.walls))}
    fresh_norms = {M.norm(n["name"] if isinstance(n, dict) else n) for a in ans for n in a.get("names") or []}
    new_names += len(fresh_norms - wall_norms)
    all_names += len(fresh_norms)
    per_set.append(len(named))
    pooled_named += len(named)
    pooled_total += len(names)
    print("    %s/%-8s %d answers: %d of %d cards named%s%s" % (
        city.upper(), sid, len(ans), len(named), len(names), (" (" + ", ".join(sorted(named)) + ")") if named else "", T))
med = cli.median(per_set)
ok = bool(per_set) and med <= 1 and not collide
print("  pooled: %d of %d cards named; median per set %s over %d sets; new-name rate %s (%s)%s" % (
    pooled_named, pooled_total, cli.f(med, 1), len(per_set), cli.f(new_names / float(all_names) if all_names else None),
    csrc, T))
print("  ⟦FA_Q⟧ = %s · ⟦FA_SETS⟧ = %d · ⟦FA_HITS⟧ = %d · ⟦FA_CARDS⟧ = %d · ⟦FA_MED⟧ = %s%s" % (
    "/".join(str(len(v)) for _, v in sorted(questions.items())), len(per_set), pooled_named, pooled_total,
    cli.f(med, 1), T))
print("E fresh asks: median %s of 7 (gate <=1, %d sets) -> %s%s" % (cli.f(med, 1), len(per_set), cli.verdict(ok), T),
      "| if FAIL: add the gem phrasings' second pass and rerun once; then cut the dare-as-promise")
