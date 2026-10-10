/* Saved-case stage operations. A browser intent is persisted before POST; reconnect only reads. */
(() => {
  "use strict";
  const config = window.WORKSPACE_STAGE_ACTIONS, host = window.WORKSPACE_HOST;
  delete window.WORKSPACE_STAGE_ACTIONS;
  const hash = x => typeof x === "string" && /^[a-f0-9]{64}$/.test(x);
  if (!config?.enabled || !/^[A-Za-z0-9_-]{1,64}$/.test(config.project_ref) ||
      !hash(config.index_sha256) || !hash(config.input_version) || !host?.credential) return;
  const api = "/api/stages/projects/" + encodeURIComponent(config.project_ref);
  const storage = "atlas-stage-intent:" + config.project_ref + ":" + config.index_sha256 + ":" + config.input_version;
  const labels = {
    title: ["Stage checks & review", "阶段检查与审阅", "階段檢查與審閱"],
    boundary: ["Check saved Harness stage inputs and record your review. Starting new research requires a separately admitted Codex session.", "检查 Harness 已保存的阶段输入，并记录审阅决定。新研究运行需要单独获准的 Codex 会话。", "檢查 Harness 已儲存的階段輸入，並記錄審閱決定。新研究執行需要單獨獲准的 Codex 工作階段。"],
    stage1: ["Stage 1 · literature", "Stage 1 · 文献", "Stage 1 · 文獻"],
    stage2: ["Stage 2 · comparison", "Stage 2 · 比较", "Stage 2 · 比較"],
    check: ["Check this stage", "检查本阶段", "檢查本階段"],
    refresh: ["Read saved history", "读取历史", "讀取歷史"],
    review: ["Record review", "记录审阅", "記錄審閱"],
    hold: ["Hold this stage", "暂留本阶段", "暫留本階段"],
    "request-next": ["Request next stage", "申请进入下一阶段", "申請進入下一階段"],
    note: ["Review note / reason", "审阅意见／理由", "審閱意見／理由"],
    confirm: ["Confirm this source version and my review", "确认当前来源版本及我的审阅意见", "確認目前來源版本及我的審閱意見"],
    submit: ["Save decision", "保存决定", "儲存決定"],
    history: ["Attempts & decisions", "尝试与决定", "嘗試與決定"],
    loading: ["Reading…", "正在读取…", "正在讀取…"],
    ready: ["Connected to saved inputs", "已连接已保存输入", "已連線已儲存輸入"],
    running: ["Checking…", "正在检查…", "正在檢查…"],
    completed: ["Saved check / decision completed; no research was started", "已完成保存材料检查／决定记录；未启动研究", "已完成儲存材料檢查／決定紀錄；未啟動研究"],
    failed: ["Failed; this attempt is retained", "失败，已保留本次尝试", "失敗，已保留本次嘗試"],
    unknown: ["Outcome unknown. Read history; do not submit again.", "结果未知，请读取历史核查，不要重复提交。", "結果未知，請讀取歷史核查，不要重複提交。"],
    error: ["Unable to verify the response. Records are retained.", "无法核验回执，记录仍然保留。", "無法核驗回執，紀錄仍然保留。"],
    stored: ["Saved input", "已保存输入", "已儲存輸入"],
    missing: ["Stage input not registered", "尚未注册阶段输入", "尚未註冊階段輸入"],
    capacity: ["The action limit has been reached; history remains available.", "已达到操作上限，仍可读取历史。", "已達操作上限，仍可讀取歷史。"],
    requested: ["Next-stage request recorded; execution is not authorized by this review.", "已记录下一阶段申请；此审阅记录不授予执行权限。", "已記錄下一階段申請；此審閱紀錄不授予執行權限。"],
    blocked: ["Next-stage request blocked by the stage check.", "本阶段检查未通过，下一阶段申请已被阻塞。", "本階段檢查未通過，下一階段申請已被阻塞。"],
    details: ["Read check details", "查看检查详情", "查看檢查詳情"],
    reviewDetails: ["View review record", "查看审阅记录", "查看審閱紀錄"],
    reviewDecision: ["Review decision", "审阅决定", "審閱決定"],
    reviewed: ["Reviewed", "已审阅", "已審閱"],
    latestCheck: ["Latest stage check", "本阶段最近检查", "本階段最近檢查"],
    notChecked: ["No check recorded for this stage", "本阶段尚无检查记录", "本階段尚無檢查紀錄"],
    partialHistory: ["Older check records are outside this history window.", "更早的检查记录不在当前历史窗口中。", "較早的檢查紀錄不在目前歷史視窗中。"],
    checkPass: ["Check passed", "检查通过", "檢查通過"],
    checkReady: ["Stage check ready", "阶段检查已就绪", "階段檢查已就緒"],
    checkBlocked: ["Check blocked", "检查受阻", "檢查受阻"],
    checkIncomplete: ["Delivery incomplete", "交付尚未完整", "交付尚未完整"],
    checkMissing: ["Stage input missing", "缺少阶段输入", "缺少階段輸入"],
    blockers: ["Blocking items", "待处理事项", "待處理事項"],
    noBlockers: ["No blocking items reported by this check.", "本次检查未报告阻塞项。", "本次檢查未報告阻塞項。"],
    savedOnly: ["This is a saved-input check, not permission to start the next stage.", "这是已保存输入的检查结果，不授予下一阶段执行权限。", "這是已儲存輸入的檢查結果，不授予下一階段執行權限。"],
    retainedOnly: ["Showing a retained check; the latest server state is not verified.", "正在显示已保留的检查；最新服务状态尚未核验。", "正在顯示已保留的檢查；最新服務狀態尚未核驗。"],
    summaryDetails: ["View full check record", "查看完整检查记录", "查看完整檢查紀錄"],
    outputRefs: ["Saved output references", "已保存产物位置", "已儲存產物位置"],
    copyOutputs: ["These references belong to the retained check copy; original inputs are preserved.", "这些位置属于本次检查的保留副本；原始输入保持不变。", "這些位置屬於本次檢查的保留副本；原始輸入保持不變。"],
    includedPapers: ["Papers in the handoff", "交接包中的论文", "交接包中的論文"],
    ledgerValid: ["Ledger validation passed", "Ledger 结构校验通过", "Ledger 結構校驗通過"],
    deliveryContent: ["Delivery content", "交付内容", "交付內容"],
    contentReady: ["ready for review", "可供审阅", "可供審閱"],
    contentIncomplete: ["incomplete", "尚未完整", "尚未完整"],
    assessment: ["Independent assessment", "独立评估", "獨立評估"],
    assessmentMissing: ["not supplied", "尚未提供", "尚未提供"],
    assessmentComplete: ["completed in saved evidence", "已保存证据中已完成", "已儲存證據中已完成"],
    assessmentAudit: ["audit pending", "审计待完成", "審計待完成"],
    assessmentUnknown: ["unknown", "尚未确定", "尚未確定"],
    closestWork: ["Closest related works need verification", "最接近的相关文献仍需核验", "最接近的相關文獻仍需核驗"],
    unfinished: ["Recorded actions are unfinished", "已有操作尚未完成", "已有操作尚未完成"],
    extraction: ["Evidence extraction is incomplete", "证据提取尚未完整", "證據擷取尚未完整"],
    sourceRead: ["Source reading failure needs review", "来源读取失败需要审阅", "來源讀取失敗需要審閱"],
    coverageMissing: ["Live coverage has not been evaluated", "尚未评估实际检索的覆盖情况", "尚未評估實際檢索的覆蓋情況"],
    backendFailures: ["Recorded search backend failures need review", "已记录的检索服务失败需要审阅", "已記錄的檢索服務失敗需要審閱"],
    storage: ["Unable to save recovery information. Nothing was submitted.", "无法保存恢复信息，尚未提交。", "無法儲存復原資訊，尚未提交。"],
  };
  const t = key => labels[key][({en:0,"zh-Hans":1,"zh-Hant":2})[document.documentElement.lang] ?? 0];
  const make = (tag, parent, text) => {const n = document.createElement(tag); if (text !== undefined) n.textContent = String(text); parent?.append(n); return n;};
  const stable = value => JSON.stringify(Object.fromEntries(Object.entries(value).sort(([a],[b]) => a < b ? -1 : a > b ? 1 : 0)));
  const digest = async value => [...new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(stable(value))))].map(x=>x.toString(16).padStart(2,"0")).join("");
  const panel = make("section"); panel.id = "atlas-stage-actions"; panel.className = "atlas-panel stage-actions-panel";
  const title = make("h2",panel), boundary = make("p",panel), controls = make("div",panel);
  controls.className = "stage-actions-controls";
  const stage = make("select",controls);
  stage.setAttribute("aria-label", "Stage");
  [1,2].forEach(value => {const option=make("option",stage); option.value=String(value);});
  stage.value = document.documentElement.dataset.atlasStage === "2" ? "2" : "1";
  const check = make("button",controls), refresh = make("button",controls);
  const status = make("p",panel); status.setAttribute("role","status");
  const inputStatus = make("p",panel);
  const summary = make("section",panel); summary.className="stage-check-summary"; summary.setAttribute("aria-live","polite");
  const form = make("form",panel); form.className="stage-review-form";
  const decision = make("select",form);
  decision.setAttribute("aria-label","Stage decision");
  ["review","hold","request-next"].forEach(value=>{const option=make("option",decision);option.value=value;});
  const noteLabel=make("label",form), note=make("textarea",noteLabel); note.maxLength=4096;note.required=true;
  const confirmLabel=make("label",form), confirm=make("input",confirmLabel); confirm.type="checkbox";confirm.required=true;
  const confirmText=make("span",confirmLabel), submit=make("button",form);submit.type="submit";
  const history=make("details",panel), historyTitle=make("summary",history), rows=make("div",history);
  let view=null,pending=null,busy=false,readable=false,state="loading",sequence=0,details=null,detailSequence=0;
  let observedAtlasStage=document.documentElement.dataset.atlasStage;
  const checks=new Map();
  const remember=row=>{if(row.result && row.action!=="review-stage")checks.set(row.client_key,row);return row;};
  try {const raw=sessionStorage.getItem(storage); if(raw!==null) {
    const value=JSON.parse(raw);
    if (!value || Object.keys(value).sort().join()!=="hash,key" || !hash(value.hash) || !/^[a-z0-9-]{36}$/.test(value.key)) throw Error("invalid-intent");
    pending=value;state="unknown";
  }} catch {pending=false;state="error";}
  const bound = value => value && value.project_ref===config.project_ref && value.index_sha256===config.index_sha256 && value.input_version===config.input_version;
  const receipt = (value,expectedSource=view?.source_sha256) => {
    if (!value || !["running","completed","failed","execution-unknown"].includes(value.status) || !bound({...value.request,project_ref:config.project_ref}) ||
        value.native_execution!==false || value.model_execution!==false || value.execution_authorized!==false || !hash(value.source_sha256) ||
        !value.request || value.client_key!==value.request.key || ![1,2].includes(value.stage) || value.stage!==value.request.stage || value.action!==value.request.action ||
        (expectedSource && value.source_sha256!==expectedSource)) throw Error("receipt-binding-differs");
    return value;
  };
  const request=async (suffix="",body)=>{
    const response=await fetch(api+suffix,{method:body?"POST":"GET",credentials:"omit",cache:"no-store",redirect:"error",
      headers:{Authorization:"Bearer "+host.credential,...(body?{"Content-Type":"application/json"}:{})},...(body?{body:JSON.stringify(body)}:{})});
    if(!response.ok) throw Error("stage-response-unavailable"); return response.json();
  };
  const locked=()=>busy || !view || !readable || pending!==null || view.history_count>=128 || view.history.some(row=>["running","execution-unknown"].includes(row.status));
  const showDetails=async row=>{
    const selected=Number(stage.value), current=++detailSequence;
    try{const loaded=checks.get(row.client_key) || receipt(await request("/actions/"+encodeURIComponent(row.client_key)));
      if(loaded.client_key!==row.client_key || loaded.stage!==row.stage || loaded.action!==row.action || loaded.source_sha256!==row.source_sha256)throw Error("requested-check-differs");
      if(current!==detailSequence || Number(stage.value)!==selected || loaded.stage!==selected)return;
      details=remember(loaded);history.open=true;render();}
    catch{if(current===detailSequence && Number(stage.value)===selected){state="error";render();}}
  };
  const renderSummary=()=>{
    summary.replaceChildren();make("h3",summary,t("latestCheck"));
    if(!view){make("p",summary,t("loading"));return;}
    const action=stage.value==="1"?"checkpoint-stage1":"inspect-stage2";
    const latest=[...(view?.history || [])].reverse().find(row=>row.stage===Number(stage.value)&&row.action===action);
    if(!latest){make("p",summary,t(view?.history_count>64?"partialHistory":"notChecked"));return;}
    const result=checks.get(latest.client_key)?.result;
    const readiness=latest.status==="completed" ? (result?.readiness.status || latest.result_summary?.readiness_status) : null;
    const keys={pass:"checkPass",ready:"checkReady",blocked:"checkBlocked",incomplete:"checkIncomplete",missing:"checkMissing"};
    const label=latest.status==="failed"?"failed":latest.status==="running"?"running":latest.status==="execution-unknown"?"unknown":keys[readiness] || "unknown";
    const badge=make("strong",summary,t(label));badge.className="stage-check-badge";badge.dataset.state=latest.status==="completed" && keys[readiness]?readiness:latest.status;
    if(!readable)make("p",summary,t("retainedOnly"));
    if(latest.error)make("p",summary,latest.error.code).translate=false;
    if(result){
      const blockers=result.readiness.blockers;
      if(blockers.length){make("p",summary,t("blockers"));const list=make("ul",summary);
        const names={"closest-work-unverified":"closestWork","unfinished-actions":"unfinished","extraction-incomplete":"extraction","source-read-failure-requires-review":"sourceRead","live-coverage-not-evaluated":"coverageMissing","recorded-backend-failures-require-review":"backendFailures"};
        for(const blocker of blockers){const text=typeof blocker==="string"?(names[blocker]?t(names[blocker]):blocker):blocker.reason || blocker.message || blocker.check_id || JSON.stringify(blocker);make("li",list,text).translate=false;}
      }else make("p",summary,t("noBlockers"));
      if(result.handoff?.papers)make("p",summary,t("includedPapers")+": "+result.handoff.papers.length);
      if(result.ledger_valid===true)make("p",summary,t("ledgerValid"));
      if(result.completion){const completion=result.completion;
        make("p",summary,t("deliveryContent")+": "+t(completion.research_delivery_ready?"contentReady":"contentIncomplete"));
        const states={missing:"assessmentMissing",completed:"assessmentComplete","audit-required":"assessmentAudit",unknown:"assessmentUnknown"};
        make("p",summary,t("assessment")+": "+(states[completion.assessment_status]?t(states[completion.assessment_status]):completion.assessment_status));
      }
      const outputs=result.checkpoint?.stage_result?.outputs;
      if(Array.isArray(outputs)&&outputs.length){const saved=make("details",summary);make("summary",saved,t("outputRefs")+" · "+outputs.length);make("p",saved,t("copyOutputs"));const list=make("ul",saved);outputs.forEach(ref=>make("li",list,ref.path).translate=false);}
    }else if(Number.isSafeInteger(latest.result_summary?.blocker_count))make("p",summary,t("blockers")+": "+latest.result_summary.blocker_count);
    const button=make("button",summary,t("summaryDetails"));button.type="button";button.disabled=busy;button.onclick=()=>showDetails(latest);
    make("p",summary,t("savedOnly"));
  };
  const render=()=>{
    title.textContent=t("title");boundary.textContent=t("boundary");
    [...stage.options].forEach((option,i)=>option.textContent=t("stage"+(i+1)));
    check.textContent=t("check");refresh.textContent=t("refresh");stage.disabled=busy;check.disabled=locked();refresh.disabled=busy;
    status.textContent=t(state);inputStatus.textContent=t(view?.input_status?.[stage.value]==="saved"?"stored":"missing");
    [...decision.options].forEach(option=>option.textContent=t(option.value));
    note.setAttribute("aria-label",t("note"));note.placeholder=t("note");confirmText.textContent=t("confirm");submit.textContent=t("submit");
    [decision,note,confirm,submit].forEach(n=>n.disabled=locked());
    renderSummary();
    historyTitle.textContent=t("history");rows.replaceChildren();
    for (const row of view?.history || []) {
      const card=make("article",rows);card.className="stage-action-record";
      make("strong",card,(row.stage===1?t("stage1"):t("stage2"))+" · "+row.action).translate=false;
      make("p",card,t(["completed","failed"].includes(row.status)?row.status:row.status==="running"?"running":"unknown"));
      const isReview=row.action==="review-stage";
      if(isReview){
        const choice=row.request.decision;
        const chosen=["review","hold","request-next"].includes(choice)?t(choice==="review"?"reviewed":choice):t("assessmentUnknown");
        make("p",card,t("reviewDecision")+": "+chosen).className="stage-review-decision";
        if(typeof row.request.note==="string" && row.request.note){
          make("p",card,t("note"));const original=make("p",card,row.request.note);original.className="stage-review-note";
          original.translate=false;original.setAttribute("style","white-space: pre-wrap");
        }
      }
      if(row.result_summary){
        if(!isReview)make("p",card,row.result_summary.readiness_status+" · "+row.result_summary.blocker_count+" blockers").translate=false;
        if(isReview && row.result_summary.next_stage_request === "recorded-awaiting-execution-authority")make("p",card,t("requested"));
        if(isReview && row.result_summary.next_stage_request === "blocked")make("p",card,t("blocked"));}
      if(row.error)make("p",card,row.error.code).translate=false;
      make("code",card,row.client_key).translate=false;
      const button=make("button",card,t(isReview?"reviewDetails":"details"));button.type="button";button.disabled=busy;
      button.onclick=()=>showDetails(row);
    }
    if(details?.result && details.stage===Number(stage.value)){const card=make("article",rows);const result=details.result;make("h3",card,(details.stage===1?t("stage1"):t("stage2"))+" · "+result.kind).translate=false;
      make("p",card,result.readiness.status).translate=false;
      for(const blocker of result.readiness.blockers)make("p",card,typeof blocker==="string"?blocker:JSON.stringify(blocker)).translate=false;
      if(result.note)make("p",card,result.note).translate=false;}
  };
  const recover=async()=>{
    if(busy)return;busy=true;const current=++sequence;render();
    try {
      const loaded=await request();
      if(current!==sequence)return;
      if(!bound(loaded) || loaded.project_id!==window.WORKSPACE_VIEW?.index?.project_id || !hash(loaded.source_sha256) ||
          !Number.isSafeInteger(loaded.revision) || loaded.revision<0 || (view&&(loaded.source_sha256!==view.source_sha256 || loaded.revision<view.revision)) ||
          !Array.isArray(loaded.history) || loaded.history.length>64 || !Number.isSafeInteger(loaded.history_count) || loaded.history_count>128 ||
          loaded.native_execution!==false || loaded.model_execution!==false || loaded.next_stage_execution_authorized!==false)throw Error("invalid-stage-view");
      loaded.history.forEach(row=>receipt(row,loaded.source_sha256));view=loaded;
      if(pending){const row=receipt(await request("/actions/"+encodeURIComponent(pending.key)));
        if(row.client_key!==pending.key || await digest(row.request)!==pending.hash)throw Error("recovery-differs");
        remember(row);
        state=["completed","failed"].includes(row.status)?row.status:"unknown";
        if(["completed","failed"].includes(row.status)){sessionStorage.removeItem(storage);pending=null;details=row;}
      }else state=pending===false?"error":view.history_count>=128?"capacity":view.history.some(r=>r.status==="execution-unknown")?"unknown":"ready";
      readable=pending!==false;
    }catch{readable=false;state=pending?"unknown":"error";}
    finally{busy=false;render();}
  };
  const execute=async(review)=>{
    if(locked())return;
    const selected=Number(stage.value), action=review?"review-stage":selected===1?"checkpoint-stage1":"inspect-stage2";
    busy=true;state="running";render();
    try {
      const offer=await request("/offers/"+selected+"/"+action);
      if(!hash(offer.offer_ref) || !hash(offer.offer_sha256) || offer.revision!==view.revision || !bound(offer.document) ||
          offer.document.source_sha256!==view.source_sha256 || offer.document.stage!==selected || offer.document.action!==action || offer.document.execution_authorized!==false)throw Error("offer-differs");
      const body={stage:selected,action,key:crypto.randomUUID(),revision:view.revision,index_sha256:config.index_sha256,input_version:config.input_version,
        offer_ref:offer.offer_ref,offer_sha256:offer.offer_sha256,decision:review?decision.value:null,note:review?note.value:"",confirmed:review?confirm.checked:false};
      if(review&&(!body.confirmed||!body.note.trim()||new TextEncoder().encode(body.note).length>4096))throw Error("explicit-review-required");
      if (/\\u[dD][89aAbBcCdDeEfF][0-9a-fA-F]{2}/.test(JSON.stringify(body)))throw Error("invalid-text");
      pending={key:body.key,hash:await digest(body)};
      try{sessionStorage.setItem(storage,JSON.stringify(pending));if(sessionStorage.getItem(storage)!==JSON.stringify(pending))throw Error("unobserved-intent");}
      catch{pending=false;state="storage";return;}
      await request("/actions",body);
    }catch{state=pending?"unknown":"error";}
    finally{busy=false;await recover();}
  };
  check.type=refresh.type="button";check.onclick=()=>execute(false);refresh.onclick=recover;
  const clearStageReview=()=>{++detailSequence;details=null;note.value="";confirm.checked=false;decision.value="review";};
  stage.onchange=()=>{clearStageReview();render();};form.onsubmit=event=>{event.preventDefault();return execute(true);};
  const mount=()=>{
    const anchor=document.getElementById("atlas-stage-review"), content=document.getElementById("atlas-content");
    if(anchor && panel.previousSibling!==anchor)anchor.after(panel);
    else if(!anchor && content && panel.parentNode!==content)content.append(panel);
  };
  const content=document.getElementById("atlas-content");
  if(content)new MutationObserver(mount).observe(content,{childList:true,subtree:true});
  new MutationObserver(()=>{
    const active=document.documentElement.dataset.atlasStage;
    if(active!==observedAtlasStage){observedAtlasStage=active;clearStageReview();if(["1","2"].includes(active))stage.value=active;}
    panel.hidden=Boolean(active && !["1","2"].includes(active));
    if(panel.hidden){++detailSequence;details=null;}
    render();mount();
  }).observe(document.documentElement,{attributes:true,attributeFilter:["lang","data-atlas-stage"]});
  mount();render();recover();
})();
