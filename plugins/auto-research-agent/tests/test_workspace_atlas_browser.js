"use strict";
// Run with Playwright and ATLAS_SITE_ROOT pointing at a saved synthetic export.
const {chromium} = require("playwright"), fs = require("node:fs"), path = require("node:path"), http = require("node:http"), assert = require("node:assert/strict");
const root = path.resolve(process.env.ATLAS_SITE_ROOT || "");
if (!process.env.ATLAS_SITE_ROOT) throw new Error("ATLAS_SITE_ROOT is required");
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
      results.push({width, geometry, candidateGeometry, keyboard: "PASS", overflow: "PASS", stage2Literature: "saved fixture or synthetic UI-only projection of exact Stage 1 identities"});
    }
    console.log(JSON.stringify({status: "PASS", scope: "saved synthetic export; actual Chromium; no research/native execution", results}));
  } finally {
    if (browser) await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
