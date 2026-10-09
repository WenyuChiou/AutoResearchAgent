"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");
const plugin = path.resolve(__dirname, ".."), atlas = path.join(plugin, "references/research-workspace/atlas");
const ui = fs.readFileSync(process.argv[2] || path.join(atlas, "atlas-ui.js"), "utf8");
const host = fs.readFileSync(path.join(plugin, "cli/research_workspace_native/web/atlas-host.js"), "utf8");
const model = require(path.join(atlas, "atlas-model.js"));
const flatten = node => node.children.flatMap(child => [child, ...flatten(child)]);
class Element {
  constructor(tag) {
    this.tagName = tag; this.children = []; this.dataset = {}; this.attributes = {}; this.listeners = {};
    this.style = {setProperty() {}}; this.className = ""; this._text = "";
    this.classList = {add: name => { this.className += " " + name; }};
  }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(node => node.textContent).join(" "); }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this._text = ""; this.children = [...nodes]; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  addEventListener(name, handler) { (this.listeners[name] ||= []).push(handler); }
  set onchange(handler) {
    this._onchange = handler;
    if (!this._changeEntry) { this._changeEntry = {property: true}; (this.listeners.change ||= []).push(this._changeEntry); }
  }
  get onchange() { return this._onchange; }
  change(value) {
    this.value = value;
    for (const handler of this.listeners.change || []) (handler.property ? this._onchange : handler)({target: this});
  }
  querySelector(selector) {
    return flatten(this).find(node => selector === "span" ? node.tagName === "span" : selector === "details" ? node.tagName === "details" : selector === 'option[value="relevance"]' ? node.tagName === "option" && node.value === "relevance" : false);
  }
  scrollIntoView() {}
  focus() {}
}
let checks = 0;
const equal = (actual, expected, note) => { checks++; assert.equal(actual, expected, note); };
const contains = (actual, expected, note) => { checks++; assert(actual.includes(expected), note); };
const labels = {
  en: ["Literature knowledge network", "Compare evidence, explore directions", "Project files", "Codex & feedback"],
  "zh-Hans": ["文献知识网络", "比较文献，探索研究方向", "项目文件", "Codex 与反馈"],
  "zh-Hant": ["文獻知識網絡", "比較文獻，探索研究方向", "專案檔案", "Codex 與回饋"]
};
function runCase(initial, hostFirst) {
  const body = new Element("body"), ids = {};
  for (const id of ["atlas-content", "atlas-stages", "atlas-language-label", "atlas-language", "atlas-original", "atlas-project", "atlas-status", "atlas-footer", "atlas-view-files"]) {
    const node = new Element(id === "atlas-language" ? "select" : "div"); node.id = id; ids[id] = node; body.append(node);
  }
  ids["atlas-view-files"].append(new Element("span")); ids["atlas-language"].value = initial;
  const document = {
    body, documentElement: {lang: "en", dataset: {}},
    getElementById: id => ids[id] || flatten(body).find(node => node.id === id),
    createElement: tag => new Element(tag),
    createElementNS: (namespace, tag) => { const node = new Element(tag); node.namespaceURI = namespace; return node; },
    querySelectorAll: () => flatten(body).filter(node => node.dataset.atlasLabel)
  };
  const payload = {index: {topic: "Original English topic", papers: [{work_id: "fixture", version_id: "v1", title: "Original English title", source_ids: []}], stages: [], screening: [], sources: [], claims: []}, index_sha256: "1".repeat(64)};
  const before = JSON.stringify(payload);
  const window = {WORKSPACE_VIEW: payload, AtlasModel: model, innerWidth: 1200, WORKSPACE_HOST: {cases: [], current_case: "fixture", maintenance_enabled: false, connection: {status: "not-checked"}}};
  const context = vm.createContext({window, document, location: {origin: "http://127.0.0.1", href: "http://127.0.0.1/atlas.html"}, URL, sessionStorage: {getItem: () => null}});
  if (hostFirst) vm.runInContext(host, context);
  vm.runInContext(ui, context);
  if (!hostFirst) vm.runInContext(host, context);
  const check = (language, stage) => {
    equal(ids["atlas-language"].value, language, "selector is normalized and synchronized");
    equal(document.documentElement.lang, language, "document language matches selected language");
    const heading = flatten(ids["atlas-content"]).find(node => node.tagName === "h1");
    equal(heading.textContent, labels[language][stage - 1], "stage heading follows selection");
    contains(body.textContent, labels[language][stage - 1], "body follows selection");
    equal(ids["atlas-view-files"].querySelector("span").textContent, labels[language][2], "navigation follows selection");
    equal(document.getElementById("host-open").textContent, labels[language][3], "host listener remains compatible");
    contains(body.textContent, "Original English topic", "source text remains in its recorded language");
  };
  check(labels[initial] ? initial : "en", 1);
  for (const language of ["en", "zh-Hans", "zh-Hant", "invalid"]) {
    ids["atlas-language"].change(language); check(labels[language] ? language : "en", 1);
  }
  ids["atlas-stages"].children[1].onclick(); check("en", 2);
  ids["atlas-language"].change("zh-Hant"); check("zh-Hant", 2);
  equal(JSON.stringify(payload), before, "view changes cannot alter canonical records");
}
for (const initial of ["zh-Hans", "zh-Hant", "invalid"]) for (const hostFirst of [true, false]) runCase(initial, hostFirst);
console.log(`Atlas language DOM regression: ${checks} assertions passed; synthetic DOM and inert host only.`);
