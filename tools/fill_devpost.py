#!/usr/bin/env python3
"""Fill the Devpost draft's ⟦X⟧ placeholders from the freeze snapshot (out/freeze/numbers.json) into a NEW file.

  python3 -I tools/fill_devpost.py                                  # ~/Desktop/qloo/devpost.md -> devpost.final.md
  python3 -I tools/fill_devpost.py --in README.md --out out/freeze/README.filled.md --whole   # a preview, any file
  python3 -I tools/fill_devpost.py --scan README.md site/*.html ...   # list every ⟦X⟧ left (exit 1 if any)

Rules (devpost.md's legend, UNSAID.md §6.0):
  * a value comes only from numbers.json (each with its source) or from the two known URLs; nothing is invented;
    a placeholder numbers.json has no value for stays as it is, and is listed as unfilled with the reason;
  * ⟦ROMAN_WHY⟧ (Roman's own words) and ⟦VIDEO_URL⟧ (his upload) are never filled;
  * ⟦IMG_SHARE⟧ is filled only when media/shots/share-1080x1350.png was rendered after the regenerated Cedric set
    (i.e. by this freeze's media step);
  * the draft's legend (everything before the first "## Elevator pitch") is dropped unless --whole.
It also checks the draft's hard-coded measured claims (gate A/B/E/F, k12) against numbers.json and prints any drift.
Refuses (exit 3) unless numbers.json's regeneration is current: its engine commit contains HEAD's last engine commit
and its priors hash equals data/priors now (freeze_numbers.py provenance); --allow-stale writes a labelled preview.
Never edits the input. Writes <out> and a machine-readable <logs>/fill.json (filled, unfilled, drift)."""
import argparse
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QLOO = os.path.dirname(ROOT)
KNOWN = {"LIVE_URL": ("https://unsaid-ang.pages.dev", "known URL (the flip)"),
         "REPO_URL": ("https://github.com/mi11ione/unsaid", "known URL (the flip)")}
ROMAN_ONLY = {"ROMAN_WHY": "Roman's own words only; never drafted",
              "VIDEO_URL": "Roman's upload"}
SHARE = os.path.join(ROOT, "media", "shots", "share-1080x1350.png")
PH = re.compile(r"⟦([A-Z][A-Z0-9_]*)⟧")


def num(x):
    if x is None:
        return None
    return str(int(x)) if float(x) == int(x) else "%.1f" % x


# Hard-coded measured claims in the draft: (label, regex with groups, [numbers.json gate paths]). Each group must equal
# the freeze's value (formatted like the text). A claim the draft no longer contains is reported as "absent".
CLAIMS = [
    ("gate A strangers", r"Their UNSAID sevens share \*\*(\d+)\*\*", ["A.strangers"]),
    ("gate A table", r"\*\*PASS\*\*: New York (\d+)/10, St\. Louis (\d+)/10; strangers share (\d+)",
     ["A.nyc_pass", "A.stl_pass", "A.strangers"]),
    ("gate B table", r"B · survivors \|[^|]*\| \*\*\w+\*\*: New York (\d+)/10, St\. Louis (\d+)/10",
     ["B.nyc_pass", "B.stl_pass"]),
    ("gate E bullet", r"named \*\*(\d+) of the (\d+) cards\*\* \(median (\d+) of 7\)", ["E.hits", "E.cards", "E.median"]),
    ("gate E table", r"\*\*PASS\*\*: (\d+) of 140, median (\d+)", ["E.hits", "E.median"]),
    # the k12 lines are placeholders now (⟦K12_*⟧, from numbers.json), so they cannot drift
    ("gate F bullet", r"cards in ([\d.]+) s median, ([\d.]+) s p90; the first crossed-out name on screen in ([\d.]+) s",
     ["F.p50", "F.p90", "F.first_name_p50"]),
    ("gate F table", r"\*\*PASS\*\*: p50 ([\d.]+) s, p90 ([\d.]+) s, first name ([\d.]+) s",
     ["F.p50", "F.p90", "F.first_name_p50"]),
]


def get(d, path):
    for k in path.split("."):
        if not isinstance(d, dict) or k not in d:
            return None
        d = d[k]
    return d


