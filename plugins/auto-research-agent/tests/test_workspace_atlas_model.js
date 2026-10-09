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
// The v6 geometry remains one network for small and working-size collections.
const graphRecords = count => model.papers({index: {papers: Array.from({length: count}, (_, i) =>
  p(`G${String(i).padStart(2, "0")}`, i % 7 ? "v1" : "v2",
    i % 5 === 0 ? [`Direction ${i % 9}`, "Cross-direction"] : `Direction ${i % 9}`,
    i % 3 ? ["Shared method", `Specific method ${i}`] : "Second shared method"))}});
for (const count of [15, 30, 40, 48]) {
  const records = graphRecords(count), saved = JSON.stringify(records);
  const layout = model.networkLayout(records);
  assert.equal(layout.width, 600);
  assert.equal(layout.height, 540);
  assert.equal(layout.papers.length, count);
  assert.equal(new Set(layout.papers.map(paper => paper.key)).size, count);
  assert.equal(new Set(layout.papers.map(paper => `${paper.x},${paper.y}`)).size, count);
  assert.deepEqual(layout, model.networkLayout([...records].reverse()));
  assert.deepEqual(layout, model.networkLayout(records, {selectedKey: records[3].key, page: 4}));
  const reorderedTags = records.map(paper => ({...paper, topics: [...paper.topics].reverse(), methods: [...paper.methods].reverse()}));
  assert.deepEqual(layout, model.networkLayout(reorderedTags));
  for (const node of layout.papers) {
    const paper = records.find(paper => paper.key === node.key);
    assert.deepEqual(node.groupKeys, [...paper.topics].sort());
    const radius = Math.hypot((node.x - 300) / 230, (node.y - 270) / 205);
    assert.ok(Math.abs(radius - 1) < .00002 || count > 24 && Math.abs(radius - .82) < .00002);
    assert.ok(node.x >= 69 && node.x <= 531 && node.y >= 64 && node.y <= 476);
  }
  for (let i = 0; i < layout.papers.length; i++) {
    for (let j = i + 1; j < layout.papers.length; j++) {
      const a = layout.papers[i], b = layout.papers[j];
      assert.ok(Math.hypot(a.x - b.x, a.y - b.y) > 27, "Visible paper circles must not overlap");
    }
  }
  for (const group of layout.groups) {
    assert.deepEqual(group.ids, records.filter(paper => paper.topics.includes(group.key)).map(paper => paper.key).sort());
    assert.ok(Number.isFinite(group.x) && Number.isFinite(group.y) && group.rx > 0 && group.ry > 0);
    assert.ok(group.colorIndex >= 0 && group.colorIndex < 6);
  }
  assert.deepEqual(layout.methods.map(method => method.label).sort(), ["Second shared method", "Shared method"]);
  for (const method of layout.methods) {
    assert.deepEqual(method.ids, records.filter(paper => paper.methods.includes(method.key)).map(paper => paper.key).sort());
    assert.ok(method.x >= 205 && method.x <= 395 && method.y >= 175 && method.y <= 365);
    assert.ok(method.ids.length > 1);
  }
  assert.equal(JSON.stringify(records), saved);
}
assert.deepEqual(model.networkLayout([]), {width: 600, height: 540, papers: [], groups: [], methods: []});
const missingTags = model.papers({index: {papers: [p("none", "v1", "Unknown", "Unknown"),
  p("none", "v2", "未记录", "未驗證"), p("unique", "v1", [], "Unique method")]}});
const unknownLayout = model.networkLayout(missingTags);
assert.equal(unknownLayout.papers.length, 3);
assert.deepEqual(unknownLayout.papers.map(paper => paper.groupKeys), [[], [], []]);
assert.deepEqual(unknownLayout.methods, []);
assert.equal(unknownLayout.groups[0].key, "");
assert.equal(unknownLayout.groups[0].colorIndex, -1);
assert.deepEqual(model.networkLayout(records).methods.map(method => [method.key, method.ids]), [
  ["A", [model.key(originals[0]), model.key(originals[1]), model.key(originals[3])].sort()]]);
