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
  const api = {key, tags, papers, stage2Papers, groups, intersection, local, filter, citation};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else host.AtlasModel = api;
})(typeof window === "undefined" ? globalThis : window);
