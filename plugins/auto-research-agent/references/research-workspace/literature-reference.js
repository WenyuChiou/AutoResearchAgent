(function () {
  "use strict";

  const freezeRecord = (record) =>
    Object.freeze({
      ...record,
      authors: Object.freeze([...record.authors]),
      keywords: Object.freeze([...record.keywords]),
      roles: Object.freeze(record.roles.map((role) => Object.freeze({ ...role }))),
    });

  const demoRecords = Object.freeze([
    freezeRecord({
      workId: "work-demo-a",
      shortTitle: "Demo Study A",
      title: "Demo Study A — synthetic evidence mapping",
      authors: ["Example, Ada", "Example, Ben"],
      year: "2021",
      journal: "Demo Journal (synthetic)",
      volume: "1",
      issue: "1",
      pages: "1–12",
      doi: null,
      sourceStatus: "metadata-only",
      keywords: ["evidence map", "audit trail"],
      roles: [
        {
          name: "topic core",
          basis:
            "Synthetic role assignment: the example record directly addresses evidence mapping.",
        },
      ],
    }),
    freezeRecord({
      workId: "work-demo-b",
      shortTitle: "Demo Study B",
      title: "Demo Study B — synthetic workflow comparison",
      authors: ["Example, Cora", "Example, Dev", "Example, Eli"],
      year: "2022",
      journal: "Demo Methods Review (synthetic)",
      volume: "2",
      issue: "3",
      pages: "20–38",
      doi: null,
      sourceStatus: "metadata-only",
      keywords: ["audit trail", "workflow"],
      roles: [
        {
          name: "classic",
          basis:
            "Synthetic role assignment for interface demonstration only; it is not a scientific classic judgment.",
        },
        {
          name: "comparator",
          basis: "Synthetic record is assigned as a workflow comparator in this example view.",
        },
      ],
    }),
    freezeRecord({
      workId: "work-demo-c",
      shortTitle: "Demo Study C",
      title: "Demo Study C — synthetic closest-work review",
      authors: ["Example, Faye"],
      year: "2023",
      journal: "Demo Research Notes (synthetic)",
      volume: null,
      issue: null,
      pages: "7–16",
      doi: null,
      sourceStatus: "metadata-only",
      keywords: ["closest work", "workflow"],
      roles: [
        {
          name: "closest work",
          basis:
            "Synthetic role assignment: the example record is marked as the nearest scoped comparison.",
        },
        {
          name: "topic core",
          basis:
            "Synthetic overlapping role assignment recorded independently from closest-work status.",
        },
      ],
    }),
  ]);

  const svgNS = "http://www.w3.org/2000/svg";
  const create = (tag, text, className) => {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = text;
    if (className) element.className = className;
    return element;
  };
  const createSvg = (tag, attributes = {}) => {
    const element = document.createElementNS(svgNS, tag);
    Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, String(value)));
    return element;
  };
  const shown = (value) =>
    value === null || value === undefined || value === "" ? "Not recorded" : String(value);

  function bibEscape(value) {
    return String(value).replace(/[\\{}%&_#$^~\u0000-\u001f\u007f]/g, (character) => {
      const replacements = {
        "\\": "\\textbackslash{}",
        "{": "\\{",
        "}": "\\}",
        "%": "\\%",
        "&": "\\&",
        "_": "\\_",
        "#": "\\#",
        "$": "\\$",
        "^": "\\^{}",
        "~": "\\~{}",
      };
      return replacements[character] || " ";
    });
  }

  function toBibTeX(records) {
    const entries = records.map((paper) => {
      const key = paper.workId.replace(/[^A-Za-z0-9]+/g, "_");
      const fields = [
        ["title", paper.title],
        ["author", paper.authors.join(" and ")],
        ["journal", paper.journal],
        ["year", paper.year],
        ["volume", paper.volume],
        ["number", paper.issue],
        ["pages", paper.pages],
        ["doi", paper.doi],
      ].filter(([, value]) => value !== null && value !== undefined && value !== "");
      return `@article{${key},\n${fields
        .map(([name, value]) => `  ${name} = {${bibEscape(value)}}`)
        .join(",\n")}\n}`;
    });
    return `% SYNTHETIC BIBLIOGRAPHY — OFFLINE UI DEMO ONLY\n${entries.join("\n\n")}\n`;
  }

  function render(root) {
    let selectedId = demoRecords[0].workId;
    let zoom = 1;
    const filters = { text: "", keyword: "", role: "" };
    root.replaceChildren();
    root.classList.add("literature-shell");

    root.append(
      create("div", "Stage 1 / Synthetic Literature Reference", "kicker"),
      create("h2", "Local Literature Graph"),
      create(
        "p",
        "Browse a small Obsidian-like graph and complete bibliographic list. Edges show recorded assignments only; this view does not assert similarity, citation, evidence support, coverage, or quality.",
        "lede",
      ),
    );

    const toolbar = create("div", undefined, "lit-toolbar");
    const addField = (labelText, control) => {
      const label = create("label", undefined, "lit-field");
      label.append(create("span", labelText), control);
      toolbar.append(label);
    };
    const textFilter = create("input");
    textFilter.type = "search";
    textFilter.placeholder = "Title, author, journal, ID";
    textFilter.dataset.literatureFilter = "text";
    const keywordFilter = create("select");
    keywordFilter.dataset.literatureFilter = "keyword";
    const roleFilter = create("select");
    roleFilter.dataset.literatureFilter = "role";
    const addOptions = (select, first, values) => {
      const blank = create("option", first);
      blank.value = "";
      select.append(blank);
      values.forEach((value) => {
        const option = create("option", value);
        option.value = value;
        select.append(option);
      });
    };
    addOptions(
      keywordFilter,
      "All keywords",
      [...new Set(demoRecords.flatMap((paper) => paper.keywords))].sort(),
    );
    addOptions(
      roleFilter,
      "All roles",
      [...new Set(demoRecords.flatMap((paper) => paper.roles.map((role) => role.name)))].sort(),
    );
    addField("Filter literature", textFilter);
    addField("Keyword", keywordFilter);
    addField("Recorded role", roleFilter);
    root.append(toolbar);

    const actionRow = create("div", undefined, "lit-actions");
    const count = create("span", "", "lit-caveat");
    const exportButton = create("button", "Export visible .bib (synthetic)", "lit-button");
    exportButton.type = "button";
    exportButton.dataset.literatureAction = "export-bibtex";
    actionRow.append(exportButton, count);
    root.append(actionRow);

    const graphActions = create("div", undefined, "graph-actions");
    const graphLabel = create("span", "Graph view", "section-title");
    const zoomOut = create("button", "Zoom −", "lit-button");
    const zoomIn = create("button", "Zoom +", "lit-button");
    const zoomReset = create("button", "Reset", "lit-button");
    zoomOut.dataset.literatureAction = "zoom-out";
    zoomIn.dataset.literatureAction = "zoom-in";
    zoomReset.dataset.literatureAction = "zoom-reset";
    graphActions.append(graphLabel, zoomOut, zoomIn, zoomReset);
    root.append(graphActions);
    const graphFrame = create("div", undefined, "graph-frame");
    graphFrame.tabIndex = 0;
    graphFrame.setAttribute("role", "region");
    graphFrame.setAttribute("aria-label", "Scrollable literature graph");
    const svg = createSvg("svg", {
      "class": "literature-graph",
      "role": "group",
      "aria-label": "Synthetic literature graph of papers, keywords, and recorded roles",
    });
    graphFrame.append(svg);
    root.append(graphFrame);
    root.append(
      create(
        "p",
        "Select a paper to inspect its record. On narrow screens, scroll the graph horizontally.",
        "lit-caveat",
      ),
    );
    const legend = create("div", undefined, "graph-legend");
    [
      ["legend-key", "Paper"],
      ["legend-key keyword", "Keyword"],
      ["legend-key role", "Recorded role"],
    ].forEach(([className, label]) => legend.append(create("span", label, className)));
    legend.append(
      create(
        "span",
        "Lines mean an explicit keyword or role assignment. No paper-to-paper citation edges are recorded.",
      ),
    );
    root.append(legend);

    root.append(create("div", "Bibliographic list", "section-title"));
    const paperList = create("div", undefined, "paper-list");
    root.append(paperList);
    root.append(create("div", "Selected paper", "section-title"));
    const detail = create("section", undefined, "paper-detail");
    detail.setAttribute("aria-live", "polite");
    root.append(detail);
    root.append(create("div", "Complete metadata", "section-title"));
    const tableScroll = create("div", undefined, "metadata-scroll");
    tableScroll.setAttribute("role", "region");
    tableScroll.setAttribute("aria-label", "Scrollable complete bibliographic metadata");
    tableScroll.tabIndex = 0;
    const table = create("table");
    tableScroll.append(table);
    root.append(tableScroll);
    root.append(
      create(
        "p",
        "Synthetic UI demo only. Every source is metadata-only; no record represents full-text access. BibTeX export is separate from the canonical research deliverable exporter.",
        "lit-caveat",
      ),
    );

    const visible = () => {
      const needle = filters.text.trim().toLowerCase();
      return demoRecords.filter((paper) => {
        const haystack = [paper.workId, paper.title, paper.authors.join(" "), paper.journal]
          .join(" ")
          .toLowerCase();
        return (
          (!needle || haystack.includes(needle)) &&
          (!filters.keyword || paper.keywords.includes(filters.keyword)) &&
          (!filters.role || paper.roles.some((role) => role.name === filters.role))
        );
      });
    };

    const setSelection = (workId, focusSelector) => {
      selectedId = workId;
      updateGraph();
      updateList();
      updateDetail();
      if (focusSelector) root.querySelector(focusSelector)?.focus();
    };

    const svgText = (label, x, y) => {
      const text = createSvg("text", { x, y, "text-anchor": "middle" });
      text.textContent = label;
      return text;
    };
    const nodeGroup = (type, label, x, y, width, id) => {
      const group = createSvg("g", {
        class: `graph-node ${type}${id === selectedId ? " selected" : ""}`,
        transform: `translate(${x} ${y})`,
      });
      group.append(
        createSvg("rect", { x: -width / 2, y: -22, width, height: 44, rx: 8 }),
        svgText(label, 0, 5),
      );
      return group;
    };

    function updateGraph() {
      const papers = visible();
      const keywords = [...new Set(papers.flatMap((paper) => paper.keywords))].sort();
      const roles = [
        ...new Set(papers.flatMap((paper) => paper.roles.map((role) => role.name))),
      ].sort();
      const height = Math.max(
        400,
        papers.length * 115 + 70,
        keywords.length * 70 + 70,
        roles.length * 70 + 70,
      );
      const width = 820;
      const canvasWidth = Math.max(720, graphFrame.clientWidth) * zoom;
      svg.style.width = zoom === 1 ? "100%" : `${canvasWidth}px`;
      svg.style.minWidth = `${720 * zoom}px`;
      svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
      svg.replaceChildren();
      const title = createSvg("title");
      title.textContent = "Recorded paper-to-keyword and paper-to-role assignments";
      svg.append(title);
      const paperPositions = new Map(
        papers.map((paper, index) => [paper.workId, { x: 125, y: 65 + index * 115 }]),
      );
      const keywordPositions = new Map(
        keywords.map((keyword, index) => [keyword, { x: 420, y: 60 + index * 70 }]),
      );
      const rolePositions = new Map(
        roles.map((role, index) => [role, { x: 700, y: 60 + index * 70 }]),
      );
      const addEdge = (from, to, reason) => {
        const line = createSvg("line", {
          x1: from.x,
          y1: from.y,
          x2: to.x,
          y2: to.y,
          class: "graph-edge",
        });
        const edgeTitle = createSvg("title");
        edgeTitle.textContent = reason;
        line.append(edgeTitle);
        svg.append(line);
      };
      papers.forEach((paper) => {
        paper.keywords.forEach((keyword) =>
          addEdge(
            paperPositions.get(paper.workId),
            keywordPositions.get(keyword),
            `Recorded keyword assignment: ${paper.shortTitle} → ${keyword}`,
          ),
        );
        paper.roles.forEach((role) =>
          addEdge(
            paperPositions.get(paper.workId),
            rolePositions.get(role.name),
            `Recorded role assignment: ${paper.shortTitle} → ${role.name}. ${role.basis}`,
          ),
        );
      });
      papers.forEach((paper) => {
        const position = paperPositions.get(paper.workId);
        const group = nodeGroup(
          "paper",
          paper.shortTitle,
          position.x,
          position.y,
          170,
          paper.workId,
        );
        group.dataset.paperId = paper.workId;
        group.setAttribute("role", "button");
        group.setAttribute("aria-pressed", String(paper.workId === selectedId));
        group.setAttribute("tabindex", "0");
        group.setAttribute("aria-label", `Select ${paper.title}`);
        const fullTitle = createSvg("title");
        fullTitle.textContent = paper.title;
        group.append(fullTitle);
        group.addEventListener("click", () => setSelection(paper.workId));
        group.addEventListener("keydown", (event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            setSelection(paper.workId, `[data-paper-id="${paper.workId}"]`);
          }
        });
        svg.append(group);
      });
      keywords.forEach((keyword) => {
        const position = keywordPositions.get(keyword);
        svg.append(nodeGroup("keyword", keyword, position.x, position.y, 150));
      });
      roles.forEach((role) => {
        const position = rolePositions.get(role);
        svg.append(nodeGroup("role", role, position.x, position.y, 150));
      });
    }

    function updateList() {
      const papers = visible();
      paperList.replaceChildren();
      papers.forEach((paper) => {
        const row = create(
          "button",
          undefined,
          `paper-row${paper.workId === selectedId ? " selected" : ""}`,
        );
        row.type = "button";
        row.dataset.paperId = paper.workId;
        row.setAttribute("aria-pressed", String(paper.workId === selectedId));
        row.append(
          create("strong", paper.title),
          create("small", `${paper.authors.join("; ")} · ${paper.year} · ${paper.sourceStatus}`),
        );
        row.onclick = () =>
          setSelection(paper.workId, `.paper-row[data-paper-id="${paper.workId}"]`);
        paperList.append(row);
      });
      if (!papers.length)
        paperList.append(create("p", "No synthetic records match these filters.", "empty-note"));
      count.textContent = `${papers.length} of ${demoRecords.length} synthetic records visible`;
    }

    function updateDetail() {
      const paper = demoRecords.find((record) => record.workId === selectedId);
      detail.replaceChildren();
      if (!paper || !visible().some((record) => record.workId === selectedId)) {
        detail.append(
          create("p", "Select a visible paper to inspect its metadata and recorded role basis."),
        );
        return;
      }
      detail.append(create("strong", paper.title));
      const description = create("dl");
      [
        ["Work ID", paper.workId],
        ["Authors", paper.authors.join("; ")],
        ["Year", paper.year],
        ["Journal", paper.journal],
        ["Volume", shown(paper.volume)],
        ["Issue", shown(paper.issue)],
        ["Pages", shown(paper.pages)],
        ["DOI", shown(paper.doi)],
        ["Source", paper.sourceStatus],
        ["Keywords", paper.keywords.join(", ")],
      ].forEach(([term, value]) => description.append(create("dt", term), create("dd", value)));
      detail.append(description, create("div", "Recorded role basis", "section-title"));
      paper.roles.forEach((role) => detail.append(create("p", `${role.name}: ${role.basis}`)));
    }

    function updateTable() {
      const papers = visible();
      table.replaceChildren();
      const head = create("thead"),
        headRow = create("tr");
      [
        "Work ID",
        "Title",
        "Authors",
        "Year",
        "Journal",
        "Volume",
        "Issue",
        "Pages",
        "DOI",
        "Source",
      ].forEach((label) => headRow.append(create("th", label)));
      head.append(headRow);
      const body = create("tbody");
      papers.forEach((paper) => {
        const row = create("tr");
        [
          paper.workId,
          paper.title,
          paper.authors.join("; "),
          paper.year,
          paper.journal,
          shown(paper.volume),
          shown(paper.issue),
          shown(paper.pages),
          shown(paper.doi),
          paper.sourceStatus,
        ].forEach((value) => row.append(create("td", value)));
        body.append(row);
      });
      table.append(head, body);
    }

    function updateAll() {
      const papers = visible();
      if (!papers.some((paper) => paper.workId === selectedId))
        selectedId = papers[0]?.workId || null;
      updateGraph();
      updateList();
      updateDetail();
      updateTable();
    }

    textFilter.addEventListener("input", () => {
      filters.text = textFilter.value;
      updateAll();
    });
    keywordFilter.addEventListener("change", () => {
      filters.keyword = keywordFilter.value;
      updateAll();
    });
    roleFilter.addEventListener("change", () => {
      filters.role = roleFilter.value;
      updateAll();
    });
    zoomOut.onclick = () => {
      zoom = Math.max(0.7, zoom - 0.15);
      updateGraph();
    };
    zoomIn.onclick = () => {
      zoom = Math.min(1.6, zoom + 0.15);
      updateGraph();
    };
    zoomReset.onclick = () => {
      zoom = 1;
      updateGraph();
    };
    exportButton.onclick = () => {
      const blob = new Blob([toBibTeX(visible())], {
        type: "application/x-bibtex;charset=utf-8",
      });
      const url = URL.createObjectURL(blob);
      const link = create("a");
      link.href = url;
      link.download = "synthetic-stage1-literature.bib";
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 0);
    };
    updateAll();
  }

  window.LiteratureReference = Object.freeze({
    render,
    toBibTeX,
    demoRecords,
  });
})();
