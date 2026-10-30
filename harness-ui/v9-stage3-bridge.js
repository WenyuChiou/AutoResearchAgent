// Wiki Stage 2 / Stage 3 entry and saved-plan graph. Reading never dispatches planning.
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
 if(!/^[A-Za-z0-9_-]{1,64}$/.test(ref)||![2,3].includes(stage)||!['en','zh-TW','zh-CN'].includes(lang)||!list.some(p=>p.project_ref===ref))return null;
 return {ref,stage,lang:{en:'en','zh-TW':'tw','zh-CN':'zh'}[lang]};
}
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
  const navigate=event=>{if(current(basis)&&event?.projectRef===basis.project_ref&&['en','zh-TW','zh-CN'].includes(event.language))window.location.assign('/'+v93Fragment(event.projectRef,{lang:{en:'en','zh-TW':'tw','zh-CN':'zh'}[event.language]||'en'},3));};
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
const v93Later=laterStage;
laterStage=function(app){
 const basis=v93Identity();if(app.stage!==3||!basis)return v93Later(app);
 const view=v93Matches(v93.basis,basis)?v93.view:null, error=v93Matches(v93.errorBasis,basis)?v93.error:'';
 const href='/project-stage3-planning.html'+v93Fragment(basis.project_ref,app,3);
 return `${canonicalTop()}<section class="hs-panel"><p class="hs-eyebrow">STAGE 03</p><h1>${rl('研究设计与可行性','Research design & feasibility','研究設計與可行性')}</h1><p>${rl('图表只展示已保存规划的明确关系，不代表研究已经执行。','The diagram shows explicit relationships in the saved plan; research has not been run.','圖表只顯示已保存規劃的明確關係，不代表研究已執行。')}</p><a class="hs-button" href="${rx(href)}">${rl('打开规划与收据','Open planning and receipt','開啟規劃與收據')}</a> <button class="hs-button" data-v93-read ${v93.busy?'disabled':''}>${rl('读取保存的规划图','Read saved planning diagram','讀取已保存的規劃圖')}</button><p role="status">${rx(error||(!view?rl('尚未读取规划。','No saved plan read yet.','尚未讀取規劃。'):!view.plan?rl('目前没有已保存的规划；图中仅显示可用的问题与待确认事项。','No saved plan is available; the diagram shows only available questions and unknowns.','目前沒有已保存的規劃；圖中僅顯示可用的問題與待確認事項。'):''))}</p><div id="v93-diagram"></div></section>`;
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
