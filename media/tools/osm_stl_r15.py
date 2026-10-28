"""Fetch St. Louis eat-and-drink places within 15 mi (24,140 m) of the city centre, in ONE Overpass query (the pool's radius).
Adapted from research/round4/exp/osm_roster.py. Generic User-Agent, no name or email. Retries politely when busy.
Data (c) OpenStreetMap contributors, ODbL 1.0. Writes media/data/osm-stl-r15.json (cached; delete it to refetch).
    python3 -I media/tools/osm_stl_r15.py"""
import json
import os
import subprocess
import sys
import time

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'osm-stl-r15.json')
EP = 'https://overpass-api.de/api/interpreter'
EP2 = 'https://overpass.private.coffee/api/interpreter'  # public mirror, only when the main one is at capacity
UA = 'osm-roster/1.0'
CENTER, RADIUS_M = (38.627, -90.1994), 24140   # the engine's STL POINT and radius (UNSAID.md §3.1)
AMEN = 'restaurant|bar|pub|cafe|fast_food|food_court'


def query():
    return f'[out:json][timeout:300];nwr["amenity"~"^({AMEN})$"](around:{RADIUS_M},{CENTER[0]},{CENTER[1]});out tags center;'


def fetch(q, tries=6):
    wait = 30
    for k in range(tries):
        ep = EP if k % 2 == 0 else EP2
        p = subprocess.run(['curl', '-sS', '--max-time', '360', '-A', UA, '--data-urlencode', 'data=' + q, ep], capture_output=True, text=True)
        if p.returncode == 0:
            try:
                return json.loads(p.stdout)
            except ValueError:
                msg = p.stdout[:120].replace('\n', ' ')
        else:
            msg = p.stderr[:120]
        print(f'try {k + 1} at {ep}: {msg}; waiting {wait}s', flush=True)
        time.sleep(wait)
        wait *= 2
    sys.exit('Overpass unavailable')


if __name__ == '__main__':
    if os.path.exists(OUT):
        sys.exit(f'cached: {OUT}')
    q = query()
    d = fetch(q)
    feats = []
    for e in d['elements']:
        t = e.get('tags', {})
        lat = e.get('lat') or (e.get('center') or {}).get('lat')
        lon = e.get('lon') or (e.get('center') or {}).get('lon')
        if lat is None:
            continue
        feats.append({'osm': f'{e["type"]}/{e["id"]}', 'name': t.get('name', ''), 'amenity': t.get('amenity'), 'lat': lat, 'lon': lon})
    json.dump({'attribution': '© OpenStreetMap contributors, ODbL', 'query': q, 'osm_base': d.get('osm3s', {}).get('timestamp_osm_base'),
               'features': feats}, open(OUT, 'w'), ensure_ascii=False)
    print(f'{len(feats)} features, named {sum(1 for f in feats if f["name"])}, osm base {d.get("osm3s", {}).get("timestamp_osm_base")} -> {OUT}')
