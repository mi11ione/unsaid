"""README call trace, generated from a real run (never hand-written): every request URL (the key travels in the
X-Api-Key header and never appears), the floor line, the popularity section (``## Is this just
`filter.popularity.max`?``) and the placeholders it fills (UNSAID.md §6.0)."""
import re
import time
from collections import OrderedDict

from unsaid.qloo import redact

STEP_DOC = OrderedDict([
    ("C1 city", "the locality (NYC: UUID, region checked; STL/LA: POINT, no call)"),
    ("C2 love", "entity ID per love (exact name first)"),
    ("C2 love tag", "tag ID for a dish/drink love"),
    ("C4 pool", "per-love pool, offsets 0 and 50 (explainability on page 1 only, raw log)"),
    ("C6'", "fixed-set rescoring: 48 of U + 2 anchors, one love's signal per call"),
    ("C5 no-signal", "no-signal rescoring of U (only if P12 says popularity is not the city order)"),
    ("C7 name", "AI name -> Qloo ID, city-scoped (only names sharing a token with U)"),
    ("CAP", "the popularity cap: entity loves + filter.popularity.max removing |struck| members of U"),
])


def short_url(u):
    """Long ID lists shown as first two + count, so the trace stays readable."""
    def cut(m):
        ids = m.group(2).split(",")
        return m.group(1) + (",".join(ids[:2]) + ",…(+%d)" % (len(ids) - 2) if len(ids) > 3 else m.group(2))
    return re.sub(r"((?:filter\.results\.entities|filter\.exclude\.entities|signal\.interests\.entities)=)([^&]+)",
                  cut, redact(u))


def _group(trace):
    g = OrderedDict()
    for r in trace:
        key = next((k for k in STEP_DOC if r["label"].startswith(k)), r["label"].split(" ")[0])
        x = g.setdefault(key, {"n": 0, "net": 0, "ms": 0, "ex": r["url"], "res": 0})
        x["n"] += 1
        x["net"] += 0 if r["cache"] else 1
        x["ms"] += r["ms"]
        x["res"] += r["n"] or 0
    return g


def _f(x, nd=2):
    return "n/a" if x is None or x != x else "%.*f" % (nd, x)


def placeholders(r):
    d, cn = r["diag"], r["counts"]
    p = r["picks"]
    ph = OrderedDict([
        ("WALL", cn.get("wall")), ("ASKS", cn.get("asks")), ("U", cn.get("U")), ("R", cn.get("R_mi")),
        ("FIT", p[0]["fit_rank"] if p else None), ("ANY", p[0]["any_rank"] if p else None),
        ("QLOO_CALLS", d.get("qloo_calls")),
        ("A", p[0]["name"] if len(p) > 0 else None), ("B", p[1]["name"] if len(p) > 1 else None),
        ("C", p[2]["name"] if len(p) > 2 else None),
        ("CAP_KEEP", d.get("cap_keep")), ("CAP_SHARED", d.get("cap_shared")),
        ("OBSCURE", len(d.get("obscure") or [])), ("KNOWN", len(d.get("known") or [])),
        ("RHO_TP", _f(d.get("rho_tp"))),
        ("RHO_RES", _f(d.get("rho_res")) if d.get("rho_res") is not None else "null (%s)" % d.get("rho_res_note")),
    ])
    return ph


