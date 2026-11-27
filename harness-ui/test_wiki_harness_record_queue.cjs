const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

// Queued reads follow the page: a wish whose block is no longer shown is cancelled, never sent.
const A = 'project-aaaa1111', B = 'project-bbbb2222';
const calls = [], pending = [];
const shown = new Set(); // 'ref|stage' blocks currently in the page
const apps = [{lang:'zh', page:'workspace', el:{querySelector: selector => {
 const m = /data-wiki-record-stage="(\d)"\]\[data-wiki-record-ref="([^"]+)"/.exec(selector);
 return m && shown.has(m[2] + '|' + m[1]) ? {} : null;
}}}];
const context = vm.createContext({
 esc: value => String(value), rt: {ref:B}, apps,
 projectPath: (ref, tail) => '/api/projects/' + ref + '/' + tail,
 liveRequest: (...args) => new Promise((resolve, reject) => { calls.push(args[0]); pending.push({resolve, reject}); }),
 setTimeout: () => 0, clearTimeout: () => {}
});
vm.runInContext(fs.readFileSync(path.join(__dirname, 'wiki-harness-record.js'), 'utf8'), context);
const {wikiRecEnsure} = context;
const tick = () => new Promise(resolve => setImmediate(resolve));
const answer = (ref, stage) => ({kind:'HarnessRecordSummary', project_ref:ref, read_only:true, stages:{[stage]:{status:'not-run', blocked:[], blocked_total:0}}});
const settle = async (index, value) => { pending[index].resolve(value); await tick(); await tick(); };
const has = key => vm.runInContext(`wikiRecStore.has(${JSON.stringify(key)})`, context);

(async () => {
 // A1: Stage 1 read in flight, a Stage 2 read queued behind it, then the user is back on Stage 1.
 shown.add(B + '|1');
 wikiRecEnsure(B, 1);
 shown.add(B + '|2');
 wikiRecEnsure(B, 2); // queued
 shown.delete(B + '|2'); // left the Stage 2 page
 assert.equal(calls.length, 1);
 await settle(0, answer(B, 1));
 assert.equal(calls.length, 1, 'no Stage 2 request for a page the user already left');
 assert.equal(has(B + '|2'), false);
 // Coming back to Stage 2 asks again (the block was dropped, not stuck).
 shown.add(B + '|2');
 wikiRecEnsure(B, 2);
 assert.equal(calls.length, 2);
 assert.match(calls[1], /stage-2$/);
 await settle(1, answer(B, 2));

 console.log('PASS Harness record queue: a queued read is cancelled when its page is left.');
})().catch(error => { console.error(error); process.exit(1); });
