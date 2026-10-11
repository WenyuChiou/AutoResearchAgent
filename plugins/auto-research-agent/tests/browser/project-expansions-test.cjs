/* Actual standalone component with authored DOM observations. No browser,
 * HTTP, model, query, source acquisition or native process is started. */
'use strict';
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
class Element {
  constructor(tag) {this.tagName = tag; this.children = []; this.disabled = false; this.checked = false; this.ownText = '';}
  append(node) {this.children.push(node);}
  replaceChildren(...nodes) {this.children = nodes;}
  setAttribute(key, value) {this[key] = value;}
  set textContent(value) {this.ownText = value;}
  get textContent() {return this.ownText + this.children.map(node => node.textContent).join('\n');}
  set innerHTML(_) {throw Error('unsafe HTML sink');}
}
const all = (root, tag) => [root, ...root.children.flatMap(node => all(node))].filter(node => !tag || node.tagName === tag);
const forbidden = () => {throw Error('unexpected request or execution');};
const sandbox = {window: {}, document: {createElement: tag => new Element(tag)}, fetch: forbidden, XMLHttpRequest: forbidden};
vm.runInNewContext(fs.readFileSync(path.resolve(__dirname, '../../cli/research_workspace_native/web/projects-expansions.js'), 'utf8'), sandbox);
const ui = sandbox.window.ProjectExpansions, event = {preventDefault() {}};
const offer = (operation, suffix) => ({offer_ref: 'authored-' + suffix, offer_sha256: suffix.repeat(64), document: {
  work_id: 'authored-work', version_id: 'authored-version', title: '<source title 原文>', operation,
  backend: 'semantic-scholar', round_number: 1, reserved_seconds: 35, remaining_attempts: 2
}});
const auth = offer('references', 'a'), execution = offer('cited-by', 'b');
const value = {connected: true, authorization_offers: [auth], execution_offers: [execution], history: [{status: 'execution-unknown', operation: 'references', work_id: 'authored-old'}]};
const before = JSON.stringify(value);
async function main() {
  const titles = ['Trace the closest papers', '追踪最接近的论文', '追蹤最接近的論文'];
  for (const [index, language] of ['en', 'zh-Hans', 'zh-Hant'].entries()) {
    const root = new Element('div'), calls = [];
    ui.render(root, {value, language, blocked: false, onAction: (...args) => calls.push(args)});
    assert(root.textContent.includes(titles[index])); assert(root.textContent.includes(auth.document.title));
    assert(root.textContent.includes('execution-unknown')); assert.equal(calls.length, 0);
    assert.equal(all(root, 'button')[0].disabled, true); assert.equal(all(root, 'input')[0].checked, false);
    ui.render(root, {value, language, blocked: false, onAction: (...args) => calls.push(args)});
    assert.equal(calls.length, 0);
  }
  console.log('PASS 1: trilingual GET/render/refresh zero actions; original title and safe text');
  const root = new Element('div'), calls = [];
  let finish;
  const onAction = (action, item) => {calls.push([action, item]); return new Promise(resolve => {finish = resolve;});};
  ui.render(root, {value, language: 'en', blocked: false, onAction});
  let [authorize, execute] = all(root, 'button'), check = all(root, 'input')[0];
  await authorize.onclick(event); assert.equal(calls.length, 0);
  check.checked = true; check.onchange(); assert.equal(authorize.disabled, false);
  const pending = authorize.onclick(event); assert.equal(calls.length, 1); assert.equal(execute.disabled, true);
  await authorize.onclick(event); await execute.onclick(event); assert.equal(calls.length, 1);
  ui.render(root, {value, language: 'en', blocked: false, onAction});
  for (const button of all(root, 'button')) {assert.equal(button.disabled, true); await button.onclick(event);}
  assert.equal(calls.length, 1);
  finish(); await pending;
  assert.deepEqual(JSON.parse(JSON.stringify(calls[0])), ['expansion-authorize', auth]);
  ui.render(root, {value, language: 'en', blocked: false, onAction});
  [authorize, execute] = all(root, 'button'); check = all(root, 'input')[0];
  check.checked = true; check.onchange(); await authorize.onclick(event); assert.equal(calls.length, 1);
  assert.equal(authorize.disabled, true);
  console.log('PASS 2: explicit unchecked authorization; pending/double click/refresh held; exact offer');
  const executed = execute.onclick(event); assert.equal(calls.length, 2); finish(); await executed;
  assert.equal(calls[1][0], 'expansion-execute');
  assert.deepEqual(JSON.parse(JSON.stringify(calls[1][1])), execution);
  console.log('PASS 3: execution requires a distinct user click and exact saved offer');
  const blocked = new Element('div');
  ui.render(blocked, {value, language: 'en', blocked: true, onAction: forbidden});
  check = all(blocked, 'input')[0]; check.checked = true; check.onchange();
  for (const button of all(blocked, 'button')) {assert.equal(button.disabled, true); await button.onclick(event);}
  ui.render(blocked, {value, language: 'en', blocked: false, onAction: forbidden});
  const stale = all(blocked, 'button')[1]; ui.render(blocked, {value: {...value, connected: false}, blocked: false, onAction: forbidden});
  await stale.onclick(event); for (const button of all(blocked, 'button')) assert.equal(button.disabled, true);
  console.log('PASS 4: blocked/unconnected/stale rendered controls cannot dispatch');
  const lost = new Element('div'); let lostCalls = 0;
  const lostAction = () => {lostCalls++; throw Error('authored lost response');};
  ui.render(lost, {value, language: 'en', blocked: false, onAction: lostAction});
  check = all(lost, 'input')[0]; check.checked = true; check.onchange();
  await all(lost, 'button')[0].onclick(event); assert(lost.textContent.includes('response is unresolved'));
  ui.render(lost, {value, language: 'en', blocked: false, onAction: lostAction});
  await all(lost, 'button')[0].onclick(event); assert.equal(lostCalls, 1);
  console.log('PASS 5: lost response remains held; refresh does not resend');
  const invalid = new Element('div');
  ui.render(invalid, {value: {...value, authorization_offers: [{...auth, offer_sha256: 'bad'}, {...auth, document: {...auth.document, backend: 'openalex'}}], execution_offers: []}, blocked: false, onAction: forbidden});
  assert.equal(all(invalid, 'button').length, 0);
  ui.render(invalid, {value: {...value, authorization_offers: [{...auth, document: {...auth.document, remaining_attempts: 0}}], execution_offers: []}, blocked: false, onAction: forbidden});
  check = all(invalid, 'input')[0]; check.checked = true; check.onchange(); assert.equal(all(invalid, 'button')[0].disabled, true);
  console.log('PASS 6: invalid hash/backend and exhausted shared budget offer refuse actions');
  assert.equal(JSON.stringify(value), before); assert.equal(ui.render(null, {}), false);
  console.log('PASS 7: input observations unchanged; local UI evidence only');
}
main().catch(error => {console.error(error); process.exitCode = 1;});
