// Read HigherEdJobs posting bodies in an ordinary visible browser.
//
// The listing snapshot refreshes *which* postings exist; it carries only the
// card blurb, which averages 193 characters. The posting itself -- the
// deadline, the application URL, and the work-authorisation paragraph -- is on
// the detail page, and that is where HigherEdJobs coverage has been ~0%.
//
// Same rules as the listing collector: an ordinary browser on robots-allowed
// pages, a throwaway profile, and an abort the moment an interstitial appears.
// Nothing here executes or solves a challenge.
//
// Output is JSONL written as it goes, one record per line, so an interrupted
// run keeps everything it already read and can be resumed. A 3,000-page run
// that commits only at the end is a run that loses three thousand pages to one
// hiccup.
//
// Usage:
//   node scripts/collect_higheredjobs_details_cdp.mjs --urls <file.json>
//        --out outputs/hej_details.jsonl [--limit 50] [--delay 1500] [--headed]

import { spawn } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, appendFileSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { createInterface } from 'node:readline';
import { createReadStream } from 'node:fs';

const CHROMES = [
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
];
const arg = (name, fallback) => {
  const i = process.argv.indexOf(name);
  return i > -1 && process.argv[i + 1] ? process.argv[i + 1] : fallback;
};
const URLS = arg('--urls', 'outputs/hej_detail_urls.json');
const OUT = arg('--out', 'outputs/hej_details.jsonl');
const LIMIT = Number(arg('--limit', '0'));
const DELAY = Number(arg('--delay', '1500'));
const PORT = Number(arg('--port', '9334'));
const HEADED = !process.argv.includes('--headless');
// Headless is served a blank page here, so the browser has to be real. That
// makes a scheduled run pop a window into whatever the user is doing, so it
// can be parked off-screen instead: still an ordinary rendering browser,
// simply not in the way.
const OFFSCREEN = process.argv.includes('--offscreen');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Extraction runs in the page. It takes the posting's own body region and
// leaves the site chrome out; the challenge check comes first so an
// interstitial can never be stored as a short posting.
const EXTRACTOR = `(() => {
  const clean = v => String(v || '').replace(/[ \\t\\u00a0]+/g, ' ').replace(/\\n{3,}/g, '\\n\\n').trim();
  const all = document.body ? document.body.innerText : '';
  if (/pardon our interruption|captcha|incapsula|request unsuccessful/i.test(all)) {
    return {challenge: true};
  }
  // The posting body. Try the specific containers first and fall back to the
  // main region; anything that yields less than the card blurb is reported as
  // empty rather than stored as a body.
  const pick = ['#job-details', '.job-details', '#detailsContent', 'main', 'article']
    .map(sel => document.querySelector(sel)).find(Boolean);
  const body = clean((pick && pick.innerText) || all);
  const link = Array.from(document.querySelectorAll('a')).find(a =>
    /apply|application/i.test(a.textContent || '') && /^https?:/i.test(a.href || ''));
  return {
    challenge: false,
    title: clean(document.title),
    chars: body.length,
    body: body.slice(0, 50000),
    apply_url: link ? link.href : null,
    url: location.href,
  };
})()`;

class Cdp {
  constructor(ws) {
    this.ws = ws; this.id = 0; this.pending = new Map(); this.sessionId = null;
    ws.addEventListener('message', (e) => {
      const m = JSON.parse(e.data); const w = this.pending.get(m.id);
      if (w) { this.pending.delete(m.id); m.error ? w.reject(new Error(m.error.message)) : w.resolve(m.result); }
    });
  }
  send(method, params = {}) {
    const id = ++this.id;
    return new Promise((resolve, reject) => {
      this.pending.set(id, {resolve, reject});
      this.ws.send(JSON.stringify({id, method, params, ...(this.sessionId ? {sessionId: this.sessionId} : {})}));
      setTimeout(() => { if (this.pending.delete(id)) reject(new Error(method + ' timed out')); }, 45000);
    });
  }
}

async function endpoint(port) {
  for (let i = 0; i < 40; i += 1) {
    try {
      const r = await fetch(`http://127.0.0.1:${port}/json/version`);
      const j = await r.json();
      if (j.webSocketDebuggerUrl) return j.webSocketDebuggerUrl;
    } catch { /* not up yet */ }
    await sleep(500);
  }
  throw new Error('browser did not expose a DevTools endpoint');
}

// Resume support: whatever is already in the output file is already read.
async function alreadyDone(path) {
  const seen = new Set();
  if (!existsSync(path)) return seen;
  const rl = createInterface({input: createReadStream(path), crlfDelay: Infinity});
  for await (const line of rl) {
    if (!line.trim()) continue;
    try {
      const row = JSON.parse(line);
      // A challenged posting is worth retrying on a later run; only a
      // page we actually read is done with.
      if (row.status !== 'challenged') seen.add(String(row.source_job_id));
    } catch { /* skip a torn line */ }
  }
  return seen;
}

