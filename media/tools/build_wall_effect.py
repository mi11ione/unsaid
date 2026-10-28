"""The site's "Is this just obscure places?" table, from the same stored files freeze_numbers.py reads for the Devpost
(K12_<ARM>_FRESH_U, K12_<ARM>_FIT_MED, K14_KAPPA): out/freeze/k12_wall_effect.json (engine/k12_wall_effect.py --frozen,
Baselines) and engine/k14_label.json (used only when its k12_sha256 matches that run). Adds an "arms" block and
"kappa" to site/data/wall_effect.json; counts only.
  python3 -I media/tools/build_wall_effect.py        (deploy-site.sh runs it when the k12 run exists)"""
import hashlib, importlib.util, json, os, sys

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
spec = importlib.util.spec_from_file_location("freeze_numbers", os.path.join(ROOT, "tools", "freeze_numbers.py"))
FN = importlib.util.module_from_spec(spec)
spec.loader.exec_module(FN)
kp = os.path.join(FN.LOGS, "k12_wall_effect.json")
if not os.path.exists(kp):
    sys.exit("no k12 run at %s" % kp)
rows = [r for r in json.load(open(kp)) if "arms" in r and "random" in r]
if not rows:
    sys.exit("k12 run has no baselines (arms/random)")
B = FN.k12_baselines(rows)
pct = lambda x: None if x is None else round(100 * x)  # noqa: E731
arms = {}
for k in ("plain", "score_only", "random", "unsaid"):
    b = B[(k, "all")]
    arms[k] = {"named": round(b["fresh"], 1), "cards": b["cards"], "fit_med": pct(b["fit_med"])}
k14p = os.path.join(ROOT, "engine", "k14_label.json")
k14 = json.load(open(k14p)) if os.path.exists(k14p) else None
sha = hashlib.sha256(open(kp, "rb").read()).hexdigest()
kappa = round(k14["kappa"], 2) if k14 and k14.get("k12_sha256") == sha and k14.get("kappa") is not None else None
out = os.path.join(ROOT, "site", "data", "wall_effect.json")
d = json.load(open(out)) if os.path.exists(out) else {}
d["arms_"] = ("held-out fresh questions only (never used to build the list), one per-place verdict over U, pooled over "
              "%d sets: named = cards some AI named (random: the mean over 200 draws of 7 strike survivors); fit_med = "
              "median fit percentile (100 = fits you best). Same source as freeze_numbers K12_<ARM>_FRESH_U / _FIT_MED; "
              "kappa = k14 blind labeller vs the matcher (K14_KAPPA), null unless it labelled this k12 run." % len(rows))
d["arms"] = arms
d["kappa"] = kappa
json.dump(d, open(out, "w"), indent=1, ensure_ascii=False)
open(out, "a").write("\n")
print("site/data/wall_effect.json arms:", {k: (v["named"], v["fit_med"]) for k, v in arms.items()}, "kappa", kappa)
