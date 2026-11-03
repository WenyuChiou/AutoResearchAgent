// Complete files stay outside plan JSON, model context and the rendered text tree.
const v95MaterialLimit=128*1024*1024;
function v95MaterialHash(bytes){return crypto.subtle.digest('SHA-256',bytes).then(pin=>Array.from(new Uint8Array(pin),b=>b.toString(16).padStart(2,'0')).join(''));}
function v95MaterialRefsValid(record){
 if(record.material_refs===undefined)return true;
 return record.schema_version===2&&Array.isArray(record.material_refs)&&record.material_refs.length<=8&&record.material_refs.every(x=>x&&typeof x.question_ref==='string'&&record.plan?.question_plans?.some(q=>q.question_ref===x.question_ref)&&/^file-[a-f0-9]{32}$/.test(x.file_id)&&/^[a-f0-9]{64}$/.test(x.sha256)&&Number.isSafeInteger(x.bytes)&&x.bytes>0&&x.bytes<=v95MaterialLimit&&typeof x.name==='string');
}
function v95MaterialEntry(entry,context,size,pin,id=null){
 if(!entry||entry.sha256!==pin||entry.bytes!==size||entry.project_ref!==context.binding.project_ref||entry.stage!==3||!/^file-[a-f0-9]{32}$/.test(entry.id)||(id!==null&&entry.id!==id))throw Error('stage3-material-file-differs');
 return entry;
}
function v95MaterialTarget(state){return JSON.stringify([state.selected,state.revisionQuestion]);}
function v95MaterialRefusal(error){
 const codes={400:['stage3-material-references-invalid','stage3-material-reference-invalid'],409:['stage3-material-file-unavailable','stage3-material-file-differs','stage3-material-reader-unconnected','stage3-material-question-differs'],413:['stage3-material-capacity-exceeded']};
 return codes[error?.status]?.includes(String(error?.message||error))===true;
}
function v95MaterialEditor(context,state){
 if(state.field!=='materials')return '';
 const upload=state.materialUpload,matching=upload?.target===v95MaterialTarget(state),ready=matching&&upload?.entry?.status==='registered';
 return `<section class="n9f-details"><h4>${rl('完整材料文件','Complete material file','完整材料檔案')}</h4><p>${rl('大材料以原文件保存，最多128MiB；规划只保存摘要、版本和文件指纹，不会自动发送给模型。','Keep complete files up to128MiB. The plan stores a summary, version and file hash; files are not automatically sent to a model.','大材料以原檔案保存，最多128MiB；規劃只保存摘要、版本及檔案指紋，不會自動傳給模型。')}</p><label class="n9f-control">${rl('选择完整材料','Choose complete material','選擇完整材料')}<input type="file" data-v95-material-file accept=".pdf,.md,.txt,.csv,.tsv,.json,.jsonl,.bib,.docx,.xlsx"${state.busy||state.pending?' disabled':''}></label>${matching?`<p role="status">${rx(upload.file.name)} · ${upload.file.size} bytes · ${rx(upload.entry?.status||'not-confirmed')}</p>${ready?`<p class="n9f-text">SHA-256 ${rx(upload.entry.sha256)}</p><p>${rl('文件已保存；点击保存人工草案才会绑定到本问题和版本。','File saved. Save the manual draft to bind it to this question and version.','檔案已保存；按保存人工草案才會綁定到本問題及版本。')}</p>`:`<button type="button" class="hs-button" data-v95-material-resume${state.busy?' disabled':''}>${rl('核对并继续同一上传','Check and resume same upload','核對並繼續同一上傳')}</button>${upload.entry?.status==='uploading'?`<button type="button" class="hs-button" data-v95-material-abort${state.busy?' disabled':''}>${rl('取消未完成上传','Cancel incomplete upload','取消未完成上傳')}</button>`:''}`}`:''}</section>`;
}
function v95MaterialReferences(state){
 const upload=state.materialUpload;
 if(state.field!=='materials'||!upload||upload.target!==v95MaterialTarget(state))return null;
 if(upload.entry?.status!=='registered')throw Error('stage3-material-upload-not-complete');
 return [{question_ref:state.revisionQuestion,file_id:upload.entry.id,sha256:upload.entry.sha256,bytes:upload.entry.bytes}];
}
function v95MaterialLinks(row,question){
 const refs=(row.record.material_refs||[]).filter(x=>x.question_ref===question.question_ref);
 return refs.map(x=>`<section class="n9f-details"><h4>${rl('本版本的完整材料','Complete material for this revision','本版本完整材料')}</h4><p>${rx(x.name)} · ${x.bytes} bytes · v${row.record.revision_number}</p><p class="n9f-text">SHA-256 ${rx(x.sha256)}</p><button type="button" class="hs-button" data-v95-material-download="${rx(x.file_id)}" data-v95-receipt="${rx(row.receipt_sha256)}">${rl('核对并下载完整文件','Verify and download complete file','核對並下載完整檔案')}</button><p>${rl('文件关联不等于已阅读、获准使用或科学接受。','Association does not establish reading, usage permission or scientific acceptance.','檔案關聯不代表已閱讀、獲准使用或科學接受。')}</p></section>`).join('');
}
async function v95MaterialUpload(app){
 const context=v94fContext(app),state=context&&v94fState(context),upload=state?.materialUpload;
 if(!upload||state.busy||state.pending||upload.target!==v95MaterialTarget(state))return;
 const epoch=rt.epoch,current=()=>v94fCurrent(context,epoch,app)&&upload.target===v95MaterialTarget(state);
 state.busy=true;state.error='';livePaint();
 try{
  const bytes=new Uint8Array(await upload.file.arrayBuffer());
  if(bytes.length!==upload.file.size||bytes.length>v95MaterialLimit||!bytes.length)throw Error('stage3-material-capacity-exceeded');
  const pin=await v95MaterialHash(bytes);if(!current())throw Error('stage3-material-display-changed');
  let entry=await liveRequest('/api/v9/upload/start',{project_ref:context.binding.project_ref,stage:3,purpose:'stage3-planning-material',name:upload.file.name,bytes:bytes.length,sha256:pin,restart_aborted:true});
  v95MaterialEntry(entry,context,bytes.length,pin);upload.entry=entry;
  const identity=entry.id;
  if(!['uploading','registered'].includes(entry.status)||!Number.isSafeInteger(entry.received)||entry.received<0||entry.received>bytes.length)throw Error('stage3-material-upload-not-active');
  if(entry.status!=='registered'){
   for(let offset=entry.received;offset<bytes.length;offset+=128*1024){
    if(!current())throw Error('stage3-material-display-changed');
    const chunk=bytes.subarray(offset,offset+128*1024);let binary='';
    for(let i=0;i<chunk.length;i+=8192)binary+=String.fromCharCode(...chunk.subarray(i,i+8192));
    entry=v95MaterialEntry(await liveRequest('/api/v9/upload/chunk',{id:identity,offset,base64:btoa(binary)}),context,bytes.length,pin,identity);upload.entry=entry;
   }
   if(!current())throw Error('stage3-material-display-changed');
   entry=v95MaterialEntry(await liveRequest('/api/v9/upload/finish',{id:identity}),context,bytes.length,pin,identity);upload.entry=entry;
  }
  if(entry.status!=='registered'||entry.sha256!==pin||entry.bytes!==bytes.length)throw Error('stage3-material-file-differs');
  if(current()&&!state.value.trim())state.value=rl('完整材料文件：','Complete material file: ','完整材料檔案：')+upload.file.name+rl('（未审阅）',' (not reviewed)','（未審閱）');
 }catch(error){state.error=String(error?.message||error);}
 finally{state.busy=false;if(current())livePaint();}
}
async function v95MaterialRead(ref){
 if(!/^file-[a-f0-9]{32}$/.test(ref.file_id)||!Number.isSafeInteger(ref.bytes)||ref.bytes<=0||ref.bytes>v95MaterialLimit)throw Error('stage3-material-reference-invalid');
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),60000);
 try{
  const response=await fetch('/api/v9/files/'+ref.file_id,{headers:{Authorization:'Bearer '+window.RESEARCH_PROJECTS.credential},cache:'no-store',credentials:'omit',redirect:'error',signal:controller.signal});
  if(!response.ok||!response.body)throw Error('stage3-material-download-failed');
  const reader=response.body.getReader(),chunks=[];let size=0;
  try{while(true){const {done,value}=await reader.read();if(done)break;size+=value.byteLength;if(size>ref.bytes){await reader.cancel();throw Error('stage3-material-size-differs');}chunks.push(value);}}finally{reader.releaseLock();}
  if(size!==ref.bytes)throw Error('stage3-material-size-differs');
  const bytes=new Uint8Array(size);let offset=0;for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.byteLength;}
  if(await v95MaterialHash(bytes)!==ref.sha256)throw Error('stage3-material-hash-differs');
  return bytes;
 }finally{clearTimeout(timer);}
}
document.addEventListener('change',event=>{
 const control=event.target.closest('[data-v95-material-file]'),app=control&&apps.find(a=>a.el.contains(control)),context=app&&v94fContext(app),state=context&&v94fState(context);
 if(!state||state.busy||state.pending||state.field!=='materials')return;
 const file=control.files?.[0];if(!file)return;
 if(!file.size||file.size>v95MaterialLimit){state.materialUpload=null;state.error='stage3-material-capacity-exceeded';livePaint();return;}
 state.materialUpload={file,target:v95MaterialTarget(state),entry:null};v95MaterialUpload(app);
});
document.addEventListener('click',async event=>{
 const control=event.target.closest('[data-v95-material-resume],[data-v95-material-abort],[data-v95-material-download]'),app=control&&apps.find(a=>a.el.contains(control)),context=app&&v94fContext(app),state=context&&v94fState(context);
 if(!state||state.busy||state.pending)return;
 if(control.hasAttribute('data-v95-material-resume')){v95MaterialUpload(app);return;}
 const epoch=rt.epoch;state.busy=true;state.error='';livePaint();
 try{
  if(control.hasAttribute('data-v95-material-abort')){const item=state.materialUpload?.entry;if(item?.status!=='uploading')throw Error('upload-not-active');await liveRequest('/api/v9/upload/abort',{id:item.id,expected_generation:item.upload_attempt||1});state.materialUpload=null;}
  else{const row=v94fRevision(state),ref=row?.receipt_sha256===control.dataset.v95Receipt&&(row.record.material_refs||[]).find(x=>x.file_id===control.dataset.v95MaterialDownload);if(!ref)throw Error('stage3-material-revision-differs');const bytes=await v95MaterialRead(ref);if(v94fCurrent(context,epoch,app)&&v94fRevision(state)?.receipt_sha256===row.receipt_sha256)m9Download(ref.name,bytes,'application/octet-stream');}
 }catch(error){state.error=String(error?.message||error);}
 finally{state.busy=false;if(v94fCurrent(context,epoch,app))livePaint();}
});
