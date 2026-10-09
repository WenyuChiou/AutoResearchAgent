/* Synthetic DOM/HTTP regression: no actual browser, native session or model. */
"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path"), vm = require("node:vm"), crypto = require("node:crypto");
const source = fs.readFileSync(process.argv[2] || path.join(__dirname, "../cli/research_workspace_native/web/stage-panel.js"), "utf8"), h="1".repeat(64), version="2".repeat(64), src="3".repeat(64), secret="synthetic-memory-only-credential";
const nodes = n => [n, ...n.children.flatMap(nodes)], tick = () => new Promise(resolve=>setImmediate(resolve));
class Element {
  constructor(tag){this.tagName=tag.toUpperCase();this.children=[];this.attrs={};this.dataset={};this._text="";}
  get textContent(){return this._text+this.children.map(c=>c.textContent).join("");}set textContent(v){this._text=String(v);this.replaceChildren();}
  get options(){return this.children.filter(n=>n.tagName==="OPTION");}get value(){return this._value??this.options[0]?.value??"";}set value(v){this._value=String(v);}
  get previousSibling(){return this.parentNode?.children[this.parentNode.children.indexOf(this)-1]||null;}
  get nextSibling(){return this.parentNode?.children[this.parentNode.children.indexOf(this)+1]||null;}
  append(...children){children.forEach(n=>{n.remove();n.parentNode=this;this.children.push(n);});}
  remove(){if(this.parentNode)this.parentNode.children=this.parentNode.children.filter(n=>n!==this);this.parentNode=null;}
  replaceChildren(...children){this.children.forEach(n=>n.parentNode=null);this.children=[];this.append(...children);}
  insertBefore(n,next){n.remove();n.parentNode=this;if(next)this.children.splice(this.children.indexOf(next),0,n);else this.children.push(n);this.insertions=(this.insertions||0)+1;}
  before(n){this.parentNode.insertBefore(n,this);}after(n){this.parentNode.insertBefore(n,this.nextSibling);}setAttribute(k,v){this.attrs[k]=v;}
  set innerHTML(_){throw Error("unsafe HTML");}
}
const clone=x=>JSON.parse(JSON.stringify(x)), response=x=>({ok:true,json:async()=>clone(x)});
const view=()=>({project_ref:"case",project_id:"case-project",index_sha256:h,input_version:version,source_sha256:src,revision:1,history:[],history_count:0,input_status:{"1":"saved","2":"saved"},capabilities:{"1":["checkpoint-stage1","review-stage"],"2":["inspect-stage2","review-stage"]},native_execution:false,model_execution:false,next_stage_execution_authorized:false});
async function mount({server={view:view(),records:new Map()},storage=new Map(),mode="normal",transform=x=>x,storageError=false,enabled=true}={}){
  const html=new Element("html"),body=new Element("body"),content=new Element("main"),review=new Element("section");html.lang="en";html.dataset.atlasStage="1";content.id="atlas-content";review.id="atlas-stage-review";html.append(body);body.append(content);content.append(review);
  const document={documentElement:html,body,createElement:tag=>new Element(tag),getElementById:id=>nodes(html).find(n=>n.id===id)};
  const calls=[],observers=[],window={WORKSPACE_STAGE_ACTIONS:{enabled,project_ref:"case",index_sha256:h,input_version:version},WORKSPACE_HOST:{credential:secret},WORKSPACE_VIEW:{index:{project_id:"case-project"}},addEventListener(){}};
  let uuid=0;
  const context=vm.createContext({document,window,TextEncoder,crypto:{subtle:crypto.webcrypto.subtle,randomUUID:()=>"11111111-1111-1111-1111-"+String(++uuid).padStart(12,"0")},MutationObserver:class{constructor(callback){observers.push(callback);}observe(){}},sessionStorage:{getItem:key=>storage.get(key)??null,setItem:(key,value)=>{if(storageError)throw Error("storage unavailable");storage.set(key,value);},removeItem:key=>storage.delete(key)},
    fetch:async(url,opts)=>{
      calls.push({url,...opts});assert.equal(opts.headers.Authorization,"Bearer "+secret);assert.equal(url.includes(secret),false);
      if(opts.method==="POST"){
        assert.ok(storage.size,"intent must precede POST");assert.equal([...storage.values()][0].includes(secret),false);const request=JSON.parse(opts.body);
        const reviewAction=request.action==="review-stage",next=reviewAction?(request.decision==="request-next"?"blocked":"not-requested"):undefined;
        const result={kind:reviewAction?"WorkspaceStageReviewRecord":"WorkspaceStageActionResult",readiness:{status:"incomplete",blockers:["synthetic missing assessment"]},...(reviewAction?{decision:request.decision,note:request.note,next_stage_request:next,native_user_message_attested:false}:{}),execution_authorized:false};
        const row={client_key:request.key,stage:request.stage,action:request.action,request,status:mode==="unknown"?"execution-unknown":"completed",source_sha256:src,native_execution:false,model_execution:false,execution_authorized:false,...(mode==="unknown"?{}:{outcome:"succeeded",result})};
        server.records.set(request.key,row);const summary=clone(row);delete summary.result;if(row.result)summary.result_summary={kind:result.kind,readiness_status:result.readiness.status,blocker_count:1,next_stage_request:next};server.view.history.push(summary);server.view.history_count++;server.view.revision+=2;
        if(mode==="loss")throw Error("response lost after write");return response(transform(row));
      }
      const offer=url.match(/\/offers\/([12])\/(.+)$/);
      if(offer)return response({offer_ref:"4".repeat(64),offer_sha256:"4".repeat(64),revision:server.view.revision,document:{project_ref:"case",principal:"principal",index_sha256:h,input_version:version,source_sha256:src,stage:Number(offer[1]),action:offer[2],execution_authorized:false}});
      const action=url.match(/\/actions\/(.+)$/);if(action)return response(transform(server.records.get(decodeURIComponent(action[1]))));
      return response(transform(server.view));
    }});
  vm.runInContext(source,context);for(let i=0;i<12;i++)await tick();
  const all=()=>nodes(html),panel=()=>document.getElementById("atlas-stage-actions"),buttons=()=>all().filter(n=>n.tagName==="BUTTON"),check=()=>buttons()[0],refresh=()=>buttons()[1],form=()=>all().find(n=>n.tagName==="FORM"),select=()=>all().filter(n=>n.tagName==="SELECT");
  async function flush(){for(let i=0;i<12;i++)await tick();}
  async function submit(){await check().onclick();await flush();}
  async function reviewDecision(decision,confirmed=true,note="Review this exact saved source."){select()[1].value=decision;all().find(n=>n.tagName==="TEXTAREA").value=note;all().find(n=>n.tagName==="INPUT").checked=confirmed;form().onsubmit({preventDefault(){}});await flush();}
  return {html,content,review,document,window,server,storage,calls,observers,all,panel,check,refresh,select,flush,submit,reviewDecision};
}
(async()=>{
  const disabled=await mount({enabled:false});assert.equal(disabled.calls.length,0);assert.equal(disabled.panel(),undefined);
  const valid=await mount();assert.equal(valid.calls.length,1);assert.equal(valid.check().disabled,false);assert.equal(valid.window.WORKSPACE_STAGE_ACTIONS,undefined);assert.equal(valid.panel().previousSibling,valid.review);
  for(const [lang,label]of[["zh-Hans","检查本阶段"],["zh-Hant","檢查本階段"],["en","Check this stage"]]){valid.html.lang=lang;valid.observers.forEach(fn=>fn());assert.equal(valid.check().textContent,label);}assert.equal(valid.calls.filter(c=>c.method==="POST").length,0);
  await valid.submit();assert.equal(valid.calls.filter(c=>c.method==="POST").length,1);assert.equal(valid.storage.size,0);await valid.refresh().onclick();assert.equal(valid.calls.filter(c=>c.method==="POST").length,1);
  const loss=await mount({mode:"loss"});await loss.submit();assert.equal(loss.calls.filter(c=>c.method==="POST").length,1);assert.equal(loss.storage.size,0);assert.equal(loss.check().disabled,false);
  const stored=new Map(),unknown=await mount({mode:"unknown",storage:stored});await unknown.submit();assert.equal(unknown.check().disabled,true);assert.equal(stored.size,1);
  const reload=await mount({server:unknown.server,storage:stored,mode:"unknown"});await reload.refresh().onclick();assert.equal(reload.calls.filter(c=>c.method==="POST").length,0);assert.equal(reload.check().disabled,true);
  const wrong=await mount({transform:x=>({...x,index_sha256:"5".repeat(64)})});assert.equal(wrong.check().disabled,true);assert.equal(wrong.calls.filter(c=>c.method==="POST").length,0);
  const storageFailure=await mount({storageError:true});await storageFailure.submit();assert.equal(storageFailure.calls.filter(c=>c.method==="POST").length,0);
  const choice=await mount();await choice.reviewDecision("request-next",false);assert.equal(choice.calls.filter(c=>c.method==="POST").length,0);await choice.reviewDecision("request-next",true," ");assert.equal(choice.calls.filter(c=>c.method==="POST").length,0);
  await choice.reviewDecision("hold");assert.equal(choice.calls.filter(c=>c.method==="POST").length,1);assert.ok(!choice.panel().textContent.includes("Next-stage request recorded"),"hold is not a next-stage request");
  const blocked=await mount();await blocked.reviewDecision("request-next");assert.ok(!blocked.panel().textContent.includes("Next-stage request recorded"),"blocked request must not be shown as admitted/recorded awaiting authority");assert.ok(/blocked|阻塞|受阻/i.test(blocked.panel().textContent));
  const retained=valid.panel(),newReview=new Element("section");newReview.id="atlas-stage-review";valid.content.replaceChildren(newReview);valid.html.dataset.atlasStage="2";valid.observers.forEach(fn=>fn());assert.equal(valid.panel(),retained,"Atlas redraw retains stage service panel");assert.equal(retained.previousSibling,newReview);assert.equal(valid.select()[0].value,"2");const insertions=valid.content.insertions;valid.observers.forEach(fn=>fn());assert.equal(valid.content.insertions,insertions,"mount observer must not loop");
  console.log("Stage panel synthetic DOM: source binding, GET recovery, no resend, three languages, explicit review, next-stage status and remount PASS");
})().catch(error=>{console.error(error);process.exitCode=1;});
