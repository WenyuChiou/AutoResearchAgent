// Stage1 citation offers only. The shared livePost/history broker owns durable intents.
const realExpansionCap=32,realExpansionVerified=new Map(),realExpansionSubmitted=new Set();
const realExpansionHash=v=>typeof v==='string'&&/^[a-f0-9]{64}$/.test(v);
const realExpansionText=(v,n)=>typeof v==='string'&&v.length>0&&v.length<=n;
const realExpansionInt=(v,min=0)=>Number.isSafeInteger(v)&&v>=min;
const realExpansionKeys=(v,keys)=>v&&typeof v==='object'&&!Array.isArray(v)&&Object.keys(v).sort().join(',')===keys.split(',').sort().join(',');
function realExpansionCanonical(value){
 const compare=(a,b)=>{const x=Array.from(a,c=>c.codePointAt(0)),y=Array.from(b,c=>c.codePointAt(0));for(let i=0;i<Math.min(x.length,y.length);i++)if(x[i]!==y[i])return x[i]-y[i];return x.length-y.length;};
 return Array.isArray(value)?'['+value.map(realExpansionCanonical).join(',')+']':value&&typeof value==='object'?'{'+Object.keys(value).sort(compare).map(k=>JSON.stringify(k)+':'+realExpansionCanonical(value[k])).join(',')+'}':JSON.stringify(value);
}
async function realExpansionDigest(document){
 return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(realExpansionCanonical(document)))),b=>b.toString(16).padStart(2,'0')).join('');
}
function realExpansionContext(){
 const p=rt.overview?.project,s=rt.overview?.stage1,b=s?.progress?.binding,x=s?.expansion_execution,c=s?.coverage_actions;
 if(!liveReal()||apps[0]?.stage!==1||!p||p.project_ref!==rt.ref||p.status==='execution-unknown'||
  !realExpansionInt(p.revision)||!realExpansionInt(p.input_version,1)||!realExpansionHash(p.brief_sha256)||
  s?.project_ref!==rt.ref||s.revision!==p.revision||s.input_version!==p.input_version||
  b?.project_ref!==rt.ref||b.revision!==p.revision||b.input_version!==p.input_version||b.brief_sha256!==p.brief_sha256||
  s.ledger?.valid!==true||!realExpansionHash(s.ledger.state_sha256)||c?.ledger_state_sha256!==s.ledger.state_sha256||
  !realExpansionInt(c.active_round,1)||x?.connected!==true||x.automatic_retry!==false||x.stage1_complete!==false||x.refusal)return null;
 return {ref:rt.ref,epoch:rt.epoch,revision:p.revision,input_version:p.input_version,brief_sha256:p.brief_sha256,
  ledger_state_sha256:s.ledger.state_sha256,round_number:c.active_round};
}
function realExpansionOffer(action,index){
 const context=realExpansionContext(),s=rt.overview?.stage1,q=s?.query_execution;
 if(!context||!['authorize','execute'].includes(action)||!realExpansionInt(index)||index>=realExpansionCap)return null;
 const field=action==='authorize'?'authorization_offers':'execution_offers',rows=s.expansion_execution[field];
 if(!Array.isArray(rows))return null;const o=rows[index],d=o?.document;
 const common='project_ref,principal,input_version,brief_sha256,round_number,work_id,version_id,title,operation,arguments,backend,remaining_attempts,reserved_seconds';
 const extra=action==='authorize'?'identifier,original_permit_sha256,registration_sha256,ledger_tree_sha256,ledger_state_sha256,review_sha256,validity_seconds,max_attempts,model_execution,source_acquisition,automatic_retry':'index_sha256,plan_sha256,runtime_sha256,execution_source_sha256,permit_sha256,planned_id,query_id,expansion_grant_sha256,expansion_expires_at_unix,timeout_seconds,probe_timeout_seconds,max_results,budget,execution_authority';
 if(!realExpansionKeys(o,action==='authorize'?'offer_ref,offer_sha256,document':'offer_ref,offer_sha256,revision,document')||
  !realExpansionKeys(d,common+','+extra)||!realExpansionHash(o.offer_sha256)||d.project_ref!==context.ref||
  d.brief_sha256!==context.brief_sha256||d.round_number!==context.round_number||!realExpansionText(d.principal,256)||
  !realExpansionText(d.work_id,256)||!realExpansionText(d.version_id,256)||!realExpansionText(d.title,4096)||
  !['references','cited-by'].includes(d.operation)||d.backend!=='semantic-scholar'||
  !realExpansionInt(d.remaining_attempts,1)||!Number.isFinite(d.reserved_seconds)||d.reserved_seconds<=0||d.reserved_seconds>1e7)return null;
 const a=d.arguments,c=a?.coverage;
 if(!realExpansionKeys(a,'operation,limit,coverage')||a.operation!==d.operation||!realExpansionInt(a.limit,1)||a.limit>100||
  !realExpansionKeys(c,'plan_event_id,round_number,seed_work_id,seed_version_id')||!realExpansionText(c.plan_event_id,256)||
  c.round_number!==d.round_number||c.seed_work_id!==d.work_id||c.seed_version_id!==d.version_id)return null;
 if(action==='authorize'){
  if(!realExpansionText(d.identifier,2048)||o.offer_ref!=='project-expansion-'+o.offer_sha256.slice(0,32)||d.input_version!==context.input_version||
   d.ledger_state_sha256!==context.ledger_state_sha256||d.original_permit_sha256!==q?.permit_sha256||
   !['original_permit_sha256','registration_sha256','ledger_tree_sha256','ledger_state_sha256','review_sha256'].every(k=>realExpansionHash(d[k]))||
   !realExpansionInt(d.validity_seconds,1)||d.max_attempts!==1||d.model_execution!==false||d.source_acquisition!==false||d.automatic_retry!==false)return null;
 }else{
  const h=q?.query_history;
  if(o.offer_ref!==o.offer_sha256||!realExpansionInt(o.revision)||h?.project_ref!==context.ref||h.input_version!==context.brief_sha256||
   h.revision!==o.revision||h.index_sha256!==d.index_sha256||d.input_version!==context.brief_sha256||
   !['index_sha256','plan_sha256','runtime_sha256','execution_source_sha256','permit_sha256','expansion_grant_sha256'].every(k=>realExpansionHash(d[k]))||
   d.planned_id!==null||d.query_id!==null||d.execution_authority!=='exact-expansion-grant'||
   !realExpansionInt(d.expansion_expires_at_unix,1)||Date.now()/1000+d.reserved_seconds>=d.expansion_expires_at_unix||
   !realExpansionInt(d.timeout_seconds,1)||!realExpansionInt(d.probe_timeout_seconds,1)||d.timeout_seconds+d.probe_timeout_seconds!==d.reserved_seconds||
   !realExpansionInt(d.max_results,1)||d.max_results>100||!realExpansionKeys(d.budget,'attempts,seconds')||
   !Object.values(d.budget).every(v=>Number.isFinite(v)&&v>=0)||!realExpansionInt(d.budget.attempts))return null;
 }
 const raw=realExpansionCanonical(o);if(new TextEncoder().encode(raw).length>32768)return null;
 return {context,offer:JSON.parse(raw),action,index,basis:realExpansionCanonical({context,offer:o,action,index}),token:JSON.stringify([context.ref,context.input_version,context.brief_sha256,action,o.offer_ref,o.offer_sha256])};
}
function realExpansionHeld(row){
 return realExpansionSubmitted.has(row.token);
}
async function realExpansionVerify(){
 const work=[];
 for(const action of ['authorize','execute'])for(let index=0;index<realExpansionCap;index++){
  const row=realExpansionOffer(action,index);if(!row||realExpansionVerified.has(row.basis))continue;
  const record={valid:false,pending:true};realExpansionVerified.set(row.basis,record);
  work.push((async()=>{try{const digest=await realExpansionDigest(row.offer.document),current=realExpansionOffer(action,index);record.valid=!!current&&current.basis===row.basis&&digest===row.offer.offer_sha256;}catch(_){record.valid=false;}finally{record.pending=false;}})());
 }
 await Promise.all(work);
 // Hash observations are disposable presentation state, never authority or action history.
 while(realExpansionVerified.size>128)realExpansionVerified.delete(realExpansionVerified.keys().next().value);
 return work.length>0;
}
function realExpansionReady(action,index){const row=realExpansionOffer(action,index);return row&&realExpansionVerified.get(row.basis)?.valid===true&&!realExpansionHeld(row)?row:null;}
function realExpansionPanel(app){
 if(app.stage!==1||!liveReal())return '';
 const s=rt.overview?.stage1,x=s?.expansion_execution,q=s?.query_execution,context=realExpansionContext();
 const round=s?.coverage_actions?.active_round,budget=q?.budget,limits=q?.limits;
 const remaining=realExpansionInt(limits?.max_attempts)&&realExpansionInt(budget?.attempts)&&limits.max_attempts>=budget.attempts?limits.max_attempts-budget.attempts:null;
 const seconds=Number.isFinite(limits?.max_reserved_seconds)&&Number.isFinite(budget?.seconds)&&limits.max_reserved_seconds>=budget.seconds?limits.max_reserved_seconds-budget.seconds:null;
 const disabled=rt.busy||rt.loading||rt.pending||rt.controlHeld||rt.expansionBusy?'disabled':'';
 let body=`<p>${rl('每项许可只允许一次指定论文、版本、轮次与后端的引文追踪，共用已有查询和项目预算。先保存授权，再单独执行。','Each permission permits one exact paper, version, round and backend attempt within existing query and project budgets. Save permission first, then execute separately.','每項許可只允許一次指定論文、版本、輪次與後端的引文追蹤，共用既有查詢與專案預算。先儲存授權，再單獨執行。')}</p><p>${rl('当前轮次','Current round','目前輪次')}: ${rx(realExpansionInt(round,1)?round:null)} · ${rl('共用查询预算剩余尝试','Remaining shared query attempts','共用查詢預算剩餘嘗試')}: ${rx(remaining)} · ${rl('剩余预留秒数','Remaining reserved seconds','剩餘預留秒數')}: ${rx(seconds)}</p>`;
 if(x?.refusal)body+=`<p>${rl('服务原始拒绝','Original service refusal','服務原始拒絕')}: <code>${rx(String(x.refusal).slice(0,4096))}</code></p>`;
 if(!context)body+=`<p>${rl('当前绑定或许可不可核验，仅显示已保存状态。','Current binding or permission cannot be verified; saved status is shown for review.','目前綁定或許可無法核驗，僅顯示已儲存狀態。')}</p>`;
 let count=0;
 for(const action of ['authorize','execute']){
  const rows=x?.[action==='authorize'?'authorization_offers':'execution_offers'];if(!Array.isArray(rows))continue;
  for(let index=0;index<Math.min(rows.length,realExpansionCap);index++){
   const row=realExpansionOffer(action,index);if(!row)continue;count++;
   const d=row.offer.document,verified=realExpansionVerified.get(row.basis),ready=realExpansionReady(action,index);
   body+=`<div class="live-detail-block"><h4>${rx(d.title)}</h4><p>${rl(d.operation==='references'?'参考文献':'引用该论文的研究',d.operation==='references'?'References':'Citing papers',d.operation==='references'?'參考文獻':'引用該論文的研究')} · ${rx(d.work_id)} · ${rx(d.version_id)}</p><p>${rl('轮次','Round','輪次')} ${rx(d.round_number)} · semantic-scholar · ${rx(d.reserved_seconds)} ${rl('预留秒数','reserved seconds','預留秒數')} · ${rl('剩余尝试','remaining attempts','剩餘嘗試')} ${rx(d.remaining_attempts)}</p><details><summary>${rl('完整服务许可与摘要','Complete server offer & digest','完整服務許可與摘要')}</summary><pre class="live-record">${rx(JSON.stringify(row.offer,null,2))}</pre></details>`;
   if(action==='authorize')body+=`<label>${rl('本次授权理由','Reason for this permission','本次授權理由')}<textarea data-v7-expansion-note rows="2" maxlength="4096" ${disabled}></textarea></label>`;
   body+=`<label><input type="checkbox" data-v7-expansion-confirm ${disabled}> ${action==='authorize'?rl('明确授权这一次精确绑定的引文追踪，使用已有预算','Authorize this exact citation attempt using existing budget','明確授權這一次精確綁定的引文追蹤，使用既有預算'):rl('确认单独执行这项已保存许可，使用已有预算','Execute this saved permission separately using existing budget','確認單獨執行這項已儲存許可，使用既有預算')}</label><button type="button" class="hs-button" data-v7-expansion="${action}" data-v7-expansion-index="${index}" data-v7-expansion-basis="${rx(row.basis)}" ${ready?disabled:'disabled'}>${action==='authorize'?rl('保存这次引用扩展授权','Save this citation permission','儲存這次引文擴展授權'):rl('执行已保存的引用扩展许可','Execute saved citation permission','執行已儲存的引文擴展許可')}</button><p role="status">${realExpansionHeld(row)?rl('此许可已提交；请查阅保存历史，不会自动重发。','This offer was submitted. Check saved history; it will not be resent automatically.','此許可已提交；請查閱儲存歷史，不會自動重發。'):verified?.pending?rl('正在核验完整许可摘要','Verifying complete offer digest','正在核驗完整許可摘要'):verified&&!verified.valid?rl('许可摘要不符，禁止操作','Offer digest differs; action blocked','許可摘要不符，禁止操作'):''}</p></div>`;
  }
  if(rows.length>realExpansionCap)body+=`<p>${rl('每类最多显示32项，完整记录保留在服务历史中。','At most 32 offers per type are shown; full records remain in service history.','每類最多顯示32項，完整記錄保留於服務歷史中。')}</p>`;
 }
 if(!count)body+=`<p>${rl('当前没有完整且绑定一致的引用扩展许可。','No complete citation offer matches the current binding.','目前沒有完整且綁定一致的引文擴展許可。')}</p>`;
 for(const row of (Array.isArray(x?.unavailable)?x.unavailable:[]).slice(0,realExpansionCap))body+=`<p><code>${rx(String(row?.work_id??'Unknown').slice(0,256))} · ${rx(String(row?.operation??'Unknown').slice(0,256))} · ${rx(String(row?.code??'Unknown').slice(0,4096))}</code></p>`;
 const history=(Array.isArray(x?.history)?x.history:[]).slice(0,realExpansionCap);
 if(history.length)body+=`<details><summary>${rl('已保存引文许可与原始拒绝','Saved citation permissions & original refusals','已儲存引文許可與原始拒絕')}</summary>${history.map(row=>`<p>${rx(String(row?.work_id??'Unknown').slice(0,256))} · ${rx(String(row?.version_id??'Unknown').slice(0,256))} · ${rx(String(row?.operation??'Unknown').slice(0,256))} · ${rx(String(row?.status??'Unknown').slice(0,256))}<br><code>${rx(String(row?.refusal??'').slice(0,4096))}</code></p>`).join('')}</details>`;
 if(rt.expansionError)body+=`<p role="alert">${rx(rt.expansionError)}</p>`;
 body+=`<p><small>${rl('引文追踪记录不代表来源已读、Stage1完成或科学验收通过。','Citation tracing does not establish source reading, Stage1 completion or scientific acceptance.','引文追蹤紀錄不代表來源已讀、Stage1完成或科學驗收通過。')}</small></p>`;
 return `<details class="real-workflow" data-v7-expansion-panel><summary>${rl('Stage1 引用扩展','Stage1 citation expansion','Stage1 引文擴展')}</summary>${body}</details>`;
}
const realExpansionSavedControls=liveControls;
liveControls=function(app){const html=realExpansionSavedControls(app);return app.stage===1&&liveReal()?html.replace('<div class="lp-ops-body">','<div class="lp-ops-body">'+realExpansionPanel(app)):html;};
const realExpansionSavedRender=render;
render=function(app){realExpansionSavedRender(app);if(app.stage===1&&liveReal()&&!rt.expansionVerifying){rt.expansionVerifying=true;realExpansionVerify().then(changed=>{rt.expansionVerifying=false;if(changed)livePaint();}).catch(()=>{rt.expansionVerifying=false;});}};
async function realExpansionClick(event){
 const button=event.target.closest?.('[data-v7-expansion]');
 if(!button||!liveReal()||!button.isConnected||!apps[0]?.el?.contains(button))return;
 event.preventDefault();event.stopImmediatePropagation();
 if(apps[0].stage!==1||button.disabled||rt.busy||rt.loading||rt.pending||rt.controlHeld||rt.expansionBusy||realExpansionSubmitted.size>=256)return;
 const action=button.dataset.v7Expansion,index=Number(button.dataset.v7ExpansionIndex),row=realExpansionReady(action,index),block=button.closest('.live-detail-block');
 const note=action==='authorize'?block?.querySelector('[data-v7-expansion-note]')?.value:undefined;
 if(!row||button.dataset.v7ExpansionBasis!==row.basis)return;
 if(block?.querySelector('[data-v7-expansion-confirm]')?.checked!==true||action==='authorize'&&(!realExpansionText(note,4096)||!note.trim()||new TextEncoder().encode(note).length>4096)){
  rt.expansionError=rl('请勾选确认；授权还需填写最多4096字节的理由。','Confirm this action. Permission requires a reason of at most 4096 bytes.','請勾選確認；授權還須填寫最多4096位元組的理由。');livePaint();return;
 }
 rt.expansionBusy=true;rt.expansionError=null;
 try{
  const digest=await realExpansionDigest(row.offer.document),current=realExpansionReady(action,index);
  if(!current||current.basis!==row.basis||digest!==row.offer.offer_sha256||!button.isConnected||!apps[0]?.el?.contains(button)||
   button.dataset.v7ExpansionBasis!==row.basis||button.disabled||rt.busy||rt.loading||rt.pending||rt.controlHeld||
   block.querySelector('[data-v7-expansion-confirm]')?.checked!==true||action==='authorize'&&block.querySelector('[data-v7-expansion-note]')?.value!==note)return;
  realExpansionSubmitted.add(row.token);
  await livePost('stage1/expansion-'+action,{...liveBound(),offer_ref:row.offer.offer_ref,offer_sha256:row.offer.offer_sha256,confirmed:true,...(action==='authorize'?{user_input:note}:{})},row.context.ref);
 }finally{rt.expansionBusy=false;livePaint();}
}
document.addEventListener('click',realExpansionClick,true);
