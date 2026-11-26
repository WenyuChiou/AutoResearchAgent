// Additive stage material controls. All execution capabilities come from the server.
const m9={catalog:null,busy:false,error:'',status:'',open:false,topic:'',notes:{},target:{},importPath:'',sourcePath:'',packetHash:''};
async function m9Load(){m9.catalog=await canonicalOldRequest('/api/v9/materials');return m9.catalog;}
function m9Current(){return (m9.catalog?.materials||[]).filter(m=>m.project_ref===rt.ref&&m.stage===apps[0].stage);}
function m9Draft(m){return (m9.catalog?.drafts||[]).find(d=>d.id===m.id);}

// The qualified Host integration may supply offer(binding), submit(intent) and
// read(intent). The offer binds the Host's preallocated key and complete
// application request hash. The stock Wiki has no admission endpoint.
const m9Admission={transport:null, active:new Set(), results:new Map(), writeBlocks:new Map(), open:new Set()};
const m9SourceHash=value=>typeof value==='string'&&/^[a-f0-9]{64}$/.test(value);
const m9SourceVersion=value=>Number.isSafeInteger(value)&&value>0||
 typeof value==='string'&&/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(value);
const m9SourceMatch=(expected,actual)=>!!actual&&Object.keys(expected).every(key=>Object.hasOwn(actual,key)&&actual[key]===expected[key]);
const m9SourceRef=value=>typeof value==='string'&&/^[A-Za-z0-9_-]{1,120}$/.test(value);
const m9AdmissionTransport=()=>{
 const transport=m9Admission.transport;
 return transport&&['offer','submit','read'].every(method=>typeof transport[method]==='function')?transport:null;
};
const m9AdmissionLocks=()=>{
 const locks=globalThis.navigator?.locks;
 return typeof locks?.request==='function'?locks:null;
};
const m9AdmissionBusy=()=>rt.loading||rt.busy||rt.pending||rt.controlHeld;
function m9SourceProject(m){
 const project=rt.overview?.project;
 return project&&project.project_ref===rt.ref&&m.project_ref===rt.ref&&m9SourceVersion(project.input_version)?project:null;
}
function m9SourceScope(m){
 const p=m9SourceProject(m);
 if(!p||apps[0].stage!==1||!m9SourceRef(p.project_ref)||!/^file-[a-f0-9]{32}$/.test(m.id)||!m9SourceHash(m.sha256))return null;
 return {project_ref:p.project_ref,input_version:p.input_version,material_id:m.id,material_sha256:m.sha256};
}
function m9SourceBinding(scope){
 const p=rt.overview?.project,s=rt.overview?.stage1;
 return scope&&p.status!=='execution-unknown'&&Number.isSafeInteger(p.revision)&&p.revision>=0&&m9SourceHash(p.brief_sha256)&&
  s?.project_ref===p.project_ref&&s.input_version===p.input_version&&s.revision===p.revision&&
  s.ledger?.valid===true&&m9SourceHash(s.ledger.state_sha256)?
  {...scope,revision:p.revision,brief_sha256:p.brief_sha256,ledger_state_sha256:s.ledger.state_sha256}:null;
}
function m9AdmissionOffer(binding){
 const transport=m9AdmissionTransport();
 if(!binding||!transport)return null;
 let offer;
 try{offer=transport.offer(binding);}catch(_){return null;}
 return offer?.operation==='admit-saved-candidate'&&offer.execution_authorized===false&&
  m9SourceRef(offer.offer_ref)&&m9SourceRef(offer.key)&&m9SourceHash(offer.request_sha256)&&m9SourceMatch(binding,offer)?offer:null;
}
const m9IntentKey=scope=>'v9-provided-source-v1:'+JSON.stringify(scope);
function m9ReadIntent(scope){
 try{
  const raw=localStorage.getItem(m9IntentKey(scope));
  if(raw===null)return {intent:null};
  const intent=JSON.parse(raw);
  if(m9SourceMatch(scope,intent)&&m9SourceRef(intent.key)&&m9SourceRef(intent.offer_ref)&&
     m9SourceHash(intent.request_sha256)&&Number.isSafeInteger(intent.revision)&&intent.revision>=0&&m9SourceHash(intent.brief_sha256)&&
     m9SourceHash(intent.ledger_state_sha256)&&intent.confirmed===true)return {intent};
 }catch(_){/* A malformed or inaccessible marker must not allow another submission. */}
 return {unavailable:true};
}
function m9AdmissionReceipt(intent,result){
 if(!m9SourceMatch(intent,result)||result.execution_authorized!==false)return null;
 if(result.status==='failed'||result.status==='known-unsent')return result;
 if(result.status==='saved'&&/^e[0-9]+$/.test(result.candidate_event_id)&&
    result.provenance==='provided'&&result.identity_status==='unverified'&&
    result.screening_status==='not-screened'&&result.reading_evidence===null)return result;
 return null;
}
function m9AdmissionView(m,scope){
 const unavailable=(message)=>`<p data-n9-candidate-status role="status">${message}</p>
   <button type="button" class="hs-button" data-n9-candidate-submit="${rx(m.id)}" disabled>${rl('作为候选来源','Provide as a candidate source','作為候選來源')}</button>`;
 if(!m9AdmissionTransport())return unavailable(rl('当前 Host 尚未提供候选登记能力。已保存原文件。','This Host has no candidate admission capability available. The file is saved.','目前 Host 尚未提供候選登記能力。已儲存原始檔。'));
 if(!scope)return unavailable(rl('当前项目或输入版本未能核对。','The current project or input version could not be verified.','目前專案或輸入版本無法核對。'));
 const {intent,unavailable:missing}=m9ReadIntent(scope);
 if(missing)return unavailable(rl('无法读取原操作记录，当前不能提交。','The original operation marker is unavailable, so submission is blocked.','無法讀取原操作紀錄，目前無法送出。'));
 const marker=m9IntentKey(scope),active=m9Admission.active.has(marker),p=m9SourceProject(m);
 if(intent){
  const result=m9AdmissionReceipt(intent,m9Admission.results.get(intent.key));
  const current=intent.brief_sha256===p.brief_sha256;
  let message=rl('结果未确认。读取原回执后才能确认，原请求不会自动重发。','Outcome unconfirmed. Read the original receipt to verify it. The request is not resent automatically.','結果未確認。讀取原回執後才能確認，原請求不會自動重送。');
  if(!current)message=rl('先前操作属于同一输入的旧范围。原回执保留在该次记录中。','The previous operation belongs to an older brief for this input. Its original receipt is retained.','先前操作屬於同一輸入的舊範圍。原回執保留在該次紀錄中。');
  else if(result?.status==='saved')message=rl('候选来源已登记','Candidate source registered','候選來源已登記')+' · '+rx(result.candidate_event_id)+' · unverified · not-screened';
  else if(result)message=rl('原登记未完成','The original admission did not complete','原登記未完成')+' · '+rx(result.status);
  return `<p data-n9-candidate-status role="status">${message}</p>${current?`<button type="button" class="hs-button" data-n9-candidate-read="${rx(m.id)}" data-n9-candidate-scope="${rx(JSON.stringify(scope))}" ${active?'disabled':''}>${rl('查询原登记回执','Read original admission receipt','查詢原登記回執')}</button>`:''}`;
 }
 const writeBlock=m9Admission.writeBlocks.get(marker);
 if(writeBlock==='storage')return unavailable(rl('无法在浏览器保存原请求标识，本次未提交。','Could not save the original operation marker in browser storage. Nothing was submitted.','無法在瀏覽器儲存原請求識別碼，本次未送出。'));
 if(writeBlock==='lock'||!m9AdmissionLocks())return unavailable(rl('浏览器未能取得同源操作锁，当前不能登记。','A same-origin operation lock is unavailable. Submission is blocked.','瀏覽器無法取得同來源操作鎖，目前無法登記。'));
 const binding=m9SourceBinding(scope),offer=m9AdmissionOffer(binding);
 if(!offer)return unavailable(rl('当前材料或版本未收到可用的绑定登记选项。','No bound admission offer is available for this material and version.','目前材料或版本未收到可用的綁定登記選項。'));
 return `<p data-n9-candidate-status role="status">${rl('确认提供这份材料。登记后仍待核实和筛选。','Provide this material explicitly. Verification and screening remain pending.','確認提供這份材料。登記後仍待核實與篩選。')}</p>
   <button type="button" class="hs-button" data-n9-candidate-submit="${rx(m.id)}" data-n9-candidate-offer="${rx(offer.offer_ref)}"
    data-n9-candidate-key="${rx(offer.key)}" data-n9-candidate-request="${rx(offer.request_sha256)}"
    data-n9-candidate-binding="${rx(JSON.stringify(binding))}" ${active||m9AdmissionBusy()?'disabled':''}>${rl('作为候选来源','Provide as a candidate source','作為候選來源')}</button>`;
}
function m9SourceDetails(m,draft){
 if(m.stage!==1||m.kind!=='manual-file'||m.status!=='registered')return '';
 const p=m9SourceProject(m),scope=m9SourceScope(m),extension=/\.[A-Za-z0-9]+$/.exec(m.name)?.[0]||'Unknown';
 const view=JSON.stringify(scope||[m.project_ref,m.id,m.sha256]);
 const note=draft?.project_ref===m.project_ref&&draft.source_sha256===m.sha256?draft.note:null;
 const unknown=rl('未提供','Not recorded','未提供');
 return `<details class="n9-material-note" data-n9-source-info="${rx(view)}" ${m9Admission.open.has(view)?'open':''}>
  <summary>${rl('查看保存材料与出处','Inspect saved material and provenance','查看儲存材料與出處')}</summary>
  <dl style="overflow-wrap:anywhere">
   <dt>${rl('文件名','File name','檔名')}</dt><dd>${rx(m.name)}</dd>
   <dt>${rl('所属项目','Project','所屬專案')}</dt><dd>${rx(m.project_ref)}</dd>
   <dt>${rl('当前项目输入版本','Current project input version','目前專案輸入版本')}</dt><dd>${rx(p?`${p.input_version} · ${typeof p.input_version==='number'?rl('数字','number','數字'):rl('文本','string','文字')}`:unknown)}</dd>
   <dt>${rl('上传时的输入版本','Input version at upload','上傳時的輸入版本')}</dt><dd>${rx(m9SourceVersion(m.input_version)?m.input_version:unknown)}</dd>
   <dt>${rl('登记文件后缀 · 原始发布类型未核实','Saved extension · original publication format unverified','登記檔案副檔名 · 原始發布類型未核實')}</dt><dd>${rx(extension)}</dd>
   <dt>${rl('字节与 SHA-256','Bytes and SHA-256','位元組與 SHA-256')}</dt><dd>${rx(m.bytes)} B · <code>${rx(m.sha256)}</code></dd>
   <dt>${rl('出处 · 操作者说明，未核实','Provenance · unverified operator note','出處 · 操作者說明，未核實')}</dt><dd style="white-space:pre-wrap">${rx(note||unknown)}</dd>
  </dl>${m9AdmissionView(m,scope)}</details>`;
}
document.addEventListener('toggle',e=>{
 const node=e.target,key=node.dataset?.n9SourceInfo;
 if(!node.isConnected||!key)return;
 if(node.open)m9Admission.open.add(key);else m9Admission.open.delete(key);
},true);
function m9AdmissionMaterial(id){
 return m9Current().find(item=>item.id===id&&item.kind==='manual-file'&&item.status==='registered');
}
async function m9AdmissionAction(button,scope,transport,read){
 const m=m9AdmissionMaterial(scope.material_id),marker=m9IntentKey(scope);
 if(!m||!button.isConnected||button.disabled||m9AdmissionBusy()||transport!==m9AdmissionTransport()||
    !m9SourceMatch(scope,m9SourceScope(m))||m9Admission.active.has(marker))return;
 const prior=m9ReadIntent(scope);
 if(prior.unavailable){livePaint();return;}
 let intent=prior.intent;
 if(read){
  if(!intent||intent.brief_sha256!==m9SourceProject(m).brief_sha256||button.dataset.n9CandidateScope!==JSON.stringify(scope))return;
 }else{
  if(intent||m9Admission.writeBlocks.has(marker)){livePaint();return;}
  const binding=m9SourceBinding(scope),offer=m9AdmissionOffer(binding);
  if(!offer||offer.offer_ref!==button.dataset.n9CandidateOffer||offer.key!==button.dataset.n9CandidateKey||
     offer.request_sha256!==button.dataset.n9CandidateRequest||JSON.stringify(binding)!==button.dataset.n9CandidateBinding)return;
  intent={...binding,offer_ref:offer.offer_ref,key:offer.key,request_sha256:offer.request_sha256,confirmed:true};
  try{localStorage.setItem(marker,JSON.stringify(intent));}
  catch(_){m9Admission.writeBlocks.set(marker,'storage');livePaint();return;}
 }
 m9Admission.active.add(marker);
 livePaint();
 try{
  const result=m9AdmissionReceipt(intent,await (read?transport.read(intent):transport.submit(intent)));
  if(result)m9Admission.results.set(intent.key,result);
 }catch(_){/* Retain the same intent. An absent response says nothing about the write. */}
 finally{
  m9Admission.active.delete(marker);
  if(m9SourceMatch(scope,m9SourceScope(m)))livePaint();
 }
}
document.addEventListener('click',async e=>{
 const button=e.target.closest('[data-n9-candidate-submit],[data-n9-candidate-read]'),transport=m9AdmissionTransport();
 if(!button||button.disabled||!transport||m9AdmissionBusy())return;
 const read=!!button.dataset.n9CandidateRead;
 const m=m9AdmissionMaterial(read?button.dataset.n9CandidateRead:button.dataset.n9CandidateSubmit);
 const scope=m?m9SourceScope(m):null;
 if(!scope)return;
 if(read)return m9AdmissionAction(button,scope,transport,true);
 const locks=m9AdmissionLocks(),marker=m9IntentKey(scope);
 if(!locks){livePaint();return;}
 try{
  await locks.request(marker,{mode:'exclusive',ifAvailable:true},lock=>{
   if(lock)return m9AdmissionAction(button,scope,transport,false);
   if(m9SourceMatch(scope,m9SourceScope(m)))livePaint();
  });
 }catch(_){
  m9Admission.writeBlocks.set(marker,'lock');
  if(m9SourceMatch(scope,m9SourceScope(m)))livePaint();
 }
});

