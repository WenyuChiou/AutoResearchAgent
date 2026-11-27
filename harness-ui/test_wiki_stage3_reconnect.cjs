// Stage 3 "重新接通" (backend-fixes-1127-0630 §3, §5). Runs the shipped connection module against an in-memory
// service that behaves like ConnectionStore.record: a known identity with any unused key returns the saved record
// and writes nothing. No network, no browser.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');

const project = {project_ref:'project-r', project_id:'project-r', input_version:1, revision:7, brief_sha256:'a'.repeat(64)};
const profile = 'b'.repeat(64), saved = {connection_id:'c'.repeat(64), receipt_id:'original-key'};
const reason = 'stage3-planning-resource-unavailable';

function load(service) {
 const store = new Map();
 const app = {page:'workspace', stage:3, lang:'zh', el:{querySelector:() => null, contains:() => true}};
 const rt = {ref:project.project_ref, overview:{project:{...project}}, epoch:1, loading:false, busy:false, pending:null, controlHeld:false};
 const ctx = vm.createContext({
  rt, apps:[app], console, structuredClone, Set, Error, JSON, Object, Number, Array, String,
  crypto:{randomUUID:() => service.nextUuid()}, navigator:{locks:{request:async (_, __, fn) => fn({})}},
  sessionStorage:{getItem:key => store.get(key) ?? null, setItem:(k, v) => store.set(k, v), removeItem:k => store.delete(k)},
  canonicalReadonly:() => false, livePaint:() => {}, liveRecover:async () => {}, rl:zh => zh, rx:String,
  projectPath:(ref, tail) => `/api/projects/${ref}/${tail}`,
  liveRequest:async (p, body) => service.request(p, body), liveRefresh:async () => { service.refreshes++; },
  document:{addEventListener:(type, fn) => { if (type === 'click') ctx.clickHandler = fn; }}
 });
 vm.runInContext(fs.readFileSync(path.join(__dirname, 'v9-stage-connections.js'), 'utf8'), ctx);
 return ctx;
}

function service(initialStatus) {
 const s = {status:initialStatus, posts:[], actions:18, events:36, refreshes:0, uuids:0, keysSeen:new Set(),
  nextUuid() { return 'uuid-' + Math.floor(++s.uuids / 2); }, // each value comes twice: the page must still never reuse a key
  row() {
   return s.status === 'connected'
    ? {status:'connected', reason:null, profile_sha256:profile, ...saved}
    : {status:'unavailable', reason:s.reason ?? reason, profile_sha256:profile, connection_id:null, receipt_id:null};
  },
  async request(p, body) {
   if (p.endsWith('/overview')) return {project:{...project}};
   if (!p.endsWith('/connections')) throw Error('unexpected ' + p);
   if (body) {
    s.posts.push(structuredClone(body));
    if (s.keysSeen.has(body.key) || body.key === saved.receipt_id) throw Object.assign(Error('idempotency-payload-differs'), {status:409});
    s.keysSeen.add(body.key);
    s.status = 'connected'; // saved record returned; no action or event added
   }
   return {project_ref:project.project_ref, connections:{'stage3-planning':s.row()}, execution_authorized:false};
  }
 };
 return s;
}

async function view(ctx) {
 const v = {stage:'stage3-planning', epoch:1, basis:ctx.v9ConnectionBasis(project), row:null, error:''};
 ctx.v9ConnectionView = v;
 vm.runInContext('v9ConnectionView = this.v9ConnectionView', ctx);
 v.row = await ctx.v9ReadConnection(v);
 return v;
}

