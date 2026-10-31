/* Trusted UI sends actual form input; source material is rendered as text only. */
(function () {
  "use strict";
  // Wiki callers retain one instance per project; suspension invalidates delayed responses
  // without discarding the original submission key or uncertain transaction.
  const embeddedSessions = new Map();
  // A marker contains only opaque action identifiers and version hashes; no
  // credentials, user text or paths are written to same-origin localStorage.
  const markerPrefix = "ara.stage2.pending.v1.";
  function canonicalValue(value) {
    if(value===null || typeof value==="boolean") return JSON.stringify(value);
    if(typeof value==="number") {if(!Number.isSafeInteger(value))throw Error("canonical-number-invalid");return JSON.stringify(value);}
    if(typeof value==="string") {
      for(let i=0;i<value.length;i++){const c=value.charCodeAt(i);if(c>=0xd800&&c<=0xdbff){const n=value.charCodeAt(++i);if(!(n>=0xdc00&&n<=0xdfff))throw Error("canonical-text-invalid");}else if(c>=0xdc00&&c<=0xdfff)throw Error("canonical-text-invalid");}
      return JSON.stringify(value);
    }
    if(Array.isArray(value))return "["+value.map(canonicalValue).join(",")+"]";
    if(value && typeof value==="object") {
      const keys=Object.keys(value).sort();if(keys.some(k=>!/^[a-zA-Z0-9_]+$/.test(k)))throw Error("canonical-key-invalid");
      return "{"+keys.map(k=>JSON.stringify(k)+":"+canonicalValue(value[k])).join(",")+"}";
    }
    throw Error("canonical-type-invalid");
  }
  async function requestHash(kind,body) {
    const semantic={...body};delete semantic.revision;
    const bytes=new TextEncoder().encode(canonicalValue({kind,body:semantic}));
    const digest=await crypto.subtle.digest("SHA-256",bytes);
    return [...new Uint8Array(digest)].map(x=>x.toString(16).padStart(2,"0")).join("");
  }
  function mount(root, options = {}) {
  const embedded = options.embedded === true;
  const boot = options.bootstrap || window.RESEARCH_PROJECTS || {};
  const byId = id => typeof root.getElementById === "function" ? root.getElementById(id) : root.querySelector('#' + id);
  const binding = embedded ? Object.freeze({...options.binding}) : null;
  if (embedded) {
    if (!binding || typeof binding.project_ref !== "string" || !/^[A-Za-z0-9_-]{1,64}$/.test(binding.project_ref) ||
        !(boot.stage2_selection_projects || []).includes(binding.project_ref) ||
        typeof options.isCurrent !== "function" || typeof options.onAccepted !== "function" ||
        !((typeof binding.input_version === "string" && binding.input_version.length>0 && binding.input_version.length<=128) || (Number.isSafeInteger(binding.input_version) && binding.input_version>=0)) ||
        !Number.isSafeInteger(binding.revision) || binding.revision<0 || typeof binding.brief_sha256!=="string" || !/^[a-f0-9]{64}$/.test(binding.brief_sha256))
      throw new Error("invalid-stage2-embedded-binding");
    const previous = embeddedSessions.get(binding.project_ref);
    if (previous) {
      if (previous.root === root && ["project_ref", "input_version", "revision", "brief_sha256"].every(key => previous.binding[key] === binding[key])) return previous.handle;
      throw new Error("stage2-embedded-session-retained");
    }
  }
  let active = true, disposed = false, reading = false, reloadAfterRead = false, uncertain = false;
  let storage=null, pendingMarker=null, pendingRaw=null, recovery=null, recoverySerial=0, recoveryNoticeKey=null;
  const hex=/^[a-f0-9]{64}$/, actionKey=/^[A-Za-z0-9_-]{1,128}$/;
  const storagePrefix=embedded?markerPrefix+binding.project_ref+".":"";
  const isHex=v=>typeof v==="string" && hex.test(v), isKey=v=>typeof v==="string" && actionKey.test(v);
  const recoveryState=(status,code,type)=>({status,code,pendingType:type || null});
  function validMarker(m,key) {
    const fields=["schema","project_ref","input_version","revision","brief_sha256","delivery_manifest_sha256","workflow_head_sha256","snapshot_sha256","kind","key","request_sha256","phase","planning_key","planning_sha256"];
    return m && typeof m==="object" && !Array.isArray(m) && Object.keys(m).sort().join(",")===fields.sort().join(",") && m.schema===1 &&
      m.project_ref===binding.project_ref && key===storagePrefix+m.key && isKey(m.key) && ["stage2-select","stage2-direction-intent"].includes(m.kind) &&
      ((typeof m.input_version==="string" && m.input_version.length>0 && m.input_version.length<=128)||(Number.isSafeInteger(m.input_version)&&m.input_version>=0)) &&
      Number.isSafeInteger(m.revision) && m.revision>=0 && ["brief_sha256","delivery_manifest_sha256","workflow_head_sha256","snapshot_sha256","request_sha256"].every(k=>isHex(m[k])) &&
      ["stage2","planning"].includes(m.phase) && (m.planning_key===null || isKey(m.planning_key)) && (m.planning_sha256===null || isHex(m.planning_sha256)) &&
      (m.phase!=="stage2" || (m.planning_key===null && m.planning_sha256===null)) && (m.planning_sha256===null || m.planning_key!==null);
  }
  function scanMarkers() {
    if(!storage || !Number.isSafeInteger(storage.length) || storage.length>5000)throw Error("storage-unavailable");
    const found=[];for(let i=0;i<storage.length;i++){const key=storage.key(i);if(typeof key==="string" && key.startsWith(storagePrefix)){
      const raw=storage.getItem(key);if(typeof raw!=="string" || raw.length>4096)throw Error("storage-invalid");
      let value;try{value=JSON.parse(raw);}catch(_){throw Error("storage-invalid");}
      if(!validMarker(value,key))throw Error("storage-invalid");found.push({key,raw,value});
    }}
    return found;
  }
  if(embedded) {
    try {
      storage=options.storage || window.localStorage;
      const found=scanMarkers();
      if(found.length===1){pendingMarker=found[0].value;pendingRaw=found[0].raw;uncertain=true;recovery=recoveryState("unknown","pending-receipt",pendingMarker.kind);}
      else if(found.length>1){uncertain=true;recovery=recoveryState("unknown","multiple-pending",null);}
    } catch(error) {uncertain=true;recovery=recoveryState("unavailable",error.message==="storage-invalid"?"storage-invalid":"storage-unavailable",null);}
  }
  async function beginPending(kind,body,start,serial) {
    if(!embedded)return true;
    if(recovery || !isActive())return false;
    let digest;try{digest=await requestHash(kind,body);}catch(_){uncertain=true;recovery=recoveryState("unavailable","hash-unavailable",kind);return false;}
    if(!current(binding.project_ref,serial)){uncertain=false;return false;}
    try {
      if(scanMarkers().length)throw Error("pending-conflict");
      const marker={schema:1,project_ref:binding.project_ref,input_version:body.input_version,revision:body.revision,brief_sha256:body.brief_sha256,delivery_manifest_sha256:body.delivery_manifest_sha256,workflow_head_sha256:body.workflow_head_sha256,snapshot_sha256:body.snapshot_sha256,kind,key:body.key,request_sha256:digest,phase:"stage2",planning_key:null,planning_sha256:null};
      const key=storagePrefix+marker.key, raw=JSON.stringify(marker);
      if(!validMarker(marker,key) || storage.getItem(key)!==null)throw Error("pending-conflict");
      storage.setItem(key,raw);if(storage.getItem(key)!==raw)throw Error("storage-unavailable");
      pendingMarker=marker;pendingRaw=raw;recovery=recoveryState("unknown","pending-receipt",kind);return true;
    }catch(error){uncertain=true;recovery=recoveryState("unavailable",error.message==="pending-conflict"?"pending-conflict":"storage-unavailable",kind);return false;}
  }
  function updatePending(changes) {
    if(!embedded)return;
    if(!pendingMarker)throw Error("pending-marker-missing");
    const key=storagePrefix+pendingMarker.key;if(storage.getItem(key)!==pendingRaw)throw Error("pending-marker-changed");
    const next={...pendingMarker,...changes}, raw=JSON.stringify(next);if(!validMarker(next,key))throw Error("pending-marker-invalid");
    storage.setItem(key,raw);if(storage.getItem(key)!==raw)throw Error("pending-marker-changed");
    pendingMarker=next;pendingRaw=raw;
  }
  function clearPending() {
    if(!embedded)return;
    if(!pendingMarker)throw Error("pending-marker-missing");
    const key=storagePrefix+pendingMarker.key;if(storage.getItem(key)!==pendingRaw)throw Error("pending-marker-changed");
    storage.removeItem(key);if(storage.getItem(key)!==null)throw Error("storage-unavailable");
    pendingMarker=null;pendingRaw=null;recovery=null;uncertain=false;
  }
  const isActive = () => {
    if (!active || disposed) return false;
    try { return !embedded || options.isCurrent(binding) === true; } catch (_) { return false; }
  };
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
  Object.assign(words.en,{recoveryPending:"A previous submission is not yet confirmed. Check its saved receipt before submitting again.",recoveryUnavailable:"Recovery storage is unavailable or invalid. Submission is disabled; no research or planning was started by this check."});
  Object.assign(words["zh-TW"],{recoveryPending:"先前的送出尚未確認。請先檢查保存的收據，再進行其他提交。",recoveryUnavailable:"恢復儲存不可用或資料無效，已停用提交；此檢查不會開始研究或規劃。"});
  Object.assign(words["zh-CN"],{recoveryPending:"先前的提交尚未确认。请先检查保存的收据，再进行其他提交。",recoveryUnavailable:"恢复存储不可用或数据无效，已停用提交；此检查不会开始研究或规划。"});
  const comparisonWords = {
    "en": {
      "projectDetails": "Project and input version",
      "yourPreference": "Your preference",
      "reviewPreference": "Review preference and next step",
      "preferenceOptions": "Preference guidance and next step",
      "formalOptions": "Formal selection, when eligible",
      "guidanceHelp": "Required: describe what you want to focus on. You can retain unresolved questions.",
      "intentBoundary": "Choose 1–16 directions for planning advice. Formal selection and experiment authorization remain pending; saved input origin does not authenticate identity.",
      "nothingChosen": "No directions chosen yet. Compare the summaries below.",
      "chosenCount": "{n} direction(s) in your preference",
      "reviewDetails": "Read evidence, materials and limitations",
      "canPrefer": "You can express a preference; formal selection is not available",
      "canChoose": "Eligible for formal selection",
      "overviewMethod": "Method",
      "overviewMaterials": "Possible materials — verify access in details",
      "overviewLimit": "Main limitation",
      "overviewNext": "Next check",
      "noMaterials": "No material mapping recorded; availability remains unverified.",
      "directionCount": "{n} directions to compare",
      "eligibleCount": "{n} eligible for formal selection",
      "none": "No directions are currently recommended for formal selection. You can save a tentative preference for planning advice."
    },
    "zh-TW": {
      "projectDetails": "專案與輸入版本",
      "yourPreference": "我的方向偏好",
      "reviewPreference": "確認偏好與下一步",
      "preferenceOptions": "偏好說明與下一步",
      "formalOptions": "正式選案（符合條件時）",
      "guidanceHelp": "必填：補一句你想聚焦什麼；仍不確定的問題可以保留。",
      "intentBoundary": "可選 1–16 個方向交給 Stage 3 釐清，正式選案與實驗授權仍待確認。紀錄保存輸入來源，未驗證身分。",
      "nothingChosen": "尚未選擇；先比較下方的方向摘要。",
      "chosenCount": "已加入 {n} 個方向",
      "reviewDetails": "展開證據、材料與限制",
      "canPrefer": "可先表達偏好；尚未開放正式選案",
      "canChoose": "目前可正式選案",
      "overviewMethod": "怎麼研究",
      "overviewMaterials": "可能用到的材料（存取條件見詳細資料）",
      "overviewLimit": "主要限制",
      "overviewNext": "下一個查核",
      "noMaterials": "尚未記錄材料對應，可用性仍待查證。",
      "directionCount": "可比較 {n} 個方向",
      "eligibleCount": "可正式選案 {n} 個",
      "none": "目前沒有可推薦作正式選案的方向；仍可先保存偏好，請 Stage 3 協助規劃與查核。"
    },
    "zh-CN": {
      "projectDetails": "项目与输入版本",
      "yourPreference": "我的方向偏好",
      "reviewPreference": "确认偏好与下一步",
      "preferenceOptions": "偏好说明与下一步",
      "formalOptions": "正式选案（符合条件时）",
      "guidanceHelp": "必填：补一句你想聚焦什么；仍不确定的问题可以保留。",
      "intentBoundary": "可选 1–16 个方向交给 Stage 3 厘清，正式选案与实验授权仍待确认。记录保存输入来源，未验证身份。",
      "nothingChosen": "尚未选择；先比较下方的方向摘要。",
      "chosenCount": "已加入 {n} 个方向",
      "reviewDetails": "展开证据、材料与限制",
      "canPrefer": "可先表达偏好；尚未开放正式选案",
      "canChoose": "当前可正式选案",
      "overviewMethod": "怎么研究",
      "overviewMaterials": "可能用到的材料（访问条件见详细资料）",
      "overviewLimit": "主要限制",
      "overviewNext": "下一个查核",
      "noMaterials": "尚未记录材料对应，可用性仍待查证。",
      "directionCount": "可比较 {n} 个方向",
      "eligibleCount": "可正式选案 {n} 个",
      "none": "当前没有可推荐作正式选案的方向；仍可先保存偏好，请 Stage 3 协助规划与查核。"
    }
  };
  for (const [language, labels] of Object.entries(comparisonWords)) Object.assign(words[language],labels);
  const projectNames=new Map(); let projectNamesFailed=false;
  let notice = null, planningSubmission = null;
  let view = null, busy = false, requestKey = null, lastBody = null, viewProject = null, loadSerial = 0;
  const preferredDirections=new Map(), intentTransactions=new Map();
  let intentTransaction=null, intentNotice=null, intentHold=null;
  const current = (ref, serial) => isActive() && serial === loadSerial && byId("project").value === ref && (!embedded || ref === binding.project_ref);
  const w = () => words[byId("language").value] || words.en;
  Object.assign(words.en,{lockBusy:"Another tab is handling this project; try again when it finishes.",lockUnavailable:"This browser does not support the project transaction lock. Submission and recovery are disabled."});
  Object.assign(words["zh-TW"],{lockBusy:"另一分頁正在處理此專案；完成後再試。",lockUnavailable:"此瀏覽器不支援專案交易鎖，已停用提交及恢復。"});
  Object.assign(words["zh-CN"],{lockBusy:"另一标签页正在处理此项目；完成后再试。",lockUnavailable:"此浏览器不支持项目事务锁，已停用提交及恢复。"});
  async function withProjectLock(work) {
    if(!embedded)return work();
    const locks=window.navigator?.locks;
    if(!locks || typeof locks.request!=="function") {
      uncertain=true;recovery=recoveryState("unavailable","project-lock-unavailable",pendingMarker?.kind);notice=w().lockUnavailable;if(isActive())render();
      return recoveryState("unavailable","project-lock-unavailable",pendingMarker?.kind);
    }
    try {return await locks.request("ara.stage2.transaction.v1."+binding.project_ref,{mode:"exclusive",ifAvailable:true},async lock=>{
      if(!lock){notice=w().lockBusy;if(isActive())render();return recoveryState("unknown","project-lock-busy",pendingMarker?.kind);}
      return await work();
    });} catch(_) {uncertain=true;recovery=recoveryState("unavailable","project-lock-failed",pendingMarker?.kind);if(isActive())render();return recovery;}
  }
  function node(parent, tag, text) { const n=document.createElement(tag); n.textContent=String(text ?? w().unknown); parent.append(n); return n; }
  function list(parent, values) { const ul=node(parent,"ul",""); for(const value of values || []) node(ul,"li",typeof value==="string"?value:value.text || value.reason || w().unknown); }
  function value(v) { return v==null?w().unknown:Array.isArray(v)?(v.length?v.join(", "):w().unknown):String(v); }
  function field(parent,label,v) { node(parent,"p",label+": "+value(v)); }
  function claims(parent,rows) { if(!rows?.length)node(parent,"p",w().unknown); for(const claim of rows || []) {node(parent,"p",claim.text);field(parent,w().status,claim.status);field(parent,w().questions,claim.question_ids);if(claim.evidence_ids)field(parent,w().evidence,claim.evidence_ids);} }
  function resource(parent,use) { const r=use.resource || use,ref=use.resource_ref;node(parent,"h4",r.name);node(parent,"p",[r.category,r.status].filter(Boolean).join(" · "));if(ref){field(parent,w().questionUse,ref.purpose);field(parent,w().fit,ref.fit_status);field(parent,w().evidence,ref.evidence_ids);}field(parent,w().generalUse,r.purpose);field(parent,w().required,r.required);field(parent,w().license,r.license);field(parent,w().cost,r.cost_basis);field(parent,w().checked,r.checked_at);list(parent,[r.url,r.version,r.access_conditions].map(value));field(parent,w().evidence,r.evidence_ids);list(parent,r.limitations);list(parent,r.alternatives); }
  async function api(path, body, options={}) { const response=await fetch(path,{method:body?"POST":"GET",credentials:"omit",cache:"no-store",headers:{Authorization:"Bearer "+boot.credential,...(body?{"Content-Type":"application/json"}:{})},...(body?{body:JSON.stringify(body)}:{})}); const data=await response.json(); if(!response.ok) throw new Error(data.error || "request-failed"); return options.includeStatus?{data,status:response.status}:data; }
  function enterPlanning(ref,serial,selectedView,request,response) {
    const result=response.data,job=result?.job;
    const policyUnchanged=state=>state && ["execution_authorized","evaluation_calls_authorized","formal_execution_enabled","external_claim_ready","usable_for_formal_pairing"].every(key=>state[key]===false);
    const tentative=request.mode==="direction-intent";
    if(!current(ref,serial) || viewProject!==ref || view!==selectedView || response.status!==202 ||
      result?.kind!=="ProjectStage3PlanningSubmission" || result.submission_status!=="accepted" ||
      !policyUnchanged(result) || !policyUnchanged(job) || job.project_ref!==ref || job.key!==request.key ||
      job.request_sha256!==request.request_sha256 || job.status!=="intent-recorded" ||
      job.kind!==(tentative?"ProjectStage3DirectionPlanningJob":"ProjectStage3PlanningJob") ||
      (tentative && (job.mode!=="direction-intent" || job.formal_selected_receiver!==false))) return;
    const language=byId("language").value,query=["en","zh-TW","zh-CN"].includes(language)?"?lang="+encodeURIComponent(language):"";
    if(!embedded) uncertain=false;
    if(embedded) options.onAccepted({projectRef:ref,language,request,result});
    else window.location.assign("/project-stage3-planning.html#"+encodeURIComponent(ref)+query);
  }
  function planningHref(ref) {
    const language=byId("language").value, query=["en","zh-TW","zh-CN"].includes(language)?"?lang="+encodeURIComponent(language):"";
    return "/project-stage3-planning.html#"+encodeURIComponent(ref)+query;
  }
  function bindPlanningLink(link, ref) {
    link.href=planningHref(ref);
    if(embedded && typeof options.onNavigate === "function") link.onclick=event=>{
      event.preventDefault(); if(isActive()) options.onNavigate({projectRef:ref,language:byId("language").value});
    };
  }

  const previewText = (value, limit=120) => {
    const text=String(typeof value==="string"?value:value?.text || value?.reason || w().unknown);
    return text.length>limit?text.slice(0,limit-1).trimEnd()+"…":text;
  };
  function updatePreferenceSummary() {
    const area=byId("preference-summary"); if(!area)return;
    const chosen=(view?.cards.cards || []).filter(card=>preferredDirections.has(JSON.stringify([card.candidate_id,card.candidate_version])));
    const selected=root.querySelector('input[name="direction"]:checked');
    const formal=selected && view?.cards.cards.find(card=>card.candidate_id===selected.value && String(card.candidate_version)===selected.dataset.version);
    area.textContent=formal?w().choose+" · "+formal.candidate_question+" · v"+formal.candidate_version:chosen.length?w().chosenCount.replace("{n}",String(chosen.length))+" · "+previewText(chosen.map(card=>card.candidate_question+" · v"+card.candidate_version).join("; "),130):w().nothingChosen;
    const full=byId("chosen-directions"); if(full){full.replaceChildren();list(full,chosen.map(card=>card.candidate_question+" · v"+card.candidate_version));}
    const button=byId("review-preference");if(button){button.textContent=formal?w().confirm:w().reviewPreference;button.disabled=busy || !view || !view.cards.cards.length || !!(embedded && recovery && recovery.status!=="verified");}
  }
  if(byId("review-preference"))byId("review-preference").onclick=()=>{
    const formal=!!root.querySelector('input[name="direction"]:checked');
    const panel=byId(formal?"formal-panel":"intent-panel");if(panel){panel.open=true;panel.scrollIntoView({block:"start"});}
    const input=byId(formal?"actor":"intent-message");if(input && typeof input.focus==="function")input.focus();
  };

  function renderProjectContext() {
    const area=byId("project-context");
    if(area) area.textContent=view?(projectNames.get(viewProject) || (projectNamesFailed?w().unknown+" · ":"")+viewProject)+" · "+w().inputVersion+": "+JSON.stringify(view.input_version):"";
  }
  function render() {
    const layout=byId("selection-layout");if(layout)layout.dataset.embedded=String(embedded);
    const expanded=new Set([...root.querySelectorAll("details[data-direction-details]")].filter(n=>n.open).map(n=>n.dataset.directionDetails));
    const selectedBeforeRender = root.querySelector('input[name="direction"]:checked');
    const selectedKey = selectedBeforeRender ? JSON.stringify([selectedBeforeRender.value,selectedBeforeRender.dataset.version]) : null;
    for(const n of root.querySelectorAll("[data-i18n]")) n.textContent=w()[n.dataset.i18n];
    if(!embedded) document.documentElement.lang=byId("language").value;
    if(!embedded && boot.wiki_v9 && byId("return"))byId("return").href="/#"+encodeURIComponent(byId("project").value)+"?stage=2&lang="+encodeURIComponent(byId("language").value);
    renderProjectContext();
    byId("cards").replaceChildren();
    byId("planning").hidden=!view?.planning_input;
    byId("planning-link").hidden=!view?.planning_input;
    byId("planning-summary").replaceChildren();
    byId("choice").hidden=!view || view.selection_status==="recorded" || !view.eligible.length;
    const held=embedded && recovery && recovery.status!=="verified";
    if(embedded && typeof options.onRecoveryChange==="function") {
      const state=recovery && {...recovery}, key=JSON.stringify(state);
      if(key!==recoveryNoticeKey) { recoveryNoticeKey=key; Promise.resolve().then(()=>{if(isActive() && JSON.stringify(recovery && {...recovery})===key) options.onRecoveryChange(state);}); }
    }
    byId("submit").disabled=busy || !!held;
    byId("submit-and-start").disabled=busy || !!held;
    byId("submit-and-start").hidden=!(boot.stage3_planning_projects || []).includes(viewProject);
    byId("project").disabled=busy || embedded;
    if(byId("direction-intent")) {
      byId("direction-intent").hidden=!view || view.selection_status==="recorded" || !view.cards.cards.length;
      byId("intent-save").disabled=busy || !!held;
      byId("intent-start").disabled=busy || !!held;
      byId("intent-start").hidden=!(boot.stage3_planning_projects || []).includes(viewProject);
      byId("intent-status").textContent=intentHold?[w()[intentHold.kind],intentNotice].filter(Boolean).join(" "):intentNotice || (view?.direction_intent?w().intentSaved:"");
      const blockers=byId("intent-blockers");if(blockers){blockers.hidden=!intentHold?.blockers.length;blockers.textContent=intentHold?intentHold.blockers.map(blocker=>typeof blocker==="string"?blocker:JSON.stringify(blocker,null,2)).join("\n"):"";}
      byId("intent-receipt").textContent=JSON.stringify({direction_intent:view?.direction_intent || null,planning_submission:intentTransaction?.submission || null,planning_work:intentTransaction?.planningWork || null},null,2);
      byId("intent-planning-link").hidden=!view?.direction_intent;
      bindPlanningLink(byId("intent-planning-link"),viewProject || "");
    }
    if(byId("intent-panel"))byId("intent-panel").hidden=byId("direction-intent").hidden;
    if(byId("formal-panel"))byId("formal-panel").hidden=byId("choice").hidden;
    if(byId("preference-bar"))byId("preference-bar").hidden=!view || view.selection_status==="recorded";
    if(byId("decision-context"))byId("decision-context").textContent=view?w().directionCount.replace("{n}",String(view.cards.cards.length))+" · "+w().eligibleCount.replace("{n}",String(view.eligible.length)):"";
    updatePreferenceSummary();
    if(!view) { if(held)byId("status").textContent=recovery.code?.startsWith("project-lock-")?w().lockUnavailable:recovery.status==="unavailable"?w().recoveryUnavailable:w().recoveryPending; return; }
    byId("planning-link").href="#"+viewProject;
    byId("return-cards").href="#"+viewProject;
    byId("status").textContent=held?(recovery.code?.startsWith("project-lock-")?w().lockUnavailable:recovery.status==="unavailable"?w().recoveryUnavailable:w().recoveryPending):notice || w()[view.selection_status==="recorded"?"saved":view.eligible.length?"ready":"none"];
    for(const card of view.cards.cards) {
      const article=node(byId("cards"),"article","");node(article,"h2",card.candidate_question || card.candidate_id);
      const version=node(article,"p","v"+card.candidate_version);version.className="card-version";
      const eligible=view.eligible.some(x=>x.candidate_id===card.candidate_id && x.candidate_version===card.candidate_version);
      const badge=node(article,"p",eligible?w().canChoose:w().canPrefer);badge.className="card-status";
      const preview=node(article,"dl","");preview.className="card-preview";
      const materials=Array.from(new Set([...card.scientific_questions.flatMap(q=>q.resource_uses.map(use=>(use.resource || use).name)),...card.unmapped_resources.map(r=>r.name)].filter(Boolean)));
      for(const [label,text] of [[w().overviewMethod,card.suggested_approach],[w().overviewMaterials,materials.length?materials.slice(0,2).join("; ")+(materials.length>2?" +"+(materials.length-2):""):w().noMaterials],[w().overviewLimit,card.limitations[0]],[w().overviewNext,card.next_checks[0]]]){node(preview,"dt",label);node(preview,"dd",previewText(text));}
      if(byId("direction-intent") && view.selection_status!=="recorded") {const label=node(article,"label",""),checkbox=document.createElement("input"),key=JSON.stringify([card.candidate_id,card.candidate_version]);checkbox.type="checkbox";checkbox.name="tentative-direction";checkbox.value=card.candidate_id;checkbox.dataset.version=String(card.candidate_version);checkbox.checked=preferredDirections.has(key);checkbox.disabled=busy;checkbox.onchange=()=>{if(checkbox.checked)preferredDirections.set(key,{candidate_id:card.candidate_id,candidate_version:card.candidate_version});else preferredDirections.delete(key);updatePreferenceSummary();};label.append(checkbox,document.createTextNode(w().prefer));const context=node(label,"span",": "+(card.candidate_question || card.candidate_id)+" · v"+card.candidate_version);context.className="control-context";}
      if(eligible && view.selection_status!=="recorded") { const label=node(article,"label",""); const radio=document.createElement("input"); radio.type="radio"; radio.name="direction"; radio.value=card.candidate_id; radio.dataset.version=String(card.candidate_version); radio.checked=selectedKey===JSON.stringify([radio.value,radio.dataset.version]); radio.required=true;radio.onchange=updatePreferenceSummary; label.append(radio,document.createTextNode(w().choose));const context=node(label,"span",": "+(card.candidate_question || card.candidate_id)+" · v"+card.candidate_version);context.className="control-context"; }
      const a=node(article,"details","");a.className="direction-details";a.dataset.directionDetails=JSON.stringify([card.candidate_id,card.candidate_version]);a.open=expanded.has(a.dataset.directionDetails);node(a,"summary",w().reviewDetails);node(a,"p",card.candidate_id+" · v"+card.candidate_version);
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
    updatePreferenceSummary();
    if(view.planning_input) { const p=view.planning_input; if(p.legacy_candidates.length) node(byId("planning-summary"),"p",w().legacy); for(const q of p.questions) {node(byId("planning-summary"),"h3",q.text);node(byId("planning-summary"),"p",q.intended_claim);} list(byId("planning-summary"),p.selection_conditions);list(byId("planning-summary"),p.unresolved);byId("planning-input").textContent=JSON.stringify(p,null,2);
      if((boot.stage3_planning_projects || []).includes(viewProject) && view.selection_status==="recorded") {const link=node(byId("planning-summary"),"a",w().continuePlanning);link.id="stage3-entry";bindPlanningLink(link,viewProject);}
    }
    byId("receipt").textContent=JSON.stringify({project_ref:view.project_ref,input_version:view.input_version,selection_receipt:view.selection_receipt,delivery_manifest_sha256:view.delivery_manifest_sha256,snapshot_sha256:view.snapshot_sha256,planning_status:view.planning_status,planning_submission:planningSubmission,execution_authorized:false},null,2);
  }
  async function load() { if(!isActive() || (embedded && reading))return; reading=true; try { const ref=byId("project").value, serial=++loadSerial; view=null; viewProject=null; requestKey=null; lastBody=null; notice=null; planningSubmission=null; intentTransaction=null;intentNotice=null;intentHold=null;preferredDirections.clear();if(byId("intent-message")){byId("intent-message").value="";byId("intent-confirmed").checked=false;} render(); if(!/^[A-Za-z0-9_-]{1,64}$/.test(ref)) {byId("status").textContent=w().unconnected;return;} try { const loaded=await api("/api/projects/"+ref+"/stage2/selection"); if(!current(ref,serial))return; if(embedded && !["project_ref","input_version","revision","brief_sha256"].every(key=>loaded[key]===binding[key]))throw new Error("stage2-embedded-version-differs"); view=loaded; viewProject=ref;const saved=intentTransactions.get(intentBinding(ref,view));if(saved){intentTransaction=saved;for(const direction of saved.body.preferred_directions)preferredDirections.set(JSON.stringify([direction.candidate_id,direction.candidate_version]),direction);if(byId("intent-message")){byId("intent-message").value=saved.body.user_input;byId("intent-confirmed").checked=true;}} if(!embedded) history.replaceState(null,"","#"+encodeURIComponent(ref)+(boot.wiki_v9?"?stage=2&lang="+encodeURIComponent(byId("language").value):"")); render(); } catch(e) {if(current(ref,serial))byId("status").textContent=w().unconnected+" ("+e.message+")";}  } finally {
    reading=false;
    if(reloadAfterRead) { reloadAfterRead=false; if(isActive() && !view && !busy && !lastBody && !intentTransactions.size) void load(); }
  } }
  byId("language").onchange=()=>{if(!embedded && boot.wiki_v9 && byId("project").value)history.replaceState(null,"","#"+encodeURIComponent(byId("project").value)+"?stage=2&lang="+encodeURIComponent(byId("language").value));render();}; byId("project").onchange=embedded?()=>{byId("project").value=binding.project_ref;}:load;
  for(const [link,target] of [["planning-link","planning"],["return-cards","cards"]]) {
    byId(link).onclick=event=>{event.preventDefault();byId(target).scrollIntoView({block:"start"});};
  }
  async function startPlanning(ref, serial, receipt, selectedView) {
    const requireMatch = ok => { if(!ok) throw new Error(w().startHeld); };
    requireMatch(receipt.status==="saved" && receipt.key===requestKey && isHex(receipt.request_sha256));
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
    uncertain=true;
    if(embedded) updatePending({phase:"planning",planning_key:request.key});
    await api(path+"/prepare",request);
    if(!current(ref,serial)) return;
    const prepared=await api(path);
    if(!current(ref,serial)) return;
    const next=prepared.default_request;
    requireMatch(matches(prepared) && next && Object.keys(request).every(key=>next[key]===request[key]) &&
      prepared.job?.status==="intent-recorded" && !prepared.submission_in_progress && !prepared.submission_error &&
      isHex(next.request_sha256) && prepared.job.request_sha256===next.request_sha256);
    if(embedded) updatePending({planning_key:next.key,planning_sha256:next.request_sha256});
    const response=await api(path+"/run",{...next,confirmed:true},{includeStatus:true}),result=response.data;
    if(!current(ref,serial)) return;
    planningSubmission=result;
    notice=result.submission_status==="accepted" ? w().startAccepted : w().startHeld;
    enterPlanning(ref,serial,selectedView,next,response);
  }
  byId("choice").onsubmit=async event=>{
    event.preventDefault();
    if(busy || (embedded && recovery) || !view || !current(viewProject,loadSerial)) return;
    const start=event.submitter?.id==="submit-and-start", ref=viewProject, serial=loadSerial;
    if(start && !(boot.stage3_planning_projects || []).includes(ref)) return;
    const selected=root.querySelector('input[name="direction"]:checked');
    if(!selected || !byId("confirmed").checked) return;
    const lines=id=>byId(id).value.split(/\r?\n/).map(x=>x.trim()).filter(Boolean);
    const body={key:requestKey || crypto.randomUUID(),revision:view.revision,input_version:view.input_version,brief_sha256:view.brief_sha256,delivery_manifest_sha256:view.delivery_manifest_sha256,workflow_head_sha256:view.workflow_head_sha256,snapshot_sha256:view.snapshot_sha256,confirmed:true,decision:{actor:byId("actor").value,kind:"select",user_text:byId("message").value,selected:[{candidate_id:selected.value,candidate_version:Number(selected.dataset.version)}],conditions:lines("conditions"),unresolved:lines("unresolved"),rationale:byId("rationale").value,scope_or_resource_change:false}};
    if(lastBody && JSON.stringify({...body,key:lastBody.key})!==JSON.stringify(lastBody)) {notice="Reload the current version before changing a submitted request.";render();return;}
    requestKey=body.key; lastBody=body; busy=true; uncertain=true; notice=null; planningSubmission=null; let confirmedStage2=false; render();
    try {
      if(embedded && !(await beginPending("stage2-select",body,start,serial)))return;
      if(!current(ref,serial))return;
      const receipt=await api("/api/projects/"+ref+"/stage2/select",body);
      if(!current(ref,serial)) return;
      const refreshed=await api("/api/projects/"+ref+"/stage2/selection");
      if(!current(ref,serial)) return;
      // Recording the selection appends to the workflow; the retained receipt,
      // not the pre-submit head, binds the resulting current workflow head.
      const saved=refreshed.selection_receipt;
      const verified = receipt.status==="saved" && receipt.kind==="stage2-select" && receipt.project_ref===ref && receipt.key===body.key && isHex(receipt.request_sha256) &&
        refreshed.project_ref===ref && refreshed.input_version===body.input_version && refreshed.brief_sha256===body.brief_sha256 &&
        refreshed.delivery_manifest_sha256===body.delivery_manifest_sha256 && refreshed.snapshot_sha256===body.snapshot_sha256 &&
        Number.isInteger(refreshed.revision) && refreshed.revision>=body.revision && refreshed.selection_status==="recorded" && refreshed.planning_status==="verified" &&
        refreshed.execution_authorized===false && refreshed.planning_input?.execution_authorized===false &&
        saved && ["key","request_sha256","delivery_manifest_sha256","interaction_file_sha256","planning_manifest_sha256","workflow_head_sha256","artifact_ref"].every(k=>saved[k]===receipt[k]) &&
        ["workflow_head_sha256","interaction_file_sha256","planning_manifest_sha256"].every(k=>isHex(saved[k])) && refreshed.workflow_head_sha256===saved.workflow_head_sha256;
      if(embedded && (!verified || receipt.request_sha256!==pendingMarker?.request_sha256)) throw new Error("stage2-embedded-selection-receipt-differs");
      confirmedStage2=!!verified;
      if(verified && (!embedded || !start)) { if(embedded) clearPending(); else uncertain=false; }
      view=refreshed; viewProject=ref; render();
      if(start) {
        if(refreshed.project_ref!==ref || refreshed.input_version!==body.input_version || refreshed.brief_sha256!==body.brief_sha256) throw new Error(w().startHeld);
        await startPlanning(ref,serial,receipt,refreshed);
      }
    } catch(e) {if(current(ref,serial)) notice=(start?w().startHeld+" ":"")+e.message;}
    finally {if(embedded && confirmedStage2 && pendingMarker?.phase==="stage2" && current(ref,serial)) {try{clearPending();}catch(_){recovery=recoveryState("unavailable","storage-unavailable","stage2-select");}}busy=false;render();}
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
    for(const key of ["request_sha256","intent_sha256","submission_sha256","advisory_manifest_sha256"])requireIntent(isHex(receipt[key]));
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
    transaction.prepareSent=true;uncertain=true;
    if(embedded) updatePending({phase:"planning",planning_key:request.key});
    await api(path+"/prepare",request);
    if(!current(ref,serial))return;
    const prepared=await api(path);
    if(!current(ref,serial))return;
    requireIntent(matches(prepared),w().intentRefresh);
    if(holdIntentPlanning(prepared))return;
    intentHold=null;
    const next=prepared.default_request;
    requireIntent(next?.direction_intent_sha256===intentHash,w().intentRefresh);
    requireIntent(prepared.planning_configured && next && Object.keys(source).every(key=>next[key]===source[key]) && Object.keys(next).every(key=>key==="request_sha256" || Object.hasOwn(source,key)) && prepared.job?.status==="intent-recorded" && !prepared.submission_in_progress && !prepared.submission_error && isHex(next.request_sha256) && prepared.job.request_sha256===next.request_sha256);
    transaction.runSent=true;
    transaction.planningWork={key:next.key,request_sha256:next.request_sha256,mode:next.mode,direction_intent_sha256:intentHash};
    if(embedded) updatePending({planning_key:next.key,planning_sha256:next.request_sha256});
    const response=await api(path+"/run",{...next,confirmed:true},{includeStatus:true}),result=response.data;
    if(!current(ref,serial))return;
    transaction.submission=result;
    intentNotice=(result.submission_status==="accepted"?w().intentStartAccepted:w().intentHeld)+" "+w().intentWork+": "+next.key+" · "+(result.job?.status || result.submission_status || w().unknown);
    enterPlanning(ref,serial,selectedView,next,response);
  }
  if(byId("direction-intent"))byId("direction-intent").onsubmit=async event=>{
    event.preventDefault();
    if(busy || (embedded && recovery) || !view || view.selection_status==="recorded" || !current(viewProject,loadSerial))return;
    const start=event.submitter?.id==="intent-start",ref=viewProject,serial=loadSerial;
    if(start && !(boot.stage3_planning_projects || []).includes(ref))return;
    if(view.project_ref!==ref){intentNotice=w().intentHeld;render();return;}
    const preferred=[...preferredDirections.values()],text=byId("intent-message").value;
    if(preferred.length<1 || preferred.length>16 || !text.trim() || text.length>4000 || !byId("intent-confirmed").checked || preferred.some(direction=>!view.cards.cards.some(card=>card.candidate_id===direction.candidate_id && card.candidate_version===direction.candidate_version))) {intentNotice=w().intentInvalid;render();return;}
    const binding=intentBinding(ref,view),existing=intentTransactions.get(binding);
    const body={key:existing?.body.key || crypto.randomUUID(),revision:existing?.body.revision ?? view.revision,input_version:view.input_version,brief_sha256:view.brief_sha256,delivery_manifest_sha256:view.delivery_manifest_sha256,workflow_head_sha256:view.workflow_head_sha256,snapshot_sha256:view.snapshot_sha256,preferred_directions:preferred,user_input:text,conditions:[],unresolved:[],confirmed:true};
    if(existing && JSON.stringify(body)!==JSON.stringify(existing.body)) {intentNotice=w().intentChanged;render();return;}
    const transaction=existing || {body,binding,prepareSent:false,runSent:false};
    intentTransactions.set(binding,transaction);intentTransaction=transaction;intentNotice=null;busy=true;uncertain=true;let confirmedStage2=false;render();
    try {
      requireIntent(!start || (!transaction.prepareSent && !transaction.runSent));
      if(embedded && !(await beginPending("stage2-direction-intent",body,start,serial)))return;
      if(!current(ref,serial))return;
      const receipt=await api("/api/projects/"+ref+"/stage2/direction-intent",body);
      if(!current(ref,serial))return;
      verifyIntentReceipt(receipt,transaction);if(embedded && receipt.request_sha256!==pendingMarker?.request_sha256)throw Error("stage2-embedded-intent-receipt-differs");transaction.receipt=receipt;
      const refreshed=await api("/api/projects/"+ref+"/stage2/selection");
      if(!current(ref,serial))return;
      verifyIntentView(ref,refreshed,transaction);confirmedStage2=true;if(!start){if(embedded)clearPending();else uncertain=false;}view=refreshed;viewProject=ref;intentNotice=w().intentSaved;render();
      if(start)await startIntentPlanning(ref,serial,transaction,refreshed);
    } catch(e) {if(current(ref,serial)){intentNotice=e.message || w().intentHeld;}}
    finally {if(embedded && confirmedStage2 && pendingMarker?.phase==="stage2" && current(ref,serial)) {try{clearPending();}catch(_){recovery=recoveryState("unavailable","storage-unavailable","stage2-direction-intent");}}busy=false;render();}
  };
  if(embedded) for(const id of ["choice","direction-intent"]) {
    const form=byId(id);if(!form?.onsubmit)continue;const handler=form.onsubmit;
    form.onsubmit=event=>{event.preventDefault();return withProjectLock(()=>handler(event));};
  }
  for(const ref of embedded ? [binding.project_ref] : boot.stage2_selection_projects || []) {const option=node(byId("project"),"option",ref);option.value=ref;}
  const fragment=embedded ? "" : location.hash.slice(1),separator=fragment.indexOf("?");
  let ref="";try{ref=decodeURIComponent(separator<0?fragment:fragment.slice(0,separator));}catch{}
  if(separator>=0){const language=new URLSearchParams(fragment.slice(separator+1)).get("lang");if(Object.hasOwn(words,language))byId("language").value=language;}
  if(embedded) { byId("project").value=binding.project_ref; if(Object.hasOwn(words,options.language)) byId("language").value=options.language; }
  else if((boot.stage2_selection_projects || []).includes(ref)) byId("project").value=ref;
  load();
  if(isActive()) api("/api/projects").then(result=>{
    if(!isActive())return;
    const rows=Array.isArray(result)?result:result.projects;
    if(!Array.isArray(rows)) throw new Error("project-labels-unavailable");
    for(const row of rows) {
      const title=row.topic || row.original_description;
      if(!boot.stage2_selection_projects?.includes(row.project_ref) || typeof title!=="string") continue;
      const name=title.replace(/\s+/g," ").slice(0,240); projectNames.set(row.project_ref,name);
      for(const option of byId("project").children) if(option.value===row.project_ref) option.textContent=name+" · "+row.project_ref;
    }
    renderProjectContext();
  }).catch(()=>{if(isActive()){projectNamesFailed=true;renderProjectContext();}});
  async function reconcile(nextBinding, selectedKey=null, confirm=false) {
    if(!embedded || disposed)return recoveryState("unavailable","recovery-unavailable",null);
    if(busy || reading)return recoveryState("unknown","operation-in-progress",pendingMarker?.kind);
    const seq=++recoverySerial;
    const stillCurrent=()=>{try{return !disposed && seq===recoverySerial && options.isCurrent(nextBinding)===true;}catch(_){return false;}};
    const report=(status,code,type)=>{const value=recoveryState(status,code,type);if(stillCurrent())recovery=value;return value;};
    if(!stillCurrent())return recoveryState("unknown","current-binding-changed",pendingMarker?.kind);
    let found;try{found=scanMarkers();}catch(_){return report("unavailable","storage-unavailable",null);}
    if(selectedKey!==null && !isKey(selectedKey))return report("unknown","invalid-pending-key",null);
    const chosen=selectedKey===null?found:found.filter(x=>x.value.key===selectedKey);
    if(chosen.length!==1 || (selectedKey===null && found.length!==1))return report("unknown",found.length?"multiple-pending":"pending-marker-missing",null);
    const item=chosen[0], m=item.value;
    if(nextBinding?.project_ref!==m.project_ref || nextBinding.input_version!==m.input_version || nextBinding.brief_sha256!==m.brief_sha256 || !Number.isSafeInteger(nextBinding.revision) || nextBinding.revision<m.revision)
      return report("unknown","binding-differs",m.kind);
    function acknowledgeVerified(code) {
      if(!stillCurrent())return recoveryState("unknown","current-binding-changed",m.kind);
      try {
        const fresh=scanMarkers(), same=fresh.filter(x=>x.key===item.key && x.raw===item.raw);
        if(same.length!==1)return report("unknown","pending-marker-changed",m.kind);
        storage.removeItem(item.key);if(storage.getItem(item.key)!==null)throw Error("storage-unavailable");
        const remaining=scanMarkers();pendingMarker=remaining.length===1?remaining[0].value:null;pendingRaw=remaining.length===1?remaining[0].raw:null;
        uncertain=remaining.length>0;recovery=remaining.length?recoveryState("unknown",remaining.length>1?"multiple-pending":"pending-receipt",pendingMarker?.kind):null;
        if(isActive())render();return recoveryState("acknowledged",code,m.kind);
      } catch(_){uncertain=true;return report("unavailable","storage-unavailable",m.kind);}
    }
    let history, latest;
    try {
      history=await api("/api/projects/"+m.project_ref+"/history");if(!stillCurrent())return recoveryState("unknown","current-binding-changed",m.kind);
      latest=await api("/api/projects/"+m.project_ref+"/stage2/selection");if(!stillCurrent())return recoveryState("unknown","current-binding-changed",m.kind);
    } catch(_) {return report("unknown","receipt-read-failed",m.kind);}
    if(history?.project_ref!==m.project_ref || history.execution_authorized!==false || history.revision!==nextBinding.revision || !Array.isArray(history.actions) ||
       !Array.isArray(history.versions) || history.versions.filter(v=>v.input_version===m.input_version && v.sha256===m.brief_sha256).length!==1 ||
       latest?.project_ref!==m.project_ref || latest.input_version!==m.input_version || latest.brief_sha256!==m.brief_sha256 || latest.revision!==nextBinding.revision ||
       latest.delivery_manifest_sha256!==m.delivery_manifest_sha256 || latest.snapshot_sha256!==m.snapshot_sha256 || latest.execution_authorized!==false)
      return report("unknown","binding-differs",m.kind);
    const matches=history.actions.filter(a=>a.key===m.key);
    if(matches.length!==1)return report("unknown","action-not-uniquely-saved",m.kind);
    const action=matches[0];
    if(action.project_ref!==m.project_ref || action.kind!==m.kind || action.status!=="saved" || action.request_sha256!==m.request_sha256 || action.execution_authorized!==false)
      return report("unknown","action-not-uniquely-saved",m.kind);
    if(m.kind==="stage2-select") {
      // The server verifies this original delivery head against the selection input.
      if(!isHex(latest.delivery_workflow_head_sha256) || latest.delivery_workflow_head_sha256!==m.workflow_head_sha256) return report("unknown","original-head-not-verified",m.kind);
      const saved=latest.selection_receipt;
      if(!saved || latest.selection_status!=="recorded" || latest.planning_status!=="verified" || latest.planning_input?.execution_authorized!==false ||
         !["key","request_sha256","delivery_manifest_sha256","interaction_file_sha256","planning_manifest_sha256","workflow_head_sha256","artifact_ref"].every(k=>saved[k]===action[k]) ||
         !["workflow_head_sha256","interaction_file_sha256","planning_manifest_sha256"].every(k=>isHex(saved[k])) || latest.workflow_head_sha256!==saved.workflow_head_sha256)
        return report("unknown","selection-receipt-differs",m.kind);
    } else {
      const saved=latest.direction_intent;
      if(saved && (saved.key!==m.key || saved.request_sha256!==m.request_sha256)) {
        if(!confirm)return report("superseded","preference-replaced",m.kind);
        const pins=["input_version","brief_sha256","delivery_manifest_sha256","workflow_head_sha256","snapshot_sha256"], bound=action.request_binding;
        const newer=history.actions.filter(a=>a.key===saved.key);
        if(!bound || typeof bound!=="object" || Array.isArray(bound) || !pins.every(k=>bound[k]===m[k]) ||
           !pins.slice(1).every(k=>isHex(bound[k])) || action.mode!=="direction-advice" || action.human_selection!=="pending" ||
           !["intent_sha256","submission_sha256","advisory_manifest_sha256"].every(k=>isHex(action[k])) || typeof action.artifact_ref!=="string" || !action.artifact_ref ||
           !isKey(saved.key) || !isHex(saved.request_sha256) || saved.status!=="saved" || saved.mode!=="direction-advice" || saved.human_selection!=="pending" || saved.execution_authorized!==false ||
           newer.length!==1 || newer[0].project_ref!==m.project_ref || newer[0].kind!==m.kind || newer[0].status!=="saved" || newer[0].execution_authorized!==false ||
           !["key","request_sha256","intent_sha256","submission_sha256","advisory_manifest_sha256","artifact_ref"].every(k=>newer[0][k]===saved[k]) ||
           !["intent_sha256","submission_sha256","advisory_manifest_sha256"].every(k=>isHex(saved[k])) ||
           m.phase!=="stage2" || latest.selection_status!=="pending") return report("unknown","original-preference-binding-unavailable",m.kind);
        return acknowledgeVerified("preference-replaced");
      }
      if(!saved || latest.selection_status!=="pending" || latest.workflow_head_sha256!==m.workflow_head_sha256 || saved.status!=="saved" || saved.mode!=="direction-advice" || saved.human_selection!=="pending" || saved.execution_authorized!==false ||
         !["key","request_sha256","intent_sha256","submission_sha256","advisory_manifest_sha256","artifact_ref"].every(k=>saved[k]===action[k]) ||
         !["intent_sha256","submission_sha256","advisory_manifest_sha256"].every(k=>hex.test(saved[k] || "")))
        return report("unknown","preference-receipt-differs",m.kind);
    }
    if(m.phase==="planning") {
      if(!m.planning_key || !m.planning_sha256)return report("unknown","planning-request-hash-unavailable",m.kind);
      let plan;try{plan=await api("/api/projects/"+m.project_ref+"/stage3/planning");}catch(_){return report("unknown","planning-read-failed",m.kind);}
      if(!stillCurrent())return recoveryState("unknown","current-binding-changed",m.kind);
      const flags=["execution_authorized","evaluation_calls_authorized","formal_execution_enabled","external_claim_ready","usable_for_formal_pairing"];
      if(plan?.project_ref!==m.project_ref || plan.input_version!==m.input_version || plan.brief_sha256!==m.brief_sha256 || plan.revision!==nextBinding.revision ||
         plan.submission_in_progress!==false || flags.some(k=>plan[k]!==false || plan.job?.[k]!==false) ||
         plan.default_request?.key!==m.planning_key || plan.default_request?.request_sha256!==m.planning_sha256 ||
         plan.job?.project_ref!==m.project_ref || plan.job?.key!==m.planning_key || plan.job?.request_sha256!==m.planning_sha256 ||
         (m.kind==="stage2-select" && plan.selection_request_sha256!==m.request_sha256) ||
         (m.kind==="stage2-direction-intent" && (plan.planning_mode!=="direction-intent" || plan.direction_intent_sha256!==action.intent_sha256 || plan.formal_selected_receiver!==false)))
        return report("unknown","planning-not-confirmed",m.kind);
      if(plan.job?.status==="completed" && plan.job?.outcome==="failed") {
        if(!confirm)return report("failed","planning-completed-failed",m.kind);
        return acknowledgeVerified("planning-completed-failed");
      }
      if(plan.job?.status!=="completed" || plan.job?.outcome!=="saved" || !isHex(plan.job?.plan_manifest_sha256) || plan.plan?.execution_authorized!==false) return report("unknown","planning-not-confirmed",m.kind);
    }
    if(confirm)return report("unknown","terminal-failure-not-confirmed",m.kind);
    if(!stillCurrent())return recoveryState("unknown","current-binding-changed",m.kind);
    try {
      const currentMarkers=scanMarkers(), match=currentMarkers.filter(x=>x.key===item.key && x.raw===item.raw);
      if(match.length!==1)return report("unknown","pending-marker-changed",m.kind);
      storage.removeItem(item.key);if(storage.getItem(item.key)!==null)throw Error("storage-unavailable");
      const remaining=scanMarkers();pendingMarker=remaining.length===1?remaining[0].value:null;pendingRaw=remaining.length===1?remaining[0].raw:null;
      uncertain=remaining.length>0;recovery=remaining.length?recoveryState("unknown",remaining.length>1?"multiple-pending":"pending-receipt",pendingMarker?.kind):recoveryState("verified","saved-receipt-matched",m.kind);
      return recoveryState("verified","saved-receipt-matched",m.kind);
    } catch(_) {uncertain=true;return report("unavailable","storage-unavailable",m.kind);}
  }
  const handle = Object.freeze({
    suspend() { active=false; loadSerial++; recoverySerial++; return {pending:busy, reading, uncertain, submitted:!!lastBody || intentTransactions.size>0}; },
    resume() {
      if(disposed) return false;
      if(active) return isActive();
      active=true; if(!isActive()){active=false;return false;}
      if(!view && !busy && !lastBody && !intentTransactions.size) { if(reading) reloadAfterRead=true; else void load(); } else render();
      return true;
    },
    setLanguage(language) { if(!Object.hasOwn(words,language) || disposed) return false; byId("language").value=language; if(active) render(); return true; },
    state() { return {active:isActive(),pending:busy,reading,uncertain,submitted:!!lastBody || intentTransactions.size>0,recovery:recovery && {...recovery}}; },
    reconcile(nextBinding,key=null) { return withProjectLock(()=>reconcile(nextBinding,key,false)); },
    pendingActions() { try { return scanMarkers().map(x=>({key:x.value.key,kind:x.value.kind,phase:x.value.phase})); } catch(_) { return null; } },
    acknowledgeTerminal(nextBinding,key) { return withProjectLock(()=>reconcile(nextBinding,key,true)); },
    dispose() {
      active=false; loadSerial++; recoverySerial++;
      if(busy || uncertain || (recovery && recovery.status!=="verified")) return false;
      disposed=true; if(embedded) embeddedSessions.delete(binding.project_ref); return true;
    }
  });
  if(embedded) embeddedSessions.set(binding.project_ref,{root,binding,handle});
  return handle;
  }
  window.STAGE2_SELECTION = Object.freeze({mount});
  if((!location.pathname || location.pathname === "/project-stage2-selection.html") && document.getElementById("project")) mount(document);
}());
