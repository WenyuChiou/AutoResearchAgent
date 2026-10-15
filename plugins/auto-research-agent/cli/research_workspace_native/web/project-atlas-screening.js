/* Read-only canonical 1.2 ledger presenter. No transport or execution authority. */
(function () {
  "use strict";
  const words = {
    title: ["Discovery and screening history", "发现与筛选记录", "發現與篩選紀錄"],
    unavailable: ["This saved ledger cannot be matched to the selected paper version. Reopen the view from the project workspace.", "保存记录无法绑定到当前论文版本，请从项目工作台重新打开视图。", "保存紀錄無法綁定目前論文版本，請從專案工作台重新開啟視圖。"],
    scope: ["Counts cover this work across its saved versions. Selected-version source admission and reading evidence are separate.", "次数涵盖本作品的已保存版本；当前版本的来源审阅和阅读证据另行记录。", "次數涵蓋本作品的已保存版本；目前版本的來源審閱與閱讀證據另行記錄。"],
    discoveries: ["Recorded discoveries", "发现次数", "發現次數"],
    queries: ["Distinct queries", "不同查询数", "不同查詢數"],
    producers: ["Backend attempts producing this work", "发现本作品的后端尝试数", "發現本作品的後端嘗試數"],
    attempts: ["All backend attempts in those queries", "对应查询的全部后端尝试数", "對應查詢的全部後端嘗試數"],
    rounds: ["Recorded coverage rounds", "已记录覆盖轮次", "已記錄覆蓋輪次"],
    first: ["First discovery order in this run", "本次运行首次发现次序", "本次執行首次發現次序"],
    screening: ["Saved screening decision", "已保存筛选决定", "已保存篩選決定"],
    admission: ["Selected-source admission", "当前版本来源审阅状态", "目前版本來源審閱狀態"],
    reason: ["Reason", "理由", "理由"],
    rationale: ["Recorded rationale", "记录的具体依据", "紀錄的具體依據"],
    relevance: ["Relevance assessment", "相关度评估", "相關度評估"],
    reading: ["Selected-version reading evidence", "当前版本阅读证据", "目前版本閱讀證據"],
    model: ["Model execution evidence", "模型执行证据", "模型執行證據"],
    body: ["Complete-body reading evidence", "全文阅读证据", "全文閱讀證據"],
    discoveryHistory: ["Discoveries and query positions", "发现记录与查询位置", "發現紀錄與查詢位置"],
    decisions: ["Decisions and reversals", "筛选决定与撤回历史", "篩選決定與撤回歷史"],
    sources: ["Source attempts and failures", "来源尝试与失败", "來源嘗試與失敗"],
    imports: ["Saved source imports", "已保存来源导入", "已保存來源匯入"],
    queryHistory: ["Query and backend history", "查询与后端历史", "查詢與後端歷史"],
    query: ["Query / backend attempt", "查询／后端尝试", "查詢／後端嘗試"],
    position: ["Position within query result", "查询结果内位置", "查詢結果內位置"],
    round: ["Coverage round", "覆盖轮次", "覆蓋輪次"],
    version: ["Recorded version", "记录版本", "紀錄版本"],
    time: ["Recorded at", "记录时间", "紀錄時間"],
    reversal: ["Reverses decision", "撤回的决定", "撤回的決定"],
    none: ["No saved records in this category.", "此类别没有已保存记录。", "此類別沒有已保存紀錄。"],
    previous: ["Previous", "上一页", "上一頁"], next: ["Next", "下一页", "下一頁"],
    raw: ["Original record", "原始记录", "原始紀錄"],
    binding: ["Work / version / snapshot binding", "作品／版本／快照绑定", "作品／版本／快照綁定"],
    noRank: ["Discovery order and result position are not relevance or quality rankings. Partial records and Unknown do not mean zero, rejection or Stage 1 acceptance.", "发现次序和结果位置不是相关度或质量排名。部分记录与 Unknown 不代表零、拒绝或 Stage 1 已验收。", "發現次序和結果位置不是相關度或品質排名。部分紀錄與 Unknown 不代表零、拒絕或 Stage 1 已驗收。"]
  };
  const rows = value => Array.isArray(value) ? value : [];
  const text = value => value === null || value === undefined || value === "" ? "Unknown" :
    typeof value === "object" ? JSON.stringify(value, null, 2) : String(value);
  function element(tag, value, className, source = false) {
    const node = document.createElement(tag);
    if (value !== undefined) node.textContent = text(value);
    if (className) node.className = className;
    if (source) { node.translate = false; node.setAttribute("translate", "no"); }
    return node;
  }
  function fields(parent, values) {
    const grid = element("dl", undefined, "atlas-ledger-grid");
    for (const [label, value] of values) {
      const cell = element("div"); cell.append(element("dt", label), element("dd", value, undefined, true)); grid.append(cell);
    }
    parent.append(grid);
  }
  function raw(parent, value, t) {
    const details = element("details"); details.append(element("summary", t("raw")), element("pre", value, undefined, true)); parent.append(details);
  }
  function history(parent, label, values, render, t) {
    const all = rows(values), details = element("details"), body = element("div"), controls = element("div", undefined, "atlas-actions");
    details.append(element("summary", `${label} · ${all.length}`), controls, body); parent.append(details);
    let page = 0;
    const previous = element("button", t("previous")), next = element("button", t("next")), count = element("span");
    previous.type = next.type = "button";
    previous.onclick = () => { page--; draw(); }; next.onclick = () => { page++; draw(); };
    controls.append(previous, count, next);
    function draw() {
      page = Math.max(0, Math.min(page, Math.max(0, Math.ceil(all.length / 6) - 1)));
      previous.disabled = page === 0; next.disabled = (page + 1) * 6 >= all.length;
      count.textContent = all.length ? `${page * 6 + 1}–${Math.min((page + 1) * 6, all.length)} / ${all.length}` : "0 / 0";
      body.replaceChildren();
      if (!all.length) body.append(element("p", t("none"), "atlas-small"));
      for (const row of all.slice(page * 6, page * 6 + 6)) {
        const card = element("article", undefined, "atlas-screening-record"); render(card, row); raw(card, row, t); body.append(card);
      }
    }
    draw();
  }
  function renderLedger(parent, paper, index, payload, language) {
    if (index.canonical_records_version !== "1.2.0") return false;
    const lang = language === "zh-Hans" ? 1 : language === "zh-Hant" ? 2 : 0, t = key => words[key][lang];
    const library = index.screening_library, matches = rows(library?.rows).filter(row => row.work_id === paper.work_id && row.selected_version_id === paper.version_id);
    if (library?.kind !== "Stage1ScreeningLibrary" || library.schema_version !== "1.0.0" || library.binding?.project_ref !== index.project_id || payload.index !== index || !/^[0-9a-f]{64}$/.test(payload.index_sha256 || "") || matches.length !== 1) {
      parent.append(element("p", t("unavailable"), "atlas-note")); return true;
    }
    const row = matches[0], counts = row.counts || {}, decision = row.current_decision;
    parent.append(element("h3", `${t("title")} · ${paper.work_id}`), element("p", t("scope"), "atlas-small"));
    fields(parent, [[t("discoveries"), counts.discoveries], [t("queries"), counts.distinct_queries],
      [t("producers"), counts.discovery_producing_backend_attempts], [t("attempts"), counts.query_backend_attempts],
      [t("rounds"), counts.round_ids_known === true ? counts.recorded_rounds : null], [t("first"), row.first_candidate_discovery_order_in_run],
      [t("screening"), row.screening_status], [t("admission"), paper.selection?.status],
      [t("reason"), decision?.reason], [t("rationale"), decision?.rationale], [t("relevance"), row.relevance?.score ?? row.relevance?.status],
      [t("reading"), row.reading?.status], [t("model"), row.reading?.model_execution], [t("body"), row.reading?.complete_body_reading]]);
    parent.append(element("p", t("noRank"), "atlas-note"));
    history(parent, t("discoveryHistory"), row.discoveries, (card, d) => {
      card.append(element("strong", d.discovery_id, undefined, true));
      fields(card, [[t("query"), `${text(d.query_id)} / ${text(d.attempt_id)}`], [t("position"), d.result_position],
        [t("round"), d.round_number], [t("version"), d.version_id], [t("time"), d.completion_created_at]]);
    }, t);
    history(parent, t("decisions"), row.decision_history, (card, d) => {
      card.append(element("strong", `${text(d.event_id)} · ${text(d.new_decision)}`, undefined, true));
      fields(card, [[t("reason"), d.reason], [t("rationale"), d.rationale], [t("reversal"), d.reverses_event_id]]);
    }, t);
    for (const [key, values] of [["sources", row.source_attempts], ["imports", row.source_imports], ["queryHistory", row.query_history]]) {
      history(parent, t(key), values, (card, value) => card.append(element("strong", `${text(value.started?.event_id)} · ${text(value.finished?.outcome ?? value.result?.outcome)}`, undefined, true)), t);
    }
    const identity = element("details"); identity.append(element("summary", t("binding")));
    raw(identity, {...library.binding, work_id: paper.work_id, version_id: paper.version_id, index_sha256: payload.index_sha256}, t); parent.append(identity);
    return true;
  }
  window.ProjectAtlasScreening = Object.freeze({renderLedger});
}());
