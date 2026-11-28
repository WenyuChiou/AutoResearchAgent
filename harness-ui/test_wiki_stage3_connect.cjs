// Stage 3 connection block follows the /connections status (DESIGN 8.13 ladder). Regression: the selection check
// used to come first and read v93Identity(), which needs a connected Stage 3, so "接通本课题" never appeared.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, 'wiki-stage3.js'), 'utf8');
const start = source.indexOf('function wikiS3ConnectionLine(m) {'), end = source.indexOf('\n}\n', start) + 3;
const ctx = vm.createContext({
 v93Identity:() => null, // never available before Stage 3 is connected
 v9StaticStage3Read:() => false,
 wikiS2ConnectionLine:m => ({tone:'warn', tag:'shared', text:m.unknown ? '上次启用（或登记）的结果还没确认 Stage 2' : '核对不了 Stage 2', buttons:[{label:'重新读取', attr:'read'}]})
});
vm.runInContext(source.slice(start, end), ctx);
const line = m => ctx.wikiS3ConnectionLine({phase:'ready', unknown:false, connected:false, action:null, code:null, noLocks:false, ...m});

const connect = line({action:'connect'});
assert.equal(connect.tag, '可以接通', 'a connectable topic offers 接通本课题 even though the selection read is not available yet');
assert.equal(connect.buttons[0].attr, 'connect');
assert.equal(connect.buttons[0].label, '接通本课题');
assert.match(connect.text, /这个课题还没有接通 Stage 3。可以登记当前配置，登记不会启动研究/);

const missing = line({code:'stage3-current-selection-required'});
assert.equal(missing.tag, '缺正式选择');
assert.equal(missing.buttons[0].stage, 2);

assert.equal(line({code:'stage3-planning-profile-unavailable'}).tag, '缺运行配置');
assert.equal(line({connected:true}).tag, '已接通');
const unknown = line({unknown:true, action:'connect'});
assert.equal(unknown.tag, 'shared', 'an unconfirmed earlier submit is checked first, no new connect');
assert.match(unknown.text, /Stage 3/);
assert.doesNotMatch(unknown.text, /Stage 2/);
assert.equal(line({noLocks:true, action:'connect'}).tag, 'shared', 'without cross-tab locks it is view-only');
assert.equal(line({code:'something-else'}).text, '核对不了 Stage 3');

// Real reply of a launch with no Stage 3 interface and no Stage 2 selection (zero-quota copy): GET /connections carries
// only the stage2-controller row (unavailable, stage2-controller-profile-unavailable). The page used to fall through
// to the generic 「核对不了」; it now names the missing run configuration (or the missing interface).
const noS2 = line({stage2Only:true, stage2Reason:'stage2-controller-profile-unavailable'});
assert.equal(noS2.tag, '缺运行配置', 'Stage 2 row without a run configuration is written as a missing configuration');
assert.equal(noS2.buttons[0].page, 'settings');
assert.doesNotMatch(noS2.text, /核对不了/);
const noIface = line({stage2Only:true, stage2Reason:'stage2-continuation-activation-required'});
assert.equal(noIface.tag, '没带接通功能');
assert.match(noIface.text, /Stage 3 的接通功能/);
assert.equal(line({stage2Only:true, stage2Reason:null}).tag, '没带接通功能');


console.log('PASS Stage 3 connection ladder: connectable shows 接通本课题, selection missing only on its own reason, profile, connected, unknown, view-only, other.');
