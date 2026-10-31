/* Synthetic Wiki adapter tests; no real user, browser or research execution. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),test=require('node:test');
const source=fs.readFileSync(require('node:path').join(__dirname,'v9-stage3-bridge.js'),'utf8');
const settle=()=>new Promise(resolve=>setImmediate(resolve));
function fixture(request){
 const basis={project_ref:'project-a',input_version:1,revision:2,brief_sha256:'a'.repeat(64)};
 const target={},button={},listeners={},mounts=[];
 const app={page:'workspace',stage:3,lang:'tw',el:{contains:x=>x===button,querySelector:x=>x==='#v93-diagram'?target:null}};
 const state={ref:'project-a',epoch:1,overview:{project:basis}};
 const ctx={rt:state,apps:[app],canonicalReadonly:()=>false,stage2:()=>'<old/>',laterStage:()=>'<later/>',v7BeforeRender:()=>{},v7AfterRender:()=>{},
  rl:(zh,en,tw)=>tw||zh,rx:String,canonicalTop:()=>'<top/>',livePaint:()=>{},projectPath:(r,p)=>'/api/projects/'+r+'/'+p,
  liveRequest:request|| (async()=>({...basis,plan:{kind:'Stage3ResearchPlan'}})),
  window:{RESEARCH_PROJECTS:{stage2_selection_projects:['project-a'],stage3_planning_projects:['project-a']},STAGE3_RESEARCH_DIAGRAM:{mount:(...x)=>mounts.push(x)}},
  document:{addEventListener:(name,fn)=>listeners[name]=fn},location:{hash:'#project-a?stage=3&lang=zh-TW'},URLSearchParams,encodeURIComponent,decodeURIComponent,console};
 vm.createContext(ctx);vm.runInContext(source,ctx);return {ctx,state,app,button,listeners,mounts,basis};
}
test('Wiki routes restore only an existing project and permitted stage/language',()=>{
 const f=fixture();assert.equal(JSON.stringify(f.ctx.v93RouteTarget([{project_ref:'project-a'}])),JSON.stringify({ref:'project-a',stage:3,lang:'tw'}));
 assert.equal(f.ctx.v93RouteTarget([{project_ref:'other'}]),null);
 f.ctx.location.hash='#project-a?stage=4&lang=zh-TW';assert.equal(f.ctx.v93RouteTarget([{project_ref:'project-a'}]),null);
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
