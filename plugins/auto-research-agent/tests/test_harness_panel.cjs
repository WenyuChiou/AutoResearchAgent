/* Synthetic DOM/HTTP boundary tests; this does not claim real-browser or model execution. */
"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path"), vm = require("node:vm"), crypto = require("node:crypto");
const source = fs.readFileSync(process.argv[2] || path.join(__dirname, "../cli/research_workspace_native/web/harness-panel.js"), "utf8"), h = "1".repeat(64), c = "2".repeat(64), secret = "synthetic-memory-only-secret";
const flatten = node => [node, ...node.children.flatMap(flatten)];
class Element {
  constructor(tag) {this.tagName = tag.toUpperCase(); this.children = []; this.dataset = {}; this.attrs = {}; this._text = "";}
  get textContent() {return this._text + this.children.map(child => child.textContent).join("");} set textContent(value) {this._text = String(value); this.replaceChildren();}
  get nextSibling() {return this.parentNode?.children[this.parentNode.children.indexOf(this) + 1] || null;}
  append(...nodes) {for (const node of nodes) {node.remove(); node.parentNode = this; this.children.push(node);}}
  remove() {if (this.parentNode) this.parentNode.children = this.parentNode.children.filter(child => child !== this); this.parentNode = null;}
  replaceChildren(...nodes) {for (const child of this.children) child.parentNode = null; this.children = []; this.append(...nodes);}
  insertBefore(node, next) {node.remove(); node.parentNode = this; this.children.splice(this.children.indexOf(next), 0, node); this.insertions = (this.insertions || 0) + 1;}
  setAttribute(name, value) {this.attrs[name] = value;} click() {this.clicked = true;}
  set innerHTML(_) {throw Error("unsafe-HTML");}
}
const response = value => ({ok: true, json: async () => JSON.parse(JSON.stringify(value))});
const tick = () => new Promise(resolve => setImmediate(resolve));
const hashRequest = (body, projectRef = "case-one") => crypto.createHash("sha256").update(JSON.stringify(Object.fromEntries(Object.entries({...body, project_ref: projectRef}).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0)))).digest("hex");
const baseView = () => ({project_ref: "case-one", project_id: "project-one", index_sha256: h, input_canonical_sha256: c, revision: 1, capabilities: ["validate-index", "derive-literature-selection", "export-selection"], operation_scope: "offline-saved-input", research_execution: false, model_execution: false, scientific_admission: false, history: [], history_count: 0, history_limit: 64, action_limit: 128});
async function mount({enabled = true, storage = new Map(), server = {view: baseView()}, mode = "normal", transform = value => value, storageError = false} = {}) {
  const html = new Element("html"), body = new Element("body"), content = new Element("main"), review = new Element("section"); html.lang = "en"; html.append(body); body.append(content); content.id = "atlas-content"; review.id = "atlas-stage-review"; content.append(review);
  const document = {documentElement: html, body, createElement: tag => new Element(tag), getElementById: id => flatten(html).find(node => node.id === id)};
  let nextKey = 0;
  const calls = [], observers = [], urls = [], window = {WORKSPACE_HARNESS: {enabled, project_ref: server.view.project_ref, index_sha256: server.view.index_sha256}, WORKSPACE_HOST: {credential: secret}, WORKSPACE_VIEW: {index: {project_id: server.view.project_id}}, addEventListener() {}};
  const context = vm.createContext({document, window, location: {origin: "http://127.0.0.1:1"}, MutationObserver: class {constructor(callback) {observers.push(callback);} observe() {}}, sessionStorage: {getItem: key => storage.get(key) ?? null, setItem: (key, value) => {if (storageError) throw Error("synthetic-storage-error"); storage.set(key, value);}, removeItem: key => storage.delete(key)}, crypto: {...crypto.webcrypto, subtle: crypto.webcrypto.subtle, randomUUID: () => "11111111-1111-1111-1111-" + String(++nextKey).padStart(12, "0")}, TextEncoder, Blob, URL: {createObjectURL: () => {urls.push("created"); return "blob:synthetic";}, revokeObjectURL: () => urls.push("revoked")}, setTimeout: callback => callback(),
    fetch: async (url, options) => {
      calls.push({url, ...options}); assert.equal(options.headers.Authorization, "Bearer " + secret); assert.equal(url.includes(secret), false);
      if (options.method === "POST") {
        assert.ok(storage.size, "intent must exist before I/O"); const request = JSON.parse(options.body), revision = server.view.revision;
        if (mode === "unrecorded") return {ok: false, json: async () => ({error: "stale-revision"})};
        if (mode === "stale" || mode === "stale-loss") {
          const observed = revision + 1;
          const row = {key: request.key, project_ref: "case-one", method: "harness-ops/" + request.action, action: request.action, status: "rejected-known-unsent", request, request_sha256: hashRequest(request), index_sha256: h, input_canonical_sha256: c, contract_version: "1.0.0", output_ref: "a".repeat(32), artifacts: [], intent_revision: observed + 1, completion_revision: observed + 1, research_execution: false, model_execution: false, scientific_admission: false, outcome: "rejected-known-unsent", error: {code: "stale-revision", type: "HarnessOpsError"}, rejection: {type: "known-unsent", phase: "before-admission", offer_revision: request.expected_revision, observed_revision: observed}};
          server.view.revision = observed + 1; server.view.history.push(row); server.view.history_count++;
          if (mode === "stale-loss") throw Error("synthetic-refusal-response-loss");
          return {ok: false, json: async () => ({error: "stale-revision", receipt: transform(row)})};
        }
        const result = {validation: "passed", papers: 15, input_canonical_sha256: c, research_execution: false, scientific_admission: false, official_stage2_import_eligible: false};
        const raw = Buffer.from("synthetic result"), artifact = {name: "operation.json", size: raw.length, sha256: crypto.createHash("sha256").update(raw).digest("hex")}; server.raw = raw;
        const row = {key: request.key, project_ref: "case-one", method: "harness-ops/" + request.action, action: request.action, status: mode === "unknown" ? "execution-unknown" : "completed", request, request_sha256: hashRequest(request), index_sha256: h, input_canonical_sha256: c, contract_version: "1.0.0", output_ref: "a".repeat(32), artifacts: mode === "unknown" ? [] : [artifact], intent_revision: revision + 1, research_execution: false, model_execution: false, scientific_admission: false};
        if (mode !== "unknown") Object.assign(row, {outcome: "succeeded", completion_revision: revision + 2, result});
        server.view.revision += mode === "unknown" ? 1 : 2; server.view.history.push(row); server.view.history_count++; if (mode === "loss") throw Error("synthetic-response-loss"); return response(transform(row));
      }
      if (url.includes("/artifacts/")) return {ok: true, arrayBuffer: async () => Uint8Array.from(server.raw).buffer};
      if (url.includes("/actions/")) return server.view.history.length ? response(transform(server.view.history.at(-1))) : {ok: false, json: async () => ({error: "action-not-found"})};
      return response(transform(server.view));
    }});
  vm.runInContext(source, context); for (let i = 0; i < 10; i++) await tick();
  const nodes = () => flatten(html), action = () => nodes().find(node => node.dataset.harnessAction === "validate-index"), refresh = () => nodes().find(node => node.id === "harness-history-refresh");
  const submit = async () => {await action().onclick(); for (let i = 0; i < 10; i++) await tick();};
  return {html, content, review, document, window, storage, server, calls, observers, urls, nodes, action, refresh, submit};
}
(async () => {
  const disabled = await mount({enabled: false}); assert.equal(disabled.calls.length, 0); assert.equal(disabled.action().disabled, true);
  const valid = await mount(); assert.equal(valid.calls.length, 1); assert.equal(valid.window.WORKSPACE_HARNESS, undefined); assert.equal(valid.action().disabled, false);
  assert.equal(valid.nodes().find(node => node.id === "atlas-harness-tools").nextSibling, valid.review);
  const insertions = valid.content.insertions; valid.observers.forEach(callback => callback()); assert.equal(valid.content.insertions, insertions, "observer must not trigger a mount loop");
  await valid.submit(); assert.equal(valid.calls.filter(call => call.method === "POST").length, 1); assert.equal(valid.storage.size, 0); assert.equal(valid.action().disabled, false);
  await valid.nodes().find(node => node.dataset.artifact === "operation.json").onclick(); assert.deepEqual(valid.urls, ["created", "revoked"]);
  const retained = new Map(), unknown = await mount({mode: "unknown", storage: retained}); await unknown.submit(); assert.equal(unknown.action().disabled, true); assert.equal(retained.size, 1); assert.equal([...retained.values()][0].includes(secret), false);
  const reload = await mount({mode: "unknown", storage: retained, server: unknown.server}); assert.equal(reload.calls.filter(call => call.method === "POST").length, 0); await reload.refresh().onclick(); assert.equal(reload.calls.filter(call => call.method === "POST").length, 0); assert.equal(reload.action().disabled, true);
  const loss = await mount({mode: "loss"}); await loss.submit(); assert.equal(loss.calls.filter(call => call.method === "POST").length, 1); assert.equal(loss.storage.size, 0); assert.equal(loss.nodes().find(node => node.attrs.role === "status").dataset.state, "succeeded");
  for (const mode of ["stale", "stale-loss"]) {
    const refused = await mount({mode}); await refused.submit();
    assert.equal(refused.calls.filter(call => call.method === "POST").length, 1);
    assert.equal(refused.storage.size, 0); assert.equal(refused.action().disabled, false);
    assert.equal(refused.nodes().find(node => node.attrs.role === "status").dataset.state, "rejected-known-unsent");
    assert.equal(refused.server.view.history[0].artifacts.length, 0);
    await refused.refresh().onclick();
    assert.equal(refused.calls.filter(call => call.method === "POST").length, 1, "GET proof must not auto-resubmit");
    await refused.submit();
    const posted = refused.calls.filter(call => call.method === "POST").map(call => JSON.parse(call.body));
    assert.equal(posted.length, 2, "only a new explicit action may POST");
    assert.notEqual(posted[0].key, posted[1].key); assert.ok(posted[1].expected_revision > posted[0].expected_revision);
  }
  const unrecorded = await mount({mode: "unrecorded"}); await unrecorded.submit();
  assert.equal(unrecorded.storage.size, 1); assert.equal(unrecorded.action().disabled, true);
  assert.equal(unrecorded.nodes().find(node => node.attrs.role === "status").dataset.state, "execution-unknown");
  const unrecordedReload = await mount({mode: "unrecorded", storage: unrecorded.storage, server: unrecorded.server});
  await unrecordedReload.refresh().onclick();
  assert.equal(unrecordedReload.calls.filter(call => call.method === "POST").length, 0);
  assert.equal(unrecordedReload.storage.size, 1); assert.equal(unrecordedReload.action().disabled, true);
  for (const alter of [row => {delete row.rejection;}, row => {row.rejection.phase = "after-admission";}, row => {row.rejection.offer_revision++;}, row => {row.request_sha256 = "f".repeat(64);}, row => {row.request.key = "wrong-key";}, row => {row.project_ref = "other-project";}, row => {row.input_canonical_sha256 = "f".repeat(64);}, row => {row.artifacts.push({name: "operation.json", size: 1, sha256: h});}]) {
    const tampered = await mount({mode: "stale", transform: value => {const copy = JSON.parse(JSON.stringify(value)); if (copy.status === "rejected-known-unsent") alter(copy); else copy.history?.filter(row => row.status === "rejected-known-unsent").forEach(alter); return copy;}});
    await tampered.submit(); assert.equal(tampered.storage.size, 1); assert.equal(tampered.action().disabled, true);
    assert.equal(tampered.calls.filter(call => call.method === "POST").length, 1);
  }
  const corrupt = await mount({transform: value => ({...value, index_sha256: "3".repeat(64)})}); assert.equal(corrupt.action().disabled, true); assert.equal(corrupt.calls.filter(call => call.method === "POST").length, 0);
  const badStorage = new Map([["atlas-harness-intent:case-one:" + h, "bad JSON"]]), blocked = await mount({storage: badStorage}); assert.equal(blocked.action().disabled, true); assert.equal(blocked.nodes().find(node => node.attrs.role === "status").dataset.state, "unavailable");
  const unavailableStorage = await mount({storageError: true}); await unavailableStorage.submit(); assert.equal(unavailableStorage.calls.filter(call => call.method === "POST").length, 0); assert.equal(unavailableStorage.nodes().find(node => node.attrs.role === "status").dataset.state, "storage");
  const corruptArtifact = await mount(); await corruptArtifact.submit(); corruptArtifact.server.raw = Buffer.from("tampered"); await corruptArtifact.nodes().find(node => node.dataset.artifact === "operation.json").onclick(); assert.deepEqual(corruptArtifact.urls, []); assert.equal(corruptArtifact.nodes().find(node => node.attrs.role === "status").dataset.state, "unavailable");
  const oldPanel = valid.nodes().find(node => node.id === "atlas-harness-tools"), newReview = new Element("section"); newReview.id = "atlas-stage-review"; valid.content.replaceChildren(newReview); valid.html.lang = "zh-Hant"; valid.observers.forEach(callback => callback()); assert.equal(oldPanel.nextSibling, newReview); assert.equal(valid.action().textContent, "校驗交付");
  if (process.argv[3]) {
    const fixture = JSON.parse(fs.readFileSync(process.argv[3], "utf8")), storage = new Map();
    if (fixture.pending) storage.set("atlas-harness-intent:" + fixture.final.project_ref + ":" + fixture.final.index_sha256, JSON.stringify(fixture.pending));
    const actual = await mount({server: {view: fixture.final}, storage});
    assert.equal(actual.action().disabled, false); assert.equal(actual.nodes().filter(node => node.className === "harness-record").length, fixture.expected_records ?? 3);
    assert.equal(actual.calls.filter(call => call.method === "POST").length, 0); assert.notEqual(fixture.final.index_sha256, fixture.final.input_canonical_sha256);
    if (fixture.pending) {assert.equal(storage.size, 0); assert.equal(actual.nodes().find(node => node.attrs.role === "status").dataset.state, "rejected-known-unsent");}
    console.log("actual offline Harness producer/refusal receipts accepted; synthetic DOM; no browser/native/model claim");
  }
  console.log("harness panel synthetic DOM/HTTP recovery, identity, no-resend, artifact hash and remount tests PASS");
})().catch(error => {console.error(error); process.exitCode = 1;});
