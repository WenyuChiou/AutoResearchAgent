"use strict";
// Injected DOM and microtasks test shared lifecycle; actual WebGL QA is separate.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const model = require("../references/research-workspace/atlas/atlas-model.js");
const associations = require("../references/research-workspace/atlas/atlas-associations.js");
const source = fs.readFileSync(require.resolve("../references/research-workspace/atlas/atlas-network.js"), "utf8");
const plain = value => JSON.parse(JSON.stringify(value));
function freeze(value) {
  if (value && typeof value === "object") {
    Object.values(value).forEach(freeze);
    Object.freeze(value);
  }
  return value;
}
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.attributes = {}; this.dataset = {}; this.connected = false; }
  append(...children) { children.forEach(child => { child.parent = this; this.children.push(child); }); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name]; }
  get isConnected() { return this.connected || Boolean(this.parent?.isConnected); }
}
const paper = (work, version, topic) => ({work_id: work, version_id: version,
  title: `${work} ${version}: Literal <script> shared retirement consumption`, authors: ["Original author"],
  findings: {method: "Shared retirement consumption comparison"},
  classification: {topic_cluster: topic, method: ["Literal method"]}, source_ids: []});
const payload = freeze({index: {papers: [paper("same", "v1", ["X", "Y"]),
  paper("same", "v2", ["Y"]), paper("other", "v1", ["X"])]}});
const rows = freeze(model.papers(payload)), before = JSON.stringify(payload), rowBefore = JSON.stringify(rows);
const canonicalLinks = associations.build(rows, {neighbors: 2});
const canonicalBefore = JSON.stringify(canonicalLinks);
const topicColors = new Map([["X", "#123456"], ["Y", "#654321"]]);
const paperAliases = new Map(rows.map((row, i) => [row.key, `P0${i + 1}`]));
function runtime({connected = false, computed = true, showLabels = false, fail = false, focus = {kind: "paper", key: rows[0].key}, records = rows} = {}) {
  const pending = [], calls = [], selected = [], settingsCalls = [], fallbackCalls = [], associationOptions = [];
  const pose = freeze({position: {x: 10, y: 20, z: 30}, target: {x: 0, y: 0, z: 0}});
  const settings = {mode: 2, computed, showLabels};
  const root = {queueMicrotask: callback => pending.push(callback), AtlasAssociations: {
    build: (...args) => { associationOptions.push(plain(args[1])); return freeze(associations.build(...args)); }
  }, AtlasSpatial: {mount: (host, options) => {
    assert.equal(host.isConnected, true, "spatial mount requires attached host");
    const instance = {host, options, modes: [], labels: [], fits: 0, destroys: 0,
      setMode(mode) { this.modes.push(mode); }, fit() { this.fits++; },
      setLabels(value) { this.labels.push(value); return true; },
      destroy() { this.destroys++; }, snapshot: () => ({saved: "camera"}),
      diagnostics: () => ({mounted: true, fixture: true})};
    calls.push(instance);
    if (fail) throw new Error("Injected renderer failure");
    return instance;
  }}};
  const document = {createElement: tag => new Element(tag)};
  vm.runInNewContext(source, {window: root, document});
  const parent = new Element("main"); parent.connected = connected;
  const options = {papers: records, model, language: "zh-Hans", t: key => "translated:" + key,
    onSelect: value => selected.push(value), focus,
    pose, settings, topicColors, paperAliases, onSettings: () => settingsCalls.push(settings.computed),
    onFallback: () => fallbackCalls.push("requested")};
  const mounted = root.AtlasNetwork.mount(parent, options);
  return {parent, options, mounted, calls, selected, settingsCalls, fallbackCalls, pending, associationOptions,
    flush() { while (pending.length) pending.shift()(); }};
}

