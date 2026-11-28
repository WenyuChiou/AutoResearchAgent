// Review 1128 fixes, each with a test that fails on the code before the fix:
//  P1-1 the coverage form embedded in the Stage 1 run tab (Traditional text, write mark, own card root)
//  P1-2 the Stage 2 / Stage 3 connection cards that V1 really draws (wikiS2ConnBlock / wikiS3ConnBlock)
//  P1-3 the materials page upload input
//  P2-1 labels stored at load time (a language switch must change them)
//  P2-2 the scope card includes the consent card, so a missing consent text greys the confirm buttons
// A fake DOM stands in for the page: card = nearest [data-v1-card] or section, as in v1GateCards. No network.
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const read = name => fs.readFileSync(path.join(__dirname, name), 'utf8');
const TEXT = read('wiki-v1-text.js');
const MARK = '⁠';
const esc = value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
const tick = () => new Promise(resolve => setImmediate(resolve));

// ---------- page stand-in ----------
function makeContext(lang, extra = {}) {
 const windowHandlers = [];
 const app = {page: 'workspace', stage: 1, lang, el: {querySelector: () => null, contains: () => true}};
 const context = vm.createContext({apps: [app], console: {warn() {}}, window: {addEventListener: (type, fn) => windowHandlers.push({type, fn})}, esc, ...extra});
 return {context, app, windowHandlers};
}
// Gate the write controls found in `html` as the page does, then press every event type on each; returns what happened.
async function press(context, windowHandlers, html, events = ['click', 'keydown', 'submit', 'change']) {
 const root = /^\s*<[^>]*data-v1-card/.test(html), section = /^\s*<section/.test(html);
 const card = {dataset: {}, outerHTML: html, notes: [],
  querySelector(selector) { return selector === '[data-v1-gate-note]' && this.notes.length ? this.notes[0] : null; },
  insertAdjacentHTML(where, markup) { this.outerHTML += markup; this.notes.push(markup); }};
 const tags = [...html.matchAll(/<(button|input)\b[^>]*\bdata-v1-write\b[^>]*>/g)];
 const controls = tags.map(m => ({disabled: false, dataset: {}, tagName: m[1].toUpperCase(),
  closest(selector) {
   if (selector === '[data-v1-card]') return root ? card : null;
   if (selector === 'section') return section ? card : null;
   if (selector === '[data-v1-gated]') return card.dataset.v1Gated === '1' ? card : null;
   if (selector.startsWith('[data-v1-write]')) return this;
   return null;
  }}));
 vm.runInContext('v1GateCards', context)({querySelectorAll: selector => selector === '[data-v1-write]' ? controls : []});
 let reached = 0;
 for (const control of controls) {
  control.disabled = false; // a later re-render of the control must not matter
  for (const type of events) {
   let stopped = false;
   const event = {type, key: 'Enter', target: control, preventDefault() {}, stopImmediatePropagation() { stopped = true; }};
   for (const h of windowHandlers.filter(h => h.type === type)) { h.fn(event); if (stopped) break; }
   if (!stopped) reached += 1;
  }
 }
 return {controls: controls.length, gated: card.dataset.v1Gated === '1', disabled: controls.filter(c => c.disabled).length, reached, note: card.notes[0] || ''};
}
const dropText = (context, key, lang) => vm.runInContext(`v1Text[${JSON.stringify(key)}].${lang} = ''`, context);

