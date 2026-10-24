/* Actual StageSlots source and HTML; authored shared-contract data, no runtime. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {webcrypto} = require('node:crypto');
const fixture = JSON.parse(fs.readFileSync(0, 'utf8'));
const web = path.resolve(__dirname, '../../cli/research_workspace_native/web');

class Element {
  constructor(tag) {
    this.tagName = tag.toUpperCase(); this.children = []; this.attributes = {};
    this.dataset = {}; this.style = {}; this.hidden = false; this.disabled = false;
    this.text = ''; this.listeners = {};
    this.classList = {
      add: (...names) => { this.className = [...new Set([...(this.className || '').split(/\s+/), ...names])].join(' '); },
      remove: (...names) => { this.className = (this.className || '').split(/\s+/).filter(name => !names.includes(name)).join(' '); },
      toggle: (name, force) => {
        const present = (this.className || '').split(/\s+/).includes(name);
        const next = force === undefined ? !present : force;
        if (next) this.classList.add(name); else this.classList.remove(name);
        return next;
      },
      contains: name => (this.className || '').split(/\s+/).includes(name)
    };
  }
  append(...nodes) { for (const node of nodes) { node.parentElement = this; this.children.push(node); } }
  appendChild(node) { this.append(node); return node; }
  replaceChildren(...nodes) { this.children.forEach(node => { node.parentElement = null; }); this.children = []; this.text = ''; this.append(...nodes); }
  remove() { if (this.parentElement) this.parentElement.children = this.parentElement.children.filter(node => node !== this); this.parentElement = null; }
  get textContent() { return this.text + this.children.map(node => node.textContent).join('\n'); }
  set textContent(value) { this.replaceChildren(); this.text = String(value); }
  set innerHTML(_) { throw new Error('StageSlots must use textContent, never HTML'); }
  setAttribute(name, value) {
    this.attributes[name] = String(value);
    if (name.startsWith('data-')) this.dataset[name.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = String(value);
    else if (name === 'class') this.className = String(value);
    else if (name === 'hidden' || name === 'disabled') this[name] = true;
    else this[name] = String(value);
  }
  getAttribute(name) { return this.attributes[name] ?? null; }
  removeAttribute(name) { delete this.attributes[name]; if (name === 'hidden' || name === 'disabled') this[name] = false; }
  addEventListener(name, callback) { (this.listeners[name] ||= []).push(callback); }
  click() { if (!this.disabled) { const event = {target: this, preventDefault() {}}; this.onclick?.(event); for (const fn of this.listeners.click || []) fn(event); } }
  reset() {}
  focus() {}
  scrollIntoView(options) { (this.scrolls ||= []).push(JSON.parse(JSON.stringify(options))); }
  querySelectorAll(selector) { return descendants(this).filter(node => matches(node, selector)); }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
}
const descendants = root => root.children.flatMap(node => [node, ...descendants(node)]);
function matches(node, selector) {
  if (selector.includes(',')) return selector.split(',').some(part => matches(node, part.trim()));
  if (selector.startsWith('#')) return node.id === selector.slice(1);
  if (selector.startsWith('.')) return node.classList.contains(selector.slice(1));
  const attr = selector.match(/^\[([^=\]]+)(?:=["']?([^"'\]]+)["']?)?\]$/);
  if (attr) return node.getAttribute(attr[1]) !== null && (attr[2] === undefined || node.getAttribute(attr[1]) === attr[2]);
  return node.tagName.toLowerCase() === selector;
}
function htmlTree(html) {
  const root = new Element('document'), stack = [root];
  const voids = new Set(['area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr']);
  for (const token of html.match(/<!--[\s\S]*?-->|<![^>]*>|<[^>]*>|[^<]+/g) || []) {
    if (/^<!/.test(token)) continue;
    if (/^<\//.test(token)) { stack.pop(); continue; }
    if (token.startsWith('<')) {
      const tag = token.match(/^<([\w-]+)/)[1].toLowerCase(), node = new Element(tag);
      for (const match of token.slice(tag.length + 1, -1).matchAll(/([^\s=/>]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/g)) node.setAttribute(match[1], match[2] ?? match[3] ?? match[4] ?? '');
      stack.at(-1).append(node); if (!voids.has(tag) && !token.endsWith('/>')) stack.push(node);
    } else stack.at(-1).text += token;
  }
  return root;
}
const root = htmlTree(fs.readFileSync(path.join(web, 'projects.html'), 'utf8'));
const events = [], sideEffects = [];
const forbidden = name => (..._) => { sideEffects.push(name); throw new Error(`Unexpected ${name} in presentation`); };
const window = {
  RESEARCH_PROJECTS: {credential: 'authored-private-credential'},
  dispatchEvent(event) { events.push(event); }, addEventListener() {},
  fetch: forbidden('fetch'), open: forbidden('window.open'),
  localStorage: {getItem: forbidden('key-read'), setItem: forbidden('key-write')},
  crypto: {randomUUID: forbidden('action-key')},
  navigator: {sendBeacon: forbidden('beacon')}
};
const document = {
  getElementById: id => descendants(root).find(node => node.id === id) || null,
  createElement: tag => new Element(tag),
  querySelectorAll: selector => root.querySelectorAll(selector),
  querySelector: selector => root.querySelector(selector),
  addEventListener() {}, dispatchEvent: event => window.dispatchEvent(event)
};
vm.runInNewContext(fs.readFileSync(path.join(web, 'projects-stages.js'), 'utf8'), {
  document, window, CustomEvent: class {constructor(type, options = {}) {this.type = type; this.detail = options.detail;}},
  fetch: forbidden('fetch'), XMLHttpRequest: forbidden('XHR'), WebSocket: forbidden('WebSocket'),
  localStorage: window.localStorage, crypto: window.crypto, navigator: window.navigator,
  console, setTimeout: forbidden('timer'), clearTimeout() {}
});
const stages = window.ResearchProjectStages;
assert(stages && Object.isFrozen(stages), 'frozen presentation API is available');
const get = id => { const node = document.getElementById(id); assert(node, `missing ${id}`); return node; };
const slots = Array.from({length: 6}, (_, i) => get(`project-stage-${i + 1}`));
const identity = fixture.contract.identity;
const clone = value => JSON.parse(JSON.stringify(value));
const render = (contract = fixture.contract, language = 'en', project = fixture.project, loading = false) => stages.render({project, contract, language, loading});
const statusText = () => slots.map((_, i) => get(`project-stage-${i + 1}-status`).textContent).join('\n');
function visible(stage) {
  for (let n = 1; n <= 6; n++) assert.equal(get(`project-stage-${n}`).hidden, n !== stage, `only Stage ${stage} is visible`);
  assert.equal(stages.activeStage(), stage);
}

const savedCanary = 'saved-source-canary';
fixture.contract.stages['1'].status = 'partial';
fixture.contract.stages['1'].attempts = [{status: savedCanary, failure: '<img src=x onerror=dispatch()> literal source'}];
fixture.contract.stages['1'].expected_outputs.push('<script>literal expected output</script>');
fixture.contract.stages['1'].metrics.actual_search_calls = {value: 0, unit: 'attempts', status: 'recorded', evidence: []};
fixture.contract.stages['1'].metrics.monetary_cost = {value: null, unit: 'authored-unknown-currency', status: 'unknown', evidence: []};
const before = JSON.stringify(fixture);
render(); visible(1);
assert(statusText().includes(savedCanary), 'current saved attempt is shown');
assert(statusText().includes('<img src=x onerror=dispatch()> literal source'), 'source markup stays literal');
assert(slots[0].textContent.includes('<script>literal expected output</script>'), 'expected output markup stays literal');
assert(statusText().includes('Unknown'), 'missing metric remains Unknown');
assert.match(get('project-stage-1-status').textContent, /partial/);
assert.match(get('project-stage-1-status').textContent, /"score": null/, 'unassessed scientific score remains null');
assert(statusText().includes('authored-unknown-currency'), 'original measurement unit remains visible');
assert.match(statusText(), /monetary_cost:\s*Unknown\s*·\s*authored-unknown-currency\s*·\s*unknown/);
assert(statusText().includes('recorded'), 'recorded zero remains a distinct observation');
assert.match(statusText(), /actual_search_calls[\s\S]*?0[\s\S]*?recorded/);
assert.equal(JSON.stringify(fixture), before, 'render does not alter source contract or input');

for (let n = 1; n <= 6; n++) {
  const count = events.length;
  get(`project-stage-nav-${n}`).click(); visible(n);
  assert.equal(events.length, count + 1, 'navigation emits one presentation event');
  assert.equal(events.at(-1).type, 'research-project-stage');
  assert.deepEqual(JSON.parse(JSON.stringify(events.at(-1).detail)), {
    stage: n, ...Object.fromEntries(['project_ref', 'input_version', 'revision', 'brief_sha256'].map(key => [key, identity[key]]))
  });
}
for (const invalid of [0, 7, -1, 1.5, NaN, Infinity, '2', '02', '2x', null, undefined, true, {}, [], Number.MAX_SAFE_INTEGER + 1]) {
  const count = events.length; stages.showStage(invalid); visible(6);
  assert.equal(events.length, count, 'invalid stage cannot switch or emit');
}
const preserved = new Element('input'); preserved.value = 'unsaved researcher text';
get('project-stage-2-operations').append(preserved);
const result = new Element('iframe'); get('project-stage-1-results').append(result);
for (const language of ['zh-Hans', 'zh-Hant', 'en']) {
  render(fixture.contract, language); visible(6);
  assert.equal(get('project-stage-2-operations').children.at(-1), preserved, 'same binding retains operation nodes');
  assert.equal(preserved.value, 'unsaved researcher text');
  assert.equal(get('project-stage-1-results').children.at(-1), result, 'same binding retains mounted result');
  slots.forEach((slot, i) => assert.equal(get(`project-stage-${i + 1}`), slot, 'stable stage nodes survive render'));
}
const translations = [
  ['en', /status/i, /Operations/, /Delivered results/, /Expected outputs/, /unconnected/i],
  ['zh-Hans', /状态/, /操作/, /结果/, /预期输出/, /未接通/],
  ['zh-Hant', /狀態/, /操作/, /結果/, /預期輸出/, /未接通/]
];
for (const [language, ...labels] of translations) {
  render(fixture.contract, language);
  for (const label of labels) assert.match(slots[2].textContent, label, `${language} Stage 3 labels`);
  for (let n = 3; n <= 6; n++) {
    assert.match(get(`project-stage-${n}-status`).textContent, /planned|已规划|已規劃/i);
    const button = get(`project-stage-${n}-unconnected`);
    assert.equal(button.disabled, true); assert.equal(button.onclick == null, true);
    assert.equal((button.listeners.click || []).length, 0);
    const count = events.length; button.click(); assert.equal(events.length, count);
  }
  assert.match(get('project-stage-2-result-state').textContent, /not generated|尚未生成|尚未產生|尚未生成/i);
}

const invalidContracts = [];
const changed = (name, fn) => { const value = clone(fixture.contract); fn(value); invalidContracts.push([name, value]); };
changed('wrong kind', value => { value.kind = 'OtherView'; });
changed('wrong version', value => { value.schema_version = '1.1.0'; });
for (const [key, value] of [['project_ref', 'foreign-project'], ['input_version', 2], ['revision', 8], ['brief_sha256', 'b'.repeat(64)]]) {
  changed(`top ${key}`, contract => { contract.identity[key] = value; });
  for (const n of [1, 2, 6]) changed(`stage ${n} ${key}`, contract => { contract.stages[n].input[key] = value; });
}
changed('invalid identity number', value => { value.identity.input_version = '1'; });
changed('missing stage', value => { delete value.stages['4']; });
changed('wrong stage marker', value => { value.stages['2'].stage = 2; });
for (const key of ['expected_outputs', 'artifacts', 'attempts', 'pending_questions', 'approvals']) changed(`malformed ${key}`, value => { value.stages['1'][key] = null; });
for (const key of ['connected', 'execution_authorized', 'accepted']) changed(`malformed ${key}`, value => { value.stages['2'][key] = 'false'; });
changed('malformed metrics', value => { value.stages['1'].metrics = []; });
changed('future complete', value => { value.stages['3'].status = 'completed'; });
changed('future connected', value => { value.stages['4'].connected = true; });
changed('future authorized', value => { value.stages['5'].execution_authorized = true; });
changed('future accepted', value => { value.stages['6'].accepted = true; });
invalidContracts.push(['null contract', null]);
for (const [name, contract] of invalidContracts) {
  render(); render(contract);
  assert.equal(statusText().includes(savedCanary), false, `${name} must refuse saved observations`);
  assert.equal(slots[0].textContent.includes('<script>literal expected output</script>'), false, `${name} must refuse saved expected outputs`);
  stages.showStage(2);
  const detail = events.at(-1).detail;
  assert.deepEqual(JSON.parse(JSON.stringify(detail)), {
    stage: 2, ...Object.fromEntries(['project_ref', 'input_version', 'revision', 'brief_sha256'].map(key => [key, fixture.project[key]]))
  }, `${name} navigation retains only the current project identity`);
}
for (const [name, project] of [['foreign project', {...fixture.project, project_ref: 'foreign'}], ['no project', null]]) {
  render(); render(fixture.contract, 'en', project);
  assert.equal(statusText().includes(savedCanary), false, `${name} must refuse saved observations`);
}
for (const [key, value] of [['project_ref', '../foreign'], ['revision', -1], ['input_version', ' padded '], ['brief_sha256', 'not-a-hash']]) {
  render(fixture.contract, 'en', {...fixture.project, [key]: value});
  assert.equal(statusText().includes(savedCanary), false, `malformed project ${key} refuses observations`);
  stages.showStage(3);
  assert.deepEqual(JSON.parse(JSON.stringify(events.at(-1).detail)), {stage: 3}, `malformed project ${key} emits no identity`);
}
render(); render(fixture.contract, 'en', fixture.project, true);
assert.equal(statusText().includes(savedCanary), false, 'loading clears old saved observations');
stages.clear({language: 'en', loading: false});
assert.equal(statusText().includes(savedCanary), false, 'clear retires current saved observations');
assert.equal(sideEffects.length, 0, 'all paths remain presentation only');
assert.equal(JSON.stringify(events).includes('authored-private-credential'), false);
assert.equal(JSON.stringify(events).includes('key'), false, 'presentation events have no action identity');

// Load the complete existing broker, using its public portal and real button
// handlers. Only its transport replies and DOM are authored; no function is
// extracted, replaced or copied into this test.
async function deliveryNavigationGuards() {
  const flush = () => new Promise(resolve => setImmediate(resolve));
  async function until(predicate, diagnostic = () => '') {
    const deadline = Date.now() + 3000;
    while (!predicate() && Date.now() < deadline) await flush();
    assert(predicate(), `mock broker reached its awaited boundary: ${diagnostic()}`);
  }
  async function scenario(options = {}) {
    const tree = htmlTree(fs.readFileSync(path.join(web, 'projects.html'), 'utf8'));
    const find = id => descendants(tree).find(node => node.id === id);
    const project = {...clone(fixture.project), brief: {original_description: 'Authored delivery topic', needs: []}};
    const freshProject = {...clone(project), ...(options.freshProject || {})};
    const artifact = {artifact_ref: 'authored-package', manifest_sha256: 'c'.repeat(64), status: 'saved-evidence-validated', binding: {
      project_id: project.project_id, input_version: project.input_version, brief_sha256: project.brief_sha256
    }, ...(options.artifact || {})};
    const receipt = {status: 'saved', delivery_status: 'saved-evidence-validated', artifact_ref: artifact.artifact_ref, manifest_sha256: artifact.manifest_sha256, ...(options.receipt || {})};
    const posts = [], requests = [], navigation = [], listeners = {};
    let overviewCount = 0, finishPost, finishReadback;
    const sample = (current, delivered) => ({project: current, stage1: {
      stage1_status: 'partial', ledger: {state_sha256: 'd'.repeat(64), gate: {outcome: 'continue'}, next_allowed_action: 'review'},
      delivery: {canonical_package: delivered ? artifact : null, offers: [{status: 'ready-for-saved-evidence-delivery', offer_ref: 'authored-offer', offer_sha256: 'e'.repeat(64)}]}
    }, stage2: null, models: null, model_offers: []});
    const doc = {
      getElementById: find, createElement: tag => new Element(tag), querySelectorAll: selector => tree.querySelectorAll(selector),
      documentElement: tree.querySelector('html'), body: tree.querySelector('body'),
      addEventListener(type, fn) { (listeners[type] ||= []).push(fn); },
      dispatchEvent(event) { if (event.type === 'research-project-navigate') navigation.push(JSON.parse(JSON.stringify(event.detail))); for (const fn of listeners[event.type] || []) fn(event); }
    };
    if (options.embedded) doc.body.classList.add('project-embedded');
    const brokerWindow = {RESEARCH_PROJECTS: {credential: 'authored-private-credential', models: false, views: []}, dispatchEvent() {}, addEventListener() {}};
    const storage = new Map();
    const fetchMock = async (url, init) => {
      requests.push({url, method: init.method});
      let value;
      if (init.method === 'POST') {
        assert.equal(url, `/api/projects/${project.project_ref}/stage1/${options.operation || 'deliver'}`);
        posts.push(JSON.parse(init.body)); value = await new Promise(resolve => { finishPost = () => resolve(receipt); });
      } else if (url === '/api/projects') value = {projects: []};
      else if (url.endsWith('/overview')) {
        overviewCount++;
        if (overviewCount > 1 && options.holdReadback) value = await new Promise(resolve => {finishReadback = () => resolve(sample(freshProject, true));});
        else value = sample(overviewCount > 1 ? freshProject : project, overviewCount > 1);
      } else if (url.endsWith('/contract')) {
        value = clone(fixture.contract); const currentProject = overviewCount > 1 ? freshProject : project;
        value.identity = {...value.identity, ...currentProject};
        for (const stage of Object.values(value.stages)) stage.input = {...stage.input, ...currentProject};
      } else if (/\/(history|models\/actions\/0|stage2\/actions)$/.test(url)) value = {actions: [], next_offset: null};
      else if (url.endsWith('/models/native')) value = {};
      else throw new Error(`Unexpected mocked route: ${url}`);
      return {ok: true, json: async () => value};
    };
    const sandbox = {
      document: doc, window: brokerWindow, fetch: fetchMock, TextEncoder,
      sessionStorage: {getItem: key => storage.get(key) || null, setItem: (key, value) => storage.set(key, value)},
      crypto: {subtle: webcrypto.subtle, randomUUID: () => 'authored-ui-key'},
      Event: class {constructor(type) {this.type = type;}},
      CustomEvent: class {constructor(type, init = {}) {this.type = type; this.detail = init.detail;}}, console
    };
    vm.createContext(sandbox);
    vm.runInContext(fs.readFileSync(path.join(web, 'projects-stages.js'), 'utf8'), sandbox);
    vm.runInContext(fs.readFileSync(path.join(web, 'projects.js'), 'utf8'), sandbox);
    await flush();
    assert.equal(await brokerWindow.ResearchProjectPortal.selectProject(project.project_ref), true, find('notice').textContent);
    brokerWindow.ResearchProjectStages.showStage(options.activeStage || 1);
    const button = find(options.operation === 'export' ? 'ledger-export' : 'ledger-deliver');
    assert.equal(button.disabled, false, find('notice').textContent);
    const saving = button.onclick({preventDefault() {}});
    await until(() => finishPost, () => find('notice').textContent + ' ' + JSON.stringify(requests));
    if (options.beforePostReply) options.beforePostReply({project, find, brokerWindow});
    finishPost();
    if (options.holdReadback) { await until(() => finishReadback); find('new-project').onclick(); finishReadback(); }
    await saving;
    assert.equal(posts.length, 1, 'explicit button produces exactly one authored POST');
    assert.equal(requests.filter(row => row.method === 'POST').length, 1, 'readback/navigation cannot send another POST');
    assert.equal(posts[0].confirmed, true);
    assert.equal(posts[0].input_version, fixture.project.input_version);
    assert.equal(posts[0].brief_sha256, fixture.project.brief_sha256);
    const scrolls = find('project-stage-1-results').scrolls || [];
    return {navigation, scrolls, notice: find('notice').textContent};
  }
  const successful = await scenario();
  assert.deepEqual(successful.scrolls, [{block: 'start', behavior: 'smooth'}], 'fresh explicit delivery scrolls to lower Stage 1 result');
  assert.deepEqual(successful.navigation, []);
  const embedded = await scenario({embedded: true});
  assert.deepEqual(embedded.navigation, [{target: 'project-stage-1-results'}], 'embedded project requests only the lower result mount');
  assert.deepEqual(embedded.scrolls, []);
  const failures = [
    ['failed receipt', {receipt: {status: 'failed'}}],
    ['unknown receipt', {receipt: {status: 'execution-unknown'}}],
    ['incomplete delivery receipt', {receipt: {delivery_status: 'unknown'}}],
    ['mismatched receipt artifact', {receipt: {artifact_ref: 'foreign-package'}}],
    ['mismatched receipt manifest', {receipt: {manifest_sha256: 'f'.repeat(64)}}],
    ['invalid manifest', {artifact: {manifest_sha256: 'bad'}}],
    ['invalid artifact reference', {artifact: {artifact_ref: '../foreign'}}],
    ['unverified artifact', {artifact: {status: 'source-verification-failed'}}],
    ['missing artifact binding', {artifact: {binding: null}}],
    ['foreign artifact project', {artifact: {binding: {...identity, project_id: 'foreign-id'}}}],
    ['stale artifact input', {artifact: {binding: {...identity, project_id: fixture.project.project_id, input_version: 2}}}],
    ['stale artifact brief', {artifact: {binding: {...identity, project_id: fixture.project.project_id, brief_sha256: 'f'.repeat(64)}}}],
    ['active Stage 2', {activeStage: 2}],
    ['export operation', {operation: 'export'}],
    ['project changes during POST', {beforePostReply: ({project}) => {project.project_ref = 'foreign';}}],
    ['input changes during POST', {beforePostReply: ({project}) => {project.input_version = 2;}}],
    ['brief changes during POST', {beforePostReply: ({project}) => {project.brief_sha256 = 'f'.repeat(64);}}],
    ['generation changes during POST', {beforePostReply: ({find}) => find('new-project').onclick()}],
    ['project changes in readback', {freshProject: {project_ref: 'foreign'}}],
    ['input changes in readback', {freshProject: {input_version: 2}}],
    ['brief changes in readback', {freshProject: {brief_sha256: 'f'.repeat(64)}}],
    ['generation changes during readback', {holdReadback: true}]
  ];
  for (const [name, options] of failures) {
    const result = await scenario({...options, embedded: true});
    assert.deepEqual(result.navigation, [], `${name} cannot navigate`);
    assert.deepEqual(result.scrolls, [], `${name} cannot scroll`);
  }
  return failures.length + 2;
}
(async () => {
  const delivery_navigation_cases = await deliveryNavigationGuards();
  console.log(JSON.stringify({kind: 'ProjectStageSlotsAuthoredDomChecks', stages: 6, languages: 3, refused_contracts: invalidContracts.length, presentation_events: events.length, side_effects: sideEffects.length, delivery_navigation_cases, authored_broker_posts: delivery_navigation_cases, real_network_calls: 0, checks: ['current-bound-fields', 'literal-source-text', 'unknown-and-recorded-zero', 'six-stage-navigation', 'invalid-stage-refusal', 'same-binding-node-preservation', 'trilingual-labels', 'future-stage-disabled', 'malformed-and-foreign-binding', 'loading-and-clear', 'whole-broker-delivery-navigation']}));
})().catch(error => {console.error(error); process.exitCode = 1;});