def markdown(r, trace, city_label, loves_text, fake, set_id=None):
    d, cn = r["diag"], r["counts"]
    T = " [FAKE]" if fake else ""
    L = ["# UNSAID call trace%s" % (" [FAKE: canned responses; numbers prove code paths, not Qloo]" if fake else ""), ""]
    L.append("Query: **%s** · set `%s` · loves: %s · %s · as of %s · ran %s" % (
        city_label, set_id or "-", ", ".join(loves_text), d.get("engine_v"), d.get("as_of"),
        time.strftime("%Y-%m-%d %H:%M %Z")))
    L.append("")
    L.append("Status **%s** · flags: %s · %d Qloo calls (%d over the network) in %s s." % (
        r["status"], ", ".join(r.get("flags") or []) or "none", d.get("qloo_calls") or 0, d.get("qloo_network") or 0,
        d.get("elapsed_s")))
    L.append("")
    L.append("## Call trace")
    L.append("")
    L.append("| step | calls (network / cache) | sum ms | results | what it became | example request |")
    L.append("|---|---|---|---|---|---|")
    for k, x in _group(trace).items():
        L.append("| %s | %d (%d / %d) | %d | %d | %s | `%s` |" % (k, x["n"], x["net"], x["n"] - x["net"], x["ms"], x["res"],
                                                             STEP_DOC.get(k, ""), short_url(x["ex"])))
    L.append("")
    L.append("<details><summary>Every request (%d), in order. The key is sent in the X-Api-Key header only.</summary>" %
             len(trace))
    L.append("")
    L.append("| # | step | status | ms | cache | n | request |")
    L.append("|---|---|---|---|---|---|---|")
    for i, t in enumerate(trace, 1):
        L.append("| %d | %s | %s | %s | %s | %s | `%s` |" % (i, t["label"], t["status"], t["ms"],
                                                           "hit" if t["cache"] else "net", t["n"], short_url(t["url"])))
    L.append("")
    L.append("</details>")
    L.append("")
    L.append("## The set every rank is taken over")
    L.append("")
    fl = cn.get("floor") or {}
    L.append("%s → %s (closed %s, below 4.3 %s, outside %s mi %s, not a restaurant or bar %s; of which music venue %s)"
             ".%s" % (cn.get("P"), cn.get("U"), fl.get("closed"), fl.get("below_43"), cn.get("R_mi"), fl.get("outside_R"),
                      fl.get("not_venue"), fl.get("not_venue_music", 0), T))
    L.append("")
    L.append("Pools: one per entity love, offsets 0 and 50, `urn:tag:category:place:restaurant` ∪ `…:bar`, "
             "`business_rating.min=4` server side then ≥ 4.3 − 1e-4 client side, `bias.trends=off`. Every rank on a "
             "card is a rank inside this one U. %s. Tie share at Qloo's default affinity: %s (thin_taste above 0.30)."
             % (d.get("baseline"), _f(d.get("tie_share"))))
    L.append("")
    L.append("| love | rescoring calls | coverage | anchor drift | tied | ρ(order, popularity) | live? |")
    L.append("|---|---|---|---|---|---|---|")
    dead = {l["label"]: l for l in r["loves"] if l.get("dead")}
    for l in r["loves"]:
        rs = (d.get("rescore") or {}).get(l["label"]) or next(
            (v for k, v in (d.get("rescore") or {}).items() if k.lower() == (l["label"] or "").lower()), {})
        L.append("| %s (%s) | %s | %s | %s | %s | %s | %s |" % (
            l["label"], l.get("type_label"), rs.get("calls", 0), _f(rs.get("coverage")), _f(rs.get("drift"), 4),
            _f(rs.get("tie_share")), _f(rs.get("rho_pop")),
            "dead: %s" % dead[l["label"]].get("dead_reason") if l["label"] in dead else "yes"))
    for l in r["loves"]:
        if l.get("dead_line"):
            L.append("")
            L.append("> %s%s" % (l["dead_line"], T))
    L.append("")
    L.append("## Is this just `filter.popularity.max`?")
    L.append("")
    cap_ok = d.get("cap_overlap") is not None and d["cap_overlap"] <= 0.80
    L.append("- A popularity cap cutting the same %s would keep **%s** of the places the AIs named. Its 7 and yours "
             "share **%s**.%s" % (cn.get("struck_in_U") or "%s" % (cn.get("U", 0) - cn.get("S", 0)),
                                  d.get("cap_keep"), d.get("cap_shared"), T))
    if d.get("rho_res") is None:
        L.append("- Taste vs popularity ρ **%s**. %s: the residual sentence is deleted (bracket rule).%s" % (
            _f(d.get("rho_tp")), d.get("rho_res_note") or "RHO_RES undefined (base = popularity)", T))
    else:
        L.append("- Taste vs popularity ρ **%s**; after the city's own order is taken away, ρ **%s**.%s" % (
            _f(d.get("rho_tp")), _f(d.get("rho_res")), T))
    L.append("  - ρ_tp = Spearman(for-you RRF order, popularity) over U. ρ_res = partial Spearman ρ(for-you, popularity | "
             "the city's no-signal rank), defined only when P12 finds the no-signal order is not popularity (ρ < 0.99).")
    L.append("- The cap's 7: %s." % (", ".join(x["name"] or x["id"] for x in d.get("cap7") or []) or "n/a"))
    L.append("")
    L.append("| STRUCK THOUGH OBSCURE (%d) | KEPT THOUGH KNOWN (%d) |" % (len(d.get("obscure") or []),
                                                                     len(d.get("known") or [])))
    L.append("|---|---|")
    ob, kn = d.get("obscure") or [], d.get("known") or []
    for i in range(max(len(ob), len(kn), 1)):
        L.append("| %s | %s |" % (ob[i]["name"] if i < len(ob) else "", kn[i]["name"] if i < len(kn) else ""))
    L.append("")
    L.append("C · not a cap: cap overlap %s (gate ≤ 0.80) → %s%s; cap's 7 share %s with ours (≤ 2 is the 0.50-odds "
             "bar)." % (_f(d.get("cap_overlap")), "PASS" if cap_ok else "FAIL", T, d.get("cap_shared")))
    L.append("")
    L.append("## The wall")
    L.append("")
    st = {}
    for w in r["wall"]:
        st[w["reason"]] = st.get(w["reason"], 0) + 1
    provs = sorted({"%s (%s)" % (w["provider"], w["lane"]) for w in r["wall"]})
    L.append("%s distinct names from %s asks (%s). Source: %s. Name outcomes: %s." % (
        cn.get("wall"), cn.get("asks"), ", ".join(provs) or "none", d.get("wall_source"),
        ", ".join("%s %d" % kv for kv in sorted(st.items()))))
    if d.get("reverse_struck"):
        L.append("")
        L.append("Reverse check struck: %s." % ", ".join(x["name"] for x in d["reverse_struck"]))
    L.append("")
    L.append("## The cards (for-you order)")
    L.append("")
    L.append("| # | place | what | for you | for anyone | holds | because | rating | never said in |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for i, c in enumerate(r["picks"], 1):
        L.append("| %d | %s | %s | #%s | %s | %s | %s | %s | %s asks (%s street) |" % (
            i, c["name"], c["what"], c["fit_rank"], "#%s" % c["any_rank"] if c["any_rank"] else "—",
            "%s of %s" % (c["holds"], c["n_loves"]) if c["holds"] is not None else "n/a",
            c["because"], _f(c["rating"], 1), c["never_said"]["asks"], c["never_said"]["street_asks"]))
    if r["reserves"]:
        L.append("")
        L.append("Reserves: %s." % ", ".join("%s (#%s)" % (c["name"], c["fit_rank"]) for c in r["reserves"]))
    b = r.get("burn") or {}
    L.append("")
    L.append("Street check: %d asks over %d neighbourhoods; burned: %s." % (
        len(b.get("asked") or []), len({a["neighbourhood"] for a in b.get("asked") or []}),
        ", ".join("%s (by %s, %s)" % (x["name"], x["by"], x["neighbourhood"]) for x in b.get("burned") or []) or "none"))
    L.append("")
    L.append("## Placeholders this run fills (UNSAID.md §6.0)%s" % T)
    L.append("")
    for k, v in placeholders(r).items():
        L.append("- ⟦%s⟧ = %s%s" % (k, v, T))
    return "\n".join(L) + "\n"
