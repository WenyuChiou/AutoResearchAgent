const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
require('./v1_text_shim.cjs');

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
// Query row on a launch without a query service: the row and the three query buttons give one reason (acceptance S-3).
assert.equal(ctx.wsPhaseRows()[2].reason, '查询执行还没接通');
assert.doesNotMatch(ctx.wsPhaseRows()[2].reason, /运行许可/);
rt.overview.stage1.progress.phases[2] = {phase_id:'query', status:'required', reason:'query-permission-required'};
assert.equal(ctx.wsPhaseRows()[2].reason, '没有这一段的运行许可', 'with a query service, the permission reason still applies');
// Follow-up 3 / 2: ledger present, no query count, no query service: the host says 「unknown」, the buttons say 「还没接通」.
rt.overview.stage1.progress.phases[2] = {phase_id:'query', status:'unknown', reason:'query-permission-required'};
assert.equal(rt.overview.stage1.query_execution, undefined);
{
 const row = ctx.wsPhaseRows()[2];
 assert.equal(row.reason, '查询执行还没接通');
 assert.equal(row.kind, 'idle', 'not connected is not 被拦下');
 assert.equal(row.label, '还没接通');
 assert.equal(row.raw.status, 'unknown', 'the host own word stays in the raw record');
}
rt.overview.stage1.query_execution = {authorization_offer:null};
assert.equal(ctx.wsPhaseRows()[2].kind, 'block', 'with a query service an unknown count is still unknown');
assert.equal(ctx.wsPhaseRows()[2].reason, '没有这一段的运行许可');
delete rt.overview.stage1.query_execution;
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

// ---- Paper card, candidate list, evidence review, materials (8.8, 8.9, 8.12) ----
function loadPaper(rt, extra={}) {
 const base = {wikiS1Relations:{supports:'支持', contradicts:'不支持'}, wikiS1Checks:{all:'全部', contradicts:'✕ 不支持'},
  wikiS1Check:claim => claim.verified ? claim.relation : 'unchecked', wikiS1VisibleSources:()=>[], wikiS1Evidence:()=>'', wikiS1Selected:()=>'',
  realActionEnvelope:()=>true, realReadingExecutable:()=>false, realReadingOffer:value => value.reading_offer?.available,
  wsOpsActive:()=>true, wikiS1Tabs:{}, wikiS1Results:()=>'', v7AfterRender:()=>{}, ...extra};
 const c = load(rt, base);
 const source = fs.readFileSync(path.join(__dirname,'wiki-stage1-ops.js'),'utf8');
 const from = source.indexOf('// ---------- 8.8 / 8.9'), to = source.indexOf("// Loading a paper's record");
 vm.runInContext(source.slice(from, to), c);
 const materials = fs.readFileSync(path.join(__dirname,'wiki-stage1-materials.js'),'utf8');
 vm.runInContext(materials.slice(0, materials.indexOf('const wsMaterialsPrevResults')), c);
 return c;
}
rt = makeRt(true, {wsProg:{state:'absent'}});
ctx = loadPaper(rt);
assert.equal(ctx.wikiS1Relations.contradicts, '相互矛盾');
assert.equal(ctx.wikiS1Relations.unverifiable, '无法核实');
assert.equal(ctx.wikiS1Checks.context, '· 只是背景');
assert.equal(ctx.wikiS1Check({verified:true, relation:'supports', locator:'x'}), 'supports');
const humanClaim = relation => ({relation, locator:'x', core_event:{payload:{verifier:{actor_type:'human'}}}});
assert.equal(ctx.wikiS1Check(humanClaim('unclear')), 'unclear');
assert.equal(ctx.wikiS1Check({...humanClaim('unclear'), core_event:{payload:{verifier:{actor_type:'agent'}}}}), 'unchecked', 'agent record is not a human check');
assert.equal(ctx.wikiS1Check({...humanClaim('unclear'), locator:null}), 'unchecked');

// Candidate list: design sentence, no invented rows, load-more only when the service offers a next page.
assert.match(ctx.wsCandidatePanel(), /这里还没有检索候选/);
rt.library = {total:2, next_offset:20, rows:[{index:0, work_id:'w1', title:'A <b>', year:2020, source_status:'not-acquired', screening_status:'include'},
 {index:1, work_id:'w2', title:'B', year:null, source_status:'pending', screening_status:'not-screened'}]};
let list = ctx.wsCandidatePanel();
assert.match(list, /这是当前查询的输出，还不是正式交付。来源、阅读和纳入决定要分别审阅。/);
assert.match(list, /A &lt;b&gt;/);
assert.match(list, /<td>未提供<\/td>/);
assert.match(list, /读取更多候选/);
assert.match(list, /data-real-paper="1"/);
rt.library.next_offset = null;
assert.doesNotMatch(ctx.wsCandidatePanel(), /读取更多候选/);

