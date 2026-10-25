/* Six stage areas over one bound saved contract. Navigation grants no authority. */
(function () {
  "use strict";
  const stages = [1, 2, 3, 4, 5, 6], identityKeys = ["project_ref", "input_version", "revision", "brief_sha256"];
  const outputs = [["scope", "search-plan", "coverage-ledger", "source-notes", "canonical-delivery"], ["source-handoff", "comparison", "candidate-routes", "independent-review", "selection-package"], ["design", "feasibility-review"], ["experiment-plan", "run-records"], ["analysis", "figures"], ["manuscript", "submission-review"]];
  const words = {
    en: {names: ["Literature & evidence", "Comparison & research directions", "Research design & feasibility", "Experiment execution", "Analysis & figures", "Writing & submission"], operations: "Operations", results: "Delivered results", status: "Saved stage status", expected: "Expected outputs", version: "Input version", connection: "Connection", accepted: "Research acceptance", permission: "Execution authorization", attempts: "Recorded attempts", questions: "Pending questions", metrics: "Saved measurements", records: "Saved records and evidence", missing: "Saved stage state is unavailable for this project version. Refresh saved state to inspect it.", loading: "Reading this project's saved stage state…", noProject: "Choose a research project to inspect this stage.", planned: "Planned", unconnected: "Unconnected", connected: "Connected", yes: "Yes", no: "No", unknown: "Unknown", future: "This stage is planned and its execution is not connected. Its own inputs, operations and results will appear here when a stage adapter is available.", action: "Execution not connected", empty: "Not generated yet.", stage2Missing: "This project's saved Stage 2 comparison and direction view has no connected producer. Review the Stage 1 input above; a saved review does not generate research directions."},
    "zh-Hans": {names: ["文献与证据", "比较与研究方向", "研究设计与可行性", "实验执行", "分析与图表", "写作与投稿"], operations: "运行操作", results: "交付结果", status: "已保存阶段状态", expected: "预期输出", version: "输入版本", connection: "接口连接", accepted: "研究验收", permission: "执行授权", attempts: "已登记尝试", questions: "待处理问题", metrics: "已保存量测", records: "保存记录与证据", missing: "此项目版本的已保存阶段状态不可用。请刷新保存状态后检查。", loading: "正在读取当前项目的已保存阶段状态…", noProject: "请选择研究项目，再查看此阶段。", planned: "已规划", unconnected: "未接通", connected: "已接通", yes: "是", no: "否", unknown: "Unknown", future: "此阶段已规划，执行尚未接通。阶段接口可用后，自己的输入、操作与结果会显示在这里。", action: "执行尚未接通", empty: "尚未生成。", stage2Missing: "当前项目尚未连接已保存的 Stage 2 比较与方向结果。请先审阅上方 Stage 1 输入；保存审阅不会生成研究方向。"},
    "zh-Hant": {names: ["文獻與證據", "比較與研究方向", "研究設計與可行性", "實驗執行", "分析與圖表", "寫作與投稿"], operations: "執行操作", results: "交付結果", status: "已保存階段狀態", expected: "預期輸出", version: "輸入版本", connection: "介面連接", accepted: "研究驗收", permission: "執行授權", attempts: "已登記嘗試", questions: "待處理問題", metrics: "已保存量測", records: "保存紀錄與證據", missing: "此專案版本的已保存階段狀態不可用。請重新整理保存狀態後檢查。", loading: "正在讀取目前專案的已保存階段狀態…", noProject: "請選擇研究專案，再檢視此階段。", planned: "已規劃", unconnected: "未接通", connected: "已接通", yes: "是", no: "否", unknown: "Unknown", future: "此階段已規劃，執行尚未接通。階段介面可用後，自己的輸入、操作及結果會顯示在這裡。", action: "執行尚未接通", empty: "尚未產生。", stage2Missing: "目前專案尚未連接已保存的 Stage 2 比較與方向結果。請先審閱上方 Stage 1 輸入；保存審閱不會產生研究方向。"}
  };
  Object.assign(words.en, {selectionEntry: "Review directions and choose", selectionIntro: "Read the current directions, evidence and materials before confirming a version. Opening this view does not start research."});
  Object.assign(words["zh-Hans"], {selectionEntry: "比较方向并选择", selectionIntro: "先阅读当前方向、证据与材料，再确认版本。打开此页面不会启动研究。"});
  Object.assign(words["zh-Hant"], {selectionEntry: "比較方向並選案", selectionIntro: "先閱讀目前方向、證據與材料，再確認版本。開啟此頁不會啟動研究。"});
  Object.assign(words.en, {planningEntry: "Continue Stage 3 planning", planningIntro: "Planning is connected. Review the saved choice, prepare an input and explicitly start planning. Experiment execution remains disconnected."});
  Object.assign(words["zh-Hans"], {planningEntry: "继续 Stage 3 规划", planningIntro: "规划接口已接通。查看保存的选择，准备输入后明确开始规划。实验执行仍未接通。"});
  Object.assign(words["zh-Hant"], {planningEntry: "接續 Stage 3 規劃", planningIntro: "規劃介面已接通。檢視保存選案，準備輸入後明確開始規劃。實驗執行仍未接通。"});
  const outputWords = {
    scope: ["Confirmed scope", "已确认研究范围", "已確認研究範圍"], "search-plan": ["Search plan", "检索计划", "檢索計畫"], "coverage-ledger": ["Coverage ledger", "覆盖记录", "覆蓋紀錄"], "source-notes": ["Source notes", "来源笔记", "來源筆記"], "canonical-delivery": ["Canonical delivery", "规范交付包", "規範交付包"],
    "source-handoff": ["Stage1 evidence handoff", "Stage1 证据交接", "Stage1 證據交接"], comparison: ["Literature comparison", "文献比较", "文獻比較"], "candidate-routes": ["Candidate directions", "候选研究方向", "候選研究方向"], "independent-review": ["Independent review", "独立查核", "獨立查核"], "selection-package": ["Direction selection package", "方向选择包", "方向選擇包"],
    design: ["Research design", "研究设计", "研究設計"], "feasibility-review": ["Feasibility review", "可行性审阅", "可行性審閱"], "experiment-plan": ["Experiment plan", "实验计划", "實驗計畫"], "run-records": ["Experiment records", "实验记录", "實驗紀錄"], analysis: ["Analysis", "结果分析", "結果分析"], figures: ["Figures", "图表", "圖表"], manuscript: ["Manuscript", "论文稿件", "論文稿件"], "submission-review": ["Submission review", "投稿审阅", "投稿審閱"]
  };
  let active = 1, current = null, language = "en";
  const same = (left, right) => left && right && identityKeys.every(key => left[key] === right[key]);
  // Preserve the type and bounds used by ui_submission.valid_input_version.
  const inputVersion = value => Number.isSafeInteger(value) && value > 0 || typeof value === "string" && [...value].length > 0 && [...value].length <= 128 && !/[\u0000-\u001f\u007f]/u.test(value) && !/^\p{White_Space}|\p{White_Space}$/u.test(value);
  const identity = project => project && /^[A-Za-z0-9_-]{1,64}$/.test(project.project_ref || "") && inputVersion(project.input_version) && Number.isSafeInteger(project.revision) && project.revision >= 0 && /^[0-9a-f]{64}$/.test(project.brief_sha256 || "");
  function bound(contract, project) {
    return identity(project) && contract && contract.kind === "HarnessUiProjectView" && contract.schema_version === (typeof project.input_version === "string" ? "1.1.0" : "1.0.0") && same(contract.identity, project)
      && contract.stages && stages.every(number => {
        const stage = contract.stages[String(number)];
        return stage && stage.stage === String(number) && same(stage.input, project) && typeof stage.status === "string" && stage.status.length > 0 && stage.status.length <= 128
          && ["connected", "accepted", "execution_authorized"].every(key => typeof stage[key] === "boolean")
          && ["expected_outputs", "artifacts", "attempts", "pending_questions", "approvals"].every(key => Array.isArray(stage[key]))
          && stage.metrics && typeof stage.metrics === "object" && !Array.isArray(stage.metrics)
          && (number < 3 || stage.status === "planned" && stage.connected === false && stage.accepted === false && stage.execution_authorized === false && stage.artifacts.length === 0 && stage.attempts.length === 0);
      });
  }
  function add(parent, tag, value, source = false) {
    const node = document.createElement(tag); node.textContent = value;
    if (source) node.setAttribute("translate", "no"); parent.append(node); return node;
  }
  function emit() {
    const detail = {stage: active};
    if (identity(current)) for (const key of identityKeys) detail[key] = current[key];
    window.dispatchEvent(new CustomEvent("research-project-stage", {detail}));
  }
  function showStage(number) {
    if (!Number.isSafeInteger(number) || !stages.includes(number)) return false;
    active = number;
    for (const stage of stages) {
      const slot = document.getElementById("project-stage-" + stage), nav = document.getElementById("project-stage-nav-" + stage);
      if (slot) slot.hidden = stage !== active;
      if (nav) nav.setAttribute("aria-current", stage === active ? "step" : "false");
    }
    emit(); return true;
  }
  function render({project, contract, language: nextLanguage = "en", loading = false}) {
    language = Object.hasOwn(words, nextLanguage) ? nextLanguage : "en"; current = identity(project) ? project : null;
    const w = words[language], lang = {en: 0, "zh-Hans": 1, "zh-Hant": 2}[language], valid = !loading && bound(contract, project);
    document.querySelectorAll("[data-stage-text]").forEach(node => {if (Object.hasOwn(w, node.dataset.stageText)) node.textContent = w[node.dataset.stageText];});
    for (const number of stages) {
      const title = document.getElementById("project-stage-" + number + "-title"), area = document.getElementById("project-stage-" + number + "-status"), nav = document.getElementById("project-stage-nav-" + number);
      if (title) title.textContent = w.names[number - 1];
      if (nav) {nav.textContent = number + ". " + w.names[number - 1]; nav.onclick = () => showStage(number);}
      if (!area) continue;
      area.replaceChildren(); delete area.dataset.projectRef; delete area.dataset.inputVersion;
      add(area, "h3", w.status);
      const stage = valid ? contract.stages[String(number)] : null;
      if (current) {
        area.dataset.projectRef = current.project_ref; area.dataset.inputVersion = String(current.input_version);
        add(area, "p", current.project_ref + " · " + w.version + " " + current.input_version + " · r" + current.revision, true);
      }
      if (!stage) add(area, "p", loading ? w.loading : current ? w.missing : w.noProject);
      const facts = add(area, "dl", ""); facts.className = "project-stage-facts";
      const rows = [[w.status, number >= 3 ? w.planned : stage ? stage.status : w.unknown], [w.connection, number >= 3 ? w.unconnected : stage ? stage.connected ? w.connected : w.unconnected : w.unknown], [w.accepted, stage ? stage.accepted ? w.yes : w.no : w.unknown], [w.permission, number >= 3 ? w.no : stage ? stage.execution_authorized ? w.yes : w.no : w.unknown]];
      if (stage) rows.push([w.attempts, String(stage.attempts.length)], [w.questions, String(stage.pending_questions.length)]);
      for (const [label, value] of rows) {add(facts, "dt", label); add(facts, "dd", value, true);}
      add(area, "h4", w.expected);
      const list = add(area, "ul", ""); list.className = "project-stage-outputs";
      for (const code of stage ? stage.expected_outputs : outputs[number - 1]) add(list, "li", outputWords[code]?.[lang] || String(code), !outputWords[code]);
      if (stage) {
        const measurements = add(area, "details", ""); measurements.className = "project-stage-measurements"; add(measurements, "summary", w.metrics);
        for (const [name, value] of Object.entries(stage.metrics)) {
          const known = value && typeof value.value === "number" && Number.isFinite(value.value) && value.value >= 0 && value.status !== "unknown";
          add(measurements, "p", name + ": " + (known ? value.value : w.unknown) + " · " + (value?.unit || w.unknown) + " · " + (value?.status || w.unknown), true);
        }
        const details = add(area, "details", ""); add(details, "summary", w.records);
        add(details, "pre", JSON.stringify({input: stage.input, artifacts: stage.artifacts, attempts: stage.attempts, pending_questions: stage.pending_questions, approvals: stage.approvals, assessment: stage.assessment}, null, 2), true);
      }
      if (number >= 3) {
        const operations = document.getElementById("project-stage-" + number + "-operations");
        let placeholder = document.getElementById("project-stage-" + number + "-unconnected");
        if (operations && !placeholder) {placeholder = add(operations, "button", ""); placeholder.id = "project-stage-" + number + "-unconnected"; placeholder.type = "button"; placeholder.disabled = true;}
        if (placeholder) placeholder.textContent = w.action;
      }
      const result = document.getElementById("project-stage-" + number + "-result-state");
      if (result) {
        result.replaceChildren();
        const configured = window.RESEARCH_PROJECTS?.stage2_selection_projects;
        if (number === 2 && valid && Array.isArray(configured) && configured.includes(current.project_ref)) {
          add(result, "p", w.selectionIntro);
          const link = add(result, "a", w.selectionEntry);
          link.href = "/project-stage2-selection.html#" + encodeURIComponent(current.project_ref);
        } else if (number === 3 && valid && window.RESEARCH_PROJECTS?.stage3_planning_projects?.includes(current.project_ref)) {
          add(result, "p", w.planningIntro);
          const link = add(result, "a", w.planningEntry);
          link.href = "/project-stage3-planning.html#" + encodeURIComponent(current.project_ref);
        } else {add(result, "p", w.empty); add(result, "p", number === 2 ? w.stage2Missing : w.future);}
      }
    }
    showStage(active);
  }
  function clear(options = {}) {render({project: null, contract: null, language: options.language || language, loading: Boolean(options.loading)});}
  window.ResearchProjectStages = Object.freeze({render, showStage, activeStage: () => active, clear});
  document.addEventListener("project-screening-clear", () => clear());
  clear();
}());
