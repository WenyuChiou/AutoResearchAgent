const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const esc = value => String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
const sha = char => char.repeat(64);
function makeProject(scoped) {
 return {project_ref:'project-a', input_version:1, revision:2, brief_sha256:sha('b'),
  brief:{original_description:'<Heat> & health'},
  intake_report:{necessary_clarification_complete:scoped,
   scope:{geography:{status:scoped?'specified':'pending', value:scoped?'美国':null}, priority_reading_target:{status:'x', value:scoped?10:null}},
   formal_final_count:{target:scoped?30:null}},
  settings:null};
}
function makeRt(scoped, extra={}) {
 const project = makeProject(scoped);
 return {ref:'project-a', overview:{project, models:{calls_reserved:0, jobs:[]}, stage1:{
  progress:{phases:[['scope', scoped?'recorded':'required','scope-required'],['planning','required','plan-required'],
   ['query','unconnected','query-permission-required'],['screening','unconnected','screening-required'],
   ['reading','unconnected','reading-registration-required'],['coverage','unconnected','coverage-required'],
   ['delivery','required','delivery-required']].map(([phase_id,status,reason]) => ({phase_id,status,reason}))},
  queries:[], delivery:{offers:[], canonical_package:null}, reading_registration:{status:'unconnected', missing_works:[]}}},
  loading:false, busy:false, pending:null, controlHeld:false, error:'', scopeDraft:null, ...extra};
}
function load(rt, extra={}) {
 const ctx = vm.createContext({rt, esc, apps:[{wikiS1:{}}], TextEncoder, JSON, Set, Math,
  canonicalReadonly:()=>false, wikiHomeArchiveBound:()=>false, projectPath:(ref,tail)=>`/api/projects/${ref}/${tail}`,
  liveScopeValues:() => rt.scopeDraft?.values || {geography:'', geographyValue:'', target:'30', priority:'20', note:''},
  realModelOffers:()=>[], realPlanningState:()=>({allowed:true, current:true, blocking:0}), realPlanningFailure:()=>'',
  realPlanImportReady:()=>false, realPlanDraftCurrent:()=>false, realQueryOwnerOffer:()=>null, realCurrent:()=>true,
  realCoverage:()=>'', wikiS1Active:()=>true, wikiS1Tabs:{}, wikiS1Results:()=>'', wikiS1State:()=>({}), wikiS1Index:()=>null,
  ...extra});
 const source = fs.readFileSync(path.join(__dirname,'wiki-stage1-ops.js'),'utf8');
 vm.runInContext(source.slice(0,source.indexOf('// ---------- hooks into')),ctx);
 return ctx;
}
const filled = {geography:'specified', geographyValue:'美国', target:'30', priority:'10', note:'只看美国'};
const buttonOf = (html, marker) => {
 const at = html.indexOf(marker), start = html.lastIndexOf('<span class="ws-btn">', at), end = html.indexOf('</span>', html.indexOf('</button>', at));
 return html.slice(start, end + 7);
};

// Fixed reasons from DESIGN 8.0, in the listed order.
let rt = makeRt(false), ctx = load(rt);
assert.equal(ctx.wsLock(), '');
rt.controlHeld = true; assert.equal(ctx.wsLock(), '有一条回执还没核对，先到操作历史里核对');
rt.pending = {}; assert.equal(ctx.wsLock(), '上次提交的结果还没确认，先核对');
rt.busy = true; assert.equal(ctx.wsLock(), '正在保存，请稍等');
rt.loading = true; assert.equal(ctx.wsLock(), '正在读取保存记录');

// Scope page, no consent route: the "没带" card with three-step preview and a gray, explained button.
rt = makeRt(false, {wsProg:{key:null, state:'absent'}});
ctx = load(rt); rt.wsProg.key = ctx.wsProgKey();
let page = ctx.wsScopePage({wikiS1:{}});
assert.match(page, /data-ws-consent="absent"/);
assert.match(page, /保存并确认范围/);
assert.match(page, /现在：<\/b>只保存范围，不检索、不调用模型/);
assert.match(page, /&lt;Heat&gt; &amp; health/, 'topic is escaped and read only');
assert.match(buttonOf(page, 'data-ws-confirm="save"'), /disabled/);
assert.match(buttonOf(page, 'data-ws-confirm="save"'), /还缺：地域范围、范围说明/);
assert.match(buttonOf(page, 'data-ws-draft'), /disabled/, 'no draft store exists, so the draft button stays gray with a reason');
assert.doesNotMatch(page, /data-ws-consent="provided"/);
assert.doesNotMatch(page, /<option value="specified" selected/);
assert.doesNotMatch(page, /data-live-geography-value/, 'region field only appears for specified geography');
rt.scopeDraft = {values:filled};
rt.scopeDraft.basis = undefined;
page = ctx.wsScopePage({wikiS1:{}});
assert.doesNotMatch(buttonOf(page, 'data-ws-confirm="save"'), /disabled/);
assert.match(page, /data-live-geography-value/);
rt.scopeDraft = {values:{...filled, target:'0', note:'x'.repeat(4097)}};
page = ctx.wsScopePage({wikiS1:{}});
assert.match(page, /请填 1 以上的整数/);
assert.match(page, /超过 4096 字节/);
assert.match(buttonOf(page, 'data-ws-confirm="save"'), /还缺：正式文献目标、范围说明（超过 4096 字节）/);
rt.scopeDraft = {values:filled};
rt.busy = true;
assert.match(buttonOf(ctx.wsScopePage({wikiS1:{}}), 'data-ws-confirm="save"'), /正在保存，请稍等/);
rt.busy = false; rt.error = 'boom <x>';
assert.match(ctx.wsScopePage({wikiS1:{}}), /没有保存：boom &lt;x&gt;，表单内容保留/);

