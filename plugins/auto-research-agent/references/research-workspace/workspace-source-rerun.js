/* Optional v3 saved-source rerun presentation. Research values are never translated. */
(() => {
  "use strict";
  const index = window.WORKSPACE_VIEW?.index;
  const overlay = index?.source_rerun;
  if (!overlay?.data || !Array.isArray(overlay.data.rows)) return;
  const data = overlay.data;
  const key = value => `${value.work_id}\u0000${value.version_id}`;
  const rows = new Map();
  data.rows.forEach(value => { if (!rows.has(key(value))) rows.set(key(value), value); });
  const recorded = value => value !== null && value !== undefined && value !== "";
  const text = value => recorded(value) ? (typeof value === "object" ? JSON.stringify(value, null, 2) : String(value)) : "Not recorded";
  const element = (tag, value, cls) => { const node = document.createElement(tag); if (value !== undefined) node.textContent = value; if (cls) node.className = cls; return node; };
  const source = (tag, value, cls) => { const node = element(tag, text(value), cls); node.translate = false; return node; };
  const disclosure = (root, label, value) => { const box = element("details", undefined, "rerun-disclosure"); box.append(element("summary", label), source("pre", value)); root.append(box); };
  const field = (root, label, value) => { const item = element("div", undefined, "rerun-field"); item.append(element("dt", label), source("dd", value)); root.append(item); };
  function row(paper) { return rows.get(key(paper)); }
  function outcome(root, result, compact) {
    const reading = result.reading || {}, block = element("section", undefined, compact ? "rerun-note" : "rerun-card");
    if (!compact) block.append(source("h3", result.work_id), source("p", `${result.version_id} · ${result.source_id}`, "rerun-identity"));
    const states = element("dl", undefined, "rerun-states");
    field(states, "Current read", `${text(reading.status)} · ${text(reading.evidence_level)}`);
    field(states, "Original state", `${text(result.previous_status)} · ${text(result.previous_evidence_level)}`);
    field(states, "Identity", reading.identity_status);
    field(states, "Extracted text", recorded(reading.characters) ? `${reading.characters} characters · SHA-256 ${text(reading.text_sha256)}` : null);
    block.append(states);
    const metadata = element("dl", undefined, "rerun-metadata");
    for (const [name, label] of [["journal","Journal"],["volume","Volume"],["issue","Issue"],["pages","Pages"],["doi","DOI"]]) field(metadata, label, result.metadata?.[name]);
    block.append(element("h4", "Rerun metadata"), metadata);
    const provenance = {};
    for (const [name, value] of Object.entries(result.metadata || {})) if (recorded(value)) provenance[name] = result.metadata_provenance?.[name] ?? "Not recorded";
    disclosure(block, "Metadata provenance", provenance);
    disclosure(block, "Locators and recorded geometry", reading.locators);
    disclosure(block, "Diagnostics and errors", {diagnostics:reading.diagnostics ?? null, error:reading.error ?? null, attempt_id:result.attempt_id ?? null});
    const caveat = element("details", undefined, "rerun-disclosure");
    caveat.append(element("summary", "Layout fidelity caveat"), element("p", "Saved text, locators, and recorded geometry do not establish the default page layout or visual fidelity of the original source."));
    block.append(caveat); root.append(block);
  }
  function note(root, paper) { const result = row(paper); if (result) outcome(root, result, true); }
  function render(root) {
    const page = element("div", undefined, "source-rerun");
    const intro = element("section", undefined, "rerun-intro");
    intro.append(element("p", "STAGE 1 · SAVED SOURCE RERUN", "rerun-eyebrow"), element("h2", "Saved-source rerun"), element("p", "A bounded offline reread of saved sources. Current read results are shown separately from the original package state; historical claims and scientific judgments are unchanged. Paper details use the first canonical source; every source outcome is retained below.", "rerun-lede"));
    const metrics = element("dl", undefined, "rerun-metrics");
    for (const [label, value] of [["Rerun rows", data.rows.length],["Research execution", data.research_execution],["Scientific judgments changed", data.scientific_judgments_changed],["Official Stage 2 import eligible", data.official_stage2_import_eligible]]) field(metrics, label, value);
    intro.append(metrics);
    disclosure(intro, "Manifest and runtime binding", {manifest_sha256:overlay.manifest_sha256, base_index_sha256:data.base_index_sha256, parser_runtime:data.parser_runtime, kind:data.kind, schema_version:data.schema_version});
    page.append(intro);
    const list = element("section", undefined, "rerun-list"); list.append(element("h3", "Read outcomes")); data.rows.forEach(value => outcome(list, value, false)); page.append(list);
    const downloads = element("nav", undefined, "rerun-downloads"); downloads.setAttribute("aria-label", "Saved-source rerun downloads");
    for (const [path, label] of [["source-rerun/catalog.xlsx","Catalog (Excel)"],["source-rerun/report.md","Rerun report (Markdown)"],["source-rerun/references.bib","References (BibTeX)"]]) { const link = element("a", label); link.href = `./${path}`; link.download = path.split("/").pop(); downloads.append(link); }
    page.append(downloads); root.append(page);
  }
  window.WorkspaceSourceRerun = Object.freeze({render, note, row});
})();
