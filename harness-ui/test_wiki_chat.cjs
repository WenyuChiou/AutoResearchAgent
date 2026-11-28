// Wiki V1 chat drawer: the pure parts (state mapping, gray-button reasons, markup). No DOM, no network.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
require('./v1_text_shim.cjs');

const context = vm.createContext({
 esc: value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;'),
 TextEncoder, document: {addEventListener() {}}, apps: [], rt: {}, v7AfterRender() {}
});
vm.runInContext(fs.readFileSync(path.join(__dirname, 'wiki-chat.js'), 'utf8') + `
;globalThis.api = {wikiChatPanel, wikiChatDraftReason, wikiChatMarkup, wikiChatTabMarkup, wikiChatControls, wikiChatBytes, wikiChatQuick};`, context);
const {wikiChatPanel, wikiChatDraftReason, wikiChatMarkup, wikiChatTabMarkup, wikiChatControls, wikiChatBytes, wikiChatQuick} = context.api;

const base = (extra = {}) => Object.assign({
 kind:'V9HarnessConversation', panel_state:'ready', can_send:true, panel_reason:null, model:'m', max_turns:3, reserved_turns:1, remaining_turns:2, turn_seconds:120,
 expires_at:1800000000, turns:[], sessions:[], hidden_turn_count:0, controllable_turn_ids:[], budget_identity_preserved:false,
 context:{materials:[], expected_materials:[], supported_actions:['state', 'materials', 'read_material']}, admission_blockers:[], other_turn:null
}, extra);
const panel = (state, extra = {}) => wikiChatPanel(Object.assign({stage:1, phase:'ready', state, busy:false}, extra));
const draw = (state, extra = {}, ctl = {}) => {
 const c = Object.assign({stage:1, phase:'ready', state, busy:false, title:'课题甲'}, extra), p = wikiChatPanel(c);
 return wikiChatMarkup(c, p, Object.assign({open:true, answers:{}, reconciled:{}}, ctl), state);
};

// 1. The eleven states (DESIGN 8.4): dot, status line, and why the send button is gray.
const rows = [
 ['not-configured', 'off', '本机还没有配置对话'],
 ['login-required', 'off', '还没登录 Codex'],
 ['no-permit', 'wait', '这个课题还没有对话许可'],
 ['ready', 'done', '可以发送'],
 ['sending', 'run', '等待回复'],
 ['unknown-result', 'wait', '这一轮的结果还没确认'],
 ['blocked', 'wait', '被拦下'],
 ['other-turn', 'wait', '别处有一轮对话还没结束'],
 ['stage-unconnected', 'off', '这一段的材料还没接通，对话关着']
];
for (const [key, dot, label] of rows) {
 const state = base({panel_state:key, can_send:key === 'ready', panel_reason:key === 'blocked' ? {text:'调用次数已用完，不会自动追加'} : null,
  turns:key === 'sending' ? [{id:'t', status:'running', user_text:'q', outputs:[]}] : []});
 const p = panel(state);
 assert.equal(p.key, key); assert.equal(p.dot, dot, key); assert.equal(p.label, label, key);
 assert.equal(p.canSend, key === 'ready', key);
 if (key !== 'ready') assert.ok(p.sendReason, key + ' gray send button needs a reason');
}
assert.equal(panel(null, {phase:'loading'}).key, 'reading');
assert.equal(panel(null, {phase:'loading'}).label, '正在读取对话状态');
assert.equal(panel(null, {phase:'error'}).key, 'read-failed');
assert.equal(panel(null, {phase:'error'}).dot, 'err');
assert.equal(panel(base(), {phase:'error'}).stale, true, 'a failed re-read keeps the last state and says so');
assert.match(draw(base(), {phase:'error'}), /上次读取/);
assert.equal(panel(base(), {archive:true}).key, 'archive');
assert.equal(panel(null, {stage:5, phase:'idle'}).key, 'stage-unconnected', 'stage 4-6 never reads a state');
assert.equal(panel(base({panel_state:'login-required'})).body, false, 'login hides materials and history');
assert.equal(panel(base({panel_state:'not-configured'})).body, false);

// Starting vs waiting vs asking while sending.
const turnState = status => base({panel_state:'sending', turns:[{id:'t', status, user_text:'q', outputs:[], pending:status === 'waiting' ? {id:'r', sha256:'s', kind:'questions', questions:[{id:'q1', question:'范围？'}]} : null}]});
assert.equal(panel(turnState('starting')).label, '本轮启动中');
assert.equal(panel(turnState('running')).label, '等待回复');
assert.equal(panel(turnState('waiting')).label, '等你回答 Codex 的问题');
assert.equal(panel(turnState('waiting')).dot, 'wait');
assert.equal(panel(base(), {busy:true}).canSend, false);
assert.equal(panel(base(), {busy:true}).sendReason, '本轮进行中');

