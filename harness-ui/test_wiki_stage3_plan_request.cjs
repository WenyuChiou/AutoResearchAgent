// Stage 3 「请求生成计划」 (DESIGN 8.13 lower row). Runs the shipped module against an in-memory planning service.
// No network; the run endpoint is a stand-in and no model is involved.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');

const basis = {project_ref:'project-p', input_version:1, revision:9, brief_sha256:'a'.repeat(64)};
const request = {...basis, key:'stage3-fixed', selection_request_sha256:'b'.repeat(64)};

function load({calls = 1, view = {}} = {}) {
 const posts = [], reads = [];
 const ctx = vm.createContext({
  console, JSON, Object, Number, String, Array, Error, Map,
  rt:{ref:'project-p', epoch:1, loading:false, busy:false, pending:null, controlHeld:false, meta:{run_limits:{model_calls:calls}}},
  v93:{busy:false, basis, view:{...basis, plan:null, planning_configured:true, dispatch_action:'prepare-then-confirm-run', default_request:request, job:null, ...view}},
  apps:[{el:{contains:() => true}}],
  v93Identity:() => ctx.v93.basis, v93Matches:(a, b) => !!a && !!b && a.project_ref === b.project_ref,
  wikiS3Escape:value => String(value), projectPath:(ref, tail) => `/api/projects/${ref}/${tail}`, livePaint:() => {},
  v93ReadSaved:async () => { reads.push(1); },
  liveRequest:async (p, body) => { posts.push({p, body:JSON.parse(JSON.stringify(body))}); return ctx.answer(p, body); },
  answer:(p, body) => ({kind:'ProjectStage3PlanningJob', project_ref:'project-p', key:body.key, request_sha256:'c'.repeat(64), status:'intent-recorded'}),
  document:{addEventListener() {}}
 });
 vm.runInContext(fs.readFileSync(path.join(__dirname, 'wiki-stage3-plan-request.js'), 'utf8'), ctx);
 return {ctx, posts, reads};
}
const line = ctx => ctx.wikiS3RequestLine(ctx.v93.view);

test('not requested: one green button; gray with a reason for zero quota, no planning configuration, or a lock', () => {
 let {ctx} = load();
 let row = line(ctx);
 assert.equal(row.tag, '还没请求');
 assert.match(row.text, /你选的方向已保存。可以请求生成研究计划/);
 assert.equal(row.buttons[0].act, 'prepare');
 assert.equal(row.buttons[0].gate, '');
 // Review P1-3: the run's model-call limit does not bind planning; zero or missing run limits leave it open.
 for (const calls of [0, null]) {
  ({ctx} = load({calls}));
  assert.equal(line(ctx).buttons[0].gate, '', 'run_limits ' + calls);
  assert.doesNotMatch(ctx.wikiS3RequestMarkup(ctx.v93.view), /模型调用上限是|读不到这次启动/);
 }
 ({ctx} = load({calls:0, view:{job:{status:'intent-recorded', request_sha256:'c'.repeat(64)}}}));
 assert.doesNotMatch(ctx.wikiS3RequestMarkup(ctx.v93.view), /这次启动的模型调用上限/, 'the grant card does not quote the run limit');
 assert.match(ctx.wikiS3RequestMarkup(ctx.v93.view), /规划的调用和时长上限后台没有返回给页面/);
 // Review P2-4: missing planning information is its own reason, with the blockers in the technical details.
 ({ctx} = load({view:{planning_configured:true, dispatch_action:'needs-information', default_request:null, planning_blockers:['direction-question-missing']}}));
 row = line(ctx);
 assert.equal(row.buttons[0].gate, '还缺规划需要的信息，原因在技术细节里');
 assert.ok(row.detail.includes('direction-question-missing'));
 ({ctx} = load({view:{planning_configured:false, dispatch_action:'unavailable'}}));
 assert.equal(line(ctx).buttons[0].gate, '这次启动没有提供规划配置，不能生成计划');
 ({ctx} = load());
 ctx.rt.pending = {ref:'project-p'};
 assert.equal(line(ctx).buttons[0].gate, '上次提交的结果还没确认，先核对');
});

