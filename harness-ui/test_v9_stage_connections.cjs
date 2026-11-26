// SYNTHETIC. A local HTML document runs the shipped renderers and delegated DOM handlers.
// Network is disabled in the document. livePost/liveRecover use an in-memory transport.
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync, writeFileSync, mkdtempSync, existsSync, rmSync} = require('node:fs');
const {join} = require('node:path');
const {tmpdir} = require('node:os');
const {pathToFileURL} = require('node:url');
const {spawnSync} = require('node:child_process');
const source = name => readFileSync(join(__dirname,name),'utf8');

function browserFixture() {
  window.RESEARCH_PROJECTS = {};
  const app = {el:document.querySelector('main'), page:'workspace', stage:2, lang:'zh'};
  const project = {project_ref:'SYNTHETIC-A', project_id:'SYNTHETIC-ID', input_version:1, revision:2, brief_sha256:'a'.repeat(64)};
  Object.assign(window, {app, apps:[app], project, rt:{ref:project.project_ref,overview:{project},epoch:0},
    stage2:()=>'<p>SYNTHETIC original material</p>', laterStage:()=>'<p>SYNTHETIC original archive</p>',
    v7AfterRender(){}, v7BeforeRender(){}, canonicalReadonly:()=>false, canonicalTop:()=>'',
    liveHeader:()=>'', rl:zh=>zh, rx:value=>String(value).replaceAll('&','&amp;').replaceAll('"','&quot;').replaceAll('<','&lt;'),
    projectPath:(ref,tail)=>'/api/projects/'+ref+'/'+tail, calls:[], changes:{},
    livePaint(){app.el.innerHTML=app.stage===2?stage2(app):laterStage(app);},
    async liveRefresh(){rt.epoch++; livePaint();},
    async liveRequest(path, body){
      const tail=path.split('/').slice(4).join('/');
      calls.push({tail, body:body&&structuredClone(body)});
      if (tail==='overview') return {project:{...project,...changes.overview}};
      if (tail==='stage2/continuation') return {...project, status:changes.selection||'no-candidate', execution_authorized:false, ...changes.continuation};
      if (tail==='history') return {actions:[]};
      if (tail==='stage3/planning') return {...project,plan:null};
      if (tail!=='connections') throw Error('unexpected fixture request '+tail);
      if (body) {
        if (changes.postError) throw Object.assign(Error(changes.postError),{status:changes.postHttp});
        project.revision++;
        changes.status=changes.afterPost||'connected'; changes.reason=changes.afterReason||null;
      } else if (changes.getError) throw Object.assign(Error(changes.getError),{status:changes.http});
      if (!body && changes.wait) {const waiting=changes.wait; delete changes.wait; await waiting;}
      const status=changes.status||'connectable';
      const row={status, reason:changes.reason||null, profile_sha256:'b'.repeat(64),
        connection_id:status==='connected'?'c'.repeat(64):null, receipt_id:status==='connected'?'SYNTHETIC-receipt':null, ...changes.row};
      return {project_ref:project.project_ref, execution_authorized:false,
        connections:{'stage2-controller':row, 'stage3-planning':row}, ...changes.response};
    }});
  // The shared lock name and ifAvailable/exclusive mode are part of the fixture contract.
  Object.defineProperty(navigator,'locks',{configurable:true,value:{
    request:async (name, options, callback)=>{
      if(name!=='ara.stage2.transaction.v1.'+rt.ref || !options.ifAvailable || options.mode!=='exclusive')
        throw Error('incorrect fixture lock');
      return callback(changes.noLock?null:{name});
    }}});
}
async function exercise() {
  const check=(v,description)=>{if(!v)throw Error(description);};
  const tick=()=>new Promise(resolve=>setTimeout(resolve,10));
  const status=()=>app.el.querySelector('[data-v9-connection-panel]')?.textContent||app.el.textContent;
  const button=action=>app.el.querySelector('[data-v9-connection="'+action+'"]');
  const posts=()=>calls.filter(call=>call.body);
  const reset=async (config={},stage=2)=>{
    sessionStorage.clear();window.changes=config;calls.length=0;
    Object.assign(rt,{ref:project.project_ref,overview:{project},busy:false,pending:null,controlHeld:false,loading:false,error:''});
    app.stage=stage;rt.epoch++;livePaint();await tick();
  };
  await reset(); check(posts().length===0 && button('connect'),'render uses only GET');
  const connect=button('connect');connect.click();connect.click();await tick();
  check(posts().length===1 && status().includes('本课题已接通'),'one explicit registration and verified readback');
  const keys=['key','revision','input_version','brief_sha256','stage','profile_sha256','confirmed'];
  check(Object.keys(posts()[0].body).sort().join()===keys.sort().join()&&posts()[0].body.stage==='stage2-controller'
    &&posts()[0].body.confirmed===true,'seven-field intent');
  check(calls.slice(calls.indexOf(posts()[0])+1).some(c=>c.tail==='connections'&&!c.body),'separate success discovery');
  check(!app.el.querySelector('[data-v93-choice]') && app.el.innerHTML.includes('SYNTHETIC original material'),'connected is not selection');
  await reset({afterPost:'consent-required',afterReason:'stage2-continuation-activation-required'});
  button('connect').click();await tick();
  check(status().includes('启用同意')&&!button('connect')&&posts().length===1,'consent shortfall after click');
  button('read').click();await tick();check(posts().length===1,'consent read retains record');
  await reset({status:'unavailable',reason:'stage2-controller-current-input-required'});
  button('read').click();await tick();check(status().includes('输入包和接收回执')&&!posts().length,'missing packet');
  await reset({postError:'cross-site-rejected',postHttp:403});
  button('connect').click();await tick();check(status().includes('访问被拒绝')&&!button('connect'),'rejected POST');
  await reset({getError:'not-found',http:404});
  button('read').click();await tick();check(status().includes('没有提供本阶段接通接口')&&!posts().length,'missing endpoint');
  await reset({getError:'stage2-controller-binding-differs',http:409});
  button('read').click();await tick();check(status().includes('原物理目录')&&status().includes('原包和回执')&&!button('connect')&&!posts().length,'moved directory GET only');
  await reset({getError:'SYNTHETIC-other-conflict',http:409});
  button('read').click();await tick();check(!status().includes('搬过目录')&&status().includes('无法核验')&&!posts().length,'unknown 409');
  await reset({postError:'SYNTHETIC-upstream',postHttp:503});
  button('connect').click();await tick();
  const saved=sessionStorage.getItem('v7-pending-action');
  check(saved&&status().includes('Unknown')&&!button('connect'),'unknown keeps pending intent');
  await liveRecover();button('read').click();await tick();
  check(sessionStorage.getItem('v7-pending-action')===saved&&posts().length===1,'read and recovery never replay or clear unknown');
  await reset();const staleButton=button('connect');
  changes.overview={input_version:'1'};staleButton.click();await tick();check(!posts().length&&!button('connect'),'typed preflight drift');
  for(const [field,value] of Object.entries({project_ref:'SYNTHETIC-B',project_id:'SYNTHETIC-other-id',input_version:'1',brief_sha256:'d'.repeat(64),revision:999})){
    await reset({status:'connected',overview:{[field]:value}},3);
    check(!app.el.querySelector('[data-v93-read]')&&!button('connect')&&!status().includes('本课题已接通'),'bound overview mismatch: '+field);
  }
  await reset({response:{project_ref:'SYNTHETIC-B'}});check(!button('connect'),'wrong discovery project');
  await reset({response:{execution_authorized:true}});check(!button('connect'),'invalid execution flag');
  await reset({status:'connected',row:{receipt_id:null}},3);check(!app.el.querySelector('[data-v93-read]'),'incomplete connection receipt');
  await reset({noLock:true});button('connect').click();await tick();check(!posts().length&&status().includes('项目锁'),'busy lock');
  for(const [flag,value] of Object.entries({busy:true,loading:true,pending:{ref:'SYNTHETIC-foreign'},controlHeld:true})){
    await reset();const original=button('connect');rt[flag]=value;original.click();await tick();check(!posts().length,'preserve parent '+flag);
  }
  await reset({status:'connected',selection:'selection-available'});
  check(app.el.querySelector('[data-v93-choice]'),'verified selection opens original entry');
  await reset({status:'connected',selection:'selection-available',continuation:{project_id:'wrong'}});
  check(!app.el.querySelector('[data-v93-choice]'),'foreign selection blocked');
  await reset({status:'connected'},3);
  const read=app.el.querySelector('[data-v93-read]');check(read,'verified planning connection opens original entry');
  read.click();await tick();check(!posts().length&&calls.some(c=>c.tail==='stage3/planning'),'planning read does not execute');
  await reset({},3);button('connect').click();await tick();
  check(posts().length===1&&posts()[0].body.stage==='stage3-planning'&&status().includes('本课题已接通'),'stage3 explicit registration');
  await reset({status:'connected'},3);
  let release;changes.wait=new Promise(resolve=>release=resolve);button('read').click();await Promise.resolve();
  rt.ref='SYNTHETIC-B';rt.overview={project:{...project,project_ref:rt.ref}};rt.epoch++;livePaint();release();await tick();
  check(!app.el.querySelector('[data-v93-read]')&&!status().includes('本课题已接通'),'late response for previous project');
}
test('SYNTHETIC stage connections through the served renderer functions and real button clicks',()=>{
  const chrome=[process.env.CHROME_BIN, process.env.CHROME_PATH,
    'C:/Program Files/Google/Chrome/Application/chrome.exe','/usr/bin/google-chrome','/usr/bin/chromium',
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'].find(p=>p&&existsSync(p));
  assert.ok(chrome,'Chrome or Chromium is required (or set CHROME_BIN)');
  const temp=mkdtempSync(join(tmpdir(),'pr4-connections-'));
  try {
    const runtime=source('renderer/src/runtime.js');
    const actions=runtime.slice(runtime.indexOf('async function liveReceiptBound('),runtime.indexOf('const liveDisabled='));
    const scripts=[`(${browserFixture})();`, actions, ...['stage2_display.js','v9-stage-connections.js','v9-stage3-bridge.js'].map(source),
      `(${exercise})().then(()=>document.title='SYNTHETIC_PASS',e=>document.title='FAIL '+e.stack);`];
    const html=join(temp,'fixture.html');
    writeFileSync(html,'<!doctype html><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src \'unsafe-inline\'"><title>RUNNING</title><main></main>'+
      scripts.map(s=>'<script>'+s.replaceAll('</script','<\\/script')+'</script>').join(''));
    const run=spawnSync(chrome,['--headless','--disable-gpu','--disable-background-networking','--no-first-run',
      '--user-data-dir='+join(temp,'profile'),'--virtual-time-budget=5000','--dump-dom',pathToFileURL(html).href],{encoding:'utf8',timeout:30000,maxBuffer:2e6});
    assert.equal(run.status,0,run.error?.message||run.stderr);
    assert.equal(run.stdout.match(/<title>([^<]*)<\/title>/)?.[1],'SYNTHETIC_PASS');
  } finally { rmSync(temp,{recursive:true,force:true,maxRetries:8,retryDelay:100}); }
});
