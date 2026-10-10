/* Installed-browser acceptance of universal intake. Real core/HTTP/SQLite;
 * synthetic authored plan only, no model, search, native or scientific run. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const readline = require('node:readline');
const {spawn} = require('node:child_process');
const {createHash, randomUUID} = require('node:crypto');

const options = {};
for (let i = 2; i < process.argv.length; i += 2) {
  const flag = process.argv[i], value = process.argv[i + 1];
  if (!/^--(repo|python|playwright|browser|temp|output)$/.test(flag) || !value || options[flag.slice(2)])
    throw Error('one value per known flag is required');
  options[flag.slice(2)] = value;
}
for (const name of ['repo', 'python', 'playwright', 'browser', 'temp', 'output'])
  if (!options[name] || !path.isAbsolute(options[name])) throw Error('absolute --' + name + ' required');
options.repo = fs.realpathSync(options.repo);
const plugin = path.join(options.repo, 'plugins', 'auto-research-agent');
const fixture = path.join(plugin, 'tests', 'browser', 'project-intake-fixture.py');
if (fs.realpathSync(__filename) !== path.join(plugin, 'tests', 'test_workspace_project_browser.cjs'))
  throw Error('driver must belong to the sole candidate repo');
if (fs.realpathSync(fixture) !== fixture) throw Error('linked fixture rejected');
if (fs.existsSync(options.output)) throw Error('existing receipt must never be overwritten');
fs.mkdirSync(options.temp, {recursive: true});
fs.mkdirSync(path.dirname(options.output), {recursive: true});
const hash = file => createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const scripts = {[__filename]: hash(__filename), [fixture]: hash(fixture)};
const runId = randomUUID();
const control = path.join(options.temp, 'project-browser-' + runId + '.jsonl');
fs.writeFileSync(control, '', {flag: 'wx'});
const child = spawn(options.python, ['-B', '-X', 'utf8', fixture,
  '--repo', options.repo, '--temp-root', options.temp, '--control-file', control],
  {windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'],
    env: {...process.env, TEMP: options.temp, TMP: options.temp, TMPDIR: options.temp, PYTHONDONTWRITEBYTECODE: '1'}});
const queue = [], waiting = [], results = [], pageErrors = [], diagnostics = [], screenshots = [];
let stderr = '', childFailure, browser, context, ready, finishing = false;
function childFailed(error) { childFailure = error; for (const waiter of waiting.splice(0)) waiter.reject(error); }
child.on('error', childFailed);
child.on('exit', (code, signal) => childFailed(Error('fixture exited: ' + code + '/' + signal)));
child.stderr.on('data', bytes => { stderr += bytes; });
readline.createInterface({input: child.stdout}).on('line', line => {
  try {const value = JSON.parse(line); if (waiting.length) waiting.shift().resolve(value); else queue.push(value);}
  catch {stderr += line + '\n';}
});
process.on('exit', () => {if (child.exitCode === null && child.signalCode === null) child.kill();});
function next() {
  if (queue.length) return Promise.resolve(queue.shift());
  if (childFailure) return Promise.reject(childFailure);
  return new Promise((resolve, reject) => {
    const finish = (fn, value) => {clearTimeout(timer); fn(value);};
    const waiter = {resolve: value => finish(resolve, value), reject: error => finish(reject, error)};
    const timer = setTimeout(() => {
      waiting.splice(waiting.indexOf(waiter), 1); waiter.reject(Error('fixture response timeout: ' + stderr));
    }, 15000);
    waiting.push(waiter);
  });
}
async function rpc(op, more = {}) {
  fs.appendFileSync(control, JSON.stringify({op, ...more}) + '\n');
  const reply = await next(); assert.ok(!reply.error, reply.error); return reply.ok;
}
async function check(name, operation) {
  try {await operation(); results.push({name, status: 'passed'});}
  catch (error) {
    results.push({name, status: 'failed', error: error.stack});
    try {const page = context && context.pages().at(-1); if (page && !page.isClosed()) await shot(page, 'failure-' + results.length);}
    catch (capture) {diagnostics.push({failure_screenshot: capture.message});}
    throw error;
  }
}
async function api(page, url, body, authenticated = true) {
  return page.evaluate(async ({url, body, authenticated}) => {
    const headers = {'Content-Type': 'application/json'};
    if (authenticated) headers.Authorization = 'Bearer ' + window.RESEARCH_PROJECTS.credential;
    const response = await fetch(url, {method: body ? 'POST' : 'GET', headers,
      ...(body ? {body: JSON.stringify(body)} : {})});
    return {status: response.status, value: await response.json()};
  }, {url, body, authenticated});
}
const identity = view => Object.fromEntries(['revision', 'input_version', 'brief_sha256'].map(name => [name, view[name]]));
async function select(page, topic) {
  const response = page.waitForResponse(r => r.request().method() === 'GET' && r.url().endsWith('/overview'));
  await page.locator('#project-list button').filter({hasText: topic}).click(); await response;
  await page.waitForFunction(topic => document.querySelector('#topic-heading').textContent === topic && !document.querySelector('#native-refresh').disabled, topic);
}
async function refreshed(page) {
  const response = page.waitForResponse(r => r.request().method() === 'GET' && r.url().endsWith('/overview'));
  await page.locator('#refresh').click(); await response;
  await page.waitForFunction(() => !document.querySelector('#native-refresh').disabled);
}
async function create(page, topic, needs) {
  await page.locator('#new-project').click();
  await page.locator('#topic').fill(topic); await page.locator('#needs').fill(needs);
  await page.locator('#create-form button').click();
  await page.waitForFunction(topic => document.querySelector('#topic-heading').textContent === topic && !document.querySelector('#revise-form button').disabled, topic);
}
async function resourceFields(page) {
  await page.locator('#resources').fill('One researcher, saved public case files only. No model or external search is authorized. Preserve failures and Unknown.');
  await page.locator('#confirmation').fill('I explicitly confirm this topic and scope. Use 30 formal works, 20 priority readings; keep the full screening list.');
}
async function confirm(page) {
  await resourceFields(page);
  await page.locator('#geography').selectOption('not-applicable');
  await page.locator('#geography-value').fill('Method study; no geographic restriction is material.');
  await page.locator('#formal-count').fill('30'); await page.locator('#priority-count').fill('20');
  await page.locator('#confirm-form button[type=submit]').click();
  await page.waitForFunction(() => document.querySelector('#intake-card').open === false);
  await page.waitForFunction(() => !document.querySelector('#revise-form button').disabled);
}
async function shot(page, label) {
  const file = path.join(path.dirname(options.output), 'project-' + label + '-' + runId + '.png');
  if (fs.existsSync(file)) throw Error('screenshot collision');
  await page.evaluate(() => scrollTo(0, 0));
  await page.screenshot({path: file, fullPage: true});
  screenshots.push({label, path: file, sha256: hash(file)});
}
const music = 'Polyphonic music transcription with scarce annotations';
const aircraft = 'Aircraft fault diagnosis with sensor drift';
let musicRef, aircraftRef;
const operation = (async () => {
  ready = await next(); assert.match(ready.origin, /^http:\/\/127\.0\.0\.1:\d+$/);
  assert.equal(ready.mode, 'offline-real-core-with-synthetic-plan-proposal');
  const {chromium} = require(options.playwright);
  browser = await chromium.launch({executablePath: options.browser, headless: true, chromiumSandbox: true});
  context = await browser.newContext({viewport: {width: 1440, height: 960}});
  context.setDefaultTimeout(12000);
  await context.route('**/*', route => route.request().url().startsWith(ready.origin + '/') ? route.continue() : route.abort());
  const page = await context.newPage();
  page.on('pageerror', error => pageErrors.push(error.message));
  page.on('console', message => {if (message.type() === 'error') diagnostics.push({console: message.text()});});
  page.on('requestfailed', request => diagnostics.push({url: request.url(), failure: request.failure()}));
  await page.goto(ready.origin + '/');
  await check('lost create response and reload recover exact saved key without automatic POST', async () => {
    let posts = 0;
    await page.route('**/api/projects', async route => {
      if (route.request().method() !== 'POST') return route.continue();
      posts++; const response = await route.fetch(); assert.equal(response.status(), 200); await route.abort('failed');
    });
    await page.locator('#topic').fill(music); await page.locator('#needs').fill('Which methods work with scarce annotations?');
    await page.locator('#create-form button').click();
    await page.waitForFunction(() => document.querySelector('#notice').classList.contains('error'));
    assert.equal((await rpc('snapshot')).projects.length, 1);
    await page.reload();
    await page.waitForFunction(topic => document.querySelector('#topic-heading').textContent === topic && !document.querySelector('#revise-form button').disabled, music);
    assert.equal(posts, 1);
    assert.equal(await page.evaluate(() => JSON.stringify({...localStorage, ...sessionStorage}).includes(window.RESEARCH_PROJECTS.credential)), false);
    musicRef = (await rpc('snapshot')).projects[0].project.project_ref;
    await page.unroute('**/api/projects');
  });
  await check('draft resource settings do not confirm scope or authorize any provider', async () => {
    await resourceFields(page); await page.locator('#configure').click();
    await page.waitForFunction(() => !document.querySelector('#configure').disabled);
    const saved = (await rpc('snapshot')).projects[0].project;
    assert.ok(saved.settings); assert.equal(saved.intake_report.necessary_clarification_complete, false);
    assert.equal(saved.formal_question.status, 'pending'); assert.equal(saved.execution_authorized, false);
    for (const id of ['suggest-topic', 'plan-search', 'authorize-topic', 'authorize-plan']) assert.equal(await page.locator('#' + id).isDisabled(), true);
  });
  await check('actual UI answers confirm the real v1.1 brief, 30 formal and 20 priority', async () => {
    await confirm(page); const saved = (await rpc('snapshot')).projects[0].project;
    assert.equal(saved.brief.schema_version, '1.1.0'); assert.equal(saved.brief.original_description, music);
    assert.equal(saved.intake_report.necessary_clarification_complete, true);
    assert.equal(saved.intake_report.formal_final_count.target, 30);
    assert.equal(saved.intake_report.scope.priority_reading_target.value, '20');
    assert.equal(saved.stage1_intake_ready, false); assert.equal(saved.model_calls, null); assert.equal(saved.monetary_cost, null);
  });
  await check('test-only synthetic proposal uses the real compiler, then UI initializes real ledger', async () => {
    const compiled = await rpc('compile', {project_ref: musicRef});
    assert.equal(compiled.plan_execution_status, 'not-executed');
    await refreshed(page); assert.equal(await page.locator('#ledger-init').isDisabled(), false);
    await page.locator('#ledger-init').click();
    await page.waitForFunction(() => !document.querySelector('#ledger-checkpoint').disabled);
    const saved = (await rpc('snapshot')).projects[0];
    assert.equal(saved.project.stage1_intake_ready, true); assert.equal(saved.stage1.ledger.valid, true);
    assert.ok(saved.stage1.queries.length >= 12); assert.equal(saved.stage1.stage1_complete, false);
    const visible = await page.locator('#ledger-state').textContent();
    assert.ok(visible.includes(saved.stage1.ledger.gate.outcome)); assert.ok(visible.includes(saved.stage1.ledger.next_allowed_action));
    assert.equal(visible.includes('[object Object]'), false);
    assert.equal(saved.stage1.canonical_package, null); assert.equal(saved.stage1.evaluation_status, 'not-scored');
    assert.ok(saved.stage1.queries.every(query => query.execution_available === false));
  });
  await check('UI checkpoint and export persist actual core receipts, without claiming coverage success', async () => {
    for (const id of ['ledger-checkpoint', 'ledger-export']) {
      await page.locator('#' + id).click(); await page.waitForFunction(() => !document.querySelector('#ledger-export').disabled);
    }
    const saved = (await rpc('snapshot')).projects[0];
    assert.ok(saved.stage1.checkpoint); assert.equal(saved.stage1.stage1_complete, false);
    const actions = saved.history.actions;
    assert.ok(actions.some(row => row.kind === 'stage1-checkpoint' && row.status === 'saved'));
    const exported = actions.find(row => row.kind === 'stage1-export' && row.status === 'saved');
    assert.ok(exported); assert.match(exported.manifest_sha256, /^[0-9a-f]{64}$/);
    assert.equal(exported.source_state_sha256, saved.stage1.ledger.state_sha256);
    assert.equal(exported.artifact_kind, 'Stage1ExportManifest'); assert.equal(exported.canonical_package, null);
    assert.equal(saved.stage1.source_acquisition_calls, null);
    await shot(page, 'stage1-real-ledger');
  });
  await check('Stage2 and stages3-6 remain truthful when eligible evidence and native provider are absent', async () => {
    const saved = (await rpc('snapshot')).projects[0];
    assert.deepEqual(saved.stage2.offers, []); assert.equal(saved.stage2.stage2_complete, false);
    assert.equal(await page.locator('#activate-stage2').isDisabled(), true);
    assert.ok(Object.values(saved.project.later_stages).every(row => row.status === 'planned' && row.connected === false));
    assert.match(await page.locator('#native-questions').textContent(), /No active native/);
  });
  await check('three UI languages preserve researcher topic and source wording verbatim', async () => {
    for (const locale of ['zh-Hans', 'zh-Hant', 'en']) {
      await page.locator('#language').selectOption(locale);
      assert.equal(await page.locator('html').getAttribute('lang'), locale);
      assert.equal(await page.locator('#topic-heading').textContent(), music);
      assert.match(await page.locator('#needs-summary').textContent(), /scarce annotations/);
      assert.equal(await page.locator('#ledger-export').isDisabled(), false);
      if (locale === 'zh-Hans') await shot(page, 'stage1-ledger-zh-Hans');
    }
  });
  await check('second unrelated topic uses the same UI and stays isolated from the first ledger', async () => {
    const needs = Array.from({length: 8}, (_, i) => 'Question ' + i + ': ' + 'sensor validation, failures and domain shift; '.repeat(12)).join('\n');
    await create(page, aircraft, needs); await confirm(page);
    const snapshot = await rpc('snapshot'); assert.equal(snapshot.projects.length, 2);
    const second = snapshot.projects.find(row => row.project.brief.original_description === aircraft);
    aircraftRef = second.project.project_ref; assert.notEqual(aircraftRef, musicRef);
    assert.equal(second.stage1.ledger, null); assert.equal(second.project.stage1_intake_ready, false);
    assert.equal(second.project.settings.budgets.model_calls, 0);
  });
  await check('same key replays one saved receipt, changed replay and client authority are rejected', async () => {
    const view = (await api(page, '/api/projects/' + aircraftRef)).value;
    const body = {...identity(view), key: 'browser-repeat-configuration', resource_envelope: view.settings.resource_envelope,
      budgets: view.settings.budgets, consent: view.settings.consent, user_input: view.settings.user_input, confirmed: true};
    const first = await api(page, '/api/projects/' + aircraftRef + '/configure', body);
    const second = await api(page, '/api/projects/' + aircraftRef + '/configure', body);
    assert.equal(first.status, 200); assert.equal(second.status, 200); assert.equal(second.value.replayed, true);
    const replay = {...second.value}; delete replay.replayed; const original = {...first.value}; delete original.replayed;
    assert.deepEqual(replay, original);
    const changed = await api(page, '/api/projects/' + aircraftRef + '/configure', {...body, resource_envelope: 'changed'});
    assert.equal(changed.status, 409);
    const injected = await api(page, '/api/projects/' + aircraftRef + '/configure', {...body, key: 'browser-root-rejected', root: 'C:/private'});
    assert.equal(injected.status, 400);
    assert.equal((await api(page, '/api/projects/' + aircraftRef, null, false)).status, 401);
    const snapshot = await rpc('snapshot'), saved = snapshot.projects.find(row => row.project.project_ref === aircraftRef);
    assert.equal(saved.history.actions.filter(row => row.key === body.key).length, 1);
    assert.equal(snapshot.actual_model_calls, 0); assert.equal(snapshot.actual_search_calls, 0);
    await refreshed(page);
  });
  await check('invalid GET suffixes fail closed; valid ledger/offer GETs do not append actions', async () => {
    const before = await rpc('snapshot');
    for (const suffix of ['history/actions', 'contract/actions', 'overview/actions', 'confirm', 'stage2/native']) {
      const reply = await api(page, '/api/projects/' + aircraftRef + '/' + suffix);
      assert.ok([400, 404].includes(reply.status), suffix + ' was admitted as a normal read');
    }
    for (const suffix of ['stage1', 'stage1/offers', 'stage2', 'stage2/offers', 'contract'])
      assert.equal((await api(page, '/api/projects/' + musicRef + '/' + suffix)).status, 200);
    assert.deepEqual(await rpc('snapshot'), before);
  });
  await check('UTF-8 input exceeding the byte bound is rejected before local intent or HTTP POST', async () => {
    await page.locator('#new-project').click(); let posts = 0;
    const listener = request => {if (request.method() === 'POST') posts++;}; page.on('request', listener);
    const before = await page.evaluate(() => sessionStorage.getItem('harness-project-ui-intents-v1'));
    await page.locator('#topic').fill('論'.repeat(1400)); await page.locator('#needs').fill('Question');
    await page.locator('#create-form button').click();
    await page.waitForFunction(() => document.querySelector('#notice').textContent.includes('UTF-8'));
    assert.equal(posts, 0); assert.equal(await page.evaluate(() => sessionStorage.getItem('harness-project-ui-intents-v1')), before);
    page.off('request', listener); await select(page, aircraft);
  });
  await check('project switch disables stale forms while delayed overview is loading', async () => {
    let observed = false;
    await page.route('**/api/projects/' + musicRef + '/overview', async route => {
      observed = true; await new Promise(resolve => setTimeout(resolve, 120)); await route.continue();
    });
    const loading = select(page, music);
    await page.waitForFunction(() => document.querySelector('#revise-form button').disabled);
    assert.equal(await page.locator('#ledger-init').isDisabled(), true); assert.equal(await page.locator('#ledger-export').isDisabled(), true);
    await loading; assert.equal(observed, true); await page.unroute('**/api/projects/' + musicRef + '/overview');
    await select(page, aircraft); assert.equal(await page.locator('#ledger-export').isDisabled(), true);
  });
  await check('SQLite reopen, UI refresh and reload preserve receipts with zero extra mutation', async () => {
    const before = await rpc('snapshot'); await rpc('reopen');
    let posts = 0; const listener = request => {if (request.method() === 'POST') posts++;}; page.on('request', listener);
    await refreshed(page); await page.reload(); await page.locator('#project-list button').filter({hasText: aircraft}).waitFor();
    await select(page, aircraft); await select(page, music); await page.locator('#history-refresh').click();
    assert.deepEqual(await rpc('snapshot'), before); assert.equal(posts, 0); page.off('request', listener);
  });
  await check('desktop/tablet/mobile keep long content readable and bounded history scrollable', async () => {
    await select(page, aircraft);
    for (const [label, width, height] of [['desktop', 1440, 960], ['tablet', 820, 1180], ['mobile', 390, 844]]) {
      await page.setViewportSize({width, height});
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true, label + ' horizontal overflow');
      const refreshSize = await page.locator('#refresh').boundingBox();
      assert.ok(refreshSize.width >= 130 && refreshSize.height <= 64, label + ' long content compressed the refresh button');
      const needsScroll = await page.locator('#needs-summary').evaluate(node => {
        node.scrollTop = node.scrollHeight; const result = {height: node.clientHeight, total: node.scrollHeight, moved: node.scrollTop};
        node.scrollTop = 0; return result;
      });
      assert.ok(needsScroll.height <= 181 && needsScroll.total > needsScroll.height && needsScroll.moved > 0, label + ' full original needs must scroll inside a bounded panel');
      await page.locator('.workflow summary').click();
      await page.locator('#history').evaluate(node => {node.scrollTop = node.scrollHeight;});
      assert.equal(await page.locator('#history').evaluate(node => node.clientHeight <= 341), true);
      assert.equal(await page.evaluate(() => document.documentElement.scrollHeight > innerHeight), true);
      if (label !== 'mobile') await shot(page, label);
      await page.locator('.workflow summary').click();
    }
    await page.setViewportSize({width: 1440, height: 960});
  });
  await check('researcher topic revision saves lineage and returns to pending rather than reusing old answers', async () => {
    const before = (await rpc('snapshot')).projects.find(row => row.project.project_ref === aircraftRef);
    await page.locator('#revise-form').evaluate(form => {form.closest('details').open = true;});
    await page.locator('#revised-topic').fill(aircraft + ' with missing sensors');
    await page.locator('#revise-form button').click(); await page.waitForFunction(() => document.querySelector('#intake-card').open === true);
    await page.waitForFunction(() => !document.querySelector('#configure').disabled);
    const after = (await rpc('snapshot')).projects.find(row => row.project.project_ref === aircraftRef);
    assert.notEqual(after.project.input_version, before.project.input_version);
    assert.equal(after.project.intake_report.necessary_clarification_complete, false);
    assert.ok(after.history.versions.some(row => row.sha256 === before.project.brief_sha256));
    assert.equal(after.stage1.ledger, null); assert.equal(after.project.execution_authorized, false);
  });
  await check('UI-only synthetic HTTP responses: queued model admission stays pending until exact terminal history; GET never resends', async () => {
    // These browser response overlays do not configure a provider or reach a
    // model POST on the real server. Backend/native acceptance is separate.
    const before = await rpc('snapshot'); let receipt, terminal, posts = 0;
    const modelActionsPattern = new RegExp('/api/projects/' + musicRef + '/models/actions(?:/[0-9]+)?$');
    const stable = value => Array.isArray(value) ? '[' + value.map(stable).join(',') + ']'
      : value && typeof value === 'object' ? '{' + Object.keys(value).sort().map(key => JSON.stringify(key) + ':' + stable(value[key])).join(',') + '}' : JSON.stringify(value);
    await page.route('**/api/projects/' + musicRef + '/overview', async route => {
      const real = await route.fetch(), value = await real.json();
      value.models = {authorization_available: false, active_jobs: receipt && !terminal ? [receipt] : [], unknown_count: 0};
      value.model_offers = {offers: [{operation: 'suggest-topic', available: true, offer_ref: 'test-only-ui-offer', offer_sha256: 'a'.repeat(64)}]};
      await route.fulfill({response: real, json: value});
    });
    await page.route('**/api/projects/' + musicRef + '/history', async route => {
      const real = await route.fetch(), value = await real.json();
      if (receipt) value.actions.push(receipt);
      await route.fulfill({response: real, json: value});
    });
    await page.route(modelActionsPattern, async route => {
      if (route.request().method() === 'POST') {
        posts++; const body = route.request().postDataJSON();
        const semantic = {...body}; delete semantic.revision;
        receipt = {key: body.key, kind: 'model-operation', project_ref: musicRef,
          request_sha256: createHash('sha256').update(stable({kind: 'model-operation', body: semantic})).digest('hex'),
          status: 'saved', model_status: 'queued', result: {model_status: 'queued'}};
        return route.fulfill({status: 200, json: receipt});
      }
      await route.fulfill({status: 200, json: {actions: terminal ? [terminal] : [], next_offset: null}});
    });
    await select(page, music); assert.equal(await page.locator('#suggest-topic').isDisabled(), false);
    await page.locator('#suggest-topic').click();
    await page.waitForFunction(() => document.querySelector('#history').textContent.includes('model-operation'));
    const pending = () => page.evaluate(key => JSON.parse(sessionStorage.getItem('harness-project-ui-intents-v1') || '[]').some(row => row.key === key), receipt.key);
    assert.equal(await pending(), true); assert.equal(await page.locator('#suggest-topic').isDisabled(), true);
    terminal = {...receipt, operation: 'suggest-topic', status: 'content-review-pending', request_sha256: 'b'.repeat(64)};
    await refreshed(page); assert.equal(await pending(), true); assert.equal(await page.locator('#suggest-topic').isDisabled(), true);
    await page.reload(); await page.locator('#project-list button').filter({hasText: music}).waitFor(); await select(page, music);
    assert.equal(await pending(), true); assert.equal(posts, 1);
    terminal.request_sha256 = receipt.request_sha256;
    await refreshed(page); assert.equal(await pending(), false); assert.equal(await page.locator('#suggest-topic').isDisabled(), false);
    assert.equal(posts, 1); assert.deepEqual(await rpc('snapshot'), before);
    for (const suffix of ['overview', 'history']) await page.unroute('**/api/projects/' + musicRef + '/' + suffix);
    await page.unroute(modelActionsPattern);
    await refreshed(page); assert.equal(await page.locator('#suggest-topic').isDisabled(), true);
  });
  assert.deepEqual(pageErrors, []);
  return {status: 'passed', browser: await browser.version(), mode: ready.mode};
})();
const deadline = setTimeout(() => finish({status: 'failed', error: 'absolute 120-second browser deadline expired'}), 120000);
async function bounded(promise, label) {
  let timer;
  try {return await Promise.race([promise, new Promise((_, reject) => {timer = setTimeout(() => reject(Error(label + ' timed out')), 5000);})]);}
  finally {clearTimeout(timer);}
}
async function finish(meta) {
  if (finishing) return; finishing = true; clearTimeout(deadline); process.exitCode = 1;
  const cleanup = [];
  try {if (browser) await bounded(browser.close(), 'browser close');} catch (error) {cleanup.push(error.message);}
  try {
    if (child.exitCode === null && child.signalCode === null && !childFailure) {
      const exited = new Promise(resolve => child.once('exit', resolve));
      fs.appendFileSync(control, '{"op":"stop"}\n'); await bounded(exited, 'fixture shutdown');
    }
    if (child.exitCode !== 0 || child.signalCode !== null) cleanup.push('fixture did not exit successfully');
  } catch (error) {cleanup.push(error.message);}
  if (child.exitCode === null && child.signalCode === null) {
    const exited = new Promise(resolve => child.once('exit', resolve)); child.kill();
    try {await bounded(exited, 'fixture kill confirmation');} catch (error) {cleanup.push(error.message);}
  }
  if (stderr || cleanup.length) meta.status = 'failed';
  const receipt = {...meta, run_id: runId, candidate_repo: options.repo, scripts,
    source_sha256: ready && ready.source_sha256, served_sha256: ready && ready.served_sha256,
    results, screenshots, page_errors: pageErrors, diagnostics, stderr, cleanup,
    model_or_search_execution: 'none; unconnected providers', child_exit: {pid: child.pid, code: child.exitCode, signal: child.signalCode}};
  try {fs.writeFileSync(options.output, JSON.stringify(receipt, null, 2) + '\n', {flag: 'wx'});}
  catch (error) {console.error('receipt persistence failed: ' + error.message); return;}
  console.log(JSON.stringify({status: receipt.status, tests: results.length, passed: results.filter(row => row.status === 'passed').length, output: options.output}));
  process.exitCode = receipt.status === 'passed' ? 0 : 1;
}
operation.then(finish).catch(error => finish({status: 'failed', error: error.stack}));
for (const signal of ['SIGINT', 'SIGTERM']) process.once(signal, () => finish({status: 'failed', error: signal}));
