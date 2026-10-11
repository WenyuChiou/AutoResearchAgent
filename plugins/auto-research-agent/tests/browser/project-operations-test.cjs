/* Installed browser, real local HTTP/SQLite and saved Atlas. No research run. */
'use strict';
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path');
const {spawn} = require('node:child_process'), {randomUUID} = require('node:crypto');
const args = Object.fromEntries(process.argv.slice(2).reduce((pairs, value, i, all) => i % 2 ? pairs : [...pairs, [value.slice(2), all[i + 1]]], []));
for (const key of ['repo', 'python', 'temp-root', 'output', 'playwright', 'chrome']) assert(path.isAbsolute(args[key]), key);
const {chromium} = require(args.playwright), id = randomUUID(), root = path.join(args['temp-root'], 'v6-' + id);
fs.mkdirSync(root); const control = path.join(root, 'control.jsonl'); fs.writeFileSync(control, '', {flag: 'wx'});
const command = [path.join(args.repo, 'plugins/auto-research-agent/tests/browser/project-intake-fixture.py'), '--repo', args.repo, '--temp-root', root, '--control-file', control, '--ui-overlay'];
if (args['views-config']) command.push('--views-config', args['views-config'], '--views-sha256', args['views-sha256']);
const child = spawn(args.python, ['-B', '-X', 'utf8', ...command], {stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true});
let stdout = '', stderr = '', exited = false, exitCode, browser, ready, resolveReady, rejectReady;
const started = new Promise((resolve, reject) => {resolveReady = resolve; rejectReady = reject;});
child.stdout.on('data', raw => {stdout += raw; const line = stdout.split('\n')[0]; try {ready = JSON.parse(line); resolveReady(ready);} catch (_) {}});
child.stderr.on('data', raw => {stderr += raw;});
const finished = new Promise(resolve => child.once('exit', code => {exited = true; exitCode = code; rejectReady(Error('fixture exited ' + code + ': ' + stderr)); resolve(code);}));
child.once('error', rejectReady);
const checks = [], pageErrors = [], posts = [], screenshots = [];
async function shot(page, name) {const file = path.join(path.dirname(args.output), name + '-' + id + '.png'); assert(!fs.existsSync(file)); await page.screenshot({path: file, fullPage: true}); screenshots.push(file);}
async function check(name, action) {await action(); checks.push(name);}
let failure = null, cleanup = [];
(async () => {
  let timer;
  try {
    const fixture = await Promise.race([started, new Promise((_, reject) => {timer = setTimeout(() => reject(Error('fixture startup timeout')), 30000);})]); clearTimeout(timer);
    browser = await chromium.launch({executablePath: args.chrome, headless: true, args: ['--enable-webgl', '--use-angle=swiftshader', '--enable-unsafe-swiftshader']});
    const context = await browser.newContext({viewport: {width: 1600, height: 1100}, deviceScaleFactor: 1});
    context.on('page', p => p.on('pageerror', e => pageErrors.push(e.message)));
    context.on('request', r => {if (r.method() === 'POST') posts.push(r.url());});
    const page = await context.newPage();
    await check('saved v6 main route and unchanged graph render', async () => {
      const response = await page.goto(fixture.origin + '/'); assert.equal(response.status(), 200);
      assert(page.url().includes('/views/stage1-original-r3/atlas.html'));
      await page.locator('#atlas-network').waitFor(); assert.equal(await page.locator('#create-card').count(), 0);
      assert.equal(await page.locator('#project-operations-frame').count(), 0);
      await page.locator('#atlas-language').selectOption('zh-Hans'); await shot(page, 'v6-preserved-main');
    });
    let savedDocument;
    await check('lazy same-origin operation drawer and three languages', async () => {
      await page.locator('#project-operations-open').click();
      const panel = page.frameLocator('#project-operations-frame'); await panel.locator('#create-form').waitFor();
      const frame = page.frames().find(f => f.url().endsWith('/projects-panel.html'));
      for (const lang of ['en', 'zh-Hans', 'zh-Hant']) {
        await page.locator('#project-operations-close').click(); await page.locator('#atlas-language').selectOption(lang); await page.locator('#project-operations-open').click();
        await frame.waitForFunction(lang => document.getElementById('language').value === lang, lang);
        assert(await panel.locator('#new-project').isVisible());
      }
      savedDocument = await frame.evaluate(() => {window.presentationMarker = 'retained'; return document.querySelector('#create-card').outerHTML;});
      await page.locator('#project-operations-close').click(); await page.locator('#atlas-language').selectOption('zh-Hans'); await page.locator('#project-operations-open').click();
      await shot(page, 'v6-additive-operations');
    });
    await check('closing and reopening retains graph and operation document without dispatch', async () => {
      await page.locator('#project-operations-close').click();
      await page.evaluate(() => {window.retainedGraph = document.getElementById('atlas-network');});
      await page.locator('#project-operations-open').click();
      const frame = page.frames().find(f => f.url().endsWith('/projects-panel.html'));
      assert.equal(await frame.evaluate(() => window.presentationMarker), 'retained');
      assert(await page.evaluate(() => window.retainedGraph === document.getElementById('atlas-network'))); assert(savedDocument.length > 0); assert.equal(posts.length, 0);
    });
    await check('saved-view panel link navigates main UI rather than blocked frame', async () => {
      const panel = page.frameLocator('#project-operations-frame');
      await panel.locator('#view-list a').first().click(); await page.waitForURL('**/views/stage1-original-r3/atlas.html');
      await page.locator('#atlas-network').waitFor(); assert.equal(await page.locator('#project-operations-frame').count(), 0);
      assert.equal(posts.length, 0); assert.deepEqual(pageErrors, []);
    });
  } catch (e) {failure = e.stack;}
  finally {
    clearTimeout(timer);
    if (browser) try {await browser.close();} catch (e) {cleanup.push(e.message);}
    if (!exited) fs.appendFileSync(control, JSON.stringify({op: 'stop'}) + '\n');
    let limit; await Promise.race([finished, new Promise(resolve => {limit = setTimeout(() => {cleanup.push('fixture cleanup timeout'); child.kill(); resolve();}, 5000);})]); clearTimeout(limit);
    const receipt = {kind: 'PreservedV6BrowserCheck', passed: !failure && !cleanup.length && exitCode === 0 && stderr === '' && !pageErrors.length, checks, failure, cleanup, exitCode, stderr, pageErrors, post_count: posts.length, source_sha256: ready?.source_sha256, served_sha256: ready?.served_sha256, screenshots, actual_model_search_calls: 0, views_config_sha256: args['views-sha256'] || null};
    fs.writeFileSync(args.output, JSON.stringify(receipt, null, 2) + '\n', {flag: 'wx'});
    console.log(JSON.stringify({passed: receipt.passed, checks: checks.length, post_count: posts.length, exitCode, failure, output: args.output}));
    if (!receipt.passed) process.exitCode = 1;
  }
})();
