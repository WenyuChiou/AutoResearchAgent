/* Actual host/session/chat scripts with a small DOM substitute. CSS assertions
   check the bounded scroll contract; they do not measure browser layout. */
"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");
const assets = process.argv[2] ? path.resolve(process.argv[2]) : path.join(__dirname, "../cli/research_workspace_native/web");
const cssPath = process.argv[3] ? path.resolve(process.argv[3]) : path.join(__dirname, "../references/research-workspace/atlas/atlas.css");
const fixture = JSON.parse(fs.readFileSync(path.join(__dirname, "fixtures/native-atlas-pipeline-view-v1.json"), "utf8"));
const flatten = node => [node, ...node.children.flatMap(flatten)];
const tick = () => new Promise(resolve => setImmediate(resolve));
async function mount(locale, scenario = {}) {
  let document;
  const focused = [], calls = [], observers = [], storage = new Map();
  class Element {
    constructor(tag) {this.tagName = tag.toUpperCase(); this.children = []; this.dataset = {}; this.attrs = {}; this.events = {}; this.value = ""; this._text = "";}
    get textContent() {return this._text + this.children.map(e => e.textContent).join("");}
    set textContent(value) {this._text = String(value); this.replaceChildren();}
    get childElementCount() {return this.children.length;}
    get isConnected() {return this.tagName === "HTML" || Boolean(this.parent?.isConnected);}
    append(...nodes) {for (const node of nodes) {node.remove(); node.parent = this; this.children.push(node);}}
    prepend(node) {node.remove(); node.parent = this; this.children.unshift(node);}
    remove() {if (this.parent) {this.parent.children = this.parent.children.filter(e => e !== this); this.parent = null;}}
    replaceChildren(...nodes) {for (const node of this.children) node.parent = null; this.children = []; this.append(...nodes);}
    setAttribute(name, value) {this.attrs[name] = String(value);}
    addEventListener(event, handler) {(this.events[event] ||= []).push(handler);}
    async emit(event, detail = {}) {for (const handler of this.events[event] || []) await handler(detail);}
    focus() {document.activeElement = this; focused.push(this);}
    querySelectorAll(selector) {assert.equal(selector, "[data-native-label]"); return flatten(this).filter(e => e.dataset.nativeLabel);}
    set innerHTML(_) {throw Error("No HTML interpolation");}
  }
  const html = new Element("html"); html.lang = locale; html.dataset.atlasStage = "1";
  const body = new Element("body"); html.append(body);
  const language = new Element("select"); language.id = "atlas-language"; language.value = locale; body.append(language);
  document = {documentElement: html, body, activeElement: body, createElement: tag => new Element(tag),
    querySelector: () => null, getElementById: id => flatten(html).find(e => e.id === id)};
  const window = {WORKSPACE_HOST: {credential: "only-in-memory", current_case: "fixture", maintenance_enabled: false,
    cases: [{ref: "fixture", label: "Synthetic UI QA", project_id: "internal-a", index_sha256: fixture.index_sha256,
      manifest_sha256: "b".repeat(64), url: "/views/fixture/atlas.html", fixture: true}], connection: scenario.connection || {status: "not-checked"}},
    WORKSPACE_NATIVE_ATLAS: {enabled: true, credential: "only-in-memory", current_case: "fixture", project_ref: fixture.project_ref,
      index_sha256: fixture.index_sha256, input_version: fixture.input_version}};
  const listeners = new Map();
  window.addEventListener = (type, handler) => {(listeners.get(type) || listeners.set(type, []).get(type)).push(handler);};
  window.dispatchEvent = event => {for (const handler of listeners.get(event.type) || []) handler(event); return true;};
  class CustomEvent {constructor(type, options = {}) {this.type = type; this.detail = options.detail;}}
  const context = vm.createContext({window, document, TextEncoder, URL, CustomEvent,
    location: {href: "http://127.0.0.1:8774/views/fixture/atlas.html", origin: "http://127.0.0.1:8774"},
    sessionStorage: {getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, String(value)), removeItem: key => storage.delete(key)},
    crypto: {randomUUID: () => "12345678-1234-1234-1234-123456789abc"},
    MutationObserver: class {constructor(callback) {observers.push(callback);} observe() {}},
    fetch: async (url, options) => {
      calls.push({url, ...options});
      const value = url === "/api/connection" ? {status: "check-passed"} : url.endsWith("/offer") ?
        {offer_ref: "1".repeat(64), offer_sha256: "2".repeat(64), revision: fixture.revision, max_text_bytes: 16384} :
        options.method === "POST" ? {status: "dispatched"} : JSON.parse(JSON.stringify(fixture));
      if (scenario.transform && url !== "/api/connection" && !url.endsWith("/offer") && options.method !== "POST") scenario.transform(value);
      return {ok: true, json: async () => value};
    }});
  for (const filename of ["atlas-host.js", "session-panel.js", "native-atlas-chat.js"])
    vm.runInContext(fs.readFileSync(path.join(assets, filename), "utf8"), context, {filename});
  await tick(); await tick();
  return {document, html, language, calls, focused, observers};
}
(async () => {
  const ready = {status: "native-ready", actual_codex_process_observed: true, authenticated_process: false};
  const hostText = state => flatten(state.html).find(node => node.className === "host-boundary").textContent;
  const hostStatus = state => flatten(state.html).find(node => node.className === "host-status");
  const replied = locale => locale === "en" ? "Saved Codex reply observed" : locale === "zh-Hans" ? "已观察到保存的 Codex 回复" : "已觀察到儲存的 Codex 回覆";
  const pending = locale => locale === "en" ? "No saved model reply is visible yet" : locale === "zh-Hans" ? "目前尚未看到已保存的模型回复" : "目前尚未看到已儲存的模型回覆";
  const boundaryText = state => flatten(state.html).find(node => node.dataset.nativeLabel === "nativeBoundary" || node.dataset.nativeLabel === "boundary").textContent;
  let cases = 0;
  for (const locale of ["en", "zh-Hans", "zh-Hant"]) {
    const real = await mount(locale, {connection: ready});
    assert.equal(hostStatus(real).dataset.status, "native-ready");
    assert.ok(hostText(real).includes(replied(locale)));
    assert.ok(!boundaryText(real).includes(locale === "en" ? "Injected" : locale === "zh-Hans" ? "注入" : "注入"));
    assert.ok(real.html.textContent.includes(locale === "en" ? "Synthetic repository fixture" : locale === "zh-Hans" ? "仓库合成测试案例" : "儲存庫合成測試案例"));
    assert.equal(real.calls.filter(row => row.method === "POST").length, 0);
    cases++;
    const synthetic = await mount(locale);
    assert.equal(hostStatus(synthetic).dataset.status, "not-checked");
    assert.ok(!hostText(synthetic).includes(replied(locale)));
    assert.ok(hostText(synthetic).includes(locale === "en" ? "fixture reply" : locale === "zh-Hans" ? "演示回复" : "示範回覆"));
    cases++;
    for (const variant of ["user-tool-terminal", "no-frame", "conflict", "malformed", "stale-binding", "partial"]) {
      const state = await mount(locale, {connection: ready, transform: view => {
        const entry = view.transcript.entries.find(row => row.role === "assistant");
        if (variant === "user-tool-terminal") view.transcript.entries = view.transcript.entries.filter(row => row.role !== "assistant");
        if (variant === "no-frame") entry.frame_refs = [];
        if (variant === "conflict") {entry.kind = "assistant-conflict"; entry.status = "unknown"; entry.text = null; entry.failure = "conflicting-saved-item";}
        if (variant === "malformed") entry.frame_refs[0].raw_sha256 = "tampered";
        if (variant === "stale-binding") view.input_version = "f".repeat(64);
        if (variant === "partial") {entry.kind = "assistant-delta"; entry.status = "partial";}
      }});
      assert.ok(!hostText(state).includes(replied(locale)), variant);
      if (variant !== "partial") assert.ok(hostText(state).includes(pending(locale)), variant);
      assert.equal(state.calls.filter(row => row.method === "POST").length, 0);
      cases++;
    }
    const stopped = await mount(locale, {connection: ready, transform: view => {view.failure = "session-stopped";}});
    assert.equal(hostStatus(stopped).dataset.status, "native-stopped");
    assert.ok(hostText(stopped).includes(replied(locale))); // Historical evidence retained.
    assert.ok(stopped.html.textContent.includes("session-stopped"));
    cases++;
    const unchecked = await mount(locale, {connection: {...ready, actual_codex_process_observed: false}});
    assert.equal(hostStatus(unchecked).dataset.status, "not-checked");
    assert.ok(!hostText(unchecked).includes(replied(locale)));
    cases++;
  }
  console.log("PASS " + cases + " status cases; actual scripts + DOM fixture, no native/model or new I/O");
})().catch(error => {console.error(error); process.exitCode = 1;});
