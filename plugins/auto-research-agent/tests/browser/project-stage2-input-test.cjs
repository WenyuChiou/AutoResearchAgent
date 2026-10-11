/* Actual parent panel over a saved Core-package view; authored DOM/fetch only. */
'use strict';
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm'), path = require('node:path');
const view = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
class Element {
  constructor(tag) {this.tag = tag; this.children = []; this.connected = true; this.text = '';}
  append(...nodes) {this.children.push(...nodes);}
  replaceChildren(...nodes) {for (const node of this.children) node.disconnect(); this.children = nodes;}
  disconnect() {this.connected = false; this.children.forEach(node => node.disconnect());}
  get isConnected() {return this.connected;}
  set textContent(text) {this.text = text;}
  get textContent() {return this.text + this.children.map(node => node.textContent).join('\n');}
  setAttribute(name, value) {this[name] = value;}
}
const flatten = element => [element, ...element.children.flatMap(flatten)];
const area = new Element('div'), listeners = {}, requests = [], events = [];
let reply = view;
const sandbox = {
  document: {getElementById: id => id === 'project-atlas-entry' ? area : flatten(area).find(row => row.id === id), createElement: tag => new Element(tag), addEventListener: (key, fn) => {listeners[key] = fn;}, dispatchEvent: event => {events.push(event);}},
  window: {RESEARCH_PROJECTS: {credential: 'authored-private-credential'}, addEventListener() {}},
  location: {origin: 'http://127.0.0.1:12345'}, TextEncoder, setTimeout, clearTimeout,
  CustomEvent: class {constructor(type, options) {this.type = type; this.detail = options.detail;}},
  fetch: async (url, options) => {requests.push({url, options}); return {ok: true, json: async () => reply};}
};
vm.runInNewContext(fs.readFileSync(path.resolve(__dirname, '../../cli/research_workspace_native/web/projects-atlas.js'), 'utf8'), sandbox);
const state = (language = 'en', update = {}) => listeners['project-atlas-state']({detail: {
  project: {project_ref: view.project_ref, input_version: view.input_version, revision: view.revision},
  artifact: {artifact_ref: view.artifact_ref, manifest_sha256: view.manifest_sha256, status: 'saved-evidence-validated'}, language, ...update
}});
(async () => {
  let checks = 0;
  for (const [language, title] of [['en', 'Review Stage 1'], ['zh-Hans', '审阅 Stage 1'], ['zh-Hant', '審閱 Stage 1']]) {
    state(language); const before = requests.length;
    const details = area.children[2]; assert(details.textContent.includes(title));
    assert.equal(requests.length, before, 'closed review panel does not read or execute');
    await details.children[1].children[0].onclick();
    assert.equal(requests.length, before + 1);
    const panel = details.children[1];
    assert(view.stage2_input.works.every(work => panel.textContent.includes(work.title)));
    assert(panel.textContent.includes('Unknown')); assert(panel.textContent.includes(view.stage2_input.context_sha256));
    const form = flatten(panel).find(row => row.tag === 'form');
    const select = form.children[0], input = form.children[1].children[0];
    select.value = 'request-stage2'; input.value = '<img src=x> 原文';
    form.onsubmit({preventDefault() {}});
    const event = events.at(-1); assert.equal(event.type, 'project-review-stage2-input');
    assert.equal(event.detail.context_sha256, view.stage2_input.context_sha256);
    assert.equal(event.detail.artifact_ref, view.artifact_ref); assert.equal(event.detail.decision, 'request-stage2');
    assert.equal(event.detail.user_input, input.value); assert.equal(JSON.stringify(event).includes('credential'), false);
    const count = events.length;
    input.value = '中'.repeat(2000); form.onsubmit({preventDefault() {}});
    input.value = '\ud800'; form.onsubmit({preventDefault() {}}); assert.equal(events.length, count);
    state(language, {project: {project_ref: 'another-project', input_version: 1, revision: 0}});
    input.value = 'stale'; form.onsubmit({preventDefault() {}}); assert.equal(events.length, count);
    checks++;
  }
  reply = {...view, stage2_input: {...view.stage2_input, project_ref: 'foreign-project'}};
  state(); const content = area.children[2].children[1]; await content.children[0].onclick();
  assert.equal(flatten(content).some(node => node.tag === 'form'), false);
  assert.equal(requests.every(row => row.options.method === 'GET'), true);
  assert.equal(requests.every(row => row.options.credentials === 'omit' && row.options.redirect === 'error'), true);
  listeners['project-screening-clear'](); assert.equal(area.children.length, 0);
  console.log(JSON.stringify({kind: 'SavedStage2InputPanelAuthoredDomChecks', trilingual_panels: checks, mutation_requests: 0, checks: ['opaque-bound-decision', 'all-works-retained', 'unknown', 'source-text', 'UTF8-bound', 'surrogate-rejection', 'stale-form', 'foreign-context', 'GET-only']}));
})().catch(error => {console.error(error); process.exitCode = 1;});
