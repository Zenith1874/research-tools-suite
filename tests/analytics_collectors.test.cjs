// Exercise both collector adapters with an isolated DOM/network stub.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');
const settle = () => new Promise(resolve => setImmediate(resolve));

async function harness(site, version, preferences = {}) {
  let code = fs.readFileSync(path.join(__dirname, site === 'research'
    ? '../static/research-nav.js' : '../docs/portfolio_site_analytics.js'), 'utf8');
  if (site === 'research') code = code.slice(code.indexOf('  function sessionToken()'),
    code.indexOf('  function start()')) + '\ninitEventTracking();';
  const events = [], scripts = [], handlers = {};
  const listen = (name, fn) => (handlers[name] ||= []).push(fn);
  const origin = site === 'research' ? 'https://research.zhengresearch.com' : 'https://zhengresearch.com';
  const window = {location: new URL(origin + '/?private=query#private-fragment'),
    sessionStorage: {getItem: () => 'session-1'}, crypto: {randomUUID: () => 'random-page-id'},
    addEventListener: listen, screen: {width: 1200, height: 800}};
  const document = {readyState: 'complete', title: 'QA', referrer: 'https://example.org/?secret=1',
    visibilityState: 'visible', body: {}, addEventListener: listen,
    createElement: () => ({}), head: {appendChild: script => scripts.push(script)}};
  const context = vm.createContext({window, document, URL, Intl,
    Blob: class {constructor(parts) { this.text = parts.join(''); }},
    navigator: {...preferences, sendBeacon(url, blob) { events.push({url, ...JSON.parse(blob.text)}); return true; }},
    fetch: async () => ({ok: true, json: async () => ({analytics_behavior_version: version})})});
  vm.runInContext(code, context); await settle();
  function click(href) {
    const link = Object.assign(new URL(href, origin), {tagName: 'A', textContent: '', className: '',
      parentElement: null, hasAttribute: () => false, querySelector: () => null,
      getAttribute: name => name === 'href' ? href : '',
      closest: selector => selector.startsWith('a') ? link : null});
    (handlers.click || []).forEach(fn => fn({target: link}));
  }
  const hide = () => { document.visibilityState = 'hidden';
    (handlers.visibilitychange || []).forEach(fn => fn()); };
  return {window, document, events, scripts, click, hide};
}

for (const site of ['research', 'portfolio']) {
  test(site + ': old backend keeps legacy dwell and never emits new events', async () => {
    const h = await harness(site, undefined);
    assert.equal(h.scripts.length, 0);
    h.click('/next?private=query#secret'); h.hide(); h.hide();
    assert.equal(h.events.filter(x => x.event === 'session_end').length, 1);
    assert.equal(h.events.filter(x => x.event === 'internal_navigation').length, 0);
  });
  test(site + ': new backend enables behavior; click payloads omit query and fragment', async () => {
    const h = await harness(site, 1);
    assert.equal(h.scripts.length, 1);
    assert.match(h.scripts[0].src, /\/analytics-behavior.js\?v=/);
    let started = 0;
    h.window.ZRAnalyticsBehavior = {start: () => started++}; h.scripts[0].onload();
    h.click('/next?private=query#secret');
    h.click('https://example.org/article?private=query#secret'); h.hide();
    assert.equal(started, 1);
    assert.deepEqual(h.events.filter(x => x.event && x.event !== 'page_view').map(x => [x.event, x.target]),
      [['internal_navigation', '/next'], ['outbound_click', 'https://example.org/article']]);
    assert.doesNotMatch(JSON.stringify(h.events), /private=query|private-fragment|secret=1/);
  });
  test(site + ': privacy opt-outs suppress visits, events and helper loading', async () => {
    for (const preferences of [{doNotTrack: '1'}, {globalPrivacyControl: true}]) {
      const h = await harness(site, 1, preferences);
      h.click('/next'); h.hide();
      assert.equal(h.events.length, 0); assert.equal(h.scripts.length, 0);
    }
  });
}
