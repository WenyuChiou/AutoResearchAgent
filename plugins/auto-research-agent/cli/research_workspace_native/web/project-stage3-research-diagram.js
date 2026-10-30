/* Read-only F03 projection. The supplied saved view remains the scientific source. */
(function (root) {
  "use strict";
  const rows = value => Array.isArray(value) ? value : [];
  const show = value => value === undefined ? "—" : typeof value === "string" ? value : JSON.stringify(value);
  const kinds = ["question", "design", "analysis", "result", "conditional"];
  const words = {
    en: {title: "Research plan relationships", question: "Scientific question", design: "Research design", analysis: "Analysis", result: "Planned output", conditional: "Conditional planning record", note: "Only explicit source references are drawn. Arrows do not establish causality or completed execution.", conditionalNote: "Conditional records retain the original question references. No formal design, analysis or result IDs have been created.", grouped: "Grouped view: each box contains all records of that kind in this view. An arrow means at least one recorded reference; inspect the full reference table for individual links.", empty: "No saved plan relationships are available.", references: "Full source reference table", source: "Source", link: "Recorded reference", unknowns: "Unknowns (original values)", missing: "Unresolved reference", binding: "Saved version bindings", description: "Recorded links from scientific questions to research designs, analyses and planned outputs; missing references remain unresolved."},
    "zh-TW": {title: "研究計畫關係圖", question: "科學問題", design: "研究設計", analysis: "分析方法", result: "預期產物", conditional: "條件式規劃紀錄", note: "只繪出來源明列的引用；箭頭不代表因果關係或已執行完成。", conditionalNote: "條件式紀錄保留原 question_ref；沒有建立正式 design、analysis 或 result ID。", grouped: "分組視圖：每個框包含本視圖該類的全部紀錄。箭頭表示至少一筆原始引用；個別連結請見完整引用表。", empty: "目前沒有可呈現的已保存計畫關係。", references: "完整來源引用表", source: "來源", link: "原始引用", unknowns: "Unknown（保留原值）", missing: "待釐清引用", binding: "已保存的版本綁定", description: "呈現科學問題、研究設計、分析與預期產物間明列的引用，缺少的引用保持待釐清。"},
    "zh-CN": {title: "研究计划关系图", question: "科学问题", design: "研究设计", analysis: "分析方法", result: "预期产物", conditional: "条件式规划记录", note: "只绘出来源明列的引用；箭头不代表因果关系或已执行完成。", conditionalNote: "条件式记录保留原 question_ref；没有建立正式 design、analysis 或 result ID。", grouped: "分组视图：每个框包含本视图该类的全部记录。箭头表示至少一笔原始引用；个别链接请见完整引用表。", empty: "目前没有可呈现的已保存计划关系。", references: "完整来源引用表", source: "来源", link: "原始引用", unknowns: "Unknown（保留原值）", missing: "待厘清引用", binding: "已保存的版本绑定", description: "呈现科学问题、研究设计、分析与预期产物间明列的引用，缺少的引用保持待厘清。"}
  };
  let mounts = 0;

  function project(view) {
    const plan = view?.plan, conditional = view?.planning_mode === "direction-intent";
    const model = {mode: conditional ? "conditional" : "formal", binding: {}, nodes: [], edges: [], unknowns: [], missing: []};
    for (const [name, value] of Object.entries(plan || {})) {
      if (/^(kind|schema_version|plan_id|version)$|sha256$/.test(name)) model.binding[name] = value;
    }
    for (const name of ["key", "request_sha256"]) {
      if (Object.hasOwn(view?.default_request || {}, name)) model.binding[name] = view.default_request[name];
    }
    const index = new Map(), edges = new Map();
    function add(kind, record, source, id, label) {
      const node = {key: `${kind}-${model.nodes.length}`, kind, id, label, source, record};
      model.nodes.push(node);
      const key = JSON.stringify([kind, id]);
      index.set(key, [...(index.get(key) || []), node]);
      return node;
    }
    function find(kind, id, source) {
      const matches = index.get(JSON.stringify([kind, id])) || [];
      if (id === undefined || matches.length !== 1) {
        model.missing.push({kind, id, source, reason: matches.length > 1 ? "ambiguous" : "missing"});
        return null;
      }
      return matches[0];
    }
    function link(from, to, source) {
      if (!from || !to) return;
      const key = `${from.key}/${to.key}`;
      if (!edges.has(key)) edges.set(key, {from: from.key, to: to.key, sources: []});
      edges.get(key).sources.push(source);
    }
    if (conditional) {
      rows(view?.direction_context?.questions).forEach((q, i) => add("question", q, `/direction_context/questions/${i}`, q.question_ref, q.text));
      rows(plan?.question_plans).forEach((p, i) => {
        const source = `/plan/question_plans/${i}`;
        const node = add("conditional", p, source, p.question_ref, p.design);
        link(find("question", p.question_ref, `${source}/question_ref`), node, `${source}/question_ref`);
        if (Object.hasOwn(p, "unknowns")) model.unknowns.push({source: `${source}/unknowns`, value: p.unknowns});
      });
      for (const name of ["unresolved", "source_unresolved", "pending_scope_questions", "missing_mapping"]) {
        if (Object.hasOwn(view?.direction_context || {}, name)) model.unknowns.push({source: `/direction_context/${name}`, value: view.direction_context[name]});
      }
    } else if (plan?.kind === "Stage3ResearchPlan") {
      for (const [field, kind, id, label] of [["questions", "question", "question_ref", "text"], ["designs", "design", "design_id", "family"], ["analyses", "analysis", "analysis_id", "method"], ["results", "result", "result_id", "artifact"]]) {
        rows(plan[field]).forEach((record, i) => add(kind, record, `/plan/${field}/${i}`, record[id], record[label]));
      }
      rows(plan.question_plans).forEach((p, i) => {
        const source = `/plan/question_plans/${i}`, q = find("question", p.question_ref, `${source}/question_ref`);
        for (const [field, kind] of [["design_ids", "design"], ["analysis_ids", "analysis"], ["result_ids", "result"]]) {
          rows(p[field]).forEach((id, j) => {
            const ref = `${source}/${field}/${j}`, target = find(kind, id, ref);
            if (kind === "design") link(q, target, ref);
          });
        }
      });
      for (const [field, kind, idField, targetKind] of [["analyses", "analysis", "design_ids", "design"], ["results", "result", "analysis_ids", "analysis"]]) {
        rows(plan[field]).forEach((record, i) => {
          const source = `/plan/${field}/${i}`, target = model.nodes.find(n => n.source === source);
          rows(record[idField]).forEach((id, j) => {
            const ref = `${source}/${idField}/${j}`;
            link(find(targetKind, id, ref), target, ref);
          });
        });
      }
      rows(plan.unknowns).forEach((value, i) => model.unknowns.push({source: `/plan/unknowns/${i}`, value}));
    }
    model.edges = [...edges.values()];
    return model;
  }

  function panels(model) {
    const present = kinds.filter(kind => model.nodes.some(n => n.kind === kind));
    const groups = present.map(kind => model.nodes.filter(n => n.kind === kind));
    if (model.nodes.length <= 9 && model.edges.length <= 12 && groups.every(g => g.length <= 4)) return [{...model, grouped: false}];
    const nodes = groups.map((members, i) => ({key: `group-${i}`, kind: members[0].kind, members, id: members.length, label: undefined}));
    const membership = new Map(nodes.flatMap(n => n.members.map(member => [member.key, n.key]))), links = new Map();
    for (const edge of model.edges) {
      const from = membership.get(edge.from), to = membership.get(edge.to), key = `${from}/${to}`;
      if (!links.has(key)) links.set(key, {from, to, sources: []});
      links.get(key).sources.push(...edge.sources);
    }
    return [{nodes, edges: [...links.values()], grouped: true}];
  }

  function layout(panel) {
    const ranks = kinds.filter(kind => panel.nodes.some(n => n.kind === kind));
    const positions = new Map();
    let top = 56;
    for (const kind of ranks) {
      const nodes = panel.nodes.filter(n => n.kind === kind);
      nodes.forEach((n, i) => positions.set(n.key, {...n, x: 512 + (i - Math.floor(nodes.length / 2)) * 288 + (nodes.length % 2 ? 0 : 128), y: top, width: 256, height: 96}));
      const outgoing = panel.edges.filter(e => nodes.some(n => n.key === e.from));
      top += 96 + Math.max(80, outgoing.length * 24 + 32);
    }
    const routes = panel.edges.map(edge => {
      const from = positions.get(edge.from), to = positions.get(edge.to);
      const outgoing = panel.edges.filter(e => e.from === edge.from), incoming = panel.edges.filter(e => e.to === edge.to);
      const between = panel.edges.filter(e => positions.get(e.from).y === from.y);
      return {...edge, sx: from.x + 128 + (outgoing.indexOf(edge) - Math.floor(outgoing.length / 2)) * 32,
        tx: to.x + 144 + (incoming.indexOf(edge) - Math.floor(incoming.length / 2)) * 32,
        sy: from.y + 96, ty: to.y, lane: from.y + 120 + between.indexOf(edge) * 24};
    });
    const nodes = [...positions.values()], left = Math.min(...nodes.map(n => n.x)) - 32;
    const width = Math.max(...nodes.map(n => n.x + n.width)) - left + 32;
    for (const node of nodes) node.x -= left;
    for (const route of routes) {route.sx -= left;route.tx -= left;}
    return {nodes, routes, width, height: Math.max(400, top - 40)};
  }

  function routePath(route, routes) {
    const {sx, sy, tx, ty, lane} = route, sign = Math.sign(tx - sx), r = 8;
    const crossings = new Set();
    for (const other of routes) {
      if (other === route) continue;
      for (const [x, y1, y2] of [[other.sx, other.sy, other.lane - r], [other.tx, other.lane + r, other.ty]]) {
        if (x > Math.min(sx, tx) + 12 && x < Math.max(sx, tx) - 12 && lane > y1 + 4 && lane < y2 - 4) crossings.add(x);
      }
    }
    let path = `M ${sx} ${sy} V ${lane - r} Q ${sx} ${lane} ${sx + sign * r} ${lane}`;
    for (const x of [...crossings].sort((a, b) => sign * (a - b))) path += ` H ${x - sign * 4} Q ${x} ${lane - 8} ${x + sign * 4} ${lane}`;
    return path + ` H ${tx - sign * r} Q ${tx} ${lane} ${tx} ${lane + r} V ${ty}`;
  }

  const textWidth = (text, size) => Array.from(text).reduce((total, c) => total + (c.codePointAt(0) > 255 ? size : Math.ceil(size * 0.62)), 0);
  function clip(text, size = 12) {
    if (textWidth(text, size) <= 216) return text;
    let result = "";
    for (const char of text) {
      if (textWidth(result + char + "…", size) > 216) break;
      result += char;
    }
    return result + "…";
  }
  function wrap(text) {
    const lines = [];let line = "";
    for (const token of text.match(/[A-Za-z0-9]+(?:['’_-][A-Za-z0-9]+)*|\s+|./gu) || []) {
      if (textWidth(line + token, 14) > 216 && line) {lines.push(line.trimEnd());line = "";}
      if (!line && /^\s+$/.test(token)) continue;
      for (const char of token) {
        if (textWidth(line + char, 14) > 216) {lines.push(line);line = "";}
        line += char;
      }
    }
    lines.push(line.trimEnd());return lines;
  }

  function mount(container, view, options = {}) {
    const doc = container.ownerDocument, language = Object.hasOwn(words, options.language) ? options.language : "en", w = words[language];
    const model = project(view), prefix = `stage3-research-${++mounts}`;
    function node(parent, tag, text, attributes = {}, svg = false) {
      const child = svg ? doc.createElementNS("http://www.w3.org/2000/svg", tag) : doc.createElement(tag);
      for (const [key, value] of Object.entries(attributes)) child.setAttribute(key, String(value));
      if (text !== undefined) child.textContent = text;
      parent.append(child);return child;
    }
    container.replaceChildren();
    node(container, "h3", w.title);
    node(container, "p", model.mode === "conditional" ? w.conditionalNote : w.note);
    const version = node(container, "details");
    node(version, "summary", w.binding + (Object.hasOwn(model.binding, "version") ? `: v${show(model.binding.version)}` : ""));
    const binding = node(version, "pre", show(model.binding));
    binding.style.overflowWrap = "anywhere";binding.style.whiteSpace = "pre-wrap";
    if (!model.nodes.length) node(container, "p", w.empty);
    for (const [i, panel] of (model.nodes.length ? panels(model) : []).entries()) {
      const geometry = layout(panel), figure = node(container, "figure", undefined, {class: "stage3-research-figure"});
      figure.style.margin = "1rem 0";figure.style.minWidth = "0";figure.style.maxWidth = "100%";
      if (panel.grouped) node(figure, "figcaption", w.grouped);
      const scroller = node(figure, "div", undefined, {class: "stage3-research-scroll", tabindex: "0", role: "region", "aria-label": w.title});
      scroller.style.overflowX = "auto";scroller.style.maxWidth = "100%";
      const svg = node(scroller, "svg", undefined, {viewBox: `0 0 ${geometry.width} ${geometry.height}`, role: "img", "aria-labelledby": `${prefix}-${i}-title ${prefix}-${i}-desc`}, true);
      svg.style.width = `${geometry.width}px`;svg.style.minWidth = `${geometry.width}px`;svg.style.marginInline = "auto";svg.style.display = "block";svg.style.fontFamily = "system-ui, sans-serif";
      node(svg, "title", w.title, {id: `${prefix}-${i}-title`}, true);
      node(svg, "desc", model.mode === "conditional" ? w.conditionalNote : w.description, {id: `${prefix}-${i}-desc`}, true);
      const defs = node(svg, "defs", undefined, {}, true);
      const marker = node(defs, "marker", undefined, {id: `${prefix}-${i}-arrow`, markerWidth: 8, markerHeight: 6, refX: 7, refY: 3, orient: "auto"}, true);
      node(marker, "path", undefined, {d: "M 0 0 L 8 3 L 0 6 Z", fill: "#40566d"}, true);
      node(svg, "rect", undefined, {x: 0, y: 0, width: geometry.width, height: geometry.height, fill: "#fff"}, true);
      for (const route of geometry.routes) {
        const d = routePath(route, geometry.routes);
        node(svg, "path", undefined, {d, stroke: "#fff", "stroke-width": 6, fill: "none"}, true);
        const path = node(svg, "path", undefined, {d, stroke: "#40566d", "stroke-width": 1.5, fill: "none", "marker-end": `url(#${prefix}-${i}-arrow)`}, true);
        node(path, "title", route.sources.join("\n"), {}, true);
      }
      for (const n of geometry.nodes) {
        const group = node(svg, "g", undefined, {"data-source-ref": n.source || "", "data-kind": n.kind}, true);
        node(group, "title", n.members ? n.members.map(m => `${show(m.id)}: ${show(m.label)}`).join("\n") : `${show(n.id)}: ${show(n.label)}`, {}, true);
        node(group, "rect", undefined, {x: n.x, y: n.y, width: n.width, height: n.height, rx: 6, fill: n.kind === "result" ? "#f1f5f8" : "#fff", stroke: "#143f6b"}, true);
        node(group, "text", w[n.kind], {x: n.x + 16, y: n.y + 20, fill: "#40566d", "font-size": 12}, true);
        const count = panel.edges.filter(e => e.to === n.key).length;
        node(group, "text", `${count} in`, {x: n.x + 240, y: n.y + 20, fill: "#40566d", "font-size": 12, "text-anchor": "end"}, true);
        const label = n.members ? `${w[n.kind]} × ${n.members.length}` : show(n.label);
        const lines = wrap(label);
        for (let j = 0; j < Math.min(2, lines.length); j++) node(group, "text", clip(lines[j] + (j === 1 && lines.length > 2 ? "…" : ""), 14), {x: n.x + 16, y: n.y + 44 + j * 18, fill: "#143f6b", "font-size": 14, "font-weight": 600}, true);
        node(group, "text", clip(show(n.id)), {x: n.x + 16, y: n.y + 84, fill: "#40566d", "font-size": 12, "font-family": "ui-monospace, monospace"}, true);
      }
    }
    const details = node(container, "details"), summary = node(details, "summary", w.references);
    summary.style.minHeight = "44px";
    const table = node(details, "table"), caption = node(table, "caption", w.references);
    caption.style.textAlign = "left";table.style.width = "100%";table.style.overflowWrap = "anywhere";table.style.tableLayout = "fixed";
    const head = node(table, "thead"), headers = node(head, "tr");
    for (const label of [w.link, w.source]) node(headers, "th", label, {scope: "col"});
    const body = node(table, "tbody");
    function row(label, source) {const tr = node(body, "tr");node(tr, "td", label);node(tr, "td", source);}
    for (const n of model.nodes) row(`${w[n.kind]} ${show(n.id)}: ${show(n.record)}`, n.source);
    for (const e of model.edges) row(`${show(model.nodes.find(n => n.key === e.from).id)} → ${show(model.nodes.find(n => n.key === e.to).id)}`, e.sources.join("\n"));
    for (const m of model.missing) row(`${w.missing}: ${show(m.id)} (${m.reason})`, m.source);
    for (const u of model.unknowns) row(`${w.unknowns}: ${show(u.value)}`, u.source);
    if (model.missing.length) node(container, "p", `${w.missing}: ${model.missing.length}`);
    node(container, "p", `${w.unknowns}: ${model.unknowns.length}`);
    return model;
  }
  root.STAGE3_RESEARCH_DIAGRAM = Object.freeze({project, mount});
}(typeof window === "object" ? window : globalThis));