// ---------- P1-1 coverage form ----------
function coverageHtml(lang, operation, {dropTw = false, dropEn = false} = {}) {
 let src = read('renderer/src/real-runtime.js');
 if (dropTw) src = src.replace("'儲存覆蓋審閱'", "''");
 if (dropEn) src = src.replace("'Save coverage review'", "''");
 const button = src.slice(src.indexOf('function realButton('), src.indexOf('\n', src.indexOf('function realButton(')));
 const coverage = src.slice(src.indexOf('function realCoverage(){'), src.indexOf('function realText('));
 const ops = read('wiki-stage1-ops.js');
 const form = ops.slice(ops.indexOf('function wsCoverageForm() {'), ops.indexOf('\n}\n', ops.indexOf('function wsCoverageForm() {')) + 3);
 const {context, app, windowHandlers} = makeContext(lang, {
  liveDisabled: () => '',
  rt: {coverageIndex: 0, overview: {stage1: {ledger: {state_sha256: 's'}, coverage_actions: {ledger_state_sha256: 's', blockers: [], held: false,
   offers: [{operation, offer_ref: 'o', offer_sha256: 'h', document: {title: 'Paper', claims: [], clusters: [], round_number: 1, query: 'q', result_count: 3}}]}}}}});
 const runtime = read('renderer/src/runtime.js');
 const rlLine = runtime.slice(runtime.indexOf('const rl = '), runtime.indexOf('\n', runtime.indexOf('const rl = ')));
 vm.runInContext('const li = a => a.lang === "en" ? 1 : a.lang === "tw" ? 2 : 0; const translated = (a, arr) => arr[li(a)]; const rx = v => esc(v == null ? "Unknown" : String(v));\n' + rlLine, context);
 vm.runInContext(TEXT, context);
 vm.runInContext(button + '\n' + coverage + '\n' + form, context);
 return {html: vm.runInContext('wsCoverageForm()', context), context, windowHandlers, app};
}
test('P1-1 coverage form: write mark, own card root, and complete Traditional and English text', async () => {
 for (const operation of ['review-work', 'receipt', 'human-action', 'open-round']) {
  for (const lang of ['zh', 'en', 'tw']) {
   const {html, context, windowHandlers} = coverageHtml(lang, operation);
   assert.match(html, /data-v1-card/, `${operation}/${lang}: the form is its own card`);
   assert.match(html, /data-v1-write[^>]*data-v7-workflow="coverage-save"/, `${operation}/${lang}: the save button is a write button`);
   assert.ok(!html.includes(MARK), `${operation}/${lang}: no text of the form fell back to Simplified`);
   const r = await press(context, windowHandlers, html);
   assert.equal(r.gated, false, `${operation}/${lang}: complete form is open`);
  }
 }
});
test('P1-1 coverage form: a missing translation greys the save button and nothing is sent; zh is not affected', async () => {
 for (const [lang, drop] of [['tw', {dropTw: true}], ['en', {dropEn: true}]]) {
  const {html, context, windowHandlers} = coverageHtml(lang, 'human-action', drop);
  const r = await press(context, windowHandlers, html);
  assert.ok(r.controls >= 1, 'there is a write button to gate');
  assert.equal(r.gated, true, `${lang}: gated`);
  assert.equal(r.reached, 0, `${lang}: click, Enter, submit and change send nothing`);
 }
 const zh = coverageHtml('zh', 'human-action', {dropTw: true, dropEn: true});
 const rz = await press(zh.context, zh.windowHandlers, zh.html);
 assert.equal(rz.gated, false, 'zh is not affected');
 assert.ok(rz.reached > 0);
});

// ---------- P1-2 Stage 2 / Stage 3 connection cards ----------
function stage2Context(lang, model, over = {}) {
 const {context, app, windowHandlers} = makeContext(lang, {
  rt: {ref: 'project-a', overview: {project: {project_ref: 'project-a'}}, list: [], loading: false, busy: false, pending: null, controlHeld: false},
  canonicalReadonly: () => false, wikiStage2State: {result: {status: 'ready'}}, v9ConnectionModel: () => model, v9ConnectionConnected: () => false,
  v9LegacyConnection: () => false, v9AllowsCandidateRequest: () => true, liveRequest() { throw Error('no request while rendering'); },
  stage2: () => 'earlier', v7AfterRender: () => {}, livePaint: () => {}, canonicalTop: () => '', liveHeader: () => '', canonicalHeading: () => '', canonicalStage2Validate: () => ({ok: false}),
  wikiHarnessRecord: () => '', wikiStage2CurrentSelection: () => true, v93ChoiceIdentity: () => null, CSS: {escape: v => String(v)}, p9: {shown: null}, n2: {}, m9: {busy: false},
  sessionStorage: {getItem: () => null, setItem() {}, removeItem() {}}, document: {addEventListener() {}}, ...over});
 app.stage = 2;
 vm.runInContext(TEXT, context);
 vm.runInContext(read('wiki-stage2.js'), context);
 return {context, app, windowHandlers};
}
const model2 = over => ({phase: 'ready', stage: 'stage2-controller', basis: {}, view: {}, row: null, code: '', unknown: false, action: 'publish', token: 'tok', reading: false, writing: false, canWrite: true, noLocks: false, connected: false, ...over});
test('P1-2 Stage 2 connection card: every write button is marked, the card is gated when a text is missing, zh unaffected', async () => {
 for (const action of ['connect', 'publish', 'activate']) {
  for (const lang of ['en', 'tw']) {
   const {context, app, windowHandlers} = stage2Context(lang, model2({action}));
   const html = vm.runInContext('wikiS2ConnBlock', context)(app);
   assert.match(html, new RegExp(`data-v1-write[^>]*data-v9-connection="${action}"`), `${action}: marked`);
   const open = await press(context, windowHandlers, html);
   assert.equal(open.gated, false, `${action}/${lang}: complete card is open`);
   dropText(context, '本课题的 Stage 2', lang);
   const html2 = vm.runInContext('wikiS2ConnBlock', context)(app);
   const r = await press(context, windowHandlers, html2);
   assert.equal(r.gated, true, `${action}/${lang}: a missing text gates the card`);
   assert.equal(r.reached, 0, `${action}/${lang}: nothing is sent`);
  }
 }
 // the candidate request line inside the same card
 const {context, app, windowHandlers} = stage2Context('en', model2({action: null, connected: true}));
 let html = vm.runInContext('wikiS2ConnBlock', context)(app);
 assert.match(html, /data-v1-write[^>]*data-wiki-stage2-action="request"/, 'request candidates is marked');
 dropText(context, '本课题的 Stage 2', 'en');
 html = vm.runInContext('wikiS2ConnBlock', context)(app);
 const rq = await press(context, windowHandlers, html);
 assert.ok(rq.gated && rq.reached === 0, 'the request button is gated too');
 const zh = stage2Context('zh', model2({action: 'publish'}));
 dropText(zh.context, '本课题的 Stage 2', 'en');
 const rz = await press(zh.context, zh.windowHandlers, vm.runInContext('wikiS2ConnBlock', zh.context)(zh.app));
 assert.equal(rz.gated, false, 'zh is not affected');
 assert.ok(rz.reached > 0);
});
function stage3Context(lang, model) {
 const s2 = stage2Context(lang, model);
 const src = read('wiki-stage3.js');
 const part = src.slice(src.indexOf('function wikiS3ConnectionLine(m) {'), src.indexOf('function wikiS3SavedView'));
 vm.runInContext('const wikiS3Escape = esc; var v93Identity = () => null; var v93Matches = () => false; var wikiS3ReadLine;\n' + part, s2.context);
 s2.app.stage = 3;
 return s2;
}
test('P1-2 Stage 3 connection card: connect and reconnect are marked and gated', async () => {
 for (const [action, code] of [['connect', ''], ['reconnect', 'stage3-planning-resource-unavailable']]) {
  for (const lang of ['en', 'tw']) {
   const {context, app, windowHandlers} = stage3Context(lang, model2({stage: 'stage3-planning', action, code}));
   const html = vm.runInContext('wikiS3ConnBlock', context)(app);
   assert.match(html, new RegExp(`data-v1-write[^>]*data-v9-connection="${action}"`), `${action}: marked`);
   assert.equal((await press(context, windowHandlers, html)).gated, false, `${action}/${lang}: complete card is open`);
   dropText(context, '本课题的 Stage 3', lang);
   const r = await press(context, windowHandlers, vm.runInContext('wikiS3ConnBlock', context)(app));
   assert.ok(r.gated && r.reached === 0, `${action}/${lang}: gated and nothing is sent`);
  }
 }
});

