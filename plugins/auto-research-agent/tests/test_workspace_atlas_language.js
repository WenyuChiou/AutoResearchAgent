"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");
const plugin = path.resolve(__dirname, ".."), atlas = path.join(plugin, "references/research-workspace/atlas");
const ui = fs.readFileSync(process.argv[2] || path.join(atlas, "atlas-ui.js"), "utf8");
const host = process.argv.includes("--host") ? fs.readFileSync(path.join(plugin, "cli/research_workspace_native/web/atlas-host.js"), "utf8") : null;
const model = require(path.join(atlas, "atlas-model.js"));
const flatten = node => node.children.flatMap(child => [child, ...flatten(child)]);
let activeDocument;
class Element {
  constructor(tag) {
    this.tagName = tag; this.children = []; this.dataset = {}; this.attributes = {}; this.listeners = {};
    this.style = {setProperty() {}}; this.className = ""; this._text = "";
    this.classList = {add: name => { this.className += " " + name; }};
  }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(node => node.textContent).join(" "); }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) {
    if (activeDocument && flatten(this).includes(activeDocument.activeElement)) activeDocument.activeElement = activeDocument.body;
    this._text = ""; this.children = [...nodes];
  }
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
    return flatten(this).find(node => ["span", "details", "h1"].includes(selector) ? node.tagName === selector : selector === 'option[value="relevance"]' ? node.tagName === "option" && node.value === "relevance" : false);
  }
  scrollIntoView() {}
  focus() { activeDocument.activeElement = this; }
}
let checks = 0;
const equal = (actual, expected, note) => { checks++; assert.equal(actual, expected, note); };
const contains = (actual, expected, note) => { checks++; assert(actual.includes(expected), note); };
const labels = {
  en: ["Literature knowledge network", "Compare evidence, explore directions", "Project files", "Codex & feedback"],
  "zh-Hans": ["文献知识网络", "比较文献，探索研究方向", "项目文件", "Codex 与反馈"],
  "zh-Hant": ["文獻知識網絡", "比較文獻，探索研究方向", "專案檔案", "Codex 與回饋"]
};
function runCase(initial, hostFirst, dense = false) {
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
    querySelectorAll: selector => flatten(body).filter(node => selector === "[data-atlas-focus]" ? node.dataset.atlasFocus : node.dataset.atlasLabel)
  };
  activeDocument = document; document.activeElement = body;
  const payload = {index: {topic: "Original English topic", papers: [
    {work_id: "fixture", version_id: "v1", title: "Original English title", source_ids: [], classification: {topic_cluster: "Direction A", method: "Shared original method"}},
    {work_id: "second", version_id: "v1", title: "Second original title", source_ids: [], classification: {topic_cluster: "Direction B", method: "Shared original method"}},
  ], stages: [], screening: [], sources: [], claims: []}, index_sha256: "1".repeat(64)};
  if (dense) for (let i = 0; i < 28; i++) payload.index.papers.push({work_id: `extra-${i}`, version_id: "v1", title: `Retained paper ${i}`, source_ids: [], classification: {topic_cluster: "Direction A", method: "Shared original method"}});
  payload.stage2_comparison = {literature: payload.index.papers.map(row => ({...row, key: model.key(row)}))};
  const before = JSON.stringify(payload);
  const window = {WORKSPACE_VIEW: payload, AtlasModel: model, innerWidth: 1200, WORKSPACE_HOST: {cases: [], current_case: "fixture", maintenance_enabled: false, connection: {status: "not-checked"}}};
  const context = vm.createContext({window, document, location: {origin: "http://127.0.0.1", href: "http://127.0.0.1/atlas.html"}, URL, sessionStorage: {getItem: () => null}});
  if (host && hostFirst) vm.runInContext(host, context);
  vm.runInContext(ui, context);
  if (host && !hostFirst) vm.runInContext(host, context);
  ids["atlas-stages"].children[1].onclick();
  const compare = flatten(ids["atlas-content"]).find(node => ["Compare these papers", "比较这些论文", "比較這些論文"].includes(node.textContent));
  compare.focus(); compare.onclick();
  equal(document.activeElement.tagName, "h1", "cross-tab action focuses the destination heading when its control disappears");
  let comparison = flatten(ids["atlas-content"]).find(node => node.type === "checkbox");
  comparison.focus(); comparison.checked = false; comparison.onchange();
  equal(document.activeElement.dataset.atlasFocus, comparison.dataset.atlasFocus, "comparison checkbox preserves exact version focus");
  ids["atlas-stages"].children[0].onclick();
  ids["atlas-stages"].children[1].focus(); ids["atlas-stages"].children[1].onclick();
  equal(document.activeElement === ids["atlas-stages"].children[1], true, "stage activation preserves keyboard focus on the replacement control");
  ids["atlas-stages"].children[0].onclick();
  equal(flatten(ids["atlas-content"]).filter(node => node.tagName === "svg").every(node => node.attributes.preserveAspectRatio === "none"), true, "SVG edges use the same independent x/y scales as HTML nodes");
  let checkbox = flatten(ids["atlas-content"]).find(node => node.type === "checkbox");
  checkbox.focus(); checkbox.checked = true; checkbox.onchange();
  equal(document.activeElement.type, "checkbox", "similarity change preserves focus");
  const paperControl = flatten(ids["atlas-content"]).find(node => node.dataset.nodeKey?.startsWith("paper:"));
  paperControl.focus(); paperControl.onclick();
  equal(document.activeElement.dataset.nodeKey, paperControl.dataset.nodeKey, "paper activation preserves exact node focus");
  flatten(ids["atlas-content"]).find(node => ["Reset network", "返回全图", "返回全圖"].includes(node.textContent)).onclick();
  ids["atlas-stages"].children[0].onclick();
  if (dense) {
    const next = flatten(ids["atlas-content"]).find(node => node.dataset.atlasFocus === "page:page:1");
    next.focus(); next.onclick();
    equal(document.activeElement.dataset.atlasFocus, "page:page:1", "pagination preserves keyboard focus on its replacement");
  }
  const check = (language, stage) => {
    equal(ids["atlas-language"].value, language, "selector is normalized and synchronized");
    equal(document.documentElement.lang, language, "document language matches selected language");
    const heading = flatten(ids["atlas-content"]).find(node => node.tagName === "h1");
    equal(heading.textContent, labels[language][stage - 1], "stage heading follows selection");
    contains(body.textContent, labels[language][stage - 1], "body follows selection");
    equal(ids["atlas-view-files"].querySelector("span").textContent, labels[language][2], "navigation follows selection");
    if (host) equal(document.getElementById("host-open").textContent, labels[language][3], "host listener remains compatible");
    contains(body.textContent, "Original English topic", "source text remains in its recorded language");
  };
  check(labels[initial] ? initial : "en", 1);
  const graphNodes = () => flatten(ids["atlas-content"]).filter(node => node.className.includes("atlas-node"));
  const lineKinds = () => flatten(ids["atlas-content"]).filter(node => node.tagName === "line").map(node => node.dataset.kind);
  const count = graphNodes().length;
  if (dense) {
    const nodes = graphNodes().filter(node => node.className.includes("atlas-paper-node"));
    equal(nodes.length, 30, "thirty paper versions remain drawn rather than silently truncated");
    equal(new Set(nodes.map(node => `${node.style.left}/${node.style.top}`)).size, 30, "dense direction gives every paper a distinct position");
  }
  equal(document.getElementById("atlas-process").tagName, "details", "process history uses progressive disclosure");
  equal(document.getElementById("atlas-process").open, false, "process history starts closed");
  equal(lineKinds().includes("direction"), true, "direction links retain their type");
  equal(lineKinds().includes("method"), true, "recorded method links retain their distinct type");
  const topicNode = () => graphNodes().find(node => node.dataset.nodeKey === "topic:Direction A");
  topicNode().onclick();
  equal(graphNodes().length, count, "category selection must not replace the network with a subset");
  equal(topicNode().attributes["aria-pressed"], "true", "clicked category has focus");
  topicNode().onclick();
  equal(graphNodes().length, count, "clicking the same category restores the complete graph");
  equal(topicNode().attributes["aria-pressed"], undefined, "same-category click clears focus");
  const categoryCard = () => flatten(ids["atlas-content"]).find(node => node.className === "atlas-topic-card" && node.textContent.includes("Direction A"));
  categoryCard().onclick(); equal(graphNodes().length, count, "category count cards must preserve the whole graph too");
  equal(topicNode().attributes["aria-pressed"], "true", "category count card and graph share one focus");
  categoryCard().onclick(); equal(topicNode().attributes["aria-pressed"], undefined, "same category card clears graph focus");
  const paperNode = () => graphNodes().find(node => node.dataset.nodeKey === 'paper:["fixture","v1"]');
  paperNode().onclick(); equal(paperNode().attributes["aria-pressed"], "true", "paper click opens its own details");
  paperNode().onclick(); equal(paperNode().attributes["aria-pressed"], undefined, "same-paper click clears focus");
  equal(document.getElementById("atlas-process").open, false, "node navigation does not expand process history");
  equal(JSON.stringify(payload), before, "node interactions cannot mutate retained research records");
  for (const language of ["en", "zh-Hans", "zh-Hant", "invalid"]) {
    ids["atlas-language"].change(language); check(labels[language] ? language : "en", 1);
  }
  paperNode().onclick();
  flatten(ids["atlas-content"]).find(node => node.tagName === "button" && node.textContent === "Local network").onclick();
  equal(lineKinds().includes("similarity"), true, "local graph labels computed similarity links separately");
  equal(graphNodes().every(node => node.dataset.nodeKey.startsWith("paper:")), true, "every local paper has an exact identity");
  equal(paperNode().dataset.muted, "false", "local focused paper remains visible");
  paperNode().onpointerenter(); equal(paperNode().dataset.muted, "false", "local hover uses exact paper identity");
  paperNode().onclick(); equal(paperNode().attributes["aria-pressed"], undefined, "same local paper toggles back without library navigation");
  equal(graphNodes().length, count, "same local paper restores the full classified network");
  ids["atlas-stages"].children[1].onclick(); check("en", 2);
  equal(document.getElementById("atlas-process").tagName, "details", "Stage 2 process history also uses progressive disclosure");
  equal(document.getElementById("atlas-process").open, false, "Stage 2 process history starts closed");
  ids["atlas-language"].change("zh-Hant"); check("zh-Hant", 2);
  equal(JSON.stringify(payload), before, "view changes cannot alter canonical records");
  ids["atlas-language"].change("en");
  for (let stage = 3; stage <= 6; stage++) {
    ids["atlas-stages"].children[stage - 1].onclick();
    equal(document.getElementById("atlas-process").dataset.integrationStatus, "planned/unconnected", "later stages expose integration status separately from source contract");
    contains(ids["atlas-content"].textContent, "planned / unconnected", "later stages cannot claim executed research");
  }
}
for (const initial of ["zh-Hans", "zh-Hant", "invalid"]) for (const hostFirst of [true, false]) runCase(initial, hostFirst);
runCase("en", false, true);
console.log(`Atlas language DOM regression: ${checks} assertions passed; synthetic DOM only; host is opt-in.`);
