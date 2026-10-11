/* Installed Chrome with actual project HTTP/SQLite/Core and authored backend
 * output. No real search, source acquisition, native process or model call. */
'use strict';
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path');
const {spawn} = require('node:child_process'), readline = require('node:readline');
const {createHash, randomUUID} = require('node:crypto');
const options = {};
for (let i = 2; i < process.argv.length; i += 2) {
  const key = process.argv[i], value = process.argv[i + 1];
  if (!/^--(repo|python|playwright|browser|temp|output)$/.test(key) || !value || options[key.slice(2)]) throw Error('known flags required once');
  options[key.slice(2)] = value;
}
for (const key of ['repo', 'python', 'playwright', 'browser', 'temp', 'output']) if (!path.isAbsolute(options[key] || '')) throw Error('absolute ' + key + ' required');
const repo = fs.realpathSync(options.repo), plugin = path.join(repo, 'plugins/auto-research-agent');
if (fs.realpathSync(__filename) !== path.join(plugin, 'tests/test_project_expansion_browser.cjs')) throw Error('sole candidate driver required');
if (fs.existsSync(options.output)) throw Error('receipt must never be overwritten');
fs.mkdirSync(path.dirname(options.output), {recursive: true});
const control = path.join(options.temp, 'pex-control-' + randomUUID() + '.txt');
const sha = raw => createHash('sha256').update(raw).digest('hex');
const sources = {};
for (const dir of ['cli', 'schemas', 'references']) {
  const visit = root => {for (const item of fs.readdirSync(root, {withFileTypes: true})) {
    if (['__pycache__', '.ruff_cache', '.pytest_cache'].includes(item.name)) continue;
    const file = path.join(root, item.name);
    if (item.isDirectory()) visit(file); else if (item.isFile() && !/\.py[co]$/.test(file)) sources[path.relative(repo, file).replaceAll('\\', '/')] = sha(fs.readFileSync(file));
  }}; visit(path.join(plugin, dir));
}
for (const name of ['test_project_expansion_browser.cjs', 'project_expansion_browser_fixture.py', 'test_project_expansions.py', 'project_stage1_query_http_cases.py']) {
  const relative = 'plugins/auto-research-agent/tests/' + name; sources[relative] = sha(fs.readFileSync(path.join(repo, relative)));
}
const results = [], screenshots = [], pageErrors = [], diagnostics = [], requests = [], cleanup = [], queue = [], observations = [];
let child, browser, context, page, failure, stderr = '', browserVersion, metadata, exit;
const bounded = (promise, ms, name) => {
  let timer; return Promise.race([promise, new Promise((_, reject) => {timer = setTimeout(() => reject(Error(name + ' timeout')), ms);})]).finally(() => clearTimeout(timer));
};
async function inspect() {
  const reply = new Promise((resolve, reject) => queue.push({resolve, reject}));
  fs.appendFileSync(control, 'inspect\n'); const value = await bounded(reply, 35000, 'fixture inspect'); observations.push(value); return value;
}
async function check(name, fn) {
  try {await fn(); results.push({name, status: 'passed'});}
  catch (error) {results.push({name, status: 'failed', error: error.message}); throw error;}
}
async function choose(target) {
  await target.locator('#project-list button').first().click();
  await target.waitForFunction(() => document.querySelector('#expansion-panel button') && !document.querySelector('#refresh').disabled);
}
async function refresh() {
  // The production refresh control has no disabled/busy promise. Await its
  // actual registered handler rather than observing a transient empty render.
  await page.locator('#refresh').evaluate(async node => {
    if (node.disabled) throw Error('refresh disabled');
    await node.onclick(new Event('click'));
  });
  await page.getByRole('heading', {name: 'Saved citation actions', exact: true}).waitFor();
}
function card(operation, action) {
  const name = action === 'authorize' ? 'Authorize this citation attempt' : 'Execute this saved citation permission';
  return page.locator('#expansion-panel .history-row').filter({hasText: operation}).filter({has: page.getByRole('button', {name, exact: true})}).first();
}
async function authorize(operation) {
  const row = card(operation, 'authorize'), button = row.getByRole('button', {name: 'Authorize this citation attempt', exact: true});
  assert(await button.isDisabled()); await row.locator('input[type=checkbox]').check(); await button.click();
  await page.getByRole('button', {name: 'Execute this saved citation permission', exact: true}).first().waitFor();
}
async function shot(label) {
  const file = path.join(path.dirname(options.output), label + '.png');
  await page.locator('#expansion-panel').screenshot({path: file}); screenshots.push({label, file, sha256: sha(fs.readFileSync(file))});
}
async function main() {
  fs.writeFileSync(control, '', {flag: 'wx'});
  const ready = new Promise((resolve, reject) => {
    child = spawn(options.python, ['-I', '-B', '-X', 'utf8', path.join(plugin, 'tests/project_expansion_browser_fixture.py'), '--temp-root', options.temp, '--control-file', control], {
      cwd: repo, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'], env: {...process.env, TEMP: options.temp, TMP: options.temp, PYTHONDONTWRITEBYTECODE: '1'}
    });
    exit = new Promise(done => {child.once('exit', (code, signal) => {for (const item of queue.splice(0)) item.reject(Error('fixture exited')); done({code, signal});});});
    child.once('error', reject); child.stderr.on('data', bytes => {stderr += bytes.toString('utf8');});
    const lines = readline.createInterface({input: child.stdout});
    lines.on('line', line => {
      try {const value = JSON.parse(line); if (value.url) resolve(value); else {const item = queue.shift(); if (item) item.resolve(value); else diagnostics.push({unrequested_fixture_observation: value});}}
      catch (error) {reject(error);}
    });
    child.once('exit', code => {if (!metadata) reject(Error('fixture exited before ready: ' + code));});
  });
  metadata = await bounded(ready, 90000, 'fixture ready');
  const origin = new URL(metadata.url).origin;
  assert.equal(new URL(metadata.url).hostname, '127.0.0.1');
  browser = await require(options.playwright).chromium.launch({executablePath: options.browser, headless: true, chromiumSandbox: true});
  browserVersion = browser.version(); context = await browser.newContext({viewport: {width: 1440, height: 1080}});
  await context.route('**/*', route => new URL(route.request().url()).origin === origin ? route.continue() : route.abort());
  context.on('request', request => {if (request.method() === 'POST') requests.push({method: 'POST', path: new URL(request.url()).pathname});});
  context.on('requestfailed', request => diagnostics.push({request_failed: new URL(request.url()).pathname, method: request.method(), error: request.failure()?.errorText}));
  context.on('response', response => {if (new URL(response.url()).pathname.startsWith('/api/')) diagnostics.push({response_path: new URL(response.url()).pathname, status: response.status()});});
  page = await context.newPage(); page.on('pageerror', error => pageErrors.push(error.message));
  page.on('console', message => {if (message.type() === 'error') diagnostics.push({console: message.text()});});
  await page.goto(metadata.url); await choose(page);
  const baseline = await inspect(); assert.equal(baseline.children, 1);
  if (process.env.PEX_DIAGNOSTIC_ONLY === '1') {await check('Initial project overview renders', async () => {assert.equal(pageErrors.length, 0);}); return;}
  await check('GET and three language changes render actual server offers without I/O', async () => {
    for (const [language, title] of [['en', 'Trace the closest papers'], ['zh-Hans', '追踪最接近的论文'], ['zh-Hant', '追蹤最接近的論文']]) {
      await page.locator('#language').selectOption(language); await page.getByRole('heading', {name: title, exact: true}).waitFor(); await shot(language);
    }
    await page.locator('#language').selectOption('en'); assert.deepEqual(await inspect(), baseline); assert.equal(requests.length, 0);
  });
  await check('Unchecked consent cannot submit; explicit authorization saves no backend call', async () => {
    await authorize('References'); const saved = await inspect(); assert.equal(saved.children, 1); assert.equal(saved.grants.length, 1); assert.equal(saved.grants[0].status, 'permission-saved');
  });
  await check('Lost execute response persists one real Core action; double click cannot resend', async () => {
    let posts = 0;
    let observedResponse, failedResponse;
    const responseSeen = new Promise((resolve, reject) => {observedResponse = resolve; failedResponse = reject;});
    await page.route('**/stage1/expansion-execute', async route => {
      try {
        posts++; const response = await route.fetch();
        const observation = {lost_response_status: response.status(), error: (await response.json()).error};
        diagnostics.push(observation); await route.abort('failed'); observedResponse(observation);
      } catch (error) {failedResponse(error);}
    });
    const button = card('References', 'execute').getByRole('button', {name: 'Execute this saved citation permission', exact: true});
    await button.click(); await page.waitForTimeout(150); await button.evaluate(node => node.click());
    await bounded(responseSeen, 35000, 'lost response observation');
    const saved = await inspect(); assert.equal(posts, 1);
    assert.equal(diagnostics.find(row => 'lost_response_status' in row).lost_response_status, 200);
    assert.equal(saved.children, 2); assert.equal(saved.intents.length, 1); assert.equal(saved.intents[0].status, 'completed');
    assert.equal(saved.intents[0].outer_status, 'saved'); assert.equal(saved.intents[0].operation, 'references');
    await page.unroute('**/stage1/expansion-execute');
  });
  await check('Reload and second tab read saved history with zero additional dispatch', async () => {
    const before = await inspect(); await page.reload(); await choose(page); await refresh();
    const other = await context.newPage(); await other.goto(metadata.url); await choose(other); await other.close();
    assert.deepEqual(await inspect(), before);
  });
  await check('Second direction uses its own explicit grant and one shared budget attempt', async () => {
    await authorize('Citing papers');
    const responseSeen = page.waitForResponse(response => new URL(response.url()).pathname.endsWith('/stage1/expansion-execute'));
    await card('Citing papers', 'execute').getByRole('button', {name: 'Execute this saved citation permission', exact: true}).click();
    assert.equal((await responseSeen).status(), 200);
    const saved = await inspect(); assert.equal(saved.children, 3); assert.equal(saved.budget.attempts, 3); assert.equal(saved.intents.length, 2);
    assert.deepEqual(saved.intents.map(row => row.operation).sort(), ['cited-by', 'references']); assert(saved.intents.every(row => row.status === 'completed'));
    await refresh();
    assert.equal(await page.locator('#expansion-panel .history-row').filter({hasText: 'consumed'}).count(), 2);
    assert(!(await page.locator('#expansion-panel').innerText()).includes('Citation expansion is not connected'));
    await shot('after-two-directions');
  });
  await check('Refresh never adds execution and Stage1 is not automatically accepted', async () => {
    const before = await inspect(); await refresh(); assert.deepEqual(await inspect(), before);
    assert(!['completed', 'accepted', 'passed'].includes(await page.locator('#stage1-state').innerText()));
    assert.equal(pageErrors.length, 0);
  });
}
(async () => {
  try {await main();} catch (error) {failure = error.message; if (page) {try {
    diagnostics.push({visible_notice: await page.locator('#notice').innerText().catch(() => 'notice absent')});
    const file = path.join(path.dirname(options.output), 'failure.png');
    await page.screenshot({path: file, fullPage: true}); screenshots.push({label: 'failure', file, sha256: sha(fs.readFileSync(file))});
  } catch (_) {}}}
  if (browser) {try {await bounded(browser.close(), 5000, 'browser close');} catch (error) {cleanup.push(error.message);}}
  if (child && child.exitCode === null) {try {fs.appendFileSync(control, 'stop\n'); await bounded(exit, 12000, 'fixture close');} catch (error) {cleanup.push(error.message); child.kill(); try {await bounded(exit, 5000, 'fixture kill');} catch (error) {cleanup.push(error.message);}}}
  const childResult = exit ? await bounded(exit, 1000, 'final child exit').catch(error => ({error: error.message})) : null;
  if (childResult?.code !== 0 || childResult?.signal) cleanup.push('fixture exit was not successful');
  try {if (fs.existsSync(control)) fs.unlinkSync(control);} catch (error) {cleanup.push(error.message);}
  const unchanged = Object.entries(sources).every(([file, digest]) => sha(fs.readFileSync(path.join(repo, file))) === digest);
  const receipt = {status: failure || stderr || cleanup.length || !unchanged ? 'failed' : 'passed', failure, browser: browserVersion, repo, sources, source_inventory_unchanged: unchanged, results, screenshots, page_errors: pageErrors, diagnostics, requests, observations, stderr, cleanup, child: childResult, diagnostic_only: process.env.PEX_DIAGNOSTIC_ONLY === '1', real_research_execution: 'disabled by authored fixture, not a platform usage measurement', actual_backend: 'authored fake subprocess', actual_http_sqlite_core: true, full_stage1_acceptance: false};
  try {fs.writeFileSync(options.output, JSON.stringify(receipt, null, 2) + '\n', {flag: 'wx'});} catch (error) {console.error('receipt persistence failed: ' + error.message); process.exitCode = 1; return;}
  console.log(JSON.stringify({status: receipt.status, passed: results.filter(row => row.status === 'passed').length, checks: results.length, failure, output: options.output}));
  process.exitCode = receipt.status === 'passed' ? 0 : 1;
})();