function m9Export(m){const operation=m9.catalog?.operations.find(o=>o.material_id===m.id),draft=m9Draft(m);return {kind:'V9LocalContinuationRequest',material:m,local_review:draft||null,harness_workflow:operation||null,
   input_stage:m.stage,target_stage:draft?.target_stage??m.stage,execution_authorized:false,
   handoff_scope:'operator material reference; not a formal scientific handoff or model permit',
   next_requirements:operation?.status==='prepared'?['Register independent review roles and receipts in this workflow','Explicit research resources and provider required for new model calls']:m.next_requirements||['Input schema and stage capability must be checked by Harness'],
   inspect_command:operation?.status==='prepared'?['python','-m','stage2_workflow','inspect','--run',operation.run_dir,'--expected-head',operation.event_head]:null};}
function m9Download(name,bytes,type='application/json'){const blob=new Blob([bytes],{type}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);}
function m9Panel(app){const entries=(m9.catalog?.available_deliveries||[]).filter(x=>x.stage===app.stage),materials=m9Current();return `<details class="hs-panel n9-materials" data-n9-material-panel ${m9.open?'open':''}><summary>${rl('加入文件与阶段接续','Add files & continue a stage','加入檔案與階段接續')} · Stage${app.stage} · ${materials.length} ${rl('份材料','materials','份材料')}</summary><p class="n2-hint">${rl('手动材料保留原件、版本和阶段。登记后可恢复、核验与准备接续；不会自动标记为已阅读、已纳入或研究完成。','Original materials, versions and stages are retained. Register, restore, validate and prepare continuation without automatic reading or completion claims.','手動材料保留原件、版本及階段。登記後可恢復、核驗及準備接續；不自動標記為已閱讀、已納入或研究完成。')}</p><div class="n9-material-tools"><input type="file" multiple data-n9-upload aria-label="${rl('选择阶段材料','Choose stage materials','選擇階段材料')}" accept=".pdf,.json,.jsonl,.md,.txt,.csv,.tsv,.bib,.zip,.docx,.png,.jpg,.xlsx" ${m9.busy?'disabled':''}><button class="hs-button" data-n9-action="refresh" ${m9.busy?'disabled':''}>${rl('读取保存状态','Reload saved state','讀取保存狀態')}</button></div><small>${rl('每文件最多128 MiB。ZIP保留为原始材料，不自动执行或解包。','Up to128 MiB per file. ZIPs remain original material; no automatic execution or extraction.','每檔最多128 MiB。ZIP保留原始材料，不自動執行或解包。')}</small>${entries.length?`<div class="n9-material-tools">${entries.map(x=>`<button class="hs-button" data-n9-delivery="${rx(x.id)}" ${m9.busy?'disabled':''}>${rl('登记当前交付','Register current delivery','登記目前交付')} · ${rx(x.name)}</button>`).join('')}</div>`:''}<p class="n9-feedback" role="status">${rx(n9Message(m9.status))}</p>${m9.error?`<p class="live-error" role="alert">${rx(m9.error)}</p>`:''}<div data-n9-catalog>${materials.map(m=>m9Card(m)).join('')||`<p class="n2-hint">${rl('此项目在当前阶段尚未登记手动材料。','No manual materials registered for this project and stage.','此專案在目前階段尚未登記手動材料。')}</p>`}</div>${app.stage===2?`<details class="n2-secondary"><summary>${rl('接入其他Stage2 packet（本地已解包）','Import another Stage2 packet (already extracted locally)','接入其他Stage2 packet（本機已解包）')}</summary><p class="n2-hint">${rl('使用Harness原有Stage2Packet格式；目录位于the configured incoming directory。核对全部来源字节，原科学规则不变。','Use the existing Harness Stage2Packet format under the configured incoming directory. All source bytes and original contract rules are verified.','使用Harness原有Stage2Packet格式，目錄位於the configured incoming directory。核對全部來源位元組，原科學規則不變。')}</p><div class="n9-manual-import"><label>packet.json<input data-n9-field="importPath" value="${rx(m9.importPath)}" placeholder="/your/incoming/packet.json"></label><label>${rl('来源文件目录','Source file directory','來源檔案目錄')}<input data-n9-field="sourcePath" value="${rx(m9.sourcePath)}"></label><label>packet.json SHA-256<input data-n9-field="packetHash" value="${rx(m9.packetHash)}"></label><button class="hs-button" data-n9-action="import" ${m9.busy?'disabled':''}>${rl('核验并登记packet','Validate & register packet','核驗並登記packet')}</button></div></details>`:''}${app.stage>=3?`<p class="n2-hint">${rl('本阶段可保存和恢复材料；执行适配尚未接通。','Materials can be saved and restored; execution adapter is not connected.','本階段可保存及恢復材料，執行適配尚未接通。')}</p>`:''}</details>`;}
function m9Card(m){const draft=m9Draft(m),op=m9.catalog.operations.find(o=>o.material_id===m.id);return `<article class="n9-material-card"><h4>${rx(m.name)}</h4><small>${rx(n9UiLabel(m.status))} · Stage${m.stage} · SHA ${rx(m.sha256.slice(0,16))}…</small><p>${m.kind==='manual-file'?rl('待处理材料：尚未自动提取、筛选或阅读。','Pending material: not automatically extracted, screened or read.','待處理材料：尚未自動提取、篩選或閱讀。'):rl('保存交付：原始判断保留，接续另建状态。','Saved delivery: original judgments retained; continuation has separate state.','保存交付：原始判斷保留，接續另建狀態。')}</p>${m9SourceDetails(m,draft)}<div class="hs-action-row">${m.stage===2&&m.packet_path?`<button class="hs-button" data-n9-prepare="${rx(m.id)}" ${m9.busy||op?'disabled':''}>${rl('建立Harness接续快照','Prepare Harness workflow','建立Harness接續快照')}</button>`:''}${m.kind==='manual-file'&&m.status==='registered'?`<button class="hs-button" data-n9-file="${rx(m.id)}">${rl('下载原件','Download original','下載原件')}</button>`:''}<button class="hs-button" data-n9-export="${rx(m.id)}">${rl('导出接续请求','Export continuation request','匯出接續請求')}</button></div>${op?`<div class="n9-workflow"><strong>${rx(n9UiLabel(op.status))}</strong><p>${op.status==='prepared'?rl('Harness已保存真实工作流快照；尚未启动模型、研究或独立评审。','Harness saved a real workflow snapshot; no model, research or independent review has started.','Harness已保存真實工作流快照；尚未啟動模型、研究或獨立評審。'):rx(op.error||rl('操作尚未确认，请读取原状态','Operation is unconfirmed; reload the saved state','操作尚未確認，請讀取原狀態'))}<br><small>${rx(op.workflow_id||op.id)} · head ${rx(op.event_head?.slice(0,16)||'Unknown')}</small></p>${op.status==='prepared'?`<button class="hs-button" data-n9-inspect="${rx(op.id)}">${rl('核验并恢复工作流','Verify & restore workflow','核驗並恢復工作流')}</button>`:''}</div>`:''}<details class="n9-material-note"><summary>${rl('后续阶段与本地意见','Next stage & local note','後續階段與本地意見')}${draft?' · '+rl('已保存','Saved','已保存'):''}</summary><label>${rl('希望接续到','Requested stage','希望接續至')} <select data-n9-target="${rx(m.id)}">${[1,2,3,4,5,6].map(stage=>`<option value="${stage}" ${(m9.target[m.id]??draft?.target_stage??m.stage)===stage?'selected':''}>Stage ${stage}</option>`).join('')}</select></label><textarea rows="3" maxlength="4000" data-n9-note="${rx(m.id)}" placeholder="${rl('用途、希望补充的问题或待审路线','Purpose, questions or route for review','用途、希望補充的問題或待審路線')}">${rx(m9.notes[m.id]??draft?.note??'')}</textarea><button class="hs-button" data-n9-save="${rx(m.id)}" ${m9.busy?'disabled':''}>${rl('保存接续草稿','Save continuation draft','保存接續草稿')}</button><small> · ${rl('保存目标阶段不等于该阶段已获准执行','Requested stage does not authorize execution','保存目標階段不等於該階段已獲准執行')}</small></details>${m.stage===1&&m.kind==='saved-delivery'?`<p>${rx(m.next_requirements?.join('；')||'')}</p>`:''}</article>`;}
function m9Stage1Bar(){return `<div class="n9-stage1-bar"><button class="hs-button" data-n9-jump="topic">${rl('题目与范围','Topic & scope','題目與範圍')}</button><button class="hs-button" data-n9-jump="materials">${rl('加入文件','Add files','加入檔案')}</button><button class="hs-button" data-n9-jump="feedback">${rl('运行与反馈','Progress & feedback','執行與回饋')}</button><span>${rl('结果为主体 · 原笔记与证据按需展开','Results first · notes and evidence on demand','結果為主體 · 原筆記與證據按需展開')}</span></div>`;}
function m9Matching(){return m9Current().filter(m=>m.packet_path&&(m.packet_file_sha256||m.sha256)===n2.meta?.packet_json_sha256);}
function m9Choice(){return {packet_sha256:n2.meta.packet_json_sha256,source_ids:[...n2.papers],candidates:n2.model.routes.filter(r=>n2.routes.includes(r.candidate.candidate_id)).map(r=>({candidate_id:r.candidate.candidate_id,version:r.candidate.version}))};}
const m9ResultRender=n2Render;
n2Render=function(app){const html=m9ResultRender(app);if(!n2.model)return html;const matches=m9Matching();return html+`<section class="hs-panel n9-continuation"><h3>${rl('本次比较与接续状态','Comparison & continuation state','本次比較與接續狀態')}</h3><p>${rl('下方保存的是比较清单。正式选案、研究执行和新产物仍需对应的 Harness 回执；当前图表来自原交付。','Save a comparison shortlist here. Formal selection, execution and new outputs require Harness receipts; current charts show the original delivery.','此處保存比較清單。正式選案、研究執行及新產物仍需對應 Harness 回執；目前圖表來自原交付。')}</p>${matches.length?matches.map(m=>{const d=m9Draft(m),op=m9.catalog.operations.find(o=>o.material_id===m.id),s=d?.selection;return `<div class="n9-material-card"><strong>${rx(m.name)} · ${rx(m.id.slice(0,16))}</strong><p data-n9-selection-status>${s?rx(s.source_ids.join(' / '))+' · '+rx(s.candidates.map(c=>c.candidate_id+' v'+c.version).join(' / '))+' · r'+d.revision:rl('尚未保存比较清单','Comparison shortlist not saved','尚未保存比較清單')}</p><div class="hs-action-row"><button class="hs-button" data-n9-choice-save="${rx(m.id)}" ${m9.busy?'disabled':''}>${rl('保存当前文献与路线比较','Save current literature & route comparison','保存目前文獻與路線比較')}</button><button class="hs-button" data-n9-choice-restore="${rx(m.id)}" ${m9.busy||!s?'disabled':''}>${rl('恢复已保存比较','Restore saved comparison','恢復已保存比較')}</button></div><small>${op?rx(n9UiLabel(op.status))+' · '+rx(op.workflow_id||op.id):rl('Harness工作流尚未建立','Harness workflow not prepared','Harness工作流尚未建立')} · ${rl('新研究产物：尚未生成','New research output: not generated','新研究產物：尚未產生')}</small></div>`;}).join(''):`<p>${rl('先在“加入文件”登记或导入packet，再点“读取并显示这份材料”。比较只绑定当前核验版本，其他项目的结果不会混入。','Register or import a packet, then choose Read & display this input. Comparisons bind to the verified version; other projects are kept separate.','先登記或匯入packet，再點「讀取並顯示此材料」。比較只綁定目前核驗版本，不混入其他專案結果。')}</p>`}<p role="status">${rx(n9Message(m9.status))}</p>${m9.error?`<p role="alert">${rx(m9.error)}</p>`:''}</section>`;};
document.addEventListener('click',async e=>{
 const b=e.target.closest('[data-n9-choice-save],[data-n9-choice-restore]');if(!b||m9.busy)return;
 const id=b.dataset.n9ChoiceSave||b.dataset.n9ChoiceRestore,m=m9Matching().find(x=>x.id===id);
 if(!m||(typeof p9!=='undefined'&&p9.shown&&p9.shown.id!==id))return;
 const ref=rt.ref,stage=apps[0].stage,model=n2.model,meta=n2.meta,
  epoch=typeof p9==='undefined'?null:p9.epoch,shown=typeof p9==='undefined'?null:p9.shown;
 const assertCurrent=()=>{
  if(ref!==rt.ref||stage!==apps[0].stage||model!==n2.model||meta!==n2.meta||
     epoch!==(typeof p9==='undefined'?null:p9.epoch)||shown!==(typeof p9==='undefined'?null:p9.shown)||
     !m9Matching().some(x=>x.id===id&&x.project_ref===ref&&x.sha256===m.sha256))
   throw Error('comparison-display-changed');
 };
 m9.busy=true;m9.error='';
 try{
  if(b.dataset.n9ChoiceSave){
   const d=m9Draft(m);
   await canonicalOldRequest('/api/v9/draft',{id:m.id,revision:d?.revision||0,note:d?.note||'',target_stage:d?.target_stage||2,selection:m9Choice()});
   assertCurrent();await m9Load();assertCurrent();
   m9.status=()=>rl('比较清单已保存到磁盘；未提交正式选案。','Comparison saved to disk; no formal selection submitted.','比較清單已保存至磁碟，未提交正式選案。');
  }else{
   await m9Load();assertCurrent();
   const d=m9Draft(m),s=d?.selection;
   if(d?.project_ref!==ref||d.source_sha256!==m.sha256||!s||s.packet_sha256!==n2.meta.packet_json_sha256||
      s.source_ids.some(id=>!n2.model.sourceById.has(id))||
      s.candidates.some(c=>!n2.model.routes.some(r=>r.candidate.candidate_id===c.candidate_id&&r.candidate.version===c.version)))
    throw Error('saved-comparison-binding-differs');
   n2.papers=[...s.source_ids];n2.routes=s.candidates.map(c=>c.candidate_id);n2.view='routes';
   m9.status=()=>rl('已恢复同一交付版本的文献与路线比较。','Comparison restored for this exact delivery version.','已恢復同一交付版本的文獻與路線比較。');
  }
 }catch(error){m9.error=error.message;}finally{m9.busy=false;livePaint();}
});
const m9Stage1=stage1,m9Stage2=stage2,m9Later=laterStage,m9After=v7AfterRender;
stage1=app=>m9Stage1(app)+m9Panel(app);
stage2=app=>m9Stage2(app)+m9Panel(app);
laterStage=app=>m9Later(app)+m9Panel(app);
let m9Loaded=false;
v7AfterRender=function(app){m9After(app);app.el.dataset.n9Stage=app.stage;if(app.stage===2&&n2Active()){const name=app.el.querySelector('.hs-project-name span');if(name)name.textContent=rl('Stage2 · 独立自然提问交付','Stage2 · Independent natural-request delivery','Stage2 · 獨立自然提問交付');const note=app.el.querySelector('.lp-topic>small');if(note)note.textContent=rl('本示例的Stage2是独立交付，尚未绑定为上方Stage1项目的下游。','This Stage2 example is an independent delivery, not a bound downstream result of the Stage1 project.','本示例Stage2為獨立交付，尚未綁定為上方Stage1專案的下游。');}const badge=app.el.querySelector('.hs-preview');if(badge)badge.textContent=rl('V9 · 本地联动','V9 · Local workbench','V9 · 本機聯動');const panel=app.el.querySelector('[data-n9-material-panel]');if(panel)panel.addEventListener('toggle',()=>{if(panel.isConnected)m9.open=panel.open;});if(!m9Loaded){m9Loaded=true;m9Load().then(()=>livePaint()).catch(e=>{m9.error=e.message;livePaint();});}};
document.addEventListener('input',e=>{if(e.target.matches('[data-n9-field]'))m9[e.target.dataset.n9Field]=e.target.value;if(e.target.matches('[data-n9-note]'))m9.notes[e.target.dataset.n9Note]=e.target.value;});
document.addEventListener('change',async e=>{if(e.target.matches('[data-n9-target]'))m9.target[e.target.dataset.n9Target]=Number(e.target.value);if(!e.target.matches('[data-n9-upload]'))return;const files=[...e.target.files],ref=rt.ref,stage=apps[0].stage;if(m9.busy)return;m9.busy=true;m9.open=true;m9.error='';try{for(const file of files){if(file.size>128*1024*1024)throw Error('file-exceeds-128-MiB');m9.status=()=>rl('正在保存：','Saving: ','正在保存：')+file.name;livePaint();const data=new Uint8Array(await file.arrayBuffer()),pin=[...new Uint8Array(await crypto.subtle.digest('SHA-256',data))].map(b=>b.toString(16).padStart(2,'0')).join('');const entry=await canonicalOldRequest('/api/v9/upload/start',{name:file.name,bytes:file.size,sha256:pin,project_ref:ref,stage});if(entry.status!=='registered'){for(let offset=entry.received;offset<data.length;offset+=128*1024){const chunk=data.slice(offset,offset+128*1024);let binary='';for(let i=0;i<chunk.length;i+=8192)binary+=String.fromCharCode(...chunk.subarray(i,i+8192));await canonicalOldRequest('/api/v9/upload/chunk',{id:entry.id,offset,base64:btoa(binary)});}await canonicalOldRequest('/api/v9/upload/finish',{id:entry.id});}}m9.status=()=>rl('文件已按原字节保存。未启动研究。','Files saved with exact bytes. No research started.','檔案已依原始位元組保存，未啟動研究。');await m9Load();}catch(error){m9.error=error.message;m9.status=()=>rl('请读取保存状态；重新选择同文件可继续未完成上传。','Reload saved state; reselect the same file to resume an incomplete upload.','請讀取保存狀態；重新選擇同檔案可接續未完成上傳。');}finally{m9.busy=false;livePaint();}});
document.addEventListener('click',async e=>{const b=e.target.closest('[data-n9-action],[data-n9-delivery],[data-n9-prepare],[data-n9-inspect],[data-n9-export],[data-n9-file],[data-n9-save],[data-n9-jump]');if(!b)return;e.preventDefault();if(b.dataset.n9Jump){if(b.dataset.n9Jump==='materials'){m9.open=true;const panel=apps[0].el.querySelector('[data-n9-material-panel]');if(panel){panel.open=true;panel.scrollIntoView({block:'start',behavior:'smooth'});}}else{const selector=b.dataset.n9Jump==='topic'?'.lp-operations':'[data-a03-feedback],.a03-feedback,[data-live-feedback],.live-feedback,.rf-panel';const node=apps[0].el.querySelector(selector);if(node){if(node.tagName==='DETAILS')node.open=true;node.scrollIntoView({block:'start',behavior:'smooth'});}else{const details=[...apps[0].el.querySelectorAll('details')].find(x=>/反馈|回饋|feedback/i.test(x.querySelector('summary')?.textContent||''));if(details){details.open=true;details.scrollIntoView({block:'start'});}}}return;}if(m9.busy)return;m9.busy=true;m9.error='';m9.open=true;const ref=rt.ref;try{if(b.dataset.n9Delivery)await canonicalOldRequest('/api/v9/register',{delivery_id:b.dataset.n9Delivery,project_ref:ref});if(b.dataset.n9Prepare){const m=m9.catalog.materials.find(m=>m.id===b.dataset.n9Prepare);await canonicalOldRequest('/api/v9/workflow/prepare',{id:m.id,expected_sha256:m.sha256});m9.status=()=>rl('Harness工作流快照已保存。接下来需要独立评审输入与执行配置。','Harness workflow snapshot saved. Independent review inputs and execution configuration are next.','Harness工作流快照已保存，接下來需要獨立評審輸入及執行設定。');}if(b.dataset.n9Inspect){const result=await canonicalOldRequest('/api/v9/workflows/'+b.dataset.n9Inspect);m9.status=()=>rl('已重新核验工作流及来源，保存head一致。','Workflow and sources revalidated; saved head matches.','已重新核驗工作流及來源，保存head一致。')+'\n'+result.workflow_id;}if(b.dataset.n9Save){const m=m9.catalog.materials.find(m=>m.id===b.dataset.n9Save),d=m9Draft(m);await canonicalOldRequest('/api/v9/draft',{id:m.id,revision:d?.revision||0,note:m9.notes[m.id]??d?.note??'',target_stage:m9.target[m.id]??d?.target_stage??m.stage});m9.status=()=>rl('接续草稿已保存到本地磁盘。','Continuation draft saved to local disk.','接續草稿已保存至本機磁碟。');}if(b.dataset.n9Export){const m=m9.catalog.materials.find(m=>m.id===b.dataset.n9Export);m9Download('V9-continuation-'+m.id+'.json',JSON.stringify(m9Export(m),null,2));}if(b.dataset.n9File){const m=m9.catalog.materials.find(m=>m.id===b.dataset.n9File),r=await fetch('/api/v9/files/'+m.id,{headers:{Authorization:'Bearer '+window.RESEARCH_PROJECTS.credential},cache:'no-store'});if(!r.ok)throw Error('material-download-failed');const data=await r.arrayBuffer();if([...new Uint8Array(await crypto.subtle.digest('SHA-256',data))].map(b=>b.toString(16).padStart(2,'0')).join('')!==m.sha256)throw Error('download-hash-differs');m9Download(m.name,data,'application/octet-stream');}if(b.dataset.n9Action==='import'){await canonicalOldRequest('/api/v9/import-packet',{project_ref:ref,packet_path:m9.importPath,source_root:m9.sourcePath,sha256:m9.packetHash.trim().toLowerCase()});m9.status=()=>rl('材料已核验并登记。','Material verified and registered.','材料已核驗並登記。');}await m9Load();}catch(error){m9.error=error.message;m9.status=()=>rl('未确认成功时请读取保存状态，原材料和失败记录保留。','If outcome is uncertain, reload saved state. Original materials and failures remain.','未確認成功時請讀取保存狀態，原材料及失敗紀錄保留。');}finally{m9.busy=false;livePaint();}});
