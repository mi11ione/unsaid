"""Builds the static data that the site and the media templates read.

    python3 -I media/tools/build_data.py        (from /Users/mi11ion/Desktop/qloo/unsaid)

Reads (never writes) the round-4 research data:
    research/round4/exp/claude_answers.jsonl     the real Claude census (64 + 64 asks, 27 Oct 2026)
    research/round4/exp/census_stats.txt         every census figure on screen is checked against a line here
    research/round4/proto/data/roster.js         818 OSM places + the census's red discs (map only)
    research/round4/proto/data/hoods-stl.json    OSM neighbourhood boundaries (label points for the mock reserves)
    unsaid/agent/demo/claude_without.jsonl       the real "plan my Friday ... but nothing every AI would tell me" answer

Writes:
    site/data/census.json        census figures, each with its census_stats.txt line, + the 16 gem asks (for the clip)
    site/data/map/stl.json       grey dots, red discs, the gem callout
    site/data/walls/stl.json     the dated city wall: every St. Louis census answer (Claude, real, 27 Oct)
    site/data/try.json           the try-these sets (only Cedric has a stream yet, and it is MOCK)
    site/data/config.json        lanes, the cities the site knows
    site/data/mock/*.ndjson      MOCK streams for every §2.2 state; every one carries flags ["fake"]
    site/data/mock/resolve.json  MOCK answers for GET /api/resolve when no server is up
    media/data/assistant.json    the real assistant answer for image 3
"""
import hashlib
import json
import re
import sys
from pathlib import Path

UNSAID = Path(__file__).resolve().parents[2]
QLOO = UNSAID.parent
EXP = QLOO / 'research' / 'round4' / 'exp'
PROTO = QLOO / 'research' / 'round4' / 'proto' / 'data'
SITE = UNSAID / 'site' / 'data'
MEDIA = UNSAID / 'media' / 'data'
sys.path.insert(0, str(UNSAID / 'engine'))
from unsaid.matcher import norm  # noqa: E402  the engine's own normalisation, so the wall's norm keys match it

STATS = (EXP / 'census_stats.txt').read_text().splitlines()


def cite(line, pattern, *expect):
    """Assert census_stats.txt line `line` (1-based) matches `pattern` and its groups equal `expect`."""
    m = re.search(pattern, STATS[line - 1])
    assert m, f'census_stats.txt:{line} does not match {pattern!r}: {STATS[line - 1]!r}'
    got = tuple(int(g) if g.isdigit() else g for g in m.groups())
    assert got == expect, f'census_stats.txt:{line}: {got} != {expect}'
    return f'census_stats.txt:{line}'


def jdump(path, obj, indent=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=indent) + '\n')


rows = [json.loads(line) for line in open(EXP / 'claude_answers.jsonl')]
names_of = lambda r: [p['name'] if isinstance(p, dict) else p for p in r['places']]

# ---------------------------------------------------------------- census figures (each cited) --------
stl = sorted([r for r in rows if r['city'] == 'stl'], key=lambda r: r['order'])
gem_asks = []
for r in stl:
    if r['family'] != 'hidden':
        continue
    ns = names_of(r)
    pos = next((i for i, n in enumerate(ns) if 'gioia' in n.lower()), None)
    gem_asks.append({'id': r['id'], 'ask': r['phrasing'], 'hit': pos is not None, 'pos': None if pos is None else pos + 1, 'n': len(ns)})
plain = [r for r in stl if r['family'] == 'generic']
plain_hits = sum(any('gioia' in n.lower() for n in names_of(r)) for r in plain)

