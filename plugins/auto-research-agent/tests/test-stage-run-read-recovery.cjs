/* Actual panel source; synthetic DOM/fetch only, no native/model/browser. */
"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");
const source = fs.readFileSync(process.argv[2] || path.join(__dirname, "../references/research-workspace/web/stage-run-panel.js"), "utf8");
const nodes = n => [n, ...n.children.flatMap(nodes)], tick = () => new Promise(r => setImmediate(r));
class Element {
  constructor(tag) { this.tagName = tag.toUpperCase(); this.children = []; this.handlers = {}; this.dataset = {}; this.attrs = {}; this._text = ""; }
  get textContent() { return this._text + this.children.map(c => c.textContent).join(""); }
  set textContent(value) { this._text = String(value); this.replaceChildren(); }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  setAttribute(name, value) { this.attrs[name] = value; }
  addEventListener(name, fn) { this.handlers[name] = fn; }
  querySelectorAll() { return nodes(this).filter(n => n.tagName === "DETAILS" && n.dataset.jobKey); }
  async click() { if (!this.disabled) await this.handlers.click?.(); }
  set innerHTML(_) { throw Error("unsafe HTML"); }
}
const clone = value => JSON.parse(JSON.stringify(value)), response = value => ({ok: true, json: async () => clone(value)});
const deferred = () => { let resolve; const promise = new Promise(r => resolve = r); return {promise, resolve}; };
async function mount({blockFirst = null, failFirst = false, loseRun = false, nativeOperation = false} = {}) {
  const html = new Element("html"), body = new Element("body"); html.lang = "en"; html.append(body);
  const document = {documentElement: html, body, createElement: t => new Element(t), querySelector: () => null, addEventListener() {}};
  const calls = [], storage = new Map(), timers = [], server = {failNext: false, jobs: [], revision: 1};
  const snapshot = () => ({ready: true, blocked: null, budget: {reserved: server.jobs.length, max_calls: 8, seconds_remaining: 120}, pipeline: {status: "pending", candidates: []}, jobs: clone(server.jobs), deliveries: {}, revision: server.revision, next_task: {phase: "source-review", task_sha256: "a".repeat(64)}});
  const operation = {can_interrupt: true, action_ref: "opaque-action", action_sha256: "b".repeat(64)};
  const nativeView = () => ({revision: 1, index_sha256: "c".repeat(64), input_version: "d".repeat(64), requests: [], operations: nativeOperation ? [operation] : []});
  let readCount = 0, uuid = 0;
  vm.runInNewContext(source, {
    document, window: {WORKSPACE_STAGE_RUN: {credential: "synthetic-memory-only", project_ref: "test"}, addEventListener() {}},
    crypto: {randomUUID: () => "11111111-1111-1111-1111-" + String(++uuid).padStart(12, "0")},
    sessionStorage: {getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value)},
    MutationObserver: class { observe() {} }, setInterval: fn => { timers.push(fn); return 1; }, clearInterval() {},
    fetch: async (url, options) => {
      calls.push({url, method: options.method});
      assert.equal(options.headers.Authorization, "Bearer synthetic-memory-only");
      assert.ok(!url.includes("synthetic-memory-only"));
      if (options.method === "POST") {
        assert.ok(storage.size, "durable non-secret intent must precede POST");
        assert.ok([...storage.values()].every(value => !value.includes("synthetic-memory-only")));
        const request = JSON.parse(options.body);
        if (url.endsWith("/actions")) {
          server.jobs.push({key: request.key, task: {phase: "source-review"}, status: "completed", final_text: "Saved source review"});
          server.revision++;
          if (loseRun) throw Error("response lost after commit");
          return response({status: "completed"});
        }
        assert.ok(url.endsWith("/interrupts"));
        throw Error("native response lost; outcome unknown");
      }
      if (!url.endsWith("/native")) {
        readCount++;
        if (readCount === 1 && blockFirst) await blockFirst.promise;
        if ((readCount === 1 && failFirst) || server.failNext) { server.failNext = false; throw Error("read unavailable"); }
        return response(snapshot());
      }
      return response({native_view: nativeView()});
    }
  });
  const all = () => nodes(html), buttons = () => all().filter(n => n.tagName === "BUTTON");
  const flush = async () => { for (let i = 0; i < 12; i++) await tick(); };
  await flush();
  return {html, server, calls, storage, timers, all, buttons, flush,
    notice: () => all().find(n => n.attrs.role === "status"),
    refresh: () => buttons()[1].click(), postCount: () => calls.filter(c => c.method === "POST").length};
}
(async () => {
  const gate = deferred(), single = await mount({blockFirst: gate});
  assert.equal(single.calls.length, 1);
  await single.refresh(); await single.timers[0]();
  assert.equal(single.calls.length, 1, "overlapping refresh/timer reads must stay single-flight");
  gate.resolve(); await single.flush();
  assert.equal(single.calls.length, 2); assert.equal(single.postCount(), 0);

  const readFailure = await mount({failFirst: true});
  assert.ok(readFailure.notice().textContent.includes("read unavailable"));
  readFailure.server.jobs.push({key: "saved-job", task: {phase: "source-review"}, status: "completed", final_text: "Saved source review"});
  await readFailure.refresh();
  assert.equal(readFailure.notice().textContent, "");
  const history = readFailure.all().find(n => n.tagName === "DETAILS");
  assert.ok(history.textContent.includes("Saved source review")); history.open = true;
  await readFailure.refresh();
  assert.equal(readFailure.all().find(n => n.tagName === "DETAILS").open, true);
  assert.equal(readFailure.postCount(), 0);

  const lostRun = await mount({loseRun: true});
  await lostRun.buttons()[0].click();
  assert.equal(lostRun.postCount(), 1);
  assert.equal(lostRun.notice().textContent, "", "saved job resolves lost response without reposting");
  assert.ok(lostRun.html.textContent.includes("Saved source review"));
  await lostRun.refresh(); await lostRun.timers[0]();
  assert.equal(lostRun.postCount(), 1);

  const nativeUnknown = await mount({nativeOperation: true});
  await nativeUnknown.buttons().find(n => n.textContent === "Stop this model turn").click(); await nativeUnknown.flush();
  assert.equal(nativeUnknown.postCount(), 1);
  assert.ok(nativeUnknown.notice().textContent.includes("Request outcome unknown"));
  nativeUnknown.server.failNext = true; await nativeUnknown.refresh();
  assert.ok(nativeUnknown.notice().textContent.includes("read unavailable"));
  await nativeUnknown.refresh(); await nativeUnknown.timers[0]();
  assert.ok(nativeUnknown.notice().textContent.includes("Request outcome unknown"), "successful GET must not turn native uncertainty into success");
  assert.equal(nativeUnknown.buttons().find(n => n.textContent === "Stop this model turn").disabled, true);
  assert.equal(nativeUnknown.postCount(), 1);
  console.log("Stage run read recovery: GET single-flight, saved history recovery, expanded history, saved run loss reconciliation, native unknown retained and no implicit POST PASS");
})().catch(error => { console.error(error); process.exitCode = 1; });
