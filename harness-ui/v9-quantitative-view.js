/* Pure presentation of an already validated, source-bound quantitative model. */
function v96MountQuant(target, model, locale = 'en') {
 const doc = target.ownerDocument;
 const language = ['en', 'zh-TW', 'zh-CN'].includes(locale) ? locale : 'en';
 const words = {
  en: { inputs:'Quantitative inputs', limits:'Source data and limitations', boundary:'Charts present the supplied source values; they do not establish scientific validation.', unknown:'Unknown', tables:'Complete data', table:'Complete data and source pointers', rows:'rows', sources:'Complete source files', source:'Source', bytes:'bytes', next:'Next steps from the saved plan', scale:'Common scale', scroll:'Scroll horizontally to read the complete chart.', noValues:'No numeric values are available.' },
  'zh-TW': { inputs:'量化輸入', limits:'來源資料與限制', boundary:'圖表呈現所提供的來源數值；不代表已通過科學驗證。', unknown:'未知', tables:'完整資料', table:'完整資料與來源指標', rows:'列', sources:'完整來源檔案', source:'來源', bytes:'位元組', next:'已保存規劃的下一步', scale:'共同色階', scroll:'可橫向捲動，查看完整圖表。', noValues:'目前沒有可用的數值。' },
  'zh-CN': { inputs:'量化输入', limits:'来源资料与限制', boundary:'图表呈现所提供的来源数值；不代表已通过科学验证。', unknown:'未知', tables:'完整资料', table:'完整资料与来源指针', rows:'行', sources:'完整来源文件', source:'来源', bytes:'字节', next:'已保存规划的下一步', scale:'共同色阶', scroll:'可横向滚动，查看完整图表。', noValues:'目前没有可用的数值。' }
 }[language];
 const palette = ['#397985', '#3365a3', '#8c5c30', '#704a91'];
 const element = (tag, className, text) => {
  const node = doc.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = String(text);
  return node;
 };
 const svgElement = (tag, attrs, text) => {
  const node = doc.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, String(value));
  if (text !== undefined) node.textContent = String(text);
  return node;
 };
 const exact = value => value === null ? words.unknown : String(value);
 const formatted = value => value === null ? words.unknown : new Intl.NumberFormat(language, {
  maximumSignificantDigits:4, ...((Math.abs(value) >= 1e7 || (value !== 0 && Math.abs(value) < 0.001)) ? {notation:'scientific'} : {})
 }).format(value);
 const columnTitle = column => column.unit ? `${column.label} (${column.unit})` : column.label;
 const list = (parent, items) => {
  const ul = element('ul');
  for (const item of items) ul.append(element('li', '', item));
  parent.append(ul);
 };
 const scrollRegion = (label, className) => {
  const region = element('div', `n96-scroll ${className}`);
  region.setAttribute('role', 'region');
  region.setAttribute('aria-label', label);
  region.setAttribute('tabindex', '0');
  return region;
 };
 const root = element('section', 'n96-quant');
 root.setAttribute('lang', language);
 const intro = element('header', 'n96-intro');
 intro.append(element('p', 'n96-eyebrow', words.inputs), element('h2', '', model.title));
 if (model.summary) intro.append(element('p', '', model.summary));
 root.append(intro);
 const limits = element('section', 'n96-limitations');
 limits.append(element('h3', '', words.limits), element('p', 'n96-caption', words.boundary));
 list(limits, model.limitations);
 root.append(limits);

 const tables = new Map(model.tables.map(table => [table.id, table]));
 for (const chart of model.charts) {
  const table = tables.get(chart.table);
  const indexes = new Map(table.columns.map((column, index) => [column.key, index]));
  const labelIndex = indexes.get(chart.label);
  const valueIndexes = chart.values.map(key => indexes.get(key));
  const card = element('section', 'n96-chart');
  card.append(element('h3', '', chart.title));
  if (table.context) card.append(element('p', 'n96-context', table.context));
  card.append(element('p', 'n96-scroll-hint', words.scroll));
  if (chart.type === 'bar') {
   const values = table.rows.flatMap(row => valueIndexes.map(index => row.values[index])).filter(value => value !== null);
   const minimum = Math.min(0, ...values), maximum = Math.max(0, ...values);
   const left = 100, right = 500, width = 600;
   const x = value => minimum === maximum ? left : left + (value - minimum) / (maximum - minimum) * (right - left);
   const zero = x(0);
   const legend = element('ul', 'n96-legend');
   valueIndexes.forEach((index, series) => {
    const item = element('li');
    const swatch = element('span', 'n96-swatch');
    swatch.style.backgroundColor = palette[series];
    swatch.setAttribute('aria-hidden', 'true');
    item.append(swatch, element('span', '', columnTitle(table.columns[index])));
    legend.append(item);
   });
   card.append(legend);
   const region = scrollRegion(chart.title, 'n96-bars');
   const axis = svgElement('svg', {class:'n96-bar-axis', viewBox:`0 0 ${width} 38`, width, height:38, 'aria-hidden':'true', focusable:'false', 'data-n96-min':minimum, 'data-n96-max':maximum});
   axis.append(svgElement('line', {x1:left, x2:right, y1:28, y2:28, class:'n96-axis-line'}));
   for (const tick of [...new Set([minimum, 0, maximum])]) {
    axis.append(svgElement('line', {x1:x(tick), x2:x(tick), y1:24, y2:32, class:'n96-axis-line'}));
    axis.append(svgElement('text', {x:x(tick), y:18, 'text-anchor':'middle', class:'n96-axis-text'}, formatted(tick)));
   }
   region.append(axis);
   if (!values.length) card.append(element('p', 'n96-caption', words.noValues));
   for (const row of table.rows) {
    const group = element('div', 'n96-bar-group');
    group.append(element('h4', '', row.values[labelIndex]));
    valueIndexes.forEach((index, series) => {
     const value = row.values[index], column = table.columns[index];
     const entry = element('div', 'n96-bar-entry');
     entry.append(element('p', 'n96-series-label', columnTitle(column)));
     const svg = svgElement('svg', {class:'n96-bar-plot', viewBox:`0 0 ${width} 36`, width, height:36, role:'img', 'aria-label':`${row.values[labelIndex]} · ${columnTitle(column)}: ${exact(value)}`, focusable:'false'});
     svg.append(svgElement('line', {x1:zero, x2:zero, y1:2, y2:34, class:'n96-zero-line'}));
     if (value !== null) {
      svg.append(svgElement('rect', {x:Math.min(zero, x(value)), y:9, width:Math.abs(x(value) - zero), height:18, rx:2, fill:palette[series], 'data-n96-value':String(value), 'data-n96-series':series}));
     }
     svg.append(svgElement('text', {x:value === null ? left : x(value) + (value < 0 ? -8 : 8), y:24, 'text-anchor':value !== null && value < 0 ? 'end' : 'start', class:value === null ? 'n96-value-text n96-unknown' : 'n96-value-text'}, formatted(value)));
     entry.append(svg);
     group.append(entry);
    });
    region.append(group);
   }
   card.append(region);
  } else {
   const groupIndex = indexes.get(chart.group), valueIndex = valueIndexes[0];
   const labels = [...new Set(table.rows.map(row => row.values[labelIndex]))];
   const groups = [...new Set(table.rows.map(row => row.values[groupIndex]))];
   const cells = new Map();
   for (const row of table.rows) {
    const group = row.values[groupIndex];
    if (!cells.has(group)) cells.set(group, new Map());
    cells.get(group).set(row.values[labelIndex], row.values[valueIndex]);
   }
   const values = table.rows.map(row => row.values[valueIndex]).filter(value => value !== null);
   const minimum = values.length ? Math.min(...values) : null, maximum = values.length ? Math.max(...values) : null;
   const unit = table.columns[valueIndex].unit;
   card.append(element('p', 'n96-scale', `${columnTitle(table.columns[valueIndex])} · ${words.scale}: ${formatted(minimum)} – ${formatted(maximum)}`));
   const region = scrollRegion(chart.title, 'n96-heatmap');
   const grid = element('table', 'n96-heatmap-table');
   if (minimum !== null) {
    grid.setAttribute('data-n96-min', String(minimum));
    grid.setAttribute('data-n96-max', String(maximum));
   }
   grid.append(element('caption', '', `${table.columns[groupIndex].label} / ${table.columns[labelIndex].label} · ${columnTitle(table.columns[valueIndex])}`));
   const head = element('thead'), heading = element('tr');
   const corner = element('th', '', table.columns[groupIndex].label);
   corner.setAttribute('scope', 'col');
   heading.append(corner);
   for (const label of labels) {
    const cell = element('th', '', label);
    cell.setAttribute('scope', 'col');
    heading.append(cell);
   }
   head.append(heading);
   const body = element('tbody');
   for (const group of groups) {
    const row = element('tr'), heading = element('th', '', group);
    heading.setAttribute('scope', 'row');
    row.append(heading);
    for (const label of labels) {
     const value = cells.get(group).get(label) ?? null;
     const cell = element('td', value === null ? 'n96-missing' : '', formatted(value));
     cell.setAttribute('aria-label', `${group} · ${label}: ${exact(value)} ${unit}`);
     if (value !== null) {
      const fraction = maximum === minimum ? 0.5 : (value - minimum) / (maximum - minimum);
      const rgb = [237,245,248].map((light, index) => Math.round(light + ([36,87,116][index] - light) * fraction));
      const luminance = rgb.map(channel => channel / 255).map(channel => channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2).reduce((sum, channel, index) => sum + channel * [0.2126,0.7152,0.0722][index], 0);
      cell.style.backgroundColor = `rgb(${rgb.join(', ')})`;
      cell.style.color = luminance > 0.179 ? '#000000' : '#ffffff';
      cell.setAttribute('data-n96-value', String(value));
     }
     row.append(cell);
    }
    body.append(row);
   }
   grid.append(head, body);
   region.append(grid);
   card.append(region);
  }
  root.append(card);
 }

 const complete = element('section', 'n96-complete');
 complete.append(element('h3', '', words.tables));
 for (const table of model.tables) {
  const details = element('details', 'n96-details');
  details.append(element('summary', '', `${table.title} · ${words.table} (${table.rows.length} ${words.rows})`));
  if (table.context) details.append(element('p', 'n96-context', table.context));
  const region = scrollRegion(table.title, 'n96-table-scroll');
  const grid = element('table', 'n96-data-table');
  grid.append(element('caption', '', table.title));
  const head = element('thead'), heading = element('tr');
  for (const column of table.columns) {
   const cell = element('th', '', columnTitle(column));
   cell.setAttribute('scope', 'col');
   heading.append(cell);
  }
  head.append(heading);
  const body = element('tbody');
  for (const row of table.rows) {
   const entry = element('tr');
   row.values.forEach((value, index) => {
    const cell = element('td', table.columns[index].type === 'number' ? 'n96-number' : '');
    cell.append(element('span', 'n96-exact-value', exact(value)));
    const trace = row.sources[index];
    cell.append(element('code', 'n96-cell-source', `${words.source}: ${trace.source} ${trace.pointer}`));
    entry.append(cell);
   });
   body.append(entry);
  }
  grid.append(head, body);
  region.append(grid);
  details.append(region);
  if (table.notes.length) list(details, table.notes);
  complete.append(details);
 }
 root.append(complete);

 const next = element('section', 'n96-next');
 next.append(element('h3', '', words.next));
 for (const step of model.next_steps) {
  const quote = element('blockquote');
  quote.append(element('p', '', step.quote), element('cite', '', step.pointer));
  next.append(quote);
 }
 root.append(next);
 const sources = element('details', 'n96-details n96-sources');
 sources.append(element('summary', '', `${words.sources} (${model.sources.length})`));
 for (const source of model.sources) {
  const entry = element('article');
  entry.append(element('h4', '', source.id), element('p', '', source.description), element('code', '', `SHA-256: ${source.sha256}`), element('p', 'n96-caption', `${source.bytes} ${words.bytes}`));
  sources.append(entry);
 }
 root.append(sources);
 target.replaceChildren(root);
 return root;
}
