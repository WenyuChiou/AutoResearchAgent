/* Wiki V1 Stage 3 page tests. Synthetic plans only; no server, model or write path. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');

const read = name => fs.readFileSync(path.join(__dirname, name), 'utf8');
const escapeHtml = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const settle = () => new Promise(resolve => setImmediate(resolve));
const basis = {project_ref:'project-a', input_version:1, revision:2, brief_sha256:'a'.repeat(64)};

const method = [
 'Step 1: Establish the reference — Reproduce the transparent baseline\nInputs: the public series A\nProcedure: fit the baseline on 2010-2019\nOutput: baseline error table\nDecision: baseline error is recorded\nIf blocked: narrow to the available years\nTimebox: 2 weeks',
 'Step 2: Build the proposed method — Fit the proposed model\nInputs: baseline error table\nProcedure: fit with the frozen rule\nOutput: prediction file\nDecision: error below baseline on the holdout\nIf blocked: report the limited comparison\nTimebox: 3 weeks',
 'Response validation\nWhy this check applies: not a response question.'
].join('\n\n');
const directionPlan = () => ({kind:'Stage3DirectionPlanningResult', planning_status:'conditional-draft',
 question_plans:[{question_ref:'q1', method, materials:'Series A is listed but not yet verified.', design:'Compare with the transparent baseline.',
  interpretation:'Proposed error must be lower on the holdout.', minimum_deliverable:'One baseline table.', unknowns:['Series A licence: not confirmed', 'Holdout years: undecided']}]});
const directionView = (plan = directionPlan()) => ({...basis, plan, job:{plan_manifest_sha256:'b'.repeat(64), request_sha256:'c'.repeat(64)},
 direction_context:{questions:[{question_ref:'q1', text:'Does the proposed method beat the baseline?'}]}});

function strictPlan(withSteps) {
 const plan = {kind:'Stage3ResearchPlan', schema_version:withSteps ? '1.2.0' : '1.0.0', questions:[{question_ref:'q1', text:'Strict question?'}],
  question_plans:[{question_ref:'q1', measurement:'Measure the error', minimum_deliverable:'Minimum table', resource_uses:[{resource_id:'r1', purpose:'baseline series'}]}],
  designs:[{design_id:'d1', family:'holdout comparison', procedure:'Compare on the holdout', stop_conditions:['stop if data is missing'], credibility_checks:['check leakage']}],
  analyses:[{analysis_id:'a1', method:'paired error', criteria:['error below baseline']}],
  resources:[{resource_id:'r1', availability:'available', minimum:'series A', fitness:'fits 2010-2019'}],
  results:[{result_id:'x1', artifact:'error table'}], unknowns:[{description:'Licence unknown'}],
  milestones:[{milestone_id:'m1', description:'Reproduce baseline', depends_on:[], deliverable:'baseline table'},
   {milestone_id:'m2', description:'Fit the model', depends_on:['m1'], deliverable:'prediction file'}]};
 if (withSteps) {
  plan.milestones[0].step = {inputs:['/resources/0/minimum'], operation:'/designs/0/procedure', outputs:['/milestones/0/deliverable'],
   success_criteria:['/analyses/0/criteria/0'], named_entities:[]};
  plan.milestones[1].step = {inputs:['/milestones/0/deliverable'], operation:'/milestones/1/description', outputs:['/milestones/1/deliverable'],
   success_criteria:['/designs/0/credibility_checks/0'], named_entities:[]};
 }
 return plan;
}

function fixture({view = null, error = '', requests = [], guide = null} = {}) {
 const app = {page:'workspace', stage:3, lang:'zh', el:{querySelector:() => null, contains:() => true}};
 const v93 = {view, basis:view ? basis : null, busy:false, error, errorBasis:error ? basis : null, sequence:0};
 const calls = [];
 const ctx = {rt:{ref:'project-a', epoch:1, overview:{project:{...basis, brief:{original_description:'Synthetic topic'}}}}, apps:[app],
  v93, laterStage:() => '<later/>', v7AfterRender:() => {}, livePaint:() => {}, rx:escapeHtml, rl:zh => zh,
  v93Identity:() => ({...basis}), v93Matches:(a, b) => !!a && !!b && ['project_ref','input_version','revision','brief_sha256'].every(k => a[k] === b[k]),
  v93Fragment:() => '#project-a?stage=3', v9ConnectionConnected:() => true, v9ConnectionPanel:() => '<connection-panel/>', v9ConnectionModel:() => ({phase:'ready', connected:true, canWrite:true, token:'t', code:null}),
  wikiS2ConnectionLine:() => ({tone:'done', tag:'已接通', text:'这个课题已接通', buttons:[]}),
  v9StaticStage3Read:() => false, wikiHarnessRecord:() => '<div data-wiki-record>这一段还没有记录</div>',
  v93QuestionResourceUses:() => [{resource:{name:'Series A', status:'available', purpose:'baseline'}, resource_ref:{purpose:'baseline series', fit_status:'fits'}}],
  v93PublicArchive:() => '<section>archive</section>',
  v93ReadSaved:async (a, b) => { calls.push([a === app, b]); }, v94:guide || {status:'idle'},
  document:{addEventListener:() => {}}, setTimeout, console};
 vm.createContext(ctx);
 vm.runInContext(read('wiki-stage3.js'), ctx);
 return {ctx, app, calls, v93};
}
const page = f => f.ctx.laterStage(f.app);

test('direction plans: steps, four fields, overview and open checks come from the saved text only', () => {
 const f = fixture({view:directionView()});
 const model = f.ctx.wikiS3Model(f.v93.view, f.v93.view.plan);
 assert.equal(model.steps.length, 2);
 assert.equal(model.steps[0].title, 'Reproduce the transparent baseline');
 assert.equal(model.steps[0].inputs[0].text, 'the public series A');
 assert.equal(model.steps[0].criteria[0].text, 'baseline error is recorded');
 assert.equal(model.steps[0].branch, 'narrow to the available years');
 assert.equal(model.unknowns.length, 2);
 assert.equal(model.overview.question[0], 'Does the proposed method beat the baseline?');
 const html = page(f);
 assert.match(html, /条件式草案 · v1/);
 assert.match(html, /2 项条件待确认/);
 assert.match(html, /还没有执行实验/);
 assert.doesNotMatch(html, /<later\/>/);
});

test('overview marks a missing card as 还缺 instead of inventing content', () => {
 const plan = directionPlan(); delete plan.question_plans[0].minimum_deliverable;
 const html = page(fixture({view:directionView(plan)}));
 assert.match(html, /data-s3-card="minimum"[^]*?还缺：规划没有写“最低可行方案”/);
 assert.doesNotMatch(html, /data-s3-card="question"[^]*?还缺[^]*?data-s3-card="data"/);
});

test('strict 1.2.0 plans resolve step cells; older plans say 这一版没有提供', () => {
 const f = fixture({view:directionView(strictPlan(true))});
 const model = f.ctx.wikiS3Model(f.v93.view, f.v93.view.plan);
 assert.equal(model.steps[0].inputs[0].text, 'series A');
 assert.equal(model.steps[0].operation.text, 'Compare on the holdout');
 assert.equal(model.steps[1].inputs[0].text, 'baseline table');
 assert.deepEqual(Array.from(model.steps[0].next), ['m1']);
 const old = fixture({view:directionView(strictPlan(false))});
 const html = page(old);
 assert.match(html, /为什么做[^]*?这一版没有提供/);
 const card = html.slice(html.indexOf('data-s3-step="m0"'));
 assert.equal((card.slice(0, card.indexOf('</article>')).match(/这一版没有提供/g) || []).length, 5, 'why + four cells');
});

test('only the selected step expands and shows 输入/操作/产出/判据/去向/实际产出', () => {
 const f = fixture({view:directionView()});
 const html = page(f);
 assert.equal((html.match(/class="ws3-step-body"/g) || []).length, 1);
 for (const label of ['<h4>输入</h4>', '<h4>操作</h4>', '<h4>产出</h4>', '<h4>判据</h4>', '去向', '实际产出']) assert.ok(html.includes(label), label);
 assert.match(html, /实际产出<\/b> 还没有：规划还没有执行/);
 f.app.wikiS3.selected = 's1';
 assert.match(page(f), /Fit the proposed model/);
});

test('review: absent says 还没有 with the reason; present renders rows, jump links and totals', () => {
 const absent = page(fixture({view:directionView()}));
 assert.match(absent, /data-s3-review[^]*?还没有：页面这次没有读到对这份规划的评审/);
 const review = {kind:'Stage3SemanticReview', reviewer:{kind:'native-model'}, findings:[
  {question_ref:'q1', axis:'answerability', status:'adequate', reason:'Clear question', plan_locations:['/question_plans/0/method'], revision:null, missing_information:null},
  {question_ref:'q1', axis:'resource-fit', status:'needs-revision', reason:'Licence not shown', plan_locations:['/question_plans/0/materials'],
   revision:{location:'/question_plans/0/materials', action:'State the licence terms'}, missing_information:null},
  {question_ref:'q1', axis:'feasibility', status:'unknown', reason:'Years undecided', plan_locations:['/question_plans/0/design'],
   revision:null, missing_information:{needed:'holdout years', owner:'data owner'}},
  {question_ref:'q1', axis:'result-interpretation', status:'adequate', reason:'Old record', plan_locations:['/question_plans/0/interpretation']}]};
 const view = {...directionView(), review};
 const html = page(fixture({view}));
 assert.match(html, /评审者：系统/);
 assert.match(html, /资料与材料<\/th><td><span class="ws3-verdict ws3-v-edit"><span aria-hidden="true">✎<\/span> 要修改/);
 assert.match(html, /data-s3-jump="\/question_plans\/0\/materials">State the licence terms/);
 assert.match(html, /需要补：holdout years（问谁：data owner）/);
 assert.match(html, /这一版没有提供/);
 assert.match(html, /通过 2 \/ 4<span class="ws3-ntag">工程测试<\/span>/);
});

test('jump targets map plan locations to step cards, overview cards and the open-check list', () => {
 const f = fixture({view:directionView()});
 const model = f.ctx.wikiS3Model(f.v93.view, f.v93.view.plan);
 assert.equal(f.ctx.wikiS3JumpTarget(model, '/question_plans/0/materials'), 'card:data');
 assert.equal(f.ctx.wikiS3JumpTarget(model, '/question_plans/0/unknowns/1'), 'unknowns');
 assert.equal(f.ctx.wikiS3JumpTarget(model, '/question_plans/0/method'), 'step:s0');
 assert.equal(f.ctx.wikiS3JumpTarget(model, '/milestones/1/step'), 'step:m1');
 assert.equal(f.ctx.wikiS3JumpTarget(model, 'no-pointer'), null);
});

test('decision stays disabled with a written reason; no fake submit', () => {
 const html = page(fixture({view:directionView()}));
 const block = html.slice(html.indexOf('data-s3-decision'));
 assert.match(block, /接受计划[^]*?按建议修改后再评审[^]*?退回 Stage 2 重选/);
 assert.equal((block.match(/type="radio"[^>]*disabled/g) || []).length, 3);
 assert.match(block, /<button type="button" class="hs-button" disabled>确认<\/button>/);
 assert.match(block, /现在还不能做这一步：页面读不到对计划的正式决定入口/);
 assert.match(block, /接受也不会启动实验/);
});

test('drawing modes: unavailable ones are disabled with the reason; excerpt is used without steps', () => {
 const f = fixture({view:directionView()});
 const html = page(f);
 assert.match(html, /data-s3-draw="loop" aria-pressed="false" disabled>反馈循环（拟议）<small>这份规划没有提供/);
 assert.match(html, /顺序表示规划怎么组织；各步骤还没有执行。/);
 assert.match(html, /未提供步骤之间的关系|完整关系与来源（1）/);
 const plan = directionPlan(); plan.question_plans[0].method = 'Free-form text without step headings.';
 const excerpt = page(fixture({view:directionView(plan)}));
 assert.match(excerpt, /data-s3-draw="excerpt" aria-pressed="true"/);
 assert.match(excerpt, /原文顺序不表示因果或反馈关系/);
 assert.match(excerpt, /已记录的方法说明/);
});

test('flow board puts retreats on the right with the plan\'s own wording', () => {
 const html = page(fixture({view:directionView()}));
 assert.match(html, /ws3-branch[^]*?narrow to the available years/);
 assert.match(html, /<h3>退路（2 条）<\/h3>/);
});

test('auto read: one GET per project version, failure keeps a retry button instead of looping', async () => {
 const f = fixture();
 f.ctx.v93Identity = () => ({...basis});
 f.app.wikiS3 = undefined;
 f.ctx.v7AfterRender(f.app); f.ctx.v7AfterRender(f.app);
 await settle();
 assert.equal(f.calls.length, 1, 'repeated renders do not repeat the read');
 assert.equal(f.calls[0][0], true);
 assert.match(page(f), /正在读取已保存的规划，不会重新生成。/);
 const failed = fixture({error:'boom'});
 failed.ctx.v7AfterRender(failed.app); await settle();
 assert.equal(failed.calls.length, 0, 'a recorded failure is not retried automatically');
 const html = page(failed);
 assert.match(html, /读取失败[^]*?data-v93-read>重新读取/);
 assert.doesNotMatch(html, /查看已保存的规划/);
});

test('no saved plan: says so and keeps reading state out of the way', () => {
 const f = fixture({view:{...basis, plan:null}});
 assert.match(page(f), /目前没有已保存的规划，图里只显示已有的问题和待确认事项。/);
});

test('connection block is dropped once connected and saved; it shows before the plan exists', () => {
 const saved = page(fixture({view:directionView()}));
 assert.doesNotMatch(saved, /data-wiki-s3-conn/);
 const waiting = page(fixture());
 assert.match(waiting, /data-wiki-s3-conn/);
 assert.doesNotMatch(waiting, /connection-panel/, 'the old V9 panel is not used on the V1 page');
});

test('hand-written draft: summary says 人工规划草案 and the amber line appears', () => {
 const f = fixture({view:directionView()});
 const model = f.ctx.wikiS3Model(f.v93.view, f.v93.view.plan);
 const row = f.ctx.wikiS3SummaryRow(f.app, model, 2);
 assert.match(row, /人工规划草案 · v2/);
 assert.match(f.ctx.wikiS3DraftLine(2), /由你修改，还没有经过科学审查，也没有执行研究/);
 assert.equal(f.ctx.wikiS3DraftLine(null), '');
});

test('materials tab holds the rules, links no fake upload and keeps the unreviewed marker', () => {
 const f = fixture({view:directionView()});
 const html = f.ctx.wikiS3MaterialsTab(f.v93.view);
 assert.match(html, /最多 128 MiB/);
 assert.match(html, /这个版本还没有完整材料/);
 assert.match(html, /文件关联不等于已阅读、获准使用或科学接受/);
 assert.doesNotMatch(html, /type="file"/);
});

test('reading never sends a write: the bridge read is one GET and the page code has no write calls', async () => {
 const bridge = read('v9-stage3-bridge.js');
 const body = bridge.slice(bridge.indexOf('async function v93ReadSaved'), bridge.indexOf("document.addEventListener('click'", bridge.indexOf('async function v93ReadSaved')));
 assert.match(body, /liveRequest\(projectPath\(basis\.project_ref,'stage3\/planning'\)\)/);
 assert.doesNotMatch(body, /livePost|method:\s*'POST'|fetch\(/);
 const source = read('wiki-stage3.js');
 assert.doesNotMatch(source, /livePost|liveRequest|fetch\(|XMLHttpRequest|localStorage\.setItem|sessionStorage\.setItem/);
 // The ReadSaved function really issues a single request and no body.
 const requests = [];
 const ctx = {rt:{epoch:1}, v93:{busy:false, sequence:0}, livePaint:() => {}, v93Identity:() => ({...basis}), v93Matches:(a, b) => a.project_ref === b.project_ref,
  projectPath:(ref, suffix) => '/api/projects/' + ref + '/' + suffix, liveRequest:async (...args) => { requests.push(args); return {...basis, plan:null}; }};
 vm.createContext(ctx);
 vm.runInContext(body.replace(/^\/\/.*$/m, ''), ctx);
 await ctx.v93ReadSaved({stage:3}, {...basis});
 assert.equal(requests.length, 1);
 assert.deepEqual(Array.from(requests[0]), ['/api/projects/project-a/stage3/planning']);
});

test('page is inactive outside Chinese Stage 3 so the other languages keep the old page', () => {
 const f = fixture({view:directionView()});
 f.app.lang = 'en';
 assert.equal(page(f), '<later/>');
 f.app.lang = 'zh'; f.app.stage = 2;
 assert.equal(page(f), '<later/>');
});

test('review P2-5: a forced read runs while an older read is in flight, and only the newest answer is kept', async () => {
 const bridge = read('v9-stage3-bridge.js');
 const body = bridge.slice(bridge.indexOf('async function v93ReadSaved'), bridge.indexOf("document.addEventListener('click'", bridge.indexOf('async function v93ReadSaved')));
 const pending = [];
 const ctx = {rt:{epoch:1}, v93:{busy:false, sequence:0}, livePaint:() => {}, v93Identity:() => ({...basis}), v93Matches:(a, b) => a.project_ref === b.project_ref,
  projectPath:(ref, suffix) => '/api/projects/' + ref + '/' + suffix, liveRequest:() => new Promise(resolve => pending.push(resolve))};
 vm.createContext(ctx);
 vm.runInContext(body.replace(/^\/\/.*$/m, ''), ctx);
 const first = ctx.v93ReadSaved({stage:3}, {...basis});
 const skipped = ctx.v93ReadSaved({stage:3}, {...basis});
 assert.equal(pending.length, 1, 'without force an in-flight read means no second request');
 const forced = ctx.v93ReadSaved({stage:3}, {...basis}, true);
 assert.equal(pending.length, 2, 'force reads again');
 pending[0]({...basis, plan:null, marker:'old'});
 pending[1]({...basis, plan:null, marker:'new'});
 await Promise.all([first, skipped, forced]);
 assert.equal(ctx.v93.view.marker, 'new');
 assert.equal(ctx.v93.busy, false);
});
