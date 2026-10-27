"""Day-1 wall fixture: one frontier model asked from memory, no search (copied from research/exp/consensus.py).
Data only; the engine reads it with ast and never executes it. Real AI answers (names only), no Qloo data."""
NYC = {
"P1 best": ["Attaboy","Death & Co","Please Don't Tell","Employees Only","Dante","Bemelmans Bar","The Dead Rabbit","Double Chicken Please","Katana Kitten","Clover Club","Amor y Amargo","King Cole Bar","Overstory","Superbueno"],
"P2 hidden gems": ["Angel's Share","Little Branch","Raines Law Room","Bar Goto","Sunny's Bar","Montero Bar & Grill","The Back Room","Dear Irving","Beauty & Essex","Patent Pending","Nothing Really Matters","Bar Moga"],
"P3 locals": ["Jimmy's Corner","Rudy's Bar & Grill","Old Town Bar","Fanelli Cafe","Sophie's","International Bar","Montero Bar & Grill","Sunny's Bar","Union Pool","Skinny Dennis","Holiday Cocktail Lounge","Lucy's"],
"P4 not touristy": ["Burp Castle","Bohemian Hall & Beer Garden","Nothing Really Matters","Ghost Donkey","Le Boudoir","Pine Box Rock Shop","Sunny's Bar","The Campbell","Bar Moga","Bonnie's","Brooklyn Barge","Undercote"],
"P5 Khruangbin": ["Public Records","Eavesdrop","Tokyo Record Bar","Nowadays","Barbès","Bar Bayeux","Union Pool","The Sultan Room","Mood Ring","Good Room","Ornithology Jazz Club","The Lot Radio"],
"P6 Grand Budapest": ["Bemelmans Bar","King Cole Bar","The Campbell","Lobby Bar at Hotel Chelsea","Bar Pisellino","Raines Law Room","The Bar Room at The Beekman","The Nines","The Russian Tea Room","Café Carlyle","Cafe Sabarsky"],
"P7 Ten Bells": ["Ten Bells","The Four Horsemen","Le Dive","Wildair","Parcelle","Ruffian","June","Kindred","Have & Meyer","Contento","Sauced"],
"P8 all three": ["The Four Horsemen","Bemelmans Bar","Public Records","Le Dive","Bar Pisellino","Eavesdrop","Barbès","Ruffian","The Campbell","Wildair","Union Pool","Parcelle"],
}
NYC_FRESH = {
"F1 underrated": ["Dutch Kills","Fresh Kills","The Shanty","Grand Army","Fort Defiance","Bar Goto","Amor y Amargo","Sunny's Bar","The Long Island Bar","Clover Club","Ramona"],
"F2 Wes+psych-funk": ["Bemelmans Bar","The Campbell","Public Records","Bar Pisellino","Eavesdrop","Bar Bayeux","Barbès","Café Erzulie","Lobby Bar at Hotel Chelsea","The Django","Le Boudoir","Paul's Baby Grand"],
}
STL = {
"P1 best": ["Pappy's Smokehouse","Gioia's Deli","Crown Candy Kitchen","Ted Drewes Frozen Custard","Bogart's Smokehouse","Vicia","Bulrush","Union Loafers","Pastaria","Charlie Gitto's on the Hill","Blueberry Hill","Planter's House","Broadway Oyster Bar","Olive + Oak"],
"P2 hidden gems": ["Balkan Treat Box","Lona's Lil Eats","Mai Lee","Grace Meat + Three","Blues City Deli","The Fountain on Locust","Polite Society","Yellowbelly","Chiang Mai","Nixta","Sugarfire Smoke House","Taco Buddha"],
"P3 locals": ["Imo's Pizza","O'Connell's Pub","Southwest Diner","Courtesy Diner","Hodak's","Blues City Deli","Schlafly Tap Room","Pat's Bar & Grill","Gioia's Deli","Crown Candy Kitchen","Pappy's Smokehouse","Llywelyn's Pub"],
"P4 not touristy": ["Venice Cafe","The Royale","Platypus","Retreat Gastropub","The Fountain on Locust","Mangia Italiano","Small Batch","Polite Society","Rooster","Bar Les Frères","Yellowbelly"],
"P5 Frankie Beverly": ["BB's Jazz, Blues & Soups","Jazz St. Louis","Broadway Oyster Bar","Beale on Broadway","Blueberry Hill","Sweetie Pie's","The Pageant","Delmar Hall","Robbie's House of Jazz","Gourmet Soul"],
"P6 Kings of Comedy": ["Helium Comedy Club","Funny Bone","Sweetie Pie's","Pappy's Smokehouse","Blueberry Hill","Ballpark Village","Hodak's","Crown Candy Kitchen","BB's Jazz, Blues & Soups"],
"P7 rib tips": ["Pappy's Smokehouse","Bogart's Smokehouse","Sugarfire Smoke House","Salt + Smoke","Roper's Ribs","Smoki O's","Adam's Smokehouse","Beast Craft BBQ","Hendricks BBQ","Phil's Bar-B-Que","Big Baby Q","Shaved Duck"],
"P8 all three": ["Pappy's Smokehouse","BB's Jazz, Blues & Soups","Smoki O's","Sweetie Pie's","Broadway Oyster Bar","Bogart's Smokehouse","Blueberry Hill","Jazz St. Louis","Helium Comedy Club","Roper's Ribs","Beale on Broadway","Hodak's"],
}
STL_FRESH = {
"F1 underrated": ["Indo","Sado","Nudo House","Balkan Treat Box","Lona's Lil Eats","Mai Lee","Elmwood","Sardella","Yellowbelly","Blues City Deli","Steve's Hot Dogs"],
"F2 soul+jazz": ["Sweetie Pie's","BB's Jazz, Blues & Soups","Gourmet Soul","Robbie's House of Jazz","Jazz St. Louis","Broadway Oyster Bar","Smoki O's","Kingside Diner","Beale on Broadway","Blueberry Hill"],
}
JASON_STL = {  # taste-conditioned only; P1-P4 generic are identical to STL
"P5 Sinatra": ["Jazz St. Louis","The Tenderloin Room","Charlie Gitto's on the Hill","Tony's","Kemoll's","Al's Restaurant","Cafe Napoli","Planter's House","Herbie's","Blueberry Hill"],
"P6 Rounders": ["River City Casino","Ameristar Casino","Lumière Place","Ballpark Village","The Tenderloin Room","Kreis Steakhouse","Morton's The Steakhouse","Mike Shannon's Steaks and Seafood","Planter's House"],
"P7 Carbone": ["Charlie Gitto's on the Hill","Pastaria","Lorenzo's Trattoria","Cunetto House of Pasta","Dominic's on the Hill","Zia's on the Hill","Giovanni's on the Hill","Tony's","Mangia Italiano","Acero","Gioia's Deli","Rigazzi's"],
"P8 all three": ["Charlie Gitto's on the Hill","The Tenderloin Room","Tony's","Jazz St. Louis","Kemoll's","Planter's House","Dominic's on the Hill","Pastaria","Kreis Steakhouse","Gioia's Deli","Blueberry Hill","Herbie's"],
}