// Paper card: not loaded yet -> one button whose reason is explicit.
let card = ctx.wsPaperProcess('w3');
assert.match(buttonOf(card, 'data-ws-load-paper'), /这篇还没有出现在已保存的检索候选里/);
card = ctx.wsPaperProcess('w1');
assert.doesNotMatch(buttonOf(card, 'data-ws-load-paper'), /disabled/);
// Loaded detail.
rt.paperDetail = {project_ref:'project-a', binding:{ledger_state_sha256:'L'}, row:{work_id:'w1', screening_status:'pending', source_status:'not-acquired', metadata:{title:'A'}}, reading_offer:{available:false, blocked_reason:'no-source'}};
rt.overview.stage1.ledger = {state_sha256:'L'};
rt.overview.stage1.source_execution = null;
card = ctx.wsPaperProcess('w1');
assert.match(card, /筛选决定 <span class="ws-tag ws-idle">现在：待定/);
assert.doesNotMatch(card, /type="radio"[^>]*checked/);
assert.match(buttonOf(card, 'data-v7-workflow="screen"'), /请先选一个/);
assert.match(card, /筛选决定只更新这一篇；来源获取和阅读要单独做/);
assert.match(buttonOf(card, 'data-v7-workflow="source-preview"'), /来源获取现在不可用/);
assert.match(card, /<b>不会改 Harness 的阅读提示词<\/b>/);
assert.match(buttonOf(card, 'data-v7-workflow="reading-authorize"'), /阅读还没有可用的来源或额度/);
// Backend codes are not body text (DESIGN 2.6); the raw value stays in technical details.
assert.match(card, /阅读条件：服务给了原因代码/);
assert.match(card, /<summary>原值<\/summary><code>no-source<\/code>/, 'the raw value sits next to the plain sentence');
assert.doesNotMatch(card, /阅读条件：no-source/);
assert.match(card, /data-ws-expansion-slot/);
assert.match(card, /未获取/);
// Already readable: no authorization step for the source.
rt.paperDetail.reading_offer = {available:true};
card = ctx.wsPaperProcess('w1');
assert.match(card, /已有可读来源/);
assert.doesNotMatch(card, /data-v7-workflow="source-authorize"/);
assert.doesNotMatch(buttonOf(card, 'data-v7-workflow="reading-authorize"'), /disabled/);
// Locked while a write is pending.
rt.busy = true;
assert.match(buttonOf(ctx.wsPaperProcess('w1'), 'data-v7-workflow="screen"'), /正在保存，请稍等/);
rt.busy = false;
// A record for another paper is never shown for this one.
rt.paperDetail.row.work_id = 'other';
assert.match(ctx.wsPaperProcess('w1'), /读取这篇的处理/);
rt.paperDetail.row.work_id = 'w1';
// Reading notes: three groups, saved text stays, reason before the confirm box is ticked.
rt.readingView = {project_ref:'project-a', source_mode:'saved-source-review', classification:{topic_cluster:'T <x>'}, findings:{question:'Q'}, sources:[], claims:[], reading_review_offer:{offer_ref:'o'}, offers:[]};
card = ctx.wsPaperProcess('w1');
for (const group of ['分类', '内容', '和本课题的关系']) assert.match(card, new RegExp('<h5>' + group + '</h5>'));
assert.match(card, /data-v7-note="classification\.topic_cluster" placeholder="未提供">T &lt;x&gt;/);
// Missing fields stay empty with a placeholder, so saving never writes the words 「未提供」 as a note (review P2-2).
assert.match(card, /data-v7-note="findings\.limitations" placeholder="未提供"><\/textarea>/);
assert.match(card, /class="ws-notes" data-v7-reading-review/, 'old reading-save handler finds the new form');
assert.match(buttonOf(card, 'reading-save'), /请先勾选「我已审阅这些注释」/);
assert.match(card, /保存不代表 Stage 1 完成/);
rt.readingView.reading_review_offer = null;
assert.match(buttonOf(ctx.wsPaperProcess('w1'), 'reading-save'), /data-ws-blocked/);
// Archive projects cannot write.
const archive = loadPaper(makeRt(true), {wikiHomeArchiveBound:()=>true});
assert.match(archive.wsPaperProcess('w1'), /这是历史归档，不能在这里改/);
assert.doesNotMatch(archive.wsPaperProcess('w1'), /data-v7-workflow/);

