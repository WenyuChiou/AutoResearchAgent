// Old (English / Traditional Chinese) page: the project dropdown leads with the topic, not the raw project reference, and
// neighbouring pieces of text keep a space between them (acceptance S-1: 「Progress & feedbackAwaiting…」, 「2Planningrequired」).
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const runtime = fs.readFileSync(path.join(__dirname, 'renderer/src/runtime.js'), 'utf8');
const start = runtime.indexOf('function liveProjectLabel(p)'), end = runtime.indexOf('\n}', start) + 2;
const ctx = vm.createContext({rl:(zh, en) => en, rt:{list:[]}});
vm.runInContext(runtime.slice(start, end), ctx);
const label = ctx.liveProjectLabel({project_ref:'project-a92053179e0f4b0c', input_version:1, topic:'退休后家庭消费如何变化'});
assert.equal(label, '退休后家庭消费如何变化 · Input version 1');
assert.ok(!label.includes('project-a92'), 'the raw reference is not in the label when there is a topic');
assert.equal(ctx.liveProjectLabel({project_ref:'project-b', input_version:2}), 'project-b · Input version 2', 'without a topic the reference is all there is');
// Look-alikes (same title, same input version) keep the reference so the options stay distinguishable.
const twins = [{project_ref:'project-t1', input_version:1, topic:'同名'}, {project_ref:'project-t2', input_version:1, topic:'同名'}, {project_ref:'project-t3', input_version:2, topic:'同名'}];
ctx.rt.list = twins;
assert.equal(ctx.liveProjectLabel(twins[0]), '同名 · Input version 1 · project-t1');
assert.equal(ctx.liveProjectLabel(twins[1]), '同名 · Input version 1 · project-t2');
assert.equal(ctx.liveProjectLabel(twins[2]), '同名 · Input version 2', 'a different version is already distinct');
for (const name of ['renderer/src/runtime.js', 'renderer/src/base.js']) {
 const text = fs.readFileSync(path.join(__dirname, name), 'utf8');
 assert.ok(!text.includes('</strong><small>'), name + ' glues a title and its note together');
}
assert.ok(!runtime.includes('</span><span><strong>${rx(phaseLabel'), 'step number and step name are separated');
assert.doesNotMatch(fs.readFileSync(path.join(__dirname, 'wiki-v1-global.js'), 'utf8'), /旧版界面，功能不全/, 'the language list no longer marks a language as the old interface');
console.log('PASS old page text.');
