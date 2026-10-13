"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");
const plugin = path.resolve(__dirname, ".."), atlas = path.join(plugin, "references/research-workspace/atlas");
const ui = fs.readFileSync(process.argv[2] || path.join(atlas, "atlas-ui.js"), "utf8");
const host = fs.readFileSync(path.join(plugin, "cli/research_workspace_native/web/atlas-host.js"), "utf8");
const model = require(path.join(atlas, "atlas-model.js"));
const associations = require(path.join(atlas, "atlas-associations.js"));
assert.doesNotMatch(ui, /threshold:\s*\.09/, "UI graph and related cards inherit the shared association default");
const flatten = node => node.children.flatMap(child => [child, ...flatten(child)]);
class Element {
  constructor(tag) {
    this.tagName = tag; this.children = []; this.dataset = {}; this.attributes = {}; this.listeners = {};
    this.style = {setProperty() {}}; this.className = ""; this._text = "";
    this.classList = {add: name => { this.className += " " + name; }};
  }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(node => node.textContent).join(" "); }
  append(...nodes) { nodes.forEach(node => { if (node.parent) { const old = node.parent.children.indexOf(node); if (old >= 0) node.parent.children.splice(old, 1); } node.parent = this; node.ownerDocument ||= this.ownerDocument; this.children.push(node); }); }
  insertBefore(node, anchor) {
    const active = this.ownerDocument?.activeElement;
    if (active && (active === node || flatten(node).includes(active))) this.ownerDocument.activeElement = this.ownerDocument.body;
    if (node.parent) { const old = node.parent.children.indexOf(node); if (old >= 0) node.parent.children.splice(old, 1); }
    node.parent = this; node.ownerDocument ||= this.ownerDocument;
    const index = anchor ? this.children.indexOf(anchor) : -1;
    if (index < 0) this.children.push(node); else this.children.splice(index, 0, node);
  }
  replaceChildren(...nodes) {
    const active = this.ownerDocument?.activeElement;
    if (active && (active === this || flatten(this).includes(active))) this.ownerDocument.activeElement = this.ownerDocument.body;
    this._text = ""; this.children = []; this.append(...nodes);
  }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  addEventListener(name, handler) { (this.listeners[name] ||= []).push(handler); }
  set onchange(handler) {
    this._onchange = handler;
    if (!this._changeEntry) { this._changeEntry = {property: true}; (this.listeners.change ||= []).push(this._changeEntry); }
  }
  get onchange() { return this._onchange; }
  change(value) {
    this.value = value;
    for (const handler of this.listeners.change || []) (handler.property ? this._onchange : handler)({target: this});
  }
  querySelector(selector) {
    return flatten(this).find(node => selector === "span" ? node.tagName === "span" : selector === "details" ? node.tagName === "details" : selector === 'option[value="relevance"]' ? node.tagName === "option" && node.value === "relevance" : false);
  }
  scrollIntoView(options) { this.lastScrollIntoView = options; }
  getClientRects() { return this.style.visibility === "hidden" ? [] : [{}]; }
  focus() { if (this.ownerDocument && this.style.visibility !== "hidden") this.ownerDocument.activeElement = this; }
}
let checks = 0;
const equal = (actual, expected, note) => { checks++; assert.equal(actual, expected, note); };
const contains = (actual, expected, note) => { checks++; assert(actual.includes(expected), note); };
const labels = {
  en: ["Literature knowledge network", "Compare evidence, explore directions", "Design & feasibility", "Experiment execution", "Analysis & figures", "Writing & submission", "Project files", "Codex & feedback"],
  "zh-Hans": ["文献知识网络", "比较文献，探索研究方向", "设计与可行性", "实验执行", "分析与图表", "写作与投稿", "项目文件", "Codex 与反馈"],
  "zh-Hant": ["文獻知識網絡", "比較文獻，探索研究方向", "設計與可行性", "實驗執行", "分析與圖表", "寫作與投稿", "專案檔案", "Codex 與回饋"]
};
function runCase(initial, hostFirst, dense = false, boundaries = false, options = {}) {
  const body = new Element("body"), ids = {};
  for (const id of ["atlas-content", "atlas-stages", "atlas-language-label", "atlas-language", "atlas-original", "atlas-project", "atlas-status", "atlas-footer", "atlas-view-files"]) {
    const node = new Element(id === "atlas-language" ? "select" : "div"); node.id = id; ids[id] = node; body.append(node);
  }
  ids["atlas-view-files"].append(new Element("span")); ids["atlas-language"].value = initial;
  const document = {
    body, documentElement: {lang: "en", dataset: {}},
    getElementById: id => ids[id] || flatten(body).find(node => node.id === id),
    createElement: tag => { const node = new Element(tag); node.ownerDocument = document; return node; },
    createElementNS: (namespace, tag) => { const node = new Element(tag); node.ownerDocument = document; node.namespaceURI = namespace; return node; },
    querySelectorAll: () => flatten(body).filter(node => node.dataset.atlasLabel)
  };
  body.ownerDocument = document; flatten(body).forEach(node => { node.ownerDocument = document; }); document.activeElement = body;
  const payload = {index: {topic: "Original English topic", papers: [
    {work_id: "fixture", version_id: "v1", title: "Original English title", source_ids: [], classification: {topic_cluster: "Direction A", method: "Shared original method"}},
    {work_id: "second", version_id: "v1", title: "Second original title", source_ids: [], classification: {topic_cluster: "Direction B", method: "Shared original method"}},
  ], stages: [], screening: [], sources: [], claims: []}, index_sha256: "1".repeat(64)};
  if (dense) for (let i = 0; i < 28; i++) payload.index.papers.push({work_id: `extra-${i}`, version_id: "v1", title: `Retained paper ${i}`, source_ids: [], classification: {topic_cluster: "Direction A", method: "Shared original method"}});
  if (options.library) for (let i = 28; i < 58; i++) payload.index.papers.push({work_id: `extra-${i}`, version_id: "v1", title: `Retained paper ${i}`, source_ids: [], classification: {topic_cluster: "Direction A", method: "Shared original method"}});
  if (boundaries) {
    payload.index.papers[0].classification.method = ["Shared original method", "Unique recorded method"];
    payload.index.papers.push({work_id: "unclassified", version_id: "v2", title: "Unclassified retained title", source_ids: [], classification: {topic_cluster: "Unknown", method: "Unknown"}});
  }
  if (Object.hasOwn(options, "fixture")) {
    payload.fixture = options.fixture; payload.fixture_notice = "Synthetic routes and judgments; retained paper identities only.";
    payload.stage2 = {evaluation: {evaluation_status: "audit-required", dimensions: {P4: {score: 83.33333333333333, sum: 5, max: 6, assessed: 3, required: 3}}, rows: []}};
  }
  if (options.later) payload.index.stages = [3, 4, 5, 6].map(stage => ({stage, purpose: `Recorded workflow ${stage}`,
    required_inputs: [`input-${stage}`], expected_deliverables: [`output-${stage}`], support_status: null,
    execution_enabled: null, node_flow: ["plan", "execute"]}));
  const before = JSON.stringify(payload);
  const scrollCalls = [];
  const microtasks = [], frames = new Map(); let frameId = 0;
  const mediaListeners = new Set(), resizeListeners = new Set(), mediaQuery = {matches: Boolean(options.mobile),
    addEventListener: (name, listener) => { if (name === "change") mediaListeners.add(listener); },
    removeEventListener: (name, listener) => { if (name === "change") mediaListeners.delete(listener); }};
  const window = {WORKSPACE_VIEW: payload, AtlasModel: model, AtlasAssociations: associations, innerWidth: options.mobile ? 390 : 1200, scrollY: 0,
    queueMicrotask: callback => microtasks.push(callback), requestAnimationFrame: callback => { const id = ++frameId; frames.set(id, callback); return id; },
    cancelAnimationFrame: id => frames.delete(id), getComputedStyle: node => node.style, matchMedia: () => mediaQuery,
    addEventListener: (name, listener) => { if (name === "resize") resizeListeners.add(listener); },
    removeEventListener: (name, listener) => { if (name === "resize") resizeListeners.delete(listener); },
    setPhone: matches => { mediaQuery.matches = matches; mediaListeners.forEach(listener => listener({matches})); },
    resizeToPhone: matches => { mediaQuery.matches = matches; resizeListeners.forEach(listener => listener()); },
    scrollTo(value) { this.scrollY = value.top; scrollCalls.push({...value}); },
    WORKSPACE_HOST: {cases: [], current_case: "fixture", maintenance_enabled: false, connection: {status: "not-checked"}}};
  if (options.focus) window.AtlasNetwork = {mount(parent, mountOptions) {
    let dead = false;
    const controls = document.createElement("div"), host = document.createElement("div"), mode = document.createElement("button");
    controls.className = "atlas-actions atlas-spatial-controls"; host.className = "atlas-spatial-host";
    mode.textContent = "3D"; mode.dataset.fakeControl = "mode"; mode.onclick = () => mountOptions.onSettings();
    controls.append(mode); parent.append(controls, host);
    window.queueMicrotask(() => {
      if (dead) return;
      const paper = mountOptions.papers[0], topic = document.createElement("button"), label = document.createElement("button");
      topic.className = "atlas-spatial-topic-marker"; topic.dataset.nodeKind = "topic";
      topic.dataset.nodeKey = JSON.stringify(["topic", paper.topics[0]]); topic.style.visibility = "hidden";
      topic.onclick = () => mountOptions.onSelect({kind: "topic", key: paper.topics[0]});
      label.className = "atlas-spatial-label atlas-spatial-paper"; label.title = paper.title; label.textContent = "P01"; label.style.visibility = "hidden";
      if (options.stableLabelIdentity) {
        label.dataset.nodeKey = JSON.stringify(["paper", paper.key]); label.dataset.nodeKind = "paper";
        label.textContent = mountOptions.focus?.kind === "paper" ? paper.title : "P01";
      }
      label.onclick = () => mountOptions.onSelect({kind: "paper", key: paper.key}); host.append(topic, label);
      window.requestAnimationFrame(() => { if (!dead) { topic.style.visibility = "visible"; label.style.visibility = "visible"; } });
    });
    return {snapshot: () => null, destroy: () => { dead = true; }};
  }};
  const context = vm.createContext({window, document, location: {origin: "http://127.0.0.1", href: "http://127.0.0.1/atlas.html"}, URL, sessionStorage: {getItem: () => null}});
  if (hostFirst) vm.runInContext(host, context);
  vm.runInContext(ui, context);
  if (!hostFirst) vm.runInContext(host, context);
  const check = (language, stage) => {
    equal(ids["atlas-language"].value, language, "selector is normalized and synchronized");
    equal(document.documentElement.lang, language, "document language matches selected language");
    const heading = flatten(ids["atlas-content"]).find(node => node.tagName === "h1");
    equal(heading.textContent, labels[language][stage - 1], "stage heading follows selection");
    contains(body.textContent, labels[language][stage - 1], "body follows selection");
    equal(ids["atlas-view-files"].querySelector("span").textContent, labels[language][6], "navigation follows selection");
    equal(document.getElementById("host-open").textContent, labels[language][7], "host listener remains compatible");
    contains(body.textContent, "Original English topic", "source text remains in its recorded language");
  };
  check(labels[initial] ? initial : "en", 1);
  if (Object.hasOwn(options, "fixture")) {
    const notices = {en: "Simulated interface example", "zh-Hans": "界面模拟示例", "zh-Hant": "介面模擬範例"};
    const reports = {en: ["Open simulated Stage 2 report", "Original verified Stage 2 report & evaluation"], "zh-Hans": ["查看模拟 Stage 2 报告", "原始已验证 Stage 2 报告与评估"], "zh-Hant": ["檢視模擬 Stage 2 報告", "原始已驗證 Stage 2 報告與評估"]};
    for (const language of ["en", "zh-Hans", "zh-Hant"]) {
      ids["atlas-language"].change(language);
      ids["atlas-stages"].children[1].onclick(); check(language, 2);
      const banners = flatten(ids["atlas-content"]).filter(node => node.className.includes("atlas-fixture-notice"));
      equal(banners.length, payload.fixture === true ? 1 : 0, "only literal true marks the visible simulated interface");
      if (payload.fixture === true) contains(banners[0].textContent, notices[language], "simulated judgment warning follows the selected language");
      const report = flatten(ids["atlas-content"]).find(node => node.tagName === "a" && node.href === "./stage2/report-reader.html");
      equal(report.textContent, reports[language][payload.fixture === true ? 0 : 1], "fixture reports cannot be labelled as verified original evaluations");
      contains(document.getElementById("atlas-assessment").textContent, "P4: 83.3% (5/6)", "score presentation rounds its percentage while retaining the six-point unit");
      const stagePanels = flatten(ids["atlas-content"]), workflow = stagePanels.find(node => node.className.includes("atlas-workflow"));
      equal(stagePanels.indexOf(report) < stagePanels.indexOf(workflow), true, "Stage 2 result precedes its workflow in every language");
      equal(stagePanels.indexOf(workflow) < stagePanels.indexOf(document.getElementById("atlas-process")), true, "Stage 2 collapsed history follows workflow");
      equal(JSON.stringify(payload), before, "fixture marker, raw notice and raw score remain unchanged by language and stage navigation");
    }
    return;
  }
  if (options.focus) {
    const flushMicrotasks = () => { while (microtasks.length) microtasks.shift()(); };
    const flushFrames = () => { const pending = [...frames.values()]; frames.clear(); pending.forEach(callback => callback()); flushMicrotasks(); };
    const flush = () => { while (microtasks.length || frames.size) { flushMicrotasks(); if (frames.size) flushFrames(); } };
    const topicNode = () => flatten(document.getElementById("atlas-network")).find(node => node.dataset.nodeKind === "topic");
    const paperNode = () => flatten(document.getElementById("atlas-network")).find(node => node.className === "atlas-spatial-label atlas-spatial-paper");
    const modeControl = () => flatten(document.getElementById("atlas-network")).find(node => node.dataset.fakeControl === "mode");
    flush();
    const contentChildren = ids["atlas-content"].children, split = document.getElementById("atlas-network");
    const scope = contentChildren.find(node => node.className === "atlas-actions atlas-tabs");
    const collectionStatus = contentChildren.find(node => node.className === "atlas-small atlas-collection-status");
    assert(contentChildren.indexOf(split) < contentChildren.indexOf(scope), "phone DOM puts the graph before collection actions"); checks++;
    assert(contentChildren.indexOf(scope) < contentChildren.indexOf(collectionStatus), "collection status follows its actions in DOM order"); checks++;
    const graphChildren = split.children[0].children;
    const networkActions = graphChildren.find(node => node.className === "atlas-actions atlas-network-actions");
    const spatialControls = graphChildren.find(node => node.className === "atlas-actions atlas-spatial-controls");
    const spatialHost = graphChildren.find(node => node.className === "atlas-spatial-host");
    assert(graphChildren.indexOf(networkActions) < graphChildren.indexOf(spatialControls), "network actions precede mode controls in DOM order"); checks++;
    assert(graphChildren.indexOf(spatialControls) < graphChildren.indexOf(spatialHost), "all graph controls precede the graph in DOM order"); checks++;
    modeControl().focus(); const mountedTopic = topicNode(); window.resizeToPhone(false);
    equal(document.activeElement, modeControl(), "resize fallback restores the focused graph control after ancestor movement");
    equal(topicNode(), mountedTopic, "desktop breakpoint reorder preserves the mounted graph");
    assert(contentChildren.indexOf(scope) < contentChildren.indexOf(split), "desktop breakpoint moves collection context before the graph in DOM order"); checks++;
    window.resizeToPhone(true);
    equal(document.activeElement, modeControl(), "phone resize fallback restores focused graph control");
    equal(topicNode(), mountedTopic, "phone breakpoint reorder preserves the mounted graph");
    assert(contentChildren.indexOf(split) < contentChildren.indexOf(scope), "phone breakpoint restores graph-first DOM order"); checks++;
    topicNode().focus(); topicNode().onclick({key: "Enter"}); flushMicrotasks();
    equal(document.activeElement, document.body, "hidden replacement cannot accept the first focus attempt"); flushFrames();
    equal(document.activeElement, topicNode(), "Enter selection restores the visible logical topic after projection");
    topicNode().onclick({key: " "}); flush();
    equal(document.activeElement, topicNode(), "Space selection restores the visible logical topic after remount");
    paperNode().focus(); paperNode().onclick({key: "Enter"}); flush();
    equal(document.activeElement, paperNode(), "paper labels restore by accepted metadata without data-node-key");
    if (options.stableLabelIdentity) {
      equal(paperNode().textContent, paperNode().title, "selected paper presents its full title");
      paperNode().onclick({key: "Enter"}); flush();
      equal(paperNode().textContent, "P01", "clearing selection restores the compact alias");
      equal(document.activeElement, paperNode(), "stable paper identity retains focus when its rendered title changes");
    }
    modeControl().focus(); modeControl().onclick(); flush();
    equal(document.activeElement, modeControl(), "a remounted graph control retains its logical focus position");
    ids["atlas-language"].focus(); topicNode().onclick(); flush();
    equal(document.activeElement, ids["atlas-language"], "graph callbacks do not steal unrelated user focus");
    topicNode().focus(); topicNode().onclick(); ids["atlas-language"].focus(); ids["atlas-language"].change("zh-Hans"); flush();
    equal(document.activeElement, ids["atlas-language"], "superseded deferred mounts cannot restore phantom graph focus");
    return;
  }
  if (options.controlFocus) {
    const flushMicrotasks = () => { while (microtasks.length) microtasks.shift()(); };
    const control = key => flatten(body).find(node => node.dataset.atlasFocus === key);
    const clickAndRetain = (current, note) => {
      const key = current.dataset.atlasFocus; current.focus(); current.onclick(); flushMicrotasks();
      equal(document.activeElement, control(key), note);
    };
    const changeAndRetain = (key, value, note) => {
      const current = control(key); current.focus(); current.change(value); flushMicrotasks();
      equal(document.activeElement, control(key), note);
    };
    clickAndRetain(control("workflow:1:2"), "workflow steps retain logical focus after opening their product");
    const collectionTabs = () => flatten(ids["atlas-content"]).find(node => node.className === "atlas-actions atlas-tabs");
    clickAndRetain(collectionTabs().children[1], "archive collection tab retains logical focus after scope change");
    clickAndRetain(collectionTabs().children[0], "working collection tab retains logical focus after scope change");
    clickAndRetain(control("topic-card:Direction A"), "direction summary controls retain logical focus after selection");
    changeAndRetain("search", "Retained", "search retains logical focus after filtering");
    changeAndRetain("search", "", "clearing search retains logical focus");
    changeAndRetain("choice:topics", "Direction A", "topic filter retains logical focus");
    changeAndRetain("choice:topics", "", "clearing topic filter retains logical focus");
    changeAndRetain("choice:methods", "Shared original method", "method filter retains logical focus");
    changeAndRetain("choice:methods", "", "clearing method filter retains logical focus");
    changeAndRetain("choice:status", "unbound", "status filter retains logical focus");
    changeAndRetain("choice:status", "", "clearing status filter retains logical focus");
    changeAndRetain("choice:sorting", "title", "sorting retains logical focus");
    let stage = control("stage:2"); stage.focus(); stage.onclick(); flushMicrotasks();
    equal(document.activeElement, control("stage:2"), "Stage 2 retains its logical navigation focus");
    stage = control("stage:1"); stage.focus(); stage.onclick(); flushMicrotasks();
    equal(document.activeElement, control("stage:1"), "Stage 1 retains its logical navigation focus");
    let next = control("page:page:1"); next.focus(); next.onclick(); flushMicrotasks();
    equal(document.activeElement, control("page:page:1"), "pagination retains the enabled next control");
    next = control("page:page:1"); next.focus(); next.onclick(); flushMicrotasks();
    equal(document.activeElement, control("page:page:-1"), "pagination moves focus to the enabled peer at the last page");
    const search = control("search"); search.focus(); search.change("Retained");
    ids["atlas-language"].focus(); ids["atlas-stages"].children[1].onclick(); flushMicrotasks();
    equal(document.activeElement, ids["atlas-language"], "a newer render never steals unrelated focus for an older generation");
    return;
  }
  if (options.later) {
    const planned = {en: "Planned · not connected", "zh-Hans": "已规划 · 尚未连接", "zh-Hant": "已規劃 · 尚未連接"};
    const instructions = {en: "Workflow instructions", "zh-Hans": "工作流说明", "zh-Hant": "工作流程說明"};
    const actual = {en: "Actual recorded status", "zh-Hans": "实际记录状态", "zh-Hant": "實際記錄狀態"};
    const unknown = {en: "Unknown", "zh-Hans": "未知", "zh-Hant": "未知"};
    for (const language of ["en", "zh-Hans", "zh-Hant"]) {
      ids["atlas-language"].change(language);
      for (let stage = 3; stage <= 6; stage++) {
        ids["atlas-stages"].children[stage - 1].onclick(); check(language, stage);
        contains(ids["atlas-stages"].children[stage - 1].textContent, planned[language], "later-stage navigation declares its unconnected state");
        contains(ids["atlas-content"].textContent, planned[language], "later-stage panel repeats planned state without implying execution");
        contains(ids["atlas-content"].textContent, instructions[language], "workflow instructions have a separate heading");
        contains(ids["atlas-content"].textContent, actual[language], "actual recorded status has a separate heading");
        contains(ids["atlas-content"].textContent, unknown[language], "missing support and execution status remain Unknown");
      }
    }
    equal(JSON.stringify(payload), before, "later-stage browsing cannot alter source status records");
    return;
  }
  if (options.library) {
    const archiveLabel = {en: "Screening archive", "zh-Hans": "筛选档案", "zh-Hant": "篩選檔案"}[initial];
    const backLabel = {en: "Back to whole library", "zh-Hans": "返回完整文献库", "zh-Hant": "返回完整文獻庫"}[initial];
    const nextLabel = {en: "Next", "zh-Hans": "下一页", "zh-Hant": "下一頁"}[initial];
    const archiveButton = () => flatten(ids["atlas-content"]).find(node => node.tagName === "button" && node.textContent.startsWith(archiveLabel));
    archiveButton().onclick();
    const library = () => document.getElementById("atlas-library"), selectors = () => flatten(library()).filter(node => node.tagName === "select");
    library().open = true; library().ontoggle();
    const search = flatten(library()).find(node => node.tagName === "input" && node.type === "search"); search.change("Retained");
    selectors()[0].change("Direction A"); selectors()[1].change("Shared original method"); selectors()[2].change("unbound"); selectors()[3].change("title");
    flatten(library()).find(node => node.tagName === "button" && node.textContent === nextLabel).onclick();
    const rows = () => flatten(library()).filter(node => node.className === "atlas-paper"), retainedKeys = rows().map(node => node.dataset.paperKey).join("/"), selected = rows()[0];
    const selectedTitle = selected.children.find(node => node.tagName === "strong").textContent;
    window.scrollY = 1843; selected.onclick();
    const details = () => flatten(ids["atlas-content"]).find(node => node.className.includes("atlas-detail-panel"));
    contains(details().textContent, selectedTitle, "whole-library paper opens the same upper detailed paper view");
    equal(document.getElementById("atlas-network").lastScrollIntoView.block, "start", "library selection scrolls directly to the network detail");
    equal(rows().map(node => node.dataset.paperKey).join("/"), retainedKeys, "opening upper details preserves the current library page");
    window.scrollY = 240; flatten(details()).find(node => node.tagName === "button" && node.textContent === backLabel).onclick();
    equal(window.scrollY, 1843, "back to library restores the recorded scroll position"); equal(scrollCalls.at(-1).behavior, "auto", "return uses exact restoration rather than a moving smooth destination");
    equal(library().open, true, "return leaves the library expanded"); equal(archiveButton().attributes["aria-pressed"], "true", "return preserves archive scope");
    equal(flatten(library()).find(node => node.type === "search").value, "Retained", "return preserves the search text");
    equal(selectors().map(node => node.value).join("/"), "Direction A/Shared original method/unbound/title", "return preserves direction, method, status and ordering");
    equal(rows().map(node => node.dataset.paperKey).join("/"), retainedKeys, "return preserves exact second-page work/version identities");
    equal(Boolean(flatten(details()).find(node => node.textContent === backLabel)), false, "return clears its one-shot back control");
    rows()[0].onclick(); contains(details().textContent, selectedTitle, "reopening the same library paper does not toggle its details away");
    const filteredRelated = flatten(details()).find(node => node.dataset.relatedPaper === '["second","v1"]');
    equal(Boolean(filteredRelated), true, "related versions include targets outside the library filter"); filteredRelated.onclick();
    contains(details().textContent, "Second original title", "related click opens a target hidden by library filters");
    equal(selectors().map(node => node.value).join("/"), "Direction A/Shared original method/unbound/title", "related navigation preserves library filters and ordering");
    equal(rows().map(node => node.dataset.paperKey).join("/"), retainedKeys, "related navigation preserves the saved library page");
    equal(flatten(document.getElementById("atlas-network")).find(node => node.dataset.nodeKey === 'paper:["second","v1"]').attributes["aria-pressed"], "true", "related target gets exact graph focus despite filters");
    rows()[0].onclick();
    const summaryB = () => flatten(ids["atlas-content"]).find(node => node.className === "atlas-topic-card" && node.textContent.includes("Direction B"));
    const graphNode = key => flatten(ids["atlas-content"]).find(node => node.dataset.nodeKey === key);
    equal(Boolean(graphNode("topic:Direction B")), false, "library direction A initially limits the graph to its own context");
    const originalDetail = details().textContent, graphCoordinates = () => flatten(document.getElementById("atlas-network")).filter(node => node.className.includes("atlas-paper-node")).map(node => [node.dataset.nodeKey, node.style.left, node.style.top]).join("/");
    const originalGraph = graphCoordinates();
    summaryB().onclick();
    equal(graphNode("topic:Direction B").attributes["aria-pressed"], "true", "summary direction B is present and highlighted despite the library A filter");
    equal(graphNode('paper:["second","v1"]').dataset.muted, "false", "summary focus locates the target beyond the first 48-paper graph page");
    contains(details().textContent, "Second original title", "summary direction updates upper details with its recorded papers");
    equal(rows().map(node => node.dataset.paperKey).join("/"), retainedKeys, "summary graph pagination cannot replace the current library page");
    equal(selectors().map(node => node.value).join("/"), "Direction A/Shared original method/unbound/title", "summary focus cannot clear saved library filters or ordering");
    summaryB().onclick();
    equal(Boolean(graphNode("topic:Direction B")), false, "repeated summary category selection restores the original filtered graph");
    equal(graphCoordinates(), originalGraph, "clearing summary focus restores the separate graph page and coordinates");
    summaryB().onclick();
    flatten(ids["atlas-content"]).find(node => node.dataset.summaryPaper === '["second","v1"]').onclick();
    equal(graphNode('paper:["second","v1"]').attributes["aria-pressed"], "true", "summary paper outside the library filter is highlighted at its exact graph identity");
    contains(details().textContent, "Second original title", "summary paper updates the upper exact paper detail");
    equal(details().lastScrollIntoView.block, "start", "summary paper scrolls directly to the upper detail panel");
    equal(rows().map(node => node.dataset.paperKey).join("/"), retainedKeys, "summary paper focus retains the saved library page");
    equal(JSON.stringify(payload), before, "library navigation and return cannot change canonical paper records");
    return;
  }
  if (boundaries) {
    const resetLabel = {en: "Reset network", "zh-Hans": "返回全图", "zh-Hant": "返回全圖"}[initial];
    flatten(ids["atlas-content"]).find(node => node.tagName === "button" && node.textContent === resetLabel).onclick();
  }
  const graphNodes = () => flatten(ids["atlas-content"]).filter(node => node.className.includes("atlas-node"));
  const lineKinds = () => flatten(ids["atlas-content"]).filter(node => node.tagName === "line").map(node => node.dataset.kind);
  const visibleLines = () => flatten(ids["atlas-content"]).filter(node => node.tagName === "line" && node.style.display !== "none");
  const count = graphNodes().length;
  const coordinates = () => JSON.stringify(graphNodes().filter(node => node.className.includes("atlas-paper-node")).map(node => [node.dataset.nodeKey, node.style.left, node.style.top]));
  const originalCoordinates = coordinates();
  if (boundaries) {
    const shared = () => graphNodes().find(node => node.dataset.nodeKey === "method:Shared original method");
    const unique = () => graphNodes().find(node => node.dataset.nodeKey === "method:Unique recorded method");
    const firstPaper = () => graphNodes().find(node => node.dataset.nodeKey === 'paper:["fixture","v1"]');
    const otherPaper = () => graphNodes().find(node => node.dataset.nodeKey === 'paper:["second","v1"]');
    const unclassified = () => graphNodes().find(node => node.dataset.nodeKey === "topic:");
    const mainDetails = () => flatten(ids["atlas-content"]).find(node => node.className.includes("atlas-detail-panel"));
    const sharedPosition = [shared().style.left, shared().style.top].join("/");
    equal(Boolean(unique()), false, "unfocused singleton is not represented as a shared method hub");
    flatten(ids["atlas-content"]).find(node => node.tagName === "button" && node.textContent === "Unique recorded method · 1").onclick();
    equal(Boolean(unique()), true, "explicitly focused singleton is drawn beside existing shared hubs");
    equal(unique().attributes["aria-pressed"], "true", "focused singleton retains its exact method identity");
    equal([shared().style.left, shared().style.top].join("/"), sharedPosition, "appending a focused singleton cannot move the shared hub");
    equal(coordinates(), originalCoordinates, "focusing a singleton cannot reposition the whole paper network");
    equal(firstPaper().dataset.muted, "false", "singleton method links only its recorded member paper");
    equal(otherPaper().dataset.muted, "true", "other papers are not inferred to share a singleton method");
    contains(mainDetails().textContent, "Original English title", "singleton details retain the matching paper");
    unique().onclick();
    equal(Boolean(unique()), false, "repeated singleton click clears the extra focused hub");
    equal(coordinates(), originalCoordinates, "clearing a singleton restores the same paper coordinates");
    unclassified().onclick();
    equal(unclassified().attributes["aria-pressed"], "true", "unclassified category can receive graph focus");
    contains(mainDetails().textContent, "Unclassified retained title", "unclassified focus opens its retained paper instead of an empty list");
    equal(mainDetails().textContent.includes("Original English title"), false, "classified records are excluded from the unclassified detail list");
    equal(coordinates(), originalCoordinates, "unclassified focus cannot replace or reposition the main graph");
    unclassified().onclick();
    equal(unclassified().attributes["aria-pressed"], undefined, "repeated unclassified click clears focus");
    equal(graphNodes().length, count, "clearing boundary focus restores all initial graph nodes");
    equal(coordinates(), originalCoordinates, "boundary reset keeps exact paper positions");
    equal(document.getElementById("atlas-process").open, false, "boundary navigation leaves process history collapsed");
    equal(JSON.stringify(payload), before, "boundary navigation cannot change literal methods or Unknown source tags");
    return;
  }
  if (dense) {
    const nodes = graphNodes().filter(node => node.className.includes("atlas-paper-node"));
    equal(nodes.length, 30, "thirty paper versions remain drawn rather than silently truncated");
    equal(new Set(nodes.map(node => `${node.style.left}/${node.style.top}`)).size, 30, "dense direction gives every paper a distinct position");
  }
  equal(document.getElementById("atlas-process").tagName, "details", "process history uses progressive disclosure");
  equal(document.getElementById("atlas-process").open, false, "process history starts closed");
  equal(lineKinds().includes("direction"), true, "direction links retain their type");
  equal(lineKinds().includes("method"), true, "recorded method links retain their distinct type");
  const topicNode = () => graphNodes().find(node => node.dataset.nodeKey === "topic:Direction A");
  const basis = () => flatten(ids["atlas-content"]).find(node => node.className.includes("atlas-relation-list"));
  equal(basis().hidden, true, "default paper details do not expose relationship basis without a graph selection");
  equal(visibleLines().length, 0, "planar fallback initially conceals every relationship");
  topicNode().onpointerenter(); equal(visibleLines().length, 0, "hover does not reveal planar relationships");
  equal(basis().hidden, true, "hover cannot expose textual relationship basis");
  topicNode().onclick();
  equal(basis().hidden, false, "direction selection reveals its textual basis");
  equal(basis().open, true, "selected basis opens without another disclosure click");
  contains(basis().textContent, "Original English title", "basis preserves the selected direction's recorded paper");
  equal(basis().textContent.includes("Second original title"), false, "basis excludes unrelated direction papers");
  equal(visibleLines().every(line => line.dataset.kind === "direction"), true, "direction selection reveals only its incident membership lines");
  equal(visibleLines().length, dense ? 29 : 1, "the selected direction reveals all and only its recorded paper members");
  equal(graphNodes().length, count, "category selection must not replace the network with a subset");
  equal(coordinates(), originalCoordinates, "category selection keeps the v6 whole-canvas geometry");
  equal(topicNode().attributes["aria-pressed"], "true", "clicked category has focus");
  topicNode().onclick();
  equal(basis().hidden, true, "clearing selection conceals the textual basis again");
  equal(visibleLines().length, 0, "clearing planar selection conceals relationships again");
  equal(graphNodes().length, count, "clicking the same category restores the complete graph");
  equal(topicNode().attributes["aria-pressed"], undefined, "same-category click clears focus");
  const categoryCard = () => flatten(ids["atlas-content"]).find(node => node.className === "atlas-topic-card" && node.textContent.includes("Direction A"));
  categoryCard().onclick(); equal(graphNodes().length, count, "summary selection must preserve the complete main graph");
  equal(basis().hidden, false, "lower summary selection reveals the same upper basis");
  equal(topicNode().attributes["aria-pressed"], "true", "summary category highlights the matching graph node");
  const summary = document.getElementById("atlas-direction-summary");
  contains(summary.textContent, "Original English title", "summary has its own short paper list");
  const paperNode = () => graphNodes().find(node => node.dataset.nodeKey === 'paper:["fixture","v1"]');
  paperNode().onclick(); equal(paperNode().attributes["aria-pressed"], "true", "paper click opens its own details");
  contains(basis().textContent, "Shared original method", "paper basis includes recorded method membership");
  const relatedCard = flatten(ids["atlas-content"]).find(node => node.dataset.relatedPaper === '["second","v1"]');
  equal(Boolean(relatedCard), true, "right detail exposes exact related paper version");
  contains(flatten(ids["atlas-content"]).find(node => node.className === "atlas-related").textContent, "Shared original method", "related basis retains literal original method");
  relatedCard.onclick();
  contains(document.getElementById("atlas-paper-detail").textContent, "Second original title", "related paper opens upper detail");
  equal(document.getElementById("atlas-paper-detail").lastScrollIntoView.block, "start", "related paper scrolls to upper detail");
  paperNode().onclick();
  equal(coordinates(), originalCoordinates, "paper selection preserves all graph positions");
  const toggle = () => flatten(ids["atlas-content"]).find(node => node.tagName === "input" && node.type === "checkbox");
  toggle().checked = true; toggle().onchange();
  equal(coordinates(), originalCoordinates, "similarity overlays the v6 network rather than selecting a local layout");
  equal(graphNodes().length, count, "similarity does not remove direction or method nodes");
  equal(lineKinds().includes("similarity"), true, "global similarity uses its own edge class");
  const mainTitle = () => flatten(ids["atlas-content"]).find(node => node.className.includes("atlas-detail-panel")).textContent;
  const selectedDetail = mainTitle();
  flatten(ids["atlas-content"]).find(node => node.className === "atlas-topic-card" && node.textContent.includes("Direction B")).onclick();
  contains(mainTitle(), "Second original title", "direction summary updates upper details to its recorded papers");
  const summaryPaper = () => flatten(ids["atlas-content"]).find(node => node.dataset.summaryPaper === '["second","v1"]');
  summaryPaper().onclick(); equal(summaryPaper().attributes["aria-pressed"], "true", "summary paper toggles its own compact preview");
  equal(graphNodes().find(node => node.dataset.nodeKey === 'paper:["second","v1"]').attributes["aria-pressed"], "true", "summary paper highlights its exact graph node");
  contains(mainTitle(), "Second original title", "summary paper highlighting updates the upper detailed selection");
  equal(document.getElementById("atlas-paper-detail").lastScrollIntoView.block, "start", "summary selection scrolls directly to upper details");
  equal(coordinates(), originalCoordinates, "summary paper highlighting does not rearrange the network");
  summaryPaper().onclick(); equal(summaryPaper().attributes["aria-pressed"], "true", "reopening the same summary paper retains its detail");
  toggle().checked = false; toggle().onchange();
  paperNode().onclick(); paperNode().onclick(); equal(paperNode().attributes["aria-pressed"], undefined, "same-paper graph click clears focus");
  equal(document.getElementById("atlas-process").open, false, "node navigation does not expand process history");
  equal(JSON.stringify(payload), before, "node interactions cannot mutate retained research records");
  for (const language of ["en", "zh-Hans", "zh-Hant", "invalid"]) {
    ids["atlas-language"].change(language); check(labels[language] ? language : "en", 1);
  }
  paperNode().onclick();
  flatten(ids["atlas-content"]).find(node => node.tagName === "button" && node.textContent === "Local network").onclick();
  equal(lineKinds().includes("similarity"), true, "local graph labels computed similarity links separately");
  equal(graphNodes().every(node => node.dataset.nodeKey.startsWith("paper:")), true, "every local paper has an exact identity");
  equal(paperNode().dataset.muted, "false", "local focused paper remains visible");
  equal(basis().hidden, false, "local planar selection retains its textual relationship basis");
  contains(basis().textContent, "Original English title", "local basis belongs to the exact selected paper");
  contains(basis().textContent, "Jaccard", "local fallback computed relation retains its actual metric label");
  paperNode().onpointerenter(); equal(paperNode().dataset.muted, "false", "local hover uses exact paper identity");
  paperNode().onclick(); equal(paperNode().attributes["aria-pressed"], undefined, "same local paper toggles back without library navigation");
  equal(basis().hidden, true, "clearing local paper also hides its textual basis");
  equal(graphNodes().length, count, "same local paper restores the full classified network");
  ids["atlas-stages"].children[1].onclick(); check("en", 2);
  equal(document.getElementById("atlas-process").tagName, "details", "Stage 2 process history also uses progressive disclosure");
  equal(document.getElementById("atlas-process").open, false, "Stage 2 process history starts closed");
  ids["atlas-language"].change("zh-Hant"); check("zh-Hant", 2);
  equal(JSON.stringify(payload), before, "view changes cannot alter canonical records");
}
for (const initial of ["zh-Hans", "zh-Hant", "invalid"]) for (const hostFirst of [true, false]) runCase(initial, hostFirst);
runCase("en", false, true);
for (const language of ["en", "zh-Hans", "zh-Hant"]) runCase(language, false, false, true);
for (const language of ["en", "zh-Hans", "zh-Hant"]) runCase(language, false, true, false, {library: true});
for (const fixture of [true, false, "true"]) runCase("en", false, false, false, {fixture});
for (const language of ["en", "zh-Hans", "zh-Hant"]) runCase(language, false, true, false, {controlFocus: true});
runCase("en", false, false, false, {focus: true, mobile: true});
for (const language of ["en", "zh-Hans", "zh-Hant"]) runCase(language, false, false, false, {focus: true, mobile: true, stableLabelIdentity: true});
runCase("en", false, false, false, {later: true});
console.log(`Atlas language DOM regression: ${checks} assertions passed; synthetic DOM and inert host only.`);
