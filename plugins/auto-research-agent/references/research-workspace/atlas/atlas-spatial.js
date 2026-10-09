/* Offline WebGL presentation adapter. Positions and computed links are not evidence. */
(function (root) {
  "use strict";
  const axes = ["x", "y", "z"], palette = ["#77c9c4", "#94b8df", "#d8ba7b", "#bd9dce", "#dcaaa4", "#a8c6ae"];
  const id = (kind, key) => JSON.stringify([kind, key]);
  const compare = (a, b) => a < b ? -1 : a > b ? 1 : 0;
  const hash = value => { let h = 2166136261; for (const c of value) h = Math.imul(h ^ c.charCodeAt(0), 16777619); return h >>> 0; };
  const point = (p, mode = 3) => ({x: p?.x, y: p?.y, z: mode === 2 ? 0 : p?.z});
  const finite = p => !!p && axes.every(a => Number.isFinite(p[a]));
  const dot = (a, b) => axes.reduce((sum, axis) => sum + a[axis] * b[axis], 0);
  const subtract = (a, b) => Object.fromEntries(axes.map(axis => [axis, a[axis] - b[axis]]));
  const normalize = (p, fallback) => { const n = Math.hypot(p.x, p.y, p.z); return n > 1e-9 ? Object.fromEntries(axes.map(a => [a, p[a] / n])) : {...fallback}; };
  const cross = (a, b) => ({x: a.y * b.z - a.z * b.y, y: a.z * b.x - a.x * b.z, z: a.x * b.y - a.y * b.x});
  const endpoint = value => {
    if (value && typeof value === "object") return id(value.kind || value.type, value.key);
    if (typeof value !== "string") throw new TypeError("Missing graph endpoint");
    for (const kind of ["paper", "topic", "method"]) if (value.startsWith(kind + ":")) return id(kind, value.slice(kind.length + 1));
    return id("paper", value);
  };
  function buildGraph(papers, model, extraLinks = [], similarity = false, topicColors = {}, paperAliases = {}) {
    if (!Array.isArray(papers) || !model?.networkLayout || !model?.groups) throw new TypeError("Missing canonical graph model");
    const rows = [...papers].sort((a, b) => compare(a.key, b.key));
    if (rows.some(p => typeof p.key !== "string") || new Set(rows.map(p => p.key)).size !== rows.length) throw new TypeError("Duplicate or missing paper identity");
    const layout = model.networkLayout(rows, {singleMethods: true});
    const groups = model.groups(rows), methods = model.groups(rows, "methods");
    const positions = new Map(layout.papers.map(p => [p.key, p]));
    const overrides = new Map(topicColors instanceof Map ? topicColors : Object.entries(topicColors || {}));
    const aliases = new Map(paperAliases instanceof Map ? paperAliases : Object.entries(paperAliases || {}));
    const colors = new Map(groups.map(g => {
      const color = overrides.get(g.key);
      if (color !== undefined && (typeof color !== "string" || !/^#(?:[0-9a-f]{3}|[0-9a-f]{4}|[0-9a-f]{6}|[0-9a-f]{8})$/i.test(color))) throw new TypeError("Invalid topic color");
      return [g.key, color || palette[hash(g.key) % palette.length]];
    }));
    const nodes = [], links = [], seen = new Set();
    function node(kind, key, label, position, color, ids = []) {
      const seed = hash(id(kind, key));
      const result = {id: id(kind, key), kind, key, label, color, ids: [...ids],
        x: position.x - layout.width / 2, y: layout.height / 2 - position.y, z: (seed % 361 - 180) * .9};
      nodes.push(result); return result;
    }
    rows.forEach((paper, i) => {
      const position = positions.get(paper.key);
      if (!position) throw new TypeError("Layout lost paper identity");
      const alias = aliases.get(paper.key) ?? `P${String(i + 1).padStart(2, "0")}`;
      if (typeof alias !== "string" || !alias.trim() || alias.length > 32) throw new TypeError("Invalid paper alias");
      const author = String(paper.authors?.[0] || paper.work_id || paper.title).replace(/[-_]/g, " ");
      const n = node("paper", paper.key, `${alias} · ${author.slice(0, 21)}`, position, colors.get(position.primaryGroupKey) || "#aab8c8");
      n.alias = alias; n.title = paper.title; n.topics = [...(paper.topics || [])]; n.methods = [...(paper.methods || [])];
    });
    groups.forEach(g => node("topic", g.key, g.label, layout.groups.find(p => p.key === g.key), colors.get(g.key), g.ids));
    methods.forEach(g => node("method", g.key, g.label, layout.methods.find(p => p.key === g.key), "#b4bfcf", g.ids));
    const byId = new Map(nodes.map(n => [n.id, n]));
    function link(source, target, kind, weight = 1, metadata) {
      if (!byId.has(source) || !byId.has(target)) throw new TypeError("Graph link has unknown identity");
      if (source === target) return;
      const identity = JSON.stringify([kind, ...[source, target].sort(compare)]);
      if (seen.has(identity)) return;
      if (!Number.isFinite(weight) || weight < 0 || weight > 1) throw new TypeError("Invalid graph weight");
      seen.add(identity); links.push({source, target, kind, weight, ...(metadata ? {metadata} : {})});
    }
    groups.forEach(g => g.ids.forEach(key => link(id("paper", key), id("topic", g.key), "topic-membership")));
    methods.forEach(g => g.ids.forEach(key => link(id("paper", key), id("method", g.key), "method-membership")));
    extraLinks.forEach(edge => {
      if (typeof edge.kind !== "string" || !edge.kind) throw new TypeError("Missing graph relationship kind");
      const weight = edge.weight ?? edge.similarity ?? (edge.kind.startsWith("lexical-") ? edge.score : 1);
      link(endpoint(edge.source || edge.from), endpoint(edge.target || edge.to), edge.kind, weight, JSON.parse(JSON.stringify(edge)));
    });
    if (similarity) rows.forEach(paper => model.local(rows, paper.key).forEach(other => {
      link(id("paper", paper.key), id("paper", other.paper.key), "method-similarity", other.similarity);
    }));
    links.sort((a, b) => compare(JSON.stringify([a.kind, a.source, a.target]), JSON.stringify([b.kind, b.source, b.target])));
    // Bounded springs pull recorded/explicit computed associations together. Freeze afterwards.
    const anchors = new Map(nodes.map(n => [n.id, point(n)]));
    for (let round = 0; round < 60; round++) {
      const delta = new Map(nodes.map(n => [n.id, {x: 0, y: 0, z: 0}]));
      links.forEach(edge => {
        const a = byId.get(edge.source), b = byId.get(edge.target), d = subtract(b, a), length = Math.hypot(d.x, d.y, d.z) || 1;
        const target = edge.kind.includes("membership") ? 115 : 155;
        const strength = edge.kind === "content-similarity" || edge.kind.startsWith("lexical-") ? .011 : .018;
        const scale = Math.max(-10, Math.min(10, (length - target) * strength * edge.weight)) / length;
        axes.forEach(axis => { delta.get(a.id)[axis] += d[axis] * scale; delta.get(b.id)[axis] -= d[axis] * scale; });
      });
      nodes.forEach((a, i) => nodes.slice(i + 1).forEach(b => {
        let d = subtract(a, b), length = Math.hypot(d.x, d.y, d.z);
        if (length < 1e-6) { d = {x: 1, y: .3, z: .2}; length = Math.hypot(d.x, d.y, d.z); }
        if (length < 58) axes.forEach(axis => { const push = d[axis] / length * (58 - length) * .08; delta.get(a.id)[axis] += push; delta.get(b.id)[axis] -= push; });
      }));
      nodes.forEach(n => axes.forEach(axis => { n[axis] += delta.get(n.id)[axis] + (anchors.get(n.id)[axis] - n[axis]) * .006; }));
    }
    nodes.forEach(n => axes.forEach(axis => { n[axis] = Math.round(n[axis] * 100) / 100; n["f" + axis] = n[axis]; }));
    return {nodes, links};
  }
  function fitCamera(points, pose, viewport, mode) {
    if (mode !== 2 && mode !== 3) throw new TypeError("Unsupported graph dimensions");
    if (!finite(pose?.position) || !finite(pose?.target)) throw new TypeError("Non-finite camera pose");
    const {width, height, fov = 50} = viewport;
    if (![width, height, fov].every(Number.isFinite) || !(width > 0 && height > 0 && fov > 0 && fov < 150)) throw new TypeError("Invalid graph viewport");
    const rows = points.map(p => point(p, mode));
    if (!rows.length || rows.some(p => !finite(p))) throw new TypeError("Non-finite graph coordinates");
    const target = Object.fromEntries(axes.map(a => [a, (Math.min(...rows.map(p => p[a])) + Math.max(...rows.map(p => p[a]))) / 2]));
    const direction = mode === 2 ? {x: 0, y: 0, z: 1} : normalize(subtract(pose.position, pose.target), {x: 0, y: 0, z: 1});
    let up = mode === 2 ? {x: 0, y: 1, z: 0} : normalize(finite(pose.up) ? pose.up : {x: 0, y: 1, z: 0}, {x: 0, y: 1, z: 0});
    if (Math.abs(dot(up, direction)) > .98) up = {x: 1, y: 0, z: 0};
    const right = normalize(cross(up, direction), {x: 1, y: 0, z: 0}); up = normalize(cross(direction, right), {x: 0, y: 1, z: 0});
    const tangent = Math.tan(fov * Math.PI / 360), vertical = tangent * .87, horizontal = tangent * width / height * .87;
    let distance = 100;
    rows.forEach(p => { const d = subtract(p, target); distance = Math.max(distance, dot(d, direction) + Math.max(Math.abs(dot(d, up)) / vertical, Math.abs(dot(d, right)) / horizontal) + 28); });
    return {position: Object.fromEntries(axes.map(a => [a, target[a] + direction[a] * distance])), target, up, mode};
  }
  function project(position, camera, width, height) {
    const multiply = (m, v) => [0, 1, 2, 3].map(row => m[row] * v[0] + m[row + 4] * v[1] + m[row + 8] * v[2] + m[row + 12] * v[3]);
    const local = multiply(camera.matrixWorldInverse.elements, [position.x, position.y, position.z, 1]);
    const clip = multiply(camera.projectionMatrix.elements, local), w = clip[3];
    if (!Number.isFinite(w) || w <= 0 || clip.some(v => !Number.isFinite(v))) return null;
    const x = clip[0] / w, y = clip[1] / w, z = clip[2] / w;
    return z < -1 || z > 1 ? null : {x: (x + 1) * width / 2, y: (1 - y) * height / 2};
  }
  function symbolBounds(node, camera, viewport, mode, nodeRadius) {
    const center = project(point(node, mode), camera, viewport.width, viewport.height);
    if (!center) return null;
    let radius = node.kind === "topic" ? 19 : node.kind === "method" ? 16 : 14;
    if (node.kind === "paper") {
      if (!Number.isFinite(nodeRadius) || nodeRadius <= 0) throw new TypeError("Invalid rendered paper radius");
      // Project the enclosing world-space cube: conservative even while orbiting/zooming.
      const corners = [];
      for (const x of [-1, 1]) for (const y of [-1, 1]) for (const z of [-1, 1]) {
        const position = point(node, mode);
        corners.push(project({x: position.x + x * nodeRadius, y: position.y + y * nodeRadius, z: position.z + z * nodeRadius}, camera, viewport.width, viewport.height));
      }
      radius = corners.some(corner => !corner) ? Math.max(viewport.width, viewport.height) * 2
        : Math.max(radius, ...corners.flatMap(corner => [Math.abs(corner.x - center.x), Math.abs(corner.y - center.y)]));
    }
    return {id: node.id, kind: node.kind, x: center.x - radius, y: center.y - radius, width: radius * 2, height: radius * 2, radius};
  }
  function resolveLabels(items, width, height, obstacles = []) {
    const shown = [], hidden = [], intersects = (a, b) => a.x < b.x + b.width + 5 && a.x + a.width + 5 > b.x && a.y < b.y + b.height + 5 && a.y + a.height + 5 > b.y;
    [...items].sort((a, b) => a.priority - b.priority || compare(a.id, b.id)).forEach(item => {
      const box = {...item.box};
      if (item.selected && item.projectable) { box.x = Math.max(4, Math.min(width - box.width - 4, box.x)); box.y = Math.max(4, Math.min(height - box.height - 4, box.y)); }
      const choices = [box];
      if (item.anchor && item.priority <= 3) {
        const {x, y, radius} = item.anchor;
        choices.push({...box, x: x - box.width / 2, y: y - radius - box.height - 7},
          {...box, x: x + radius + 7, y: y - box.height / 2}, {...box, x: x - radius - box.width - 7, y: y - box.height / 2});
      }
      const available = item.projectable && choices.find(candidate => candidate.x >= 0 && candidate.y >= 0 && candidate.x + candidate.width <= width && candidate.y + candidate.height <= height
        && !obstacles.some(obstacle => intersects(candidate, obstacle)) && !shown.some(other => intersects(candidate, other.box)));
      if (available) shown.push({...item, box: available}); else hidden.push(item.id);
    });
    return {shown, hidden};
  }
  function eligibleLabels(nodes, links, state = {}) {
    if (state.showLabels === true) return nodes.map(n => n.id);
    const focus = state.focus && id(state.focus.kind || state.focus.type, state.focus.key), active = state.hover || focus;
    if (!active) return nodes.filter(n => n.kind === "topic").map(n => n.id);
    const found = new Set([active]);
    links.forEach(edge => {
      const source = edge.source.id || edge.source, target = edge.target.id || edge.target;
      if (source === active) found.add(target); if (target === active) found.add(source);
    });
    return nodes.filter(n => found.has(n.id)).map(n => n.id);
  }
  function incident(edge, focus) {
    if (!focus) return false;
    const key = id(focus.kind || focus.type, focus.key);
    return (edge.source.id || edge.source) === key || (edge.target.id || edge.target) === key;
  }
  const mounts = new WeakMap();
  function mount(host, options) {
    if (!host || typeof root.ForceGraph3D !== "function") throw new TypeError("Offline graph runtime unavailable");
    mounts.get(host)?.destroy();
    const document = host.ownerDocument, source = buildGraph(options.papers, options.model, options.extraLinks || [], options.similarity === true, options.topicColors, options.paperAliases);
    const original = new Map(source.nodes.map(n => [n.id, point(n)])), byId = new Map(source.nodes.map(n => [n.id, n]));
    const shell = document.createElement("div"), canvas = document.createElement("div"), overlay = document.createElement("div");
    const wire = document.createElementNS("http://www.w3.org/2000/svg", "svg"), wireByLink = new Map();
    shell.className = "atlas-spatial"; canvas.className = "atlas-spatial-canvas"; overlay.className = "atlas-spatial-labels";
    Object.assign(shell.style, {position: "relative", width: "100%", height: "100%", overflow: "hidden", background: "#0e1827"});
    Object.assign(canvas.style, {position: "absolute", inset: "0"}); Object.assign(overlay.style, {position: "absolute", inset: "0", pointerEvents: "none"});
    Object.assign(wire.style, {position: "absolute", inset: "0", width: "100%", height: "100%", pointerEvents: "none"});
    shell.append(canvas, wire, overlay); host.append(shell);
    let graph, mode = options.mode === 2 || options.mode === "2d" ? 2 : 3, dead = false, focus = null, hover = null, showLabels = options.showLabels === true, frame = 0, pendingFit = 0, generation = 0, labels = {shown: [], hidden: []}, lastPose = null;
    const faults = [], controls = [], labelById = new Map(), markerById = new Map(), modePoses = new Map();
    let topicMarkers = [], methodMarkers = [], symbolRects = [];
    const copyPose = (pose, dimension) => ({position: point(pose.position), target: point(pose.target),
      up: finite(pose.up) ? point(pose.up) : {x: 0, y: 1, z: 0}, mode: dimension, zoom: pose.zoom});
    Object.entries(options.pose?.poses || {}).forEach(([dimension, pose]) => {
      if (["2", "3"].includes(dimension) && finite(pose?.position) && finite(pose?.target)) modePoses.set(Number(dimension), copyPose(pose, Number(dimension)));
    });
    const size = () => ({width: Math.max(1, shell.clientWidth || host.clientWidth || 600), height: Math.max(1, shell.clientHeight || host.clientHeight || 640)});
    const selected = n => focus?.kind === n.kind && focus.key === n.key;
    const related = n => !focus || selected(n) || source.links.some(e => (e.source.id || e.source) === id(focus.kind, focus.key) && (e.target.id || e.target) === n.id || (e.target.id || e.target) === id(focus.kind, focus.key) && (e.source.id || e.source) === n.id);
    const activePaper = () => focus?.kind === "paper" ? focus.key : byId.get(hover)?.kind === "paper" ? byId.get(hover).key : null;
    const visible = n => showLabels || n.kind !== "method" || n.ids.length > 1 || selected(n) || n.id === hover || n.ids.includes(activePaper());
    const meshVisible = n => n.kind === "paper" && visible(n);
    const lexical = edge => edge.kind === "content-similarity" || edge.kind.startsWith("lexical-");
    const dashed = edge => edge.kind.includes("method") || lexical(edge);
    const shownEdge = edge => incident(edge, focus) && visible(typeof edge.source === "object" ? edge.source : byId.get(edge.source)) && visible(typeof edge.target === "object" ? edge.target : byId.get(edge.target));
    const solidEdge = edge => !dashed(edge) && shownEdge(edge);
    const select = n => { if (!dead) options.onSelect?.({kind: n.kind, key: n.key}); };
    function bindNode(button, n) {
      const callback = () => select(n); button.addEventListener("click", callback); controls.push([button, "click", callback]);
      for (const name of ["pointerenter", "focus", "pointerleave", "blur"]) {
        const update = () => { if (!dead) { hover = ["pointerenter", "focus"].includes(name) ? n.id : null; graph.nodeVisibility(meshVisible); } };
        button.addEventListener(name, update); controls.push([button, name, update]);
      }
    }
    const snapshot = () => {
      if (dead || !graph) return lastPose;
      const camera = graph.camera(), target = graph.controls().target;
      const pose = {position: point(camera.position), target: point(target), up: point(camera.up), mode, zoom: camera.zoom};
      if (!finite(pose.position) || !finite(pose.target) || !finite(pose.up)) return lastPose;
      modePoses.set(mode, copyPose(pose, mode));
      return {...pose, poses: Object.fromEntries([...modePoses].map(([dimension, value]) => [dimension, copyPose(value, dimension)]))};
    };
    function applyPose(pose) {
      if (!finite(pose?.position) || !finite(pose?.target)) throw new TypeError("Non-finite camera restore");
      const control = graph.controls(); control.noRotate = mode !== 3; control.enableRotate = mode === 3; control.enableDamping = false;
      graph.camera().up.set(...axes.map(a => (finite(pose.up) ? pose.up : {x: 0, y: 1, z: 0})[a]));
      if (Number.isFinite(pose.zoom) && pose.zoom > 0) { graph.camera().zoom = pose.zoom; graph.camera().updateProjectionMatrix(); }
      graph.cameraPosition(pose.position, pose.target, 0); control.update();
      if (!finite(point(graph.camera().position)) || !finite(point(control.target))) throw new TypeError("Camera restore failed");
      lastPose = snapshot();
    }
    function fit() {
      if (dead || !source.nodes.length) return false;
      generation++; root.cancelAnimationFrame(pendingFit); pendingFit = 0;
      const pose = snapshot() || {position: {x: 0, y: 0, z: 650}, target: {x: 0, y: 0, z: 0}, up: {x: 0, y: 1, z: 0}};
      try { applyPose(fitCamera(source.nodes.filter(visible), pose, {...size(), fov: graph.camera().fov}, mode)); return true; }
      catch (error) { faults.push(String(error)); throw error; }
    }
    function queueFit() {
      const ticket = ++generation; root.cancelAnimationFrame(pendingFit);
      pendingFit = root.requestAnimationFrame(() => { pendingFit = 0; if (!dead && ticket === generation) fit(); });
    }
    function setFocus(value) {
      if (dead) return false;
      if (value) value = {kind: value.kind || value.type, key: value.key};
      if (value && !byId.has(id(value.kind, value.key))) return false;
      focus = value ? {kind: value.kind, key: value.key} : null;
      graph.nodeVisibility(meshVisible).nodeColor(n => related(n) ? n.color : "#3c4b5e").linkVisibility(solidEdge);
      wireByLink.forEach((line, edge) => { if (!shownEdge(edge)) line.style.display = "none"; });
      return true;
    }
    function setLabels(value) {
      if (dead) return false;
      if (typeof value !== "boolean") throw new TypeError("Label visibility must be boolean");
      showLabels = value; graph.nodeVisibility(meshVisible); return true;
    }
    function setMode(value) {
      if (dead) return false;
      const next = value === 2 || value === "2d" ? 2 : value === 3 || value === "3d" ? 3 : null;
      if (!next) throw new TypeError("Unsupported graph dimensions");
      if (next === mode) return true;
      snapshot(); const restore = modePoses.get(next);
      generation++; root.cancelAnimationFrame(pendingFit); pendingFit = 0; mode = next;
      graph.numDimensions(mode);
      source.nodes.forEach(n => axes.forEach(a => { n[a] = a === "z" && mode === 2 ? 0 : original.get(n.id)[a]; n["f" + a] = n[a]; }));
      graph.graphData(source);
      applyPose(restore || {position: {x: mode === 3 ? 70 : 0, y: mode === 3 ? 70 : 0, z: 650}, target: {x: 0, y: 0, z: 0}, up: {x: 0, y: 1, z: 0}});
      if (!restore) queueFit(); return true;
    }
    function drawLabels() {
      if (dead) return;
      const viewport = size(), camera = graph.camera(); camera.updateMatrixWorld();
      topicMarkers = []; methodMarkers = [];
      const nodeValue = graph.nodeVal(), relativeSize = graph.nodeRelSize();
      const obstacles = source.nodes.filter(visible).map(n => symbolBounds(n, camera, viewport, mode,
        Math.cbrt(typeof nodeValue === "function" ? nodeValue(n) : nodeValue) * relativeSize)).filter(Boolean);
      symbolRects = obstacles;
      markerById.forEach((button, key) => {
        const n = byId.get(key), location = project(point(n, mode), camera, viewport.width, viewport.height);
        const margin = n.kind === "topic" ? 20 : 16;
        const shown = visible(n) && !!location && location.x >= margin && location.x <= viewport.width - margin && location.y >= margin && location.y <= viewport.height - margin;
        const emphasized = related(n) || hover === n.id;
        Object.assign(button.style, {visibility: shown ? "visible" : "hidden", left: `${location?.x || 0}px`, top: `${location?.y || 0}px`,
          opacity: emphasized ? ".95" : ".32", boxShadow: selected(n) || hover === n.id ? `0 0 9px ${n.color}` : "none"});
        button.setAttribute("aria-pressed", String(selected(n)));
        const marker = {id: n.id, x: location?.x ?? null, y: location?.y ?? null, visible: shown};
        if (n.kind === "topic") topicMarkers.push(marker);
        else {
          button.setAttribute("data-node-shape", mode === 3 ? "cube" : "square");
          button.children[0].style.display = mode === 3 ? "block" : "none";
          button.style.height = mode === 3 ? "24px" : "22px";
          button.style.background = mode === 3 ? "transparent" : n.color;
          button.style.border = mode === 3 ? "0" : `1px solid ${n.color}`;
          methodMarkers.push({...marker, shape: mode === 3 ? "cube" : "square"});
        }
      });
      wire.setAttribute("viewBox", `0 0 ${viewport.width} ${viewport.height}`);
      wireByLink.forEach((line, edge) => {
        const a = typeof edge.source === "object" ? edge.source : byId.get(edge.source), b = typeof edge.target === "object" ? edge.target : byId.get(edge.target);
        const start = shownEdge(edge) && project(point(a, mode), camera, viewport.width, viewport.height), end = shownEdge(edge) && project(point(b, mode), camera, viewport.width, viewport.height);
        line.style.display = start && end ? "" : "none";
        if (start && end) { line.setAttribute("x1", start.x); line.setAttribute("y1", start.y); line.setAttribute("x2", end.x); line.setAttribute("y2", end.y); }
      });
      const eligible = new Set(eligibleLabels(source.nodes, source.links, {focus, hover, showLabels}));
      const items = source.nodes.filter(n => visible(n) && eligible.has(n.id)).map(n => {
        const location = project(point(n, mode), camera, viewport.width, viewport.height), button = labelById.get(n.id);
        button.textContent = selected(n) || hover === n.id ? n.title || n.label : n.kind === "paper" ? n.label : n.label.length > 30 ? n.label.slice(0, 29) + "…" : n.label;
        const width = button.offsetWidth || 120, height = button.offsetHeight || 21;
        const radius = obstacles.find(obstacle => obstacle.id === n.id)?.radius || 14;
        return {id: n.id, selected: selected(n), projectable: !!location, priority: selected(n) ? 0 : hover === n.id ? 1 : n.kind === "topic" ? 2 : n.kind === "paper" ? 3 : 4,
          anchor: location && {...location, radius}, box: {x: (location?.x || 0) - width / 2, y: (location?.y || 0) + radius + 7, width, height}};
      });
      labels = resolveLabels(items, viewport.width, viewport.height, obstacles);
      labelById.forEach(button => { button.style.visibility = "hidden"; });
      labels.shown.forEach(item => {
        const button = labelById.get(item.id); button.setAttribute("aria-pressed", String(item.selected));
        Object.assign(button.style, {visibility: "visible", left: `${item.box.x}px`, top: `${item.box.y}px`, textDecoration: item.selected ? "underline" : "none"});
      });
      frame = root.requestAnimationFrame(drawLabels);
    }
    function destroy() {
      if (dead) return;
      lastPose = snapshot(); dead = true; generation++; root.cancelAnimationFrame(frame); root.cancelAnimationFrame(pendingFit);
      observer?.disconnect(); controls.forEach(([element, name, callback]) => element.removeEventListener(name, callback));
      try { if (graph) { graph.pauseAnimation(); graph._destructor(); } }
      finally { shell.remove(); if (mounts.get(host) === api) mounts.delete(host); }
    }
    let observer;
    const api = {setFocus, setLabels, fit, setMode, destroy, snapshot, diagnostics: () => ({mode, destroyed: dead, focus, hover, showLabels, nodes: source.nodes.length, links: source.links.length, focusedRelations: source.links.filter(shownEdge).length,
      papers: source.nodes.filter(n => n.kind === "paper").length, camera: snapshot(), labelsVisible: labels.shown.length, labelsHidden: source.nodes.length - labels.shown.length, labelsOmittedByLod: labels.hidden.length,
      visibleLabelIds: labels.shown.map(item => item.id), eligibleLabelIds: eligibleLabels(source.nodes, source.links, {focus, hover, showLabels}), labelRects: labels.shown.map(item => ({id: item.id, ...item.box})),
      topicMarkers: topicMarkers.map(marker => ({...marker})), methodMarkers: methodMarkers.map(marker => ({...marker})), symbolRects: symbolRects.map(rect => ({...rect})), navigation: graph ? {noRotate: graph.controls().noRotate, enableRotate: graph.controls().enableRotate,
        staticMoving: graph.controls().staticMoving, dynamicDampingFactor: graph.controls().dynamicDampingFactor} : null, faults: [...faults]})};
    try {
      graph = root.ForceGraph3D()(canvas);
      graph.forceEngine("d3").enableNodeDrag(false).showNavInfo(false).backgroundColor("#0e1827")
        .numDimensions(mode).nodeId("id").nodeRelSize(9).nodeVal(n => n.kind === "paper" ? 8 : n.kind === "topic" ? 8 : 2.5)
        .nodeColor(n => n.color).nodeOpacity(.96).nodeLabel(n => { const text = document.createElement("div"); text.textContent = n.title || n.label; return text; })
        .nodeVisibility(meshVisible).linkVisibility(solidEdge)
        .linkColor(edge => lexical(edge) ? "#5b7894" : edge.kind.startsWith("recorded-") ? "#b6a0c9" : edge.kind.includes("method") ? "#8798ab" : (byId.get(edge.target.id || edge.target)?.color || "#779fc5"))
        .linkOpacity(.7).linkWidth(edge => edge.kind === "topic-membership" ? .8 : .45)
        .onNodeClick(select).onNodeHover(n => { if (!dead) { hover = n?.id || null; graph.nodeVisibility(meshVisible); } }).cooldownTicks(0).graphData(source);
      source.links.filter(dashed).forEach(edge => {
        const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
        line.setAttribute("stroke", lexical(edge) ? "#7595b8" : "#a4b4c8");
        line.setAttribute("stroke-width", lexical(edge) ? "1.2" : "1");
        line.setAttribute("stroke-dasharray", lexical(edge) ? "2 5" : "4 4");
        line.setAttribute("opacity", ".64"); line.style.display = "none"; wire.append(line); wireByLink.set(edge, line);
      });
      source.nodes.forEach(n => {
        if (n.kind !== "paper") {
          const marker = document.createElement("button"), kindLabels = n.kind === "topic" ? ["Direction node: ", "方向节点：", "方向節點："] : ["Method node: ", "方法节点：", "方法節點："];
          const prefix = kindLabels[options.language === "zh-Hans" ? 1 : options.language === "zh-Hant" ? 2 : 0];
          marker.type = "button"; marker.className = `atlas-spatial-${n.kind}-marker`; marker.title = n.label;
          marker.setAttribute("aria-label", prefix + n.label); marker.setAttribute("data-node-key", n.id);
          marker.setAttribute("data-node-kind", n.kind);
          Object.assign(marker.style, {position: "absolute", pointerEvents: "auto", width: n.kind === "topic" ? "26px" : "22px", height: n.kind === "topic" ? "26px" : "24px", minWidth: "0", minHeight: "0",
            padding: "0", border: `1px solid ${n.color}`, borderRadius: "1px", background: n.color, cursor: "pointer", visibility: "hidden", transform: `translate(-50%, -50%)${n.kind === "topic" ? " rotate(45deg)" : ""}`});
          if (n.kind === "method") {
            const cube = document.createElementNS("http://www.w3.org/2000/svg", "svg"); cube.setAttribute("viewBox", "0 0 22 24"); cube.setAttribute("aria-hidden", "true");
            Object.assign(cube.style, {width: "100%", height: "100%", pointerEvents: "none"});
            ["11,0 22,6 11,12 0,6", "0,6 11,12 11,24 0,18", "11,12 22,6 22,18 11,24"].forEach((points, i) => {
              const face = document.createElementNS("http://www.w3.org/2000/svg", "polygon"); face.setAttribute("points", points); face.setAttribute("fill", n.color); face.setAttribute("opacity", ["1", ".65", ".85"][i]); cube.append(face);
            }); marker.append(cube);
          }
          bindNode(marker, n); overlay.append(marker); markerById.set(n.id, marker);
        }
        const button = document.createElement("button"); button.type = "button"; button.className = `atlas-spatial-label atlas-spatial-${n.kind}`;
        button.textContent = n.kind === "paper" ? n.label : n.label.length > 30 ? n.label.slice(0, 29) + "…" : n.label;
        button.title = n.title || n.label; button.setAttribute("aria-label", n.title || n.label);
        Object.assign(button.style, {position: "absolute", pointerEvents: "auto", whiteSpace: "nowrap", color: n.color,
          font: `${n.kind === "method" ? 14 : 15}px system-ui`, maxWidth: "240px", overflow: "hidden", textOverflow: "ellipsis", border: "0", background: "transparent", padding: "2px 3px", cursor: "pointer", textShadow: "0 1px 3px #0e1827"});
        bindNode(button, n);
        overlay.append(button); labelById.set(n.id, button);
      });
      const resize = () => { if (!dead) { const {width, height} = size(); graph.width(width).height(height); } };
      observer = new root.ResizeObserver(resize); observer.observe(host); resize(); setFocus(options.focus || null);
      if (mode === 2) source.nodes.forEach(n => { n.z = 0; n.fz = 0; });
      const pose = modePoses.get(mode) || options.pose;
      if (pose && finite(pose.position) && finite(pose.target) && (pose.mode === mode || pose.mode === undefined)) applyPose(pose);
      else { applyPose({position: {x: 70, y: 70, z: 650}, target: {x: 0, y: 0, z: 0}, up: {x: 0, y: 1, z: 0}}); queueFit(); }
      mounts.set(host, api); frame = root.requestAnimationFrame(drawLabels); return api;
    } catch (error) { destroy(); throw error; }
  }
  const api = {buildGraph, mount, fitCamera, resolveLabels, eligibleLabels, symbolBounds, incident};
  if (typeof module !== "undefined" && module.exports) module.exports = api; else root.AtlasSpatial = api;
})(typeof window === "undefined" ? globalThis : window);
