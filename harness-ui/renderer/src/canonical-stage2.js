// Read-only projection of an official saved Atlas Stage2 attachment.
// The local adapter verifies the exact payload_json SHA256 and Python-canonical
// attachment hash before calling this module. These structural checks neither
// authenticate arbitrary data nor grant execution/scientific acceptance.
function canonicalStage2Validate(payload,binding){
 const object=value=>value!==null&&typeof value==='object'&&!Array.isArray(value);
 const hash=value=>typeof value==='string'&&/^[a-f0-9]{64}$/.test(value);
 const text=value=>typeof value==='string'&&value.length>0;
 const fail=reason=>({ok:false,reason});
 if(!object(binding)||binding.kind!=='V7CanonicalSavedViewBinding'||binding.schema_version!=='1.0.0'||!text(binding.view_ref)||!/^[A-Za-z0-9_-]{1,64}$/.test(binding.view_ref)||!text(binding.project_id)||typeof binding.fixture!=='boolean'||!['index_sha256','manifest_sha256','payload_sha256'].every(k=>hash(binding[k])))return fail('canonical-stage2-view-binding-invalid');
 if(!object(payload)||!object(payload.index)||payload.index.project_id!==binding.project_id||payload.index_sha256!==binding.index_sha256)return fail('canonical-stage2-project-index-differs');
 if(payload.fixture===true&&binding.fixture!==true)return fail('canonical-stage2-fixture-binding-differs');
 if(payload.stage2==null)return fail(binding.stage2_attachment_sha256===null?'stage2-saved-result-missing':'canonical-stage2-attachment-hash-without-result');
 if(!hash(binding.stage2_attachment_sha256))return fail('canonical-stage2-attachment-hash-invalid');
 const attachment=payload.stage2,bridge=attachment?.bridge_receipt,selection=attachment?.selection,comparison=payload.stage2_comparison;
 if(!object(attachment)||attachment.kind!=='WorkspaceStage2Attachment'||attachment.schema_version!=='1.0.0'||attachment.project_id!==binding.project_id||attachment.stage1_index_sha256!==binding.index_sha256||attachment.fixture===true&&binding.fixture!==true)return fail('canonical-stage2-attachment-binding-differs');
 if(!object(bridge)||bridge.kind!=='WorkspaceStage2BridgeReceipt'||bridge.schema_version!=='1.0.0'||bridge.association!=='explicit-operator-selected-binding'||bridge.project_id!==binding.project_id||bridge.stage1_index_sha256!==binding.index_sha256||!['stage1_package_manifest_sha256','stage2_manifest_sha256','selection_sha256','brief_sha256','resources_sha256','source_snapshot_sha256','stored_packet_sha256','workflow_event_head'].every(k=>hash(bridge[k])))return fail('canonical-stage2-bridge-binding-differs');
 if(bridge.original_stage1_lineage_attested!==false||bridge.human_selection!=='pending'||bridge.stage3_authorized!==false||bridge.formal_ready!==false||bridge.improvement_demonstrated!==false)return fail('canonical-stage2-non-authority-flags-differ');
 if(binding.stage2_manifest_sha256!==undefined&&binding.stage2_manifest_sha256!==bridge.stage2_manifest_sha256)return fail('canonical-stage2-delivery-manifest-differs');
 const packet=selection?.evaluation_packet;
 if(!object(selection)||!Array.isArray(selection.current_options)||!object(packet)||!['1.0.0','2.0.0','2.1.0','2.2.0','2.3.0','2.4.0'].includes(packet.schema_version)||!object(attachment.evaluation))return fail('canonical-stage2-selection-shape-invalid');
 if(!object(comparison)||comparison.schema_version!=='1.0.0'||!['literature','directions','evidence'].every(k=>Array.isArray(comparison[k])))return fail('canonical-stage2-comparison-shape-invalid');
 const pair=(id,version)=>JSON.stringify([id,version]);
 const options=selection.current_options.map(row=>row?.candidate);
 if(options.some(row=>!object(row)||!text(row.candidate_id)||!Number.isSafeInteger(row.version)||row.version<1))return fail('canonical-stage2-candidate-version-invalid');
 const optionKeys=options.map(row=>pair(row.candidate_id,row.version));
 const directionKeys=comparison.directions.map(row=>pair(row?.candidate_id,row?.version));
 if(new Set(optionKeys).size!==optionKeys.length||new Set(directionKeys).size!==directionKeys.length||optionKeys.length!==directionKeys.length||directionKeys.some(key=>!optionKeys.includes(key)))return fail('canonical-stage2-direction-version-differs');
 if(!Array.isArray(packet.candidates)||options.some(row=>!packet.candidates.some(candidate=>candidate?.candidate_id===row.candidate_id&&candidate?.version===row.version)))return fail('canonical-stage2-packet-candidate-version-differs');
 const checkLiterature=(rows,originals)=>Array.isArray(rows)&&Array.isArray(originals)&&rows.length===originals.length&&rows.every(row=>object(row)&&text(row.work_id)&&text(row.version_id)&&originals.some(source=>source?.work_id===row.work_id&&source?.version_id===row.version_id))&&new Set(rows.map(row=>pair(row.work_id,row.version_id))).size===rows.length;
 if(!checkLiterature(comparison.literature,packet.literature??[]))return fail('canonical-stage2-literature-version-differs');
 if(comparison.supplemental_literature!==undefined&&!checkLiterature(comparison.supplemental_literature,packet.supplemental_literature??[]))return fail('canonical-stage2-supplemental-version-differs');
 const same=(a,b)=>a===b||Array.isArray(a)&&Array.isArray(b)&&a.length===b.length&&a.every((v,i)=>same(v,b[i]))||object(a)&&object(b)&&Object.keys(a).length===Object.keys(b).length&&Object.keys(a).every(k=>Object.hasOwn(b,k)&&same(a[k],b[k]));
 const originals=packet.evidence??[],fields=['evidence_id','source_id','work_id','version_id','locator','quote','evidence_level'],used=new Set();
 if(!Array.isArray(originals)||originals.length!==comparison.evidence.length)return fail('canonical-stage2-evidence-binding-differs');
 for(const row of comparison.evidence){const index=object(row)?originals.findIndex((original,i)=>object(original)&&!used.has(i)&&fields.every(key=>same(row[key]??null,original[key]??null))):-1;if(index<0)return fail('canonical-stage2-evidence-binding-differs');used.add(index);}
 return {ok:true,reason:null,payload,binding};
}

