"""K14 · an independent labeller for k12's held-out "named" check.

k12 counts a card as named by the held-out fresh asks with the same matcher that does the strike (R1-R5 + the reverse
check). A methods judge asked for a check that does not share that code. Here a separate model reads each answer and
says, blind, whether it names each candidate venue.

Pairs (held-out answer x place), from k12's stored run (out/k12_wall_effect.json, same sets, same answers):
  flagged  the matcher's loose prefilter fires: a distinctive token of the place's name is in the answer, or a name
           the answer lists scores fuzzy >= 0.6 against it. Every flagged pair is labelled: the cards of every k12 arm
           (plain, PLAIN+RULES, score-only, UNSAID) and every strike survivor (RANDOM-7's population).
  sample   a seeded 10% of the unflagged pairs between those answers and the arms' cards (what the prefilter misses).
One `claude -p` call per answer (default model, no tools, no MCP, no session), its candidates numbered and shuffled,
never told the matcher's verdict or the arm: "Does this answer name this specific venue (same place, not a different
place with a similar name)?" -> JSON [{"i", "named", "quote"}]. A "named" whose quote is not in the answer text is
recorded (quote_ok false) and still counted as the labeller said.

Outputs: out/k14_labels.jsonl (one line per pair, with names: gitignored), out/k14_label.json and --public-md
(counts only): agreement with the matcher (precision, recall; the sample weighted back to the unflagged population)
and the held-out AI-named cards per arm by the labeller, pooled and per city, next to k12's.

  python3 -I k14_label.py --dry-run                 # the pairs and the calls it would make
  python3 -I k14_label.py --public-md k14_label.md  # label (resumable; <= --max-calls claude -p calls)
"""
import argparse, collections, hashlib, json, os, random, re, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from unsaid import engine as E, matcher as M  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--k12", default=os.path.join(HERE, "out", "k12_wall_effect.json"))
ap.add_argument("--fresh", default=os.path.join(os.path.dirname(HERE), "harness", "runs", "fresh.jsonl"))
ap.add_argument("--labels", default=os.path.join(HERE, "out", "k14_labels.jsonl"))
ap.add_argument("--sample", type=float, default=0.10)
ap.add_argument("--chunk", type=int, default=40, help="candidates per call")
ap.add_argument("--max-calls", type=int, default=600)
ap.add_argument("--workers", type=int, default=4)
ap.add_argument("--model", help="claude -p --model (default: the CLI's default)")
ap.add_argument("--dry-run", action="store_true")
ap.add_argument("--first", type=int, help="only the first N calls (a trial)")
ap.add_argument("--public-md")
args = ap.parse_args()
ARMS = ("plain", "plain_rules", "score_only", "unsaid")
CITY = {"stl": "St. Louis", "nyc": "New York City"}

rows = json.load(open(args.k12))
fresh = {}
for line in open(args.fresh):
    if line.strip():
        r = json.loads(line)
        if r.get("status") != "failed" and not r.get("fake"):
            fresh[r["id"]] = dict(r, names=r.get("names") or r.get("places") or [])


def answer_tokens(a):
    return set(M.norm(E.answer_text(a)).split())


def matcher_hits(r, a):
    """k12's per-place verdict for ONE answer, over the set's whole U (k12.named_ids, verbatim)."""
    ids, name_of = sorted(r["U_names"]), r["U_names"]
    pool = [{"entity_id": i, "name": name_of.get(i) or ""} for i in ids]
    veto = set(r.get("veto") or [])
    raws = [n["name"] if isinstance(n, dict) else n for n in a.get("names") or []]
    st, _ = M.match_wall([x for x in raws if x not in veto], pool, None) if raws else ({}, {})
    rix = E.reverse_index([a])
    return set(st) | {i for i in ids if E.reverse_hit(name_of.get(i) or "", rix) is not None}


def sampled(aid, pid):
    h = int(hashlib.sha256(("k14:%s:%s" % (aid, pid)).encode()).hexdigest()[:8], 16)
    return h / float(0xFFFFFFFF) < args.sample


