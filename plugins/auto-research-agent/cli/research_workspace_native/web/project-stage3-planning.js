/* Source-bound planning actions; no timer, credentials in storage, or automatic dispatch. */
(function () {
  "use strict";
  const boot=window.RESEARCH_PROJECTS || {}, el=id=>document.getElementById(id);
  const words={
    en:{back:"Return to project",language:"Language",title:"Stage 3 · Research planning",intro:"Turn the selected direction into a research plan. Saved conditions and unknowns remain visible.",project:"Project",selection:"Review the selected direction",refresh:"Read saved state",next:"Continue planning",boundary:"Preparing an input makes no model call. Starting planning uses the configured planner once. Experiments remain unauthorized.",prepare:"1. Prepare planning input",confirm:"I want to start planning for this saved selection.",run:"2. Start planning",inspect:"Inspect saved result",recover:"Recover verified saved result",plan:"Research plan",fullPlan:"Full plan, conditions and unresolved questions",receipt:"Version and planning receipt",pending:"Choose a current eligible direction in Stage 2 first.",unconnected:"This project has no configured planner. Your selection remains saved.",ready:"Selection saved. Prepare its planning input to continue.",prepared:"Input prepared. Confirm to start planning; no model has been called yet.",accepted:"Submission accepted. Use Read saved state to inspect the actual planning status.",dispatching:"Planning is in progress. Your saved selection is unchanged.",saved:"A verified draft plan is available. Review its conditions and unresolved questions.",failed:"Planning did not produce an accepted plan. Inspect the saved failure; no automatic retry is scheduled.",unknown:"The outcome is not confirmed. Inspect retained evidence before any further action.",loading:"Reading the current project and saved planning state…",error:"The operation could not be verified",choose:"Choose a project"},
    "zh-TW":{back:"返回專案",language:"語言",title:"Stage 3 · 研究規劃",intro:"把選定方向轉成研究計畫，保留選案條件與未知事項。",project:"專案",selection:"檢視選定方向",refresh:"讀取保存狀態",next:"接續規劃",boundary:"準備輸入不呼叫模型。開始規劃會依原設定呼叫規劃器一次，尚未授權執行實驗。",prepare:"1. 準備規劃輸入",confirm:"我要針對這次保存的選案開始規劃。",run:"2. 開始規劃",inspect:"檢查保存結果",recover:"恢復已驗證保存結果",plan:"研究計畫",fullPlan:"完整計畫、條件與未解問題",receipt:"版本與規劃收據",pending:"請先在 Stage 2 選擇目前可選方向。",unconnected:"此專案尚未設定規劃器；原選案仍已保存。",ready:"選案已保存。可準備規劃輸入。",prepared:"輸入已準備，確認後才開始規劃；尚未呼叫模型。",accepted:"已收到提交。請用「讀取保存狀態」查看實際規劃進度。",dispatching:"規劃進行中，原選案保持不變。",saved:"已取得經驗證的計畫草稿，請檢視條件與未解問題。",failed:"規劃未產生可接受計畫。請檢視原失敗，不會自動重試。",unknown:"目前無法確認結果；請先檢查保留證據。",loading:"正在讀取目前專案與保存的規劃狀態…",error:"無法驗證這次操作",choose:"選擇專案"},
    "zh-CN":{back:"返回项目",language:"语言",title:"Stage 3 · 研究规划",intro:"把选定方向转成研究计划，保留选案条件与未知事项。",project:"项目",selection:"查看选定方向",refresh:"读取保存状态",next:"继续规划",boundary:"准备输入不调用模型。开始规划会依原配置调用规划器一次，尚未授权执行实验。",prepare:"1. 准备规划输入",confirm:"我要针对这次保存的选案开始规划。",run:"2. 开始规划",inspect:"检查保存结果",recover:"恢复已验证保存结果",plan:"研究计划",fullPlan:"完整计划、条件与未解问题",receipt:"版本与规划回执",pending:"请先在 Stage 2 选择当前可选方向。",unconnected:"此项目尚未配置规划器；原选案仍已保存。",ready:"选案已保存。可准备规划输入。",prepared:"输入已准备，确认后才开始规划；尚未调用模型。",accepted:"已收到提交。请用「读取保存状态」查看实际规划进度。",dispatching:"规划进行中，原选案保持不变。",saved:"已取得经验证的计划草稿，请查看条件与未解问题。",failed:"规划未产生可接受计划。请查看原失败，不会自动重试。",unknown:"当前无法确认结果；请先检查保留证据。",loading:"正在读取当前项目与保存的规划状态…",error:"无法验证这次操作",choose:"选择项目"}
  };
  const labels=[
    ["evidenceState","Saved records and verification limits","保存紀錄與待驗證範圍","保存记录与待验证范围"],
    ["evidenceDetails","Version and authority details","版本與權限明細","版本与权限明细"],
    ["plan_id","Plan identifier","計畫識別","计划标识"],
    ["version","Plan version","計畫版本","计划版本"],
    ["schema_version","Schema version","格式版本","格式版本"],
    ["source_manifest_sha256","Bound source hash","綁定來源雜湊","绑定来源哈希"],
    ["execution_authorized","Research execution authorized","研究執行授權","研究执行授权"],
    ["evaluation_calls_authorized","Evaluation calls authorized","評分呼叫授權","评分调用授权"],
    ["formal_execution_enabled","Formal execution enabled","正式執行啟用","正式执行启用"],
    ["external_claim_ready","External claim ready","對外主張就緒","对外主张就绪"],
    ["usable_for_formal_pairing","Usable for formal pairing","可用於正式配對","可用于正式配对"],
    ["recordStatus","Saved job / plan status","保存工作／計畫狀態","保存工作／计划状态"],
    ["reviewLimit","This view supplies no semantic-review or human plan-confirmation receipt. Saved/checked is not scientific acceptance.","本頁未提供語義審查或真人計畫確認收據；保存／結構檢查不等於科學驗收。","本页未提供语义审查或真人计划确认回执；保存／结构检查不等于科学验收。"],
    ["evalLimit","This page does not run scoring, calibration, A/B or experiments.","本頁不執行評分、校準、A/B 或實驗。","本页不执行评分、校准、A/B 或实验。"],
    ["unknownValue","Unknown / not supplied","未知／未提供","未知／未提供"],
    ["noneRecorded","No entries recorded","未記錄項目","未记录项目"],
    ["missingRef","Unresolved reference","未能對應的引用","未能对应的引用"],
    ["questionIdentity","Question and selected version","問題與選案版本","问题与选案版本"],
    ["evidenceDesign","Evidence, measurement and claim boundary","證據、測量與主張邊界","证据、测量与主张边界"],
    ["materials","Data, materials, models and tools","資料、材料、模型與工具","数据、材料、模型与工具"],
    ["designs","Research / experiment design","研究／實驗設計","研究／实验设计"],
    ["analyses","Methods, analysis and uncertainty","方法、分析與不確定性","方法、分析与不确定性"],
    ["results","Planned outputs and result interpretation","規劃產物與結果判讀","规划产物与结果判读"],
    ["unknowns","Unknowns and resolution timing","未知條件與解決時點","未知条件与解决时点"],
    ["conditions","Source conditions and dispositions","來源條件與處置","来源条件与处置"],
    ["milestones","Milestones and minimum delivery","里程碑與最小交付","里程碑与最小交付"],
    ["shared","Shared across these questions; not independent replications","由下列問題共用；不計為獨立重複實驗","由下列问题共用；不计为独立重复实验"],
    ["question_ref","SQ reference","SQ 引用","SQ 引用"],
    ["candidate_id","Candidate","候選","候选"],
    ["candidate_version","Candidate version","候選版本","候选版本"],
    ["priority","Priority","優先級","优先级"],
    ["gap_ids","Gap references","缺口引用","缺口引用"],
    ["intended_claim","Intended claim","預期主張","预期主张"],
    ["evidence_needed","Necessary evidence","必要證據","必要证据"],
    ["measurement","Measurement / analysis unit","測量／分析單位","测量／分析单位"],
    ["claim_boundary","Claim boundary","主張邊界","主张边界"],
    ["resource_id","Resource reference","資源引用","资源引用"],
    ["purpose","Use for this SQ","本題用途","本题用途"],
    ["fit_rationale","Fit rationale","適配理由","适配理由"],
    ["status","Recorded status","紀錄狀態","记录状态"],
    ["origin","Resource origin","資源來源","资源来源"],
    ["availability","Availability","可用性","可用性"],
    ["access_conditions","Access / use conditions","取得／使用條件","获取／使用条件"],
    ["fitness","Material suitability","材料適用性","材料适用性"],
    ["scale_basis","Scale estimate basis","規模估算依據","规模估算依据"],
    ["minimum","Minimum resources","最小規模資源","最小规模资源"],
    ["standard","Standard resources","標準規模資源","标准规模资源"],
    ["uncertainties","Resource uncertainties","資源未知事項","资源未知事项"],
    ["design_id","Design reference","設計引用","设计引用"],
    ["question_refs","Linked questions","關聯問題","关联问题"],
    ["family","Research family","研究型態","研究类型"],
    ["procedure","Procedure","程序","程序"],
    ["comparisons","Comparisons / baselines","比較／基準","比较／基线"],
    ["description","Description","說明","说明"],
    ["reason","Reason / non-applicability","理由／不適用說明","理由／不适用说明"],
    ["credibility_checks","Credibility checks","可信度檢查","可信度检查"],
    ["failure_conditions","Failure conditions","失敗條件","失败条件"],
    ["stop_conditions","Stop conditions","停止條件","停止条件"],
    ["analysis_id","Analysis reference","分析引用","分析引用"],
    ["design_ids","Linked designs","關聯設計","关联设计"],
    ["method","Analysis method","分析方法","分析方法"],
    ["criteria","Analysis / decision criteria","分析／判定準則","分析／判定准则"],
    ["uncertainty","Uncertainty","不確定性","不确定性"],
    ["limitations","Limitations","限制","限制"],
    ["result_id","Output reference","產物引用","产物引用"],
    ["analysis_ids","Linked analyses","關聯分析","关联分析"],
    ["artifact","Planned artifact","規劃產物","规划产物"],
    ["observed_value","Observed value (null until run)","觀測值（未執行維持 null）","观测值（未执行维持 null）"],
    ["supports","If supported","若支持","若支持"],
    ["contradicts","If contradicted","若反駁","若反驳"],
    ["inconclusive","If inconclusive","若無法判定","若无法判定"],
    ["blockers","Blocking conditions","阻塞條件","阻塞条件"],
    ["minimum_deliverable","Minimum useful output","最小有用交付","最小有用交付"],
    ["unknown_id","Unknown reference","未知條件引用","未知条件引用"],
    ["kind","Condition kind","條件類型","条件类型"],
    ["blocking","Blocking","是否阻塞","是否阻塞"],
    ["resolve_before","Resolve before","最遲解決步驟","最迟解决步骤"],
    ["resolution","Resolution plan","解決規劃","解决规划"],
    ["resolution_evidence_needed","Required resolving evidence","解決所需證據","解决所需证据"],
    ["resource_ids","Affected resources","受影響資源","受影响资源"],
    ["owner","Owner (null if unassigned)","責任者（未指定為 null）","责任人（未指定为 null）"],
    ["recheck_trigger","Recheck trigger","重查觸發條件","重查触发条件"],
    ["fallback","Fallback","替代方案","替代方案"],
    ["scope_change_required","Scope change required","是否需改變範圍","是否需改变范围"],
    ["disposition","Disposition","處置","处置"],
    ["condition_ref","Source condition reference","來源條件引用","来源条件引用"],
    ["source_sha256","Source hash","來源雜湊","来源哈希"],
    ["interpretation","Condition interpretation","條件解讀","条件解读"],
    ["response","Planned response","規劃回應","规划回应"],
    ["unknown_ids","Linked unknowns","關聯未知條件","关联未知条件"],
    ["milestone_id","Milestone reference","里程碑引用","里程碑引用"],
    ["depends_on","Dependencies","相依項目","依赖项"],
    ["duration_basis","Duration estimate basis","時程估算依據","时程估算依据"],
    ["deliverable","Deliverable","交付物","交付物"],
    ["user_input","Original planning request","原始規劃要求","原始规划要求"],
    ["source_unresolved","Stage 2 source unknowns","Stage 2 來源未知事項","Stage 2 来源未知事项"],
    ["pending_scope_questions","Pending source scope questions","來源中待確認的範圍問題","来源中待确认的范围问题"],
    ["planning_blockers","Planning preparation needs clarification","規劃準備需釐清的事項","规划准备需澄清的事项"]
  ];
  labels.push(
    ["directionMode","Conditional direction planning · formal selection pending","方向條件規劃 · 正式選案待定","方向条件规划 · 正式选案待定"],
    ["planningWork","Stage 3 planning job; desktop agent conversation is not connected","Stage 3 規劃工作；桌面 agent 對話尚未接通","Stage 3 规划工作；桌面 agent 对话尚未接通"],
    ["needsInformation","More information or a narrower planning scope is needed. The preference remains saved.","需要補充必要資訊或先縮小規劃範圍；原方向意向仍已保存。","需要补充必要信息或先缩小规划范围；原方向意向仍已保存。"],
    ["pending","Save a direction preference or a current selection in Stage 2 first.","請先在 Stage 2 保存方向偏好或目前選案。","请先在 Stage 2 保存方向偏好或当前选案。"],
    ["directionIntro","Develop the saved direction preference while keeping formal selection pending.","細化已保存的方向偏好；正式選案仍待確認。","细化已保存的方向偏好；正式选案仍待确认。"],
    ["directionSelection","Review the Stage 2 direction preference","檢視 Stage 2 方向偏好","查看 Stage 2 方向偏好"],
    ["directionConfirm","Start conditional planning for this saved direction preference.","針對這次保存的方向偏好開始條件規劃。","针对这次保存的方向偏好开始条件规划。"],
    ["directionReady","Preference saved. Prepare conditional planning; formal selection remains pending.","方向偏好已保存，可準備條件規劃；正式選案仍待確認。","方向偏好已保存，可准备条件规划；正式选案仍待确认。"],
    ["directionPrepared","Input prepared. Confirm to start conditional planning; no model has been called.","輸入已準備，確認後開始條件規劃；尚未呼叫模型。","输入已准备，确认后开始条件规划；尚未调用模型。"],
    ["directionSaved","The conditional draft is saved. Review the remaining evidence and conditions.","條件規劃草稿已保存，請檢視待補證據與未解條件。","条件规划草稿已保存，请查看待补证据与未解条件。"],
    ["directionDispatching","Conditional planning is in progress; the original preference is retained.","條件規劃進行中，原方向偏好仍保留。","条件规划进行中，原方向偏好仍保留。"],
    ["directionUnconnected","No planner is configured. The direction preference remains saved.","尚未設定規劃器；方向偏好仍已保存。","尚未配置规划器；方向偏好仍已保存。"],
    ["directionQuestionIdentity","Original question and preferred direction version","原始問題與偏好方向版本","原始问题与偏好方向版本"],
    ["directionConditions","User request and source conditions","使用者要求與來源條件","用户要求与来源条件"],
    ["directionUserConditions","User conditions","使用者條件","用户条件"],
    ["directionUserUnknowns","Unresolved user questions","使用者尚待釐清的問題","用户尚待澄清的问题"],
    ["resource_ref","Use and suitability for this question","本題用途與適用性","本题用途与适用性"],
    ["resource","Recorded resource","來源資源","来源资源"],
    ["resourceVersion","Resource version","資源版本","资源版本"],
    ["resourceKind","Resource type","資源類型","资源类型"],
    ["resourceTitle","Resource name or title","資源名稱或標題","资源名称或标题"],
    ["resourceNested","Additional recorded resource details","其他資源紀錄明細","其他资源记录明细"],
    ["fit_status","Suitability status","適用性狀態","适用性状态"],
    ["fit_evidence_ids","Evidence for suitability","適用性證據","适用性证据"],
    ["license","Use permission or license","使用許可或授權","使用许可或授权"],
    ["unresolved_resource_refs","Material links still to resolve","待釐清的材料對應","待澄清的材料对应"],
    ["next_checks","Next verification steps","下一步查核","下一步核查"],
    ["next_check_status","Status of these checks","查核狀態","核查状态"],
    ["missing_mapping","Source questions needing a mapping","缺少來源對應的問題","缺少来源对应的问题"],
    ["researchMethod","Research method","研究方法","研究方法"],
    ["design","Study or experiment design","研究或實驗設計","研究或实验设计"],
    ["validation","Validation and credibility checks","驗證與可信度檢查","验证与可信度检查"],
    ["analysis","Planned analysis","預定分析","预定分析"],
    ["resultInterpretation","Interpretation of possible results","可能結果的判讀","可能结果的判读"],
  );
  for(const [key,en,tw,cn] of labels){words.en[key]=en;words["zh-TW"][key]=tw;words["zh-CN"][key]=cn;}
  let view=null,serial=0,busy=false,notice=null;
  const w=()=>words[el("language").value] || words.en;
  const directionCopy={intro:"directionIntro",selection:"directionSelection",confirm:"directionConfirm",ready:"directionReady",prepared:"directionPrepared",saved:"directionSaved",dispatching:"directionDispatching",unconnected:"directionUnconnected"};
  const copyKey=key=>view?.planning_mode==="direction-intent" && Object.hasOwn(directionCopy,key)?directionCopy[key]:key;
  const ref=()=>el("project").value;
  const current=(project,sequence)=>ref()===project && serial===sequence;
  const node=(parent,tag,text)=>{const n=document.createElement(tag);n.textContent=String(text ?? "Unknown");parent.append(n);return n;};
  const rows=value=>Array.isArray(value)?value:[];
  const missing=(parent,id)=>{const p=node(parent,"p",w().missingRef+": "+String(id ?? w().unknownValue));p.className="sq-missing";};
  function fields(parent,record,keys,displayKeys={}){
    const dl=node(parent,"dl","");dl.className="sq-fields";
    for(const key of keys){
      const label=Object.hasOwn(displayKeys,key)?displayKeys[key]:key;
      node(dl,"dt",Object.hasOwn(w(),label)?w()[label]:label.replaceAll("_"," "));const dd=node(dl,"dd","");const value=record?.[key];
      if(Array.isArray(value)){
        if(!value.length)node(dd,"span",w().noneRecorded);
        else{const ul=node(dd,"ul","");for(const item of value)node(ul,"li",typeof item==="object"?JSON.stringify(item):item);}
      }else node(dd,"span",value===undefined || value===""?w().unknownValue:value===null?"null":typeof value==="object"?JSON.stringify(value):value);
    }
  }
  function section(parent,title){const s=node(parent,"section","");s.className="sq-section";node(s,"h4",w()[title]);return s;}
  function record(parent,row,keys){
    const box=node(parent,"div","");box.className="sq-record";
    if(rows(row.question_refs).length>1)node(box,"p",w().shared);
    fields(box,row,keys);return box;
  }
  function linked(parent,title,ids,collection,key,show){
    const s=section(parent,title);
    if(!rows(ids).length)node(s,"p",w().unknownValue);
    for(const id of rows(ids)){const matches=rows(collection).filter(r=>r[key]===id);if(!matches.length)missing(s,id);for(const row of matches)show(s,row);}
  }
  function renderScientificPlan(plan){
    const target=el("questions");target.replaceChildren();
    for(const q of rows(plan?.questions)){
      const article=node(target,"article","");node(article,"h3",q.text || q.question_ref);
      fields(section(article,"questionIdentity"),q,["question_ref","candidate_id","candidate_version","priority","gap_ids","intended_claim"]);
      const plans=rows(plan.question_plans).filter(p=>p.question_ref===q.question_ref);
      if(!plans.length)missing(article,q.question_ref);
      for(const p of plans){
        fields(section(article,"evidenceDesign"),p,["evidence_needed","measurement","claim_boundary","blockers","minimum_deliverable"]);
        const materials=section(article,"materials");
        if(!rows(p.resource_uses).length)node(materials,"p",w().unknownValue);
        for(const use of rows(p.resource_uses)){
          const box=record(materials,use,["resource_id","purpose","fit_rationale","status"]);
          const resources=rows(plan.resources).filter(r=>r.resource_id===use.resource_id);
          if(!resources.length)missing(box,use.resource_id);
          for(const resource of resources)fields(box,resource,["origin","availability","access_conditions","fitness","scale_basis","minimum","standard","uncertainties"]);
        }
        linked(article,"designs",p.design_ids,plan.designs,"design_id",(s,d)=>{
          const box=record(s,d,["design_id","question_refs","family","procedure","credibility_checks","failure_conditions","stop_conditions"]);
          node(box,"h5",w().comparisons);fields(box,d.comparisons,["status","description","reason"]);
        });
        linked(article,"analyses",p.analysis_ids,plan.analyses,"analysis_id",(s,a)=>record(s,a,["analysis_id","question_refs","design_ids","method","criteria","uncertainty","limitations"]));
        linked(article,"results",p.result_ids,plan.results,"result_id",(s,r)=>{
          const box=record(s,r,["result_id","question_refs","analysis_ids","artifact","status","observed_value"]);
          fields(box,r.interpretation,["supports","contradicts","inconclusive"]);
        });
      }
      const unknowns=section(article,"unknowns");const matched=rows(plan.unknowns).filter(u=>rows(u.question_refs).includes(q.question_ref));
      if(!matched.length)node(unknowns,"p",w().noneRecorded);
      for(const u of matched)record(unknowns,u,["unknown_id","description","question_refs","resource_ids","kind","blocking","resolve_before","resolution","resolution_evidence_needed","owner","recheck_trigger","fallback","scope_change_required","disposition"]);
    }
    const conditions=el("plan-conditions");conditions.replaceChildren();
    const cs=section(conditions,"conditions");
    if(!rows(plan?.condition_dispositions).length)node(cs,"p",w().noneRecorded);
    for(const c of rows(plan?.condition_dispositions))record(cs,c,["condition_ref","source_sha256","question_refs","interpretation","disposition","response","unknown_ids"]);
    for(const u of rows(plan?.unknowns).filter(u=>!rows(u.question_refs).some(ref=>rows(plan?.questions).some(q=>q.question_ref===ref))))record(cs,u,["unknown_id","description","question_refs","blocking","resolve_before","resolution","resolution_evidence_needed","fallback"]);
    const milestones=el("plan-milestones");milestones.replaceChildren();const ms=section(milestones,"milestones");
    if(!rows(plan?.milestones).length)node(ms,"p",w().noneRecorded);
    for(const m of rows(plan?.milestones))record(ms,m,["milestone_id","description","depends_on","design_ids","duration_basis","deliverable"]);
  }
  function renderEvidence(){
    const box=el("evidence-state");box.hidden=!view;box.replaceChildren();if(!view)return;
    node(box,"h2",w().evidenceState);node(box,"p",w().recordStatus+": "+([view.job?.status,view.job?.outcome,view.job?.planning_status].filter(v=>v!==undefined && v!==null).join(" / ") || w().unknownValue));
    if(view.planning_mode==="direction-intent"){node(box,"p",w().directionMode);node(box,"p",w().planningWork);}
    node(box,"p",w().reviewLimit);node(box,"p",w().evalLimit);
    const details=node(box,"details","");node(details,"summary",w().evidenceDetails);
    fields(details,view.plan,["plan_id","version","schema_version","source_manifest_sha256"]);
    fields(details,view,["execution_authorized","evaluation_calls_authorized","formal_execution_enabled","external_claim_ready","usable_for_formal_pairing"]);
  }
  function renderDirectionResource(parent,record,title){
    const box=section(parent,title);
    if(!record || typeof record!=="object" || Array.isArray(record)){fields(box,{resource:record},["resource"]);return;}
    const keys=Object.keys(record), plain=keys.filter(k=>record[k]===null || typeof record[k]!=="object" || (Array.isArray(record[k]) && record[k].every(v=>v===null || typeof v!=="object")));
    const display={version:"resourceVersion",kind:"resourceKind",resource_type:"resourceKind",name:"resourceTitle",title:"resourceTitle"};
    if(plain.length)fields(box,record,plain,display);
    if(!keys.length)node(box,"p",w().unknownValue);
    const nested=keys.filter(k=>!plain.includes(k));
    if(nested.length){const details=node(box,"details","");node(details,"summary",w().resourceNested);fields(details,record,nested,display);}
  }
  function renderDirectionPlan(){
    const context=view.direction_context, plan=view.plan, target=el("questions");target.replaceChildren();
    el("plan-conditions").replaceChildren();el("plan-milestones").replaceChildren();
    for(const q of rows(context?.questions)){
      const article=node(target,"article","");node(article,"h3",q.text);
      fields(section(article,"directionQuestionIdentity"),q,["question_ref","candidate_id","candidate_version","priority","gap_ids","intended_claim"]);
      const card=rows(context.preferred_cards).find(c=>c.candidate_id===q.candidate_id && c.candidate_version===q.candidate_version);
      const source=rows(card?.scientific_questions).find(r=>r.question?.question_id===q.question_id);
      const materials=section(article,"materials");node(materials,"p",source?.resource_mapping_status || w().unknownValue);
      for(const use of rows(source?.resource_uses)){renderDirectionResource(materials,use.resource_ref,"resource_ref");renderDirectionResource(materials,use.resource,"resource");}
      if(source)fields(materials,source,["unresolved_resource_refs","next_checks","next_check_status"]);
      const p=rows(plan?.question_plans).find(r=>r.question_ref===q.question_ref);
      if(p){
        fields(section(article,"designs"),p,["materials","method","design","validation"],{method:"researchMethod"});
        fields(section(article,"analyses"),p,["analysis"]);
        fields(section(article,"results"),p,["interpretation","minimum_deliverable"],{interpretation:"resultInterpretation"});
        fields(section(article,"unknowns"),p,["unknowns"]);
      }else node(article,"p",w().unknownValue);
    }
    fields(section(el("plan-conditions"),"directionConditions"),context,["user_input","conditions","unresolved","source_unresolved","pending_scope_questions","missing_mapping"],{conditions:"directionUserConditions",unresolved:"directionUserUnknowns"});
    if(rows(view.planning_blockers).length)fields(section(el("plan-conditions"),"unknowns"),view,["planning_blockers"]);
    if(plan?.markdown)node(el("plan-milestones"),"p",plan.markdown);
  }
  async function api(project,action,body){const r=await fetch("/api/projects/"+encodeURIComponent(project)+"/stage3/planning"+(action?"/"+action:""),{method:body?"POST":"GET",credentials:"omit",cache:"no-store",headers:{Authorization:"Bearer "+boot.credential,...(body?{"Content-Type":"application/json"}:{})},...(body?{body:JSON.stringify(body)}:{})});const data=await r.json();if(!r.ok)throw new Error(data.error || "request-failed");return data;}
  function render(){
    document.documentElement.lang=el("language").value;
    document.querySelectorAll("[data-i18n]").forEach(n=>{n.textContent=w()[copyKey(n.dataset.i18n)];});
    const request=view?.default_request,job=view?.job,prepared=job?.status==="intent-recorded";
    el("selection").href="/project-stage2-selection.html#"+encodeURIComponent(ref());
    el("project").disabled=busy;el("refresh").disabled=busy;
    const admitted=view?.selection_status==="recorded" || view?.planning_mode==="direction-intent";
    el("actions").hidden=!view || !view.planning_configured || !admitted;
    el("prepare").disabled=busy || !request || Boolean(job);
    el("confirmed").disabled=busy || !prepared;
    el("run").disabled=busy || !prepared || !el("confirmed").checked || view?.submission_in_progress;
    el("inspect").disabled=busy || !request?.request_sha256;
    el("recover").disabled=busy || !request?.request_sha256 || !view?.recovery_pin_available || job?.outcome==="saved";
    let status=!view?"choose":!admitted?"pending":!view.planning_configured?"unconnected":(view.dispatch_action==="needs-information" || view.direction_context?.missing_mapping?.length)?"needsInformation":job?.outcome==="saved"?"saved":job?.outcome==="failed"?"failed":view.submission_error?"failed":job?.status==="execution-unknown"?"unknown":view.submission_in_progress || job?.status==="dispatching"?"dispatching":prepared?"prepared":"ready";
    el("status").textContent=notice || w()[copyKey(status)];
    renderEvidence();el("plan").hidden=!(view?.plan || view?.direction_context);if(view?.planning_mode==="direction-intent")renderDirectionPlan();else renderScientificPlan(view?.plan);
    el("plan-json").textContent=view?.plan?JSON.stringify(view.plan,null,2):"";
    el("receipt").textContent=view?JSON.stringify({...view,plan:undefined},null,2):"";
  }
  async function load(){const project=ref(),sequence=++serial;view=null;notice=w().loading;el("confirmed").checked=false;render();if(!/^[A-Za-z0-9_-]{1,64}$/.test(project)){notice=w().choose;render();return;}try{const data=await api(project);if(!current(project,sequence))return;view=data;notice=null;}catch(e){if(!current(project,sequence))return;notice=w().error+": "+e.message;}render();}
  async function act(action){if(busy || !view?.default_request)return;const project=ref(),sequence=serial,source={...view.default_request};if(action!=="prepare" && !source.request_sha256)return;if(action==="run" && !el("confirmed").checked)return;busy=true;notice=null;render();try{const data=await api(project,action,{...source,...(action==="run"?{confirmed:true}:{})});if(!current(project,sequence))return;if(action==="run" && data.submission_status==="accepted"){notice=w().accepted;el("confirmed").checked=false;}else{const dataView=await api(project);if(!current(project,sequence))return;view=dataView;notice=null;}}catch(e){if(current(project,sequence))notice=w().error+": "+e.message;}finally{busy=false;render();}}
  el("language").onchange=render;el("project").onchange=load;el("refresh").onclick=load;el("confirmed").onchange=render;
  for(const action of ["prepare","run","inspect","recover"])el(action).onclick=()=>act(action);
  for(const project of boot.stage3_planning_projects || []){const option=node(el("project"),"option",project);option.value=project;}
  const initial=location.hash.slice(1);if((boot.stage3_planning_projects || []).includes(initial))el("project").value=initial;
  load();
}());
