const {test}=require('node:test');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'renderer/src/startup-recovery.js'),'utf8');
const required=['/project-bootstrap.js','/app.js','/project-stage2-selection.js'];
function page(store=new Map(),{storageUnavailable=false,paths=required}={}){
 const events={},listeners={},timers=[],address='http://127.0.0.1:12345/#project-original?stage=1&lang=en';
 const panel={hidden:false,dataset:{}},retry={hidden:true,dataset:{},addEventListener:(name,fn)=>listeners[name]=fn};
 const scripts=paths.map(src=>({tagName:'SCRIPT',src:'http://127.0.0.1:12345'+src}));
 const state={reloads:0};
 const on=(name,fn)=>events[name]=fn;
 const context={URL,Set,location:{href:address,origin:'http://127.0.0.1:12345',reload:()=>state.reloads++},
  document:{addEventListener:(name,fn)=>on('document:'+name,fn),getElementById:id=>id==='wiki-startup-recovery'?panel:retry,querySelectorAll:()=>scripts},
  window:{addEventListener:on},setTimeout:fn=>{timers.push(fn);return 1;},clearTimeout:()=>{},
  sessionStorage:{getItem:key=>{if(storageUnavailable)throw Error('blocked');return store.get(key)||null;},setItem:(key,val)=>store.set(key,val),removeItem:key=>store.delete(key)}};
 vm.runInNewContext(source,context);
 return {state,panel,retry,store,context,load:path=>events['document:load']({target:scripts.find(s=>s.src.endsWith(path))}),
  finish:()=>events.load(),timeout:()=>timers[0](),manual:()=>listeners.click()};
}
test('normal V9 and V7 startup never reloads',()=>{
 for(const paths of [required,required.slice(0,2)]){const p=page(new Map(),{paths});paths.forEach(p.load);p.finish();p.timeout();assert.equal(p.state.reloads,0);assert.equal(p.panel.hidden,true);}
});
for(const missing of required)test('one missing '+missing+' reloads once and preserves all pending bytes',()=>{
 const pending='{"status":"unknown","body":{"key":"original","input_version":1}}',store=new Map([['v7-pending-action',pending]]);
 const p=page(store);required.filter(x=>x!==missing).forEach(p.load);p.finish();p.timeout();assert.equal(p.state.reloads,1);assert.equal(store.get('v7-pending-action'),pending);
 const next=page(store);required.filter(x=>x!==missing).forEach(next.load);next.finish();next.timeout();assert.equal(next.state.reloads,0);assert.equal(next.panel.hidden,false);assert.equal(next.panel.dataset.state,'failed');assert.equal(next.retry.hidden,false);
 next.manual();assert.equal(next.state.reloads,1);assert.equal(store.get('v7-pending-action'),pending);
});
test('successful reopen removes only the private retry marker',()=>{
 const store=new Map([['v7-pending-action','saved-awaiting-history'],['v7-last-project-v1','project-original']]);
 page(store).finish();const p=page(store);required.forEach(p.load);p.finish();assert.deepEqual([...store],[['v7-pending-action','saved-awaiting-history'],['v7-last-project-v1','project-original']]);assert.equal(p.state.reloads,0);
});
test('storage unavailable has visible manual recovery and no automatic loop',()=>{
 const p=page(new Map(),{storageUnavailable:true});p.finish();p.timeout();assert.equal(p.state.reloads,0);assert.equal(p.panel.dataset.state,'failed');p.manual();assert.equal(p.state.reloads,1);
});
test('stalled loading has a bounded timeout; late load cannot restart again',()=>{
 const p=page();p.timeout();required.forEach(p.load);p.finish();assert.equal(p.state.reloads,1);assert.equal(p.panel.hidden,false);
});
test('an unrelated script load cannot mark missing startup resources ready',()=>{
 const p=page();p.load('/not-required');p.finish();assert.equal(p.state.reloads,1);assert.equal(p.panel.hidden,false);
});