test('the 8.13 states map from the saved view', () => {
 const states = [
  [{job:{status:'intent-recorded', request_sha256:'c'.repeat(64)}}, '等你授权'],
  [{job:{status:'dispatching'}}, '处理中'],
  [{submission_in_progress:true}, '处理中'],
  [{job:{status:'execution-unknown'}}, '结果未知'],
  [{job:{status:'completed', outcome:'failed'}}, '规划失败'],
  [{submission_error:{code:'stage3-planning-deadline-or-io-failed'}}, '结果未知'],
  [{submission_error:{code:'stage3-planning-input-rejected'}}, '被拦下']
 ];
 for (const [view, tag] of states) assert.equal(line(load({view}).ctx).tag, tag, JSON.stringify(view));
 assert.equal(line(load({view:{plan:{kind:'plan'}}}).ctx), null, 'a saved plan has no request row');
 const unknown = line(load({view:{job:{status:'execution-unknown'}, recovery_pin_available:true}}).ctx);
 assert.equal(unknown.buttons.map(b => b.act).join(), 'inspect,recover,read');
 assert.equal(line(load({view:{job:{status:'execution-unknown'}}}).ctx).buttons.map(b => b.act).join(), 'inspect,read', 'recover only with a trusted pin');
 const grant = line(load({view:{job:{status:'intent-recorded', request_sha256:'c'.repeat(64)}}}).ctx);
 assert.equal(grant.grant.gate, '请先勾选确认');
 assert.equal(line(load({calls:0, view:{job:{status:'intent-recorded', request_sha256:'c'.repeat(64)}}}).ctx).grant.gate, '请先勾选确认', 'zero run limits do not lock the grant');
});

test('prepare sends the service request as given (fixed key), run adds request_sha256 and confirmed, then re-reads', async () => {
 const {ctx, posts, reads} = load();
 await ctx.wikiS3PlanAction(ctx.apps[0], 'prepare');
 assert.equal(posts.length, 1);
 assert.equal(posts[0].p, '/api/projects/project-p/stage3/planning/prepare');
 assert.equal(JSON.stringify(posts[0].body), JSON.stringify(request));
 assert.equal(reads.length, 1);
 ctx.v93.view.job = {status:'intent-recorded', request_sha256:'c'.repeat(64), key:request.key};
 vm.runInContext(`wikiS3Req.check = '${'c'.repeat(64)}'`, ctx);
 await ctx.wikiS3PlanAction(ctx.apps[0], 'run');
 assert.equal(posts[1].p, '/api/projects/project-p/stage3/planning/run');
 assert.equal(JSON.stringify(posts[1].body), JSON.stringify({...request, request_sha256:'c'.repeat(64), confirmed:true}));
 assert.equal(reads.length, 2);
});

test('a refused run is reported as blocked, a failure as an error; neither is retried', async () => {
 const {ctx, posts} = load({view:{job:{status:'intent-recorded', request_sha256:'c'.repeat(64)}}});
 ctx.answer = () => { throw Object.assign(Error('stage3-planning-project-busy'), {status:409}); };
 line(ctx); vm.runInContext(`wikiS3Req.check = '${'c'.repeat(64)}'`, ctx);
 await ctx.wikiS3PlanAction(ctx.apps[0], 'run');
 assert.equal(posts.length, 1, 'no automatic retry');
 let row = line(ctx);
 assert.equal(row.tag, '被拦下');
 assert.match(row.text, /不会自动重发/);
});