// ---------- P1-3 materials upload input ----------
function materialsContext(lang) {
 const {context, app, windowHandlers} = makeContext(lang, {
  v1On: () => true, m9Panel: () => 'old', n9Message: v => v || '', document: {addEventListener() {}},
  wsTag: (k, l) => `<tag>${l}</tag>`, wsBtn: (l, a, r) => `<button data-v1-write ${a}>${l}</button>${r || ''}`, wsMaterialsDownloads: () => '',
  m9: {catalog: {materials: [], operations: [], drafts: []}, busy: false, error: '', status: '', target: {}, notes: {}, sourcePath: '', importPath: '', packetHash: ''},
  m9Current: () => [], m9Draft: () => null});
 app.stage = 1;
 vm.runInContext(TEXT, context);
 const block = read('wiki-stage1-materials.js');
 vm.runInContext(block.slice(block.indexOf('// ---------- Wiki V1 materials panel')), context);
 return {context, app, windowHandlers};
}
test('P1-3 materials page: the upload input is a write control; a missing text greys it and its change event is stopped', async () => {
 for (const lang of ['en', 'tw']) {
  const {context, app, windowHandlers} = materialsContext(lang);
  const html = vm.runInContext('m9Panel', context)(app);
  assert.match(html, /<input type="file"[^>]*data-v1-write/, 'the upload input is marked');
  const card = h => /<section class="ws-m9-card">[\s\S]*?<\/section>/.exec(h)[0]; // the nearest section of the input
  assert.equal((await press(context, windowHandlers, card(html))).gated, false, `${lang}: complete panel is open`);
  dropText(context, '选择阶段材料', lang);
  const r = await press(context, windowHandlers, card(vm.runInContext('m9Panel', context)(app)));
  assert.ok(r.gated && r.reached === 0, `${lang}: gated, and click and change send nothing`);
 }
});

