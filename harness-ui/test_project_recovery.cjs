const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {webcrypto}=require('node:crypto');
const topic='Same saved engineering question',refs=['project-A','project-B','project-C'];
const projects=refs.map((ref,index)=>({project_ref:ref,project_id:ref,topic,input_version:index+1,
  revision:10+index,brief_sha256:String(index+1).repeat(64),brief:{original_description:topic}}));
const runtime=fs.readFileSync(path.join(__dirname,'renderer/src/runtime.js'),'utf8');
const bridge=fs.readFileSync(path.join(__dirname,'v9-stage3-bridge.js'),'utf8');
const route=bridge.slice(bridge.indexOf('function v93RouteTarget('),bridge.indexOf('// Restore only the currently loaded project'));
const flush=async()=>{await new Promise(setImmediate);await new Promise(setImmediate);};
async function page({storage=new Map(),url='http://localhost/',list=projects,denied=null,pending=null,caseRef=refs[0],blockedStorage=false,foreignOverview=false}={}){
  const location=new URL(url),events=[],requests=[],app={stage:1,lang:'en',el:{querySelector(){return null;}}};
  const session=new Map(pending?[['v7-pending-action',JSON.stringify(pending)]]:[]);
  const context={apps:[app],URLSearchParams,location,crypto:webcrypto,TextEncoder,Uint8Array,
    history:{state:{kept:true},replaceState(state,unused,target){assert.equal(state,this.state);location.href=new URL(target,location).href;}},
    localStorage:{getItem(k){if(blockedStorage)throw Error('blocked storage');return storage.get(k)??null;},setItem(k,v){if(blockedStorage)throw Error('blocked storage');storage.set(k,v);}},
    sessionStorage:{getItem:k=>session.get(k)??null,setItem:(k,v)=>session.set(k,v),removeItem:k=>session.delete(k)},
    document:{hidden:false,activeElement:null,addEventListener:(type,handler)=>events.push({type,handler})},
    window:{RESEARCH_PROJECTS:{credential:'synthetic-test',models:false}},setInterval(){},v7AfterRender(){},render(){},esc:v=>String(v).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;'),
    translated:(app,values)=>values[{zh:0,en:1,tw:2}[app.lang]],
    fetch:async(url,options)=>{requests.push({url,method:options.method});assert.equal(options.method,'GET','restoration must never write');
      let value,status=200;
      if(url==='/v7-case.json')value={case_ref:caseRef};
      else if(url==='/api/projects')value={projects:list};
      else{const found=url.match(/^\/api\/projects\/([^/]+)\/(overview|history)$/);assert(found,url);const ref=decodeURIComponent(found[1]);
        if(ref===denied){status=403;value={error:'project-unavailable'};}
        else if(found[2]==='history')value={actions:[]};
        else {const project=list.find(p=>p.project_ref===ref);assert(project,'only accessible listed projects can be read');value={project:{...project,project_ref:foreignOverview?'foreign-project':ref},stage1:{ledger:{run_ref:'run-'+ref}}};}}
      return {ok:status===200,status,json:async()=>value};}}
  vm.createContext(context);vm.runInContext(route+'\n'+runtime,context);await flush();
  const run=code=>vm.runInContext(code,context);
  return {run,storage,requests,location,app,session,async choose(ref){const event={target:{value:ref,matches:s=>s==='[data-live-project]'},stopImmediatePropagation(){}};
    for(const entry of events)if(entry.type==='change')await entry.handler(event);await flush();}};
}
(async()=>{
  const first=await page();const html=first.run('liveTop(apps[0])');
  const labels=[...html.matchAll(/<option[^>]*>([^<]*)<\/option>/g)].map(x=>x[1]);
  assert.equal(new Set(labels).size,3,'same-title project labels must be distinct');
  refs.forEach(ref=>assert(labels.some(label=>label.includes(ref)),'visible option identifies '+ref));
  assert(html.includes('data-live-project-identity'),'current project identity is visible');
  await first.choose(refs[1]);assert.equal(first.run('rt.ref'),refs[1]);assert.equal(first.run('liveBound().input_version'),2);
  assert(first.location.hash.includes(refs[1]),'explicit selection updates the project link');
  assert(first.run('liveTop(apps[0])').includes('Input version'));
  const reopened=await page({storage:first.storage});assert.equal(reopened.run('rt.ref'),refs[1]);
  const explicit=await page({storage:first.storage,url:'http://localhost/#project-A?stage=2&lang=zh-TW&view=matrix'});
  assert.equal(explicit.run('rt.ref'),refs[0]);assert.equal(explicit.app.stage,2);assert.equal(explicit.app.lang,'tw');
  assert.equal(explicit.location.hash,'#project-A?stage=2&lang=zh-TW&view=matrix','valid existing links keep their parameters');
  await first.choose(refs[2]);const fallback=await page({storage:first.storage,url:'http://localhost/#project-gone?stage=1&lang=en'});
  assert.equal(fallback.run('rt.ref'),refs[2]);assert(fallback.run('liveTop(apps[0])').includes('data-live-project-notice'));
  assert(!fallback.requests.some(r=>r.url.includes('project-gone')),'never fetch a project absent from the current roster');
  const denied=await page({storage:first.storage,denied:refs[2]});assert.equal(denied.run('rt.ref'),refs[0]);
  assert(denied.run('liveTop(apps[0])').includes('data-live-project-notice'));
  const pending={ref:refs[1],path:'/api/projects/project-B/compile',body:{key:'original-key',revision:11,input_version:2,brief_sha256:'2'.repeat(64)}};
  const held=await page({storage:first.storage,pending,url:'http://localhost/#project-A?stage=1&lang=en'});
  assert.equal(held.run('rt.ref'),refs[1]);assert.equal(held.run('rt.pending.body.key'),'original-key');assert(held.session.has('v7-pending-action'));
  const blocked=await page({blockedStorage:true});await blocked.choose(refs[1]);assert(blocked.location.hash.includes(refs[1]));
  const empty=await page({list:[],caseRef:'foreign-case'});assert.equal(empty.requests.filter(r=>r.url.includes('/overview')).length,0);
  const foreign=await page({storage:new Map(),foreignOverview:true});assert.equal(foreign.storage.size,0,'mismatched overview never becomes a remembered selection');
  const another=await page();assert.equal(another.run('rt.ref'),refs[0],'independent profile does not borrow the other selection');
  for(const env of [first,reopened,explicit,fallback,denied,held,blocked,empty,foreign,another])assert(env.requests.every(r=>r.method==='GET'));
  console.log('PASS same-title labels, profile reopen, explicit links, inaccessible fallback, pending marker and version isolation; 10 scenarios; GET only');
})().catch(e=>{console.error(e);process.exitCode=1;});
