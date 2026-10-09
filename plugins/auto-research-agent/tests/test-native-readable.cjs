/* Actual panel/scope scripts with a DOM substitute, not measured browser layout. */
"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");
const assets = process.argv[2] ? path.resolve(process.argv[2]) : path.join(__dirname, "../cli/research_workspace_native/web");
const hash = c => c.repeat(64), copy = value => JSON.parse(JSON.stringify(value));
const flatten = e => [e, ...e.children.flatMap(flatten)];
const visible = e => e.tagName === "DETAILS" && !e.open ? e.children.find(c => c.tagName === "SUMMARY")?.textContent || "" : e._text + e.children.map(visible).join(" ");
const tick = () => new Promise(resolve => setImmediate(resolve));
async function mount(locale, observed = true) {
  class Element {
    constructor(tag) {this.tagName = tag.toUpperCase(); this.children = []; this.dataset = {}; this.attrs = {}; this._text = ""; this.value = "";}
    get textContent() {return this._text + this.children.map(e => e.textContent).join("");}
    set textContent(v) {this._text = String(v); this.replaceChildren();}
    get childElementCount() {return this.children.length;}
    get isConnected() {return this.tagName === "HTML" || Boolean(this.parent?.isConnected);}
    append(...items) {for (const e of items) {e.remove(); e.parent = this; this.children.push(e);}}
    prepend(e) {e.remove(); e.parent = this; this.children.unshift(e);}
    remove() {if (this.parent) {this.parent.children = this.parent.children.filter(e => e !== this); this.parent = null;}}
    replaceChildren(...items) {for (const e of this.children) e.parent = null; this.children = []; this.append(...items);}
    setAttribute(k, v) {this.attrs[k] = String(v);}
    querySelectorAll(selector) {
      if (selector === "[data-native-label]") return flatten(this).filter(e => e.dataset.nativeLabel);
      if (selector === "[data-scope-label]") return flatten(this).filter(e => e.dataset.scopeLabel);
      if (selector === "[data-scope-aria]") return flatten(this).filter(e => e.dataset.scopeAria);
      assert.equal(selector, "input, textarea, select, button");
      return flatten(this).filter(e => ["INPUT", "TEXTAREA", "SELECT", "BUTTON"].includes(e.tagName));
    }
    set innerHTML(_) {throw Error("No HTML interpolation");}
  }
  const html = new Element("html"); html.lang = locale;
  const body = new Element("body"), host = new Element("section"); host.id = "host-panel"; html.append(body); body.append(host);
  const document = {documentElement: html, body, createElement: tag => new Element(tag), querySelector: () => null,
    getElementById: id => flatten(html).find(e => e.id === id)};
  const base = {project_ref: "case", index_sha256: hash("a"), input_version: hash("b"), revision: 8, failure: null,
    requests: [{request_ref: hash("c"), request_sha256: hash("d"), method: "item/tool/requestUserInput", status: "pending", payload: {questions: [{id: "q", question: "Literal <img> source question"}]}},
      {request_ref: hash("e"), request_sha256: hash("f"), method: "item/commandExecution/requestApproval", status: "pending", can_accept: false,
        payload: {command: "synthetic-no-op", reason: "Literal approval reason"}}], operations: [],
    actions: [{kind: "answer", status: "refused", failure: "approval-not-admitted", client_key: "older", target_ref: hash("1")} ]};
  const snapshot = {version_ref: hash("2"), sha256: hash("3"), parent_ref: null, original_description: "Literal 原文 <img> research request",
    scope_fields: [{field: "geography", material: true, reason: "Original scope rationale"}],
    scope: {geography: {status: "pending", value: null}}, decisions: []};
  const history = {...base, latest_version_ref: snapshot.version_ref,
    versions: [{version_ref: snapshot.version_ref, sha256: snapshot.sha256, parent_ref: null}], actions: []};
  const snapshots = new Map([[snapshot.version_ref, copy(snapshot)]]);
  const calls = [], storage = new Map(), observers = [];
  const window = {WORKSPACE_NATIVE_ATLAS: {enabled: true, credential: "memory-only", project_ref: base.project_ref,
    index_sha256: base.index_sha256, input_version: base.input_version}};
  const context = vm.createContext({window, document, TextEncoder, crypto: {randomUUID: () => "12345678-1234-1234-1234-123456789abc"},
    sessionStorage: {getItem: k => storage.get(k) ?? null, setItem: (k, v) => storage.set(k, v)},
    MutationObserver: class {constructor(callback) {observers.push(callback);} observe() {}},
    fetch: async (url, options) => {
      calls.push({url, ...options});
      if (options.method === "POST") {
        const request = JSON.parse(options.body);
        if (url.endsWith("/answers")) return {ok: false, json: async () => ({error: "approval-not-admitted"})};
        if (observed) {
          const old = snapshot.version_ref; snapshot.version_ref = hash("4"); snapshot.sha256 = hash("5"); snapshot.parent_ref = old;
          history.latest_version_ref = snapshot.version_ref;
          snapshots.set(snapshot.version_ref, copy(snapshot));
          history.versions.push({version_ref: snapshot.version_ref, sha256: snapshot.sha256, parent_ref: old});
          history.actions.push({action_ref: hash("6"), client_key: request.key, kind: "append", status: "version-saved",
            version_ref: snapshot.version_ref, version_sha256: snapshot.sha256});
          return {ok: true, json: async () => copy(history.actions.at(-1))};
        }
        history.latest_version_ref = hash("7"); history.versions.push({version_ref: hash("7"), sha256: hash("8"), parent_ref: hash("2")});
        snapshot.version_ref = hash("7"); snapshot.sha256 = hash("8");
        snapshots.set(snapshot.version_ref, copy(snapshot));
        throw Error("response-lost"); // A changed version alone does not attest this key.
      }
      return {ok: true, json: async () => copy(url.endsWith("/scope") ? history : url.includes("/scope/versions/") ? snapshots.get(url.split("/").at(-1)) : base)};
    }});
  for (const script of ["session-panel.js", "session-scope.js"]) vm.runInContext(fs.readFileSync(path.join(assets, script), "utf8"), context, {filename: script});
  await tick(); await tick(); await tick();
  return {html, document, calls, storage, observers};
}
async function submitScope(state) {
  const form = state.document.getElementById("native-scope-form");
  const controls = flatten(form);
  controls.find(e => e.dataset.scopeAria === "field").value = "geography";
  controls.find(e => e.dataset.scopeAria === "choice").value = "unrestricted";
  controls.find(e => e.dataset.scopeAria === "reason").value = "Keep broad";
  controls.find(e => e.dataset.scopeAria === "original").value = "Original instruction";
  controls.find(e => e.type === "checkbox").checked = true;
  form.onsubmit({preventDefault() {}});
  for (let i = 0; i < 5; i++) await tick();
}
(async () => {
  for (const locale of ["en", "zh-Hans", "zh-Hant"]) {
    const state = await mount(locale), all = flatten(state.html), shown = visible(state.html);
    assert.ok(shown.includes("Literal <img> source question"));
    assert.ok(shown.includes("synthetic-no-op") && shown.includes("Literal approval reason"));
    assert.ok(shown.includes("refused") && shown.includes("approval-not-admitted"));
    assert.ok(shown.includes("Literal 原文 <img> research request") && shown.includes("Unknown"));
    assert.ok(!shown.includes(hash("a")) && !shown.includes(hash("c")) && !shown.includes(hash("3")));
    assert.ok(all.filter(e => e.tagName === "PRE").every(e => e.parent.tagName === "DETAILS" && !e.parent.open));
    assert.equal(all.filter(e => e.tagName === "IMG").length, 0);
    assert.ok(all.filter(e => e.dataset.nativeLabel === "accept").every(e => e.disabled));
    assert.ok(all.filter(e => ["decline", "cancel"].includes(e.dataset.nativeLabel)).every(e => !e.disabled));
    const label = all.find(e => e.dataset.nativeLabel === "question").textContent;
    assert.equal(label, locale === "en" ? "Your answer is needed" : "需要你回答");
    const original = all.find(e => e.tagName === "P" && e.textContent === "Literal 原文 <img> research request");
    assert.equal(original.attrs.translate, "no");
    await submitScope(state);
    assert.ok(visible(state.document.getElementById("native-scope-panel")).includes(locale === "en" ? "Decision record saved" : locale === "zh-Hans" ? "决定记录已保存" : "決定紀錄已儲存"));
    assert.equal(state.calls.filter(c => c.method === "POST").length, 1);
    assert.equal([...state.storage.values()].map(JSON.parse).flat().length, 1); // No unknown-key clearing.
    console.log("PASS readable collapsed source records and exact saved decision: " + locale);
  }
  const uncertain = await mount("en", false);
  await submitScope(uncertain);
  const text = visible(uncertain.document.getElementById("native-scope-panel"));
  assert.ok(text.includes("Local intent retained") && !text.includes("Decision record saved"));
  assert.equal(uncertain.calls.filter(c => c.method === "POST").length, 1);
  assert.equal([...uncertain.storage.values()].map(JSON.parse).flat().length, 1);
  const denied = await mount("en");
  const decline = flatten(denied.html).find(e => e.dataset.nativeLabel === "decline");
  await decline.onclick(); await tick();
  assert.ok(visible(denied.document.getElementById("native-notice")).includes("approval-not-admitted"));
  const body = JSON.parse(denied.calls.find(c => c.method === "POST").body);
  assert.deepEqual(Object.keys(body).sort(), ["index_sha256", "input_version", "key", "request_ref", "request_sha256", "result", "revision"]);
  assert.deepEqual(body.result, {decision: "decline"});
  console.log("PASS response-loss/version-change retains unknown and rejection remains visible with unchanged wire shape");
  console.log("PASS 4 tests; actual scripts with DOM substitute, no browser/native/model");
})().catch(error => {console.error(error); process.exitCode = 1;});
