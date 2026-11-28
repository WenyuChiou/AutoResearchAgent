// An archive saved before Stage 2 (D62) has no Stage 2 result. The page said 「保存的结果没有通过核对」 with an alert,
// as if a check had failed (acceptance M-11). Missing is now said as missing; a real failed check still reads as blocked.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
require('./v1_text_shim.cjs');
const source = fs.readFileSync(path.join(__dirname, 'wiki-stage2.js'), 'utf8');
const cut = (name, until) => { const start = source.indexOf('function ' + name + '('); return source.slice(start, source.indexOf(until, start)); };
let reason = 'stage2-saved-result-missing';
const ctx = vm.createContext({canonicalReadonly:() => true, rt:{savedRun:{payload:{}, binding:{}}}, esc:v => String(v),
 canonicalStage2Validate:() => ({ok:false, reason})});
vm.runInContext(cut('wikiS2ArchiveModel', '\n}\n') + '\n}\n' + cut('wikiS2CompareTab', '\n}\n') + '\n}\n' + cut('wikiS2StatusText', '\n}\n') + '\n}\n', ctx);
let model = ctx.wikiS2ArchiveModel();
assert.equal(model.missing, true);
assert.equal(model.blocked, undefined);
ctx.wikiS2Model = () => model;
assert.match(ctx.wikiS2CompareTab({}, model, {}), /这份归档没有 Stage 2 的结果/);
assert.doesNotMatch(ctx.wikiS2CompareTab({}, model, {}), /没有通过核对|role="alert"/);
assert.match(ctx.wikiS2StatusText({}).now, /没有保存 Stage 2 的结果/);
reason = 'canonical-stage2-binding-differs';
model = ctx.wikiS2ArchiveModel();
assert.equal(model.blocked, 'canonical-stage2-binding-differs', 'a failed check is still blocked');
assert.match(ctx.wikiS2CompareTab({}, model, {}), /保存的结果没有通过核对/);
console.log('PASS archive without a Stage 2 result is said as missing.');
