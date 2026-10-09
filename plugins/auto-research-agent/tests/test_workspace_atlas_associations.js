"use strict";
const assert = require("node:assert/strict");
const vm = require("node:vm"), fs = require("node:fs");
const association = require("../references/research-workspace/atlas/atlas-associations.js");
const paper = (work, version, topics, method, text) => ({work_id: work, version_id: version,
  title: "Equal title", authors: ["IgnoredIdentitySecret"], year: 2026,
  classification: {topic_cluster: topics, method}, findings: {question: text}});
const records = [paper("a", "v1", ["X", "Y"], ["Shared", "Separate"], "retirement wealth household spending"),
  paper("a", "v2", "Y", "Shared", "retirement wealth household spending"),
  paper("b", "v1", "Z", "Other", "household spending income retirement"),
  paper("c", "v1", "Unknown", "Unknown", "galaxy telescope photon")];
const before = JSON.stringify(records), result = association.build(records);
const topic = result.recorded.find(link => link.kind === "recorded-topic-overlap");
assert.deepEqual(topic, {from: {type: "topic", key: "X"}, to: {type: "topic", key: "Y"},
  kind: "recorded-topic-overlap", basis: "shared-paper-membership", score: 1, count: 1,
  shared_terms: [], shared_papers: [association.key(records[0])]});
const versions = result.recorded.find(link => link.kind === "recorded-paper-overlap");
assert.deepEqual(versions.shared_topics, ["Y"]);
assert.deepEqual(versions.shared_methods, ["Shared"]);
assert.notEqual(versions.from.key, versions.to.key);
assert.ok(result.lexical.some(link => [link.from.key, link.to.key].includes(association.key(records[2])) &&
  [link.from.key, link.to.key].includes(association.key(records[0]))));
assert.ok(result.lexical.every(link => link.kind === "lexical-content" && link.basis === "tf-idf-cosine-v1" &&
  link.shared_terms.length > 0 && link.score > 0 && link.score <= 1));
assert.ok(result.lexical.every(link => ![link.from.key, link.to.key].includes(association.key(records[3]))));
assert.equal(new Set(result.lexical.map(link => JSON.stringify([link.from, link.to]))).size, result.lexical.length);
assert.deepEqual(association.build([...records].reverse()), result);
assert.deepEqual(association.build(records.map(p => ({...p, key: "wrong-key", topics: Array.isArray(p.classification.topic_cluster) ?
  [...p.classification.topic_cluster].reverse() : [p.classification.topic_cluster]}))), result);
assert.equal(JSON.stringify(records), before);
assert.ok(!association.features(records[0]).includes("ignoredidentitysecret"));
assert.ok(!association.features({...records[0], findings: {}}).includes("equal"));
assert.deepEqual(association.tokens("The and of with research papers stage saved evidence source unknown"), []);
const noOverlap = [paper("d", "v1", "A", [], "galaxy telescope"), paper("e", "v1", "B", [], "retirement income")];
assert.deepEqual(association.lexical(noOverlap, {threshold: 0}), []);
assert.deepEqual(association.build([]), {recorded: [], lexical: [], lexicalTopics: []});
assert.deepEqual(association.lexical([records[0]]), []);
assert.deepEqual(association.lexical(records, {neighbors: 0}), []);
assert.ok(association.lexical(records, {threshold: 1}).every(link => link.score === 1));
const chinese = [paper("h", "v1", [], [], "家庭消费变化"), paper("i", "v1", [], [], "家庭消费预测"),
  paper("j", "v1", [], [], "望远镜银河")];
assert.ok(association.lexical(chinese).some(link => link.shared_terms.includes("消费")));
assert.ok(association.tokens("家庭消费").includes("庭消"));
const retainedCells = records.map(p => ({...p, findings: undefined,
  cells: {question: {field: "selection.literature[0].findings.question", text: p.findings.question},
    validation: {field: null, text: "IgnoredUnboundSecret"}}}));
assert.deepEqual(association.build(retainedCells), result);
assert.ok(!association.features({...records[0], findings: {}, cells: {
  question: {field: null, text: "IgnoredUnboundSecret"}}}).includes("ignoredunboundsecret"));
const twins = [paper("t", "v1", [], [], "retirement household income"), paper("t", "v2", [], [], "retirement household income")];
assert.equal(association.lexical(twins).length, 1);
assert.equal(association.lexical(twins)[0].score, 1);
const grouped = [paper("k", "v1", ["Retirement", "Consumption"], [], "retirement wealth household spending"),
  paper("k", "v2", "Validation", [], "retirement wealth household spending"),
  paper("m", "v1", "Astronomy", [], "galaxy telescope photon")];
assert.ok(association.features(grouped[0]).includes("retirement"));
assert.ok(association.features(grouped[0]).includes("consumption"));
const groupLinks = association.lexicalTopics(grouped);
assert.ok(groupLinks.some(link => [link.from.key, link.to.key].includes("Validation")));
assert.ok(groupLinks.every(link => link.kind === "lexical-topic" && link.basis === "tf-idf-topic-aggregate-v1" &&
  link.source_fields.includes("question") && link.source_members.from.length && link.source_members.to.length));
assert.ok(groupLinks.some(link => [...link.source_members.from, ...link.source_members.to].includes(association.key(grouped[1]))));
const changed = grouped.map(p => p.work_id === "k" && p.version_id === "v2" ?
  {...p, findings: {question: "galaxy telescope photon"}} : p);
assert.notDeepEqual(association.lexicalTopics(changed), groupLinks);
assert.deepEqual(association.lexicalTopics([...grouped].reverse()), groupLinks);
const malicious = '<script>globalThis.executed = true</script><img src=x onerror=alert(1)>household spending';
const hostile = records.map(p => ({...p, findings: {question: malicious}}));
assert.ok(!association.tokens(malicious).includes("executed"));
assert.ok(association.build(hostile).lexical.every(link => link.shared_terms.every(term => !/[<>]/.test(term))));
const context = {window: {}};
vm.runInNewContext(fs.readFileSync(require.resolve("../references/research-workspace/atlas/atlas-associations.js"), "utf8"), context);
assert.equal(typeof context.window.AtlasAssociations.build, "function");
assert.equal(context.executed, undefined);
// More than two possible neighbors stays bounded by the union of each paper's top two.
const bounded = Array.from({length: 12}, (_, i) => paper(`N${i}`, "v1", [], [],
  `shared household spending retirement ${i % 2 ? "wealth" : "income"} detail${i}`));
assert.ok(association.lexical(bounded).length <= bounded.length * 2);
assert.deepEqual(association.lexical(bounded), association.lexical([...bounded].reverse()));
console.log("Atlas associations passed: literal memberships, distinct versions, lexical cross-topic links, Chinese, bounds, inert source text.");
