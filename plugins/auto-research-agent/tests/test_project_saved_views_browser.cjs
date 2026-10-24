'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.resolve(__dirname, '../cli/research_workspace_native/web/project-saved-views.js'), 'utf8');
const hash = character => character.repeat(64);
const ref = 'saved_view_A03';
const row = {
  ref,
  label: 'Canonical Stage1 delivery',
  project_id: 'real30',
  input_version: 'STRING20261009-A03',
  index_sha256: hash('a'),
  manifest_sha256: hash('b'),
  html_sha256: hash('c'),
  url: `/project-stage1-saved/${ref}/index.html`,
  fixture: false,
  read_only: true,
  execution_authorized: false,
  accepted: false
};

class Element {
  constructor(tag) {
    this.tag = tag;
    this.children = [];
    this.parent = null;
    this.attributes = {};
    this.style = {};
    this.hidden = false;
    this.value = '';
    this._text = '';
    if (tag === 'iframe') this.contentDocument = {URL: 'http://127.0.0.1/saved', body: {getBoundingClientRect: () => ({height: 487.2})}};
  }
  append(...nodes) { for (const node of nodes) { node.remove(); node.parent = this; this.children.push(node); } }
  after(node) {
    node.remove();
    const index = this.parent.children.indexOf(this);
    node.parent = this.parent;
    this.parent.children.splice(index + 1, 0, node);
  }
  remove() {
    if (this.parent) this.parent.children = this.parent.children.filter(node => node !== this);
    this.parent = null;
  }
  replaceChildren(...nodes) { for (const child of this.children) child.parent = null; this.children = []; this.append(...nodes); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name] ?? null; }
  set textContent(value) { this._text = String(value); }
  get textContent() { return this._text + this.children.map(node => node.textContent).join(''); }
}
const flatten = node => [node, ...node.children.flatMap(flatten)];

function run(config) {
  const root = new Element('body');
  const anchor = new Element('section');
  const binding = new Element('script');
  binding.textContent = typeof config === 'string' ? config : JSON.stringify(config);
  root.append(anchor, binding);
  const forbidden = name => () => { throw new Error(`${name} is forbidden`); };
  const document = {
    createElement: tag => new Element(tag),
    getElementById: id => id === 'project-saved-view-bindings' ? binding : flatten(root).find(node => node.id === id) || null,
    dispatchEvent: forbidden('dispatch')
  };
  const window = {location: {origin: 'http://127.0.0.1'}, document};
  const sandbox = {
    window, document, URL,
    fetch: forbidden('fetch'),
    XMLHttpRequest: forbidden('XMLHttpRequest'),
    WebSocket: forbidden('WebSocket'),
    EventSource: forbidden('EventSource'),
    localStorage: new Proxy({}, {get: forbidden('localStorage read'), set: forbidden('localStorage write')})
  };
  vm.runInNewContext(source, sandbox, {filename: 'project-saved-views.js'});
  return {root, anchor, api: window.ResearchSavedStage1Views};
}

function sectionOf(result) { return result.root.children.find(node => node.id === 'project-saved-stage1'); }
function frameOf(section) { return flatten(section).find(node => node.id === 'project-saved-stage1-frame'); }

{
  const result = run({kind: 'SavedStage1References', schema_version: '1.0.0', views: [row]});
  assert(Object.isFrozen(result.api));
  assert.equal(result.api.mount({anchor: result.anchor}), true);
  const section = sectionOf(result);
  assert.equal(result.root.children.indexOf(section), result.root.children.indexOf(result.anchor) + 1);
  assert.match(section.textContent, /Saved Stage1 delivery · read-only/);
  assert.match(section.textContent, /real30/);
  assert.match(section.textContent, /STRING20261009-A03/);
  let frame = frameOf(section);
  assert(frame);
  assert.equal(frame.src, row.url);
  assert.equal(frame.title, 'Saved Stage1 delivery');
  assert.equal(frame.getAttribute('sandbox'), 'allow-scripts allow-same-origin allow-downloads');
  frame.onload();
  assert.equal(frame.style.height, '488px');
  frame.readerState = {scrollTop: 240, downloadFocused: true};
  result.api.update({selection: null, stage: 1, language: 'en'});
  assert.equal(frameOf(section), frame, 'unchanged native summaries preserve the same saved reader iframe');
  assert.equal(frameOf(section).src, row.url);
  assert.deepEqual(frameOf(section).readerState, {scrollTop: 240, downloadFocused: true});

  result.api.update({selection: {project_ref: 'native'}, stage: 1, language: 'en'});
  assert.equal(section.hidden, true);
  assert.equal(frameOf(section), undefined);
  result.api.update({selection: null, stage: 1, language: 'zh-Hant'});
  assert.equal(section.hidden, false);
  assert.match(section.textContent, /已保存的 Stage1 交付 · 唯讀/);
  frame = frameOf(section);
  assert(frame);
  assert.equal(frame.src, row.url);
  assert.equal(flatten(section).some(node => node.tag === 'button'), false, 'saved references expose no native mutation action');
  result.api.update({selection: null, stage: 1, language: 'zh-Hans'});
  assert.match(section.textContent, /已保存的 Stage1 交付 · 只读/);
  result.api.update({selection: null, stage: 2, language: 'en'});
  assert.equal(section.hidden, true);
  assert.equal(frameOf(section), undefined);
  result.api.update({selection: null, stage: 1, language: 'en'});
  assert.equal(frameOf(section).src, row.url, 'returning to Stage1 restores the valid saved selection');
}

