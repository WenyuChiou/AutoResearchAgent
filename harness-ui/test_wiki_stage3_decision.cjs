// Stage 3 「你的决定」 (DESIGN 3.4 item 5, 8.18). Runs the shipped module against stubbed reads and an in-memory
// decide endpoint. No network, no model.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');

const H = c => c.repeat(64);
const basis = {project_ref:'project-d', input_version:1, revision:4, brief_sha256:H('a')};
const binding = {project_ref:'project-d', revision:4, input_version:1, brief_sha256:H('a'), parent_plan_manifest_sha256:H('b'),
 parent_plan_sha256:H('c'), plan_request_sha256:H('d'), plan_revision_receipt_sha256:null};
const fields = ['method', 'materials', 'design', 'analysis', 'interpretation', 'validation', 'minimum_deliverable'];
const fullPlan = {kind:'Stage3DirectionPlanningResult', planning_status:'draft', question_plans:[Object.fromEntries(fields.map(f => [f, 'x']))]};
const record = (sequence, decision, key, extra = {}) => ({receipt_sha256:H(String(sequence)), record:{kind:'decision', sequence, decision, text:'', request:{key}, binding, ...extra}});
const hdOf = (extra = {}) => ({kind:'ProjectStage3PlanDecisionView', schema_version:1, binding, has_manual_revision:false, revision_ambiguous:false, records:[], latest:null, history:[], ...extra});

function load({view = {}, connected = true} = {}) {
 const listeners = {}, posts = [];
 const ctx = vm.createContext({
  console, JSON, Object, Number, String, Array, Error, Map, Set, Math, Date, Promise, TextEncoder,
  crypto:{randomUUID:() => 'k-' + (++ctx.uuids)}, uuids:0,
  rt:{ref:'project-d', epoch:1, loading:false, busy:false, pending:null, controlHeld:false},
  v93:{busy:false, basis, view:{...basis, plan:fullPlan, job:{outcome:'saved', planning_status:'draft'}, feedback:{records:[]}, host_decision:hdOf(), ...view}},
  apps:[{el:{contains:() => true, querySelector:() => null}}],
  v93Identity:() => basis, v93Matches:(a, b) => !!a && !!b && a.project_ref === b.project_ref,
  v9ConnectionConnected:() => connected,
  wikiS3Escape:value => String(value).replaceAll('<', '&lt;'), projectPath:(ref, tail) => `/api/projects/${ref}/${tail}`, livePaint:() => {},
  reads:0, nextView:null,
  v93ReadSaved:async () => { ctx.reads++; if (ctx.nextView) ctx.v93.view = ctx.nextView; },
  liveRequest:async (p, body) => { posts.push({p, body:JSON.parse(JSON.stringify(body))}); return ctx.answer(p, body); },
  answer:(p, body) => ({receipt_sha256:H('e'), replayed:false, record:{kind:'decision', sequence:1, decision:body.decision, text:body.text, request:body, binding}}),
  wikiS3Decision:noPlan => `<stub ${noPlan}>`,
  document:{addEventListener:(type, fn) => { listeners[type] = fn; }}
 });
 vm.runInContext(fs.readFileSync(path.join(__dirname, 'wiki-stage3-decision.js'), 'utf8'), ctx);
 const html = () => ctx.wikiS3Decision();
 const text = () => html().replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ');
 const click = act => listeners.click({target:{closest:() => ({disabled:false, dataset:{s3Dec:act}})}, preventDefault() {}});
 const pick = value => listeners.change({target:{matches:() => true, value}});
 const state = () => vm.runInContext('wikiS3Dec', ctx);
 const save = async () => { click('confirm'); await ctx.wikiS3DecSave(ctx.apps[0]); };
 return {ctx, posts, html, text, click, pick, state, save, listeners};
}

