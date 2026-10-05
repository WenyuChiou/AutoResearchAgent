/* Actual installed Chromium against explicit loopback fixture; no downloads/native/model. */
const assert = require('node:assert/strict');
const {createHash, randomUUID} = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const {spawn} = require('node:child_process');
const readline = require('node:readline');
const options = Object.fromEntries(process.argv.slice(2).reduce((a, v, i, all) => {
  if (!(i % 2)) a.push([v.slice(2), all[i + 1]]); return a;
}, []));
const {chromium} = require(options.playwright);
fs.mkdirSync(options.temp, {recursive: true});
for (const key of ['TEMP', 'TMP', 'TMPDIR']) process.env[key] = options.temp;
const control = path.join(options.temp, `browser-control-${randomUUID()}.jsonl`);
fs.writeFileSync(control, '', {flag: 'wx'});
const child = spawn(options.python, ['-B', '-X', 'utf8', path.join(__dirname, 'browser_fixture.py'),
  '--repo', options.repo, '--reference-root', options.reference,
  '--overlay', options.overlay, '--temp-root', options.temp, '--control-file', control,
  ...(options.scope === 'true' ? ['--scope'] : [])],
  {windowsHide: true, stdio: ['ignore', 'pipe', 'pipe']});
const queue = [], waiting = [];
let stderr = '', childFailure;
function failedChild(error) {
  childFailure = error;
  for (const waiter of waiting.splice(0)) waiter.reject(error);
}
child.on('error', failedChild);
child.on('exit', (code, signal) => failedChild(Error(`fixture exited: ${code}/${signal}`)));
process.on('exit', () => {if (child.exitCode === null && child.signalCode === null) child.kill();});
child.stderr.on('data', data => {stderr += data;});
readline.createInterface({input: child.stdout}).on('line', line => {
  try { const value = JSON.parse(line); if (waiting.length) waiting.shift().resolve(value); else queue.push(value); }
  catch {stderr += line + '\n';}
});
const next = () => {
  if (queue.length) return Promise.resolve(queue.shift());
  if (childFailure) return Promise.reject(childFailure);
  return new Promise((resolve, reject) => {
    const finish = (fn, value) => {clearTimeout(timer); fn(value);};
    const waiter = {resolve: value => finish(resolve, value), reject: error => finish(reject, error)};
    const timer = setTimeout(() => {
      waiting.splice(waiting.indexOf(waiter), 1); waiter.reject(Error('fixture timeout: ' + stderr));
    }, 15000);
    waiting.push(waiter);
  });
};
const rpc = async (op, name, more = {}) => {
  fs.appendFileSync(control, JSON.stringify({op, name, ...more}) + '\n');
  const value = await next(); assert.ok(!value.error, JSON.stringify(value)); return value.ok;
};
const results = [], errors = [], diagnostics = [];
let browser, context, origin, sourceHashes, servedHashes;
const check = async (name, run) => {
  try {await run(); results.push({name, status: 'passed'});}
  catch (error) {results.push({name, status: 'failed', error: error.stack}); throw error;}
};
const pageFor = async p => {
  const page = await context.newPage();
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => {if (message.type() === 'error') diagnostics.push({console: message.text()});});
  page.on('requestfailed', request => diagnostics.push({url: request.url(), failed: request.failure()}));
  page.on('request', request => diagnostics.push({method: request.method(), url: request.url()}));
  await page.goto(origin);
  await page.locator('#native-session-panel').waitFor();
  await page.locator('#workspaceLanguage').selectOption('en');
  await connect(page, p);
  return page;
};
const connect = async (page, p, token = p.token) => {
  await page.locator('#native-session-panel input[aria-label=project]').fill(p.ref);
  await page.locator('#native-session-panel input[aria-label=credential]').fill(token);
  diagnostics.push(await page.locator('.native-connect').evaluate(form => ({valid: form.checkValidity(),
    fields: [...form.querySelectorAll('input')].map(e => ({name: e.getAttribute('aria-label'), length: e.value.length,
      valid: e.validity.valid, message: e.validationMessage})), handler: typeof form.onsubmit})));
  const response = page.waitForResponse(r => r.request().method() === 'GET' && r.url().endsWith('/' + p.ref));
  await page.locator('[data-native-label=connect]').click(); await response;
};
const refresh = async page => {
  const response = page.waitForResponse(r => r.request().method() === 'GET' && r.url().includes('/api/native/'));
  await page.locator('[data-native-label=refresh]').click(); await response;
};
const settle = async (page, status) => {
  await page.waitForFunction(s => document.querySelector('#native-history').textContent.includes(s), status);
};
const answer = async (page, value = 'neutral answer') => {
  await page.locator('#native-questions textarea').fill(value);
  await page.locator('[data-native-label=send]').click();
};
const scopeReady = page => page.locator('#native-scope-form').waitFor();
const scopeChoice = async page => {
  await scopeReady(page);
  await page.locator('#native-scope-form [aria-label=field]').selectOption('geography');
  await page.locator('#native-scope-form [aria-label=value]').fill('Region A');
  await page.locator('#native-scope-form [aria-label=reason]').fill('Explicit neutral choice.');
  await page.locator('#native-scope-form [aria-label=original]').fill('Use Region A.');
  await page.locator('#native-scope-form input[type=checkbox]').check();
};
const saveScope = async page => {
  await scopeChoice(page); await page.locator('button[data-scope-label=save]').click();
  await page.waitForFunction(() => document.querySelector('#native-scope-panel select[aria-label=version]').options.length === 2);
};
const scopeLedgerCount = page => page.evaluate(() => Object.keys(sessionStorage)
  .filter(k => k.startsWith('native-scope-intents:')).reduce((n, k) => n + JSON.parse(sessionStorage.getItem(k)).length, 0));
