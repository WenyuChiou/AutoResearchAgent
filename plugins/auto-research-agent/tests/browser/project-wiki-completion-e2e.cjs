/* Actual V9 Wiki Stage2 button to same-project saved Stage3 plan.
 * The planner is the Python fixture's deterministic callback; no model runs.
 */
const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || "playwright");

const [origin, ref, evidence, profile, widthText, heightText, mobileText] = process.argv.slice(2);
assert.match(origin, /^http:\/\/127\.0\.0\.1:\d+$/);
assert.match(ref, /^[A-Za-z0-9_-]{1,64}$/);
assert.ok(path.isAbsolute(evidence));
assert.match(profile, /^(desktop-1440|mobile-390)$/);
const width = Number(widthText), height = Number(heightText), isMobile = mobileText === "true";
assert.ok(Number.isInteger(width) && width > 0 && Number.isInteger(height) && height > 0);
fs.mkdirSync(evidence, {recursive: true});
const projectPath = `/api/projects/${ref}`;
const selectionPath = `${projectPath}/stage2/select`;
const planningPath = `${projectPath}/stage3/planning`;
const startPaths = [selectionPath, `${planningPath}/prepare`, `${planningPath}/run`];
const actionTimeoutMs = 65000;
const initialUrl = `${origin}/#${ref}?stage=2&lang=en`;
const summary = {
  kind: "ProjectWikiCompletionBrowserEvidence",
  schema_version: "1.0.0",
  automation: true,
  actual_human: false,
  scientific_evaluation: "not-run",
  project_ref: ref,
  operation_id: `wiki-stage2-to-stage3-${ref}`,
  profile,
  original_url: initialUrl,
  original_button: null,
  final_url: null,
  requests: [],
  profiles: [],
  observed_events: {},
  page_errors: [],
  console_errors: [],
  external_requests: [],
};
let browser;
let activePage;
let activeContext;

function sha256(raw) {
  return crypto.createHash("sha256").update(raw).digest("hex");
}

function observe(page) {
  page.on("pageerror", error => summary.page_errors.push(String(error)));
  page.on("console", message => {
    if (message.type() === "error") summary.console_errors.push(message.text());
  });
  page.on("request", request => {
    const url = new URL(request.url());
    if (url.origin !== origin) {
      summary.external_requests.push(request.url());
      return;
    }
    if (url.pathname !== projectPath && !url.pathname.startsWith(`${projectPath}/`)) return;
    const method = request.method();
    if (["GET", "HEAD", "OPTIONS"].includes(method)) return;
    const raw = request.postData() || "";
    summary.requests.push({
      path: url.pathname,
      method,
      payload: method === "POST" && startPaths.includes(url.pathname) ? JSON.parse(raw) : null,
      payload_sha256: sha256(Buffer.from(raw, "utf8")),
    });
  });
}

function assertNoProjectWrites(since, label) {
  assert.deepEqual(summary.requests.slice(since).map(row => `${row.method} ${row.path}`), [],
    `${label} must remain read-only (${profile})`);
}

async function waitForPlanningRunResponse(page) {
  const request = await page.waitForRequest(request =>
    request.url() === `${origin}${planningPath}/run` &&
    request.method() === "POST");
  let timer;
  try {
    // Start the response deadline at dispatch. Request.response() also retains
    // a response already observed before this continuation runs.
    const response = await Promise.race([
      request.response(),
      new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error("Planning run HTTP response timed out after dispatch")),
          actionTimeoutMs);
      }),
    ]);
    assert.ok(response, "Planning run ended without an HTTP response");
    return response;
  } finally {
    clearTimeout(timer);
  }
}

async function readSaved(page) {
  const button = page.getByRole("button", {name: "View saved plan", exact: true});
  let value;
  for (let attempt = 0; attempt < 4; attempt++) {
    const response = page.waitForResponse(response => {
      const request = response.request();
      const url = new URL(response.url());
      return url.origin === origin && url.pathname === planningPath && request.method() === "GET";
    });
    await button.click();
    const actual = await response;
    assert.equal(actual.status(), 200);
    value = await actual.json();
    if (value.job?.outcome === "saved") {
      await page.locator("#v93-diagram svg").waitFor();
      return value;
    }
    await page.waitForTimeout(100);
  }
  assert.fail(`saved plan unavailable: ${JSON.stringify(value?.job)}`);
}

async function screenshot(page, profile) {
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true,
    `horizontal overflow: ${profile}`);
  const target = path.join(evidence, `${profile}.png`);
  await page.screenshot({path: target, fullPage: true});
  summary.profiles.push({profile, width: await page.evaluate(() => innerWidth),
    screenshot: target, sha256: sha256(fs.readFileSync(target))});
}

