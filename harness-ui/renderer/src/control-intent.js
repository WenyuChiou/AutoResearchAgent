// Retirement transport foundation. No UI entry, automatic POST or original-intent cleanup.
const liveControlStorage='v7-retirement-control-v1';
const liveControlHex=x=>typeof x==='string'&&/^[a-f0-9]{64}$/.test(x);
const liveControlId=x=>typeof x==='string'&&/^[A-Za-z0-9_-]{1,128}$/.test(x);
function liveControlValid(record){
 const p=record?.intent,b=p?.body;
 return record?.kind==='V7RetirementControlIntent.v1'&&['pending','observed'].includes(record.state)&&
  p&&liveControlId(p.ref)&&p.path===projectPath(p.ref,'models/retire')&&b&&
  Object.keys(b).sort().join(',')==='brief_sha256,confirmed,input_version,job_ref,job_request_sha256,job_snapshot_sha256,key,revision,user_input'&&
  liveControlId(b.key)&&liveControlId(b.job_ref)&&Number.isSafeInteger(b.revision)&&b.revision>=0&&
  Number.isSafeInteger(b.input_version)&&b.input_version>0&&liveControlHex(b.brief_sha256)&&
  liveControlHex(b.job_request_sha256)&&liveControlHex(b.job_snapshot_sha256)&&b.confirmed===true&&
  typeof b.user_input==='string'&&b.user_input.trim()&&new TextEncoder().encode(b.user_input).length<=4096;
}
function liveControlStore(record){
 try{
  if(rt.controlJournalInvalid||rt.controlArchiveVerified===false)throw new Error('retirement-control-journal-unverified');
  const raw=sessionStorage.getItem(liveControlStorage),saved=liveControlJournalRead(raw);
  if(JSON.stringify(saved.archives)!==JSON.stringify(rt.controlArchives||[])||saved.active&&JSON.stringify(saved.active.intent)!==JSON.stringify(record.intent))throw new Error('retirement-control-journal-changed');
  liveControlJournalWrite(record,rt.controlArchives||[],raw);
 }catch(error){rt.controlHeld=true;rt.controlJournalInvalid=true;rt.controlArchiveVerified=false;throw error;}
}
function liveControlLoad(){
 rt.controlIntent=null;rt.controlHeld=false;rt.controlError=null;rt.controlArchives=[];rt.controlArchiveVerified=true;rt.controlJournalInvalid=false;
 try{const saved=liveControlJournalRead(sessionStorage.getItem(liveControlStorage));
  rt.controlIntent=saved.active;rt.controlArchives=saved.archives;rt.controlArchiveVerified=!saved.archives.length;
  rt.controlHeld=!!saved.active||!rt.controlArchiveVerified;
 }catch(error){rt.controlHeld=true;rt.controlJournalInvalid=true;rt.controlArchiveVerified=false;rt.controlError=error.message;}
}
function liveControlJournalRead(raw){
 if(raw===null)return {active:null,archives:[]};
 if(typeof raw!=='string'||new TextEncoder().encode(raw).length>1048576)throw new Error('retirement-control-journal-invalid');
 const value=JSON.parse(raw);
 if(value?.kind!=='V7RetirementControlJournal.v1'){
  if(!liveControlValid(value)||new TextEncoder().encode(raw).length>65536)throw new Error('retirement-control-record-invalid');
  return {active:value,archives:[]};
 }
 if(Object.keys(value).sort().join(',')!=='active,archives,kind'||!Array.isArray(value.archives)||value.archives.length>16||value.active!==null&&(!liveControlValid(value.active)||new TextEncoder().encode(JSON.stringify(value.active)).length>65536))throw new Error('retirement-control-journal-invalid');
 const seen=new Set();
 for(const entry of value.archives){
  if(typeof entry!=='string'||new TextEncoder().encode(entry).length>65536)throw new Error('retirement-control-archive-invalid');
  const record=JSON.parse(entry),id=JSON.stringify([record?.intent?.ref,record?.intent?.body?.key]);
  if(!liveControlValid(record)||record.state!=='observed'||!record.receipt||seen.has(id))throw new Error('retirement-control-archive-invalid');seen.add(id);
 }
 if(value.active&&seen.has(JSON.stringify([value.active.intent.ref,value.active.intent.body.key])))throw new Error('retirement-control-archive-duplicate');
 return {active:value.active,archives:value.archives};
}
function liveControlJournalWrite(active,archives,expectedRaw){
 const recordRaw=JSON.stringify(active);
 if(active&&new TextEncoder().encode(recordRaw).length>65536)throw new Error('retirement-control-record-invalid');
 const raw=archives.length?JSON.stringify({kind:'V7RetirementControlJournal.v1',active,archives}):recordRaw;
 liveControlJournalRead(raw);
 if(sessionStorage.getItem(liveControlStorage)!==expectedRaw)throw new Error('retirement-control-journal-changed');
 sessionStorage.setItem(liveControlStorage,raw);
 if(sessionStorage.getItem(liveControlStorage)!==raw)throw new Error('retirement-control-not-persisted');
}
function liveRetirementTarget(key){
 const p=rt.overview?.project,m=rt.overview?.models;
 if((rt.controlArchives||[]).length>=16||(rt.controlArchives||[]).some(raw=>{const r=JSON.parse(raw);return r.intent.ref===rt.ref&&r.intent.body.job_ref===key&&r.receipt.status==='saved';}))return null;
 if(apps[0]?.stage!==1||!p||p.project_ref!==rt.ref||m?.project_ref!==rt.ref||m.connected!==true||
  m.revision!==p.revision||m.input_version!==p.input_version||m.brief_sha256!==p.brief_sha256||
  !Array.isArray(m.active_jobs)||m.active_jobs.length!==0||!Array.isArray(m.jobs)||
  !Number.isSafeInteger(p.revision)||p.revision<0||!Number.isSafeInteger(p.input_version)||p.input_version<1||!liveControlHex(p.brief_sha256))return null;
 const jobs=m.jobs.filter(j=>j?.key===key);if(jobs.length!==1)return null;
 const job=jobs[0],o=job.retirement_offer;
 if(job.project_ref!==rt.ref||job.input_version!==p.input_version||job.brief_sha256!==p.brief_sha256||
  !['execution-unknown','failed-or-unknown'].includes(job.status)||job.retirement||o?.available!==true||o.blocked_reason!==null||
  o.job_ref!==job.key||o.job_request_sha256!==job.request_sha256||!liveControlHex(o.job_request_sha256)||!liveControlHex(o.job_snapshot_sha256))return null;
 return {ref:rt.ref,revision:p.revision,input_version:p.input_version,brief_sha256:p.brief_sha256,
  job_ref:o.job_ref,job_request_sha256:o.job_request_sha256,job_snapshot_sha256:o.job_snapshot_sha256};
}
async function liveControlEvidenceHash(e){
 const raw='{'+Object.keys(e).sort().map(k=>JSON.stringify(k)+':'+JSON.stringify(e[k])).join(',')+'}';
 return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(raw))),b=>b.toString(16).padStart(2,'0')).join('');
}
async function liveControlReceipt(record,a){
 if(!liveControlValid(record)||!await liveReceiptBound(record.intent,a)||a.execution_authorized!==false||!['saved','failed','known-unsent'].includes(a.status))return false;
 if(a.status!=='saved')return true;
 const b=record.intent.body,r=a.retirement,e=r?.evidence;
 if(a.target_key!==b.job_ref||r?.status!=='retired-no-resend'||r.action_key!==b.key||r.request_sha256!==a.request_sha256||
  r.job_request_sha256!==b.job_request_sha256||r.job_snapshot_sha256!==b.job_snapshot_sha256||
  !e||Object.keys(e).sort().join(',')!=='automatic_resend,basis,budget_refunded,filesystem,native_dispatch_observed,research_outcome,runtime_binding_sha256'||
  e.basis!=='never-admitted-no-runtime'||!['not-created','binding-only'].includes(e.filesystem)||!liveControlHex(e.runtime_binding_sha256)||
  e.native_dispatch_observed!==false||e.automatic_resend!==false||e.budget_refunded!==false||e.research_outcome!=='Unknown')return false;
 return r.evidence_sha256===await liveControlEvidenceHash(e);
}
async function liveControlObserve(record,a){
 if(rt.controlIntent!==record)return false;
 const bound=await liveControlReceipt(record,a);if(rt.controlIntent!==record||!bound)return false;
 const observed={...record,state:'observed',receipt:a};
 liveControlStore(observed);rt.controlIntent=observed;rt.controlHeld=false;
 return true; // The original rt.pending and its storage key are deliberately untouched.
}
async function liveRetirementStart(jobRef,userInput,confirmed){
 if(rt.busy||rt.loading||rt.controlHeld||rt.controlIntent||confirmed!==true||typeof userInput!=='string'||
  !userInput.trim()||new TextEncoder().encode(userInput).length>4096)return false;
 const target=liveRetirementTarget(jobRef);if(!target)return false;
 const original=rt.pending,epoch=rt.epoch;let record;
 rt.busy=true;
 try{
  const originalBytes=JSON.stringify(original),storedOriginal=sessionStorage.getItem('v7-pending-action');
  if(original&&(original.ref!==target.ref||original.path!==projectPath(target.ref,'models/actions')||
   original.body?.key!==jobRef||!await liveReceiptBound(original,{kind:'model-operation',key:jobRef,
    project_ref:target.ref,request_sha256:target.job_request_sha256})))return false;
  if(rt.pending!==original||JSON.stringify(rt.pending)!==originalBytes||sessionStorage.getItem('v7-pending-action')!==storedOriginal||
   rt.epoch!==epoch||rt.loading||rt.controlHeld||rt.controlIntent||
   JSON.stringify(liveRetirementTarget(jobRef))!==JSON.stringify(target))return false;
  const {ref,...body}=target;
  record={kind:'V7RetirementControlIntent.v1',state:'pending',intent:{ref,path:projectPath(ref,'models/retire'),
   body:{...body,key:crypto.randomUUID(),confirmed:true,user_input:userInput}},
   original_request:original?{ref:original.ref,key:original.body.key,request_sha256:target.job_request_sha256}:null};
  rt.controlIntent=record;rt.controlHeld=true;liveControlStore(record);
  const result=await liveRequest(record.intent.path,record.intent.body);
  const observed=await liveControlObserve(record,result);
  if(!observed&&rt.controlIntent===record)rt.controlError='retirement-control-outcome-unconfirmed';
  return observed;
 }catch(error){
  if(record&&rt.controlIntent===record&&error.receipt){
   try{if(await liveControlObserve(record,error.receipt))return true;}catch(_){/* Retain the original durable control. */}
  }
  if(record?rt.controlIntent===record:rt.epoch===epoch&&rt.pending===original)rt.controlError=error.message;
  return false;
 }finally{rt.busy=false;livePaint();}
}
async function liveRetirementRecover(){
 if(rt.busy||rt.loading)return false;
 if((rt.controlArchiveVerified===false||rt.controlJournalInvalid)&&!await liveControlArchiveRecover())return false;
 const record=rt.controlIntent;if(!record)return !rt.controlHeld;
 rt.busy=true;
 try{
  const value=await liveRequest(projectPath(record.intent.ref,'history'));
  if(rt.controlIntent!==record)return false;
  if(value.project_ref!==record.intent.ref||!Array.isArray(value.actions))throw new Error('retirement-control-history-unbound');
  const rows=value.actions.filter(a=>a?.key===record.intent.body.key);
  if(rows.length===1&&await liveControlObserve(record,rows[0]))return true;
  if(rt.controlIntent===record)rt.controlError='retirement-control-outcome-unconfirmed';return false;
 }catch(error){if(rt.controlIntent===record)rt.controlError=error.message;return false;}
 finally{rt.busy=false;livePaint();}
}
function liveControlArchiveBinding(record=rt.controlIntent){return JSON.stringify(record);}
function liveControlReceiptText(receipt){
 const {replayed,...body}=receipt;
 const canonical=v=>Array.isArray(v)?v.map(canonical):v&&typeof v==='object'?Object.fromEntries(Object.keys(v).sort().map(k=>[k,canonical(v[k])])):v;
 return JSON.stringify(canonical(body));
}
async function liveControlArchiveReceipt(record,value){
 if(value.project_ref!==record.intent.ref||!Array.isArray(value.actions))return false;
 const rows=value.actions.filter(a=>a?.key===record.intent.body.key);
 return rows.length===1&&await liveControlReceipt(record,record.receipt)&&await liveControlReceipt(record,rows[0])&&liveControlReceiptText(rows[0])===liveControlReceiptText(record.receipt);
}
async function liveRetirementArchive(binding,confirmed){
 const record=rt.controlIntent;
 if(rt.busy||rt.loading||rt.controlHeld||rt.controlArchiveVerified!==true||rt.controlJournalInvalid||apps[0]?.stage!==1||!record||record.intent.ref!==rt.ref||record.state!=='observed'||binding!==liveControlArchiveBinding(record)||confirmed!==true||(rt.controlArchives||[]).length>=16)return false;
 const original=rt.pending,originalBytes=JSON.stringify(original),epoch=rt.epoch,ref=rt.ref,archives=JSON.stringify(rt.controlArchives);let raw,pendingRaw;
 const owns=()=>rt.controlIntent===record&&liveControlArchiveBinding(record)===binding&&rt.pending===original&&JSON.stringify(rt.pending)===originalBytes&&rt.epoch===epoch&&rt.ref===ref&&apps[0]?.stage===1&&JSON.stringify(rt.controlArchives)===archives;
 const current=()=>{if(!owns())return false;const same=sessionStorage.getItem(liveControlStorage)===raw&&sessionStorage.getItem('v7-pending-action')===pendingRaw;if(!same){rt.controlHeld=true;rt.controlArchiveVerified=false;rt.controlJournalInvalid=true;}return same;};
 rt.busy=true;
 try{
  raw=sessionStorage.getItem(liveControlStorage);pendingRaw=sessionStorage.getItem('v7-pending-action');
  const saved=liveControlJournalRead(raw);
  if(JSON.stringify(saved.active)!==binding||JSON.stringify(saved.archives)!==archives){rt.controlJournalInvalid=true;rt.controlArchiveVerified=false;throw new Error('retirement-control-journal-changed');}
  const value=await liveRequest(projectPath(ref,'history'));if(!current())return false;
  const valid=await liveControlArchiveReceipt(record,value);if(!current())return false;
  if(!valid)throw new Error('retirement-control-archive-unconfirmed');
  const next=[...rt.controlArchives,binding];rt.controlHeld=true;
  try{liveControlJournalWrite(null,next,raw);}catch(error){rt.controlJournalInvalid=true;rt.controlArchiveVerified=false;throw error;}
  rt.controlArchives=next;rt.controlIntent=null;rt.controlArchiveVerified=true;rt.controlHeld=false;rt.controlError=null;return true;
 }catch(error){if(owns()){rt.controlHeld=true;rt.controlError=error.message;}return false;}
 finally{rt.busy=false;livePaint();}
}
async function liveControlArchiveRecover(){
 if(rt.busy||rt.loading||apps[0]?.stage!==1)return false;
 const prior=rt.controlIntent,priorBytes=JSON.stringify(prior),priorArchives=JSON.stringify(rt.controlArchives),original=rt.pending,originalBytes=JSON.stringify(original),epoch=rt.epoch,ref=rt.ref;
 const owns=()=>rt.controlIntent===prior&&JSON.stringify(prior)===priorBytes&&JSON.stringify(rt.controlArchives)===priorArchives&&rt.pending===original&&JSON.stringify(rt.pending)===originalBytes&&rt.epoch===epoch&&rt.ref===ref&&apps[0]?.stage===1;
 rt.busy=true;rt.controlHeld=true;rt.controlArchiveVerified=false;
 try{
  const raw=sessionStorage.getItem(liveControlStorage),pendingRaw=sessionStorage.getItem('v7-pending-action');
  let saved;
  try{saved=liveControlJournalRead(raw);}catch(error){rt.controlJournalInvalid=true;throw error;}
  const known=JSON.parse(priorArchives),core=r=>r&&JSON.stringify(Object.fromEntries(Object.entries(r).filter(([k])=>!['state','receipt'].includes(k))));
  const keepsActive=!prior||saved.active&&(JSON.stringify(saved.active)===priorBytes||prior.state==='pending'&&saved.active.state==='observed'&&core(saved.active)===core(prior))||saved.archives.includes(priorBytes);
  if(known.some((entry,i)=>saved.archives[i]!==entry)||!keepsActive){rt.controlJournalInvalid=true;throw new Error('retirement-control-memory-evidence-unpersisted');}
  const current=()=>{if(!owns())return false;const same=sessionStorage.getItem(liveControlStorage)===raw&&sessionStorage.getItem('v7-pending-action')===pendingRaw;if(!same){rt.controlHeld=true;rt.controlArchiveVerified=false;rt.controlJournalInvalid=true;}return same;};
  const histories=new Map();
  for(const entry of saved.archives){
   const archived=JSON.parse(entry),project=archived.intent.ref;
   if(!histories.has(project)){histories.set(project,await liveRequest(projectPath(project,'history')));if(!current())return false;}
   const valid=await liveControlArchiveReceipt(archived,histories.get(project));if(!current())return false;
   if(!valid)throw new Error('retirement-control-archive-unconfirmed');
  }
  if(!current())return false;
  rt.controlIntent=saved.active;rt.controlArchives=saved.archives;rt.controlArchiveVerified=true;rt.controlJournalInvalid=false;rt.controlHeld=!!saved.active;rt.controlError=null;return true;
 }catch(error){if(owns()){rt.controlHeld=true;rt.controlArchiveVerified=false;rt.controlError=error.message;}return false;}
 finally{rt.busy=false;livePaint();}
}
liveControlLoad();
