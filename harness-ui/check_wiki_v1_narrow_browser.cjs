// Wiki V1 narrow-screen check (Simplified Chinese). Read-only: opens pages, resizes, presses keys on the menu button.
// usage: WIKI_V1_PROJECT=<ref with data> WIKI_V1_EMPTY=<ref without delivery> node check_wiki_v1_narrow_browser.cjs <playwright-module-path> <origin> <chrome.exe> [out-dir] [widths]
// For every page and width <= 900 it asserts: no horizontal page overflow, the main column is >= 90% of the viewport,
// nothing outside a scroll box sticks out past the viewport, the menu button is a visible 44px target, the sidebar
// links are folded until the button is used, and Enter/Space open and Escape closes the menu. At 1440 the button is
// not shown and the sidebar is still 232px. English and Traditional Chinese pages keep the old layout (no data-v1, no menu button).
const path = require('node:path');
const [playwrightPath, origin, chrome, outDir, widthsArg] = process.argv.slice(2);
const {chromium} = require(playwrightPath);
const widths = (widthsArg || '390,600,900,1440').split(',').map(Number);
const P1 = process.env.WIKI_V1_PROJECT, P2 = process.env.WIKI_V1_EMPTY || P1;
const scenarios = [
 {n:'home', p:'/#lang=zh-CN'}, {n:'stage1', p:`/#${P1}?stage=1&lang=zh-CN`}, {n:'stage1-scope', p:`/#${P2}?stage=1&lang=zh-CN`},
 {n:'stage2', p:`/#${P1}?stage=2&lang=zh-CN`}, {n:'stage3', p:`/#${P1}?stage=3&lang=zh-CN`, inject:true},
 {n:'settings', p:`/#${P1}?stage=1&lang=zh-CN`, click:'[data-page="settings"]'},
];
const metrics = () => {
 const vw = innerWidth, main = document.querySelector('.hs-main')?.getBoundingClientRect();
 const contained = e => { for (let p = e.parentElement; p && p !== document.body; p = p.parentElement) { const o = getComputedStyle(p).overflowX; if (o === 'auto' || o === 'scroll' || o === 'hidden') return true; } return false; };
 const sticks = [...document.querySelectorAll('.hs-content *, .hs-topbar *')].filter(e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.right > vw + 1 && !contained(e) && getComputedStyle(e).position !== 'fixed'; }).slice(0, 3).map(e => String(e.className).slice(0, 40));
 const btn = document.querySelector('[data-v1-menu]'), br = btn?.getBoundingClientRect(), side = document.querySelector('.v1-side');
 const navHidden = !!side && [...side.querySelectorAll('.v1-nav-item')].every(n => n.getBoundingClientRect().height === 0);
 const small = [...document.querySelectorAll('.hs-main button:not(:disabled), .hs-main summary, .hs-main select')].filter(e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 && r.height < 43.5; }).length;
 return {sw: document.documentElement.scrollWidth, vw, main: main ? Math.round(main.width) : 0, sticks, v1: !!document.querySelector('[data-v1]'),
  btn: !!btn && getComputedStyle(btn).display !== 'none', btnW: br ? Math.round(br.width) : 0, btnH: br ? Math.round(br.height) : 0, navHidden, sideW: side ? Math.round(side.getBoundingClientRect().width) : 0, small};
};
(async () => {
 const browser = await chromium.launch({headless: true, executablePath: chrome, args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist']});
 let failed = 0; const report = (ok, text) => { if (!ok) failed++; console.log((ok ? 'ok   ' : 'FAIL ') + text); };
 for (const s of process.env.ONLY_OLD_LANGS ? [] : scenarios) for (const w of widths) {
  const page = await browser.newPage({viewport: {width: w, height: w >= 1280 ? 1000 : 844}});
  const errors = [], writes = [];
  page.on('console', m => { if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) errors.push(m.text().slice(0, 160)); });
  page.on('pageerror', e => errors.push('pageerror ' + e.message));
  page.on('request', r => { if (r.method() !== 'GET') writes.push(r.method() + ' ' + r.url()); });
  if (s.inject) { process.env.WIKI_V1_PROJECT = P1; await require('./check_wiki_v1_fixtures/stage3-inject.cjs')(page); }
  await page.goto(origin + s.p, {waitUntil: 'networkidle'});
  await page.waitForFunction(() => !!document.querySelector('.hs-product[data-v1]') && !document.querySelector('[data-v1-status="run"]'), null, {timeout: 60000}).catch(() => {});
  await page.waitForTimeout(2500);
  if (s.click) { await page.click(s.click).catch(() => {}); await page.waitForTimeout(1500); }
  const m = await page.evaluate(metrics), problems = [];
  if (!m.v1) problems.push('no data-v1');
  if (w <= 900) {
   if (m.sw > m.vw) problems.push(`page overflow ${m.sw}>${m.vw}`);
   if (m.main < 0.9 * m.vw) problems.push(`main ${m.main} < 90% of ${m.vw}`);
   if (m.sticks.length) problems.push('sticks out: ' + m.sticks.join(','));
   if (!m.btn || m.btnH < 44 || m.btnW < 44) problems.push(`menu button missing or small ${m.btnW}x${m.btnH}`);
   if (!m.navHidden) problems.push('sidebar not folded');
   if (s.n === 'home') {
    const button = page.locator('[data-v1-menu]');
    const state = () => button.getAttribute('aria-expanded');
    await button.focus(); await page.keyboard.press('Enter');
    if (await state() !== 'true' || !(await page.locator('.v1-nav-item').first().isVisible())) problems.push('Enter did not open the menu');
    await page.keyboard.press('Escape');
    if (await state() !== 'false' || !(await page.evaluate(() => document.activeElement?.matches('[data-v1-menu]')))) problems.push('Escape did not close and refocus');
    await page.keyboard.press('Space');
    if (await state() !== 'true') problems.push('Space did not open the menu');
    await page.keyboard.press('Space');
    if (await state() !== 'false') problems.push('Space did not close the menu');
    await button.click(); await page.click('.v1-nav-item[data-page="settings"]'); await page.waitForTimeout(800);
    if (await page.locator('[data-v1-menu]').getAttribute('aria-expanded') !== 'false') problems.push('picking an item left the menu open');
   }
  } else if (m.btn || m.sideW !== 232) problems.push(`desktop changed: button ${m.btn}, sidebar ${m.sideW}`);
  for (const e of errors) problems.push('console: ' + e);
  for (const x of writes) problems.push('write request: ' + x);
  report(!problems.length, `${s.n} w=${w} scrollW=${m.sw} main=${m.main} controls<44px=${m.small}${problems.length ? ' :: ' + problems.join('; ') : ''}`);
  if (outDir) await page.screenshot({path: path.join(outDir, `${s.n}-${w}.png`), fullPage: true});
  await page.close();
 }
 // English and Traditional Chinese keep the old layout.
 for (const lang of ['en', 'zh-TW']) for (const w of [390, 1440]) {
  const page = await browser.newPage({viewport: {width: w, height: 844}});
  await page.goto(`${origin}/#${P1}?stage=1&lang=${lang}`, {waitUntil: 'networkidle'}); await page.waitForTimeout(3500);
  const m = await page.evaluate(metrics);
  report(!m.v1 && !m.btn, `${lang} w=${w} data-v1=${m.v1} menu-button=${m.btn}`);
  await page.close();
 }
 await browser.close();
 console.log(failed ? `${failed} failed` : 'all passed'); process.exit(failed ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