test('review P1-2: a run with no answer (network, 5xx) is an unknown outcome: tick cleared, only the read-only check, no resend', async () => {
 for (const failure of [Error('Failed to fetch'), Object.assign(Error('HTTP 502'), {status:502})]) {
  const sha = 'c'.repeat(64);
  const {ctx, posts} = load({view:{job:{status:'intent-recorded', request_sha256:sha, key:request.key}}});
  line(ctx);
  vm.runInContext(`wikiS3Req.check = '${sha}'`, ctx);
  ctx.answer = () => { throw failure; };
  await ctx.wikiS3PlanAction(ctx.apps[0], 'run');
  // The re-read still says intent-recorded (the service may not have written yet).
  let row = line(ctx);
  assert.equal(row.tag, '结果未知', failure.message);
  assert.equal(row.grant, undefined, 'no grant card, so no one-click resend');
  assert.equal(row.buttons.map(b => b.act).join(), 'inspect,read');
  assert.equal(vm.runInContext('wikiS3Req.check', ctx), null, 'the tick is cleared');
  assert.doesNotMatch(ctx.wikiS3RequestMarkup(ctx.v93.view), /data-s3-plan="run"/, 'no run button on the page');
  // The read-only check answers intent-recorded: the grant card comes back, unticked.
  ctx.answer = (p, body) => ({kind:'ProjectStage3PlanningJob', project_ref:'project-p', key:body.key, request_sha256:sha, status:'intent-recorded'});
  await ctx.wikiS3PlanAction(ctx.apps[0], 'inspect');
  assert.equal(posts[1].p, '/api/projects/project-p/stage3/planning/inspect');
  row = line(ctx);
  assert.equal(row.tag, '等你授权');
  assert.equal(row.grant.gate, '请先勾选确认');
 }
});

test('inspect is read-only and its answer is shown; a receipt for another key is refused', async () => {
 let {ctx, posts} = load({view:{job:{status:'execution-unknown', request_sha256:'c'.repeat(64)}}});
 ctx.answer = (p, body) => ({kind:'ProjectStage3PlanningJob', project_ref:'project-p', key:body.key, request_sha256:body.request_sha256, status:'completed', outcome:'failed'});
 await ctx.wikiS3PlanAction(ctx.apps[0], 'inspect');
 assert.equal(posts[0].p, '/api/projects/project-p/stage3/planning/inspect');
 assert.equal(posts[0].body.confirmed, undefined);
 assert.equal(line(ctx).tag, '规划失败');
 ({ctx} = load({view:{job:{status:'execution-unknown', request_sha256:'c'.repeat(64)}}}));
 ctx.answer = (p, body) => ({kind:'ProjectStage3PlanningJob', project_ref:'project-p', key:'other', status:'completed'});
 await ctx.wikiS3PlanAction(ctx.apps[0], 'inspect');
 const row = line(ctx);
 assert.equal(row.tag, '结果未知', 'a refused receipt does not settle the unknown job');
 assert.ok(row.detail.includes('stage3-planning-receipt-differs'), 'the reason is in the technical details');
});

test('review P1-1: a submission error next to an unknown or finished job keeps the job state and the read-only check', () => {
 const err = {code:'stage3-planning-deadline-or-io-failed'}, sha = 'c'.repeat(64);
 let row = line(load({view:{submission_error:err, job:{status:'execution-unknown', request_sha256:sha}}}).ctx);
 assert.equal(row.tag, '结果未知');
 assert.ok(row.buttons.some(b => b.act === 'inspect'), 'the read-only check stays');
 assert.doesNotMatch(row.text, /没有完成/);
 row = line(load({view:{submission_error:err, job:{status:'completed', outcome:'failed', request_sha256:sha}}}).ctx);
 assert.equal(row.tag, '规划失败');
 row = line(load({view:{submission_error:err, job:{status:'intent-recorded', request_sha256:sha}}}).ctx);
 assert.equal(row.tag, '结果未知', 'a timeout is never written as blocked');
 assert.ok(row.buttons.some(b => b.act === 'inspect'));
 assert.equal(row.grant, undefined, 'no grant card, so no resend');
 row = line(load({view:{submission_error:{code:'stage3-planning-input-rejected'}}}).ctx);
 assert.equal(row.tag, '被拦下', 'other submission errors are still blocked');
});

