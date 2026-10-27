"""Fetch New York's eat-and-drink places (Manhattan, Brooklyn, Queens) from OpenStreetMap, in ONE Overpass query.
Adapted from research/round4/exp/osm_roster.py. Generic User-Agent, no name or email. Retries politely when busy.
Data (c) OpenStreetMap contributors, ODbL 1.0. Writes media/data/osm-nyc.json (cached; delete it to refetch).
    python3 -I media/tools/osm_nyc.py"""
import json
import os
import subprocess
import sys
import time

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'osm-nyc.json')
EP = 'https://overpass-api.de/api/interpreter'
EP2 = 'https://overpass.private.coffee/api/interpreter'  # public mirror, only when the main one is at capacity
UA = 'osm-roster/1.0'
BOROUGHS = {'Q11299': 'Manhattan', 'Q18419': 'Brooklyn', 'Q18424': 'Queens'}  # boundary relations by Wikidata id
AMEN = 'restaurant|bar|pub|cafe|fast_food'


def query():
    areas = ''.join(f'area["wikidata"="{q}"]["boundary"="administrative"]->.a{i};' for i, q in enumerate(BOROUGHS))
    body = ''.join(f'nwr["amenity"~"^({AMEN})$"](area.a{i});' for i in range(len(BOROUGHS)))
    return f'[out:json][timeout:300];{areas}({body});out tags center;'


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