{
  const second = {...row, ref: 'saved_view_B04', label: 'L'.repeat(160), project_id: 'project-b', input_version: 7,
    url: '/project-stage1-saved/saved_view_B04/index.html', index_sha256: hash('d')};
  const result = run({kind: 'SavedStage1References', schema_version: '1.0.0', views: [row, second]});
  result.api.mount({anchor: result.anchor});
  const section = sectionOf(result);
  assert.equal(frameOf(section), undefined, 'multiple saved views require an explicit selection');
  const select = flatten(section).find(node => node.tag === 'select');
  assert.equal(select.children.at(-1).textContent.length, 160, 'loader and client accept the same label boundary');
  select.value = second.ref;
  select.onchange();
  assert.equal(frameOf(section).src, second.url);
  assert.match(section.textContent, /project-b/);
  assert.match(section.textContent, /Input version: 7/);
  result.api.update({selection: {}, stage: 1, language: 'en'});
  result.api.update({selection: null, stage: 1, language: 'en'});
  assert.equal(frameOf(section).src, second.url);
}

for (const invalid of [
  '{',
  {kind: 'SavedStage1References', schema_version: '1.0.0', views: [{...row, url: row.url + '?download=1'}]},
  {kind: 'SavedStage1References', schema_version: '1.0.0', views: [{...row, url: 'https://foreign.example' + row.url}]},
  {kind: 'SavedStage1References', schema_version: '1.0.0', views: [{...row, manifest_sha256: 'bad'}]},
  {kind: 'SavedStage1References', schema_version: '1.0.0', views: [{...row, input_version: true}]},
  {kind: 'SavedStage1References', schema_version: '1.0.0', views: [{...row, input_version: null}]}
]) {
  const result = run(invalid);
  result.api.mount({anchor: result.anchor});
  assert.equal(frameOf(sectionOf(result)), undefined, 'malformed or untrusted bindings fail closed');
}

const projectA = 'project-' + '1'.repeat(32);
const projectB = 'project-' + '2'.repeat(32);
const bind = (view, project_ref) => ({
  ...view, project_ref, project_input_sha256: hash('d'),
  binding_origin: 'trusted-host-stage1-view-binding'
});
const boundA = bind(row, projectA);
const boundB = bind({...row, ref: 'saved_view_B', label: 'Other project material',
  url: '/project-stage1-saved/saved_view_B/index.html'}, projectB);
const selection = project_ref => ({project_ref, input_version: row.input_version});

{
  const result = run({kind: 'SavedStage1References', schema_version: '1.0.0', views: [row, boundB, boundA]});
  // The saved refs must be unique, even if an unbound copy has the same identity.
  result.api.mount({anchor: result.anchor});
  result.api.update({selection: selection(projectA), stage: 1, language: 'en'});
  assert.equal(frameOf(sectionOf(result)), undefined, 'duplicate saved refs fail closed');
}

