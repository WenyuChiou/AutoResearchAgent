/* Actual parent source with authored DOM/channel/GET broker. No live I/O. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = path.resolve(__dirname, '../../cli/research_workspace_native/web/projects-atlas.js');
const hash = 'a'.repeat(64), credential = 'authored-secret-not-for-child';
const project = {project_ref: 'authored-A', revision: 5, input_version: 1, brief_sha256: hash};
const artifact = {artifact_ref: 'stage1-canonical-' + 'b'.repeat(32), status: 'saved-evidence-validated', manifest_sha256: hash};
const binding = {...project, artifact_ref: artifact.artifact_ref, manifest_sha256: hash};
const file = {file_ref: 'c'.repeat(64), sha256: 'd'.repeat(64), path: 'references.bib', mime: 'application/x-bibtex'};
const view = {...binding, schema: 'ProjectStage1AtlasView/1', index_sha256: hash, payload: {index_sha256: hash}, stage2_input: {brief_sha256: hash}, files: [file]};
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.style = {}; this.isConnected = false; }
  append(...nodes) { for (const node of nodes) { if (node instanceof Element) { node.parent = this; node.isConnected = this.isConnected; } this.children.push(node); } }
  replaceChildren(...nodes) { for (const node of this.children) if (node instanceof Element) node.isConnected = false; this.children = []; this.append(...nodes); }
  remove() { this.isConnected = false; if (this.parent) this.parent.children = this.parent.children.filter(node => node !== this); }
  setAttribute(name, value) { this[name] = value; }
  scrollIntoView() { this.scrolled = true; }
}
const area = new Element('div'), inline = new Element('div'); area.isConnected = inline.isConnected = true;
const documentListeners = {}, windowListeners = {}, requests = [], messages = [], ports = [], layouts = [];
let pendingFetch = null, responseView = view, child = null;
const origin = 'http://127.0.0.1:12345';
const find = (root, id) => root.children.find(row => row.id === id) || root.children.filter(row => row instanceof Element).map(row => find(row, id)).find(Boolean);
const sandbox = {
  document: {
    getElementById: id => id === 'project-atlas-entry' ? area : id === 'project-atlas-inline' ? inline : find(area, id) || find(inline, id),
    createElement: tag => { const element = new Element(tag); if (tag === 'iframe') { child = {postMessage(value, target, transfer) {messages.push({value, target, transfer});}}; element.contentWindow = child; } return element; },
    addEventListener: (name, fn) => {documentListeners[name] = fn;}, dispatchEvent: event => layouts.push(event)
  },
  window: {RESEARCH_PROJECTS: {credential}, addEventListener: (name, fn) => {windowListeners[name] = fn;}, open() {throw new Error('popup is forbidden');}},
  location: {origin}, setTimeout: () => 1, clearTimeout() {}, CustomEvent: function (type, options) {this.type = type; this.detail = options.detail;},
  MessageChannel: function () { const port1 = {closed: false, start() {}, close() {this.closed = true;}, postMessage(value) {messages.push({fileReply: value});}}, port2 = {}; ports.push(port1); return {port1, port2}; },
  fetch: async (url, options) => {
    requests.push({url, options});
    const {schema, project_ref, input_version, revision, artifact_ref, manifest_sha256, index_sha256} = responseView;
    // Real file GETs carry this narrow saved-artifact envelope, without a brief,
    // payload or Stage2 context. The current view/brief stays in parent memory.
    const savedFile = {schema, project_ref, input_version, revision, artifact_ref, manifest_sha256, index_sha256, file: {...file, content: 'authored BibTeX'}};
    return pendingFetch ? pendingFetch : {ok: true, json: async () => url.includes('/files/') ? savedFile : responseView};
  }
};
vm.runInNewContext(fs.readFileSync(source, 'utf8'), sandbox);
const state = update => documentListeners['project-atlas-state']({detail: {project, artifact, language: 'en', ...update}});
const ready = (source, messageOrigin = origin) => windowListeners.message({origin: messageOrigin, source, data: {kind: 'project-atlas-ready'}});
const flush = () => new Promise(resolve => setImmediate(resolve));
(async () => {
  state(); const frame = inline.children.find(row => row.tag === 'iframe'); assert.equal(frame.id, 'project-atlas-frame'); assert.equal(frame.src, '/project-atlas.html');
  await flush(); assert.equal(requests.length, 1); assert.equal(messages.length, 0);
  ready({}); ready(child, 'https://foreign.example'); assert.equal(messages.length, 0);
  ready(child); assert.equal(messages.length, 1); assert.equal(messages[0].target, origin); assert.equal(messages[0].value.inline, true);
  assert.equal(JSON.stringify(messages).includes(credential), false);
  assert.equal(requests[0].options.method, 'GET'); assert.equal(requests[0].options.headers.Authorization, 'Bearer ' + credential);
  assert.equal(requests[0].options.credentials, 'omit'); assert.equal(requests[0].options.redirect, 'error');
  const layout = height => ports[0].onmessage({data: {kind: 'layout', ...binding, height}});
  layout(12001); layout(239); layout(500.5); assert.equal(layouts.length, 0);
  ports[0].onmessage({data: {kind: 'layout', ...binding, input_version: 2, height: 800}}); assert.equal(layouts.length, 0);
  layout(850); assert.equal(frame.style.height, '850px'); assert.equal(layouts[0].type, 'project-atlas-layout'); assert.equal(layouts[0].detail.project_ref, project.project_ref);
  ports[0].onmessage({data: {kind: 'file-read', id: 'bad', file_ref: 'e'.repeat(64), sha256: file.sha256}}); await flush(); assert.equal(requests.length, 1);
  ports[0].onmessage({data: {kind: 'file-read', id: 'good', file_ref: file.file_ref, sha256: file.sha256}}); await flush();
  assert.equal(requests.length, 2); assert.equal(messages[1].fileReply.kind, 'file'); assert.equal(requests[1].url.endsWith('/files/' + file.file_ref + '/' + file.sha256), true);
  ports[0].onmessage({data: {kind: 'return'}}); assert.equal(area.scrolled, true); assert.equal(frame.isConnected, true);
  const stableNotice = find(inline, 'project-atlas-result-notice');
  state({language: 'zh-Hant'}); assert.equal(inline.children.find(row => row.tag === 'iframe'), frame); assert.equal(requests.length, 2);
  assert.equal(find(inline, 'project-atlas-result-notice'), stableNotice);
  ready(child); await flush(); assert.equal(requests.length, 3); assert.equal(ports[0].closed, true); assert.equal(ports.length, 2); assert.equal(messages.at(-1).value.language, 'zh-Hant');
  const refreshedMessages = messages.length;
  ports[0].onmessage({data: {kind: 'layout', ...binding, height: 900}});
  ports[0].onmessage({data: {kind: 'file-read', id: 'retired', file_ref: file.file_ref, sha256: file.sha256}});
  await flush(); assert.equal(requests.length, 3); assert.equal(messages.length, refreshedMessages); assert.equal(frame.style.height, '850px');
  for (const changed of [
    {project: {...project, revision: 6}}, {project: {...project, input_version: 2}}, {project: {...project, project_ref: 'authored-B'}},
    {project: {...project, brief_sha256: 'f'.repeat(64)}}, {artifact: {...artifact, artifact_ref: 'stage1-canonical-other'}},
    {artifact: {...artifact, manifest_sha256: 'e'.repeat(64)}}
  ]) {
    const obsolete = inline.children.find(row => row.tag === 'iframe'), priorPort = ports.at(-1);
    const nextProject = changed.project || project, nextArtifact = changed.artifact || artifact;
    responseView = {...view, ...nextProject, artifact_ref: nextArtifact.artifact_ref, manifest_sha256: nextArtifact.manifest_sha256, stage2_input: {brief_sha256: nextProject.brief_sha256}};
    state(changed); assert.equal(obsolete.isConnected, false); assert.equal(priorPort.closed, true);
    ready(child); await flush(); assert.equal(inline.children.filter(row => row.tag === 'iframe').length, 1);
  }
  let release; pendingFetch = new Promise(resolve => {release = resolve;}); responseView = view;
  state(); const obsolete = inline.children.find(row => row.tag === 'iframe'); ready(child); const sent = messages.length;
  documentListeners['project-screening-clear'](); assert.equal(obsolete.isConnected, false);
  release({ok: true, json: async () => view}); await flush(); assert.equal(messages.length, sent); assert.equal(inline.children.filter(row => row.tag === 'iframe').length, 0);
  pendingFetch = null;
  for (const language of ['en', 'zh-Hans', 'zh-Hant']) {
    state({artifact: null, language}); assert.equal(inline.children.filter(row => row.tag === 'iframe').length, 0); assert.ok(area.children[0].textContent.length > 20);
    assert.equal(inline.hidden, false); assert.match(find(inline, 'project-atlas-result-notice').textContent, /Not generated yet|尚未生成|尚未產生/);
    state({artifact: {...artifact, status: 'stale-input'}, language}); assert.equal(inline.children.filter(row => row.tag === 'iframe').length, 0);
  }
  state(); await flush(); ready(child);
  ports.at(-1).onmessage({data: {kind: 'view-error'}}); assert.equal(inline.children.filter(row => row.tag === 'iframe').length, 0); assert.match(area.children[0].textContent, /refused/);
  assert.equal(requests.every(row => row.options.method === 'GET'), true);
  console.log(JSON.stringify({kind: 'AuthoredProjectAtlasChannelChecks', result: 'passed', requests: requests.length, mutation_requests: 0, checks: ['inline-auto-load', 'exact-source-origin', 'credential-retained', 'opaque-file', 'refresh-bound-GET', 'full-binding-retirement', 'late-response-drop', 'bounded-layout', 'trilingual-empty-refusal', 'GET-only']}));
})().catch(error => {console.error(error); process.exitCode = 1;});
