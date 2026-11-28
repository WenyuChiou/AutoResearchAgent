// Stage 3 「按修改稿重新生成计划」 (interface: stage3-replan-interface-1127.md). Runs the shipped modules against an
// in-memory planning service. No network; the run endpoint is a stand-in and no model is involved.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');

const H = c => c.repeat(64);
const basis = {project_ref:'project-r', input_version:1, revision:4, brief_sha256:H('a')};
const REV = H('r'), DEC = H('d'), CMT = H('c'), SHA = H('5');
const request = {...basis, selection_request_sha256:H('b'), mode:'replan-from-revision', key:'stage3-replan-k1', decision_receipt_sha256:DEC, plan_revision_receipt_sha256:REV};
const savedPlan = {kind:'Stage3ResearchPlan', questions:[{question_ref:'q1', text:'第一个问题'}], question_plans:[
 {question_ref:'q1', method:'旧方法', design:'旧设计', minimum_deliverable:'旧交付', unchanged:'x'}, {question_ref:'q2', method:'二的方法', analysis:'二的分析'}]};
const revisedPlan = {question_plans:[
 {question_ref:'q1', method:'新方法', design:'旧设计', minimum_deliverable:'新交付'}, {question_ref:'q2', method:'二的方法', analysis:'二的新分析'}]};
const feedback = {records:[
 {receipt_sha256:CMT, record:{kind:'comment', question_ref:'q1', text:'评语一'}},
 {receipt_sha256:REV, record:{kind:'revision', plan:revisedPlan, comments:[CMT], changes:[]}}]};
const planView = {...basis, plan:savedPlan, feedback, job:{status:'completed', outcome:'saved', request_sha256:H('f')}, planning_configured:true, default_request:{...basis, key:'stage3-first', selection_request_sha256:H('b')},
 replan:{available:true, reason:null, request:{...request}, job:null, from_revision_receipt_sha256:REV, from_decision_receipt_sha256:DEC}};

function load({view = {}, both = false} = {}) {
 const posts = [], reads = [], readArgs = [];
 const ctx = vm.createContext({
  console, JSON, Object, Number, String, Array, Error, Map, Set, Math, Date, Promise, TextEncoder,
  rt:{ref:'project-r', epoch:1, loading:false, busy:false, pending:null, controlHeld:false},
  v93:{busy:false, basis, view:{...planView, ...view}},
  apps:[{el:{contains:() => true, querySelector:() => null}}],
  v93Identity:() => ctx.v93.basis, v93Matches:(a, b) => !!a && !!b && a.project_ref === b.project_ref,
  wikiS3Escape:value => String(value).replaceAll('<', '&lt;'), projectPath:(ref, tail) => `/api/projects/${ref}/${tail}`, livePaint:() => {},
  v93ReadSaved:async (...args) => { reads.push(1); readArgs.push(args); },
  liveRequest:async (p, body) => { posts.push({p, body:JSON.parse(JSON.stringify(body))}); return ctx.answer(p, body); },
  answer:(p, body) => ({kind:'ProjectStage3PlanningJob', project_ref:'project-r', key:body.key, request_sha256:SHA, status:'intent-recorded'}),
  v9ConnectionConnected:() => true, crypto:{randomUUID:() => 'k'}, wikiS3Decision:noPlan => `<stub ${noPlan}>`,
  document:{listeners:{}, addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }}
 });
 if (both) vm.runInContext(fs.readFileSync(path.join(__dirname, 'wiki-stage3-decision.js'), 'utf8'), ctx);
 vm.runInContext(fs.readFileSync(path.join(__dirname, 'wiki-stage3-replan.js'), 'utf8'), ctx);
 return {ctx, posts, reads, readArgs};
}
const line = ctx => ctx.wikiS3RpLine(ctx.v93.view);
const html = ctx => ctx.wikiS3RpMarkup(ctx.v93.view);
// The Host's frozen list (replan.job.revision_input, 29c4d5d1 project_stage3_replan.py _frozen_view): the page shows exactly this.
const frozenInput = (changes = [
 {question_ref:'q1', field:'method', model_value:'旧方法', researcher_value:'新方法'},
 {question_ref:'q1', field:'minimum_deliverable', model_value:'旧交付', researcher_value:'新交付'},
 {question_ref:'q2', field:'analysis', model_value:'二的分析', researcher_value:'二的新分析'}]) => ({plan_revision_receipt_sha256:REV, decision_receipt_sha256:DEC,
 parent_request_sha256:H('q'), parent_plan_manifest_sha256:H('b'), changes, comments:[{question_ref:'q1', text:'评语一'}], revision_input_sha256:H('i')});
