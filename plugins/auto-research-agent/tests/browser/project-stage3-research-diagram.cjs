/* Synthetic, offline DOM coverage. No research, scoring, provider or HTTP run. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const test = require("node:test");
const {fixture, web} = require("./project-stage3-wiki.cjs");
const script = fs.readFileSync(path.join(web, "project-stage3-research-diagram.js"), "utf8");
const plain = value => JSON.parse(JSON.stringify(value));

function freeze(value) {
  if (value && typeof value === "object" && !Object.isFrozen(value)) {
    Object.freeze(value);for (const child of Object.values(value)) freeze(child);
  }
  return value;
}
function api() {
  const window = {};
  vm.runInNewContext(script, {window});
  return window.STAGE3_RESEARCH_DIAGRAM;
}
class Element {
  constructor(doc, tag) {this.ownerDocument = doc;this.tagName = tag;this.children = [];this.attributes = {};this.style = {};this._text = "";}
  set innerHTML(_) {throw new Error("Unsafe HTML rendering");}
  set textContent(value) {this._text = String(value);this.children = [];}
  get textContent() {return this._text + this.children.map(n => n.textContent).join("\n");}
  setAttribute(key, value) {this.attributes[key] = value;}
  append(...children) {this.children.push(...children);}
  replaceChildren(...children) {this.children = children;this._text = "";}
}
function container() {
  const doc = {createElement: tag => new Element(doc, tag), createElementNS: (ns, tag) => {
    assert.equal(ns, "http://www.w3.org/2000/svg");return new Element(doc, tag);
  }};
  return new Element(doc, "section");
}
function all(node) {return [node, ...node.children.flatMap(all)];}
function at(value, pointer) {return pointer.slice(1).split("/").reduce((v, key) => v[key], value);}
function adversarialConditional() {
  return {planning_mode: "direction-intent", selection_status: "pending", execution_authorized: false,
    default_request: {key: "synthetic-intent", request_sha256: "d".repeat(64)},
    direction_context: {questions: [{question_ref: "original:SQA", text: "Which explanation remains unresolved?"}],
      unresolved: ["Access remains unknown"], source_unresolved: null, pending_scope_questions: [], missing_mapping: []},
    plan: {kind: "Stage3DirectionPlanningResult", schema_version: "1.0.0", version: 0, execution_authorized: false,
      question_plans: [{question_ref: "original:SQA", design: "A conditional comparison after access is verified", method: "Unknown pending source fit",
        analysis: null, interpretation: false, minimum_deliverable: 0, unknowns: ["Permission unresolved"]}]}};
}

test("formal F03 reuses explicit references and one shared design", () => {
  const view = freeze(fixture()), before = JSON.stringify(view), model = api().project(view);
  assert.equal(model.nodes.length, 7);assert.equal(model.edges.length, 6);
  assert.equal(model.nodes.filter(n => n.id === "shared-design").length, 1);
  assert.deepEqual(plain(model.binding), {kind: "Stage3ResearchPlan", schema_version: "1.1.0", plan_id: "synthetic-plan", version: 1,
    source_manifest_sha256: "a".repeat(64), request_sha256: "c".repeat(64)});
  for (const n of model.nodes) assert.equal(at(view, n.source), n.record);
  for (const e of model.edges) for (const source of e.sources) {
    const from = model.nodes.find(n => n.key === e.from), to = model.nodes.find(n => n.key === e.to);
    assert.ok([from.id, to.id].includes(at(view, source)));
  }
  assert.deepEqual(plain(model.edges.map(e => model.nodes.find(n => n.key === e.from).kind)), ["question", "question", "design", "design", "analysis", "analysis"]);
  assert.equal(model.unknowns[0].value.resolve_before, "material-design");
  assert.equal(JSON.stringify(view), before);
});

test("a missing design reference stays missing without creating content or a substitute link", () => {
  const view = fixture();view.plan.question_plans[0].design_ids = ["missing-design"];
  const model = api().project(view);
  assert.ok(model.missing.some(m => m.id === "missing-design" && m.source === "/plan/question_plans/0/design_ids/0"));
  assert.equal(model.nodes.some(n => n.id === "missing-design"), false);
  const q = model.nodes.find(n => n.id === "q-observe");
  assert.equal(model.edges.some(e => e.from === q.key), false);
  assert.equal(model.nodes.filter(n => n.kind === "analysis").length, 2);
});

test("procedure prose and Q-level materials do not create inferred scientific edges", () => {
  const view = fixture();view.plan.designs[0].procedure = "First collect, then calibrate, then validate, then publish";
  view.plan.resources[0].availability = "available";
  const model = api().project(view);
  assert.equal(model.nodes.length, 7);assert.equal(model.edges.length, 6);
  assert.equal(model.nodes.some(n => n.kind === "resource" || n.kind === "step"), false);
});

test("ambiguous IDs retain their records but do not choose an arbitrary link target", () => {
  const view = fixture();view.plan.designs.push({...view.plan.designs[0], family: "Another record with the same ID"});
  const model = api().project(view);
  assert.equal(model.nodes.filter(n => n.id === "shared-design").length, 2);
  assert.ok(model.missing.some(m => m.reason === "ambiguous"));
  assert.equal(model.edges.some(e => model.nodes.find(n => n.key === e.to).kind === "design"), false);
});

test("adversarial conditional records retain falsy values without becoming formal nodes", () => {
  const view = freeze(adversarialConditional()), before = JSON.stringify(view), model = api().project(view);
  assert.equal(model.mode, "conditional");assert.equal(model.nodes.length, 2);assert.equal(model.edges.length, 1);
  assert.deepEqual(plain(model.nodes.map(n => n.kind)), ["question", "conditional"]);
  assert.ok(model.nodes.every(n => n.id === "original:SQA"));
  assert.equal(model.edges[0].sources[0], "/plan/question_plans/0/question_ref");
  assert.equal(model.nodes[1].record.analysis, null);assert.equal(model.nodes[1].record.interpretation, false);
  assert.equal(model.nodes[1].record.minimum_deliverable, 0);assert.equal(model.binding.version, 0);
  assert.equal(model.unknowns.find(u => u.source === "/direction_context/source_unresolved").value, null);
  assert.equal(JSON.stringify(view), before);
});

test("mount renders safe accessible SVG with unique IDs across multiple mounts", () => {
  const component = api(), a = container(), b = container(), view = fixture();
  view.plan.questions[0].text = '<img src=x onerror="unexpected()">';
  view.plan.results[0].observed_value = 0;view.plan.results[1].observed_value = false;
  component.mount(a, freeze(view), {language: "zh-TW"});component.mount(b, view, {language: "en"});
  const elements = [...all(a), ...all(b)], ids = elements.map(n => n.attributes.id).filter(Boolean);
  assert.equal(ids.length, new Set(ids).size);
  for (const svg of elements.filter(n => n.tagName === "svg")) {
    assert.equal(svg.children[0].tagName, "title");assert.equal(svg.attributes.role, "img");
    for (const id of svg.attributes["aria-labelledby"].split(" ")) assert.ok(ids.includes(id));
  }
  assert.ok(a.textContent.includes(view.plan.questions[0].text));
  assert.ok(a.textContent.includes('"observed_value":0'));assert.ok(a.textContent.includes('"observed_value":false'));
  assert.equal(elements.some(n => ["img", "script", "foreignObject", "iframe", "a"].includes(n.tagName)), false);
  assert.ok(a.textContent.includes("研究計畫關係圖"));assert.ok(b.textContent.includes("Research plan relationships"));
});

test("large plans group all original records while the complete reference table remains available", () => {
  const view = fixture();
  for (let i = 2; i < 10; i++) {
    view.plan.designs.push({...view.plan.designs[0], design_id: `extra-design-${i}`});
    view.plan.question_plans[0].design_ids.push(`extra-design-${i}`);
  }
  const target = container(), model = api().mount(target, freeze(view), {language: "zh-CN"});
  const nodes = all(target).filter(n => n.tagName === "g" && n.attributes["data-kind"]);
  assert.equal(nodes.length, 4);assert.equal(model.nodes.length, 15);
  for (const n of model.nodes) assert.ok(target.textContent.includes(n.id), n.id);
  for (const e of model.edges) for (const source of e.sources) assert.ok(target.textContent.includes(source), source);
  assert.ok(target.textContent.includes("分组视图"));assert.ok(target.textContent.includes("完整来源引用表"));
});

test("long Unicode labels retain full source text with a shortened diagram label", () => {
  const view = fixture(), ref = "問題引用".repeat(12), target = container();
  view.plan.questions[0].question_ref = ref;view.plan.question_plans[0].question_ref = ref;
  view.plan.questions[0].text = "This question keeps complete words while its source remains unchanged";
  api().mount(target, freeze(view), {language: "zh-TW"});
  const svg = all(target).find(n => n.tagName === "svg");
  assert.ok(all(svg).some(n => n.tagName === "title" && n.textContent.includes(ref)));
  const ids = all(svg).filter(n => n.tagName === "text" && n.attributes["font-family"] === "ui-monospace, monospace");
  assert.ok(ids.some(n => n.textContent.endsWith("…") && n.textContent.length < ref.length));
  assert.ok(target.textContent.includes(ref));assert.equal(view.plan.questions[0].question_ref, ref);
});

test("layout keeps nodes within the canvas and retains distinct port coordinates", () => {
  const target = container();api().mount(target, fixture());
  const svg = all(target).find(n => n.tagName === "svg"), box = svg.attributes.viewBox.split(" ").map(Number);
  const nodeRects = all(svg).filter(n => n.tagName === "g").flatMap(n => n.children.filter(c => c.tagName === "rect"));
  assert.equal(Math.min(...nodeRects.map(n => Number(n.attributes.x))), 32);
  assert.equal(svg.style.minWidth, `${box[2]}px`);
  for (const rect of all(svg).filter(n => n.tagName === "rect")) {
    const a = rect.attributes;
    assert.ok(Number(a.x) >= 0 && Number(a.x) + Number(a.width) <= box[2]);
    assert.ok(Number(a.y) >= 0 && Number(a.y) + Number(a.height) <= box[3]);
  }
  const routes = all(svg).filter(n => n.tagName === "path" && n.attributes["marker-end"]).map(n => n.attributes.d);
  assert.equal(routes.length, 6);
  assert.equal(new Set(routes.map(d => d.match(/^M ([\d.]+) ([\d.]+)/)[0])).size, routes.length);
  assert.equal(new Set(routes.map(d => d.match(/(\d+) (\d+) V (\d+)$/)[0])).size, routes.length);
});

test("new versions and empty views replace the old graph without mutating any authority flags", () => {
  const component = api(), target = container(), old = fixture();component.mount(target, old);
  const next = fixture();next.plan.version = 2;next.plan.questions[0].text = "A newly versioned question";
  component.mount(target, freeze(next));
  assert.ok(target.textContent.includes('"version":2'));assert.ok(target.textContent.includes("A newly versioned question"));
  assert.equal(target.textContent.includes(old.plan.questions[0].text), false);
  component.mount(target, null);
  assert.equal(all(target).some(n => n.tagName === "svg"), false);
  assert.ok(target.textContent.includes("No saved plan relationships"));
  for (const key of ["execution_authorized", "evaluation_calls_authorized", "formal_execution_enabled", "external_claim_ready", "usable_for_formal_pairing"]) assert.equal(next[key], false);
});

function validConditional() {
  return {
    "planning_mode": "direction-intent",
    "selection_status": "pending",
    "execution_authorized": false,
    "default_request": {
      "key": "synthetic-valid-intent",
      "request_sha256": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
    },
    "direction_context": {
      "questions": [
        {
          "question_ref": "original:SQA",
          "text": "Which explanation remains unresolved?"
        }
      ],
      "unresolved": [
        "Access remains unknown"
      ],
      "source_unresolved": [],
      "pending_scope_questions": [],
      "missing_mapping": []
    },
    "plan": {
      "kind": "Stage3DirectionPlanningResult",
      "schema_version": "1.0.0",
      "intent_sha256": "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
      "planning_status": "needs-information",
      "markdown": "Conditional draft; verify access first.",
      "execution_authorized": false,
      "question_plans": [
        {
          "question_ref": "original:SQA",
          "materials": "Source access remains unverified",
          "method": "Compare recorded estimates if access is verified",
          "design": "A conditional comparison",
          "validation": "Verify source scope before use",
          "analysis": "Compare estimates with limitations",
          "interpretation": "Interpret associations only",
          "unknowns": [
            "Permission unresolved"
          ],
          "minimum_deliverable": "A source-bound comparison after material verification"
        }
      ]
    }
  };
}

test("valid saved conditional result retains intent identity and original references", () => {
  const view = freeze(validConditional()), before = JSON.stringify(view), target = container();
  const model = api().mount(target, view, {language: "en"});
  assert.equal(model.binding.intent_sha256, view.plan.intent_sha256);
  assert.equal(model.binding.request_sha256, view.default_request.request_sha256);
  assert.equal(model.nodes.length, 2);assert.equal(model.edges.length, 1);
  assert.equal(model.nodes[0].record, view.direction_context.questions[0]);
  assert.equal(model.nodes[1].record, view.plan.question_plans[0]);
  assert.equal(model.edges[0].sources[0], "/plan/question_plans/0/question_ref");
  for (const text of [view.plan.intent_sha256, view.plan.question_plans[0].materials, "Permission unresolved"]) assert.ok(target.textContent.includes(text));
  assert.equal(model.nodes.some(n => ["design", "analysis", "result"].includes(n.kind)), false);
  assert.equal(JSON.stringify(view), before);
});

test("empty conditional Host view keeps source unknowns without drawing a graph", () => {
  const view = validConditional();view.plan = null;view.default_request = null;
  view.direction_context.questions = [];
  view.direction_context.missing_mapping = ["No structured scientific question is mapped"];
  view.direction_context.source_unresolved = ["Dataset access remains unverified"];
  view.direction_context.pending_scope_questions = ["Confirm the source question"];
  const before = JSON.stringify(view), target = container(), model = api().mount(target, freeze(view));
  assert.equal(model.nodes.length, 0);assert.equal(model.edges.length, 0);
  assert.equal(all(target).some(n => n.tagName === "svg"), false);
  assert.ok(target.textContent.includes("No saved plan relationships"));
  for (const name of ["unresolved", "source_unresolved", "pending_scope_questions", "missing_mapping"]) {
    assert.ok(target.textContent.includes("/direction_context/" + name));
    for (const value of view.direction_context[name]) assert.ok(target.textContent.includes(value));
  }
  assert.ok(all(target).some(n => n.tagName === "table"));
  assert.equal(JSON.stringify(view), before);
});
