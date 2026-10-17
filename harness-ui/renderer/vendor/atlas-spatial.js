/* V7 A03 local spatial presentation. Derived coordinates/lighting/label LOD only; no evidence or relationship change. */
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
      result.planarX = result.x; result.planarY = result.y;
      nodes.push(result); return result;
    }
    rows.forEach((paper, i) => {
      const position = positions.get(paper.key);
      if (!position) throw new TypeError("Layout lost paper identity");
      const alias = aliases.get(paper.key) ?? `P${String(i + 1).padStart(2, "0")}`;
      if (typeof alias !== "string" || !alias.trim() || alias.length > 32) throw new TypeError("Invalid paper alias");
      const author = String(paper.authors?.[0] || paper.work_id || paper.title).replace(/[-_]/g, " ");
      const n = node("paper", paper.key, `${alias} · ${author.slice(0, 21)}`, position, colors.get(position.primaryGroupKey) || "#aab8c8");
      n.alias = alias; n.primaryGroupKey = position.primaryGroupKey; n.title = paper.title; n.topics = [...(paper.topics || [])]; n.methods = [...(paper.methods || [])];
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
    // Radial branch presentation only. The primary saved membership chooses
    // one display location; other memberships remain intact original links.
    const papers3d = nodes.filter(n => n.kind === "paper"), directions3d = nodes.filter(n => n.kind === "topic"), methods3d = nodes.filter(n => n.kind === "method");
    const groupAnchors = new Map();
    directions3d.forEach((n, i) => {
      const angle = -.35 + i * Math.PI * 2 / Math.max(1, directions3d.length);
      n.x = Math.cos(angle) * 125; n.y = 20 + Math.sin(angle * 1.7) * 25; n.z = Math.sin(angle) * 125;
      groupAnchors.set(n.key, {node:n, angle});
      const members = papers3d.filter(p => p.primaryGroupKey === n.key);
      members.forEach((paper, j) => {
        const spread = Math.min(.97, 3.8 / Math.max(1, directions3d.length));
        const a = angle + ((j + .5) / Math.max(1, members.length) - .5) * spread;
        const radius = 310 + (j % 3) * 45 + ((hash(paper.key) >>> 6) % 19);
        paper.x = Math.cos(a) * radius; paper.z = Math.sin(a) * radius;
        paper.y = 24 + Math.sin(a * 2 + .4) * 48 + (j % 3) * 24;
      });
    });
    papers3d.filter(n => !groupAnchors.has(n.primaryGroupKey)).forEach((n,i) => {
      const a = i * 2.399963 + .8; n.x = Math.cos(a) * 390; n.z = Math.sin(a) * 390; n.y = 55;
    });
    methods3d.forEach((n,i) => {
      const members=n.ids.map(key=>byId.get(id("paper",key))).filter(Boolean);
      if (!members.length) { n.x=0;n.y=0;n.z=0;return; }
      const primary=members.map(p=>p.primaryGroupKey).sort((a,b)=>members.filter(p=>p.primaryGroupKey===b).length-members.filter(p=>p.primaryGroupKey===a).length||compare(a,b))[0];
      const local=members.filter(p=>p.primaryGroupKey===primary), anchor=groupAnchors.get(primary)?.node || {x:0,y:0,z:0};
      const mean=axis=>local.reduce((sum,p)=>sum+p[axis],0)/local.length;
      n.x=anchor.x+(mean("x")-anchor.x)*.56; n.z=anchor.z+(mean("z")-anchor.z)*.56;
      n.y=anchor.y+(mean("y")-anchor.y)*.56 + (i%3-1)*8;
      n.presentationPrimaryTopic=primary;
    });
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
    if (node.kind === "paper" || node.spatialMesh) {
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
      const box = item.pointerBox ? {...item.pointerBox, width: Math.max(item.pointerBox.width, item.box.width), height: Math.max(item.pointerBox.height, item.box.height)} : {...item.box};
      if (item.pointerBox) { box.width = Math.min(box.width, Math.max(1, width - 8)); box.height = Math.min(box.height, Math.max(1, height - 8)); }
      if ((item.selected || item.focused || item.pointerBox) && item.projectable) { box.x = Math.max(4, Math.min(width - box.width - 4, box.x)); box.y = Math.max(4, Math.min(height - box.height - 4, box.y)); }
      const choices = [box];
      if (item.anchor && item.priority <= 3) {
        const {x, y, radius} = item.anchor;
        choices.push({...box, x: x - box.width / 2, y: y - radius - box.height - 7},
          {...box, x: x + radius + 7, y: y - box.height / 2}, {...box, x: x - radius - box.width - 7, y: y - box.height / 2});
      }
      const available = item.projectable && (item.pointerBox ? box : choices.find(candidate => candidate.x >= 0 && candidate.y >= 0 && candidate.x + candidate.width <= width && candidate.y + candidate.height <= height
        && !obstacles.some(obstacle => intersects(candidate, obstacle)) && !shown.some(other => intersects(candidate, other.box))));
      if (available || item.focused && item.projectable) shown.push({...item, box: available || box}); else hidden.push(item.id);
    });
    return {shown, hidden};
  }
  function eligibleLabels(nodes, links, state = {}) {
    const focus = state.focus && id(state.focus.kind || state.focus.type, state.focus.key), active = state.hover || focus;
    if (!active) {
      const topics = nodes.filter(n => n.kind === "topic");
      // Show a small stable set of paper aliases in overview, all identities
      // remain accessible on hover/click and in the linked complete library.
      const overview = state.showLabels === true ? nodes.filter(n => n.kind === "paper").slice(0, 10) : [];
      return [...topics, ...overview].map(n => n.id);
    }
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
    const light = options.theme === "light", background = light ? "#fafbf8" : "#08111e", muted = light ? "#ccd5db" : "#314255";
    if (light) source.nodes.filter(n => n.kind === "method").forEach(n => { n.color = "#71899d"; });
    const original = new Map(source.nodes.map(n => [n.id, point(n)])), byId = new Map(source.nodes.map(n => [n.id, n]));
    const shell = document.createElement("div"), canvas = document.createElement("div"), overlay = document.createElement("div");
    const wire = document.createElementNS("http://www.w3.org/2000/svg", "svg"), wireByLink = new Map();
    shell.className = "atlas-spatial"; canvas.className = "atlas-spatial-canvas"; overlay.className = "atlas-spatial-labels";
    Object.assign(shell.style, {position: "relative", width: "100%", height: "100%", overflow: "hidden", background});
    Object.assign(canvas.style, {position: "absolute", inset: "0"}); Object.assign(overlay.style, {position: "absolute", inset: "0", pointerEvents: "none"});
    Object.assign(wire.style, {position: "absolute", inset: "0", width: "100%", height: "100%", pointerEvents: "none"});
    shell.append(canvas, wire, overlay); host.append(shell);
    let graph, mode = options.mode === 2 || options.mode === "2d" ? 2 : 3, dead = false, focus = null, hover = null, vendorHover = null, domPointerHover = null, domFocusHover = null, pointerInside = true, showLabels = options.showLabels === true, frame = 0, pendingFit = 0, generation = 0, labels = {shown: [], hidden: []}, lastPose = null;
    let navigationMode = mode === 2 ? "pan" : "rotate", panPointer = null, lastPanAt = 0, lastPanDistance = 0, expanded = false, expandedStyle = null, oldBodyOverflow = null;
    let navigationBar = null, navigationStatus = null;
    const faults = [], controls = [], labelById = new Map(), labelSizes = new Map(), markerById = new Map(), paperTouchById = new Map(), modePoses = new Map(), spatialMeshes = new Map();
    const three = options.three; let neighborhoodOnly = false;
    let branchGroup = null, haloTexture = null;
    const presentationBranches = [], halos = [];
    function makeHalo(n, mesh) {
      if (!three) return;
      if (!haloTexture) {
        const image = document.createElement("canvas"); image.width=64;image.height=64;
        const context = image.getContext("2d");
        if (!context) return;
        const gradient=context.createRadialGradient(32,32,1,32,32,31);
        gradient.addColorStop(0,"rgba(255,255,255,.78)");gradient.addColorStop(.18,"rgba(255,255,255,.40)");gradient.addColorStop(.55,"rgba(255,255,255,.09)");gradient.addColorStop(1,"rgba(255,255,255,0)");
        context.fillStyle=gradient;context.fillRect(0,0,64,64);haloTexture=new three.CanvasTexture(image);
      }
      const material=new three.SpriteMaterial({map:haloTexture,color:n.color,transparent:true,opacity:light?.28:.7,depthWrite:false,blending:three.AdditiveBlending});
      const halo=new three.Sprite(material);halo.scale.setScalar(n.kind==="topic"?54:n.kind==="paper"?36:32);mesh.add(halo);halos.push(halo);
    }
    function refreshBranches() {
      if (!three || !graph) return;
      if (!branchGroup) {branchGroup=new three.Group();branchGroup.name="presentation-only-primary-branches";graph.scene().add(branchGroup);}
      presentationBranches.forEach(line=>{line.geometry.dispose();line.material.dispose();branchGroup.remove(line);});presentationBranches.length=0;
      const center = mode===2 ? {x:0,y:0,z:0} : {x:0,y:-15,z:0};
      const line=(a,b,color,main=false,key=null) => {
        const mid=axis=>(a[axis]+b[axis])/2;
        const lift=mode===3?32:0;
        const curve=new three.CubicBezierCurve3(new three.Vector3(a.x,a.y,a.z),new three.Vector3(mid("x")*.60,a.y+lift,mid("z")*.60),new three.Vector3(mid("x")*1.06,b.y+lift,mid("z")*1.06),new three.Vector3(b.x,b.y,b.z));
        const material=new three.LineBasicMaterial({color,transparent:true,opacity:main?(light?.40:.40):(light?.32:.36),depthWrite:false});
        const shape=new three.Line(new three.BufferGeometry().setFromPoints(curve.getPoints(28)),material);
        shape.userData={presentationOnly:true,workKey:key};shape.renderOrder=-1;branchGroup.add(shape);presentationBranches.push(shape);
      };
      source.nodes.filter(n=>n.kind==="topic").forEach(n=>line(center,point(n,mode),light?"#8ca0a9":"#506277",true));
      source.nodes.filter(n=>n.kind==="paper").forEach(n=>{
        const anchor=byId.get(id("topic",n.primaryGroupKey));if(!anchor)return;
        const method=source.nodes.find(m=>m.kind==="method"&&m.presentationPrimaryTopic===n.primaryGroupKey&&m.ids.includes(n.key));
        // The method fork is a layout waypoint, not a new topic→method fact.
        if(method){line(point(anchor,mode),point(method,mode),n.color,false,n.key);line(point(method,mode),point(n,mode),n.color,false,n.key);}
        else line(point(anchor,mode),point(n,mode),n.color,false,n.key);
      });
    }
    let topicMarkers = [], methodMarkers = [], symbolRects = [], observer, intersectionObserver, motionQuery, normalNavigation;
    let viewport = {width: 0, height: 0}, pageVisible = document.visibilityState !== "hidden", intersecting = true;
    let reducedMotion = false, pointerActive = false, dirty = true, renderKey = null, fitTicket = 0, rendererRunning = false;
    let settleRemaining = 0, stableFrames = 0;
    const settleLimit = 24, stableLimit = 2;
    const copyPose = (pose, dimension) => ({position: point(pose.position), target: point(pose.target),
      up: finite(pose.up) ? point(pose.up) : {x: 0, y: 1, z: 0}, mode: dimension, zoom: pose.zoom});
    Object.entries(options.pose?.poses || {}).forEach(([dimension, pose]) => {
      if (["2", "3"].includes(dimension) && finite(pose?.position) && finite(pose?.target)) modePoses.set(Number(dimension), copyPose(pose, Number(dimension)));
    });
    const size = () => ({width: Math.max(1, shell.clientWidth || host.clientWidth || 600), height: Math.max(1, shell.clientHeight || host.clientHeight || 640)});
    const renderable = () => !dead && pageVisible && intersecting;
    function cancelFrames() {
      root.cancelAnimationFrame(frame); frame = 0;
      root.cancelAnimationFrame(pendingFit); pendingFit = 0;
    }
    function resumeRenderer() {
      if (!graph || rendererRunning || !renderable()) return;
      rendererRunning = true;
      try { graph.resumeAnimation(); }
      catch (error) { rendererRunning = false; throw error; }
    }
    function pauseRenderer() {
      if (graph && rendererRunning) { graph.pauseAnimation(); rendererRunning = false; }
    }
    function scheduleFrame() {
      if (renderable() && !frame) frame = root.requestAnimationFrame(drawLabels);
    }
    function scheduleFit() {
      if (!renderable() || !fitTicket || pendingFit) return;
      const ticket = fitTicket;
      pendingFit = root.requestAnimationFrame(() => {
        pendingFit = 0;
        if (!dead && renderable() && ticket === fitTicket && ticket === generation) { fitTicket = 0; fit(); }
      });
    }
    function invalidate(settle = true) {
      if (settle) dirty = true;
      if (!renderable()) return;
      resumeRenderer();
      if (!reducedMotion && !pointerActive && (settle || !settleRemaining)) settleRemaining = settleLimit;
      stableFrames = 0; scheduleFit(); scheduleFrame();
    }
    function lifecycle() {
      if (!renderable()) { pointerActive = false; settleRemaining = 0; cancelFrames(); pauseRenderer(); }
      else invalidate();
    }
    const selected = n => focus?.kind === n.kind && focus.key === n.key;
    const related = n => !focus || selected(n) || source.links.some(e => (e.source.id || e.source) === id(focus.kind, focus.key) && (e.target.id || e.target) === n.id || (e.target.id || e.target) === id(focus.kind, focus.key) && (e.source.id || e.source) === n.id);
    const activePaper = () => focus?.kind === "paper" ? focus.key : byId.get(hover)?.kind === "paper" ? byId.get(hover).key : null;
    const visible = n => (!neighborhoodOnly || !focus || related(n)) && (n.kind !== "method" || n.ids.length > 1 || selected(n) || n.id === hover || n.ids.includes(activePaper()));
    const meshVisible = n => (n.kind === "paper" || !!three) && visible(n);
    function nodeMesh(n) {
      if (!three) return undefined;
      const old = spatialMeshes.get(n.id); old?.geometry.dispose(); old?.material.dispose();
      const radius = n.kind === "paper" ? 6.8 : n.kind === "topic" ? 9.2 : 4.9;
      n.spatialRadius = radius;
      const geometry = n.kind === "paper" ? new three.SphereGeometry(radius, 18, 12)
        : n.kind === "topic" ? new three.OctahedronGeometry(radius) : new three.SphereGeometry(radius, 12, 8);
      const material = new three.MeshPhongMaterial({color: n.color, transparent: true, opacity: .98,
        shininess: 18, specular: "#ffffff", emissive:n.color, emissiveIntensity:light?.12:.62, flatShading: n.kind === "topic"});
      const mesh = new three.Mesh(geometry, material); if (n.kind === "method") mesh.rotation.set(.28, .44, 0);
      makeHalo(n,mesh);n.spatialMesh = true; spatialMeshes.set(n.id, mesh); return mesh;
    }
    const lexical = edge => edge.kind === "content-similarity" || edge.kind.startsWith("lexical-");
    const dashed = edge => edge.kind.includes("method") || lexical(edge);
    const shownEdge = edge => (focus ? incident(edge, focus) : false) && visible(typeof edge.source === "object" ? edge.source : byId.get(edge.source)) && visible(typeof edge.target === "object" ? edge.target : byId.get(edge.target));
    const solidEdge = edge => !dashed(edge) && shownEdge(edge);
    const select = n => { if (!dead && !(lastPanDistance > 4 && Date.now() - lastPanAt < 300)) options.onSelect?.({kind: n.kind, key: n.key}); };
    function resolveHover() {
      if (dead) return;
      hover = domPointerHover?.id || domFocusHover?.id || (pointerInside ? vendorHover : null);
      graph.nodeVisibility(meshVisible); invalidate();
    }
    function bindNode(button, n) {
      const callback = () => select(n); button.addEventListener("click", callback); controls.push([button, "click", callback]);
      const enter = () => {
        const box = labelById.get(n.id) === button && labels.shown.find(item => item.id === n.id)?.box;
        domPointerHover = {button, id: n.id, box: box && {...box}}; resolveHover();
      };
      const leave = () => { if (domPointerHover?.button === button) domPointerHover = null; resolveHover(); };
      const focusNode = () => { domFocusHover = {button, id: n.id}; resolveHover(); };
      const blurNode = () => { if (domFocusHover?.button === button) domFocusHover = null; resolveHover(); };
      [["pointerenter", enter], ["pointerleave", leave], ["focus", focusNode], ["blur", blurNode]].forEach(([name, update]) => {
        button.addEventListener(name, update); controls.push([button, name, update]);
      });
    }
    const snapshot = () => {
      if (dead || !graph) return lastPose;
      const camera = graph.camera(), target = graph.controls().target;
      const pose = {position: point(camera.position), target: point(target), up: point(camera.up), mode, zoom: camera.zoom};
      if (!finite(pose.position) || !finite(pose.target) || !finite(pose.up)) return lastPose;
      modePoses.set(mode, copyPose(pose, mode));
      return {...pose, poses: Object.fromEntries([...modePoses].map(([dimension, value]) => [dimension, copyPose(value, dimension)]))};
    };
    function configureNavigation() {
      if (!graph) return;
      const control = graph.controls(), manualPan = navigationMode === "pan";
      // The bundled runtime defaults to TrackballControls. Explicit pan mode
      // moves the public camera+target pair, including single-finger touch.
      control.enabled = !manualPan;
      control.noRotate = mode !== 3 || manualPan; control.enableRotate = mode === 3 && !manualPan;
      control.noPan = manualPan; control.noZoom = manualPan;
      shell.style.cursor = manualPan ? (panPointer ? "grabbing" : "grab") : "grab";
      navigationBar?.querySelectorAll("[data-spatial-navigation-mode]").forEach(button => {
        const chosen = button.dataset.spatialNavigationMode === navigationMode;
        button.setAttribute("aria-pressed", String(chosen));
        button.disabled = mode === 2 && button.dataset.spatialNavigationMode === "rotate";
      });
      if (navigationStatus) navigationStatus.textContent = navigationMode === "pan" ? navText("拖动画布平移；方向键也可移动", "Drag to pan; arrow keys also move", "拖動畫布平移；方向鍵也可移動") : navText("拖动画布旋转；切换平移可移动边缘节点", "Drag to rotate; choose Pan to reach edge nodes", "拖動畫布旋轉；切換平移可移動邊緣節點");
    }
    function navText(zh,en,tw) { return options.language === "zh-Hans" ? zh : options.language === "zh-Hant" ? tw : en; }
    function setNavigation(value) {
      if (dead || !["rotate", "pan"].includes(value)) return false;
      navigationMode = mode === 2 ? "pan" : value; panPointer = null; configureNavigation(); invalidate(); return true;
    }
    function panByPixels(dx,dy) {
      if (dead || !Number.isFinite(dx) || !Number.isFinite(dy) || !graph) return false;
      const pose = snapshot(), camera = graph.camera(), bounds=size();
      const forward=normalize(subtract(pose.position,pose.target),{x:0,y:0,z:1});
      const right=normalize(cross(pose.up,forward),{x:1,y:0,z:0}), up=normalize(cross(forward,right),{x:0,y:1,z:0});
      const distance=Math.hypot(...axes.map(axis=>pose.position[axis]-pose.target[axis]));
      const units=2*distance*Math.tan((camera.fov||52)*Math.PI/360)/bounds.height/(camera.zoom||1);
      const shift=Object.fromEntries(axes.map(axis=>[axis,(-dx*right[axis]+dy*up[axis])*units]));
      applyPose({...pose,position:Object.fromEntries(axes.map(axis=>[axis,pose.position[axis]+shift[axis]])),target:Object.fromEntries(axes.map(axis=>[axis,pose.target[axis]+shift[axis]]))});
      return true;
    }
    function zoomBy(factor) {
      if(dead || !graph || !Number.isFinite(factor) || factor<=0)return false;
      const pose=snapshot(),offset=subtract(pose.position,pose.target),distance=Math.hypot(offset.x,offset.y,offset.z);
      const next=Math.max(40,Math.min(20000,distance*factor));
      applyPose({...pose,position:Object.fromEntries(axes.map(axis=>[axis,pose.target[axis]+offset[axis]*next/Math.max(distance,1e-9)]))});return true;
    }
    function resetView() {
      if(dead)return false;neighborhoodOnly=false;graph.nodeVisibility(meshVisible);
      applyPose({position:{x:mode===3?90:0,y:mode===3?510:0,z:650},target:{x:0,y:0,z:0},up:{x:0,y:1,z:0}});return fit();
    }
    function fallbackExpand(value) {
      if(value===expanded)return;
      expanded=value;
      if(value){expandedStyle=Object.fromEntries(["position","inset","zIndex","width","height","maxHeight"].map(key=>[key,host.style[key]]));oldBodyOverflow=document.body?.style.overflow;Object.assign(host.style,{position:"fixed",inset:"12px",zIndex:"100000",width:"auto",height:"auto",maxHeight:"none"});host.classList.add("v8-graph-expanded");if(document.body)document.body.style.overflow="hidden";}
      else {if(expandedStyle)Object.assign(host.style,expandedStyle);expandedStyle=null;host.classList.remove("v8-graph-expanded");if(document.body&&oldBodyOverflow!==null)document.body.style.overflow=oldBodyOverflow;oldBodyOverflow=null;}
      if(!dead)invalidate();
    }
    function installNavigation() {
      navigationBar=document.createElement("div");navigationBar.className="atlas-spatial-navigation";navigationBar.setAttribute("role","toolbar");navigationBar.setAttribute("aria-label",navText("图谱导航","Graph navigation","圖譜導覽"));
      const actions=[
        ["rotate",navText("旋转","Rotate","旋轉"),"rotate"],["pan",navText("平移","Pan","平移"),"pan"],
        ["zoom-in","＋",navText("放大图谱","Zoom in","放大圖譜")],["zoom-out","−",navText("缩小图谱","Zoom out","縮小圖譜")],
        ["left","←",navText("向左移动图谱","Move graph left","向左移動圖譜")],["right","→",navText("向右移动图谱","Move graph right","向右移動圖譜")],["up","↑",navText("向上移动图谱","Move graph up","向上移動圖譜")],["down","↓",navText("向下移动图谱","Move graph down","向下移動圖譜")],
        ["reset",navText("复位","Reset","復位"),navText("复位视角与位置","Reset view and position","復位視角與位置")],["expand",navText("展开画布","Expand canvas","展開畫布"),navText("展开或返回画布","Expand or restore canvas","展開或返回畫布")]
      ];
      actions.forEach(([action,label,title])=>{const button=document.createElement("button");button.type="button";button.textContent=label;button.dataset.spatialNavigation=action;button.setAttribute("aria-label",title);button.title=title;if(["rotate","pan"].includes(action)){button.dataset.spatialNavigationMode=action;button.setAttribute("aria-label",navText(action==="pan"?"平移模式":"旋转模式",action==="pan"?"Pan mode":"Rotate mode",action==="pan"?"平移模式":"旋轉模式"));}navigationBar.append(button);});
      navigationStatus=document.createElement("div");navigationStatus.className="atlas-spatial-navigation-status";navigationStatus.setAttribute("role","status");navigationBar.append(navigationStatus);shell.append(navigationBar);
      shell.dataset.navigationTheme=light?"light":"dark";shell.tabIndex=0;shell.setAttribute("aria-label",navText("可旋转、平移和缩放的文献图谱","Literature graph: rotate, pan and zoom","可旋轉、平移和縮放的文獻圖譜"));
      const listen=(element,name,callback)=>{element.addEventListener(name,callback);controls.push([element,name,callback]);};
      listen(navigationBar,"pointerdown",event=>event.stopPropagation());
      listen(navigationBar,"click",async event=>{
        const button=event.target.closest("[data-spatial-navigation]");if(!button)return;event.preventDefault();event.stopPropagation();const action=button.dataset.spatialNavigation;
        if(action==="pan"||action==="rotate")setNavigation(action);
        else if(action==="zoom-in")zoomBy(.8);else if(action==="zoom-out")zoomBy(1.25);
        else if(action==="left")panByPixels(-80,0);else if(action==="right")panByPixels(80,0);else if(action==="up")panByPixels(0,-80);else if(action==="down")panByPixels(0,80);
        else if(action==="reset")resetView();
        else if(action==="expand"){
          if(expanded)fallbackExpand(false);
          else if(document.fullscreenElement===host){await document.exitFullscreen?.();}
          else if(typeof host.requestFullscreen==="function"){try{await host.requestFullscreen();}catch(error){if(!dead)fallbackExpand(true);}}
          else fallbackExpand(true);
          button.textContent=expanded||document.fullscreenElement===host?navText("返回画布","Restore canvas","返回畫布"):navText("展开画布","Expand canvas","展開畫布");invalidate();
        }
      });
      listen(shell,"pointerdown",event=>{
        if(navigationMode!=="pan"||event.target.closest?.("button")||event.button>0)return;
        panPointer={id:event.pointerId,x:event.clientX,y:event.clientY,total:0};lastPanDistance=0;canvas.setPointerCapture?.(event.pointerId);event.preventDefault();configureNavigation();
      });
      listen(document,"pointermove",event=>{if(!panPointer||event.pointerId!==panPointer.id)return;const dx=event.clientX-panPointer.x,dy=event.clientY-panPointer.y;panPointer.x=event.clientX;panPointer.y=event.clientY;panPointer.total+=Math.hypot(dx,dy);panByPixels(dx,dy);event.preventDefault();});
      const end=event=>{if(!panPointer||event.pointerId!==panPointer.id)return;lastPanDistance=panPointer.total;lastPanAt=Date.now();canvas.releasePointerCapture?.(event.pointerId);panPointer=null;configureNavigation();};
      listen(document,"pointerup",end);listen(document,"pointercancel",end);
      listen(shell,"wheel",event=>{if(navigationMode!=="pan"||event.target.closest?.(".atlas-spatial-navigation"))return;event.preventDefault();zoomBy(Math.exp(Math.max(-.5,Math.min(.5,event.deltaY*.001))));});
      listen(shell,"keydown",event=>{if(event.key==="Escape"&&expanded){event.preventDefault();fallbackExpand(false);return;}if(event.target!==shell&&event.target!==canvas&&event.target.tagName!=="CANVAS")return;const steps={ArrowLeft:[-80,0],ArrowRight:[80,0],ArrowUp:[0,-80],ArrowDown:[0,80]};if(steps[event.key]){event.preventDefault();panByPixels(...steps[event.key]);}else if(event.key==="+"||event.key==="="){event.preventDefault();zoomBy(.8);}else if(event.key==="-"){event.preventDefault();zoomBy(1.25);}else if(event.key==="0"){event.preventDefault();resetView();}else if(event.key==="Escape"&&expanded){fallbackExpand(false);}});
      listen(document,"fullscreenchange",()=>{if(!dead){const button=navigationBar.querySelector('[data-spatial-navigation="expand"]');if(button)button.textContent=document.fullscreenElement===host?navText("返回画布","Restore canvas","返回畫布"):navText("展开画布","Expand canvas","展開畫布");invalidate();}});
      configureNavigation();
    }
    function applyPose(pose) {
      if (!finite(pose?.position) || !finite(pose?.target)) throw new TypeError("Non-finite camera restore");
      const control = graph.controls(); configureNavigation();control.enableDamping = false;
      graph.camera().up.set(...axes.map(a => (finite(pose.up) ? pose.up : {x: 0, y: 1, z: 0})[a]));
      if (Number.isFinite(pose.zoom) && pose.zoom > 0) { graph.camera().zoom = pose.zoom; graph.camera().updateProjectionMatrix(); }
      graph.cameraPosition(pose.position, pose.target, 0);
      // The bundled cameraPosition updates target only while controls.enabled.
      // Explicit pan disables native gestures, so synchronize its public target
      // before TrackballControls.update computes the eye vector/look-at pose.
      control.target.set(...axes.map(axis => pose.target[axis]));
      graph.camera().lookAt(control.target);control.update();
      if (!finite(point(graph.camera().position)) || !finite(point(control.target))) throw new TypeError("Camera restore failed");
      lastPose = snapshot(); invalidate();
    }
    function fit() {
      if (dead || !source.nodes.length) return false;
      neighborhoodOnly = false; graph.nodeVisibility(meshVisible);
      if (!renderable()) { fitTicket = ++generation; return true; }
      generation++; fitTicket = 0; root.cancelAnimationFrame(pendingFit); pendingFit = 0;
      const pose = snapshot() || {position: {x: 0, y: 0, z: 650}, target: {x: 0, y: 0, z: 0}, up: {x: 0, y: 1, z: 0}};
      try { applyPose(fitCamera(source.nodes.filter(visible), pose, {...size(), fov: graph.camera().fov}, mode)); return true; }
      catch (error) { faults.push(String(error)); throw error; }
    }
    function queueFit() {
      fitTicket = ++generation; root.cancelAnimationFrame(pendingFit); pendingFit = 0; scheduleFit();
    }
    // V7 local extension: frame the selected one-hop neighborhood, without
    // adding relationships or moving nodes. Keep manual orbit orientation.
    function fitFocus() {
      if (dead || !focus || !renderable()) return false;
      neighborhoodOnly = true; graph.nodeVisibility(meshVisible);
      const neighborhood = source.nodes.filter(n => visible(n) && related(n));
      if (!neighborhood.length) return false;
      generation++; fitTicket = 0; root.cancelAnimationFrame(pendingFit); pendingFit = 0;
      try { applyPose(fitCamera(neighborhood, snapshot(), {...size(), fov: graph.camera().fov}, mode)); return true; }
      catch (error) { faults.push(String(error)); throw error; }
    }
    function setFocus(value) {
      if (dead) return false;
      if (value) value = {kind: value.kind || value.type, key: value.key};
      if (value && !byId.has(id(value.kind, value.key))) return false;
      focus = value ? {kind: value.kind, key: value.key} : null; if (!focus) neighborhoodOnly = false;
      spatialMeshes.forEach((mesh, key) => { const n = byId.get(key); mesh.material.color.set(related(n) ? n.color : muted); mesh.material.opacity = related(n) ? .96 : .32; });
      graph.nodeVisibility(meshVisible).nodeColor(n => related(n) ? n.color : muted).linkVisibility(solidEdge);
      wireByLink.forEach((line, edge) => { if (!shownEdge(edge)) line.style.display = "none"; });
      presentationBranches.forEach(line=>{line.material.opacity=focus ? (line.userData.workKey===activePaper() || focus.kind==="topic" && source.nodes.find(n=>n.kind==="paper"&&n.key===line.userData.workKey)?.topics.includes(focus.key) ? .65 : .08) : (light?.32:.36);});
      invalidate();
      return true;
    }
    function setLabels(value) {
      if (dead) return false;
      if (typeof value !== "boolean") throw new TypeError("Label visibility must be boolean");
      showLabels = value; graph.nodeVisibility(meshVisible); invalidate(); return true;
    }
    function setMode(value) {
      if (dead) return false;
      const next = value === 2 || value === "2d" ? 2 : value === 3 || value === "3d" ? 3 : null;
      if (!next) throw new TypeError("Unsupported graph dimensions");
      if (next === mode) return true;
      snapshot(); const restore = modePoses.get(next);
      generation++; fitTicket = 0; root.cancelAnimationFrame(pendingFit); pendingFit = 0; mode = next;
      navigationMode=mode===2?"pan":"rotate";configureNavigation();graph.numDimensions(mode);
      source.nodes.forEach(n => axes.forEach(a => { n[a] = mode === 2 ? (a === "z" ? 0 : n["planar" + a.toUpperCase()]) : original.get(n.id)[a]; n["f" + a] = n[a]; }));
      graph.graphData(source);refreshBranches();
      applyPose(restore || {position: {x: mode === 3 ? 90 : 0, y: mode === 3 ? 510 : 0, z: 650}, target: {x: 0, y: 0, z: 0}, up: {x: 0, y: 1, z: 0}});
      invalidate(); if (!restore) queueFit(); return true;
    }
    function drawLabels() {
      frame = 0;
      if (!renderable()) return;
      const camera = graph.camera(), target = graph.controls().target; camera.updateMatrixWorld();
      const nextKey = JSON.stringify([mode, focus, hover, showLabels, viewport,
        ...axes.map(axis => camera.position[axis]), ...axes.map(axis => target[axis]), camera.zoom,
        ...camera.matrixWorldInverse.elements, ...camera.projectionMatrix.elements]);
      if (!dirty && nextKey === renderKey) {
        stableFrames++;
        if (!reducedMotion && (pointerActive || settleRemaining > 0 && stableFrames < stableLimit)) scheduleFrame();
        else { settleRemaining = 0; pauseRenderer(); }
        return;
      }
      const moved = nextKey !== renderKey;
      dirty = false; renderKey = nextKey; stableFrames = moved ? 0 : stableFrames + 1;
      if (!pointerActive && settleRemaining > 0) settleRemaining--;
      topicMarkers = []; methodMarkers = [];
      const nodeValue = graph.nodeVal(), relativeSize = graph.nodeRelSize();
      const obstacles = source.nodes.filter(visible).map(n => symbolBounds(n, camera, viewport, mode,
        n.spatialMesh ? n.spatialRadius : Math.cbrt(typeof nodeValue === "function" ? nodeValue(n) : nodeValue) * relativeSize)).filter(Boolean);
      symbolRects = obstacles;
      paperTouchById.forEach((button, key) => {
        const box = obstacles.find(item => item.id === key), diameter = Math.max(48, box?.width || 48);
        Object.assign(button.style, {visibility: box ? "visible" : "hidden", width: `${diameter}px`, height: `${diameter}px`,
          left: `${box ? box.x + box.width / 2 : 0}px`, top: `${box ? box.y + box.height / 2 : 0}px`});
        button.setAttribute("aria-pressed", String(selected(byId.get(key))));
      });
      markerById.forEach((button, key) => {
        const n = byId.get(key), location = project(point(n, mode), camera, viewport.width, viewport.height);
        const margin = 22;
        const shown = visible(n) && !!location && location.x >= margin && location.x <= viewport.width - margin && location.y >= margin && location.y <= viewport.height - margin;
        const emphasized = related(n) || hover === n.id;
        Object.assign(button.style, {visibility: shown ? "visible" : "hidden", left: `${location?.x || 0}px`, top: `${location?.y || 0}px`,
          opacity: emphasized ? ".95" : ".32", boxShadow: selected(n) || hover === n.id ? `0 0 9px ${n.color}` : "none"});
        button.setAttribute("aria-pressed", String(selected(n)));
        const marker = {id: n.id, x: location?.x ?? null, y: location?.y ?? null, visible: shown};
        if (n.spatialMesh) button.children[0].style.visibility = "hidden";
        if (n.kind === "topic") topicMarkers.push(marker);
        else {
          const shape = button.children[0], cube = shape.children[0];
          button.setAttribute("data-node-shape", mode === 3 ? "cube" : "square");
          cube.style.display = mode === 3 ? "block" : "none";
          Object.assign(shape.style, {height: mode === 3 ? "24px" : "22px", background: mode === 3 ? "transparent" : n.color,
            border: mode === 3 ? "0" : `1px solid ${n.color}`});
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
      if (domFocusHover) eligible.add(domFocusHover.id);
      const items = source.nodes.filter(n => visible(n) && eligible.has(n.id)).map(n => {
        const location = project(point(n, mode), camera, viewport.width, viewport.height), button = labelById.get(n.id);
        const text = selected(n) || hover === n.id ? n.title || n.label : n.kind === "paper" ? n.alias : n.label.length > 30 ? n.label.slice(0, 29) + "…" : n.label;
        if (button.textContent !== text) { button.textContent = text; labelSizes.delete(n.id); }
        const pointerBox = domPointerHover?.button === button ? domPointerHover.box : null;
        const maxWidth = Math.min(240, Math.max(1, viewport.width - 8)), maxHeight = Math.max(1, viewport.height - 8);
        const sizing = {minWidth: `${Math.min(maxWidth, Math.max(44, pointerBox?.width || 44))}px`, maxWidth: `${maxWidth}px`,
          minHeight: `${Math.min(maxHeight, Math.max(44, pointerBox?.height || 44))}px`, maxHeight: `${maxHeight}px`};
        Object.entries(sizing).forEach(([key, value]) => { if (button.style[key] !== value) { button.style[key] = value; labelSizes.delete(n.id); } });
        if (!labelSizes.has(n.id)) labelSizes.set(n.id, {width: button.offsetWidth || 120, height: button.offsetHeight || 44});
        const {width, height} = labelSizes.get(n.id);
        const radius = obstacles.find(obstacle => obstacle.id === n.id)?.radius || 14;
        return {id: n.id, selected: selected(n), focused: domFocusHover?.id === n.id, pointerBox, projectable: !!location, priority: selected(n) ? 0 : hover === n.id ? 1 : n.kind === "topic" ? 2 : n.kind === "paper" ? 3 : 4,
          anchor: location && {...location, radius}, box: {x: (location?.x || 0) - width / 2, y: (location?.y || 0) + radius + 7, width, height}};
      });
      labels = resolveLabels(items, viewport.width, viewport.height, obstacles);
      const shownLabelIds = new Set(labels.shown.map(item => item.id));
      labelById.forEach((button, id) => { if (!shownLabelIds.has(id)) button.style.visibility = "hidden"; });
      labels.shown.forEach(item => {
        const button = labelById.get(item.id); button.setAttribute("aria-pressed", String(item.selected));
        Object.assign(button.style, {visibility: "visible", left: `${item.box.x}px`, top: `${item.box.y}px`, textDecoration: item.selected ? "underline" : "none"});
      });
      if (reducedMotion) { settleRemaining = 0; pauseRenderer(); }
      else if (pointerActive || settleRemaining > 0) scheduleFrame();
      else { settleRemaining = 0; pauseRenderer(); }
    }
    function destroy() {
      if (dead) return;
      lastPose = snapshot(); dead = true; panPointer=null;fallbackExpand(false);generation++; fitTicket = 0; cancelFrames(); pauseRenderer();
      observer?.disconnect(); intersectionObserver?.disconnect(); controls.forEach(([element, name, callback]) => element.removeEventListener(name, callback));
      try { if (graph) { graph.pauseAnimation(); graph._destructor(); } }
      finally { presentationBranches.forEach(line=>{line.geometry.dispose();line.material.dispose();});presentationBranches.length=0;branchGroup?.removeFromParent();halos.forEach(halo=>halo.material.dispose());halos.length=0;haloTexture?.dispose();spatialMeshes.forEach(mesh => { mesh.geometry.dispose(); mesh.material.dispose(); }); spatialMeshes.clear(); shell.remove(); if (mounts.get(host) === api) mounts.delete(host); }
    }
    const api = {setFocus, setLabels, fit, fitFocus, setMode, setNavigation, panByPixels, zoomBy, resetView, destroy, snapshot, diagnostics: () => ({presentation: "a03-mindwalk-inspired-branches-v2", visualBranchCount:presentationBranches.length, visualBranchMeaning:"presentation-only-not-new-research-edges", coordinateMeaning: "presentation-only-not-an-embedding", depthRange: source.nodes.length ? Math.max(...source.nodes.map(n => n.z)) - Math.min(...source.nodes.map(n => n.z)) : 0, mode, theme: light ? "light" : "dark", background, destroyed: dead, focus, hover, showLabels, neighborhoodOnly, nodes: source.nodes.length, links: source.links.length, focusedRelations: source.links.filter(shownEdge).length,
      focusNodes: focus ? source.nodes.filter(n => visible(n) && related(n)).map(n => ({id: n.id, ...point(n)})) : [],
      spatialMeshShapes: [...spatialMeshes].map(([id, mesh]) => ({id, geometry: mesh.geometry.type, opacity: mesh.material.opacity})),
      papers: source.nodes.filter(n => n.kind === "paper").length, camera: snapshot(), labelsVisible: labels.shown.length, labelsHidden: source.nodes.length - labels.shown.length, labelsOmittedByLod: labels.hidden.length,
      visibleLabelIds: labels.shown.map(item => item.id), eligibleLabelIds: eligibleLabels(source.nodes, source.links, {focus, hover, showLabels}), labelRects: labels.shown.map(item => ({id: item.id, ...item.box})),
      topicMarkers: topicMarkers.map(marker => ({...marker})), methodMarkers: methodMarkers.map(marker => ({...marker})), symbolRects: symbolRects.map(rect => ({...rect})), lifecycle: {pageVisible, intersecting, reducedMotion, pointerActive, dirty, scheduled: !!frame, rendererRunning}, navigation: graph ? {mode:navigationMode,expanded:expanded||document.fullscreenElement===host,publicCameraPan:true,noRotate: graph.controls().noRotate, enableRotate: graph.controls().enableRotate,
        staticMoving: graph.controls().staticMoving, dynamicDampingFactor: graph.controls().dynamicDampingFactor} : null, faults: [...faults]})};
    try {
      graph = root.ForceGraph3D()(canvas); rendererRunning = true;
      graph.forceEngine("d3").enableNodeDrag(false).showNavInfo(false).backgroundColor(background)
        .nodeThreeObject(nodeMesh).nodeThreeObjectExtend(false)
        .numDimensions(mode).nodeId("id").nodeRelSize(12).nodeVal(n => n.kind === "paper" ? 8 : n.kind === "topic" ? 8 : 2.5)
        .nodeColor(n => n.color).nodeOpacity(.96).nodeResolution(20).nodeLabel(n => { const text = document.createElement("div"); text.textContent = n.title || n.label; return text; })
        .nodeVisibility(meshVisible).linkVisibility(solidEdge)
        .linkColor(edge => lexical(edge) ? (light ? "#bc6e2a" : "#f1b46d") : edge.kind.startsWith("recorded-") ? (light ? "#80698f" : "#b6a0c9") : edge.kind.includes("method") ? "#79a9cb" : (byId.get(edge.target.id || edge.target)?.color || "#779fc5"))
        .linkOpacity(.65).linkWidth(edge => edge.kind === "topic-membership" ? .5 : .35).linkCurvature(.12)
        .onNodeClick(select).onNodeHover(n => { if (!dead) { vendorHover = n?.id || null; resolveHover(); } }).cooldownTicks(0).graphData(source);
      // An oblique view and key/fill lighting make the existing 3D volumes readable.
      graph.camera().fov = 52; graph.camera().updateProjectionMatrix();
      if (three && typeof graph.lights === "function") {
        const keyLight = new three.DirectionalLight("#ffffff", 2.15); keyLight.position.set(-180, 320, 520);
        const fillLight = new three.DirectionalLight("#d9e7ff", .7); fillLight.position.set(360, -120, -240);
        graph.lights([new three.AmbientLight("#ffffff", .85), keyLight, fillLight]);
      }
      refreshBranches();
      source.links.filter(dashed).forEach(edge => {
        const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
        line.setAttribute("stroke", lexical(edge) ? (light ? "#bc6e2a" : "#f1b46d") : light ? "#507d9c" : "#8ec0e4");
        line.setAttribute("stroke-width", lexical(edge) ? "1.6" : "1.2");
        line.setAttribute("stroke-dasharray", lexical(edge) ? "2 5" : "4 4");
        line.setAttribute("opacity", ".64"); line.style.display = "none"; wire.append(line); wireByLink.set(edge, line);
      });
      source.nodes.forEach(n => {
        if (n.kind === "paper") {
          const touch = document.createElement("button"); touch.type = "button"; touch.className = "atlas-spatial-paper-touch";
          touch.setAttribute("aria-label", n.title || n.label); touch.setAttribute("data-node-key", n.id); touch.setAttribute("data-node-kind", "paper");
          Object.assign(touch.style, {position: "absolute", pointerEvents: "auto", minWidth: "48px", minHeight: "48px", padding: "0", border: "0",
            background: "transparent", visibility: "hidden", transform: "translate(-50%, -50%)"});
          bindNode(touch, n); overlay.append(touch); paperTouchById.set(n.id, touch);
        }
        if (n.kind !== "paper") {
          const marker = document.createElement("button"), kindLabels = n.kind === "topic" ? ["Direction node: ", "方向节点：", "方向節點："] : ["Method node: ", "方法节点：", "方法節點："];
          const prefix = kindLabels[options.language === "zh-Hans" ? 1 : options.language === "zh-Hant" ? 2 : 0];
          marker.type = "button"; marker.className = `atlas-spatial-${n.kind}-marker`; marker.title = n.label;
          marker.setAttribute("aria-label", prefix + n.label); marker.setAttribute("data-node-key", n.id);
          marker.setAttribute("data-node-kind", n.kind);
          Object.assign(marker.style, {position: "absolute", pointerEvents: "auto", width: "44px", height: "44px", minWidth: "44px", minHeight: "44px",
            padding: "0", border: "0", background: "transparent", cursor: "pointer", visibility: "hidden", transform: "translate(-50%, -50%)"});
          const shape = document.createElement("span");
          Object.assign(shape.style, {display: "block", position: "absolute", left: n.kind === "topic" ? "9px" : "11px", top: n.kind === "topic" ? "9px" : "10px",
            width: n.kind === "topic" ? "26px" : "22px", height: n.kind === "topic" ? "26px" : "24px", boxSizing: "border-box",
            border: `1px solid ${n.color}`, borderRadius: "1px", background: n.kind === "topic" ? n.color : "transparent", transform: n.kind === "topic" ? "rotate(45deg)" : "none", pointerEvents: "none"});
          if (n.kind === "method") {
            const cube = document.createElementNS("http://www.w3.org/2000/svg", "svg"); cube.setAttribute("viewBox", "0 0 22 24"); cube.setAttribute("aria-hidden", "true");
            Object.assign(cube.style, {width: "100%", height: "100%", pointerEvents: "none"});
            ["11,0 22,6 11,12 0,6", "0,6 11,12 11,24 0,18", "11,12 22,6 22,18 11,24"].forEach((points, i) => {
              const face = document.createElementNS("http://www.w3.org/2000/svg", "polygon"); face.setAttribute("points", points); face.setAttribute("fill", n.color); face.setAttribute("opacity", ["1", ".65", ".85"][i]); cube.append(face);
            }); shape.append(cube);
          }
          marker.append(shape);
          bindNode(marker, n); overlay.append(marker); markerById.set(n.id, marker);
        }
        const button = document.createElement("button"); button.type = "button"; button.className = `atlas-spatial-label atlas-spatial-${n.kind}`;
        button.textContent = n.kind === "paper" ? n.alias : n.label.length > 30 ? n.label.slice(0, 29) + "…" : n.label;
        button.title = n.title || n.label; button.setAttribute("aria-label", n.title || n.label);
        button.setAttribute("data-node-key", n.id); button.setAttribute("data-node-kind", n.kind);
        Object.assign(button.style, {position: "absolute", pointerEvents: "auto", whiteSpace: "nowrap", color: light && n.kind === "method" ? "#4e6579" : n.color,
          font: `${n.kind === "method" ? 14 : 15}px system-ui`, lineHeight: "19px", minWidth: "44px", minHeight: "44px", boxSizing: "border-box", maxWidth: "240px", overflow: "hidden", textOverflow: "ellipsis", border: "0", background: "transparent", padding: "12px 3px 13px", cursor: "pointer", textShadow: light ? "0 1px 2px #ffffffcc" : "0 1px 3px #0e1827"});
        bindNode(button, n);
        overlay.append(button); labelById.set(n.id, button);
      });
      const listen = (element, name, callback) => { element.addEventListener(name, callback); controls.push([element, name, callback]); };
      const beginPointer = () => { if (!dead) { pointerActive = !reducedMotion; settleRemaining = 0; resumeRenderer(); scheduleFrame(); } };
      const endPointer = () => { if (!dead && pointerActive) { pointerActive = false; invalidate(); } };
      const leavePointer = () => {
        if (!dead) { pointerInside = false; domPointerHover = null; resolveHover(); }
      };
      const movePointer = () => {
        if (!dead) {
          if (!pointerInside) { pointerInside = true; resolveHover(); }
          else invalidate();
        }
      };
      listen(shell, "pointerdown", beginPointer); listen(document, "pointerup", endPointer); listen(document, "pointercancel", endPointer);
      listen(shell, "pointermove", movePointer); listen(shell, "pointerleave", leavePointer); listen(shell, "wheel", invalidate); listen(shell, "keydown", invalidate);
      const graphControls = graph.controls();
      normalNavigation = {staticMoving: graphControls.staticMoving, dynamicDampingFactor: graphControls.dynamicDampingFactor};
      if (typeof graphControls.addEventListener === "function") listen(graphControls, "change", () => invalidate(false));
      if (typeof document.addEventListener === "function") listen(document, "visibilitychange", () => {
        pageVisible = document.visibilityState !== "hidden"; lifecycle();
      });
      if (typeof root.IntersectionObserver === "function") {
        intersectionObserver = new root.IntersectionObserver(entries => {
          const entry = entries[entries.length - 1];
          if (entry) { intersecting = entry.isIntersecting !== false; lifecycle(); }
        });
        intersectionObserver.observe(host);
      }
      if (typeof root.matchMedia === "function") {
        const applyMotion = value => {
          reducedMotion = value; pointerActive = false; settleRemaining = 0;
          graphControls.staticMoving = value ? true : normalNavigation.staticMoving;
          graphControls.dynamicDampingFactor = value ? 0 : normalNavigation.dynamicDampingFactor;
          graphControls.update(); invalidate();
        };
        motionQuery = root.matchMedia("(prefers-reduced-motion: reduce)"); applyMotion(motionQuery.matches === true);
        if (typeof motionQuery.addEventListener === "function") listen(motionQuery, "change", event => {
          applyMotion(event.matches === true);
        });
      }
      const resize = () => {
        if (dead) return;
        const next = size();
        if (next.width === viewport.width && next.height === viewport.height) return;
        viewport = next; labelSizes.clear(); graph.width(viewport.width).height(viewport.height); invalidate();
      };
      observer = new root.ResizeObserver(resize); observer.observe(host); resize(); setFocus(options.focus || null);
      if (mode === 2) {source.nodes.forEach(n => axes.forEach(a => { n[a] = a === "z" ? 0 : n["planar" + a.toUpperCase()]; n["f" + a] = n[a]; }));refreshBranches();}
      const pose = modePoses.get(mode) || options.pose;
      if (pose && finite(pose.position) && finite(pose.target) && (pose.mode === mode || pose.mode === undefined)) applyPose(pose);
      else { applyPose({position: {x: mode === 3 ? 90 : 0, y: mode === 3 ? 510 : 0, z: 650}, target: {x: 0, y: 0, z: 0}, up: {x: 0, y: 1, z: 0}}); queueFit(); }
      installNavigation();mounts.set(host, api); invalidate(); return api;
    } catch (error) { destroy(); throw error; }
  }
  const api = {buildGraph, mount, fitCamera, resolveLabels, eligibleLabels, symbolBounds, incident};
  if (typeof module !== "undefined" && module.exports) module.exports = api; else root.AtlasSpatial = api;
})(typeof window === "undefined" ? globalThis : window);
