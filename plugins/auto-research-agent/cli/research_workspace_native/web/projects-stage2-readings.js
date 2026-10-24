/* Independent saved reports are reading links, never project selection grants. */
(function () {
  "use strict";
  const words = {
    en: ["Independent Stage 2 reports", "These reports are not linked to this project's Stage 1 run. Open a report to read directions, materials and review comments. This does not select a research direction."],
    "zh-Hans": ["独立保存的 Stage 2 报告", "这些报告未关联到当前项目的 Stage 1。可阅读方向、材料与评语；打开报告不代表选案。"],
    "zh-Hant": ["獨立保存的 Stage 2 報告", "這些報告未關聯至目前專案的 Stage 1。可閱讀方向、材料與評語；開啟報告不代表選案。"]
  };
  const valid = row => row && row.kind === "Stage2ReadingReference" && row.schema_version === "1.0.0"
    && typeof row.ref === "string" && /^[A-Za-z0-9_-]{1,64}$/.test(row.ref)
    && typeof row.label === "string" && row.label.length > 0 && row.label.length <= 320
    && row.url === "/project-stage2-readings/" + row.ref + "/index.html"
    && /^[0-9a-f]{64}$/.test(row.binding_sha256 || "") && /^[0-9a-f]{64}$/.test(row.delivery_manifest_sha256 || "")
    && row.source_kind === "independent-saved-stage2" && row.reading_only === true
    && row.stage1_lineage_attested === false && row.selection_authority === false && row.execution_authorized === false;
  function render() {
    const area = document.getElementById("project-stage-2-result-state");
    if (!area) return;
    let box = document.getElementById("project-stage2-independent-readings");
    if (!box) { box = document.createElement("section"); box.id = "project-stage2-independent-readings"; area.append(box); }
    box.replaceChildren(); box.hidden = true;
    const rows = window.RESEARCH_PROJECTS?.stage2_readings;
    if (!Array.isArray(rows) || rows.length < 1 || rows.length > 8 || !rows.every(valid) || new Set(rows.map(row => row.ref)).size !== rows.length) return;
    const copy = words[document.getElementById("language")?.value] || words.en;
    for (const [tag, text] of [["h3", copy[0]], ["p", copy[1]]]) { const node = document.createElement(tag); node.textContent = text; box.append(node); }
    for (const row of rows) { const link = document.createElement("a"); link.textContent = row.label; link.href = row.url; link.setAttribute("translate", "no"); const p = document.createElement("p"); p.append(link); box.append(p); }
    box.hidden = false;
  }
  window.addEventListener("research-project-stage", event => { if (event.detail?.stage === 2) render(); });
  render();
}());
