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
  // Source values may collide with UI labels, e.g. a paper titled "Evidence".
  const source = (tag, value) => {
    const element = create(tag, value);
    element.setAttribute("translate", "no");
    return element;
  };
  const shown = (value) =>
    value === null || value === undefined || value === "" ? "Not recorded" : String(value);

  const compactLabel = (value, limit = 24) => {
    const label = String(value).replace(/\s+/g, " ").trim();
    return label.length <= limit ? label : `${label.slice(0, limit - 1).trimEnd()}\u2026`;
  };
  const clampGraphPoint = (point, width = 960, height = 540) => ({
    x: Math.max(44, Math.min(width - 44, point.x)),
    y: Math.max(44, Math.min(height - 44, point.y)),
  });
  const filterRecords = (records, filters = {}) => {
    const needle = String(filters.text || "").trim().toLowerCase();
    return records.filter((paper) => {
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

  function layoutGraph(nodes, edges, width = 960, height = 540) {
    const center = { x: width / 2, y: height / 2 };
    const ordered = [...nodes].sort((a, b) => a.key.localeCompare(b.key));
    const positions = new Map();
    const rings = {
      paper: Math.min(width, height) * 0.2,
      keyword: Math.min(width, height) * 0.36,
      role: Math.min(width, height) * 0.43,
    };
    const byType = new Map(
      ["paper", "keyword", "role"].map((type) => [
        type,
        ordered.filter((node) => node.type === type),
      ]),
    );
    byType.forEach((items, type) => {
      items.forEach((node, index) => {
        const angle = (Math.PI * 2 * index) / Math.max(1, items.length) - Math.PI / 2;
        positions.set(node.key, {
          x: center.x + Math.cos(angle) * rings[type],
          y: center.y + Math.sin(angle) * rings[type],
        });
      });
    });
    for (let step = 0; step < 42; step += 1) {
      const forces = new Map(ordered.map((node) => [node.key, { x: 0, y: 0 }]));
      for (let left = 0; left < ordered.length; left += 1) {
        for (let right = left + 1; right < ordered.length; right += 1) {
          const a = positions.get(ordered[left].key), b = positions.get(ordered[right].key);
          let dx = a.x - b.x, dy = a.y - b.y;
          const distance = Math.max(1, Math.hypot(dx, dy));
          if (distance < 116) {
            const push = (116 - distance) * 0.055;
            dx /= distance; dy /= distance;
            forces.get(ordered[left].key).x += dx * push;
            forces.get(ordered[left].key).y += dy * push;
            forces.get(ordered[right].key).x -= dx * push;
            forces.get(ordered[right].key).y -= dy * push;
          }
        }
      }
      edges.forEach((edge) => {
        const from = positions.get(edge.from), to = positions.get(edge.to);
        const dx = to.x - from.x, dy = to.y - from.y;
        const distance = Math.max(1, Math.hypot(dx, dy));
        const pull = (distance - 178) * 0.012;
        forces.get(edge.from).x += (dx / distance) * pull;
        forces.get(edge.from).y += (dy / distance) * pull;
        forces.get(edge.to).x -= (dx / distance) * pull;
        forces.get(edge.to).y -= (dy / distance) * pull;
      });
      ordered.forEach((node) => {
        const point = positions.get(node.key), force = forces.get(node.key);
        force.x += (center.x - point.x) * 0.002;
        force.y += (center.y - point.y) * 0.002;
        Object.assign(point, clampGraphPoint({ x: point.x + force.x, y: point.y + force.y }, width, height));
      });
    }
    return positions;
  }

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

  function render(root, records = demoRecords) {
    let selectedId = records[0]?.workId || null;
    const viewport = { scale: 1, x: 0, y: 0 };
    let graphPositions = new Map();
    const filters = { text: "", keyword: "", role: "" };
    root.replaceChildren();
    root.classList.add("literature-shell");

    root.append(
      create("div", "Stage 1 / Synthetic Literature Reference", "kicker"),
      create("h2", "Local Literature Graph"),
      create(
        "p",
        "Explore papers, recorded classifications, and literature roles.",
        "lede",
      ),
    );

    const graphExplanation = create("details", undefined, "graph-explanation");
    graphExplanation.append(
      create("summary", "What do the connections mean?"),
      create("p", "Edges show recorded assignments only. They do not establish similarity, citations, claim support, coverage, or research quality."),
    );
    root.append(graphExplanation);

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
        const option = source("option", value);
        option.value = value;
        select.append(option);
      });
    };
    addOptions(
      keywordFilter,
      "All keywords",
      [...new Set(records.flatMap((paper) => paper.keywords))].sort(),
    );
    addOptions(
      roleFilter,
      "All roles",
      [...new Set(records.flatMap((paper) => paper.roles.map((role) => role.name)))].sort(),
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
    const zoomFit = create("button", "Fit", "lit-button");
    const zoomReset = create("button", "Reset layout", "lit-button");
    zoomOut.dataset.literatureAction = "zoom-out";
    zoomIn.dataset.literatureAction = "zoom-in";
    zoomFit.dataset.literatureAction = "zoom-fit";
    zoomReset.dataset.literatureAction = "layout-reset";
    graphActions.append(graphLabel, zoomOut, zoomIn, zoomFit, zoomReset);
    root.append(graphActions);
    const graphFrame = create("div", undefined, "graph-frame");
    graphFrame.tabIndex = 0;
    graphFrame.setAttribute("role", "region");
    graphFrame.setAttribute("aria-label", "Interactive literature graph; drag the canvas to pan");
    const svg = createSvg("svg", {
      "class": "literature-graph",
      "role": "group",
      "aria-label": "Synthetic literature graph of papers, keywords, and recorded roles",
    });
    graphFrame.append(svg);
    const graphTooltip = create("div", "", "graph-tooltip");
    graphTooltip.hidden = true;
    graphTooltip.setAttribute("role", "status");
    graphFrame.append(graphTooltip);
    root.append(graphFrame);
    root.append(
      create(
        "p",
        "Select a paper to inspect its record. Hover or focus a node for its full label.",
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

    const visible = () => filterRecords(records, filters);

    const setSelection = (workId, focusSelector) => {
      selectedId = workId;
      updateGraph();
      updateList();
      updateDetail();
      window.WorkspaceI18n?.apply(root);
      if (focusSelector) root.querySelector(focusSelector)?.focus();
    };

    const applyViewport = () => {
      svg.querySelector(".graph-scene")?.setAttribute(
        "transform",
        `translate(${viewport.x} ${viewport.y}) scale(${viewport.scale})`,
      );
      svg.setAttribute("data-zoom", viewport.scale.toFixed(2));
    };
    const fitGraph = () => {
      viewport.scale = 1;
      viewport.x = 0;
      viewport.y = 0;
      applyViewport();
    };
    const zoomGraph = (factor, anchor = { x: 480, y: 270 }) => {
      const previous = viewport.scale;
      viewport.scale = Math.max(0.55, Math.min(2.4, previous * factor));
      viewport.x = anchor.x - ((anchor.x - viewport.x) * viewport.scale) / previous;
      viewport.y = anchor.y - ((anchor.y - viewport.y) * viewport.scale) / previous;
      applyViewport();
    };
    const pointInGraph = (event) => {
      const point = svg.createSVGPoint();
      point.x = event.clientX;
      point.y = event.clientY;
      const screen = point.matrixTransform(svg.getScreenCTM().inverse());
      return {
        x: (screen.x - viewport.x) / viewport.scale,
        y: (screen.y - viewport.y) / viewport.scale,
      };
    };
    let draggedNodeKey = null;

    function updateGraph() {
      const papers = visible();
      const keywords = [...new Set(papers.flatMap((paper) => paper.keywords))].sort();
      const roles = [...new Set(papers.flatMap((paper) => paper.roles.map((role) => role.name)))].sort();
      const nodes = [
        ...papers.map((paper) => ({
          key: `paper:${paper.workId}`,
          type: "paper",
          label: paper.title,
          detail: `${paper.authors.join("; ")} · ${paper.year} · ${paper.sourceStatus}`,
          paper,
        })),
        ...keywords.map((keyword) => ({
          key: `keyword:${keyword}`,
          type: "keyword",
          label: keyword,
          detail: "Recorded classification",
        })),
        ...roles.map((role) => ({
          key: `role:${role}`,
          type: "role",
          label: role,
          detail: "Recorded literature role",
        })),
      ];
      const edges = papers.flatMap((paper) => [
        ...paper.keywords.map((keyword) => ({
          from: `paper:${paper.workId}`,
          to: `keyword:${keyword}`,
          reason: `Recorded keyword assignment: ${paper.title} → ${keyword}`,
        })),
        ...paper.roles.map((role) => ({
          from: `paper:${paper.workId}`,
          to: `role:${role.name}`,
          reason: `Recorded role assignment: ${paper.title} → ${role.name}. ${role.basis}`,
        })),
      ]);
      graphPositions = layoutGraph(nodes, edges);
      svg.setAttribute("viewBox", "0 0 960 540");
      svg.replaceChildren();
      const title = createSvg("title");
      title.textContent = "Recorded paper-to-classification and paper-to-role assignments";
      const scene = createSvg("g", { class: "graph-scene" });
      const edgeLayer = createSvg("g", { class: "graph-edges" });
      const nodeLayer = createSvg("g", { class: "graph-nodes" });
      scene.append(edgeLayer, nodeLayer);
      svg.append(title, scene);

      const connected = new Map(nodes.map((node) => [node.key, new Set([node.key])]));
      edges.forEach((edge) => {
        connected.get(edge.from).add(edge.to);
        connected.get(edge.to).add(edge.from);
        const from = graphPositions.get(edge.from), to = graphPositions.get(edge.to);
        const line = createSvg("line", {
          x1: from.x, y1: from.y, x2: to.x, y2: to.y,
          class: "graph-edge",
          "data-from": edge.from,
          "data-to": edge.to,
        });
        const edgeTitle = createSvg("title");
        edgeTitle.setAttribute("translate", "no");
        edgeTitle.textContent = edge.reason;
        line.append(edgeTitle);
        edgeLayer.append(line);
      });

      const highlight = (key) => {
        const neighborhood = key ? connected.get(key) : null;
        nodeLayer.querySelectorAll(".graph-node").forEach((element) => {
          element.classList.toggle("dimmed", Boolean(neighborhood && !neighborhood.has(element.dataset.nodeKey)));
          element.classList.toggle("neighbor", Boolean(key && key !== element.dataset.nodeKey && neighborhood?.has(element.dataset.nodeKey)));
        });
        edgeLayer.querySelectorAll(".graph-edge").forEach((element) => {
          const active = !key || element.dataset.from === key || element.dataset.to === key;
          element.classList.toggle("dimmed", !active);
          element.classList.toggle("neighbor", Boolean(key && active));
        });
      };
      const showTooltip = (node, element) => {
        graphTooltip.replaceChildren(
          source("strong", node.label),
          source("span", node.detail),
        );
        graphTooltip.dataset.type = node.type;
        graphTooltip.hidden = false;
        const frameBox = graphFrame.getBoundingClientRect();
        const nodeBox = element.getBoundingClientRect();
        graphTooltip.style.left = `${Math.max(10, Math.min(frameBox.width - 290, nodeBox.left - frameBox.left + nodeBox.width / 2 + 18))}px`;
        graphTooltip.style.top = `${Math.max(10, nodeBox.top - frameBox.top - 8)}px`;
      };
      const hideTooltip = () => { graphTooltip.hidden = true; };

      nodes.forEach((node) => {
        const position = graphPositions.get(node.key);
        const group = createSvg("g", {
          translate: "no",
          class: `graph-node ${node.type}${node.paper?.workId === selectedId ? " selected" : ""}`,
          transform: `translate(${position.x} ${position.y})`,
          tabindex: "0",
          role: node.type === "paper" ? "button" : "img",
          "aria-label": node.type === "paper" ? `Select ${node.label}` : `${node.detail}: ${node.label}`,
        });
        group.dataset.nodeKey = node.key;
        if (node.paper) {
          group.dataset.paperId = node.paper.workId;
          group.setAttribute("aria-pressed", String(node.paper.workId === selectedId));
        }
        const radius = node.type === "paper" ? 30 : 23;
        group.append(
          createSvg("circle", { r: radius }),
          createSvg("circle", { r: 4, class: "graph-node-core" }),
        );
        const label = createSvg("text", { y: radius + 17, "text-anchor": "middle" });
        label.textContent = compactLabel(node.label, node.type === "paper" ? 25 : 18);
        const fullTitle = createSvg("title");
        fullTitle.textContent = `${node.label}. ${node.detail}`;
        group.append(label, fullTitle);
        group.addEventListener("pointerenter", () => { highlight(node.key); showTooltip(node, group); });
        group.addEventListener("pointerleave", () => { highlight(null); hideTooltip(); });
        group.addEventListener("focus", () => { highlight(node.key); showTooltip(node, group); });
        group.addEventListener("blur", () => { highlight(null); hideTooltip(); });
        group.addEventListener("click", () => {
          if (draggedNodeKey === node.key) {
            draggedNodeKey = null;
            return;
          }
          if (node.paper) setSelection(node.paper.workId);
        });
        group.addEventListener("keydown", (event) => {
          if (node.paper && (event.key === "Enter" || event.key === " ")) {
            event.preventDefault();
            setSelection(node.paper.workId, `[data-paper-id="${node.paper.workId}"]`);
          }
          const movement = { ArrowLeft: [-12, 0], ArrowRight: [12, 0], ArrowUp: [0, -12], ArrowDown: [0, 12] }[event.key];
          if (movement) {
            event.preventDefault();
            Object.assign(position, clampGraphPoint({ x: position.x + movement[0], y: position.y + movement[1] }));
            group.setAttribute("transform", `translate(${position.x} ${position.y})`);
            edgeLayer.querySelectorAll(".graph-edge").forEach((edge) => {
              if (edge.dataset.from === node.key) { edge.setAttribute("x1", position.x); edge.setAttribute("y1", position.y); }
              if (edge.dataset.to === node.key) { edge.setAttribute("x2", position.x); edge.setAttribute("y2", position.y); }
            });
            showTooltip(node, group);
          }
        });
        nodeLayer.append(group);
      });
      applyViewport();
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
          source("strong", paper.title),
          source("small", `${paper.authors.join("; ")} · ${paper.year} · ${paper.sourceStatus}`),
        );
        row.onclick = () =>
          setSelection(paper.workId, `.paper-row[data-paper-id="${paper.workId}"]`);
        paperList.append(row);
      });
      if (!papers.length)
        paperList.append(create("p", "No synthetic records match these filters.", "empty-note"));
      count.textContent = `${papers.length} of ${records.length} synthetic records visible`;
    }

    function updateDetail() {
      const paper = records.find((record) => record.workId === selectedId);
      detail.replaceChildren();
      if (!paper || !visible().some((record) => record.workId === selectedId)) {
        detail.append(
          create("p", "Select a visible paper to inspect its metadata and recorded role basis."),
        );
        return;
      }
      detail.append(source("strong", paper.title));
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
      ].forEach(([term, value]) => description.append(create("dt", term), source("dd", value)));
      detail.append(description, create("div", "Recorded role basis", "section-title"));
      paper.roles.forEach((role) => detail.append(source("p", `${role.name}: ${role.basis}`)));
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
        ].forEach((value) => row.append(source("td", value)));
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
      window.WorkspaceI18n?.apply(root);
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
    zoomOut.onclick = () => zoomGraph(0.85);
    zoomIn.onclick = () => zoomGraph(1.18);
    zoomFit.onclick = fitGraph;
    zoomReset.onclick = () => {
      fitGraph();
      updateGraph();
      window.WorkspaceI18n?.apply(root);
    };
    let pointerSession = null;
    svg.addEventListener("pointerdown", (event) => {
      if (pointerSession) return;
      draggedNodeKey = null;
      const node = event.target.closest?.(".graph-node");
      pointerSession = node
        ? {
            type: "node",
            pointerId: event.pointerId,
            node,
            captureTarget: node,
            key: node.dataset.nodeKey,
            clientX: event.clientX,
            clientY: event.clientY,
            moved: false,
          }
        : {
            type: "pan",
            pointerId: event.pointerId,
            captureTarget: svg,
            clientX: event.clientX,
            clientY: event.clientY,
            x: viewport.x,
            y: viewport.y,
          };
      pointerSession.captureTarget.setPointerCapture(event.pointerId);
      event.preventDefault();
    });
    svg.addEventListener("pointermove", (event) => {
      if (!pointerSession || event.pointerId !== pointerSession.pointerId) return;
      if (pointerSession.type === "pan") {
        const box = svg.getBoundingClientRect();
        viewport.x = pointerSession.x + ((event.clientX - pointerSession.clientX) * 960) / box.width;
        viewport.y = pointerSession.y + ((event.clientY - pointerSession.clientY) * 540) / box.height;
        applyViewport();
        return;
      }
      if (
        Math.hypot(event.clientX - pointerSession.clientX, event.clientY - pointerSession.clientY) > 4
      )
        pointerSession.moved = true;
      const position = graphPositions.get(pointerSession.key);
      if (!position) return;
      const point = pointInGraph(event);
      Object.assign(position, clampGraphPoint(point));
      pointerSession.node.setAttribute("transform", `translate(${position.x} ${position.y})`);
      svg.querySelectorAll(".graph-edge").forEach((edge) => {
        if (edge.dataset.from === pointerSession.key) { edge.setAttribute("x1", position.x); edge.setAttribute("y1", position.y); }
        if (edge.dataset.to === pointerSession.key) { edge.setAttribute("x2", position.x); edge.setAttribute("y2", position.y); }
      });
    });
    const endPointer = (event) => {
      if (!pointerSession || event.pointerId !== pointerSession.pointerId) return;
      const finished = pointerSession;
      draggedNodeKey = event.type === "pointerup" && finished.type === "node" && finished.moved ? finished.key : null;
      pointerSession = null;
      if (finished.captureTarget.hasPointerCapture(event.pointerId))
        finished.captureTarget.releasePointerCapture(event.pointerId);
    };
    svg.addEventListener("pointerup", endPointer);
    svg.addEventListener("pointercancel", endPointer);
    svg.addEventListener("lostpointercapture", endPointer);
    svg.addEventListener("wheel", (event) => {
      event.preventDefault();
      const point = svg.createSVGPoint();
      point.x = event.clientX;
      point.y = event.clientY;
      const anchor = point.matrixTransform(svg.getScreenCTM().inverse());
      zoomGraph(event.deltaY < 0 ? 1.12 : 0.89, anchor);
    }, { passive: false });
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
    layoutGraph,
    filterRecords,
    clampGraphPoint,
  });
})();
