// The two write cards that are not built with v1t(): the Stage 2/3 connection card (v9-stage-connections.js, rl()) and
// the Stage 2 selection component (its own script and words table, inside a shadow root). When any of their text is
// missing, empty or still Simplified in en/tw, the card is disabled and click, Enter and submit send nothing; zh is not
// affected. Mutations (a gate that always says ok) must fail this test. No network, no browser.
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const read = name => fs.readFileSync(path.join(__dirname, name), 'utf8');
const TEXT = read('wiki-v1-text.js');
const tick = () => new Promise(resolve => setImmediate(resolve));
const SELECTION_TESTS = path.join(__dirname, '../plugins/auto-research-agent/tests/test_project_stage2_selection_embedded.cjs');

// window handlers run first (capture), then the card's own document handlers, as in the page.
function eventChain(windowHandlers, documentHandlers) {
 return async event => {
  let stopped = false;
  event.preventDefault = () => {};
  event.stopImmediatePropagation = () => { stopped = true; };
  for (const fn of windowHandlers.filter(h => h.type === event.type).map(h => h.fn)) { fn(event); if (stopped) return false; }
  for (const fn of documentHandlers.filter(h => h.type === event.type).map(h => h.fn)) { await fn(event); }
  return true;
 };
}

// ---------- 1. connection card ----------
const hash = char => char.repeat(64);
function connectionScenario(lang, {removeEn = false, text = TEXT} = {}) {
 const windowHandlers = [], documentHandlers = [];
 const posts = [];
 const app = {lang, page: 'workspace', stage: 2, el: {contains: () => true, querySelector: () => null}};
 const project = {project_ref: 'P1', project_id: 'id-1', input_version: 1, revision: 2, brief_sha256: hash('a')};
 const row = {status: 'connectable', profile_sha256: hash('b'), reason: null, connection_id: null, receipt_id: null};
 const context = vm.createContext({
  apps: [app], console: {warn() {}}, queueMicrotask: () => {}, crypto: {randomUUID: () => 'k1'},
  rt: {ref: 'P1', epoch: 1, loading: false, busy: false, pending: null, controlHeld: false, overview: {project}},
  canonicalReadonly: () => false, projectPath: (ref, tail = '') => '/api/projects/' + ref + (tail ? '/' + tail : ''),
  rx: value => String(value).replaceAll('&', '&amp;').replaceAll('"', '&quot;').replaceAll('<', '&lt;'),
  livePaint() {}, liveRecover() {}, v9ContinuationConflict: () => false, wikiStage2State: undefined,
  sessionStorage: {getItem: () => null, setItem() {}, removeItem() {}}, navigator: {locks: {request: async (name, options, callback) => callback({name})}},
  window: {addEventListener: (type, fn) => windowHandlers.push({type, fn}), RESEARCH_PROJECTS: {}},
  document: {addEventListener: (type, fn) => documentHandlers.push({type, fn}), activeElement: null, body: {}},
  async liveRequest(requestPath, body) {
   if (body) { posts.push({path: requestPath, body}); throw Error('stub: no real service'); }
   if (requestPath.endsWith('/connections')) return {project_ref: 'P1', execution_authorized: false, connections: {'stage2-controller': row}};
   if (requestPath.endsWith('/overview')) return {project};
   throw Error('unexpected read ' + requestPath);
  }
 });
 // rl() exactly as the runtime defines it.
 const runtime = read('renderer/src/runtime.js');
 const rlLine = runtime.slice(runtime.indexOf('const rl = '), runtime.indexOf('\n', runtime.indexOf('const rl = ')));
 vm.runInContext('const li = a => a.lang === "en" ? 1 : a.lang === "tw" ? 2 : 0; const translated = (a, arr) => arr[li(a)];\n' + rlLine, context);
 vm.runInContext(text, context);
 vm.runInContext(read('v9-stage-connections.js'), context);
 if (removeEn) vm.runInContext("v1Text['接通本课题'] = {en: 'Connect this project', tw: ''}; ", context); // placeholder, see below
 const basis = vm.runInContext('v9ConnectionBasis(rt.overview.project)', context);
 vm.runInContext('v9ConnectionView = ' + JSON.stringify({epoch: 1, basis, stage: 'stage2-controller', reading: false, row, error: ''}), context);
 const html = vm.runInContext('v9ConnectionPanel(apps[0])', context);
 const token = /data-connection-basis="([^"]*)"/.exec(html)[1].replaceAll('&quot;', '"').replaceAll('&amp;', '&');
 const card = {dataset: {}, outerHTML: html, notes: [],
  querySelector(selector) { return selector === '[data-v1-gate-note]' && this.notes.length ? this.notes[0] : null; },
  insertAdjacentHTML(where, markup) { this.outerHTML += markup; this.notes.push(markup); }};
 const gated = () => card.dataset.v1Gated === '1';
 const button = {disabled: false, dataset: {connectionBasis: token, v9Connection: 'connect'}, tagName: 'BUTTON',
  closest(selector) {
   if (selector === '[data-v9-connection]') return button;
   if (selector === '[data-v1-card]') return null;
   if (selector === 'section') return card;
   if (selector === '[data-v1-gated]') return gated() ? card : null;
   if (selector.startsWith('[data-v1-write]')) return /data-v1-write/.test(html) ? button : null;
   return null;
  }};
 return {html, card, button, windowHandlers, documentHandlers, posts, context, hasWriteMark: /data-v1-write[^>]*data-v9-connection="connect"/.test(html)};
}
async function pressConnect(s) {
 const chain = eventChain(s.windowHandlers, s.documentHandlers);
 const root = {querySelectorAll: selector => selector === '[data-v1-write]' ? [s.button] : []};
 vm.runInContext('v1GateCards', s.context)(root);
 s.button.disabled = false; // a later re-render of the button must not matter: the guard is independent of "disabled"
 await chain({type: 'click', target: s.button});
 await chain({type: 'keydown', key: 'Enter', target: s.button});
 await chain({type: 'submit', target: s.button});
 await tick(); await tick();
 return {gated: s.card.dataset.v1Gated === '1', posts: s.posts.length, note: s.card.notes[0] || ''};
}