const withJob = (extra = {}, job = {}) => ({replan:{...planView.replan, job:{kind:'ProjectStage3PlanningJob', project_ref:'project-r', key:request.key, request_sha256:SHA, status:'intent-recorded', revision_input:frozenInput(), ...job}}, ...extra});
const attempt = (extra = {}) => ({key:'stage3-replan-old', request_sha256:H('a'), status:'execution-unknown', outcome:null, result_unknown:true, read_only:true, recovery_pin_available:false,
 revision_input:{...frozenInput(), decision_receipt_sha256:H('e'), plan_revision_receipt_sha256:H('f')}, job:{status:'execution-unknown'}, ...extra});
const withAttempts = (list, over = {}) => ({replan:{...planView.replan, attempts:list, attempts_omitted:0, ...over}});
const tick = (ctx, sha = SHA) => { line(ctx); vm.runInContext(`wikiS3Rp.check = {sha:'${sha}', edits:${JSON.stringify(JSON.stringify(ctx.wikiS3RpEdits(ctx.v93.view).changes))}}`, ctx); };
const act = (ctx, name, target) => ctx.wikiS3RpAction(ctx.apps[0], name, target);
const textOf = markup => markup.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ');

test('the entry replaces the disabled stub: shown with edits against the revision, grayed with its reason without them', () => {
 let {ctx} = load();
 let row = line(ctx);
 assert.equal(row.tag, '还没请求');
 assert.equal(row.buttons[0].label, '按修改稿重新生成计划');
 assert.equal(row.buttons[0].act, 'prepare');
 assert.equal(row.buttons[0].gate, '');
 assert.doesNotMatch(html(ctx), /需要后台新增|只读选方向时的材料/);
 // The entry does not depend on the page's own reading of the revision: there is no list before prepare, the Host freezes it.
 ({ctx} = load({view:{feedback:undefined}}));
 assert.equal(line(ctx).buttons[0].gate, '');
 assert.doesNotMatch(html(ctx), /data-s3-rp-edits/, 'no edit list before prepare');
 assert.match(line(ctx).text, /准备后后台会给出要送给规划模型的修改清单/);
 // Inside the decision block the stub is gone and this entry stands in its place.
 ({ctx} = load({both:true}));
 const saved = {receipt_sha256:DEC, record:{kind:'decision', sequence:1, decision:'revise-then-review', request:{key:'d1'}, binding:{}}};
 const binding = {project_ref:'project-r', revision:4, input_version:1, brief_sha256:H('a'), parent_plan_manifest_sha256:H('b'), parent_plan_sha256:H('c'), plan_request_sha256:H('d'), plan_revision_receipt_sha256:REV};
 ctx.v93.view.job = {outcome:'saved', planning_status:'draft', plan_manifest_sha256:H('b'), request_sha256:H('d')};
 ctx.v93.view.host_decision = {kind:'ProjectStage3PlanDecisionView', schema_version:1, binding, has_manual_revision:true, revision_ambiguous:false, records:[saved], latest:saved, history:[]};
 const block = ctx.wikiS3Decision();
 assert.match(block, /data-s3-replan/);
 assert.match(block, /按修改稿重新生成计划/);
 assert.doesNotMatch(block, /需要后台新增|只读选方向时的材料|disabled>请求生成计划/);
});

test('prepare: zero model, the body is replan.request without request_sha256, then a forced re-read; busy and lock gate it', async () => {
 const {ctx, posts, reads, readArgs} = load({view:{replan:{...planView.replan, request:{...request, request_sha256:H('9')}}}});
 await act(ctx, 'prepare');
 assert.equal(posts.length, 1);
 assert.equal(posts[0].p, '/api/projects/project-r/stage3/planning/prepare');
 assert.equal(posts[0].body.request_sha256, undefined, 'prepare must not carry request_sha256 (extra field is a 400)');
 assert.equal(JSON.stringify(posts[0].body), JSON.stringify(request));
 assert.equal(posts[0].body.mode, 'replan-from-revision');
 assert.equal(reads.length, 1);
 assert.equal(readArgs[0][2], true, 'the re-read is forced');
 // A lock that appeared after drawing still stops it.
 const second = load();
 second.ctx.rt.pending = {ref:'project-r'};
 await act(second.ctx, 'prepare');
 assert.equal(second.posts.length, 0);
 // The page's own feedback records do not gate the zero-quota prepare.
 const third = load({view:{feedback:undefined}});
 await act(third.ctx, 'prepare');
 assert.equal(third.posts.length, 1);
});

