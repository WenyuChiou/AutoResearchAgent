/* Installed Chrome, real local HTTP/SQLite/Core delivery; no research run. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path');
const {spawn} = require('node:child_process');
const {createHash, randomUUID} = require('node:crypto');
const args = Object.fromEntries(process.argv.slice(2).reduce((rows, value, index, all) => index % 2 ? rows : [...rows, [value.slice(2), all[index + 1]]], []));
for (const name of ['repo', 'python', 'temp-root', 'output', 'playwright', 'chrome']) assert(path.isAbsolute(args[name]), name);
const {chromium} = require(args.playwright);
const {PNG} = require(path.join(path.dirname(args.playwright), 'pngjs'));
const sha = raw => createHash('sha256').update(raw).digest('hex');
const privateRoot = path.join(args['temp-root'], 'unified-' + randomUUID());
fs.mkdirSync(privateRoot);
const stop = path.join(privateRoot, 'stop');
const processFixture = spawn(args.python, ['-B', '-X', 'utf8', path.join(args.repo, 'plugins/auto-research-agent/tests/project_unified_browser_fixture.py'), '--stop-file', stop], {
  stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true,
  env: {...process.env, TEMP: args['temp-root'], TMP: args['temp-root'], TMPDIR: args['temp-root']}
});
let stdout = '', stderr = '', fixture, finalFixture, exited = false, exitCode;
let resolveReady, rejectReady;
const ready = new Promise((resolve, reject) => {resolveReady = resolve; rejectReady = reject;});
processFixture.stdout.on('data', raw => {
  stdout += raw;
  for (const line of stdout.trim().split('\n')) {
    try {
      const item = JSON.parse(line);
      if (item.kind === 'UnifiedProjectBrowserFixture') {fixture = item; resolveReady(item);}
      if (item.kind === 'UnifiedProjectBrowserFixtureStopped') finalFixture = item;
    } catch (_) { /* A partial JSON line is completed on the next event. */ }
  }
});
processFixture.stderr.on('data', raw => {stderr += raw;});
const finished = new Promise(resolve => processFixture.once('exit', code => {
  exited = true; exitCode = code; rejectReady(Error('local fixture exited before readiness')); resolve();
}));
processFixture.once('error', rejectReady);
const checks = [], errors = [], posts = [], external = [], screenshots = [], cleanup = [], downloads = [], renderedGraphs = [], contracts = [], contractReads = [];
let browser, page, secret = '', failure = null, startupTimer;
async function check(name, action) {await action(); checks.push(name);}
async function shot(name) {
  const file = path.join(path.dirname(args.output), name + '.png');
  assert(!fs.existsSync(file), 'fresh screenshot output');
  await page.screenshot({path: file, fullPage: true});
  screenshots.push({path: file, sha256: sha(fs.readFileSync(file)), viewport: page.viewportSize()});
}
async function renderedGraph(child, project, mode, suffix = '') {
  const canvas = child.locator('.atlas-spatial-canvas canvas');
  await canvas.scrollIntoViewIfNeeded();
  await child.waitForFunction(mode => {
    const value = document.querySelector('.atlas-spatial-host')?.atlasDiagnostics?.();
    return value?.mode === mode && value.lifecycle.intersecting && value.papers === 1 && value.symbolRects.length > 0 && !value.faults.length;
  }, mode);
  let raw, colored = 0;
  for (let attempt = 0; attempt < 6 && colored < 32; attempt++) {
    await child.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    raw = await canvas.screenshot();
    const png = PNG.sync.read(raw);
    colored = 0;
    for (let index = 0; index < png.data.length; index += 4) {
      if (png.data[index] > 60 || png.data[index + 1] > 60 || png.data[index + 2] > 80) colored++;
    }
  }
  assert(colored >= 32, 'actual WebGL canvas must contain rendered paper pixels');
  const name = 'unified-alpha-rendered-' + mode + 'd' + suffix + '.png', file = path.join(path.dirname(args.output), name);
  fs.writeFileSync(file, raw, {flag: 'wx'});
  const diagnostics = await child.evaluate(() => document.querySelector('.atlas-spatial-host').atlasDiagnostics());
  renderedGraphs.push({project_ref: project.project_ref, work_id: project.work_id, mode, rendered_colored_pixels: colored, diagnostics});
  screenshots.push({path: file, sha256: sha(raw), viewport: page.viewportSize(), capture: 'actual-WebGL-canvas'});
}
async function operationFrame() {
  await page.locator('#project-operations-frame').waitFor();
  const handle = await page.locator('#project-operations-frame').elementHandle();
  return handle.contentFrame();
}
async function atlasFrame(operation) {
  await operation.waitForFunction(() => Boolean(document.querySelector('#project-atlas-frame')?.contentWindow));
  const handle = await operation.locator('#project-atlas-frame').elementHandle();
  const child = await handle.contentFrame();
  await child.waitForFunction(() => Boolean(window.WORKSPACE_VIEW?.index && document.querySelector('#atlas-network')));
  return child;
}
async function selectProject(project, expectResult = true) {
  await page.locator('#project-intake-choice').selectOption(project.project_ref);
  await page.locator('#project-intake-select').click();
  const operation = await operationFrame();
  await operation.waitForFunction(ref => window.ResearchProjectPortal.selection()?.project_ref === ref && document.querySelector('#stage1-progress')?.dataset.projectRef === ref, project.project_ref);
  await operation.locator('#project-stage-nav-1').click();
  assert.equal(await operation.locator('#project-heading').textContent(), project.topic);
  assert.equal(await operation.locator('#stage1-progress').getAttribute('data-input-version'), String(project.input_version));
  assert.equal(await operation.locator('#stage1-progress .progress-phases li').count(), 7);
  if (!expectResult) return operation;
  const child = await atlasFrame(operation);
  await child.waitForFunction(topic => document.querySelector('#atlas-project')?.textContent === topic, project.topic);
  assert.equal(await child.locator('#atlas-project').textContent(), project.topic);
  const content = await child.evaluate(() => ({topic: window.WORKSPACE_VIEW.index.topic, papers: window.WORKSPACE_VIEW.index.papers.map(row => ({title: row.title, work_id: row.work_id})), identity: document.querySelector('#project-atlas-status').textContent}));
  assert.deepEqual(content.papers, [{title: project.title, work_id: project.work_id}]);
  assert(content.identity.includes(project.project_ref));
  assert(content.identity.includes(String(project.input_version)));
  assert.equal(await operation.locator('#project-atlas-inline > #project-atlas-frame').count(), 1);
  assert.equal(await child.locator('#atlas-stages button').count(), 6);
  return {operation, child};
}
(async () => {
  try {
    await Promise.race([ready, new Promise((_, reject) => {startupTimer = setTimeout(() => reject(Error('fixture startup timeout')), 60000);})]);
    clearTimeout(startupTimer);
    const origin = new URL(fixture.url).origin;
    browser = await chromium.launch({executablePath: args.chrome, headless: true, args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader']});
    const context = await browser.newContext({viewport: {width: 1600, height: 1100}, deviceScaleFactor: 1});
    await context.route('**/*', async route => {
      const url = new URL(route.request().url());
      if (url.origin !== origin && !['data:', 'blob:'].includes(url.protocol)) {external.push(url.origin + url.pathname); await route.abort();}
      else await route.continue();
    });
    context.on('page', item => item.on('pageerror', error => errors.push(error.message)));
    context.on('request', request => {if (request.method() === 'POST') posts.push(new URL(request.url()).pathname);});
    context.on('response', response => {
      const route = new URL(response.url()).pathname;
      if (!/^\/api\/projects\/[A-Za-z0-9_-]+\/contract$/.test(route)) return;
      contractReads.push(response.json().then(value => {
        contracts.push({path: route, method: response.request().method(), status: response.status(), identity: value.identity,
          stages: Object.fromEntries(Object.entries(value.stages || {}).map(([number, stage]) => [number, {input: stage.input, status: stage.status, connected: stage.connected, accepted: stage.accepted, execution_authorized: stage.execution_authorized}]))});
      }).catch(error => {errors.push('saved stage contract read failed: ' + error.message);}));
    });
    page = await context.newPage();
    await check('unselected shell hides unrelated historic result and opens no popup', async () => {
      const response = await page.goto(fixture.url); assert.equal(response.status(), 200);
      await page.waitForFunction(() => document.querySelectorAll('#project-intake-choice option').length === 5);
      assert.equal(await page.locator('#atlas-content').isVisible(), false);
      assert.equal(await page.locator('#project-operations-frame').count(), 1);
      assert.equal(context.pages().length, 1);
      const operation = await operationFrame();
      secret = await operation.evaluate(() => window.RESEARCH_PROJECTS.credential);
      assert(secret.length >= 32);
      assert.equal(await operation.locator('#project-atlas-frame').count(), 0);
    });
    const [alpha, beta, empty, scope] = fixture.projects;
    await check('top selector switches operations, progress, graph and saved paper identities', async () => {
      await selectProject(alpha); await selectProject(beta); await selectProject(alpha);
      assert.equal(await page.locator('#atlas-content').isVisible(), false);
      assert.equal(context.pages().length, 1);
      await shot('unified-desktop');
    });
    await check('late saved result and retired child message cannot overwrite new project', async () => {
      await selectProject(beta);
      const operation = await operationFrame();
      await operation.evaluate(() => {window.__retiredAtlasWindow = document.querySelector('#project-atlas-frame').contentWindow;});
      let release, delayedSeen, fulfilled;
      const delayed = new Promise(resolve => {delayedSeen = resolve;});
      const gate = new Promise(resolve => {release = resolve;});
      const completed = new Promise(resolve => {fulfilled = resolve;});
      const pattern = '**/api/projects/' + alpha.project_ref + '/stage1/atlas/**';
      await context.route(pattern, async route => {
        const response = await route.fetch(); delayedSeen(); await gate;
        await route.fulfill({response}); fulfilled();
      });
      await page.locator('#project-intake-choice').selectOption(alpha.project_ref);
      await page.locator('#project-intake-select').click();
      await delayed;
      const active = await selectProject(beta);
      release(); await completed; await context.unroute(pattern);
      await operation.evaluate(() => window.dispatchEvent(new MessageEvent('message', {origin: location.origin, source: window.__retiredAtlasWindow, data: {kind: 'project-atlas-ready'}})));
      await active.child.waitForFunction(topic => document.querySelector('#atlas-project').textContent === topic, beta.topic);
      assert.equal(await active.child.locator('#atlas-project').textContent(), beta.topic);
      assert.equal(await operation.locator('#project-atlas-frame').count(), 1);
    });
    await check('empty project and known scope version without result clear saved graphs', async () => {
      for (const project of [empty, scope]) {
        const operation = await selectProject(project, false);
        await operation.waitForFunction(() => document.querySelector('#project-atlas-result-notice')?.textContent.length > 0);
        assert.equal(await operation.locator('#project-atlas-frame').count(), 0);
        assert(await operation.locator('#project-atlas-result-notice').isVisible());
        assert.match(await operation.locator('#project-atlas-result-notice').textContent(), /not generated|no validated saved|尚未生成|尚未產生|尚未产生/i);
        assert.equal(await page.locator('#atlas-content').isVisible(), false);
      }
      assert.equal(scope.input_version, 2);
      await shot('unified-empty-scope');
    });
    await check('EN, simplified and traditional Chinese propagate through inline graph', async () => {
      await selectProject(beta);
      const heading = {en: 'Current progress', 'zh-Hans': '当前进度', 'zh-Hant': '目前進度'};
      for (const language of ['en', 'zh-Hans', 'zh-Hant']) {
        await page.locator('#atlas-language').selectOption(language);
        const operation = await operationFrame();
        await operation.waitForFunction(value => document.querySelector('#language').value === value, language);
        const child = await atlasFrame(operation);
        await child.waitForFunction(value => document.querySelector('#atlas-language').value === value, language);
        assert((await operation.locator('#stage1-progress h2').textContent()).includes(heading[language]));
        assert.equal(await child.locator('#atlas-project').textContent(), beta.topic);
        await shot('unified-language-' + language);
      }
    });
    await check('six sidebar and portal stage transitions retain current contract and Stage1 graph in three languages', async () => {
      const {operation, child} = await selectProject(alpha);
      await operation.evaluate(() => {window.__retainedAtlasFrame = document.querySelector('#project-atlas-frame'); window.__retainedAtlasWindow = window.__retainedAtlasFrame.contentWindow;});
      const names = {
        en: ['Literature & evidence', 'Comparison & research directions', 'Research design & feasibility', 'Experiment execution', 'Analysis & figures', 'Writing & submission'],
        'zh-Hans': ['文献与证据', '比较与研究方向', '研究设计与可行性', '实验执行', '分析与图表', '写作与投稿'],
        'zh-Hant': ['文獻與證據', '比較與研究方向', '研究設計與可行性', '實驗執行', '分析與圖表', '寫作與投稿']
      };
      async function active(number, language) {
        await operation.waitForFunction(number => window.ResearchProjectPortal.activeStage() === number && document.querySelectorAll('[data-project-stage]:not([hidden])').length === 1 && !document.getElementById('project-stage-' + number).hidden, number);
        assert.equal(await operation.locator('#project-stage-' + number + '-title').textContent(), names[language][number - 1]);
        assert.equal(await operation.locator('#project-stage-nav-' + number).getAttribute('aria-current'), 'step');
        assert.equal(await page.locator('#atlas-stages [data-atlas-focus="stage:' + number + '"]').getAttribute('aria-pressed'), 'true');
        assert.equal(await operation.locator('#project-stage-' + number + '-status').getAttribute('data-project-ref'), alpha.project_ref);
        assert.equal(await operation.locator('#project-stage-' + number + '-status').getAttribute('data-input-version'), String(alpha.input_version));
        const saved = JSON.parse(await operation.locator('#project-stage-' + number + '-status pre').textContent());
        for (const key of ['project_ref', 'input_version', 'revision']) assert.equal(saved.input[key], alpha[key]);
        assert.match(saved.input.brief_sha256, /^[a-f0-9]{64}$/);
        assert.equal(await operation.evaluate(() => document.querySelector('#project-atlas-frame') === window.__retainedAtlasFrame && document.querySelector('#project-atlas-frame').contentWindow === window.__retainedAtlasWindow), true);
        if (number === 2) {
          await operation.locator('#project-stage-2 #stage2-input-entry form').waitFor({state: 'visible'});
          assert.equal(await operation.locator('#project-stage-1 #stage2-input-entry').count(), 0);
          assert((await operation.locator('#stage2-input-entry').textContent()).includes(alpha.title));
          assert.equal(await operation.locator('#project-stage-2 #activate-stage2').isDisabled(), true);
          assert.match(await operation.locator('#project-stage-2-result-state').textContent(), /Not generated|尚未生成|尚未產生/);
          assert.equal(await operation.locator('#stage1-progress').isVisible(), false);
        }
        if (number >= 3) {
          assert.match(await operation.locator('#project-stage-' + number + '-status').textContent(), /Planned|已规划|已規劃/);
          assert.match(await operation.locator('#project-stage-' + number + '-status').textContent(), /Unconnected|未接通/);
          assert.match(await operation.locator('#project-stage-' + number + '-result-state').textContent(), /Not generated|尚未生成|尚未產生/);
          assert.equal(await operation.locator('#project-stage-' + number + '-unconnected').isDisabled(), true);
          assert.deepEqual(saved.artifacts, []);
          assert.deepEqual(saved.attempts, []);
          assert.equal(await operation.locator('#project-stage-' + number + '-operations #stage2-input-entry').count(), 0);
        }
      }
      for (const language of ['en', 'zh-Hans', 'zh-Hant']) {
        await page.locator('#atlas-language').selectOption(language);
        await operation.waitForFunction(language => document.getElementById('language').value === language, language);
        for (let number = 1; number <= 6; number++) {
          await page.locator('#atlas-stages [data-atlas-focus="stage:' + number + '"]').click();
          await active(number, language);
          await operation.locator('#project-stage-nav-' + (7 - number)).click();
          await active(7 - number, language);
        }
        await operation.locator('#project-stage-nav-2').click(); await active(2, language);
        await shot('unified-stage2-' + language);
        await operation.locator('#project-stage-nav-6').click(); await active(6, language);
        await shot('unified-stage6-' + language);
      }
      await page.locator('#project-historical-view > summary').click();
      await page.waitForFunction(() => document.getElementById('project-historical-view').open);
      await page.locator('#atlas-stages [data-atlas-focus="stage:2"]').click();
      assert.equal(await operation.evaluate(() => window.ResearchProjectPortal.activeStage()), 6);
      await page.locator('#project-historical-view > summary').click();
      await page.waitForFunction(() => !document.getElementById('project-historical-view').open && document.querySelector('#atlas-stages [data-atlas-focus="stage:6"]')?.getAttribute('aria-pressed') === 'true');
      await active(6, 'zh-Hant');
      assert.equal(await page.locator('#atlas-project').textContent(), alpha.topic);
      assert.equal(await operation.evaluate(() => window.ResearchProjectPortal.showStage(2)), true);
      await active(2, 'zh-Hant');
      const note = operation.locator('#stage2-input-entry form textarea');
      await note.fill('Unsaved input-review note must survive stage navigation.');
      await page.locator('#atlas-stages [data-atlas-focus="stage:1"]').click(); await active(1, 'zh-Hant');
      await operation.locator('#project-stage-nav-2').click(); await active(2, 'zh-Hant');
      assert.equal(await note.inputValue(), 'Unsaved input-review note must survive stage navigation.');
      await operation.locator('#project-stage-nav-1').click(); await active(1, 'zh-Hant');
      assert.equal(await child.locator('#atlas-project').textContent(), alpha.topic);
      assert.equal(posts.length, 0);
    });
    await check('Stage2 saved input switches project identity without adopting an earlier review', async () => {
      const {operation} = await selectProject(alpha);
      await operation.locator('#project-stage-nav-2').click();
      await operation.locator('#stage2-input-entry form').waitFor({state: 'visible'});
      await page.locator('#project-intake-choice').selectOption(beta.project_ref);
      await page.locator('#project-intake-select').click();
      await operation.waitForFunction(ref => window.ResearchProjectPortal.selection()?.project_ref === ref, beta.project_ref);
      assert.equal(await operation.evaluate(() => window.ResearchProjectPortal.activeStage()), 2);
      await operation.waitForFunction(title => document.querySelector('#stage2-input-entry form') && document.querySelector('#stage2-input-entry').textContent.includes(title), beta.title);
      assert.equal((await operation.locator('#stage2-input-entry').textContent()).includes(alpha.title), false);
      assert.equal(await operation.locator('#project-stage-2-status').getAttribute('data-project-ref'), beta.project_ref);
      assert.equal(await operation.locator('#stage2-input-entry form textarea').inputValue(), '');
      await operation.locator('#project-stage-nav-1').click();
      const child = await atlasFrame(operation);
      await child.waitForFunction(topic => document.getElementById('atlas-project').textContent === topic, beta.topic);
      assert.equal(posts.length, 0);
    });
    await check('saved source links, review draft and file read stay bound and GET only', async () => {
      const catalogRead = page.waitForResponse(response => response.url().includes('/api/projects/' + alpha.project_ref + '/stage1/atlas/') && !response.url().includes('/files/') && response.status() === 200);
      const {operation, child} = await selectProject(alpha);
      const catalog = await (await catalogRead).json();
      await child.locator('#atlas-library summary').click();
      await child.locator('.atlas-paper').first().click();
      assert((await child.locator('#atlas-paper-detail').textContent()).includes(alpha.title));
      assert(await child.locator('#atlas-paper-detail a[href="https://example.org/study"]').count() > 0);
      await child.locator('#atlas-review-note').fill('Local UI regression review · 请保留来源与未知事项');
      await child.locator('#atlas-review-prepare').click();
      const draft = await child.locator('#atlas-review-draft').inputValue();
      assert(draft.includes(alpha.topic));
      assert.match(draft, /WorkspaceIndex SHA-256: [a-f0-9]{64}/);
      assert(!draft.includes(secret));
      for (const [file, selector] of [
        [catalog.files.find(row => row.path === 'references.bib'), '#atlas-exports a[href$="references.bib"]'],
        [catalog.files.find(row => row.path.startsWith('wiki/')), '#atlas-paper-detail a[href*="wiki/"]']
      ]) {
        assert(file, 'bound saved file exists');
        const [response, result] = await Promise.all([
          page.waitForResponse(response => response.url().endsWith('/files/' + file.file_ref + '/' + file.sha256)),
          page.waitForEvent('download'), child.locator(selector).click()
        ]);
        assert.equal(response.status(), 200);
        const reply = await response.json();
        assert.equal(reply.project_ref, alpha.project_ref);
        assert.equal(reply.artifact_ref, alpha.artifact_ref);
        assert.equal(reply.manifest_sha256, alpha.manifest_sha256);
        assert.equal(reply.file.sha256, file.sha256);
        assert.equal(sha(Buffer.from(reply.file.content, 'utf8')), file.sha256);
        const filename = path.basename(file.path), destination = path.join(path.dirname(args.output), filename);
        assert.equal(result.suggestedFilename(), filename);
        await result.saveAs(destination);
        assert.equal(sha(fs.readFileSync(destination)), file.sha256);
        downloads.push({path: file.path, sha256: file.sha256, downloaded_path: destination, actual_get_status: response.status()});
      }
      const before = await child.locator('#atlas-project').textContent();
      await child.evaluate(() => location.reload());
      const refreshed = await atlasFrame(operation);
      await refreshed.waitForFunction(topic => document.querySelector('#atlas-project').textContent === topic, before);
      await operation.locator('#refresh').click();
      await selectProject(alpha);
      assert.equal(posts.length, 0);
    });
    await check('desktop, tablet and narrow layouts retain long content and usable inline graph', async () => {
      for (const width of [1600, 1024, 390]) {
        await page.setViewportSize({width, height: width === 1600 ? 1100 : 844});
        const {operation, child} = await selectProject(beta);
        for (const [frame, selector] of [[page, '#project-intake-card'], [operation, '#stage1-progress'], [operation, '#project-atlas-inline'], [child, '#atlas-network']]) {
          const bounds = await frame.locator(selector).evaluate(element => ({scroll: element.scrollWidth, client: element.clientWidth, right: element.getBoundingClientRect().right, width: innerWidth}));
          assert(bounds.scroll <= bounds.client + 2 && bounds.right <= bounds.width + 2, JSON.stringify({selector, width, bounds}));
        }
        assert(await operation.locator('#project-atlas-frame').evaluate(element => element.getBoundingClientRect().height >= 700));
        assert.equal(await page.locator('#project-operations-dialog[open]').count(), 0);
        await shot('unified-width-' + width);
        for (const number of [2, 6]) {
          await operation.locator('#project-stage-nav-' + number).click();
          for (const selector of ['#project-stage-navigation', '#project-stage-' + number, '#project-stage-' + number + '-status', '#project-stage-' + number + '-operations']) {
            const bounds = await operation.locator(selector).evaluate(element => ({scroll: element.scrollWidth, client: element.clientWidth, right: element.getBoundingClientRect().right, width: innerWidth}));
            assert(bounds.scroll <= bounds.client + 2 && bounds.right <= bounds.width + 2, JSON.stringify({selector, width, bounds}));
          }
          await shot('unified-width-' + width + '-stage' + number);
        }
        await operation.locator('#project-stage-nav-1').click();
      }
    });
    await check('default 3D canvas and 2D paper selection render the current saved work', async () => {
      await page.setViewportSize({width: 1600, height: 1100});
      const {child} = await selectProject(alpha);
      await renderedGraph(child, alpha, 3);
      await child.getByRole('button', {name: '2D', exact: true}).click();
      await child.locator('.atlas-spatial-controls label input').nth(1).check();
      await renderedGraph(child, alpha, 2);
      await child.locator('.atlas-spatial-paper[data-node-kind="paper"]').first().click();
      await child.waitForFunction(work => document.querySelector('.atlas-spatial-host')?.atlasDiagnostics?.().focus?.key.includes(work), alpha.work_id);
      assert((await child.locator('#atlas-paper-detail').textContent()).includes(alpha.title));
      assert((await child.locator('#atlas-paper-detail').textContent()).includes(alpha.work_id));
      assert.equal(await child.locator('.atlas-spatial svg').count(), 1, 'v6 SVG edge overlay accompanies the actual WebGL 2D view');
      await renderedGraph(child, alpha, 2, '-selected');
      await shot('unified-alpha-desktop-2d-selected');
    });
    await check('credentials remain out of child, URL, storage and receipt', async () => {
      const operation = await operationFrame(), child = await atlasFrame(operation);
      assert.equal(await child.evaluate(() => Boolean(window.RESEARCH_PROJECTS || window.RESEARCH_HOST?.credential)), false);
      for (const frame of page.frames()) {
        assert(!frame.url().includes(secret));
        assert.equal(await frame.evaluate(secret => [...Object.values(localStorage), ...Object.values(sessionStorage)].some(value => value.includes(secret)), secret), false);
      }
      assert.equal(posts.length, 0); assert.deepEqual(external, []); assert.deepEqual(errors, []);
      assert.equal(context.pages().length, 1);
      await Promise.all(contractReads);
      assert(contracts.length > 0, 'actual project contract GETs observed');
      for (const contract of contracts) {
        assert.equal(contract.method, 'GET'); assert.equal(contract.status, 200);
        assert.deepEqual(Object.keys(contract.stages), ['1', '2', '3', '4', '5', '6']);
        for (const stage of Object.values(contract.stages)) assert.deepEqual(stage.input, contract.identity);
      }
    });
  } catch (error) {
    failure = error.stack;
    if (page && !page.isClosed()) try {await shot('unified-failure');} catch (_) { /* Preserve the primary failure. */ }
  } finally {
    clearTimeout(startupTimer);
    if (browser) try {await browser.close();} catch (error) {cleanup.push(error.message);}
    if (!exited) fs.writeFileSync(stop, 'stop\n', {flag: 'wx'});
    let timer;
    await Promise.race([finished, new Promise(resolve => {timer = setTimeout(() => {cleanup.push('fixture cleanup timeout'); processFixture.kill(); resolve();}, 5000);})]);
    clearTimeout(timer);
    const receipt = {
      kind: 'UnifiedProjectBrowserCheck',
      passed: !failure && !cleanup.length && exitCode === 0 && !stderr && !errors.length,
      checks, failure, cleanup, exitCode, stderr, pageErrors: errors,
      post_count: posts.length, post_paths: posts, external_requests: external,
      source_inventory: fixture?.source_inventory, fixture_final: finalFixture,
      screenshots, downloads, renderedGraphs, contracts, scope: 'authored-saved-result-engineering-only',
    };
    const raw = JSON.stringify(receipt, null, 2) + '\n';
    assert(!secret || !raw.includes(secret), 'receipt credential leak');
    fs.writeFileSync(args.output, raw, {flag: 'wx'});
    console.log(JSON.stringify({passed: receipt.passed, checks: checks.length, post_count: posts.length, failure, output: args.output}));
    if (!receipt.passed) process.exitCode = 1;
  }
})();
