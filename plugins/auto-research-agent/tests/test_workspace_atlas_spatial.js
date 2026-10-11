"use strict";
const assert = require("node:assert/strict");
const model = require("../references/research-workspace/atlas/atlas-model.js");
const spatial = require("../references/research-workspace/atlas/atlas-spatial.js");
const paper = (work, version, topics, methods) => ({work_id: work, version_id: version,
  title: "Same title <script>", authors: ["Original author"], classification: {topic_cluster: topics, method: methods}, source_ids: []});
const input = {index: {papers: [paper("a", "v1", ["X", "Y"], ["Literal A", "A"]),
  paper("a", "v2", ["Y"], ["Literal A"]), paper("b", "v1", ["X"], ["Other"]), paper("c", "v1", "Unknown", "Unknown")]}};
const before = JSON.stringify(input), records = model.papers(input), typed = (kind, key) => JSON.stringify([kind, key]);
const links = [{source: {kind: "topic", key: "X"}, target: "topic:Y", kind: "shared-topic", weight: .5},
  {source: "paper:" + records[0].key, target: records[2].key, kind: "content-similarity", similarity: .4}];
const result = spatial.buildGraph(records, model, links);
assert.equal(result.nodes.filter(n => n.kind === "paper").length, 4);
assert.equal(result.nodes.filter(n => n.kind === "topic").length, 2);
assert.equal(result.nodes.filter(n => n.kind === "method").length, 3);
assert.equal(result.links.filter(e => e.kind === "topic-membership").length, 4);
assert.equal(result.links.filter(e => e.kind === "method-membership").length, 4);
assert.equal(result.links.filter(e => e.kind === "content-similarity").length, 1);
assert.equal(result.links.filter(e => e.source === typed("paper", records[0].key) && e.kind === "topic-membership").length, 2);
const inventory = JSON.stringify(result);
assert.deepEqual(spatial.eligibleLabels(result.nodes, result.links), result.nodes.filter(n => n.kind === "topic").map(n => n.id));
const focused = {kind: "paper", key: records[0].key}, neighboring = new Set([typed("paper", focused.key)]);
assert.ok(result.links.every(edge => !spatial.incident(edge, null)));
assert.deepEqual(result.links.filter(edge => spatial.incident(edge, focused)), result.links.filter(edge => [edge.source, edge.target].includes(typed("paper", records[0].key))));
result.links.forEach(e => { if (e.source === typed("paper", focused.key)) neighboring.add(e.target); if (e.target === typed("paper", focused.key)) neighboring.add(e.source); });
assert.deepEqual(spatial.eligibleLabels(result.nodes, result.links, {focus: focused}), result.nodes.filter(n => neighboring.has(n.id)).map(n => n.id));
assert.deepEqual(spatial.eligibleLabels(result.nodes, result.links, {focus: focused, hover: typed("paper", records[3].key)}), [typed("paper", records[3].key)]);
assert.deepEqual(spatial.eligibleLabels(result.nodes, result.links, {focus: focused, showLabels: true}), result.nodes.map(n => n.id));
assert.equal(JSON.stringify(result), inventory);
assert.deepEqual(result.nodes.find(n => n.id === typed("paper", records[0].key)).methods, ["Literal A", "A"]);
assert.ok(result.nodes.every(n => [n.x, n.y, n.z, n.fx, n.fy, n.fz].every(Number.isFinite)));
assert.deepEqual(spatial.buildGraph([...records].reverse(), model, [...links].reverse()), result);
assert.equal(JSON.stringify(input), before);
assert.throws(() => spatial.buildGraph([...records, records[0]], model), /identity/);
assert.throws(() => spatial.buildGraph(records, model, [{source: records[0].key, target: "missing", kind: "content-similarity"}]), /unknown identity/);
assert.throws(() => spatial.buildGraph(records, model, [{...links[0], weight: NaN}]), /weight/);
const lexical = spatial.buildGraph(records, model, [{from: {type: "paper", key: records[0].key}, to: {type: "paper", key: records[1].key}, kind: "lexical-content", score: .7}]).links.find(e => e.kind === "lexical-content");
assert.equal(lexical.weight, .7); assert.equal(lexical.metadata.score, .7);
assert.equal(spatial.buildGraph(records, model, [{from: {type: "topic", key: "X"}, to: {type: "topic", key: "Y"}, kind: "recorded-topic-overlap", score: 3}]).links.find(e => e.kind === "recorded-topic-overlap").weight, 1);
assert.equal(spatial.buildGraph(records, model, [], true).links.filter(e => e.kind === "method-similarity").length, 1);
const topicColor = (rows, key, overrides) => spatial.buildGraph(rows, model, [], false, overrides).nodes.find(n => n.kind === "topic" && n.key === key).color;
assert.equal(topicColor(records, "Y"), topicColor(records.slice(0, 2), "Y"));
assert.equal(topicColor(records, "X", new Map([["X", "#abcdef"]])), "#abcdef");
assert.equal(topicColor(records.slice(2, 3), "X", {X: "#abcdef"}), "#abcdef");
assert.throws(() => topicColor(records, "X", {X: "url(external)"}), /color/);
assert.throws(() => topicColor(records, "X", {X: "#12345"}), /color/);
assert.equal(spatial.buildGraph(records, model, [{from: {type: "topic", key: "X"}, to: {type: "topic", key: "Y"}, kind: "lexical-topic", score: .35}]).links.find(e => e.kind === "lexical-topic").weight, .35);
const aliases = new Map(records.map((p, i) => [p.key, `Full${i + 1}`]));
assert.equal(spatial.buildGraph(records.slice(2), model, [], false, {}, aliases).nodes.find(n => n.key === records[2].key).alias, "Full3");
assert.equal(spatial.buildGraph(records.slice(2), model, [], false, {}, Object.fromEntries(aliases)).nodes.find(n => n.key === records[2].key).alias, "Full3");
assert.throws(() => spatial.buildGraph(records, model, [], false, {}, {[records[0].key]: ""}), /alias/);
const pose = {position: {x: 0, y: 0, z: 0}, target: {x: 0, y: 0, z: 0}, up: {x: 0, y: 0, z: 1}};
const planar = spatial.fitCamera([{x: 20, y: 30}], pose, {width: 320, height: 600}, 2);
assert.equal(planar.target.z, 0); assert.ok(Number.isFinite(planar.position.z));
assert.deepEqual(planar.up, {x: 0, y: 1, z: 0});
assert.throws(() => spatial.fitCamera([{x: 20, y: 30}], pose, {width: 320, height: 600}, 3), /coordinates/);
assert.throws(() => spatial.fitCamera([{x: 20, y: 30}], pose, {width: Infinity, height: 600}, 2), /viewport/);
assert.throws(() => spatial.fitCamera([{x: 20, y: 30}], pose, {width: 320, height: 600}, 4), /dimensions/);
const resolved = spatial.resolveLabels([{id: "selected", priority: 0, selected: true, projectable: true, box: {x: -20, y: -20, width: 80, height: 20}},
  {id: "hidden", priority: 3, projectable: true, box: {x: 6, y: 8, width: 80, height: 20}}], 320, 600);
