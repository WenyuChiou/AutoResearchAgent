// Local live-service additions; use only the repository's bound action offers.
// Renderer mode is not proof of account authentication or execution authority.
// Capabilities, limits and available action offers still come from the current project.
const liveReal = () => rt.meta?.kind === 'V7RuntimeConfiguration' || rt.meta?.evidence === 'own-account-live';
const savedRuntimeRender=render;
render=function(app){savedRuntimeRender(app);if(liveReal()){liveRestorePanels(app);realRuntimeChrome(app);}};
function realChromeStatus(){
 const p=rt.overview?.project,current=!!p&&p.project_ref===rt.ref,s=current?rt.overview.stage1:null,a=rt.atlas;
 const candidates=current?(s?.ledger?.counts?.works??(s?.ledger===null?0:'Unknown')):'Unknown';
 const delivered=current&&a?.project_ref===rt.ref&&a.input_version===p.input_version?(a.payload?.index?.papers?.length??'Unknown'):current&&!s?.delivery?.canonical_package?0:rl('待载入','Awaiting load');
 const outputs=current?new Set((rt.modelHistory?.actions||[]).map(j=>j.result||j).filter(j=>j.project_ref===rt.ref&&j.input_version===p.input_version&&j.brief_sha256===p.brief_sha256&&j.output_ref&&j.output_sha256).map(j=>j.output_ref)).size:'Unknown';
 return {project:current?rl('当前项目','Current project')+' · v'+p.input_version:rl('未选择项目','No project selected'),model:'Codex · '+realServiceLabels().model,counts:rl('候选','Candidates')+' '+candidates+' · '+rl('交付论文','Delivered papers')+' '+delivered+' · '+rl('保存输出','Saved outputs')+' '+outputs,footer:rl('当前项目的保存记录；运行状态与研究验收分别判断。','Saved records for the current project; execution status and research acceptance are assessed separately.')};
}
function realRuntimeChrome(app){
 const value=realChromeStatus(),sidebar=app.el.querySelector('.hs-sidebar-foot'),footer=app.el.querySelectorAll('.hs-footer span');
 if(sidebar)sidebar.innerHTML=`<strong>${rx(value.project)}</strong>${rx(value.model)}<br>${rx(value.counts)}`;
 if(footer[0])footer[0].textContent=value.footer;if(footer[1])footer[1].textContent=value.model;
}
const savedControls = liveControls;
const savedAssistant = liveAssistant;
const savedHeader = liveHeader;
const savedPost = livePost;
const savedResults = liveResults;
const savedModelOutputs = liveModelOutputs;
const savedOtherPage = otherPage;
const savedRefresh=liveRefresh;
liveRefresh=async function(...args){
 await savedRefresh(...args);
 if(!liveReal())return;
 const ref=rt.ref,epoch=rt.epoch,p=rt.overview?.project,s=rt.overview?.stage1;
 if(rt.workflowBasis!==realBasis()){rt.paperDetail=null;rt.sourceOffer=null;rt.readingView=null;rt.coverageIndex=null;rt.workflowBasis=realBasis();}
 if(!rt.realPhasePinned&&s?.progress?.next_action?.phase_id){rt.phase=s.progress.next_action.phase_id;livePaint();}
 rt.library=null;
 if(!p||!s?.ledger)return;
 try{
  const value=await liveRequest(projectPath(ref,`stage1/screening/${p.input_version}/${s.ledger.state_sha256}/0`));
  if(ref!==rt.ref||epoch!==rt.epoch)return;
  if(value.project_ref!==ref||value.input_version!==p.input_version)throw new Error('screening-project-binding-differs');
  rt.library=value;livePaint();
 }catch(error){if(epoch===rt.epoch){rt.error=error.message;livePaint();}}
};
function realLibrary(){
 const library=rt.library;
 if(!library?.rows?.length)return '';
 return `<section class="hs-panel live-files"><h3>${rl('已保存的检索候选','Saved search candidates')} · ${library.total}</h3><p>${rl('当前查询输出；尚未成为正式交付。来源、阅读与纳入决定仍需分别审阅。','Current query output; not a formal delivery. Source, reading and inclusion remain separate reviews.')}</p><div class="live-table-scroll"><table class="live-table"><thead><tr><th>${rl('论文','Paper')}</th><th>${rl('年份','Year')}</th><th>${rl('来源状态','Source')}</th><th>${rl('筛选状态','Screening')}</th></tr></thead><tbody>${library.rows.map(row=>`<tr><td><button class="hs-button" data-real-paper="${row.index}">${rx(row.title)}</button></td><td>${rx(row.year)}</td><td>${rx(row.source_status)}</td><td>${rx(row.screening_status)}</td></tr>`).join('')}</tbody></table></div>${library.next_offset!==null?realButton('library-next','读取更多候选','Load more candidates'):""}${rt.paperDetail?.project_ref===rt.ref?`<details open><summary>${rl('当前候选记录','Candidate record')}</summary><pre class="live-record">${rx(JSON.stringify(rt.paperDetail.row,null,2))}</pre></details>`:''}</section>`;
}
otherPage = function(app){
 if(!liveReal()||app.page!=='settings')return savedOtherPage(app);
 const m=rt.overview?.models,q=rt.overview?.stage1?.query_execution;
 return `${liveHeader(app)}<section class="hs-panel live-files"><h2>${rl('连接与额度','Connection & limits')}</h2><p>Harness ${rx(rt.meta.harness_head)} · Codex ${rx(rt.meta.model)}</p><p>${rl('模型任务状态','Model status')}: ${rx(m?.status)} · ${rl('已预留调用','Reserved calls')}: ${rx(m?.calls_reserved)}</p><p>${rl('查询状态','Query status')}: ${rx(q?.status)}</p><p>${rl('金额','Monetary cost')}: ${rx(rt.overview?.project?.monetary_cost)}</p><pre class="live-record">${rx(JSON.stringify(rt.overview?.project?.settings?.budgets||null,null,2))}</pre><p>${rl('Stage2 自动执行、持续 Codex 聊天尚未验收；登录或任务已启动不代表研究完成。','Automatic Stage2 and persistent Codex chat are not accepted yet; login or dispatch is not research completion.')}</p></section>`;
};
livePost = async function(tail,body,ref=rt.ref){
  if(liveReal() && tail==='confirm') {
    const limits=rt.meta.run_limits,positive=value=>Number.isSafeInteger(value)&&value>0;
    body={...body,
      resource_envelope:'Bounded V7 integration validation: '+JSON.stringify(limits)+'. No scoring or later-stage execution.',
      budgets:limits,consent:{external_search:positive(limits?.seconds)&&positive(limits?.search_calls),public_source_read:positive(limits?.seconds)&&positive(limits?.source_reads),browser_fallback:false}};
  }
  return savedPost(tail,body,ref);
};
liveHeader = app => {
 let html=savedHeader(app).replace(rl('仓库离线 case · 非研究结论','Repository offline case · not research findings'),liveReal()?rl('真实调用验收 · 覆盖未完成','Live integration run · coverage incomplete'):rl('仓库离线 case · 非研究结论','Repository offline case · not research findings'));
 const pending=liveReal()&&(realQueryPending()||realQueryNextBackend());
 if(pending&&rt.error==='query-unreconciled-action')html=html.replace(/<div class="live-error" role="alert">[\s\S]*?<\/div>/,`<div class="live-callout" role="status">${rx(pending.message)}<p>${pending.queryJob?rl('后台正在保存查询记录，重复提交仍被阻止；这不代表查询或阶段已完成。','The backend is saving the query record; duplicate submission remains blocked. Neither the query nor the stage is complete.'):rl('下一来源仍须使用当前服务提供的操作；不会自动提交。','The next source still requires the current server-offered action; it is never submitted automatically.')}</p><details><summary>${rl('查看原始拒绝记录','Inspect original refusal')}</summary><pre class="live-record">${rx(rt.error)}</pre></details><button data-live-action="refresh" class="hs-button">${rl('刷新进度','Refresh progress')}</button></div>`);
 return html;
};
function realQueryPending(overview=rt.overview){
 const p=overview?.project,q=overview?.stage1?.query_execution,progress=overview?.stage1?.progress,b=progress?.binding,h=q?.query_history,row=h?.history?.at(-1);
 if(!p||p.project_ref!==rt.ref||!b||b.project_ref!==rt.ref||b.input_version!==p.input_version||b.revision!==p.revision||b.brief_sha256!==p.brief_sha256||progress.next_action?.phase_id!=='query'||progress.next_action?.reason!=='active-action'||p.status==='execution-unknown'||!['completed','running','dispatching'].includes(q?.status))return null;
 if(q.refusal&&q.refusal!=='query-unreconciled-action'||h?.project_ref!==rt.ref||h.input_version!==p.brief_sha256||row?.method!=='stage1/planned-query'||row.status!=='dispatching'||row.failure||row.offer?.project_ref!==rt.ref||row.offer.brief_sha256!==p.brief_sha256||row.offer.input_version!==p.brief_sha256)return null;
 const receipt=(rt.history?.actions||[]).findLast(r=>r.kind==='stage1-query-execute'&&r.project_ref===rt.ref&&r.query_action_key===row.client_key&&r.query_request_sha256===row.request_sha256);
 if(receipt?.status!=='saved'||receipt.query_status!=='dispatch-unobserved')return null;
 return {queryJob:row,queryReceipt:receipt,message:rl('查询执行中，等待保存回执','Query is executing; awaiting its saved receipt')};
}
function realQueryNextBackend(overview=rt.overview){
 const p=overview?.project,s=overview?.stage1,q=s?.query_execution,b=s?.progress?.binding,h=q?.query_history,offer=q?.query_offer,d=offer?.document,pending=s?.ledger?.pending_actions;
 if(!p||p.project_ref!==rt.ref||p.status==='execution-unknown'||!b||b.project_ref!==rt.ref||b.input_version!==p.input_version||b.revision!==p.revision||b.brief_sha256!==p.brief_sha256||s.progress.next_action?.phase_id!=='query'||s.progress.next_action?.reason!=='uncertain-action'||q?.status!=='completed'||q.refusal)return null;
 if(!offer?.offer_ref||!offer.offer_sha256||typeof d?.backend!=='string'||!d.backend||d.project_ref!==rt.ref||d.brief_sha256!==p.brief_sha256||d.input_version!==p.brief_sha256||!Array.isArray(pending)||pending.length!==1||pending[0]!==d.query_id)return null;
 if(h?.project_ref!==rt.ref||h.input_version!==p.brief_sha256||h.revision!==offer.revision||!h.history?.length||!h.history.every(r=>r.status==='completed'&&r.offer?.project_ref===rt.ref&&r.offer.brief_sha256===p.brief_sha256)||!h.history.some(r=>r.result?.query_id===d.query_id&&r.result.backend_result_id&&r.result.query_result_id===null))return null;
 return {queryNextOffer:offer,message:rl('已保存上一后端结果，等待同一查询的 '+d.backend+' 检索；各后端结束后生成候选','Previous backend result saved; awaiting '+d.backend+' for the same query. Candidates are produced after all backends finish.')};
}
function realBudget(){return rt.overview?.project?.settings?.budgets||rt.meta?.run_limits||null;}
function realQueryOwnerOffer(){
 const p=rt.overview?.project,s=rt.overview?.stage1,b=s?.progress?.binding,q=s?.query_execution,o=q?.owner_offer;
 if(!realActionEnvelope(s)||s.input_version!==p.input_version||b?.project_ref!==rt.ref||b.revision!==p.revision||b.input_version!==p.input_version||b.brief_sha256!==p.brief_sha256||q?.status!=='owner-reopen-required')return null;
 return typeof o?.offer_sha256==='string'&&/^[a-f0-9]{64}$/.test(o.offer_sha256)&&o.offer_ref==='project-query-owner-'+o.offer_sha256.slice(0,32)?o:null;
}
function realPlanImportReady(){
 const p=rt.overview?.project,s=rt.overview?.stage1,m=rt.overview?.models,q=s?.query_execution;
 return !!(!rt.busy&&!rt.loading&&!rt.pending&&p&&p.project_ref===rt.ref&&p.status!=='execution-unknown'&&p.intake_report?.necessary_clarification_complete===true&&p.plan===null&&s?.ledger===null&&['not-started','intake-not-ready'].includes(s.stage1_status)&&Array.isArray(m?.active_jobs)&&m.active_jobs.length===0&&(m.blocking_unknown_count??m.unknown_count??0)===0&&(!q||Array.isArray(q.jobs)&&q.jobs.length===0&&['permission-required','unavailable-or-stale','intake-prerequisite-required'].includes(q.status)&&q.execution_authorized!==true&&(!q.refusal||q.refusal==='intake-plan-not-ready')));
}
function realPlanDraftCurrent(){const p=rt.overview?.project,d=rt.planDraft;return !!(p&&d&&d.ref===rt.ref&&d.input_version===p.input_version&&d.revision===p.revision&&d.brief_sha256===p.brief_sha256);}
function realServiceLabels(){
 const m=rt.overview?.models,s=rt.overview?.stage1,q=s?.query_execution,source=s?.source_execution;
 const label=(actual,configured)=>typeof actual==='boolean'?(actual?rl('已注册，执行需许可','Registered; permission required'):rl('未接通','Unconnected')):configured===false?rl('未注册','Not registered'):configured===true?rl('启动时配置，当前状态未确认','Configured at startup; current state unconfirmed'):'Unknown';
 return {model:label(m?.authorization_available,rt.meta?.content_model_registered),query:label(s&&Object.hasOwn(s,'query_execution')?!!q:undefined,rt.meta?.query_runtime_registered),source:label(source?.runner_connected,s&&Object.hasOwn(s,'source_execution')&&source===null?false:rt.meta?.source_worker_requested)};
}
function realPlanningState(){
 const p=rt.overview?.project,m=rt.overview?.models;
 const current=!!(p&&m&&p.project_ref===rt.ref&&m.project_ref===rt.ref&&Number.isSafeInteger(p.revision)&&p.revision>=0&&m.revision===p.revision&&Number.isSafeInteger(p.input_version)&&p.input_version>=1&&m.input_version===p.input_version&&typeof p.brief_sha256==='string'&&/^[a-f0-9]{64}$/.test(p.brief_sha256)&&m.brief_sha256===p.brief_sha256);
 if(!current)return {current:false,allowed:false,blocking:null,failures:[]};
 const count=Object.hasOwn(m,'blocking_unknown_count')?m.blocking_unknown_count:m.unknown_count;
 const blocking=Number.isSafeInteger(count)&&count>=0?count:null;
 const failures=(Array.isArray(m.jobs)?m.jobs:[]).filter(j=>j?.project_ref===rt.ref&&j.input_version===p.input_version&&j.brief_sha256===p.brief_sha256&&typeof j.failure==='string'&&j.failure).map(j=>({operation:j.operation,status:j.status,failure:j.failure}));
 return {current:true,allowed:blocking===0,blocking,failures};
}
function realPlanningBlockMessage(state=realPlanningState()){
 return state.blocking>0?rl('模型任务仍有未确认结果。检查原任务，不重发；原记录与已预留额度保留。','A model task still has an unconfirmed outcome. Inspect the original task; do not resend. Original records and reserved usage are retained.','模型任務仍有未確認結果。檢查原任務，不重發；原紀錄與已預留額度保留。'):rl('当前项目的模型阻挡状态尚未确认。请刷新并检查原任务，不重发。','The current project model blocking state is unconfirmed. Refresh and inspect the original task; do not resend.','目前專案的模型阻擋狀態尚未確認。請重新整理並檢查原任務，不重發。');
}
function realPlanningFailure(){
 const state=realPlanningState();if(state.allowed)return '';
 return `<div class="live-error" data-v7-planning-block role="status"><p>${rx(realPlanningBlockMessage(state))}</p><p>${rl('未确认阻挡任务数','Blocking unknown tasks','未確認阻擋任務數')}: ${rx(state.blocking)}</p>${state.failures.length?`<details open><summary>${rl('后台原始错误','Original backend failure','後端原始錯誤')}</summary><pre class="live-record">${rx(JSON.stringify(state.failures,null,2))}</pre></details>`:''}</div>`;
}
function realControls(){
  const jobs=rt.overview?.models?.jobs||[];
  const offers=realModelOffers();
  const offer=offers.find(o=>o.available && o.operation==='plan-search');
  const q=rt.overview?.stage1?.query_execution;
  const budget=realBudget(),savedBudget=!!rt.overview?.project?.settings?.budgets;
  const remaining=Math.max(0,(rt.overview?.project?.settings?.budgets?.model_calls||0)-(rt.overview?.models?.calls_reserved||0));
  const planning=realPlanningState();
  return `<section class="live-callout"><strong>${rl('真实 Harness 操作','Live Harness operations')}</strong>
    <p>Codex ${rx(rt.meta.model)} · Harness ${rx(rt.meta.harness_head?.slice(0,8))}</p>
    <p>${savedBudget?rl('当前项目已保存额度','Current project saved limits'):rl('新项目启动额度 · 尚未保存','New-project startup limits · not yet saved')}: ${rx(budget?.model_calls)} ${rl('次模型','model calls')} · ${rx(budget?.search_calls)} ${rl('次查询','queries')} · ${rx(budget?.source_reads)} ${rl('份公开来源','public sources')}。${rl('每一步单独执行；不会自动进入 Stage2。','Explicit steps; no automatic Stage2.')}</p>
    ${realPlanningFailure()}
    <button class="hs-button" data-real-action="authorize-plan" ${remaining&&planning.allowed?liveDisabled():'disabled'}>${rl('授权一次查询规划','Authorize one planning call')}</button>
    <button class="hs-button hs-button-primary" data-real-action="plan" ${offer&&planning.allowed?liveDisabled():'disabled'}>${rl('运行 Codex 查询规划','Run Codex planning')}</button>
    ${[['query-authorize','authorization_offer','授权已保存查询'],['query-bootstrap','bootstrap_offer','准备查询运行'],['query-execute','query_offer','执行当前查询']].map(([action,key,label])=>`<button class="hs-button" data-real-action="${action}" ${q?.[key]?liveDisabled():'disabled'}>${rx(label)}</button>`).join('')}
    ${realQueryOwnerOffer()?`<button class="hs-button" data-real-action="query-restore-owner" ${liveDisabled()}>${rl('恢复已保存运行','Resume saved run')}</button><p><small>${rl('只恢复已保存运行的控制权与历史，不执行查询、不调用模型；下一步仍需单独操作。','Restore control and history for the saved run only. This performs no query or model call; subsequent actions remain explicit.')}</small></p>`:''}
    <p>${rl('当前任务','Current jobs')}: ${jobs.map(j=>rx(j.operation+' · '+j.status)).join(' / ')||rl('尚未调用','No calls yet')}</p>
    ${rt.modelHistory?.actions?.some(a=>(a.result||a).operation==='plan-search'&&(a.result||a).output_ref)?`<button class="hs-button" data-real-action="review-plan">${rl('审阅已保存规划','Review saved plan')}</button>`:''}
    ${rt.overview?.project?.intake_report?.necessary_clarification_complete===true&&rt.overview.project.plan===null?`<button class="hs-button" data-real-action="import-plan" ${realPlanImportReady()?'':'disabled'}>${rl('导入已有规划（不调用模型）','Import an existing plan (no model call)')}</button>`:''}
    ${realPlanDraftCurrent()?`<details open><summary>${rt.planDraft.mode==='reviewed-import'?rl('审阅导入规划 · 不调用模型','Review imported plan · no model call'):rl('规划修订 · 不覆盖模型原文','Plan revision · original output retained')}</summary><p>${rt.planDraft.mode==='reviewed-import'?rl('粘贴并审阅已有规划 JSON。这是审阅导入，不是当前项目的新模型输出；原项目模型原文与 hash 保持保存。','Paste and review existing plan JSON. This is a reviewed import, not a new model output for this project; the original project output and hash remain saved.'):''}${rl('修订会单独保存并由原有 Harness 编译器校验。此操作不执行检索。','Revision is separately saved and validated by the existing Harness compiler. This does not run searches.')}</p><label>${rl('规划 JSON','Plan JSON')}<textarea data-real-plan rows="10" ${liveDisabled()}>${rx(rt.planDraft.text)}</textarea></label><button class="hs-button" data-real-action="compile-plan" ${rt.planDraft.mode==='reviewed-import'&&!realPlanImportReady()?'disabled':liveDisabled()}>${rl('保存并校验修订','Save and validate revision')}</button></details>`:''}
    ${realSavedActions()}
  </section>`;
}
liveControls = function(app){let html=savedControls(app);if(!liveReal())return html;
  const services=realServiceLabels();
  html=html.replace(/<div class="live-capabilities">[\s\S]*?<\/div>/,`<div class="live-capabilities">Codex: ${rx(services.model)} · ${rl('查询','Queries')}: ${rx(services.query)} · ${rl('来源','Sources')}: ${rx(services.source)}。${rl('实际结果以保存记录为准；Stage2 自动执行未接通。','Saved records determine outcomes; automatic Stage2 is unconnected.')}</div>`);
  return app.stage===1?html.replace('<div class="lp-ops-body">','<div class="lp-ops-body">'+realControls()):html;
};
liveAssistant = function(app){let html=savedAssistant(app);if(!liveReal())return html;
  html=html.replaceAll(rl('真实模型未连接','Live model unconnected'),app.stage===1?'Codex · '+realServiceLabels().model:rl('Stage2 Codex 会话未接通','Stage2 Codex session unconnected','Stage2 Codex 會話未接通'));
  if(app.stage===1&&rt.tab==='chat')html=html.replace('<div class="v7-assistant-body">','<div class="v7-assistant-body"><p class="live-callout">'+rl('这里查看保存输出、答复当前任务的问题，并在服务提供许可时发起针对已保存输出的补充问答。讨论不会修改文献包、人工审阅决定或阶段状态。','Inspect saved outputs, answer current task questions, and ask about saved outputs when the service offers permission. Discussion does not change literature packages, human review decisions or stage status.')+'</p>'+realNativeControl(app)+(typeof realRetirementPanel==='function'?realRetirementPanel(app):'')+realFollowup(app));
  return html;
};
liveModelOutputs = function(){if(!liveReal())return savedModelOutputs();
  const actions=rt.modelHistory?.actions||[];
  return `<details class="live-model-history" open><summary>${rl('Codex 实际任务与保存输出','Actual Codex tasks & saved outputs')} · ${actions.length}</summary>${actions.map((a,i)=>{const r=a.result||a;return `<article class="live-detail-block"><strong>${rx(r.operation||a.operation)} · ${rx(r.status||a.status)}</strong>${r.followup?`<p>${rl('补充问题','Follow-up question')}: ${rx(r.followup.question)}</p><small>${rl('针对输出','Target output')}: ${rx(r.followup.target_output_ref)}</small>`:""}<pre class="live-record">${rx(r.output_preview||r.failure||a.failure||'尚无模型输出')}</pre>${r.output_ref&&r.output_sha256?`<button class="hs-button" data-real-output="${i}">${rl('查看完整保存输出','Read complete saved output')}</button>`:''}${r.operation==='read-paper'&&r.output_ref?realButton('reading-draft','审阅已保存阅读输出','Review saved reading output',true,i):''}</article>`;}).join('')}${rt.modelOutput && rt.modelOutput.ref===rt.ref?`<p><small>SHA256 · ${rx(rt.modelOutput.sha)}</small></p><pre class="live-record">${rx(rt.modelOutput.text)}</pre>`:''}</details>`;
};
liveResults = function(app){const html=savedResults(app);if(!liveReal()||app.stage!==1)return html;
  const report=rt.meta.acceptance_report&&rt.meta.acceptance_report.project_ref===rt.ref?`<details class="hs-panel live-files"><summary>${rl('历史验收记录 · 当前状态见运行反馈','Historical acceptance record · current status is in progress')}</summary><pre class="live-record">${rx(JSON.stringify(rt.meta.acceptance_report,null,2))}</pre></details>`:'';
  return html.replace('<div class="lp-result-body">','<div class="lp-result-body">'+report+'<section class="hs-panel live-files">'+liveModelOutputs()+'</section>'+realLibrary()+realPaperActions()+realReadingReview());
};
const savedReason=liveReason;
liveReason = reason => {
 const messages={'reading-registration-required':['请完成当前文献的阅读审阅登记','Review and register the current saved reading notes'],'plan-required':['等待运行查询规划','Awaiting query planning'],'uncertain-action':['操作结果需检查；原始失败已保留','Inspect the operation outcome; original failure retained'],'unknown-state':['阶段状态未确认，已有记录可在下方查看','Stage state unconfirmed; inspect the saved records below']};
 return liveReal()&&messages[reason]?rl(...messages[reason]):savedReason(reason);
};
document.addEventListener('click',async e=>{
  const paperButton=e.target.closest('[data-real-paper]');
  if(paperButton&&liveReal()){
   e.preventDefault();const ref=rt.ref,epoch=rt.epoch,p=rt.overview.project,s=rt.overview.stage1,l=rt.library;rt.readingView=null;rt.sourceOffer=null;rt.paperDetail=null;livePaint();
   try{const value=await liveRequest(projectPath(ref,`stage1/screening-detail/${p.input_version}/${s.ledger.state_sha256}/${l.projection_sha256}/${paperButton.dataset.realPaper}`));if(ref!==rt.ref||epoch!==rt.epoch)return;if(value.project_ref!==ref)throw new Error('candidate-project-binding-differs');rt.paperDetail=value;livePaint();}catch(error){rt.error=error.message;livePaint();}return;
  }
  const outputButton=e.target.closest('[data-real-output]');
  if(outputButton){e.preventDefault();const ref=rt.ref,epoch=rt.epoch,r0=rt.modelHistory.actions[Number(outputButton.dataset.realOutput)],r=r0.result||r0;let text='',offset=0;try{for(let n=0;n<32;n++){const part=await liveRequest(projectPath(ref,`models/outputs/${r.output_ref}/${offset}`));if(ref!==rt.ref||epoch!==rt.epoch)return;if(part.project_ref!==ref||part.output_ref!==r.output_ref||part.output_sha256!==r.output_sha256||part.offset!==offset)throw new Error('model-output-binding-mismatch');text+=part.text;if(part.next_offset===null)break;offset=part.next_offset;}rt.modelOutput={ref,sha:r.output_sha256,text};livePaint();}catch(err){rt.error=err.message;livePaint();}return;}
  const b=e.target.closest('[data-real-action]');if(!b||!liveReal())return;
  e.preventDefault();e.stopImmediatePropagation();const action=b.dataset.realAction;
  if(action==='import-plan'){
   if(!realPlanImportReady())return;
   const p=rt.overview.project;rt.planDraft={ref:rt.ref,revision:p.revision,input_version:p.input_version,brief_sha256:p.brief_sha256,mode:'reviewed-import',text:''};livePaint();return;
  }
  if(action==='review-plan'){
   const row=rt.modelHistory.actions.findLast(a=>(a.result||a).operation==='plan-search'&&(a.result||a).output_ref),r=row.result||row,ref=rt.ref,epoch=rt.epoch;let offset=0,text='';
   try{for(let n=0;n<32;n++){const part=await liveRequest(projectPath(ref,`models/outputs/${r.output_ref}/${offset}`));if(epoch!==rt.epoch||ref!==rt.ref)return;if(part.project_ref!==ref||part.output_sha256!==r.output_sha256||part.offset!==offset)throw new Error('plan-output-binding-differs');text+=part.text;if(part.next_offset===null)break;offset=part.next_offset;}rt.planDraft={ref,revision:rt.overview.project.revision,input_version:rt.overview.project.input_version,brief_sha256:rt.overview.project.brief_sha256,mode:'saved-model-output',output_sha256:r.output_sha256,text};livePaint();}catch(error){rt.error=error.message;livePaint();}return;
  }
  if(action==='compile-plan'){
   if(!realPlanDraftCurrent()||rt.busy||rt.loading||rt.pending||rt.planDraft.mode==='reviewed-import'&&!realPlanImportReady())return;
   try{const text=document.querySelector('[data-real-plan]').value,request=JSON.parse(text);rt.planDraft.text=text;await livePost('compile',{...liveBound(),request,as_of:new Date().toISOString().slice(0,10)});}catch(error){rt.error=error.message;livePaint();}return;
  }
  if(['authorize-plan','plan'].includes(action)&&!realPlanningState().allowed){rt.error=realPlanningBlockMessage();livePaint();return;}
  if(action==='authorize-plan')return livePost('models/authorize',{...liveBound(),operation:'plan-search',user_input:'用户要求在本地 V7 用本人 Codex 和仓库 Harness 实际验证链路。本轮上限 '+JSON.stringify(realBudget())+'；不做评分、不运行Stage2。',confirmed:true});
  if(action==='plan'){const o=realModelOffers().find(o=>o.available&&o.operation==='plan-search');if(o)return livePost('models/actions',{...liveBound(),offer_ref:o.offer_ref,offer_sha256:o.offer_sha256,confirmed:true});}
  if(action.startsWith('query-')){const q=rt.overview.stage1.query_execution;const o=action==='query-restore-owner'?realQueryOwnerOffer():q?.[{'query-authorize':'authorization_offer','query-bootstrap':'bootstrap_offer','query-execute':'query_offer'}[action]];if(!o)return;const body={...liveBound(),offer_ref:o.offer_ref,offer_sha256:o.offer_sha256,confirmed:true};if(action==='query-authorize')body.user_input='本地 V7 限定链路验收，本轮上限 '+JSON.stringify(realBudget())+'；不评分，不进入Stage2。';return livePost('stage1/'+action,body);}
},true);