# ---------------------------------------------------------------- pairs
pairs = {}            # (aid, pid) -> {...}
tok_cache, unflagged = {}, set()
for r in rows:
    arm_ids = {i for k in ARMS for i in r["arms"][k]["ids"]}
    cand = arm_ids | set(r["S_ids"])
    for aid in r["fresh_ids"]:
        a = fresh.get(aid)
        if a is None:
            continue
        toks = tok_cache.setdefault(aid, answer_tokens(a))
        hits = matcher_hits(r, a)
        listed = [n["name"] if isinstance(n, dict) else n for n in a.get("names") or []]
        for pid in cand:
            name = r["U_names"].get(pid) or ""
            flag = None
            if any(t in toks for t in M.distinctive(name)):
                flag = "token"
            elif listed and max(E.fuzzy_score(x, name) for x in listed) >= 0.6:
                flag = "fuzzy"
            elif pid in arm_ids:
                unflagged.add((aid, pid))
                if sampled(aid, pid):
                    flag = "sample"
            if flag is None:
                continue
            p = pairs.setdefault((aid, pid), {"answer": aid, "place": pid, "name": name,
                                              "where": r.get("U_where", {}).get(pid, ""), "city": r["city"],
                                              "flag": flag, "matcher": pid in hits, "sets": []})
            p["sets"].append(r["set"])

unflagged -= set(pairs) - {k for k, p in pairs.items() if p["flag"] == "sample"}
n_unflagged = len(unflagged)
done = {}
if os.path.exists(args.labels):
    for line in open(args.labels):
        if line.strip():
            x = json.loads(line)
            done[(x["answer"], x["place"])] = x
todo = collections.defaultdict(list)
for k, p in pairs.items():
    if k not in done:
        todo[p["answer"]].append(p)
jobs = []
for aid, ps in sorted(todo.items()):
    random.Random("k14-order:" + aid).shuffle(ps)
    for j in range(0, len(ps), args.chunk):
        jobs.append((aid, ps[j:j + args.chunk]))
by_flag = collections.Counter(p["flag"] for p in pairs.values())
print("== k14_label: %d pairs (%s) over %d answers; unflagged arm pairs %d (sampled %.0f%%); %d labelled, %d calls to go"
      % (len(pairs), ", ".join("%s %d" % kv for kv in sorted(by_flag.items())), len({p["answer"] for p in pairs.values()}),
         n_unflagged, 100 * args.sample, len(done), len(jobs)))
if args.first:
    jobs = jobs[:args.first]
if len(jobs) > args.max_calls:
    raise SystemExit("refusing: %d calls > --max-calls %d (raise --chunk)" % (len(jobs), args.max_calls))

PROMPT = """Below is an AI assistant's answer to a question someone posted about where to eat or drink in {city}. After it is a numbered list of venues, each with a name and an address.

For each venue, decide: does the answer name this specific venue? Count it only if it is the same place: not a different place with a similar name, not a word that merely appears in the venue's name, not a street, neighbourhood or dish.

Reply with only JSON, no other text: an array with one object per venue, in list order, like {{"i": 1, "named": false, "quote": ""}}. "quote" is the exact words from the answer that name the venue when named is true, else "".

=== ANSWER ===
{answer}
=== END ANSWER ===

=== VENUES ===
{venues}
=== END VENUES ==="""
ENV = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_CODE_", "CLAUDECODE", "CLAUDE_PID"))
       and k not in ("QLOO_API_KEY", "GEMINI_API_KEY", "RENDER_API_KEY", "PROXY_SECRET", "UNSAID_TOKEN")}
SCRATCH = os.path.join(HERE, "out", "k14_cwd")


def ask(job):
    aid, ps = job
    a = fresh[aid]
    text = (a.get("raw") or E.answer_text(a))[:24000]
    venues = "\n".join("%d. %s (%s)" % (k + 1, p["name"], p["where"] or "address unknown") for k, p in enumerate(ps))
    cmd = ["claude", "-p", PROMPT.format(city=CITY.get(a.get("city"), a.get("city")), answer=text, venues=venues),
           "--output-format", "json", "--tools", "", "--strict-mcp-config", "--no-session-persistence",
           "--disable-slash-commands", "--setting-sources", "local"]
    if args.model:
        cmd += ["--model", args.model]
    for attempt in range(2):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=300, env=ENV, cwd=SCRATCH,
                                 stdin=subprocess.DEVNULL)
            res = json.loads(out.stdout)
            body = res.get("result") or ""
            got = json.loads(body[body.index("["):body.rindex("]") + 1])
            model = (list((res.get("modelUsage") or {}).keys()) or [None])[0]
            break
        except Exception as e:  # malformed reply or CLI hiccup: one retry, then the pairs stay unlabelled
            got, model, err = None, None, "%s: %s" % (type(e).__name__, str(e)[:120])
    if got is None:
        print("  [k14] %s: no labels (%s)" % (aid, err), file=sys.stderr)
        return []
    norm_text = " ".join(M.norm(text).split())
    lab = []
    for x in got:
        try:
            k = int(x.get("i")) - 1
        except (TypeError, ValueError):
            continue
        if not 0 <= k < len(ps):
            continue
        p = ps[k]
        q = str(x.get("quote") or "")
        lab.append(dict({kk: p[kk] for kk in ("answer", "place", "name", "city", "flag", "matcher", "sets")},
                        named=bool(x.get("named")), quote=q[:200],
                        quote_ok=(not x.get("named")) or bool(q and " ".join(M.norm(q).split()) in norm_text),
                        model=model, at=time.strftime("%Y-%m-%dT%H:%M:%S%z")))
    return lab


