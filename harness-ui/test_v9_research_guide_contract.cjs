/* Synthetic display contract and GET/recovery cases; zero research calls. */
'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const {webcrypto}=require('node:crypto');
const source=fs.readFileSync(path.join(__dirname,'v9-research-guide-contract.js'),'utf8');
const adapter=fs.readFileSync(path.join(__dirname,'v9-research-guide.js'),'utf8');
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
 vm.runInContext(source,ctx);return {view,guide,ctx};
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
 assert.equal(vm.runInContext('v94.status',f.ctx),'absent');
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
 assert.equal(vm.runInContext('v94.status',f.ctx),'absent');assert.equal(vm.runInContext('v94.controller',f.ctx),null);
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
  assert.equal(vm.runInContext('v94.status',f.ctx),'absent');assert.equal(vm.runInContext('v94.controller',f.ctx),null);
  assert.doesNotMatch(f.ctx.v93SavedPlanSummary(newView),/data-v94-read disabled/);
  assert.deepEqual(planningReads,['/api/projects/project-a/stage3/planning','/api/projects/project-a/stage3/planning']);
  assert.ok(requests.every(request=>request.url==='/api/v9/materials'&&!request.options.method));
 } finally {
  for(const request of requests)request.resolve(new Response('{"materials":[]}'));
  await new Promise(setImmediate);
 }
});
