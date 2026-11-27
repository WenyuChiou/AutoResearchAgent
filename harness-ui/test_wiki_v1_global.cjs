// Wiki V1 global pages (DESIGN 8.1, 8.2): files, history, settings markup and their five states. No network.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const diag = fs.readFileSync(path.join(__dirname, 'renderer/src/connection-diagnostics.js'), 'utf8');
const listeners = {};
const rt = {ref:null, list:[], meta:null, loading:false, busy:false, pending:null, error:'', overview:null, atlas:null, history:null, savedRun:null, epoch:1};
const app = {lang:'zh', page:'files', stage:1, el:{contains:() => true}};
const esc = value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
const context = vm.createContext({
 rt, apps:[app], esc, Date, JSON, Number, String, Object, Array, Promise, Math,
 v1On:a => a.lang === 'zh', v1OriginNames:{local:'本地项目', archive:'历史归档', synthetic:'合成样例', unknown:'来历未标注'},
 v1CurrentRow:() => rt.ref ? {origin:'local'} : null, v1ProjectTitle:() => rt.overview?.project?.brief?.original_description || '',
 wikiHomeArchiveBound:ref => /^view:/.test(ref || '') && rt.savedRun?.entry?.project_ref === ref,
 otherPage:() => '<section class="old">old</section>', livePaint:() => {}, liveRequest:() => { throw Error('no request in markup'); },
 localStorage:{removeItem() {}}, requestAnimationFrame:fn => fn(), render:() => {}, v7AfterRender:() => {},
 window:{RESEARCH_PROJECTS:{credential:'c'}}, location:{protocol:'http:'},
 document:{addEventListener:(type, fn) => (listeners[type] ||= []).push(fn)}
});
vm.runInContext(diag + '\n' + fs.readFileSync(path.join(__dirname, 'wiki-v1-global.js'), 'utf8'), context);
const page = name => { app.page = name; return context.otherPage(app); };
const text = html => html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ');

// No topic open: every page says so and keeps the old block for its handlers.
for (const name of ['files', 'history', 'settings']) {
 const html = page(name);
 assert.match(html, new RegExp(`data-v1-global="${name}"`));
 assert.match(html, /<section class="old">old<\/section>$/);
}
assert.match(text(page('files')), /还没有打开课题/);

// Loading, refused (other topic's record), error.
rt.ref = 'project-a'; rt.loading = true;
assert.match(text(page('history')), /正在读取保存记录/);
rt.loading = false; rt.error = 'HTTP 503';
assert.match(text(page('files')), /读取失败。 已经读到的内容没有丢/);
rt.error = ''; rt.overview = {project:{project_ref:'project-b'}};
assert.match(text(page('files')), /当前课题和文件记录不一致，已拒绝显示/);

// Topic open, nothing saved yet: the designed empty sentences.
const project = {project_ref:'project-a', input_version:1, revision:5, brief_sha256:'a'.repeat(64), brief:{original_description:'退休后家庭消费'}, settings:{brief_sha256:'a'.repeat(64), budgets:{model_calls:0, rounds:0, search_calls:0, seconds:0, source_reads:0}, execution_authorized:false}};
rt.overview = {project};
assert.match(text(page('files')), /这个课题还没有保存的文件。第一段交付后这里会出现文献图谱、论文目录、笔记和 BibTeX。/);
assert.match(text(page('history')), /这个课题还没有操作记录。/);
assert.match(text(page('history')), /这里先显示已能读取的记录/);

// Files from the delivery package: BibTeX and notes rows; download reasons where there is no original.
rt.atlas = {manifest_sha256:'m'.repeat(64), files:[{file_ref:'r1', sha256:'1'.repeat(64), path:'references.bib', mime:'application/x-bibtex'}, {file_ref:'r2', sha256:'2'.repeat(64), path:'wiki/' + 'c'.repeat(64) + '.md', mime:'text/markdown'}], payload:{index:{papers:[{title:'A'}, {title:'B'}]}}};
let html = page('files');
assert.match(html, /论文目录<\/b><small>2 篇/);
assert.match(html, /参考文献 BibTeX/);
assert.match(html, /逐篇笔记 1/);
assert.match(html, /data-v1g-download="0"/);
assert.match(html, /后台还没有这份文件的原件下载接口/);
assert.doesNotMatch(text(html).replace(/本页技术细节.*$/, ''), /1111111111|wiki\/c/, 'paths and checksums stay in the technical details');
app.v1gBad = {['1'.repeat(64)]:true};
assert.match(page('files'), /data-v1g-download="0" disabled>下载<\/button><small class="v1-reason">保存的文件和记录不一致，不能下载/);
app.v1gBad = {};

