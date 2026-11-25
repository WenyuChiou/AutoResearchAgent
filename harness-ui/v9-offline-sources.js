// Separate fixed-source contract. The live source authorization validator stays intact.
let offlineSourceView = null, offlineSourceBusy = false, offlineSourceError = '';
const offlineHash = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
const offlineMode = () => rt.overview?.stage1?.fixed_replay?.mode === 'fixed-offline-engineering';
const offlineBasis = () => JSON.stringify([rt.ref, liveBound(), rt.overview?.stage1?.ledger?.state_sha256]);
function offlineBound(value) {
 const p=rt.overview?.project, ledger=rt.overview?.stage1?.ledger?.state_sha256;
 if(!offlineMode() || !p || value?.mode!=='fixed-offline-engineering' || value.project_ref!==rt.ref || p.project_ref!==rt.ref ||
    !Number.isSafeInteger(value.input_version) || value.input_version<1 || value.input_version!==p.input_version ||
    value.revision!==p.revision || value.brief_sha256!==p.brief_sha256 || !offlineHash(ledger) || value.ledger_state_sha256!==ledger ||
    value.execution_authorized!==false) throw new Error('offline-source-current-binding-mismatch');
 return value;
}
function offlineIndex(value) {
 offlineBound(value);
 if(value.kind!=='ProjectStage1OfflineSources' || !offlineHash(value.config_sha256) || !Array.isArray(value.sources) || value.sources.length>32 ||
    value.model_calls!==0 || value.source_acquisition_calls!==0 || value.scientific_acceptance!==false || value.automatic_retry!==false)
  throw new Error('offline-source-index-contract-mismatch');
 const seen=new Set();
 for(const row of value.sources) {
  if(typeof row.work_ref!=='string' || !/^[A-Za-z0-9_-]{1,128}$/.test(row.work_ref) || typeof row.version_id!=='string' ||
     !/^[A-Za-z0-9_-]{1,128}$/.test(row.version_id) || seen.has(row.work_ref)) throw new Error('offline-source-work-binding-mismatch');
  seen.add(row.work_ref);
 }
 return value;
}
function offlineOffer(value, row) {
 offlineBound(value);
 if(value.work_ref!==row.work_ref || value.version_id!==row.version_id || !offlineHash(value.offer_sha256))
  throw new Error('offline-source-offer-binding-mismatch');
 return value;
}
const offlineCurrentView = () => offlineSourceView?.basis===offlineBasis() ? offlineSourceView : null;
async function offlineLoad() {
 if(!offlineMode() || offlineSourceBusy || rt.busy || rt.loading) return;
 const ref=rt.ref, basis=offlineBasis(), epoch=rt.epoch;
 offlineSourceBusy=true;offlineSourceError='';offlineSourceView=null;livePaint();
 try {
  const value=await liveRequest(projectPath(ref,'stage1/sources'));
  if(ref!==rt.ref || basis!==offlineBasis() || epoch!==rt.epoch) return;
  offlineIndex(value);
  const offers={}, errors={};
  for(const row of value.sources.filter(r=>r.status==='ready-for-explicit-local-import')) {
   try {
    const offer=await liveRequest(projectPath(ref,'stage1/sources/works/'+encodeURIComponent(row.work_ref)));
    if(ref!==rt.ref || basis!==offlineBasis() || epoch!==rt.epoch) return;
    offers[row.work_ref]=offlineOffer(offer,row);
   } catch(error) { errors[row.work_ref]=error.message; }
  }
  if(ref===rt.ref && basis===offlineBasis() && epoch===rt.epoch) offlineSourceView={basis,value,offers,errors,reading:{}};
 } catch(error) { if(ref===rt.ref && basis===offlineBasis() && epoch===rt.epoch) offlineSourceError=error.message; }
 finally {offlineSourceBusy=false;livePaint();}
}
const offlineCanonical = value => Array.isArray(value) ? '['+value.map(offlineCanonical).join(',')+']' :
 value && typeof value==='object' ? '{'+Object.keys(value).sort().map(k=>JSON.stringify(k)+':'+offlineCanonical(value[k])).join(',')+'}' : JSON.stringify(value);