async function main() {
  const chrome = CHROMES.find(existsSync);
  if (!chrome) throw new Error('no Chrome or Edge found');
  const targets = JSON.parse(readFileSync(URLS, 'utf-8'));
  const done = await alreadyDone(OUT);
  const todo = targets.filter((t) => !done.has(String(t.source_job_id)));
  const slice = LIMIT > 0 ? todo.slice(0, LIMIT) : todo;
  console.log(`targets ${targets.length}, already read ${done.size}, this run ${slice.length}`);
  if (!slice.length) return;

  const profile = mkdtempSync(join(tmpdir(), 'hej-detail-'));
  const child = spawn(chrome, [
    `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`,
    '--no-first-run', '--no-default-browser-check',
    '--disable-background-networking', '--disable-sync',
    ...(OFFSCREEN ? ['--window-position=-32000,-32000', '--window-size=1280,900'] : []),
    ...(HEADED ? [] : ['--headless=new']), 'about:blank',
  ], {stdio: 'ignore'});

  mkdirSync(dirname(OUT), {recursive: true});
  // How many challenges in a row mean the board is refusing us, rather
  // than one posting being unserveable.
  const CHALLENGE_RUN = 4;
  let read = 0, empty = 0, challenged = 0, failed = 0, consecutiveChallenges = 0;
  try {
    const ws = new WebSocket(await endpoint(PORT));
    await new Promise((res, rej) => { ws.addEventListener('open', res); ws.addEventListener('error', rej); });
    const cdp = new Cdp(ws);
    const {targetId} = await cdp.send('Target.createTarget', {url: 'about:blank'});
    const {sessionId} = await cdp.send('Target.attachToTarget', {targetId, flatten: true});
    cdp.sessionId = sessionId;
    await cdp.send('Page.enable'); await cdp.send('Runtime.enable');

    for (const target of slice) {
      let out = null;
      try {
        await cdp.send('Page.navigate', {url: target.source_url});
        for (let attempt = 0; attempt < 16; attempt += 1) {
          await sleep(400);
          const {result} = await cdp.send('Runtime.evaluate',
            {expression: EXTRACTOR, returnByValue: true});
          out = result.value;
          if (out && (out.challenge || out.chars > 400)) break;
        }
      } catch (err) {
        failed += 1;
        appendFileSync(OUT, JSON.stringify({source_job_id: target.source_job_id,
          source_url: target.source_url, status: 'error', note: err.message}) + '\n');
        continue;
      }
      if (!out) { failed += 1; continue; }
      if (out.challenge) {
        // One challenged page and a board refusing us are different things,
        // and conflating them cost a whole run: a single URL that always
        // serves an interstitial stopped the collector at the same posting
        // every time, so the 2,950 pages behind it were never reachable.
        //
        // So a challenge is recorded against that posting and the run moves
        // on; only a run of them means the board is saying no, and then we
        // stop rather than keep asking.
        challenged += 1;
        consecutiveChallenges += 1;
        appendFileSync(OUT, JSON.stringify({
          source_job_id: target.source_job_id, source_url: target.source_url,
          status: 'challenged',
          note: 'an interstitial was served for this posting; not evidence about the posting',
          captured_at: new Date().toISOString().replace(/\.\d+Z$/, 'Z'),
        }) + '\n');
        if (consecutiveChallenges >= CHALLENGE_RUN) {
          console.log(`\n${consecutiveChallenges} challenges in a row; the board is `
            + `refusing. Stopping with ${read} pages kept this run.`);
          break;
        }
        await sleep(DELAY * 2);   // back off before the next one
        continue;
      }
      consecutiveChallenges = 0;
      const status = out.chars > 400 ? 'ok' : 'empty';
      if (status === 'empty') empty += 1; else read += 1;
      appendFileSync(OUT, JSON.stringify({
        source_job_id: target.source_job_id, source_url: target.source_url,
        status, chars: out.chars, body: out.body, apply_url: out.apply_url,
        title: out.title, captured_at: new Date().toISOString().replace(/\.\d+Z$/, 'Z'),
      }) + '\n');
      if ((read + empty) % 25 === 0) {
        process.stdout.write(`  ${read + empty}/${slice.length}  ok=${read} empty=${empty}\r`);
      }
      await sleep(DELAY);
    }
  } finally {
    child.kill();
    try { rmSync(profile, {recursive: true, force: true}); } catch { /* best effort */ }
  }
  console.log(`\nread ${read}, empty ${empty}, challenged ${challenged}, failed ${failed}`);
  console.log(`appended to ${OUT}`);
}

main().catch((e) => { console.error('FAILED:', e.message); process.exit(1); });
