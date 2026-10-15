/* Actual parent panel over a saved Core-package view; authored DOM/fetch only. */
'use strict';
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm'), path = require('node:path');
const view = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
class Element {
  constructor(tag) {this.tag = tag; this.children = []; this.connected = true; this.text = ''; this.style = {};}
  append(...nodes) {for (const node of nodes) node.parent = this; this.children.push(...nodes);}
  replaceChildren(...nodes) {for (const node of this.children) node.disconnect(); this.children = []; this.append(...nodes);}
  remove() {this.disconnect(); if (this.parent) this.parent.children = this.parent.children.filter(node => node !== this);}
  disconnect() {this.connected = false; this.children.forEach(node => node.disconnect());}
  get isConnected() {return this.connected;}
  set textContent(text) {this.text = text;}
  get textContent() {return this.text + this.children.map(node => node.textContent).join('\n');}
  setAttribute(name, value) {this[name] = value;}
}
const flatten = element => [element, ...element.children.flatMap(flatten)];
const area = new Element('div'), inline = new Element('div'), listeners = {}, windowListeners = {}, requests = [], events = [], channels = [];
let reply = view, stage2 = null, readFailure = null, pendingRead = null;
const sandbox = {
  document: {getElementById: id => id === 'project-atlas-entry' ? area : id === 'project-atlas-inline' ? inline : id === 'stage2-input-entry' ? stage2 : [...flatten(area), ...flatten(inline), ...(stage2 ? flatten(stage2) : [])].find(row => row.id === id), createElement: tag => new Element(tag), addEventListener: (key, fn) => {listeners[key] = fn;}, dispatchEvent: event => {events.push(event);}},
  window: {RESEARCH_PROJECTS: {credential: 'authored-private-credential'}, addEventListener: (key, fn) => {windowListeners[key] = fn;}, open() {throw new Error('Atlas popup is forbidden');}},
  location: {origin: 'http://127.0.0.1:12345'}, TextEncoder, setTimeout, clearTimeout,
  CustomEvent: class {constructor(type, options) {this.type = type; this.detail = options.detail;}},
  MessageChannel: class {constructor() {this.port1 = {start() {}, close() {}, postMessage() {}}; this.port2 = {}; channels.push(this);}},
  fetch: async (url, options) => {requests.push({url, options}); if (readFailure) throw readFailure; if (pendingRead) return pendingRead; return {ok: true, json: async () => reply};}
};
vm.runInNewContext(fs.readFileSync(path.resolve(__dirname, '../../cli/research_workspace_native/web/projects-atlas.js'), 'utf8'), sandbox);
const state = (language = 'en', update = {}) => listeners['project-atlas-state']({detail: {
  project: {project_ref: view.project_ref, input_version: view.input_version, revision: view.revision, brief_sha256: view.stage2_input.brief_sha256},
  artifact: {artifact_ref: view.artifact_ref, manifest_sha256: view.manifest_sha256, status: 'saved-evidence-validated'}, language, ...update
}});
const flush = () => new Promise(resolve => setImmediate(resolve));
(async () => {
  let checks = 0;
  for (const [language, title] of [['en', 'Review Stage 1'], ['zh-Hans', '审阅 Stage 1'], ['zh-Hant', '審閱 Stage 1']]) {
    const prior = requests.length; state(language); await flush();
    assert.equal(requests.length, prior + 1, 'changed project binding auto-reads only its saved result');
    const frame = inline.children.find(row => row.tag === 'iframe'); assert(frame); assert.equal(frame.src, '/project-atlas.html');
    const before = requests.length; state(language); await flush();
    assert.equal(inline.children.find(row => row.tag === 'iframe'), frame, 'same binding retains the inline result');
    const details = area.children.find(row => row.tag === 'details'); assert(details.textContent.includes(title));
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
    assert.equal(event.detail.brief_sha256, view.stage2_input.brief_sha256);
    assert.equal(event.detail.artifact_ref, view.artifact_ref); assert.equal(event.detail.decision, 'request-stage2');
    assert.equal(event.detail.user_input, input.value); assert.equal(JSON.stringify(event).includes('credential'), false);
    const count = events.length;
    input.value = '中'.repeat(2000); form.onsubmit({preventDefault() {}});
    input.value = '\ud800'; form.onsubmit({preventDefault() {}}); assert.equal(events.length, count);
    state(language, {project: {project_ref: 'another-project', input_version: 1, revision: 0, brief_sha256: view.stage2_input.brief_sha256}});
    input.value = 'stale'; form.onsubmit({preventDefault() {}}); assert.equal(events.length, count);
    await flush(); assert.equal(frame.isConnected, false);
    checks++;
  }
  reply = {...view, stage2_input: {...view.stage2_input, project_ref: 'foreign-project'}};
  state(); await flush(); const content = area.children.find(row => row.tag === 'details').children[1]; await content.children[0].onclick();
  assert.equal(flatten(content).some(node => node.tag === 'form'), false);
  assert.equal(requests.every(row => row.options.method === 'GET'), true);
  assert.equal(requests.every(row => row.options.credentials === 'omit' && row.options.redirect === 'error'), true);
  listeners['project-screening-clear'](); assert.equal(flatten(area).some(row => row.tag === 'form' || row.tag === 'details'), false);
  assert.equal(inline.children.some(row => row.tag === 'iframe'), false);
  assert.match(flatten(inline).find(row => row.id === 'project-atlas-result-notice').textContent, /Not generated yet/);
  stage2 = new Element('div'); reply = view;
  let stage2Checks = 0;
  for (const [language, title, consumer] of [['en', 'Review Stage 1', 'Stage 2 consumer'], ['zh-Hans', '审阅 Stage 1', 'Stage 2 接口'], ['zh-Hant', '審閱 Stage 1', 'Stage 2 介面']]) {
    const prior = requests.length; state(language); await flush();
    assert.equal(requests.length, prior + 1, 'Stage 2 input reuses the initial saved Atlas GET');
    assert.equal(area.children.some(row => row.tag === 'details'), false, 'input review belongs to Stage 2');
    const details = stage2.children.find(row => row.tag === 'details'); assert(details.open); assert(details.textContent.includes(title));
    assert(details.textContent.includes(consumer)); assert(details.textContent.includes(view.stage2_input.records_version));
    assert(view.stage2_input.works.every(work => details.textContent.includes(work.title)));
    const form = flatten(details).find(row => row.tag === 'form'); assert(form);
    const before = requests.length; state(language); await flush();
    assert.equal(requests.length, before, 'same binding and language projection adds no read or mutation');
    const count = events.length;
    form.children[1].children[0].value = 'disconnected same-version form'; form.onsubmit({preventDefault() {}});
    assert.equal(events.length, count, 'a replaced form cannot save an earlier view');
    const currentForm = flatten(stage2).find(row => row.tag === 'form');
    currentForm.children[0].value = 'hold'; currentForm.children[1].children[0].value = 'Keep the saved limitations';
    currentForm.onsubmit({preventDefault() {}});
    const event = events.at(-1); assert.equal(event.type, 'project-review-stage2-input');
    assert.equal(event.detail.context_sha256, view.stage2_input.context_sha256);
    assert.equal(event.detail.brief_sha256, view.stage2_input.brief_sha256);
    assert.equal(event.detail.revision, view.revision); assert.equal(event.detail.manifest_sha256, view.manifest_sha256);
    assert.equal(event.detail.decision, 'hold'); assert.equal(requests.length, before);
    currentForm.children[0].value = 'execute-stage2'; currentForm.onsubmit({preventDefault() {}});
    assert.equal(events.length, count + 1, 'review cannot introduce an execution decision');
    listeners['project-screening-clear'](); assert.equal(flatten(stage2).some(row => row.tag === 'form'), false);
    stage2Checks++;
  }
  for (const version of ['1.1.0', '1.2.0']) {
    reply = {...view, stage2_input: {...view.stage2_input, records_version: version, consumer_status: 'unconnected', eligible_for_stage2: false, limitations: ['stage2-canonical-consumer-unconnected']}};
    state(); await flush();
    assert(stage2.textContent.includes(version)); assert(stage2.textContent.includes('Consumer unconnected'));
    assert(stage2.textContent.includes('Handoff not eligible'));
    assert.equal(flatten(stage2).some(row => row.id === 'activate-stage2'), false);
    listeners['project-screening-clear']();
  }
  for (const change of [
    {project_ref: 'foreign-project'}, {input_version: view.input_version + 1}, {brief_sha256: 'f'.repeat(64)},
    {artifact_ref: 'foreign-artifact'}, {manifest_sha256: 'f'.repeat(64)}, {index_sha256: 'f'.repeat(64)},
    {context_sha256: 'invalid'}, {execution_authorized: true}, {limitations: null}
  ]) {
    reply = {...view, stage2_input: {...view.stage2_input, ...change}};
    const prior = requests.length, before = events.length;
    state(); await flush();
    assert.equal(flatten(stage2).some(row => row.tag === 'form'), false, 'foreign or malformed input refuses the automatic projection');
    const notice = stage2.children.find(row => row.id === 'stage2-input-notice'); assert(notice && notice.isConnected && notice.hidden !== true);
    assert.equal(notice.role, 'status'); assert(notice.textContent.includes('input was refused or could not be read'));
    assert.equal(view.stage2_input.works.some(work => stage2.textContent.includes(work.title)), false, 'refusal retains no source text');
    assert.equal(requests.length, prior + 1, 'refusal adds no request'); assert.equal(events.length, before, 'refusal adds no mutation event');
    listeners['project-screening-clear']();
  }
  for (const [language, failure] of [['en', 'input was refused or could not be read'], ['zh-Hans', '输入被拒绝或无法读取'], ['zh-Hant', '輸入被拒絕或無法讀取']]) {
    reply = {...view, stage2_input: {...view.stage2_input, project_ref: 'foreign-project'}};
    const prior = requests.length, before = events.length;
    state(language); await flush();
    assert(stage2.textContent.includes(failure)); assert.equal(flatten(stage2).some(row => row.tag === 'form'), false);
    assert.equal(requests.length, prior + 1); assert.equal(events.length, before);
    state(language, {artifact: null}); await flush();
    assert.equal(flatten(stage2).some(row => row.id === 'stage2-input-notice'), false, 'changed project state clears the old refusal');
    listeners['project-screening-clear']();
    reply = view; readFailure = new Error('authored saved-view read failure');
    state(language); await flush();
    assert(stage2.textContent.includes(failure)); assert.equal(flatten(stage2).some(row => row.tag === 'form'), false);
    assert.equal(requests.length, prior + 2, 'failed read adds only its original GET'); assert.equal(events.length, before);
    readFailure = null; listeners['project-screening-clear']();
    state(language); await flush();
    const child = inline.children.find(row => row.tag === 'iframe'); assert(child);
    child.contentWindow = {postMessage() {}};
    windowListeners.message({origin: sandbox.location.origin, source: child.contentWindow, data: {kind: 'project-atlas-ready'}});
    const port = channels.at(-1).port1; assert.equal(typeof port.onmessage, 'function');
    port.onmessage({data: {kind: 'view-error'}});
    const childNotice = stage2.children.find(row => row.id === 'stage2-input-notice'); assert(childNotice && childNotice.isConnected && childNotice.hidden !== true);
    assert(childNotice.textContent.includes(failure)); assert.equal(flatten(stage2).some(row => row.tag === 'form'), false);
    assert.equal(child.isConnected, false); assert.equal(requests.length, prior + 3); assert.equal(events.length, before);
    state(language, {artifact: null}); await flush(); const cleared = stage2.textContent;
    port.onmessage({data: {kind: 'view-error'}});
    assert.equal(stage2.textContent, cleared, 'retired child errors cannot restore a refusal');
    listeners['project-screening-clear']();
  }
  let rejectRead;
  pendingRead = new Promise((_, reject) => {rejectRead = reject;}); reply = view;
  const beforeLate = requests.length, beforeLateEvents = events.length;
  state(); await flush();
  state('en', {project: {project_ref: 'another-project', input_version: 1, revision: 0, brief_sha256: view.stage2_input.brief_sha256}, artifact: null}); await flush();
  const switched = stage2.textContent;
  rejectRead(new Error('authored late read failure')); pendingRead = null; await flush();
  assert.equal(stage2.textContent, switched, 'late failed reads cannot restore a refusal to another project');
  assert.equal(flatten(stage2).some(row => row.id === 'stage2-input-notice' || row.tag === 'form'), false);
  assert.equal(requests.length, beforeLate + 1); assert.equal(events.length, beforeLateEvents);
  listeners['project-screening-clear']();
  state('en', {artifact: null}); await flush();
  assert(stage2.textContent.includes('No validated saved Stage 1 input'));
  assert.equal(requests.every(row => row.options.method === 'GET'), true);
  assert.equal(requests.every(row => row.options.credentials === 'omit' && row.options.redirect === 'error'), true);
  console.log(JSON.stringify({kind: 'SavedStage2InputPanelAuthoredDomChecks', trilingual_panels: checks, trilingual_stage2_slots: stage2Checks, mutation_requests: 0, checks: ['inline-auto-GET', 'same-binding-retained', 'stage2-input-placement', 'stage2-reuses-validated-GET', 'opaque-bound-decision', 'all-works-retained', 'unknown', 'source-text', 'UTF8-bound', 'surrogate-rejection', 'stale-form', 'disconnected-form', 'foreign-context', 'visible-stage2-refusal', 'trilingual-read-failure', 'trilingual-child-failure', 'retired-child-failure', 'late-failure-project-switch', 'unconnected-1.1-1.2', 'GET-only']}));
})().catch(error => {console.error(error); process.exitCode = 1;});
