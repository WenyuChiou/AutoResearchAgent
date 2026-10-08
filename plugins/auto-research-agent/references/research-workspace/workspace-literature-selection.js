/* Pure work/version selection policy shared by the browser view and Node tests. */
(function (root, factory) {
  "use strict";
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.WorkspaceLiteratureSelection = api;
})(typeof window === "object" ? window : null, function () {
  "use strict";
  const statuses = new Set(["included", "pending", "excluded"]);
  const exactIdentity = value => `${String(value?.work_id ?? "")}\u0000${String(value?.version_id ?? "")}`;
  const paper = record => record?.original || record;

  function create(index, payload) {
    const rows = Array.isArray(payload?.rows) ? payload.rows : [];
    const byIdentity = new Map();
    for (const row of rows) {
      if (!row?.work_id || !row?.version_id || !statuses.has(row.status)) continue;
      const key = exactIdentity(row);
      if (byIdentity.has(key)) throw new Error("duplicate formal-selection identity");
      byIdentity.set(key, Object.freeze({...row, reasons: Object.freeze([...(row.reasons || [])])}));
    }
    const available = Boolean(payload && Array.isArray(payload.rows));
    const defaultScope = available && index?.schema_version === "3.0.0" ? "included" : "all";
    return Object.freeze({
      available,
      defaultScope,
      counts: Object.freeze({...payload?.counts}),
      row(record) { return byIdentity.get(exactIdentity(paper(record))) || null; },
      status(record) { return this.row(record)?.status || "unreviewed"; },
      filter(records, scope) {
        if (!available || scope === "all") return [...records];
        return records.filter(record => this.status(record) === scope);
      },
      citationTarget(scope) {
        if (!available) return null;
        if (scope === "screening") return {href:"./literature/screening.bib", filename:"screening.bib"};
        if (scope === "original") return {href:"./references.bib", filename:"references-original.bib"};
        return {href:"./literature/included.bib", filename:"included.bib"};
      },
    });
  }

  return Object.freeze({create, exactIdentity});
});
