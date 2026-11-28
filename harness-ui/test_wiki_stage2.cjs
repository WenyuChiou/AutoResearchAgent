// Wiki V1 Stage 2: which state renders what, when buttons work, and that reading never writes.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
require('./v1_text_shim.cjs');
const test = require('node:test');

const source = fs.readFileSync(path.join(__dirname, 'wiki-stage2.js'), 'utf8');
const escape = value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');

function load(over = {}) {
  const writes = [], listeners = {}, store = new Map();
  const app = {page:'workspace', stage:2, lang:'zh', el:{querySelector:() => null}};
  const ctx = {
    rt:{ref:'project-a', overview:{project:{project_ref:'project-a', revision:3, brief:{original_description:'题目 <x>'}}}, list:[], loading:false},
    apps:[app], esc:escape, CSS:{escape:value => String(value)},
    canonicalReadonly:() => false, canonicalTop:() => '<top></top>', liveHeader:() => '<div class="hs-heading"><div><p class="hs-eyebrow">STAGE 02 / 06</p><h1>研究方向比较工作台</h1><p>原描述</p></div></div>',
    canonicalHeading:() => '<div class="hs-heading"><div><p class="hs-eyebrow">STAGE 02 / 06</p><h1>x</h1></div></div>',
    canonicalStage2Validate:() => ({ok:false, reason:'not-loaded'}),
    wikiHarnessRecord:() => '<div data-wiki-record>这一段还没有记录</div>',
    wikiStage2State:null, wikiStage2CurrentSelection:() => true, v93ChoiceIdentity:() => null,
    v9ConnectionModel:() => null, v9ConnectionConnected:() => false, v9LegacyConnection:() => false, v9AllowsCandidateRequest:() => true,
    stage2:app => 'earlier', v7AfterRender:() => {}, livePaint:() => {},
    // Any of these would be a write; the page must never reach them while rendering.
    liveRequest:(...args) => { writes.push(args); return Promise.reject(Error('no requests while rendering')); },
    fetch:(...args) => { writes.push(args); throw Error('no fetch'); },
    document:{addEventListener:(type, fn) => { (listeners[type] ||= []).push(fn); }},
    sessionStorage:{getItem:key => store.has(key) ? store.get(key) : null, setItem:(key, value) => store.set(key, String(value)), removeItem:key => store.delete(key)},
    p9:{shown:null}, n2:{}, m9:{busy:false}, ...over
  };
  vm.createContext(ctx);
  vm.runInContext(source, ctx);
  ctx.__app = app; ctx.__writes = writes; ctx.__listeners = listeners; ctx.__store = store;
  return ctx;
}
const click = (ctx, element) => { for (const fn of ctx.__listeners.click) fn({target:{closest:() => element}}); };
const control = (dataset, extra = {}) => ({dataset, disabled:false, closest:() => ({}), ...extra});

function archive(count = 4) {
  const dispositions = ['recommend', 'park', 'revise', undefined];
  const directions = Array.from({length:count}, (_, i) => ({candidate_id:String.fromCharCode(65 + i % 26) + '-route-' + i, version:1, question:'问题 ' + i + ' <b>',
    opportunity:'区别 ' + i, requirements:['工具 ' + i], limitations:['风险 ' + i], disposition:dispositions[i % 4], reason:'理由 ' + i, next_step:'下一步 ' + i,
    evidence_ids:i % 2 ? ['e1'] : ['e2'],
    checks:i === 0 ? {answerability:{status:'assessed', blocking:true, rationale:'r', next_check:'补查 <i>'}, execution:{status:'assessed', blocking:false}, materials:{status:'x'}} : undefined}));
  const literature = ['w1', 'w2', 'w3', 'w4'].map(id => ({work_id:id, version_id:'v1', title:'论文 ' + id, evidence_level:'full-text', cells:{method:{text:id === 'w4' ? '相同' : '方法 ' + id}, findings:{text:'发现'}, limitations:{text:'限制'}}}));
  const evidence = [{evidence_id:'e1', work_id:'w1', version_id:'v1'}, {evidence_id:'e2', work_id:'w2', version_id:'v1'}];
  const payload = {stage2:{evaluation:{}}, stage2_comparison:{directions, literature, evidence, comparison:'x\n## 建议指标\n- 指标甲：测准确率\n- 指标乙：测耗时\n## 其他\n'}};
  return {ok:true, payload:{...payload, stage2:{evaluation:{}}}, binding:{fixture:false}};
}
const asArchive = (ctx, validated) => { ctx.canonicalReadonly = () => true; ctx.rt.savedRun = {payload:validated.payload, binding:validated.binding, entry:{label:'归档标题'}}; ctx.canonicalStage2Validate = () => validated; };

