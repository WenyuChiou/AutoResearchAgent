// Behaviour test for review P1-1..3 / P2-1: with the hidden old copy placed BEFORE the new form in the document,
// the selectors the old save handlers use (real-runtime.js document.querySelector calls) must reach the new form.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');

const source = fs.readFileSync(path.join(__dirname, 'wiki-stage1-ops.js'), 'utf8');
const helper = source.slice(source.indexOf('const wsSharedSelectors'), source.indexOf('const wsPrevAfter'));

// Minimal document: elements in document order, attributes, ancestors, value.
function element(attrs, ancestors, value) {
 const map = new Map(Object.entries(attrs));
 return {map, ancestors, value,
  getAttribute: name => map.get(name), setAttribute: (name, v) => map.set(name, v), removeAttribute: name => map.delete(name),
  closest: sel => { const name = sel.slice(1, -1); return [...ancestors].find(a => a.map.has(name)) || null; }};
}
function documentOf(nodes) {
 const match = (node, sel) => {
  const m = /^\[([\w-]+)(?:="([^"]*)")?\]$/.exec(sel);
  return node.map.has(m[1]) && (m[2] === undefined || node.map.get(m[1]) === m[2]);
 };
 return {querySelectorAll: sel => nodes.filter(n => match(n, sel)), querySelector: sel => nodes.find(n => match(n, sel)) || null};
}

// What each old save handler reads (real-runtime.js:384, 385, 390, 396, 407, 227).
const reads = [
 ['screen', '[data-v7-screen]'], ['screen note', '[data-v7-screen-note]'], ['reading consent', '[data-v7-reading-consent]'],
 ['reading notes', '[data-v7-reading-review]'], ['coverage', '[data-v7-coverage-form]'], ['plan import', '[data-real-plan]'],
 ['claim text', '[data-v7-claim-text="0"]'], ['claim relation', '[data-v7-claim-relation="0"]'], ['claim level', '[data-v7-claim-level="0"]'], ['claim section', '[data-v7-claim-section="0"]']
];

test('every save handler selector reaches the new form even when the hidden old copy comes first', () => {
 const ctx = {};
 vm.createContext(ctx);
 vm.runInContext(helper + ';this.retire = wsRetireOldForms; this.names = wsSharedSelectors;', ctx);
 const hiddenOld = element({'data-local-operations': '1'}, []);
 const newPanel = element({'data-wiki-s1': ''}, []);
 const nodes = [];
 for (const [, sel] of reads) {
  const m = /^\[([\w-]+)(?:="([^"]*)")?\]$/.exec(sel);
  nodes.push(element({[m[1]]: m[2] ?? ''}, [hiddenOld], 'OLD'));
 }
 for (const [, sel] of reads) {
  const m = /^\[([\w-]+)(?:="([^"]*)")?\]$/.exec(sel);
  nodes.push(element({[m[1]]: m[2] ?? ''}, [newPanel], 'NEW'));
 }
 const doc = documentOf(nodes);
 for (const [name, sel] of reads) assert.equal(doc.querySelector(sel).value, 'OLD', 'precondition: old copy is first for ' + name);
 ctx.retire(doc);
 for (const [name, sel] of reads) assert.equal(doc.querySelector(sel).value, 'NEW', name + ' reads the new form');
 assert.equal(nodes.filter(n => n.value === 'OLD' && [...n.map.keys()].some(k => k.endsWith('-retired'))).length, reads.length, 'old copies keep their value under a retired name');
});

test('the retired list covers every selector named in the review', () => {
 const ctx = {};
 vm.createContext(ctx);
 vm.runInContext(helper + ';this.names = wsSharedSelectors;', ctx);
 for (const name of ['data-v7-reading-review', 'data-v7-coverage-form', 'data-real-plan', 'data-v7-screen', 'data-v7-screen-note', 'data-v7-reading-consent',
  'data-v7-claim-text', 'data-v7-claim-relation', 'data-v7-claim-level', 'data-v7-claim-section']) assert.ok(ctx.names.includes(name), name);
});

// Re-review P2: removing the call from the after-render hook must fail a test, so run the real hook.
test('the Stage 1 after-render hook retires the old form copies on every paint', () => {
 const start = source.indexOf('const wsPrevAfter = v7AfterRender;');
 const end = source.indexOf('\n};', start) + 3;
 assert.ok(start >= 0 && end > start);
 const seen = [];
 const el = {querySelector: sel => sel === '[data-wiki-s1]' ? {} : null, querySelectorAll: () => []};
 const ctx = {v7AfterRender: () => {}, wsOpsActive: () => true, wsProgLoad: () => {}, wsHasConsent: () => false,
  wsRetireOldForms: root => seen.push(root)};
 vm.createContext(ctx);
 vm.runInContext(source.slice(start, end) + ';this.after = v7AfterRender;', ctx);
 ctx.after({el});
 assert.deepEqual(seen, [el], 'the hook must call wsRetireOldForms(app.el)');
 seen.length = 0;
 ctx.wsOpsActive = () => false;
 ctx.after({el});
 assert.deepEqual(seen, [], 'pages without the new Stage 1 panel are left alone');
});
