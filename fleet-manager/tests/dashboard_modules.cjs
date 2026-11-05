// Actual served ES-module regression tests. DOM doubles are not browser QA.
// Run: node --experimental-vm-modules --test tests/dashboard_modules.cjs
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '../src/fleet_manager/ui/static/js');

class Element {
  constructor(tag = 'div') {
    this.tagName = tag.toUpperCase(); this.children = []; this.dataset = {};
    this.style = {}; this.listeners = {}; this.attributes = {}; this.value = '';
    this.className = ''; this._text = ''; this.disabled = false;
    this.classList = { toggle: () => {}, add: () => {}, remove: () => {} };
  }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(x => x.textContent).join(''); }
  set innerHTML(value) { this._html = String(value); this.children = []; this._text = ''; }
  get innerHTML() { return this._html || this.textContent; }
  appendChild(child) { child.parentNode = this; this.children.push(child); return child; }
  append(...children) { children.forEach(child => this.appendChild(child)); }
  replaceChildren(...children) { this.children = []; this.append(...children); }
  removeChild(child) { this.children = this.children.filter(x => x !== child); }
  replaceWith(child) { const p = this.parentNode; p.children[p.children.indexOf(this)] = child; child.parentNode = p; }
  remove() { this.parentNode?.removeChild(this); }
  get lastElementChild() { return this.children.at(-1); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  removeAttribute(name) { delete this.attributes[name]; }
  addEventListener(name, fn) { (this.listeners[name] ||= []).push(fn); }
  focus() { if (this.ownerDocument) this.ownerDocument.activeElement = this; }
  querySelectorAll(selector) {
    return this.children.flatMap(child => [child, ...child.querySelectorAll('*')])
      .filter(child => selector === '*' || selector === 'button' && child.tagName === 'BUTTON');
  }
  async fire(name) {
    const event = { target: this, preventDefault() {}, stopPropagation() {} };
    if (this['on' + name]) await this['on' + name](event);
    for (const fn of this.listeners[name] || []) await fn(event);
  }
}

async function harness(search = '', fetcher = async () => ({ nodes: [] })) {
  const elements = new Map();
  const document = {
    readyState: 'loading', activeElement: null, listeners: {},
    getElementById(id) {
      if (!elements.has(id)) { const e = new Element(); e.ownerDocument = document; elements.set(id, e); }
      return elements.get(id);
    },
    createElement(tag) { const e = new Element(tag); e.ownerDocument = document; return e; },
    querySelectorAll(selector) {
      return selector.startsWith('#nodes-table-body') ? document.getElementById('nodes-table-body').children : [];
    },
    addEventListener(name, fn) { (this.listeners[name] ||= []).push(fn); }
  };
  const windowListeners = {};
  const window = { location: new URL('http://localhost/dashboard' + search),
    addEventListener(name, fn) { (windowListeners[name] ||= []).push(fn); } };
  const history = { state: null, replaceState(_state, _title, url) { window.location = new URL(url, window.location); } };
  window.history = history;
  const requests = [];
  const context = vm.createContext({ document, window, history, URL, URLSearchParams,
    AbortController, console, navigator: {}, setInterval: () => 1, clearInterval() {},
    setTimeout: () => 1, clearTimeout() {},
    fetch: async (url, options) => {
      requests.push({ url, options }); const data = await fetcher(url, options);
      return { ok: true, status: 200, text: async () => JSON.stringify(data) };
    }
  });
  const modules = new Map();
  function moduleFor(filename) {
    filename = path.resolve(filename);
    if (!modules.has(filename)) modules.set(filename,
      new vm.SourceTextModule(fs.readFileSync(filename, 'utf8'), { context, identifier: filename }));
    return modules.get(filename);
  }
  const app = moduleFor(path.join(root, 'app.js'));
  await app.link((specifier, parent) => moduleFor(path.resolve(path.dirname(parent.identifier), specifier)));
  await app.evaluate();
  return { document, window, requests, windowListeners,
    element: id => document.getElementById(id),
    module: name => modules.get(path.join(root, name + '.js')).namespace };
}
const node = id => ({ id, name: id === 1 ? 'alpha' : 'beta', address: '192.0.2.' + id, ssh_port: 22 });
const fleet = { nodes: [
  { node: node(1), display_status: 'REACHABLE', setup_state: 'READY' },
  { node: node(2), display_status: 'NOT_CHECKED', setup_state: 'PENDING_SETUP' }
] };
const rowIds = h => h.element('nodes-table-body').children.map(row => row.dataset.nodeId).filter(Boolean);
const details = (id, state = 'PENDING_SETUP') => ({ node_id: id, setup_state: state,
  server_identity: { trust_state: 'UNTRUSTED', presented_fingerprint: 'SHA256:node' + id, key_type: 'ssh-ed25519' },
  client_authentication: { bootstrap_instruction: 'bootstrap for node ' + id } });
