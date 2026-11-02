/* Deterministic synthetic UI checks: no browser, Host, credentials or model. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),test=require('node:test'),{createHash}=require('node:crypto');
const source=fs.readFileSync(path.join(__dirname,'v9-stage3-feedback.js'),'utf8');
const clone=value=>JSON.parse(JSON.stringify(value));
const escape=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const settle=()=>new Promise(resolve=>setImmediate(resolve));
function fixture(request){
 const basis={project_ref:'alpha',input_version:'imported-v1',revision:3,brief_sha256:'a'.repeat(64)};
 const binding={...basis,parent_plan_manifest_sha256:'b'.repeat(64),parent_plan_sha256:'c'.repeat(64),plan_request_sha256:'d'.repeat(64)};
 const plan={kind:'Stage3DirectionPlanningResult',markdown:'Original Markdown only.',question_plans:[{question_ref:'q1',method:'Original method',materials:'Unknown access',design:'Original design',unknowns:['Original limitation']},{question_ref:'q2',method:'Second method',unknowns:['Second unknown']}]};
 const view={...basis,job:{outcome:'saved',request_sha256:binding.plan_request_sha256,plan_manifest_sha256:binding.parent_plan_manifest_sha256},plan,direction_context:{questions:[{question_ref:'q1',text:'Question one'},{question_ref:'q2',text:'Question two'}]},feedback:{kind:'ProjectStage3PlanningFeedbackView',schema_version:1,binding,records:[]}};
 const listeners={},calls=[],owned=new Set(),state={ref:'alpha',epoch:1},app={page:'workspace',stage:3,lang:'en',el:{contains:element=>owned.has(element),querySelector:()=>null}};
 let serial=0,paints=0;
 const ctx={Map,TextEncoder,crypto:{randomUUID:()=>`synthetic-key-${++serial}`},apps:[app],rt:state,v93:{view,basis},v93Identity:()=>state.ref===basis.project_ref?basis:null,
  v93Matches:(a,b)=>!!a&&!!b&&['project_ref','input_version','revision','brief_sha256'].every(k=>a[k]===b[k]),
  v93SavedPlanSummary:()=>'<section class="original">Original method; Original limitation</section>',laterStage:()=>'<main><div class="n9-page-actions"></div>'+ ctx.v93SavedPlanSummary(ctx.v93.view)+'<details class="n9-plan-graph"><summary>Graph</summary></details></main>',
  v7BeforeRender:()=>{},v7AfterRender:()=>{},rl:(zh,en,tw)=>app.lang==='en'?en:app.lang==='tw'?tw:zh,rx:escape,projectPath:(ref,tail)=>'/api/projects/'+encodeURIComponent(ref)+'/'+tail,
  livePaint:()=>{paints++;},liveRequest:async(url,body)=>{calls.push({url,body:clone(body??null)});return request?request(url,body):response(body,url.endsWith('/comment')?'comment':'revision');},
  document:{body:{},activeElement:null,addEventListener:(type,fn)=>(listeners[type]??=[]).push(fn)}};
 function response(body,kind='comment',extra={}){
  const record={kind,binding:clone(binding),request:clone(body),input_source:'project-host-user-submission',native_message:false,model_generated:false,execution_authorized:false};
  if(kind==='comment')Object.assign(record,{text:body.text,question_ref:body.question_ref});
  else {const parent=ctx.v94fRevision(getState()),number=parent?parent.record.revision_number+1:2,revised=clone(parent?.record.plan||plan);for(const change of body.changes)revised.question_plans.find(q=>q.question_ref===change.question_ref)[change.field]=change.value;Object.assign(record,{revision_number:number,parent_revision:clone(body.parent_revision),comments:clone(body.comments),changes:clone(body.changes),plan:revised,authoring_mode:'manual-planning-draft',original_markdown_preserved:true});}
  return {receipt_sha256:createHash('sha256').update(kind+body.key).digest('hex'),record,replayed:false,...extra};
 }
 vm.createContext(ctx);vm.runInContext(source,ctx);
 function getState(){return ctx.v94fState(ctx.v94fContext(app));}
 function control(field,value){const element={dataset:{v94fControl:field},value,closest:()=>element};owned.add(element);return element;}
 async function dispatch(type,element){for(const listener of listeners[type]||[])await listener({target:element,preventDefault(){this.prevented=true;}});await settle();}
 return {ctx,app,state,basis,binding,view,plan,calls,listeners,owned,getState,control,dispatch,response,html:()=>ctx.laterStage(app),paints:()=>paints};
}
test('loading and rendering expose native controls with no write or model request',()=>{
 const f=fixture();for(let i=0;i<3;i++){f.html();f.ctx.v7AfterRender(f.app);}
 assert.deepEqual(f.calls,[]);assert.match(f.html(),/Comments and manual drafts/);assert.match(f.html(),/<form data-v94f-form="comment">/);
 assert.match(f.html(),/<label[^>]*>Comment<textarea/);assert.match(f.html(),/<option value="" selected>Original plan v1/);
 assert.doesNotMatch(f.html(),/<details[^>]*\bopen(?:\s|>)/);
 assert.doesNotMatch(source,/localStorage|sessionStorage|fetch\(|\/prepare|\/run|\.credential/);
});
test('native submit and keyboard form path send exact scoped user text once',async()=>{
 const f=fixture(),text='<script>inert()</script> Preserve this comment.\nSecond line.';
 await f.dispatch('input',f.control('commentText',text));await f.dispatch('change',f.control('commentQuestion','q1'));
 const form={dataset:{v94fForm:'comment'},closest:()=>form};f.owned.add(form);await f.dispatch('submit',form);
 assert.equal(f.calls.length,1);assert.equal(f.calls[0].url,'/api/projects/alpha/stage3/planning/comment');
 const body=f.calls[0].body;assert.equal(body.text,text);assert.equal(body.question_ref,'q1');assert.equal(body.input_version,'imported-v1');assert.equal(body.parent_plan_sha256,f.binding.parent_plan_sha256);
 assert.equal(Object.hasOwn(body,'project_ref'),false);assert.equal(Object.hasOwn(body,'confirmed'),false);
 assert.equal(f.getState().records.length,1);assert.match(f.html(),/&lt;script&gt;/);assert.doesNotMatch(f.html(),/<script>/);assert.match(f.html(),/Question one/);
});
test('response loss keeps the exact operation and explicit retry reuses its key and bytes',async()=>{
 let attempts=0,f;f=fixture(async(url,body)=>{if(++attempts===1)throw Error('response lost');return f.response(body,'comment',{replayed:true});});
 const state=f.getState();state.commentText='Keep the source limit';await f.ctx.v94fSubmit(f.app,'comment');
 assert.ok(state.pending);assert.match(f.html(),/unconfirmed outcome/);const first=clone(f.calls[0]);
 f.html();f.ctx.v7AfterRender(f.app);await f.ctx.v94fSubmit(f.app,'comment');assert.equal(f.calls.length,1,'no automatic or duplicate new submission');
 await f.ctx.v94fSend(f.app,true);assert.deepEqual(f.calls[1],first);assert.equal(state.pending,null);assert.equal(state.records.length,1);assert.match(f.html(),/receipt for this operation was recovered/);
});
test('explicit receipt check is one GET and recovers a committed response without POST',async()=>{
 let stored,f;f=fixture(async(url,body)=>{if(body){stored=f.response(body);throw Error('lost after commit');}return {...f.view,feedback:{...f.view.feedback,records:[stored]}};});
 f.getState().commentText='Stored once';await f.ctx.v94fSubmit(f.app,'comment');await f.ctx.v94fInspect(f.app);
 assert.equal(f.calls.length,2);assert.equal(f.calls[1].body,null);assert.equal(f.calls[1].url,'/api/projects/alpha/stage3/planning');
 assert.equal(f.getState().pending,null);assert.equal(f.getState().records.length,1);
});
test('receipt check without a match stays uncertain and never retries automatically',async()=>{
 let f;f=fixture(async(url,body)=>{if(body)throw Error('connection lost');return f.view;});
 f.getState().commentText='Uncertain';await f.ctx.v94fSubmit(f.app,'comment');await f.ctx.v94fInspect(f.app);
 assert.ok(f.getState().pending);assert.equal(f.getState().status,'absent');f.html();assert.equal(f.calls.length,2);
});
test('manual revision binds comment and parent receipts while preserving original plan and Markdown',async()=>{
 const f=fixture(),original=JSON.stringify(f.plan),state=f.getState();state.commentText='Clarify method';state.commentQuestion='q1';await f.ctx.v94fSubmit(f.app,'comment');f.html();
 state.value='User-authored method';await f.ctx.v94fSubmit(f.app,'revise');
 let body=f.calls[1].body;assert.equal(body.parent_revision,null);assert.deepEqual(body.comments,[{key:f.calls[0].body.key,sha256:state.records[0].receipt_sha256}]);assert.deepEqual(body.changes,[{question_ref:'q1',field:'method',value:'User-authored method'}]);
 assert.equal(JSON.stringify(f.plan),original);assert.match(f.html(),/Manual planning draft v2/);assert.match(f.html(),/User-authored method/);assert.match(f.html(),/Original Markdown \(unchanged\)/);assert.match(f.html(),/Original limitation/);assert.match(f.html(),/<details class="n9f-original">/);
 const parent=f.ctx.v94fRevision(state);state.value='Second manual edit';await f.ctx.v94fSubmit(f.app,'revise');body=f.calls[2].body;
 assert.equal(body.parent_revision.key,parent.record.request.key);assert.equal(body.parent_revision.sha256,parent.receipt_sha256);assert.match(f.html(),/Manual planning draft v3/);
 state.selected='';assert.doesNotMatch(f.html(),/data-v94f-manual/);assert.match(f.html(),/Original method/);
});
test('question-specific saved comments open their matching editable question',()=>{
 const f=fixture(),body={key:'comment-q2',...Object.fromEntries(Object.entries(f.binding).filter(([k])=>k!=='project_ref')),text:'Only question two',question_ref:'q2'};
 f.view.feedback.records=[f.response(body)];const html=f.html();assert.equal(f.getState().revisionQuestion,'q2');assert.match(html,/<form data-v94f-form="revise">/);assert.match(html,/Second method/);
});
test('UTF-8 text and complete JSON limits reject before sending',async()=>{
 const f=fixture(),state=f.getState();state.commentText='界'.repeat(601);await f.ctx.v94fSubmit(f.app,'comment');assert.match(state.error,/1800 UTF-8/);assert.equal(f.calls.length,0);assert.equal(state.pending,null);
 state.commentText='\u0001'.repeat(700);await f.ctx.v94fSubmit(f.app,'comment');assert.match(state.error,/4096 UTF-8/);assert.equal(f.calls.length,0);assert.equal(state.pending,null);
});
test('old project, typed version and saved-plan changes never expose active forms or history',()=>{
 const f=fixture(),state=f.getState();state.commentText='Alpha-only draft';state.error='Alpha-only failure';
 f.state.ref='beta';assert.doesNotMatch(f.html(),/Alpha-only|data-v94f-panel/);f.state.ref='alpha';
 f.basis.input_version=1;assert.doesNotMatch(f.html(),/Alpha-only|data-v94f-panel/);f.basis.input_version='imported-v1';
 f.view.job.plan_manifest_sha256='0'.repeat(64);assert.doesNotMatch(f.html(),/Alpha-only|data-v94f-panel/);
});
test('late completion is retained only under its old binding and cannot repaint a different project',async()=>{
 let release,f;f=fixture((url,body)=>new Promise(resolve=>{release=()=>resolve(f.response(body));}));f.getState().commentText='Alpha only';
 const operation=f.ctx.v94fSubmit(f.app,'comment');await settle();const paints=f.paints();f.state.ref='beta';f.state.epoch++;release();await operation;
 assert.equal(f.paints(),paints);assert.doesNotMatch(f.html(),/Alpha only|data-v94f-panel/);assert.equal(f.calls.length,1);
});
test('foreign or mismatched receipt does not clear the pending operation',async()=>{
 let f;f=fixture(async(url,body)=>{const row=f.response(body);row.record.binding.project_ref='beta';return row;});
 f.getState().commentText='My comment';await f.ctx.v94fSubmit(f.app,'comment');assert.ok(f.getState().pending);assert.equal(f.getState().records.length,0);assert.match(f.html(),/receipt-differs/);
});
test('three locales, folded receipt details and focus restoration use native keyboard controls',()=>{
 const f=fixture();for(const [lang,label] of [['en','Save comment'],['zh','保存评语'],['tw','保存評語']]){f.app.lang=lang;assert.ok(f.html().includes(label));}
 const state=f.getState(),control=f.control('commentText','Typing'),focus=[];control.selectionStart=2;control.selectionEnd=4;f.ctx.document.activeElement=control;
 f.ctx.v7BeforeRender(f.app);f.ctx.document.activeElement=f.ctx.document.body;f.app.el.querySelector=()=>({focus:()=>focus.push('focus'),setSelectionRange:(a,b)=>focus.push([a,b])});f.ctx.v7AfterRender(f.app);
 assert.deepEqual(focus,['focus',[2,4]]);assert.equal(state.focus,null);
 const css=fs.readFileSync(path.join(__dirname,'v9-stage3-feedback.css'),'utf8');assert.match(css,/:focus-visible/);assert.match(css,/@media \(max-width: 600px\)/);
});
test('feedback controls stay labelled, details folded and responsive assets composed',()=>{
 const f=fixture(),body={key:'readability-comment',...Object.fromEntries(Object.entries(f.binding).filter(([k])=>k!=='project_ref')),text:'A saved supporting comment',question_ref:'q1'};
 f.view.feedback.records=[f.response(body)];
 for(const lang of ['en','zh','tw']){
  f.app.lang=lang;const html=f.html(),controls=[...html.matchAll(/<(select|textarea)\b[^>]*data-v94f-control="([^"]+)"[^>]*>/g)];
  assert.deepEqual(controls.map(match=>match[2]).sort(),['commentQuestion','commentText','field','revisionComment','revisionQuestion','selected','value'].sort());
  for(const [,tag,name] of controls)assert.match(html,new RegExp(`<label\\b[^>]*>[^<\\s][^<]*<${tag}\\b[^>]*data-v94f-control="${name}"[^>]*>`),`${lang}: ${name} needs a visible wrapping label`);
  assert.match(html,/<p role="status" aria-live="polite">/);
  assert.equal((html.match(/<fieldset/g)||[]).length,2);
  assert.equal((html.match(/<fieldset[^>]*><legend>[^<]+<\/legend>/g)||[]).length,2);
  assert.doesNotMatch(html,/<details[^>]*\bopen(?:\s|>)/);
 }
 const css=fs.readFileSync(path.join(__dirname,'v9-stage3-feedback.css'),'utf8');
 assert.match(css,/\.n9f-panel\s*\{[^}]*min-width:\s*0/,'panel can shrink inside the host layout');
 assert.match(css,/\.n9f-panel\s*\{[^}]*padding:\s*clamp\(1rem,/,'outer padding keeps a one-rem minimum');
 assert.match(css,/\.n9f-panel\s*\{[^}]*overflow-wrap:\s*anywhere/,'long question titles and status text may wrap');
 assert.match(css,/\.n9f-panel,\s*\.n9f-panel \*/,'panel padding participates in border-box sizing');
 assert.match(css,/\.n9f-panel fieldset\s*\{[^}]*padding:\s*1rem/);
 assert.match(css,/\.n9f-details,\s*\.n9f-original\s*\{[^}]*overflow-wrap:\s*anywhere/);
 assert.match(css,/@media\s*\(max-width:\s*600px\)\s*\{\s*\.n9f-details dl\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)/);
 const runner=fs.readFileSync(path.join(__dirname,'run_v9.py'),'utf8'),moduleList=runner.match(/MODULES\s*=\s*\(([^)]*)\)/);
 assert.ok(moduleList,'V9 declares its ordered module composition');
 const modules=[...moduleList[1].matchAll(/'([^']+\.js)'/g)].map(match=>match[1]);
 assert.equal(modules.filter(name=>name==='v9-stage3-feedback.js').length,1);
 assert.ok(modules.indexOf('v9-stage3-feedback.js')>modules.indexOf('v9-stage3-bridge.js'));
 assert.ok(modules.indexOf('v9-stage3-bridge.js')>=0);
 assert.ok(runner.includes("HERE/'v9-stage3-feedback.css'"));
});

