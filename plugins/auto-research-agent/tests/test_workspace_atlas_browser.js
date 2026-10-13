"use strict";
// Run with Playwright and ATLAS_SITE_ROOT pointing at a saved synthetic export.
const {chromium} = require("playwright"), fs = require("node:fs"), path = require("node:path"), http = require("node:http"), assert = require("node:assert/strict");
const root = path.resolve(process.env.ATLAS_SITE_ROOT || "");
if (!process.env.ATLAS_SITE_ROOT) throw new Error("ATLAS_SITE_ROOT is required");
async function navigationGeometry(page, width) {
  const navigation = page.locator(".atlas-workspace-nav, #atlas-stages");
  assert.equal(await navigation.count(), 2, "expected workspace and stage navigation");
  const rows = [];
  for (let index = 0; index < 2; index += 1) {
    const nav = navigation.nth(index), items = nav.locator(":scope > a, :scope > button");
    const itemCount = await items.count();
    assert(itemCount > 1, `navigation ${index} must have multiple destinations`);
    const last = items.last();
    await items.first().focus();
    for (let step = 1; step < itemCount; step += 1) await page.keyboard.press("Tab");
    assert(await last.evaluate(item => item === document.activeElement), `navigation ${index} last item did not receive keyboard focus`);
    if (width <= 700) await nav.evaluate(element => { element.scrollLeft = element.scrollWidth; });
    const geometry = await nav.evaluate((element, phone) => {
      const bounds = element.getBoundingClientRect();
      const items = [...element.children].map(child => child.getBoundingClientRect());
      const tops = items.map(item => item.top);
      const last = items.at(-1);
      return {
        clientWidth: element.clientWidth,
        scrollWidth: element.scrollWidth,
        scrollLeft: element.scrollLeft,
        oneRow: Math.max(...tops) - Math.min(...tops) <= 1,
        lastVisible: last.left >= bounds.left - 1 && last.right <= bounds.right + 1,
        contained: bounds.left >= -1 && bounds.right <= document.documentElement.clientWidth + 1,
        phone,
      };
    }, width <= 700);
    assert(geometry.lastVisible, `navigation ${index} last item is not scroll-reachable at ${width}px: ${JSON.stringify(geometry)}`);
    assert(geometry.contained, `navigation ${index} escapes the page at ${width}px: ${JSON.stringify(geometry)}`);
    if (geometry.phone) assert(geometry.oneRow, `navigation ${index} wrapped on the phone viewport: ${JSON.stringify(geometry)}`);
    await items.first().focus();
    assert(await items.first().evaluate(item => item === document.activeElement), `navigation ${index} first item did not receive keyboard focus`);
    rows.push(geometry);
  }
  if (width <= 700) assert(rows.some(row => row.scrollWidth > row.clientWidth + 1), `phone navigation did not expose a bounded horizontal scroll surface: ${JSON.stringify(rows)}`);
  const pageGeometry = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
    bodyRight: document.body.getBoundingClientRect().right,
  }));
  assert(pageGeometry.scrollWidth <= pageGeometry.clientWidth + 1, `page overflow at ${width}px: ${JSON.stringify(pageGeometry)}`);
  assert(pageGeometry.bodyRight <= pageGeometry.clientWidth + 1, `body escapes viewport at ${width}px: ${JSON.stringify(pageGeometry)}`);
  return rows;
}
(async () => {
  const server = http.createServer((req, res) => {
    const relative = decodeURIComponent(new URL(req.url, "http://127.0.0.1").pathname).replace(/^\/+/, "");
    const file = path.resolve(root, relative || "atlas.html");
    if (!file.startsWith(root + path.sep)) { res.writeHead(403).end(); return; }
    const mime = {".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json"};
    try { res.writeHead(200, {"Content-Type": mime[path.extname(file)] || "application/octet-stream"}).end(fs.readFileSync(file)); } catch { res.writeHead(404).end(); }
  });
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  let browser;
  const results = [];
  try {
    browser = await chromium.launch({headless: process.env.ATLAS_HEADLESS === "1", ...(process.env.ATLAS_BROWSER_EXECUTABLE ? {executablePath: process.env.ATLAS_BROWSER_EXECUTABLE} : {})});
    const page = await browser.newPage(), origin = `http://127.0.0.1:${server.address().port}`;
    await page.route("**/*", route => new URL(route.request().url()).origin === origin ? route.continue() : route.abort());
    for (const width of [1440, 768, 390]) {
      await page.setViewportSize({width, height: 1000});
      await page.goto(origin + "/atlas.html");
      const navigation = await navigationGeometry(page, width);
      await page.locator('#atlas-stages button').nth(1).focus(); await page.keyboard.press("Enter");
      assert.equal(await page.evaluate(() => document.activeElement.dataset.atlasFocus), "stage:2");
      await page.keyboard.press("Tab");
      assert.equal(await page.evaluate(() => document.activeElement.dataset.atlasFocus), "stage:3");
      await page.locator('#atlas-stages button').nth(0).click();
      const host = page.locator(".atlas-spatial-host").first();
      await host.scrollIntoViewIfNeeded();
      await page.waitForFunction(() => document.querySelector(".atlas-spatial-host")?.atlasDiagnostics().nodes > 0);
      const geometry = await host.evaluate(box => ({width: box.clientWidth, parentWidth: box.parentElement.clientWidth, height: box.clientHeight, ...box.atlasDiagnostics()}));
      assert.equal(geometry.focusedRelations, 0); assert.equal(geometry.faults.length, 0);
      assert(geometry.width <= geometry.parentWidth, JSON.stringify(geometry));
      const paper = page.locator("[data-summary-paper]").first(), key = await paper.getAttribute("data-summary-paper");
      await paper.focus(); await page.keyboard.press("Enter");
      await host.scrollIntoViewIfNeeded();
      await page.waitForFunction(() => document.querySelector(".atlas-spatial-host")?.atlasDiagnostics().focus?.kind === "paper");
      assert.deepEqual(await host.evaluate(box => box.atlasDiagnostics().focus), {kind: "paper", key});
      await page.locator("#atlas-library > summary").click();
      await page.waitForFunction(() => document.querySelector("#atlas-library")?.open === true);
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => resolve())));
      const next = page.locator('[data-atlas-focus="page:page:1"]');
      if (await next.isEnabled()) {
        await next.focus(); await page.keyboard.press("Enter");
        await page.waitForFunction(() => ["page:page:1", "page:page:-1"].includes(document.activeElement.dataset.atlasFocus));
        assert(["page:page:1", "page:page:-1"].includes(await page.evaluate(() => document.activeElement.dataset.atlasFocus)));
      }
      const select = page.locator(".atlas-filters select").first(), choiceKey = await select.getAttribute("data-atlas-focus");
      await select.focus(); await select.selectOption({index: 1});
      assert.equal(await page.evaluate(() => document.activeElement.dataset.atlasFocus), choiceKey);
      await page.locator('#atlas-stages button').nth(1).click();
      // UI-only fallback reuses exact identities; no stage or model is run.
      await page.evaluate(() => {
        const payload = window.WORKSPACE_VIEW, view = payload.stage2_comparison || {};
        if (view.directions?.length) return;
        const rows = payload.index.papers.slice(0, 6).map((row, i) => ({...row, key: JSON.stringify([row.work_id, row.version_id]), source_ids: row.source_ids?.length ? row.source_ids : [`ui-source-${i}`], evidence_ids: [`ui-evidence-${i}`]}));
        const evidence = rows.map((row, i) => ({evidence_id: `ui-evidence-${i}`, work_id: row.work_id, version_id: row.version_id, source_id: row.source_ids[0]}));
        payload.stage2_comparison = {...view, literature: rows, evidence, directions: [1, 2, 3].map(i => ({candidate_id: `ui-route-${i}`, version: 1, question: "Synthetic interface route with retained paper identities", evidence_ids: evidence.map(row => row.evidence_id)}))};
      });
      await page.getByRole("button", {name: "Direction sets", exact: true}).click();
      await page.getByRole("button", {name: "Compare these papers", exact: true}).focus(); await page.keyboard.press("Enter");
      assert.equal(await page.getByRole("button", {name: "Paper comparison", exact: true}).getAttribute("aria-pressed"), "true");
      await page.getByRole("button", {name: "Paper comparison", exact: true}).click();
      const comparison = page.locator('input[data-atlas-focus^="compare:"]').first();
      if (await comparison.count()) {
        const comparisonKey = await comparison.getAttribute("data-atlas-focus");
        await comparison.focus(); await page.keyboard.press("Space");
        assert.equal(await page.evaluate(() => document.activeElement.dataset.atlasFocus), comparisonKey);
      } else assert((await page.locator("#atlas-content").innerText()).includes("no structured literature rows"));
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1));
      await page.getByRole("button", {name: "Candidate routes & review", exact: true}).click();
      const candidateGeometry = await page.locator(".atlas-card .atlas-graph").evaluateAll(graphs => graphs.map(graph => ({width: graph.getBoundingClientRect().width, available: graph.parentElement.clientWidth - parseFloat(getComputedStyle(graph.parentElement).paddingLeft) - parseFloat(getComputedStyle(graph.parentElement).paddingRight)})));
      assert(candidateGeometry.length > 0, "candidate regression requires bound paper graphs");
      candidateGeometry.forEach(row => assert(row.width <= row.available + 1, JSON.stringify(row)));
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1), `candidate routes overflow at ${width}px`);
      results.push({width, navigation, geometry, candidateGeometry, keyboard: "PASS", overflow: "PASS", stage2Literature: "saved fixture or synthetic UI-only projection of exact Stage 1 identities"});
    }
    console.log(JSON.stringify({status: "PASS", scope: "saved synthetic export; actual Chromium; no research/native execution", results}));
  } finally {
    if (browser) await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
