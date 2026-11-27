// Wiki V1 page check (Simplified Chinese). Read-only: it only opens pages and switches tabs.
// usage: node check_wiki_v1_unify_browser.cjs <playwright-module-path> <origin> <config.json> [out-dir]
// config: {"chrome": "...chrome.exe", "scenarios": [{"name", "path", "clicks": [selector...], "inject": optional fixed-response file}]}
// For every scenario it asserts, on the visible page only:
//  1. no retired block (titles/selectors listed below) is visible;
//  2. no internal word from DESIGN 2.6 appears in visible body text (code/pre excluded);
//  3. no console error or page error;
//  4. no non-GET request was sent while viewing;
//  5. every visible disabled action button has a reason text next to it.
const fs = require('node:fs');
const path = require('node:path');
const [playwrightPath, origin, configPath, outDir] = process.argv.slice(2);
const {chromium} = require(playwrightPath);
const config = JSON.parse(fs.readFileSync(configPath, 'utf8'));

const RETIRED_TEXT = ['切换项目', '保存输出与文献审阅', '运行进度与反馈', 'Codex 协作与人工审阅', 'Loop与人工审查', 'Loop 与人工审查',
 'STAGE 03 / 06', 'STAGE 01 / 06', 'STAGE 02 / 06', '设计与可行性', '过程与决策', '答复、范围与版本', '改进与验证', '界面改进',
 '登记当前交付', '运行 Stage 2 · 尚未接通', '启动离线问答案例', '初始化 Stage1 本地记录', '运行已登记案例任务', '未派发记录',
 '运行反馈与来源', '操作与保存状态', '项目与研究主题', '加入文件与阶段接续', '研究方向比较工作台', '文献知识网络'];
const RETIRED_SELECTORS = ['.lp-topic', '.lp-operations', '.lp-results', '.rf-panel', '.v7-assistant', '.wiki-shell-state',
 '.wiki-s1-project', '.wiki-s2-project', '.hs-stage-nav', '[data-v7-ui]', '.hs-preview', '.hs-footer'];
const INTERNAL_WORDS = ['undefined', 'NaN', '[object Object]', 'Unknown', 'unverified', 'NOT_PRESENT', 'NOT_VERIFIED', 'OPEN_PER_PUBLISHED',
 'saved_reference_sources', 'required', 'planned / unconnected', '受信操作者', '公共投影', 'note-evidence-', 'saved-import-', 'stage2-continuation'];
const REASON_CLASS = /reason|why|v1-reason|ws3-why-off|wiki-s2-reason|hint/;

async function inspect(page) {
 return page.evaluate(({retiredText, retiredSelectors, internal, reasonClass}) => {
  const visible = node => { if (!node || !node.isConnected) return false; const r = node.getBoundingClientRect(); const s = getComputedStyle(node); return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const root = document.querySelector('.hs-product') || document.body;
  const problems = [], reasonRe = new RegExp(reasonClass);
  for (const sel of retiredSelectors) for (const node of root.querySelectorAll(sel)) if (visible(node)) problems.push('旧版块可见: ' + sel);
  const text = root.innerText;
  // Code blocks and saved paper titles/quotes are source text, not interface wording.
  let body = text;
  for (const n of root.querySelectorAll('code, pre, .live-record, [data-s1-paper] strong, .wiki-s1-selection h3, .wiki-s1-card > h2, blockquote')) if (visible(n) && n.innerText) body = body.split(n.innerText).join('');
  for (const t of retiredText) if (body.includes(t)) problems.push('旧标题可见: ' + t);
  for (const w of internal) if (body.includes(w)) problems.push('内部词可见: ' + w + ' …' + body.slice(Math.max(0, body.indexOf(w) - 30), body.indexOf(w) + 30).replace(/\s+/g, ' '));
  const exempt = b => b.closest('.v1-side, .v1-menu, [role="tablist"], .wiki-s1-chips, .wiki-s2-chips, .wiki-s2-pager, .wiki-home-filters') || b.matches('[role="tab"], [aria-pressed]');
  for (const b of root.querySelectorAll('button:disabled')) {
   if (!visible(b) || exempt(b)) continue;
   const around = [b.nextElementSibling, b.parentElement?.nextElementSibling, ...(b.parentElement?.children || [])].filter(Boolean);
   const ok = around.some(n => n !== b && reasonRe.test(String(n.className)) && visible(n) && n.innerText.trim()) ||
    [...(b.closest('section, form, div')?.querySelectorAll('small, p') || [])].some(n => visible(n) && /现在还不能|请先|正在|还没有|还没|不能在这里改|先核对|没有/.test(n.innerText));
   if (!ok) problems.push('灰按钮没有原因: ' + b.innerText.trim().slice(0, 30));
  }
  return problems;
 }, {retiredText: RETIRED_TEXT, retiredSelectors: RETIRED_SELECTORS, internal: INTERNAL_WORDS, reasonClass: REASON_CLASS.source}).then(list => list);
}

(async () => {
 const browser = await chromium.launch({headless: true, executablePath: config.chrome, args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist']});
 let failed = 0;
 for (const sc of config.scenarios) {
  const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
  const errors = [], writes = [];
  page.on('console', m => { if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) errors.push(m.text().slice(0, 200)); });
  page.on('pageerror', e => errors.push('pageerror: ' + e.message));
  page.on('response', r => { if (r.status() >= 500) errors.push('HTTP ' + r.status() + ' ' + r.url()); });
  page.on('request', r => { if (r.method() !== 'GET') writes.push(r.method() + ' ' + r.url()); });
  if (sc.inject) await require(path.resolve(sc.inject))(page);
  await page.goto(origin + sc.path, {waitUntil: 'networkidle'});
  await page.waitForTimeout(sc.wait || 4000);
  for (const click of sc.clicks || []) { await page.click(click); await page.waitForTimeout(1500); }
  const problems = (await inspect(page)).map(String);
  for (const e of errors) problems.push('控制台报错: ' + e);
  for (const w of writes) problems.push('只看不点却发了写请求: ' + w);
  if (outDir) await page.screenshot({path: path.join(outDir, sc.name + '.png'), fullPage: true});
  console.log((problems.length ? 'FAIL ' : 'PASS ') + sc.name + (problems.length ? '\n  - ' + [...new Set(problems)].join('\n  - ') : ''));
  if (problems.length) failed++;
  await page.close();
 }
 await browser.close();
 console.log(`${config.scenarios.length - failed}/${config.scenarios.length} scenarios passed`);
 process.exit(failed ? 1 : 0);
})().catch(error => { console.error(error); process.exit(2); });
