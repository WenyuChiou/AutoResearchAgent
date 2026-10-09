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
    browser = await chromium.launch({headless: false});
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
      const geometry = await page.locator(".atlas-graph").first().evaluate(box => {
        const svg = box.querySelector("svg"), view = svg.viewBox.baseVal;
        const nodes = [...box.querySelectorAll(".atlas-node")];
        const offsets = [...svg.querySelectorAll("line")].flatMap(line => [[line.x1.baseVal.value, line.y1.baseVal.value], [line.x2.baseVal.value, line.y2.baseVal.value]].map(([x, y]) => {
          const node = nodes.find(n => Math.abs(parseFloat(n.style.left) * view.width / 100 - x) < .01 && Math.abs(parseFloat(n.style.top) * view.height / 100 - y) < .01);
          if (!node) throw new Error("edge has no corresponding node");
          const r = node.getBoundingClientRect(), m = line.getScreenCTM();
          return Math.hypot(m.a * x + m.c * y + m.e - r.x - r.width / 2, m.b * x + m.d * y + m.f - r.y - r.height / 2);
        }));
        return {width: box.clientWidth, parentWidth: box.parentElement.clientWidth, height: box.clientHeight, endpoints: offsets.length, maxOffset: Math.max(...offsets)};
      });
      assert(geometry.endpoints > 0); assert(geometry.maxOffset < 2, JSON.stringify(geometry));
      assert(geometry.width <= geometry.parentWidth, JSON.stringify(geometry));
      const paper = page.locator('.atlas-node[data-node-key^="paper:"]').first(), key = await paper.getAttribute("data-node-key");
      await paper.focus(); await page.keyboard.press("Enter");
      assert.equal(await page.evaluate(() => document.activeElement.dataset.nodeKey), key);
      const check = page.locator('input[data-atlas-focus="similarity"]');
      await check.focus(); await page.keyboard.press("Space");
      assert.equal(await page.evaluate(() => document.activeElement.dataset.atlasFocus), "similarity");
      await page.locator("#atlas-library > summary").click();
      const next = page.locator('[data-atlas-focus="page:page:1"]');
      if (await next.isEnabled()) {
        await next.focus(); await page.keyboard.press("Enter");
        assert(["page:page:1", "page:page:-1"].includes(await page.evaluate(() => document.activeElement.dataset.atlasFocus)));
      }
      const select = page.locator(".atlas-filters select").first(), choiceKey = await select.getAttribute("data-atlas-focus");
      await select.focus(); await select.selectOption({index: 1});
      assert.equal(await page.evaluate(() => document.activeElement.dataset.atlasFocus), choiceKey);
      await page.locator('#atlas-stages button').nth(1).click();
      // UI-only Stage 2 fixture: reuse exact Stage 1 work/version identities.
      // The saved package currently has no structured Stage 2 literature rows.
      await page.evaluate(() => { window.WORKSPACE_VIEW.stage2_comparison = {...window.WORKSPACE_VIEW.stage2_comparison, literature: window.WORKSPACE_VIEW.index.papers.map(row => ({...row, key: JSON.stringify([row.work_id, row.version_id])}))}; });
      await page.getByRole("button", {name: "Direction sets", exact: true}).click();
      await page.getByRole("button", {name: "Compare these papers", exact: true}).focus(); await page.keyboard.press("Enter");
      assert.equal(await page.evaluate(() => document.activeElement.tagName), "H1");
      await page.getByRole("button", {name: "Paper comparison", exact: true}).click();
      const comparison = page.locator('input[data-atlas-focus^="compare:"]').first();
      if (await comparison.count()) {
        const comparisonKey = await comparison.getAttribute("data-atlas-focus");
        await comparison.focus(); await page.keyboard.press("Space");
        assert.equal(await page.evaluate(() => document.activeElement.dataset.atlasFocus), comparisonKey);
      } else assert((await page.locator("#atlas-content").innerText()).includes("no structured literature rows"));
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1));
      results.push({width, geometry, keyboard: "PASS", overflow: "PASS", stage2Literature: "synthetic UI-only projection of exact Stage 1 identities"});
    }
    console.log(JSON.stringify({status: "PASS", scope: "saved synthetic export; actual Chromium; no research/native execution", results}));
  } finally {
    if (browser) await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
