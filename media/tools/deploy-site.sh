#!/bin/zsh
# Check and deploy unsaid/site to Cloudflare Pages (direct upload, project "unsaid").
#   zsh media/tools/deploy-site.sh            check, render the OG image, deploy
#   CHECK_ONLY=1 zsh media/tools/deploy-site.sh   check only
# 1. renders the Open Graph image (the Cedric share card, with the site's address) into site/data/live/og-cedric.png
# 2. fails if any ⟦placeholder⟧ reaches a visitor: static HTML/JSON outside data/mock, and the rendered text of the
#    landing page, /agents, every try-these set and Cedric's card, name and popularity sheets, at 390 and 1440 px
# 3. deploys with wrangler (site/data/live is gitignored and ships only through this upload)
set -e
cd "$(dirname "$0")/../.."
HOST=$(python3 -c "import json;print(json.load(open('site/data/config.json')).get('site',''))")
PORT=$((8900 + RANDOM % 90))
UNSAID_API=http://127.0.0.1:9 python3 -I media/tools/devserver.py $PORT >/dev/null 2>&1 &
SRV=$!; trap "kill $SRV 2>/dev/null" EXIT; sleep 0.8
B="http://127.0.0.1:$PORT"

if [[ -f site/data/live/stl_stl-cedric.json ]]; then
  node media/tools/cdp.mjs shot "file://$PWD/media/share.html?src=../site/data/live/stl_stl-cedric.json&site=$HOST" site/data/live/og-cedric.png 1080 1350 1 >/dev/null
  echo "og image: site/data/live/og-cedric.png"
fi

# neighbourhood names for the paste box (a neighbourhood is never matched as a place: "The Hill")
python3 -I -c "import json;d=json.load(open('harness/neighbourhoods.json'));json.dump({'_':'neighbourhood names (harness/neighbourhoods.json, OpenStreetMap): the paste box never matches these as places','cities':d['cities']},open('site/data/hoods.json','w'),ensure_ascii=False)"

# the held-out table on the popularity sheet (the k12 run and k14 labels freeze_numbers reads)
python3 -I media/tools/build_wall_effect.py || true

# similar vs unrelated tastes, for the "Is this just obscure places?" sheet (from the regenerated store, when present)
python3 -I media/tools/build_overlap.py || true

bad=0
# static: no bracket in shipped HTML or JSON (mock streams are marked MOCK and never shown without ?mock=)
if grep -rl "⟦" site --include='*.html' --include='*.json' | grep -v '^site/data/mock/'; then echo "FAIL: ⟦ in the files above"; bad=1; fi
# rendered: what a visitor reads
SETS=$(python3 -c "import json;print(' '.join(s['id'] for s in json.load(open('site/data/try.json'))['sets']))")
W='new Promise(r=>setTimeout(r,2500))'
check() {  # url width [js to run first]
  local js=${3:-0}
  local out=$(node media/tools/cdp.mjs eval "$1" "(async()=>{await $W;await ($js);await new Promise(r=>setTimeout(r,600));return document.body.innerText.includes('⟦')?'BAD':'ok'})()" $2 900 2>/dev/null)
  [[ $out == '"ok"' ]] || { echo "FAIL: ⟦ on $1 at $2 px ($out)"; bad=1; }
}
for w in 390 1440; do
  check "$B/index.html" $w
  check "$B/agents" $w
  for s in ${=SETS}; do check "$B/index.html#/r?set=$s" $w; done
  check "$B/index.html#/r?set=stl-cedric" $w "document.querySelector('.card').click()"
  check "$B/index.html#/r?set=stl-cedric" $w "document.getElementById('lnk-pop').click()"
  check "$B/index.html#/r?set=stl-cedric" $w "document.querySelector('.nm button').click()"
done
[[ $bad == 0 ]] || { echo "not deployed: placeholders would reach visitors"; exit 1; }
echo "placeholder check: ok"
[[ -n $CHECK_ONLY ]] && exit 0
cd site && npx -y wrangler@3 pages deploy . --project-name unsaid --branch main --commit-dirty=true
