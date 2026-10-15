/* Explicit engineering example notice only: no native facade or process. */
(() => {
  "use strict";
  const messages = {
    en: "Synthetic backend example. Harness Ledger, runner, HTTP and SQLite run; Hub child and probe are injected. Codex, models and real searches are disabled. Stage 2 is an independent saved example.",
    "zh-Hans": "模拟后端工程案例：Harness 的 Ledger、runner、HTTP 和 SQLite 实际运行；Hub 子进程与探测由测试替身代替。未启动 Codex、模型或真实搜索。Stage 2 是独立的保存案例。",
    "zh-Hant": "模擬後端工程案例：Harness 的 Ledger、runner、HTTP 與 SQLite 實際執行；Hub 子程序與探測由測試替身代替。未啟動 Codex、模型或真實搜尋。Stage 2 是獨立的儲存案例。",
  };
  const notice = document.createElement("p");
  notice.id = "planned-query-fixture-notice";
  notice.className = "atlas-notice";
  notice.setAttribute("role", "note");
  const content = document.getElementById("atlas-content");
  const render = () => {
    notice.textContent = messages[document.documentElement.lang] ?? messages.en;
    if (content && content.firstChild !== notice) content.prepend(notice);
  };
  if (content) new MutationObserver(render).observe(content, {childList: true});
  new MutationObserver(render).observe(document.documentElement, {
    attributes: true, attributeFilter: ["lang"],
  });
  render();
})();
