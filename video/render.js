// Renders film.html frame by frame into an H.264 MP4.
// Usage: npm install && node render.js [workers=4] [fps=30]
// Needs Playwright (local or global) and ffmpeg with libx264 (set FFMPEG to override the binary path).
// Outputs <OUT>.mp4 and <OUT>.srt in this folder (OUT defaults to transformer-explainer).
// NOSUBS=1 renders without burned-in subtitles (for adding subtitles/voice-over in an editor).
const { spawn, execSync } = require('child_process');
const fs = require('fs');
let pw;
try { pw = require('playwright'); } catch { pw = require(execSync('npm root -g').toString().trim() + '/playwright'); }
const { chromium } = pw;
const FF = process.env.FFMPEG || 'ffmpeg';
const WORKERS = +(process.argv[2] || 4), FPS = +(process.argv[3] || 30);
const OUT = process.env.OUT || 'transformer-explainer', PAGE = 'file://' + process.cwd() + '/film.html' + (process.env.NOSUBS ? '?nosubs' : '');

async function segment(k, from, to) {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
  page.on('pageerror', e => console.error(`[w${k}] pageerror`, e.message));
  await page.goto(PAGE);
  await page.evaluate(() => window.prepare());
  const ff = spawn(FF, ['-hide_banner', '-loglevel', 'error', '-y', '-f', 'image2pipe', '-framerate', String(FPS), '-c:v', 'mjpeg', '-i', '-',
    '-c:v', 'libx264', '-preset', 'medium', '-crf', '20', '-pix_fmt', 'yuv420p', '-r', String(FPS), `seg_${k}.mp4`], { stdio: ['pipe', 'inherit', 'inherit'] });
  for (let f = from; f < to; f++) {
    await page.evaluate(t => window.render(t), f / FPS);
    const buf = await page.screenshot({ type: 'jpeg', quality: 93 });
    if (!ff.stdin.write(buf)) await new Promise(r => ff.stdin.once('drain', r));
    if ((f - from) % 600 === 0) console.log(`[w${k}] ${f - from}/${to - from}`);
  }
  ff.stdin.end();
  await new Promise(r => ff.on('close', r));
  await browser.close();
}

(async () => {
  const probe = await chromium.launch();
  const p = await probe.newPage();
  await p.goto(PAGE);
  const { dur, subs } = await p.evaluate(() => ({ dur: window.DURATION, subs: window.SUBS }));
  await probe.close();
  const total = Math.round(dur * FPS), per = Math.ceil(total / WORKERS);
  const t0 = Date.now();
  await Promise.all(Array.from({ length: WORKERS }, (_, k) => segment(k, k * per, Math.min(total, (k + 1) * per))));
  fs.writeFileSync('segs.txt', Array.from({ length: WORKERS }, (_, k) => `file 'seg_${k}.mp4'`).join('\n'));
  // join segments and add a silent stereo track for player/editor compatibility
  await new Promise((res, rej) => spawn(FF, ['-hide_banner', '-loglevel', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', 'segs.txt',
    '-f', 'lavfi', '-i', 'anullsrc=channel_layout=stereo:sample_rate=48000', '-shortest', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '96k',
    '-movflags', '+faststart', `${OUT}.mp4`], { stdio: 'inherit' }).on('close', c => c ? rej(c) : res()));
  const ts = x => { const ms = Math.round(x * 1000); const h = Math.floor(ms / 3600000), m = Math.floor(ms / 60000) % 60, s = Math.floor(ms / 1000) % 60; return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')},${String(ms % 1000).padStart(3, '0')}`; };
  fs.writeFileSync(`${OUT}.srt`, subs.map(([a, b, text], i) => `${i + 1}\n${ts(a)} --> ${ts(b)}\n${text}\n`).join('\n'));
  console.log(`done: ${total} frames in ${((Date.now() - t0) / 1000).toFixed(0)}s`);
})();