def same(text, val):
    if val is None:
        return None
    try:
        return abs(float(text) - float(val)) < 1e-9
    except ValueError:
        return str(text) == str(val)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--numbers", default=os.path.join(ROOT, "out", "freeze", "numbers.json"))
    ap.add_argument("--in", dest="src", default=os.path.join(QLOO, "devpost.md"))
    ap.add_argument("--out", default=os.path.join(QLOO, "devpost.final.md"))
    ap.add_argument("--whole", action="store_true", help="keep the whole file (default drops the draft's legend)")
    ap.add_argument("--allow-stale", action="store_true", help="fill even when the regeneration is stale (a preview; "
                    "the header says STALE)")
    ap.add_argument("--report", help="fill.json path (default: next to numbers.json, fill.json or fill.<name>.json)")
    ap.add_argument("--scan", nargs="+", metavar="FILE", help="only list every ⟦X⟧ left in these files (exit 1 if any)")
    a = ap.parse_args()
    if a.scan:
        left = 0
        for f in a.scan:
            for i, line in enumerate(open(f), 1):
                for k in PH.findall(line):
                    left += 1
                    print("  LEFT %s:%d ⟦%s⟧   %s" % (os.path.relpath(f, ROOT), i, k, line.strip()[:110]))
        print("scan: %d placeholders left in %d files" % (left, len(a.scan)))
        sys.exit(1 if left else 0)
    if os.path.abspath(a.src) == os.path.abspath(a.out):
        sys.exit("refusing: --out must be a new file, not the draft itself")
    N = json.load(open(a.numbers))
    # every number must come from THIS freeze's regeneration: re-check its stamp against the tree now
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import freeze_numbers as FN
    prov = FN.provenance(N.get("fresh_dir") or "")
    if prov["problems"] and not a.allow_stale:
        for pr in prov["problems"]:
            print("REFUSING to fill: %s" % pr, file=sys.stderr)
        print("Regenerate (./freeze.sh --from 2), or pass --allow-stale for a labelled preview.", file=sys.stderr)
        sys.exit(3)
    text = open(a.src).read()
    if not a.whole:
        i = text.find("\n## Elevator pitch")
        if i < 0:
            sys.exit("no '## Elevator pitch' heading in %s; pass --whole" % a.src)
        text = text[i + 1:]

    vals = {}
    for k, v in (N.get("placeholders") or {}).items():
        vals[k] = (v.get("value"), v.get("source", ""), v.get("note", ""))
    for k, (v, src) in KNOWN.items():
        vals[k] = (v, src, "")
    ced = os.path.join(N.get("fresh_dir") or "", "stl_stl-cedric.json")
    gen = os.path.getmtime(ced) if os.path.exists(ced) else float("inf")      # the share card must post-date the regen
    if os.path.exists(SHARE) and os.path.getmtime(SHARE) > gen:
        vals["IMG_SHARE"] = ("![UNSAID share card: Frankie Beverly & Maze · The Original Kings of Comedy · rib tips](%s)" % SHARE,
                             "media/render.sh share, rendered %s" % time.strftime(
                                 "%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(SHARE))), "")
    else:
        vals["IMG_SHARE"] = (None, "media/render.sh", "the share image was not rendered after this regeneration (step 7)")
    for k, why in ROMAN_ONLY.items():
        vals[k] = (None, "Roman", why)

    filled, unfilled = {}, {}

    def sub(m):
        k = m.group(1)
        v, src, note = vals.get(k, (None, "", "not in numbers.json"))
        if v is None or v == "":
            unfilled.setdefault(k, {"count": 0, "source": src, "why": note or "no value at this freeze"})["count"] += 1
            return m.group(0)
        filled.setdefault(k, {"value": v, "source": src, "count": 0})["count"] += 1
        return v

    # a value numbers.json marks "DELETE: ..." (⟦AGENT_QUOTE⟧ when its card moved) takes its whole line out; Roman decides
    deleted = {}
    for k, (v, src, note) in vals.items():
        if v is None and str(note).startswith("DELETE"):
            lines = []
            for line in text.split("\n"):
                if "⟦%s⟧" % k in line:
                    deleted[k] = note
                    line = "<!-- %s: line deleted by the freeze (%s); Roman decides -->" % (k, note.replace("--", "-"))
                lines.append(line)
            text = "\n".join(lines)
    out = PH.sub(sub, text)
    drift = []
    for label, rx, paths in CLAIMS:
        m = re.search(rx, out)
        want = [get(N.get("gates") or {}, p) for p in paths]
        if not m:
            drift.append({"claim": label, "status": "absent from the text"})
            continue
        got = list(m.groups())
        if all(w is None for w in want):
            drift.append({"claim": label, "status": "not measured at this freeze", "text": got})
            continue
        bad = [(g, w) for g, w in zip(got, want) if w is not None and not same(g, w)]
        if bad:
            drift.append({"claim": label, "status": "DRIFT", "text": got, "freeze": [num(w) if isinstance(w, (int, float)) else w for w in want]})

    stale = ("STALE PREVIEW (%s). " % "; ".join(prov["problems"])) if prov["problems"] else ""
    head = (stale and "<!-- %s-->\n" % stale) + ("<!-- Filled by tools/fill_devpost.py at %s from %s (freeze snapshot %s, git %s). Source: %s. "
            "Unfilled: %s. Strip the HTML comments before pasting into Devpost. -->\n\n" % (
                time.strftime("%Y-%m-%d %H:%M %Z"), os.path.relpath(a.numbers, ROOT), N.get("generated_at"),
                N.get("git_head"), a.src, ", ".join(sorted(unfilled)) or "none"))
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w") as f:
        f.write(head + out)

    rep = a.report or os.path.join(os.path.dirname(os.path.abspath(a.numbers)),
                                   "fill.json" if os.path.basename(a.src) == "devpost.md" else
                                   "fill.%s.json" % os.path.splitext(os.path.basename(a.src))[0])
    json.dump({"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "in": a.src, "out": a.out, "filled": filled,
               "unfilled": unfilled, "deleted": deleted, "drift": drift}, open(rep, "w"), indent=1, ensure_ascii=False)

    print("wrote %s (%d placeholders filled, %d kinds unfilled)" % (a.out, sum(v["count"] for v in filled.values()),
                                                                     len(unfilled)))
    for k, v in sorted(filled.items()):
        print("  filled   ⟦%s⟧ x%d = %s   [%s]" % (k, v["count"], v["value"][:90].replace("\n", " "), v["source"]))
    for k, v in sorted(unfilled.items()):
        print("  UNFILLED ⟦%s⟧ x%d: %s   [%s]" % (k, v["count"], v["why"], v["source"]))
    for k, note in sorted(deleted.items()):
        print("!" * 100)
        print("!!! ⟦%s⟧ DELETED from %s: %s. Roman decides." % (k, a.out, note))
        print("!" * 100)
    for d in drift:
        if d["status"] == "DRIFT":
            print("  DRIFT    %s: text says %s, the freeze measured %s" % (d["claim"], d["text"], d["freeze"]))
        else:
            print("  claim    %s: %s" % (d["claim"], d["status"]))
    print("fill report: %s" % rep)


if __name__ == "__main__":
    main()
