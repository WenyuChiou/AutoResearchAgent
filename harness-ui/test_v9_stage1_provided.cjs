const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),test=require('node:test');
function fixture({fail=null,cache={}}={}){
 const listeners={},calls=[],rt={ref:'project-a',overview:{project:{revision:8,input_version:1,brief_sha256:'b'.repeat(64)},stage1:{ledger:{state_sha256:'a'.repeat(64)}}}};
 const material={id:'file-a',project_ref:'project-a',stage:1,kind:'manual-file',status:'registered',sha256:'c'.repeat(64)};
 let serial=0;
 const ctx={console,JSON,Number,Array,Object,crypto:{randomUUID:()=>String(++serial)},rt,
  sessionStorage:{getItem:k=>cache[k]??null,setItem:(k,v)=>cache[k]=v},
  m9:{catalog:{stage1_provided_admission:true}},m9Card:()=>'<article>Original material</article>',m9Current:()=>[material],
  rl:(_zh,en)=>en,rx:x=>String(x).replaceAll('<','&lt;').replaceAll('"','&quot;'),
  document:{addEventListener:(kind,fn)=>(listeners[kind]??=[]).push(fn)},livePaint(){},m9Load:async()=>{},
  liveRefresh:async()=>{rt.overview.project.revision=10;rt.overview.stage1.ledger.state_sha256='d'.repeat(64);},
  canonicalOldRequest:async(url,body)=>{calls.push(JSON.parse(JSON.stringify({url,body})));if(fail){const e=fail;fail=null;throw e;}return {key:body.key,status:'saved'};}};
 vm.createContext(ctx);vm.runInContext(fs.readFileSync(path.join(__dirname,'v9-stage1-provided.js'),'utf8'),ctx);
 async function fill(){
  for(const [key,value] of Object.entries({title:'Authored test',authors:'First Author\nSecond Author',year:'2024',version:'v1',url:'https://example.org/test',type:'text/plain',reason:'Engineering only'})){
   for(const fn of listeners.input)fn({target:{matches:()=>true,dataset:{providedId:material.id,providedField:key},value}});
  }
 }
 async function click(){const button={dataset:{providedSubmit:material.id}};for(const fn of listeners.click)await fn({target:{closest:()=>button},preventDefault(){}});}
 return {ctx,calls,rt,material,cache,fill,click,html:()=>ctx.m9Card(material),setFail:e=>{fail=e;}};
}
test('ordinary fields produce the existing Record shape and keep result visible per material',async()=>{
 const f=fixture();await f.fill();assert.match(f.html(),/<textarea[^>]*data-provided-field="authors"/);
 await f.click();assert.deepEqual(f.calls[0].body.record.authors,['First Author','Second Author']);
 assert.deepEqual(Object.keys(f.calls[0].body.record).sort(),['authors','title','version','year']);
 assert.equal(f.calls[0].body.source_uri,'https://example.org/test');assert.match(f.html(),/data-provided-form="file-a" open/);assert.match(f.html(),/Receipt: 1/);
 assert.doesNotMatch(f.ctx.m9Card({...f.material,id:'file-b'}),/Receipt: 1/);
});
test('missing ledger produces visible error and zero requests',async()=>{
 const f=fixture();await f.fill();f.rt.overview.stage1.ledger=null;await f.click();assert.equal(f.calls.length,0);assert.match(f.html(),/current-ledger-required/);assert.match(f.html(),/data-provided-form="file-a" open/);
});
test('same request survives refresh and page reconstruction without a new key',async()=>{
 const f=fixture();await f.fill();await f.click();await f.click();assert.deepEqual(f.calls[1],f.calls[0]);
 const reopened=fixture({cache:f.cache});reopened.rt.overview.project.revision=10;await reopened.fill();await reopened.click();assert.deepEqual(reopened.calls[0],f.calls[0]);
});
test('exact receipt-free stale refusals allow an explicit retry with fresh bindings',async()=>{
 for(const code of ['stale-revision','stage1-ledger-state-stale']){
  const f=fixture({fail:Object.assign(Error(code),{status:409})});await f.fill();await f.click();assert.equal(f.calls.length,1);await f.click();assert.notEqual(f.calls[1].body.key,f.calls[0].body.key);assert.equal(f.calls[1].body.revision,10);assert.equal(f.calls[1].body.ledger_state_sha256,'d'.repeat(64));
 }
});
test('uncertain or receipt-bearing failures keep the exact request',async()=>{
 for(const error of [Error('network'),Object.assign(Error('stale-revision'),{status:503}),Object.assign(Error('stage1-ledger-state-stale'),{status:409,receipt:{status:'execution-unknown'}})]){
  const f=fixture({fail:error});await f.fill();await f.click();f.rt.overview.project.revision=10;await f.click();assert.deepEqual(f.calls[1],f.calls[0]);
 }
});
test('HTTP 200 unknown receipts remain unconfirmed on same-key replay',async()=>{
 const f=fixture();f.ctx.canonicalOldRequest=async(url,body)=>{f.calls.push({url,body:JSON.parse(JSON.stringify(body))});return {key:body.key,status:'execution-unknown'};};
 await f.fill();await f.click();assert.match(f.html(),/Registration unconfirmed/);assert.doesNotMatch(f.html(),/Registered; still/);
 await f.click();assert.deepEqual(f.calls[1],f.calls[0]);assert.match(f.html(),/Registration unconfirmed/);
});
