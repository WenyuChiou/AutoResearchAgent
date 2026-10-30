/* Real local Host UI journey. Only the first run acknowledgement is lost.
 * route.fetch reaches the real server; no successful API reply is fabricated.
 */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const {chromium} = require(process.env.STAGE3_E2E_PLAYWRIGHT_MODULE || "playwright");

const [origin, ref, evidence] = process.argv.slice(2);
assert.match(origin, /^http:\/\/127\.0\.0\.1:\d+$/);
assert.match(ref, /^[A-Za-z0-9_-]{1,64}$/);
assert.ok(path.isAbsolute(evidence));
fs.mkdirSync(evidence, {recursive: true});
const endpoint = `/api/projects/${ref}/stage3/planning`;
const labels = {
  en: ["Stage 3 · Research planning", "2. Start planning"],
  "zh-TW": ["Stage 3 · 研究規劃", "2. 開始規劃"],
  "zh-CN": ["Stage 3 · 研究规划", "2. 开始规划"],
};
const summary = {kind: "Stage3ActualHostBrowserE2E", profiles: [],
  run_requests: 0, response_losses: 0, page_errors: [], console_errors: [], external_requests: [],
  native_model_calls: null, scientific_evaluation: "not-run"};
let browser;
let activePage;
let activeContext;

function observe(page) {
  page.on("pageerror", error => summary.page_errors.push(String(error)));
  page.on("console", message => {
    if (message.type() === "error") summary.console_errors.push({text: message.text(), url: message.location().url});
  });
  page.on("request", request => {
    const url = new URL(request.url());
    if (url.origin !== origin) summary.external_requests.push(request.url());
    if (url.pathname === endpoint + "/run" && request.method() === "POST") {
      summary.run_requests++;
    }
  });
}

async function readSaved(page) {
  const response = page.waitForResponse(r => new URL(r.url()).pathname === endpoint
    && r.request().method() === "GET", {timeout: 32000});
  await page.locator("#refresh").click();
  const saved = await response;
  assert.equal(saved.status(), 200);
  return saved.json();
}

async function inspectSaved(page) {
  const details = page.locator("#planning-details");
  if (!(await details.evaluate(element => element.open))) {
    await details.locator(":scope > summary").click();
  }
  const inspected = page.waitForResponse(r => new URL(r.url()).pathname === endpoint + "/inspect");
  await page.getByRole("button", {name: "Inspect saved result", exact: true}).click();
  assert.equal((await inspected).status(), 200);
}

async function profiles(page, viewport, expectedPlan) {
  for (const [language, text] of Object.entries(labels)) {
    await page.locator("#language").selectOption(language);
    await page.getByRole("heading", {level: 1, name: text[0], exact: true}).waitFor();
    assert.equal(await page.locator("html").getAttribute("lang"), language);
    assert.deepEqual(JSON.parse(await page.locator("#plan-json").textContent()), expectedPlan);
    assert.equal(await page.locator("#run").textContent(), text[1]);
    assert.equal(await page.locator("#run").isVisible(), false);
    assert.equal(await page.locator("#run").isDisabled(), true);
    assert.equal(await page.locator("#recover").isDisabled(), true);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true,
      `Horizontal overflow for ${viewport}/${language}`);
    const file = path.join(evidence, `${viewport}-${language}.png`);
    await page.screenshot({path: file, fullPage: true});
    summary.profiles.push({viewport, language, screenshot: file,
      sha256: crypto.createHash("sha256").update(fs.readFileSync(file)).digest("hex")});
  }
}

