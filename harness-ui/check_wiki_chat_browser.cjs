// Wiki V1 chat drawer, real-browser check. No model, no Codex process: chat responses are fixed fixtures
// injected at the network layer (except the "default off" scenario, which talks to the real host).
// usage: node check_wiki_chat_browser.cjs <playwright-module-path> <chrome.exe> <origin> <project-ref> [out-dir]
const fs = require('node:fs');
const path = require('node:path');
const [playwrightPath, chromePath, origin, ref, outDir] = process.argv.slice(2);
const {chromium} = require(playwrightPath);
if (outDir) fs.mkdirSync(outDir, {recursive: true});

const state = (panel, extra = {}) => Object.assign({
 kind:'V9HarnessConversation', project_ref:ref, stage:1, panel_state:panel, content_hidden:false, panel_reason:null, enabled:true, can_send:panel === 'ready',
 connect_check:{ok:true, reasons:[]}, spend_check:{ok:true, reasons:[], remaining_turns:2}, model:'fixture-model', effort:'high', expires_at:Math.floor(Date.now() / 1000) + 3600,
 turn_seconds:120, max_turns:3, reserved_turns:1, remaining_turns:2, turns:[], sessions:[], hidden_turn_count:0, controllable_turn_ids:[], budget_identity_preserved:false,
 admission_blockers:[], other_turn:null, read_only:true, research_execution:false,
 context:{project_ref:ref, stage:1, supported_actions:['state', 'materials', 'read_material'], expected_materials:[], materials:[
  {id:'m1', name:'阅读笔记.md', sha256:'0123456789abcdef', origin:'registered-file', readable:{ok:true, reason:null, text:'能读'}},
  {id:'m2', name:'原文.pdf', sha256:'fedcba9876543210', origin:'registered-file', readable:{ok:false, reason:'not-plain-text', text:'不能读：只能读登记过的纯文本'}},
  {id:'m3', name:'大文件.txt', sha256:'1111222233334444', origin:'registered-file', readable:{ok:false, reason:'too-large', text:'不能读：超过 64 KiB'}}]}
}, extra);
const turn = (id, status, extra = {}) => Object.assign({id, session_id:'s1', status, user_text:'列出当前阶段已登记的材料，先告诉我哪些能读、哪些还不能读。', response:'', outputs:[], notices:[], pending:null, created_at:Math.floor(Date.now() / 1000) - 60}, extra);
const done = turn('t1', 'completed', {response:'阅读笔记.md 能读；原文.pdf 和大文件.txt 现在不能读。', outputs:[{call_id:'c', action:'read_material', value:{material_id:'m1'}, model_saw_truncated:true}], notices:[{kind:'auto-declined-command'}]});
const reason = text => ({panel_reason:{code:'x', group:'g', text}});

const STATES = {
 'ready': state('ready', {sessions:[{id:'s1'}], turns:[done]}),
 'ready-empty': state('ready'),
 'sending': state('sending', {sessions:[{id:'s1'}], turns:[turn('t2', 'running')], controllable_turn_ids:['t2']}),
 'asking': state('sending', {sessions:[{id:'s1'}], turns:[turn('t2', 'waiting', {pending:{id:'r1', sha256:'h', kind:'questions', questions:[{id:'a', question:'只看当前课题吗？'}, {id:'b', question:'要包含被排除的文献吗？'}]}})], controllable_turn_ids:['t2']}),
 'unknown': state('unknown-result', {sessions:[{id:'s1'}], turns:[turn('t3', 'unknown', {error:'chat-deadline-native-terminal-unconfirmed', error_reason:{text:'超过时限，结果没确认'}})]}),
 'failed': state('ready', {sessions:[{id:'s1'}], turns:[turn('t4', 'failed', {error:'chat-response-too-large', error_reason:{code:'chat-response-too-large', text:'回答太长，没有保存'}})]}),
 'blocked-budget': state('blocked', Object.assign(reason('调用次数已用完，不会自动追加'), {can_send:false, remaining_turns:0, reserved_turns:3, admission_blockers:['chat-cumulative-budget-exhausted']})),
 'blocked-expired': state('blocked', Object.assign(reason('对话许可已到期，发送关闭；已用额度和原回答保留'), {can_send:false, admission_blockers:['chat-operator-lease-expired'], sessions:[{id:'s1'}], turns:[done]})),
 'no-permit': state('no-permit', Object.assign(reason('这个课题还没有对话许可'), {can_send:false, admission_blockers:['chat-continuation-project-stage-not-authorized']})),
 'login': state('login-required', {content_hidden:true, can_send:false, context:{materials:[], content_hidden:true}}),
 'other-turn': state('other-turn', {can_send:false, other_turn:{project_ref:'project-other', stage:2, turn_id:'t9', created_at:Math.floor(Date.now() / 1000) - 600}}),
 'stage-unconnected': state('stage-unconnected', {can_send:false, model:'fixture-model', context:{materials:[], expected_materials:[{category:'来源包', status:'reader-not-connected'}, {category:'原文定位', status:'reader-not-connected'}]}}),
 'zero-allowance': state('blocked', Object.assign(reason('调用次数已用完，不会自动追加'), {can_send:false, max_turns:0, reserved_turns:0, remaining_turns:0})),
 'restarted': state('sending', {sessions:[{id:'s1'}], turns:[turn('t5', 'running')], controllable_turn_ids:[]}),
 'continuation': state('unknown-result', {budget_identity_preserved:true, sessions:[{id:'s1'}], turns:[turn('t3', 'unknown')]}),
 'hidden-older': state('ready', {sessions:[{id:'s1'}], turns:[done], hidden_turn_count:7})
};

