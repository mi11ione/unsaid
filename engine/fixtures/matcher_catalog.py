"""Offline golden set for the matcher (K4), built over the 136 labelled names in research/exp/labels.py.

For each AI-named string: the Qloo-style record(s) it should strike. Names are my best guess at how Qloo
(Google-style place names) spells them, deliberately the harder spelling where unsure:
"PDT" for "Please Don't Tell", "Bemelmans Bar at The Carlyle", "Imo's Pizza" three times, branch suffixes.
in_pool=False means the record exists in Qloo but not in the pool U: closed, a seed, or not eat & drink
(music venue, comedy club, hotel), so it is "outside_pool" on the wall and must strike nothing.

DECOYS are real-looking confusables that are in U and named by nobody. Striking one is a false strike
(precision cost, the safe direction). FILLER are invented names that must never be struck.

Day 1 replaces this file with the real U of each seed set, labelled by a human (k4 live run dumps it).
"""
P, OUT = True, False

NYC = {
    "Attaboy": [("Attaboy", P)],
    "Death & Co": [("Death & Co New York", P)],
    "Please Don't Tell": [("PDT", P)],
    "Employees Only": [("Employees Only", P)],
    "Dante": [("Dante", P), ("Dante West Village", P)],
    "Bemelmans Bar": [("Bemelmans Bar at The Carlyle", P), ("The Carlyle, A Rosewood Hotel", OUT)],
    "The Dead Rabbit": [("The Dead Rabbit Grocery and Grog", P)],
    "Double Chicken Please": [("Double Chicken Please", P)],
    "Katana Kitten": [("Katana Kitten", P)],
    "Clover Club": [("Clover Club", P)],
    "Amor y Amargo": [("Amor y Amargo", P)],
    "King Cole Bar": [("King Cole Bar & Lounge", P)],
    "Overstory": [("Overstory", P)],
    "Superbueno": [("Superbueno", P)],
    "Angel's Share": [("Angel's Share", P)],
    "Little Branch": [("Little Branch", P)],
    "Raines Law Room": [("Raines Law Room", P), ("Raines Law Room at The William", P)],
    "Bar Goto": [("Bar Goto", P), ("Bar Goto Niban", P)],
    "Sunny's Bar": [("Sunny's Bar", P)],
    "Montero Bar & Grill": [("Montero's Bar & Grill", P)],
    "The Back Room": [("The Back Room", P)],
    "Dear Irving": [("Dear Irving", P), ("Dear Irving on Hudson", P)],
    "Beauty & Essex": [("Beauty & Essex", P)],
    "Patent Pending": [("Patent Pending", P)],
    "Nothing Really Matters": [("Nothing Really Matters", P)],
    "Bar Moga": [("Bar Moga", P)],
    "Jimmy's Corner": [("Jimmy's Corner", P)],
    "Rudy's Bar & Grill": [("Rudy's Bar & Grill", P)],
    "Old Town Bar": [("Old Town Bar & Restaurant", P)],
    "Fanelli Cafe": [("Fanelli's Cafe", P)],
    "Sophie's": [("Sophie's", P)],
    "International Bar": [("International Bar", P)],
    "Union Pool": [("Union Pool", P)],
    "Skinny Dennis": [("Skinny Dennis", P)],
    "Holiday Cocktail Lounge": [("Holiday Cocktail Lounge", P)],
    "Lucy's": [("Lucy's", P)],
    "Burp Castle": [("Burp Castle", P)],
    "Bohemian Hall & Beer Garden": [("Bohemian Hall and Beer Garden", P)],
    "Ghost Donkey": [("Ghost Donkey", P)],
    "Le Boudoir": [("Le Boudoir", P)],
    "Pine Box Rock Shop": [("Pine Box Rock Shop", P)],
    "The Campbell": [("The Campbell Bar", P)],
    "Bonnie's": [("Bonnie's", P)],
    "Brooklyn Barge": [("Brooklyn Barge", P)],
    "Undercote": [("Undercote", P)],
    "Public Records": [("Public Records", P)],
    "Eavesdrop": [("Eavesdrop", P)],
    "Tokyo Record Bar": [("Tokyo Record Bar", P)],
    "Nowadays": [("Nowadays", OUT)],
    "Barbès": [("Barbes", P)],
    "Bar Bayeux": [("Bar Bayeux", P)],
    "The Sultan Room": [("The Sultan Room", OUT)],
    "Mood Ring": [("Mood Ring", P)],
    "Good Room": [("Good Room", OUT)],
    "Ornithology Jazz Club": [("Ornithology Jazz Club", P), ("Ornithology Jazz Club Bushwick", P)],
    "The Lot Radio": [("The Lot Radio", OUT)],
    "Lobby Bar at Hotel Chelsea": [("Lobby Bar", P), ("Hotel Chelsea", OUT)],
    "Bar Pisellino": [("Bar Pisellino", P)],
    "The Bar Room at The Beekman": [("The Bar Room", P), ("The Beekman, A Thompson Hotel", OUT)],
    "The Nines": [("The Nines", P)],
    "The Russian Tea Room": [("The Russian Tea Room", P)],
    "Café Carlyle": [("Café Carlyle", OUT)],
    "Cafe Sabarsky": [("Café Sabarsky", P)],
    "Ten Bells": [("The Ten Bells", OUT)],  # the seed place: excluded from results
    "The Four Horsemen": [("The Four Horsemen", P)],
    "Le Dive": [("Le Dive", P)],
    "Wildair": [("Wildair", P)],
    "Parcelle": [("Parcelle Wine", P), ("Parcelle Wine Bar Greenwich", P)],
    "Ruffian": [("Ruffian Wine Bar & Chef's Table", P)],
    "June": [("June Wine Bar", P)],
    "Kindred": [("Kindred", P)],
    "Have & Meyer": [("Have & Meyer", P)],
    "Contento": [("Contento", P)],
    "Sauced": [("Sauced", P)],
}

