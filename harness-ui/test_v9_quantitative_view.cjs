/* Synthetic DOM mechanics only; browser layout and scientific validation are separate. */
'use strict';
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path'), test = require('node:test'), vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, 'v9-quantitative-view.js'), 'utf8');

class Element {
 constructor(ownerDocument, tagName, namespaceURI = null) {
  this.ownerDocument = ownerDocument; this.tagName = tagName; this.namespaceURI = namespaceURI;
  this.children = []; this.attributes = new Map(); this.className = ''; this.style = {}; this.content = ''; this.replacements = 0;
 }
 append(...children) { this.children.push(...children); }
 replaceChildren(...children) { this.content = ''; this.children = children; this.replacements++; }
 setAttribute(key, value) { this.attributes.set(key, String(value)); }
 getAttribute(key) { return this.attributes.get(key) ?? null; }
 set textContent(value) { this.children = []; this.content = String(value); }
 get textContent() { return this.content + this.children.map(child => child.textContent).join(''); }
 set innerHTML(value) { throw new Error('HTML sink used'); }
 set srcdoc(value) { throw new Error('HTML sink used'); }
}
function all(root, predicate) {
 return [root, ...root.children.flatMap(child => all(child, () => true))].filter(predicate);
}
const tagged = (root, tagName) => all(root, node => node.tagName === tagName);
const styled = (root, className) => all(root, node => String(node.className || node.getAttribute('class') || '').split(/\s+/).includes(className));
function mount(model, locale = 'en') {
 const document = {createElement:tag => new Element(document, tag), createElementNS:(namespace, tag) => new Element(document, tag, namespace)};
 const target = document.createElement('main');
 target.append(document.createElement('aside'));
 const forbidden = () => { throw new Error('Renderer attempted an external effect'); };
 const context = vm.createContext({fetch:forbidden, setTimeout:forbidden, setInterval:forbidden});
 vm.runInContext(source, context);
 const root = context.v96MountQuant(target, model, locale);
 assert.equal(target.replacements, 1);
 assert.equal(target.children.length, 1);
 assert.equal(root, target.children[0]);
 return {root, target};
}
function table(id, columns, values) {
 return {id, title:'Table '+id, context:'Recorded context for '+id, columns, notes:['Retain source precision.'], rows:values.map((values, i) => ({id:'row-'+i, values, sources:values.map((_, j) => ({source:'data', pointer:`/${id}/${i}/${j}`}))}))};
}
function fixture() {
 return {
  title:'Recorded quantitative inputs', summary:'Compare the supplied measurements.', question_ref:'question-1',
  sources:[{id:'data', description:'Complete source data; qualification remains unknown.', sha256:'a'.repeat(64), bytes:321}],
  limitations:['Only the recorded groups are represented.', 'The sampling context remains unknown.'],
  tables:[table('bars', [
   {key:'label', label:'Group', type:'text', unit:''},
   {key:'first', label:'First series', type:'number', unit:'recorded units'},
   {key:'second', label:'Second series', type:'number', unit:'recorded units'}
  ], [['First group', -4, 8], ['Second group', 0, null], ['Third group', 0.12345678901234568, 1e-10]]),
  table('heat', [
   {key:'label', label:'Category', type:'text', unit:''},
   {key:'group', label:'Cohort', type:'text', unit:''},
   {key:'value', label:'Share', type:'number', unit:'%'}
  ], [['A', 'One', 0], ['B', 'One', 10], ['A', 'Two', 10], ['B', 'Two', null], ['C', 'Two', 5]])],
  charts:[{type:'bar', title:'Grouped recorded values', table:'bars', label:'label', group:null, values:['first','second']},
   {type:'heatmap', title:'Shares by recorded group', table:'heat', label:'label', group:'group', values:['value']}],
  next_steps:[{pointer:'/question_plans/0/validation', quote:'Compare only the recorded values.\nRetain every open check.'}]
 };
}
function freeze(value) {
 if (value && typeof value === 'object') { Object.values(value).forEach(freeze); Object.freeze(value); }
 return value;
}

test('mounts one pure view without changing the projected input and retains all source text', () => {
 const model = freeze(fixture()), before = JSON.stringify(model);
 const {root} = mount(model);
 assert.equal(JSON.stringify(model), before);
 for (const value of [model.title, model.summary, ...model.limitations, ...model.tables.flatMap(t => [t.context, ...t.notes]), model.sources[0].description, model.sources[0].sha256, model.next_steps[0].quote, model.next_steps[0].pointer]) assert.ok(root.textContent.includes(value));
 assert.equal(root.getAttribute('lang'), 'en');
 assert.ok(root.textContent.includes('they do not establish scientific validation'));
 for (const node of tagged(root, 'svg')) assert.equal(node.namespaceURI, 'http://www.w3.org/2000/svg');
});