test('three options with no preselection; the no-plan stub keeps its reason', () => {
 const {ctx, html} = load();
 const out = html();
 for (const value of ['accept', 'revise-then-review', 'return-to-stage2']) assert.match(out, new RegExp(`value="${value}" data-s3-dec-pick  >`));
 assert.doesNotMatch(out, /checked/);
 assert.match(out, /data-s3-dec="confirm" disabled>请先选一个/);
 assert.match(out, /接受也不会启动实验/);
 assert.match(out, /本机页面记录，未核验身份，不授权执行/);
 assert.equal(ctx.wikiS3Decision('现在还不能做这一步：还没有计划。'), '<stub 现在还不能做这一步：还没有计划。>');
});

test('gray with a reason: not connected, no plan, no decision record, busy, unknown, plan just revised', () => {
 assert.match(load({connected:false}).text(), /Stage 3 还没有接通/);
 assert.match(load({view:{plan:null}}).text(), /还没有计划/);
 assert.match(load({view:{host_decision:undefined}}).text(), /后台没有提供决定记录/);
 let t = load();
 t.state().busy.set('project-d', 'k');
 assert.match(t.html(), /data-s3-dec="confirm" disabled/);
 assert.match(t.text(), /正在保存/);
 t = load();
 t.ctx.v94fContext = () => ({});
 t.ctx.v94fState = () => ({records:[{receipt_sha256:H('9'), record:{kind:'revision', revision_number:2}}]});
 assert.match(t.text(), /计划刚被修订过，页面先要重新读取这一版才能决定/);
 assert.match(t.html(), /data-v93-read/);
});

test('accept is grayed with its reason unless the planning status allows it; the other two stay open', () => {
 const cases = [
  [{job:{outcome:'saved'}}, /保存的计划缺少规划状态/],
  [{job:{outcome:'saved', planning_status:'needs-information'}}, /设计评审认为这份计划还缺信息/],
  [{job:{outcome:'saved', planning_status:'failed'}}, /设计评审认为这份计划还缺信息/],
  [{plan:{...fullPlan, planning_status:undefined}}, /计划自己没有写规划状态/],
  [{plan:{...fullPlan, question_plans:[{method:'x'}]}}, /计划还有未填完的内容/]
 ];
 for (const [view, why] of cases) {
  const {html} = load({view});
  assert.match(html(), /value="accept" data-s3-dec-pick  disabled>/, JSON.stringify(view));
  assert.match(html(), why);
  assert.match(html(), /value="revise-then-review" data-s3-dec-pick  >/);
 }
 assert.doesNotMatch(load({view:{job:{outcome:'saved', planning_status:'ready-for-plan-review'}}}).html(), /value="accept" data-s3-dec-pick  disabled/);
});

test('the reason is counted in UTF-8 bytes; over 4096 bytes keeps the text and grays the button', () => {
 const t = load();
 t.pick('return-to-stage2');
 t.state().text = '字'.repeat(1366); // 4098 bytes, 1366 characters
 assert.match(t.html(), /超过 4096 字节，原文保留（现在 4098 字节）/);
 assert.match(t.html(), /data-s3-dec="confirm" disabled>确认：退回 Stage 2 重选…/);
 t.state().text = '字'.repeat(1365);
 assert.match(t.html(), /可选，最多 4096 字节（现在 4095 字节）/);
 assert.match(t.html(), /data-s3-dec="confirm" >确认：退回 Stage 2 重选…/);
});