const settle = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); };

test('status filter removes previously rendered nonmatching rows and supports zero results', async () => {
  const h = await harness(); const state = h.module('state'); const render = h.module('fleet').renderFleet;
  render(fleet); assert.deepEqual(rowIds(h), ['1', '2']);
  state.setCurrentFilter('REACHABLE'); render(fleet); assert.deepEqual(rowIds(h), ['1']);
  state.setCurrentFilter('STALE'); render(fleet); assert.deepEqual(rowIds(h), []);
  state.setCurrentFilter('ALL'); render(fleet); assert.deepEqual(rowIds(h), ['1', '2']);
});

test('search renders exactly matching names, addresses and ports after previous rows', async () => {
  const h = await harness(); const state = h.module('state'); const render = h.module('fleet').renderFleet;
  render(fleet); state.setCurrentSearch('alpha'); render(fleet); assert.deepEqual(rowIds(h), ['1']);
  state.setCurrentSearch('192.0.2.2'); render(fleet); assert.deepEqual(rowIds(h), ['2']);
  state.setCurrentSearch('no match'); render(fleet); assert.deepEqual(rowIds(h), []);
  state.setCurrentSearch('22'); render(fleet); assert.deepEqual(rowIds(h), ['1', '2']);
});

test('existing pending inventory node offers a working onboarding resume action', async () => {
  const h = await harness('', async url => url.endsWith('/onboarding') ? details(2) : { nodes: [] });
  h.module('state').setOperatorToken('test-only'); h.module('fleet').renderFleet(fleet);
  const row = h.element('nodes-table-body').children.find(x => x.dataset.nodeId === '2');
  const action = row.querySelectorAll('button').find(x => /onboard|resume|setup/i.test(x.textContent));
  assert.ok(action, 'pending row must offer onboarding'); await action.fire('click'); await settle();
  assert.equal(h.element('onboarding-modal').style.display, 'flex');
  assert.ok(h.requests.some(r => r.url === '/api/nodes/2/onboarding'));
});

test('delayed details from node A cannot replace node B content or handlers', async () => {
  let release;
  const h = await harness('', url => url === '/api/nodes/1/onboarding'
    ? new Promise(resolve => { release = resolve; }) : Promise.resolve(details(2)));
  h.module('state').setOperatorToken('test-only'); const onboarding = h.module('node-onboarding');
  const first = onboarding.openOnboardingModal(node(1)); await settle();
  await onboarding.openOnboardingModal(node(2)); release(details(1, 'READY')); await first;
  assert.equal(h.element('bootstrap-cmd-snippet').textContent, 'bootstrap for node 2');
  assert.notEqual(h.element('step-complete-box').style.display, 'block');
  await h.element('scan-host-key-btn').fire('click');
  assert.ok(h.requests.some(r => r.url === '/api/nodes/2/scan-host-key'));
  assert.ok(!h.requests.some(r => r.url === '/api/nodes/1/scan-host-key'));
});

