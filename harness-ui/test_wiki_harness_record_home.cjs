const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

// Home table reads: first 8 visible rows, one request at a time, stop on leaving home, stop on the first timeout.
const refs = Array.from({length:10}, (_, i) => 'project-' + String(i).padStart(4, '0'));
const calls = [], pending = [], timers = [];
const apps = [{lang:'zh', page:'home'}];
const context = vm.createContext({
 esc: value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;'),
 rt: {ref:null, list:refs.map(ref => ({project_ref:ref}))},
 apps,
 projectPath: (ref, tail) => '/api/projects/' + ref + '/' + tail,
 liveRequest: (...args) => new Promise((resolve, reject) => { calls.push(args); pending.push({resolve, reject}); }),
 setTimeout: (fn, ms) => { timers.push({fn, ms}); return timers.length; },
 clearTimeout: id => { if (timers[id - 1]) timers[id - 1].fn = null; },
 wikiHomeRow: project => ({origin:project.origin || 'local', stage:project.stage === undefined ? 1 : project.stage})
});
vm.runInContext((fs.readFileSync(path.join(__dirname, 'wiki-v1-text.js'), 'utf8') + '\n' + fs.readFileSync(path.join(__dirname, 'wiki-harness-record.js'), 'utf8')), context);
const {wikiRecHomeStart, wikiRecHomeVisible, wikiRecHomeLeave, wikiRecHomeNote, wikiRecHomeWaiting, wikiRecHome} = context;
const tick = () => new Promise(resolve => setImmediate(resolve));
const answer = (ref, extra = {}) => ({
 kind:'HarnessRecordSummary', project_ref:ref, read_only:true,
 stages:{'1':{status:'recorded', summary:{records:5}, rows:[], blocked:[], blocked_total:0, ...extra}}
});
const settle = async (index, value) => { pending[index].resolve(value); await tick(); await tick(); };
const runTimer = ms => { for (const timer of timers) if (timer.fn && timer.ms === ms) { const fn = timer.fn; timer.fn = null; fn(); } };

(async () => {
 // Visible rows only: hidden (filtered) rows, non-local origins and rows without a stage are skipped; at most 8.
 const row = (ref, hidden) => ({hidden, querySelector: () => ({dataset:{wikiHomeOpen:ref}})});
 const app = {el:{querySelectorAll: selector => {
  assert.match(selector, /tr\[data-wiki-home-origin\]:not\(\[hidden\]\) \[data-wiki-home-open\]/);
  return refs.map(ref => ({dataset:{wikiHomeOpen:ref}}));
 }}};
 context.rt.list[1].origin = 'archive';
 context.rt.list[2].stage = null;
 const visible = wikiRecHomeVisible(app);
 assert.equal(visible.length, 8);
 assert.ok(!visible.some(item => item.ref === refs[1] || item.ref === refs[2]));
 context.rt.list[1].origin = undefined; context.rt.list[2].stage = undefined;

 // Sequential: one request at a time, GET only, never more than 8 in total.
 wikiRecHomeStart(refs.map(ref => ({ref})));
 assert.equal(calls.length, 1);
 assert.deepEqual(calls[0], ['/api/projects/' + refs[0] + '/harness-record/stage-1']);
 assert.ok(wikiRecHomeWaiting(refs[0]) && wikiRecHomeWaiting(refs[7]) && !wikiRecHomeWaiting(refs[8]));
 assert.match(wikiRecHomeNote(), /前 8 个课题.*0 \/ 8.*一次只读一个/);
 wikiRecHomeStart(refs.map(ref => ({ref}))); // another home paint with the same rows: nothing new
 assert.equal(calls.length, 1);
 await settle(0, answer(refs[0]));
 assert.equal(calls.length, 2);
 assert.equal(wikiRecHome(refs[0]).text, '5 条记录 · 拦下 0 次');
 assert.equal(wikiRecHome(refs[1]), null); // not read yet

 // Leaving home stops at once: the request in flight finishes, nothing new is sent.
 apps[0].page = 'workspace';
 wikiRecHomeLeave();
 await settle(1, answer(refs[1]));
 assert.equal(calls.length, 2);
 assert.equal(wikiRecHomeNote(), '');
 assert.equal(wikiRecHome(refs[1]).text, '5 条记录 · 拦下 0 次'); // the late answer is still kept, no resend

 // Back home: continue with the rows not read yet, still one at a time.
 apps[0].page = 'home';
 wikiRecHomeStart(refs.map(ref => ({ref})));
 assert.equal(calls.length, 3);
 assert.match(calls[2][0], new RegExp(refs[2]));
 await settle(2, answer(refs[2], {status:'not-run', summary:{records:null}, blocked_total:1}));
 assert.equal(wikiRecHome(refs[2]).text, '还没有运行 · 被拦下 1 次');
 assert.equal(calls.length, 4);

 // Leaving without the leave hook is caught too: the next step sees the page is not home.
 apps[0].page = 'files';
 await settle(3, answer(refs[3]));
 assert.equal(calls.length, 4);
 apps[0].page = 'home';

 // First timeout stops the rest, and the page says so. A late answer does not restart the queue.
 wikiRecHomeLeave();
 wikiRecHomeStart(refs.map(ref => ({ref})));
 assert.equal(calls.length, 5);
 assert.match(calls[4][0], new RegExp(refs[4]));
 runTimer(30000);
 assert.match(wikiRecHomeNote(), /读取超时，已停止读取后续课题.*打开课题后可见/);
 assert.equal(calls.length, 5);
 await settle(4, answer(refs[4]));
 assert.equal(calls.length, 5);
 assert.equal(wikiRecHome(refs[5]), null);

 // Rows that are not host projects (saved views) are never read.
 const before = calls.length;
 wikiRecHomeLeave();
 wikiRecHomeStart([{ref:'view:d62'}]);
 assert.equal(calls.length, before);

 console.log('PASS Harness record home reads: first 8 visible rows, one at a time, stop on leaving, stop on first timeout, read-only.');
})().catch(error => { console.error(error); process.exit(1); });
