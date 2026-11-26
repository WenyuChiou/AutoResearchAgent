'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict'),test=require('node:test');
const dir=path.join(__dirname,'renderer/src'),now=Date.parse('2026-11-26T12:00:00Z');
function input(){return {ref:'p1',project:{project_ref:'p1',input_version:1,revision:8,brief_sha256:'b'.repeat(64),brief:{original_description:'Music'},settings:{brief_sha256:'b'.repeat(64),budgets:{model_calls:0,seconds:0},execution_authorized:false}},models:{project_ref:'p1',input_version:1,revision:8,brief_sha256:'b'.repeat(64),connected:false,native_authenticated:null,authorization_available:false,calls_reserved:0,blocking_unknown_count:0},offers:{project_ref:'p1',revision:8,offers:[]}};}
function context(){const c={};vm.createContext(c);const f=path.join(dir,'connection-diagnostics.js');if(fs.existsSync(f))vm.runInContext(fs.readFileSync(f,'utf8'),c);return c;}
function view(i=input()){return context().connectionDiagnostics(i,now);}
function offer(i=input()){i.models.connected=true;i.models.authorization_available=true;i.offers.offers=[{offer_ref:'offer-1',operation:'read-paper',input_version:1,brief_sha256:i.project.brief_sha256,available:true,expires_at:'2026-11-26T13:00:00Z',max_calls:2,max_seconds:30}];return i;}
function settingsHtml(rt,lang='en'){
 const c=context();
 Object.assign(c,{rt,liveReal:()=>true,savedOtherPage:()=>'',liveHeader:()=>'',v7AfterRender:()=>{},Date});
 const src=fs.readFileSync(path.join(dir,'real-runtime.js'),'utf8');
 const start=src.indexOf('otherPage = function(app)');
 vm.runInContext(src.slice(start,src.indexOf('\nlivePost =',start)),c);
 return c.otherPage({page:'settings',lang});
}
test('ordinary settings explains unknown login and recovery, instead of raw status alone',()=>{
 const i=input();
 const html=settingsHtml({ref:i.ref,overview:{project:i.project,models:i.models,model_offers:i.offers}},'zh-CN');
 assert.match(html,/data-connection-diagnostics/);assert.match(html,/无法核实登录状态/);assert.match(html,/恢复/);assert.doesNotMatch(html,/<button|<form/);
});
const readRejections=[
 ['credential-required',/Reopen the same ordinary Wiki homepage/],
 ['credential-rejected',/Reopen the same ordinary Wiki homepage/],
 ['origin-or-host-rejected',/Return to the original Wiki address/],
 ['cross-site-rejected',/Return to the original Wiki address/]
];
async function coldSettings({bootstrap, error='', status=200, pending=null}){
 const runtime=fs.readFileSync(path.join(dir,'runtime.js'),'utf8');
 const realRuntime=fs.readFileSync(path.join(dir,'real-runtime.js'),'utf8');
 const section=(source,start,end)=>{
  const first=source.indexOf(start),last=source.indexOf(end,first+start.length);
  assert.ok(first>=0&&last>first,start);
  return source.slice(first,last);
 };
 const sidebar={textContent:''};
 let renderedHtml='';
 const app={page:'settings',stage:1,lang:'en',el:{querySelector(selector){
  if(selector==='.hs-sidebar-foot')return sidebar;
  if(selector==='[data-connection-diagnostics]'&&renderedHtml.includes('data-connection-diagnostics'))return {};
  return null;
 }}};
 const c=context(),calls=[];
 Object.assign(c,{
  window:bootstrap?{RESEARCH_PROJECTS:bootstrap}:{},location:{hash:''},
  liveHeader:()=>'',liveFeedback:()=>'<p>History</p>',livePaint:()=>{},liveHomeProject:()=>null,
  liveSavedProject:()=>null,liveSelectProject:async()=>{},v7AfterRender:()=>{},rows:()=>[],
  rl:(_zh,en)=>en,rx:String,
  async fetch(route,options){
   calls.push([route,options.method]);
   const denied=error&&route==='/api/projects';
   return {ok:!denied,status:denied?status:200,json:async()=>denied?{error}:
    route==='/v7-case.json'?{kind:'V7RuntimeConfiguration'}:{projects:[]}};
  }
 });
 vm.runInContext([
  section(runtime,'const rt = {','\ntry { rt.pending'),
  section(runtime,'async function liveRequest(','\nasync function liveRefresh'),
  section(runtime,'otherPage=app=>','\ndocument.addEventListener(\'change\''),
  section(realRuntime,'const liveReal = ','\nconst savedRuntimeRender'),
  section(realRuntime,'const savedOtherPage = ','\nconst savedRefresh'),
  section(realRuntime,'function realLibrary(){','\nlivePost =')
 ].join('\n'),c);
 c.app=app;c.pending=pending;c.liveRecover=async()=>{};
 vm.runInContext('rt.pending=pending;',c);
 await vm.runInContext(section(runtime,"Promise.all([liveRequest('/v7-case.json'),liveRequest('/api/projects')])",'\nsetInterval('),c);
 const render=page=>{
  app.page=page;
  renderedHtml=c.otherPage(app);
  c.v7AfterRender(app);
  return {html:renderedHtml,sidebar:sidebar.textContent};
 };
 return {render,calls,live:vm.runInContext('liveReal()',c)};
}
test('ordinary Wiki cold reads show the four recoveries and keep other pages on normal navigation',async()=>{
 const bootstrap={credential:'synthetic',wiki_v9:true};
 const healthy=await coldSettings({bootstrap});
 assert.equal(healthy.live,true);
 assert.match(healthy.render('settings').html,/data-connection-diagnostics/);
 for(const [error,recovery] of readRejections){
  const status=error.startsWith('credential-')?401:403;
  const entry=await coldSettings({bootstrap,error,status});
  assert.deepEqual(entry.calls,[['/v7-case.json','GET'],['/api/projects','GET']]);
  assert.equal(entry.live,false);
  const {html,sidebar}=entry.render('settings');
  assert.match(html,recovery);
  assert.match(html,/Login cannot be verified/);
  assert.doesNotMatch(html,/Local Harness records are connected|may be confirmed/);
  assert.match(sidebar,/Project read failed/);
  assert.deepEqual(entry.render('history'),{html:'<p>History</p>',sidebar:'Local service connected · current papers 0'});
  assert.match(entry.render('settings').html,recovery);
 }
});
test('cold Wiki settings keep local unknown writes ahead of read recovery',async()=>{
 const entry=await coldSettings({bootstrap:{credential:'synthetic',wiki_v9:true},error:'credential-rejected',status:401,pending:{ref:'p1'}});
 const {html}=entry.render('settings');
 assert.match(html,/Keep the original operation key/);
 assert.doesNotMatch(html,/Reopen the same ordinary Wiki homepage|may be confirmed/);
});
test('non-Wiki bootstrap and unknown Wiki refusal keep the existing fallback',async()=>{
 for(const bootstrap of [undefined,{credential:'synthetic'},{credential:'synthetic',wiki_v9:false}]){
  const entry=await coldSettings({bootstrap,error:'credential-rejected',status:401});
  const {html,sidebar}=entry.render('settings');
  assert.match(html,/Local Harness records are connected/);
  assert.doesNotMatch(html,/data-connection-diagnostics/);
  assert.match(sidebar,/Local service connected/);
 }
 const unknown=await coldSettings({bootstrap:{credential:'synthetic',wiki_v9:true},error:'private C:/secret/token',status:500});
 assert.doesNotMatch(unknown.render('settings').html,/data-connection-diagnostics|C:\/secret/);
});
for(const [error,recovery] of readRejections){
 test(`ordinary settings shows specific recovery for ${error}`,()=>{
  const html=settingsHtml({ref:'p1',error});
  assert.match(html,recovery);
  assert.match(html,/Login cannot be verified/);
  assert.doesNotMatch(html,/Current project response is missing|Current content task may be confirmed/);
 });
}
test('ordinary settings keeps unknown read errors generic and private',()=>{
 const html=settingsHtml({ref:'p1',error:'private C:/secret/token'});
 assert.match(html,/Current project response is missing or mismatched/);
 assert.match(html,/Login cannot be verified/);
 assert.doesNotMatch(html,/C:\/secret|Current content task may be confirmed/);
});
test('zero limits stay zero, unknown money/auth remain unknown; pure view does not mutate input',()=>{const i=input(),before=JSON.stringify(i),v=view(i);assert.equal(v.provider,'absent');assert.equal(v.authentication,'unknown');assert.equal(v.permission,'none');assert.equal(v.budgets.model_calls,0);assert.equal(v.monetaryCost,null);assert.equal(JSON.stringify(i),before);});
test('provider registration does not imply native login or research permission',()=>{const i=offer(),v=view(i);assert.equal(v.provider,'registered');assert.equal(v.authentication,'unknown');assert.equal(v.permission,'confirmable');assert.equal(v.researchAuthorized,false);assert.equal(v.permits[0].maxCalls,2);});
test('only explicit bound boolean authentication is shown',()=>{for(const [raw,want]of [[true,'verified'],[false,'not-authenticated'],['true','unknown'],[null,'unknown']]){const i=input();i.models.native_authenticated=raw;assert.equal(view(i).authentication,want);}});
test('foreign project data never appears under selected project',()=>{const i=offer();i.project.project_ref='p2';i.project.brief.original_description='Foreign title';const v=view(i);assert.equal(v.binding,'unavailable');assert.equal(v.topic,null);assert.equal(v.permission,'unknown');});
test('model responses must match exact integer input, revision and brief',()=>{for(const [key,value]of [['project_ref','p2'],['input_version','1'],['input_version',2],['revision',7],['brief_sha256','old']]){const i=offer();i.models[key]=value;i.models.native_authenticated=true;const v=view(i);assert.equal(v.provider,'unknown',key);assert.equal(v.authentication,'unknown',key);assert.equal(v.permission,'unknown',key);}});
test('wrong or stale offers cannot provide an effective permission',()=>{for(const mutate of [i=>i.offers.project_ref='p2',i=>i.offers.revision=7,i=>i.offers.offers[0].input_version='1',i=>i.offers.offers[0].brief_sha256='old']){const i=offer();mutate(i);assert.notEqual(view(i).permission,'confirmable');}});
test('expiry is checked each render, malformed or absent expiry cannot become permission',()=>{const i=offer();assert.equal(view(i).permission,'confirmable');assert.equal(context().connectionDiagnostics(i,now+3600000).permits[0].reason,'expired');for(const value of [null,'invalid','2026-11-26T13:00:00']){i.offers.offers[0].expires_at=value;assert.notEqual(view(i).permission,'confirmable');}});
test('server refusal takes precedence over future expiry; unknown writes prevent retry advice',()=>{const i=offer();i.offers.offers[0].available=false;i.offers.offers[0].blocked_reason='model-permit-call-budget-exhausted';assert.equal(view(i).permits[0].reason,'exhausted');i.offers.offers[0].available=true;i.models.blocking_unknown_count=1;assert.equal(view(i).permission,'held');assert.equal(view(i).recovery,'unknown-write');});
test('a cold renderer derives exactly the same diagnostic without persistent storage',()=>{const i=offer();assert.equal(JSON.stringify(view(i)),JSON.stringify(view(JSON.parse(JSON.stringify(i)))));});
test('missing data and known HTTP errors give bounded recovery, never raw secrets',()=>{for(const [error,recovery]of [['credential-required','credential'],['origin-or-host-rejected','origin'],['private C:/secret/token','read-failed']]){const i=input();i.error=error;const v=view(i);assert.equal(v.recovery,recovery);assert.equal(v.permission,'unknown');const html=context().connectionDiagnosticsHtml(v,'en');assert.ok(!html.includes('C:/secret'));}});
test('all user fields are escaped, and diagnostic contains no controls or raw offer errors',()=>{const i=offer();i.project.brief.original_description='<img src=x onerror=alert(1)>';i.offers.offers[0].operation='<script>';i.offers.offers[0].available=false;i.offers.offers[0].blocked_reason='SECRET_TOKEN';for(const locale of ['zh-CN','zh-TW','en']){const html=context().connectionDiagnosticsHtml(view(i),locale);assert.ok(html.includes('&lt;img'));assert.doesNotMatch(html,/<img|<script|<button|<form|SECRET_TOKEN/);}});
test('known write barriers survive read errors and suppress every confirmable permit',()=>{
 for(const error of ['', 'credential-required','origin-or-host-rejected'])for(const barrier of ['local','model']){
  const i=offer();i.error=error;if(barrier==='local')i.writeHeld=true;else i.models.blocking_unknown_count=1;
  const v=view(i);assert.equal(v.permission,'held');assert.equal(v.recovery,'unknown-write');assert.ok(v.permits.every(p=>p.reason!=='confirmable'));
 }
 const i=input();i.project=null;i.writeHeld=true;assert.equal(view(i).recovery,'unknown-write');
});
test('ordinary settings passes pending and control-held without exposing their data',()=>{
 const i=offer(),overview={project:i.project,models:i.models,model_offers:i.offers};
 for(const [error,recovery] of readRejections){
  for(const field of ['pending','controlHeld']){
   const html=settingsHtml({ref:i.ref,[field]:{secret:'NEVER_DISPLAY'},overview,error});
   assert.match(html,/Keep the original operation key/);
   assert.doesNotMatch(html,recovery);
   assert.doesNotMatch(html,/NEVER_DISPLAY|may be confirmed/);
  }
 }
});
test('cold reads without a project retain specific 401/403 recovery',()=>{
 for(const [error,recovery]of [['credential-required','credential'],['origin-or-host-rejected','origin']]){const i={error};assert.equal(view(i).recovery,recovery);i.writeHeld=true;assert.equal(view(i).recovery,'unknown-write');}
});
test('unknown-write count uses the existing conservative legacy fallback',()=>{
 for(const count of [undefined,null,-1,'0',0.5]){const i=offer();i.models.blocking_unknown_count=count;i.models.unknown_count=0;assert.notEqual(view(i).permission,'confirmable');}
 const i=offer();delete i.models.blocking_unknown_count;i.models.unknown_count=1;assert.equal(view(i).permission,'held');i.models.unknown_count=0;assert.equal(view(i).permission,'confirmable');delete i.models.unknown_count;assert.notEqual(view(i).permission,'confirmable');
});
test('malformed offer or impossible calendar date cannot break rendering or look valid',()=>{
 const i=offer();i.offers.offers=[null];assert.notEqual(view(i).permission,'confirmable');assert.doesNotThrow(()=>context().connectionDiagnosticsHtml(view(i),'en'));
 for(const expires_at of ['2099-02-31T13:00:00Z','2099-00-01T13:00:00Z','2099-12-00T13:00:00Z']){const j=offer();j.offers.offers[0].expires_at=expires_at;assert.equal(view(j).permits[0].reason,'unknown-expiry');}
});
