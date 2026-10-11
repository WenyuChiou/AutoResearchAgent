/* Read-only navigation over one server-bound overview; never dispatch an action. */
(function () {
  "use strict";
  const targets = Object.freeze({scope: "intake-card", planning: "plan-summary", query: "query-state", screening: "stage1-library", reading: "stage1-library", coverage: "coverage-controls", delivery: "ledger-card", history: "history", native: "native-questions"});
  const phases = ["scope", "planning", "query", "screening", "reading", "coverage", "delivery"];
  const statuses = new Set(["recorded", "available", "required", "held", "unknown", "unconnected", "partial"]);
  const labels = {
    en: {title: "Stage1 · Current progress", next: "Next step", open: "Go to this step", version: "Input version", help: "Saved steps, a validated package and accepted research are different. This guide only opens existing controls; it never starts or retries work.", missing: "Refresh saved state to read this project's progress.", localHeld: "A submission is still unconfirmed. Inspect saved history before another action.", scope: "Scope", planning: "Search plan", query: "Search", screening: "Screening", reading: "Sources & reading", coverage: "Coverage review", delivery: "Delivery & review", history: "Saved history", native: "Codex questions", recorded: "Saved", available: "Action available", required: "Needs attention", held: "Held", unknown: "Unknown", unconnected: "Unconnected", partial: "Partial", genericReason: "Inspect the saved evidence and remaining conditions."},
    "zh-Hans": {title: "Stage1 · 当前进度", next: "下一步", open: "查看这一步", version: "输入版本", help: "步骤已保存、资料包有效和研究已验收是不同状态。这里只定位已有操作，不启动或重试任务。", missing: "刷新保存状态，读取此项目的进度。", localHeld: "仍有未确认的提交。请先检查保存历史，再进行其他操作。", scope: "研究范围", planning: "检索计划", query: "文献检索", screening: "文献筛选", reading: "来源与阅读", coverage: "覆盖审阅", delivery: "交付与审阅", history: "保存历史", native: "Codex 问题", recorded: "已保存", available: "可操作", required: "待处理", held: "暂缓", unknown: "Unknown", unconnected: "未接通", partial: "部分完成", genericReason: "查看保存证据及尚未满足的条件。"},
    "zh-Hant": {title: "Stage1 · 目前進度", next: "下一步", open: "查看這一步", version: "輸入版本", help: "步驟已保存、資料包有效及研究已驗收是不同狀態。這裡只定位既有操作，不啟動或重試任務。", missing: "重新整理保存狀態，讀取此專案的進度。", localHeld: "仍有未確認的提交。請先檢查保存歷史，再進行其他操作。", scope: "研究範圍", planning: "檢索計畫", query: "文獻檢索", screening: "文獻篩選", reading: "來源與閱讀", coverage: "覆蓋審閱", delivery: "交付與審閱", history: "保存歷史", native: "Codex 問題", recorded: "已保存", available: "可操作", required: "待處理", held: "暫緩", unknown: "Unknown", unconnected: "未接通", partial: "部分完成", genericReason: "查看保存證據及尚未滿足的條件。"}
  };
  const reasons = {
    "scope-required": ["Confirm the research scope and resource limits.", "确认研究范围与资源限制。", "確認研究範圍及資源限制。"],
    "plan-required": ["Review or prepare a version-bound search plan.", "准备或审阅绑定当前版本的检索计划。", "準備或審閱綁定目前版本的檢索計畫。"],
    "query-permission-required": ["Inspect the separate search permission and budget.", "检查独立的检索许可与预算。", "檢查獨立的檢索許可及預算。"],
    "query-bootstrap-required": ["Initialize the already authorized search runtime.", "初始化已获授权的检索环境。", "初始化已獲授權的檢索環境。"],
    "query-offered": ["Review the current offered query before sending it.", "发送前检查当前提供的检索任务。", "傳送前檢查目前提供的檢索任務。"],
    "query-unconnected": ["The search runtime is not connected. Inspect configuration; a budget entry does not connect it.", "检索环境未接通。请检查配置；填写预算不会使其接通。", "檢索環境未接通。請檢查設定；填寫預算不會使其接通。"],
    "owner-reopen-required": ["Inspect the saved ledger and its explicit owner-rebinding offer before continuing.", "继续前检查保存记录及明确提供的重新绑定操作。", "繼續前檢查保存紀錄及明確提供的重新綁定操作。"],
    "screening-required": ["Inspect retained papers and save keep/reject reasons.", "检查留底文献，保存保留或排除理由。", "檢查留底文獻，保存保留或排除理由。"],
    "reading-required": ["Review bound sources, claims and reading records.", "审阅绑定来源、主张与阅读记录。", "審閱綁定來源、主張及閱讀紀錄。"],
    "coverage-required": ["Review the actual coverage gate and unresolved needs.", "审阅实际覆盖门槛与未满足的研究需要。", "審閱實際覆蓋門檻及未滿足的研究需要。"],
    "delivery-offered": ["Review the offered saved-evidence delivery.", "检查可交付的保存证据资料包。", "檢查可交付的保存證據資料包。"],
    "delivery-required": ["Inspect the current checkpoint, preparation and delivery conditions.", "检查当前 checkpoint、资料准备及交付条件。", "檢查目前 checkpoint、資料準備及交付條件。"],
    "unknown-state": ["Required state evidence is missing or inconsistent. Inspect saved history; success cannot be inferred.", "必要状态证据缺失或不一致。请检查保存历史，不能推定成功。", "必要狀態證據缺失或不一致。請檢查保存歷史，不能推定成功。"],
    "package-saved-review-required": ["A package is saved; inspect its evidence and handoff before accepting the stage.", "资料包已保存；验收阶段前仍需检查证据与交接。", "資料包已保存；驗收階段前仍須檢查證據及交接。"],
    "uncertain-action": ["Read retained action history; an uncertain outcome must not be resent.", "读取保留的操作历史；结果不明的操作不可重发。", "讀取保留的操作歷史；結果不明的操作不可重發。"],
    "active-action": ["Read the current task and any native questions. Do not send it again.", "查看当前任务及原生问题，不要重复提交。", "查看目前任務及原生問題，不要重複提交。"],
    "stale-input": ["The saved run belongs to an earlier input version. Inspect its history.", "保存运行属于旧输入版本，请检查历史。", "保存執行屬於舊輸入版本，請檢查歷史。"]
  };
  function add(parent, tag, value, className) {const node = document.createElement(tag); node.textContent = value; if (className) node.className = className; parent.append(node); return node;}
  function bound(view, project) {
    const value = view && view.binding;
    return view && view.kind === "ProjectStage1Progress" && view.schema_version === "1.0.0" && value && project
      && /^[A-Za-z0-9_-]{1,64}$/.test(project.project_ref || "") && /^[0-9a-f]{64}$/.test(project.brief_sha256 || "")
      && Number.isInteger(project.revision) && project.revision >= 0 && Number.isInteger(project.input_version) && project.input_version > 0
      && ["project_ref", "revision", "input_version", "brief_sha256"].every(key => value[key] === project[key])
      && Array.isArray(view.phases) && view.phases.length === phases.length && view.research_complete === false
      && view.phases.every((phase, index) => phase && phase.phase_id === phases[index] && statuses.has(phase.status));
  }
  function navigate(target) {
    const node = document.getElementById(targets[target]);
    if (!node || node.hidden) return;
    if (node.tagName === "DETAILS") node.open = true;
    for (let parent = node.parentElement; parent; parent = parent.parentElement) if (parent.tagName === "DETAILS") parent.open = true;
    node.scrollIntoView({block: "start", behavior: "smooth"}); node.setAttribute("tabindex", "-1"); node.focus({preventScroll: true});
  }
  function render({project, view, language, busy, loading, held}) {
    const area = document.getElementById("stage1-progress"); if (!area) return;
    const words = labels[language] || labels.en, lang = {en: 0, "zh-Hans": 1, "zh-Hant": 2}[language] ?? 0;
    area.replaceChildren(); delete area.dataset.projectRef; delete area.dataset.inputVersion;
    area.hidden = !project; if (!project) return;
    add(area, "h2", words.title);
    if (!bound(view, project)) {add(area, "p", words.missing, "subtle"); return;}
    area.dataset.projectRef = project.project_ref; area.dataset.inputVersion = String(project.input_version);
    add(area, "p", words.version + " " + project.input_version + " · r" + project.revision, "subtle");
    const grid = add(area, "ol", "", "progress-phases");
    for (const phase of view.phases) {
      if (!Object.hasOwn(targets, phase.phase_id) || !Object.hasOwn(words, phase.status)) continue;
      const item = add(grid, "li", ""); item.dataset.status = phase.status;
      add(item, "strong", words[phase.phase_id]); add(item, "span", words[phase.status]);
    }
    const next = held ? {target: "history", phase_id: "history"} : view.next_action;
    if (next && Object.hasOwn(targets, next.target)) {
      const line = add(area, "div", "", "progress-next");
      add(line, "strong", words.next + " · " + (words[next.target] || words[next.phase_id]));
      add(line, "p", held ? words.localHeld : reasons[next.reason]?.[lang] || words.genericReason);
      const button = add(line, "button", words.open); button.type = "button"; button.disabled = Boolean(busy || loading);
      button.onclick = () => navigate(next.target);
    }
    add(area, "p", words.help, "subtle");
  }
  window.ResearchStage1Progress = Object.freeze({render});
}());
