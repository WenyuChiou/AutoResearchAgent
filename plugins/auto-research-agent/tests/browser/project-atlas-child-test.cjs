/* Actual iframe child source, authored DOM and memory port; no browser/network I/O. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {webcrypto} = require('node:crypto');
const source = path.resolve(__dirname, '../../cli/research_workspace_native/web/project-atlas-child.js');
const hash = 'a'.repeat(64), origin = 'http://127.0.0.1:12345';
const binding = {project_ref: 'authored-A', input_version: 1, revision: 5, brief_sha256: hash, artifact_ref: 'stage1-canonical-authored', manifest_sha256: hash};
const content = '@article{authored,title={Authored citation}}';
const fileHash = require('node:crypto').createHash('sha256').update(content).digest('hex');
const file = {file_ref: 'b'.repeat(64), sha256: fileHash, path: 'references.bib', mime: 'application/x-bibtex'};
const view = {...binding, schema: 'ProjectStage1AtlasView/1', index_sha256: hash, payload: {index_sha256: hash}, stage2_input: {brief_sha256: hash}, files: [file]};
const events = {}, documentEvents = {}, messages = [], scripts = [], frames = [], downloads = [], classes = [];
let bodyHeight = 800;
let digestsStarted = 0, digestsSettled = 0;
class Element {
  constructor(tag) {this.tag = tag; this.children = []; this.listeners = {}; this.value = 'en';}
  setAttribute(name, value) {this[name] = value;}
  append(...items) { this.children.push(...items); for (const item of items) if (item?.tag === 'script') {scripts.push(item.src); queueMicrotask(() => item.onload());} }
  getBoundingClientRect() {return {height: bodyHeight};}
  addEventListener(name, fn) {this.listeners[name] = fn;}
  dispatchEvent(event) {this.listeners[event.type]?.(event);}
  click() {downloads.push(this);}
}
const status = new Element('p'), languageControl = new Element('select'), body = new Element('body'), head = new Element('head');
body.classList = {add(name) {classes.push(name);}};
const parent = {postMessage(value, target) {messages.push({ready: value, target});}};
const port = {closed: false, start() {this.started = true;}, close() {this.closed = true;}, postMessage(value) {messages.push({port: value});}};
const window = {parent, opener: {postMessage() {throw new Error('opener must not be used');}}, addEventListener(name, fn) {events[name] = fn;}};
const sandbox = {
  window, document: {body, head, getElementById: id => id === 'project-atlas-status' ? status : id === 'atlas-language' ? languageControl : null, createElement: tag => new Element(tag), addEventListener: (name, fn) => {documentEvents[name] = fn;}},
  location: {origin, href: origin + '/project-atlas.html'}, requestAnimationFrame: fn => frames.push(fn), setTimeout: () => 1, clearTimeout() {},
  ResizeObserver: class {observe() {} disconnect() {this.disconnected = true;}},
  MutationObserver: class {observe() {} disconnect() {this.disconnected = true;}},
  TextEncoder, Blob, crypto: {subtle: {async digest(...args) {++digestsStarted; try {return await webcrypto.subtle.digest(...args);} finally {++digestsSettled;}}}}, URL: class extends URL {static createObjectURL() {return 'blob:authored';} static revokeObjectURL() {}},
  Event: function (type) {this.type = type;}
};
vm.runInNewContext(fs.readFileSync(source, 'utf8'), sandbox);
const bound = (change = {}, eventChange = {}) => events.message({source: parent, origin, data: {kind: 'project-atlas-bound', view, binding, language: 'en', inline: true, ...change}, ports: [port], ...eventChange});
const flush = () => new Promise(resolve => setImmediate(resolve));
const settledDigest = async count => {
  const deadline = Date.now() + 3000;
  while (digestsSettled < count && Date.now() < deadline) await flush();
  assert.equal(digestsStarted, count); assert.equal(digestsSettled, count, 'saved-file digest did not settle');
  await flush();
};
const measure = () => {while (frames.length) frames.shift()();};
(async () => {
  assert.equal(messages[0].ready.kind, 'project-atlas-ready'); assert.equal(messages[0].target, origin);
  for (const invalid of [
    {eventChange: {source: {}}}, {eventChange: {origin: 'https://foreign.invalid'}}, {eventChange: {ports: []}},
    {change: {inline: false}}, {change: {binding: {...binding, revision: 6}}}, {change: {binding: {...binding, brief_sha256: 'c'.repeat(64)}}},
    {change: {binding: {...binding, input_version: 0}}}, {change: {binding: {...binding, manifest_sha256: 'invalid'}}},
    {change: {view: {...view, index_sha256: 'invalid'}}}, {change: {view: {...view, payload: {index_sha256: 'c'.repeat(64)}}}},
    {change: {view: {...view, files: [{...file, path: '../private.md'}]}}}, {change: {view: {...view, files: [{...file, mime: 'text/html'}]}}}
  ]) {bound(invalid.change, invalid.eventChange); await flush(); assert.equal(scripts.length, 0);}
  bound(); await flush(); measure(); assert.equal(port.started, true); assert.equal(scripts.length, 7);
  assert.deepEqual(scripts.map(name => name.split('/').at(-1)), ['atlas-model.js', '3d-force-graph-1.80.1.min.js', 'atlas-associations.js', 'atlas-spatial.js', 'atlas-network.js', 'project-atlas-screening.js', 'atlas-ui.js']);
  assert.deepEqual(classes, ['project-atlas-inline']); assert.match(head.children[0].textContent, /\.atlas-sidebar/); assert.equal(window.WORKSPACE_VIEW, view.payload);
  const layout = messages.find(row => row.port?.kind === 'layout').port; assert.equal(layout.height, 800); assert.equal(layout.brief_sha256, hash);
  bound(); await flush(); assert.equal(scripts.length, 7);
  bodyHeight = 20000; events.resize(); measure(); assert.equal(messages.at(-1).port.height, 12000);
  bodyHeight = 100; events.resize(); measure(); assert.equal(messages.at(-1).port.height, 240);
  port.onmessage({data: {kind: 'language', language: 'zh-Hans'}}); assert.equal(languageControl.value, 'zh-Hans'); assert.match(status.textContent, /已保存/);
  const link = {href: origin + '/references.bib'}, click = {target: {closest: () => link}, preventDefault() {this.prevented = true;}};
  documentEvents.click(click); assert.equal(click.prevented, true); const request = messages.at(-1).port; assert.equal(request.kind, 'file-read'); assert.equal(request.sha256, fileHash);
  port.onmessage({data: {kind: 'file', id: request.id, file: {...file, sha256: 'c'.repeat(64), content}}}); await flush(); assert.equal(downloads.length, 0);
  documentEvents.click(click); const valid = messages.at(-1).port;
  port.onmessage({data: {kind: 'file', id: valid.id, file: {...file, content}}}); await settledDigest(1); assert.equal(downloads.length, 1); assert.equal(downloads[0].download, 'references.bib');
  documentEvents.click(click); const corrupt = messages.at(-1).port;
  port.onmessage({data: {kind: 'file', id: corrupt.id, file: {...file, content: content + 'tampered'}}}); await settledDigest(2); assert.equal(downloads.length, 1);
  events.pagehide(); assert.equal(port.closed, true); assert.equal(window.WORKSPACE_VIEW, undefined);
  console.log(JSON.stringify({kind: 'AuthoredProjectAtlasChildChecks', result: 'passed', native_model_search_calls: 0, checks: ['exact-frame-parent-origin-port', 'project-brief-version-artifact-hash', 'file-allowlist-hash', 'single-bind', 'inline-chrome', 'bounded-height', 'language-sync', 'pagehide-retirement']}));
})().catch(error => {console.error(error); process.exitCode = 1;});
