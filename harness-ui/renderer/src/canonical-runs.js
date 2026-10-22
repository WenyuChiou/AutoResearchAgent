// Projection of existing Harness outputs. These registrations grant no execution.
rt.savedViews=[];rt.savedRun=null;rt.savedRosterReady=false;
const canonicalOldRequest=liveRequest,canonicalOldRefresh=liveRefresh,canonicalOldPaint=livePaint;
const canonicalOldPost=livePost;
function canonicalRef(ref){return typeof ref==='string'&&ref.startsWith('view:')?ref.slice(5):null;}
function canonicalEntry(ref=rt.ref){return rt.savedViews.find(v=>v.project_ref===ref)||null;}
function canonicalReadonly(){return canonicalRef(rt.ref)!==null;}
livePost=async function(...args){if(canonicalReadonly()){rt.error='saved-view-readonly';livePaint();return;}return canonicalOldPost(...args);};
async function canonicalHash(text){return [...new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(text)))].map(b=>b.toString(16).padStart(2,'0')).join('');}
async function canonicalDecode(value,entry){
 if(!value||value.kind!=='V7CanonicalSavedView'||value.execution_authority!==false||typeof value.payload_json!=='string')throw Error('saved-view-envelope-differs');
 const b=value.binding;
 if(!b||b.kind!=='V7CanonicalSavedViewBinding'||b.schema_version!=='1.0.0'||b.view_ref!==entry.ref||b.project_id!==entry.project_id||b.fixture!==entry.fixture||b.manifest_sha256!==entry.manifest_sha256||b.index_sha256!==entry.index_sha256||await canonicalHash(value.payload_json)!==b.payload_sha256)throw Error('saved-view-binding-differs');
 const payload=JSON.parse(value.payload_json);
 if(!payload.index||payload.index.project_id!==b.project_id||payload.index_sha256!==b.index_sha256||!Array.isArray(payload.index.papers)||!Array.isArray(payload.index.claims))throw Error('saved-view-project-differs');
 return {entry,binding:b,payload};
}
liveRequest=async function(path,body){
 if(body&&canonicalReadonly())throw Error('saved-view-readonly');
 if(path!=='/api/projects'||body)return canonicalOldRequest(path,body);
 const [projects,saved]=await Promise.all([canonicalOldRequest(path),canonicalOldRequest('/v7-saved-runs.json')]);
 if(saved.kind!=='V7CanonicalSavedViewList'||saved.execution_authority!==false||!Array.isArray(saved.views)||saved.views.length>16)throw Error('saved-view-list-differs');
 const seen=new Set();
 for(const v of saved.views){if(!v||typeof v.ref!=='string'||!/^[A-Za-z0-9_-]{1,64}$/.test(v.ref)||v.project_ref!=='view:'+v.ref||typeof v.project_id!=='string'||typeof v.fixture!=='boolean'||v.execution_authority!==false||v.payload_url!=='/v7-saved-runs/'+v.ref+'.json'||seen.has(v.ref))throw Error('saved-view-list-binding-differs');seen.add(v.ref);}
 rt.savedViews=saved.views;rt.savedRosterReady=true;
 return {projects:[...(Array.isArray(projects)?projects:projects.projects||[]),...saved.views.map(v=>({project_ref:v.project_ref,topic:v.label}))]};
};
livePaint=function(){
 if(!canonicalReadonly())return canonicalOldPaint();
 const app=apps[0],run=rt.savedRun;
 app.previewProject={id:rt.ref||'saved',topic:run?.entry.label||canonicalEntry()?.label||rl('正在读取保存记录','Loading saved record','正在讀取保存紀錄'),hasResults:!!run};
 render(app);
};
liveRefresh=async function(ref=rt.ref,options={}){
 // The retained runtime starts its first project GET before this module is installed.
 // Load the combined roster once before choosing the initial project/view.
 if(!rt.savedRosterReady){const list=await liveRequest('/api/projects');rt.list=list.projects;if(!ref)ref=rt.pending?.ref||rt.meta?.case_ref||rt.list[0]?.project_ref;}
 if(!canonicalRef(ref)){rt.savedRun=null;return canonicalOldRefresh(ref,options);}
 const epoch=++rt.epoch;rt.ref=ref;rt.loading=true;rt.error='';rt.savedRun=null;rt.overview=null;rt.atlas=null;rt.library=null;rt.history=null;rt.native=null;rt.modelHistory=null;rt.file=null;rt.selected=null;rt.focus=null;rt.draft='';livePaint();
 try{
  if(options.list){const list=await liveRequest('/api/projects');if(epoch!==rt.epoch)return;rt.list=list.projects;}
  const entry=canonicalEntry(ref);if(!entry)throw Error('saved-view-not-registered');
  const value=await canonicalOldRequest(entry.payload_url),run=await canonicalDecode(value,entry);
  if(epoch!==rt.epoch||ref!==rt.ref)return;
  rt.savedRun=run;rt.atlas={payload:run.payload};rt.selected=run.payload.index.papers[0]?.work_id||null;
 }catch(error){if(epoch===rt.epoch&&ref===rt.ref){rt.error=error.message;rt.savedRun=null;rt.atlas=null;}}
 finally{if(epoch===rt.epoch&&ref===rt.ref){rt.loading=false;livePaint();}}
};
function canonicalBadge(run){return run?.binding.fixture?rl('仓库合成 case · 不是研究结果','Repository synthetic case · not research findings','倉庫合成 case · 不是研究結果'):rl('Harness 历史保存记录 · 不代表本次重新运行','Historical Harness records · not a new run','Harness 歷史保存紀錄 · 不代表本次重新執行');}
function canonicalTop(){return `<div class="canonical-project-switch"><label><span>${rl('当前项目','Current project','目前專案')}</span><select data-live-project>${rt.list.map(p=>`<option value="${rx(p.project_ref)}" ${p.project_ref===rt.ref?'selected':''}>${rx(p.topic||p.project_ref)}</option>`).join('')}</select></label></div>`;}
function canonicalHeading(app){const run=rt.savedRun,names={1:['文献知识网络','Literature knowledge network','文獻知識網路'],2:['研究方向比较工作台','Research comparison workbench','研究方向比較工作臺'],3:['设计与可行性','Design & feasibility','設計與可行性'],4:['实验执行','Experiment execution','實驗執行'],5:['分析与图表','Analysis & figures','分析與圖表'],6:['写作与投稿','Writing & submission','寫作與投稿']};return `<div class="hs-heading"><div><p class="hs-eyebrow">STAGE ${String(app.stage).padStart(2,'0')} / 06</p><h1>${rl(...(names[app.stage]||['Unknown','Unknown','Unknown']))}</h1></div><span class="hs-status">${app.stage>2?rl('规划中 · 尚未接通','Planned · unconnected','規劃中 · 尚未接通'):canonicalBadge(run)}</span></div>${rt.error?`<p class="live-error">${rx(rt.error)}</p>`:''}`;}
function canonicalOperations(app){
 if(app.stage===1){
  const run=rt.savedRun,index=run?.payload?.index,stage=Array.isArray(index?.stages)?index.stages.find(row=>row?.stage===1):null;
  const count=rows=>Array.isArray(rows)?rows.length:null;
  const statuses=rows=>Array.isArray(rows)?[...new Set(rows.map(row=>row?.status).filter(value=>value!==undefined&&value!==null))].join(' · ')||null:null;
  const saved=(rows,zh,en,tw=zh)=>`${rl(zh,en,tw)}: ${rx(count(rows))}`;
  const items=[
   [rl('选题与范围','Topic & scope','選題與範圍'),`${rl('保存选题','Saved topic','保存選題')}: ${rx(index?.topic)} · ${rl('范围确认','Scope confirmation','範圍確認')}: Unknown`],
   [rl('文献检索','Literature search','文獻檢索'),saved(index?.search,'保存检索记录','Saved search records','保存檢索紀錄')+' · '+rl('执行状态','Execution state','執行狀態')+': Unknown'],
   [rl('获取来源','Source acquisition','取得來源'),saved(index?.sources,'保存来源记录','Saved source records','保存來源紀錄')+' · '+rl('执行状态','Execution state','執行狀態')+': Unknown'],
   [rl('文献筛选','Screening','文獻篩選'),saved(index?.screening,'保存筛选记录','Saved screening records','保存篩選紀錄')+' · '+rl('原记录状态','Recorded states','原紀錄狀態')+': '+rx(statuses(index?.screening))],
   [rl('阅读与证据','Reading & evidence','閱讀與證據'),saved(index?.claims,'保存主张记录','Saved claim records','保存主張紀錄')+' · '+rl('阅读完成状态','Reading completion','閱讀完成狀態')+': Unknown'],
   [rl('交付与版本','Delivery & version','交付與版本'),`${rl('保存状态','Saved state','保存狀態')}: ${rx(index?.status)} · ${rl('记录版本','Records schema','紀錄版本')}: ${rx(index?.schema_version)}`],
   [rl('人工审阅','Human review','人工審閱'),`${rl('人工审阅状态','Human review state','人工審閱狀態')}: Unknown · ${rl('保存准入记录','Saved readiness record','保存准入紀錄')}: ${rx(index?.readiness?.status)}`]
  ];
   return `<details class="lp-operations hs-panel" data-canonical-saved-operations data-local-operations="1" ${app.previewOps?.[1]?'open':''}><summary><strong>Stage1 · ${rl('操作与保存状态','Operations & saved state','操作與保存狀態')}</strong></summary><div class="lp-ops-body"><button class="hs-button" data-live-action="refresh" ${rt.loading?'disabled':''}>${rl('重新读取保存结果','Reload saved output','重新讀取保存結果')}</button><p>${rl('记录数量仅表示已保存内容；执行与完成状态按原记录判断。','Record counts describe saved content; execution and completion follow original records.','紀錄數量僅表示已保存內容；執行與完成狀態依原紀錄判斷。')}</p><dl>${items.map(([name,value])=>`<dt>${name}</dt><dd>${value}</dd>`).join('')}</dl><p>${rl('阶段模块连接','Stage module connection','階段模組連接')}: ${rx(stage?.support_status)} · ${rl('执行接口已启用','Execution interface enabled','執行介面已啟用')}: ${rx(stage?.execution_enabled)} · ${rl('原生会话连接','Native session connection','原生會話連接')}: ${rx(index?.native_session?.status)}</p><p>${rl('保存视图不发起检索、模型或阶段执行。真实项目继续使用原操作入口与许可。','Saved views start no search, model or stage execution. Live projects keep their existing operation entry points and permissions.','保存視圖不發起檢索、模型或階段執行。真實專案繼續使用原操作入口與許可。')}</p></div></details>`;
 }
return `<details class="lp-operations hs-panel" data-local-operations="${app.stage}" ${app.previewOps?.[app.stage]?'open':''}><summary><strong>Stage${app.stage} · ${rl('操作','Operations','操作')}</strong></summary><div class="lp-ops-body"><p>${rl('这里读取 Harness 已保存的阶段输出。正式阶段命令已存在，当前保存视图没有模型或阶段执行权限。','This view reads saved Harness output. Canonical stage commands exist; this saved view has no model or stage execution authority.','這裡讀取 Harness 已保存的階段輸出。正式階段命令已存在，目前保存視圖沒有模型或階段執行權限。')}</p><button class="hs-button" data-live-action="refresh" ${rt.loading?'disabled':''}>${rl('重新读取保存结果','Reload saved output','重新讀取保存結果')}</button><button class="hs-button" disabled>${rl('运行当前阶段 · 尚未接线','Run this stage · adapter unconnected','執行目前階段 · 尚未接線')}</button></div></details>`;}
function canonicalStage1Results(app){const run=rt.savedRun;return `<details class="lp-results" data-local-results="1" ${app.previewResultsOpen[1]!==false?'open':''}><summary><strong>Stage1 · ${rl('结果','Results','結果')}</strong><span>${run?rl('已保存','Saved','已保存'):rl('尚未读取','Not loaded','尚未讀取')}</span></summary><div class="lp-result-body">${!run?`<section class="hs-panel lp-empty"><h2>${rt.loading?rl('正在读取…','Loading…','正在讀取…'):rl('没有可验证的结果','No verified result','沒有可驗證的結果')}</h2></section>`:`<section class="hs-panel"><div class="hs-panel-head"><h2>${rl('文献知识网络','Literature knowledge network','文獻知識網路')}</h2><span class="hs-status">${rows().length} ${rl('条文献记录','literature records','筆文獻紀錄')}</span></div><div class="hs-atlas-grid">${liveGraph()}${liveDetails()}</div></section>${liveLibrary()}`}</div></details>`;}
function canonicalStage2Results(app){const run=rt.savedRun;const validated=run?canonicalStage2Validate(run.payload,run.binding):{ok:false,reason:'not-loaded'};return `<details class="lp-results" data-local-results="2" ${app.previewResultsOpen[2]!==false?'open':''}><summary><strong>Stage2 · ${rl('结果','Results','結果')}</strong><span>${validated.ok?rl('已保存','Saved','已保存'):rl('尚未生成可显示的 Stage2 结果','No displayable Stage2 result','尚未產生可顯示的 Stage2 結果')}</span></summary><div class="lp-result-body">${canonicalStage2Render(app,validated)}</div></details>`;}
function canonicalFeedback(app){const run=rt.savedRun,index=run?.payload.index;return `<details class="hs-panel" data-canonical-feedback><summary>Stage${app.stage} · ${rl('运行反馈与来源','Run feedback & provenance','執行回饋與來源')}</summary><p>${canonicalBadge(run)}</p><p>${rl('保留 Harness 原始状态、Unknown 和限制。载入页面不启动研究；保存文件不等于阶段完成。','Original Harness status, Unknown and limitations are retained. Loading starts no research; saved files do not imply stage completion.','保留 Harness 原始狀態、Unknown 與限制。載入頁面不啟動研究；保存檔案不等於階段完成。')}</p><pre class="live-record">${rx(JSON.stringify({binding:run?.binding??null,stage1_status:index?.status??null,readiness:index?.readiness??null,stage_states:index?.stages??null,stage1_summary:index?.summary??null,stage2_status:run?.payload.stage2?.selection?.status??null,stage2_blockers:run?.payload.stage2?.selection?.blocking_items??null},null,2))}</pre></details>`;}
const canonicalStage1Previous=stage1,canonicalStage2Previous=stage2;
stage1=app=>canonicalReadonly()?`${canonicalTop()}${canonicalHeading(app)}${canonicalStage1Results(app)}${canonicalOperations(app)}${canonicalFeedback(app)}`:canonicalStage1Previous(app);
stage2=app=>canonicalReadonly()?`${canonicalHeading(app)}${canonicalStage2Results(app)}${canonicalOperations(app)}${canonicalFeedback(app)}`:canonicalStage2Previous(app);
const canonicalChromePrevious=realChromeStatus,canonicalOtherPrevious=otherPage;
const canonicalLaterPrevious=laterStage;
realChromeStatus=function(){if(!canonicalReadonly())return canonicalChromePrevious();return {project:rt.savedRun?.binding.project_id||rl('正在读取保存记录','Loading saved record','正在讀取保存紀錄'),model:rl('保存视图 · 不执行模型','Saved view · no model execution','保存視圖 · 不執行模型'),counts:rows().length+' '+rl('条文献记录','literature records','筆文獻紀錄'),footer:canonicalBadge(rt.savedRun)};};
otherPage=app=>canonicalReadonly()?`${canonicalHeading(app)}${canonicalFeedback(app)}`:canonicalOtherPrevious(app);
laterStage=app=>canonicalReadonly()?`${canonicalHeading(app)}<section class="hs-panel lp-empty"><h2>Stage${app.stage} · ${rl('规划中 · 尚未接通','Planned · unconnected','規劃中 · 尚未接通')}</h2><p>${rl('当前没有这个阶段的输出或执行接口。','No output or execution interface for this stage.','目前沒有這個階段的輸出或執行介面。')}</p></section>`:canonicalLaterPrevious(app);
// Capture before existing handlers: saved views cannot acquire execution rights.
document.addEventListener('click',event=>{
 if(!canonicalReadonly())return;
 const button=event.target.closest('[data-live-action],[data-real-action],[data-v7-control]');if(!button)return;
 const action=button.dataset.liveAction;if(['refresh','all'].includes(action))return;
 event.preventDefault();event.stopImmediatePropagation();rt.error='saved-view-readonly';livePaint();
},true);

// Read-only field expansion and pagination; no model or stage actions.
canonicalStage2Mount(document);