test('confirm then save sends the binding, a new key, the choice, the text and confirmed; the follow-up is shown', async () => {
 for (const [decision, follow] of [['accept', /你接受了这版计划/], ['revise-then-review', /已保存你的意图。接下来可以用上面的「评语与修订」改计划。现在还不能针对修改后的计划再生成一次：后台生成计划时只读选方向时的材料，不读你修改过的版本。这个功能需要后台新增。/], ['return-to-stage2', /Stage 2 的选择一经保存不能更改；要换方向，目前需要新建课题。/]]) {
  const t = load();
  t.pick(decision);
  t.state().text = '因为';
  t.click('confirm');
  assert.match(t.html(), /data-s3-dec-confirm/);
  assert.match(t.text(), /将保存的决定： ?/);
  await t.ctx.wikiS3DecSave(t.ctx.apps[0]);
  assert.equal(t.posts.length, 1);
  assert.equal(t.posts[0].p, '/api/projects/project-d/stage3/planning/decide');
  const {project_ref, ...expected} = binding;
  assert.equal(JSON.stringify(t.posts[0].body), JSON.stringify({...expected, key:'k-1', decision, text:'因为', confirmed:true}));
  assert.equal(t.ctx.reads, 1, 'a read-only re-read follows');
  const saved = record(1, decision, 'k-1');
  t.ctx.v93.view.host_decision = hdOf({records:[saved], latest:saved});
  t.state().saved = saved.receipt_sha256;
  assert.match(t.text(), follow);
  assert.match(t.text(), /已保存/);
  assert.match(t.text(), /第 1 次/);
  assert.match(t.text(), /时间：这条记录保存时还没有记录时间/, 'a record without recorded_at says so');
  if (decision === 'revise-then-review') {
   assert.match(t.html(), /data-s3-dec="feedback">去「评语与修订」/);
   assert.doesNotMatch(t.text(), /再点「请求生成计划」/, 'review P1-2: never sends the user to the grayed button');
   assert.ok(t.html().includes('disabled>请求生成计划</button><small class="wiki-s2-reason">现在还不能针对修改后的计划再生成一次：后台生成计划时只读选方向时的材料，不读你修改过的版本。这个功能需要后台新增。</small>'));
  }
 }
});

test('double click sends one request; each new save uses a new key', async () => {
 const t = load();
 let release;
 t.ctx.answer = (p, body) => new Promise(resolve => { release = () => resolve({receipt_sha256:H('e'), record:{decision:body.decision, request:body}}); });
 t.pick('revise-then-review');
 t.click('confirm');
 const first = t.ctx.wikiS3DecSave(t.ctx.apps[0]);
 const second = t.ctx.wikiS3DecSave(t.ctx.apps[0]);
 release(); await Promise.all([first, second]);
 assert.equal(t.posts.length, 1);
 t.ctx.answer = (p, body) => ({receipt_sha256:H('f'), record:{decision:body.decision, request:body}});
 t.pick('revise-then-review');
 await t.save();
 assert.equal(t.posts.length, 2);
 assert.notEqual(t.posts[0].body.key, t.posts[1].body.key);
});

test('every refusal code shows the interface wording, the raw code in technical details, and nothing is resent', async () => {
 const codes = {
  'stage3-decision-version-differs':'这版计划已经变了，请刷新后再决定。',
  'stage3-decision-plan-not-ready':'计划还有未填完的内容，或设计评审认为还缺信息，不能接受',
  'stage3-decision-planning-status-missing':'保存的计划缺少规划状态，不能接受',
  'stage3-decision-revision-ambiguous':'这份计划有两份并列的修订稿，请先在其中一份基础上继续修订，再做决定。',
  'stage3-planning-unconnected':'Stage 3 规划还没有接通',
  'stage3-decision-saved-plan-required':'还没有保存的计划',
  'stage3-decision-key-payload-differs':'同一个操作编号的内容不同',
  'stage3-planning-project-busy':'另一次 Stage 3 保存正在进行',
  'stage3-decision-record-bound':'已满 32 条',
  'stage3-decision-record-differs':'决定记录的校验不一致',
  'stage3-decision-text-too-long':'理由超过 4096 字节',
  'stage3-decision-response-bound':'回读会超过上限',
  'stage3-planning-body-bound-exceeded':'请求太大',
  'explicit-stage3-decision-required':'需要你明确确认',
  'credential-rejected':'凭据不对',
  'cross-site-rejected':'请求来源不对'
 };
 for (const [code, words] of Object.entries(codes)) {
  const t = load();
  const status = code === 'stage3-decision-text-too-long' || code.endsWith('bound-exceeded') || code === 'stage3-decision-response-bound' ? 413 : /credential/.test(code) ? 401 : /cross-site|explicit/.test(code) ? 403 : 409;
  t.ctx.answer = () => { throw Object.assign(Error(code), {status}); };
  t.pick('return-to-stage2');
  await t.save();
  assert.equal(t.posts.length, 1, code);
  const out = t.text();
  assert.ok(out.includes(words), code + ' → ' + out);
  assert.match(out, /被拦下/);
  assert.ok(t.html().includes(`<code>${code}</code>`), 'raw code in technical details');
  assert.doesNotMatch(out.replace(/技术细节.*$/, ''), new RegExp(code));
  assert.equal(vm.runInContext('wikiS3Dec.unknown', t.ctx), null, 'a refusal is not an unknown outcome');
 }
});

