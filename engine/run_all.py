"""Day-1 order: probes, K9, K1, gate A (k2a), K7, K8, gate B (k3), one query + gate C (run_query), gate E (k5),
gate D (k10, 0 Qloo calls), gate F (k11), the try-these precompute (to a temp dir in fake mode), then the matcher test.
  python3 -I run_all.py --fake        (no key: every code path, [FAKE] tags)
  QLOO_API_KEY=... python3 -I run_all.py --walls walls.json --budget 1200
--budget N is shared across the scripts: each one gets what is left, prints QLOO_NETWORK_CALLS=n, and the run stops
before the (N+1)-th live Qloo call (cache hits are free).
Prints the verdict lines; full output and traces are in out/ (gitignored). The last line is run_all's own verdict:
PASS when every script ran to completion (gate verdicts are reported above it, PASS or FAIL as measured)."""
import os, re, shutil, subprocess, sys, tempfile

KIT = os.path.dirname(os.path.abspath(__file__))
extra = sys.argv[1:]
budget = None
if "--budget" in extra:
    i = extra.index("--budget")
    budget = int(extra[i + 1])
    extra = extra[:i] + extra[i + 2:]
used = 0
fake = "--fake" in extra
steps = [["probes.py"], ["k9_baseline.py"], ["k1_density.py"], ["k2a_lift.py"], ["k7_explain.py"], ["k8_closed.py"],
         ["k3_survivors.py"], ["k4_relabel.py", "--export", "--score"] if fake else ["k4_relabel.py", "--export"],
         ["run_query.py", "--city", "stl", "--set", "cedric"], ["k5_fresh.py"],
         ["k10_meter.py"], ["k11_latency.py"], ["tests/test_matcher.py"], ["tests/test_api.py"]]
TMP = tempfile.mkdtemp(prefix="unsaid-try-")
if fake:   # live precompute writes Qloo data: run it by hand with an --out outside git
    steps.insert(-2, ["precompute.py", "--out", os.path.join(TMP, "try-these")])
KEYS = ("Probes ", "K1 ", "A taste", "two strangers", "⟦STRANGERS⟧", "K7 ", "K8 ", "K9 ", "B survivors", "cap overlap median",
        "C not a cap", "run_query:", "E fresh", "⟦FA_", "D meter", "⟦M_", "F speed", "⟦P50", "precompute:",
        "K4 offline:", "K4 offline overall", "K4 live", "⟦LABELLED", "  status ", "  floor:", "API contract")
os.makedirs(os.path.join(KIT, "out"), exist_ok=True)
ran, crashed = 0, []
for s in steps:
    if s[0].startswith("tests"):
        args = [sys.executable, "-I", os.path.join(KIT, s[0])]
    else:
        drop_city = "--city" in s
        ex = [a for i, a in enumerate(extra) if not (drop_city and (a == "--city" or (i and extra[i - 1] == "--city")))]
        args = [sys.executable, "-I", os.path.join(KIT, s[0])] + s[1:] + ex
        if budget is not None:
            args += ["--budget", str(max(0, budget - used))]
    p = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
    name = os.path.basename(s[0]).replace(".py", "")
    with open(os.path.join(KIT, "out", name + (".fake" if fake else "") + ".log"), "w") as f:
        f.write(p.stdout)
    tb = "Traceback (most recent call last)" in p.stdout
    # run_query exits 1 when it has fewer than 7 cards; that is a verdict, not a crash
    if tb or (p.returncode != 0 and not name.startswith("test_") and name != "run_query"):
        crashed.append(name)
    elif name.startswith("test_") and p.returncode != 0:
        crashed.append(name)
    ran += 1
    n = sum(int(x) for x in re.findall(r"QLOO_NETWORK_CALLS=(\d+)", p.stdout))
    used += n
    over = "BUDGET EXCEEDED" in p.stdout
    if over and name not in crashed:
        crashed.append(name)
    keep = [l for l in p.stdout.splitlines() if any(k in l for k in KEYS)]
    print("## %s (exit %d) · Qloo network calls %d · running total %d%s" % (
        name, p.returncode, n, used, (" of %d budgeted" % budget) if budget is not None else ""))
    for l in keep:
        print("   " + l.strip())
    if tb or over:
        print("   " + "\n   ".join(p.stdout.strip().splitlines()[-4:]))
    if over:
        print("   stopped: --budget %d reached" % budget)
        break
shutil.rmtree(TMP, ignore_errors=True)
ok = not crashed
print("run_all: %d of %d scripts ran to completion%s; %d Qloo network calls%s -> %s%s" % (
    ran - len(crashed), len(steps), (" (stopped/crashed: %s)" % ", ".join(crashed)) if crashed else "", used,
    (" of %d budgeted" % budget) if budget is not None else "", "PASS" if ok else "FAIL", " [FAKE]" if fake else ""))
sys.exit(0 if ok else 1)
