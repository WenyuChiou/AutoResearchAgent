const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

// Backend read of the Harness record: counts first, labelled fallback, three read states, one request at a time.
const REF = 'project-aaaa1111';
const calls = [];
const timers = [];
const pending = [];
const clicks = [];
const context = vm.createContext({
 esc: value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;'),
 rt: {ref:REF},
 projectPath: (ref, tail) => '/api/projects/' + ref + '/' + tail,
 liveRequest: (...args) => new Promise((resolve, reject) => { calls.push(args); pending.push({resolve, reject}); }),
 document: {addEventListener: (type, fn) => { if (type === 'click') clicks.push(fn); }},
 setTimeout: (fn, ms) => { timers.push({fn, ms}); return timers.length; },
 clearTimeout: id => { if (timers[id - 1]) timers[id - 1].fn = null; },
 v1S1Record: () => ({summary:'按已保存交付统计：记录了 30 篇文献。', source:'旧说明', chips:[], checks:[{name:'筛选决定', result:'纳入 1', raw:{a:1}}]})
});
vm.runInContext(fs.readFileSync(path.join(__dirname, 'wiki-harness-record.js'), 'utf8'), context);
const {wikiRecordBlock, wikiRecHome} = context;
const tick = () => new Promise(resolve => setImmediate(resolve));
const runTimer = ms => { for (const timer of timers) if (timer.fn && timer.ms === ms) { const fn = timer.fn; timer.fn = null; fn(); } };

const stage = (status, extra = {}) => { const one = {
 kind:'HarnessRecordSummary', project_ref:REF, read_only:true, execution_authorized:false,
 stages:{'1':{
  status, reason:null, summary:{records:179, rows_with_data:2, checkpoint_passed:false},
  rows:[
   {key:'search', label:'检索记录', value:{queries:12, backend_failures:1}, missing:null, source:{view:'stage1', path:'ledger.counts'}},
   {key:'screening', label:'筛选决定', value:{decisions:40}, missing:'没有保存纳入、排除各多少', source:{view:'stage1', path:'ledger.counts'}},
   {key:'checkpoint', label:'交付检查点', value:null, missing:'还没有保存交付检查点', source:{view:'stage1', path:'checkpoint'}}
  ],
  blocked:[
   {category:'failed-check', label:'没通过的检查', count:1, reasons:['bad<b>x</b>']}, {category:'wrong-project', label:'错项目', count:0, reasons:[]},
   {category:'stale-version', label:'旧版本', count:0, reasons:[]}, {category:'duplicate-click', label:'重复点击', count:0, reasons:[]},
   {category:'over-limit', label:'超额度', count:0, reasons:[]}
  ],
  blocked_total:1, reopen:{available:false, missing:'x'}, timeline:{available:false, missing:'y'}, ...extra
 }}
}; one.stages['2'] = one.stages['3'] = one.stages['1']; return one; };

