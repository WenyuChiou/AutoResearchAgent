(() => {
  "use strict";
  const root = document.getElementById("stage2-workbench");
  if (!root) return;
  const payload = root.querySelector("[data-s2w-view]");
  let view;
  try { view = JSON.parse(payload.textContent); } catch (_) { return; }
  const tabs = [...root.querySelectorAll('[role="tab"]')];
  const panels = [...root.querySelectorAll('[role="tabpanel"]')];
  function activate(tab) {
    tabs.forEach(item => item.setAttribute("aria-selected", String(item === tab)));
    panels.forEach(panel => { panel.hidden = panel.id !== tab.getAttribute("aria-controls"); });
  }
  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => activate(tab));
    tab.addEventListener("keydown", event => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      let next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 :
        (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
      tabs[next].focus(); activate(tabs[next]);
    });
  });

  const literature = new Map((view.literature || []).map(row => [String(row.key), row]));
  const rows = [...root.querySelectorAll("[data-s2w-literature-row]")];
  const search = root.querySelector("[data-s2w-search]");
  const count = root.querySelector("[data-s2w-count]");
  function searchable(row) {
    const values = [row.title, row.authors, row.year, row.roles, row.evidence_level];
    Object.values(row.cells || {}).forEach(cell => values.push(cell?.text));
    return values.map(value => typeof value === "string" ? value : JSON.stringify(value ?? "")).join("\n");
  }
  function filter() {
    const query = search.value.toLocaleLowerCase();
    let visible = 0;
    rows.forEach(element => {
      const match = searchable(literature.get(element.dataset.key) || {}).toLocaleLowerCase().includes(query);
      element.hidden = !match; if (match) visible += 1;
    });
    const selected = rows.filter(row => row.querySelector("[data-s2w-select]").checked).length;
    count.textContent = `${visible} of ${rows.length} papers shown · ${selected} selected`;
  }
  search.addEventListener("input", filter);
  rows.forEach(row => row.querySelector("[data-s2w-select]").addEventListener("change", filter)); filter();

  const fieldLabels = [
    ["question", "Recorded question / rationale"], ["data", "Data"],
    ["geography", "Research region"], ["population", "Population / object"],
    ["concepts", "Recorded topic / concepts"],
    ["method", "Method"], ["findings", "Findings"],
    ["validation", "Validation"], ["limitations", "Limitations"],
    ["relevance", "Relevance"]
  ];
  const mode = root.querySelector("[data-s2w-mode]");
  const visibleFields = {
    overview: ["question", "geography", "population", "data", "findings"],
    concepts: ["concepts", "question", "method", "validation", "limitations"]
  };
  function tableMode() {
    root.querySelector(".s2w-literature").dataset.mode = mode.value;
    root.querySelectorAll("[data-s2w-field]").forEach(cell => {
      cell.hidden = mode.value !== "detail" && !visibleFields[mode.value].includes(cell.dataset.s2wField);
    });
  }
  mode.addEventListener("change", tableMode); tableMode();
  const comparison = root.querySelector("[data-s2w-comparison]");
  function addText(parent, tag, value, className) {
    const element = document.createElement(tag); element.textContent = value == null ? "Unknown" :
      typeof value === "string" ? value : JSON.stringify(value, null, 2);
    if (className) element.className = className; parent.append(element); return element;
  }
  function compactCell(cell, value) {
    const text = value == null ? "Unknown" : typeof value === "string" ? value : JSON.stringify(value, null, 2);
    if (text.length <= 180) { addText(cell, "span", text); return; }
    const details = document.createElement("details"); details.className = "s2w-preview";
    addText(details, "summary", text.slice(0, 180).trimEnd() + "…");
    addText(details, "div", text, "s2w-full"); cell.append(details);
  }
  function compareSelected() {
    const selected = rows.filter(row => row.querySelector("[data-s2w-select]").checked)
      .map(row => literature.get(row.dataset.key)).filter(Boolean);
    comparison.replaceChildren(); comparison.hidden = false;
    addText(comparison, "h3", "Selected paper comparison");
    if (!selected.length) { addText(comparison, "p", "Select any papers to compare. No fixed count is required."); return; }
    const scroll = document.createElement("div"); scroll.className = "s2w-table-scroll"; scroll.tabIndex = 0;
    scroll.setAttribute("aria-label", "Scrollable selected paper comparison");
    const table = document.createElement("table"); table.className = "s2w-table s2w-transpose";
    const head = document.createElement("thead"), headRow = document.createElement("tr");
    addText(headRow, "th", "Recorded field").scope = "col";
    selected.forEach(row => { const cell = addText(headRow, "th", row.title); cell.scope = "col"; });
    head.append(headRow); table.append(head);
    const body = document.createElement("tbody");
    fieldLabels.forEach(([name, label]) => {
      const tr = document.createElement("tr"); const heading = addText(tr, "th", label); heading.scope = "row";
      selected.forEach(row => { const cell = document.createElement("td"); const recorded = row.cells?.[name] ?? (name === "question" ? row.cells?.rationale : undefined); compactCell(cell, recorded?.text); tr.append(cell); });
      body.append(tr);
    });
    table.append(body); scroll.append(table); comparison.append(scroll); comparison.scrollIntoView({block: "nearest"});
  }
  root.querySelector("[data-s2w-compare]").addEventListener("click", compareSelected);
  root.querySelector("[data-s2w-clear]").addEventListener("click", () => {
    rows.forEach(row => { row.querySelector("[data-s2w-select]").checked = false; });
    comparison.replaceChildren(); comparison.hidden = true; filter();
  });
})();
