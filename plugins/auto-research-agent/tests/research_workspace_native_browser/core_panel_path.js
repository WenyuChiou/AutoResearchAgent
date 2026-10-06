const fs = require('fs');
const path = require('path');
const assert = require('assert/strict');
const { chromium } = require('playwright');
const TARGET_URL = process.env.TARGET_URL;
const OUTPUT = process.env.WIKI_BROWSER_OUTPUT;
const checks = [];
const check = (name, actual, expected) => { assert.deepEqual(actual, expected, name); checks.push(name); };
(async () => {
  assert.match(TARGET_URL, /^http:\/\/127\.0\.0\.1:[0-9]+$/);
  const browser = await chromium.launch({headless: false});
  const context = await browser.newContext({viewport: {width: 1440, height: 1000}});
  const page = await context.newPage();
  const errors = [], calls = [];
  page.on('pageerror', error => errors.push(String(error)));
  page.on('request', request => { if (request.url().startsWith(TARGET_URL + '/api/')) calls.push(request.method()); });
  await context.route('**/*', route => new URL(route.request().url()).origin === TARGET_URL ? route.continue() : route.abort());
  const connect = async project => {
    await page.locator('[aria-label="project"]').fill(project);
    await page.locator('[aria-label="credential"]').fill('a'.repeat(40));
    await page.getByRole('button', {name: 'Read session', exact: true}).click();
    await page.locator('#native-binding').getByText(project, {exact: false}).waitFor();
  };
  try {
    await page.goto(TARGET_URL, {waitUntil: 'networkidle', timeout: 15000});
    check('English first load', await page.locator('html').getAttribute('lang'), 'en');
    check('First load has no API actions or reads', calls, []);
    await connect('project-a');
    const question = 'Synthetic question project-a <source-value>';
    check('Verbatim pending source question', await page.getByLabel(question, {exact: true}).count(), 1);
    await page.evaluate(() => document.documentElement.lang = 'zh-Hant');
    check('Localization preserves source question', await page.getByLabel(question, {exact: true}).count(), 1);
    await page.evaluate(() => document.documentElement.lang = 'en');
    await page.getByLabel(question, {exact: true}).fill('synthetic-answer');
    check('Credential field cleared after connection', await page.locator('[aria-label="credential"]').inputValue(), '');
    await page.route('**/answers', async route => { await route.fetch(); await route.abort('failed'); });
    await page.getByRole('button', {name: 'Send answer', exact: true}).evaluate(button => { button.click(); button.click(); });
    await page.locator('#native-history').getByText('"status": "dispatched"', {exact: false}).waitFor();
    check('Repeated click plus lost response has one POST', calls.filter(method => method === 'POST').length, 1);
    await page.getByRole('button', {name: 'Refresh history', exact: true}).click();
    check('Refresh does not POST', calls.filter(method => method === 'POST').length, 1);
    const storage = await page.evaluate(() => Object.values(sessionStorage).map(JSON.parse));
    check('Stored intent contains only key/kind/target', Object.keys(storage[0][0]).sort(), ['key', 'kind', 'target']);
    check('Credential absent from session storage', JSON.stringify(storage).includes('a'.repeat(40)), false);
    check('Answer absent from session storage', JSON.stringify(storage).includes('synthetic-answer'), false);
    await connect('project-b');
    check('Project switch shows correct pending question', await page.getByLabel('Synthetic question project-b <source-value>', {exact: true}).inputValue(), '');
    check('Project switch does not POST', calls.filter(method => method === 'POST').length, 1);
    await page.reload({waitUntil: 'networkidle'});
    check('Reload leaves credentials empty', await page.locator('[aria-label="credential"]').inputValue(), '');
    await connect('project-a');
    check('Reconnect hides already sent question', await page.getByRole('button', {name: 'Send answer', exact: true}).count(), 0);
    check('Reconnect retains dispatched history', await page.locator('#native-history').getByText('"status": "dispatched"', {exact: false}).count(), 1);
    check('Reload/reconnect never resends', calls.filter(method => method === 'POST').length, 1);
    check('Sent source question is no longer pending', await page.getByLabel(question, {exact: true}).count(), 0);
    check('No page errors', errors, []);
    await page.locator('#native-session-panel').screenshot({path: path.join(OUTPUT, 'panel.png')});
    fs.writeFileSync(path.join(OUTPUT, 'browser-result.json'), JSON.stringify({status:'PASS', checks, api_requests: calls, browser_version: browser.version(), playwright_version: require('playwright/package.json').version}, null, 2));
    console.log(JSON.stringify({status:'PASS', checks:checks.length, posts:calls.filter(method=>method==='POST').length}));
  } catch (error) {
    fs.writeFileSync(path.join(OUTPUT, 'browser-result.json'), JSON.stringify({status:'FAIL', checks, error:String(error), api_requests:calls}, null, 2));
    throw error;
  } finally {
    await context.close();
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode=1; });
