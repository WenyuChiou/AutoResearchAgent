/* Synthetic DOM + persisted intent; no browser/network/native/model. */
'use strict';
const assert=require('node:assert/strict'), fs=require('node:fs'), path=require('node:path'), vm=require('node:vm'), crypto=require('node:crypto');
const source=fs.readFileSync(process.argv[2]||path.join(__dirname,'../cli/research_workspace_native/web/stage-query-panel.js'),'utf8');
const h='1'.repeat(64), v='2'.repeat(64), tick=()=>new Promise(r=>setImmediate(r)), nodes=n=>[n,...n.children.flatMap(nodes)], clone=x=>JSON.parse(JSON.stringify(x));
class Element{
 constructor(tag){this.tagName=tag.toUpperCase();this.children=[];this.attrs={};this.dataset={};this._text='';}
 get textContent(){return this._text+this.children.map(n=>n.textContent).join('');}set textContent(v){this._text=String(v);this.replaceChildren();}
 get previousSibling(){return this.parent?.children[this.parent.children.indexOf(this)-1]||null;}
 get nextSibling(){return this.parent?.children[this.parent.children.indexOf(this)+1]||null;}
 append(...children){children.forEach(n=>{n.remove();n.parent=this;this.children.push(n);});}
 remove(){if(this.parent)this.parent.children=this.parent.children.filter(n=>n!==this);this.parent=null;}
 replaceChildren(...children){this.children.forEach(n=>n.parent=null);this.children=[];this.append(...children);}
 insertBefore(n,next){n.remove();n.parent=this;if(next)this.children.splice(this.children.indexOf(next),0,n);else this.children.push(n);}
 after(n){this.parent.insertBefore(n,this.nextSibling);}setAttribute(k,v){this.attrs[k]=v;}
 set innerHTML(_){throw Error('unsafe HTML');}
}
async function mount({server={view:{project_ref:'case',index_sha256:h,input_version:v,revision:1,history:[],model_execution:false,automatic_retry:false,budget:{attempts:0,seconds:0}},records:new Map()},storage=new Map(),mode='complete',transform=x=>x,storageError=false,enabled=true,beforeDigest=async()=>{},badOffer=false,offerError=null}={}){
 const html=new Element('html'),body=new Element('body'),content=new Element('main'),anchor=new Element('section');html.lang='en';html.dataset.atlasStage='1';html.append(body);body.append(content);content.id='atlas-content';anchor.id='atlas-stage-actions';content.append(anchor);
 const document={documentElement:html,createElement:tag=>new Element(tag),getElementById:id=>nodes(html).find(n=>n.id===id)}, calls=[],observers=[];
 const window={WORKSPACE_PLANNED_QUERIES:{enabled,project_ref:'case',index_sha256:h,input_version:v},WORKSPACE_HOST:{credential:'secret-memory-only'}};
 let uuid=0;
 const context=vm.createContext({document,window,TextEncoder,crypto:{subtle:{digest:async(...a)=>{await beforeDigest();return crypto.webcrypto.subtle.digest(...a);}},randomUUID:()=>`11111111-1111-1111-1111-${String(++uuid).padStart(12,'0')}`},MutationObserver:class{constructor(fn){observers.push(fn);}observe(){}},sessionStorage:{getItem:k=>storage.get(k)??null,setItem:(k,x)=>{if(storageError)throw Error('storage-failure');storage.set(k,x);},removeItem:k=>storage.delete(k)},fetch:async(url,opts)=>{
 calls.push({url,...opts});assert.equal(opts.headers.Authorization,'Bearer secret-memory-only');assert.equal(url.includes('secret-memory-only'),false);
 const response=x=>({ok:true,json:async()=>clone(transform(x))});
 if(opts.method==='POST'){
  assert.equal(storage.size,1,'local intent precedes POST');assert.equal([...storage.values()][0].includes('secret-memory-only'),false);
  const request=JSON.parse(opts.body),semantic=Object.fromEntries(Object.entries(request).filter(([k])=>k!=='revision').sort(([a],[b])=>a<b?-1:1));
  const row={client_key:request.key,request,request_sha256:crypto.createHash('sha256').update(JSON.stringify(semantic)).digest('hex'),status:mode==='unknown'?'execution-unknown':'completed',outcome:mode==='refused'?'refused-known-unsent':'observed',model_execution:false,automatic_retry:false,...(mode==='refused'?{error:{code:'query-admission-refused'}}:{})};
  server.records.set(request.key,row);server.view.history.push(clone(row));server.view.revision+=2;server.view.budget={attempts:1,seconds:32};
  if(mode==='loss')throw Error('response lost');return response(row);
 }
 if(url.endsWith('/offer') && offerError)return {ok:false,json:async()=>({error:offerError})};
 if(url.endsWith('/offer'))return response({offer_ref:'3'.repeat(64),offer_sha256:'3'.repeat(64),revision:server.view.revision,document:{project_ref:'case',index_sha256:badOffer?'4'.repeat(64):h,input_version:v,execution_authority:'separate-research-permit',backend:'openalex',arguments:{query:'source original 查询'},max_results:3,reserved_seconds:32,probe_timeout_seconds:30,timeout_seconds:2}});
 const action=url.match(/\/actions\/(.+)$/);if(action)return response(server.records.get(decodeURIComponent(action[1])));
 return response(server.view);
 }});vm.runInContext(source,context);const flush=async()=>{for(let i=0;i<12;i++)await tick();};await flush();
 const all=()=>nodes(html),panel=()=>document.getElementById('atlas-planned-queries'),buttons=()=>all().filter(n=>n.tagName==='BUTTON'),prepare=()=>buttons()[0],refresh=()=>buttons()[1],submit=()=>buttons()[2],checkbox=()=>all().find(n=>n.tagName==='INPUT'),form=()=>all().find(n=>n.tagName==='FORM');
 async function run(){await prepare().onclick();checkbox().checked=true;checkbox().onchange();await form().onsubmit({preventDefault(){}});await flush();}
 return {html,content,anchor,all,panel,prepare,refresh,submit,checkbox,form,run,flush,calls,storage,server,observers};
}
(async()=>{
 let count=0;
 const disabled=await mount({enabled:false});assert.equal(disabled.panel(),undefined);assert.equal(disabled.calls.length,0);count++;
 const a=await mount();assert.equal(a.calls.length,1);assert.equal(a.panel().previousSibling,a.anchor);assert.ok(a.panel().textContent.includes('remain unproven'));assert.equal(a.all().find(n=>n.tagName==='DETAILS').open,undefined);await a.prepare().onclick();assert.ok(a.panel().textContent.includes('source original 查询'));assert.equal(a.submit().disabled,true);await a.form().onsubmit({preventDefault(){}});assert.equal(a.calls.filter(x=>x.method==='POST').length,0);count++;
 for(const [lang,label]of[['zh-Hans','运行这一条查询'],['zh-Hant','執行這一條查詢'],['en','Run this one query']]){a.html.lang=lang;a.observers.forEach(fn=>fn());assert.equal(a.submit().textContent,label);}count++;
 const loss=await mount({mode:'loss'});await loss.run();assert.equal(loss.calls.filter(x=>x.method==='POST').length,1);assert.equal(loss.storage.size,0);assert.ok(loss.panel().textContent.includes('observation saved'));await loss.refresh().onclick();assert.equal(loss.calls.filter(x=>x.method==='POST').length,1);count++;
 const stored=new Map(),unknown=await mount({mode:'unknown',storage:stored});await unknown.run();assert.equal(stored.size,1);assert.equal(unknown.prepare().disabled,true);const reload=await mount({server:unknown.server,storage:stored});await reload.refresh().onclick();assert.equal(reload.calls.filter(x=>x.method==='POST').length,0);assert.equal(reload.prepare().disabled,true);count++;
 for(const mutation of [x=>({...x,request_sha256:'9'.repeat(64)}),x=>({...x,request:{...x.request,confirmed:false}}),x=>({...x,client_key:'other-key'}),x=>({...x,model_execution:true})]){
  const invalid=await mount({transform:x=>x.request?mutation(x):x});await invalid.run();assert.equal(invalid.calls.filter(x=>x.method==='POST').length,1);assert.equal(invalid.storage.size,1);assert.equal(invalid.prepare().disabled,true);assert.ok(!invalid.panel().textContent.includes('observation saved'));count++;
 }
 const storageFailure=await mount({storageError:true});await storageFailure.run();assert.equal(storageFailure.calls.filter(x=>x.method==='POST').length,0);assert.ok(storageFailure.panel().textContent.includes('nothing submitted'));count++;
 for(const code of ['query-budget-exhausted','query-project-denied']){const blocked=await mount({offerError:code});await blocked.prepare().onclick();assert.ok(blocked.panel().textContent.includes(code));assert.equal(blocked.calls.filter(x=>x.method==='POST').length,0);assert.equal(blocked.storage.size,0);count++;}
 const wrong=await mount({badOffer:true});await wrong.prepare().onclick();assert.equal(wrong.submit().disabled,true);assert.equal(wrong.calls.filter(x=>x.method==='POST').length,0);count++;
 const refused=await mount({mode:'refused'});await refused.run();assert.ok(refused.panel().textContent.includes('refused-known-unsent'));assert.ok(refused.panel().textContent.includes('query-admission-refused'));assert.equal(refused.storage.size,0);count++;
 let release,entered;const ready=new Promise(r=>entered=r),held=new Promise(r=>release=r),racy=await mount({beforeDigest:async()=>{entered();await held;}});await racy.prepare().onclick();racy.checkbox().checked=true;const first=racy.form().onsubmit({preventDefault(){}});await ready;await racy.form().onsubmit({preventDefault(){}});assert.equal(racy.calls.filter(x=>x.method==='POST').length,0);release();await first;assert.equal(racy.calls.filter(x=>x.method==='POST').length,1);count++;
 a.html.dataset.atlasStage='2';a.observers.forEach(fn=>fn());assert.equal(a.panel().hidden,true);count++;
 console.log(`PASS ${count} query UI cases; synthetic DOM only, no native/model/browser`);
})().catch(error=>{console.error(error);process.exitCode=1;});