assert.equal(resolved.shown[0].id, "selected"); assert.deepEqual(resolved.hidden, ["hidden"]);
const keyboardLabel = spatial.resolveLabels([{id: "keyboard", priority: 1, selected: false, focused: true, projectable: true,
  box: {x: 290, y: 310, width: 240, height: 44}}], 317, 420);
assert.equal(keyboardLabel.shown[0]?.id, "keyboard", "a focused long title must stay inside the phone viewport without becoming a selected node");
assert.equal(keyboardLabel.shown[0].selected, false); assert.deepEqual(keyboardLabel.hidden, []);
const crowdedKeyboardLabel = spatial.resolveLabels([{id: "keyboard", priority: 1, selected: false, focused: true, projectable: true,
  box: {x: 290, y: 310, width: 240, height: 44}}], 317, 420, [{x: 0, y: 0, width: 317, height: 420}]);
assert.equal(crowdedKeyboardLabel.shown[0]?.id, "keyboard", "collision reduction cannot hide the control that currently holds keyboard focus");
const pointerBox = {x: 120, y: 80, width: 124, height: 44};
for (const viewportWidth of [317, 220]) for (const width of [70, 240]) {
  const pointerLabel = spatial.resolveLabels([{id: "pointer", priority: 1, selected: false, projectable: true, pointerBox,
    anchor: {x: 180, y: 240, radius: 28}, box: {x: 35, y: 200, width, height: 44}}], viewportWidth, 420, [{x: 0, y: 0, width: viewportWidth, height: 420}]);
  const box = pointerLabel.shown[0]?.box;
  assert.ok(box && box.x <= 182 && box.x + box.width >= 182 && box.y <= 102 && box.y + box.height >= 102,
    "hover title changes must retain the existing pointer target through a click, even when ordinary placements collide");
  assert.equal(pointerLabel.shown[0].selected, false);
  assert.ok(box.x >= 0 && box.x + box.width <= viewportWidth && box.y >= 0 && box.y + box.height <= 420,
    "a hovered title stays within the current viewport after host resize");
}
const iconBox = {x: 140, y: 140, width: 40, height: 40};
const onDemand = {id: "active", priority: 0, selected: true, projectable: true, anchor: {x: 160, y: 160, radius: 20}, box: {x: 120, y: 155, width: 80, height: 20}};
const clearLabel = spatial.resolveLabels([onDemand], 320, 320, [iconBox]);
assert.equal(clearLabel.shown.length, 1);
assert.ok(clearLabel.shown[0].box.y + clearLabel.shown[0].box.height < iconBox.y);
for (const priority of [2, 3]) {
  const alternative = spatial.resolveLabels([{...onDemand, priority, selected: false}], 320, 320, [iconBox]);
  assert.equal(alternative.shown.length, 1);
  assert.ok(alternative.shown[0].box.y + alternative.shown[0].box.height < iconBox.y);
}
assert.deepEqual(spatial.resolveLabels([{...onDemand, priority: 4, selected: false}], 320, 320, [iconBox]).hidden, ["active"]);
assert.deepEqual(onDemand.box, {x: 120, y: 155, width: 80, height: 20});

