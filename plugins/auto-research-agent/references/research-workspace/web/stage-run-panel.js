(() => {
  "use strict";
  const config = window.WORKSPACE_STAGE_RUN;
  delete window.WORKSPACE_STAGE_RUN;
  if (!config || !config.credential || !config.project_ref) return;
  const base = "/api/stage-run/projects/" + encodeURIComponent(config.project_ref);
  const panel = document.createElement("section");
  panel.className = "stage-run-panel";
  panel.id = "stage-run-panel";
  const title = document.createElement("h2"), context = document.createElement("p");
  const banner = document.createElement("div"), next = document.createElement("p");
  const run = document.createElement("button"), refresh = document.createElement("button"), publish = document.createElement("button");
  const history = document.createElement("div"), notice = document.createElement("p"), native = document.createElement("div"), candidates = document.createElement("div"), deliveries = document.createElement("div");
  banner.className = "stage-run-banner";
  refresh.className = "stage-run-refresh";
  notice.setAttribute("role", "status");
  panel.append(title, context, banner, next, run, refresh, publish, notice, native, candidates, history, deliveries);
  const footer = document.querySelector("#atlas-footer");
  if (footer) footer.before(panel); else document.body.append(panel);
  const labels = {
    en: ["Codex × Harness · run one step", "Repository test sources · real model execution. Independent scientific assessment remains pending.", "Run this step", "Refresh saved progress", "Next step", "No further permitted step", "Reserved model calls", "Seconds remaining", "Submitting; a lost response is recovered by refreshing, never automatic resend.", "Request outcome unknown. Refresh progress before taking another action."],
    zh: ["Codex × Harness · 逐步执行", "仓库测试来源 · 真实模型执行；独立科学评估仍待完成。", "执行这一步", "刷新已保存的进度", "下一步", "暂无可执行的后续步骤", "已预留模型调用", "剩余秒数", "正在提交；丢失响应时只刷新查询，不自动重发。", "请求结果尚不确定。请先刷新进度，再决定下一步。"],
    "zh-Hant": ["Codex × Harness · 逐步執行", "倉庫測試來源 · 真實模型執行；獨立科學評估仍待完成。", "執行這一步", "重新整理已儲存的進度", "下一步", "暫無可執行的後續步驟", "已預留模型呼叫", "剩餘秒數", "正在提交；遺失回應時只重新整理查詢，不自動重送。", "請求結果尚不確定。請先重新整理進度，再決定下一步。"]
  };
  const phases = {
    "source-review": ["Stage 1 · source review", "Stage 1 · 来源审阅", "Stage 1 · 來源審閱"],
    research: ["Stage 2 · proposal generation", "Stage 2 · 生成研究路线", "Stage 2 · 生成研究路線"],
    extraction: ["Stage 2 · extract and validate", "Stage 2 · 擷取与校验", "Stage 2 · 擷取與校驗"],
    challenger: ["Independent challenger", "独立质疑审查", "獨立質疑審查"],
    "challenger-extraction": ["Validate challenger review", "校验质疑审查", "校驗質疑審查"],
    feasibility: ["Independent feasibility review", "独立可行性审查", "獨立可行性審查"],
    "feasibility-extraction": ["Validate feasibility review", "校验可行性审查", "校驗可行性審查"],
    reconciliation: ["Reconcile evidence", "综合审查证据", "綜合審查證據"],
    "reconciliation-extraction": ["Validate reconciliation", "校验综合结果", "校驗綜合結果"]
  };
  let state = null, submitting = false;
  const drafts = new Map(), held = new Set();
  let currentNative = null, nativeSignature = null;
  const lang = () => {
    const value = (document.querySelector("#atlas-language, #language, #lang, select[aria-label]") || {}).value || document.documentElement.lang || "en";
    return /Hant|TW|traditional/.test(value) ? "zh-Hant" : /zh|cn|简/.test(value) ? "zh" : "en";
  };
  const phaseName = phase => (phases[phase] || [phase, phase, phase])[lang() === "en" ? 0 : lang() === "zh" ? 1 : 2];
  async function request(path, body) {
    const options = {headers: {Authorization: "Bearer " + config.credential}, cache: "no-store"};
    if (body) { options.method = "POST"; options.headers["Content-Type"] = "application/json"; options.body = JSON.stringify(body); }
    const response = await fetch(base + path, options);
    const value = await response.json();
    if (!response.ok) throw new Error(value.error || String(response.status));
    return value;
  }
  function draw() {
    const text = labels[lang()];
    title.textContent = text[0]; context.textContent = text[1];
    run.textContent = text[2]; refresh.textContent = text[3];
    publish.textContent = lang() === "en" ? "Save current delivery" : lang() === "zh" ? "保存当前交付" : "儲存目前交付";
    publish.disabled = submitting || !state?.pipeline.candidates?.length || state?.jobs.some(job => ["running", "intent-recorded"].includes(job.status));
    run.disabled = submitting || !state || !state.ready;
    if (!state) return;
    banner.textContent = `${text[6]}: ${state.budget.reserved} / ${state.budget.max_calls} · ${text[7]}: ${state.budget.seconds_remaining} · ${state.pipeline.status}`;
    next.textContent = state.next_task ? `${text[4]}: ${phaseName(state.next_task.phase)}` : text[5];
    if (state.blocked) { notice.textContent = state.blocked; notice.className = "stage-run-error"; }
    history.replaceChildren();
    candidates.replaceChildren();
    for (const candidate of state.pipeline.candidates || []) {
      const card = document.createElement("article"), heading = document.createElement("h3");
      heading.textContent = candidate.question || candidate.candidate_id;
      card.append(heading);
      for (const field of ["opportunity", "value", "approach"]) {
        if (typeof candidate[field] === "string") { const text = document.createElement("p"); text.textContent = candidate[field]; card.append(text); }
      }
      const limitations = document.createElement("p");
      limitations.textContent = (candidate.limitations || []).join(" · "); card.append(limitations);
      candidates.append(card);
    }
    deliveries.replaceChildren();
    for (const [key, receipt] of Object.entries(state.deliveries || {})) {
      const button = document.createElement("button"); button.className = "stage-run-refresh";
      button.textContent = lang() === "en" ? `Download current HTML · ${receipt.status}` : `下载当前 HTML · ${receipt.status}`;
      button.disabled = receipt.status !== "saved";
      button.addEventListener("click", async () => {
        try {
          const response = await fetch(base + "/deliveries/" + encodeURIComponent(key), {headers: {Authorization: "Bearer " + config.credential}, cache: "no-store"});
          if (!response.ok) throw new Error("delivery-download-rejected");
          const url = URL.createObjectURL(await response.blob()), link = document.createElement("a");
          link.href = url; link.download = "stage2-native-partial.html"; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
        } catch (error) { notice.textContent = error.message; }
      });
      deliveries.append(button);
    }
    for (const job of state.jobs) {
      const details = document.createElement("details"), summary = document.createElement("summary");
      summary.textContent = `${phaseName(job.task.phase)} · ${job.status}`;
      details.append(summary);
      if (job.final_text) { const output = document.createElement("pre"); output.textContent = job.final_text; details.append(output); }
      if (job.error) { const error = document.createElement("p"); error.textContent = job.error; error.className = "stage-run-error"; details.append(error); }
      history.append(details);
    }
  }
  async function load() {
    try { state = await request(""); draw(); renderNative((await request("/native")).native_view); }
    catch (error) { notice.textContent = error.message; notice.className = "stage-run-error"; run.disabled = true; }
  }
  async function nativeAction(view, target, result) {
    view = currentNative;
    if (!view) return;
    const ref = target.request_ref || target.action_ref;
    if (held.has(ref)) return;
    const key = "ui-" + crypto.randomUUID();
    const body = {key, revision: view.revision, index_sha256: view.index_sha256, input_version: view.input_version,
      ...(target.request_ref ? {request_ref: ref, request_sha256: target.request_sha256, result} :
        {action_ref: ref, action_sha256: target.action_sha256})};
    sessionStorage.setItem("stage-run-native-intent:" + ref, JSON.stringify({key, ref}));
    held.add(ref);
    try { await request(target.request_ref ? "/answers" : "/interrupts", body); }
    catch (error) { notice.textContent = labels[lang()][9] + " " + error.message; }
    await load();
  }
  function renderNative(view) {
    currentNative = view;
    const signature = JSON.stringify([view?.requests, view?.operations, lang(), [...held]]);
    if (signature === nativeSignature) return;
    nativeSignature = signature;
    native.replaceChildren();
    if (!view) return;
    for (const target of view.requests.filter(item => item.status === "pending")) {
      const form = document.createElement("form"), fields = [];
      const locked = held.has(target.request_ref) || sessionStorage.getItem("stage-run-native-intent:" + target.request_ref);
      for (const q of target.payload.questions || []) {
        const label = document.createElement("label"), prompt = document.createElement("p");
        prompt.textContent = q.question;
        const field = document.createElement(q.isSecret ? "input" : "textarea");
        if (q.isSecret) field.type = "password";
        const id = target.request_ref + ":" + q.id;
        field.value = drafts.get(id) || ""; field.maxLength = 8000; field.required = true; field.disabled = Boolean(locked);
        field.addEventListener("input", () => drafts.set(id, field.value));
        label.append(prompt, field); form.append(label); fields.push([q.id, field]);
      }
      if (target.method === "item/tool/requestUserInput") {
        const button = document.createElement("button"); button.textContent = lang() === "en" ? "Reply to Codex" : "回复 Codex";
        button.disabled = Boolean(locked); form.append(button);
        form.addEventListener("submit", event => {event.preventDefault(); nativeAction(view, target,
          {answers: Object.fromEntries(fields.map(([id, field]) => [id, {answers: [field.value]}]))});});
      } else {
        const reason = document.createElement("p"); reason.textContent = target.payload.reason || target.method; form.append(reason);
        // The content-only permit authorizes refusal/cancellation, never commands or file writes.
        for (const decision of ["decline", "cancel"]) {
          const button = document.createElement("button"); button.type = "button"; button.textContent = decision;
          button.disabled = Boolean(locked); button.addEventListener("click", () => nativeAction(view, target, {decision})); form.append(button);
        }
      }
      native.append(form);
    }
    for (const op of view.operations.filter(item => item.can_interrupt === true)) {
      const button = document.createElement("button"); button.textContent = lang() === "en" ? "Stop this model turn" : "停止这一轮模型执行";
      button.disabled = held.has(op.action_ref) || Boolean(sessionStorage.getItem("stage-run-native-intent:" + op.action_ref));
      button.addEventListener("click", () => nativeAction(view, op)); native.append(button);
    }
  }
  run.addEventListener("click", async () => {
    if (submitting || !state || !state.ready || !state.next_task) return;
    submitting = true; run.disabled = true; notice.textContent = labels[lang()][8];
    const key = "ui-" + crypto.randomUUID();
    const body = {key, revision: state.revision, task_sha256: state.next_task.task_sha256, confirmed: true};
    // Save non-secret intent before POST. Refresh only queries server history.
    sessionStorage.setItem("stage-run-intent:" + config.project_ref, JSON.stringify(body));
    try { await request("/actions", body); notice.textContent = ""; }
    catch (error) { notice.textContent = labels[lang()][9] + " " + error.message; }
    finally { submitting = false; await load(); }
  });
  refresh.addEventListener("click", load);
  publish.addEventListener("click", async () => {
    if (submitting || !state) return;
    submitting = true;
    const body = {key: "delivery-" + crypto.randomUUID(), revision: state.revision, confirmed: true};
    try { sessionStorage.setItem("stage-run-delivery-intent:" + config.project_ref, JSON.stringify(body)); await request("/deliveries", body); }
    catch (error) { notice.textContent = error.message; }
    finally { submitting = false; await load(); }
  });
  document.addEventListener("change", draw);
  new MutationObserver(draw).observe(document.documentElement, {attributes: true, attributeFilter: ["lang"]});
  load();
  // Polling is read-only: no POST, new intent, pump or model admission.
  const timer = setInterval(load, 2500);
  window.addEventListener("pagehide", () => clearInterval(timer), {once: true});
})();
