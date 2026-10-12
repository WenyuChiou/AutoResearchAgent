/* Existing pinned fixture views stay references, never current-project delivery. */
(function () {
  "use strict";
  const bootstrap = window.RESEARCH_PROJECTS || {}, hash = value => /^[a-f0-9]{64}$/.test(value || "");
  const words = {
    en: ["Stage2 interface example", "Example only · not this project's delivered result. Comparison, directions and candidates below come from a registered synthetic package; viewing does not run research.", "No registered Stage2 example is available on this server.", "Reading the saved example…", "The saved example was refused or could not be read."],
    "zh-Hans": ["Stage2 界面示例", "仅为示例，不是当前项目的交付结果。下方比较、方向和候选路线来自已登记的模拟包；查看不会运行研究。", "此服务尚未登记 Stage2 示例包。", "正在读取已保存的示例…", "示例被拒绝或无法读取。"],
    "zh-Hant": ["Stage2 介面示例", "僅為示例，並非目前專案的交付結果。下方比較、方向及候選路線來自已登記的模擬包；檢視不會執行研究。", "此服務尚未登記 Stage2 示例包。", "正在讀取已保存的示例…", "示例被拒絕或無法讀取。"]
  };
  let generation = 0, binding = null, frame = null, observer = null, resize = null, selected = null;
  const examples = Array.isArray(bootstrap.stage2_examples) && bootstrap.stage2_examples.length <= 40 ? bootstrap.stage2_examples.filter(row => row && row.fixture === true && /^[A-Za-z0-9_-]{1,64}$/.test(row.ref || "") && row.url === "/project-stage2-examples/" + row.ref + "/atlas.html" && ["index_sha256", "manifest_sha256", "payload_sha256"].every(key => hash(row[key])) && typeof row.project_id === "string" && row.project_id.length > 0 && row.project_id.length <= 128) : [];
  const language = () => Object.hasOwn(words, document.getElementById("language")?.value) ? document.getElementById("language").value : "en";
  const mount = () => document.getElementById("stage2-preview-entry");
  function clear() {
    ++generation; observer?.disconnect(); resize?.disconnect(); observer = resize = null;
    frame?.remove(); frame = null; mount()?.replaceChildren();
  }
  function childLanguage() {
    if (!frame?.contentDocument) return;
    const control = frame.contentDocument.getElementById("atlas-language");
    if (control && control.value !== language()) { control.value = language(); control.dispatchEvent(new Event("change")); }
  }
  function render() {
    const area = mount(); if (!area) return;
    const w = words[language()];
    if (frame) { area.querySelector("h3").textContent = w[0]; area.querySelector("p").textContent = w[1]; childLanguage(); return; }
    area.replaceChildren();
    const title = document.createElement("h3"), warning = document.createElement("p");
    title.textContent = w[0]; warning.textContent = w[1]; warning.className = "subtle"; area.append(title, warning);
    if (!examples.length) { const missing = document.createElement("p"); missing.textContent = w[2]; area.append(missing); return; }
    const choice = document.createElement("select"); choice.setAttribute("aria-label", w[0]);
    for (const row of examples) { const option = document.createElement("option"); option.value = row.ref; option.textContent = row.label; option.setAttribute("translate", "no"); choice.append(option); }
    selected = examples.some(row => row.ref === selected) ? selected : examples[0].ref;
    choice.value = selected; area.append(choice);
    const notice = document.createElement("p"); notice.setAttribute("role", "status"); notice.textContent = w[3]; area.append(notice);
    choice.onchange = () => { selected = choice.value; clear(); render(); };
    const row = examples.find(item => item.ref === selected), own = generation;
    const child = document.createElement("iframe"); frame = child; child.id = "stage2-preview-frame"; child.title = w[0]; child.referrerPolicy = "no-referrer";
    child.style.cssText = "width:100%;height:700px;border:0;display:block;margin-top:16px";
    child.onload = async () => {
      try {
        if (child.contentDocument?.URL === "about:blank") return;
        const response = await fetch(row.url.replace(/atlas\.html$/, "atlas-data.js"), {method: "GET", credentials: "omit", redirect: "error"});
        if (!response.ok) throw Error("example read refused");
        const bytes = await response.arrayBuffer(); if (bytes.byteLength > 32 * 1024 * 1024) throw Error("example size differs");
        const actual = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))).map(value => value.toString(16).padStart(2, "0")).join("");
        if (actual !== row.payload_sha256) throw Error("example bytes differ");
        const raw = new TextDecoder("utf-8", {fatal: true}).decode(bytes), prefix = "window.WORKSPACE_VIEW = ";
        if (!raw.startsWith(prefix) || !raw.endsWith(";\n")) throw Error("example format differs");
        const payload = JSON.parse(raw.slice(prefix.length, -2));
        if (payload.fixture !== true || payload.stage2?.fixture !== true || payload.index_sha256 !== row.index_sha256 || payload.index?.project_id !== row.project_id || !payload.stage2_comparison) throw Error("example binding differs");
        if (own !== generation || frame !== child) return;
        const doc = child.contentDocument, view = child.contentWindow.WORKSPACE_VIEW;
        if (!view) throw Error("rendered example unavailable");
        if (view.index_sha256 !== row.index_sha256) throw Error("rendered example index differs");
        if (view.fixture !== true || view.stage2?.fixture !== true) throw Error("rendered example fixture differs");
        const style = doc.createElement("style");
        style.textContent = "body{margin:0;min-height:0}.atlas-shell{display:block;min-height:0}.atlas-sidebar,.atlas-topbar,#atlas-stage-review,.atlas-stage-review{display:none!important}#atlas-content{padding:12px 0;max-width:none}";
        doc.head.append(style);
        doc.querySelector("#atlas-stages button:nth-child(2)")?.click();
        childLanguage(); notice.textContent = "";
        const fit = () => { if (own !== generation || frame !== child) return; child.style.height = Math.min(30000, Math.max(260, Math.ceil(doc.body.getBoundingClientRect().height))) + "px"; document.dispatchEvent(new Event("project-atlas-layout")); };
        if (typeof MutationObserver === "function") { observer = new MutationObserver(fit); observer.observe(doc.body, {childList: true, subtree: true}); }
        if (typeof ResizeObserver === "function") { resize = new ResizeObserver(fit); resize.observe(doc.body); }
        fit();
      } catch (error) {
        if (own !== generation || frame !== child) return;
        observer?.disconnect(); resize?.disconnect(); child.remove(); frame = null; notice.textContent = words[language()][4];
        notice.dataset.refusal = String(error?.message || "example unavailable").slice(0,160);
      }
    };
    area.append(child); child.src = row.url;
  }
  window.addEventListener("research-project-stage", event => {
    const item = event.detail;
    if (!item || !/^[A-Za-z0-9_-]{1,64}$/.test(item.project_ref || "") || !Number.isSafeInteger(item.input_version) || item.input_version < 1 || !Number.isSafeInteger(item.revision) || item.revision < 0 || !hash(item.brief_sha256)) return;
    const key = [item.project_ref, item.input_version, item.revision, item.brief_sha256].join("/");
    if (key !== binding) { clear(); binding = key; }
    if (item.stage === 2) render();
  });
  document.addEventListener("project-screening-clear", () => { clear(); binding = null; });
  window.addEventListener("pagehide", clear);
}());
