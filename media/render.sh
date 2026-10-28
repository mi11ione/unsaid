#!/bin/zsh
# Re-render every image, the clip and the site screenshots. Needs Google Chrome, node (no npm packages),
# python3 with Pillow, ffmpeg for the MP4.
#   ./render.sh            everything        ./render.sh hero | images | share | clip | site | data
#   SRC=../site/data/sets/stl-cedric.ndjson ./render.sh images     re-render from a real results file
set -e
cd "$(dirname "$0")"
U="file://$PWD"
S=shots
mkdir -p $S
what=${1:-all}
src=${SRC:-../site/data/mock/stl-cedric.ndjson}
q="src=$src"
shot() { node tools/cdp.mjs shot "$@" >/dev/null && echo "$2"; }
small() { python3 - "$@" <<'PY'
import sys
from PIL import Image
src, dst, w = sys.argv[1], sys.argv[2], int(sys.argv[3])
im = Image.open(src); im.resize((w, round(w * im.height / im.width)), Image.LANCZOS).save(dst)
print(dst)
PY
}

if [[ $what == all || $what == data ]]; then
  (cd .. && python3 -I media/tools/build_data.py && node media/tools/test_matcher.mjs)
fi

if [[ $what == all || $what == hero || $what == images ]]; then
  shot "$U/hero.html?v=devpost&$q" $S/1-hero-1600x1000.png 1600 1000 1
  small $S/1-hero-1600x1000.png $S/1-hero-600-check.png 600
  shot "$U/hero.html?v=phone&$q" $S/1-hero-phone-390.png 390 0 2
  shot "$U/hero.html?v=tv&$q" $S/1-hero-tv-1920x1080.png 1920 1080 1
fi

if [[ $what == all || $what == images ]]; then
  shot "$U/image2.html?$q" $S/2-card-1600x1000.png 1600 1000 1
  small $S/2-card-1600x1000.png $S/2-card-600-check.png 600
  shot "$U/image3.html?$q" $S/3-without-with-1600x1000.png 1600 1000 1
  small $S/3-without-with-1600x1000.png $S/3-without-with-600-check.png 600
fi

if [[ $what == all || $what == share || $what == images ]]; then
  shot "$U/share.html?$q" $S/share-1080x1350.png 1080 1350 1
fi

if [[ $what == all || $what == clip ]]; then
  rm -rf $S/clip-frames
  node tools/cdp.mjs frames "$U/clip.html?$q" $S/clip-frames 1920 1080 30 10
  ffmpeg -y -loglevel error -framerate 30 -i $S/clip-frames/f%04d.png -c:v libx264 -pix_fmt yuv420p -crf 16 -preset slow -movflags +faststart $S/clip-hidden-gem-1920x1080.mp4
  python3 - <<'PY'
from PIL import Image
ts = [0.8, 2.6, 4.6, 6.7, 8.1, 10.0]
fr = [Image.open(f'shots/clip-frames/f{round(t*30):04d}.png').resize((640, 360), Image.LANCZOS) for t in ts]
strip = Image.new('RGB', (640 * 3 + 16, 360 * 2 + 8), (40, 40, 38))
for i, f in enumerate(fr):
    strip.paste(f, ((i % 3) * 648, (i // 3) * 368))
strip.save('shots/clip-keyframes.png')
PY
  rm -rf $S/clip-frames
  echo "$S/clip-hidden-gem-1920x1080.mp4"
fi

if [[ $what == all || $what == site ]]; then
  zsh tools/shoot-site.sh
fi

if [[ $what == all || $what == hero || $what == images ]]; then
  shot "$U/hero-mailee.html?v=devpost&$q" $S/1b-hero-mailee-1600x1000.png 1600 1000 1
  small $S/1b-hero-mailee-1600x1000.png $S/1b-hero-mailee-600-check.png 600
fi
