// Nested cards (review 1128, P1-1 follow-up): each card answers only for its own text. A fallback marker inside an inner
// card root greys the inner card's controls and nothing of the outer card; a marker in the outer card's own text greys
// the outer controls and leaves the inner card alone. Events follow the same nearest-card rule. A small tree fake stands
// in for the DOM (cloneNode, querySelectorAll, closest, insertAdjacentHTML). No network.
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const TEXT = fs.readFileSync(path.join(__dirname, 'wiki-v1-text.js'), 'utf8');
const MARK = '⁠';

class Fake {
 constructor(tag, attrs = {}, kids = []) { this.tagName = tag.toUpperCase(); this.attrs = {...attrs}; this.children = []; this.parent = null; this.dataset = {}; this.disabled = false; kids.forEach(k => this.add(k)); }
 add(kid) { if (typeof kid !== 'string') kid.parent = this; this.children.push(kid); return this; }
 hasAttribute(name) { return Object.hasOwn(this.attrs, name) || (name === 'data-v1-gate-note' && this.attrs['data-v1-gate-note'] !== undefined); }
 get outerHTML() { return `<${this.tagName.toLowerCase()}${Object.keys(this.attrs).map(k => ' ' + k).join('')}>${this.children.map(c => typeof c === 'string' ? c : c.outerHTML).join('')}</${this.tagName.toLowerCase()}>`; }
 all() { return this.children.flatMap(c => typeof c === 'string' ? [] : [c, ...c.all()]); }
 querySelectorAll(selector) { const name = selector.replace(/^\[|\]$/g, ''); return this.all().filter(n => n.hasAttribute(name)); }
 cloneNode() { const copy = new Fake(this.tagName, this.attrs); this.children.forEach(c => copy.add(typeof c === 'string' ? c : c.cloneNode(true))); return copy; }
 remove() { this.parent.children = this.parent.children.filter(c => c !== this); }
 closest(selector) {
  const ok = n => selector.startsWith('[data-v1-write]') ? n.hasAttribute('data-v1-write') : selector === '[data-v1-card]' ? n.hasAttribute('data-v1-card')
   : selector === 'section' ? n.tagName === 'SECTION' : selector === '[data-v1-gated]' ? n.dataset.v1Gated === '1' : false;
  for (let n = this; n; n = n.parent) if (ok(n)) return n;
  return null;
 }
 insertAdjacentHTML(where, html) { const note = new Fake('p', {'data-v1-gate-note': ''}, [html]); note.parent = this; this.children.unshift(note); }
 composedPath() { const p = []; for (let n = this; n; n = n.parent) p.push(n); return p; }
}

function scenario({markIn = false, markOut = false}) {
 const handlers = [];
 const context = vm.createContext({apps: [{lang: 'en'}], console: {warn() {}}, window: {addEventListener: (type, fn) => handlers.push({type, fn})}});
 vm.runInContext(TEXT, context);
 const buttonIn = new Fake('button', {'data-v1-write': ''}, ['Save coverage' + (markIn ? MARK : '')]);
 const inner = new Fake('details', {'data-v1-card': ''}, ['Inner card text' + (markIn ? MARK : ''), buttonIn]);
 const buttonOut = new Fake('button', {'data-v1-write': ''}, ['Authorize']);
 const outer = new Fake('section', {'data-v1-card': ''}, ['Outer card text' + (markOut ? MARK : ''), inner, buttonOut]);
 const root = new Fake('div', {}, [outer]);
 vm.runInContext('v1GateCards', context)(root);
 const press = target => {
  let stopped = false;
  const event = {type: 'click', target, composedPath: () => target.composedPath(), preventDefault() {}, stopImmediatePropagation() { stopped = true; }};
  for (const h of handlers.filter(h => h.type === 'click')) { h.fn(event); if (stopped) break; }
  return !stopped; // true = the click reaches the control's own handler
 };
 const notes = card => card.children.filter(c => typeof c !== 'string' && c.hasAttribute('data-v1-gate-note')).length;
 return {inner, outer, buttonIn, buttonOut, reachedIn: press(buttonIn), reachedOut: press(buttonOut), notesIn: notes(inner), notesOut: notes(outer)};
}

test('a fallback inside the inner card greys only the inner card; the outer card stays open and has no note', () => {
 const r = scenario({markIn: true});
 assert.equal(r.buttonIn.disabled, true, 'inner button is grey');
 assert.equal(r.inner.dataset.v1Gated, '1');
 assert.equal(r.reachedIn, false, 'inner click is stopped');
 assert.equal(r.notesIn, 1, 'inner card has its note');
 assert.equal(r.outer.dataset.v1Gated, undefined, 'the outer card is not gated by the inner card text');
 assert.equal(r.buttonOut.disabled, false, 'outer button stays open');
 assert.equal(r.reachedOut, true, 'outer click reaches its handler');
 assert.equal(r.notesOut, 0, 'no note on the outer card');
});

test('a fallback in the outer card own text greys the outer card; the clean inner card is not affected', () => {
 const r = scenario({markOut: true});
 assert.equal(r.buttonOut.disabled, true, 'outer button is grey');
 assert.equal(r.outer.dataset.v1Gated, '1');
 assert.equal(r.reachedOut, false, 'outer click is stopped');
 assert.equal(r.notesOut, 1, 'outer card has its note');
 assert.equal(r.inner.dataset.v1Gated, undefined, 'the inner card is not gated');
 assert.equal(r.buttonIn.disabled, false, 'inner button stays open');
 assert.equal(r.reachedIn, true, 'a click in the clean inner card still reaches its handler');
 assert.equal(r.notesIn, 0);
});

test('both cards gated when both have a fallback; neither when clean', () => {
 const both = scenario({markIn: true, markOut: true});
 assert.ok(both.buttonIn.disabled && both.buttonOut.disabled && !both.reachedIn && !both.reachedOut);
 const clean = scenario({});
 assert.ok(!clean.buttonIn.disabled && !clean.buttonOut.disabled && clean.reachedIn && clean.reachedOut);
});