test('connection card: the write button carries the mark and a fully translated card is open in zh and en', async () => {
 for (const lang of ['zh', 'en']) {
  const s = connectionScenario(lang);
  assert.ok(s.hasWriteMark, 'the Connect button is a write button');
  assert.ok(/data-v9-connection="connect"/.test(s.html));
  const r = await pressConnect(s);
  assert.equal(r.gated, false, lang + ' card is open when nothing fell back');
  assert.ok(r.posts >= 1, lang + ': the click reaches the card handler and tries to write: ' + r.posts);
 }
});

test('connection card: text that is missing in the language gates the card; nothing is sent; zh is not affected', async () => {
 // tw: the card's own rl() calls omit most Traditional texts, so it is already gated with the current code.
 const tw = connectionScenario('tw');
 const rtw = await pressConnect(tw);
 assert.equal(rtw.gated, true, 'a card with rl() text that has no Traditional version is gated');
 assert.equal(rtw.posts, 0, 'click, Enter and submit send nothing');
 assert.match(rtw.note, /切換到簡體中文/, 'the reason is written in Traditional');
 // en: blank one English text of the card by editing the source the card is built from.
 const source = read('v9-stage-connections.js').replace("rl('接通本课题','Connect this project')", "rl('接通本课题','')");
 assert.notEqual(source, read('v9-stage-connections.js'), 'the English text was removed');
 const windowHandlers = [], documentHandlers = [];
 const original = vm.runInContext;
 // run the same scenario with the edited card source
 const patched = fs.readFileSync;
 fs.readFileSync = function (file, ...rest) { return String(file).endsWith('v9-stage-connections.js') ? source : patched.call(fs, file, ...rest); };
 let en, zh;
 try { en = connectionScenario('en'); zh = connectionScenario('zh'); } finally { fs.readFileSync = patched; }
 const ren = await pressConnect(en);
 assert.equal(ren.gated, true, 'one English text missing -> the card is gated');
 assert.equal(ren.posts, 0, 'en: click, Enter and submit send nothing');
 assert.ok(!/[一-鿿]/.test(ren.note), 'en: the reason is not Simplified Chinese');
 const rzh = await pressConnect(zh);
 assert.equal(rzh.gated, false, 'zh is not affected');
 assert.ok(rzh.posts >= 1, 'zh still sends');
});

test('connection card: mutation - a gate that always says ok lets the gated card send (so the test above guards it)', async () => {
 const mutated = TEXT.replace('function v1CardGate(markup) {', "function v1CardGate(markup) {\n return {ok:true, reason:''};");
 assert.notEqual(mutated, TEXT);
 const tw = connectionScenario('tw', {text: mutated});
 const r = await pressConnect(tw);
 assert.ok(r.gated === false && r.posts >= 1, 'with the gate broken a card with missing text still sends: ' + JSON.stringify({gated: r.gated, posts: r.posts}));
});