// Evidence review fold.
const claim = {quote:'q1', source_id:'s1', text:'T', evidence_level:'full-text'};
rt.readingView = null;
let fold = ctx.wsEvidenceReview(claim, 'w1');
assert.match(fold, /依据全文/);
assert.match(fold, /这条证据现在没有可保存的审阅入口/);
assert.doesNotMatch(fold, /data-v7-workflow="claim-save"/, 'no review input exists, so no fake save button');
assert.doesNotMatch(ctx.wsEvidenceReview({...claim, evidence_level:undefined}, 'w1'), /依据摘要|依据全文/, 'unmarked scope shows no tag');
rt.readingView = {project_ref:'project-a', offers:[{quote:'other', evidence_index:0}, {quote:'q1', source_id:'s1', evidence_index:1}]};
fold = ctx.wsEvidenceReview(claim, 'w1');
assert.match(fold, /data-v7-claim-relation="1"/);
assert.match(fold, /data-v7-index="1"/);
for (const name of ['未核对（还没判断）','支持','部分支持','相互矛盾','不清楚','无法核实','只是背景']) assert.ok(fold.includes('>' + name + '</option>'), name);
assert.match(buttonOf(fold, 'claim-save'), /请先选关系/);
assert.match(fold, /我已审阅这条证据/);