test('unknown outcome: no resend; the re-read finds the record by key, or says nothing was saved', async () => {
 let t = load();
 t.ctx.answer = () => { throw Error('Failed to fetch'); };
 const saved = record(1, 'accept', 'k-1');
 t.ctx.nextView = {...t.ctx.v93.view, host_decision:hdOf({records:[saved], latest:saved})};
 t.pick('accept');
 await t.save();
 assert.equal(t.posts.length, 1);
 assert.equal(t.ctx.reads, 1);
 assert.equal(vm.runInContext('wikiS3Dec.unknown', t.ctx), null, 'found by key: settled');
 assert.match(t.text(), /你接受了这版计划/);

 t = load();
 t.ctx.answer = () => { throw Object.assign(Error('HTTP 502'), {status:502}); };
 t.pick('accept');
 await t.save();
 assert.match(t.text(), /结果未知/);
 assert.match(t.text(), /核对时没有找到这次的记录，说明没有保存。原请求不会重发/);
 assert.match(t.html(), /data-s3-dec="confirm" disabled/, 'no save while unknown');
 assert.doesNotMatch(t.text(), /先只读核对/, 'after the check the gate does not ask for another check');
 assert.match(t.text(), /点上面的「知道了」后可以重新决定/);
 await t.ctx.wikiS3DecSave(t.ctx.apps[0]);
 assert.equal(t.posts.length, 1, 'never resent');
 await t.ctx.wikiS3DecCheck(t.ctx.apps[0]); // 「知道了」
 assert.doesNotMatch(t.text(), /结果未知/);

 t = load();
 t.ctx.answer = () => { throw Error('Failed to fetch'); };
 t.ctx.v93ReadSaved = async () => { t.ctx.reads++; t.ctx.v93.view = null; }; // the re-read itself failed
 t.pick('accept');
 await t.save();
 assert.equal(vm.runInContext('wikiS3Dec.unknown.absent', t.ctx), undefined, 'not concluded without a read');
});

test('after a manual revision old decisions say 针对旧版本 and a new decision can be made on the revision', async () => {
 const old = {...record(1, 'accept', 'k-old'), superseded_by_manual_revision:true};
 const revised = {...binding, plan_revision_receipt_sha256:H('9')};
 const t = load({view:{host_decision:hdOf({binding:revised, has_manual_revision:true, history:[old]})}});
 assert.match(t.text(), /之前的决定针对修订前的计划，已移到历史；请对当前这版重新决定。/);
 assert.match(t.text(), /针对旧版本/);
 assert.match(t.text(), /这一版计划还没有决定/);
 t.pick('revise-then-review');
 await t.save();
 assert.equal(t.posts[0].body.plan_revision_receipt_sha256, H('9'));
});

test('two tied revisions: not "no decision"; all three options grayed with the way out', () => {
 let t = load({view:{host_decision:hdOf({has_manual_revision:true, revision_ambiguous:true, history:[record(1, 'accept', 'k')]})}});
 assert.match(t.text(), /这份计划有两份并列的修订稿，请先在其中一份基础上继续修订，再做决定。/);
 assert.doesNotMatch(t.text(), /这一版计划还没有决定/);
 assert.equal((t.html().match(/data-s3-dec-pick  disabled/g) || []).length, 3);
 t = load({view:{feedback:{records:Array(32).fill({})}, host_decision:hdOf({revision_ambiguous:true})}});
 assert.match(t.text(), /修订记录已满，请重新生成计划/);
});