STL = {
    "Pappy's Smokehouse": [("Pappy's Smokehouse", P)],
    "Gioia's Deli": [("Gioia's Deli", P), ("Gioia's Deli Downtown", P)],
    "Crown Candy Kitchen": [("Crown Candy Kitchen", P)],
    "Ted Drewes Frozen Custard": [("Ted Drewes Frozen Custard", P), ("Ted Drewes Frozen Custard - Grand", P)],
    "Bogart's Smokehouse": [("Bogart's Smokehouse", P)],
    "Vicia": [("Vicia", P)],
    "Bulrush": [("Bulrush STL", P)],
    "Union Loafers": [("Union Loafers Cafe and Bread Bakery", P)],
    "Pastaria": [("Pastaria", P), ("Pastaria Deli & Wine", P)],
    "Charlie Gitto's on the Hill": [("Charlie Gitto's On The Hill", P), ("Charlie Gitto's Downtown", P)],
    "Blueberry Hill": [("Blueberry Hill", P), ("The Duck Room at Blueberry Hill", OUT)],
    "Planter's House": [("Planter's House", P)],
    "Broadway Oyster Bar": [("Broadway Oyster Bar", P)],
    "Olive + Oak": [("Olive and Oak", P)],
    "Balkan Treat Box": [("Balkan Treat Box", P)],
    "Lona's Lil Eats": [("Lona's Lil Eats", P)],
    "Mai Lee": [("Mai Lee Restaurant", P)],
    "Grace Meat + Three": [("Grace Meat & Three", OUT)],  # closed 13 Sep 2026
    "Blues City Deli": [("Blues City Deli", P)],
    "The Fountain on Locust": [("The Fountain on Locust", P)],
    "Polite Society": [("Polite Society", P)],
    "Yellowbelly": [("Yellowbelly", P)],
    "Chiang Mai": [("Chiang Mai", P)],
    "Nixta": [("Nixta", P)],
    "Sugarfire Smoke House": [("Sugarfire Smokehouse - Olivette", P), ("Sugarfire Smokehouse Downtown", P)],
    "Taco Buddha": [("Taco Buddha", P), ("Taco Buddha Kirkwood", P)],
    "Imo's Pizza": [("Imo's Pizza", P), ("Imo's Pizza", P), ("Imo's Pizza", P)],
    "O'Connell's Pub": [("O'Connell's Pub", P)],
    "Southwest Diner": [("Southwest Diner", P)],
    "Courtesy Diner": [("Courtesy Diner", P), ("Courtesy Diner - Hampton", P)],
    "Hodak's": [("Hodak's Restaurant & Bar", P)],
    "Schlafly Tap Room": [("Schlafly Taproom", P), ("Schlafly Bottleworks", P)],
    "Pat's Bar & Grill": [("Pat's Bar & Grill", P)],
    "Llywelyn's Pub": [("Llywelyn's Pub", P), ("Llywelyn's Pub - Webster Groves", P)],
    "Venice Cafe": [("Venice Cafe", P)],
    "The Royale": [("The Royale", P)],
    "Platypus": [("Platypus", P)],
    "Retreat Gastropub": [("Retreat Gastropub", P)],
    "Mangia Italiano": [("Mangia Italiano", P)],
    "Small Batch": [("Small Batch", P)],
    "Rooster": [("Rooster", P), ("Rooster South Grand", P)],
    "Bar Les Frères": [("Bar Les Freres", P)],
    "BB's Jazz, Blues & Soups": [("BB's Jazz Blues & Soups", P)],
    "Jazz St. Louis": [("Jazz St. Louis", OUT)],
    "Beale on Broadway": [("Beale on Broadway", P)],
    "Sweetie Pie's": [("Sweetie Pie's", OUT)],  # closed Sep 2022
    "The Pageant": [("The Pageant", OUT)],
    "Delmar Hall": [("Delmar Hall", OUT)],
    "Robbie's House of Jazz": [("Robbie's House of Jazz", OUT)],
    "Gourmet Soul": [],  # unverifiable: not in Qloo
    "Helium Comedy Club": [("Helium Comedy Club", OUT)],
    "Funny Bone": [("The Funny Bone", OUT)],
    "Ballpark Village": [("Ballpark Village", OUT)],
    "Salt + Smoke": [("Salt + Smoke BBQ", P), ("Salt + Smoke - Delmar Loop", P)],
    "Roper's Ribs": [("Roper's Ribs", P)],
    "Smoki O's": [("Smoki O's BBQ", P)],
    "Adam's Smokehouse": [("Adam's Smokehouse", P)],
    "Beast Craft BBQ": [("Beast Craft BBQ Co.", P)],
    "Hendricks BBQ": [("Hendricks BBQ", P)],
    "Phil's Bar-B-Que": [("Phil's BBQ", P)],
    "Big Baby Q": [("Big Baby Q and Smokehouse", P)],
    "Shaved Duck": [("The Shaved Duck", P)],
}

