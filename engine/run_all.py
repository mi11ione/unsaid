"""Day-1 order: probes, K9, K1, K2a, K7, K8, K3 (+K2b), lineup, one query trace, then the matcher test.
  python3 -I run_all.py --fake        (today, no key)
  QLOO_API_KEY=... python3 -I run_all.py --walls walls.json
Prints only the verdict lines; full output and traces are in out/."""
import os, subprocess, sys

KIT = os.path.dirname(os.path.abspath(__file__))
extra = sys.argv[1:]
steps = [["probes.py"], ["k9_baseline.py"], ["k1_density.py"], ["k2a_lift.py"], ["k7_explain.py"], ["k8_closed.py"],
         ["k3_survivors.py"], ["lineup_eval.py"], ["run_query.py", "--city", "stl", "--set", "cedric"],
         ["tests/test_matcher.py"]]
os.makedirs(os.path.join(KIT, "out"), exist_ok=True)
for s in steps:
    args = [sys.executable, "-I", os.path.join(KIT, s[0])] + s[1:] + ([] if s[0].startswith("tests") else extra)
    p = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
    name = os.path.basename(s[0]).replace(".py", "")
    with open(os.path.join(KIT, "out", name + ".log"), "w") as f:
        f.write(p.stdout)
    keep = [l for l in p.stdout.splitlines() if any(k in l for k in ("K1 ", "K2a ", "K2b ", "K3 ", "K4 offline:", "K7 ", "K8 ",
            "K9 ", "Lineup eval", "two strangers", "rerun determinism", "because-line", "P1 ", "P2 ", "P4 ", "status "))]
    print("## %s (exit %d)" % (name, p.returncode))
    for l in keep:
        print("   " + l.strip())
