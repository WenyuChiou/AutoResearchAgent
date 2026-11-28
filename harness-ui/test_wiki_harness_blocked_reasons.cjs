// 「被拦下」 reasons (wiki-harness-record.js): plain Chinese in the body, the raw saved value only in 「技术细节」.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const context = vm.createContext({esc: value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;'), console});
vm.runInContext(fs.readFileSync(path.join(__dirname, 'wiki-harness-record.js'), 'utf8') + '\nthis.__t = {wikiHarnessRecord, wikiRecBlockedReasons, wikiRecBlockedCell, wikiRecBlockedUnknown, wikiRecReason};', context);
const {wikiHarnessRecord, wikiRecBlockedReasons, wikiRecBlockedCell, wikiRecBlockedUnknown, wikiRecReason} = context.__t;
const withoutTech = html => html.replace(/<details class="wiki-record-tech">.*?<\/details>/gs, '').replace(/<[^>]+>/g, ' ');
const code = /[a-z0-9]+(?:-[a-z0-9]+){2,}/;
const render = reasons => wikiHarnessRecord({summary:'x', blocked:{failedCheck:reasons.length}, blockedReasons:{failedCheck:reasons}});

// The classes seen in a real run.
for (const [raw, word] of [['stage1-run-grant-expired', '过期'], ['stage1-run-action-execution-unknown', '不确定'], ['intake-search-request-invalid', '格式不合'],
 ['deadline-exceeded', '时长'], ['stage1-run-grant-stale', '作废'], ['source-worker-required-module-missing', '缺少']]) {
 const html = render([raw]);
 assert.match(withoutTech(html), new RegExp(word), raw + ' is explained in Chinese');
 assert.doesNotMatch(withoutTech(html), code, raw + ' is not shown as body text');
 assert.match(html, /<summary>技术细节<\/summary><code>[^<]*<\/code>/);
 assert.ok(html.includes('<code>' + raw + '</code>'), 'the raw value is kept in the technical details');
}
// Several reasons, a repeated one and an unknown one.
const many = render(['stage1-run-grant-expired', 'stage1-run-grant-expired', 'something-nobody-listed']);
assert.equal((withoutTech(many).match(/运行许可剩余时间不够做这一步/g) || []).length, 1, 'the same explanation is not repeated');
assert.match(withoutTech(many), /被拦下，原因见技术细节/);
assert.doesNotMatch(withoutTech(many), /something-nobody-listed/);
assert.ok(many.includes('something-nobody-listed'), 'unknown raw value still available in the details');
// Free text from the host is escaped and never read as a table key.
for (const key of ['constructor', '__proto__', 'toString', 'hasOwnProperty', 'size', 'get']) {
 assert.equal(wikiRecBlockedCell([key]).startsWith(wikiRecBlockedUnknown), true, key + ' is an unknown code');
 assert.equal(wikiRecReason(key), '原因代码 ' + key, key + ' is not looked up on the prototype');
}
assert.doesNotMatch(wikiRecBlockedCell(['<img src=x onerror=1>']), /<img/);
assert.equal(wikiRecBlockedCell([]), '');

// The table only holds codes the backend really uses (never invented), with Chinese text and no code in the text.
assert.ok(wikiRecBlockedReasons.size >= 40, 'table size ' + wikiRecBlockedReasons.size);
const files = [];
(function walk(dir) {
 for (const entry of fs.readdirSync(dir, {withFileTypes:true})) {
  const full = path.join(dir, entry.name);
  if (entry.isDirectory()) { if (!/node_modules|vendor|^tests?$|__pycache__/.test(entry.name)) walk(full); }
  else if (entry.name.endsWith('.py') && !entry.name.startsWith('test_')) files.push(full);
 }
})(path.join(__dirname, '..'));
if (files.length > 50) {
 const text = files.map(file => fs.readFileSync(file, 'utf8')).join('\n');
 for (const key of wikiRecBlockedReasons.keys()) assert.ok(new RegExp('["\']' + key + '["\']').test(text), key + ' is not a code the backend uses');
}
// Review P2-1: wording that matches the condition the backend really checks.
const said = key => wikiRecBlockedReasons.get(key);
assert.match(said('saved-parser-network-or-process-unavailable'), /解析器尝试联网或起进程，被安全限制拦下/, 'the parser overstepped; the environment is not missing anything');
assert.doesNotMatch(said('saved-parser-network-or-process-unavailable'), /不可用/);
assert.match(said('stage1-run-budget-exceeded'), /没有创建许可/, 'refused at creation, not a used-up grant');
assert.doesNotMatch(said('stage1-run-budget-exceeded'), /超出这份许可/);
for (const key of ['stage1-run-grant-expired', 'source-grant-expired', 'project-expansion-grant-expired', 'project-query-seal-expired', 'project-query-bootstrap-expired']) assert.match(said(key), /剩余时间不够.*已过期/, key + ' may be remaining time, not expiry');
assert.match(said('project-query-bootstrap-requires-reconciliation'), /已有检索作业，或服务正在关闭/);
for (const key of ['stage1-ledger-state-stale', 'stage1-checkpoint-stale', 'stage1-delivery-offer-stale', 'stage1-coverage-offer-stale', 'stage1-agent-pending-work-stale']) assert.match(said(key), /先到操作历史核对这条记录/, key + ' is held until checked');
for (const [key, zh] of wikiRecBlockedReasons) {
 assert.match(zh, /[一-龥]/, key + ' has Chinese text');
 assert.doesNotMatch(zh, code, key + ' text carries no code');
}
console.log('PASS blocked reasons: Chinese body, raw code in technical details, ' + wikiRecBlockedReasons.size + ' codes.');