test('only exact prewrite refusals unlock editing through an explicit native control',async()=>{
 for(const [code,status] of [['stage3-feedback-response-bound',413],['stage3-feedback-plan-bound',413],['stage3-feedback-record-bound',409]]){
  let attempt=0,f;f=fixture(async(url,body)=>{if(++attempt===1)throw Object.assign(Error(code),{status});return f.response(body);});
  const state=f.getState();state.commentText='Original refused text';await f.ctx.v94fSubmit(f.app,'comment');
  const original=clone(f.calls[0]);assert.ok(state.pending);assert.match(f.html(),/data-v94f-edit-refused/);
  await f.dispatch('input',f.control('commentText','Premature edit'));assert.equal(state.commentText,'Original refused text');
  const button={closest:()=>button,hasAttribute:name=>name==='data-v94f-edit-refused'};f.owned.add(button);
  await f.dispatch('click',button);assert.equal(state.pending,null);assert.deepEqual(clone(state.lastRefused.body),original.body);assert.equal(f.calls.length,1);
  await f.dispatch('input',f.control('commentText','Shorter revised text'));await f.ctx.v94fSubmit(f.app,'comment');
  assert.equal(f.calls.length,2);assert.notEqual(f.calls[1].body.key,original.body.key);assert.equal(f.calls[1].body.text,'Shorter revised text');assert.equal(state.records.length,1);
 }
});
test('unknown transport and wire errors keep the original key and prohibit refused-edit recovery',async()=>{
 for(const error of [Error('connection lost'),Object.assign(Error('response-too-large'),{status:413}),Object.assign(Error('stage3-feedback-plan-bound'),{status:500}),Object.assign(Error('stage3-feedback-plan-bound'),{status:413,receipt:{status:'saved'}})]){
  const f=fixture(async()=>{throw error;}),state=f.getState();state.commentText='Uncertain text';await f.ctx.v94fSubmit(f.app,'comment');
  const pending=clone(state.pending);assert.doesNotMatch(f.html(),/data-v94f-edit-refused/);
  const button={closest:()=>button,hasAttribute:name=>name==='data-v94f-edit-refused'};f.owned.add(button);await f.dispatch('click',button);
  assert.deepEqual(clone(state.pending),pending);assert.equal(f.calls.length,1);assert.equal(state.lastRefused,undefined);
 }
});
test('a later uncertain retry cannot inherit a previous definitive refusal',async()=>{
 let count=0;const f=fixture(async()=>{if(++count===1)throw Object.assign(Error('stage3-feedback-response-bound'),{status:413});throw Error('response lost');});
 const state=f.getState();state.commentText='Keep this operation';await f.ctx.v94fSubmit(f.app,'comment');assert.match(f.html(),/data-v94f-edit-refused/);
 await f.ctx.v94fSend(f.app,true);assert.deepEqual(f.calls[1],f.calls[0]);assert.ok(state.pending);assert.doesNotMatch(f.html(),/data-v94f-edit-refused/);
});