// Consent present: 4a card; the missing read-only consent endpoint is stated, not invented.
rt = makeRt(false, {wsProg:{state:'read', value:{status:'not-started'}}});
ctx = load(rt); rt.wsProg.key = ctx.wsProgKey(); rt.scopeDraft = {values:filled};
page = ctx.wsScopePage({wikiS1:{}});
assert.match(page, /data-ws-consent="provided"/);
assert.match(page, /后台没有给出同意书内容的只读接口/);
assert.match(page, /到那一段时要你单独接通/);
assert.match(buttonOf(page, 'data-ws-confirm="advance"'), /请先勾选确认/);
assert.match(buttonOf(page, 'data-ws-confirm="advance"'), /disabled/);
page = ctx.wsScopePage({wikiS1:{wsConsentOk:true}});
assert.doesNotMatch(buttonOf(page, 'data-ws-confirm="advance"'), /disabled/);
assert.match(page, /我确认上面的范围，并同意按这份同意书自动推进 Stage 1。选方向和对评审的决定仍然由我本人做/);

// Six unusable-consent reasons use the fixed sentences and fall back to the stepwise card.
for (const [code, label, text] of [
 ['stage-progression-consent-digest-differs','核对不上','同意书的内容和启动时登记的不一致，没有使用'],
 ['stage-progression-consent-invalid','无效','同意书的格式不对，或没有写明已确认，没有使用'],
 ['stage-progression-consent-binding-differs','不是这个课题或这个版本','同意书对应的是另一个课题，或这个课题的旧版本'],
 ['stage-progression-consent-expired','已过期','同意书已过期，不会自动续期'],
 ['stage-progression-consent-stage-not-covered','没覆盖这一段','同意书没有覆盖这一段'],
 ['stage-progression-consent-required','没带','这次启动没有带同意书。每一步要你单独授权']]) {
 rt = makeRt(true, {wsProg:{state:'error', code}});
 ctx = load(rt); rt.wsProg.key = ctx.wsProgKey();
 const auto = ctx.wsAuto();
 assert.equal(auto.kind, 'block'); assert.equal(auto.label, label); assert.equal(auto.text, text);
 assert.match(ctx.wsAutoRow(), new RegExp(label));
}
rt = makeRt(true, {wsProg:{state:'error', code:'stage-progression-budget-unavailable'}});
ctx = load(rt); rt.wsProg.key = ctx.wsProgKey();
assert.equal(ctx.wsAuto().label, '缺运行许可');
assert.match(ctx.wsAutoRow(), /去连接与设置/);

// Seven auto-advance states (only when a consent route exists; absent route shows no row).
const autoCase = (scoped, prog) => {
 const r = makeRt(scoped, {wsProg:{state:'read', value:prog}}), c = load(r); r.wsProg.key = c.wsProgKey();
 return {auto:c.wsAuto(), row:c.wsAutoRow()};
};
assert.equal(autoCase(false, {status:'waiting-for-project-scope'}).auto.label, '等你确认范围');
assert.equal(autoCase(true, {status:'waiting-for-predecessor'}).auto.label, '等上一段');
assert.equal(autoCase(true, {status:'not-started'}).auto.label, '还没开始');
assert.match(autoCase(true, {status:'not-started'}).row, /data-ws-advance/);
assert.equal(autoCase(true, {status:'waiting-for-spending-grant'}).auto.label, '缺运行许可');
assert.equal(autoCase(true, {status:'in-progress'}).auto.label, '进行中');
assert.match(autoCase(true, {status:'in-progress'}).row, /不需要你操作/);
assert.equal(autoCase(true, {status:'execution-unknown'}).auto.label, '结果未确认');
assert.match(autoCase(true, {status:'execution-unknown'}).row, /核对上次提交/);
assert.equal(autoCase(true, {status:'saved'}).auto.label, '已保存');
assert.match(autoCase(true, {status:'saved'}).row, /Stage 2 现在还不能自动推进/);
rt = makeRt(true, {wsProg:{state:'absent'}}); ctx = load(rt); rt.wsProg.key = ctx.wsProgKey();
assert.equal(ctx.wsAutoRow(), '', 'no consent route: no auto-advance row');
rt.busy = true;
assert.match(autoCase(true, {status:'not-started'}).row, /not-started|还没开始/);

