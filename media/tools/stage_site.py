"""Stage the site for upload (deploy-site.sh): in a copy of site/, each stored set's `wall` (3 MB of its 3.6 MB) moves to
<set>.wall.json, fetched by the page only when the visitor opens the list, pastes an answer or shares; and the live
index gets each set's photo thumbnails (name, image, neighbourhood) so the landing never loads a whole set.
The repo's site/data/live stays as the regeneration wrote it (other tools read it).
  python3 -I media/tools/stage_site.py <staged site dir>"""
import json, os, sys

live = os.path.join(sys.argv[1], "data", "live")
idx_p = os.path.join(live, "index.json")
idx = json.load(open(idx_p)) if os.path.exists(idx_p) else {"sets": []}
moved = 0
for s in idx.get("sets", []):
    p = os.path.join(live, s.get("file") or "")
    if not s.get("file") or not os.path.exists(p):
        continue
    j = json.load(open(p))
    R = j.get("result", j)
    s["thumbs"] = [{"name": c.get("name"), "image": c.get("image"), "neighbourhood": c.get("neighbourhood")}
                   for c in R.get("picks", []) if c.get("image")]
    if isinstance(R.get("wall"), list):
        json.dump({"wall": R.pop("wall")}, open(p[:-5] + ".wall.json", "w"), ensure_ascii=False, separators=(",", ":"))
        json.dump(j, open(p, "w"), ensure_ascii=False, separators=(",", ":"))
        moved += 1
json.dump(idx, open(idx_p, "w"), ensure_ascii=False, indent=1)
print("staged: %d set walls split into <set>.wall.json; thumbnails in index.json" % moved)