test('review P2-2: the tick belongs to one prepared request; a new prepare voids it', () => {
 const {ctx} = load({view:{job:{status:'intent-recorded', request_sha256:'c'.repeat(64), key:request.key}}});
 line(ctx); // first read binds the state to this topic
 vm.runInContext(`wikiS3Req.check = '${'c'.repeat(64)}'`, ctx);
 assert.equal(line(ctx).grant.gate, '');
 assert.match(ctx.wikiS3RequestMarkup(ctx.v93.view), /data-s3-plan-check checked/);
 ctx.v93.view.job = {status:'intent-recorded', request_sha256:'d'.repeat(64), key:request.key};
 assert.equal(line(ctx).grant.gate, '请先勾选确认');
 assert.doesNotMatch(ctx.wikiS3RequestMarkup(ctx.v93.view), /data-s3-plan-check checked/);
});

test('review P2-1: the action checks the gate again before sending', async () => {
 const sha = 'c'.repeat(64);
 let {ctx, posts} = load({view:{job:{status:'intent-recorded', request_sha256:sha, key:request.key}}});
 await ctx.wikiS3PlanAction(ctx.apps[0], 'run');
 assert.equal(posts.length, 0, 'not ticked: nothing sent');
 line(ctx); vm.runInContext(`wikiS3Req.check = '${sha}'`, ctx);
 ctx.rt.pending = {ref:'project-p'};
 await ctx.wikiS3PlanAction(ctx.apps[0], 'run');
 assert.equal(posts.length, 0, 'a lock that appeared after drawing still stops it');
 ({ctx, posts} = load({view:{planning_configured:false, dispatch_action:'unavailable'}}));
 await ctx.wikiS3PlanAction(ctx.apps[0], 'prepare');
 assert.equal(posts.length, 0, 'prepare is not sent without planning configuration');
 ({ctx, posts} = load({view:{job:{status:'intent-recorded', request_sha256:sha, key:request.key}}}));
 await ctx.wikiS3PlanAction(ctx.apps[0], 'inspect');
 assert.equal(posts.length, 0, 'inspect is only sent where it is offered');
});

test('review P2-3: a request in flight stays busy when the user leaves the topic and comes back', async () => {
 const sha = 'c'.repeat(64);
 const {ctx, posts} = load({view:{job:{status:'intent-recorded', request_sha256:sha, key:request.key}}});
 line(ctx); vm.runInContext(`wikiS3Req.check = '${sha}'`, ctx);
 let release;
 ctx.answer = () => new Promise(resolve => { release = () => resolve({kind:'ProjectStage3PlanningSubmission', job:{project_ref:'project-p', key:request.key, status:'dispatching'}}); });
 const first = ctx.wikiS3PlanAction(ctx.apps[0], 'run');
 ctx.rt.ref = 'project-b'; line(ctx); // away
 ctx.rt.ref = 'project-p'; line(ctx); // back
 assert.equal(line(ctx).grant.gate, '正在保存，请稍等');
 await ctx.wikiS3PlanAction(ctx.apps[0], 'run');
 assert.equal(posts.length, 1, 'no second POST while the first is in flight');
 release(); await first;
 assert.equal(vm.runInContext('wikiS3Req.busy.size', ctx), 0);
});

test('review P2-10: an unknown run outcome is kept per topic; another topic unknown does not replace it', async () => {
 const sha = 'c'.repeat(64);
 const {ctx} = load({view:{job:{status:'intent-recorded', request_sha256:sha, key:request.key}}});
 ctx.answer = () => { throw Error('Failed to fetch'); };
 const runOn = async topic => {
  ctx.rt.ref = topic; ctx.v93.basis = {...basis, project_ref:topic}; line(ctx);
  vm.runInContext(`wikiS3Req.check = '${sha}'`, ctx);
  await ctx.wikiS3PlanAction(ctx.apps[0], 'run');
 };
 await runOn('project-p');
 assert.equal(line(ctx).tag, '结果未知');
 await runOn('project-b');
 assert.equal(line(ctx).tag, '结果未知');
 ctx.rt.ref = 'project-p'; ctx.v93.basis = {...basis};
 const row = line(ctx);
 assert.equal(row.tag, '结果未知', 'back on the first topic its unknown outcome is still there');
 assert.equal(row.grant, undefined);
});
