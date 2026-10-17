// Executed inside the retained V7 module. Repository APIs own state and authority.
const rt = {ref:null, epoch:0, loading:false, busy:false, list:[], overview:null, atlas:null,
  history:null, modelHistory:null, native:null, meta:null, selected:null, error:'', file:null, feedback:false,
  phase:'delivery', assistant:false, tab:'chat', draft:'', topicDraft:'', mode:3, focus:null, pending:null};
try { rt.pending = JSON.parse(sessionStorage.getItem('v7-pending-action') || 'null'); } catch (_) {}
// Presentation preferences only: never read or modify action intents or permits.
const livePanelNames=new Set(['sources','native-control','model-retirement']),livePanelStates=new Map(),livePanelStorage='v7-panel-state-v1';
function liveValidPanelKey(key){
 if(typeof key!=='string'||key.length>256)return false;
 try{const b=JSON.parse(key);return Array.isArray(b)&&b.length===4&&typeof b[0]==='string'&&/^[A-Za-z0-9_-]{1,64}$/.test(b[0])&&Number.isSafeInteger(b[1])&&b[1]>0&&typeof b[2]==='string'&&/^[a-f0-9]{64}$/.test(b[2])&&Number.isSafeInteger(b[3])&&b[3]>=1&&b[3]<=6&&JSON.stringify(b)===key;}catch(_){return false;}
}
function livePanelKey(app){
 const p=rt.overview?.project;if(!p||p.project_ref!==rt.ref)return null;
 const key=JSON.stringify([rt.ref,p.input_version,p.brief_sha256,app?.stage]);return liveValidPanelKey(key)?key:null;
}
function liveLoadPanels(){
 try{const raw=sessionStorage.getItem(livePanelStorage);if(typeof raw!=='string'||raw.length>24576)return;const entries=JSON.parse(raw);if(!Array.isArray(entries)||entries.length>64)return;
  for(const pair of entries){if(!Array.isArray(pair)||pair.length!==2||!liveValidPanelKey(pair[0]))continue;const value=pair[1];if(!value||typeof value!=='object'||Array.isArray(value)||!Object.keys(value).every(name=>livePanelNames.has(name)&&typeof value[name]==='boolean'))continue;livePanelStates.set(pair[0],{...value});}
 }catch(_){/* Optional preferences cannot block the workbench. */}
}
liveLoadPanels();
function liveRestorePanels(app){
 const key=livePanelKey(app);if(!key||!app?.el?.querySelectorAll)return;
 const saved=livePanelStates.get(key);
 for(const node of app.el.querySelectorAll('details[data-v7-panel]')){const name=node.dataset.v7Panel;if(!livePanelNames.has(name))continue;node.dataset.v7PanelBasis=key;if(saved&&Object.hasOwn(saved,name)&&node.open!==saved[name])node.open=saved[name];}
}
document.addEventListener('toggle',event=>{
 const node=event.target;if(!node?.isConnected||!node.matches?.('details[data-v7-panel]')||!livePanelNames.has(node.dataset.v7Panel))return;
 const app=apps.find(candidate=>candidate.el?.contains(node));if(!app)return;
 const key=livePanelKey(app);if(!key||node.dataset.v7PanelBasis!==key)return;
 const previous=livePanelStates.get(key)||{};if(previous[node.dataset.v7Panel]===node.open)return;
 livePanelStates.delete(key);livePanelStates.set(key,{...previous,[node.dataset.v7Panel]:node.open});
 while(livePanelStates.size>64)livePanelStates.delete(livePanelStates.keys().next().value);
 try{const raw=JSON.stringify([...livePanelStates]);if(raw.length<=24576)sessionStorage.setItem(livePanelStorage,raw);}catch(_){/* Keep working with bounded memory if storage is unavailable. */}
},true);
const rx = value => esc(value == null ? 'Unknown' : typeof value === 'object' ? JSON.stringify(value) : String(value));
const rl = (zh,en,tw=zh) => translated(apps[0],[zh,en,tw]);
const phaseNames={scope:['确认范围','Scope'],planning:['查询规划','Planning'],query:['查询与来源','Query & sources'],screening:['文献筛选','Screening'],reading:['阅读与证据','Reading'],coverage:['覆盖检查','Coverage'],delivery:['保存交付','Delivery']};
const stateNames={recorded:'已记录',partial:'部分完成',available:'可操作',unconnected:'未接通',held:'需处理',unknown:'Unknown',pending:'待处理',planned:'未接通',running:'运行中'};
const projectPath = (ref,tail='') => '/api/projects/'+encodeURIComponent(ref)+(tail?'/'+tail:'');
const rows = () => rt.atlas?.payload?.index?.papers || [];
function liveBound(){const p=rt.overview?.project;return p?Object.fromEntries(['revision','input_version','brief_sha256'].map(k=>[k,p[k]])):{};}
function liveAtlasPath(){const p=rt.overview?.project,a=rt.overview?.stage1?.delivery?.canonical_package;return p&&a?projectPath(rt.ref,`stage1/atlas/${p.input_version}/${p.revision}/${a.artifact_ref}/${a.manifest_sha256}`):null;}
function livePaint(){const app=apps[0];app.previewProject={id:rt.ref||'loading',topic:rt.overview?.project?.brief?.original_description||rl('正在读取项目','Loading project'),hasResults:!!rt.atlas};render(app);const badge=app.el.querySelector('.hs-preview');if(badge)badge.textContent=rl('V9 · 本地服务联动','V9 · Local service');}
async function liveRequest(path,body){
 const h={Authorization:'Bearer '+window.RESEARCH_PROJECTS.credential};if(body)h['Content-Type']='application/json';
 const response=await fetch(path,{method:body?'POST':'GET',headers:h,body:body?JSON.stringify(body):undefined,cache:'no-store',credentials:'same-origin'});
 const value=await response.json();if(!response.ok){const e=new Error(value.error||`HTTP ${response.status}`);e.status=response.status;e.receipt=value.receipt;throw e;}return value;
}
async function liveRefresh(ref=rt.ref,{list=false}={}){
 const epoch=++rt.epoch;rt.loading=true;rt.error='';rt.file=null;
  if(ref!==rt.ref){rt.ref=ref;rt.overview=null;rt.atlas=null;rt.history=null;rt.native=null;rt.modelHistory=null;rt.selected=null;rt.focus=null;rt.draft='';rt.scopeDraft=null;rt.planDraft=null;rt.realPhasePinned=false;}
 livePaint();
 try{
  const projects=list?await liveRequest('/api/projects'):rt.list;if(epoch!==rt.epoch)return;rt.list=Array.isArray(projects)?projects:projects.projects||[];
  if(!ref){ref=rt.meta?.case_ref||rt.list[0]?.project_ref;rt.ref=ref;}
  if(!ref)return;
  const overview=await liveRequest(projectPath(ref,'overview'));if(epoch!==rt.epoch)return;
  if(overview.project.project_ref!==ref)throw new Error('project-binding-mismatch');
  // Clear prior output immediately before requesting the current bound artifact.
  rt.overview=overview;rt.atlas=null;
  const path=liveAtlasPath();const [atlas,history,native,modelHistory]=await Promise.all([
   path?liveRequest(path):null,liveRequest(projectPath(ref,'history')),
   window.RESEARCH_PROJECTS.models?liveRequest(projectPath(ref,'models/native')):null, window.RESEARCH_PROJECTS.models?liveRequest(projectPath(ref,'models/actions')):null]);
  if(epoch!==rt.epoch||ref!==rt.ref)return;
  if(atlas&&(atlas.project_ref!==ref||atlas.revision!==overview.project.revision||atlas.input_version!==overview.project.input_version||atlas.manifest_sha256!==overview.stage1.delivery.canonical_package.manifest_sha256))throw new Error('artifact-binding-mismatch');
  rt.atlas=atlas;rt.history=history;rt.native=native;rt.modelHistory=modelHistory;
  if(!rows().some(p=>p.work_id===rt.selected))rt.selected=rows()[0]?.work_id||null;
 }catch(error){if(epoch===rt.epoch){rt.error=error.message;rt.atlas=null;rt.native=null;}}
 finally{if(epoch===rt.epoch){rt.loading=false;livePaint();}}
}
async function liveReceiptBound(p,a){
 const native=p.path.includes('/models/native/'),relative=p.ref?p.path.slice(projectPath(p.ref).length+1):'';
 const kinds={'confirm':'submit','compile':'compile','models/authorize':'model-authorization','models/actions':'model-operation','models/retire':'model-retirement','stage1/sources/authorize':'stage1-source-authorize','stage1/sources/execute':'stage1-source-execute','stage1/sources/recover-owner':'stage1-source-recover-owner','stage1/reading-review':'stage1-reading-registry','stage1/source-claim':'stage1-claim','stage1/prepare-delivery':'stage1-produce-records','stage2/actions':'stage2-activate'};
 const kind=native?p.path.split('/').pop():!p.ref?'create':kinds[relative]||relative.replace('stage1/','stage1-');
 if(native&&!['answer','interrupt'].includes(kind))return false;
 const compare=(a,b)=>{const x=Array.from(a,c=>c.codePointAt(0)),y=Array.from(b,c=>c.codePointAt(0));for(let i=0;i<Math.min(x.length,y.length);i++){if(x[i]!==y[i])return x[i]-y[i];}return x.length-y.length;};
 const canonical=v=>Array.isArray(v)?'['+v.map(canonical).join(',')+']':v&&typeof v==='object'?'{'+Object.keys(v).sort(compare).map(k=>JSON.stringify(k)+':'+canonical(v[k])).join(',')+'}':JSON.stringify(v);
 const body=native?p.body:Object.fromEntries(Object.entries(p.body).filter(([k])=>k!=='revision'));
 const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(canonical({kind,body})))),b=>b.toString(16).padStart(2,'0')).join('');
 const target=native?(kind==='answer'?p.body.request_ref:p.body.action_ref):null;
 return a?.key===p.body.key&&a.request_sha256===hash&&(!p.ref||a.project_ref===p.ref)&&(native?a.kind==='ProjectNativeActionObservation.v1'&&a.operation===kind&&a.target_ref===target&&a.native_index_sha256===p.body.index_sha256&&a.native_input_version===p.body.input_version&&a.native_revision===p.body.revision:a.kind===kind);
}
async function livePost(tail,body,ref=rt.ref){
 if(rt.busy||rt.loading||rt.pending||rt.controlHeld)return;
 const path=ref?projectPath(ref,tail):'/api/projects';const pending={path,ref,body:{...body,key:crypto.randomUUID()}};
 rt.pending=pending;sessionStorage.setItem('v7-pending-action',JSON.stringify(pending));rt.busy=true;rt.error='';livePaint();
 const native=path.includes('/models/native/'),clear=()=>{rt.pending=null;sessionStorage.removeItem('v7-pending-action');};
 const citation=tail==='stage1/expansion-authorize'||tail==='stage1/expansion-execute',citationBytes=JSON.stringify(pending);
 const citationCurrent=()=>rt.pending===pending&&JSON.stringify(pending)===citationBytes&&sessionStorage.getItem('v7-pending-action')===citationBytes;
 const citationSettle=async receipt=>{if(!citationCurrent())return false;const bound=await liveReceiptBound(pending,receipt);if(!citationCurrent()||!bound||!['saved','failed','known-unsent'].includes(receipt.status))return false;clear();return true;};
 const citationUnknown=()=>rl('引文请求结果仍为 Unknown；保留原请求，请查询保存历史，不会自动重发。','Citation request outcome remains Unknown. The original request is retained; check saved history. No automatic resend.','引文請求結果仍為 Unknown；保留原請求，請查詢儲存歷史，不會自動重發。');
 try{const result=await liveRequest(path,pending.body);if(citation){if(!await citationSettle(result))rt.error=citationUnknown();}else if(!native||await liveReceiptBound(pending,result)&&['known-unsent','result-observed'].includes(result.status))clear();else rt.error=rl('停止或答复请求的结果尚未确认；保留原意图，不会自动重发。','Stop or answer outcome remains unconfirmed; the original intent is retained without automatic resend.','停止或答覆請求的結果尚未確認；保留原意圖，不會自動重發。');if(!ref&&result.project_ref){ref=result.project_ref;rt.topicDraft='';}}
 catch(error){rt.error=error.message;if(citation){if(!await citationSettle(error.receipt))rt.error=citationUnknown()+' '+error.message;}else if(native){if(await liveReceiptBound(pending,error.receipt)&&['known-unsent','result-observed'].includes(error.receipt.status))clear();}else if(error.status&&error.status<500)clear();}
 finally{rt.busy=false;const message=rt.error;await liveRefresh(ref,{list:true});if(message){rt.error=message;livePaint();}}
}
async function liveRecover(){
 if(!rt.pending)return;const p=rt.pending;
 const citation=['stage1/expansion-authorize','stage1/expansion-execute'].some(tail=>p.path===projectPath(p.ref,tail)),citationBytes=citation?JSON.stringify(p):null,citationStored=citation?sessionStorage.getItem('v7-pending-action'):null;
 try{let a;const native=p.path.includes('/models/native/');
 if(p.path.includes('/models/native/')){const value=await liveRequest(projectPath(p.ref,'models/native'));a=(value.native_actions||[]).find(row=>row.key===p.body.key&&row.project_ref===p.ref);}
 else if(p.ref){const value=await liveRequest(projectPath(p.ref,'history'));a=(value.actions||[]).find(row=>row.key===p.body.key);}
 else{const value=await liveRequest('/api/projects/actions/'+encodeURIComponent(p.body.key));a=value.action||value;}
 if(rt.pending!==p)return;
 const bound=await liveReceiptBound(p,a);if(rt.pending!==p)return;
 if(citation&&(JSON.stringify(p)!==citationBytes||sessionStorage.getItem('v7-pending-action')!==citationStored))return;
 if(bound&&(native?['known-unsent','result-observed']:['saved','failed','known-unsent']).includes(a.status)){rt.pending=null;sessionStorage.removeItem('v7-pending-action');await liveRefresh(a.project_ref||p.ref,{list:true});}
 else{rt.error=rl('尚未确认上次操作的结果；不会自动重发。','Previous outcome remains unknown; no automatic resend.','尚未確認上次操作的結果；不會自動重發。');livePaint();}}
 catch(e){if(rt.pending!==p)return;rt.error=e.message;livePaint();}
}
const liveDisabled=()=>rt.busy||rt.loading||rt.pending||rt.controlHeld?'disabled':'';
function liveTop(app){return `<section class="lp-topic hs-panel"><div class="lp-topic-title"><h2>${rl('项目与研究主题','Project & research topic')}</h2><span class="hs-status">${rl('已连接本地 Harness','Local Harness connected')}</span></div><div class="lp-topic-fields"><label>${rl('当前项目','Current project')}<select data-live-project ${rt.busy?'disabled':''}>${rt.list.map(p=>`<option value="${rx(p.project_ref)}" ${p.project_ref===rt.ref?'selected':''}>${rx(p.topic||p.brief?.original_description||p.project_ref)}</option>`).join('')}</select></label><label>${rl('新研究主题','New topic')}<div class="lp-topic-entry"><input data-live-topic maxlength="240" value="${rx(rt.topicDraft)}" ${rt.loading||rt.busy?'disabled':''} placeholder="${rl('输入你的研究主题','Enter a topic')}"><button class="hs-button" data-live-action="create" ${liveDisabled()}>${rl('创建项目','Create project')}</button></div></label></div><small>${rl('保存选题不启动研究。每个项目独立保存进度与结果。','Saving a topic does not start research. Each project has separate state and results.')}</small></section>`;}
function liveHeader(app){return `<div class="hs-heading"><div><p class="hs-eyebrow">STAGE ${String(app.stage).padStart(2,'0')} / 06</p><h1>${app.stage===1?rl('文献知识网络','Literature knowledge network'):rl('研究方向比较工作台','Research comparison workbench')}</h1><p>${rx(rt.overview?.project?.brief?.original_description)}</p></div><span class="hs-status">${rt.ref===rt.meta?.case_ref?rl('仓库离线 case · 非研究结论','Repository offline case · not research findings'):rl('本地项目','Local project')}</span></div>${rt.error?`<div class="live-error" role="alert">${rl('本次操作未完成','Operation did not complete')}：${rx(rt.error)} <button data-live-action="refresh" class="hs-button">${rl('刷新检查','Refresh')}</button></div>`:''}${rt.pending?`<div class="live-error">${rt.busy?rl('操作已提交，等待保存结果','Submitted; waiting for saved outcome'):rl('上次请求结果尚未确认，已阻止重复提交','Previous outcome unknown; duplicate submission blocked')} <button class="hs-button" data-live-action="recover" ${rt.busy?'disabled':''}>${rl('查询上次结果','Check outcome')}</button></div>`:''}`;}
function liveScopeBasis(){return JSON.stringify([rt.ref,rt.overview?.project?.input_version]);}
function liveScopeValues(){return rt.scopeDraft?.basis===liveScopeBasis()?rt.scopeDraft.values:{geography:'',geographyValue:'',target:'30',priority:'20',note:''};}
function liveScopeInput(event){
 if(!rt.overview?.project||rt.loading||rt.busy||rt.pending)return;
 const fields={'data-live-geography':'geography','data-live-geography-value':'geographyValue','data-live-target':'target','data-live-priority':'priority','data-live-scope':'note'};
 const attr=Object.keys(fields).find(name=>event.target.matches(`[${name}]`));if(!attr)return;
 rt.scopeDraft={basis:liveScopeBasis(),values:{...liveScopeValues(),[fields[attr]]:event.target.value}};
}
function liveScopeForm(){
 const values=liveScopeValues(),disabled=!rt.overview?.project||rt.loading||rt.busy||rt.pending?'disabled':'';
 const choices=[['',rl('请明确选择','Choose explicitly')],['specified',rl('指定地区','Specified geography')],['unrestricted',rl('不限制','Unrestricted')],['not-applicable',rl('不适用','Not applicable')]];
 return `<div class="live-scope"><label>${rl('地域范围','Geography')}<select data-live-geography ${disabled}>${choices.map(([v,label])=>`<option value="${v}" ${values.geography===v?'selected':''}>${label}</option>`).join('')}</select></label><label>${rl('指定地区名称','Specified geography name')}<input data-live-geography-value maxlength="240" value="${rx(values.geographyValue)}" ${disabled} placeholder="${rl('选择指定地区时填写','Required for specified geography')}"></label><label>${rl('正式文献目标','Formal works target')}<input data-live-target type="number" min="1" value="${rx(values.target)}" ${disabled}></label><label>${rl('优先阅读目标','Priority readings')}<input data-live-priority type="number" min="1" value="${rx(values.priority)}" ${disabled}></label><label>${rl('范围说明','Scope explanation')}<textarea data-live-scope rows="2" ${disabled}>${rx(values.note)}</textarea></label><button class="hs-button" data-live-action="confirm" ${disabled}>${rl('保存并确认范围','Save & confirm scope')}</button></div>`;
}
function liveControls(app){const p=rt.overview?.project,s=rt.overview?.stage1,offer=s?.delivery?.offers?.find(o=>o.status==='ready-for-saved-evidence-delivery');
 return `<details class="lp-operations hs-panel" ${app.previewOps[app.stage]?'open':''} data-local-operations="${app.stage}"><summary><div><strong>Stage${app.stage} · ${rl('操作','Operations')}</strong><small>${app.stage===1?rl('选题 → 确认范围 → 保存交付','Topic → scope → saved delivery'):rl('接收 Stage1 文献包 → 审阅输入','Receive Stage1 package → review input')}</small></div><span>⌄</span></summary><div class="lp-ops-body">${app.stage===1?`${!p?.intake_report?.necessary_clarification_complete?`${liveScopeForm()}`:`<p>${rl('范围已确认','Scope confirmed')} · v${rx(p.input_version)}</p>`}<button class="hs-button hs-button-primary" data-live-action="deliver" ${!offer?'disabled':liveDisabled()}>${s?.delivery?.canonical_package?rl('重新检查当前交付','Recheck saved delivery'):rl('生成已保存证据的交付','Deliver saved evidence')}</button><small>${rl('仅处理已保存的来源；不是启动搜索或自动完成 Stage1。','Processes saved sources only; does not launch search or complete Stage1.')}</small>`:`<p>${rt.atlas?rl('当前项目 Stage1 文献包已读取，可在下方审阅。','Current Stage1 package loaded for review.'):rl('当前项目还没有 Stage1 交付。','No Stage1 delivery for this project.')}</p><button class="hs-button" disabled>${rl('运行 Stage2 · 尚未接通','Run Stage2 · unconnected')}</button>`}<button class="hs-button" data-live-action="refresh" ${rt.loading?'disabled':''}>${rl('刷新进度与结果','Refresh progress & results')}</button><div class="live-capabilities">${rl('已接通：项目、保存状态、交付读取、输入审阅。未接通：真实 Codex 执行、外部搜索、Stage2 自动运行。','Connected: projects, saved state, delivery and input review. Unconnected: live Codex execution, external search, automatic Stage2.')}</div></div></details>`;
}
function liveEmpty(stage){return `<section class="hs-panel lp-empty" data-live-empty="${stage}"><span class="lp-eyebrow">STAGE ${stage} / OUTPUT</span><h2>${rt.loading?rl('正在读取…','Loading…'):rl('尚未生成','Not generated yet')}</h2><p>${rl('这里仅显示当前项目的已保存结果，不借用其他项目或示例。','Only this project’s saved results appear here; no fallback example data.')}</p></section>`;}
// Display saved provenance only; these details do not alter records or permissions.
function liveSavedTrace(p,index){
 const claims=Array.isArray(index.claims)?index.claims.filter(c=>c?.work_id===p.work_id):null;
 const sourceIds=new Set([...(Array.isArray(p.source_ids)?p.source_ids:[]),...(claims||[]).map(c=>c.source_id).filter(id=>id!=null)]);
 const sources=Array.isArray(index.sources)?index.sources.filter(row=>sourceIds.has(row?.source_id)&&(!row.work_id||row.work_id===p.work_id)):null;
 const edges=Array.isArray(index.edges)?index.edges.filter(row=>row?.work_id===p.work_id):null;
 const raw=(label,value)=>`<details><summary>${label}</summary><pre class="live-record">${rx(value===undefined||value===null?'Unknown':JSON.stringify(value,null,2))}</pre></details>`;
 const fields=row=>`<dl>${['text','claim_id','source_id','work_id','version_id','relation','locator','start','end'].map(key=>`<dt>${key}</dt><dd>${rx(row[key])}</dd>`).join('')}</dl>`;
 return `<details data-live-saved-trace><summary>${rl('证据与版本','Evidence & version','證據與版本')} · ${rx(claims?.length)}</summary><code>${rx(p.work_id)}<br>${rx(p.version_id)}</code>${claims?.length?claims.map(c=>`<details class="real-claim" data-live-saved-claim><summary>${rx(c.claim_id)}</summary>${fields(c)}<blockquote>${rx(c.quote)}</blockquote>${raw(rl('保存的完整主张记录','Complete saved claim record','保存的完整主張紀錄'),c)}</details>`).join(''):`<p>${rx(null)}</p>`}<details data-live-saved-sources><summary>${rl('来源记录与绑定','Source records & bindings','來源紀錄與綁定')} · ${rx(sources?.length)}</summary>${sources?.length?sources.map(row=>raw(rx(row.source_id),row)).join(''):`<p>${rx(null)}</p>`}</details>${raw(rl('主张与来源关系及溯源','Claim/source relationships & provenance','主張與來源關係及溯源'),edges?.length?edges:null)}</details>`;
}
function liveDetails(){const p=rows().find(p=>p.work_id===rt.selected);if(!p)return `<section class="hs-panel hs-detail">${rl('选择论文查看详情','Select a paper')}</section>`;const index=rt.atlas.payload.index;
 const keys={question:rl('研究问题','Question'),method:rl('方法','Method'),data:rl('数据','Data'),main_findings:rl('主要发现','Findings'),limitations:rl('局限','Limitations')};
 return `<section class="hs-panel hs-detail" data-live-detail><small class="hs-detail-kicker">${rx(p.year)} · ${rx(p.venue)} · ${rx(p.evidence_level)}</small><h2 class="hs-detail-title">${rx(p.title)}</h2><p>${rx(p.authors?.join(' · '))}</p>${Object.entries(keys).map(([k,label])=>`<section class="live-detail-block"><h3>${label}</h3><p>${rx(p.findings?.[k])}</p></section>`).join('')}<section class="live-detail-block"><h3>${rl('访问与来源','Access & sources')}</h3><p>DOI: ${rx(p.doi)}</p><p>${rx(p.url)}</p><p>${rl('来源 ID','Source IDs')}: ${rx(p.source_ids?.join(', '))}</p></section>${liveSavedTrace(p,index)}</section>`;
}
function liveGraph(){const coverage=rows().some(p=>Array.isArray(p.coverage_topics));return `<section class="hs-panel"><div class="v7-graph-controls"><div>${[3,2].map(mode=>`<button class="hs-button" data-live-mode="${mode}" aria-pressed="${rt.mode===mode}">${mode}D</button>`).join('')}<button class="hs-button" data-live-action="all">${rl('查看全图','Show all')}</button><button class="hs-button" data-live-fit>${rl('适应窗口','Fit view','適應視窗')}</button><button class="hs-button" data-live-focus ${rt.focus?'':'disabled'}>${rl('聚焦所选','Focus selection','聚焦所選')}</button><label><input type="checkbox" data-live-labels ${rt.graphLabels!==false?'checked':''}>${rl('显示标签','Show labels','顯示標籤')}</label>${coverage?`<label><input type="checkbox" data-live-related ${rt.related!==false?'checked':''}>${rl('共享需求相似线（推导）','Shared-need similarity (derived)','共享需求相似線（推導）')}</label>`:''}</div></div><div class="v7-spatial-context">${rx(rt.focus?.key||rl('选择节点查看关系','Select a node'))}</div><div class="v7-spatial-host" data-live-spatial></div><div class="v7-graph-legend"><span>● ${rl('论文','Paper')}</span><span>◆ ${rl('方向','Topic')}</span><span>■ ${rl('方法','Method')}</span>${coverage?`<span>${rl('实线：保存的需求归属；短虚线：共享需求相似。选择论文显示相关线。','Solid: saved need membership; short dash: shared-need similarity. Select a paper to reveal its connections.','實線：保存的需求歸屬；短虛線：共享需求相似。選擇論文顯示相關線。')}</span>`:''}</div><p class="v7-graph-basis">${rl('仅使用保存的分类；Unknown 不会被编成关系。远近不代表证据强弱。','Only saved classifications create relationships. Unknown stays unknown; distance is not evidence strength.')}</p></section>`;}
function liveSharedNeedLinks(source){
 if(rt.related===false)return [];
 const records=source.filter(p=>Array.isArray(p.coverage_topics)),links=[];
 for(let i=0;i<records.length;i++)for(let j=i+1;j<records.length;j++){
  const a=new Set(records[i].coverage_topics),b=new Set(records[j].coverage_topics),shared=[...a].filter(x=>b.has(x)),union=new Set([...a,...b]);
  // The general closest-work collection is omitted by the saved-plan adapter.
  // Require two specific shared needs; a single broad group creates no pair edge.
  if(shared.length<2||!union.size)continue;
  const weight=shared.length/union.size;if(weight<.25)continue;
  links.push({source:records[i].key,target:records[j].key,kind:'lexical-shared-need',weight,shared_needs:shared,basis:'Jaccard of saved specific coverage needs',scientific_relation:false});
 }
 return links;
}
function liveLibrary(){if(typeof canonicalReadonly==='function'&&canonicalReadonly())return `<section class="hs-panel"><div class="hs-panel-head"><h2>${rl('文献列表','Library','文獻列表')} · ${rows().length}</h2></div><div class="hs-list">${rows().map((p,i)=>`<button type="button" class="hs-paper-row cursor-interaction" data-live-paper="${rx(p.work_id)}" aria-pressed="${p.work_id===rt.selected}"><div><strong>${rx(p.title)}</strong><small>P${i+1} · ${rx(p.work_id)} · ${rx(p.year)} · ${rx(Array.isArray(p.classification?.topic_cluster)?p.classification.topic_cluster.join(' / '):p.classification?.topic_cluster)}</small><small>${rx(p.authors?.join(' · '))} · ${rx(p.venue)} · ${rx(p.version_id)} · ${rx(p.evidence_level)}</small></div><span class="hs-status">${rl('阅读状态','Reading status','閱讀狀態')}: ${rx(p.reading_status)}</span></button>`).join('')}</div></section>`;return `<section class="hs-panel"><div class="hs-panel-head"><h2>${rl('文献列表','Library')} · ${rows().length}</h2></div><div class="live-paper-list">${rows().map((p,i)=>`<button class="hs-button" data-live-paper="${rx(p.work_id)}" aria-pressed="${p.work_id===rt.selected}"><small>P${i+1} · ${rx(p.year)}</small><strong>${rx(p.title)}</strong></button>`).join('')}</div></section>`;}
function liveFiles(){return `<details class="hs-panel live-files"><summary>${rl('已保存输出与版本','Saved outputs & versions')} · ${rt.atlas?.files?.length||0}</summary><p><small>SHA256 · ${rx(rt.atlas?.manifest_sha256)}</small></p><div class="live-file-list">${(rt.atlas?.files||[]).map((f,i)=>`<button class="hs-button" data-live-file="${i}">${rx(f.path)}</button>`).join('')}</div>${rt.file?`<h3>${rx(rt.file.filename)}</h3><pre>${rx(rt.file.content)}</pre>`:''}</details>`;}
function liveResults(app){return `<details class="lp-results" data-local-results="${app.stage}" ${app.previewResultsOpen[app.stage]!==false?'open':''}><summary><strong>Stage${app.stage} · ${rl('结果','Results')}</strong><span>${rt.atlas?rl(app.stage===1?'已保存 · 待审阅':'Stage1 输入已保存','Saved · review required'):rl('尚未生成','Not generated')} ⌄</span></summary><div class="lp-result-body">${!rt.atlas?liveEmpty(app.stage):app.stage===1?`<section class="hs-panel"><div class="hs-panel-head"><h2>${rl('文献知识网络','Literature knowledge network')}</h2><span class="hs-status">${rows().length} ${rl('篇文献','papers')}</span></div><div class="hs-atlas-grid">${liveGraph()}${liveDetails()}</div></section>${liveLibrary()}${liveFiles()}`:liveStage2Results()}</div></details>`;}
function liveStage2Results(){
 const context=rt.atlas.stage2_input||{},unknown=rl('未知（Unknown）','Unknown','未知（Unknown）');
 const statuses={include:['纳入','Included','納入'],exclude:['排除','Excluded','排除'],pending:['待定','Pending','待定'],'not-screened':['未筛选','Not screened','未篩選'],'human-reviewed':['人工审阅已登记','Human review registered','人工審閱已登記'],'discovery-only':['仅发现 · 未读','Discovery only · unread','僅發現 · 未讀']};
 const status=value=>Object.hasOwn(statuses,value)?rl(...statuses[value])+' ('+value+')':value??unknown;
 const reasons={'stage1-handoff-not-eligible':['Stage1 原交接条件未满足','Original Stage1 handoff conditions not met','Stage1 原交接條件未滿足'],'stage2-canonical-consumer-unconnected':['Stage2 规范包消费者未接通','Stage2 canonical packet consumer unconnected','Stage2 規範包消費者未接通'],'source-unavailable':['来源缺失','Source unavailable','來源缺失'],'reading-not-registered':['阅读尚未登记','Reading not registered','閱讀尚未登記'],'claim-source-or-location-unavailable':['主张来源或定位缺失','Claim source or location unavailable','主張來源或定位缺失'],'claim-level-needs-versioned-consumer':['证据级别需要版本兼容消费者','Claim level needs a versioned consumer','證據層級需要版本相容消費者']};
 const limits=value=>Array.isArray(value)?value.length?value.map(code=>Object.hasOwn(reasons,code)?rl(...reasons[code])+' ('+code+')':code).join('\n'):rl('未记录限制项（[]）','No recorded limitation entries ([])','未記錄限制項（[]）'):unknown;
 const works=Array.isArray(context.works)?context.works:[],consumer=context.consumer_status==='unconnected'?rl('尚未接通','Unconnected','尚未接通'):context.consumer_status==='existing-contract'?rl('已有契约','Existing contract','既有契約'):unknown;
 const handoff=context.eligible_for_stage2===true?rl('满足已记录条件（true）','Recorded conditions met (true)','滿足已記錄條件（true）'):context.eligible_for_stage2===false?rl('未满足已记录条件（false）','Recorded conditions not met (false)','未滿足已記錄條件（false）'):unknown;
 const binding=Object.fromEntries(['project_ref','input_version','brief_sha256','settings_sha256','artifact_ref','manifest_sha256','index_sha256','context_sha256','records_sha256','handoff_sha256','checkpoint_event_id','ledger_state_sha256','retained_inventory_sha256','retained_file_count','execution_authorized','stage2_complete'].map(key=>[key,context[key]??null]));
 return `<section class="hs-panel"><div class="hs-panel-head"><div><h2>${rl('Stage1 输入文献 · 比较矩阵','Stage1 input · comparison matrix','Stage1 輸入文獻 · 比較矩陣')}</h2><p>${rl('已保存的交接输入；Stage2 研究方向尚未生成。','Saved handoff input; Stage2 research directions have not been generated.','已保存的交接輸入；Stage2 研究方向尚未產生。')}</p><p><small>${rl('规范记录版本','Canonical records version','規範記錄版本')}: ${rx(context.records_version)} · ${rl('Stage2 规范包消费者','Stage2 canonical packet consumer','Stage2 規範包消費者')}: ${rx(consumer)} (${rx(context.consumer_status)})</small></p></div><span class="hs-status">${rl('待审阅','Review required','待審閱')}</span></div><div class="live-table-scroll"><table class="live-table"><thead><tr>${[rl('论文','Paper','論文'),rl('问题','Question','問題'),rl('方法','Method','方法'),rl('局限','Limitations','局限')].map(s=>`<th>${s}</th>`).join('')}</tr></thead><tbody>${rows().map(p=>{
  const matches=works.filter(w=>w.work_id===p.work_id&&w.version_id===p.version_id),work=matches.length===1?matches[0]:null;
  const detail=[`${rl('文献标识','Work ID','文獻識別碼')}: ${p.work_id??unknown}`,`${rl('版本标识','Version ID','版本識別碼')}: ${p.version_id??unknown}`,`${rl('来源 ID','Source IDs','來源 ID')}: ${work&&Array.isArray(work.source_ids)&&work.source_ids.length?work.source_ids.join(', '):unknown}`,`${rl('已记录限制','Recorded limitations','已記錄限制')}:\n${limits(work?.limitations)}`].join('\n');
  return `<tr><td><button class="hs-button" data-live-paper="${rx(p.work_id)}">${rx(p.title)}</button><p><small>${rl('筛选','Screening','篩選')}: ${rx(status(work?.screening_status))}<br>${rl('阅读','Reading','閱讀')}: ${rx(status(work?.reading_status))}</small></p><details><summary>${rl('输入状态与限制','Input status & limitations','輸入狀態與限制')}</summary><pre class="live-record">${rx(detail)}</pre></details></td><td>${rx(p.findings?.question)}</td><td>${rx(p.findings?.method)}</td><td>${rx(p.findings?.limitations)}</td></tr>`;
 }).join('')}</tbody></table></div><p class="live-callout">${rl('原 Stage1 handoff 资格','Original Stage1 handoff eligibility','原 Stage1 handoff 資格')}: ${rx(handoff)}<br>${rx(limits(context.limitations))}</p><details><summary>${rl('输入版本与绑定','Input version & binding','輸入版本與綁定')}</summary><pre class="live-record">${rx(JSON.stringify(binding,null,2))}</pre></details></section><div class="hs-atlas-grid">${liveGraph()}${liveDetails()}</div><section class="hs-panel lp-empty"><h2>${rl('Stage2 方向与路线：尚未生成','Stage2 directions & routes: not generated','Stage2 方向與路線：尚未產生')}</h2><p>${rl('完整执行接口未连接；输入预览不代表阶段完成。','Full execution is unconnected. Input preview does not mean stage completion.','完整執行介面未連接；輸入預覽不代表階段完成。')}</p></section>`;
}
function liveProgressNote(overview){
 const pendingQuery=typeof realQueryPending==='function'?(realQueryPending(overview)||realQueryNextBackend(overview)):null;if(pendingQuery)return pendingQuery;
 const p=overview?.project,s=overview?.stage1,m=overview?.models,q=s?.query_execution;
 if(!p||!s||s.project_ref!==p.project_ref||s.revision!==p.revision||s.input_version!==p.input_version)return null;
 const modelBound=m?.project_ref===p.project_ref&&m?.revision===p.revision&&m?.input_version===p.input_version&&m?.brief_sha256===p.brief_sha256;
 const activeKeys=new Set(modelBound?(m.active_jobs||[]).filter(j=>j.input_version===p.input_version&&j.brief_sha256===p.brief_sha256).map(j=>j.key):[]);
 const planningJob=(modelBound?m.jobs||[]:[]).find(j=>activeKeys.has(j.key)&&j.operation==='plan-search'&&j.project_ref===p.project_ref&&j.input_version===p.input_version&&j.brief_sha256===p.brief_sha256&&['intent-recorded','queued','running','dispatching'].includes(j.status));
 if(planningJob&&s.progress?.next_action?.reason==='active-action')return {message:rl('Codex 正在规划查询','Codex is planning queries'),planningJob};
 if(p.intake_report?.necessary_clarification_complete===true&&p.plan===null&&s.ledger===null&&q?.refusal==='intake-plan-not-ready'&&q.jobs?.length===0&&!activeKeys.size&&s.progress?.next_action?.reason==='stale-input')return {message:rl('范围已保存，尚未生成查询计划','Scope saved; query plan not generated yet'),planningJob:null};
 return null;
}
function liveFeedback(app){const progress=rt.overview?.stage1?.progress;const phases=app.stage===1?progress?.phases||[]:[{phase_id:'input',status:rt.atlas?'recorded':'pending',reason:'Stage1 package'},{phase_id:'review',status:rt.atlas?.stage2_input?.review?'recorded':'pending',reason:'Human review'},{phase_id:'execution',status:'unconnected',reason:'stage2-execution-unconnected'}];const selected=phases.find(p=>p.phase_id===rt.phase)||phases[0];
 const note=app.stage===1?liveProgressNote(rt.overview):null,planningPhase=note?.planningJob?progress?.next_action?.phase_id:null,phaseLabel=id=>planningPhase===id?rl('查询规划 · 当前模型任务','Query planning · current model task'):(phaseNames[id]?.[li(app)===1?1:0]||id);
 const detail=app.stage===2?rt.overview?.stage2:({scope:rt.overview?.project?.intake_report,planning:rt.overview?.project?.plan,query:{queries:rt.overview?.stage1?.query_execution??rt.overview?.stage1?.queries,sources:rt.overview?.stage1?.source_execution},screening:rt.atlas?.payload?.index?.screening??rt.library,reading:{registration:rt.overview?.stage1?.reading_registration,claims:rt.atlas?.payload?.index?.claims},coverage:rt.overview?.stage1?.ledger?.gate,delivery:rt.overview?.stage1?.delivery}[selected?.phase_id]);
 return `<details class="hs-panel rf-panel" data-live-feedback ${rt.feedback?'open':''}><summary><div><strong>Stage${app.stage} · ${rl('运行进度与反馈','Progress & feedback')}</strong><small>${app.stage===1?rx(note?.message||liveReason(progress?.next_action?.reason)):rl('输入审阅；执行未接通','Input review; execution unconnected')}</small></div><span>⌄</span></summary><div class="rf-body"><p>${rl('来自 Harness 保存记录；不代表研究质量通过。','From saved Harness records; not scientific acceptance.')}</p>${note?`<p class="live-callout">${rx(note.message)} · ${rl('服务原始状态与拒绝详情仍保留在下方。','Original server status and refusal details are retained below.')}</p>`:''}<div class="rf-grid"><nav class="rf-step-list">${phases.map((p,i)=>`<button data-live-phase="${p.phase_id}" aria-pressed="${selected?.phase_id===p.phase_id}"><span class="rf-step-number">${i+1}</span><span><strong>${rx(phaseLabel(p.phase_id))}</strong><small>${rx(note?.queryJob&&p.phase_id==='query'?rl('运行中','Running'):note?.queryNextOffer&&p.phase_id==='query'?rl('等待下一来源','Awaiting next backend'):(li(app)===1?p.status:stateNames[p.status]||p.status))}</small></span></button>`).join('')}</nav><section class="rf-step-detail"><h3>${rx(phaseLabel(selected?.phase_id))}</h3><p>${rx(liveReason(selected?.reason))}</p>${livePhaseSummary(app,planningPhase===selected?.phase_id?'planning':selected?.phase_id)}<details><summary>${rl('查看原始记录与输出','Inspect raw records & outputs')}</summary><pre class="live-record">${rx(JSON.stringify(app.stage===1?{backend_progress:progress,selected_record:detail??null,query_refusal:rt.overview?.stage1?.query_execution?.refusal??null,active_model_task:note?.planningJob??null,active_query_task:note?.queryJob??null,query_dispatch_receipt:note?.queryReceipt??null,next_query_offer:note?.queryNextOffer??null}:detail??null,null,2))}</pre></details>${selected?.phase_id==='delivery'&&rt.atlas?`<button data-live-action="results" class="hs-button">${rl('查看下方结果与文件','View results & files')}</button>`:''}</section></div><details><summary>${rl('保存历史','Saved history')}</summary><pre class="live-record">${rx(rt.history==null?null:JSON.stringify(rt.history,null,2))}</pre></details></div></details>`;
}
function liveAssistant(app){const context=rt.atlas?.stage2_input,view=rt.native?.native_view;return `<details class="hs-panel v7-assistant" data-live-assistant ${rt.assistant?'open':''}><summary><strong>Stage${app.stage} · Codex ${rl('协作与人工审阅','collaboration & human review')}</strong><small>${!!rt.ref&&rt.ref===rt.meta?.chat_ref?rl('离线 case · 无真实模型','Offline case · no live model'):rl('真实模型未连接','Live model unconnected')}</small></summary><div class="v7-assistant-body"><div class="v7-assistant-tabs">${['chat','review','handoff'].map((v,i)=>`<button class="hs-button" data-live-tab="${v}" aria-pressed="${rt.tab===v}">${[rl('Codex 问答','Codex Q&A'),rl('人工审阅','Human review'),rl('申请下一阶段','Next stage')][i]}</button>`).join('')}</div>${rt.tab==='chat'?`<p>${rl('只显示当前项目、当前阶段的会话。内容任务与运行授权分开。','Only the current project/stage session is shown. Content tasks and execution permission are separate.')}</p>${!!rt.ref&&rt.ref===rt.meta?.chat_ref&&app.stage===1?liveModelCase():''}${app.stage!==1?`<p class="live-callout">${rl('Stage2 Codex 会话接口尚未连接。','Stage2 Codex session is unconnected.')}</p>`:view?liveNative(view):liveNativeIdle()}${app.stage===1?liveModelOutputs():''}`:`<p>${rt.tab==='handoff'?rl('申请会保存审阅意见，不会自动放行或运行下一阶段。','A request saves a review; it does not authorize or run the next stage.'):rl('审阅绑定当前项目、输入版本与文献包 hash。','Review binds the current project, input version and package hash.')}</p>${context?`<label>${rl('决定','Decision')}<select data-live-decision><option value="keep-stage1">${rl('继续补充 Stage1','Continue Stage1')}</option><option value="hold">${rl('暂缓交接','Hold handoff')}</option><option value="request-stage2">${rl('申请进入 Stage2','Request Stage2')}</option></select></label><label>${rl('审阅意见','Review note')}<textarea data-live-review rows="3">${rx(rt.draft)}</textarea></label><button class="hs-button hs-button-primary" data-live-action="review" ${liveDisabled()}>${rl('保存审阅记录','Save review')}</button><p>${rl('进入资格','Eligibility')}: ${context.eligible_for_stage2?rl('满足记录条件','Recorded conditions met'):rl('未满足；申请不改变此状态','Not met; a request does not change this')}</p><pre class="live-record">${rx(context.review?JSON.stringify(context.review,null,2):rl('尚无审阅记录','No saved review'))}</pre>`:`<p>${rl('先生成当前项目的文献包，再审阅具体输出。','Generate this project’s package before reviewing its output.')}</p>`}`}</div></details>`;}
function liveNativeIdle(){
 const p=rt.overview?.project,m=rt.overview?.models,all=(m?.jobs||rt.modelHistory?.actions||[]).map(row=>row.result||row),jobs=all.filter(j=>j.project_ref===rt.ref&&j.input_version===p?.input_version&&(!j.brief_sha256||j.brief_sha256===p?.brief_sha256));
 const active=(m?.active_jobs||[]).length||jobs.some(j=>['queued','running','dispatching','intent-recorded'].includes(j.status));
 const latest=jobs.at(-1),completed=latest?.output_ref&&latest?.output_sha256&&['completed','content-review-pending','plan-validated-not-executed'].includes(latest.status);
 const failed=latest&&['failed-or-unknown','validation-failed','execution-unknown'].includes(latest.status);
 const message=active?rl('任务正在运行，目前没有待答复请求。进度与输出会保存到当前项目。','A task is running; no reply is currently requested. Progress and outputs are saved to this project.'):completed?rl('任务已完成并保存输出，目前没有待答复请求。请在下方查看输出；持续补充问答按服务可用状态显示。','The task completed and its output is saved; no reply is pending. Inspect the output below; follow-up availability is shown separately.'):failed?rl('已有任务失败或校验未通过，原始记录已保留。目前没有待答复请求，请查看任务记录。','A task failed or did not pass validation; the original record is retained. No reply is pending; inspect the saved task history.'):m?.status==='registered-content-provider'||m?.connected?rl('内容任务服务已注册，目前没有运行中的提问。','The content-task service is registered; no question is currently active.'):rl('尚未确认可用的内容任务服务；目前没有可答复的会话。','An available content-task service has not been confirmed; there is no session to answer.');
 return `<p class="live-callout" data-live-native-idle>${message}</p>`;
}
function liveNative(view){return (view.requests||[]).map((q,i)=>({q,i})).filter(({q})=>q.status==='pending').map(({q,i})=>`<form data-live-question="${i}"><p>${rx(q.method)}</p>${q.method==='item/tool/requestUserInput'?(q.payload?.questions||[]).map((question,j)=>`<label>${rx(question.question||question.header||question.id)}<textarea data-live-answer="${j}" rows="2"></textarea></label>`).join(''):`<p>${rl('此内容任务只支持拒绝或取消工具请求。','This content task allows only declining or cancelling tools.')}</p>`}<button class="hs-button" data-live-native="${i}" ${liveDisabled()}>${q.method==='item/tool/requestUserInput'?rl('提交答复','Submit answer'):rl('拒绝请求','Decline')}</button></form>`).join('')||`<p>${rl('没有待答复的问题','No pending questions')}</p>`;}

