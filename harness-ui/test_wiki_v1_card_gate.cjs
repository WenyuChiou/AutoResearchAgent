// Cards that write (authorize, confirm, request, decide): when any text of a card fell back to Simplified Chinese in
// en/tw, the card's write buttons are disabled with a reason in the current language and click, Enter and submit send
// nothing. zh is never gated. A mutation (the gate always says ok) must make this test fail. No network.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const read = name => fs.readFileSync(path.join(__dirname, name), 'utf8');
const TEXT = read('wiki-v1-text.js');
const CARD_KEY = '创建 Stage 1 运行许可'; // a real label of the run-permit card
const OTHER_KEY = '确认范围并开始自动推进'; // a real label of the scope-confirmation card (batch 2)

// A card, its write button and an input, with only the DOM calls the gate uses.
function makeDom(html) {
 const card = {dataset: {}, outerHTML: html, notes: [],
  querySelector(selector) { return selector === '[data-v1-gate-note]' && this.notes.length ? this.notes[0] : null; },
  insertAdjacentHTML(where, markup) { this.outerHTML += markup; this.notes.push(markup); }};
 const hasMark = () => card.dataset.v1Gated === '1';
 const button = {disabled: false, dataset: {}, tagName: 'BUTTON',
  closest(selector) {
   if (selector === '[data-v1-card]') return null;
   if (selector === 'section') return card;
   if (selector === '[data-v1-gated]') return hasMark() ? card : null;
   if (selector.startsWith('[data-v1-write]')) return button;
   return null;
  }};
 const input = {dataset: {}, tagName: 'INPUT', closest(selector) { return selector === '[data-v1-gated]' && hasMark() ? card : selector.startsWith('[data-v1-write]') ? null : null; }};
 const root = {querySelectorAll: selector => selector === '[data-v1-write]' ? [button] : []};
 return {card, button, input, root};
}

// One scenario: language, optional missing translation -> what the person can do. posts counts requests sent.
function scenario(lang, {removeKey = null, source = TEXT} = {}) {
 const handlers = [];
 const apps = [{lang}];
 const context = vm.createContext({apps, console: {warn() {}}, window: {addEventListener: (type, fn, capture) => handlers.push({type, fn, capture})}});
 vm.runInContext(source + '\nthis.__t = {v1t, v1GateCards, v1GateEvent, v1CardGate, v1Text};', context);
 const t = context.__t;
 if (removeKey) t.v1Text[removeKey].en = '';
 const label = t.v1t(CARD_KEY);
 const dom = makeDom(`<section class="ws-card"><p>${t.v1t(OTHER_KEY)}</p><button data-v1-write>${label}</button></section>`);
 t.v1GateCards(dom.root);
 let posts = 0;
 // The card's own handlers run after the capture guard, as in the page.
 const ownHandler = () => { posts += 1; };
 const dispatch = event => {
  let stopped = false;
  event.preventDefault = () => {};
  event.stopImmediatePropagation = () => { stopped = true; };
  for (const h of handlers.filter(h => h.type === event.type)) { h.fn(event); if (stopped) return; }
  ownHandler(event);
 };
 dispatch({type: 'click', target: dom.button});
 dispatch({type: 'keydown', key: 'Enter', target: dom.button});
 dispatch({type: 'keydown', key: 'Enter', target: dom.input});
 dispatch({type: 'submit', target: dom.input});
 return {disabled: dom.button.disabled, gated: dom.card.dataset.v1Gated === '1', note: dom.card.notes[0] || '', posts, label};
}

// 1. Every translation present: the card is open in all three languages and the four events reach the card.
for (const lang of ['zh', 'en', 'tw']) {
 const r = scenario(lang);
 assert.equal(r.disabled, false, lang + ': a fully translated card stays open');
 assert.equal(r.gated, false);
 assert.equal(r.posts, 4, lang + ': events reach the card handler when not gated');
}

// 2. One English text of the card missing: en is gated, nothing is sent, the reason is in English. tw and zh are not.
{
 const r = scenario('en', {removeKey: CARD_KEY});
 assert.equal(r.disabled, true, 'the write button is disabled');
 assert.equal(r.gated, true);
 assert.match(r.note, /This text has no English version yet|no version in this language/i, 'the reason is written in the current language');
 assert.ok(!/[一-鿿]/.test(r.note), 'the reason is not Simplified Chinese');
 assert.equal(r.posts, 0, 'click, Enter and submit send nothing from a gated card');
 const tw = scenario('tw', {removeKey: CARD_KEY});
 assert.equal(tw.disabled, false, 'removing an English text does not gate the Traditional Chinese card');
 assert.equal(tw.posts, 4);
 // Simplified is never gated, even when the English entry is gone.
 const zh = scenario('zh', {removeKey: CARD_KEY});
 assert.equal(zh.disabled, false, 'zh is not affected');
 assert.equal(zh.gated, false);
 assert.equal(zh.posts, 4, 'zh still sends');
}

// 3. Traditional text missing gates the Traditional card with a Traditional reason.
{
 const handlers = [];
 const context = vm.createContext({apps: [{lang: 'tw'}], console: {warn() {}}, window: {addEventListener: (type, fn) => handlers.push({type, fn})}});
 vm.runInContext(TEXT + '\nthis.__t = {v1t, v1CardGate, v1Text};', context);
 context.__t.v1Text[CARD_KEY].tw = ' ';
 const gate = context.__t.v1CardGate('<section>' + context.__t.v1t(CARD_KEY) + '</section>');
 assert.equal(gate.ok, false);
 assert.match(gate.reason, /切換到簡體中文/);
 assert.equal(context.__t.v1CardGate('<section>' + context.__t.v1t(OTHER_KEY) + '</section>').ok, true);
}

// 4. Every key used by a card that writes has an English and a Traditional text (the table test covers the rest).
{
 const table = vm.runInContext(TEXT + '\nv1Text', vm.createContext({apps: [{lang: 'zh'}]}));
 const unescape = body => body.replace(/\\(.)/g, (m, c) => c === 'n' ? '\n' : c);
 const cardFiles = fs.readdirSync(__dirname).filter(n => /^wiki-.*\.js$/.test(n) && n !== 'wiki-v1-text.js' && read(n).includes('data-v1-write'));
 assert.ok(cardFiles.length >= 5, 'the write cards are in several modules: ' + cardFiles.join(', '));
 for (const file of cardFiles) {
  for (const m of read(file).matchAll(/v1t\('((?:[^'\\\n]|\\.)*)'/g)) {
   const key = unescape(m[1]);
   assert.ok(Object.hasOwn(table, key), `${file}: ${key} is in the table`);
   assert.ok(table[key].en.trim() && table[key].tw.trim(), `${file}: ${key} has en and tw`);
  }
 }
}

// 5. Mutation: a gate that always says ok must break this test (so the test really guards the behaviour).
{
 const mutated = TEXT.replace('function v1CardGate(markup) {', "function v1CardGate(markup) {\n return {ok:true, reason:''};");
 assert.notEqual(mutated, TEXT, 'the mutation applied');
 const r = scenario('en', {removeKey: CARD_KEY, source: mutated});
 assert.ok(r.disabled === false && r.posts > 0, 'with an always-ok gate the missing-text card still sends (the test above would fail)');
}
console.log('PASS Wiki V1 card gate: gated in en/tw on a fallback text, nothing sent by click/Enter/submit, zh unaffected, mutation caught.');