const originalOfflineReceiptBound=liveReceiptBound;
liveReceiptBound=async function(p,receipt) {
 if(!p?.offline_source_config_sha256) return originalOfflineReceiptBound(p,receipt);
 if(!offlineHash(p.offline_source_config_sha256) || p.path!==projectPath(p.ref,'stage1/sources/execute') ||
    receipt?.kind!=='stage1-offline-source' || receipt.project_ref!==p.ref || receipt.key!==p.body?.key) return false;
 const body={...p.body,offline_config_sha256:p.offline_source_config_sha256};delete body.revision;
 // Native receipts intentionally omit request bodies; their digest binds the intent.
 const raw=new TextEncoder().encode(offlineCanonical({kind:'stage1-offline-source',body}));
 const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',raw)),b=>b.toString(16).padStart(2,'0')).join('');
 return receipt.request_sha256===hash;
};
async function offlineRegister(work) {
 const view=offlineCurrentView(), row=view?.value.sources.find(r=>r.work_ref===work), offer=view?.offers[work];
 if(!view || !offer || row?.status!=='ready-for-explicit-local-import' || liveDisabled() || offlineSourceBusy || rt.overview?.stage1?.coverage_actions?.held) return;
 offlineIndex(view.value);offlineOffer(offer,row);
 const ref=rt.ref, body={...liveBound(),confirmed:true,ledger_state_sha256:offer.ledger_state_sha256,
  work_ref:work,offer_sha256:offer.offer_sha256,key:crypto.randomUUID()};
 const pending={ref,path:projectPath(ref,'stage1/sources/execute'),body,offline_source_config_sha256:view.value.config_sha256};
 const bytes=JSON.stringify(pending);
 // Persist the exact intent before sending. A storage error must not send a POST.
 sessionStorage.setItem('v7-pending-action',bytes);rt.pending=pending;rt.busy=true;rt.error='';livePaint();
 const settle=async receipt=>{
  if(rt.pending!==pending || JSON.stringify(pending)!==bytes || sessionStorage.getItem('v7-pending-action')!==bytes) return false;
  const bound=await liveReceiptBound(pending,receipt);
  if(rt.pending!==pending || JSON.stringify(pending)!==bytes || sessionStorage.getItem('v7-pending-action')!==bytes || !bound || !['saved','failed','known-unsent'].includes(receipt.status)) return false;
  rt.pending=null;sessionStorage.removeItem('v7-pending-action');return true;
 };
 try {const receipt=await liveRequest(pending.path,body);if(!await settle(receipt))rt.error='offline-source-outcome-unobserved';}
 catch(error) {rt.error=error.message;if(!await settle(error.receipt))rt.error+=' · offline-source-outcome-unobserved';}
 finally {rt.busy=false;const error=rt.error;await liveRefresh(ref,{list:true});await offlineLoad();if(error){rt.error=error;livePaint();}}
}
async function offlineReading(work) {
 const view=offlineCurrentView(), row=view?.value.sources.find(r=>r.work_ref===work), basis=offlineBasis(),epoch=rt.epoch;
 if(!row || row.status!=='source-registered' || offlineSourceBusy || rt.busy || rt.loading) return;
 offlineSourceBusy=true;livePaint();
 try {
  const value=await liveRequest(projectPath(rt.ref,'stage1/source-reading/'+encodeURIComponent(work)));
  if(view!==offlineCurrentView() || basis!==offlineBasis() || epoch!==rt.epoch) return;
  // This is a read only preview, never a signed reading/review submission.
  if(value.project_ref!==rt.ref || value.input_version!==view.value.input_version || value.work_ref!==work ||
     value.version_id!==row.version_id || value.brief_sha256!==view.value.brief_sha256 || value.ledger_state_sha256!==view.value.ledger_state_sha256)
   throw new Error('offline-source-reading-binding-mismatch');
  view.reading[work]={status:'saved-reading-preview',source_ids:(value.sources||[]).map(s=>s.source_id),
   claim_count:Array.isArray(value.claims)?value.claims.length:null};
 } catch(error) {if(view===offlineCurrentView() && basis===offlineBasis() && epoch===rt.epoch)view.reading[work]={reason:error.message};}
 finally {offlineSourceBusy=false;livePaint();}
}
const previousOfflineFeedback=liveFeedback;
liveFeedback=function(app) {
 const original=previousOfflineFeedback(app);if(app.stage!==1 || !offlineMode())return original;
 const view=offlineCurrentView(), held=rt.overview?.stage1?.coverage_actions?.held, disabled=offlineSourceBusy?'disabled':liveDisabled();
 const names={'ready-for-explicit-local-import':'可明确登记','source-registered':'已登记','execution-unknown':'登记结果未知','intent-recorded':'登记结果未知','registration-unobserved':'来源登记未确认'};
 return original+`<section class="hs-panel" data-offline-sources><h3>${rl('已保存的离线来源','Saved offline sources')}</h3>
 <p>${rl('仅登记当前项目固定材料，不访问外网、不调用模型，新增科研调用成本为零。工程操作不代表真人科研审阅、覆盖通过或阶段交付。','Register pinned materials for this project only. No external network or model call and no new research-call cost. Engineering actions are not human scientific review, coverage approval or delivery.')}</p>
 <p>${rx(rt.ref)} · ${rl('输入版本','Input version')} ${rx(rt.overview?.project?.input_version)}</p>
 <button type="button" class="hs-button" data-offline-source-load ${offlineSourceBusy||rt.busy||rt.loading?'disabled':''}>${rl('查看并核对已保存来源','Inspect saved sources')}</button>
 <p role="status">${rx(offlineSourceError || (held?'stage1-coverage-write-outcome-unobserved':offlineSourceBusy?'正在读取当前绑定':view?'当前项目与账本绑定已核对':'尚未读取来源索引'))}</p>
 ${view?`<details><summary>${rl('当前输入指纹','Current input fingerprints')}</summary><p>brief: ${rx(view.value.brief_sha256)}<br>ledger: ${rx(view.value.ledger_state_sha256)}<br>config: ${rx(view.value.config_sha256)}</p></details>`:''}
 ${(view?.value.sources||[]).map(row=>`<article data-offline-source-work="${rx(row.work_ref)}"><p>${rx(row.work_ref)}<br>${rx(row.version_id)}</p><p data-offline-source-status>${rx(names[row.status]||row.status)}</p>
 ${row.registry_ref?`<p>${rl('原生来源索引','Native source registry')}: ${rx(row.registry_ref)}</p>`:''}
 ${row.receipt?`<p>${rl('原回执','Saved receipt')}: ${rx(row.receipt.key)} · ${rx(row.receipt.status)} · source ${rx(row.receipt.source_id)} · ${rx(row.receipt.actor_role)}</p>`:''}
 ${view.errors[row.work_ref]?`<p role="status">${rx(view.errors[row.work_ref])}</p>`:''}
 <button type="button" class="hs-button" data-offline-source-register="${rx(row.work_ref)}" ${row.status==='ready-for-explicit-local-import'&&view.offers[row.work_ref]&&!held?disabled:'disabled'}>${rl('登记这份固定离线材料','Register this fixed offline material')}</button>
 <button type="button" class="hs-button" data-offline-source-reading="${rx(row.work_ref)}" ${row.status==='source-registered'&&!offlineSourceBusy&&!rt.busy&&!rt.loading?'':'disabled'}>${rl('工程只读：查看来源与阅读条件','Engineering read only: inspect source and reading requirements')}</button>
 ${view.reading[row.work_ref]?`<p role="status" data-offline-source-reading-result>${rx(view.reading[row.work_ref])}</p>`:''}</article>`).join('')}
 <p>${rl('阅读、筛选、真实身份、覆盖与来源包仍以各自原生记录和门槛为准；没有记录就保持未完成。','Reading, screening, verified identity, coverage and source packages retain their native records and gates. Missing records remain incomplete.')}</p></section>`;
};
document.addEventListener('click',async event=>{
 const button=event.target.closest('[data-offline-source-load],[data-offline-source-register],[data-offline-source-reading]');
 if(!button || button.disabled)return;event.preventDefault();
 try {
  if(button.hasAttribute('data-offline-source-load'))await offlineLoad();
  else if(button.hasAttribute('data-offline-source-register'))await offlineRegister(button.dataset.offlineSourceRegister);
  else await offlineReading(button.dataset.offlineSourceReading);
 } catch(error) {rt.error=error.message;livePaint();}
});