test('four candidates side by side with the seven rows in the specified order and saved opinions', () => {
  const ctx = load(); asArchive(ctx, archive(4));
  const html = ctx.wikiS2Page(ctx.__app);
  assert.equal([...html.matchAll(/<th scope="col"[^>]*><b class="wiki-s2-letter">/g)].length, 4);
  const rows = [...html.matchAll(/<th scope="row">([^<]*)<\/th>/g)].map(match => match[1]);
  assert.deepEqual(rows, ['研究问题', '和最接近研究的区别', '数据能不能拿到', '工具和投入', '风险和退路', '卡住的条件', '依据的证据']);
  for (const label of ['系统建议', '系统暂缓', '系统建议先修订', '系统意见未提供']) assert.match(html, new RegExp(label));
  assert.doesNotMatch(html, /<input type="radio"[^>]*checked/, 'no direction is preselected');
  assert.match(html, /问题 0 &lt;b&gt;/, 'saved text is escaped');
  assert.match(html, /<b data-tone="block">卡住<\/b>/); assert.match(html, /<b data-tone="free">不卡<\/b>/); assert.match(html, /<b data-tone="unk">未提供<\/b>/);
  assert.match(html, /还没有<\/span><small>这份保存的结果里没有这条路线的五项检查/, 'a route without checks says why');
  assert.match(html, /系统建议 · 不是你的选择/);
  assert.equal(ctx.__writes.length, 0, 'rendering requests nothing');
});

test('archive and imported candidates cannot submit a formal selection and the button says why', () => {
  const ctx = load(); asArchive(ctx, archive(2));
  const html = ctx.wikiS2Page(ctx.__app);
  // DESIGN 8.0: archives show no write controls in the decision block, only the read-only sentence.
  assert.match(html, /data-s2-decide[^]*这是历史归档，不能在这里改/);
  assert.doesNotMatch(html, /data-s2-decide[^]*<input type="radio" name="wiki-s2-pick"/);
  assert.doesNotMatch(html, /data-v93-choice/);
  assert.match(html, /这份候选和某个课题的 Stage 1 文献包之间没有正式的绑定记录/);
  ctx.__app.wikiS2.pick = 'A-route-0@1';
  assert.doesNotMatch(ctx.wikiS2Page(ctx.__app), /确认选择方向 A…/, 'archives offer no confirm button even with a pick');
  const imported = load({p9:{shown:{}}, n2:{model:{routes:[{candidate:{candidate_id:'A', version:1, question:'q'}, assessment:{disposition:'recommend'}}], sources:[], packet:{evidence:[]}}}});
  const text = imported.wikiS2Page(imported.__app);
  assert.match(text, /没有这个课题的接通记录和 Stage 1 绑定，不能提交正式选择/);
  assert.match(text, /本页显示的是接入的候选包，不是本课题自己的 Stage 2/);
});

test('a live project with the selection component mounts it and offers no fake submit', () => {
  const view = {kind:'Stage2SelectionView', selection_status:'pending', eligible:[{candidate_id:'A', version:1}],
    cards:{cards:[{candidate_id:'A', candidate_version:1, candidate_question:'问 A', requirements:['工具'], limitations:['限'], next_checks:[{text:'查'}], alternatives:[]},
                  {candidate_id:'B', candidate_version:1, candidate_question:'问 B', requirements:[], limitations:[], closest_prior_work:{review:{summary:'区别 B'}}}]}};
  const ctx = load({wikiStage2State:{selection:view, basis:[]}, v93ChoiceIdentity:() => ({project_ref:'project-a'})});
  const html = ctx.wikiS2Page(ctx.__app);
  assert.match(html, /data-v93-choice/);
  assert.doesNotMatch(html, /请先选一个/);
  assert.match(html, /建议 方向 A（保存的结果只列出了建议的方向/);
  assert.match(html, /系统意见未提供/, 'a version the delivery does not recommend gets no invented park/revise label');
  assert.match(html, /区别 B/);
  assert.doesNotMatch(html, /这份候选和某个课题的 Stage 1 文献包之间没有正式的绑定记录/, 'native candidates carry their own binding');
  assert.match(html, /仅本机草稿，未提交 Harness/);
});

