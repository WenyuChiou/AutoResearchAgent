/* Actual host/session/chat scripts with a small DOM substitute. CSS assertions
   check the bounded scroll contract; they do not measure browser layout. */
"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");
const assets = process.argv[2] ? path.resolve(process.argv[2]) : path.join(__dirname, "../cli/research_workspace_native/web");
const cssPath = process.argv[3] ? path.resolve(process.argv[3]) : path.join(__dirname, "../references/research-workspace/atlas/atlas.css");
const fixture = JSON.parse(fs.readFileSync(path.join(__dirname, "fixtures/native-atlas-pipeline-view-v1.json"), "utf8"));
const flatten = node => [node, ...node.children.flatMap(flatten)];
const tick = () => new Promise(resolve => setImmediate(resolve));
async function mount(locale) {
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
      manifest_sha256: "b".repeat(64), url: "/views/fixture/atlas.html", fixture: true}], connection: {status: "not-checked"}},
    WORKSPACE_NATIVE_ATLAS: {enabled: true, credential: "only-in-memory", current_case: "fixture", project_ref: fixture.project_ref,
      index_sha256: fixture.index_sha256, input_version: fixture.input_version}};
  const context = vm.createContext({window, document, TextEncoder, URL,
    location: {href: "http://127.0.0.1:8774/views/fixture/atlas.html", origin: "http://127.0.0.1:8774"},
    sessionStorage: {getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, String(value)), removeItem: key => storage.delete(key)},
    crypto: {randomUUID: () => "12345678-1234-1234-1234-123456789abc"},
    MutationObserver: class {constructor(callback) {observers.push(callback);} observe() {}},
    fetch: async (url, options) => {
      calls.push({url, ...options});
      const value = url === "/api/connection" ? {status: "check-passed"} : url.endsWith("/offer") ?
        {offer_ref: "1".repeat(64), offer_sha256: "2".repeat(64), revision: fixture.revision, max_text_bytes: 16384} :
        options.method === "POST" ? {status: "dispatched"} : JSON.parse(JSON.stringify(fixture));
      return {ok: true, json: async () => value};
    }});
  for (const filename of ["atlas-host.js", "session-panel.js", "native-atlas-chat.js"])
    vm.runInContext(fs.readFileSync(path.join(assets, filename), "utf8"), context, {filename});
  await tick(); await tick();
  return {document, html, language, calls, focused, observers};
}
(async () => {
  for (const locale of ["en", "zh-Hans", "zh-Hant"]) {
    const state = await mount(locale), find = id => state.document.getElementById(id);
    const panel = find("host-panel"), toggle = find("host-open"), text = find("native-chat-text");
    assert.equal(panel.hidden, true);
    await toggle.emit("click"); assert.equal(panel.hidden, false); assert.equal(toggle.attrs["aria-expanded"], "true");
    text.focus(); const focused = state.focused.length;
    await find("native-chat-prepare").onclick(); text.value = "Synthetic explicit message";
    await text.parent.onsubmit({preventDefault() {}});
    assert.equal(panel.hidden, false); assert.equal(state.focused.length, focused);
    assert.equal(state.calls.filter(row => row.method === "POST").length, 1);
    const nativeRefresh = flatten(state.html).find(node => node.dataset.nativeLabel === "refresh");
    await nativeRefresh.onclick(); await nativeRefresh.onclick();
    const hostRefresh = flatten(state.html).find(node => node.className === "host-refresh");
    await hostRefresh.emit("click");
    assert.equal(panel.hidden, false); assert.equal(toggle.attrs["aria-expanded"], "true");
    assert.equal(state.focused.length, focused);
    assert.equal(state.calls.filter(row => row.method === "POST").length, 1);
    state.language.value = locale === "en" ? "zh-Hans" : "en";
    state.document.documentElement.lang = state.language.value;
    await state.language.emit("change"); state.observers.forEach(callback => callback());
    assert.equal(panel.hidden, false); assert.equal(state.focused.length, focused);
    assert.equal(flatten(state.html).filter(node => node.id === "host-panel").length, 1);
    assert.ok(find("native-chat-transcript").textContent.includes("Literal <img> 简體 saved model-text fixture."));
    await panel.emit("keydown", {key: "Escape"}); assert.equal(panel.hidden, true);
    assert.equal(state.document.activeElement, toggle);
    console.log("PASS drawer message/GET/locale preserves open state and no explicit focus grab: " + locale);
  }
  const css = fs.readFileSync(cssPath, "utf8");
  const rule = /\.atlas-network-split\s*>\s*\.atlas-detail-panel\s*\{([^}]+)\}/g;
  const declarations = [...css.matchAll(rule)].map(match => match[1]).join(";");
  assert.match(declarations, /max-height\s*:\s*900px\s*;/);
  assert.match(declarations, /overflow-y\s*:\s*auto\s*;/);
  assert.match(declarations, /min-height\s*:\s*0\s*;/);
  assert.doesNotMatch(declarations, /display\s*:\s*none|overflow(?:-y)?\s*:\s*hidden/);
  assert.match(css, /summary:focus-visible\s*\{[^}]*outline/);
  console.log("PASS long detail has a bounded independent scroll contract; no measured browser layout");
  console.log("PASS 4 tests; actual scripts plus DOM/CSS contract, no native/model");
})().catch(error => {console.error(error); process.exitCode = 1;});
