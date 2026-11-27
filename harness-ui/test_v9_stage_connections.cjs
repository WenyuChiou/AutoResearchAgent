// SYNTHETIC. A local HTML document runs the shipped renderers and delegated DOM handlers.
// Network is disabled in the document. livePost/liveRecover use an in-memory transport.
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync, writeFileSync, mkdtempSync, existsSync, rmSync} = require('node:fs');
const {join} = require('node:path');
const {tmpdir} = require('node:os');
const {pathToFileURL} = require('node:url');
const {spawn, spawnSync} = require('node:child_process');
const source = name => readFileSync(join(__dirname,name),'utf8');

function browserFixture() {
  window.RESEARCH_PROJECTS = {};
  const digest=async (kind,body)=>{
    const keys=Object.keys(body).filter(key=>key!=='revision').sort();
    const semantic=Object.fromEntries(keys.map(key=>[key,body[key]]));
    const bytes=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify({body:semantic,kind})));
    return Array.from(new Uint8Array(bytes),v=>v.toString(16).padStart(2,'0')).join('');
  };
  window.fixtureDigest=digest;
  const app = {el:document.querySelector('main'), page:'workspace', stage:2, lang:'zh'};
  const project = {project_ref:'SYNTHETIC-A', project_id:'SYNTHETIC-ID', input_version:1, revision:2, brief_sha256:'a'.repeat(64)};
  Object.assign(window, {app, apps:[app], project, rt:{ref:project.project_ref,overview:{project},epoch:0},
    stage2:()=>'<p>SYNTHETIC original material</p>', laterStage:()=>'<p>SYNTHETIC original archive</p>',
    v7AfterRender(){}, v7BeforeRender(){}, canonicalReadonly:()=>false, canonicalTop:()=>'',
    liveHeader:()=>'', rl:zh=>zh, rx:value=>String(value).replaceAll('&','&amp;').replaceAll('"','&quot;').replaceAll('<','&lt;'),
    projectPath:(ref,tail='')=>'/api/projects/'+encodeURIComponent(ref)+(tail?'/'+tail:''), calls:[], changes:{},
    livePaint(){app.el.innerHTML=app.stage===2?stage2(app):laterStage(app);},
    async liveRefresh(ref=rt.ref){rt.epoch++; rt.ref=ref;rt.overview={project:{...project}};livePaint();},
    async liveRequest(path, body){
      const tail=path.split('/').slice(4).join('/');
      calls.push({tail, body:body&&structuredClone(body)});
      if(tail==='overview' && changes.missingProject)return {};
      if(tail==='stage2/continuation' && changes.waitContinuation)await changes.waitContinuation;
      if(tail==='stage2/continuation' && changes.continuationError)throw Object.assign(Error(changes.continuationError),{status:409});
      if(tail==='stage2/selection' && changes.receiveDelta){project.revision+=changes.receiveDelta;delete changes.receiveDelta;}
      if(tail==='stage2/selection')return {...project,kind:'Stage2SelectionView',delivery_manifest_sha256:'1'.repeat(64),snapshot_sha256:'2'.repeat(64),delivery_workflow_head_sha256:'3'.repeat(64),execution_authorized:false,...changes.selectionView};
      if (tail==='overview') return {project:{...project,...changes.overview}};
      if (tail==='stage2/continuation') return {...project, status:changes.selection||'no-candidate', execution_authorized:false, delivery_manifest_sha256:'1'.repeat(64),snapshot_sha256:'2'.repeat(64),workflow_head_sha256:'3'.repeat(64), ...changes.continuation};
      if(tail==='history' && changes.waitHistory)await changes.waitHistory;
      if(tail==='history' && changes.historyError)throw Error(changes.historyError);
      if (tail==='history') return {project_ref:project.project_ref,revision:project.revision,execution_authorized:false,actions:changes.actions||[]};
      if(tail==='stage2')return {project_ref:project.project_ref,execution_authorized:false,revision:project.revision,offers:changes.offer?[changes.offer]:[]};
      if(tail==='stage2/actions' && body){
        changes.offer=null;changes.status='connectable';changes.reason=null;project.revision++;
        return {project_ref:project.project_ref,kind:'stage2-activate',key:body.key,status:'saved',execution_authorized:false,
          request_sha256:await digest('stage2-activate',body),input_version:project.input_version,brief_sha256:project.brief_sha256,
          offer_ref:body.offer_ref,offer_sha256:body.offer_sha256,stage2_status:'ready-for-explicit-stage2-run'};
      }
      if (tail==='stage3/planning') return {...project,plan:null};
      if (tail!=='connections') throw Error('unexpected fixture request '+tail);
      if (body) {
        if(changes.switchInPost){rt.ref='SYNTHETIC-B';rt.overview={project:{...project,project_ref:rt.ref}};rt.epoch++;livePaint();}
        if (changes.postError) throw Object.assign(Error(changes.postError),{status:changes.postHttp});
        project.revision++;
        changes.savedKey=body.key;
        changes.status=changes.afterPost||'connected'; changes.reason=changes.afterReason||null;
        if(changes.status==='consent-required'){
          const hash='d'.repeat(64);
          changes.offer={offer_ref:'stage2-'+hash.slice(0,32),offer_sha256:hash,input_version:body.input_version,
            brief_sha256:body.brief_sha256,status:'ready-for-researcher-activation',work_count:3};
          const kind='stage2-register-offer';
          changes.actions=[{project_ref:project.project_ref,kind,key:body.key,status:'saved',execution_authorized:false,offer:changes.offer,
            request_sha256:changes.wrongOfferDigest?'f'.repeat(64):await digest(kind,{input_version:body.input_version,key:body.key,brief_sha256:body.brief_sha256,
              connection_profile_sha256:body.profile_sha256,offer_sha256:hash})}];
        }
        if(changes.loseRegistration){
          const kind=body.stage==='stage2-controller'?'stage2-record-connection':'stage3-record-connection', id='c'.repeat(64);
          changes.actions=[{kind,project_ref:project.project_ref,status:'saved',key:body.key,connection_id:id,execution_authorized:false,
            request_sha256:await digest(kind,{key:body.key,brief_sha256:body.brief_sha256,input_version:body.input_version,connection_sha256:id})}];
          throw Error('SYNTHETIC-response-lost');
        }
      } else if (changes.getError) throw Object.assign(Error(changes.getError),{status:changes.http});
      if (!body && changes.wait) {const waiting=changes.wait; delete changes.wait; await waiting;}
      const status=changes.status||'connectable';
      const row={status, reason:changes.reason||null, profile_sha256:'b'.repeat(64),
        connection_id:status==='connected'?'c'.repeat(64):null, receipt_id:status==='connected'?(changes.savedKey||'SYNTHETIC-receipt'):null, ...(body&&changes.offer?{activation_offer:changes.offer,revision:project.revision}:{}),...changes.row,...(body?changes.postRow:{})};
      return {project_ref:project.project_ref, execution_authorized:false,
        connections:body?{[body.stage]:row}:{'stage2-controller':row, 'stage3-planning':row}, ...changes.response,...(body?changes.postResponse:{})};
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
    Object.assign(rt,{ref:project.project_ref,overview:{project:{...project}},busy:false,pending:null,controlHeld:false,loading:false,error:''});
    app.stage=stage;rt.epoch++;livePaint();await tick();
  };
  // Each counterexample runs on a fresh rendered page, including the previously reachable request button.
  const problems=[];
  const probe=(ok,name)=>{if(!ok)problems.push(name);};
  probe(projectPath('SYNTHETIC-A')==='/api/projects/SYNTHETIC-A','fixture base project path');
  await reset({status:'connected',selection:'candidate-ready',receiveDelta:2});
  probe(!!app.el.querySelector('[data-v93-choice]')&&rt.overview.project.revision===project.revision,'first selection receipt advances overview by exactly two');
  await reset({status:'connected',selection:'candidate-ready',receiveDelta:9});probe(!app.el.querySelector('[data-v93-choice]'),'unexplained revision bump denied');
  window.RESEARCH_PROJECTS.stage2_selection_projects=[project.project_ref];
  for(const legacy of [false,true]){
    await reset({status:'connected',continuationError:'stage2-continuation-result-not-current',...(legacy?{getError:'not-found',http:404}:{})});
    probe(app.el.innerText.includes('原物理目录')&&!app.el.querySelector('[data-v93-choice]'),'listed project retains original conflict '+legacy);
  }
  window.RESEARCH_PROJECTS.stage2_selection_projects=[];
  for(const stage of [2,3]){
    await reset({loseRegistration:true},stage);button('connect').click();await tick();
    const original=rt.pending?.body.key;
    probe(!!original,'lost response persisted');
    const action=changes.actions[0], validHash=action.request_sha256;
    action.request_sha256='0'.repeat(64);await liveRecover();probe(rt.pending?.body.key===original,'wrong native hash retains intent');
    action.request_sha256=validHash;action.key='other';await liveRecover();probe(rt.pending?.body.key===original,'wrong original key retains intent');
    action.key=original;button('read').click();await tick();
    probe(!rt.pending&&!sessionStorage.getItem('v7-pending-action')&&posts().length===1&&status().includes('本课题已接通'),'GET-only confirmation for lost receipt stage '+stage);
  }
  const activationMarker=()=>({ref:project.project_ref,path:projectPath(project.project_ref,'stage2/actions'),body:{
    input_version:project.input_version,revision:project.revision,brief_sha256:project.brief_sha256,
    key:'SYNTHETIC-activation',confirmed:true,offer_sha256:'d'.repeat(64),offer_ref:'stage2-'+'d'.repeat(32)}});
  for(const error of [false,true]){
    await reset();const marker=activationMarker();rt.pending=marker;sessionStorage.setItem('v7-pending-action',JSON.stringify(marker));
    changes.actions=[{key:marker.body.key,kind:'stage2-activate',project_ref:marker.ref,status:'saved',execution_authorized:false,
      request_sha256:await fixtureDigest('stage2-activate',marker.body)}];
    let release;changes.waitHistory=new Promise(resolve=>release=resolve);
    const recovery=liveRecover();await tick();
    rt.ref='SYNTHETIC-B';rt.overview={project:{...project,project_ref:rt.ref}};rt.epoch++;livePaint();
    if(error)changes.historyError='SYNTHETIC-private-activation-error';
    release();await recovery;
    probe(rt.ref==='SYNTHETIC-B'&&rt.pending===marker&&!rt.error,'activation recovery confined on project switch '+error);
  }
  await reset();const retained=activationMarker();rt.pending=retained;sessionStorage.setItem('v7-pending-action',JSON.stringify(retained));
  changes.actions=[{...retained.body,kind:'stage2-activate',project_ref:retained.ref,execution_authorized:false,status:'saved',
    stage2_status:'ready-for-explicit-stage2-run',request_sha256:await fixtureDigest('stage2-activate',retained.body)}];
  await liveRecover();probe(!rt.pending&&!sessionStorage.getItem('v7-pending-action')&&!posts().length,'activation receipt recovered on original project without another POST');
  await reset({missingProject:true});probe(!button('connect'),'missing overview project');
  window.RESEARCH_PROJECTS.stage3_planning_projects=[project.project_ref];
  await reset({status:'unavailable',reason:'stage3-planning-project-stale'},3);
  probe(!app.el.querySelector('[data-v93-read]'),'boot list bypasses explicit denial');
  await reset({getError:'not-found',http:404},3);probe(!!app.el.querySelector('[data-v93-read]'),'legacy read on absent endpoint');
  window.RESEARCH_PROJECTS.stage3_planning_projects=[];
  await reset({selection:'candidate-ready',status:'connected'});
  probe(!!app.el.querySelector('[data-v93-choice]')&&calls.some(c=>c.tail==='stage2/selection'),'candidate-ready requires actual selection evidence');
  await reset({selection:'candidate-ready',status:'connected',selectionView:{snapshot_sha256:'9'.repeat(64)}});
  probe(!app.el.querySelector('[data-v93-choice]'),'candidate/selection pins differ');
  await reset({status:'connected',continuationError:'stage2-continuation-result-not-current'});
  probe(app.el.innerText.includes('原物理目录')&&!button('connect'),'retained continuation 409 guidance');
  await reset({getError:'stage2-controller-binding-differs',http:409,selection:'ready'});
  probe(!app.el.querySelector('[data-wiki-stage2-action=request]'),'blocked connection and old ready');
  const stale=document.createElement('button');stale.dataset.wikiStage2Action='request';app.el.append(stale);stale.click();await tick();
  probe(!posts().length,'old request delegated handler blocked');
  await reset({status:'consent-required',reason:'stage2-continuation-activation-required',afterPost:'consent-required',afterReason:'stage2-continuation-activation-required'});
  const publish=button('publish');probe(publish?.textContent==='生成本课题的启用提议' && status().includes('等你 · 第 1 步'), 'initial consent names step one');
  if(publish){
    publish.click();await tick();
    const panel=app.el.querySelector('[data-v9-connection-panel]');
    probe(posts().length===1&&button('activate')?.textContent==='同意这份提议并启用 Stage 2'&&
      !button('publish')&&panel.querySelector('p[role="status"]').textContent.includes('等你 · 第 2 步')&&
      !panel.querySelector('p[role="status"]').textContent.includes(changes.offer.offer_ref)&&
      panel.querySelector('details').textContent.includes(changes.offer.offer_ref),'verified offer ID lives only in technical details');
    await liveRefresh();await tick();probe(posts().length===1&&!!button('activate'),'offer survives refresh without autopost');
    v9ConnectionView=null;wikiStage2State=undefined;sessionStorage.clear();
    await liveRefresh();await tick();probe(posts().length===1&&!!button('activate'),'offer survives cold reopen from backend reads alone');
    button('activate')?.click();await tick();probe(posts().length===2&&posts()[1].tail==='stage2/actions'&&posts()[1].body.offer_ref===changes.actions[0].offer.offer_ref&&!rt.pending&&sessionStorage.getItem('v7-pending-action')===null&&!!button('connect'),'separate existing activation contract');
  }
  await reset({status:'consent-required',reason:'stage2-continuation-activation-required',afterPost:'consent-required',afterReason:'stage2-continuation-activation-required',wrongOfferDigest:true});
  button('publish').click();await tick();probe(!!rt.pending&&status().includes('Unknown')&&!button('activate'),'offer without original receipt digest stays Unknown');
  const originalVersion=project.input_version;project.input_version='1';
  await reset();probe(!button('connect')&&!posts().length,'legacy string input cannot register');project.input_version=originalVersion;
  for(const wrong of [{postRow:{receipt_id:'wrong-key'}},{postResponse:{execution_authorized:true}},{postResponse:{project_ref:'wrong'}},
      {postResponse:{connections:{}}},{postRow:{profile_sha256:'f'.repeat(64)}}]){
    await reset(wrong);button('connect').click();await tick();
    const saved=sessionStorage.getItem('v7-pending-action');
    probe(!!saved&&!!rt.pending&&status().includes('Unknown')&&!button('connect'),'unverified 200 remains pending '+JSON.stringify(wrong));
    button('read')?.click();await tick();
    probe(saved===sessionStorage.getItem('v7-pending-action')&&posts().length===1,'read cannot settle malformed POST or resend');
  }
  await reset({switchInPost:true,postError:'SYNTHETIC-private-denial',postHttp:403});button('connect').click();await tick();
  probe(rt.ref==='SYNTHETIC-B'&&!rt.error&&!app.el.innerText.includes('SYNTHETIC-private-denial'),'late error does not alter another project');
  check(!problems.length,problems.join(', '));
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
  check(status().includes('等你 · 第 2 步')&&!button('connect')&&posts().length===1,'consent shortfall after click');
  await liveRefresh();await tick();check(posts().length===1,'consent read retains record');
  await reset({status:'unavailable',reason:'stage2-controller-current-input-required'});
  button('read').click();await tick();check(status().includes('输入包和接收回执')&&!posts().length,'missing packet');
  await reset({postError:'cross-site-rejected',postHttp:403});
  button('connect').click();await tick();check(status().includes('访问被拒绝')&&!button('connect'),'rejected POST');
  await reset({getError:'not-found',http:404});
  button('read').click();await tick();check(status().includes('没有提供 Stage 2 接通接口')&&!posts().length,'missing endpoint');
  await reset({getError:'stage2-controller-binding-differs',http:409});
  button('read').click();await tick();check(status().includes('原物理目录')&&status().includes('原包和回执')&&!button('connect')&&!posts().length,'moved directory GET only');
  await reset({getError:'SYNTHETIC-other-conflict',http:409});
  button('read').click();await tick();check(!status().includes('搬过目录')&&status().includes('无法核验')&&!posts().length,'unknown 409');
  await reset({postError:'SYNTHETIC-upstream',postHttp:503});
  button('connect').click();await tick();
  const saved=sessionStorage.getItem('v7-pending-action');
  check(saved&&status().includes('Unknown')&&!button('connect'),'unknown keeps pending intent');
  // Even a generic receipt matching the wrong operation must never settle this native transaction.
  changes.actions=[{project_ref:rt.ref,kind:'connections',key:rt.pending.body.key,status:'saved',
    request_sha256:await window.fixtureDigest('connections',rt.pending.body)}];
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
  await reset({},3);
  check(button('connect')?.textContent==='接通本课题'&&!button('publish')&&!button('activate')&&!button('read'),'Stage 3 offers a single connect action');
  button('connect').click();await tick();
  check(posts().length===1&&posts()[0].body.stage==='stage3-planning'&&status().includes('本课题已接通'),'stage3 explicit registration');
  await reset({status:'connected'},3);
  let release;changes.wait=new Promise(resolve=>release=resolve);button('read').click();await Promise.resolve();
  rt.ref='SYNTHETIC-B';rt.overview={project:{...project,project_ref:rt.ref}};rt.epoch++;livePaint();release();await tick();
  check(!app.el.querySelector('[data-v93-read]')&&!status().includes('本课题已接通'),'late response for previous project');
}
async function exerciseUnreadyStage2() {
  const check=(value,description)=>{if(!value)throw Error(description);};
  const tick=()=>new Promise(resolve=>setTimeout(resolve,10));
  const connection=action=>app.el.querySelector('[data-v9-connection="'+action+'"]');
  const continuation=action=>app.el.querySelector('[data-wiki-stage2-action="'+action+'"]');
  const panel=()=>app.el.querySelector('[data-v9-connection-panel]');
  const posts=()=>calls.filter(call=>call.body);
  const errors=[];
  const probe=(value,description)=>{if(!value)errors.push(description);};
  const open=async config=>{
    sessionStorage.clear();window.changes={continuationError:'stage2-controller-not-connected',...config};
    calls.length=0;await liveRefresh();await tick();
    probe(app.el.querySelector('[data-wiki-stage2-continuation] code')?.textContent==='stage2-controller-not-connected',
      'ordinary Stage 2 exposes the original 409 code');
    probe(!continuation('request')&&!app.el.querySelector('[data-v93-choice]'),'409 hides run and selection controls');
    probe(!continuation('connection'),'ordinary Stage 2 shows the connection directly without a jump button');
    connection('read')?.click();await tick();
    probe(!posts().length && !sessionStorage.getItem('v7-pending-action'),
      'view and refresh preserve an unwritten project');
  };
  await open({getError:'not-found',http:404});
  probe(panel().innerText.includes('联系原项目操作者')&&!connection('connect')&&!connection('publish'),
    'missing connection interface names the operator and exposes no write');
  await open({status:'unavailable',reason:'stage2-controller-profile-unavailable',row:{profile_sha256:null}});
  probe(panel().innerText.includes('没有提供 Stage 2 运行配置')&&panel().innerText.includes('联系原项目操作者')&&!connection('connect'),
    'missing host profile names the configuration and operator');
  await open({status:'unavailable',reason:'stage2-controller-current-input-required'});
  const stage1=panel().querySelector('button[data-stage="1"]');
  probe(panel().innerText.includes('输入包和接收回执') && stage1?.textContent.includes('查看交付') && !connection('publish'),
    'missing input offers the existing Stage 1 navigation without a write control');
  window.RESEARCH_PROJECTS.stage2_selection_projects=[project.project_ref];
  await open({getError:'not-found',http:404});
  probe(!app.el.querySelector('[data-v93-choice]'),'known 409 suppresses the legacy selection allowlist');
  window.RESEARCH_PROJECTS.stage2_selection_projects=[];
  await open({status:'consent-required',reason:'stage2-continuation-activation-required',
    afterPost:'consent-required',afterReason:'stage2-continuation-activation-required'});
  probe(!connection('connect')&&!!connection('publish')&&!connection('activate'),
    'an eligible project needs an explicit offer before consent');
  connection('publish').click();await tick();
  probe(posts().length===1&&posts()[0].tail==='connections'&&!!connection('activate'),
    'publishing leaves a separate verified human consent action');
  window.changes={status:'connected',selection:'ready'};
  calls.length=0;await liveRefresh();await tick();
  probe(panel().querySelector('hr')&&panel().querySelector('[data-wiki-stage2-request-row]')?.textContent.includes('文献包已接收')&&
    panel().contains(continuation('request'))&&panel().contains(continuation('read'))&&
    app.el.querySelectorAll('[data-wiki-stage2-action="read"]').length===1,
    'the connected project shows the existing candidate request and readback inside its connection panel');
  const before=calls.filter(call=>call.tail==='stage2/continuation').length;
  continuation('read')?.click();await tick();
  probe(calls.filter(call=>call.tail==='stage2/continuation').length===before+1&&!posts().length,
    'the inline readback uses the existing read-only continuation request');
  probe(!app.el.innerText.includes('接收文献包'),'no manual literature intake action');
  window.changes={status:'connected',selection:'selection-available'};
  calls.length=0;await liveRefresh();await tick();
  probe(!!app.el.querySelector('[data-v93-choice]')&&panel().textContent.includes('当前版本的候选已保存，可以查看选案')&&
    !posts().length,'a verified saved selection is described accurately on readback');
  window.changes={status:'connected',selection:'SYNTHETIC-unknown-status'};
  calls.length=0;await liveRefresh();await tick();
  probe(panel().textContent.includes('候选请求状态待核对')&&!continuation('request')&&!posts().length,
    'an unrecognized status does not claim no request or allow a write');
  check(!errors.length,errors.join(' | '));
}

async function exerciseStage2ConnectionFocus() {
  const tick=()=>new Promise(resolve=>setTimeout(resolve,10));
  const heading=()=>app.el.querySelector('[data-v9-connection-panel] h2');
  const outside=document.createElement('button');
  document.body.append(outside);
  const failures=[];
  for (const [read,move] of [
    ['connections',null],['connections','outside'],['connections','stage'],
    ['continuation',null],['continuation','outside'],['continuation','project'],
  ]) {
    let release;
    const pending=new Promise(resolve=>{release=resolve;});
    window.changes=read==='connections'?{continuationError:'stage2-controller-not-connected',status:'unavailable',
      reason:'stage2-controller-profile-unavailable',row:{profile_sha256:null}}:{status:'connected',selection:'ready'};
    if (read==='connections') changes.wait=pending;
    calls.length=0;app.stage=2;
    await liveRefresh();await tick();
    const requests=calls.length;
    heading().focus();
    if (document.activeElement!==heading() || calls.length!==requests)
      failures.push('focus the same heading without a request');
    if (read==='continuation') {
      changes.waitContinuation=pending;
      app.el.querySelector('[data-wiki-stage2-action="read"]').click();
    }
    if (move==='outside') outside.focus();
    if (move==='stage') {app.stage=3;livePaint();}
    if (move==='project') {rt.ref='SYNTHETIC-B';rt.epoch++;livePaint();}
    release();await tick();
    const expected=move==='outside'?outside:move?document.body:heading();
    if (document.activeElement!==expected)
      failures.push(read+(move?' preserves navigation or new focus ('+move+')':' retains heading after repaint'));
    if (calls.some(call=>call.body)) failures.push('no POST during discovery');
  }
  if (failures.length) throw Error(failures.join(' | '));
}

async function exerciseStaticPlanningRead() {
  const controller = {status:'unavailable',reason:'stage2-controller-profile-unavailable',
    profile_sha256:null,connection_id:null,receipt_id:null};
  const stage2Only = {'stage2-controller':controller};
  const unavailable = {...controller,reason:'stage3-current-selection-required'};
  const connected = {...controller,status:'connected',reason:null};
  const fallback = {response:{connections:stage2Only}};
  const scenarios = [
    ['#546 Stage 2-only response, listed',fallback,true,true,false],
    ['#546 Stage 2-only response, unlisted',fallback,false,false,false],
    ['explicit Stage 3 unavailable',{response:{connections:{...stage2Only,'stage3-planning':unavailable}}},true,false,false],
    ['stale conflict',{getError:'stage3-planning-project-stale',http:409},true,false,false],
    ['access denied',{getError:'credential-rejected',http:403},true,false,false],
    ['verified Stage 3 connection',{response:{connections:{...stage2Only,'stage3-planning':connected}}},false,true,true],
    ['older Host whole-interface 404',{getError:'not-found',http:404},true,true,true],
    ['wrong connection project',{response:{connections:stage2Only,project_ref:'SYNTHETIC-B'}},true,false,false],
    ['wrong execution flag',{response:{connections:stage2Only,execution_authorized:true}},true,false,false],
    ['unexpected response field',{response:{connections:stage2Only,extra:true}},true,false,false],
    ['missing rows',{response:{connections:{}}},true,false,false],
    ['null controller',{response:{connections:{'stage2-controller':null}}},true,false,false],
    ['invalid controller status',{response:{connections:{'stage2-controller':{...controller,status:'unknown'}}}},true,false,false],
    ['malformed controller receipt',{response:{connections:{'stage2-controller':{...controller,receipt_id:'unexpected'}}}},true,false,false],
    ['extra controller field',{response:{connections:{'stage2-controller':{...controller,unexpected:true}}}},true,false,false],
    ['explicit null Stage 3',{response:{connections:{...stage2Only,'stage3-planning':null}}},true,false,false],
    ['unexpected extra connection',{response:{connections:{...stage2Only,other:controller}}},true,false,false],
    ['wrong project ID',{...fallback,overview:{project_id:'SYNTHETIC-OTHER'}},true,false,false],
    ['wrong revision',{...fallback,overview:{revision:999}},true,false,false],
    ['wrong brief pin',{...fallback,overview:{brief_sha256:'e'.repeat(64)}},true,false,false],
    ['noninteger input',{...fallback,overview:{input_version:'1'}},true,false,false],
    ['connection receipt pending',fallback,true,false,false,true],
  ];
  const tick=()=>new Promise(resolve=>setTimeout(resolve,10));
  const defects=[];
  for (const [name,config,listed,readable,hasWorkflowLink,pending] of scenarios) {
    window.changes=config;calls.length=0;app.stage=3;
    window.RESEARCH_PROJECTS.stage3_planning_projects=listed?[project.project_ref]:[];
    rt.pending=pending?{ref:project.project_ref,path:projectPath(project.project_ref,'connections')}:null;
    await liveRefresh();await tick();
    const read=app.el.querySelector('[data-v93-read]');
    const graph=app.el.querySelector('#v93-diagram');
    const workflowLink=app.el.querySelector('a[href^="/project-stage3-planning.html"]');
    if (!!read!==readable || !!graph!==readable || !!workflowLink!==hasWorkflowLink ||
        app.el.querySelector('[data-v9-connection="connect"]')) defects.push(name+' controls');
    if (read) {
      read.click();await tick();
      if (calls.filter(call=>call.tail==='stage3/planning'&&!call.body).length!==1) defects.push(name+' read');
    }
    if (calls.some(call=>call.body)) defects.push(name+' POST');
  }
  if (defects.length) throw Error(defects.join(' | '));
}

// One headless Chrome per test file (each file is its own Node process); every exercise gets a new page.
// Starting the browser and running the page are limited separately: a cold Windows runner may need a long
// time to start Chrome, but a page that does not finish within PAGE_LIMIT_MS is a real hang and fails fast.
const STARTUP_LIMIT_MS = 90000;
const PAGE_LIMIT_MS = 10000;
let browserPromise = null;

function findChrome() {
  return [process.env.CHROME_BIN, process.env.CHROME_PATH,
    'C:/Program Files/Google/Chrome/Application/chrome.exe','/usr/bin/google-chrome','/usr/bin/chromium',
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'].find(p=>p&&existsSync(p));
}

function killTree(child) {
  if (!child || child.exitCode !== null || child.pid === undefined) return;
  if (process.platform === 'win32') spawnSync('taskkill',['/PID',String(child.pid),'/T','/F'],{stdio:'ignore',timeout:15000});
  else { try { child.kill('SIGKILL'); } catch {} }
}

function launchBrowser() {
  const chrome=findChrome();
  assert.ok(chrome,'Chrome or Chromium is required (or set CHROME_BIN)');
  const temp=mkdtempSync(join(tmpdir(),'pr4-connections-'));
  const started=Date.now();
  const child=spawn(chrome,['--headless','--disable-gpu','--disable-background-networking','--no-first-run',
    '--remote-debugging-port=0','--user-data-dir='+join(temp,'profile'),'about:blank'],{stdio:['ignore','ignore','pipe'],windowsHide:true});
  let stderr='';
  child.stderr.on('data',chunk=>{stderr=(stderr+chunk).slice(-4000);});
  const state={chrome,temp,child,ws:null,nextId:1,pending:new Map(),startupMs:0,stderr:()=>stderr,exited:false};
  child.on('exit',()=>{state.exited=true;});
  process.on('exit',()=>{killTree(child);});
  const portFile=join(temp,'profile','DevToolsActivePort');
  return (async()=>{
    while (!existsSync(portFile)) {
      if (state.exited) throw Error('Chrome exited before it was ready: '+stderr);
      if (Date.now()-started>STARTUP_LIMIT_MS) throw Error('Chrome did not start within '+STARTUP_LIMIT_MS+' ms (browser startup, not the page): '+stderr);
      await new Promise(resolve=>setTimeout(resolve,50));
    }
    let lines;
    for (;;) {  // Chrome may still hold the file (EBUSY on Windows) or have written only one line
      try {
        lines=readFileSync(portFile,'utf8').split('\n');
        if (lines.length>=2&&lines[1]) break;
      } catch (error) {
        if (!['EBUSY','EPERM','EACCES','ENOENT'].includes(error.code)) throw error;
      }
      if (state.exited) throw Error('Chrome exited before it was ready: '+stderr);
      if (Date.now()-started>STARTUP_LIMIT_MS) throw Error('DevToolsActivePort stayed unreadable or incomplete: '+stderr);
      await new Promise(resolve=>setTimeout(resolve,50));
    }
    const ws=new WebSocket('ws://127.0.0.1:'+lines[0].trim()+lines[1].trim());
    await new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>reject(Error('DevTools connection timed out after browser start: '+stderr)),Math.max(1000,STARTUP_LIMIT_MS-(Date.now()-started)));
      ws.addEventListener('open',()=>{clearTimeout(timer);resolve();});
      ws.addEventListener('error',()=>{clearTimeout(timer);reject(Error('DevTools connection failed: '+stderr));});
    });
    ws.addEventListener('message',event=>{
      const message=JSON.parse(event.data), waiting=state.pending.get(message.id);
      if (!waiting) return;
      state.pending.delete(message.id);
      if (message.error) waiting.reject(Error(message.error.message)); else waiting.resolve(message.result);
    });
    const failPending=reason=>{
      for (const waiting of state.pending.values()) waiting.reject(Error(reason));
      state.pending.clear();
    };
    ws.addEventListener('close',()=>failPending('DevTools connection closed: '+stderr));
    ws.addEventListener('error',()=>failPending('DevTools connection failed: '+stderr));
    state.ws=ws;
    state.startupMs=Date.now()-started;
    return state;
  })().catch(error=>{killTree(child);throw error;});
}

