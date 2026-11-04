/* Synthetic display contract and GET/recovery cases; zero research calls. */
'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const {webcrypto,createHash}=require('node:crypto');
const source=fs.readFileSync(path.join(__dirname,'v9-research-guide-contract.js'),'utf8');
const adapter=fs.readFileSync(path.join(__dirname,'v9-research-guide.js'),'utf8');
const feedback=fs.readFileSync(path.join(__dirname,'v9-stage3-feedback.js'),'utf8');
const renderer=fs.readFileSync(path.join(__dirname,'v9-research-guide-view.js'),'utf8');
const pin='a'.repeat(64),manifest='b'.repeat(64),quote='A synthetic method requiring verification; no study has run.';
const clone=value=>JSON.parse(JSON.stringify(value));
const anchor=()=>[{pointer:'/question_plans/0/method',quote}];
function fixture(){
 const view={project_ref:'project-a',input_version:1,direction_intent_sha256:pin,job:{plan_manifest_sha256:manifest},
  plan:{kind:'Stage3DirectionPlanningResult',question_plans:[{question_ref:'idea-a@1/q',method:quote,unknowns:['Unverified data.']}]}};
 const graph={nodes:[{id:'source',kind:'method',title:'A method',detail:'Verify before study.',sources:anchor()},
  {id:'target',kind:'validation',title:'A check',detail:'Not run.',sources:anchor()}],
  edges:[{from:'source',to:'target',label:'Check the proposed method',sources:anchor()}]};
 const guide={kind:'Stage3ResearchPresentation',version:1,project_ref:'project-a',input_version:1,direction_intent_sha256:pin,
  plan_manifest_sha256:manifest,question_ref:'idea-a@1/q',flow:graph,loop:clone(graph),
  materials:[{name:'A public lead',use:'Verify its fit',gap:'Access unknown',sources:anchor()}],
  baselines:[{name:'A baseline',change:'Remove an input',purpose:'Compare mechanisms',sources:anchor()}]};
 const ctx=vm.createContext({TextDecoder,Uint8Array,crypto:webcrypto,window:{RESEARCH_PROJECTS:{credential:'synthetic-only'}}});
 vm.runInContext(source,ctx);vm.runInContext(renderer,ctx);return {view,guide,ctx};
}
function manualFixture(){
 const f=fixture(),view=f.view;
 Object.assign(view,{revision:2,brief_sha256:pin});view.job.request_sha256='d'.repeat(64);view.plan.markdown='Original plan Markdown.';
 const binding={project_ref:view.project_ref,input_version:view.input_version,revision:view.revision,brief_sha256:view.brief_sha256,
  parent_plan_manifest_sha256:manifest,parent_plan_sha256:'e'.repeat(64),plan_request_sha256:view.job.request_sha256};
 const revision={receipt_sha256:'c'.repeat(64),record:{kind:'revision',binding:clone(binding),request:{key:'manual-a'},revision_number:2,
  plan:clone(view.plan),changes:[{question_ref:'idea-a@1/q',field:'method',value:'Manual method A; data remain unverified.'}],
  execution_authorized:false,native_message:false,model_generated:false,parent_revision:null}};
 revision.record.plan.question_plans[0].method=revision.record.changes[0].value;
 view.feedback={kind:'ProjectStage3PlanningFeedbackView',schema_version:1,binding,records:[revision]};
 function guideFor(row){
  const guide=clone(f.guide),text=row.record.plan.question_plans[0].method;
  Object.assign(guide,{version:2,revision_receipt_sha256:row.receipt_sha256,revision_number:row.record.revision_number});
  for(const graph of [guide.flow,guide.loop])for(const item of [...graph.nodes,...graph.edges])item.sources.forEach(source=>source.quote=text);
  for(const item of [...guide.materials,...guide.baselines])item.sources.forEach(source=>source.quote=text);
  return guide;
 }
 return {...f,revision,manualGuide:guideFor(revision),guideFor};
}
test('manual v2 binds its exact receipt and number while source quotes resolve the selected draft',()=>{
 const f=manualFixture(),before=JSON.stringify(f.view),expected={project_ref:'project-a',input_version:1,direction_intent_sha256:pin,
  plan_manifest_sha256:manifest,revision_receipt_sha256:f.revision.receipt_sha256,revision_number:2};
 assert.deepEqual(clone(f.ctx.v94PlanBinding(f.view,f.revision)),expected);
 assert.equal(f.ctx.v94ValidateGuide(f.manualGuide,f.view,f.revision),f.manualGuide);
 assert.equal(f.ctx.v94GuideName(f.view,f.revision),'stage3-revision-'+f.revision.receipt_sha256+'.json');
 assert.equal(f.ctx.v94GuideName(f.view),'stage3-research-'+manifest+'.json');
 assert.equal(f.ctx.v94ValidateGuide(f.guide,f.view),f.guide);assert.equal(JSON.stringify(f.view),before);
 assert.throws(()=>f.ctx.v94ValidateGuide(f.manualGuide,f.view),/research-guide-/);
 assert.throws(()=>f.ctx.v94ValidateGuide(f.guide,f.view,f.revision),/research-guide-/);
 const stale=clone(f.manualGuide);stale.flow.nodes[0].sources[0].quote=quote;
 assert.throws(()=>f.ctx.v94ValidateGuide(stale,f.view,f.revision),/source-quote/);
});
test('manual guide rejects changed bindings, receipts, revision numbers, pointers and authority fields',()=>{
 const f=manualFixture();
 for(const [key,value] of [['project_ref','project-b'],['input_version','1'],['direction_intent_sha256','f'.repeat(64)],
  ['plan_manifest_sha256','f'.repeat(64)],['revision_receipt_sha256','f'.repeat(64)],['revision_number',3],['revision_number','2'],['version',1]]){
  const bad=clone(f.manualGuide);bad[key]=value;assert.throws(()=>f.ctx.v94ValidateGuide(bad,f.view,f.revision),/research-guide-/,key);
 }
 for(const mutate of [g=>g.execution_authorized=true,g=>g.native_message=false,g=>delete g.revision_number,
  g=>g.flow.nodes[0].sources[0].pointer='/question_plans/1/method',g=>g.flow.nodes[0].sources[0].pointer='/record/plan/question_plans/0/method',
  g=>g.flow.nodes[0].sources[0].quote='An invented result.']){
  const bad=clone(f.manualGuide);mutate(bad);assert.throws(()=>f.ctx.v94ValidateGuide(bad,f.view,f.revision),/research-guide-/);
 }
 for(const key of ['project_ref','input_version','revision','brief_sha256','parent_plan_manifest_sha256','parent_plan_sha256','plan_request_sha256']){
  const stale=clone(f.revision);stale.record.binding[key]='stale';
  assert.equal(f.ctx.v94PlanBinding(f.view,stale),null,key);assert.throws(()=>f.ctx.v94ValidateGuide(f.manualGuide,f.view,stale),/research-guide-/);
 }
 for(const mutate of [r=>r.receipt_sha256='bad',r=>r.record.revision_number=1,r=>r.record.revision_number='2',r=>r.record.kind='comment']){
  const bad=clone(f.revision);mutate(bad);assert.equal(f.ctx.v94PlanBinding(f.view,bad),null);
 }
});
test('manual material selection uses a unique receipt filename and cannot reuse the original guide',()=>{
 const f=manualFixture(),item=(name,id)=>({id:'file-'+id.repeat(32),project_ref:'project-a',stage:3,name,kind:'manual-file',status:'registered',bytes:20,sha256:pin});
 const original=item(f.ctx.v94GuideName(f.view),'1'),manual=item(f.ctx.v94GuideName(f.view,f.revision),'2');
 assert.equal(f.ctx.v94ChooseMaterial({materials:[original,manual]},f.view),original);
 assert.equal(f.ctx.v94ChooseMaterial({materials:[original,manual]},f.view,f.revision),manual);
 assert.equal(f.ctx.v94ChooseMaterial({materials:[original]},f.view,f.revision),null);
 assert.throws(()=>f.ctx.v94ChooseMaterial({materials:[manual,manual]},f.view,f.revision),/ambiguous/);
});
const settle=()=>new Promise(setImmediate);
async function waitFor(check){for(let i=0;i<200;i++){if(check())return;await new Promise(resolve=>setTimeout(resolve,5));}assert.fail('synthetic guide read did not settle');}
function composedFixture({deferred=false}={}){
 const f=manualFixture(),ctx=f.ctx,second=clone(f.revision);
 second.receipt_sha256='f'.repeat(64);second.record.request.key='manual-b';second.record.revision_number=3;
 second.record.plan.question_plans[0].method='Manual method B; its separate limit is unverified.';
 second.record.changes[0].value=second.record.plan.question_plans[0].method;
 f.view.feedback.records.push(second);
 const guides=[f.guide,f.manualGuide,f.guideFor(second)],files=guides.map((guide,i)=>{
  const bytes=Buffer.from(JSON.stringify(guide)),row=i===0?null:i===1?f.revision:second;
  return {bytes,item:{id:'file-'+String(i+1).repeat(32),project_ref:'project-a',stage:3,name:ctx.v94GuideName(f.view,row),kind:'manual-file',status:'registered',bytes:bytes.length,sha256:createHash('sha256').update(bytes).digest('hex')}};
 }),catalog={materials:files.map(file=>file.item)},calls=[],requests=[],listeners={},owned=new Set();let paints=0;
 const basis={project_ref:'project-a',input_version:1,revision:2,brief_sha256:pin},app={page:'workspace',stage:3,lang:'en',el:{contains:element=>owned.has(element),querySelector:()=>null}};
 const escape=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 Object.assign(ctx,{TextEncoder,AbortController,setTimeout,clearTimeout,apps:[app],rt:{epoch:1},v93:{view:f.view,basis},v93Identity:()=>ctx.v93.basis,
  v93Matches:(a,b)=>!!a&&!!b&&['project_ref','input_version','revision','brief_sha256'].every(key=>a[key]===b[key]),
  v7BeforeRender:()=>{},v7AfterRender:()=>{},v93SavedPlanSummary:view=>'<p data-original-plan>'+escape(view.plan.question_plans[0].method)+'</p>',
  laterStage:()=>'<main><div class="n9-page-actions"></div>'+ctx.v93SavedPlanSummary(ctx.v93.view)+'<details class="n9-plan-graph"><summary>Original graph</summary></details></main>',
  livePaint:()=>paints++,liveRequest:async()=>{throw Error('guide reads must not dispatch a planning request');},projectPath:(ref,tail)=>'/api/projects/'+ref+'/'+tail,
  rl:(z,e)=>e,rx:escape,document:{body:{},activeElement:null,addEventListener:(name,listener)=>(listeners[name]??=[]).push(listener)},
  fetch:async(url,options)=>{
   calls.push({url,options});if(url==='/api/v9/materials')return deferred?new Promise(resolve=>requests.push({url,options,resolve})):new Response(JSON.stringify(catalog));
   const file=files.find(file=>url==='/api/v9/files/'+file.item.id);assert.ok(file,'only a registered guide is read');return new Response(file.bytes);
  }});
 vm.runInContext(renderer,ctx);vm.runInContext(adapter,ctx);vm.runInContext(feedback,ctx);
 const guideState=()=>vm.runInContext('({...v94})',ctx),html=()=>ctx.laterStage(app),render=()=>{const value=html();ctx.v7AfterRender(app);return value;};
 async function dispatch(type,element){owned.add(element);for(const listener of listeners[type]||[])await listener({target:element,preventDefault(){}});await settle();}
 async function select(row){const control={dataset:{v94fControl:'selected'},value:row?'revision:'+row.record.request.key:'',closest:selector=>selector==='[data-v94f-control]'?control:null};await dispatch('change',control);render();}
 async function reload(){const button={closest:selector=>selector==='[data-v94-read]'?button:null};await dispatch('click',button);}
 async function close(){for(const request of requests)request.resolve(new Response('{"materials":[]}'));await settle();await settle();}
 return {...f,second,files,catalog,ctx,app,calls,requests,guideState,html,render,select,reload,close,paints:()=>paints};
}
test('composed actual modules select, render and reload the exact manual guide using only GET',async t=>{
 const f=composedFixture(),before=JSON.stringify(f.view);t.after(f.close);
 f.render();await waitFor(()=>f.guideState().status==='ready');
 assert.match(f.html(),/data-v94-guide/);assert.match(f.html(),new RegExp(quote));assert.equal(f.guideState().guide.version,1);
 await f.select(f.revision);await waitFor(()=>f.guideState().status==='ready');
 assert.equal(f.ctx.v94SelectedRevision(f.view).receipt_sha256,f.revision.receipt_sha256);
 assert.equal(f.guideState().guide.revision_receipt_sha256,f.revision.receipt_sha256);
 assert.match(f.html(),/This guide belongs to the selected manual draft/);assert.match(f.html(),/Manual method A/);
 assert.match(f.html(),/Complete manual draft and open checks/);assert.match(f.html(),/Unverified data/);assert.match(f.html(),/Original plan Markdown/);
 assert.match(f.html(),new RegExp('data-original-plan>'+quote));assert.equal(JSON.stringify(f.view),before);
 const count=f.calls.length;await f.reload();await waitFor(()=>f.guideState().status==='ready');
 assert.equal(f.calls.length,count+2);assert.equal(f.calls.at(-1).url,'/api/v9/files/'+f.files[1].item.id);
 await f.select(f.second);await waitFor(()=>f.guideState().status==='ready');
 assert.equal(f.guideState().guide.revision_receipt_sha256,f.second.receipt_sha256);assert.match(f.html(),/Manual method B/);
 await f.select(null);await waitFor(()=>f.guideState().status==='ready');
 assert.equal(f.guideState().guide.version,1);assert.doesNotMatch(f.html(),/data-v94f-manual/);assert.match(f.html(),new RegExp(quote));
 assert.ok(f.calls.every(call=>!call.options.method));assert.ok(f.calls.every(call=>call.url==='/api/v9/materials'||call.url.startsWith('/api/v9/files/')));
});
for(const transition of ['original-to-manual','manual-a-to-b','same-binding-refresh','cross-project']){
 test('late '+transition+' completion cannot repaint or clear its replacement read',async t=>{
  const f=composedFixture({deferred:true});t.after(f.close);
  if(transition==='original-to-manual')f.render();else await f.select(f.revision);
  assert.equal(f.requests.length,1);const first=f.requests[0];
  if(transition==='original-to-manual')await f.select(f.revision);
  else if(transition==='manual-a-to-b')await f.select(f.second);
  else {
   const view=clone(f.ctx.v93.view);
   if(transition==='cross-project'){
    view.project_ref='project-b';view.feedback.binding.project_ref='project-b';view.feedback.records=[];
    f.ctx.v93.basis={...f.ctx.v93.basis,project_ref:'project-b'};
   }
   f.ctx.v93.view=view;f.render();
  }
  assert.equal(f.requests.length,2);assert.equal(first.options.signal.aborted,true);
  const current=f.guideState().controller,paints=f.paints();
  first.resolve(new Response('{"materials":[]}'));await settle();await settle();
  assert.equal(f.guideState().controller,current);assert.equal(f.guideState().status,'loading');assert.equal(f.paints(),paints);assert.equal(f.guideState().guide,null);
  f.requests[1].resolve(new Response(JSON.stringify(transition==='cross-project'?{materials:[]}:f.catalog)));
  await waitFor(()=>f.guideState().controller===null);
  assert.equal(f.guideState().status,'ready');
  if(transition==='cross-project'){
   assert.equal(f.guideState().source,'plan-excerpts');assert.equal(f.guideState().guide.project_ref,'project-b');
  }
  if(transition!=='cross-project')assert.equal(f.guideState().guide.revision_receipt_sha256,transition==='manual-a-to-b'?f.second.receipt_sha256:f.revision.receipt_sha256);
  assert.ok(f.calls.every(call=>!call.options.method));
 });
}
test('authored guide keeps exact source, typed binding and original plan untouched',()=>{
 const {view,guide,ctx}=fixture(),before=JSON.stringify(view);
 assert.equal(ctx.v94ValidateGuide(guide,view),guide);assert.equal(JSON.stringify(view),before);
 assert.equal(ctx.v94GuideName(view),'stage3-research-'+manifest+'.json');
});
test('wrong project, typed version, intent, manifest or question is rejected',()=>{
 const {view,guide,ctx}=fixture();
 for(const [key,value] of [['project_ref','project-b'],['input_version','1'],['direction_intent_sha256','c'.repeat(64)],['plan_manifest_sha256','d'.repeat(64)],['question_ref','other@1/q']]){
  const bad=clone(guide);bad[key]=value;assert.throws(()=>ctx.v94ValidateGuide(bad,view),/research-guide-/);
 }
});
test('unknown authority fields and unsupported source pointers cannot be smuggled in',()=>{
 const {view,guide,ctx}=fixture();
 for(const mutate of [g=>g.execution_authorized=true,g=>g.flow.nodes[0].sources[0].pointer='/__proto__/method',
  g=>g.flow.nodes[0].sources[0].pointer='/question_plans/1/method',g=>g.flow.nodes[0].sources[0].quote='A fabricated conclusion.',
  g=>g.flow.nodes[0].available=true,g=>g.materials[0].status='available']){
  const bad=clone(guide);mutate(bad);assert.throws(()=>ctx.v94ValidateGuide(bad,view),/research-guide-/);
 }
});
test('duplicate nodes, broken or duplicate edges and excessive content fail closed',()=>{
 const {view,guide,ctx}=fixture();
 for(const mutate of [g=>g.flow.nodes.push(clone(g.flow.nodes[0])),g=>g.flow.edges[0].to='missing',
  g=>g.flow.edges.push(clone(g.flow.edges[0])),g=>g.flow.nodes[0].detail='x'.repeat(421),g=>g.loop.nodes=[]]){
  const bad=clone(guide);mutate(bad);assert.throws(()=>ctx.v94ValidateGuide(bad,view),/research-guide-/);
 }
});
test('material lookup rejects ambiguity, oversized uploads and unsafe file references',()=>{
 const {view,ctx}=fixture();const item={id:'file-'+'c'.repeat(32),project_ref:'project-a',stage:3,name:ctx.v94GuideName(view),
  kind:'manual-file',status:'registered',bytes:20,sha256:pin};
 assert.equal(ctx.v94ChooseMaterial({materials:[item]},view),item);
 assert.equal(ctx.v94ChooseMaterial({materials:[{...item,project_ref:'project-b'}]},view),null);
 assert.throws(()=>ctx.v94ChooseMaterial({materials:[item,item]},view),/ambiguous/);
 for(const change of [{bytes:65537},{id:'../../credential'},{status:'uploading'},{sha256:'bad'}])
  assert.throws(()=>ctx.v94ChooseMaterial({materials:[{...item,...change}]},view),/material/);
});
test('binary GET binds exact bytes/hash and retains authentication and no-store',async()=>{
 const {ctx}=fixture(),bytes=Buffer.from('{"display":"only"}'),hash=Buffer.from(await webcrypto.subtle.digest('SHA-256',bytes)).toString('hex');let request;
 ctx.fetch=async(p,o)=>{request={p,o};return new Response(bytes)};
 assert.equal(JSON.stringify(await ctx.v94FetchJson('/api/v9/files/file-'+pin.slice(0,32),65536,null,{bytes:bytes.length,sha256:hash})),JSON.stringify({display:'only'}));
 assert.equal(request.o.headers.Authorization,'Bearer synthetic-only');assert.equal(request.o.cache,'no-store');
 assert.equal(request.o.redirect,'error');assert.equal(request.o.credentials,'same-origin');assert.equal(request.o.method,undefined);
 await assert.rejects(()=>ctx.v94FetchJson('/api/v9/files/file-'+pin.slice(0,32),65536,null,{bytes:bytes.length,sha256:pin}),/hash/);
 await assert.rejects(()=>ctx.v94FetchJson('/api/v9/materials',4,null),/byte-limit/);
});
test('empty catalog leaves original saved plan visible without a planner call',async()=>{
 const f=fixture(),calls=[],basis={project_ref:'project-a',input_version:1,revision:2,brief_sha256:pin};
 Object.assign(f.ctx,{AbortController,setTimeout,clearTimeout,apps:[{page:'workspace',stage:3,el:{querySelector:()=>null}}],rt:{epoch:1},
  v93:{view:f.view,basis},v93Identity:()=>basis,v93Matches:(a,b)=>JSON.stringify(a)===JSON.stringify(b),v7AfterRender:()=>{},
  v93SavedPlanSummary:()=>'<p>Original saved plan</p>',v94GuideHtml:()=>'<p>Guide</p>',livePaint:()=>{},rl:(z,e,t)=>t||z,rx:String,
  document:{addEventListener:()=>{}},fetch:async(p,o)=>{calls.push({p,o});return new Response('{"materials":[]}')}});
 vm.runInContext(adapter,f.ctx);await f.ctx.v94Load(f.view,basis,1);
 assert.deepEqual(calls.map(x=>x.p),['/api/v9/materials']);assert.match(f.ctx.v93SavedPlanSummary(f.view),/Original saved plan/);
 assert.equal(vm.runInContext('v94.status',f.ctx),'ready');assert.equal(vm.runInContext('v94.source',f.ctx),'plan-excerpts');
});
test('late responses cannot paint a different project/version',async()=>{
 const f=fixture(),basis={project_ref:'project-a',input_version:1,revision:2,brief_sha256:pin};let resolve,paints=0;
 Object.assign(f.ctx,{AbortController,setTimeout,clearTimeout,apps:[{page:'workspace',stage:3}],rt:{epoch:1},v93:{view:f.view,basis},
  v93Identity:()=>basis,v93Matches:(a,b)=>a===b,v7AfterRender:()=>{},v93SavedPlanSummary:()=>'',livePaint:()=>paints++,
  document:{addEventListener:()=>{}},fetch:()=>new Promise(r=>{resolve=r})});
 vm.runInContext(adapter,f.ctx);const pending=f.ctx.v94Load(f.view,basis,1);f.ctx.rt.epoch=2;resolve(new Response('{"materials":[]}'));await pending;
 assert.equal(paints,1);assert.equal(vm.runInContext('v94.guide',f.ctx),null);
});
test('complete guide reads exactly the saved material using GET and preserves original details',async()=>{
 const f=fixture(),basis={project_ref:'project-a',input_version:1,revision:2,brief_sha256:pin},calls=[];
 const bytes=Buffer.from(JSON.stringify(f.guide)),hash=Buffer.from(await webcrypto.subtle.digest('SHA-256',bytes)).toString('hex');
 const item={id:'file-'+'c'.repeat(32),project_ref:'project-a',stage:3,name:f.ctx.v94GuideName(f.view),kind:'manual-file',status:'registered',bytes:bytes.length,sha256:hash};
 const before=JSON.stringify(f.view);
 Object.assign(f.ctx,{AbortController,setTimeout,clearTimeout,apps:[{page:'workspace',stage:3}],rt:{epoch:1},v93:{view:f.view,basis},
  v93Identity:()=>basis,v93Matches:(a,b)=>a===b,v7AfterRender:()=>{},v93SavedPlanSummary:()=>'<p>Original source and unknowns</p>',
  v94GuideHtml:g=>'<p>'+g.question_ref+'</p>',livePaint:()=>{},rl:(z,e,t)=>t||z,rx:String,
  document:{addEventListener:()=>{}},fetch:async(p,o)=>{calls.push({p,o});return new Response(p.endsWith('/materials')?JSON.stringify({materials:[item]}):bytes)}});
 vm.runInContext(adapter,f.ctx);await f.ctx.v94Load(f.view,basis,1);
 assert.equal(vm.runInContext('v94.status',f.ctx),'ready');assert.equal(JSON.stringify(f.view),before);
 assert.deepEqual(calls.map(x=>x.p),['/api/v9/materials','/api/v9/files/'+item.id]);assert.ok(calls.every(x=>!x.o.method));
 const html=f.ctx.v93SavedPlanSummary(f.view);assert.match(html,/idea-a@1\/q/);assert.match(html,/<details[^>]*><summary>[^]*Original source and unknowns/);
});
test('wrong material hash yields readable failure and original source, never a rendered guide',async()=>{
 const f=fixture(),basis={project_ref:'project-a',input_version:1,revision:2,brief_sha256:pin};
 const bytes=Buffer.from(JSON.stringify(f.guide)),item={id:'file-'+'c'.repeat(32),project_ref:'project-a',stage:3,name:f.ctx.v94GuideName(f.view),kind:'manual-file',status:'registered',bytes:bytes.length,sha256:pin};
 Object.assign(f.ctx,{AbortController,setTimeout,clearTimeout,apps:[{page:'workspace',stage:3}],rt:{epoch:1},v93:{view:f.view,basis},
  v93Identity:()=>basis,v93Matches:(a,b)=>a===b,v7AfterRender:()=>{},v93SavedPlanSummary:()=>'<p>Retained original</p>',
  v94GuideHtml:()=>{throw Error('must not render')},livePaint:()=>{},rl:(z,e,t)=>t||z,rx:String,document:{addEventListener:()=>{}},
  fetch:async p=>new Response(p.endsWith('/materials')?JSON.stringify({materials:[item]}):bytes)});
 vm.runInContext(adapter,f.ctx);await f.ctx.v94Load(f.view,basis,1);
 assert.equal(vm.runInContext('v94.status',f.ctx),'failed');assert.equal(vm.runInContext('v94.guide',f.ctx),null);
 assert.match(f.ctx.v93SavedPlanSummary(f.view),/research-guide-hash/);assert.match(f.ctx.v93SavedPlanSummary(f.view),/Retained original/);
});
test('same-binding refresh replaces a pending epoch and an old completion cannot clear the new read',async()=>{
 const f=fixture(),basis={project_ref:'project-a',input_version:1,revision:2,brief_sha256:pin},requests=[];
 const app={page:'workspace',stage:3,el:{querySelector:()=>null}};
 Object.assign(f.ctx,{AbortController,setTimeout,clearTimeout,apps:[app],rt:{epoch:1},v93:{view:f.view,basis},
  v93Identity:()=>basis,v93Matches:(a,b)=>a===b,v7AfterRender:()=>{},v93SavedPlanSummary:()=>'<p>Retained original</p>',
  livePaint:()=>{},rl:(z,e,t)=>t||z,rx:String,document:{addEventListener:()=>{}},
  fetch:(p,o)=>new Promise(resolve=>requests.push({p,o,resolve}))});
 vm.runInContext(adapter,f.ctx);f.ctx.v7AfterRender(app);
 assert.equal(requests.length,1);f.ctx.rt.epoch=2;f.ctx.v7AfterRender(app);
 assert.equal(requests.length,2);assert.equal(requests[0].o.signal.aborted,true);
 const current=vm.runInContext('v94.controller',f.ctx);
 requests[0].resolve(new Response('{"materials":[]}'));await new Promise(setImmediate);
 assert.equal(vm.runInContext('v94.controller',f.ctx),current);
 assert.equal(vm.runInContext('v94.status',f.ctx),'loading');
 requests[1].resolve(new Response('{"materials":[]}'));await new Promise(setImmediate);
 assert.equal(vm.runInContext('v94.status',f.ctx),'ready');assert.equal(vm.runInContext('v94.source',f.ctx),'plan-excerpts');assert.equal(vm.runInContext('v94.controller',f.ctx),null);
 assert.doesNotMatch(f.ctx.v93SavedPlanSummary(f.view),/data-v94-read disabled/);
 assert.match(f.ctx.v93SavedPlanSummary(f.view),/Retained original/);
});