(async () => {
  const ready = await next(); origin = ready.origin; sourceHashes = ready.source_sha256;
  servedHashes = ready.served_sha256;
  assert.match(origin, /^http:\/\/127\.0\.0\.1:\d+$/);
  browser = await chromium.launch({executablePath: options.browser, headless: true,
    chromiumSandbox: true, args: ['--disable-gpu']});
  context = await browser.newContext();
  await context.route('**/*', route => route.request().url().startsWith(origin + '/') ? route.continue() : route.abort());
  await check('three languages preserve question/source text; exact answer; resolution separate from terminal', async () => {
    const p = await rpc('create', 'answer'); await rpc('question', 'answer'); const page = await pageFor(p);
    for (const locale of ['en', 'zh-Hans', 'zh-Hant', 'en']) {
      await page.locator('#workspaceLanguage').selectOption(locale);
      assert.equal(await page.locator('#native-questions textarea').getAttribute('aria-label'), 'Evidence <literal> 作者原文');
      assert.equal(await page.locator('#native-questions script').count(), 0);
    }
    assert.equal(await page.locator('input[aria-label=credential]').inputValue(), '');
    await answer(page); await settle(page, 'dispatched');
    let state = await rpc('state', 'answer');
    assert.deepEqual(state.messages, [{id: 83, result: {answers: {q: {answers: ['neutral answer']}}}}]);
    assert.equal(state.writes, 1); assert.deepEqual(state.turns, {});
    await rpc('resolved', 'answer'); await refresh(page); await settle(page, 'completed');
    state = await rpc('state', 'answer'); assert.deepEqual(state.turns, {});
    await page.close();
  });
  await check('reload and GET history do not resend; no credentials retained', async () => {
    const p = await rpc('create', 'reload'); await rpc('question', 'reload'); const page = await pageFor(p);
    await answer(page); await settle(page, 'dispatched'); const before = await rpc('state', 'reload');
    let posts = 0; page.on('request', r => {if (r.method() === 'POST') posts++;});
    await refresh(page); await page.reload();
    assert.equal(await page.locator('input[aria-label=credential]').inputValue(), '');
    await connect(page, p); await settle(page, 'dispatched');
    assert.equal(posts, 0); assert.equal((await rpc('state', 'reload')).writes, before.writes);
    assert.equal(await page.evaluate(token => JSON.stringify({...localStorage, ...sessionStorage}).includes(token), p.token), false);
    await page.close();
  });
  await check('decline and interrupt use server bound native targets', async () => {
    const p = await rpc('create', 'approval'); await rpc('question', 'approval', {method: 'item/commandExecution/requestApproval'});
    const page = await pageFor(p); await page.locator('[data-native-label=decline]').click(); await settle(page, 'dispatched');
    assert.deepEqual((await rpc('state', 'approval')).messages[0], {id: 83, result: {decision: 'decline'}});
    await rpc('resolved', 'approval'); await rpc('start', 'approval'); await refresh(page);
    await page.locator('[data-native-label=interrupt]').click(); await settle(page, 'write-observed');
    const sent = (await rpc('state', 'approval')).messages.at(-1);
    assert.equal(sent.method, 'turn/interrupt');
    assert.deepEqual(sent.params, {threadId: 'private-thread-approval', turnId: 'saved-turn'});
    await page.close();
  });
  await check('two tabs submit only one native answer; cross principal project stays closed', async () => {
    const p = await rpc('create', 'tabs'); await rpc('question', 'tabs'); const a = await pageFor(p), b = await pageFor(p);
    await Promise.all([answer(a), answer(b)]); await settle(a, 'dispatched'); await settle(b, 'dispatched');
    assert.equal((await rpc('state', 'tabs')).writes, 1);
    const foreign = await rpc('create', 'foreign', {principal: 'principal-b'}); await rpc('question', 'foreign');
    await connect(a, foreign); await a.waitForFunction(() => document.querySelector('#native-notice').textContent.includes('failed'));
    assert.equal(await a.locator('#native-questions textarea').count(), 0);
    assert.equal((await rpc('state', 'foreign')).writes, 0); await a.close(); await b.close();
  });
  await check('lost HTTP response recovers by GET without POST retry', async () => {
    const p = await rpc('create', 'lost'); await rpc('question', 'lost'); const page = await pageFor(p);
    let posts = 0;
    await page.route('**/api/native/projects/' + p.ref + '/answers', async route => {
      posts++; const response = await route.fetch(); assert.equal(response.status(), 200); await route.abort('failed');
    });
    await answer(page); await settle(page, 'dispatched'); await refresh(page);
    await page.reload(); await connect(page, p); await settle(page, 'dispatched');
    assert.equal(posts, 1); assert.equal((await rpc('state', 'lost')).writes, 1); await page.close();
  });
  await check('partial native write is durable unknown and never resent', async () => {
    const p = await rpc('create', 'partial'); await rpc('question', 'partial'); await rpc('partial', 'partial');
    const page = await pageFor(p); await answer(page); await settle(page, 'execution-unknown');
    const before = await rpc('state', 'partial'); assert.equal(before.writes, 2); assert.equal(before.raw_hex.length, 10);
    await refresh(page); await page.reload(); await connect(page, p); await settle(page, 'execution-unknown');
    assert.equal((await rpc('state', 'partial')).writes, 2); await page.close();
  });
  await check('source drift rejects submission without native I/O', async () => {
    const p = await rpc('create', 'drift'); await rpc('question', 'drift'); const page = await pageFor(p);
    await rpc('drift', 'drift'); await answer(page);
    await page.waitForFunction(() => document.querySelector('#native-notice').textContent.includes('failed'));
    assert.equal((await rpc('state', 'drift')).writes, 0); await page.close();
  });
  await check('malformed frame and owner loss preserve unknown without browser retries', async () => {
    for (const mode of ['malformed', 'owner-loss']) {
      const p = await rpc('create', mode); await rpc('question', mode); const page = await pageFor(p);
      await answer(page); await settle(page, 'dispatched'); await rpc(mode, mode); await refresh(page);
      const state = await rpc('state', mode);
      assert.ok(Object.values(state.intents).some(r => r.status === 'execution-unknown'));
      assert.equal(state.writes, 1); await page.close();
    }
  });
  await check('late older GET cannot replace a newer saved revision', async () => {
    const p = await rpc('create', 'get-order'); await rpc('question', 'get-order'); const page = await pageFor(p);
    let release, captured, oldRequest;
    const held = new Promise(resolve => {release = resolve;});
    const seen = new Promise(resolve => {captured = resolve;});
    let reads = 0;
    await page.route('**/api/native/projects/' + p.ref, async route => {
      if (++reads !== 1) return route.continue();
      oldRequest = route.request(); const response = await route.fetch();
      captured(); await held; await route.fulfill({response});
    });
    await page.locator('[data-native-label=refresh]').click(); await seen;
    await rpc('resolved', 'get-order'); await refresh(page);
    await page.waitForFunction(() => !document.querySelector('#native-questions textarea'));
    const binding = await page.locator('#native-binding').textContent();
    const finished = page.waitForEvent('requestfinished', r => r === oldRequest);
    release(); await finished; await page.waitForTimeout(50);
    assert.equal(await page.locator('#native-binding').textContent(), binding);
    assert.equal(await page.locator('#native-questions textarea').count(), 0);
    assert.equal((await rpc('state', 'get-order')).writes, 0); await page.close();
  });
  await check('failed obsolete project connection cannot clear current project', async () => {
    const a = await rpc('create', 'connect-old'), b = await rpc('create', 'connect-new');
    await rpc('question', 'connect-old'); await rpc('question', 'connect-new'); const page = await pageFor(a);
    let release, captured, oldRequest;
    const held = new Promise(resolve => {release = resolve;});
    const seen = new Promise(resolve => {captured = resolve;});
    await page.route('**/api/native/projects/' + a.ref, async route => {
      oldRequest = route.request(); captured(); await held; await route.abort('failed');
    });
    await page.locator('input[aria-label=project]').fill(a.ref);
    await page.locator('input[aria-label=credential]').fill(a.token);
    await page.locator('[data-native-label=connect]').click(); await seen;
    await connect(page, b);
    await page.waitForFunction(ref => document.querySelector('#native-binding').textContent.includes(ref), b.ref);
    const binding = await page.locator('#native-binding').textContent();
    const failed = page.waitForEvent('requestfailed', r => r === oldRequest);
    release(); await failed; await page.waitForTimeout(50);
    assert.equal(await page.locator('#native-binding').textContent(), binding);
    assert.equal(await page.locator('#native-questions textarea').count(), 1);
    assert.equal((await rpc('state', 'connect-old')).writes, 0);
    assert.equal((await rpc('state', 'connect-new')).writes, 0); await page.close();
  });
  await check('original Wiki README link serves the exact accepted public bytes', async () => {
    const page = await context.newPage(); await page.goto(origin);
    await page.locator('#workspaceLanguage').selectOption('en');
    const response = page.waitForResponse(r => r.url() === origin + '/README.md');
    await page.locator('a[href="../../README.md"]').click();
    const readme = await response; assert.equal(readme.status(), 200);
    assert.match(readme.headers()['content-type'], /^text\/plain/);
    assert.equal(createHash('sha256').update(await readme.body()).digest('hex'),
      '5a2830f28f8f398c53afac3cd63094132a40e04cdfc754d5419360decf50d3af');
    await page.close();
  });
  await check('two-question UTF-8 answer limit rejects before local intent and POST', async () => {
    const p = await rpc('create', 'large'); await rpc('question', 'large', {two_questions: true});
    const page = await pageFor(p); let posts = 0;
    page.on('request', r => {if (r.method() === 'POST') posts++;});
    await page.locator('#native-questions textarea').nth(0).fill('字'.repeat(7000));
    await page.locator('#native-questions textarea').nth(1).fill('語'.repeat(7000));
    await page.locator('[data-native-label=send]').click();
    await page.waitForFunction(() => document.querySelector('#native-notice').textContent.length > 0);
    assert.equal(posts, 0); assert.equal((await rpc('state', 'large')).writes, 0);
    assert.equal(await page.evaluate(() => Object.keys(sessionStorage).filter(k => k.startsWith('native-intents:')).length), 0);
    await page.locator('#workspaceLanguage').selectOption('zh-Hant');
    await page.waitForFunction(() => document.querySelector('#native-notice').textContent === '回答超過 32 KiB，請縮短後提交。');
    assert.equal(await page.locator('#native-questions textarea').nth(0).inputValue(), '字'.repeat(7000));
    await page.close();
  });
  if (options.scope === 'true') {
    await check('scope confirmation and two explicit old-version reviews preserve source and do not execute', async () => {
      const p = await rpc('create-scope', 'scope-review'); const before = await rpc('state', 'scope-review');
      const page = await pageFor(p); await scopeReady(page);
      const original = await page.locator('#native-scope-panel select[aria-label=version]').inputValue();
      await saveScope(page);
      await page.locator('#native-scope-panel select[aria-label=version]').selectOption(original);
      await page.waitForFunction(ref => document.querySelector('#native-scope-panel pre').textContent.includes(ref), original);
      for (const note of ['First explicit review.', 'Second explicit review.']) {
        await page.locator('#native-review-form [aria-label=note]').fill(note);
        await page.locator('#native-review-form input[type=checkbox]').check();
        await page.locator('button[data-scope-label=review]').click();
        await page.waitForFunction(note => document.querySelector('#native-scope-panel').textContent.includes(note), note);
      }
      const after = await rpc('state', 'scope-review');
      assert.equal(after.scope.versions.length, 2); assert.equal(after.scope.actions.length, 3);
      assert.deepEqual(after.scope.actions.filter(a => a.kind === 'review').map(a => a.version_ref), [original, original]);
      assert.ok(after.scope.actions.every(a => a.execution_authorized === false));
      assert.equal(after.brief_sha256, before.base_brief_sha256); assert.equal(after.index_sha256, before.index_sha256);
      assert.deepEqual(after.protocol, before.protocol); assert.deepEqual(after.intents, {}); assert.deepEqual(after.calls, []);
      assert.equal((await page.locator('#native-scope-panel').textContent()).includes('private-source-marker'), false);
      await page.close();
    });
    await check('delayed selected-version GET blocks the old form before POST and local intent', async () => {
      const p = await rpc('create-scope', 'scope-select'); const page = await pageFor(p); await scopeReady(page);
      const original = await page.locator('#native-scope-panel select[aria-label=version]').inputValue();
      await saveScope(page); await page.locator('#native-review-form [aria-label=note]').fill('Old form input.');
      await page.locator('#native-review-form input[type=checkbox]').check();
      const count = await scopeLedgerCount(page); let posts = 0, release, captured;
      const held = new Promise(resolve => {release = resolve;}), seen = new Promise(resolve => {captured = resolve;});
      page.on('request', r => {if (r.method() === 'POST') posts++;});
      await page.route('**/scope/versions/' + original, async route => {
        const response = await route.fetch(); captured(); await held; await route.fulfill({response});
      });
      await page.locator('#native-scope-panel select[aria-label=version]').selectOption(original); await seen;
      assert.equal(await page.locator('button[data-scope-label=review]').isDisabled(), true);
      await page.locator('#native-review-form').evaluate(form => form.dispatchEvent(new Event('submit', {cancelable: true, bubbles: true})));
      assert.equal(posts, 0); assert.equal(await scopeLedgerCount(page), count);
      release(); await page.waitForFunction(() => !document.querySelector('button[data-scope-label=review]').disabled);
      assert.deepEqual((await rpc('state', 'scope-select')).calls, []); await page.close();
    });
    await check('scope UTF-8 and lone-surrogate values reject before ledger and network', async () => {
      const p = await rpc('create-scope', 'scope-bound'); const page = await pageFor(p); await scopeChoice(page);
      let posts = 0; page.on('request', r => {if (r.method() === 'POST') posts++;});
      await page.locator('#native-scope-form [aria-label=reason]').fill('字'.repeat(7000));
      await page.locator('#native-scope-form [aria-label=original]').fill('語'.repeat(7000));
      await page.locator('button[data-scope-label=save]').click();
      await page.waitForFunction(() => document.querySelector('#native-scope-panel > [role=status]').textContent.length > 0);
      assert.equal(posts, 0); assert.equal(await scopeLedgerCount(page), 0);
      await page.locator('#workspaceLanguage').selectOption('zh-Hant');
      await page.waitForFunction(() => document.querySelector('#native-scope-panel > [role=status]').textContent === '決定過長或本機意圖儲存不可用');
      await page.locator('#native-scope-form [aria-label=reason]').fill('Reason');
      await page.locator('#native-scope-form [aria-label=original]').fill('Original instruction');
      await page.locator('#native-scope-form [aria-label=value]').evaluate(e => {e.value = String.fromCharCode(0xd800);});
      await page.locator('button[data-scope-label=save]').click();
      assert.equal(posts, 0); assert.equal(await scopeLedgerCount(page), 0);
      assert.equal((await rpc('state', 'scope-bound')).scope.versions.length, 1); await page.close();
    });
    await check('lost scope response recovers the saved version with GET and no execution', async () => {
      const p = await rpc('create-scope', 'scope-lost'); const page = await pageFor(p); await scopeChoice(page);
      let posts = 0;
      await page.route('**/api/native/projects/' + p.ref + '/scope/versions', async route => {
        posts++; const response = await route.fetch(); assert.equal(response.status(), 200); await route.abort('failed');
      });
      await page.locator('button[data-scope-label=save]').click();
      await page.waitForFunction(() => document.querySelector('#native-scope-panel').textContent.includes('version-saved'));
      await refresh(page); await page.reload(); await connect(page, p); await scopeReady(page);
      await page.waitForFunction(() => document.querySelector('#native-scope-panel select[aria-label=version]').options.length === 2);
      const state = await rpc('state', 'scope-lost'); assert.equal(posts, 1);
      assert.equal(state.scope.versions.length, 2); assert.equal(state.scope.actions.length, 1);
      assert.equal(state.scope.execution_authorized, false); assert.deepEqual(state.calls, []);
      assert.equal(state.brief_sha256, state.base_brief_sha256); await page.close();
    });
  }
  assert.deepEqual(errors, []);
  return {status: 'passed', browser: await browser.version(), source_sha256: ready.source_sha256};
})().then(meta => finish(meta)).catch(error => finish({status: 'failed', error: error.stack}));
let finishing = false;
async function bounded(promise, label) {
  let timer;
  try {return await Promise.race([promise, new Promise((_, reject) => {
    timer = setTimeout(() => reject(Error(label + ' timed out')), 5000);
  })]);} finally {clearTimeout(timer);}
}
async function finish(meta) {
  if (finishing) return;
  finishing = true;
  process.exitCode = 1;
  const cleanup = [];
  try {if (browser) await bounded(browser.close(), 'browser close');}
  catch (error) {cleanup.push(error.message);}
  try {
    if (child.exitCode === null && child.signalCode === null && !childFailure) {
      const exited = new Promise(resolve => child.once('exit', resolve));
      fs.appendFileSync(control, '{"op":"stop"}\n');
      await bounded(exited, 'fixture stop');
    }
    if (child.exitCode !== 0 || child.signalCode !== null) cleanup.push('fixture exit was not successful');
  } catch (error) {cleanup.push(error.message);}
  finally {if (child.exitCode === null && child.signalCode === null) child.kill();}
  if (cleanup.length) meta = {...meta, status: 'failed', cleanup};
  const receipt = {...meta, source_sha256: sourceHashes, served_sha256: servedHashes,
    results, page_errors: errors, diagnostics, stderr};
  try {fs.writeFileSync(options.output, JSON.stringify(receipt, null, 2) + '\n', {flag: 'wx'});}
  catch (error) {console.error('receipt persistence failed: ' + error.message); return;}
  console.log(JSON.stringify({status: receipt.status, tests: results.length, passed: results.filter(r => r.status === 'passed').length, output: options.output}));
  process.exitCode = receipt.status === 'passed' ? 0 : 1;
}
for (const signal of ['SIGINT', 'SIGTERM']) process.once(signal, () => finish({status: 'failed', error: signal}));
