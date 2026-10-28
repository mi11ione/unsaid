"""Cities and the location half of the base filters (UNSAID.md §3.1).

  NYC:     filter.location=<locality UUID> (from C1), then a client distance check: 8 mi from the typed borough's
           centroid (default Manhattan).
  STL, LA: filter.location=POINT(<lon> <lat>) & filter.location.radius=<metres> (STL 16093 = 10 mi, LA 24140 = 15 mi).
           Longitude first. The same radius is applied again client side, so the floor line counts it.
Any other city: C1 /search (locality, region checked) and a POINT with a 10 mi radius.
"""
import math
import re

MI = 1609.344

CITIES = {
    "nyc": {"name": "New York City", "slug": "new-york", "query": "New York City", "region": "New York",
            "mode": "locality", "radius_mi": 10, "center": (40.7831, -73.9712),       # Manhattan centroid
            "aliases": ["new york", "new york city", "nyc", "ny", "manhattan", "brooklyn", "queens", "bronx",
                        "the bronx", "staten island"]},
    "stl": {"name": "St. Louis", "slug": "st-louis", "query": "St. Louis", "region": "Missouri",
            "mode": "point", "radius_mi": 15, "radius_m": 24140, "center": (38.6270, -90.1994),
            "aliases": ["st. louis", "st louis", "saint louis", "stl", "st-louis"]},
    "la": {"name": "Los Angeles", "slug": "los-angeles", "query": "Los Angeles", "region": "California",
           "mode": "point", "radius_mi": 15, "radius_m": 24140, "center": (34.0522, -118.2437),
           "aliases": ["los angeles", "la", "l.a.", "los-angeles"]},
}
BOROUGHS = {  # centroid of the typed borough (lat, lon)
    "manhattan": (40.7831, -73.9712), "brooklyn": (40.6782, -73.9442), "queens": (40.7282, -73.7949),
    "bronx": (40.8448, -73.8648), "the bronx": (40.8448, -73.8648), "staten island": (40.5795, -74.1502),
}
AMBIGUOUS = {  # a bare name Qloo resolves to the wrong place (the Richmond trap)
    "richmond": ["Staten Island, New York", "Richmond, Virginia"],
    "portland": ["Portland, Oregon", "Portland, Maine"],
    "springfield": ["Springfield, Illinois", "Springfield, Missouri", "Springfield, Massachusetts"],
}


def _key(text):
    return re.sub(r"\s+", " ", (text or "").strip().lower().rstrip("."))


def lookup(text):
    """Text -> (city key, borough or None) for the configured cities, else (None, None)."""
    t = _key(text)
    t0 = t.split(",")[0].strip()
    for k, c in CITIES.items():
        if t in c["aliases"] or t0 in c["aliases"]:
            b = t0 if k == "nyc" and t0 in BOROUGHS else None
            return k, b
    return None, None


def haversine_mi(a, b):
    (la1, lo1), (la2, lo2) = a, b
    p1, p2 = math.radians(la1), math.radians(la2)
    dp, dl = p2 - p1, math.radians(lo2 - lo1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 3958.7613 * math.asin(math.sqrt(h))


def location_params(city):
    """The location part of the base filters for a resolved city dict."""
    if city.get("mode") == "locality" and city.get("id"):
        return {"filter.location": city["id"]}
    lat, lon = city["center_latlon"]
    return {"filter.location": "POINT(%s %s)" % (_num(lon), _num(lat)),   # WKT: X (lon) first
            "filter.location.radius": int(city.get("radius_m") or round(city["radius_mi"] * MI))}


def _num(x):
    return ("%.6f" % x).rstrip("0").rstrip(".")


def public(city):
    """CONTRACT.md city: {id, name, slug, center:[lon,lat], radius_mi}."""
    lat, lon = city["center_latlon"]
    return {"id": city.get("id"), "name": city["name"], "slug": city["slug"], "center": [lon, lat],
            "radius_mi": city["radius_mi"], "borough": city.get("borough"), "mode": city.get("mode"),
            "key": city.get("key")}