census = {
    '_': 'Every figure here is a census figure; "src" is the census_stats.txt line it is checked against by build_data.py.',
    'model': 'Claude Sonnet 5.5', 'model_id': stl[0]['model'], 'date': '27 Oct 2026', 'web_search': False, 'preregistered': True,
    'stl': {
        'city': 'St. Louis',
        'asks': {'n': 64, 'src': cite(3, r'ST\. LOUIS: (\d+) asks', 64)},
        'gem': {'name': "Gioia's Deli", 'hits': 13, 'of': 16, 'hood': 'The Hill',
                'src': cite(58, r"Gioia's Deli\s+(\d+)/(\d+)", 13, 16)},
        'gem_family': {'n': 16, 'src': cite(51, r'hidden\s+(\d+) asks', 16)},
        'plain': {'hits': 11, 'of': 14,
                  'src': cite(46, r"Gioia's Deli (\d+)/", 11) + ' (generic first) + ' + cite(52, r'generic\s+(\d+) asks', 14)},
        'second': {'name': "Pappy's Smokehouse", 'src': cite(49, r"Gioia's Deli 37, (Pappy's Smokehouse) 35", "Pappy's Smokehouse")},
        'said': {'n': 236, 'src': cite(20, r'SAID \(L2, headline\) = (\d+)', 236)},
        'k50': {'n': 29, 'src': cite(44, r'K50 = (\d+) names', 29)},
        'strangers_shared': {'n': 9, 'src': cite(76, r'Cedric∩Jason = (\d+)', 9)},
        'osm': {'n': 818, 'src': cite(81, r'OSM roster: (\d+) features', 818)},
        'gem_asks': gem_asks,
        'asked': {'first': stl[0]['t_start'], 'last': max(r['t_start'] for r in stl), 'src': 'claude_answers.jsonl t_start'},
    },
    'nyc': {
        'city': 'New York',
        'asks': {'n': 64, 'src': cite(92, r'NEW YORK .*: (\d+) asks', 64)},
        'gem': {'name': 'Sripraphai', 'hits': 11, 'of': 16, 'first': 6, 'hood': 'Woodside, Queens',
                'src': cite(147, r'Sripraphai\s+(\d+)/(\d+)', 11, 16) + ' + ' + cite(136, r'Sripraphai (\d+), Di Fara', 6)},
        'said': {'n': 334, 'src': cite(109, r'SAID \(L2, headline\) = (\d+)', 334)},
        'osm': {'n': 11959, 'src': cite(170, r'(\d+) named', 11959)},
    },
}
# the per-ask list must reproduce the cited figures
assert sum(a['hit'] for a in gem_asks) == census['stl']['gem']['hits'] and len(gem_asks) == census['stl']['gem']['of']
assert plain_hits == census['stl']['plain']['hits'] and len(plain) == census['stl']['plain']['of']
assert len(stl) == census['stl']['asks']['n']
jdump(SITE / 'census.json', census, 1)

# ---------------------------------------------------------------- the map (STL) -----------------------
src = (PROTO / 'roster.js').read_text()
roster = json.loads(src[src.index('{'):src.rstrip().rstrip(';').rindex('}') + 1])
assert len(roster['places']) == census['stl']['osm']['n']
gioia = roster['ai'][0]
assert gioia['name'] == census['stl']['gem']['name']
stl_map = {
    'city': 'St. Louis', 'lat0': 38.63, 'latMax': 38.70,
    'places': roster['places'],
    'ai': [{'name': a['name'], 'count': a['count'], 'lat': a['lat'], 'lon': a['lon']} for a in roster['ai']],
    'callouts': [census['stl']['gem']['name'], census['stl']['second']['name']],
    'credit': 'grey: {n} mapped places to eat and drink, © OpenStreetMap contributors, ODbL'.format(n=f"{len(roster['places']):,}"),
    'osm_as_of': roster['meta']['osm'],
}
jdump(SITE / 'map' / 'stl.json', stl_map)

# ---------------------------------------------------------------- the dated city wall (STL) -----------
def clean(n):
    n = re.sub(r'\s*\(.*?\)\s*', ' ', n).strip()
    m = re.match(r'^.+? at (.+)$', n)  # 'Pork steak and ribs BBQ at Pappy's Smokehouse' -> the venue
    if m and len(m.group(1).split()) <= 5 and not n.lower().startswith(('jazz at', 'lounge at')):
        n = m.group(1)
    return n


answers = []
for r in stl:
    answers.append({'provider': 'Claude', 'model': r['model'], 'phrasing_id': r['id'], 'phrasing': r['phrasing'],
                    'family': r['family'], 'asked_at': r['t_start'], 'lane': 'dated', 'names': [clean(n) for n in names_of(r)]})
