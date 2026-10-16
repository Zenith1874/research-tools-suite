// Run with: node --test tests/portfolio_analytics_ui.test.cjs
// Exercise request ordering and rendering as pure JavaScript, without a browser.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');

const html = fs.readFileSync(path.join(__dirname, '../private_static/portfolio_analytics.html'), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const settle = () => new Promise(resolve => setImmediate(resolve));

function harness() {
  const elements = new Map(), requests = [], timers = new Map();
  let nextTimer = 0;
  function element(id) {
    if (!elements.has(id)) {
      const classes = new Set();
      const node = {innerHTML: '', textContent: '', className: '', value: '', disabled: false,
        previousElementSibling: {textContent: id}, setAttribute() {}, addEventListener() {},
        classList: {toggle(name, on) { on ? classes.add(name) : classes.delete(name); },
          contains(name) { return classes.has(name); }}};
      Object.defineProperty(node, 'selectedOptions', {get: () => [{text: node.value}]});
      elements.set(id, node);
    }
    return elements.get(id);
  }
  element('days').value = '30';
  element('site').value = 'all';
  const context = vm.createContext({
    document: {getElementById: element, querySelectorAll: () => []},
    URLSearchParams, AbortController,
    Intl: {DateTimeFormat: () => ({resolvedOptions: () => ({timeZone: 'America/Denver'})})},
    setTimeout(callback) { const id = ++nextTimer; timers.set(id, callback); return id; },
    clearTimeout(id) { timers.delete(id); },
    fetch(url, options) { return new Promise((resolve, reject) => {
      requests.push({url, options, resolve, reject});
    }); },
  });
  vm.runInContext(script, context);
  function respond(index, data = {}, status = 200) {
    requests[index].resolve({ok: status === 200, status, json: async () => ({
      generated_at: '2026-09-20T14:00:00+00:00',
      time_range: {timezone: 'America/Denver'}, retention_policy: 'permanent',
      daily: [], trend: {status: 'empty'}, ...data,
    })});
  }
  return {context, element, requests, timers, respond,
    run: code => vm.runInContext(code, context)};
}

test('requests include the browser timezone and ignore late old responses', async () => {
  const h = harness();
  assert.equal(new URL('http://localhost' + h.requests[0].url).searchParams.get('tz'), 'America/Denver');
  h.element('site').value = 'research';
  const latest = h.run("currentView='diagnostics'; load();");
  assert.equal(h.requests[0].options.signal.aborted, true);
  h.respond(1, {overview: {traffic_quality: {raw_requests: {views: 28}}}});
  await latest;
  const rendered = h.element('diagnosticKpis').innerHTML;
  assert.match(rendered, /28 条/);
  h.respond(0, {overview: {page_views: {views: 999}}});
  await settle();
  assert.equal(h.element('diagnosticKpis').innerHTML, rendered);
  assert.match(h.element('status').textContent, /Research · 诊断记录/);
  assert.equal(h.element('refresh').disabled, false);
});

test('a failed filter request hides earlier results and enables retry', async () => {
  const h = harness();
  h.respond(0, {overview: {page_views: {views: 5}}});
  await settle();
  assert.equal(h.element('visitorView').classList.contains('hidden'), false);
  h.element('days').value = '1';
  const pending = h.run('load()');
  assert.equal(h.element('visitorView').classList.contains('hidden'), true);
  h.respond(1, {error: 'temporarily unavailable'}, 503);
  await pending;
  assert.equal(h.element('visitorView').classList.contains('hidden'), true);
  assert.match(h.element('status').textContent, /加载失败/);
  assert.equal(h.element('refresh').disabled, false);
});

test('a stalled request can time out without leaving refresh disabled', async () => {
  const h = harness();
  [...h.timers.values()][0]();
  assert.equal(h.requests[0].options.signal.aborted, true);
  h.requests[0].reject(new DOMException('Aborted', 'AbortError'));
  await settle();
  assert.match(h.element('status').textContent, /加载超时/);
  assert.equal(h.element('refresh').disabled, false);
});

test('monthly trend aggregation retains older records and zero bars stay zero', () => {
  const h = harness();
  const daily = Array.from({length: 93}, (_, index) => ({
    date: new Date(Date.UTC(2026, 0, 1 + index)).toISOString().slice(0, 10),
    views: index === 0 ? 20 : index === 92 ? 3 : 0,
  }));
  h.context.dailyFixture = daily;
  const buckets = h.run('trendBuckets(dailyFixture)');
  assert.equal(buckets.monthly, true);
  assert.equal(buckets.rows[0].date, '2026-01');
  assert.equal(buckets.rows.reduce((total, row) => total + row.views, 0), 23);
  h.run("renderTrend('visitorTrend',{trend:{status:'ok'},daily:[{date:'2026-09-19',views:0},{date:'2026-09-20',views:5}]})");
  assert.match(h.element('visitorTrend').innerHTML, /height:0%/);
  assert.match(h.element('visitorTrend').innerHTML, /height:100%/);
});

test('mobile details show every returned record within the bounded container', async () => {
  const h = harness();
  const visits = Array.from({length: 30}, (_, index) => ({
    visited_at: '2026-09-20T14:00:00+00:00', site: 'research', path: '/page-' + index,
    traffic_class: 'confirmed_browser',
  }));
  const events = Array.from({length: 25}, (_, index) => ({
    occurred_at: '2026-09-20T14:00:00+00:00', site: 'research', path: '/page-' + index,
    scope: 'remote', event_name: 'page_view',
  }));
  const pending = h.run("currentView='diagnostics'; load()");
  h.respond(1, {recent_visits: visits, events: {recent: events}, overview: {
    events: {events: 125}, traffic_quality: {raw_requests: {views: 230}},
  }});
  await pending;
  assert.equal((h.element('diagnosticVisitCards').innerHTML.match(/summary-card/g) || []).length, 30);
  assert.equal((h.element('diagnosticEventCards').innerHTML.match(/summary-card/g) || []).length, 25);
  assert.match(h.element('diagnosticRecentVisitCount').textContent, /30 条 \/ 共 230 条/);
});

test('new behavior metrics disclose their units, no-history state and escape paths', async () => {
  const h = harness();
  h.respond(0, {view: 'visitor', events: {behavior: {foreground: {samples: 2,
    median_seconds: 25, over_30_seconds: 1}, scroll_depth: [{label: '75', events: 2}],
    navigation: [{label: '/<script> → /gdp', events: 1}]}}});
  await settle();
  const content = h.element('visitorBehavior').innerHTML;
  assert.match(content, /25 秒/); assert.match(content, /1 \/ 2 个样本/);
  assert.match(content, /仅外部事件/); assert.match(content, /不回填历史/);
  assert.match(content, /不是阅读人数/); assert.doesNotMatch(content, /<script>/);
  h.run("renderBehavior({events:{behavior:{foreground:{samples:0}}}},'visitor')");
  assert.match(h.element('visitorBehavior').innerHTML, /暂无新版时长样本/);
});
