"""The 10 seed sets per city for the day-1 kill tests. (text, type hint); type None means "let /search decide".
NYC A and STL cedric/jason are the cases in unsaid-v2.md §3; the rest span artist/film/TV/brand/dish/place mixes.
Type hints map to /search `types`; "tag" goes straight to /v2/tags."""
SEED_SETS = {
    "nyc": [
        ("A", [("Khruangbin", "artist"), ("The Grand Budapest Hotel", "movie"), ("Ten Bells", "place")]),
        ("B", [("Radiohead", "artist"), ("Lost in Translation", "movie"), ("Norwegian Wood", "book")]),
        ("C", [("Bad Bunny", "artist"), ("Narcos", "tv_show"), ("tacos al pastor", "tag")]),
        ("D", [("Taylor Swift", "artist"), ("Gilmore Girls", "tv_show"), ("Levain Bakery", "place")]),
        ("E", [("Kendrick Lamar", "artist"), ("Atlanta", "tv_show"), ("Popeyes", "brand")]),
        ("F", [("Phoebe Bridgers", "artist"), ("Lady Bird", "movie"), ("natural wine", "tag")]),
        ("G", [("Frank Sinatra", "artist"), ("The Godfather", "movie"), ("Carbone", "place")]),
        ("H", [("Beyonce", "artist"), ("Insecure", "tv_show"), ("Sweetgreen", "brand")]),
        ("I", [("Bob Dylan", "artist"), ("Inside Llewyn Davis", "movie"), ("Joe's Pizza", "place")]),
        ("J", [("Daft Punk", "artist"), ("Blade Runner 2049", "movie"), ("ramen", "tag")]),
    ],
    "stl": [
        ("cedric", [("The Original Kings of Comedy", "movie"), ("Frankie Beverly & Maze", "artist"), ("rib tips", "tag")]),
        ("jason", [("Frank Sinatra", "artist"), ("Rounders", "movie"), ("Carbone", "place")]),
        ("cedric2", [("Al Green", "artist"), ("Barbershop", "movie"), ("rib tips", "tag")]),
        ("cedric3", [("Frankie Beverly & Maze", "artist"), ("The Neighborhood", "tv_show"), ("Joe Turner's Come and Gone", None)]),
        ("cedric4", [("The Original Kings of Comedy", "movie"), ("Al Green", "artist"), ("soul food", "tag")]),
        ("S6", [("Nelly", "artist"), ("The Blues Brothers", "movie"), ("toasted ravioli", "tag")]),
        ("S7", [("Taylor Swift", "artist"), ("Ted Lasso", "tv_show"), ("Starbucks", "brand")]),
        ("S8", [("Jay-Z", "artist"), ("Paid in Full", "movie"), ("Budweiser", "brand")]),
        ("S9", [("Wilco", "artist"), ("Lady Bird", "movie"), ("natural wine", "tag")]),
        ("S10", [("Kendrick Lamar", "artist"), ("Atlanta", "tv_show"), ("Popeyes", "brand")]),
    ],
}
SEED_SETS["la"] = [  # Cedric's fallback city if St. Louis fails gate B (UNSAID.md §4)
    ("cedric", [("The Original Kings of Comedy", "movie"), ("Frankie Beverly & Maze", "artist"), ("rib tips", "tag")]),
]
CITY_QUERY = {"nyc": ("New York City", "New York"), "stl": ("St. Louis", "Missouri"), "la": ("Los Angeles", "California")}
STRANGERS = ("stl", "cedric", "jason")  # the two-strangers test


def get(city, sid):
    for k, loves in SEED_SETS[city]:
        if k == sid:
            return loves
    raise KeyError(sid)
