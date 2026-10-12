/* Actual StageSlots source and HTML; authored shared-contract data, no runtime. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
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
  ['en', /status/i, /Operations/, /Results/, /Expected outputs/, /unconnected/i],
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
for (const [key, value] of [['project_ref', '../foreign'], ['revision', -1], ['input_version', '1'], ['brief_sha256', 'not-a-hash']]) {
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
console.log(JSON.stringify({kind: 'ProjectStageSlotsAuthoredDomChecks', stages: 6, languages: 3, refused_contracts: invalidContracts.length, presentation_events: events.length, side_effects: sideEffects.length, checks: ['current-bound-fields', 'literal-source-text', 'unknown-and-recorded-zero', 'six-stage-navigation', 'invalid-stage-refusal', 'same-binding-node-preservation', 'trilingual-labels', 'future-stage-disabled', 'malformed-and-foreign-binding', 'loading-and-clear']}));
