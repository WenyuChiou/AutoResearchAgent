/* Current raw UI assets in installed Chrome; every API response is synthetic.
 * No core host, research runtime, Codex, model, source fetch or search runs. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {createHash, randomUUID} = require('node:crypto');

const options = {};
for (let i = 2; i < process.argv.length; i += 2) {
  const flag = process.argv[i], value = process.argv[i + 1];
  if (!/^--(repo|playwright|browser|output)$/.test(flag) || !value || options[flag.slice(2)])
    throw Error('one value per known flag required');
  options[flag.slice(2)] = value;
}
for (const name of ['repo', 'playwright', 'browser', 'output'])
  if (!options[name] || !path.isAbsolute(options[name])) throw Error('absolute --' + name + ' required');
const repo = fs.realpathSync(options.repo), plugin = path.join(repo, 'plugins', 'auto-research-agent');
if (fs.realpathSync(__filename) !== path.join(plugin, 'tests', 'test_project_query_panel_browser.cjs'))
  throw Error('driver must belong to the sole candidate');
if (fs.existsSync(options.output)) throw Error('existing evidence must never be overwritten');
fs.mkdirSync(path.dirname(options.output), {recursive: true});
const sha = raw => createHash('sha256').update(raw).digest('hex');
const files = ['projects.html', 'projects.js', 'projects.css'].map(name =>
  path.join(plugin, 'cli', 'research_workspace_native', 'web', name));
const sourceBefore = Object.fromEntries([...files, __filename].map(file => [path.relative(repo, file).replaceAll('\\', '/'), sha(fs.readFileSync(file))]));
const assets = Object.fromEntries(files.map(file => ['/' + path.basename(file), fs.readFileSync(file)]));
const origin = 'http://127.0.0.1:47619', ref = 'project-query-ui-fixture', runId = randomUUID();
const buttons = ['query-authorize', 'query-bootstrap', 'query-execute', 'query-restore-owner'];
const fields = ['authorization_offer', 'bootstrap_offer', 'query_offer', 'owner_offer'];
const operations = ['authorize', 'bootstrap', 'execute', 'restore-owner'];
const results = [], screenshots = [], pageErrors = [], routeErrors = [], outbound = [], requests = [];
let browser, context, page, browserVersion, failure;
const project = {
  project_ref: ref, project_id: ref, revision: 4, input_version: 1, brief_sha256: 'a'.repeat(64),
  brief: {original_description: 'Synthetic query UI fixture · No research calls', needs: [{question: 'Test saved UI observations only.'}]},
  intake_report: {necessary_clarification_complete: true}, plan: {execution_status: 'not-executed'},
  settings: {resource_envelope: 'Fixture only', user_input: 'No actual execution',
    budgets: {model_calls: 0, seconds: 94, search_calls: 2, source_reads: 0, rounds: 0},
    consent: {external_search: true, public_source_read: false}},
};
const limits = {max_attempts: 2, max_reserved_seconds: 94, max_results: 3};
const offer = index => ({offer_ref: 'opaque-offer-' + index, offer_sha256: String(index + 1).repeat(64),
  document: {...(index === 0 ? {limits} : {}), backend: 'openalex', planned_id: 'opaque-planned',
    arguments: {query: '<img src=x onerror="window.__injected=true"> fixture query'}}});
const queryView = selected => ({status: 'synthetic-query-history', limits,
  budget: {attempts: 1, seconds: 62, probes: 1},
  ...Object.fromEntries(fields.map((field, index) => [field, selected === 'all' || selected === index ? offer(index) : null])),
  jobs: [{operation: 'bootstrap', status: 'execution-unknown', error: {code: 'fixture-probe-unknown'}}],
  query_history: {history: [{operation: 'backend', status: 'failed', result: {outcome: 'fixture-network-error'}}]},
});
let view = null, actions = [], posts = [], loseResponse = false;

async function check(name, operation) {
  try {await operation(); results.push({name, status: 'passed'});}
  catch (error) {results.push({name, status: 'failed', error: error.stack}); throw error;}
}
async function screenshot(label, panel = true) {
  const file = path.join(path.dirname(options.output), 'query-' + label + '-' + runId + '.png');
  if (fs.existsSync(file)) throw Error('screenshot collision');
  const target = panel ? page.locator('section').filter({has: page.locator('#query-state')}) : page;
  await target.screenshot({path: file, ...(panel ? {} : {fullPage: true})});
  screenshots.push({label, path: file, sha256: sha(fs.readFileSync(file))});
}
async function open(selected, viewport = {width: 1440, height: 960}) {
  if (context) await context.close();
  view = selected === null ? null : queryView(selected); actions = []; posts = []; loseResponse = false;
  context = await browser.newContext({viewport});
  context.setDefaultTimeout(8000);
  await context.addInitScript(() => {
    window.__uiPosts = [];
    const original = window.fetch;
    window.fetch = (url, options) => {
      if (options && options.method === 'POST') window.__uiPosts.push({url,
        body: JSON.parse(options.body), intents: JSON.parse(sessionStorage.getItem('harness-project-ui-intents-v1') || '[]')});
      return original(url, options);
    };
  });
  await context.route('**/*', async route => {
    try {
      const request = route.request(), url = new URL(request.url());
      if (url.origin !== origin) {outbound.push(url.origin); return route.abort();}
      if (url.pathname === '/' || assets[url.pathname]) {
        const name = url.pathname === '/' ? '/projects.html' : url.pathname;
        return route.fulfill({status: 200, body: assets[name], contentType:
          name.endsWith('.html') ? 'text/html' : name.endsWith('.css') ? 'text/css' : 'text/javascript'});
      }
      if (url.pathname === '/project-bootstrap.js') return route.fulfill({status: 200, contentType: 'text/javascript',
        body: 'window.RESEARCH_PROJECTS=' + JSON.stringify({credential: 'explicit-fake-ui-token', views: [], models: false, stage1: true, stage2: false}) + ';'});
      if (url.pathname.startsWith('/api/')) requests.push({method: request.method(), path: url.pathname,
        ...(request.method() === 'POST' ? {body: request.postDataJSON()} : {})});
      if (request.method() === 'POST') {
        const body = request.postDataJSON(), operation = url.pathname.split('/').at(-1);
        assert.equal(url.pathname, '/api/projects/' + ref + '/stage1/' + operation);
        assert.ok(operations.some(value => operation === 'query-' + value));
        posts.push({path: url.pathname, body});
        if (loseResponse) return route.abort('failed');
        return route.fulfill({status: 200, json: {status: 'saved', query_status: 'fixture-intent-recorded-not-executed'}});
      }
      if (url.pathname === '/api/projects') return route.fulfill({status: 200, json: {projects: [project]}});
      if (url.pathname.endsWith('/overview')) return route.fulfill({status: 200, json: {project, models: null, model_offers: [], stage2: null,
        stage1: {stage1_status: 'saved-fixture-not-research-complete', ledger: null, queries: [], query_execution: view, delivery: {offers: []}}}});
      if (url.pathname.endsWith('/models/native')) return route.fulfill({status: 200, json: {native_view: null, native_actions: []}});
      if (url.pathname.endsWith('/history')) return route.fulfill({status: 200, json: {actions}});
      if (url.pathname.startsWith('/api/')) return route.fulfill({status: 200, json: {actions: [], next_offset: null}});
      return route.fulfill({status: 404, body: ''});
    } catch (error) {routeErrors.push(error.stack); return route.fulfill({status: 500, json: {error: 'fixture-route-failed'}});}
  });
  page = await context.newPage();
  page.on('pageerror', error => pageErrors.push(error.message));
  await page.goto(origin + '/');
  await page.locator('#project-list button').click();
  await page.waitForFunction(() => !document.querySelector('#native-refresh').disabled);
}
async function refresh() {
  await page.evaluate(() => {document.querySelector('#notice').textContent = 'fixture refresh pending';});
  await page.locator('#refresh').click();
  await page.waitForFunction(() => document.querySelector('#notice').textContent ===
    'Saved history loaded. Any unknown action remains unknown.' && !document.querySelector('#native-refresh').disabled);
}
const intents = () => page.evaluate(() => JSON.parse(sessionStorage.getItem('harness-project-ui-intents-v1') || '[]'));

