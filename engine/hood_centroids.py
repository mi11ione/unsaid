"""OSM neighbourhood centroids for the card's neighbourhood fallback (UNSAID.md §2.1 card front; 0 Qloo calls).
harness/neighbourhoods.json holds names only, so this fetches the centroids: named place=neighbourhood|suburb|
quarter|town|village|hamlet within each city's radius (+1 mi), one Overpass query per city, `out center`.
Data (c) OpenStreetMap contributors, ODbL 1.0. Project User-Agent, no name or email.
  python3 -I hood_centroids.py         -> fixtures/hood_centroids.json"""
import json, os, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from unsaid import cities as C  # noqa: E402

KIT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(KIT, "fixtures", "hood_centroids.json")
EPS = ["https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter",
       "https://overpass.kumi.systems/api/interpreter"]
UA = "unsaid-engine/0.4"


def fetch(lat, lon, metres):
    q = ('[out:json][timeout:90];nwr["place"~"^(neighbourhood|suburb|quarter|town|village|hamlet)$"]["name"]'
         '(around:%d,%s,%s);out center tags;' % (metres, lat, lon))
    for k in range(8):
        ep = EPS[k % len(EPS)]
        p = subprocess.run(["curl", "-sS", "--max-time", "100", "-A", UA, "--data-urlencode", "data=" + q, ep],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True,
                           stdin=subprocess.DEVNULL)
        try:
            return json.loads(p.stdout)["elements"]
        except ValueError:
            print("overpass try %d at %s: %s" % (k + 1, ep, (p.stdout or p.stderr)[:80].replace("\n", " ")),
                  file=sys.stderr)
            time.sleep(15 * (k + 1))
    sys.exit("Overpass unavailable; the engine falls back to Qloo-pool centroids")


def main():
    out = {"source": "OpenStreetMap place=neighbourhood|suburb|quarter|town|village|hamlet, (c) OpenStreetMap "
                     "contributors, ODbL 1.0", "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "cities": {}}
    for ck in ("stl", "nyc", "la"):
        c = C.CITIES[ck]
        lat, lon = c["center"]
        rows = []
        for e in fetch(lat, lon, int((c["radius_mi"] + 1) * C.MI)):
            ctr = e.get("center") or ({"lat": e["lat"], "lon": e["lon"]} if "lat" in e else None)
            name = (e.get("tags") or {}).get("name", "").strip()
            if ctr and name and "Historic District" not in name:
                rows.append({"name": name, "place": e["tags"].get("place"), "lat": round(ctr["lat"], 5),
                             "lon": round(ctr["lon"], 5)})
        out["cities"][ck] = sorted(rows, key=lambda r: r["name"])
        print(ck, len(rows))
    with open(OUT, "w") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