// Mount waits for the connecting render task; initial diagnostics never imply a renderer.
const live = runtime();
assert.equal(live.calls.length, 0); assert.equal(live.pending.length, 1);
assert.deepEqual(plain(live.mounted.diagnostics()), {mounted: false, faults: []});
assert.equal(live.mounted.snapshot(), live.options.pose);
live.parent.connected = true; live.flush();
assert.equal(live.calls.length, 1); const instance = live.calls[0];
assert.equal(instance.options.papers, rows); assert.equal(instance.options.model, model);
assert.equal(instance.options.language, "zh-Hans"); assert.equal(instance.options.topicColors, topicColors);
assert.equal(instance.options.paperAliases, paperAliases);
assert.deepEqual([...paperAliases], rows.map((row, i) => [row.key, `P0${i + 1}`]));
assert.equal(instance.options.focus, live.options.focus); assert.equal(instance.options.pose, live.options.pose);
assert.equal(instance.options.mode, 2);
assert.equal(instance.options.showLabels, false);
assert.deepEqual(live.associationOptions, [{neighbors: 2}], "the adapter inherits the shared association threshold");
assert.deepEqual(plain(instance.options.extraLinks), plain([
  ...canonicalLinks.recorded, ...canonicalLinks.lexical, ...canonicalLinks.lexicalTopics
]));
assert.equal(JSON.stringify(rows), rowBefore); assert.equal(JSON.stringify(payload), before);
assert.equal(JSON.stringify(canonicalLinks), canonicalBefore);
assert.deepEqual(live.mounted.snapshot(), {saved: "camera"});
assert.deepEqual(live.mounted.diagnostics(), {mounted: true, fixture: true});
instance.options.onSelect({kind: "paper", key: rows[1].key});
assert.deepEqual(live.selected, [{kind: "paper", key: rows[1].key}]);

// The actual adapter and related-card helper share the .12 default boundary.
const thresholdPayload = freeze({index: {papers: [
  {...paper("threshold-a", "v1", ["X"]), classification: {topic_cluster: ["X"], method: []}, findings: {question: "household alpha bravo charlie delta"}},
  {...paper("threshold-b", "v1", ["Y"]), classification: {topic_cluster: ["Y"], method: []}, findings: {question: "household echo foxtrot golf hotel"}}
]}});
const thresholdRows = freeze(model.papers(thresholdPayload)), thresholdKey = associations.key(thresholdRows[0]);
const defaultRelated = associations.related(thresholdRows, thresholdKey);
assert.deepEqual(defaultRelated, []);
const relaxedGraph = associations.build(thresholdRows, {neighbors: 2, threshold: .1});
const relaxedPaperLinks = relaxedGraph.lexical;
assert.equal(relaxedPaperLinks.length, 1); assert.equal(relaxedPaperLinks[0].score, .112343);
const relaxedRelated = associations.related(thresholdRows, thresholdKey, {threshold: .1});
assert.equal(relaxedRelated.length, 1); assert.equal(relaxedRelated[0].lexical.score, .112343);
const thresholdNetwork = runtime({connected: true, records: thresholdRows, focus: {kind: "paper", key: thresholdRows[0].key}}); thresholdNetwork.flush();
const defaultAdapterLinks = plain(thresholdNetwork.calls[0].options.extraLinks);
assert.deepEqual(thresholdNetwork.associationOptions, [{neighbors: 2}]);
assert.equal(defaultAdapterLinks.filter(link => link.kind === "lexical-content").length, defaultRelated.length);
assert.equal(defaultAdapterLinks.filter(link => link.kind === "lexical-content" || link.kind === "lexical-topic").length, 0);
thresholdNetwork.mounted.destroy();