wall_items, seen = [], {}
for a in answers:
    for n in a['names']:
        k = norm(n)
        if not k:
            continue
        if k in seen:
            seen[k]['asks'] += 1
            continue
        it = {'name': n, 'norm': k, 'provider': a['provider'], 'model': a['model'], 'phrasing_id': a['phrasing_id'],
              'phrasing': a['phrasing'], 'asked_at': a['asked_at'], 'lane': 'dated', 'asks': 1}
        seen[k] = it
        wall_items.append(it)
jdump(SITE / 'walls' / 'stl.json', {
    'city': 'st-louis', 'as_of': max(a['asked_at'] for a in answers), 'source': 'Claude census, claude -p, no web search',
    'answers': answers, 'distinct': len(wall_items)})

# ---------------------------------------------------------------- New York: map (Manhattan, Brooklyn, Queens) + wall ----
import csv  # noqa: E402
nyc = sorted([r for r in rows if r['city'] == 'nyc'], key=lambda r: r['order'])
nyc_answers = [{'provider': 'Claude', 'model': r['model'], 'phrasing_id': r['id'], 'phrasing': r['phrasing'], 'family': r['family'],
                'asked_at': r['t_start'], 'lane': 'dated', 'names': [clean(n) for n in names_of(r)]} for r in nyc]
jdump(SITE / 'walls' / 'nyc.json', {'city': 'new-york', 'as_of': max(a['asked_at'] for a in nyc_answers),
                                    'source': 'Claude census, claude -p, no web search', 'answers': nyc_answers})
census['nyc']['asked'] = {'first': nyc[0]['t_start'], 'last': max(r['t_start'] for r in nyc), 'src': 'claude_answers.jsonl t_start'}
jdump(SITE / 'census.json', census, 1)
osm_nyc = MEDIA / 'osm-nyc.json'
NYC_MAP = None
if osm_nyc.exists():
    O = json.load(open(osm_nyc))
    feats = O['features']
    by_id = {f['osm']: f for f in feats}
    by_norm = {}
    for f in feats:
        if f['name']:
            by_norm.setdefault(norm(f['name']), []).append(f)
    discs, unplaced = [], []
    for row in csv.DictReader(open(EXP / 'claude_named_nyc.csv')):
        hit = next((by_id[i] for i in row['osm_ids'].split() if i in by_id), None)
        if not hit:
            cands = by_norm.get(norm(row['display']), [])
            hit = cands[0] if len(cands) == 1 else None
        if hit:
            discs.append({'name': row['display'], 'count': int(row['mentions']), 'lat': hit['lat'], 'lon': hit['lon']})
        else:
            unplaced.append(row['display'])
    gem = census['nyc']['gem']['name']
    assert any(d['name'] == gem for d in discs), f'{gem} not found on the NYC map'
    NYC_MAP = {'city': 'New York', 'lat0': 40.72, 'places': [[round(f['lon'], 5), round(f['lat'], 5)] for f in feats],
               'ai': discs, 'callouts': [gem],
               'credit': 'grey: {n} mapped places to eat and drink in Manhattan, Brooklyn and Queens, © OpenStreetMap contributors, ODbL'.format(n=f"{len(feats):,}"),
               'osm_as_of': O.get('osm_base'), 'unplaced': len(unplaced)}
    jdump(SITE / 'map' / 'nyc.json', NYC_MAP)
    print(f"nyc map: {len(feats)} dots, {len(discs)} discs placed, {len(unplaced)} census names not placed")

