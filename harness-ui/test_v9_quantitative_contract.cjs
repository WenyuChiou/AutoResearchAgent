'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {webcrypto,createHash}=require('node:crypto');
const read=name=>fs.readFileSync(path.join(__dirname,name),'utf8');
const copy=value=>JSON.parse(JSON.stringify(value));
const hash=bytes=>createHash('sha256').update(bytes).digest('hex');
function fixture(){
 const project='project-'+'a'.repeat(32),pin='b'.repeat(64),manifest='c'.repeat(64);
 const view={project_ref:project,input_version:1,direction_intent_sha256:pin,job:{plan_manifest_sha256:manifest,request_sha256:'d'.repeat(64)},
  revision:2,brief_sha256:pin,plan:{kind:'Stage3DirectionPlanningResult',question_plans:[{question_ref:'idea-a@1/core',method:'Check the source before research.',unknowns:['Access remains unknown.']}]}};
 const binding={project_ref:project,input_version:1,revision:2,brief_sha256:pin,parent_plan_manifest_sha256:manifest,parent_plan_sha256:'e'.repeat(64),plan_request_sha256:view.job.request_sha256};
 const revision={receipt_sha256:'f'.repeat(64),record:{kind:'revision',revision_number:11,binding,plan:copy(view.plan)}};
 view.feedback={binding};
 const data={rows:[{label:'Group A',n:7,share:1.25},{label:'Group B',n:null,share:3.5}]},bytes=Buffer.from(JSON.stringify(data));
 const source={id:'data',sha256:hash(bytes),bytes:bytes.length,description:'Synthetic group estimates, not individual records.'};
 const cells=i=>[{source:'data',pointer:'/rows/'+i+'/label'},{source:'data',pointer:'/rows/'+i+'/n'}];
 const guide={kind:'Stage3QuantitativePresentation',version:1,project_ref:project,input_version:1,direction_intent_sha256:pin,plan_manifest_sha256:manifest,
  question_ref:'idea-a@1/core',title:'Source-bound data',summary:'No study has run.',sources:[source],limitations:['Access unknown.'],
  tables:[{id:'counts',title:'Counts',context:'Synthetic groups.',columns:[{key:'label',label:'Group',type:'text',unit:''},{key:'count',label:'Count',type:'number',unit:'units'}],rows:[{id:'a',cells:cells(0)},{id:'b',cells:cells(1)}],notes:[]}],
  charts:[{type:'bar',title:'Counts',table:'counts',label:'label',group:null,values:['count']}],next_steps:[{pointer:'/question_plans/0/unknowns/0',quote:'Access remains unknown.'}]};
 const item={project_ref:project,stage:3,name:'stage3-quant-source-'+source.sha256+'.json',kind:'manual-file',status:'registered',id:'file-'+'1'.repeat(32),sha256:source.sha256,bytes:source.bytes};
 const catalog={materials:[item]};
 const ctx=vm.createContext({TextDecoder,Uint8Array,crypto:webcrypto});
 vm.runInContext(read('v9-research-guide-contract.js'),ctx);vm.runInContext(read('v9-quantitative-contract.js'),ctx);
 return {ctx,view,revision,guide,data,bytes,catalog,item};
}
test('original and manual display bindings preserve exact source values and nulls without mutation',()=>{
 const f=fixture(),before=JSON.stringify([f.view,f.guide,f.data]);
 f.ctx.v96ValidateQuant(f.guide,f.view);
 const model=f.ctx.v96ProjectQuant(f.guide,new Map([['data',f.data]]));
 assert.deepEqual(copy(model.tables[0].rows.map(row=>row.values)),[['Group A',7],['Group B',null]]);
 assert.equal(JSON.stringify([f.view,f.guide,f.data]),before);
 const manual={...copy(f.guide),revision_receipt_sha256:f.revision.receipt_sha256,revision_number:11};
 assert.equal(f.ctx.v96ValidateQuant(manual,f.view,f.revision),manual);
 assert.match(f.ctx.v96QuantName(f.view,f.revision),/^stage3-quantitative-f{64}\.json$/);
 assert.throws(()=>f.ctx.v96ValidateQuant(manual,f.view),/shape/);
});
test('project, input, intent, manifest, manual receipt and authority additions fail closed',()=>{
 const f=fixture();
 for(const [key,value] of [['project_ref','project-'+'2'.repeat(32)],['input_version','1'],['direction_intent_sha256','2'.repeat(64)],['plan_manifest_sha256','2'.repeat(64)],['question_ref','other']]){
  const g=copy(f.guide);g[key]=value;assert.throws(()=>f.ctx.v96ValidateQuant(g,f.view),/quantitative-guide-/);
 }
 for(const mutate of [g=>g.execution_authorized=true,g=>g.sources[0].url='https://invalid.example',g=>g.tables[0].rows[0].cells[0].value='invented',g=>g.next_steps[0].quote='Research is complete.']){
  const g=copy(f.guide);mutate(g);assert.throws(()=>f.ctx.v96ValidateQuant(g,f.view),/quantitative-guide-/);
 }
 const m={...copy(f.guide),revision_receipt_sha256:'0'.repeat(64),revision_number:11};
 assert.throws(()=>f.ctx.v96ValidateQuant(m,f.view,f.revision),/binding/);
});
test('catalog refuses foreign, unregistered, ambiguous, wrong hash and oversized files',()=>{
 const f=fixture();
 assert.equal(f.ctx.v96SourceMaterials(f.catalog,f.guide).get('data'),f.item);
 for(const patch of [{project_ref:'project-foreign'},{stage:2},{status:'uploading'},{sha256:'0'.repeat(64)},{bytes:f.item.bytes+1}]){
  assert.throws(()=>f.ctx.v96SourceMaterials({materials:[{...f.item,...patch}]},f.guide),/quantitative-guide-/);
 }
 assert.throws(()=>f.ctx.v96SourceMaterials({materials:[f.item,{...f.item,id:'file-'+'2'.repeat(32)}]},f.guide),/ambiguous/);
 const display={...f.item,name:f.ctx.v96QuantName(f.view),bytes:131073};
 assert.throws(()=>f.ctx.v96ChooseQuant({materials:[display]},f.view),/material/);
 assert.equal(f.ctx.v96ChooseQuant({materials:[]},f.view),null);
});
test('pointers reject inheritance, prototype keys, noncanonical indices, absent values and coercion',()=>{
 const f=fixture();
 for(const pointer of ['/rows/01/n','/rows/9/n','/rows/0/constructor','/rows/0/~2','/rows/0/not-found'])assert.throws(()=>f.ctx.v96Pointer(f.data,pointer),/quantitative-guide-/);
 assert.throws(()=>f.ctx.v96Pointer(Object.create({inherited:5}),'/inherited'),/pointer/);
 assert.equal(f.ctx.v96Pointer({'a/b':{'c~d':0}},'/a~1b/c~0d'),0);
 for(const value of ['7',false,{},[],Infinity,1e16]){
  const data=copy(f.data);data.rows[0].n=value;assert.throws(()=>f.ctx.v96ProjectQuant(f.guide,new Map([['data',data]])),/cell-type/);
 }
});
test('duplicates, incompatible units, unsupported chart kinds and missing sources are refused',()=>{
 const f=fixture();
 for(const mutate of [g=>g.tables.push(copy(g.tables[0])),g=>g.tables[0].columns[1].key='label',g=>g.tables[0].rows[1].id='a',g=>g.charts[0].type='html',g=>g.charts[0].values=['label'],g=>g.charts[0].group='label']){
  const g=copy(f.guide);mutate(g);assert.throws(()=>f.ctx.v96ValidateQuant(g,f.view),/quantitative-guide-/);
 }
 assert.throws(()=>f.ctx.v96ProjectQuant(f.guide,new Map()),/source-unavailable/);
 const mixed=copy(f.guide);mixed.tables[0].columns.push({key:'other',label:'Other',type:'number',unit:'seconds'});
 mixed.tables[0].rows.forEach((row,index)=>row.cells.push({source:'data',pointer:'/rows/'+index+'/share'}));
 mixed.charts[0].values.push('other');assert.throws(()=>f.ctx.v96ValidateQuant(mixed,f.view),/bar-units/);
 const data=copy(f.data);data.rows[1].label='Group A';assert.throws(()=>f.ctx.v96ProjectQuant(f.guide,new Map([['data',data]])),/duplicate-labels/);
});
test('bounded projection refuses more than 2048 cells without silently dropping records',()=>{
 const f=fixture(),g=copy(f.guide),table=g.tables[0];
 table.columns=Array.from({length:12},(_,i)=>({key:'c'+i,label:'Column '+i,type:'number',unit:'units'}));
 table.rows=Array.from({length:128},(_,i)=>({id:'r'+i,cells:Array.from({length:12},()=>({source:'data',pointer:'/rows/0/n'}))}));
 g.tables.push({...copy(table),id:'other'});
 assert.throws(()=>f.ctx.v96ValidateQuant(g,f.view),/cell-capacity/);
});
test('next-step text comes only from the same selected question and revision',()=>{
 const f=fixture();
 for(const step of [{pointer:'/question_plans/1/method',quote:'Check'},{pointer:'/question_plans/0/markdown',quote:'Check'},{pointer:'/question_plans/0/method',quote:'Invented'}]){
  const g=copy(f.guide);g.next_steps=[step];assert.throws(()=>f.ctx.v96ValidateQuant(g,f.view),/step-/);
 }
 const m={...copy(f.guide),revision_receipt_sha256:f.revision.receipt_sha256,revision_number:11};
 f.revision.record.plan.question_plans[0].unknowns[0]='A changed condition.';
 assert.throws(()=>f.ctx.v96ValidateQuant(m,f.view,f.revision),/step-quote/);
});
test('existing authenticated transport checks the actual JSON bytes before projection',async()=>{
 const f=fixture();let options;
 f.ctx.window={RESEARCH_PROJECTS:{credential:'synthetic-only'}};
 f.ctx.fetch=async(url,opts)=>{options=opts;return new Response(f.bytes);};
 const value=await f.ctx.v94FetchJson('/api/v9/files/'+f.item.id,524288,undefined,f.item);
 assert.equal(value.rows[0].n,7);assert.equal(options.headers.Authorization,'Bearer synthetic-only');
 f.ctx.fetch=async()=>new Response(Buffer.from(JSON.stringify({...f.data,extra:'changed'})));
 await assert.rejects(()=>f.ctx.v94FetchJson('/api/v9/files/'+f.item.id,524288,undefined,f.item),/byte-count|hash/);
});
