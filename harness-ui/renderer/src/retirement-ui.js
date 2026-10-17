// Stage1-only controls for the existing non-dispatching retirement protocol.
function realRetirementPendingMatches(target){
 const p=rt.pending;return !p||p.ref===target.ref&&p.path===projectPath(target.ref,'models/actions')&&p.body?.key===target.job_ref;
}
function realRetirementTargets(){
 if(apps[0]?.stage!==1||rt.controlIntent||rt.controlHeld)return [];
 const jobs=rt.overview?.models?.jobs;if(!Array.isArray(jobs))return [];
 return jobs.map(j=>liveRetirementTarget(j?.key)).filter(t=>t&&realRetirementPendingMatches(t));
}
function realRetirementPanel(app){
 if(app.stage!==1)return '';
 const record=rt.controlIntent,targets=realRetirementTargets(),archives=rt.controlArchives||[];
 if(!record&&!rt.controlHeld&&!targets.length&&!archives.length)return '';
 const disabled=rt.busy||rt.loading?'disabled':'',sameProject=record?.intent.ref===rt.ref;
 let body=`<p>${rl('只结束服务已确认从未派发的模型记录。原结果保持 Unknown，不重发、不退还预留额度，也不生成研究结果。','Close only a model record the service confirms was never dispatched. Preserve Unknown and reserved usage; do not resend or produce research results.','只結束服務已確認從未派發的模型記錄。原結果保持 Unknown，不重發、不退還預留額度，也不產生研究結果。')}</p>`;
 if(record){
  body+=`<p>${rl('控制记录所属项目','Control record project','控制記錄所屬專案')}: ${rx(record.intent.ref)}</p><p>${rl('原记录','Original record','原記錄')}: ${rx(record.intent.body.job_ref)}</p>`;
  if(!sameProject)body+=`<p>${rl('请切回该项目查询控制回执；当前项目不能覆盖这条记录。','Return to that project to check its control receipt. This project cannot replace that record.','請切回該專案查詢控制回執；當前專案不能覆蓋這條記錄。')}</p>`;
  else if(rt.controlHeld)body+=`<p role="status">${rl('控制回执尚需核对；这不改变原任务的 Unknown。','The control receipt needs verification; the original task remains Unknown.','控制回執尚需核對；這不改變原任務的 Unknown。')}</p><button type="button" class="hs-button" data-v7-control="recover" data-v7-control-ref="${rx(record.intent.ref)}" data-v7-control-key="${rx(record.intent.body.key)}" ${disabled}>${rl('查询已保存的控制回执','Check saved control receipt','查詢已保存的控制回執')}</button>`;
  else{body+=`<p role="status">${rl('控制回执已核对；仅表示控制结果已记录，原任务结果未改。','Control receipt verified. Only the control outcome was recorded; the original task outcome is unchanged.','控制回執已核對；僅表示控制結果已記錄，原任務結果未改。')} ${rx(record.receipt?.status)}</p>`;
   if(archives.length<16)body+=`<label><input type="checkbox" data-v7-archive-confirm ${disabled}> ${rl('确认核对并留档此控制回执，保留原请求和 Unknown','Confirm verification and archival of this control receipt, retaining the original request and Unknown','確認核對並留檔此控制回執，保留原請求與 Unknown')}</label><button type="button" class="hs-button" data-v7-control="archive" data-v7-archive-basis="${rx(liveControlArchiveBinding(record))}" ${disabled}>${rl('核对并留档此回执','Verify & archive this receipt','核對並留檔此回執')}</button><p><small>${rl('留档不清除原待确认请求；下一次控制仍需符合当前项目和服务限制。','Archival does not clear the original pending request. Another control must still meet current project and service limits.','留檔不清除原待確認請求；下一次控制仍須符合當前專案與服務限制。')}</small></p>`;
  }
 }else if(rt.controlJournalInvalid)body+=`<p role="status">${rl('已有控制记录无法识别，继续阻止提交并保留记录用于检查。','An existing control record could not be read. Submissions stay blocked and the record is retained for inspection.','已有控制記錄無法識別，繼續阻止提交並保留記錄供檢查。')}</p>`;
 if(archives.length)body+=`<details class="live-detail-block"><summary>${rl('本标签页已留档控制回执','Archived control receipts in this tab','本分頁已留檔控制回執')} · ${archives.length}</summary><ul>${archives.map(raw=>JSON.parse(raw)).filter(r=>r.intent.ref===rt.ref).map(r=>`<li>${rx(r.intent.body.key)} · ${rx(r.receipt.status)}</li>`).join('')}</ul><p>${rl('完整控制记录保留在本标签页，服务器原始回执不改写。','Full control records remain in this tab; original server receipts are unchanged.','完整控制記錄保留在本分頁，伺服器原始回執不改寫。')}</p></details>`;
 if(rt.controlArchiveVerified===false||rt.controlJournalInvalid)body+=`<p role="status">${rl('本地控制留档需要重新读取服务历史核验；不会重发操作。','Local control archives need verification against service history; no operation will be resent.','本地控制留檔需要重新讀取服務歷史核驗；不會重發操作。')}</p><button type="button" class="hs-button" data-v7-control="archive-recover" data-v7-control-ref="${rx(rt.ref)}" ${disabled}>${rl('核对本地控制留档','Verify local control archives','核對本地控制留檔')}</button>`;
 if(archives.length>=16)body+=`<p>${rl('本标签页已达 16 条留档上限，保留全部记录，不再开启新的控制。','This tab has reached its 16-record archive limit. All records are retained and new controls stay unavailable.','本分頁已達 16 條留檔上限，保留全部記錄，不再開啟新的控制。')}</p>`;
 body+=targets.map(t=>`<div class="live-detail-block"><p>${rl('未派发记录','Undispatched record','未派發記錄')}: ${rx(t.job_ref)}</p><label>${rl('结束这条记录的理由','Reason for closing this record','結束這條記錄的理由')}<textarea data-v7-retire-note rows="2" maxlength="4096" ${disabled}></textarea></label><label><input type="checkbox" data-v7-retire-confirm ${disabled}> ${rl('确认只结束这条未派发记录，保留 Unknown 和原预算','Confirm closing only this undispatched record, retaining Unknown and the original budget','確認只結束這條未派發記錄，保留 Unknown 與原預算')}</label><button type="button" class="hs-button" data-v7-control="retire" data-v7-job="${rx(t.job_ref)}" data-v7-control-basis="${rx(JSON.stringify(t))}" ${disabled}>${rl('结束此未派发记录','Close this undispatched record','結束此未派發記錄')}</button></div>`).join('');
 if(rt.controlError)body+=`<p role="alert">${rl('控制操作尚未完成；请核对记录。','Control operation is incomplete; check its record.','控制操作尚未完成；請核對記錄。')} <small>${rx(rt.controlError)}</small></p>`;
 return `<details class="real-workflow" data-v7-panel="model-retirement"><summary>${rl('未派发记录 · 结束与回执','Undispatched records · close & receipts','未派發記錄 · 結束與回執')}</summary>${body}</details>`;
}
async function realRetirementClick(event){
 const button=event.target.closest?.('[data-v7-control]');
 if(!button||!liveReal()||!button.isConnected||!apps[0].el.contains(button))return;
 event.preventDefault();event.stopImmediatePropagation();
 if(apps[0].stage!==1||rt.busy||rt.loading||button.disabled)return;
 if(button.dataset.v7Control==='archive-recover'){
  if(button.dataset.v7ControlRef!==rt.ref)return;await liveControlArchiveRecover();return;
 }
 if(button.dataset.v7Control==='archive'){
  if(rt.controlIntent?.intent.ref!==rt.ref||rt.controlHeld||button.dataset.v7ArchiveBasis!==liveControlArchiveBinding())return;
  if(button.closest('[data-v7-panel="model-retirement"]')?.querySelector('[data-v7-archive-confirm]')?.checked!==true){rt.controlError=rl('请确认本次核对与留档。','Confirm this verification and archival.','請確認本次核對與留檔。');livePaint();return;}
  await liveRetirementArchive(button.dataset.v7ArchiveBasis,true);return;
 }
 if(button.dataset.v7Control==='recover'){
  const record=rt.controlIntent;
  if(record?.intent.ref!==rt.ref||button.dataset.v7ControlRef!==record.intent.ref||button.dataset.v7ControlKey!==record.intent.body.key)return;
  await liveRetirementRecover();return;
 }
 if(button.dataset.v7Control!=='retire'||rt.controlHeld||rt.controlIntent)return;
 const target=realRetirementTargets().find(t=>t.job_ref===button.dataset.v7Job);
 if(!target||button.dataset.v7ControlBasis!==JSON.stringify(target))return;
 const block=button.closest('.live-detail-block'),note=block?.querySelector('[data-v7-retire-note]')?.value;
 if(block?.querySelector('[data-v7-retire-confirm]')?.checked!==true||typeof note!=='string'||!note.trim()||new TextEncoder().encode(note).length>4096){
  rt.controlError=rl('请勾选确认并填写理由，理由最多 4096 字节。','Confirm and enter a reason of at most 4096 bytes.','請勾選確認並填寫理由，理由最多 4096 位元組。');livePaint();return;
 }
 rt.controlError=null;
 const original=rt.pending,epoch=rt.epoch,basis=JSON.stringify(target);
 const observed=await liveRetirementStart(target.job_ref,note,true);
 if(!observed&&!rt.controlError&&!rt.controlIntent&&rt.pending===original&&rt.epoch===epoch&&JSON.stringify(liveRetirementTarget(target.job_ref))===basis){rt.controlError=rl('目标或原请求已变化，请刷新核对。','The target or original request changed; refresh and check.','目標或原請求已變更，請重新整理核對。');livePaint();}
}
document.addEventListener('click',realRetirementClick,true);