test('without a mounted component the live decision names the missing step', () => {
  const view = {selection_status:'pending', eligible:[], cards:[{candidate_id:'A', candidate_version:1, candidate_question:'q'}]};
  const ctx = load({wikiStage2State:{selection:view}});
  assert.match(ctx.wikiS2Page(ctx.__app), /现在还不能做这一步：Stage 2 还没有接通/);
  ctx.v9ConnectionConnected = () => true;
  assert.match(ctx.wikiS2Page(ctx.__app), /这次启动没有提供当前交付的正式选择入口/);
});

test('a recorded selection shows the receipt with only the facts the receipt holds', () => {
  const view = {selection_status:'recorded', selection_receipt:{key:'k'}, eligible:[], cards:[{candidate_id:'A', candidate_version:1, candidate_question:'q'}]};
  const ctx = load({wikiStage2State:{selection:view}});
  const html = ctx.wikiS2Page(ctx.__app);
  assert.match(html, /data-s2-receipt/);
  assert.equal([...html.matchAll(/<span class="wiki-s2-missing">还没有<\/span><small>选择回执里没有保存这一项/g)].length, 4);
  assert.doesNotMatch(html, /data-s2-decide/, 'the decision area is gone after a selection');
});

test('empty project: waiting for the literature package, or the saved input table when a package is readable', () => {
  const ctx = load();
  assert.match(ctx.wikiS2Page(ctx.__app), /Stage 2 在等这个课题的 Stage 1 文献包/);
  ctx.wikiS1Index = () => ({papers:[{work_id:'w', version_id:'v', title:'输入 <p>'}], claims:[{work_id:'w', version_id:'v'}], screening:[{work_id:'w', version_id:'v', status:'include', observed_at:'1'}]});
  const html = ctx.wikiS2Page(ctx.__app);
  assert.match(html, /这是交接过来的输入，Stage 2 的研究方向还没有生成/);
  assert.match(html, /输入 &lt;p&gt;<\/th><td>纳入<\/td><td>1 条保存的证据/);
});

test('a saved result that fails verification is not shown and nothing replaces it', () => {
  const ctx = load(); asArchive(ctx, {ok:false, reason:'canonical-stage2-evidence-binding-differs'});
  const html = ctx.wikiS2Page(ctx.__app);
  assert.match(html, /保存的结果没有通过核对，没有显示，也不会用示例内容补上/);
  assert.match(html, /data-wiki-stage2-action="read">重新读取/);
  assert.doesNotMatch(html, /data-s2-compare/);
});

test('connection and request lines use the specified wording and buttons', () => {
  const base = {phase:'ready', stage:'stage2-controller', basis:{}, view:{}, row:null, code:'', unknown:false, action:null, http:null, token:'t', reading:false, writing:false, canWrite:true, noLocks:false, connected:false, offerRef:null};
  const ctx = load();
  const line = over => ctx.wikiS2ConnectionLine({...base, ...over});
  assert.equal(line({action:'publish'}).tag, '等你 · 第 1 步');
  assert.equal(line({action:'publish'}).buttons[0].label, '生成本课题的启用提议');
  assert.equal(line({action:'activate'}).tag, '等你 · 第 2 步');
  assert.match(line({action:'activate'}).text, /同意后只登记启用，不会启动研究/);
  assert.equal(line({action:'connect'}).buttons[0].label, '接通本课题');
  assert.equal(line({connected:true}).tag, '已接通');
  assert.equal(line({code:'stage2-controller-current-input-required'}).buttons[0].label, '前往 Stage 1 查看交付');
  assert.equal(line({code:'stage2-controller-profile-unavailable'}).tag, '缺运行配置');
  assert.equal(line({http:404}).tag, '没带接通功能');
  assert.equal(line({code:'stage2-activation-record-unverified'}).tag, '启用记录缺回执');
  assert.equal(line({code:'project-lock-busy'}).tag, '暂时拿不到锁');
  assert.equal(line({http:403}).tag, '访问被拒');
  assert.equal(line({code:'connection-project-binding-mismatch'}).tag, '记录对不上');
  assert.equal(line({unknown:true}).buttons[0].label, '核对上次提交');
  assert.equal(line({noLocks:true, action:'connect'}).tag, '只能查看');
  assert.equal(line({phase:'waiting'}).tag, '正在核对');
  assert.equal(line({code:'something-else'}).tag, '核对不了');
  const request = status => { ctx.wikiStage2State = status; return ctx.wikiS2RequestLine(); };
  assert.equal(request({result:{status:'ready'}}).buttons[0].label, '请求生成候选');
  assert.equal(request({result:{status:'no-candidate'}}).text, '后台已经回执，候选交付还没有保存');
  assert.equal(request({result:{status:'blocked'}}).tag, '请求受阻');
  assert.equal(request({error:'stage2-continuation-original-admission-unavailable'}).buttons[0].label, '去连接与设置');
  assert.equal(request({error:'stage2-continuation-project-stale'}).tag, '版本不一致');
  assert.equal(request({error:'stage2-continuation-result-not-current'}).buttons.length, 0);
  assert.equal(request({error:'stage2-continuation-worker-busy'}).tag, '另一个请求在处理');
  assert.equal(request({error:'unknown-failure'}).tag, '读不到回执');
  assert.equal(request({busy:true}).tag, '正在读取');
});

