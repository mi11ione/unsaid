#!/bin/zsh
# Screenshots of the static site, served the way Pages serves it (no /api: the page falls back to MOCK).
#   zsh media/tools/shoot-site.sh            (render.sh site calls this)
set -e
cd "$(dirname "$0")/.."
OUT=shots/site; mkdir -p $OUT
PORT=$((8700 + RANDOM % 200))
UNSAID_API=http://127.0.0.1:9 python3 -I tools/devserver.py $PORT >/dev/null 2>&1 &   # static site; /api answers 404 (no engine)
SRV=$!
trap "kill $SRV 2>/dev/null" EXIT
sleep 0.8
B="http://127.0.0.1:$PORT"
# a fixed wait: every stored set and ?speed=8 mock settles within ~2 s (polling inside the CDP evaluate can stall)
DONE='new Promise(r=>setTimeout(r,4000))'
AT() { echo "new Promise(r=>setTimeout(r,$1))"; }
shot() { node tools/cdp.mjs shot "$@" >/dev/null && echo "$2"; }
FILL='(async()=>{const s=(q,v)=>{const i=document.querySelector(q);i.focus();i.value=v;i.dispatchEvent(new Event("input"));i.dispatchEvent(new Event("blur"));};
 s("input[data-i=\"0\"]","Frankie Beverly & Maze");s("input[data-i=\"1\"]","Original Kings of Comedy");s("input[data-i=\"2\"]","rib tips");s("#city","Richmond");
 await new Promise(r=>setTimeout(r,600));})()'

for W in 1600 390; do
  D=$([[ $W == 390 ]] && echo 2 || echo 1)
  shot "$B/index.html" $OUT/s1-input-$W.png $W 0 $D
  shot "$B/index.html" $OUT/s1-needs-input-$W.png $W 0 $D "$FILL"
  shot "$B/index.html?mock=stl-cedric#/r?city=st-louis" $OUT/s2-run-2s-$W.png $W 0 $D "$(AT 2300)"
  shot "$B/index.html?mock=stl-cedric#/r?city=st-louis" $OUT/s2-run-burn-$W.png $W 0 $D "$(AT 11500)"
  shot "$B/index.html?speed=8#/r?set=stl-cedric" $OUT/s2-result-$W.png $W 0 $D "$DONE"
  shot "$B/index.html?speed=8#/r?set=stl-cedric" $OUT/s3-card-back-$W.png $W 1000 $D "$DONE.then(()=>{document.querySelector('.card').click();document.querySelector('details.log').open=true})"
  shot "$B/index.html?speed=8#/r?set=stl-cedric" $OUT/s4-popularity-$W.png $W 1000 $D "$DONE.then(()=>document.getElementById('lnk-pop').click())"
  shot "$B/index.html?speed=8#/r?set=stl-cedric" $OUT/s2-human-strike-$W.png $W 0 $D "$DONE.then(()=>{const c=document.querySelectorAll('.card')[1];c.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true}));return new Promise(r=>setTimeout(r,1300))})"
  shot "$B/index.html?speed=8#/r?set=stl-cedric" $OUT/s2-share-sheet-$W.png $W 1000 $D "$DONE.then(()=>document.getElementById('lnk-share').click())"
  shot "$B/agents.html" $OUT/agents-$W.png $W 0 $D
done
shot "$B/index.html?speed=8#/r?set=stl-cedric" $OUT/s2-result-600.png 600 0 1 "$DONE"
for M in stl-few stl-none stl-partial stl-dated stl-degraded stl-down stl-limited stl-flat stl-thin stl-dead; do
  shot "$B/index.html?mock=$M&speed=8#/r?city=st-louis" $OUT/state-$M-1600.png 1600 0 1 "$DONE"
done
shot "$B/index.html?mock=stl-thin&speed=8#/r?city=st-louis" $OUT/state-stl-thin-card-1600.png 1600 1000 1 "$DONE.then(()=>document.querySelectorAll('.card')[1].click())"
shot "$B/index.html?mock=stl-flat&speed=8#/r?city=st-louis" $OUT/state-stl-flat-card-1600.png 1600 1000 1 "$DONE.then(()=>document.querySelector('.card').click())"
shot "$B/index.html?mock=stl-queued#/r?city=st-louis" $OUT/state-queued-1600.png 1600 0 1 "$(AT 700)"
shot "$B/index.html?mock=stl-cedric&health=waking#/r?city=st-louis" $OUT/state-waking-1600.png 1600 0 1 "$(AT 1500)"
shot "$B/index.html?mock=stl-slow#/r?city=st-louis" $OUT/state-ranking-21s-1600.png 1600 0 1 "$(AT 21000)"
shot "$B/index.html?mock=stl-cedric&speed=8#/r?city=st-louis" $OUT/s2-dare-1600.png 1600 0 1 "$DONE.then(()=>{const t=document.getElementById('dare');t.value='Try Gioia’s Deli on the Hill and Pappy’s Smokehouse.';t.dispatchEvent(new Event('input'));return new Promise(r=>setTimeout(r,500))})"
# New York: the map header with Queens and the Sripraphai callout (MOCK set)
if [[ -f ../site/data/map/nyc.json ]]; then
  shot "$B/index.html?speed=8#/r?set=nyc-khruangbin" $OUT/s2-nyc-1600.png 1600 0 1 "$DONE"
  shot "$B/index.html?speed=8#/r?set=nyc-khruangbin" $OUT/s2-nyc-390.png 390 0 2 "$DONE"
fi
