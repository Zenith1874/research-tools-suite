// Collect the HigherEdJobs Business listing through an ordinary browser.
//
// The board serves a normal browser the public listing while giving an HTTP
// client an intermittent Imperva interstitial, so the project's sanctioned
// answer has always been "capture it in a visible browser and import that".
// `collect_higheredjobs_browser.js` holds the page logic for it but is a bare
// Playwright page-function with nothing to run it, and Playwright is not
// installed here. This drives the Chrome already on the machine over the
// DevTools Protocol instead: Node 22+ has a global WebSocket, so it needs no
// dependency at all.
//
// What this is not: it does not execute, solve, or work around a challenge.
// If a page comes back showing an interstitial or a CAPTCHA the run aborts and
// writes nothing -- the same all-or-nothing rule the importer enforces, for
// the same reason. A partial listing that looks complete is worse than none.
//
// It also runs in a throwaway profile directory, so it never touches the
// user's own Chrome profile, cookies, or signed-in sessions.
//
// Usage:
//   node scripts/collect_higheredjobs_cdp.mjs [--out <path>] [--page-size 100]
//                                             [--delay 2000] [--headed]

import { spawn } from 'node:child_process';
import { existsSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';

const BASE = 'https://www.higheredjobs.com/faculty/search.cfm?JobCat=232&CatName=Business';
const CHROMES = [
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
];

function arg(name, fallback) {
  const i = process.argv.indexOf(name);
  return i > -1 && process.argv[i + 1] ? process.argv[i + 1] : fallback;
}
const OUT = arg('--out', 'outputs/higheredjobs_business_snapshot.json');
const PAGE_SIZE = Number(arg('--page-size', '100'));
const DELAY = Number(arg('--delay', '2000'));
const HEADED = process.argv.includes('--headed');
const PORT = Number(arg('--port', '9333'));

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// The extraction, byte-for-byte the logic in collect_higheredjobs_browser.js.
// Kept as a string because it is evaluated inside the page.
const EXTRACTOR = `(() => {
  const clean = v => String(v || '').replace(/\\s+/g, ' ').trim();
  const text = document.body.innerText.replace(/\\s+/g, ' ').trim();
  if (/pardon our interruption|captcha|incapsula|request unsuccessful/i.test(text)) {
    return {challenge: true};
  }
  const m = text.match(/\\bResults\\s+(\\d[\\d,]*)\\s*[-\\u2013]\\s*(\\d[\\d,]*)\\s+of\\s+(\\d[\\d,]*)\\b/i);
  const cards = Array.from(document.querySelectorAll('div.row.record')).map(card => {
    const anchor = card.querySelector('a[href*="details.cfm?JobCode="]');
    const sourceUrl = anchor ? new URL(anchor.getAttribute('href'), location.href).href : '';
    const sourceJobId = sourceUrl ? new URL(sourceUrl).searchParams.get('JobCode') : '';
    const title = clean(anchor && anchor.textContent);
    const left = card.querySelector('.col-sm-7');
    const salaryEl = left && left.querySelector('.job-salary');
    const salary = clean(salaryEl && salaryEl.textContent);
    const leftValues = String((left && left.innerText) || '').split(/\\n+/).map(clean).filter(Boolean);
    const remaining = leftValues.filter(v => v.toLowerCase() !== title.toLowerCase()
      && (!salary || v.toLowerCase() !== salary.toLowerCase()) && v.toLowerCase() !== 'save job');
    const right = card.querySelector('.col-sm-5');
    const catEl = right && right.querySelector('.text-nowrap');
    const category = clean(catEl && catEl.textContent);
    const rightText = clean(right && right.innerText);
    const posted = rightText.match(/\\bPosted\\s+(?:today|yesterday|\\d+\\s+(?:hours?|days?|weeks?|months?)\\s+ago|[A-Za-z]+\\s+\\d{1,2},\\s+\\d{4}|\\d{1,2}\\/\\d{1,2}\\/\\d{2,4})\\b/i);
    const cardText = clean(card.innerText);
    return {
      source_job_id: clean(sourceJobId), source_url: sourceUrl, title_raw: title,
      institution_raw: remaining[0] || '',
      location_raw: remaining.length > 1 ? remaining[remaining.length - 1] : null,
      description_excerpt: clean((category ? 'HigherEdJobs category: ' + category + '. ' : '') + cardText).slice(0, 2000),
      posted_date_raw: posted ? posted[0] : null, salary_raw: salary || null, official_url: null,
      extra: {
        source_category: category || null,
        source_priority_listing: Boolean(card.querySelector('.addon-marker')),
        source_middle_lines: remaining.length > 2 ? remaining.slice(1, -1) : [],
      },
    };
  });
  return {challenge: false, range: m ? m.slice(1, 4).map(v => Number(v.replace(/,/g, ''))) : null, cards};
})()`;

class Cdp {
  constructor(ws) { this.ws = ws; this.id = 0; this.pending = new Map(); this.sessionId = null;
    ws.addEventListener('message', (event) => {
      const msg = JSON.parse(event.data);
      const waiter = this.pending.get(msg.id);
      if (waiter) { this.pending.delete(msg.id);
        msg.error ? waiter.reject(new Error(msg.error.message)) : waiter.resolve(msg.result); }
    });
  }
  send(method, params = {}) {
    const id = ++this.id;
    return new Promise((resolve, reject) => {
      this.pending.set(id, {resolve, reject});
      this.ws.send(JSON.stringify({id, method, params,
        ...(this.sessionId ? {sessionId: this.sessionId} : {})}));
      setTimeout(() => { if (this.pending.delete(id)) reject(new Error(method + ' timed out')); }, 60000);
    });
  }
}

async function connect(port) {
  for (let i = 0; i < 40; i += 1) {
    try {
      const res = await fetch(`http://127.0.0.1:${port}/json/version`);
      const info = await res.json();
      if (info.webSocketDebuggerUrl) return info.webSocketDebuggerUrl;
    } catch { /* not up yet */ }
    await sleep(500);
  }
  throw new Error('browser did not expose a DevTools endpoint');
}

async function main() {
  const chrome = CHROMES.find(existsSync);
  if (!chrome) throw new Error('no Chrome or Edge found in the usual locations');
  const profile = mkdtempSync(join(tmpdir(), 'hej-capture-'));
  console.log(`browser : ${chrome}`);
  console.log(`profile : ${profile}   (throwaway; your own profile is untouched)`);

  const child = spawn(chrome, [
    `--remote-debugging-port=${PORT}`,
    `--user-data-dir=${profile}`,
    '--no-first-run', '--no-default-browser-check',
    '--disable-background-networking', '--disable-sync',
    ...(HEADED ? [] : ['--headless=new']),
    'about:blank',
  ], {stdio: 'ignore', detached: false});

  let snapshot = null, aborted = null;
  try {
    const wsUrl = await connect(PORT);
    const ws = new WebSocket(wsUrl);
    await new Promise((r, j) => { ws.addEventListener('open', r); ws.addEventListener('error', j); });
    const cdp = new Cdp(ws);
    const {targetId} = await cdp.send('Target.createTarget', {url: 'about:blank'});
    const {sessionId} = await cdp.send('Target.attachToTarget', {targetId, flatten: true});
    cdp.sessionId = sessionId;
    await cdp.send('Page.enable');
    await cdp.send('Runtime.enable');

    let reportedTotal = null, requiredPages = null;
    const pages = [], jobs = [];

    for (let n = 1; requiredPages === null || n <= requiredPages; n += 1) {
      const url = `${BASE}&NumJobs=${PAGE_SIZE}&Page=${n}`;
      await cdp.send('Page.navigate', {url});
      // Settle, then poll for the cards rather than trusting one fixed wait.
      let out = null;
      for (let attempt = 0; attempt < 20; attempt += 1) {
        await sleep(500);
        const {result} = await cdp.send('Runtime.evaluate',
          {expression: EXTRACTOR, returnByValue: true, awaitPromise: false});
        out = result.value;
        if (out && (out.challenge || (out.range && out.cards.length))) break;
      }
      if (!out) { aborted = `page ${n}: nothing evaluated`; break; }
      if (out.challenge) { aborted = `page ${n}: challenge shown; no snapshot written`; break; }
      if (!out.range) {
        // Say what the page actually was. "No result range" covers a challenge
        // we failed to recognise, a redirect, and an empty render, and those
        // need different answers.
        const {result} = await cdp.send('Runtime.evaluate', {returnByValue: true,
          expression: `({url: location.href, title: document.title,
            cards: document.querySelectorAll('div.row.record').length,
            chars: document.body.innerText.length,
            head: document.body.innerText.replace(/\\s+/g,' ').trim().slice(0, 400)})`});
        console.error('\npage state:', JSON.stringify(result.value, null, 2));
        aborted = `page ${n}: no parseable result range`; break;
      }
      const [start, end, observedTotal] = out.range;
      if (reportedTotal === null) {
        reportedTotal = observedTotal;
        requiredPages = Math.ceil(reportedTotal / PAGE_SIZE);
        console.log(`board reports ${reportedTotal} records -> ${requiredPages} pages at ${PAGE_SIZE}/page`);
      } else if (observedTotal !== reportedTotal) {
        aborted = `total changed mid-capture: ${reportedTotal} -> ${observedTotal}`; break;
      }
      const expStart = ((n - 1) * PAGE_SIZE) + 1;
      const expEnd = Math.min(n * PAGE_SIZE, reportedTotal);
      if (start !== expStart || end !== expEnd) {
        aborted = `page ${n} reported ${start}-${end}, expected ${expStart}-${expEnd}`; break;
      }
      if (out.cards.length !== end - start + 1) {
        aborted = `page ${n} exposed ${out.cards.length} cards for ${start}-${end}`; break;
      }
      pages.push({page: n, start, end, cards: out.cards.length});
      jobs.push(...out.cards);
      process.stdout.write(`  page ${n}/${requiredPages}  ${jobs.length} cards\r`);
      if (n < requiredPages) await sleep(DELAY);
    }
    console.log('');

    if (!aborted) {
      const unique = new Set(jobs.map((j) => j.source_job_id)).size;
      if (unique !== reportedTotal) aborted = `${unique} unique JobCodes for ${reportedTotal} reported`;
      else snapshot = {
        source: 'higheredjobs', source_url: BASE,
        capture_method: 'ordinary_visible_browser_pagination', coverage_complete: true,
        reported_total: reportedTotal, page_size: PAGE_SIZE, pages_fetched: pages.length,
        captured_at: new Date().toISOString().replace(/\.\d+Z$/, 'Z'),
        pages, jobs,
      };
    }
  } finally {
    child.kill();
    try { rmSync(profile, {recursive: true, force: true}); } catch { /* best effort */ }
  }

  if (aborted) { console.error(`\nABORTED: ${aborted}`); process.exit(2); }
  mkdirSync(dirname(OUT), {recursive: true});
  writeFileSync(OUT, JSON.stringify(snapshot), 'utf-8');
  console.log(`\nwrote ${OUT}`);
  console.log(`  ${snapshot.reported_total} records across ${snapshot.pages_fetched} pages`);
}

main().catch((err) => { console.error('FAILED:', err.message); process.exit(1); });