(async () => {
  const {chromium} = require(options.playwright);
  browser = await chromium.launch({executablePath: options.browser, headless: true, chromiumSandbox: true});
  browserVersion = browser.version();
  await check('unregistered query service disables all four actions', async () => {
    await open(null);
    for (const id of buttons) assert.equal(await page.locator('#' + id).isDisabled(), true);
    assert.match(await page.locator('#query-state').innerText(), /No search runtime is registered/);
    assert.equal(posts.length, 0);
  });
  await check('three languages render real raw panel with preserved synthetic failures', async () => {
    await open('all');
    const expected = {en: ['Authorize these search limits', 'Initialize the search runtime', 'Execute the offered query', 'Restore saved ledger ownership'],
      'zh-Hans': ['授权此搜索范围与限额', '初始化搜索运行时', '执行当前查询', '恢复保存记录的写入控制'],
      'zh-Hant': ['授權此搜尋範圍與限額', '初始化搜尋執行環境', '執行目前查詢', '恢復保存紀錄的寫入控制']};
    for (const [language, labels] of Object.entries(expected)) {
      await page.locator('#language').selectOption(language);
      assert.equal(await page.locator('html').getAttribute('lang'), language);
      for (let i = 0; i < buttons.length; i++) {
        assert.equal(await page.locator('#' + buttons[i]).innerText(), labels[i]);
        assert.equal(await page.locator('#' + buttons[i]).isDisabled(), false);
      }
      const history = await page.locator('#query-observations').innerText();
      assert.match(history, /execution-unknown/); assert.match(history, /fixture-probe-unknown/);
      assert.match(history, /failed/); assert.match(history, /fixture-network-error/);
      assert.equal(await page.locator('#query-observations img').count(), 0);
      assert.equal(await page.evaluate(() => Boolean(window.__injected)), false);
      await screenshot(language);
    }
  });
  for (let index = 0; index < operations.length; index++) await check('opaque ' + operations[index] + ' action records intent before POST', async () => {
    await open(index);
    for (let i = 0; i < buttons.length; i++) assert.equal(await page.locator('#' + buttons[i]).isDisabled(), i !== index);
    if (!index) await page.locator('#query-consent').fill('Keep my exact scope confirmation. 搜索许可。');
    const nextOverview = page.waitForResponse(response => response.url().endsWith('/overview'));
    await page.locator('#' + buttons[index]).click();
    await nextOverview;
    await page.waitForFunction(() => window.__uiPosts.length === 1 && !document.querySelector('#native-refresh').disabled);
    const captured = await page.evaluate(() => window.__uiPosts[0]);
    assert.equal(posts.length, 1); assert.equal(captured.url, '/api/projects/' + ref + '/stage1/query-' + operations[index]);
    assert.deepEqual(Object.keys(captured.body).sort(), ['revision', 'input_version', 'brief_sha256', 'offer_ref', 'offer_sha256', 'confirmed', 'key', ...(!index ? ['user_input'] : [])].sort());
    assert.equal(captured.body.offer_ref, offer(index).offer_ref); assert.equal(captured.body.offer_sha256, offer(index).offer_sha256);
    assert.equal(captured.body.input_version, 1); assert.equal(captured.body.brief_sha256, project.brief_sha256); assert.equal(captured.body.confirmed, true);
    if (!index) assert.equal(captured.body.user_input, 'Keep my exact scope confirmation. 搜索许可。');
    const held = captured.intents.find(row => row.key === captured.body.key);
    assert.ok(held); assert.equal(held.project_ref, ref); assert.equal(held.kind, 'stage1-query-' + operations[index]);
    assert.match(held.request_sha256, /^[a-f0-9]{64}$/);
    const ordered = value => Array.isArray(value) ? value.map(ordered) : value && typeof value === 'object'
      ? Object.fromEntries(Object.keys(value).sort().map(key => [key, ordered(value[key])])) : value;
    const semantic = Object.fromEntries(Object.entries(captured.body).filter(([name]) => name !== 'revision'));
    assert.equal(held.request_sha256, sha(Buffer.from(JSON.stringify(ordered({kind: held.kind, body: semantic})))));
    assert.equal(await page.locator('#notice').innerText(), 'Action recorded. Read the execution history for its actual outcome.');
  });
  await check('lost query response survives reload and only exact GET history releases it', async () => {
    await open(2); loseResponse = true;
    await page.locator('#query-execute').click();
    await page.waitForFunction(() => document.querySelector('#notice').classList.contains('error'));
    const held = (await intents())[0]; assert.ok(held); assert.equal(posts.length, 1);
    actions = [{...held, status: 'saved', request_sha256: '0'.repeat(64)}];
    await refresh(); assert.equal((await intents()).length, 1); assert.equal(posts.length, 1);
    actions = [{...held, status: 'execution-unknown'}];
    await page.reload(); await page.locator('#project-list button').click();
    await page.waitForFunction(() => !document.querySelector('#native-refresh').disabled);
    assert.equal((await intents()).length, 1); assert.equal(posts.length, 1);
    for (const id of buttons) assert.equal(await page.locator('#' + id).isDisabled(), true);
    actions = [{...held, status: 'saved'}];
    await refresh(); assert.equal((await intents()).length, 0); assert.equal(posts.length, 1);
    await screenshot('response-loss-history');
  });
  await check('mobile simplified Chinese panel remains within viewport', async () => {
    await open('all', {width: 390, height: 844});
    await page.locator('#language').selectOption('zh-Hans');
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await screenshot('mobile-zh-Hans', false);
  });
  assert.deepEqual(routeErrors, []); assert.deepEqual(pageErrors, []); assert.deepEqual(outbound, []);
})().catch(error => {failure = error.stack;}).finally(async () => {
  try {if (context) await context.close(); if (browser) await browser.close();}
  catch (error) {failure = (failure || '') + '\ncleanup: ' + error.stack;}
  const sourceAfter = Object.fromEntries([...files, __filename].map(file => [path.relative(repo, file).replaceAll('\\', '/'), sha(fs.readFileSync(file))]));
  const receipt = {kind: 'SyntheticProjectQueryUiBrowserEvidence', status: failure ? 'failed' : 'passed', browser: browserVersion,
    run_id: runId, source_before: sourceBefore, source_after: sourceAfter, source_unchanged: JSON.stringify(sourceBefore) === JSON.stringify(sourceAfter),
    results, screenshots, api_requests: requests, page_errors: pageErrors, route_errors: routeErrors, outbound_requests: outbound, failure,
    actual_core_host: false, actual_runtime_probe: false, actual_native_model: false, actual_search: false,
    scope: 'Installed Chrome executes current raw UI assets. Every API response and project/permit/query/history observation is an authored fixture; no real service execution or scientific completion is demonstrated.'};
  fs.writeFileSync(options.output, JSON.stringify(receipt, null, 2) + '\n', {flag: 'wx'});
  console.log(JSON.stringify({status: receipt.status, tests: results.length, passed: results.filter(row => row.status === 'passed').length,
    source_unchanged: receipt.source_unchanged, output: options.output, failure}));
  process.exitCode = receipt.status === 'passed' ? 0 : 1;
});
