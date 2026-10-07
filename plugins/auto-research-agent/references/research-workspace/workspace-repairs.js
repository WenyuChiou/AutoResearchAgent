/* Accepted private repair presentation. Opening this file cannot execute research. */
(() => {
  "use strict";
  const index = window.WORKSPACE_VIEW.index, overlay = index.supplement, data = overlay.data;
  const element = (tag, value, cls) => { const node = document.createElement(tag); if (value !== undefined) node.textContent = String(value); if (cls) node.className = cls; return node; };
  const source = (tag, value, cls) => { const node = element(tag, typeof value === "object" && value !== null ? JSON.stringify(value, null, 2) : value ?? "unknown", cls); node.translate = false; return node; };
  const detail = (root, label, value) => { const node = element("details", undefined, "repair-disclosure"); node.append(element("summary", label), source("pre", value)); root.append(node); return node; };
  const atomVersions = new Map(data.papers.map(row => [row.work_id, row.version_id]));
  const fields = ["source_finding", "interpretation", "hypotheses", "limitations", "stage2_implications", "open_items"];
  const caution = value => /unknown|partial|unresolved|fail|review.only|incomplete|blocked|pending/i.test(String(value));
  function assessments(rows) {
    const counts = new Map();
    rows.forEach(row => { const value = row.assessment ?? "unknown"; counts.set(value, (counts.get(value) || 0) + 1); });
    return Array.from(counts, ([value, count]) => `${value}: ${count}`).join(" · ");
  }
  function states(root, value, all = false) {
    const list = element("dl", undefined, "repair-states");
    function visit(current, path) {
      if (current !== null && typeof current === "object") { Object.entries(current).forEach(([key, item]) => visit(item, path ? `${path}.${key}` : key)); return; }
      const key = path.split(".").pop();
      if (!all && !/status|state|outcome|verdict|eligible|authorized|changed/i.test(key) && !caution(current)) return;
      list.append(source("dt", path), source("dd", current, caution(current) ? "repair-caution" : undefined));
    }
    visit(value, "");
    if (list.children.length) root.append(list);
  }
  function hint(root, text) {
    const box = element("details", undefined, "repair-hint");
    const summary = element("summary", "About these records"), tooltip = element("span", text, "repair-hint-tooltip");
    tooltip.setAttribute("aria-hidden", "true"); summary.append(tooltip);
    box.append(summary, element("p", text)); root.append(box);
  }
  function atom(root, row) {
    const card = element("section", undefined, "repair-atom note-card"); card.dataset.atomId = row.atom_id;
    const head = element("div", undefined, "repair-atom-head");
    head.append(source("h4", row.atom_id), source("span", row.assessment, `repair-badge${caution(row.assessment) ? " repair-caution" : ""}`));
    card.append(head, source("p", `${row.work_id} / ${atomVersions.get(row.work_id) ?? "unknown"} / ${row.parent_claim_id}`, "repair-lineage"), source("p", row.type ?? "unrecorded", "repair-kind"));
    if (row.text !== undefined) card.append(source("p", row.text, "repair-atom-text"));
    detail(card, "Source binding, limits and unresolved obligations", row); root.append(card);
  }
  function finding(root, row, compact = false) {
    const card = element("section", undefined, "repair-finding note-card"); card.dataset.findingId = row.finding_id;
    card.append(source("h4", row.title ?? row.finding_id), source("p", `${row.work_id} / ${atomVersions.get(row.work_id) ?? "unknown"}`, "repair-lineage"));
    if (row.source_finding !== undefined) card.append(source("p", row.source_finding, "repair-finding-preview"));
    states(card, Object.fromEntries(Object.entries(row).filter(([key]) => /^(assessment|status|state)$/.test(key))));
    const full = element("details", undefined, "repair-disclosure repair-finding-full"); full.append(element("summary", compact ? "Read accepted finding" : "Read full finding"));
    for (const key of fields) if (row[key] !== undefined) full.append(element("h5", key.replaceAll("_", " ")), source("p", row[key]));
    detail(full, "Exact quotations, locators and versions", row); card.append(full); root.append(card);
  }
  function groups(root, rows) {
    const grouped = new Map();
    rows.forEach(row => { if (!grouped.has(row.work_id)) grouped.set(row.work_id, []); grouped.get(row.work_id).push(row); });
    const list = element("div", undefined, "repair-atoms-groups");
    grouped.forEach((matching, work) => {
      const box = element("details", undefined, "repair-atoms-group"); box.dataset.repairWork = work;
      const summary = element("summary");
      summary.append(source("strong", `${work} / ${atomVersions.get(work) ?? "unknown"}`), element("span", `${matching.length} atomic revision entries`, "repair-group-count"), source("span", assessments(matching), "repair-group-states"));
      box.append(summary);
      const cards = element("div", undefined, "repair-atoms-list"); matching.forEach(row => atom(cards, row)); box.append(cards); list.append(box);
    });
    const controls = element("div", undefined, "repair-expand-controls");
    for (const [label, open] of [["Expand work groups", true], ["Collapse work groups", false]]) { const button = element("button", label, "repair-button"); button.type = "button"; button.onclick = () => list.querySelectorAll(".repair-atoms-group").forEach(box => {box.open = open;}); controls.append(button); }
    root.append(controls, list);
  }
  function note(root, paper) {
    if (atomVersions.get(paper.work_id) !== paper.version_id) return;
    const matching = data.atomic_revisions.filter(row => row.work_id === paper.work_id);
    const box = element("details", undefined, "repair-panel repair-disclosure"); box.dataset.repairWork = paper.work_id;
    const summary = element("summary", `Accepted repair supplement · ${matching.length} atomic revision entries`);
    summary.append(source("span", assessments(matching), "repair-group-states")); box.append(summary);
    const findings = element("div", undefined, "repair-findings-grid"); data.core_findings.filter(row => row.work_id === paper.work_id).forEach(row => finding(findings, row, true)); box.append(findings);
    const atoms = element("details", undefined, "repair-disclosure"); atoms.append(element("summary", "Original claim → atomic revisions")); matching.forEach(row => atom(atoms, row)); box.append(atoms);
    detail(box, "Supplement-wide reading states and obligations (not all attributed to this work)", {source_reading:data.source_reading, unresolved:data.unresolved}); root.append(box);
  }
  function graph(root) {
    const block = element("details", undefined, "repair-graph repair-disclosure");
    block.append(element("summary", `Claim revision graph · ${data.atomic_revisions.length} atomic revision links`));
    hint(block, "Links identify recorded revisions and source bindings. They do not assert new citation, similarity or scientific sufficiency.");
    const frame = element("div", undefined, "repair-graph-frame"); frame.tabIndex = 0; frame.setAttribute("role", "region"); frame.setAttribute("aria-label", "Claim revision graph, scroll to read all labels");
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", `0 0 960 ${80 + data.atomic_revisions.length * 32}`); svg.setAttribute("role", "img"); svg.setAttribute("aria-label", "Original claim to accepted atomic revision graph");
    data.atomic_revisions.forEach((row, pos) => {
      const y = 38 + pos * 32, line = document.createElementNS(svg.namespaceURI, "line");
      for (const [key, value] of Object.entries({x1:360,y1:y,x2:460,y2:y,stroke:"#667f96"})) line.setAttribute(key, value);
      svg.append(line);
      for (const [x, text] of [[12,row.parent_claim_id], [470,`${row.atom_id} · ${row.assessment}`]]) { const node = document.createElementNS(svg.namespaceURI, "text"); node.setAttribute("x", x); node.setAttribute("y", y + 5); node.setAttribute("font-size", "13"); node.textContent = text; node.translate = false; svg.append(node); }
    });
    frame.append(svg); block.append(frame); detail(block, "Typed relationships and provenance", overlay.edges); root.append(block);
  }
  function render(root) {
    const page = element("div", undefined, "repair-closeout");
    const overview = element("section", undefined, "repair-overview");
    overview.append(element("p", "Stage 1 · accepted repair supplement", "repair-eyebrow"), element("h2", "Accepted repairs & core findings"), element("p", "Assertion narrowing is separate from evidence resolution.", "repair-intro"));
    const counts = data.original_compound_counts, metrics = element("dl", undefined, "repair-metrics");
    for (const [label, value] of [["Distinct works", index.papers.length], ["Original canonical claims", index.claims.length], ["Atomic revision entries", data.atomic_revisions.length], ["Core findings", data.core_findings.length]]) {const item = element("div"); item.append(source("dd", value), element("dt", label)); metrics.append(item);} overview.append(metrics);
    overview.append(source("p", `Historical compound groups: ${counts.denominator} · ${counts.supported} supported / ${counts.partial} partial / ${counts.unknown} unknown`, "repair-historical-counts"));
    const history = element("details", undefined, "repair-disclosure"); history.append(element("summary", "History and acceptance binding"), element("p", "Original v2 results remain historical. Unknowns, incomplete coverage and failed engineering attempts remain visible."));
    detail(history, "Acceptance and input hashes", {manifest_sha256:overlay.manifest_sha256, review_sha256:overlay.review_sha256, acceptance:overlay.acceptance}); overview.append(history); page.append(overview);
    const status = element("section", undefined, "repair-status-section"); status.append(element("h3", "Reading and unresolved states"));
    states(status, {supplement_status:overlay.status, official_stage2_import_eligible:data.official_stage2_import_eligible, protected_execution_authorized:data.protected_execution_authorized, scientific_scores_changed:data.scientific_scores_changed});
    states(status, data.source_reading, true); states(status, data.source_findings_resolution); states(status, data.assertion_correction); states(status, data.unresolved); states(status, data.engineering);
    const recorded = element("div", undefined, "repair-recorded-details");
    for (const [label, value] of [["Source-reading results", data.source_reading], ["Evidence resolution", data.source_findings_resolution], ["Assertion correction", data.assertion_correction], ["Unresolved source and claim obligations", data.unresolved], ["Preserved engineering failures", data.engineering]]) detail(recorded, label, value);
    status.append(recorded); page.append(status);
    const findings = element("section", undefined, "repair-findings-section"); findings.append(element("h3", "Core findings"));
    const grid = element("div", undefined, "repair-findings-grid"); data.core_findings.forEach(row => finding(grid, row)); findings.append(grid); page.append(findings);
    const revisions = element("section", undefined, "repair-revisions-section"); revisions.append(element("h3", "Original claim → atomic revision mapping"));
    hint(revisions, "Expand a work group to read its atomic assertions. Each source binding preserves the full recorded limits and unresolved obligations."); groups(revisions, data.atomic_revisions); page.append(revisions);
    const exports = element("nav", undefined, "repair-exports"); exports.setAttribute("aria-label", "Closeout downloads");
    for (const [path, label] of [["closeout/literature-catalog.xlsx", "Editable Excel"], ["closeout/core-findings.md", "Core findings Markdown"], ["closeout/README.zh-TW.md", "繁體中文收尾說明"], ["closeout/claim-revision-map.json", "Complete claim revision mapping"]]) {const link = element("a", label); link.href = "./" + path; link.download = path.split("/").pop(); exports.append(link);} page.append(exports); root.append(page);
  }
  window.WorkspaceRepair = Object.freeze({note, graph, render});
})();
