/* Actual NativePanel plus chat against the frozen real-SQLite API-view fixture.
   This small DOM substitute does not claim installed-browser/native acceptance. */
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const crypto = require("node:crypto");
const base = __dirname;
const assets = process.argv[2] ? path.resolve(process.argv[2]) : path.join(base, "../cli/research_workspace_native/web");
const fixturePath = path.join(base, "fixtures/native-atlas-pipeline-view-v1.json");
const fixtureBytes = fs.readFileSync(fixturePath);
assert.equal(crypto.createHash("sha256").update(fixtureBytes).digest("hex"),
  "8ef73d951c1e40f2dc9acb5740562577bcbf7c8c5b5f7c6b1055e78a54681a9a");
const fixture = JSON.parse(fixtureBytes);
const copy = value => JSON.parse(JSON.stringify(value));
class Element {
  constructor(tag) {this.tagName = tag.toUpperCase(); this.children = []; this.dataset = {}; this.attrs = {}; this.value = ""; this.disabled = false; this._text = "";}
  get textContent() {return this._text + this.children.map(e => e.textContent).join("");}
  set textContent(value) {this._text = String(value); this.replaceChildren();}
  get childElementCount() {return this.children.length;}
  get isConnected() {return this.tagName === "HTML" || Boolean(this.parent?.isConnected);}
  append(...items) {for (const item of items) {item.remove(); item.parent = this; this.children.push(item);}}
  prepend(item) {item.remove(); item.parent = this; this.children.unshift(item);}
  remove() {if (this.parent) {this.parent.children = this.parent.children.filter(e => e !== this); this.parent = null;}}
  replaceChildren(...items) {for (const child of this.children) child.parent = null; this.children = []; this.append(...items);}
  setAttribute(name, value) {this.attrs[name] = String(value);}
  querySelectorAll(selector) {assert.equal(selector, "[data-native-label]"); return flatten(this).filter(e => e.dataset.nativeLabel);}
  set innerHTML(_) {throw Error("HTML interpolation must never occur");}
}
const flatten = element => [element, ...element.children.flatMap(flatten)];
const tick = () => new Promise(resolve => setImmediate(resolve));
async function mount({view = copy(fixture), storage = new Map(), failMessage = false, enabled = true, locale = "en"} = {}) {
  const html = new Element("html"); html.lang = locale;
  const body = new Element("body"); html.append(body);
  const host = new Element("section"); host.id = "host-panel"; body.append(host);
  const calls = [], observers = [];
  const document = {documentElement: html, body,
    createElement: tag => new Element(tag), querySelector: () => null,
    getElementById: id => flatten(html).find(e => e.id === id)};
  const window = {WORKSPACE_NATIVE_ATLAS: {enabled, credential: "fixture-memory-only-secret", current_case: "fixture-case",
    project_ref: fixture.project_ref, index_sha256: fixture.index_sha256, input_version: fixture.input_version}};
  const context = vm.createContext({window, document, TextEncoder,
    sessionStorage: {getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, String(value))},
    crypto: {randomUUID: () => "12345678-1234-1234-1234-123456789abc"},
    MutationObserver: class {constructor(callback) {observers.push(callback);} observe() {}},
    fetch: async (url, options) => {
      calls.push({url, ...options});
      if (options.method === "POST") {if (failMessage) throw Error("synthetic-response-loss"); return {ok: true, json: async () => ({status: "dispatched"})};}
      return {ok: true, json: async () => url.endsWith("/offer") ?
        {offer_ref: "1".repeat(64), offer_sha256: "2".repeat(64), revision: view.revision} : copy(view)};
    },
  });
  for (const script of ["session-panel.js", "native-atlas-chat.js"]) vm.runInContext(fs.readFileSync(path.join(assets, script), "utf8"), context, {filename: script});
  await tick(); await tick();
  const refresh = async next => {if (next) view = copy(next); const button = flatten(html).find(e => e.dataset.nativeLabel === "refresh"); await button.onclick(); await tick();};
  return {html, document, calls, storage, refresh, observers, context};
}
const transcript = state => state.document.getElementById("native-chat-transcript");
const articles = state => transcript(state).children.filter(e => e.tagName === "ARTICLE");
let assertions = 0;
async function test(name, callback) {await callback(); assertions++; console.log("PASS " + name);}
(async () => {
  await test("actual typed API fixture, literal source text and failed terminal", async () => {
    const state = await mount();
    assert.equal(articles(state).length, 4);
    assert.ok(transcript(state).textContent.includes("Literal <img> 简體 saved model-text fixture."));
    assert.ok(articles(state).some(e => e.dataset.role === "system" && e.textContent.includes("turn-terminal · failed")));
    assert.ok(articles(state).some(e => e.dataset.role === "tool" && e.textContent.includes("native-tool-failed")));
    assert.equal(flatten(state.html).filter(e => e.tagName === "IMG").length, 0);
    assert.equal(state.storage.size, 0);
    assert.equal(state.calls.length, 1); assert.equal(state.calls[0].method, "GET");
    assert.ok(!state.calls[0].url.includes("secret"));
  });
  await test("explicit refresh is GET only and keeps source text", async () => {
    const state = await mount();
    await state.refresh(); await state.refresh();
    assert.equal(state.calls.length, 3); assert.ok(state.calls.every(call => call.method === "GET"));
    assert.equal(articles(state).length, 4);
  });
  await test("unknown version and changed transcript fields fail closed", async () => {
    const variants = [
      value => {value.transcript.schema_version = "2.0.0";},
      value => {value.transcript = null;},
      value => {value.transcript.extra = true;},
      value => {value.transcript.entries[1].private_root = "bad";},
      value => {value.transcript.entries[1].role = "developer";},
      value => {value.transcript.entries[1].kind = "raw-rpc";},
      value => {value.transcript.entries[1].status = "research-approved";},
    ];
    for (const change of variants) {
      const value = copy(fixture); change(value); const state = await mount({view: value});
      assert.equal(articles(state).length, 0);
      assert.equal(state.document.getElementById("native-chat-prepare").disabled, true);
      assert.ok(transcript(state).textContent.includes("unavailable"));
      await state.document.getElementById("native-chat-prepare").onclick();
      assert.equal(state.calls.length, 1);
    }
  });
  await test("typed frame refs require exact fields, positive safe sequence and hash", async () => {
    const variants = ["a".repeat(64), {frame_sequence: 0, raw_sha256: "a".repeat(64)},
      {frame_sequence: 2 ** 53, raw_sha256: "a".repeat(64)}, {frame_sequence: 1, raw_sha256: "bad"},
      {frame_sequence: 1, raw_sha256: "a".repeat(64), extra: true}];
    for (const ref of variants) {
      const value = copy(fixture); value.transcript.entries[1].frame_refs = [ref];
      assert.equal(articles(await mount({view: value})).length, 0);
    }
  });
  await test("strict declared window and text bounds", async () => {
    const variants = [
      value => {value.transcript.window.event_limit = 129;},
      value => {value.transcript.window.entry_limit = 129;},
      value => {value.transcript.window.text_byte_limit = 65537;},
      value => {value.transcript.window.truncated = 1;},
      value => {value.transcript.window.omitted_frames = -1;},
      value => {value.transcript.window.omitted_frames = 2 ** 53;},
      value => {value.transcript.window.extra = true;},
      value => {value.transcript.entries[1].text = "字".repeat(5462);},
      value => {value.transcript.entries[1].text = "\ud800";},
      value => {value.transcript.entries = Array(129).fill(value.transcript.entries[0]);},
      value => {value.transcript.entries[1].frame_refs = Array(129).fill(value.transcript.entries[1].frame_refs[0]);},
      value => {const entry = copy(value.transcript.entries[1]); entry.text = "x".repeat(16384); value.transcript.entries = Array(5).fill(entry);},
    ];
    for (const change of variants) {
      const value = copy(fixture); change(value);
      assert.equal(articles(await mount({view: value})).length, 0);
    }
  });
  await test("legacy absent transcript means no observed reply, not completed", async () => {
    const value = copy(fixture); delete value.transcript;
    const state = await mount({view: value});
    assert.equal(articles(state).length, 0); assert.ok(transcript(state).textContent.includes("No saved model reply"));
    assert.equal(state.document.getElementById("native-chat-prepare").disabled, false);
  });
  await test("three languages preserve literal source text", async () => {
    for (const locale of ["en", "zh-Hans", "zh-Hant"]) {
      const state = await mount({locale});
      assert.ok(transcript(state).textContent.includes("Literal <img> 简體 saved model-text fixture."));
      assert.equal(articles(state).length, 4);
    }
  });
  await test("response loss stores only opaque intent; refresh and reconnect never POST", async () => {
    const storage = new Map(); const state = await mount({storage, failMessage: true});
    await state.document.getElementById("native-chat-prepare").onclick();
    const text = state.document.getElementById("native-chat-text"); text.value = "private draft secret text";
    await text.parent.onsubmit({preventDefault() {}});
    assert.equal(state.calls.filter(call => call.method === "POST").length, 1);
    const [key, raw] = [...storage.entries()][0];
    assert.ok(key.startsWith("native-message-intents:"));
    assert.deepEqual(Object.keys(JSON.parse(raw)[0]).sort(), ["key", "offer_sha256", "target"]);
    assert.ok(!raw.includes("private draft") && !raw.includes("secret") && !raw.includes("credential"));
    await state.refresh(); assert.equal(state.calls.filter(call => call.method === "POST").length, 1);
    const reloaded = await mount({storage});
    assert.ok(reloaded.calls.every(call => call.method === "GET"));
    assert.equal(reloaded.document.getElementById("native-chat-prepare").disabled, true);
    assert.equal(reloaded.document.getElementById("native-chat-send").disabled, true);
  });
  await test("unbound native capability adds no discussion and sends nothing", async () => {
    const state = await mount({enabled: false});
    assert.equal(state.document.getElementById("native-chat-text"), undefined);
    assert.equal(state.calls.length, 0);
  });
  console.log(`PASS ${assertions} tests; actual fixture plus DOM substitute, no browser/native/model`);
})().catch(error => {console.error(error); process.exitCode = 1;});