test('manual editor disclosure survives field selection without any request',async()=>{
 const f=fixture(),body={key:'editor-comment',...Object.fromEntries(Object.entries(f.binding).filter(([k])=>k!=='project_ref')),text:'A supporting comment',question_ref:'q1'};
 f.view.feedback.records=[f.response(body)];f.html();
 const editor={open:true,matches:selector=>selector==='[data-v94f-editor]'};f.owned.add(editor);
 await f.dispatch('toggle',editor);
 assert.match(f.html(),/<details[^>]*data-v94f-editor[^>]*\bopen(?:\s|>)/);
 await f.dispatch('change',f.control('field','design'));
 assert.match(f.html(),/<details[^>]*data-v94f-editor[^>]*\bopen(?:\s|>)/);
 editor.open=false;await f.dispatch('toggle',editor);
 assert.doesNotMatch(f.html(),/<details[^>]*data-v94f-editor[^>]*\bopen(?:\s|>)/);
 assert.deepEqual(f.calls,[]);
});
test('before-render captures an opened editor even before its queued toggle event',()=>{
 const f=fixture(),state=f.getState();f.app.el.querySelector=selector=>selector==='[data-v94f-editor]'?{open:true}:null;
 f.ctx.v7BeforeRender(f.app);
 assert.equal(state.editorOpen,true);assert.deepEqual(f.calls,[]);
 f.state.ref='beta';assert.doesNotMatch(f.html(),/data-v94f-editor/);
});

