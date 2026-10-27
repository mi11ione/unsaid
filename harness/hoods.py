"""Neighbourhood roster for the street asks (UNSAID.md §3.3 step 10, §3.6 budget "every neighbourhood in STL and NYC").
One Overpass query per area: named place=neighbourhood|suburb|quarter inside the City of St. Louis and inside
Manhattan + Brooklyn (the census boundaries). Data (c) OpenStreetMap contributors, ODbL 1.0.
Generic User-Agent, no name or email in any header.
Usage: python3 -I hoods.py            -> writes neighbourhoods.json next to this file"""
import json, os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
EPS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter",
       "https://overpass.private.coffee/api/interpreter"]
UA = "unsaid-harness/0.1"
AREAS = {"stl": ["Q38022"], "nyc": ["Q11299", "Q18419"]}  # City of St. Louis; Manhattan, Brooklyn


def fetch(qid):
    q = ('[out:json][timeout:120];area["wikidata"="%s"]["boundary"="administrative"]->.a;'
         'nwr["place"~"^(neighbourhood|suburb|quarter)$"]["name"](area.a);out tags;' % qid)
    for k in range(6):
        ep = EPS[k % len(EPS)]
        # curl, not urllib: the system Python's TLS stack fails the handshake with overpass-api.de
        p = subprocess.run(["curl", "-sS", "--max-time", "150", "-A", UA, "--data-urlencode", "data=" + q, ep],
                           capture_output=True, text=True, stdin=subprocess.DEVNULL)
        try:
            return json.loads(p.stdout)["elements"]
        except Exception:
            print("overpass try %d at %s failed: %s" % (k + 1, ep, (p.stderr or p.stdout)[:120]), file=sys.stderr)
            time.sleep(20 * (k + 1))
    sys.exit("Overpass unavailable; street asks can still take --hoods on the command line")


def main():
    out = {"source": "OpenStreetMap place=neighbourhood|suburb|quarter, (c) OpenStreetMap contributors, ODbL 1.0",
           "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "cities": {}}
    for ck, qids in AREAS.items():
        names = set()
        for q in qids:
            for e in fetch(q):
                n = (e.get("tags") or {}).get("name", "").strip()
                if n:
                    names.add(n)
        out["cities"][ck] = sorted(names)
        print(ck, len(names))
    with open(os.path.join(HERE, "neighbourhoods.json"), "w") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main()
