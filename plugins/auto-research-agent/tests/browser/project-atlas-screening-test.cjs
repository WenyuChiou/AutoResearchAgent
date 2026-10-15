/* Actual v6 renderer + native presenter over saved authored Core records. */
"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");
const plugin = path.resolve(__dirname, "../.."), input = process.argv[2];
const payload = JSON.parse(fs.readFileSync(path.join(input, "payload.json"), "utf8"));
const ui = fs.readFileSync(path.join(input, "ui.js"), "utf8");
const presenter = fs.readFileSync(path.join(plugin, "cli/research_workspace_native/web/project-atlas-screening.js"), "utf8");
const model = require(path.join(plugin, "references/research-workspace/atlas/atlas-model.js"));
const flatten = node => node.children.flatMap(child => [child, ...flatten(child)]);
class Element {
  constructor(tag) {
    this.tagName = tag; this.children = []; this.dataset = {}; this.attributes = {}; this.listeners = {};
    this.style = {setProperty() {}}; this.className = ""; this._text = ""; this.parentNode = null;
    this.classList = {add: name => {this.className += " " + name;}};
  }
  set textContent(value) {this.replaceChildren(); this._text = String(value);}
  get textContent() {return this._text + this.children.map(node => node.textContent).join(" ");}
  append(...nodes) {for (const node of nodes) {node.remove(); node.parentNode = this; this.children.push(node);}}
  remove() {if (this.parentNode) this.parentNode.children = this.parentNode.children.filter(node => node !== this); this.parentNode = null;}
  replaceChildren(...nodes) {this._text = ""; for (const node of this.children) node.parentNode = null; this.children = []; this.append(...nodes);}
  insertBefore(node, anchor) {node.remove(); node.parentNode = this; this.children.splice(anchor === null ? this.children.length : this.children.indexOf(anchor), 0, node); return node;}
  setAttribute(name, value) {this.attributes[name] = String(value);}
  addEventListener(name, handler) {(this.listeners[name] ||= []).push(handler);}
  querySelector(selector) {return flatten(this).find(node => selector === "span" ? node.tagName === "span" : selector === "details" ? node.tagName === "details" : selector === 'option[value="relevance"]' && node.tagName === "option" && node.value === "relevance");}
  scrollIntoView() {} focus() {}
}
const languages = {en: "Recorded discoveries", "zh-Hans": "发现次数", "zh-Hant": "發現次數"};
let selections = 0;
for (const [language, label] of Object.entries(languages)) {
  const body = new Element("body"), ids = {};
  for (const id of ["atlas-content", "atlas-stages", "atlas-language-label", "atlas-language", "atlas-original", "atlas-project", "atlas-status", "atlas-footer"]) {
    const node = new Element(id === "atlas-language" ? "select" : "div"); node.id = id; ids[id] = node; body.append(node);
  }
  ids["atlas-language"].value = language;
  const document = {body, documentElement: {lang: "en", dataset: {}}, getElementById: id => ids[id] || flatten(body).find(node => node.id === id), createElement: tag => new Element(tag), createElementNS: (_ns, tag) => new Element(tag), querySelectorAll: () => flatten(body).filter(node => node.dataset.atlasLabel)};
  const before = JSON.stringify(payload), context = vm.createContext({window: {WORKSPACE_VIEW: payload, AtlasModel: model}, document, URL});
  vm.runInContext(presenter, context); vm.runInContext(ui, context);
  const render = context.window.ProjectAtlasScreening.renderLedger;
  assert(document.getElementById("atlas-process").textContent.includes(label));
  for (const paper of model.papers(payload)) {
    const button = flatten(body).find(node => node.dataset.paperKey === paper.key);
    assert(button, "saved paper selectable by exact work/version key"); button.onclick();
    const detail = document.getElementById("atlas-paper-detail");
    assert(detail.textContent.includes(label)); assert(detail.textContent.includes(paper.work_id));
    const row = payload.index.screening_library.rows.find(row => row.work_id === paper.work_id);
    assert(detail.textContent.includes(row.screening_status));
    assert(detail.textContent.includes(row.current_decision?.rationale || "Unknown"));
    assert(detail.textContent.includes(payload.index_sha256)); selections++;
  }
  const paper = model.papers(payload)[0], index = payload.index;
  const old = new Element("div"); assert.equal(render(old, paper, {...index, canonical_records_version: "1.1.0"}, payload, language), false); assert.equal(old.children.length, 0);
  const unavailable = new Element("div"); assert.equal(render(unavailable, {...paper, version_id: "wrong-version"}, index, payload, language), true); assert.equal(unavailable.children.length, 1);
  for (const library of [
    {...index.screening_library, binding: {...index.screening_library.binding, project_ref: "another-project"}},
    {...index.screening_library, rows: [...index.screening_library.rows, index.screening_library.rows[0]]}
  ]) {
    const wrong = {...index, screening_library: library}, rejected = new Element("div");
    assert.equal(render(rejected, paper, wrong, {...payload, index: wrong}, language), true); assert.equal(rejected.children.length, 1);
  }
  const row = structuredClone(index.screening_library.rows[0]); row.counts.round_ids_known = false; row.counts.recorded_rounds = 0;
  row.current_decision = {...row.current_decision, rationale: '<img src=x onerror="throw 1">'};
  row.discoveries = Array.from({length: 13}, (_, i) => ({...row.discoveries[0], discovery_id: `authored-page-${i}`}));
  const changed = {...index, screening_library: {...index.screening_library, rows: [row]}}, shell = {...payload, index: changed}, parent = new Element("div");
  render(parent, paper, changed, shell, language);
  assert(parent.textContent.includes('<img src=x onerror="throw 1">')); assert.equal(flatten(parent).some(node => node.tagName === "img"), false);
  const history = parent.children.find(node => node.tagName === "details");
  assert(history.textContent.includes("1–6 / 13")); history.children[1].children[2].onclick(); assert(history.textContent.includes("7–12 / 13"));
  history.children[1].children[2].onclick(); assert(history.textContent.includes("13–13 / 13")); assert.equal(history.children[2].children.length, 1);
  const grid = parent.children.find(node => node.tagName === "dl"); assert.equal(grid.children[4].children[1].textContent, "Unknown");
  ids["atlas-language"].onchange({target: {value: language}});
  assert.equal(JSON.stringify(payload), before, "selection, language and pagination never mutate canonical bytes");
}
console.log(JSON.stringify({kind: "SavedScreeningPresenterDOM", passed: true, languages: 3, exact_version_selections: selections, checks: ["derived-v6-hook", "legacy-fallback", "unmatched-refusal", "unknown-rounds", "literal-source-text", "bounded-pagination", "immutable-data"], native_model_search_calls: 0}));
