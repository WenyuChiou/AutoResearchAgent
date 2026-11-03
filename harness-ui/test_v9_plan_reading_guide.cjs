/* Synthetic saved-plan projections; no planner, server or research calls. */
'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm');
const fs=require('node:fs'),path=require('node:path'),{webcrypto}=require('node:crypto');
const clone=value=>JSON.parse(JSON.stringify(value));
const fields=['materials','method','design','validation','analysis','interpretation','minimum_deliverable'];
function fixture(){
 const pin='a'.repeat(64),manifest='b'.repeat(64),question={question_ref:'selected@1/q',unknowns:['Access remains unknown.']};
 for(const field of fields)question[field]=field+': a proposed source-bound step, not executed.';
 question.method='Initialize household state.\nUse the qualified LLM response.\nUpdate desired demand and current cash.\nCheck all candidates before commit.\nStop or advance the current period.';
 const view={project_ref:'project-a',input_version:1,revision:2,brief_sha256:pin,direction_intent_sha256:pin,
  direction_context:{questions:[{question_ref:question.question_ref,text:'Selected household decision question'}]},
  job:{plan_manifest_sha256:manifest,request_sha256:'c'.repeat(64)},
  plan:{kind:'Stage3DirectionPlanningResult',question_plans:[question],execution_authorized:false}};
 const ctx=vm.createContext({TextDecoder,Uint8Array,crypto:webcrypto,window:{RESEARCH_PROJECTS:{credential:'synthetic-only'}}});
 for(const name of ['v9-research-guide-contract.js','v9-research-guide-view.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,name),'utf8'),ctx);
 ctx.rl=(zh,en)=>en;ctx.rx=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 return {ctx,view,question};
}
test('a saved selected plan yields bounded exact excerpts without an authored file or scientific edges',()=>{
 const {ctx,view,question}=fixture(),before=JSON.stringify(view),guide=ctx.v94PlanReadingGuide(view);
 assert.equal(guide.question_ref,question.question_ref);assert.equal(guide.flow.nodes.length,7);
 assert.equal(guide.flow.edges.length,0);assert.equal(guide.loop.edges.length,0);
 for(const node of [...guide.flow.nodes,...guide.loop.nodes])for(const source of node.sources){
  const field=source.pointer.split('/').at(-1);assert.ok(question[field].includes(source.quote));
  assert.ok(source.quote.length<=2200);assert.ok(node.detail.length<=420);
 }
 const html=ctx.v94GuideHtml(guide,{reading:true});
 for(const text of ['qualified LLM response','Initialize household state','Stop or advance'])assert.ok(html.includes(text));
 assert.match(html,/Source order does not establish causal or feedback relationships/);
 assert.doesNotMatch(html,/Proposed feedback loop|Authored planning guide|data-n94-edge /);
 assert.equal(JSON.stringify(view),before);assert.equal(view.plan.execution_authorized,false);
});
test('the same product path projects a different topic without a household or LLM template',()=>{
 const {ctx,view,question}=fixture();question.method='Initialize river gauges.\nRoute a measured hydrograph.\nCompare held-out discharge.\nStop at the fixed horizon.';
 const html=ctx.v94GuideHtml(ctx.v94PlanReadingGuide(view),{reading:true});
 assert.match(html,/river gauges/);assert.match(html,/held-out discharge/);assert.doesNotMatch(html,/LLM|household/);
});
test('three interface locales translate reading labels and keep the saved research text',()=>{
 const {ctx,view}=fixture(),guide=ctx.v94PlanReadingGuide(view);
 for(const [locale,label] of [[0,'设计'],[1,'Design'],[2,'設計']]){
  ctx.rl=(...values)=>values[locale];const html=ctx.v94GuideHtml(guide,{reading:true});
  assert.ok(html.includes(label));assert.ok(html.includes('qualified LLM response'));
 }
});
test('wrong topic references and stale revision bindings cannot generate a guide',()=>{
 const {ctx,view}=fixture();assert.throws(()=>ctx.v94PlanReadingGuide(view,null,'other@1/q'),/reading-question/);
 view.direction_context.questions[0].question_ref='other@1/q';
 assert.throws(()=>ctx.v94PlanReadingGuide(view),/reading-question/);
 const bad=fixture();bad.view.input_version='1';assert.throws(()=>bad.ctx.v94PlanReadingGuide(bad.view),/reading-binding/);
});
test('manual projection is bound to its actual receipt and current complete draft text',()=>{
 const {ctx,view}=fixture(),binding={project_ref:view.project_ref,input_version:1,revision:2,brief_sha256:view.brief_sha256,
  parent_plan_manifest_sha256:view.job.plan_manifest_sha256,parent_plan_sha256:'d'.repeat(64),plan_request_sha256:view.job.request_sha256};
 view.feedback={binding};const revision={receipt_sha256:'e'.repeat(64),record:{kind:'revision',revision_number:8,binding,plan:clone(view.plan)}};
 revision.record.plan.question_plans[0].method='New current method.\nIts separate stop condition.';
 const guide=ctx.v94PlanReadingGuide(view,revision);assert.equal(guide.revision_number,8);assert.equal(guide.revision_receipt_sha256,revision.receipt_sha256);
 assert.match(JSON.stringify(guide),/New current method/);assert.doesNotMatch(JSON.stringify(guide),/qualified LLM response/);
 const changed=clone(revision);changed.receipt_sha256='f'.repeat(64);assert.throws(()=>ctx.v94ValidateGuide(guide,view,changed),/binding/);
 const stale=clone(revision);stale.record.binding.input_version=2;assert.throws(()=>ctx.v94PlanReadingGuide(view,stale),/reading-binding/);
});
test('long complete method and unknowns remain untouched while excerpts and all groups stay bounded',()=>{
 const {ctx,view,question}=fixture();question.method=Array.from({length:32},(_,i)=>'Step '+i+': '+('界😀'.repeat(900))).join('\n');
 const before=JSON.stringify(view),guide=ctx.v94PlanReadingGuide(view);
 assert.equal(guide.loop.nodes.length,8);assert.equal(JSON.stringify(view),before);
 for(const node of [...guide.flow.nodes,...guide.loop.nodes]){
  assert.ok(node.detail.length<=420);for(const source of node.sources){assert.ok(source.quote.length<=2200);assert.ok(question.method.includes(source.quote)||fields.some(f=>question[f].includes(source.quote)));}
 }
 assert.deepEqual(question.unknowns,['Access remains unknown.']);
});
test('missing method is explicit failure instead of a fabricated process',()=>{
 const {ctx,view,question}=fixture();delete question.method;assert.throws(()=>ctx.v94PlanReadingGuide(view),/reading-method/);
});
test('the actual loader projects an absent guide with one GET and leaves saved planning untouched',async()=>{
 const {ctx,view}=fixture(),calls=[],before=JSON.stringify(view),basis={project_ref:view.project_ref};
 Object.assign(ctx,{AbortController,setTimeout,clearTimeout,apps:[{page:'workspace',stage:3}],rt:{epoch:1},v93:{view,basis},
  v93Identity:()=>basis,v93Matches:(a,b)=>a===b,livePaint:()=>{},v93SavedPlanSummary:()=>'<p>Complete source text</p>',v7AfterRender:()=>{},
  document:{addEventListener:()=>{}},fetch:async(url,options)=>{calls.push({url,options});return new Response('{"materials":[]}');}});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'v9-research-guide.js'),'utf8'),ctx);
 await ctx.v94Load(view,basis,1);const state=vm.runInContext('({status:v94.status,source:v94.source,guide:v94.guide})',ctx);
 assert.equal(state.status,'ready');assert.equal(state.source,'plan-excerpts');assert.equal(calls.length,1);assert.equal(calls[0].url,'/api/v9/materials');
 assert.equal(calls[0].options.method,undefined);assert.equal(JSON.stringify(view),before);
 assert.match(ctx.v94GuideSection(view,null,'<p>Complete source text</p>'),/Complete source text/);
});
