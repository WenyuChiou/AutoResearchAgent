/* Scoped synthetic selection tests: no browser, models, or real user actions. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const {createHash,webcrypto}=require('node:crypto');
const {TextEncoder}=require('node:util');
const source = fs.readFileSync(path.join(__dirname, '../cli/research_workspace_native/web/project-stage2-selection.js'), 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));
class Element {
  constructor(tag='div') { this.tagName=tag.toUpperCase();this.children=[];this.dataset={};this.value='';this.checked=false;this.hidden=false;this.disabled=false;this._text=''; }
  append(...nodes) { this.children.push(...nodes); if(this.tagName==='SELECT'&&!this.value&&nodes[0])this.value=nodes[0].value||nodes[0].textContent; }
  replaceChildren(...nodes) { this.children=nodes; }
  scrollIntoView() {}
  set textContent(value) { this._text=String(value);this.children=[]; }
  get textContent() { return this._text+this.children.map(child=>child.textContent||'').join(''); }
}
const descendants = node => [node,...(node.children||[]).flatMap(descendants)];
function canonical(v) {if(v===null||typeof v!=="object")return JSON.stringify(v);if(Array.isArray(v))return "["+v.map(canonical).join(",")+"]";return "{"+Object.keys(v).sort().map(k=>JSON.stringify(k)+":"+canonical(v[k])).join(",")+"}";}
function digest(kind,body){const semantic={...body};delete semantic.revision;return createHash('sha256').update(canonical({kind,body:semantic}),'utf8').digest('hex');}
function memoryStorage() {const values=new Map();return {get length(){return values.size},key:i=>[...values.keys()][i]??null,getItem:k=>values.has(k)?values.get(k):null,setItem:(k,v)=>values.set(k,String(v)),removeItem:k=>values.delete(k),values};}
function memoryLocks() { const held=new Set(); return {async request(name,opts,callback){if(held.has(name))return callback(null);held.add(name);try{return await callback({name});}finally{held.delete(name);}}}; }
function harness(options={}) {
 const names=['selection-layout','decision-context','preference-bar','preference-summary','review-preference','chosen-directions','intent-panel','formal-panel','language','project','project-context','cards','planning','planning-link','return-cards','planning-summary','choice','submit','submit-and-start','receipt','status','planning-input','actor','message','rationale','conditions','unresolved','confirmed','direction-intent','intent-save','intent-start','intent-status','intent-blockers','intent-receipt','intent-planning-link','intent-message','intent-confirmed'];
 const els=new Map(names.map(id=>[id,new Element(id==='project'||id==='language'?'select':'div')]));
 for(const [id,e] of els)e.id=id;
 const real=options.realFixture, chosen=real?real.body.decision.selected[0]:{candidate_id:'candidate',candidate_version:1};
 const brief=real?real.before.brief_sha256:'a'.repeat(64);let ack='b'.repeat(64), selectReceipt=null;
 const binding=real?{project_ref:real.before.project_ref,input_version:real.before.input_version,revision:options.preselected?real.after.revision:real.before.revision,brief_sha256:real.before.brief_sha256}:{project_ref:'project-a',input_version:1,revision:1,brief_sha256:brief};
 let selected=!!options.preselected, current=true, writes=[], reads=[], uuid=0, release, waitSelect=false, intent=!!options.intent, prepared=false, readRelease, holdRead=!!options.holdRead, runRelease, intentRelease, holdIntent=false, intentReceipt=options.existingIntent||null, historyRelease;
 if(real && options.preselected){selectReceipt=real.after.selection_receipt;ack=real.post.request_sha256;}
 const card={candidate_id:chosen.candidate_id,candidate_version:chosen.candidate_version,candidate_question:'Bounded question',suggested_approach:'A method',closest_prior_work:{review:null},contribution:[],scientific_questions:[],requirements:[],unmapped_resources:[],limitations:[],alternatives:[],next_checks:[]};
 const view=()=>real?{...structuredClone(selected?real.after:real.before),delivery_workflow_head_sha256:real.before.workflow_head_sha256}:({ ...binding,delivery_workflow_head_sha256:'d'.repeat(64),revision:(selected||intentReceipt)?2:1,delivery_manifest_sha256:'c'.repeat(64),workflow_head_sha256:selected?'9'.repeat(64):'d'.repeat(64),snapshot_sha256:'e'.repeat(64),eligible:options.empty?[]:[chosen],selection_status:selected?'recorded':'pending',selection_receipt:selected?selectReceipt:null,planning_input:selected?{questions:[],legacy_candidates:[],selection_conditions:['keep'],unresolved:['unknown'],execution_authorized:false}:null,planning_status:selected?'verified':'pending',execution_authorized:false,direction_intent:intentReceipt || (intent?{intent_sha256:'f'.repeat(64)}:null),cards:{cards:options.cards || [card]},...(options.versionMismatch?{input_version:'1'}:{}),...(selected && options.driftAfterSave?{workflow_head_sha256:'0'.repeat(64)}:{}) });
 const response=(v,status=200)=>({ok:status>=200&&status<300,status,json:async()=>structuredClone(v)});
 const fetch=async (url,init)=>{
  const body=init?.body?JSON.parse(init.body):null;
  if(init?.method==='POST')writes.push({url,body});else reads.push(url);
  if(url==='/api/projects')return response({projects:[]});
  if(url.endsWith('/history')) {if(options.holdHistory)await new Promise(resolve=>{historyRelease=resolve});const actions=[];if(selected)actions.push(real?structuredClone(real.history.actions[0]):{...selectReceipt,project_ref:binding.project_ref,kind:'stage2-select',status:'saved'});if(intentReceipt)actions.push({...intentReceipt,project_ref:binding.project_ref,kind:'stage2-direction-intent'});let h={project_ref:binding.project_ref,revision:real?(selected?real.after.revision:real.before.revision):(selected||intentReceipt?2:1),versions:[{input_version:binding.input_version,sha256:binding.brief_sha256}],actions,execution_authorized:false};return response(options.historyTransform?options.historyTransform(h):h);}
  if(url.endsWith('/stage2/selection')){const captured=view();if(holdRead){holdRead=false;await new Promise(resolve=>{readRelease=resolve});}return response(captured);}
  if(url.endsWith('/stage2/select')){
   if(waitSelect)await new Promise(resolve=>{release=resolve});
   selected=true;ack=real?real.post.request_sha256:digest('stage2-select',body);selectReceipt=real?real.after.selection_receipt:{key:body.key,request_sha256:ack,delivery_manifest_sha256:'c'.repeat(64),interaction_file_sha256:'7'.repeat(64),planning_manifest_sha256:'8'.repeat(64),workflow_head_sha256:'9'.repeat(64),artifact_ref:'stage2-choice-'+ack,selection_status:'recorded',planning_status:'verified',execution_authorized:false};
   if(options.failSelectResponse)throw Error('synthetic lost response');return response(real?real.post:{...selectReceipt,project_ref:binding.project_ref,kind:'stage2-select',status:'saved'});
  }
  if(url.endsWith('/stage2/direction-intent')) {
   if(holdIntent)await new Promise(resolve=>{intentRelease=resolve});
   intentReceipt={status:'saved',key:body.key,mode:'direction-advice',human_selection:'pending',execution_authorized:false,artifact_ref:'synthetic',request_sha256:digest('stage2-direction-intent',body),intent_sha256:'2'.repeat(64),submission_sha256:'3'.repeat(64),advisory_manifest_sha256:'4'.repeat(64)};
   return response(intentReceipt);
  }
  if(url.endsWith('/stage3/planning') && options.planOverride)return response(options.planOverride);
  if(url.endsWith('/stage3/planning') && options.intentReady){const request={key:'plan-key',revision:2,input_version:binding.input_version,brief_sha256:brief,mode:'direction-intent',direction_intent_sha256:intentReceipt.intent_sha256};return response({project_ref:binding.project_ref,input_version:binding.input_version,revision:2,brief_sha256:brief,planning_mode:'direction-intent',direction_intent_sha256:intentReceipt.intent_sha256,planning_configured:true,default_request:{...request,...(prepared?{request_sha256:'1'.repeat(64)}:{})},job:prepared?{status:'intent-recorded',request_sha256:'1'.repeat(64)}:null,submission_in_progress:false,submission_error:null});}
  if(url.endsWith('/stage3/planning') && options.intentNeedsInformation)return response({project_ref:binding.project_ref,input_version:binding.input_version,revision:2,brief_sha256:brief,planning_mode:'direction-intent',direction_intent_sha256:intentReceipt.intent_sha256,planning_status:'needs-information',planning_blockers:['clarify']});
  if(url.endsWith('/stage3/planning')) return response({project_ref:'project-a',input_version:1,revision:2,brief_sha256:brief,selection_status:'recorded',selection_request_sha256:ack,planning_configured:true,default_request:{key:'plan-key',selection_request_sha256:ack,...(prepared?{request_sha256:'1'.repeat(64)}:{})},job:prepared?{status:'intent-recorded',request_sha256:'1'.repeat(64)}:null,submission_in_progress:false,submission_error:null});
  if(url.endsWith('/stage3/planning/prepare')) {prepared=true;if(options.losePrepareResponse)throw Error('synthetic prepare response lost');return response({status:'intent-recorded',request_sha256:'1'.repeat(64)});}
  if(url.endsWith('/stage3/planning/run')) {
   if(options.holdRun) await new Promise(resolve=>{runRelease=resolve});
   const flags={execution_authorized:false,evaluation_calls_authorized:false,formal_execution_enabled:false,external_claim_ready:false,usable_for_formal_pairing:false};
   return response({kind:'ProjectStage3PlanningSubmission',submission_status:'accepted',...flags,job:{kind:options.intentReady?'ProjectStage3DirectionPlanningJob':'ProjectStage3PlanningJob',...(options.intentReady?{mode:'direction-intent',formal_selected_receiver:false}:{}),project_ref:options.badRunProject?'project-b':'project-a',key:'plan-key',request_sha256:'1'.repeat(64),status:'intent-recorded',...flags}},202);
  }
  throw Error('unexpected request '+url);
 };
 const root={getElementById:id=>els.get(id),querySelectorAll:()=>[],querySelector:selector=>{
  assert.equal(selector,'input[name="direction"]:checked');return descendants(els.get('cards')).find(n=>n.name==='direction'&&n.checked)||null;
 }};
 const doc={getElementById:()=>null,createElement:tag=>new Element(tag),createTextNode:t=>({textContent:String(t)}),documentElement:{}};
 const store=options.storage||memoryStorage();const recoveryNotifications=[],navigations=[],window={navigator:options.noLocks?{}:{locks:options.locks||memoryLocks()},localStorage:store,RESEARCH_PROJECTS:{credential:'synthetic',stage2_selection_projects:[binding.project_ref],stage3_planning_projects:[binding.project_ref]},location:{assign:()=>{throw Error('embedded navigation must be scoped')}}};
 const ctx={window,document:doc,location:{pathname:'/',hash:''},history:{replaceState:()=>{throw Error('embedded history is parent-owned')}},URLSearchParams,TextEncoder,crypto:{subtle:webcrypto.subtle,randomUUID:()=>real?(++uuid,real.body.key):('key-'+ ++uuid)},fetch,console};
 vm.runInNewContext(source,ctx);
 const args={embedded:true,bootstrap:window.RESEARCH_PROJECTS,binding,language:'zh-TW',isCurrent:b=>current&&b.project_ref===binding.project_ref,onAccepted:v=>navigations.push(['accepted',v]),onNavigate:v=>navigations.push(['manual',v]),onRecoveryChange:v=>recoveryNotifications.push(v)};
 const handle=options.deferMount?null:window.STAGE2_SELECTION.mount(root,args);
 function selectRadio(){const radio=descendants(els.get('cards')).find(n=>n.name==='direction');assert.ok(radio);radio.checked=true;}
 function form(){els.get('confirmed').checked=true;els.get('actor').value='Synthetic';els.get('message').value='Synthetic choice';els.get('rationale').value='Synthetic reason';els.get('conditions').value='keep';els.get('unresolved').value='unknown';}
 return {els,root,window,args,handle,writes,reads,navigations,recoveryNotifications,selectRadio,form,setCurrent:v=>{current=v},waitSelect:()=>{waitSelect=true},release:()=>release(),uuids:()=>uuid,setIntent:()=>{intent=true},releaseRead:()=>readRelease(),releaseRun:()=>runRelease(),waitIntent:()=>{holdIntent=true},releaseIntent:()=>intentRelease(),releaseHistory:()=>historyRelease(),store,binding};
}

module.exports={harness,Element,descendants,memoryStorage,memoryLocks};
if(require.main===module) {
test('a saved preference receipt stays distinct from an empty or edited local draft',async()=>{
 const receipt={status:'saved',intent_sha256:'f'.repeat(64)},f=harness({existingIntent:receipt,deferMount:true});
 f.binding.revision=2;const handle=f.window.STAGE2_SELECTION.mount(f.root,f.args);await tick();
 for(const [lang,saved,draft,empty,count] of [['en',/already saved/,/Current editing draft/,/No directions added/,/1 direction/],['zh-TW',/已有保存/,/目前編輯草稿/,/尚未加入方向/,/已加入 1/],['zh-CN',/已有保存/,/当前编辑草稿/,/尚未加入方向/,/已加入 1/]]){
  handle.setLanguage(lang);const summary=f.els.get('preference-summary');
  assert.match(summary.textContent,saved);assert.match(summary.textContent,draft);assert.match(summary.textContent,empty);
  const box=descendants(f.els.get('cards')).find(n=>n.name==='tentative-direction');assert.equal(box.checked,false);
  assert.equal(f.els.get('intent-confirmed').checked,false);assert.equal(f.els.get('intent-message').value,'');
  box.checked=true;box.onchange();assert.match(summary.textContent,saved);assert.match(summary.textContent,count);
  box.checked=false;box.onchange();assert.match(summary.textContent,empty);
 }
 assert.equal(f.writes.length,0);assert.equal(f.navigations.length,0);assert.equal(f.store.length,0);
});
test('scoped current cards retain unknowns, and zero recommendation never creates a choice',async()=>{
 const f=harness({empty:true});await tick();assert.equal(f.els.get('choice').hidden,true);assert.match(f.els.get('status').textContent,/沒有可推薦/);assert.equal(f.writes.length,0);assert.equal(f.handle.state().submitted,false);
});
test('mismatched typed version is rejected without exposing cards or sending writes',async()=>{
 const f=harness({versionMismatch:true});await tick();assert.match(f.els.get('status').textContent,/version-differs/);assert.equal(f.els.get('cards').children.length,0);assert.equal(f.writes.length,0);
});
test('language changes preserve input, original candidate selection and three-language link',async()=>{
 const f=harness();await tick();f.selectRadio();f.form();
 for(const lang of ['en','zh-TW','zh-CN']) {assert.equal(f.handle.setLanguage(lang),true);assert.equal(f.els.get('message').value,'Synthetic choice');assert.ok(f.root.querySelector('input[name="direction"]:checked'));assert.match(f.els.get('intent-planning-link').href,new RegExp('lang='+lang));}
 assert.equal(f.writes.length,0);
});
test('suspend blocks delayed continuation and resuming retries original request key',async()=>{
 const f=harness();await tick();f.selectRadio();f.form();f.waitSelect();
 const first=f.els.get('choice').onsubmit({preventDefault(){},submitter:f.els.get('submit')});while(f.writes.length===0)await tick();
 assert.equal(f.writes.length,1);assert.equal(f.handle.suspend().pending,true);f.setCurrent(false);f.release();await first;
 assert.equal(f.writes.length,1);assert.equal(f.navigations.length,0);assert.equal(f.handle.dispose(),false);
 f.setCurrent(true);assert.equal(f.handle.resume(),true);f.selectRadio();
 await f.els.get('choice').onsubmit({preventDefault(){},submitter:f.els.get('submit')});assert.equal(f.writes.length,1);
 const result=await f.handle.reconcile({...f.binding,revision:2});assert.equal(result.status,'verified');assert.equal(f.handle.dispose(),true);assert.equal(f.writes.length,1);assert.equal(f.uuids(),1);assert.equal(f.navigations.length,0);
});
test('retained session rejects new roots and changed binding rather than discarding a transaction',async()=>{
 const f=harness();await tick();assert.equal(f.window.STAGE2_SELECTION.mount(f.root,f.args),f.handle);
 assert.throws(()=>f.window.STAGE2_SELECTION.mount({...f.root},{...f.args,binding:{...f.args.binding,revision:2}}),/session-retained/);
});
test('disposal invalidates pending read and no navigation or POST follows',async()=>{
 const f=harness();f.setCurrent(false);f.handle.suspend();await tick();assert.equal(f.writes.length,0);assert.equal(f.navigations.length,0);assert.equal(f.handle.resume(),false);
});

test('initial resume does not duplicate GET; stale initial read is retried only after it finishes',async()=>{
 const f=harness({holdRead:true});assert.equal(f.handle.resume(),true);assert.equal(f.reads.filter(x=>x.endsWith('/stage2/selection')).length,1);
 f.handle.suspend();assert.equal(f.handle.resume(),true);assert.equal(f.reads.filter(x=>x.endsWith('/stage2/selection')).length,1);
 f.releaseRead();await tick();await tick();assert.equal(f.reads.filter(x=>x.endsWith('/stage2/selection')).length,2);assert.equal(f.els.get('cards').children.length,1);
});
test('accepted one-click planning notifies parent exactly once with bound project and locale',async()=>{
 const f=harness();await tick();f.selectRadio();f.form();await f.els.get('choice').onsubmit({preventDefault(){},submitter:f.els.get('submit-and-start')});
 assert.equal(f.navigations.length,1);assert.equal(f.navigations[0][0],'accepted');assert.equal(f.navigations[0][1].projectRef,'project-a');assert.equal(f.navigations[0][1].language,'zh-TW');assert.equal(f.navigations[0][1].request.key,'plan-key');
 assert.equal(f.writes.filter(x=>x.url.endsWith('/run')).length,1);
});
test('suspended accepted planning response cannot notify or navigate a different project',async()=>{
 const f=harness({holdRun:true});await tick();f.selectRadio();f.form();const first=f.els.get('choice').onsubmit({preventDefault(){},submitter:f.els.get('submit-and-start')});for(let i=0;i<500 && !f.writes.some(x=>x.url.endsWith('/run'));i++)await tick();
 assert.equal(f.writes.filter(x=>x.url.endsWith('/run')).length,1);f.handle.suspend();f.setCurrent(false);f.releaseRun();await first;assert.equal(f.navigations.length,0);assert.equal(f.writes.length,3);
});
test('manual planning links preserve locale and notify only on explicit current click',async()=>{
 const f=harness({intent:true});await tick();f.selectRadio();f.form();await f.els.get('choice').onsubmit({preventDefault(){},submitter:f.els.get('submit')});
 for(const lang of ['en','zh-TW','zh-CN']){f.handle.setLanguage(lang);const link=descendants(f.els.get('planning-summary')).find(n=>n.id==='stage3-entry');assert.match(link.href,new RegExp('lang='+lang));assert.match(f.els.get('intent-planning-link').href,new RegExp('lang='+lang));link.onclick({preventDefault(){}});assert.equal(f.navigations.at(-1)[1].language,lang);}
 f.setCurrent(false);f.els.get('intent-planning-link').onclick({preventDefault(){}});assert.equal(f.navigations.length,3);
});

test('a changed delivery pin after save is held before planning',async()=>{
 const f=harness({driftAfterSave:true});await tick();f.selectRadio();f.form();await f.els.get('choice').onsubmit({preventDefault(){},submitter:f.els.get('submit-and-start')});
 assert.equal(f.writes.length,1);assert.match(f.els.get('status').textContent,/尚未確認/);assert.equal(f.navigations.length,0);
});
test('an accepted response for another project cannot navigate',async()=>{
 const f=harness({badRunProject:true});await tick();f.selectRadio();f.form();await f.els.get('choice').onsubmit({preventDefault(){},submitter:f.els.get('submit-and-start')});assert.equal(f.navigations.length,0);
});
test('suspended tentative preference keeps its request key and never advances in the background',async()=>{
 const f=harness();await tick();const box=descendants(f.els.get('cards')).find(n=>n.name==='tentative-direction');assert.ok(box);box.checked=true;box.onchange();f.els.get('intent-message').value='Keep this open';f.els.get('intent-confirmed').checked=true;f.waitIntent();
 const first=f.els.get('direction-intent').onsubmit({preventDefault(){},submitter:f.els.get('intent-save')});while(f.writes.length===0)await tick();assert.equal(f.writes.length,1);f.handle.suspend();f.setCurrent(false);f.releaseIntent();await first;assert.equal(f.writes.length,1);assert.equal(f.navigations.length,0);
 f.setCurrent(true);assert.equal(f.handle.resume(),true);await f.els.get('direction-intent').onsubmit({preventDefault(){},submitter:f.els.get('intent-save')});
 const result=await f.handle.reconcile({...f.binding,revision:2});assert.equal(result.status,'verified');assert.equal(f.writes.length,1);assert.equal(f.uuids(),1);assert.equal(f.navigations.length,0);
});


test('a verified saved selection allows disposal and mounting the accepted new revision',async()=>{
 const f=harness();await tick();f.selectRadio();f.form();await f.els.get('choice').onsubmit({preventDefault(){},submitter:f.els.get('submit')});
 assert.equal(f.handle.state().uncertain,false);assert.equal(f.handle.dispose(),true);
 const nextRoot={...f.root}, next=f.window.STAGE2_SELECTION.mount(nextRoot,{...f.args,binding:{...f.args.binding,revision:2}});await tick();
 assert.equal(next.state().active,true);assert.equal(f.writes.length,1);assert.match(f.els.get('status').textContent,/已登記選案/);
});
test('failed verification remains uncertain and cannot be disposed or replaced',async()=>{
 const f=harness({driftAfterSave:true});await tick();f.selectRadio();f.form();await f.els.get('choice').onsubmit({preventDefault(){},submitter:f.els.get('submit')});
 assert.equal(f.handle.state().uncertain,true);assert.equal(f.handle.dispose(),false);assert.throws(()=>f.window.STAGE2_SELECTION.mount({...f.root},{...f.args,binding:{...f.args.binding,revision:2}}),/session-retained/);
});

 test('real ProjectHost receipt advances head and validates canonical request hash',async()=>{
  const real=require('./fixtures/stage2_formal_selection_service_saved.json'), f=harness({realFixture:real});await tick();f.selectRadio();
  f.els.get('confirmed').checked=true;for(const [field,value] of Object.entries({actor:real.body.decision.actor,message:real.body.decision.user_text,rationale:real.body.decision.rationale,conditions:real.body.decision.conditions.join('\n'),unresolved:real.body.decision.unresolved.join('\n')}))f.els.get(field).value=value;
  await f.els.get('choice').onsubmit({preventDefault(){},submitter:f.els.get('submit')});
  assert.notEqual(real.before.workflow_head_sha256,real.after.workflow_head_sha256);assert.equal(f.writes.length,1);assert.deepEqual(f.writes[0].body,real.body);assert.equal(f.handle.state().recovery,null);assert.equal(f.handle.dispose(),true);
 });
 test('saved formal receipt after reload matches verified delivery head',async()=>{
  const real=require('./fixtures/stage2_formal_selection_service_saved.json'),store=memoryStorage(),b=real.body;
  const marker={schema:1,project_ref:real.before.project_ref,input_version:b.input_version,revision:b.revision,brief_sha256:b.brief_sha256,delivery_manifest_sha256:b.delivery_manifest_sha256,workflow_head_sha256:b.workflow_head_sha256,snapshot_sha256:b.snapshot_sha256,kind:'stage2-select',key:b.key,request_sha256:real.post.request_sha256,phase:'stage2',planning_key:null,planning_sha256:null};
  store.setItem('ara.stage2.pending.v1.'+marker.project_ref+'.'+marker.key,JSON.stringify(marker));const f=harness({realFixture:real,preselected:true,storage:store});await tick();
  assert.equal(f.handle.state().recovery.status,'unknown');const result=await f.handle.reconcile(f.binding);assert.equal(result.status,'verified');assert.equal(store.length,0);assert.equal(f.writes.length,0);assert.equal(f.handle.dispose(),true);
 });
 test('forged history and corrupt storage retain unknown and prohibit writes',async()=>{
  const real=require('./fixtures/stage2_formal_selection_service_saved.json'),store=memoryStorage(),b=real.body;
  const marker={schema:1,project_ref:real.before.project_ref,input_version:b.input_version,revision:b.revision,brief_sha256:b.brief_sha256,delivery_manifest_sha256:b.delivery_manifest_sha256,workflow_head_sha256:b.workflow_head_sha256,snapshot_sha256:b.snapshot_sha256,kind:'stage2-select',key:b.key,request_sha256:real.post.request_sha256,phase:'stage2',planning_key:null,planning_sha256:null};
  const key='ara.stage2.pending.v1.'+marker.project_ref+'.'+marker.key;store.setItem(key,JSON.stringify(marker));const f=harness({realFixture:real,preselected:true,storage:store,historyTransform:h=>{h.actions[0].request_sha256='0'.repeat(64);return h}});await tick();
  const result=await f.handle.reconcile(f.binding);assert.equal(result.status,'unknown');assert.equal(store.length,1);assert.equal(f.writes.length,0);assert.equal(f.handle.dispose(),false);
  const broken=memoryStorage();broken.setItem(key,'{');const g=harness({realFixture:real,storage:broken});await tick();assert.equal(g.handle.state().recovery.status,'unavailable');assert.equal(g.writes.length,0);assert.equal(broken.getItem(key),'{');
 });
 test('binding change during reconcile never clears a pending marker',async()=>{
  const real=require('./fixtures/stage2_formal_selection_service_saved.json'),store=memoryStorage(),b=real.body;
  const marker={schema:1,project_ref:real.before.project_ref,input_version:b.input_version,revision:b.revision,brief_sha256:b.brief_sha256,delivery_manifest_sha256:b.delivery_manifest_sha256,workflow_head_sha256:b.workflow_head_sha256,snapshot_sha256:b.snapshot_sha256,kind:'stage2-select',key:b.key,request_sha256:real.post.request_sha256,phase:'stage2',planning_key:null,planning_sha256:null};store.setItem('ara.stage2.pending.v1.'+marker.project_ref+'.'+marker.key,JSON.stringify(marker));
  const f=harness({realFixture:real,preselected:true,storage:store,holdHistory:true});await tick();const p=f.handle.reconcile(f.binding);await tick();f.setCurrent(false);f.releaseHistory();const result=await p;assert.equal(result.status,'unknown');assert.equal(store.length,1);assert.equal(f.writes.length,0);
 });

 test('multiple same-project action markers never overwrite and remain unresolved',async()=>{
  const real=require('./fixtures/stage2_formal_selection_service_saved.json'),store=memoryStorage(),b=real.body;
  const marker={schema:1,project_ref:real.before.project_ref,input_version:b.input_version,revision:b.revision,brief_sha256:b.brief_sha256,delivery_manifest_sha256:b.delivery_manifest_sha256,workflow_head_sha256:b.workflow_head_sha256,snapshot_sha256:b.snapshot_sha256,kind:'stage2-select',key:b.key,request_sha256:real.post.request_sha256,phase:'stage2',planning_key:null,planning_sha256:null};
  const prefix='ara.stage2.pending.v1.'+marker.project_ref+'.';store.setItem(prefix+marker.key,JSON.stringify(marker));const second={...marker,key:'second-key'};store.setItem(prefix+second.key,JSON.stringify(second));const original=[...store.values.entries()];
  const f=harness({realFixture:real,preselected:true,storage:store});await tick();assert.equal(f.handle.state().recovery.code,'multiple-pending');const result=await f.handle.reconcile(f.binding);assert.equal(result.status,'unknown');assert.deepEqual([...store.values.entries()],original);assert.equal(f.writes.length,0);assert.equal(f.handle.dispose(),false);
 });
 test('different typed version and unavailable storage fail closed',async()=>{
  const real=require('./fixtures/stage2_formal_selection_service_saved.json'),store=memoryStorage(),b=real.body;
  const marker={schema:1,project_ref:real.before.project_ref,input_version:b.input_version,revision:b.revision,brief_sha256:b.brief_sha256,delivery_manifest_sha256:b.delivery_manifest_sha256,workflow_head_sha256:b.workflow_head_sha256,snapshot_sha256:b.snapshot_sha256,kind:'stage2-select',key:b.key,request_sha256:real.post.request_sha256,phase:'stage2',planning_key:null,planning_sha256:null};store.setItem('ara.stage2.pending.v1.'+marker.project_ref+'.'+marker.key,JSON.stringify(marker));
  const f=harness({realFixture:real,preselected:true,storage:store});await tick();assert.equal((await f.handle.reconcile({...f.binding,input_version:'1'})).status,'unknown');assert.equal(store.length,1);assert.equal(f.writes.length,0);
  const g=harness({realFixture:real,storage:{get length(){throw Error('denied')}}});await tick();assert.equal(g.handle.state().recovery.status,'unavailable');assert.equal(g.writes.length,0);
 });

 test('lost POST response notifies Wiki without navigation and permits explicit read-only recovery',async()=>{
  const f=harness({failSelectResponse:true});await tick();f.selectRadio();f.form();await f.els.get('choice').onsubmit({preventDefault(){},submitter:f.els.get('submit')});await tick();
  assert.equal(f.recoveryNotifications.at(-1).status,'unknown');assert.equal(f.writes.length,1);assert.equal(f.navigations.length,0);
  const checked=await f.handle.reconcile({...f.binding,revision:2});assert.equal(checked.status,'verified');assert.equal(f.writes.length,1);assert.equal(f.handle.dispose(),true);
 });

 test('needs-information preserves saved preference and clears pre-prepare marker without dispatch',async()=>{
  const f=harness({intentNeedsInformation:true});await tick();const box=descendants(f.els.get('cards')).find(n=>n.name==='tentative-direction');box.checked=true;box.onchange();f.els.get('intent-message').value='clarify';f.els.get('intent-confirmed').checked=true;
  await f.els.get('direction-intent').onsubmit({preventDefault(){},submitter:f.els.get('intent-start')});assert.equal(f.writes.length,1);assert.match(f.els.get('intent-status').textContent,/聚焦/);assert.equal(f.store.length,0);assert.equal(f.handle.state().uncertain,false);assert.equal(f.navigations.length,0);
 });
 test('marker rejects coerced hash and key arrays and a different valid prior head remains unknown',async()=>{
  const real=require('./fixtures/stage2_formal_selection_service_saved.json'),b=real.body,prefix='ara.stage2.pending.v1.'+real.before.project_ref+'.';
  const marker={schema:1,project_ref:real.before.project_ref,input_version:b.input_version,revision:b.revision,brief_sha256:b.brief_sha256,delivery_manifest_sha256:b.delivery_manifest_sha256,workflow_head_sha256:b.workflow_head_sha256,snapshot_sha256:b.snapshot_sha256,kind:'stage2-select',key:b.key,request_sha256:real.post.request_sha256,phase:'stage2',planning_key:null,planning_sha256:null};
  for(const patch of [{brief_sha256:[b.brief_sha256]},{key:[b.key]},{planning_key:['x'],phase:'planning'},{planning_sha256:[b.brief_sha256],planning_key:'x',phase:'planning'}]){const store=memoryStorage(),m={...marker,...patch};store.setItem(prefix+b.key,JSON.stringify(m));const f=harness({realFixture:real,preselected:true,storage:store});await tick();assert.equal(f.handle.state().recovery.status,'unavailable');assert.equal(f.writes.length,0);assert.equal(store.length,1);}
  const store=memoryStorage();store.setItem(prefix+b.key,JSON.stringify({...marker,workflow_head_sha256:'f'.repeat(64)}));const f=harness({realFixture:real,preselected:true,storage:store});await tick();const result=await f.handle.reconcile(f.binding);assert.equal(result.status,'unknown');assert.equal(result.code,'original-head-not-verified');assert.equal(store.length,1);
 });

 test('saved preference superseded by a later one is explicit and retained',async()=>{
  const store=memoryStorage(),a='a'.repeat(64),old={status:'saved',key:'old-key',mode:'direction-advice',human_selection:'pending',execution_authorized:false,artifact_ref:'old',request_sha256:'b'.repeat(64),intent_sha256:'2'.repeat(64),submission_sha256:'3'.repeat(64),advisory_manifest_sha256:'4'.repeat(64)};
  const marker={schema:1,project_ref:'project-a',input_version:1,revision:1,brief_sha256:a,delivery_manifest_sha256:'c'.repeat(64),workflow_head_sha256:'d'.repeat(64),snapshot_sha256:'e'.repeat(64),kind:'stage2-direction-intent',key:old.key,request_sha256:old.request_sha256,phase:'stage2',planning_key:null,planning_sha256:null};store.setItem('ara.stage2.pending.v1.project-a.old-key',JSON.stringify(marker));
  const newer={...old,key:'new-key',request_sha256:'f'.repeat(64)},f=harness({storage:store,existingIntent:newer,historyTransform:h=>({...h,actions:[{...old,project_ref:'project-a',kind:'stage2-direction-intent'}]})});await tick();const result=await f.handle.reconcile({...f.binding,revision:2});assert.equal(result.status,'superseded');assert.equal(store.length,1);assert.equal(f.writes.length,0);assert.equal((await f.handle.acknowledgeTerminal({...f.binding,revision:2},old.key)).code,'original-preference-binding-unavailable');assert.equal(f.handle.dispose(),false);
  const request_binding=Object.fromEntries(['input_version','brief_sha256','delivery_manifest_sha256','workflow_head_sha256','snapshot_sha256'].map(k=>[k,marker[k]]));
  const g=harness({storage:store,existingIntent:newer,historyTransform:h=>({...h,actions:[{...old,project_ref:'project-a',kind:'stage2-direction-intent',request_binding},{...newer,project_ref:'project-a',kind:'stage2-direction-intent'}]})});await tick();const ack=await g.handle.acknowledgeTerminal({...g.binding,revision:2},old.key);assert.equal(ack.status,'acknowledged');assert.equal(ack.code,'preference-replaced');assert.equal(store.length,0);assert.equal(g.writes.length,0);
 });
 test('verified failed planning is distinguished from execution unknown and never cleared',async()=>{
  const real=require('./fixtures/stage2_formal_selection_service_saved.json'),b=real.body,flags={execution_authorized:false,evaluation_calls_authorized:false,formal_execution_enabled:false,external_claim_ready:false,usable_for_formal_pairing:false};
  for(const outcome of ['failed','execution-unknown']) {const store=memoryStorage(),m={schema:1,project_ref:real.before.project_ref,input_version:b.input_version,revision:b.revision,brief_sha256:b.brief_sha256,delivery_manifest_sha256:b.delivery_manifest_sha256,workflow_head_sha256:b.workflow_head_sha256,snapshot_sha256:b.snapshot_sha256,kind:'stage2-select',key:b.key,request_sha256:real.post.request_sha256,phase:'planning',planning_key:'plan-key',planning_sha256:'1'.repeat(64)};store.setItem('ara.stage2.pending.v1.'+m.project_ref+'.'+m.key,JSON.stringify(m));
   const plan={...flags,project_ref:m.project_ref,input_version:m.input_version,revision:real.after.revision,brief_sha256:m.brief_sha256,submission_in_progress:false,default_request:{key:m.planning_key,request_sha256:m.planning_sha256},selection_request_sha256:m.request_sha256,job:{...flags,project_ref:m.project_ref,key:m.planning_key,request_sha256:m.planning_sha256,status:'completed',outcome}};
   const f=harness({realFixture:real,preselected:true,storage:store,planOverride:plan});await tick();const result=await f.handle.reconcile(f.binding);assert.equal(result.status,outcome==='failed'?'failed':'unknown');assert.equal(store.length,1);assert.equal(f.writes.length,0);assert.equal(f.handle.dispose(),false);
  }
 });

 test('explicit acknowledgement under lock clears only the proven failed marker',async()=>{
  const real=require('./fixtures/stage2_formal_selection_service_saved.json'),b=real.body,flags={execution_authorized:false,evaluation_calls_authorized:false,formal_execution_enabled:false,external_claim_ready:false,usable_for_formal_pairing:false},store=memoryStorage();
  const m={schema:1,project_ref:real.before.project_ref,input_version:b.input_version,revision:b.revision,brief_sha256:b.brief_sha256,delivery_manifest_sha256:b.delivery_manifest_sha256,workflow_head_sha256:b.workflow_head_sha256,snapshot_sha256:b.snapshot_sha256,kind:'stage2-select',key:b.key,request_sha256:real.post.request_sha256,phase:'planning',planning_key:'plan-key',planning_sha256:'1'.repeat(64)};
  const prefix='ara.stage2.pending.v1.'+m.project_ref+'.';store.setItem(prefix+m.key,JSON.stringify(m));const other={...m,key:'other-key'};store.setItem(prefix+other.key,JSON.stringify(other));
  const plan={...flags,project_ref:m.project_ref,input_version:m.input_version,revision:real.after.revision,brief_sha256:m.brief_sha256,submission_in_progress:false,default_request:{key:m.planning_key,request_sha256:m.planning_sha256},selection_request_sha256:m.request_sha256,job:{...flags,project_ref:m.project_ref,key:m.planning_key,request_sha256:m.planning_sha256,status:'completed',outcome:'failed'}};
  const f=harness({realFixture:real,preselected:true,storage:store,planOverride:plan});await tick();assert.equal(f.handle.pendingActions().length,2);assert.equal((await f.handle.reconcile(f.binding)).code,'multiple-pending');
  const result=await f.handle.acknowledgeTerminal(f.binding,m.key);assert.equal(result.status,'acknowledged');assert.equal(result.code,'planning-completed-failed');assert.equal(store.length,1);assert.equal(store.getItem(prefix+other.key),JSON.stringify(other));assert.equal(f.handle.state().recovery.status,'unknown');assert.equal(f.handle.dispose(),false);assert.equal(f.writes.length,0);
 });
 test('explicit acknowledgement cannot clear execution unknown',async()=>{
  const real=require('./fixtures/stage2_formal_selection_service_saved.json'),b=real.body,flags={execution_authorized:false,evaluation_calls_authorized:false,formal_execution_enabled:false,external_claim_ready:false,usable_for_formal_pairing:false},store=memoryStorage();
  const m={schema:1,project_ref:real.before.project_ref,input_version:b.input_version,revision:b.revision,brief_sha256:b.brief_sha256,delivery_manifest_sha256:b.delivery_manifest_sha256,workflow_head_sha256:b.workflow_head_sha256,snapshot_sha256:b.snapshot_sha256,kind:'stage2-select',key:b.key,request_sha256:real.post.request_sha256,phase:'planning',planning_key:'plan-key',planning_sha256:'1'.repeat(64)};store.setItem('ara.stage2.pending.v1.'+m.project_ref+'.'+m.key,JSON.stringify(m));
  const plan={...flags,project_ref:m.project_ref,input_version:m.input_version,revision:real.after.revision,brief_sha256:m.brief_sha256,submission_in_progress:false,default_request:{key:m.planning_key,request_sha256:m.planning_sha256},selection_request_sha256:m.request_sha256,job:{...flags,project_ref:m.project_ref,key:m.planning_key,request_sha256:m.planning_sha256,status:'completed',outcome:'execution-unknown'}};
  const f=harness({realFixture:real,preselected:true,storage:store,planOverride:plan});await tick();const result=await f.handle.acknowledgeTerminal(f.binding,m.key);assert.equal(result.status,'unknown');assert.equal(store.length,1);assert.equal(f.writes.length,0);
 });

 test('confirmation interrupted by page change leaves all markers intact',async()=>{
  const real=require('./fixtures/stage2_formal_selection_service_saved.json'),b=real.body,store=memoryStorage();const m={schema:1,project_ref:real.before.project_ref,input_version:b.input_version,revision:b.revision,brief_sha256:b.brief_sha256,delivery_manifest_sha256:b.delivery_manifest_sha256,workflow_head_sha256:b.workflow_head_sha256,snapshot_sha256:b.snapshot_sha256,kind:'stage2-select',key:b.key,request_sha256:real.post.request_sha256,phase:'planning',planning_key:'plan-key',planning_sha256:'1'.repeat(64)};store.setItem('ara.stage2.pending.v1.'+m.project_ref+'.'+m.key,JSON.stringify(m));
  const f=harness({realFixture:real,preselected:true,storage:store,holdHistory:true});await tick();const pending=f.handle.acknowledgeTerminal(f.binding,m.key);await tick();f.setCurrent(false);f.releaseHistory();assert.equal((await pending).code,'current-binding-changed');assert.equal(store.length,1);assert.equal(f.writes.length,0);
 });

 test('two tabs share the project lock and cannot acknowledge while POST is in flight',async()=>{
  const store=memoryStorage(),locks=memoryLocks(),first=harness({storage:store,locks});await tick();first.selectRadio();first.form();first.waitSelect();const sending=first.els.get('choice').onsubmit({preventDefault(){},submitter:first.els.get('submit')});for(let i=0;i<500 && first.writes.length===0;i++)await tick();assert.equal(first.writes.length,1);assert.equal(store.length,1);const raw=[...store.values.entries()];
  const second=harness({storage:store,locks});await tick();const key=second.handle.pendingActions()[0].key,result=await second.handle.acknowledgeTerminal(second.binding,key);assert.equal(result.code,'project-lock-busy');assert.deepEqual([...store.values.entries()],raw);assert.equal(second.writes.length,0);first.release();await sending;assert.equal(first.writes.length,1);
 });
 test('missing project Web Locks disables submit and recovery without deleting data',async()=>{
  const store=memoryStorage(),f=harness({storage:store,noLocks:true});await tick();f.selectRadio();f.form();const sent=await f.els.get('choice').onsubmit({preventDefault(){},submitter:f.els.get('submit')});assert.equal(sent.code,'project-lock-unavailable');assert.equal(f.writes.length,0);assert.equal(store.length,0);assert.match(f.els.get('status').textContent,/不支援專案交易鎖/);
  const checked=await f.handle.reconcile(f.binding);assert.equal(checked.code,'project-lock-unavailable');assert.equal(f.writes.length,0);
 });

 test('read-only verified recovery clears only its selected marker when multiple are pending',async()=>{
  const real=require('./fixtures/stage2_formal_selection_service_saved.json'),b=real.body,store=memoryStorage(),m={schema:1,project_ref:real.before.project_ref,input_version:b.input_version,revision:b.revision,brief_sha256:b.brief_sha256,delivery_manifest_sha256:b.delivery_manifest_sha256,workflow_head_sha256:b.workflow_head_sha256,snapshot_sha256:b.snapshot_sha256,kind:'stage2-select',key:b.key,request_sha256:real.post.request_sha256,phase:'stage2',planning_key:null,planning_sha256:null};
  const prefix='ara.stage2.pending.v1.'+m.project_ref+'.',other={...m,key:'other-key'};store.setItem(prefix+m.key,JSON.stringify(m));store.setItem(prefix+other.key,JSON.stringify(other));const f=harness({realFixture:real,preselected:true,storage:store});await tick();const result=await f.handle.reconcile(f.binding,m.key);assert.equal(result.status,'verified');assert.equal(store.length,1);assert.equal(store.getItem(prefix+other.key),JSON.stringify(other));assert.equal(f.handle.state().recovery.status,'unknown');assert.equal(f.handle.dispose(),false);assert.equal(f.writes.length,0);
 });

 test('embedded tentative save and start dispatches prepare and run once',async()=>{
  const f=harness({intentReady:true});await tick();const box=descendants(f.els.get('cards')).find(n=>n.name==='tentative-direction');box.checked=true;box.onchange();f.els.get('intent-message').value='Synthetic direction';f.els.get('intent-confirmed').checked=true;
  await f.els.get('direction-intent').onsubmit({preventDefault(){},submitter:f.els.get('intent-start')});assert.equal(f.writes.filter(x=>x.url.endsWith('/stage2/direction-intent')).length,1);assert.equal(f.writes.filter(x=>x.url.endsWith('/stage3/planning/prepare')).length,1);assert.equal(f.writes.filter(x=>x.url.endsWith('/stage3/planning/run')).length,1);assert.equal(f.navigations.length,1);const marker=JSON.parse([...f.store.values.values()][0]);assert.equal(marker.phase,'planning');assert.equal(marker.planning_key,'plan-key');assert.equal(marker.planning_sha256,'1'.repeat(64));
 });
 test('embedded tentative lost prepare response retains original marker and cannot resubmit',async()=>{
  const f=harness({intentReady:true,losePrepareResponse:true});await tick();const box=descendants(f.els.get('cards')).find(n=>n.name==='tentative-direction');box.checked=true;box.onchange();f.els.get('intent-message').value='Synthetic direction';f.els.get('intent-confirmed').checked=true;
  await f.els.get('direction-intent').onsubmit({preventDefault(){},submitter:f.els.get('intent-start')});const before=[...f.store.values.entries()];assert.equal(f.writes.filter(x=>x.url.endsWith('/stage3/planning/prepare')).length,1);assert.equal(f.writes.filter(x=>x.url.endsWith('/stage3/planning/run')).length,0);const marker=JSON.parse(before[0][1]);assert.equal(marker.phase,'planning');assert.equal(marker.planning_key,'plan-key');assert.equal(marker.planning_sha256,null);assert.equal(f.handle.state().recovery.status,'unknown');
  await f.els.get('direction-intent').onsubmit({preventDefault(){},submitter:f.els.get('intent-start')});assert.equal(f.writes.length,2);assert.deepEqual([...f.store.values.entries()],before);assert.equal(f.navigations.length,0);
 });

}
