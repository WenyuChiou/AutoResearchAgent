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
  title: "Literal <script> shared retirement consumption", authors: ["Original author"],
  classification: {topic_cluster: topic, method: ["Literal method"]}, source_ids: []});
const payload = freeze({index: {papers: [paper("same", "v1", ["X", "Y"]),
  paper("same", "v2", ["Y"]), paper("other", "v1", ["X"])]}});
const rows = freeze(model.papers(payload)), before = JSON.stringify(payload), rowBefore = JSON.stringify(rows);
const canonicalLinks = associations.build(rows, {neighbors: 2, threshold: .09});
const canonicalBefore = JSON.stringify(canonicalLinks);
const topicColors = new Map([["X", "#123456"], ["Y", "#654321"]]);
const paperAliases = new Map(rows.map((row, i) => [row.key, `P0${i + 1}`]));
function runtime({connected = false, computed = true, showLabels = false, fail = false} = {}) {
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
  const options = {papers: rows, model, language: "zh-Hans", t: key => "translated:" + key,
    onSelect: value => selected.push(value), focus: {kind: "paper", key: rows[0].key},
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
assert.deepEqual(live.associationOptions, [{neighbors: 2, threshold: .09}]);
assert.deepEqual(plain(instance.options.extraLinks), plain([
  ...canonicalLinks.recorded, ...canonicalLinks.lexical, ...canonicalLinks.lexicalTopics
]));
assert.equal(JSON.stringify(rows), rowBefore); assert.equal(JSON.stringify(payload), before);
assert.equal(JSON.stringify(canonicalLinks), canonicalBefore);
assert.deepEqual(live.mounted.snapshot(), {saved: "camera"});
assert.deepEqual(live.mounted.diagnostics(), {mounted: true, fixture: true});
instance.options.onSelect({kind: "paper", key: rows[1].key});
assert.deepEqual(live.selected, [{kind: "paper", key: rows[1].key}]);

// The 2D/3D buttons track the effective mode and forward only allowed live actions.
const [controls] = live.parent.children, buttons = controls.children.filter(e => e.tag === "button");
assert.deepEqual(buttons.slice(0, 2).map(e => e.textContent), ["2D", "3D"]);
assert.deepEqual(buttons.slice(0, 2).map(e => e.getAttribute("aria-pressed")), ["true", "false"]);
buttons[1].onclick(); buttons[0].onclick(); buttons[2].onclick();
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
assert.equal(JSON.stringify(rows), rowBefore); assert.equal(JSON.stringify(payload), before);
live.mounted.destroy(); live.mounted.destroy();
instance.options.onSelect({kind: "topic", key: "X"}); buttons[1].onclick(); buttons[2].onclick();
labelInput.checked = true; labelInput.onchange();
assert.equal(instance.destroys, 1); assert.equal(live.selected.length, 1);
assert.deepEqual(instance.modes, [3, 2]); assert.equal(instance.fits, 1);
assert.deepEqual(instance.labels, [true, false]);
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
assert.equal(JSON.stringify(rows), rowBefore); assert.equal(JSON.stringify(payload), before);
console.log("atlas network lifecycle, microtasks, immutable links, mode, settings and fallback contracts passed");
