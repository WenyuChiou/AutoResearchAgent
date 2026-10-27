/* Synthetic DOM + authored API responses; no network, human choice or model. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(process.argv[2],'utf8');
class Element { constructor(tag='div'){this.tagName=tag.toUpperCase();this.children=[];this.dataset={};this.value='';this.checked=false;this.hidden=false;this.disabled=false;this._text='';} append(...xs){this.children.push(...xs);if(this.tagName==='SELECT'&&!this.value&&xs[0])this.value=xs[0].value||xs[0].textContent;} replaceChildren(...xs){this.children=xs;} scrollIntoView(){} get textContent(){return this._text+this.children.map(x=>x.textContent||'').join('');} set textContent(x){this._text=String(x);this.children=[];} }
const tick=()=>new Promise(r=>setImmediate(r));
const ack='a'.repeat(64),requestHash='b'.repeat(64),brief='c'.repeat(64);
function fixture(options={}) {
 const ids=['language','project','project-context','cards','planning','planning-link','return-cards','planning-summary','choice','submit','submit-and-start','receipt','status','planning-input','actor','message','rationale','conditions','unresolved','confirmed'];
 const els=new Map(ids.map(id=>{const e=new Element(id==='project'||id==='language'?'select':'div');e.id=id;return [id,e];}));
 els.get('language').value='en';els.get('submit').dataset.i18n='submit';els.get('submit-and-start').dataset.i18n='saveAndStart';
 const chosen={value:'candidate',dataset:{version:'1'}},calls=[];let selected=false,prepared=false,dispatched=0,uuids=0,selects=0;
 const version=options.version ?? 1;
 const card={candidate_id:'candidate',candidate_version:1,candidate_question:'Unrelated synthetic question',suggested_approach:'A generic method',closest_prior_work:{review:null},contribution:[],scientific_questions:[],requirements:[],unmapped_resources:[],limitations:[],alternatives:[],next_checks:[]};
 const selection=ref=>({project_ref:ref,input_version:version,revision:selected?2:1,brief_sha256:brief,delivery_manifest_sha256:'d'.repeat(64),workflow_head_sha256:'e'.repeat(64),snapshot_sha256:'f'.repeat(64),eligible:options.empty?[]:[{candidate_id:'candidate',candidate_version:1}],selection_status:selected?'recorded':'pending',selection_receipt:selected?{request_sha256:options.badSelectionAck?'f'.repeat(64):ack}:null,planning_status:'pending',planning_input:selected?{questions:[],legacy_candidates:[],selection_conditions:['kept'],unresolved:['unknown']}:null,cards:{cards:[card]}});
 const request=()=>({key:'server-original-job-key',input_version:version,revision:2,brief_sha256:brief,selection_request_sha256:ack,...(prepared?{request_sha256:requestHash}:{})});
 const planning=ref=>({project_ref:ref,input_version:version,revision:2,brief_sha256:brief,selection_status:'recorded',selection_request_sha256:options.badPlanningAck?'f'.repeat(64):ack,planning_configured:true,default_request:request(),submission_in_progress:false,submission_error:null,job:options.existingJob?{status:'completed',outcome:'saved'}:prepared?{status:'intent-recorded',request_sha256:options.badPreparedHash?'f'.repeat(64):requestHash}:null,...(options.driftAfterPrepare&&prepared?{input_version:typeof version==='number'?String(version):1}:{})});
 const response=v=>({ok:true,json:async()=>v});
 const document={documentElement:{},getElementById:id=>els.get(id),querySelectorAll:()=>[els.get('submit'),els.get('submit-and-start')],querySelector:()=>chosen,createElement:t=>new Element(t),createTextNode:text=>({textContent:text})};
 const fetch=async(url,opts)=>{
  const body=opts?.body?JSON.parse(opts.body):null;calls.push({url,method:opts?.method,body});
  if(url==='/api/projects')return response({projects:[]});
  const match=url.match(/^\/api\/projects\/([AB])\/(.*)$/);assert.ok(match,'unexpected URL '+url);const [,ref,path]=match;
  if(path==='stage2/selection')return response(selection(ref));
  if(path==='stage2/select'){
   selects++;assert.equal(body.key,'original-selection-key');assert.deepEqual(body.decision.conditions,['condition one','condition two']);assert.deepEqual(body.decision.unresolved,['unknown one','unknown two']);
   if(options.selectError || (options.loseFirstSelect&&selects===1))throw new Error('saved selection response unavailable');
   selected=true;return response({status:options.selectUnknown?'execution-unknown':'saved',key:body.key,request_sha256:ack,planning_manifest_sha256:'d'.repeat(64),workflow_head_sha256:'e'.repeat(64)});
  }
  if(path==='stage3/planning')return response(planning(ref));
  if(path==='stage3/planning/prepare'){
   assert.equal(body.key,'server-original-job-key');assert.equal(body.selection_request_sha256,ack);
   if(options.prepareError)return {ok:false,json:async()=>({error:'prepare-failed'})};
   prepared=true;if(options.switchAfterPrepare){els.get('project').value='B';els.get('project').onchange();}return response({status:'intent-recorded',request_sha256:requestHash});
  }
  if(path==='stage3/planning/run'){
   assert.equal(body.key,'server-original-job-key');assert.equal(body.request_sha256,requestHash);assert.equal(body.confirmed,true);dispatched++;
   if(options.loseRun)throw new Error('run response lost');
   return response({submission_status:'accepted',dispatch_observed:false,execution_authorized:false,job:{status:'intent-recorded'}});
  }
  throw new Error('unexpected route '+path);
 };
 const context={document,window:{RESEARCH_PROJECTS:{credential:'synthetic-only',stage2_selection_projects:['A','B'],stage3_planning_projects:options.unconfigured?[]:['A','B']}},location:{hash:''},history:{replaceState(){}},fetch,crypto:{randomUUID(){uuids++;return 'original-selection-key';}},console};
 vm.runInNewContext(source,context);
 const submit=start=>{els.get('confirmed').checked=true;els.get('actor').value='fixture';els.get('message').value='Choose the displayed candidate version';els.get('rationale').value='Authored fixture';els.get('conditions').value='condition one\ncondition two';els.get('unresolved').value='unknown one\r\nunknown two';return els.get('choice').onsubmit({preventDefault(){},submitter:els.get(start?'submit-and-start':'submit')});};
 return {els,calls,submit,dispatched:()=>dispatched,uuids:()=>uuids};
}
let cases=0;
async function check(name,fn){await fn();cases++;console.log('ok '+cases+' '+name);}
async function main(){
 await check('passive reads and language changes never POST',async()=>{const h=fixture();await tick();for(const lang of ['en','zh-TW','zh-CN']){h.els.get('language').value=lang;h.els.get('language').onchange();assert.ok(h.els.get('submit-and-start').textContent.length);}assert.equal(h.calls.filter(x=>x.method==='POST').length,0);});
 await check('save-only preserves conditions and never prepares or dispatches',async()=>{const h=fixture();await tick();await h.submit(false);assert.equal(h.dispatched(),0);assert.equal(h.calls.filter(x=>x.url.includes('/stage3/')).length,0);assert.equal(h.els.get('choice').hidden,true);});
 await check('one click commits then prepares and starts once, retaining typed versions and keys',async()=>{for(const version of [1,'1']){const h=fixture({version});await tick();const first=h.submit(true);await h.submit(true);await first;assert.equal(h.dispatched(),1);assert.equal(h.uuids(),1);assert.deepEqual(h.calls.filter(x=>x.url!=='/api/projects').map(x=>x.url.replace('/api/projects/A/','')),['stage2/selection','stage2/select','stage2/selection','stage3/planning','stage3/planning/prepare','stage3/planning','stage3/planning/run']);assert.match(h.els.get('status').textContent,/accepted/);assert.doesNotMatch(h.els.get('status').textContent,/completed/);}});
 await check('zero recommendations and unconfigured planning add no dispatch',async()=>{const h=fixture({empty:true});await tick();assert.equal(h.els.get('choice').hidden,true);assert.equal(h.dispatched(),0);const u=fixture({unconfigured:true});await tick();await u.submit(true);assert.equal(u.calls.filter(x=>x.method==='POST').length,0);});
 await check('failed or unknown select never reaches planning',async()=>{for(const opts of [{selectError:true},{selectUnknown:true}]){const h=fixture(opts);await tick();await h.submit(true);assert.equal(h.calls.filter(x=>x.url.includes('/stage3/')).length,0);}});
 await check('explicit retry reuses original selection key',async()=>{const h=fixture({loseFirstSelect:true});await tick();await h.submit(true);await h.submit(true);assert.equal(h.calls.filter(x=>x.url.endsWith('/stage2/select')).length,2);assert.equal(h.uuids(),1);assert.equal(h.dispatched(),1);});
 await check('wrong selection ack or planning ack refuses continuation',async()=>{for(const opts of [{badSelectionAck:true},{badPlanningAck:true}]){const h=fixture(opts);await tick();await h.submit(true);assert.equal(h.dispatched(),0);assert.equal(h.calls.filter(x=>x.url.endsWith('/prepare')).length,0);}});
 await check('existing job is inspected without a new prepare or run',async()=>{const h=fixture({existingJob:true});await tick();await h.submit(true);assert.equal(h.calls.filter(x=>x.url.endsWith('/prepare')).length,0);assert.equal(h.dispatched(),0);});
 await check('prepare failure or changed prepared hash/version never runs',async()=>{for(const opts of [{prepareError:true},{badPreparedHash:true},{driftAfterPrepare:true}]){const h=fixture(opts);await tick();await h.submit(true);assert.equal(h.dispatched(),0);}});
 await check('switching project during preparation blocks delayed run',async()=>{const h=fixture({switchAfterPrepare:true});await tick();await h.submit(true);await tick();assert.equal(h.dispatched(),0);assert.equal(h.calls.some(x=>x.method==='POST'&&x.url.includes('/B/')),false);});
 await check('lost run response never automatically retries or reports completion',async()=>{const h=fixture({loseRun:true});await tick();await h.submit(true);await tick();assert.equal(h.dispatched(),1);assert.match(h.els.get('status').textContent,/run response lost/);assert.doesNotMatch(h.els.get('status').textContent,/completed/);});
 console.log(JSON.stringify({kind:'synthetic-selection-oneclick',cases,failures:0,network:false,model_calls:0,real_human_selection:false,execution_authorized:false}));
}
main().catch(e=>{console.error(e);process.exitCode=1;});
