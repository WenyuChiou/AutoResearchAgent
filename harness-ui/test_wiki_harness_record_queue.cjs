const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

// Queued reads follow the page: a wish whose block is no longer shown is cancelled, never sent.
const A = 'project-aaaa1111', B = 'project-bbbb2222', C = 'project-cccc3333', D = 'project-dddd4444';
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
vm.runInContext((fs.readFileSync(path.join(__dirname, 'wiki-v1-text.js'), 'utf8') + '\n' + fs.readFileSync(path.join(__dirname, 'wiki-harness-record.js'), 'utf8')), context);
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

 // A2: a home read queued behind another read; the user opens that project before it starts.
 apps[0].page = 'home'; context.rt.ref = null; shown.clear();
 shown.add(C + '|1');
 const n = calls.length;
 wikiRecEnsure(C, 1);
 assert.equal(calls.length, n + 1);
 wikiRecEnsure(A, 1, false, true); // home wish, queued
 apps[0].page = 'workspace'; context.rt.ref = A; shown.clear(); shown.add(A + '|1'); // opened A's Stage 1 page
 await settle(pending.length - 1, answer(C, 1));
 assert.equal(calls.length, n + 2, "A's block is on the page: its read is sent, not dropped");
 assert.match(calls[n + 1], /project-aaaa1111\/harness-record\/stage-1$/);
 assert.equal(has(A + '|1'), true);
 await settle(pending.length - 1, answer(A, 1));
 assert.equal(vm.runInContext("wikiRecStore.get('" + A + "|1').state", context), 'ok');
 // The same wish is still dropped when nothing shows it and the user is off the home page.
 shown.clear();
 shown.add(D + '|1');
 wikiRecEnsure(D, 1);
 wikiRecEnsure(A, 2, false, true);
 shown.clear();
 apps[0].page = 'workspace';
 const m = calls.length;
 await settle(pending.length - 1, answer(D, 1));
 assert.equal(calls.length, m, 'a home wish with no block on the page is dropped after leaving home');

 console.log('PASS Harness record queue: a queued read is cancelled when its page is left.');
})().catch(error => { console.error(error); process.exit(1); });
