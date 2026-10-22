const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const context = {stage2: () => '', v7AfterRender() {}, document: {addEventListener() {}},
  URL, rl: (zh, en) => en, n9UiLabel: value => value,
  rx: value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;').replaceAll('"', '&quot;')};
vm.createContext(context);
for (const file of ['stage2_display.js', 'v9-workbench.js']) {
  vm.runInContext(fs.readFileSync(path.join(__dirname, file), 'utf8'), context, {filename: file});
}

function fixture() {
  const source = {source_id: 'source-1', work_id: 'work-1', version_id: 'v1',
    evidence_level: 'abstract', sha256: 'a'.repeat(64), source_url: 'https://example.org/source'};
  return {packet: {kind: 'Stage2Packet', sources: [source], candidates: [], evidence: [],
    literature: [{work_id: 'work-1', version_id: 'v1', source_ids: ['source-1'],
      title: 'Structured <paper> title', authors: ['Named issuer'], doi: null,
      url: 'https://example.org/literature'}]},
  cards: [{...source, title: 'source-1', authors: [], saved_text: 'Plain saved excerpt.',
    artifact: {sha256: source.sha256}}]};
}
function build(f) { return context.n2BuildModel(f.packet, null, f.cards); }
let cases = 0;
const f = fixture(), before = JSON.stringify(f), model = build(f);
assert.equal(model.sources[0].title, 'Structured <paper> title');
assert.deepEqual(model.sources[0].authors, ['Named issuer']);
assert.equal(model.sources[0].parsed.fields.url, 'https://example.org/source');
assert.equal(model.sources[0].evidence_level, 'abstract');
assert.equal(model.selection.status, 'input-only');
assert.equal(model.sources[0].parsed.fields.doi, undefined);
context.model = model;
const html = vm.runInContext("n2.model=model;n2.papers=['source-1'];n2Papers()", context);
assert.ok(html.includes('Structured &lt;paper&gt; title'));
assert.ok(html.includes('Named issuer'));
assert.ok(html.includes('href="https://example.org/source"'));
assert.ok(html.includes('abstract') && !html.includes('<paper>'));
assert.ok(!html.includes('Verbatim excerpts'), 'do not offer an absent excerpt that renders null');
assert.equal(JSON.stringify(f), before);
cases++;

for (const change of [row => row.work_id = 'other-work', row => row.version_id = 'v2',
  row => row.source_ids = ['other-source'], row => row.source_ids = null]) {
  const wrong = fixture(); change(wrong.packet.literature[0]);
  const item = build(wrong).sources[0];
  assert.equal(item.title, 'source-1'); assert.equal(item.authors, null); cases++;
}
const duplicate = fixture(); duplicate.packet.literature.push({...duplicate.packet.literature[0]});
assert.equal(build(duplicate).sources[0].title, 'source-1'); cases++;
const legacy = fixture();
legacy.cards[0] = {...legacy.cards[0], title: 'Legacy card title', authors: ['Legacy author'],
  url: 'https://example.org/legacy', saved_text: '- title: Parsed title\n- authors: Parsed author\n- url: https://example.org/parsed\n- doi: 10.1234/legacy'};
const old = build(legacy).sources[0];
assert.equal(old.title, 'Legacy card title'); assert.deepEqual(old.authors, ['Legacy author']);
assert.equal(old.parsed.fields.url, 'https://example.org/parsed');
assert.equal(old.parsed.fields.doi, '10.1234/legacy'); cases++;
const parsed = fixture(); parsed.cards[0].saved_text = '- title: Saved title\n- author/issuer: Saved issuer';
assert.equal(build(parsed).sources[0].title, 'Saved title');
assert.equal(build(parsed).sources[0].authors, 'Saved issuer'); cases++;
const link = fixture(); delete link.packet.sources[0].source_url;
link.packet.literature[0].doi = '10.1234/structured';
assert.equal(build(link).sources[0].parsed.fields.url, 'https://example.org/literature');
assert.equal(build(link).sources[0].parsed.fields.doi, '10.1234/structured'); cases++;
const absent = fixture(); delete absent.packet.literature; delete absent.packet.sources[0].source_url;
assert.equal(build(absent).sources[0].title, 'source-1');
assert.equal(build(absent).sources[0].authors, null); cases++;
assert.equal(context.n2Link('javascript:alert(1)', 'Source'), 'Unknown'); cases++;
const withExcerpt = fixture(); withExcerpt.cards[0].saved_text = '## Verbatim excerpts\nSaved quote.\n## Notes\nNotes.';
context.model = build(withExcerpt);
assert.ok(vm.runInContext('n2.model=model;n2Papers()', context).includes('Verbatim excerpts'));
cases++;
console.log(JSON.stringify({kind: 'source-metadata-rendering-regression', cases, failures: 0,
  scientific_reclassification: false, research_execution: false}));
