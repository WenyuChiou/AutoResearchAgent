/* One explicitly admitted Stage1 query. Reconnect reads durable history only. */
(() => {
  "use strict";
  const c=window.WORKSPACE_PLANNED_QUERIES, host=window.WORKSPACE_HOST;
  delete window.WORKSPACE_PLANNED_QUERIES;
  const hash=x=>typeof x==="string" && /^[a-f0-9]{64}$/.test(x);
  if(!c?.enabled || !/^[A-Za-z0-9_-]{1,64}$/.test(c.project_ref) || !hash(c.index_sha256) || !hash(c.input_version) || !host?.credential)return;
  const base="/api/stages/projects/"+encodeURIComponent(c.project_ref)+"/queries";
  const storage="atlas-query-intent:"+c.project_ref+":"+c.index_sha256+":"+c.input_version;
  const labels={
    title:["Run a planned Stage 1 query","运行 Stage 1 计划查询","執行 Stage 1 計畫查詢"],
    boundary:["Uses a confirmed scope and a separate research permit. One backend attempt is retained; a completed query does not mean Stage 1 is complete. Updated papers require a new bound delivery view.","使用已确认的范围及独立研究许可。保留单次后端尝试；查询完成不代表 Stage 1 完成。新增论文需要生成新的来源绑定交付视图。","使用已確認的範圍及獨立研究許可。保留單次後端嘗試；查詢完成不代表 Stage 1 完成。新增論文需要產生新的來源綁定交付視圖。"],
    prepare:["Review next permitted query","审阅下一条获准查询","審閱下一條獲准查詢"],
    refresh:["Read attempt history","读取尝试历史","讀取嘗試歷史"],
    confirm:["I confirm this exact query and budget","我确认此条查询及预算","我確認此條查詢及預算"],
    submit:["Run this one query","运行这一条查询","執行這一條查詢"],
    ready:["Query prepared; explicit confirmation required","查询已准备，请明确确认","查詢已準備，請明確確認"],
    unknown:["Outcome unknown or still running. Refresh history; do not submit again.","结果未知或仍在运行。请刷新历史，不要重复提交。","結果未知或仍在執行。請重新整理歷史，不要重複提交。"],
    saved:["Attempt observation saved","尝试观察结果已保存","嘗試觀察結果已儲存"],
    unavailable:["Query unavailable; records remain retained","查询不可用，记录继续保留","查詢不可用，紀錄繼續保留"],
    storage:["Unable to save recovery intent; nothing submitted","无法保存恢复意图，尚未提交","無法儲存復原意圖，尚未提交"],
    details:["Source bindings & attempt records","来源绑定与尝试记录","來源綁定與嘗試紀錄"],
    limits:["Attempt count and process/probe time are reserved. Provider request, network, billing and process-tree bounds remain unproven.","预留尝试次数与进程／探测时间。提供方请求、网络、费用与进程树上限仍未证实。","預留嘗試次數與程序／探測時間。提供方請求、網路、費用與程序樹上限仍未證實。"],
    results:["requested results","请求结果数","請求結果數"], reserved:["reserved","预留","預留"], probe:["probe","探测","探測"], backend:["backend","后端","後端"],
    none:["No new query submitted","尚未提交新查询","尚未提交新查詢"],
  };
  const t=k=>labels[k][({en:0,"zh-Hans":1,"zh-Hant":2})[document.documentElement.lang]??0];
  const make=(tag,parent,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=String(text);parent?.append(n);return n;};
  const stable=x=>JSON.stringify(Object.fromEntries(Object.entries(x).sort(([a],[b])=>a<b?-1:a>b?1:0)));
  const digest=async x=>[...new Uint8Array(await crypto.subtle.digest("SHA-256",new TextEncoder().encode(stable(x))))].map(x=>x.toString(16).padStart(2,"0")).join("");
  const bound=x=>x && x.project_ref===c.project_ref && x.index_sha256===c.index_sha256 && x.input_version===c.input_version;
  const panel=make("section");panel.id="atlas-planned-queries";panel.className="atlas-panel stage-actions-panel";
  const title=make("h2",panel), boundary=make("p",panel), limits=make("p",panel), controls=make("div",panel);controls.className="stage-actions-controls";
  const prepare=make("button",controls), refresh=make("button",controls), summary=make("p",panel), notice=make("p",panel);notice.setAttribute("role","status");
  const form=make("form",panel), label=make("label",form), confirm=make("input",label), confirmText=make("span",label), submit=make("button",form);
  confirm.type="checkbox";submit.type="submit";prepare.type=refresh.type="button";
  const details=make("details",panel), detailsTitle=make("summary",details), records=make("pre",details);
  let view=null,offer=null,pending=null,busy=false,status="none",sequence=0,failure="",observation=null;
  try{const raw=sessionStorage.getItem(storage);if(raw!==null){pending=JSON.parse(raw);if(!pending || Object.keys(pending).sort().join()!=="hash,key" || !hash(pending.hash) || !/^[a-z0-9-]{36}$/.test(pending.key))throw Error("intent-invalid");status="unknown";}}
  catch{pending=false;status="unavailable";}
  const request=async(suffix="",body)=>{const response=await fetch(base+suffix,{method:body?"POST":"GET",credentials:"omit",cache:"no-store",redirect:"error",headers:{Authorization:"Bearer "+host.credential,...(body?{"Content-Type":"application/json"}:{})},...(body?{body:JSON.stringify(body)}:{})});if(!response.ok){let result;try{result=await response.json();}catch{}throw Error(typeof result?.error==="string"?result.error:typeof result?.error?.code==="string"?result.error.code:"query-request-failed");}return response.json();};
  const receipt=x=>{
    if(!x || !["dispatch-unobserved","dispatching","execution-unknown","completed"].includes(x.status) || x.model_execution!==false || x.automatic_retry!==false || !x.request || !bound({...x.request,project_ref:c.project_ref}) || x.client_key!==x.request.key || !hash(x.request_sha256))throw Error("query-receipt-differs");
    return x;
  };
  const held=()=>pending!==null || view?.history.some(x=>x.status!=="completed");
  const render=()=>{
    title.textContent=t("title");boundary.textContent=t("boundary");limits.textContent=t("limits");prepare.textContent=t("prepare");refresh.textContent=t("refresh");confirmText.textContent=t("confirm");submit.textContent=t("submit");detailsTitle.textContent=t("details");notice.textContent=t(status)+(failure?" · "+failure:"")+(observation?" · "+observation.status+" / "+observation.outcome+(observation.error?.code?" · "+observation.error.code:""):"");
    prepare.disabled=busy || held() || !view;refresh.disabled=busy;confirm.disabled=busy || held() || !offer;submit.disabled=busy || held() || !offer || !confirm.checked;
    summary.textContent=offer?offer.document.arguments.query+" · "+offer.document.backend+" · "+offer.document.max_results+" "+t("results")+" · "+offer.document.reserved_seconds+"s "+t("reserved")+" ("+offer.document.probe_timeout_seconds+"s "+t("probe")+" + "+offer.document.timeout_seconds+"s "+t("backend")+")":"";
    records.textContent=JSON.stringify({offer,history:view?.history??[],budget:view?.budget??null},null,2);
  };
  const recover=async()=>{
    if(busy)return;busy=true;const current=++sequence;offer=null;confirm.checked=false;render();
    try{
      const next=await request();if(!bound(next) || next.model_execution!==false || next.automatic_retry!==false || !Array.isArray(next.history))throw Error("query-view-differs");next.history.forEach(receipt);
      if(current!==sequence)return;view=next;
      if(pending && pending!==false){const row=next.history.find(x=>x.client_key===pending.key);if(row){const value=receipt(await request("/actions/"+encodeURIComponent(pending.key)));const actual=await digest(Object.fromEntries(Object.entries(value.request).filter(([k])=>k!=="revision")));
        if(current!==sequence)return;if(value.client_key!==pending.key || value.request_sha256!==pending.hash || actual!==pending.hash)throw Error("query-intent-differs");
        if(value.status==="completed"){sessionStorage.removeItem(storage);pending=null;status="saved";failure="";observation=value;}else status="unknown";
      }else status="unknown";}
      else status=pending===false?status:held()?"unknown":observation?"saved":"none";
    }catch(error){failure=error.message;status=pending?"unknown":"unavailable";view=null;}
    finally{if(current===sequence){busy=false;render();}}
  };
  prepare.onclick=async()=>{
    if(busy || held() || !view)return;busy=true;const current=++sequence;offer=null;confirm.checked=false;render();
    try{const value=await request("/offer");if(current!==sequence)return;if(!hash(value.offer_ref) || value.offer_ref!==value.offer_sha256 || value.revision!==view.revision || !bound(value.document) || value.document.execution_authority!=="separate-research-permit")throw Error("query-offer-differs");offer=value;status="ready";failure="";observation=null;}
    catch(error){status="unavailable";failure=error.message;}finally{if(current===sequence){busy=false;render();}}
  };
  form.onsubmit=async event=>{
    event.preventDefault();if(busy || held() || !offer || !confirm.checked)return;
    busy=true;const current=++sequence,selected=offer;render();
    try{const body={key:crypto.randomUUID(),revision:selected.revision,index_sha256:c.index_sha256,input_version:c.input_version,offer_ref:selected.offer_ref,offer_sha256:selected.offer_sha256,confirmed:true};
      const computed=await digest(Object.fromEntries(Object.entries(body).filter(([k])=>k!=="revision")));if(current!==sequence || offer!==selected)return;
      pending={key:body.key,hash:computed};try{sessionStorage.setItem(storage,JSON.stringify(pending));if(sessionStorage.getItem(storage)!==JSON.stringify(pending))throw Error("unobserved-intent");}catch{pending=false;status="storage";return;}
      status="unknown";render();await request("/actions",body);
    }catch(error){failure=error.message;status=pending?"unknown":"unavailable";}finally{busy=false;if(status==="storage")render();else await recover();}
  };
  confirm.onchange=render;refresh.onclick=recover;
  const mount=()=>{const anchor=document.getElementById("atlas-stage-actions");if(anchor && panel.previousSibling!==anchor)anchor.after(panel);};
  const content=document.getElementById("atlas-content");if(content)new MutationObserver(mount).observe(content,{childList:true,subtree:true});
  new MutationObserver(()=>{panel.hidden=document.documentElement.dataset.atlasStage!=="1";render();mount();}).observe(document.documentElement,{attributes:true,attributeFilter:["lang","data-atlas-stage"]});
  panel.hidden=document.documentElement.dataset.atlasStage!=="1";mount();render();recover();
})();