test('before confirming, every edit is listed: question, item, original value, the researcher edit; plus the cited comments', () => {
 // The page's own feedback holds a different draft: it is ignored, the Host's frozen list is what is shown.
 const {ctx} = load({view:{...withJob(), feedback:{records:[{receipt_sha256:REV, record:{kind:'revision', plan:{question_plans:[{question_ref:'q1', method:'本地改的另一份', design:'旧设计'}]}, comments:[]}}]}}});
 const edits = ctx.wikiS3RpEdits(ctx.v93.view);
 assert.equal(edits.changes.length, 3);
 assert.deepEqual(JSON.parse(JSON.stringify(edits.changes.map(c => [c.question_ref, c.field, c.model_value, c.researcher_value]))),
  [['q1', 'method', '旧方法', '新方法'], ['q1', 'minimum_deliverable', '旧交付', '新交付'], ['q2', 'analysis', '二的分析', '二的新分析']]);
 const out = html(ctx), text = textOf(out);
 assert.equal((out.match(/data-s3-rp-edit>/g) || []).length, 3);
 for (const piece of ['第一个问题', 'q1', '方法', '原值（模型生成的上一版）', '旧方法', '你的修改', '新方法', '最小交付', '旧交付', '新交付', '分析', '二的分析', '二的新分析', '评语一']) assert.ok(text.includes(piece), piece);
 assert.doesNotMatch(text, /旧设计/, 'an unchanged item is not listed');
 assert.match(text, /共 3 处/);
 assert.match(text, /修订稿附带的材料引用不会送出/);
 assert.match(out, /data-s3-rp-grant/);
 assert.match(out, /data-s3-rp-check\s*>/, 'unticked');
 assert.doesNotMatch(text, /本地改的另一份/, 'the page never builds its own list');
 // An HTML-looking value is escaped by the page's escape.
 const cleared = load({view:withJob({}, {revision_input:frozenInput([{question_ref:'q1', field:'method', model_value:'', researcher_value:'<b>x'}])})});
 assert.match(html(cleared.ctx), /&lt;b>x/);
 assert.match(html(cleared.ctx), /（空）/);
});

test('the confirmation is bound to that prepare request_sha256 and to the edit list shown; a new prepare or a changed edit voids it', async () => {
 const {ctx, posts} = load({view:withJob()});
 assert.equal(line(ctx).grant.gate, '请先勾选确认');
 for (const fn of ctx.document.listeners.change) fn({target:{matches:selector => selector === '[data-s3-rp-check]', checked:true}});
 assert.equal(line(ctx).grant.gate, '');
 assert.match(html(ctx), /data-s3-rp-check checked/);
 // A different prepare (another request_sha256): the tick is void.
 ctx.v93.view = {...ctx.v93.view, ...withJob({}, {request_sha256:H('7')})};
 assert.equal(line(ctx).grant.gate, '请先勾选确认');
 assert.doesNotMatch(html(ctx), /data-s3-rp-check checked/);
 await act(ctx, 'run');
 assert.equal(posts.length, 0, 'a void tick sends nothing');
 // Same request but the revision's edits changed under the tick.
 ctx.v93.view = {...ctx.v93.view, ...withJob()};
 for (const fn of ctx.document.listeners.change) fn({target:{matches:selector => selector === '[data-s3-rp-check]', checked:true}});
 assert.equal(line(ctx).grant.gate, '');
 ctx.v93.view.replan.job.revision_input = frozenInput([{question_ref:'q1', field:'method', model_value:'旧方法', researcher_value:'又改了'}]);
 assert.equal(line(ctx).grant.gate, '请先勾选确认');
});

test('run: only after the tick; sends the same request plus request_sha256 and confirmed:true; the job is not re-prepared', async () => {
 const {ctx, posts, reads} = load({view:withJob()});
 await act(ctx, 'run');
 assert.equal(posts.length, 0, 'not ticked: nothing sent');
 tick(ctx);
 ctx.answer = (p, body) => ({kind:'ProjectStage3PlanningSubmission', job:{project_ref:'project-r', key:body.key, request_sha256:SHA, status:'dispatching'}});
 await act(ctx, 'run');
 assert.equal(posts.length, 1);
 assert.equal(posts[0].p, '/api/projects/project-r/stage3/planning/run');
 assert.equal(JSON.stringify(posts[0].body), JSON.stringify({...request, request_sha256:SHA, confirmed:true}));
 assert.equal(reads.length, 1);
 assert.equal(vm.runInContext('wikiS3Rp.check', ctx), null, 'the tick is consumed');
 // A lock that appeared after drawing stops a ticked run.
 const locked = load({view:withJob()});
 tick(locked.ctx); locked.ctx.rt.controlHeld = true;
 await act(locked.ctx, 'run');
 assert.equal(locked.posts.length, 0);
});