test('a broken decision journal and a size marker are shown as such, never as "no decision"', () => {
 let t = load({view:{host_decision:{error:'stage3-decision-record-differs'}}});
 assert.match(t.text(), /决定记录这次读不出来/);
 assert.match(t.html(), /<code>stage3-decision-record-differs<\/code>/);
 assert.doesNotMatch(t.text(), /还没有决定/);
 assert.match(t.html(), /data-s3-dec="confirm" disabled/);
 t = load({view:{host_decision:{omitted:'response-bound', count:3, latest_decision:'return-to-stage2', latest_sequence:3}}});
 assert.match(t.text(), /已经保存了 3 条决定，最新一条（第 3 次）是「退回 Stage 2 重选」/);
 assert.doesNotMatch(t.text(), /还没有决定/);
 t = load({view:{host_decision:{omitted:'response-bound', count:0, latest_decision:null, latest_sequence:null}}});
 assert.match(t.text(), /后台说还没有决定/);
});

test('the Stage 3 status line follows the latest saved decision', () => {
 const saved = record(2, 'return-to-stage2', 'k');
 const t = load({view:{host_decision:hdOf({records:[saved], latest:saved})}});
 const status = t.ctx.wikiS3DecStatus();
 assert.equal(status.tone, 'done');
 assert.match(status.now[1], /你的决定已保存：退回 Stage 2 重选（本机页面记录，未核验身份，不授权执行）/);
 assert.equal(load().ctx.wikiS3DecStatus(), null);
});

