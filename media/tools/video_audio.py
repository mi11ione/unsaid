"""The video's UI-sound track, synthesised here from sine waves and seeded noise (no samples, no music, nothing licensed).
  python3 -I media/tools/video_audio.py <sfx.json> <seconds> <out.wav>
sfx.json is window.__SFX from video.html: [{t, k}], k in tick | hit | strike | scratch | rise | key. Standard library only."""
import json, math, random, struct, sys, wave

SR = 48000
src, secs, out = sys.argv[1], float(sys.argv[2]), sys.argv[3]
cues = json.load(open(src))
if isinstance(cues, str):          # cdp.mjs eval prints the JSON-encoded value of a JSON string
    cues = json.loads(cues)
N = int(SR * secs) + SR // 10
buf = [0.0] * N
rnd = random.Random(7)


def add(t, samples):
    i0 = int(t * SR)
    for j, v in enumerate(samples):
        if 0 <= i0 + j < N:
            buf[i0 + j] += v


def env(n, a, d):        # attack a s, exponential decay d s
    na = max(1, int(a * SR))
    return [(j / na if j < na else math.exp(-(j - na) / (d * SR))) for j in range(n)]


def tone(f, dur, amp, a=.002, d=.05, f2=None):
    n = int(dur * SR); e = env(n, a, d); ph = 0.0; out = []
    for j in range(n):
        ff = f if f2 is None else f + (f2 - f) * j / n
        ph += 2 * math.pi * ff / SR
        out.append(amp * e[j] * math.sin(ph))
    return out


def noise(dur, amp, a=.004, d=.06, lp=.15, hp=.0, sweep=None):
    """one-pole low-passed noise (optionally with a moving cutoff), minus a slower low-pass = a soft band"""
    n = int(dur * SR); e = env(n, a, d); y = y2 = 0.0; out = []
    for j in range(n):
        k = lp if sweep is None else lp + (sweep - lp) * j / n
        x = rnd.uniform(-1, 1); y += k * (x - y); y2 += hp * (y - y2)
        out.append(amp * e[j] * (y - y2))
    return out


for c in cues:
    t, k = c["t"], c["k"]
    if k == "tick":
        add(t, tone(1900, .05, .10, d=.012))
    elif k == "hit":
        add(t, tone(1320, .09, .12, d=.03)); add(t, tone(2640, .05, .04, d=.015))
    elif k == "key":
        add(t, noise(.03, .10, a=.001, d=.006, lp=.5, hp=.05))
    elif k == "scratch":
        add(t, noise(.06, .05, a=.002, d=.02, lp=.35, hp=.06))
    elif k == "strike":
        add(t, noise(.32, .55, a=.01, d=.11, lp=.06, hp=.02, sweep=.4))
    elif k == "rise":
        add(t, tone(660, .6, .10, a=.01, d=.25)); add(t + .09, tone(990, .7, .08, a=.01, d=.3))

peak = max(1e-9, max(abs(v) for v in buf))
g = min(1.0, 0.35 / peak)              # quiet: peaks near -9 dBFS, most cues far below
with wave.open(out, "wb") as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
    fr = bytearray()
    for j, v in enumerate(buf):
        s = int(max(-1, min(1, v * g)) * 32767)
        fr += struct.pack("<hh", s, s)
    w.writeframes(bytes(fr))
print(out, "%d cues, %.1f s" % (len(cues), secs))
