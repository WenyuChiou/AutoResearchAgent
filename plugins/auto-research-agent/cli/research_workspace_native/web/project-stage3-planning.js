/* Source-bound planning actions; no timer, credentials in storage, or automatic dispatch. */
(function () {
  "use strict";
  const boot=window.RESEARCH_PROJECTS || {}, el=id=>document.getElementById(id);
  const words={
    en:{back:"Return to project",language:"Language",title:"Stage 3 · Research planning",intro:"Turn the selected direction into a research plan. Saved conditions and unknowns remain visible.",project:"Project",selection:"Review the selected direction",refresh:"Read saved state",next:"Continue planning",boundary:"Preparing an input makes no model call. Starting planning uses the configured planner once. Experiments remain unauthorized.",prepare:"1. Prepare planning input",confirm:"I want to start planning for this saved selection.",run:"2. Start planning",inspect:"Inspect saved result",recover:"Recover verified saved result",plan:"Research plan",fullPlan:"Full plan, conditions and unresolved questions",receipt:"Version and planning receipt",pending:"Choose a current eligible direction in Stage 2 first.",unconnected:"This project has no configured planner. Your selection remains saved.",ready:"Selection saved. Prepare its planning input to continue.",prepared:"Input prepared. Confirm to start planning; no model has been called yet.",accepted:"Submission accepted. Use Read saved state to inspect the actual planning status.",dispatching:"Planning is in progress. Your saved selection is unchanged.",saved:"A verified draft plan is available. Review its conditions and unresolved questions.",failed:"Planning did not produce an accepted plan. Inspect the saved failure; no automatic retry is scheduled.",unknown:"The outcome is not confirmed. Inspect retained evidence before any further action.",loading:"Reading the current project and saved planning state…",error:"The operation could not be verified",choose:"Choose a project"},
    "zh-TW":{back:"返回專案",language:"語言",title:"Stage 3 · 研究規劃",intro:"把選定方向轉成研究計畫，保留選案條件與未知事項。",project:"專案",selection:"檢視選定方向",refresh:"讀取保存狀態",next:"接續規劃",boundary:"準備輸入不呼叫模型。開始規劃會依原設定呼叫規劃器一次，尚未授權執行實驗。",prepare:"1. 準備規劃輸入",confirm:"我要針對這次保存的選案開始規劃。",run:"2. 開始規劃",inspect:"檢查保存結果",recover:"恢復已驗證保存結果",plan:"研究計畫",fullPlan:"完整計畫、條件與未解問題",receipt:"版本與規劃收據",pending:"請先在 Stage 2 選擇目前可選方向。",unconnected:"此專案尚未設定規劃器；原選案仍已保存。",ready:"選案已保存。可準備規劃輸入。",prepared:"輸入已準備，確認後才開始規劃；尚未呼叫模型。",accepted:"已收到提交。請用「讀取保存狀態」查看實際規劃進度。",dispatching:"規劃進行中，原選案保持不變。",saved:"已取得經驗證的計畫草稿，請檢視條件與未解問題。",failed:"規劃未產生可接受計畫。請檢視原失敗，不會自動重試。",unknown:"目前無法確認結果；請先檢查保留證據。",loading:"正在讀取目前專案與保存的規劃狀態…",error:"無法驗證這次操作",choose:"選擇專案"},
    "zh-CN":{back:"返回项目",language:"语言",title:"Stage 3 · 研究规划",intro:"把选定方向转成研究计划，保留选案条件与未知事项。",project:"项目",selection:"查看选定方向",refresh:"读取保存状态",next:"继续规划",boundary:"准备输入不调用模型。开始规划会依原配置调用规划器一次，尚未授权执行实验。",prepare:"1. 准备规划输入",confirm:"我要针对这次保存的选案开始规划。",run:"2. 开始规划",inspect:"检查保存结果",recover:"恢复已验证保存结果",plan:"研究计划",fullPlan:"完整计划、条件与未解问题",receipt:"版本与规划回执",pending:"请先在 Stage 2 选择当前可选方向。",unconnected:"此项目尚未配置规划器；原选案仍已保存。",ready:"选案已保存。可准备规划输入。",prepared:"输入已准备，确认后才开始规划；尚未调用模型。",accepted:"已收到提交。请用「读取保存状态」查看实际规划进度。",dispatching:"规划进行中，原选案保持不变。",saved:"已取得经验证的计划草稿，请查看条件与未解问题。",failed:"规划未产生可接受计划。请查看原失败，不会自动重试。",unknown:"当前无法确认结果；请先检查保留证据。",loading:"正在读取当前项目与保存的规划状态…",error:"无法验证这次操作",choose:"选择项目"}
  };
  let view=null,serial=0,busy=false,notice=null;
  const w=()=>words[el("language").value] || words.en;
  const ref=()=>el("project").value;
  const current=(project,sequence)=>ref()===project && serial===sequence;
  const node=(parent,tag,text)=>{const n=document.createElement(tag);n.textContent=String(text ?? "Unknown");parent.append(n);return n;};
  async function api(project,action,body){const r=await fetch("/api/projects/"+encodeURIComponent(project)+"/stage3/planning"+(action?"/"+action:""),{method:body?"POST":"GET",credentials:"omit",cache:"no-store",headers:{Authorization:"Bearer "+boot.credential,...(body?{"Content-Type":"application/json"}:{})},...(body?{body:JSON.stringify(body)}:{})});const data=await r.json();if(!r.ok)throw new Error(data.error || "request-failed");return data;}
  function render(){
    document.documentElement.lang=el("language").value;
    document.querySelectorAll("[data-i18n]").forEach(n=>{n.textContent=w()[n.dataset.i18n];});
    const request=view?.default_request,job=view?.job,prepared=job?.status==="intent-recorded";
    el("selection").href="/project-stage2-selection.html#"+encodeURIComponent(ref());
    el("project").disabled=busy;el("refresh").disabled=busy;
    el("actions").hidden=!view || !view.planning_configured || view.selection_status!=="recorded";
    el("prepare").disabled=busy || !request || Boolean(job);
    el("confirmed").disabled=busy || !prepared;
    el("run").disabled=busy || !prepared || !el("confirmed").checked || view?.submission_in_progress;
    el("inspect").disabled=busy || !request?.request_sha256;
    el("recover").disabled=busy || !request?.request_sha256 || !view?.recovery_pin_available || job?.outcome==="saved";
    let status=!view?"choose":view.selection_status!=="recorded"?"pending":!view.planning_configured?"unconnected":job?.outcome==="saved"?"saved":job?.outcome==="failed"?"failed":view.submission_error?"failed":job?.status==="execution-unknown"?"unknown":view.submission_in_progress || job?.status==="dispatching"?"dispatching":prepared?"prepared":"ready";
    el("status").textContent=notice || w()[status];
    el("plan").hidden=!view?.plan;el("questions").replaceChildren();
    for(const q of view?.plan?.questions || []){const a=node(el("questions"),"article","");node(a,"h3",q.text || q.id);node(a,"p",q.intended_claim);}
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
