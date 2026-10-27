"""README call trace, generated from a real run (never hand-written). Template described in engine-v3.md §13."""
import re
import time
from collections import OrderedDict

from unsaid import matcher as M

STEP_DOC = OrderedDict([
    ("C1 city", "locality, region checked against input"),
    ("C2 love", "entity ID per love (exact name first)"),
    ("C2 love tag", "tag ID for a dish/drink love"),
    ("C4 pool", "taste pool P, server order = taste rank"),
    ("C5 baseline", "no-signal rank of every member of U (same filters)"),
    ("C7 name", "wall name -> Qloo ID, city-scoped"),
    ("C6 drop", "drop-one rank over S"),
])


def short_url(u):
    """Long ID lists shown as first two + count, so the trace stays readable."""
    def cut(m):
        ids = m.group(2).split(",")
        return m.group(1) + (",".join(ids[:2]) + ",…(+%d)" % (len(ids) - 2) if len(ids) > 3 else m.group(2))
    return re.sub(r"((?:filter\.results\.entities|filter\.exclude\.entities|signal\.interests\.entities)=)([^&]+)", cut, u)


def _group(trace):
    g = OrderedDict()
    for r in trace:
        key = next((k for k in STEP_DOC if r["label"].startswith(k)), r["label"])
        x = g.setdefault(key, {"n": 0, "net": 0, "ms": 0, "ex": r["url"], "res": 0})
        x["n"] += 1
        x["net"] += 0 if r["cache"] else 1
        x["ms"] += r["ms"]
        x["res"] += r["n"] or 0
    return g


def markdown(res, q, city_label, loves_spec, wall, fake):
    d = res["diag"]
    R = res.get("_R") or {}
    L = []
    L.append("# UNSAID call trace%s" % (" [FAKE: canned responses, numbers prove code paths only]" if fake else ""))
    L.append("")
    L.append("Query: **%s** · loves: %s · engine v3 · %s · base `%s`" % (
        city_label, ", ".join(t for t, _ in loves_spec), time.strftime("%Y-%m-%d %H:%M"), q.base))
    L.append("")
    L.append("## 1. Every call")
    L.append("")
    L.append("| step | calls (network / cache) | sum ms | results | what it became | example request (`X-Api-Key` header, never in the URL) |")
    L.append("|---|---|---|---|---|---|")
    for k, x in _group(q.trace).items():
        L.append("| %s | %d (%d / %d) | %d | %d | %s | `%s` |" % (k, x["n"], x["net"], x["n"] - x["net"], x["ms"], x["res"],
                                                             STEP_DOC.get(k, ""), short_url(x["ex"])))
    L.append("")
    L.append("Totals: %d calls, %d over the network, %d from the content-hash cache." % (
        len(q.trace), q.calls["network"], q.calls["cache"]))
    L.append("")
    L.append("## 2. The set every rank is taken over")
    L.append("")
    dr = d.get("drops", {})
    L.append("P = %d places from the taste call (restaurant ∪ bar, rating ≥ 4 server side, seed places excluded). "
             "U = %d after the client floor (closed %d, rating < 4.3: %d, no rating %d). Every rank on a card is a rank "
             "inside this one U. Paging: %s." % (d.get("P", 0), d.get("U", 0), dr.get("closed", 0), dr.get("rating", 0),
                                                 dr.get("no_rating", 0), (d.get("pool") or {}).get("paging")))
    L.append("")
    L.append("## 3. Leakage panel (is this taste, or just fame?)")
    L.append("")
    b = d.get("baseline_rescore") or {}
    rows = [
        ("Spearman(taste rank, city rank) over U", d.get("rho_taste_base"), "≤ 0.90 means taste moves the order (K2a)"),
        ("Spearman(taste rank, popularity rank)", d.get("rho_taste_pop"), "popularity leakage; ρ² = share of the taste order explained by fame"),
        ("Spearman(no-signal rank, popularity rank)", d.get("rho_nosignal_pop"), "≥ 0.98: the city order *is* popularity"),
        ("AUC(popularity → named by an AI)", d.get("auc_pop_struck"), "0.5 = the AIs' wall is unrelated to popularity"),
        ("wall ∩ popularity cap of the same size", d.get("popcap_overlap"), "≤ 0.80: the wall is not just a popularity cut (K2b)"),
        ("baseline rescoring coverage / anchor drift", "%s / %s" % (_f(b.get("coverage")), _f(b.get("drift"), 4)),
         "all IDs back, scores merge across chunks"),
        ("explainability warning rate over U", d.get("explain_warn_rate"), "< 0.30 (K7)"),
    ]
    L.append("| measure | value | reading |")
    L.append("|---|---|---|")
    for a, v, c in rows:
        L.append("| %s | %s | %s |" % (a, v if isinstance(v, str) else _f(v), c))
    agg = (d.get("explain_agg") or {}).get("shares", {}).get("top_10") or {}
    if agg:
        L.append("")
        L.append("What drives the top 10 (aggregate explainability): " + " · ".join(
            "%s %.2f" % kv for kv in sorted(agg.items(), key=lambda kv: -kv[1])))
    L.append("")
    L.append("## 4. The wall")
    L.append("")
    w = d.get("wall", {})
    L.append("%d answers, %d distinct names (source: %s). Struck in U: %d. Name status: %s." % (
        w.get("answers", 0), w.get("names", 0), w.get("source"), w.get("struck", 0),
        ", ".join("%s %d" % kv for kv in sorted((w.get("status") or {}).items()))))
    L.append("")
    L.append("S = U − struck = %d. Kept (holds in ≥ n−1 drop-one runs) = %d. Flags: %s. Status: **%s**." % (
        d.get("S", 0), d.get("kept", 0), ", ".join(res.get("flags") or []) or "none", res["status"]))
    L.append("")
    L.append("## 5. The cards")
    L.append("")
    L.append("| # | place | neighbourhood | fits you | city order | holds | because (source) | AI answers naming it |")
    L.append("|---|---|---|---|---|---|---|---|")
    for i, c in enumerate(res["cards"], 1):
        bc = c["because"]
        L.append("| %d | %s | %s | %s | %s | %s | %s (%s%s) | %d of %d |" % (
            i, c["name"], c["neighbourhood"], c["fits"], c["city_order"], c["holds"], bc["line"], bc["source"],
            ", %.2f" % bc["share"] if bc.get("share") is not None else "", c["ai"]["named"], c["ai"]["asked"]))
    if res["cards"]:
        c = res["cards"][0]
        L.append("")
        L.append("## 6. Raw log for card 1 (%s, `%s`)" % (c["name"], c["qloo_id"]))
        L.append("")
        per = res.get("_per") or {}
        near = sorted(per.items(), key=lambda kv: -M.overlap(M.distinctive(kv[0]), M.distinctive(c["name"] or "")))[:5]
        L.append("- Named by 0 of %d answers. Closest wall names and what each resolved to:" % c["ai"]["asked"])
        for raw, info in near:
            L.append("  - \"%s\" → %s %s" % (raw, info["status"], info.get("resolved") or ""))
        L.append("- Every answer, its provider, model, phrasing and timestamp: `out/<run>.wall.json`.")
    sk = d.get("skeptic") or {}
    L.append("")
    L.append("Skeptic: %s." % ("burned %s" % ([b["name"] for b in sk.get("burned", [])] or "none") if sk.get("run")
                               else "not run (no LLM attached)"))
    return "\n".join(L) + "\n"


def _f(x, nd=2):
    return "n/a" if x is None or x != x else "%.*f" % (nd, x)