// The 2D/3D buttons track the effective mode and forward only allowed live actions.
const [controls] = live.parent.children, buttons = controls.children.filter(e => e.tag === "button");
const legend = live.parent.children.find(node => node.className === "atlas-node-legend");
const legendIcons = legend.children.map(item => item.children[0]);
assert.deepEqual(legendIcons.map(icon => icon.getAttribute("data-node-shape")), ["sphere", "diamond", "square"]);
assert.deepEqual(buttons.slice(0, 2).map(e => e.textContent), ["2D", "3D"]);
assert.deepEqual(buttons.slice(0, 2).map(e => e.getAttribute("aria-pressed")), ["true", "false"]);
buttons[1].onclick(); assert.equal(legendIcons[2].getAttribute("data-node-shape"), "cube");
buttons[0].onclick(); assert.equal(legendIcons[2].getAttribute("data-node-shape"), "square"); buttons[2].onclick();
assert.deepEqual(instance.modes, [3, 2]); assert.equal(live.options.settings.mode, 2);
assert.deepEqual(buttons.slice(0, 2).map(e => e.getAttribute("aria-pressed")), ["true", "false"]);
assert.equal(instance.fits, 1);
const input = controls.children.find(e => e.tag === "label").children[0];
assert.equal(input.checked, true); input.checked = false; input.onchange();
assert.equal(live.options.settings.computed, false); assert.deepEqual(live.settingsCalls, [false]);
// Label visibility changes the live renderer without rebuilding it or changing its camera.
const labelControls = controls.children.filter(e => e.tag === "label");
assert.equal(labelControls.length, 2);
const labelInput = labelControls.find(e => e.children[0] !== input).children[0];
const basisOf = value => value.parent.children.find(node => node.className === "atlas-relation-list");
const relationRows = value => basisOf(value).children.filter(node => node.tag === "p");
const liveBasis = relationRows(live).map(node => node.textContent);
assert.equal(labelInput.checked, false);
const retainedPose = JSON.stringify(live.mounted.snapshot());
labelInput.checked = true; labelInput.onchange();
assert.equal(live.options.settings.showLabels, true);
labelInput.checked = false; labelInput.onchange();
assert.equal(live.options.settings.showLabels, false);
assert.deepEqual(instance.labels, [true, false]);
assert.equal(live.calls.length, 1); assert.equal(instance.destroys, 0);
assert.equal(JSON.stringify(live.mounted.snapshot()), retainedPose);
assert.deepEqual(live.settingsCalls, [false]);
assert.deepEqual(relationRows(live).map(node => node.textContent), liveBasis, "mode and label controls cannot expand relationship basis");
assert.equal(JSON.stringify(rows), rowBefore); assert.equal(JSON.stringify(payload), before);
live.mounted.destroy(); live.mounted.destroy();
instance.options.onSelect({kind: "topic", key: "X"}); buttons[1].onclick(); buttons[2].onclick();
input.checked = true; input.onchange();
labelInput.checked = true; labelInput.onchange();
assert.equal(instance.destroys, 1); assert.equal(live.selected.length, 1);
assert.deepEqual(instance.modes, [3, 2]); assert.equal(instance.fits, 1);
assert.deepEqual(instance.labels, [true, false]);
assert.equal(live.options.settings.computed, false); assert.deepEqual(live.settingsCalls, [false]);
assert.equal(live.options.settings.showLabels, false);

// Destroy before the queued mount cancels it; an unattached host never mounts either.
const cancelled = runtime({connected: true}); cancelled.mounted.destroy(); cancelled.flush();
assert.equal(cancelled.calls.length, 0);
const detached = runtime(); detached.flush(); assert.equal(detached.calls.length, 0);
assert.deepEqual(plain(detached.mounted.diagnostics()), {mounted: false, faults: []});

// With the computed layer off, only canonical recorded association edges are forwarded.
const recorded = runtime({connected: true, computed: false}); recorded.flush();
assert.deepEqual(plain(recorded.calls[0].options.extraLinks), plain(canonicalLinks.recorded));
assert.equal(JSON.stringify(rows), rowBefore); assert.equal(JSON.stringify(payload), before);
recorded.mounted.destroy();

// Explicitly enabled labels survive mounting as the effective checkbox and renderer setting.
const labelled = runtime({connected: true, showLabels: true}); labelled.flush();
assert.equal(labelled.calls[0].options.showLabels, true);
const labelledCheckboxes = labelled.parent.children[0].children.filter(e => e.tag === "label");
assert.equal(labelledCheckboxes[1].children[0].checked, true);
labelled.mounted.destroy();

