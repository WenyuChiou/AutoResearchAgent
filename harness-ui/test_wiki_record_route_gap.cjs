// Direct address #project-…?stage=2: the default Stage 1 page paints first. Its Harness record read must not go out
// in front of the Stage 2 read (the Stage 2 page never uses the Stage 1 record). Ordinary Stage 1 visits read at once.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');

function setup(route) {
 const requests = [], timers = [];
 const app = {lang:'zh', page:'workspace', stage:1, el:{querySelector: () => null, querySelectorAll: () => []}};
 const context = vm.createContext({
  esc: value => String(value), console, clearTimeout,
  setTimeout: (fn, ms) => { timers.push({fn, ms}); return timers.length; },
  rt: {ref:'project-aaa', list:[{project_ref:'project-aaa'}]}, apps: [app],
  v93RouteTarget: () => route,
  projectPath: (ref, tail) => '/api/projects/' + ref + '/' + tail,
  liveRequest: pathname => { requests.push(pathname); return new Promise(() => {}); }
 });
 vm.runInContext((fs.readFileSync(path.join(__dirname, 'wiki-v1-text.js'), 'utf8') + '\n' + fs.readFileSync(path.join(__dirname, 'wiki-harness-record.js'), 'utf8')) + '\nthis.__t = {wikiRecordBlock, wikiRecRouteDelayMs};', context);
 return {context, requests, timers, app};
}

test('a stage route naming another stage delays the Stage 1 read; applying the route drops it', () => {
 const run = setup({ref:'project-aaa', stage:2, lang:'zh'});
 const html = run.context.__t.wikiRecordBlock(1);
 assert.match(html, /读取中/, 'the block shows its loading line meanwhile');
 assert.equal(run.timers.length, 1);
 assert.equal(run.timers[0].ms, run.context.__t.wikiRecRouteDelayMs, 'the read is scheduled after the delay, not at once');
 assert.deepEqual(run.requests, [], 'nothing is sent while the route is pending');
});

test('without a route, or with the route on this very stage, the read goes out at once', () => {
 for (const route of [null, {ref:'project-aaa', stage:1, lang:'zh'}, {ref:'project-other', stage:2, lang:'zh'}]) {
  const run = setup(route);
  run.context.__t.wikiRecordBlock(1);
  assert.equal(run.timers[0].ms, 0, JSON.stringify(route));
 }
});
