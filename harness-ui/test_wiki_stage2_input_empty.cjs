// The Stage 2 candidates tab said 「Stage 2 在等这个课题的 Stage 1 文献包」 while the connection row above it said 「文献包已接收，
// 可以请求生成候选」 (follow-up 3, found while checking the request row). The empty state now follows the continuation answer.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, 'wiki-stage2.js'), 'utf8');
const start = source.indexOf('function wikiS2InputTable() {'), end = source.indexOf('\n}\n', start) + 3;
const make = (state, delivered) => {
 const ctx = vm.createContext({esc: v => String(v), wikiS1Index: () => null, rt: {overview: {stage1: {delivery: {canonical_package: delivered ? {} : null}}}}});
 if (state !== undefined) vm.runInContext('var wikiStage2State = ' + JSON.stringify(state), ctx);
 vm.runInContext(source.slice(start, end), ctx);
 return ctx.wikiS2InputTable().replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ');
};
assert.match(make({result: {status: 'ready'}}, false), /Stage 2 已接收这个课题的文献包，候选还没有生成/);
assert.doesNotMatch(make({result: {status: 'ready'}}, false), /在等/);
assert.match(make(undefined, false), /Stage 2 在等这个课题的 Stage 1 文献包/, 'nothing received: still waiting');
assert.match(make({error: 'stage2-controller-not-connected'}, false), /在等/, 'an error is not a receipt');
assert.match(make({result: {status: 'ready'}}, true), /Stage 1 文献包已交付/, 'a delivered package keeps its own wording');
console.log('PASS Stage 2 empty candidates follow the continuation answer.');