stage1=app=>`${liveTop(app)}${liveHeader(app)}${liveControls(app)}${liveResults(app)}${liveFeedback(app)}${liveAssistant(app)}`;
stage2=app=>`${liveHeader(app)}${liveControls(app)}${liveResults(app)}${liveFeedback(app)}${liveAssistant(app)}`;
otherPage=app=>`${liveHeader(app)}${app.page==='files'?liveFiles():app.page==='settings'?`<section class="hs-panel live-files"><h2>${rl('连接与额度','Connection & limits')}</h2><p>${rl('Harness 本地记录服务已接通。真实 Codex 与搜索未注册。','Local Harness records are connected. Live Codex and search are not registered.')}</p><p>${rl('金额','Monetary cost')}: ${rx(rt.overview?.project?.monetary_cost)}</p><pre class="live-record">${rx(JSON.stringify(rt.overview?.project?.settings?.budgets||null,null,2))}</pre><p>${rl('额度声明与执行许可分开；这轮验收不进行真实模型调用。','Declared limits and execution permission are separate. This acceptance run uses no live model.')}</p></section>`:liveFeedback(app)}`;
const previousAfter=v7AfterRender;
v7AfterRender=function(app){previousAfter(app);const footer=app.el.querySelector('.hs-footer');if(footer)footer.textContent=rl('V9 本地联动 · 原材料、保存输出与未接通操作分别标识','V9 local integration · original inputs, saved outputs and unconnected operations labeled');const foot=app.el.querySelector('.hs-sidebar-foot');if(foot)foot.textContent=rl('本地服务已连接 · 当前文献 ','Local service connected · current papers ')+rows().length;const badge=app.el.querySelector('.hs-preview');if(badge)badge.textContent='V9 · '+rl('本地联动','Local integration');const host=app.el.querySelector('[data-live-spatial]');if(!host)return;
 const known=x=>(Array.isArray(x)?x:[x]).filter(value=>typeof value==='string'&&value.trim()&&!/^unknown/i.test(value));
 const source=rows().map(p=>({...p,key:p.work_id,topics:known(p.coverage_topics??p.classification?.topic_cluster),methods:known(p.classification?.method)}));
 try{app.v7SpatialKey=v7Key(app);app.v7Spatial=AtlasSpatial.mount(host,{papers:source,model:AtlasModel,three:window.V7Three,theme:'light',mode:rt.mode,extraLinks:liveSharedNeedLinks(source),topicColors:typeof publicPlanningPalette==='object'?publicPlanningPalette:{},showLabels:rt.graphLabels!==false,focus:rt.focus,language:{zh:'zh-Hans',en:'en',tw:'zh-Hant'}[app.lang],paperAliases:Object.fromEntries(source.map((p,i)=>[p.key,'P'+(i+1)])),onSelect:selection=>{rt.focus={kind:selection.kind,key:selection.key};if(selection.kind==='paper')rt.selected=selection.key;livePaint();}});host.v7Diagnostics=()=>app.v7Spatial?.diagnostics();}catch(e){host.textContent=rl('图形未加载；可使用文献列表。','Graph unavailable; use the library.');host.dataset.error=e.message;}
};
document.addEventListener('change',event=>{if(event.target.matches('[data-live-labels]')){rt.graphLabels=event.target.checked;apps[0].v7Spatial?.setLabels(rt.graphLabels);}if(event.target.matches('[data-live-related]')){rt.related=event.target.checked;livePaint();}});
document.addEventListener('click',event=>{const button=event.target.closest('[data-live-fit],[data-live-focus]');if(!button)return;event.preventDefault();if(button.hasAttribute('data-live-focus'))apps[0].v7Spatial?.fitFocus();else apps[0].v7Spatial?.fit();});
document.addEventListener('change',e=>{liveScopeInput(e);if(e.target.matches('[data-live-project]')){e.stopImmediatePropagation();liveRefresh(e.target.value);} });
document.addEventListener('input',e=>{liveScopeInput(e);if(e.target.matches('[data-live-review],[data-live-draft]'))rt.draft=e.target.value;if(e.target.matches('[data-live-topic]'))rt.topicDraft=e.target.value;});
document.addEventListener('toggle',e=>{if(e.target.matches('[data-live-feedback]'))rt.feedback=e.target.open;if(e.target.matches('[data-live-assistant]'))rt.assistant=e.target.open;},true);
document.addEventListener('click',async e=>{
 if(e.target.closest('[data-stage]')){rt.draft='';rt.assistant=false;rt.feedback=false;rt.file=null;}const b=e.target.closest('[data-live-action],[data-live-paper],[data-live-phase],[data-live-tab],[data-live-mode],[data-live-file],[data-live-native]');if(!b)return;e.preventDefault();e.stopImmediatePropagation();
 if(b.hasAttribute('data-live-paper')){rt.selected=b.dataset.livePaper;rt.focus={kind:'paper',key:rt.selected};livePaint();return;}
 if(b.hasAttribute('data-live-phase')){rt.phase=b.dataset.livePhase;rt.realPhasePinned=true;livePaint();return;}
 if(b.hasAttribute('data-live-tab')){rt.tab=b.dataset.liveTab;rt.draft='';livePaint();return;}
 if(b.hasAttribute('data-live-mode')){rt.mode=Number(b.dataset.liveMode);livePaint();return;}
 if(b.hasAttribute('data-live-file')){const epoch=rt.epoch, f=rt.atlas.files[Number(b.dataset.liveFile)];try{const r=await liveRequest(liveAtlasPath()+`/files/${f.file_ref}/${f.sha256}`);if(epoch!==rt.epoch)return;rt.file=r.file;livePaint();apps[0].el.querySelector('.live-files').open=true;}catch(error){rt.error=error.message;livePaint();}return;}
 if(b.hasAttribute('data-live-native')){const v=rt.native.native_view,q=v.requests[Number(b.dataset.liveNative)],form=b.closest('form');const result=q.method==='item/tool/requestUserInput'?{answers:Object.fromEntries(q.payload.questions.map((row,i)=>[row.id,{answers:[form.querySelector(`[data-live-answer="${i}"]`).value]}]))}:{decision:'decline'};await livePost('models/native/answer',{revision:v.revision,index_sha256:v.index_sha256,input_version:v.input_version,request_ref:q.request_ref,request_sha256:q.request_sha256,result});return;}
 const action=b.dataset.liveAction;
 if(action==='model-case'){const offer=(rt.overview.model_offers?.offers||[]).find(o=>o.available===true);if(offer)return livePost('models/actions',{...liveBound(),offer_ref:offer.offer_ref,offer_sha256:offer.offer_sha256,confirmed:true});return;}if(action==='refresh')return liveRefresh(rt.ref,{list:true});if(action==='recover')return liveRecover();
 if(action==='all'){rt.focus=null;livePaint();return;}
 if(action==='results'){const result=apps[0].el.querySelector('.lp-results');result.open=true;result.scrollIntoView({behavior:'smooth'});return;}
 if(action==='create'){const topic=document.querySelector('[data-live-topic]').value.trim();if(!topic)return;return livePost('',{topic},null);}
 if(action==='confirm'){if(rt.loading||rt.busy||rt.pending||!rt.overview?.project)return;const geography=document.querySelector('[data-live-geography]').value,geographyValue=document.querySelector('[data-live-geography-value]').value.trim(),note=document.querySelector('[data-live-scope]').value.trim();if(!geography||!note||(geography==='specified'&&!geographyValue)){rt.error=rl('请选择范围并填写说明','Choose scope and enter an explanation');livePaint();return;}
  return livePost('confirm',{...liveBound(),choices:[{field:'geography',status:geography,value:geography==='specified'?geographyValue:null,reason:note,user_input:note}],formal_target:Number(document.querySelector('[data-live-target]').value),priority_reading_target:Number(document.querySelector('[data-live-priority]').value),resource_envelope:'No model or external search authorized by this scope confirmation.',budgets:{model_calls:0,seconds:0,search_calls:0,source_reads:0,rounds:0},consent:{external_search:false,public_source_read:false,browser_fallback:false},user_input:note,confirmed:true});}
 if(action==='deliver'){const offer=rt.overview.stage1.delivery.offers.find(o=>o.status==='ready-for-saved-evidence-delivery');return livePost('stage1/deliver',{...liveBound(),offer_ref:offer.offer_ref,offer_sha256:offer.offer_sha256,ledger_state_sha256:offer.ledger_state_sha256,confirmed:true});}
 if(action==='review'){if(!rt.draft.trim())return;const c=rt.atlas.stage2_input;return livePost('stage1/review-stage2-input',{...liveBound(),artifact_ref:c.artifact_ref,manifest_sha256:c.manifest_sha256,context_sha256:c.context_sha256,decision:document.querySelector('[data-live-decision]').value,user_input:rt.draft,confirmed:true});}
},true);
// Load only on this local server. No model, stage or search action runs on read.
rt.overview=null;rt.atlas=null;livePaint();
Promise.all([liveRequest('/v7-case.json'),liveRequest('/api/projects')]).then(async([meta,list])=>{rt.meta=meta;rt.list=Array.isArray(list)?list:list.projects||[];await liveRefresh(rt.pending?.ref||meta.case_ref||rt.list[0]?.project_ref);if(rt.pending)await liveRecover();}).catch(e=>{rt.error=e.message;rt.loading=false;livePaint();});
setInterval(()=>{if(document.hidden||rt.busy||rt.loading||document.activeElement?.matches('textarea,input,select'))return;const s=rt.overview?.stage1,jobs=[...Object.values(rt.overview?.models?.jobs||{}),...Object.values(s?.query_execution?.jobs||{}),...Object.values(s?.source_execution?.jobs||{})];const running=jobs.some(j=>['reserved','queued','running','dispatching','acquiring','parsing','submitted','in_progress'].includes(j.status)||['running','queued','parsing'].includes(j.followup?.status));if(running||(rt.overview?.models?.active_jobs||[]).length||(typeof realQueryPending==='function'&&realQueryPending()))liveRefresh();},10000);