const posts = [];
async function open(browser, name, stage, handler, wait = 'networkidle') {
 const page = await browser.newPage({viewport:{width:1440, height:900}});
 const errors = [];
 page.on('console', m => { if (m.type() === 'error' && !/status of 404/.test(m.text())) errors.push(m.text()); }); // the existing Stage 1 readback of a not-yet-written progression record answers 404
 page.on('pageerror', e => errors.push(String(e)));
 posts.length = 0;
 await page.route('**/api/v9/chat/**', async route => {
  const request = route.request();
  if (request.method() === 'POST') { posts.push({url:request.url().split('/').pop(), body:JSON.parse(request.postData() || '{}')}); }
  await handler(route, request);
 });
 await page.goto(`${origin}/#${encodeURIComponent(ref)}?stage=${stage}&lang=zh-CN`, {waitUntil:wait});
 await page.waitForTimeout(wait === 'networkidle' ? 3500 : 2500);
 return {page, errors};
}
const json = (route, value, status = 200) => route.fulfill({status, contentType:'application/json', body:JSON.stringify(value)});
const shot = (page, name) => outDir ? page.screenshot({path:path.join(outDir, name + '.png')}) : null;
const text = page => page.evaluate(() => document.querySelector('.wc-drawer')?.innerText || '');
let failed = 0;
function report(name, problems) {
 console.log((problems.length ? 'FAIL ' : 'PASS ') + name + (problems.length ? '\n  - ' + [...new Set(problems)].join('\n  - ') : ''));
 if (problems.length) failed++;
}

