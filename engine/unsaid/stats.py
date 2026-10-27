"""Rank statistics. Ranks only, never raw-score subtraction (docs_interpreting-affinity-scores.md)."""
import random


def rank(values, higher_better=True):
    """{id: value} -> {id: rank 1..N}, average rank for exact ties."""
    items = sorted(values.items(), key=lambda kv: (-kv[1] if higher_better else kv[1], kv[0]))
    out, i = {}, 0
    while i < len(items):
        j = i
        while j + 1 < len(items) and items[j + 1][1] == items[i][1]:
            j += 1
        r = (i + j) / 2.0 + 1
        for k in range(i, j + 1):
            out[items[k][0]] = r
        i = j + 1
    return out


def pct(rk, n):
    """rank 1 -> 1.0, rank n -> 0.0"""
    return 1.0 if n <= 1 else 1 - (rk - 1) / (n - 1)


def spearman(a, b):
    """a, b: {id: rank}. Over the shared ids."""
    ids = sorted(set(a) & set(b))
    n = len(ids)
    if n < 3:
        return float("nan")
    ra = rank({i: -a[i] for i in ids})
    rb = rank({i: -b[i] for i in ids})
    ma = sum(ra.values()) / n
    mb = sum(rb.values()) / n
    cov = sum((ra[i] - ma) * (rb[i] - mb) for i in ids)
    va = sum((ra[i] - ma) ** 2 for i in ids) ** 0.5
    vb = sum((rb[i] - mb) ** 2 for i in ids) ** 0.5
    return cov / (va * vb) if va and vb else float("nan")


def jaccard(x, y):
    x, y = set(x), set(y)
    return len(x & y) / len(x | y) if x | y else float("nan")


def auc(scores, labels):
    """P(score of a positive > score of a negative), ties count half (Mann-Whitney)."""
    pos = [s for s, l in zip(scores, labels) if l]
    neg = [s for s, l in zip(scores, labels) if not l]
    if not pos or not neg:
        return float("nan")
    w = 0.0
    for p in pos:
        for q in neg:
            w += 1.0 if p > q else (0.5 if p == q else 0.0)
    return w / (len(pos) * len(neg))


def bootstrap(xs, stat=lambda v: sum(v) / len(v), n=2000, lo=0.05, hi=0.95, seed=1):
    if not xs:
        return float("nan"), float("nan")
    r = random.Random(seed)
    vals = sorted(stat([r.choice(xs) for _ in xs]) for _ in range(n))
    return vals[int(lo * n)], vals[int(hi * n) - 1]


def median(xs):
    s = sorted(xs)
    n = len(s)
    if not n:
        return float("nan")
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2
