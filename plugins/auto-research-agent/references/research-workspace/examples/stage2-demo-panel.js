/* Demo-only Stage2 worker: fixed server case, explicit one-shot POST, reads never run. */
(() => {
  "use strict";
  const host = window.WORKSPACE_HOST;
  if (!host?.credential || host.current_case !== "stage2") return;
  const api = "/api/stage2-demo/stage2";
  const lang = () => document.documentElement.lang;
  const text = (en, hans, hant) => lang() === "zh-Hans" ? hans : lang() === "zh-Hant" ? hant : en;
  const content = document.getElementById("atlas-content");
  if (!content) return;
  const panel = document.createElement("section");
  panel.id = "stage2-repository-demo";
  panel.className = "atlas-card stage-actions-panel";
  const title = document.createElement("h2"), boundary = document.createElement("p");
  const confirmLabel = document.createElement("label"), confirm = document.createElement("input");
  confirm.type = "checkbox";
  const confirmation = document.createElement("span");
  confirmLabel.append(confirm, confirmation);
  const controls = document.createElement("div"), run = document.createElement("button");
  const refresh = document.createElement("button"), report = document.createElement("button");
  controls.className = "stage-actions-controls";
  for (const button of [run, refresh, report]) button.type = "button";
  controls.append(run, refresh, report);
  const status = document.createElement("p"), result = document.createElement("div");
  status.setAttribute("role", "status");
  panel.append(title, boundary, confirmLabel, controls, status, result);
  let saved = null, busy = true, lost = false, previousStage = null;

  function render() {
    const stage = document.documentElement.dataset.atlasStage;
    if (previousStage !== null && previousStage !== stage) confirm.checked = false;
    previousStage = stage;
    panel.hidden = stage !== "2";
    title.textContent = text("Run the repository Stage 2 case", "运行仓库 Stage 2 案例", "執行倉庫 Stage 2 案例");
    boundary.textContent = text(
      "Engineering demo: the real Stage 2 controller writes a new workflow, review records and delivery using the fixed SyntheticAdapter. This legacy packet fixture is independent of Stage 1; it does not run daily_v3, Codex, models, searches or scoring. The old view above remains a separate saved example.",
      "工程演示：实际 Stage 2 controller 通过固定 SyntheticAdapter 新建工作流、审阅记录和交付。该旧版 packet 测试案例独立于 Stage 1，不执行 daily_v3、Codex、模型、搜索或评分。上方视图仍是另一个独立保存案例。",
      "工程演示：實際 Stage 2 controller 透過固定 SyntheticAdapter 新建工作流、審閱紀錄與交付。此舊版 packet 測試案例獨立於 Stage 1，不執行 daily_v3、Codex、模型、搜尋或評分。上方視圖仍是另一個獨立儲存案例。");
    confirmation.textContent = text("I understand this is a synthetic repository demo", "我确认这是仓库的模拟工程案例", "我確認這是倉庫的模擬工程案例");
    run.textContent = text("Run repository Stage 2 demo", "运行仓库 Stage 2 演示", "執行倉庫 Stage 2 演示");
    refresh.textContent = text("Read run history", "读取运行记录", "讀取執行紀錄");
    report.textContent = text("Download the new delivery report", "下载本次新交付报告", "下載本次新交付報告");
    const row = saved?.action;
    run.disabled = panel.hidden || busy || lost || !saved || !!row || !confirm.checked;
    refresh.disabled = busy;
    confirm.disabled = busy || !!row;
    report.disabled = busy || row?.outcome !== "succeeded";
    status.textContent = busy ? text("Reading / running…", "正在读取／运行…", "正在讀取／執行…") :
      lost ? text("Response unverified. Read history; do not resend.", "回执尚未核验，请读取历史，不要重发。", "回執尚未核驗，請讀取歷史，不要重發。") :
      !row ? text("No run yet. The button creates new output once.", "尚未运行。按钮只新建一次输出。", "尚未執行。按鈕只新建一次輸出。") :
      row.status === "execution-unknown" ? text("Outcome unknown; output and intent are retained. No automatic rerun.", "结果未知，已保留输出与意图，不自动重跑。", "結果未知，已保留輸出與意圖，不自動重跑。") :
      row.outcome === "failed" ? text("Worker failed. This failure is saved; no automatic retry.", "执行失败，已保留失败记录，不自动重试。", "執行失敗，已保留失敗紀錄，不自動重試。") :
      row.outcome === "succeeded" ? text("Synthetic pipeline finished. Delivery still needs content and independent assessment; the stage is not complete.", "模拟工作流已产出交付，但内容与独立评估仍有缺口，本阶段尚未完成。", "模擬工作流已產出交付，但內容與獨立評估仍有缺口，本階段尚未完成。") : row.status;
    result.replaceChildren();
    if (!row) return;
    const actual = row.result;
    if (actual) {
      const list = document.createElement("ol");
      const stages = actual.adapter_calls ?? [];
      for (const call of stages) {
        const li = document.createElement("li");
        const names = {
          research: text("Research proposal saved", "研究提案已保存", "研究提案已儲存"),
          extract: text("Structured packet extracted", "结构化 packet 已提取", "結構化 packet 已擷取"),
          "review:challenger": text("Independent challenger fixture reviewed", "独立质疑者测试审阅已完成", "獨立質疑者測試審閱已完成"),
          "review:feasibility": text("Independent feasibility fixture reviewed", "独立可行性测试审阅已完成", "獨立可行性測試審閱已完成"),
          resolve: text("Review synthesis and new delivery saved", "审阅综合与新交付已保存", "審閱綜合與新交付已儲存"),
        };
        li.textContent = names[call] ?? call;
        list.append(li);
      }
      const note = document.createElement("p");
      note.textContent = text("Human selection: pending. Stage 3 execution: disabled. Formal / scientific acceptance: false. Missing topic matrix and external assessment are retained.",
        "人工选择：待确认；Stage 3 执行：未授权；正式／科学验收：未通过。缺失的 topic matrix 与外部评估保持为缺口。",
        "人工選擇：待確認；Stage 3 執行：未授權；正式／科學驗收：未通過。缺失的 topic matrix 與外部評估保持為缺口。");
      result.append(list, note);
    }
    const details = document.createElement("details"), summary = document.createElement("summary");
    summary.textContent = text("Source, versions and saved receipt", "来源、版本与保存回执", "來源、版本與儲存回執");
    const code = document.createElement("pre");
    code.textContent = JSON.stringify(row, null, 2);
    details.append(summary, code);
    result.append(details);
  }

  async function fetchJson(path = api, options = {}) {
    const response = await fetch(path, {
      credentials: "omit", cache: "no-store", mode: "same-origin", redirect: "error",
      headers: {Authorization: "Bearer " + host.credential, "Content-Type": "application/json"}, ...options,
    });
    const value = await response.json();
    if (!response.ok) throw new Error(value.error ?? "demo-response-rejected");
    return value;
  }

  async function readHistory() {
    busy = true; render();
    try { saved = await fetchJson(); lost = false; }
    catch { lost = true; }
    finally { busy = false; render(); }
  }
  run.addEventListener("click", async () => {
    if (run.disabled || !saved || saved.action) return;
    busy = true; render();
    try {
      saved = await fetchJson(api, {method: "POST", body: JSON.stringify({
        key: saved.key, case_sha256: saved.case_sha256, index_sha256: saved.index_sha256, confirmed: true,
      })});
      lost = false;
    } catch { lost = true; }
    finally { busy = false; render(); }
  });
  refresh.addEventListener("click", readHistory);
  confirm.addEventListener("change", render);
  report.addEventListener("click", async () => {
    if (report.disabled) return;
    busy = true; render();
    try {
      const value = await fetchJson(api + "/report");
      const url = URL.createObjectURL(new Blob([value.html], {type: "text/html;charset=utf-8"}));
      const anchor = document.createElement("a");
      anchor.href = url; anchor.download = "stage2-synthetic-new-delivery.html";
      anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch { lost = true; }
    finally { busy = false; render(); }
  });
  function attach() { if (!panel.isConnected) content.append(panel); }
  new MutationObserver(attach).observe(content, {childList: true});
  new MutationObserver(render).observe(document.documentElement, {attributes: true, attributeFilter: ["lang", "data-atlas-stage"]});
  attach(); render(); readHistory(); // GET only; never run when the page opens.
})();