# ---------------------------------------------------------------- config + try-these ------------------
jdump(SITE / 'config.json', {
    'lanes': ['ChatGPT', 'Claude', 'Gemini'],
    'cities': {'st-louis': {'name': 'St. Louis', 'map': 'data/map/stl.json', 'wall': 'data/walls/stl.json', 'census': 'stl'},
               'new-york': {'name': 'New York', 'map': 'data/map/nyc.json' if NYC_MAP else None, 'wall': 'data/walls/nyc.json', 'census': 'nyc'}},
    'floor': {'rating': 4.3},
}, 1)
jdump(SITE / 'try.json', {'sets': [
    {'id': 'stl-cedric', 'label': 'Cedric · St. Louis', 'city': 'st-louis',
     'loves': ['Frankie Beverly & Maze', 'The Original Kings of Comedy', 'rib tips'], 'ran': None,
     'src': 'data/mock/stl-cedric.ndjson', 'mock': True},
    {'id': 'stl-jason', 'label': 'Jason · St. Louis', 'city': 'st-louis', 'loves': ['Frank Sinatra', 'Rounders', 'Carbone'],
     'ran': None, 'src': None, 'mock': False},
    {'id': 'nyc-khruangbin', 'label': 'Khruangbin · New York', 'city': 'new-york', 'loves': ['Khruangbin', None, None],
     'ran': None, 'src': 'data/mock/nyc-khruangbin.ndjson' if NYC_MAP else None, 'mock': bool(NYC_MAP)},
]}, 1)

# ---------------------------------------------------------------- MOCK streams -------------------------
hoods = json.load(open(PROTO / 'hoods-stl.json'))['elements']
label_pt = {}
for h in hoods:
    for m in h.get('members', []):
        if m.get('role') == 'label':
            label_pt[h['tags']['name']] = (m['lon'], m['lat'])

LOVES = [  # S1 field order: an artist, a film or show, something you'd order
    {'id': None, 'label': 'Frankie Beverly & Maze', 'kind': 'entity', 'type': 'artist', 'dead': False},
    {'id': None, 'label': 'The Original Kings of Comedy', 'kind': 'entity', 'type': 'movie', 'dead': False},
    {'id': None, 'label': 'rib tips', 'kind': 'tag', 'type': 'dish', 'dead': False},
]
# MOCK card bodies (round-3 prototype values). Names are null: no Qloo ranking exists, so the UI shows a placeholder.
# Positions: the hero's seven OSM places (no AI named them) in their real neighbourhoods; reserves at hood label points.
MOCK_CARDS = [
    ('soul food · live R&B', 0, 4, 151, 4.6, 3), ('barbecue · rib tips by the pound', 2, 5, 138, 4.5, 3),
    ('barbecue counter · smoker out back', 2, 6, 122, 4.7, 3), ('comedy room with a kitchen', 1, 9, 170, 4.4, 2),
    ('supper club · Sunday jazz', 0, 11, 176, 4.4, 3), ('fish fry and wings', 2, 14, 149, 4.3, 3),
    ('lounge · old-school soul records', 0, 17, 188, 4.5, 2),
    ('tavern · Friday fish', 2, 19, 160, 4.4, 3), ('jazz bar · late kitchen', 0, 21, 182, 4.5, 2), ('soul food · cafeteria line', 2, 24, 131, 4.3, 3),
]
seven = roster['seven']
spots = [(s['hood'], s['lon'], s['lat']) for s in seven] + [(h, *label_pt[h]) for h in ('The Ville', 'Old North Saint Louis', 'Soulard')]
U, R_MI = 196, 10
AS_OF = None  # a mock run never happened: no invented timestamps (the UI shows ⟦date⟧)


STL_CITY = {'id': None, 'name': 'St. Louis', 'slug': 'st-louis', 'center': [-90.199, 38.627], 'radius_mi': R_MI}


def card(i, tied=False, spot_list=None, src_answers=None):
    spot_list, src_answers = spot_list or spots, src_answers or answers
    what, love, fit, anyr, rating, holds = MOCK_CARDS[i]
    hood, lon, lat = spot_list[i]
    cid = 'mock-' + hashlib.sha1(f'card{i}'.encode()).hexdigest()[:8]
    return {'id': cid, 'name': None, 'what': what, 'because': LOVES[love]['label'], 'fit_rank': None if tied else fit,
            'any_rank': anyr, 'U': U, 'rating': rating, 'open': True, 'neighbourhood': hood, 'address': None,
            'lat': lat, 'lon': lon, 'url': None, 'holds': holds, 'n_loves': 3, 'tied': tied,
            'never_said': {'asks': len(src_answers) + 3, 'city_asks': len(src_answers), 'street_asks': 3, 'as_of': AS_OF}}