test('the button appears only for an unavailable Stage 3 registration with the lost-lease reason', async () => {
 const s = service('unavailable'), ctx = load(s);
 assert.equal(ctx.v9ConnectionAction(await view(ctx)), 'reconnect');
 for (const other of ['stage3-planning-profile-unavailable', 'stage3-current-selection-required', 'something-else']) {
  s.reason = other;
  assert.equal(ctx.v9ConnectionAction(await view(ctx)), null, other);
 }
 s.reason = reason;
 const stage2 = await view(ctx);
 stage2.stage = 'stage2-controller';
 assert.equal(ctx.v9ConnectionAction(stage2), null, 'Stage 2 rows never get it');
 s.status = 'connected';
 assert.equal(ctx.v9ConnectionAction(await view(ctx)), null, 'nothing to do once connected');
 assert.match(ctx.v9ConnectionReason(reason), /Stage 3 的规划登记已保存；如果上次是强行关闭，这次启动后会先显示『未接通』，点『重新接通』即可恢复，不会重复执行任何步骤，也不会新增记录。/);
});

test('every reconnect uses a key never used before, even if the random source repeats', () => {
 const ctx = load(service('unavailable'));
 const keys = Array.from({length:6}, () => ctx.v9ReconnectKey());
 assert.equal(new Set(keys).size, keys.length);
});

test('one click sends one write with the current binding, verifies the saved record and keeps no pending marker', async () => {
 const s = service('unavailable'), ctx = load(s);
 const v = await view(ctx);
 await ctx.v9ReconnectStage(v);
 assert.equal(s.posts.length, 1);
 const body = s.posts[0];
 assert.deepEqual(Object.keys(body).sort(), ['brief_sha256', 'confirmed', 'input_version', 'key', 'profile_sha256', 'revision', 'stage']);
 assert.equal(body.stage, 'stage3-planning');
 assert.equal(body.profile_sha256, profile);
 assert.equal(body.revision, project.revision);
 assert.notEqual(body.key, saved.receipt_id);
 assert.equal(ctx.rt.pending, null, 'no unknown-outcome marker: the service writes nothing new');
 assert.equal(ctx.rt.busy, false);
 assert.equal(s.refreshes, 1, 'reads the project again afterwards');
 assert.equal(s.status, 'connected');
 // A second reconnect (another restart) again uses a fresh key.
 s.status = 'unavailable';
 const again = await view(ctx);
 await ctx.v9ReconnectStage(again);
 assert.equal(s.posts.length, 2);
 assert.notEqual(s.posts[1].key, s.posts[0].key);
});

test('a reply that is not the saved record is refused', async () => {
 const s = service('unavailable'), ctx = load(s);
 const v = await view(ctx);
 const original = s.request;
 s.request = async (p, body) => body ? {project_ref:project.project_ref, connections:{'stage3-planning':{status:'connected', reason:null, profile_sha256:profile, connection_id:'not-a-hash', receipt_id:'x'}}, execution_authorized:false} : original(p, body);
 await assert.rejects(() => ctx.v9ReconnectStage(v), /stage-connection-(response-invalid|receipt-unverified)/);
 assert.equal(ctx.rt.busy, false);
});

test('the Stage 3 connection block shows 重新接通 even though the selection read is unavailable while disconnected', () => {
 const source = fs.readFileSync(path.join(__dirname, 'wiki-stage3.js'), 'utf8');
 const start = source.indexOf('function wikiS3ConnectionLine(m) {'), end = source.indexOf('\n}\n', start) + 3;
 const ctx = vm.createContext({v93Identity:() => null, wikiS2ConnectionLine:() => ({tone:'idle', tag:'-', text:'Stage 2', buttons:[]})});
 vm.runInContext(source.slice(start, end), ctx);
 const line = ctx.wikiS3ConnectionLine({phase:'ready', unknown:false, connected:false, action:'reconnect', code:reason});
 assert.equal(line.tag, '未接通');
 assert.equal(line.buttons[0].attr, 'reconnect');
 assert.equal(line.buttons[0].label, '重新接通');
 assert.match(line.text, /^Stage 3 的规划登记已保存；如果上次是强行关闭/);
 assert.equal(ctx.wikiS3ConnectionLine({phase:'ready', unknown:false, connected:false, action:null, code:'x'}).tag, '缺正式选择');
});
