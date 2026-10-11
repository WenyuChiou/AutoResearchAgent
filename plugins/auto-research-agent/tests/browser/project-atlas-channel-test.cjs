/* Actual parent source with an authored DOM/channel/fetch broker. No live I/O. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = path.resolve(__dirname, '../../cli/research_workspace_native/web/projects-atlas.js');
const hash = 'a'.repeat(64), credential = 'authored-secret-not-for-child';
const project = {project_ref: 'authored-A', revision: 5, input_version: 1};
const artifact = {artifact_ref: 'stage1-canonical-' + 'b'.repeat(32), status: 'saved-evidence-validated', manifest_sha256: hash};
const binding = {...project, artifact_ref: artifact.artifact_ref, manifest_sha256: hash};
const file = {file_ref: 'c'.repeat(64), sha256: 'd'.repeat(64), path: 'references.bib', mime: 'application/x-bibtex'};
const view = {...binding, schema: 'ProjectStage1AtlasView/1', index_sha256: hash, payload: {index_sha256: hash}, files: [file]};
class Element {
  constructor() { this.children = []; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  setAttribute(name, value) { this[name] = value; }
}
const area = new Element(), documentListeners = {}, windowListeners = {}, requests = [], messages = [], ports = [];
let pendingFetch = null, child = null;
const origin = 'http://127.0.0.1:12345';
const sandbox = {
  document: {getElementById: id => id === 'project-atlas-entry' ? area : area.children.find(row => row.id === id), createElement: () => new Element(), addEventListener: (name, fn) => {documentListeners[name] = fn;}},
  window: {RESEARCH_PROJECTS: {credential}, focus() {}, addEventListener: (name, fn) => {windowListeners[name] = fn;}, open(url) { assert.equal(url, '/project-atlas.html'); child = {closed: false, close() {this.closed = true;}, postMessage(value, target, transfer) {messages.push({value, target, transfer});}}; return child; }},
  location: {origin}, setTimeout: () => 1, clearTimeout() {},
  MessageChannel: function () { const port1 = {closed: false, start() {}, close() {this.closed = true;}, postMessage(value) {messages.push({fileReply: value});}}, port2 = {}; ports.push(port1); return {port1, port2}; },
  fetch: async (url, options) => { requests.push({url, options}); return pendingFetch ? pendingFetch : {ok: true, json: async () => url.includes('/files/') ? {...binding, index_sha256: hash, file: {...file, content: 'authored BibTeX'}} : view}; }
};
vm.runInNewContext(fs.readFileSync(source, 'utf8'), sandbox);
const state = update => documentListeners['project-atlas-state']({detail: {project, artifact, language: 'en', ...update}});
const ready = (source, messageOrigin = origin) => windowListeners.message({origin: messageOrigin, source, data: {kind: 'project-atlas-ready'}});
const flush = () => new Promise(resolve => setImmediate(resolve));
(async () => {
  state(); const button = area.children[0]; assert.equal(button.id, 'project-atlas-open');
  await button.onclick(); assert.equal(requests.length, 1); assert.equal(messages.length, 0);
  ready({}); ready(child, 'https://foreign.example'); assert.equal(messages.length, 0);
  ready(child); assert.equal(messages.length, 1); assert.equal(messages[0].target, origin);
  assert.equal(JSON.stringify(messages).includes(credential), false);
  assert.equal(requests[0].options.method, 'GET'); assert.equal(requests[0].options.headers.Authorization, 'Bearer ' + credential);
  assert.equal(requests[0].options.credentials, 'omit'); assert.equal(requests[0].options.redirect, 'error');
  ports[0].onmessage({data: {kind: 'file-read', id: 'bad', file_ref: 'e'.repeat(64), sha256: file.sha256}}); await flush(); assert.equal(requests.length, 1);
  ports[0].onmessage({data: {kind: 'file-read', id: 'good', file_ref: file.file_ref, sha256: file.sha256}}); await flush();
  assert.equal(requests.length, 2); assert.equal(messages[1].fileReply.kind, 'file');
  assert.equal(requests[1].url.endsWith('/files/' + file.file_ref + '/' + file.sha256), true);
  ports[0].onmessage({data: {kind: 'language', language: 'zh-Hant'}});
  ready(child); await flush(); assert.equal(requests.length, 3); assert.equal(ports[0].closed, true); assert.equal(ports.length, 2); assert.equal(messages.length, 3); assert.equal(messages[2].value.language, 'zh-Hant');
  state({project: {...project, revision: 6}}); assert.equal(child.closed, true); assert.equal(ports[1].closed, true);
  let release; pendingFetch = new Promise(resolve => {release = resolve;});
  const opening = area.children[0].onclick(); const obsolete = child; ready(child);
  documentListeners['project-screening-clear'](); assert.equal(obsolete.closed, true);
  release({ok: true, json: async () => view}); await opening;
  assert.equal(messages.length, 3); assert.equal(area.children.length, 0);
  pendingFetch = null; state({artifact: {...artifact, status: 'stale-input'}}); assert.equal(area.children.length, 0);
  assert.equal(requests.every(row => row.options.method === 'GET'), true);
  console.log(JSON.stringify({kind: 'AuthoredProjectAtlasChannelChecks', result: 'passed', requests: requests.length, mutation_requests: 0, checks: ['exact-source-origin', 'credential-retained', 'opaque-file', 'refresh-bound-GET', 'stale-close', 'late-response-drop', 'stale-delivery-hidden', 'GET-only']}));
})().catch(error => {console.error(error); process.exitCode = 1;});