// Injected DOM/runtime: actual WebGL/browser acceptance remains a separate check.
let nextFrame = 0, observerDisconnected = 0, intersectionDisconnected = 0, layoutReads = 0, domWrites = 0;
const frames = new Map();
const runLastFrame = () => { const [key, callback] = [...frames].at(-1); frames.delete(key); callback(); };
const runAllFrames = () => { while (frames.size) runLastFrame(); };
global.requestAnimationFrame = callback => { frames.set(++nextFrame, callback); return nextFrame; };
global.cancelAnimationFrame = frame => frames.delete(frame);
const resizes = [];
global.ResizeObserver = class { constructor(callback) { this.callback = callback; resizes.push(this); } observe() { this.callback(); } disconnect() { observerDisconnected++; } };
const intersections = [];
global.IntersectionObserver = class {
  constructor(callback) { this.callback = callback; intersections.push(this); }
  observe() { this.callback([{isIntersecting: true}]); }
  disconnect() { intersectionDisconnected++; }
  set(value) { this.callback([{isIntersecting: value}]); }
};
const motion = {matches: false, listeners: new Map(), addEventListener(name, callback) { this.listeners.set(name, callback); },
  removeEventListener(name, callback) { if (this.listeners.get(name) === callback) this.listeners.delete(name); },
  set(value) { this.matches = value; this.listeners.get("change")?.({matches: value}); }};
global.matchMedia = () => motion;
class Element {
  constructor(document) { this.ownerDocument = document; this.visibilityWrites = []; this.style = new Proxy({}, {set: (target, key, value) => { domWrites++; if (key === "visibility") this.visibilityWrites.push(value); target[key] = value; return true; }}); this.children = []; this.listeners = new Map(); this.attributes = {}; this.clientWidth = 600; this.clientHeight = 640; this._textContent = ""; }
  get offsetWidth() { layoutReads++; return 120; }
  get offsetHeight() { layoutReads++; return 44; }
  get textContent() { return this._textContent; }
  set textContent(value) { if (this._textContent !== value) { domWrites++; this._textContent = value; } }
  append(...children) { children.forEach(child => { child.parent = this; this.children.push(child); }); }
  remove() { if (this.parent) this.parent.children = this.parent.children.filter(child => child !== this); }
  setAttribute(name, value) { if (this.attributes[name] !== value) { domWrites++; this.attributes[name] = value; } }
  addEventListener(name, callback) { this.listeners.set(name, callback); }
  removeEventListener(name, callback) { if (this.listeners.get(name) === callback) this.listeners.delete(name); }
  emit(name, value = {}) { this.listeners.get(name)?.(value); }
}
const document = new Element(null); document.ownerDocument = document; document.visibilityState = "visible";
document.createElement = () => new Element(document); document.createElementNS = () => new Element(document);
const vector = () => ({x: 0, y: 0, z: 0, set(x, y, z) { Object.assign(this, {x, y, z}); }});
const identity = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1];
const perspective = (depth, zoom = 1) => ({matrixWorldInverse: {elements: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, -depth, 1]},
  projectionMatrix: {elements: [zoom * 2.145, 0, 0, 0, 0, zoom * 2.145, 0, 0, 0, 0, -1.0002, -1, 0, 0, -.20002, 0]}});
const projectedPaper = {id: "sphere", kind: "paper", x: 0, y: 0, z: 0}, viewport = {width: 600, height: 600};
const distant = spatial.symbolBounds(projectedPaper, perspective(800), viewport, 3, 18);
const close = spatial.symbolBounds(projectedPaper, perspective(200), viewport, 3, 18);
const zoomed = spatial.symbolBounds(projectedPaper, perspective(200, 2), viewport, 3, 18);
assert.ok(close.radius > 58 && zoomed.radius > close.radius && close.radius > distant.radius);
const nearLabel = {id: "sphere-name", priority: 0, projectable: true, anchor: {x: 300, y: 300, radius: close.radius},
  box: {x: 240, y: 321, width: 120, height: 21}};
