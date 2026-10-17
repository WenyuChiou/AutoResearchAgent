// Imported inputs and active operations have separate identities and authority.
const p9={views:new Map(),original:null,shown:null,epoch:0,loading:false,attempted:new Set()};
const p9BaseActive=n2Active;
n2Active=()=>p9.views.has(rt.ref)||p9BaseActive();
function p9State(view){
 const packet=JSON.parse(view.packet_text),model=n2BuildModel(packet,null,view.cards);
 return {meta:{packet_json_sha256:view.packet_file_sha256,selection_json_sha256:'unassessed',documents:[],attachments:[]},
  model,comparison:{},named:null,papers:model.sources.slice(0,2).map(s=>s.source_id),
  routes:model.routes.slice(0,2).map(r=>r.candidate.candidate_id),view:'routes',evidence:null,
  records:new Map(),raw:null,document:null,documents:new Map(),pending:new Set(),errors:new Map(),
  filePage:0,search:'',draft:null,note:'',draftStatus:'not-saved',loading:false,error:null};
}
function p9Apply(){
 const target=p9.views.get(rt.ref);
 if(target&&p9.shown!==target){
  if(p9.shown)Object.assign(p9.shown.state,n2);else p9.original={...n2};
  Object.assign(n2,target.state);p9.shown=target;
 }else if(!target&&p9.shown){
  Object.assign(p9.shown.state,n2);Object.assign(n2,p9.original);p9.shown=null;
 }
}
async function p9Open(id){
 const ref=rt.ref,epoch=++p9.epoch;
 const material=m9.catalog?.materials.find(m=>m.id===id&&m.project_ref===ref&&m.stage===2);
 if(!material)throw Error('packet-project-binding-differs');
 const view=await canonicalOldRequest('/api/v9/packets/'+encodeURIComponent(id));
 if(view.kind!=='V9ValidatedPacketView'||view.project_ref!==ref||view.material_id!==id||
    view.packet_file_sha256!==(material.packet_file_sha256||material.sha256)||
    await canonicalHash(view.packet_text)!==view.packet_file_sha256||view.execution_authorized!==false)
  throw Error('packet-display-binding-differs');
 for(const card of view.cards){if(await canonicalHash(card.saved_text)!==card.artifact.sha256)throw Error('source-display-binding-differs');}
 const state=p9State(view);
 if(ref!==rt.ref||epoch!==p9.epoch)throw Error('project-changed-during-display-read');
 p9.views.set(ref,{id,view,state});p9Apply();
 // This preference only causes a verified GET after reload, never a POST.
 try{sessionStorage.setItem('v9-imported-view:'+ref,id);}catch{}
 m9.status=rl('已核验导入材料，下面显示该版本；尚未生成新研究。',
  'Verified imported version displayed below; no new research generated.','已核驗匯入材料，下方顯示該版本；尚未產生新研究。');
}
const p9Card=m9Card;
m9Card=function(m){let html=p9Card(m);if(m.stage===2&&m.packet_path)
 html=html.replace('<div class="hs-action-row">',`<div class="hs-action-row"><button class="hs-button" data-n9-open-packet="${rx(m.id)}" ${m9.busy?'disabled':''}>${rl('读取并显示这份材料','Read & display this input','讀取並顯示此材料')}</button>`);return html;};
