/* Actual six-stage source with authored DOM; no network, action or native work. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const fixture = JSON.parse(fs.readFileSync(0, 'utf8'));
class Element {
  constructor(tag = 'div') { this.tagName = tag; this.children = []; this.dataset = {}; this.attributes = {}; this.text = ''; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; this.text = ''; }
  get textContent() { return this.text + this.children.map(c => c.textContent).join('\n'); }
  set textContent(value) { this.replaceChildren(); this.text = String(value); }
  set innerHTML(_) { throw Error('Source text must not become HTML'); }
  setAttribute(key, value) { this.attributes[key] = String(value); }
}
const elements = new Map(), events = [], sideEffects = [];
const get = id => { if (!elements.has(id)) elements.set(id, new Element()); return elements.get(id); };
const deny = () => { sideEffects.push('forbidden'); throw Error('Presentation attempted an effect'); };
const window = {RESEARCH_PROJECTS: {stage2_selection_projects: [fixture.project.project_ref]}, dispatchEvent: event => events.push(event)};
const document = {getElementById: get, createElement: tag => new Element(tag), querySelectorAll: () => [], addEventListener() {}};
vm.runInNewContext(fs.readFileSync(path.resolve(__dirname, '../../cli/research_workspace_native/web/projects-stages.js'), 'utf8'), {
  document, window, CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options.detail; } },
  fetch: deny, XMLHttpRequest: deny, WebSocket: deny, setTimeout: deny, localStorage: {getItem: deny, setItem: deny}
});
const clone = value => JSON.parse(JSON.stringify(value));
const render = (project = fixture.project, contract = fixture.contract, language = 'en') => window.ResearchProjectStages.render({project, contract, language});
const descendants = node => node.children.flatMap(child => [child, ...descendants(child)]);
const links = () => descendants(get('project-stage-2-result-state')).filter(n => n.tagName === 'a');
let refused = 0;
for (const language of ['en', 'zh-Hant', 'zh-Hans']) {
  render(fixture.project, fixture.contract, language);
  assert(get('project-stage-2-status').textContent.includes('retained-current-marker'));
  assert.equal(links().length, 1, 'current typed version exposes the configured selection entry');
  assert.equal(links()[0].href, '/project-stage2-selection.html#' + fixture.project.project_ref);
  window.ResearchProjectStages.showStage(2);
  assert.equal(events.at(-1).detail.input_version, fixture.project.input_version);
  assert.equal(typeof events.at(-1).detail.input_version, typeof fixture.project.input_version);
  assert.equal(events.at(-1).detail.project_ref, fixture.project.project_ref);
  for (const mutate of [
    c => { c.schema_version = c.schema_version === '1.0.0' ? '1.1.0' : '1.0.0'; },
    c => { c.identity.input_version = typeof fixture.project.input_version === 'string' ? 1 : '1'; },
    c => { c.stages['2'].input.input_version = typeof fixture.project.input_version === 'string' ? 1 : '1'; },
    c => { c.stages['2'].input.revision++; },
    c => { c.identity.project_ref = 'foreign-project'; },
    c => { c.identity.brief_sha256 = 'b'.repeat(64); }
  ]) {
    const changed = clone(fixture.contract); mutate(changed); render(fixture.project, changed, language);
    assert.equal(links().length, 0, 'stale, foreign or type-mismatched contract retires the entry');
    assert(!get('project-stage-2-status').textContent.includes('retained-current-marker'));
    refused++;
  }
}
for (const value of [0, -1, 1.5, true, null, {}, [], '', ' padded', 'padded ', 'x'.repeat(129), 'x\n', 'x\x7f', '\u0085x', 'x\u0085']) {
  render({...fixture.project, input_version: value});
  assert.equal(links().length, 0, 'malformed version cannot expose saved selection');
  window.ResearchProjectStages.showStage(2);
  assert.deepEqual(JSON.parse(JSON.stringify(events.at(-1).detail)), {stage: 2});
  refused++;
}
render();
window.RESEARCH_PROJECTS.stage2_selection_projects = [];
render();
assert.equal(links().length, 0, 'a valid version does not create an unconfigured selection registration');
window.ResearchProjectStages.clear();
assert.equal(links().length, 0);
assert.equal(sideEffects.length, 0);
console.log(JSON.stringify({kind: 'TypedStageNavigationChecks', languages: 3, refused_contracts: refused, version_type: typeof fixture.project.input_version, version: fixture.project.input_version, side_effects: 0}));