(async () => {
 const browser = await chromium.launch({executablePath:chromePath, headless:true});
 const must = (problems, ok, message) => { if (!ok) problems.push(message); };

 // 1. Default off, against the real host: tab says so, drawer says why, nothing but GET leaves the page.
 {
  const problems = [];
  const writes = [];
  const page = await browser.newPage({viewport:{width:1440, height:900}});
  const errors = [];
  page.on('console', m => { if (m.type() === 'error' && !/status of 404/.test(m.text())) errors.push(m.text()); }); // the existing Stage 1 readback of a not-yet-written progression record answers 404
  page.on('request', r => { if (r.method() !== 'GET') writes.push(r.method() + ' ' + r.url()); });
  const states = [];
  page.on('response', async r => { if (r.url().includes('/api/v9/chat/state')) states.push(await r.json().catch(() => null)); });
  await page.goto(`${origin}/#${encodeURIComponent(ref)}?stage=1&lang=zh-CN`, {waitUntil:'networkidle'});
  await page.waitForTimeout(3500);
  must(problems, await page.locator('.wc-tab').isVisible(), '收起时没有「Codex 对话」竖向标签');
  must(problems, /对话未启用/.test(await page.locator('.wc-tab').innerText()), '标签上没有写「对话未启用」');
  must(problems, states.length >= 1 && states[0]?.panel_state === 'not-configured', '真实后台没有回「未配置」: ' + JSON.stringify(states[0]?.panel_state));
  await shot(page, 'default-off-closed');
  await page.click('.wc-tab');
  await page.waitForTimeout(500);
  const body = await text(page);
  must(problems, /本机还没有配置对话/.test(body), '抽屉里没写原因');
  must(problems, /页面上不能配置，也不能授权/.test(body), '没写页面不能授权');
  must(problems, await page.locator('[data-wc-send]').isDisabled(), '没配置时发送按钮没灰');
  must(problems, /本机还没有配置对话/.test(await page.locator('[data-wc-reason]').innerText()), '灰按钮没写原因');
  must(problems, (await page.locator('.wc-drawer').boundingBox()).width <= 381, '抽屉宽度不是 380px');
  must(problems, !(await page.locator('.hs-main').evaluate(n => n.getBoundingClientRect().width < 900)), '抽屉挤压了主区');
  await shot(page, 'default-off-open');
  await page.keyboard.press('Escape');
  await page.waitForTimeout(300);
  must(problems, await page.locator('.wc-tab').isVisible() && !(await page.locator('.wc-drawer').isVisible()), 'Esc 没有收起');
  for (const w of writes) problems.push('发了写请求: ' + w);
  for (const e of errors) problems.push('控制台报错: ' + e);
  await page.close();
  report('default-off (real host)', problems);
 }

 // 2. Every state, one screenshot each, with the common asserts.
 const expectations = {
  'ready':[/可以发送/, /已预留 1 轮，每轮最多 120 秒 · 剩余 2 轮/, /本轮已完成/, /读取了：阅读笔记\.md · 模型调用 1 次/, /结果较长，Codex 只看到了开头/, /Codex 请求执行命令，已自动拒绝/],
  'ready-empty':[/这个课题在这一段还没有对话/, /不能读：只能读登记过的纯文本/, /不能读：超过 64 KiB/, /本阶段文件 · 3 份登记材料/],
  'sending':[/等待回复/, /中断本轮 Codex/, /只停这一次对话/],
  'asking':[/等你回答 Codex 的问题/, /Codex 在向你提问/, /提交答复/],
  'unknown':[/这一轮的结果还没确认/, /只读核对原任务/, /不会重发/, /先核对上一轮/],
  'failed':[/本轮失败/, /回答太长，没有保存/],
  'blocked-budget':[/调用次数已用完，不会自动追加/, /已预留 3 轮.*剩余 0 轮/],
  'blocked-expired':[/对话许可已到期，发送关闭；已用额度和原回答保留/],
  'no-permit':[/这个课题还没有对话许可/, /Stage 1 整轮运行的同意书不能代用/, /去连接与设置/, /重新检查/],
  'login':[/还没登录 Codex/, /请在 Codex 自己的界面登录。这里不会要你输入密钥/],
  'other-turn':[/别处有一轮对话还没结束/, /这台电脑上同一时间只能有一轮对话/, /去那一轮看看/],
  'stage-unconnected':[/这一段的材料还没接通，对话关着/, /接通后会读的材料[\s\S]*来源包[\s\S]*原文定位/],
  'zero-allowance':[/已预留 0 轮.*剩余 0 轮/, /调用次数已用完/],
  'restarted':[/服务重启过，这一轮只能核对/, /只读核对原任务/],
  'continuation':[/这份许可下不能核对，请联系操作者/],
  'hidden-older':[/更早的对话没有显示/]
 };
 for (const [name, fixture] of Object.entries(STATES)) {
  const {page, errors} = await open(browser, name, 1, (route, request) => request.method() === 'GET' ? json(route, fixture) : json(route, {}, 500));
  const problems = [];
  await page.click('.wc-tab');
  await page.waitForTimeout(700);
  const body = await text(page);
  for (const re of expectations[name] || []) must(problems, re.test(body), '缺少: ' + re);
  must(problems, !/授权这个课题|点此授权|签同意书/.test(body), '页面上出现了授权入口');
  if (fixture.turns.length) must(problems, ((await page.locator('.wc-messages').boundingBox()) || {height:0}).height >= 80, '消息区被压没了（看不到对话）');
  const raw = body.match(/(?<![\w/.#=-])[a-z0-9]+(?:-[a-z0-9]+){2,}(?![\w/.-])/);
  must(problems, !raw || (await page.locator('.wc-drawer code').allInnerTexts()).join(' ').includes(raw[0]), '后台代码出现在正文: ' + (raw && raw[0]));
  for (const bad of ['undefined', 'NaN', '[object Object]']) must(problems, !body.includes(bad), '内部词: ' + bad);
  const gray = await page.evaluate(() => [...document.querySelectorAll('.wc-drawer button:disabled')].filter(b => b.offsetParent).map(b => ({label:b.innerText.trim(), reason:[...b.parentElement.parentElement.querySelectorAll('.wc-reason')].some(n => n.offsetParent && n.innerText.trim()) || [...b.parentElement.querySelectorAll('.wc-reason')].some(n => n.offsetParent && n.innerText.trim())})));
  for (const g of gray) must(problems, g.reason, '灰按钮没有原因: ' + g.label);
  for (const e of errors) problems.push('控制台报错: ' + e);
  must(problems, posts.length === 0, '只看不点却发了写请求');
  await shot(page, name);
  await page.close();
  report('state ' + name, problems);
 }

 // 3. Reading and read-failed.
 {
  const {page, errors} = await open(browser, 'reading', 1, async route => { await new Promise(r => setTimeout(r, 9000)); await json(route, STATES.ready).catch(() => {}); }, 'domcontentloaded');
  const problems = [];
  await page.click('.wc-tab'); await page.waitForTimeout(400);
  const body = await text(page);
  must(problems, /正在读取对话状态/.test(body) && /不调用模型/.test(body) && /读取完成后才能发送/.test(body), '读取中状态不对: ' + body.slice(0, 120));
  await shot(page, 'reading');
  await page.close(); report('state reading', problems.concat(errors));
 }
 {
  const {page} = await open(browser, 'read-failed', 1, route => route.abort());
  const problems = [];
  await page.click('.wc-tab'); await page.waitForTimeout(700);
  const body = await text(page);
  must(problems, /对话状态没读到/.test(body) && /重新检查/.test(body), '读取失败状态不对: ' + body.slice(0, 120));
  must(problems, await page.locator('[data-wc-send]').isDisabled(), '读取失败时发送没灰');
  await shot(page, 'read-failed');
  await page.close(); report('state read-failed', problems);
 }

 // 4. Interaction: chips only fill, byte limit, send body, idempotent key, ask answer, stop, reconcile.
 {
  let current = STATES['ready-empty'];
  const {page, errors} = await open(browser, 'flow', 1, (route, request) => {
   if (request.method() === 'GET') return json(route, current);
   const url = request.url().split('/').pop(), body = JSON.parse(request.postData() || '{}');
   if (url === 'send') { current = STATES['sending']; return json(route, Object.assign(turn('t2', 'starting'), {user_text:body.text})); }
   if (url === 'answer') { current = STATES['ready']; return json(route, {saved:true, turn_id:body.turn_id, request_id:body.request_id}); }
   if (url === 'stop') return json(route, turn('t2', 'stop-requested'));
   if (url === 'reconcile') { current = STATES['ready']; return json(route, turn('t3', 'completed', {response:'已补回', reconciliation:null})); }
   return json(route, {}, 404);
  });
  const problems = [];
  await page.click('.wc-tab'); await page.waitForTimeout(600);
  must(problems, await page.locator('[data-wc-send]').isDisabled() && /消息是空的/.test(await page.locator('[data-wc-reason]').innerText()), '空消息可以发或没写原因');
  await page.click('[data-wc-chip="0"]');
  must(problems, (await page.inputValue('[data-wc-input]')).startsWith('读取本阶段已保存的交付'), '快捷提问没有填进输入框');
  must(problems, posts.length === 0, '点快捷提问就发了请求');
  must(problems, await page.locator('[data-wc-send]').isEnabled(), '有内容后发送还是灰的');
  await page.fill('[data-wc-input]', 'a'.repeat(8193));
  must(problems, await page.locator('[data-wc-send]').isDisabled() && /超过 8192 字节，没有发送/.test(await page.locator('[data-wc-reason]').innerText()), '超长消息没有拦住');
  await page.fill('[data-wc-input]', '这个课题现在有哪些材料？');
  await page.click('[data-wc-send]'); await page.waitForTimeout(900);
  const send = posts.find(p => p.url === 'send');
  must(problems, !!send && Object.keys(send.body).sort().join() === 'brief_sha256,input_version,key,project_ref,session_id,stage,text', '发送体字段不对: ' + JSON.stringify(send && Object.keys(send.body)));
  must(problems, send && send.body.key.length >= 12 && send.body.key.length <= 100 && Number.isInteger(send.body.input_version) && /^[0-9a-f]{64}$/.test(send.body.brief_sha256), '编号或绑定不合规');
  must(problems, await page.locator('[data-wc-input]').isDisabled(), '本轮进行中输入框没灰');
  must(problems, await page.locator('[data-wc-send]').isDisabled() && /本轮进行中/.test(await page.locator('[data-wc-reason]').innerText()), '本轮进行中发送没灰或没写原因');
  must(problems, await page.locator('[data-wc-stop]').isEnabled(), '没有中断按钮');
  await page.click('[data-wc-stop]'); await page.waitForTimeout(500);
  must(problems, posts.some(p => p.url === 'stop' && Object.keys(p.body).join() === 'turn_id'), '中断请求不对');
  current = STATES['asking']; await page.click('[data-wc-refresh]'); await page.waitForTimeout(700);
  await page.fill('[data-wc-ans="t2|a"]', '只看当前课题'); await page.fill('[data-wc-ans="t2|b"]', '不包含');
  await page.click('[data-wc-answer]'); await page.waitForTimeout(700);
  const answer = posts.find(p => p.url === 'answer');
  must(problems, !!answer && answer.body.request_id === 'r1' && answer.body.request_sha256 === 'h' && answer.body.value.a === '只看当前课题' && answer.body.value.b === '不包含', '答复请求不对: ' + JSON.stringify(answer));
  current = STATES['unknown']; await page.click('[data-wc-refresh]'); await page.waitForTimeout(700);
  await page.click('[data-wc-reconcile]'); await page.waitForTimeout(700);
  must(problems, posts.some(p => p.url === 'reconcile' && p.body.turn_id === 't3'), '核对请求不对');
  must(problems, posts.filter(p => p.url === 'send').length === 1, '发了不止一次 send');
  for (const e of errors) problems.push('控制台报错: ' + e);
  await shot(page, 'flow-end');
  await page.close(); report('flow: chip, byte limit, send, stop, answer, reconcile', problems);
 }

 // 5. A refused send shows the plain reason and keeps the words; a network drop keeps the same key.
 {
  let attempt = 0;
  const {page} = await open(browser, 'refuse', 1, (route, request) => {
   if (request.method() === 'GET') return json(route, STATES['ready-empty']);
   attempt++;
   if (attempt === 1) return route.abort();
   if (attempt === 2) return json(route, {error:'chat-cumulative-budget-exhausted', reason:{code:'chat-cumulative-budget-exhausted', group:'budget-exhausted', text:'调用次数已用完，不会自动追加'}, research_execution:false}, 409);
   return json(route, {error:'credential-rejected'}, 401);
  });
  const problems = [];
  await page.click('.wc-tab'); await page.waitForTimeout(500);
  await page.fill('[data-wc-input]', '试一下'); await page.click('[data-wc-send]'); await page.waitForTimeout(700);
  must(problems, /结果还没确认，不会自动重发/.test(await text(page)), '断网后没写「结果还没确认」');
  must(problems, (await page.inputValue('[data-wc-input]')) === '试一下', '断网后输入的话丢了');
  await page.click('[data-wc-send]'); await page.waitForTimeout(700);
  const keys = posts.filter(p => p.url === 'send').map(p => p.body.key);
  must(problems, keys.length === 2 && keys[0] === keys[1], '重发没有沿用同一个编号: ' + keys);
  must(problems, /调用次数已用完，不会自动追加/.test(await text(page)) && /看原始拒绝记录/.test(await text(page)), '被拒绝时没写人话原因或没有「看原始拒绝记录」');
  await page.click('[data-wc-tech]'); await page.waitForTimeout(300);
  must(problems, await page.locator('.wc-tech code.wc-mark').count() === 1, '技术细节里没有标黄原始代码');
  await shot(page, 'refused');
  await page.click('[data-wc-send]'); await page.waitForTimeout(700);
  must(problems, /页面的登录信息失效了，请从 Wiki 首页重新打开/.test(await text(page)), '401 没写登录信息失效');
  await page.close(); report('refused send, dropped network, expired page login', problems);
 }

 // 6. Stage 4-6 is closed without any chat request; open/closed is remembered per stage.
 {
  const seen = [];
  const {page, errors} = await open(browser, 'later', 4, route => { seen.push(route.request().url()); return json(route, STATES['ready']); });
  const problems = [];
  must(problems, await page.locator('.wc-tab').isVisible(), 'Stage 4 没有对话入口');
  await page.click('.wc-tab'); await page.waitForTimeout(400);
  const body = await text(page);
  must(problems, /这一段的材料还没接通，对话关着/.test(body) && /本阶段还没有开放/.test(body) && /实验执行助手/.test(body), 'Stage 4 状态不对');
  must(problems, !seen.some(u => /stage=[4-6]/.test(u)), 'Stage 4 不该发对话请求: ' + seen.join());
  await shot(page, 'stage4');
  await page.reload({waitUntil:'networkidle'}); await page.waitForTimeout(3000);
  must(problems, await page.locator('.wc-drawer').isVisible(), '重开后没有记住展开');
  for (const e of errors) problems.push('控制台报错: ' + e);
  await page.evaluate(() => localStorage.clear());
  await page.close(); report('stage 4 closed, open state remembered', problems);
 }

 // 7. Review fixes P2-1..P2-5.
 {
  const {page} = await open(browser, 'hostile', 1, (route, request) => request.method() === 'GET' ? json(route, state('x" onmouseover="alert(1)', {can_send:false})) : json(route, {}, 500));
  const problems = [];
  await page.click('.wc-tab'); await page.waitForTimeout(500);
  must(problems, (await page.locator('[onmouseover]').count()) === 0, '后台状态值变成了页面属性');
  must(problems, /对话许可没有通过核对，界面只读，发送关闭/.test(await text(page)), '未知状态没有按只读处理');
  await page.close(); report('P2-1 hostile state value stays inert', problems);
 }
 {
  let gets = 0;
  const {page} = await open(browser, 'poll-stop', 1, (route, request) => { if (request.method() === 'GET') gets++; return request.method() === 'GET' ? json(route, STATES['sending']) : json(route, {}, 500); });
  const problems = [];
  await page.click('.wc-tab');
  const before = gets; await page.waitForTimeout(4500);
  must(problems, gets - before >= 1, '进行中的一轮没有在轮询（对照组）');
  await page.click('.v1-nav-item[data-page="files"]'); await page.waitForTimeout(800);
  const after = gets; await page.waitForTimeout(6500);
  must(problems, gets === after, '离开阶段页后还在轮询: ' + (gets - after) + ' 次');
  await page.click('.v1-nav-item[data-page="workspace"]'); await page.waitForTimeout(1500);
  const lang = await page.locator('select[data-language], .v1-lang').first().isVisible().catch(() => false);
  must(problems, lang, '没有语言选择，无法测切换语言');
  if (lang) {
   const mark = gets;
   await page.selectOption('select[data-language], .v1-lang', 'en'); await page.waitForTimeout(800);
   const switched = gets; await page.waitForTimeout(5000);
   must(problems, gets === switched, '切换语言后还在轮询: ' + (gets - switched) + ' 次 (之前 ' + (switched - mark) + ')');
  }
  await page.close(); report('P2-2 polling stops when leaving the stage page or changing language', problems);
 }
 {
  let delayed = false;
  const {page} = await open(browser, 'switch-during-send', 1, async (route, request) => {
   if (request.method() === 'GET') return json(route, Object.assign({}, STATES['ready-empty'], {stage:Number(new URL(request.url()).searchParams.get('stage'))}));
   delayed = true; await new Promise(r => setTimeout(r, 3500));
   return json(route, turn('t-late', 'starting', {user_text:'来自 Stage 1'})).catch(() => {});
  });
  const problems = [];
  await page.click('.wc-tab'); await page.waitForTimeout(500);
  await page.fill('[data-wc-input]', 'Stage 1 的草稿'); await page.click('[data-wc-send]');
  await page.waitForTimeout(300);
  await page.click('.v1-flow-item[data-stage="2"]'); await page.waitForTimeout(1500);
  must(problems, delayed, '发送请求没有发出');
  await page.click('.wc-tab').catch(() => {}); await page.waitForTimeout(400);
  await page.fill('[data-wc-input]', 'Stage 2 的草稿'); await page.waitForTimeout(3600);
  const body = await text(page);
  must(problems, (await page.inputValue('[data-wc-input]')) === 'Stage 2 的草稿', '新阶段的草稿被清掉了');
  must(problems, /可以发送/.test(body) && !/本轮启动中|等待回复|来自 Stage 1/.test(body), '旧阶段的这一轮写到了新阶段上: ' + body.slice(0, 160));
  await page.close(); report('P2-3 a send in flight does not write to the next stage', problems);
 }
 {
  let answered = false, stopped = false, getDelay = 0;
  const {page} = await open(browser, 'double-click', 1, async (route, request) => {
   if (request.method() === 'GET') { if (getDelay) await new Promise(r => setTimeout(r, getDelay)); return json(route, answered ? STATES['asking'] : stopped ? STATES['sending'] : STATES['asking']).catch(() => {}); }
   const url = request.url().split('/').pop();
   if (url === 'answer') { answered = true; getDelay = 2500; return json(route, {saved:true, turn_id:'t2', request_id:'r1'}); }
   return json(route, turn('t2', 'stop-requested'));
  });
  const problems = [];
  await page.click('.wc-tab'); await page.waitForTimeout(600);
  await page.fill('[data-wc-ans="t2|a"]', '甲'); await page.fill('[data-wc-ans="t2|b"]', '乙');
  await Promise.all([page.click('[data-wc-answer]'), page.click('[data-wc-answer]', {timeout:600}).catch(() => {})]);
  await page.waitForTimeout(500);
  must(problems, posts.filter(p => p.url === 'answer').length === 1, '答复发了 ' + posts.filter(p => p.url === 'answer').length + ' 次');
  must(problems, (await page.locator('[data-wc-answer]').count()) === 0, '答复成功后提问卡还在');
  await page.close(); report('P2-4 answer cannot be submitted twice before the re-read', problems);
 }
 {
  let getDelay = 0;
  const {page} = await open(browser, 'stop-twice', 1, async (route, request) => {
   if (request.method() === 'GET') { if (getDelay) await new Promise(r => setTimeout(r, getDelay)); return json(route, STATES['sending']).catch(() => {}); }
   getDelay = 2500; return json(route, turn('t2', 'stop-requested'));
  });
  const problems = [];
  await page.click('.wc-tab'); await page.waitForTimeout(600);
  await page.click('[data-wc-stop]'); await page.waitForTimeout(300);
  must(problems, await page.locator('[data-wc-stop]').isDisabled(), '中断成功后按钮还能点');
  await page.locator('[data-wc-stop]').click({force:true, timeout:500}).catch(() => {}); await page.waitForTimeout(300);
  must(problems, posts.filter(p => p.url === 'stop').length === 1, '中断发了 ' + posts.filter(p => p.url === 'stop').length + ' 次');
  await page.close(); report('P2-4 stop cannot be sent twice before the re-read', problems);
 }
 {
  let phase = 'asking';
  const {page} = await open(browser, 'ask-poll', 1, (route, request) => request.method() === 'GET' ? json(route, phase === 'asking' ? STATES['asking'] : STATES['failed']) : json(route, {}, 500));
  const problems = [];
  await page.click('.wc-tab'); await page.waitForTimeout(800);
  must(problems, (await page.locator('[data-wc-answer]').count()) === 1, '没有提问卡');
  phase = 'failed'; await page.waitForTimeout(12000);
  must(problems, (await page.locator('[data-wc-answer]').count()) === 0 && /本轮失败/.test(await text(page)), '等回答期间后台超时，页面没有更新');
  await page.close(); report('P2-5 waiting for an answer still re-reads the turn', problems);
 }

 await browser.close();
 console.log(failed ? failed + ' scenario(s) failed' : 'all scenarios passed');
 process.exit(failed ? 1 : 0);
})().catch(error => { console.error(error); process.exit(2); });
