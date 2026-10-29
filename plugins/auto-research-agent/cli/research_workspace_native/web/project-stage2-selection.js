/* Trusted UI sends actual form input; source material is rendered as text only. */
(function () {
  "use strict";
  const boot = window.RESEARCH_PROJECTS || {}, byId = id => document.getElementById(id);
  const words = {
    en: {required:"Required",fit:"Question fit",questionUse:"Use for this question",generalUse:"General use",license:"License",cost:"Cost basis",checked:"Checked at",status:"Claim status",questions:"Question IDs",evidence:"Evidence IDs",noQuestion:"This saved version has no structured scientific-question mapping.",planning:"Stage 3 planning input",planningBoundary:"Verified planning input retains unresolved conditions; it does not authorize experiments.",retained:"Retained planning input",backCards:"Return to direction comparison",legacy:"A versioned scientific-question mapping is still required before detailed planning.",return:"Return to project",title:"Stage 2 · Choose a research direction",intro:"Read each direction, compare its evidence and materials, then confirm a current eligible version for Stage 3 planning.",project:"Project",confirm:"Confirm your choice",name:"Your name",message:"Your selection message",reason:"Why choose this direction?",conditions:"Conditions to retain (one per line)",unknowns:"Open questions (one per line)",attest:"I have reviewed the displayed version, materials, limitations and conditions. This is a planning choice; it does not authorize experiments.",submit:"Confirm and prepare Stage 3 planning input",binding:"Version and receipt",none:"No eligible recommendation. Review the decision cards and unresolved evidence; no selection or execution has been authorized.",ready:"Choose a current eligible version after reviewing its materials.",saved:"Choice recorded. Stage 3 planning input was verified. Experiment execution remains unauthorized.",unconnected:"No validated delivery is connected to this project. A local draft is not a formal selection.",question:"Scientific question",approach:"Suggested method",limits:"Limits and alternatives",materials:"Data, references and tools",precedent:"Closest precedent and difference",unknown:"Unknown",unmapped:"No question mapping recorded; this does not prove materials are absent.",next:"Next necessary check",choose:"Choose this version",requirements:"Initial requirements",unused:"Resources without a question mapping",contribution:"Proposed contribution"},
    "zh-TW": {required:"是否必要",fit:"問題適配狀態",questionUse:"用於此問題的用途",generalUse:"一般用途",license:"授權",cost:"成本依據",checked:"查核時間",status:"主張狀態",questions:"問題編號",evidence:"證據編號",noQuestion:"此保存版本尚無結構化的科學問題對應。",planning:"Stage 3 規劃輸入",planningBoundary:"已驗證的規劃輸入保留未解條件，尚未授權執行實驗。",retained:"完整規劃輸入",backCards:"返回方向比較",legacy:"此舊版方向仍需版本化的科學問題對應，才能進行詳細規劃。",return:"返回專案",title:"Stage 2 · 選擇研究方向",intro:"閱讀方向、比較證據與材料，再確認目前可選的版本，交接 Stage 3 規劃。",project:"專案",confirm:"確認選擇",name:"你的姓名",message:"你的選案原始訊息",reason:"為什麼選這個方向？",conditions:"保留條件（每行一項）",unknowns:"未解問題（每行一項）",attest:"我已閱讀目前版本、材料、限制與條件。這是規劃選案，不是實驗執行授權。",submit:"確認並準備 Stage 3 規劃輸入",binding:"版本與收據",none:"目前沒有可推薦方向。仍可閱讀決策卡與未解證據；尚未選案或授權執行。",ready:"閱讀材料後，選擇目前可選版本。",saved:"已登記選案，Stage 3 規劃輸入已驗證；尚未授權執行實驗。",unconnected:"此專案尚未接上已驗證交付包；本地草稿不算正式選案。",question:"科學問題",approach:"建議方法",limits:"限制與替代方案",materials:"資料、參考報告與工具",precedent:"最近前例與差異",unknown:"未知",unmapped:"尚未記錄問題與材料的對應，不代表材料不存在。",next:"下一個必要查核",choose:"選擇這個版本",requirements:"初步必要條件",unused:"尚未對應問題的資源",contribution:"預期增量"},
    "zh-CN": {required:"是否必要",fit:"问题适配状态",questionUse:"用于此问题的用途",generalUse:"一般用途",license:"授权",cost:"成本依据",checked:"核查时间",status:"主张状态",questions:"问题编号",evidence:"证据编号",noQuestion:"此保存版本尚无结构化的科学问题对应。",planning:"Stage 3 规划输入",planningBoundary:"已验证的规划输入保留未解条件，尚未授权执行实验。",retained:"完整规划输入",backCards:"返回方向比较",legacy:"此旧版方向仍需版本化的科学问题对应，才能进行详细规划。",return:"返回项目",title:"Stage 2 · 选择研究方向",intro:"阅读方向、比较证据与材料，再确认当前可选的版本，交接 Stage 3 规划。",project:"项目",confirm:"确认选择",name:"你的姓名",message:"你的选案原始消息",reason:"为什么选这个方向？",conditions:"保留条件（每行一项）",unknowns:"未解问题（每行一项）",attest:"我已阅读当前版本、材料、限制与条件。这是规划选案，不是实验执行授权。",submit:"确认并准备 Stage 3 规划输入",binding:"版本与收据",none:"当前没有可推荐方向。仍可阅读决策卡与未解证据；尚未选案或授权执行。",ready:"阅读材料后，选择当前可选版本。",saved:"已登记选案，Stage 3 规划输入已验证；尚未授权执行实验。",unconnected:"此项目尚未接上已验证交付包；本地草稿不算正式选案。",question:"科学问题",approach:"建议方法",limits:"限制与替代方案",materials:"数据、参考报告与工具",precedent:"最近前例与差异",unknown:"未知",unmapped:"尚未记录问题与材料的对应，不代表材料不存在。",next:"下一个必要核查",choose:"选择这个版本",requirements:"初步必要条件",unused:"尚未对应问题的资源",contribution:"预期增量"}
  };
  words.en.continuePlanning="Continue Stage 3 planning";
  words["zh-TW"].continuePlanning="接續 Stage 3 規劃";
  words["zh-CN"].continuePlanning="继续 Stage 3 规划";
  words.en.inputVersion="Input version"; words["zh-TW"].inputVersion="輸入版本"; words["zh-CN"].inputVersion="输入版本";
  Object.assign(words["en"], {"submit":"Save selection only","saveAndStart":"Save and start planning","startBoundary":"Save and start makes one planning request after this choice is verified. It does not run research or experiments.","startAccepted":"Choice saved. The planning request was accepted; inspect Stage 3 for its actual outcome.","startHeld":"Planning was not started again. Check the saved selection and Stage 3 status before continuing."});
  Object.assign(words["zh-TW"], {"submit":"只保存選案","saveAndStart":"保存並開始規劃","startBoundary":"保存並開始會在選案驗證後送出一次規劃請求，不執行研究或實驗。","startAccepted":"選案已保存，規劃請求已接受；請到 Stage 3 檢視實際結果。","startHeld":"未再次開始規劃。請先檢查已保存的選案與 Stage 3 狀態。"});
  Object.assign(words["zh-CN"], {"submit":"只保存选案","saveAndStart":"保存并开始规划","startBoundary":"保存并开始会在选案验证后发出一次规划请求，不执行研究或实验。","startAccepted":"选案已保存，规划请求已接受；请到 Stage 3 查看实际结果。","startHeld":"未再次开始规划。请先检查已保存的选案与 Stage 3 状态。"});
  Object.assign(words.en, {tentative:"Tentative preference",prefer:"Include in tentative preference",intentMessage:"Your direction guidance",intentAttest:"I have reviewed these versions and their unknowns. Save this tentative preference for advice; formal selection is still pending and experiments are not authorized.",intentBoundary:"Choose 1–16 delivered directions, including directions awaiting revision or evidence. This preference requests advice; it does not make a formal selection. The saved origin does not authenticate your identity.",intentSave:"Save tentative preference only",intentStart:"Save preference and start planning",intentSaved:"Tentative preference saved. Formal selection remains pending; experiments are not authorized.",intentStartAccepted:"Tentative preference saved. The Stage 3 planning request was accepted; inspect Stage 3 for its actual outcome.",intentHeld:"Planning was not started again. Review the saved preference and Stage 3 status.",intentInvalid:"Choose 1–16 current directions, enter your guidance and confirm the tentative preference.",intentChanged:"This submitted preference is fixed. Reload the current delivery before changing it.",intentWork:"Stage 3 planning work",intentReceipt:"Tentative preference receipt",intentLink:"Open Stage 3 planning"});
  Object.assign(words["zh-TW"], {tentative:"暫定方向偏好",prefer:"加入暫定方向偏好",intentMessage:"你的方向指導",intentAttest:"我已閱讀這些版本與未知事項。此暫定偏好只供建議，正式選案仍待確認，尚未授權執行實驗。",intentBoundary:"可勾選 1–16 個已交付方向，包括仍待修訂或補證據的方向。此偏好用於徵詢建議，不構成正式選案。保存的來源不代表已驗證你的身分。",intentSave:"只保存暫定偏好",intentStart:"保存偏好並開始規劃",intentSaved:"暫定偏好已保存；正式選案仍待確認，尚未授權執行實驗。",intentStartAccepted:"暫定偏好已保存，Stage 3 規劃請求已接受；請到 Stage 3 檢視實際結果。",intentHeld:"未再次開始規劃。請檢查已保存的偏好與 Stage 3 狀態。",intentInvalid:"請選擇 1–16 個目前方向、填寫方向指導，並確認暫定偏好。",intentChanged:"已送出的偏好內容固定；請重新載入目前交付版本後再修改。",intentWork:"Stage 3 規劃工作",intentReceipt:"暫定偏好收據",intentLink:"開啟 Stage 3 規劃"});
  Object.assign(words["zh-CN"], {tentative:"暂定方向偏好",prefer:"加入暂定方向偏好",intentMessage:"你的方向指导",intentAttest:"我已阅读这些版本与未知事项。此暂定偏好仅供建议，正式选案仍待确认，尚未授权执行实验。",intentBoundary:"可勾选 1–16 个已交付方向，包括仍待修订或补证据的方向。此偏好用于征询建议，不构成正式选案。保存的来源不代表已验证你的身份。",intentSave:"只保存暂定偏好",intentStart:"保存偏好并开始规划",intentSaved:"暂定偏好已保存；正式选案仍待确认，尚未授权执行实验。",intentStartAccepted:"暂定偏好已保存，Stage 3 规划请求已接受；请到 Stage 3 查看实际结果。",intentHeld:"未再次开始规划。请检查已保存的偏好与 Stage 3 状态。",intentInvalid:"请选择 1–16 个当前方向、填写方向指导，并确认暂定偏好。",intentChanged:"已发出的偏好内容固定；请重新加载当前交付版本后再修改。",intentWork:"Stage 3 规划工作",intentReceipt:"暂定偏好收据",intentLink:"打开 Stage 3 规划"});
  Object.assign(words.en,{intentRefresh:"The saved receipt and current preference differ. Refresh this page before continuing; no planning run has started.",intentFocus:"More focus is needed. Refresh this page, choose fewer directions or clarify the question, then save again. The saved preference and unknowns are retained.",intentUnavailable:"Planning is currently unavailable. Read the reasons below; the preference is saved and no planning run has started."});
  Object.assign(words["zh-TW"],{intentRefresh:"保存收據與目前偏好不同。請重新整理此頁後再繼續；尚未啟動規劃。",intentFocus:"需要進一步聚焦。請重新整理此頁、減少方向或釐清問題後再保存。原偏好與未知事項仍保留。",intentUnavailable:"目前暫時無法開始規劃。請閱讀下方原因；偏好已保存，尚未啟動規劃。"});
  Object.assign(words["zh-CN"],{intentRefresh:"保存收据与当前偏好不同。请刷新此页后再继续；尚未启动规划。",intentFocus:"需要进一步聚焦。请刷新此页、减少方向或厘清问题后再保存。原偏好与未知事项仍保留。",intentUnavailable:"当前暂时无法开始规划。请阅读下方原因；偏好已保存，尚未启动规划。"});
  const projectNames=new Map(); let projectNamesFailed=false;
  let notice = null, planningSubmission = null;
  let view = null, busy = false, requestKey = null, lastBody = null, viewProject = null, loadSerial = 0;
  const preferredDirections=new Map(), intentTransactions=new Map();
  let intentTransaction=null, intentNotice=null, intentHold=null;
  const current = (ref, serial) => serial === loadSerial && byId("project").value === ref;
  const w = () => words[byId("language").value] || words.en;
  function node(parent, tag, text) { const n=document.createElement(tag); n.textContent=String(text ?? w().unknown); parent.append(n); return n; }
  function list(parent, values) { const ul=node(parent,"ul",""); for(const value of values || []) node(ul,"li",typeof value==="string"?value:value.text || value.reason || w().unknown); }
  function value(v) { return v==null?w().unknown:Array.isArray(v)?(v.length?v.join(", "):w().unknown):String(v); }
  function field(parent,label,v) { node(parent,"p",label+": "+value(v)); }
  function claims(parent,rows) { if(!rows?.length)node(parent,"p",w().unknown); for(const claim of rows || []) {node(parent,"p",claim.text);field(parent,w().status,claim.status);field(parent,w().questions,claim.question_ids);if(claim.evidence_ids)field(parent,w().evidence,claim.evidence_ids);} }
  function resource(parent,use) { const r=use.resource || use,ref=use.resource_ref;node(parent,"h4",r.name);node(parent,"p",[r.category,r.status].filter(Boolean).join(" · "));if(ref){field(parent,w().questionUse,ref.purpose);field(parent,w().fit,ref.fit_status);field(parent,w().evidence,ref.evidence_ids);}field(parent,w().generalUse,r.purpose);field(parent,w().required,r.required);field(parent,w().license,r.license);field(parent,w().cost,r.cost_basis);field(parent,w().checked,r.checked_at);list(parent,[r.url,r.version,r.access_conditions].map(value));field(parent,w().evidence,r.evidence_ids);list(parent,r.limitations);list(parent,r.alternatives); }
  async function api(path, body) { const response=await fetch(path,{method:body?"POST":"GET",credentials:"omit",cache:"no-store",headers:{Authorization:"Bearer "+boot.credential,...(body?{"Content-Type":"application/json"}:{})},...(body?{body:JSON.stringify(body)}:{})}); const data=await response.json(); if(!response.ok) throw new Error(data.error || "request-failed"); return data; }
  function renderProjectContext() {
    const area=byId("project-context");
    if(area) area.textContent=view?(projectNames.get(viewProject) || (projectNamesFailed?w().unknown+" · ":"")+viewProject)+" · "+w().inputVersion+": "+JSON.stringify(view.input_version):"";
  }
  function render() {
    for(const n of document.querySelectorAll("[data-i18n]")) n.textContent=w()[n.dataset.i18n];
    document.documentElement.lang=byId("language").value;
    renderProjectContext();
    byId("cards").replaceChildren();
    byId("planning").hidden=!view?.planning_input;
    byId("planning-link").hidden=!view?.planning_input;
    byId("planning-summary").replaceChildren();
    byId("choice").hidden=!view || view.selection_status==="recorded" || !view.eligible.length;
    byId("submit").disabled=busy;
    byId("submit-and-start").disabled=busy;
    byId("submit-and-start").hidden=!(boot.stage3_planning_projects || []).includes(viewProject);
    byId("project").disabled=busy;
    if(byId("direction-intent")) {
      byId("direction-intent").hidden=!view || view.selection_status==="recorded" || !view.cards.cards.length;
      byId("intent-save").disabled=busy;
      byId("intent-start").disabled=busy;
      byId("intent-start").hidden=!(boot.stage3_planning_projects || []).includes(viewProject);
      byId("intent-status").textContent=intentHold?[w()[intentHold.kind],intentNotice].filter(Boolean).join(" "):intentNotice || (view?.direction_intent?w().intentSaved:"");
      const blockers=byId("intent-blockers");if(blockers){blockers.hidden=!intentHold?.blockers.length;blockers.textContent=intentHold?intentHold.blockers.map(blocker=>typeof blocker==="string"?blocker:JSON.stringify(blocker,null,2)).join("\n"):"";}
      byId("intent-receipt").textContent=JSON.stringify({direction_intent:view?.direction_intent || null,planning_submission:intentTransaction?.submission || null,planning_work:intentTransaction?.planningWork || null},null,2);
      byId("intent-planning-link").hidden=!view?.direction_intent;
      byId("intent-planning-link").href="/project-stage3-planning.html#"+encodeURIComponent(viewProject || "");
    }
    if(!view) return;
    byId("planning-link").href="#"+viewProject;
    byId("return-cards").href="#"+viewProject;
    byId("status").textContent=notice || w()[view.selection_status==="recorded"?"saved":view.eligible.length?"ready":"none"];
    for(const card of view.cards.cards) {
      const a=node(byId("cards"),"article",""); node(a,"h2",card.candidate_question || card.candidate_id); node(a,"p",card.candidate_id+" · v"+card.candidate_version);
      if(byId("direction-intent") && view.selection_status!=="recorded") {const label=node(a,"label",""),checkbox=document.createElement("input"),key=JSON.stringify([card.candidate_id,card.candidate_version]);checkbox.type="checkbox";checkbox.name="tentative-direction";checkbox.value=card.candidate_id;checkbox.dataset.version=String(card.candidate_version);checkbox.checked=preferredDirections.has(key);checkbox.disabled=busy;checkbox.onchange=()=>{if(checkbox.checked)preferredDirections.set(key,{candidate_id:card.candidate_id,candidate_version:card.candidate_version});else preferredDirections.delete(key);};label.append(checkbox,document.createTextNode(w().prefer));}
      const eligible=view.eligible.some(x=>x.candidate_id===card.candidate_id && x.candidate_version===card.candidate_version);
      if(eligible && view.selection_status!=="recorded") { const label=node(a,"label",""); const radio=document.createElement("input"); radio.type="radio"; radio.name="direction"; radio.value=card.candidate_id; radio.dataset.version=String(card.candidate_version); radio.required=true; label.append(radio,document.createTextNode(w().choose)); }
      node(a,"h3",w().approach); node(a,"p",card.suggested_approach);
      node(a,"h3",w().precedent); const review=card.closest_prior_work.review; if(!review) node(a,"p",w().unknown); for(const c of review?.comparisons || []) { node(a,"p",[c.work_id,c.established,c.overlap,c.difference].filter(Boolean).join(" · ")); list(a,c.limitations || c.evidence_limits); }
      node(a,"h3",w().contribution); claims(a,card.contribution);
      if(!card.scientific_questions.length) node(a,"p",w().noQuestion);
      node(a,"h3",w().requirements); list(a,card.requirements);
      for(const q of card.scientific_questions) { node(a,"h3",w().question); node(a,"p",q.question.text); node(a,"p",q.question.intended_claim); node(a,"h4",w().materials); node(a,"p",q.resource_mapping_status==="unmapped"?w().unmapped:q.resource_mapping_status); for(const use of q.resource_uses) resource(a,use); }
      if(card.unmapped_resources.length) { node(a,"h3",w().unused); node(a,"p",w().unmapped); for(const r of card.unmapped_resources) resource(a,r); }
      node(a,"h3",w().limits); list(a,card.limitations); for(const alt of card.alternatives) list(a,alt.alternatives);
      node(a,"h3",w().next); list(a,card.next_checks);
    }
    if(view.planning_input) { const p=view.planning_input; if(p.legacy_candidates.length) node(byId("planning-summary"),"p",w().legacy); for(const q of p.questions) {node(byId("planning-summary"),"h3",q.text);node(byId("planning-summary"),"p",q.intended_claim);} list(byId("planning-summary"),p.selection_conditions);list(byId("planning-summary"),p.unresolved);byId("planning-input").textContent=JSON.stringify(p,null,2);
      if((boot.stage3_planning_projects || []).includes(viewProject) && view.selection_status==="recorded") {const link=node(byId("planning-summary"),"a",w().continuePlanning);link.id="stage3-entry";link.href="/project-stage3-planning.html#"+encodeURIComponent(viewProject);}
    }
    byId("receipt").textContent=JSON.stringify({project_ref:view.project_ref,input_version:view.input_version,selection_receipt:view.selection_receipt,delivery_manifest_sha256:view.delivery_manifest_sha256,snapshot_sha256:view.snapshot_sha256,planning_status:view.planning_status,planning_submission:planningSubmission,execution_authorized:false},null,2);
  }
  async function load() { const ref=byId("project").value, serial=++loadSerial; view=null; viewProject=null; requestKey=null; lastBody=null; notice=null; planningSubmission=null; intentTransaction=null;intentNotice=null;intentHold=null;preferredDirections.clear();if(byId("intent-message")){byId("intent-message").value="";byId("intent-confirmed").checked=false;} render(); if(!/^[A-Za-z0-9_-]{1,64}$/.test(ref)) {byId("status").textContent=w().unconnected;return;} try { const loaded=await api("/api/projects/"+ref+"/stage2/selection"); if(!current(ref,serial))return; view=loaded; viewProject=ref;const saved=intentTransactions.get(intentBinding(ref,view));if(saved){intentTransaction=saved;for(const direction of saved.body.preferred_directions)preferredDirections.set(JSON.stringify([direction.candidate_id,direction.candidate_version]),direction);if(byId("intent-message")){byId("intent-message").value=saved.body.user_input;byId("intent-confirmed").checked=true;}} history.replaceState(null,"","#"+ref); render(); } catch(e) {if(current(ref,serial))byId("status").textContent=w().unconnected+" ("+e.message+")";} }
  byId("language").onchange=render; byId("project").onchange=load;
  for(const [link,target] of [["planning-link","planning"],["return-cards","cards"]]) {
    byId(link).onclick=event=>{event.preventDefault();byId(target).scrollIntoView({block:"start"});};
  }
  async function startPlanning(ref, serial, receipt, selectedView) {
    const requireMatch = ok => { if(!ok) throw new Error(w().startHeld); };
    requireMatch(receipt.status==="saved" && receipt.key===requestKey && /^[a-f0-9]{64}$/.test(receipt.request_sha256 || ""));
    requireMatch(selectedView.selection_status==="recorded" && selectedView.selection_receipt?.request_sha256===receipt.request_sha256);
    const path="/api/projects/"+ref+"/stage3/planning";
    const matches = state => state.project_ref===ref && state.selection_status==="recorded" &&
      state.selection_request_sha256===receipt.request_sha256 && state.input_version===selectedView.input_version &&
      state.revision===selectedView.revision && state.brief_sha256===selectedView.brief_sha256;
    const state=await api(path);
    if(!current(ref,serial)) return;
    requireMatch(matches(state) && state.planning_configured && state.default_request && !state.job && !state.submission_in_progress && !state.submission_error);
    const request={...state.default_request};
    requireMatch(request.selection_request_sha256===receipt.request_sha256);
    await api(path+"/prepare",request);
    if(!current(ref,serial)) return;
    const prepared=await api(path);
    if(!current(ref,serial)) return;
    const next=prepared.default_request;
    requireMatch(matches(prepared) && next && Object.keys(request).every(key=>next[key]===request[key]) &&
      prepared.job?.status==="intent-recorded" && !prepared.submission_in_progress && !prepared.submission_error &&
      /^[a-f0-9]{64}$/.test(next.request_sha256 || "") && prepared.job.request_sha256===next.request_sha256);
    const result=await api(path+"/run",{...next,confirmed:true});
    if(!current(ref,serial)) return;
    planningSubmission=result;
    notice=result.submission_status==="accepted" ? w().startAccepted : w().startHeld;
  }
  byId("choice").onsubmit=async event=>{
    event.preventDefault();
    if(busy || !view || !current(viewProject,loadSerial)) return;
    const start=event.submitter?.id==="submit-and-start", ref=viewProject, serial=loadSerial;
    if(start && !(boot.stage3_planning_projects || []).includes(ref)) return;
    const selected=document.querySelector('input[name="direction"]:checked');
    if(!selected || !byId("confirmed").checked) return;
    const lines=id=>byId(id).value.split(/\r?\n/).map(x=>x.trim()).filter(Boolean);
    const body={key:requestKey || crypto.randomUUID(),revision:view.revision,input_version:view.input_version,brief_sha256:view.brief_sha256,delivery_manifest_sha256:view.delivery_manifest_sha256,workflow_head_sha256:view.workflow_head_sha256,snapshot_sha256:view.snapshot_sha256,confirmed:true,decision:{actor:byId("actor").value,kind:"select",user_text:byId("message").value,selected:[{candidate_id:selected.value,candidate_version:Number(selected.dataset.version)}],conditions:lines("conditions"),unresolved:lines("unresolved"),rationale:byId("rationale").value,scope_or_resource_change:false}};
    if(lastBody && JSON.stringify({...body,key:lastBody.key})!==JSON.stringify(lastBody)) {notice="Reload the current version before changing a submitted request.";render();return;}
    requestKey=body.key; lastBody=body; busy=true; notice=null; planningSubmission=null; render();
    try {
      const receipt=await api("/api/projects/"+ref+"/stage2/select",body);
      if(!current(ref,serial)) return;
      const refreshed=await api("/api/projects/"+ref+"/stage2/selection");
      if(!current(ref,serial)) return;
      view=refreshed; viewProject=ref; render();
      if(start) {
        if(refreshed.project_ref!==ref || refreshed.input_version!==body.input_version || refreshed.brief_sha256!==body.brief_sha256) throw new Error(w().startHeld);
        await startPlanning(ref,serial,receipt,refreshed);
      }
    } catch(e) {if(current(ref,serial)) notice=(start?w().startHeld+" ":"")+e.message;}
    finally {busy=false;render();}
  };
  function intentBinding(ref,state) {
    return JSON.stringify([ref,state.input_version,state.brief_sha256,state.delivery_manifest_sha256,state.workflow_head_sha256,state.snapshot_sha256]);
  }
  function requireIntent(ok,message=w().intentHeld) {if(!ok)throw new Error(message);}
  function holdIntentPlanning(state) {
    const kind=state.planning_status==="needs-information" || state.dispatch_action==="needs-information"?"intentFocus":state.planning_status==="unavailable" || state.dispatch_action==="unavailable"?"intentUnavailable":null;
    if(!kind)return false;
    intentHold={kind,blockers:Array.isArray(state.planning_blockers)?state.planning_blockers:[]};intentNotice=null;return true;
  }
  function verifyIntentReceipt(receipt, transaction) {
    requireIntent(receipt?.status==="saved" && receipt.key===transaction.body.key && receipt.mode==="direction-advice" && receipt.human_selection==="pending" && receipt.execution_authorized===false && typeof receipt.artifact_ref==="string" && receipt.artifact_ref.length>0);
    for(const key of ["request_sha256","intent_sha256","submission_sha256","advisory_manifest_sha256"])requireIntent(/^[a-f0-9]{64}$/.test(receipt[key] || ""));
  }
  function verifyIntentView(ref,state,transaction) {
    requireIntent(state.project_ref===ref && intentBinding(ref,state)===transaction.binding && Number.isInteger(state.revision) && state.revision>=transaction.body.revision);
    requireIntent(state.direction_intent?.intent_sha256===transaction.receipt.intent_sha256,w().intentRefresh);
    verifyIntentReceipt(state.direction_intent,transaction);
    for(const key of ["request_sha256","intent_sha256","submission_sha256","advisory_manifest_sha256","artifact_ref"])requireIntent(state.direction_intent[key]===transaction.receipt[key]);
  }
  async function startIntentPlanning(ref,serial,transaction,selectedView) {
    requireIntent(!transaction.prepareSent && !transaction.runSent);
    const path="/api/projects/"+ref+"/stage3/planning", intentHash=transaction.receipt.intent_sha256;
    const matches=state=>state.project_ref===ref && state.planning_mode==="direction-intent" && state.direction_intent_sha256===intentHash && state.input_version===selectedView.input_version && state.revision===selectedView.revision && state.brief_sha256===selectedView.brief_sha256;
    const state=await api(path);
    if(!current(ref,serial))return;
    requireIntent(matches(state),w().intentRefresh);
    if(holdIntentPlanning(state))return;
    intentHold=null;
    requireIntent(state.planning_configured && state.default_request && !state.job && !state.submission_in_progress && !state.submission_error);
    const source={...state.default_request};
    requireIntent(source.direction_intent_sha256===intentHash,w().intentRefresh);
    requireIntent(typeof source.key==="string" && source.key.length>0 && source.mode==="direction-intent" && source.direction_intent_sha256===intentHash && source.revision===selectedView.revision && source.input_version===selectedView.input_version && source.brief_sha256===selectedView.brief_sha256 && !source.request_sha256);
    const request={key:source.key,revision:source.revision,input_version:source.input_version,brief_sha256:source.brief_sha256,mode:"direction-intent",direction_intent_sha256:intentHash};
    transaction.prepareSent=true;
    await api(path+"/prepare",request);
    if(!current(ref,serial))return;
    const prepared=await api(path);
    if(!current(ref,serial))return;
    requireIntent(matches(prepared),w().intentRefresh);
    if(holdIntentPlanning(prepared))return;
    intentHold=null;
    const next=prepared.default_request;
    requireIntent(next?.direction_intent_sha256===intentHash,w().intentRefresh);
    requireIntent(prepared.planning_configured && next && Object.keys(source).every(key=>next[key]===source[key]) && Object.keys(next).every(key=>key==="request_sha256" || Object.hasOwn(source,key)) && prepared.job?.status==="intent-recorded" && !prepared.submission_in_progress && !prepared.submission_error && /^[a-f0-9]{64}$/.test(next.request_sha256 || "") && prepared.job.request_sha256===next.request_sha256);
    transaction.runSent=true;
    transaction.planningWork={key:next.key,request_sha256:next.request_sha256,mode:next.mode,direction_intent_sha256:intentHash};
    const result=await api(path+"/run",{...next,confirmed:true});
    if(!current(ref,serial))return;
    transaction.submission=result;
    intentNotice=(result.submission_status==="accepted"?w().intentStartAccepted:w().intentHeld)+" "+w().intentWork+": "+next.key+" · "+(result.job?.status || result.submission_status || w().unknown);
  }
  if(byId("direction-intent"))byId("direction-intent").onsubmit=async event=>{
    event.preventDefault();
    if(busy || !view || view.selection_status==="recorded" || !current(viewProject,loadSerial))return;
    const start=event.submitter?.id==="intent-start",ref=viewProject,serial=loadSerial;
    if(start && !(boot.stage3_planning_projects || []).includes(ref))return;
    if(view.project_ref!==ref){intentNotice=w().intentHeld;render();return;}
    const preferred=[...preferredDirections.values()],text=byId("intent-message").value;
    if(preferred.length<1 || preferred.length>16 || !text.trim() || text.length>4000 || !byId("intent-confirmed").checked || preferred.some(direction=>!view.cards.cards.some(card=>card.candidate_id===direction.candidate_id && card.candidate_version===direction.candidate_version))) {intentNotice=w().intentInvalid;render();return;}
    const binding=intentBinding(ref,view),existing=intentTransactions.get(binding);
    const body={key:existing?.body.key || crypto.randomUUID(),revision:existing?.body.revision ?? view.revision,input_version:view.input_version,brief_sha256:view.brief_sha256,delivery_manifest_sha256:view.delivery_manifest_sha256,workflow_head_sha256:view.workflow_head_sha256,snapshot_sha256:view.snapshot_sha256,preferred_directions:preferred,user_input:text,conditions:[],unresolved:[],confirmed:true};
    if(existing && JSON.stringify(body)!==JSON.stringify(existing.body)) {intentNotice=w().intentChanged;render();return;}
    const transaction=existing || {body,binding,prepareSent:false,runSent:false};
    intentTransactions.set(binding,transaction);intentTransaction=transaction;intentNotice=null;busy=true;render();
    try {
      requireIntent(!start || (!transaction.prepareSent && !transaction.runSent));
      const receipt=await api("/api/projects/"+ref+"/stage2/direction-intent",body);
      if(!current(ref,serial))return;
      verifyIntentReceipt(receipt,transaction);transaction.receipt=receipt;
      const refreshed=await api("/api/projects/"+ref+"/stage2/selection");
      if(!current(ref,serial))return;
      verifyIntentView(ref,refreshed,transaction);view=refreshed;viewProject=ref;intentNotice=w().intentSaved;render();
      if(start)await startIntentPlanning(ref,serial,transaction,refreshed);
    } catch(e) {if(current(ref,serial)){intentNotice=e.message || w().intentHeld;}}
    finally {busy=false;render();}
  };
  for(const ref of boot.stage2_selection_projects || []) {const option=node(byId("project"),"option",ref);option.value=ref;}
  const ref=location.hash.slice(1); if((boot.stage2_selection_projects || []).includes(ref)) byId("project").value=ref;
  load();
  api("/api/projects").then(result=>{
    const rows=Array.isArray(result)?result:result.projects;
    if(!Array.isArray(rows)) throw new Error("project-labels-unavailable");
    for(const row of rows) {
      const title=row.topic || row.original_description;
      if(!boot.stage2_selection_projects?.includes(row.project_ref) || typeof title!=="string") continue;
      const name=title.replace(/\s+/g," ").slice(0,240); projectNames.set(row.project_ref,name);
      for(const option of byId("project").children) if(option.value===row.project_ref) option.textContent=name+" · "+row.project_ref;
    }
    renderProjectContext();
  }).catch(()=>{projectNamesFailed=true;renderProjectContext();});
}());
