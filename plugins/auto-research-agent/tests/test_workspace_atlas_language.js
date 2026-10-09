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
function runCase(initial, hostFirst, dense = false, boundaries = false) {
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
  const payload = {index: {topic: "Original English topic", papers: [
    {work_id: "fixture", version_id: "v1", title: "Original English title", source_ids: [], classification: {topic_cluster: "Direction A", method: "Shared original method"}},
    {work_id: "second", version_id: "v1", title: "Second original title", source_ids: [], classification: {topic_cluster: "Direction B", method: "Shared original method"}},
  ], stages: [], screening: [], sources: [], claims: []}, index_sha256: "1".repeat(64)};
  if (dense) for (let i = 0; i < 28; i++) payload.index.papers.push({work_id: `extra-${i}`, version_id: "v1", title: `Retained paper ${i}`, source_ids: [], classification: {topic_cluster: "Direction A", method: "Shared original method"}});
  if (boundaries) {
    payload.index.papers[0].classification.method = ["Shared original method", "Unique recorded method"];
    payload.index.papers.push({work_id: "unclassified", version_id: "v2", title: "Unclassified retained title", source_ids: [], classification: {topic_cluster: "Unknown", method: "Unknown"}});
  }
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
  if (boundaries) {
    const resetLabel = {en: "Reset network", "zh-Hans": "返回全图", "zh-Hant": "返回全圖"}[initial];
    flatten(ids["atlas-content"]).find(node => node.tagName === "button" && node.textContent === resetLabel).onclick();
  }
  const graphNodes = () => flatten(ids["atlas-content"]).filter(node => node.className.includes("atlas-node"));
  const lineKinds = () => flatten(ids["atlas-content"]).filter(node => node.tagName === "line").map(node => node.dataset.kind);
  const count = graphNodes().length;
  const coordinates = () => JSON.stringify(graphNodes().filter(node => node.className.includes("atlas-paper-node")).map(node => [node.dataset.nodeKey, node.style.left, node.style.top]));
  const originalCoordinates = coordinates();
  if (boundaries) {
    const shared = () => graphNodes().find(node => node.dataset.nodeKey === "method:Shared original method");
    const unique = () => graphNodes().find(node => node.dataset.nodeKey === "method:Unique recorded method");
    const firstPaper = () => graphNodes().find(node => node.dataset.nodeKey === 'paper:["fixture","v1"]');
    const otherPaper = () => graphNodes().find(node => node.dataset.nodeKey === 'paper:["second","v1"]');
    const unclassified = () => graphNodes().find(node => node.dataset.nodeKey === "topic:");
    const mainDetails = () => flatten(ids["atlas-content"]).find(node => node.className.includes("atlas-detail-panel"));
    const sharedPosition = [shared().style.left, shared().style.top].join("/");
    equal(Boolean(unique()), false, "unfocused singleton is not represented as a shared method hub");
    flatten(ids["atlas-content"]).find(node => node.tagName === "button" && node.textContent === "Unique recorded method · 1").onclick();
    equal(Boolean(unique()), true, "explicitly focused singleton is drawn beside existing shared hubs");
    equal(unique().attributes["aria-pressed"], "true", "focused singleton retains its exact method identity");
    equal([shared().style.left, shared().style.top].join("/"), sharedPosition, "appending a focused singleton cannot move the shared hub");
    equal(coordinates(), originalCoordinates, "focusing a singleton cannot reposition the whole paper network");
    equal(firstPaper().dataset.muted, "false", "singleton method links only its recorded member paper");
    equal(otherPaper().dataset.muted, "true", "other papers are not inferred to share a singleton method");
    contains(mainDetails().textContent, "Original English title", "singleton details retain the matching paper");
    unique().onclick();
    equal(Boolean(unique()), false, "repeated singleton click clears the extra focused hub");
    equal(coordinates(), originalCoordinates, "clearing a singleton restores the same paper coordinates");
    unclassified().onclick();
    equal(unclassified().attributes["aria-pressed"], "true", "unclassified category can receive graph focus");
    contains(mainDetails().textContent, "Unclassified retained title", "unclassified focus opens its retained paper instead of an empty list");
    equal(mainDetails().textContent.includes("Original English title"), false, "classified records are excluded from the unclassified detail list");
    equal(coordinates(), originalCoordinates, "unclassified focus cannot replace or reposition the main graph");
    unclassified().onclick();
    equal(unclassified().attributes["aria-pressed"], undefined, "repeated unclassified click clears focus");
    equal(graphNodes().length, count, "clearing boundary focus restores all initial graph nodes");
    equal(coordinates(), originalCoordinates, "boundary reset keeps exact paper positions");
    equal(document.getElementById("atlas-process").open, false, "boundary navigation leaves process history collapsed");
    equal(JSON.stringify(payload), before, "boundary navigation cannot change literal methods or Unknown source tags");
    return;
  }
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
  equal(coordinates(), originalCoordinates, "category selection keeps the v6 whole-canvas geometry");
  equal(topicNode().attributes["aria-pressed"], "true", "clicked category has focus");
  topicNode().onclick();
  equal(graphNodes().length, count, "clicking the same category restores the complete graph");
  equal(topicNode().attributes["aria-pressed"], undefined, "same-category click clears focus");
  const categoryCard = () => flatten(ids["atlas-content"]).find(node => node.className === "atlas-topic-card" && node.textContent.includes("Direction A"));
  categoryCard().onclick(); equal(graphNodes().length, count, "summary selection must preserve the complete main graph");
  equal(topicNode().attributes["aria-pressed"], "true", "summary category highlights the matching graph node");
  const summary = document.getElementById("atlas-direction-summary");
  contains(summary.textContent, "Original English title", "summary has its own short paper list");
  const paperNode = () => graphNodes().find(node => node.dataset.nodeKey === 'paper:["fixture","v1"]');
  paperNode().onclick(); equal(paperNode().attributes["aria-pressed"], "true", "paper click opens its own details");
  equal(coordinates(), originalCoordinates, "paper selection preserves all graph positions");
  const toggle = () => flatten(ids["atlas-content"]).find(node => node.tagName === "input" && node.type === "checkbox");
  toggle().checked = true; toggle().onchange();
  equal(coordinates(), originalCoordinates, "similarity overlays the v6 network rather than selecting a local layout");
  equal(graphNodes().length, count, "similarity does not remove direction or method nodes");
  equal(lineKinds().includes("similarity"), true, "global similarity uses its own edge class");
  const mainTitle = () => flatten(ids["atlas-content"]).find(node => node.className.includes("atlas-detail-panel")).textContent;
  const selectedDetail = mainTitle();
  flatten(ids["atlas-content"]).find(node => node.className === "atlas-topic-card" && node.textContent.includes("Direction B")).onclick();
  equal(mainTitle(), selectedDetail, "direction summary cannot replace the selected main paper details");
  const summaryPaper = () => flatten(ids["atlas-content"]).find(node => node.dataset.summaryPaper === '["second","v1"]');
  summaryPaper().onclick(); equal(summaryPaper().attributes["aria-pressed"], "true", "summary paper toggles its own compact preview");
  equal(graphNodes().find(node => node.dataset.nodeKey === 'paper:["second","v1"]').attributes["aria-pressed"], "true", "summary paper highlights its exact graph node");
  equal(mainTitle(), selectedDetail, "summary paper highlighting preserves the independent main detail");
  equal(coordinates(), originalCoordinates, "summary paper highlighting does not rearrange the network");
  summaryPaper().onclick(); equal(summaryPaper().attributes["aria-pressed"], "false", "summary preview can be closed locally");
  toggle().checked = false; toggle().onchange();
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
}
for (const initial of ["zh-Hans", "zh-Hant", "invalid"]) for (const hostFirst of [true, false]) runCase(initial, hostFirst);
runCase("en", false, true);
for (const language of ["en", "zh-Hans", "zh-Hant"]) runCase(language, false, false, true);
console.log(`Atlas language DOM regression: ${checks} assertions passed; synthetic DOM and inert host only.`);