// A mount failure provides an explicit translated fallback and retains an unmounted state.
const failed = runtime({connected: true, fail: true}); failed.flush();
const errorHost = failed.parent.children[1];
assert.equal(errorHost.children[0].textContent, "translated:spatialUnavailable");
assert.equal(errorHost.children[1].textContent, "translated:planarFallback");
assert.equal(failed.mounted.diagnostics().mounted, false);
assert.deepEqual(plain(failed.mounted.diagnostics().faults), ["Error: Injected renderer failure"]);
assert.equal(failed.mounted.snapshot(), failed.options.pose);
assert.equal(failed.fallbackCalls.length, 0); errorHost.children[1].onclick();
assert.deepEqual(failed.fallbackCalls, ["requested"]); assert.equal(failed.selected.length, 0);
failed.mounted.destroy();
errorHost.children[1].onclick(); assert.deepEqual(failed.fallbackCalls, ["requested"]);

// Textual basis uses the same exact typed focus as graph edges, never the default detail.
for (const focus of [null, {kind: "paper", key: "same"}, {kind: "topic", key: "missing"}, {kind: "method", key: "X"}, {kind: "other", key: rows[0].key}]) {
  const cleared = runtime({focus});
  assert.equal(basisOf(cleared).hidden, true, "initial, stale or wrong-type selection hides basis");
  assert.equal(relationRows(cleared).length, 0, "hidden basis cannot retain unrelated rows");
  cleared.mounted.destroy();
}
const selectedPaper = runtime({computed: false, focus: {kind: "paper", key: rows[1].key}});
assert.equal(basisOf(selectedPaper).hidden, false); assert.equal(basisOf(selectedPaper).open, true);
const paperText = relationRows(selectedPaper).map(row => row.textContent);
assert.equal(paperText.length, 4, "one recorded topic, one method and two incident paper overlaps");
assert(paperText.every(text => text.includes(rows[1].title)), "each basis row must touch the selected exact paper version");
assert(paperText.some(text => text.includes("translated:directionLink")));
assert(paperText.some(text => text.includes("translated:methodLink")));
assert.equal(paperText.some(text => text.startsWith("X ↔ Y")), false, "topic overlap is not incident to a paper node");
assert(relationRows(selectedPaper).every(row => row.translate === false));
assert(paperText.some(text => text.includes("<script>")), "source text is literal textContent rather than HTML");
const selectedTopic = runtime({computed: false, focus: {kind: "topic", key: "X"}});
assert.equal(relationRows(selectedTopic).length, 3, "topic basis has two memberships and its direct topic overlap");
assert.equal(relationRows(selectedTopic).some(row => row.textContent.includes(rows[1].title)), false, "paper not classified under X is excluded");
const selectedMethod = runtime({computed: false, focus: {type: "method", key: "Literal method"}});
assert.equal(relationRows(selectedMethod).length, 3, "methods have recorded membership basis even without association extraLinks");
assert(relationRows(selectedMethod).every(row => row.textContent.endsWith("Literal method · translated:methodLink")));
const single = runtime({records: freeze([rows[0]]), computed: false, focus: {kind: "paper", key: rows[0].key}});
assert.equal(relationRows(single).length, 3, "one paper still has its two recorded topics and unique method");
const computedTopic = runtime({focus: {kind: "topic", key: "X"}});
const computedText = relationRows(computedTopic).map(row => row.textContent);
assert(computedText.some(text => text.includes("translated:computedLinks")), "computed incident relationships remain separately labelled");
assert(computedText.every(text => text.startsWith("X ↔") || text.includes(" ↔ X ·")), "computed layers do not broaden typed selection");
const noMetadata = runtime({records: freeze(model.papers({index: {papers: [{work_id: "unknown", version_id: "v1", title: "Unknown classification"}]}})), focus: {kind: "paper", key: '["unknown","v1"]'}});
assert.equal(basisOf(noMetadata).hidden, false); assert.deepEqual(relationRows(noMetadata).map(row => row.textContent), ["translated:noRelations"], "missing metadata must not invent membership");
const resetBasis = runtime({focus: null}); assert.equal(basisOf(resetBasis).hidden, true);
for (const value of [selectedPaper, selectedTopic, selectedMethod, single, computedTopic, noMetadata, resetBasis]) value.mounted.destroy();
assert.equal(JSON.stringify(rows), rowBefore); assert.equal(JSON.stringify(payload), before);
console.log("atlas network lifecycle, typed selection-only basis, microtasks, immutable links, mode, settings and fallback contracts passed");
