/* Deterministic DOM/fetch regression; records are synthetic, no native work. */
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {webcrypto} = require("node:crypto");
class Node {
  constructor(tag) { this.tag = tag; this.children = []; this.events = {}; this.dataset = {}; this.hidden = false; this.disabled = false; this.textContent = ""; }
  append(node) { this.children.push(node); }
  replaceChildren(...nodes) { this.children = nodes; }
  setAttribute() {}
  focus() {}
  addEventListener(name, callback) { this.events[name] = callback; }
  async click() { if (!this.disabled) await this.events.click?.({}); }
}
const descendants = node => [node, ...node.children.flatMap(descendants)];
const digest = async value => Buffer.from(await webcrypto.subtle.digest("SHA-256", new TextEncoder().encode(JSON.stringify(value)))).toString("hex");
(async () => {
  const body = new Node("body"), language = {value: "en", addEventListener() {}};
  const binding = {index_sha256: "a".repeat(64), manifest_sha256: "b".repeat(64), project_id: "synthetic-project"};
  const records = await Promise.all(Array.from({length: 101}, async (_, i) => {
    const key = "key-" + i, message = "Synthetic feedback " + i;
    return {...binding, case_ref: "stage1", created_at: "2026-01-01T00:00:00Z", feedback_ref: await digest(["stage1", key]), key, message,
      record_sha256: await digest({binding, case_ref: "stage1", key, message, stage: 1}), replayed: false, sequence: i + 1, stage: 1, status: "recorded-not-dispatched"};
  }));
  const requests = []; let malformed = true;
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../cli/research_workspace_native/web/atlas-host.js"), "utf8"), {
    window: {WORKSPACE_HOST: {credential: "local-test-token", current_case: "stage1", cases: [{ref: "stage1", ...binding, url: "/cases/stage1/atlas.html"}], maintenance_enabled: true}},
    document: {body, createElement: tag => new Node(tag), getElementById: () => language, documentElement: {dataset: {}}},
    location: {href: "http://127.0.0.1:1/cases/stage1/atlas.html", origin: "http://127.0.0.1:1"},
    sessionStorage: {getItem: () => null}, URL, TextEncoder, crypto: webcrypto,
    fetch: async (url, options) => {
      requests.push({url, method: options.method});
      const cursor = Number(new URL(url, "http://127.0.0.1:1").searchParams.get("after_seq"));
      return {ok: true, json: async () => cursor === 0 ? records.slice(0, 100) : malformed ? [records[99]] : [records[100]]};
    },
  });
  const find = text => descendants(body).find(node => node.tag === "button" && node.textContent === text);
  const rows = () => descendants(body).find(node => node.className === "host-feedback-history").children;
  await find("Read feedback history").click();
  assert.equal(rows().length, 100);
  assert.equal(find("Read next feedback page").hidden, false);
  await find("Read next feedback page").click();
  assert.equal(rows().length, 100, "invalid page must preserve previous records");
  malformed = false;
  await find("Read next feedback page").click();
  assert.equal(rows().length, 101);
  assert.equal(find("Read next feedback page").hidden, true);
  assert.equal(requests[2].url, "/api/maintenance/stage1?after_seq=100&limit=100");
  assert.ok(requests.every(request => request.method === "GET"));
  await find("Read feedback history").click();
  assert.equal(rows().length, 100, "reload begins at the first bounded page");
  console.log("feedback pagination: 101 records, malformed page retention, bounded cursor, GET-only PASS");
})().catch(error => { console.error(error); process.exitCode = 1; });