async function main() {
  const channel = process.env.PROJECT_WIKI_COMPLETION_BROWSER_CHANNEL;
  assert.ok(!channel || channel === "chrome", "unsupported Wiki browser channel");
  summary.browser_channel = channel || "playwright-chromium";
  const launchOptions = {headless: true, chromiumSandbox: true};
  if (channel) launchOptions.channel = channel;
  browser = await chromium.launch(launchOptions);
  summary.browser_version = browser.version();
  const context = await browser.newContext({viewport: {width, height}, isMobile, hasTouch: isMobile});
  await context.tracing.start({screenshots: true, snapshots: true, sources: true});
  const page = await context.newPage();
  activePage = page; activeContext = context;
  page.setDefaultTimeout(actionTimeoutMs);
  observe(page);
  await page.goto(initialUrl);
  const chooser = page.locator("[data-v93-choice]");
  const radio = chooser.locator('input[name="direction"]');
  await radio.waitFor();
  assert.equal(await radio.count(), 1);
  await radio.click();
  await chooser.getByRole("button", {name: "Confirm your choice", exact: true}).click();
  await chooser.getByLabel("Your name", {exact: true}).fill("synthetic-browser-automation");
  await chooser.getByLabel("Your selection message", {exact: true}).fill(
    "Automation fixture selection; no human acceptance or research authorization."
  );
  await chooser.getByLabel("Why choose this direction?", {exact: true}).fill(
    "Exercise the original V9 Wiki completion route."
  );
  await chooser.getByLabel("Conditions to retain (one per line)", {exact: true}).fill("Keep limitations");
  await chooser.getByLabel("Open questions (one per line)", {exact: true}).fill("Access unknown");
  await chooser.locator("#confirmed").check();
  const start = chooser.getByRole("button", {name: "Save and start planning", exact: true});
  summary.original_button = (await start.textContent()).trim();
  assertNoProjectWrites(0, "before Save and start planning");
  const [receiptResponse, runResponse] = await Promise.all([
    page.waitForResponse(response =>
      response.url() === `${origin}${selectionPath}` && response.request().method() === "POST"),
    waitForPlanningRunResponse(page),
    start.click(),
  ]);
  assert.equal(receiptResponse.status(), 200);
  assert.equal(runResponse.status(), 202);
  const selectionReceipt = await receiptResponse.json();
  assert.equal(selectionReceipt.status, "saved");
  await page.waitForURL(url => url.hash.includes(`stage=3`) && url.hash.includes(ref));
  await page.getByRole("heading", {name: "Research design & feasibility", exact: true}).waitFor();
  assert.deepEqual(summary.requests.map(row => `${row.method} ${row.path}`),
    startPaths.map(route => `POST ${route}`),
    `one Save and start planning click must POST select, prepare, run once in order (${profile})`);
  const afterStart = summary.requests.length;
  const saved = await readSaved(page);
  assert.equal(saved.plan.kind, "Stage3ResearchPlan");
  assert.equal(saved.project_ref, ref);
  assert.equal(saved.job.outcome, "saved");
  assert.equal(saved.plan.execution_authorized, false);
  assert.equal(saved.job.execution_authorized, false);
  const runRequests = () => summary.requests.filter(row => row.path === `${planningPath}/run`);
  assert.equal(runRequests().length, 1);
  await screenshot(page, profile);
  assertNoProjectWrites(afterStart, "first view");
  const refreshed = await readSaved(page);
  assert.equal(refreshed.job.plan_manifest_sha256, saved.job.plan_manifest_sha256);
  assert.equal(runRequests().length, 1);
  assertNoProjectWrites(afterStart, "refresh");
  summary.final_url = page.url();
  const selectedRequest = summary.requests.find(row => row.path === selectionPath);
  const planningRequest = runRequests()[0];
  assert.ok(selectedRequest);
  assert.ok(planningRequest);
  assert.equal(planningRequest.payload.confirmed, true);
  const common = {
    project_ref: ref,
    input_version: saved.input_version,
    operation_id: summary.operation_id,
    submission_request_sha256: selectionReceipt.request_sha256,
     planning_key: planningRequest.payload.key,
     planning_request_sha256: saved.job.request_sha256,
     plan_manifest_sha256: saved.job.plan_manifest_sha256,
    original_request_key: selectedRequest.payload.key,
    origin: "automation",
    result: "passed",
  };
  summary.selection_receipt = selectionReceipt;
  summary.plan_manifest_sha256 = saved.job.plan_manifest_sha256;
  summary.planning_request_sha256 = saved.job.request_sha256;
  await context.tracing.stop({path: path.join(evidence, `${profile}-trace.zip`)});
  await context.close();
  activePage = null; activeContext = null;
  assertNoProjectWrites(afterStart, "final browser window");
  assert.equal(summary.profiles.length, 1);
  assert.deepEqual(summary.page_errors, []);
  assert.deepEqual(summary.external_requests, []);
  summary.unexpected_console_errors = summary.console_errors.filter(text =>
    !(text.includes("favicon.ico") && text.includes("404")));
  assert.deepEqual(summary.unexpected_console_errors, []);
  summary.observed_events = {
    entry: {...common, phase: "entry", target: "wiki-stage2-direction", mechanism: "click"},
    action: {...common, phase: "action", target: "wiki-stage2-save-and-start", mechanism: "click"},
    outcome: {...common, phase: "outcome", target: "wiki-stage3-saved-plan", mechanism: "click"},
  };
  summary.outcome = "passed";
}

(async () => {
  try { await main(); }
  catch (error) {
    summary.outcome = "failed";
    summary.error = String(error.stack || error);
    process.exitCode = 1;
    if (activePage) {
      try { await activePage.screenshot({path: path.join(evidence, "failure.png"), fullPage: true}); }
      catch (captureError) { summary.failure_screenshot_error = String(captureError); }
    }
    if (activeContext) {
      try { await activeContext.tracing.stop({path: path.join(evidence, "failure-trace.zip")}); }
      catch (captureError) { summary.failure_trace_error = String(captureError); }
    }
  } finally {
    if (browser) await browser.close();
    const target = path.join(evidence, "browser-observer.json");
    fs.writeFileSync(target, JSON.stringify(summary, null, 2), {flag: "wx"});
    console.log(JSON.stringify({outcome: summary.outcome, summary: target,
      requests: summary.requests.length, profiles: summary.profiles.length}));
    if (summary.error) console.error(summary.error);
  }
})();
