/* Actual panel/scope scripts with a DOM substitute, not measured browser layout. */
"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");
const assets = process.argv[2] ? path.resolve(process.argv[2]) : path.join(__dirname, "../cli/research_workspace_native/web");
const hash = c => c.repeat(64), copy = value => JSON.parse(JSON.stringify(value));
const flatten = e => [e, ...e.children.flatMap(flatten)];
const visible = e => e.tagName === "DETAILS" && !e.open ? e.children.find(c => c.tagName === "SUMMARY")?.textContent || "" : e._text + e.children.map(visible).join(" ");
const tick = () => new Promise(resolve => setImmediate(resolve));
async function mount(locale, mode) {
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
  const snapshot = {version_ref: hash("2"), sha256: hash("3"), parent_ref: null, revision: 9, original_description: "Literal 原文 <img> research request",
    scope_fields: [{field: "geography", material: true, reason: "Original scope rationale"}],
    scope: {geography: {status: "pending", value: null}}, decisions: []};
  const history = {...base, latest_version_ref: snapshot.version_ref,
    versions: [{version_ref: snapshot.version_ref, sha256: snapshot.sha256, parent_ref: null}], actions: []};
  const snapshots = new Map([[snapshot.version_ref, copy(snapshot)]]);
  const calls = [], storage = new Map(), observers = []; let keys = 0;
  if (mode === "legacy") storage.set(`native-scope-intents:${base.project_ref}:${base.index_sha256}:${base.input_version}`,
    JSON.stringify([{key: "12345678-1234-1234-1234-123456789abc", kind: "versions", target: snapshot.version_ref}]));
  const window = {WORKSPACE_NATIVE_ATLAS: {enabled: true, credential: "memory-only", project_ref: base.project_ref,
    index_sha256: base.index_sha256, input_version: base.input_version}};
  const context = vm.createContext({window, document, TextEncoder, crypto: {randomUUID: () => `12345678-1234-1234-1234-${String(++keys).padStart(12, "0")}`, subtle: {digest: async (_algorithm, bytes) => Uint8Array.from(require("node:crypto").createHash("sha256").update(bytes).digest()).buffer}},
    sessionStorage: {getItem: k => storage.get(k) ?? null, setItem: (k, v) => storage.set(k, v)},
    MutationObserver: class {constructor(callback) {observers.push(callback);} observe() {}},
    fetch: async (url, options) => {
      calls.push({url, ...options});
      if (options.method === "POST") {
        const request = JSON.parse(options.body);
        if (url.endsWith("/answers")) return {ok: false, json: async () => ({error: "approval-not-admitted"})};
        if (calls.filter(c => c.method === "POST").length === 2) {
          const old = snapshot.version_ref; snapshot.version_ref = hash("4"); snapshot.sha256 = hash("5"); snapshot.parent_ref = old;
          snapshot.revision = ++history.revision; base.revision = history.revision;
          history.latest_version_ref = snapshot.version_ref; snapshots.set(snapshot.version_ref, copy(snapshot));
          history.versions.push({version_ref: snapshot.version_ref, sha256: snapshot.sha256, parent_ref: old});
          const row = {action_ref: hash("6"), client_key: request.key, kind: "append", status: "version-saved",
            version_ref: snapshot.version_ref, version_sha256: snapshot.sha256};
          history.actions.push(row); return {ok: true, json: async () => row};
        }
        const stable = value => JSON.stringify(value, (_key, item) => item && typeof item === "object" && !Array.isArray(item) ?
          Object.fromEntries(Object.keys(item).sort().map(k => [k, item[k]])) : item);
        const sha = value => require("node:crypto").createHash("sha256").update(stable(value)).digest("hex");
        const semantic = copy(request); delete semantic.revision;
        const row = {action_ref: hash("6"), client_key: request.key, kind: "append", status: "rejected-known-unsent",
          version_ref: request.parent_ref, version_sha256: request.parent_sha256, failure: "stale-revision", execution_authorized: false,
          submitted_request: copy(request), submitted_request_sha256: sha(request), request_sha256: sha({kind: "append", body: semantic}),
          submitted_revision: request.revision, observed_revision: 10};
        if (mode === "wrong-body") row.submitted_request.choices[0].reason = "different payload";
        if (mode === "wrong-hash") row.submitted_request_sha256 = hash("0");
        if (mode === "wrong-revision") row.submitted_revision--;
        if (mode === "wrong-target") row.version_ref = hash("0");
        if (mode === "missing-body") delete row.submitted_request;
        if (mode === "authorized") row.execution_authorized = true;
        if (mode !== "no-receipt") history.actions.push(row);
        history.revision = 10; snapshot.revision = 10; snapshots.set(snapshot.version_ref, copy(snapshot)); base.revision = 10;
        if (mode === "lost-response") throw Error("response-lost");
        return {ok: false, json: async () => ({error: "stale-revision"})};
      }
      return {ok: true, json: async () => copy(url.endsWith("/scope") ? history : url.includes("/scope/versions/") ? snapshots.get(url.split("/").at(-1)) : base)};
    }});
  for (const script of ["session-panel.js", "session-scope.js"]) vm.runInContext(fs.readFileSync(path.join(assets, script), "utf8"), context, {filename: script});
  await tick(); await tick(); await tick();
  return {html, document, calls, storage, observers};
}
async function submitScope(state, twice = false) {
  const form = state.document.getElementById("native-scope-form"), controls = flatten(form);
  controls.find(e => e.dataset.scopeAria === "field").value = "geography";
  controls.find(e => e.dataset.scopeAria === "choice").value = "unrestricted";
  controls.find(e => e.dataset.scopeAria === "reason").value = "Keep broad";
  controls.find(e => e.dataset.scopeAria === "original").value = "Original instruction";
  controls.find(e => e.type === "checkbox").checked = true;
  form.onsubmit({preventDefault() {}});
  if (twice) form.onsubmit({preventDefault() {}});
  for (let i = 0; i < 8; i++) await tick();
}
const saveButton = state => flatten(state.document.getElementById("native-scope-form")).find(e => e.dataset.scopeLabel === "save");
const local = state => [...state.storage.values()].map(JSON.parse).flat();
(async () => {
  for (const locale of ["en", "zh-Hans", "zh-Hant"]) {
    const state = await mount(locale, "known");
    await submitScope(state, true);
    const posts = state.calls.filter(c => c.method === "POST");
    assert.equal(posts.length, 1); // Digest wait/double click cannot duplicate POST.
    assert.equal(JSON.parse(posts[0].body).revision, 9); // The second scope GET is newer than history.
    assert.equal(saveButton(state).disabled, false);
    assert.equal(local(state).length, 1); assert.ok(local(state)[0].request_sha256);
    const text = visible(state.document.getElementById("native-scope-panel"));
    assert.ok(text.includes(locale === "en" ? "was not applied" : locale === "zh-Hans" ? "此决定未应用" : "此決定未套用"));
    assert.ok(text.includes("stale-revision"));
    await tick(); assert.equal(state.calls.filter(c => c.method === "POST").length, 1);
    await submitScope(state); // Only this explicit user action produces the second key/POST.
    assert.equal(state.calls.filter(c => c.method === "POST").length, 2);
    assert.equal(local(state).length, 2); assert.notEqual(local(state)[0].key, local(state)[1].key);
    assert.ok(visible(state.document.getElementById("native-scope-panel")).includes(locale === "en" ? "Decision record saved" : locale === "zh-Hans" ? "决定记录已保存" : "決定紀錄已儲存"));
    console.log("PASS native/scope revision interleave and explicit retry only: " + locale);
  }
  const recovered = await mount("en", "lost-response"); await submitScope(recovered);
  assert.equal(saveButton(recovered).disabled, false);
  assert.equal(recovered.calls.filter(c => c.method === "POST").length, 1);
  assert.equal(local(recovered).length, 1);
  console.log("PASS lost response recovers exact durable rejection through GET with retained intent");
  for (const mode of ["no-receipt", "wrong-body", "wrong-hash", "wrong-revision", "wrong-target", "missing-body", "authorized"]) {
    const state = await mount("en", mode); await submitScope(state);
    assert.equal(saveButton(state).disabled, true, mode);
    assert.ok(!visible(state.document.getElementById("native-scope-panel")).includes("was not applied"), mode);
    assert.equal(state.calls.filter(c => c.method === "POST").length, 1);
    assert.equal(local(state).length, 1);
    console.log("PASS incomplete/tampered receipt remains unknown without automatic retry: " + mode);
  }
  const legacy = await mount("en", "legacy");
  assert.equal(saveButton(legacy).disabled, true);
  assert.equal(legacy.calls.filter(c => c.method === "POST").length, 0);
  assert.equal(local(legacy).length, 1);
  assert.ok(!visible(legacy.document.getElementById("native-scope-panel")).includes("was not applied"));
  console.log("PASS legacy unknown without full body/hash stays held");
  console.log("PASS 12 scope stale DOM tests; no browser/native/model");
})().catch(error => {console.error(error); process.exitCode = 1;});