// ---------- 2. Stage 2 selection component ----------
function selectionHarness({removeEnglishKey = false} = {}) {
 const {harness} = require(SELECTION_TESTS);
 const run = vm.runInNewContext;
 if (removeEnglishKey) vm.runInNewContext = (code, ctx, ...rest) => run.call(vm, String(code).replace('required:"Required"', 'required:""'), ctx, ...rest);
 try { return harness(); } finally { vm.runInNewContext = run; }
}
function gateComponent(lang, pairs, text = TEXT) {
 const windowHandlers = [];
 const context = vm.createContext({apps: [{lang}], console: {warn() {}}, window: {addEventListener: (type, fn) => windowHandlers.push({type, fn})}});
 vm.runInContext(text + '\nthis.__t = {v1GateComponent};', context);
 const inner = {tagName: 'BUTTON', disabled: false, dataset: {}, closest: selector => selector.includes('button[type="submit"]') ? inner : null};
 const host = {dataset: {}, previousElementSibling: null, notes: [],
  shadowRoot: {querySelectorAll: () => [inner]},
  querySelectorAll: () => [],
  insertAdjacentHTML(where, markup) { this.notes.push(markup); }};
 const gate = context.__t.v1GateComponent(host, pairs, 'button[type="submit"]');
 return {gate, host, inner, windowHandlers};
}
async function submitFormal(f, host, windowHandlers) {
 // Events from inside a shadow root arrive at window retargeted to the host; the real origin is first in the path.
 const chain = eventChain(windowHandlers, []);
 const origin = {tagName: 'BUTTON', closest: selector => selector.includes('button[type="submit"]') ? origin : null, dataset: {}};
 const sent = [];
 for (const event of [{type: 'click', target: host, composedPath: () => [origin, host]}, {type: 'keydown', key: 'Enter', target: host, composedPath: () => [origin, host]}, {type: 'submit', target: host, composedPath: () => [origin, host]}]) {
  if (await chain(event)) sent.push(event.type); // not stopped: the component's own handler would run
 }
 return sent;
}

test('selection component: complete en and zh-TW tables leave the card open; a deleted English text gates it and sends nothing', async () => {
 // the real component and its real words table (embedded harness of the plugin tests)
 for (const [component, app] of [['en', 'en'], ['zh-TW', 'tw'], ['zh-CN', 'zh']]) {
  const f = selectionHarness();
  await tick();
  f.handle.setLanguage(component);
  const pairs = f.handle.textPairs();
  assert.ok(pairs.length > 50, 'the component exposes its text pairs');
  const g = gateComponent(app, pairs);
  assert.equal(g.gate.ok, true, component + ': every text is translated, the card is open: ' + (g.gate.missing || []).slice(0, 5));
 }
 // One English text deleted from the component's own table.
 const f = selectionHarness({removeEnglishKey: true});
 await tick();
 f.handle.setLanguage('en');
 const pairs = f.handle.textPairs();
 const g = gateComponent('en', pairs);
 assert.equal(g.gate.ok, false, 'the missing English text gates the card');
 assert.deepEqual([...g.gate.missing], ['required']);
 assert.equal(g.inner.disabled, true, 'the submit buttons are disabled');
 assert.equal(g.host.dataset.v1Gated, '1');
 assert.match(g.host.notes[0], /no version in this language/, 'the reason is written in English');
 const sent = await submitFormal(f, g.host, g.windowHandlers);
 assert.deepEqual(sent, [], 'click, Enter and submit are stopped before the component handler');
 // zh is never affected, even with the English text deleted
 f.handle.setLanguage('zh-CN');
 const gz = gateComponent('zh', f.handle.textPairs());
 assert.equal(gz.gate.ok, true);
 assert.equal(gz.host.dataset.v1Gated, undefined);
 assert.deepEqual(await submitFormal(f, gz.host, gz.windowHandlers), ['click', 'keydown', 'submit'], 'zh events reach the component');
 // The component really writes when it is not gated (so "sends nothing" above is the gate, not an idle form).
 const open = selectionHarness();
 await tick(); open.selectRadio(); open.form();
 await open.els.get('choice').onsubmit({preventDefault() {}, submitter: open.els.get('submit')});
 assert.ok(open.writes.length >= 1, 'an ungated form posts the selection');
});

test('selection component: mutation - a gate that always says ok lets the missing-text card through', async () => {
 const mutated = TEXT.replace("const gate = missing.length ?", "const gate = false ?");
 assert.notEqual(mutated, TEXT);
 const f = selectionHarness({removeEnglishKey: true});
 await tick();
 f.handle.setLanguage('en');
 const g = gateComponent('en', f.handle.textPairs(), mutated);
 assert.equal(g.gate.ok, true, 'the broken gate passes the card');
 assert.deepEqual(await submitFormal(f, g.host, g.windowHandlers), ['click', 'keydown', 'submit'], 'and its events are not stopped');
});