if args.dry_run:
    print("dry run: no calls")
    sys.exit(0)
os.makedirs(SCRATCH, exist_ok=True)
with open(args.labels, "a") as f, ThreadPoolExecutor(max_workers=args.workers) as ex:
    for n, lab in enumerate(ex.map(ask, jobs), 1):
        for x in lab:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
            done[(x["answer"], x["place"])] = x
        f.flush()
        if n % 20 == 0:
            print("  %d of %d calls" % (n, len(jobs)))

# ---------------------------------------------------------------- agreement
lab = {k: v for k, v in done.items() if k in pairs}
w = {"token": 1.0, "fuzzy": 1.0, "sample": 1.0 / args.sample}
cm = collections.Counter()
for k, x in lab.items():
    cm[(x["matcher"], x["named"], "w")] += w[pairs[k]["flag"]]
    cm[(x["matcher"], x["named"], "n")] += 1
TP, FP, FN, TN = (cm[(m, l, "w")] for m, l in ((True, True), (True, False), (False, True), (False, False)))
prec = TP / (TP + FP) if TP + FP else None
rec = TP / (TP + FN) if TP + FN else None
agree = (TP + TN) / (TP + FP + FN + TN) if lab else None
kappa = None
tot = TP + FP + FN + TN
if tot:
    pe = ((TP + FP) * (TP + FN) + (FN + TN) * (FP + TN)) / (tot * tot)
    kappa = (agree - pe) / (1 - pe) if pe < 1 else None
sample_named = sum(1 for k, x in lab.items() if pairs[k]["flag"] == "sample" and x["named"])
sample_n = sum(1 for k in lab if pairs[k]["flag"] == "sample")
bad_quote = sum(1 for x in lab.values() if x["named"] and not x["quote_ok"])

# ---------------------------------------------------------------- held-out named per arm, by the labeller
named_by = collections.defaultdict(set)        # set id -> places the labeller says a held-out answer names
for (aid, pid), x in lab.items():
    if x["named"]:
        for sid in x["sets"]:
            named_by[sid].add(pid)


def arm_counts(rs):
    out = {}
    for k in ARMS:
        out[k] = {"labeller": sum(1 for r in rs for i in r["arms"][k]["ids"] if i in named_by[r["set"]]),
                  "matcher": sum(r["arms"][k]["fresh"] for r in rs), "cards": 7 * len(rs)}
    lab_r = 0.0
    for r in rs:
        S = r["S_ids"]
        rng = random.Random("k12-random7:" + r["set"])
        draws = [rng.sample(S, min(7, len(S))) for _ in range(r["random"]["draws"])]
        lab_r += sum(sum(1 for i in d if i in named_by[r["set"]]) for d in draws) / float(len(draws))
    out["random"] = {"labeller": round(lab_r, 2), "matcher": round(sum(r["random"]["fresh_mean"] for r in rs), 2),
                     "cards": 7 * len(rs)}
    return out


ARM_COUNTS = {"all": arm_counts(rows)}
for c in sorted({r["city"] for r in rows}):
    ARM_COUNTS[c] = arm_counts([r for r in rows if r["city"] == c])
