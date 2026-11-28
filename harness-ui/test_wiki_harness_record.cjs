const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const context = vm.createContext({
 esc: value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
});
vm.runInContext((fs.readFileSync(path.join(__dirname, 'wiki-v1-text.js'), 'utf8') + '\n' + fs.readFileSync(path.join(__dirname, 'wiki-harness-record.js'), 'utf8')), context);
const {wikiHarnessRecord, wikiRecordSummary} = context;

assert.equal(wikiRecordSummary(), '这一段还没有运行，没有记录。');
assert.equal(wikiRecordSummary({recordCount:null, blockedCount:-1}), '这一段还没有运行，没有记录。');
const empty = wikiHarnessRecord({checks:[{name:'没有原始记录', result:'不可展示'}]});
assert.match(empty, /这一段还没有运行，没有记录。/);
assert.doesNotMatch(empty, /<details|不可展示|\d+ 次/);

const rendered = wikiHarnessRecord({
 recordCount:1,
 blockedCount:0,
 checks:[{name:'交付检查', result:'已保存', raw:{note:'<script>'}}],
 blocked:{failedCheck:0},
 timeline:[{step:'未保存的步骤', modelCalls:5}]
});
assert.equal(wikiRecordSummary({recordCount:1, blockedCount:0}), '1 条记录 · 拦下 0 次');
assert.match(rendered, /展开明细/);
assert.match(rendered, /交付检查/);
assert.match(rendered, /&lt;script&gt;/);
assert.doesNotMatch(rendered, /<script>|未保存的步骤|模型调用<\/th>/);
assert.equal((rendered.match(/0 次 · 没有发生/g) || []).length, 1);
assert.match(rendered, /超额度<\/th><td>未提供/);
assert.match(rendered, /关掉重开<\/h3>\s*<p>这一段还没有运行，没有记录。/);

const fromCaller = wikiHarnessRecord({summary:'<img src=x onerror=1> 30 篇', checks:[{name:'a', result:'b'}]});
assert.match(fromCaller, /&lt;img src=x onerror=1&gt; 30 篇/);
assert.doesNotMatch(fromCaller, /<img/);

console.log('PASS Harness record: escaped caller summary, empty and partial records, explicit zero, escaped source, no fake timeline.');
