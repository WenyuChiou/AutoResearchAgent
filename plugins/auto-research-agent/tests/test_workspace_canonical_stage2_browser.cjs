'use strict';

const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');

class SavedStage2Page {
  constructor(page) { this.page = page; }
  async stage(number) {
    // Stable focus identity is the existing accessible stage-navigation contract.
    await this.page.locator(`#atlas-stages button[data-atlas-focus="stage:${number}"]`).click();
    await this.page.waitForFunction(n => document.documentElement.dataset.atlasStage === String(n), number);
  }
  async language(value) {
    // The label also contains option text; use the existing stable select id.
    await this.page.locator('#atlas-language').selectOption(value);
    await this.page.waitForFunction(lang => document.documentElement.lang === lang, value);
  }
}

(async () => {
  const root = process.env.CANONICAL_STAGE2_URL;
  assert(root && /^http:\/\/127\.0\.0\.1:\d+\/$/.test(root));
  const artifactRoot = process.env.CANONICAL_STAGE2_RENDERED_ARTIFACTS;
  if (artifactRoot) fs.mkdirSync(artifactRoot, {recursive: true});
  const browser = await chromium.launch({headless: true,
    executablePath: process.env.ATLAS_BROWSER_EXECUTABLE || undefined});
  const failures = [], requests = [], results = [];
  try {
    for (const width of [1440, 390]) {
      for (const language of ['en', 'zh-Hans', 'zh-Hant']) {
        const context = await browser.newContext({viewport: {width, height: 1000}});
        const tracing = artifactRoot && language === 'en' && width === 1440;
        if (tracing) await context.tracing.start({screenshots: true, snapshots: true});
        const page = await context.newPage(), view = new SavedStage2Page(page);
        page.on('pageerror', error => failures.push(error.message));
        page.on('request', request => requests.push({method: request.method(), url: request.url()}));
        await context.route('**/*', route => {
          if (new URL(route.request().url()).origin !== new URL(root).origin) {
            failures.push('external-request:' + route.request().url());
            return route.abort();
          }
          return route.continue();
        });
        try {
          await page.goto(root);
          await page.getByRole('link', {name: 'Synthetic current Stage2', exact: true}).click();
          assert.equal(new URL(page.url()).pathname, '/views/current-stage2/atlas.html');
          await page.waitForLoadState('domcontentloaded');
          await page.waitForFunction(() => window.WORKSPACE_VIEW?.index);
          const payload = await page.evaluate(() => window.WORKSPACE_VIEW);
          assert.equal(payload.index.schema_version, '1.2.0');
          assert.equal(payload.index_sha256, process.env.CANONICAL_STAGE2_INDEX_SHA256);
          assert.equal(payload.index.stage2_canonical_consumer.status, 'unconnected');
          assert(payload.index.papers.some(p => p.reading_status === 'discovery-only' && p.findings.main_findings === 'Unknown'));
          assert.equal(payload.stage2.bridge_receipt.stage3_authorized, false);
          assert.equal(payload.stage2.bridge_receipt.original_stage1_lineage_attested, false);
          assert.equal(payload.stage2.bridge_receipt.human_selection, 'pending');
          assert.equal(payload.stage2.evaluation.rows.length, 9);
          await view.stage(2);
          await view.language(language);
          const geometry = await page.evaluate(() => ({viewport: innerWidth, document: document.documentElement.scrollWidth}));
          assert(geometry.document <= geometry.viewport + 1, JSON.stringify(geometry));
          let screenshot = null;
          if (artifactRoot) {
            const target = path.join(artifactRoot, `stage2-${language}-${width}.png`);
            await page.screenshot({path: target});
            screenshot = {file: path.basename(target), sha256: crypto.createHash('sha256').update(fs.readFileSync(target)).digest('hex')};
          }
          // Operations use the unchanged English labels; all locale rendering is captured above.
          await page.locator('#atlas-language').selectOption('en');
          await page.waitForFunction(() => document.documentElement.lang === 'en');
          await page.getByRole('button', {name: 'Paper comparison', exact: true}).click();
          assert(await page.getByRole('table').count() > 0);
          await page.getByRole('button', {name: 'Candidate routes & review', exact: true}).click();
          const content = await page.locator('#atlas-content').innerText();
          const candidates = payload.stage2.selection.evaluation_packet.candidates;
          assert(candidates.length > 0);
          const latest = candidates.reduce((a, b) => a.version > b.version ? a : b);
          assert(content.includes(latest.question));
          const summary = page.getByText('Complete original assessment, comments & attachment', {exact: true});
          await summary.click();
          assert(await summary.evaluate(el => el.parentElement.open));
          assert((await summary.evaluate(el => el.parentElement.textContent)).includes('R1 source-bound comment'));
          await view.stage(3);
          assert((await page.locator('#atlas-content').innerText()).match(/planned|not connected|unconnected/i));
          await view.stage(2);
          const response = await context.request.get(root + 'views/current-stage2/stage2/core_selection.json');
          assert.equal(response.status(), 200);
          assert.equal(crypto.createHash('sha256').update(await response.body()).digest('hex'), process.env.CANONICAL_STAGE2_SELECTION_SHA256);
          await page.locator('#atlas-original').click();
          assert.equal(new URL(page.url()).pathname, '/views/current-stage2/index.html');
          await page.getByRole('link', {name: 'Open literature map and comparison atlas', exact: true}).click();
          assert.equal(new URL(page.url()).pathname, '/views/current-stage2/atlas.html');
          // Frozen Wiki/Atlas links remain unchanged; Browser Back returns through the visited loop.
          await page.goBack(); await page.goBack(); await page.goBack();
          assert.equal(page.url(), root);
          results.push({language, width, geometry, screenshot, status: 'PASS', portal_return: 'browser-history'});
        } finally {
          if (tracing) await context.tracing.stop({path: path.join(artifactRoot, 'private-browser-trace.zip')});
          await context.close();
        }
      }
    }
    assert.deepEqual(failures, []);
    assert(requests.every(r => r.method === 'GET'));
    const report = {status: 'PASS', url: root, browser: browser.version(), results,
      post_requests: requests.filter(r => r.method !== 'GET').length, page_errors: failures,
      scope: 'synthetic current canonical1.2 plus saved evaluated Stage2; no native/model/research authority'};
    if (artifactRoot) fs.writeFileSync(path.join(artifactRoot, 'browser-receipt.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report));
  } finally { await browser.close(); }
})().catch(error => { console.error(error.stack); process.exitCode = 1; });