// Run tab: seven fixed rows in the designed order, with their states.
rt = makeRt(true, {wsProg:{state:'absent'}}); ctx = load(rt); rt.wsProg.key = ctx.wsProgKey();
const app = {wikiS1:{}};
let tab = ctx.wsRunTab(app);
const names = [...tab.matchAll(/class="ws-dot">\d<\/span><b>([^<]+)<\/b>/g)].map(match => match[1]);
assert.deepEqual(names, ['确认范围','检索规划','查询与来源','文献筛选','阅读与证据','覆盖检查','保存交付']);
assert.match(tab, /范围 v1 · 指定地区：美国 · 文献目标 30 · 优先阅读 10/);
assert.match(tab, /每一步的上限写在那一步的授权卡里/);
assert.match(tab, /data-ws-grant="plan"/, 'no consent: stepwise authorization card');
assert.match(buttonOf(tab, 'data-real-action="authorize-plan"'), /没有可用的额度/);
assert.match(buttonOf(tab, 'data-real-action="plan"'), /没有本课题的运行许可，见连接与设置/);
assert.match(tab, /请先勾选确认|我确认只授权这一次、这一件事/);
assert.equal(ctx.wsPhaseRows()[1].kind, 'wait');
assert.equal(ctx.wsPhaseRows()[2].kind, 'idle', 'unconnected row is not started');
// Scope not confirmed: the plan row is not asking for you yet.
rt = makeRt(false, {wsProg:{state:'absent'}}); ctx = load(rt);
assert.equal(ctx.wsPhaseRows()[0].label, '等你');
assert.equal(ctx.wsPhaseRows()[1].label, '未开始');

// Consent present: no authorization cards, only view/refresh buttons.
rt = makeRt(true, {wsProg:{state:'read', value:{status:'not-started'}}}); ctx = load(rt); rt.wsProg.key = ctx.wsProgKey();
tab = ctx.wsRunTab({wikiS1:{}});
assert.doesNotMatch(tab, /data-ws-grant=/);
assert.doesNotMatch(tab, /data-real-action="query-authorize"/);
assert.match(tab, /这一轮由同意书自动往下走/);
assert.match(tab, /data-live-action="refresh"/);

// Query table never invents numbers.
rt = makeRt(true, {wsProg:{state:'absent'}});
rt.overview.stage1.queries = [{query:'heat <mortality>', purpose:'main', status:'intent-recorded-not-executed'}];
ctx = load(rt);
const table = ctx.wsQueryTable();
assert.match(table, /heat &lt;mortality&gt;/);
assert.match(table, /已记录，还没执行/);
assert.match(table, /<td>未提供<\/td>/);

// Delivery and decision (8.11): no preselected choice, request-stage2 gated by eligibility.
rt = makeRt(true, {wsProg:{state:'absent'}, atlas:{stage2_input:{eligible_for_stage2:false}}, draft:''});
ctx = load(rt);
let delivery = ctx.wsDeliveryDetail({wikiS1:{}});
assert.match(delivery, /还没有生成交付/);
assert.match(buttonOf(delivery, 'data-live-action="deliver"'), /还没有可交付的已保存证据/);
assert.doesNotMatch(delivery, /type="radio"[^>]*checked/);
assert.match(delivery, /value="request-stage2" data-ws-decision-radio\s+disabled/);
assert.match(delivery, /未满足；申请不会改变这个状态/);
assert.match(delivery, /申请只保存你的审阅意见，不会自动放行，也不会运行下一段/);
assert.match(buttonOf(delivery, 'data-live-action="review"'), /请先选一个/);
assert.match(delivery, /还没有审阅记录/);
rt.atlas.stage2_input.eligible_for_stage2 = true;
delivery = ctx.wsDeliveryDetail({wikiS1:{wsDecision:'request-stage2'}});
assert.doesNotMatch(delivery, /value="request-stage2" data-ws-decision-radio checked\s+disabled/);
assert.match(delivery, /已满足记录的条件/);
rt.draft = 'ok';
assert.doesNotMatch(buttonOf(delivery = ctx.wsDeliveryDetail({wikiS1:{wsDecision:'hold'}}), 'data-live-action="review"'), /disabled/);

// Archive projects are read only.
ctx = load(makeRt(true, {wsProg:{state:'absent'}}), {wikiHomeArchiveBound:()=>true});
assert.match(ctx.wsScopePage({wikiS1:{}}), /这是历史归档，不能在这里改/);
tab = ctx.wsRunTab({wikiS1:{}});
assert.match(buttonOf(tab, 'data-real-action="authorize-plan"') || '', /这是历史归档，不能在这里改|^$/);
console.log('PASS Stage 1 ops: scope page, auto-advance states, run table, delivery decision.');
