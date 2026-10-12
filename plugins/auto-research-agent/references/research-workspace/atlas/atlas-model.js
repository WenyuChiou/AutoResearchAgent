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
    const spatial = options.spatial && typeof options.spatial === "object";
    const degrees = (value, limit) => Number.isFinite(value) ? clamp(value, -limit, limit) * Math.PI / 180 : 0;
    const yaw = degrees(options.spatial?.yaw, 18), pitch = degrees(options.spatial?.pitch, 12);
    const project = (point, depth, centerY) => {
      if (!spatial) return point;
      const dx = point.x - 300, dy = point.y - centerY;
      const x = dx * Math.cos(yaw) + depth * Math.sin(yaw);
      const z = -dx * Math.sin(yaw) + depth * Math.cos(yaw);
      const y = dy * Math.cos(pitch) - z * Math.sin(pitch);
      const scale = 1000 / (1000 - dy * Math.sin(pitch) - z * Math.cos(pitch));
      return {x: 300 + x * scale, y: centerY + y * scale};
    };
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
    const hash = value => {
      let result = 2166136261;
      for (const char of value) result = Math.imul(result ^ char.charCodeAt(0), 16777619);
      return result >>> 0;
    };
    const literalMethods = ordered.map(paper => ({...paper, methods: tags(paper.methods)}));
    const allMethods = groups(literalMethods, "methods")
      .sort((a, b) => b.ids.length - a.ids.length || compare(a.key, b.key));
    const sharedByPaper = new Map(ordered.map(paper => [paper.key, allMethods
      .filter(method => method.ids.length > 1 && method.ids.includes(paper.key)).map(method => method.key).join("\n")]));
    assigned.forEach(members => members.sort((a, b) => compare(sharedByPaper.get(a.key), sharedByPaper.get(b.key)) || compare(a.key, b.key)));
    const ring = classified.flatMap(group => assigned.get(group.key)), count = ring.length;
    /* Plan with every literal method, even when some are not displayed, so a
       focus change or visibility toggle cannot move paper/caption positions. */
    let height = Math.max(816, Math.ceil((count * 98 * 74 + classified.length * 142 * 68 + allMethods.length * 48 * 48) / 400));
    const intersects = (a, b, gap = 0) => a.x < b.x + b.width + gap && a.x + a.width + gap > b.x &&
      a.y < b.y + b.height + gap && a.y + a.height + gap > b.y;
    let result;
    for (let attempt = 0; attempt < 3; attempt++) {
      const occupied = [], centerY = height / 2;
      const place = (target, width, boxHeight, topOffset, seed) => {
        let best, bestPenalty = Infinity;
        for (let step = 0; step < 2048; step++) {
          const angle = (seed % 6283) / 1000 + step * 2.399963229728653;
          const radius = Math.sqrt(step) * 10;
          /* The second bounded pass covers the whole canvas rather than
             accepting an overlap when the nearest neighborhood is crowded. */
          const rawX = step < 1024 ? target.x + Math.cos(angle) * radius : 12 + width / 2 + ((step * .754877666 + (seed % 997) / 997) % 1) * (576 - width);
          const rawY = step < 1024 ? target.y + Math.sin(angle) * radius : 12 + topOffset + ((step * .569840291 + (seed % 991) / 991) % 1) * (height - 24 - boxHeight);
          const x = round(clamp(rawX, 12 + width / 2, 588 - width / 2));
          const y = round(clamp(rawY, 12 + topOffset, height - 12 - boxHeight + topOffset));
          const labelBox = {x: round(x - width / 2), y: round(y - topOffset), width, height: boxHeight};
          let penalty = 0;
          for (const other of occupied) if (intersects(labelBox, other, 10)) {
            penalty += Math.max(0, Math.min(labelBox.x + width + 10, other.x + other.width + 10) - Math.max(labelBox.x, other.x)) *
              Math.max(0, Math.min(labelBox.y + boxHeight + 10, other.y + other.height + 10) - Math.max(labelBox.y, other.y));
          }
          if (penalty < bestPenalty) {best = {x, y, labelBox}; bestPenalty = penalty;}
          if (!penalty) break;
        }
        occupied.push(best.labelBox);
        return best;
      };
      const baseTargets = new Map();
      const paperNodes = ring.map((paper, index) => {
        const seed = hash(paper.key), angle = -Math.PI * .75 + index * Math.PI * 2 / Math.max(count, 1);
        const target = {x: 300 + Math.cos(angle) * 230 + seed % 13 - 6,
          y: centerY + Math.sin(angle) * (centerY - 90) + (seed >>> 8) % 15 - 7};
        baseTargets.set(paper.key, target);
        return {key: paper.key, ...place(project(target, seed % 41 - 20, centerY), 88, 64, 15, seed),
          groupKeys: tags(paper.topics).filter(label => groupByKey.has(label)).sort(compare),
          primaryGroupKey: primary.get(paper.key), labelSide: "center"};
      });
      const paperByKey = new Map(paperNodes.map(paper => [paper.key, paper]));
      const halos = classified.map((group, index) => {
        const local = assigned.get(group.key);
        const members = (local.length ? local.map(paper => paper.key) : group.ids).map(id => paperByKey.get(id));
        const x = members.reduce((sum, paper) => sum + paper.x, 0) / members.length;
        const y = members.reduce((sum, paper) => sum + paper.y, 0) / members.length;
        const baseMembers = members.map(paper => baseTargets.get(paper.key));
        const bx = baseMembers.reduce((sum, paper) => sum + paper.x, 0) / baseMembers.length;
        const by = baseMembers.reduce((sum, paper) => sum + paper.y, 0) / baseMembers.length;
        const caption = place(project({x: 300 + (bx - 300) * .58, y: centerY + (by - centerY) * .58}, -40, centerY), 132, 58, 29, hash(group.key));
        return {...group, x: round(x), y: round(y), labelX: caption.x, labelY: caption.y, labelBox: caption.labelBox,
          rx: round(clamp(Math.max(...members.map(paper => Math.abs(paper.x - x))) + 46, 62, 250)),
          ry: round(clamp(Math.max(...members.map(paper => Math.abs(paper.y - y))) + 48, 62, centerY - 18)),
          colorIndex: group.key ? index % 6 : -1};
      });
      const allPlacedMethods = allMethods.map(method => {
        const members = method.ids.map(id => baseTargets.get(id)), seed = hash(method.key);
        const mx = members.reduce((sum, paper) => sum + paper.x, 0) / members.length;
        const my = members.reduce((sum, paper) => sum + paper.y, 0) / members.length;
        const inward = members.length === 1 ? .78 : .60;
        const target = {x: 300 + (mx - 300) * inward + ((seed >>> 4) % 29 - 14),
          y: centerY + (my - centerY) * inward + ((seed >>> 12) % 29 - 14)};
        return {...method, ids: [...method.ids].sort(compare), ...place(project(target, 40, centerY), 38, 38, 13, seed)};
      });
      let labelCollisionCount = 0;
      occupied.forEach((box, index) => occupied.slice(index + 1).forEach(other => {if (intersects(box, other, 6)) labelCollisionCount++;}));
      result = {width: 600, height, papers: paperNodes, groups: halos,
        methods: allPlacedMethods.filter(method => options.singleMethods === true || method.ids.length > 1), labelCollisionCount};
      if (!labelCollisionCount) break;
      height = Math.ceil(height * 1.2);
    }
    return result;
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
