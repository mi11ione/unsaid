"""Street catch-up: find the neighbourhoods of every card and reserve in some directories of result JSONs that no street
wall has asked yet, and write them as a hoods file for `walls_cli.py ask --kind street`.

Only `city` and each pick's/reserve's `neighbourhood` are read; nothing else from a result file is used or stored.
Already asked = any `hood` in runs/wall-street-*.jsonl (a live, answered record, either lane).

  python3 -I street_catchup.py --label street-2 DIR [DIR ...]     # writes runs/.street-2.hoods.json (gitignored)
Exit code 3 when there is nothing new to ask.
"""
import argparse, glob, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lanes as L

CITY_KEYS = {"stl": "stl", "st-louis": "stl", "nyc": "nyc", "new-york": "nyc"}


def hoods_in(dirs):
    out = {}
    for d in dirs:
        for f in sorted(glob.glob(os.path.join(os.path.expanduser(d), "**", "*.json"), recursive=True)):
            try:
                o = json.load(open(f))
            except Exception:
                continue
            res = o.get("result") if isinstance(o, dict) else None
            if not isinstance(res, dict):
                continue
            city = o.get("city") if isinstance(o.get("city"), str) else ((res.get("city") or {}).get("key") or (res.get("city") or {}).get("slug"))
            ck = CITY_KEYS.get(city)
            if not ck:
                continue
            for c in (res.get("picks") or []) + (res.get("reserves") or []):
                h = (c.get("neighbourhood") or "").strip()
                if h:
                    out.setdefault(ck, set()).add(h)
    return out


def asked():
    out = {}
    for f in glob.glob(os.path.join(L.RUNS, "wall-street-*.jsonl")):
        for r in L.load(f).values():
            if r.get("hood") and L.is_done(r):
                out.setdefault(r["city"], set()).add(r["hood"])
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dirs", nargs="+")
    ap.add_argument("--label", default="street-2")
    a = ap.parse_args()
    have, done = hoods_in(a.dirs), asked()
    path = os.path.join(L.RUNS, ".%s.hoods.json" % a.label)
    prev = json.load(open(path))["cities"] if os.path.exists(path) else {}
    new = {ck: sorted(v - done.get(ck, set())) for ck, v in have.items()}
    merged = {ck: sorted(set(prev.get(ck, [])) | set(new.get(ck, []))) for ck in set(prev) | set(new)}
    os.makedirs(L.RUNS, exist_ok=True)
    json.dump({"source": "neighbourhood + city of picks and reserves in %s" % ", ".join(a.dirs), "cities": merged},
              open(path, "w"), indent=1, ensure_ascii=False)
    print("neighbourhoods in the results: %s; already asked: %s; new: %s -> %s" % (
        {k: len(v) for k, v in have.items()}, {k: len(have.get(k, set()) & done.get(k, set())) for k in have},
        {k: len(v) for k, v in new.items()}, os.path.relpath(path, HERE)))
    sys.exit(0 if any(new.values()) or any(merged.values()) else 3)


if __name__ == "__main__":
    main()
