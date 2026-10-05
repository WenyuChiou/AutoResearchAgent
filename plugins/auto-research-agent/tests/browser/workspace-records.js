/* Opt-in browser regression. Synthetic fixture only; no research or networking. */
(() => {
  "use strict";
  const result = document.createElement("section"); result.id = "browser-test-results"; result.setAttribute("translate", "no");
  document.body.prepend(result);
  let passed = 0, failed = 0;
  function check(name, test) {
    const row = document.createElement("p");
    try { if (!test()) throw new Error("assertion was false"); row.textContent = `PASS: ${name}`; passed++; }
    catch (error) { row.textContent = `FAIL: ${name}: ${error.message}`; failed++; }
    result.append(row);
  }
  const api = window.WorkspaceRecords, data = window.WORKSPACE_VIEW.index;
  check("fresh origin defaults to English", () => document.documentElement.lang === "en");
  check("document title identifies a read-only package view", () => document.title === "Research Workspace | Read-only package view");
  check("all index papers rendered in graph/list/catalog", () => document.querySelectorAll(".graph-node.paper").length === 2 && document.querySelectorAll(".paper-row").length === 2 && document.querySelectorAll(".metadata-scroll tbody tr").length === 2);
  check("source injection remains inert text", () => !document.querySelector("#article img") && document.querySelector("#article").textContent.includes('<img src=x onerror="alert(1)">'));
  check("unsafe schemes and escaping artifact IDs rejected", () => ["javascript:alert(1)","../paper.pdf","/paper.pdf","a\\b","%2e%2e/paper.pdf","a//b","a/./b"].every(value => !api.safeArtifactId(value)) && api.safeArtifactId("papers/work-version.pdf"));
  check("missing year is explicit in list/detail/catalog without changing canonical data", () => document.querySelector(".paper-row small").textContent.includes(" · Not recorded · ") && [...document.querySelectorAll(".paper-detail dt")].find(node => node.textContent === "Year").nextElementSibling.textContent === "Not recorded" && document.querySelector(".metadata-scroll tbody tr").children[3].textContent === "Not recorded" && data.papers[0].year === null);
  for (const locale of ["zh-Hans", "zh-Hant", "en"]) {
    window.WorkspaceI18n.set(locale);
    check(`${locale}: language changes and source-label collision stays literal`, () => document.documentElement.lang === locale && document.querySelector(".paper-row strong").textContent === "Evidence" && document.querySelector(".paper-detail strong").textContent === "Evidence");
    document.querySelector('[data-workspace-view="catalog"]').click();
    check(`${locale}: catalog section titles remain visible`, () => {
      const titles = [...document.querySelectorAll("#article > .section-title")].filter(node => node.nextElementSibling?.matches(".paper-detail,.metadata-scroll"));
      return titles.length === 2 && titles.every(node => !node.hidden && node.getClientRects().length > 0 && node.textContent.trim());
    });
    document.querySelector('[data-workspace-view="graph"]').click();
  }
  const selected = document.querySelectorAll(".paper-row")[1]; selected.click();
  check("graph/list/detail share work/version selection", () => document.querySelector(".paper-row.selected").dataset.paperId === document.querySelector(".graph-node.paper.selected").dataset.paperId && document.querySelector(".paper-detail").dataset.selectedWork === "fixture-1" && document.querySelector(".paper-detail").dataset.selectedVersion === "version-1");
  const filter = document.querySelector('[data-literature-filter="text"]');
  filter.value = "Evidence"; filter.dispatchEvent(new Event("input", {bubbles:true}));
  check("filter updates graph/list/catalog and visible selection", () => document.querySelectorAll(".paper-row").length === 1 && document.querySelectorAll(".graph-node.paper").length === 1 && document.querySelectorAll(".metadata-scroll tbody tr").length === 1 && document.querySelector(".paper-detail").dataset.selectedWork === "fixture-0");
  const visible = [{workId:document.querySelector(".paper-row").dataset.paperId}];
  check("filtered BibTeX uses saved canonical entry", () => api.bibliography(visible, "filtered") === data.bibliography.entries[0].bibtex);
  check("all BibTeX preserves full canonical bytes regardless of filter", () => api.bibliography(visible, "all") === data.bibliography.all_bibtex);
  check("export scope is explicit", () => document.querySelector("#bibliographyScope").options.length === 2);
  check("raw source URL never becomes a navigation target", () => !document.querySelector('a[href^="javascript:"]'));
  document.querySelector('[data-workspace-view="notes"]').click();
  check("saved Markdown notes are bound to work/version and private relative files", () => {
    const links = [...document.querySelectorAll('[data-note-work]')];
    return links.length === data.papers.length && links.every(link => {
      const record = window.WORKSPACE_VIEW.note_paths.find(row => row.work_id === link.dataset.noteWork && row.version_id === link.dataset.noteVersion);
      return record && link.getAttribute("href") === "./" + record.path && /^wiki\/[a-f0-9]{64}\.md$/.test(record.path);
    });
  });
  for (const stage of [3,4,5,6]) {
    document.querySelectorAll("#stageRail button")[stage - 1].click();
    check(`stage ${stage} stays blocked with execution disabled`, () => document.querySelector("#article").textContent.includes("Blocked · execution disconnected") && [...document.querySelectorAll(".controls button")].every(button => button.disabled));
  }
  document.querySelectorAll("#stageRail button")[0].click();
  const title = document.createElement("h2"); title.textContent = `Synthetic browser checks: ${passed} passed, ${failed} failed`; result.prepend(title);
  result.dataset.failed = String(failed); result.dataset.passed = String(passed);
})();