# MOCK outcomes. A real business from the census is only ever struck, reason "mock", no Qloo ID: nothing about it is
# claimed. The dimmed reasons are shown only on fictional placeholder items (name null -> the UI draws ⟦dimmed n⟧).
DIMMED_DEMO = ['closed (Qloo)', 'not found in Qloo', 'not in pool']


def stream(name, *, status='ok', n_picks=7, n_res=3, flags=(), loves=LOVES, tied=(), burn=True, pre=(), lanes_answers=None, city=None, ans_src=None, spot_list=None,
           degraded_as_of=None, known=False, end_early=None, diag_extra=None):
    ev, t = [], 0

    def push(dt, e):
        nonlocal t
        t += dt
        e['t'] = round(t)
        ev.append(e)
    for e in pre:
        push(e.pop('dt', 0), e)
    if end_early:
        push(400, {'type': 'done', 'result': {'status': end_early, 'flags': ['fake'], 'loves': loves,
                   'city': city or STL_CITY,
                   'picks': [], 'reserves': [], 'wall': [], 'counts': None, 'burn': None,
                   'diag': {'qloo_calls': 0, 'engine_v': 'mock', 'as_of': AS_OF}}})
        return ev
    ans_src = ans_src or answers
    ans = ans_src if lanes_answers is None else ans_src[:lanes_answers]
    wall = []
    seen2 = set()
    for a in ans:
        for n in a['names']:
            k = norm(n)
            if not k or k in seen2:
                continue
            seen2.add(k)
            wall.append({'name': n, 'norm': k, 'provider': a['provider'], 'model': a['model'], 'phrasing_id': a['phrasing_id'],
                         'phrasing': a['phrasing'], 'asked_at': a['asked_at'], 'lane': a['lane'], 'outcome': 'struck', 'reason': 'mock',
                         'qloo_id': None})
    for i, why in enumerate(DIMMED_DEMO):  # fictional items, one per dimmed reason
        wall.append({'name': None, 'ph': f'dimmed {i + 1}', 'norm': f'mock dimmed {i + 1}', 'provider': None, 'model': None,
                     'phrasing_id': None, 'phrasing': None, 'asked_at': None, 'lane': 'dated', 'outcome': 'dimmed', 'reason': why,
                     'qloo_id': None})
    total = 27
    push(0, {'type': 'calls', 'done': 0, 'total': total})
    for i, w in enumerate(wall):  # the dated wall lands within a second
        push(3, {'type': 'wall_name', **{k: v for k, v in w.items() if k not in ('outcome', 'reason', 'qloo_id')}})
    push(500, {'type': 'calls', 'done': 6, 'total': total})
    push(900, {'type': 'pool', 'U': U})
    for i, w in enumerate(wall):
        push(5, {'type': 'strike', 'norm': w['norm'], 'outcome': w['outcome'], 'reason': w['reason'], 'qloo_id': w['qloo_id']})
    for d in (9, 12, 15, 18, 21, 24, 27):
        push(700, {'type': 'calls', 'done': d, 'total': total})
    picks = [card(i, tied=i in tied, spot_list=spot_list, src_answers=ans_src) for i in range(n_picks)]
    reserves = [card(7 + i, spot_list=spot_list, src_answers=ans_src) for i in range(n_res)]
    live = [l['label'] for l in loves if not l['dead']]
    for c in picks + reserves:  # a because-line only ever names a live love of this set
        if c['because'] not in live:
            c['because'] = live[0]
    for c in picks:
        push(120, {'type': 'card', **c})
    burned = []
    asked = []
    if burn and n_picks >= 7:
        for c in picks:
            asked.append({'neighbourhood': c['neighbourhood'], 'lane': 'dated', 'provider': None, 'asked_at': None, 'named': []})  # MOCK: no provider, no date
        # MOCK: one card burns on its street and the first reserve takes its place
        victim, riser = picks[2], reserves[0]
        asked[2]['named'] = [victim['name']]
        burned.append({'card_id': victim['id'], 'by': None, 'at': None, 'neighbourhood': victim['neighbourhood'], 'replaced_by': riser['id']})
        push(1800, {'type': 'burn', **burned[0]})
        picks = picks[:2] + picks[3:] + [riser]
        picks.sort(key=lambda c: (c['fit_rank'] is None, c['fit_rank'] or 0))
        reserves = reserves[1:]
    wall_n = len(wall)
    struck = sum(1 for w in wall if w['outcome'] == 'struck')
    assert all(w['name'] is None or (w['outcome'] == 'struck' and w['reason'] == 'mock' and w['qloo_id'] is None) for w in wall)
    res = {
        'status': status, 'flags': ['fake'] + list(flags), 'loves': loves,
        'city': city or STL_CITY,
        'picks': picks, 'reserves': reserves, 'wall': wall,
        'counts': {'wall': wall_n, 'asks': len(ans) + len(asked), 'P': 241, 'U': U, 'S': U - struck, 'R_mi': R_MI,
                   'answers': len(ans), 'ais': sorted({a['provider'] for a in ans}),
                   'floor': {'closed': 6, 'below_43': 22, 'outside_R': 11, 'not_venue': 6}},
        'burn': {'asked': asked, 'burned': burned} if asked else None,
        'diag': {'qloo_calls': total, 'calls': {'pool': 6, 'rescore': 15, 'ids': 5, 'cap': 1, 'total': total},
                 'rho_tp': 0.41, 'rho_res': 0.12, 'cap_keep': 23, 'cap_shared': 1,
                 'obscure_names': [None] * 4, 'known_names': [None] * 2,  # never real names in a mock: that would be a claim
                 'engine_v': 'mock', 'as_of': degraded_as_of or AS_OF, 'trace_url': None, **(diag_extra or {})},
    }
    if known:
        res['known'] = [card(i, spot_list=spot_list, src_answers=ans_src) for i in range(3)]
    push(500, {'type': 'done', 'result': res})
    return ev


