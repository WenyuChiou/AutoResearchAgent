/* Additive controls only. Atlas selection, graph and source records stay intact. */
(function () {
  "use strict";
  if (document.body.classList.contains("project-embedded")) {
    document.addEventListener("click", event => {
      const link = event.target.closest?.("a[href]");
      if (!link || !link.closest(".studio-nav")) return;
      const url = new URL(link.href, location.href);
      if (url.origin !== location.origin || url.search || url.hash
          || !(url.pathname === "/" || /^\/views\/[A-Za-z0-9_-]{1,64}\/atlas\.html$/.test(url.pathname))) return;
      // Saved views cannot be framed; user navigation leaves the operation
      // frame. This does not change the project's bound saved-data popup.
      event.preventDefault(); window.top.location.assign(url.href);
    });
    return;
  }
  const language = document.getElementById("atlas-language");
  const words = {
    en: ["Codex & Harness", "Research operations", "Close operations", "Select the project explicitly below. The saved Atlas stays unchanged; opening this panel does not run research."],
    "zh-Hans": ["Codex 与 Harness", "研究操作", "关闭操作面板", "请在下方明确选择项目。已保存图谱保持不变；打开面板不会执行研究。"],
    "zh-Hant": ["Codex 與 Harness", "研究操作", "關閉操作面板", "請在下方明確選擇專案。已保存圖譜保持不變；開啟面板不會執行研究。"]
  };
  const button = document.createElement("button"), dialog = document.createElement("dialog");
  button.type = "button"; button.id = "project-operations-open";
  button.setAttribute("aria-haspopup", "dialog"); button.setAttribute("aria-controls", "project-operations-dialog");
  dialog.id = "project-operations-dialog"; dialog.setAttribute("aria-labelledby", "project-operations-title");
  const header = document.createElement("header"), title = document.createElement("h2"), close = document.createElement("button"), hint = document.createElement("p");
  title.id = "project-operations-title"; close.type = "button"; close.id = "project-operations-close";
  header.append(title, close); dialog.append(header, hint); document.body.append(dialog);
  const controls = document.querySelector(".atlas-topbar-controls");
  if (!controls) { dialog.remove(); return; }
  controls.prepend(button);
  let frame = null;
  function translate() {
    const w = words[language?.value] || words.en;
    [button.textContent, title.textContent, close.textContent, hint.textContent] = w;
    if (frame) frame.title = w[1];
    // Only the existing same-origin selector is changed. No credential, source
    // binding, action key or message is copied across this presentation seam.
    const select = frame?.contentDocument?.getElementById("language");
    if (select && select.value !== language.value) {
      select.value = language.value; select.dispatchEvent(new Event("change"));
    }
  }
  button.onclick = () => {
    if (!frame) {
      frame = document.createElement("iframe"); frame.id = "project-operations-frame";
      frame.src = "/projects-panel.html"; frame.onload = translate; dialog.append(frame);
    }
    translate(); dialog.showModal(); close.focus();
  };
  close.onclick = () => dialog.close();
  dialog.addEventListener("close", () => button.focus());
  language?.addEventListener("change", translate);
  translate();
}());
