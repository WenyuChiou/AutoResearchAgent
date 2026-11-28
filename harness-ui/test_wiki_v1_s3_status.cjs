// Wiki V1 Stage 3 status bar (wiki-v1.js, DESIGN 3.4 / 8.13): which line shows for each connection state.
// Runs only the Stage 3 status section of the shipped file. No network.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');

const textSource = fs.readFileSync(path.join(__dirname, 'wiki-v1-text.js'), 'utf8');
const source = fs.readFileSync(path.join(__dirname, 'wiki-v1.js'), 'utf8');
const start = source.indexOf('// ---------- Stage 3 status');
const section = source.slice(start, source.indexOf("\ndocument.addEventListener('click'", start));

function load(conn, {basis = null, view = null} = {}) {
 const ctx = vm.createContext({
  v1StageStatus:{}, v1PageStatus:{}, v93:{busy:false, basis, view, error:'', errorBasis:null},
  v93Identity:() => basis, v93Matches:(a, b) => !!a && !!b && a.project_ref === b.project_ref,
  v9ConnectionModel:() => conn
 });
 vm.runInContext(textSource, ctx);
 vm.runInContext(section, ctx);
 return ctx.v1PageStatus.s3({});
}
const ready = extra => ({phase:'ready', unknown:false, action:null, code:'', connected:false, ...extra});

test('connect, reconnect and other reasons keep their lines', () => {
 assert.match(load(ready({action:'connect'})).next, /接通本课题/);
 assert.equal(load(ready({action:'reconnect'})).you.text, '重新接通');
 assert.match(load(ready({code:'stage3-planning-profile-unavailable'})).now[1], /现在接不上/);
 assert.match(load(ready({code:'stage3-current-selection-required'})).now[1], /Stage 2 还没有选定方向/);
});

test('a launch with no Stage 3 interface is not told as "Stage 2 has no selection"', () => {
 const status = load(ready({stage2Only:true, stage2Reason:'stage2-controller-profile-unavailable'}));
 assert.match(status.now[1], /Stage 3 现在接不上/);
 assert.doesNotMatch(status.now.join(''), /还没有选定方向/);
});

test('connected without a selection read is not written as "cannot connect" (review P2-c)', () => {
 const status = load(ready({connected:true, code:'something-else'}));
 assert.doesNotMatch(status.now.join(''), /接不上/);
 assert.match(status.now[1], /Stage 3 已接通，但这次没有读到选定的方向/);
 assert.equal(status.button.attrs, 'data-v1-reload');
});

test('a saved plan asks for the decision', () => {
 const basis = {project_ref:'p'};
 assert.equal(load(ready({connected:true}), {basis, view:{project_ref:'p', plan:{}}}).you.text, '对计划做决定');
});

test('the topic menu closes on a click outside it or Escape, and stays open for clicks inside (review P2-d)', () => {
 const from = source.indexOf('// The toggle event comes a moment later');
 const part = source.slice(from, source.indexOf('// ---------- Stage 1 status', from));
 const menu = {open:true}, listeners = {doc:[], win:{}};
 const app = {v1SwitchOpen:true, el:{querySelector:() => menu}};
 const ctx = vm.createContext({apps:[app], rt:{ref:'p'},
  document:{addEventListener:(type, fn) => listeners.doc.push(fn)},
  window:{addEventListener:(type, fn) => { listeners.win[type] = fn; }}});
 vm.runInContext(part, ctx);
 const inside = {closest:sel => sel.includes('data-v1-switch') ? {} : null};
 const outside = {closest:() => null};
 listeners.win.click({target:inside});
 assert.equal(app.v1SwitchOpen, true, 'a click inside the menu keeps it');
 listeners.win.click({target:outside});
 assert.equal(app.v1SwitchOpen, false);
 assert.equal(menu.open, false);
 app.v1SwitchOpen = true; menu.open = true;
 listeners.win.keydown({key:'Escape'});
 assert.equal(app.v1SwitchOpen, false);
 assert.equal(menu.open, false);
});
