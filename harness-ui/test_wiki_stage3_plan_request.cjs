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
  console, JSON, Object, Number, String, Array, Error,
  rt:{ref:'project-p', epoch:1, loading:false, busy:false, pending:null, controlHeld:false, meta:{run_limits:{model_calls:calls}}},
  v93:{busy:false, basis, view:{...basis, plan:null, planning_configured:true, dispatch_action:'prepare-then-confirm-run', default_request:request, job:null, ...view}},
  apps:[{el:{contains:() => true}}],
  v93Identity:() => basis, v93Matches:(a, b) => !!a && !!b && a.project_ref === b.project_ref,
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
 ({ctx} = load({calls:0}));
 assert.equal(line(ctx).buttons[0].gate, '这次启动的模型调用上限是 0，不能生成计划');
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
 assert.equal(line(load({calls:0, view:{job:{status:'intent-recorded', request_sha256:'c'.repeat(64)}}}).ctx).grant.gate, '这次启动的模型调用上限是 0，不能生成计划');
});

test('prepare sends the service request as given (fixed key), run adds request_sha256 and confirmed, then re-reads', async () => {
 const {ctx, posts, reads} = load();
 await ctx.wikiS3PlanAction(ctx.apps[0], 'prepare');
 assert.equal(posts.length, 1);
 assert.equal(posts[0].p, '/api/projects/project-p/stage3/planning/prepare');
 assert.equal(JSON.stringify(posts[0].body), JSON.stringify(request));
 assert.equal(reads.length, 1);
 ctx.v93.view.job = {status:'intent-recorded', request_sha256:'c'.repeat(64), key:request.key};
 await ctx.wikiS3PlanAction(ctx.apps[0], 'run');
 assert.equal(posts[1].p, '/api/projects/project-p/stage3/planning/run');
 assert.equal(JSON.stringify(posts[1].body), JSON.stringify({...request, request_sha256:'c'.repeat(64), confirmed:true}));
 assert.equal(reads.length, 2);
});

test('a refused run is reported as blocked, a failure as an error; neither is retried', async () => {
 const {ctx, posts} = load({view:{job:{status:'intent-recorded', request_sha256:'c'.repeat(64)}}});
 ctx.answer = () => { throw Object.assign(Error('stage3-planning-project-busy'), {status:409}); };
 await ctx.wikiS3PlanAction(ctx.apps[0], 'run');
 assert.equal(posts.length, 1, 'no automatic retry');
 let row = line(ctx);
 assert.equal(row.tag, '被拦下');
 assert.match(row.text, /不会自动重发/);
 ctx.answer = () => { throw Error('Failed to fetch'); };
 await ctx.wikiS3PlanAction(ctx.apps[0], 'run');
 assert.equal(line(ctx).tag, '出错');
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
