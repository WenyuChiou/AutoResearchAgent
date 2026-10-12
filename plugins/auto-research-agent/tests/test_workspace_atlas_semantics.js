"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");
const ui = fs.readFileSync(process.argv[2], "utf8"), plugin = path.resolve(process.argv[3]);
const model = require(path.join(plugin, "references/research-workspace/atlas/atlas-model.js"));
const cases = JSON.parse(fs.readFileSync(process.argv[4], "utf8"));
const flatten = node => node.children.flatMap(child => [child, ...flatten(child)]);
class Element {
  constructor(tag) {
    this.tagName = tag; this.children = []; this.dataset = {}; this.attributes = {}; this.listeners = {};
    this.style = {setProperty() {}}; this.className = ""; this._text = ""; this.parentNode = null;
    this.classList = {add: name => { this.className += " " + name; }};
  }
  set textContent(value) { this.replaceChildren(); this._text = String(value); }
  get textContent() { return this._text + this.children.map(node => node.textContent).join(" "); }
  append(...nodes) { for (const node of nodes) { node.remove(); node.parentNode = this; this.children.push(node); } }
  remove() { if (this.parentNode) this.parentNode.children = this.parentNode.children.filter(node => node !== this); this.parentNode = null; }
  replaceChildren(...nodes) { this._text = ""; for (const node of this.children) node.parentNode = null; this.children = []; this.append(...nodes); }
  insertBefore(node, anchor) {
    if (anchor !== null && !this.children.includes(anchor)) throw Error("insertBefore anchor is not a child");
    if (node === anchor) return node;
    node.remove(); node.parentNode = this;
    this.children.splice(anchor === null ? this.children.length : this.children.indexOf(anchor), 0, node);
    return node;
  }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  addEventListener(name, handler) { (this.listeners[name] ||= []).push(handler); }
  querySelector(selector) {
    return flatten(this).find(node => selector === "span" ? node.tagName === "span" : selector === "details" ? node.tagName === "details" : selector === 'option[value="relevance"]' ? node.tagName === "option" && node.value === "relevance" : false);
  }
  scrollIntoView() {}
  focus() {}
}
let checks = 0;
const failures = [];
function check(assertion) { checks++; try { assertion(); } catch (error) { failures.push(error.message); } }
function contains(actual, expected, message) { check(() => assert(actual.includes(expected), message)); }
function excludes(actual, unexpected, message) { check(() => assert(!actual.includes(unexpected), message)); }
function equal(actual, expected, message) { check(() => assert.equal(actual, expected, message)); }
const formerParent = new Element("div"), parent = new Element("div"), moved = new Element("section"), anchor = new Element("section");
formerParent.append(moved); parent.append(anchor); parent.insertBefore(moved, anchor);
check(() => assert.deepEqual(parent.children, [moved, anchor], "insertion reorders by reference"));
equal(formerParent.children.length, 0, "insertion removes the previous parent entry");
equal(moved.parentNode, parent, "insertion updates the parent reference");
parent.insertBefore(moved, null); parent.insertBefore(anchor, anchor);
check(() => assert.deepEqual(parent.children, [anchor, moved], "null appends and self-insertion preserves order without duplicates"));
check(() => assert.throws(() => parent.insertBefore(new Element("div"), formerParent), /anchor is not a child/));
parent.replaceChildren(anchor); equal(moved.parentNode, null, "replacement detaches removed children");
parent.textContent = "reset"; equal(anchor.parentNode, null, "text replacement detaches previous children");
const words = {
  en: {unknown: "Unknown", assessed: "criteria assessed", provisional: "provisional", paper: "Project / paper version / snapshot hash", project: "Project / snapshot hash", audit: "Required audit is pending.", failed: "Technical assessment failed or is incomplete."},
  "zh-Hans": {unknown: "未知", assessed: "已评估判据", provisional: "暂定", paper: "项目／论文版本／快照哈希", project: "项目／快照哈希", audit: "必要覆核待完成。", failed: "技术评估失败或未完成。"},
  "zh-Hant": {unknown: "未知", assessed: "已評估判準", provisional: "暫定", paper: "專案／論文版本／快照雜湊", project: "專案／快照雜湊", audit: "必要覆核待完成。", failed: "技術評估失敗或未完成。"}
};
for (const [caseName, payload] of Object.entries(cases)) for (const language of Object.keys(words)) {
  const body = new Element("body"), ids = {};
  for (const id of ["atlas-content", "atlas-stages", "atlas-language-label", "atlas-language", "atlas-original", "atlas-project", "atlas-status", "atlas-footer"]) {
    const node = new Element(id === "atlas-language" ? "select" : "div"); node.id = id; ids[id] = node; body.append(node);
  }
  ids["atlas-language"].value = language;
  const document = {
    body, documentElement: {lang: "en", dataset: {}},
    getElementById: id => ids[id] || flatten(body).find(node => node.id === id),
    createElement: tag => new Element(tag), createElementNS: (namespace, tag) => new Element(tag),
    querySelectorAll: () => flatten(body).filter(node => node.dataset.atlasLabel)
  };
  const before = JSON.stringify(payload), dictionary = words[language];
  const context = vm.createContext({window: {WORKSPACE_VIEW: payload, AtlasModel: model}, document, URL});
  vm.runInContext(ui, context);
  const process1 = document.getElementById("atlas-process");
  contains(process1.textContent, dictionary.paper, "Stage 1 labels actual paper version, not native input version");
  contains(process1.textContent, payload.index_sha256, "Stage 1 keeps the complete recorded snapshot hash");
  contains(process1.textContent, payload.index.papers[0].version_id, "Stage 1 keeps actual version identity");
  excludes(process1.textContent, "Project / input version / source binding", "No hash is relabeled as input version");
  ids["atlas-stages"].children[1].onclick();
  contains(document.getElementById("atlas-process").textContent, dictionary.project, "Stage 2 labels project and selection snapshot separately from input version");
  const assessment = document.getElementById("atlas-assessment"), chips = flatten(assessment).filter(node => node.className === "atlas-chip");
  equal(chips.length, 3, "P4/P5/P6 remain separate dimensions");
  for (let i = 0; i < 3; i++) {
    const metric = ["P4", "P5", "P6"][i], dimension = payload.stage2.evaluation.dimensions[metric];
    equal(dimension.max, 6, "Raw-point denominator remains six");
    equal(dimension.required, 3, "Assessed-criterion denominator remains three");
    if (caseName === "audit-required") {
      contains(chips[i].textContent, `${metric}: ${dimension.score}% (${dimension.sum}/6)`, "Recorded percent and raw points keep distinct units");
      contains(chips[i].textContent, `3/3 ${dictionary.assessed}`, "Criterion completeness is independent of raw points");
      contains(chips[i].textContent, dictionary.provisional, "Pending named audit keeps every score provisional");
    } else {
      contains(chips[i].textContent, `${metric}: ${dictionary.unknown} (${dictionary.unknown}/6)`, "Failed judging shows unknown raw points with the fixed denominator");
      contains(chips[i].textContent, `0/3 ${dictionary.assessed}`, "Missing R2 prevents completed independent assessment");
      excludes(chips[i].textContent, "0%", "Missing score remains unknown, never zero");
    }
  }
  contains(assessment.textContent, dictionary[caseName === "audit-required" ? "audit" : "failed"], "Audit and technical failure messages remain distinct");
  const original = flatten(assessment).find(node => node.tagName === "pre" && node.textContent.trimStart().startsWith("{") && JSON.parse(node.textContent)?.kind === payload.stage2.kind);
  assert(original, "Complete original assessment is still available"); checks++;
  equal(JSON.stringify(JSON.parse(original.textContent)), JSON.stringify(payload.stage2), "Original attachment and all R1/R2/ADJ comments retain their exact JSON values");
  equal(JSON.stringify(payload), before, "UI rendering does not rewrite canonical research data");
}
assert.equal(failures.length, 0, failures.join("\n"));
console.log(`Atlas semantics DOM regression: ${checks} assertions passed; repository daily-v3 fixtures, no native calls.`);
