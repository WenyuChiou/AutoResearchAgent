// Explicit uploaded-source admission; never authorize query/model/review work.
const s1Provided={drafts:{},requests:{},busy:false,states:{}};
const s1ProvidedCard=m9Card;
function s1ProvidedState(id){return s1Provided.states[id]??={open:false,message:'',error:''};}
try{
 const cached=JSON.parse(sessionStorage.getItem('v9-provided-requests')||'{}');
 if(cached&&typeof cached==='object'&&!Array.isArray(cached))s1Provided.requests=cached;
}catch(_){}
function s1ProvidedSave(){try{sessionStorage.setItem('v9-provided-requests',JSON.stringify(s1Provided.requests));}catch(_){}}
document.addEventListener('toggle',e=>{
 const n=e.target;if(n.matches?.('[data-provided-form]')&&n.isConnected)s1ProvidedState(n.dataset.providedForm).open=n.open;
},true);
function s1ProvidedField(id,key,label,value){
 const attributes=`data-provided-field="${key}" data-provided-id="${rx(id)}" maxlength="2000" ${s1Provided.busy?'disabled':''}`;
 return `<label>${label}${key==='authors'?`<textarea rows="3" ${attributes}>${rx(value)}</textarea>`:`<input ${attributes} value="${rx(value)}">`}</label>`;
}
// The registration form for one registered Stage 1 upload; shared by the old card and the Wiki V1 materials table.
function s1ProvidedForm(m){
 if(m.stage!==1||m.kind!=='manual-file'||m.status!=='registered')return '';
 const original='';
 if(!m9.catalog?.stage1_provided_admission)return original+`<p>${rl('此构建未接通已存来源登记。文件上传不等于 Stage1 来源、阅读或交付。','Saved-source admission is unavailable in this build. Upload is not a Stage1 source, reading or delivery.')}</p>`;
 const d=s1Provided.drafts[m.id]||{},state=s1ProvidedState(m.id);
 const fields=[['title','原件题名','Original title'],['authors','作者（每行一位）','Authors (one per line)'],['year','年份','Year'],['version','原件版本','Source version'],['url','原始来源 URL','Original source URL'],['doi','DOI（可留空）','DOI (optional)'],['type','原始类型（如 text/plain）','Original type (e.g. text/plain)'],['reason','保存理由与材料性质','Reason and material scope']];
 return original+`<details data-provided-form="${rx(m.id)}" ${state.open?'open':''}><summary>${rl('登记为研究者导入的已保存材料（不是检索结果）','Register as a researcher-imported saved material (not a search result)')}</summary><p>${rl('只登记已上传原件及其身份声明，不表示身份核实、筛选、全文阅读或 Stage1 完成。不启动查询或模型。','Records uploaded bytes and declared identity only; no verification, screening, full reading, Stage1 completion, query or model call.')}</p>${fields.map(([key,zh,en])=>s1ProvidedField(m.id,key,rl(zh,en),d[key]||'')).join('')}${rt.overview?.stage1?.ledger?'':`<p role="note">${rl('这个课题还没有 Stage 1 账本：先在「运行与操作」里完成检索规划并初始化，才能登记。','This topic has no Stage 1 ledger yet: finish the search plan and initialization under Run and operations first.')}</p>`}<button class="hs-button" data-provided-submit="${rx(m.id)}" ${s1Provided.busy||!rt.overview?.stage1?.ledger?'disabled':''}>${rl('确认登记此来源（离线）','Confirm this source registration (offline)')}</button><p role="status">${rx(state.message)}</p>${state.error?`<p role="alert">${rx(state.error)}</p>`:''}</details>`;
}
m9Card=function(m){return s1ProvidedCard(m)+s1ProvidedForm(m);};
document.addEventListener('input',e=>{
 const n=e.target;if(!n.matches('[data-provided-field]'))return;
 const d=s1Provided.drafts[n.dataset.providedId]??={};d[n.dataset.providedField]=n.value;
});
document.addEventListener('click',async e=>{
 const button=e.target.closest('[data-provided-submit]');if(!button||s1Provided.busy)return;
 e.preventDefault();const id=button.dataset.providedSubmit;
 const material=m9Current().find(m=>m.id===id&&m.project_ref===rt.ref&&m.stage===1);
 if(!material||!m9.catalog?.stage1_provided_admission){const state=s1ProvidedState(id);state.open=true;state.error='provided-material-current-view-required';livePaint();return;}
 const state=s1ProvidedState(id);state.open=true;
 const d=s1Provided.drafts[id]||{},project=rt.overview?.project,ledger=rt.overview?.stage1?.ledger;
 state.error='';state.message='';
 try{
  const year=Number(d.year);
  if(!project||!ledger||!d.year?.trim()||!Number.isInteger(year)||!d.title?.trim()||!d.authors?.trim()||!d.version?.trim()||!d.url?.trim()||!d.type?.trim()||!d.reason?.trim())throw Error('provided-source-fields-and-current-ledger-required');
  const record={title:d.title.trim(),authors:d.authors.split('\n').map(s=>s.trim()).filter(Boolean),year,version:d.version.trim()};
  if(d.doi?.trim())record.doi=d.doi.trim();
  const body={project_ref:rt.ref,revision:project.revision,input_version:project.input_version,brief_sha256:project.brief_sha256,ledger_state_sha256:ledger.state_sha256,confirmed:true,material_id:id,material_sha256:material.sha256,record,source_uri:d.url.trim(),original_type:d.type.trim(),reason:d.reason.trim()};
  const signature=JSON.stringify(Object.fromEntries(Object.entries(body).filter(([k])=>!['revision','ledger_state_sha256'].includes(k)))),prior=s1Provided.requests[id];
  const request=prior?.signature===signature?prior.body:{...body,key:crypto.randomUUID()};
  s1Provided.requests[id]={signature,body:request};s1ProvidedSave();s1Provided.busy=true;livePaint();
  const receipt=await canonicalOldRequest('/api/v9/stage1/admit-material',request);
  state.message=(receipt.status==='saved'
   ?rl('已登记，仍未筛选或阅读。回执：','Registered; still unscreened and unread. Receipt: ')
   :rl('登记结果未确认；保留原请求，请核对保存历史。回执：','Registration unconfirmed; original request retained. Check saved history. Receipt: '))+receipt.key;
  await liveRefresh();await m9Load();
 }catch(error){
  state.error=error.message;
  // Only these exact receipt-free preflight refusals prove no action was saved.
  // Network/unknown/receipt-bearing failures retain the original request key.
  if(error.status===409&&!error.receipt&&['stale-revision','stage1-ledger-state-stale'].includes(error.message)){
   delete s1Provided.requests[id];s1ProvidedSave();await liveRefresh();
  }
 }
 finally{s1Provided.busy=false;livePaint();}
});