test('saved-plan action reaches feedback without request, draft loss or cross-project focus',async()=>{
 const f=fixture(),focus=[];f.getState().commentText='Unsent comment';

 const panel={scrollIntoView:options=>focus.push(options.block),focus:options=>focus.push(options.preventScroll)};
 f.app.el.querySelector=selector=>selector==='[data-v94f-panel]'?panel:null;
 const button={closest:()=>button,hasAttribute:name=>name==='data-v94f-focus'};f.owned.add(button);
 assert.match(f.html(),/data-v94f-focus/);
 await f.dispatch('click',button);
 assert.deepEqual(focus,['start',true]);assert.equal(f.getState().commentText,'Unsent comment');assert.deepEqual(f.calls,[]);
 f.state.ref='beta';await f.dispatch('click',button);assert.deepEqual(focus,['start',true]);assert.deepEqual(f.calls,[]);
});

test('question picker remains reachable when the selected question has no supporting comment',async()=>{
 const f=fixture(),body={key:'q1-only',...Object.fromEntries(Object.entries(f.binding).filter(([k])=>k!=='project_ref')),text:'Review q1 only',question_ref:'q1'};
 f.view.feedback.records=[f.response(body)];f.html();f.getState().value='Unsent revision';
 await f.dispatch('change',f.control('revisionQuestion','q2'));
 assert.match(f.html(),/data-v94f-control="revisionQuestion"/);assert.doesNotMatch(f.html(),/<form data-v94f-form="revise">/);
 await f.dispatch('change',f.control('revisionQuestion','q1'));assert.match(f.html(),/<form data-v94f-form="revise">/);
 assert.equal(f.getState().value,'Unsent revision');assert.deepEqual(f.calls,[]);
 f.getState().pending={action:'revise',body:f.ctx.v94fBody(f.ctx.v94fContext(f.app),f.getState(),'revise')};assert.match(f.html(),/<select data-v94f-control="revisionQuestion" disabled>/);assert.deepEqual(f.calls,[]);
});