test('delayed host scan cannot install trust handler for a different modal owner', async () => {
  let release;
  const h = await harness('', url => url.endsWith('/scan-host-key')
    ? new Promise(resolve => { release = resolve; }) : Promise.resolve(details(url.includes('/1/') ? 1 : 2)));
  h.module('state').setOperatorToken('test-only'); const onboarding = h.module('node-onboarding');
  await onboarding.openOnboardingModal(node(1)); const scan = onboarding.scanHostKey(1); await settle();
  await onboarding.openOnboardingModal(node(2));
  release({ fingerprint: 'SHA256:OLD', key_type: 'ssh-ed25519' }); await scan;
  assert.ok(!h.element('scanned-fingerprint-content').textContent.includes('SHA256:OLD'));
  await h.element('step-trust-btn').fire('click');
  assert.ok(!h.requests.some(r => r.url === '/api/nodes/1/trust-host-key'));
});

test('closing and reopening the same node discards the previous request generation', async () => {
  let release; let calls = 0;
  const h = await harness('', url => {
    if (!url.endsWith('/onboarding')) return Promise.resolve({ nodes: [] });
    if (++calls === 1) return new Promise(resolve => { release = resolve; });
    return Promise.resolve(details(1, 'AUTHENTICATION_REQUIRED'));
  });
  h.module('state').setOperatorToken('test-only'); const onboarding = h.module('node-onboarding');
  const old = onboarding.openOnboardingModal(node(1)); await settle();
  onboarding.closeOnboardingModal(); await onboarding.openOnboardingModal(node(1));
  release(details(1, 'READY')); await old;
  assert.notEqual(h.element('step-complete-box').style.display, 'block');
});

test('failed revalidation clears previously READY completion panel', async () => {
  let ready = true;
  const h = await harness('', async url => {
    if (url.endsWith('/connectivity-check')) { ready = false; return { outcome: 'AUTH_FAILED' }; }
    return url.endsWith('/onboarding') ? details(1, ready ? 'READY' : 'AUTHENTICATION_REQUIRED') : { nodes: [] };
  });
  h.module('state').setOperatorToken('test-only'); await h.module('node-onboarding').openOnboardingModal(node(1));
  assert.equal(h.element('step-complete-box').style.display, 'block');
  await h.element('onboarding-check-ssh-btn').fire('click'); await settle();
  assert.notEqual(h.element('step-complete-box').style.display, 'block');
});

for (const query of ['?token=secret', '?token=%E0%A4%A&select=1', '?token=&token=second']) {
  test('direct navigation rejects and scrubs URL credential: ' + query.replace(/secret|second/g, 'fixture'), async () => {
    const h = await harness(query); h.module('app').initApp(); await settle();
    assert.equal(h.module('state').getOperatorToken(), null);
    assert.equal(h.window.location.search.includes('token'), false);
    assert.equal(h.element('auth-modal').style.display, 'flex');
    assert.equal(h.requests.length, 0);
  });
}

test('form authentication is memory-only, logout clears it and reload requires fresh entry', async () => {
  const h = await harness(); h.module('app').initApp(); h.element('token-input').value = 'test-only';
  await h.element('auth-form').fire('submit');
  assert.equal(h.module('state').getOperatorToken(), 'test-only');
  await h.element('logout-btn').fire('click'); assert.equal(h.module('state').getOperatorToken(), null);
  assert.equal(h.element('auth-modal').style.display, 'flex');
  const reloaded = await harness(); reloaded.module('app').initApp();
  assert.equal(reloaded.module('state').getOperatorToken(), null);
  assert.equal(reloaded.element('auth-modal').style.display, 'flex');
});

test('back navigation cannot restore URL credentials and scrubs stale token parameter', async () => {
  const h = await harness(); h.module('app').initApp();
  h.window.location = new URL('http://localhost/dashboard?token=historical');
  for (const listener of h.windowListeners.popstate || []) listener({ type: 'popstate' });
  for (const listener of h.windowListeners.pageshow || []) listener({ persisted: true });
  await settle(); assert.equal(h.module('state').getOperatorToken(), null);
  assert.equal(h.window.location.search.includes('token'), false);
});