// ---------- P2-1 labels stored at load time ----------
test('P2-1 labels assigned at load time follow the language after a switch', () => {
 const stage1 = read('wiki-stage1.js'), ops = read('wiki-stage1-ops.js'), materials = read('wiki-stage1-materials.js');
 const head = stage1.slice(0, stage1.indexOf('function wikiS1Active'));
 const statements = [
  /^wikiS1Tabs\.ops = .*;$/m.exec(ops)[0], /^Object\.assign\(wikiS1Relations, .*\);$/m.exec(ops)[0],
  /^Object\.assign\(wikiS1Checks, .*\);$/m.exec(ops)[0], /^wikiS1Tabs\.materials = .*;$/m.exec(materials)[0]];
 for (const loadLang of ['tw', 'en', 'zh']) {
  const {context, app} = makeContext(loadLang);
  vm.runInContext(TEXT, context);
  vm.runInContext(head + '\n' + statements.join('\n'), context);
  for (const lang of ['zh', 'en', 'tw', 'tw', 'en', 'zh']) {
   app.lang = lang;
   const read1 = vm.runInContext('[wikiS1Tabs.ops, wikiS1Tabs.materials, wikiS1Relations.contradicts, wikiS1Relations.unverifiable, wikiS1Checks.unclear, wikiS1Checks.unverifiable, wikiS1Checks.contradicts]', context);
   const expected = vm.runInContext(`['运行与操作', '材料', '相互矛盾', '无法核实', '? 不清楚', '⊘ 无法核实', '✕ 相互矛盾'].map(k => v1t(k))`, context);
   assert.deepEqual([...read1], [...expected], `loaded as ${loadLang}, read as ${lang}`);
   assert.ok(![...read1].some(text => String(text).includes(MARK)), `loaded as ${loadLang}, read as ${lang}: no fallback marker`);
  }
 }
});

// ---------- P2-2 scope card includes the consent card ----------
test('P2-2 scope card: the confirm buttons are gated when the consent card text is missing', async () => {
 const sha = c => c.repeat(64);
 const project = {project_ref: 'project-a', input_version: 1, revision: 2, brief_sha256: sha('b'), brief: {original_description: 'Topic'},
  intake_report: {necessary_clarification_complete: false, scope: {geography: {status: 'pending', value: null}, priority_reading_target: {status: 'x', value: null}}, formal_final_count: {target: null}}, settings: null};
 const rt = {ref: 'project-a', overview: {project, models: {calls_reserved: 0, jobs: []}, stage1: {progress: {phases: []}, queries: [], delivery: {offers: [], canonical_package: null}, reading_registration: {status: 'unconnected', missing_works: []}}},
  loading: false, busy: false, pending: null, controlHeld: false, error: '', scopeDraft: null, wsProg: {key: null, state: 'absent'}};
 const {context, app, windowHandlers} = makeContext('en', {rt, TextEncoder, JSON, Set, Math, canonicalReadonly: () => false, wikiHomeArchiveBound: () => false,
  projectPath: (ref, tail) => `/api/projects/${ref}/${tail}`, liveScopeValues: () => ({geography: '', geographyValue: '', target: '30', priority: '20', note: ''}),
  realModelOffers: () => [], realPlanningState: () => ({allowed: true, current: true, blocking: 0}), realPlanningFailure: () => '', realPlanImportReady: () => false,
  realPlanDraftCurrent: () => false, realQueryOwnerOffer: () => null, realCurrent: () => true, realCoverage: () => '', wikiS1Active: () => true, wikiS1Tabs: {},
  wikiS1Results: () => '', wikiS1State: () => ({}), wikiS1Index: () => null});
 vm.runInContext(TEXT, context);
 const ops = read('wiki-stage1-ops.js');
 vm.runInContext(ops.slice(0, ops.indexOf('// ---------- hooks into')), context);
 rt.wsProg.key = vm.runInContext('wsProgKey()', context);
 const page = vm.runInContext('wsScopePage', context)({wikiS1: {}});
 assert.match(page, /^\s*<section[^>]*data-v1-card[^>]*data-wiki-ops="scope"/, 'the scope page is one card');
 // The grant module inserts the consent card in front of the confirm card (string insertion in wsgPrevScopePage).
 const consent = `<section class="ws-grant-consent"><p>${vm.runInContext('v1t', context)('这个课题允许联网吗')}</p></section>`;
 const marker = '<section class="decide ws-decide"';
 const at = page.indexOf(marker);
 const withConsent = page.slice(0, at) + consent + page.slice(at);
 assert.equal((await press(context, windowHandlers, withConsent)).gated, false, 'complete consent text keeps the confirm buttons open');
 dropText(context, '这个课题允许联网吗', 'en');
 const consentMissing = `<section class="ws-grant-consent"><p>${vm.runInContext('v1t', context)('这个课题允许联网吗')}</p></section>`;
 const r = await press(context, windowHandlers, page.slice(0, at) + consentMissing + page.slice(at));
 assert.ok(r.controls >= 1, 'the scope page has write buttons');
 assert.equal(r.gated, true, 'a missing consent text gates the confirm buttons');
 assert.equal(r.reached, 0);
});