{
  const legacy = {...row, ref: 'saved_unbound', url: '/project-stage1-saved/saved_unbound/index.html'};
  const result = run({kind: 'SavedStage1References', schema_version: '1.0.0', views: [legacy, boundB, boundA]});
  result.api.mount({anchor: result.anchor});
  const section = sectionOf(result);
  result.api.update({selection: selection(projectA), stage: 1, language: 'en'});
  assert.equal(section.hidden, false, 'the exact project can read its trusted saved material');
  let frame = frameOf(section);
  assert(frame);
  assert.equal(frame.src, boundA.url);
  assert.match(section.textContent, /STRING20261009-A03/, 'string input versions remain literal');
  assert.doesNotMatch(section.textContent, /Other project material/);
  assert.equal(flatten(section).some(node => node.tag === 'select'), false, 'unbound/other-project rows are not offered');
  assert.equal(frame.getAttribute('sandbox'), 'allow-scripts allow-same-origin allow-downloads');
  result.api.update({selection: selection(projectA), stage: 1, language: 'en'});
  assert.equal(frameOf(section), frame, 'same binding summaries preserve the reader');
  const mutableSelection = selection(projectA);
  result.api.update({selection: mutableSelection, stage: 1, language: 'en'});
  mutableSelection.project_ref = projectB;
  result.api.update({selection: mutableSelection, stage: 1, language: 'en'});
  assert.equal(frame.parent, null, 'reused caller objects cannot hide a project switch');
  assert.equal(frameOf(section).src, boundB.url);
  result.api.update({selection: selection(projectA), stage: 1, language: 'en'});
  result.api.update({selection: selection(projectA), stage: 1, language: 'zh-Hant'});
  assert.match(section.textContent, /已保存的 Stage1 交付 · 唯讀/);
  assert.equal(frameOf(section).src, boundA.url);
  result.api.update({selection: selection(projectA), stage: 1, language: 'zh-Hans'});
  assert.match(section.textContent, /已保存的 Stage1 交付 · 只读/);
  assert.equal(frameOf(section).src, boundA.url);
  frame = frameOf(section);
  result.api.update({selection: selection(projectB), stage: 1, language: 'en'});
  assert.equal(frame.parent, null, 'switching projects removes the old iframe');
  assert.equal(frameOf(section).src, boundB.url, 'matching uses project_ref, not the shared project_id');
  frame.onload();
  assert.equal(frameOf(section).src, boundB.url, 'a late old load cannot restore another project');
  frame = frameOf(section);
  result.api.update({selection: selection('project-' + '3'.repeat(32)), stage: 1, language: 'en'});
  assert.equal(section.hidden, true);
  assert.equal(frame.parent, null);
  assert.equal(frameOf(section), undefined, 'unknown projects do not fall back to legacy material');
  result.api.update({selection: selection(projectA), stage: 2, language: 'en'});
  assert.equal(section.hidden, true);
  assert.equal(frameOf(section), undefined, 'the Stage1 material frame is absent on Stage2');
  result.api.update({selection: {...selection(projectA), input_version: 7}, stage: 1, language: 'en'});
  assert.equal(frameOf(section), undefined, 'wrong typed versions cannot reuse the saved material');
  result.api.update({selection: null, stage: 1, language: 'en'});
  assert.equal(section.hidden, false, 'unselected legacy references remain available');
}

{
  const secondA = {...boundA, ref: 'saved_A_second', label: 'Second same-project source',
    url: '/project-stage1-saved/saved_A_second/index.html'};
  const result = run({kind: 'SavedStage1References', schema_version: '1.0.0', views: [boundA, secondA, boundB]});
  result.api.mount({anchor: result.anchor});
  const section = sectionOf(result);
  result.api.update({selection: selection(projectA), stage: 1, language: 'en'});
  const select = flatten(section).find(node => node.tag === 'select');
  assert.deepEqual(select.children.map(node => node.value), ['', boundA.ref, secondA.ref]);
  select.value = secondA.ref;
  select.onchange();
  assert.equal(frameOf(section).src, secondA.url);
  result.api.update({selection: selection(projectA), stage: 1, language: 'zh-Hant'});
  assert.equal(frameOf(section).src, secondA.url, 'language changes retain the current matching material');
  result.api.update({selection: selection(projectB), stage: 1, language: 'en'});
  assert.equal(frameOf(section).src, boundB.url);
  select.value = boundA.ref;
  select.onchange();
  assert.equal(frameOf(section).src, boundB.url, 'detached controls cannot select a foreign project row');
}

for (const invalid of [
  {project_ref: projectA},
  {project_input_sha256: hash('d')},
  {binding_origin: 'trusted-host-stage1-view-binding'},
  {project_ref: projectA, project_input_sha256: hash('d')},
  {project_ref: projectA, binding_origin: 'trusted-host-stage1-view-binding'},
  {project_ref: projectA, project_input_sha256: 'bad', binding_origin: 'trusted-host-stage1-view-binding'},
  {project_ref: 'project-' + 'A'.repeat(32), project_input_sha256: hash('d'), binding_origin: 'trusted-host-stage1-view-binding'},
  {project_ref: projectA, project_input_sha256: hash('d'), binding_origin: 'client-guessed'},
  {project_ref: null, project_input_sha256: hash('d'), binding_origin: 'trusted-host-stage1-view-binding'}
]) {
  const result = run({kind: 'SavedStage1References', schema_version: '1.0.0', views: [{...row, ...invalid}]});
  result.api.mount({anchor: result.anchor});
  assert.equal(frameOf(sectionOf(result)), undefined, 'malformed mapping is refused even without an active project');
  result.api.update({selection: selection(projectA), stage: 1, language: 'en'});
  assert.equal(frameOf(sectionOf(result)), undefined, 'partial or malformed trusted mapping cannot display material');
}

{
  const numericString = {...boundA, input_version: '7'};
  const result = run({kind: 'SavedStage1References', schema_version: '1.0.0', views: [numericString]});
  result.api.mount({anchor: result.anchor});
  result.api.update({selection: {project_ref: projectA, input_version: 7}, stage: 1, language: 'en'});
  assert.equal(frameOf(sectionOf(result)), undefined, 'numeric string and integer versions stay distinct');
  result.api.update({selection: {project_ref: projectA, input_version: '7'}, stage: 1, language: 'en'});
  assert.equal(frameOf(sectionOf(result)).src, boundA.url);
}

console.log('project saved Stage1 view VM checks: passed');
require('./test_project_operations_browser.cjs');