// Every write below is offered by the current production service. Reads never dispatch work.
function realActionEnvelope(view){const p=rt.overview?.project;return !!(p&&p.project_ref===rt.ref&&view?.project_ref===rt.ref&&view.revision===p.revision);}
function realModelOffers(){const value=rt.overview?.model_offers;return realActionEnvelope(value)&&Array.isArray(value.offers)?value.offers:[];}
function realReadingOffer(detail=rt.paperDetail){
 const p=rt.overview?.project,b=detail?.binding,o=detail?.reading_offer;
 if(!realCurrent(detail)||b?.project_ref!==rt.ref||b.input_version!==p.input_version||b.brief_sha256!==p.brief_sha256||b.ledger_state_sha256!==rt.overview?.stage1?.ledger?.state_sha256)return null;
 return o?.kind==='Stage1SavedReadingOfferPreview'&&o.operation==='read-paper'&&o.project_ref===rt.ref&&o.work_ref===detail.row?.work_id&&o.available===true&&typeof o.snapshot_sha256==='string'&&/^[a-f0-9]{64}$/.test(o.snapshot_sha256)?o:null;
}
function realReadingExecutable(o){const p=rt.overview?.project;return !!(p&&o?.available===true&&o.operation==='read-paper'&&o.input_version===p.input_version&&o.brief_sha256===p.brief_sha256&&typeof o.work_ref==='string'&&o.work_ref&&/^[a-f0-9]{64}$/.test(o.snapshot_sha256||'')&&/^[a-f0-9]{64}$/.test(o.offer_sha256||'')&&o.offer_ref==='model-offer-'+o.offer_sha256.slice(0,32)&&typeof o.expires_at==='string'&&Date.parse(o.expires_at)>Date.now());}
function realBasis(){return JSON.stringify([rt.ref,rt.overview?.project?.revision,rt.overview?.project?.input_version,rt.overview?.project?.brief_sha256,rt.overview?.stage1?.ledger?.state_sha256]);}
function realFollowupTargets(){const p=rt.overview?.project;return (rt.modelHistory?.actions||[]).map(row=>row.result||row).filter(j=>p&&j.project_ref===rt.ref&&j.input_version===p.input_version&&j.brief_sha256===p.brief_sha256&&j.operation!=='follow-up'&&['completed','content-review-pending','plan-validated-not-executed'].includes(j.status)&&j.output_ref&&j.output_sha256);}
function realFollowupDraft(){const p=rt.overview?.project,d=rt.followupDraft;return d&&d.ref===rt.ref&&d.input_version===p?.input_version?d:{ref:rt.ref,input_version:p?.input_version,output_ref:'',output_sha256:'',question:''};}
function realFollowupEnabled(){const p=rt.overview?.project,m=rt.overview?.models;return !!(p&&m?.project_ref===rt.ref&&m.input_version===p.input_version&&m.brief_sha256===p.brief_sha256&&m.followup_available===true&&m.followup_stages?.includes(1));}
function realFollowupOffers(){const p=rt.overview?.project;return realFollowupEnabled()?realModelOffers().map((o,i)=>({o,i})).filter(({o})=>p&&o.operation==='follow-up'&&o.stage===1&&o.available===true&&o.input_version===p.input_version&&o.brief_sha256===p.brief_sha256):[];}
function realFollowup(app){
 if(app.stage!==1)return '';const p=rt.overview?.project,m=rt.overview?.models,d=realFollowupDraft(),targets=realFollowupTargets(),offers=realFollowupOffers(),connected=realFollowupEnabled(),remaining=Number.isFinite(p?.settings?.budgets?.model_calls)&&Number.isFinite(m?.calls_reserved)?Math.max(0,p.settings.budgets.model_calls-m.calls_reserved):null;
 const target=targets.find(j=>j.output_ref===d.output_ref&&j.output_sha256===d.output_sha256),disabled=!connected||remaining===null||remaining<1||!target?'disabled':liveDisabled();
 return `<section class="real-workflow" data-v7-followup><h3>${rl('针对保存输出继续提问','Ask about a saved output')}</h3><p>${connected?rl('每次明确授权后建立一条受控内容任务，使用服务器绑定的有限历史。','Each explicit authorization creates a controlled content task using the limited history bound by the server.'):rl('当前服务尚未提供补充问答接口；保存输出仍可在下方查看。','This service has not offered follow-up Q&A. Saved outputs remain available below.')}</p><p>${rl('当前项目可用模型调用','Remaining project model calls')}: ${rx(remaining)} · ${rl('预算来自当前项目，不自动追加','Limits come from the current project and are not increased automatically')}</p>
 <label>${rl('提问针对的保存输出','Saved output to discuss')}<select data-v7-followup-target ${!connected?'disabled':liveDisabled()}><option value="">${rl('请选择输出','Choose an output')}</option>${targets.map(j=>`<option value="${rx(j.output_ref)}" ${d.output_ref===j.output_ref?'selected':''}>${rx(j.operation)} · ${rx(j.work_ref||j.output_ref.slice(0,12))} · ${rx(j.status)}</option>`).join('')}</select></label>
 <label>${rl('补充问题','Follow-up question')}<textarea data-v7-followup-question rows="3" maxlength="4096" ${!connected?'disabled':liveDisabled()}>${rx(d.question)}</textarea></label><label class="real-confirm"><input data-v7-followup-consent type="checkbox" ${disabled}> ${rl('授权当前项目对选定保存输出执行一次内容问答；不启动新检索、不修改产物或审阅决定。','Authorize one content discussion about this saved output in the current project; no new search or artifact/review changes.')}</label><button type="button" class="hs-button" data-v7-workflow="followup-authorize" ${disabled}>${rl('保存提问并授权一次','Save question & authorize once')}</button>
 ${offers.map(({o,i})=>`<div class="live-callout"><strong>${rl('服务器已授权的提问','Server-authorized question')}</strong><p>${rx(o.question)}</p><small>${rl('针对输出','Target output')}: ${rx(o.output_ref)}</small>${realButton('followup-send','发送这条已授权提问','Send this authorized question',true,i)}</div>`).join('')}
 <p><small>${rl('回复与原始问题分别保存。任务结束后没有待答问题是正常状态，不表示 Codex 断开。','Questions and replies are saved separately. No pending question after task completion is normal and does not mean Codex disconnected.')}</small></p></section>`;
}
function realCurrent(view){const p=rt.overview?.project;return !!(view&&p&&view.project_ref===rt.ref&&view.input_version===p.input_version&&(!view.revision||view.revision===p.revision)&&(!view.brief_sha256||view.brief_sha256===p.brief_sha256)&&(!view.ledger_state_sha256||view.ledger_state_sha256===rt.overview.stage1?.ledger?.state_sha256));}
function realButton(action,zh,en,enabled=true,index=null,tw=zh){return `<button type="button" class="hs-button" data-v7-workflow="${action}" ${index===null?'':`data-v7-index="${index}"`} ${enabled?liveDisabled():'disabled'}>${rl(zh,en,tw)}</button>`;}
function realLedgerBody(){return {...liveBound(),ledger_state_sha256:rt.overview?.stage1?.ledger?.state_sha256,confirmed:true};}
function realNativeInterruptTargets(){
 const p=rt.overview?.project,m=rt.overview?.models,n=rt.native,v=n?.native_view,hex=x=>typeof x==='string'&&/^[a-f0-9]{64}$/.test(x);
 if(!p||p.project_ref!==rt.ref||!Number.isSafeInteger(p.revision)||p.revision<0||!Number.isSafeInteger(p.input_version)||p.input_version<1||!hex(p.brief_sha256)||!realActionEnvelope(m)||m.input_version!==p.input_version||m.brief_sha256!==p.brief_sha256||m.connected!==true||n?.project_ref!==rt.ref||n.connected!==true||n.automatic_resend!==false||v?.project_ref!==rt.ref||v.failure||!Number.isSafeInteger(v.revision)||v.revision<0||!hex(v.index_sha256)||!hex(v.input_version)||!Array.isArray(v.operations)||!Array.isArray(n.native_actions)||!Array.isArray(m.jobs)||!Array.isArray(m.active_jobs))return [];
 const running=m.active_jobs.filter(j=>j?.status==='running'),jobs=m.jobs.filter(j=>j?.status==='running');
 if(running.length!==1||jobs.length!==1||running[0].key!==n.operation_key||jobs[0].key!==n.operation_key)return [];
 const job=jobs[0];if(job.project_ref!==rt.ref||job.input_version!==p.input_version||job.brief_sha256!==p.brief_sha256)return [];
 return v.operations.filter(o=>typeof o?.action_ref==='string'&&/^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$/.test(o.action_ref)&&hex(o.action_sha256)&&o.can_interrupt===true&&v.operations.filter(other=>other?.action_ref===o.action_ref).length===1&&!n.native_actions.some(a=>a?.operation==='interrupt'&&a.target_ref===o.action_ref&&(a.native_index_sha256==null||a.native_index_sha256===v.index_sha256)&&(a.native_input_version==null||a.native_input_version===v.input_version)&&!(a.status==='known-unsent'&&a.provider_invoked===false))).map(operation=>({operation,view:v,job}));
}
function realNativeControl(app){
 if(app.stage!==1)return '';const p=rt.overview?.project,n=rt.native,targets=realNativeInterruptTargets();
 const observations=p&&n&&p.project_ref===rt.ref&&n.project_ref===rt.ref&&Array.isArray(n.native_actions)?n.native_actions.filter(a=>a?.kind==='ProjectNativeActionObservation.v1'&&a.operation==='interrupt'&&a.project_ref===rt.ref&&a.project_input_version===p.input_version&&a.project_brief_sha256===p.brief_sha256):[];
 if(!targets.length&&!observations.length)return '';
 return `<details class="real-workflow" data-v7-panel="native-control"><summary>${rl('当前原生任务 · 停止请求与记录','Current native task · stop requests & records','當前原生任務 · 停止請求與記錄')}</summary><p>${rl('只向当前任务发出停止请求；回执不代表任务已经停止。结果与已预留额度继续保留，不会自动重发。','Request that the current task stop. A receipt does not mean it has stopped. Results and reserved usage are retained; requests are never resent automatically.','只向當前任務發出停止請求；回執不代表任務已經停止。結果與已預留額度繼續保留，不會自動重發。')}</p>${targets.map((t,i)=>`<p>${rx(t.job.operation)} · ${rx(t.operation.action_ref)}</p><label><input type="checkbox" data-v7-interrupt-confirm="${i}" ${liveDisabled()}>${rl('确认向此任务发出一次停止请求','Confirm one stop request for this task','確認向此任務發出一次停止請求')}</label>${realButton('model-interrupt','请求停止当前任务','Request current task stop',true,i,'請求停止當前任務').replace('<button ','<button data-v7-interrupt-binding="'+rx(realNativeTargetBinding(t))+'" ')}`).join('')}${observations.map(a=>`<p>${rl('停止请求记录','Stop request record','停止請求記錄')}: ${rx(a.status)} · ${rx(a.target_ref)}</p>`).join('')}</details>`;
}
function realNativeTargetBinding(t){return JSON.stringify([rt.ref,rt.overview.project.revision,rt.overview.project.input_version,rt.overview.project.brief_sha256,t.job.key,t.view.revision,t.view.index_sha256,t.view.input_version,t.operation.action_ref,t.operation.action_sha256]);}
function realSourceRecoveryOffer(){
 const p=rt.overview?.project,s=rt.overview?.stage1?.source_execution,o=s?.recovery_offer;
 if(!realActionEnvelope(s)||!o||o.kind!=='Stage1SourceOwnerRecoveryOffer'||o.schema_version!=='1.0.0'||o.operation!=='recover-source-owner'||o.status!=='available'||o.project_ref!==rt.ref||o.revision!==p.revision||o.input_version!==p.input_version||o.brief_sha256!==p.brief_sha256||o.execution_authorized!==false||o.automatic_dispatch!==false||o.automatic_retry!==false||!/^[a-f0-9]{64}$/.test(o.offer_sha256)||o.offer_ref!=='source-owner-recovery-'+o.offer_sha256.slice(0,32))return null;
 return o;
}
function realSavedActions(){
 const p=rt.overview?.project,s=rt.overview?.stage1;if(!p||!s)return '';
 const source=s.source_execution||{},grants=Object.values(source.grants||{}),jobs=Object.values(source.jobs||{}),offers=realModelOffers();
 const allowed=(realActionEnvelope(source)?grants:[]).filter(g=>g.status==='authorized'&&g.input_version===p.input_version&&g.brief_sha256===p.brief_sha256&&g.expires_at*1000>Date.now()&&!jobs.some(j=>j.grant_ref===g.grant_ref));
 const reading=offers.filter(realReadingExecutable);
 const registration=s.reading_registration,ready=!!(s.ledger&&s.checkpoint?.current===true&&s.saved_records_connected===true&&registration?.status==='ready'&&registration.grants_execution===false&&registration.missing_works?.length===0&&realCurrent(registration));
 return `<details class="real-workflow" data-v7-panel="sources"><summary>${rl('来源、阅读与交付','Sources, reading & delivery')}</summary><p>${rl('先从下方候选列表选择论文，分别完成筛选、来源、阅读与审阅。保存交付不代表覆盖门槛已通过。','Choose a paper below to screen, acquire, read and review it. A saved delivery does not mean the coverage gate passed.')}</p>
 ${realSourceRecoveryOffer()?`<p>${rl('服务重启后可恢复来源控制权与历史；原任务仍可能结果未知，此操作不会重发，也不授权新的来源或模型调用。','After a service restart, restore source control and history. Previous tasks can remain unknown; this action neither retries them nor authorizes a source or model call.','服務重啟後可恢復來源控制權與歷史；原任務仍可能結果未知，此操作不會重發，也不授權新的來源或模型呼叫。')}</p>${realButton('source-recover-owner','恢复来源控制权','Restore source control',true,null,'恢復來源控制權')}`:''}
 ${realActionEnvelope(source)&&jobs.some(j=>j.owner_recovery)?`<p role="status">${rl('已记录来源控制权恢复；原任务仍结果未知，未重新执行。','Source control recovery is recorded; the previous task remains unknown and was not executed again.','已記錄來源控制權恢復；原任務仍結果未知，未重新執行。')}</p>`:''}
 ${jobs.map(j=>`<p>${rx(j.work_ref)} · ${rl('来源','Acquisition')}: ${rx(j.status)} · ${rl('解析','Parsing')}: ${rx(j.followup?.status)} ${rx(j.failure?.code||j.followup?.failure?.code||'')}</p>`).join('')}
 ${allowed.map(g=>`<p>${rx(g.work_ref)} ${realButton('source-execute','执行已授权来源获取','Execute authorized acquisition',true,grants.indexOf(g))}</p>`).join('')}
 ${reading.map(o=>`<p>${rx(o.work_ref)} ${realButton('reading-execute','运行已授权 Codex 阅读','Run authorized Codex reading',true,offers.indexOf(o))}</p>`).join('')}
 <div class="real-action-row">${realButton('checkpoint','检查当前覆盖与状态','Checkpoint coverage & state',!!s.ledger)}${realButton('prepare','准备已审阅文献交付','Prepare reviewed delivery',ready)}</div>
 <p>${rl('当前阅读登记','Reading registration')}: ${rx(registration?.status)} · ${rl('缺少文献登记','Missing readings')}: ${rx(registration?.missing_works?.length)}</p>${realCoverage()}</details>`;
}
function realPaperActions(){
 const d=rt.paperDetail;if(!realCurrent(d)||d.binding?.ledger_state_sha256!==rt.overview?.stage1?.ledger?.state_sha256)return '';
 const row=d.row,reading=d.reading_offer,source=rt.sourceOffer,work=row.work_id;
 return `<section class="hs-panel live-files real-workflow" data-v7-paper-review><h3>${rx(row.metadata?.title||work)}</h3><p>${rl('筛选决定只更新当前论文；来源与阅读仍需单独执行。','Screening changes only this paper; acquisition and reading are separate steps.')}</p><label>${rl('筛选决定','Screening decision')}<select data-v7-screen><option value="pending">${rl('待定','Pending')}</option><option value="include">${rl('纳入','Include')}</option><option value="exclude">${rl('排除','Exclude')}</option></select></label><label>${rl('决定理由','Rationale')}<textarea data-v7-screen-note rows="2" maxlength="4096"></textarea></label>${realButton('screen','保存筛选决定','Save screening decision')}
 <div class="real-action-row">${realButton('source-preview','查看公开来源获取条件','Inspect source acquisition')}${realButton('reading-authorize','授权一次 Codex 阅读','Authorize one Codex reading',!!realReadingOffer(d))}${realButton('source-review','审阅已保存来源笔记','Review saved-source notes')}</div>
 <p>${rl('阅读条件','Reading eligibility')}: ${rx(reading?.available?rl('已有可读来源','Saved source available'):reading?.blocked_reason)}</p>
 ${source&&source.work_ref===work?`<div class="live-callout"><p>${rl('来源获取条件','Source acquisition offer')}: ${rx(source.status||source.blocked_reason||source.refusal||source.runner_connected)}</p><details><summary>${rl('来源与许可范围','Source & permission scope')}</summary><pre class="live-record">${rx(JSON.stringify(source,null,2))}</pre></details>${realButton('source-authorize','授权此公开来源获取','Authorize this source acquisition',source.runner_connected===true&&!!source.offer_ref&&!!source.offer_sha256)}</div>`:''}
 <label>${rl('本次阅读授权说明','Authorization explanation for this reading')}<textarea data-v7-reading-consent rows="2" maxlength="4096" placeholder="${rl('确认本次只读取这份已保存来源；此说明保存到授权记录。','Authorize reading only this saved source; this explanation is saved with the permission.')}"></textarea></label><p><small>${realFollowupEnabled()?rl('此说明不改变 Harness 的阅读提示词。阅读输出保存后，可在 Codex 区域选择该输出进行补充内容问答。','This explanation does not change the Harness reading prompt. After the output is saved, select it in the Codex panel for follow-up questions.','此說明不改變 Harness 的閱讀提示詞。閱讀輸出保存後，可在 Codex 區域選擇該輸出進行補充內容問答。'):rl('此说明不改变 Harness 的阅读提示词。保存后可查看阅读输出；当前服务的补充内容问答未接通。','This explanation does not change the Harness reading prompt. Saved reading output remains available to inspect; follow-up Q&A is unconnected in this service.','此說明不改變 Harness 的閱讀提示詞。保存後可查看閱讀輸出；目前服務的補充內容問答未接通。')}</small></p>
 </section>`;
}
const realNoteFields={classification:['topic_cluster','method','geography','population','data_type','domain'],findings:['question','data','method','main_findings','limitations','relevance','transferability']};
const realFieldNames={topic_cluster:['主题','Topic'],method:['方法','Method'],geography:['地区','Geography'],population:['研究对象','Population'],data_type:['数据类型','Data type'],domain:['领域','Domain'],question:['研究问题','Question'],data:['数据','Data'],main_findings:['主要发现','Findings'],limitations:['局限','Limitations'],relevance:['相关性','Relevance'],transferability:['可迁移性','Transferability']};
function realReadingReview(){
 const v=rt.readingView;if(!realCurrent(v))return '';const source=v.source_mode==='saved-source-review',notes=source?v:v.draft,offer=v.reading_review_offer;if(!notes)return '';
 return `<section class="hs-panel live-files real-workflow" data-v7-reading-review><h3>${rl('阅读与证据审阅','Reading & evidence review')}</h3><p>${rl('原始输出保留不变；只保存你确认的注释。无法核实的字段保留 Unknown。','The original output is retained. Save only reviewed annotations; unverifiable fields stay Unknown.')}</p><details><summary>${rl('查看来源与原文','Inspect sources & original output')}</summary><pre class="live-record">${rx(JSON.stringify(source?{sources:v.sources,claims:v.claims}:v.draft,null,2))}</pre></details>
 <details><summary>${rl('编辑阅读笔记','Edit reading notes')}</summary><div class="real-note-grid">${Object.entries(realNoteFields).flatMap(([group,fields])=>fields.map(k=>`<label>${rl(...realFieldNames[k])}<textarea rows="2" maxlength="4096" data-v7-note="${group}.${k}">${rx(notes[group]?.[k])}</textarea></label>`)).join('')}</div><label class="real-confirm"><input type="checkbox" data-v7-reading-confirm> ${rl('我已审阅这些注释；保存不代表 Stage1 完成。','I reviewed these notes; saving is not Stage1 completion.')}</label>${realButton('reading-save','保存审阅笔记','Save reviewed notes',!!offer?.offer_ref)}</details>
 ${(v.offers||[]).map((o,i)=>`<details class="real-claim"><summary>${rl('审阅证据片段','Review evidence span')} ${o.evidence_index+1}</summary><blockquote>${rx(o.quote)}</blockquote><p><small>${rx(o.source_id)}</small></p><label>${rl('此片段支持或反对的主张','Claim supported or challenged')}<textarea data-v7-claim-text="${i}" rows="2" maxlength="4096"></textarea></label><label>${rl('关系','Relation')}<select data-v7-claim-relation="${i}">${['pending','supports','partial','contradicts','unclear','unverifiable','context'].map(x=>`<option value="${x}">${x}</option>`).join('')}</select></label><label>${rl('证据范围','Evidence level')}<select data-v7-claim-level="${i}"><option value="abstract">${rl('摘要','Abstract')}</option><option value="full-text">${rl('全文','Full text')}</option></select></label><label>${rl('章节位置','Section')}<input data-v7-claim-section="${i}" maxlength="4096"></label>${realButton('claim-save','保存这条证据审阅','Save this evidence review',true,i)}</details>`).join('')}</section>`;
}
function realCoverage(){
 const s=rt.overview?.stage1,a=s?.coverage_actions;if(!a||a.ledger_state_sha256!==s.ledger?.state_sha256)return '';
 const offers=a.offers||[],o=offers[rt.coverageIndex],d=o?.document||{},claimSelect=(attr,key,label)=>`<label>${rx(label)}<select ${attr}="${rx(key)}"><option value="">Unknown</option>${(d.claims||[]).map(c=>`<option value="${rx(c.claim_ref)}">${rx(c.text)}</option>`).join('')}</select></label>`;
 let fields='';
 if(o?.operation==='review-work')fields=`<h4>${rx(d.title)}</h4><p>${rl('为相关主题和身份信息选择已有证据；无证据时保持 Unknown。','Choose saved evidence for topics and identity; missing evidence stays Unknown.')}</p>${(d.clusters||[]).map(c=>claimSelect('data-v7-cluster',c.cluster_id,c.title||c.cluster_id)).join('')}<label>${rl('身份核实','Identity assessment')}<select data-v7-identity><option value="unverifiable">${rl('无法核实','Unverifiable')}</option><option value="verified">${rl('已核实','Verified')}</option><option value="conflict">${rl('存在冲突','Conflict')}</option></select></label>${['title','authors','year','identifier','version'].map(k=>claimSelect('data-v7-identity-claim',k,k)).join('')}<label class="real-confirm"><input type="checkbox" data-v7-closest> ${rl('已核实为最接近研究','Verified closest work')}</label><label>${rl('审阅理由','Rationale')}<textarea data-v7-coverage-note rows="2" maxlength="4096"></textarea></label><details><summary>${rl('证据原文','Saved evidence')}</summary><pre class="live-record">${rx(JSON.stringify(d.claims,null,2))}</pre></details>`;
 else if(o?.operation==='receipt')fields=`<p>${rx(d.query)} · ${rx(d.result_count)}</p><label>${rl('查询结果是否截断','Were results truncated?')}<select data-v7-truncated><option value="">Unknown</option><option value="true">${rl('是','Yes')}</option><option value="false">${rl('否','No')}</option></select></label><label>${rl('观察说明','Observation')}<textarea data-v7-coverage-note rows="2" maxlength="4096"></textarea></label>`;
 else if(o?.operation==='human-action')fields=`<label>${rl('覆盖决定','Coverage decision')}<select data-v7-coverage-decision><option value="">${rl('请选择','Choose')}</option><option value="accept-stop">${rl('请求停止，仍受证据门槛约束','Request stop, subject to evidence gate')}</option><option value="request-cluster">${rl('补充某个主题','Request a cluster')}</option></select></label><label>${rl('待补充主题','Cluster for requested coverage')}<select data-v7-coverage-cluster><option value="">${rl('请选择','Choose')}</option>${(d.clusters||[]).map(c=>`<option value="${rx(c.cluster_id)}">${rx(c.title||c.cluster_id)}</option>`).join('')}</select></label><label>${rl('说明','Instruction')}<textarea data-v7-coverage-note rows="2" maxlength="4096"></textarea></label>`;
 else if(o)fields=`<p>${rl('目标覆盖轮次','Target coverage round')}: ${rx(d.round_number)} · ${rl('轮次变更不会自动执行检索','Changing the round does not run a search')}</p>`;
 const names={'review-work':rl('审阅论文覆盖','Review paper coverage'),receipt:rl('记录查询限制','Record query limits'),'open-round':rl('开启下一轮','Open next round'),'close-round':rl('关闭当前轮','Close current round'),'human-action':rl('人工覆盖决定','Human coverage decision')};
 return `<details class="real-workflow"><summary>${rl('覆盖与停止条件','Coverage & stopping conditions')}</summary><p>${(a.blockers||[]).map(x=>rx(typeof x==='string'?x:x.code)).join(' · ')||rl('暂无阻塞记录','No blockers recorded')}</p><label>${rl('当前可审阅操作','Available review action')}<select data-v7-coverage-choice><option value="">${rl('请选择','Choose')}</option>${offers.map((x,i)=>`<option value="${i}" ${i===rt.coverageIndex?'selected':''}>${rx(names[x.operation]||x.operation)} · ${rx(x.document?.title||x.document?.query||'')}</option>`).join('')}</select></label>${o?`<div data-v7-coverage-form>${fields}${realButton('coverage-save','保存覆盖审阅','Save coverage review',!a.held)}</div>`:''}</details>`;
}
function realText(value){if(typeof value!=='string'||!value.trim()||new TextEncoder().encode(value).length>4096||/[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/u.test(value))throw new Error(rl('请填写完整文字，每项不超过4096字节','Enter valid text within 4096 UTF-8 bytes'));return value;}
function realSourceOffer(value,ref,work){
 const p=rt.overview?.project,d=value?.document,b=d?.binding,detail=rt.paperDetail,ledger=rt.overview?.stage1?.ledger?.state_sha256;
 if(!p||p.project_ref!==ref||d?.kind!=='Stage1ProjectSourceAuthorizationOffer'||d.project_ref!==ref)throw new Error('read-project-binding-mismatch');
 if(!realCurrent(detail)||!work||detail.row?.work_id!==work||detail.binding?.ledger_state_sha256!==ledger||value.work_ref!==work||d.selected?.work_id!==work)throw new Error('read-source-work-binding-mismatch');
 if(value.revision!==p.revision||b?.input_version!==p.input_version||b.brief_sha256!==p.brief_sha256||!ledger||b.ledger_state_sha256!==ledger)throw new Error('read-source-input-binding-mismatch');
 // The server validates the complete canonical document again on authorization.
 if(typeof value.offer_sha256!=='string'||! /^[a-f0-9]{64}$/.test(value.offer_sha256)||value.offer_ref!=='project-source-'+value.offer_sha256.slice(0,32))throw new Error('read-source-offer-binding-mismatch');
 return {...value,project_ref:ref,input_version:b.input_version,brief_sha256:b.brief_sha256,ledger_state_sha256:b.ledger_state_sha256};
}
async function realRead(tail,property){
 const ref=rt.ref,basis=realBasis(),epoch=rt.epoch,work=property==='sourceOffer'?rt.paperDetail?.row?.work_id:null;
 let value=await liveRequest(projectPath(ref,tail));
 if(ref!==rt.ref||basis!==realBasis()||epoch!==rt.epoch)return false;
 if(property==='sourceOffer'){
  if(!work||tail!=='stage1/sources/works/'+encodeURIComponent(work))throw new Error('read-source-work-binding-mismatch');
  value=realSourceOffer(value,ref,work);
 }
 if(value.project_ref!==ref)throw new Error('read-project-binding-mismatch');
 rt[property]=value;livePaint();return true;
}
document.addEventListener('change',e=>{
 if(e.target.matches('[data-v7-followup-target]')){const target=realFollowupTargets().find(j=>j.output_ref===e.target.value);rt.followupDraft={...realFollowupDraft(),output_ref:target?.output_ref||'',output_sha256:target?.output_sha256||''};livePaint();}
 if(e.target.matches('[data-v7-coverage-choice]')){rt.coverageIndex=e.target.value===''?null:Number(e.target.value);livePaint();document.querySelector('[data-v7-coverage-form]')?.closest('details')?.setAttribute('open','');}
});
document.addEventListener('input',e=>{if(e.target.matches('[data-real-plan]')&&realPlanDraftCurrent()&&!rt.busy&&!rt.loading&&!rt.pending)rt.planDraft.text=e.target.value;if(e.target.matches('[data-v7-followup-question]'))rt.followupDraft={...realFollowupDraft(),question:e.target.value};});
document.addEventListener('click',async e=>{
 const button=e.target.closest('[data-v7-workflow]');if(!button||!liveReal())return;e.preventDefault();e.stopImmediatePropagation();if(rt.busy||rt.loading||rt.pending||button.disabled||rt.workflowReading)return;
 const action=button.dataset.v7Workflow,index=Number(button.dataset.v7Index),s=rt.overview?.stage1,p=rt.overview?.project,detail=rt.paperDetail,work=realCurrent(detail)&&detail.binding?.ledger_state_sha256===s?.ledger?.state_sha256?detail.row?.work_id:null;
 const read=async(tail,property)=>{rt.workflowReading=true;try{return await realRead(tail,property);}finally{rt.workflowReading=false;}};
 try{
  if(action==='model-interrupt'){
   if(apps[0].stage!==1)return;const target=realNativeInterruptTargets()[index];if(!target||button.dataset.v7InterruptBinding!==realNativeTargetBinding(target))return;
   if(document.querySelector(`[data-v7-interrupt-confirm="${index}"]`)?.checked!==true)throw new Error(rl('请确认本次停止请求','Confirm this stop request','請確認本次停止請求'));
   const v=target.view,o=target.operation;
   return await livePost('models/native/interrupt',{revision:v.revision,index_sha256:v.index_sha256,input_version:v.input_version,action_ref:o.action_ref,action_sha256:o.action_sha256});
  }
  if(action==='followup-authorize'){
   if(apps[0].stage!==1||!realFollowupEnabled())return;const d=realFollowupDraft(),target=realFollowupTargets().find(j=>j.output_ref===d.output_ref&&j.output_sha256===d.output_sha256),m=rt.overview.models,budget=p.settings?.budgets?.model_calls;
   if(!target||!Number.isFinite(budget)||!Number.isFinite(m.calls_reserved)||budget-m.calls_reserved<1)return;
   if(document.querySelector('[data-v7-followup-consent]')?.checked!==true)throw new Error(rl('请明确授权本次内容问答','Explicitly authorize this content discussion'));
   const question=realText(document.querySelector('[data-v7-followup-question]').value);rt.followupDraft={...d,question};
   return await livePost('models/authorize',{...liveBound(),operation:'follow-up',stage:1,output_ref:target.output_ref,output_sha256:target.output_sha256,question,user_input:rl('授权当前项目对选定保存输出执行一次内容问答；不启动新检索、不修改产物或审阅决定。','Authorize one content discussion about this saved output in the current project; no new search or artifact/review changes.'),confirmed:true});
  }
  if(action==='followup-send'){
   if(apps[0].stage!==1)return;const item=realFollowupOffers().find(x=>x.i===index);if(!item)return;const o=item.o;
   return await livePost('models/actions',{...liveBound(),offer_ref:o.offer_ref,offer_sha256:o.offer_sha256,confirmed:true});
  }
  if(action==='library-next'){
   const l=rt.library;if(!l||l.next_offset===null)return;const ref=rt.ref,basis=realBasis();rt.workflowReading=true;
   try{const page=await liveRequest(projectPath(ref,`stage1/screening/${p.input_version}/${s.ledger.state_sha256}/${l.next_offset}/${l.projection_sha256}`));if(ref!==rt.ref||basis!==realBasis())return;if(page.project_ref!==ref||page.input_version!==p.input_version||page.projection_sha256!==l.projection_sha256||page.offset!==l.next_offset)throw new Error('screening-page-binding-mismatch');rt.library={...page,rows:[...l.rows,...page.rows]};livePaint();}finally{rt.workflowReading=false;}return;
  }
  if(action==='source-preview'&&work)return await read('stage1/sources/works/'+encodeURIComponent(work),'sourceOffer');
  if(action==='source-recover-owner'){
   if(apps[0].stage!==1)return;const o=realSourceRecoveryOffer();if(!o)return;
   return await livePost('stage1/sources/recover-owner',{...liveBound(),offer_ref:o.offer_ref,offer_sha256:o.offer_sha256,confirmed:true});
  }
  if(action==='source-authorize'&&work){const o=rt.sourceOffer;if(o)realSourceOffer(o,rt.ref,work);if(o?.work_ref===work&&o.runner_connected===true&&o.offer_ref&&o.offer_sha256)return await livePost('stage1/sources/authorize',{...liveBound(),work_ref:work,offer_ref:o.offer_ref,offer_sha256:o.offer_sha256,confirmed:true});return;}
  if(action==='source-execute'){if(!realActionEnvelope(s?.source_execution))return;const g=Object.values(s.source_execution.grants||{})[index];if(g&&g.status==='authorized'&&g.input_version===p.input_version&&g.brief_sha256===p.brief_sha256&&g.expires_at*1000>Date.now()&&!Object.values(s.source_execution?.jobs||{}).some(j=>j.grant_ref===g.grant_ref))return await livePost('stage1/sources/execute',{...liveBound(),grant_ref:g.grant_ref,grant_sha256:g.grant_sha256,confirmed:true});return;}
  if(action==='screen'&&work){const decision=document.querySelector('[data-v7-screen]').value,rationale=realText(document.querySelector('[data-v7-screen-note]').value);if(!['include','exclude','pending'].includes(decision))return;return await livePost('stage1/screen',{...realLedgerBody(),work_ref:work,decision,rationale});}
  if(action==='reading-authorize'&&work){const o=realReadingOffer(detail);if(!o)return;return await livePost('models/authorize',{...liveBound(),operation:'read-paper',work_ref:work,snapshot_sha256:o.snapshot_sha256,user_input:realText(document.querySelector('[data-v7-reading-consent]').value),confirmed:true});}
  if(action==='reading-execute'){const o=realModelOffers()[index];if(realReadingExecutable(o))return await livePost('models/actions',{...liveBound(),offer_ref:o.offer_ref,offer_sha256:o.offer_sha256,confirmed:true});return;}
  if(action==='source-review'&&work)return await read('stage1/source-reading/'+encodeURIComponent(work),'readingView');
  if(action==='reading-draft'){const row=rt.modelHistory.actions[index],r=row?.result||row;if(r?.operation==='read-paper'&&r.output_ref)return await read('stage1/reading/'+encodeURIComponent(r.output_ref),'readingView');return;}
  if(action==='reading-save'){
   const v=rt.readingView,o=v?.reading_review_offer;if(!realCurrent(v)||!o)return;const form=document.querySelector('[data-v7-reading-review]');if(!form.querySelector('[data-v7-reading-confirm]').checked)throw new Error(rl('请先明确确认已审阅','Confirm that you reviewed these notes'));
   const review={classification:{},findings:{},roles:v.source_mode==='saved-source-review'?v.roles:[]};for(const [group,keys]of Object.entries(realNoteFields))for(const key of keys)review[group][key]=realText(form.querySelector(`[data-v7-note="${group}.${key}"]`).value);
   const binding=v.source_mode==='saved-source-review'?{work_ref:v.work_ref,source_snapshot_sha256:v.source_snapshot_sha256}:{output_ref:v.output_ref,draft_sha256:v.draft_sha256};
   return await livePost('stage1/reading-review',{...realLedgerBody(),...binding,offer_ref:o.offer_ref,offer_sha256:o.offer_sha256,review});
  }
  if(action==='claim-save'){
   const v=rt.readingView,o=v?.offers?.[index];if(!realCurrent(v)||!o)return;const get=name=>document.querySelector(`[data-v7-claim-${name}="${index}"]`).value;
   return await livePost('stage1/claim',{...realLedgerBody(),output_ref:v.output_ref,draft_sha256:v.draft_sha256,evidence_index:o.evidence_index,offer_ref:o.offer_ref,offer_sha256:o.offer_sha256,review:{claim_text:realText(get('text')),section:realText(get('section')),relation:get('relation'),evidence_level:get('level')}});
  }
  if(action==='checkpoint'&&s.ledger)return await livePost('stage1/checkpoint',realLedgerBody());
  if(action==='prepare'){
   const r=s.reading_registration;if(!s.checkpoint?.current||!realCurrent(r)||r?.status!=='ready'||r.missing_works?.length!==0||s.saved_records_connected!==true)return;
   const recovery=s.saved_records_recovery?.revision===p.revision?s.saved_records_recovery.offers?.find(o=>o.status==='ready-for-saved-records-registration'):null;
   const body={...realLedgerBody(),checkpoint_event_id:s.checkpoint.event_id};if(recovery)Object.assign(body,Object.fromEntries(['producer_key','producer_request_sha256','records_sha256','checkpoint_event_id'].map(k=>[k,recovery[k]])));
   return await livePost(recovery?'stage1/recover-delivery':'stage1/prepare-delivery',body);
  }
  if(action==='coverage-save'){
   const a=s.coverage_actions,o=a?.offers?.[rt.coverageIndex];if(!o||a.held||a.ledger_state_sha256!==s.ledger?.state_sha256)return;const form=document.querySelector('[data-v7-coverage-form]'),val=selector=>form.querySelector(selector).value;let review={};
   if(o.operation==='review-work'){const entries=selector=>Array.from(form.querySelectorAll(selector));review={cluster_claims:Object.fromEntries(entries('[data-v7-cluster]').filter(n=>n.value).map(n=>[n.dataset.v7Cluster,n.value])),identity_status:val('[data-v7-identity]'),identity_claims:Object.fromEntries(entries('[data-v7-identity-claim]').map(n=>[n.dataset.v7IdentityClaim,n.value||null])),closest:form.querySelector('[data-v7-closest]').checked,rationale:realText(val('[data-v7-coverage-note]'))};if(!Object.keys(review.cluster_claims).length)throw new Error(rl('至少为一个主题选择已有证据','Choose saved evidence for at least one cluster'));}
   else if(o.operation==='receipt'){const value=val('[data-v7-truncated]');review={truncated:value===''?null:value==='true',note:realText(val('[data-v7-coverage-note]'))};}
   else if(o.operation==='human-action'){const choice=val('[data-v7-coverage-decision]'),cluster=val('[data-v7-coverage-cluster]');if(!['accept-stop','request-cluster'].includes(choice)||(choice==='request-cluster'&&!cluster))throw new Error(rl('请明确选择覆盖决定及主题','Choose a coverage decision and required cluster'));review={action:choice,cluster_id:choice==='request-cluster'?cluster:null,user_input:realText(val('[data-v7-coverage-note]'))};}
   else if(!['open-round','close-round'].includes(o.operation))return;
   return await livePost('stage1/coverage',{...realLedgerBody(),operation:o.operation,offer_ref:o.offer_ref,offer_sha256:o.offer_sha256,review});
  }
 }catch(error){rt.error=error.message;livePaint();}
},true);