DECOYS = {
    "nyc": ["Union Hall", "Lucy's Cantina Royale", "Sophie's Cuban Cuisine", "The Back Room at One57",
            "Death Ave", "Old Town Hot Pot", "Little Owl", "Public House", "Bar Primi", "Kindred Spirits Pub"],
    "stl": ["Pat Connolly Tavern", "Venice Pizza", "Mai Thai", "Small Change", "Broadway Bistro",
            "Union Studio", "Taco Circus", "Blues Fest Cafe"],
}

_SYL = ["mar", "vel", "tor", "quin", "bel", "sor", "dra", "lin", "fen", "osk", "pell", "rav", "zan", "thu", "corb",
        "esk", "lom", "nyr", "vash", "ilo"]
_SUF = ["Tavern", "Kitchen", "Bar", "Cafe", "Room", "Social", "Provisions", "Wine Bar", "Grill", "House"]


def filler(city, n=60):
    """Invented names (two syllables + a generic suffix), deterministic, distinct per city."""
    off = 0 if city == "nyc" else 7
    out = []
    for i in range(len(_SYL)):
        for j in range(len(_SYL)):
            if i == j:
                continue
            a = _SYL[(i + off) % len(_SYL)] + _SYL[(j + 2 * off) % len(_SYL)]
            out.append("%s %s" % (a.capitalize(), _SUF[(i * 7 + j) % len(_SUF)]))
            if len(out) == n:
                return out
    return out


def build(city):
    """-> (pool, catalog, truth): pool = U records, catalog = every Qloo record (for /search), truth = named IDs."""
    table = NYC if city == "nyc" else STL
    pool, catalog, named = [], [], set()
    for raw, recs in table.items():
        for j, (qname, inpool) in enumerate(recs):
            eid = "%s:%s:%d" % (city, raw, j)
            rec = {"entity_id": eid, "name": qname, "raw": raw}
            catalog.append(rec)
            if inpool:
                pool.append(rec)
                named.add(eid)
    for d in DECOYS[city]:
        rec = {"entity_id": "%s:decoy:%s" % (city, d), "name": d, "raw": None}
        pool.append(rec)
        catalog.append(rec)
    for f in filler(city):
        rec = {"entity_id": "%s:filler:%s" % (city, f), "name": f, "raw": None}
        pool.append(rec)
        catalog.append(rec)
    return pool, catalog, named
