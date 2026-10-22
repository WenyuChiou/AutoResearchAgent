// Original reviews are read-only records, never formal decisions or scores.
async function n9ReadReviews(view){
 const source=view.independent_reviews,fail=()=>{throw Error('review-reading-binding-differs');};
 const hash=value=>typeof value==='string'&&/^[a-f0-9]{64}$/.test(value);
 if(!source||source.kind!=='V9IndependentReviewReading'||source.project_ref!==view.project_ref||
    source.material_id!==view.material_id||source.packet_file_sha256!==view.packet_file_sha256||
    source.packet_sha256!==view.packet_sha256||!hash(source.delivery_manifest_sha256)||
    !hash(source.snapshot_sha256)||!hash(source.batch_sha256)||
    !source.resolution_counts||typeof source.resolution_counts!=='object'||Array.isArray(source.resolution_counts)||
    !Object.values(source.resolution_counts).every(v=>Number.isSafeInteger(v)&&v>=0)||
    !Number.isSafeInteger(source.recommendations_count)||source.recommendations_count<0||
    !hash(source.reviews_file_sha256)||typeof source.reviews_text!=='string'||source.reviews_text.length>4*1024*1024||
    source.human_selection!=='pending'||source.formal_selection_available!==false||
    source.stage3_execution_authorized!==false||source.scientific_acceptance!==false||
    !['draft-not-ready','local-report-ready'].includes(source.delivery_status))fail();
 if(await canonicalHash(source.reviews_text)!==source.reviews_file_sha256)fail();
 const records=JSON.parse(source.reviews_text),packet=JSON.parse(view.packet_text);
 if(!Array.isArray(records)||records.length>200||!Array.isArray(packet.candidates))fail();
 const seen=new Set();
 for(const record of records){
  const key=JSON.stringify([record?.candidate_id,record?.candidate_version,record?.role]);
  if(!record||!packet.candidates.some(c=>c.candidate_id===record.candidate_id&&c.version===record.candidate_version)||
     typeof record.role!=='string'||seen.has(key))fail();
  seen.add(key);
  if(record.status==='complete'){
   const assessment=record.review?.assessment;
   if(!assessment||assessment.candidate_id!==record.candidate_id||assessment.candidate_version!==record.candidate_version||assessment.packet_sha256!==view.packet_sha256||record.review.snapshot_sha256!==source.snapshot_sha256)fail();
  }
 }
 return {source,records};
}
const n9ReviewBodies=new Map();
function n9ReviewReader(app,reading,opened){
 if(!reading)return '';
 n9ReviewBodies.clear();
 const {source,records}=reading,label=(zh,en,tw=zh)=>canonicalStage2Label(app,zh,en,tw),escape=canonicalStage2Escape;
 const scope=JSON.stringify([source.project_ref,source.material_id,source.reviews_file_sha256]);
 const detail=(key,title,body)=>{
  n9ReviewBodies.set(key,body);
  return `<details data-n9-review-key="${escape(key)}" data-n9-review-scope="${escape(scope)}" ${opened[key]?'open data-n9-review-loaded="1"':''}><summary>${escape(title)}</summary><div data-n9-review-body>${opened[key]?body():''}</div></details>`;
 };
 const text=value=>escape(value===null||value===undefined?label('未提供','Not supplied','未提供'):typeof value==='string'?value:JSON.stringify(value));
 const lookup=(values,key,fallback)=>Object.hasOwn(values,key)?values[key]:fallback;
 const criterion=name=>lookup({opportunity:label('机会定位','Opportunity','機會定位'),value:label('研究价值','Value','研究價值'),answerability:label('可回答性','Answerability','可回答性'),materials:label('资料与材料','Materials','資料與材料'),execution:label('执行可行性','Execution','執行可行性')},name,name);
 const status=value=>lookup({complete:label('评语已交付','Review delivered','評語已交付'),failed:label('失败','Failed','失敗'),missing:label('缺件','Missing','缺件'),unavailable:label('不可用','Unavailable','不可用'),interrupted:label('已中断','Interrupted','已中斷'),empty:label('空回覆','Empty response','空回覆')},value,label('状态未知','Unknown status','狀態未知'));
 const groups=[...new Set(records.map(r=>JSON.stringify([r.candidate_id,r.candidate_version])))];
 const counts=source.resolution_counts,resolved=counts.resolved||0,pending=Object.values(counts).reduce((sum,n)=>sum+n,0)-resolved;
 const render=()=>`<p class="n2-hint">${label('已裁决','Resolved','已裁決')}: ${resolved} · ${label('待裁决','Pending resolution','待裁決')}: ${pending} · ${label('原报告推荐','Report recommendations','原報告推薦')}: ${source.recommendations_count}</p>`+groups.map(pair=>{
  const [id,version]=JSON.parse(pair),candidate=n2.model.routes.find(r=>r.candidate.candidate_id===id&&r.candidate.version===version)?.candidate;
  return `<section><h2>${text(candidate?.question||id)}</h2>${records.filter(r=>r.candidate_id===id&&r.candidate_version===version).map(record=>{
   const key=JSON.stringify([id,version,record.role]),assessment=record.review?.assessment;
   const role=record.role==='challenger'?label('挑战审查','Challenger','挑戰審查'):record.role==='feasibility'?label('可行性审查','Feasibility','可行性審查'):record.role;
   return detail(key,`${role} · ${status(record.status)}`,()=>{
    const checks=Object.entries(assessment?.checks||{}).map(([name,check])=>`<dt>${text(criterion(name))}</dt><dd><p><strong>${label('理由','Rationale','理由')}:</strong> ${text(check.rationale)}</p>${check.next_check?`<p><strong>${label('需要补查','Next check','需要補查')}:</strong> ${text(check.next_check)}</p>`:''}</dd>`).join('');
    return `<div class="n9-review-body"><p>${text(assessment?.reason||record.error)}</p>${assessment?`${assessment.next_step?`<h3>${label('下一步','Next step','下一步')}</h3><p>${text(assessment.next_step)}</p>`:''}<dl>${checks}</dl>`:''}${detail(key+':json',label('完整原始记录','Complete original record','完整原始紀錄'),()=>`<pre>${escape(JSON.stringify(record,null,2))}</pre>`)}</div>`;
   });
  }).join('')}</section>`;
 }).join('')+detail('source',label('来源与版本','Source & version','來源與版本'),()=>`<dl><dt>Packet SHA-256</dt><dd>${text(source.packet_sha256)}</dd><dt>Delivery SHA-256</dt><dd>${text(source.delivery_manifest_sha256)}</dd><dt>Reviews SHA-256</dt><dd>${text(source.reviews_file_sha256)}</dd></dl>`);
 const state=source.delivery_status==='draft-not-ready'?label('草稿 · 尚未选案','Draft · no formal selection','草稿 · 尚未選案'):label('保存报告 · 尚未选案','Saved report · no formal selection','保存報告 · 尚未選案');
 return `<section class="hs-panel n9-original-reviews">${detail('reader',label('原始独立评审','Original independent reviews','原始獨立評審')+` · ${records.length} · ${state}`,render)}</section>`;
}
document.addEventListener('toggle',event=>{
 const node=event.target,reading=typeof n2==='undefined'?null:n2.reviewReading;
 if(!node?.matches?.('[data-n9-review-key]')||!node.isConnected||!reading||!apps[0].el.contains(node))return;
 const source=reading.source,scope=JSON.stringify([source.project_ref,source.material_id,source.reviews_file_sha256]);
 if(node.dataset.n9ReviewScope!==scope)return;
 n2.reviewDisclosures[node.dataset.n9ReviewKey]=node.open;
 if(!node.open||node.dataset.n9ReviewLoaded)return;
 const render=n9ReviewBodies.get(node.dataset.n9ReviewKey),body=node.querySelector(':scope > [data-n9-review-body]');
 if(render&&body){body.innerHTML=render();node.dataset.n9ReviewLoaded='1';}
},true);