test('saved-plan click replaces a pending guide read even when binding and epoch are unchanged',async()=>{
 const f=fixture(),basis={project_ref:'project-a',input_version:1,revision:2,brief_sha256:pin},requests=[],listeners=[],planningReads=[];
 const button={},app={page:'workspace',stage:3,lang:'tw',el:{contains:value=>value===button,querySelector:()=>null}};
 const currentView=()=>({...clone(f.view),...basis});
 Object.assign(f.ctx,{AbortController,setTimeout,clearTimeout,URLSearchParams,encodeURIComponent,decodeURIComponent,
  apps:[app],rt:{epoch:1,ref:'project-a',overview:{project:basis}},canonicalReadonly:()=>false,
  stage2:()=>'',laterStage:()=>'',v7BeforeRender:()=>{},v7AfterRender:()=>{},canonicalTop:()=>'',
  projectPath:(ref,tail)=>'/api/projects/'+ref+'/'+tail,
  liveRequest:async url=>{planningReads.push(url);return currentView();},livePaint:()=>{},
  rl:(z,e,t)=>t||z,rx:String,location:{hash:'#project-a?stage=3&lang=zh-TW'},
  document:{addEventListener:(name,listener)=>{if(name==='click')listeners.push(listener);}},
  fetch:(url,options)=>new Promise(resolve=>requests.push({url,options,resolve}))});
 f.ctx.window.addEventListener=()=>{};
 f.ctx.window.RESEARCH_PROJECTS.stage3_planning_projects=['project-a'];
 vm.runInContext(fs.readFileSync(path.join(__dirname,'v9-stage3-bridge.js'),'utf8'),f.ctx);
 vm.runInContext(adapter,f.ctx);
 const click={target:{closest:selector=>selector==='[data-v93-read]'?button:null}};
 try {
  await listeners[0](click);f.ctx.v7AfterRender(app);
  assert.equal(requests.length,1);const oldView=vm.runInContext('v93.view',f.ctx);
  // livePaint is coalesced: the same-binding GET completes before an animation frame.
  await listeners[0](click);const newView=vm.runInContext('v93.view',f.ctx);
  assert.notEqual(newView,oldView);assert.equal(JSON.stringify(newView),JSON.stringify(oldView));assert.equal(f.ctx.rt.epoch,1);
  f.ctx.v7AfterRender(app);assert.equal(requests.length,2);assert.equal(requests[0].options.signal.aborted,true);
  const replacement=vm.runInContext('v94.controller',f.ctx);
  requests[0].resolve(new Response('{"materials":[]}'));await new Promise(setImmediate);
  assert.equal(vm.runInContext('v94.controller',f.ctx),replacement);assert.equal(vm.runInContext('v94.status',f.ctx),'loading');
  requests[1].resolve(new Response('{"materials":[]}'));await new Promise(setImmediate);
  assert.equal(vm.runInContext('v94.status',f.ctx),'ready');assert.equal(vm.runInContext('v94.source',f.ctx),'plan-excerpts');assert.equal(vm.runInContext('v94.controller',f.ctx),null);
  assert.doesNotMatch(f.ctx.v93SavedPlanSummary(newView),/data-v94-read disabled/);
  assert.deepEqual(planningReads,['/api/projects/project-a/stage3/planning','/api/projects/project-a/stage3/planning']);
  assert.ok(requests.every(request=>request.url==='/api/v9/materials'&&!request.options.method));
 } finally {
  for(const request of requests)request.resolve(new Response('{"materials":[]}'));
  await new Promise(setImmediate);
 }
});

test('exhausted feedback state capacity retains the original saved plan without throwing',async t=>{
 const f=composedFixture();t.after(f.close);
 vm.runInContext('v94fStates.clear(); for(let i=0;i<8;i++)v94fStates.set("occupied-"+i,{busy:true,pending:{}});',f.ctx);
 assert.equal(f.ctx.v94SelectedRevision(f.view),null);assert.doesNotThrow(()=>f.render());
 assert.match(f.html(),/data-original-plan/);assert.doesNotMatch(f.html(),/data-v94f-panel/);
 await waitFor(()=>f.guideState().status==='ready');assert.match(f.html(),/data-original-plan/);
 assert.ok(f.calls.every(call=>!call.options.method));
});