test('grouped bars share an actual domain containing zero and retain negative, zero and missing values', () => {
 const {root} = mount(fixture()), axis = styled(root, 'n96-bar-axis')[0];
 assert.equal(axis.getAttribute('data-n96-min'), '-4');
 assert.equal(axis.getAttribute('data-n96-max'), '8');
 const bars = tagged(root, 'rect');
 assert.equal(bars.length, 5);
 assert.deepEqual(bars.map(node => node.getAttribute('data-n96-series')), ['0','1','0','0','1']);
 const negative = bars.find(node => node.getAttribute('data-n96-value') === '-4');
 const positive = bars.find(node => node.getAttribute('data-n96-value') === '8');
 const zero = bars.find(node => node.getAttribute('data-n96-value') === '0');
 assert.equal(Number(negative.getAttribute('x')), 100);
 assert.ok(Math.abs(Number(positive.getAttribute('width')) - 2 * Number(negative.getAttribute('width'))) < 1e-10);
 assert.equal(Number(zero.getAttribute('width')), 0);
 const plots = styled(root, 'n96-bar-plot');
 assert.equal(plots.length, 6);
 assert.equal(tagged(plots[3], 'rect').length, 0);
 assert.ok(plots[3].textContent.includes('Unknown'));
 assert.equal(tagged(plots[0], 'text')[0].getAttribute('text-anchor'), 'end');
 assert.ok(plots.every(plot => styled(plot, 'n96-zero-line')[0].getAttribute('x1') === styled(plots[0], 'n96-zero-line')[0].getAttribute('x1')));
 assert.ok(root.textContent.includes('First series (recorded units)'));
 assert.ok(root.textContent.includes('Second series (recorded units)'));
});

test('single-series bars handle negative-only, zero-only and null-only data without nonfinite geometry', () => {
 for (const values of [[-9,-3], [0,0], [null,null]]) {
  const model = fixture(); model.tables = [table('only', [
   {key:'label',label:'Label',type:'text',unit:''}, {key:'value',label:'Measurement',type:'number',unit:'units'}
  ], values.map((value, i) => ['Row '+i, value]))];
  model.charts = [{type:'bar',title:'Recorded measurements',table:'only',label:'label',group:null,values:['value']}];
  const {root} = mount(model), axis = styled(root, 'n96-bar-axis')[0];
  assert.equal(axis.getAttribute('data-n96-min'), String(Math.min(0, ...values.filter(value => value !== null))));
  assert.equal(axis.getAttribute('data-n96-max'), '0');
  for (const node of all(root, () => true)) for (const [name, value] of node.attributes) if (['x','x1','x2','y','y1','y2','width','height','viewBox'].includes(name)) assert.doesNotMatch(value, /NaN|Infinity|undefined/);
  assert.equal(tagged(root, 'rect').length, values.filter(value => value !== null).length);
  if (values[0] === null) assert.ok(root.textContent.includes('No numeric values are available.'));
 }
});

test('heatmap uses one common scale, full axis labels and explicit unknowns for null and absent combinations', () => {
 const {root} = mount(fixture()), grid = styled(root, 'n96-heatmap-table')[0];
 assert.equal(grid.getAttribute('data-n96-min'), '0'); assert.equal(grid.getAttribute('data-n96-max'), '10');
 const cells = tagged(grid, 'td');
 assert.equal(cells.length, 6);
 assert.equal(styled(grid, 'n96-missing').length, 2);
 assert.ok(styled(grid, 'n96-missing').every(cell => cell.textContent === 'Unknown' && cell.getAttribute('data-n96-value') === null));
 const tens = cells.filter(cell => cell.getAttribute('data-n96-value') === '10');
 assert.equal(tens.length, 2); assert.equal(tens[0].style.backgroundColor, tens[1].style.backgroundColor);
 assert.deepEqual(tagged(grid, 'th').map(cell => cell.textContent), ['Cohort','A','B','C','One','Two']);
 assert.ok(root.textContent.includes('Share (%) · Common scale: 0 – 10'));
 const region = styled(root, 'n96-heatmap')[0];
 assert.equal(region.getAttribute('role'), 'region'); assert.equal(region.getAttribute('tabindex'), '0');
 assert.equal(region.getAttribute('aria-label'), 'Shares by recorded group');
});

test('heatmap numeric labels have at least 4.5 contrast throughout the shared scale', () => {
 const model = fixture(), heat = model.tables[1];
 heat.rows = table('heat', heat.columns, Array.from({length:101}, (_, i) => ['Category '+i, 'One', i])).rows;
 const {root} = mount(model);
 for (const cell of tagged(styled(root, 'n96-heatmap-table')[0], 'td')) {
  const rgb = cell.style.backgroundColor.match(/\d+/g).map(Number).map(value => value / 255).map(value => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2);
  const luminance = rgb.reduce((sum, value, i) => sum + value * [0.2126,0.7152,0.0722][i], 0);
  const ratio = cell.style.color === '#ffffff' ? 1.05 / (luminance + 0.05) : (luminance + 0.05) / 0.05;
  assert.ok(ratio >= 4.5, `Contrast ${ratio} for ${cell.textContent}`);
 }
});