// History: plain words, newest first, result tags, filters, raw record highlighted on request.
rt.history = {project_ref:'project-a', actions:[
 {kind:'create', status:'saved', key:'k1', recorded_at:'2026-11-27T08:01:48+00:00'},
 {kind:'submit', status:'saved', key:'k2', recorded_at:'2026-11-27T08:02:55+00:00'},
 {kind:'compile', status:'failed', error:'intake-search-request-invalid', key:'k3', recorded_at:'2026-11-27T08:30:59+00:00'}]};
html = page('history');
const order = ['生成检索规划', '保存了范围', '新建了课题'].map(word => html.indexOf(word));
assert.ok(order[0] > 0 && order[0] < order[1] && order[1] < order[2], 'newest first');
assert.match(html, /全部 <b>3<\/b>/);
assert.match(html, /出错 <b>1<\/b>/);
assert.match(html, /s-err">出错/);
assert.doesNotMatch(text(html).replace(/本页技术细节.*$/, ''), /intake-search-request-invalid/, 'the raw error stays in the raw record');
app.v1gFilter = 'err';
html = page('history');
assert.equal((html.match(/data-v1g-raw="/g) || []).length, 1);
app.v1gFilter = 'all'; app.v1gRaw = 'k3';
html = page('history');
assert.match(html, /<details class="v1-tech" data-v1g-tech open>/);
assert.match(html, /<dt class="flash" data-v1g-raw-row="k3">/);
app.v1gRaw = null;
rt.pending = {ref:'project-a', path:'/api/projects/project-a/compile', body:{key:'k9'}};
assert.match(page('history'), /结果未确认[\s\S]*data-v1-recover>核对上次提交/);
rt.pending = null;

// Settings: six blocks, read-only wording, zero limits stay zero, unknown stays unknown.
rt.meta = {run_limits:{model_calls:0, rounds:0, search_calls:0, seconds:0, source_reads:0}, harness_head:'h'};
html = page('settings');
for (const block of ['conn', 'codex', 'lang', 'topic', 'env']) assert.match(html, new RegExp(`data-v1g-block="${block}"`));
assert.match(html, /data-v1g-guide>重新显示首次引导/);
assert.match(text(html), /对话许可不能当运行许可用，反过来也不行。/);
assert.match(text(html), /模型调用 上限 0/);
assert.match(text(html), /已报告金额（不是费用上限）：未提供/);
assert.match(text(html), /无法核实登录状态/);
assert.match(text(html), /范围、额度和运行操作请到对应阶段确认；这里不改许可。/);
assert.doesNotMatch(text(html).replace(/本页技术细节.*$/, ''), /Unknown|undefined|内容任务许可|科研运行许可/);

// Archives are read only and say so.
rt.ref = 'view:d62'; rt.overview = null; rt.history = null; rt.atlas = null;
rt.savedRun = {entry:{project_ref:'view:d62', label:'D62'}, binding:{manifest_sha256:'m'}, payload:{index:{papers:[{title:'A'}], bibliography:'@article{a}'}, note_paths:{a:1}}};
html = page('files');
assert.match(html, /只读/);
assert.match(html, /归档没有随附这份原件，只能在页面里看/);
assert.match(text(page('history')), /归档里没有保存操作记录/);
assert.match(text(page('settings')), /这是历史归档：只读，不连接 Codex，没有许可和额度。/);

// 8.22 environment bar: only when the page itself can tell it was not opened from the service.
assert.equal(context.v1gEnvAlerts().length, 0);
rt.error = 'origin-or-host-rejected';
assert.match(context.v1gEnvAlerts()[0].title, /这个页面不是从 Wiki 服务打开的/);
rt.error = ''; context.window.RESEARCH_PROJECTS = undefined;
assert.equal(context.v1gEnvAlerts()[0].raw, 'no-service-bootstrap');

console.log('PASS Wiki V1 global pages: environment bar, no topic, loading, refused, error, empty, files, history filters and raw rows, settings blocks, archives.');
