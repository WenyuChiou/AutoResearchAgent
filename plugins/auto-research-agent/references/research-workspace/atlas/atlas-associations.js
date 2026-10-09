/* Read-only associations over saved records. Lexical proximity is not a citation,
   verified claim, evidence strength, or an inferred research classification. */
(function (host) {
  "use strict";
  const compare = (a, b) => a < b ? -1 : a > b ? 1 : 0;
  const rows = value => Array.isArray(value) ? value : [];
  const key = paper => JSON.stringify([paper.work_id, paper.version_id]);
  const tags = value => [...new Set((Array.isArray(value) ? value : [value]).filter(value =>
    typeof value === "string" && value.trim() && !/^(unknown|unverified|not recorded|not independently assessed)(\b|\s|$)/i.test(value.trim()) &&
    !["未知", "未记录", "未記錄", "未验证", "未驗證"].includes(value.trim())))].sort(compare);
  const stop = new Set(("a an and are as at be been being but by can could did do does doing for from had has have " +
    "he her here hers him his how i if in into is it its itself may me might more most must my no nor not of on " +
    "once only or other our ours out over own same she should so some such than that the their theirs them " +
    "themselves then there these they this those through to too under up us very was we were what when where " +
    "which while who whom why will with would you your also across after around based before both each et al " +
    "including include includes rather use uses used using via within without work works paper papers research " +
    "study studies results result evidence source sources support supports supported saved recorded audit claim " +
    "claims stage topic relevance unknown unverified unconfirmed selected proposed supplies provides provide " +
    "describe describes show shows establish establishes version bound actual one two three first second " +
    "third cannot needed need necessary particular different important specific general new well whether against " +
    "assertion assertions compound partial confirmed confirms independently assessed assessment premise closest found").split(/\s+/));
  const fields = ["question", "data", "method", "main_findings", "relevance", "transferability"];
  function tokens(value) {
    if (typeof value !== "string") return [];
    const text = value.toLowerCase().replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, " ")
      .replace(/<[^>]*>/g, " ").replace(/https?:\/\/\S+/g, " ");
    const found = [];
    for (const word of text.match(/[a-z][a-z0-9]{1,47}/g) || []) {
      const singular = word.length > 4 && /s$/.test(word) && !/(ss|is|us)$/.test(word) && !["series", "species"].includes(word) ?
        /ies$/.test(word) ? word.slice(0, -3) + "y" : word.slice(0, -1) : word;
      if (!stop.has(word) && !stop.has(singular)) found.push(singular);
    }
    for (const run of text.match(/\p{Script=Han}+/gu) || []) {
      const chars = [...run];
      for (let i = 0; i + 1 < chars.length; i++) found.push(chars[i] + chars[i + 1]);
    }
    return found;
  }
  function features(paper) {
    const text = fields.map(field => {
      if (typeof paper.findings?.[field] === "string") return paper.findings[field];
      const cell = paper.cells?.[field === "main_findings" ? "findings" : field];
      // Stage 2's retained cells name their bound canonical findings field.
      return typeof cell?.field === "string" && cell.field.endsWith(`.findings.${field}`) ? cell.text : null;
    }).filter(value => typeof value === "string")
      .map(value => value.replace(/^Saved Stage 1 topic relevance:\s*/i, "")
        .replace(/^Saved Stage 1 assertion; compound audit=[^;]+; not a confirmed premise:\s*/i, "")
        .replace(/^Saved independent compound-claim audit:\s*[^.]+\.\s*/i, ""))
      .filter(value => !/^No .* direction is selected; source support does not validate /i.test(value));
    return [...new Set(text)].flatMap(tokens).concat(tags(paper.topics ?? paper.classification?.topic_cluster).flatMap(tokens));
  }
  function endpoint(type, value) { return {type, key: value}; }
  function pair(a, b, kind, basis, details) {
    const ordered = [a, b].sort((a, b) => compare(JSON.stringify(a), JSON.stringify(b)));
    return {from: ordered[0], to: ordered[1], kind, basis, ...details};
  }
  const identity = link => JSON.stringify([link.from, link.to, link.kind]);
  const order = links => links.sort((a, b) => compare(identity(a), identity(b)));
  function normalized(records) {
    const found = new Map();
    for (const paper of rows(records)) {
      if (typeof paper?.work_id !== "string" || typeof paper?.version_id !== "string") continue;
      const canonical = key(paper);
      if (!found.has(canonical)) found.set(canonical, {...paper, key: canonical,
        topics: tags(paper.topics ?? paper.classification?.topic_cluster),
        methods: tags(paper.methods ?? paper.classification?.method)});
    }
    return [...found.values()].sort((a, b) => compare(a.key, b.key));
  }
  function recorded(records) {
    const papers = normalized(records), links = [], topics = new Map();
    for (const paper of papers) for (const label of paper.topics) {
      if (!topics.has(label)) topics.set(label, []);
      topics.get(label).push(paper.key);
    }
    const groups = [...topics].sort(([a], [b]) => compare(a, b));
    for (let i = 0; i < groups.length; i++) for (let j = i + 1; j < groups.length; j++) {
      const shared = groups[i][1].filter(id => groups[j][1].includes(id));
      if (shared.length) links.push(pair(endpoint("topic", groups[i][0]), endpoint("topic", groups[j][0]),
        "recorded-topic-overlap", "shared-paper-membership", {score: shared.length, count: shared.length,
          shared_terms: [], shared_papers: shared}));
    }
    for (let i = 0; i < papers.length; i++) for (let j = i + 1; j < papers.length; j++) {
      const sharedTopics = papers[i].topics.filter(label => papers[j].topics.includes(label));
      const sharedMethods = papers[i].methods.filter(label => papers[j].methods.includes(label));
      if (sharedTopics.length || sharedMethods.length) links.push(pair(endpoint("paper", papers[i].key),
        endpoint("paper", papers[j].key), "recorded-paper-overlap", "shared-literal-topics-or-methods",
        {score: sharedTopics.length + sharedMethods.length, count: sharedTopics.length + sharedMethods.length,
          shared_terms: [...new Set([...sharedTopics, ...sharedMethods])].sort(compare),
          shared_topics: sharedTopics, shared_methods: sharedMethods}));
    }
    return order(links);
  }
  function lexicalPairs(documents, options, kind) {
    const count = documents.length;
    const threshold = Number.isFinite(options.threshold) ? Math.min(1, Math.max(0, options.threshold)) : .12;
    const neighbors = Number.isInteger(options.neighbors) ? Math.min(4, Math.max(0, options.neighbors)) : 2;
    const frequencies = documents.map(document => {
      const result = new Map();
      for (const term of document.features) result.set(term, (result.get(term) || 0) + 1);
      return result;
    });
    const documentFrequency = new Map();
    for (const frequency of frequencies) for (const term of frequency.keys()) {
      documentFrequency.set(term, (documentFrequency.get(term) || 0) + 1);
    }
    const vectors = frequencies.map(frequency => {
      const vector = new Map();
      for (const [term, occurrences] of frequency) {
        const weight = (1 + Math.log(occurrences)) * (1 + Math.log((count + 1) / (documentFrequency.get(term) + 1)));
        if (weight) vector.set(term, weight);
      }
      return {vector, norm: Math.hypot(...vector.values())};
    });
    const candidates = [], byNode = new Map(documents.map(document => [document.node.key, []]));
    for (let i = 0; i < count; i++) for (let j = i + 1; j < count; j++) {
      const shared = [...vectors[i].vector].filter(([term]) => vectors[j].vector.has(term))
        .map(([term, weight]) => [term, weight * vectors[j].vector.get(term)])
        .sort((a, b) => b[1] - a[1] || compare(a[0], b[0]));
      const dot = shared.reduce((sum, [, weight]) => sum + weight, 0);
      const score = vectors[i].norm && vectors[j].norm ? dot / (vectors[i].norm * vectors[j].norm) : 0;
      if (score <= 0 || score < threshold) continue;
      const link = pair(documents[i].node, documents[j].node,
        kind, kind === "lexical-topic" ? "tf-idf-topic-aggregate-v1" : "tf-idf-cosine-v1", {score: Math.round(Math.min(1, score) * 1000000) / 1000000,
          shared_terms: shared.slice(0, 6).map(([term]) => term)});
      candidates.push(link); byNode.get(documents[i].node.key).push(link); byNode.get(documents[j].node.key).push(link);
    }
    const chosen = new Set();
    for (const links of byNode.values()) {
      links.sort((a, b) => b.score - a.score || compare(identity(a), identity(b)));
      links.slice(0, neighbors).forEach(link => chosen.add(identity(link)));
    }
    return order(candidates.filter(link => chosen.has(identity(link))));
  }
  function lexical(records, options = {}) {
    return lexicalPairs(normalized(records).map(paper => ({node: endpoint("paper", paper.key), features: features(paper)})),
      options, "lexical-content");
  }
  function lexicalTopics(records, options = {}) {
    const groups = new Map();
    for (const paper of normalized(records)) for (const topic of paper.topics) {
      if (!groups.has(topic)) groups.set(topic, []);
      groups.get(topic).push(paper);
    }
    const documents = [...groups].sort(([a], [b]) => compare(a, b))
      .map(([topic, members]) => ({node: endpoint("topic", topic), features: members.flatMap(features)}));
    return lexicalPairs(documents, options, "lexical-topic").map(link => ({...link,
      source_members: {from: groups.get(link.from.key).map(paper => paper.key), to: groups.get(link.to.key).map(paper => paper.key)},
      source_fields: [...fields]}));
  }
  function build(records, options = {}) {
    return {recorded: recorded(records), lexical: lexical(records, options), lexicalTopics: lexicalTopics(records, options)};
  }
  function related(records, paperKey, options = {}) {
    const papers = normalized(records), byKey = new Map(papers.map(paper => [paper.key, paper]));
    if (!byKey.has(paperKey)) return [];
    const settings = {neighbors: 2, threshold: .09, ...options}, found = new Map();
    const links = [...recorded(papers), ...(settings.computed !== false ? lexical(papers, settings) : [])];
    for (const link of links) {
      if (link.from.type !== "paper" || link.to.type !== "paper") continue;
      const other = link.from.key === paperKey ? link.to.key : link.to.key === paperKey ? link.from.key : null;
      if (other === paperKey || !byKey.has(other)) continue;
      if (!found.has(other)) found.set(other, {paper: byKey.get(other), shared_topics: [], shared_methods: [], lexical: null});
      const entry = found.get(other);
      if (link.kind === "recorded-paper-overlap") {
        entry.shared_topics = [...new Set([...entry.shared_topics, ...rows(link.shared_topics)])].sort(compare);
        entry.shared_methods = [...new Set([...entry.shared_methods, ...rows(link.shared_methods)])].sort(compare);
      } else if (link.kind === "lexical-content") {
        entry.lexical = {score: link.score, shared_terms: [...link.shared_terms], basis: link.basis};
      }
    }
    const sharedCount = entry => entry.shared_topics.length + entry.shared_methods.length;
    return [...found.values()].sort((a, b) =>
      Number(sharedCount(b) > 0) - Number(sharedCount(a) > 0) || sharedCount(b) - sharedCount(a) ||
      (b.lexical?.score || 0) - (a.lexical?.score || 0) || compare(a.paper.key, b.paper.key));
  }
  const api = {key, tokens, features, recorded, lexical, lexicalTopics, build, related};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else host.AtlasAssociations = api;
})(typeof window === "undefined" ? globalThis : window);