const doc = {
 'stage3-replan-direction-mode-unsupported':'方向意图阶段（还没选定方向）不支持按修改稿重新生成，请先在 Stage 2 选定方向。',
 'stage3-replan-revision-required':'还没有手工修订稿，请先用「评语与修订」改计划。',
 'stage3-decision-revision-ambiguous':'这份计划有两份并列的修订稿，请先在其中一份基础上继续修订。',
 'stage3-replan-decision-required':'需要先对这份修订稿选择「按建议修改后再评审」。',
 'stage3-replan-decision-differs':'这个决定是针对旧的修订稿做的，请对当前这份重新决定。',
 'stage3-replan-decision-superseded':'你后来对这份修订稿做了别的决定，不能再按它重新生成计划；如要重新规划，请先重新选择「按建议修改后再评审」。',
 'stage3-replan-plan-unreadable':'有一份更新的计划暂时读不出来（通常是系统升级后缺少可信校验值），先不能按这一版再生成，请联系维护者。'
};
const others = {'stage3-replan-revision-changed':/修订稿已经变了/, 'stage3-replan-input-too-large':/48,000 字节.*不会截断，请精简修订稿/,
 'stage3-replan-key-payload-differs':/操作编号已被另一份内容占用/, 'stage3-replan-mode-required':/只能用「按修改稿重新生成」运行/, 'stage3-job-not-prepared':/还没有准备好/,
 'stage3-planning-unconfigured':/没有提供规划配置/, 'stage3-project-version-differs':/版本已经变了/, 'stage3-current-selection-required':/Stage 2 选择/,
 'stage3-replan-key-differs':/编号的校验不对/, 'stage3-replan-key-reserved':/留给按修改稿重新生成/, 'stage3-replan-mode-invalid':/格式不对/,
 'stage3-replan-receipt-invalid':/回执格式不对/, 'intake-fields-invalid':/缺少或多了字段/, 'explicit-stage3-planning-required':/明确确认后才能运行/,
 'stage3-planning-project-busy':/另一次 Stage 3 保存正在进行/, 'stage3-planning-input-rejected':/另一次保存/, 'stage3-planning-body-bound-exceeded':/请求太大/,
 'credential-rejected':/凭据不对/, 'cross-site-rejected':/请求来源不对/};

test('refusal codes: not-available reasons use the interface wording, the raw code only in technical details', () => {
 for (const [code, text] of Object.entries(doc)) {
  const {ctx} = load({view:{replan:{...planView.replan, available:false, reason:code, request:null}}});
  const row = line(ctx), out = html(ctx);
  assert.equal(row.buttons[0].gate, text, code);
  assert.ok(out.includes(text), code);
  assert.ok(row.detail.includes(code), 'raw code in the technical details: ' + code);
  const body = out.replace(/<details class="wiki-s2-tech">[\s\S]*?<\/details>/g, '');
  assert.ok(!body.includes(code), 'the raw code is not body text: ' + code);
  assert.equal(row.buttons[0].act, 'prepare');
  assert.ok(row.buttons[0].gate, 'disabled');
 }
});

test('refusal codes on a request: the interface wording, 没有调用模型 on run, the raw code only in technical details, no resend', async () => {
 const codes = [...Object.keys(doc), ...Object.keys(others)];
 for (const code of codes) {
  for (const stage of ['prepare', 'run']) {
   const {ctx, posts} = load({view:stage === 'run' ? withJob() : {}});
   if (stage === 'run') tick(ctx);
   ctx.answer = () => { throw Object.assign(Error(code), {status:409}); };
   await act(ctx, stage);
   assert.equal(posts.length, 1, 'one request, no resend: ' + code);
   const row = line(ctx), out = html(ctx);
   assert.equal(row.tag, stage === 'run' ? '已拒绝，没有调用模型' : '被拦下', code);
   assert.ok(row.detail.includes(code));
   assert.ok(!out.replace(/<details class="wiki-s2-tech">[\s\S]*?<\/details>/g, '').includes(code), 'raw code is not body text: ' + code);
   if (doc[code]) assert.ok(row.text.startsWith(doc[code]), code);
   else assert.match(row.text, others[code], code);
   if (stage === 'run') assert.match(row.text, /没有调用模型/);
   assert.equal(row.grant, undefined, 'no grant card after a refusal: no one-click retry');
  }
 }
});