MOCKS = {
    'stl-cedric': stream('stl-cedric'),
    'stl-few': stream('stl-few', status='empty_few', n_picks=5, n_res=0, burn=False),
    'stl-none': stream('stl-none', status='empty_none', n_picks=0, n_res=0, burn=False, known=True),
    'stl-partial': stream('stl-partial', status='partial', lanes_answers=16,
                          pre=[{'type': 'status', 'state': 'partial', 'text': None}]),
    'stl-dated': stream('stl-dated', status='dated_only', pre=[{'type': 'status', 'state': 'dated_only', 'text': None}]),
    'stl-degraded': stream('stl-degraded', status='degraded', burn=False, degraded_as_of=None,
                           pre=[{'type': 'status', 'state': 'degraded', 'text': None}]),
    'stl-down': stream('stl-down', end_early='degraded'),
    'stl-queued': stream('stl-queued', pre=[{'type': 'status', 'state': 'queued', 'ahead': 2, 'eta_s': 40, 'text': None},
                                            {'type': 'status', 'state': 'queued', 'ahead': 1, 'eta_s': 20, 'text': None, 'dt': 1500}]),
    'stl-limited': stream('stl-limited', end_early='limited'),
    'stl-flat': stream('stl-flat', flags=['flat'], burn=False),
    'stl-thin': stream('stl-thin', flags=['thin_taste'], tied=(1, 4, 5), burn=False),
    'stl-dead': stream('stl-dead', flags=['dead_love:Anthony Anderson'], burn=False,
                       loves=[LOVES[0], LOVES[2]] + [{'id': None, 'label': 'Anthony Anderson', 'kind': 'entity', 'type': 'person', 'dead': True}]),
    'stl-slow': stream('stl-slow'),  # 'ranking': the client stretches this one past 20 s (see api.js MOCK_SLOW)
}
if NYC_MAP:
    # MOCK New York set: placeholder cards at ten OSM places in Queens/Brooklyn that no census answer names (neighbourhood null)
    named = {norm(n) for a in nyc_answers for n in a['names']}
    pool = [f for f in json.load(open(osm_nyc))['features'] if f['name'] and norm(f['name']) not in named and f['amenity'] in ('restaurant', 'bar')]
    nyc_spots = [(None, pool[j]['lon'], pool[j]['lat']) for j in range(0, len(pool), max(1, len(pool) // 10))][:10]
    MOCKS['nyc-khruangbin'] = stream('nyc-khruangbin', burn=False, ans_src=nyc_answers, spot_list=nyc_spots,
        city={'id': None, 'name': 'New York', 'slug': 'new-york', 'center': [-73.95, 40.72], 'radius_mi': 8},
        loves=[{'id': None, 'label': 'Khruangbin', 'kind': 'entity', 'type': 'artist', 'dead': False},
               {'id': None, 'label': None, 'kind': 'entity', 'type': None, 'dead': False},
               {'id': None, 'label': None, 'kind': 'tag', 'type': None, 'dead': False}])
for k, ev in MOCKS.items():
    (SITE / 'mock' / f'{k}.ndjson').write_text(''.join(json.dumps(e, ensure_ascii=False) + '\n' for e in ev))

jdump(SITE / 'mock' / 'resolve.json', {
    '_': 'MOCK answers for GET /api/resolve when no server is up. Keys are norm(text).',
    'love': {
        'frankie beverly and maze': {'status': 'ok', 'chip': {'id': None, 'label': 'Frankie Beverly & Maze', 'kind': 'entity', 'type': 'artist'},
                                     'alternatives': [{'id': None, 'label': None, 'kind': 'entity', 'type': None}]},
        'original kings of comedy': {'status': 'ok', 'chip': {'id': None, 'label': 'The Original Kings of Comedy', 'kind': 'entity', 'type': 'movie'},
                                     'alternatives': []},
        'rib tips': {'status': 'needs_input', 'chip': {'id': None, 'label': 'Rib tips', 'kind': 'tag', 'type': 'dish'},
                     'alternatives': [{'id': None, 'label': None, 'kind': 'entity', 'type': None}]},
        'khruangbin': {'status': 'ok', 'chip': {'id': None, 'label': 'Khruangbin', 'kind': 'entity', 'type': 'artist'}, 'alternatives': []},
    },
    'city': {
        'st louis': {'status': 'ok', 'city': {'id': None, 'name': 'St. Louis', 'slug': 'st-louis', 'region': 'Missouri'}, 'alternatives': []},
        'stl': {'status': 'ok', 'city': {'id': None, 'name': 'St. Louis', 'slug': 'st-louis', 'region': 'Missouri'}, 'alternatives': []},
        'new york': {'status': 'ok', 'city': {'id': None, 'name': 'New York', 'slug': 'new-york', 'region': 'New York'}, 'alternatives': []},
        'richmond': {'status': 'needs_input', 'city': {'id': None, 'name': 'Staten Island', 'slug': None, 'region': 'New York'},
                     'alternatives': [{'id': None, 'name': 'Richmond, Virginia', 'slug': 'richmond-va', 'region': 'Virginia'}]},
    },
}, 1)

# ---------------------------------------------------------------- the real assistant answer (image 3) --
txt, model = None, None
for line in open(UNSAID / 'agent' / 'demo' / 'claude_without.jsonl'):
    d = json.loads(line)
    if d.get('type') == 'system':
        model = d.get('model')
    if d.get('type') == 'result':
        txt = d['result']
jdump(MEDIA / 'assistant.json', {
    'prompt': 'plan my Friday in St. Louis, I love Frankie Beverly & Maze, Kings of Comedy and rib tips, but nothing every AI would tell me',
    'prompt_src': 'research/round4/agentic.md (the user line of the demo runs)',
    'model': model, 'answer': txt, 'src': 'unsaid/agent/demo/claude_without.jsonl', 'asked_at': None}, 1)

print(f"census ok: gem {census['stl']['gem']['hits']}/{census['stl']['gem']['of']}, plain {plain_hits}/{len(plain)}, "
      f"asks {len(stl)}; map {len(roster['places'])} dots, {len(roster['ai'])} discs; wall {len(wall_items)} distinct names "
      f"from {len(answers)} answers; {len(MOCKS)} mock streams")
