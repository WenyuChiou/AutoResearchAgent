/* Installed-browser + real temporary HTTP/Core/SQLite. Authored research only. */
"use strict";
const fs = require("node:fs"), path = require("node:path"), cp = require("node:child_process"), crypto = require("node:crypto"), assert = require("node:assert/strict");
const [python, output] = process.argv.slice(2);
if (!python || !path.isAbsolute(output)) throw Error("python and fresh absolute private output required");
fs.mkdirSync(output); // EEXIST fails; historical receipts cannot be overwritten.
const fixture = path.resolve(__dirname, "../project_claim_browser_fixture.py"), stop = path.join(output, "stop");
const child = cp.spawn(python, ["-X", "utf8", "-u", fixture, "--stop-file", stop], {stdio: ["ignore", "pipe", "pipe"]});
let lines = "", errors = "", ready, final, browser, exitCode, failure;
const checks = [], diagnostics = [], pageErrors = [], posts = [];
let resolveReady, rejectReady;
const started = new Promise((ok, fail) => { resolveReady = ok; rejectReady = fail; });
const exited = new Promise(resolve => { child.on("exit", (code, signal) => { exitCode = code; if (!ready) rejectReady(Error("fixture exited before ready: " + code)); resolve({code, signal}); }); child.on("error", e => {rejectReady(e); resolve({error: e.message});}); });
child.stderr.on("data", b => {errors += b;});
child.stdout.on("data", b => { lines += b; const rows = lines.split("\n"); lines = rows.pop(); for (const line of rows) {
  try { const value = JSON.parse(line); if (value.kind === "SyntheticSavedDraftBrowserFixture") {ready = value; resolveReady(value);} else if (value.kind === "SyntheticSavedDraftBrowserFixtureStopped") final = value; } catch { diagnostics.push("non-json fixture output"); }
}});
const within = (promise, ms, message) => { let timer; return Promise.race([promise, new Promise((_, no) => {timer = setTimeout(() => no(Error(message)), ms);})]).finally(() => clearTimeout(timer)); };
function record(name) { checks.push({name, passed: true}); }
(async () => {
  try {
    await within(started, 45000, "fixture ready timeout");
    const {chromium} = require(process.env.PLAYWRIGHT_MODULE || "playwright");
    browser = await chromium.launch({headless: true, executablePath: process.env.CHROME_PATH});
    const context = await browser.newContext({viewport: {width: 1440, height: 1000}});
    await context.route("**/*", route => new URL(route.request().url()).origin === new URL(ready.url).origin ? route.continue() : route.abort());
    const page = await context.newPage(); page.setDefaultTimeout(30000);
    page.on("pageerror", e => pageErrors.push(e.message)); page.on("console", m => {if (m.type() === "error") diagnostics.push(m.text());});
    page.on("request", r => {if (r.method() === "POST") posts.push(new URL(r.url()).pathname);});
    await page.goto(ready.url);
    await page.locator("#project-list button").first().click();
    const captions = {en: "Review evidence in saved source text", "zh-Hans": "审阅已保存原文的证据", "zh-Hant": "審閱已保存原文的證據"};
    async function open(language) {
      await page.locator("#language").selectOption(language);
      await page.locator("#screening-list button").first().click();
      await page.getByRole("button", {name: captions[language], exact: true}).click();
      await page.locator("#saved-claim-source-text").waitFor({state: "visible"});
      assert((await page.locator("#saved-claim-source-text").inputValue()).length > 30);
    }
    for (const lang of ["en", "zh-Hans", "zh-Hant"]) { await open(lang); await page.screenshot({path: path.join(output, lang + ".png"), fullPage: false}); }
    assert.equal(posts.length, 0); record("actual library detail and trilingual saved-source GET without dispatch");
    // Render an authored CRLF/Unicode page through the same production widget.
    // No network content is replaced; this isolated seam never submits to Core.
    const newline = await page.evaluate(async () => {
      const frame = document.createElement("iframe"); document.body.append(frame);
      frame.contentDocument.body.innerHTML = '<section id="source-claim-card"><div id="source-claim-panel"></div></section>';
      const script = frame.contentDocument.createElement("script"); script.src = "/projects-saved-claims.js";
      await new Promise((ok, fail) => {script.onload = ok; script.onerror = fail; frame.contentDocument.body.append(script);});
      const hash = "a".repeat(64), project = {project_ref: "authored", input_version: 1, revision: 1, brief_sha256: hash};
      frame.contentWindow.ResearchSavedClaims.update({project, stage1: {ledger: {state_sha256: hash}}, language: "en", busy: false, held: false});
      let received;
      frame.contentWindow.ResearchSavedClaims.render({...project, ledger_state_sha256: hash, work_ref: "authored-work", version_id: "v1",
        sources: [{source_ref: hash, source_id: "authored-source", scope: "authored"}], selected_source: {source_ref: hash, offer_sha256: hash, text_sha256: hash},
        page: {start_byte: 0, text: "first\r\n中文😀\r\nlast", next_byte: 8}}, () => false, item => {received = item; return {status: "saved"};});
      const doc = frame.contentDocument, source = doc.getElementById("saved-claim-source-text");
      await Array.from(doc.querySelectorAll("button")).find(n => n.textContent === "Next page").onclick();
      if (!Array.from(doc.querySelectorAll("button")).find(n => n.textContent === "Previous page").disabled) throw Error("failed page changed navigation history");
      source.setSelectionRange(6, 10); Array.from(doc.querySelectorAll("button")).find(n => n.textContent === "Use selected passage").click();
      doc.querySelector("form textarea").value = "Authored claim"; doc.querySelector('form input:not([type="checkbox"])').value = "Authored paragraph";
      doc.querySelector('form input[type="checkbox"]').checked = true;
      await doc.querySelector("form").onsubmit(new Event("submit", {cancelable: true}));
      frame.remove(); return received;
    });
    assert.equal(newline.quote, "中文😀"); assert.equal(newline.start_byte, 7); assert.equal(newline.end_byte, 17);
    record("production widget preserves original CRLF and UTF8 multibyte selection offsets (authored seam)");
    await open("en");
    let resume, entered;
    const pause = new Promise(resolve => {resume = resolve;});
    const awaiting = new Promise(resolve => {entered = resolve;});
    const delayedRoute = async route => {entered(); await pause; await route.continue();};
    await page.route("**/stage1/source-claims/**", delayedRoute);
    const delayedResponse = page.waitForResponse(r => r.url().includes("/stage1/source-claims/") && r.status() === 200);
    await page.getByRole("button", {name: captions.en, exact: true}).click();
    await awaiting;
    await page.getByRole("button", {name: "Close", exact: true}).click();
    resume(); await (await delayedResponse).finished();
    await page.waitForTimeout(100);
    assert(await page.locator("#source-claim-card").isHidden());
    await page.unroute("**/stage1/source-claims/**", delayedRoute);
    record("explicit close retires late initial GET; failed authored pagination keeps history");
    await open("en");
    await page.locator("#saved-claim-source-text").evaluate(n => n.setSelectionRange(0, 30));
    await page.getByRole("button", {name: "Use selected passage", exact: true}).click();
    await page.locator("#saved-claim-form textarea").fill("Authored browser human-reviewed claim");
    await page.locator('#saved-claim-form input:not([type="checkbox"])').fill("Authored first paragraph");
    await page.locator('#saved-claim-form select').first().selectOption("supports");
    await page.locator('#saved-claim-form input[type="checkbox"]').check();
    let observed;
    await page.route("**/stage1/source-claim", async route => { const response = await route.fetch(); observed = {status: response.status(), body: await response.json()}; await route.abort(); });
    await page.getByRole("button", {name: "Save reviewed claim", exact: true}).click();
    await page.locator('#saved-claim-form button[type="submit"]').evaluate(n => n.click());
    await page.waitForFunction(() => document.getElementById("notice").textContent.includes("response") || document.getElementById("recover-intents")?.disabled === false);
    await within((async () => {while (!observed) await new Promise(r => setTimeout(r, 25));})(), 30000, "POST outcome unobserved");
    assert.equal(observed.status, 200); assert.equal(observed.body.status, "saved");
    assert.equal(posts.filter(p => p.endsWith("/stage1/source-claim")).length, 1);
    record("explicit real HTTP Core claim saved once despite response loss and second click");
    const pendingBefore = await page.evaluate(() => JSON.parse(sessionStorage.getItem("harness-project-ui-intents-v1") || "[]"));
    assert.equal(pendingBefore.length, 1);
    assert.equal(pendingBefore[0].kind, "stage1-claim");
    await page.locator("#refresh").click();
    await page.waitForFunction(() => JSON.parse(sessionStorage.getItem("harness-project-ui-intents-v1") || "[]").length === 0);
    await open("en");
    assert.equal(posts.length, 1); await page.screenshot({path: path.join(output, "after-recovery.png"), fullPage: false});
    record("GET history and reopened source view recover saved action with no resend");
    assert.deepEqual(pageErrors, []);
  } catch (e) {failure = e.stack || String(e);}
  finally {
    if (browser) await browser.close().catch(e => {failure ||= e.message;});
    fs.writeFileSync(stop, "stop", {flag: "wx"});
    try {await within(exited, 15000, "fixture cleanup timeout");} catch (e) {failure ||= e.message; child.kill(); await within(exited, 5000, "fixture termination unobserved").catch(() => {});}
    if (exitCode !== 0 || !final || errors) failure ||= "fixture completion or stderr failure";
    if (final && ready && final.claims !== ready.baseline_claims + 1) failure ||= "unexpected Core claim count";
    const receipt = {kind: "SavedSourceClaimBrowserCheck", passed: !failure, checks, failure, pageErrors, diagnostics, posts,
      fixture: ready && {baseline_claims: ready.baseline_claims, synthetic_provider_units: ready.synthetic_provider_units,
        executed_sources: ready.executed_sources, ui_sources: ready.ui_sources},
      completion: final && {claims: final.claims, baseline_claims: final.baseline_claims, synthetic_provider_units: final.synthetic_provider_units},
      fixture_exit_code: exitCode, stderr: errors, real_research_execution: false,
      driver_sha256: crypto.createHash("sha256").update(fs.readFileSync(__filename)).digest("hex")};
    fs.writeFileSync(path.join(output, "receipt.json"), JSON.stringify(receipt, null, 2) + "\n", {flag: "wx"});
    process.stdout.write(JSON.stringify({passed: receipt.passed, checks: checks.length, failure}) + "\n");
    process.exitCode = receipt.passed ? 0 : 1;
  }
})().catch(e => {process.stderr.write(e.stack + "\n"); process.exitCode = 1;});
