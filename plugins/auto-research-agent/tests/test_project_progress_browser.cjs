/* Authored DOM checks. Navigation must never submit or execute research. */
"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");
class Node {
  constructor(tag) {this.tagName = tag.toUpperCase(); this.children = []; this.dataset = {}; this.hidden = false; this.textContent = "";}
  append(child) {child.parentElement = this; this.children.push(child);}
  replaceChildren() {this.children = []; this.textContent = "";}
  setAttribute(name, value) {this[name] = value;}
  scrollIntoView() {this.scrolled = true;}
  focus() {this.focused = true;}
}
const source = path.join(__dirname, "../cli/research_workspace_native/web/projects-progress.js"), nodes = new Map();
for (const [id, tag] of [["stage1-progress", "section"], ["history", "div"], ["coverage-controls", "details"], ["stage1-library", "details"]]) {const node = new Node(tag); node.id = id; nodes.set(id, node);}
let embedded = false; const events = [];
const context = {window: {}, CustomEvent: class {constructor(type, fields) {this.type = type; this.detail = fields.detail;}}, document: {body: {classList: {contains: value => embedded && value === "project-embedded"}}, dispatchEvent: event => events.push(event), createElement: tag => new Node(tag), getElementById: id => nodes.get(id)}, fetch: () => {throw Error("navigation performed I/O");}};
vm.runInNewContext(fs.readFileSync(source, "utf8"), context, {filename: source});
const render = context.window.ResearchStage1Progress.render, area = nodes.get("stage1-progress");
const project = {project_ref: "project-1", revision: 4, input_version: 2, brief_sha256: "a".repeat(64)};
const phaseIds = ["scope", "planning", "query", "screening", "reading", "coverage", "delivery"];
const view = {kind: "ProjectStage1Progress", schema_version: "1.0.0", binding: {...project}, phases: phaseIds.map(phase_id => ({phase_id, status: "recorded"})), next_action: {phase_id: "coverage", target: "coverage", reason: "coverage-required"}, research_complete: false};
const walk = node => [node, ...node.children.flatMap(walk)];
const text = () => walk(area).map(node => node.textContent).join(" ");
const show = more => render({project, view, language: "en", busy: false, loading: false, held: false, ...more});
const nextButton = () => walk(area).find(node => node.className === "progress-next")?.children.find(node => node.tagName === "BUTTON");
for (const [language, title] of [["en", "Current progress"], ["zh-Hans", "当前进度"], ["zh-Hant", "目前進度"]]) {show({language}); assert(text().includes(title)); assert.equal(walk(area).filter(node => node.tagName === "LI").length, 7);}
show(); const next = nextButton(); next.onclick();
assert.equal(nodes.get("coverage-controls").open, true); assert.equal(nodes.get("coverage-controls").focused, true);
show({held: true}); nextButton().onclick(); assert.equal(nodes.get("history").focused, true); assert(text().includes("unconfirmed"));
for (const field of ["project_ref", "revision", "input_version", "brief_sha256"]) {show({view: {...view, binding: {...project, [field]: "stale"}}}); assert(!walk(area).some(node => node.tagName === "BUTTON")); assert(text().includes("Refresh saved state")); assert.equal(area.dataset.projectRef, undefined);}
show({project: {}, view: {...view, binding: {}}}); assert(!walk(area).some(node => node.tagName === "BUTTON"));
show({view: {...view, phases: phaseIds.map(() => null)}}); assert(!walk(area).some(node => node.tagName === "BUTTON"));
show({view: {...view, phases: phaseIds.map(phase_id => ({phase_id, status: "complete"}))}}); assert(!walk(area).some(node => node.tagName === "BUTTON"));
show({view: {...view, next_action: {phase_id: "delivery", target: "delivery", reason: "package-saved-review-required"}}}); assert(text().includes("before accepting the stage")); assert(!text().includes("Research complete"));
for (const [language, instruction] of [["en", "reading notes are saved separately"], ["zh-Hans", "主张与阅读笔记分别保存"], ["zh-Hant", "主張及閱讀筆記分別保存"]]) {
  show({language, view: {...view, next_action: {phase_id: "reading", target: "reading", reason: "reading-registration-required"}}});
  assert(text().includes(instruction)); nextButton().onclick();
  assert.equal(nodes.get("stage1-library").open, true); assert.equal(nodes.get("stage1-library").focused, true);
}
show({busy: true}); assert(walk(area).find(node => node.tagName === "BUTTON").disabled);
show({view: {...view, next_action: {target: "__proto__"}}}); assert.equal(nextButton(), undefined); assert.equal(walk(area).filter(node => node.tagName === "BUTTON").length, 7);
const wrapper = new Node("details"); wrapper.append(nodes.get("coverage-controls"));
embedded = true; show(); nextButton().onclick();
assert.equal(wrapper.open, true); assert.equal(events.length, 1);
assert.equal(events[0].type, "research-project-navigate"); assert.equal(events[0].detail.target, "coverage-controls");
embedded = false; show(); const coveragePhase = walk(area).find(node => node.tagName === "LI" && node.children[0].textContent === "Coverage review"); coveragePhase.children[0].onclick(); assert.equal(nodes.get("coverage-controls").focused, true);
show({project: null}); assert.equal(area.hidden, true);
console.log("11 authored DOM groups passed; same-page phase and folded-parent navigation; no HTTP/model/search/native calls.");