test('complete tables preserve every exact scalar, unit and source pointer inside initially closed disclosures', () => {
 const model = fixture(), {root} = mount(model), grids = styled(root, 'n96-data-table');
 assert.equal(grids.length, model.tables.length);
 for (const [index, grid] of grids.entries()) {
  const input = model.tables[index], body = tagged(grid, 'tbody')[0];
  assert.equal(tagged(body, 'tr').length, input.rows.length);
  assert.equal(tagged(body, 'td').length, input.rows.length * input.columns.length);
  assert.deepEqual(styled(body, 'n96-exact-value').map(node => node.textContent), input.rows.flatMap(row => row.values.map(value => value === null ? 'Unknown' : String(value))));
  assert.deepEqual(styled(body, 'n96-cell-source').map(node => node.textContent), input.rows.flatMap(row => row.sources.map(ref => `Source: ${ref.source} ${ref.pointer}`)));
  for (const column of input.columns) assert.ok(tagged(grid, 'th').some(node => node.textContent === (column.unit ? `${column.label} (${column.unit})` : column.label)));
 }
 assert.ok(root.textContent.includes('0.12345678901234568')); assert.ok(root.textContent.includes('1e-10'));
 assert.equal(tagged(root, 'details').length, model.tables.length + 1);
 assert.ok(tagged(root, 'details').every(node => node.getAttribute('open') === null && node.children[0].tagName === 'summary'));
});

test('bounded complete tables retain all 128 rows and twelve columns without truncation', () => {
 const model = fixture(), columns = Array.from({length:12}, (_, i) => ({key:'c'+i,label:'Full column '+i,type:i ? 'number' : 'text',unit:i ? 'original units' : ''}));
 model.tables = [table('bounded', columns, Array.from({length:128}, (_, i) => Array.from({length:12}, (_, j) => j ? i * 12 + j + 0.123456789 : 'Full row '+i)))];
 model.charts = [{type:'bar',title:'Full recorded rows',table:'bounded',label:'c0',group:null,values:['c1']}];
 const {root} = mount(model), grid = styled(root, 'n96-data-table')[0];
 assert.equal(tagged(tagged(grid, 'tbody')[0], 'tr').length, 128);
 assert.equal(styled(grid, 'n96-exact-value').length, 1536);
 assert.equal(styled(grid, 'n96-cell-source').length, 1536);
 assert.ok(root.textContent.includes('Full row 127')); assert.ok(root.textContent.includes('/bounded/127/11'));
});

test('all authored strings stay inert in DOM text, including malicious labels and quotes', () => {
 const model = fixture(), attack = '<img src=x onerror="unsafe()"> & </svg><script>unsafe()</script>';
 model.title = attack; model.summary = attack; model.limitations = [attack];
 model.sources[0].description = attack; model.next_steps[0] = {quote:attack,pointer:'/question_plans/0/'+attack};
 for (const item of model.tables) {
  item.title = attack; item.context = attack; item.notes = [attack];
  for (const column of item.columns) { column.label = attack; if (column.unit) column.unit = attack; }
  for (const row of item.rows) { row.values = row.values.map(value => typeof value === 'string' ? value + attack : value); for (const ref of row.sources) ref.pointer += attack; }
 }
 model.charts.forEach(chart => { chart.title = attack; });
 const {root} = mount(model);
 assert.ok(root.textContent.includes(attack));
 assert.equal(tagged(root, 'script').length + tagged(root, 'img').length + tagged(root, 'iframe').length, 0);
 for (const node of all(root, () => true)) for (const name of node.attributes.keys()) assert.doesNotMatch(name, /^(?:on|href$|src$|srcdoc$)/i);
});

test('three interface locales preserve original data and verbatim next-step quotes', () => {
 for (const [locale, labels] of Object.entries({en:['Quantitative inputs','Source data and limitations','Unknown','Next steps from the saved plan'], 'zh-TW':['量化輸入','來源資料與限制','未知','已保存規劃的下一步'], 'zh-CN':['量化输入','来源资料与限制','未知','已保存规划的下一步']})) {
  const model = fixture(), {root} = mount(model, locale);
  for (const label of labels) assert.ok(root.textContent.includes(label), `${locale}: ${label}`);
  assert.equal(root.getAttribute('lang'), locale);
  assert.ok(root.textContent.includes('First group')); assert.ok(root.textContent.includes('0.12345678901234568'));
  assert.equal(tagged(styled(root, 'n96-next')[0], 'p')[0].textContent, model.next_steps[0].quote);
 }
 assert.equal(mount(fixture(), 'unsupported').root.getAttribute('lang'), 'en');
});
