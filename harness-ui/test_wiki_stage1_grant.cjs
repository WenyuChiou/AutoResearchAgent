const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const esc = value => String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
const LIMITS = {model_calls:5, seconds:600, search_calls:5, source_reads:5, rounds:5};
const ZERO = {model_calls:0, seconds:0, search_calls:0, source_reads:0, rounds:0};
const project = (consent = true) => ({project_ref:'project-a', input_version:1, revision:2, brief_sha256:'b'.repeat(64),
 plan:{manifest_sha256:'c'.repeat(64)},
 settings:{budgets:{model_calls:3, seconds:120, search_calls:3, source_reads:4, rounds:2}, consent:{external_search:consent, public_source_read:consent}}});
function load(limits, extra = {}) {
 const rt = {ref:'project-a', meta:{run_limits:limits}, overview:{project:project()}, loading:false, busy:false, pending:null, controlHeld:false, error:'', ...extra};
 const ctx = vm.createContext({rt, esc, apps:[{wikiS1:{}}], TextEncoder, JSON, Set, Math, Date, Number,
  canonicalReadonly:() => false, wikiHomeArchiveBound:() => false, projectPath:(ref, tail) => `/api/projects/${ref}/${tail}`,
  wikiS1Tabs:{}, wikiS1Results:() => '', livePaint:() => {}, window:{RESEARCH_PROJECTS:{credential:'x'}}});
 const ops = fs.readFileSync(path.join(__dirname, 'wiki-stage1-ops.js'), 'utf8');
 vm.runInContext(ops.slice(0, ops.indexOf('// ---------- hooks into')), ctx);
 const grant = fs.readFileSync(path.join(__dirname, 'wiki-stage1-grant.js'), 'utf8');
 vm.runInContext(grant.slice(0, grant.indexOf('// ---------- hooks into')), ctx);
 return ctx;
}
const buttonOf = html => html.slice(html.indexOf('<span class="ws-btn">'), html.indexOf('</span>', html.indexOf('</button>')) + 7);
const read = (grant, creation = {available:true, reason:null, max_seconds:120}) => ({key:null, state:'read',
 value:{grant_creation:creation, run_grant:grant, consent:{present:false}}});

// Zero launch: the entry is there, the button is gray and says why, the words box still exists.
let ctx = load(ZERO);
let html = ctx.wsgCardHtml();
assert.match(html, /data-wsg-state="zero"/);
assert.match(html, /运行上限是 0/);
assert.match(buttonOf(html), /disabled/);
assert.doesNotMatch(html, /data-wsg-words/, 'nothing to write when nothing can be submitted');

// Words are required and kept verbatim (not trimmed).
ctx = load(LIMITS);
ctx.rt.wsg = read({status:'none'});
let form = ctx.wsgFormFor('project-a');
const summary = ctx.rt.wsg.value, p = ctx.rt.overview.project;
assert.equal(ctx.wsgSubmitGate(summary, p), '请先写下你的授权理由（原话）');
form.words = '  我授权这一轮，到上限就停。  ';
assert.equal(form.words, '  我授权这一轮，到上限就停。  ');
assert.equal(ctx.wsgSubmitGate(summary, p), '请先勾选确认');
form.confirmed = true;
assert.equal(ctx.wsgSubmitGate(summary, p), '');
form.seconds = '999';
assert.match(ctx.wsgSubmitGate(summary, p), /最长秒数要是 1 到 120/);
form.seconds = '';
html = ctx.wsgCardHtml();
assert.doesNotMatch(buttonOf(html), /disabled/);
assert.match(html, /有效期最长 2 分/);

// Operations that need consent or budget are disabled with the reason, and never selected.
ctx = load(LIMITS, {overview:{project:project(false)}});
ctx.rt.wsg = read({status:'none'});
html = ctx.wsgCardHtml();
assert.match(html, /data-wsg-op="query"[^>]*disabled/);
assert.match(html, /课题没勾「同意外部检索」/);
assert.deepEqual(Array.from(ctx.wsgSelectedOps(ctx.rt.overview.project)), ['analyze-full-paper', 'records', 'delivery']);

// An existing grant closes creation and shows limits, validity and use.
ctx = load(LIMITS);
ctx.rt.wsg = read({status:'active', limits:{model_calls:3, seconds:100, search_calls:3, source_reads:4, rounds:2}, operations:['query'],
 max_actions:4, actions_used:1, expires_at:2000000000, remaining_seconds:90, user_input:'我写的话', lease:{state:'open'}},
 {available:false, reason:'stage1-run-grant-renewal-refused', max_seconds:120});
html = ctx.wsgCardHtml();
assert.match(html, /有效/);
assert.match(html, /1 \/ 4/);
assert.match(html, /还剩 1 分 30 秒/);
assert.match(html, /我写的话/);
assert.match(buttonOf(html), /disabled/);
assert.match(html, /已经有运行许可/);
assert.doesNotMatch(html, /data-wsg-confirm/);

