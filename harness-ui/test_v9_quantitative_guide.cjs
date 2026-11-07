'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const {webcrypto,createHash}=require('node:crypto');
const pin=bytes=>createHash('sha256').update(bytes).digest('hex');
const clone=value=>JSON.parse(JSON.stringify(value));
const read=name=>fs.readFileSync(path.join(__dirname,name),'utf8');
function fixture(){
 const view={project_ref:'project-'+'a'.repeat(32),input_version:1,direction_intent_sha256:'b'.repeat(64),
  job:{plan_manifest_sha256:'c'.repeat(64),request_sha256:'d'.repeat(64)},revision:2,brief_sha256:'e'.repeat(64),
  plan:{kind:'Stage3DirectionPlanningResult',question_plans:[{question_ref:'idea-a@1/core',method:'Verify the inputs before research.',unknowns:['Access is unknown.']}]}};
 const binding={project_ref:view.project_ref,input_version:1,revision:2,brief_sha256:view.brief_sha256,
  parent_plan_manifest_sha256:view.job.plan_manifest_sha256,parent_plan_sha256:'f'.repeat(64),plan_request_sha256:view.job.request_sha256};
 view.feedback={binding};
 const revision={receipt_sha256:'9'.repeat(64),record:{kind:'revision',revision_number:11,binding,plan:clone(view.plan)}};
 const data=Buffer.from(JSON.stringify({rows:[{name:'Group A',value:7}]}));
 const guide={kind:'Stage3QuantitativePresentation',version:1,project_ref:view.project_ref,input_version:1,direction_intent_sha256:view.direction_intent_sha256,
  plan_manifest_sha256:view.job.plan_manifest_sha256,question_ref:'idea-a@1/core',title:'Recorded numeric inputs',summary:'Not a completed study.',
  sources:[{id:'data',sha256:pin(data),bytes:data.length,description:'Synthetic test data.'}],limitations:['Access remains unknown.'],
  tables:[{id:'table',title:'One table',context:'Synthetic only.',notes:[],columns:[{key:'label',label:'Group',type:'text',unit:''},{key:'value',label:'Value',type:'number',unit:'units'}],
   rows:[{id:'row',cells:[{source:'data',pointer:'/rows/0/name'},{source:'data',pointer:'/rows/0/value'}]}]}],
  charts:[{type:'bar',title:'Recorded values',table:'table',label:'label',group:null,values:['value']}],next_steps:[{pointer:'/question_plans/0/unknowns/0',quote:'Access is unknown.'}]};
 const basis={project_ref:view.project_ref,version:1},calls=[],files=new Map(),catalog={materials:[]},paint={count:0,mounts:[]};
 const ctx=vm.createContext({TextDecoder,Uint8Array,crypto:webcrypto,AbortController,setTimeout,clearTimeout,
  window:{RESEARCH_PROJECTS:{credential:'synthetic-only'}},document:{documentElement:{lang:'zh-TW'},addEventListener:()=>{}},rt:{epoch:1},apps:[{page:'workspace',stage:3}],
  v93:{basis,view},v93Identity:()=>basis,v93Matches:(left,right)=>left===right,v93QuestionResourceUses:()=>[],v93SavedPlanSummary:()=>'<p>Original plan</p>',
  v94GuideHtml:()=>'<p>Existing design</p>',v7AfterRender:()=>{},livePaint:()=>paint.count++,rl:(cn,en,tw)=>tw,rx:value=>String(value).replaceAll('<','&lt;'),
  v96MountQuant:(target,model,locale)=>paint.mounts.push({target,model,locale})});
 ctx.v94fContext=()=>({view:ctx.v93.view});ctx.v94fState=()=>({revision:ctx.currentRevision??null});ctx.v94fRevision=state=>state.revision;
 for(const name of ['v9-research-guide-contract.js','v9-research-guide.js','v9-quantitative-contract.js','v9-quantitative-guide.js'])vm.runInContext(read(name),ctx);
 function addFile(name,bytes,id){
  const row={project_ref:view.project_ref,stage:3,kind:'manual-file',status:'registered',name,id:'file-'+id.repeat(32),bytes:bytes.length,sha256:pin(bytes)};
  catalog.materials.push(row);files.set(row.id,bytes);return row;
 }
 const source=addFile('stage3-quant-source-'+pin(data)+'.json',data,'1');
 function addGuide(value=guide,rev=null){return addFile(ctx.v96QuantName(view,rev),Buffer.from(JSON.stringify(value)),'2');}
 ctx.fetch=async(url,options)=>{
  calls.push({url,options});
  if(url==='/api/v9/materials')return new Response(JSON.stringify(catalog));
  return new Response(files.get(url.slice('/api/v9/files/'.length))??'',{status:files.has(url.slice('/api/v9/files/'.length))?200:404});
 };
 const state=()=>vm.runInContext('v96',ctx);
 return {ctx,view,revision,guide,data,basis,calls,files,catalog,source,paint,addGuide,state};
}
test('matching materials load through GET only and passive render reuses the same values',async()=>{
 const f=fixture();f.addGuide();const before=JSON.stringify(f.view);
 await f.ctx.v96Load(f.view,f.basis,1);
 assert.equal(f.state().status,'ready');assert.equal(f.state().model.tables[0].rows[0].values[1],7);
 assert.equal(f.calls.length,3);assert.ok(f.calls.every(call=>!call.options.method||call.options.method==='GET'));
 assert.equal(JSON.stringify(f.view),before);
 vm.runInContext('v94.key=v94Key(v93.view,v93Identity());v94.view=v93.view;v94.status="ready";',f.ctx);
 const target={},app={page:'workspace',stage:3,el:{querySelector:selector=>selector==='[data-v96-quant]'?target:null}};
 f.ctx.v7AfterRender(app);f.ctx.v7AfterRender(app);
 assert.equal(f.calls.length,3);assert.equal(f.paint.mounts.length,2);assert.equal(f.paint.mounts[0].locale,'zh-TW');
});
test('absent optional sidecar does not replace or fail the original guide',async()=>{
 const f=fixture();await f.ctx.v96Load(f.view,f.basis,1);
 assert.equal(f.state().status,'absent');assert.equal(f.calls.length,1);assert.equal(f.ctx.v96Section(f.view,null),'');
 assert.match(f.ctx.v94GuideSection(f.view,null,'Original source'),/Existing design/);
});
test('same-length tampering of a registered source is rejected without displaying numbers',async()=>{
 const f=fixture();f.addGuide();f.files.set(f.source.id,Buffer.from(f.data.toString().replace(':7',':8')));
 await f.ctx.v96Load(f.view,f.basis,1);
 assert.equal(f.state().status,'failed');assert.match(f.state().error,/hash/);assert.equal(f.state().model,null);
 assert.match(f.ctx.v94GuideSection(f.view,null,'Original source'),/Original source/);
 assert.match(f.ctx.v96Section(f.view,null),/來源核對/);
});
test('a stale manual receipt fails before any source document read',async()=>{
 const f=fixture();f.ctx.currentRevision=f.revision;
 const guide={...clone(f.guide),revision_receipt_sha256:'0'.repeat(64),revision_number:11};f.addGuide(guide,f.revision);
 await f.ctx.v96Load(f.view,f.basis,1,f.revision);
 assert.equal(f.state().status,'failed');assert.match(f.state().error,/binding/);assert.equal(f.calls.length,2);
});
test('an epoch change while catalog is pending prevents further file reads and repaint',async()=>{
 const f=fixture();f.addGuide();let release;f.ctx.fetch=(url,options)=>{f.calls.push({url,options});return new Promise(resolve=>release=()=>resolve(new Response(JSON.stringify(f.catalog))));};
 const pending=f.ctx.v96Load(f.view,f.basis,1),painted=f.paint.count;f.ctx.rt.epoch=2;release();await pending;
 assert.equal(f.calls.length,1);assert.equal(f.paint.count,painted);assert.equal(f.state().model,null);assert.equal(f.ctx.v96Section(f.view,null),'');
});
test('late verified source cannot paint a different selected revision',{timeout:5000},async()=>{
 const f=fixture();f.addGuide();let release,announce;const requested=new Promise(resolve=>announce=resolve),fetch=f.ctx.fetch;
 f.ctx.fetch=(url,options)=>url.endsWith(f.source.id)?new Promise(resolve=>{release=()=>resolve(new Response(f.data));announce();}):fetch(url,options);
 const pending=f.ctx.v96Load(f.view,f.basis,1);
 await requested;
 assert.equal(typeof release,'function');f.ctx.currentRevision=f.revision;const painted=f.paint.count;release();await pending;
 assert.equal(f.state().model,null);assert.equal(f.paint.count,painted);assert.equal(f.ctx.v96Section(f.view,f.revision),'');
});
test('timeout during the final source digest never publishes a cancelled model',{timeout:5000},async()=>{
 const f=fixture();f.addGuide();let expire,release,announce;
 const hashing=new Promise(resolve=>announce=resolve);
 f.ctx.setTimeout=callback=>{expire=callback;return 1;};f.ctx.clearTimeout=()=>{};
 f.ctx.crypto={subtle:{digest:async(...args)=>{
  const result=await webcrypto.subtle.digest(...args);
  if(pin(Buffer.from(args[1]))===pin(f.data))return new Promise(resolve=>{release=()=>resolve(result);announce();});
  return result;
 }}};
 const pending=f.ctx.v96Load(f.view,f.basis,1);await hashing;
 assert.equal(f.state().status,'loading');assert.equal(f.calls.length,3);
 expire();assert.equal(f.state().controller.signal.aborted,true);release();await pending;
 assert.equal(f.state().status,'failed');assert.match(f.state().error,/read-timeout/);
 assert.equal(f.state().model,null);assert.equal(f.paint.mounts.length,0);
 assert.match(f.ctx.v94GuideSection(f.view,null,'Original source'),/Existing design/);
});
test('timeout while the catalog completes leaves a readable failure, not permanent loading',{timeout:5000},async()=>{
 const f=fixture();f.addGuide();let expire,release;
 f.ctx.setTimeout=callback=>{expire=callback;return 1;};f.ctx.clearTimeout=()=>{};
 f.ctx.fetch=(url,options)=>{f.calls.push({url,options});return new Promise(resolve=>release=()=>resolve(new Response(JSON.stringify(f.catalog))));};
 const pending=f.ctx.v96Load(f.view,f.basis,1);expire();release();await pending;
 assert.equal(f.state().status,'failed');assert.match(f.state().error,/read-timeout/);
 assert.equal(f.calls.length,1);assert.equal(f.state().model,null);
 assert.match(f.ctx.v96Section(f.view,null),/重新讀取數值材料/);
});
