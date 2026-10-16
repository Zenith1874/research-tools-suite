// Pure JS collector tests: no network, real browser or production records.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');
const source = fs.readFileSync(path.join(__dirname, '../static/analytics-behavior.js'), 'utf8');

function harness(options = {}) {
  const handlers = {}, timers = new Map(), events = [];
  let clock = 0, timerId = 0;
  const listen = (name, handler) => (handlers[name] ||= []).push(handler);
  const document = {visibilityState: options.hidden ? 'hidden' : 'visible',
    documentElement: {scrollHeight: 4000}, body: {scrollHeight: 4000}, addEventListener: listen};
  const window = {crypto: {randomUUID: () => 'random-page-id-0001'},
    addEventListener: listen, innerHeight: 800, scrollY: 0};
  const context = vm.createContext({window, document, navigator: options.navigator || {},
    performance: {now: () => clock},
    setTimeout(fn, delay) { const id = ++timerId; timers.set(id, {at: clock + delay, fn}); return id; },
    clearTimeout: id => timers.delete(id)});
  vm.runInContext(source, context);
  const send = (event, target, extra = {}) => events.push({event, target, ...extra});
  window.ZRAnalyticsBehavior.start(send);
  function advance(ms) {
    const end = clock + ms;
    for (;;) {
      const next = [...timers.entries()].sort((a, b) => a[1].at - b[1].at)[0];
      if (!next || next[1].at > end) break;
      clock = next[1].at; timers.delete(next[0]); next[1].fn();
    }
    clock = end;
  }
  const fire = (name, event = {isTrusted: true}) => (handlers[name] || []).forEach(fn => fn(event));
  const visibility = state => { document.visibilityState = state; fire('visibilitychange'); };
  return {window, document, context, send, events, timers, advance, fire, visibility};
}

test('visible time pauses, resumes, reports cumulatively and handles BFCache', () => {
  const h = harness();
  h.advance(20000); h.visibility('hidden'); h.advance(120000);
  assert.deepEqual(h.events.map(x => x.dwell_seconds), [15, 20]);
  assert.equal(h.timers.size, 0);
  h.visibility('visible'); h.advance(20000); h.fire('pagehide');
  h.visibility('hidden');
  assert.deepEqual(h.events.map(x => x.dwell_seconds), [15, 20, 30, 40]);
  h.advance(300000); h.visibility('visible'); h.fire('pageshow'); h.advance(5000); h.fire('pagehide');
  assert.equal(h.events.at(-1).dwell_seconds, 45);
  assert.equal(new Set(h.events.map(x => x.page_id)).size, 1);
});

test('background-loaded pages wait and duplicate initialization is harmless', () => {
  const h = harness({hidden: true});
  h.window.ZRAnalyticsBehavior.start(h.send);
  h.advance(300000); assert.equal(h.events.length, 0);
  h.visibility('visible'); h.advance(15000);
  assert.deepEqual(h.events.map(x => x.dwell_seconds), [15]);
});

test('short/initial/synthetic scrolls do not count; depth thresholds fire once', () => {
  const h = harness();
  h.fire('scroll'); assert.equal(h.events.length, 0);
  h.window.scrollY = 300; h.fire('scroll', {isTrusted: false});
  assert.equal(h.events.length, 0);
  h.fire('scroll');
  h.window.scrollY = 3000; h.fire('scroll'); h.fire('scroll');
  assert.deepEqual(h.events.map(x => x.target), ['25', '50', '75', '90']);
  const short = harness(); short.document.documentElement.scrollHeight = 500;
  short.document.body.scrollHeight = 500; short.window.scrollY = 1; short.fire('scroll');
  assert.equal(short.events.length, 0);
});

test('DNT and GPC suppress every new event and timer', () => {
  for (const navigator of [{doNotTrack: '1'}, {globalPrivacyControl: true}]) {
    const h = harness({navigator});
    h.advance(600000); h.visibility('hidden'); h.window.scrollY = 3000; h.fire('scroll');
    assert.equal(h.events.length, 0); assert.equal(h.timers.size, 0);
  }
});

test('long open pages have bounded checkpoints instead of constant heartbeats', () => {
  const h = harness(); h.advance(7200000);
  assert.deepEqual(h.events.map(x => x.dwell_seconds), [15, 30, 60, 180, 600, 1800]);
  h.fire('pagehide'); assert.equal(h.events.at(-1).dwell_seconds, 7200);
});