async function main() {
  browser = await chromium.launch({headless: true});
  summary.browser_version = browser.version();
  const desktop = await browser.newContext({viewport: {width: 1440, height: 960}});
  await desktop.tracing.start({screenshots: true, snapshots: true, sources: true});
  const page = await desktop.newPage();
  activePage = page; activeContext = desktop;
  page.setDefaultTimeout(35000);
  observe(page);
  await page.goto(origin + "/project-stage3-planning.html#" + ref);
  await page.getByRole("status").filter({hasText: "Choose a current eligible direction"}).waitFor();
  assert.equal(await page.locator("#actions").isVisible(), false);
  assert.equal(summary.run_requests, 0);
  await page.getByRole("link", {name: "Review the selected direction", exact: true}).click();
  assert.equal(new URL(page.url()).hash, "#" + ref);
  await page.getByRole("radio").waitFor();
  assert.equal(await page.getByRole("radio").count(), 1);
  await page.getByRole("radio").check();
  await page.getByLabel("Your name", {exact: true}).fill("synthetic-browser-e2e-actor");
  await page.getByLabel("Your selection message", {exact: true}).fill(
    "Engineering selection only.\n保留原文與限制，不授權研究或實驗。");
  await page.getByLabel("Why choose this direction?", {exact: true}).fill("Verify the real source-bound UI route.");
  await page.getByLabel("Conditions to retain (one per line)", {exact: true}).fill("Keep limitations");
  await page.getByLabel("Open questions (one per line)", {exact: true}).fill("Access unknown");
  await page.locator("#confirmed").check();
  await page.getByRole("button", {name: "Save selection only", exact: true}).click();
  await page.locator("#stage3-entry").waitFor({state: "visible", timeout: 65000});
  assert.equal(summary.run_requests, 0);
  assert.equal(new URL(await page.locator("#stage3-entry").getAttribute("href"), origin).hash, "#" + ref);
  await page.locator("#stage3-entry").click();
  await page.getByRole("status").filter({hasText: "Selection saved. Prepare"}).waitFor();
  assert.equal(await page.locator("#run").isDisabled(), true);
  await page.getByRole("button", {name: "1. Prepare planning input", exact: true}).click();
  await page.waitForFunction(() => !document.getElementById("confirmed").disabled, null, {timeout: 65000});
  assert.equal(summary.run_requests, 0);
  assert.equal(await page.locator("#run").isDisabled(), true);
  const prepared = JSON.parse(await page.locator("#receipt").textContent());
  assert.equal(prepared.job.status, "intent-recorded");
  for (const flag of ["execution_authorized", "evaluation_calls_authorized",
    "formal_execution_enabled", "external_claim_ready", "usable_for_formal_pairing"]) {
    assert.equal(prepared[flag], false);
  }
  await page.route(origin + endpoint + "/run", async route => {
    const actual = await route.fetch({timeout: 32000});
    assert.equal(actual.status(), 202);
    assert.equal((await actual.json()).dispatch_observed, false);
    summary.response_losses++;
    await route.abort("connectionreset");
  });
  await page.locator("#confirmed").check();
  await page.getByRole("button", {name: "2. Start planning", exact: true}).click();
  await page.getByRole("status").filter({hasText: "The operation could not be verified"}).waitFor();
  assert.equal(summary.response_losses, 1);
  assert.equal(summary.run_requests, 1);
  let saved;
  for (let attempt = 0; attempt < 3; attempt++) {
    saved = await readSaved(page);
    if (saved.job?.outcome === "saved") break;
  }
  assert.equal(saved.job.outcome, "saved", "Retained job must be discoverable after lost acknowledgement");
  await page.locator("#plan").waitFor({state: "visible"});
  const plan = JSON.parse(await page.locator("#plan-json").textContent());
  assert.equal(plan.execution_authorized, false);
  assert.equal(saved.job.planning_status, "needs-information");
  assert.ok(plan.condition_dispositions.length > 0);
  assert.ok(plan.unknowns.some(row => row.blocking && row.resolve_before === "material-design"));
  for (const result of plan.results) {
    assert.equal(result.status, "not-run");
    assert.equal(result.observed_value, null);
    assert.deepEqual(Object.keys(result.interpretation).sort(), ["contradicts", "inconclusive", "supports"]);
  }
  summary.question_refs = plan.questions.map(row => row.question_ref);
  summary.plan_manifest_sha256 = saved.job.plan_manifest_sha256;
  summary.planning_status = saved.job.planning_status;
  await inspectSaved(page);
  await page.waitForFunction(() => !document.getElementById("refresh").disabled);
  assert.equal(summary.run_requests, 1);
  await profiles(page, "desktop-1440", plan);
  await page.locator("#selection").click();
  await page.locator("#stage3-entry").waitFor({state: "visible"});
  assert.equal(new URL(page.url()).hash, "#" + ref);
  assert.equal((await page.locator("#planning-input").textContent()).includes("Access unknown"), true);
  await desktop.tracing.stop({path: path.join(evidence, "desktop-trace.zip")});
  await desktop.close();
  activePage = null; activeContext = null;
  const mobile = await browser.newContext({viewport: {width: 390, height: 844}, isMobile: true, hasTouch: true});
  await mobile.tracing.start({screenshots: true, snapshots: true, sources: true});
  const mobilePage = await mobile.newPage();
  activePage = mobilePage; activeContext = mobile;
  mobilePage.setDefaultTimeout(35000);
  observe(mobilePage);
  await mobilePage.goto(origin + "/project-stage3-planning.html#" + ref);
  await mobilePage.locator("#plan").waitFor({state: "visible"});
  await profiles(mobilePage, "mobile-390", plan);
  await mobile.tracing.stop({path: path.join(evidence, "mobile-trace.zip")});
  await mobile.close();
  activePage = null; activeContext = null;
  assert.equal(summary.profiles.length, 6);
  assert.equal(summary.run_requests, 1);
  assert.deepEqual(summary.page_errors, []);
  assert.deepEqual(summary.external_requests, []);
  summary.unexpected_console_errors = summary.console_errors.filter(row =>
    !row.text.includes("ERR_CONNECTION_RESET") && !(row.url === origin + "/favicon.ico" && row.text.includes("404 (Not Found)")));
  assert.deepEqual(summary.unexpected_console_errors, []);
  summary.outcome = "passed";
}

(async () => {
  try { await main(); }
  catch (error) {
    summary.outcome = "failed"; summary.error = String(error.stack || error); process.exitCode = 1;
    if (activePage) {
      try { await activePage.screenshot({path: path.join(evidence, "failure.png"), fullPage: true}); }
      catch (captureError) { summary.failure_screenshot_error = String(captureError); }
    }
    if (activeContext) {
      try { await activeContext.tracing.stop({path: path.join(evidence, "failure-trace.zip")}); }
      catch (captureError) { summary.failure_trace_error = String(captureError); }
    }
  }
  finally {
    if (browser) await browser.close();
    const file = path.join(evidence, "browser-e2e-summary.json");
    fs.writeFileSync(file, JSON.stringify(summary, null, 2), {flag: "wx"});
    console.log(JSON.stringify({outcome: summary.outcome, profiles: summary.profiles.length,
      run_requests: summary.run_requests, response_losses: summary.response_losses, summary: file}));
    if (summary.error) console.error(summary.error);
  }
})();