// Unique method labels remain literal one-paper nodes, never fake shared hubs.
const uniqueRecords = model.papers({index: {papers: Array.from({length: 15}, (_, i) =>
  p(`U${i}`, "v1", `Direction ${i % 9}`, `Literal one-paper method ${i}`))}});
assert.deepEqual(model.networkLayout(uniqueRecords).methods, []);
const assertMethodSeparation = layout => {
  for (let i = 0; i < layout.methods.length; i++) {
    const method = layout.methods[i];
    assert.ok(method.x >= 50 && method.x <= 550 && method.y >= 55 && method.y <= 485);
    for (const paper of layout.papers) {
      assert.ok(Math.hypot(method.x - paper.x, method.y - paper.y) >= 35.999, "Method and paper markers must not overlap");
    }
    for (const other of layout.methods.slice(i + 1)) {
      assert.ok(Math.hypot(method.x - other.x, method.y - other.y) >= 35.999, "Method markers must not overlap");
    }
  }
};
const singleLayout = model.networkLayout(uniqueRecords, {singleMethods: true});
assert.equal(singleLayout.methods.length, 15);
assertMethodSeparation(singleLayout);
assert.deepEqual(singleLayout, model.networkLayout([...uniqueRecords].reverse(), {singleMethods: true, selectedKey: uniqueRecords[2].key, page: 2}));
assert.deepEqual(singleLayout.papers, model.networkLayout(uniqueRecords).papers);
assert.ok(singleLayout.methods.some(method => method.x < 190 || method.x > 410));
assert.ok(new Set(singleLayout.methods.map(method => Math.round(Math.hypot(method.x - 300, method.y - 270)))).size > 8);
for (const method of singleLayout.methods) {
  const paper = uniqueRecords.find(paper => paper.methods.includes(method.key));
  const point = singleLayout.papers.find(point => point.key === paper.key);
  assert.deepEqual(method.ids, [paper.key]);
  assert.ok(Math.hypot(method.x - point.x, method.y - point.y) < 150);
}
for (const count of [15, 30, 40, 48]) {
  const records = graphRecords(count), original = JSON.stringify(records);
  const allMethods = model.networkLayout(records, {singleMethods: true});
  assertMethodSeparation(allMethods);
  assert.deepEqual(allMethods, model.networkLayout([...records].reverse(), {singleMethods: true, selectedKey: records[1].key}));
  assert.deepEqual(allMethods, model.networkLayout(records.map(paper => ({...paper, methods: [...paper.methods].reverse()})), {singleMethods: true}));
  assert.deepEqual(allMethods.papers, model.networkLayout(records).papers);
  assert.deepEqual(allMethods.methods.map(method => [method.key, method.ids]), model.groups(records, "methods").map(method =>
    [method.key, [...method.ids].sort()]).sort((a, b) => b[1].length - a[1].length || (a[0] < b[0] ? -1 : 1)));
  assert.deepEqual(allMethods.methods.filter(method => method.ids.length > 1), model.networkLayout(records).methods);
  assert.equal(JSON.stringify(records), original);
}
assert.deepEqual(model.networkLayout(missingTags, {singleMethods: true}).methods.map(method => [method.key, method.ids]),
  [["Unique method", [model.key(missingTags[2])]]]);
const twoPerPaper = model.papers({index: {papers: Array.from({length: 40}, (_, i) =>
  p(String(i), "v1", `Topic ${i % 6}`, [`Method ${i}`, `Alternate ${i}`]))}});
const twoMethodLayout = model.networkLayout(twoPerPaper, {singleMethods: true});
assert.equal(twoMethodLayout.methods.length, 80);
assertMethodSeparation(twoMethodLayout);
console.log("Atlas model assertions passed; synthetic records only.");
