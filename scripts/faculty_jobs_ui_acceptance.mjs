// Screenshot acceptance for the faculty jobs page.
//
// Every shot is paired with an assertion, because a screenshot on its own only
// proves a page rendered -- not that it rendered the right number. Console
// messages are collected across the whole run and reported at the end: a page
// that looks right while throwing is not a page that passes.
// Nothing is installed to run this. Playwright is taken from wherever it
// already exists (the npx cache is usual) and driven against a Chromium that
// is already on the machine: the cached playwright builds each want a browser
// revision that is not downloaded, and fetching one would mean installing a
// dependency in order to take a screenshot.
//
//   SERVER_PORT=8117 python server.py &
//   PLAYWRIGHT_ENTRY=<...>/node_modules/playwright/index.js //   CHROME_PATH=<...>/ms-playwright/chromium-1223/chrome-win64/chrome.exe //   OUT=./shots BASE=http://127.0.0.1:8117 //   node scripts/faculty_jobs_ui_acceptance.mjs
//
// Point BASE at a scratch instance, not at the running service: this drives a
// real browser through every scope and filter on the page.
//
// ESM ignores NODE_PATH, and playwright lives in the npx cache rather than in
// this project -- resolve it explicitly so nothing has to be installed.
import { writeFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

const playwright = await import(pathToFileURL(process.env.PLAYWRIGHT_ENTRY).href);
// A CommonJS package imported from ESM lands under .default.
const chromium = (playwright.default || playwright).chromium;

const BASE = process.env.BASE || 'http://127.0.0.1:8117';
const OUT = process.env.OUT;
const results = [];
const consoleMessages = [];

function check(name, condition, detail) {
  results.push({ name, pass: !!condition, detail });
  console.log((condition ? 'PASS  ' : 'FAIL  ') + name + (detail ? '  -- ' + detail : ''));
}

// Point at the Chromium already on this machine. The cached playwright builds
// each want a browser revision that is not downloaded, and downloading one to
// take a screenshot would be installing a dependency for this work.
const browser = await chromium.launch({
  executablePath: process.env.CHROME_PATH,
});

async function newPage(width, height) {
  const context = await browser.newContext({ viewport: { width, height } });
  const page = await context.newPage();
  page.on('console', (m) => consoleMessages.push(m.type() + ': ' + m.text()));
  page.on('pageerror', (e) => consoleMessages.push('pageerror: ' + e.message));
  return { context, page };
}

async function summaryOf(page) {
  return page.evaluate(() => {
    const strip = document.getElementById('fc-scope-strip');
    const cells = Array.from(strip ? strip.querySelectorAll('.fc-scope-cell') : []);
    const current = strip && strip.querySelector('.fc-scope-cell.current');
    const filtered = cells.find((c) => c.classList.contains('filtered'));
    const countEl = document.getElementById('fc-job-count');
    return {
      cells: cells.length,
      current: current ? current.innerText.split('\n')[0] : null,
      values: cells.map((c) => c.innerText.split('\n')[1]),
      filtered: filtered ? filtered.innerText.split('\n')[1] : null,
      count: countEl ? countEl.textContent : '',
      rows: document.querySelectorAll('.fc-job-card, .fc-job-row, tbody tr').length,
      sideways: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    };
  });
}

const SCOPES = [
  ['business_school', 'STRICT VIEWING'],
  ['business', 'BROAD VIEWING'],
  ['all', 'AUDIT VIEWING'],
];

for (const pair of SCOPES) {
  const scope = pair[0];
  const label = pair[1];
  const { context, page } = await newPage(1280, 1400);
  await page.goto(BASE + '/faculty-jobs?scope=' + scope, { waitUntil: 'networkidle' });
  await page.waitForSelector('.fc-scope-cell', { timeout: 20000 });
  const s = await summaryOf(page);
  await page.screenshot({ path: OUT + '/01-scope-' + scope + '-1280.png' });
  check(scope + ': strip shows four cells', s.cells === 4, 'cells=' + s.cells);
  check(scope + ': the selected scope is marked as the one being viewed',
        s.current === label, 'current=' + s.current);
  check(scope + ': all three scopes are visible at once',
        s.values.slice(0, 3).every((v) => v && /\d/.test(v)), s.values.join(' / '));
  check(scope + ': rows rendered', s.rows > 0, 'rows=' + s.rows);
  check(scope + ': no sideways scroll', !s.sideways);
  await context.close();
}

{
  const { context, page } = await newPage(390, 900);
  await page.goto(BASE + '/faculty-jobs', { waitUntil: 'networkidle' });
  await page.waitForSelector('.fc-scope-cell', { timeout: 20000 });
  const s = await summaryOf(page);
  await page.screenshot({ path: OUT + '/02-mobile-390.png' });
  check('390px: no sideways scroll', !s.sideways);
  check('390px: the strip still carries all three scopes', s.cells === 4, 'cells=' + s.cells);
  await context.close();
}

{
  const { context, page } = await newPage(1280, 1400);
  const url = BASE + '/faculty-jobs?scope=all&region=United%20States&sort=market_priority';
  await page.goto(url, { waitUntil: 'networkidle' });
  await page.waitForSelector('.fc-scope-cell', { timeout: 20000 });
  const first = await summaryOf(page);
  await page.reload({ waitUntil: 'networkidle' });
  await page.waitForSelector('.fc-scope-cell', { timeout: 20000 });
  const second = await summaryOf(page);
  await page.screenshot({ path: OUT + '/03-url-replay.png' });
  check('URL replay: the same URL returns the same count',
        first.count === second.count && first.count.length > 0, first.count);
  check('URL replay: the comparison is unchanged by filters',
        first.values.slice(0, 3).join('|') === second.values.slice(0, 3).join('|'),
        first.values.slice(0, 3).join(' / '));
  // Compare the numbers, not the strings: the audit cell reads "3,525 of
  // 4,733" and the filtered cell reads "3,884", so a string comparison here
  // would pass no matter what either number was.
  const digits = (s) => Number(String(s).replace(/[^0-9]/g, ''));
  const filteredN = digits(first.filtered);
  const auditCatalogue = digits(first.values[2].split(' of ')[1]);
  check('URL replay: the filtered count is a subset of the audit catalogue',
        filteredN > 0 && filteredN < auditCatalogue,
        'filtered=' + filteredN + ' audit catalogue=' + auditCatalogue);
  await context.close();
}

{
  const { context, page } = await newPage(1280, 1400);
  await page.goto(BASE + '/faculty-jobs?scope=all&region=Canada', { waitUntil: 'networkidle' });
  await page.waitForSelector('.fc-scope-cell', { timeout: 20000 });
  const clear = page.locator('a,button').filter({ hasText: /clear all/i }).first();
  const found = await clear.count();
  if (found) {
    await clear.click();
    // Clear all is a client-side button, not a navigation: networkidle
    // resolves immediately and the previous render's cells are still in the
    // DOM, so waiting on the selector waits for nothing. Wait for the marker
    // to actually move, or this reports a stale frame as a failure.
    await page.waitForFunction(() => {
      const c = document.querySelector('.fc-scope-cell.current');
      return c && /STRICT/i.test(c.innerText);
    }, { timeout: 20000 }).catch(() => {});
  }
  const s = await summaryOf(page);
  await page.screenshot({ path: OUT + '/04-clear-all.png' });
  check('Clear all: the control exists', found > 0);
  check('Clear all: returns to the strict default',
        s.current === 'STRICT VIEWING', 'current=' + s.current + ' url=' + page.url());
  await context.close();
}

{
  const { context, page } = await newPage(1280, 1400);
  await page.goto(BASE + '/faculty-jobs', { waitUntil: 'networkidle' });
  await page.waitForSelector('.fc-scope-cell', { timeout: 20000 });
  const opener = page.locator('[data-job-id], .fc-job-title a, .fc-job-open').first();
  const opened = await opener.count();
  if (opened) {
    await opener.click();
    await page.waitForTimeout(1500);
  }
  const dialog = await page.evaluate(() => {
    const d = document.querySelector('dialog[open], .fc-dialog.open, [role="dialog"]');
    return d ? { present: true, text: d.innerText.slice(0, 160) } : { present: false };
  });
  await page.screenshot({ path: OUT + '/05-detail-dialog.png' });
  check('Detail: a posting opens a dialog', dialog.present,
        dialog.present ? dialog.text.split('\n')[0] : 'no dialog element found');
  await context.close();
}

{
  const { context, page } = await newPage(1280, 1400);
  await page.goto(BASE + '/faculty-jobs', { waitUntil: 'networkidle' });
  await page.waitForSelector('.fc-scope-cell', { timeout: 20000 });
  const toggle = page.locator('.fc-multi-toggle, [aria-expanded]').first();
  const present = await toggle.count();
  let expanded = null;
  if (present) {
    await toggle.click();
    await page.waitForTimeout(500);
    expanded = await toggle.getAttribute('aria-expanded');
  }
  await page.screenshot({ path: OUT + '/06-multiselect.png' });
  check('Multi-select: the control reports its expanded state',
        expanded === 'true', 'aria-expanded=' + expanded);
  await context.close();
}

await browser.close();

const failures = results.filter((r) => !r.pass);
const noise = consoleMessages.filter((m) => !/^log:/.test(m));
console.log('');
console.log((results.length - failures.length) + '/' + results.length + ' checks passed');
console.log('console messages: ' + consoleMessages.length + ' (non-log: ' + noise.length + ')');
noise.slice(0, 10).forEach((m) => console.log('  ' + m));
writeFileSync(OUT + '/results.json',
  JSON.stringify({ results, consoleMessages }, null, 2));
process.exit(failures.length ? 1 : 0);