// Materials tab: designed strip and the slot for the materials panel; the package files list (8.12 文献包里的文件)
// names files as the project files page does and sends downloads there (checked download, 8.1). No invented files.
rt.atlas = null;
let materials = ctx.wsMaterialsTab({});
assert.doesNotMatch(materials, /ws-strip/, 'the 加入文件 card carries this sentence; no second copy above it');
assert.match(materials, /data-ws-materials-slot/);
assert.match(ctx.wsMaterialsDownloads(), /文献包还没有生成，这里还没有可下载的文件/);
rt.atlas = {files:[{path:'references.bib', sha256:'a'.repeat(64)}, {path:'wiki/' + 'b'.repeat(64) + '.md', sha256:'c'.repeat(64)}]};
const downloads = ctx.wsMaterialsDownloads();
assert.match(downloads, /参考文献 BibTeX/);
assert.match(downloads, /逐篇笔记 1/);
assert.doesNotMatch(downloads, /bbbbbbbb/, 'no stored path in the text');
assert.match(downloads, /data-page="files">去项目文件下载/);
assert.match(archive.wsMaterialsTab({}), /这是历史归档，不能在这里改/);
// Review P2-3: the saved-materials header only says "saved with original bytes" when there is something saved.
{
 const block = fs.readFileSync(path.join(__dirname,'wiki-stage1-materials.js'),'utf8');
 const v1 = block.slice(block.indexOf('// ---------- Wiki V1 materials panel'));
 const app = {lang:'zh', page:'workspace', stage:1};
 const mc = vm.createContext({esc:v => String(v), apps:[app], v1On:() => true, m9Panel:() => 'old', n9Message:v => v || '', document:{addEventListener:() => {}},
  wsTag:(k, l) => `<tag>${l}</tag>`, wsBtn:(l, a, r) => `<button ${a}>${l}</button>${r || ''}`, wsMaterialsDownloads:() => '',
  m9:{catalog:{materials:[], operations:[], drafts:[]}, busy:false, error:'', status:'', target:{}, notes:{}, sourcePath:'', importPath:'', packetHash:''},
  m9Current:() => mc.m9.catalog?.materials || [], m9Draft:() => null});
 vm.runInContext(v1, mc);
 assert.match(mc.m9Panel(app), /还没有登记材料。/);
 assert.match(mc.m9Panel(app), /不会自动标记为已读、已纳入或已批准/);
 assert.doesNotMatch(mc.m9Panel(app), /已按原始字节保存/);
 mc.m9.catalog.materials.push({id:'file-1', kind:'manual-file', status:'registered', name:'a.pdf', stage:1, bytes:2048, registered_at:'2026-11-27T08:00:00Z'});
 assert.match(mc.m9Panel(app), /1 份。文件已按原始字节保存，没有启动研究。/);
 assert.match(mc.m9Panel(app), /data-n9-file="file-1"/);
 // Review P2-b: while the list is being read, or when the read failed, the header does not say "none yet".
 const saved = mc.m9.catalog;
 mc.m9.catalog = null;
 assert.doesNotMatch(mc.m9Panel(app), /还没有登记材料/);
 assert.match(mc.m9Panel(app), /正在读取保存记录/);
 mc.m9.error = 'HTTP 503';
 assert.doesNotMatch(mc.m9Panel(app), /还没有登记材料/);
 assert.match(mc.m9Panel(app), /这次没有读到已保存的材料/);
 mc.m9.catalog = saved; mc.m9.error = '';
}
// Acceptance M-7: no sentence is built from an empty value.
{
 const rt2 = makeRt(false), c2 = load(rt2);
 rt2.overview.stage1.coverage_actions = {blockers:[], offers:[]};
 const text = c2.wsCoverageDetail();
 assert.doesNotMatch(text, /第 未提供 轮|未提供/);
 assert.match(text, /还没有读到当前是第几轮/);
 rt2.overview.stage1.coverage_actions = {blockers:[], offers:[{document:{round_number:3}}]};
 assert.match(c2.wsCoverageDetail(), /目前第 3 轮/);
}
// Acceptance S-4: 「核验并登记候选包」 is grey, with a reason, wherever registering cannot work.
{
 const block = fs.readFileSync(path.join(__dirname,'wiki-stage1-materials.js'),'utf8');
 const v1 = block.slice(block.indexOf('// ---------- Wiki V1 materials panel'));
 const app = {lang:'zh', page:'workspace', stage:2};
 const state = {archive:false, canonical:false, origin:'', code:'', fields:['a', 'b', 'c']};
 const listeners = [], patched = [];
 const wrap = {set outerHTML(html) { patched.push(html); }};
 app.el = {querySelector:selector => selector === '[data-n9-action="import"]' ? {closest:() => wrap} : null};
 const mc = vm.createContext({esc:v => String(v), apps:[app], v1On:() => true, m9Panel:() => 'old', n9Message:v => v || '', rt:{ref:'project-a', list:[{project_ref:'project-a'}]}, wikiHomeRow:() => ({origin:state.origin || 'local'}), document:{addEventListener:(type, fn) => { if (type === 'input') listeners.push(fn); }},
  wsTag:(k, l) => `<tag>${l}</tag>`, wsBtn:(l, a, r) => `<span class="b"><button ${a} ${r ? 'disabled' : ''}>${l}</button>${r ? '<small>' + r + '</small>' : ''}</span>`, wsMaterialsDownloads:() => '',
  wikiHomeArchiveBound:() => state.archive, canonicalReadonly:() => state.canonical,
  v9ConnectionModel:() => ({phase:'ready', code:state.code}),
  m9:{catalog:{materials:[], operations:[], drafts:[]}, busy:false, error:'', status:'', target:{}, notes:{}, sourcePath:'a', importPath:'b', packetHash:'c'},
  m9Current:() => [], m9Draft:() => null});
 vm.runInContext(v1, mc);
 const button = () => { const html = mc.m9Panel(app), at = html.indexOf('data-n9-action="import"'); return html.slice(html.lastIndexOf('<span class="b">', at), html.indexOf('</span>', at) + 7); };
 assert.doesNotMatch(button(), /disabled/, 'a configured, writable project with the three fields filled can register');
 state.archive = true; assert.match(button(), /disabled.*历史归档，不能在这里改/s); state.archive = false;
 // Follow-up 3 / 1: a saved sample is archive-bound too, but is worded as a sample.
 state.archive = true; state.origin = 'synthetic'; assert.match(button(), /disabled.*这是保存的样例，不能在这里改/s); assert.doesNotMatch(button(), /历史归档/); state.archive = false; state.origin = '';
 state.canonical = true; assert.match(button(), /disabled.*保存的样例，不能在这里改/s); state.canonical = false;
 state.code = 'stage2-controller-profile-unavailable'; assert.match(button(), /disabled.*没有提供 Stage 2 的运行配置/s); state.code = '';
 mc.m9.sourcePath = ''; assert.match(button(), /disabled.*请先填好上面的三项/s);
 // P1: the three fields start empty and are filled by typing. Drive the real input listener (not the state): the button is
 // re-judged on each input, only the button is replaced, and nothing repaints the page.
 mc.m9.sourcePath = ''; mc.m9.importPath = ''; mc.m9.packetHash = '';
 const type = (field, value) => { const target = {dataset:{n9Field:field}, value, matches:selector => selector === '[data-n9-field]'}; for (const fn of listeners) fn({target}); return patched[patched.length - 1]; };
 assert.equal(listeners.length, 1);
 assert.match(type('sourcePath', 'D:/pkg'), /disabled.*请先填好上面的三项/s, 'one of three filled: still grey, with the reason');
 assert.match(type('importPath', 'D:/pkg/packet.json'), /disabled.*请先填好上面的三项/s);
 assert.doesNotMatch(type('packetHash', 'a'.repeat(64)), /disabled/, 'all three filled: the button becomes usable');
 assert.equal(mc.m9.packetHash, 'a'.repeat(64), 'the typed value is stored');
 assert.match(type('packetHash', '  '), /disabled.*请先填好上面的三项/s, 'clearing a field greys it again');
 type('packetHash', 'b'.repeat(64));
 state.archive = true; assert.match(type('packetHash', 'b'.repeat(64)), /disabled.*历史归档/s, 'an archive stays grey whatever is typed'); state.archive = false;
 state.code = 'stage2-controller-profile-unavailable'; assert.match(type('packetHash', 'b'.repeat(64)), /disabled.*运行配置/s, 'a launch without configuration stays grey'); state.code = '';
}
console.log('PASS Stage 1 ops: scope page, auto-advance states, run table, delivery decision, paper card, evidence review, materials.');
