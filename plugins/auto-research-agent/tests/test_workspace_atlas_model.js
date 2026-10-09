"use strict";
const assert = require("node:assert/strict");
const model = require("../references/research-workspace/atlas/atlas-model.js");
const p = (work, version, topics, methods) => ({work_id: work, version_id: version,
  title: "Equal title", classification: {topic_cluster: topics, method: methods}, source_ids: []});
const originals = [p("a", "v1", ["X", "Y"], ["A", "B"]), p("a", "v2", "Y", "A"),
  p("b", "v1", "Unknown", "Unknown"), p("c", "v1", "X", "A")];
const payload = {literature_selection: {rows: [
  {work_id: "a", version_id: "v1", status: "excluded"},
  {work_id: "a", version_id: "v2", status: "pending"}]}, index: {papers: originals, screening: [
  {work_id: "a", version_id: "v1", status: "include", reason: "first"},
  {work_id: "a", version_id: "v1", status: "exclude", reason: "changed"}],
  claims: [{work_id: "a", version_id: "v2", relation: "unverified"}],
  bibliography: {entries: originals.map(p => ({...p, bibtex: `@misc{${p.work_id}${p.version_id}}`}))}}};
const before = JSON.stringify(payload), records = model.papers(payload);
assert.equal(new Set(records.map(p => p.key)).size, 4);
assert.deepEqual(model.groups(records).map(g => [g.label, g.ids.length]), [["X", 2], ["Y", 2]]);
assert.equal(model.intersection(records, ["X", "Y"]).length, 1);
assert.equal(records[2].topics.length, 0);
assert.deepEqual(records[0].screening.map(r => r.reason), ["first", "changed"]);
assert.equal(records[0].claims.length, 0);
assert.equal(records[1].claims[0].relation, "unverified");
assert.equal(records[0].discovery.count, null);
assert.equal(model.local(records, records[0].key)[0].similarity, .5);
assert.equal(model.filter(records, {status: "excluded"}).length, 1);
assert.deepEqual(model.filter(records, {status: "pending"}).map(p => p.key), [model.key(originals[1])]);
assert.equal(model.filter(records, {status: "unbound"}).length, 2);
assert.equal(model.citation(payload, [records[0].key]), "@misc{av1}");
assert.equal(JSON.stringify(payload), before);
const large = model.papers({index: {papers: Array.from({length: 360}, (_, i) => p(`S${i}`, "v1", i % 2 ? ["X", "Y"] : "X", "A"))}});
assert.equal(model.groups(large)[0].ids.length, 360);
assert.equal(model.intersection(large, ["X", "Y"]).length, 180);
assert.equal(model.filter(large, {topic: "X"}).length, 360);
assert.equal(model.local(large, large[0].key).length, 359);
const stage2 = model.stage2Papers({...payload, stage2_comparison: {literature: [
  {...p("a", "independent-v3", "Stage2-only topic", "Stage2 method"), cells: {method: {text: "Prose is not a method tag"}}},
  p("s2", "v1", "未知", "未記錄")]}});
assert.deepEqual(model.groups(stage2).map(g => g.label), ["Stage2-only topic"]);
assert.equal(stage2[0].methods[0], "Stage2 method");
assert.equal(stage2[1].methods.length, 0);
assert.deepEqual(model.stage2Papers(payload), []);
assert.equal(model.intersection(stage2, ["X"]).length, 0);
console.log("Atlas model assertions passed; synthetic records only.");