// Every DevTools call has an upper bound, so a lost reply can never hang the test file.
function cdp(state,method,params={},sessionId,limitMs=PAGE_LIMIT_MS*3) {
  const id=state.nextId++;
  return new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>{state.pending.delete(id);reject(Error('DevTools call '+method+' got no reply within '+limitMs+' ms'));},limitMs);
    state.pending.set(id,{resolve:value=>{clearTimeout(timer);resolve(value);},reject:error=>{clearTimeout(timer);reject(error);}});
    try { state.ws.send(JSON.stringify({id,method,params,...(sessionId?{sessionId}:{})})); }
    catch (error) { clearTimeout(timer);state.pending.delete(id);reject(error); }
  });
}

async function closeBrowser() {
  if (!browserPromise) return;
  const promise=browserPromise;
  browserPromise=null;
  let state;
  try { state=await promise; } catch { return; }
  try { state.ws.close(); } catch {}
  killTree(state.child);
  if (!state.exited) await new Promise(resolve=>{const timer=setTimeout(resolve,5000);state.child.once('exit',()=>{clearTimeout(timer);resolve();});});
  rmSync(state.temp,{recursive:true,force:true,maxRetries:8,retryDelay:100});
}

async function runChromeExercise(exercise, runtimeHooks='') {
  browserPromise ||= launchBrowser();
  const state=await browserPromise;
  const temp=mkdtempSync(join(tmpdir(),'pr4-connections-page-'));
  let targetId;
  try {
    const runtime=source('renderer/src/runtime.js');
    const actions=runtime.slice(runtime.indexOf('async function liveReceiptBound('),runtime.indexOf('const liveDisabled='));
    const scripts=[`(${browserFixture})();`, actions, runtimeHooks, ...['stage2_display.js','v9-stage-connections.js','v9-stage3-bridge.js'].map(source),
      `(${exercise})().then(()=>document.title='SYNTHETIC_PASS',e=>document.title='FAIL '+e.stack);`];
    const html=join(temp,'fixture.html');
    writeFileSync(html,'<!doctype html><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src \'unsafe-inline\'"><title>RUNNING</title><main></main>'+
      scripts.map(s=>'<script>'+s.replaceAll('</script','<\\/script')+'</script>').join(''));
    ({targetId}=await cdp(state,'Target.createTarget',{url:pathToFileURL(html).href}));
    const {sessionId}=await cdp(state,'Target.attachToTarget',{targetId,flatten:true});
    const began=Date.now();
    let title='';
    // Strict page limit: this is the time for the page's own work, not for starting the browser.
    while (Date.now()-began<PAGE_LIMIT_MS) {
      const result=await cdp(state,'Runtime.evaluate',{expression:'document.title',returnByValue:true},sessionId);
      title=String(result.result?.value??'');
      if (title==='SYNTHETIC_PASS'||title.startsWith('FAIL ')) break;
      await new Promise(resolve=>setTimeout(resolve,25));
    }
    assert.equal(title,'SYNTHETIC_PASS','page did not pass within '+PAGE_LIMIT_MS+' ms (browser had started in '+state.startupMs+' ms); title='+title+(state.stderr()?'\nChrome stderr: '+state.stderr():''));
  } finally {
    if (targetId) { try { await cdp(state,'Target.closeTarget',{targetId}); } catch {} }
    rmSync(temp,{recursive:true,force:true,maxRetries:8,retryDelay:100});
  }
}
module.exports = {runChromeExercise, closeBrowser};
if (require.main === module) {
test.after(()=>closeBrowser());
test('SYNTHETIC stage connections through the served renderer functions and real button clicks',
  ()=>runChromeExercise(exercise));
test('SYNTHETIC ordinary Stage 2 unified request controls and original not-connected 409',
  ()=>runChromeExercise(exerciseUnreadyStage2));
test('SYNTHETIC Stage 2 keeps the connection heading focused during discovery repaint',
  ()=>runChromeExercise(exerciseStage2ConnectionFocus));
test('SYNTHETIC Stage 3 static saved planning on the Stage 2-only Host contract',
  ()=>runChromeExercise(exerciseStaticPlanningRead));
}