const p9Stage2=stage2;
stage2=function(app){p9Apply();return p9Stage2(app);};
const p9Files=n2Files,p9Feedback=n2Feedback,p9Metrics=n2ReviewMetrics,p9Render=n2Render;
n2Files=function(){return p9.shown?`<details class="hs-panel"><summary>${rl('当前导入原文与身份','Imported originals & identity','目前匯入原文與身分')}</summary>${n2Record('Stage2Packet',n2.model.packet)}${n2Record('SHA-256',p9.shown.view.packet_file_sha256)}<p>${rl('逐篇原卡在“文献比较”展开；原件和缺失字段保持不变。','Open each source card under literature comparison. Originals and missing fields are retained.','逐篇原卡於「文獻比較」展開；原件及缺失欄位保持不變。')}</p></details>`:p9Files();};
n2ReviewMetrics=function(){return p9.shown?`<p>${rl('本次导入没有附带经绑定核验的独立评审结果，评分保持未提供。','This import has no bound independent review receipt; scores remain unavailable.','本次匯入沒有附帶經綁定核驗的獨立評審結果，評分保持未提供。')}</p>`:p9Metrics();};
n2Feedback=function(){if(!p9.shown)return p9Feedback().replace('本地展示仅GET读取；没有调用研究模型，没有提交选案、审批或下一阶段。','交付读取采用GET；手动材料与草稿可保存。没有调用研究模型或提交正式选案。').replace('Local display uses GET reads only; no research model, selection, approval or next stage was submitted.','Delivery reads use GET; manual inputs and drafts can be saved. No research model or formal selection was submitted.');
 const view=p9.shown.view;
 return `<details class="hs-panel" data-n2-feedback><summary>Stage2 · ${rl('接续状态与缺口','Continuation & missing interfaces','接續狀態與缺口')}</summary><p>${rl('已导入并重新校验原材料。下方结果是输入投影，尚无新研究产物。','Imported original inputs revalidated. The displayed result is an input projection, not a newly generated research artifact.','已匯入並重新校驗原材料。下方結果為輸入投影，尚無新研究產物。')}</p><p>SHA-256: ${rx(view.packet_file_sha256)}</p><p>${rl('正式选案尚不可提交：需要同一workflow的可信交付登记、当前事件head、独立评审回执与原生用户消息。','Formal selection is unavailable: requires trusted delivery registration, current workflow head, independent review receipts and native user-message provenance.','正式選案尚不可提交：需要同一workflow的可信交付登記、目前事件head、獨立評審回執及原生使用者訊息。')}</p>${n2Record(rl('完整缺口与血缘','Missing inputs & lineage','完整缺口與血緣'),{formal_selection:view.formal_selection,upstream:view.stage1_lineage})}<button class="hs-button" data-n9-open-packet="${rx(p9.shown.id)}">${rl('重新核验并更新结果','Revalidate & refresh results','重新核驗並更新結果')}</button><button class="hs-button" data-n9-original>${rl('返回原保存交付','Return to original delivery','返回原保存交付')}</button></details>`;
};
n2Render=function(app){let html=p9Render(app);if(p9.shown){html=html.replace(rl('独立自然提问交付；未绑定为当前Stage1的下游。','Independent natural-request delivery; not bound as a downstream result of current Stage1.','獨立自然提問交付；未綁定為目前Stage1的下游。'),rl('当前手动导入材料；来源血缘按原packet保留，尚未取得接续执行许可。','Current manual input; lineage is retained from its packet and continuation admission is still required.','目前手動匯入材料；來源血緣依原packet保留，尚未取得接續執行許可。'));}return html;};
function p9Loop(){
 const p=rt.overview?.project,s=rt.overview?.stage1;
 const bound=p?.project_ref===rt.ref&&!canonicalReadonly();
 const active=bound&&s?.progress?.binding?.input_version===p.input_version&&s.progress.binding.brief_sha256===p.brief_sha256&&s.progress.binding.revision===p.revision;
 return `<details class="hs-panel" data-n9-loop-review><summary>Stage1 · ${rl('Loop与人工审查','Loop & human review','Loop與人工審查')}</summary><p>${active?rl('可在当前已保存记录上审查筛选、阅读和覆盖；正在执行或结果未知的步骤不能重复提交。','Review saved screening, reading and coverage records. Running or unknown operations must not be resubmitted.','可於目前已保存紀錄審查篩選、閱讀及覆蓋；正在執行或結果未知的步驟不可重複提交。'):rl('这是保存交付或尚未绑定的项目。可查看历史；运行中的Loop审查需要当前项目及版本回执。','This is a saved delivery or an unbound project. Live loop review requires current project/version receipts.','此為保存交付或尚未綁定的專案。可查看歷史；執行中的Loop審查需要目前專案及版本回執。')}</p>${active?`<div class="hs-action-row"><button class="hs-button" data-live-phase="screening">${rl('查看筛选决定','Screening decisions','查看篩選決定')}</button><button class="hs-button" data-live-phase="reading">${rl('查看阅读与证据','Reading & evidence','查看閱讀與證據')}</button>${realButton('checkpoint','检查覆盖与下一步','Checkpoint & next step',!!s.ledger)}</div><pre class="live-record">${rx(JSON.stringify({current:s.progress.next_action,phases:s.progress.phases,checkpoint:s.checkpoint},null,2))}</pre>`:''}<p>${rl('继续下一轮由Harness的当前检查结果、有效操作和预算决定；本页不自动重复Loop，也不把保存意见当作审批。','The next loop follows Harness checkpoint results, available actions and budget. Saving a note is not an approval.','下一輪由Harness目前檢查結果、有效操作及預算決定；保存意見不等於審批。')}</p></details>`;
}
const p9Stage1=stage1;
stage1=app=>p9Stage1(app)+p9Loop();
const p9After=v7AfterRender;
v7AfterRender=function(app){p9After(app);if(p9.shown&&app.stage===2){const name=app.el.querySelector('.hs-project-name span');if(name)name.textContent=rl('Stage2 · 当前导入材料','Stage2 · Imported input','Stage2 · 目前匯入材料');}
 if(app.stage===2&&m9.catalog&&!p9.attempted.has(rt.ref)){const ref=rt.ref;p9.attempted.add(ref);let id;try{id=sessionStorage.getItem('v9-imported-view:'+ref);}catch{}if(id){p9Open(id).catch(e=>{m9.error=e.message;}).finally(()=>livePaint());}}
};
document.addEventListener('click',async event=>{const b=event.target.closest('[data-n9-open-packet]');if(!b||m9.busy)return;m9.busy=true;m9.error='';try{await p9Open(b.dataset.n9OpenPacket);}catch(error){m9.error=error.message;}finally{m9.busy=false;livePaint();}});
document.addEventListener('click',event=>{if(!event.target.closest('[data-n9-original]')||m9.busy)return;p9.epoch++;p9.views.delete(rt.ref);try{sessionStorage.removeItem('v9-imported-view:'+rt.ref);}catch{}p9Apply();livePaint();});
