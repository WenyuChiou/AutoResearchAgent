/* Pure navigation over already validated records; no fetch or execution. */
(function (host) {
  "use strict";
  const key = p => JSON.stringify([p.work_id, p.version_id]);
  const tags = value => [...new Set((Array.isArray(value) ? value : [value]).filter(v =>
    typeof v === "string" && v.trim() && !/^(unknown|unverified|not recorded|not independently assessed)(\b|\s|$)/i.test(v.trim()) &&
    !["未知", "未记录", "未記錄", "未验证", "未驗證"].includes(v.trim())))];
  const rows = value => Array.isArray(value) ? value : [];
  const matches = (p, row) => row.work_id === p.work_id && row.version_id === p.version_id;
  function papers(payload) {
    const index = payload.index;
    return rows(index.papers).map(p => ({
      ...p, key: key(p),
      topics: tags(p.classification?.topic_cluster),
      methods: tags(p.classification?.method),
      notePath: rows(payload.note_paths).find(n => matches(p, n))?.path ?? null,
      selection: rows(payload.literature_selection?.rows).find(r => matches(p, r)) ?? null,
      screening: rows(index.screening).filter(r => matches(p, r)),
      sources: rows(index.sources).filter(s => rows(p.source_ids).includes(s.source_id)),
      claims: rows(index.claims).filter(c => matches(p, c)),
      relations: rows(index.edges).filter(e => matches(p, e)),
      rawSearch: rows(index.search),
      discovery: {count: null, first_result_position: null, round: null, backend_attempts: null},
    }));
  }
  function stage2Papers(payload) {
    return rows(payload.stage2_comparison?.literature).map(p => ({
      ...p, key: p.key ?? key(p),
      topics: tags(p.classification?.topic_cluster),
      methods: tags(p.classification?.method),
    }));
  }
  function groups(records, field = "topics") {
    const found = new Map();
    for (const p of records) for (const label of rows(p[field])) {
      if (!found.has(label)) found.set(label, new Set());
      found.get(label).add(p.key);
    }
    return [...found].map(([label, ids]) => ({key: label, label, ids: [...ids]}))
      .sort((a, b) => b.ids.length - a.ids.length || a.key.localeCompare(b.key));
  }
  function networkLayout(records, options = {}) {
    /* One shared v6 canvas. Coordinates describe presentation, never relevance.
       Focus and pagination are intentionally not geometry inputs. */
    const compare = (a, b) => a < b ? -1 : a > b ? 1 : 0;
    const round = value => Math.round(value * 1000) / 1000;
    const clamp = (value, low, high) => Math.max(low, Math.min(high, value));
    const ordered = [...records].sort((a, b) => compare(a.key, b.key));
    const classified = groups(ordered).map(group => ({...group, ids: [...group.ids].sort(compare)}))
      .sort((a, b) => compare(a.key, b.key));
    const groupByKey = new Map(classified.map(group => [group.key, group]));
    const assigned = new Map(classified.map(group => [group.key, []]));
    const primary = new Map();
    for (const paper of ordered) {
      const memberships = tags(paper.topics).filter(label => groupByKey.has(label))
        .sort((a, b) => groupByKey.get(b).ids.length - groupByKey.get(a).ids.length || compare(a, b));
      const first = memberships[0] ?? "";
      primary.set(paper.key, first);
      if (!assigned.has(first)) assigned.set(first, []);
      assigned.get(first).push(paper);
    }
    if (assigned.has("")) classified.push({key: "", label: "", ids: assigned.get("").map(paper => paper.key)});
    const ring = classified.flatMap(group => assigned.get(group.key));
    const count = ring.length;
    const paperNodes = ring.map((paper, index) => {
      const angle = -Math.PI * .75 + index * Math.PI * 2 / Math.max(count, 1);
      /* Radial staggering keeps 30–48 nodes on the same network rather than
         switching to category grids, and separates neighboring node labels. */
      const radius = count > 24 && index % 2 ? .82 : 1;
      const groupKeys = tags(paper.topics).filter(label => groupByKey.has(label)).sort(compare);
      return {key: paper.key, x: round(300 + Math.cos(angle) * 230 * radius),
        y: round(270 + Math.sin(angle) * 205 * radius), groupKeys,
        primaryGroupKey: primary.get(paper.key), labelSide: Math.cos(angle) < -.2 ? "left" : Math.cos(angle) > .2 ? "right" : "center"};
    });
    const paperByKey = new Map(paperNodes.map(paper => [paper.key, paper]));
    const halos = classified.map((group, index) => {
      const local = assigned.get(group.key);
      const members = (local.length ? local.map(paper => paper.key) : group.ids).map(id => paperByKey.get(id));
      const x = members.reduce((sum, paper) => sum + paper.x, 0) / members.length;
      const y = members.reduce((sum, paper) => sum + paper.y, 0) / members.length;
      const extentX = Math.max(...members.map(paper => Math.abs(paper.x - x)));
      const extentY = Math.max(...members.map(paper => Math.abs(paper.y - y)));
      return {...group, x: round(x), y: round(y),
        rx: round(clamp(extentX + 46, 62, 250)), ry: round(clamp(extentY + 48, 62, 225)),
        colorIndex: group.key ? index % 6 : -1};
    });
    const hash = value => {
      let result = 2166136261;
      for (const char of value) result = Math.imul(result ^ char.charCodeAt(0), 16777619);
      return result >>> 0;
    };
    const literalMethods = ordered.map(paper => ({...paper, methods: tags(paper.methods)}));
    const displayed = groups(literalMethods, "methods").filter(group => options.singleMethods === true || group.ids.length > 1)
      .sort((a, b) => b.ids.length - a.ids.length || compare(a.key, b.key));
    const occupied = [...paperNodes];
    const methods = displayed.map(method => {
      const members = method.ids.map(id => paperByKey.get(id)), seed = hash(method.key);
      const mx = members.reduce((sum, paper) => sum + paper.x, 0) / members.length;
      const my = members.reduce((sum, paper) => sum + paper.y, 0) / members.length;
      /* Literal membership locates a visual target, not a scientific distance.
         Single-paper methods stay near their paper; shared hubs settle between
         their members. Keyed offsets avoid a mechanically centered circle. */
      const inward = members.length === 1 ? .68 + (seed % 13) / 100 : .60;
      const target = {x: 300 + (mx - 300) * inward + ((seed >>> 4) % 29 - 14),
        y: 270 + (my - 270) * inward + ((seed >>> 12) % 29 - 14)};
      let position = null, best = null, bestClearance = -1;
      /* A bounded deterministic spiral resolves marker collisions. Selection
         never enters this calculation and no source record is modified. */
      for (let step = 0; step < 1024; step++) {
        const angle = (seed % 6283) / 1000 + step * 2.399963229728653;
        const radius = Math.sqrt(step) * 5.5;
        const candidate = {x: round(clamp(target.x + Math.cos(angle) * radius, 50, 550)),
          y: round(clamp(target.y + Math.sin(angle) * radius, 55, 485))};
        const clearance = Math.min(Infinity, ...occupied.map(node => Math.hypot(candidate.x - node.x, candidate.y - node.y)));
        if (clearance > bestClearance) {best = candidate; bestClearance = clearance;}
        if (clearance >= 36) {position = candidate; break;}
      }
      const node = {...method, ids: [...method.ids].sort(compare), ...(position || best)};
      occupied.push(node);
      return node;
    });
    return {width: 600, height: 540, papers: paperNodes, groups: halos, methods};
  }
  function intersection(records, groupKeys, field = "topics") {
    return records.filter(p => groupKeys.every(k => rows(p[field]).includes(k)));
  }
  function local(records, selectedKey) {
    const selected = records.find(p => p.key === selectedKey);
    if (!selected?.methods.length) return [];
    const a = new Set(selected.methods);
    return records.filter(p => p.key !== selectedKey).map(p => {
      const b = new Set(p.methods), shared = [...a].filter(t => b.has(t));
      return {paper: p, similarity: shared.length / new Set([...a, ...b]).size, shared};
    }).filter(r => r.similarity > 0)
      .sort((a, b) => b.similarity - a.similarity || a.paper.key.localeCompare(b.paper.key));
  }
  function filter(records, state = {}) {
    const text = (state.text ?? "").toLocaleLowerCase();
    return records.filter(p => (!text || [p.title, p.work_id, p.version_id, ...p.methods]
      .join(" ").toLocaleLowerCase().includes(text)) &&
      (!state.topic || p.topics.includes(state.topic)) &&
      (!state.method || p.methods.includes(state.method)) &&
      (!state.status || (state.status === "unbound" ? !p.selection : p.selection?.status === state.status)));
  }
  function citation(payload, selectedKeys) {
    const chosen = new Set(selectedKeys);
    const bibliography = payload.index.source_rerun?.bibliography ?? payload.index.bibliography;
    return rows(bibliography?.entries).filter(p => chosen.has(key(p)))
      .map(p => p.bibtex.trimEnd()).join("\n\n");
  }
  const api = {key, tags, papers, stage2Papers, groups, networkLayout, intersection, local, filter, citation};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else host.AtlasModel = api;
})(typeof window === "undefined" ? globalThis : window);
