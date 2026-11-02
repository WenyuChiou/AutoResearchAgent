// Manual comments/drafts use the current saved-plan binding and existing Host only.
const v94fStates = new Map();
const v94fFields = ['method','materials','design','analysis','interpretation','validation','minimum_deliverable'];
const v94fBindingFields = ['project_ref','input_version','revision','brief_sha256','parent_plan_manifest_sha256','parent_plan_sha256','plan_request_sha256'];
function v94fSame(a,b){return JSON.stringify(v94fBindingFields.map(k=>a?.[k]))===JSON.stringify(v94fBindingFields.map(k=>b?.[k]));}
function v94fCanonical(value){return JSON.stringify(value,(_,v)=>v&&typeof v==='object'&&!Array.isArray(v)?Object.fromEntries(Object.keys(v).sort().map(k=>[k,v[k]])):v);}
function v94fContext(app){
 const basis=v93Identity(),view=v93.view,feedback=view?.feedback,binding=feedback?.binding;
 if(app&&(app.page!=='workspace'||app.stage!==3))return null;
 if(!basis||!v93Matches(basis,v93.basis)||!v93Matches(basis,view)||!v93Matches(basis,binding)||
  feedback?.kind!=='ProjectStage3PlanningFeedbackView'||feedback.schema_version!==1||!Array.isArray(feedback.records)||feedback.records.length>32||
  !['brief_sha256','parent_plan_manifest_sha256','parent_plan_sha256','plan_request_sha256'].every(k=>typeof binding[k]==='string'&&/^[a-f0-9]{64}$/.test(binding[k]))||
  binding.parent_plan_manifest_sha256!==view.job?.plan_manifest_sha256||binding.plan_request_sha256!==view.job?.request_sha256||!view.plan)return null;
 return {basis,view,binding,id:JSON.stringify(v94fBindingFields.map(k=>binding[k]))};
}
function v94fRow(row,binding){
 const record=row?.record;
 return typeof row?.receipt_sha256==='string'&&/^[a-f0-9]{64}$/.test(row.receipt_sha256)&&v94fSame(record?.binding,binding)&&
  ['comment','revision'].includes(record?.kind)&&typeof record.request?.key==='string'&&record.request.key.length>0&&
  (record.kind==='comment'?typeof record.text==='string':Number.isSafeInteger(record.revision_number)&&record.revision_number>=2&&record.plan&&Array.isArray(record.changes));
}
function v94fState(context){
 let state=v94fStates.get(context.id);
 if(!state){
  if(v94fStates.size>=8){const old=[...v94fStates].find(([,value])=>!value.pending&&!value.busy);if(!old)return null;v94fStates.delete(old[0]);}
  state={editorOpen:false,commentText:'',commentQuestion:'',selected:'',revisionQuestion:'',revisionComment:'',field:'method',value:'',records:[],pending:null,busy:false,status:'',error:'',focus:null};
  v94fStates.set(context.id,state);
 }
 for(const row of context.view.feedback.records){if(v94fRow(row,context.binding)&&!state.records.some(old=>old.receipt_sha256===row.receipt_sha256))state.records.push(row);}
 if(state.records.length>32)state.records=state.records.slice(-32);
 if(state.pending){const found=state.records.find(row=>row.record.kind===(state.pending.action==='comment'?'comment':'revision')&&v94fCanonical(row.record.request)===v94fCanonical(state.pending.body));if(found)v94fAccepted(state,found,true);}
 return state;
}
function v94fAccepted(state,row,replayed){
 if(!state.records.some(old=>old.receipt_sha256===row.receipt_sha256))state.records.push(row);
 if(row.record.kind==='revision')state.selected='revision:'+row.record.request.key;
 else {state.commentText='';state.revisionQuestion=row.record.question_ref||state.revisionQuestion;state.revisionComment=row.record.request.key;}
 state.pending=null;state.status=replayed?'recovered':'saved';state.error='';
}
function v94fCurrent(context,epoch,app){const now=v94fContext(app);return epoch===rt.epoch&&now?.id===context.id&&apps.includes(app);}
function v94fRevision(state){return state.records.find(row=>row.record.kind==='revision'&&'revision:'+row.record.request.key===state.selected)||null;}
function v94fTitle(context,ref){return context.view.direction_context?.questions?.find(q=>q.question_ref===ref)?.text||context.view.plan.questions?.find(q=>q.question_ref===ref)?.text||ref;}
function v94fLabel(field){return ({method:rl('方法','Method','方法'),materials:rl('资料与参考','Data and references','資料與參考'),design:rl('实验设计','Study design','實驗設計'),analysis:rl('分析','Analysis','分析'),interpretation:rl('结果判读','Interpretation','結果判讀'),validation:rl('验证','Validation','驗證'),minimum_deliverable:rl('最小交付','Minimum deliverable','最小交付')})[field];}
function v94fOptions(rows,value){return rows.map(([key,label])=>`<option value="${rx(key)}"${key===value?' selected':''}>${rx(label)}</option>`).join('');}
function v94fReference(row){return {key:row.record.request.key,sha256:row.receipt_sha256};}
function v94fDetails(row){
 const record=row.record;
 return `<details class="n9f-details"><summary>${rl('版本、父版本与收据','Version, parent and receipt','版本、父版本與收據')}</summary><dl><dt>${rl('收据','Receipt','收據')}</dt><dd>${rx(row.receipt_sha256)}</dd><dt>${rl('操作编号','Operation key','操作編號')}</dt><dd>${rx(record.request.key)}</dd><dt>${rl('父草案收据','Parent draft receipt','父草案收據')}</dt><dd>${rx(record.parent_revision?.sha256||rl('原规划 v1','Original plan v1','原規劃 v1'))}</dd><dt>${rl('原规划版本摘要','Original plan manifest','原規劃版本摘要')}</dt><dd>${rx(record.binding.parent_plan_manifest_sha256)}</dd></dl></details>`;
}
function v94fManual(context,row){
 if(!row)return '';
 const plan=row.record.plan;
 const questions=(plan.question_plans||[]).map(question=>`<article><h3>${rx(v94fTitle(context,question.question_ref))}</h3>${v94fFields.filter(field=>typeof question[field]==='string').map(field=>`<h4>${v94fLabel(field)}</h4><p class="n9f-text">${rx(question[field])}</p>`).join('')}${Array.isArray(question.unknowns)&&question.unknowns.length?`<h4>${rl('保留的待查事项','Retained open checks','保留的待查事項')}</h4><ul>${question.unknowns.map(value=>`<li>${rx(typeof value==='string'?value:JSON.stringify(value))}</li>`).join('')}</ul>`:''}</article>`).join('');
 return `<section class="n9f-manual" data-v94f-manual><h2>${rl('人工规划草案','Manual planning draft','人工規劃草案')} v${row.record.revision_number}</h2><p>${rl('以下结构化内容由用户修改；尚未经科学审查，也未执行研究。原始评语、限制与待查事项继续保留。','These structured fields were edited by the user. Scientific review and research execution have not occurred. Original comments, limitations and open checks remain retained.','以下結構化內容由使用者修改；尚未經科學審查，也未執行研究。原始評語、限制與待查事項繼續保留。')}</p>${questions}${v94fDetails(row)}<details class="n9f-details"><summary>${rl('原始 Markdown（未改写）','Original Markdown (unchanged)','原始 Markdown（未改寫）')}</summary><pre>${rx(typeof plan.markdown==='string'?plan.markdown:rl('未记录','Not recorded','未記錄'))}</pre></details></section>`;
}
function v94fHtml(context,state){
 const revision=v94fRevision(state),plan=revision?.record.plan||context.view.plan,questions=Array.isArray(plan.question_plans)?plan.question_plans:[];
 const editable=questions.filter(q=>v94fFields.some(field=>typeof q[field]==='string'));
 if(!editable.some(q=>q.question_ref===state.revisionQuestion))state.revisionQuestion=editable.find(q=>state.records.some(row=>row.record.kind==='comment'&&(row.record.question_ref===null||row.record.question_ref===q.question_ref)))?.question_ref||editable[0]?.question_ref||'';
 const question=editable.find(q=>q.question_ref===state.revisionQuestion),fields=v94fFields.filter(field=>typeof question?.[field]==='string');
 if(!fields.includes(state.field))state.field=fields[0]||'';
 const comments=state.records.filter(row=>row.record.kind==='comment'),eligible=comments.filter(row=>row.record.question_ref===null||row.record.question_ref===state.revisionQuestion);
 if(!eligible.some(row=>row.record.request.key===state.revisionComment))state.revisionComment=eligible[0]?.record.request.key||'';
 const locked=state.busy||!!state.pending,disabled=locked?' disabled':'',versions=[['',rl('原规划 v1','Original plan v1','原規劃 v1')],...state.records.filter(row=>row.record.kind==='revision').map(row=>['revision:'+row.record.request.key,rl('人工草案','Manual draft','人工草案')+' v'+row.record.revision_number+' · '+row.receipt_sha256.slice(0,8)])];
 const commentList=comments.map(row=>`<li><p class="n9f-context">${rx(row.record.question_ref===null?rl('整份规划','Whole plan','整份規劃'):v94fTitle(context,row.record.question_ref))}</p><p class="n9f-text">${rx(row.record.text)}</p>${v94fDetails(row)}</li>`).join('');
 const questionPicker=editable.length?`<label class="n9f-control">${rl('研究问题','Research question','研究問題')}<select data-v94f-control="revisionQuestion"${disabled}>${v94fOptions(editable.map(q=>[q.question_ref,v94fTitle(context,q.question_ref)]),state.revisionQuestion)}</select></label>`:'';
 const message=state.status==='recovered'?rl('已找到同一操作的保存收据，没有新增操作。','The saved receipt for this operation was recovered; no new operation was created.','已找到同一操作的保存收據，沒有新增操作。'):state.status==='saved'?rl('已保存，收据与历史已保留。','Saved with its receipt and history.','已保存，收據與歷史已保留。'):state.status==='absent'?rl('当前读取未找到收据。可明确重送同一请求；不会自动重送。','This read did not find a receipt. You may explicitly retry the same request; it will not be resent automatically.','目前讀取未找到收據。可明確重送同一請求；不會自動重送。'):'';
 return `<section class="hs-panel n9f-panel" data-v94f-panel tabindex="-1" aria-label="${rl('评语与人工草案','Comments and manual drafts','評語與人工草案')}"><h2>${rl('评语与人工草案','Comments and manual drafts','評語與人工草案')}</h2><p>${rl('保存评语后，可据此修改一个规划字段。人工草案保留原规划，不会重新调用模型，也不表示研究获准执行。','Save a comment, then use it to edit one planning field. Manual drafts retain the original plan and do not call a model or authorize research execution.','保存評語後，可據此修改一個規劃欄位。人工草案保留原規劃，不會重新呼叫模型，也不表示研究獲准執行。')}</p><label class="n9f-control">${rl('查看版本','View version','檢視版本')}<select data-v94f-control="selected"${disabled}>${v94fOptions(versions,state.selected)}</select></label>${v94fManual(context,revision)}<p role="status" aria-live="polite">${rx(state.busy?rl('正在保存或核对收据…','Saving or checking the receipt…','正在保存或核對收據…'):message)}</p>${state.error?`<p role="alert">${rx(state.error)}</p>`:''}${state.pending?`<div class="n9f-recovery"><p>${state.pending.refused?rl('服务器已在写入前拒绝此请求。原文仍保留；您可以先修改，再明确提交新请求。','The server rejected this request before saving. Your text is retained; edit it before explicitly submitting a new request.','伺服器已在寫入前拒絕此請求。原文仍保留；您可以先修改，再明確提交新請求。'):rl('此操作的结果尚未确认。请先核对收据，或明确重送相同编号与内容。','This operation has an unconfirmed outcome. Check its receipt, or explicitly resend the same key and content.','此操作的結果尚未確認。請先核對收據，或明確重送相同編號與內容。')}</p>${state.pending.refused?`<button type="button" class="hs-button" data-v94f-edit-refused${state.busy?' disabled':''}>${rl('修改被拒绝的请求','Edit refused request','修改被拒絕的請求')}</button>`:`<button type="button" class="hs-button" data-v94f-inspect${state.busy?' disabled':''}>${rl('核对已保存收据','Check saved receipt','核對已保存收據')}</button><button type="button" class="hs-button" data-v94f-retry${state.busy?' disabled':''}>${rl('重送同一请求','Retry same request','重送同一請求')}</button>`}</div>`:''}<section><h3>${rl('已保存评语','Saved comments','已保存評語')}</h3>${comments.length?`<ol class="n9f-comments">${commentList}</ol>`:`<p>${rl('尚无本版本的评语。','No comments for this saved version yet.','尚無本版本的評語。')}</p>`}</section><form data-v94f-form="comment"><fieldset${disabled}><legend>${rl('添加评语','Add a comment','新增評語')}</legend><label class="n9f-control">${rl('评语范围','Comment scope','評語範圍')}<select data-v94f-control="commentQuestion">${v94fOptions([['',rl('整份规划','Whole plan','整份規劃')],...questions.map(q=>[q.question_ref,v94fTitle(context,q.question_ref)])],state.commentQuestion)}</select></label><label class="n9f-control">${rl('评语内容','Comment','評語內容')}<textarea data-v94f-control="commentText" rows="3" required>${rx(state.commentText)}</textarea></label><button class="hs-button" type="submit">${rl('保存评语','Save comment','保存評語')}</button></fieldset></form><details class="n9f-details" data-v94f-editor${state.editorOpen?' open':''}><summary>${rl('根据评语保存人工草案','Save a manual draft from a comment','根據評語保存人工草案')}</summary>${questionPicker}${editable.length&&eligible.length?`<form data-v94f-form="revise"><fieldset${disabled}><legend>${rl('修改一个字段','Edit one field','修改一個欄位')}</legend><label class="n9f-control">${rl('依据评语','Supporting comment','依據評語')}<select data-v94f-control="revisionComment">${v94fOptions(eligible.map(row=>[row.record.request.key,row.record.text]),state.revisionComment)}</select></label><label class="n9f-control">${rl('规划字段','Planning field','規劃欄位')}<select data-v94f-control="field">${v94fOptions(fields.map(field=>[field,v94fLabel(field)]),state.field)}</select></label><p class="n9f-text">${rl('当前内容：','Current text:','目前內容：')} ${rx(question?.[state.field]||'')}</p><label class="n9f-control">${rl('新的字段内容','New field text','新的欄位內容')}<textarea data-v94f-control="value" rows="4" required>${rx(state.value)}</textarea></label><button class="hs-button" type="submit">${rl('保存人工规划草案','Save manual planning draft','保存人工規劃草案')}</button></fieldset></form>`:`<p>${rl('请先为可修改的问题保存一条评语。只有原本为文本的规划字段可以修改。','First save a comment for an editable question. Only planning fields that already contain text can be edited.','請先為可修改的問題保存一條評語。只有原本為文字的規劃欄位可以修改。')}</p>`}</details></section>`;
}
function v94fBody(context,state,action){
 const binding=Object.fromEntries(v94fBindingFields.filter(k=>k!=='project_ref').map(k=>[k,context.binding[k]]));
 if(typeof crypto==='undefined'||typeof crypto.randomUUID!=='function')throw Error(rl('无法建立操作编号；请重新载入。','An operation key could not be created; reload the page.','無法建立操作編號；請重新載入。'));
 const body={key:'feedback-'+crypto.randomUUID(),...binding};
 if(action==='comment')return {...body,text:state.commentText,question_ref:state.commentQuestion||null};
 const row=state.records.find(row=>row.record.kind==='comment'&&row.record.request.key===state.revisionComment),parent=v94fRevision(state);
 if(!row)throw Error(rl('请先选择已保存的评语。','Select a saved comment first.','請先選擇已保存的評語。'));
 return {...body,comments:[v94fReference(row)],parent_revision:parent?v94fReference(parent):null,changes:[{question_ref:state.revisionQuestion,field:state.field,value:state.value}]};
}
function v94fEditRefused(app){
 const context=v94fContext(app),state=context&&v94fState(context);
 if(!state||state.busy||!state.pending?.refused)return;
 const operation=state.pending;
 state.lastRefused={action:operation.action,body:JSON.parse(JSON.stringify(operation.body)),error:state.error};
 state.pending=null;state.status='';state.error='';
 state.focus={control:operation.action==='comment'?'commentText':'value'};livePaint();
}
async function v94fSend(app,retry=false){
 const context=v94fContext(app),state=context&&v94fState(context);if(!state||state.busy||!state.pending)return;
 const operation=state.pending,epoch=rt.epoch;state.busy=true;operation.refused=false;state.error='';state.status='';livePaint();
 try{
  const row=await liveRequest(projectPath(context.binding.project_ref,'stage3/planning/'+operation.action),JSON.parse(JSON.stringify(operation.body)));
  if(!v94fRow(row,context.binding)||row.record.kind!==(operation.action==='comment'?'comment':'revision')||v94fCanonical(row.record.request)!==v94fCanonical(operation.body))throw Error('stage3-feedback-receipt-differs');
  v94fAccepted(state,row,retry||row.replayed===true);
 }catch(error){state.error=String(error?.message||error);operation.refused=error?.receipt===undefined&&((error?.status===413&&['stage3-feedback-response-bound','stage3-feedback-plan-bound'].includes(state.error))||(error?.status===409&&state.error==='stage3-feedback-record-bound'));}
 finally{state.busy=false;if(v94fCurrent(context,epoch,app))livePaint();}
}
async function v94fSubmit(app,action){
 const context=v94fContext(app),state=context&&v94fState(context);if(!state||state.busy||state.pending)return;
 try{
  const text=action==='comment'?state.commentText:state.value;
  if(!text.trim())throw Error(rl('请填写内容。','Enter text before saving.','請填寫內容。'));
  if(new TextEncoder().encode(text).length>1800)throw Error(rl('内容超过 1800 UTF-8 字节，请缩短。','Text exceeds 1800 UTF-8 bytes; shorten it before saving.','內容超過 1800 UTF-8 位元組，請縮短。'));
  const body=v94fBody(context,state,action);
  if(new TextEncoder().encode(JSON.stringify(body)).length>4096)throw Error(rl('请求超过 4096 UTF-8 字节，请缩短内容。','Request exceeds 4096 UTF-8 bytes; shorten the text before saving.','請求超過 4096 UTF-8 位元組，請縮短內容。'));
  state.pending={action,body};await v94fSend(app);
 }catch(error){state.error=String(error?.message||error);livePaint();}
}
async function v94fInspect(app){
 const context=v94fContext(app),state=context&&v94fState(context);if(!state||state.busy||!state.pending)return;
 const epoch=rt.epoch;state.busy=true;state.error='';livePaint();
 try{
  const view=await liveRequest(projectPath(context.binding.project_ref,'stage3/planning'));
  if(!v94fCurrent(context,epoch,app))return;
  if(!v93Matches(context.basis,view)||!v94fSame(context.binding,view.feedback?.binding))throw Error('stage3-feedback-version-differs');
  v93.view=view;v94fState({...context,view});if(state.pending)state.status='absent';
 }catch(error){state.error=String(error?.message||error);}
 finally{state.busy=false;if(v94fCurrent(context,epoch,app))livePaint();}
}
const v94fOriginalSummary=v93SavedPlanSummary;
v93SavedPlanSummary=function(view){const original=v94fOriginalSummary(view),context=v94fContext(),state=context&&v94fState(context);return original&&state&&v94fRevision(state)?`<details class="n9f-original"><summary>${rl('原规划 v1（未改写，含原始待查事项）','Original plan v1 (unchanged, with original open checks)','原規劃 v1（未改寫，含原始待查事項）')}</summary>${original}</details>`:original;};
const v94fLater=laterStage;
laterStage=function(app){
 const html=v94fLater(app),context=v94fContext(app),state=context&&v94fState(context);if(!state)return html;
 const actions='<div class="n9-page-actions">',withActions=html.replace(actions,actions+'<button type="button" class="hs-button" data-v94f-focus>'+rl('评语与修订','Comment or revise','評語與修訂')+'</button>');
 const panel=v94fHtml(context,state),marker='<details class="n9-plan-graph"';
 return withActions.includes(marker)?withActions.replace(marker,panel+'<p class="n9f-original-note">'+rl('下方关系图来自未改写的原规划。','The research map below shows the unchanged original plan.','下方關係圖來自未改寫的原規劃。')+'</p>'+marker):withActions+panel;
};
const v94fBefore=v7BeforeRender,v94fAfter=v7AfterRender;
v7BeforeRender=function(app){
 const context=v94fContext(app),state=context&&v94fState(context),active=document.activeElement;
 const editor=app.el.querySelector('[data-v94f-editor]');if(state&&typeof editor?.open==='boolean')state.editorOpen=editor.open;
 if(state&&app.el.contains(active)&&active?.dataset?.v94fControl)state.focus={control:active.dataset.v94fControl,start:active.selectionStart,end:active.selectionEnd};
 v94fBefore(app);
};
v7AfterRender=function(app){
 v94fAfter(app);const context=v94fContext(app),state=context&&v94fState(context);
 if(state?.focus&&(!document.activeElement||document.activeElement===document.body)){
  const target=app.el.querySelector('[data-v94f-control="'+state.focus.control+'"]');target?.focus();
  if(target&&typeof target.setSelectionRange==='function'&&Number.isInteger(state.focus.start))target.setSelectionRange(state.focus.start,state.focus.end);
 }if(state)state.focus=null;
};
for(const type of ['input','change'])document.addEventListener(type,event=>{
 const control=event.target.closest('[data-v94f-control]'),app=control&&apps.find(app=>app.el.contains(control)),context=app&&v94fContext(app),state=context&&v94fState(context),field=control?.dataset.v94fControl;
 if(!state||state.busy||state.pending||!['commentText','commentQuestion','selected','revisionQuestion','revisionComment','field','value'].includes(field))return;
 state[field]=control.value;state.error='';if(type==='change'&&!['commentText','value'].includes(field))livePaint();
});
document.addEventListener('submit',event=>{
 const form=event.target.closest('[data-v94f-form]'),app=form&&apps.find(app=>app.el.contains(form));if(!app||!v94fContext(app))return;
 event.preventDefault();const action=form.dataset.v94fForm;if(['comment','revise'].includes(action))v94fSubmit(app,action);
});
document.addEventListener('click',event=>{
 const control=event.target.closest('[data-v94f-retry],[data-v94f-inspect],[data-v94f-edit-refused],[data-v94f-focus]'),app=control&&apps.find(app=>app.el.contains(control));if(!app||!v94fContext(app))return;
 if(control.hasAttribute('data-v94f-focus')){const panel=app.el.querySelector('[data-v94f-panel]');panel?.scrollIntoView({block:'start'});panel?.focus({preventScroll:true});return;}
 if(control.hasAttribute('data-v94f-inspect'))v94fInspect(app);else if(control.hasAttribute('data-v94f-edit-refused'))v94fEditRefused(app);else v94fSend(app,true);
});

document.addEventListener('toggle',event=>{
 const editor=event.target.matches?.('[data-v94f-editor]')?event.target:null,app=editor&&apps.find(app=>app.el.contains(editor)),context=app&&v94fContext(app),state=context&&v94fState(context);
 if(state&&typeof editor.open==='boolean')state.editorOpen=editor.open;
},true);
