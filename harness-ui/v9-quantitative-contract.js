// A display-only, closed projection of hash-verified JSON materials.
const v96Id = value => typeof value === 'string' && /^[a-z][a-z0-9_-]{0,40}$/.test(value);
function v96Need(ok, reason) { if (!ok) throw Error('quantitative-guide-' + reason); }
function v96Shape(value, fields) { return v94Object(value, fields); }
function v96Texts(values, maxItems, maxLength, minimum = 0) {
 return Array.isArray(values) && values.length >= minimum && values.length <= maxItems &&
  values.every(value => v94Text(value, maxLength));
}
function v96QuantName(view, revision = null) {
 const binding = v94PlanBinding(view, revision);
 return binding ? 'stage3-quantitative-' + (revision ? binding.revision_receipt_sha256 : binding.plan_manifest_sha256) + '.json' : null;
}
function v96Material(catalog, project, name, bytesLimit, expected = null) {
 v96Need(Array.isArray(catalog?.materials) && catalog.materials.length <= 1000, 'catalog');
 const matches = catalog.materials.filter(item => item.project_ref === project && item.stage === 3 && item.name === name);
 if (!matches.length && expected === null) return null;
 v96Need(matches.length === 1, 'material-ambiguous-or-missing');
 const item = matches[0];
 v96Need(item.kind === 'manual-file' && item.status === 'registered' && /^file-[a-f0-9]{32}$/.test(item.id) &&
  v94Pin(item.sha256) && Number.isSafeInteger(item.bytes) && item.bytes > 0 && item.bytes <= bytesLimit, 'material');
 if (expected) v96Need(item.sha256 === expected.sha256 && item.bytes === expected.bytes, 'source-binding');
 return item;
}
function v96ChooseQuant(catalog, view, revision = null) {
 const name = v96QuantName(view, revision);
 v96Need(name, 'view-binding');
 return v96Material(catalog, view.project_ref, name, 131072);
}
function v96Pointer(value, pointer) {
 v96Need(typeof pointer === 'string' && pointer.startsWith('/') && pointer.length <= 256, 'pointer');
 const segments = pointer.slice(1).split('/');
 v96Need(segments.length <= 16, 'pointer-depth');
 for (const encoded of segments) {
  v96Need(!/~(?:[^01]|$)/.test(encoded), 'pointer-escape');
  const key = encoded.replace(/~1/g, '/').replace(/~0/g, '~');
  v96Need(!['__proto__','prototype','constructor'].includes(key) && value !== null && typeof value === 'object' &&
   Object.hasOwn(value, key) && (!Array.isArray(value) || /^(0|[1-9][0-9]*)$/.test(key)), 'pointer-unavailable');
  value = value[key];
 }
 return value;
}
function v96ValidateQuant(guide, view, revision = null) {
 const binding = v94PlanBinding(view, revision);
 const fields = ['kind','version','project_ref','input_version','direction_intent_sha256','plan_manifest_sha256',
  'question_ref','title','summary','sources','tables','charts','next_steps','limitations'];
 if (revision) fields.push('revision_receipt_sha256','revision_number');
 v96Need(binding && v96Shape(guide, fields) && guide.kind === 'Stage3QuantitativePresentation' && guide.version === 1, 'shape');
 v96Need(/^project-[a-f0-9]{32}$/.test(binding.project_ref) && Number.isSafeInteger(binding.input_version) &&
  binding.input_version > 0 && Object.keys(binding).every(key => guide[key] === binding[key]), 'binding');
 const plan = revision ? revision.record.plan : view.plan;
 const questions = plan.question_plans.filter(row => row.question_ref === guide.question_ref);
 v96Need(questions.length === 1 && v94Text(guide.question_ref, 240), 'question');
 v96Need(v94Text(guide.title, 200) && v94Text(guide.summary, 1000) && v96Texts(guide.limitations, 16, 600, 1), 'description');
 v96Need(Array.isArray(guide.sources) && guide.sources.length > 0 && guide.sources.length <= 4, 'sources');
 const sourceIds = new Set(); let sourceBytes = 0;
 for (const source of guide.sources) {
  v96Need(v96Shape(source, ['id','sha256','bytes','description']) && v96Id(source.id) && !sourceIds.has(source.id) &&
   v94Pin(source.sha256) && Number.isSafeInteger(source.bytes) && source.bytes > 0 && source.bytes <= 524288 &&
   v94Text(source.description, 600), 'source');
  sourceIds.add(source.id); sourceBytes += source.bytes;
 }
 v96Need(sourceBytes <= 1048576, 'source-capacity');
 v96Need(Array.isArray(guide.tables) && guide.tables.length > 0 && guide.tables.length <= 8, 'tables');
 const tableIds = new Set(); let cellCount = 0;
 for (const table of guide.tables) {
  v96Need(v96Shape(table, ['id','title','context','columns','rows','notes']) && v96Id(table.id) && !tableIds.has(table.id) &&
   v94Text(table.title, 200) && v94Text(table.context, 1000) && v96Texts(table.notes, 12, 600), 'table');
  tableIds.add(table.id);
  v96Need(Array.isArray(table.columns) && table.columns.length > 0 && table.columns.length <= 12, 'columns');
  const columns = new Set();
  for (const column of table.columns) {
   v96Need(v96Shape(column, ['key','label','type','unit']) && v96Id(column.key) && !columns.has(column.key) &&
    v94Text(column.label, 200) && ['text','number'].includes(column.type) && typeof column.unit === 'string' &&
    column.unit.length <= 160 && (column.type !== 'number' || column.unit.trim()), 'column');
   columns.add(column.key);
  }
  v96Need(Array.isArray(table.rows) && table.rows.length > 0 && table.rows.length <= 128, 'rows');
  const rowIds = new Set();
  for (const row of table.rows) {
   v96Need(v96Shape(row, ['id','cells']) && v96Id(row.id) && !rowIds.has(row.id) && Array.isArray(row.cells) &&
    row.cells.length === table.columns.length, 'row');
   rowIds.add(row.id); cellCount += row.cells.length;
   for (const cell of row.cells) v96Need(v96Shape(cell, ['source','pointer']) && sourceIds.has(cell.source) &&
    typeof cell.pointer === 'string' && cell.pointer.startsWith('/') && cell.pointer.length <= 256, 'cell');
  }
 }
 v96Need(cellCount <= 2048, 'cell-capacity');
 v96Need(Array.isArray(guide.charts) && guide.charts.length > 0 && guide.charts.length <= 6, 'charts');
 for (const chart of guide.charts) {
  v96Need(v96Shape(chart, ['type','title','table','label','group','values']) && ['bar','heatmap'].includes(chart.type) &&
   v94Text(chart.title, 200) && tableIds.has(chart.table) && Array.isArray(chart.values) && chart.values.length > 0 &&
   chart.values.length <= 4 && new Set(chart.values).size === chart.values.length, 'chart');
  const table = guide.tables.find(item => item.id === chart.table), cols = new Map(table.columns.map(column => [column.key, column]));
  v96Need(cols.get(chart.label)?.type === 'text' && chart.values.every(key => cols.get(key)?.type === 'number'), 'chart-columns');
  if (chart.type === 'bar') v96Need(chart.group === null && new Set(chart.values.map(key => cols.get(key).unit)).size === 1, 'bar-units');
  else v96Need(chart.values.length === 1 && chart.group !== chart.label && cols.get(chart.group)?.type === 'text', 'heatmap-columns');
 }
 v96Need(Array.isArray(guide.next_steps) && guide.next_steps.length > 0 && guide.next_steps.length <= 6, 'next-steps');
 const index = plan.question_plans.indexOf(questions[0]), prefix = '/question_plans/' + index + '/';
 for (const step of guide.next_steps) {
  v96Need(v96Shape(step, ['pointer','quote']) && v94Text(step.quote, 2200) && typeof step.pointer === 'string' &&
   step.pointer.startsWith(prefix), 'step-source');
  v96Need(/^(method|materials|design|analysis|validation|interpretation|minimum_deliverable|unknowns\/(0|[1-9][0-9]?))$/.test(step.pointer.slice(prefix.length)), 'step-pointer');
  const text = v96Pointer(plan, step.pointer);
  v96Need(typeof text === 'string' && text.includes(step.quote), 'step-quote');
 }
 return guide;
}
function v96SourceMaterials(catalog, guide) {
 return new Map(guide.sources.map(source => [source.id, v96Material(catalog, guide.project_ref,
  'stage3-quant-source-' + source.sha256 + '.json', 524288, source)]));
}
function v96ProjectQuant(guide, documents) {
 const tables = guide.tables.map(table => ({...table, rows:table.rows.map(row => ({id:row.id,
  sources:row.cells.map(cell => ({...cell})), values:row.cells.map((cell, index) => {
   v96Need(documents.has(cell.source), 'source-unavailable');
   const value = v96Pointer(documents.get(cell.source), cell.pointer), type = table.columns[index].type;
   v96Need(type === 'text' ? v94Text(value, 240) : value === null ||
    (typeof value === 'number' && Number.isFinite(value) && Math.abs(value) <= 1e15), 'cell-type');
   return value;
  })}))}));
 for (const chart of guide.charts) {
  const table = tables.find(item => item.id === chart.table), indices = new Map(table.columns.map((column, index) => [column.key, index]));
  const keys = new Set();
  for (const row of table.rows) {
   const key = JSON.stringify(chart.type === 'bar' ? [row.values[indices.get(chart.label)]] :
    [row.values[indices.get(chart.label)], row.values[indices.get(chart.group)]]);
   v96Need(!keys.has(key), 'chart-duplicate-labels'); keys.add(key);
  }
 }
 return {...guide, binding:Object.fromEntries(['project_ref','input_version','direction_intent_sha256','plan_manifest_sha256',
  'revision_receipt_sha256','revision_number'].filter(key => Object.hasOwn(guide, key)).map(key => [key, guide[key]])), tables};
}
