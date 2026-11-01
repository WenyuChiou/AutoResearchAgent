// Wiki Stage 2 / Stage 3 entry and saved-plan graph. Reading never dispatches planning.
// Utility pages describe their own purpose rather than repeating the active stage.
if(typeof otherPage==='function'){
 const v93OtherPage=otherPage;
 otherPage=function(app){
  const labels={files:rl('项目文件','Project files','專案檔案'),history:rl('操作历史','History','操作歷史'),settings:rl('连接与设置','Connection and settings','連線與設定')};
  const html=v93OtherPage(app),title=labels[app.page];if(!title)return html;
  const heading=`<h1>${title}</h1>`;
  return /<h1>[^]*?<\/h1>/.test(html)?html.replace(/<p class="hs-eyebrow">[^<]*<\/p>/,'<p class="hs-eyebrow">PROJECT</p>').replace(/<h1>[^]*?<\/h1>(?:<p>[^]*?<\/p>)?/,heading):`<div class="hs-heading">${heading}</div>${html}`;
 };
}
const v93={view:null,basis:null,errorBasis:null,sequence:0,busy:false,error:''};
function v93ValidProject(p){return !!p&&((typeof p.input_version==='string'&&p.input_version.length>0&&p.input_version.length<=128)||(Number.isSafeInteger(p.input_version)&&p.input_version>=0))&&Number.isSafeInteger(p.revision)&&p.revision>=0&&typeof p.brief_sha256==='string'&&/^[a-f0-9]{64}$/.test(p.brief_sha256);}
function v93Identity(){
 const p=rt.overview?.project;
 if(!v93ValidProject(p)||p.project_ref!==rt.ref||canonicalReadonly()||!Array.isArray(window.RESEARCH_PROJECTS?.stage3_planning_projects)||!window.RESEARCH_PROJECTS.stage3_planning_projects.includes(rt.ref))return null;
 return {project_ref:p.project_ref,input_version:p.input_version,revision:p.revision,brief_sha256:p.brief_sha256};
}
function v93Matches(a,b){return !!a&&!!b&&['project_ref','input_version','revision','brief_sha256'].every(k=>a[k]===b[k]);}
function v93Language(app){return {zh:'zh-CN',tw:'zh-TW',en:'en'}[app.lang]||'en';}
function v93Fragment(ref,app,stage){return '#'+encodeURIComponent(ref)+'?stage='+stage+'&lang='+encodeURIComponent(v93Language(app));}
function v93RouteTarget(list){
 const raw=location.hash.slice(1),i=raw.indexOf('?');if(i<0)return null;
 let ref;try{ref=decodeURIComponent(raw.slice(0,i));}catch(_){return null;}
 const params=new URLSearchParams(raw.slice(i+1)),stage=Number(params.get('stage')),lang=params.get('lang');
  if(!/^[A-Za-z0-9_-]{1,64}$/.test(ref)||!Number.isInteger(stage)||stage<1||stage>6||!['en','zh-TW','zh-CN'].includes(lang)||!list.some(p=>p.project_ref===ref))return null;
 return {ref,stage,lang:{en:'en','zh-TW':'tw','zh-CN':'zh'}[lang]};
}
// Restore only the currently loaded project; navigation never submits or refreshes it.
function v93RestoreStageRoute(){
 const route=v93RouteTarget(rt.list),app=apps[0];
 if(!route||!app||route.ref!==rt.ref||rt.overview?.project?.project_ref!==route.ref)return;
 if(app.page==='workspace'&&app.stage===route.stage&&app.lang===route.lang)return;
 app.lang=route.lang;localStage(app,route.stage,{historyMode:'restore'});livePaint();
}
window.addEventListener('popstate',v93RestoreStageRoute);
window.addEventListener('hashchange',v93RestoreStageRoute);
const v93Choices=new Map();let v93ActiveChoice=null;
function v93ChoiceIdentity(){
 const p=rt.overview?.project, configured=window.RESEARCH_PROJECTS?.stage2_selection_projects;
 if(!v93ValidProject(p)||p.project_ref!==rt.ref||canonicalReadonly()||!Array.isArray(configured)||!configured.includes(rt.ref))return null;
 return {project_ref:p.project_ref,input_version:p.input_version,revision:p.revision,brief_sha256:p.brief_sha256};
}
const v93Before=v7BeforeRender;
v7BeforeRender=function(app){
 v93Before(app);
 if(!v93ActiveChoice)return;
 const keep=app.page==='workspace'&&app.stage===2&&v93Matches(v93ActiveChoice.binding,v93ChoiceIdentity());
 if(!keep){v93ActiveChoice.instance.suspend();v93ActiveChoice.focus=null;v93ActiveChoice=null;}
 else {const focused=v93ActiveChoice.element.shadowRoot?.activeElement;v93ActiveChoice.focus=focused?{element:focused,start:focused.selectionStart,end:focused.selectionEnd}:null;}
};
const v93Stage2=stage2;
stage2=function(app){
 const original=v93Stage2(app),basis=v93ChoiceIdentity();
 if(!basis)return original;
 return `<section class="hs-panel"><h2>${rl('当前交付的研究方向','Directions in the current delivery','目前交付的研究方向')}</h2><p>${rl('在此查看方向、材料和未知事项，再决定保存暂定偏好或正式选案。','Review the current directions, materials and unknowns here; a tentative preference is not a formal selection.','在此查看方向、材料與未知事項，再決定保存暫定偏好或正式選案。')}</p><div data-v93-choice></div></section><details class="hs-panel"><summary>${rl('先前 Wiki 材料与本地草稿','Earlier Wiki materials and local drafts','先前 Wiki 材料與本地草稿')}</summary><p>${rl('这些材料可能来自较早的导入版本，不能替代目前交付。','These materials may come from an earlier import and do not replace the current delivery.','這些材料可能來自較早匯入版本，不能取代目前交付。')}</p>${original}</details>`;
};
function v93RecoveryControl(target,record,basis,app){
 const box=document.createElement('div'),message=document.createElement('p');
 message.textContent=rl('先前提交尚未确认；请检查原收据，不会自动重送。','An earlier submission is unconfirmed. Check its original receipt; nothing will be resent automatically.','先前送出尚未確認；請檢查原收據，不會自動重送。');
 box.append(message);target.append(box);
 const entries=record.instance.pendingActions?.(), pending=Array.isArray(entries)&&entries.length?entries:[null];
 const isCurrent=()=>app.page==='workspace'&&app.stage===2&&v93Matches(basis,v93ChoiceIdentity());
 for(const entry of pending){
  const button=document.createElement('button');button.type='button';
  button.textContent=rl('检查未确认提交','Check unconfirmed submission','檢查未確認提交')+(entry?' · '+entry.key:'');box.append(button);
  button.onclick=async()=>{
   if(button.disabled||!isCurrent())return;button.disabled=true;
   try{
    const result=await record.instance.reconcile(basis,entry?.key);
    if(!isCurrent())return;
    if(result?.status==='verified'){
     if(record.instance.dispose()){v93Choices.delete(basis.project_ref);v93ActiveChoice=null;}
     livePaint();return;
    }
    if(entry&&['failed','superseded'].includes(result?.status)){
     message.textContent=result.status==='failed'?rl('规划已失败；原失败记录会保留。','Planning failed; the original failure record is retained.','規劃已失敗；原失敗紀錄會保留。'):rl('此偏好已被较新的偏好取代；原记录会保留。','This preference has been replaced by a newer one; the original record is retained.','此偏好已被較新的偏好取代；原紀錄會保留。');
     const acknowledge=document.createElement('button');acknowledge.type='button';acknowledge.textContent=rl('确认并解除此项等待','Acknowledge and clear this pending item','確認並解除此項等待');box.append(acknowledge);
     acknowledge.onclick=async()=>{
      if(acknowledge.disabled||!isCurrent()||typeof window.confirm!=='function'||!window.confirm(rl('确认保留原记录并解除这项等待？不会自动重送。','Keep the original record and clear this pending item? Nothing will be resent.','確認保留原紀錄並解除這項等待？不會自動重送。')))return;
      acknowledge.disabled=true;
      try{const done=await record.instance.acknowledgeTerminal(basis,entry.key);if(!isCurrent())return;
       if(done?.status==='acknowledged'){if(record.instance.dispose()){v93Choices.delete(basis.project_ref);v93ActiveChoice=null;}livePaint();return;}
       message.textContent=rl('此项仍未能安全解除。','This item cannot yet be cleared safely.','此項仍無法安全解除。')+' ('+String(done?.code||done?.status||'unknown')+')';
      }catch(error){message.textContent=rl('检查失败，原记录已保留。','The check failed; the original record is retained.','檢查失敗，原紀錄已保留。')+' ('+String(error?.message||error)+')';}finally{acknowledge.disabled=false;}
     };return;
    }
    message.textContent=(result?.code==='project-lock-busy'?rl('另一页面正在处理此项目，请稍后再检查。','Another tab is handling this project; check again later.','另一個分頁正在處理此專案，請稍後再檢查。'):result?.code==='project-lock-unavailable'?rl('此浏览器不支持安全的跨页面锁，无法提交或解除等待。','This browser cannot provide the required cross-tab lock; submitting and clearing pending items are unavailable.','此瀏覽器不支援必要的跨分頁鎖，無法送出或解除等待。'):rl('尚未能确认原提交；请保留原收据并稍后重查。','The original submission is not yet verified; retain its receipt and check again later.','尚未能確認原送出；請保留原收據並稍後重查。'))+' ('+String(result?.code||result?.status||'unknown')+')';
   }catch(error){message.textContent=rl('检查失败，原提交仍未确认。','The check failed; the original submission remains unconfirmed.','檢查失敗，原送出仍未確認。')+' ('+String(error?.message||error)+')';}
   finally{button.disabled=false;}
  };
 }
}
function v93MountChoice(app){
 const target=app.el.querySelector('[data-v93-choice]'),basis=v93ChoiceIdentity();
 if(app.page!=='workspace'||app.stage!==2||!target||!basis)return;
 const template=document.getElementById('v93-selection-template');
 if(!template||!window.STAGE2_SELECTION){target.textContent=rl('选案元件尚未连接。','The selection component is unavailable.','選案元件尚未連接。');return;}
 let record=v93Choices.get(basis.project_ref);
 if(record&&!v93Matches(record.binding,basis)){
  if(!record.instance.dispose()){v93RecoveryControl(target,record,basis,app);return;}
  v93Choices.delete(basis.project_ref);record=null;
 }
 if(!record){
  const element=document.createElement('div'),root=element.attachShadow({mode:'open'}),css=document.createElement('link');
  css.rel='stylesheet';css.href='/project-stage2-selection.css';root.append(css,template.content.cloneNode(true));
  const nav=root.querySelector('nav');if(nav)nav.style.display='none'; // Wiki owns the outer project and language controls.
  const current=b=>app.page==='workspace'&&app.stage===2&&v93Matches(b,v93ChoiceIdentity());
   const navigate=event=>{
    if(current(basis)&&event?.projectRef===basis.project_ref&&['en','zh-TW','zh-CN'].includes(event.language)){
     window.location.hash=v93Fragment(event.projectRef,{lang:{en:'en','zh-TW':'tw','zh-CN':'zh'}[event.language]||'en'},3);
     // Hash-only navigation keeps the pre-write overview. Re-enter the existing
     // authenticated bootstrap to read the committed revision without resending.
     window.location.reload();
    }
   };
  const instance=window.STAGE2_SELECTION.mount(root,{embedded:true,bootstrap:window.RESEARCH_PROJECTS,binding:basis,language:v93Language(app),isCurrent:current,onAccepted:navigate,onNavigate:navigate,onRecoveryChange:()=>{if(current(basis))livePaint();}});
  record={binding:basis,element,instance,language:v93Language(app)};v93Choices.set(basis.project_ref,record);
 }
 if(record.instance.state().recovery)v93RecoveryControl(target,record,basis,app);
 target.append(record.element);v93ActiveChoice=record;
 if(record.focus&&(!document.activeElement||document.activeElement===document.body)){
  try{record.focus.element.focus({preventScroll:true});if(Number.isInteger(record.focus.start)&&Number.isInteger(record.focus.end))record.focus.element.setSelectionRange(record.focus.start,record.focus.end);}catch(_){}
 }
 record.focus=null;
 if(record.language!==v93Language(app)){record.instance.setLanguage(v93Language(app));record.language=v93Language(app);}
 record.instance.resume();
}
function v93SavedPlanSummary(view){
 const plan=view?.plan;if(plan?.kind!=='Stage3DirectionPlanningResult')return '';
 const text=typeof plan.markdown==='string'?plan.markdown:'',lead=text.split(/\n\s*\n/)[0];
 const questions=Array.isArray(view.direction_context?.questions)?view.direction_context.questions:[];
 const rows=Array.isArray(plan.question_plans)?plan.question_plans:[];
 const labels={method:rl('方法','Method','方法'),materials:rl('资料与参考','Data and references','資料與參考'),design:rl('实验设计','Study design','實驗設計'),analysis:rl('分析','Analysis','分析'),interpretation:rl('结果判读','Interpretation','結果判讀'),validation:rl('验证','Validation','驗證'),minimum_deliverable:rl('最小交付','Minimum deliverable','最小交付')};
 const content=rows.map((row,index)=>{
  const question=questions.find(q=>q.question_ref===row.question_ref),title=question?.text||rl('研究问题','Research question','研究問題')+' '+(index+1);
   const stages=[['question',rl('研究问题','Research question','研究問題'),title],
    ['materials',labels.materials,row.materials],['method',labels.method,row.method],
    ['design',labels.design,row.design],['analysis',labels.analysis,row.analysis],
    ['validation',labels.validation,row.validation],['interpretation',labels.interpretation,row.interpretation],
    ['minimum_deliverable',labels.minimum_deliverable,row.minimum_deliverable]];
   const missing=rl('尚未记录；请查看完整原记录。','Not recorded; inspect the complete source record.','尚未記錄；請查看完整原紀錄。');
   const valueText=value=>typeof value==='string'&&value.trim()?value:missing;
   const preview=value=>{const text=valueText(value);return text.length>150?text.slice(0,149).trimEnd()+'…':text;};
   // These are source-field navigation steps, not inferred scientific edges or pass states.
   const flow=`<h4>${rl('研究规划流程（拟议）','Proposed research planning flow','研究規劃流程（擬議）')}</h4><p class="n9-flow-note">${rl('顺序表示规划如何组织；各步骤尚未执行。选择一步查看完整原文；资料与方法仍待核验。','The sequence organizes the plan; these steps have not been run. Open a step to read its complete source. Materials and methods still require verification.','順序表示規劃如何組織；各步驟尚未執行。選擇一步查看完整原文；資料與方法仍待核驗。')}</p><ol class="n9-plan-flow n9-source-flow">${stages.map(([key,heading,value],step)=>`<li><details class="n9-flow-source"><summary><span class="n9-flow-heading"><span aria-hidden="true">${step+1}</span><strong>${heading}</strong></span><span class="n9-plan-preview">${rx(preview(value))}</span></summary><p class="n9-source-text">${rx(valueText(value))}</p><small>${rx(key==='question'?'/direction_context/questions':`/plan/question_plans/${index}/${key}`)}</small></details></li>`).join('')}</ol>`;
   const cards=Array.isArray(view.direction_context?.preferred_cards)?view.direction_context.preferred_cards:[];
   const questionCards=cards.flatMap(card=>(Array.isArray(card.scientific_questions)?card.scientific_questions:[]).filter(item=>item.question?.question_id&&row.question_ref===`${card.candidate_id}@${card.candidate_version}/${item.question.question_id}`));
   const uses=questionCards.flatMap(item=>Array.isArray(item.resource_uses)?item.resource_uses:[]);
   const resourceRows=uses.map(use=>{const resource=use.resource||{},ref=use.resource_ref||{};return `<tr><th scope="row">${rx(valueText(resource.name))}</th><td>${rx(valueText(ref.purpose||resource.purpose))}</td><td>${rx(typeof resource.status==='string'?resource.status:'unknown')}<br>${rx(typeof ref.fit_status==='string'?ref.fit_status:'unknown')}</td></tr>`;}).join('');
   const materials=`<section class="n9-material-map"><h4>${rl('材料如何支持这个问题','How materials support this question','材料如何支持這個問題')}</h4><p>${rl('下表仅显示已明确映射的资源；材料说明中的其他线索不等于已可用数据。','Only explicitly mapped resources appear below. Other leads in the material description do not establish available data.','下表僅顯示已明確映射的資源；材料說明中的其他線索不等於已可用資料。')}</p>${resourceRows?`<div class="n9-material-scroll" role="region" tabindex="0" aria-label="${rl('材料用途对照表','Material-use table','材料用途對照表')}"><table><thead><tr><th>${rl('资源','Resource','資源')}</th><th>${rl('用途','Use','用途')}</th><th>${rl('可用性／适配','Availability / fit','可用性／適配')}</th></tr></thead><tbody>${resourceRows}</tbody></table></div>`:`<p class="n9-material-unknown">${rl('本问题没有已映射的资源；保持 unknown。','No resources are mapped to this question; availability remains unknown.','本問題沒有已映射的資源；保持 unknown。')}</p>`}<details class="n9-plan-details"><summary>${labels.materials} · ${rl('完整原记录','Complete source record','完整原紀錄')}</summary><p>${rx(valueText(row.materials))}</p></details></section>`;
  const fields=Object.entries(labels).filter(([key])=>typeof row[key]==='string').map(([key,label])=>`<h4>${label}</h4><p>${rx(row[key])}</p>`).join('');
  const unknowns=Array.isArray(row.unknowns)?row.unknowns:[];
    return `<article class="n9-plan-question"><h3>${rx(title)}</h3><p>${unknowns.length} ${rl('项待查事项','open checks','項待查事項')}</p>${flow}${materials}<details class="n9-plan-details"><summary>${rl('完整规划与待查事项','Full planning details and open checks','完整規劃與待查事項')}</summary>${fields}<h4>${rl('待查事项','Open checks','待查事項')}</h4><ul>${unknowns.map(item=>`<li>${rx(typeof item==='string'?item:JSON.stringify(item))}</li>`).join('')}</ul><p>${rx(row.question_ref||'')}</p></details></article>`;
 }).join('');
 return `<section class="n9-plan-overview"><h2>${rl('已保存的规划摘要','Saved planning summary','已保存的規劃摘要')}</h2><p class="n9-plan-state">${plan.planning_status==='conditional-draft'?rl('条件式草案','Conditional draft','條件式草案'):rl('规划草案','Planning draft','規劃草案')} · ${rl('尚未执行实验','Experiments have not been run','尚未執行實驗')}</p>${lead?`<p class="n9-plan-lead">${rx(lead)}</p>`:''}${content}</section>`;
}
const v93Later=laterStage;
laterStage=function(app){
 const basis=v93Identity();if(app.stage!==3||!basis)return v93Later(app);
 const view=v93Matches(v93.basis,basis)?v93.view:null, error=v93Matches(v93.errorBasis,basis)?v93.error:'';
 const href='/project-stage3-planning.html'+v93Fragment(basis.project_ref,app,3);
 return `${canonicalTop()}<section class="hs-panel"><p class="hs-eyebrow">STAGE 03</p><h1>${rl('研究设计与可行性','Research design & feasibility','研究設計與可行性')}</h1><p>${rl('将偏好方向逐题对应到资料、方法、设计与结果判读；草案不代表研究已执行。','Connect the preferred direction to data, methods, study design and interpretation, one question at a time. A draft does not mean research has been run.','將偏好方向逐題對應到資料、方法、設計與結果判讀；草案不代表研究已執行。')}</p><div class="n9-page-actions"><button class="hs-button hs-button-primary" data-v93-read ${v93.busy?'disabled':''}>${rl('查看已保存的规划','View saved plan','檢視已保存的規劃')}</button><a class="hs-button" href="${rx(href)}">${rl('打开规划与收据','Open planning and receipt','開啟規劃與收據')}</a></div><p role="status">${rx(error||(v93.busy?rl('正在读取已保存的规划，不会重新生成。','Reading the saved plan; no generation will be started.','正在讀取已保存的規劃，不會重新生成。'):!view?rl('先读取已保存的规划，查看摘要与待查事项。','Read the saved plan to see its summary and open checks.','先讀取已保存的規劃，查看摘要與待查事項。'):!view.plan?rl('目前没有已保存的规划；图中仅显示可用的问题与待确认事项。','No saved plan is available; the diagram shows only available questions and unknowns.','目前沒有已保存的規劃；圖中僅顯示可用的問題與待確認事項。'):''))}</p>${v93SavedPlanSummary(view)}<details class="n9-plan-graph"${view?.plan?.kind==='Stage3ResearchPlan'?' open':''}><summary>${rl('研究关系图与来源','Research map and sources','研究關係圖與來源')}</summary><div id="v93-diagram"></div></details></section>`;
};
const v93After=v7AfterRender;
v7AfterRender=function(app){
 v93After(app);v93MountChoice(app);const basis=v93Identity(),target=app.el.querySelector('#v93-diagram');
 if(app.stage===3&&target&&v93Matches(v93.basis,basis)&&v93.view&&window.STAGE3_RESEARCH_DIAGRAM)
  window.STAGE3_RESEARCH_DIAGRAM.mount(target,v93.view,{language:v93Language(app)});
};
document.addEventListener('click',async event=>{
 const button=event.target.closest('[data-v93-read]');if(!button||v93.busy)return;
 const app=apps.find(a=>a.el.contains(button)),basis=v93Identity();if(!app||app.stage!==3||!basis)return;
 const epoch=rt.epoch,sequence=++v93.sequence;v93.busy=true;v93.error='';v93.errorBasis=null;v93.view=null;v93.basis=null;livePaint();
 try{
  const view=await liveRequest(projectPath(basis.project_ref,'stage3/planning'));
  if(sequence!==v93.sequence||epoch!==rt.epoch||!v93Matches(basis,v93Identity()))return;
  if(!v93Matches(basis,view))throw Error('project or version differs; refresh the project');
  v93.view=view;v93.basis=basis;
 }catch(error){if(sequence===v93.sequence&&epoch===rt.epoch&&v93Matches(basis,v93Identity())){v93.error=String(error.message||error);v93.errorBasis=basis;}}
 finally{if(sequence===v93.sequence){v93.busy=false;livePaint();}}
});
