// Minimal headless-Chrome driver over the DevTools protocol (Node's built-in WebSocket; no npm deps).
// usage:
//   node cdp.mjs shot  <url> <out.png> <w> <h> [dpr] [js to await before the capture]   (h=0: the page's own height)
//   node cdp.mjs frames <url> <outdir> <w> <h> <fps> <seconds>    (page must expose window.seek(t) → Promise|void)
import { spawn } from 'node:child_process';
import { writeFileSync, mkdirSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const [mode, url, out, W, H, a5, a6] = process.argv.slice(2);
const w = +W; let h = +H;
const port = 9300 + Math.floor(Math.random() * 500);
const prof = mkdtempSync(join(tmpdir(), 'cdp-'));
const ch = spawn(CHROME, ['--headless=new', '--disable-features=MacAppCodeSignClone', '--disable-gpu', '--hide-scrollbars', '--allow-file-access-from-files',
  `--remote-debugging-port=${port}`, `--user-data-dir=${prof}`, '--window-size=2000,2000', 'about:blank'], { stdio: 'ignore' });
// Always kill Chrome and delete its throwaway profile, on success, error or signal. Leaked profiles once filled the disk.
// SIGTERM lets Chrome remove its own code_sign_clone (SIGKILL leaked one per launch); profile removed after
const cleanup = () => { try { ch.kill('SIGTERM'); } catch {} try { rmSync(prof, { recursive: true, force: true }); } catch {} };
process.on('exit', cleanup);
for (const s of ['SIGINT', 'SIGTERM', 'SIGHUP']) process.on(s, () => process.exit(130));
process.on('uncaughtException', e => { console.error(e?.stack || e); process.exit(1); });
process.on('unhandledRejection', e => { console.error(e?.stack || e); process.exit(1); });
const sleep = ms => new Promise(r => setTimeout(r, ms));

async function target() {
  for (let i = 0; i < 60; i++) {
    try { const l = await (await fetch(`http://127.0.0.1:${port}/json`)).json(); const p = l.find(x => x.type === 'page'); if (p) return p.webSocketDebuggerUrl; } catch {}
    await sleep(150);
  }
  throw new Error('no chrome');
}
const ws = new WebSocket(await target());
await new Promise(r => ws.addEventListener('open', r, { once: true }));
let id = 0; const pend = new Map(); const waiters = [];
ws.addEventListener('message', e => {
  const m = JSON.parse(e.data);
  if (m.id && pend.has(m.id)) { const { res, rej } = pend.get(m.id); pend.delete(m.id); m.error ? rej(new Error(JSON.stringify(m.error))) : res(m.result); }
  else if (m.method === 'Runtime.exceptionThrown') console.error('page exception:', JSON.stringify(m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text).slice(0, 600));
  else if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') console.error('page console.error:', m.params.args.map(a => a.value ?? a.description).join(' ').slice(0, 600));
  if (m.method) waiters.filter(x => x.ev === m.method).forEach(x => { waiters.splice(waiters.indexOf(x), 1); x.res(m.params); });
});
const send = (method, params = {}) => new Promise((res, rej) => { const i = ++id; pend.set(i, { res, rej }); ws.send(JSON.stringify({ id: i, method, params })); });
const on = ev => new Promise(res => waiters.push({ ev, res }));
const evalp = async expr => { const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true }); if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails)); return r.result.value; };

await send('Page.enable'); await send('Runtime.enable');
const dpr = mode !== 'frames' ? +(a5 || 1) : 1;
await send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: dpr, mobile: false });
// navigate, and wait for the page to say it has drawn (pages load their JSON asynchronously). A local preview server
// sometimes leaves a request pending; if the page hasn't signalled ready in 6 s, load it again (up to 3 times).
for (let attempt = 0; attempt < 3; attempt++) {
  const loaded = on('Page.loadEventFired');
  await send('Page.navigate', { url: attempt ? 'about:blank' : url }); await loaded;
  if (attempt) { const l2 = on('Page.loadEventFired'); await send('Page.navigate', { url }); await l2; }
  await evalp('document.fonts.ready');
  let ok = false;
  for (let i = 0; i < 60 && !(ok = await evalp('window.__ready === true')); i++) await sleep(100);
  if (ok) break;
  console.error('page not ready, reloading');
}
const err = await evalp('window.__error || null'); if (err) console.error('page error:', err);
await sleep(300);
if (mode !== 'frames' && a6) { await Promise.race([evalp(a6), sleep(40000).then(() => console.error('pre-capture script timed out'))]); await sleep(400); }
if (!h) { h = await evalp(`(document.getElementById("stage") ? document.getElementById("stage").offsetHeight : Math.max(document.body.scrollHeight, document.documentElement.scrollHeight))`); await send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: dpr, mobile: false }); await sleep(200); }
const cap = async () => Buffer.from((await send('Page.captureScreenshot', { format: 'png', clip: { x: 0, y: 0, width: w, height: h, scale: 1 }, captureBeyondViewport: false })).data, 'base64');

if (mode === 'eval') {
  console.log(JSON.stringify(await evalp(out)));   // node cdp.mjs eval <url> <expression> <w> <h> [dpr] [script]
} else if (mode === 'shot') {
  writeFileSync(out, await cap()); console.log(out);
} else {
  const fps = +a5, secs = +a6; mkdirSync(out, { recursive: true });
  const n = Math.round(fps * secs);
  for (let f = 0; f <= n; f++) {
    await evalp(`Promise.resolve(window.seek(${f / fps})).then(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))))`);
    writeFileSync(join(out, `f${String(f).padStart(4, '0')}.png`), await cap());
  }
  console.log(`${n + 1} frames → ${out}`);
}
ws.close();
// graceful quit: wait for Chrome to exit (it cleans its clone), then the exit handler removes the profile
await new Promise(r => { ch.once('exit', r); ch.kill('SIGTERM'); setTimeout(() => { try { ch.kill('SIGKILL'); } catch {} r(); }, 5000); });
process.exit(0);