test('an unknown code, and codes that name an Object prototype member, get the generic wording; never the raw code as body text', async () => {
 for (const code of ['stage3-brand-new-code', 'constructor', '__proto__', 'toString', 'hasOwnProperty', 'valueOf', '']) {
  const {ctx} = load({view:withJob()});
  tick(ctx);
  ctx.answer = () => { throw Object.assign(Error(code), {status:422}); };
  await act(ctx, 'run');
  const row = line(ctx);
  assert.equal(row.tag, '已拒绝，没有调用模型');
  assert.match(row.text, /服务拒绝了这一步，原因代码在技术细节里。/, JSON.stringify(code));
  assert.doesNotMatch(row.text, /function|\[object|undefined/);
  if (code) assert.ok(!html(ctx).replace(/<details class="wiki-s2-tech">[\s\S]*?<\/details>/g, '').includes(code), code);
  const gated = load({view:{replan:{...planView.replan, available:false, reason:code, request:null}}});
  assert.equal(line(gated.ctx).buttons[0].gate, '服务拒绝了这一步，原因代码在技术细节里。', 'reason ' + JSON.stringify(code));
 }
});

test('refused-before-call: the job outcome and the answer to run both say 已拒绝，没有调用模型, with no run button', async () => {
 const {ctx} = load({view:withJob({}, {status:'completed', outcome:'refused-before-call'})});
 const row = line(ctx), out = html(ctx);
 assert.equal(row.tag, '已拒绝，没有调用模型');
 assert.match(row.text, /这次生成在调用模型之前被拒绝（修订稿或决定刚刚变了），没有花额度。请刷新后按当前的修订稿和决定重新请求生成。/);
 assert.doesNotMatch(out, /data-s3-rp="(run|prepare)"/);
 assert.ok(row.detail.includes('refused-before-call'));
 // The answer to run itself: the key then changes in the re-read, but the notice stays until the next action.
 const run = load({view:withJob()});
 tick(run.ctx);
 run.ctx.answer = (p, body) => ({kind:'ProjectStage3PlanningSubmission', job:{project_ref:'project-r', key:body.key, request_sha256:SHA, status:'completed', outcome:'refused-before-call'}});
 await act(run.ctx, 'run');
 run.ctx.v93.view = {...planView}; // the re-read brings a new request (new key): prepare is open again
 const after = line(run.ctx);
 assert.equal(after.notice.tag, '已拒绝，没有调用模型');
 assert.match(html(run.ctx), /data-s3-rp-notice/);
 assert.equal(after.buttons[0].act, 'prepare');
 // A new prepare clears the notice.
 await act(run.ctx, 'prepare');
 assert.equal(line(run.ctx).notice, null);
});

test('unreadable_plans and newer_plan_unreadable have visible explanations; a code that is not known gets the generic text', () => {
 const item = error => ({key:'stage3-replan-k0', request_sha256:H('1'), error, error_class:'Stage3Error', parent_request_sha256:H('2'), from_revision_receipt_sha256:REV, from_decision_receipt_sha256:DEC});
 const env = load({view:{unreadable_plans:[item('stage3-replan-plan-environment-changed')]}});
 let out = textOf(env.ctx.wikiS3RpNotices(env.ctx.v93.view));
 assert.match(out, /因为系统升级暂时读不出来，计划本身没有损坏。下面显示的是它之前的那一版；请联系维护者为它补上校验值后即可恢复。/);
 assert.match(out, /不能接受这一版，也不能再按修改稿生成/);
 out = textOf(load({view:{unreadable_plans:[item('stage3-replan-plan-data-damaged')]}}).ctx.wikiS3RpNotices({...planView, unreadable_plans:[item('stage3-replan-plan-data-damaged')]}));
 assert.match(out, /保存数据对不上，可能被改动或丢失，已停止使用它。下面显示的是它之前的那一版；请联系维护者检查。/);
 for (const error of ['stage3-saved-job-binding-differs', 'constructor', undefined]) {
  const view = {...planView, unreadable_plans:[item(error)]};
  const markup = env.ctx.wikiS3RpNotices(view);
  assert.match(textOf(markup), /暂时读不出来，原因代码在技术细节里。下面显示的是它之前的那一版/);
  if (error) assert.ok(!markup.replace(/<details class="wiki-s2-tech">[\s\S]*?<\/details>/g, '').includes(error), 'raw code only in details: ' + error);
  assert.ok(markup.includes('Stage3Error'), 'the class name is in the technical details');
 }
 assert.match(textOf(env.ctx.wikiS3RpNotices({...planView, replan_error:'stage3-replan-history-ambiguous'})), /两份并列的新计划/);
 assert.equal(env.ctx.wikiS3RpNotices({...planView}), '', 'nothing when nothing is wrong');
 // newer_plan_unreadable: the notice, and 「接受」 is grayed in the decision block with the interface wording.
 const both = load({both:true});
 const binding = {project_ref:'project-r', revision:4, input_version:1, brief_sha256:H('a'), parent_plan_manifest_sha256:H('b'), parent_plan_sha256:H('c'), plan_request_sha256:H('d'), plan_revision_receipt_sha256:null};
 both.ctx.v93.view.job = {outcome:'saved', planning_status:'draft'};
 both.ctx.v93.view.plan = {kind:'Stage3DirectionPlanningResult', planning_status:'draft', question_plans:[Object.fromEntries(['method', 'materials', 'design', 'analysis', 'interpretation', 'validation', 'minimum_deliverable'].map(f => [f, 'x']))]};
 both.ctx.v93.view.host_decision = {kind:'ProjectStage3PlanDecisionView', schema_version:1, binding, has_manual_revision:false, revision_ambiguous:false, records:[], latest:null, history:[], newer_plan_unreadable:true};
 both.ctx.v93.view.unreadable_plans = [item('stage3-replan-plan-environment-changed')];
 const block = both.ctx.wikiS3Decision();
 assert.match(textOf(block), /有一份更新的计划还读不出来，不能接受这一版；请等维护者恢复那份计划后再决定。/);
 assert.match(block, /value="accept" data-s3-dec-pick\s+disabled/);
 assert.match(block, /data-s3-rp-unreadable/);
 // Without the flag, accept stays open.
 both.ctx.v93.view.host_decision = {...both.ctx.v93.view.host_decision, newer_plan_unreadable:undefined};
 both.ctx.v93.view.unreadable_plans = [];
 assert.doesNotMatch(both.ctx.wikiS3Decision(), /value="accept" data-s3-dec-pick\s+disabled/);
});

test('result unknown: a run with no answer (network, timeout, 5xx) clears the tick, shows 结果未知, offers only the read-only check, resends nothing', async () => {
 for (const failure of [Error('Failed to fetch'), Object.assign(Error('HTTP 502'), {status:502}), Object.assign(Error('HTTP 504'), {status:504}), Object.assign(Error('timeout'), {name:'TimeoutError'})]) {
  const {ctx, posts} = load({view:withJob()});
  tick(ctx);
  ctx.answer = () => { throw failure; };
  await act(ctx, 'run');
  // The re-read still says intent-recorded (the service may not have written yet).
  const row = line(ctx);
  assert.equal(row.tag, '结果未知', failure.message);
  assert.equal(row.grant, undefined, 'no grant card, so no one-click resend');
  assert.equal(row.buttons.map(b => b.act).join(), 'inspect,read');
  assert.equal(vm.runInContext('wikiS3Rp.check', ctx), null, 'the tick is cleared');
  assert.doesNotMatch(html(ctx), /data-s3-rp="run"/);
  assert.ok(row.detail.includes(failure.message));
  assert.match(row.text, /模型可能已经调用过。不会重发/);
  // Forcing the old tick and calling run again sends nothing.
  vm.runInContext(`wikiS3Rp.check = {sha:'${SHA}', edits:${JSON.stringify(JSON.stringify(ctx.wikiS3RpEdits(ctx.v93.view).changes))}}`, ctx);
  await act(ctx, 'run');
  assert.equal(posts.length, 1, 'no resend');
  // The read-only check: an answer for another key does not settle it; the right key does.
  ctx.answer = () => ({kind:'ProjectStage3PlanningJob', project_ref:'project-r', key:'other', status:'intent-recorded'});
  await act(ctx, 'inspect');
  assert.equal(line(ctx).tag, '结果未知');
  ctx.answer = (p, body) => ({kind:'ProjectStage3PlanningJob', project_ref:'project-r', key:body.key, request_sha256:SHA, status:'execution-unknown'});
  await act(ctx, 'inspect');
  assert.equal(posts[posts.length - 1].p, '/api/projects/project-r/stage3/planning/inspect');
  assert.equal(posts[posts.length - 1].body.request_sha256, SHA);
  assert.equal(posts[posts.length - 1].body.confirmed, undefined, 'inspect is read-only');
  ctx.v93.view = {...ctx.v93.view, ...withJob({}, {status:'execution-unknown'})}; // the re-read that follows
  assert.equal(line(ctx).tag, '结果未知');
  assert.equal(line(ctx).grant, undefined);
 }
});

test('result unknown from the saved job and from a timed-out submission_error; a refused 4xx run is not unknown', async () => {
 let row = line(load({view:withJob({}, {status:'execution-unknown'})}).ctx);
 assert.equal(row.tag, '结果未知');
 assert.equal(row.buttons.map(b => b.act).join(), 'inspect,read', 'no recover button without the Host recovery_pin_available');
 const err = {code:'stage3-planning-deadline-or-io-failed', key:request.key};
 row = line(load({view:{...withJob(), submission_error:err}}).ctx);
 assert.equal(row.tag, '结果未知');
 assert.equal(row.grant, undefined);
 // A submission_error that names another key is not this request's.
 row = line(load({view:{...withJob(), submission_error:{...err, key:'stage3-replan-other'}}}).ctx);
 assert.equal(row.tag, '等你授权');
 // The read-only check finds it never dispatched: back to the grant, tick needed again.
 const {ctx} = load({view:{...withJob(), submission_error:{...err, request_sha256:SHA}}});
 ctx.answer = (p, body) => ({kind:'ProjectStage3PlanningJob', project_ref:'project-r', key:body.key, request_sha256:SHA, status:'intent-recorded'});
 await act(ctx, 'inspect');
 row = line(ctx);
 assert.equal(row.tag, '等你授权');
 assert.match(row.text, /上次在调用模型之前就停了，没有执行/);
 assert.equal(row.grant.gate, '请先勾选确认');
 // Per topic: another topic's unknown run does not replace this one.
 const two = load({view:withJob()});
 two.ctx.answer = () => { throw Error('Failed to fetch'); };
 for (const topic of ['project-r', 'project-b']) {
  two.ctx.rt.ref = topic; two.ctx.v93.basis = {...basis, project_ref:topic}; tick(two.ctx);
  await act(two.ctx, 'run');
 }
 two.ctx.rt.ref = 'project-r'; two.ctx.v93.basis = {...basis};
 assert.equal(line(two.ctx).tag, '结果未知');
});

test('double click sends one request; busy is kept per project when the user leaves and comes back', async () => {
 const {ctx, posts} = load({view:withJob()});
 tick(ctx);
 let release;
 ctx.answer = () => new Promise(resolve => { release = () => resolve({kind:'ProjectStage3PlanningSubmission', job:{project_ref:'project-r', key:request.key, request_sha256:SHA, status:'dispatching'}}); });
 const first = act(ctx, 'run'), second = act(ctx, 'run');
 await second;
 assert.equal(posts.length, 1, 'the second click sends nothing');
 ctx.rt.ref = 'project-b'; line(ctx);
 ctx.rt.ref = 'project-r'; line(ctx);
 assert.match(line(ctx).grant.gate, /正在保存，请稍等/);
 await act(ctx, 'run');
 assert.equal(posts.length, 1, 'still one after leaving and coming back');
 release(); await first;
 assert.equal(vm.runInContext('wikiS3Rp.busy.size', ctx), 0);
 // The same for prepare.
 const p = load();
 let free;
 p.ctx.answer = () => new Promise(resolve => { free = () => resolve({kind:'ProjectStage3PlanningJob', project_ref:'project-r', key:request.key, request_sha256:SHA, status:'intent-recorded'}); });
 const a = act(p.ctx, 'prepare'), b = act(p.ctx, 'prepare');
 await b;
 assert.equal(p.posts.length, 1);
 free(); await a;
});

test('other states: processing, failed, saved, not available with its reason, unreadable job, a status this page does not know', () => {
 assert.equal(line(load({view:withJob({}, {status:'dispatching'})}).ctx).tag, '处理中');
 assert.equal(line(load({view:{submission_in_progress:true}}).ctx).tag, '处理中');
 assert.equal(line(load({view:withJob({}, {status:'completed', outcome:'failed'})}).ctx).tag, '规划失败');
 assert.equal(line(load({view:withJob({}, {status:'completed', outcome:'saved'})}).ctx).tag, '计划已保存');
 let row = line(load({view:{replan:{error:'stage3-decision-record-differs'}}}).ctx);
 assert.equal(row.tag, '读不出来');
 assert.ok(row.detail.includes('stage3-decision-record-differs'));
 row = line(load({view:{replan:{...planView.replan, job:{error:'stage3-replan-job-unreadable'}}}}).ctx);
 assert.equal(row.tag, '读不出来');
 assert.equal(row.buttons.map(b => b.act).join(), 'read');
 // Never turn an unknown job into a request button.
 for (const job of [{status:'completed', outcome:'brand-new'}, {status:'brand-new'}]) {
  row = line(load({view:withJob({}, job)}).ctx);
  assert.equal(row.tag, '状态没认出来');
  assert.equal(row.buttons.map(b => b.act).join(), 'read');
  assert.equal(row.grant, undefined);
 }
 // No replan field at all: the revision is missing.
 row = line(load({view:{replan:undefined}}).ctx);
 assert.equal(row.buttons[0].gate, '还没有手工修订稿，请先用「评语与修订」改计划。');
 // replan.request in an unexpected shape is not sent.
 row = line(load({view:{replan:{...planView.replan, request:{...request, mode:'other'}}}}).ctx);
 assert.equal(row.tag, '读不出来');
 assert.equal(line(load({view:{plan:null}}).ctx), null);
});

test('no frozen edit list from the Host (missing, malformed, empty): the grant is gated with the reason and run is not sent; the page does not build one', async () => {
 for (const input of [undefined, {...frozenInput(), changes:undefined}, {...frozenInput(), changes:[{question_ref:'q1'}]}, frozenInput([])]) {
  const {ctx, posts} = load({view:withJob({}, {revision_input:input})});
  const gate = line(ctx).grant.gate;
  assert.match(gate, /没有给出这份作业冻结的修改清单|冻结的修改清单是空的/, JSON.stringify(input)?.slice(0, 40));
  assert.match(textOf(html(ctx)), /页面不自己拼|是空的/);
  vm.runInContext(`wikiS3Rp.check = {sha:'${SHA}', edits:''}`, ctx);
  await act(ctx, 'run');
  assert.equal(posts.length, 0);
 }
});

test('older attempts stay in a read-only history after a new key: result unknown has only the read-only check, nothing can be run or prepared', async () => {
 const key = 'stage3-replan-old';
 const {ctx, posts} = load({view:withAttempts([attempt(), attempt({key:'stage3-replan-r', request_sha256:H('b'), status:'completed', outcome:'refused-before-call', result_unknown:false}),
  attempt({key:'stage3-replan-p', request_sha256:H('c'), status:'intent-recorded', result_unknown:false}), attempt({key:request.key, request_sha256:SHA})], {attempts_omitted:3})});
 const out = html(ctx), text = textOf(out);
 assert.match(out, /data-s3-rp-history/);
 assert.equal((out.match(/data-s3-rp-attempt=/g) || []).length, 3, 'the current request is not repeated in the history');
 assert.match(text, /共 3 份/);
 assert.match(text, /另有 3 份更早的没有列出/);
 assert.match(text, /调用可能已经发出、额度可能已经花掉；只能只读核对，不会重发/);
 assert.match(text, /这次在调用模型之前被拒绝，没有花额度/);
 assert.match(text, /这份作业只准备过，没有调用模型/);
 const buttons = [...out.matchAll(/data-s3-rp="(\w+)" data-s3-rp-target="([^"]+)"/g)].map(m => m[1] + ':' + m[2]);
 assert.deepEqual(buttons, ['inspect:' + key], 'only the unknown attempt has a button, and it is read-only');
 assert.doesNotMatch(out, /data-s3-rp-recover-check/, 'no pin: no recovery');
 // Run / prepare / recover on an older attempt send nothing; inspect sends the read-only request for that attempt.
 for (const name of ['run', 'prepare', 'recover']) { await act(ctx, name, key); }
 assert.equal(posts.length, 0);
 ctx.answer = (p, body) => ({kind:'ProjectStage3PlanningJob', project_ref:'project-r', key:body.key, request_sha256:H('a'), status:'execution-unknown'});
 await act(ctx, 'inspect', key);
 assert.equal(posts.length, 1);
 assert.equal(posts[0].p, '/api/projects/project-r/stage3/planning/inspect');
 assert.equal(JSON.stringify(posts[0].body), JSON.stringify({project_ref:'project-r', input_version:1, revision:4, brief_sha256:H('a'), selection_request_sha256:H('b'), mode:'replan-from-revision', key, decision_receipt_sha256:H('e'), plan_revision_receipt_sha256:H('f'), request_sha256:H('a')}));
 // The history survives when replan itself is not available (a new decision changed the key and the reason).
 const gone = load({view:withAttempts([attempt()], {available:false, reason:'stage3-replan-decision-superseded', request:null})});
 assert.match(textOf(html(gone.ctx)), /以前按修改稿生成的作业（只读，共 1 份）/);
});

test('recover is offered only where the Host says recovery_pin_available, with its own tick, never a resend; the current job follows the same rule', async () => {
 const key = 'stage3-replan-old';
 const {ctx, posts} = load({view:withAttempts([attempt({recovery_pin_available:true})])});
 const out = html(ctx);
 assert.match(out, /data-s3-rp="recover" data-s3-rp-target="stage3-replan-old" disabled/);
 assert.match(out, /data-s3-rp-recover-check/);
 await act(ctx, 'recover', key);
 assert.equal(posts.length, 0, 'no tick, nothing sent');
 for (const fn of ctx.document.listeners.change) fn({target:{matches:selector => selector === '[data-s3-rp-recover-check]', checked:true, dataset:{s3RpSha:H('a')}}});
 assert.doesNotMatch(html(ctx), /data-s3-rp="recover" data-s3-rp-target="stage3-replan-old" disabled/);
 ctx.answer = (p, body) => ({kind:'ProjectStage3PlanningJob', project_ref:'project-r', key:body.key, request_sha256:H('a'), status:'completed', outcome:'saved'});
 await act(ctx, 'recover', key);
 assert.equal(posts.length, 1);
 assert.match(posts[0].p, /stage3\/planning\/recover$/);
 assert.equal(posts[0].body.mode, 'replan-from-revision');
 assert.equal(posts[0].body.request_sha256, H('a'));
 assert.equal(posts[0].body.confirmed, undefined);
 // A tick for a request_sha256 the page does not list is not accepted.
 for (const fn of ctx.document.listeners.change) fn({target:{matches:selector => selector === '[data-s3-rp-recover-check]', checked:true, dataset:{s3RpSha:H('9')}}});
 assert.equal(vm.runInContext('wikiS3Rp.recoverCheck', ctx), null);
 // Not unknown, or no pin: no recover button.
 const none = load({view:withAttempts([attempt({recovery_pin_available:true, result_unknown:false, status:'completed', outcome:'failed'})])});
 assert.doesNotMatch(html(none.ctx), /data-s3-rp="recover"/);
 // The current job.
 const cur = load({view:withJob({}, {status:'execution-unknown', recovery_pin_available:true})});
 assert.equal(line(cur.ctx).buttons.map(b => b.act).join(), 'inspect,recover,read');
 assert.equal(line(cur.ctx).buttons[1].gate, '请先勾选确认');
 const nopin = load({view:withJob({}, {status:'execution-unknown', recovery_pin_available:false})});
 assert.equal(line(nopin.ctx).buttons.map(b => b.act).join(), 'inspect,read');
 assert.match(textOf(html(cur.ctx)), /当时冻结的修改清单（3 处，只读）/);
});