test('connection block: gray buttons give a reason, connected and saved folds into a status tag', () => {
  const model = over => ({phase:'ready', stage:'stage2-controller', basis:{}, view:{}, row:null, code:'', unknown:false, action:'publish', token:'tok', reading:false, writing:false, canWrite:false, noLocks:false, connected:false, ...over});
  let current = model({});
  const ctx = load({v9ConnectionModel:() => current});
  assert.match(ctx.wikiS2ConnBlock(ctx.__app), /data-v9-connection="publish" data-connection-basis="tok" disabled>生成本课题的启用提议<\/button><small class="wiki-s2-reason">现在还不能做这一步/);
  ctx.rt.pending = {ref:'project-a'};
  assert.match(ctx.wikiS2ConnBlock(ctx.__app), /上次提交的结果还没确认，先核对/);
  ctx.rt.pending = null; ctx.rt.controlHeld = true;
  assert.match(ctx.wikiS2ConnBlock(ctx.__app), /有一条回执还没核对，先到操作历史里核对/);
  ctx.rt.controlHeld = false; current = model({canWrite:true});
  assert.doesNotMatch(ctx.wikiS2ConnBlock(ctx.__app), /disabled/);
  current = model({action:null, connected:true});
  ctx.wikiStage2State = {result:{status:'candidate-ready'}};
  assert.equal(ctx.wikiS2ConnBlock(ctx.__app), '', 'connected with saved candidates: no block');
  ctx.wikiStage2State = {result:{status:'ready'}};
  assert.match(ctx.wikiS2ConnBlock(ctx.__app), /data-s2-conn-row="request"[^]*请求生成候选/);
  assert.equal(ctx.__writes.length, 0);
});

test('pagination, pending-review flags and the local draft stay on this machine', () => {
  const ctx = load(); asArchive(ctx, archive(9));
  assert.match(ctx.wikiS2Page(ctx.__app), /第 1 页，共 2 页/);
  click(ctx, control({s2Page:'1'}));
  assert.equal(ctx.__app.wikiS2.page, 1);
  assert.equal([...ctx.wikiS2Page(ctx.__app).matchAll(/<b class="wiki-s2-letter">/g)].length, 1);
  click(ctx, control({s2Flag:'A-route-0@1'}));
  assert.deepEqual(JSON.parse(ctx.__store.get('wiki-s2-flags:project-a')), ['A-route-0@1']);
  ctx.__app.wikiS2.page = 0;
  assert.match(ctx.wikiS2Page(ctx.__app), /已标记待审/);
  ctx.__app.wikiS2.pick = 'B-route-1@1'; ctx.__app.wikiS2.note = '先看看';
  click(ctx, control({s2TentativeSave:''}));
  assert.equal(ctx.__app.wikiS2.tentative.letter, 'B');
  assert.match(ctx.wikiS2Page(ctx.__app), /<span class="wiki-s2-opinion" data-tone="draft">暂定<\/span>/);
  click(ctx, control({s2Save:''}));
  assert.equal(ctx.__app.wikiS2.draftStatus, 'saved');
  assert.equal(JSON.parse(ctx.__store.get('wiki-s2-draft:project-a')).note, '先看看');
  click(ctx, control({s2Clear:''}));
  assert.equal(ctx.__store.has('wiki-s2-draft:project-a'), false);
  assert.equal(ctx.__writes.length, 0, 'nothing was sent anywhere');
});