const bounded = spatial.resolveLabels([nearLabel], 600, 600, [close]).shown[0].box;
assert.ok(bounded.y + bounded.height < close.y, "zoomed paper names cannot cover the actual rendered sphere bound");
assert.throws(() => spatial.symbolBounds(projectedPaper, perspective(200), viewport, 3, NaN), /radius/);
const created = [];
global.ForceGraph3D = () => () => {
  const config = {}, camera = {position: vector(), up: vector(), fov: 50, zoom: 1,
    matrixWorldInverse: {elements: identity}, projectionMatrix: {elements: [.002, 0, 0, 0, 0, .002, 0, 0, 0, 0, .002, .002, 0, 0, 0, 1]}, updateMatrixWorld() {}, updateProjectionMatrix() {}};
  const control = {target: vector(), noRotate: false, staticMoving: false, dynamicDampingFactor: .2, listeners: new Map(), update() {},
    addEventListener(name, callback) { this.listeners.set(name, callback); }, removeEventListener(name, callback) { if (this.listeners.get(name) === callback) this.listeners.delete(name); },
    emit(name) { this.listeners.get(name)?.(); }, trackballGesture() { if (!this.noRotate) { camera.position.x += 5; this.emit("change"); } }};
  const graph = {config, camera: () => camera, controls: () => control, disposed: 0,
    cameraPosition(position, target) { config.cameraWrites = (config.cameraWrites || 0) + 1; Object.assign(camera.position, position); Object.assign(control.target, target); return graph; },
    pauseAnimation() { config.pauseCalls = (config.pauseCalls || 0) + 1; config.paused = true; return graph; },
    resumeAnimation() {
      config.resumeCalls = (config.resumeCalls || 0) + 1;
      if (config.resumeError) throw config.resumeError;
      config.paused = false;
      control.emit("change");
      if (Object.hasOwn(config, "pendingHover")) {
        const next = config.pendingHover; delete config.pendingHover;
        if (next !== config.vendorHover) { config.vendorHover = next; config.hoverCalls = (config.hoverCalls || 0) + 1; config.onNodeHover(next); }
      }
      return graph;
    }, _destructor() { graph.disposed++; },
    numDimensions(value) { config.dimensions = value; if (value === 2) config.data?.nodes.forEach(n => { delete n.z; delete n.fz; }); return graph; },
    graphData(data) { config.data = data; const byId = new Map(data.nodes.map(n => [n.id, n])); data.links.forEach(e => { if (typeof e.source === "string") e.source = byId.get(e.source); if (typeof e.target === "string") e.target = byId.get(e.target); }); return graph; }};
  ["forceEngine", "enableNodeDrag", "showNavInfo", "backgroundColor", "nodeId", "nodeRelSize", "nodeVal", "nodeColor", "nodeOpacity", "nodeLabel", "nodeVisibility", "linkVisibility", "linkColor", "linkOpacity", "linkWidth", "onNodeClick", "onNodeHover", "cooldownTicks", "width", "height"].forEach(name => {
    graph[name] = function (...values) { if (!values.length) return config[name]; config[name] = values[0]; return graph; };
  });
  created.push(graph); return graph;
};
const host = new Element(document), selection = [];
const mounted = spatial.mount(host, {papers: records, model, extraLinks: links, mode: "3d", onSelect: item => selection.push(item)});
const first = created[0]; assert.equal(first.config.enableNodeDrag, false);
assert.ok(first.config.nodeRelSize > 7); assert.ok(first.config.nodeVal({kind: "paper"}) > 5);
assert.equal(mounted.diagnostics().showLabels, false);
const retainedNodes = first.config.data.nodes.length, retainedLinks = first.config.data.links.length;
const topics = first.config.data.nodes.filter(n => n.kind === "topic");
assert.ok(topics.every(n => first.config.nodeVisibility(n) === false));
assert.ok(first.config.data.links.every(e => !first.config.linkVisibility(e)), "initial graph has no relationship lines");
const wires = host.children[0].children[1].children;
assert.ok(wires.every(line => line.style.display === "none"), "dashed lines cannot flash before the first frame");
const wireEdges = first.config.data.links.filter(edge => edge.kind.includes("method") || edge.kind === "content-similarity");
function checkFocusedEdges(value) {
  const expected = edge => spatial.incident(edge, value);
  assert.ok(first.config.data.links.every(edge => first.config.linkVisibility(edge) === (expected(edge) && !wireEdges.includes(edge))));
  runLastFrame();
  assert.deepEqual(wires.map(line => line.style.display !== "none"), wireEdges.map(expected));
  assert.equal(mounted.diagnostics().focusedRelations, first.config.data.links.filter(expected).length);
}
checkFocusedEdges(null);
first.config.onNodeHover(first.config.data.nodes[0]); checkFocusedEdges(null);
first.config.onNodeHover(null);
const markers = host.children[0].children[2].children.filter(node => node.className === "atlas-spatial-topic-marker");
assert.equal(markers.length, topics.length); assert.equal(markers[0].attributes["aria-label"], "Direction node: " + topics[0].label);
assert.equal(markers[0].style.width, "44px"); assert.equal(markers[0].style.height, "44px");
assert.equal(markers[0].style.transform, "translate(-50%, -50%)");
assert.equal(markers[0].children[0].style.width, "26px"); assert.equal(markers[0].children[0].style.transform, "rotate(45deg)");
const methodNodes = first.config.data.nodes.filter(n => n.kind === "method");
const methodMarkers = host.children[0].children[2].children.filter(node => node.className === "atlas-spatial-method-marker");
assert.equal(methodMarkers.length, methodNodes.length);
assert.ok(methodNodes.every(node => !first.config.nodeVisibility(node)), "method cubes replace paper-like WebGL spheres");
assert.equal(methodMarkers[0].attributes["aria-label"], "Method node: " + methodNodes[0].label);
assert.equal(methodMarkers[0].style.width, "44px"); assert.equal(methodMarkers[0].style.height, "44px");
assert.equal(methodMarkers[0].children[0].style.width, "22px");
assert.equal(methodMarkers[0].children[0].children[0].children.length, 3, "cube has three bounded SVG faces");
const labelButtons = host.children[0].children[2].children.filter(node => node.className?.startsWith("atlas-spatial-label "));
assert.deepEqual(labelButtons.map(button => [button.attributes["data-node-key"], button.attributes["data-node-kind"]]),
  result.nodes.map(node => [node.id, node.kind]), "projected labels preserve exact typed node identities for focus across title changes");