function canonicalStage2Label(app,zh,en,tw=zh){return app?.lang==='en'?en:['tw','zh-Hant','zh-TW'].includes(app?.lang)?tw:zh;}
function canonicalStage2Escape(value){return String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function canonicalStage2Value(app,value){
 if(value===undefined||value===null)return canonicalStage2Escape(canonicalStage2Label(app,'未知（Unknown）','Unknown','未知（Unknown）'));
 return canonicalStage2Escape(typeof value==='string'?(value||'""'):JSON.stringify(value));
}
// Keep references only. Closed records never stringify or recursively traverse data.
let canonicalStage2LazyRecords=new Map();
const canonicalStage2MountedRoots=new WeakSet();
function canonicalStage2Lazy(app,label,value,mode='fields'){
 const id=String(canonicalStage2LazyRecords.size);
 canonicalStage2LazyRecords.set(id,{app,value,mode});
 return `<details class="live-detail-block" data-stage2-lazy="${id}" data-stage2-mode="${mode}"><summary>${canonicalStage2Escape(label)}</summary><div data-stage2-lazy-body></div></details>`;
}
function canonicalStage2Record(app,label,value){return canonicalStage2Lazy(app,label,value,'json');}
function canonicalStage2ReadableRecord(app,label,value){return canonicalStage2Lazy(app,label,value);}
function canonicalStage2More(app,id,start){return `<button type="button" class="hs-button" data-stage2-more="${id}" data-stage2-start="${start}">${canonicalStage2Escape(canonicalStage2Label(app,'继续读取','Read more','繼續讀取'))}</button>`;}
function canonicalStage2Page(record,id,start=0){
 const {app,value,mode}=record;
 if(mode==='text'){
  const end=Math.min(start+4000,value.length);
  return `<pre class="live-record">${canonicalStage2Escape(value.slice(start,end))}</pre>${end<value.length?canonicalStage2More(app,id,end):''}`;
 }
 if(value===null||typeof value!=='object'){
  if(typeof value==='string'&&value.length>4000){const textId=String(canonicalStage2LazyRecords.size);const textRecord={app,value,mode:'text'};canonicalStage2LazyRecords.set(textId,textRecord);return canonicalStage2Page(textRecord,textId);}
  return canonicalStage2Value(app,value);
 }
 const array=Array.isArray(value),keys=array?null:Object.keys(value),length=array?value.length:keys.length,end=Math.min(start+40,length);
 if(!length)return canonicalStage2Value(app,value);
 let html='<dl>';
 for(let i=start;i<end;i++){
  const key=array?String(i+1):keys[i],item=value[array?i:key];
  const nested=item!==null&&typeof item==='object'||typeof item==='string'&&item.length>4000;
  html+=`<dt>${canonicalStage2Escape(key)}</dt><dd>${nested?canonicalStage2Lazy(app,key,item):canonicalStage2Value(app,item)}</dd>`;
 }
 return html+'</dl>'+(end<length?canonicalStage2More(app,id,end):'');
}
function canonicalStage2Expand(id){
 const record=canonicalStage2LazyRecords.get(String(id));if(!record)return '';
 if(record.mode==='text')return canonicalStage2Page(record,String(id));
 if(record.mode==='json'){
  // Only a deliberate expansion constructs complete original JSON.
  const value=record.value===undefined?'Unknown':JSON.stringify(record.value,null,2);
  const textId=String(canonicalStage2LazyRecords.size),textRecord={app:record.app,value,mode:'text'};
  canonicalStage2LazyRecords.set(textId,textRecord);return canonicalStage2Page(textRecord,textId);
 }
 return canonicalStage2Page(record,String(id))+canonicalStage2Record(record.app,canonicalStage2Label(record.app,'原始保存 JSON','Original saved JSON','原始保存 JSON'),record.value);
}
function canonicalStage2Fields(app,value){return canonicalStage2ReadableRecord(app,canonicalStage2Label(app,'逐字段读取','Read fields','逐欄位讀取'),value);}
function canonicalStage2Mount(root){
 if(!root||canonicalStage2MountedRoots.has(root))return;canonicalStage2MountedRoots.add(root);
 root.addEventListener('toggle',event=>{
  const node=event.target;if(!node?.matches?.('[data-stage2-lazy]')||!node.open||node.dataset.stage2Loaded)return;
  const body=node.querySelector(':scope > [data-stage2-lazy-body]');if(!body)return;
  body.innerHTML=canonicalStage2Expand(node.dataset.stage2Lazy);node.dataset.stage2Loaded='true';
 },true);
 root.addEventListener('change',canonicalStage2WorkbenchEvent);
 root.addEventListener('click',event=>{
  if(canonicalStage2WorkbenchEvent(event))return;
  const button=event.target.closest?.('[data-stage2-more]');if(!button)return;
  const record=canonicalStage2LazyRecords.get(button.dataset.stage2More);if(!record)return;
  event.preventDefault();button.outerHTML=canonicalStage2Page(record,button.dataset.stage2More,Number(button.dataset.stage2Start));
 });
}

function canonicalStage2SavedRecordsRender(app,validated){
 canonicalStage2LazyRecords=new Map();
 const checked=validated?.ok===true?canonicalStage2Validate(validated.payload,validated.binding):validated;
 const label=(zh,en,tw=zh)=>canonicalStage2Label(app,zh,en,tw),show=value=>canonicalStage2Value(app,value);
 if(checked?.ok!==true){const missing=checked?.reason==='stage2-saved-result-missing';return `<section class="hs-panel lp-empty" data-canonical-stage2-unavailable><h2>${label(missing?'Stage2 结果：尚未生成':'Stage2 保存结果暂不可用',missing?'Stage2 result: not generated':'Saved Stage2 result unavailable',missing?'Stage2 結果：尚未產生':'Stage2 保存結果暫不可用')}</h2><p>${label('仅显示当前已绑定的保存结果；不会使用示例数据补齐。','Only bound saved results are displayed; no example data is substituted.','僅顯示目前已綁定的保存結果；不會使用示例資料補齊。')}</p><pre class="live-record">${show(checked?.reason)}</pre></section>`;}
 const {payload,binding}=checked,attachment=payload.stage2,view=payload.stage2_comparison,bridge=attachment.bridge_receipt;
 const selection=attachment.selection,packet=selection.evaluation_packet,tables=view.research_tables;
 const count=value=>Array.isArray(value)?value.length:null;
 const counts=`<dl data-canonical-stage2-counts><dt>${label('推荐数（selection.recommendations）','Recommendations (selection.recommendations)','推薦數（selection.recommendations）')}</dt><dd data-stage2-recommendations-count>${show(count(selection.recommendations))}</dd><dt>${label('文献数（主表）','Literature count (main table)','文獻數（主表）')}</dt><dd data-stage2-literature-count>${show(count(view.literature))}</dd><dt>${label('已记录比较格数（research_tables.cells）','Recorded comparison cells (research_tables.cells)','已記錄比較格數（research_tables.cells）')}</dt><dd data-stage2-comparison-cell-count>${show(count(tables?.cells))}</dd></dl>`;
 const fullRecords=`<section class="hs-panel" data-stage2-full-records><h2>${label('完整选择、评估与历史记录','Complete selection, assessment & history records','完整選擇、評估與歷史紀錄')}</h2><p>${label('按保存字段原样阅读版本、评语与历史；未提供的字段为 Unknown，不重建历史。','Read versions, comments and history exactly as saved; absent fields remain Unknown and history is not reconstructed.','按保存欄位原樣閱讀版本、評語與歷史；未提供的欄位為 Unknown，不重建歷史。')}</p>${canonicalStage2ReadableRecord(app,label('完整 selection（含保存的版本、评语与历史）','Complete selection (including saved versions, comments & history)','完整 selection（含保存的版本、評語與歷史）'),selection)}${canonicalStage2ReadableRecord(app,label('完整 evaluation_packet','Complete evaluation_packet','完整 evaluation_packet'),packet)}${canonicalStage2ReadableRecord(app,label('完整独立 evaluation','Complete independent evaluation','完整獨立 evaluation'),attachment.evaluation)}</section>`;
 const fullComparison=`<details class="live-detail-block" data-stage2-full-comparison><summary>${label('全部比较维度与逐格记录','All comparison dimensions & cell records','全部比較維度與逐格紀錄')}</summary>${canonicalStage2ReadableRecord(app,label('维度定义（dimensions）','Dimension definitions (dimensions)','維度定義（dimensions）'),tables?.dimensions)}<div data-stage2-comparison-cells>${canonicalStage2ReadableRecord(app,label('全部已记录比较格（cells）','All recorded comparison cells (cells)','全部已記錄比較格（cells）'),tables?.cells)}</div>${canonicalStage2ReadableRecord(app,label('完整比较表与资源记录','Complete comparison tables & resource records','完整比較表與資源紀錄'),tables)}</details>`;
 const cell=(row,key)=>show(row?.cells?.[key]?.text);
 const evidenceLinks=ids=>Array.isArray(ids)?ids.map(id=>`<a href="#canonical-stage2-evidence-${encodeURIComponent(String(id))}">${show(id)}</a>`).join(' · '):show(null);
 const directions=view.directions.map(direction=>`<article class="hs-panel" data-canonical-direction><div class="hs-panel-head"><div><small>${show(direction.candidate_id)} · v${show(direction.version)}</small><h3>${show(direction.question)}</h3></div><span class="hs-status">${show(direction.disposition)}</span></div><dl><dt>${label('研究机会','Opportunity','研究機會')}</dt><dd>${show(direction.opportunity)}</dd><dt>${label('研究价值','Value','研究價值')}</dt><dd>${show(direction.value)}</dd><dt>${label('方法与路径','Approach','方法與路徑')}</dt><dd>${show(direction.approach)}</dd><dt>${label('必要材料与条件','Requirements','必要材料與條件')}</dt><dd>${show(direction.requirements)}</dd><dt>${label('限制与未解决项','Limitations & unresolved items','限制與未解決項')}</dt><dd>${show(direction.limitations)}</dd><dt>${label('处置理由','Disposition reason','處置理由')}</dt><dd>${show(direction.reason)}</dd><dt>${label('下一项检查','Next check','下一項檢查')}</dt><dd>${show(direction.next_step)}</dd><dt>${label('关联证据','Linked evidence','關聯證據')}</dt><dd>${evidenceLinks(direction.evidence_ids)}</dd></dl>${canonicalStage2Record(app,label('查看保存的方向审查','Inspect saved direction checks','查看保存的方向審查'),direction.checks)}</article>`).join('');
 const literature=rows=>`<div class="live-table-scroll"><table class="live-table"><thead><tr>${[label('文献与版本','Work & version','文獻與版本'),label('问题','Question','問題'),label('方法','Method'),label('发现','Findings','發現'),label('限制','Limitations')].map(text=>`<th>${canonicalStage2Escape(text)}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>`<tr><td><strong>${show(row.title)}</strong><p><small>${show(row.work_id)} · ${show(row.version_id)} · ${show(row.evidence_level)}</small></p>${canonicalStage2ReadableRecord(app,label('全部文献字段与比较维度','All literature fields & comparison dimensions','全部文獻欄位與比較維度'),row)}</td><td>${cell(row,'question')}</td><td>${cell(row,'method')}</td><td>${cell(row,'findings')}</td><td>${cell(row,'limitations')}</td></tr>`).join('')}</tbody></table></div>`;
 const evidence=view.evidence.map(row=>`<details class="live-detail-block" id="canonical-stage2-evidence-${encodeURIComponent(String(row.evidence_id))}"><summary>${show(row.evidence_id)} · ${show(row.work_id)} · ${show(row.version_id)}</summary><p>${label('来源','Source','來源')}: ${show(row.source_id)} · ${show(row.evidence_level)}</p><p>${label('定位','Locator')}: ${show(row.locator)}</p><blockquote>${show(row.quote)}</blockquote></details>`).join('');
 const notice=binding.fixture?label('合成案例 · 仅展示接口与保存内容，不是研究结论。','Synthetic case · interface and saved-content demonstration, not research findings.','合成案例 · 僅展示介面與保存內容，不是研究結論。'):label('已保存 Stage2 内容 · 实际状态以原始记录为准。','Saved Stage2 content · actual status follows the original records.','已保存 Stage2 內容 · 實際狀態以原始紀錄為準。');
 const bindingView=Object.fromEntries(['kind','schema_version','view_ref','project_id','index_sha256','manifest_sha256','payload_sha256','stage2_attachment_sha256','fixture'].map(key=>[key,binding[key]]));
 return `<section data-canonical-stage2 data-canonical-fixture="${binding.fixture}"><section class="hs-panel"><div class="hs-panel-head"><div><h2>${label('Stage2 · 研究方向与文献比较','Stage2 · research directions & literature comparison','Stage2 · 研究方向與文獻比較')}</h2><p>${notice}</p></div><span class="hs-status">${view.directions.length} ${label('个保存方向','saved directions','個保存方向')}</span></div><p>${label('原生运行、人工选择和阶段完成分别判断；此视图只读，不授予下一阶段权限。','Native execution, human selection and stage completion are separate. This read-only view grants no next-stage permission.','原生執行、人工選擇和階段完成分別判斷；此檢視唯讀，不授予下一階段權限。')}</p><p>${label('独立评估记录状态','Independent assessment record','獨立評估紀錄狀態')}: ${show(attachment.evaluation.evaluation_status)} · ${label('人工选择','Human choice','人工選擇')}: ${show(bridge.human_selection)}</p><p>${label('与 Stage1 的关联','Association with Stage1','與 Stage1 的關聯')}: ${label('操作者明确选择的阅读关联；未据此证明原始运行血缘。','Explicit operator-selected reading association; original execution lineage is not attested by it.','操作者明確選擇的閱讀關聯；未據此證明原始執行血緣。')}</p>${counts}${canonicalStage2Record(app,label('版本、来源与绑定','Versions, provenance & bindings','版本、來源與綁定'),{binding:bindingView,bridge_receipt:bridge,packet_schema_version:attachment.selection.evaluation_packet.schema_version})}</section>${fullRecords}<section><h2>${label('已保存研究方向','Saved research directions','已保存研究方向')}</h2>${directions||`<section class="hs-panel"><p>${label('当前保存记录未记录方向；推荐数以 selection.recommendations 保存字段为准。','No directions are recorded in this saved result; the recommendation count follows the saved selection.recommendations field.','目前保存紀錄未記錄方向；推薦數以 selection.recommendations 保存欄位為準。')}</p></section>`}</section><section class="hs-panel"><h2>${label('文献比较','Literature comparison','文獻比較')}</h2><p>${show(view.comparison)}</p>${literature(view.literature)}${fullComparison}${canonicalStage2Record(app,label('比较表与资源','Comparison tables & resources','比較表與資源'),{resources:view.resources,research_tables:view.research_tables})}${Array.isArray(view.supplemental_literature)?`<details><summary>${label('补充来源版本','Supplemental source versions','補充來源版本')} · ${view.supplemental_literature.length}</summary>${literature(view.supplemental_literature)}</details>`:''}</section><section class="hs-panel"><h2>${label('证据与来源限制','Evidence & source limitations','證據與來源限制')}</h2>${evidence||`<p>${label('未记录可展示的证据条目。','No displayable evidence entries are recorded.','未記錄可展示的證據條目。')}</p>`}${view.prior_work_reviews!==undefined?canonicalStage2Record(app,label('已有研究定位记录','Prior-work review records','已有研究定位紀錄'),{prior_work_reviews:view.prior_work_reviews,source_levels:view.prior_work_source_levels}):''}${canonicalStage2Record(app,label('独立评估与原始评语','Independent assessment & original comments','獨立評估與原始評語'),attachment.evaluation)}</section></section>`;
}

// Small read-only projection into the retained V7 workbench components.
const canonicalStage2Workbenches=new Map();
function canonicalStage2WorkKey(row){return JSON.stringify([row?.work_id,row?.version_id]);}
function canonicalStage2WorkbenchData(state){
 const view=state.checked.payload.stage2_comparison;
 const literature=view.literature.filter(row=>state.selected.has(canonicalStage2WorkKey(row)));
 const keys=new Set(literature.map(canonicalStage2WorkKey));
 const evidence=view.evidence.filter(row=>keys.has(canonicalStage2WorkKey(row)));
 const links=[];
 for(const direction of view.directions){for(const id of Array.isArray(direction.evidence_ids)?direction.evidence_ids:[]){for(const row of evidence.filter(row=>row.evidence_id===id))links.push({direction,evidence:row});}}
 const tables=view.research_tables;
 const cells=Array.isArray(tables?.cells)?tables.cells.filter(row=>keys.has(canonicalStage2WorkKey(row))):null;
 const numeric=(cells||[]).filter(row=>typeof row.value==='number'&&Number.isFinite(row.value));
 return {view,literature,evidence,links,tables,cells,numeric};
}
function canonicalStage2WorkbenchBody(state){
 const {app}=state,{view,literature,evidence,links,tables,cells,numeric}=canonicalStage2WorkbenchData(state);
 const label=(zh,en,tw=zh)=>canonicalStage2Label(app,zh,en,tw),show=value=>canonicalStage2Value(app,value);
 const missing=label('Unknown · 尚未提供','Unknown · not supplied','Unknown · 尚未提供');
 const picker=`<details class="wb-picker" open><summary>${label('已选文献','Selected literature','已選文獻')} · ${literature.length}/${view.literature.length}</summary><div class="wb-check-grid">${view.literature.map(row=>`<label><input type="checkbox" data-stage2-wb-paper="${encodeURIComponent(canonicalStage2WorkKey(row))}" ${state.selected.has(canonicalStage2WorkKey(row))?'checked':''}><span><strong>${show(row.title)}</strong><small>${show(row.work_id)} · ${show(row.version_id)}</small></span></label>`).join('')}</div></details>`;
 const tabs=`<div class="wb-workbench-tabs" role="group">${[['comparison',label('文献比较','Literature comparison','文獻比較')],['relations',label('文献关系','Literature relationships','文獻關係')],['routes',label('路线匹配','Route matching','路線匹配')]].map(([key,name])=>`<button type="button" class="hs-button cursor-interaction" data-stage2-wb-tab="${key}" aria-pressed="${state.tab===key}">${name}</button>`).join('')}</div>`;
 let body='';
 if(state.tab==='comparison')body=`<div class="live-table-scroll"><table class="live-table"><thead><tr>${[label('文献与版本','Work & version','文獻與版本'),label('问题','Question','問題'),label('方法','Method'),label('发现','Findings','發現'),label('限制','Limitations')].map(text=>`<th>${text}</th>`).join('')}</tr></thead><tbody>${literature.map(row=>`<tr data-stage2-wb-comparison-row><td>${show(row.title)}<small>${show(row.work_id)} · ${show(row.version_id)}</small></td>${['question','method','findings','limitations'].map(key=>`<td>${show(row.cells?.[key]?.text)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>${literature.length?'':`<p class="wb-comparison-note">${label('未选择文献。','No literature selected.','未選擇文獻。')}</p>`}`;
 if(state.tab==='relations')body=`<p class="wb-comparison-note">${label('文献间引用、继承或冲突关系：Unknown · 当前保存契约未提供明确关系，不能以共同标签推断。','Paper-to-paper citation, inheritance or conflict: Unknown. This saved contract supplies no explicit paper relationships; shared tags do not establish them.','文獻間引用、繼承或衝突關係：Unknown · 目前保存契約未提供明確關係，不能以共同標籤推斷。')}</p><div class="wb-edge-list">${evidence.map(row=>`<article class="wb-route-context" data-stage2-wb-evidence><strong>${show(row.work_id)} · ${show(row.version_id)} → ${show(row.evidence_id)}</strong><p>${show(row.locator)}</p><blockquote>${show(row.quote)}</blockquote><small>${show(row.source_id)} · ${show(row.evidence_level)}</small></article>`).join('')||`<p>${missing}</p>`}</div>`;
 if(state.tab==='routes')body=`<p class="wb-comparison-note">${label('只显示保存的 candidate.evidence_ids 与文献/版本明确绑定；不是匹配分数、推荐或执行许可。','Only saved candidate.evidence_ids bound to a work/version are shown; these links are not match scores, recommendations or execution permission.','只顯示保存的 candidate.evidence_ids 與文獻/版本明確綁定；不是匹配分數、推薦或執行許可。')}</p>${links.map(({direction,evidence:ev})=>`<div class="wb-route-context" data-stage2-wb-route><div class="hs-s2-columns"><div class="hs-s2-col"><span>${label('文献','Literature','文獻')}</span><div class="hs-s2-node">${show(ev.work_id)}<small>${show(ev.version_id)}</small></div></div><div class="hs-s2-col"><span>→ ${label('证据','Evidence','證據')}</span><div class="hs-s2-node">${show(ev.evidence_id)}<small>${show(ev.locator)}</small></div></div><div class="hs-s2-col"><span>→ ${label('路线','Route','路線')}</span><div class="hs-s2-node" data-kind="route">${show(direction.candidate_id)} · v${show(direction.version)}<small>${show(direction.question)}</small></div></div><div class="hs-s2-col"><span>→ ${label('保存处置','Saved disposition','保存處置')}</span><div class="hs-s2-node" data-kind="gap">${show(direction.disposition)}<small>${show(direction.reason)}</small></div></div></div></div>`).join('')||`<p class="wb-comparison-note">${missing}</p>`}`;
 const metrics=`<details class="wb-picker" data-stage2-wb-metrics><summary>${label('指标与数据','Metrics & data','指標與資料')} · ${cells===null?show(null):cells.length}</summary><p>${label('仅列出保存的比较数据；保留 true、false 和 Unknown。单位、条件与可比性未核实时，不绘制数值图或排名。','Recorded comparison data only; true, false and Unknown are preserved. Numeric charts and ranking require established units, conditions and comparability.','僅列出保存的比較資料；保留 true、false 和 Unknown。單位、條件與可比性未核實時，不繪製數值圖或排名。')}</p>${cells?.length?`<div class="live-table-scroll"><table class="live-table"><thead><tr><th>work / version</th><th>dimension</th><th>value</th><th>status</th><th>evidence / reason</th></tr></thead><tbody>${cells.map(row=>{const dimension=Array.isArray(tables?.dimensions)?tables.dimensions.find(d=>d.dimension_id===row.dimension_id):null;return `<tr><td>${show(row.work_id)} · ${show(row.version_id)}</td><td>${show(dimension?.label)} · ${show(row.dimension_id)}<small>${show(dimension?.definition)} · ${show(dimension?.conditions)}</small></td><td>${show(row.value)}</td><td>${show(row.status)}</td><td>${show(row.evidence_ids)} · ${show(row.reason)}</td></tr>`;}).join('')}</tbody></table></div>`:`<p>${missing}</p>`}</details>`;
 return `<div class="hs-panel-head"><h2>${label('研究比较工作台','Research comparison workbench','研究比較工作臺')}</h2><span class="hs-status">${state.checked.binding.fixture?label('合成案例','Synthetic case','合成案例'):label('保存记录','Saved records','保存紀錄')}</span></div>${picker}${tabs}<div data-stage2-wb-content="${state.tab}">${body}</div>${metrics}`;
}
function canonicalStage2WorkbenchEvent(event){
 const target=event.target.closest?.('[data-stage2-wb-tab],[data-stage2-wb-paper]');if(!target?.hasAttribute?.('data-stage2-wb-tab')&&!target?.hasAttribute?.('data-stage2-wb-paper'))return false;
 const panel=target.closest('[data-stage2-workbench]'),state=canonicalStage2Workbenches.get(panel?.dataset.stage2Workbench);if(!state)return false;
 if(target.hasAttribute('data-stage2-wb-tab')){if(event.type!=='click'||!['comparison','relations','routes'].includes(target.dataset.stage2WbTab))return false;event.preventDefault();state.tab=target.dataset.stage2WbTab;}
 else {if(event.type!=='change')return false;const key=decodeURIComponent(target.dataset.stage2WbPaper);if(target.checked)state.selected.add(key);else state.selected.delete(key);}
 panel.innerHTML=canonicalStage2WorkbenchBody(state);return true;
}
function canonicalStage2Render(app,validated){
 const original=canonicalStage2SavedRecordsRender(app,validated),checked=validated?.ok===true?canonicalStage2Validate(validated.payload,validated.binding):validated;
 if(checked?.ok!==true)return original;
 const key=checked.binding.project_id+':'+checked.binding.payload_sha256;
 let state=canonicalStage2Workbenches.get(key);
 if(!state){state={tab:'comparison',selected:new Set(checked.payload.stage2_comparison.literature.map(canonicalStage2WorkKey))};canonicalStage2Workbenches.set(key,state);while(canonicalStage2Workbenches.size>8)canonicalStage2Workbenches.delete(canonicalStage2Workbenches.keys().next().value);}
 state.app=app;state.checked=checked;
 return `<section class="hs-panel" data-stage2-workbench="${canonicalStage2Escape(key)}">${canonicalStage2WorkbenchBody(state)}</section><details data-stage2-original-records><summary>${canonicalStage2Label(app,'完整保存结果、版本与评估','Complete saved results, versions & assessment','完整保存結果、版本與評估')}</summary>${original}</details>`;
}