test('recorded_at is shown in local time with the UTC original on hover; null says no time was recorded', () => {
 const at = '2026-11-27T06:05:09.123456+00:00';
 const timed = record(1, 'accept', 'k1', {recorded_at:at}), old = record(2, 'return-to-stage2', 'k2', {recorded_at:null});
 const t = load({view:{host_decision:hdOf({records:[timed, old], latest:old})}});
 const local = new Date(at).toLocaleString('zh-CN', {year:'numeric', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', second:'2-digit', hour12:false});
 assert.ok(t.html().includes(`<time datetime="${at}" title="UTC ${at}" data-s3-dec-time>${local}</time>`), 'local time, UTC original as the title');
 assert.match(t.text(), /这条记录保存时还没有记录时间/);
 assert.doesNotMatch(t.text(), /后台记录里没有保存时间/);
 const bad = load({view:{host_decision:hdOf({records:[record(1, 'accept', 'k', {recorded_at:'not-a-time<'})], latest:null})}});
 assert.match(bad.html(), /title="not-a-time&lt;">not-a-time&lt;/, 'an unreadable value is shown as is, escaped');
});

test('review P1-1: after an unknown save, a size marker or a damaged journal in the re-read is not read as "not saved"', async () => {
 const prior = record(1, 'accept', 'k-old');
 const start = {host_decision:hdOf({records:[prior], latest:prior})};
 const run = async (after, pick = 'return-to-stage2') => {
  const t = load({view:start});
  t.ctx.answer = () => { throw Object.assign(Error('HTTP 502'), {status:502}); };
  t.ctx.nextView = {...t.ctx.v93.view, host_decision:after};
  t.pick(pick);
  await t.save();
  return t;
 };
 // Damaged journal: still unknown, says the records cannot be read, no "not saved", the form stays closed.
 let t = await run({error:'stage3-decision-record-differs'});
 assert.match(t.text(), /结果未知/);
 assert.match(t.text(), /读不出决定记录.*还不能确认有没有保存/);
 assert.doesNotMatch(t.text(), /说明没有保存/);
 assert.match(t.html(), /data-s3-dec="check" >只读核对/);
 // Size marker with one more record whose latest is this choice: written.
 t = await run({omitted:'response-bound', count:2, latest_decision:'return-to-stage2', latest_sequence:2});
 assert.equal(vm.runInContext('wikiS3Dec.unknown', t.ctx), null);
 assert.match(t.text(), /按读取摘要判断已经写入：第 2 次「退回 Stage 2 重选」/);
 assert.doesNotMatch(t.text(), /说明没有保存/);
 // Size marker unchanged: nothing was written.
 t = await run({omitted:'response-bound', count:1, latest_decision:'accept', latest_sequence:1});
 assert.match(t.text(), /说明没有保存/);
 // Size marker with a new write that is not this choice: cannot tell.
 t = await run({omitted:'response-bound', count:2, latest_decision:'accept', latest_sequence:2});
 assert.match(t.text(), /对不上这次的选择，还不能确认有没有保存/);
 assert.doesNotMatch(t.text(), /说明没有保存/);
});

test('review P2-1: a confirmation is bound to the shown plan version; a new version voids it', async () => {
 const t = load();
 t.pick('return-to-stage2');
 t.click('confirm');
 assert.match(t.html(), /data-s3-dec-confirm/);
 // A re-read brings a revised plan (another tab saved a revision) while the panel is open.
 t.ctx.v93.view = {...t.ctx.v93.view, host_decision:hdOf({binding:{...binding, plan_revision_receipt_sha256:H('9')}, has_manual_revision:true})};
 await t.ctx.wikiS3DecSave(t.ctx.apps[0]);
 assert.equal(t.posts.length, 0, 'nothing is saved against a version the user did not confirm');
 assert.doesNotMatch(t.html(), /data-s3-dec-confirm/);
 assert.match(t.text(), /计划已经变了，之前的确认作废/);
 t.click('confirm');
 await t.ctx.wikiS3DecSave(t.ctx.apps[0]);
 assert.equal(t.posts.length, 1);
 assert.equal(t.posts[0].body.plan_revision_receipt_sha256, H('9'));
});

test('review P2-2: a reason code that names an Object prototype member gets the generic wording', async () => {
 for (const code of ['constructor', 'toString', '__proto__', 'hasOwnProperty']) {
  const t = load();
  t.ctx.answer = () => { throw Object.assign(Error(code), {status:409}); };
  t.pick('return-to-stage2');
  await t.save();
  assert.match(t.text(), /服务拒绝了这次保存，原因代码在技术细节里。没有留下任何记录。/, code);
  assert.doesNotMatch(t.text(), /native code|function/, code);
 }
});

test('review P2-3: 「接受」 is judged on the shown revision, not the parent plan', () => {
 const incomplete = {...fullPlan, question_plans:[{method:'x'}]};
 const revised = {...binding, plan_revision_receipt_sha256:H('9')};
 // After a reload the page does not hold the revision: no client verdict from the (incomplete) parent plan.
 let t = load({view:{plan:incomplete, host_decision:hdOf({binding:revised, has_manual_revision:true})}});
 assert.doesNotMatch(t.html(), /value="accept" data-s3-dec-pick  disabled/);
 assert.doesNotMatch(t.html(), /计划还有未填完的内容/);
 // The page holds that revision: its plan is judged (complete here), not the parent's.
 t = load({view:{plan:incomplete, host_decision:hdOf({binding:revised, has_manual_revision:true})}});
 t.ctx.v94fContext = () => ({});
 t.ctx.v94fState = () => ({records:[{receipt_sha256:H('9'), record:{kind:'revision', revision_number:2, plan:fullPlan}}]});
 assert.doesNotMatch(t.html(), /value="accept" data-s3-dec-pick  disabled/);
 t.ctx.v94fState = () => ({records:[{receipt_sha256:H('9'), record:{kind:'revision', revision_number:2, plan:incomplete}}]});
 assert.match(t.html(), /value="accept" data-s3-dec-pick  disabled/, 'an incomplete shown revision is still grayed');
});