assert.ok(labelButtons.every(button => button.style.minWidth === "44px" && button.style.minHeight === "44px"));
runAllFrames(); const spatialMarkers = mounted.diagnostics().topicMarkers;
assert.ok(mounted.diagnostics().methodMarkers.every(marker => marker.shape === "cube"));
assert.ok(methodMarkers.every(marker => marker.attributes["data-node-shape"] === "cube"));
assert.equal(frames.size, 0, "idle renderer stops scheduling frames");
assert.equal(first.config.paused, true); assert.equal(mounted.diagnostics().lifecycle.rendererRunning, false);
const shell = host.children[0], readsAtIdle = layoutReads, writesAtIdle = domWrites;
const pointerResume = first.config.resumeCalls || 0;
shell.emit("pointerdown"); assert.equal(first.config.resumeCalls, pointerResume + 1); assert.equal(first.config.paused, false); runLastFrame();
assert.equal(layoutReads, readsAtIdle); assert.equal(domWrites, writesAtIdle);
assert.equal(frames.size, 1, "active pointer keeps navigation projection live");
document.emit("pointerup"); runAllFrames(); assert.equal(frames.size, 0);
assert.ok(first.config.resumeCalls > pointerResume); assert.equal(first.config.paused, true);
shell.emit("pointerdown"); document.emit("pointercancel"); runAllFrames();
assert.equal(mounted.diagnostics().lifecycle.pointerActive, false); assert.equal(first.config.paused, true);
const dampingPause = first.config.pauseCalls;
first.controls().trackballGesture(); runLastFrame();
assert.equal(first.config.paused, false); assert.ok(frames.size > 0, "camera changes receive bounded settling frames");
first.camera().position.x += 1; first.controls().emit("change"); runLastFrame(); runAllFrames();
assert.ok(first.config.pauseCalls > dampingPause); assert.equal(first.config.paused, true);
const hoverPaper = first.config.data.nodes.find(node => node.kind === "paper");
first.config.pendingHover = hoverPaper; const hoverResume = first.config.resumeCalls;
shell.emit("pointermove"); assert.equal(first.config.resumeCalls, hoverResume + 1);
assert.equal(mounted.diagnostics().hover, hoverPaper.id); runAllFrames(); assert.equal(first.config.paused, true);
const samePaperCalls = first.config.hoverCalls; const leaveResume = first.config.resumeCalls;
shell.emit("pointerleave");
assert.equal(mounted.diagnostics().hover, null, "leaving the shell clears public hover immediately");
assert.equal(first.config.resumeCalls, leaveResume + 1, "shell leave wakes paused vendor raycasting once");
runAllFrames(); assert.equal(first.config.paused, true);
first.config.pendingHover = hoverPaper; shell.emit("pointermove");
assert.equal(mounted.diagnostics().hover, hoverPaper.id, "the same paper can be hovered after re-entry");
assert.equal(first.config.hoverCalls, samePaperCalls, "vendor suppresses callbacks for its retained raycast object");
runAllFrames(); assert.equal(first.config.paused, true);
const otherHoverPaper = first.config.data.nodes.find(node => node.kind === "paper" && node !== hoverPaper);
shell.emit("pointerleave"); runAllFrames(); first.config.pendingHover = otherHoverPaper; shell.emit("pointermove");
assert.equal(mounted.diagnostics().hover, otherHoverPaper.id, "a different paper replaces retained vendor hover");
runAllFrames(); assert.equal(first.config.paused, true);
shell.emit("pointerleave"); runAllFrames(); first.config.pendingHover = null; shell.emit("pointermove");
assert.equal(mounted.diagnostics().hover, null, "blank re-entry clears retained hover in the vendor cycle");
runAllFrames(); assert.equal(mounted.diagnostics().hover, null); assert.equal(first.config.paused, true);
const topicMarker = markers[0], topicLabel = labelButtons.find(button => button.textContent === topics[0].label);
topicMarker.emit("pointerenter"); topicLabel.emit("pointerleave");
assert.equal(mounted.diagnostics().hover, topics[0].id, "another control cannot clear the active pointer source");
runAllFrames(); first.config.pendingHover = otherHoverPaper; shell.emit("pointermove");
assert.equal(mounted.diagnostics().hover, topics[0].id, "vendor callbacks cannot replace active marker hover");
runAllFrames(); topicMarker.emit("pointerleave"); assert.equal(mounted.diagnostics().hover, otherHoverPaper.id);
topicLabel.emit("pointerenter"); runAllFrames();
host.clientWidth = shell.clientWidth = 220; resizes[0].callback(); runAllFrames();
assert.equal(topicLabel.style.maxWidth, "212px", "hovered DOM label width follows the resized host");
assert.ok(parseFloat(topicLabel.style.minWidth) <= 212);
assert.ok(mounted.diagnostics().labelRects.every(box => box.x >= 0 && box.x + box.width <= 220));
host.clientWidth = shell.clientWidth = 600; resizes[0].callback(); runAllFrames();
first.config.pendingHover = hoverPaper; shell.emit("pointermove");
assert.equal(mounted.diagnostics().hover, topics[0].id, "vendor callbacks cannot replace active label hover");
runAllFrames(); topicLabel.emit("pointerleave"); assert.equal(mounted.diagnostics().hover, hoverPaper.id);
topicMarker.emit("pointerenter"); topicMarker.emit("focus"); topicMarker.emit("pointerleave");
assert.equal(mounted.diagnostics().hover, topics[0].id, "pointer leave preserves keyboard focus");
topicLabel.emit("blur"); assert.equal(mounted.diagnostics().hover, topics[0].id, "another control cannot clear the active focus source");
shell.emit("pointerleave"); assert.equal(mounted.diagnostics().hover, topics[0].id, "shell leave preserves keyboard focus");
shell.emit("pointermove"); topicMarker.emit("pointerenter"); topicMarker.emit("blur");
assert.equal(mounted.diagnostics().hover, topics[0].id, "blur preserves active DOM pointer hover");
topicMarker.emit("pointerleave"); assert.equal(mounted.diagnostics().hover, hoverPaper.id);
shell.emit("pointerleave"); assert.equal(mounted.diagnostics().hover, null, "removing all DOM sources outside restores null");
runAllFrames(); shell.emit("pointermove"); assert.equal(mounted.diagnostics().hover, hoverPaper.id, "inside with no DOM source restores vendor hover"); runAllFrames();
first.config.resumeError = new Error("synthetic-resume-failure");
assert.throws(() => shell.emit("keydown", {key: "ArrowRight"}), /synthetic-resume-failure/);
assert.equal(mounted.diagnostics().lifecycle.rendererRunning, false); assert.equal(frames.size, 0);
delete first.config.resumeError;
shell.emit("keydown", {key: "ArrowRight"}); assert.equal(frames.size, 1); runAllFrames();
document.visibilityState = "hidden"; document.emit("visibilitychange");
const hiddenReads = layoutReads, hiddenWrites = domWrites, hiddenCameraWrites = first.config.cameraWrites;
first.camera().projectionMatrix.elements[12] = 3; first.controls().emit("change");
assert.equal(mounted.fit(), true); assert.equal(first.config.cameraWrites, hiddenCameraWrites);
assert.equal(frames.size, 0); assert.equal(mounted.diagnostics().lifecycle.pageVisible, false); assert.equal(first.config.paused, true);
assert.equal(layoutReads, hiddenReads); assert.equal(domWrites, hiddenWrites);
document.visibilityState = "visible"; document.emit("visibilitychange"); runAllFrames();
assert.ok(first.config.cameraWrites > hiddenCameraWrites); assert.equal(first.config.paused, true);
assert.ok(mounted.diagnostics().topicMarkers.every(marker => !marker.visible));
first.camera().projectionMatrix.elements[12] = 0; first.controls().emit("change"); runAllFrames();
intersections[0].set(false); const offscreenReads = layoutReads, offscreenWrites = domWrites;
first.camera().projectionMatrix.elements[12] = 3; first.controls().emit("change");
assert.equal(frames.size, 0); assert.equal(mounted.diagnostics().lifecycle.intersecting, false); assert.equal(first.config.paused, true);
assert.equal(layoutReads, offscreenReads); assert.equal(domWrites, offscreenWrites);
intersections[0].set(true); runAllFrames(); assert.ok(mounted.diagnostics().topicMarkers.every(marker => !marker.visible));
first.camera().projectionMatrix.elements[12] = 0; first.controls().emit("change"); runAllFrames();
motion.set(true); runAllFrames();
assert.equal(first.controls().staticMoving, true); assert.equal(first.controls().dynamicDampingFactor, 0); assert.equal(first.config.paused, true);
shell.emit("pointerdown"); runAllFrames();
assert.equal(frames.size, 0); assert.equal(mounted.diagnostics().lifecycle.reducedMotion, true); assert.equal(first.config.paused, true);
document.emit("pointerup"); motion.set(false); runAllFrames();
assert.equal(first.controls().staticMoving, false); assert.equal(first.controls().dynamicDampingFactor, .2);
shell.clientWidth = 620; resizes[0].callback(); assert.equal(first.config.width, 620); runAllFrames();
methodMarkers[0].listeners.get("click")();
assert.deepEqual(selection.pop(), {kind: "method", key: methodNodes[0].key});
methodMarkers[0].listeners.get("focus")(); assert.equal(mounted.diagnostics().hover, methodNodes[0].id);
methodMarkers[0].listeners.get("blur")(); assert.equal(mounted.diagnostics().hover, hoverPaper.id);
assert.ok(spatialMarkers.some(marker => marker.visible));
first.camera().projectionMatrix.elements[12] = 3; first.controls().emit("change"); runAllFrames();
assert.ok(mounted.diagnostics().topicMarkers.every(marker => !marker.visible));
assert.ok(markers.every(marker => marker.style.visibility === "hidden"));
first.camera().projectionMatrix.elements[12] = 0; first.controls().emit("change"); runAllFrames();
assert.equal(mounted.setLabels(true), true); assert.equal(mounted.diagnostics().eligibleLabelIds.length, retainedNodes);
checkFocusedEdges(null);
assert.throws(() => mounted.setLabels("yes"), /boolean/); mounted.setLabels(false);
assert.ok(topics.every(n => first.config.nodeVisibility(n) === false));
assert.equal(host.children.length, 1); assert.equal(mounted.diagnostics().papers, 4);
assert.equal(mounted.setFocus({kind: "paper", key: "stale"}), false);
assert.equal(mounted.setFocus({kind: "paper", key: records[0].key}), true);
assert.equal(mounted.setFocus({type: "paper", key: records[0].key}), true);
checkFocusedEdges(focused);
first.config.onNodeHover(first.config.data.nodes.find(n => n.key === records[3].key));
checkFocusedEdges(focused);
assert.deepEqual(mounted.diagnostics().eligibleLabelIds, [typed("paper", records[3].key)]);
first.config.onNodeHover(null); assert.deepEqual(mounted.diagnostics().focus, focused);
mounted.setFocus({kind: "topic", key: topics[0].key}); checkFocusedEdges({kind: "topic", key: topics[0].key});
mounted.setFocus({kind: "method", key: methodNodes[0].key}); checkFocusedEdges({kind: "method", key: methodNodes[0].key});
mounted.setFocus(null); checkFocusedEdges(null);
mounted.setFocus(focused); checkFocusedEdges(focused);
labelButtons[0].emit("focus"); runAllFrames(); labelButtons[0].visibilityWrites = [];
first.camera().position.x += 1; first.controls().emit("change"); runAllFrames();
assert.equal(labelButtons[0].visibilityWrites.includes("hidden"), false, "redrawing a visible focused label cannot temporarily hide it and drop keyboard focus");
labelButtons[0].emit("blur"); runAllFrames();
assert.equal(first.config.data.nodes.length, retainedNodes); assert.equal(first.config.data.links.length, retainedLinks);
first.config.onNodeClick(first.config.data.nodes.find(n => n.key === records[0].key));
assert.deepEqual(selection, [{kind: "paper", key: records[0].key}]);
markers[0].listeners.get("click")(); assert.deepEqual(selection.at(-1), {kind: "topic", key: topics[0].key});
const lateMarkerClick = markers[0].listeners.get("click");
markers[0].listeners.get("focus")(); assert.equal(mounted.diagnostics().hover, topics[0].id);
markers[0].listeners.get("blur")(); assert.equal(mounted.diagnostics().hover, null);
assert.equal(first.config.nodeLabel(first.config.data.nodes[0]).textContent, "Same title <script>");
mounted.fit(); const saved = mounted.snapshot(); assert.ok(Number.isFinite(saved.position.z));
first.camera().position.set(200, 140, 520); first.controls().target.set(30, -20, 20);
const orbitPose = mounted.snapshot();
mounted.setMode("2d"); const staleFit = [...frames.values()].at(-1);
mounted.fit(); assert.equal(mounted.diagnostics().mode, 2);
checkFocusedEdges(focused);
assert.equal(mounted.diagnostics().navigation.noRotate, true); assert.equal(first.controls().enableRotate, false);
const planarPose = mounted.snapshot().position; first.controls().trackballGesture(); assert.deepEqual(mounted.snapshot().position, planarPose);
runAllFrames(); assert.notDeepEqual(mounted.diagnostics().topicMarkers.map(p => [p.x, p.y]), spatialMarkers.map(p => [p.x, p.y]));
assert.ok(mounted.diagnostics().methodMarkers.every(marker => marker.shape === "square"));
assert.ok(methodMarkers.every(marker => marker.children[0].style.height === "22px" && marker.children[0].children[0].style.display === "none"));
assert.equal(mounted.snapshot().target.z, 0); assert.ok(first.config.data.nodes.every(n => n.z === 0));
const priorWrites = first.config.cameraWrites;
mounted.setMode("3d"); assert.deepEqual(mounted.snapshot().position, orbitPose.position); assert.deepEqual(mounted.snapshot().target, orbitPose.target);
checkFocusedEdges(focused);
assert.equal(mounted.diagnostics().navigation.noRotate, false); assert.equal(first.controls().enableRotate, true);
assert.equal(first.controls().staticMoving, false); assert.equal(first.controls().dynamicDampingFactor, .2);
runAllFrames(); assert.ok(methodMarkers.every(marker => marker.attributes["data-node-shape"] === "cube" && marker.children[0].children[0].style.display === "block"));
assert.equal(frames.size, 0); mounted.fit(); assert.ok(first.config.data.nodes.every(n => Number.isFinite(n.z)));
const currentWrites = first.config.cameraWrites; staleFit(); assert.equal(first.config.cameraWrites, currentWrites);
assert.ok(currentWrites > priorWrites);
const rotatingPose = mounted.snapshot().position; first.controls().trackballGesture(); assert.equal(mounted.snapshot().position.x, rotatingPose.x + 5);
const remountPose = mounted.snapshot();
const replacement = spatial.mount(host, {papers: records, model, mode: "3d", pose: remountPose, language: "zh-Hant"});
assert.equal(first.disposed, 1); assert.equal(mounted.diagnostics().destroyed, true);
assert.deepEqual(replacement.snapshot(), remountPose); assert.equal(host.children.length, 1);
assert.ok(host.children[0].children[2].children.find(node => node.className === "atlas-spatial-topic-marker").attributes["aria-label"].startsWith("方向節點："));
first.config.onNodeClick(first.config.data.nodes[0]); lateMarkerClick(); assert.equal(selection.length, 2);
assert.ok(markers.every(marker => marker.listeners.size === 0));
assert.ok(methodMarkers.every(marker => marker.listeners.size === 0));
first.config.onNodeHover(first.config.data.nodes[0]); assert.equal(mounted.diagnostics().hover, null);
replacement.setMode("2d"); assert.deepEqual(replacement.snapshot().position, remountPose.poses[2].position); assert.ok(frames.size > 0);
const replacementShell = host.children[0];
const replacementResumes = created[1].config.resumeCalls || 0;
replacement.destroy(); replacement.destroy();
assert.equal(created[1].disposed, 1); assert.equal(observerDisconnected, 2); assert.equal(intersectionDisconnected, 2);
assert.equal(frames.size, 0); assert.equal(host.children.length, 0);
assert.equal(replacementShell.listeners.size, 0); assert.equal(document.listeners.size, 0); assert.equal(motion.listeners.size, 0);
assert.equal(created[1].controls().listeners.size, 0);
replacementShell.emit("pointerdown"); replacementShell.emit("pointermove"); document.emit("pointerup"); created[1].controls().emit("change");
assert.equal(created[1].config.resumeCalls || 0, replacementResumes); assert.equal(frames.size, 0);
assert.equal(replacement.setFocus({kind: "paper", key: records[0].key}), false);
const healthyFactory = global.ForceGraph3D;
global.ForceGraph3D = () => canvas => { const graph = healthyFactory()(canvas); graph.forceEngine = () => { throw new Error("Injected setup failure"); }; return graph; };
assert.throws(() => spatial.mount(host, {papers: records, model}), /Injected setup failure/);
assert.equal(created.at(-1).disposed, 1); assert.equal(host.children.length, 0); assert.equal(frames.size, 0);
global.ForceGraph3D = healthyFactory;
assert.equal(JSON.stringify(input), before);
console.log("atlas spatial identity, finite mode, selection, pose, level-of-detail and disposal regressions passed");
