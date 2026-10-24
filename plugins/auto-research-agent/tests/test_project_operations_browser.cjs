/* Actual operations/saved-view scripts in bounded authored DOM. The broker's
 * navigation is injected; this is not a real browser or native execution test. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const web = path.resolve(__dirname, '../cli/research_workspace_native/web');
const scripts = ['project-saved-views.js', 'project-operations.js'].map(name => [name, fs.readFileSync(path.join(web, name), 'utf8')]);
const projectRef = 'project-' + '1'.repeat(32), brief = 'b'.repeat(64);
const version = '20261009-A03';
const material = {
  ref: 'saved_original30', label: 'Original 30 saved material', project_id: 'original30', input_version: version,
  index_sha256: 'a'.repeat(64), manifest_sha256: 'c'.repeat(64), html_sha256: 'd'.repeat(64),
  url: '/project-stage1-saved/saved_original30/index.html', fixture: false, read_only: true,
  accepted: false, execution_authorized: false, project_ref: projectRef,
  project_input_sha256: 'e'.repeat(64), binding_origin: 'trusted-host-stage1-view-binding'
};

class Element {
  constructor(tag) {
    this.tag = tag; this.tagName = tag.toUpperCase(); this.children = []; this.parent = null;
    this.attributes = {}; this.dataset = {}; this.style = {}; this.value = ''; this.hidden = false;
    this.disabled = false; this._text = ''; this.events = new Map();
    const classes = new Set();
    this.classList = {contains: name => classes.has(name), add: name => classes.add(name)};
  }
  append(...nodes) { for (const node of nodes) { node.remove(); node.parent = this; this.children.push(node); } }
  prepend(node) { node.remove(); node.parent = this; this.children.unshift(node); }
  before(node) { const i = this.parent.children.indexOf(this); node.remove(); node.parent = this.parent; this.parent.children.splice(i, 0, node); }
  after(node) { const i = this.parent.children.indexOf(this); node.remove(); node.parent = this.parent; this.parent.children.splice(i + 1, 0, node); }
  remove() { if (this.parent) this.parent.children = this.parent.children.filter(node => node !== this); this.parent = null; }
  replaceChildren(...nodes) { for (const node of this.children) node.parent = null; this.children = []; this.append(...nodes); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name] ?? null; }
  set textContent(value) { this._text = String(value); }
  get textContent() { return this._text + this.children.map(node => node.textContent).join(''); }
  addEventListener(type, listener) { const list = this.events.get(type) || []; list.push(listener); this.events.set(type, list); }
  dispatchEvent(event) { for (const listener of this.events.get(event.type) || []) listener(event); }
  querySelectorAll(selector) { return flatten(this).filter(node => selector === '[data-atlas-focus]' ? node.dataset.atlasFocus : node.tag === selector); }
  closest(selector) { return selector === '[data-atlas-focus]' && this.dataset.atlasFocus ? this : null; }
  get parentElement() { return this.parent; }
  get isConnected() { return this.parent !== null; }
  getBoundingClientRect() { return {height: 320, top: 0}; }
  scrollIntoView() { this.scrolled = true; }
  focus() {}
}
const flatten = node => [node, ...node.children.flatMap(flatten)];
const event = (type, target) => ({type, target, preventDefault() {}, stopImmediatePropagation() {}});
const tick = () => new Promise(resolve => setImmediate(resolve));

async function run({views = [material], inputVersion = version, selectedVersion = inputVersion, bindingOverride,
  loadingOutcome = null, allowNewTopic = false, legacySelectionState = false, selectionStateOverride} = {}) {
  const body = new Element('body'), controls = new Element('div'), workspaceNav = new Element('nav');
  const language = new Element('select'); language.id = 'atlas-language'; language.value = 'en';
  const title = new Element('h1'); title.id = 'atlas-project';
  const content = new Element('section'); content.id = 'atlas-content';
  const stages = new Element('nav'); stages.id = 'atlas-stages';
  for (let i = 1; i <= 6; i++) { const button = new Element('button'); button.dataset.atlasFocus = 'stage:' + i; stages.append(button); }
  const bindings = new Element('script'); bindings.id = 'project-saved-view-bindings';
  bindings.textContent = JSON.stringify({kind: 'SavedStage1References', schema_version: '1.0.0', views});
  body.append(language, title, controls, workspaceNav, stages, content, bindings);
  const childBody = new Element('body'), childLanguage = new Element('select'); childLanguage.id = 'language'; childLanguage.value = 'en';
  for (let i = 1; i <= 6; i++) { const panel = new Element('section'); panel.id = 'project-stage-' + i; childBody.append(panel); }
  childBody.append(childLanguage);
  const lookup = (root, id) => flatten(root).find(node => node.id === id) || null;
  const childDocument = {body: childBody, getElementById: id => lookup(childBody, id), addEventListener() {}};
  const childWindow = new Element('window');
  let selected = null, activeStage = 1, selectCalls = 0, newTopicCalls = 0, selectionStatus = 'unselected';
  const nullObservations = [];
  const listed = {project_ref: projectRef, topic: 'Original saved project', input_version: inputVersion};
  const api = {
    async listProjects() { return [{...listed}]; },
    selection() { return selected && {...selected}; },
    selectionState() {
      return selectionStateOverride === undefined
        ? {kind: 'HarnessUiProjectSelectionState', schema_version: '1.0.0', status: selected ? 'selected' : selectionStatus}
        : selectionStateOverride;
    },
    async selectProject(ref) {
      assert.equal(ref, projectRef); selectCalls++;
      if (loadingOutcome !== null) {
        // The real broker clears its project and emits this event before GET.
        selected = null; selectionStatus = 'loading';
        childWindow.dispatchEvent(event('research-project-selection'));
        nullObservations.push(lookup(body, 'project-saved-stage1-frame')?.src || null);
        await tick();
        if (loadingOutcome === 'throw' || loadingOutcome === 'refuse') {
          selectionStatus = 'failed'; childWindow.dispatchEvent(event('research-project-selection'));
          if (loadingOutcome === 'throw') throw Error('overview failed');
          return false;
        }
      }
      selected = {...listed, input_version: selectedVersion, revision: 2, brief_sha256: brief};
      childWindow.dispatchEvent(event('research-project-selection'));
      return true;
    },
    beginTopic() {
      if (!allowNewTopic) throw Error('new topic forbidden');
      newTopicCalls++; selected = null; selectionStatus = 'unselected';
      childWindow.dispatchEvent(event('research-project-selection'));
      return true;
    },
    activeStage() { return activeStage; },
    showStage(number) { activeStage = number; childWindow.dispatchEvent(event('research-project-stage')); return true; }
  };
  if (legacySelectionState) delete api.selectionState;
  childWindow.ResearchProjectPortal = api;
  const timers = [];
  const forbidden = () => { throw Error('network/storage/action forbidden'); };
  const document = {
    body, getElementById: id => lookup(body, id), addEventListener() {},
    querySelector: selector => selector === '.atlas-topbar-controls' ? controls : selector === '.atlas-workspace-nav' ? workspaceNav : null,
    createElement(tag) {
      const node = new Element(tag);
      if (tag === 'iframe') { node.contentWindow = childWindow; node.contentDocument = childDocument; }
      return node;
    }
  };
  const window = {document, location: {origin: 'http://127.0.0.1'}, scrollTo() {}, scrollY: 0};
  const sandbox = {window, document, URL, TextEncoder, Event: class {constructor(type) {this.type = type;}},
    setTimeout: callback => timers.push(callback), requestAnimationFrame: callback => callback(),
    fetch: forbidden, XMLHttpRequest: forbidden, WebSocket: forbidden,
    localStorage: new Proxy({}, {get: forbidden, set: forbidden})};
  const context = vm.createContext(sandbox);
  for (const [name, source] of scripts) {
    if (name === 'project-operations.js' && bindingOverride !== undefined) {
      window.ResearchSavedStage1Views = {...window.ResearchSavedStage1Views, projectInputBinding: () => bindingOverride};
    }
    vm.runInContext(source, context, {filename: name});
  }
  const frame = document.getElementById('project-operations-frame'); assert(frame); frame.onload();
  for (let i = 0; i < 4; i++) { while (timers.length) timers.shift()(); await tick(); }
  return {document, language, stages, api, nullObservations, selectedCalls: () => selectCalls,
    newTopicCalls: () => newTopicCalls,
    setLoadingOutcome(value) { loadingOutcome = value; },
    async refresh() { await document.getElementById('project-intake-refresh').onclick(); await tick(); },
    async newTopic() {
      document.getElementById('project-intake-topic').value = 'An explicitly prepared new topic';
      await document.getElementById('project-intake-new').onclick(); await tick();
    },
    async choose() {
      const choice = document.getElementById('project-intake-choice'); choice.value = projectRef;
      await document.getElementById('project-intake-select').onclick(); await tick();
    },
    async stage(number) { stages.dispatchEvent(event('click', stages.children[number - 1])); await tick(); await tick(); },
    changeSelection(value) { selected = value; if (value === null) selectionStatus = 'loading'; childWindow.dispatchEvent(event('research-project-selection')); }
  };
}

async function main() {
  {
    const result = await run();
    result.changeSelection(null);
    assert.equal(result.document.getElementById('project-saved-stage1-frame'), null, 'first inner-broker load is not intentional unselected state');
  }
  {
    const result = await run({legacySelectionState: true, loadingOutcome: 'success'});
    await result.choose();
    assert.deepEqual(result.nullObservations, [null], 'legacy broker null remains held during explicit project opening');
    assert.equal(result.document.getElementById('project-saved-stage1-frame').src, material.url);
  }
  for (const phase of [null, {}, {kind: 'HarnessUiProjectSelectionState', schema_version: '9.0.0', status: 'selected'},
    {kind: 'HarnessUiProjectSelectionState', schema_version: '1.0.0', status: 'unselected'},
    {kind: 'HarnessUiProjectSelectionState', schema_version: '1.0.0', status: 'unknown'}]) {
    const result = await run({selectionStateOverride: phase}); await result.choose();
    assert.equal(result.document.getElementById('project-saved-stage1-frame'), null, 'malformed or inconsistent broker state refuses material');
  }
  for (const loadingOutcome of ['success', 'throw', 'refuse']) {
    const result = await run({loadingOutcome, allowNewTopic: true});
    await result.choose();
    assert.deepEqual(result.nullObservations, [null], 'pending broker null must suppress unselected material before overview');
    if (loadingOutcome === 'success') {
      assert.equal(result.document.getElementById('project-saved-stage1-frame').src, material.url);
    } else {
      assert.equal(result.document.getElementById('project-saved-stage1-frame'), null, 'failed navigation retains suppression');
      result.changeSelection(null);
      await result.refresh();
      for (const lang of ['zh-Hant', 'zh-Hans', 'en']) {
        result.language.value = lang; result.language.dispatchEvent(event('change'));
        assert.equal(result.document.getElementById('project-saved-stage1-frame'), null, 'late null, refresh and language cannot reopen fallback');
      }
      assert.equal(result.selectedCalls(), 1, 'failed navigation is never automatically resent');
      assert.equal(result.newTopicCalls(), 0, 'failure does not implicitly prepare a new topic');
      result.setLoadingOutcome('success'); await result.choose();
      assert.equal(result.document.getElementById('project-saved-stage1-frame').src, material.url, 'explicit valid selection recovers');
    }
    result.changeSelection(null);
    assert.equal(result.document.getElementById('project-saved-stage1-frame'), null, 'unexpected broker null after a bound project stays suppressed');
    await result.newTopic();
    assert.equal(result.newTopicCalls(), 1);
    assert.equal(result.document.getElementById('project-saved-stage1-frame').src, material.url, 'only explicit successful new-topic navigation restores unselected references');
  }
  {
    const result = await run();
    const {document} = result;
    assert.equal(document.getElementById('project-intake-choice').children.length, 2, 'trusted string input appears in the real selector');
    await result.choose();
    assert.equal(result.selectedCalls(), 1);
    assert.match(document.getElementById('project-intake-summary').textContent, /20261009-A03/);
    assert.equal(document.getElementById('project-saved-stage1-frame').src, material.url);
    await result.stage(2);
    assert.equal(document.getElementById('project-saved-stage1-frame'), null, 'Stage2 navigation clears the Stage1 frame');
    await result.stage(1);
    assert.equal(document.getElementById('project-saved-stage1-frame').src, material.url);
    assert.equal(document.getElementById('project-saved-stage1').scrolled, true, 'Stage1 navigation reaches the same-project material');
    for (const lang of ['zh-Hant', 'zh-Hans', 'en']) {
      result.language.value = lang; result.language.dispatchEvent(event('change'));
      assert.equal(document.getElementById('project-saved-stage1-frame').src, material.url);
    }
    result.changeSelection({project_ref: projectRef, topic: 'stale', input_version: 'old', revision: 1, brief_sha256: brief});
    assert.equal(document.getElementById('project-saved-stage1-frame'), null, 'stale string version refuses without falling back to unselected material');
  }
  {
    const result = await run({views: [], inputVersion: 1}); await result.choose();
    assert.match(result.document.getElementById('project-intake-summary').textContent, /Input version 1/);
  }
  {
    const result = await run({views: [], inputVersion: 1, selectedVersion: 2}); await result.choose();
    assert.match(result.document.getElementById('project-intake-summary').textContent, /Input version 2/, 'legacy integer revisions retain their existing broker behavior');
  }
  for (const options of [
    {views: []},
    {views: [{...material, binding_origin: 'guessed'}]},
    {views: [{...material, input_version: 'other'}]},
    {views: [{...material, project_ref: 'project-' + '2'.repeat(32)}]}
  ]) {
    const result = await run(options);
    assert.equal(result.document.getElementById('project-intake-choice').children.length, 1, 'unversioned/foreign/stale string inputs stay unavailable');
    assert.equal(result.document.getElementById('project-intake-select').disabled, true);
  }
  {
    const result = await run({selectedVersion: 7}); await result.choose();
    assert.doesNotMatch(result.document.getElementById('project-intake-summary').textContent, /Current project:/, 'the returned selection must match the listed typed version');
  }
  const profile = {kind: 'SavedStage1ProjectInputBinding', schema_version: '1.0.0', project_ref: projectRef,
    input_version: version, project_input_sha256: 'e'.repeat(64), execution_authorized: false};
  for (const override of [null, {}, {...profile, schema_version: '2.0.0'}, {...profile, project_input_sha256: 'unknown'},
    {...profile, execution_authorized: true}, {...profile, input_version: 7}, {...profile, project_ref: 'foreign'}]) {
    const result = await run({bindingOverride: override});
    assert.equal(result.document.getElementById('project-intake-choice').children.length, 1, 'unknown or mismatched input profiles cannot widen the legacy schema');
  }
  console.log('project operations typed saved-input DOM checks: passed');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
