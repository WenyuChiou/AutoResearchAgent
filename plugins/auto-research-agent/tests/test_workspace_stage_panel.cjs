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
async function mount({server={view:view(),records:new Map()},storage=new Map(),mode="normal",transform=x=>x,storageError=false,enabled=true,readiness="incomplete",blockers=["synthetic missing assessment"],beforeDigest=async()=>{},beforeActionGet=async()=>{}}={}){
  const html=new Element("html"),body=new Element("body"),content=new Element("main"),review=new Element("section");html.lang="en";html.dataset.atlasStage="1";content.id="atlas-content";review.id="atlas-stage-review";html.append(body);body.append(content);content.append(review);
  const document={documentElement:html,body,createElement:tag=>new Element(tag),getElementById:id=>nodes(html).find(n=>n.id===id)};
  const calls=[],observers=[],window={WORKSPACE_STAGE_ACTIONS:{enabled,project_ref:"case",index_sha256:h,input_version:version},WORKSPACE_HOST:{credential:secret},WORKSPACE_VIEW:{index:{project_id:"case-project"}},addEventListener(){}};
  let uuid=0;
  const context=vm.createContext({document,window,TextEncoder,crypto:{subtle:{digest:async(...args)=>{await beforeDigest();return crypto.webcrypto.subtle.digest(...args);}},randomUUID:()=>"11111111-1111-1111-1111-"+String(++uuid).padStart(12,"0")},MutationObserver:class{constructor(callback){observers.push(callback);}observe(){}},sessionStorage:{getItem:key=>storage.get(key)??null,setItem:(key,value)=>{if(storageError)throw Error("storage unavailable");storage.set(key,value);},removeItem:key=>storage.delete(key)},
    fetch:async(url,opts)=>{
      calls.push({url,...opts});assert.equal(opts.headers.Authorization,"Bearer "+secret);assert.equal(url.includes(secret),false);
      if(opts.method==="POST"){
        assert.ok(storage.size,"intent must precede POST");assert.equal([...storage.values()][0].includes(secret),false);const request=JSON.parse(opts.body);
        const reviewAction=request.action==="review-stage",next=reviewAction?(request.decision==="request-next"?(["pass","ready"].includes(readiness)?"recorded-awaiting-execution-authority":"blocked"):"not-requested"):undefined;
        const result={kind:reviewAction?"WorkspaceStageReviewRecord":"WorkspaceStageActionResult",readiness:{status:readiness,blockers:clone(blockers)},...(reviewAction?{decision:request.decision,note:request.note,next_stage_request:next,native_user_message_attested:false}:{}),execution_authorized:false};
        if(!reviewAction){if(request.stage===1)Object.assign(result,{ledger_valid:true,handoff:{papers:[{work_id:"p1"},{work_id:"p2"}]},checkpoint:{stage_result:{outputs:[{path:"raw/candidate.json"},{path:"raw/claims.json"},{path:"raw/decisions.json"},{path:"raw/handoff.json"}]}}});else result.completion={research_delivery_ready:true,assessment_status:"missing",stage2_complete:false,stage3_execution_authorized:false};}
        const row={client_key:request.key,stage:request.stage,action:request.action,request,status:mode==="unknown"?"execution-unknown":"completed",source_sha256:src,native_execution:false,model_execution:false,execution_authorized:false,...(mode==="unknown"?{}:{outcome:"succeeded",result})};
        server.records.set(request.key,row);const summary=clone(row);delete summary.result;if(row.result)summary.result_summary={kind:result.kind,readiness_status:result.readiness.status,blocker_count:result.readiness.blockers.length,decision:result.decision,next_stage_request:next};server.view.history.push(summary);server.view.history_count++;server.view.revision+=2;
        if(mode==="loss")throw Error("response lost after write");return response(transform(row));
      }
      const offer=url.match(/\/offers\/([12])\/(.+)$/);
      if(offer)return response({offer_ref:"4".repeat(64),offer_sha256:"4".repeat(64),revision:server.view.revision,document:{project_ref:"case",principal:"principal",index_sha256:h,input_version:version,source_sha256:src,stage:Number(offer[1]),action:offer[2],execution_authorized:false}});
      const action=url.match(/\/actions\/(.+)$/);if(action){await beforeActionGet(decodeURIComponent(action[1]));return response(transform(server.records.get(decodeURIComponent(action[1]))));}
      return response(transform(server.view));
    }});
  vm.runInContext(source,context);for(let i=0;i<12;i++)await tick();
  const all=()=>nodes(html),panel=()=>document.getElementById("atlas-stage-actions"),buttons=()=>all().filter(n=>n.tagName==="BUTTON"),check=()=>buttons()[0],refresh=()=>buttons()[1],form=()=>all().find(n=>n.tagName==="FORM"),select=()=>all().filter(n=>n.tagName==="SELECT");
  async function flush(){for(let i=0;i<12;i++)await tick();}
  async function submit(){await check().onclick();await flush();}
  async function reviewDecision(decision,confirmed=true,note="Review this exact saved source."){select()[1].value=decision;all().find(n=>n.tagName==="TEXTAREA").value=note;all().find(n=>n.tagName==="INPUT").checked=confirmed;const completion=form().onsubmit({preventDefault(){}});assert.equal(typeof completion?.then,"function","review submit must expose its complete asynchronous action");await completion;await flush();}
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
  const summary=instance=>instance.all().find(n=>n.className==="stage-check-summary"), badge=instance=>nodes(summary(instance)).find(n=>n.className==="stage-check-badge");
  const passed=await mount({readiness:"pass",blockers:[]});assert.ok(summary(passed).textContent.includes("No check recorded"));assert.equal(passed.calls.length,1);
  await passed.submit();assert.equal(badge(passed).dataset.state,"pass");assert.ok(summary(passed).textContent.includes("Check passed"));assert.ok(summary(passed).textContent.includes("Ledger validation passed"));assert.ok(summary(passed).textContent.includes("Papers in the handoff: 2"));assert.ok(summary(passed).textContent.includes("raw/handoff.json"));assert.ok(summary(passed).textContent.includes("No blocking items"));assert.equal(passed.calls.length,5,"result summary adds no automatic I/O");
  const callsBeforeDetail=passed.calls.length;await nodes(summary(passed)).find(n=>n.tagName==="BUTTON").onclick();assert.equal(passed.calls.length,callsBeforeDetail,"already received check needs no repeat GET");
  await passed.reviewDecision("request-next");assert.equal(badge(passed).dataset.state,"pass","review intent must not replace the check result");assert.ok(summary(passed).textContent.includes("Ledger validation passed"));assert.ok(!summary(passed).textContent.includes("Next-stage request recorded"));
  for(const [lang,text]of[["zh-Hans","检查通过"],["zh-Hant","檢查通過"],["en","Check passed"]]){passed.html.lang=lang;passed.observers.forEach(fn=>fn());assert.ok(summary(passed).textContent.includes(text));}
  const reloaded=await mount({server:passed.server});assert.equal(reloaded.calls.length,1,"reload only reads existing history");assert.equal(badge(reloaded).dataset.state,"pass");assert.ok(!summary(reloaded).textContent.includes("Ledger validation passed"));await nodes(summary(reloaded)).find(n=>n.tagName==="BUTTON").onclick();assert.ok(summary(reloaded).textContent.includes("Ledger validation passed"));assert.equal(reloaded.calls.length,2);assert.equal(reloaded.calls.filter(c=>c.method==="POST").length,0);
  const stageBlocked=await mount({readiness:"blocked",blockers:["closest-work-unverified","extraction-incomplete"]});await stageBlocked.submit();assert.equal(badge(stageBlocked).dataset.state,"blocked");assert.ok(summary(stageBlocked).textContent.includes("Closest related works need verification"));assert.ok(summary(stageBlocked).textContent.includes("Evidence extraction is incomplete"));stageBlocked.html.lang="zh-Hant";stageBlocked.observers.forEach(fn=>fn());assert.ok(summary(stageBlocked).textContent.includes("最接近的相關文獻仍需核驗"));
  const stage2=await mount({readiness:"incomplete",blockers:[{check_id:"independent-assessment",reason:"Retained source: independent assessment missing."}]});stage2.html.dataset.atlasStage="2";stage2.observers.forEach(fn=>fn());await stage2.submit();assert.equal(badge(stage2).dataset.state,"incomplete");assert.ok(summary(stage2).textContent.includes("Retained source: independent assessment missing."));assert.ok(summary(stage2).textContent.includes("Independent assessment: not supplied"));assert.ok(summary(stage2).textContent.includes("Delivery content: ready for review"));assert.equal(stage2.calls.filter(c=>c.method==="POST").length,1);
  const newFailure=clone(passed.server.view.history.find(r=>r.action==="checkpoint-stage1"));newFailure.client_key="failed-check";newFailure.request.key="failed-check";newFailure.status="failed";newFailure.error={code:"synthetic-check-failure"};passed.server.view.history.push(newFailure);passed.server.view.history_count++;passed.server.view.revision++;
  const failedLatest=await mount({server:passed.server});assert.equal(badge(failedLatest).dataset.state,"failed");assert.ok(!summary(failedLatest).textContent.includes("Check passed"),"new failure supersedes earlier success");assert.ok(summary(failedLatest).textContent.includes("synthetic-check-failure"));assert.equal(failedLatest.calls.length,1);
  assert.equal(badge(unknown).dataset.state,"execution-unknown");assert.ok(!summary(unknown).textContent.includes("Check passed"));
  const truncatedView=view();truncatedView.history_count=65;const truncated=await mount({server:{view:truncatedView,records:new Map()}});assert.ok(summary(truncated).textContent.includes("outside this history window"));assert.ok(!summary(truncated).textContent.includes("No check recorded"));assert.equal(truncated.calls.length,1);
  const untrusted=clone(passed.server.view);untrusted.history=[clone(untrusted.history.find(r=>r.action==="checkpoint-stage1"))];untrusted.history[0].source_sha256="9".repeat(64);untrusted.history[0].result_summary.readiness_status="pass";
  const badHistory=await mount({server:{view:untrusted,records:new Map()}});assert.ok(!badHistory.panel().textContent.includes("Check passed"));assert.equal(badge(badHistory),undefined,"invalid initial history cannot become a saved pass");
  let tamper=false;const trustedBlocked=await mount({readiness:"blocked",blockers:["closest-work-unverified"],transform:x=>{if(!tamper||!x.history)return x;const changed=clone(x);changed.revision++;changed.history[0].source_sha256="9".repeat(64);changed.history[0].result_summary.readiness_status="pass";return changed;}});await trustedBlocked.submit();tamper=true;await trustedBlocked.refresh().onclick();assert.equal(badge(trustedBlocked).dataset.state,"blocked","bad refresh cannot replace prior verified check");assert.ok(summary(trustedBlocked).textContent.includes("latest server state is not verified"));assert.ok(!summary(trustedBlocked).textContent.includes("Check passed"));
  const changedPending=await mount({readiness:"blocked",blockers:["closest-work-unverified"],transform:x=>{if(!x.result)return x;const changed=clone(x);changed.request.note="Changed response payload";changed.result.readiness={status:"pass",blockers:[]};return changed;}});await changedPending.submit();assert.equal(badge(changedPending).dataset.state,"blocked","rejected pending response cannot poison check cache");assert.ok(!summary(changedPending).textContent.includes("Check passed"));assert.equal(changedPending.storage.size,1);assert.equal(changedPending.calls.filter(c=>c.method==="POST").length,1);
  const wrongDetail=await mount({server:stageBlocked.server,transform:x=>{if(!x.result)return x;const changed=clone(x);changed.client_key=changed.request.key="foreign-stage-key";changed.stage=changed.request.stage=2;changed.action=changed.request.action="inspect-stage2";changed.result.readiness={status:"pass",blockers:["UNEXPECTED STAGE2 RESULT"]};return changed;}});await nodes(summary(wrongDetail)).find(n=>n.tagName==="BUTTON").onclick();assert.equal(badge(wrongDetail).dataset.state,"blocked");assert.ok(!wrongDetail.panel().textContent.includes("UNEXPECTED STAGE2 RESULT"));assert.equal(wrongDetail.calls.filter(c=>c.method==="POST").length,0);
  let releaseDigest,digestEntered;const digestGate=new Promise(resolve=>releaseDigest=resolve),enteredDigest=new Promise(resolve=>digestEntered=resolve);
  const heldReview=await mount({beforeDigest:()=>{digestEntered();return digestGate;}});let reviewFinished=false;
  const awaitingReview=heldReview.reviewDecision("hold").then(()=>{reviewFinished=true;});await enteredDigest;
  assert.equal(reviewFinished,false,"review handler must remain awaited while digest is unfinished");assert.equal(heldReview.calls.filter(c=>c.method==="POST").length,0);
  releaseDigest();await awaitingReview;assert.equal(reviewFinished,true);assert.equal(heldReview.calls.filter(c=>c.method==="POST").length,1,"awaited review finishes exactly one durable action");assert.equal(heldReview.storage.size,0);
  console.log("Review submit awaits the asynchronous digest and recovery boundary PASS");
  const recordCards=instance=>instance.all().filter(n=>n.className==="stage-action-record");
  const detailCards=instance=>instance.all().filter(n=>n.tagName==="ARTICLE"&&n.children.some(child=>child.tagName==="H3"));
  const stageReview=await mount({readiness:"ready",blockers:[]});stageReview.html.dataset.atlasStage="2";stageReview.observers.forEach(fn=>fn());await stageReview.submit();
  const originalNote="Keep this version · 保留原稿\nReason: <b>await researcher choice</b> / 等待研究者決定";
  await stageReview.reviewDecision("hold",true,originalNote);assert.equal(stageReview.server.view.history.length,2);
  const savedReview=stageReview.server.view.history.find(row=>row.action==="review-stage");assert.equal(savedReview.result_summary.decision,"hold");
  const reviewReload=await mount({server:stageReview.server});reviewReload.html.dataset.atlasStage="2";reviewReload.observers.forEach(fn=>fn());
  assert.equal(badge(reviewReload).dataset.state,"ready");assert.equal(detailCards(reviewReload).length,0,"reload has no transient details");
  const [checkCard,reviewCard]=recordCards(reviewReload);assert.ok(!nodes(checkCard).some(n=>n.className==="stage-review-decision"),"a check is not a review decision");
  assert.ok(!reviewCard.textContent.includes("ready · 0 blockers"),"review readiness must not look like a new check");
  for(const [lang,label]of[["en","Review decision: Hold this stage"],["zh-Hans","审阅决定: 暂留本阶段"],["zh-Hant","審閱決定: 暫留本階段"]]){
    reviewReload.html.lang=lang;reviewReload.observers.forEach(fn=>fn());const card=recordCards(reviewReload)[1];
    assert.ok(card.textContent.includes(label));const preserved=nodes(card).find(n=>n.className==="stage-review-note");
    assert.equal(preserved.textContent,originalNote);assert.equal(preserved.translate,false);assert.equal(preserved.attrs.style,"white-space: pre-wrap");
  }
  assert.equal(reviewReload.calls.length,1,"durable review history renders directly from the single initial GET");assert.equal(reviewReload.calls.filter(c=>c.method==="POST").length,0);
  await nodes(summary(reviewReload)).find(n=>n.tagName==="BUTTON").onclick();assert.equal(detailCards(reviewReload).length,1);assert.ok(detailCards(reviewReload)[0].textContent.startsWith("Stage 2"));
  reviewReload.select()[0].value="1";reviewReload.select()[0].onchange();assert.equal(detailCards(reviewReload).length,0,"manual stage selection clears the other stage's transient details");
  const stageOne=await mount({readiness:"blocked",blockers:["stage-one-only-blocker"]});await stageOne.submit();assert.ok(detailCards(stageOne)[0].textContent.includes("stage-one-only-blocker"));
  const beforeStageSwitch=stageOne.calls.length;stageOne.html.dataset.atlasStage="2";stageOne.observers.forEach(fn=>fn());assert.equal(detailCards(stageOne).length,0,"sidebar stage change clears Stage 1 details");assert.ok(!summary(stageOne).textContent.includes("stage-one-only-blocker"));assert.equal(stageOne.calls.length,beforeStageSwitch,"stage selection does not send or recover an action");
  const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};
  const detailRaceGate=deferred(),detailRaceEntered=deferred();
  const switchedDetail=await mount({server:stageOne.server,beforeActionGet:()=>{detailRaceEntered.resolve();return detailRaceGate.promise;}});
  const delayedDetail=nodes(summary(switchedDetail)).find(n=>n.tagName==="BUTTON").onclick();await detailRaceEntered.promise;
  switchedDetail.select()[0].value="2";switchedDetail.select()[0].onchange();detailRaceGate.resolve();await delayedDetail;
  assert.equal(detailCards(switchedDetail).length,0,"a prior stage's delayed details must not reappear after switching stage");assert.equal(switchedDetail.calls.filter(c=>c.method==="POST").length,0);
  const firstSaved=clone([...stageOne.server.records.values()][0]),lastSaved=clone(firstSaved);
  firstSaved.result.note="OLDER SAVED DETAIL";lastSaved.client_key=lastSaved.request.key="22222222-2222-2222-2222-222222222222";lastSaved.result.note="LATEST SAVED DETAIL";
  const raceView=clone(stageOne.server.view);const firstSummary=clone(raceView.history[0]),lastSummary=clone(firstSummary);lastSummary.client_key=lastSummary.request.key=lastSaved.client_key;raceView.history=[firstSummary,lastSummary];raceView.history_count=2;
  const firstGate=deferred(),lastGate=deferred(),firstEntered=deferred(),lastEntered=deferred();
  const sameStage=await mount({server:{view:raceView,records:new Map([[firstSaved.client_key,firstSaved],[lastSaved.client_key,lastSaved]])},beforeActionGet:key=>{if(key===firstSaved.client_key){firstEntered.resolve();return firstGate.promise;}lastEntered.resolve();return lastGate.promise;}});
  const firstDetail=nodes(recordCards(sameStage)[0]).find(n=>n.tagName==="BUTTON").onclick();await firstEntered.promise;
  const lastDetail=nodes(recordCards(sameStage)[1]).find(n=>n.tagName==="BUTTON").onclick();await lastEntered.promise;
  lastGate.resolve();await lastDetail;assert.ok(detailCards(sameStage)[0].textContent.includes("LATEST SAVED DETAIL"));
  firstGate.resolve();await firstDetail;assert.ok(detailCards(sameStage)[0].textContent.includes("LATEST SAVED DETAIL"));assert.ok(!detailCards(sameStage)[0].textContent.includes("OLDER SAVED DETAIL"),"a slower prior detail cannot replace the last requested detail");assert.equal(sameStage.calls.filter(c=>c.method==="POST").length,0);
  const foreign=recordCards(sameStage)[0];sameStage.select()[0].value="2";sameStage.select()[0].onchange();await nodes(foreign).find(n=>n.tagName==="BUTTON").onclick();assert.equal(detailCards(sameStage).length,0,"other-stage history remains GET-only and cannot display details in the selected stage");
  console.log("Deferred stage-switch details and same-stage last-request-wins PASS");
  console.log("Restored review decisions, original notes, check/review separation and cross-stage details PASS");
  console.log("Stage panel synthetic DOM: source binding, GET recovery, no resend, three languages, explicit review, next-stage status and remount PASS; visible latest result summary PASS");
})().catch(error=>{console.error(error);process.exitCode=1;});
