const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {webcrypto}=require('node:crypto');
const topic='Same saved engineering question',refs=['project-A','project-B','project-C'];
const projects=refs.map((ref,index)=>({project_ref:ref,project_id:ref,topic,input_version:index+1,
  revision:10+index,brief_sha256:String(index+1).repeat(64),brief:{original_description:topic}}));
const runtime=fs.readFileSync(path.join(__dirname,'renderer/src/runtime.js'),'utf8');
const bridge=fs.readFileSync(path.join(__dirname,'v9-stage3-bridge.js'),'utf8');
const route=bridge.slice(bridge.indexOf('function v93RouteTarget('),bridge.indexOf('// Restore only the currently loaded project'));
const flush=async()=>{await new Promise(setImmediate);await new Promise(setImmediate);};
async function page({storage=new Map(),url='http://localhost/',list=projects,listError=null,denied=null,pending=null,caseRef=refs[0],blockedStorage=false,foreignOverview=false,waitOverview=null,createResponse=null}={}){
  const options=projects.map(p=>({value:p.project_ref,textContent:topic}));
  const notices=[],location=new URL(url),events=[],requests=[],app={page:'workspace',stage:1,lang:'en',el:{querySelector(selector){return selector==='.hs-content'?{prepend:note=>notices.push(note)}:selector==='[data-live-project-notice]'?notices.at(-1):null;},querySelectorAll(){return [{options}];}}};
  const session=new Map(pending?[['v7-pending-action',JSON.stringify(pending)]]:[]);
  const context={apps:[app],URLSearchParams,location,crypto:webcrypto,TextEncoder,Uint8Array,
    history:{state:{kept:true},replaceState(state,unused,target){assert.equal(state,this.state);location.href=new URL(target,location).href;}},
    localStorage:{getItem(k){if(blockedStorage)throw Error('blocked storage');return storage.get(k)??null;},setItem(k,v){if(blockedStorage)throw Error('blocked storage');storage.set(k,v);}},
    sessionStorage:{getItem:k=>session.get(k)??null,setItem:(k,v)=>session.set(k,v),removeItem:k=>session.delete(k)},
    document:{hidden:false,activeElement:null,createElement(){return {dataset:{},setAttribute(){}};},addEventListener:(type,handler)=>events.push({type,handler})},
    localStage(app,stage,options){assert.equal(options.historyMode,'restore');app.page='workspace';app.stage=stage;},
    window:{RESEARCH_PROJECTS:{credential:'synthetic-test',models:false},addEventListener:(type,handler)=>events.push({type,handler})},setInterval(){},v7AfterRender(){},render(){},esc:v=>String(v).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;'),
    translated:(app,values)=>values[{zh:0,en:1,tw:2}[app.lang]],
    fetch:async(url,options)=>{requests.push({url,method:options.method});
      if(options.method!=='GET'){assert(createResponse&&url==='/api/projects'&&options.method==='POST','only this explicit synthetic create may write');return {ok:true,status:200,json:async()=>({project_ref:createResponse})};}
      let value,status=200;
      if(url==='/v7-case.json')value={case_ref:caseRef};
      else if(url==='/api/projects'){value=listError?{error:listError}:{projects:list};if(listError)status=503;}
      else{const found=url.match(/^\/api\/projects\/([^/]+)\/(overview|history)$/);assert(found,url);const ref=decodeURIComponent(found[1]);
        if(ref===denied){status=403;value={error:'project-unavailable'};}
        else if(found[2]==='history')value={actions:[]};
        else {if(waitOverview){const delayed=waitOverview(ref);if(delayed)return delayed;}const project=list.find(p=>p.project_ref===ref);assert(project,'only accessible listed projects can be read');value={project:{...project,project_ref:foreignOverview?'foreign-project':ref},stage1:{ledger:{run_ref:'run-'+ref}}};}}
      return {ok:status===200,status,json:async()=>value};}}
  vm.createContext(context);vm.runInContext(route+'\n'+runtime,context);await flush();
  const run=code=>vm.runInContext(code,context);
  return {run,storage,requests,location,app,session,options,notices,async recoverList(){listError=null;await run('liveRefresh(undefined,{list:true})');await flush();},async navigate(hash){location.hash=hash;for(const entry of events)if(entry.type==='hashchange')await entry.handler();await flush();},async choose(ref){const event={target:{value:ref,matches:s=>s==='[data-live-project]'},stopImmediatePropagation(){}};
    for(const entry of events)if(entry.type==='change')await entry.handler(event);await flush();}};
}
(async()=>{
  const fresh=await page({list:[],caseRef:null});
  assert.equal(fresh.run('rt.error'),'','a fresh empty library is not a route/language failure');
  assert.equal(fresh.run('rt.loading'),false);
  assert.equal(fresh.requests.filter(q=>q.method!=='GET').length,0,'opening an empty library never writes');
  assert.equal(fresh.requests.filter(q=>q.url.startsWith('/api/projects/')).length,0,'no project request without a project');
  for(const lang of ['zh','en','tw']){
    fresh.app.lang=lang;
    assert(fresh.run('liveEmptyHome()').includes('data-live-empty-home'),'localized first-topic guidance');
    assert(!fresh.run('liveTop(apps[0])').includes('data-live-project-identity'),'do not invent an ID for an empty library');
  }
  fresh.app.lang='en';fresh.run('livePaint()');
  assert.equal(fresh.app.previewProject.topic,'No project','successful empty read must stop claiming it is loading');
  fresh.app.lang='zh';fresh.run('livePaint()');
  const beforeLanguageRequests=fresh.requests.length;
  for(const [lang,title] of [['en','No project'],['tw','尚無專案']]){
    fresh.app.lang=lang;fresh.run('render(apps[0])');
    assert.equal(fresh.app.previewProject.topic,title,'ordinary locale render updates the derived empty project title');
  }
  assert.equal(fresh.requests.length,beforeLanguageRequests,'locale repaint is read-free');
  const unavailable=await page({list:[],listError:'project-list-unavailable'});
  assert.equal(unavailable.run('rt.error'),'project-list-unavailable');
  assert.equal(unavailable.run('liveEmptyHome()'),'','a failed list read must not be presented as an empty library');
  assert(unavailable.run('liveHeader(apps[0])').includes('role="alert"'),'keep real errors visible');
  assert(!unavailable.run('liveTop(apps[0])').includes('No project'),'failed read must not label the roster empty');
  await unavailable.recoverList();
  assert.equal(unavailable.run('rt.error'),'');
  assert(unavailable.run('liveEmptyHome()').includes('data-live-empty-home'),'retry recovers startup metadata as well as the empty list');
  assert.equal(unavailable.app.previewProject.topic,'No project');
  assert(unavailable.requests.every(q=>q.method==='GET'),'failed-list retry does not create work');
  fresh.run('rt.loading=true');
  assert.equal(fresh.run('liveEmptyHome()'),'','a pending list read is not empty');
  assert(!fresh.run('liveTop(apps[0])').includes('No project'),'loading must not label the roster empty');
  fresh.run('rt.loading=false');
  const first=await page();const html=first.run('liveTop(apps[0])');
  const labels=[...html.matchAll(/<option[^>]*>([^<]*)<\/option>/g)].map(x=>x[1]);
  assert.equal(new Set(labels).size,3,'same-title project labels must be distinct');
  // The raw reference is shown only where two projects would otherwise get the same label.
  const bases=labels.map(label=>label.replace(/ · project-[A-Za-z0-9]+$/,''));
  labels.forEach((label,i)=>assert.equal(/ · project-/.test(label),bases.filter(b=>b===bases[i]).length>1,'reference only for look-alikes: '+label));
  first.run('v7AfterRender(apps[0])');assert.equal(new Set(first.options.map(o=>o.textContent)).size,3,'retained read-only selectors also get unique labels');
  assert(html.includes('data-live-project-identity'),'current project identity is visible');
  await first.choose(refs[1]);assert.equal(first.run('rt.ref'),refs[1]);assert.equal(first.run('liveBound().input_version'),2);
  assert(first.location.hash.includes(refs[1]),'explicit selection updates the project link');
  assert(first.run('liveTop(apps[0])').includes('Input version'));
  const reopened=await page({storage:first.storage});assert.equal(reopened.run('rt.ref'),refs[1]);
  await reopened.navigate('#project-A?stage=1&lang=en');assert.equal(reopened.run('rt.ref'),refs[0]);
  await reopened.navigate('#project-not-listed?stage=1&lang=en');assert(reopened.run('liveTop(apps[0])').includes('An accessible project is open'));
  const explicit=await page({storage:first.storage,url:'http://localhost/#project-A?stage=2&lang=zh-TW&view=matrix'});
  assert.equal(explicit.run('rt.ref'),refs[0]);assert.equal(explicit.app.stage,2);assert.equal(explicit.app.lang,'tw');
  assert.equal(explicit.location.hash,'#project-A?stage=2&lang=zh-TW&view=matrix','valid existing links keep their parameters');
  await first.choose(refs[2]);const fallback=await page({storage:first.storage,url:'http://localhost/#project-gone?stage=1&lang=en'});
  assert.equal(fallback.run('rt.ref'),refs[2]);assert(fallback.run('liveTop(apps[0])').includes('data-live-project-notice'));
  assert(!fallback.requests.some(r=>r.url.includes('project-gone')),'never fetch a project absent from the current roster');
  const denied=await page({storage:first.storage,denied:refs[2]});assert.equal(denied.run('rt.ref'),refs[0]);
  assert(denied.run('liveTop(apps[0])').includes('data-live-project-notice'));
  const removed=await page({storage:new Map(first.storage),list:projects.filter(p=>p.project_ref!==refs[0]),caseRef:refs[2]});
  assert(removed.run('liveTop(apps[0])').includes('data-live-project-notice'),'a removed previous project has a recovery notice');
  const pending={ref:refs[1],path:'/api/projects/project-B/compile',body:{key:'original-key',revision:11,input_version:2,brief_sha256:'2'.repeat(64)}};
  const held=await page({storage:first.storage,pending,url:'http://localhost/#project-A?stage=1&lang=en'});
  assert.equal(held.run('rt.ref'),refs[1]);assert.equal(held.run('rt.pending.body.key'),'original-key');assert(held.session.has('v7-pending-action'));
  assert.equal(held.location.hash,'#project-A?stage=1&lang=en','an unresolved intent never overwrites the explicit original link');
  await held.navigate('#project-A?stage=1&lang=en');assert.equal(held.run('rt.ref'),refs[1]);assert.equal(held.run('rt.pending.body.key'),'original-key');
  const blocked=await page({blockedStorage:true});await blocked.choose(refs[1]);assert(blocked.location.hash.includes(refs[1]));
  const empty=await page({list:[],caseRef:'foreign-case'});assert.equal(empty.requests.filter(r=>r.url.includes('/overview')).length,0);
  const noFallback=await page({list:[projects[0]],denied:refs[0],url:'http://localhost/#project-gone?stage=1&lang=en'});
  assert(noFallback.run('liveTop(apps[0])').includes('no accessible project has been read'));
  const created=await page({createResponse:refs[2]});await created.choose(refs[1]);await created.run("livePost('',{topic:'Synthetic new topic'},null)");await flush();
  assert.equal(created.run('rt.ref'),refs[2]);assert(created.location.hash.startsWith('#project-C?'),'a new project gets its own reopen URL');assert.equal(created.requests.filter(r=>r.method==='POST').length,1);
  const releases=[],racing=await page({waitOverview:ref=>ref===refs[1]?new Promise(resolve=>releases.push(resolve)):null});
  const old=racing.choose(refs[1]);await flush();await racing.choose(refs[2]);const latest=racing.choose(refs[1]);await flush();
  releases[0]({ok:false,status:403,json:async()=>({error:'denied-old'})});await old;
  assert(racing.location.hash.startsWith('#project-C?'),'an obsolete callback cannot commit a route while the current B is loading');
  releases[1]({ok:false,status:403,json:async()=>({error:'denied-current'})});await latest;
  assert.equal(racing.run('rt.ref'),refs[2]);assert(racing.location.hash.startsWith('#project-C?'));
  let releaseLatest;const parameters=await page({waitOverview:ref=>ref===refs[1]?new Promise(resolve=>{releaseLatest=resolve;}):null});
  parameters.app.page='settings';const navigation=parameters.navigate('#project-B?stage=2&lang=zh-TW');await flush();
  await parameters.navigate('#project-B?stage=3&lang=zh-CN');
  releaseLatest({ok:true,status:200,json:async()=>({project:projects[1],stage1:{ledger:{run_ref:'run-B'}}})});await navigation;
  assert.equal(parameters.app.stage,3);assert.equal(parameters.app.lang,'zh');assert.equal(parameters.app.page,'workspace');
  parameters.app.page='history';await parameters.navigate('#project-gone?stage=1&lang=en');parameters.run('v7AfterRender(apps[0])');assert.equal(parameters.notices.length,1,'fallback is visible outside Stage1');
  const foreign=await page({storage:new Map(),foreignOverview:true});assert.equal(foreign.storage.size,0,'mismatched overview never becomes a remembered selection');
  const another=await page();assert.equal(another.run('rt.ref'),refs[0],'independent profile does not borrow the other selection');
  for(const env of [first,reopened,explicit,fallback,denied,removed,held,blocked,empty,noFallback,foreign,another,racing,parameters])assert(env.requests.every(r=>r.method==='GET'));
 console.log('PASS same-title labels, profile reopen, latest public routes, bounded truthful fallback, pending marker/link, versions, synthetic create and stale callbacks; fresh empty home in three languages, loading/error distinction; recovery GET only');
})().catch(e=>{console.error(e);process.exitCode=1;});