// Each authorization has its own reason and confirmation; nothing is shared or reused.
ctx = load(LIMITS);
form = ctx.wsgFormFor('project-a');
assert.equal(ctx.wsgActionWords('authorize-plan'), '');
assert.match(ctx.wsgReasonGate('authorize-plan'), /先写下/);
ctx.wsgReasonFor('authorize-plan').words = '  只授权规划  ';
assert.match(ctx.wsgReasonGate('authorize-plan'), /先勾选/);
ctx.wsgReasonFor('authorize-plan').confirmed = true;
assert.equal(ctx.wsgActionWords('authorize-plan'), '  只授权规划  ');
assert.equal(ctx.wsgActionWords('query-authorize'), '', 'the plan reason is not usable for the query');
assert.equal(ctx.wsgActionWords('followup-authorize'), '');
form.words = '创建许可的话'; form.confirmed = true;
assert.equal(ctx.wsgActionWords('query-authorize'), '', 'the grant words are not usable for authorizations');
ctx.wsgClearReason('authorize-plan');
assert.equal(ctx.wsgActionWords('authorize-plan'), '');
ctx.wsgReasonFor('query-authorize').words = 'x'.repeat(4097); ctx.wsgReasonFor('query-authorize').confirmed = true;
assert.match(ctx.wsgReasonGate('query-authorize'), /超过 4096 字节/);
ctx.wsgReasonFor('query-authorize').words = '汉'.repeat(1366);  // 4098 bytes
assert.match(ctx.wsgReasonGate('query-authorize'), /超过 4096 字节/, 'bytes, not characters');

// Forms belong to a project: a late result for one never shows on another.
ctx = load(LIMITS);
const a = ctx.wsgFormFor('project-a'), b = ctx.wsgFormFor('project-b');
a.result = {ok:true, expires_at:'2030-01-01T00:00:00Z'};
assert.equal(b.result, null);
assert.notEqual(a, b);
assert.equal(ctx.wsgFormFor('project-a'), a);

// Backend codes never appear as body text; the raw value goes to the technical details.
ctx = load(LIMITS);
ctx.rt.wsg = read({status:'invalid', reason:'stage1-run-grant-ambiguous', lease:{state:'clock-regressed'}},
 {available:false, reason:'stage1-run-grant-verification-required', max_seconds:120});
html = ctx.wsgCardHtml();
assert.doesNotMatch(html.replace(/<details[\s\S]*?<\/details>/g, ''), /stage1-run-grant-ambiguous|clock-regressed/);
assert.match(html, /不止一份许可对得上/);
assert.match(html, /时钟倒退，已停用/);
ctx.rt.wsg = {key:null, state:'read', value:{grant_creation:{available:false, reason:'stage1-run-grant-renewal-refused'}, run_grant:{status:'none'},
 consent:{present:true, valid:false, reason:'stage-progression-consent-binding-differs'}}};
html = ctx.wsgCardHtml();
assert.doesNotMatch(html.replace(/<details[\s\S]*?<\/details>/g, ''), /stage-progression-consent-binding-differs/);
assert.match(html, /<code>stage-progression-consent-binding-differs<\/code>/);

// A server refusal is shown in plain words with whether anything was recorded.
form = ctx.wsgFormFor('project-a');
form.result = {ok:false, reason:'这个课题当前版本已经有运行许可', recorded:false};
assert.match(ctx.wsgCardHtml(), /没有写入任何东西/);
form.result = {ok:false, reason:'x', recorded:true};
assert.match(ctx.wsgCardHtml(), /已作为失败记录保存/);

// Scope consent comes only from the boxes; nothing is ticked by default and a zero limit cannot be ticked.
ctx = load(LIMITS);
assert.deepEqual(JSON.parse(JSON.stringify(ctx.wsgScopeConsent())), {external_search:false, public_source_read:false, browser_fallback:false});
form = ctx.wsgFormFor('project-a'); form.search = true;
assert.deepEqual(JSON.parse(JSON.stringify(ctx.wsgScopeConsent())), {external_search:true, public_source_read:false, browser_fallback:false});
assert.match(ctx.wsgConsentCard(), /联网检索公开文献，最多 <code>5<\/code> 次/);
ctx = load({...LIMITS, search_calls:0});
ctx.wsgFormFor('project-a').search = true;
assert.equal(ctx.wsgScopeConsent().external_search, false);
assert.match(ctx.wsgConsentCard(), /data-wsg-consent="external_search"[^>]*disabled/);

// The old fixed wording is gone from the runtime, and the three sends read the page's words.
const runtime = fs.readFileSync(path.join(__dirname, 'renderer/src/real-runtime.js'), 'utf8');
assert.doesNotMatch(runtime, /Bounded V7 integration validation/);
assert.doesNotMatch(runtime, /用户要求在本地 V7/);
assert.doesNotMatch(runtime, /本地 V7 限定链路验收/);
assert.doesNotMatch(runtime, /positive\(limits\?\.seconds\)&&positive\(limits\?\.search_calls\)/);
assert.match(runtime, /user_input:words/);
assert.doesNotMatch(runtime, /user_input:rl\(/, 'no fixed authorization sentence is left');
for (const action of ['authorize-plan', 'query-authorize', 'followup-authorize']) assert.ok(runtime.includes("realResearcherWords('" + action + "')"), action);
assert.ok(!runtime.includes('realResearcherWords()'), 'every authorization names its own card');
assert.ok(runtime.includes('function realCanSend()') && (runtime.match(/realReasonDone\('[a-z-]+',ok\)/g) || []).length === 3, 'words are only cleared when the request was sent');
assert.ok(runtime.includes('wsgClearReason(action);livePaint();'), 'clearing repaints so the box and button refresh');
console.log('wiki stage1 grant tests passed');
