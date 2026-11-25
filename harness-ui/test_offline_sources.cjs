const {test}=require('node:test');
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {webcrypto,createHash}=require('node:crypto');
const source=fs.readFileSync(require('node:path').join(__dirname,'v9-offline-sources.js'),'utf8');
function fixture(){
 const calls=[],store=new Map(),h='a'.repeat(64),config='b'.repeat(64);
 const index={kind:'ProjectStage1OfflineSources',mode:'fixed-offline-engineering',project_ref:'project-test',revision:8,input_version:1,
  brief_sha256:h,ledger_state_sha256:h,config_sha256:config,execution_authorized:false,model_calls:0,source_acquisition_calls:0,
  scientific_acceptance:false,automatic_retry:false,sources:[{work_ref:'work-test',version_id:'version-test',status:'ready-for-explicit-local-import'}]};
 const offer={...index,work_ref:'work-test',version_id:'version-test',offer_sha256:'c'.repeat(64)};
 const ctx={crypto:webcrypto,TextEncoder,document:{addEventListener(){}},sessionStorage:{setItem:(k,v)=>store.set(k,v),getItem:k=>store.get(k)??null,removeItem:k=>store.delete(k)},
  rt:{ref:'project-test',epoch:1,overview:{project:{project_ref:'project-test',revision:8,input_version:1,brief_sha256:h},stage1:{fixed_replay:{mode:'fixed-offline-engineering'},ledger:{state_sha256:h}}}},
  projectPath:(ref,tail='')=>'/api/projects/'+ref+(tail?'/'+tail:''),livePaint(){},liveRefresh:async()=>{},
  liveReceiptBound:async()=>true,liveFeedback:()=>'<live-original>',rl:(zh,en)=>en,rx:v=>JSON.stringify(v),
  liveRequest:async(path,body)=>{calls.push({path,body});if(body)throw new Error('unobserved');return path.includes('/works/')?offer:index;}};
 ctx.liveBound=()=>({revision:ctx.rt.overview.project.revision,input_version:ctx.rt.overview.project.input_version,brief_sha256:h});
 ctx.liveDisabled=()=>ctx.rt.pending||ctx.rt.busy||ctx.rt.loading||ctx.rt.controlHeld?'disabled':'';
 vm.createContext(ctx);vm.runInContext(source,ctx);
 return {ctx,index,offer,calls,store,run:code=>vm.runInContext(code,ctx)};
}
function receipt(p,status='saved'){
 const body={...p.body,offline_config_sha256:p.offline_source_config_sha256};delete body.revision;
 const canonical=v=>v&&typeof v==='object'?'{'+Object.keys(v).sort().map(k=>JSON.stringify(k)+':'+canonical(v[k])).join(',')+'}':JSON.stringify(v);
 return {project_ref:p.ref,kind:'stage1-offline-source',key:p.body.key,status,execution_authorized:false,
  request_sha256:createHash('sha256').update(canonical({kind:'stage1-offline-source',body})).digest('hex')};
}
test('inspection reads native index and offer without POST',async()=>{const f=fixture();await f.ctx.offlineLoad();assert.equal(f.calls.length,2);assert.ok(f.calls.every(c=>!c.body));assert.ok(f.run('offlineCurrentView()'));});
for(const [field,value] of [['project_ref','project-other'],['input_version','1'],['revision',9],['brief_sha256','d'.repeat(64)],['ledger_state_sha256','d'.repeat(64)],['execution_authorized',true]]){
 test('reject index binding '+field,()=>{const f=fixture();assert.throws(()=>f.ctx.offlineIndex({...f.index,[field]:value}),/binding-mismatch/);});
}
test('offer must bind the exact work version',()=>{const f=fixture();assert.throws(()=>f.ctx.offlineOffer({...f.offer,version_id:'wrong'},f.index.sources[0]),/binding-mismatch/);});
test('stale project view cannot register',async()=>{const f=fixture();await f.ctx.offlineLoad();f.ctx.rt.overview.project.revision++;await f.ctx.offlineRegister('work-test');assert.ok(f.calls.every(c=>!c.body));});
test('lost response preserves durable intent and prevents a second POST',async()=>{const f=fixture();await f.ctx.offlineLoad();await f.ctx.offlineRegister('work-test');const first=f.ctx.rt.pending;assert.ok(first);assert.equal(f.store.get('v7-pending-action'),JSON.stringify(first));await f.ctx.offlineRegister('work-test');assert.equal(f.calls.filter(c=>c.body).length,1);});
test('native redacted receipt binds exact config and rejects changed intent',async()=>{const f=fixture();await f.ctx.offlineLoad();await f.ctx.offlineRegister('work-test');const p=f.ctx.rt.pending,r=receipt(p);assert.equal(await f.ctx.liveReceiptBound(p,r),true);assert.equal(await f.ctx.liveReceiptBound({...p,offline_source_config_sha256:'d'.repeat(64)},r),false);assert.equal(await f.ctx.liveReceiptBound({...p,body:{...p.body,input_version:2}},r),false);assert.equal(await f.ctx.liveReceiptBound(p,{...r,project_ref:'other'}),false);});
test('HTTP409 execution-unknown retains key',async()=>{const f=fixture();await f.ctx.offlineLoad();const original=f.ctx.liveRequest;f.ctx.liveRequest=async(path,body)=>{if(!body)return original(path);const e=new Error('execution-unknown');e.status=409;e.receipt=receipt(f.ctx.rt.pending,'execution-unknown');throw e;};await f.ctx.offlineRegister('work-test');assert.ok(f.ctx.rt.pending);assert.ok(f.store.has('v7-pending-action'));});
test('known native receipt settles pending',async()=>{const f=fixture();await f.ctx.offlineLoad();const original=f.ctx.liveRequest;f.ctx.liveRequest=async(path,body)=>body?receipt(f.ctx.rt.pending):original(path);await f.ctx.offlineRegister('work-test');assert.equal(f.ctx.rt.pending,null);assert.equal(f.store.has('v7-pending-action'),false);});
test('unavailable durable storage sends nothing',async()=>{const f=fixture();await f.ctx.offlineLoad();f.ctx.sessionStorage.setItem=()=>{throw new Error('storage denied')};await assert.rejects(f.ctx.offlineRegister('work-test'),/storage denied/);assert.ok(f.calls.every(c=>!c.body));});
test('live mode and its receipt checker retain original behavior',async()=>{const f=fixture();delete f.ctx.rt.overview.stage1.fixed_replay;assert.equal(f.ctx.liveFeedback({stage:1}),'<live-original>');await f.ctx.offlineLoad();assert.equal(f.calls.length,0);assert.equal(await f.ctx.liveReceiptBound({path:'/live'},{}),true);});