// 2. Message box: empty and over 8192 bytes cannot be sent.
assert.match(wikiChatDraftReason('   '), /空的/);
assert.equal(wikiChatDraftReason('hello'), '');
assert.equal(wikiChatDraftReason('a'.repeat(8192)), '');
assert.equal(wikiChatDraftReason('a'.repeat(8193)), '超过 8192 字节，没有发送');
assert.equal(wikiChatDraftReason('中'.repeat(2731)), '超过 8192 字节，没有发送', 'counted in bytes, not characters');
assert.equal(wikiChatBytes('中'), 3);

// 3. Quota bar and expiry.
const ready = draw(base());
assert.match(ready, /已预留 1 轮，每轮最多 120 秒 · 剩余 2 轮 · 有效到 \d{4}年\d{1,2}月\d{1,2}日 \d{2}:\d{2}/);
assert.match(ready, /width:33%/);
assert.match(draw(base({max_turns:0, reserved_turns:0, remaining_turns:0})), /已预留 0 轮.*剩余 0 轮/);
assert.doesNotMatch(draw(base({panel_state:'no-permit', can_send:false})), /已预留/, 'no permit: reason instead of a quota bar');
assert.doesNotMatch(draw(base({panel_state:'not-configured', model:null})), /已预留/);

// 4. Materials: every row says whether it can be read and why not; counts and empty text.
const materials = ['能读', '不能读：超过 64 KiB', '不能读：文件找不到'].map((text, i) => ({id:'m' + i, name:'文件' + i, sha256:'abcdef012345' + i, origin:'registered-file', readable:{ok:i === 0, reason:i ? 'x' : null, text}}));
const shown = draw(base({context:{materials, expected_materials:[], supported_actions:[]}}));
assert.match(shown, /本阶段文件 · 3 份登记材料/);
assert.match(shown, /wc-ok">能读/);
assert.match(shown, /wc-no">不能读：超过 64 KiB/);
assert.match(shown, /不能读：文件找不到/);
assert.match(shown, /版本 abcdef01/);
assert.match(shown, /data-wc-original="m1"/);
assert.match(draw(base()), /本阶段文件 · 0 份登记材料[\s\S]*还没有。/);
assert.match(draw(base({panel_state:'stage-unconnected', can_send:false, context:{materials:[], expected_materials:[{category:'来源包'}, {category:'原文定位'}]}})), /接通后会读的材料[\s\S]*来源包[\s\S]*原文定位/);
assert.match(draw(base({panel_state:'stage-unconnected', can_send:false}), {stage:3}), /所选方向的计划[\s\S]*流程图[\s\S]*对应评审/);

// 5. Messages: end tags, notices, truncation note, 50-turn note, no raw code in the message area.
const turn = extra => Object.assign({id:'t1', status:'completed', user_text:'问', response:'答', outputs:[{action:'read_material', value:{material_id:'m0'}, model_saw_truncated:false}], notices:[]}, extra);
const withTurns = (...turns) => draw(base({turns, context:{materials, expected_materials:[], supported_actions:[]}}));
let html = withTurns(turn());
assert.match(html, /本轮已完成/); assert.match(html, /读取了：文件0 · 模型调用 1 次/);
html = withTurns(turn({status:'failed', outputs:[], response:'', error:'chat-response-too-large', error_reason:{text:'回答太长，没有保存', code:'chat-response-too-large'}}));
assert.match(html, /本轮失败[\s\S]*回答太长，没有保存/);
assert.doesNotMatch(html.replace(/<code[\s\S]*?<\/code>/g, ''), /chat-response-too-large/, 'raw code only in technical details');
assert.match(html, /<code[^>]*>chat-response-too-large<\/code>/);
assert.match(withTurns(turn({status:'interrupted'})), /中断请求已发出，是否真的停了还要核对/);
assert.match(withTurns(turn({status:'unknown'})), /结果还没确认/);
assert.match(withTurns(turn({notices:[{kind:'auto-declined-command'}]})), /Codex 请求执行命令，已自动拒绝/);
assert.match(withTurns(turn({notices:[{kind:'auto-declined-file-change'}]})), /Codex 请求修改文件，已自动拒绝/);
assert.match(withTurns(turn({outputs:[{action:'read_material', value:{material_id:'m0'}, model_saw_truncated:true}]})), /结果较长，Codex 只看到了开头/);
assert.doesNotMatch(withTurns(turn()), /结果较长/);
assert.match(draw(base({hidden_turn_count:4})), /更早的对话没有显示/);
assert.match(draw(base()), /这个课题在这一段还没有对话。先读取会话/);
assert.match(withTurns(turn({user_text:'<img src=x>', response:'<script>x</script>'})), /&lt;img src=x&gt;[\s\S]*&lt;script&gt;/);

// 6. Question card: 1-3 questions, 4096-byte note, submit button; none when nothing is waiting.
const ask = base({panel_state:'sending', turns:[{id:'t9', status:'waiting', user_text:'q', outputs:[], pending:{id:'r1', sha256:'h', kind:'questions', questions:[{id:'a', question:'范围？'}, {id:'b', question:'版本？'}]}}]});
html = draw(ask);
assert.match(html, /Codex 在向你提问/); assert.equal((html.match(/data-wc-ans=/g) || []).length, 2); assert.match(html, /提交答复/); assert.match(html, /4096 字节/);
assert.doesNotMatch(draw(base()), /Codex 在向你提问/);
assert.match(draw(base({panel_state:'sending', turns:[{id:'t', status:'running', outputs:[]}]})), /这一轮正在运行，现在没有要你回答的/);
const tool = base({panel_state:'sending', turns:[{id:'t8', status:'waiting', outputs:[], pending:{id:'r2', sha256:'h', kind:'harness-approval'}}]});
html = draw(tool);
assert.match(html, /这次对话只能读材料，不能用工具改东西/); assert.match(html, /拒绝请求/); assert.doesNotMatch(html, /确认执行此操作/);

// 7. Gray-button reasons that depend on the saved turns.
const ctl = state => ({state, sending:false});
let p = panel(turnState('running'));
assert.equal(wikiChatControls(ctl(turnState('running')), p).stopReason, '服务重启过，这一轮只能核对', 'not controllable: restarted service can only reconcile');
assert.equal(wikiChatControls(ctl(turnState('running')), p).reconcileTurn.id, 't');
const live = Object.assign(turnState('running'), {controllable_turn_ids:['t']});
assert.equal(wikiChatControls(ctl(live), panel(live)).stopReason, '');
assert.equal(wikiChatControls(ctl(live), panel(live)).reconcileTurn, null);
const unknown = base({panel_state:'unknown-result', turns:[{id:'u', status:'unknown', user_text:'q', outputs:[]}]});
assert.equal(wikiChatControls(ctl(unknown), panel(unknown)).reconcileTurn.id, 'u');
assert.equal(wikiChatControls(ctl(unknown), panel(unknown)).reconcileReason, '');
const cont = Object.assign({}, unknown, {budget_identity_preserved:true});
assert.equal(wikiChatControls(ctl(cont), panel(cont)).reconcileReason, '这份许可下不能核对，请联系操作者');
assert.equal(wikiChatControls(ctl(base()), panel(base())).newReason, '还没有对话，直接发送就会开始');
const withSession = base({sessions:[{id:'s1'}]});
assert.equal(wikiChatControls(ctl(withSession), panel(withSession)).newReason, '');
assert.equal(wikiChatControls(ctl(unknown), panel(unknown)).newReason, '先核对上一轮');

// 8. Page rules: no authorize button anywhere, chips only fill, stage 4-6 closed, default off wording.
for (const state of [base(), base({panel_state:'no-permit', can_send:false}), base({panel_state:'not-configured', model:null})]) {
 assert.doesNotMatch(draw(state), /去授权|点此授权|授权这个课题|签同意书|data-wc-grant/);
}
html = draw(base({panel_state:'no-permit', can_send:false}));
assert.match(html, /许可由本机操作者在页面外准备/); assert.match(html, /Stage 1 整轮运行的同意书不能代用/); assert.match(html, /去连接与设置/); assert.match(html, /重新检查/);
html = draw(base({panel_state:'not-configured', model:null, panel_reason:{text:'本机还没有配置对话'}}));
assert.match(html, /对话的配置和许可由本机操作者在页面外准备，页面上不能配置，也不能授权/);
assert.match(wikiChatTabMarkup({state:base({panel_state:'not-configured', panel_reason:{text:'本机还没有配置对话'}}), stage:1}, panel(base({panel_state:'not-configured'})), {open:false}), /对话未启用/);
html = draw(null, {stage:4, phase:'idle'});
assert.match(html, /本阶段还没有开放/); assert.doesNotMatch(html, /data-wc-chip/);
assert.equal((draw(base()).match(/data-wc-chip=/g) || []).length, wikiChatQuick[1].length);
assert.equal(wikiChatQuick[3].length, 1);
assert.match(draw(base()), /点击只填入，确认后再发送/);
assert.match(draw(base()), /问答不能代替选方向、批准计划或启动研究/);
assert.match(draw(base()), /V1 的对话只读。列出的工具只代表声明，不代表已连接/);
assert.match(draw(base()), /文献与证据助手[\s\S]*课题甲 · Stage 1/);
assert.match(draw(base(), {stage:2}), /比较与选案助手/); assert.match(draw(base(), {stage:3}), /设计与可行性助手/);
assert.match(draw(base({panel_state:'other-turn', can_send:false, other_turn:{project_ref:'p2', stage:2, created_at:1800000000}}), {otherTitle:'另一个课题'}), /另一个课题」的 Stage 2[\s\S]*去那一轮看看/);
const archive = draw(null, {archive:true, phase:'idle'});
assert.match(archive, /这是历史归档（或合成样例），不能在这里改/); assert.doesNotMatch(archive, /data-wc-send/);

// 9. A state value from the service never reaches an attribute unescaped (review P2-1).
{
 const hostile = draw(base({panel_state:'x" onmouseover="alert(1)', can_send:false}));
 assert.doesNotMatch(hostile, /" onmouseover="/);
 assert.match(hostile, /data-wc-state="x&quot; onmouseover=&quot;alert\(1\)"/);
 assert.match(hostile, /对话许可没有通过核对，界面只读，发送关闭/, 'an unknown state is read-only and says why');
}

console.log('PASS Wiki chat drawer: 11 states, byte limit, quota, readable rows, turn endings, ask card, gray reasons.');

// 9. Polling rule (design addendum): open = while a turn works; collapsed = also while a result is unknown; otherwise
// collapsing stops it; leaving the stage page / language switch always stops it.
(async () => {
 const timers = [];
 let nextId = 1, snapshot = null;
 Object.assign(context, {
  window:{RESEARCH_PROJECTS:{credential:'x'}},
  setTimeout:(fn, ms) => { const id = nextId++; timers.push({id, ms, fn}); return id; },
  clearTimeout:id => { const i = timers.findIndex(t => t.id === id); if (i >= 0) timers.splice(i, 1); },
  fetch:async () => ({ok:true, status:200, json:async () => snapshot}),
  wikiChatCurrent:() => ({ref:'p', archive:false, stage:1}), wikiChatPaint() {}
 });
 const app = {stage:1}, ctl = context.wikiChatCtl(app);
 const reset = (state, open, page) => {
  timers.length = 0; snapshot = state; context.v1Page = () => page ?? 's1';
  Object.assign(ctl, {key:'p|1', open, state:null, phase:'ready', loading:false, pollTimer:0, root:{isConnected:true, querySelector:() => null, v1Markup:''}});
 };
 const working = base({turns:[{id:'t', status:'running', user_text:'q', outputs:[]}]});
 const asking = base({turns:[{id:'t', status:'waiting', user_text:'q', outputs:[], pending:{answer:null}}]});
 const unknown = base({panel_state:'unknown-result', turns:[{id:'t', status:'unknown', user_text:'q', outputs:[]}]});
 const idle = base();
 const poll = async (state, open, page) => { reset(state, open, page); await context.wikiChatLoad(app); ctl.pollTimer = timers.length ? timers[timers.length - 1].id : 0; return timers.map(t => t.ms); };

 assert.deepEqual(await poll(working, true), [2000], 'open drawer, working turn: 2 s');
 assert.deepEqual(await poll(working, false), [2000], 'collapsed, working turn: keeps polling');
 assert.deepEqual(await poll(asking, false), [10000], 'collapsed, waiting for a person: 10 s');
 assert.deepEqual(await poll(unknown, false), [10000], 'collapsed, unknown result: keeps polling slowly');
 assert.deepEqual(await poll(unknown, true), [], 'open drawer with an unknown result shows it; no polling');
 assert.deepEqual(await poll(idle, false), [], 'collapsed, nothing running: no polling');
 assert.deepEqual(await poll(working, false, ''), [], 'not a stage page (language switch): no polling');

 // Collapsing: a timer set while open is cleared unless a turn is working or unknown.
 for (const [state, kept] of [[idle, false], [working, true], [unknown, true], [asking, true]]) {
  await poll(state, true);
  if (!timers.length) timers.push({id:99, ms:1, fn() {}}), ctl.pollTimer = 99; // an old timer that collapsing must handle
  ctl.state = state;
  context.wikiChatOpen(app, false);
  assert.equal(timers.some(t => t.id === ctl.pollTimer), kept, 'collapsing with ' + state.turns.map(t => t.status).join() + ' keeps the timer: ' + kept);
 }
 // A fired timer re-checks: it does not read after the page is left.
 await poll(working, false);
 const fired = timers[0]; ctl.state = working; context.v1Page = () => ''; let reads = 0; snapshot = working;
 context.fetch = async () => { reads++; return {ok:true, status:200, json:async () => working}; };
 fired.fn();
 assert.equal(reads, 0, 'timer fired after leaving the stage page reads nothing');
})().then(() => console.log('PASS chat drawer polling rule.'), error => { console.error(error); process.exit(1); });
