/* Synthetic integration of the actual Wiki bridge and scoped selection component. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),test=require('node:test');
const {harness}=require('../plugins/auto-research-agent/tests/test_project_stage2_selection_embedded.cjs');
const source=fs.readFileSync(path.join(__dirname,'v9-stage3-bridge.js'),'utf8');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function setup(options={}){
  const f=harness({...options,deferMount:true}),basis=f.args.binding,placed=[],moves=[],reloads=[];
 const originalQuery=f.root.querySelector.bind(f.root);f.root.querySelector=selector=>selector==='nav'?null:originalQuery(selector);f.root.append=()=>{};
 const slot={append:element=>placed.push(element)},app={page:'workspace',stage:2,lang:'tw',el:{querySelector:selector=>selector==='[data-v93-choice]'?slot:null,contains:()=>false}};
 const state={ref:basis.project_ref,epoch:1,overview:{project:basis}};
 const template={content:{cloneNode:()=>({})}},doc={body:{},activeElement:null,getElementById:id=>id==='v93-selection-template'?template:null,addEventListener(){},createElement:tag=>tag==='link'?{}:{children:[],append(...nodes){this.children.push(...nodes);},attachShadow(){this.shadowRoot=f.root;return f.root;}}};
  f.window.addEventListener=()=>{};
  f.window.location={set hash(value){moves.push('/'+value);},reload:()=>reloads.push(moves.at(-1))};
 const ctx={rt:state,apps:[app],canonicalReadonly:()=>false,stage2:()=>'<older/>',laterStage:()=>'<later/>',v7BeforeRender:()=>{},v7AfterRender:()=>{},rl:(zh,en,tw)=>tw||zh,rx:String,canonicalTop:()=>'',livePaint:()=>{},projectPath:(ref,sub)=>'/api/projects/'+ref+'/'+sub,liveRequest:async()=>{throw Error('unexpected graph request')},window:f.window,document:doc,location:{hash:''},URLSearchParams,encodeURIComponent,decodeURIComponent,console};
  vm.createContext(ctx);vm.runInContext(source,ctx);return {f,ctx,app,state,placed,moves,reloads};
}
test('Wiki mounts the real selection component and accepted selection enters the same Wiki project',async()=>{
 const h=setup();h.ctx.v7AfterRender(h.app);await tick();await tick();
 assert.equal(h.f.reads.filter(x=>x.endsWith('/stage2/selection')).length,1);assert.equal(h.f.writes.length,0);
 assert.match(h.f.els.get('cards').textContent,/Bounded question/);h.f.selectRadio();h.f.form();
 h.ctx.v7BeforeRender(h.app);h.ctx.v7AfterRender(h.app);assert.equal(h.placed[0],h.placed[1]);
 await h.f.els.get('choice').onsubmit({preventDefault(){},submitter:h.f.els.get('submit-and-start')});
 assert.deepEqual(h.moves,['/#project-a?stage=3&lang=zh-TW']);
  assert.deepEqual(h.reloads,h.moves,'accepted planning re-enters bootstrap with the same project and language');
 assert.equal(h.f.writes.filter(x=>x.url.endsWith('/stage2/select')).length,1);
  assert.equal(h.f.writes.filter(x=>x.url.endsWith('/planning/run')).length,1);
});
test('Wiki project switch suppresses continuation of an in-flight real component submission',async()=>{
 const h=setup();h.ctx.v7AfterRender(h.app);await tick();await tick();h.f.selectRadio();h.f.form();h.f.waitSelect();
 const pending=h.f.els.get('choice').onsubmit({preventDefault(){},submitter:h.f.els.get('submit-and-start')});
 const deadline=Date.now()+5000;while(h.f.writes.length===0&&Date.now()<deadline)await new Promise(resolve=>setTimeout(resolve,5));
 assert.equal(h.f.writes.length,1,'selection request did not reach the suspended test handler');
 h.app.stage=3;h.ctx.v7BeforeRender(h.app);h.f.release();await pending;
  assert.equal(h.f.writes.length,1);assert.deepEqual(h.moves,[]);assert.deepEqual(h.reloads,[]);
});
test('Wiki zero recommendations remain visible and cannot generate a formal submission',async()=>{
 const h=setup({empty:true});h.ctx.v7AfterRender(h.app);await tick();await tick();
  assert.equal(h.f.els.get('choice').hidden,true);assert.equal(h.f.writes.length,0);assert.match(h.f.els.get('status').textContent,/沒有可推薦/);assert.deepEqual(h.reloads,[]);
});

test('Wiki verifies a lost selection response against the advanced revision without resending',async()=>{
 const h=setup({failSelectResponse:true});h.ctx.v7AfterRender(h.app);await tick();await tick();h.f.selectRadio();h.f.form();
 await h.f.els.get('choice').onsubmit({preventDefault(){},submitter:h.f.els.get('submit')});await tick();
 assert.equal(h.f.writes.length,1);h.state.overview.project={...h.f.args.binding,revision:2};h.ctx.v7BeforeRender(h.app);h.ctx.v7AfterRender(h.app);
 const recovery=h.placed.at(-1),button=recovery.children[1];assert.equal(typeof button.onclick,'function');await button.onclick();
  assert.equal(h.f.writes.length,1);assert.deepEqual(h.moves,[]);assert.deepEqual(h.reloads,[]);assert.equal(h.f.window.localStorage.length,0);
});

test('Wiki accepts the verified new workflow head from a real synthetic service receipt',async()=>{
 const real=JSON.parse(fs.readFileSync(path.join(__dirname,'../plugins/auto-research-agent/tests/fixtures/stage2_formal_selection_service_saved.json'),'utf8'));
 assert.notEqual(real.before.workflow_head_sha256,real.after.workflow_head_sha256);
 const h=setup({realFixture:real});h.ctx.v7AfterRender(h.app);await tick();await tick();h.f.selectRadio();
 const e=h.f.els,d=real.body.decision;e.get('confirmed').checked=true;e.get('actor').value=d.actor;e.get('message').value=d.user_text;e.get('rationale').value=d.rationale;e.get('conditions').value=d.conditions.join('\n');e.get('unresolved').value=d.unresolved.join('\n');
 await e.get('choice').onsubmit({preventDefault(){},submitter:e.get('submit')});
 assert.equal(h.f.writes.length,1);assert.equal(e.get('choice').hidden,true);assert.equal(h.f.window.localStorage.length,0);assert.deepEqual(h.moves,[]);
});

test('Wiki reload verifies the original saved service receipt without sending another POST',async()=>{
 const real=JSON.parse(fs.readFileSync(path.join(__dirname,'../plugins/auto-research-agent/tests/fixtures/stage2_formal_selection_service_saved.json'),'utf8'));
 const first=setup({realFixture:real,failSelectResponse:true});first.ctx.v7AfterRender(first.app);await tick();await tick();first.f.selectRadio();
 const e=first.f.els,d=real.body.decision;e.get('confirmed').checked=true;e.get('actor').value=d.actor;e.get('message').value=d.user_text;e.get('rationale').value=d.rationale;e.get('conditions').value=d.conditions.join('\n');e.get('unresolved').value=d.unresolved.join('\n');
 await e.get('choice').onsubmit({preventDefault(){},submitter:e.get('submit')});assert.equal(first.f.writes.length,1);assert.equal(first.f.window.localStorage.length,1);
 const second=setup({realFixture:real,preselected:true,storage:first.f.window.localStorage});second.ctx.v7AfterRender(second.app);await tick();await tick();
 const box=second.placed[0],button=box.children[1];assert.equal(typeof button.onclick,'function');await button.onclick();
  assert.equal(second.f.writes.length,0);assert.equal(second.f.window.localStorage.length,0);assert.deepEqual(second.moves,[]);assert.deepEqual(second.reloads,[]);
});
