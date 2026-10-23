const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const context={};vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname,'renderer/src/canonical-stage2.js'),'utf8'),context);
const pin='a'.repeat(64),candidate={candidate_id:'synthetic-direction',version:1};
function fixture(version){
 const bridge={kind:'WorkspaceStage2BridgeReceipt',schema_version:'1.0.0',association:'explicit-operator-selected-binding',project_id:'synthetic-project',stage1_index_sha256:pin,original_stage1_lineage_attested:false,human_selection:'pending',stage3_authorized:false,formal_ready:false,improvement_demonstrated:false};
 for(const k of ['stage1_package_manifest_sha256','stage2_manifest_sha256','selection_sha256','brief_sha256','resources_sha256','source_snapshot_sha256','stored_packet_sha256','workflow_event_head'])bridge[k]=pin;
 const packet={schema_version:version,candidates:[candidate],literature:[],evidence:[]};
 if(version==='2.6.0')packet.entry={kind:'Stage2DirectRequestOrigin',schema_version:'1.0.0',request_text:'Synthetic research request',request_sha256:pin,binding_sha256:pin,stage1_lineage:false};
 return {payload:{index:{project_id:'synthetic-project'},index_sha256:pin,stage2:{kind:'WorkspaceStage2Attachment',schema_version:'1.0.0',project_id:'synthetic-project',stage1_index_sha256:pin,bridge_receipt:bridge,selection:{current_options:[{candidate}],evaluation_packet:packet},evaluation:{}},stage2_comparison:{schema_version:'1.0.0',directions:[candidate],literature:[],evidence:[]}},binding:{kind:'V7CanonicalSavedViewBinding',schema_version:'1.0.0',view_ref:'synthetic',project_id:'synthetic-project',fixture:false,index_sha256:pin,manifest_sha256:pin,payload_sha256:pin,stage2_attachment_sha256:pin}};
}
let assertions=0;
for(const version of ['1.0.0','2.0.0','2.1.0','2.2.0','2.3.0','2.4.0','2.5.0','2.6.0']){const f=fixture(version);assert.equal(context.canonicalStage2Validate(f.payload,f.binding).ok,true,version);assertions++;}
for(const alter of [f=>f.payload.stage2.selection.evaluation_packet.schema_version='2.7.0',f=>f.payload.stage2.bridge_receipt.formal_ready=true,f=>f.payload.stage2.bridge_receipt.stage3_authorized=true,f=>f.binding.index_sha256='b'.repeat(64),f=>f.payload.stage2_comparison.directions[0]={...candidate,version:2},f=>delete f.payload.stage2.selection.evaluation_packet.entry,f=>f.payload.stage2.selection.evaluation_packet.entry.stage1_lineage=true]){const f=fixture('2.6.0');alter(f);assert.equal(context.canonicalStage2Validate(f.payload,f.binding).ok,false);assertions++;}
console.log(JSON.stringify({kind:'canonical-stage2-version-binding-regression',assertions,failures:0,research_execution:false}));

async function originalReviews(){
 const crypto=require('node:crypto'),digest=value=>crypto.createHash('sha256').update(value).digest('hex');
 context.document={addEventListener(){}};context.canonicalHash=async value=>digest(value);
 vm.runInContext(fs.readFileSync(path.join(__dirname,'v9-review-reading.js'),'utf8'),context);
 const candidates=Array.from({length:4},(_,i)=>({candidate_id:'direction-'+i,version:1,question:'Question <script> '+i}));
 const packetText=JSON.stringify({candidates}),packetHash=digest(packetText);
 const records=candidates.flatMap(candidate=>['challenger','feasibility'].map(role=>({candidate_id:candidate.candidate_id,candidate_version:1,role,status:'complete',error:null,review:{snapshot_sha256:pin,assessment:{candidate_id:candidate.candidate_id,candidate_version:1,packet_sha256:packetHash,reason:'Original reason '+candidate.candidate_id+' '+role,next_step:'Original next step',checks:Object.fromEntries(['opportunity','value','answerability','materials','execution'].map(name=>[name,{rationale:'Rationale <img onerror=bad> '+name,next_check:'Next check '+name}]))}}})));
 const reviewsText=JSON.stringify(records),view={project_ref:'project-1',material_id:'packet-id',packet_text:packetText,packet_file_sha256:packetHash,packet_sha256:packetHash};
 view.independent_reviews={kind:'V9IndependentReviewReading',project_ref:view.project_ref,material_id:view.material_id,packet_file_sha256:packetHash,packet_sha256:packetHash,delivery_manifest_sha256:pin,snapshot_sha256:pin,batch_sha256:pin,reviews_file_sha256:digest(reviewsText),reviews_text:reviewsText,human_selection:'pending',formal_selection_available:false,stage3_execution_authorized:false,scientific_acceptance:false,delivery_status:'draft-not-ready',resolution_counts:{resolved:1,'resolution-required':3},recommendations_count:0};
 const reading=await context.n9ReadReviews(view);context.n2={model:{routes:candidates.map(candidate=>({candidate}))}};
 const original=JSON.stringify(reading.records),app={lang:'en'},opened={};
 Object.defineProperty(reading.records[0],'toJSON',{value(){throw Error('Closed review must not stringify');},configurable:true});
 let html=context.n9ReviewReader(app,reading,opened);assert.ok(html.includes('8')&&html.includes('Draft'));assert.ok(!html.includes('Original reason'));
 html=vm.runInContext("n9ReviewBodies.get('reader')()",context);assert.ok(html.includes('Question &lt;script&gt;'));assert.ok(!html.includes('<script>'));
 delete reading.records[0].toJSON;
 let rationaleCount=0;for(const record of records){const key=JSON.stringify([record.candidate_id,1,record.role]);const render=vm.runInContext('n9ReviewBodies.get('+JSON.stringify(key)+')',context);const body=render();assert.ok(body.includes(record.review.assessment.reason));for(const name of Object.keys(record.review.assessment.checks)){assert.ok(body.includes('Rationale &lt;img onerror=bad&gt; '+name));assert.ok(body.includes('Next check '+name));rationaleCount++;}const raw=vm.runInContext('n9ReviewBodies.get('+JSON.stringify(key+':json')+')()',context);assert.ok(raw.includes('packet_sha256'));}
 assert.equal(rationaleCount,40);assert.equal(JSON.stringify(reading.records),original);
 opened.reader=true;assert.match(context.n9ReviewReader({lang:'tw'},reading,opened),/data-n9-review-loaded="1"/);
 for(const alter of [v=>v.project_ref='other',v=>v.independent_reviews.reviews_file_sha256=pin,v=>v.independent_reviews.stage3_execution_authorized=true,v=>v.independent_reviews.packet_sha256=pin,v=>{const r=JSON.parse(v.independent_reviews.reviews_text);r[0].candidate_version=99;v.independent_reviews.reviews_text=JSON.stringify(r);v.independent_reviews.reviews_file_sha256=digest(v.independent_reviews.reviews_text)}]){const copy=JSON.parse(JSON.stringify(view));alter(copy);await assert.rejects(()=>context.n9ReadReviews(copy),/review-reading-binding-differs/);}
 console.log(JSON.stringify({kind:'original-review-reader-regression',records:8,rationales:40,next_checks:40,negative_cases:5,failures:0,research_execution:false}));
}
originalReviews().catch(error=>{console.error(error);process.exitCode=1;});
