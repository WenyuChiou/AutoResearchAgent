// Isolated reader for the received natural-request Stage2 delivery. GET only.
const n2Ref=null,n2OldStage2=stage2,n2OldAfter=v7AfterRender;
const n2={meta:null,model:null,loading:false,error:null,view:'papers',papers:[],routes:[],evidence:null,records:new Map(),raw:null,document:null,documents:new Map(),pending:new Set(),errors:new Map(),filePage:0,search:'',draft:null,note:'',draftStatus:'not-saved'};
let n2Active=()=>rt.ref===n2Ref; const n2Array=value=>Array.isArray(value)?value:[];
const n2Views={papers:['文献对比','Literature comparison','文獻對比'],routes:['方向与路线','Directions & routes','方向與路線'],evidence:['证据关系','Evidence relationships','證據關係']};
function n2Same(a,b){return a===b||Array.isArray(a)&&Array.isArray(b)&&a.length===b.length&&a.every((v,i)=>n2Same(v,b[i]))||a!==null&&b!==null&&typeof a==='object'&&typeof b==='object'&&!Array.isArray(a)&&!Array.isArray(b)&&Object.keys(a).length===Object.keys(b).length&&Object.keys(a).every(k=>Object.hasOwn(b,k)&&n2Same(a[k],b[k]));}
function n2CardFields(text){const lines=String(text||'').split(/\r?\n/),fields={};for(const line of lines){const match=line.match(/^\s*-\s+([^:]+):\s*(.*)$/);if(match)fields[match[1].trim().toLowerCase()]=match[2].trim();}const section=name=>{const heading=new RegExp('^##\\s+'+(name==='Verbatim excerpts'?'Verbatim excerpts?':name)+(name==='Verbatim excerpts'?'(?:\\s+.*)?':'')+'\\s*$','i'),start=lines.findIndex(line=>heading.test(line));if(start<0)return null;let end=start+1;while(end<lines.length&&!/^#{1,2}\s/.test(lines[end]))end++;return lines.slice(start+1,end).join('\n').trim()||null;};return {fields,excerpts:section('Verbatim excerpts'),notes:section('Notes')};}
function n2BuildModel(packet,selection,cards){
 if(packet?.kind!=='Stage2Packet'||!Array.isArray(packet.sources)||!Array.isArray(packet.candidates)||!Array.isArray(packet.evidence)||(selection&&(!Array.isArray(selection.current_options)||!n2Same(packet,selection.evaluation_packet))))throw Error('natural-stage2-selection-packet-differs');
 if(new Set(packet.sources.map(s=>s.source_id)).size!==packet.sources.length||cards.length!==packet.sources.length||new Set(cards.map(s=>s.source_id)).size!==cards.length)throw Error('natural-stage2-source-membership-differs');
 const sources=packet.sources.map(source=>{
  const card=cards.find(c=>c.source_id===source.source_id);
  if(!card||card.work_id!==source.work_id||card.version_id!==source.version_id||card.evidence_level!==source.evidence_level||card.artifact?.sha256!==source.sha256)throw Error('natural-stage2-source-version-differs');
  const parsed=n2CardFields(card.saved_text),fields=parsed.fields;
  // Plain excerpts need not repeat the packet's structured bibliography.
  // Use it only when one record matches the exact work, version and source.
  const matches=n2Array(packet.literature).filter(work=>work?.work_id===source.work_id&&work?.version_id===source.version_id&&n2Array(work?.source_ids).includes(source.source_id));
  const work=matches.length===1?matches[0]:{};
  const supplied=value=>typeof value==='string'&&value.trim().length>0||Array.isArray(value)&&value.length>0&&value.every(item=>typeof item==='string'&&item.trim().length>0);
  if(!supplied(fields.url))fields.url=[card.url,source.final_url,source.source_url,work.url].find(supplied)||null;
  if(!supplied(fields.doi)&&supplied(work.doi))fields.doi=work.doi;
  const title=[card.title!==source.source_id?card.title:null,fields.title,work.title].find(supplied)||source.source_id;
  const authors=[card.authors,fields.authors,fields.author,fields['author/issuer'],work.authors].find(supplied)||null;
  return {...source,card,parsed,title,authors};
 });
 const sourceById=new Map(sources.map(s=>[s.source_id,s])),evidenceById=new Map(packet.evidence.map(e=>[e.evidence_id,e]));if(evidenceById.size!==packet.evidence.length)throw Error('natural-stage2-evidence-duplicate');
 const exact=e=>e&&sourceById.get(e.source_id)?.work_id===e.work_id&&sourceById.get(e.source_id)?.version_id===e.version_id;
 const options=selection?.current_options||packet.candidates.map(candidate=>({candidate,assessment:null}));
 const routes=options.map(option=>{const candidate=packet.candidates.find(c=>c.candidate_id===option.candidate?.candidate_id&&c.version===option.candidate?.version);if(!candidate||!n2Same(candidate,option.candidate))throw Error('natural-stage2-candidate-version-differs');const references=n2Array(candidate.evidence_ids).map(id=>({id,evidence:evidenceById.get(id)||null})),bound=references.filter(r=>exact(r.evidence));return {candidate,assessment:option.assessment||null,references,bound,sourceIds:[...new Set(bound.map(r=>r.evidence.source_id))]};});
 return {packet,selection:selection||{kind:'V9UnassessedInputProjection',status:'input-only',current_options:options},sources,sourceById,evidenceById,routes,levels:Object.fromEntries([...new Set(sources.map(s=>s.evidence_level))].map(level=>[level,sources.filter(s=>s.evidence_level===level).length]))};
}
async function n2Load(){}
function n2Limit(text){return (text.match(/[\u3400-\u9fff]/g)||[]).length/Math.max(text.length,1)>.25?90:180;}
function n2Short(value,limit){const text=String(value??'Unknown'),max=limit??n2Limit(text);return text.length>max?text.slice(0,max)+'…':text;}
function n2Text(value){const text=value===null||value===undefined?'Unknown':Array.isArray(value)?value.join('\n'):typeof value==='string'?value:JSON.stringify(value,null,2),limit=n2Limit(text);return text.length>limit?`<details class="n2-long"><summary>${rx(n2Short(text,limit))}</summary><div class="n2-original">${rx(text)}</div></details>`:`<div class="n2-original">${rx(text)}</div>`;}
function n2SafeUrl(value){try{const url=new URL(value);return ['http:','https:'].includes(url.protocol)&&!url.username&&!url.password?url.href:null;}catch{return null;}}
function n2Doi(value){if(typeof value!=='string')return null;const doi=value.trim().replace(/^https?:\/\/(?:dx\.)?doi\.org\//i,'');return /^10\.\d{4,9}\/\S+$/i.test(doi)?'https://doi.org/'+doi.split('/').map(encodeURIComponent).join('/'):null;}
function n2Link(value,label){const url=n2SafeUrl(value);return url?`<a href="${rx(url)}" target="_blank" rel="noopener noreferrer">${rx(label||value)}</a>`:'Unknown';}
function n2Record(label,value){const id=String(n2.records.size);n2.records.set(id,{label,value});return `<button class="hs-button n2-record" data-n2-record="${id}">${rx(label)}</button>`;}
function n2Table(objects,rows){return `<div class="n2-table-scroll" tabindex="0" aria-label="${rl('可横向滚动的对照表','Horizontally scrollable comparison table','可橫向捲動的對照表')}"><table class="n2-table"><thead><tr><th scope="col">${rl('对照维度','Compare','對照維度')}</th>${objects.map(o=>`<th scope="col"><span>${rx(n2Short(o.title,90))}</span>${o.subtitle?`<small>${rx(o.subtitle)}</small>`:''}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>`<tr><th scope="row">${rx(row.label)}</th>${objects.map(o=>`<td>${row.cell(o)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;}
function n2EvidenceLinks(evidence){return evidence.length?evidence.map(e=>`<button class="hs-button n2-evidence-link" data-n2-evidence="${rx(e.evidence_id)}">${rx(e.evidence_id)} · ${rx(e.source_id)}</button>`).join(''):'Unknown';}
function n2SourceEvidence(source){return n2.model.packet.evidence.filter(e=>e.source_id===source.source_id&&e.work_id===source.work_id&&e.version_id===source.version_id);}
function n2Picker(kind){const sources=kind==='sources',items=sources?n2.model.sources.map(s=>({id:s.source_id,title:s.title,sub:s.evidence_level})):n2.model.routes.map(r=>({id:r.candidate.candidate_id,title:n9RoutePreview(r,'candidate.question',160),sub:r.assessment?.disposition??'Unknown'})),selected=sources?n2.papers:n2.routes;return `<details class="n2-picker" ${selected.length<2?'open':''}><summary>${rl('选择2–3个对象并排对照','Choose 2–3 objects to compare','選擇2–3個對象並排對照')} · ${selected.length} / ${items.length}</summary><div class="n2-picker-list">${items.map(item=>`<label><input type="checkbox" value="${rx(item.id)}" data-n2-select="${kind}" ${selected.includes(item.id)?'checked':''}><span>${rx(item.title||item.id)}<small>${rx(item.id)} · ${rx(item.sub)}</small></span></label>`).join('')}</div></details>`;}
function n2Papers(){const selected=n2.model.sources.filter(s=>n2.papers.includes(s.source_id)),objects=selected.map(source=>({id:source.source_id,title:source.title,subtitle:source.source_id+' · '+source.evidence_level,source}));return `${n2Picker('sources')}<p class="n2-hint">${rl('这里比较原始来源卡，含论文、官方报告和数据指南；不是统一的全文论文表。未提供的研究问题／方法／实验指标保持Unknown。','These saved source cards include papers, official reports and data guides, not a uniform full-paper table. Missing questions / methods / experimental metrics remain Unknown.','此處比較原始來源卡，含論文、官方報告與資料指南；不是統一全文論文表。未提供的研究問題／方法／實驗指標維持Unknown。')}</p>${objects.length?n2Table(objects,[{label:rl('作者／机构','Authors / issuer','作者／機構'),cell:o=>n2Text(o.source.authors)},{label:rl('阅读层级（原记录）','Evidence level (saved)','閱讀層級（原紀錄）'),cell:o=>`<strong>${rx(o.source.evidence_level)}</strong>${n2Text(o.source.parsed.fields['evidence level'])}`},{label:rl('本报告中的用途（原卡）','Role in report (source card)','本報告中的用途（原卡）'),cell:o=>n2Text(o.source.parsed.fields.role)},{label:rl('来源卡说明与限制','Source-card notes & limits','來源卡說明與限制'),cell:o=>n2Text(o.source.parsed.notes)},{label:rl('原文摘录／保存证据','Verbatim excerpts / saved evidence','原文摘錄／保存證據'),cell:o=>`${n2Text(o.source.parsed.excerpts)}${n2EvidenceLinks(n2SourceEvidence(o.source))}`},{label:rl('题名、访问与版本','Title, access & version','題名、存取與版本'),cell:o=>`${n2Doi(o.source.card.parsed?.doi||o.source.parsed.fields.doi)?`DOI: ${n2Link(n2Doi(o.source.card.parsed?.doi||o.source.parsed.fields.doi),o.source.card.parsed?.doi||o.source.parsed.fields.doi)}<br>`:''}${n2Link(o.source.card.url||o.source.parsed.fields.url,rl('打开来源页','Open source page','開啟來源頁'))}${o.source.card.pdf||o.source.parsed.fields.pdf?`<br>${n2Link(o.source.card.pdf||o.source.parsed.fields.pdf,'PDF')}`:''}${n2Text(o.source.version_id)}${n2Record(rl('完整来源卡','Full source card','完整來源卡'),o.source.card.saved_text)}`},{label:rl('未提供的结构化论文字段','Unavailable structured paper fields','未提供的結構化論文欄位'),cell:()=>`<details><summary>Unknown</summary>${n2Text({research_question:'Unknown',data_and_sample:'Unknown',method:'Unknown',quantitative_metrics:'Unknown',experimental_conditions:'Unknown'})}</details>`}]):`<p>${rl('请先选择文献／资料。','Choose literature / source materials first.','請先選擇文獻／資料。')}</p>`}<details class="n2-secondary"><summary>${rl('Metric与可比条件','Metrics & comparable conditions','Metric與可比條件')}</summary><p>${rl('来源卡未提供统一的metric／值／单位／数据集／协议表，不能从摘录抓数字排名。不同层级材料为not directly comparable／Unknown。报告评分在“方向与路线”的次级评审区单列。','No shared metric / value / unit / dataset / protocol table is supplied. Numbers are not scraped from excerpts for ranking. Materials at different evidence levels remain not directly comparable / Unknown. Report scores are separate under Directions & routes.','來源卡未提供統一metric／值／單位／資料集／協定表，不從摘錄擷取數字排名。不同層級材料維持not directly comparable／Unknown。報告評分於「方向與路線」次級評審區單列。')}</p></details>`;}
function n2Routes(){const routes=n2.model.routes.filter(r=>n2.routes.includes(r.candidate.candidate_id)),objects=routes.map(route=>({id:route.candidate.candidate_id,title:route.candidate.candidate_id,subtitle:'v'+route.candidate.version+' · '+n2Short(route.candidate.question,52),route})),fields=[['question',rl('研究问题','Research question','研究問題')],['approach',rl('研究路线／比较基线','Approach / baselines','研究路線／比較基線')],['value',rl('研究价值（原记录）','Research value (saved)','研究價值（原紀錄）')],['opportunity',rl('原报告提出的Gap','Proposed gap (saved)','原報告提出的Gap')],['requirements',rl('需要的资料与工具','Required data & tools','所需資料與工具')],['limitations',rl('风险与限制','Risks & limitations','風險與限制')]];return `${n2Picker('routes')}${objects.length?n2Table(objects,[{label:rl('作者判断（非真人选案）','Author assessment (not a human choice)','作者判斷（非真人選案）'),cell:o=>`<strong class="n2-disposition n2-${rx(o.route.assessment?.disposition||'unknown')}">${rx(o.route.assessment?.disposition??'Unknown')}</strong><details><summary>${rl('理由与下一步','Reason & next step','理由與下一步')}</summary>${n2Text(o.route.assessment?.reason)}${n2Text(o.route.assessment?.next_step)}${n2Record(rl('完整作者检查','Full author checks','完整作者檢查'),o.route.assessment)}</details>`},{label:rl('来源依据','Source basis','來源依據'),cell:o=>`${o.route.bound.length} ${rl('条精确版本引用','exact-version references','條精確版本引用')} · ${o.route.sourceIds.length} ${rl('项来源资料','source materials','項來源資料')}${n2EvidenceLinks(o.route.bound.map(r=>r.evidence))}`},{label:rl('待审草稿（仅本地）','Review draft (local only)','待審草稿（僅本地）'),cell:o=>`<label><input type="radio" name="n2-draft" data-n2-draft="${rx(o.id)}" ${n2.draft===o.id?'checked':''}>${rl('标记待审','Mark for review','標記待審')}</label>`},...fields.map(([key,label])=>({label,cell:o=>n2Text(o.route.candidate[key])})),{label:rl('原始候选','Original candidate','原始候選'),cell:o=>n2Record(rl('完整候选与版本','Full candidate & version','完整候選與版本'),o.route.candidate)}]):'<p>Unknown</p>'}${n2Draft()}${n2Gap(routes)}${n2ReviewMetrics()}`;}
function n2Gap(routes){const objects=routes.map(route=>({id:route.candidate.candidate_id,title:route.candidate.candidate_id,route})),keys=[...new Set(routes.flatMap(r=>Object.keys(r.assessment?.checks||{})))];return `<details class="n2-secondary"><summary>${rl('Gap、执行条件与缺失项','Gaps, execution conditions & missing items','Gap、執行條件與缺失項')}</summary>${objects.length?n2Table(objects,keys.map(key=>({label:key,cell:o=>{const check=o.route.assessment?.checks?.[key];return check?`${n2Text(check.status)}<p>${rl('阻挡','Blocking','阻擋')}: ${rx(check.blocking??'Unknown')}</p>${n2Text(check.rationale)}${n2Text(check.next_check)}`:'Unknown';}}))):''}<details><summary>${rl('全包未解决事项','Packet-wide unresolved items','全包未解決事項')}</summary>${n2Text(n2.model.packet.unresolved)}</details><details><summary>${rl('资料与参考入口补件（执行后整理）','Data / reference addendum (post-execution index)','資料與參考入口補件（執行後整理）')}</summary>${n2Text(n2.meta.resources_text)}</details></details>`;}
function n2ReviewMetrics(){return ''; }
function n2Relations(){const routes=n2.model.routes.filter(r=>n2.routes.includes(r.candidate.candidate_id)),sourceIds=[...new Set(routes.flatMap(r=>r.sourceIds))],objects=routes.map(route=>({id:route.candidate.candidate_id,title:route.candidate.candidate_id,route}));return `${n2Picker('routes')}<p class="n2-hint">${rl('只画原候选引用到来源的关系；空格表示未绑定，不等于不相关。引用数不是相似度、推荐排名或科学证实。','Only candidate-to-source citation bindings are shown. Empty means no saved binding, not unrelated. Citation counts are not similarity, recommendation ranking or scientific confirmation.','僅呈現原候選至來源的引用關係；空格表示未綁定，不等於不相關。引用數不是相似度、推薦排名或科學證實。')}</p>${objects.length?n2Table(objects,sourceIds.map(id=>({label:n2.model.sourceById.get(id)?.title||id,cell:o=>{const refs=o.route.bound.filter(r=>r.evidence.source_id===id);return refs.length?n2EvidenceLinks(refs.map(r=>r.evidence)):`<span>${rl('未绑定','No saved binding','未綁定')}</span>`;}}))):'<p>Unknown</p>'}`;}
function n2DraftKey(){return 'v9-natural-stage2-local-review:'+JSON.stringify([n2.meta.project_ref??rt.ref,n2.meta.material_id??'original-delivery',n2.meta.packet_json_sha256,n2.meta.selection_json_sha256]);}
function n2RestoreDraft(){try{const value=JSON.parse(sessionStorage.getItem(n2DraftKey())||'null');if(value?.kind==='V8LocalReviewDraft'&&value.source_key===n2DraftKey()&&n2.model.routes.some(r=>r.candidate.candidate_id===value.candidate_id&&r.candidate.version===value.version)){n2.draft=value.candidate_id;n2.note=typeof value.note==='string'?value.note.slice(0,4096):'';n2.draftStatus='local-only';}}catch{}}
function n2SaveDraft(clear=false){const route=n2.model?.routes.find(r=>r.candidate.candidate_id===n2.draft);if(!clear&&!route)return;try{const key=n2DraftKey();if(clear){sessionStorage.removeItem(key);if(sessionStorage.getItem(key)!==null)throw Error('local-draft-clear-readback-differs');n2.draft=null;n2.note='';n2.draftStatus='cleared-local-only';}else{const text=JSON.stringify({kind:'V8LocalReviewDraft',source_key:key,candidate_id:route.candidate.candidate_id,version:route.candidate.version,note:n2.note,submitted_to_harness:false});sessionStorage.setItem(key,text);if(sessionStorage.getItem(key)!==text)throw Error('local-draft-readback-differs');n2.draftStatus='local-only';}}catch{n2.draftStatus='storage-error-local-only';}}
function n2Draft(){const route=n2.model.routes.find(r=>r.candidate.candidate_id===n2.draft);return `<details class="n2-secondary" data-n2-review ${route?'open':''}><summary>${rl('人工审阅草稿与交接','Human-review draft & handoff','人工審閱草稿與交接')} · ${route?rl('本地待审','Local draft','本地待審'):rl('未正式选案','No formal selection','未正式選案')}</summary>${route?`<h3>${rx(route.candidate.candidate_id)}</h3>${n9RouteText(route,'candidate.question')}<label>${rl('本地意见','Local note','本地意見')}<textarea data-n2-note rows="3" maxlength="4096">${rx(n2.note)}</textarea></label><div class="hs-action-row"><button class="hs-button" data-n2-save>${rl('保存本地草稿','Save local draft','保存本地草稿')}</button><button class="hs-button" data-n2-clear>${rl('清除本地草稿','Clear local draft','清除本地草稿')}</button></div><small aria-live="polite">${rx(n9UiLabel(n2.draftStatus))} · ${rl('未提交Harness','Not submitted to Harness','未提交Harness')}</small>`:''}<div class="hs-action-row"><button class="hs-button" disabled>${rl('提交正式选案','Submit formal selection','提交正式選案')}</button><button class="hs-button" disabled>Codex</button><button class="hs-button" disabled>${rl('Stage3交接','Stage3 handoff','Stage3交接')}</button></div><p>${rl('研究接口未接通：缺当前workflow／可信human-record提交绑定与provider。作者recommend不是human选案；本地草稿不改变prehuman、Stage1血缘或执行许可。','Research interfaces are unconnected: no current workflow / trusted human-record submission binding or provider. An author recommendation is not a human choice; local drafts change neither prehuman status, Stage1 lineage nor execution permission.','研究介面未接通：缺目前workflow／可信human-record提交綁定與provider。作者recommend不是human選案；本地草稿不改變prehuman、Stage1血緣或執行許可。')}</p></details>`;}
function n2Evidence(){const e=n2.model.evidenceById.get(n2.evidence);if(!e)return '';const source=n2.model.sourceById.get(e.source_id);return `<section class="hs-panel n2-evidence" data-n2-evidence-view><div class="hs-panel-head"><h3>${rx(e.evidence_id)} · ${rx(source?.title||e.source_id)}</h3><button class="hs-button" data-n2-close-evidence>${rl('收起','Close','收起')}</button></div><p>${rx(e.work_id)} · ${rx(e.version_id)} · ${rx(source?.evidence_level??'Unknown')}</p><p>${rx(e.locator??'Unknown')} · ${rl('科学关系状态','Scientific relation','科學關係狀態')}: ${rx(e.relation??'Unknown')}</p><blockquote>${rx(e.quote??'Unknown')}</blockquote>${source?n2Record(rl('查看完整来源卡','Read full source card','查看完整來源卡'),source.card.saved_text):''}${n2Record(rl('原始证据记录','Original evidence record','原始證據紀錄'),e)}</section>`;}
function n2Raw(){if(!n2.raw)return '';const raw=n2.raw,size=6000,pages=Math.max(1,Math.ceil(raw.text.length/size));raw.page=Math.max(0,Math.min(raw.page,pages-1));return `<section class="hs-panel n2-raw"><div class="hs-panel-head"><h3>${rx(raw.label)}</h3><button class="hs-button" data-n2-close-raw>${rl('收起','Close','收起')}</button></div><div class="hs-action-row"><button class="hs-button" data-n2-raw-page="-1" ${raw.page===0?'disabled':''}>${rl('上一页','Previous','上一頁')}</button><span>${raw.page+1}/${pages}</span><button class="hs-button" data-n2-raw-page="1" ${raw.page+1===pages?'disabled':''}>${rl('下一页','Next','下一頁')}</button></div><pre>${rx(raw.text.slice(raw.page*size,(raw.page+1)*size))}</pre></section>`;}
async function n2LoadDocument(id){const d=n2.meta?.documents.find(d=>d.id===id);if(!d?.text_url||n2.pending.has(id)||n2.documents.has(id))return;n2.pending.add(id);n2.errors.delete(id);try{const value=await canonicalOldRequest(d.text_url);if(value?.kind!=='ReceivedStage2NaturalSavedText'||value.id!==d.id||value.sha256!==d.sha256||value.bytes!==d.bytes||typeof value.text!=='string'||new TextEncoder().encode(value.text).length!==d.bytes||await canonicalHash(value.text)!==d.sha256)throw Error('natural-stage2-document-byte-binding-differs');n2.documents.set(id,value.text);}catch(error){n2.errors.set(id,error.message);}finally{n2.pending.delete(id);if(n2Active()&&apps[0]?.stage===2)livePaint();}}
function n2Document(){if(!n2.document)return '';const d=n2.meta.documents.find(d=>d.id===n2.document);if(!d)return '';const text=n2.documents.get(d.id);return `<section class="hs-panel n2-document"><div class="hs-panel-head"><h3>${rx(d.name)}</h3><a class="hs-button" href="${rx(d.url)}" download>${rl('下载原文件','Download original','下載原檔案')}</a><button class="hs-button" data-n2-close-document>${rl('收起','Close','收起')}</button></div><small>${d.bytes.toLocaleString()} bytes · ${rx(d.sha256)}</small>${n2.errors.has(d.id)?`<p class="live-error">${rx(n2.errors.get(d.id))}</p>`:text===undefined?`<p>${rl('正在核验原文…','Verifying original…','正在核驗原文…')}</p>`:n2Text(text)}</section>`;}
function n2Files(){const documents=n2.meta.documents.filter(d=>d.role!=='source-card'),files=n2.meta.attachments,pages=Math.max(1,Math.ceil(files.length/30));n2.filePage=Math.max(0,Math.min(n2.filePage,pages-1));return `<details class="hs-panel n2-files" data-n2-files><summary>${rl('原报告、评语、资源补件与全部原始文件','Original reports, comments, resource addendum & all files','原報告、評語、資源補件及全部原始檔案')}</summary><div class="n2-file-links">${documents.map(d=>`<button class="hs-button" data-n2-document="${rx(d.id)}">${rx(d.name)} <small>${rx(d.role)}</small></button>`).join('')}</div><details><summary>${rl('全部交付附件（含保留失败历史）','All transfer attachments (including retained failures)','全部交付附件（含保留失敗歷史）')} · ${files.length}</summary><div class="n2-file-list">${files.slice(n2.filePage*30,(n2.filePage+1)*30).map(d=>`<a href="${rx(d.url)}" download>${rx(d.relative_path||d.name)}</a>`).join('')}</div><div class="hs-action-row"><button class="hs-button" data-n2-file-page="-1" ${n2.filePage===0?'disabled':''}>${rl('上一页','Previous','上一頁')}</button><span>${n2.filePage+1}/${pages}</span><button class="hs-button" data-n2-file-page="1" ${n2.filePage+1===pages?'disabled':''}>${rl('下一页','Next','下一頁')}</button></div></details></details>`;}
function n2Feedback(){return ''; }
function n2Render(app){n2.records=new Map();if(!n2.model)return `<section class="hs-panel"><h2>${rl('正在读取最新Stage2交付','Loading latest Stage2 delivery','正在讀取最新Stage2交付')}</h2><p>${rx(n2.error||rl('核验原文件与来源身份…','Verifying files & source identities…','核驗原檔案與來源身分…'))}</p></section>`;const model=n2.model,counts=model.levels;return `<details class="n2-boundary"><summary>${rl('独立自然提问 · prehuman · 尚未真人选案','Independent natural request · prehuman · no human direction choice','獨立自然提問 · prehuman · 尚未真人選案')}</summary><p>${rl('当前Stage1 v3和本Stage2交付没有正式血缘绑定。作者推荐与具名报告评分接受均不自动批准Stage3。','Current Stage1 v3 and this Stage2 delivery have no formal lineage binding. Neither author recommendation nor named score-record acceptance approves Stage3.','目前Stage1 v3與此Stage2交付無正式血緣綁定。作者推薦及具名報告評分接受均不自動批准Stage3。')}</p></details><details class="lp-results" data-local-results="2" open><summary><strong>Stage2 · ${rl('方向与文献工作台','Directions & literature workbench','方向與文獻工作臺')}</strong></summary><div class="lp-result-body"><section class="hs-panel n2-workbench" data-n2-workbench><div class="hs-panel-head"><div><h2>${rl('研究比较','Research comparison','研究比較')}</h2><p>${model.sources.length} ${rl('项来源资料','source materials','項來源資料')} · ${rx(counts['full-text']??0)} full-text · ${rx(counts.abstract??0)} abstract · ${model.routes.length} ${rl('条方向','directions','條方向')}</p></div><span class="hs-status">${n2Array(model.selection.recommendations).length} recommend · ${n2Array(model.selection.parked_options).length} park</span></div><nav class="n2-tabs" role="tablist" aria-label="Stage2">${Object.entries(n2Views).map(([id,label])=>`<button class="hs-button" id="n2-tab-${id}" role="tab" aria-selected="${n2.view===id}" aria-controls="n2-panel" tabindex="${n2.view===id?'0':'-1'}" data-n2-view="${id}">${rl(...label)}</button>`).join('')}</nav><p class="n2-notice" aria-live="polite">${rx(n9Message(n2.notice)||'')}</p><div id="n2-panel" role="tabpanel" aria-labelledby="n2-tab-${n2.view}">${n2.view==='papers'?n2Papers():n2.view==='routes'?n2Routes():n2Relations()}</div></section>${n2Evidence()}${n2Raw()}${n2Document()}${n2Files()}</div></details>${n2Feedback()}`;}
stage2=function(app){if(!n2Active())return n2OldStage2(app);if(!n2.meta&&!n2.loading&&!n2.error)queueMicrotask(()=>{if(n2Active()&&apps[0]?.stage===2)n2Load();});return `${typeof canonicalTop==='function'?canonicalTop():''}${canonicalHeading(app)}${canonicalOperations(app)}${n2Render(app)}`;};

const wikiStage2Original = stage2;
let wikiStage2State;

function wikiStage2Basis() {
  const project = rt.overview?.project;
  if (!project || project.project_ref !== rt.ref || canonicalReadonly()
      || rt.overview?.stage2?.receiving_only) return null;
  return [project.project_ref, project.input_version, project.brief_sha256, project.project_id, project.revision, rt.epoch];
}

function wikiStage2CurrentSelection() {
  const state=wikiStage2State;
  return !!state?.selection && JSON.stringify(wikiStage2Basis())===JSON.stringify(state.basis);
}
function wikiStage2OwnsView() {
  const state = wikiStage2State;
  return !!state && JSON.stringify(wikiStage2Basis()) === JSON.stringify(state.basis)
    && (state.error === "stage2-continuation-original-admission-unavailable"
      || (!!state.result && state.result.status !== "selection-available" && !wikiStage2CurrentSelection()));
}

async function wikiStage2Load(state, submit) {
  if (state !== wikiStage2State || state.busy) return;
  const [ref, inputVersion, brief] = state.basis;
  if (JSON.stringify(wikiStage2Basis()) !== JSON.stringify(state.basis)) return;
  state.busy = true;
  state.selection = null; state.selectionError = "";
  try {
    if (submit && !state.key) state.key = crypto.randomUUID();
    const result = await liveRequest(projectPath(ref, "stage2/continuation"), submit ? {
      key: state.key, input_version: inputVersion, brief_sha256: brief, confirmed: true,
    } : undefined);
    if (result.project_ref !== ref || (state.basis[3] !== undefined && result.project_id !== state.basis[3]) || result.input_version !== inputVersion
        || result.brief_sha256 !== brief) throw Error("project-binding-mismatch");
    state.result = result;
    state.error = "";
    if (!submit && typeof v9ConnectionConnected==='function' && result.execution_authorized===false &&
        ['candidate-ready','selection-available'].includes(result.status)) {
      try {
        const current=await liveRequest(projectPath(ref,'stage2/selection'));
        if (current?.kind!=='Stage2SelectionView' || current.execution_authorized!==false ||
            current.project_ref!==ref || current.input_version!==inputVersion || current.brief_sha256!==brief ||
            current.revision!==state.basis[4] || !['delivery_manifest_sha256','delivery_workflow_head_sha256','snapshot_sha256'].every(k=>v9ConnectionHash(current[k])) ||
            (result.status==='candidate-ready' && (current.delivery_manifest_sha256!==result.delivery_manifest_sha256 ||
              current.snapshot_sha256!==result.snapshot_sha256 || current.delivery_workflow_head_sha256!==result.workflow_head_sha256))) throw Error('stage2-selection-binding-differs');
        state.selection=current;
      } catch (error) { state.selectionError=error.message; }
    }
  } catch (error) {
    if (error.message !== "stage2-continuation-worker-busy") state.result = null;
    state.error = error.message;
  } finally {
    state.busy = false;
    if (state === wikiStage2State && JSON.stringify(wikiStage2Basis()) === JSON.stringify(state.basis)
        && apps[0]?.page === "workspace" && apps[0]?.stage === 2) livePaint();
  }
}

function wikiStage2Panel(state) {
  const label = (zh, en, tw) => rl(zh, en, tw);
  const status = state.result?.status;
  const descriptions = {
    ready: label("项目已接入。可请求生成候选。", "This project is connected. You can request candidates.", "專案已接入。可請求產生候選。"),
    "request-saved": label("请求已保存。可查看处理状态。", "Request saved. You can check its status.", "請求已儲存。可查看處理狀態。"),
    running: label("正在处理此请求。", "This request is in progress.", "正在處理此請求。"),
    "candidate-ready": label("当前版本的候选已保存。", "Candidates saved for this version.", "目前版本的候選已儲存。"),
    "no-candidate": label("已有控制器回执。候选交付尚未保存。", "A controller receipt is saved. Candidate delivery is pending.", "已有控制器回執。候選交付尚未儲存。"),
    "execution-unknown": label("已有请求。请由操作者核对原运行记录。", "A request exists. Ask the operator to check the retained run.", "已有請求。請由操作者核對原執行紀錄。"),
    blocked: label("已保存的请求受阻。请由操作者检查交接。", "The saved request is blocked. Ask the operator to check the handoff.", "已儲存的請求受阻。請由操作者檢查交接。"),
    "stage2-controller-not-connected": label("本课题还没有接通 Stage 2。", "Stage 2 is not connected for this project.", "本課題還沒有接通 Stage 2。"),
    "stage2-continuation-activation-required": label("请先完成本项目的 Stage 2 启用。", "Complete Stage 2 activation for this project first.", "請先完成本專案的 Stage 2 啟用。"),
    "stage2-continuation-original-admission-unavailable": label("原运行许可缺失或已过期。请联系操作者。", "The original run admission is missing or expired. Contact the operator.", "原執行許可缺失或已過期。請聯絡操作者。"),
    "stage2-continuation-project-stale": label("当前输入版本和已接入作业不一致。请重新打开项目。", "Reopen the project. The input version has changed.", "目前輸入版本和已接入作業不一致。請重新開啟專案。"),
    "stage2-continuation-result-not-current": label("保存的候选与当前记录不一致。请联系操作者。", "The saved candidates could not be verified for this version. Contact the operator.", "保存的候選與目前紀錄不一致。請聯絡操作者。"),
    "stage2-continuation-request-exists": label("已有请求。请查看保存状态。", "A request already exists. Check its saved status.", "已有請求。請查看儲存狀態。"),
    "stage2-continuation-worker-busy": label("另一个请求正在处理。请稍后再试。", "Another request is running. Try again shortly.", "另一個請求正在處理。請稍後再試。"),
  };
  const pathConflict=state.error==="stage2-continuation-result-not-current" && typeof v9ConnectionReason==='function';
  const mayRequest=typeof v9AllowsCandidateRequest!=='function'||v9AllowsCandidateRequest();
  const message = pathConflict ? v9ConnectionReason(state.error,409) : state.busy
    ? label("正在读取请求状态。", "Checking request status.", "正在讀取請求狀態。")
    : descriptions[state.error || status] || (state.error
      ? label("暂时无法读取回执。请再查一次保存状态。", "The receipt could not be read. Check its saved status again.", "暫時無法讀取回執。請再查一次儲存狀態。")
      : "");
  const cards = state.result?.cards || [];
  const heading = label("候选方向", "Candidate directions", "候選方向");
  const prompts = [
    ["suggested_approach", label("方法", "Approach", "方法")],
    ["requirements", label("需要的资料", "Requirements", "需要的資料")],
    ["limitations", label("限制", "Limitations", "限制")],
  ];
  return `<section class="hs-panel" data-wiki-stage2-continuation><h2>${heading}</h2>
    <small>${rx(rt.overview.project.brief?.original_description || state.basis[0])} · ${label("输入版本", "Input version", "輸入版本")} ${rx(state.basis[1])}</small>
    <p role="status">${rx(message)}</p><div class="n9-page-actions">
      ${status === "ready" && mayRequest ? `<button type="button" class="hs-button hs-button-primary" data-wiki-stage2-action="request" ${state.busy ? "disabled" : ""}>${label("请求生成候选", "Request candidates", "請求產生候選")}</button>` : ""}
      <button type="button" class="hs-button" data-wiki-stage2-action="read" ${state.busy ? "disabled" : ""}>${label("查看保存状态", "Check saved status", "查看儲存狀態")}</button>
    </div>
    ${pathConflict||state.selectionError ? '<details><summary>'+label('技术详情','Technical details','技術詳情')+'</summary><code>'+rx(pathConflict?state.error:state.selectionError)+'</code></details>' : ''}
    ${state.result?.synthetic_test_only ? `<p>${label("合成工程候选", "Synthetic engineering candidates", "合成工程候選")}</p>` : ""}
    ${state.result?.human_selection === "pending" ? `<p>${label("等待人工选案", "Human selection pending", "等待人工選案")}</p>` : ""}
    ${state.result?.assessment_status === "missing" ? `<p>${label("独立评估尚未提供", "Independent assessment unavailable", "獨立評估尚未提供")}</p>` : ""}
    ${status === "candidate-ready" && state.result.comparison ? `<p><strong>${state.result.comparison_is_input_baseline
      ? label("接入时的比较基线", "Comparison baseline at intake", "接入時的比較基線")
      : label("交付中记录的比较", "Comparison recorded in the delivery", "交付中記錄的比較")}</strong> ${rx(state.result.comparison)}</p>` : ""}
    ${cards.map(card => `<details class="n2-secondary"><summary>${rx(card.candidate_question)} · v${rx(card.candidate_version)}</summary>
      <dl>${prompts.map(([field, name]) => `<dt>${name}</dt><dd>${rx(Array.isArray(card[field]) ? card[field].join(" · ") || null : card[field])}</dd>`).join("")}</dl>
    </details>`).join("")}</section>`;
}

stage2 = function (app) {
  const original = wikiStage2Original(app);
  const basis = wikiStage2Basis();
  if (!basis) return original;
  if (JSON.stringify(wikiStage2State?.basis) !== JSON.stringify(basis)) {
    const state = {basis, key: null, result: null, busy: false, error: ""};
    wikiStage2State = state;
    queueMicrotask(() => wikiStage2Load(state, false));
  }
  if (window.RESEARCH_PROJECTS?.stage2_selection_projects?.includes(rt.ref)
      && !wikiStage2OwnsView()) return original;
  const panel = wikiStage2Panel(wikiStage2State);
  if (!wikiStage2State.result) return panel + original;
  return `${liveHeader(app)}${panel}<details class="hs-panel">
    <summary>${rl("先前的 Wiki 输入和记录", "Earlier Wiki inputs and records", "先前的 Wiki 輸入和紀錄")}</summary>
    ${original}</details>`;
};

document.addEventListener("click", event => {
  const button = event.target.closest?.("[data-wiki-stage2-action]");
  if (!button || !wikiStage2State || button.disabled) return;
  const submit = button.dataset.wikiStage2Action === "request";
  if (submit && ((typeof v9AllowsCandidateRequest==="function" && !v9AllowsCandidateRequest()) || wikiStage2State.result?.status !== "ready" || rt.busy || rt.loading || rt.pending || rt.controlHeld)) return;
  wikiStage2Load(wikiStage2State, submit);
  livePaint();
});
v7AfterRender=function(app){n2OldAfter(app);if(n2Active()&&app.stage===2)n2Load();};
function n2Paint(open){livePaint();if(open)apps[0].el.querySelector(open)?.setAttribute('open','');}
document.addEventListener('change',event=>{if(!n2Active()||apps[0]?.stage!==2||!n2.model)return;const el=event.target;if(el.matches('[data-n2-select]')){const sources=el.dataset.n2Select==='sources',key=sources?'papers':'routes',allowed=sources?n2.model.sources.map(s=>s.source_id):n2.model.routes.map(r=>r.candidate.candidate_id);if(!allowed.includes(el.value))return;if(el.checked&&!n2[key].includes(el.value)){if(n2[key].length>=3){el.checked=false;n2.notice=()=>rl('最多并排3个对象，请先取消一个。','Up to 3 objects; deselect one first.','最多並排3個對象，請先取消一個。');}else{n2[key].push(el.value);n2.notice='';}}else if(!el.checked)n2[key]=n2[key].filter(v=>v!==el.value);n2.evidence=null;n2.raw=null;n2Paint('.n2-picker');}if(el.matches('[data-n2-draft]')&&n2.model.routes.some(r=>r.candidate.candidate_id===el.dataset.n2Draft)){if(n2.draft!==el.dataset.n2Draft)n2.note='';n2.draft=el.dataset.n2Draft;n2.draftStatus='unsaved-local-only';n2Paint('[data-n2-review]');}});
document.addEventListener('input',event=>{if(n2Active()&&event.target.matches('[data-n2-note]'))n2.note=event.target.value.slice(0,4096);});
document.addEventListener('keydown',event=>{if(!n2Active()||!n2.model||!event.target.matches('[data-n2-view][role="tab"]')||!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();const keys=Object.keys(n2Views),at=keys.indexOf(n2.view),next=event.key==='Home'?0:event.key==='End'?keys.length-1:(at+(event.key==='ArrowRight'?1:-1)+keys.length)%keys.length;n2.view=keys[next];n2.notice='';n2.raw=null;n2.evidence=null;n2.document=null;n2Paint();apps[0].el.querySelector('#n2-tab-'+n2.view)?.focus();});
document.addEventListener('click',async event=>{if(!n2Active()||apps[0]?.stage!==2||!n2.model)return;const b=event.target.closest('[data-n2-view],[data-n2-evidence],[data-n2-record],[data-n2-close-evidence],[data-n2-close-raw],[data-n2-raw-page],[data-n2-document],[data-n2-close-document],[data-n2-file-page],[data-n2-save],[data-n2-clear]');if(!b)return;event.preventDefault();if(b.hasAttribute('data-n2-view')){const view=b.dataset.n2View;if(!Object.hasOwn(n2Views,view))return;n2.view=view;n2.notice='';n2.evidence=null;n2.raw=null;n2.document=null;}if(b.hasAttribute('data-n2-evidence')){if(!n2.model.evidenceById.has(b.dataset.n2Evidence))return;n2.evidence=b.dataset.n2Evidence;}if(b.hasAttribute('data-n2-record')){const record=n2.records.get(b.dataset.n2Record);if(!record)return;n2.raw={label:record.label,text:typeof record.value==='string'?record.value:JSON.stringify(record.value??null,null,2),page:0};}if(b.hasAttribute('data-n2-close-evidence'))n2.evidence=null;if(b.hasAttribute('data-n2-close-raw'))n2.raw=null;if(b.hasAttribute('data-n2-raw-page')&&n2.raw)n2.raw.page+=Number(b.dataset.n2RawPage)||0;if(b.hasAttribute('data-n2-document')){const d=n2.meta.documents.find(d=>d.id===b.dataset.n2Document);if(!d?.text_url)return;n2.document=d.id;n2Paint();await n2LoadDocument(d.id);return;}if(b.hasAttribute('data-n2-close-document'))n2.document=null;if(b.hasAttribute('data-n2-file-page'))n2.filePage+=Number(b.dataset.n2FilePage)||0;if(b.hasAttribute('data-n2-save'))n2SaveDraft();if(b.hasAttribute('data-n2-clear'))n2SaveDraft(true);n2Paint(b.hasAttribute('data-n2-file-page')?'[data-n2-files]':null);});
