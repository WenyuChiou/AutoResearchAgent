/* Synthetic Wiki adapter tests; no real user, browser or research execution. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),test=require('node:test');
const source=fs.readFileSync(require('node:path').join(__dirname,'v9-stage3-bridge.js'),'utf8');
const settle=()=>new Promise(resolve=>setImmediate(resolve));
const escapeHtml=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function fixture(request){
 const basis={project_ref:'project-a',input_version:1,revision:2,brief_sha256:'a'.repeat(64)};
 const target={},button={},listeners={},mounts=[];
 const app={page:'workspace',stage:3,lang:'tw',el:{contains:x=>x===button,querySelector:x=>x==='#v93-diagram'?target:null}};
 const state={ref:'project-a',epoch:1,overview:{project:basis}};
 const ctx={rt:state,apps:[app],canonicalReadonly:()=>false,stage2:()=>'<old/>',laterStage:()=>'<later/>',otherPage:()=>'<div class="hs-heading"><p class="hs-eyebrow">STAGE 01 / 06</p><h1>Literature</h1><p>Repeated project brief</p></div><p role="alert">Original pending outcome</p>',v7BeforeRender:()=>{},v7AfterRender:()=>{},
  rl:(zh,en,tw)=>tw||zh,rx:escapeHtml,canonicalTop:()=>'<top/>',livePaint:()=>{},projectPath:(r,p)=>'/api/projects/'+r+'/'+p,
  liveRequest:request|| (async()=>({...basis,plan:{kind:'Stage3ResearchPlan'}})),
  window:{addEventListener:(name,fn)=>listeners[name]=fn,RESEARCH_PROJECTS:{stage2_selection_projects:['project-a'],stage3_planning_projects:['project-a']},STAGE3_RESEARCH_DIAGRAM:{mount:(...x)=>mounts.push(x)}},
  document:{addEventListener:(name,fn)=>listeners[name]=fn},location:{hash:'#project-a?stage=3&lang=zh-TW'},URLSearchParams,encodeURIComponent,decodeURIComponent,console};
 vm.createContext(ctx);vm.runInContext(source,ctx);return {ctx,state,app,button,listeners,mounts,basis};
}
test('utility headings follow the current page and preserve pending/error content',()=>{
 const f=fixture();
 for(const [page,title] of [['files','專案檔案'],['history','操作歷史'],['settings','連線與設定']]){
  f.app.page=page;const html=f.ctx.otherPage(f.app);
  assert.match(html,new RegExp('<h1>'+title+'</h1>'));assert.ok(html.includes('Original pending outcome'));
  assert.equal((html.match(/<h1>/g)||[]).length,1);
  assert.doesNotMatch(html,/STAGE 01|Repeated project brief/);assert.ok(html.includes('PROJECT'));
 }
 f.app.page='workspace';assert.ok(f.ctx.otherPage(f.app).includes('<h1>Literature</h1>'));
});
test('Wiki routes restore only an existing project and permitted stage/language',()=>{
 const f=fixture();assert.equal(JSON.stringify(f.ctx.v93RouteTarget([{project_ref:'project-a'}])),JSON.stringify({ref:'project-a',stage:3,lang:'tw'}));
 assert.equal(f.ctx.v93RouteTarget([{project_ref:'other'}]),null);
  for(const stage of [1,2,3,4,5,6]){
    f.ctx.location.hash='#project-a?stage='+stage+'&lang=zh-TW';
    assert.equal(f.ctx.v93RouteTarget([{project_ref:'project-a'}]).stage,stage);
  }
  for(const stage of [0,7,2.5]){
    f.ctx.location.hash='#project-a?stage='+stage+'&lang=zh-TW';assert.equal(f.ctx.v93RouteTarget([{project_ref:'project-a'}]),null);
  }
});

test('browser Back and Forward restore stages and language without requests or draft loss',()=>{
 const f=fixture(()=>assert.fail('navigation must not request or dispatch'));
 const base=fs.readFileSync(require('node:path').join(__dirname,'renderer/src/base.js'),'utf8');
 vm.runInContext(base.slice(base.indexOf('  function localStage('),base.indexOf('  const localContextKeys=')),f.ctx);
 const location=new URL('http://localhost/nested/wiki/?theme=night#project-a?stage=3&lang=zh-TW&view=matrix');
 const entries=[location.href],state={retained:'state'};let position=0,paints=0,pushes=0;
 f.ctx.location=location;f.ctx.livePaint=()=>paints++;f.state.list=[{project_ref:'project-a'},{project_ref:'project-b'}];
 f.ctx.history={state,pushState(received,unused,target){assert.equal(received,state);entries.splice(++position);entries.push(new URL(target,location).href);location.href=entries[position];pushes++;},replaceState(){assert.fail('stage clicks must add a history entry');}};
 Object.assign(f.app,{previewStageContexts:{},selected:{id:'stage3'},focal:'stage3',draftAnswers:{question:'unsent'},draftNotes:{note:'retained'}});
 const drafts=JSON.stringify([f.app.draftAnswers,f.app.draftNotes]);
 f.ctx.localStage(f.app,2);f.app.selected={id:'stage2'};f.app.focal='stage2';
 f.app.lang='en';f.ctx.localStage(f.app,1);
 assert.equal(entries.length,3);assert.equal(pushes,2);
 const travel=delta=>{position+=delta;location.href=entries[position];f.listeners.popstate();f.listeners.hashchange();};
 travel(-1);assert.equal(f.app.stage,2);assert.equal(f.app.lang,'tw');assert.equal(f.app.selected.id,'stage2');assert.equal(paints,1);
 travel(-1);assert.equal(f.app.stage,3);assert.equal(f.app.focal,'stage3');assert.equal(paints,2);
 travel(1);assert.equal(f.app.stage,2);assert.equal(paints,3);
 travel(1);assert.equal(f.app.stage,1);assert.equal(f.app.lang,'en');assert.equal(paints,4);
 assert.equal(pushes,2);assert.equal(entries.length,3);assert.equal(location.pathname,'/nested/wiki/');assert.equal(location.search,'?theme=night');assert.match(location.hash,/view=matrix/);
 assert.equal(JSON.stringify([f.app.draftAnswers,f.app.draftNotes]),drafts);
 f.ctx.localStage(f.app,1);assert.equal(pushes,2,'same stage does not add a duplicate entry');
 for(const fragment of ['#project-b?stage=2&lang=en','#project-a?stage=7&lang=en','#project-a?stage=2&lang=xx','#%ZZ?stage=2&lang=en']){
  const before=JSON.stringify(f.app);location.hash=fragment;f.listeners.popstate();f.listeners.hashchange();assert.equal(JSON.stringify(f.app),before);assert.equal(paints,4);
 }
 location.hash='#project-a?stage=2&lang=en';f.state.overview={project:{...f.basis,project_ref:'project-b'}};f.listeners.popstate();assert.equal(f.app.stage,1,'mismatched overview is not restored');
});


test('first stage navigation canonicalizes a hashless entry before pushing',()=>{
 for(const firstStage of [1,2]){
  const f=fixture(()=>assert.fail('history restoration cannot request or dispatch'));
  const base=fs.readFileSync(require('node:path').join(__dirname,'renderer/src/base.js'),'utf8');
  vm.runInContext(base.slice(base.indexOf('  function localStage('),base.indexOf('  const localContextKeys=')),f.ctx);
  const location=new URL('http://localhost/nested/wiki/?theme=night');
  const entries=[location.href],state={retained:'initial-state'};let position=0,replacements=0,pushes=0;
  const setLocation=target=>{location.href=new URL(target,location).href;};
  f.ctx.location=location;f.state.list=[{project_ref:'project-a'}];
  f.ctx.history={state,replaceState(received,unused,target){assert.equal(received,state);replacements++;entries[position]=new URL(target,location).href;setLocation(target);},pushState(received,unused,target){assert.equal(received,state);pushes++;entries.splice(++position);entries.push(new URL(target,location).href);setLocation(target);}};
  Object.assign(f.app,{stage:1,lang:'en',previewStageContexts:{},selected:{id:'stage1'},focal:'stage1',draftNotes:{note:'unsent'}});
  f.ctx.localStage(f.app,firstStage);if(firstStage===1){assert.equal(pushes,0,'initial same-stage click only normalizes');f.ctx.localStage(f.app,2);}
  assert.equal(replacements,1);assert.equal(pushes,1);assert.equal(entries.length,2);
  assert.equal(new URL(entries[0]).hash,'#project-a?stage=1&lang=en');assert.equal(location.hash,'#project-a?stage=2&lang=en');
  position--;location.href=entries[position];f.listeners.popstate();f.listeners.hashchange();
  assert.equal(f.app.stage,1);assert.equal(f.app.lang,'en');assert.equal(f.app.focal,'stage1');assert.equal(f.app.draftNotes.note,'unsent');assert.equal(location.pathname,'/nested/wiki/');assert.equal(location.search,'?theme=night');
  position++;location.href=entries[position];f.listeners.popstate();f.listeners.hashchange();assert.equal(f.app.stage,2);assert.equal(replacements,1);assert.equal(pushes,1);
 }
});

test('same-version GET mounts the graph in the Wiki and changes no data',async()=>{
 const calls=[],f=fixture(async path=>{calls.push(path);return {...f.basis,plan:{kind:'Stage3ResearchPlan'}}});
 await f.listeners.click({target:{closest:()=>f.button}});f.ctx.v7AfterRender(f.app);
 assert.deepEqual(calls,['/api/projects/project-a/stage3/planning']);assert.equal(f.mounts.length,1);assert.equal(f.mounts[0][0],f.app.el.querySelector('#v93-diagram'));
 assert.equal(f.mounts[0][2].language,'zh-TW');
});
test('an outdated response cannot draw a graph for another project',async()=>{
 let release;const f=fixture(()=>new Promise(resolve=>{release=resolve}));const p=f.listeners.click({target:{closest:()=>f.button}});await settle();f.state.ref='project-b';f.state.epoch++;release({...f.basis,plan:{kind:'Stage3ResearchPlan'}});await p;f.ctx.v7AfterRender(f.app);assert.equal(f.mounts.length,0);
});
test('a response with mismatched typed version is refused',async()=>{
 const f=fixture(async()=>({...f.basis,input_version:'1',plan:{}}));await f.listeners.click({target:{closest:()=>f.button}});f.ctx.v7AfterRender(f.app);assert.equal(f.mounts.length,0);assert.match(f.ctx.laterStage(f.app),/version differs/);
});

test('Wiki labels the older cards and does not imply a missing plan exists',async()=>{
 const f=fixture(async()=>({...f.basis,plan:null}));f.app.stage=2;
 assert.match(f.ctx.stage2(f.app),/較早匯入版本/);assert.match(f.ctx.stage2(f.app),/data-v93-choice/);
 f.app.stage=3;await f.listeners.click({target:{closest:()=>f.button}});
 assert.match(f.ctx.laterStage(f.app),/沒有已保存的規劃/);
});

test('saved conditional planning leads with readable materials and method, keeping full details closed',async()=>{
 const calls=[],f=fixture(async path=>{calls.push(path);return {...f.basis,plan:{kind:'Stage3DirectionPlanningResult',planning_status:'conditional-draft',markdown:'A saved conditional plan.\n\nAdditional paragraph.',question_plans:[{question_ref:'q1',method:'Compare held-fixed rules.',materials:'Published age tables; access still unknown.',design:'Proposed design only.',unknowns:['Verify table definitions.']}]},direction_context:{questions:[{question_ref:'q1',text:'How does age composition affect demand?'}]}};});
 await f.listeners.click({target:{closest:()=>f.button}});
 const html=f.ctx.laterStage(f.app);
 assert.ok(html.indexOf('已保存的規劃摘要')<html.indexOf('研究關係圖與來源'));
 for(const text of ['How does age composition affect demand?','Compare held-fixed rules.','Published age tables; access still unknown.','Verify table definitions.','尚未執行實驗'])assert.ok(html.includes(text));
 assert.match(html,/<details class="n9-plan-details">/);assert.match(html,/<details class="n9-plan-graph">/);
  assert.match(html,/<ol class="n9-plan-flow n9-source-flow">/);
  assert.equal((html.match(/class="n9-flow-heading"/g)||[]).length,8);
 assert.ok(html.includes('研究規劃流程（擬議）'));assert.ok(html.includes('各步驟尚未執行'));
 assert.doesNotMatch(html,/<details[^>]*\bopen(?:\s|>)/);
 assert.deepEqual(calls,['/api/projects/project-a/stage3/planning']);
 assert.equal(f.mounts.length,0,'Rendering a summary does not dispatch or mount a generation');
});

test('conditional resource view preserves exact question/version use, unknowns and source without generation',async()=>{
  const row={question_ref:'idea-a@2/q1',materials:'Public table leads; access unknown.',method:'Saved rule method',unknowns:['Original missing rights']};
  const resource={name:'A mapped tool',status:'unknown',purpose:'General purpose'};
  const card={candidate_id:'idea-a',candidate_version:2,scientific_questions:[{question:{question_id:'q1'},resource_uses:[{resource,resource_ref:{purpose:'Question-specific accounting',fit_status:'proposed'}}]}]};
  const other={candidate_id:'idea-a',candidate_version:1,scientific_questions:[{question:{question_id:'q1'},resource_uses:[{resource:{name:'OLD VERSION RESOURCE'}}]}]};
  const view={plan:{kind:'Stage3DirectionPlanningResult',planning_status:'conditional-draft',question_plans:[row]},direction_context:{questions:[{question_ref:row.question_ref,text:'Saved question'}],preferred_cards:[card,other]}};
  const before=JSON.stringify(view),calls=[],f=fixture(async path=>{calls.push(path);return {...f.basis,...view};});
  await f.listeners.click({target:{closest:()=>f.button}});const html=f.ctx.laterStage(f.app);
  for(const value of ['A mapped tool','Question-specific accounting','unknown','proposed','Original missing rights','/plan/question_plans/0/method'])assert.ok(html.includes(value));
  assert.doesNotMatch(html,/OLD VERSION RESOURCE/);assert.equal(JSON.stringify(view),before);
  assert.equal((html.match(/<details class="n9-flow-source">/g)||[]).length,8);
  assert.doesNotMatch(html,/<details[^>]*\bopen(?:\s|>)/);assert.deepEqual(calls,['/api/projects/project-a/stage3/planning']);
});

test('saved source fields remain inert and unmapped material leads are not promoted',async()=>{
  const f=fixture(async()=>({...f.basis,plan:{kind:'Stage3DirectionPlanningResult',question_plans:[{question_ref:'q1',materials:'<img src=x onerror=alert(1)>',method:'<script>unsafe()</script>',unknowns:['Original source limit']}]}}));
  await f.listeners.click({target:{closest:()=>f.button}});const html=f.ctx.laterStage(f.app);
  assert.ok(html.includes('&lt;img'));assert.ok(html.includes('&lt;script&gt;'));assert.doesNotMatch(html,/<script>|<img/);
  assert.ok(html.includes('本問題沒有已映射的資源；保持 unknown。'));
  assert.ok(html.includes('Original source limit'));
});

test('unmatched or unavailable plan fields remain explicit and no old plan leaks across versions',async()=>{
 const f=fixture(async()=>({...f.basis,plan:{kind:'Stage3DirectionPlanningResult',question_plans:[{question_ref:'missing'}]}}));
 await f.listeners.click({target:{closest:()=>f.button}});
 let html=f.ctx.laterStage(f.app);assert.match(html,/尚未記錄/);assert.match(html,/研究問題 1/);
 f.state.overview.project={...f.basis,revision:3};html=f.ctx.laterStage(f.app);assert.doesNotMatch(html,/已保存的規劃摘要/);
});

test('formal saved plans retain their linked-record graph without a false scalar summary',async()=>{
 const calls=[],plan={kind:'Stage3ResearchPlan',questions:[{question_ref:'q1',text:'Formal saved question'}],question_plans:[{question_ref:'q1',design_ids:['d1'],analysis_ids:['a1'],result_ids:['r1']}],designs:[{design_id:'d1',family:'Saved design'}],analyses:[{analysis_id:'a1',method:'Saved analysis',design_ids:['d1']}],results:[{result_id:'r1',artifact:'Saved output',analysis_ids:['a1']}],unknowns:[{reason:'Actual unresolved material'}]};
 const before=JSON.stringify(plan),f=fixture(async path=>{calls.push(path);return {...f.basis,plan};});
 await f.listeners.click({target:{closest:()=>f.button}});
 const html=f.ctx.laterStage(f.app);f.ctx.v7AfterRender(f.app);
 assert.doesNotMatch(html,/n9-plan-overview|尚未記錄|0 項待查事項/);
 assert.match(html,/<details class="n9-plan-graph" open>/);
 assert.equal(f.mounts.length,1);assert.equal(f.mounts[0][1].plan,plan);
 assert.deepEqual(calls,['/api/projects/project-a/stage3/planning']);assert.equal(JSON.stringify(plan),before);
});

test('error from a prior project or version is not shown on a new binding',async()=>{
 const f=fixture(async()=>{throw Error('project A only failure')});
 await f.listeners.click({target:{closest:()=>f.button}});
 assert.match(f.ctx.laterStage(f.app),/project A only failure/);
 f.state.ref='project-b';f.state.overview.project={...f.basis,project_ref:'project-b'};
 f.ctx.window.RESEARCH_PROJECTS.stage3_planning_projects.push('project-b');
 assert.doesNotMatch(f.ctx.laterStage(f.app),/project A only failure/);
 f.state.ref='project-a';f.state.overview.project={...f.basis,revision:3};
 assert.doesNotMatch(f.ctx.laterStage(f.app),/project A only failure/);
});

test('Wiki preserves a mounted choice across redraw and suspends on project or stage switch',()=>{
  const f=fixture(),placed=[],navigations=[],calls=[],pending={value:false};let reloads=0;f.app.stage=2;
 f.app.el.querySelector=selector=>selector==='[data-v93-choice]'?{append:item=>placed.push(item)}:null;
 const template={content:{cloneNode:()=>({})}};
 f.ctx.document.getElementById=id=>id==='v93-selection-template'?template:null;
 f.ctx.document.createElement=tag=>tag==='link'?{}:{children:[],append(...nodes){this.children.push(...nodes);},attachShadow(){this.shadowRoot={append(){},querySelector:()=>null,activeElement:null};return this.shadowRoot;}};
  f.ctx.window.location={set hash(value){navigations.push('/'+value);},reload:()=>reloads++};
 let saved;
 f.ctx.window.STAGE2_SELECTION={mount:(root,opts)=>{calls.push('mount');saved=opts;return {
   suspend:()=>calls.push('suspend'),resume:()=>calls.push('resume'),
   setLanguage:value=>calls.push('language:'+value),state:()=>({recovery:null}),dispose:()=>{calls.push('dispose');return !pending.value;}
 }}};
 f.ctx.v7AfterRender(f.app);f.ctx.v7BeforeRender(f.app);f.ctx.v7AfterRender(f.app);
 assert.equal(calls.filter(x=>x==='mount').length,1);assert.equal(placed[0],placed[1]);
 let restored=0;placed[0].shadowRoot.activeElement={selectionStart:2,selectionEnd:4,focus:()=>restored++,setSelectionRange:(start,end)=>{assert.equal(start,2);assert.equal(end,4);}};
 f.ctx.document.body={};f.ctx.document.activeElement=f.ctx.document.body;f.ctx.v7BeforeRender(f.app);f.ctx.v7AfterRender(f.app);assert.equal(restored,1);

 f.app.lang='en';f.ctx.v7AfterRender(f.app);assert.ok(calls.includes('language:en'));
 saved.onNavigate({projectRef:'other',language:'en'});assert.deepEqual(navigations,[]);
  saved.onAccepted({projectRef:'project-a',language:'invalid'});assert.equal(reloads,0);
 saved.onNavigate({projectRef:'project-a',language:'en'});assert.deepEqual(navigations,['/#project-a?stage=3&lang=en']);
  assert.equal(reloads,1,'hash-only navigation must reload the Wiki to adopt the committed project revision');
  saved.onAccepted({projectRef:'project-a',language:'zh-TW'});
  assert.deepEqual(navigations,['/#project-a?stage=3&lang=en','/#project-a?stage=3&lang=zh-TW']);assert.equal(reloads,2);
 f.app.stage=3;f.ctx.v7BeforeRender(f.app);assert.ok(calls.includes('suspend'));
  saved.onAccepted({projectRef:'project-a',language:'en'});assert.equal(reloads,2,'a suspended stage cannot navigate');
 f.app.stage=2;f.state.overview.project={...f.basis,revision:3};pending.value=true;f.ctx.v7AfterRender(f.app);
 assert.equal(calls.filter(x=>x==='mount').length,1);assert.ok(calls.includes('dispose'));
  saved.onAccepted({projectRef:'project-a',language:'en'});assert.equal(reloads,2,'a stale revision cannot navigate');
});

for(const wikiPath of ['/','/index.html?view=wiki'])test('accepted continuation preserves the Wiki path '+wikiPath,()=>{
  const f=fixture(),reloads=[],url=new URL('http://wiki.test'+wikiPath+'#project-a?stage=2&lang=zh-TW');let options;
  f.app.stage=2;f.app.el.querySelector=selector=>selector==='[data-v93-choice]'?{append(){}}:null;
  f.ctx.document.getElementById=id=>id==='v93-selection-template'?{content:{cloneNode:()=>({})}}:null;
  f.ctx.document.createElement=tag=>tag==='link'?{}:{append(){},attachShadow(){return {append(){},querySelector:()=>null};}};
  f.ctx.window.location={
    assign:value=>{url.href=new URL(value,url).href;},
    set hash(value){url.hash=value;},
    reload:()=>reloads.push(url.pathname+url.search+url.hash),
  };
  f.ctx.window.STAGE2_SELECTION={mount:(_root,args)=>{options=args;return {state:()=>({recovery:null}),resume(){},suspend(){}};}};
  f.ctx.v7AfterRender(f.app);options.onAccepted({projectRef:'project-a',language:'en'});
  assert.deepEqual(reloads,[wikiPath+'#project-a?stage=3&lang=en']);
});

test('missing or malformed project version cannot authorize a graph read',async()=>{
 const f=fixture(),calls=[];f.ctx.liveRequest=async path=>{calls.push(path);return {}};
 for(const change of [{input_version:undefined},{revision:undefined},{brief_sha256:undefined},{brief_sha256:'bad'}]){
  f.state.overview.project={...f.basis,...change};await f.listeners.click({target:{closest:()=>f.button}});
  assert.equal(f.ctx.laterStage(f.app),'<later/>');
 }
 assert.deepEqual(calls,[]);
});

test('changed revision offers an explicit read-only recovery before remounting',async()=>{
 const f=fixture(),slot={children:[],append(...nodes){this.children.push(...nodes);}},checks=[];let resolved=false,paints=0;
 f.app.stage=2;f.app.el.querySelector=selector=>selector==='[data-v93-choice]'?slot:null;
 f.ctx.document.getElementById=id=>id==='v93-selection-template'?{content:{cloneNode:()=>({})}}:null;
 f.ctx.document.createElement=tag=>tag==='link'?{}:{children:[],append(...nodes){this.children.push(...nodes);},attachShadow(){this.shadowRoot={append(){},querySelector:()=>null};return this.shadowRoot;}};
 f.ctx.livePaint=()=>paints++;
 f.ctx.window.STAGE2_SELECTION={mount:()=>({suspend(){},resume(){},setLanguage(){},state:()=>({recovery:null}),dispose:()=>resolved,reconcile:async basis=>{checks.push(basis);return {status:resolved?'verified':'unknown',code:resolved?'saved':'not-yet-confirmed'};}})};
 f.ctx.v7AfterRender(f.app);f.state.overview.project={...f.basis,revision:3};f.ctx.v7BeforeRender(f.app);slot.children=[];f.ctx.v7AfterRender(f.app);
 const box=slot.children[0],button=box.children[1];assert.equal(typeof button.onclick,'function');await button.onclick();
 assert.equal(checks.length,1);assert.equal(checks[0].revision,3);assert.match(box.children[0].textContent,/尚未能確認/);assert.equal(paints,0);
 resolved=true;await button.onclick();assert.equal(checks.length,2);assert.equal(paints,1);
});

test('Wiki displays each verified terminal item and requires human confirmation before clearing',async()=>{
 const f=fixture(),calls=[],slot={children:[],append(...x){this.children.push(...x);}};f.app.stage=2;
 f.ctx.document.createElement=()=>({children:[],append(...x){this.children.push(...x);}});
 let accepted=false;
 f.ctx.window.confirm=()=>accepted;
 const instance={pendingActions:()=>[{key:'one',kind:'stage2-direction-intent',phase:'stage2'},{key:'two',kind:'stage2-select',phase:'planning'}],
  reconcile:async (basis,key)=>{calls.push(['read',key]);return {status:key==='one'?'superseded':'unknown',code:key==='one'?'preference-replaced':'execution-unknown'};},
  acknowledgeTerminal:async (basis,key)=>{calls.push(['ack',key]);return {status:'acknowledged'};},dispose:()=>false};
 f.ctx.v93RecoveryControl(slot,{instance},f.basis,f.app);const box=slot.children[0];
 assert.equal(box.children.length,3);assert.match(box.children[1].textContent,/one/);assert.match(box.children[2].textContent,/two/);
 await box.children[2].onclick();assert.equal(box.children.length,3);assert.match(box.children[0].textContent,/execution-unknown/);
 await box.children[1].onclick();assert.match(box.children[0].textContent,/取代/);assert.equal(box.children.length,4);
 await box.children[3].onclick();assert.deepEqual(calls,[['read','two'],['read','one']]);
 accepted=true;await box.children[3].onclick();assert.deepEqual(calls,[['read','two'],['read','one'],['ack','one']]);
});

test('Wiki explains unavailable and busy cross-tab protection',async()=>{
 for(const [code,pattern] of [['project-lock-busy',/另一個分頁/],['project-lock-unavailable',/不支援必要的跨分頁鎖/]]){
  const f=fixture(),slot={children:[],append(...x){this.children.push(...x);}};f.app.stage=2;f.ctx.document.createElement=()=>({children:[],append(...x){this.children.push(...x);}});
  const instance={pendingActions:()=>[{key:'one'}],reconcile:async()=>({status:'unavailable',code})};
  f.ctx.v93RecoveryControl(slot,{instance},f.basis,f.app);await slot.children[0].children[1].onclick();assert.match(slot.children[0].children[0].textContent,pattern);
 }
});
