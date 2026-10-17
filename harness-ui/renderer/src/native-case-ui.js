// Independent admitted native case task; historical source records stay read-only.
const nc={cases:[],pending:null,job:null,result:null,error:'',busy:false,epoch:0,restoreProject:true,timer:null};
const ncSlot='v7-native-case-intent-v1';
try{nc.pending=JSON.parse(sessionStorage.getItem(ncSlot)||'null');}catch(_){nc.error='native-intent-storage-invalid';}
async function ncRequest(path,body){
 const response=await fetch('/api/v7/stage1/'+path,{method:body?'POST':'GET',headers:{Authorization:'Bearer '+window.RESEARCH_PROJECTS.credential,...(body?{'Content-Type':'application/json'}:{})},body:body?JSON.stringify(body):undefined,cache:'no-store',credentials:'same-origin'});
 const value=await response.json();if(!response.ok)throw Error(value.error||'native-request-rejected');return value;
}
function ncProject(){return rt.savedRun?.binding.project_id||rt.overview?.project?.project_id||rt.overview?.project?.project_ref;}
function ncCase(){return nc.cases.find(c=>c.project_id===ncProject()&&c.project_ref===rt.ref)||null;}
function ncPollWithinWindow(now=Date.now()){
 const started=nc.pending?.created_at;
 return typeof started==='number'&&Number.isFinite(started)&&Number.isFinite(now)&&now-started>=0&&now-started<180000;
}
function ncProgress(job){
 if(job?.delivery_status==='validated-by-collector'){
  const shown=nc.result?.native_job_ref===job.job_ref&&rt.savedRun?.native_job_ref===job.job_ref
   &&nc.result.project_ref===rt.ref&&rt.savedRun.project_ref===rt.ref
   &&nc.result.binding.project_id===job.project_id&&rt.savedRun.binding.project_id===job.project_id;
  return shown?rl('本次输出已核验并更新到下方结果','Output verified and updated below','本次輸出已核驗並更新到下方結果')
   :rl('服务产物已核验，页面结果待载入或恢复','Service output verified; page result awaits loading or recovery','服務產物已核驗，頁面結果待載入或恢復');
 }
 if(job?.delivery_status==='validating')return rl('Codex 已返回，正在核验 Harness 产物','Codex returned; checking Harness artifacts','Codex 已返回，正在核驗 Harness 產物');
 if(job?.status==='running')return rl('Codex 任务运行中','Codex task running','Codex 任務執行中')+' · '+(job.latest_native_event?.item_type||job.latest_native_event?.method||'awaiting-native-event');
 return rl('原始任务状态','Original task status','原始任務狀態')+' · '+(job?.status||'not-started');
}
function ncPanel(app){
 const c=ncCase();if(!c||app.stage!==1)return '';
 const j=nc.job?.case_ref===c.ref?nc.job:null;
 return `<section class="hs-panel" data-native-case-panel><div class="hs-panel-head"><h2>${rl('真实 Codex → Harness 案例任务','Real Codex → Harness case task','真實 Codex → Harness 案例任務')}</h2><span class="hs-status">${rx(j?.status||'not-started')}</span></div><p>${rx(c.label)}</p><p>${rl('使用已保存来源验证调用链；不新增搜索，不代表新研究或科学验收完成。','Verify the call chain with saved sources; no new search or scientific completion.','使用已保存來源驗證呼叫鏈；不新增搜尋，不代表新研究或科學驗收完成。')}</p><p>${rx(c.model)} / ${rx(c.effort)} · ${rl('内部推理次数和费用按实际回执记录，缺失为 Unknown。','Internal inference count and cost follow actual receipts; missing values remain Unknown.','內部推理次數和費用依實際回執記錄，缺失為 Unknown。')}</p><label><input type="checkbox" data-native-case-confirm> ${rl('确认执行这一项独立任务并保留输出和失败','Confirm this independent task and retain outputs and failures','確認執行這項獨立任務並保留輸出與失敗')}</label><div class="lp-inline-actions"><button class="hs-button hs-button-primary" data-native-case-start ${nc.pending||nc.busy||j||c.last_job_ref?'disabled':''}>${rl('运行已登记案例任务','Run registered case task','執行已登記案例任務')}</button><button class="hs-button" data-native-case-refresh>${rl('读取进度与结果','Read progress & result','讀取進度與結果')}</button></div>${nc.error?`<p class="live-error">${rx(nc.error)}</p>`:''}<details data-native-case-feedback><summary>${rl('本次任务进度、回执与交付','Task progress, receipt & delivery','本次任務進度、回執與交付')}</summary><pre class="live-record">${rx(JSON.stringify(j||{status:'not-started'},null,2))}</pre></details></section>`;
}
const ncOriginalPanel=ncPanel;
ncPanel=function(app){const html=ncOriginalPanel(app);return html?html.replace('<details data-native-case-feedback>',`<p class="live-callout">${rx(ncProgress(nc.job?.case_ref===ncCase()?.ref?nc.job:null))}</p><details data-native-case-feedback>`):html;};
const ncOldOps=canonicalOperations;
canonicalOperations=app=>{const original=ncOldOps(app),panel=ncPanel(app);return panel?original.replace(/<\/div><\/details>$/,panel+'</div></details>'):original;};
const ncOldControls=realControls;
realControls=function(...args){return ncOldControls(...args)+ncPanel(apps[0]);};
const ncOldBadge=canonicalBadge;
canonicalBadge=function(run){return run?.native_job_ref?rl('本次真实 Codex/Harness 调用 · 历史来源重导出','Actual Codex/Harness call · historical sources re-exported','本次真實 Codex/Harness 呼叫 · 歷史來源重新匯出'):ncOldBadge(run);};
async function ncRefresh(){
 clearTimeout(nc.timer);nc.timer=null;
 const epoch=++nc.epoch,ref=rt.ref;
 try{
  const catalogue=await ncRequest('cases');if(epoch!==nc.epoch||ref!==rt.ref)return;
  if(catalogue.kind!=='V7NativeStage1Catalogue'||!Array.isArray(catalogue.cases))throw Error('native-catalogue-invalid');
  nc.cases=catalogue.cases;
  const current=ncCase();
  const observed=nc.pending||(current?.last_job_ref?{case_ref:current.ref,spec_sha256:current.spec_sha256,job_ref:current.last_job_ref}:null);
  if(observed){
   const c=nc.cases.find(v=>v.ref===observed.case_ref);
   if(!c||c.spec_sha256!==observed.spec_sha256)throw Error('native-intent-binding-changed');
   if(nc.restoreProject){nc.restoreProject=false;if(!rt.pending&&rt.ref!==c.project_ref){await liveRefresh(c.project_ref,{list:true});return;}}
   const job=await ncRequest('jobs/'+observed.job_ref);if(epoch!==nc.epoch||ref!==rt.ref)return;
   if(job.job_ref!==observed.job_ref||job.case_ref!==c.ref||job.spec_sha256!==c.spec_sha256||job.project_id!==c.project_id)throw Error('native-job-binding-differs');
   nc.job=job;
   if(job.delivery_status==='validated-by-collector'&&job.delivery?.result_url){
    if(job.delivery.result_url!=='/api/v7/stage1/jobs/'+job.job_ref+'/result')throw Error('native-result-route-differs');
    const result=await ncRequest('jobs/'+job.job_ref+'/result');
    if(epoch!==nc.epoch||ref!==rt.ref)return;
    if(result.kind!=='V7NativeDeliveredResult'||result.job_ref!==job.job_ref||result.case_ref!==c.ref||result.project_ref!==c.project_ref||result.entry?.project_ref!==c.project_ref||result.entry?.project_id!==c.project_id)throw Error('native-result-binding-differs');
    const decoded=await canonicalDecode(result.envelope,result.entry);
    if(decoded.binding.project_id!==c.project_id)throw Error('native-result-project-differs');
    if(epoch!==nc.epoch||ref!==rt.ref)return;
    nc.result={...decoded,native_job_ref:job.job_ref,project_ref:result.project_ref};
   }
  }
  nc.restoreProject=false;
  if(nc.result?.project_ref===rt.ref&&nc.result.binding.project_id===ncProject()){rt.savedRun=nc.result;rt.atlas={payload:nc.result.payload};}
  nc.error='';
 }catch(error){if(epoch===nc.epoch&&ref===rt.ref)nc.error=error.message;}
 if(epoch===nc.epoch&&ref===rt.ref)livePaint();
 if(epoch===nc.epoch&&ncPollWithinWindow()
    &&(['intent-recorded','running'].includes(nc.job?.status)||nc.job?.delivery_status==='validating'))nc.timer=setTimeout(()=>ncRefresh(),5000);
}
const ncOldRefresh=liveRefresh;
liveRefresh=async function(...args){nc.epoch++;await ncOldRefresh(...args);await ncRefresh();};
document.addEventListener('click',async event=>{
 const start=event.target.closest('[data-native-case-start]'),refresh=event.target.closest('[data-native-case-refresh]');
 if(!start&&!refresh)return;event.preventDefault();event.stopImmediatePropagation();
 if(refresh){await ncRefresh();return;}
 const c=ncCase();
 if(!c||apps[0].stage!==1||nc.pending||nc.busy||c.last_job_ref||!apps[0].el.querySelector('[data-native-case-confirm]')?.checked)return;
 nc.busy=true;
 try{
  const key=crypto.randomUUID();const job_ref='native-'+await canonicalHash(key);
  const pending={case_ref:c.ref,spec_sha256:c.spec_sha256,key,job_ref,created_at:Date.now()};
  sessionStorage.setItem(ncSlot,JSON.stringify(pending));
  if(sessionStorage.getItem(ncSlot)!==JSON.stringify(pending))throw Error('native-intent-save-failed');
  nc.pending=pending;livePaint();
  nc.job=await ncRequest('runs',{case_ref:c.ref,key,spec_sha256:c.spec_sha256,confirmed:true});
 }catch(error){nc.error=error.message;}finally{nc.busy=false;livePaint();if(nc.pending)await ncRefresh();}
},true);
Promise.resolve().then(()=>ncRefresh());
