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
const response = value => ({ok: true, json: async () => copy(value)});
const actionResult = body => ({action_ref: "5".repeat(64), action_sha256: "6".repeat(64), kind: "message",
  client_key: body.key, target_ref: body.offer_ref, status: "dispatched", replayed: false, failure: null});
const deferred = () => {let resolve; const promise = new Promise(done => {resolve = done;}); return {promise, resolve};};
const knownUnsent = (body, binding = fixture) => ({schema_version: "NativeKnownUnsent.v1", status: "known-unsent",
  operation: "message", project_ref: binding.project_ref, index_sha256: binding.index_sha256,
  input_version: binding.input_version, client_key: body.key, offer_ref: body.offer_ref, offer_sha256: body.offer_sha256});
const rejected = receipt => ({ok: false, status: 400, json: async () => ({error: "synthetic-rejection", ...(receipt ? {receipt} : {})})});
let keys = 0;
async function mount({view = copy(fixture), storage = new Map(), failMessage = false, enabled = true,
  locale = "en", maxTextBytes = 16384, hooks = {}, atlas = true, server = {view, offered: false}} = {}) {
  const html = new Element("html"); html.lang = locale;
  const body = new Element("body"); html.append(body);
  const host = new Element("section"); host.id = "host-panel"; body.append(host);
  const calls = [], observers = [];
  const document = {documentElement: html, body,
    createElement: tag => new Element(tag), querySelector: () => null,
    getElementById: id => flatten(html).find(e => e.id === id)};
  const window = atlas ? {WORKSPACE_NATIVE_ATLAS: {enabled, credential: "fixture-memory-only-secret", current_case: "fixture-case",
    project_ref: fixture.project_ref, index_sha256: fixture.index_sha256, input_version: fixture.input_version}} : {};
  const context = vm.createContext({window, document, TextEncoder,
    sessionStorage: {getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, String(value))},
    crypto: {randomUUID: () => `12345678-1234-1234-1234-${String(++keys).padStart(12, "0")}`},
    MutationObserver: class {constructor(callback) {observers.push(callback);} observe() {}},
    fetch: async (url, options) => {
      calls.push({url, ...options});
      if (options.method === "POST") {
        const body = JSON.parse(options.body);
        if (hooks.post) return hooks.post(body, server);
        if (failMessage) throw Error("synthetic-response-loss");
        return response(actionResult(body));
      }
      if (url.endsWith("/offer")) {
        // The real API saves the first offer and advances SQLite revision.
        if (!server.offered) {server.view.revision++; server.offered = true;}
        const offered = {offer_ref: "1".repeat(64), offer_sha256: "2".repeat(64),
          revision: server.view.revision, max_text_bytes: maxTextBytes};
        return response(hooks.offer ? await hooks.offer(offered, server) : offered);
      }
      return response(hooks.view ? await hooks.view(copy(server.view), server) : server.view);
    },
  });
  for (const script of ["session-panel.js", "native-atlas-chat.js"]) vm.runInContext(fs.readFileSync(path.join(assets, script), "utf8"), context, {filename: script});
  await tick(); await tick();
  const refresh = async next => {if (next) server.view = copy(next); const button = flatten(html).find(e => e.dataset.nativeLabel === "refresh"); await button.onclick(); await tick();};
  const connect = async () => {
    const inputs = flatten(html).filter(e => e.tagName === "INPUT");
    inputs[0].value = server.view.project_ref; inputs[1].value = "fixture-memory-only-secret";
    await inputs[0].parent.parent.onsubmit({preventDefault() {}}); await tick();
  };
  if (!atlas) await connect();
  return {html, document, calls, storage, refresh, connect, observers, context, server};
}
const transcript = state => state.document.getElementById("native-chat-transcript");
const articles = state => transcript(state).children.filter(e => e.tagName === "ARTICLE");
const prepare = state => state.document.getElementById("native-chat-prepare").onclick();
const send = async (state, value = "Explicit message") => {
  const field = state.document.getElementById("native-chat-text"); field.value = value;
  await field.parent.onsubmit({preventDefault() {}});
};
const posts = state => state.calls.filter(call => call.method === "POST");
const intents = state => [...state.storage.entries()].filter(([key]) => key.startsWith("native-message-intents:"));
let assertions = 0;
async function test(name, callback) {
  if (process.argv[3] && !name.includes(process.argv[3])) return;
  await callback(); assertions++; console.log("PASS " + name);
}
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
  await test("first Prepare rereads the same binding after durable offer revision advances", async () => {
    const state = await mount();
    await prepare(state);
    assert.equal(state.server.view.revision, fixture.revision + 1);
    assert.equal(state.document.getElementById("native-chat-send").disabled, false);
    assert.equal(state.calls.length, 3);
    assert.ok(state.calls.every(call => call.method === "GET"));
    assert.equal(state.calls[1].url.endsWith("/offer"), true);
    assert.equal(state.calls[0].url, state.calls[2].url);
    await send(state);
    assert.equal(posts(state).length, 1);
    assert.equal(JSON.parse(posts(state)[0].body).revision, fixture.revision + 1);
    assert.equal(state.document.getElementById("native-chat-text").value, "");
  });
  await test("validated offer limit counts UTF-8 bytes and rejects malformed limits", async () => {
    const state = await mount({maxTextBytes: 6}); await prepare(state);
    await send(state, "字字x"); assert.equal(posts(state).length, 0); assert.equal(intents(state).length, 0);
    await send(state, "字字"); assert.equal(posts(state).length, 1);
    for (const limit of [undefined, 0, 16385, 1.5, "6"]) {
      const bad = await mount({hooks: {offer: value => {value.max_text_bytes = limit; return value;}}});
      await prepare(bad);
      assert.equal(bad.document.getElementById("native-chat-send").disabled, true);
      await send(bad); assert.equal(posts(bad).length, 0);
    }
  });
  await test("stale offers and changed reread source or transcript cannot enable Send", async () => {
    for (const delta of [-1, 1]) {
      const state = await mount({hooks: {offer: value => ({...value, revision: value.revision + delta})}});
      await prepare(state); await send(state); assert.equal(posts(state).length, 0);
      assert.equal(state.document.getElementById("native-chat-send").disabled, true);
    }
    for (const change of [value => {value.project_ref = "project-b";}, value => {value.index_sha256 = "b".repeat(64);},
      value => {value.input_version = "b".repeat(64);}, value => {value.transcript.schema_version = "2.0.0";}]) {
      const state = await mount({hooks: {view: (value, server) => {if (server.offered) change(value); return value;}}});
      await prepare(state); await send(state); assert.equal(posts(state).length, 0);
      assert.equal(state.document.getElementById("native-chat-send").disabled, true);
    }
  });
  await test("duplicate clicks and two tabs never duplicate an admitted send", async () => {
    const gate = deferred(), state = await mount({hooks: {post: () => gate.promise}});
    await prepare(state); const sending = send(state);
    await tick(); await send(state); await prepare(state); await state.refresh();
    assert.equal(posts(state).length, 1);
    gate.resolve(response({status: "dispatched"})); await sending;
    const server = {view: copy(fixture), offered: false}; let writes = 0;
    const hooks = {post: (body, current) => {
      if (body.revision !== current.view.revision) return rejected(knownUnsent(body, current.view));
      writes++; current.view.revision++;
      current.view.actions.push({client_key: body.key, target_ref: body.offer_ref, kind: "message", status: "dispatched"});
      return response({status: "dispatched"});
    }};
    const first = await mount({server, hooks}), second = await mount({server, hooks});
    await prepare(first); await prepare(second); await send(first); await send(second);
    assert.equal(writes, 1); assert.equal(posts(first).length + posts(second).length, 2);
    assert.equal(intents(first).map(([, value]) => JSON.parse(value)).flat().length, 1);
    assert.equal(intents(second).map(([, value]) => JSON.parse(value)).flat().length, 0);
    await first.refresh(); await second.refresh(); assert.equal(writes, 1);
  });
  await test("matching typed known-unsent receipt clears only its own intent and permits explicit retry", async () => {
    const prior = {key: "88888888-8888-8888-8888-888888888888", target: "3".repeat(64), offer_sha256: "4".repeat(64)};
    const value = copy(fixture); value.actions.push({client_key: prior.key, kind: "message", target_ref: prior.target, status: "completed"});
    const ledger = `native-message-intents:${value.project_ref}:${value.index_sha256}:${value.input_version}`;
    const storage = new Map([[ledger, JSON.stringify([prior])]]);
    const hooks = {post: body => rejected(knownUnsent(body))};
    const state = await mount({storage, server: {view: value, offered: true}, hooks});
    await prepare(state); await send(state, "Keep this draft");
    assert.deepEqual(JSON.parse(storage.get(ledger)), [prior]);
    assert.equal(state.document.getElementById("native-chat-text").value, "Keep this draft");
    assert.equal(state.document.getElementById("native-chat-prepare").disabled, false);
    assert.equal(state.document.getElementById("native-chat-send").disabled, true);
    assert.equal(posts(state).length, 1);
    const firstKey = JSON.parse(posts(state)[0].body).key;
    hooks.post = () => response({status: "dispatched"}); await prepare(state); await send(state);
    assert.equal(posts(state).length, 2); assert.notEqual(JSON.parse(posts(state)[1].body).key, firstKey);
  });
  await test("HTTP 400 and absent malformed or mismatched receipts retain the original key", async () => {
    const changes = [() => null, value => "known-unsent", value => ({...value, extra: true}),
      value => {delete value.operation; return value;}, ...["schema_version", "status", "operation", "project_ref",
        "index_sha256", "input_version", "client_key", "offer_ref", "offer_sha256"].map(field => value => ({...value, [field]: "wrong"}))];
    for (const change of changes) {
      const state = await mount({hooks: {post: body => rejected(change(knownUnsent(body)))}});
      await prepare(state); await send(state); const saved = copy(intents(state));
      assert.equal(JSON.parse(saved[0][1]).length, 1);
      await state.refresh(); await prepare(state); await send(state);
      assert.deepEqual(intents(state), saved); assert.equal(posts(state).length, 1);
      assert.equal(state.document.getElementById("native-chat-prepare").disabled, true);
    }
  });
  await test("timeout lost or malformed responses and failed followup reads preserve uncertainty", async () => {
    const outcomes = [() => {throw Error("synthetic-timeout");}, () => ({ok: true, json: async () => {throw Error("synthetic-lost-body");}}),
      () => response(null), () => response({client_key: "wrong", status: "completed"})];
    for (const post of outcomes) {
      const state = await mount({hooks: {post}}); await prepare(state); await send(state);
      assert.equal(state.document.getElementById("native-chat-text").value, "Explicit message");
      const saved = copy(intents(state)); await state.refresh(); await send(state);
      assert.deepEqual(intents(state), saved); assert.equal(posts(state).length, 1);
      const reloaded = await mount({storage: state.storage});
      assert.equal(reloaded.document.getElementById("native-chat-send").disabled, true);
      assert.ok(reloaded.calls.every(call => call.method === "GET"));
    }
    for (const change of [action => {action.kind = "answer";}, action => {action.target_ref = "f".repeat(64);},
      action => {action.client_key = "wrong";}]) {
      let sent;
      const state = await mount({hooks: {post: body => {sent = body; return response({status: "completed", client_key: "wrong"});},
        view: value => {
          if (sent) {const action = {client_key: sent.key, target_ref: sent.offer_ref, kind: "message", status: "completed"};
            change(action); value.actions.push(action);}
          return value;
        }}});
      await prepare(state); await send(state); const saved = copy(intents(state));
      assert.equal(state.document.getElementById("native-chat-prepare").disabled, true);
      await state.refresh(); await send(state); assert.deepEqual(intents(state), saved); assert.equal(posts(state).length, 1);
    }
    let posted = false;
    const state = await mount({hooks: {post: body => {posted = true; return rejected(knownUnsent(body));},
      view: value => {if (posted) throw Error("synthetic-followup-read-loss"); return value;}}});
    await prepare(state); await send(state);
    assert.equal(JSON.parse(intents(state)[0][1]).length, 0);
    assert.equal(posts(state).length, 1);
  });
  await test("prepare and rejection races across project switch or reconnect fail closed", async () => {
    const ready = await mount({atlas: false}); await prepare(ready);
    assert.equal(ready.document.getElementById("native-chat-send").disabled, false);
    await ready.connect(); await send(ready);
    assert.equal(ready.document.getElementById("native-chat-send").disabled, true);
    assert.equal(posts(ready).length, 0);
    for (const switchProject of [false, true]) {
      const gate = deferred(), state = await mount({atlas: false, hooks: {offer: value => gate.promise.then(() => value)}});
      const preparing = prepare(state); await tick();
      if (switchProject) state.server.view.project_ref = "project-b";
      await state.connect(); gate.resolve(); await preparing;
      await send(state); assert.equal(posts(state).length, 0);
      assert.equal(state.document.getElementById("native-chat-send").disabled, true);
    }
    const rereadGate = deferred(); let blockedReread = false;
    const prepared = await mount({atlas: false, hooks: {view: (value, server) => {
      if (server.offered && !blockedReread) {blockedReread = true; return rereadGate.promise.then(() => value);} return value;
    }}});
    const preparing = prepare(prepared); await tick();
    await prepared.connect(); rereadGate.resolve(); await preparing;
    await send(prepared); assert.equal(posts(prepared).length, 0);
    assert.equal(prepared.document.getElementById("native-chat-send").disabled, true);
    const gate = deferred(); let posted = false, heldRead = false;
    const state = await mount({atlas: false, hooks: {
      post: body => {posted = true; return rejected(knownUnsent(body));},
      view: value => {if (posted && !heldRead) {heldRead = true; return gate.promise.then(() => value);} return value;},
    }});
    await prepare(state); const sending = send(state); await tick();
    const saved = copy(intents(state)); await state.connect(); gate.resolve(); await sending;
    assert.deepEqual(intents(state), saved); assert.equal(posts(state).length, 1);
    assert.equal(state.document.getElementById("native-chat-prepare").disabled, true);
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
