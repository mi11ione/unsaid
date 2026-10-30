#!/bin/zsh
# Re-render every image, the clip and the site screenshots. Needs Google Chrome, node (no npm packages),
# python3 with Pillow, ffmpeg for the MP4.
#   ./render.sh            everything        ./render.sh hero | images | share | clip | video | site | data
#   URL=https://unsaid.mi11ion.io FRAMES=<scratch dir> ./render.sh video     the 60 s video (end-card URL; where its PNG frames go, deleted after)
#   SRC=../site/data/mock/stl-cedric.ndjson ./render.sh images     force a results file (default: live, else mock)
set -e
cd "$(dirname "$0")"
U="file://$PWD"
S=shots
mkdir -p $S
what=${1:-all}
# default: the live result (media/data/live/query_stl-cedric.json) when present, else the MOCK stream
q=${SRC:+src=$SRC}
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

# image 1 is the Mai Lee hero (round 2); hero.html (Gioia's, "Ask Claude…") is retired and no longer rendered
if [[ $what == all || $what == hero || $what == images ]]; then
  shot "$U/hero-mailee.html?v=devpost&$q" $S/1-hero-1600x1000.png 1600 1000 1
  small $S/1-hero-1600x1000.png $S/1-hero-600-check.png 600
  shot "$U/hero-mailee.html?v=phone&$q" $S/1-hero-phone-390.png 390 0 2
  shot "$U/hero-mailee.html?v=tv&$q" $S/1-hero-tv-1920x1080.png 1920 1080 1
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

if [[ $what == all || $what == video ]]; then
  # the 60 s Devpost video: video.html (one timeline, window.seek) → 30 fps PNG frames → H.264. Frames are ~2 GB:
  # they go to $FRAMES (default: a temp dir) and are deleted after encoding. Sources: VIDEO-NOTES.md.
  (cd .. && python3 -I media/tools/build_video_data.py)
  F=${FRAMES:-${TMPDIR:-/tmp}/unsaid-video-frames}
  rm -rf $F; mkdir -p $F
  END=$(node tools/cdp.mjs eval "$U/video.html" "window.__END" 1920 1080 | tr -d '"')
  node tools/cdp.mjs eval "$U/video.html" "JSON.stringify(window.__SFX)" 1920 1080 > $F/sfx.json
  node tools/cdp.mjs frames "$U/video.html${URL:+?url=$URL}" $F 1920 1080 30 $END
  python3 -I tools/video_audio.py $F/sfx.json $END $F/ui.wav
  ffmpeg -y -loglevel error -framerate 30 -i $F/f%04d.png -i $F/ui.wav -c:v libx264 -pix_fmt yuv420p -crf 18 -preset slow \
    -profile:v high -c:a aac -b:a 160k -shortest -movflags +faststart $S/video-60s-1920x1080.mp4
  python3 - $F <<'PY'
import sys
from PIL import Image, ImageDraw, ImageFont
F = sys.argv[1]
ts = [2.6, 6.0, 10.8, 12.9, 15.0, 21.5, 23.6, 27.2, 29.6, 31.8, 36.0, 39.3, 41.8, 48.3, 51.8, 58.5]
w, h, g = 640, 360, 8
sheet = Image.new('RGB', (4 * w + 3 * g, 4 * (h + 26) + 3 * g), (40, 40, 38))
d = ImageDraw.Draw(sheet)
try: font = ImageFont.truetype('/System/Library/Fonts/Menlo.ttc', 16)
except Exception: font = None
for i, t in enumerate(ts):
    x, y = (i % 4) * (w + g), (i // 4) * (h + 26 + g)
    sheet.paste(Image.open(f'{F}/f{round(t * 30):04d}.png').convert('RGB').resize((w, h), Image.LANCZOS), (x, y + 26))
    d.text((x + 6, y + 4), f'{int(t // 60)}:{t % 60:04.1f}', fill=(200, 198, 190), font=font)
sheet.save('shots/video-keyframes.png')
PY
  rm -rf $F
  echo "$S/video-60s-1920x1080.mp4"
fi

if [[ $what == all || $what == site ]]; then
  zsh tools/shoot-site.sh
fi

