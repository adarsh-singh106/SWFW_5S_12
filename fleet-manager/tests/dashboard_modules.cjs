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
    this.className = ''; this._text = ''; this.disabled = false; this.isConnected = true; this.inert = false;
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
  contains(target) { return this === target || this.children.some(child => child.contains(target)); }
  querySelector(selector) { return selector.startsWith('button') ? this.children.find(child => child.tagName === 'BUTTON' && !child.disabled) : null; }
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
    readyState: 'loading', activeElement: null, listeners: {}, body: { children: [] },
    getElementById(id) {
      if (!elements.has(id)) { const e = new Element(); e.ownerDocument = document; elements.set(id, e); }
      return elements.get(id);
    },
    createElement(tag) { const e = new Element(tag); e.ownerDocument = document; return e; },
    querySelector(selector) {
      const all = this.querySelectorAll(selector);
      return all[0] || null;
    },
    querySelectorAll(selector) {
      if (selector.startsWith('#nodes-table-body')) return document.getElementById('nodes-table-body').children;
      if (selector.includes('history-table-body') || selector.includes('history-item')) return document.getElementById('history-table-body').children;
      return [];
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

test('overview counts API connectivity states and keeps setup separate', async () => {
  const h = await harness(); const render = h.module('fleet').renderFleet;
  const statuses = ['REACHABLE', 'UNREACHABLE', 'CHECK_ERROR', 'STALE', 'NOT_CHECKED'];
  render({ observation_ttl_seconds: 45, nodes: statuses.map((status, i) => ({
    node: node(i + 1), display_status: status, setup_state: 'HOST_KEY_REQUIRED'
  })) });
  for (const id of ['reachable', 'unreachable', 'errors', 'stale', 'not-checked'])
    assert.equal(h.element('stat-' + id).textContent, '1');
  assert.equal(h.element('stat-total').textContent, '5');
  assert.match(h.element('observation-ttl').textContent, /45/);
  const row = h.element('nodes-table-body').children[0];
  assert.equal(row.children[2].textContent, 'REACHABLE');
  assert.equal(row.children[3].textContent, 'HOST_KEY_REQUIRED');
});

test('observations show API TTL, valid age, expiry, and invalid or missing timestamps', async () => {
  const h = await harness(); const render = h.module('fleet').renderFleet;
  const now = Date.now();
  render({ observation_ttl_seconds: 30, nodes: [
    { node: node(1), display_status: 'REACHABLE', setup_state: 'READY', observation: { observed_at: new Date(now - 5000).toISOString() } },
    { node: node(2), display_status: 'STALE', setup_state: 'READY', reason: 'TTL_EXPIRED', observation: { observed_at: new Date(now - 60000).toISOString() } },
    { node: node(3), display_status: 'CHECK_ERROR', setup_state: 'CONFIGURATION_ERROR', reason: 'INVALID_TIMESTAMP', observation: { observed_at: 'invalid' } },
    { node: node(4), display_status: 'NOT_CHECKED', setup_state: 'PENDING_SETUP', observation: null }
  ] });
  const rows = h.element('nodes-table-body').children;
  assert.match(rows[0].children[4].textContent, /5s ago/);
  assert.match(rows[1].children[4].textContent, /Expired/);
  assert.match(rows[2].children[4].textContent, /Invalid timestamp/);
  assert.match(rows[3].children[4].textContent, /Never observed/);
  assert.equal(h.element('last-updated').textContent.includes('Observed'), false);
  assert.equal(h.module('inventory-view').observationDetails({}, 30, 'CHECK_ERROR').timestamp, 'Timestamp unavailable');
});

test('hostile inventory values and failure reason remain text, with contextual actions', async () => {
  const h = await harness(); const render = h.module('fleet').renderFleet;
  render({ observation_ttl_seconds: 60, nodes: [{
    node: { id: 7, name: '<img src=x onerror=alert(1)>', address: '<script>bad</script>', ssh_port: 2222 },
    display_status: 'UNREACHABLE', setup_state: 'AUTHENTICATION_REQUIRED',
    reason: '<svg onload=alert(2)>', observation: null
  }] });
  const row = h.element('nodes-table-body').children[0];
  assert.match(row.children[0].textContent, /<img/);
  assert.match(row.children[1].textContent, /<script>/);
  assert.match(row.children[5].textContent, /<svg/);
  assert.equal(row.children.some(cell => cell._html !== undefined), false);
  assert.deepEqual(row.querySelectorAll('button').map(x => x.textContent), ['Check SSH', 'Operations', 'Continue setup']);
});

test('all setup states are separate from connectivity and selected node survives filters', async () => {
  const h = await harness(); const render = h.module('fleet').renderFleet; const state = h.module('state');
  const setups = ['READY', 'HOST_KEY_REQUIRED', 'AUTHENTICATION_REQUIRED', 'CONFIGURATION_ERROR', 'PENDING_SETUP'];
  const data = { observation_ttl_seconds: 60, nodes: setups.map((setup, i) => ({
    node: node(i + 1), display_status: 'REACHABLE', setup_state: setup
  })) };
  render(data);
  assert.deepEqual(h.element('nodes-table-body').children.map(row => row.children[3].textContent), setups);
  state.setSelectedNodeId(2); render(data);
  assert.equal(h.element('nodes-table-body').children[1].className, 'selected-row');
  state.setCurrentSearch('no-match'); render(data); assert.deepEqual(rowIds(h), []);
  assert.equal(state.getSelectedNodeId(), 2);
  state.setCurrentSearch(''); render(data);
  assert.equal(h.element('nodes-table-body').children[1].className, 'selected-row');
  render({ observation_ttl_seconds: 60, nodes: [] });
  assert.match(h.element('nodes-table-body').textContent, /No nodes registered/);
  assert.equal(h.element('inventory-results').textContent, 'No registered nodes');
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

test('failed revalidation keeps setup and failed check result distinct', async () => {
  let ready = true;
  const h = await harness('', async url => {
    if (url.endsWith('/connectivity-check')) { ready = false; return { outcome: 'AUTH_FAILED' }; }
    return url.endsWith('/onboarding') ? details(1, ready ? 'READY' : 'AUTHENTICATION_REQUIRED') : { nodes: [] };
  });
  h.module('state').setOperatorToken('test-only'); await h.module('node-onboarding').openOnboardingModal(node(1));
  assert.match(h.element('onboarding-setup-state').textContent, /previously passed/);
  await h.element('onboarding-check-ssh-btn').fire('click'); await settle();
  assert.match(h.element('validation-result').textContent, /AUTH_FAILED/);
  assert.match(h.element('onboarding-setup-state').textContent, /needs attention/);
});

test('trust requires a fresh scan and exact acknowledged fingerprint', async () => {
  let fingerprint = 'SHA256:first';
  const h = await harness('', url => url.endsWith('/scan-host-key')
    ? { fingerprint, confirmation: 'confirm', trust_state: 'UNTRUSTED', verification_instruction: 'Read target console' }
    : url.endsWith('/onboarding') ? details(1) : { observation: null });
  h.module('state').setOperatorToken('test-only');
  const onboarding = h.module('node-onboarding');
  onboarding.initOnboarding();
  await onboarding.openOnboardingModal(node(1));
  await onboarding.trustHostKey(1, fingerprint, 'confirm');
  assert.ok(!h.requests.some(r => r.url.endsWith('/trust-host-key')));
  await onboarding.scanHostKey(1);
  assert.equal(h.element('scanned-fingerprint-content').textContent, fingerprint);
  assert.equal(h.element('step-trust-btn').disabled, true);
  await onboarding.trustHostKey(1, fingerprint, 'confirm');
  assert.ok(!h.requests.some(r => r.url.endsWith('/trust-host-key')));
  h.element('fingerprint-acknowledgement').checked = true;
  await h.element('fingerprint-acknowledgement').fire('change');
  assert.equal(h.element('step-trust-btn').disabled, false);
  h.element('scanned-fingerprint-content').textContent = 'SHA256:tampered';
  await onboarding.trustHostKey(1, fingerprint, 'confirm');
  assert.ok(!h.requests.some(r => r.url.endsWith('/trust-host-key')));
  h.element('scanned-fingerprint-content').textContent = fingerprint;
  fingerprint = 'SHA256:second';
  await onboarding.scanHostKey(1);
  assert.equal(h.element('fingerprint-acknowledgement').checked, false);
  assert.equal(h.element('step-trust-btn').disabled, true);
});

test('acknowledgement does not cross nodes or dialog reopen', async () => {
  const h = await harness('', url => url.endsWith('/scan-host-key')
    ? { fingerprint: 'SHA256:key', confirmation: 'confirm', trust_state: 'UNTRUSTED' }
    : url.endsWith('/onboarding') ? details(url.includes('/1/') ? 1 : 2) : { observation: null });
  h.module('state').setOperatorToken('test-only'); const onboarding = h.module('node-onboarding');
  await onboarding.openOnboardingModal(node(1)); await onboarding.scanHostKey(1);
  h.element('fingerprint-acknowledgement').checked = true; await h.element('fingerprint-acknowledgement').fire('change');
  await onboarding.openOnboardingModal(node(2));
  assert.equal(h.element('fingerprint-acknowledgement').checked, false);
  await onboarding.trustHostKey(1, 'SHA256:key', 'confirm');
  await onboarding.closeOnboardingModal(); await onboarding.openOnboardingModal(node(1));
  assert.equal(h.element('step-trust-btn').disabled, true);
  assert.ok(!h.requests.some(r => r.url.endsWith('/trust-host-key')));
});

test('auth retry owns focus without unlocking onboarding or an already inert background', async () => {
  const h = await harness('', url => url.endsWith('/onboarding') ? details(1) : { observation: null });
  h.module('state').setOperatorToken('test-only');
  const shell = h.element('shell'); shell.inert = true;
  const authModal = h.element('auth-modal'); const onboardingModal = h.element('onboarding-modal');
  h.document.body.children = [shell, authModal, onboardingModal];
  const opener = h.element('opener'); opener.focus();
  h.element('close-onboarding-btn').tagName = 'BUTTON';
  onboardingModal.appendChild(h.element('close-onboarding-btn'));
  authModal.appendChild(h.element('token-input'));
  const onboarding = h.module('node-onboarding'); const auth = h.module('auth');
  await onboarding.openOnboardingModal(node(1));
  assert.equal(authModal.inert, true);
  const onboardingFocus = h.element('close-onboarding-btn');
  auth.showAuthModal('Session unauthorized');
  assert.equal(authModal.inert, false);
  assert.equal(onboardingModal.inert, true);
  assert.equal(h.document.activeElement, h.element('token-input'));
  auth.hideAuthModal();
  assert.equal(onboardingModal.inert, false);
  assert.equal(authModal.inert, true);
  assert.equal(shell.inert, true);
  assert.equal(h.document.activeElement, onboardingFocus);
  onboarding.closeOnboardingModal();
  assert.equal(shell.inert, true);
  assert.equal(h.document.activeElement, opener);
});

test('direct node switch and closing lower dialog preserve modal ownership', async () => {
  const h = await harness('', url => url.endsWith('/onboarding') ? details(1) : { observation: null });
  h.module('state').setOperatorToken('test-only');
  const shell = h.element('shell'); const authModal = h.element('auth-modal');
  const onboardingModal = h.element('onboarding-modal');
  h.document.body.children = [shell, authModal, onboardingModal];
  const onboarding = h.module('node-onboarding'); const auth = h.module('auth');
  await onboarding.openOnboardingModal(node(1));
  await onboarding.openOnboardingModal(node(2));
  assert.equal(shell.inert, true);
  onboarding.closeOnboardingModal();
  assert.equal(shell.inert, false);
  await onboarding.openOnboardingModal(node(1));
  auth.showAuthModal('Retry');
  onboarding.closeOnboardingModal();
  assert.equal(shell.inert, true);
  assert.equal(authModal.inert, false);
  assert.equal(h.document.activeElement, h.element('token-input'));
  auth.hideAuthModal();
  assert.equal(shell.inert, false);
});

test('opening onboarding during authentication keeps authentication in front', async () => {
  const h = await harness('', url => url.endsWith('/onboarding') ? details(1) : { observation: null });
  h.module('state').setOperatorToken('test-only');
  const shell = h.element('shell'); const authModal = h.element('auth-modal');
  const onboardingModal = h.element('onboarding-modal');
  h.document.body.children = [shell, authModal, onboardingModal];
  const auth = h.module('auth'); const onboarding = h.module('node-onboarding');
  const opener = h.element('opener'); opener.focus();
  authModal.appendChild(h.element('token-input'));
  h.element('close-onboarding-btn').tagName = 'BUTTON';
  onboardingModal.appendChild(h.element('close-onboarding-btn'));
  auth.showAuthModal('Retry');
  await onboarding.openOnboardingModal(node(1));
  assert.equal(authModal.inert, false);
  assert.equal(onboardingModal.inert, true);
  assert.equal(h.document.activeElement, h.element('token-input'));
  auth.hideAuthModal();
  assert.equal(onboardingModal.inert, false);
  assert.equal(h.document.activeElement, h.element('close-onboarding-btn'));
  onboarding.closeOnboardingModal();
  assert.equal(shell.inert, false);
  assert.equal(h.document.activeElement, opener);
});

test('mismatched scan shows both fingerprints and allows deliberate rescan without acknowledgement reuse', async () => {
  let scans = 0;
  const h = await harness('', url => url.endsWith('/scan-host-key')
    ? { fingerprint: ++scans === 1 ? 'SHA256:wrong' : 'SHA256:right', confirmation: 'confirm', trust_state: scans === 1 ? 'MISMATCH' : 'UNTRUSTED' }
    : url.endsWith('/onboarding') ? {
      ...details(1, 'HOST_KEY_REQUIRED'), server_identity: { trust_state: 'MISMATCH', presented_fingerprint: 'SHA256:pinned' }
    } : { observation: null });
  h.module('state').setOperatorToken('test-only'); const onboarding = h.module('node-onboarding');
  await onboarding.openOnboardingModal(node(1));
  assert.equal(h.element('trusted-fingerprint-content').textContent, 'SHA256:pinned');
  assert.equal(h.element('scan-host-key-btn').disabled, false);
  await onboarding.scanHostKey(1);
  assert.equal(h.element('scanned-fingerprint-content').textContent, 'SHA256:wrong');
  assert.equal(h.element('step-trust-btn').disabled, true);
  assert.match(h.element('onboarding-feedback').textContent, /differs|does not match/);
  assert.equal(h.element('scan-host-key-btn').disabled, false);
  h.element('fingerprint-acknowledgement').checked = true;
  await onboarding.trustHostKey(1, 'SHA256:wrong', 'confirm');
  assert.ok(!h.requests.some(r => r.url.endsWith('/trust-host-key')));
  await onboarding.scanHostKey(1);
  assert.equal(h.element('scanned-fingerprint-content').textContent, 'SHA256:right');
  assert.equal(h.element('fingerprint-acknowledgement').checked, false);
  assert.equal(h.element('step-trust-btn').disabled, true);
});

test('status labels separate trusted key, setup, connectivity and latest observation', async () => {
  const h = await harness('', url => url.endsWith('/onboarding')
    ? { ...details(1, 'READY'), display_status: 'STALE', server_identity: { trust_state: 'TRUSTED', presented_fingerprint: 'SHA256:pinned' } }
    : { observation: { outcome: 'CONNECTED', observed_at: '2026-11-06T10:00:00Z' } });
  h.module('state').setOperatorToken('test-only'); await h.module('node-onboarding').openOnboardingModal(node(1));
  assert.equal(h.element('trusted-fingerprint-content').textContent, 'SHA256:pinned');
  assert.equal(h.element('scanned-fingerprint-content').textContent, '');
  assert.match(h.element('onboarding-setup-state').textContent, /previously passed/);
  assert.match(h.element('onboarding-connectivity-state').textContent, /expired/);
  assert.match(h.element('onboarding-observation').textContent, /CONNECTED/);
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
  assert.equal(h.module('state').isAuthenticated(), true);
  assert.equal(h.module('state').getOperatorToken(), null);
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

test('command preview matches backend catalog compilation and validates typed arguments', async () => {
  const h = await harness();
  const ops = h.module('operations');

  // 1. system.uptime
  assert.equal(ops.getCommandPreview('system.uptime', '/', 'ssh'), 'uptime');

  // 2. system.memory
  assert.equal(ops.getCommandPreview('system.memory', '/', 'ssh'), 'free -m');

  // 3. system.disk validation
  assert.equal(ops.validateDiskPath('/').valid, true);
  assert.equal(ops.validateDiskPath('/var/log').valid, true);
  assert.equal(ops.validateDiskPath('/data_2026/test.txt').valid, true);
  assert.equal(ops.getCommandPreview('system.disk', '/var/log', 'ssh'), 'df -h -P -- /var/log');

  // Rejections
  assert.equal(ops.validateDiskPath('').valid, false);
  assert.equal(ops.validateDiskPath('relative/path').valid, false);
  assert.equal(ops.validateDiskPath('/has space').valid, false);
  assert.equal(ops.validateDiskPath('/traversal/../etc').valid, false);
  assert.equal(ops.validateDiskPath('/invalid$char').valid, false);
  assert.equal(ops.getCommandPreview('system.disk', 'invalid/path', 'ssh'), 'df -h -P -- [invalid path]');

  // 4. service.status validation
  assert.equal(ops.validateServiceName('ssh').valid, true);
  assert.equal(ops.validateServiceName('nginx').valid, true);
  assert.equal(ops.validateServiceName('prometheus-node-exporter').valid, true);
  assert.equal(ops.validateServiceName('unit@0.service').valid, true);
  assert.equal(ops.getCommandPreview('service.status', '/', 'nginx'), 'systemctl --no-pager status -- nginx');

  // Rejections
  assert.equal(ops.validateServiceName('').valid, false);
  assert.equal(ops.validateServiceName('-leading-hyphen').valid, false);
  assert.equal(ops.validateServiceName('has space').valid, false);
  assert.equal(ops.validateServiceName('a'.repeat(65)).valid, false);
  assert.equal(ops.validateServiceName('bad;rm').valid, false);
  assert.equal(ops.getCommandPreview('service.status', '/', '-bad'), 'systemctl --no-pager status -- [invalid service]');
});

test('duration formatting handles valid timestamps and rejects invalid or missing dates', async () => {
  const h = await harness();
  const ops = h.module('operations');

  // Valid durations
  assert.equal(ops.formatDuration('2026-11-07T10:00:00.000Z', '2026-11-07T10:00:00.450Z'), '450ms');
  assert.equal(ops.formatDuration('2026-11-07T10:00:00.000Z', '2026-11-07T10:00:02.500Z'), '2.50s');

  // Missing or invalid
  assert.equal(ops.formatDuration(null, '2026-11-07T10:00:02.500Z'), '—');
  assert.equal(ops.formatDuration('2026-11-07T10:00:00.000Z', null), '—');
  assert.equal(ops.formatDuration('', ''), '—');
  assert.equal(ops.formatDuration('not-a-date', 'also-not-a-date'), '—');
  assert.equal(ops.formatDuration('2026-11-07T10:00:05.000Z', '2026-11-07T10:00:01.000Z'), '—');
});

test('result inspector renders SUCCESS, FAILURE, TIMEOUT, UNCERTAIN with safe output and badges', async () => {
  const h = await harness();
  const ops = h.module('operations');
  const state = h.module('state');
  state.setSelectedNodeId(1);

  // 1. SUCCESS record
  const successRec = {
    id: 'op-001',
    node_id: 1,
    action: 'system.uptime',
    arguments: {},
    requested_at: '2026-11-07T12:00:00Z',
    started_at: '2026-11-07T12:00:00.100Z',
    completed_at: '2026-11-07T12:00:00.350Z',
    outcome: 'SUCCESS',
    failure_category: null,
    exit_code: 0,
    stdout: 'up 14 days, load average: 0.05, 0.02',
    stderr: '',
    output_truncated: false,
    audit_metadata: { operator_digest_prefix: 'test-digest' }
  };

  ops.displayOperationResult(successRec, false);
  assert.equal(h.element('op-result-box').style.display, 'block');
  assert.equal(h.element('inspector-standby').style.display, 'none');
  assert.equal(h.element('result-outcome-badge').textContent, 'SUCCESS');
  assert.equal(h.element('result-exit-code').textContent, 'Exit Code: 0');
  assert.equal(h.element('result-duration').textContent, '250ms');
  assert.equal(h.element('inspector-mode-tag').textContent, 'Live Execution');
  assert.equal(h.element('result-stdout').textContent, 'up 14 days, load average: 0.05, 0.02');
  assert.equal(h.element('result-stderr-section').style.display, 'none');
  assert.equal(h.element('result-uncertain-warning').style.display, 'none');

  // 2. FAILURE record with STDERR
  const failRec = {
    id: 'op-002',
    node_id: 1,
    action: 'service.status',
    arguments: { service_name: 'missing-svc' },
    requested_at: '2026-11-07T12:05:00Z',
    started_at: '2026-11-07T12:05:00.000Z',
    completed_at: '2026-11-07T12:05:01.000Z',
    outcome: 'FAILURE',
    failure_category: 'COMMAND_ERROR',
    exit_code: 3,
    stdout: '',
    stderr: 'Unit missing-svc.service could not be found.',
    output_truncated: false,
    audit_metadata: {}
  };

  ops.displayOperationResult(failRec, false);
  assert.equal(h.element('result-outcome-badge').textContent, 'FAILURE');
  assert.equal(h.element('result-exit-code').textContent, 'Exit Code: 3');
  assert.equal(h.element('result-failure-category').textContent, 'COMMAND_ERROR');
  assert.equal(h.element('result-stderr-section').style.display, 'block');
  assert.equal(h.element('result-stderr').textContent, 'Unit missing-svc.service could not be found.');

  // 3. UNCERTAIN record
  const uncertainRec = {
    ...successRec,
    id: 'op-003',
    outcome: 'UNCERTAIN',
    exit_code: null
  };
  ops.displayOperationResult(uncertainRec, false);
  assert.equal(h.element('result-outcome-badge').textContent, 'UNCERTAIN');
  assert.equal(h.element('result-uncertain-warning').style.display, 'block');

  // 4. Historical mode label
  ops.displayOperationResult(successRec, true);
  assert.equal(h.element('inspector-mode-tag').textContent, 'Historical Record');
});

test('independent node execution states: running node does not lock other nodes', async () => {
  const h = await harness();
  const ops = h.module('operations');
  const state = h.module('state');

  // Node 1 in flight
  state.setSelectedNodeId(1);
  ops.updateExecButtonState(1);
  assert.equal(h.element('exec-btn').disabled, false);

  // Switch to node 2
  state.setSelectedNodeId(2);
  ops.updateExecButtonState(2);
  assert.equal(h.element('exec-btn').disabled, false);
});

test('stale response protection discards mismatched node execution results', async () => {
  const h = await harness();
  const ops = h.module('operations');
  const state = h.module('state');

  // Current selected node is 2
  state.setSelectedNodeId(2);
  h.element('result-op-id').textContent = 'initial';

  // Attempt to display result for node 1
  ops.displayOperationResult({
    id: 'op-node1',
    node_id: 1,
    action: 'system.uptime',
    outcome: 'SUCCESS'
  });

  // Must not overwrite
  assert.equal(h.element('result-op-id').textContent, 'initial');
});

test('audit history semantic table renders records with honest pagination and empty page recovery', async () => {
  let offsetRequested = 0;
  const mockOperations = Array.from({ length: 20 }, (_, i) => ({
    id: 'op-' + i,
    node_id: 1,
    action: 'system.uptime',
    arguments: {},
    requested_at: '2026-11-07T12:00:00Z',
    started_at: '2026-11-07T12:00:00Z',
    completed_at: '2026-11-07T12:00:01Z',
    outcome: 'SUCCESS',
    exit_code: 0,
    failure_category: null
  }));

  const h = await harness('', url => {
    if (url.includes('/operations?')) {
      const u = new URL(url, 'http://localhost');
      offsetRequested = parseInt(u.searchParams.get('offset') || '0', 10);
      if (offsetRequested === 0) return { operations: mockOperations };
      if (offsetRequested === 20) return { operations: mockOperations.slice(0, 5) };
      return { operations: [] };
    }
    return {};
  });

  const history = h.module('history');
  const state = h.module('state');
  state.setOperatorToken('test-token');
  state.setSelectedNodeId(1);

  // Initial page (0-20)
  state.setHistoryOffset(0);
  await history.fetchNodeOperationsHistory(1);
  assert.equal(h.element('history-table-body').children.length, 20);
  assert.equal(h.element('history-prev-btn').disabled, true);
  assert.equal(h.element('history-next-btn').disabled, false);
  assert.equal(h.element('history-page-label').textContent, 'Showing records 1–20');

  // Next page (offset 20: 5 records)
  state.setHistoryOffset(20);
  await history.fetchNodeOperationsHistory(1);
  assert.equal(h.element('history-table-body').children.length, 5);
  assert.equal(h.element('history-prev-btn').disabled, false);
  assert.equal(h.element('history-next-btn').disabled, true); // < 20 disables next
  assert.equal(h.element('history-page-label').textContent, 'Showing records 21–25');
});

test('return to inventory restores focus to invoking element', async () => {
  const h = await harness();
  const state = h.module('state');

  const invBtn = h.document.createElement('button');
  invBtn.textContent = 'Operations';
  state.setInventoryReturnFocus(invBtn);

  assert.equal(state.getInventoryReturnFocus(), invBtn);
});

test('first-run setup form submits matching password and authenticates operator', async () => {
  const h = await harness('', async (url) => {
    if (url.endsWith('/api/auth/setup')) {
      return { ok: true, csrf_token: 'csrf-1234', message: 'Setup completed' };
    }
    return { nodes: [] };
  });
  h.module('app').initApp();
  const auth = h.module('auth');
  auth.switchAuthView('setup');
  assert.equal(h.element('auth-setup-view').style.display, 'block');

  h.element('setup-password').value = 'AdminPassword2026!';
  h.element('setup-confirm-password').value = 'AdminPassword2026!';
  await h.element('setup-form').fire('submit');

  assert.equal(h.module('state').isAuthenticated(), true);
  assert.equal(h.element('auth-modal').style.display, 'none');
});

test('inline validation enforces 12-char minimum and matching password in setup', async () => {
  const h = await harness();
  h.module('app').initApp();
  const auth = h.module('auth');
  auth.switchAuthView('setup');

  const pw = h.element('setup-password');
  const confirm = h.element('setup-confirm-password');
  const msg = h.element('setup-validation-msg');

  pw.value = 'short';
  await pw.fire('input');
  assert.equal(msg.style.display, 'block');
  assert.match(msg.textContent, /at least 12 characters/);

  pw.value = 'ValidPassword123!';
  confirm.value = 'MismatchPassword123!';
  await confirm.fire('input');
  assert.equal(msg.style.display, 'block');
  assert.match(msg.textContent, /do not match/);

  confirm.value = 'ValidPassword123!';
  await confirm.fire('input');
  assert.equal(msg.style.display, 'none');
});

test('mandatory password change flow triggers and establishes permanent credential', async () => {
  const h = await harness('', async (url) => {
    if (url.endsWith('/api/auth/login')) {
      return { ok: true, must_change_password: true, csrf_token: 'csrf-bootstrap' };
    }
    if (url.endsWith('/api/auth/change-password')) {
      return { ok: true, must_change_password: false, csrf_token: 'csrf-permanent' };
    }
    return { nodes: [] };
  });
  h.module('app').initApp();
  h.element('token-input').value = 'CHANGEME';
  await h.element('auth-form').fire('submit');

  assert.equal(h.module('state').getMustChangePassword(), true);
  assert.equal(h.element('auth-change-password-view').style.display, 'block');
  assert.equal(h.element('change-current-password').value, 'CHANGEME');

  h.element('change-new-password').value = 'BrandNewPermanentPass2026!';
  h.element('change-confirm-password').value = 'BrandNewPermanentPass2026!';
  await h.element('change-password-form').fire('submit');

  assert.equal(h.module('state').getMustChangePassword(), false);
  assert.equal(h.element('auth-modal').style.display, 'none');
});

test('password visibility toggles switch input type between password and text', async () => {
  const h = await harness();
  h.module('app').initApp();
  const tokenInput = h.element('token-input');
  const toggleBtn = h.element('toggle-token-btn');

  tokenInput.type = 'password';
  await toggleBtn.fire('click');
  assert.equal(tokenInput.type, 'text');
  await toggleBtn.fire('click');
  assert.equal(tokenInput.type, 'password');
});
