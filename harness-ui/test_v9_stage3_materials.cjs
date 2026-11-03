'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),test=require('node:test');
const {webcrypto,createHash}=require('node:crypto');
const clone=x=>JSON.parse(JSON.stringify(x)),hash=x=>createHash('sha256').update(x).digest('hex');
function fixture(options={}){
 const binding={project_ref:'alpha',input_version:1,revision:2,brief_sha256:'a'.repeat(64),parent_plan_manifest_sha256:'b'.repeat(64),parent_plan_sha256:'c'.repeat(64),plan_request_sha256:'d'.repeat(64)};
 const plan={kind:'Stage3DirectionPlanningResult',markdown:'Unchanged original',question_plans:[{question_ref:'q1',method:'Original',materials:'Unknown rights',unknowns:['Retained unknown']}]};
 const view={...binding,job:{outcome:'saved',plan_manifest_sha256:binding.parent_plan_manifest_sha256,request_sha256:binding.plan_request_sha256},plan,feedback:{kind:'ProjectStage3PlanningFeedbackView',schema_version:1,binding,records:[]}};
 const listeners={},calls=[],downloads=[],parts=[],rt={ref:'alpha',epoch:1},owned=new Set(),app={page:'workspace',stage:3,el:{contains:x=>owned.has(x),querySelector:()=>null}};
  let entry=null,failOnce=options.loseChunk===true||options.loseEachAttempt===true,serial=0,revisionFailed=false;const abortHistory=[];
 const ctx={Map,TextEncoder,Uint8Array,AbortController,setTimeout,clearTimeout,crypto:{subtle:webcrypto.subtle,randomUUID:()=>String(++serial)},apps:[app],rt,v93:{view,basis:binding},
  v93Identity:()=>rt.ref==='alpha'?binding:null,v93Matches:(a,b)=>a&&b&&['project_ref','input_version','revision','brief_sha256'].every(k=>a[k]===b[k]),
  v93SavedPlanSummary:()=>'<p>Original</p>',laterStage:()=>'<main><div class="n9-page-actions"></div><details class="n9-plan-graph"></details></main>',v7BeforeRender(){},v7AfterRender(){},
  rl:(zh,en)=>en,rx:x=>String(x).replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;'),livePaint(){},projectPath:(r,p)=>'/api/projects/'+r+'/'+p,
  btoa:x=>Buffer.from(x,'binary').toString('base64'),window:{RESEARCH_PROJECTS:{credential:'synthetic-not-real'}},m9Download:(...args)=>downloads.push(args),
  document:{body:{},activeElement:null,addEventListener:(type,fn)=>(listeners[type]??=[]).push(fn)},
  liveRequest:async(url,body)=>{
   calls.push({url,body:clone(body)});
    if(url.endsWith('/upload/start')){
     if(!entry||entry.sha256!==body.sha256||entry.name!==body.name){entry={...body,id:'file-'+hash(JSON.stringify([body.project_ref,body.name,body.sha256])).slice(0,32),kind:'manual-file',status:'uploading',received:0,upload_attempt:1};parts.length=0;}
     else if(entry.status==='aborted'&&body.restart_aborted===true){entry={...entry,status:'uploading',received:0,upload_attempt:entry.upload_attempt+1};parts.length=0;failOnce=options.loseEachAttempt===true;}
     return clone(entry);
    }
   if(url.endsWith('/upload/chunk')){const bytes=Buffer.from(body.base64,'base64');assert.equal(body.offset,entry.received);parts.push(bytes);entry.received+=bytes.length;if(failOnce){failOnce=false;throw Error('synthetic-lost-chunk-reply');}return clone(entry);}
   if(url.endsWith('/upload/finish')){entry.status='registered';return options.finishWrongProject?{...clone(entry),project_ref:'other'}:clone(entry);}
    if(url.endsWith('/upload/abort')){assert.equal(body.expected_generation,entry.upload_attempt);if(entry.status!=='aborted')abortHistory.push({upload_id:entry.id,upload_attempt:entry.upload_attempt,received:entry.received});entry.status='aborted';entry.received=0;parts.length=0;return clone(entry);}
    if(url.endsWith('/revise')){if(options.reviseError&&!revisionFailed){revisionFailed=true;throw options.reviseError;}const updated=clone(plan);updated.question_plans[0].materials=body.changes[0].value;return {receipt_sha256:'f'.repeat(64),record:{kind:'revision',schema_version:2,binding,request:clone(body),revision_number:2,plan:updated,changes:body.changes,material_refs:body.material_refs.map(x=>({...x,name:entry.name}))}};}
   throw Error('unexpected request '+url);
  },
  fetch:async(url,init)=>{
   calls.push({url,init});assert.equal(init.credentials,'omit');assert.equal(init.redirect,'error');
   const data=options.downloadBytes??Buffer.concat(parts);let read=false;
   return {ok:true,body:{getReader:()=>({read:async()=>read?{done:true}:(read=true,{done:false,value:data}),cancel:async()=>{},releaseLock(){}})}};
  }};
 vm.createContext(ctx);for(const name of ['v9-stage3-materials.js','v9-stage3-feedback.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,name),'utf8'),ctx);
 const state=ctx.v94fState(ctx.v94fContext(app));state.field='materials';state.revisionQuestion='q1';state.value='Complete file; rights still unknown';
 const comment={receipt_sha256:'1'.repeat(64),record:{kind:'comment',binding,request:{key:'comment-1'},text:'Retain limitations',question_ref:'q1'}};state.records.push(comment);state.revisionComment='comment-1';
 function file(bytes){return {name:'complete-<material>.txt',size:bytes.length,arrayBuffer:async()=>bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength)};}
  return {ctx,state,app,rt,view,plan,calls,downloads,parts,abortHistory,file,entry:()=>entry,prepare:bytes=>state.materialUpload={file:file(bytes),target:ctx.v95MaterialTarget(state),entry:null},
  async changeFile(value){const control={files:[value],closest:s=>s==='[data-v95-material-file]'?control:null};owned.add(control);for(const fn of listeners.change)await fn({target:control});const end=Date.now()+5000;while(state.busy&&Date.now()<end)await new Promise(r=>setImmediate(r));assert.equal(state.busy,false);},
   async submit(){const control={dataset:{v94fForm:'revise'},closest:s=>s==='[data-v94f-form]'?control:null};owned.add(control);for(const fn of listeners.submit)await fn({target:control,preventDefault(){}});const end=Date.now()+5000;while(state.busy&&Date.now()<end)await new Promise(r=>setImmediate(r));assert.equal(state.busy,false);},
   async click(attribute){const control={dataset:{},hasAttribute:name=>name===attribute,closest:selector=>selector.includes('['+attribute+']')?control:null};owned.add(control);for(const fn of listeners.click)await fn({target:control});const end=Date.now()+5000;while(state.busy&&Date.now()<end)await new Promise(r=>setImmediate(r));assert.equal(state.busy,false);}};
}
test('native file choice and draft submit retain exact bytes outside the small versioned request',async()=>{
 const f=fixture(),data=Buffer.from('界😀"\\\n'.repeat(16000));await f.changeFile(f.file(data));assert.equal(f.state.error,'');assert.equal(f.entry().status,'registered');assert.deepEqual(Buffer.concat(f.parts),data);
 assert.match(f.ctx.v95MaterialEditor(f.ctx.v94fContext(f.app),f.state),/128MiB/);await f.submit();assert.equal(f.state.error,'');
 const sent=f.calls.find(x=>x.url.endsWith('/revise')).body;assert.ok(JSON.stringify(sent).length<2000);assert.equal(sent.material_refs[0].sha256,hash(data));assert.equal(sent.material_refs[0].bytes,data.length);
 const row=f.ctx.v94fRevision(f.state);assert.equal(row.record.revision_number,2);assert.match(f.ctx.v95MaterialLinks(row,row.record.plan.question_plans[0]),/Verify and download complete file/);assert.equal(f.plan.markdown,'Unchanged original');assert.deepEqual(f.plan.question_plans[0].unknowns,['Retained unknown']);
 assert.ok(f.calls.filter(x=>x.url.endsWith('/chunk')).every(x=>Buffer.byteLength(JSON.stringify(x.body))<262144));assert.ok(!f.calls.some(x=>/\/run$|\/prepare$/.test(x.url)));
});
test('uncertain upload resumes by the original identity and confirmed offset',async()=>{
 const f=fixture({loseChunk:true}),data=Buffer.alloc(300000,42);f.prepare(data);await f.ctx.v95MaterialUpload(f.app);assert.match(f.state.error,/lost-chunk/);assert.equal(f.entry().received,131072);
 await f.ctx.v95MaterialUpload(f.app);assert.equal(f.entry().status,'registered');assert.deepEqual(Buffer.concat(f.parts),data);assert.deepEqual(f.calls.filter(x=>x.url.endsWith('/chunk')).map(x=>x.body.offset),[0,131072,262144]);assert.equal(new Set(f.calls.filter(x=>x.url.endsWith('/start')).map(x=>JSON.stringify(x.body))).size,1);
});
test('a file above the existing cap is rejected before reading or sending and clears an old selection',async()=>{
 const f=fixture();f.prepare(Buffer.from('old'));let reads=0;await f.changeFile({name:'oversized.txt',size:128*1024*1024+1,arrayBuffer:async()=>{reads++;throw Error('must not read');}});assert.equal(reads,0);assert.equal(f.calls.length,0);assert.equal(f.state.materialUpload,null);assert.equal(f.state.error,'stage3-material-capacity-exceeded');
});
test('foreign finalization or a changed display cannot become a revision reference',async()=>{
 const f=fixture({finishWrongProject:true});f.prepare(Buffer.from('Actual bytes'));await f.ctx.v95MaterialUpload(f.app);assert.equal(f.state.error,'stage3-material-file-differs');assert.throws(()=>f.ctx.v95MaterialReferences(f.state),/not-complete/);assert.ok(!f.calls.some(x=>x.url.endsWith('/revise')));
 const g=fixture();g.prepare(Buffer.from('Same plan'));await g.ctx.v95MaterialUpload(g.app);g.state.selected='revision:another';assert.equal(g.ctx.v95MaterialReferences(g.state),null);
});
test('complete file download verifies exact size and hash; corrupt and excessive bodies fail',async()=>{
 const data=Buffer.from('界😀 complete material'),f=fixture({downloadBytes:data}),ref={file_id:'file-'+'e'.repeat(32),sha256:hash(data),bytes:data.length};
 assert.deepEqual(Buffer.from(await f.ctx.v95MaterialRead(ref)),data);await assert.rejects(f.ctx.v95MaterialRead({...ref,sha256:'0'.repeat(64)}),/hash-differs/);await assert.rejects(f.ctx.v95MaterialRead({...ref,bytes:data.length-1}),/size-differs/);
});
test('material projection validates revision metadata and escapes user filenames',()=>{
 const f=fixture(),record={kind:'revision',schema_version:2,plan:f.plan,revision_number:3,material_refs:[{question_ref:'q1',file_id:'file-'+'e'.repeat(32),sha256:'2'.repeat(64),bytes:100,name:'<script>not executable</script>'}]};assert.equal(f.ctx.v95MaterialRefsValid(record),true);assert.equal(f.ctx.v95MaterialRefsValid({...record,schema_version:1}),false);assert.equal(f.ctx.v95MaterialRefsValid({...record,material_refs:{}}),false);assert.equal(f.ctx.v95MaterialRefsValid({...record,material_refs:[{...record.material_refs[0],bytes:0}]}),false);
 const html=f.ctx.v95MaterialLinks({receipt_sha256:'f'.repeat(64),record},f.plan.question_plans[0]);assert.doesNotMatch(html,/<script>/);assert.match(html,/100 bytes · v3/);
});
test('native cancel and same-file reselection restart explicitly with the current abort generation',async()=>{
 const options={loseEachAttempt:true},f=fixture(options),data=Buffer.alloc(300000,42),chosen=f.file(data);
 await f.changeFile(chosen);const identity=f.entry().id;assert.equal(f.entry().upload_attempt,1);assert.equal(f.entry().received,131072);
 await f.click('data-v95-material-abort');assert.equal(f.state.materialUpload,null);assert.equal(f.entry().status,'aborted');assert.equal(f.abortHistory.length,1);
 await f.changeFile(chosen);assert.equal(f.entry().id,identity);assert.equal(f.entry().upload_attempt,2);assert.match(f.state.error,/lost-chunk/);
 await f.click('data-v95-material-abort');assert.equal(f.abortHistory.length,2);assert.equal(f.state.materialUpload,null);
 options.loseEachAttempt=false;await f.changeFile(chosen);assert.equal(f.entry().id,identity);assert.equal(f.entry().upload_attempt,3);assert.equal(f.entry().status,'registered');assert.deepEqual(Buffer.concat(f.parts),data);
 assert.deepEqual(f.calls.filter(call=>call.url.endsWith('/upload/abort')).map(call=>call.body),[{id:identity,expected_generation:1},{id:identity,expected_generation:2}]);
 assert.ok(f.calls.filter(call=>call.url.endsWith('/upload/start')).every(call=>call.body.restart_aborted===true));assert.equal(f.abortHistory.length,2);
});
test('exact material prewrite refusals unlock explicit editing and replacement with a new request',async()=>{
 for(const [status,code] of [[400,'stage3-material-references-invalid'],[400,'stage3-material-reference-invalid'],[409,'stage3-material-file-unavailable'],[409,'stage3-material-file-differs'],[409,'stage3-material-reader-unconnected'],[409,'stage3-material-question-differs'],[413,'stage3-material-capacity-exceeded']]){
  const f=fixture({reviseError:Object.assign(Error(code),{status})}),first=Buffer.from('Original complete material'),replacement=Buffer.from('Replacement complete material');
  await f.changeFile(f.file(first));await f.submit();const original=clone(f.calls.find(call=>call.url.endsWith('/revise')).body),count=f.calls.length;
  assert.equal(f.state.pending.refused,true,code);assert.match(f.ctx.v94fHtml(f.ctx.v94fContext(f.app),f.state),/data-v94f-edit-refused/);
  await f.changeFile(f.file(replacement));await f.submit();assert.equal(f.calls.length,count);assert.equal(f.entry().sha256,hash(first));
  await f.click('data-v94f-edit-refused');assert.equal(f.state.pending,null);assert.deepEqual(clone(f.state.lastRefused.body),original);assert.equal(f.state.materialUpload.entry.sha256,hash(first));
  await f.changeFile(f.file(replacement));await f.submit();const requests=f.calls.filter(call=>call.url.endsWith('/revise'));
  assert.equal(requests.length,2);assert.notEqual(requests[1].body.key,original.key);assert.equal(requests[1].body.material_refs[0].sha256,hash(replacement));assert.equal(requests[1].body.material_refs[0].bytes,replacement.length);assert.equal(f.state.pending,null);assert.equal(f.state.error,'');assert.deepEqual(clone(f.state.lastRefused.body),original);
 }
});
test('network,503,unknown and receipt-bearing material errors retain the exact pending request',async()=>{
 for(const error of [Error('network response lost'),Object.assign(Error('stage3-material-file-unavailable'),{status:503}),Object.assign(Error('stage3-material-unknown'),{status:409}),Object.assign(Error('stage3-material-file-unavailable'),{status:400}),Object.assign(Error('stage3-material-file-differs'),{status:409,receipt:{status:'saved'}})]){
  const f=fixture({reviseError:error}),data=Buffer.from('Uncertain complete material');await f.changeFile(f.file(data));await f.submit();
  const pending=clone(f.state.pending),count=f.calls.length;assert.equal(pending.refused,false);assert.doesNotMatch(f.ctx.v94fHtml(f.ctx.v94fContext(f.app),f.state),/data-v94f-edit-refused/);
  await f.click('data-v94f-edit-refused');await f.changeFile(f.file(Buffer.from('Premature replacement')));await f.submit();
  assert.deepEqual(clone(f.state.pending),pending);assert.equal(f.state.lastRefused,undefined);assert.equal(f.calls.length,count);assert.equal(f.entry().sha256,hash(data));
 }
});
