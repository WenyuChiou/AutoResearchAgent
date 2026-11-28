// Stage 1 four counts on a project with no saved delivery: label first, no unit left dangling (acceptance M-7).
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, 'wiki-stage1.js'), 'utf8');
const start = source.indexOf('function wikiS1Metrics(index, state) {'), end = source.indexOf('\n}\n', start) + 3;
const ctx = vm.createContext({wikiS1Check: row => row.relation || 'unchecked'});
vm.runInContext(source.slice(start, end), ctx);
const empty = ctx.wikiS1Metrics(null, {sources:[], groups:[]});
const text = empty.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ');
for (const bad of ['还没有 来源已纳入', '还没有 个需求分组', '还没有 条证据定位', '还没有 证据已核对']) assert.ok(!text.includes(bad), bad);
for (const good of ['来源已纳入 还没有', '证据定位 还没有', '证据已核对 还没有', '需求分组 还没有']) assert.ok(text.includes(good), good);
const filled = ctx.wikiS1Metrics({}, {sources:[{decision:{status:'include'}, claims:[{locator:'p1'}]}], groups:[1, 2]}).replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ');
assert.match(filled, /1 \/ 1 来源已纳入/);
assert.match(filled, /2 个需求分组/);
console.log('PASS empty Stage 1 counts read as 「label 还没有」.');
