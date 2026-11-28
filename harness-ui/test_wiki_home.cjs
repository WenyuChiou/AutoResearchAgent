// Wiki V1 HOME failure paths (review base P2-8) and the "工作台" rule (review base P1-1). No network.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const listeners = {};
const calls = [];
const store = new Map();
const storage = {getItem:key => store.has(key) ? store.get(key) : null, setItem:(key, value) => store.set(key, String(value)), removeItem:key => store.delete(key)};
const rt = {ref:null, list:[], meta:{}, loading:false, busy:false, pending:null, error:'', topicDraft:'', overview:null, savedRun:null};
const app = {lang:'zh', page:'home', stage:1, el:{dataset:{}, querySelectorAll:() => [], querySelector:() => null, contains:() => true}};
const esc = value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
const context = vm.createContext({
 rt, apps:[app], esc, localStorage:storage, sessionStorage:storage, liveProjectPreference:'pref',
 canonicalEntry:() => null, liveDisabled:() => rt.busy || rt.pending ? 'disabled' : '',
 otherPage:() => 'old', render:() => {}, v7AfterRender:() => {},
 liveRefresh:(...args) => { calls.push(['refresh', ...args]); return Promise.resolve(); },
 liveRecover:() => calls.push(['recover']), livePaint:() => calls.push(['paint']), livePost:(...args) => calls.push(['post', ...args]),
 v1Notice:(text, recover) => calls.push(['notice', text, recover]),
 location:{hash:'#x', pathname:'/', search:''}, history:{pushState:() => {}, state:null}, window:{scrollTo:() => {}, addEventListener:() => {}},
 document:{title:'', addEventListener:(type, fn) => (listeners[type] ||= []).push(fn)}, queueMicrotask:fn => fn(), setTimeout:() => 0
});
vm.runInContext((fs.readFileSync(path.join(__dirname, 'wiki-v1-text.js'), 'utf8') + '\n' + fs.readFileSync(path.join(__dirname, 'wiki-home.js'), 'utf8')), context);
const markup = () => context.wikiHomeMarkup();
const click = attrs => {
 const button = {disabled:false, dataset:{}, hasAttribute:name => Object.hasOwn(attrs, name)};
 for (const [name, value] of Object.entries(attrs)) button.dataset[name.replace(/^data-/, '').replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = value;
 const event = {target:{closest:() => button}, preventDefault() {}, stopImmediatePropagation() {}};
 for (const fn of listeners.click) fn(event);
};
const project = (ref, topic, extra = {}) => ({project_ref:ref, topic, revision:2, input_version:1, stage1_status:'not-started', stage1_intake_ready:false, ...extra});

// Create rejected by the service (4xx) or failing (5xx): the error is shown with its raw code in details, list kept.
rt.list = [project('project-a', '老龄化与消费')];
for (const error of ['project-topic-required', 'HTTP 503']) {
 rt.error = error;
 const html = markup();
 assert.match(html, /这次读取或保存没有完成/);
 assert.match(html, new RegExp('<details><summary>技术细节</summary><p>' + error));
 assert.match(html, /老龄化与消费/, 'projects already read stay on the page');
 assert.doesNotMatch(html, /正在保存…/);
}
rt.error = '';

// Create in flight, then unknown: wording of 8.5; never resent; the check is read-only.
rt.busy = true; rt.pending = {ref:null, path:'/api/projects', body:{key:'k1'}};
assert.match(markup(), /正在保存…<\/button>/);
assert.match(markup(), /正在保存新课题…/);
rt.busy = false;
assert.match(markup(), /新课题的创建结果还待核对，不会自动重建。/);
assert.match(markup(), /data-wiki-home-recover>回到原提交处核对/);
calls.length = 0;
click({'data-wiki-home-recover':''});
assert.deepEqual(calls, [['recover']], 'recovering only reads the original receipt');

// Another topic's unconfirmed submit (8.3).
rt.pending = {ref:'project-a', path:'/api/projects/project-a/compile', body:{key:'k2'}};
assert.match(markup(), /另一个课题有未确认的提交（老龄化与消费）/);
assert.match(markup(), /data-wiki-home-pending-open="project-a">切回那个课题核对/);
rt.pending = null;

// Same titles are told apart; the record column never claims "not run" for a topic with records.
rt.list = [project('project-aaaa111111', '同名课题'), project('project-bbbb222222', '同名课题', {stage1_status:'query-ledger-active', revision:7})];
let html = markup();
assert.match(html, /编号尾号 111111/);
assert.match(html, /打开 同名课题 · 编号尾号 222222/);
assert.match(html, /有 Stage 1 记录，打开课题后可见/);
assert.match(html, /<td class="wiki-home-muted" data-wiki-home-record-ref="project-aaaa111111">打开课题后可见<\/td>/); // not read yet: no claim either way
store.set('wiki-v1-record:project-bbbb222222', JSON.stringify({papers:30, located:149, checked:0, claims:149}));
assert.match(markup(), /按已保存交付统计：30 篇文献 · 核对 0 \/ 149/);

// "工作台" with an open topic stays on that topic (no re-read, drafts untouched); without one it goes home.
rt.ref = 'project-a'; rt.list = [project('project-a', '老龄化与消费')]; rt.overview = {project:{project_ref:'project-a'}}; rt.scopeDraft = {values:{note:'草稿'}};
app.page = 'settings'; calls.length = 0;
click({'data-page':'workspace'});
assert.equal(app.page, 'workspace');
assert.deepEqual(calls.filter(call => call[0] === 'refresh'), []);
assert.equal(rt.scopeDraft.values.note, '草稿');
rt.ref = null; rt.overview = null; app.page = 'files'; rt.pending = {ref:null, body:{key:'k3'}}; calls.length = 0;
click({'data-page':'workspace'});
assert.equal(app.page, 'files', 'an unconfirmed submit keeps the page');
assert.equal(calls[0][0], 'notice');
assert.match(calls[0][1], /先核对/);
rt.pending = null; calls.length = 0;
click({'data-page':'workspace'});
assert.equal(app.page, 'home');
assert.equal(JSON.stringify(calls.find(call => call[0] === 'refresh')), JSON.stringify(['refresh', null, {list:true}]));

// DESIGN 8.5 first-visit guide: three steps with links and a 连接 Codex entry; closing is remembered.
rt.list = []; rt.error = ''; rt.pending = null; app.page = 'home';
html = markup();
assert.match(html, /data-wiki-home-guide/);
for (const step of ['开新课题', '你要点的三处', '产物在哪看']) assert.match(html, new RegExp(step));
assert.match(html, /data-page="files">去项目文件/);
assert.match(html, /data-page="settings" data-wiki-home-codex>连接 Codex/);
assert.ok(html.indexOf('wiki-home-decisions') < html.indexOf('data-wiki-home-guide') && html.indexOf('data-wiki-home-guide') < html.indexOf('wiki-home-projects'), 'between the three decisions and the project table');
app.el.querySelector = () => ({remove() {}});
click({'data-wiki-home-guide-close':''});
assert.equal(store.get('wiki-v1-guide-closed'), '1');
assert.doesNotMatch(markup(), /data-wiki-home-guide/);
store.delete('wiki-v1-guide-closed');
assert.match(markup(), /data-wiki-home-guide/, 'settings can show it again by clearing the mark');

// Acceptance M-6: 「看这三处」 visibly responds (focus moves to the list and it is marked), not only a scroll.
{
 const classes = new Set(), attrs = {};
 let focused = false;
 const decisions = {scrollIntoView() {}, focus() { focused = true; }, setAttribute(name, value) { attrs[name] = value; }, classList:{add:name => classes.add(name), remove:name => classes.delete(name)}};
 const saved = app.el.querySelector;
 app.el.querySelector = selector => selector === '.wiki-home-decisions' ? decisions : null;
 click({'data-wiki-home-focus':'decisions'});
 app.el.querySelector = saved;
 assert.equal(focused, true, 'focus moves to the three decisions');
 assert.equal(attrs.tabindex, '-1');
 assert.ok(classes.has('wiki-home-flash'), 'the list is marked for a moment');
}
console.log('PASS Wiki home: first-visit guide, create 4xx/5xx shown with list kept, saving and unknown create wording, read-only recovery, foreign pending, same titles, record column, 工作台 rule.');