calls = len({x["answer"] for x in lab.values()})
res = {"pairs": len(pairs), "labelled": len(lab), "flags": dict(by_flag), "unflagged_arm_pairs": n_unflagged,
       "sample_rate": args.sample, "sample_named": sample_named, "sample_n": sample_n,
       "confusion_weighted": {"tp": round(TP, 1), "fp": round(FP, 1), "fn": round(FN, 1), "tn": round(TN, 1)},
       "confusion_raw": {"%s_%s" % ("m" if m else "notm", "l" if l else "notl"): cm[(m, l, "n")]
                         for m in (True, False) for l in (True, False)},
       "precision": prec, "recall": rec, "agreement": agree, "kappa": kappa, "named_quote_not_found": bad_quote,
       "models": sorted({x.get("model") or "?" for x in lab.values()}), "arms": ARM_COUNTS}
res["k12_sha256"] = hashlib.sha256(open(args.k12, "rb").read()).hexdigest()   # which k12 run these labels are for
json.dump(res, open(os.path.join(HERE, "out", "k14_label.json"), "w"), indent=1)
if args.public_md:                                   # the same counts beside the md, committed (no names in it)
    json.dump(res, open(os.path.splitext(args.public_md)[0] + ".json", "w"), indent=1)


def f(x, nd=2):
    return "n/a" if x is None else "%.*f" % (nd, x)


print("  labelled %d of %d pairs (%s); matcher vs labeller: precision %s, recall %s, agreement %s, kappa %s; "
      "sampled unflagged pairs named: %d of %d; named with a quote not in the text: %d" % (
          len(lab), len(pairs), ", ".join(res["models"]), f(prec), f(rec), f(agree, 3), f(kappa), sample_named,
          sample_n, bad_quote))
for k in ARMS + ("random",):
    a = ARM_COUNTS["all"][k]
    print("  %-11s held-out named: labeller %s · matcher %s of %d (%s)" % (
        k, a["labeller"], a["matcher"], a["cards"], " · ".join("%s labeller %s / matcher %s" % (
            c.upper(), ARM_COUNTS[c][k]["labeller"], ARM_COUNTS[c][k]["matcher"]) for c in sorted(ARM_COUNTS) if c != "all")))
if args.public_md:
    LBL = {"plain": "Qloo's plain top 7", "plain_rules": "PLAIN+RULES", "score_only": "score-only (no strike)",
           "unsaid": "UNSAID", "random": "RANDOM-7 (mean of k12's draws)"}
    cities = [c for c in sorted(ARM_COUNTS) if c != "all"]
    with open(args.public_md, "w") as fh:
        fh.write("# K14 · an independent labeller for the held-out \"named\" check\n\n")
        fh.write("A separate model (`claude -p`, %s, no tools) read each held-out fresh-ask answer and said, blind, "
                 "whether it names each candidate venue (same place, not a similar name). Candidates: every pair the "
                 "matcher's loose prefilter flags (a distinctive name token in the answer, or fuzzy >= 0.6), over the "
                 "cards of every k12 arm and every strike survivor, plus a seeded %d%% sample of the unflagged arm pairs. "
                 "%d pairs labelled over %d answers. Counts only: names stay in engine/out (gitignored).\n\n" % (
                     ", ".join(res["models"]), round(100 * args.sample), len(lab), calls))
        fh.write("**Matcher vs labeller** (the sample weighted back to all unflagged pairs): precision %s, recall %s, "
                 "agreement %s, Cohen's kappa %s. Raw: matcher yes and labeller yes %d, matcher yes and labeller no %d, "
                 "matcher no and labeller yes %d, both no %d. Sampled unflagged pairs the labeller calls named: %d of %d. "
                 "Named with a quote not found in the answer: %d.\n\n" % (
                     f(prec), f(rec), f(agree, 3), f(kappa), cm[(True, True, "n")], cm[(True, False, "n")],
                     cm[(False, True, "n")], cm[(False, False, "n")], sample_named, sample_n, bad_quote))
        fh.write("| arm | held-out AI-named, labeller | matcher (k12) | %s |\n|---|---:|---:|%s\n" % (
            " | ".join("%s labeller / matcher" % c.upper() for c in cities), "---:|" * len(cities)))
        for k in ARMS + ("random",):
            a = ARM_COUNTS["all"][k]
            fh.write("| %s | %s of %d | %s | %s |\n" % (LBL[k], a["labeller"], a["cards"], a["matcher"], " | ".join(
                "%s / %s" % (ARM_COUNTS[c][k]["labeller"], ARM_COUNTS[c][k]["matcher"]) for c in cities)))
    print("  table: %s" % args.public_md)
