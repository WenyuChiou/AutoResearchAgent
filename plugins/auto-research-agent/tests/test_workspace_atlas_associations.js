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

// Direct paper relations merge recorded and computed bases into one version-bound card.
const selectedKey = association.key(records[0]), related = association.related(records, selectedKey);
assert.equal(related.length, 2);
assert.deepEqual(related[0].shared_topics, ["Y"]);
assert.deepEqual(related[0].shared_methods, ["Shared"]);
assert.equal(related[0].paper.key, association.key(records[1]));
assert.equal(related[0].paper.title, records[1].title);
assert.notEqual(related[0].paper.key, selectedKey);
assert.equal(related[0].lexical.score, 1);
assert.equal(related[0].lexical.basis, "tf-idf-cosine-v1");
assert.ok(related[0].lexical.shared_terms.includes("retirement"));
assert.equal(new Set(related.map(row => row.paper.key)).size, related.length);
const crossTopic = related.find(row => row.paper.key === association.key(records[2]));
assert.deepEqual(crossTopic.shared_topics, []); assert.deepEqual(crossTopic.shared_methods, []);
assert.ok(crossTopic.lexical.score > 0 && crossTopic.lexical.shared_terms.includes("household"));
assert.deepEqual(association.related(records, selectedKey, {computed: false}), [
  {...related[0], lexical: null}
]);
assert.deepEqual(association.related(records, selectedKey, {neighbors: 0}), [
  {...related[0], lexical: null}
]);
assert.deepEqual(association.related([...records].reverse(), selectedKey), related);
assert.deepEqual(association.related(retainedCells, selectedKey).map(row => ({...row, paper: row.paper.key})),
  related.map(row => ({...row, paper: row.paper.key})));
assert.deepEqual(association.related(records.map(p => ({...p, key: "wrong-key"})), selectedKey), related);
assert.deepEqual(association.related(records, "wrong-key"), []);
assert.deepEqual(association.related([], selectedKey), []);
assert.deepEqual(association.related([records[0]], selectedKey), []);
assert.equal(JSON.stringify(records), before);

// A topic-aggregate edge or a bridge paper never creates a direct relation between its members.
const bridge = [paper("bridge", "v1", ["X", "Y"], [], ""),
  paper("left", "v1", "X", [], ""), paper("right", "v1", "Y", [], "")];
assert.ok(association.build(bridge).recorded.some(edge => edge.from.type === "topic"));
assert.deepEqual(association.related(bridge, association.key(bridge[1])).map(row => row.paper.key),
  [association.key(bridge[0])]);
const unknowns = [paper("unknown-a", "v1", ["Unknown", "未知"], "Unverified", ""),
  paper("unknown-b", "v1", ["Unknown", "未知"], "Unverified", "")];
assert.deepEqual(association.related(unknowns, association.key(unknowns[0]), {threshold: 0}), []);
assert.deepEqual(association.related(noOverlap, association.key(noOverlap[0]), {threshold: 0}), []);

// Default graph edges and related cards use the same cosine threshold.
const thresholdParity = [paper("threshold-a", "v1", [], [], "household alpha bravo charlie delta"),
  paper("threshold-b", "v1", [], [], "household echo foxtrot golf hotel")];
const defaultThresholdGraph = association.build(thresholdParity);
assert.deepEqual(defaultThresholdGraph.lexical, []);
assert.deepEqual(association.related(thresholdParity, association.key(thresholdParity[0])), []);
const lowerThresholdGraph = association.build(thresholdParity, {threshold: .1});
assert.equal(lowerThresholdGraph.lexical.length, 1);
assert.equal(lowerThresholdGraph.lexical[0].score, .112343);
const lowerThresholdCards = association.related(thresholdParity, association.key(thresholdParity[0]), {threshold: .1});
assert.equal(lowerThresholdCards.length, 1);
assert.equal(lowerThresholdCards[0].lexical.score, lowerThresholdGraph.lexical[0].score);