(async () => {
 // Loading: first paint asks for one read, shows the loading strip, no expand.
 let html = wikiRecordBlock(1);
 assert.match(html, /读取中/);
 assert.match(html, /不需要你操作/);
 assert.doesNotMatch(html, /<details/);
 runTimer(0);
 assert.equal(calls.length, 1);
 assert.deepEqual(calls[0], ['/api/projects/' + REF + '/harness-record/stage-1']); // GET only: no body argument
 assert.match(wikiRecordBlock(1), /读取中/); // repaint while waiting: no second request
 runTimer(0);
 assert.equal(calls.length, 1);

 // One at a time: a second stage waits for the first; a newer wish replaces an older one that never started.
 wikiRecordBlock(2); runTimer(0);
 wikiRecordBlock(3); runTimer(0);
 assert.equal(calls.length, 1);
 pending[0].resolve(stage('recorded'));
 await tick(); await tick();
 assert.equal(calls.length, 2);
 assert.match(calls[1][0], /stage-3$/); // stage 2 was replaced by the newest wish
 assert.equal(calls.filter(c => /stage-2/.test(c[0])).length, 0);

 // Backend counts win over the page's own count; unsaved rows say 还没有 with the host's reason; escaping.
 html = wikiRecordBlock(1);
 assert.match(html, /179 条记录 · 拦下 1 次/);
 assert.doesNotMatch(html, /按已保存交付统计|30 篇/);
 assert.match(html, /检索词 12 · 检索失败 1/);
 assert.match(html, /决定 40/);
 assert.match(html, /还没有：没有保存纳入、排除各多少/);
 assert.match(html, /还没有：还没有保存交付检查点/);
 assert.match(html, /检查点没有通过/);
 assert.match(html, /0 次 · 没有发生/);
 assert.match(html, /只数已保存的失败记录/);
 assert.match(html, /bad&lt;b&gt;x&lt;\/b&gt;/);
 assert.doesNotMatch(html, /<b>x<\/b>/);
 assert.equal((html.match(/后台还没有提供这一块/g) || []).length, 2); // reopen + timeline
 assert.match(html, /data-wiki-record-stage="1"/);

 // Stage 3 request ends; nothing else is waiting.
 pending[1].resolve(stage('not-run'));
 await tick(); await tick();

 // Inferred values are labelled 推算, only when the host says so.
 const inferred = stage('recorded');
 inferred.stages['1'].rows[0].inferred = true;
 inferred.stages['1'].rows[1].inferred_keys = ['decisions'];
 inferred.stages['1'].summary.inferred = true;
 context.rt.ref = REF; // same project, new stage key
 wikiRecordBlock(2); runTimer(0);
 assert.equal(calls.length, 3);
 const marked = JSON.parse(JSON.stringify(inferred));
 marked.stages['2'] = marked.stages['1'];
 pending[2].resolve(marked);
 await tick(); await tick();
 html = wikiRecordBlock(2);
 assert.match(html, /推算 · 检索词 12/);
 assert.match(html, /决定 40（推算）/);
 assert.match(html, /179 条记录 · 拦下 1 次（推算）/);
 assert.doesNotMatch(wikiRecordBlock(1).replace(/推算/, ''), /推算 ·/); // stage 1 rows were not marked

 // Home column: only what was already read; the stage 3 result was "not-run" so it adds nothing.
 const home = wikiRecHome(REF);
 assert.deepEqual([...home.stages], [1, 2]);
 assert.match(home.text, /358 条记录 · 拦下 2 次（推算）/);
 assert.equal(wikiRecHome('project-other'), null);

 // Not-run with no page data: the plain empty strip. Not-run with saved delivery: labelled fallback.
 html = wikiRecordBlock(3);
 assert.match(html, /这一段还没有运行，没有记录。/);
 assert.doesNotMatch(html, /\d+ 次/);

 // Unavailable: fallback wording stays, basis is stated with the host's reason; unknown codes are escaped.
 const R2 = 'project-bbbb2222';
 context.rt.ref = R2;
 wikiRecordBlock(1); runTimer(0);
 const unavailable = stage('unavailable');
 unavailable.project_ref = R2;
 unavailable.stages['1'].reason = 'stage1-unconnected<i>';
 pending[3].resolve(unavailable);
 await tick(); await tick();
 html = wikiRecordBlock(1);
 assert.match(html, /按已保存交付统计：记录了 30 篇文献/);
 assert.match(html, /后台这一段的记录现在读不到（原因代码 stage1-unconnected&lt;i&gt;）/);
 assert.match(html, /不是后台的 Harness 记录汇总/);
 assert.doesNotMatch(html, /<i>/);
 const known = stage('unavailable'); known.stages['1'].reason = 'stage3-unconnected';
 context.rt.ref = 'project-cccc3333';
 known.project_ref = 'project-cccc3333';
 wikiRecordBlock(1); runTimer(0);
 pending[4].resolve(known);
 await tick(); await tick();
 assert.match(wikiRecordBlock(1), /Stage 3 还没有接通/);

 // Timeout: shown after 30 s, the real request stays in flight, retry is blocked until it ends, nothing is resent.
 const R3 = 'project-dddd4444';
 context.rt.ref = R3;
 const before = calls.length;
 wikiRecordBlock(1); runTimer(0);
 assert.equal(calls.length, before + 1);
 runTimer(30000);
 html = wikiRecordBlock(1);
 assert.match(html, /读取超时/);
 assert.match(html, /等了 30 秒还没读到。这不代表没有记录/);
 assert.match(html, /data-wiki-record-retry disabled/);
 assert.match(html, /上一次读取还没结束/);
 wikiRecordBlock(2); runTimer(0); // another stage during the flight does not start a second request
 assert.equal(calls.length, before + 1);
 pending[before].reject(Object.assign(Error('connection <reset>'), {status:500}));
 await tick(); await tick();
  html = wikiRecordBlock(1);
 assert.match(html, /读取失败/); // the late failure replaces the timeout display
 assert.match(html, /看原始错误/);
 assert.match(html, /connection &lt;reset&gt;/);
 assert.doesNotMatch(html, /connection <reset>/);
 assert.match(html, /已显示的结果不受影响/);
 assert.match(html, /data-wiki-record-retry disabled/); // the queued stage 2 read now holds the single slot
 assert.equal(calls.length, before + 2); // stage 2 started only after stage 1 ended
 assert.match(calls[before + 1][0], /stage-2$/);

 // Plain failure shows the red state, never an empty-stage message; 404 = this host has no summary.
 const R4 = 'project-eeee5555';
 context.rt.ref = R4;
 pending[before + 1].resolve(stage('recorded')); await tick(); await tick();
 wikiRecordBlock(1); runTimer(0);
 const last = pending.length - 1;
 pending[last].reject(Object.assign(Error('HTTP 404'), {status:404}));
 await tick(); await tick();
 html = wikiRecordBlock(1);
 assert.match(html, /按已保存交付统计/);
 assert.match(html, /这个后台没有提供 Harness 记录汇总/);

 // Archives and saved views have no host record: no request.
 const count = calls.length;
 context.rt.ref = 'view:abc';
 html = wikiRecordBlock(1); runTimer(0);
 assert.equal(calls.length, count);
 assert.match(html, /这份保存的记录没有后台的 Harness 记录汇总/);
 assert.match(html, /按已保存交付统计/);

 // A wrong-shaped answer is a read failure, not data.
 context.rt.ref = 'project-ffff6666';
 wikiRecordBlock(1); runTimer(0);
 pending[pending.length - 1].resolve({kind:'Other'});
 await tick(); await tick();
 assert.match(wikiRecordBlock(1), /读取失败/);
 assert.match(wikiRecordBlock(1), /harness-record-shape-differs/);

 // Explicit retry button: restarts only when nothing is in flight, and sends one GET.
 const R6 = 'project-gggg7777';
 context.rt.ref = R6;
 wikiRecordBlock(1); runTimer(0);
 pending[pending.length - 1].reject(Object.assign(Error('HTTP 500'), {status:500}));
 await tick(); await tick();
 assert.match(wikiRecordBlock(1), /读取失败/);
 const root = {dataset:{wikiRecordRef:R6, wikiRecordStage:'1'}};
 const click = () => clicks[0]({target:{closest: selector => selector === '[data-wiki-record-retry]' ? {closest: () => root} : null}, preventDefault() {}});
 const sent = calls.length;
 click();
 assert.equal(calls.length, sent + 1);
 assert.match(wikiRecordBlock(1), /读取中/);
 click(); // a second click while one read is in flight sends nothing
 assert.equal(calls.length, sent + 1);

 console.log('PASS Harness record backend read: counts first, labelled fallback, 推算, loading/timeout/failure, one request at a time, escaping.');
})().catch(error => { console.error(error); process.exit(1); });
