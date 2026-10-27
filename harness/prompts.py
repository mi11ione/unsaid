"""Phrasing set for the Claude census (round 4, Package A). Frozen before any run.
Each city gets 64 asks: 14 generic-mainstream, 16 hidden-gem family, 12 Cedric-taste,
12 Jason-taste, 10 strangers. One uniform JSON suffix is appended to every ask."""
import json, random

SUFFIX = (' Reply with only JSON: an array of 8-12 objects like '
          '{"name": "...", "neighbourhood": "..."}. No other text.')

CITIES = {
    "stl": {"full": "St. Louis", "short": "STL", "alt": "St Louis"},
    "nyc": {"full": "New York", "short": "NYC", "alt": "Manhattan or Brooklyn"},
}

GENERIC = [  # mainstream: what a person types first
    "best places to eat and drink in {full}",
    "where should I eat in {full}?",
    "top restaurants in {full}",
    "best bars in {full}",
    "what are the must-try restaurants in {full}",
    "going to {full} this weekend, where should we eat and drink",
    "good dinner spots {short}",
    "best food in {alt}",
    "where to get a drink in {full} tonight",
    "first time in {full}, what are the places I have to eat at",
    "what's good to eat around {full}",
    "recommend some restaurants and bars in {full}",
    "where do locals eat in {full}?",
    "what do people from {full} actually eat, and where",
]
HIDDEN = [  # hidden-gem family: explicitly asks off the consensus
    "hidden gems to eat and drink in {full}",
    "{full} hidden gem restaurants",
    "best hidden gems in {alt} for food",
    "not touristy places to eat in {full}",
    "where to eat in {full} that isn't touristy",
    "underrated restaurants in {full}",
    "most underrated bars and restaurants {short}",
    "places to eat in {full} most visitors never hear of",
    "restaurants in {full} that tourists never find out about",
    "tell me somewhere to eat in {full} that nobody else would tell me",
    "where to eat in {full}, but skip anything every AI would say",
    "I've already done all the famous spots in {full}. where do I go now?",
    "off the beaten path food and drinks in {full}",
    "local secret spots to eat in {full}",
    "under the radar restaurants and bars in {alt}",
    "places in {full} that aren't on every list",
]
CEDRIC = [  # The Original Kings of Comedy, Frankie Beverly & Maze, rib tips
    "I love Frankie Beverly & Maze, The Original Kings of Comedy and rib tips. where should I eat and drink in {full}?",
    "where can I get good rib tips in {full}",
    "best rib tips in {short}?",
    "I'm a huge Frankie Beverly and Maze fan, where should I go out to eat and drink in {full}",
    "places in {full} for someone who loves The Original Kings of Comedy",
    "rib tips, old school R&B, stand-up comedy. plan where I eat and drink in {full}",
    "where would a Frankie Beverly & Maze fan eat in {full}?",
    "I'm into Kings of Comedy, Maze, and good barbecue. restaurants and bars in {full}?",
    "best soul food and barbecue in {full}, I live for rib tips",
    "where to eat in {full} if your favorite song is Before I Let Go",
    "I love rib tips and old school comedy, where should I eat in {alt}",
    "hidden gems in {full} for a rib tips and Frankie Beverly kind of person",
]
JASON = [  # Frank Sinatra, Rounders, Carbone
    "I love Frank Sinatra, Rounders and Carbone. where should I eat and drink in {full}?",
    "restaurants in {full} for someone who loves Carbone",
    "where's the Carbone of {full}?",
    "best old-school Italian in {full}, like Carbone",
    "I'm a big Sinatra fan, where should I eat and drink in {full}",
    "places in {full} for a guy whose favorite movie is Rounders",
    "steakhouses and red sauce Italian in {short}, Sinatra playing ideally",
    "where would Frank Sinatra eat in {full} today?",
    "I love Rounders, poker, Sinatra and a great veal parm. dinner and drinks in {full}?",
    "classic swanky bars in {full} for a Sinatra guy",
    "if I like Carbone what should I try in {alt}",
    "hidden gems in {full} for a Carbone and Sinatra kind of guy",
]
STRANGERS = [
    "visiting my mom in {full} next week, she's 74 and doesn't like loud places. where should we eat?",
    "broke college student in {full}, where can I eat well for under $15",
    "my girlfriend is vegan and I'm not, where can we both eat in {full}",
    "taking my two kids (6 and 9) to {full}, where do we eat that won't be a nightmare",
    "in {full} for a work conference, need somewhere good to take a client and a bar after",
    "anniversary dinner in {full}, 10 years, want somewhere special",
    "just moved to {full}, where should I go to feel like a local",
    "nurse working nights in {full}, where can I get good food late",
    "food snob from Chicago visiting {full}, impress me",
    "group of 8 for a birthday in {full}, where do we eat and then drink",
]

FAMILIES = [("generic", GENERIC, None), ("hidden", HIDDEN, None),
            ("taste", CEDRIC, "cedric"), ("taste", JASON, "jason"),
            ("stranger", STRANGERS, None)]


def build(seed=20261027):
    asks = []
    for ck, c in CITIES.items():
        for fam, lst, person in FAMILIES:
            for i, p in enumerate(lst):
                ph = p.format(**c)
                asks.append({"id": f"{ck}-{person or fam}-{i:02d}", "city": ck, "family": fam,
                             "person": person, "phrasing": ph, "prompt": ph + SUFFIX})
    random.Random(seed).shuffle(asks)
    for k, a in enumerate(asks):
        a["order"] = k
    return asks


if __name__ == "__main__":
    asks = build()
    print(json.dumps(asks, indent=1))