// Topic aggregates disclose classification-only feature inputs in their provenance inventory.
const classifiedTopics = [
  {work_id: "classified-a", version_id: "v1", classification: {topic_cluster: "retirement income"}, findings: {}},
  {work_id: "classified-b", version_id: "v1", classification: {topic_cluster: "household income"}, findings: {}}
];
const classifiedTopicLinks = association.lexicalTopics(classifiedTopics);
assert.equal(classifiedTopicLinks.length, 1);
assert.equal(classifiedTopicLinks[0].score, .336097);
assert.deepEqual(classifiedTopicLinks[0].source_fields,
  ["question", "data", "method", "main_findings", "relevance", "transferability", "topics", "classification.topic_cluster"]);
assert.deepEqual([...classifiedTopicLinks[0].source_members.from, ...classifiedTopicLinks[0].source_members.to].sort(),
  classifiedTopics.map(association.key).sort());

// Recorded relations rank first, then recorded counts, cosine values and canonical keys.
const ranked = [paper("selected", "v1", ["X", "Y"], ["M", "N"], "retirement household income"),
  paper("many", "v1", ["X", "Y"], "M", "galaxy photon telescope"),
  paper("high-z", "v1", "X", [], "retirement household income"),
  paper("high-a", "v1", "X", [], "retirement household income"),
  paper("low", "v1", [], "N", "galaxy photon telescope"),
  paper("computed", "v1", "Z", "Other", "retirement household income")];
const ranking = association.related(ranked, association.key(ranked[0]), {neighbors: 4});
assert.deepEqual(ranking.map(row => row.paper.work_id), ["many", "high-a", "high-z", "low", "computed"]);

// Pure output preserves literal source text; HTML-looking titles never become executable code.
function freeze(value) {
  if (value && typeof value === "object") { Object.values(value).forEach(freeze); Object.freeze(value); }
  return value;
}
const frozen = freeze(hostile.map(p => ({...p, title: malicious}))), frozenBefore = JSON.stringify(frozen);
const inert = association.related(frozen, selectedKey);
assert.equal(inert[0].paper.title, malicious);
assert.equal(inert[0].paper.findings.question, malicious);
assert.ok(inert.every(row => row.lexical?.shared_terms.every(term => !/[<>]/.test(term))));
assert.equal(JSON.stringify(frozen), frozenBefore);
assert.equal(globalThis.executed, undefined);

const context = {window: {}};
vm.runInNewContext(fs.readFileSync(require.resolve("../references/research-workspace/atlas/atlas-associations.js"), "utf8"), context);
assert.equal(typeof context.window.AtlasAssociations.build, "function");
assert.equal(typeof context.window.AtlasAssociations.related, "function");
assert.equal(context.executed, undefined);
// More than two possible neighbors stays bounded by the union of each paper's top two.
const bounded = Array.from({length: 12}, (_, i) => paper(`N${i}`, "v1", [], [],
  `shared household spending retirement ${i % 2 ? "wealth" : "income"} detail${i}`));
assert.ok(association.lexical(bounded).length <= bounded.length * 2);
assert.deepEqual(association.lexical(bounded), association.lexical([...bounded].reverse()));

// Related cards are exactly the symmetric union of the graph's direct paper edges.
const options = {neighbors: 2, threshold: .09}, graph = association.build([...records, ...bounded], options);
const graphRecords = [...records, ...bounded], graphBefore = JSON.stringify(graphRecords);
for (const p of graphRecords) {
  const id = association.key(p), cards = association.related(graphRecords, id, options);
  const expected = [...new Set([...graph.recorded, ...graph.lexical]
    .filter(edge => edge.from.type === "paper" && edge.to.type === "paper")
    .flatMap(edge => edge.from.key === id ? [edge.to.key] : edge.to.key === id ? [edge.from.key] : []))].sort();
  assert.deepEqual(cards.map(row => row.paper.key).sort(), expected);
  for (const card of cards) assert.ok(association.related(graphRecords, card.paper.key, options)
    .some(row => row.paper.key === id));
}
assert.equal(JSON.stringify(graphRecords), graphBefore);
console.log("Atlas associations passed: literal memberships, distinct versions, lexical cross-topic links, Chinese, bounds, inert source text.");
