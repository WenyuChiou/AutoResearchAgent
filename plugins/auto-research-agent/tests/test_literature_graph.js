"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(
  path.join(__dirname, "../references/research-workspace/literature-reference.js"),
  "utf8",
);
const context = { window: {} };
vm.runInNewContext(source, context, { filename: "literature-reference.js" });
const graph = context.window.LiteratureReference;

const fixture = (version, classification, role) => ({
  workId: `same-work~version-${version}`, title: "One shared title", authors: ["Researcher, A"],
  journal: "Journal", keywords: [classification], roles: [{ name: role, basis: "Recorded assignment" }],
});
const records = [fixture(1, "classification-a", "topic core"), fixture(2, "classification-b", "closest work")];
const identities = (filters) => Array.from(graph.filterRecords(records, filters), (row) => row.workId);
assert.deepEqual(identities({}), ["same-work~version-1", "same-work~version-2"], "shared titles retain versions");
assert.deepEqual(identities({ keyword: "classification-b" }), ["same-work~version-2"], "classification retains identity");
assert.deepEqual(identities({ role: "topic core" }), ["same-work~version-1"], "role filtering does not infer edges");

const nodes = [
  { key: "paper:same-work~version-1", type: "paper" },
  { key: "paper:same-work~version-2", type: "paper" },
  { key: "keyword:classification-a", type: "keyword" },
  { key: "role:topic core", type: "role" },
];
const edges = [
  { from: nodes[0].key, to: nodes[2].key },
  { from: nodes[0].key, to: nodes[3].key },
];
const first = [...graph.layoutGraph(nodes, edges)].map(([key, point]) => [key, point.x, point.y]);
const second = [...graph.layoutGraph([...nodes].reverse(), [...edges].reverse())].map(
  ([key, point]) => [key, point.x, point.y],
);
assert.deepEqual(first, second, "layout is deterministic across input ordering");
first.forEach(([, x, y]) => {
  assert.ok(x >= 44 && x <= 916, `x coordinate ${x} is bounded`);
  assert.ok(y >= 44 && y <= 496, `y coordinate ${y} is bounded`);
});
assert.deepEqual(
  { ...graph.clampGraphPoint({ x: -100, y: 900 }) },
  { x: 44, y: 496 },
  "keyboard and pointer node movement share bounded coordinates",
);

console.log("literature graph deterministic layout/filter/bounds: PASS");