test('literature compare: three at most, hide identical rows, evidence matrix, metrics from the saved plan', () => {
  const ctx = load(); asArchive(ctx, archive(4));
  ctx.wikiS2Page(ctx.__app);
  ctx.__app.wikiS2.tab = 'literature';
  let html = ctx.wikiS2Page(ctx.__app);
  assert.match(html, /<th scope="col">论文 w1<\/th><th scope="col">论文 w2<\/th>/);
  click(ctx, control({s2Lit:'w3@v1'}));
  click(ctx, control({s2Lit:'w4@v1'}));
  assert.equal(ctx.__app.wikiS2.lit.length, 3);
  assert.equal(ctx.__app.wikiS2.litNote, '最多并排 3 个，请先取消一个');
  ctx.__app.wikiS2.lit = ['w4@v1']; ctx.__app.wikiS2.hideSame = true;
  html = ctx.wikiS2Page(ctx.__app);
  assert.match(html, /选 2–3 篇并排对照/);
  ctx.__app.wikiS2.lit = ['w1@v1', 'w4@v1'];
  html = ctx.wikiS2Page(ctx.__app);
  assert.doesNotMatch(html, /<th scope="row">阅读层级（原记录）<\/th>/, 'a row that is identical in both columns is hidden');
  assert.match(html, /<th scope="row">研究方法与样本<\/th>/);
  assert.match(html, /data-s2-card="w1@v1"/); assert.match(html, /data-s2-card="w2@v1"/);
  assert.match(html, /空格表示没有保存绑定，不等于不相关/);
  assert.match(html, /文献之间的关系：未提供/);
  assert.match(html, /不画效果排名/); assert.match(html, /指标甲：测准确率/); assert.match(html, /<td>未提供<\/td><td><span class="wiki-s2-opinion" data-tone="none">待验证/);
  // DESIGN 8.0: archives offer no save buttons at all.
  assert.doesNotMatch(html, /保存当前文献与路线比较/);
});

test('independent review fold: says so when the archive saved none', () => {
  const ctx = load(); asArchive(ctx, archive(2));
  assert.match(ctx.wikiS2Page(ctx.__app), /这份归档没有保存独立评估/);
  const reading = {source:{delivery_status:'draft-not-ready', packet_sha256:'p', delivery_manifest_sha256:'d', reviews_file_sha256:'r'},
    records:[{candidate_id:'A-route-0', candidate_version:1, role:'challenger', status:'complete', review:{assessment:{reason:'因 <e>', next_step:'下', checks:{value:{next_check:'补'}}}}}]};
  const imported = load({p9:{shown:{}}, n2:{reviewReading:reading, model:{routes:[{candidate:{candidate_id:'A-route-0', version:1, question:'q'}, assessment:{checks:{value:{status:'assessed', rationale:'好'}}}}], sources:[], packet:{evidence:[]}}}});
  const html = imported.wikiS2Page(imported.__app);
  assert.match(html, /1 个候选有可行性评估 · 复核意见 1 条/);
  assert.match(html, /挑战审查 · 评语已交付/); assert.match(html, /草稿 · 尚未选案/); assert.match(html, /这是报告质量评审，不是路线效果排名/);
  assert.match(html, /因 &lt;e&gt;/);
});

test('status bar text follows the page state and nothing is written when it is computed', () => {
  const ctx = load(); asArchive(ctx, archive(4));
  assert.match(ctx.wikiS2StatusText(ctx.__app).now, /4 个候选已保存（历史归档）/);
  const live = load({wikiStage2State:{selection:{selection_status:'pending', eligible:[], cards:[{candidate_id:'A', candidate_version:1, candidate_question:'q'}]}}});
  const status = live.wikiS2StatusText(live.__app);
  assert.equal(status.now, '1 个候选已比较好，等你选'); assert.equal(status.human, '等你 · 选一个方向');
  assert.equal(live.__writes.length, 0);
});

test('the Wiki page replaces the earlier Stage 2 in zh, en and tw; other stages are untouched', () => {
  const ctx = load();
  ctx.__app.lang = 'en';
  assert.match(ctx.stage2(ctx.__app), /Stage 2 · Choose direction/);
  assert.doesNotMatch(ctx.stage2(ctx.__app), /选方向/);
  ctx.__app.lang = 'tw';
  assert.match(ctx.stage2(ctx.__app), /Stage 2 · 選擇方向|Stage 2 · 選方向/);
  ctx.__app.lang = 'zh';
  assert.match(ctx.stage2(ctx.__app), /Stage 2 · 选方向/);
  assert.match(ctx.stage2(ctx.__app), /<h1>题目 &lt;x&gt;<\/h1>/);
  assert.doesNotMatch(ctx.stage2(ctx.__app), /<p>原描述<\/p>/);
  ctx.__app.stage = 1; assert.equal(ctx.stage2(ctx.__app), 'earlier');
});