function liveReason(reason){
 const map={'package-saved-review-required':['交付已保存，等待审阅','Package saved; review required'],
 'delivery-offered':['可生成已保存来源的交付','Saved sources can be delivered'],
 'scope-required':['请先确认研究范围','Confirm scope first'],'scope-recorded':['研究范围已保存','Scope saved'],
 'plan-recorded':['查询规划已保存','Plan saved'],'query-recorded':['已记录部分查询；不代表完整覆盖','Some queries recorded; coverage incomplete'],
 'reading-registration-required':['阅读登记接口未连接','Reading registration unconnected'],
 'reading-registration-unconnected':['阅读登记接口未连接','Reading registration unconnected'],
 'screening-recorded':['筛选记录已保存','Screening records saved'],
 'coverage-required':['需要完成覆盖检查','Coverage check required'],
 'plan-required':['需要查询规划；真实模型尚未连接','Planning required; live model unconnected']};
 return map[reason]?translated(apps[0],map[reason].concat(map[reason][0])):reason||'Unknown';
}
function livePhaseSummary(app,phase){
 const stage=rt.overview?.stage1,counts=stage?.ledger?.counts||{},p=rt.overview?.project;
 const lines=app.stage===2?[rl('输入来源：当前项目 Stage1 交付','Input: current project Stage1 delivery'),rl('完整 Stage2 执行尚未接通','Full Stage2 execution remains unconnected')]:{
 scope:[p?.brief?.original_description,rl('范围确认','Scope confirmed')+': '+(p?.intake_report?.necessary_clarification_complete?rl('是','Yes'):rl('否','No'))],
 planning:[rl('查询规划','Query plan')+': '+(p?.plan?rl('已保存，尚不代表执行','Saved; not execution'):rl('尚未生成','Not generated'))],
 query:[rl('已记录查询','Recorded queries')+': '+(counts.queries??'Unknown'),rl('已记录文献','Recorded works')+': '+(counts.works??'Unknown')],
 screening:[rl('筛选决定记录','Screening decisions')+': '+(counts.decisions??'Unknown')],
 reading:[rl('已保存证据主张','Saved claims')+': '+(counts.claims??'Unknown'),rl('阅读完成度：按登记状态判断；不把文件存在当成阅读完成','Reading completion requires registration, not file presence')],
 coverage:[rl('检查结论','Gate outcome')+': '+(stage?.ledger?.gate?.outcome??'Unknown'),...(stage?.ledger?.gate?.blocking_items||[])],
 delivery:[rt.atlas?rl('文献包已保存，下方结果已同步','Package saved; results synchronized'):rl('还没有生成交付结果','No delivered result yet'),rl('研究验收','Research acceptance')+': '+rl('尚未通过','Not passed')]
 }[phase]||[];
 return `<div class="live-phase-summary">${lines.map(line=>`<p>${rx(line)}</p>`).join('')}</div>`;
}
function liveModelCase(){const offer=(rt.overview?.model_offers?.offers||[]).find(o=>o.available===true);return `<div class="live-callout"><strong>${rl('仓库问答接口 case','Repository Q&A case')}</strong><p>${rl('使用仓库的合成 provider 测试待答问题、答复和保存输出；不调用真实 Codex，不消耗模型额度。启动后请在 55 秒内答复。','Uses a synthetic repository provider to test questions, replies and saved output. No live Codex or model quota. Reply within 55 seconds.')}</p><button class="hs-button" data-live-action="model-case" ${offer?liveDisabled():'disabled'}>${rl('启动离线问答案例','Start offline Q&A case')}</button></div>`;}
function liveModelOutputs(){const actions=rt.modelHistory?.actions||[];return `<details class="live-model-history" ${actions.length?'open':''}><summary>${rl('Codex 内容任务记录','Codex content task history')} · ${actions.length}</summary>${actions.map(row=>`<article class="live-detail-block"><strong>${rx(row.status)}</strong><p>${rx(row.output_preview??row.refusal??row.error??'Unknown')}</p><small>${rx(row.key)}</small></article>`).join('')}</details>`;}
